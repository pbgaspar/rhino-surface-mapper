"""Testes sem interface para a lógica de navegação do Mapper.

Executar a partir de ``rhino-surface-mapper`` com::

    py -3.13 -m unittest discover -s tests -v
"""

import math
import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from recovery_tkinter.rhino_surface_mapper_v2 import App


class FakeOverlay:
    def __init__(self):
        self.calls = []

    def set_navigation(self, heading, distance, heading_color, distance_color):
        self.calls.append((heading, distance, heading_color, distance_color))


class NavigationState:
    """Estado mínimo para testar ``App.update_overlay`` sem criar janelas."""

    _heading_error = staticmethod(App._heading_error)
    llxy = App.llxy

    def __init__(self):
        self.overlay = FakeOverlay()
        self.search_started = True
        self.next_target_xy = (0.0, 1_000.0)
        self.rhino_lat = 0.0
        self.rhino_lon = 0.0
        self.rhino_heading = 0.0
        self.center_lat = 0.0
        self.center_lon = 0.0
        self.radius = 6_371_000.0
        self.overlay_blink_on = True
        self.overlay_next_blink = 0.0


class NavigationLogicTests(unittest.TestCase):
    def test_heading_error_wraps_at_north(self):
        self.assertEqual(App._heading_error(359, 1), 2)
        self.assertEqual(App._heading_error(1, 359), -2)
        self.assertEqual(App._heading_error(90, 0), -90)
        self.assertEqual(App._heading_error(270, 0), 90)

    def test_overlay_instructions_match_heading_error(self):
        state = NavigationState()

        App.update_overlay(state)
        self.assertEqual(state.overlay.calls[-1], ("000°", "1000 m", "#00cc44", "white"))

        state.rhino_heading = 90.0
        App.update_overlay(state)
        self.assertEqual(state.overlay.calls[-1], ("<<< 000°", "1000 m", "#ff3030", "white"))

        state.rhino_heading = 359.0
        App.update_overlay(state)
        self.assertEqual(state.overlay.calls[-1], ("000°", "1000 m", "#00cc44", "white"))

        state.rhino_heading = 358.0
        App.update_overlay(state)
        self.assertEqual(state.overlay.calls[-1], ("000° >>>", "1000 m", "#ffd21c", "white"))

    def test_overlay_clears_when_navigation_data_is_incomplete(self):
        state = NavigationState()
        state.rhino_heading = None

        App.update_overlay(state)
        self.assertEqual(state.overlay.calls[-1], ("—", "—", "#888888", "white"))

    def test_rhino_icon_uses_nearest_five_degree_heading(self):
        state = type("IconState", (), {"rhino_icons": list(range(72))})()
        state.rhino_heading = 2.49
        self.assertEqual(App._rhino_icon_for_heading(state), 0)
        state.rhino_heading = 2.5
        self.assertEqual(App._rhino_icon_for_heading(state), 1)
        state.rhino_heading = 359.0
        self.assertEqual(App._rhino_icon_for_heading(state), 0)

    def test_coordinate_conversion_round_trip(self):
        state = type(
            "CoordinateState",
            (),
            {
                "center_lat": 38.0,
                "center_lon": -9.0,
                "radius": 6_371_000.0,
            },
        )()
        state.llxy = App.llxy.__get__(state)
        state.xyll = App.xyll.__get__(state)

        x, y = state.llxy(38.01, -8.98)
        lat, lon = state.xyll(x, y)
        self.assertTrue(math.isclose(lat, 38.01, abs_tol=1e-10))
        self.assertTrue(math.isclose(lon, -8.98, abs_tol=1e-10))


if __name__ == "__main__":
    unittest.main()
