from typing import List, Dict, Any
from pywen.utils.tool_basics import ToolCall, ToolResult
from pywen.core.tool_registry import ToolRegistry
from pywen.core.tool_scheduler import CoreToolScheduler

class ToolExecutor:
    """Non-interactive tool executor for batch processing."""
    
    def __init__(self, tool_registry: ToolRegistry):
        self.tool_registry = tool_registry
        self.scheduler = CoreToolScheduler(tool_registry)
    
    async def execute_tools(self, tool_calls: List[ToolCall], agent_name: str = '') -> List[ToolResult]:
        """Execute multiple tool calls non-interactively."""
        if not tool_calls:
            return []
        results = await self.scheduler.schedule_tool_calls(tool_calls, agent_name)
        
        return results
