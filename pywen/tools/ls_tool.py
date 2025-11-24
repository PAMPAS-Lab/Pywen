import os
from typing import Any, Mapping
from .base_tool import BaseTool, ToolResult
from pywen.core.tool_registry2 import register_tool

CLAUDE_DESCRIPTION = """
Lists files and directories in a given path. 
The path parameter must be an absolute path, not a relative path. 
You can optionally provide an array of glob patterns to ignore with the ignore parameter. 
You should generally prefer the Glob and Grep tools, if you know which directories to search.
"""

@register_tool(name="ls", providers=["claude", "qwen",])
class LSTool(BaseTool):
    name="ls"
    display_name="List Directory"
    description="List contents of a directory"
    parameter_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path to list (default: current directory)",
                "default": "."
            },
            "show_hidden": {
                "type": "boolean",
                "description": "Show hidden files and directories",
                "default": False
            }
        }
    }
    
    async def execute(self, **kwargs) -> ToolResult:
        """List directory contents."""
        path = kwargs.get("path", ".")
        show_hidden = kwargs.get("show_hidden", False)
        
        try:
            if not os.path.exists(path):
                return ToolResult(call_id="", error=f"Path not found: {path}")
            
            if not os.path.isdir(path):
                return ToolResult(call_id="", error=f"Path is not a directory: {path}")
            
            items = []
            for item in os.listdir(path):
                if not show_hidden and item.startswith('.'):
                    continue
                
                item_path = os.path.join(path, item)
                if os.path.isdir(item_path):
                    items.append(f"{item}/")
                else:
                    items.append(item)
            
            if not items:
                return ToolResult(call_id="", result="Directory is empty")
            
            return ToolResult(call_id="", result="\n".join(sorted(items)))
        
        except Exception as e:
            return ToolResult(call_id="", error=f"Error listing directory: {str(e)}")

    def build(self, provider:str = "", func_type: str = "") -> Mapping[str, Any]:
        if provider.lower() == "claude" or provider.lower() == "anthropic":
            res = {
                "name": self.name,
                "description": CLAUDE_DESCRIPTION,
                "input_schema": self.parameter_schema,
            }
        else:
            res = {
                "type": "function",
                "function": {
                    "name": self.name,
                    "description": self.description,
                    "parameters": self.parameter_schema
                }
            }
        return res
