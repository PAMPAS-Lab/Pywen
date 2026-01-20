"""帮助命令实现"""
from __future__ import annotations
from typing import Any, Dict, List, Tuple
from rich.panel import Panel
from .base_command import BaseCommand, CommandResult, CommandAction

class HelpCommand(BaseCommand):
    def __init__(self) -> None:
        super().__init__("help", "show this help message", "h")

    async def execute(self, context: Dict[str, Any], args: str) -> CommandResult:
        console = context.get("console")
        if not console:
            return CommandResult(action=CommandAction.HANDLED, error="console not found in context")

        help_content = self._build_help_content(context)

        panel = Panel(
            help_content,
            title="Pywen CLI Help",
            border_style="blue",
            padding=(1, 2),
        )
        console.print(panel)
        return CommandResult(action=CommandAction.HANDLED)

    def _build_help_content(self, context: Dict[str, Any]) -> str:
        content: List[str] = []

        # 基本使用说明
        content.append("[bold cyan]Basics:[/bold cyan]")
        content.append(
            "[bold purple]Add context:[/bold purple] Use [purple]@[/purple] to specify files for context "
            "(e.g., [purple]@src/myfile.ts[/purple]) to target specific files or folders."
        )
        content.append(
            "[bold purple]Shell mode:[/bold purple] Execute shell commands via [purple]![/purple] "
            "(e.g., [purple]!npm run start[/purple]) or use natural language (e.g. [purple]start server[/purple])."
        )
        content.append("")

        # 命令列表（动态）
        content.append("[bold cyan]Commands:[/bold cyan]")
        content.extend(self._build_commands_section(context))
        content.append("")

        # 键盘快捷键
        content.append("[bold cyan]Keyboard Shortcuts:[/bold cyan]")
        content.append("[purple]Enter[/purple]          Send message")
        content.append("[purple]Ctrl+J[/purple]         New line ([purple]Alt+Enter[/purple] works for certain linux distros)")
        content.append("[purple]Up/Down[/purple]        Cycle through your prompt history")
        content.append("[purple]Alt+Left/Right[/purple] Jump through words in the input")
        content.append("[purple]Shift+Tab[/purple]      Toggle auto-accepting edits")
        content.append("[purple]Ctrl+Y[/purple]         Toggle YOLO mode")
        content.append("[purple]Esc[/purple]            Cancel operation")
        content.append("[purple]Ctrl+C[/purple]         Quit application")

        return "\n".join(content)

    def _build_commands_section(self, context: Dict[str, Any]) -> List[str]:
        """
        从 CommandRegistry 动态生成命令列表。
        """
        reg = context.get("cmd_mgr")
        lines: List[str] = []

        if not reg:
            lines.append("[purple]/help[/purple]         show this help message")
            lines.append("[purple]/quit[/purple]         exit the cli")
            lines.append("[purple]![/purple]             shell command")
            return lines

        # reg.all() -> Dict[str, BaseCommand]
        all_cmds = reg.all()

        # 去重：同一个 BaseCommand 可能以 name 和 alt_name 两个 key 出现
        unique: Dict[int, Tuple[str, Any]] = {}
        for key, cmd in all_cmds.items():
            unique[id(cmd)] = (key, cmd)

        by_primary: Dict[str, Dict[str, Any]] = {}
        for _key, cmd in (v for v in unique.values()):
            primary = getattr(cmd, "name", "")
            if not primary:
                continue
            item = by_primary.setdefault(primary, {"cmd": cmd, "aliases": set()})
            alt = getattr(cmd, "alt_name", None)
            if alt:
                item["aliases"].add(alt)

        for name in sorted(by_primary.keys()):
            cmd = by_primary[name]["cmd"]
            aliases = sorted(by_primary[name]["aliases"])

            desc = getattr(cmd, "description", "") or ""
            alias_text = f" (alias: {', '.join('/'+a for a in aliases)})" if aliases else ""

            arg_hint = getattr(cmd, "argument_hint", "") or ""
            hint_text = f"  [dim]{arg_hint}[/dim]" if arg_hint else ""

            lines.append(f"[purple]/{name:<12}[/purple] {desc}{alias_text}{hint_text}")

        # shell 命令固定项
        lines.append(f"[purple]{'!':<13}[/purple] shell command")

        return lines

