"""Skills manager with caching."""
from __future__ import annotations
from pathlib import Path
from typing import Optional
from threading import RLock
from .loader import load_skills_from_roots, skill_roots_for_cwd
from .models import SkillLoadOutcome
from .system import install_system_skills

class SkillsManager:
    def __init__(self, pywen_home: Path, embedded_system_skills_dir: Path | None = None) -> None:
        try:
            install_system_skills(pywen_home, embedded_system_skills_dir)
        except Exception as err:
            print(f"failed to install system skills: {err}")

        self._pywen_home = pywen_home
        self._cache_by_cwd: dict[Path, SkillLoadOutcome] = {}
        self._lock = RLock()

    def skills_for_cwd(self, cwd: Optional[Path] = None) -> SkillLoadOutcome:
        return self.skills_for_cwd_with_options(cwd or Path.cwd(), force_reload=False)

    def skills_for_cwd_with_options(self, cwd: Path, force_reload: bool = False) -> SkillLoadOutcome:
        with self._lock:
            cached = self._cache_by_cwd.get(cwd)
        if cached is not None and not force_reload:
            return cached

        roots = skill_roots_for_cwd(self._pywen_home, cwd)
        outcome = load_skills_from_roots(roots)
        with self._lock:
            self._cache_by_cwd[cwd] = outcome
        return outcome
