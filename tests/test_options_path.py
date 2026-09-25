import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import rhino_surface_mapper_qt


class OptionsPathTests(unittest.TestCase):
    def test_source_options_path_stays_next_to_source_module(self):
        expected = Path(rhino_surface_mapper_qt.__file__).resolve().parent / 'options.json'
        self.assertEqual(rhino_surface_mapper_qt.OPTIONS_PATH, expected)

    def test_frozen_options_path_stays_next_to_executable(self):
        executable = Path('portable') / 'RhinoSurfaceMapper.exe'
        try:
            with patch.object(sys, 'frozen', True, create=True), \
                    patch.object(sys, 'executable', str(executable)):
                reloaded = importlib.reload(rhino_surface_mapper_qt)
                self.assertEqual(reloaded.OPTIONS_PATH, executable.resolve().parent / 'options.json')
        finally:
            importlib.reload(rhino_surface_mapper_qt)


if __name__ == '__main__':
    unittest.main()
