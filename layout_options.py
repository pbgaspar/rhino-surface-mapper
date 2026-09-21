"""Painel de preferências recolhível e organização das barras principais."""
from pathlib import Path
from PyQt6.QtCore import Qt, QByteArray
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QToolButton, QScrollArea, QMenu, QComboBox, QSpinBox,
    QLineEdit, QFileDialog, QLabel, QColorDialog, QMessageBox, QSizePolicy, QFontComboBox, QStyleFactory, QAbstractSpinBox)
from settings_persistence import (read_exported_settings, save_preferences,
                                  write_exported_settings)


def _theme_is_dark(theme, system_scheme):
    return theme == 'Dark' or (theme == 'Como o Windows' and system_scheme == Qt.ColorScheme.Dark)


def _widget_theme_colors(dark):
    if dark:
        return {'background': '#202429', 'foreground': '#edf1f5',
                'panel': '#2c3239', 'border': '#46515d'}
    return {'background': '#edf1f4', 'foreground': '#233448',
            'panel': '#ffffff', 'border': '#cbd5dd'}


def _theme_stylesheet(colors, arrow_root):
    background = colors['background']
    foreground = colors['foreground']
    panel = colors['panel']
    border = colors['border']
    return (f'QMainWindow, QWidget {{ background: {background}; color: {foreground}; }} '
            f'QPushButton, QToolButton, QComboBox, QSpinBox, QLineEdit {{ '
            f'background: {panel}; border: 1px solid {border}; border-radius: 4px; padding: 4px; }} '
            'QPushButton:disabled { color: #7e8790; } '
            'QPushButton:checked { border: 2px solid #448b68; } '
            f'QMenu {{ background: {panel}; }} '
            'QMenu::item:selected { background: #448b68; color: white; }' +
            f"""
            QAbstractSpinBox {{ padding: 4px 24px 4px 4px; min-height: 24px; }}
            QAbstractSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 22px; height: 16px; border-left: 1px solid {border}; background: {panel}; }}
            QAbstractSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 22px; height: 16px; border-left: 1px solid {border}; background: {panel}; }}
            QAbstractSpinBox::up-arrow {{ image: url("{arrow_root}/spin-up.svg"); width: 10px; height: 7px; }}
            QAbstractSpinBox::down-arrow {{ image: url("{arrow_root}/spin-down.svg"); width: 10px; height: 7px; }}
            QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: #698779; }}
        """)


