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


def test_airlift_point_menu_starts_srv_navigation(window):
    from unittest.mock import Mock, patch

    window.set_airlift_active(True)
    point = max(window.view.airlift_points,
                key=lambda candidate: candidate.x_m ** 2 + candidate.y_m ** 2)
    window.state.center_lat = 38
    window.state.center_lon = -9
    assert window.state.rhino_lat is not None
    position = window.view.screen(point.x_m, point.y_m)
    assert window.view.marker_at(position) == ("airlift", point)

    menu = Mock()
    with patch("qt_map_operations.QMenu", return_value=menu):
        window.marker_menu(position)

    navigate = next(
        call for call in menu.addAction.call_args_list
        if call.args[0] == "Navigate")
    assert window.state.current_presentation.kind.value == "srv"
    assert window.state.center_lat == 38
    assert window.state.rhino_lat == 38
    navigate.args[1]()

    target = window.state.active_nav_target
    assert target["type"] == "airlift"
    assert target["item"] is point
    assert (target["x"], target["y"]) == (point.x_m, point.y_m)
    assert (target["_system"], target["_body"]) == ("Sol", "Earth")
    assert target["_latitude"] is not None
    assert target["_longitude"] is not None


def test_airlift_point_menu_starts_ship_navigation(window):
    from unittest.mock import Mock, patch
    from mapper_core import HAS_LAT_LONG_FLAG, MAIN_SHIP_FLAG

    window.set_airlift_active(True)
    point = max(window.view.airlift_points,
                key=lambda candidate: candidate.x_m ** 2 + candidate.y_m ** 2)
    window.state.process_status(dict(
        Flags=HAS_LAT_LONG_FLAG | MAIN_SHIP_FLAG,
        Latitude=38, Longitude=-9, Heading=0,
        StarSystem="Sol", BodyName="Earth"))
    window.refresh()
    position = window.view.screen(point.x_m, point.y_m)
    assert window.view.marker_at(position) == ("airlift", point)

    menu = Mock()
    with patch("qt_map_operations.QMenu", return_value=menu):
        window.marker_menu(position)

    navigate = next(
        call for call in menu.addAction.call_args_list
        if call.args[0] == "Navigate")
    navigate.args[1]()

    assert window.state.active_nav_target["item"] is point
    assert window.state.active_nav_target["type"] == "airlift"


def _navigation_item(window, kind):
    if kind == "marks":
        return {"name": "Target", "lat": 38.01, "lon": -9.0}
    if kind == "deposits":
        return {"name": "Deposit", "x": 1200.0, "y": 0.0}
    if kind == "rigs":
        return {"x": 0.0, "y": 1200.0}
    if kind == "route":
        return {"number": 1, "x": 1500.0, "y": 0.0}
    window.set_airlift_active(True)
    return max(window.view.airlift_points,
               key=lambda candidate: candidate.x_m ** 2 + candidate.y_m ** 2)


@pytest.mark.parametrize("kind", ["marks", "deposits", "rigs", "route", "airlift"])
def test_ship_can_navigate_to_geographic_targets(window, kind):
    item = _navigation_item(window, kind)
    from mapper_core import HAS_LAT_LONG_FLAG, MAIN_SHIP_FLAG

    window.state.process_status(dict(
        Flags=HAS_LAT_LONG_FLAG | MAIN_SHIP_FLAG,
        Latitude=38, Longitude=-9, Heading=0,
        StarSystem="Sol", BodyName="Earth"))
    window.refresh()

    window.start_navigation(kind, item)

    assert window.state.active_nav_target["type"] == kind
    assert window.state.active_nav_target["item"] is item


@pytest.mark.parametrize("kind", ["marks", "deposits", "rigs", "route", "airlift"])
def test_on_foot_cannot_start_geographic_navigation(window, kind):
    item = _navigation_item(window, kind)
    from mapper_core import HAS_LAT_LONG_FLAG, ON_FOOT_FLAG

    window.state.process_status(dict(
        Flags=HAS_LAT_LONG_FLAG, Flags2=ON_FOOT_FLAG,
        Latitude=38, Longitude=-9, Heading=0,
        StarSystem="Sol", BodyName="Earth"))

    window.start_navigation(kind, item)

    assert window.state.active_nav_target is None


