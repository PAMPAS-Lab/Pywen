"""CLI Console for displaying agent progress."""
from __future__ import annotations
import os
from typing import Optional, Any, Dict, Union
from rich import get_console
from rich.console import Group,RenderableType
from rich.panel import Panel
from rich.text import Text
from rich.syntax import Syntax
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from pywen.tools.base_tool import ToolRiskLevel
from pywen.utils.permission_manager import PermissionLevel, PermissionManager
from pywen.cli.highlighted_content import create_enhanced_tool_result_display, HighlightedContentDisplay
from pywen.agents.agent_events import Agent_Events, AgentEvent

class CLIConsole:
    """Console for displaying agent progress and handling user interactions."""

    def __init__(self, perm_mgr: Optional[PermissionManager] = None):
        self.printer = Printer(get_console())
        self.tokens = TokenTracker(32768)
        self.banner = BannerView(self.printer)
        self.status_bar = StatusBar(self.printer, self.tokens)
        self.tool_call_view = ToolCallView(self.printer)
        self.renderers = ToolCallResultRendererRegistry(self.printer)
        self.approval = ApprovalService(
                permission_manager= perm_mgr or PermissionManager(PermissionLevel.LOCKED), 
                printer=self.printer, 
                tool_call_view=self.tool_call_view
                )
        self.router = EventRouter(self.printer, self.renderers, self.tool_call_view)

    def print(self, message: str, color: str = "blue", bold: bool = False):
        self.printer.print_text(message, color, bold)

    async def confirm_tool_call(self, tool_name, tool_args, tool=None) -> bool:
        return await self.approval.confirm(tool_name, tool_args, tool)

    def show_interactive_banner(self):
        self.banner.show()

    def show_status_bar(self, model_name:str = "qwen3-coder-plus", permission_level:str = "yolo"):
        self.status_bar.show(
                model_name=model_name,
                permission_level=permission_level,
                sandbox_label="no sandbox (see /docs)",
        )

    def start_interactive_mode(self):
        self.show_interactive_banner()

    def update_token_usage(self, tokens_used: int):
        self.tokens.add(tokens_used)

    def set_max_context_tokens(self, max_tokens: int):
        self.tokens.set_max(max_tokens)

    def set_current_tokens(self, value:int):
        self.tokens.reset(value)

    def get_current_tokens(self) -> int:
        return self.tokens.current

    async def handle_events(self, event):
        return self.router.handle(event)

    def prompt_prefix(self, session_id: str) -> HTML:
        return HTML(f'<ansiblue>✦</ansiblue><ansigreen>{session_id}</ansigreen> <ansiblue>❯</ansiblue> ')

class Printer:
    """仅负责输出（统一入口，隔离 rich 细节）"""
    def __init__(self, console):
        self.console = console

    def print_text(self, message: Union[str, Text, RenderableType], color: str = "blue", bold: bool = False):
        if isinstance(message, Text):
            if color:
                message.stylize(color)
            self.console.print(message)
            return
        if isinstance(message, str):
            if color:
                self.console.print(Text(message, style=color))
            else:
                self.console.print(message)
            return
        self.console.print(message)

    def print_raw(self, obj):
        self.console.print(obj)

    def print_end_chunk(self, content: str):
        self.console.print(content, end="", markup=False)