class LayoutOptions:
    def build_layout_options(self, layout, operations, controls, options):
        self.setting_fields = {}
        self.loading_settings = False
        self.preferences = dict(options) if isinstance(options, dict) else {}
        self.option_resets = {}
        self.option_sections = {}
        self.fixed_buttons = []
        self.color_buttons = {}
        # Reutiliza os controlos para conservar sinais e regras de ativação.
        for box in (operations, controls):
            while box.count():
                item = box.takeAt(0)
                if item.widget():
                    item.widget().hide()
        maps = QPushButton('Mapas')
        menu = QMenu(maps)
        # Esta é a barra efetivamente apresentada depois de aplicar o layout.
        # A ordem segue o menu de mapas definido para a utilização normal.
        for title, callback in [('Abrir', self.load_map), ('Guardar', self.save_map),
                                ('Novo', self.new_map), ('Ver e manter', self.show_map_library)]:
            menu.addAction(title, callback)
        maps.setObjectName("maps_menu")
        maps.setMenu(menu)
        operations.addWidget(maps)
        self.op_buttons['Mapas'] = maps
        self.fixed_buttons.append((maps, 90))
        for key, title in [('Marca','Marca'), ('Marcar depósito','Depósito'), ('Marcar rig','Rig')]:
            button = self.op_buttons[key]
            button.setText(title)
            button.show()
            operations.addWidget(button)
            self.fixed_buttons.append((button, 90))
        self.options_button = QPushButton('Configurações')
        self.options_button.setCheckable(True)
        operations.addWidget(self.options_button)
        operations.addWidget(self.op_buttons['Sair'])
        self.op_buttons['Sair'].show()
        self.fixed_buttons.extend([(self.options_button,125), (self.op_buttons['Sair'],90)])
        operations.addStretch()
        for button, width in [(self.search_button,140),(self.skip_button,150),(self.overlay_button,90)]:
            controls.addWidget(button)
            button.show()
            self.fixed_buttons.append((button,width))
        controls.addStretch()
        controls.addWidget(self.assist_button)
        self.fixed_buttons.append((self.assist_button,180))
        controls.addWidget(self.follow)
        self.follow.show()
        controls.addSpacing(18)
        controls.addWidget(self.info_right)
        self.info_right.setFixedWidth(195)
        self.info_left.hide()
        self.radar_info.hide()
        self.assist_info.hide()
        layout.removeWidget(self.view)
        body = QHBoxLayout()
        body.addWidget(self.view, 1)
        self.options_panel = QScrollArea()
        self.options_panel.setWidgetResizable(True)
        self.options_panel.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        close = QPushButton('Fechar configurações ×')
        close.clicked.connect(lambda: self.options_button.setChecked(False))
        panel_layout.addWidget(close)
        self.options_panel.setWidget(panel)
        body.addWidget(self.options_panel)
        layout.insertLayout(3, body, 1)
        self.options_panel.hide()
        self.options_button.toggled.connect(self.toggle_options_panel)

        def section(title):
            header = QToolButton()
            header.setText(title)
            header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            header.setArrowType(Qt.ArrowType.RightArrow)
            header.setCheckable(True)
            header.setMinimumHeight(34)
            header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            content = QWidget()
            form = QFormLayout(content)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
            content.hide()
            header.toggled.connect(content.setVisible)
            header.toggled.connect(lambda opened: header.setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow))
            panel_layout.addWidget(header)
            panel_layout.addWidget(content)
            self.option_sections[title] = (header, content)
            self.option_resets[title] = []
            return form

        def number(form, theme, label, key, default, low, high, callback, suffix=''):
            spin = QSpinBox()
            spin.setObjectName(key)
            spin.setRange(low, high)
            spin.setSuffix(suffix)
            value = self.preferences.get(key, default)
            spin.setValue(value if type(value) is int and low <= value <= high else default)
            self.setting_fields[key] = (spin.value, spin.setValue, lambda v: type(v) is int and low <= v <= high)
            callback(spin.value())
            def changed(value):
                callback(value)
                self.save_preference(key, value)
                self.view.update()
            spin.valueChanged.connect(changed)
            form.addRow(label, spin)
            self.option_resets[theme].append(lambda: spin.setValue(default))
            return spin

        def color(form, theme, label, key, default):
            button = QPushButton()
            button.setObjectName(key)
            self.color_buttons[key] = button
            value = self.preferences.get(key, default)
            if not isinstance(value, str) or not QColor(value).isValid():
                value = default
            def apply(value, save=True):
                self.view.colors[key] = value
                if key == "rhino_color":
                    svg = (Path(__file__).resolve().parent / "assets" / "Rhino.svg").read_text(encoding="utf-8-sig")
                    self.view.rhino_renderer.load(QByteArray(svg.replace("#e6ebf0", value).encode("utf-8")))
                button.setText(value)
                button.setStyleSheet(f'border-left: 18px solid {value}; padding: 5px;')
                self.view.update()
                if save:
                    self.save_preference(key, value)
            self.setting_fields[key] = (lambda: self.view.colors[key], apply, lambda v: isinstance(v,str) and QColor(v).isValid())
            apply(value, False)
            def choose():
                value = QColorDialog.getColor(QColor(self.view.colors[key]), self, label)
                if value.isValid():
                    apply(value.name())
            button.clicked.connect(choose)
            form.addRow(label, button)
            self.option_resets[theme].append(lambda: apply(self.view.default_map_color(key) if key in ('map_background','grid_color') else default))

        for field, default in [('coverage_width_m',2000),('scanner_range_m',2000),('search_azimuth',0)]:
            spin = self.parameter_spins[field]
            self.setting_fields[field] = (spin.value, spin.setValue, lambda v, spin=spin: type(v) is int and spin.minimum() <= v <= spin.maximum())
            value = self.preferences.get(field, default)
            if type(value) is int and spin.minimum() <= value <= spin.maximum():
                spin.setValue(value)
            spin.valueChanged.connect(lambda value, field=field:self.save_preference(field,value))
        form = section('Busca e navegação')
        for field, label in [('coverage_width_m','Cobertura'), ('search_azimuth','AZ Busca')]:
            form.addRow(label, self.parameter_spins[field])
            self.parameter_spins[field].show()
        self.option_resets['Busca e navegação'].extend([lambda:self.parameter_spins['coverage_width_m'].setValue(2000),lambda:self.search_azimuth_spin.setValue(0)])
        form = section('Radar')
        self.option_resets['Radar'].append(lambda:self.parameter_spins['scanner_range_m'].setValue(2000))
        form.addRow('Alcance do scanner', self.parameter_spins['scanner_range_m'])
        self.parameter_spins['scanner_range_m'].show()
        number(form,'Radar','Velocidade da onda','radar_speed',667,100,3000,lambda v: setattr(self.view.radar,'SPEED_M_S',v),' m/s')
        color(form,'Radar','Cor da onda','wave_color','#69b574')
        form.addRow(self.radar_info)
        self.radar_info.show()
        self.radar_info.setWordWrap(True)
        form = section('Rhino')
        number(form,'Rhino','Tamanho','rhino_size',56,20,160,lambda v: setattr(self.view,'rhino_height',v),' px')
        color(form,'Rhino','Cor da blindagem','rhino_color','#e6ebf0')
        form = section('Assistência de direção')
        number(form,'Assistência de direção','Velocidade máxima estimada','assist_speed',15,15,40,lambda v:setattr(self.assist,'max_speed',v),' m/s')
        number(form,'Assistência de direção','Duração máxima base','assist_pulse_ms',800,200,1000,lambda v:setattr(self.assist,'max_pulse',v/1000),' ms')
        number(form,'Assistência de direção','Tolerância do rumo','assist_tolerance_deg',3,0,180,lambda v:setattr(self.assist,'tolerance',v),'°')
        self.assist_info.setWordWrap(True)
        form.addRow(self.assist_info)
        self.assist_info.show()
        form = section('Parâmetros ED')
        group = QComboBox()
        group.addItems([chr(65+i) for i in range(26)])
        group.setCurrentIndex(self.scanner_group)
        group.currentIndexChanged.connect(lambda v: (setattr(self,'scanner_group',v),self.save_preference('scanner_group',v)))
        form.addRow('Fire group do Mineral Scanner', group)
        self.setting_fields['scanner_group'] = (group.currentIndex, group.setCurrentIndex, lambda v: type(v) is int and 0 <= v <= 25)
        path = QLineEdit(self.bindings_override)
        path.setPlaceholderText('Perfil SRV automático')
        form.addRow('Ficheiro de controlos', path)
        def apply_bindings():
            self.bindings_override = path.text().strip()
            self.radar_input.load(self.bindings_override or None)
            self.steering_input.load()
            self.save_preference('bindings_path', self.bindings_override)
        path.editingFinished.connect(apply_bindings)
        self.setting_fields['bindings_path'] = (path.text, lambda v:(path.setText(v),apply_bindings()), lambda v:isinstance(v,str))
        choose = QPushButton('Escolher .binds')
        def browse():
            filename, _ = QFileDialog.getOpenFileName(self,'Controlos SRV',path.text(),'Bindings (*.binds)')
            if filename:
                path.setText(filename)
                apply_bindings()
        choose.clicked.connect(browse)
        form.addRow(choose)
        status = QPushButton('Escolher Status.json')
        status.clicked.connect(self.choose_status)
        form.addRow(status)
        self.option_resets['Parâmetros ED'].extend([lambda:group.setCurrentIndex(0),lambda:(path.clear(),apply_bindings())])
        form = section('Mapa')
        for label,key,default in [('Fundo','map_background','#ffffff'),('Grelha','grid_color','#eeeeee'),('Rasto','trail_color','#2f7d32'),('Cobertura','coverage_color','#8cbd8c')]:
            color(form,'Mapa',label,key,default)
        number(form,'Mapa','Escala do texto','map_text_scale',100,75,175,lambda v:setattr(self.view,'text_scale',v/100),' %')
        form = section('Overlay')
        number(form,'Overlay','Largura','overlay_width',360,240,900,lambda v:self.overlay.resize(v,round(v/self.overlay.aspect_ratio)),' px')
        number(form,'Overlay','Opacidade','overlay_opacity',100,25,100,lambda v:self.overlay.setWindowOpacity(v/100),' %')
        form = section('Layout')
        theme = QComboBox()
        theme.addItems(['Como o Windows','Dark','Light'])
        theme.setCurrentText(self.preferences.get('theme','Como o Windows'))
        form.addRow('Tema',theme)
        self.setting_fields['theme'] = (theme.currentText, theme.setCurrentText, lambda v:v in ('Como o Windows','Dark','Light'))
        theme.currentTextChanged.connect(lambda v:(self.apply_theme(v),self.save_preference('theme',v)))
        self.option_resets['Layout'].append(lambda: theme.setCurrentIndex(0))
        family = QFontComboBox()
        family.setCurrentFont(QFont(self.preferences.get('font_family','Segoe UI')))
        form.addRow('Tipo de letra', family)
        def set_font(value):
            font = QFont(self.font())
            font.setFamily(value.family())
            self.setFont(font)
            self.save_preference('font_family',value.family())
        family.currentFontChanged.connect(set_font)
        self.setting_fields['font_family'] = (lambda:family.currentFont().family(), lambda v:family.setCurrentFont(QFont(v)), lambda v:isinstance(v,str) and bool(v.strip()))
        initial_font = QFont(self.font())
        initial_font.setFamily(family.currentFont().family())
        self.setFont(initial_font)
        def font_size(value):
            font = QFont(self.font())
            font.setPointSize(value)
            self.setFont(font)
        number(form,'Layout','Tamanho da letra','font_size',9,8,11,font_size,' pt')
        self.option_resets['Layout'].append(lambda:family.setCurrentFont(QFont('Segoe UI')))
        number(form,'Layout','Largura do painel','panel_width',320,280,440,lambda v:self.options_panel.setFixedWidth(v),' px')
        number(form,'Layout','Altura dos botões','button_height',34,28,44,self.resize_buttons,' px')
        for title,(header,content) in self.option_sections.items():
            if self.option_resets[title]:
                reset = QPushButton('Repor valores padrão')
                reset.clicked.connect(lambda checked=False,title=title:[callback() for callback in self.option_resets[title]])
                content.layout().addRow(reset)
        actions = QHBoxLayout()
        for title, callback in [('Guardar',self.export_settings),('Carregar',self.import_settings),('Repor',self.reset_settings)]:
            button = QPushButton(title)
            button.setFixedSize(78,34)
            button.clicked.connect(callback)
            actions.addWidget(button)
        actions.addStretch()
        panel_layout.addLayout(actions)
        panel_layout.addStretch()
        # O estilo Windows pode usar setas horizontais nos campos derivados.
        # Usar o mesmo estilo e política em todos os campos do painel.
        for spin in self.options_panel.findChildren(QAbstractSpinBox):
            numeric_style = QStyleFactory.create('Fusion')
            numeric_style.setParent(spin)
            spin.setStyle(numeric_style)
            spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.theme_selector = theme
        self.apply_theme(theme.currentText())
        self.setMinimumSize(1150,560)
        QApplication.styleHints().colorSchemeChanged.connect(self.system_theme_changed)

    def export_settings(self):
        filename, _ = QFileDialog.getSaveFileName(self,'Guardar configurações','Rhino-configuracoes.json','Configurações (*.json)')
        if not filename:
            return
        data = {key:getter() for key,(getter,_,_) in self.setting_fields.items()}
        try:
            write_exported_settings(filename, data)
        except OSError as exc:
            QMessageBox.warning(self,'Configurações',f'Não foi possível guardar: {exc}')

    def import_settings(self):
        filename, _ = QFileDialog.getOpenFileName(self,'Carregar configurações','','Configurações (*.json)')
        if not filename:
            return
        try:
            data = read_exported_settings(filename)
            for key,value in data.items():
                if key not in self.setting_fields or not self.setting_fields[key][2](value):
                    raise ValueError(f'Configuração inválida: {key}')
        except (OSError,ValueError,TypeError) as exc:
            QMessageBox.warning(self,'Configurações',f'Não foi possível carregar: {exc}')
            return
        self.loading_settings = True
        try:
            # Aplicar o tema primeiro; as cores do ficheiro prevalecem depois.
            for key in sorted(data,key=lambda key:key != 'theme'):
                self.setting_fields[key][1](data[key])
            self.preferences.update({key:getter() for key,(getter,_,_) in self.setting_fields.items()})
        finally:
            self.loading_settings = False
        self.save_preference('theme',self.theme_selector.currentText())
        self.view.update()

    def reset_settings(self):
        self.loading_settings = True
        try:
            for callback in self.option_resets['Layout']:
                callback()
            for title,callbacks in self.option_resets.items():
                if title != 'Layout':
                    for callback in callbacks:
                        callback()
            self.preferences.update({key:getter() for key,(getter,_,_) in self.setting_fields.items()})
        finally:
            self.loading_settings = False
        self.save_preference('theme',self.theme_selector.currentText())
        self.view.update()

    def system_theme_changed(self, scheme):
        if self.preferences.get("theme", "Como o Windows") == "Como o Windows":
            self.apply_theme("Como o Windows")

    def resize_buttons(self, height):
        for button,width in self.fixed_buttons:
            button.setFixedSize(width,height)

    def toggle_options_panel(self, visible):
        if visible:
            self.pause_assistance('Configurações abertas')
        self.options_panel.setVisible(visible)

    def save_preference(self, key, value):
        self.preferences[key] = value
        if self.loading_settings:
            return
        try:
            save_preferences(self.options_path, self.preferences)
        except OSError as exc:
            self.statusBar().showMessage(f'Não foi possível guardar as configurações: {exc}')

    def apply_theme(self, theme):
        dark = _theme_is_dark(theme, QApplication.styleHints().colorScheme())
        colors = _widget_theme_colors(dark)
        arrow_root = (Path(__file__).resolve().parent / 'assets').as_posix()
        self.setStyleSheet(_theme_stylesheet(colors, arrow_root))
        self.view.dark_theme = dark
        for key in ('map_background','grid_color'):
            if key not in self.preferences:
                value = self.view.default_map_color(key)
                self.view.colors[key] = value
                self.color_buttons[key].setText(value)
                self.color_buttons[key].setStyleSheet(f'border-left: 18px solid {value}; padding: 5px;')
        map_library = getattr(self, 'map_library', None)
        if map_library is not None:
            map_library.set_theme(dark)
        self.view.update()


from PyQt6.QtWidgets import QApplication