def test_ship_navigation_preserves_search_state_without_pausing_or_progressing(window):
    from mapper_core import HAS_LAT_LONG_FLAG, MAIN_SHIP_FLAG

    assert window.state.start_search()
    search_state = (
        window.state.search_started,
        window.state.search_paused,
        window.state.search_pause_point,
        window.state.return_to_pause,
        window.state.route_index,
        window.state.next_target_xy,
        list(window.state.route_history),
    )
    route_item = {"number": 1, "x": 10_000.0, "y": 10_000.0}
    window.state.process_status(dict(
        Flags=HAS_LAT_LONG_FLAG | MAIN_SHIP_FLAG,
        Latitude=38, Longitude=-9, Heading=0,
        StarSystem="Sol", BodyName="Earth"))
    window.refresh()

    window.start_navigation("route", route_item)
    assert window.state.active_nav_target["item"] is route_item
    assert window.state.search_started
    assert window.state.search_paused is search_state[1]
    assert window.state.search_pause_point == search_state[2]
    assert window.state.return_to_pause is search_state[3]
    assert window.state.route_index == search_state[4]
    assert window.state.next_target_xy == search_state[5]
    assert window.state.route_history == search_state[6]

    window.state.update_next()
    assert not window.state.skip_next()
    window.stop_navigation()
    assert (
        window.state.search_started,
        window.state.search_paused,
        window.state.search_pause_point,
        window.state.return_to_pause,
        window.state.route_index,
        window.state.next_target_xy,
        window.state.route_history,
    ) == search_state


def test_srv_navigation_still_pauses_search_and_returns_to_pause(window):
    assert window.state.start_search()
    pause_point = window.state.llxy(
        window.state.rhino_lat, window.state.rhino_lon)
    window.start_navigation(
        "deposits", {"name": "Deposit", "x": 10_000.0, "y": 10_000.0})

    assert window.state.search_paused
    assert window.state.search_pause_point == pause_point

    window.state.rhino_lat, window.state.rhino_lon = window.state.xyll(500.0, 500.0)
    window.stop_navigation()

    assert window.state.return_to_pause
    assert window.state.search_pause_point == pause_point


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


def test_zero_duration_draws_only_disk_outlines_and_keeps_numbered_markers(window):
    from unittest.mock import Mock, patch
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    from airlift import DeploymentPosition

    view = window.view
    view.airlift_points = (
        DeploymentPosition(1, 0.0, 0.0),
        DeploymentPosition(2, 100.0, 100.0),
    )
    painter = Mock()

    view.airlift_fade_seconds = 0
    view.draw_airlift_disks(painter)
    assert painter.setBrush.call_args.args == (Qt.BrushStyle.NoBrush,)
    assert painter.drawEllipse.call_count == len(view.airlift_points)

    painter.reset_mock()
    view.airlift_fade_seconds = 5
    view.airlift_fade_started_at = 100.0
    with patch("rhino_surface_mapper_qt.time.monotonic", return_value=100.0):
        view.draw_airlift_disks(painter)
    assert isinstance(painter.setBrush.call_args.args[0], QColor)
    assert painter.drawEllipse.call_count == len(view.airlift_points)

    painter.reset_mock()
    view.airlift_fade_seconds = 0
    view.draw_airlift_disks(painter)
    assert painter.setBrush.call_args.args == (Qt.BrushStyle.NoBrush,)
    markers = Mock()
    view.draw_airlift_markers(markers)
    assert markers.drawText.call_count == len(view.airlift_points)


def test_search_and_airlift_are_mutually_exclusive(window):
    assert window.state.search_started is False
    assert window.set_airlift_active(True)
    assert window.start_search() is None
    assert not window.airlift_active
    assert window.state.search_started

    assert window.set_airlift_active(True)
    assert not window.state.search_started


def _start_srv_navigation(window, kind, item):
    window.state.center_lat = 38
    window.state.center_lon = -9
    window.start_navigation(kind, item)


def test_deactivating_airlift_cancels_airlift_navigation(window):
    window.set_airlift_active(True)
    point = max(window.view.airlift_points,
                key=lambda candidate: candidate.x_m ** 2 + candidate.y_m ** 2)
    _start_srv_navigation(window, "airlift", point)
    assert window.state.active_nav_target["type"] == "airlift"

    assert not window.set_airlift_active(False)

    assert window.state.active_nav_target is None
    assert not window.airlift_active
    assert not window.view.airlift_points


def test_deactivating_airlift_preserves_other_navigation(window):
    window.set_airlift_active(True)
    _start_srv_navigation(window, "route", {"number": 1, "x": 1500.0, "y": 0.0})

    assert not window.set_airlift_active(False)

    assert window.state.active_nav_target is not None
    assert window.state.active_nav_target["type"] == "route"


def test_starting_search_cancels_airlift_navigation(window):
    window.set_airlift_active(True)
    point = max(window.view.airlift_points,
                key=lambda candidate: candidate.x_m ** 2 + candidate.y_m ** 2)
    _start_srv_navigation(window, "airlift", point)

    with patch("rhino_surface_mapper_qt.QMessageBox.information"):
        window.start_search()

    assert not window.airlift_active
    assert window.state.search_started
    assert window.state.active_nav_target is None


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
