"""Medição de guinadas: soma diferenças assinadas de rumo, atravessando 000º.

Mede a alteração observada entre o início e o fim da estabilização, incluindo
a resposta tardia do jogo. Não é uma medição instantânea do ângulo das rodas.
"""
import csv
import math
from datetime import datetime, timezone
from steering import angle_delta
from i18n import translate


class TurnTrial:
    def __init__(self, path=None):
        self.path = path
        self.rows = []
        self.current = None

    def begin(self, direction, now, sample):
        self.current = dict(direction=direction, started=now, baseline=None,
                            last=None, change=0., count=0, gap=False, speeds=[])
        if sample is not None and 0<=now-sample[0]<=2.5:
            self.current['baseline'] = sample[3]
            self.current['last'] = (sample[0], sample[3])

    def observe(self, sample, speed=None):
        c = self.current
        if c is None or sample is None or c['last'] is None:
            return
        t,_,_,heading = sample
        previous_t,previous_heading = c['last']
        if t<=previous_t:
            return
        c['gap'] |= t-previous_t>2.5
        c['change'] += angle_delta(previous_heading,heading)
        c['last'] = (t,heading)
        c['count'] += 1
        if speed is not None and math.isfinite(speed):
            c['speeds'].append(speed)

    def finish(self, now, complete=True):
        c,self.current = self.current,None
        if c is None:
            return
        valid = bool(complete and c['last'] and c['count'] and not c['gap']
                     and c['last'][0]>=c['started']+2.5 and now-c['last'][0]<=2.5)
        row = dict(utc=datetime.now(timezone.utc).isoformat(),
                   sentido='esquerda' if c['direction']<0 else 'direita',
                   duracao_comando_s=2, rumo_inicial=c['baseline'],
                   rumo_final=c['last'][1] if c['last'] else None,
                   alteracao_assinada_graus=round(c['change'],2),
                   alteracao_absoluta_graus=round(abs(c['change']),2),
                   velocidade_media_estimada_ms=round(sum(c['speeds'])/len(c['speeds']),2) if c['speeds'] else None,
                   amostras=c['count'], valida=valid,
                   motivo='' if valid else ('interrompida' if not complete else 'telemetria insuficiente'))
        self.rows.append(row)
        if self.path:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            header=not self.path.exists()
            with self.path.open('a',encoding='utf-8-sig',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=row.keys(),delimiter=';')
                if header:
                    writer.writeheader()
                writer.writerow(row)

    def mean(self, direction=None):
        values=[r['alteracao_absoluta_graus'] for r in self.rows
                if r['valida'] and (direction is None or r['sentido']==direction)]
        return sum(values)/len(values) if values else None

    def summary(self):
        value=self.mean()
        count=sum(r['valida'] for r in self.rows)
        if value is None:
            return translate('TurnTrial', 'No turns measured')
        summary = translate('TurnTrial', 'Average {value:.1f}º · {count} turns').format(
            value=value, count=count)
        return summary.replace('.', ',')
