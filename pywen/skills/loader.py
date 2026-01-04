from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
import os
import yaml
from .models import SkillError, SkillLoadOutcome, SkillMetadata, SkillRoot, SkillScope

SKILLS_FILENAME = "SKILL.md"
SKILLS_DIR_NAME = "skills"
REPO_ROOT_CONFIG_DIR_NAME = ".pywen"
ADMIN_SKILLS_ROOT = "/etc/pywen/skills"
MAX_NAME_LEN = 64
MAX_DESCRIPTION_LEN = 1024
MAX_SHORT_DESCRIPTION_LEN = MAX_DESCRIPTION_LEN

class SkillParseError(Exception):
    pass

@dataclass
class SkillFrontmatter:
    name: str
    description: str
    short_description: Optional[str]

def load_skills(pywen_home: Path, cwd: Path) -> SkillLoadOutcome:
    return load_skills_from_roots(skill_roots_for_cwd(pywen_home, cwd))

def load_skills_from_roots(roots: Iterable[SkillRoot]) -> SkillLoadOutcome:
    outcome = SkillLoadOutcome()
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
    return outcome

def user_skills_root(pywen_home: Path) -> SkillRoot:
    return SkillRoot(path=pywen_home / SKILLS_DIR_NAME, scope=SkillScope.USER)

def system_skills_root(pywen_home: Path) -> SkillRoot:
    return SkillRoot(path=pywen_home / SKILLS_DIR_NAME / ".system", scope=SkillScope.SYSTEM)

def admin_skills_root() -> SkillRoot:
    return SkillRoot(path=Path(ADMIN_SKILLS_ROOT), scope=SkillScope.ADMIN)

def repo_skills_root(cwd: Path) -> Optional[SkillRoot]:
    base = cwd if cwd.is_dir() else cwd.parent
    if base is None:
        return None
    base = base.resolve()

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
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError as err:
        raise SkillParseError(f"failed to read file: {err}") from err

    frontmatter = extract_frontmatter(contents)
    if frontmatter is None:
        raise SkillParseError("missing YAML frontmatter delimited by ---")

    try:
        parsed = yaml.safe_load(frontmatter) or {}
    except yaml.YAMLError as err:
        raise SkillParseError(f"invalid YAML: {err}") from err

    name = sanitize_single_line(str(parsed.get("name", "")))
    description = sanitize_single_line(str(parsed.get("description", "")))

    metadata = parsed.get("metadata") or {}
    short_description = metadata.get("short-description")
    if short_description is not None:
        short_description = sanitize_single_line(str(short_description))
        if not short_description:
            short_description = None

    validate_field(name, MAX_NAME_LEN, "name")
    validate_field(description, MAX_DESCRIPTION_LEN, "description")
    if short_description is not None:
        validate_field(
            short_description, MAX_SHORT_DESCRIPTION_LEN, "metadata.short-description"
        )

    try:
        resolved_path = path.resolve()
    except OSError:
        resolved_path = path

    return SkillMetadata(
        name=name,
        description=description,
        short_description=short_description,
        path=resolved_path,
        scope=scope,
    )

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
