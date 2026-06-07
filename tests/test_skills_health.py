"""Skill health checking — acceptance tests.

Acceptance criteria:
1. check_all_skills_health outputs health status for all skills
2. YAML-malformed skill is marked FAIL with specific error reason
3. Script file referenced in SKILL.md body but missing on disk is flagged
4. Broken symbolic links in scripts/ are detected
5. All healthy -> exit code 0; any failure -> exit code 1
6. --json flag produces machine-readable JSON output
7. Pre-release version strings are accepted as valid
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from pywen.skills.health import (
    check_all_skills_health,
    check_skill_health,
    format_health_report_json,
    run_health_check_cli,
)
from pywen.skills.loader import SKILLS_FILENAME, parse_skill_file
from pywen.skills.models import SkillMetadata, SkillScope


def _write_good_skill(tmp_path: Path, name: str) -> SkillMetadata:
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent(f"""\
---
name: {name}
description: 正常的健康技能
---

# Body
""")
    p = skill_dir / SKILLS_FILENAME
    p.write_text(content, encoding="utf-8")
    return parse_skill_file(p, SkillScope.USER)


def _write_skill_with_script_ref(tmp_path: Path, name: str, script_name: str, create_script: bool = True) -> SkillMetadata:
    """Write a skill that references a script in its body."""
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    if create_script:
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        (scripts_dir / script_name).write_text("#!/bin/bash\necho hello", encoding="utf-8")
    content = textwrap.dedent(f"""\
---
name: {name}
description: 引用脚本的技能
---

# Body

Run `scripts/{script_name}` to set up the environment.
""")
    p = skill_dir / SKILLS_FILENAME
    p.write_text(content, encoding="utf-8")
    return parse_skill_file(p, SkillScope.USER)


def _write_bad_yaml_skill(tmp_path: Path, name: str) -> SkillMetadata:
    """Write a valid file, parse it, then corrupt the YAML."""
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    good_content = textwrap.dedent(f"""\
---
name: {name}
description: 即将损坏的技能
---

# Body
""")
    p = skill_dir / SKILLS_FILENAME
    p.write_text(good_content, encoding="utf-8")
    skill = parse_skill_file(p, SkillScope.USER)

    bad_content = textwrap.dedent("""\
---
name: [invalid yaml
description: broken
---
# Body
""")
    p.write_text(bad_content, encoding="utf-8")
    return skill


def test_healthy_skill_passes(tmp_path: Path) -> None:
    """Criterion 1: Healthy skill reports is_healthy=True."""
    skill = _write_good_skill(tmp_path, "healthy")
    report = check_skill_health(skill)
    assert report.is_healthy is True
    assert len(report.issues) == 0


def test_broken_yaml_fails(tmp_path: Path) -> None:
    """Criterion 2: YAML-malformed skill is marked FAIL with error details."""
    skill = _write_bad_yaml_skill(tmp_path, "broken-yaml")
    report = check_skill_health(skill)
    assert report.is_healthy is False
    assert any("SKILL.md" in issue for issue in report.issues)


def test_missing_script_ref_flagged(tmp_path: Path) -> None:
    """Criterion 3: Script referenced in body but missing on disk is flagged."""
    # Write a skill that references a script but don't create the script file
    skill = _write_skill_with_script_ref(tmp_path, "missing-script", "setup.sh", create_script=False)
    report = check_skill_health(skill)
    assert report.is_healthy is False
    assert any("setup.sh" in issue and "referenced but not found" in issue for issue in report.issues)


def test_existing_script_ref_passes(tmp_path: Path) -> None:
    """Criterion 3 (positive): Referenced script that exists on disk passes check."""
    skill = _write_skill_with_script_ref(tmp_path, "good-script", "setup.sh", create_script=True)
    report = check_skill_health(skill)
    assert report.is_healthy is True


def test_broken_symlink_detected(tmp_path: Path) -> None:
    """Criterion 4: Broken symbolic links in scripts/ are detected."""
    skill = _write_good_skill(tmp_path, "symlink-skill")
    skill_dir = skill.path.parent
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir()
    broken_link = scripts_dir / "broken.sh"
    try:
        broken_link.symlink_to("/nonexistent/path/broken.sh")
    except (OSError, NotImplementedError):
        pytest.skip("symlink not supported on this platform")

    report = check_skill_health(skill)
    assert report.is_healthy is False
    assert any("broken symbolic link" in issue for issue in report.issues)


def test_exit_code_all_healthy(tmp_path: Path) -> None:
    """Criterion 5: All healthy -> exit code 0."""
    skills = [_write_good_skill(tmp_path, f"skill-{i}") for i in range(3)]
    exit_code = run_health_check_cli(skills, use_json=False)
    assert exit_code == 0


def test_exit_code_with_failures(tmp_path: Path) -> None:
    """Criterion 5: Any failure -> exit code 1."""
    good = _write_good_skill(tmp_path, "good-skill")
    bad = _write_bad_yaml_skill(tmp_path, "bad-skill")
    exit_code = run_health_check_cli([good, bad], use_json=False)
    assert exit_code == 1


def test_json_output_format(tmp_path: Path) -> None:
    """Criterion 6: JSON output is valid and machine-readable."""
    skill = _write_good_skill(tmp_path, "json-health")
    reports = check_all_skills_health([skill])
    json_output = format_health_report_json(reports)
    data = json.loads(json_output)
    assert isinstance(data, list)
    assert len(data) == 1
    assert "skill_name" in data[0]
    assert "is_healthy" in data[0]
    assert "issues" in data[0]


def test_prerelease_version_is_valid(tmp_path: Path) -> None:
    """Criterion 7: Pre-release version strings are accepted as valid."""
    skill_dir = tmp_path / "prerelease-health"
    skill_dir.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
---
name: prerelease-health
description: 预发布版本技能
version: "1.0.0-beta.1"
---

# Body
""")
    p = skill_dir / SKILLS_FILENAME
    p.write_text(content, encoding="utf-8")
    skill = parse_skill_file(p, SkillScope.USER)
    assert skill.version == "1.0.0-beta.1"
    report = check_skill_health(skill)
    # Version should NOT appear in issues
    assert report.is_healthy is True
    assert not any("version" in issue.lower() for issue in report.issues)
