"""Low-level reading and change detection for Elite Dangerous Status.json."""

from __future__ import annotations

import json
from os import PathLike
from pathlib import Path
from typing import Any


def read_status_if_changed(
    path: str | PathLike[str],
    previous_mtime_ns: int | None,
    *,
    force: bool = False,
) -> tuple[int, Any] | None:
    """Read a status document when its file has changed or rereading is forced."""
    status_path = Path(path)
    mtime_ns = status_path.stat().st_mtime_ns
    if not force and mtime_ns == previous_mtime_ns:
        return None
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    return mtime_ns, payload
