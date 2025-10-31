"""帮助命令实现"""

from rich.panel import Panel
from rich import get_console
from .base_command import BaseCommand

class HelpCommand(BaseCommand):
    def __init__(self):
        super().__init__("help", "show this help message", "h")
        self.console = get_console()
    
    async def execute(self, context, args: str) -> bool:
        """显示帮助信息"""
        help_content = self._build_help_content()
        
        panel = Panel(
            help_content,
            title="Pywen CLI Help",
            border_style="blue",
            padding=(1, 2)
        )
        
        self.console.print(panel)
        return True
    
    def _build_help_content(self) -> str:
        """构建帮助内容"""
        content = []
        
        # 基本使用说明
        content.append("[bold cyan]Basics:[/bold cyan]")
        content.append("[bold purple]Add context:[/bold purple] Use [purple]@[/purple] to specify files for context (e.g., [purple]@src/myfile.ts[/purple]) to target specific files or folders.")
        content.append("[bold purple]Shell mode:[/bold purple] Execute shell commands via [purple]![/purple] (e.g., [purple]!npm run start[/purple]) or use natural language (e.g. [purple]start server[/purple]).")
        content.append("")
        
        # 可用命令
        content.append("[bold cyan]Commands:[/bold cyan]")
        
        commands = [
            ("/about", "show version info"),
            ("/auth", "change the auth method"),
            ("/clear", "clear the screen and conversation history"),
            ("/help", "for help on pywen code"),
            ("/memory", "Commands for interacting with memory."),
            ("  show", "Show the current memory contents."),
            ("  add", "Add content to the memory."),
            ("  refresh", "Refresh the memory from the source."),
            ("/privacy", "display the privacy notice"),
            ("/theme", "change the theme"),
            ("/docs", "open full Pywen documentation in your browser"),
            ("/editor", "set external editor preference"),
            ("/stats", "check session stats. Usage: /stats [model|tools]"),
            ("/mcp", "list configured MCP servers and tools"),
            ("/extensions", "list active extensions"),
            ("/tools", "list available Pywen tools"),
            ("/agent", "switch between different agents"),
            ("/model", "switch between different model providers"),
            ("/bug", "submit a bug report"),
            ("/chat", "Manage conversation history. Usage: /chat <list|save|resume> <tag>"),
            ("/quit", "exit the cli"),
            ("/compress", "Compresses the context by replacing it with a summary."),
            ("!", "shell command"),
        ]
        
        for cmd, desc in commands:
            if cmd.startswith("  "):
                content.append(f"  [purple]{cmd.strip():<10}[/purple] {desc}")
            else:
                content.append(f"[purple]{cmd:<12}[/purple] {desc}")
        
        content.append("")
        
        # 键盘快捷键
        content.append("[bold cyan]Keyboard Shortcuts:[/bold cyan]")
        content.append("[purple]Enter[/purple]         Send message")
        content.append("[purple]Ctrl+J[/purple]        New line ([purple]Alt+Enter[/purple] works for certain linux distros)")
        content.append("[purple]Up/Down[/purple]       Cycle through your prompt history")
        content.append("[purple]Alt+Left/Right[/purple] Jump through words in the input")
        content.append("[purple]Shift+Tab[/purple]     Toggle auto-accepting edits")
        content.append("[purple]Ctrl+Y[/purple]        Toggle YOLO mode")
        content.append("[purple]Esc[/purple]           Cancel operation")
        content.append("[purple]Ctrl+C[/purple]        Quit application")
        
        return "\n".join(content)
