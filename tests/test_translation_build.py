from pathlib import Path
import subprocess

import pytest
from PySide6.QtCore import QTranslator

import translation_build
from translation_build import (
    TranslationCompilationError,
    compile_translation_catalogue,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRANSLATION_SOURCE = PROJECT_ROOT / "translations" / "rsm_pt_PT.ts"


def test_compile_catalogue_overwrites_stale_output_and_loads_portuguese(
    tmp_path,
):
    output = tmp_path / "rsm_pt_PT.qm"
    output.write_bytes(b"stale catalogue")

    compile_translation_catalogue(TRANSLATION_SOURCE, output)

    translator = QTranslator()
    assert translator.load(str(output))
    assert translator.translate("LayoutOptions", "Ship") == "Nave"


def test_missing_lrelease_tool_fails_with_install_guidance(tmp_path, monkeypatch):
    missing_tool = tmp_path / "missing" / "pyside6-lrelease.exe"
    monkeypatch.setattr(
        translation_build, "_lrelease_executable", lambda: missing_tool
    )

    with pytest.raises(
        TranslationCompilationError, match="Install the project requirements"
    ):
        compile_translation_catalogue(TRANSLATION_SOURCE, tmp_path / "out.qm")


def test_lrelease_failure_is_reported_and_does_not_package_stale_output(
    tmp_path, monkeypatch
):
    compiler = tmp_path / "pyside6-lrelease.exe"
    compiler.touch()
    output = tmp_path / "out.qm"
    output.write_bytes(b"stale catalogue")
    monkeypatch.setattr(
        translation_build, "_lrelease_executable", lambda: compiler
    )

    def fail_compilation(*_args, **_kwargs):
        raise subprocess.CalledProcessError(2, [str(compiler)])

    monkeypatch.setattr(translation_build.subprocess, "run", fail_compilation)

    with pytest.raises(TranslationCompilationError, match="exit code 2"):
        compile_translation_catalogue(TRANSLATION_SOURCE, output)


def test_success_without_a_catalogue_is_reported(tmp_path, monkeypatch):
    compiler = tmp_path / "pyside6-lrelease.exe"
    compiler.touch()
    monkeypatch.setattr(
        translation_build, "_lrelease_executable", lambda: compiler
    )
    monkeypatch.setattr(
        translation_build.subprocess, "run", lambda *_args, **_kwargs: None
    )

    with pytest.raises(
        TranslationCompilationError, match="did not create a catalogue"
    ):
        compile_translation_catalogue(TRANSLATION_SOURCE, tmp_path / "out.qm")
