from __future__ import annotations
import os
import re
import time
import yaml
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional
from .models import (
    SkillDependency,
    SkillError,
    SkillLoadOutcome,
    SkillMetadata,
    SkillRoot,
    SkillScope,
)

SKILLS_FILENAME = "SKILL.md"
SKILLS_DIR_NAME = "skills"
REPO_ROOT_CONFIG_DIR_NAME = ".pywen"
ADMIN_SKILLS_ROOT = "/etc/pywen/skills"
MAX_NAME_LEN = 64
MAX_DESCRIPTION_LEN = 1024
MAX_SHORT_DESCRIPTION_LEN = MAX_DESCRIPTION_LEN

# Semantic version pattern (SemVer 2.0.0):
#   core: 1.2.3
#   pre-release: 1.2.3-beta.1
#   build metadata: 1.2.3+build.123
_SEMVER_PATTERN = re.compile(
    r'^\d+\.\d+\.\d+'
    r'(?:-[0-9A-Za-z\-.]+)?'
    r'(?:\+[0-9A-Za-z\-.]+)?$'
)


class SkillParseError(Exception):
    pass


def load_skills(pywen_home: Path, cwd: Path) -> SkillLoadOutcome:
    return load_skills_from_roots(skill_roots_for_cwd(pywen_home, cwd))


def load_skills_from_roots(roots: Iterable[SkillRoot]) -> SkillLoadOutcome:
    """Load and deduplicate skills from all roots, then check dependencies and record timing."""
    from .dependency_resolver import check_dependencies

    outcome = SkillLoadOutcome()
    start = time.monotonic()

    for root in roots:
        discover_skills_under_root(root.path, root.scope, outcome)

    seen: set[str] = set()
    deduped: list[SkillMetadata] = []
    for skill in outcome.skills:
        if skill.name not in seen:
            seen.add(skill.name)
            deduped.append(skill)

    deduped.sort(key=lambda skill: (skill.name, str(skill.path)))
    outcome.skills = deduped

    # Dependency validation
    dep_issues = check_dependencies(deduped)
    for issue in dep_issues:
        outcome.errors.append(
            SkillError(path=Path("<dependency>"), message=issue)
        )

    outcome.load_duration_ms = (time.monotonic() - start) * 1000
    return outcome


def user_skills_root(pywen_home: Path) -> SkillRoot:
    return SkillRoot(path=pywen_home / SKILLS_DIR_NAME, scope=SkillScope.USER)


def system_skills_root(pywen_home: Path) -> SkillRoot:
    return SkillRoot(path=pywen_home / SKILLS_DIR_NAME / ".system", scope=SkillScope.SYSTEM)


def admin_skills_root() -> SkillRoot:
    return SkillRoot(path=Path(ADMIN_SKILLS_ROOT), scope=SkillScope.ADMIN)


def repo_skills_root(cwd: Path) -> Optional[SkillRoot]:
    base = (cwd if cwd.is_dir() else cwd.parent).resolve()

    repo_root = find_git_root(base)
    if repo_root is not None:
        for directory in [base, *base.parents]:
            skills_root = directory / REPO_ROOT_CONFIG_DIR_NAME / SKILLS_DIR_NAME
            if skills_root.is_dir():
                return SkillRoot(path=skills_root, scope=SkillScope.REPO)
            if directory == repo_root:
                break
        return None

    skills_root = base / REPO_ROOT_CONFIG_DIR_NAME / SKILLS_DIR_NAME
    if skills_root.is_dir():
        return SkillRoot(path=skills_root, scope=SkillScope.REPO)
    return None


def skill_roots_for_cwd(pywen_home: Path, cwd: Path) -> list[SkillRoot]:
    roots: list[SkillRoot] = []

    repo_root = repo_skills_root(cwd)
    if repo_root is not None:
        roots.append(repo_root)

    roots.append(user_skills_root(pywen_home))
    roots.append(system_skills_root(pywen_home))
    if os.name == "posix":
        roots.append(admin_skills_root())

    return roots


def discover_skills_under_root(root: Path, scope: SkillScope, outcome: SkillLoadOutcome) -> None:
    try:
        root = root.resolve()
    except OSError:
        return

    if not root.is_dir():
        return

    queue = [root]
    while queue:
        directory = queue.pop(0)
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    name = entry.name
                    if name.startswith("."):
                        continue
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir():
                            queue.append(Path(entry.path))
                            continue
                        if entry.is_file() and name == SKILLS_FILENAME:
                            try:
                                skill = parse_skill_file(Path(entry.path), scope)
                                outcome.skills.append(skill)
                            except SkillParseError as err:
                                if scope != SkillScope.SYSTEM:
                                    outcome.errors.append(
                                        SkillError(path=Path(entry.path), message=str(err))
                                    )
                    except OSError:
                        continue
        except OSError:
            continue


