"""Janela de consulta dos mapas guardados, sem alterar o mapa activo."""
import json
import html
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QSize, QRectF, QPointF
from PyQt6.QtGui import QColor, QPainter, QPen, QIcon
from PyQt6.QtWidgets import (QDialog, QLabel, QLineEdit, QListWidget,
    QSplitter, QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    QSizePolicy, QCheckBox, QHBoxLayout, QMessageBox, QPushButton, QStyledItemDelegate)
from deposit_marker import draw_deposit
from PyQt6.QtSvg import QSvgRenderer

from mapper_core import MapperState
from qt_map_operations import MapOperations, maps_directory


def _theme_values(dark):
    if dark:
        return dict(
            foreground='#edf1f5',
            tree_foreground='#ffffff',
            panel='#252d34',
            border='#4c5d6b',
            tree_panel='#2c3239',
            selection='#2f5d78',
            selection_border='#80c8ff',
            indicator='#18222b',
            indicator_border='#8296a8',
            preview_background='#38434a',
            preview_foreground='#d5e2e8',
        )
    return dict(
        foreground='#233448',
        tree_foreground='#233448',
        panel='#ffffff',
        border='#cbd5dd',
        tree_panel='#ffffff',
        selection='#dbe9f2',
        selection_border='#2478c4',
        indicator='#f3f6f8',
        indicator_border='#8296a8',
        preview_background='#ffffff',
        preview_foreground='#233448',
    )


def _tree_stylesheet(colors, arrow_root):
    return f'''
        QTreeWidget {{ background: transparent; border: none; outline: 0; color: {colors['foreground']}; }}
        QTreeWidget::item {{ background: {colors['tree_panel']}; border: 1px solid {colors['border']};
                            border-radius: 5px; margin: 3px 1px; padding: 7px; }}
        QTreeWidget::item:selected {{ background: {colors['selection']}; color: {colors['tree_foreground']};
                                     border: 1px solid {colors['selection_border']}; }}
        QTreeWidget::branch {{ background: transparent; border: none; image: none; }}
        QTreeWidget::branch:has-children:closed {{
            image: url("{arrow_root}/tree-closed.svg");
        }}
        QTreeWidget::branch:has-children:open {{
            image: url("{arrow_root}/tree-open.svg");
        }}
    '''


class MapRowDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        if index.parent().isValid():
            # Conserva a altura dos cartões anteriores, incluindo as margens.
            size.setHeight(max(size.height(), 48))
        return size


class MapTree(QTreeWidget):
    """Desenha os atributos no espaço de indentação, sem coluna adicional."""
    def __init__(self):
        super().__init__()
        self.setIndentation(24)
        self.setItemDelegate(MapRowDelegate(self))
        self.set_theme(True)

    def set_theme(self, dark):
        self.dark_theme = dark
        colors = _theme_values(dark)
        arrow_root = (Path(__file__).resolve().parent / 'assets').as_posix()
        self.setStyleSheet(_tree_stylesheet(colors, arrow_root))
        self.viewport().update()

    def drawBranches(self, painter, rect, index):
        if not index.parent().isValid():
            super().drawBranches(painter, rect, index)
            return
        flags = index.data(Qt.ItemDataRole.UserRole+1)
        if flags is None:
            return
        count, favorite, protected = flags
        painter.save()
        side = min(rect.height()-6, rect.width()-2)
        box = QRectF(rect.right()-side, rect.top()+3, side, side)
        selected = self.selectionModel().isSelected(index)
        colors = _theme_values(self.dark_theme)
        painter.setPen(QPen(QColor(colors['selection_border'] if selected else colors['border']), 1))
        painter.setBrush(QColor(colors['selection'] if selected else colors['tree_panel']))
        painter.drawRoundedRect(box, 4, 4)
        half = side/2
        font = painter.font()
        font.setPixelSize(max(8, int(half*.65)))
        painter.setFont(font)
        painter.setPen(QColor(colors['tree_foreground']))
        text = str(count) if count else 'X'
        while painter.fontMetrics().horizontalAdvance(text) > half-3 and font.pixelSize() > 6:
            font.setPixelSize(font.pixelSize()-1)
            painter.setFont(font)
        painter.drawText(QRectF(box.left()+1, box.top(), half-2 if count else side-2, half),
                         Qt.AlignmentFlag.AlignCenter, text)
        def symbol(name, x, y):
            renderer = QSvgRenderer(str(Path(__file__).resolve().parent/'assets'/f'{name}.svg'))
            renderer.render(painter, QRectF(x+2, y+2, half-4, half-4))
        if count:
            symbol('mining', box.left()+half, box.top())
        if favorite:
            symbol('favorite', box.left(), box.top()+half)
        if protected:
            symbol('protected', box.left()+half, box.top()+half)
        painter.restore()


