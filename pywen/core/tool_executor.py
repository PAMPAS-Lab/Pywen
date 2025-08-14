"""Non-interactive tool executor."""

import sys
from pathlib import Path
from typing import List, Dict, Any

from pywen.utils.tool_basics import ToolCall, ToolResult
from pywen.core.tool_registry import ToolRegistry
from pywen.core.tool_scheduler import CoreToolScheduler
from pywen.core.session_stats import session_stats


class NonInteractiveToolExecutor:
    """Non-interactive tool executor for batch processing."""
    
    def __init__(self, tool_registry: ToolRegistry):
        self.tool_registry = tool_registry
        self.scheduler = CoreToolScheduler(tool_registry)
    
    async def execute_tools(self, tool_calls: List[ToolCall], agent_name: str = None) -> List[ToolResult]:
        """Execute multiple tool calls non-interactively."""
        if not tool_calls:
            return []
        
        # Use scheduler for execution
        results = await self.scheduler.schedule_tool_calls(tool_calls, agent_name)
        
        return results
    
    def get_available_tools(self) -> List[str]:
        """Get list of available tool names."""
        return [tool.name for tool in self.tool_registry.get_all_tools()]
    
    def get_tool_declarations(self) -> List[Dict[str, Any]]:
        """Get function declarations for all available tools."""
        return self.tool_registry.get_function_declarations()
    
    async def execute_tool_call(self, tool_call: ToolCall, console=None, agent_name: str = None) -> ToolResult:
        """Execute a tool call with confirmation if needed."""
        try:
            # 获取工具实例
            tool = self.tool_registry.get_tool(tool_call.name)  # 使用 name 而不是 tool_name
            if not tool:
                return ToolResult(
                    call_id=tool_call.call_id,
                    error=f"Tool '{tool_call.name}' not found"
                )
            
            # 检查是否需要用户确认
            confirmation_details = await tool.get_confirmation_details(**tool_call.arguments)
            if confirmation_details and console and hasattr(console, 'confirm_tool_call'):
                if not console.confirm_tool_call(tool_call):
                    return ToolResult(
                        call_id=tool_call.call_id,
                        error="User cancelled tool execution"
                    )
            
            # 执行工具
            result = await tool.execute(**tool_call.arguments)

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
                error=str(e)
            )