def parse_skill_file(path: Path, scope: SkillScope) -> SkillMetadata:
    """Parse a SKILL.md file with security scanning and audit logging."""
    from .security import scan_skill_content, RiskLevel, is_trusted_path
    from .audit import emit, AuditEvent, AuditEventType

    parse_start = time.monotonic()

    try:
        contents = path.read_text(encoding="utf-8")
    except OSError as err:
        _emit_load_failed(path, scope, str(err))
        raise SkillParseError(f"failed to read file: {err}") from err

    frontmatter = extract_frontmatter(contents)
    if frontmatter is None:
        msg = "missing YAML frontmatter delimited by ---"
        _emit_load_failed(path, scope, msg)
        raise SkillParseError(msg)

    try:
        parsed = yaml.safe_load(frontmatter) or {}
    except yaml.YAMLError as err:
        msg = f"invalid YAML: {err}"
        _emit_load_failed(path, scope, msg)
        raise SkillParseError(msg) from err

    name = sanitize_single_line(str(parsed.get("name", "")))
    description = sanitize_single_line(str(parsed.get("description", "")))

    metadata = parsed.get("metadata") or {}
    short_description = metadata.get("short-description")
    if short_description is not None:
        short_description = sanitize_single_line(str(short_description))
        if not short_description:
            short_description = None

    # Version field (optional, must be semver)
    version = parsed.get("version")
    if version is not None:
        version = str(version).strip()
        if not _SEMVER_PATTERN.match(version):
            version = None  # Silently ignore invalid formats

    # Dependency declarations (optional)
    requires_raw = parsed.get("requires", [])
    requires: list[SkillDependency] = []
    if isinstance(requires_raw, list):
        for dep in requires_raw:
            if isinstance(dep, dict) and dep.get("name"):
                requires.append(SkillDependency(
                    name=str(dep["name"]).strip(),
                    min_version=dep.get("min_version"),
                    max_version=dep.get("max_version"),
                ))

    validate_field(name, MAX_NAME_LEN, "name")
    validate_field(description, MAX_DESCRIPTION_LEN, "description")
    if short_description is not None:
        validate_field(
            short_description, MAX_SHORT_DESCRIPTION_LEN, "metadata.short-description"
        )

    # Security scanning (skip for trusted paths)
    if not is_trusted_path(path):
        # Scan the description field
        desc_findings = scan_skill_content(description)
        for rule, ctx in desc_findings:
            if rule.risk_level == RiskLevel.HIGH:
                msg = (
                    f"Security violation in 'description': {rule.description} "
                    f"(context: '...{ctx}...')"
                )
                _emit_security_violation(path, scope, rule.name, ctx)
                _emit_load_failed(path, scope, msg)
                raise SkillParseError(msg)

        # Scan the frontmatter text (catches injection in custom metadata fields)
        fm_findings = scan_skill_content(frontmatter)
        for rule, ctx in fm_findings:
            if rule.risk_level == RiskLevel.HIGH:
                msg = (
                    f"Security violation in frontmatter: {rule.description} "
                    f"(context: '...{ctx}...')"
                )
                _emit_security_violation(path, scope, rule.name, ctx)
                _emit_load_failed(path, scope, msg)
                raise SkillParseError(msg)

        # Scan the full SKILL.md content
        content_findings = scan_skill_content(contents)
        for rule, ctx in content_findings:
            if rule.risk_level == RiskLevel.HIGH:
                msg = (
                    f"Security violation in skill body: {rule.description} "
                    f"(context: '...{ctx}...')"
                )
                _emit_security_violation(path, scope, rule.name, ctx)
                _emit_load_failed(path, scope, msg)
                raise SkillParseError(msg)
            elif rule.risk_level == RiskLevel.MEDIUM:
                # Medium risk: warn but allow loading
                print(
                    f"⚠️  Security Warning: Skill at '{path}' contains potentially "
                    f"sensitive content.\n"
                    f"    Rule: {rule.name}\n"
                    f"    Context: '...{ctx}...'\n"
                    f"    The skill has been loaded, but please review its content before use."
                )

    try:
        resolved_path = path.resolve()
    except OSError:
        resolved_path = path

    result = SkillMetadata(
        name=name,
        description=description,
        short_description=short_description,
        path=resolved_path,
        scope=scope,
        version=version,
        requires=tuple(requires),
    )

    # Audit log
    duration_ms = (time.monotonic() - parse_start) * 1000
    emit(AuditEvent(
        event=AuditEventType.SKILL_LOADED,
        timestamp=datetime.now().isoformat(),
        skill_name=result.name,
        skill_path=str(result.path),
        scope=scope.value,
        duration_ms=round(duration_ms, 2),
    ))

    return result


def _emit_load_failed(path: Path, scope: SkillScope, error: str) -> None:
    """Emit a skill_load_failed audit event."""
    try:
        from .audit import emit, AuditEvent, AuditEventType
        emit(AuditEvent(
            event=AuditEventType.SKILL_LOAD_FAILED,
            timestamp=datetime.now().isoformat(),
            skill_path=str(path),
            scope=scope.value,
            error=error,
        ))
    except Exception:
        pass  # Audit failure should not break the main flow


def _emit_security_violation(path: Path, scope: SkillScope, rule_name: str, context: str) -> None:
    """Emit a security_violation audit event."""
    try:
        from .audit import emit, AuditEvent, AuditEventType
        emit(AuditEvent(
            event=AuditEventType.SECURITY_VIOLATION,
            timestamp=datetime.now().isoformat(),
            skill_path=str(path),
            scope=scope.value,
            details={"rule": rule_name, "context": f"...{context}..."},
        ))
    except Exception:
        pass  # Audit failure should not break the main flow


def sanitize_single_line(raw: str) -> str:
    return " ".join(raw.split())


def validate_field(value: str, max_len: int, field_name: str) -> None:
    if not value:
        raise SkillParseError(f"missing field `{field_name}`")
    if len(value) > max_len:
        raise SkillParseError(
            f"invalid {field_name}: exceeds maximum length of {max_len} characters"
        )


def extract_frontmatter(contents: str) -> Optional[str]:
    lines = contents.splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    frontmatter_lines: list[str] = []
    found_closing = False
    for line in lines[1:]:
        if line.strip() == "---":
            found_closing = True
            break
        frontmatter_lines.append(line)

    if not frontmatter_lines or not found_closing:
        return None

    return "\n".join(frontmatter_lines)


def find_git_root(start: Path) -> Optional[Path]:
    for directory in [start, *start.parents]:
        git_marker = directory / ".git"
        if git_marker.is_dir() or git_marker.is_file():
            return directory
    return None
