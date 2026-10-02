"""Qt-free safe soft deletion and retention cleanup for map files."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app_paths import maps_directory, maps_trash_directory
from map_persistence import is_map_file_protected

TRASH_RETENTION_KEY = 'trash_retention_days'
DEFAULT_RETENTION_DAYS = 30
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 3650


@dataclass(frozen=True)
class TrashEntry:
    """A managed Trash item and its validated restore metadata."""

    item_path: Path
    original_relative_path: str
    deleted_at: datetime

    @property
    def destination(self) -> Path:
        return maps_directory() / Path(self.original_relative_path)


def _validated_relative_path(value: Any, maps_root: Path) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError('Trash metadata contains an invalid original path.')
    relative = Path(value)
    destination = (maps_root / relative).resolve()
    try:
        destination.relative_to(maps_root)
    except ValueError as exc:
        raise ValueError('Trash metadata contains a path outside the map library.') from exc
    if destination.suffix.lower() != '.json':
        raise ValueError('Trash metadata does not identify a map file.')
    return relative


def _validated_trash_item(item: Path, trash_root: Path) -> tuple[Path, Path, Path]:
    """Return contained regular Trash paths, rejecting symlink traversal."""
    if item.is_symlink() or not item.is_dir():
        raise ValueError('Trash item is not a regular directory.')
    resolved_item = item.resolve()
    try:
        resolved_item.relative_to(trash_root)
    except ValueError as exc:
        raise ValueError('Trash item is outside the Trash directory.') from exc

    paths = []
    for name in ('metadata.json', 'map.json'):
        path = item / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Trash item is missing a regular {name}.')
        resolved_path = path.resolve()
        try:
            resolved_path.relative_to(resolved_item)
        except ValueError as exc:
            raise ValueError(f'Trash {name} is outside its item directory.') from exc
        paths.append(resolved_path)
    return resolved_item, paths[0], paths[1]


def inspect_trash() -> tuple[list[TrashEntry], int]:
    """Return valid managed entries and the count of invalid preserved items."""
    maps_root = maps_directory().resolve()
    trash_root = maps_trash_directory().resolve()
    valid = []
    invalid = 0
    for item in trash_root.iterdir():
        if not item.is_dir() and not item.is_symlink():
            continue
        try:
            resolved_item, metadata_path, _ = _validated_trash_item(item, trash_root)
            metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
            if not isinstance(metadata, dict):
                raise ValueError('Trash metadata must be a JSON object.')
            relative = _validated_relative_path(metadata.get('original_relative_path'), maps_root)
            deleted_at = datetime.fromisoformat(metadata['deleted_at']).astimezone(timezone.utc)
            valid.append(TrashEntry(resolved_item, relative.as_posix(), deleted_at))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            invalid += 1
    return valid, invalid


def restore_trash_entry(entry: TrashEntry, destination: Path | str | None = None) -> Path:
    """Restore one entry without overwriting an existing map."""
    valid_entries, _ = inspect_trash()
    current = next((candidate for candidate in valid_entries if candidate.item_path == entry.item_path), None)
    if current is None:
        raise ValueError('The selected Trash entry is no longer valid.')
    maps_root = maps_directory().resolve()
    target = (maps_root / current.original_relative_path if destination is None
              else Path(destination)).resolve()
    try:
        target.relative_to(maps_root)
    except ValueError as exc:
        raise ValueError('The restore destination is outside the map library.') from exc
    if target.exists():
        raise FileExistsError(f'The restore destination already exists: {target.name}')
    target.parent.mkdir(parents=True, exist_ok=True)
    os.rename(current.item_path / 'map.json', target)
    try:
        (current.item_path / 'metadata.json').unlink()
        current.item_path.rmdir()
    except OSError as exc:
        raise OSError('The map was restored, but its Trash metadata could not be cleaned up.') from exc
    return target


def retention_days(value: Any) -> int:
    """Normalize a persisted retention value to the supported safe range."""
    if type(value) is not int or not MIN_RETENTION_DAYS <= value <= MAX_RETENTION_DAYS:
        return DEFAULT_RETENTION_DAYS
    return value


def soft_delete_map(path: Path | str, *, active_path: Path | str | None = None) -> Path:
    """Move an eligible map into Trash and return its internal item directory."""
    source = Path(path)
    maps_root = maps_directory().resolve()
    source_resolved = source.resolve()
    if not source_resolved.is_file() or source_resolved.suffix.lower() != '.json':
        raise ValueError('The selected map is no longer a regular map file.')
    try:
        relative = source_resolved.relative_to(maps_root)
    except ValueError as exc:
        raise ValueError('The selected file is outside the map library.') from exc
    if active_path is not None and source_resolved == Path(active_path).resolve():
        raise ValueError('The currently active map cannot be deleted.')
    if is_map_file_protected(source_resolved):
        raise ValueError('Protected maps cannot be deleted.')

    trash = maps_trash_directory()
    item = trash / uuid.uuid4().hex
    item.mkdir()
    metadata = {'original_relative_path': relative.as_posix(),
                'deleted_at': datetime.now(timezone.utc).isoformat()}
    try:
        (item / 'metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        os.replace(source_resolved, item / 'map.json')
    except (OSError, ValueError):
        try:
            if not (item / 'map.json').exists():
                (item / 'metadata.json').unlink(missing_ok=True)
                item.rmdir()
        except OSError:
            pass
        raise
    return item


def cleanup_expired_trash(days: Any) -> int:
    """Remove only complete, recognized Trash items older than ``days``."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days(days))
    removed = 0
    maps_root = maps_directory().resolve()
    trash_root = maps_trash_directory().resolve()
    for item in trash_root.iterdir():
        if not item.is_dir() and not item.is_symlink():
            continue
        try:
            resolved_item, metadata_path, map_path = _validated_trash_item(item, trash_root)
            metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
            if not isinstance(metadata, dict):
                raise ValueError('Trash metadata must be a JSON object.')
            _validated_relative_path(metadata.get('original_relative_path'), maps_root)
            deleted = datetime.fromisoformat(metadata['deleted_at']).astimezone(timezone.utc)
            if deleted >= cutoff:
                continue
            if not map_path.is_file():
                continue
            map_path.unlink()
            metadata_path.unlink()
            resolved_item.rmdir()
            removed += 1
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return removed
