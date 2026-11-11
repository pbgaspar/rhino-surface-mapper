"""Contrato do layout: botões fixos e preferências sem perder outros campos."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from xml.etree import ElementTree
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QPushButton, QSpinBox
from PySide6.QtCore import Qt, QTranslator
from layout_options import (OP_MARK, OP_MARK_DEPOSIT, OP_MARK_RIG,
                            SECTION_LAYOUT, THEME_DARK,
                            THEME_LABELS, THEME_LIGHT, THEME_SYSTEM,
                            _theme_is_dark)
from airlift_preferences import (
    AIRLIFT_DEPLOYMENT_COUNT_KEY,
    AIRLIFT_FADE_SECONDS_KEY,
    AIRLIFT_RADIUS_KEY,
    normalize_airlift_preferences,
)
from settings_persistence import load_preferences
from rhino_surface_mapper_qt import MapperWindow
from surface_mining_coordinator import SurfaceMiningCoordinator


class LayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.status_path = Path(self.temp.name)/'Status.json'
        self.window = MapperWindow(
            self.status_path, game_running_check=lambda: True)
        self.window.surface_mining_coordinator.prefetch_snapshot = Mock()
        self.window.options_path = Path(self.temp.name)/'options.json'
        for timer in (self.window.timer,self.window.radar_timer,self.window.assist_timer):
            timer.stop()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.temp.cleanup()

    def test_menu_bar_toolbar_layout_and_options_panel_state(self):
        w = self.window
        self.assertEqual(
            [action.text() for action in w.menuBar().actions()],
            ['Maps', 'Market Research', 'Options', 'Help', 'Exit'])
        self.assertEqual(
            [action.text() for action in w.maps_menu.actions()],
            ['Open', 'Open from file…', 'Save', 'New', 'View and Manage'])
        self.assertEqual(
            [action.text() for action in w.help_menu.actions()],
            ['Check for Updates...', 'About Rhino Surface Mapper...'])
        self.assertFalse(w.market_research_action.menu())
        self.assertFalse(w.options_action.menu())
        self.assertFalse(w.exit_action.menu())
        self.assertEqual(len(w.op_buttons), 3)
        self.assertTrue(all(isinstance(button, QPushButton)
                            for button in w.op_buttons.values()))

        width = w.view.width()
        with patch.object(w, 'pause_assistance') as pause:
            w.options_action.setChecked(True)
            pause.assert_called_once_with('Configurações abertas')
        self.app.processEvents()
        self.assertLess(w.view.width(),width)
        self.assertTrue(w.options_panel_open)
        self.assertTrue(w.options_panel.isVisible())
        self.assertTrue(all(not header.isChecked() for header,_ in w.option_sections.values()))
        w.radar_options()
        self.app.processEvents()
        self.assertEqual(w.view.width(),width)
        self.assertFalse(w.options_panel_open)
        self.assertFalse(w.options_panel.isVisible())
        self.assertFalse(w.options_action.isChecked())

        w.set_options_panel_open(True)
        close = next(button for button in w.options_panel.findChildren(QPushButton)
                     if button.text() == 'Close options ×')
        close.click()
        self.assertFalse(w.options_panel_open)
        self.assertFalse(w.options_action.isChecked())
        self.assertEqual(len([button for button in w.findChildren(QPushButton)
                              if button.text() == 'Choose Status.json']), 1)

    def test_menu_actions_keep_their_callbacks(self):
        callback_names = (
            'load_map', 'open_map_file', 'save_map', 'new_map',
            'show_map_library', 'show_market_research',
            'check_for_updates_manually', 'show_about_dialog', 'close',
        )
        callbacks = {name: Mock() for name in callback_names}
        with patch.multiple(MapperWindow, **callbacks):
            window = MapperWindow(
                Path(self.temp.name) / 'callbacks-Status.json',
                game_running_check=lambda: True)
            try:
                for action in window.maps_menu.actions():
                    action.trigger()
                window.market_research_action.trigger()
                window.check_updates_action.trigger()
                window.about_action.trigger()
                window.exit_action.trigger()
                self.assertEqual(
                    [callbacks[name].call_count for name in callback_names],
                    [1] * len(callback_names))
            finally:
                for timer in (window.timer, window.radar_timer,
                              window.assist_timer):
                    timer.stop()
        window.close()

    def test_pt_pt_menu_toolbar_and_dynamic_fuel_labels(self):
        catalogue = (Path(__file__).resolve().parents[1]
                     / 'translations' / 'rsm_pt_PT.qm')
        translator = QTranslator()
        self.assertTrue(translator.load(str(catalogue)))
        self.assertTrue(self.app.installTranslator(translator))
        self.addCleanup(self.app.removeTranslator, translator)

        window = MapperWindow(
            Path(self.temp.name) / 'portuguese-Status.json',
            game_running_check=lambda: True)
        self.addCleanup(window.close)
        for timer in (window.timer, window.radar_timer, window.assist_timer):
            timer.stop()
        self.assertEqual(
            [action.text() for action in window.menuBar().actions()],
            ['Mapas', 'Pesquisa de Mercados', 'Opções', 'Ajuda', 'Sair'])
        self.assertEqual(
            [action.text() for action in window.maps_menu.actions()],
            ['Abrir', 'Abrir de ficheiro…', 'Guardar', 'Novo', 'Ver e gerir'])
        self.assertEqual(
            [window.op_buttons[key].text() for key in
             (OP_MARK, OP_MARK_DEPOSIT, OP_MARK_RIG)],
            ['Marca', 'Depósito', 'Equipamento'])
        self.assertEqual(window.search_button.text(), 'Iniciar pesquisa')
        self.assertEqual(window.skip_button.text(), 'Saltar seguinte')
        self.assertEqual(window.overlay_button.text(), 'Sobreposição')
        self.assertEqual(window.follow.text(), 'Centrar')
        self.assertEqual(window.assist_button.text(),
                         'Assistência de direção [F8]')
        self.assertEqual(window.airlift_config_button.text(),
                         'Configurar Airlift')
        self.assertEqual(window.info_right.text(), 'COMBUSTÍVEL : —')

        window.state.fuel_percent = 64.6
        window.refresh(redraw_map=False)
        self.assertEqual(window.info_right.text(), 'COMBUSTÍVEL : 65% ✓ Normal')
        window.state.search_started = True
        window.refresh(redraw_map=False)
        self.assertEqual(window.search_button.text(), 'Parar pesquisa')

        messages = ElementTree.parse(
            Path(__file__).resolve().parents[1]
            / 'translations' / 'rsm_pt_PT.ts').getroot()
        contexts = {
            context.findtext('name'): {
                message.findtext('source'): message.findtext('translation')
                for message in context.findall('message')
            }
            for context in messages.findall('context')
        }
        self.assertEqual(contexts['SteeringUI']['Steering assistance [F8]'],
                         'Assistência de direção [F8]')

    def test_toolbar_button_height_preference_applies_to_both_rows(self):
        w = self.window
        w.resize_buttons(41)
        self.assertTrue(all(widget.height() == 41
                            for widget in w.toolbar_buttons))
        self.assertEqual(w.search_button.text(), 'Start search')
        self.assertEqual(w.skip_button.text(), 'Skip next')
        self.assertEqual(w.assist_button.text(), 'Steering assistance [F8]')

    def test_market_research_uses_retained_coordinator_and_main_shutdown(self):
        coordinator = self.window.surface_mining_coordinator
        self.assertIsInstance(coordinator, SurfaceMiningCoordinator)

        with patch("market_research_window.MarketResearchWindow.initialize"):
            self.window.show_market_research()
            first_window = self.window.market_research
            self.window.show_market_research()

        self.assertIs(self.window.market_research, first_window)
        self.assertIs(first_window.coordinator, coordinator)

        with patch.object(coordinator, "shutdown") as shutdown:
            first_window.close()
            self.app.processEvents()
            shutdown.assert_not_called()
            self.window.close()
            shutdown.assert_called_once_with()

    def test_market_research_opening_without_known_system_does_not_search(self):
        coordinator = self.window.surface_mining_coordinator
        coordinator.request_snapshot = Mock()
        with patch("market_research_window.MarketResearchWindow.update_inara"):
            self.window.show_market_research()

        research = self.window.market_research
        self.assertEqual(research.system.text(), "")
        coordinator.request_snapshot.assert_not_called()
        self.assertEqual(
            research.inara_cache_path,
            self.window.options_path.parent / "inara_summary_cache_v1.json",
        )

    def test_market_research_opening_with_known_system_starts_one_normal_search(self):
        self.window._observe_system("Kappa")
        coordinator = self.window.surface_mining_coordinator
        coordinator.request_snapshot = Mock(return_value=71)
        with patch("market_research_window.MarketResearchWindow.update_inara"):
            self.window.show_market_research()

        research = self.window.market_research
        self.assertEqual(research.system.text(), "Kappa")
        coordinator.request_snapshot.assert_called_once_with("Kappa", force=False)

    def test_offline_transition_preserves_session_last_known_system(self):
        self.window._observe_system("Kappa")
        self.window.live_status = {"StarSystem": "Kappa"}
        self.window.status_valid = True

        self.window.set_offline()

        self.assertEqual(self.window.current_system(), "Kappa")
        self.assertEqual(self.window.live_status, {})

    def test_journal_fallback_updates_session_last_known_system(self):
        from elite_dangerous.journal import JournalIdentity

        self.window.journal_identity.current_identity = Mock(
            return_value=JournalIdentity(system="Lave"))
        self.window.game_is_running = Mock(return_value=True)
        self.window.status_valid = True
        self.window.live_status = {"BodyName": "Different body", "Flags": 0}
        self.window.state.body = "Current body"
        self.window.refresh = Mock()
        self.window.evaluate_status_update = Mock()
        with patch(
            "rhino_surface_mapper_qt.read_status_if_changed",
            return_value=None,
        ):
            self.window.poll()

        self.assertEqual(self.window.current_system(), "Lave")

    def test_commander_movement_does_not_change_open_research_context_or_search(self):
        self.window._observe_system("Kappa")
        with patch("market_research_window.MarketResearchWindow.initialize"):
            self.window.show_market_research()
        research = self.window.market_research
        research.system.setText("Sol")
        coordinator = self.window.surface_mining_coordinator
        coordinator.request_snapshot = Mock()

        self.window._observe_system("Lave")

        self.assertEqual(self.window.current_system(), "Lave")
        self.assertEqual(research.system.text(), "Sol")
        coordinator.request_snapshot.assert_not_called()

    def test_retained_market_research_reopening_preserves_user_state(self):
        with patch("market_research_window.MarketResearchWindow.initialize") as initialize:
            self.window.show_market_research()
            research = self.window.market_research
            research.system.setText("Sol")
            research.top_products.setValue(5)
            research.status.setText("Ready — Sol")
            research.results.setPlainText("Existing results")
            self.window.show_market_research()

        self.assertIs(self.window.market_research, research)
        initialize.assert_called_once_with()
        self.assertEqual(research.system.text(), "Sol")
        self.assertEqual(research.top_products.value(), 5)
        self.assertEqual(research.status.text(), "Ready — Sol")
        self.assertEqual(research.results.toPlainText(), "Existing results")

    def test_session_last_known_system_ignores_empty_updates_and_replaces_valid_value(self):
        self.assertIsNone(self.window.current_system())
        self.window._observe_system("  Kappa  ")
        self.assertEqual(self.window.current_system(), "Kappa")
        self.window._observe_system(None)
        self.window._observe_system("  ")
        self.assertEqual(self.window.current_system(), "Kappa")
        self.window._observe_system("Lave")
        self.assertEqual(self.window.current_system(), "Lave")

    def test_new_system_observation_prefetches_once_and_changes_prefetch_target(self):
        prefetch = self.window.surface_mining_coordinator.prefetch_snapshot

        self.window._observe_system("  Kappa  ")
        self.window._observe_system("Kappa")
        self.window._observe_system("Lave")

        self.assertEqual(
            [call.args[0] for call in prefetch.call_args_list],
            ["Kappa", "Lave"],
        )

    def test_preferences_preserve_existing_keys(self):
        w = self.window
        w.preferences['future_setting'] = 'preservar'
        field = w.options_panel.findChild(QSpinBox,'rhino_size')
        field.setValue(73)
        w.theme_selector.setCurrentText('Dark')
        saved = json.loads(w.options_path.read_text(encoding='utf-8'))
        self.assertEqual(saved['rhino_size'],73)
        self.assertEqual(saved['future_setting'],'preservar')
        self.assertEqual(saved['theme'],THEME_DARK)
        self.assertEqual(w.view.rhino_height,73)
        self.assertTrue(w.view.dark_theme)

    def test_theme_resolution_and_widget_stylesheet(self):
        w = self.window
        self.assertFalse(_theme_is_dark(THEME_LIGHT, Qt.ColorScheme.Dark))
        self.assertTrue(_theme_is_dark(THEME_DARK, Qt.ColorScheme.Light))
        self.assertTrue(_theme_is_dark(THEME_SYSTEM, Qt.ColorScheme.Dark))
        self.assertFalse(_theme_is_dark(THEME_SYSTEM, Qt.ColorScheme.Light))

        w.apply_theme('Light')
        self.assertFalse(w.view.dark_theme)
        self.assertIn('background: #edf1f4; color: #233448;', w.styleSheet())
        self.assertIn('background: #ffffff; border: 1px solid #cbd5dd;', w.styleSheet())
        self.assertIn('QMenu::item { padding: 4px 18px 4px 8px; }',
                      w.styleSheet())
        self.assertIn('QMenu::item:selected { background: #448b68;',
                      w.styleSheet())
        self.assertIn('QMenuBar::item:checked', w.styleSheet())

        w.apply_theme('Dark')
        self.assertTrue(w.view.dark_theme)
        self.assertIn('background: #202429; color: #edf1f5;', w.styleSheet())
        self.assertIn('background: #2c3239; border: 1px solid #46515d;', w.styleSheet())
        w.apply_theme('System')
        self.assertIn('QMenu::item { padding: 4px 18px 4px 8px; }',
                      w.styleSheet())

    def test_spin_arrows_with_mouse_in_both_themes(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QStyle, QStyleOptionSpinBox
        from PySide6.QtTest import QTest
        w = self.window
        w.options_action.setChecked(True)
        for theme in ('Light', 'Dark'):
            w.theme_selector.setCurrentText(theme)
            for title, (header, content) in w.option_sections.items():
                header.setChecked(True)
                for spin in content.findChildren(QSpinBox):
                    value = (spin.minimum()+spin.maximum())//2
                    spin.setValue(value)
                    w.options_panel.ensureWidgetVisible(spin)
                    self.app.processEvents()
                    option = QStyleOptionSpinBox()
                    spin.initStyleOption(option)
                    up = spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option, QStyle.SubControl.SC_SpinBoxUp, spin)
                    down = spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option, QStyle.SubControl.SC_SpinBoxDown, spin)
                    self.assertFalse(up.intersects(down), (title, up, down))
                    self.assertEqual(up.center().x(),down.center().x(),title)
                    self.assertLess(up.center().y(),down.center().y(),title)
                    QTest.mouseClick(spin,Qt.MouseButton.LeftButton,pos=up.center())
                    self.assertEqual(spin.value(),value+spin.singleStep(),(theme,title,spin.objectName()))
                    QTest.mouseClick(spin,Qt.MouseButton.LeftButton,pos=down.center())
                    self.assertEqual(spin.value(),value,(theme,title,spin.objectName()))
                header.setChecked(False)

    def test_dark_map_uses_selected_background(self):
        from unittest.mock import patch
        from PySide6.QtGui import QColor
        w = self.window
        w.preferences.pop('map_background',None)
        w.apply_theme('Dark')
        self.app.processEvents()
        self.assertEqual(w.view.grab().toImage().pixelColor(40,90).name(),'#606060')
        with patch('layout_options.QColorDialog.getColor',return_value=QColor('#8899aa')):
            w.color_buttons['map_background'].click()
        self.app.processEvents()
        self.assertEqual(w.view.grab().toImage().pixelColor(40,90).name(),'#8899aa')
        w.apply_theme('Light')
        w.apply_theme('Dark')
        self.assertEqual(w.view.colors['map_background'],'#8899aa')

        w.setting_fields['grid_color'][1]('#112233')
        w.apply_theme('Light')
        w.apply_theme('Dark')
        self.assertEqual(w.view.colors['grid_color'],'#112233')

    def test_scanned_area_uses_wave_color(self):
        w = self.window
        w.state.center_lat = 0
        w.state.center_lon = 0
        w.state.radar_coverage = [dict(x=0,y=0,radius=2000)]
        w.view.colors['wave_color'] = '#bb6633'
        self.app.processEvents()
        picture = w.view.grab().toImage()
        self.assertEqual(picture.pixelColor(picture.width()//2+40,picture.height()//2+40).name(),'#bb6633')

    def test_settings_export_import_and_reset(self):
        from unittest.mock import patch
        w = self.window
        target = Path(self.temp.name)/'preset.json'
        w.setting_fields[AIRLIFT_RADIUS_KEY][1](7)
        w.setting_fields[AIRLIFT_DEPLOYMENT_COUNT_KEY][1](18)
        w.setting_fields[AIRLIFT_FADE_SECONDS_KEY][1](10)
        w.preferences.update({
            AIRLIFT_RADIUS_KEY: w.airlift_radius_km,
            AIRLIFT_DEPLOYMENT_COUNT_KEY: w.airlift_deployment_count,
            AIRLIFT_FADE_SECONDS_KEY: w.airlift_fade_seconds,
        })
        w.setting_fields['rhino_size'][1](81)
        w.setting_fields['theme'][1]('Dark')
        w.setting_fields['wave_color'][1]('#123456')
        w.setting_fields['ship_size'][1](101)
        w.setting_fields['ship_color'][1]('#d3334c')
        with patch('layout_options.QFileDialog.getSaveFileName',return_value=(str(target),'')):
            w.export_settings()
        w.reset_settings()
        self.assertEqual(w.view.rhino_height,56)
        self.assertEqual(w.view.ship_width,72)
        self.assertEqual(w.view.ship_color,'#557194')
        self.assertEqual(w.theme_selector.currentText(),THEME_LABELS[THEME_SYSTEM])
        self.assertEqual(
            (w.airlift_radius_km, w.airlift_deployment_count,
             w.airlift_fade_seconds),
            (5, 10, 5),
        )
        with patch('layout_options.QFileDialog.getOpenFileName',return_value=(str(target),'')):
            w.import_settings()
        self.assertEqual(w.view.rhino_height,81)
        self.assertEqual(w.view.ship_width,101)
        self.assertEqual(w.view.ship_color,'#d3334c')
        self.assertEqual(w.view.colors['wave_color'],'#123456')
        self.assertEqual(w.theme_selector.currentText(),'Dark')
        self.assertEqual(
            (w.airlift_radius_km, w.airlift_deployment_count,
             w.airlift_fade_seconds),
            (7, 18, 10),
        )
        self.assertEqual(json.loads(w.options_path.read_text())['rhino_size'],81)
        self.assertEqual(json.loads(w.options_path.read_text())['ship_size'],101)
        saved = json.loads(w.options_path.read_text(encoding='utf-8'))
        self.assertEqual(saved[AIRLIFT_RADIUS_KEY], 7)
        self.assertEqual(saved[AIRLIFT_DEPLOYMENT_COUNT_KEY], 18)
        self.assertEqual(saved[AIRLIFT_FADE_SECONDS_KEY], 10)
        self.assertFalse(any('airlift' in key and 'active' in key
                             for key in saved))
        ship_size = w.findChild(QSpinBox, 'ship_size')
        self.assertEqual((ship_size.minimum(), ship_size.maximum()), (20, 160))
        self.assertFalse(w.setting_fields['ship_size'][2](19))
        self.assertFalse(w.setting_fields['ship_size'][2](161))
        self.assertFalse(w.setting_fields['ship_color'][2]('#888888'))
        target.write_text(json.dumps({'rhino_settings_version':1,'settings':{'rhino_size':75,'assist_speed':-1}}))
        with patch('layout_options.QFileDialog.getOpenFileName',return_value=(str(target),'')), patch('layout_options.QMessageBox.warning') as warning:
            w.import_settings()
        warning.assert_called_once()
        self.assertEqual(w.view.rhino_height,81)

    def test_airlift_preferences_default_and_persisted_values(self):
        from unittest.mock import patch

        with patch(
                'rhino_surface_mapper_qt.load_preferences',
                return_value={}):
            w = MapperWindow(
                Path(self.temp.name) / 'Status-airlift-defaults.json',
                game_running_check=lambda: True)
        try:
            for timer in (w.timer, w.radar_timer, w.assist_timer):
                timer.stop()
            w.options_path = Path(self.temp.name) / 'airlift-options.json'
            w.loading_settings = False
            self._assert_airlift_defaults_and_persistence(w)
        finally:
            w.close()

    def _assert_airlift_defaults_and_persistence(self, w):
        self.assertEqual(
            (w.airlift_radius_km, w.airlift_deployment_count,
             w.airlift_fade_seconds),
            (5, 10, 5),
        )
        self.assertFalse(any(
            key in w.preferences
            for key in ('airlift_active', 'airlift_enabled')
        ))

        w.setting_fields[AIRLIFT_RADIUS_KEY][1](7)
        self.assertEqual(w.airlift_deployment_count, 19)
        w.save_preference(AIRLIFT_RADIUS_KEY, 7)
        saved = json.loads(w.options_path.read_text(encoding='utf-8'))
        self.assertEqual(saved[AIRLIFT_RADIUS_KEY], 7)
        self.assertEqual(saved[AIRLIFT_DEPLOYMENT_COUNT_KEY], 19)

        for radius, count in (
                *((5, value) for value in range(6, 11)),
                *((7, value) for value in range(13, 20))):
            with self.subTest(radius=radius, count=count):
                w.setting_fields[AIRLIFT_RADIUS_KEY][1](radius)
                w.setting_fields[AIRLIFT_DEPLOYMENT_COUNT_KEY][1](count)
                w.preferences[AIRLIFT_RADIUS_KEY] = radius
                w.preferences[AIRLIFT_DEPLOYMENT_COUNT_KEY] = count
                w.save_preference(AIRLIFT_FADE_SECONDS_KEY, 0)
                saved = json.loads(w.options_path.read_text(encoding='utf-8'))
                self.assertEqual(saved[AIRLIFT_RADIUS_KEY], radius)
                self.assertEqual(saved[AIRLIFT_DEPLOYMENT_COUNT_KEY], count)
                self.assertEqual(saved[AIRLIFT_FADE_SECONDS_KEY], 0)
                reloaded = normalize_airlift_preferences(
                    load_preferences(w.options_path))
                self.assertEqual(reloaded[AIRLIFT_RADIUS_KEY], radius)
                self.assertEqual(reloaded[AIRLIFT_DEPLOYMENT_COUNT_KEY], count)
                self.assertEqual(reloaded[AIRLIFT_FADE_SECONDS_KEY], 0)
                w.preferences[AIRLIFT_RADIUS_KEY] = 5
                w.preferences[AIRLIFT_DEPLOYMENT_COUNT_KEY] = 10
                w.preferences[AIRLIFT_FADE_SECONDS_KEY] = 5
                w.airlift_radius_km = 5
                w.airlift_deployment_count = 10
                w.airlift_fade_seconds = 5

    def test_valid_airlift_preferences_are_applied_at_startup(self):
        from unittest.mock import patch

        for index, (radius, count) in enumerate(((5, 6), (7, 19))):
            with self.subTest(radius=radius, count=count), patch(
                    'rhino_surface_mapper_qt.load_preferences',
                    return_value={
                        AIRLIFT_RADIUS_KEY: radius,
                        AIRLIFT_DEPLOYMENT_COUNT_KEY: count,
                        AIRLIFT_FADE_SECONDS_KEY: 10,
                    }):
                window = MapperWindow(
                    Path(self.temp.name) / f'Status-valid-{index}.json',
                    game_running_check=lambda: True)
                try:
                    self.assertEqual(
                        (window.airlift_radius_km,
                         window.airlift_deployment_count,
                         window.airlift_fade_seconds),
                        (radius, count, 10),
                    )
                    self.assertTrue(hasattr(window, 'airlift_active'))
                    self.assertFalse(window.airlift_active)
                    self.assertNotIn('airlift_active', window.preferences)
                    self.assertNotIn('airlift_active', window.setting_fields)
                finally:
                    window.close()

    def test_invalid_loaded_airlift_preferences_recover_to_valid_defaults(self):
        from unittest.mock import patch

        cases = (
            {AIRLIFT_RADIUS_KEY: 5, AIRLIFT_DEPLOYMENT_COUNT_KEY: 11},
            {AIRLIFT_RADIUS_KEY: 7, AIRLIFT_DEPLOYMENT_COUNT_KEY: 20},
            {AIRLIFT_RADIUS_KEY: 7, AIRLIFT_DEPLOYMENT_COUNT_KEY: 21},
            {AIRLIFT_RADIUS_KEY: True, AIRLIFT_DEPLOYMENT_COUNT_KEY: 10},
            {AIRLIFT_RADIUS_KEY: 7, AIRLIFT_DEPLOYMENT_COUNT_KEY: True},
            {AIRLIFT_RADIUS_KEY: 7, AIRLIFT_DEPLOYMENT_COUNT_KEY: 10},
            {AIRLIFT_FADE_SECONDS_KEY: 11},
            {AIRLIFT_FADE_SECONDS_KEY: True},
        )
        for index, preferences in enumerate(cases):
            with self.subTest(preferences=preferences), patch(
                    'rhino_surface_mapper_qt.load_preferences',
                    return_value=preferences):
                window = MapperWindow(
                    Path(self.temp.name) / f'Status-{index}.json',
                    game_running_check=lambda: True)
                try:
                    self.assertIn(window.airlift_radius_km, (5, 7))
                    self.assertTrue(
                        window.setting_fields[AIRLIFT_DEPLOYMENT_COUNT_KEY][2](
                            window.airlift_deployment_count))
                    self.assertTrue(
                        window.setting_fields[AIRLIFT_FADE_SECONDS_KEY][2](
                            window.airlift_fade_seconds))
                    self.assertNotIn('airlift_active', window.preferences)
                    self.assertNotIn('airlift_enabled', window.preferences)
                finally:
                    window.close()

    def test_operation_and_section_identity_is_not_display_text(self):
        w = self.window
        button = w.op_buttons[OP_MARK]
        w.op_buttons[OP_MARK].setText('Texto alterado')
        self.assertIs(w.op_buttons[OP_MARK], button)

        header, content = w.option_sections[SECTION_LAYOUT]
        header.setText('Título alterado')
        w.setting_fields['font_size'][1](11)
        for callback in w.option_resets[SECTION_LAYOUT]:
            callback()
        self.assertEqual(w.setting_fields['font_size'][0](),9)
        self.assertEqual(header.text(),'Título alterado')

    def test_theme_uses_stable_values_and_accepts_legacy_label(self):
        w = self.window
        w.theme_selector.setCurrentText('Light')
        w.theme_selector.setCurrentText('Dark')
        self.assertEqual(w.theme_selector.currentData(), THEME_DARK)
        self.assertEqual(json.loads(w.options_path.read_text(encoding='utf-8'))['theme'], THEME_DARK)

        w.setting_fields['theme'][1]('Como o Windows')
        self.assertEqual(w.theme_selector.currentData(), THEME_SYSTEM)
        self.assertTrue(w.setting_fields['theme'][2]('Como o Windows'))
        self.assertTrue(w.setting_fields['theme'][2](THEME_LIGHT))

    def test_language_selector_uses_stable_codes_and_persists_selection(self):
        from PySide6.QtWidgets import QComboBox
        options_path = Path(self.temp.name) / 'language-options.json'
        with patch(
            'rhino_surface_mapper_qt.load_preferences',
            return_value={'language': 'en_GB'},
        ):
            w = MapperWindow(
                Path(self.temp.name) / 'Status-language.json',
                game_running_check=lambda: True,
            )
        try:
            for timer in (w.timer, w.radar_timer, w.assist_timer):
                timer.stop()
            w.options_path = options_path
            w.loading_settings = False
            selector = w.options_panel.findChild(QComboBox, 'language_selector')
            self.assertIsNotNone(selector)
            self.assertEqual(selector.findData('en_GB') >= 0, True)
            self.assertEqual(selector.findData('pt_PT') >= 0, True)
            selector.setCurrentIndex(selector.findData('en_GB'))
            selector.setCurrentIndex(selector.findData('pt_PT'))
            self.assertEqual(selector.currentData(), 'pt_PT')
            self.assertEqual(
                json.loads(options_path.read_text(encoding='utf-8'))['language'],
                'pt_PT',
            )
        finally:
            w.close()

    def test_legacy_persisted_theme_loads_as_system_theme(self):
        from unittest.mock import patch
        with patch('rhino_surface_mapper_qt.load_preferences', return_value={'theme': 'Como o Windows'}):
            window = MapperWindow(
                Path(self.temp.name)/'Status-legacy.json', game_running_check=lambda: True)
        try:
            for timer in (window.timer,window.radar_timer,window.assist_timer):
                timer.stop()
            self.assertEqual(window.preferences['theme'], THEME_SYSTEM)
            self.assertEqual(window.theme_selector.currentData(), THEME_SYSTEM)
        finally:
            window.close()

    def test_stable_persisted_theme_loads_directly(self):
        from unittest.mock import patch
        with patch('rhino_surface_mapper_qt.load_preferences', return_value={'theme': THEME_DARK}):
            window = MapperWindow(
                Path(self.temp.name)/'Status-stable.json', game_running_check=lambda: True)
        try:
            for timer in (window.timer,window.radar_timer,window.assist_timer):
                timer.stop()
            self.assertEqual(window.preferences['theme'], THEME_DARK)
            self.assertEqual(window.theme_selector.currentData(), THEME_DARK)
            self.assertTrue(window.view.dark_theme)
        finally:
            window.close()
