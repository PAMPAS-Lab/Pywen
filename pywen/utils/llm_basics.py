"""Basic LLM data structures."""

from dataclasses import dataclass
from typing import List, Optional
from pywen.utils.tool_basics import ToolCall

@dataclass
class LLMMessage:
    """Standard message format for LLM interactions."""
    role: str  # "system", "user", "assistant", "tool"
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None  # For tool response messages

@dataclass
class LLMUsage:
    """Token usage information."""
    input_tokens: int
    output_tokens: int
    total_tokens: int
    
    def __add__(self, other: "LLMUsage") -> "LLMUsage":
        return LLMUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens
        )

@dataclass
class LLMResponse:
    """Standard LLM response format."""
    content: str
    tool_calls: Optional[List[ToolCall]] = None
    usage: Optional[LLMUsage] = None
    model: Optional[str] = None
    finish_reason: Optional[str] = None

    @classmethod
    def from_raw(cls, data: dict):
        """Create LLMResponse from raw dictionary."""
        usage = None
        tc = None
        if "usage" in data and data["usage"]:
            tk = data["usage"].model_dump() if hasattr(data["usage"], "model_dump") else data["usage"]
            usage = LLMUsage(
                input_tokens = tk.get("input_tokens", 0),
                output_tokens = tk.get("output_tokens", 0),
                total_tokens = tk.get("total_tokens", 0)
            )
        if "tool_calls" in data and data["tool_calls"]:
            tc = [ToolCall.from_raw(tc) for tc in data["tool_calls"]]

        return cls(
            content=data.get("content", ""),
            tool_calls= tc, 
            usage=usage,
            model=data.get("model", None),
            finish_reason=data.get("finish_reason")
        )
