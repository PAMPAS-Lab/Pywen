"""
Highlighted content display for showing file changes with +/- indicators.
"""

import difflib
from typing import List, Tuple, Optional, Dict
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.syntax import Syntax
from rich.table import Table


class HighlightedContentDisplay:
    """Display file content with highlighted changes."""
    
    @staticmethod
    def get_language_from_path(file_path: str) -> str:
        """Determine programming language from file extension."""
        if file_path.endswith('.py'):
            return 'python'
        elif file_path.endswith('.js'):
            return 'javascript'
        elif file_path.endswith('.ts'):
            return 'typescript'
        elif file_path.endswith('.html'):
            return 'html'
        elif file_path.endswith('.css'):
            return 'css'
        elif file_path.endswith('.json'):
            return 'json'
        elif file_path.endswith('.xml'):
            return 'xml'
        elif file_path.endswith('.yaml') or file_path.endswith('.yml'):
            return 'yaml'
        elif file_path.endswith('.md'):
            return 'markdown'
        elif file_path.endswith('.sh'):
            return 'bash'
        elif file_path.endswith('.sql'):
            return 'sql'
        else:
            return 'text'
    
    @staticmethod
    def create_highlighted_file_content(
        content: str,
        file_path: str,
        changed_lines: Optional[List[int]] = None,
        added_lines: Optional[List[int]] = None,
        removed_lines: Optional[List[int]] = None,
        max_lines: int = 50
    ) -> Panel:
        """Create a panel showing file content with +/- indicators for changes."""

        lines = content.splitlines()
        language = HighlightedContentDisplay.get_language_from_path(file_path)

        # If content is too long, show first part with truncation notice
        display_lines = lines[:max_lines]
        is_truncated = len(lines) > max_lines

        # Create content with line numbers and +/- indicators
        content_text = Text()

        for i, line in enumerate(display_lines, 1):
            # Determine the change indicator and styles
            if added_lines and i in added_lines:
                indicator = "+"
                indicator_style = "bold green"
                line_style = "green"
                line_num_style = "green"
            elif removed_lines and i in removed_lines:
                indicator = "-"
                indicator_style = "bold red"
                line_style = "red"
                line_num_style = "red"
            elif changed_lines and i in changed_lines:
                indicator = "~"
                indicator_style = "bold yellow"
                line_style = "yellow"
                line_num_style = "yellow"
            else:
                indicator = " "
                indicator_style = "dim"
                line_style = "dim"
                line_num_style = "dim"

            # Line number with appropriate color
            content_text.append(f"{i:3d} ", style=line_num_style)
            # Indicator with appropriate color
            content_text.append(f"{indicator} ", style=indicator_style)

            # Line content with appropriate color
            content_text.append(line, style=line_style)
            content_text.append("\n")

        if is_truncated:
            content_text.append(f"\n... ({len(lines) - max_lines} more lines)", style="dim italic")

        return Panel(
            content_text,
            title=f"📄 {file_path}" + (" (with changes)" if changed_lines or added_lines or removed_lines else ""),
            title_align="left",
            border_style="green" if changed_lines or added_lines or removed_lines else "blue",
            padding=(0, 1)
        )
    
    @staticmethod
    def create_edit_result_display(
        old_content: str,
        new_content: str,
        old_text: str,
        new_text: str,
        file_path: str
    ) -> Panel:
        """Create a display for edit results showing the new content with precise +/- indicators."""

        # Find which lines were changed, added, or removed
        old_lines = old_content.splitlines()
        new_lines = new_content.splitlines()

        # Use difflib to find the exact changes
        differ = difflib.SequenceMatcher(None, old_lines, new_lines)

        added_lines = []
        changed_lines = []

        for tag, i1, i2, j1, j2 in differ.get_opcodes():
            if tag == 'replace':
                # Check if it's a simple replacement (same number of lines) or mixed
                if (i2 - i1) == (j2 - j1):
                    # Same number of lines - mark as changed
                    for line_num in range(j1 + 1, j2 + 1):
                        changed_lines.append(line_num)
                else:
                    # Different number of lines - some are added, some are changed
                    min_lines = min(i2 - i1, j2 - j1)
                    # First part is changed
                    for line_num in range(j1 + 1, j1 + min_lines + 1):
                        changed_lines.append(line_num)
                    # Rest is added
                    for line_num in range(j1 + min_lines + 1, j2 + 1):
                        added_lines.append(line_num)
            elif tag == 'insert':
                # Lines were added
                for line_num in range(j1 + 1, j2 + 1):
                    added_lines.append(line_num)

        return HighlightedContentDisplay.create_highlighted_file_content(
            new_content, file_path,
            changed_lines=changed_lines,
            added_lines=added_lines
        )
    
    @staticmethod
    def create_write_file_result_display(
        content: str,
        file_path: str,
        is_new_file: bool,
        old_content: Optional[str] = None
    ) -> Panel:
        """Create a display for write_file results with +/- indicators."""

        if is_new_file:
            # For new files, show all lines as added (+)
            lines_count = len(content.splitlines())
            added_lines = list(range(1, lines_count + 1))
            return HighlightedContentDisplay.create_highlighted_file_content(
                content, file_path, added_lines=added_lines
            )
        else:
            # For overwritten files, show diff-style indicators
            if old_content:
                # Find changed, added, and removed lines by comparing old and new content
                old_lines = old_content.splitlines()
                new_lines = content.splitlines()

                # Use difflib to find changes
                differ = difflib.SequenceMatcher(None, old_lines, new_lines)
                added_lines = []
                changed_lines = []

                for tag, i1, i2, j1, j2 in differ.get_opcodes():
                    if tag == 'replace':
                        # Check if it's a simple replacement or mixed
                        if (i2 - i1) == (j2 - j1):
                            # Same number of lines - mark as changed
                            for line_num in range(j1 + 1, j2 + 1):
                                changed_lines.append(line_num)
                        else:
                            # Different number of lines - some changed, some added
                            min_lines = min(i2 - i1, j2 - j1)
                            # First part is changed
                            for line_num in range(j1 + 1, j1 + min_lines + 1):
                                changed_lines.append(line_num)
                            # Rest is added
                            for line_num in range(j1 + min_lines + 1, j2 + 1):
                                added_lines.append(line_num)
                    elif tag == 'insert':
                        # Lines were added
                        for line_num in range(j1 + 1, j2 + 1):
                            added_lines.append(line_num)

                return HighlightedContentDisplay.create_highlighted_file_content(
                    content, file_path,
                    changed_lines=changed_lines,
                    added_lines=added_lines
                )
            else:
                # No old content available, show without indicators
                return HighlightedContentDisplay.create_highlighted_file_content(
                    content, file_path
                )
    
    @staticmethod
    def create_side_by_side_comparison(
        old_content: str,
        new_content: str,
        file_path: str,
        max_lines: int = 30
    ) -> Panel:
        """Create a side-by-side comparison of old and new content."""
        
        old_lines = old_content.splitlines()
        new_lines = new_content.splitlines()
        
        # Limit lines for display
        old_display = old_lines[:max_lines]
        new_display = new_lines[:max_lines]
        
        # Create table for side-by-side display
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Before", style="red", width=50)
        table.add_column("After", style="green", width=50)
        
        max_display_lines = max(len(old_display), len(new_display))
        
        for i in range(max_display_lines):
            old_line = old_display[i] if i < len(old_display) else ""
            new_line = new_display[i] if i < len(new_display) else ""
            
            # Add line numbers
            old_text = f"{i+1:3d} │ {old_line}" if old_line else ""
            new_text = f"{i+1:3d} │ {new_line}" if new_line else ""
            
            table.add_row(old_text, new_text)
        
        # Add truncation notice if needed
        if len(old_lines) > max_lines or len(new_lines) > max_lines:
            table.add_row(
                f"... ({len(old_lines) - max_lines} more)" if len(old_lines) > max_lines else "",
                f"... ({len(new_lines) - max_lines} more)" if len(new_lines) > max_lines else ""
            )
        
        return Panel(
            table,
            title=f"📝 Comparison: {file_path}",
            title_align="left",
            border_style="blue",
            padding=(0, 1)
        )


def create_enhanced_tool_result_display(result_data: dict, tool_name: str) -> Panel:
    """Create enhanced display for tool results with highlighted content."""
    
    operation = result_data.get('operation')
    file_path = result_data.get('file_path', 'unknown')
    summary = result_data.get('summary', 'Operation completed')
    
    if operation == 'edit_file':
        # Show the new content with highlighted changes
        old_content = result_data.get('old_content', '')
        new_content = result_data.get('new_content', '')
        old_text = result_data.get('old_text', '')
        new_text = result_data.get('new_text', '')
        
        return HighlightedContentDisplay.create_edit_result_display(
            old_content, new_content, old_text, new_text, file_path
        )
    
    elif operation == 'write_file':
        # Show the file content with highlighting for changes
        content = result_data.get('content', '')
        old_content = result_data.get('old_content')
        is_new_file = result_data.get('is_new_file', False)
        
        return HighlightedContentDisplay.create_write_file_result_display(
            content, file_path, is_new_file, old_content
        )
    
    else:
        # Fallback for other operations
        return Panel(
            Text(summary),
            title=f"✓ {tool_name}",
            title_align="left",
            border_style="green",
            padding=(0, 1)
        )
