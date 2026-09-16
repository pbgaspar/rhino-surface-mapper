import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

@unittest.skipUnless(importlib.util.find_spec('PyQt6'), 'PyQt6 não instalado')
class MapOperationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from rhino_surface_mapper_qt import MapperWindow
        self.temp = tempfile.TemporaryDirectory()
        self.window = MapperWindow(Path(self.temp.name)/'Status.json')
        self.window.timer.stop()
        self.window.state.process_status(dict(Flags=0x04000000,Latitude=38,Longitude=-9,Heading=0,BodyName='Test'))

    def tearDown(self):
        self.window.close()
        self.temp.cleanup()

    def test_deposit_duplicate_edit_rig_cancel_and_delete(self):
        from PyQt6.QtCore import QPointF
        from PyQt6.QtWidgets import QMessageBox
        w = self.window
        with patch.object(w,'edit_deposit_values',return_value=dict(name='A',size='Grande',rigs=3)):
            w.mark_deposit()
        self.assertEqual(len(w.state.deposits),1)
        with patch('qt_map_operations.QMessageBox.information') as info:
            w.mark_deposit()
            info.assert_called_once()
        item = w.state.deposits[0]
        with patch.object(w,'edit_deposit_values',return_value=None):
            w.edit_deposit(item)
        self.assertEqual(item['name'],'A')
        with patch.object(w,'edit_deposit_values',return_value=dict(name='B',size='Médio',rigs=2)):
            w.edit_deposit(item)
        self.assertEqual(item['name'],'B')
        self.assertIs(w.view.marker_at(w.view.screen(item['x'],item['y']))[1],item)
        w.mark_rig()
        w.cancel_placement()
        w.place_rig(QPointF(100,100))
        self.assertEqual(w.state.rigs,[])
        w.mark_rig()
        w.place_rig(QPointF(100,100))
        w.place_rig(QPointF(200,200))
        self.assertEqual(len(w.state.rigs),1)
        with patch('qt_map_operations.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):
            w.delete_marker('deposits',item)
        self.assertEqual(w.state.deposits,[])

    def test_save_load_round_trip_and_invalid_file_preserves_map(self):
        from PyQt6.QtWidgets import QMessageBox
        w = self.window
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/'map.json')
            w.state.start_search()
            expected = w.state.to_dict()
            with patch('qt_map_operations.QFileDialog.getSaveFileName',return_value=(path,'')):
                w.save_map()
            with patch('qt_map_operations.QFileDialog.getOpenFileName',return_value=(path,'')), patch('qt_map_operations.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):
                w.load_map()
            # A abertura migra as datas ausentes dos mapas antigos.
            self.assertIsNotNone(w.state.created_at)
            self.assertIsNotNone(w.state.last_saved_at)
            expected.update(created_at=w.state.created_at, last_saved_at=w.state.last_saved_at)
            self.assertEqual(w.state.to_dict(),expected)
            old = w.state
            Path(path).write_text('{',encoding='utf-8')
            with patch('qt_map_operations.QFileDialog.getOpenFileName',return_value=(path,'')), patch('qt_map_operations.QMessageBox.critical') as error:
                w.load_map()
                error.assert_called_once()
            self.assertIs(w.state,old)
            with patch('qt_map_operations.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes), \
                    patch.object(w, 'save_new_pml_version', return_value=Path(path)):
                w.new_map()
            self.assertFalse(w.state.search_started)
            self.assertFalse(w.overlay.isVisible())
            self.assertFalse(w.overlay_button.isEnabled())
    def test_load_rereads_unchanged_status_immediately(self):
        import json
        from PyQt6.QtWidgets import QMessageBox
        w = self.window
        with tempfile.TemporaryDirectory() as directory:
            status_path = Path(directory)/'Status.json'
            map_path = Path(directory)/'map.json'
            status_path.write_text(json.dumps(dict(Flags=0x04000000,Latitude=38,Longitude=-9,Heading=90,BodyName='Test',Fuel=dict(FuelReservoir=0.4))),encoding='utf-8')
            w.status_path = status_path
            w.poll()
            w.state.start_search()
            w.state.save(map_path)
            stamp = w.last_mtime
            with patch('qt_map_operations.QFileDialog.getOpenFileName',return_value=(str(map_path),'')), patch('qt_map_operations.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):
                w.load_map()
            self.assertEqual(w.last_mtime,stamp)
            self.assertEqual(w.state.rhino_lat,38)
            self.assertEqual(w.state.rhino_heading,90)
            self.assertEqual(w.state.fuel_percent,50)
            self.assertIn('50%',w.info_right.text())
            self.assertTrue(w.state.search_started)
            self.assertIsNotNone(w.state.next_target_xy)

    def test_mark_position_persistence_rename_and_delete(self):
        from mapper_core import MapperState
        from PyQt6.QtCore import QPointF
        from PyQt6.QtWidgets import QMessageBox
        w = self.window
        for azimuth, expected_x, expected_y in [(0, 0, 1000), (90, 1000, 0), (180, 0, -1000), (270, -1000, 0)]:
            with patch.object(w, 'edit_mark_values', return_value=dict(name='Local', azimuth=azimuth, distance=1000)):
                w.mark()
            item = w.state.marks[-1]
            self.assertAlmostEqual(item['x'], expected_x, delta=1)
            self.assertAlmostEqual(item['y'], expected_y, delta=1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'marks.json'
            w.state.save(path)
            restored = MapperState()
            restored.load(path)
            self.assertEqual(restored.marks, w.state.marks)
        with patch.object(w, 'edit_mark_values', return_value=dict(name='Novo nome', azimuth=90, distance=2000)):
            w.alter_mark(item)
        self.assertAlmostEqual(item['x'], 2000, delta=1)
        self.assertAlmostEqual(item['y'], 0, delta=1)
        self.assertEqual(item['name'], 'Novo nome')
        bounds = w.view.mark_bounds(item)
        self.assertIs(w.view.marker_at(QPointF(bounds.right()-3, bounds.center().y()))[1], item)
        w.view.grab()  # Executa o desenho vetorial e do nome em offscreen.
        with patch('qt_map_operations.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            w.delete_marker('marks', item)
        self.assertEqual(len(w.state.marks), 3)
        w.state.new_map()
        self.assertEqual(w.state.marks, [])

    def test_mark_cancel_and_body_change(self):
        w = self.window
        with patch.object(w, 'edit_mark_values', return_value=None):
            w.mark()
        self.assertEqual(w.state.marks, [])
        def change_body():
            w.state.process_status(dict(Flags=0x04000000, Latitude=38, Longitude=-9, Heading=0, BodyName='Other'))
            return dict(name='Local', azimuth=0, distance=100)
        with patch.object(w, 'edit_mark_values', side_effect=change_body):
            w.mark()
        self.assertEqual(w.state.marks, [])

    def test_alter_mark_cancel_and_name_only_preserve_position(self):
        w = self.window
        with patch.object(w, 'edit_mark_values', return_value=dict(name='A', azimuth=37, distance=1234.56)):
            w.mark()
        item = w.state.marks[0]
        original = dict(item)
        with patch.object(w, 'edit_mark_values', return_value=None):
            w.alter_mark(item)
        self.assertEqual(item, original)
        def rename(existing):
            return dict(existing, name='B')
        with patch.object(w, 'edit_mark_values', side_effect=rename):
            w.alter_mark(item)
        self.assertEqual(item, dict(original, name='B'))

    def test_real_mark_dialog_preserves_fractional_and_long_distances(self):
        from qt_map_operations import MarkDialog
        w = self.window
        for distance in (1234.56, 123456.78):
            with patch.object(w, 'edit_mark_values', return_value=dict(name='A', azimuth=37, distance=distance)):
                w.mark()
            item = w.state.marks[-1]
            original = dict(item)
            def rename(existing):
                dialog = MarkDialog(w, existing)
                dialog.name.setText('B')
                result = dialog.values()
                dialog.close()
                return result
            with patch.object(w, 'edit_mark_values', side_effect=rename):
                w.alter_mark(item)
            self.assertEqual(item, dict(original, name='B'))
            def move(existing):
                dialog = MarkDialog(w, existing)
                dialog.distance.setValue(500)
                dialog.azimuth.setValue(90)
                result = dialog.values()
                dialog.close()
                return result
            with patch.object(w, 'edit_mark_values', side_effect=move):
                w.alter_mark(item)
            self.assertNotEqual(item['x'], original['x'])
