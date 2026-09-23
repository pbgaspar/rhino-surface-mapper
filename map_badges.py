"""Símbolos vetoriais comuns à biblioteca e ao rodapé do mapa."""
from functools import lru_cache
from pathlib import Path
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QPixmap, QColor, QFont
from PySide6.QtSvg import QSvgRenderer


@lru_cache(maxsize=256)
def flag_pixmap(favorite, protected, deposits=None):
    """Reserva X para zero depósitos; desenha número, mineração e atributos."""
    symbols = []
    prefix = '' if deposits is None else 'X' if not deposits else str(deposits)
    if deposits:
        symbols.append('mining')
    if favorite:
        symbols.append('favorite')
    if protected:
        symbols.append('protected')
    text_width = max(16, len(prefix)*9) if prefix else 0
    pixmap = QPixmap(max(1, text_width + 24*len(symbols)), 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor('#edf1f5'))
    painter.setFont(QFont('Segoe UI', 10))
    if prefix:
        painter.drawText(QRectF(0, 0, text_width, 24), Qt.AlignmentFlag.AlignCenter, prefix)
    for index, symbol in enumerate(symbols):
        renderer = QSvgRenderer(str(Path(__file__).resolve().parent/'assets'/f'{symbol}.svg'))
        renderer.render(painter, QRectF(text_width + index*24 + 2, 2, 20, 20))
    painter.end()
    return pixmap
