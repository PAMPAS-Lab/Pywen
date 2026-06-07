"""关于命令实现"""

import platform
import sys

from rich import get_console
from rich.panel import Panel

from pywen import get_version

from .base_command import BaseCommand, CommandAction, CommandResult


class AboutCommand(BaseCommand):
    def __init__(self):
        super().__init__("about", "show version info")
        self.console = get_console()
    
    async def execute(self, context, args: str) -> CommandResult:
        """显示版本信息"""
        version_info = self._build_version_info()
        
        panel = Panel(
            version_info,
            title="Pywen Version Info",
            border_style="blue",
            padding=(1, 2)
        )
        
        self.console.print(panel)
        return  CommandResult(action=CommandAction.HANDLED) 
    
    def _build_version_info(self) -> str:
        """构建版本信息"""
        content = []
        content.append(f"[bold cyan]Pywen CLI Version:[/bold cyan] {get_version()}")
        content.append(f"[bold cyan]Python Version:[/bold cyan] {sys.version}")
        content.append(f"[bold cyan]Platform:[/bold cyan] {platform.platform()}")
        content.append(f"[bold cyan]Architecture:[/bold cyan] {platform.machine()}")
        return "\n".join(content)
