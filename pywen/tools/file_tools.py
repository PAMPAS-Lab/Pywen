import os
from typing import Any, Mapping
from pywen.ui.highlighted_content import HighlightedContentDisplay
from .base_tool import BaseTool, ToolResult, ToolRiskLevel
from pywen.core.tool_registry2 import register_tool

CLAUDE_DESCRIPTION_WRITE = """
Writes a file to the local filesystem.

Usage:
- This tool will overwrite the existing file if there is one at the provided path.
- If this is an existing file, you MUST use the Read tool first to read the file's contents. This tool will fail if you did not read the file first.
- ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required.
- NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.
- Only use emojis if the user explicitly requests it. Avoid writing emojis to files unless asked.
"""
@register_tool(name="write_file", providers=["claude", "qwen"])
class WriteFileTool(BaseTool):
    name="write_file"
    display_name="Write File"
    description="Write content to a file"
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
    }
    risk_level=ToolRiskLevel.MEDIUM 

    async def _generate_confirmation_message(self, **kwargs) -> str:
        """Generate detailed confirmation message with file preview."""
        path = kwargs.get("path", "")
        content = kwargs.get("content", "")

        file_exists = os.path.exists(path)

        if file_exists:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    old_content = f.read()

                import difflib
                old_lines = old_content.splitlines(keepends=True)
                new_lines = content.splitlines(keepends=True)

                diff_lines = list(difflib.unified_diff(
                    old_lines, new_lines,
                    fromfile=f"a/{path}", tofile=f"b/{path}",
                    n=3
                ))

                if diff_lines:
                    preview_lines = diff_lines[:20]
                    diff_text = ''.join(preview_lines)
                    if len(diff_lines) > 20:
                        diff_text += f"\n... ({len(diff_lines) - 20} more lines)"

                    return f"📝 Overwrite File: {path}\n\n{diff_text}"
                else:
                    return f"📝 Overwrite File: {path}\nNo changes detected"

            except Exception:
                return f"📝 Overwrite File: {path} (unable to read current content)"
        else:
            lines_count = len(content.splitlines())
            preview = f"📄 Create New File: {path}\n"
            preview += f"📊 Content: {lines_count} lines, {len(content)} characters\n\n"

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

        file_exists = os.path.exists(path)

        if file_exists:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    old_content = f.read()

                panel = HighlightedContentDisplay.create_side_by_side_comparison(
                    old_content, content, path,
                )

                return panel

            except Exception:
                return None
        else:
            panel = HighlightedContentDisplay.create_write_file_result_display(
                content, path, is_new_file=True,
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
            file_exists = os.path.exists(path)
            old_content = ""
            if file_exists:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        old_content = f.read()
                except:
                    old_content = ""

            directory = os.path.dirname(path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory)

            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

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

    def build(self, provider:str = "", func_type: str = "") -> Mapping[str, Any]:
        if provider.lower() == "claude" or provider.lower() == "anthropic":
            res = {
                "name": self.name,
                "description": CLAUDE_DESCRIPTION_WRITE,
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

CLAUDE_DESCRIPTION_READ = """
eads a file from the local filesystem. You can access any file directly by using this tool.

Assume this tool is able to read all files on the machine. If the User provides a path to a file assume that path is valid. It is okay to read a file that does not exist; an error will be returned.

Usage:
- The file_path parameter must be an absolute path, not a relative path
- By default, it reads up to 2000 lines starting from the beginning of the file
- You can optionally specify a line offset and limit (especially handy for long files), but it's recommended to read the whole file by not providing these parameters
- Any lines longer than 2000 characters will be truncated
- Results are returned using cat -n format, with line numbers starting at 1
- You have the capability to call multiple tools in a single response. It is always better to speculatively read multiple files as a batch that are potentially useful.
- If you read a file that exists but has empty contents you will receive a system reminder warning in place of file contents.
"""

@register_tool(name="read_file", providers=["claude", "qwen"])
class ReadFileTool(BaseTool):
    name="read_file"
    display_name="Read File"
    description="Read content from a file"
    parameter_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file"
                    }
                },
            "required": ["path"]
            }
    risk_level=ToolRiskLevel.SAFE

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

    def build(self, provider:str = "", func_type: str = "") -> Mapping[str, Any]:
        if provider.lower() == "claude" or provider.lower() == "anthropic":
            res = {
                "name": self.name,
                "description": CLAUDE_DESCRIPTION_READ,
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
