"""
Diff display utilities for showing file changes in a user-friendly format.
"""
import difflib
from typing import List
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text

class DiffDisplay:
    """Utility class for displaying file diffs in various formats."""
    
    @staticmethod
    def create_side_by_side_diff(
        old_content: str, 
        new_content: str, 
        old_label: str = "Before", 
        new_label: str = "After",
        context_lines: int = 3
    ) -> Panel:
        """Create a side-by-side diff display."""
        
        old_lines = old_content.splitlines(keepends=False)
        new_lines = new_content.splitlines(keepends=False)
        
        # Generate unified diff to understand changes
        diff = list(difflib.unified_diff(
            old_lines, new_lines, 
            fromfile=old_label, tofile=new_label,
            n=context_lines, lineterm=""
        ))
        
        # Create side-by-side display
        left_panel = DiffDisplay._create_file_panel(old_lines, old_label, "red")
        right_panel = DiffDisplay._create_file_panel(new_lines, new_label, "green")
        
        # Create columns layout
        columns = Columns([left_panel, right_panel], equal=True, expand=True)
        
        return Panel(
            columns,
            title="📝 File Changes",
            title_align="left",
            border_style="blue",
            padding=(0, 1)
        )
    
    @staticmethod
    def _create_file_panel(lines: List[str], label: str, color: str) -> Panel:
        """Create a panel for one side of the diff."""
        content = Text()
        
        for i, line in enumerate(lines, 1):
            line_num = f"{i:3d} "
            content.append(line_num, style="dim")
            content.append(line, style=color if color == "green" else "white")
            content.append("\n")
        
        return Panel(
            content,
            title=label,
            title_align="left",
            border_style=color,
            padding=(0, 1)
        )
    
    @staticmethod
    def create_unified_diff(
        old_content: str, 
        new_content: str, 
        file_path: str = "file",
        context_lines: int = 3
    ) -> Panel:
        """Create a unified diff display (like git diff)."""
        
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        
        diff_lines = list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{file_path}", tofile=f"b/{file_path}",
            n=context_lines
        ))
        
        if not diff_lines:
            return Panel(
                Text("No changes detected", style="dim"),
                title="📝 Diff",
                border_style="blue"
            )
        
        content = Text()
        for line in diff_lines:
            line = line.rstrip('\n')
            if line.startswith('+++') or line.startswith('---'):
                content.append(line, style="bold blue")
            elif line.startswith('@@'):
                content.append(line, style="bold cyan")
            elif line.startswith('+'):
                content.append(line, style="green")
            elif line.startswith('-'):
                content.append(line, style="red")
            else:
                content.append(line, style="white")
            content.append("\n")
        
        return Panel(
            content,
            title=f"📝 Diff: {file_path}",
            title_align="left",
            border_style="blue",
            padding=(0, 1)
        )
    
    @staticmethod
    def create_edit_preview(
        original_content: str,
        old_text: str,
        new_text: str,
        file_path: str,
        context_lines: int = 3
    ) -> Panel:
        """Create a preview for edit operations showing the specific change."""
        
        # Find the location of the change
        lines = original_content.splitlines()
        old_text_lines = old_text.splitlines()
        new_text_lines = new_text.splitlines()
        
        # Find where the old text appears
        change_start = -1
        for i in range(len(lines) - len(old_text_lines) + 1):
            if lines[i:i+len(old_text_lines)] == old_text_lines:
                change_start = i
                break
        
        if change_start == -1:
            # Fallback to simple text replacement preview
            return Panel(
                Text(f"Replace:\n{old_text}\n\nWith:\n{new_text}", style="white"),
                title=f"📝 Edit Preview: {file_path}",
                border_style="yellow"
            )
        
        # Create context around the change
        start_line = max(0, change_start - context_lines)
        end_line = min(len(lines), change_start + len(old_text_lines) + context_lines)
        
        content = Text()
        
        # Add file header
        content.append(f"@@ -{change_start+1},{len(old_text_lines)} +{change_start+1},{len(new_text_lines)} @@\n", style="bold cyan")
        
        # Add context before
        for i in range(start_line, change_start):
            content.append(f" {i+1:3d} ", style="dim")
            content.append(lines[i], style="white")
            content.append("\n")
        
        # Add removed lines
        for i, old_line in enumerate(old_text_lines):
            content.append(f"-{change_start+i+1:3d} ", style="red")
            content.append(old_line, style="red")
            content.append("\n")
        
        # Add added lines
        for i, new_line in enumerate(new_text_lines):
            content.append(f"+{change_start+i+1:3d} ", style="green")
            content.append(new_line, style="green")
            content.append("\n")
        
        # Add context after
        context_after_start = change_start + len(old_text_lines)
        for i in range(context_after_start, min(end_line, context_after_start + context_lines)):
            if i < len(lines):
                content.append(f" {i+1:3d} ", style="dim")
                content.append(lines[i], style="white")
                content.append("\n")
        
        return Panel(
            content,
            title=f"📝 Edit Preview: {file_path}",
            title_align="left",
            border_style="yellow",
            padding=(0, 1)
        )
    
    @staticmethod
    def create_write_file_preview(
        content: str,
        file_path: str,
        is_new_file: bool = True,
        old_content: str = "",
        max_lines: int = 20
    ) -> Panel:
        """Create a preview for write_file operations."""
        
        if is_new_file:
            # Show new file content with line numbers
            lines = content.splitlines()
            display_lines = lines[:max_lines]
            
            text_content = Text()
            for i, line in enumerate(display_lines, 1):
                text_content.append(f"+{i:3d} ", style="green")
                text_content.append(line, style="green")
                text_content.append("\n")
            
            if len(lines) > max_lines:
                text_content.append(f"... ({len(lines) - max_lines} more lines)", style="dim")
            
            return Panel(
                text_content,
                title=f"📄 New File: {file_path}",
                title_align="left",
                border_style="green",
                padding=(0, 1)
            )
        else:
            # Show diff for file overwrite
            return DiffDisplay.create_unified_diff(old_content, content, file_path)


def show_diff_confirmation(
    operation: str,
    file_path: str,
    old_content: str = "",
    new_content: str = "",
    old_text: str = "",
    new_text: str = ""
) -> Panel:
    """Show a confirmation dialog with diff preview."""
    
    if operation == "edit_file":
        return DiffDisplay.create_edit_preview(old_content, old_text, new_text, file_path)
    elif operation == "write_file":
        is_new_file = not old_content
        return DiffDisplay.create_write_file_preview(new_content, file_path, is_new_file, old_content)
    else:
        # Fallback to unified diff
        return DiffDisplay.create_unified_diff(old_content, new_content, file_path)
