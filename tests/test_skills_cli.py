from __future__ import annotations

import asyncio
import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

from pywen.main import async_main
from pywen.skills.loader import SKILLS_FILENAME

ROOT = Path(__file__).resolve().parents[1]


def _write_skill(root: Path, name: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / SKILLS_FILENAME).write_text(
        textwrap.dedent(
            f"""\
            ---
            name: {name}
            description: Healthy skill
            ---

            # Body
            """
        ),
        encoding="utf-8",
    )


def test_skill_health_check_cli_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    _write_skill(repo / ".pywen" / "skills", "healthy")

    monkeypatch.setenv("HOME", str(home))
    os.chdir(ROOT)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(sys, "argv", ["pywen", "skill", "health-check", "--json"])

    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(async_main())

    assert exc_info.value.code == 0
    output = capsys.readouterr()
    reports = json.loads(output.out)
    assert output.err == ""
    assert reports == [
        {
            "skill_name": "healthy",
            "skill_path": str((repo / ".pywen" / "skills" / "healthy" / SKILLS_FILENAME).resolve()),
            "scope": "repo",
            "is_healthy": True,
            "issues": [],
        }
    ]
