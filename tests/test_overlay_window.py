"""Qt overlay interaction tests runnable without a physical display."""

import os
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication
    from pyqt_overlay import OverlayWindow
except ImportError:
    QApplication = None


@unittest.skipUnless(QApplication is not None, "PySide6 não está instalado")
class OverlayWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.overlay = OverlayWindow()
        self.overlay.setGeometry(100, 100, 360, 150)

    def tearDown(self):
        self.overlay.close()

    def test_hit_test_identifies_edges_and_interior(self):
        self.assertEqual(self.overlay.hit_test(QPoint(0, 0)), "nw")
        self.assertEqual(self.overlay.hit_test(QPoint(359, 149)), "se")
        self.assertEqual(self.overlay.hit_test(QPoint(180, 75)), "move")

    def test_resize_keeps_the_expected_aspect_ratio(self):
        for mode, point in (("se", QPoint(560, 350)), ("n", QPoint(280, 20)), ("w", QPoint(20, 175))):
            with self.subTest(mode=mode):
                self.overlay.setGeometry(100, 100, 360, 150)
                self.overlay.resize_mode = mode
                self.overlay.start_geometry = self.overlay.geometry()
                self.overlay.press_global = QPoint(100, 100)
                self.overlay.resize_proportional(point)
                self.assertGreaterEqual(self.overlay.width(), 180)
                self.assertAlmostEqual(self.overlay.width() / self.overlay.height(), 2.4, delta=0.03)

    def test_navigation_state_is_retained_for_painting(self):
        self.overlay.set_navigation("090° >>>", "250 m", "#ffd21c", "white")
        self.assertEqual(self.overlay.heading_text, "090° >>>")
        self.assertEqual(self.overlay.distance_text, "250 m")


if __name__ == "__main__":
    unittest.main()
