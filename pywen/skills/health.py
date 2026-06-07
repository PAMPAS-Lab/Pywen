"""Skill health checking.

Provides integrity checks for installed skills:

1. SKILL.md parseability (valid YAML)
2. Referenced scripts exist under ``scripts/`` (parsed from SKILL.md body)
3. Broken symbolic links in ``scripts/`` directory
4. Version format validation (when present)

CLI usage::

    pywen skill health-check
    pywen skill health-check --json

Exit codes: 0 = all healthy, 1 = failures found (CI-friendly).
"""
from __future__ import annotations

import json
import re
from typing import List

from .loader import _SEMVER_PATTERN, SkillParseError, parse_skill_file
from .models import SkillHealthReport, SkillMetadata

# Pattern to extract script references from SKILL.md body text.
# Matches paths like "scripts/setup.sh", "scripts/run.py", etc.
_SCRIPT_REF_PATTERN = re.compile(r'\bscripts/([^\s\)\]"\'`]+)')


def _extract_script_refs(skill: SkillMetadata) -> set[str]:
    """Extract script file references from the SKILL.md body.

    Reads the raw file and looks for paths matching ``scripts/...``.
    Returns a set of referenced filenames (without the ``scripts/`` prefix).
    """
    try:
        contents = skill.path.read_text(encoding="utf-8")
    except OSError:
        return set()

    refs: set[str] = set()
    for match in _SCRIPT_REF_PATTERN.finditer(contents):
        refs.add(match.group(1))
    return refs


def check_skill_health(skill: SkillMetadata) -> SkillHealthReport:
    """Run integrity checks on a single skill.

    Checks:
    1. SKILL.md can be re-parsed without errors
    2. Script files referenced in SKILL.md body exist on disk
    3. Broken symbolic links in the scripts/ directory
    4. Version field (if present) is valid semver
    """
    issues: List[str] = []
    skill_dir = skill.path.parent

    # Check 1: SKILL.md re-parse
    try:
        parse_skill_file(skill.path, skill.scope)
    except SkillParseError as e:
        issues.append(f"SKILL.md: {e}")
    except Exception as e:
        issues.append(f"SKILL.md: unexpected error: {e}")

    # Check 2: script references from SKILL.md body
    script_refs = _extract_script_refs(skill)
    if script_refs:
        for ref_name in sorted(script_refs):
            script_path = skill_dir / "scripts" / ref_name
            if not script_path.exists():
                issues.append(f"scripts/{ref_name}: referenced but not found")

    # Check 3: broken symbolic links in scripts/ directory
    scripts_dir = skill_dir / "scripts"
    if scripts_dir.is_dir():
        try:
            for entry in scripts_dir.iterdir():
                if entry.is_symlink() and not entry.exists():
                    issues.append(f"scripts/{entry.name}: broken symbolic link")
        except OSError as e:
            issues.append(f"scripts/: cannot read directory: {e}")

    # Check 4: version format
    if skill.version and not _SEMVER_PATTERN.match(skill.version):
        issues.append(f"version: invalid semver format '{skill.version}'")

    return SkillHealthReport(
        skill_name=skill.name,
        skill_path=skill.path,
        scope=skill.scope,
        is_healthy=len(issues) == 0,
        issues=issues,
    )


def check_all_skills_health(skills: List[SkillMetadata]) -> List[SkillHealthReport]:
    """Run health checks on all skills."""
    return [check_skill_health(skill) for skill in skills]


def format_health_report_text(reports: List[SkillHealthReport]) -> str:
    """Format health reports as human-readable text."""
    lines: List[str] = []
    total = len(reports)
    lines.append(f"Checking {total} skills...\n")

    ok_count = 0
    fail_count = 0
    for report in reports:
        scope_str = report.scope.value if hasattr(report.scope, 'value') else str(report.scope)
        if report.is_healthy:
            lines.append(f"✓ {report.skill_name} ({scope_str}): OK")
            ok_count += 1
        else:
            lines.append(f"✗ {report.skill_name} ({scope_str}): FAIL")
            for issue in report.issues:
                lines.append(f"  - {issue}")
            fail_count += 1

    lines.append(f"\nSummary: {ok_count} OK, {fail_count} FAILED")
    return "\n".join(lines)


def format_health_report_json(reports: List[SkillHealthReport]) -> str:
    """Format health reports as machine-readable JSON."""
    data = []
    for r in reports:
        data.append({
            "skill_name": r.skill_name,
            "skill_path": str(r.skill_path),
            "scope": r.scope.value if hasattr(r.scope, 'value') else str(r.scope),
            "is_healthy": r.is_healthy,
            "issues": r.issues,
        })
    return json.dumps(data, ensure_ascii=False, indent=2)


def run_health_check_cli(
    skills: List[SkillMetadata],
    use_json: bool = False,
) -> int:
    """Run health checks and print results. Returns exit code (0 = all OK, 1 = failures)."""
    reports = check_all_skills_health(skills)

    if use_json:
        print(format_health_report_json(reports))
    else:
        print(format_health_report_text(reports))

    has_failures = any(not r.is_healthy for r in reports)
    return 1 if has_failures else 0
