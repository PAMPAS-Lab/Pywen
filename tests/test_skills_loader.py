from __future__ import annotations
from pathlib import Path
import sys
import textwrap
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pywen.skills.loader import (
    MAX_DESCRIPTION_LEN,
    SKILLS_FILENAME,
    SkillParseError,
    load_skills_from_roots,
    parse_skill_file,
    repo_skills_root,
)
from pywen.skills.models import SkillRoot, SkillScope

def write_skill(root: Path, name: str, description: str, short_desc: str | None = None) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    short_block = ""
    if short_desc is not None:
        short_block = f"metadata:\n  short-description: {short_desc}\n"
    content = textwrap.dedent(f"""\
---
name: {name}
description: {description.replace("\n", "\n  ")}
{short_block}
---

# Body
"""
    )
    path = skill_dir / SKILLS_FILENAME
    path.write_text(content, encoding="utf-8")
    return path

def test_parse_valid_skill() -> None:
    root = Path(__file__).parent / "_tmp_valid"
    if root.exists():
        for item in root.rglob("*"):
            if item.is_file():
                item.unlink()
        for item in sorted(root.rglob("*"), reverse=True):
            if item.is_dir():
                item.rmdir()
    root.mkdir(parents=True, exist_ok=True)

    path = write_skill(root, "demo-skill", "does things\ncarefully")
    skill = parse_skill_file(path, SkillScope.USER)
    assert skill.name == "demo-skill"
    assert skill.description == "does things carefully"
    assert skill.short_description is None

def test_short_description_metadata() -> None:
    root = Path(__file__).parent / "_tmp_short"
    if root.exists():
        for item in root.rglob("*"):
            if item.is_file():
                item.unlink()
        for item in sorted(root.rglob("*"), reverse=True):
            if item.is_dir():
                item.rmdir()
    root.mkdir(parents=True, exist_ok=True)

    path = write_skill(root, "demo-skill", "long description", short_desc="short summary")
    skill = parse_skill_file(path, SkillScope.USER)
    assert skill.short_description == "short summary"

def test_enforces_description_length() -> None:
    root = Path(__file__).parent / "_tmp_len"
    if root.exists():
        for item in root.rglob("*"):
            if item.is_file():
                item.unlink()
        for item in sorted(root.rglob("*"), reverse=True):
            if item.is_dir():
                item.rmdir()
    root.mkdir(parents=True, exist_ok=True)

    too_long = "x" * (MAX_DESCRIPTION_LEN + 1)
    path = write_skill(root, "too-long", too_long)
    with pytest.raises(SkillParseError):
        parse_skill_file(path, SkillScope.USER)

def test_dedup_prefers_first_root() -> None:
    base = Path(__file__).parent / "_tmp_dedupe"
    if base.exists():
        for item in base.rglob("*"):
            if item.is_file():
                item.unlink()
        for item in sorted(base.rglob("*"), reverse=True):
            if item.is_dir():
                item.rmdir()
    base.mkdir(parents=True, exist_ok=True)

    repo_root = base / "repo"
    user_root = base / "user"
    write_skill(repo_root, "dupe-skill", "from repo")
    write_skill(user_root, "dupe-skill", "from user")

    outcome = load_skills_from_roots(
        [
            SkillRoot(path=repo_root, scope=SkillScope.REPO),
            SkillRoot(path=user_root, scope=SkillScope.USER),
        ]
    )
    assert len(outcome.skills) == 1
    assert outcome.skills[0].scope == SkillScope.REPO

def test_repo_skills_root_nearest() -> None:
    base = Path(__file__).parent / "_tmp_repo"
    if base.exists():
        for item in base.rglob("*"):
            if item.is_file():
                item.unlink()
        for item in sorted(base.rglob("*"), reverse=True):
            if item.is_dir():
                item.rmdir()
    base.mkdir(parents=True, exist_ok=True)

    repo_root = base / "repo"
    (repo_root / ".git").mkdir(parents=True, exist_ok=True)

    nested = repo_root / "nested" / "inner"
    skills_root = repo_root / "nested" / ".pywen" / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)

    found = repo_skills_root(nested)
    assert found is not None
    assert found.path == skills_root
    assert found.scope == SkillScope.REPO

def test_repo_skills_root_no_escape() -> None:
    base = Path(__file__).parent / "_tmp_repo_escape"
    if base.exists():
        for item in base.rglob("*"):
            if item.is_file():
                item.unlink()
        for item in sorted(base.rglob("*"), reverse=True):
            if item.is_dir():
                item.rmdir()
    base.mkdir(parents=True, exist_ok=True)

    outer = base / "outer"
    repo_root = outer / "repo"
    (repo_root / ".git").mkdir(parents=True, exist_ok=True)
    (outer / ".pywen" / "skills").mkdir(parents=True, exist_ok=True)

    found = repo_skills_root(repo_root)
    assert found is None
