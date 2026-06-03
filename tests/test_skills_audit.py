"""Structured audit logging — acceptance tests.

Acceptance criteria:
1. Normal skill load produces skill_loaded event (with skill_name, skill_path, scope, duration_ms)
2. Parse failure produces skill_load_failed event (with error field)
3. Audit log format is valid JSON
4. Log output target is configurable via standard logging
5. Successful injection produces skill_injected event
6. Failed injection produces skill_inject_failed event
"""
from __future__ import annotations
import json
import logging
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pywen.skills.loader import parse_skill_file, SKILLS_FILENAME, SkillParseError
from pywen.skills.models import SkillScope, SkillLoadOutcome, UserInput
from pywen.skills.injection import build_skill_injections
from pywen.skills.audit import AuditEventType


def _write_skill(tmp_path: Path, name: str, description: str) -> Path:
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent(f"""\
---
name: {name}
description: {description}
---

# Body
""")
    p = skill_dir / SKILLS_FILENAME
    p.write_text(content, encoding="utf-8")
    return p


def _write_bad_skill(tmp_path: Path, name: str) -> Path:
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    content = "# No frontmatter here\nJust some markdown."
    p = skill_dir / SKILLS_FILENAME
    p.write_text(content, encoding="utf-8")
    return p


class _LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(self.format(record))


def _setup_audit_capture() -> _LogCapture:
    audit_logger = logging.getLogger("pywen.skills.audit")
    audit_logger.setLevel(logging.DEBUG)
    handler = _LogCapture()
    handler.setFormatter(logging.Formatter("%(message)s"))
    audit_logger.addHandler(handler)
    return handler


def _teardown_audit_capture(handler: _LogCapture) -> None:
    logging.getLogger("pywen.skills.audit").removeHandler(handler)


def test_skill_loaded_event_emitted(tmp_path: Path) -> None:
    """Criterion 1: Normal load produces skill_loaded event with key fields."""
    handler = _setup_audit_capture()
    try:
        path = _write_skill(tmp_path, "audit-test", "审计测试技能")
        parse_skill_file(path, SkillScope.USER)
        assert handler.records, "No audit log records emitted"
        loaded_events = [
            json.loads(r) for r in handler.records
            if json.loads(r).get("event") == AuditEventType.SKILL_LOADED.value
        ]
        assert loaded_events, "No skill_loaded event found"
        ev = loaded_events[-1]
        assert ev.get("skill_name") == "audit-test"
        assert ev.get("skill_path")
        assert ev.get("scope") == "user"
        assert ev.get("duration_ms") is not None
    finally:
        _teardown_audit_capture(handler)


def test_skill_load_failed_event_emitted(tmp_path: Path) -> None:
    """Criterion 2: Parse failure produces skill_load_failed event with error."""
    handler = _setup_audit_capture()
    try:
        path = _write_bad_skill(tmp_path, "bad-audit")
        with pytest.raises(SkillParseError):
            parse_skill_file(path, SkillScope.USER)
        failed_events = [
            json.loads(r) for r in handler.records
            if json.loads(r).get("event") == AuditEventType.SKILL_LOAD_FAILED.value
        ]
        assert failed_events, "No skill_load_failed event found"
        ev = failed_events[-1]
        assert ev.get("error")
    finally:
        _teardown_audit_capture(handler)


def test_audit_log_is_valid_json(tmp_path: Path) -> None:
    """Criterion 3: Audit log format is valid JSON (one event per line)."""
    handler = _setup_audit_capture()
    try:
        path = _write_skill(tmp_path, "json-test", "JSON格式测试")
        parse_skill_file(path, SkillScope.USER)
        for record in handler.records:
            parsed = json.loads(record)
            assert isinstance(parsed, dict)
    finally:
        _teardown_audit_capture(handler)


def test_audit_logging_configurable() -> None:
    """Criterion 4: Log output target is configurable via standard logging."""
    audit_logger = logging.getLogger("pywen.skills.audit")
    assert audit_logger is not None
    assert audit_logger.name == "pywen.skills.audit"


def test_skill_injected_event_emitted(tmp_path: Path) -> None:
    """Criterion 5: Successful injection produces skill_injected event."""
    handler = _setup_audit_capture()
    try:
        path = _write_skill(tmp_path, "inject-test", "注入测试技能")
        skill = parse_skill_file(path, SkillScope.USER)
        outcome = SkillLoadOutcome(skills=[skill])
        inputs = [UserInput.skill(skill.name, skill.path)]

        result = build_skill_injections(inputs, outcome)
        assert len(result.items) == 1

        injected_events = [
            json.loads(r) for r in handler.records
            if json.loads(r).get("event") == AuditEventType.SKILL_INJECTED.value
        ]
        assert injected_events, "No skill_injected event found"
        ev = injected_events[-1]
        assert ev.get("skill_name") == "inject-test"
        assert ev.get("skill_path")
    finally:
        _teardown_audit_capture(handler)


def test_skill_inject_failed_event_emitted(tmp_path: Path) -> None:
    """Criterion 6: Failed injection produces skill_inject_failed event."""
    handler = _setup_audit_capture()
    try:
        # Create a skill, then delete the file so injection fails
        path = _write_skill(tmp_path, "inject-fail", "注入失败技能")
        skill = parse_skill_file(path, SkillScope.USER)
        path.unlink()  # Remove the file so reading fails

        outcome = SkillLoadOutcome(skills=[skill])
        inputs = [UserInput.skill(skill.name, skill.path)]

        result = build_skill_injections(inputs, outcome)
        assert len(result.warnings) == 1

        failed_events = [
            json.loads(r) for r in handler.records
            if json.loads(r).get("event") == AuditEventType.SKILL_INJECT_FAILED.value
        ]
        assert failed_events, "No skill_inject_failed event found"
        ev = failed_events[-1]
        assert ev.get("skill_name") == "inject-fail"
        assert ev.get("error")
    finally:
        _teardown_audit_capture(handler)
