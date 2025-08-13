"""Enhanced tool registry matching TypeScript version."""

import importlib
from typing import Dict, List, Optional, Any, Callable
from pywen.tools.base import BaseTool


class ToolRegistry:
    """Registry for managing available tools."""

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._tool_factories: Dict[str, Callable] = {}
        self._setup_default_tool_factories()
    
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

    def _setup_default_tool_factories(self):
        """Setup default tool factories for common tools."""
        self._tool_factories = {
            # File tools
            'read_file': lambda config=None: self._import_and_create('pywen.tools.file_tools', 'ReadFileTool'),
            'write_file': lambda config=None: self._import_and_create('pywen.tools.file_tools', 'WriteFileTool'),
            'edit_file': lambda config=None: self._import_and_create('pywen.tools.edit_tool', 'EditTool'),
            'read_many_files': lambda config=None: self._import_and_create('pywen.tools.read_many_files_tool', 'ReadManyFilesTool'),

            # File system tools
            'ls': lambda config=None: self._import_and_create('pywen.tools.ls_tool', 'LSTool'),
            'grep': lambda config=None: self._import_and_create('pywen.tools.grep_tool', 'GrepTool'),
            'glob': lambda config=None: self._import_and_create('pywen.tools.glob_tool', 'GlobTool'),

            # System tools
            'bash': lambda config=None: self._import_and_create('pywen.tools.bash_tool', 'BashTool'),

            # Web tools
            'web_fetch': lambda config=None: self._import_and_create('pywen.tools.web_fetch_tool', 'WebFetchTool'),
            'web_search': lambda config=None: self._import_and_create('pywen.tools.web_search_tool', 'WebSearchTool', config),

            # Memory tools
            'memory': lambda config=None: self._import_and_create('pywen.tools.memory_tool', 'MemoryTool'),

            # Claude Code Agent specific tools
            'agent_tool': lambda config=None: self._import_and_create('pywen.agents.claudecode.tools.agent_tool', 'AgentTool', config),
            'architect_tool': lambda config=None: self._import_and_create('pywen.agents.claudecode.tools.architect_tool', 'ArchitectTool', config),
        }

    def _import_and_create(self, module_name: str, class_name: str, *args):
        """Dynamically import and create tool instance."""
        try:
            module = importlib.import_module(module_name)
            tool_class = getattr(module, class_name)
            return tool_class(*args)
        except Exception as e:
            raise ImportError(f"Failed to import {class_name} from {module_name}: {e}")

    def register_tool_factory(self, tool_name: str, factory: Callable):
        """Register a custom tool factory."""
        self._tool_factories[tool_name] = factory

    def create_and_register_tool(self, tool_name: str, config=None) -> bool:
        """Create and register a tool by name using factories."""
        if tool_name in self._tools:
            return True  # Already registered

        if tool_name not in self._tool_factories:
            return False  # No factory available

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

