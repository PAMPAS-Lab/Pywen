"""Skill dependency declaration and resolution.

Skills can declare dependencies in their SKILL.md frontmatter::

    requires:
      - name: docker
        min_version: "1.0.0"

During loading, the framework validates that all declared dependencies
are present and satisfy the requested version ranges.  Circular
dependencies are also detected.

Version comparison prefers ``packaging.version.Version`` when available;
otherwise it falls back to tuple-based integer comparison.
"""
from __future__ import annotations

from typing import List

from .models import SkillDependency, SkillMetadata


class DependencyError(Exception):
    pass


def _compare_versions(v1: str, v2: str) -> int:
    """Compare two version strings.  Returns -1 / 0 / 1.

    Per SemVer 2.0.0, build metadata (``+...``) is ignored for comparison,
    and pre-release versions have lower precedence than the associated
    normal version.
    """
    # Strip build metadata before comparison
    v1_core = v1.split("+")[0]
    v2_core = v2.split("+")[0]

    try:
        from packaging.version import Version
        pv1, pv2 = Version(v1_core), Version(v2_core)
        if pv1 < pv2:
            return -1
        elif pv1 > pv2:
            return 1
        return 0
    except ImportError:
        # Fallback: compare dot-separated integer tuples from the core version
        try:
            core1 = v1_core.split("-")[0]
            core2 = v2_core.split("-")[0]
            t1 = tuple(int(x) for x in core1.split("."))
            t2 = tuple(int(x) for x in core2.split("."))
            if t1 < t2:
                return -1
            elif t1 > t2:
                return 1
            # Same core version — compare pre-release identifiers
            pre1 = v1_core.split("-")[1:] if "-" in v1_core else []
            pre2 = v2_core.split("-")[1:] if "-" in v2_core else []
            # Pre-release < release (per SemVer §11.4)
            if pre1 and not pre2:
                return -1
            if not pre1 and pre2:
                return 1
            if pre1 and pre2:
                # Compare pre-release identifiers field-by-field
                pre1_str = "-".join(pre1)
                pre2_str = "-".join(pre2)
                pre1_parts = pre1_str.split(".")
                pre2_parts = pre2_str.split(".")
                for p1, p2 in zip(pre1_parts, pre2_parts, strict=False):
                    # Numeric identifiers compare numerically
                    if p1.isdigit() and p2.isdigit():
                        n1, n2 = int(p1), int(p2)
                        if n1 < n2:
                            return -1
                        elif n1 > n2:
                            return 1
                    else:
                        # String identifiers compare lexicographically
                        if p1 < p2:
                            return -1
                        elif p1 > p2:
                            return 1
                # Shorter pre-release has lower precedence
                if len(pre1_parts) < len(pre2_parts):
                    return -1
                elif len(pre1_parts) > len(pre2_parts):
                    return 1
            return 0
        except ValueError:
            return 0
    except Exception:
        return 0


def _detect_cycles(skill_index: dict[str, SkillMetadata]) -> List[str]:
    """Detect circular dependencies using depth-first search."""
    issues: List[str] = []
    visited: set[str] = set()
    in_stack: set[str] = set()

    def dfs(name: str, path: list[str]) -> None:
        if name not in skill_index:
            return  # Missing deps are handled by the main check
        if name in in_stack:
            cycle_start = path.index(name)
            cycle = " → ".join(path[cycle_start:] + [name])
            issues.append(f"Circular dependency detected: {cycle}")
            return
        if name in visited:
            return

        visited.add(name)
        in_stack.add(name)
        path.append(name)

        skill = skill_index[name]
        for dep in skill.requires:
            if isinstance(dep, SkillDependency):
                dfs(dep.name, path)

        path.pop()
        in_stack.discard(name)

    for skill_name in skill_index:
        if skill_name not in visited:
            dfs(skill_name, [])

    return issues


def check_dependencies(skills: List[SkillMetadata]) -> List[str]:
    """Validate all skill dependencies.

    Returns a list of unmet-dependency descriptions (empty means all OK).
    Checks: missing dependencies, version range violations, circular deps.
    """
    skill_index: dict[str, SkillMetadata] = {s.name: s for s in skills}
    issues: List[str] = []

    # 1. Missing dependencies & version checks
    for skill in skills:
        for dep in skill.requires:
            if not isinstance(dep, SkillDependency):
                continue

            if dep.name not in skill_index:
                issues.append(
                    f"Skill '{skill.name}' requires '{dep.name}' which is not installed."
                )
                continue

            dep_skill = skill_index[dep.name]
            if (dep.min_version or dep.max_version) and not dep_skill.version:
                constraints = []
                if dep.min_version:
                    constraints.append(f">= {dep.min_version}")
                if dep.max_version:
                    constraints.append(f"<= {dep.max_version}")
                issues.append(
                    f"Skill '{skill.name}' requires '{dep.name}' "
                    f"{' and '.join(constraints)}, but '{dep.name}' does not declare a version."
                )
                continue

            # Minimum version
            if dep.min_version and dep_skill.version:
                try:
                    if _compare_versions(dep_skill.version, dep.min_version) < 0:
                        issues.append(
                            f"Skill '{skill.name}' requires '{dep.name}' >= "
                            f"{dep.min_version}, but found {dep_skill.version}."
                        )
                except Exception:
                    pass

            # Maximum version
            if dep.max_version and dep_skill.version:
                try:
                    if _compare_versions(dep_skill.version, dep.max_version) > 0:
                        issues.append(
                            f"Skill '{skill.name}' requires '{dep.name}' <= "
                            f"{dep.max_version}, but found {dep_skill.version}."
                        )
                except Exception:
                    pass

    # 2. Circular dependency detection
    cycle_issues = _detect_cycles(skill_index)
    issues.extend(cycle_issues)

    return issues
