"""Testes unitários para a funcionalidade Navegar em marcas e objetos com pausa de busca."""

import math
import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from mapper_core import MapperState, SRV_FLAG


def sample_status(**changes):
    base = {
        "Flags": SRV_FLAG,
        "Latitude": 38.0,
        "Longitude": -9.0,
        "Heading": 0.0,
        "PlanetRadius": 6_371_000.0,
        "StarSystem": "Teste",
        "BodyName": "A 1",
        "Fuel": {"FuelReservoir": 0.8},
    }
    base.update(changes)
    return base


class NavigationMarkerTests(unittest.TestCase):
    def setUp(self):
        self.state = MapperState()
        self.state.process_status(sample_status())

    def test_overlay_allowed_when_navigating_to_target_without_search(self):
        self.assertFalse(self.state.overlay_allowed())
        self.state.active_nav_target = {
            "type": "marks",
            "name": "[Marca] Teste",
            "x": 0.0,
            "y": 500.0,
        }
        self.assertTrue(self.state.overlay_allowed())
        self.state.active_nav_target = None
        self.assertFalse(self.state.overlay_allowed())

    def test_overlay_navigation_calculates_bearing_distance_and_target_name(self):
        # Alvo a 1000 metros a Norte (Y = +1000) do Rhino (0, 0)
        self.state.active_nav_target = {
            "type": "marks",
            "name": "[Marca] Alfa",
            "x": 0.0,
            "y": 1000.0,
        }
        heading, distance, color, dist_color, target_name = self.state.overlay_navigation()
        self.assertEqual(heading, "000°")
        self.assertEqual(distance, "1000 m")
        self.assertEqual(color, "#00cc44")
        self.assertEqual(target_name, "[Marca] Alfa")

    def test_search_pauses_when_navigating_and_stores_pause_point(self):
        self.state.start_search(0)
        self.assertTrue(self.state.search_started)
        self.assertFalse(self.state.search_paused)
        self.assertIsNone(self.state.search_pause_point)

        # Simular início de navegação para uma marca
        rhino_x, rhino_y = self.state.llxy(self.state.rhino_lat, self.state.rhino_lon)
        self.state.search_paused = True
        self.state.search_pause_point = (rhino_x, rhino_y)
        self.state.active_nav_target = {
            "type": "marks",
            "name": "[Marca] Mina",
            "x": 500.0,
            "y": 500.0,
        }

        self.assertTrue(self.state.search_paused)
        self.assertEqual(self.state.search_pause_point, (rhino_x, rhino_y))

        # Overlay deve apontar para a marca e não para a busca
        _, _, _, _, name = self.state.overlay_navigation()
        self.assertEqual(name, "[Marca] Mina")

    def test_arrival_within_100m_transitions_to_return_to_pause(self):
        pause_xy = (0.0, 0.0)
        mark_target = {"type": "marks", "name": "[Marca] Destino", "x": 50.0, "y": 50.0}
        self.state.search_started = True
        self.state.search_paused = True
        self.state.search_pause_point = pause_xy
        self.state.active_nav_target = mark_target

        # Posicionar Rhino a 50m do alvo (distância <= 100m)
        self.state.rhino_lat, self.state.rhino_lon = self.state.xyll(50.0, 50.0)
        self.state.overlay_navigation()

        # O alvo ativo deve ter sido limpo e ativado o regresso ao ponto de pausa
        self.assertIsNone(self.state.active_nav_target)
        self.assertTrue(self.state.return_to_pause)

        # Próxima chamada de overlay deve apontar para o ponto de pausa
        _, _, _, _, name = self.state.overlay_navigation()
        self.assertEqual(name, "Ponto de Pausa ⏸")

    def test_arrival_at_pause_point_resumes_search(self):
        self.state.start_search(0)
        self.state.search_paused = True
        self.state.return_to_pause = True
        self.state.search_pause_point = (0.0, 0.0)

        # Rhino chega ao ponto de pausa (0, 0)
        self.state.rhino_lat, self.state.rhino_lon = self.state.xyll(0.0, 0.0)
        self.state.overlay_navigation()

        # Deve sair do modo de pausa e retomar a rota de busca normal
        self.assertFalse(self.state.return_to_pause)
        self.assertFalse(self.state.search_paused)
        self.assertIsNone(self.state.search_pause_point)

        _, _, _, _, name = self.state.overlay_navigation()
        self.assertTrue(name.startswith("Busca: Ponto"))

    def test_overlay_disallowed_when_commander_exits_rhino(self):
        self.state.start_search(0)
        self.assertTrue(self.state.overlay_allowed())

        # Comandante sai do Rhino (Flags sem SRV_FLAG)
        self.state.process_status(sample_status(Flags=0))
        self.assertFalse(self.state.in_srv)
        self.assertFalse(self.state.overlay_allowed())

        # Comandante volta a entrar no Rhino
        self.state.process_status(sample_status())
        self.assertTrue(self.state.in_srv)
        self.assertTrue(self.state.overlay_allowed())


if __name__ == "__main__":
    unittest.main()