class MapPreview(QWidget):
    """Pré-visualização simples, somente de leitura, de um mapa seleccionado."""
    def __init__(self):
        super().__init__()
        self.state = None
        self.dark_theme = True
        self.setMinimumSize(460, 300)

    def set_theme(self, dark):
        self.dark_theme = dark
        self.update()

    def show_map(self, state):
        self.state = state
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        colors = _theme_values(self.dark_theme)
        painter.fillRect(self.rect(), QColor(colors['preview_background']))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.state is None:
            painter.setPen(QColor(colors['preview_foreground']))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'Selecciona um mapa para o pré-visualizar.')
            return
        items = self.state.points + self.state.deposits + self.state.rigs + self.state.marks
        if not items:
            painter.setPen(QColor(colors['preview_foreground']))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'Este mapa ainda não contém registos.')
            return
        xs, ys = [item['x'] for item in items], [item['y'] for item in items]
        span = max(1000.0, max(xs)-min(xs), max(ys)-min(ys))
        scale = min((self.width()-40)/span, (self.height()-40)/span)
        cx, cy = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2
        def point(item):
            return ((self.width()/2)+(item['x']-cx)*scale,
                    (self.height()/2)-(item['y']-cy)*scale)
        painter.setPen(QPen(QColor('#3d9147'), 1.5))
        previous = None
        for item in self.state.points:
            current = point(item)
            if previous is not None and not item.get('break_before'):
                painter.drawLine(int(previous[0]), int(previous[1]), int(current[0]), int(current[1]))
            previous = current
        painter.setPen(QPen(QColor('#e17862'), 2))
        for item in self.state.deposits:
            x, y = point(item)
            draw_deposit(painter, QPointF(x, y), item)
        painter.setPen(QPen(QColor('#ffd15c'), 2))
        for item in self.state.marks:
            x, y = point(item)
            painter.drawRect(int(x)-4, int(y)-4, 8, 8)
            painter.drawText(int(x)+8, int(y)-4, item.get('name', 'Marca'))
        painter.setPen(QPen(QColor('#7dc6ff'), 2))
        for item in self.state.rigs:
            x, y = point(item)
            painter.drawEllipse(int(x)-4, int(y)-4, 8, 8)
            painter.drawText(int(x)+8, int(y)-4, item.get('name', 'Rig'))


