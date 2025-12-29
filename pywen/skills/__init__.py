"""Python implementation of Codex skills discovery and injection."""

from .models import (
    SkillScope,
    SkillMetadata,
    SkillError,
    SkillLoadOutcome,
    SkillRoot,
    SkillInstructions,
    SkillInjections,
    UserInput,
)
from .loader import (
    load_skills,
    load_skills_from_roots,
    skill_roots_for_cwd,
    user_skills_root,
    system_skills_root,
    admin_skills_root,
    repo_skills_root,
)
from .manager import SkillsManager
from .render import render_skills_section
from .injection import build_skill_injections
from .system import system_cache_root_dir, install_system_skills

__all__ = [
    "SkillScope",
    "SkillMetadata",
    "SkillError",
    "SkillLoadOutcome",
    "SkillRoot",
    "SkillInstructions",
    "SkillInjections",
    "UserInput",
    "load_skills",
    "load_skills_from_roots",
    "skill_roots_for_cwd",
    "user_skills_root",
    "system_skills_root",
    "admin_skills_root",
    "repo_skills_root",
    "SkillsManager",
    "render_skills_section",
    "build_skill_injections",
    "system_cache_root_dir",
    "install_system_skills",
]
