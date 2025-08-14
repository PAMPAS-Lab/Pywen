"""Core tool scheduler for managing tool execution."""

import asyncio
import uuid
import sys
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass


from pywen.utils.tool_basics import ToolCall, ToolResult
from pywen.core.tool_registry import ToolRegistry
from pywen.core.session_stats import session_stats


@dataclass
class ScheduledTask:
    """Represents a scheduled tool execution task."""
    id: str
    tool_call: ToolCall
    priority: int = 0
    max_retries: int = 3
    current_retry: int = 0


class CoreToolScheduler:
    """Core scheduler for managing tool execution."""
    
    def __init__(self, tool_registry: ToolRegistry):
        self.tool_registry = tool_registry
        self.task_queue: List[ScheduledTask] = []
        self.running_tasks: Dict[str, asyncio.Task] = {}
        self.max_concurrent_tasks = 5
    
    async def schedule_tool_calls(self, tool_calls: List[ToolCall], agent_name: str = None) -> List[ToolResult]:
        """Schedule multiple tool calls for execution."""
        tasks = []
        for tool_call in tool_calls:
            task = ScheduledTask(
                id=str(uuid.uuid4()),
                tool_call=tool_call
            )
            tasks.append(task)
        
        # Execute tasks concurrently
        results = await asyncio.gather(
            *[self._execute_task(task, agent_name) for task in tasks],
            return_exceptions=True
        )
        
        # Process results
        tool_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                tool_results.append(ToolResult(
                    call_id=tasks[i].tool_call.id,
                    content="",
                    error=str(result)
                ))
            else:
                tool_results.append(result)
        
        return tool_results
    
    async def _execute_task(self, task: ScheduledTask, agent_name: str = None) -> ToolResult:
        """Execute a single scheduled task."""
        tool_call = task.tool_call
        tool = self.tool_registry.get_tool(tool_call.name)
        
        if not tool:
            return ToolResult(
                call_id=tool_call.call_id,
                content="",
                error=f"Tool not found: {tool_call.name}"
            )
        
        try:
            result = await tool.execute(**tool_call.arguments)
            result.tool_call_id = tool_call.call_id

            # Record tool call in session stats
            session_stats.record_tool_call(
                tool_name=tool_call.name,
                success=result.success,
                agent_name=agent_name
            )

            return result

        except Exception as e:
            # Record failed tool call in session stats
            session_stats.record_tool_call(
                tool_name=tool_call.name,
                success=False,
                agent_name=agent_name
            )

            return ToolResult(
                call_id=tool_call.call_id,
                content="",
                error=f"Tool execution failed: {str(e)}"
            )
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Get current queue status."""
        return {
            "queued_tasks": len(self.task_queue),
            "running_tasks": len(self.running_tasks),
            "max_concurrent": self.max_concurrent_tasks
        }
