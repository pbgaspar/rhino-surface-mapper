"""Focused tests for Trash selection in the Map Library."""
import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QListWidget

from map_library import MapLibraryWindow


class MapLibraryTrashTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.library = MapLibraryWindow()

    def tearDown(self):
        self.library.close()

    def test_restore_requires_an_explicitly_selected_trash_entry(self):
        entry = SimpleNamespace(
            original_relative_path='System/Map.json',
            deleted_at=datetime.now(timezone.utc),
            destination=None,
        )
        observed = {}

        def inspect_dialog(dialog):
            listing = dialog.findChild(QListWidget)
            buttons = dialog.findChild(QDialogButtonBox)
            restore_button = next(button for button in buttons.buttons()
                                  if button.text() == 'Restore')
            observed['listing'] = listing
            observed['restore_button'] = restore_button
            observed['initially_disabled'] = not restore_button.isEnabled()

            listing.selectionModel().setCurrentIndex(
                listing.model().index(0, 0),
                QItemSelectionModel.SelectionFlag.NoUpdate,
            )
            observed['disabled_without_selection'] = not restore_button.isEnabled()
            self.library._restore_selected_trash(dialog, listing)

            listing.item(0).setSelected(True)
            observed['enabled_after_selection'] = restore_button.isEnabled()

        with patch('map_library.inspect_trash', return_value=([entry], 0)), \
                patch('map_library.restore_trash_entry') as restore, \
                patch.object(QDialog, 'exec', inspect_dialog):
            self.library.show_trash()

        self.assertTrue(observed['initially_disabled'])
        self.assertTrue(observed['disabled_without_selection'])
        self.assertTrue(observed['enabled_after_selection'])
        restore.assert_not_called()


if __name__ == '__main__':
    unittest.main()
