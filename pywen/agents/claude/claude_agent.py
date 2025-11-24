import os
from typing import Dict, List, Optional, AsyncGenerator, Any
import datetime
import json
from pywen.agents.base_agent import BaseAgent
from pywen.llm.llm_client import LLMClient, LLMMessage
from pywen.utils.llm_basics import LLMResponse
from pywen.utils.tool_basics import ToolCall, ToolResult
from pywen.core.trajectory_recorder import TrajectoryRecorder
from .prompts import ClaudeCodePrompts
from .context_manager import ClaudeCodeContextManager
from pywen.core.session_stats import session_stats
from pywen.core.agent_registry import registry  as agent_registry
from pywen.config.manager import ConfigManager
from pywen.agents.claude.system_reminder import (
    generate_system_reminders, emit_reminder_event, reset_reminder_session,
    get_system_reminder_start,emit_tool_execution_event
)
from pywen.hooks.models import HookEvent
from pywen.core.tool_registry2 import list_tools_for_provider, get_tool

class ClaudeAgent(BaseAgent):

    def __init__(self, config, hook_mgr, cli_console = None):
        super().__init__(config, hook_mgr, cli_console)
        self.type = "ClaudeAgent"
        self.llm_client = LLMClient(self.config.active_model)
        self.prompts = ClaudeCodePrompts()
        self.project_path = os.getcwd()
        self.max_iterations = config.max_turns
        self.context_manager = ClaudeCodeContextManager(self.project_path)
        self.context = {}
        self.conversation_history: List[LLMMessage] = []
        trajectories_dir = ConfigManager.get_trajectories_dir()
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        trajectory_path = trajectories_dir / f"claude_trajectory_{timestamp}.json"
        self.trajectory_recorder = TrajectoryRecorder(trajectory_path)
        session_stats.set_current_agent(self.type)
        self.quota_checked = False
        self.todo_items = []
        reset_reminder_session()
        self.file_metrics = {}
        self.tools = self._setup_claude_code_tools()

    def _setup_claude_code_tools(self):
        # TODO. 急需重构工具适配器体系
        tools = []
        task_tool = get_tool('task_tool')
        task_tool.set_current_agent(self)
        tools.append(task_tool.build("claude"))
        architect_tool = get_tool('architect_tool')
        architect_tool.set_current_agent(self)
        tools.append(architect_tool.build("claude"))
        for tool in list_tools_for_provider("claude"):
            if tool.name != 'task_tool' and tool.name != 'architect_tool':
                tools.append(tool.build("claude"))
        return tools

    def _build_messages(self, messages: List[LLMMessage]) -> List[Dict[str, Any]]:
        msgs: List[Dict[str, Any]] = []
        for m in messages:
            one: Dict[str, Any] = {"role": m.role}
            if m.content is not None:
                one["content"] = m.content
            if hasattr(m, 'tool_call_id') and m.tool_call_id:
                one["tool_call_id"] = m.tool_call_id
            if hasattr(m, 'tool_calls') and m.tool_calls:
                one["tool_calls"] = []
                for tc in m.tool_calls:
                    payload: Dict[str, Any] = {
                        "call_id": getattr(tc, "call_id", None),
                        "name": getattr(tc, "name", None),
                    }
                    args = getattr(tc, "arguments", None)
                    if args is not None:
                        payload["arguments"] = args
                    inp = getattr(tc, "input", None)
                    if inp is not None:
                        payload["input"] = inp
                    one["tool_calls"].append(payload)
            msgs.append(one)
        return msgs

    def _build_system_prompt(self) -> str:
        return ""

    def _build_claude_messages(self) -> List[LLMMessage]:
        """构建系统提示词，拼接动态信息"""
        messages = []

        messages.append(LLMMessage(
            role="system",
            content=self.prompts.get_system_identity()
        ))

        workflow_content = self.prompts.get_system_workflow()
        env_info = self.prompts.get_env_info(self.project_path)
        workflow_with_env = f"{workflow_content}\n\n{env_info}"

        messages.append(LLMMessage(
            role="system",
            content=workflow_with_env
        ))

        messages.append(LLMMessage(
            role="user",
            content=get_system_reminder_start()
        ))

        for msg in self.conversation_history[:-1]:
            messages.append(msg)

        if self.conversation_history:
            messages.append(self.conversation_history[-1])

        has_context = bool(self.context and len(self.conversation_history) > 1)
        dynamic_reminders = generate_system_reminders(
            has_context=has_context,
            agent_id=self.type,
            todo_items=self.todo_items
        )
        
        for reminder in dynamic_reminders:
            reminder_message = LLMMessage(
                role="user",
                content=reminder.content
            )
            messages.append(reminder_message)
            self.conversation_history.append(reminder_message)

        return messages


    def _update_context(self):
        try:
            self.context = self.context_manager.get_context()

            additional_context = self.prompts.build_context(self.project_path)
            self.context.update(additional_context)

        except Exception as e:
            if self.cli_console:
                self.cli_console.print(f"Failed to build context: {e}", "yellow")
            self.context = {'project_path': self.project_path}

    def reset_conversation(self):
        self.conversation_history.clear()
        if self.cli_console:
            self.cli_console.print("Conversation history cleared", "green")

    async def run(self, user_message: str, **kwargs) -> AsyncGenerator[Dict[str, Any], None]:
        try:
            agent_registry.switch_to(self)
            self.trajectory_recorder.start_recording(
                task=user_message,
                provider=self.config.active_model.provider or "anthropic",
                model=self.config.active_model.model or "claude-3",
                max_steps=self.max_iterations
            )

            session_stats.record_task_start(self.type)

            yield {"type": "user_message", "data": {"message": user_message}}

            # quota请求暂不发送，进行话题检查，但话题暂时无用，仅作对齐处理
            topic_info = await self._detect_new_topic(user_message)
            if topic_info and topic_info.get('isNewTopic'):
                yield {
                    "type": "new_topic_detected",
                    "data": {
                        "title": topic_info.get('title'),
                        "isNewTopic": topic_info.get('isNewTopic')
                    }
                }

            self._update_context()
            
            emit_reminder_event('session:startup', {
                'agentId': self.type,
                'messages': len(self.conversation_history),
                'timestamp': datetime.datetime.now().timestamp(),
                'context': self.context
            })

            llm_message = LLMMessage(role="user", content=user_message)
            self.conversation_history.append(llm_message)

            messages = self._build_claude_messages()

            async for event in self._query_recursive(messages, depth=0, **kwargs):
                yield event

        except Exception as e:
            yield {
                "type": "error",
                "data": {
                    "error": f"Agent error: {str(e)}"
                },
            }

    async def _check_quota(self) -> bool:
        try:
            quota_messages = [{"role": "user", "content": "quota"}]

            params = {"model": self.config.active_model.model}
            content = ""

            async for evt in self.llm_client.astream_response(quota_messages, **params):
                if evt.type == "output_text.delta":
                    content += evt.data
                elif evt.type == "completed":
                    break
                elif evt.type == "error":
                    if self.cli_console:
                        self.cli_console.print(f"Quota check error: {evt.data}", "yellow")
                    return False

            quota_llm_response = LLMResponse(
                content=content,
                model=self.config.active_model.model,
                finish_reason="stop",
                usage=None,
                tool_calls=[]
            )

            self.trajectory_recorder.record_llm_interaction(
                messages=[LLMMessage(role="user", content="quota")],
                response=quota_llm_response,
                provider=self.config.active_model.provider or "anthropic",
                model=self.config.active_model.model or "claude-3",
                tools=None,
                current_task="quota_check",
                agent_name="ClaudeAgent"
            )

            return bool(content)
        except Exception as e:
            if self.cli_console:
                self.cli_console.print(f"Quota check failed: {e}", "yellow")
            return False

    async def _detect_new_topic(self, user_input: str) -> Optional[Dict[str, Any]]:
        try:
            topic_messages = [
                {"role": "system", "content": self.prompts.get_check_new_topic_prompt()},
                {"role": "user", "content": user_input}
            ]

            params = {"model": self.config.active_model.model}
            content = ""

            async for evt in self.llm_client.astream_response(topic_messages, **params):
                if evt.type == "output_text.delta":
                    content += evt.data
                elif evt.type == "completed":
                    break
                elif evt.type == "error":
                    if self.cli_console:
                        self.cli_console.print(f"Topic detection error: {evt.data}", "yellow")
                    return None

            topic_llm_response = LLMResponse(
                content=content,
                model=self.config.active_model.model,
                finish_reason="stop",
                usage=None,
                tool_calls=[]
            )

            self.trajectory_recorder.record_llm_interaction(
                messages=[
                    LLMMessage(role="system", content=self.prompts.get_check_new_topic_prompt()),
                    LLMMessage(role="user", content=user_input)
                ],
                response=topic_llm_response,
                provider=self.config.active_model.provider or "anthropic",
                model=self.config.active_model.model or "claude-3",
                tools=None,
                current_task="topic_detection",
                agent_name="ClaudeAgent"
            )

            if content:
                try:
                    topic_info = json.loads(content.strip())
                    return topic_info
                except json.JSONDecodeError:
                    return None
            return None
        except Exception as e:
            if self.cli_console:
                self.cli_console.print(f"Topic detection failed: {e}", "yellow")
            return None  

    async def _query_recursive(
        self,
        messages: List[LLMMessage],
        depth: int = 0,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        try:
            if depth >= self.max_iterations:
                yield {
                    "type": "max_turns_reached",
                    "data": {
                        "max_iterations": self.max_iterations,
                        "current_depth": depth
                    }
                }
                return

            if kwargs.get('abort_signal') and kwargs['abort_signal'].is_set():
                yield {
                    "type": "error",
                    "data": {"error": "Operation was cancelled"}
                }
                return


            assistant_message, tool_calls, final_response = None, [], None
            async for response_event in self._get_assistant_response_streaming(messages, depth=depth, **kwargs):
                if response_event["type"] in ["llm_stream_start", "llm_chunk", "content"]:
                    yield response_event
                elif response_event["type"] == "assistant_response":
                    assistant_message = response_event["assistant_message"]
                    tool_calls = response_event["tool_calls"]
                    final_response = response_event.get("final_response")

            if assistant_message:
                self.conversation_history.append(assistant_message)

                llm_response = LLMResponse(
                    content=assistant_message.content or "",
                    tool_calls=[ToolCall(
                        call_id=tc.get("id", "unknown"),
                        name=tc.get("name", ""),
                        arguments=tc.get("arguments", {})
                    ) for tc in tool_calls] if tool_calls else None,
                    model=self.config.active_model.model,
                    finish_reason="stop",
                    usage=final_response.usage if final_response and hasattr(final_response, 'usage') else None
                )

                self.trajectory_recorder.record_llm_interaction(
                    messages=messages,
                    response=llm_response,
                    provider=self.config.active_model.provider or "anthropic",
                    model=self.config.active_model.model or "claude-3",
                    tools=self.tools,
                    current_task=f"Processing query at depth {depth}",
                    agent_name=self.type
                )


            if not tool_calls:

                if final_response and hasattr(final_response, 'usage') and final_response.usage:
                    yield {"type": "turn_token_usage", "data": final_response.usage.total_tokens}
                yield {
                    "type": "task_complete",
                    "content": assistant_message.content if assistant_message else "",
                    
                }

                return

            for tool_call in tool_calls:
                yield {
                    "type": "tool_call_start",
                    "data": {
                        "call_id": tool_call.get("id", "unknown"),
                        "name": tool_call["name"],
                        "arguments": tool_call.get("arguments", {})
                    }
                }

            tool_results = []
            async for tool_event in self._execute_tools(tool_calls, **kwargs):
                yield tool_event
                
                if tool_event["type"] == "tool_results":
                    tool_results = tool_event["results"]

            if kwargs.get('abort_signal') and kwargs['abort_signal'].is_set():
                yield {
                    "type": "error",
                    "data": {"error": "Operation was cancelled during tool execution"}
                }
                return

            for tool_result in tool_results:
                self.conversation_history.append(tool_result)

            #构建下一轮提示词
            has_context = bool(self.context and len(self.conversation_history) > 1)
            new_dynamic_reminders = generate_system_reminders(
                has_context=has_context,
                agent_id=self.type,
                todo_items=self.todo_items
            )
            
            for reminder in new_dynamic_reminders:
                reminder_message = LLMMessage(
                    role="user",
                    content=reminder.content
                )
                self.conversation_history.append(reminder_message)
            
            updated_messages = [
                LLMMessage(role="system", content=self.prompts.get_system_identity()),
                LLMMessage(role="system", content=f"{self.prompts.get_system_workflow()}\n\n{self.prompts.get_env_info(self.project_path)}"),
                LLMMessage(role="system", content=get_system_reminder_start())
            ] + self.conversation_history.copy()

            async for event in self._query_recursive(updated_messages, depth=depth+1, **kwargs):
                yield event

        except Exception as e:
            yield {
                "type": "error",
                "data":{"error": f"Query error: {str(e)}"},
            }

    async def _get_assistant_response_streaming(
        self,
        messages: List[LLMMessage],
        depth: int = 0,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        try:
            if kwargs.get('abort_signal') and kwargs['abort_signal'].is_set():
                yield {
                    "type": "error",
                    "data": {"error": "Operation was cancelled"}
                }
                return

            formatted_messages = self._build_messages(messages)

            params = {
                "model": self.config.active_model.model,
                "tools": self.tools,
                "max_tokens": 4096
            }

            yield {
                "type": "llm_stream_start",
                "data": {"depth": depth}
            }

            assistant_content = ""
            collected_tool_calls = []
            current_tool_call = None
            tool_json_buffer = ""
            usage_data = None

            async for evt in self.llm_client.astream_response(formatted_messages, **params):
                if evt.type == "output_text.delta":
                    yield {
                        "type": "llm_chunk",
                        "data": {"content": evt.data}
                    }
                    assistant_content += evt.data

                elif evt.type == "content_block_start":
                    block_data = evt.data
                    if block_data.get("block_type") == "tool_use":
                        current_tool_call = {
                            "call_id": block_data.get("call_id"),
                            "name": block_data.get("name"),
                        }
                        tool_json_buffer = ""

                elif evt.type == "tool_call.delta_json":
                    if current_tool_call:
                        tool_json_buffer += evt.data

                elif evt.type == "content_block_stop":
                    if current_tool_call:
                        try:
                            tool_args = json.loads(tool_json_buffer) if tool_json_buffer else {}
                        except json.JSONDecodeError:
                            tool_args = {}

                        tc = ToolCall(
                            call_id=current_tool_call["call_id"],
                            name=current_tool_call["name"],
                            arguments=tool_args,
                            type="function",
                        )
                        collected_tool_calls.append(tc)
                        current_tool_call = None
                        tool_json_buffer = ""

                elif evt.type == "message_delta":
                    if evt.data and "usage" in evt.data:
                        usage_data = evt.data["usage"]

                elif evt.type == "completed":
                    break

                elif evt.type == "error":
                    yield {
                        "type": "error",
                        "data": {"error": str(evt.data)}
                    }
                    return

            assistant_msg = LLMMessage(
                role="assistant",
                content=assistant_content,
                tool_calls=collected_tool_calls if collected_tool_calls else None
            )

            tool_calls = []
            if collected_tool_calls:
                for tc in collected_tool_calls:
                    tool_calls.append({
                        "id": tc.call_id,
                        "name": tc.name,
                        "arguments": tc.arguments
                    })

            usage_obj = None
            if usage_data:
                input_tokens = usage_data.get('input_tokens', 0)
                output_tokens = usage_data.get('output_tokens', 0)

                usage_attrs = {
                    'input_tokens': input_tokens,
                    'output_tokens': output_tokens,
                    'total_tokens': input_tokens + output_tokens
                }
                usage_obj = type('obj', (object,), usage_attrs)()

            final_response = type('obj', (object,), {
                'usage': usage_obj,
                'content': assistant_content,
                'tool_calls': collected_tool_calls
            })()

            yield {
                "type": "assistant_response",
                "assistant_message": assistant_msg,
                "tool_calls": tool_calls,
                "final_response": final_response
            }

        except Exception as e:
            yield {
                "type": "error",
                "data": {"error": f"Streaming failed: {str(e)}"}
            }

    async def _execute_tools(
        self,
        tool_calls: List[Dict[str, Any]],
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        if not tool_calls:
            yield {
                "type": "tool_results",
                "results": []
            }
            return

        tool_results = []
        for tool_call in tool_calls:
            try:
                yield {
                    "type": "tool_start",
                    "data": {
                        "call_id": tool_call.get("id", "unknown"),
                        "name": tool_call["name"],
                        "arguments": tool_call.get("arguments", {})
                    }
                }

                tool_result, llm_message = await self._execute_single_tool_with_result(tool_call, **kwargs)

                yield {
                    "type": "tool_result",
                    "data": {
                        "call_id": tool_call.get("id", "unknown"),
                        "name": tool_call["name"],
                        "arguments": tool_call.get("arguments", {}),
                        "result": tool_result.result if tool_result.success and isinstance(tool_result.result, dict) else str(tool_result.result or tool_result.error),
                        "success": tool_result.success
                    }
                }

                tool_results.append(llm_message)

                if kwargs.get('abort_signal') and kwargs['abort_signal'].is_set():
                    break

            except Exception as e:
                error_msg = f"Error executing tool '{tool_call['name']}': {str(e)}"
                error_message = LLMMessage(
                    role="tool",
                    content=f"Error: {error_msg}",
                    tool_call_id=tool_call.get("id", "unknown")
                )

                yield {
                    "type": "tool_error",
                    "data": {
                        "call_id": tool_call.get("id", "unknown"),
                        "name": tool_call["name"],
                        "error": error_msg,
                        "success": False
                    }
                }

                tool_results.append(error_message)

        yield {
            "type": "tool_results",
            "results": tool_results
        }



    async def _execute_single_tool_with_result(
        self,
        tool_call: Dict[str, Any],
        **kwargs
    ) -> tuple[ToolResult, LLMMessage]:
        try:
            if kwargs.get('abort_signal') and kwargs['abort_signal'].is_set():
                cancelled_result = ToolResult(
                    call_id=tool_call.get("id", "unknown"),
                    error="Operation was cancelled",
                )
                cancelled_message = LLMMessage(
                    role="tool",
                    content="Operation was cancelled",
                    tool_call_id=tool_call.get("id", "unknown")
                )
                return cancelled_result, cancelled_message

            tool_call_obj = ToolCall(
                call_id=tool_call.get("id", "unknown"),
                name=tool_call["name"],
                arguments=tool_call.get("arguments", {})
            )
            if self.hook_mgr:
                pre_ok, pre_msg, _ = await self.hook_mgr.emit(
                    HookEvent.PreToolUse,
                    base_payload={
                        "session_id": getattr(self.config, "session_id", ""),
                    },
                    tool_name=tool_call_obj.name,
                    tool_input=dict(tool_call_obj.arguments or {}),
                )
                if pre_msg and self.cli_console:
                    self.cli_console.print(pre_msg, "yellow")
                if not pre_ok:
                    blocked_reason = pre_msg or "Tool call blocked by PreToolUse hook"
                    blocked_result = ToolResult(
                        call_id=tool_call_obj.call_id,
                        error=blocked_reason,
                    )
                    blocked_message = LLMMessage(
                        role="tool",
                        content=f"Blocked: {blocked_reason}",
                        tool_call_id=tool_call_obj.call_id,
                    )
                    return blocked_result, blocked_message

            tool = get_tool(tool_call["name"])
            if not tool:
                raise ValueError(f"Tool '{tool_call['name']}' not found")
            confirmation_details = await tool.get_confirmation_details(**tool_call.get("arguments", {}))
            if confirmation_details:
                confirmed = await self.cli_console.confirm_tool_call(tool_call_obj, tool)
                if not confirmed:
                    cancelled_result = ToolResult(
                        call_id=tool_call.get("id", "unknown"),
                        error="Tool execution was cancelled by user",
                    )
                    cancelled_message = LLMMessage(
                        role="tool",
                        content="Tool execution was cancelled by user",
                        tool_call_id=tool_call.get("id", "unknown")
                    )
                    return cancelled_result, cancelled_message

            tool_result = await tool.execute(**tool_call.get("arguments", {}))
            
            # 发送工具执行事件并更新 TODO 状态
            new_todos = emit_tool_execution_event(tool_call_obj, self.type, self.todo_items)
            if new_todos is not None:
                self.todo_items = new_todos

            if self.hook_mgr:
                post_ok, post_msg, post_extra = await self.hook_mgr.emit(
                    HookEvent.PostToolUse,
                    base_payload={
                        "session_id": getattr(self.config, "session_id", ""),
                    },
                    tool_name=tool_call_obj.name,
                    tool_input=dict(tool_call_obj.arguments or {}),
                    tool_response={
                        "result": tool_result.result,
                        "success": tool_result.success,
                        "error": tool_result.error,
                    },
                )
                if post_msg and self.cli_console:
                    self.cli_console.print(post_msg, "yellow")
                if post_extra.get("additionalContext"):
                    self.conversation_history.append(LLMMessage(
                        role="system",
                        content=post_extra["additionalContext"]
                    ))
                if not post_ok:
                    reason = post_msg or "PostToolUse hook blocked further processing"
                    tool_result.error = reason
                    tool_result.result = None

            if tool_result.success:
                if isinstance(tool_result.result, dict):
                    operation = tool_result.result.get('operation', '')
                    file_path = tool_result.result.get('file_path', '')

                    if operation == 'edit_file':
                        old_text = tool_result.result.get('old_text', '')
                        new_text = tool_result.result.get('new_text', '')
                        content = f"SUCCESS: File {file_path} edited successfully. Changed '{old_text}' to '{new_text}'. Task completed."
                    elif operation == 'write_file':
                        content = f"SUCCESS: File {file_path} written successfully. Task completed."
                    else:
                        content = tool_result.result.get('summary', str(tool_result.result))
                else:
                    content = str(tool_result.result) if tool_result.result is not None else "Operation completed successfully"
            else:
                content = f"Error: {tool_result.error}" if tool_result.error else "Tool execution failed"

            llm_message = LLMMessage(
                role="tool",
                content=content,
                tool_call_id=tool_call.get("id", "unknown")
            )

            return tool_result, llm_message

        except Exception as e:
            error_msg = f"Error executing tool '{tool_call['name']}': {str(e)}"
            error_result = ToolResult(
                call_id=tool_call.get("id", "unknown"),
                error=error_msg,
            )
            error_message = LLMMessage(
                role="tool",
                content=f"Error: {error_msg}",
                tool_call_id=tool_call.get("id", "unknown")
            )
            return error_result, error_message
