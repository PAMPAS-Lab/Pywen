import os
import datetime
import json
from typing import Dict, List, Optional, AsyncGenerator, Any
from pywen.agents.base_agent import BaseAgent
from pywen.llm.llm_basics import LLMResponse, LLMMessage, ToolCall, ToolCallResult
from pywen.llm.llm_events import LLM_Events
from pywen.utils.trajectory_recorder import TrajectoryRecorder
from pywen.utils.session_stats import session_stats
from pywen.config.token_limits import TokenLimits
from pywen.config.manager import ConfigManager
from pywen.agents.agent_events import AgentEvent, Agent_Events
from pywen.agents.claude.system_reminder import (
        generate_system_reminders, emit_reminder_event, reset_reminder_session,
        get_system_reminder_start,emit_tool_execution_event
        )
from .prompts import ClaudeCodePrompts
from .context_manager import ClaudeCodeContextManager

class ClaudeAgent(BaseAgent):
    def __init__(self, config_mgr:ConfigManager, cli, tool_mgr):
        super().__init__(config_mgr, cli, tool_mgr)
        self.type = "ClaudeAgent"
        self.prompts = ClaudeCodePrompts()
        self.project_path = os.getcwd()
        self.max_iterations = config_mgr.get_app_config().max_turns
        self.context_manager = ClaudeCodeContextManager(self.project_path)
        self.context = {}
        self.conversation_history: List[LLMMessage] = []
        trajectories_dir = config_mgr.get_trajectories_dir()
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        trajectory_path = trajectories_dir / f"claude_trajectory_{timestamp}.json"
        self.trajectory_recorder = TrajectoryRecorder(trajectory_path)
        session_stats.set_current_agent(self.type)
        self.quota_checked = False
        self.todo_items = []
        reset_reminder_session()
        self.file_metrics = {}
        self._setup_claude_code_tools()

    def create_sub_agent(self) -> 'ClaudeAgent':
        sub_agent = ClaudeAgent(self.config_mgr, self.cli, self.tool_mgr)
        sub_agent.project_path = self.project_path
        sub_agent.context = self.context.copy()
        sub_agent.file_metrics = self.file_metrics.copy()
        return sub_agent

    async def run(self, user_message: str) -> AsyncGenerator[AgentEvent, None]:
        try:
            agent_config = self.config_mgr.get_active_agent()
            model_name = self.config_mgr.get_active_model_name() or "claude-4"
            max_tokens = TokenLimits.get_limit("anthropic", model_name)
            self.cli.set_max_context_tokens(max_tokens)
            self.trajectory_recorder.start_recording(
                    task=user_message,
                    provider=agent_config.provider or "anthropic",
                    model=model_name,
                    max_steps=self.max_iterations
            )
            session_stats.record_task_start(self.type)
            yield AgentEvent.user_message(user_message)

            # quota请求暂不发送，进行话题检查，但话题暂时无用，仅作对齐处理
            """
            topic_info = await self._detect_new_topic(user_message)
            if topic_info and topic_info.get('isNewTopic'):
                title = topic_info.get('title', 'New Topic')
                isnew = topic_info.get('isNewTopic', False)
                item = {"type": "new_topic", "title": title, "isNewTopic": isnew}
                yield AgentEvent.user_defined(item)
            """
            self._update_context()

            emit_reminder_event('session:startup', {
                'agentId': self.type,
                'messages': len(self.conversation_history),
                'timestamp': datetime.datetime.now().timestamp(),
                'context': self.context
                }
            )

            llm_message = LLMMessage(role="user", content=user_message)
            self.conversation_history.append(llm_message)
            messages = self._build_claude_messages()
            async for event in self._query_recursive(messages, depth=0):
                yield event

        except Exception as e:
            yield AgentEvent.error(f"Agent error: {str(e)}")

    def _setup_claude_code_tools(self, except_tools: Optional[List[str]] = None) -> List[Any]:
        self.tools = []
        exclude = set(except_tools or [])
        for tool in self.tool_mgr.list_for_provider("claude"):
            if tool.name in exclude:
                continue
            self.tools.append(tool.build("claude"))
        return self.tools

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
        messages.append(LLMMessage(role="system", content=workflow_with_env))
        messages.append(LLMMessage(role="system", content= self.prompts.get_claude_md_prompt()))
        messages.append(LLMMessage(role="user", content=get_system_reminder_start() ))
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
            reminder_message = LLMMessage(role="user", content=reminder.content)
            messages.append(reminder_message)
            self.conversation_history.append(reminder_message)

        return messages

    def _update_context(self):
        try:
            self.context = self.context_manager.get_context()
            additional_context = self.prompts.build_context(self.project_path)
            self.context.update(additional_context)
        except Exception as e:
            self.context = {'project_path': self.project_path}

    def reset_conversation(self):
        self.conversation_history.clear()

    async def _check_quota(self) -> bool:
        try:
            model_name = self.config_mgr.get_active_model_name() or "claude-4"
            quota_messages = [{"role": "user", "content": "quota"}]
            params = {"model": model_name, "max_tokens": 4096,}
            content = ""

            async for event in self.llm_client.astream_response(quota_messages, **params):
                if event.type == LLM_Events.ASSISTANT_DELTA:
                    content += event.data or ""
                elif event.type == LLM_Events.RESPONSE_FINISHED:
                    break
                elif event.type == LLM_Events.ERROR:
                    return False

            quota_llm_response = LLMResponse(content, model=model_name, finish_reason="stop", usage=None, tool_calls=[])

            self.trajectory_recorder.record_llm_interaction(
                    messages=[LLMMessage(role="user", content="quota")],
                    response=quota_llm_response,
                    provider=self.config_mgr.get_active_agent().provider or "anthropic",
                    model= model_name,
                    tools=None,
                    current_task="quota_check",
                    agent_name="ClaudeAgent"
                    )

            return bool(content)
        except Exception as e:
            return False

    async def _detect_new_topic(self, user_input: str) -> Optional[Dict[str, Any]]:
        try:
            model_name = self.config_mgr.get_active_model_name() or "claude-4"
            topic_messages = [
                    {"role": "system", "content": self.prompts.get_check_new_topic_prompt()},
                    {"role": "user", "content": user_input}
            ]

            params = {"model": model_name, "max_tokens":4096}
            content = ""

            async for event in self.llm_client.astream_response(topic_messages, **params):
                if event.type == LLM_Events.ASSISTANT_DELTA:
                    content += event.data or ""
                elif event.type == LLM_Events.RESPONSE_FINISHED:
                    break
                elif event.type == LLM_Events.ERROR:
                    return None

            topic_llm_response = LLMResponse(
                    content=content,
                    model= model_name,
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
                    provider= self.config_mgr.get_active_agent().provider or "anthropic",
                    model= model_name,
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
            return None  

    async def _query_recursive(self, messages: List[LLMMessage], depth: int = 0) -> AsyncGenerator[AgentEvent, None]:
        try:
            model_name = self.config_mgr.get_active_model_name() or "claude-4"
            if depth >= self.max_iterations:
                yield AgentEvent.turn_max_reached(self.max_iterations)
                return

            assistant_message, tool_calls, final_response = None, [], None
            async for event in self._get_assistant_response_streaming(messages, depth=depth):
                if event.type in [Agent_Events.LLM_STREAM_START, Agent_Events.TEXT_DELTA]:
                    yield event
                elif event.type == Agent_Events.ERROR:
                    # 将流式阶段的错误直接透传给上层，避免后续空响应误报
                    yield event
                    return
                elif event.type == Agent_Events.USER_DEFINED:
                    if event.data and event.data["type"] == "assistant_response":
                        assistant_message = event.data["assistant_message"]
                        tool_calls = event.data["tool_calls"]
                        final_response = event.data.get("final_response")
            if assistant_message:
                self.conversation_history.append(assistant_message)
                llm_response = LLMResponse(
                        content=assistant_message.content or "",
                        tool_calls=[ToolCall(call_id=tc.get("id", "unknown"), name=tc.get("name", ""), arguments=tc.get("arguments", {})) for tc in tool_calls] if tool_calls else None,
                        model= model_name,
                        finish_reason="stop",
                        usage=final_response.usage if final_response and hasattr(final_response, 'usage') else None
                        )

                self.trajectory_recorder.record_llm_interaction(
                        messages=messages,
                        response=llm_response,
                        provider=self.config_mgr.get_active_agent().provider or "anthropic",
                        model= model_name,
                        tools=self.tools,
                        current_task=f"Processing query at depth {depth}",
                        agent_name=self.type
                        )

            if not tool_calls:
                preview = assistant_message.content[:200] if assistant_message and assistant_message.content else ""
                # 如果没有工具调用且内容为空，视为异常，返回错误而不是直接完成
                if not preview:
                    yield AgentEvent.error("LLM returned empty response with no tool calls")
                    return
                if final_response and hasattr(final_response, 'usage') and final_response.usage:
                    yield AgentEvent.turn_token_usage(final_response.usage.total_tokens)
                yield AgentEvent.task_complete(assistant_message.content if assistant_message else "")
                return

            for tool_call in tool_calls:
                yield AgentEvent.tool_call(
                        call_id=tool_call.get("id", "unknown"),
                        name=tool_call["name"],
                        args=tool_call.get("arguments", {})
                        )

            tool_result_messages = []
            async for tool_event, llm_message in self._execute_tools(tool_calls):
                yield tool_event
                if llm_message:
                    tool_result_messages.append(llm_message)

            for msg in tool_result_messages:
                self.conversation_history.append(msg)

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

            tokens_used = sum(self.approx_token_count(m.content or "") for m in self.conversation_history)
            self.cli.set_current_tokens(tokens_used)
            async for event in self._query_recursive(updated_messages, depth=depth+1):
                yield event

        except Exception as e:
            yield AgentEvent.error(f"Query error: {str(e)}")

    async def _get_assistant_response_streaming(self, messages: List[LLMMessage], depth: int = 0, **kwargs ) -> AsyncGenerator[AgentEvent, None]:
        try:
            formatted_messages = self._build_messages(messages)
            active_agent = self.config_mgr.get_active_agent()
            params = {
                    "model": self.config_mgr.get_active_model_name(), 
                    "tools": self.tools,
                    "max_tokens": self.config_mgr.get_active_model_max_tokens(),
            }
            yield AgentEvent.llm_stream_start({"depth": depth})

            assistant_content = ""
            collected_tool_calls = []
            usage_data = None

            async for event in self.llm_client.astream_response(formatted_messages, **params):
                if event.type == LLM_Events.ASSISTANT_DELTA:
                    assistant_content += event.data or ""
                    yield AgentEvent.text_delta(event.data or "")
                elif event.type == LLM_Events.TOOL_CALL_READY:
                    tool_call = event.data
                    tc = ToolCall(
                                call_id= tool_call.get("call_id") if tool_call else "unknown",
                                name= tool_call.get("name") if tool_call else "",
                                arguments= tool_call.get("arguments") if tool_call else {},
                                type="function",
                                )
                    collected_tool_calls.append(tc)
                elif event.type == LLM_Events.TOKEN_USAGE:
                    usage_data = event.data
                    usage = event.data or {}
                    total = usage.get("total_tokens", 0)
                    self.cli.update_token_usage(total)
                    yield AgentEvent.turn_token_usage(total)
                elif event.type == LLM_Events.RESPONSE_FINISHED:
                    break
                elif event.type == LLM_Events.ERROR:
                    err_payload = event.data
                    err_msg = ""
                    if isinstance(err_payload, dict):
                        err_msg = err_payload.get("message") or str(err_payload)
                    else:
                        err_msg = str(err_payload)
                    composed = f"LLM error (provider={getattr(active_agent, 'provider', None)} model={params.get('model')}): {err_msg}"
                    yield AgentEvent.error(composed)
                    return

            assistant_msg = LLMMessage(
                    role="assistant",
                    content=assistant_content,
                    tool_calls=collected_tool_calls or None
                    )

            tool_calls = []
            if collected_tool_calls:
                for tc in collected_tool_calls:
                    tool_calls.append({"id": tc.call_id, "name": tc.name, "arguments": tc.arguments})

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

            yield AgentEvent.user_defined({
                 "type": "assistant_response",
                 "assistant_message": assistant_msg,
                 "tool_calls": tool_calls,
                 "final_response": final_response
                })

        except Exception as e:
            yield AgentEvent.error(f"Streaming error: {str(e)}")

    async def _execute_tools(self, tool_calls: List[Dict[str, Any]]) -> AsyncGenerator[tuple[AgentEvent, Optional[LLMMessage]], None]:
        if not tool_calls:
            yield AgentEvent.tool_result("", "", "No tools to execute", True, {}), None
            return

        for tool_call in tool_calls:
            try:
                tool_result, llm_message = await self._execute_single_tool_with_result(tool_call)
                event = AgentEvent.tool_result(
                        call_id=tool_call.get("id", "unknown"),
                        name=tool_call["name"],
                        result=tool_result.result if tool_result.success and isinstance(tool_result.result, dict) else str(tool_result.result or tool_result.error),
                        success=tool_result.success,
                        args=tool_call.get("arguments", {})
                        )
                yield event, llm_message

            except Exception as e:
                error_msg = f"Error executing tool '{tool_call['name']}': {str(e)}"
                error_message = LLMMessage(
                        role="tool",
                        content=f"Error: {error_msg}",
                        tool_call_id=tool_call.get("id", "unknown")
                        )

                event = AgentEvent.tool_result(
                        call_id=tool_call.get("id", "unknown"),
                        name=tool_call["name"],
                        result=error_msg,
                        success=False,
                        args=tool_call.get("arguments", {})
                        )
                yield event, error_message

    async def _execute_single_tool_with_result(self, tool_call: Dict[str, Any],) -> tuple[ToolCallResult, LLMMessage]:
        try:
            tool_call_obj = ToolCall(
                    call_id=tool_call.get("id", "unknown"),
                    name=tool_call["name"],
                    arguments=tool_call.get("arguments", {})
                    )
            tool = self.tool_mgr.get_tool(tool_call["name"])
            if not tool:
                raise ValueError(f"Tool '{tool_call['name']}' not found")

            is_approved, result = await self.tool_mgr.execute(tool_call["name"],tool_call.get("arguments", {}),tool, agent=self)

            # 发送工具执行事件并更新 TODO 状态
            new_todos = emit_tool_execution_event(tool_call_obj, self.type, self.todo_items)
            if new_todos is not None:
                self.todo_items = new_todos

            llm_message = LLMMessage(role="tool",  content= str(result), tool_call_id=tool_call.get("id", "unknown") )

            tc_res = ToolCallResult(
                    call_id=tool_call.get("id", "unknown"),
                    result=result,
                    error=None if is_approved else str(result),
                    )

            return tc_res, llm_message

        except Exception as e:
            error_msg = f"Error executing tool '{tool_call['name']}': {str(e)}"
            error_result = ToolCallResult(
                    call_id=tool_call.get("id", "unknown"),
                    error=error_msg,
                    )
            error_message = LLMMessage(
                    role="tool",
                    content=f"Error: {error_msg}",
                    tool_call_id=tool_call.get("id", "unknown")
                    )
            return error_result, error_message
