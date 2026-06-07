"""Render skills metadata for prompt context.

When version is present on a skill, it is shown alongside the name.
When a query is provided and the skill count exceeds top_k, only the
most relevant skills are included in the output.
"""
from __future__ import annotations

from typing import List, Optional

from .models import SkillMetadata


def render_skills_section(
    skills: List[SkillMetadata],
    query: Optional[str] = None,
    top_k: int = 10,
) -> Optional[str]:
    if not skills:
        return None

    # Apply relevance-based filtering when query is provided
    display_skills = skills
    if query and len(skills) > top_k:
        from .ranker import rank_skills_by_relevance
        display_skills = rank_skills_by_relevance(skills, query, top_k)

    lines: list[str] = []
    lines.append("## Skills")
    lines.append(
        "These skills are discovered at startup from multiple local sources. Each entry includes a name, description, and file path so you can open the source for full instructions."
    )

    for skill in display_skills:
        path_str = skill.path.as_posix()
        version_str = f" v{skill.version}" if skill.version else ""
        lines.append(f"- {skill.name}{version_str}: {skill.description} (file: {path_str})")

    lines.append(
        """- Discovery: Available skills are listed in project docs and may also appear in a runtime "## Skills" section (name + description + file path). These are the sources of truth; skill bodies live on disk at the listed paths.
- Trigger rules: If the user names a skill (with `$SkillName` or plain text) OR the task clearly matches a skill's description, you must use that skill for that turn. Multiple mentions mean use them all. Do not carry skills across turns unless re-mentioned.
- Missing/blocked: If a named skill isn't in the list or the path can't be read, say so briefly and continue with the best fallback.
- How to use a skill (progressive disclosure):
  1) After deciding to use a skill, open its `SKILL.md`. Read only enough to follow the workflow.
  2) If `SKILL.md` points to extra folders such as `references/`, load only the specific files needed for the request; don't bulk-load everything.
  3) If `scripts/` exist, prefer running or patching them instead of retyping large code blocks.
  4) If `assets/` or templates exist, reuse them instead of recreating from scratch.
- Description as trigger: The YAML `description` in `SKILL.md` is the primary trigger signal; rely on it to decide applicability. If unsure, ask a brief clarification before proceeding.
- Coordination and sequencing:
  - If multiple skills apply, choose the minimal set that covers the request and state the order you'll use them.
  - Announce which skill(s) you're using and why (one short line). If you skip an obvious skill, say why.
- Context hygiene:
  - Keep context small: summarize long sections instead of pasting them; only load extra files when needed.
  - Avoid deeply nested references; prefer one-hop files explicitly linked from `SKILL.md`.
  - When variants exist (frameworks, providers, domains), pick only the relevant reference file(s) and note that choice.
- Safety and fallback: If a skill can't be applied cleanly (missing files, unclear instructions), state the issue, pick the next-best approach, and continue."""
    )

    return "\n".join(lines)
