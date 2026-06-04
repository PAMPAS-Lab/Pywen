"""Skills manager with caching and incremental hot-reload via mtime polling.

When a change is detected (file added, modified, or removed), only the
affected skills are re-parsed and merged back into the cached outcome,
rather than performing a full reload of all skill roots.
"""
from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from threading import RLock
from typing import Optional

from .loader import (
    SkillParseError,
    load_skills_from_roots,
    parse_skill_file,
    skill_roots_for_cwd,
)
from .models import SkillError, SkillLoadOutcome, SkillMetadata, SkillRoot, SkillScope
from .system import install_system_skills


class SkillsManager:
    def __init__(self, pywen_home: Path, embedded_system_skills_dir: Path | None = None) -> None:
        try:
            install_system_skills(pywen_home, embedded_system_skills_dir)
        except Exception as err:
            print(f"failed to install system skills: {err}")

        self._pywen_home = pywen_home
        self._cache_by_cwd: dict[Path, SkillLoadOutcome] = {}
        self._detailed_mtime: dict[Path, dict[Path, float]] = {}
        self._lock = RLock()

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def skills_for_cwd(self, cwd: Optional[Path] = None) -> SkillLoadOutcome:
        return self.skills_for_cwd_with_options(cwd or Path.cwd(), force_reload=False)

    def skills_for_cwd_with_options(self, cwd: Path, force_reload: bool = False) -> SkillLoadOutcome:
        with self._lock:
            cached = self._cache_by_cwd.get(cwd)

        # Return cached result if nothing has changed
        if cached is not None and not force_reload:
            if not self._has_changed(cwd):
                return cached
            # Incremental reload: only re-parse changed files
            outcome = self._incremental_reload(cwd, cached)
            with self._lock:
                self._cache_by_cwd[cwd] = outcome
                self._detailed_mtime[cwd] = self._collect_skill_mtimes(cwd)
            return outcome

        # Full reload from disk (first load or forced)
        roots = skill_roots_for_cwd(self._pywen_home, cwd)
        outcome = load_skills_from_roots(roots)

        with self._lock:
            self._cache_by_cwd[cwd] = outcome
            self._detailed_mtime[cwd] = self._collect_skill_mtimes(cwd)

        return outcome

    # ------------------------------------------------------------------ #
    # Incremental hot-reload internals                                    #
    # ------------------------------------------------------------------ #

    def _collect_skill_mtimes(self, cwd: Path) -> dict[Path, float]:
        """Scan skill directories and return per-file mtime snapshot."""
        from .loader import skill_roots_for_cwd as _roots
        snapshot: dict[Path, float] = {}
        roots = _roots(self._pywen_home, cwd)
        for root in roots:
            if root.path.is_dir():
                with suppress(OSError):
                    for skill_file in root.path.rglob("SKILL.md"):
                        with suppress(OSError):
                            snapshot[skill_file.resolve()] = skill_file.stat().st_mtime
        return snapshot

    def _has_changed(self, cwd: Path) -> bool:
        """Check whether any skill files have been added, modified, or removed."""
        prev = self._detailed_mtime.get(cwd)
        if prev is None:
            return True  # No prior snapshot — treat as changed
        current = self._collect_skill_mtimes(cwd)
        return current != prev

    def _incremental_reload(self, cwd: Path, prev: SkillLoadOutcome) -> SkillLoadOutcome:
        """Re-parse only changed skills and merge with cached results.

        Steps:
        1. Compare current mtimes with previous to find changed/added/deleted files.
        2. Re-parse only the changed and added files.
        3. Merge new results with unchanged cached skills.
        4. Re-run deduplication and dependency checks on the merged set.
        """
        from .dependency_resolver import check_dependencies

        current_mtimes = self._collect_skill_mtimes(cwd)
        prev_mtimes = self._detailed_mtime.get(cwd, {})

        # Determine which files changed, were added, or were removed
        current_resolved = {str(p): p for p in current_mtimes}
        prev_resolved = {str(p): p for p in prev_mtimes}

        changed_or_added = {
            current_resolved[k]
            for k in current_resolved
            if k not in prev_resolved or current_mtimes[current_resolved[k]] != prev_mtimes[prev_resolved[k]]
        }
        deleted_paths = {prev_resolved[k] for k in prev_resolved if k not in current_resolved}

        # No changes at all — return cached result
        if not changed_or_added and not deleted_paths:
            return prev

        # Determine scope for new files by matching against roots
        roots = skill_roots_for_cwd(self._pywen_home, cwd)
        def _scope_for_path(path: Path) -> SkillScope:
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            for root in roots:
                try:
                    resolved.relative_to(root.path.resolve())
                    return root.scope
                except (ValueError, OSError):
                    continue
            return SkillScope.USER

        # Re-parse changed/added files
        newly_parsed: list[SkillMetadata] = []
        new_errors: list[SkillError] = []
        for path in changed_or_added:
            scope = _scope_for_path(path)
            try:
                skill = parse_skill_file(path, scope)
                newly_parsed.append(skill)
            except SkillParseError as err:
                if scope != SkillScope.SYSTEM:
                    new_errors.append(SkillError(path=path, message=str(err)))
            except Exception as err:
                if scope != SkillScope.SYSTEM:
                    new_errors.append(SkillError(path=path, message=str(err)))

        # Keep unchanged skills (those whose paths are not in changed/deleted sets)
        deleted_strs = {str(p) for p in deleted_paths}
        changed_strs = {str(p) for p in changed_or_added}
        unchanged_skills = [
            s for s in prev.skills
            if str(s.path) not in deleted_strs and str(s.path) not in changed_strs
        ]

        # Merge and re-run dedup + dependency check
        merged_skills = unchanged_skills + newly_parsed
        merged_skills.sort(key=self._skill_priority_key(roots))

        # Deduplicate by name (first occurrence wins, matching full-load behavior)
        seen: set[str] = set()
        deduped: list[SkillMetadata] = []
        for skill in merged_skills:
            if skill.name not in seen:
                seen.add(skill.name)
                deduped.append(skill)

        deduped.sort(key=lambda s: (s.name, str(s.path)))

        # Carry over previous errors for deleted/unchanged, plus new errors
        dependency_error_path = Path("<dependency>")
        prev_errors_kept = [
            e for e in prev.errors
            if e.path != dependency_error_path
            and str(e.path) not in deleted_strs
            and str(e.path) not in changed_strs
        ]
        all_errors = prev_errors_kept + new_errors

        # Re-check dependencies on the merged set
        dep_issues = check_dependencies(deduped)
        for issue in dep_issues:
            all_errors.append(SkillError(path=dependency_error_path, message=issue))

        return SkillLoadOutcome(
            skills=deduped,
            errors=all_errors,
            load_duration_ms=prev.load_duration_ms,
            parse_durations_ms=dict(prev.parse_durations_ms),
        )

    def _skill_priority_key(self, roots: list[SkillRoot]):
        """Return a sort key that preserves full-load root precedence."""
        root_paths: list[tuple[int, Path]] = []
        for index, root in enumerate(roots):
            try:
                root_paths.append((index, root.path.resolve()))
            except OSError:
                root_paths.append((index, root.path))

        scope_priority = {
            SkillScope.REPO: 0,
            SkillScope.USER: 1,
            SkillScope.SYSTEM: 2,
            SkillScope.ADMIN: 3,
        }

        def key(skill: SkillMetadata) -> tuple[int, int, str]:
            try:
                resolved = skill.path.resolve()
            except OSError:
                resolved = skill.path

            fallback_index = len(root_paths)
            for index, root_path in root_paths:
                try:
                    resolved.relative_to(root_path)
                    return (index, scope_priority.get(skill.scope, fallback_index), str(resolved))
                except ValueError:
                    continue

            return (
                fallback_index,
                scope_priority.get(skill.scope, fallback_index),
                str(resolved),
            )

        return key
