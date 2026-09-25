"""Caixa dos depósitos partilhada pelos mapas e pela pré-visualização."""
from pathlib import Path
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPen, QFontMetricsF
from PySide6.QtSvg import QSvgRenderer
from i18n import translate


_DEPOSIT_SIZE_LABELS = {
    'Pequeno': 'Small',
    'Médio': 'Medium',
    'Grande': 'Large',
    'Enorme': 'Huge',
}


def deposit_details(item):
    size = item.get('size', 'Pequeno')
    label = translate('DepositDialog', _DEPOSIT_SIZE_LABELS.get(size, size))
    return f"{label} · {item.get('rigs', 1)} rigs"


def deposit_bounds(point, font, item):
    metrics = QFontMetricsF(font)
    line = max(20.0, metrics.height()+2)
    width = max(line+metrics.horizontalAdvance(item.get('name', 'Depósito')),
                metrics.horizontalAdvance(deposit_details(item)))+16
    return QRectF(point.x()-line/2, point.y()-line/2, width, line*2+8)


def draw_deposit(painter, point, item):
    """Primeira linha com símbolo/nome; segunda com tamanho e rigs."""
    painter.save()
    bounds = deposit_bounds(point, painter.font(), item)
    line = (bounds.height()-8)/2
    painter.setPen(QPen(QColor('white'), 2))
    painter.setBrush(QColor('#172b4d'))
    painter.drawRoundedRect(bounds, 5, 5)
    renderer = QSvgRenderer(str(Path(__file__).resolve().parent/'assets'/'mining.svg'))
    renderer.render(painter, QRectF(bounds.left()+5, bounds.top()+4, line-2, line-2))
    painter.setPen(QColor('white'))
    painter.drawText(QRectF(bounds.left()+line+8, bounds.top()+4,
                           bounds.width()-line-12, line), Qt.AlignmentFlag.AlignVCenter,
                     item.get('name', 'Depósito'))
    painter.drawText(QRectF(bounds.left()+8, bounds.top()+4+line,
                           bounds.width()-16, line), Qt.AlignmentFlag.AlignVCenter, deposit_details(item))
    painter.restore()
