from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Generic, Literal, Optional, TypeVar


class Agent_Events:
    USER_MESSAGE         = "user.message"
    LLM_STREAM_START     = "stream.start"
    TEXT_DELTA           = "text.delta"
    TEXT_DONE            = "text.done"
    REASONING_DELTA      = "reasoning.delta"
    REASONING_DONE       = "reasoning.done"
    TOOL_CALL            = "tool.call"
    TOOL_RESULT          = "tool.result"
    TURN_TOKEN_USAGE     = "turn.token_usage"
    TURN_COMPLETE        = "turn.complete"
    TURN_MAX_REACHED     = "turn.max_reached"
    TASK_COMPLETE        = "task.complete"
    WAITING_FOR_USER     = "waiting.for_user"
    USER_DEFINED         = "user_defined"
    CANCEL               = "cancel"
    ERROR                = "error"


AgentEventType = Literal[
    "user.message",
    "stream.start",
    "text.delta",
    "text.done",
    "reasoning.delta",
    "reasoning.done",
    "tool.call",
    "tool.result",
    "turn.token_usage", 
    "turn.complete",
    "turn.max_reached",
    "task.complete",
    "waiting.for_user",
    "cancel",
    "error",
    "user_defined",
]

T = TypeVar("T")

@dataclass
class AgentEvent(Generic[T]):
    type: AgentEventType
    data: Optional[T] = None

    @staticmethod
    def user_message(text: str, turn: int = 0) -> AgentEvent:
        return AgentEvent(Agent_Events.USER_MESSAGE , {"text": text, "turn": turn})

    @staticmethod
    def llm_stream_start(data = None) -> AgentEvent:
        return AgentEvent(Agent_Events.LLM_STREAM_START , None)

    @staticmethod
    def text_delta(content: str) -> AgentEvent:
        return AgentEvent(Agent_Events.TEXT_DELTA , {"content": content})

    @staticmethod
    def text_done(content: Optional[str] = None) -> AgentEvent:
        data = {"content": content} if content is not None else {}
        return AgentEvent(Agent_Events.TEXT_DONE , data)

    @staticmethod
    def tool_call(call_id: str, name:str, args: Any) -> AgentEvent:
        data = {"call_id": call_id, "name": name, "args": args}
        return AgentEvent(Agent_Events.TOOL_CALL, data)

    @staticmethod
    def tool_result(call_id: str, name:str, result: Any, success: bool, args: Any) -> AgentEvent:
        data = {"call_id": call_id, "name": name, "result": result, "success": success,"args": args}
        return AgentEvent(Agent_Events.TOOL_RESULT , data)

    @staticmethod
    def turn_token_usage(total_tokens: int) -> AgentEvent:
        data = {"total_tokens": total_tokens}
        return AgentEvent(Agent_Events.TURN_TOKEN_USAGE , data)

    @staticmethod
    def turn_max_reached(max_turns: int) -> AgentEvent:
        data = {"max_turns": max_turns}
        return AgentEvent(Agent_Events.TURN_MAX_REACHED , data)

    @staticmethod
    def turn_complete(summary: Optional[str] = None) -> AgentEvent:
        data = {"summary": summary} if summary is not None else {}
        return AgentEvent(Agent_Events.TURN_COMPLETE , data)

    @staticmethod
    def task_complete(summary: Optional[str] = None) -> AgentEvent:
        data = {"summary": summary} if summary is not None else {}
        return AgentEvent(Agent_Events.TASK_COMPLETE , data)

    @staticmethod
    def user_defined(item: Dict) ->AgentEvent:
        return AgentEvent(Agent_Events.USER_DEFINED , item)

    @staticmethod
    def error(message: str, code: Optional[int] = None) -> AgentEvent:
        # 同时填充 message 与 error 字段，兼容旧的消费端
        data = {"message": message, "error": message, "code": None}
        if code is not None:
            data["code"] = code
        return AgentEvent(Agent_Events.ERROR , data)
