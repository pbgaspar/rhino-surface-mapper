"""Qt-free application-local filesystem paths."""

from __future__ import annotations

import sys
from pathlib import Path


def maps_directory() -> Path:
    """Return the application MAPAS directory, creating it when needed."""
    base = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent
    directory = base / 'MAPAS'
    directory.mkdir(parents=True, exist_ok=True)
    return directory
