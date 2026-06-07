from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class ToolCall:
    """Represents a tool call from the LLM."""
    call_id: str
    name: str
    arguments: Optional[Dict[str, Any] | str] = None
    type: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "call_id": self.call_id,
            "name": self.name,
            "arguments": self.arguments,
            "type" : self.type,
        }

    @classmethod
    def from_raw(cls, data: dict):
        import json
        args = data.get("arguments", "")
        if isinstance(args, str):
            args = json.loads(args) if args.strip() else {}
        return cls(
            call_id=data["call_id"],
            name=data["name"],
            arguments=args,
            type=data.get("type"),
        )

class ToolCallResultDisplay:
    """Tool result display configuration."""
    def __init__(self, markdown: str = "", summary: str = ""):
        self.markdown = markdown
        self.summary = summary

@dataclass
class ToolCallConfirmationDetails:
    """Details for tool call confirmation."""
    type: str
    message: str
    is_risky: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ToolCallResult:
    call_id: str
    result: Optional[str | Dict] = None
    error: Optional[str] = None
    display: Optional[ToolCallResultDisplay] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    summary: Optional[str] = None
    
    @property
    def success(self) -> bool:
        return self.error is None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "call_id": self.call_id,
            "result": self.result,
            "error": self.error,
            "display": self.display.__dict__ if self.display else None,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
            "summary": self.summary,
            "success": self.success
        }

@dataclass
class LLMMessage:
    role: str  # "system", "user", "assistant", "tool"
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None 

@dataclass
class LLMUsage:
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
            model=data.get("model"),
            finish_reason=data.get("finish_reason")
        )
