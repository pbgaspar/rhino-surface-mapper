"""Focused tests for Map Library system discovery, ordering and search."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

from map_library import MapLibraryWindow


class MapLibrarySystemListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.library = None
        self.maps_directory_patch = patch('map_library.maps_directory', return_value=self.root)
        self.maps_directory_patch.start()

    def tearDown(self):
        if self.library is not None:
            self.library.close()
        self.maps_directory_patch.stop()
        self.tmp.cleanup()

    def add_system(self, name, mtime, maps=('Map [1].json',)):
        system = self.root / name
        system.mkdir()
        for map_name in maps:
            path = system / map_name
            path.write_text('{}', encoding='utf-8')
            os.utime(path, (mtime, mtime))
        return system

    def make_library(self):
        self.library = MapLibraryWindow()
        self.library.refresh_systems()
        return self.library

    def suggestions(self, library):
        return [library.suggestions.item(i).text() for i in range(library.suggestions.count())]

    def test_empty_search_lists_all_systems_with_maps_newest_first(self):
        self.add_system('Alpha', 1_000)
        self.add_system('Beta', 3_000)
        self.add_system('Gamma', 2_000)
        (self.root / 'Empty').mkdir()
        library = self.make_library()
        self.assertEqual(self.suggestions(library), ['Beta', 'Gamma', 'Alpha'])

    def test_system_mtime_is_newest_map_in_folder(self):
        system = self.add_system('Delta', 1_000, maps=('Old [1].json',))
        newest = system / 'New [2].json'
        newest.write_text('{}', encoding='utf-8')
        os.utime(newest, (5_000, 5_000))
        self.add_system('Epsilon', 2_000)
        library = self.make_library()
        self.assertEqual(self.suggestions(library), ['Delta', 'Epsilon'])

    def test_equal_timestamps_sort_alphabetically(self):
        self.add_system('zeta', 1_000)
        self.add_system('Alpha', 1_000)
        self.add_system('beta', 1_000)
        library = self.make_library()
        self.assertEqual(self.suggestions(library), ['Alpha', 'beta', 'zeta'])

    def test_search_filters_while_preserving_recency_order(self):
        self.add_system('Kappa One', 1_000)
        self.add_system('Lyra', 4_000)
        self.add_system('Kappa Two', 3_000)
        library = self.make_library()
        library.search.setText('kappa')
        self.assertEqual(self.suggestions(library), ['Kappa Two', 'Kappa One'])

    def test_short_search_text_keeps_minimum_length_rule(self):
        self.add_system('Kappa', 1_000)
        library = self.make_library()
        library.search.setText('k')
        self.assertEqual(self.suggestions(library), [])
        library.search.setText('   ')
        self.assertEqual(self.suggestions(library), ['Kappa'])

    def test_reopening_library_keeps_current_system_highlighted(self):
        self.add_system('Alpha', 1_000)
        self.add_system('Kappa', 2_000)
        library = self.make_library()
        library.select_system('Alpha')
        library.show()
        self.assertEqual(library.suggestions.currentItem().text(), 'Alpha')
        self.assertEqual(library.current_system, 'Alpha')

    def test_showing_library_picks_up_new_system(self):
        self.add_system('Alpha', 1_000)
        library = self.make_library()
        self.add_system('Beta', 2_000)
        library.show()
        self.assertEqual(self.suggestions(library), ['Beta', 'Alpha'])


if __name__ == '__main__':
    unittest.main()
