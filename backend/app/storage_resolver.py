from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from .config import settings


class _TemplateLike(Protocol):
    document_type: str
    stored_filename: str | None
    storage_path: str


def _split_stored_path(stored_path: str) -> tuple[str | None, str | None]:
    """Return (parent_name, file_name) for a path stored on any OS."""
    parts = [part for part in re.split(r"[/\\]+", stored_path) if part and part not in {".", ".."}]
    if not parts:
        return None, None
    name = parts[-1]
    parent = parts[-2] if len(parts) >= 2 else None
    return parent, name


def resolve_stored_file(stored_path: str | None, base_dir: Path, *, subdir: str | None = None) -> Path:
    """Resolve a DB-stored absolute path against the current storage root.

    `storage_path` values are absolute paths recorded at write time. A database
    copied between the Docker server and the PC version (or between PCs) makes
    those paths invalid, so missing files are rebased onto `base_dir` by
    filename: `base_dir/subdir/name`, `base_dir/parent/name`, `base_dir/name`.
    """
    if stored_path:
        stored = Path(stored_path)
        if stored.is_file():
            return stored
    else:
        stored = None

    candidates: list[Path] = []
    if stored_path:
        parent, name = _split_stored_path(stored_path)
        if name:
            if subdir:
                candidates.append(base_dir / subdir / name)
            if parent and parent != subdir:
                candidates.append(base_dir / parent / name)
            candidates.append(base_dir / name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    if candidates:
        return candidates[0]
    return stored if stored is not None else base_dir


def document_template_file(template: _TemplateLike) -> Path:
    """Resolve the on-disk HWPX file for a DocumentTemplate row."""
    subdir = template.document_type.lower()
    path = resolve_stored_file(template.storage_path, settings.template_dir, subdir=subdir)
    if path.is_file() or not template.stored_filename:
        return path
    candidate = settings.template_dir / subdir / template.stored_filename
    if candidate.is_file():
        return candidate
    return path


def import_job_file(stored_path: str | None) -> Path:
    """Resolve an uploaded import/weather file inside the imports directory."""
    return resolve_stored_file(stored_path, settings.import_dir)
