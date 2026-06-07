"""Models for the Python skills system."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional


class SkillScope(str, Enum):
    REPO = "repo"
    USER = "user"
    SYSTEM = "system"
    ADMIN = "admin"


@dataclass(frozen=True)
class SkillDependency:
    """Declares a dependency from one skill to another."""
    name: str
    min_version: Optional[str] = None
    max_version: Optional[str] = None


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    short_description: Optional[str]
    path: Path
    scope: SkillScope
    version: Optional[str] = None
    requires: tuple = field(default_factory=tuple)  # tuple[SkillDependency, ...]


@dataclass(frozen=True)
class SkillError:
    path: Path
    message: str


@dataclass
class SkillLoadOutcome:
    skills: list[SkillMetadata] = field(default_factory=list)
    errors: list[SkillError] = field(default_factory=list)
    # Performance tracking
    load_duration_ms: float = 0.0
    parse_durations_ms: dict = field(default_factory=dict)  # dict[str, float]


@dataclass(frozen=True)
class SkillRoot:
    path: Path
    scope: SkillScope


@dataclass(frozen=True)
class SkillInstructions:
    name: str
    path: str
    contents: str


@dataclass
class SkillInjections:
    items: list[SkillInstructions] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class UserInput:
    kind: str
    name: Optional[str] = None
    path: Optional[str] = None

    @staticmethod
    def skill(name: str, path: Path) -> "UserInput":
        return UserInput(kind="skill", name=name, path=str(path))


@dataclass
class SkillHealthReport:
    """Health check report for a single skill."""
    skill_name: str
    skill_path: Path
    scope: SkillScope
    is_healthy: bool
    issues: list[str] = field(default_factory=list)


SkillInputCollection = Iterable[UserInput]
