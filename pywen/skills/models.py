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
class SkillMetadata:
    name: str
    description: str
    short_description: Optional[str]
    path: Path
    scope: SkillScope

@dataclass(frozen=True)
class SkillError:
    path: Path
    message: str

@dataclass
class SkillLoadOutcome:
    skills: list[SkillMetadata] = field(default_factory=list)
    errors: list[SkillError] = field(default_factory=list)

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

SkillInputCollection = Iterable[UserInput]
