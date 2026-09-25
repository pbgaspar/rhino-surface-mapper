"""Main window and map view for Rhino Surface Mapper using PySide6."""
import json
import copy
import math
import sys
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QKeySequence, QShortcut, QFont, QPainterPath, QFontMetricsF, QIcon, QTransform
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QSpinBox, QCheckBox, QFileDialog, QMessageBox)
from mapper_core import MapperState
from map_pml import corresponds_to_map, newest_by_pml
from settings_persistence import load_preferences
from elite_dangerous.status import read_status_if_changed
from pyqt_overlay import OverlayWindow
from qt_map_operations import MapOperations
from radar import RadarPulse
from radar_input import RadarInput
from steering_ui import SteeringUI
from layout_options import (LayoutOptions, OP_EXIT, OP_MARK, OP_MARK_DEPOSIT,
                            OP_MARK_RIG)
from map_library import MapLibraryWindow
from deposit_marker import draw_deposit, deposit_bounds
from numeric_fields import MetresSpinBox, DegreesSpinBox
from i18n import install_translator, translate
from PySide6.QtWidgets import QDialog, QFormLayout, QComboBox, QLineEdit, QDialogButtonBox


OPTIONS_PATH = Path(__file__).resolve().parent / 'options.json'


class AzimuthSpinBox(DegreesSpinBox):
    """Azimute inteiro apresentado sempre com três algarismos."""

    def textFromValue(self, value):
        return f'{value:03d}'


