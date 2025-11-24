import os
from typing import Any, Mapping
from .base_tool import BaseTool, ToolResult, ToolRiskLevel
from pywen.core.tool_registry2 import register_tool

CLAUDE_DESCRIPTION = """
Performs exact string replacements in files.

Usage:
- You must use your `Read` tool at least once in the conversation before editing. This tool will error if you attempt an edit without reading the file.
- When editing text from Read tool output, ensure you preserve the exact indentation (tabs/spaces) as it appears AFTER the line number prefix. The line number prefix format is: spaces + line number + tab. Everything after that tab is the actual file content to match. Never include any part of the line number prefix in the old_string or new_string.
- ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required.
- Only use emojis if the user explicitly requests it. Avoid adding emojis to files unless asked.
- The edit will FAIL if `old_string` is not unique in the file. Either provide a larger string with more surrounding context to make it unique or use `replace_all` to change every instance of `old_string`.
- Use `replace_all` for replacing and renaming strings across the file. This parameter is useful if you want to rename a variable for instance.
"""

@register_tool(name="edit", providers=["claude", "qwen"])
class EditTool(BaseTool):
    name="edit"
    display_name="Edit File"
    description="Edit files by replacing text"
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
    }
    risk_level=ToolRiskLevel.MEDIUM

    async def _generate_confirmation_message(self, **kwargs) -> str:
        """Generate detailed confirmation message with diff preview."""
        path = kwargs.get("path", "")
        old_str = kwargs.get("old_str", "")
        new_str = kwargs.get("new_str", "")

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            if old_str not in content:
                content_normalized = content.replace('\r\n', '\n').replace('\r', '\n')
                old_str_normalized = old_str.replace('\r\n', '\n').replace('\r', '\n')
                
                if old_str_normalized not in content_normalized:
                    lines = content.split('\n')
                    for i, line in enumerate(lines, 1):
                        if any(word in line for word in old_str.split() if len(word) > 2):
                            return f"📝 Edit File: {path}\n💡 Similar text found on line {i}: '{line.strip()}'\n🔍 Searching for: '{old_str}'"
                    return f"📝 Edit File: {path}\n⚠️ Text to replace not found: '{old_str}'\n📄 Current file has {len(lines)} lines"

            new_content = content.replace(old_str, new_str)

            import difflib
            old_lines = content.splitlines(keepends=True)
            new_lines = new_content.splitlines(keepends=True)

            diff_lines = list(difflib.unified_diff(
                old_lines, new_lines,
                fromfile=f"a/{path}", tofile=f"b/{path}",
                n=3
            ))

            if diff_lines:
                # Show first few lines of diff
                preview_lines = diff_lines[:15]  # Limit to first 15 lines
                diff_text = ''.join(preview_lines)
                if len(diff_lines) > 15:
                    diff_text += f"\n... ({len(diff_lines) - 15} more lines)"

                return f"📝 Edit File: {path}\n\n{diff_text}"
            else:
                return f"📝 Edit File: {path}\nNo changes detected"

        except Exception as e:
            return f"Edit {path}: {old_str} → {new_str} (Preview error: {e})"

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
            
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            
            if old_str not in content:
                content_normalized = content.replace('\r\n', '\n').replace('\r', '\n')
                old_str_normalized = old_str.replace('\r\n', '\n').replace('\r', '\n')
                
                if old_str_normalized not in content_normalized:
                    return ToolResult(call_id="", error=f"Text to replace not found in file: '{old_str}'")
                else:
                    content = content_normalized
                    old_str = old_str_normalized
            
            new_content = content.replace(old_str, new_str)

            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)

            return ToolResult(
                    call_id="",
                    result={
                            "operation": "edit_file",
                            "file_path": path,
                            "old_content": content,
                            "new_content": new_content,
                            "old_text": old_str,
                            "new_text": new_str,
                            "summary": f"✅ Successfully edited {path}\n📝 Changed: '{old_str}' → '{new_str}'\n🎯 Task completed - file modification successful"
                        },
                    )
        
        except Exception as e:
            return ToolResult(call_id="", error=f"Error editing file: {str(e)}")

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
