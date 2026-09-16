"""Teste do ciclo Qt real num processo separado (sem Tk/Tcl)."""
import importlib.util
import unittest
from recovery_tkinter.overlay_process import OverlayProcess


@unittest.skipUnless(importlib.util.find_spec("PyQt6"), "PyQt6 não está instalado")
class OverlayProcessTests(unittest.TestCase):
    def test_process_navigation_visibility_and_shutdown(self):
        overlay = OverlayProcess()
        try:
            self.assertTrue(overlay.process.is_alive())
            overlay.set_navigation('090° >>>', '250 m', '#ffd21c', 'white')
            overlay.hide()
            self.assertFalse(overlay.isVisible())
            overlay.show()
            self.assertTrue(overlay.isVisible())
        finally:
            overlay.close()
        self.assertFalse(overlay.process.is_alive())
        overlay.close()
