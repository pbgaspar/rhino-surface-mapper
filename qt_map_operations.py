"""Operações e diálogos Qt para mapas, depósitos e rigs."""
import math
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
    QComboBox, QSpinBox, QFileDialog, QMessageBox, QMenu, QApplication, QDoubleSpinBox,
    QInputDialog)
from mapper_core import MapperState
from numeric_fields import MetresSpinBox, DegreesSpinBox, compact

# Margem usada para reconhecer automaticamente um PML e decidir se Novo está
# a começar a exploração de outra zona.
PML_MATCH_DISTANCE_M = 13_000

def maps_directory():
    """Dados do utilizador junto do programa, nunca na extração temporária do EXE."""
    base = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent
    directory = base / 'MAPAS'
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def safe_filename_component(value):
    """Conserva o nome legível, substituindo só caracteres proibidos no Windows."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(value)).strip().rstrip('. ')
    return cleaned or 'Sem nome'


def pml_filename(state):
    """Nome normalizado do ficheiro de um PML, sem inventar partes do planeta."""
    return f'{safe_filename_component(state.body)} [{safe_filename_component(state.pml_id)}].json'



class DepositDialog(QDialog):
    """Diálogo modal com nome, tamanho e número de rigs de um depósito."""
    def __init__(self, parent, existing=None):
        """Preenche os campos a partir de existing, ou usa valores iniciais.
        O diálogo só devolve os dados; não modifica diretamente o mapa."""
        super().__init__(parent)
        self.setWindowTitle('Editar depósito' if existing else 'Marcar depósito')
        data = existing or {}
        form = QFormLayout(self)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(4)
        self.name = QLineEdit(data.get('name',''))
        self.size = QComboBox()
        self.size.addItems(['Pequeno','Médio','Grande','Enorme'])
        self.size.setCurrentText(data.get('size','Pequeno'))
        self.rigs = QSpinBox()
        self.rigs.setSuffix(' rigs')
        self.rigs.setRange(1,6)
        self.rigs.setValue(int(data.get('rigs',1)))
        compact(self.rigs)
        form.addRow('Nome:', self.name)
        form.addRow('Tamanho:', self.size)
        form.addRow('Nº rigs:', self.rigs)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self):
        """Devolve um dicionário com os três campos editáveis.
        Um nome vazio recebe o texto Depósito; os outros campos são limitados pelos controlos."""
        return dict(name=self.name.text().strip() or 'Depósito', size=self.size.currentText(), rigs=self.rigs.value())


class MarkDialog(QDialog):
    """Introduz ou altera uma marca relativa ao Rhino ao abrir o diálogo."""
    def __init__(self, parent, existing=None):
        super().__init__(parent)
        self.setWindowTitle('Alterar marca' if existing else 'Marca')
        form = QFormLayout(self)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(4)
        self.name = QLineEdit()
        self.name.setMaxLength(120)
        self.azimuth = DegreesSpinBox()
        self.azimuth.setToolTip('0° Norte · 90° Este · 180° Sul · 270° Oeste')
        self.distance = MetresSpinBox()
        form.addRow('Nome da marca:', self.name)
        form.addRow('Azimute desde o norte:', self.azimuth)
        form.addRow('Distância ao Rhino:', self.distance)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.name.textChanged.connect(lambda text: buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(text.strip())))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        if existing:
            self.name.setText(existing['name'])
            self.azimuth.setValue(round(existing['azimuth']) % 360)
            self.distance.setValue(round(existing['distance']))
        # O formato inteiro é apenas apresentação. Conservar os valores antigos
        # se o utilizador não alterar o respetivo campo evita deslocar marcas.
        self.original_values = dict(existing) if existing else None
        self.initial_azimuth = self.azimuth.value()
        self.initial_distance = self.distance.value()
        if existing and existing['distance'] > self.distance.maximum():
            self.distance.setToolTip('Distância original superior a 99999 m. Será conservada se não alterar este campo.')

    def values(self):
        azimuth, distance = self.azimuth.value(), self.distance.value()
        if self.original_values:
            if azimuth == self.initial_azimuth:
                azimuth = self.original_values['azimuth']
            if distance == self.initial_distance:
                distance = self.original_values['distance']
        return dict(name=self.name.text().strip(), azimuth=azimuth, distance=distance)


class MapOperations:
    """Conjunto de métodos incorporado em MapperWindow por herança múltipla.
    Usa os atributos state, view e overlay da janela; não cria outra janela principal."""

    @staticmethod
    def surface_distance(radius, lat_a, lon_a, lat_b, lon_b):
        """Distância de grande círculo entre duas posições, em metros."""
        dlat = math.radians(lat_b-lat_a)
        dlon = math.radians(lon_b-lon_a)
        a = (math.sin(dlat/2)**2 + math.cos(math.radians(lat_a))
             * math.cos(math.radians(lat_b)) * math.sin(dlon/2)**2)
        return 2*radius*math.asin(min(1, math.sqrt(a)))

    def pml_path(self, state=None):
        """Devolve o destino canónico para um mapa já identificado como PML."""
        state = state or self.state
        if not (state.system.strip() and state.body.strip() and state.pml_id.strip()):
            return None
        return maps_directory() / safe_filename_component(state.system) / pml_filename(state)

    def choose_list_item(self, title, label, items):
        """Mostra uma lista com a seleção legível em temas claros e escuros."""
        dialog = QInputDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setComboBoxItems(items)
        dialog.setComboBoxEditable(False)
        combo = dialog.findChild(QComboBox)
        if combo is not None:
            combo.view().setStyleSheet(
                'QListView::item:selected { background: #2478c4; color: white; '
                'border: 1px solid #9fd4ff; }')
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.textValue()

    @staticmethod
    def infer_legacy_pml(state, path, system, body):
        """Completa metadados que os mapas antigos ainda não gravavam.

        A marca ``Centro [n]`` criada pela versão anterior é uma fonte fiável
        para recuperar o identificador e o centro, sem mexer no ficheiro até o
        utilizador escolher guardá-lo novamente.
        """
        if not state.system and path.parent.name.casefold() == safe_filename_component(system).casefold():
            state.system = system
        # Os dois mapas antigos não têm ainda metadados de PML. Neles, o nome
        # do ficheiro é a fonte mais específica: "Kappa 2 [20]" e
        # "Kappa 2 a [6]" são planetas diferentes, ainda que um JSON antigo
        # possa ter conservado por engano o nome do planeta anterior.
        legacy_name = re.fullmatch(r'(.+?)\s+\[[^\]]+\](?:\s+v\d+)?', path.stem,
                                   re.IGNORECASE)
        if (not state.pml_id and state.pml_center_lat is None and legacy_name):
            state.body = legacy_name.group(1).strip()
        elif not state.body:
            state.body = body
        for mark in state.marks:
            match = re.fullmatch(r'Centro\s*\[([^\]]+)\]', str(mark.get('name', '')).strip(), re.IGNORECASE)
            if match and 'lat' in mark and 'lon' in mark:
                state.pml_id = state.pml_id or match.group(1).strip()
                state.pml_center_lat = state.pml_center_lat if state.pml_center_lat is not None else mark['lat']
                state.pml_center_lon = state.pml_center_lon if state.pml_center_lon is not None else mark['lon']
                break
        state.body_key = f'{state.system}|{state.body}'

    def nearby_pml_maps(self, system, body, lat, lon):
        """Lê apenas mapas do sistema atual e devolve os PML até 10 km.

        Um ficheiro inválido ou de versão antiga sem centro de PML não bloqueia
        a entrada no Rhino; será simplesmente ignorado nesta deteção.
        """
        directory = maps_directory() / safe_filename_component(system)
        if not directory.is_dir():
            return []
        matches = []
        for path in directory.glob('*.json'):
            try:
                candidate = MapperState()
                candidate.load(path)
                self.infer_legacy_pml(candidate, path, system, body)
                if (candidate.system.casefold() != system.casefold()
                        or candidate.body.casefold() != body.casefold()
                        or candidate.pml_center_lat is None):
                    continue
                distance = self.surface_distance(candidate.radius, lat, lon,
                                                 candidate.pml_center_lat,
                                                 candidate.pml_center_lon)
                if distance < PML_MATCH_DISTANCE_M:
                    matches.append((distance, path, candidate))
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                continue
        return sorted(matches, key=lambda item: item[0])

    def nearby_pml_maps_without_system(self, body, lat, lon):
        """Procura apenas mapas existentes quando o jogo omite StarSystem.

        Não cria nada neste caso. A pasta do mapa já existente fornece o nome
        de sistema que faltou à telemetria, mas só depois de o planeta e o
        centro do PML confirmarem que se trata do mesmo local.
        """
        matches = []
        for directory in maps_directory().iterdir():
            if directory.is_dir():
                matches.extend(self.nearby_pml_maps(directory.name, body, lat, lon))
        return sorted(matches, key=lambda item: item[0])

    def next_john_doe_id(self, system, body):
        """Calcula o próximo JD apenas entre os mapas do planeta atual."""
        highest = 0
        directory = maps_directory() / safe_filename_component(system)
        if directory.is_dir():
            for path in directory.glob('*.json'):
                try:
                    candidate = MapperState()
                    candidate.load(path)
                    self.infer_legacy_pml(candidate, path, system, body)
                    if candidate.body.casefold() != body.casefold():
                        continue
                    match = re.fullmatch(r'JD(\d+)', candidate.pml_id.strip(), re.IGNORECASE)
                    if match:
                        highest = max(highest, int(match.group(1)))
                except (OSError, ValueError, TypeError, KeyError, AttributeError):
                    continue
        return f'JD{highest+1}'

    def install_loaded_map(self, candidate, source_text='Mapa carregado', source_path=None):
        """Troca o estado somente depois de um mapa já validado estar disponível."""
        if candidate.protected:
            choice = self.choose_protected_map_mode()
            if choice is None:
                return False
            if choice == 'mining':
                candidate.enter_mining_mode()
            else:
                import copy
                candidate = copy.deepcopy(candidate)
                candidate.protected = False
                candidate.mining_only = False
                candidate.created_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                candidate.last_saved_at = None
                source_path = self.write_new_version(candidate, source_path)
        if source_path:
            source_path = Path(source_path)
            if not candidate.read_only and candidate.populate_missing_timestamps(source_path):
                # Migração pontual de mapas antigos: conserva as datas que
                # estavam nas propriedades do ficheiro antes desta escrita.
                candidate.save(source_path, update_saved_at=False)
        self.cancel_placement()
        self.view.radar.waves.clear()
        self.stop_assistance()
        self.state = candidate
        self.view.state = candidate
        # Guarda o ficheiro efetivamente aberto. "Substituir" tem de escrever
        # neste caminho, incluindo quando se trata de uma versão antiga.
        self.current_map_path = Path(source_path) if source_path else None
        for field, spin in self.parameter_spins.items():
            spin.blockSignals(True)
            spin.setValue(int(getattr(candidate, field)))
            spin.blockSignals(False)
        points = ([] if candidate.mining_only else candidate.points) + candidate.deposits + candidate.rigs + candidate.marks
        if points:
            xs, ys = [p['x'] for p in points], [p['y'] for p in points]
            self.view.center = QPointF((min(xs)+max(xs))/2, (min(ys)+max(ys))/2)
            self.view.scale = max(0.001, min(10, min(
                self.view.width()/max(4000, max(xs)-min(xs)+2000),
                self.view.height()/max(4000, max(ys)-min(ys)+2000))))
        else:
            self.view.center = QPointF()
            self.view.scale = 0.08
        self.overlay_mode_active = False
        self.overlay_navigation_active = False
        self.info_left.setText(f'{candidate.system} — {candidate.body} | {source_text}')
        # O JSON do mapa não inclui a presença/posição atual do Rhino.
        # Reler já, mesmo parado e sem alteração da data de Status.json.
        self.last_mtime = None
        self.poll(reloading_map=True)
        return True

    def choose_protected_map_mode(self):
        """Pausa os temporizadores durante a decisão para não registar ao fundo."""
        timers = [getattr(self, name, None) for name in ('timer', 'radar_timer', 'assist_timer')]
        running = [(timer, timer.interval()) for timer in timers if timer is not None and timer.isActive()]
        for timer, _ in running:
            timer.stop()
        try:
            box = QMessageBox(self)
            box.setWindowTitle('Mapa protegido')
            box.setText('Como queres utilizar este mapa protegido?')
            box.setInformativeText('Continuar exploração cria uma nova versão editável. Só minerar permite consultar os pontos e navegar, sem registar alterações.')
            explore = box.addButton('Continuar exploração', QMessageBox.ButtonRole.AcceptRole)
            mining = box.addButton('Só minerar', QMessageBox.ButtonRole.ActionRole)
            box.addButton('Cancelar', QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(mining)
            box.exec()
            return 'explore' if box.clickedButton() is explore else 'mining' if box.clickedButton() is mining else None
        finally:
            for timer, interval in running:
                timer.start(interval)

    def map_is_read_only(self):
        """Impede operações de edição também quando chamadas por atalhos."""
        if not self.state.read_only:
            return False
        QMessageBox.information(self, 'Mapa só para consulta',
                                'Abre o mapa e escolhe Continuar exploração para criar uma nova versão editável.')
        return True

    def write_new_version(self, state, source_path=None):
        """Escolhe um nome livre para a cópia, incluindo mapas antigos sem PML."""
        canonical = self.pml_path(state)
        if canonical is None and source_path:
            canonical = Path(source_path)
            canonical = canonical.with_name(re.sub(r' v\d+$', '', canonical.stem) + '.json')
        if canonical is None:
            raise ValueError('O mapa ainda não tem um ficheiro ou PML identificado.')
        canonical.parent.mkdir(parents=True, exist_ok=True)
        expression = re.compile(rf'^{re.escape(canonical.stem)} v(\d+)\.json$', re.IGNORECASE)
        highest = max([1] + [int(match.group(1)) for path in canonical.parent.iterdir()
                            if (match := expression.fullmatch(path.name))])
        destination = canonical.with_name(f'{canonical.stem} v{highest+1}.json')
        state.save(destination)
        return destination

    def setup_new_pml(self):
        """Pede os dados mínimos para identificar um PML ainda desconhecido."""
        s = self.state
        prompt = ('Número do PML nesta zona. Deixa vazio se ainda não o conheces.')
        pml_id, accepted = QInputDialog.getText(self, 'Novo PML', prompt)
        if not accepted:
            return False
        pml_id = pml_id.strip()
        if not pml_id:
            if QMessageBox.question(
                    self, 'PML desconhecido',
                    'Não foi indicado um PML. Criar a identificação temporária seguinte?'
            ) != QMessageBox.StandardButton.Yes:
                return False
            pml_id = self.next_john_doe_id(s.system, s.body)
        azimuth_dialog = QInputDialog(self)
        azimuth_dialog.setWindowTitle(f'Centro do PML [{pml_id}]')
        azimuth_dialog.setLabelText('Azimute do Rhino para o centro do PML (0° = norte):')
        azimuth_dialog.setInputMode(QInputDialog.InputMode.IntInput)
        azimuth_dialog.setIntRange(0, 359)
        azimuth_dialog.setIntStep(1)
        azimuth_dialog.setIntValue(0)
        azimuth_spin = azimuth_dialog.findChild(QSpinBox)
        if azimuth_spin is not None:
            azimuth_spin.setWrapping(True)
        if azimuth_dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        azimuth = azimuth_dialog.intValue()
        distance, accepted = QInputDialog.getDouble(
            self, f'Centro do PML [{pml_id}]',
            'Distância do Rhino ao centro do PML (m):', 0, 0, 100000, 0)
        if not accepted:
            return False
        coordinates = self.mark_coordinates(s, s.rhino_lat, s.rhino_lon,
                                            {'azimuth': azimuth, 'distance': distance})
        s.pml_id = pml_id
        s.pml_center_lat, s.pml_center_lon = coordinates['lat'], coordinates['lon']
        s.created_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        s.last_saved_at = None
        s.marks.append(dict(name=f'Centro [{pml_id}]', **coordinates))
        self.statusBar().showMessage(f'PML [{pml_id}] criado. Guarda o mapa para o conservar.')
        return True

    def open_or_create_pml_for_current_position(self):
        """Abre o PML próximo ou inicia a identificação de um PML novo.

        Só é chamado com sistema, planeta e posição fornecidos pelo jogo. Assim
        nunca são criadas pastas John Doe por falta temporária de telemetria.
        """
        s = self.state
        if not (s.body.strip() and s.rhino_lat is not None):
            return
        system_is_known = bool(s.system.strip())
        matches = (self.nearby_pml_maps(s.system, s.body, s.rhino_lat, s.rhino_lon)
                   if system_is_known else
                   self.nearby_pml_maps_without_system(s.body, s.rhino_lat, s.rhino_lon))
        # Várias versões do mesmo PML não são vários PML. Abrimos a cópia mais
        # recente automaticamente; as versões antigas continuam disponíveis em
        # Abrir, sem interromper a entrada normal no Rhino.
        newest_by_pml = {}
        for item in matches:
            pml_id = item[2].pml_id.casefold()
            if (pml_id not in newest_by_pml
                    or item[1].stat().st_mtime > newest_by_pml[pml_id][1].stat().st_mtime):
                newest_by_pml[pml_id] = item
        matches = list(newest_by_pml.values())
        if len(matches) == 1:
            _, path, candidate = matches[0]
            # O Status.json por vezes omite StarSystem. Para abrir um mapa já
            # confirmado pela pasta, pelo planeta e pelo centro do PML, usamos
            # o sistema guardado sem o inventar nem o gravar na telemetria.
            status = dict(self.live_status)
            status['StarSystem'] = candidate.system
            status['BodyName'] = candidate.body
            candidate.process_status(status)
            if not self.install_loaded_map(candidate, f'PML [{candidate.pml_id}] aberto', path):
                return
            self.statusBar().showMessage(f'Mapa aberto: {path.name}')
            return
        if len(matches) > 1:
            # Aqui cada entrada é um PML distinto; a data permite escolher a
            # cópia mais recentemente gravada quando as distâncias são próximas.
            matches.sort(key=lambda item: item[1].stat().st_mtime, reverse=True)
            labels = [f'[{candidate.pml_id}] — guardado {datetime.fromtimestamp(path.stat().st_mtime):%Y-%m-%d %H:%M} — {distance/1000:.1f} km'
                      for distance, path, candidate in matches]
            chosen = self.choose_list_item('Vários PML próximos', 'Escolhe o PML:', labels)
            if chosen is None:
                return
            index = labels.index(chosen)
            _, path, candidate = matches[index]
            status = dict(self.live_status)
            status['StarSystem'] = candidate.system
            status['BodyName'] = candidate.body
            candidate.process_status(status)
            if not self.install_loaded_map(candidate, f'PML [{candidate.pml_id}] aberto', path):
                return
            self.statusBar().showMessage(f'Mapa aberto: {path.name}')
            return
        if system_is_known:
            if self.setup_new_pml():
                # O primeiro mapa de um PML tem sempre o nome principal, sem
                # sufixo de versão. Passa logo a ser o mapa atual.
                path = self.pml_path()
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    self.state.save(path)
                    self.current_map_path = path
                    self.statusBar().showMessage(f'PML [{self.state.pml_id}] criado: {path.name}')
                except OSError as exc:
                    QMessageBox.critical(self, 'Erro ao criar PML', str(exc))
        else:
            self.statusBar().showMessage('O jogo não informou o sistema; não é possível criar um PML novo.')

    def save_new_pml_version(self):
        """Guarda uma versão adicional sem alterar as versões já existentes.

        A data de gravação é apresentada na lista e usada na ordenação. O nome
        conserva apenas a versão para não confundir "Substituir" com renomear.
        """
        if self.state.read_only:
            raise PermissionError('Abre o mapa e escolhe Continuar exploração.')
        canonical = self.pml_path()
        if canonical is None:
            raise ValueError('O mapa ainda não tem sistema, planeta e PML identificados.')
        canonical.parent.mkdir(parents=True, exist_ok=True)
        highest = 1
        expression = re.compile(rf'^{re.escape(canonical.stem)} v(\d+)\.json$', re.IGNORECASE)
        # Não usar Path.glob com canonical.stem: os parênteses retos do PML
        # seriam interpretados como padrão e fariam sempre voltar a criar v2.
        for path in canonical.parent.iterdir():
            if not path.is_file():
                continue
            match = expression.fullmatch(path.name)
            if match:
                highest = max(highest, int(match.group(1)))
        candidate = canonical.with_name(f'{canonical.stem} v{highest+1}.json')
        self.state.save(candidate)
        self.current_map_path = candidate
        return candidate

    def confirm_pml_exit(self):
        """Pede a operação de gravação comum ao X e ao botão Sair.

        Mapas anteriores à gestão de PML mantêm o comportamento antigo para não
        surpreender quem ainda os esteja a abrir apenas para consulta.
        """
        if self.state.read_only or self.pml_path() is None:
            return True
        message = QMessageBox(self)
        message.setWindowTitle('Guardar mapa do PML')
        message.setText(f'PML [{self.state.pml_id}]: como queres guardar antes de sair?')
        new_version = message.addButton('Gravar nova versão', QMessageBox.ButtonRole.ActionRole)
        replace = message.addButton('Substituir', QMessageBox.ButtonRole.AcceptRole)
        discard = message.addButton('Sair sem gravar', QMessageBox.ButtonRole.DestructiveRole)
        cancel = message.addButton('Cancelar', QMessageBox.ButtonRole.RejectRole)
        message.setDefaultButton(replace)
        message.exec()
        try:
            if message.clickedButton() is cancel:
                return False
            if message.clickedButton() is discard:
                return True
            if message.clickedButton() is new_version:
                path = self.save_new_pml_version()
            else:
                path = self.current_map_path or self.pml_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                self.state.save(path)
            self.statusBar().showMessage(f'Mapa guardado: {path.name}')
            return True
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, 'Erro ao guardar', str(exc))
            return False

    def prepare_to_replace_current_map(self, next_action):
        """Resolve o destino das alterações antes de Abrir ou Novo.

        Apagar descarta apenas as alterações em memória; nunca apaga um
        ficheiro no disco. Gravar substitui o ficheiro ativo e Nova Versão cria
        uma cópia numerada antes de mudar de mapa.
        """
        s = self.state
        has_current_map = bool(self.current_map_path or s.pml_id.strip())
        if s.read_only:
            return True
        if not has_current_map:
            return True
        # Compatibilidade com mapas antigos, que ainda não têm um PML nem um
        # ficheiro ativo onde guardar uma versão.
        if self.pml_path() is None:
            return (QMessageBox.question(self, next_action, 'Apagar o mapa atual?')
                    == QMessageBox.StandardButton.Yes)
        message = QMessageBox(self)
        message.setWindowTitle(next_action)
        message.setText(f'Que queres fazer ao mapa atual antes de {next_action.lower()}?')
        discard = message.addButton('Não gravar', QMessageBox.ButtonRole.DestructiveRole)
        new_version = message.addButton('Nova Versão', QMessageBox.ButtonRole.ActionRole)
        save = message.addButton('Gravar', QMessageBox.ButtonRole.AcceptRole)
        cancel = message.addButton('Cancelar', QMessageBox.ButtonRole.RejectRole)
        message.setDefaultButton(save)
        message.exec()
        if message.clickedButton() is cancel:
            return False
        try:
            if message.clickedButton() is new_version:
                path = self.save_new_pml_version()
                self.statusBar().showMessage(f'Nova versão gravada: {path.name}')
            elif message.clickedButton() is save:
                path = self.current_map_path or self.pml_path()
                if path is None:
                    raise ValueError('O mapa atual ainda não tem um ficheiro associado.')
                path.parent.mkdir(parents=True, exist_ok=True)
                self.state.save(path)
                self.current_map_path = path
            # Não gravar: continuar sem escrever nem apagar qualquer ficheiro.
            self.refresh(redraw_map=False)
            return True
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, 'Erro ao guardar', str(exc))
            return False

    def new_map(self):
        """Pede confirmação quando há dados e limpa o mapa, mantendo telemetria.
        Cancela uma colocação pendente e atualiza o overlay ao terminar o modo de busca."""
        if not self.prepare_to_replace_current_map('Novo mapa'):
            return
        s = self.state
        if (s.pml_center_lat is not None and s.rhino_lat is not None
                and self.surface_distance(s.radius, s.rhino_lat, s.rhino_lon,
                                          s.pml_center_lat, s.pml_center_lon)
                > PML_MATCH_DISTANCE_M):
            answer = QMessageBox.question(
                self, 'Novo mapa noutro PML',
                'Estás a mais de 13 km do centro deste PML. Trata-se de outro PML?')
            if answer == QMessageBox.StandardButton.Yes:
                # A partir daqui o mapa anterior deixa de ser o contexto
                # ativo: Centro [6] não pode acompanhar Centro [JD1].
                self.cancel_placement()
                self.state.new_map()
                self.current_map_path = None
                self.open_or_create_pml_for_current_position()
                return
        self.cancel_placement()
        # Novo começa um registo limpo, mas continua no PML atual. Assim Abrir,
        # Guardar e Sair não regressam ao comportamento genérico de ficheiros.
        self.state.new_map(keep_pml=True)
        self.state.created_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        self.state.last_saved_at = None
        self.current_map_path = None
        if self.state.pml_center_lat is not None:
            x, y = self.state.llxy(self.state.pml_center_lat, self.state.pml_center_lon)
            self.state.marks.append(dict(name=f'Centro [{self.state.pml_id}]', x=x, y=y,
                                         lat=self.state.pml_center_lat,
                                         lon=self.state.pml_center_lon))
        try:
            path = self.save_new_pml_version()
            self.statusBar().showMessage(f'Novo mapa criado: {path.name}')
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, 'Erro ao criar mapa novo', str(exc))
        self.view.scale = 0.08
        self.view.recenter()
        self.refresh()

    def save_map(self):
        """Guarda o PML atual após escolher substituir ou criar uma versão."""
        if self.map_is_read_only():
            return
        if self.state.center_lat is None:
            QMessageBox.information(self,'Guardar','Ainda não existe um mapa para guardar.')
            return
        try:
            directory = maps_directory()
        except OSError as exc:
            QMessageBox.critical(self,'Erro ao preparar MAPAS',str(exc))
            return
        canonical_path = self.current_map_path or self.pml_path()
        if canonical_path is not None:
            question = QMessageBox(self)
            question.setWindowTitle('Guardar mapa')
            question.setText('Como queres guardar este mapa?')
            new_version = question.addButton('Gravar nova versão', QMessageBox.ButtonRole.ActionRole)
            replace = question.addButton('Substituir', QMessageBox.ButtonRole.AcceptRole)
            cancel = question.addButton('Cancelar', QMessageBox.ButtonRole.RejectRole)
            question.setDefaultButton(replace)
            question.exec()
            if question.clickedButton() is cancel:
                return
            if question.clickedButton() is new_version:
                try:
                    path = self.save_new_pml_version()
                    self.statusBar().showMessage(f'Mapa guardado: {path.name}')
                    self.refresh(redraw_map=False)
                except (OSError, ValueError) as exc:
                    QMessageBox.critical(self, 'Erro ao guardar', str(exc))
                return
            path = canonical_path
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path, _ = QFileDialog.getSaveFileName(self,'Guardar mapa',str(directory / 'mapa.json'),'Rhino Map (*.json)')
            if not path:
                return
            if not Path(path).suffix:
                path += '.json'
        try:
            self.state.save(Path(path))
            self.current_map_path = Path(path)
            self.statusBar().showMessage(f'Mapa guardado: {Path(path).name}')
            self.refresh(redraw_map=False)
        except OSError as exc:
            QMessageBox.critical(self,'Erro ao guardar',str(exc))

    def load_map(self):
        """Abre uma versão do PML atual, sem navegar por todos os sistemas."""
        s = self.state
        if not (s.system.strip() and s.body.strip() and s.pml_id.strip()):
            # Mantém o seletor genérico apenas para mapas antigos, sem PML.
            # É também útil para recuperar um ficheiro antes de o migrar.
            try:
                directory = maps_directory()
            except OSError as exc:
                QMessageBox.critical(self, 'Erro ao preparar MAPAS', str(exc))
                return
            path, _ = QFileDialog.getOpenFileName(self, 'Abrir mapa', str(directory), 'Rhino Map (*.json)')
            if not path:
                return
            try:
                candidate = MapperState()
                candidate.load(Path(path))
            except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError, ZeroDivisionError) as exc:
                QMessageBox.critical(self, 'Erro ao abrir', str(exc))
                return
        else:
            try:
                directory = self.pml_path().parent
            except OSError as exc:
                QMessageBox.critical(self,'Erro ao preparar MAPAS',str(exc))
                return
            versions = []
            for path in directory.glob('*.json'):
                try:
                    candidate = MapperState()
                    candidate.load(path)
                    self.infer_legacy_pml(candidate, path, s.system, s.body)
                    if candidate.body.casefold() == s.body.casefold() and candidate.pml_id.casefold() == s.pml_id.casefold():
                        versions.append((path, candidate))
                except (OSError, ValueError, TypeError, KeyError, AttributeError):
                    continue
            if not versions:
                QMessageBox.information(self, 'Abrir', 'Ainda não existe uma versão guardada deste PML.')
                return
            versions.sort(key=lambda item: item[0].stat().st_mtime, reverse=True)
            labels = [f'{datetime.fromtimestamp(path.stat().st_mtime):%Y-%m-%d %H:%M} — {path.name}'
                      for path, _ in versions]
            selected = self.choose_list_item(f'Abrir PML [{s.pml_id}]', 'Versão:', labels)
            if selected is None:
                return
            path, candidate = versions[labels.index(selected)]
        try:
            if not self.prepare_to_replace_current_map('Abrir mapa'):
                return
            if not self.install_loaded_map(candidate, source_path=path):
                return
        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError, ZeroDivisionError) as exc:
            QMessageBox.critical(self,'Erro ao abrir',str(exc))

    def edit_deposit_values(self, existing=None):
        """Executa o editor e devolve os campos aceites, ou None se for cancelado."""
        dialog = DepositDialog(self, existing)
        return dialog.values() if dialog.exec() == QDialog.DialogCode.Accepted else None

    def mark_deposit(self):
        """Regista um depósito na posição do Rhino capturada antes do diálogo.
        Impede duplicados a menos de 80 metros e verifica se o planeta mudou durante a edição."""
        if self.map_is_read_only():
            return
        s = self.state
        if s.rhino_lat is None or s.center_lat is None:
            QMessageBox.information(self,'Depósito','Primeiro entra no Rhino.')
            return
        lat, lon = s.rhino_lat, s.rhino_lon
        body_key = s.body_key
        for deposit in s.deposits:
            dlat, dlon = math.radians(lat-deposit['lat']), math.radians(lon-deposit['lon'])
            # Fórmula de haversine: distância na superfície da esfera, em vez
            # de comparar graus diretamente ou usar a escala visual do mapa.
            a = math.sin(dlat/2)**2 + math.cos(math.radians(lat))*math.cos(math.radians(deposit['lat']))*math.sin(dlon/2)**2
            if 2*s.radius*math.asin(min(1,math.sqrt(a))) < 80:
                QMessageBox.information(self,'Depósito já marcado','Já existe um depósito a menos de 80 m.')
                return
        values = self.edit_deposit_values()
        # Telemetria pode mudar durante o diálogo modal.
        if values is not None and self.state is s and not s.read_only and s.body_key == body_key:
            x,y = s.llxy(lat,lon)
            s.deposits.append(dict(x=x,y=y,lat=lat,lon=lon,**values))
            self.refresh()

    def edit_mark_values(self, existing=None):
        dialog = MarkDialog(self, existing)
        return dialog.values() if dialog.exec() == QDialog.DialogCode.Accepted else None

    def mark(self):
        """Captura a origem antes do diálogo e calcula o destino na esfera."""
        if self.map_is_read_only():
            return
        s = self.state
        if s.rhino_lat is None or s.center_lat is None:
            QMessageBox.information(self, 'Marca', 'Primeiro entra no Rhino e aguarda a posição.')
            return
        self.cancel_placement()
        lat, lon, body = s.rhino_lat, s.rhino_lon, s.body_key
        values = self.edit_mark_values()
        if values is None or self.state is not s or s.read_only or s.body_key != body:
            return
        s.marks.append(dict(name=values['name'], **self.mark_coordinates(s, lat, lon, values)))
        self.refresh()

    def alter_mark(self, item):
        """Edita todos os campos com referência ao Rhino capturado à abertura."""
        if self.map_is_read_only():
            return
        s = self.state
        if s.rhino_lat is None or s.center_lat is None:
            QMessageBox.information(self, 'Alterar marca', 'Primeiro entra no Rhino e aguarda a posição.')
            return
        lat, lon, body = s.rhino_lat, s.rhino_lon, s.body_key
        phi, target_phi = math.radians(lat), math.radians(item['lat'])
        delta = math.radians(item['lon']-lon)
        east = math.sin(delta)*math.cos(target_phi)
        north = math.cos(phi)*math.sin(target_phi)-math.sin(phi)*math.cos(target_phi)*math.cos(delta)
        a = math.sin((target_phi-phi)/2)**2 + math.cos(phi)*math.cos(target_phi)*math.sin(delta/2)**2
        existing = dict(name=item['name'],
                        azimuth=round(math.degrees(math.atan2(east, north)) % 360) % 360,
                        distance=round(2*s.radius*math.asin(math.sqrt(max(0, min(1, a)))), 2))
        values = self.edit_mark_values(existing)
        if (values is None or self.state is not s or s.read_only or s.body_key != body
                or not any(mark is item for mark in s.marks)):
            return
        # Aceitar apenas um nome novo não desloca a marca pelo arredondamento dos campos.
        if values['azimuth'] != existing['azimuth'] or values['distance'] != existing['distance']:
            item.update(self.mark_coordinates(s, lat, lon, values))
        item['name'] = values['name']
        self.refresh()

    @staticmethod
    def mark_coordinates(s, lat, lon, values):
        bearing = math.radians(values['azimuth'])
        arc = values['distance'] / s.radius
        phi, lam = math.radians(lat), math.radians(lon)
        dest_phi = math.asin(max(-1, min(1, math.sin(phi)*math.cos(arc) + math.cos(phi)*math.sin(arc)*math.cos(bearing))))
        dest_lam = lam + math.atan2(math.sin(bearing)*math.sin(arc)*math.cos(phi), math.cos(arc)-math.sin(phi)*math.sin(dest_phi))
        lat, lon = math.degrees(dest_phi), (math.degrees(dest_lam)+180)%360-180
        x, y = s.llxy(lat, lon)
        return dict(x=x, y=y, lat=lat, lon=lon)

    def mark_rig(self):
        """Ativa a colocação de um único rig por clique no mapa.
        Ainda não cria um marcador: é necessário escolher a posição ou cancelar com Escape."""
        if self.map_is_read_only():
            return
        if self.state.center_lat is None:
            QMessageBox.information(self,'Rig','Primeiro entra no Rhino.')
            return
        self.placing_rig = True
        self.statusBar().showMessage('Clica no mapa para colocar o rig. Escape cancela.')

    def cancel_placement(self):
        """Desativa a colocação pendente e limpa a instrução da barra de estado."""
        self.placing_rig = False
        self.statusBar().clearMessage()

    def place_rig(self, point):
        """Converte o clique de píxeis para metros e latitude/longitude e cria um rig.
        Desativa imediatamente a colocação para não criar rigs em cliques posteriores."""
        if self.state.read_only or not self.placing_rig or self.state.center_lat is None:
            return
        q = self.view.world(point)
        lat, lon = self.state.xyll(q.x(), q.y())
        self.state.rigs.append(dict(x=q.x(), y=q.y(), lat=lat, lon=lon))
        self.cancel_placement()
        self.refresh()

    def edit_deposit(self, item):
        """Aplica os campos aceites apenas se o depósito ainda pertencer ao mapa.
        Cancelar mantém os dados originais; a posição geográfica não é alterada."""
        if self.map_is_read_only():
            return
        values = self.edit_deposit_values(item)
        if values is not None and not self.state.read_only and any(d is item for d in self.state.deposits):
            item.update(values)
            self.refresh()

    def delete_marker(self, kind, item):
        """Remove o marcador por identidade depois de confirmação.
        Comparar com is evita apagar outro dicionário que tenha os mesmos valores."""
        if self.map_is_read_only():
            return
        if QMessageBox.question(self,'Apagar marcador','Apagar este marcador?') == QMessageBox.StandardButton.Yes:
            items = getattr(self.state,kind)
            for index, candidate in enumerate(items):
                if candidate is item:
                    del items[index]
                    break
            if self.state.active_nav_target and self.state.active_nav_target.get('item') is item:
                self.stop_navigation()
            self.refresh()

    def is_navigating_to(self, kind, item):
        """Verifica se o marcador indicado é o destino ativo de navegação."""
        target = self.state.active_nav_target
        if target is None:
            return False
        return target.get('item') is item

    def start_navigation(self, kind, item):
        """Inicia a navegação para uma marca, depósito, rig ou ponto da rota."""
        s = self.state
        if s.read_only and kind == 'route':
            return
        if s.rhino_lat is None or s.center_lat is None:
            QMessageBox.information(self, 'Navegar', 'Primeiro entra no Rhino e aguarda a posição.')
            return

        if kind == 'marks':
            x, y = s.llxy(item['lat'], item['lon'])
            name = f"[Marca] {item['name']}"
            target_data = {'type': kind, 'item': item, 'name': name, 'x': x, 'y': y, 'lat': item['lat'], 'lon': item['lon']}
        elif kind == 'deposits':
            x, y = item['x'], item['y']
            name = f"[Depósito] {item.get('name', 'Depósito')}"
            target_data = {'type': kind, 'item': item, 'name': name, 'x': x, 'y': y, 'lat': item.get('lat'), 'lon': item.get('lon')}
        elif kind == 'rigs':
            x, y = item['x'], item['y']
            name = "[Rig]"
            target_data = {'type': kind, 'item': item, 'name': name, 'x': x, 'y': y, 'lat': item.get('lat'), 'lon': item.get('lon')}
        elif kind == 'route':
            x, y = item['x'], item['y']
            num = item.get('number', s.route_index + 1)
            name = f"[Busca] Ponto {num}"
            target_data = {'type': kind, 'item': item, 'name': name, 'x': x, 'y': y}
        else:
            return

        if s.search_started and not s.search_paused:
            s.search_paused = True
            s.search_pause_point = s.llxy(s.rhino_lat, s.rhino_lon)

        s.return_to_pause = False
        s.active_nav_target = target_data
        self.statusBar().showMessage(f"A navegar para: {name}")
        self.refresh()

    def stop_navigation(self):
        """Cancela a navegação direta e gere o regresso ao ponto de pausa se aplicável."""
        s = self.state
        s.active_nav_target = None
        if s.search_paused and s.search_pause_point is not None:
            s.return_to_pause = True
            self.statusBar().showMessage("Navegação parada. A regressar ao Ponto de Pausa ⏸.")
        else:
            s.search_paused = False
            s.search_pause_point = None
            s.return_to_pause = False
            self.statusBar().showMessage("Navegação parada.")
        self.refresh()

    def marker_menu(self, position):
        """Abre o menu adequado ao marcador sob o rato.
        As funções lambda adiam a ação até o utilizador escolher a opção."""
        found = self.view.marker_at(position)
        if found is None:
            return
        kind, item = found
        menu = QMenu(self)

        # Opção Navegar / Parar navegação para todos os tipos de marcadores
        if self.is_navigating_to(kind, item):
            menu.addAction('Parar navegação', self.stop_navigation)
        else:
            menu.addAction('Navegar', lambda: self.start_navigation(kind, item))
        menu.addSeparator()

        if self.state.read_only:
            details = f"Nome: {item.get('name', 'Rig' if kind == 'rigs' else 'Marca')}"
            if kind == 'deposits':
                details += f"\nTamanho: {item.get('size', '—')}\nRigs: {item.get('rigs', 0)}"
            details += f"\nLatitude: {item.get('lat', 0):.5f}°\nLongitude: {item.get('lon', 0):.5f}°"
            menu.addAction('Informações', lambda: QMessageBox.information(self, 'Ponto marcado', details))
            menu.addAction('Copiar coordenadas', lambda: QApplication.clipboard().setText(
                f"{item.get('lat', 0):.5f} {item.get('lon', 0):.5f}"))
            menu.exec(self.view.mapToGlobal(position.toPoint()))
            return

        if kind == 'marks':
            menu.addAction('Alterar', lambda: self.alter_mark(item))
            menu.addAction('Apagar', lambda: self.delete_marker(kind, item))
        elif kind == 'deposits':
            menu.addAction('Copiar coordenadas', lambda: QApplication.clipboard().setText(f"{item['lat']:.5f} {item['lon']:.5f}"))
            menu.addAction('Editar depósito', lambda: self.edit_deposit(item))
            menu.addAction('Apagar depósito', lambda: self.delete_marker(kind, item))
        elif kind == 'rigs':
            menu.addAction('Apagar rig', lambda: self.delete_marker(kind, item))
        elif kind == 'route':
            pass

        menu.addSeparator()
        menu.addAction('Cancelar')
        menu.exec(self.view.mapToGlobal(position.toPoint()))
