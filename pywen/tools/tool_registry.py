import importlib
from typing import Dict, List, Optional, Any, Callable
from pywen.tools.base_tool import BaseTool

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._tool_factories: Dict[str, Callable] = {}
    
    def register(self, tool: BaseTool):
        """Register a tool."""
        self._tools[tool.name] = tool
    
    def get_tool(self, name: str) -> Optional[BaseTool]:
        """Get tool by name."""
        return self._tools.get(name)
    
    def list_tools(self) -> List[BaseTool]:
        """Get list of all registered tools."""
        return list(self._tools.values())
    
    def get_function_declarations(self) -> List[Dict[str, Any]]:
        """Get function declarations for all tools."""
        return [tool.get_function_declaration() for tool in self._tools.values()]
    
    def remove_tool(self, name: str) -> bool:
        """Remove a tool from registry."""
        if name in self._tools:
            del self._tools[name]
            return True
        return False
    
    def clear(self):
        """Clear all tools from registry."""
        self._tools.clear()
    
    def get_tool_names(self) -> List[str]:
        """Get list of tool names."""
        return list(self._tools.keys())

    def register_tool_factory(self, tool_name: str, factory: Callable):
        """Register a custom tool factory."""
        self._tool_factories[tool_name] = factory

    def create_and_register_tool(self, tool_name: str, config=None) -> bool:
        """Create and register a tool by name using factories."""
        if tool_name in self._tools:
            return True

        if tool_name not in self._tool_factories:
            return False

        try:
            tool_instance = self._tool_factories[tool_name](config)
            if tool_instance:
                self.register(tool_instance)
                return True
        except Exception as e:
            print(f"Failed to create tool {tool_name}: {e}")

        return False

    def register_tools_by_names(self, tool_names: List[str], config=None) -> List[str]:
        """Register multiple tools by names. Returns list of successfully registered tools."""
        registered = []
        for tool_name in tool_names:
            if self.create_and_register_tool(tool_name, config):
                registered.append(tool_name)
        return registered
