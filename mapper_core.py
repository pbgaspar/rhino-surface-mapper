"""Núcleo independente da interface do Rhino Surface Mapper.

Este módulo contém as regras de estado, mapa e navegação, sem dependências
de interface gráfica. Pode ser testado isoladamente e é utilizado pela janela
principal para processar os dados do jogo e dos mapas guardados.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from map_persistence import (
    is_map_file_protected,
    read_file_timestamps,
    read_map_json,
    update_map_file_flags,
    write_map_json,
)

# Flags é um conjunto de bits enviado pelo jogo. Este bit identifica uso do SRV.
SRV_FLAG = 0x04000000
DEFAULT_RADIUS_M = 6_371_000.0
SEARCH_RADIUS_M = 3_500.0
SEARCH_SPACING_M = 1_800.0


@dataclass(frozen=True)
class StatusUpdate:
    """Result of processing one telemetry status."""

    accepted: bool
    location_changed: bool = False
    system: str = ""
    body: str = ""
    latitude: float | None = None
    longitude: float | None = None

    def __bool__(self) -> bool:
        """Preserve the historical boolean contract for existing callers."""
        return self.accepted


class MapperState:
    """Estado e operações do mapa, independente de qualquer toolkit gráfico."""

    def __init__(self) -> None:
        """Inicializa os dados de telemetria, mapa e busca sem criar qualquer interface.
        None significa ainda não conhecido; listas vazias significam ausência de registos."""
        self.status_path: Path | None = None
        self.points: list[dict[str, Any]] = []
        self.radar_coverage = []
        self.map_generation = 0
        self.deposits: list[dict[str, Any]] = []
        self.rigs: list[dict[str, Any]] = []
        self.marks: list[dict[str, Any]] = []
        self.system = ""
        self.body = ""
        self.body_key: str | None = None
        # Metadados opcionais: mapas antigos não os têm e continuam válidos.
        self.created_at: str | None = None
        self.last_saved_at: str | None = None
        self.favorite = False
        self.protected = False
        self.mining_only = False  # Modo da sessão; nunca é gravado no JSON.
        # PML identifica a zona de exploração dentro do planeta. O centro do
        # mapa continua a ser um referencial técnico; o centro do PML é a
        # posição geográfica usada para reencontrar o mapa no regresso.
        self.pml_id = ""
        self.pml_center_lat: float | None = None
        self.pml_center_lon: float | None = None
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
        self.search_azimuth = 0
        self.search_started = False
        self.datum_lat: float | None = None
        self.datum_lon: float | None = None
        self.route_index = 0
        self.next_target_xy: tuple[float, float] | None = None
        self.route_history: list[dict[str, Any]] = []
        self.overlay_blink_on = True
        self.overlay_next_blink = 0.0
        self.active_nav_target: dict[str, Any] | None = None
        self.search_paused = False
        self.search_pause_point: tuple[float, float] | None = None
        self.return_to_pause = False
        self.in_srv = False

    def overlay_allowed(self) -> bool:
        """Modos que autorizam o overlay; apenas permitido quando o comandante está no Rhino."""
        if not self.in_srv:
            return False
        return bool(self.search_started or self.active_nav_target is not None or self.return_to_pause)

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

    def new_map(self, keep_pml: bool = False) -> None:
        """Limpa o mapa e a procura, mantendo telemetria atual do Rhino.

        ``keep_pml`` é usado pelo botão Novo: começa outro registo no mesmo
        PML. A mudança real de planeta usa o valor padrão e limpa o PML.
        """
        self.favorite = False
        self.protected = False
        self.mining_only = False
        self.points.clear()
        self.radar_coverage.clear()
        self.map_generation += 1
        self.deposits.clear()
        self.rigs.clear()
        self.marks.clear()
        self.created_at = None
        self.last_saved_at = None
        self.last_xy = None
        self.search_started = False
        self.search_paused = False
        self.search_pause_point = None
        self.return_to_pause = False
        self.active_nav_target = None
        self.datum_lat = None
        self.datum_lon = None
        if not keep_pml:
            self.pml_id = ""
            self.pml_center_lat = None
            self.pml_center_lon = None
        self.route_index = 0
        self.next_target_xy = None
        self.route_history.clear()

    def process_status(self, status: dict[str, Any], *, record_position: bool = True) -> StatusUpdate:
        """Atualiza a telemetria a partir de um ``Status.json``.

        Devolve ``True`` quando a posição foi aceite como telemetria do Rhino.
        """
        flags = int(status.get("Flags", 0))
        self.in_srv = bool(flags & SRV_FLAG)
        if not self.in_srv:
            return StatusUpdate(False)

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
            return StatusUpdate(False)
        latitude, longitude = float(lat), float(lon)

        system, body = status.get("StarSystem", ""), status.get("BodyName", "")
        # O Status.json pode omitir StarSystem durante vários segundos. Quando
        # o planeta continua a ser o mesmo, conservar o último sistema válido
        # evita tratar cada atualização como um planeta novo e limpar o mapa.
        if not system and self.system and body == self.body:
            system = self.system
        body_key = f"{system}|{body}"
        if system and not self.system and self.body and body == self.body:
            self.system = system
            self.body_key = body_key
        if self.body_key and self.body_key != body_key:
            return StatusUpdate(True, True, system, body, latitude, longitude)
        if record_position:
            self.rhino_lat, self.rhino_lon = latitude, longitude
        if self.read_only and self.body_key != body_key:
            # Consultar outro planeta não pode apagar o mapa protegido.
            return StatusUpdate(True, True, system, body, latitude, longitude)
        # Um novo corpo define outro referencial: não podemos juntar percursos
        # de planetas diferentes nas mesmas coordenadas locais.
        if self.body_key != body_key:
            self.body_key, self.system, self.body = body_key, system, body
            self.center_lat, self.center_lon = self.rhino_lat, self.rhino_lon
            self.radius = float(status.get("PlanetRadius") or DEFAULT_RADIUS_M)
            self.new_map()

        if not record_position:
            return StatusUpdate(True, False, system, body, latitude, longitude)

        x, y = self.llxy(self.rhino_lat, self.rhino_lon)
        # Registamos amostras separadas por pelo menos 10 m. Saltos acima de
        # 100 m ficam assinalados para o desenho não inventar uma linha contínua.
        if not self.read_only and (self.last_xy is None or math.hypot(x - self.last_xy[0], y - self.last_xy[1]) >= 10.0):
            point = {"x": x, "y": y, "lat": self.rhino_lat, "lon": self.rhino_lon,
                     "t": status.get("timestamp", time.time())}
            if self.last_xy is not None and math.hypot(x - self.last_xy[0], y - self.last_xy[1]) > 100.0:
                point["break_before"] = True
            self.points.append(point)
            self.last_xy = (x, y)

        self.update_next()
        return StatusUpdate(True, False, system, body, latitude, longitude)

    def start_search(self, azimuth: int = 0) -> bool:
        """Define o Datum na posição atual e prepara o primeiro destino."""
        if self.read_only:
            return False
        if type(azimuth) is not int or not 0 <= azimuth <= 359:
            raise ValueError("AZ Busca deve ser um inteiro entre 000 e 359.")
        if self.rhino_lat is None or self.rhino_lon is None or self.center_lat is None:
            return False
        self.search_azimuth = azimuth
        self.datum_lat, self.datum_lon = self.rhino_lat, self.rhino_lon
        self.search_started = True
        self.search_paused = False
        self.search_pause_point = None
        self.return_to_pause = False
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
        if self.read_only:
            return False
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
        if self.read_only:
            self.next_target_xy = None
            return
        if (not self.search_started or self.datum_lat is None or self.datum_lon is None
                or self.route_index >= self.search_total_points):
            self.next_target_xy = None
            return

        datum_x, datum_y = self.llxy(self.datum_lat, self.datum_lon)
        # sin produz X (este/oeste) e cos produz Y (norte/sul). Com ângulo zero
        # o destino está a norte; aumentar o ângulo avança no sentido horário.
        step_angle = (2.0 * math.pi) / self.search_total_points
        angle = math.radians(self.search_azimuth) + self.route_index * step_angle
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
        angle = math.radians(self.search_azimuth) + self.route_index * step_angle
        self.next_target_xy = (
            datum_x + SEARCH_RADIUS_M * math.sin(angle),
            datum_y + SEARCH_RADIUS_M * math.cos(angle),
        )

    def overlay_navigation(self, now: float | None = None) -> tuple[str, str, str, str, str]:
        """Devolve texto, cores e nome do alvo a desenhar no overlay de navegação."""
        target_name = ""
        tx, ty = None, None

        if self.active_nav_target is not None:
            tx = self.active_nav_target.get("x")
            ty = self.active_nav_target.get("y")
            target_name = self.active_nav_target.get("name", "")
        elif self.return_to_pause and self.search_pause_point is not None:
            tx, ty = self.search_pause_point
            target_name = "Ponto de Pausa ⏸"
        elif self.search_started and not self.search_paused and self.next_target_xy is not None:
            tx, ty = self.next_target_xy
            target_name = f"Busca: Ponto {self.route_index + 1}"

        if (not self.in_srv or tx is None or ty is None or self.rhino_lat is None
                or self.rhino_lon is None or self.rhino_heading is None):
            return "—", "—", "#888888", "white", target_name

        rx, ry = self.llxy(self.rhino_lat, self.rhino_lon)
        distance = math.hypot(tx - rx, ty - ry)
        bearing = (math.degrees(math.atan2(tx - rx, ty - ry)) + 360.0) % 360.0
        error = MapperState.heading_error(self.rhino_heading, bearing)
        if abs(error) <= 2.0:
            color = "#00cc44"
        elif abs(error) <= 8.0:
            color = "#ffd21c"
        else:
            color = "#ff3030"

        arrows = 3 if abs(error) <= 8 else 5
        if error < -2.0:
            heading = f"{'<' * arrows} {bearing:03.0f}°"
        elif error > 2.0:
            heading = f"{bearing:03.0f}° {'»' * arrows}"
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

        # Conclusão aos 100 metros:
        if distance <= 100.0:
            if self.active_nav_target is not None:
                self.navigation_arrivals = getattr(self, 'navigation_arrivals', 0)+1
                self.active_nav_target = None
                if self.search_paused and self.search_pause_point is not None:
                    self.return_to_pause = True
                else:
                    self.search_paused = False
            elif self.return_to_pause:
                self.return_to_pause = False
                self.search_paused = False
                self.search_pause_point = None

        return heading, f"{distance:.0f} m", color, distance_color, target_name

    def to_dict(self) -> dict[str, Any]:
        """Serializa o estado no formato de mapa já existente."""
        return {
            "system": self.system, "body": self.body,
            "created_at": self.created_at, "last_saved_at": self.last_saved_at,
            "favorite": self.favorite, "protected": self.protected,
            "pml_id": self.pml_id, "pml_center_lat": self.pml_center_lat,
            "pml_center_lon": self.pml_center_lon, "center_lat": self.center_lat,
            "center_lon": self.center_lon, "planet_radius": self.radius,
            "coverage_width_m": self.coverage_width_m, "scanner_range_m": self.scanner_range_m,
            "search_started": self.search_started, "datum_lat": self.datum_lat,
            "search_azimuth": self.search_azimuth,
            "datum_lon": self.datum_lon, "route_index": self.route_index,
            "route_history": self.route_history, "points": self.points,
            "radar_coverage": self.radar_coverage,
            "deposits": self.deposits, "rigs": self.rigs, "marks": self.marks,
        }

    def save(self, path: Path, update_saved_at: bool = True) -> None:
        """Escreve o mapa em JSON UTF-8 no caminho indicado.
        ensure_ascii=False conserva os acentos; indent=2 torna o ficheiro legível.
        Erros de escrita propagam-se para o diálogo da interface que chamou o método.
        """
        path = Path(path)
        if self.mining_only:
            raise PermissionError('Só minerar não permite gravar alterações. Abre uma nova versão para explorar.')
        if is_map_file_protected(path):
            raise PermissionError('Este mapa está protegido. Cria uma nova versão para continuar a exploração.')
        # Só mapas novos recebem estes metadados. Não inventamos uma data de
        # criação para um mapa antigo que não a tinha gravado.
        if self.created_at is not None and update_saved_at:
            self.last_saved_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        write_map_json(path, self.to_dict())

    @property
    def read_only(self):
        return getattr(self, 'protected', False) or getattr(self, 'mining_only', False)

    def enter_mining_mode(self):
        """Suspende exploração e busca; conserva os registos para consulta."""
        self.mining_only = True
        self.search_started = False
        self.search_paused = False
        self.search_pause_point = None
        self.return_to_pause = False
        self.active_nav_target = None
        self.next_target_xy = None

    @staticmethod
    def set_file_flags(path, *, favorite, protected):
        """Altera só os dois atributos de gestão, preservando o mapa e as datas.

        É a operação explícita que permite retirar a proteção. Lê o JSON atual
        para não substituir dados por uma cópia antiga aberta na biblioteca.
        """
        update_map_file_flags(path, favorite=favorite, protected=protected)

    def populate_missing_timestamps(self, path: Path) -> bool:
        """Completa datas ausentes com as propriedades de um mapa antigo.

        No Windows ``st_ctime`` é a criação do ficheiro; ``st_mtime`` é a sua
        última modificação. Devolve True apenas quando há informação nova para
        gravar, preservando no JSON a data histórica em vez da data da migração.
        """
        created_at, last_saved_at = read_file_timestamps(path)
        changed = False
        if self.created_at is None:
            self.created_at = created_at
            changed = True
        if self.last_saved_at is None:
            self.last_saved_at = last_saved_at
            changed = True
        return changed

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
        for value in (self.created_at, self.last_saved_at):
            if value is not None and not isinstance(value, str):
                raise ValueError("Data do mapa inválida.")
        if not isinstance(self.pml_id, str):
            raise ValueError("Identificador do PML inválido.")
        if (self.pml_center_lat is None) != (self.pml_center_lon is None):
            raise ValueError("Centro do PML incompleto.")
        if self.pml_center_lat is not None:
            self.pml_center_lat, self.pml_center_lon = (
                number(self.pml_center_lat), number(self.pml_center_lon))
            if not (-90 <= self.pml_center_lat <= 90 and -180 <= self.pml_center_lon <= 180):
                raise ValueError("Centro do PML fora dos limites.")
        self.center_lat, self.center_lon = number(self.center_lat), number(self.center_lon)
        if not (-90 < self.center_lat < 90 and -180 <= self.center_lon <= 180):
            raise ValueError("Centro do mapa fora dos limites suportados.")
        if number(self.radius) <= 0:
            raise ValueError("Raio do planeta inválido.")
        if not (100 <= number(self.coverage_width_m) <= 5000 and 500 <= number(self.scanner_range_m) <= 5000):
            raise ValueError("Cobertura ou scanner fora dos limites.")
        if type(self.search_azimuth) is not int or not 0 <= self.search_azimuth <= 359:
            raise ValueError("AZ Busca deve ser um inteiro entre 000 e 359.")
        if not 0 <= self.route_index <= self.search_total_points:
            raise ValueError("Índice da busca inválido.")
        if self.search_started and (self.datum_lat is None or self.datum_lon is None):
            raise ValueError("Busca ativa sem Datum.")
        if (self.datum_lat is None) != (self.datum_lon is None):
            raise ValueError("Datum incompleto.")
        if self.datum_lat is not None:
            if not (-90 <= number(self.datum_lat) <= 90 and -180 <= number(self.datum_lon) <= 180):
                raise ValueError("Datum inválido.")
        for items in (self.points, self.deposits, self.rigs, self.marks, self.route_history):
            if not isinstance(items, list):
                raise ValueError("A coleção de marcadores deve ser uma lista.")
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError("Marcador inválido.")
                item['x'], item['y'] = number(item['x']), number(item['y'])
        for item in self.points + self.deposits + self.rigs + self.marks:
            if 'lat' not in item or 'lon' not in item:
                item['lat'], item['lon'] = self.xyll(item['x'], item['y'])
            item['lat'], item['lon'] = number(item['lat']), number(item['lon'])
            if not (-90 <= item['lat'] <= 90 and -180 <= item['lon'] <= 180):
                raise ValueError("Coordenadas do marcador inválidas.")
        for mark in self.marks:
            if not isinstance(mark.get("name"), str) or not mark["name"].strip():
                raise ValueError("Nome da marca inválido.")
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
        if not isinstance(self.radar_coverage, list):
            raise ValueError('Cobertura do radar inválida.')
        for pulse in self.radar_coverage:
            if not isinstance(pulse, dict):
                raise ValueError('Pulso de radar inválido.')
            for key in ('x', 'y', 'radius'):
                pulse[key] = number(pulse[key])
            if not 0 <= pulse['radius'] <= 5000:
                raise ValueError('Raio de cobertura inválido.')

    def _load_file(self, path: Path) -> None:
        """Desserializa os campos JSON num estado candidato.
        Método interno: só load deve ser usado externamente, pois também valida o resultado."""
        data = read_map_json(path)
        self.system, self.body = data.get("system", ""), data.get("body", "")
        self.created_at = data.get("created_at")
        self.last_saved_at = data.get("last_saved_at")
        self.favorite = data.get('favorite', False)
        self.protected = data.get('protected', False)
        if type(self.favorite) is not bool or type(self.protected) is not bool:
            raise ValueError('Favorito e proteção inválidos no mapa.')
        self.body_key = f"{self.system}|{self.body}"
        self.pml_id = data.get("pml_id", "")
        self.pml_center_lat = data.get("pml_center_lat")
        self.pml_center_lon = data.get("pml_center_lon")
        if self.pml_center_lat is not None:
            self.pml_center_lat = float(self.pml_center_lat)
        if self.pml_center_lon is not None:
            self.pml_center_lon = float(self.pml_center_lon)
        self.center_lat, self.center_lon = float(data["center_lat"]), float(data["center_lon"])
        self.radius = float(data.get("planet_radius", DEFAULT_RADIUS_M))
        self.coverage_width_m = float(data.get("coverage_width_m", 500.0))
        self.scanner_range_m = float(data.get("scanner_range_m", 2_000.0))
        self.search_started = bool(data.get("search_started", False))
        self.search_azimuth = data.get("search_azimuth", 0)
        self.datum_lat, self.datum_lon = data.get("datum_lat"), data.get("datum_lon")
        if self.datum_lat is not None:
            self.datum_lat = float(self.datum_lat)
        if self.datum_lon is not None:
            self.datum_lon = float(self.datum_lon)
        self.route_index = int(data.get("route_index", 0))
        self.marks = data.get("marks", [])
        self.radar_coverage = data.get('radar_coverage', [])
        self.route_history = data.get("route_history", [])
        self.points, self.deposits, self.rigs = data.get("points", []), data.get("deposits", []), data.get("rigs", [])
        for deposit in self.deposits:
            deposit.setdefault("size", "Pequeno")
            deposit.setdefault("rigs", 1)
        self.last_xy = ((self.points[-1]["x"], self.points[-1]["y"]) if self.points else None)
