import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import qt_map_operations as maps

class MapsDirectoryTests(unittest.TestCase):
    def test_executable_directory_not_extraction_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            exe = base/'Portable'/'RhinoSurfaceMapper.exe'
            with patch.object(maps.sys,'frozen',True,create=True), patch.object(maps.sys,'executable',str(exe)), patch.object(maps,'__file__',str(base/'_MEI123'/'qt_map_operations.py')):
                result = maps.maps_directory()
                self.assertEqual(result,exe.resolve().parent/'MAPAS')
                self.assertTrue(result.is_dir())
                self.assertEqual(maps.maps_directory(),result)

    def test_source_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'source'/'qt_map_operations.py'
            with patch.object(maps.sys,'frozen',False,create=True), patch.object(maps,'__file__',str(source)):
                self.assertEqual(maps.maps_directory(),source.resolve().parent/'MAPAS')

