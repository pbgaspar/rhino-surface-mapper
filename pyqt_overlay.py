"""Transparent, movable and resizable Qt overlay for the Mapper."""


from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget


class OverlayWindow(QWidget):
    """Mostra orientação e distância, mantendo a proporção durante o resize."""

    def __init__(self):
        """Configura uma janela sem moldura, transparente e sempre no topo.
        As variáveis de interação distinguem passar o rato, mover e redimensionar."""
        super().__init__()
        # Frameless remove a barra de título; StaysOnTop mantém a janela à frente;
        # Tool identifica-a como auxiliar. O movimento será tratado pelo nosso código.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        # A transparência é por píxel. O fundo pintado com alfa 1 continua quase
        # invisível, mas permite receber eventos do rato no interior da janela.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # Mostrar automaticamente não deve retirar o foco ao jogo.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)

        self.hovered = False
        self.dragging = False
        self.resizing = False
        self.drag_offset = QPoint()
        self.margin = 10
        self.aspect_ratio = 360 / 150
        self.heading_text = "—"
        self.distance_text = "—"
        self.heading_color = QColor("#888888")
        self.distance_color = QColor("white")
        self.target_name = ""
        self.assistance_notice = ''
        self.assistance_warning = False
        self.resize(360, 150)

    def set_navigation(self, heading_text, distance_text, heading_color, distance_color, target_name=""):
        """Recebe os textos, as cores e opcionalmente o nome do alvo calculados pelo núcleo."""
        if (self.heading_text == heading_text and self.distance_text == distance_text
                and self.heading_color == QColor(heading_color)
                and self.distance_color == QColor(distance_color)
                and self.target_name == target_name):
            return
        self.heading_text = heading_text
        self.distance_text = distance_text
        self.heading_color = QColor(heading_color)
        self.distance_color = QColor(distance_color)
        self.target_name = target_name
        self.update()

    def set_assistance_notice(self, text, warning=False):
        """Reserva uma faixa do overlay para o estado da assistência/aviso."""
        if text != self.assistance_notice or warning != self.assistance_warning:
            self.assistance_notice = text
            self.assistance_warning = warning
            self.update()

    def paintEvent(self, event):
        """Desenha o fundo quase transparente, a moldura e os textos de navegação.
        O tamanho das letras acompanha a altura da janela."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Quase invisível, mas permite receber o rato na área do overlay.
        painter.fillRect(self.rect(), QColor(255, 255, 255, 1))

        # A moldura só aparece durante interação ou ao passar o rato.
        if self.hovered or self.dragging or self.resizing:
            painter.setPen(QPen(QColor(255, 0, 0, 220), 2))
            painter.drawRect(1, 1, self.width() - 2, self.height() - 2)

        painter.save()
        if self.assistance_notice:
            painter.scale(1,.78)
        if self.target_name:
            name_font = QFont("Segoe UI", max(10, int(self.height() * 0.17)), QFont.Weight.DemiBold)
            heading_font = QFont("Segoe UI", max(13, int(self.height() * 0.28)), QFont.Weight.Bold)
            distance_font = QFont("Segoe UI", max(11, int(self.height() * 0.22)), QFont.Weight.Bold)

            h = float(self.height())
            w = float(self.width())
            painter.setPen(QColor("#80c8ff"))
            painter.setFont(name_font)
            # O destino pode incluir o tipo, por exemplo "[Depósito] ...".
            # Reduzimos apenas esta legenda até caber, em vez de centrar um
            # texto demasiado largo e cortar precisamente o seu início.
            while (painter.fontMetrics().horizontalAdvance(self.target_name) > w - 12
                   and name_font.pointSize() > 8):
                name_font.setPointSize(name_font.pointSize() - 1)
                painter.setFont(name_font)
            painter.drawText(
                QRectF(6.0, 4.0, w - 12.0, h * 0.24),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                self.target_name,
            )

            painter.setPen(self.heading_color)
            painter.setFont(heading_font)
            painter.drawText(
                QRectF(0.0, h * 0.26, w, h * 0.40),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                self.heading_text,
            )

            painter.setPen(self.distance_color)
            painter.setFont(distance_font)
            painter.drawText(
                QRectF(0.0, h * 0.66, w, h * 0.30),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                self.distance_text,
            )
        else:
            heading_font = QFont("Segoe UI", max(14, int(self.height() * 0.32)), QFont.Weight.Bold)
            distance_font = QFont("Segoe UI", max(12, int(self.height() * 0.23)), QFont.Weight.Bold)

            painter.setPen(self.heading_color)
            painter.setFont(heading_font)
            painter.drawText(
                self.rect().adjusted(0, 8, 0, -self.height() // 2),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                self.heading_text,
            )

            painter.setPen(self.distance_color)
            painter.setFont(distance_font)
            painter.drawText(
                self.rect().adjusted(0, self.height() // 2 - 8, 0, -8),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                self.distance_text,
            )

        painter.restore()
        if self.assistance_notice:
            zone = QRectF(3,self.height()*.80,self.width()-6,self.height()*.18)
            painter.fillRect(zone,QColor('#18232e'))
            painter.setPen(QColor('#ffd21c' if self.assistance_warning else '#a8d7eb'))
            font = QFont('Segoe UI',max(8,int(self.height()*.095)),QFont.Weight.Bold)
            painter.setFont(font)
            while painter.fontMetrics().horizontalAdvance(self.assistance_notice)>zone.width()-6 and font.pointSize()>5:
                font.setPointSize(font.pointSize()-1)
                painter.setFont(font)
            painter.drawText(zone,Qt.AlignmentFlag.AlignCenter,self.assistance_notice)

    def enterEvent(self, event):
        """Assinala a entrada do rato e pede o desenho da moldura."""
        self.hovered = True
        self.update()

    def leaveEvent(self, event):
        """Retira a moldura ao sair, exceto durante uma operação de arrasto.
        Repõe também o cursor normal."""
        if not self.dragging and not self.resizing:
            self.hovered = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def hit_test(self, pos):
        """Identifica interior, bordas e cantos para mover/redimensionar."""
        x, y = pos.x(), pos.y()
        w, h, m = self.width(), self.height(), self.margin
        left, right = x <= m, x >= w - m
        top, bottom = y <= m, y >= h - m
        if top and left:
            return "nw"
        if top and right:
            return "ne"
        if bottom and left:
            return "sw"
        if bottom and right:
            return "se"
        if left:
            return "w"
        if right:
            return "e"
        if top:
            return "n"
        if bottom:
            return "s"
        return "move"

    def mouseMoveEvent(self, event):
        """Atualiza o cursor ou executa a operação iniciada com o botão esquerdo.
        Usa coordenadas globais para que a própria deslocação da janela não altere a referência."""
        mode = self.hit_test(event.position().toPoint())
        if not event.buttons():
            cursors = {
                "nw": Qt.CursorShape.SizeFDiagCursor, "se": Qt.CursorShape.SizeFDiagCursor,
                "ne": Qt.CursorShape.SizeBDiagCursor, "sw": Qt.CursorShape.SizeBDiagCursor,
                "w": Qt.CursorShape.SizeHorCursor, "e": Qt.CursorShape.SizeHorCursor,
                "n": Qt.CursorShape.SizeVerCursor, "s": Qt.CursorShape.SizeVerCursor,
                "move": Qt.CursorShape.SizeAllCursor,
            }
            self.setCursor(cursors[mode])
            return

        global_pos = event.globalPosition().toPoint()
        if self.dragging:
            self.move(global_pos - self.drag_offset)
        elif self.resizing:
            self.resize_proportional(global_pos)
        self.update()

    def resize_proportional(self, global_pos):
        """Calcula o novo retângulo mantendo largura/altura igual a 2,40.
        O lado oposto ao arrasto fica fixo; nas bordas simples o outro eixo cresce em torno do centro.
        Impõe largura mínima de 180 píxeis e arredonda dimensões para números inteiros."""
        start = self.start_geometry
        dx = global_pos.x() - self.press_global.x()
        dy = global_pos.y() - self.press_global.y()
        min_w = 180
        min_h = round(min_w / self.aspect_ratio)
        mode = self.resize_mode

        # n/s/e/w significam norte/sul/este/oeste. Nos cantos, escolhemos o eixo
        # com maior deslocamento e calculamos o outro através da proporção fixa.
        if mode in ("se", "sw", "ne", "nw"):
            if abs(dx) >= abs(dy):
                new_w = max(min_w, start.width() + (dx if "e" in mode else -dx))
                new_h = max(min_h, round(new_w / self.aspect_ratio))
            else:
                new_h = max(min_h, start.height() + (dy if "s" in mode else -dy))
                new_w = max(min_w, round(new_h * self.aspect_ratio))
            x = start.x() if "e" in mode else start.x() + start.width() - new_w
            y = start.y() if "s" in mode else start.y() + start.height() - new_h
        elif mode in ("n", "s"):
            new_h = max(min_h, start.height() + (dy if mode == "s" else -dy))
            new_w = max(min_w, round(new_h * self.aspect_ratio))
            x = start.x() + (start.width() - new_w) // 2
            y = start.y() if mode == "s" else start.y() + start.height() - new_h
        else:
            new_w = max(min_w, start.width() + (dx if mode == "e" else -dx))
            new_h = max(min_h, round(new_w / self.aspect_ratio))
            x = start.x() if mode == "e" else start.x() + start.width() - new_w
            y = start.y() + (start.height() - new_h) // 2

        self.setGeometry(int(x), int(y), int(new_w), int(new_h))

    def mousePressEvent(self, event):
        """Guarda a posição global e o retângulo inicial ao premir o botão esquerdo.
        O interior inicia movimento; uma borda ou canto inicia redimensionamento."""
        if event.button() != Qt.MouseButton.LeftButton:
            return
        mode = self.hit_test(event.position().toPoint())
        self.press_global = event.globalPosition().toPoint()
        self.start_geometry = self.geometry()
        self.resize_mode = mode
        if mode == "move":
            self.dragging = True
            self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        else:
            self.resizing = True
        self.update()

    def mouseReleaseEvent(self, event):
        """Termina o movimento ou redimensionamento ao largar o botão esquerdo."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            self.resizing = False
            self.hovered = True
            self.update()
