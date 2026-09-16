"""Pulso de radar independente do desenho e dos dispositivos de entrada."""
class RadarPulse:
    SPEED_M_S = 2000.0 / 3.0
    def __init__(self):
        self.waves = []
        self.was_down = True  # exige libertar o botão após entrar no contexto
        self.context = None
        self.armed = False

    @property
    def active(self):
        return self.waves[-1] if self.waves else None

    def tick(self, state, now, enabled, down, context):
        if getattr(state, 'read_only', False):
            changed = bool(self.waves)
            self.waves = []
            self.armed = False
            self.was_down = True
            return changed
        changed = False
        if self.context != context:
            self.context = context
            self.was_down = True
            self.armed = False
            self.waves = []
        finished = False
        latest = self.active
        remaining = []
        for wave in self.waves:
            pulse, start, limit = wave
            pulse['radius'] = min(limit, max(0, (now-start)*self.SPEED_M_S))
            if now-start >= limit/self.SPEED_M_S - 1e-9:
                pulse['radius'] = limit
            changed = True
            if pulse['radius'] >= limit:
                finished = finished or wave is latest
            else:
                remaining.append(wave)
        self.waves = remaining
        if not enabled:
            # None significa que o jogo não tem foco: não inferir uma libertação.
            # Com foco, observar a libertação mesmo enquanto chega a telemetria.
            self.was_down = down is not False
            self.armed = down is False
            return changed
        if not down:
            self.armed = True
        if self.active is None and self.armed and down and (not self.was_down or finished):
            x, y = state.llxy(state.rhino_lat, state.rhino_lon)
            pulse = dict(x=x, y=y, radius=0.0)
            state.radar_coverage.append(pulse)
            self.waves.append((pulse, now, state.scanner_range_m))
            changed = True
        self.was_down = down
        return changed
