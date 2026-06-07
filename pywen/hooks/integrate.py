from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple

from .manager import HookManager
from .models import HookEvent


def run_tool_with_hooks(
    *,
    hook_manager: HookManager,
    session_ctx: Dict[str, Any],
    tool_name: str,
    tool_input: Dict[str, Any],
    tool_callable: Callable[[Dict[str, Any]], Dict[str, Any]],
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    统一封装一次工具调用：
    - 先触发 PreToolUse
    - 如果未阻断 -> 执行工具
    - 执行成功后触发 PostToolUse
    返回: (success, user_msg, tool_response_or_none)
    """
    # PreToolUse
    cont, msg, _ = hook_manager.emit(
        event=HookEvent.PreToolUse,
        base_payload=session_ctx,
        tool_name=tool_name,
        tool_input=tool_input,
    )
    if not cont:
        return False, msg or f"{tool_name} blocked by PreToolUse hook.", None

    # 真正执行工具
    try:
        tool_resp = tool_callable(tool_input)
    except Exception as e:
        return False, f"{tool_name} execution error: {e}", None

    # PostToolUse
    cont2, msg2, extra2 = hook_manager.emit(
        event=HookEvent.PostToolUse,
        base_payload=session_ctx,
        tool_name=tool_name,
        tool_input=tool_input,
        tool_response=tool_resp,
    )
    if not cont2:
        return False, (msg2 or f"{tool_name} post hook blocked."), tool_resp

    return True, msg2, tool_resp

