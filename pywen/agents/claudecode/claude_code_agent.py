"""
Claude Code Agent - Python implementation of the Claude Code assistant
"""
import asyncio
import logging
import os
from typing import Dict, List, Optional, AsyncGenerator, Any
import datetime

from pywen.agents.base_agent import BaseAgent
from pywen.tools.base import BaseTool
from pywen.utils.llm_basics import LLMMessage, LLMResponse, LLMUsage
from pywen.utils.tool_basics import ToolCall
from pywen.core.trajectory_recorder import TrajectoryRecorder
from .prompts import ClaudeCodePrompts
from .context_manager import ClaudeCodeContextManager
from pywen.core.session_stats import session_stats



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


        # Ensure trajectories directory exists
        trajectories_dir = os.path.join(self.project_path, "trajectories")
        os.makedirs(trajectories_dir, exist_ok=True)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        trajectory_path = os.path.join(trajectories_dir, f"claude_code_trajectory_{timestamp}.json")
        self.trajectory_recorder = TrajectoryRecorder(trajectory_path)

        # Setup Claude Code specific tools after base tools
        self._setup_claude_code_tools()

        self.tools = self.tool_registry.list_tools()

        self._update_context()

        # Register this agent with session stats
        session_stats.set_current_agent(self.type)

    def _setup_claude_code_tools(self):
        """Setup Claude Code specific tools and configure them."""
        # Import agent registry
        from pywen.core.agent_registry import get_agent_registry
        agent_registry = get_agent_registry()

        # Configure agent_tool and architect_tool with agent registry
        agent_tool = self.tool_registry.get_tool('agent_tool')
        if agent_tool and hasattr(agent_tool, 'set_agent_registry'):
            agent_tool.set_agent_registry(agent_registry)

        architect_tool = self.tool_registry.get_tool('architect_tool')
        if architect_tool and hasattr(architect_tool, 'set_agent_registry'):
            architect_tool.set_agent_registry(agent_registry)

    def get_enabled_tools(self) -> List[str]:
        """Return list of enabled tool names for Claude Code Agent."""
        return [
            'read_file', 'write_file', 'edit_file', 'read_many_files',
            'ls', 'grep', 'glob', 'bash', 'web_fetch', 'web_search','agent_tool','architect_tool'
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

    async def run(self, query: str, **kwargs) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Main execution loop for Claude Code Agent
        Entry point that sets up initial context and calls the recursive query function
        """
        try:
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

            # Yield trajectory saved event
            yield {
                "type": "trajectory_saved",
                "data": {
                    "path": self.trajectory_recorder.trajectory_path,
                    "is_task_start": True
                }
            }

            yield {"type": "user_message", "data": {"message": query}}
            # Update context before each run
            self._update_context()

            # Build system prompt with context
            system_prompt = self.prompts.get_system_prompt(self.context)

            # Initialize conversation with system prompt and user query
            messages = [
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(role="user", content=query)
            ]

            # Start recursive query loop with depth control
            async for event in self._query_recursive(messages, system_prompt, depth=0, **kwargs):
                yield event

            # # End trajectory recording
            # self.trajectory_recorder.end_recording(success=True, final_result="Task completed")

        except Exception as e:
            yield {
                "type": "error",
                "data":{
                "error": f"Agent error: {str(e)}"
                },
            }

    async def _query_recursive(
        self,
        messages: List[LLMMessage],
        system_prompt: str,
        depth: int = 0,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Recursive query function - implements the core query loop from original Claude Code
        This function calls itself recursively when tool calls are present

        Args:
            messages: Conversation history
            system_prompt: System prompt
            depth: Current recursion depth (for max_iterations control)
            **kwargs: Additional arguments
        """
        try:
            # TRAJECTORY: Record recursion start


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

            # Execute tools and get results with streaming events
            tool_results = []
            async for tool_event in self._execute_tools_with_strategy_streaming(tool_calls, depth=depth, **kwargs):
                if tool_event["type"] in ["tool_start", "tool_result", "tool_error"]:
                    # 📝 TRAJECTORY: Record tool results
                    if tool_event["type"] == "tool_result":
                        # Just pass through the tool result event
                        pass

                    # Forward tool events to caller
                    yield tool_event
                elif tool_event["type"] == "tool_results":
                    # Extract final results
                    tool_results = tool_event["results"]

            # Check for abort signal after tool execution
            if kwargs.get('abort_signal') and kwargs['abort_signal'].is_set():
                yield {
                    "type": "error",
                    "data": {"error": "Operation was cancelled during tool execution"}
                }
                return

            # 🔄 RECURSIVE CALL: Continue with updated message history
            updated_messages = [
                *messages,
                assistant_message,
                *tool_results
            ]

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

    
    async def _get_assistant_response(
        self,
        messages: List[LLMMessage],
        **kwargs
    ) -> tuple[LLMMessage, List[Dict[str, Any]]]:
        """
        Get assistant response from LLM, handling both streaming and non-streaming modes
        Returns: (assistant_message, tool_calls)
        """
        try:
            # Try streaming first
            if kwargs.get('stream', True):
                try:
                    response_generator = await self.llm_client.generate_response(
                        messages=messages,
                        tools=self.tools,
                        stream=True
                    )

                    assistant_content = ""
                    tool_calls = []
                    previous_content = ""

                    # Stream the response with incremental output
                    async for chunk in response_generator:
                        if hasattr(chunk, 'content') and chunk.content:
                            current_content = chunk.content
                            if current_content != previous_content:
                                new_content = current_content[len(previous_content):]
                                if new_content:
                                    # Note: We don't yield here, the caller will handle yielding
                                    pass
                                previous_content = current_content
                            assistant_content = current_content

                        if hasattr(chunk, 'tool_calls') and chunk.tool_calls:
                            for tool_call in chunk.tool_calls:
                                tool_calls.append({
                                    "id": tool_call.call_id,
                                    "name": tool_call.name,
                                    "arguments": tool_call.arguments
                                })

                    # Create assistant message
                    assistant_msg = LLMMessage(role="assistant", content=assistant_content)
                    if tool_calls:
                        from pywen.utils.tool_basics import ToolCall
                        llm_tool_calls = []
                        for tc in tool_calls:
                            llm_tool_calls.append(ToolCall(
                                call_id=tc["id"],
                                name=tc["name"],
                                arguments=tc["arguments"]
                            ))
                        assistant_msg.tool_calls = llm_tool_calls

                    return assistant_msg, tool_calls

                except Exception as e:
                    # Log error but continue to non-streaming fallback
                    if self.cli_console:
                        self.cli_console.print(f"Streaming failed, falling back to non-streaming: {str(e)}", "yellow")

            # Non-streaming fallback
            response = await self.llm_client.generate_response(
                messages=messages,
                tools=self.tools,
                stream=False
            )

            assistant_content = response.content
            tool_calls = []

            # Handle tool calls
            if response.tool_calls:
                for tool_call in response.tool_calls:
                    tool_calls.append({
                        "id": tool_call.call_id,
                        "name": tool_call.name,
                        "arguments": tool_call.arguments
                    })

            # Create assistant message
            assistant_msg = LLMMessage(role="assistant", content=assistant_content)
            if tool_calls:
                from pywen.utils.tool_basics import ToolCall
                llm_tool_calls = []
                for tc in tool_calls:
                    llm_tool_calls.append(ToolCall(
                        call_id=tc["id"],
                        name=tc["name"],
                        arguments=tc["arguments"]
                    ))
                assistant_msg.tool_calls = llm_tool_calls

            return assistant_msg, tool_calls

        except Exception as e:
            error_msg = LLMMessage(role="assistant", content=f"Error: {str(e)}")
            if self.cli_console:
                self.cli_console.print(f"Error in assistant response: {str(e)}", "red")
            return error_msg, []


    async def _execute_tools_with_strategy_streaming(
        self,
        tool_calls: List[Dict[str, Any]],
        depth: int = 0,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Execute tools with intelligent concurrency strategy (streaming version)
        Based on original Claude Code implementation
        """
        if not tool_calls:
            yield {
                "type": "tool_results",
                "results": [],
                
            }
            return

        # Simple concurrency check like original Claude Code
        can_run_concurrently = all(self._is_tool_readonly(tc["name"]) for tc in tool_calls)

        if can_run_concurrently and len(tool_calls) > 1:
            # Execute read-only tools concurrently (like original)
            async for event in self._execute_tools_concurrently_streaming(tool_calls, depth=depth, **kwargs):
                yield event
        else:
            # Execute tools serially (safer for write operations)
            async for event in self._execute_tools_serially_streaming(tool_calls, depth=depth, **kwargs):
                yield event

    async def _execute_tools_with_strategy(
        self,
        tool_calls: List[Dict[str, Any]],
        **kwargs
    ) -> List[LLMMessage]:
        """
        Execute tools with intelligent concurrency strategy
        - Read-only tools: Execute concurrently
        - Write tools: Execute serially
        """
        if not tool_calls:
            return []

        # Check if all tools are read-only
        all_readonly = all(self._is_tool_readonly(tc["name"]) for tc in tool_calls)

        if all_readonly and len(tool_calls) > 1:
            # Execute read-only tools concurrently
            return await self._execute_tools_concurrently(tool_calls, **kwargs)
        else:
            # Execute tools serially (safer for write operations)
            return await self._execute_tools_serially(tool_calls, **kwargs)

    def _is_tool_readonly(self, tool_name: str) -> bool:
        """Check if a tool is read-only (safe for concurrent execution)"""
        readonly_tools = {
            'read_file', 'read_many_files', 'ls', 'grep', 'glob',
            'web_fetch', 'web_search', 'git_status', 'git_log'
        }
        return tool_name in readonly_tools

    async def _execute_tools_concurrently(
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

    async def _execute_tools_serially_streaming(
        self,
        tool_calls: List[Dict[str, Any]],
        depth: int = 0,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Execute tools one by one with streaming events"""
        tool_results = []

        for tool_call in tool_calls:
            try:
                # Yield tool start event
                yield {
                    "type": "tool_start",
                    "data": {
                        "call_id": tool_call.get("id", "unknown"),
                        "name": tool_call["name"],
                        "arguments": tool_call.get("arguments", {}),
                        "depth": depth
                    },
                    
                }

                result = await self._execute_single_tool(tool_call, **kwargs)
                tool_results.append(result)

                # Extract result content for CLI display (avoiding ToolResult object display)
                result_content = result.content if hasattr(result, 'content') else str(result)

                # Check if it's an error result
                is_success = not (result_content.startswith("Error:") if result_content else False)

                # 工具执行统计会在 tool_scheduler 中自动记录

                yield {
                    "type": "tool_result",
                    "data": {
                        "call_id": tool_call.get("id", "unknown"),
                        "name": tool_call["name"],
                        "result": result_content,
                        "success": is_success
                    },

                }

                # Check for abort signal between tool executions
                if kwargs.get('abort_signal') and kwargs['abort_signal'].is_set():
                    break

            except Exception as e:
                error_msg = f"Error executing tool '{tool_call['name']}': {str(e)}"
                error_result = LLMMessage(
                    role="tool",
                    content=f"Error: {error_msg}",
                    tool_call_id=tool_call.get("id", "unknown")
                )
                tool_results.append(error_result)

                # Yield tool error event
                yield {
                    "type": "error",
                    "data": {
                        "call_id": tool_call.get("id", "unknown"),
                        "name": tool_call["name"],
                        "error": error_msg,
                        "success": False
                    },
                    
                }

        # Yield final results
        yield {
            "type": "tool_results",
            "results": tool_results,
            
        }

    async def _execute_tools_concurrently_streaming(
        self,
        tool_calls: List[Dict[str, Any]],
        depth: int = 0,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Execute multiple tools concurrently with streaming events"""
        import asyncio

        # Yield start events for all tools
        for tool_call in tool_calls:
            yield {
                "type": "tool_start",
                "data": {
                    "call_id": tool_call.get("id", "unknown"),
                    "name": tool_call["name"],
                    "arguments": tool_call.get("arguments", {}),
                    "depth": depth
                },
                
            }

        # Create tasks for concurrent execution
        tasks = []
        for tool_call in tool_calls:
            task = asyncio.create_task(
                self._execute_single_tool(tool_call, **kwargs)
            )
            tasks.append((task, tool_call))

        # Wait for all tasks to complete
        tool_results = []
        for task, tool_call in tasks:
            try:
                result = await task
                tool_results.append(result)

                # Extract result content for CLI display
                result_content = result.content if hasattr(result, 'content') else str(result)
                is_success = not (result_content.startswith("Error:") if result_content else False)

                # Yield tool result event
                yield {
                    "type": "tool_result",
                    "data": {
                        "call_id": tool_call.get("id", "unknown"),
                        "name": tool_call["name"],
                        "result": result_content,
                        "success": is_success
                    },
                    
                }

            except Exception as e:
                error_msg = f"Error executing tool '{tool_call['name']}': {str(e)}"
                error_result = LLMMessage(
                    role="tool",
                    content=f"Error: {error_msg}",
                    tool_call_id=tool_call.get("id", "unknown")
                )
                tool_results.append(error_result)

                # Yield tool error event
                yield {
                    "type": "error",
                    "data": {
                        "call_id": tool_call.get("id", "unknown"),
                        "name": tool_call["name"],
                        "error": error_msg,
                        "success": False
                    },
                    
                }

        # Yield final results
        yield {
            "type": "tool_results",
            "results": tool_results,
            
        }

    async def _execute_tools_serially(
        self,
        tool_calls: List[Dict[str, Any]],
        **kwargs
    ) -> List[LLMMessage]:
        """Execute tools one by one (for write tools or mixed operations)"""
        tool_results = []

        for tool_call in tool_calls:
            try:
                result = await self._execute_single_tool(tool_call, **kwargs)
                tool_results.append(result)

                # Check for abort signal between tool executions
                if kwargs.get('abort_signal') and kwargs['abort_signal'].is_set():
                    break

            except Exception as e:
                error_msg = f"Error executing tool '{tool_call['name']}': {str(e)}"
                tool_results.append(LLMMessage(
                    role="tool",
                    content=f"Error: {error_msg}",
                    tool_call_id=tool_call.get("id", "unknown")
                ))

        return tool_results

    async def _execute_single_tool(
        self,
        tool_call: Dict[str, Any],
        **kwargs
    ) -> LLMMessage:
        """
        Execute a single tool and return the result as LLMMessage
        Based on original Claude Code implementation pattern
        """
        try:
            # Convert dict to ToolCall object (like original Claude Code)
            from pywen.utils.tool_basics import ToolCall
            tool_call_obj = ToolCall(
                call_id=tool_call.get("id", "unknown"),
                name=tool_call["name"],
                arguments=tool_call.get("arguments", {})
            )

            # 检查是否需要用户确认（基于工具风险等级）- 参照Qwen Agent实现
            if hasattr(self, 'cli_console') and self.cli_console:
                # 获取工具实例来检查风险等级
                tool = self.tool_registry.get_tool(tool_call["name"])
                if tool:
                    confirmation_details = await tool.get_confirmation_details(**tool_call.get("arguments", {}))
                    if confirmation_details:  # 只有需要确认的工具才询问用户
                        confirmed = await self.cli_console.confirm_tool_call(tool_call_obj, tool)
                        if not confirmed:
                            # 用户拒绝，返回取消消息
                            return LLMMessage(
                                role="tool",
                                content="Tool execution was cancelled by user",
                                tool_call_id=tool_call.get("id", "unknown")
                            )

            # Use tool executor (same pattern as QwenAgent and original Claude Code)
            results = await self.tool_executor.execute_tools([tool_call_obj], self.type)
            result = results[0]

            # Convert ToolResult to LLMMessage with proper content extraction
            if result.success:
                # Extract meaningful content from result
                if isinstance(result.result, dict):
                    # For structured results, use summary or convert to string
                    content = result.result.get('summary', str(result.result))
                else:
                    # For simple results, use as-is
                    content = str(result.result) if result.result is not None else "Operation completed successfully"
            else:
                # Handle error case
                content = f"Error: {result.error}" if result.error else "Tool execution failed"

            return LLMMessage(
                role="tool",
                content=content,
                tool_call_id=tool_call.get("id", "unknown")
            )

        except Exception as e:
            error_msg = f"Error executing tool '{tool_call['name']}': {str(e)}"

            return LLMMessage(
                role="tool",
                content=f"Error: {error_msg}",
                tool_call_id=tool_call.get("id", "unknown")
            )


    
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
                "Context-aware responses"
            ],
            "tools": [tool.name for tool in self.tools],
            "supports_streaming": True,
            "supports_sub_agents": True
        }
    
    def set_project_path(self, path: str):
        """Set the current project path"""
        if os.path.exists(path):
            self.project_path = path
            self._update_context()
        else:
            raise ValueError(f"Path does not exist: {path}")