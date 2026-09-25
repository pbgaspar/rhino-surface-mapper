"""Decisões de assistência: não envia comandos nem controla o acelerador.

Os limites são de ensaio, não um modelo da dinâmica do veículo. Uma decisão
consome uma amostra nova; a mesma posição/rumo nunca gera toques repetidos.
"""
import math
from i18n import translate


STATUS_STOPPED = 'stopped'
STATUS_WAITING = 'waiting'
STATUS_SLOWING = 'slowing'
STATUS_CORRECTING = 'correcting'
STATUS_ON_COURSE = 'on_course'
STATUS_EASING = 'easing'
WAIT_UNSTABLE_HEADING = 'unstable_heading'


def angle_delta(a, b):
    """Diferença assinada de a para b, incluindo a passagem por norte."""
    return (b-a+180) % 360-180


class SteeringAssist:
    def __init__(self, max_speed=15.0, max_pulse=.8):
        self.tolerance = 3
        self.max_speed = max_speed
        self.max_pulse = max_pulse
        self.enabled = False
        self.status = STATUS_STOPPED
        self.wait_code = None
        self.correction_direction = 0
        self.message = translate('SteeringAssist', 'Assistance off')
        self.previous = None
        self.sample = None
        self.consumed = None
        self.wait_until = 0
        self.command_end = 0
        self.position = None
        self.motion = None
        self.speed = None
        self.speed_limit = max_speed
        self.error_degrees = None
        self.interval = None
        self.wait_reason = translate('SteeringAssist', 'Waiting for fresh data')

    def stop(self, reason=None):
        self.enabled = False
        self.status = STATUS_STOPPED
        self.wait_code = None
        self.correction_direction = 0
        self.message = reason if reason is not None else translate('SteeringAssist', 'Assistance off')

    def reset_samples(self):
        self.previous = self.sample = self.consumed = None
        self.position = self.motion = self.speed = self.interval = None
        self.error_degrees = None
        self.wait_until = 0
        self.command_end = 0

    def observe(self, now, x, y, heading):
        """Guarda apenas mudanças reais; estima velocidade no plano do mapa."""
        if not all(math.isfinite(v) for v in (now, x, y, heading)):
            self.reset_samples()
            return
        sample = (now, x, y, heading)
        # Rumo e posição podem chegar em atualizações diferentes. Uma mudança
        # só de rumo não reinicia o relógio usado para estimar a velocidade.
        if self.position is None:
            self.position = (now,x,y)
        elif (x,y) != self.position[1:]:
            pt,px,py = self.position
            dt = now-pt
            if dt>0:
                distance = math.hypot(x-px,y-py)
                self.motion = (now,dt,distance/dt,
                               math.degrees(math.atan2(x-px,y-py)) % 360,distance)
            self.position = (now,x,y)
        if self.sample is not None and sample[1:] == self.sample[1:]:
            return
        self.previous, self.sample = self.sample, sample

    def start(self):
        self.enabled = True
        self.wait_until = self.command_end = 0
        self.consumed = self.sample  # aguardar informação posterior à ativação
        self.message = translate('SteeringAssist', 'Assistance: waiting for fresh data')
        self.wait_reason = translate('SteeringAssist', 'Waiting for fresh data')
        self.status = STATUS_WAITING
        self.wait_code = None
        self.correction_direction = 0

    def wait(self, reason, wait_code=None):
        self.wait_reason = translate('SteeringAssist', reason)
        self.wait_code = wait_code
        self.status = STATUS_WAITING
        self.correction_direction = 0
        self.message = translate('SteeringAssist', 'Assistance: {reason}').format(
            reason=self.wait_reason.lower())
        return None

    def overlay_text(self):
        """Distingue espera, abrandamento e correção, em vez de esconder a causa."""
        if self.status == STATUS_SLOWING:
            if self.wait_code == WAIT_UNSTABLE_HEADING:
                return translate('SteeringAssist', 'Reduce speed · unstable heading')
            return translate('SteeringAssist', 'Reduce speed · up to {speed:.1f} m/s').format(
                speed=self.speed_limit)
        if self.status == STATUS_CORRECTING:
            return translate('SteeringAssist', 'Correcting right' if self.correction_direction > 0 else 'Correcting left')
        if self.status == STATUS_ON_COURSE:
            return translate('SteeringAssist', 'Assistance: on course')
        if self.status == STATUS_EASING:
            return translate('SteeringAssist', 'Easing steering')
        return self.wait_reason

    def decide(self, now, target):
        """Devolve (sentido, segundos) ou None. +1=direita; -1=esquerda."""
        if not self.enabled:
            return None
        if self.sample is None or now-self.sample[0] > 2.5:
            return self.wait('Waiting for fresh telemetry')
        if now < self.command_end:
            return None
        if now < self.wait_until or self.sample[0] < self.wait_until:
            return self.wait('Waiting for steering response')
        if self.sample is self.consumed:
            return None
        self.consumed = self.sample
        if self.previous is None:
            return self.wait('Waiting for a second sample')
        t, x, y, heading = self.sample
        pt, px, py, ph = self.previous
        dt = t-pt
        if dt < .25 or dt > 30:
            return self.wait('Waiting for regular samples')
        if self.motion is None:
            return self.wait('Waiting for a new position')
        mt,position_dt,speed,travel,distance = self.motion
        self.speed, self.interval = speed, position_dt
        if position_dt>30 or now-mt>2.5:
            return self.wait('Waiting for a new position')
        rate = angle_delta(ph, heading)/dt
        bearing = math.degrees(math.atan2(target[0]-x, target[1]-y)) % 360
        error = angle_delta(heading, bearing)
        self.error_degrees = error
        self.speed_limit = self.max_speed
        if speed > self.speed_limit:
            self.wait_reason = translate('SteeringAssist', 'Speed above the limit')
            self.wait_code = None
            self.status = STATUS_SLOWING
            self.correction_direction = 0
            self.message = translate('SteeringAssist', 'Reduce speed')
            return None
        if abs(rate)>20 or distance>100:
            return self.wait('Waiting for heading/position stability', WAIT_UNSTABLE_HEADING)
        if speed < .3:
            return self.wait('Waiting for movement')
        if abs(angle_delta(heading,travel))>60:
            return self.wait('Waiting for steady forward motion')
        # Aliviar antes de cruzar o rumo, usando uma previsão curta e limitada.
        predicted = error-rate*min(dt, .5)
        if abs(error)<=self.tolerance or predicted*error<=0 or abs(predicted)<=self.tolerance:
            self.status = STATUS_ON_COURSE if abs(error)<=self.tolerance else STATUS_EASING
            self.wait_code = None
            self.correction_direction = 0
            self.message = translate(
                'SteeringAssist',
                'Assistance: on course' if self.status == STATUS_ON_COURSE else 'Easing steering')
            return None
        # A velocidade reduz a duração do toque, sem impor um limite oculto
        # de marcha lenta para curvas grandes. Mantém-se uma correção por amostra.
        # Referência empírica aproximada: 93º em 2 s, perto de 10 m/s.
        # Não assumir proporcionalidade exata: aplicar 70% da estimativa,
        # limitar cada toque e observar a resposta antes do seguinte.
        base_duration = min(self.max_pulse, abs(predicted)/46.5*.7)
        duration = max(.08, base_duration/(1+max(0,speed-10)/20))
        # Escalões aplicados ao desvio atual, após o cálculo da duração base.
        deviation = abs(error)
        factor = 1 if deviation <= 30 else 1.5 if deviation <= 90 else 2 if deviation <= 120 else 3
        duration *= factor
        self.command_end = now+duration
        self.wait_until = self.command_end+.25
        self.status = STATUS_CORRECTING
        self.wait_code = None
        self.correction_direction = 1 if error > 0 else -1
        self.message = translate(
            'SteeringAssist',
            'Assistance: correcting right' if self.correction_direction > 0 else
            'Assistance: correcting left')
        return (1 if error>0 else -1), duration
