"""Turn management for conversation flow."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum

from pywen.utils.llm_basics import LLMMessage, LLMResponse
from pywen.utils.tool_basics import ToolCall, ToolResult

class TurnStatus(Enum):
    """Turn execution status."""
    ACTIVE = "active"
    COMPLETED = "completed"
    SUCCESS = "success"
    FAILURE = "failure"
    MAX_ITERATIONS = "max_iterations"
    ERROR = "error"

@dataclass
class Turn:
    """Represents a conversation turn with tool interactions."""
    
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: TurnStatus = TurnStatus.ACTIVE
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    
    # Messages
    user_message: Optional[str] = None
    system_message: Optional[str] = None
    assistant_messages: List[str] = field(default_factory=list)
    
    # LLM interactions
    llm_requests: List[List[LLMMessage]] = field(default_factory=list)
    llm_responses: List[LLMResponse] = field(default_factory=list)
    
    # Tool interactions
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_results: List[ToolResult] = field(default_factory=list)
    
    # Metadata
    total_tokens: int = 0
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # New: Iteration support
    iterations: int = 0
    events: List[Dict[str, Any]] = field(default_factory=list)
    
    @property
    def assistant_response(self) -> Optional[LLMResponse]:
        """Get the latest assistant response."""
        return self.llm_responses[-1] if self.llm_responses else None
    
    def add_event(self, event_type: str, data: Any):
        """Add event to turn."""
        self.events.append({
            "type": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat()
        })
    
    def add_user_message(self, message: str):
        """Add user message to turn."""
        self.user_message = message
        self.add_event("user_message", message)
    
    def add_llm_interaction(self, request: List[LLMMessage], response: LLMResponse):
        """Add LLM interaction to turn."""
        self.llm_requests.append(request)
        self.llm_responses.append(response)
        
        if response.usage:
            self.total_tokens += response.usage.get("total_tokens", 0)
        
        if response.content:
            self.assistant_messages.append(response.content)
    
    def add_assistant_response(self, response: LLMResponse):
        """Add assistant response (for compatibility)."""
        self.llm_responses.append(response)
        if response.content:
            self.assistant_messages.append(response.content)
        
        # Update token count
        if hasattr(response, 'usage') and response.usage:
            if hasattr(response.usage, 'total_tokens'):
                self.total_tokens += response.usage.total_tokens
            elif hasattr(response.usage, 'input_tokens') and hasattr(response.usage, 'output_tokens'):
                self.total_tokens += response.usage.input_tokens + response.usage.output_tokens
    
    def add_tool_call(self, tool_call: ToolCall):
        """Add tool call to turn."""
        self.tool_calls.append(tool_call)
        self.events.append({
            "type": "tool_call",
            "data": {
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "call_id": tool_call.call_id
            },
            "timestamp": datetime.now().isoformat()
        })
    
    def add_tool_result(self, tool_result: ToolResult):
        """Add tool result to turn."""
        self.tool_results.append(tool_result)
        self.events.append({
            "type": "tool_result",
            "data": {
                "call_id": tool_result.call_id,
                "result": tool_result.result,
                "error": tool_result.error,
                "success": tool_result.success
            },
            "timestamp": datetime.now().isoformat()
        })
    
    def get_assistant_messages(self) -> List[str]:
        """Get all assistant messages."""
        return self.assistant_messages
    
    def complete(self, status: TurnStatus = TurnStatus.COMPLETED):
        """Mark turn as completed."""
        self.status = status
        self.end_time = datetime.now()
    
    def error(self, message: str):
        """Mark turn as error."""
        self.status = TurnStatus.ERROR
        self.error_message = message
        self.end_time = datetime.now()
    
    def get_duration(self) -> Optional[float]:
        """Get turn duration in seconds."""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert turn to dictionary."""
        return {
            "id": self.id,
            "status": self.status.value,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration": self.get_duration(),
            "user_message": self.user_message,
            "assistant_messages": self.assistant_messages,
            "tool_calls_count": len(self.tool_calls),
            "tool_results_count": len(self.tool_results),
            "total_tokens": self.total_tokens,
            "error_message": self.error_message,
            "metadata": self.metadata
        }
