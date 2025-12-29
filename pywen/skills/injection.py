from __future__ import annotations
from pathlib import Path
from .models import SkillInjections, SkillLoadOutcome, SkillMetadata, SkillInstructions, UserInput

def build_skill_injections(
    inputs: list[UserInput],
    skills: SkillLoadOutcome | None,
) -> SkillInjections:
    if not inputs or skills is None:
        return SkillInjections()

    mentioned = collect_explicit_skill_mentions(inputs, skills.skills)
    if not mentioned:
        return SkillInjections()

    result = SkillInjections(items=[], warnings=[])
    for skill in mentioned:
        try:
            contents = Path(skill.path).read_text(encoding="utf-8")
            result.items.append(
                SkillInstructions(
                    name=skill.name,
                    path=str(skill.path),
                    contents=contents,
                )
            )
        except OSError as err:
            result.warnings.append(
                f"Failed to load skill {skill.name} at {skill.path}: {err}"
            )

    return result

def collect_explicit_skill_mentions(
    inputs: list[UserInput],
    skills: list[SkillMetadata],
) -> list[SkillMetadata]:
    selected: list[SkillMetadata] = []
    seen: set[str] = set()

    for input_item in inputs:
        if (
            input_item.kind == "skill"
            and input_item.name
            and input_item.path
            and input_item.name not in seen
        ):
            for skill in skills:
                if skill.name == input_item.name and str(skill.path) == input_item.path:
                    selected.append(skill)
                    seen.add(input_item.name)
                    break

    return selected