class MapLibraryWindow(QDialog):
    """Consulta sistemas, planetas, versões e conteúdos dos ficheiros em MAPAS."""
    def __init__(self, parent=None, dark=True):
        super().__init__(parent)
        self.setWindowTitle('Ver e manter mapas')
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowMinMaxButtonsHint |
                            Qt.WindowType.WindowCloseButtonHint)
        self.setMinimumSize(820, 520)
        self.resize(1150, 720)
        self.current_system = None
        self.systems = []
        self.selected_path = None
        self.selected_item = None
        self.dark_theme = dark
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        self.preview = MapPreview()
        self.info = QTextEdit()
        self.info.setReadOnly(True)
        self.info.setMinimumHeight(190)
        left_layout.addWidget(self.preview, 3)
        flags = QHBoxLayout()
        self.favorite_check = QCheckBox('Favorito')
        self.protected_check = QCheckBox('Proteger')
        for checkbox, symbol in ((self.favorite_check, 'favorite'), (self.protected_check, 'protected')):
            checkbox.setIcon(QIcon(str(Path(__file__).resolve().parent/'assets'/f'{symbol}.svg')))
            checkbox.setIconSize(QSize(22, 22))
            checkbox.setEnabled(False)
            flags.addWidget(checkbox)
        flags.addStretch()
        self.open_button = QPushButton('Abrir mapa')
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_selected_map)
        flags.addWidget(self.open_button)
        self.info_panel = QWidget()
        self.info_panel.setObjectName('map_details')
        info_layout = QVBoxLayout(self.info_panel)
        info_layout.addLayout(flags)
        info_layout.addWidget(self.info)
        left_layout.addWidget(self.info_panel, 2)
        body.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.system_title = QLabel('Procura um sistema')
        self.search = QLineEdit()
        self.search.setPlaceholderText('Escreve pelo menos 2 caracteres')
        self.suggestions = QListWidget()
        self.suggestions.setMaximumHeight(125)
        self.tree = MapTree()
        self.tree.setHeaderHidden(True)
        # O estilo dos cartões substitui os indicadores nativos do Windows.
        # Definimos as duas setas para manter visível o estado de cada planeta.
        arrow_root = (Path(__file__).resolve().parent / 'assets').as_posix()
        self.tree.setStyleSheet('''
            QTreeWidget { background: transparent; border: none; outline: 0; color: #edf1f5; }
            QTreeWidget::item { background: #2c3239; border: 1px solid #4c5d6b;
                                border-radius: 5px; margin: 3px 1px; padding: 7px; }
            QTreeWidget::item:selected { background: #2f5d78; color: white;
                                         border: 1px solid #80c8ff; }
            QTreeWidget::branch { background: transparent; border: none; image: none; }
            QTreeWidget::branch:has-children:closed {
                image: url("ARROW_ROOT/tree-closed.svg");
            }
            QTreeWidget::branch:has-children:open {
                image: url("ARROW_ROOT/tree-open.svg");
            }
        '''.replace('ARROW_ROOT', arrow_root))
        right_layout.addWidget(QLabel('Sistema:'))
        right_layout.addWidget(self.search)
        right_layout.addWidget(self.suggestions)
        right_layout.addWidget(self.system_title)
        right_layout.addWidget(self.tree, 1)
        body.addWidget(right)
        body.setSizes([760, 390])
        root.addWidget(body)

        self.search.textChanged.connect(self.filter_systems)
        self.suggestions.itemClicked.connect(lambda item: self.select_system(item.text()))
        self.tree.itemExpanded.connect(self.close_other_planets)
        self.tree.itemClicked.connect(self.select_map)
        self.favorite_check.toggled.connect(self.change_flags)
        self.protected_check.toggled.connect(self.change_flags)
        self.load_systems()
        self.set_theme(dark)

    def set_theme(self, dark):
        self.dark_theme = dark
        colors = _theme_values(dark)
        checked_icon = (Path(__file__).resolve().parent / 'assets' / 'checked.svg').as_posix()
        self.info.setStyleSheet(f'''
            QTextEdit {{ background: {colors['panel']}; border: 1px solid {colors['border']};
                         border-radius: 6px; padding: 8px; color: {colors['foreground']}; }}
        ''')
        self.info_panel.setStyleSheet(f'''
            QWidget#map_details {{ background: {colors['panel']}; border: 1px solid {colors['border']}; border-radius: 6px; }}
            QCheckBox {{ color: {colors['foreground']}; background: transparent; }}
            QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {colors['indicator_border']}; border-radius: 2px; background: {colors['indicator']}; }}
            QCheckBox::indicator:checked {{ background: {colors['selection']}; image: url("{checked_icon}"); }}
        ''')
        self.tree.set_theme(dark)
        self.preview.set_theme(dark)

    def load_systems(self):
        """Lê apenas os nomes das subpastas de MAPAS para alimentar a pesquisa."""
        directory = maps_directory()
        self.systems = sorted(path.name for path in directory.iterdir() if path.is_dir())

    def filter_systems(self, text):
        """Mostra sugestões só depois do mínimo configurado, hoje dois caracteres."""
        value = text.strip().casefold()
        self.suggestions.clear()
        if len(value) < 2:
            return
        self.suggestions.addItems([name for name in self.systems if value in name.casefold()])

    def select_system(self, system):
        """Agrupa os ficheiros por planeta no sistema seleccionado."""
        self.current_system = system
        self.system_title.setText(system)
        self.tree.clear()
        self.clear_selection()
        planets = {}
        for path in (maps_directory()/system).glob('*.json'):
            try:
                state = MapperState()
                state.load(path)
                # Corrige apenas em memória os metadados antigos a partir do
                # nome normalizado do ficheiro: "Kappa 2" e "Kappa 2 a" são
                # planetas diferentes, mesmo quando um JSON antigo os confundiu.
                MapOperations.infer_legacy_pml(state, path, system, state.body)
                body = state.body or path.stem.split(' [', 1)[0]
                planets.setdefault(body, []).append((path, state))
            except (OSError, ValueError, TypeError, KeyError):
                continue
        for body, paths in sorted(planets.items()):
            short = body.removeprefix(system).strip() or body
            planet = QTreeWidgetItem([short])
            planet.setData(0, Qt.ItemDataRole.UserRole, None)
            self.tree.addTopLevelItem(planet)
            planet.setFirstColumnSpanned(True)
            for path, state in sorted(paths, key=lambda item: item[0].stat().st_mtime, reverse=True):
                child = QTreeWidgetItem([path.name])
                child.setData(0, Qt.ItemDataRole.UserRole, str(path))
                self.update_badges(child, state)
                planet.addChild(child)

    def update_badges(self, item, state):
        item.setData(0, Qt.ItemDataRole.UserRole+1, (len(state.deposits), state.favorite, state.protected))
        self.tree.viewport().update()
        item.setToolTip(0, f'{len(state.deposits)} depósitos' + (' · Favorito' if state.favorite else '') + (' · Protegido' if state.protected else ''))

    def clear_selection(self):
        self.selected_path = self.selected_item = None
        self.preview.show_map(None)
        self.info.clear()
        for checkbox in (self.favorite_check, self.protected_check):
            checkbox.blockSignals(True)
            checkbox.setChecked(False)
            checkbox.setEnabled(False)
            checkbox.blockSignals(False)
        self.open_button.setEnabled(False)

    def change_flags(self):
        """Guarda apenas os atributos de gestão e sincroniza o mapa principal."""
        if self.selected_path is None:
            return
        try:
            parent = self.parent()
            if (parent is not None and getattr(parent, 'current_map_path', None) == self.selected_path
                    and self.protected_check.isChecked() and not parent.state.read_only):
                # Resolve primeiro os registos ainda não gravados; proteger não
                # pode fazer desaparecer a oportunidade de os conservar.
                if not parent.prepare_to_replace_current_map('Proteger mapa'):
                    self.select_map(self.selected_item, 0)
                    return
            MapperState.set_file_flags(self.selected_path, favorite=self.favorite_check.isChecked(),
                                       protected=self.protected_check.isChecked())
            if parent is not None and getattr(parent, 'current_map_path', None) == self.selected_path:
                parent.state.favorite = self.favorite_check.isChecked()
                parent.state.protected = self.protected_check.isChecked()
                if parent.state.protected:
                    # Suspende registos sem descartar o conteúdo em memória.
                    parent.state.enter_mining_mode()
                    parent.cancel_placement()
                    parent.view.radar.waves.clear()
                    parent.stop_assistance()
                parent.refresh()
            self.select_map(self.selected_item, 0)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.critical(self, 'Erro ao atualizar mapa', str(exc))
            self.select_map(self.selected_item, 0)

    def open_selected_map(self):
        parent = self.parent()
        if self.selected_path is None or parent is None:
            return
        try:
            state = MapperState()
            state.load(self.selected_path)
            MapOperations.infer_legacy_pml(state, self.selected_path,
                                          self.current_system or self.selected_path.parent.name, state.body)
            if not parent.prepare_to_replace_current_map('Abrir mapa'):
                return
            parent.install_loaded_map(state, source_path=self.selected_path)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            QMessageBox.critical(self, 'Erro ao abrir mapa', str(exc))

    def close_other_planets(self, opened):
        """Mantém só um planeta expandido para a lista continuar legível."""
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item is not opened:
                item.setExpanded(False)

    def select_map(self, item, column):
        """Carrega o ficheiro seleccionado apenas para pré-visualização e ficha."""
        filename = item.data(0, Qt.ItemDataRole.UserRole)
        if not filename:
            self.clear_selection()
            return
        path = Path(filename)
        try:
            state = MapperState()
            state.load(path)
            MapOperations.infer_legacy_pml(state, path, self.current_system or path.parent.name, state.body)
            if not state.protected and state.populate_missing_timestamps(path):
                state.save(path, update_saved_at=False)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.clear_selection()
            self.info.setPlainText(f'Não foi possível ler o mapa:\n{exc}')
            return
        self.selected_path, self.selected_item = path, item
        self.update_badges(item, state)
        for checkbox, value in ((self.favorite_check, state.favorite), (self.protected_check, state.protected)):
            checkbox.blockSignals(True)
            checkbox.setChecked(value)
            checkbox.setEnabled(True)
            checkbox.blockSignals(False)
        self.open_button.setEnabled(self.parent() is not None)
        self.preview.show_map(state)
        modified = datetime.fromtimestamp(path.stat().st_mtime).strftime('%Y-%m-%d %H:%M')
        completed = len(state.route_history)
        skipped = sum(item.get('status') == 'skipped' for item in state.route_history)
        if state.search_started or completed:
            search = f'Sim ({completed}/{state.search_total_points}) · saltos {skipped}'
        else:
            search = 'Não'
        def esc(value):
            return html.escape(str(value))
        cards = (f'<table width="100%" cellspacing="6"><tr>'
                 f'<td><b>PML</b><br>{esc(state.pml_id or "—")}</td>'
                 f'<td><b>Busca efetuada</b><br>{search}</td>'
                 f'<td><b>Percurso</b><br>{len(state.points)} pontos</td>'
                 f'<td><b>Registos</b><br>{len(state.deposits)} depósitos · {len(state.rigs)} rigs · {len(state.marks)} marcas</td>'
                 f'</tr></table>')
        sections = [f'<h3 style="margin:0">{esc(path.name)}</h3>', cards,
                    f'<p><b>Criado:</b> {esc(state.created_at or "não registado")}<br>'
                    f'<b>Última gravação:</b> {esc(state.last_saved_at or modified)}</p>']
        if state.deposits:
            sections.append('<h4>Depósitos</h4><ul>' + ''.join(
                f"<li><b>{esc(item['name'])}</b> — {esc(item['size'])}, {item['rigs']} rigs · {item['lat']:.5f}, {item['lon']:.5f}</li>"
                for item in state.deposits) + '</ul>')
        if state.marks:
            sections.append('<h4>Marcas</h4><ul>' + ''.join(
                f"<li><b>{esc(item['name'])}</b> · {item['lat']:.5f}, {item['lon']:.5f}</li>"
                for item in state.marks) + '</ul>')
        if state.rigs:
            sections.append('<h4>Rigs marcados</h4><ul>' + ''.join(
                f"<li>{item.get('lat', 0):.5f}, {item.get('lon', 0):.5f}</li>" for item in state.rigs) + '</ul>')
        self.info.setHtml(''.join(sections))
