import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 not installed",
)
_APP = None


def _application():
    from PySide6.QtWidgets import QApplication

    global _APP
    if _APP is None:
        _APP = QApplication([])
    return _APP


@pytest.fixture
def window(tmp_path):
    from airlift_preferences import (
        AIRLIFT_DEPLOYMENT_COUNT_KEY,
        AIRLIFT_FADE_SECONDS_KEY,
        AIRLIFT_RADIUS_KEY,
    )
    from mapper_core import HAS_LAT_LONG_FLAG, SRV_FLAG
    from rhino_surface_mapper_qt import MapperWindow

    _application()
    options_path = tmp_path / "options.json"
    options_path.write_text(json.dumps({
        AIRLIFT_RADIUS_KEY: 5,
        AIRLIFT_DEPLOYMENT_COUNT_KEY: 10,
        AIRLIFT_FADE_SECONDS_KEY: 5,
    }), encoding="utf-8")
    with patch("rhino_surface_mapper_qt.OPTIONS_PATH", options_path):
        result = MapperWindow(
            tmp_path / "Status.json", game_running_check=lambda: True)
    result.timer.stop()
    result.radar_timer.stop()
    result.state.process_status(dict(
        Flags=HAS_LAT_LONG_FLAG | SRV_FLAG,
        Latitude=38,
        Longitude=-9,
        Heading=0,
        StarSystem="Sol",
        BodyName="Earth",
    ))
    result.state.pml_id = "6"
    result.state.pml_center_lat = 38
    result.state.pml_center_lon = -9
    result.confirm_pml_exit = lambda: True
    result.refresh()
    yield result
    result.transition_required = False
    result.close()


def test_airlift_starts_off_and_activation_draws_selected_deployments(window):
    assert not window.airlift_active
    assert not window.view.airlift_points

    assert window.set_airlift_active(True)

    assert window.airlift_active
    assert len(window.view.airlift_points) == 10
    assert window.airlift_coverage_label.text() == "Coverage: 100.0%"
    assert window.state.active_nav_target is None

    assert not window.set_airlift_active(False)
    assert not window.airlift_active
    assert not window.view.airlift_points


def test_configuration_dialog_uses_operational_defaults_and_authoritative_coverage():
    from airlift import load_catalog
    from airlift_dialog import AirliftConfigurationDialog

    _application()
    dialog = AirliftConfigurationDialog(None, load_catalog(), 5, 10, 5)
    try:
        assert dialog.values() == (5, 10, 5)
        assert dialog.coverage.text() == "Coverage: 100.0%"

        dialog.radius.setCurrentIndex(dialog.radius.findData(7))
        assert dialog.values() == (7, 19, 5)
        assert dialog.coverage.text() == "Coverage: 100.0%"
    finally:
        dialog.close()


@pytest.mark.parametrize(("duration", "elapsed", "expected"), [
    (1, 0.5, 0.5),
    (5, 2.5, 0.5),
    (10, 5, 0.5),
])
def test_airlift_fade_only_changes_disks_and_zero_is_continuous(
        window, duration, elapsed, expected):
    from airlift import DeploymentPosition

    view = window.view
    view.airlift_points = tuple(
        DeploymentPosition(index, float(index), float(index))
        for index in range(1, 11))
    view.airlift_fade_seconds = duration
    view.airlift_fade_started_at = 100.0

    assert view.airlift_disk_opacity(now=100.0 + elapsed) == pytest.approx(expected)
    assert view.airlift_disk_opacity(now=100.0 + duration) == 0.0
    assert len(view.airlift_points) == 10

    view.airlift_fade_seconds = 0
    assert view.airlift_disk_opacity(now=1000.0) == 1.0


def test_search_and_airlift_are_mutually_exclusive(window):
    assert window.state.search_started is False
    assert window.set_airlift_active(True)
    assert window.start_search() is None
    assert not window.airlift_active
    assert window.state.search_started

    assert window.set_airlift_active(True)
    assert not window.state.search_started


def test_reconfiguration_updates_geometry_and_restarts_fade(window):
    window.set_airlift_active(True)
    assert len(window.view.airlift_points) == 10

    with patch(
            "rhino_surface_mapper_qt.AirliftConfigurationDialog") as dialog_type:
        dialog_type.return_value.exec.return_value = 1
        dialog_type.return_value.values.return_value = (7, 19, 10)
        with patch("rhino_surface_mapper_qt.time.monotonic", return_value=250.0):
            window.configure_airlift()

    assert (window.airlift_radius_km, window.airlift_deployment_count) == (7, 19)
    assert len(window.view.airlift_points) == 19
    assert window.view.airlift_fade_started_at == 250.0
    assert window.airlift_coverage_label.text() == "Coverage: 100.0%"


def test_pending_map_transition_hides_cached_airlift_geometry(window):
    window.set_airlift_active(True)
    assert window.view.airlift_points

    window.transition_required = True
    window.refresh()

    assert not window.view.airlift_points


def test_invalid_pml_state_does_not_show_stale_geometry(window):
    window.set_airlift_active(True)
    assert window.view.airlift_points

    window.state.pml_center_lat = None
    window.refresh()

    assert not window.view.airlift_points


def test_configuring_preferences_persists_no_active_state(window):
    with patch(
            "rhino_surface_mapper_qt.AirliftConfigurationDialog") as dialog_type:
        dialog_type.return_value.exec.return_value = 1
        dialog_type.return_value.values.return_value = (7, 19, 5)
        window.configure_airlift()

    stored = json.loads(window.options_path.read_text(encoding="utf-8"))
    assert stored["airlift_radius_km"] == 7
    assert stored["airlift_deployment_count"] == 19
    assert stored["airlift_fade_seconds"] == 5
    assert "airlift_active" not in stored
    assert "airlift_enabled" not in stored
    assert window.airlift_active is False
