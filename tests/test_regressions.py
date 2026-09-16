import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from mapper_core import MapperState
from recovery_tkinter.rhino_surface_mapper_v2 import App


class RegressionTests(unittest.TestCase):
    def test_completed_routes_stay_completed(self):
        for implementation in (MapperState, App):
            for completion in ('reached', 'skipped'):
                with self.subTest(implementation=implementation, completion=completion):
                    state = implementation.__new__(implementation)
                    state.search_started = True
                    state.search_azimuth = 0
                    state.center_lat = state.center_lon = 0.0
                    state.datum_lat = state.datum_lon = 0.0
                    state.radius = 6371000
                    state.route_history = []
                    state.nextinfo = Mock()
                    total = math.ceil(2 * math.pi * 3500 / 1800)
                    state.route_index = total if completion == 'skipped' else total - 1
                    angle = (total - 1) * 2 * math.pi / total
                    state.rhino_lat, state.rhino_lon = state.xyll(3500 * math.sin(angle), 3500 * math.cos(angle))
                    for _ in range(3):
                        state.update_next()
                        self.assertIsNone(state.next_target_xy)
                    self.assertEqual(len(state.route_history), int(completion == 'reached'))
                    self.assertEqual(state.route_index, total)

    def test_poll_retries_partial_json_and_accepts_older_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Status.json'
            path.write_text('{', encoding='utf-8')
            state = Mock()
            state.status_path = path
            state.last_mtime = path.stat().st_mtime_ns + 100000
            previous = state.last_mtime
            App.poll(state)
            self.assertEqual(state.last_mtime, previous)
            state.process.assert_not_called()
            path.write_text(json.dumps({'Flags': 0}), encoding='utf-8')
            App.poll(state)
            state.process.assert_called_once_with({'Flags': 0})
            self.assertEqual(state.last_mtime, path.stat().st_mtime_ns)
            App.poll(state)
            state.process.assert_called_once()
