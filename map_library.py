"""Janela de consulta dos mapas guardados, sem alterar o mapa activo."""
import json
import html
import math
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QFile, Qt, QSize, QRectF, QPointF, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QIcon, QFontMetricsF
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (QDialog, QLabel, QLineEdit, QListWidget,
    QSplitter, QTextEdit, QTreeWidget, QTreeWidgetItem, QWidget, QCheckBox,
    QMessageBox, QPushButton, QStyledItemDelegate)
from deposit_marker import deposit_bounds, draw_deposit
from PySide6.QtSvg import QSvgRenderer

from app_paths import maps_directory
from map_pml import infer_legacy_pml
from mapper_core import MapperState
from i18n import translate


class _MapLibraryLoader(QUiLoader):
    """Load the Designer root directly into the existing dialog wrapper."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window

    def createWidget(self, class_name, parent=None, name=''):
        """Reuse MapLibraryWindow for the root and delegate child creation."""
        if class_name == 'QDialog' and name == 'MapLibraryWindow':
            return self.window
        return super().createWidget(class_name, parent, name)


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

    @staticmethod
    def _annotation_extents(font, state):
        """Return pixel extents required around map anchors for annotations."""
        metrics = QFontMetricsF(font)
        left = top = right = bottom = 20.0

        def include(rect):
            nonlocal left, top, right, bottom
            left = max(left, -rect.left())
            top = max(top, -rect.top())
            right = max(right, rect.right())
            bottom = max(bottom, rect.bottom())

        for item in state.deposits:
            include(deposit_bounds(QPointF(0, 0), font, item))
        for collection in (state.marks, state.rigs):
            default_name = 'Marca' if collection is state.marks else 'Rig'
            for item in collection:
                label = item.get('name', default_name)
                include(QRectF(-4, -4, 12 + metrics.horizontalAdvance(label),
                               metrics.height() + 8))

        safety = 3.0
        return left + safety, top + safety, right + safety, bottom + safety

    @classmethod
    def _framing(cls, state, width, height, font):
        """Calculate a positive preview scale and center including annotations."""
        items = state.points + state.deposits + state.rigs + state.marks
        xs = [item['x'] for item in items]
        ys = [item['y'] for item in items]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span = max(1000.0, max_x - min_x, max_y - min_y)
        left, top, right, bottom = cls._annotation_extents(font, state)
        usable_width = max(1.0, width - left - right)
        usable_height = max(1.0, height - top - bottom)
        scale = max(0.0001, min(usable_width / span, usable_height / span))
        anchor_center_x = (min_x + max_x) / 2
        anchor_center_y = (min_y + max_y) / 2
        center_x = anchor_center_x - (left - right) / (2 * scale)
        center_y = anchor_center_y + (top - bottom) / (2 * scale)
        return scale, center_x, center_y

    def paintEvent(self, event):
        painter = QPainter(self)
        colors = _theme_values(self.dark_theme)
        painter.fillRect(self.rect(), QColor(colors['preview_background']))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.state is None:
            painter.setPen(QColor(colors['preview_foreground']))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                translate('MapLibraryWindow', 'Select a map to preview.'),
            )
            return
        items = self.state.points + self.state.deposits + self.state.rigs + self.state.marks
        if not items:
            painter.setPen(QColor(colors['preview_foreground']))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                translate('MapLibraryWindow', 'This map has no records yet.'),
            )
            return
        scale, cx, cy = self._framing(
            state=self.state,
            width=self.width(),
            height=self.height(),
            font=painter.font(),
        )
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
    HORIZONTAL_SPLIT_KEY = 'map_library_horizontal_split_ratio'
    VERTICAL_SPLIT_KEY = 'map_library_vertical_split_ratio'
    DEFAULT_HORIZONTAL_SPLIT = 760 / (760 + 390)
    DEFAULT_VERTICAL_SPLIT = 450 / (450 + 300)

    def __init__(self, parent=None, dark=True, preferences=None, save_preference=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowMinMaxButtonsHint |
                            Qt.WindowType.WindowCloseButtonHint)
        self.setMinimumSize(820, 520)
        self.resize(1150, 720)
        self.current_system = None
        self.systems = []
        self.selected_path = None
        self.selected_item = None
        self.dark_theme = dark
        self.preferences = preferences if isinstance(preferences, dict) else {}
        self.save_preference = save_preference
        ui_path = Path(__file__).resolve().parent / 'ui' / 'map_library_window.ui'
        ui_file = QFile(str(ui_path))
        if not ui_file.open(QFile.OpenModeFlag.ReadOnly):
            raise OSError(f'Unable to open UI resource: {ui_path}')
        loaded = _MapLibraryLoader(self).load(ui_file, self)
        ui_file.close()
        if loaded is None or loaded is not self:
            raise RuntimeError(f'Unable to load UI resource: {ui_path}')

        body = self.findChild(QSplitter, 'librarySplitter')
        preview_details_splitter = self.findChild(QSplitter, 'previewDetailsSplitter')
        preview_host = self.findChild(QWidget, 'previewHost')
        tree_host = self.findChild(QWidget, 'treeHost')
        if (body is None or preview_details_splitter is None or preview_host is None
                or tree_host is None):
            raise RuntimeError('MapLibraryWindow.ui is missing a required container')
        for splitter in (body, preview_details_splitter):
            splitter.setChildrenCollapsible(False)
            for index in range(splitter.count()):
                splitter.setCollapsible(index, False)

        preview_layout = preview_host.layout()
        self.preview = MapPreview()
        preview_layout.addWidget(self.preview)
        self.info = QTextEdit()
        self.info.setReadOnly(True)
        self.info.setMinimumHeight(190)
        self.findChild(QWidget, 'detailsInfoHost').layout().addWidget(self.info)
        self.favorite_check = self.findChild(QCheckBox, 'favoriteCheck')
        self.protected_check = self.findChild(QCheckBox, 'protectedCheck')
        self.favorite_filter_check = self.findChild(QCheckBox, 'favoriteFilterCheck')
        self.protected_filter_check = self.findChild(QCheckBox, 'protectedFilterCheck')
        for checkbox, symbol in ((self.favorite_check, 'favorite'), (self.protected_check, 'protected')):
            checkbox.setIcon(QIcon(str(Path(__file__).resolve().parent/'assets'/f'{symbol}.svg')))
            checkbox.setIconSize(QSize(22, 22))
            checkbox.setEnabled(False)
        self.open_button = self.findChild(QPushButton, 'openButton')
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_selected_map)
        self.info_panel = self.findChild(QWidget, 'mapDetails')
        self.system_title = self.findChild(QLabel, 'systemTitle')
        self.search = self.findChild(QLineEdit, 'searchInput')
        self.suggestions = self.findChild(QListWidget, 'suggestionsList')
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
        tree_host.layout().addWidget(self.tree)
        body.setSizes([760, 390])
        preview_details_splitter.setSizes([450, 300])
        QTimer.singleShot(0, self._restore_saved_splitters)

        self.search.textChanged.connect(self.filter_systems)
        self.suggestions.itemClicked.connect(lambda item: self.select_system(item.text()))
        self.tree.itemExpanded.connect(self.close_other_planets)
        self.tree.itemClicked.connect(self.select_map)
        self.favorite_check.toggled.connect(self.change_flags)
        self.protected_check.toggled.connect(self.change_flags)
        self.favorite_filter_check.toggled.connect(self.refresh_map_filter)
        self.protected_filter_check.toggled.connect(self.refresh_map_filter)
        self.load_systems()
        self.set_theme(dark)

    @staticmethod
    def _valid_split_ratio(value):
        """Return whether a stored splitter ratio is finite and strictly usable."""
        return isinstance(value, (int, float)) and not isinstance(value, bool) \
            and math.isfinite(value) and 0 < value < 1

    @classmethod
    def _restore_splitter_ratio(cls, splitter, value, default):
        """Apply a saved ratio, retaining defaults when it is invalid or unusable."""
        ratio = value if cls._valid_split_ratio(value) else default
        total = sum(splitter.sizes())
        if total <= 0:
            return
        splitter.setSizes([round(total * ratio), round(total * (1 - ratio))])
        if any(size <= 0 for size in splitter.sizes()):
            splitter.setSizes([round(total * default), round(total * (1 - default))])

    def _restore_saved_splitters(self):
        """Restore saved ratios after the dialog layouts have their final size."""
        splitters = (
            ('librarySplitter', self.HORIZONTAL_SPLIT_KEY, self.DEFAULT_HORIZONTAL_SPLIT),
            ('previewDetailsSplitter', self.VERTICAL_SPLIT_KEY, self.DEFAULT_VERTICAL_SPLIT),
        )
        for object_name, key, default in splitters:
            splitter = self.findChild(QSplitter, object_name)
            if splitter is not None:
                self._restore_splitter_ratio(splitter, self.preferences.get(key), default)

    def _save_splitter_preferences(self):
        """Persist current splitter ratios through the parent settings owner."""
        if not callable(self.save_preference):
            return
        splitters = (
            ('librarySplitter', self.HORIZONTAL_SPLIT_KEY),
            ('previewDetailsSplitter', self.VERTICAL_SPLIT_KEY),
        )
        for object_name, key in splitters:
            splitter = self.findChild(QSplitter, object_name)
            sizes = splitter.sizes() if splitter is not None else []
            total = sum(sizes)
            if total > 0 and all(size > 0 for size in sizes):
                self.save_preference(key, sizes[0] / total)

    def closeEvent(self, event):
        """Save splitter positions before the Map Library closes."""
        self._save_splitter_preferences()
        super().closeEvent(event)

    def set_theme(self, dark):
        self.dark_theme = dark
        colors = _theme_values(dark)
        checked_icon = (Path(__file__).resolve().parent / 'assets' / 'checked.svg').as_posix()
        self.info.setStyleSheet(f'''
            QTextEdit {{ background: {colors['panel']}; border: 1px solid {colors['border']};
                         border-radius: 6px; padding: 8px; color: {colors['foreground']}; }}
        ''')
        self.info_panel.setStyleSheet(f'''
            QWidget#mapDetails {{ background: {colors['panel']}; border: 1px solid {colors['border']}; border-radius: 6px; }}
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

    def map_matches_filters(self, state):
        """Return whether a map state satisfies the active library filters."""
        return ((not self.favorite_filter_check.isChecked() or state.favorite)
                and (not self.protected_filter_check.isChecked() or state.protected))

    def refresh_map_filter(self):
        """Rebuild the selected system after a map-level filter changes."""
        if self.current_system is not None:
            self.select_system(self.current_system)

    def select_system(self, system):
        """Agrupa os ficheiros por planeta no sistema seleccionado."""
        expanded_body = None
        if self.current_system == system:
            expanded_body = next(
                (self.tree.topLevelItem(index).text(0)
                 for index in range(self.tree.topLevelItemCount())
                 if self.tree.topLevelItem(index).isExpanded()),
                None,
            )
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
                infer_legacy_pml(state, path, system, state.body)
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
                if not self.map_matches_filters(state):
                    continue
                child = QTreeWidgetItem([path.name])
                child.setData(0, Qt.ItemDataRole.UserRole, str(path))
                self.update_badges(child, state)
                planet.addChild(child)
            if planet.childCount() == 0:
                self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(planet))
            elif planet.text(0) == expanded_body:
                planet.setExpanded(True)

    def update_badges(self, item, state):
        item.setData(0, Qt.ItemDataRole.UserRole+1, (len(state.deposits), state.favorite, state.protected))
        self.tree.viewport().update()
        tooltip = translate('MapLibraryWindow', '{count} deposits').format(count=len(state.deposits))
        if state.favorite:
            tooltip += translate('MapLibraryWindow', ' · Favourite')
        if state.protected:
            tooltip += translate('MapLibraryWindow', ' · Protected')
        item.setToolTip(0, tooltip)

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
            if self.favorite_filter_check.isChecked() or self.protected_filter_check.isChecked():
                self.select_system(self.current_system)
            else:
                self.select_map(self.selected_item, 0)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.critical(self, translate('MapLibraryWindow', 'Error updating map'), str(exc))
            self.select_map(self.selected_item, 0)

    def open_selected_map(self):
        parent = self.parent()
        if self.selected_path is None or parent is None:
            return
        try:
            state = MapperState()
            state.load(self.selected_path)
            infer_legacy_pml(state, self.selected_path,
                             self.current_system or self.selected_path.parent.name, state.body)
            if not parent.prepare_to_replace_current_map(
                    translate('MapperWindow', 'Open map'), translate('MapperWindow', 'opening the map')):
                return
            parent.install_loaded_map(state, source_path=self.selected_path)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            QMessageBox.critical(self, translate('MapLibraryWindow', 'Error opening map'), str(exc))

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
            infer_legacy_pml(state, path, self.current_system or path.parent.name, state.body)
            if not state.protected and state.populate_missing_timestamps(path):
                state.save(path, update_saved_at=False)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.clear_selection()
            self.info.setPlainText(translate(
                'MapLibraryWindow', 'Unable to read map:\n{error}').format(error=exc))
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
            search = translate(
                'MapLibraryWindow', 'Yes ({completed}/{total}) · skips {skipped}').format(
                    completed=completed, total=state.search_total_points, skipped=skipped)
        else:
            search = translate('MapLibraryWindow', 'No')
        def esc(value):
            return html.escape(str(value))
        cards = (f'<table width="100%" cellspacing="6"><tr>'
                 f'<td><b>PML</b><br>{esc(state.pml_id or "—")}</td>'
                 f'<td><b>{translate("MapLibraryWindow", "Search completed")}</b><br>{search}</td>'
                 f'<td><b>{translate("MapLibraryWindow", "Route")}</b><br>{translate("MapLibraryWindow", "{count} points").format(count=len(state.points))}</td>'
                 f'<td><b>{translate("MapLibraryWindow", "Records")}</b><br>'
                 f'{translate("MapLibraryWindow", "{deposits} deposits · {rigs} rigs · {marks} marks").format(deposits=len(state.deposits), rigs=len(state.rigs), marks=len(state.marks))}</td>'
                 f'</tr></table>')
        sections = [f'<h3 style="margin:0">{esc(path.name)}</h3>', cards,
                    f'<p><b>{translate("MapLibraryWindow", "Created:")}</b> '
                    f'{esc(state.created_at or translate("MapLibraryWindow", "not recorded"))}<br>'
                    f'<b>{translate("MapLibraryWindow", "Last saved:")}</b> '
                    f'{esc(state.last_saved_at or modified)}</p>']
        if state.deposits:
            sections.append(f'<h4>{translate("MapLibraryWindow", "Deposits")}</h4><ul>' + ''.join(
                f"<li><b>{esc(item['name'])}</b> — {esc(item['size'])}, {item['rigs']} {translate('MapLibraryWindow', 'rigs')} · {item['lat']:.5f}, {item['lon']:.5f}</li>"
                for item in state.deposits) + '</ul>')
        if state.marks:
            sections.append(f'<h4>{translate("MapLibraryWindow", "Marks")}</h4><ul>' + ''.join(
                f"<li><b>{esc(item['name'])}</b> · {item['lat']:.5f}, {item['lon']:.5f}</li>"
                for item in state.marks) + '</ul>')
        if state.rigs:
            sections.append(f'<h4>{translate("MapLibraryWindow", "Marked rigs")}</h4><ul>' + ''.join(
                f"<li>{item.get('lat', 0):.5f}, {item.get('lon', 0):.5f}</li>" for item in state.rigs) + '</ul>')
        self.info.setHtml(''.join(sections))
