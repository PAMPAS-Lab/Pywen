"""
Claude Code Agent - Python implementation of the Claude Code assistant
"""
import os
from typing import Dict, List, Optional, AsyncGenerator, Any
import datetime
from pywen.agents.base_agent import BaseAgent
from pywen.tools.base import BaseTool
from pywen.llm.llm_client import LLMClient, LLMConfig, LLMMessage
from pywen.utils.llm_basics import LLMResponse
from pywen.utils.tool_basics import ToolCall, ToolResult
from pywen.core.trajectory_recorder import TrajectoryRecorder
from .prompts import ClaudeCodePrompts
from .context_manager import ClaudeCodeContextManager
from pywen.core.session_stats import session_stats
from pywen.core.agent_registry import registry  as agent_registry

from pywen.agents.claudecode.tools.tool_adapter import ToolAdapterFactory
from pywen.config.manager import ConfigManager
from pywen.agents.claudecode.system_reminder import (
    generate_system_reminders, emit_reminder_event, reset_reminder_session,
    get_system_reminder_start
)
from pywen.hooks.models import HookEvent

class ClaudeCodeAgent(BaseAgent):
    """Claude Code Agent implementation"""

    def __init__(self, config, hook_mgr, cli_console=None):
        super().__init__(config, hook_mgr, cli_console)
        self.type = "ClaudeCodeAgent"

        self.llmconfig = LLMConfig(
            provider=config.model_config.provider.value,
            api_key=config.model_config.api_key,
            base_url=config.model_config.base_url,
            model=config.model_config.model or "qwen-plus",
            wire_api="auto",
        )
        self.llm_client = LLMClient(self.llmconfig)
        self.prompts = ClaudeCodePrompts()
        self.project_path = os.getcwd()
        self.max_iterations = getattr(config, 'max_iterations', 10)

        self.context_manager = ClaudeCodeContextManager(self.project_path)
        self.context = {}

        self.conversation_history: List[LLMMessage] = []

        trajectories_dir = ConfigManager.get_trajectories_dir()

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        trajectory_path = trajectories_dir / f"claude_code_trajectory_{timestamp}.json"
        self.trajectory_recorder = TrajectoryRecorder(trajectory_path)

        self._setup_claude_code_tools()
        self._apply_claude_code_adapters()

        # Convert tools to Anthropic native format
        self.tools_formatted = self.tools_format_convert()

        session_stats.set_current_agent(self.type)
        self.quota_checked = False

        self.todo_items = []
        reset_reminder_session()
        self.file_metrics = {}

    def _setup_claude_code_tools(self):
        """Setup Claude Code specific tools and configure them."""

        task_tool = self.tool_registry.get_tool('task_tool')
        task_tool.set_agent_registry(agent_registry)

        architect_tool = self.tool_registry.get_tool('architect_tool')
        architect_tool.set_agent_registry(agent_registry)

    def _apply_claude_code_adapters(self):
        """Apply Claude Code specific tool adapters to provide appropriate descriptions for LLM."""

        current_tools = self.tool_registry.list_tools()
        adapted_tools = []
        for tool in current_tools:
            try:
                adapter = ToolAdapterFactory.create_adapter(tool)
                adapted_tools.append(adapter)
            except ValueError:
                # No Claude Code description defined, use original tool
                adapted_tools.append(tool)

        # Replace tools with adapted versions
        self.tools = adapted_tools

    def tools_format_convert(self) -> List[Dict[str, Any]]:
        """Convert tools to Anthropic native format."""
        tool_list = []
        for t in self.tools:
            func_decl = t.get_function_declaration()
            # Convert to Anthropic format: name, description, input_schema
            tool_dict = {
                "name": func_decl["name"],
                "description": func_decl["description"],
                "input_schema": func_decl["parameters"]
            }
            tool_list.append(tool_dict)
        return tool_list

    def _build_messages(self, messages: List[LLMMessage]) -> List[Dict[str, Any]]:
        """Build messages in the format expected by responses API."""
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

    def get_enabled_tools(self) -> List[str]:
        """Return list of enabled tool names for Claude Code Agent."""
        return [
            'read_file', 'write_file', 'edit_file', 'read_many_files',
            'ls', 'grep', 'glob', 'bash', 'web_fetch', 'web_search',
            'task_tool','architect_tool','todo_write','think_tool',
        ]

    def _build_system_prompt(self) -> str:
        """Build system prompt with context and tool descriptions."""
        return self.prompts.get_system_prompt(self.context)

    def _update_context(self):
        """
        Update the context information using the Context Manager
        """
        try:
            # Use context manager to get comprehensive context
            self.context = self.context_manager.get_context()

            # Use prompts to build additional context
            additional_context = self.prompts.build_context(self.project_path)
            self.context.update(additional_context)

        except Exception as e:
            if self.cli_console:
                self.cli_console.print(f"Failed to build context: {e}", "yellow")
            # Fallback to minimal context
            self.context = {'project_path': self.project_path}

    def clear_conversation_history(self):
        """
        Clear the conversation history (useful for starting fresh)
        """
        self.conversation_history.clear()
        if self.cli_console:
            self.cli_console.print("Conversation history cleared", "green")

    def get_conversation_summary(self) -> str:
        """
        Get a summary of the current conversation history
        """
        if not self.conversation_history:
            return "No conversation history"

        user_messages = len([msg for msg in self.conversation_history if msg.role == "user"])
        assistant_messages = len([msg for msg in self.conversation_history if msg.role == "assistant"])
        tool_messages = len([msg for msg in self.conversation_history if msg.role == "tool"])

        return f"Conversation: {user_messages} user, {assistant_messages} assistant, {tool_messages} tool messages"

    async def run(self, user_message: str, **kwargs) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Main execution loop for Claude Code Agent following official flow:
        1. Quota check (if first run)
        2. Topic detection
        3. Core Agent flow with official prompt structure
        """
        try:
            agent_registry.switch_to(self)

            self.trajectory_recorder.start_recording(
                task=user_message,
                provider=self.config.model_config.provider.value,
                model=self.config.model_config.model or "",
                max_steps=self.max_iterations
            )

            # Record task start in session stats
            session_stats.record_task_start(self.type)

            yield {"type": "user_message", "data": {"message": user_message}}

            # # 1. Quota check (only on first run)
            # if not self.quota_checked:
            #     quota_ok = await self._check_quota()
            #     self.quota_checked = True
            #     if not quota_ok:
            #         yield {
            #             "type": "error",
            #             "data": {"error": "API quota check failed"}
            #         }

            # 2. Topic detection for each user input
            topic_info = await self._detect_new_topic(user_message)
            if topic_info and topic_info.get('isNewTopic'):
                yield {
                    "type": "new_topic_detected",
                    "data": {
                        "title": topic_info.get('title'),
                        "isNewTopic": topic_info.get('isNewTopic')
                    }
                }

            # Update context before each run
            self._update_context()
            
            # Emit session startup event for system reminders
            emit_reminder_event('session:startup', {
                'agentId': self.type,
                'messages': len(self.conversation_history),
                'timestamp': datetime.datetime.now().timestamp(),
                'context': self.context
            })

            # 3. Core Agent flow with official prompt structure
            llm_message = LLMMessage(role="user", content=user_message)
            self.conversation_history.append(llm_message)

            # Build official message sequence (merges reminders into user message)
            messages = await self._build_official_messages(user_message)

            # Start recursive query loop with depth control
            async for event in self._query_recursive(messages, None, depth=0, **kwargs):
                yield event

        except Exception as e:
            yield {
                "type": "error",
                "data": {
                    "error": f"Agent error: {str(e)}"
                },
            }

    async def _check_quota(self) -> bool:
        """
        Check API quota by sending a lightweight query
        Following official Claude Code quota check flow
        """
        try:
            # Send simple quota check message
            quota_messages = [{"role": "user", "content": "quota"}]

            # Use astream_response with Anthropic native API
            params = {"model": self.llmconfig.model}
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

            # Record quota check interaction in trajectory
            quota_llm_response = LLMResponse(
                content=content,
                model=self.llmconfig.model,
                finish_reason="stop",
                usage=None,
                tool_calls=[]
            )

            self.trajectory_recorder.record_llm_interaction(
                messages=[LLMMessage(role="user", content="quota")],
                response=quota_llm_response,
                provider=self.llmconfig.provider,
                model=self.llmconfig.model,
                tools=None,
                current_task="quota_check",
                agent_name="ClaudeCodeAgent"
            )

            return bool(content)  # Return True if we got any content
        except Exception as e:
            if self.cli_console:
                self.cli_console.print(f"Quota check failed: {e}", "yellow")
            return False

    async def _detect_new_topic(self, user_input: str) -> Optional[Dict[str, Any]]:
        """
        Detect if user input represents a new topic
        Following official Claude Code topic detection flow
        """
        try:
            # Build topic detection messages
            topic_messages = [
                {"role": "system", "content": self.prompts.get_check_new_topic_prompt()},
                {"role": "user", "content": user_input}
            ]

            # Use astream_response with Anthropic native API
            params = {"model": self.llmconfig.model}
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

            # Record topic detection interaction in trajectory
            topic_llm_response = LLMResponse(
                content=content,
                model=self.llmconfig.model,
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
                provider=self.llmconfig.provider,
                model=self.llmconfig.model,
                tools=None,
                current_task="topic_detection",
                agent_name="ClaudeCodeAgent"
            )

            # Parse JSON response
            if content:
                try:
                    import json
                    topic_info = json.loads(content.strip())
                    return topic_info
                except json.JSONDecodeError:
                    return None
            return None
        except Exception as e:
            if self.cli_console:
                self.cli_console.print(f"Topic detection failed: {e}", "yellow")
            return None

    async def _build_official_messages(self, user_query: str) -> List[LLMMessage]:
        """
        Build official Claude Code message sequence with system reminders integrated:
        1. system-identity
        2. system-workflow
        3. system-reminder-start (static, before user message)
        4. conversation history (excluding current user message)
        5. current user message (with dynamic reminders merged)

        Args:
            user_query: The current user query (used for reference)
        """
        messages = []

        # 1. System Identity
        messages.append(LLMMessage(
            role="system",
            content=self.prompts.get_system_identity()
        ))

        # 2. System Workflow with environment info
        workflow_content = self.prompts.get_system_workflow()
        # Add environment info using prompts method
        env_info = self.prompts.get_env_info(self.project_path)
        workflow_with_env = f"{workflow_content}\n\n{env_info}"

        messages.append(LLMMessage(
            role="system",
            content=workflow_with_env
        ))

        # 3. System Reminder Start (static, from system_reminder.py)
        messages.append(LLMMessage(
            role="user",
            content=get_system_reminder_start()
        ))

        # 4. Add conversation history (excluding the current user message)
        for msg in self.conversation_history[:-1]:  # Exclude the last message we just added
            messages.append(msg)

        # 5. Current user message (keep original content)
        if self.conversation_history:
            messages.append(self.conversation_history[-1])

        # 6. Generate and inject dynamic system reminders as separate user messages
        has_context = bool(self.context and len(self.conversation_history) > 1)
        dynamic_reminders = generate_system_reminders(
            has_context=has_context,
            agent_id=self.type,
            todo_items=self.todo_items
        )
        
        # Add each reminder as a separate user message
        for reminder in dynamic_reminders:
            reminder_message = LLMMessage(
                role="user",
                content=reminder.content
            )
            messages.append(reminder_message)
            # Also add to conversation history to persist across recursive calls
            self.conversation_history.append(reminder_message)

        return messages

    async def _query_recursive(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str],
        depth: int = 0,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Recursive query function - implements the core query loop from original Claude Code
        This function calls itself recursively when tool calls are present

        Args:
            messages: Conversation history (already includes official prompt structure)
            system_prompt: System prompt (can be None for official structure)
            depth: Current recursion depth (for max_iterations control)
            **kwargs: Additional arguments
        """
        try:
            # 🔢 DEPTH CONTROL: Check max iterations
            if depth >= self.max_iterations:
                yield {
                    "type": "max_turns_reached",
                    "data": {
                        "max_iterations": self.max_iterations,
                        "current_depth": depth
                    }
                }
                return

            # Check for abort signal
            if kwargs.get('abort_signal') and kwargs['abort_signal'].is_set():
                yield {
                    "type": "error",
                    "data": {"error": "Operation was cancelled"}
                }
                return


            # Get assistant response with fine-grained streaming events
            assistant_message, tool_calls, final_response = None, [], None
            async for response_event in self._get_assistant_response_streaming(messages, depth=depth, **kwargs):
                if response_event["type"] in ["llm_stream_start", "llm_chunk", "content"]:
                    # Forward streaming events to caller
                    yield response_event
                elif response_event["type"] == "assistant_response":
                    # Extract final response
                    assistant_message = response_event["assistant_message"]
                    tool_calls = response_event["tool_calls"]
                    final_response = response_event.get("final_response")

            # 📝 TRAJECTORY: Record LLM interaction
            if assistant_message:
                # Add assistant message to conversation history
                self.conversation_history.append(assistant_message)

                # Create LLMResponse object for trajectory recording with usage info
                llm_response = LLMResponse(
                    content=assistant_message.content or "",
                    tool_calls=[ToolCall(
                        call_id=tc.get("id", "unknown"),
                        name=tc.get("name", ""),
                        arguments=tc.get("arguments", {})
                    ) for tc in tool_calls] if tool_calls else None,
                    model=self.config.model_config.model,
                    finish_reason="stop",
                    usage=final_response.usage if final_response and hasattr(final_response, 'usage') else None
                )

                # 记录LLM交互 (session stats 会在 trajectory_recorder 中自动记录)
                self.trajectory_recorder.record_llm_interaction(
                    messages=messages,
                    response=llm_response,
                    provider=self.config.model_config.provider.value,
                    model=self.config.model_config.model,
                    tools=self.tools,
                    current_task=f"Processing query at depth {depth}",
                    agent_name=self.type
                )


            # TOP CONDITION: No tool calls means we're done
            if not tool_calls:

                # Run memory monitor after Task completed
                # current_usage = final_response.usage.total_tokens
                # comression = await self.memory_monitor.run_monitored(self.current_turn, self.conversation_history, current_usage)
                # if comression is not None:
                #     self.conversation_history = comression

                # Yield task completion event with safe usage check
                if final_response and hasattr(final_response, 'usage') and final_response.usage:
                    yield {"type": "turn_token_usage", "data": final_response.usage.total_tokens}
                yield {
                    "type": "task_complete",
                    "content": assistant_message.content if assistant_message else "",
                    
                }

                return

            # Yield tool call events for each tool
            for tool_call in tool_calls:
                yield {
                    "type": "tool_call_start",
                    "data": {
                        "call_id": tool_call.get("id", "unknown"),
                        "name": tool_call["name"],
                        "arguments": tool_call.get("arguments", {})
                    }
                }

            # Execute tools and get results (simplified)
            tool_results = []
            async for tool_event in self._execute_tools(tool_calls, **kwargs):
                # Forward all tool events to caller
                yield tool_event
                
                if tool_event["type"] == "tool_results":
                    # Extract final results
                    tool_results = tool_event["results"]

            # Check for abort signal after tool execution
            if kwargs.get('abort_signal') and kwargs['abort_signal'].is_set():
                yield {
                    "type": "error",
                    "data": {"error": "Operation was cancelled during tool execution"}
                }
                return

            # Add tool results to conversation history
            for tool_result in tool_results:
                self.conversation_history.append(tool_result)


            # 🔄 RECURSIVE CALL: Check for new system reminders and add as separate user messages
            if system_prompt:
                # Legacy mode: use system_prompt
                updated_messages = [
                    LLMMessage(role="system", content=system_prompt)
                ] + self.conversation_history.copy()
            else:
                # Official mode: check for new system reminders and add as separate messages
                has_context = bool(self.context and len(self.conversation_history) > 1)
                new_dynamic_reminders = generate_system_reminders(
                    has_context=has_context,
                    agent_id=self.type,
                    todo_items=self.todo_items
                )
                
                # Add new reminders as separate user messages to conversation history
                for reminder in new_dynamic_reminders:
                    reminder_message = LLMMessage(
                        role="user",
                        content=reminder.content
                    )
                    # Add to conversation history
                    self.conversation_history.append(reminder_message)
                
                # Use conversation history directly (no full rebuild)
                updated_messages = [
                    # Add minimal system structure for API compatibility
                    LLMMessage(role="system", content=self.prompts.get_system_identity()),
                    LLMMessage(role="system", content=f"{self.prompts.get_system_workflow()}\n\n{self.prompts.get_env_info(self.project_path)}"),
                    LLMMessage(role="system", content=get_system_reminder_start())
                ] + self.conversation_history.copy()

            # 🔄 RECURSIVE CALL: Continue with updated message history and incremented depth
            async for event in self._query_recursive(updated_messages, system_prompt, depth=depth+1, **kwargs):
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
        """
        Get assistant response from LLM with fine-grained streaming events
        Yields: llm_stream_start, llm_chunk, assistant_response events
        """
        try:
            # Check for abort signal
            if kwargs.get('abort_signal') and kwargs['abort_signal'].is_set():
                yield {
                    "type": "error",
                    "data": {"error": "Operation was cancelled"}
                }
                return

            # Build messages in Anthropic native format
            formatted_messages = self._build_messages(messages)

            # Use astream_response with Anthropic native API
            params = {
                "model": self.llmconfig.model,
                "tools": self.tools_formatted,
                "max_tokens": 4096
            }

            # Yield stream start event
            yield {
                "type": "llm_stream_start",
                "data": {"depth": depth}
            }

            # Process streaming response with Anthropic native events
            assistant_content = ""
            collected_tool_calls = []
            current_tool_call = None
            tool_json_buffer = ""

            async for evt in self.llm_client.astream_response(formatted_messages, **params):
                if evt.type == "output_text.delta":
                    # Send content delta
                    yield {
                        "type": "llm_chunk",
                        "data": {"content": evt.data}
                    }
                    assistant_content += evt.data

                elif evt.type == "content_block_start":
                    # Start of a new content block (could be text or tool_use)
                    block_data = evt.data
                    if block_data.get("block_type") == "tool_use":
                        current_tool_call = {
                            "call_id": block_data.get("call_id"),
                            "name": block_data.get("name"),
                        }
                        tool_json_buffer = ""

                elif evt.type == "tool_call.delta_json":
                    # Accumulate tool call JSON
                    if current_tool_call:
                        tool_json_buffer += evt.data

                elif evt.type == "content_block_stop":
                    # End of content block - finalize tool call if any
                    if current_tool_call:
                        import json
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

                elif evt.type == "completed":
                    # Stream completed
                    break

                elif evt.type == "error":
                    yield {
                        "type": "error",
                        "data": {"error": str(evt.data)}
                    }
                    return

            # Build assistant message
            assistant_msg = LLMMessage(
                role="assistant",
                content=assistant_content,
                tool_calls=collected_tool_calls if collected_tool_calls else None
            )

            # Convert tool calls to expected format
            tool_calls = []
            if collected_tool_calls:
                for tc in collected_tool_calls:
                    tool_calls.append({
                        "id": tc.call_id,
                        "name": tc.name,
                        "arguments": tc.arguments
                    })

            # Create a mock final_response for compatibility
            final_response = type('obj', (object,), {
                'usage': None,
                'content': assistant_content,
                'tool_calls': collected_tool_calls
            })()

            # Return final assistant_response event
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
        """
        Simplified tool execution - always execute sequentially
        """
        if not tool_calls:
            yield {
                "type": "tool_results",
                "results": []
            }
            return

        # Execute tools sequentially
        tool_results = []
        for tool_call in tool_calls:
            try:
                # Yield tool start event
                yield {
                    "type": "tool_start",
                    "data": {
                        "call_id": tool_call.get("id", "unknown"),
                        "name": tool_call["name"],
                        "arguments": tool_call.get("arguments", {})
                    }
                }

                # Execute single tool
                tool_result, llm_message = await self._execute_single_tool_with_result(tool_call, **kwargs)

                # Yield tool result for CLI display
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

                # Add to results
                tool_results.append(llm_message)

                # Check for abort signal
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
        """
        Execute a single tool and return both ToolResult and LLMMessage
        This is the main tool execution method that others can call
        """
        try:
            # Check for abort signal
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

            # Convert to ToolCall object
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

            # Check for user confirmation if needed
            if hasattr(self, 'cli_console') and self.cli_console:
                tool = self.tool_registry.get_tool(tool_call["name"])
                if tool:
                    confirmation_details = await tool.get_confirmation_details(**tool_call.get("arguments", {}))
                    if confirmation_details:
                        confirmed = await self.cli_console.confirm_tool_call(tool_call_obj, tool)
                        if not confirmed:
                            # User cancelled
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

            # Execute tool
            results = await self.tool_executor.execute_tools([tool_call_obj], self.type)
            tool_result = results[0]
            
            # Emit events for system reminders based on tool type
            self._emit_tool_events(tool_call_obj, tool_result)

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

            # Create LLM message with clear success info
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



    def _find_tool(self, tool_name: str) -> Optional[BaseTool]:
        """Find a tool by name"""
        return self.tool_registry.get_tool(tool_name)
        
    def _emit_tool_events(self, tool_call: ToolCall, tool_result: ToolResult) -> None:
        """
        Emit events for system reminders based on tool execution
        Following Kode's event-driven reminder system
        """
        current_time = datetime.datetime.now().timestamp()
        
        # File read events
        if tool_call.name in ['read_file', 'read_many_files']:
            emit_reminder_event('file:read', {
                'filePath': tool_call.arguments.get('file_path', ''),
                'timestamp': current_time,
                'agentId': self.type
            })
            
        # File edit events  
        elif tool_call.name in ['edit_file', 'write_file']:
            emit_reminder_event('file:edited', {
                'filePath': tool_call.arguments.get('file_path', ''),
                'timestamp': current_time,
                'operation': 'update' if tool_call.name == 'edit_file' else 'create',
                'agentId': self.type
            })
            
        # Todo change events
        elif tool_call.name == 'todo_write':
            # Update internal todo tracking
            todos = tool_call.arguments.get('todos', [])
            previous_todos = self.todo_items.copy()
            self.todo_items = todos
            
            emit_reminder_event('todo:changed', {
                'previousTodos': previous_todos,
                'newTodos': todos,
                'timestamp': current_time,
                'agentId': self.type,
                'changeType': self._determine_todo_change_type(previous_todos, todos)
            })
            
    def _determine_todo_change_type(self, previous_todos: List, new_todos: List) -> str:
        """Determine the type of todo change"""
        if len(new_todos) > len(previous_todos):
            return 'added'
        elif len(new_todos) < len(previous_todos):
            return 'removed'
        else:
            return 'modified'
            
    def update_todo_items(self, todo_items: List[Dict]) -> None:
        """
        Update todo items and trigger reminder events
        This can be called externally when todos are updated
        """
        previous_todos = self.todo_items.copy()
        self.todo_items = todo_items
        
        emit_reminder_event('todo:changed', {
            'previousTodos': previous_todos,
            'newTodos': todo_items,
            'timestamp': datetime.datetime.now().timestamp(),
            'agentId': self.type,
            'changeType': self._determine_todo_change_type(previous_todos, todo_items)
        })
    
    def get_capabilities(self) -> Dict[str, Any]:
        """Get agent capabilities"""
        return {
            "name": "Claude Code",
            "type": self.type,
            "description": "AI coding assistant with file operations and command execution",
            "features": [
                "Code analysis and writing",
                "File operations",
                "Command execution",
                "Project understanding",
                "Sub-agent delegation",
                "Context-aware responses",
                "Conversation history memory"
            ],
            "tools": [tool.name for tool in self.tools],
            "supports_streaming": True,
            "supports_sub_agents": True,
            "conversation_history": {
                "enabled": True,
                # "max_messages": self.max_history_messages,
                "current_messages": len(self.conversation_history),
                "summary": self.get_conversation_summary()
            }
        }
    
    def set_project_path(self, path: str):
        """Set the current project path"""
        if os.path.exists(path):
            self.project_path = path
            self._update_context()
        else:
            raise ValueError(f"Path does not exist: {path}")
