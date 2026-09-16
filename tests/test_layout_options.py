"""Contrato do layout: botões fixos e preferências sem perder outros campos."""
import json
import os
import tempfile
import unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication, QPushButton, QSpinBox
from rhino_surface_mapper_qt import MapperWindow


class LayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.window = MapperWindow(Path(self.temp.name)/'Status.json')
        self.window.options_path = Path(self.temp.name)/'options.json'
        for timer in (self.window.timer,self.window.radar_timer,self.window.assist_timer):
            timer.stop()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.temp.cleanup()

    def test_fixed_buttons_and_map_expand(self):
        w = self.window
        sizes = [b.size() for b,_ in w.fixed_buttons]
        w.resize(1600,950)
        self.app.processEvents()
        self.assertEqual(sizes,[b.size() for b,_ in w.fixed_buttons])
        width = w.view.width()
        w.options_button.setChecked(True)
        self.app.processEvents()
        self.assertLess(w.view.width(),width)
        self.assertTrue(all(not header.isChecked() for header,_ in w.option_sections.values()))
        w.options_button.setChecked(False)
        self.app.processEvents()
        self.assertEqual(w.view.width(),width)
        menu = w.findChild(QPushButton,'maps_menu').menu()
        self.assertEqual([a.text() for a in menu.actions()],['Abrir','Guardar','Novo','Ver e manter'])

    def test_preferences_preserve_existing_keys(self):
        w = self.window
        w.preferences['future_setting'] = 'preservar'
        field = w.options_panel.findChild(QSpinBox,'rhino_size')
        field.setValue(73)
        w.theme_selector.setCurrentText('Dark')
        saved = json.loads(w.options_path.read_text(encoding='utf-8'))
        self.assertEqual(saved['rhino_size'],73)
        self.assertEqual(saved['future_setting'],'preservar')
        self.assertEqual(saved['theme'],'Dark')
        self.assertEqual(w.view.rhino_height,73)
        self.assertTrue(w.view.dark_theme)

    def test_spin_arrows_with_mouse_in_both_themes(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QStyle, QStyleOptionSpinBox
        from PyQt6.QtTest import QTest
        w = self.window
        w.options_button.setChecked(True)
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
        from PyQt6.QtGui import QColor
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
        w.setting_fields['rhino_size'][1](81)
        w.setting_fields['theme'][1]('Dark')
        w.setting_fields['wave_color'][1]('#123456')
        with patch('layout_options.QFileDialog.getSaveFileName',return_value=(str(target),'')):
            w.export_settings()
        w.reset_settings()
        self.assertEqual(w.view.rhino_height,56)
        self.assertEqual(w.theme_selector.currentText(),'Como o Windows')
        with patch('layout_options.QFileDialog.getOpenFileName',return_value=(str(target),'')):
            w.import_settings()
        self.assertEqual(w.view.rhino_height,81)
        self.assertEqual(w.view.colors['wave_color'],'#123456')
        self.assertEqual(w.theme_selector.currentText(),'Dark')
        self.assertEqual(json.loads(w.options_path.read_text())['rhino_size'],81)
        target.write_text(json.dumps({'rhino_settings_version':1,'settings':{'rhino_size':75,'assist_speed':-1}}))
        with patch('layout_options.QFileDialog.getOpenFileName',return_value=(str(target),'')), patch('layout_options.QMessageBox.warning') as warning:
            w.import_settings()
        warning.assert_called_once()
        self.assertEqual(w.view.rhino_height,81)
