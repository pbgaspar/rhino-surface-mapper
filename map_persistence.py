"""Low-level filesystem and JSON persistence operations for Rhino Surface Mapper files."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


def read_map_json(path: Path | str) -> dict[str, Any]:
    """Read and parse a JSON map file from disk using UTF-8 encoding."""
    target = Path(path)
    return json.loads(target.read_text(encoding="utf-8"))


def write_map_json(path: Path | str, data: dict[str, Any]) -> None:
    """Write a dictionary to disk as a UTF-8 encoded, formatted JSON map file."""
    target = Path(path)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def is_map_file_protected(path: Path | str) -> bool:
    """Check whether an existing map file on disk has the protected flag set."""
    target = Path(path)
    if not target.exists():
        return False
    data = read_map_json(target)
    return bool(data.get("protected", False))


def update_map_file_flags(path: Path | str, *, favorite: bool, protected: bool) -> None:
    """Atomically update favorite and protected flags in a map file, preserving file mtime."""
    if type(favorite) is not bool or type(protected) is not bool:
        raise ValueError("Favorito e proteção devem ser valores booleanos.")

    target = Path(path)
    stats = target.stat()
    data = read_map_json(target)
    data.update(favorite=favorite, protected=protected)

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, target)
        os.utime(target, ns=(stats.st_atime_ns, stats.st_mtime_ns))
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def read_file_timestamps(path: Path | str) -> tuple[str, str]:
    """Return creation and modification times from file metadata as ISO 8601 strings."""
    target = Path(path)
    stats = target.stat()
    created_at = datetime.fromtimestamp(stats.st_ctime).astimezone().isoformat(timespec="seconds")
    last_saved_at = datetime.fromtimestamp(stats.st_mtime).astimezone().isoformat(timespec="seconds")
    return created_at, last_saved_at
