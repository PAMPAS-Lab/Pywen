"""
Claude Code Agent - Python implementation of the Claude Code assistant
"""
import os
from typing import Dict, List, Optional, AsyncGenerator, Any
import datetime
from pywen.agents.base_agent import BaseAgent
from pywen.tools.base import BaseTool
from pywen.utils.llm_basics import LLMMessage, LLMResponse
from pywen.utils.tool_basics import ToolCall, ToolResult
from pywen.core.trajectory_recorder import TrajectoryRecorder
from .prompts import ClaudeCodePrompts
from .context_manager import ClaudeCodeContextManager
from pywen.core.session_stats import session_stats

# Import memory moniter and file restorer
from pywen.memory.memory_moniter import MemoryMonitor, AdaptiveThreshold
from pywen.memory.file_restorer import IntelligentFileRestorer

from pywen.agents.claudecode.tools.tool_adapter import ToolAdapterFactory
from pywen.config.loader import get_trajectories_dir


class ClaudeCodeAgent(BaseAgent):
    """Claude Code Agent implementation"""

    def __init__(self, config, cli_console=None):
        super().__init__(config, cli_console)
        self.type = "ClaudeCodeAgent"
        self.prompts = ClaudeCodePrompts()
        self.project_path = os.getcwd()
        self.max_iterations = getattr(config, 'max_iterations', 10)

        # Initialize context manager
        self.context_manager = ClaudeCodeContextManager(self.project_path)
        self.context = {}

        # Initialize conversation history for session continuity
        self.conversation_history: List[LLMMessage] = []
        # self.max_history_messages = getattr(config, 'max_history_messages', 20)  # Keep last 20 messages

        # Ensure trajectories directory exists
        trajectories_dir = get_trajectories_dir()

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        trajectory_path = trajectories_dir / f"claude_code_trajectory_{timestamp}.json"
        self.trajectory_recorder = TrajectoryRecorder(trajectory_path)

        # Setup Claude Code specific tools after base tools
        self._setup_claude_code_tools()

        # Apply Claude Code adapters to provide appropriate descriptions for LLM
        self._apply_claude_code_adapters()

        #self._update_context()

        # Register this agent with session stats
        session_stats.set_current_agent(self.type)

        # Initialize memory moniter and file restorer
        self.current_turn = 0
        self.memory_moniter = MemoryMonitor(AdaptiveThreshold(check_interval=3, max_tokens=200000, rules=((0.92, 1), (0.80, 1), (0.60, 2), (0.00, 3))))
        self.file_restorer = IntelligentFileRestorer()

        # Track quota check status
        self.quota_checked = False

    def _setup_claude_code_tools(self):
        """Setup Claude Code specific tools and configure them."""
        # Import agent registry
        from pywen.core.agent_registry import get_agent_registry
        agent_registry = get_agent_registry()

        # Configure task_tool and architect_tool with agent registry
        task_tool = self.tool_registry.get_tool('task_tool')
        if task_tool and hasattr(task_tool, 'set_agent_registry'):
            task_tool.set_agent_registry(agent_registry)

        architect_tool = self.tool_registry.get_tool('architect_tool')
        if architect_tool and hasattr(architect_tool, 'set_agent_registry'):
            architect_tool.set_agent_registry(agent_registry)

    def _apply_claude_code_adapters(self):
        """Apply Claude Code specific tool adapters to provide appropriate descriptions for LLM."""

        # Get current tools from registry
        current_tools = self.tool_registry.list_tools()

        # Apply adapters to tools that have Claude Code specific descriptions
        adapted_tools = []
        for tool in current_tools:
            try:
                # Try to create an adapter for this tool
                adapter = ToolAdapterFactory.create_adapter(tool)
                adapted_tools.append(adapter)
            except ValueError:
                # No Claude Code description defined, use original tool
                adapted_tools.append(tool)

        # Replace tools with adapted versions
        self.tools = adapted_tools

    def get_enabled_tools(self) -> List[str]:
        """Return list of enabled tool names for Claude Code Agent."""
        return [
            'read_file', 'write_file', 'edit_file', 'read_many_files',
            'ls', 'grep', 'glob', 'bash', 'web_fetch', 'web_search','task_tool','architect_tool','todo_write'
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

    async def run(self, query: str, **kwargs) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Main execution loop for Claude Code Agent following official flow:
        1. Quota check (if first run)
        2. Topic detection
        3. Core Agent flow with official prompt structure
        """
        try:
            # Record the current turn
            self.current_turn += 1

            # Set this agent as current in the registry for tool access
            from pywen.core.agent_registry import set_current_agent
            set_current_agent(self)

            # Start trajectory recording
            self.trajectory_recorder.start_recording(
                task=query,
                provider=self.config.model_config.provider.value,
                model=self.config.model_config.model,
                max_steps=self.max_iterations
            )

            # Record task start in session stats
            session_stats.record_task_start(self.type)

            yield {"type": "user_message", "data": {"message": query}}

            # 1. Quota check (only on first run)
            if not self.quota_checked:
                quota_ok = await self._check_quota()
                self.quota_checked = True
                if not quota_ok:
                    yield {
                        "type": "error",
                        "data": {"error": "API quota check failed"}
                    }

            # 2. Topic detection for each user input
            topic_info = await self._detect_new_topic(query)
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

            # 3. Core Agent flow with official prompt structure
            # Add new user message to conversation history
            user_message = LLMMessage(role="user", content=query)
            self.conversation_history.append(user_message)

            # Build official message sequence
            messages = await self._build_official_messages(query)

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
            quota_messages = [LLMMessage(role="user", content="quota")]

            response_result = await self.llm_client.generate_response(
                messages=quota_messages,
                tools=None,  # No tools for quota check
                stream=False  # Use non-streaming for quota check
            )

            # Handle non-streaming response
            if isinstance(response_result, LLMResponse):
                # Non-streaming response
                final_response = response_result
                content = response_result.content or ""
            else:
                # Streaming response (fallback)
                content = ""
                final_response = None
                async for response in response_result:
                    final_response = response
                    if response.content:
                        content += response.content

            # Record quota check interaction in trajectory
            if final_response:
                quota_llm_response = LLMResponse(
                    content=content,
                    model=self.config.model_config.model,
                    finish_reason="stop",
                    usage=final_response.usage if hasattr(final_response, 'usage') else None,
                    tool_calls=[]
                )

                self.trajectory_recorder.record_llm_interaction(
                    messages=quota_messages,
                    response=quota_llm_response,
                    provider=self.config.model_config.provider.value,
                    model=self.config.model_config.model,
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
                LLMMessage(role="system", content=self.prompts.get_check_new_topic_prompt()),
                LLMMessage(role="user", content=user_input)
            ]

            response_result = await self.llm_client.generate_response(
                messages=topic_messages,
                tools=None,  # No tools for topic detection
                stream=False  # Use non-streaming for topic detection
            )

            # Handle non-streaming response
            if isinstance(response_result, LLMResponse):
                # Non-streaming response
                final_response = response_result
                content = response_result.content or ""
            else:
                # Streaming response (fallback)
                content = ""
                final_response = None
                async for response in response_result:
                    final_response = response
                    if response.content:
                        content += response.content

            # Record topic detection interaction in trajectory
            if final_response:
                topic_llm_response = LLMResponse(
                    content=content,
                    model=self.config.model_config.model,
                    finish_reason="stop",
                    usage=final_response.usage if hasattr(final_response, 'usage') else None,
                    tool_calls=[]
                )

                self.trajectory_recorder.record_llm_interaction(
                    messages=topic_messages,
                    response=topic_llm_response,
                    provider=self.config.model_config.provider.value,
                    model=self.config.model_config.model,
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
        Build official Claude Code message sequence:
        1. system-identity
        2. system-workflow
        3. system-reminder-start
        4. conversation history
        5. current user message
        6. system-reminder-end

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

        # 3. System Reminder Start
        messages.append(LLMMessage(
            role="system",
            content=self.prompts.get_system_reminder_start()
        ))

        # 4. Add conversation history (excluding the current user message)
        for msg in self.conversation_history[:-1]:  # Exclude the last message we just added
            messages.append(msg)

        # 5. Current user message (already in conversation_history)
        if self.conversation_history:
            messages.append(self.conversation_history[-1])

        # 6. System Reminder End
        messages.append(LLMMessage(
            role="system",
            content=self.prompts.get_system_reminder_end()
        ))

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
            assistant_message, tool_calls = None, []
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

                # Run memory moniter after Task completed
                current_usage = final_response.usage.total_tokens
                comression = await self.memory_moniter.run_monitored(self.current_turn, self.conversation_history, current_usage)
                if comression is not None:
                    self.conversation_history = comression

                # Yield task completion event
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


            # 🔄 RECURSIVE CALL: Rebuild official message structure with updated conversation history
            if system_prompt:
                # Legacy mode: use system_prompt
                updated_messages = [
                    LLMMessage(role="system", content=system_prompt)
                ] + self.conversation_history.copy()
            else:
                # Official mode: rebuild official message structure
                # Get the last user message from conversation history
                last_user_msg = None
                for msg in reversed(self.conversation_history):
                    if msg.role == "user":
                        last_user_msg = msg.content
                        break

                if last_user_msg:
                    updated_messages = await self._build_official_messages(last_user_msg)
                else:
                    # Fallback: use current messages
                    updated_messages = messages

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
            response_stream = await self.llm_client.generate_response(
                messages=messages,
                tools=self.tools,
                stream=True
            )

            # Yield stream start event
            yield {
                "type": "llm_stream_start",
                "data": {"depth": depth}
            }

            # 1. 流式处理响应，收集工具调用
            final_response = None
            previous_content = ""
            collected_tool_calls = []

            async for response_chunk in response_stream:
                final_response = response_chunk

                # 发送内容增量
                if response_chunk.content:
                    current_content = response_chunk.content
                    if current_content != previous_content:
                        new_content = current_content[len(previous_content):]
                        if new_content:
                            yield {
                                "type": "llm_chunk",
                                "data": {"content": new_content}
                            }
                        previous_content = current_content

                # 收集工具调用（不立即执行）
                if response_chunk.tool_calls:
                    collected_tool_calls.extend(response_chunk.tool_calls)

            # 2. 流结束后处理
            if final_response:
                # 添加到对话历史
                assistant_msg = LLMMessage(
                    role="assistant",
                    content=final_response.content,
                    tool_calls=final_response.tool_calls
                )

                # 简化的工具调用格式转换
                tool_calls = []
                if final_response.tool_calls:
                    for tc in final_response.tool_calls:
                        tool_calls.append({
                            "id": tc.call_id,
                            "name": tc.name,
                            "arguments": tc.arguments
                        })

                # 返回最终的assistant_response事件，包含usage信息
                yield {
                    "type": "assistant_response",
                    "assistant_message": assistant_msg,
                    "tool_calls": tool_calls,
                    "final_response": final_response  # 包含完整的响应对象，包括usage
                }

        except Exception as e:
            yield {
                "type": "error",
                "data": {"error": f"Streaming failed, falling back to non-streaming: {str(e)}"}
            }




    async def _execute_tools(
        self,
        tool_calls: List[Dict[str, Any]],
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Simplified tool execution with smart concurrency
        """
        if not tool_calls:
            yield {
                "type": "tool_results",
                "results": []
            }
            return

        # Determine if tools can run concurrently
        can_run_concurrently = all(self._is_tool_readonly(tc["name"]) for tc in tool_calls)

        if can_run_concurrently and len(tool_calls) > 1:
            # Execute read-only tools concurrently
            yield {"type": "tool_execution", "strategy": "concurrent"}
            tool_results = await self._execute_concurrent_tools(tool_calls, **kwargs)
        else:
            # Execute tools serially (safer for write operations)
            yield {"type": "tool_execution", "strategy": "serial"}
            tool_results = []
            async for result in self._execute_serial_tools(tool_calls, **kwargs):
                if result["type"] in ["tool_start", "tool_result", "tool_error"]:
                    yield result
                elif result["type"] == "tool_completed":
                    tool_results.append(result["llm_message"])

        # Yield final results
        yield {
            "type": "tool_results",
            "results": tool_results
        }



    def _is_tool_readonly(self, tool_name: str) -> bool:
        """Check if a tool is read-only (safe for concurrent execution)"""
        readonly_tools = {
            'read_file', 'read_many_files', 'ls', 'grep', 'glob',
            'web_fetch', 'web_search', 'git_status', 'git_log'
        }
        return tool_name in readonly_tools

    async def _execute_serial_tools(
        self,
        tool_calls: List[Dict[str, Any]],
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Execute tools one by one (simplified)"""
        
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

                # Execute single tool directly
                tool_result, llm_message = await self._execute_single_tool_with_result(tool_call, **kwargs)

                # Yield tool result for CLI display
                yield {
                    "type": "tool_result", 
                    "data": {
                        "call_id": tool_call.get("id", "unknown"),
                        "name": tool_call["name"],
                        "result": tool_result.result if tool_result.success and isinstance(tool_result.result, dict) else str(tool_result.result or tool_result.error),
                        "success": tool_result.success
                    }
                }

                # Yield completed tool for message history
                yield {
                    "type": "tool_completed",
                    "llm_message": llm_message
                }

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

                yield {
                    "type": "tool_completed", 
                    "llm_message": error_message
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
                    content="",
                    error="Operation was cancelled",
                    success=False
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
                                content="",
                                error="Tool execution was cancelled by user",
                                success=False
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
                content="",
                error=error_msg,
                success=False
            )
            error_message = LLMMessage(
                role="tool",
                content=f"Error: {error_msg}",
                tool_call_id=tool_call.get("id", "unknown")
            )
            return error_result, error_message

    async def _execute_concurrent_tools(
        self,
        tool_calls: List[Dict[str, Any]],
        **kwargs
    ) -> List[LLMMessage]:
        """Execute multiple tools concurrently (for read-only tools)"""
        import asyncio

        # Create tasks for concurrent execution
        tasks = []
        for tool_call in tool_calls:
            task = asyncio.create_task(
                self._execute_single_tool(tool_call, **kwargs)
            )
            tasks.append(task)

        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results and maintain order
        tool_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                # Handle exception
                error_msg = f"Error executing tool '{tool_calls[i]['name']}': {str(result)}"
                tool_results.append(LLMMessage(
                    role="tool",
                    content=f"Error: {error_msg}",
                    tool_call_id=tool_calls[i].get("id", "unknown")
                ))
            else:
                tool_results.append(result)

        return tool_results







    async def _execute_single_tool(
        self,
        tool_call: Dict[str, Any],
        **kwargs
    ) -> LLMMessage:
        """
        Execute a single tool and return only the LLMMessage
        This is a convenience wrapper around _execute_single_tool_with_result
        """
        _, llm_message = await self._execute_single_tool_with_result(tool_call, **kwargs)
        return llm_message

    async def _execute_tool_directly(
        self,
        tool_call: Dict[str, Any],
        **kwargs
    ) -> ToolResult:
        """
        Execute a single tool and return only the ToolResult
        This is a convenience wrapper around _execute_single_tool_with_result
        """
        tool_result, _ = await self._execute_single_tool_with_result(tool_call, **kwargs)
        return tool_result


    
    def _find_tool(self, tool_name: str) -> Optional[BaseTool]:
        """Find a tool by name"""
        return self.tool_registry.get_tool(tool_name)
    
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