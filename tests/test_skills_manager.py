from __future__ import annotations

import os
import textwrap
from pathlib import Path

from pywen.skills.loader import SKILLS_FILENAME
from pywen.skills.manager import SkillsManager
from pywen.skills.models import SkillScope


def _write_skill(root: Path, name: str, description: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / SKILLS_FILENAME
    path.write_text(
        textwrap.dedent(
            f"""\
            ---
            name: {name}
            description: {description}
            ---

            # Body
            """
        ),
        encoding="utf-8",
    )
    return path


def test_incremental_reload_preserves_scope_precedence_for_added_duplicate(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    (cwd / ".git").mkdir()

    _write_skill(home / "skills", "dupe", "from user")
    manager = SkillsManager(home)

    first = manager.skills_for_cwd(cwd)
    assert [(s.name, s.description, s.scope) for s in first.skills] == [
        ("dupe", "from user", SkillScope.USER)
    ]

    _write_skill(cwd / ".pywen" / "skills", "dupe", "from repo")
    incremental = manager.skills_for_cwd(cwd)

    assert [(s.name, s.description, s.scope) for s in incremental.skills] == [
        ("dupe", "from repo", SkillScope.REPO)
    ]


def test_incremental_reload_preserves_scope_precedence_for_modified_duplicate(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    (cwd / ".git").mkdir()

    repo_path = _write_skill(cwd / ".pywen" / "skills", "dupe", "from repo")
    _write_skill(home / "skills", "dupe", "from user")
    manager = SkillsManager(home)

    first = manager.skills_for_cwd(cwd)
    assert [(s.name, s.description, s.scope) for s in first.skills] == [
        ("dupe", "from repo", SkillScope.REPO)
    ]

    previous_mtime = repo_path.stat().st_mtime
    repo_path.write_text(
        textwrap.dedent(
            """\
            ---
            name: dupe
            description: from repo modified
            ---

            # Body
            """
        ),
        encoding="utf-8",
    )
    os.utime(repo_path, (previous_mtime + 1, previous_mtime + 1))

    incremental = manager.skills_for_cwd(cwd)
    assert [(s.name, s.description, s.scope) for s in incremental.skills] == [
        ("dupe", "from repo modified", SkillScope.REPO)
    ]
