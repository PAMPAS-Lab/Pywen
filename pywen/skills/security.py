"""Security scanning for skill content.

When a skill is loaded, its description and full body are scanned against
a set of security rules:

- HIGH risk patterns (prompt injection, path traversal) cause the skill
  to be rejected with a SkillParseError.
- MEDIUM risk patterns (references to sensitive files) trigger a warning
  but the skill is still loaded.

Trusted paths can be configured via ``configure_trusted_paths()``; skills
under those paths bypass scanning entirely.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Tuple


class RiskLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class SecurityRule:
    name: str
    pattern: re.Pattern
    risk_level: RiskLevel
    description: str


# Extensible rule set — add new rules here without modifying scan logic.
SECURITY_RULES: List[SecurityRule] = [
    # High risk: prompt injection patterns
    SecurityRule(
        name="prompt_injection_ignore",
        pattern=re.compile(
            r'ignore\s+(previous|all|above)\s+instructions',
            re.IGNORECASE
        ),
        risk_level=RiskLevel.HIGH,
        description="Possible prompt injection: 'ignore previous instructions'",
    ),
    SecurityRule(
        name="prompt_injection_override",
        pattern=re.compile(
            r'(system\s+prompt|system_prompt)\s+(override|bypass|hack)',
            re.IGNORECASE
        ),
        risk_level=RiskLevel.HIGH,
        description="Possible system prompt override attempt",
    ),
    SecurityRule(
        name="path_traversal",
        pattern=re.compile(r'\.\./\.\./',
        ),
        risk_level=RiskLevel.HIGH,
        description="Path traversal pattern detected",
    ),
    # Medium risk: sensitive file references
    SecurityRule(
        name="sensitive_file_access",
        pattern=re.compile(
            r'(\/etc\/passwd|\/etc\/shadow|~\/\.ssh|\.env)',
            re.IGNORECASE
        ),
        risk_level=RiskLevel.MEDIUM,
        description="Reference to sensitive system files",
    ),
]

# Global set of trusted paths (configured via configure_trusted_paths).
# Protected by _trusted_paths_lock for thread-safe reads and writes.
_trusted_paths: set[Path] = set()
_trusted_paths_lock = threading.Lock()


def configure_trusted_paths(paths: List[str]) -> None:
    """Set trusted paths from configuration. Skills under these paths bypass scanning."""
    global _trusted_paths
    new_set: set[Path] = set()
    for p in paths:
        expanded = Path(p).expanduser().resolve()
        new_set.add(expanded)
    with _trusted_paths_lock:
        _trusted_paths = new_set


def is_trusted_path(skill_path: Path) -> bool:
    """Return True if the skill file resides under a trusted path."""
    with _trusted_paths_lock:
        current_paths = _trusted_paths
    try:
        resolved = skill_path.resolve()
    except OSError:
        resolved = skill_path
    for trusted in current_paths:
        try:
            resolved.relative_to(trusted)
            return True
        except ValueError:
            continue
    return False


def scan_skill_content(content: str) -> List[Tuple[SecurityRule, str]]:
    """Scan content against all security rules, returning matched rules with context snippets."""
    findings: List[Tuple[SecurityRule, str]] = []
    for rule in SECURITY_RULES:
        for match in rule.pattern.finditer(content):
            start = max(0, match.start() - 30)
            end = min(len(content), match.end() + 30)
            context = content[start:end].replace('\n', ' ')
            findings.append((rule, context))
    return findings
