"""Build-time helpers for Qt translation catalogues."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sysconfig


class TranslationCompilationError(RuntimeError):
    """Raised when the Qt translation catalogue cannot be compiled."""


def _lrelease_executable() -> Path:
    """Return the PySide6 lrelease wrapper from the active Python environment."""
    executable_name = (
        "pyside6-lrelease.exe" if os.name == "nt" else "pyside6-lrelease"
    )
    return Path(sysconfig.get_path("scripts")) / executable_name


def compile_translation_catalogue(source: Path, output: Path) -> None:
    """Compile a Qt Linguist TS source using the active environment's wrapper.

    The caller must stop packaging if this function raises; this prevents a
    stale ignored QM file from being used after a failed compilation.
    """
    source = Path(source).resolve()
    output = Path(output).resolve()
    compiler = _lrelease_executable()
    if not source.is_file():
        raise TranslationCompilationError(
            f"Qt translation source was not found: {source}"
        )
    if not compiler.is_file():
        raise TranslationCompilationError(
            f"PySide6 translation compiler was not found: {compiler}. "
            "Install the project requirements with PySide6 6.3.0 or newer."
        )

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise TranslationCompilationError(
            f"Could not prepare the translation output directory: {exc}"
        ) from exc
    command = [str(compiler), str(source), "-qm", str(output)]
    try:
        subprocess.run(command, check=True)
    except OSError as exc:
        raise TranslationCompilationError(
            f"Could not start the PySide6 translation compiler: {exc}"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise TranslationCompilationError(
            "PySide6 translation compilation failed "
            f"with exit code {exc.returncode}; see compiler output above."
        ) from exc

    if not output.is_file() or output.stat().st_size == 0:
        raise TranslationCompilationError(
            f"PySide6 translation compiler did not create a catalogue: {output}"
        )
