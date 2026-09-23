"""Liga a assistência à janela, mantendo as decisões separadas da entrada Windows."""
import time
import math
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import QTimer
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import QPushButton, QLabel, QMessageBox
from steering import SteeringAssist
from steering_input import SteeringInput
from turn_trial import TurnTrial


class SteeringUI:
    def setup_steering(self, layout, options):
        self.assist = SteeringAssist()
        # Ensaio temporário pedido pelo utilizador. Não usa o controlador
        # adaptativo nem os seus limites de velocidade/rumo.
        self.direction_test = False
        self.direction_test_started = 0
        self.turn_trial = TurnTrial()
        self.turn_results_directory = Path(__file__).resolve().parent/'logs'
        self.turn_index = None
        self.turn_tick = None
        for key, attr, low, high, factor in (
                ('assist_speed', 'max_speed',15,40,1), ('assist_pulse_ms','max_pulse',200,1000,.001)):
            value = options.get(key)
            if type(value) in (int,float) and low<=value<=high:
                setattr(self.assist,attr,value*factor)
        tolerance = options.get('assist_tolerance_deg', 3)
        if type(tolerance) is int and 0 <= tolerance <= 180:
            self.assist.tolerance = tolerance
        self.steering_input = SteeringInput(self.radar_input)
        self.steering_input.load()
        self.assist_pending = 0
        self.assist_context = None
        self.f8_down = False
        self.braking_until = 0
        self.navigation_arrivals = 0
        self.assist_button = QPushButton('Ass. Direção [F8]')
        self.assist_button.clicked.connect(self.toggle_assistance)
        layout.addWidget(self.assist_button)
        self.assist_info = QLabel(self.steering_input.message)
        layout.addWidget(self.assist_info)
        self.assist_shortcut = QShortcut(QKeySequence('F8'),self)
        self.assist_shortcut.activated.connect(self.toggle_assistance)
        self.assist_timer = QTimer(self)
        self.assist_timer.timeout.connect(self.update_assistance)
        self.assist_timer.start(16)

    def steering_target(self):
        s = self.state
        if s.active_nav_target is not None:
            return (s.active_nav_target['x'],s.active_nav_target['y'])
        if s.return_to_pause:
            return s.search_pause_point
        if s.search_started and not s.search_paused:
            return s.next_target_xy
        return None

    def pause_assistance(self, reason):
        self.steering_input.release()
        self.assist.reset_samples()
        self.assist.wait(reason)
        self.assist_info.setText('Assistência em espera: '+reason)
        self.overlay.set_assistance_notice('Assistência em espera: '+reason)

    def stop_assistance(self, reason='Assistência desligada'):
        self.assist_pending = 0
        self.braking_until = 0
        self.assist.stop(reason)
        self.steering_input.release()
        self.turn_trial.finish(time.monotonic(),complete=False)
        self.turn_index = None

    def toggle_assistance(self):
        if self.assist.enabled or self.assist_pending or self.braking_until:
            self.stop_assistance()
            return
        self.steering_input.load()
        if not self.steering_input.keys:
            self.assist_info.setText(self.steering_input.message)
            QMessageBox.information(self,'Assistência de direção',self.steering_input.message)
            return
        if not self.status_valid or not self.state.in_srv or (not self.direction_test and self.steering_target() is None):
            self.assist_info.setText('Primeiro entra no Rhino; a assistência normal também exige um destino.')
            return
        self.assist_context = (id(self.state),self.state.body_key,self.state.map_generation)
        self.assist_pending = time.monotonic()+10
        self.assist.message = 'Assistência: aguarda foco no jogo'
        self.update_assistance()

    def update_assistance(self):
        """F8 no jogo, validação do contexto e libertação em todas as suspensões."""
        try:
            self._update_assistance()
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.pause_assistance(f'Falha temporária: {exc}')

    def _update_assistance(self):
        now = time.monotonic()
        focused = self.radar_input.game_focused()
        down = bool(self.radar_input.user.GetAsyncKeyState(0x77)&0x8000) if self.radar_input.available else False
        rising = down and not self.f8_down
        self.f8_down = down
        if rising and focused:
            self.toggle_assistance()
            return
        s = self.state
        context = (id(s),s.body_key,s.map_generation)
        arrivals = getattr(s, 'navigation_arrivals', 0)
        arrived = arrivals != self.navigation_arrivals and context == self.assist_context
        self.navigation_arrivals = arrivals
        if arrived and self.assist.enabled:
            self.stop_assistance('Destino atingido')
            if focused and self.status_valid and s.in_srv and self.steering_input.brake():
                self.braking_until = now+3.0
        if self.braking_until:
            if (now >= self.braking_until or not focused or not self.status_valid
                    or not s.in_srv or self.steering_input.manual() is True):
                self.stop_assistance('Assistência desligada: chegada concluída/interrompida')
            else:
                self.assist_info.setText('Destino atingido: a travar (S durante 3 s)')
                self.overlay.set_assistance_notice('Destino atingido: a travar')
                return
        target = self.steering_target()
        if context != self.assist_context:
            self.pause_assistance('Aguarda posição no mapa')
            self.assist.reset_samples()
            self.assist_context = context
        if self.assist.enabled or self.assist_pending:
            manual = self.steering_input.manual()
            if not self.direction_test and target is None:
                self.stop_assistance('Assistência desligada: navegação/busca terminada')
            elif manual is True:
                self.stop_assistance('Assistência desligada: direção manual')
            elif not focused:
                self.pause_assistance('Aguarda foco no jogo')
                return
            elif not self.status_valid or not s.in_srv:
                self.pause_assistance('Aguarda posição válida no Rhino')
                return
            elif self.live_status.get('GuiFocus',0)!=0 or int(self.live_status.get('Flags',0)) & (1<<13):
                self.pause_assistance('Aguarda fecho do painel/torre')
                return
            elif manual is None:
                self.pause_assistance('Aguarda leitura do joystick')
                return
            elif self.steering_input.error:
                self.pause_assistance(self.steering_input.error)
                self.steering_input.error = ''
                return
            elif self.assist_pending:
                self.assist_pending = 0
                self.assist.start()
                self.direction_test_started = now
                if self.direction_test:
                    path=self.turn_results_directory/('direcao-2s-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.csv')
                    self.turn_trial=TurnTrial(path)
                    self.turn_index=None
                    self.turn_tick=now
            elif not self.direction_test:
                command = self.assist.decide(now,target)
                if command:
                    if self.steering_input.pulse(*command) is False:
                        if self.steering_input.error:
                            self.pause_assistance(self.steering_input.error)
                        else:
                            self.assist.wait('Comando não enviado')
                elif self.assist.message == 'Reduzir velocidade' or 'aguarda' in self.assist.message:
                    self.steering_input.release()
        if self.direction_test and self.assist.enabled and focused:
            elapsed = max(0,now-self.direction_test_started)
            if (self.turn_tick is not None and now-self.turn_tick>.15
                    and (self.turn_tick-self.direction_test_started)%7<2
                    and self.turn_trial.current is not None):
                self.turn_trial.current['gap']=True
            self.turn_tick=now
            index = int(elapsed//7)
            offset = elapsed%7
            turn_direction = -1 if index%2==0 else 1
            if index != self.turn_index:
                # Só guinadas completas com telemetria suficiente entram na média.
                self.turn_trial.finish(now,complete=(self.turn_index is not None and index==self.turn_index+1))
                self.turn_index=index
                self.turn_trial.begin(turn_direction,now,self.assist.sample)
            motion=self.assist.motion
            self.turn_trial.observe(self.assist.sample,motion[2] if motion else None)
            remaining = 2-offset if offset<2 else 7-offset
            direction = turn_direction if offset<2 else 0
            label = ('ESQUERDA' if turn_direction<0 else 'DIREITA') if direction else 'EM FRENTE'
            if direction:
                if self.steering_input.hold_test(direction,remaining) is False:
                    self.stop_assistance(self.steering_input.error or 'Teste interrompido: comando não enviado')
            else:
                self.steering_input.release()
            if self.assist.enabled:
                self.assist.message = f'{label} {math.ceil(remaining)} s · {self.turn_trial.summary()}'
        active = self.assist.enabled or bool(self.assist_pending)
        mode = 'teste' if self.direction_test else 'assistência'
        self.assist_button.setText('Ass. Direção [F8]')
        self.assist_button.setCheckable(True)
        self.assist_button.setChecked(active)
        detail = self.assist.message
        if self.direction_test and self.turn_trial.rows:
            def average(side):
                value=self.turn_trial.mean(side)
                return '—' if value is None else f'{value:.1f}º'.replace('.',',')
            detail += f' | {self.turn_trial.summary()} | Esq. {average("esquerda")} | Dir. {average("direita")}'
            self.assist_info.setToolTip(str(self.turn_trial.path or ''))
        if active and not self.direction_test:
            speed = '—' if self.assist.speed is None else f'{self.assist.speed:.1f}'.replace('.',',')
            limit = f'{self.assist.speed_limit:.1f}'.replace('.',',')
            detail += f' | Vel. estimada: {speed} m/s | Limite: {limit} m/s | Comandos enviados: {self.steering_input.sent_pulses}'
        self.assist_info.setText(detail if self.steering_input.keys else self.steering_input.message)
        notice = ''
        if active:
            notice = 'Volta ao jogo para ativar' if self.assist_pending else (self.assist.message if self.direction_test else self.assist.overlay_text())
        self.overlay.set_assistance_notice(notice)

    def direction_test_active(self):
        return self.direction_test and (self.assist.enabled or bool(self.assist_pending))

    def observe_steering(self):
        """Chamado só após aceitar telemetria; amostras iguais são descartadas pelo núcleo."""
        s = self.state
        context = (id(s),s.body_key,s.map_generation)
        if context != self.assist_context:
            self.pause_assistance('Aguarda posição no mapa')
            self.assist.reset_samples()
            self.assist_context = context
        if s.rhino_heading is not None:
            x,y = s.llxy(s.rhino_lat,s.rhino_lon)
            self.assist.observe(time.monotonic(),x,y,s.rhino_heading)
            motion=self.assist.motion
            self.turn_trial.observe(self.assist.sample,motion[2] if motion else None)
