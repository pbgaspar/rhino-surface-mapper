"""Qt-free persistence helpers for Rhino Surface Mapper settings documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SUPPORTED_SETTINGS_VERSION = 1


def load_preferences(path: Path | str) -> dict[str, Any]:
    """Load flat internal preferences, falling back to an empty object."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return document if isinstance(document, dict) else {}


def save_preferences(path: Path | str, preferences: dict[str, Any]) -> None:
    """Save flat internal preferences without changing their file shape."""
    Path(path).write_text(
        json.dumps(preferences, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_exported_settings(path: Path | str) -> dict[str, Any]:
    """Read and structurally validate a versioned exported settings file."""
    document = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if (not isinstance(document, dict)
            or document.get("rhino_settings_version") != SUPPORTED_SETTINGS_VERSION):
        raise ValueError("Formato de configurações inválido.")
    settings = document.get("settings")
    if not isinstance(settings, dict) or not settings:
        raise ValueError("O ficheiro não contém configurações.")
    return settings


def write_exported_settings(path: Path | str, settings: dict[str, Any]) -> None:
    """Write a version-1 exported settings document."""
    document = {
        "rhino_settings_version": SUPPORTED_SETTINGS_VERSION,
        "settings": settings,
    }
    Path(path).write_text(
        json.dumps(document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
