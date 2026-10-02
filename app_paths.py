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


def application_directory() -> Path:
    """Return the directory containing the running application resources."""
    return Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent


def maps_trash_directory() -> Path:
    """Return the RSM-managed Trash directory beside ``MAPAS``."""
    directory = application_directory() / 'MAPAS_TRASH'
    directory.mkdir(parents=True, exist_ok=True)
    return directory
