# manager.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .matcher import matches_tool
from .models import HookEvent, HooksConfig
from .runner import run_command_hook_async


class HookManager:
    def __init__(self, config: HooksConfig):
        self.config = config

    async def emit(
        self,
        event: HookEvent,
        base_payload: Dict[str, Any],
        tool_name: Optional[str] = None,
        tool_input: Optional[Dict[str, Any]] = None,
        tool_response: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        groups = self.config.hooks.get(event.value, [])
        extra: Dict[str, Any] = {}
        user_msg: Optional[str] = None
        continue_ok = True

        payload = {
            "session_id": base_payload.get("session_id", ""),
            "cwd": base_payload.get("cwd", str(Path.cwd())),
            "hook_event_name": event.value,
        }
        if tool_name is not None:
            payload["tool_name"] = tool_name
        if tool_input is not None:
            payload["tool_input"] = tool_input
        if tool_response is not None:
            payload["tool_response"] = tool_response

        payload.update({k: v for k, v in base_payload.items() if k not in payload})

        for group in groups:
            if (
                event in (HookEvent.PreToolUse, HookEvent.PostToolUse)
                and (not tool_name or not matches_tool(group.matcher, tool_name))
            ):
                continue

            for cmd in group.hooks:
                res = await run_command_hook_async(
                    cmd=cmd.command,
                    payload=payload,
                    timeout=cmd.timeout,
                )
                if res.json_out:
                    cont = res.json_out.get("continue")
                    if cont is False:
                        continue_ok = False
                        user_msg = res.json_out.get("stopReason") or user_msg

                    sysmsg = res.json_out.get("systemMessage")
                    if sysmsg:
                        user_msg = (user_msg or "") + (("\n" if user_msg else "") + sysmsg)

                    hso = res.json_out.get("hookSpecificOutput", {})
                    if event == HookEvent.PreToolUse:
                        pd = hso.get("permissionDecision")
                        reason = hso.get("permissionDecisionReason")
                        if pd == "deny":
                            continue_ok = False
                            user_msg = reason or user_msg
                        elif pd == "ask":
                            continue_ok = False
                            user_msg = reason or "Tool call requires confirmation."
                    elif event == HookEvent.PostToolUse:
                        decision = res.json_out.get("decision")
                        if decision == "block":
                            continue_ok = False
                            user_msg = res.json_out.get("reason") or user_msg
                        add_ctx = hso.get("additionalContext")
                        if add_ctx:
                            extra.setdefault("additionalContext", "")
                            extra["additionalContext"] += (("\n" if extra["additionalContext"] else "") + add_ctx)
                    elif event == HookEvent.UserPromptSubmit:
                        decision = res.json_out.get("decision")
                        if decision == "block":
                            continue_ok = False
                            user_msg = res.json_out.get("reason") or user_msg
                        else:
                            add_ctx = hso.get("additionalContext")
                            if add_ctx:
                                extra.setdefault("additionalContext", "")
                                extra["additionalContext"] += (("\n" if extra["additionalContext"] else "") + add_ctx)
                    elif event in (HookEvent.Stop, HookEvent.SubagentStop):
                        decision = res.json_out.get("decision")
                        if decision == "block":
                            continue_ok = False
                            user_msg = res.json_out.get("reason") or user_msg
                    elif event == HookEvent.SessionStart:
                        add_ctx = hso.get("additionalContext")
                        if add_ctx:
                            extra.setdefault("additionalContext", "")
                            extra["additionalContext"] += (("\n" if extra["additionalContext"] else "") + add_ctx)
                else:
                    if res.exit_code == 0:
                        pass
                    elif res.exit_code == 2:
                        continue_ok = False
                        user_msg = (user_msg or "") + (("\n" if user_msg else "") + (res.stderr or "Hook blocked."))
                    else:
                        user_msg = (user_msg or "") + (("\n" if user_msg else "") + (res.stderr or "Hook error."))

                if not continue_ok:
                    return continue_ok, user_msg, extra

        return continue_ok, user_msg, extra
