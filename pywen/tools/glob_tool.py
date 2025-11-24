import glob
from typing import Any, Mapping
from .base_tool import BaseTool, ToolResult
from pywen.core.tool_registry2 import register_tool

CLAUDE_DESCRIPTION = """
- Fast file pattern matching tool that works with any codebase size
- Supports glob patterns like "**/*.js" or "src/**/*.ts"
- Returns matching file paths sorted by modification time
- Use this tool when you need to find files by name patterns
- When you are doing an open ended search that may require multiple rounds of globbing and grepping, use the Agent tool instead
- You have the capability to call multiple tools in a single response. It is always better to speculatively perform multiple searches as a batch that are potentially useful.
"""

@register_tool(name="glob", providers=["claude", "qwen",])
class GlobTool(BaseTool):
    name="glob"
    display_name="Find Files"
    description="Find files using glob patterns"
    parameter_schema={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match files (e.g., '*.py', '**/*.txt')"
            },
            "recursive": {
                "type": "boolean",
                "description": "Enable recursive search (default: true)",
                "default": True
            }
        },
        "required": ["pattern"]
    }
    
    async def execute(self, **kwargs) -> ToolResult:
        """Find files using glob pattern."""
        pattern = kwargs.get("pattern")
        recursive = kwargs.get("recursive", True)
        
        if not pattern:
            return ToolResult(call_id="", error="No pattern provided")
        
        try:
            if recursive:
                matches = glob.glob(pattern, recursive=True)
            else:
                matches = glob.glob(pattern)
            
            if not matches:
                return ToolResult(call_id="", result="No files found matching pattern")
            
            matches.sort()
            
            return ToolResult(call_id="", result="\n".join(matches))
        
        except Exception as e:
            return ToolResult(call_id="", error=f"Error finding files: {str(e)}")

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
