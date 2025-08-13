"""File operation tools."""

import os

from .base import BaseTool, ToolResult, ToolRiskLevel


class WriteFileTool(BaseTool):
    """Tool for writing to files."""

    def __init__(self):
        super().__init__(
            name="write_file",
            display_name="Write File",
            description="Write content to a file",
            parameter_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file"
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write"
                    }
                },
                "required": ["path", "content"]
            },
            risk_level=ToolRiskLevel.MEDIUM  # Writing files requires confirmation
        )
    
    async def execute(self, **kwargs) -> ToolResult:
        """Write content to a file."""
        path = kwargs.get("path")
        content = kwargs.get("content")
        
        if not path:
            return ToolResult(call_id="", error="No path provided")
        
        if content is None:
            return ToolResult(call_id="", error="No content provided")
        
        try:
            # Check if file exists to determine if this is a new file or overwrite
            file_exists = os.path.exists(path)
            old_content = ""
            if file_exists:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        old_content = f.read()
                except:
                    old_content = ""

            # Create directory if it doesn't exist
            directory = os.path.dirname(path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory)

            # Write to file
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

            # Return detailed result
            return ToolResult(
                call_id="",
                result={
                    "message": f"Successfully wrote {len(content)} characters to {path}",
                    "file_path": path,
                    "content": content,
                    "old_content": old_content if file_exists else None,
                    "is_new_file": not file_exists,
                    "operation": "write_file"
                }
            )
        
        except Exception as e:
            return ToolResult(call_id="", error=f"Error writing to file: {str(e)}")


class ReadFileTool(BaseTool):
    """Tool for reading files."""

    def __init__(self):
        super().__init__(
            name="read_file",
            display_name="Read File",
            description="Read content from a file",
            parameter_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file"
                    }
                },
                "required": ["path"]
            },
            risk_level=ToolRiskLevel.SAFE  # Reading files is safe
        )
    
    async def execute(self, **kwargs) -> ToolResult:
        """Read content from a file."""
        path = kwargs.get("path")
        
        if not path:
            return ToolResult(call_id="", error="No path provided")
        
        try:
            if not os.path.exists(path):
                return ToolResult(call_id="", error=f"File not found at {path}")
            
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            
            return ToolResult(call_id="", result=content)
        
        except Exception as e:
            return ToolResult(call_id="", error=f"Error reading file: {str(e)}")




