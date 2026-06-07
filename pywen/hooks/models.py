from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class HookEvent(str, Enum):
    PreToolUse = "PreToolUse"
    PostToolUse = "PostToolUse"
    Notification = "Notification"
    UserPromptSubmit = "UserPromptSubmit"
    Stop = "Stop"
    SubagentStop = "SubagentStop"
    PreCompact = "PreCompact"
    SessionStart = "SessionStart"
    SessionEnd = "SessionEnd"

@dataclass
class HookCommand:
    type: str
    command: str
    timeout: Optional[int] = None  # seconds

@dataclass
class HookGroup:
    matcher: Optional[str] = None  # only for PreToolUse/PostToolUse
    hooks: List[HookCommand] = field(default_factory=list)

@dataclass
class HooksConfig:
    hooks: Dict[str, List[HookGroup]] = field(default_factory=dict)

class BaseHookInput(TypedDict, total=False):
    session_id: str
    cwd: str
    hook_event_name: str

class ToolPayload(TypedDict, total=False):
    tool_name: str
    tool_input: Dict[str, Any]
    tool_response: Dict[str, Any]

class NotificationPayload(TypedDict, total=False):
    message: str

class UserPromptPayload(TypedDict, total=False):
    prompt: str

class StopPayload(TypedDict, total=False):
    stop_hook_active: bool

class PreCompactPayload(TypedDict, total=False):
    trigger: str
    custom_instructions: str

class SessionStartPayload(TypedDict, total=False):
    source: str  # "startup" | "resume" | "clear" | "compact"

class SessionEndPayload(TypedDict, total=False):
    reason: str  # "clear" | "logout" | "prompt_input_exit" | "other"

