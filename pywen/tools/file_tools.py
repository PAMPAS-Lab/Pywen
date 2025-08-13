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

    async def _generate_confirmation_message(self, **kwargs) -> str:
        """Generate detailed confirmation message with file preview."""
        path = kwargs.get("path", "")
        content = kwargs.get("content", "")

        # Check if file exists
        file_exists = os.path.exists(path)

        if file_exists:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    old_content = f.read()

                # Generate actual diff preview for file overwrite
                import difflib
                old_lines = old_content.splitlines(keepends=True)
                new_lines = content.splitlines(keepends=True)

                diff_lines = list(difflib.unified_diff(
                    old_lines, new_lines,
                    fromfile=f"a/{path}", tofile=f"b/{path}",
                    n=3
                ))

                if diff_lines:
                    # Show first few lines of diff
                    preview_lines = diff_lines[:20]  # Limit to first 20 lines
                    diff_text = ''.join(preview_lines)
                    if len(diff_lines) > 20:
                        diff_text += f"\n... ({len(diff_lines) - 20} more lines)"

                    return f"📝 Overwrite File: {path}\n\n{diff_text}"
                else:
                    return f"📝 Overwrite File: {path}\nNo changes detected"

            except Exception:
                return f"📝 Overwrite File: {path} (unable to read current content)"
        else:
            # New file
            lines_count = len(content.splitlines())
            preview = f"📄 Create New File: {path}\n"
            preview += f"📊 Content: {lines_count} lines, {len(content)} characters\n\n"

            # Show first few lines as preview
            lines = content.splitlines()
            preview_lines = lines[:5]
            for i, line in enumerate(preview_lines, 1):
                preview += f"{i:2d}| {line}\n"

            if len(lines) > 5:
                preview += f"... ({len(lines) - 5} more lines)"

            return preview

    async def _generate_confirmation_panel(self, **kwargs):
        """Generate Rich Panel with side-by-side diff preview."""
        path = kwargs.get("path", "")
        content = kwargs.get("content", "")

        # Check if file exists
        file_exists = os.path.exists(path)

        if file_exists:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    old_content = f.read()

                # Generate side-by-side comparison panel
                from pywen.ui.diff_display import DiffDisplay

                panel = DiffDisplay.create_side_by_side_comparison(
                    old_content, content, path, max_lines=20
                )

                return panel

            except Exception:
                return None
        else:
            # For new files, show content preview
            from pywen.ui.highlighted_content import HighlightedContentDisplay

            panel = HighlightedContentDisplay.create_write_file_result_display(
                content, path, is_new_file=True, max_lines=15
            )

            return panel

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

            # Return result with content information for display
            lines_count = len(content.splitlines())
            return ToolResult(
                call_id="",
                result={
                    "operation": "write_file",
                    "file_path": path,
                    "content": content,
                    "old_content": old_content if file_exists else None,
                    "is_new_file": not file_exists,
                    "lines_count": lines_count,
                    "chars_count": len(content),
                    "summary": f"Successfully {'overwrote' if file_exists else 'created'} {path} ({lines_count} lines, {len(content)} characters\ncontent:{content})"
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




