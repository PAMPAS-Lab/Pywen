"""File editing tool."""

import os

from .base import BaseTool, ToolResult, ToolRiskLevel


class EditTool(BaseTool):
    """Tool for editing files using string replacement."""
    
    def __init__(self):
        super().__init__(
            name="edit",
            display_name="Edit File",
            description="Edit files by replacing text",
            parameter_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to edit"
                    },
                    "old_str": {
                        "type": "string",
                        "description": "Text to replace"
                    },
                    "new_str": {
                        "type": "string",
                        "description": "Replacement text"
                    }
                },
                "required": ["path", "old_str", "new_str"]
            },
            risk_level=ToolRiskLevel.MEDIUM  # Editing files requires confirmation
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Edit file by replacing text."""
        path = kwargs.get("path")
        old_str = kwargs.get("old_str")
        new_str = kwargs.get("new_str")
        
        if not path:
            return ToolResult(call_id="", error="No path provided")
        
        if old_str is None:
            return ToolResult(call_id="", error="No old_str provided")
        
        if new_str is None:
            return ToolResult(call_id="", error="No new_str provided")
        
        try:
            if not os.path.exists(path):
                return ToolResult(call_id="", error=f"File not found: {path}")
            
            # Read file content
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            
            # Check if old_str exists
            if old_str not in content:
                return ToolResult(call_id="", error=f"Text to replace not found in file: {old_str}")
            
            # Replace text
            new_content = content.replace(old_str, new_str)

            # Write back to file
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)

            # Return detailed result with diff information
            return ToolResult(
                call_id="",
                result={
                    "message": f"Successfully replaced text in {path}",
                    "file_path": path,
                    "old_text": old_str,
                    "new_text": new_str,
                    "operation": "edit_file"
                }
            )
        
        except Exception as e:
            return ToolResult(call_id="", error=f"Error editing file: {str(e)}")
