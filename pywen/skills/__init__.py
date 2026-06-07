"""Python implementation of Codex skills discovery and injection."""

from .audit import (
    AuditEvent,
    AuditEventType,
)
from .audit import (
    emit as emit_audit_event,
)
from .audit import (
    make_event as make_audit_event,
)
from .dependency_resolver import DependencyError, check_dependencies
from .health import (
    check_all_skills_health,
    check_skill_health,
    format_health_report_json,
    format_health_report_text,
    run_health_check_cli,
)
from .injection import build_skill_injections
from .loader import (
    SkillParseError,
    admin_skills_root,
    load_skills,
    load_skills_from_roots,
    parse_skill_file,
    repo_skills_root,
    skill_roots_for_cwd,
    system_skills_root,
    user_skills_root,
)
from .manager import SkillsManager
from .models import (
    SkillDependency,
    SkillError,
    SkillHealthReport,
    SkillInjections,
    SkillInstructions,
    SkillLoadOutcome,
    SkillMetadata,
    SkillRoot,
    SkillScope,
    UserInput,
)
from .ranker import rank_skills_by_relevance
from .render import render_skills_section
from .security import (
    SECURITY_RULES,
    RiskLevel,
    SecurityRule,
    configure_trusted_paths,
    is_trusted_path,
    scan_skill_content,
)
from .system import install_system_skills, system_cache_root_dir

__all__ = [
    # Core models
    "SkillScope",
    "SkillMetadata",
    "SkillDependency",
    "SkillError",
    "SkillLoadOutcome",
    "SkillRoot",
    "SkillInstructions",
    "SkillInjections",
    "SkillHealthReport",
    "UserInput",
    # Loader
    "load_skills",
    "load_skills_from_roots",
    "skill_roots_for_cwd",
    "user_skills_root",
    "system_skills_root",
    "admin_skills_root",
    "repo_skills_root",
    "parse_skill_file",
    "SkillParseError",
    # Manager
    "SkillsManager",
    # Renderer
    "render_skills_section",
    # Injection
    "build_skill_injections",
    # System
    "system_cache_root_dir",
    "install_system_skills",
    # Dependency resolution
    "check_dependencies",
    "DependencyError",
    # Security scanning
    "scan_skill_content",
    "configure_trusted_paths",
    "is_trusted_path",
    "SECURITY_RULES",
    "RiskLevel",
    "SecurityRule",
    # Audit logging
    "emit_audit_event",
    "AuditEvent",
    "AuditEventType",
    "make_audit_event",
    # Relevance ranking
    "rank_skills_by_relevance",
    # Health checking
    "check_skill_health",
    "check_all_skills_health",
    "run_health_check_cli",
    "format_health_report_text",
    "format_health_report_json",
]
