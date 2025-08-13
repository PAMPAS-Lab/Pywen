"""Keyboard bindings and shortcuts for the CLI interface."""

import threading
from typing import Callable, Optional

from prompt_toolkit.key_binding import KeyBindings
from pywen.config.config import ApprovalMode
from pywen.ui.cli_console import CLIConsole
from pywen.core.permission_manager import PermissionLevel


def create_key_bindings(
    console_getter: Callable[[], CLIConsole], 
    cancel_event_getter: Optional[Callable[[], Optional[threading.Event]]] = None, 
    current_task_getter: Optional[Callable] = None
) -> KeyBindings:
    """创建键盘快捷键绑定"""
    bindings = KeyBindings()
    
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
        console = console_getter()
        if hasattr(console, 'config') and console.config:
            try:
                # Use new permission system if available
                if hasattr(console.config, 'get_permission_manager'):
                    permission_manager = console.config.get_permission_manager()
                    current_level = permission_manager.get_permission_level()

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
                    console.config.set_permission_level(next_level)

                    # Display status with appropriate color and icon
                    level_info = {
                        PermissionLevel.LOCKED: ("🔒 LOCKED", "全锁状态：所有操作都需要确认","red"),
                        PermissionLevel.EDIT_ONLY: ("✏️ EDIT_ONLY", "编辑权限：自动确认文件编辑，其他需要确认","yellow"),
                        PermissionLevel.PLANNING: ("📝 PLANNING", "规划权限：自动确认非编辑操作，编辑需要确认","blue"),
                        PermissionLevel.YOLO: ("🚀 YOLO", "锁开状态：自动确认所有操作","green")
                    }

                    icon_text, description , color= level_info[next_level]
                    console.print(f"{icon_text} - {description}",color)

                else:
                    # Fallback to old YOLO/DEFAULT toggle for backward compatibility
                    current_mode = console.config.get_approval_mode()
                    if current_mode == ApprovalMode.YOLO:
                        console.config.set_approval_mode(ApprovalMode.DEFAULT)
                        console.print("\n🔒 DEFAULT mode - tool confirmation required","yellow")
                    else:
                        console.config.set_approval_mode(ApprovalMode.YOLO)
                        console.print("\n🚀 YOLO mode - auto-approving all tools","green")

            except Exception as e:
                console.print(f"Error switching permission level: {e}","red")
        else:
            console.print("Configuration not available","red")
    
    # Shift+Tab - Toggle auto-accepting edits (placeholder)
    @bindings.add('s-tab')
    def _(event):
        """Toggle auto-accepting edits."""
        console = console_getter()
        console.print("[yellow]Auto-accepting edits toggled (not implemented yet)[/yellow]")
    
    # ESC - 取消当前操作
    @bindings.add('escape')
    def _(event):
        """Cancel current operation."""
        console = console_getter()
        cancel_event = cancel_event_getter() if cancel_event_getter else None
        
        buffer = event.app.current_buffer
        if buffer.text:
            buffer.reset()
            console.print("[yellow]Input cleared[/yellow]")
        elif cancel_event and not cancel_event.is_set():
            console.print("[yellow]Cancelling current operation...[/yellow]")
            cancel_event.set()
            # 如果有当前任务，也取消它
            if current_task_getter:
                task = current_task_getter()
                if task and not task.done():
                    task.cancel()
    
    # Ctrl+C - 智能处理：任务执行中取消任务，否则退出
    ctrl_c_count = 0
    ctrl_c_timer = None
    
    @bindings.add('c-c')
    def _(event):
        """Handle Ctrl+C - cancel task or quit."""
        nonlocal ctrl_c_count, ctrl_c_timer
        
        console = console_getter()
        cancel_event = cancel_event_getter() if cancel_event_getter else None
        
        # 检查是否有正在执行的任务
        current_task = current_task_getter() if current_task_getter else None
        has_running_task = current_task and not current_task.done()
        
        if has_running_task:
            # 如果有正在运行的任务，第一次按 Ctrl+C 取消任务
            console.print("\n[yellow]Cancelling current operation... (Press Ctrl+C again to force quit)[/yellow]")
            if cancel_event and not cancel_event.is_set():
                cancel_event.set()
            if current_task:
                current_task.cancel()
            
            # 重置计数器，给用户机会再次按 Ctrl+C 强制退出
            ctrl_c_count = 1
            
            def reset_count():
                nonlocal ctrl_c_count
                ctrl_c_count = 0
            
            if ctrl_c_timer:
                ctrl_c_timer.cancel()
            ctrl_c_timer = threading.Timer(3.0, reset_count)
            ctrl_c_timer.start()
            
        else:
            # 没有正在运行的任务，使用双击退出逻辑
            ctrl_c_count += 1
            
            if ctrl_c_count == 1:
                console.print("[yellow]Press Ctrl+C again to quit[/yellow]")
                
                def reset_count():
                    nonlocal ctrl_c_count
                    ctrl_c_count = 0
                
                if ctrl_c_timer:
                    ctrl_c_timer.cancel()
                ctrl_c_timer = threading.Timer(3.0, reset_count)
                ctrl_c_timer.start()
                
            elif ctrl_c_count >= 2:
                console.print("[red]Force quitting...[/red]")
                event.app.exit()
    
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