class MapView(QWidget):
    """Área de desenho do mapa. Converte metros em píxeis e interpreta o rato.
    O estado pertence a MapperState; esta classe apenas o apresenta e guarda a vista."""
    # Um sinal é uma mensagem Qt. connect() liga essa mensagem à função recetora.
    # O mapa comunica posições/texto; a janela decide que operação realizar.
    cursor_changed = Signal(str)
    clicked = Signal(QPointF)
    menu_requested = Signal(QPointF)

    def __init__(self, state):
        """Recebe o estado partilhado e prepara a vista e o desenho vetorial.
        center é o centro da vista em metros; scale mede píxeis por metro."""
        super().__init__()
        self.state = state
        self.radar = RadarPulse()
        self.colors = {}
        self.text_scale = 1.0
        self.dark_theme = False
        self.cursor_text = translate('MapView', 'Cursor: —')
        self.cursor_changed.connect(self.set_cursor_text)
        self.center = QPointF(0, 0)
        self.scale = 0.08
        self.drag = None
        # O percurso pode ter milhares de posições. Estes caminhos vetoriais são
        # refeitos apenas quando o percurso ou o zoom mudam; arrastar o mapa
        # limita-se a aplicar outra transformação ao mesmo desenho.
        self._trajectory_source = None
        self._trajectory_generation = None
        self._trajectory_point_count = -1
        self._trajectory_scale = None
        self._trajectory_content = None
        self._coverage_path = QPainterPath()
        self._trail_line_path = QPainterPath()
        self._trail_dot_path = QPainterPath()
        self._isolated_coverage_points = []
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)
        base = Path(__file__).resolve().parent
        self.rhino_renderer = QSvgRenderer(str(base / 'assets' / 'Rhino.svg'), self)
        self.rhino_height = 56.0

    def screen(self, x, y):
        """Converte X/Y do mapa, em metros, num QPointF em píxeis.
        O eixo Y é invertido: no mapa cresce para norte; no ecrã cresce para baixo."""
        return QPointF(self.width()/2 + (x-self.center.x())*self.scale,
                       self.height()/2 - (y-self.center.y())*self.scale)

    def world(self, point):
        """Faz a conversão inversa de screen. Recebe uma posição local do rato.
        O resultado permite calcular coordenadas e colocar marcadores no mapa."""
        return QPointF(self.center.x() + (point.x()-self.width()/2)/self.scale,
                       self.center.y() - (point.y()-self.height()/2)/self.scale)

    def world_transform(self):
        """Transformação do mapa em metros para o ecrã, usada pelos caminhos.

        Ao desenhar o caminho em metros, o Qt trata da escala, inversão do eixo
        vertical e deslocamento. Isto evita converter e desenhar cada ponto de
        novo sempre que o utilizador arrasta a vista.
        """
        return QTransform(self.scale, 0, 0, -self.scale,
                          self.width()/2-self.center.x()*self.scale,
                          self.height()/2+self.center.y()*self.scale)

    def recenter(self):
        """Coloca o Rhino no centro da vista, mantendo o nível de ampliação.
        Sem telemetria válida, não altera a vista."""
        s = self.state
        if s.rhino_lat is not None and s.center_lat is not None:
            center = QPointF(*s.llxy(s.rhino_lat, s.rhino_lon))
            if center != self.center:
                self.center = center
                self.update()

    def zoom_at(self, point, factor):
        """Amplia ou reduz sem deslocar o ponto do mapa que está sob o rato.
        factor maior que 1 aproxima; menor que 1 afasta. Os limites evitam escalas extremas."""
        # Guardamos o ponto geográfico antes de mudar a escala e compensamos
        # depois o centro. Assim, o mapa não salta para outra posição ao ampliar.
        before = self.world(point)
        self.scale = max(0.001, min(10, self.scale*factor))
        self.center += before-self.world(point)
        self.update()

    def wheelEvent(self, event):
        """Recebe automaticamente o evento da roda do rato enviado pelo Qt.
        Um passo habitual de 120 unidades corresponde a uma ampliação de 15%."""
        self.zoom_at(event.position(), 1.15 ** (event.angleDelta().y()/120))

    def mousePressEvent(self, event):
        """Encaminha o clique esquerdo, centra com o botão do meio ou inicia um arrasto.
        Os sinais permitem que a janela decida o efeito do clique sem acoplar o mapa aos diálogos."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(event.position())
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.recenter()
        elif event.button() == Qt.MouseButton.RightButton:
            self.drag = event.position()
            self.press_position = event.position()
            self.dragged = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        """Desloca a vista durante um arrasto e calcula a informação do cursor.
        A distância é em metros; o azimute é contado a partir do norte, no sentido horário."""
        if self.drag is not None:
            if (event.position()-self.press_position).manhattanLength() > 4:
                self.dragged = True
            delta = event.position()-self.drag
            self.center += QPointF(-delta.x()/self.scale, delta.y()/self.scale)
            self.drag = event.position()
            self.update()
        s = self.state
        if s.center_lat is not None:
            q = self.world(event.position())
            lat, lon = s.xyll(q.x(), q.y())
            text = translate('MapView', 'Cursor: {latitude:.5f}°, {longitude:.5f}°').format(
                latitude=lat, longitude=lon)
            if s.rhino_lat is not None:
                x, y = s.llxy(s.rhino_lat, s.rhino_lon)
                dx, dy = q.x()-x, q.y()-y
                text += translate(
                    'MapView', ' | Distance: {distance:.0f} m | Bearing: {bearing:03.0f}°').format(
                        distance=math.hypot(dx,dy),
                        bearing=math.degrees(math.atan2(dx,dy)) % 360)
            self.cursor_changed.emit(text)

    def mouseReleaseEvent(self, event):
        """Termina o arrasto do botão direito. Um clique sem arrasto pede o menu.
        A distinção evita abrir o menu quando o utilizador apenas desloca o mapa."""
        if event.button() == Qt.MouseButton.RightButton:
            self.drag = None
            self.unsetCursor()
            if not self.dragged:
                self.menu_requested.emit(event.position())

    def marker_at(self, position):
        """Procura o marcador mais próximo da posição local indicada, até 14 píxeis.
        Devolve (nome da coleção, dicionário do marcador), ou None quando não encontra nenhum."""
        for item in reversed(self.state.marks):
            if self.mark_bounds(item).contains(position):
                return 'marks', item
        for item in reversed(self.state.deposits):
            if deposit_bounds(self.screen(item['x'], item['y']), self.map_font(), item).contains(position):
                return 'deposits', item
        nearest, distance = None, 14.0
        for kind in ('deposits','rigs'):
            for item in getattr(self.state,kind):
                q = self.screen(item['x'],item['y'])
                d = math.hypot(q.x()-position.x(),q.y()-position.y())
                if d < distance:
                    nearest, distance = (kind,item), d
        for item in ([] if self.state.read_only else self.state.route_history):
            q = self.screen(item['x'], item['y'])
            d = math.hypot(q.x() - position.x(), q.y() - position.y())
            if d < distance:
                nearest, distance = ('route', item), d
        if self.state.next_target_xy is not None:
            tx, ty = self.state.next_target_xy
            q = self.screen(tx, ty)
            d = math.hypot(q.x() - position.x(), q.y() - position.y())
            if d < distance:
                route_item = {'x': tx, 'y': ty, 'number': self.state.route_index + 1, 'status': 'next'}
                nearest, distance = ('route', route_item), d
        return nearest

    def map_font(self):
        """Devolve a fonte do mapa adaptada à dimensão lógica do monitor atual.

        Mantém a fonte habitual até 1080 unidades no lado menor. Num monitor
        4K a 100%, duplica-a; a 200%, o Qt já apresenta 1080 unidades lógicas,
        pelo que não há ampliação adicional. Isto é uma aproximação de leitura,
        não uma medição física do tamanho do monitor ou da distância aos olhos.
        A fonte é calculada em cada desenho para acompanhar a mudança de ecrã.
        """
        font = QFont(self.font())
        screen = QWidget.screen(self)
        if screen is not None:
            geometry = screen.geometry()
            factor = max(1.0, min(2.0, min(geometry.width(), geometry.height()) / 1080.0))
            if font.pointSizeF() > 0:
                font.setPointSizeF(font.pointSizeF() * factor)
            elif font.pixelSize() > 0:
                font.setPixelSize(round(font.pixelSize() * factor))
        font.setPointSizeF(max(1, font.pointSizeF()) * getattr(self, "text_scale", 1.0))
        return font

    def draw_route_marker(self, painter, item):
        """Destaca o número de um destino sobre a cobertura e o rasto.

        O círculo é centrado na posição real do destino. O fundo branco opaco
        separa o número das linhas por baixo; o contorno conserva a distinção
        entre alcançado (verde) e saltado (vermelho). As dimensões acompanham
        a fonte do monitor, mas não o zoom em metros do mapa.
        save/restore impedem que a fonte, pincel e caneta afetem outros desenhos.
        """
        painter.save()
        font = QFont(painter.font())
        font.setBold(True)
        painter.setFont(font)
        label = str(item['number'])
        metrics = painter.fontMetrics()
        # Reserva espaço para dois algarismos e uma margem proporcional à fonte.
        padding = max(4.0, metrics.height() * 0.22)
        diameter = max(metrics.height(), metrics.horizontalAdvance(label)) + 2 * padding
        center = self.screen(item['x'], item['y'])
        bounds = QRectF(center.x()-diameter/2, center.y()-diameter/2, diameter, diameter)
        color = QColor('#a62020' if item['status'] == 'skipped' else '#205c28')
        # Uma segunda borda branca destaca o círculo mesmo sobre um rasto espesso.
        painter.setPen(QPen(QColor('white'), max(4.0, metrics.height()*0.22)))
        painter.setBrush(QColor('white'))
        painter.drawEllipse(bounds)
        painter.setPen(QPen(color, max(2.0, metrics.height()*0.10)))
        painter.drawEllipse(bounds)
        painter.drawText(bounds, Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()

    def mark_bounds(self, item):
        q = self.screen(item['x'], item['y'])
        metrics = QFontMetricsF(self.map_font())
        height = max(28.0, metrics.height()+10)
        return QRectF(q.x()-height/2, q.y()-height/2,
                      height+metrics.horizontalAdvance(item['name'])+12, height)

    def draw_mark(self, painter, item):
        """Ícone vetorial, independente dos caracteres disponíveis na fonte."""
        painter.save()
        bounds = self.mark_bounds(item)
        painter.setPen(QPen(QColor('#ffffff'), 2))
        painter.setBrush(QColor('#172b4d'))
        painter.drawRoundedRect(bounds, 5, 5)
        q = self.screen(item['x'], item['y'])
        painter.save()
        painter.translate(q)
        factor = bounds.height()/28
        painter.scale(factor, factor)
        path = QPainterPath()
        path.moveTo(-5, -5)
        path.cubicTo(-5, -12, 6, -12, 6, -5)
        path.cubicTo(6, -1, 0, -1, 0, 3)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor('#ffe066'), 2.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#ffe066'))
        painter.drawEllipse(QPointF(0, 8), 1.6, 1.6)
        painter.restore()
        painter.setPen(QColor('#ffffff'))
        text_bounds = bounds.adjusted(bounds.height(), 0, -6, 0)
        painter.drawText(text_bounds, Qt.AlignmentFlag.AlignVCenter, item['name'])
        painter.restore()

    def trajectory_paths(self):
        """Prepara os caminhos da cobertura e do rasto no referencial do mapa.

        ``break_before`` inicia uma nova secção e, por isso, nunca desenha uma
        faixa artificial entre duas posições separadas. Os círculos do rasto
        são outro caminho: adicionar elipses ao caminho das linhas alteraria o
        ponto corrente do QPainterPath e ligaria segmentos ao sítio errado.
        """
        s = self.state
        # O conteúdo também entra na assinatura porque algumas operações podem
        # assinalar uma quebra num ponto existente, sem substituir a lista.
        content = tuple((point['x'], point['y'], bool(point.get('break_before')))
                        for point in s.points)
        signature = (id(s.points), getattr(s, 'map_generation', None),
                     len(s.points), self.scale, content)
        cached = (self._trajectory_source, self._trajectory_generation,
                  self._trajectory_point_count, self._trajectory_scale,
                  self._trajectory_content)
        if signature == cached:
            return (self._coverage_path, self._trail_line_path,
                    self._trail_dot_path, self._isolated_coverage_points)

        coverage = QPainterPath()
        trail_lines = QPainterPath()
        trail_dots = QPainterPath()
        isolated = []
        previous = None
        # Os pontos do rasto têm dois píxeis de raio, qualquer que seja o zoom.
        dot_radius = 2.0 / self.scale
        for point in s.points:
            current = QPointF(point['x'], point['y'])
            connected = previous is not None and not point.get('break_before')
            if connected:
                coverage.lineTo(current)
                trail_lines.lineTo(current)
                # O primeiro ponto desta secção deixou de estar isolado.
                if isolated and isolated[-1] == previous:
                    isolated.pop()
            else:
                coverage.moveTo(current)
                trail_lines.moveTo(current)
                isolated.append(current)
            trail_dots.addEllipse(QRectF(current.x()-dot_radius, current.y()-dot_radius,
                                         dot_radius*2, dot_radius*2))
            previous = current

        self._trajectory_source, self._trajectory_generation = signature[:2]
        self._trajectory_point_count, self._trajectory_scale = signature[2:4]
        self._trajectory_content = signature[4]
        self._coverage_path = coverage
        self._trail_line_path = trail_lines
        self._trail_dot_path = trail_dots
        self._isolated_coverage_points = isolated
        return coverage, trail_lines, trail_dots, isolated

    def paintEvent(self, event):
        """Redesenha o mapa quando o Qt o solicita. Não altera a navegação.
        A ordem das camadas importa: grelha, cobertura, rasto, destinos, Rhino e marcadores."""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Só os textos recebem esta escala; metros, zoom e telemetria não mudam.
        p.setFont(self.map_font())
        p.fillRect(self.rect(), QColor(self.colors.get('map_background', self.default_map_color('map_background'))))
        s = self.state
        if s.center_lat is None:
            p.setPen(QColor('#b9c9ce' if self.dark_theme else '#233448'))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       translate('MapView', 'Enter the SRV to start mapping.'))
            self.draw_corners(p, 10 ** math.ceil(math.log10(70/self.scale)))
            return
        lo, hi = self.world(QPointF(0,self.height())), self.world(QPointF(self.width(),0))
        # Seleciona uma potência de dez para espaçar a grelha em função do zoom.
        # Os ciclos seguintes só percorrem a área visível, mesmo num mapa grande.
        step = 10 ** math.ceil(math.log10(70/self.scale))
        p.setPen(QPen(QColor(self.colors.get('grid_color', self.default_map_color('grid_color')))))
        for x in range(math.floor(lo.x()/step), math.ceil(hi.x()/step)+1):
            p.drawLine(self.screen(x*step,lo.y()), self.screen(x*step,hi.y()))
        for y in range(math.floor(lo.y()/step), math.ceil(hi.y()/step)+1):
            p.drawLine(self.screen(lo.x(),y*step), self.screen(hi.x(),y*step))
        if not s.read_only:
            # A área varrida e a frente da onda partilham a cor configurada.
            # Desenhá-la antes do rasto evita esconder os pontos e as linhas verdes.
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self.colors.get('wave_color','#69b574')))
            for pulse in s.radar_coverage:
                radius = pulse['radius'] * self.scale
                p.drawEllipse(self.screen(pulse['x'],pulse['y']),radius,radius)
            # Reconstruir a faixa a partir dos pontos guardados permite conservá-la
            # ao reabrir o mapa, sem gravar imagens nem misturar os pulsos do radar.
            # O caminho está em metros e só é refeito quando os pontos ou o zoom mudam.
            coverage_path, trail_lines, trail_dots, isolated_points = self.trajectory_paths()
            coverage_color = QColor(self.colors.get('coverage_color','#8cbd8c'))
            p.save()
            p.setWorldTransform(self.world_transform())
            p.setPen(QPen(coverage_color, s.coverage_width_m, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(coverage_path)
            # Uma secção formada por um único ponto não tem linha: conserva o disco.
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(coverage_color)
            coverage_radius_m = s.coverage_width_m / 2
            for point in isolated_points:
                p.drawEllipse(point, coverage_radius_m, coverage_radius_m)
            p.restore()
            if s.in_srv and s.rhino_lat is not None:
                q = self.screen(*s.llxy(s.rhino_lat,s.rhino_lon))
                if s.points:
                    last = s.points[-1]
                    x, y = s.llxy(s.rhino_lat, s.rhino_lon)
                    if math.hypot(x-last['x'], y-last['y']) <= 100:
                        p.drawLine(self.screen(last['x'], last['y']), q)
                # Disco de cobertura atual, atrás do rasto e dos marcadores.
                p.setPen(QPen(QColor(self.colors.get('trail_color','#2f7d32')), 2))
                p.setBrush(QColor(self.colors.get('coverage_color','#8cbd8c')))
                coverage_radius = s.coverage_width_m*self.scale/2
                p.drawEllipse(q, coverage_radius, coverage_radius)
            for pulse, _, _ in self.radar.waves:
                if any(item is pulse for item in s.radar_coverage):
                    p.setPen(QPen(QColor(self.colors.get('wave_color','#69b574')), 1.5))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    radius = pulse['radius'] * self.scale
                    p.drawEllipse(self.screen(pulse['x'],pulse['y']),radius,radius)
            # Rasto em dois caminhos: linhas e pontos. Cada caminho é desenhado por
            # uma única chamada Qt, mesmo quando o mapa contém milhares de posições.
            trail_color = QColor(self.colors.get('trail_color','#2f7d32'))
            p.save()
            p.setWorldTransform(self.world_transform())
            p.setPen(QPen(trail_color, 1/self.scale))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(trail_lines)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(trail_color)
            p.drawPath(trail_dots)
            p.restore()
            p.setBrush(Qt.BrushStyle.NoBrush)
            # O Datum é fixo. O destino PRÓXIMO muda à medida que a busca avança.
            if s.datum_lat is not None:
                q = self.screen(*s.llxy(s.datum_lat,s.datum_lon))
                p.setPen(QPen(QColor('#cc7a00'),2))
                p.drawEllipse(q,8,8)
                p.drawText(q+QPointF(12,12),'DATUM')
        if s.in_srv and s.rhino_lat is not None:
            q = self.screen(*s.llxy(s.rhino_lat,s.rhino_lon))
            p.setPen(QPen(QColor('#7777aa'),1,Qt.PenStyle.DashLine))
            radius = s.scanner_range_m*self.scale
            if not s.read_only:
                p.drawEllipse(q,radius,radius)
            if s.next_target_xy is not None and not s.search_paused:
                target = self.screen(*s.next_target_xy)
                p.setPen(QPen(QColor('#e08a00'),2,Qt.PenStyle.DashLine))
                p.drawLine(q,target)
                p.drawEllipse(target,9,9)
                p.drawText(target+QPointF(12,-12), translate('MapView', 'NEXT'))
            if s.active_nav_target is not None:
                nav_pos = self.screen(s.active_nav_target['x'], s.active_nav_target['y'])
                p.setPen(QPen(QColor('#00bfff'), 2.5, Qt.PenStyle.DashLine))
                p.drawLine(q, nav_pos)
                p.drawEllipse(nav_pos, 8, 8)
                p.drawText(
                    nav_pos + QPointF(12, -12),
                    translate('MapperWindow', 'NAVIGATE: {name}').format(
                        name=s.active_nav_target.get('name', '')))
            elif s.return_to_pause and s.search_pause_point is not None:
                pause_screen = self.screen(*s.search_pause_point)
                p.setPen(QPen(QColor('#ffb300'), 2.5, Qt.PenStyle.DashLine))
                p.drawLine(q, pause_screen)
            # O SVG aponta a norte; o azimute roda-o no sentido horário.
            # O tamanho é constante no ecrã, independentemente do zoom do mapa.
            if s.rhino_heading is not None and self.rhino_renderer.isValid():
                bounds = self.rhino_renderer.viewBoxF()
                height = self.rhino_height
                width = height * bounds.width() / bounds.height()
                p.save()
                p.translate(q)
                p.rotate(s.rhino_heading % 360)
                self.rhino_renderer.render(p, QRectF(-width/2, -height/2, width, height))
                p.restore()
            else:
                p.setPen(QPen(QColor('#cc2222'),3))
                p.drawEllipse(q,6,6)
        p.setPen(QPen(QColor('#c43b3b'),2))
        for item in s.deposits:
            q = self.screen(item['x'],item['y'])
            draw_deposit(p, q, item)
        p.setPen(QPen(QColor('#3333aa'),2))
        for item in s.rigs:
            q = self.screen(item['x'],item['y'])
            p.drawRect(int(q.x()-6),int(q.y()-6),12,12)
            p.drawText(q+QPointF(10,0), translate('MapView', 'Rig'))
        for item in ([] if s.read_only else s.route_history):
            # Última camada de marcadores: os números ficam à frente do rasto.
            self.draw_route_marker(p, item)
        for item in s.marks:
            self.draw_mark(p, item)
        if s.search_pause_point is not None:
            p_pos = self.screen(*s.search_pause_point)
            p.save()
            p.setPen(QPen(QColor('#101010'), 2))
            p.setBrush(QColor('#ffd21c'))
            p.drawEllipse(p_pos, 11, 11)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor('#101010'))
            p.drawRect(int(p_pos.x() - 4.5), int(p_pos.y() - 6), 3, 12)
            p.drawRect(int(p_pos.x() + 1.5), int(p_pos.y() - 6), 3, 12)
            p.setFont(self.map_font())
            p.setPen(QPen(QColor('#b8860b'), 1))
            p.drawText(p_pos + QPointF(15, 4), translate('MapView', 'PAUSED'))
            p.restore()
        self.draw_corners(p, step)

    def default_map_color(self, key):
        defaults = {'map_background': '#606060' if self.dark_theme else '#ffffff',
                    'grid_color': '#747474' if self.dark_theme else '#eeeeee'}
        return defaults[key]

    def set_cursor_text(self, text):
        self.cursor_text = text
        self.update()

    def leaveEvent(self, event):
        self.set_cursor_text(translate('MapView', 'Cursor: —'))
        super().leaveEvent(event)

    def draw_corners(self, p, step):
        p.save()
        p.setFont(self.map_font())
        fg = QColor('#edf1f5' if self.dark_theme else '#233448')
        bg = QColor(self.colors.get('map_background', self.default_map_color('map_background')))
        fg = QColor('#edf1f5' if bg.lightnessF() < .55 else '#233448')
        def label(rect, value, alignment):
            p.fillRect(rect, bg)
            p.setPen(fg)
            p.drawText(rect.adjusted(5,0,-5,0), alignment | Qt.AlignmentFlag.AlignVCenter, value)
        title = ' — '.join(str(v) for v in (self.state.system,self.state.body) if v) or translate('MapView', 'System and body: —')
        metrics = p.fontMetrics()
        height = metrics.height()+10
        title = metrics.elidedText(title, Qt.TextElideMode.ElideRight, max(50,self.width()-110))
        label(QRectF(8,8,min(metrics.horizontalAdvance(title)+14,self.width()-90),height),title,Qt.AlignmentFlag.AlignLeft)
        grid = translate('MapView', 'Grid: {step:g} m').format(step=step)
        grid_width = metrics.horizontalAdvance(grid)+14
        label(QRectF(8,self.height()-height-8,grid_width,height),grid,Qt.AlignmentFlag.AlignLeft)
        available = max(30,self.width()-grid_width-35)
        cursor = metrics.elidedText(self.cursor_text,Qt.TextElideMode.ElideRight,available-10)
        width = min(available,metrics.horizontalAdvance(cursor)+14)
        label(QRectF(self.width()-width-8,self.height()-height-8,width,height),cursor,Qt.AlignmentFlag.AlignRight)
        p.setBrush(bg)
        p.setPen(QPen(QColor('#87949c'),1))
        p.drawEllipse(QRectF(self.width()-64,10,52,52))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#cc3434'))
        arrow = QPainterPath()
        arrow.moveTo(self.width()-38,17)
        arrow.lineTo(self.width()-44,32)
        arrow.lineTo(self.width()-32,32)
        arrow.closeSubpath()
        p.drawPath(arrow)
        p.setPen(fg)
        p.drawText(QRectF(self.width()-64,32,52,25),Qt.AlignmentFlag.AlignCenter,'N')
        p.restore()



class MapperWindow(LayoutOptions, SteeringUI, MapOperations, QMainWindow):
    """Janela principal: liga controlos, estado, mapa, diálogos e overlay.
    MapOperations fornece operações de ficheiros e marcadores; QMainWindow fornece a janela Qt."""
    def __init__(self, status_path=None):
        """Constrói a interface e o temporizador de leitura de telemetria.
        status_path opcional permite testar com um ficheiro temporário, sem usar o jogo."""
        super().__init__()
        self.setWindowTitle(translate('MapperWindow', 'Rhino Surface Mapper'))
        # As mensagens transitórias têm alternativa nos diálogos. Ocultar a
        # barra de estado evita uma segunda linha redundante sob o rodapé.
        self.statusBar().hide()
        self.setWindowIcon(QIcon(str(Path(__file__).resolve().parent/'assets'/'Rhino_App.svg')))
        self.resize(1150,800)
        # Uma única instância de estado é partilhada por janela, mapa e operações.
        # O overlay recebe apenas texto/cores, não modifica os dados do mapa.
        self.state = MapperState()
        self.placing_rig = False
        self.parameter_spins = {}
        self.status_path = Path(status_path) if status_path else Path.home()/'Saved Games'/'Frontier Developments'/'Elite Dangerous'/'Status.json'
        # Caminho do mapa aberto. Permite substituir uma versão sem tocar no
        # ficheiro principal do mesmo PML.
        self.current_map_path = None
        self.last_mtime = None
        self.live_status = {}
        self.status_valid = False
        self.retry_status = False
        self.transition_required = False
        self.pending_status_update = None
        self.pending_status_snapshot = None
        self.latest_status_snapshot = None
        self.pending_old_map_resolved = False
        self.pending_destination = None
        self._transition_attempt_snapshot = None
        self._transition_schedule_pending = False
        self._transition_resolution_active = False
        self.radar_input = RadarInput()
        self.options_path = OPTIONS_PATH
        self.scanner_group = 0
        self.bindings_override = ''
        options = load_preferences(self.options_path)
        group = options.get('scanner_group', 0)
        if type(group) is int and 0 <= group <= 25:
            self.scanner_group = group
        override = options.get('bindings_path', '')
        if isinstance(override, str):
            self.bindings_override = override
        self.radar_input.load(self.bindings_override or None)
        self.overlay = OverlayWindow()
        self.overlay_mode_active = False
        self.overlay_navigation_active = False
        self.view = MapView(self.state)
        container = QWidget()
        layout = QVBoxLayout(container)
        controls = QHBoxLayout()
        operations = QHBoxLayout()
        layout.addLayout(operations)
        self.op_buttons = {}
        for button_id, title, callback in [(OP_MARK,'Marker',self.mark),
                                           (OP_MARK_DEPOSIT,'Mark deposit',self.mark_deposit),
                                           (OP_MARK_RIG,'Mark rig',self.mark_rig),
                                           (OP_EXIT,'Exit',self.close)]:
            button = QPushButton(translate('MapperWindow', title))
            button.clicked.connect(callback)
            operations.addWidget(button)
            self.op_buttons[button_id] = button
        layout.addLayout(controls)
        for label, field, minimum in [('Cobertura:','coverage_width_m',100),('Scanner:','scanner_range_m',500)]:
            spin = MetresSpinBox()
            self.parameter_spins[field] = spin
            spin.setRange(minimum,5000)
            spin.setSingleStep(100)
            spin.setValue(int(getattr(self.state,field)))
            # field=field fixa o atributo desta iteração. Sem isso, todas as
            # funções lambda usariam o último atributo do ciclo quando chamadas.
            spin.valueChanged.connect(lambda value, field=field: self.set_parameter(field,value))
        self.search_azimuth_spin = AzimuthSpinBox()
        self.search_azimuth_spin.setRange(0,359)
        self.search_azimuth_spin.setValue(0)
        self.search_azimuth_spin.setToolTip(translate('MapperWindow', 'Initial bearing for the next search: 000=North, 090=East, 180=South, 270=West.'))
        self.parameter_spins['search_azimuth'] = self.search_azimuth_spin
        for control_id, title, callback, enabled in [
                ('search_button', 'Start search', self.handle_search_button, True),
                ('skip_button', 'Skip next', self.handle_skip_button, True),
                ('overlay_button', 'Overlay', self.toggle_overlay, False)]:
            button = QPushButton(translate('MapperWindow', title))
            setattr(self, control_id, button)
            button.setEnabled(enabled)
            button.clicked.connect(callback)
        self.follow = QCheckBox(translate('MapperWindow', 'Centre'))
        self.follow.toggled.connect(lambda checked: self.view.recenter() if checked else None)
        # Barra inferior consolidada numa única linha
        self.info_bar = QHBoxLayout()
        self.info_left = QLabel(translate('MapperWindow', 'Waiting for Status.json'))
        self.info_right = QLabel('FUEL : —')
        self.info_bar.addWidget(self.info_left, 1)
        self.info_bar.addWidget(self.info_right)
        layout.addLayout(self.info_bar)
        
        self.radar_info = QLabel(translate('MapperWindow', 'Radar: waiting for the game'))
        self.radar_info.setToolTip(self.radar_input.message)
        layout.addWidget(self.radar_info)
        layout.addWidget(self.view,1)
        # O rodapé mantém uma única linha: ficheiro ativo à esquerda e a
        # instrução de navegação alinhada à direita.
        footer = QHBoxLayout()
        self.navigation = QLabel(translate('MapperWindow', 'Suggested sec.: —'))
        self.map_flag_icons = QLabel()
        self.map_flag_icons.setFixedHeight(22)
        footer.addWidget(self.map_flag_icons)
        self.map_file_info = QLabel(translate('MapperWindow', 'Map: not saved yet'))
        self.map_file_info.setTextFormat(Qt.TextFormat.PlainText)
        footer.addWidget(self.map_file_info, 1)
        footer.addWidget(self.navigation)
        layout.addLayout(footer)
        self.setup_steering(layout, options if isinstance(options,dict) else {})
        self.build_layout_options(layout, operations, controls, options)
        self.setCentralWidget(container)
        self.view.clicked.connect(self.place_rig)
        self.view.menu_requested.connect(self.marker_menu)
        escape = QShortcut(QKeySequence('Escape'),self)
        escape.activated.connect(self.cancel_placement)
        for key, callback in [('Home',self.view.recenter),('+',lambda:self.view.zoom_at(QPointF(self.view.rect().center()),1.15)),('-',lambda:self.view.zoom_at(QPointF(self.view.rect().center()),1/1.15))]:
            shortcut = QShortcut(QKeySequence(key),self)
            shortcut.activated.connect(callback)
        # O temporizador pertence à janela e corre no ciclo Qt principal.
        # O mesmo ciclo Qt trata dos eventos da janela principal e do overlay.
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(50)
        self.radar_timer = QTimer(self)
        self.radar_timer.timeout.connect(self.update_radar)
        self.radar_timer.start(16)
        screen = QApplication.primaryScreen().availableGeometry()
        self.overlay.move(screen.x()+(screen.width()-self.overlay.width())//2,screen.y()+40)
        self.poll()

    def radar_options(self):
        self.options_button.toggle()

    def update_radar(self):
        now = time.monotonic()
        s = self.state
        if self.transition_required:
            self.view.radar.waves.clear()
            self.radar_info.setText(translate('MapperWindow', 'Radar: waiting for map change'))
            return
        if s.read_only:
            self.view.radar.waves.clear()
            return
        flags = self.live_status.get('Flags', 0)
        eligible = (self.status_valid and bool(flags & 0x04000000) and bool(flags & 0x08000000)
                    and self.live_status.get('FireGroup') == self.scanner_group
                    and self.live_status.get('GuiFocus', 0) == 0
                    and s.rhino_lat is not None and s.center_lat is not None
                    and bool(self.radar_input.bindings))
        focused = self.radar_input.game_focused() if self.radar_input.bindings else False
        enabled = eligible and focused
        down = self.radar_input.down() if focused else None
        if self.view.radar.tick(s, now, enabled, down, (id(s), s.body_key, s.map_generation)):
            self.view.update()
        text = (translate('MapperWindow', 'Radar: controls unavailable — check Options') if not self.radar_input.bindings else
                translate('MapperWindow', 'Radar: pulse in progress') if self.view.radar.active is not None else
                translate('MapperWindow', 'Radar: ready') if enabled else
                translate('MapperWindow', 'Radar: waiting for a valid SRV position') if not self.status_valid else
                translate('MapperWindow', 'Radar: waiting for game focus') if not focused else
                translate('MapperWindow', 'Radar: select Analysis Mode') if not flags & 0x08000000 else
                translate('MapperWindow', 'Radar: select group {group}').format(group=chr(65+self.scanner_group)) if self.live_status.get('FireGroup') != self.scanner_group else
                translate('MapperWindow', 'Radar: close the game panel'))
        self.radar_info.setText(text)

    def set_parameter(self, field, value):
        """Atualiza um parâmetro numérico do estado e pede um novo desenho.
        field é o nome do atributo; value é o valor emitido pelo controlo numérico."""
        if self.state.read_only:
            return
        setattr(self.state,field,value)
        self.view.update()

    def show_map_library(self):
        """Abre uma janela de consulta independente do mapa e do jogo."""
        if not hasattr(self, 'map_library') or self.map_library is None:
            self.map_library = MapLibraryWindow(
                self,
                self.view.dark_theme,
                preferences=self.preferences,
                save_preference=self.save_preference,
            )
        self.map_library.show()
        self.map_library.raise_()
        self.map_library.activateWindow()

    def choose_status(self):
        """Abre o seletor de Status.json e lê imediatamente o ficheiro escolhido.
        Cancelar o diálogo mantém o caminho e o estado anteriores."""
        path, _ = QFileDialog.getOpenFileName(self,'Escolher Status.json',str(self.status_path),'JSON (*.json)')
        if path:
            self.status_path = Path(path)
            self.status_valid = False
            self.last_mtime = None
            self.poll()

    def start_search(self):
        """Inicia a busca na posição atual ou pede confirmação para substituir o Datum.
        A atualização posterior abre o overlay quando se entra neste modo."""
        if self.transition_required or self.map_is_read_only():
            return
        if self.state.search_started and QMessageBox.question(
                self, translate('MapperWindow', 'Start search'),
                translate('MapperWindow', 'Replace the current Datum?')) != QMessageBox.StandardButton.Yes:
            return
        self.search_azimuth_spin.interpretText()
        if not self.state.start_search(self.search_azimuth_spin.value()):
            QMessageBox.information(
                self, translate('MapperWindow', 'Start search'),
                translate('MapperWindow', 'Enter the SRV first and wait for its position.'))
        self.refresh()

    def handle_search_button(self):
        """Alterna entre iniciar e terminar o modo de busca."""
        if self.state.search_started:
            if QMessageBox.question(
                    self, translate('MapperWindow', 'Stop search'),
                    translate('MapperWindow', 'Stop the current search?')) == QMessageBox.StandardButton.Yes:
                self.state.search_started = False
                self.state.search_paused = False
                self.state.search_pause_point = None
                self.state.return_to_pause = False
                self.state.next_target_xy = None
                if self.state.active_nav_target is None:
                    self.overlay.hide()
                    self.overlay_mode_active = False
                self.refresh()
        else:
            self.start_search()

    def skip_next(self):
        """Avança para o destino seguinte através do núcleo e atualiza a apresentação.
        O núcleo regista o destino como saltado, distinguindo-o de um destino alcançado."""
        if self.transition_required:
            return
        self.state.skip_next()
        self.refresh()

    def handle_skip_button(self):
        """Retoma a busca imediatamente se estiver em pausa; senão salta o destino atual."""
        if self.transition_required or self.state.read_only:
            return
        if self.state.search_paused or self.state.return_to_pause:
            self.state.search_paused = False
            self.state.search_pause_point = None
            self.state.return_to_pause = False
            self.state.active_nav_target = None
            self.statusBar().showMessage(translate('MapperWindow', 'Search resumed.'))
            self.refresh()
        elif self.state.search_started:
            self.skip_next()

    def toggle_overlay(self):
        """Alterna a visibilidade apenas quando o modo atual autoriza o overlay.
        A decisão manual mantém-se nas atualizações seguintes dentro do mesmo modo."""
        if self.transition_required or not (self.state.overlay_allowed() or (self.state.in_srv and self.direction_test_active())):
            return
        self.overlay_mode_active = not self.overlay_mode_active
        self.refresh()

    def toggle_assistance(self):
        """Keep steering assistance inactive while the active map is unresolved."""
        if self.transition_required:
            self.stop_assistance('Assistência desligada: mudança de mapa pendente')
            return
        super().toggle_assistance()

    def update_assistance(self):
        """Skip assistance/navigation calculations for an unresolved location."""
        if self.transition_required:
            return
        super().update_assistance()

    def refresh(self, redraw_map=True):
        """Sincroniza combustível, navegação, botão Overlay e desenho com o estado.
        Só a transição para um modo autorizado abre automaticamente o overlay."""
        s = self.state
        fuel = s.fuel_percent
        if fuel is None:
            self.info_right.setText('FUEL : —')
        else:
            level = '⛔ Sem combustível' if fuel <= 0 else '🔴 Crítico' if fuel <= 15 else '⚠ Baixo' if fuel <= 30 else '✓ Normal'
            self.info_right.setText(f'FUEL : {fuel:.0f}% {level}')
            
        if self.transition_required:
            self.overlay.set_navigation('—', '—', '#888888', 'white', '')
            navigation = None
        else:
            navigation = s.overlay_navigation()
            self.overlay.set_navigation(*navigation)
        
        # O overlay só deve estar visível se:
        # 1. O modo for autorizado (search_started, active_nav, etc.)
        # 2. O comandante estiver no Rhino (in_srv)
        # 3. O utilizador não o tenha escondido manualmente (overlay_mode_active)
        # O foco não condiciona esta janela: clicar nela para a mover ou
        # redimensionar retira naturalmente o foco ao jogo.
        
        # Distinguir o fim da navegação de uma suspensão temporária (fora
        # do veículo ou sem foco). Só iniciar um novo modo repõe a escolha
        # automática; sair e voltar ao Rhino conserva a escolha manual.
        navigating = bool(s.search_started or s.active_nav_target is not None or s.return_to_pause or self.direction_test_active())
        if navigating and not self.overlay_navigation_active:
            self.overlay_mode_active = True
        elif not navigating:
            self.overlay_mode_active = False
        self.overlay_navigation_active = navigating
        allowed = (not self.transition_required and
                    (s.overlay_allowed() or (s.in_srv and self.direction_test_active())))
        self.overlay_button.setEnabled(allowed)
        
        should_be_visible = allowed and self.overlay_mode_active
        
        if not allowed:
            self.overlay.hide()
        elif should_be_visible:
            if not self.overlay.isVisible():
                self.overlay.show()
        else:
            self.overlay.hide()

        # Ativar/Desativar botões conforme a presença no Rhino
        in_srv = s.in_srv
        self.search_button.setEnabled(in_srv and not s.read_only and not self.transition_required)
        self.skip_button.setEnabled(in_srv and not self.transition_required and
                                    (s.search_started or s.search_paused or s.return_to_pause))
        
        # Botões de marcação e operações
        if hasattr(self, 'op_buttons'):
            for button_id, btn in self.op_buttons.items():
                if button_id in (OP_MARK, OP_MARK_DEPOSIT, OP_MARK_RIG):
                    btn.setEnabled(in_srv and not s.read_only and not self.transition_required)

        # Atualizar textos e estilos dos botões de busca e salto/pausa
        if hasattr(self, 'search_button'):
            self.search_button.setText(translate('MapperWindow', 'Stop search' if s.search_started else 'Start search'))

        if hasattr(self, 'skip_button'):
            if s.search_paused or s.return_to_pause:
                self.skip_button.setText(translate('MapperWindow', 'Search paused'))
                is_bright = int(time.monotonic() * 2) % 2 == 0
                bg = '#ffd21c' if is_bright else '#d4a000'
                self.skip_button.setStyleSheet(f"background-color: {bg}; color: #101010; font-weight: bold; border: 1px solid #705000; border-radius: 4px; padding: 3px 8px;")
            else:
                self.skip_button.setText(translate('MapperWindow', 'Skip next'))
                self.skip_button.setEnabled(in_srv and not self.transition_required and
                                            s.search_started and s.next_target_xy is not None)
                self.skip_button.setStyleSheet("")

        from map_badges import flag_pixmap
        self.map_flag_icons.setPixmap(flag_pixmap(s.favorite, s.protected))
        self.map_flag_icons.setVisible(s.favorite or s.protected)
        if self.current_map_path and self.current_map_path.exists():
            stamp = time.strftime('%Y-%m-%d %H:%M', time.localtime(self.current_map_path.stat().st_mtime))
            self.map_file_info.setText(
                f'{self.current_map_path.name} — {stamp}'
                + (f" · {translate('MapperWindow', 'Mining only')}" if s.mining_only else ''))
        else:
            self.map_file_info.setText(translate('MapperWindow', 'Map not saved yet'))
        if self.transition_required:
            self.navigation.setText(translate('MapperWindow', 'Waiting for map change'))
        elif s.active_nav_target is not None:
            self.navigation.setText(translate('MapperWindow', 'Navigating: {system} | {body} | {target}').format(system=navigation[0], body=navigation[1], target=navigation[4]))
        elif s.return_to_pause:
            self.navigation.setText(translate('MapperWindow', 'Returning to pause point | {system} | {body}').format(system=navigation[0], body=navigation[1]))
        elif s.search_started and s.next_target_xy is None:
            self.navigation.setText(translate('MapperWindow', 'Circular search completed'))
        else:
            self.navigation.setText(translate('MapperWindow', 'Suggested sec.: {system} | {body}').format(system=navigation[0], body=navigation[1]))

        if redraw_map:
            self.view.update()

    def map_signature(self):
        s = self.state
        nav_sig = (s.active_nav_target.get('x'), s.active_nav_target.get('y')) if s.active_nav_target else None
        return (s.body_key, s.rhino_lat, s.rhino_lon, s.rhino_heading, s.in_srv,
                len(s.points), s.next_target_xy, len(s.route_history),
                nav_sig, s.search_paused, s.search_pause_point, s.return_to_pause)

    def active_map_corresponds(self, system, body, latitude, longitude):
        """Evaluate incoming SRV location without changing the active map."""
        state = self.state
        if not (state.body_key and state.pml_id.strip()
                and state.pml_center_lat is not None
                and state.pml_center_lon is not None):
            return None
        return corresponds_to_map(state, system, body, latitude, longitude)

    def evaluate_status_update(self, status_update, correspondence, raw_status=None):
        """Record the first unresolved mismatch for the future lifecycle step."""
        if (not self.transition_required and status_update.accepted
                and (status_update.location_changed or correspondence is False)):
            self.transition_required = True
            self.pending_status_update = status_update
            snapshot = self.latest_status_snapshot if raw_status is None else raw_status
            self.pending_status_snapshot = copy.deepcopy(snapshot)
            self.stop_assistance('Assistência desligada: mudança de mapa pendente')
            self.schedule_pending_transition()

    def schedule_pending_transition(self):
        """Defer future lifecycle resolution until the current poll has returned."""
        if self._transition_schedule_pending or self._transition_resolution_active:
            return
        self._transition_schedule_pending = True
        QTimer.singleShot(0, self._run_pending_transition)

    def _run_pending_transition(self):
        """Run the future lifecycle seam once without implementing Step 3 yet."""
        self._transition_schedule_pending = False
        if not self.transition_required or self._transition_resolution_active:
            return
        self._transition_resolution_active = True
        try:
            self._transition_attempt_snapshot = copy.deepcopy(self.latest_status_snapshot)
            if self.resolve_pending_transition() is not None:
                self.activate_pending_destination()
        finally:
            self._transition_resolution_active = False
            if (self.transition_required and self.pending_destination is None
                    and self.latest_status_snapshot != self._transition_attempt_snapshot):
                self.schedule_pending_transition()

    def resolve_pending_transition(self):
        """Resolve the old map and prepare, but do not install, a destination."""
        if not self.transition_required or self.pending_destination is not None:
            return self.pending_destination
        try:
            if not self.pending_old_map_resolved:
                if not self.prepare_to_replace_current_map(
                        translate('MapperWindow', 'Change location'),
                        translate('MapperWindow', 'changing location'), allow_cancel=False):
                    return None
                self.pending_old_map_resolved = True
            self.pending_destination = self.prepare_pending_destination()
        except (OSError, ValueError, TypeError, KeyError, AttributeError,
                OverflowError, ZeroDivisionError) as exc:
            QMessageBox.critical(
                self, translate('MapperWindow', 'Error preparing map change'), str(exc))
            return None
        return self.pending_destination

    def clear_transition_state(self):
        """Clear lifecycle-only state after a confirmed destination activation."""
        self.transition_required = False
        self.pending_status_update = None
        self.pending_status_snapshot = None
        self.latest_status_snapshot = None
        self.pending_old_map_resolved = False
        self.pending_destination = None
        self._transition_attempt_snapshot = None
        self._transition_schedule_pending = False
        self._transition_resolution_active = False

    def activate_pending_destination(self):
        """Activate a prepared destination after latest-telemetry validation."""
        if (not self.transition_required or not self.pending_old_map_resolved
                or self.pending_destination is None):
            return False
        status = self._current_transition_status()
        if status is None:
            return False
        destination = self.pending_destination
        candidate = destination.get('state')
        if candidate is None:
            return False
        system, body = status['StarSystem'], status['BodyName']
        latitude, longitude = float(status['Latitude']), float(status['Longitude'])
        if not corresponds_to_map(candidate, system, body, latitude, longitude):
            self.pending_destination = None
            return False
        try:
            candidate.process_status(status)
            if not corresponds_to_map(candidate, system, body, latitude, longitude):
                self.pending_destination = None
                return False
            self.install_prepared_map(
                candidate,
                destination.get('source_text', translate('MapperWindow', 'Loaded map')),
                destination.get('path'),
                poll_after_install=False)
        except (OSError, ValueError, TypeError, KeyError, AttributeError,
                OverflowError, ZeroDivisionError) as exc:
            QMessageBox.critical(
                self, translate('MapperWindow', 'Error activating map change'), str(exc))
            return False
        if not corresponds_to_map(self.state, system, body, latitude, longitude):
            return False
        self.status_valid = True
        self.clear_transition_state()
        self.refresh()
        return True

    def install_loaded_map(self, candidate, source_text='Loaded map', source_path=None):
        """Install a manual map and supersede pending lifecycle state if valid."""
        result = super().install_loaded_map(candidate, source_text, source_path)
        if result and self.transition_required:
            status = self._current_transition_status()
            if (status is not None and corresponds_to_map(
                    self.state, status['StarSystem'], status['BodyName'],
                    float(status['Latitude']), float(status['Longitude']))):
                self.clear_transition_state()
                self.refresh()
        return result

    def _current_transition_status(self):
        """Return the latest valid SRV status suitable for destination preparation."""
        status = self.latest_status_snapshot or self.pending_status_snapshot
        if not status or not (int(status.get('Flags', 0)) & 0x04000000):
            return None
        if not (status.get('StarSystem', '').strip()
                and status.get('BodyName', '').strip()
                and status.get('Latitude') is not None
                and status.get('Longitude') is not None):
            return None
        return copy.deepcopy(status)

    def prepare_pending_destination(self):
        """Prepare a detached existing or new destination for Slice 3.3."""
        status = self._current_transition_status()
        if status is None:
            return None
        system = status['StarSystem']
        body = status['BodyName']
        latitude = float(status['Latitude'])
        longitude = float(status['Longitude'])
        matches = self.nearby_pml_maps(system, body, latitude, longitude)
        matches = newest_by_pml(matches)
        if len(matches) > 1:
            matches.sort(key=lambda item: item[1].stat().st_mtime, reverse=True)
            labels = [
                translate('MapperWindow', '[{pml_id}] — saved {timestamp} — {filename}').format(
                    pml_id=candidate.pml_id,
                    timestamp=datetime.fromtimestamp(path.stat().st_mtime).strftime('%Y-%m-%d %H:%M'),
                    filename=path.name)
                for _, path, candidate in matches
            ]
            chosen_index = self.choose_list_item(
                translate('MapperWindow', 'Several nearby PMLs'),
                translate('MapperWindow', 'Choose the PML:'), labels)
            if chosen_index is None:
                return None
            path, candidate = matches[chosen_index][1:]
        elif matches:
            _, path, candidate = matches[0]
        else:
            candidate = MapperState()
            candidate.process_status(status)
            if not self.setup_new_pml(candidate):
                return None
            path = self.pml_path(candidate)
            if path is None:
                return None
            path.parent.mkdir(parents=True, exist_ok=True)
            candidate.save(path)
            return dict(state=candidate, path=path,
                        source_text=translate(
                            'MapperWindow', 'PML [{pml_id}] created').format(pml_id=candidate.pml_id))

        status['StarSystem'] = candidate.system
        status['BodyName'] = candidate.body
        candidate.process_status(status)
        prepared = self.prepare_loaded_map(candidate, path)
        if prepared is None:
            return None
        candidate, path = prepared
        return dict(state=candidate, path=path,
                    source_text=translate(
                        'MapperWindow', 'PML [{pml_id}] prepared').format(pml_id=candidate.pml_id))

    def poll(self, reloading_map=False):
        """Lê Status.json se a data mudou e atualiza a telemetria e a vista.
        reloading_map protege a abertura inicial de um mapa contra dados de outro corpo.
        Uma leitura incompleta não regista a data: será repetida no próximo disparo do temporizador."""
        changed = False
        try:
            status = read_status_if_changed(
                self.status_path,
                self.last_mtime,
                force=self.retry_status,
            )
            if status is not None:
                mtime, data = status
                self.retry_status = False
                if not data.get('StarSystem') and data.get('BodyName') == self.state.body:
                    # A mesma regra de process_status tem de preceder a
                    # verificação de planeta feita na abertura do ficheiro.
                    data['StarSystem'] = self.state.system
                # Ao abrir um ficheiro, telemetria de outro planeta não deve
                # apagar o mapa que o utilizador acabou de escolher.
                if reloading_map and f"{data.get('StarSystem','')}|{data.get('BodyName','')}" != self.state.body_key:
                    self.status_valid = False
                    self.last_mtime = mtime
                    self.info_left.setText(translate(
                        'MapperWindow', '{system} — {body} | Map loaded; Rhino on another body').format(
                            system=self.state.system, body=self.state.body))
                    self.refresh()
                    return
                incoming_system = data.get('StarSystem', '')
                incoming_body = data.get('BodyName', '')
                if not incoming_system and incoming_body == self.state.body:
                    incoming_system = self.state.system
                incoming_lat = data.get('Latitude')
                incoming_lon = data.get('Longitude')
                correspondence = None
                if (data.get('Flags', 0) & 0x04000000
                        and incoming_lat is not None and incoming_lon is not None):
                    correspondence = self.active_map_corresponds(
                        incoming_system, incoming_body,
                        float(incoming_lat), float(incoming_lon))
                old_body = self.state.body_key
                before = self.map_signature()
                status_update = self.state.process_status(
                    data, record_position=correspondence is not False)
                accepted = bool(status_update)
                self.live_status = data
                self.live_status['Flags'] = int(data.get('Flags', 0))
                self.status_valid = accepted
                if accepted:
                    self.latest_status_snapshot = copy.deepcopy(data)
                    if (self.transition_required
                            and self.latest_status_snapshot != self._transition_attempt_snapshot):
                        self.schedule_pending_transition()
                self.evaluate_status_update(status_update, correspondence, data)
                changed = before != self.map_signature()
                # Só memorizamos a data depois de processar uma leitura válida.
                self.last_mtime = mtime
                if accepted:
                    if not self.transition_required:
                        self.observe_steering()
                    if old_body != self.state.body_key:
                        self.cancel_placement()
                        self.view.scale = 0.08
                        self.view.recenter()
                        # A telemetria identifica o planeta; a operação de mapas
                        # decide se existe um PML conhecido até 10 km ou se é
                        # preciso pedir a identificação de um novo PML.
                        self.open_or_create_pml_for_current_position()
                        changed = True
                    if self.follow.isChecked():
                        self.view.recenter()
                    s = self.state
                    self.info_left.setText(translate(
                        'MapperWindow', '{system} — {body} | Lat {latitude:.5f}° Lon {longitude:.5f}° | Points {points}').format(
                            system=s.system, body=s.body, latitude=s.rhino_lat,
                            longitude=s.rhino_lon, points=len(s.points)))
                else:
                    flags = int(data.get('Flags', 0))
                    if flags != 0 and not (flags & 0x04000000):
                        self.info_left.setText(translate('MapperWindow', 'Commander is not in the SRV (on foot or aboard the ship).'))
                    else:
                        self.info_left.setText(translate('MapperWindow', 'Waiting for the Rhino position.'))
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            self.status_valid = False
            self.retry_status = True
            self.info_left.setText(translate(
                'MapperWindow', 'Waiting for a valid Status.json read: {error}').format(error=exc))

        # Mesmo sem telemetria nova, atualizar navegação e intermitência.
        self.refresh(redraw_map=changed)

    def closeEvent(self, event):
        """Para o temporizador e fecha o overlay antes de fechar a janela principal.
        É chamado tanto pelo X como pelo botão Sair, que utiliza close()."""
        if not self.confirm_pml_exit():
            event.ignore()
            return
        self.timer.stop()
        self.radar_timer.stop()
        self.assist_timer.stop()
        self.stop_assistance()
        map_library = getattr(self, 'map_library', None)
        if map_library is not None:
            map_library.close()
        self.steering_input.close()
        self.overlay.close()
        super().closeEvent(event)


# Este bloco só corre ao executar o ficheiro, nunca quando um teste o importa.
# QApplication é única e exec() aguarda eventos até todas as janelas fecharem.
def main():
    """Cria a aplicação Qt e devolve o código de saída do ciclo de eventos.
    É chamada pela entrada principal ou pela execução direta deste módulo.
    A variável window mantém a janela viva durante toda a execução de exec().
    """
    # Identidade própria na barra de tarefas do Windows ao executar via Python.
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Rhino.SurfaceMapper')
    app = QApplication(sys.argv)
    app.setApplicationName('Rhino Surface Mapper')
    app.setWindowIcon(QIcon(str(Path(__file__).resolve().parent/'assets'/'Rhino_App.svg')))
    options = load_preferences(OPTIONS_PATH)
    translator = install_translator(app, options.get('language'))
    window = MapperWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
