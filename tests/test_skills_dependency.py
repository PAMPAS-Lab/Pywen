from __future__ import annotations

from pathlib import Path

from pywen.skills.dependency_resolver import check_dependencies
from pywen.skills.models import SkillDependency, SkillMetadata, SkillScope


def _skill(
    name: str,
    version: str | None = None,
    requires: tuple[SkillDependency, ...] = (),
) -> SkillMetadata:
    return SkillMetadata(
        name=name,
        description=f"{name} skill",
        short_description=None,
        path=Path(f"/fake/{name}/SKILL.md"),
        scope=SkillScope.USER,
        version=version,
        requires=requires,
    )


def test_version_constraint_requires_dependency_version() -> None:
    base = _skill("base")
    consumer = _skill(
        "consumer",
        requires=(SkillDependency(name="base", min_version="1.0.0"),),
    )

    issues = check_dependencies([base, consumer])

    assert issues == [
        "Skill 'consumer' requires 'base' >= 1.0.0, but 'base' does not declare a version."
    ]


def test_version_constraint_passes_when_dependency_version_satisfies() -> None:
    base = _skill("base", version="1.2.0")
    consumer = _skill(
        "consumer",
        requires=(SkillDependency(name="base", min_version="1.0.0"),),
    )

    assert check_dependencies([base, consumer]) == []