class TokenTracker:
    """管理会话 Token 计数与上限"""
    def __init__(self, max_tokens: int = 32768):
        self.current = 0
        self.max = max_tokens

    def add(self, used: int):
        self.current += int(used)

    def set_max(self, max_tokens: int):
        self.max = int(max_tokens)

    def left_percent(self) -> int:
        if self.max <= 0:
            return 100
        return max(0, 100 - (self.current * 100 // self.max))

    def reset(self, value:int):
        self.current = value

class BannerView:
    def __init__(self, printer: Printer):
        self.p = printer

    @staticmethod
    def _gradient_line(text: str, start_color, end_color) -> Text:
        gradient = Text()
        length = len(text)
        for i, ch in enumerate(text):
            r = int(start_color[0] + (end_color[0] - start_color[0]) * i / max(1, length - 1))
            g = int(start_color[1] + (end_color[1] - start_color[1]) * i / max(1, length - 1))
            b = int(start_color[2] + (end_color[2] - start_color[2]) * i / max(1, length - 1))
            gradient.append(ch, style=f"rgb({r},{g},{b})")
        return gradient

    def show(self):
        os.system('cls' if os.name == 'nt' else 'clear')

        ascii_logo = [
            "                                              ",
            " ██████╗ ██╗   ██╗██╗    ██╗███████╗███╗   ██╗",
            " ██╔══██╗╚██╗ ██╔╝██║    ██║██╔════╝████╗  ██║",
            " ██████╔╝ ╚████╔╝ ██║ █╗ ██║█████╗  ██╔██╗ ██║",
            " ██╔═══╝   ╚██╔╝  ██║███╗██║██╔══╝  ██║╚██╗██║",
            " ██║        ██║   ╚███╔███╔╝███████╗██║ ╚████║",
            " ╚═╝        ╚═╝    ╚══╝╚══╝ ╚══════╝╚═╝  ╚═══╝",
            "                                              ",
        ]
        start_rgb = (102, 178, 255)
        end_rgb   = (100, 220, 160)

        for line in ascii_logo:
            self.p.print_raw(self._gradient_line(line, start_rgb, end_rgb))

        tips = """[dim]Tips for getting started:
1. Ask questions, edit files, or run commands.
2. Be specific for the best results.
3. /help for more information. Type '/quit' to quit.[/dim]"""
        self.p.print_raw(tips)
        self.p.print_raw("")

class StatusBar:
    _ICON_BY_LEVEL = {
        "locked": "🔒",
        "edit_only": "✏️",
        "planning": "📝",
        "yolo": "🚀",
    }
    def __init__(self, printer: Printer, tokens: TokenTracker):
        self.p = printer
        self.tokens = tokens

    def show(self, *, model_name: str,
             permission_level: str | None = None, # 取值：locked/edit_only/planning/yolo 或 None
             sandbox_label: str = "no sandbox (see /docs)",
        ):
        current_dir = os.getcwd()
        home_dir = os.path.expanduser('~')
        display_dir = current_dir.replace(home_dir, "~", 1) if current_dir.startswith(home_dir) else current_dir
        context_status = f"({self.tokens.left_percent()}% context left)"

        permission_status = ""
        if permission_level:
            level = permission_level.lower()
            icon = self._ICON_BY_LEVEL.get(level, "❓")
            permission_status = f"  {icon} {level.upper()}"

        status_text = Text()
        status_text.append(display_dir, style="blue")
        status_text.append(f"  {sandbox_label}", style="dim")
        status_text.append(f"  {model_name}", style="green")
        status_text.append(f"  {context_status}", style="dim")

        if permission_status:
            if "🚀" in permission_status:
                status_text.append(permission_status, style="green")
            elif "🔒" in permission_status:
                status_text.append(permission_status, style="red")
            elif "✏️" in permission_status:
                status_text.append(permission_status, style="yellow")
            elif "🧠" in permission_status:
                status_text.append(permission_status, style="blue")
            else:
                status_text.append(permission_status, style="dim")

        self.p.print_raw(status_text)
        self.p.print_raw("")


class ToolCallView:
    """展示'即将执行'的工具调用"""
    def __init__(self, printer: Printer):
        self.p = printer

    def format_content(self, tool_name: str, arguments: dict) -> Text:
        if tool_name == "bash" and "command" in arguments:
            return Text(arguments["command"], style="cyan")
        elif tool_name == "write_file" and "path" in arguments:
            path = arguments["path"]
            content_preview = arguments.get("content", "")[:50]
            if len(content_preview) >= 50:
                content_preview += "..."
            return Text(f"Path: {path}\nContent: {content_preview}", style="green")
        elif tool_name == "read_file" and "path" in arguments:
            return Text(f"Reading: {arguments['path']}", style="blue")
        elif tool_name == "edit_file" and all(k in arguments for k in ["path", "old_text", "new_text"]):
            path = arguments["path"]
            old_preview = arguments["old_text"][:30] + "..." if len(arguments["old_text"]) > 30 else arguments["old_text"]
            new_preview = arguments["new_text"][:30] + "..." if len(arguments["new_text"]) > 30 else arguments["new_text"]
            return Text(f"Path: {path}\nReplace: {old_preview}\nWith: {new_preview}", style="yellow")
        else:
            args_text = ""
            for key, value in arguments.items():
                if isinstance(value, str) and len(value) > 50:
                    value_display = value[:50] + "..."
                else:
                    value_display = str(value)
                args_text += f"{key}: {value_display}\n"
            return Text(args_text.rstrip(), style="dim")

    @staticmethod
    def preview(tool_name: str) -> str:
        mapping = {
            "bash": "➤ Will execute command",
            "write_file": "➤ Will write to file",
            "read_file": "➤ Will read file content",
            "edit_file": "➤ Will modify file",
            "ls": "➤ Will list files/directories",
            "glob": "➤ Will list files/directories",
            "grep": "➤ Will search for pattern",
            "web_fetch": "➤ Will fetch web content",
            "web_search": "➤ Will fetch web content",
        }
        return mapping.get(tool_name, "➤ Executing...")

    def show(self, tool_name: str, arguments: dict):
        content = self.format_content(tool_name, arguments)
        preview = self.preview(tool_name)
        if preview:
            content = Text(str(content) + f"\n{preview}")
        panel = Panel(content, title=f"🔧 {tool_name}", title_align="left", border_style="yellow", padding=(0, 1))
        self.p.print_raw(panel)

class ToolCallResultRendererRegistry:
    def __init__(self, printer: "Printer"):
        self.renderer = UnifiedToolCallResultRenderer(printer)

    def render_success(self, tool_name: str, result: Any, arguments: Dict) -> Optional[Panel]:
        return self.renderer.render_success(tool_name, result, arguments)

    def render_error(self, tool_name: str, error: Any) -> Panel:
        return self.renderer.render_error(tool_name, error)

class UnifiedToolCallResultRenderer:
    """单类处理全部工具结果的渲染；内部做分发与兜底。"""
    def __init__(self, printer: "Printer"):
        self.p = printer

    def render_success(self, tool_name: str, result: Any, arguments: Dict) -> Optional[Panel]:
        if isinstance(result, dict) and result.get("operation") in {"write_file", "edit_file"}:
            try:
                return create_enhanced_tool_result_display(result, tool_name)
            except Exception:
                pass

        if tool_name in {"edit", "edit_file"} and isinstance(result, dict):
            return self._render_file_edit(result)
        if tool_name == "write_file" and isinstance(result, dict):
            return self._render_file_write(result)
        if tool_name == "bash":
            return self._render_bash(result, arguments)
        if tool_name in {"read_file", "read_many_files"}:
            return self._render_file_read(result, arguments)
        if tool_name in {"ls", "glob"}:
            return self._render_list(result, arguments)
        if tool_name == "grep":
            return self._render_grep(result, arguments)
        if tool_name == "think_tool":
            self.p.print_raw(Text(str(result if result is not None else ""), style="dim italic"))
            return None

        return self._render_generic(tool_name, result)

    def render_error(self, tool_name: str, error: Any) -> Panel:
        err = str(error)
        low = err.lower()
        if "permission denied" in low:
            err += "\n💡 Try running with appropriate permissions"
        elif "file not found" in low:
            err += "\n💡 Check if the file path is correct"
        elif "command not found" in low:
            err += "\n💡 Check if the command is installed and in PATH"
        return Panel(Text(err, style="red"), title=f"✗ {tool_name}",
                     title_align="left", border_style="red", padding=(0, 1))

    def _render_generic(self, tool_name: str, result: Any) -> Panel:
        s = "Operation completed successfully" if (result is None or result == "") else str(result)
        if len(s) > 500:
            s = s[:500] + "\n... (truncated)"
        return Panel(Text(s), title=f"✓ {tool_name}", title_align="left",
                     border_style="green", padding=(0, 1))

    def _render_bash(self, result: Any, arguments: Dict) -> Panel:
        output = "" if result is None else str(result)
        content = Syntax(output, "bash", theme="monokai", line_numbers=False) if len(output) > 100 else Text(output, style="green")
        title = "✓ bash"
        cmd = arguments.get("command", "")
        if cmd:
            short = (cmd[:37] + "...") if len(cmd) > 40 else cmd
            title = f"✓ bash: {short}"
        return Panel(content, title=title, title_align="left", border_style="green", padding=(0, 1))

    def _render_file_read(self, result: Any, arguments: Dict) -> Panel:
        text = "" if result is None else str(result)
        lines = text.splitlines()
        max_lines = 100
        truncated = len(lines) > max_lines
        if truncated:
            lines = lines[:max_lines]
        shown = "\n".join(lines)

        content = self._maybe_syntax(shown)
        if truncated:
            notice = Text(f"... (truncated after {max_lines} lines)", style="dim yellow")
            if isinstance(content, Text):
                content.append("\n")
                content.append(notice)
            else:
                content = Group(content, notice)

        path = arguments.get("file_path") or arguments.get("path") or ""
        title = f"✓ read_file"
        if path:
            short = ("..." + path[-47:]) if len(path) > 50 else path
            title = f"✓ read_file: {short}"
        return Panel(content, title=title, title_align="left", border_style="blue", padding=(0, 1))

    def _render_list(self, result: Any, arguments: Dict) -> Panel:
        text = "" if result is None else str(result)
        if "\n" in text:
            items = [ln.strip() for ln in text.splitlines() if ln.strip()]
            display = [f"📄 {x}" for x in items[:20]]
            if len(items) > 20:
                display.append(f"... and {len(items) - 20} more items")
            content = Text("\n".join(display))
        else:
            content = Text(text)

        p = arguments.get("path") or arguments.get("pattern") or ""
        title = f"✓ {'ls' if 'ls' in arguments.get('name','') else 'list'}"
        if p:
            short = ("..." + p[-37:]) if len(p) > 40 else p
            title = f"✓ list: {short}"
        return Panel(content, title=title, title_align="left", border_style="cyan", padding=(0, 1))

    def _render_grep(self, result: Any, arguments: Dict) -> Panel:
        text = "" if result is None else str(result)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        shown = [f"🔍 {ln}" for ln in lines[:15]]
        if len(lines) > 15:
            shown.append(f"... and {len(lines) - 15} more matches")
        content = Text("\n".join(shown), style="yellow")

        parts = []
        pat = arguments.get("pattern", "")
        if pat:
            parts.append(f"'{(pat[:17] + '...') if len(pat) > 20 else pat}'")
        path = arguments.get("path", "")
        if path:
            parts.append(f"in {('...' + path[-27:]) if len(path) > 30 else path}")
        title = f"✓ grep: {' '.join(parts)}" if parts else "✓ grep"
        return Panel(content, title=title, title_align="left", border_style="yellow", padding=(0, 1))

    def _render_file_write(self, result: Dict) -> Panel:
        file_path = result.get("file_path", "unknown")
        content = result.get("content", "")
        old_content = result.get("old_content", "")
        is_new_file = result.get("is_new_file", False)
        try:
            return HighlightedContentDisplay.create_write_file_result_display(
                content, file_path, is_new_file, old_content
            )
        except Exception:
            lines = content.splitlines()
            body = "\n".join(f"{i:3d} │ {ln}" for i, ln in enumerate(lines, 1))
            info = (f"{'📄 Created' if is_new_file else '📝 Updated'}: {file_path}\n"
                    f"📊 {result.get('lines_count', 0)} lines, {result.get('chars_count', 0)} characters\n"
                    + "─" * 50 + "\n")
            return Panel(Text(info + body, style="green"),
                         title=f"✓ write_file: {file_path}", title_align="left",
                         border_style="green", padding=(0, 1))

    def _render_file_edit(self, result: Dict) -> Panel:
        file_path = result.get("file_path", "unknown")
        new_content = result.get("new_content", "")
        old_content = result.get("old_content", "")
        old_text = result.get("old_text", "")
        new_text = result.get("new_text", "")
        try:
            return HighlightedContentDisplay.create_edit_result_display(
                old_content, new_content, old_text, new_text, file_path
            )
        except Exception:
            lines = new_content.splitlines()
            body = "\n".join(f"{i:3d} │ {ln}" for i, ln in enumerate(lines, 1))
            return Panel(Text(body, style="green"),
                         title=f"✓ edit_file: {file_path}", title_align="left",
                         border_style="green", padding=(0, 1))

    def _maybe_syntax(self, text: str):
        low = text.lower()
        lang = "text"
        if any(k in low for k in ["def ", "class ", "import "]):
            lang = "python"
        elif any(k in low for k in ["function", "var ", "const ", "let "]):
            lang = "javascript"
        elif any(k in low for k in ["#include", "int main", "printf"]):
            lang = "c"
        elif text.strip().startswith("<!DOCTYPE") or "<html" in low:
            lang = "html"
        elif text.strip().startswith("{") or text.strip().startswith("["):
            lang = "json"

        if lang == "text":
            lines = text.splitlines() or [text]
            return Text("\n".join(f"{i:3d} │ {ln}" for i, ln in enumerate(lines, 1)))
        return Syntax(text, lang, theme="monokai", line_numbers=(lang != "text"), word_wrap=True)

class ApprovalService:
    def __init__(self, *, permission_manager: PermissionManager, printer: Printer, tool_call_view: ToolCallView):
        self.p = printer
        self.tool_call_view = tool_call_view
        self.pm = permission_manager

    async def confirm(self, tool_name, tool_args, tool=None) -> bool:
        if self.pm and self.pm.should_auto_approve(tool_name, **tool_args):
            return True

        if tool:
            risk_level = tool.get_risk_level(**tool_args)
            if risk_level == ToolRiskLevel.SAFE:
                return True

        if tool_name in ['write_file', 'edit_file', 'edit'] and tool:
            try:
                confirmation_details = await tool.get_confirmation_details(**tool_args)
                if confirmation_details and hasattr(tool, '_generate_confirmation_message'):
                    detailed_message = await tool._generate_confirmation_message(**tool_args)
                    self.p.print_raw(detailed_message)
                else:
                    self._display_basic_tool_info(tool_name, tool_args)
            except Exception:
                self._display_basic_tool_info(tool_name, tool_args)
        else:
            self._display_basic_tool_info(tool_name, tool_args)

        self.p.print_raw("")

        session = PromptSession()
        while True:
            try:
                resp = await session.prompt_async(
                    HTML('<ansiblue><b>Allow this tool execution? (y/n/a for always): </b></ansiblue>')
                )
                resp = resp.lower().strip()
                if resp in ('y', 'yes', ''):
                    return True
                elif resp in ('n', 'no'):
                    return False
                elif resp in ('a', 'always'):
                    self.pm.set_permission_level(PermissionLevel.YOLO)
                    self.p.print_raw(Text("✅ YOLO mode enabled - all future tools will be auto-approved", style="green"))
                    return True
                else:
                    self.p.print_raw(Text("Please enter 'y' (yes), 'n' (no), or 'a' (always)", style="red"))
            except KeyboardInterrupt:
                self.p.print_raw(Text("\nTool execution cancelled by user (Ctrl+C)", style="yellow"))
                return False
            except EOFError:
                self.p.print_raw(Text("\nTool execution cancelled by user", style="yellow"))
                return False

    def _display_basic_tool_info(self, tool_name: str, arguments: dict):
        self.p.print_raw(f"🔧 [bold cyan]{tool_name}[/bold cyan]")
        if arguments and isinstance(arguments, dict):
            self.p.print_raw("Arguments:")
            for key, value in arguments.items():
                if key == "content" and len(str(value)) > 100:
                    preview = str(value)[:100] + "..."
                    self.p.print_raw(f"  [cyan]{key}[/cyan]: {preview}")
                else:
                    self.p.print_raw(f"  [cyan]{key}[/cyan]: {value}")
        elif arguments and isinstance(arguments, str):
            self.p.print_raw("Arguments:")
            self.p.print_text(f"{arguments}")
        else:
            self.p.print_raw("No arguments")

class EventRouter:
    """将不同 agent 的事件分发到输出/渲染逻辑"""
    def __init__(self, printer: Printer, renderer: ToolCallResultRendererRegistry, tool_call_view: ToolCallView):
        self.p = printer
        self.renderer = renderer
        self.tool_call_view = tool_call_view

    def handle(self, event: AgentEvent) -> Optional[str]:
        data = event.data
        if event.type == Agent_Events.USER_MESSAGE:
            self.p.print_text(f"🔵 User:{data['text']}", "blue", True)
            self.p.print_raw("")
        elif event.type == "task_continuation":
            self.p.print_text(f"🔄 Continuing Task (Turn {data['turn']}):", "yellow", True)
            self.p.print_text(f"{data['message']}", "blue", False)
            self.p.print_raw("")
        elif event.type == Agent_Events.LLM_STREAM_START:
            self.p.print_end_chunk("🤖 ")
        elif event.type == Agent_Events.TEXT_DELTA:
            self.p.print_end_chunk(data["content"])
        elif event.type == Agent_Events.TOOL_CALL:
            # 显示工具调用开始提示
            tool_name = data.get('name', 'Tool')
            self.p.print_text(f"🔧 Calling {tool_name} tool...", "cyan", False)
            self.p.print_raw("")
        elif event.type == Agent_Events.TOOL_RESULT:
            self._display_tool_result(data)
        elif event.type == Agent_Events.TURN_TOKEN_USAGE:
            pass
        elif event.type == Agent_Events.WAITING_FOR_USER:
            self.p.print_text(f"💭{data['reasoning']}", "yellow")
            self.p.print_raw("")
        elif event.type == "model_continues":
            self.p.print_text(f"🔄 Model continues: {data['reasoning']}", "cyan")
            if data.get('next_action'):
                self.p.print_text(f"🎯 Next: {data['next_action'][:100]}...", "dim")
            self.p.print_raw("")
        elif event.type == Agent_Events.TASK_COMPLETE:
            self.p.print_text(f"\n✅ Task completed!", "green", True)
            self.p.print_raw("")
        elif event.type == Agent_Events.TURN_MAX_REACHED:
            self.p.print_text(f"⚠️ Maximum turns reached", "yellow", True)
            self.p.print_raw("")
        elif event.type == Agent_Events.ERROR:
            # 兼容不同错误载荷：优先 message，其次 error，最后整体转字符串
            msg = ""
            if isinstance(data, dict):
                msg = data.get("message") or data.get("error") or ""
            if not msg:
                msg = str(data)
            self.p.print_text(f"❌ Error: {msg}", "red")
            self.p.print_raw("")
        elif event.type == "trajectory_saved":
            if data.get('is_task_start', False):
                self.p.print_text(f"✅ Trajectory saved to: {data['path']}", "dim")
        return event.type 

    def _display_tool_result(self, data: dict):
        tool_name = data.get('name', 'Tool')
        result = data.get('result', '')

        # 用户拒绝/取消的工具不显示结果面板
        if "rejected by the user" in str(result):
            return

        arguments = data.get('arguments', {})
        if data.get("success"):
            panel = self.renderer.render_success(tool_name, result, arguments)
        else:
            error = data.get('error', 'Unknown error')
            panel = self.renderer.render_error(tool_name, error)
        if panel is not None:
            self.p.print_raw(panel)

