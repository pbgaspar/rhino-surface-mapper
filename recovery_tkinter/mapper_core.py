"""Núcleo independente da interface do Rhino Surface Mapper.

Este módulo contém as regras de estado, mapa e navegação. Não importa Tkinter
nem PyQt6 para poder ser testado isoladamente e reutilizado pela futura janela
PyQt6.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any


# Flags é um conjunto de bits enviado pelo jogo. Este bit identifica uso do SRV.
SRV_FLAG = 0x04000000
DEFAULT_RADIUS_M = 6_371_000.0
SEARCH_RADIUS_M = 3_500.0
SEARCH_SPACING_M = 1_800.0


class MapperState:
    """Estado e operações do mapa, independente de qualquer toolkit gráfico."""

    def __init__(self) -> None:
        """Inicializa os dados de telemetria, mapa e busca sem criar qualquer interface.
        None significa ainda não conhecido; listas vazias significam ausência de registos."""
        self.status_path: Path | None = None
        self.points: list[dict[str, Any]] = []
        self.deposits: list[dict[str, Any]] = []
        self.rigs: list[dict[str, Any]] = []
        self.system = ""
        self.body = ""
        self.body_key: str | None = None
        self.center_lat: float | None = None
        self.center_lon: float | None = None
        self.radius = DEFAULT_RADIUS_M
        self.last_xy: tuple[float, float] | None = None
        self.rhino_lat: float | None = None
        self.rhino_lon: float | None = None
        self.rhino_heading: float | None = None
        self.fuel_reservoir: float | None = None
        self.fuel_percent: float | None = None
        self.fuel_low = False
        self.coverage_width_m = 2_000.0
        self.scanner_range_m = 2_000.0
        self.center_enabled = False
        self.search_started = False
        self.datum_lat: float | None = None
        self.datum_lon: float | None = None
        self.route_index = 0
        self.next_target_xy: tuple[float, float] | None = None
        self.route_history: list[dict[str, Any]] = []
        self.overlay_blink_on = True
        self.overlay_next_blink = 0.0

    def overlay_allowed(self) -> bool:
        """Modos que autorizam o overlay; acrescentar futuros modos aqui."""
        return bool(self.search_started)

    @staticmethod
    def heading_error(current: float, target: float) -> float:
        """Diferença angular assinada; negativo indica virar à esquerda."""
        # O módulo (%) faz a passagem 359°/000° e escolhe um erro em [-180,180[.
        return (target - current + 540.0) % 360.0 - 180.0

    def llxy(self, lat: float, lon: float) -> tuple[float, float]:
        """Converte latitude/longitude para metros relativos ao centro."""
        if self.center_lat is None or self.center_lon is None:
            raise RuntimeError("O centro do mapa ainda não foi definido.")
        # Aproximação local: um grau de longitude corresponde a menos metros
        # à medida que a latitude se afasta do equador (fator coseno).
        cosine = math.cos(math.radians(self.center_lat))
        return (
            math.radians(lon - self.center_lon) * self.radius * cosine,
            math.radians(lat - self.center_lat) * self.radius,
        )

    def xyll(self, x: float, y: float) -> tuple[float, float]:
        """Converte metros relativos ao centro para latitude/longitude."""
        if self.center_lat is None or self.center_lon is None:
            raise RuntimeError("O centro do mapa ainda não foi definido.")
        cosine = math.cos(math.radians(self.center_lat))
        return (
            self.center_lat + math.degrees(y / self.radius),
            self.center_lon + math.degrees(x / (self.radius * cosine)),
        )

    def new_map(self) -> None:
        """Limpa o mapa e a procura, mantendo telemetria atual do Rhino."""
        self.points.clear()
        self.deposits.clear()
        self.rigs.clear()
        self.last_xy = None
        self.search_started = False
        self.datum_lat = None
        self.datum_lon = None
        self.route_index = 0
        self.next_target_xy = None
        self.route_history.clear()

    def process_status(self, status: dict[str, Any]) -> bool:
        """Atualiza a telemetria a partir de um ``Status.json``.

        Devolve ``True`` quando a posição foi aceite como telemetria do Rhino.
        """
        if not (int(status.get("Flags", 0)) & SRV_FLAG):
            return False

        fuel = status.get("Fuel") or {}
        reservoir = fuel.get("FuelReservoir")
        if reservoir is not None:
            self.fuel_reservoir = float(reservoir)
            self.fuel_percent = max(0.0, min(100.0, self.fuel_reservoir / 0.80 * 100.0))
            self.fuel_low = bool(int(status.get("Flags", 0)) & 0x00080000)

        heading = status.get("Heading")
        if heading is not None:
            try:
                self.rhino_heading = float(heading) % 360.0
            except (TypeError, ValueError):
                self.rhino_heading = None

        lat, lon = status.get("Latitude"), status.get("Longitude")
        if lat is None or lon is None:
            return False
        self.rhino_lat, self.rhino_lon = float(lat), float(lon)

        system, body = status.get("StarSystem", ""), status.get("BodyName", "")
        body_key = f"{system}|{body}"
        # Um novo corpo define outro referencial: não podemos juntar percursos
        # de planetas diferentes nas mesmas coordenadas locais.
        if self.body_key != body_key:
            self.body_key, self.system, self.body = body_key, system, body
            self.center_lat, self.center_lon = self.rhino_lat, self.rhino_lon
            self.radius = float(status.get("PlanetRadius") or DEFAULT_RADIUS_M)
            self.new_map()

        x, y = self.llxy(self.rhino_lat, self.rhino_lon)
        # Registamos amostras separadas por pelo menos 10 m. Saltos acima de
        # 100 m ficam assinalados para o desenho não inventar uma linha contínua.
        if self.last_xy is None or math.hypot(x - self.last_xy[0], y - self.last_xy[1]) >= 10.0:
            point = {"x": x, "y": y, "lat": self.rhino_lat, "lon": self.rhino_lon,
                     "t": status.get("timestamp", time.time())}
            if self.last_xy is not None and math.hypot(x - self.last_xy[0], y - self.last_xy[1]) > 100.0:
                point["break_before"] = True
            self.points.append(point)
            self.last_xy = (x, y)

        self.update_next()
        return True

    def start_search(self) -> bool:
        """Define o Datum na posição atual e prepara o primeiro destino."""
        if self.rhino_lat is None or self.rhino_lon is None or self.center_lat is None:
            return False
        self.datum_lat, self.datum_lon = self.rhino_lat, self.rhino_lon
        self.search_started = True
        self.route_index = 0
        self.next_target_xy = None
        self.route_history.clear()
        self.update_next()
        return True

    @property
    def search_total_points(self) -> int:
        """Calcula quantos destinos cobrem a circunferência com o espaçamento definido.
        ceil arredonda para cima para não exceder o espaçamento pretendido."""
        return max(1, math.ceil((2.0 * math.pi * SEARCH_RADIUS_M) / SEARCH_SPACING_M))

    def skip_next(self) -> bool:
        """Regista o destino atual como saltado e avança para o seguinte."""
        if not self.search_started or self.next_target_xy is None:
            return False
        tx, ty = self.next_target_xy
        self.route_history.append({"number": self.route_index + 1, "x": tx, "y": ty, "status": "skipped"})
        self.route_index += 1
        if self.route_index >= self.search_total_points:
            self.next_target_xy = None
        else:
            self.update_next()
        return True

    def update_next(self) -> None:
        """Atualiza o destino da procura circular e avança quando é atingido."""
        if (not self.search_started or self.datum_lat is None or self.datum_lon is None
                or self.route_index >= self.search_total_points):
            self.next_target_xy = None
            return

        datum_x, datum_y = self.llxy(self.datum_lat, self.datum_lon)
        # sin produz X (este/oeste) e cos produz Y (norte/sul). Com ângulo zero
        # o destino está a norte; aumentar o ângulo avança no sentido horário.
        step_angle = (2.0 * math.pi) / self.search_total_points
        angle = self.route_index * step_angle
        target_x = datum_x + SEARCH_RADIUS_M * math.sin(angle)
        target_y = datum_y + SEARCH_RADIUS_M * math.cos(angle)
        self.next_target_xy = (target_x, target_y)

        if self.rhino_lat is None or self.rhino_lon is None:
            return
        rhino_x, rhino_y = self.llxy(self.rhino_lat, self.rhino_lon)
        if math.hypot(target_x - rhino_x, target_y - rhino_y) > 100.0:
            return

        self.route_history.append({"number": self.route_index + 1, "x": target_x, "y": target_y, "status": "reached"})
        self.route_index += 1
        if self.route_index >= self.search_total_points:
            self.next_target_xy = None
            return
        angle = self.route_index * step_angle
        self.next_target_xy = (
            datum_x + SEARCH_RADIUS_M * math.sin(angle),
            datum_y + SEARCH_RADIUS_M * math.cos(angle),
        )

    def overlay_navigation(self, now: float | None = None) -> tuple[str, str, str, str]:
        """Devolve texto e cores a desenhar no overlay de navegação."""
        if (not self.search_started or self.next_target_xy is None or self.rhino_lat is None
                or self.rhino_lon is None or self.rhino_heading is None):
            return "—", "—", "#888888", "white"

        tx, ty = self.next_target_xy
        rx, ry = self.llxy(self.rhino_lat, self.rhino_lon)
        distance = math.hypot(tx - rx, ty - ry)
        bearing = (math.degrees(math.atan2(tx - rx, ty - ry)) + 360.0) % 360.0
        error = MapperState.heading_error(self.rhino_heading, bearing)
        if abs(error) <= 1.0:
            color = "#00cc44"
        elif abs(error) <= 3.0:
            color = "#ffd21c"
        else:
            color = "#ff3030"

        if error < -1.0:
            heading = f"<<< {bearing:03.0f}°"
        elif error > 1.0:
            heading = f"{bearing:03.0f}° >>>"
        else:
            heading = f"{bearing:03.0f}°"

        # monotonic mede intervalos sem depender de ajustes do relógio do sistema.
        # Não usamos sleep: a interface tem de continuar a responder enquanto pisca.
        if distance <= 300.0:
            now = time.monotonic() if now is None else now
            if now >= self.overlay_next_blink:
                self.overlay_blink_on = not self.overlay_blink_on
                self.overlay_next_blink = now + 0.45
            distance_color = "white" if self.overlay_blink_on else "#202020"
        else:
            self.overlay_blink_on, self.overlay_next_blink = True, 0.0
            distance_color = "white"
        return heading, f"{distance:.0f} m", color, distance_color

    def to_dict(self) -> dict[str, Any]:
        """Serializa o estado no formato de mapa já existente."""
        return {
            "system": self.system, "body": self.body, "center_lat": self.center_lat,
            "center_lon": self.center_lon, "planet_radius": self.radius,
            "coverage_width_m": self.coverage_width_m, "scanner_range_m": self.scanner_range_m,
            "search_started": self.search_started, "datum_lat": self.datum_lat,
            "datum_lon": self.datum_lon, "route_index": self.route_index,
            "route_history": self.route_history, "points": self.points,
            "deposits": self.deposits, "rigs": self.rigs,
        }

    def save(self, path: Path) -> None:
        """Escreve o mapa em JSON UTF-8 no caminho indicado.
        ensure_ascii=False conserva os acentos; indent=2 torna o ficheiro legível.
        Erros de escrita propagam-se para o diálogo da interface que chamou o método.
        """
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, path: Path) -> None:
        """Valida uma sessão antes de substituir o estado existente."""
        candidate = MapperState()
        candidate._load_file(path)
        candidate.validate_map()
        candidate.update_next()
        # Só chegamos aqui após validação. Um erro anterior deixa self intacto.
        self.__dict__.update(candidate.__dict__)

    def validate_map(self) -> None:
        """Verifica tipos, limites e coerência de um mapa carregado.
        Normaliza números e completa coordenadas de marcadores antigos.
        Lança ValueError, TypeError ou KeyError quando os dados não podem ser utilizados."""
        def number(value):
            """Converte um valor numérico e rejeita infinito ou NaN.
            Estes valores não podem ser usados no desenho ou nos cálculos de navegação."""
            result = float(value)
            if not math.isfinite(result):
                raise ValueError("O mapa contém um número não finito.")
            return result

        if not isinstance(self.system, str) or not isinstance(self.body, str):
            raise ValueError("Sistema e corpo devem ser texto.")
        self.center_lat, self.center_lon = number(self.center_lat), number(self.center_lon)
        if not (-90 < self.center_lat < 90 and -180 <= self.center_lon <= 180):
            raise ValueError("Centro do mapa fora dos limites suportados.")
        if number(self.radius) <= 0:
            raise ValueError("Raio do planeta inválido.")
        if not (100 <= number(self.coverage_width_m) <= 5000 and 500 <= number(self.scanner_range_m) <= 5000):
            raise ValueError("Cobertura ou scanner fora dos limites.")
        if not 0 <= self.route_index <= self.search_total_points:
            raise ValueError("Índice da busca inválido.")
        if self.search_started and (self.datum_lat is None or self.datum_lon is None):
            raise ValueError("Busca ativa sem Datum.")
        if (self.datum_lat is None) != (self.datum_lon is None):
            raise ValueError("Datum incompleto.")
        if self.datum_lat is not None:
            if not (-90 <= number(self.datum_lat) <= 90 and -180 <= number(self.datum_lon) <= 180):
                raise ValueError("Datum inválido.")
        for items in (self.points, self.deposits, self.rigs, self.route_history):
            if not isinstance(items, list):
                raise ValueError("A coleção de marcadores deve ser uma lista.")
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError("Marcador inválido.")
                item['x'], item['y'] = number(item['x']), number(item['y'])
        for item in self.points + self.deposits + self.rigs:
            if 'lat' not in item or 'lon' not in item:
                item['lat'], item['lon'] = self.xyll(item['x'], item['y'])
            item['lat'], item['lon'] = number(item['lat']), number(item['lon'])
            if not (-90 <= item['lat'] <= 90 and -180 <= item['lon'] <= 180):
                raise ValueError("Coordenadas do marcador inválidas.")
        for deposit in self.deposits:
            if not isinstance(deposit.get('name', ''), str):
                raise ValueError("Nome do depósito inválido.")
            if deposit['size'] not in ('Pequeno', 'Médio', 'Grande', 'Enorme'):
                raise ValueError("Tamanho do depósito inválido.")
            count = number(deposit['rigs'])
            if not count.is_integer() or not 1 <= count <= 6:
                raise ValueError("Número de rigs inválido.")
            deposit['rigs'] = int(count)
        for item in self.route_history:
            if item.get('status') not in ('reached', 'skipped'):
                raise ValueError("Estado do destino inválido.")
            value = number(item['number'])
            if not value.is_integer() or not 1 <= value <= self.search_total_points:
                raise ValueError("Número do destino inválido.")
            item['number'] = int(value)
        self.last_xy = ((self.points[-1]['x'], self.points[-1]['y']) if self.points else None)

    def _load_file(self, path: Path) -> None:
        """Desserializa os campos JSON num estado candidato.
        Método interno: só load deve ser usado externamente, pois também valida o resultado."""
        data = json.loads(path.read_text(encoding="utf-8"))
        self.system, self.body = data.get("system", ""), data.get("body", "")
        self.body_key = f"{self.system}|{self.body}"
        self.center_lat, self.center_lon = float(data["center_lat"]), float(data["center_lon"])
        self.radius = float(data.get("planet_radius", DEFAULT_RADIUS_M))
        self.coverage_width_m = float(data.get("coverage_width_m", 500.0))
        self.scanner_range_m = float(data.get("scanner_range_m", 2_000.0))
        self.search_started = bool(data.get("search_started", False))
        self.datum_lat, self.datum_lon = data.get("datum_lat"), data.get("datum_lon")
        if self.datum_lat is not None:
            self.datum_lat = float(self.datum_lat)
        if self.datum_lon is not None:
            self.datum_lon = float(self.datum_lon)
        self.route_index = int(data.get("route_index", 0))
        self.route_history = data.get("route_history", [])
        self.points, self.deposits, self.rigs = data.get("points", []), data.get("deposits", []), data.get("rigs", [])
        for deposit in self.deposits:
            deposit.setdefault("size", "Pequeno")
            deposit.setdefault("rigs", 1)
        self.last_xy = ((self.points[-1]["x"], self.points[-1]["y"]) if self.points else None)

