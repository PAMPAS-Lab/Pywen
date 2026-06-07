"""Version field support — acceptance tests.

Acceptance criteria:
1. Valid version field (e.g. "1.0.0") is parsed correctly
2. Missing version field results in version == None
3. Version string is shown in render output
4. Invalid version formats result in version == None without exceptions
5. Pre-release versions (e.g. "1.0.0-beta") are accepted
6. Build metadata versions (e.g. "1.0.0+build.123") are accepted
7. Pre-release with build metadata (e.g. "2.0.0-rc.1+build.42") are accepted
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from pywen.skills.loader import SKILLS_FILENAME, parse_skill_file
from pywen.skills.models import SkillScope
from pywen.skills.render import render_skills_section


def _write_skill(tmp_path: Path, name: str, description: str, version: str | None = None) -> Path:
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    version_line = f'version: "{version}"\n' if version is not None else ""
    content = textwrap.dedent(f"""\
---
name: {name}
description: {description}
{version_line}---

# Body
""")
    p = skill_dir / SKILLS_FILENAME
    p.write_text(content, encoding="utf-8")
    return p


def test_version_field_parsed(tmp_path: Path) -> None:
    """Criterion 1: Valid version "1.0.0" is parsed correctly."""
    path = _write_skill(tmp_path, "my-skill", "示例技能", version="1.0.0")
    skill = parse_skill_file(path, SkillScope.USER)
    assert skill.version == "1.0.0"


def test_version_field_missing(tmp_path: Path) -> None:
    """Criterion 2: Missing version field results in version == None."""
    path = _write_skill(tmp_path, "no-version", "无版本技能", version=None)
    skill = parse_skill_file(path, SkillScope.USER)
    assert skill.version is None


def test_version_shown_in_render(tmp_path: Path) -> None:
    """Criterion 3: Version string is shown in render output."""
    path = _write_skill(tmp_path, "versioned", "带版本的技能", version="2.0.0")
    skill = parse_skill_file(path, SkillScope.USER)
    rendered = render_skills_section([skill])
    assert rendered is not None
    assert "v2.0.0" in rendered


def test_invalid_version_format_no_exception(tmp_path: Path) -> None:
    """Criterion 4: Invalid version format does not raise; version is set to None."""
    path = _write_skill(tmp_path, "bad-version", "非法版本技能", version="v1.0.0-beta")
    skill = parse_skill_file(path, SkillScope.USER)
    assert skill.version is None
    assert skill.name == "bad-version"
    assert skill.description == "非法版本技能"


def test_prerelease_version_accepted(tmp_path: Path) -> None:
    """Criterion 5: Pre-release versions like "1.0.0-beta" are accepted."""
    path = _write_skill(tmp_path, "prerelease", "预发布技能", version="1.0.0-beta")
    skill = parse_skill_file(path, SkillScope.USER)
    assert skill.version == "1.0.0-beta"


def test_build_metadata_version_accepted(tmp_path: Path) -> None:
    """Criterion 6: Build metadata versions like "1.0.0+build.123" are accepted."""
    path = _write_skill(tmp_path, "build-meta", "构建元数据版本技能", version="1.0.0+build.123")
    skill = parse_skill_file(path, SkillScope.USER)
    assert skill.version == "1.0.0+build.123"


def test_prerelease_with_build_metadata(tmp_path: Path) -> None:
    """Criterion 7: Full SemVer "2.0.0-rc.1+build.42" is accepted."""
    path = _write_skill(tmp_path, "full-semver", "完整语义版本技能", version="2.0.0-rc.1+build.42")
    skill = parse_skill_file(path, SkillScope.USER)
    assert skill.version == "2.0.0-rc.1+build.42"
