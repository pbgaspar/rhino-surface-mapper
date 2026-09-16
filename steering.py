"""Decisões de assistência: não envia comandos nem controla o acelerador.

Os limites são de ensaio, não um modelo da dinâmica do veículo. Uma decisão
consome uma amostra nova; a mesma posição/rumo nunca gera toques repetidos.
"""
import math


def angle_delta(a, b):
    """Diferença assinada de a para b, incluindo a passagem por norte."""
    return (b-a+180) % 360-180


class SteeringAssist:
    def __init__(self, max_speed=15.0, max_pulse=.8):
        self.tolerance = 3
        self.max_speed = max_speed
        self.max_pulse = max_pulse
        self.enabled = False
        self.message = 'Assistência desligada'
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
        self.wait_reason = 'Aguarda dados novos'

    def stop(self, reason='Assistência desligada'):
        self.enabled = False
        self.message = reason

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
        self.message = 'Assistência: aguarda dados novos'
        self.wait_reason = 'Aguarda dados novos'

    def wait(self, reason):
        self.wait_reason = reason
        self.message = 'Assistência: '+reason.lower()
        return None

    def overlay_text(self):
        """Distingue espera, abrandamento e correção, em vez de esconder a causa."""
        if self.message == 'Reduzir velocidade':
            if self.wait_reason == 'Rumo instável':
                return 'Reduzir velocidade · rumo instável'
            return f'Reduzir velocidade · até {self.speed_limit:.1f} m/s'.replace('.',',')
        if self.message.startswith('Assistência: correção'):
            return 'A corrigir à direita' if 'direita' in self.message else 'A corrigir à esquerda'
        if self.message == 'Assistência: no rumo':
            return 'Assistência: no rumo'
        if self.message == 'Assistência: a aliviar direção':
            return 'A aliviar direção'
        return self.wait_reason

    def decide(self, now, target):
        """Devolve (sentido, segundos) ou None. +1=direita; -1=esquerda."""
        if not self.enabled:
            return None
        if self.sample is None or now-self.sample[0] > 2.5:
            return self.wait('Aguarda telemetria nova')
        if now < self.command_end:
            return None
        if now < self.wait_until or self.sample[0] < self.wait_until:
            return self.wait('Aguarda resposta da direção')
        if self.sample is self.consumed:
            return None
        self.consumed = self.sample
        if self.previous is None:
            return self.wait('Aguarda segunda amostra')
        t, x, y, heading = self.sample
        pt, px, py, ph = self.previous
        dt = t-pt
        if dt < .25 or dt > 30:
            return self.wait('Aguarda amostras regulares')
        if self.motion is None:
            return self.wait('Aguarda nova posição')
        mt,position_dt,speed,travel,distance = self.motion
        self.speed, self.interval = speed, position_dt
        if position_dt>30 or now-mt>2.5:
            return self.wait('Aguarda nova posição')
        rate = angle_delta(ph, heading)/dt
        bearing = math.degrees(math.atan2(target[0]-x, target[1]-y)) % 360
        error = angle_delta(heading, bearing)
        self.error_degrees = error
        self.speed_limit = self.max_speed
        if speed > self.speed_limit:
            self.wait_reason = 'Velocidade acima do limite'
            self.message = 'Reduzir velocidade'
            return None
        if abs(rate)>20 or distance>100:
            return self.wait('Aguarda estabilidade do rumo/posição')
        if speed < .3:
            return self.wait('Aguarda movimento')
        if abs(angle_delta(heading,travel))>60:
            return self.wait('Aguarda marcha à frente estável')
        # Aliviar antes de cruzar o rumo, usando uma previsão curta e limitada.
        predicted = error-rate*min(dt, .5)
        if abs(error)<=self.tolerance or predicted*error<=0 or abs(predicted)<=self.tolerance:
            self.message = 'Assistência: no rumo' if abs(error)<=self.tolerance else 'Assistência: a aliviar direção'
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
        self.message = 'Assistência: correção à direita' if error>0 else 'Assistência: correção à esquerda'
        return (1 if error>0 else -1), duration
