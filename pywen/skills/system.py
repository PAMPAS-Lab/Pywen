"""System skills caching and installation."""
from __future__ import annotations
from pathlib import Path
import hashlib
import os
import shutil

SYSTEM_SKILLS_DIR_NAME = ".system"
SKILLS_DIR_NAME = "skills"
SYSTEM_SKILLS_MARKER_FILENAME = ".pywen-system-skills.marker"
SYSTEM_SKILLS_MARKER_SALT = "v1"

class SystemSkillsError(Exception):
    pass

def system_cache_root_dir(pywen_home: Path) -> Path:
    return pywen_home / SKILLS_DIR_NAME / SYSTEM_SKILLS_DIR_NAME

def install_system_skills(pywen_home: Path, embedded_skills_dir: Path | None = None) -> None:
    if embedded_skills_dir is None:
        return

    dest_system = system_cache_root_dir(pywen_home)
    dest_system.mkdir(parents=True, exist_ok=True)

    marker_path = dest_system / SYSTEM_SKILLS_MARKER_FILENAME
    expected_fingerprint = embedded_system_skills_fingerprint(embedded_skills_dir)
    if dest_system.is_dir() and marker_path.exists():
        try:
            marker = marker_path.read_text(encoding="utf-8").strip()
        except OSError as err:
            raise SystemSkillsError(f"read system skills marker: {err}") from err
        if marker == expected_fingerprint:
            return

    if dest_system.exists():
        shutil.rmtree(dest_system)

    write_embedded_dir(embedded_skills_dir, dest_system)
    try:
        marker_path.write_text(f"{expected_fingerprint}\n", encoding="utf-8")
    except OSError as err:
        raise SystemSkillsError(f"write system skills marker: {err}") from err

def embedded_system_skills_fingerprint(embedded_dir: Path) -> str:
    items: list[tuple[str, str | None]] = []
    for root, dirs, files in os.walk(embedded_dir):
        rel_root = os.path.relpath(root, embedded_dir)
        items.append((rel_root, None))
        for filename in files:
            path = Path(root) / filename
            contents_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            rel_path = os.path.relpath(path, embedded_dir)
            items.append((rel_path, contents_hash))

    items.sort(key=lambda item: item[0])
    hasher = hashlib.sha256()
    hasher.update(SYSTEM_SKILLS_MARKER_SALT.encode("utf-8"))
    for path, contents_hash in items:
        hasher.update(path.encode("utf-8"))
        if contents_hash is not None:
            hasher.update(contents_hash.encode("utf-8"))
    return hasher.hexdigest()

def write_embedded_dir(source: Path, dest: Path) -> None:
    if not source.is_dir():
        raise SystemSkillsError(f"embedded system skills dir not found: {source}")

    for root, dirs, files in os.walk(source):
        rel_root = os.path.relpath(root, source)
        target_root = dest / rel_root if rel_root != "." else dest
        target_root.mkdir(parents=True, exist_ok=True)
        for dirname in dirs:
            (target_root / dirname).mkdir(parents=True, exist_ok=True)
        for filename in files:
            src_path = Path(root) / filename
            dst_path = target_root / filename
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst_path)
