"""Basic Tool data structures."""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from enum import Enum
from datetime import datetime

@dataclass
class ToolCall:
    """Represents a tool call from the LLM."""
    call_id: str
    name: str
    arguments: Optional[Dict[str, Any]] = None
    type: Optional[str] = None
    input: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "call_id": self.call_id,
            "name": self.name,
            "arguments": self.arguments,
            "type" : self.type,
            "input": self.input
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
            input=data.get("input", "")
        )

class ToolStatus(Enum):
    """Tool execution status."""
    SUCCESS = "success"
    ERROR = "error"
    PENDING = "pending"
    RUNNING = "running"

class ToolResultDisplay:
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
class ToolResult:
    """Enhanced tool result matching TypeScript version."""
    call_id: str
    result: Optional[str] = None
    error: Optional[str] = None
    display: Optional[ToolResultDisplay] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    summary: Optional[str] = None
    
    @property
    def success(self) -> bool:
        """Check if the tool execution was successful."""
        return self.error is None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
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
