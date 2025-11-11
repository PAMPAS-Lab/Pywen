from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional, Generic, TypeVar, Literal

EventType = Literal[
    "created", 
    "output_text.delta",
    "output_item.done",
    "completed",
    "error",
    "rate_limits",
    "token_usage",
    "tool_call.delta",
    "tool_call.ready",
    "web_search_begin",
    "message_start",
    "content_block_start",
    "content_block_delta",
    "content_block_stop",
    "message_delta",
    "tool_call.delta_json",
    "reasoning_text.delta",
    "reasoning_summary_text.delta",
]

T = TypeVar("T")

@dataclass
class ResponseEvent(Generic[T]):
    type: EventType
    data: Optional[T] = None

    @staticmethod
    def created(meta: Optional[Dict[str, Any]] = None) -> ResponseEvent:
        return ResponseEvent("created", meta or {})

    @staticmethod
    def output_item_done(meta: Dict[str, Any]) -> ResponseEvent:
        return ResponseEvent("output_item.done", meta) 

    @staticmethod
    def text_delta(delta: str) -> ResponseEvent[str]:
        return ResponseEvent("output_text.delta", delta)

    @staticmethod
    def completed(meta: Optional[Dict[str, Any]] = None) -> ResponseEvent:
        return ResponseEvent("completed", meta or {})

    @staticmethod
    def error(message: str, extra: Optional[Dict[str, Any]] = None) -> ResponseEvent[Dict[str, Any]]:
        payload = {"message": message, **(extra or {})}
        return ResponseEvent("error", payload)

    @staticmethod
    def tool_call_delta(call_id: str, name: str | None, fragment: str, kind: str) -> ResponseEvent[Dict[str, Any]]:
        # kind: "function" | "custom"
        payload = {"call_id": call_id, "name": name, "fragment": fragment, "kind": kind}
        return ResponseEvent("tool_call.delta", payload)

    @staticmethod
    def tool_call_ready(call_id: str, name: str | None, args: Any, kind: str) -> ResponseEvent[Dict[str, Any]]:
        payload = {"call_id": call_id, "name": name, "args": args, "kind": kind}
        return ResponseEvent("tool_call.ready", payload)

    @staticmethod
    def web_search_begin(call_id: str)-> ResponseEvent[Dict[str, Any]]:
        return ResponseEvent("web_search_begin", {"call_id": call_id})

    @staticmethod
    def message_start(meta: Dict[str, Any]) -> ResponseEvent[Dict[str, Any]]:
        return ResponseEvent("message_start", meta)

    @staticmethod
    def content_block_start(meta: Dict[str, Any]) -> ResponseEvent[Dict[str, Any]]:
        return ResponseEvent("content_block_start", meta)

    @staticmethod
    def content_block_delta(meta: Dict[str, Any]) -> ResponseEvent[Dict[str, Any]]:
        return ResponseEvent("content_block_delta", meta)

    @staticmethod
    def content_block_stop(meta: Dict[str, Any]) -> ResponseEvent[Dict[str, Any]]:
        return ResponseEvent("content_block_stop", meta)

    @staticmethod
    def message_delta(meta: Dict[str, Any]) -> ResponseEvent[Dict[str, Any]]:
        return ResponseEvent("message_delta", meta)

    @staticmethod
    def tool_call_delta_json(partial_json: str) -> ResponseEvent[str]:
        return ResponseEvent("tool_call.delta_json", partial_json)

    @staticmethod
    def reasoning_delta(delta: str) -> ResponseEvent[str]:
        return ResponseEvent("reasoning_text.delta", delta)

    @staticmethod 
    def reasoning_summary_text_delta(meta: Optional[Dict[str, Any]] = None) -> ResponseEvent:
        return ResponseEvent("reasoning_summary_text.delta", meta or {})
