from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional, Union

EventType = Literal[
    "created",
    "output_text.delta",
    "reasoning_summary.delta",
    "reasoning_content.delta",
    "output_item.done",
    "completed",
    "error",
    "rate_limits",
    "token_usage",
    "tool_call.delta",
    "tool_call.ready",
]

@dataclass
class ResponseEvent:
    type: EventType
    data: Optional[Union[str, Dict[str, Any]]] = None

    @staticmethod
    def created(meta: Optional[Dict[str, Any]] = None) -> "ResponseEvent":
        return ResponseEvent("created", meta or {})

    @staticmethod
    def text_delta(delta: str) -> "ResponseEvent":
        return ResponseEvent("output_text.delta", delta)

    @staticmethod
    def completed(meta: Optional[Dict[str, Any]] = None) -> "ResponseEvent":
        return ResponseEvent("completed", meta or {})

    @staticmethod
    def error(message: str, extra: Optional[Dict[str, Any]] = None) -> "ResponseEvent":
        payload = {"message": message, **(extra or {})}
        return ResponseEvent("error", payload)

    @staticmethod
    def tool_call_delta(call_id: str, name: str | None, fragment: str, kind: str):
        # kind: "function" | "custom"
        payload = {"call_id": call_id, "name": name, "fragment": fragment, "kind": kind}
        return ResponseEvent("tool_call.delta", payload)

    @staticmethod
    def tool_call_ready(call_id: str, name: str | None, args: dict, kind: str):
        payload = {"call_id": call_id, "name": name, "args": args, "kind": kind}
        return ResponseEvent("tool_call.ready", payload)

