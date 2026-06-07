import asyncio
from asyncio import TimerHandle
from typing import Any, Callable, Dict, Optional

from prompt_toolkit.key_binding import KeyBindings

from pywen.cli.cli_console import CLIConsole
from pywen.utils.permission_manager import PermissionLevel, PermissionManager


def create_key_bindings(
    console_getter: Callable[[], CLIConsole], 
    perm_mgr_getter: Callable[[], PermissionManager], 
    cancel_event_getter: Optional[Callable[[], Optional[Any]]] = None, 
    current_task_getter: Optional[Callable] = None,
    *,
    exit_sentinel: str = "__PYWEN_QUIT__",
) -> KeyBindings:
    """创建键盘快捷键绑定"""
    bindings = KeyBindings()
    loop = asyncio.get_event_loop()
    
    # Ctrl+J - 新行
    @bindings.add('c-j')
    def _(event):
        """Insert a newline."""
        event.app.current_buffer.insert_text('\n')
    
    # Alt+Enter - 新行 (某些Linux发行版)
    @bindings.add('escape', 'enter')
    def _(event):
        """Insert a newline (Alt+Enter)."""
        event.app.current_buffer.insert_text('\n')
    
    # Ctrl+Y - Cycle through permission levels
    @bindings.add('c-y')
    def _(event):
        """Cycle through permission levels: LOCKED -> EDIT_ONLY -> PLANNING -> YOLO -> LOCKED"""
        perm_mgr = perm_mgr_getter()
        console = console_getter()
        try:
            current_level = perm_mgr.get_permission_level()

            # Define the cycle order
            cycle_order = [
                PermissionLevel.LOCKED,
                PermissionLevel.EDIT_ONLY,
                PermissionLevel.PLANNING,
                PermissionLevel.YOLO
            ]

            # Find current index and get next level
            try:
                current_index = cycle_order.index(current_level)
                next_index = (current_index + 1) % len(cycle_order)
                next_level = cycle_order[next_index]
            except ValueError:
                # If current level not in cycle, start from LOCKED
                next_level = PermissionLevel.LOCKED

            # Set new permission level
            perm_mgr.set_permission_level(next_level)

            # Display status with appropriate color and icon
            level_info = {
                PermissionLevel.LOCKED: ("🔒 LOCKED", "全锁状态：所有操作都需要确认","red"),
                PermissionLevel.EDIT_ONLY: ("✏️ EDIT_ONLY", "编辑权限：自动确认文件编辑，其他需要确认","yellow"),
                PermissionLevel.PLANNING: ("📝 PLANNING", "规划权限：自动确认非编辑操作，编辑需要确认","blue"),
                PermissionLevel.YOLO: ("🚀 YOLO", "锁开状态：自动确认所有操作","green")
            }

            icon_text, description , color= level_info[next_level]
            console.print(f"{icon_text} - {description}",color)

        except Exception as e:
            console.print(f"Error switching permission level: {e}","red")
    
    # Shift+Tab - Toggle auto-accepting edits (placeholder)
    @bindings.add('s-tab')
    def _(event):
        """Toggle auto-accepting edits."""
        console = console_getter()
        console.print("Auto-accepting edits toggled (not implemented yet)","yellow")
    
    # ESC - 取消当前操作
    # 注意，只有在编辑状态下按 ESC 才会触发此绑定
    @bindings.add('escape')
    def _(event):
        """Cancel current operation."""
        cancel_event = cancel_event_getter() if cancel_event_getter else None
        current_task = current_task_getter() if current_task_getter else None
        try:
            if current_task:
                current_task.cancel()
        except Exception:
            pass
        try:
            if cancel_event and hasattr(cancel_event, "set"):
                cancel_event.set()
        except Exception:
            pass
    # Ctrl+C - 智能处理：任务执行中取消任务，否则退出
    ctrl_c_count = {"n": 0}
    reset_handle: Dict[str, Optional[TimerHandle]] = {"h": None}
    def schedule_reset():
        if reset_handle["h"] is not None:
            reset_handle["h"].cancel()
        reset_handle["h"] = loop.call_later(3.0, lambda: ctrl_c_count.__setitem__("n", 0))

    @bindings.add('c-c')
    def _(event):
        console = console_getter()
        cancel_event = cancel_event_getter() if cancel_event_getter else None
        current_task = current_task_getter() if current_task_getter else None
        running = bool(current_task and not current_task.done())

        if running:
            console.print("\nCancelling current operation... (Press Ctrl+C again to quit)", "yellow")
            if cancel_event and not cancel_event.is_set():
                cancel_event.set()
            try:
                if current_task and not current_task.done():
                    current_task.cancel()
            finally:
                ctrl_c_count["n"] = 1
                schedule_reset()
            return

        # 没有任务在跑：走 3 秒内双击退出
        ctrl_c_count["n"] += 1
        if ctrl_c_count["n"] == 1:
            console.print("Press Ctrl+C again to quit", "yellow")
            schedule_reset()
        else:
            console.print("Force quitting...", "red")
            if reset_handle["h"] is not None:
                reset_handle["h"].cancel()
                reset_handle["h"] = None
            event.app.exit(result=exit_sentinel)
    
    # Alt+Left - Jump word left
    @bindings.add('escape', 'left')
    def _(event):
        """Jump to previous word."""
        buffer = event.app.current_buffer
        pos = buffer.document.find_previous_word_beginning()
        if pos:
            buffer.cursor_position += pos
    
    # Alt+Right - Jump word right  
    @bindings.add('escape', 'right')
    def _(event):
        """Jump to next word."""
        buffer = event.app.current_buffer
        pos = buffer.document.find_next_word_ending()
        if pos:
            buffer.cursor_position += pos
    
    return bindings
