"""Structured audit logging for the skills system.

Every skill load and injection produces a structured JSON event emitted
through the standard Python ``logging`` module (logger name:
``pywen.skills.audit``).  Applications can configure handlers and
formatters on that logger without modifying the framework.

Example log line::

    {"timestamp":"2026-05-17T22:00:00+08:00","event":"skill_loaded",
     "skill_name":"docker","scope":"user","duration_ms":12.34}
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger("pywen.skills.audit")


class AuditEventType(str, Enum):
    SKILL_LOADED = "skill_loaded"
    SKILL_LOAD_FAILED = "skill_load_failed"
    SKILL_INJECTED = "skill_injected"
    SKILL_INJECT_FAILED = "skill_inject_failed"
    SYSTEM_SKILLS_INSTALLED = "system_skills_installed"
    SECURITY_VIOLATION = "security_violation"


@dataclass
class AuditEvent:
    event: AuditEventType
    timestamp: str
    skill_name: Optional[str] = None
    skill_path: Optional[str] = None
    scope: Optional[str] = None
    duration_ms: Optional[float] = None
    error: Optional[str] = None
    details: Optional[dict] = None

    def to_json(self) -> str:
        """Serialize to a single-line JSON string with null fields omitted."""
        d = asdict(self)
        d["event"] = self.event.value if isinstance(self.event, AuditEventType) else self.event
        d = {k: v for k, v in d.items() if v is not None}
        return json.dumps(d, ensure_ascii=False)


def emit(event: AuditEvent) -> None:
    """Emit an audit event to the logging system.

    Configure output via ``logging.getLogger('pywen.skills.audit')``.
    """
    logger.info(event.to_json())


def make_event(
    event_type: AuditEventType,
    *,
    skill_name: Optional[str] = None,
    skill_path: Optional[str] = None,
    scope: Optional[str] = None,
    duration_ms: Optional[float] = None,
    error: Optional[str] = None,
    details: Optional[dict] = None,
) -> AuditEvent:
    """Convenience constructor that fills in the current timestamp."""
    return AuditEvent(
        event=event_type,
        timestamp=datetime.now().isoformat(),
        skill_name=skill_name,
        skill_path=skill_path,
        scope=scope,
        duration_ms=duration_ms,
        error=error,
        details=details,
    )
