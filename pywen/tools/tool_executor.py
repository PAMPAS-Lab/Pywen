from typing import List, Dict, Any
from pywen.utils.tool_basics import ToolCall, ToolResult
from pywen.tools.tool_registry import ToolRegistry
from pywen.tools.tool_scheduler import CoreToolScheduler

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
    
    def get_available_tools(self) -> List[str]:
        """Get list of available tool names."""
        return [tool.name for tool in self.tool_registry.list_tools()]
    
    def get_tool_declarations(self) -> List[Dict[str, Any]]:
        """Get function declarations for all available tools."""
        return self.tool_registry.get_function_declarations()
    
