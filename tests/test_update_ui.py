import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTranslator
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton

from app_version import APP_NAME, APP_VERSION, AUTHOR_NAME
from release_updates import parse_release_entries
from update_controller import ManualCheckResult
from update_ui import AboutDialog, UpdateBanner


class UpdateUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_banner_manual_result_does_not_dismiss_persistent_notice(self):
        release = parse_release_entries([{
            "tag_name": "v0.1.0-beta.4",
            "name": "Beta 4",
            "draft": False,
            "prerelease": True,
            "html_url": (
                "https://github.com/pbgaspar/rhino-surface-mapper/releases/tag/"
                "v0.1.0-beta.4"
            ),
        }])[0]
        banner = UpdateBanner()
        dismissed = []
        banner.dismiss_requested.connect(lambda: dismissed.append(True))
        banner.set_persistent_release(release)
        self.assertTrue(banner.isVisible())
        banner.show_manual_result(ManualCheckResult(release))
        buttons = banner.findChildren(QPushButton)
        buttons[-1].click()
        self.assertEqual(dismissed, [])
        self.assertTrue(banner.isVisible())
        self.assertTrue(banner._displayed_persistently)
        banner.close()

    def test_about_dialog_contains_canonical_identity_and_repository_action(self):
        dialog = AboutDialog()
        labels = dialog.findChildren(QLabel)
        text = [label.text() for label in labels]
        self.assertTrue(any(APP_NAME in label for label in text))
        self.assertTrue(any(APP_VERSION in label for label in text))
        self.assertTrue(any(AUTHOR_NAME in label for label in text))
        self.assertIn(
            "Companion tool for exploring and mapping surface mining sites "
            "in Elite Dangerous.", text)
        repository = next(label for label in labels if '<a href=' in label.text())
        self.assertEqual(
            repository.text(),
            '<a href="https://github.com/pbgaspar/rhino-surface-mapper">'
            'Project repository on GitHub</a>')
        self.assertTrue(repository.openExternalLinks())
        self.assertEqual(
            [button.text() for button in dialog.findChildren(QPushButton)],
            ['Close'])
        dialog.show()
        dialog.findChild(QPushButton).click()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_about_dialog_uses_portuguese_description_and_repository_label(self):
        from i18n import catalogue_path

        translator = QTranslator()
        self.assertTrue(translator.load(str(catalogue_path('pt_PT'))))
        self.assertTrue(self.app.installTranslator(translator))
        dialog = AboutDialog()
        try:
            text = [label.text() for label in dialog.findChildren(QLabel)]
            self.assertIn(
                'Ferramenta de apoio à exploração e ao mapeamento de locais '
                'de mineração de superfície em Elite Dangerous.', text)
            repository = next(label for label in dialog.findChildren(QLabel)
                              if '<a href=' in label.text())
            self.assertEqual(
                repository.text(),
                '<a href="https://github.com/pbgaspar/rhino-surface-mapper">'
                'Repositório do projeto no GitHub</a>')
            self.assertTrue(repository.openExternalLinks())
        finally:
            dialog.close()
            self.app.removeTranslator(translator)

    def test_main_window_exposes_help_menu_actions(self):
        from rhino_surface_mapper_qt import MapperWindow

        with tempfile.TemporaryDirectory() as directory:
            options_path = Path(directory) / "options.json"
            status_path = Path(directory) / "Status.json"
            with patch("rhino_surface_mapper_qt.OPTIONS_PATH", options_path):
                window = MapperWindow(
                    status_path, game_running_check=lambda: True
                )
            window.confirm_pml_exit = lambda: True
            try:
                self.assertEqual(window.help_menu.title(), "Help")
                self.assertEqual(
                    [action.text() for action in window.help_menu.actions()],
                    ["Check for Updates...", "About Rhino Surface Mapper..."],
                )
            finally:
                window.close()
