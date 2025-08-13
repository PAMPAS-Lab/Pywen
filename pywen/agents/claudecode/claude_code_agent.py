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

logger = logging.getLogger(__name__)


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

        # Initialize model and tools from base agent
        self.model = self.llm_client

        # Setup Claude Code specific tools after base tools
        self._setup_claude_code_tools()

        self.tools = self.tool_registry.list_tools()

        self._update_context()

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
            logger.warning(f"Failed to build full context: {e}")
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
                provider=getattr(self.model, 'provider', "unknown"),
                model=getattr(self.model, 'model', "unknown"),
                max_steps=self.max_iterations
            )

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

            # End trajectory recording
            self.trajectory_recorder.end_recording(success=True, final_result="Task completed")

        except Exception as e:
            logger.error(f"Error in Claude Code Agent run: {e}")
            yield {
                "type": "error",
                "content": f"Agent error: {str(e)}",
                "agent_type": self.type
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
            # � TRAJECTORY: Record recursion start


            # 🔢 DEPTH CONTROL: Check max iterations
            if depth >= self.max_iterations:

                yield {
                    "type": "max_iterations_reached",
                    "content": f"Maximum iterations ({self.max_iterations}) reached",
                    "depth": depth,
                    "agent_type": self.type
                }
                return

            # Check for abort signal
            if kwargs.get('abort_signal') and kwargs['abort_signal'].is_set():

                yield {
                    "type": "final",
                    "content": "Operation was cancelled",
                    "agent_type": self.type
                }
                return



            # 📝 TRAJECTORY: Record agent step start
            self.trajectory_recorder.record_agent_step(
                step_number=depth,
                state=f"llm_request_depth_{depth}",
                llm_messages=messages
            )

            # Get assistant response with fine-grained streaming events
            assistant_message, tool_calls = None, []
            async for response_event in self._get_assistant_response_streaming(messages, depth=depth, **kwargs):
                if response_event["type"] in ["llm_stream_start", "llm_chunk"]:
                    # Forward streaming events to caller
                    yield response_event
                elif response_event["type"] == "assistant_response":
                    # Extract final response
                    assistant_message = response_event["assistant_message"]
                    tool_calls = response_event["tool_calls"]

            # 📝 TRAJECTORY: Record LLM interaction
            if assistant_message:
                # Create LLMResponse object for trajectory recording
                llm_response = LLMResponse(
                    content=assistant_message.content or "",
                    tool_calls=[ToolCall(
                        call_id=tc.get("id", "unknown"),
                        name=tc.get("name", ""),
                        arguments=tc.get("arguments", {})
                    ) for tc in tool_calls] if tool_calls else None,
                    model=getattr(self.model, 'model', "unknown"),
                    finish_reason="stop"
                )

                self.trajectory_recorder.record_llm_interaction(
                    messages=messages,
                    response=llm_response,
                    provider=getattr(self.model, 'provider', "unknown"),
                    model=getattr(self.model, 'model', "unknown"),
                    current_task=f"depth_{depth}_query"
                )


            # TOP CONDITION: No tool calls means we're done
            if not tool_calls:

                yield {
                    "type": "final",
                    "content": assistant_message.content if assistant_message else "",
                    "agent_type": self.type
                }
                return

            # Yield tool call events for each tool
            for tool_call in tool_calls:
                # 📝 TRAJECTORY: Record tool call as agent step
                tool_call_obj = ToolCall(
                    call_id=tool_call.get("id", "unknown"),
                    name=tool_call["name"],
                    arguments=tool_call.get("arguments", {})
                )

                self.trajectory_recorder.record_agent_step(
                    step_number=depth,
                    state=f"tool_call_{tool_call['name']}",
                    tool_calls=[tool_call_obj]
                )

                yield {
                    "type": "tool_call_start",
                    "data": {
                        "call_id": tool_call.get("id", "unknown"),
                        "name": tool_call["name"],
                        "arguments": tool_call.get("arguments", {})
                    },
                    "agent_type": self.type
                }

            # Execute tools and get results with streaming events
            tool_results = []
            async for tool_event in self._execute_tools_with_strategy_streaming(tool_calls, depth=depth, **kwargs):
                if tool_event["type"] in ["tool_start", "tool_result", "tool_error"]:
                    # 📝 TRAJECTORY: Record tool results
                    if tool_event["type"] == "tool_result":
                        tool_data = tool_event.get("data", {})

                        # Create ToolResult object for trajectory recording
                        from pywen.utils.tool_basics import ToolResult
                        tool_result_obj = ToolResult(
                            call_id=tool_data.get("call_id", "unknown"),
                            result=tool_data.get("result", "") if tool_data.get("success", True) else None,
                            error=None if tool_data.get("success", True) else tool_data.get("result", "Tool execution failed"),
                            metadata={"tool_name": tool_data.get("name", "unknown")}
                        )

                        self.trajectory_recorder.record_agent_step(
                            step_number=depth,
                            state=f"tool_result_{tool_data.get('name', 'unknown')}",
                            tool_results=[tool_result_obj]
                        )

                    # Forward tool events to caller
                    yield tool_event
                elif tool_event["type"] == "tool_results":
                    # Extract final results
                    tool_results = tool_event["results"]

            # Check for abort signal after tool execution
            if kwargs.get('abort_signal') and kwargs['abort_signal'].is_set():
                yield {
                    "type": "final",
                    "content": "Operation was cancelled during tool execution",
                    "agent_type": self.type
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
            logger.error(f"Error in recursive query: {e}")
            yield {
                "type": "error",
                "content": f"Query error: {str(e)}",
                "agent_type": self.type
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
            # Try streaming first
            if kwargs.get('stream', True):
                try:
                    response_generator = await self.model.generate_response(
                        messages=messages,
                        tools=self.tools,
                        stream=True
                    )

                    # Yield stream start event
                    yield {
                        "type": "llm_stream_start",
                        "data": {"depth": depth},
                        "agent_type": self.type
                    }

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
                                    # Yield streaming content chunk
                                    yield {
                                        "type": "llm_chunk",
                                        "data": {"content": new_content},
                                        "agent_type": self.type
                                    }
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

                    # Yield final assistant response
                    yield {
                        "type": "assistant_response",
                        "assistant_message": assistant_msg,
                        "tool_calls": tool_calls,
                        "agent_type": self.type
                    }
                    return

                except Exception as e:
                    logger.warning(f"Streaming failed, falling back to non-streaming: {e}")

            # Non-streaming fallback
            response = await self.model.generate_response(
                messages=messages,
                tools=self.tools,
                stream=False
            )

            assistant_content = response.content
            tool_calls = []

            # Yield content for non-streaming mode
            if assistant_content:
                yield {
                    "type": "content",
                    "content": assistant_content,
                    "agent_type": self.type
                }

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

            # Yield final assistant response
            yield {
                "type": "assistant_response",
                "assistant_message": assistant_msg,
                "tool_calls": tool_calls,
                "agent_type": self.type
            }
            return

        except Exception as e:
            logger.error(f"Error getting assistant response: {e}")
            error_msg = LLMMessage(role="assistant", content=f"Error: {str(e)}")
            yield {
                "type": "assistant_response",
                "assistant_message": error_msg,
                "tool_calls": [],
                "agent_type": self.type
            }
            return

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
                    response_generator = await self.model.generate_response(
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
                    logger.warning(f"Streaming failed, falling back to non-streaming: {e}")

            # Non-streaming fallback
            response = await self.model.generate_response(
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
            logger.error(f"Error getting assistant response: {e}")
            error_msg = LLMMessage(role="assistant", content=f"Error: {str(e)}")
            return error_msg, []


    async def _execute_tools_with_strategy_streaming(
        self,
        tool_calls: List[Dict[str, Any]],
        depth: int = 0,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Execute tools with intelligent concurrency strategy (streaming version)
        - Read-only tools: Execute concurrently
        - Write tools: Execute serially
        """
        if not tool_calls:
            yield {
                "type": "tool_results",
                "results": [],
                "agent_type": self.type
            }
            return

        # Check if all tools are read-only
        all_readonly = all(self._is_tool_readonly(tc["name"]) for tc in tool_calls)

        if all_readonly and len(tool_calls) > 1:
            # Execute read-only tools concurrently
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
                    "agent_type": self.type
                }

                result = await self._execute_single_tool(tool_call, **kwargs)
                tool_results.append(result)

                # Yield tool result event
                # Use result.result if it's structured data, otherwise use result.content
                result_data = result.result if hasattr(result, 'result') and result.result is not None else result.content

                yield {
                    "type": "tool_result",
                    "data": {
                        "call_id": tool_call.get("id", "unknown"),
                        "name": tool_call["name"],
                        "result": result_data,
                        "success": True
                    },
                    "agent_type": self.type
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
                    "type": "tool_error",
                    "data": {
                        "call_id": tool_call.get("id", "unknown"),
                        "name": tool_call["name"],
                        "error": error_msg,
                        "success": False
                    },
                    "agent_type": self.type
                }

        # Yield final results
        yield {
            "type": "tool_results",
            "results": tool_results,
            "agent_type": self.type
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
                "agent_type": self.type
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

                # Yield tool result event
                yield {
                    "type": "tool_result",
                    "data": {
                        "call_id": tool_call.get("id", "unknown"),
                        "name": tool_call["name"],
                        "result": result.content,
                        "success": True
                    },
                    "agent_type": self.type
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
                    "type": "tool_error",
                    "data": {
                        "call_id": tool_call.get("id", "unknown"),
                        "name": tool_call["name"],
                        "error": error_msg,
                        "success": False
                    },
                    "agent_type": self.type
                }

        # Yield final results
        yield {
            "type": "tool_results",
            "results": tool_results,
            "agent_type": self.type
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
        """Execute a single tool and return the result as LLMMessage"""
        try:
            # Find the tool
            tool = self._find_tool(tool_call["name"])
            if not tool:
                error_msg = f"Tool '{tool_call['name']}' not found"
                return LLMMessage(
                    role="tool",
                    content=f"Error: {error_msg}",
                    tool_call_id=tool_call.get("id", "unknown")
                )

            # Check if tool needs confirmation
            if hasattr(self, 'cli_console') and self.cli_console:
                confirmation_details = await tool.get_confirmation_details(**tool_call.get("arguments", {}))
                if confirmation_details:  # Only ask for confirmation if needed
                    # Create a ToolCall-like object for confirmation
                    from pywen.utils.tool_basics import ToolCall
                    tool_call_obj = ToolCall(
                        call_id=tool_call.get("id", "unknown"),
                        name=tool_call["name"],
                        arguments=tool_call.get("arguments", {})
                    )
                    confirmed = await self.cli_console.confirm_tool_call(tool_call_obj, tool)
                    if not confirmed:
                        # User rejected the tool execution
                        return LLMMessage(
                            role="tool",
                            content="Tool execution was cancelled by user",
                            tool_call_id=tool_call.get("id", "unknown")
                        )

            # Execute tool
            result = await tool.execute(**tool_call.get("arguments", {}))

            # Return successful result
            return LLMMessage(
                role="tool",
                content=str(result),
                tool_call_id=tool_call.get("id", "unknown")
            )

        except Exception as e:
            error_msg = f"Error executing tool '{tool_call['name']}': {str(e)}"
            if self.cli_console:
                self.cli_console.print(error_msg, "red")

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