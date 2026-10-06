#!/usr/bin/env python3
"""Standalone offline comparison of the two accelerator channels and vision replay."""

import argparse
import csv
import gzip
import json
from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots


def rows(path):
  with gzip.open(path, 'rt') as f:
    return list(csv.DictReader(f))


def main():
  p = argparse.ArgumentParser(description=__doc__)
  p.add_argument('--archive', type=Path, required=True)
  args = p.parse_args()
  fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.09,
                      subplot_titles=('Deux valeurs distinctes : pédale et demande moteur',
                                      'Régulateur d’origine actif', 'Suivi vision : calcul hors ligne'))
  labels = []
  ntraces = 7
  summaries = []
  for index, directory in enumerate(sorted((args.archive / 'validation-lateral-rvv').glob('0000*'))):
    trace = rows(directory / 'trace.csv.gz')
    vision = rows(directory / 'vision-following.csv.gz')
    report = json.loads((directory / 'report.json').read_text())
    vision_report = json.loads((directory / 'vision-report.json').read_text())
    counts = report['counts']['pedal_during_rvv']
    labels.append(f'Trajet {index + 1}')
    summaries.append(f'Trajet {index + 1} — sous RVV : demande moteur non nulle '
                     f'{100 * counts["engine_demand_nonzero"] / counts["batches"]:.1f} %, '
                     f'pédale conducteur non nulle {100 * counts["driver_pedal_nonzero"] / counts["batches"]:.1f} %.')
    x = [float(r['seconds']) / 60 for r in trace]
    for key, name, color, row in [
      ('pedal_pct', 'Pédale conducteur · 0x228', '#2563eb', 1),
      ('engine_accelerator_demand_pct', 'Demande moteur · 0x208', '#f97316', 1),
      ('rvv_active', 'RVV actif', '#059669', 2),
    ]:
      y = [int(r[key] == 'True') if key == 'rvv_active' else float(r[key]) if r[key] else None for r in trace]
      fig.add_trace(go.Scatter(x=x, y=y, name=name, line={'color': color}, visible=index == 0,
                              hovertemplate='%{x:.2f} min · %{y}<extra>%{fullData.name}</extra>'), row=row, col=1)
    # qlog and full CAN have different first timestamps. Align on the original
    # monotonic timestamps; never silently assume equal route starts.
    offset = (vision_report['first_log_mono_time'] - int(trace[0]['logMonoTime'])) / 1e9
    vx = []; columns = {key: [] for key in ('speed_kph', 'stock_setpoint_kph', 'target_kph', 'intervention')}
    last = None
    for r in vision:
      seconds = float(r['seconds']) + offset
      if last is not None and seconds - last > 1:
        vx.append(None)
        for col in columns.values(): col.append(None)
      last = seconds
      vx.append(seconds / 60)
      for key in ('speed_kph', 'stock_setpoint_kph', 'target_kph'):
        columns[key].append(float(r[key]) if r[key] and r['eligible_stock_rvv'] == 'True' else None)
      columns['intervention'].append(float(r['speed_kph']) if r['driver_intervention'] == 'True' and r['eligible_stock_rvv'] == 'True' else None)
    for key, name, color in [('speed_kph', 'Vitesse voiture', '#475569'),
                              ('stock_setpoint_kph', 'Consigne conducteur', '#a855f7'),
                              ('target_kph', 'Cible vision calculée', '#059669'),
                              ('intervention', 'Intervention conducteur requise par le calcul', '#dc2626')]:
      fig.add_trace(go.Scatter(x=vx, y=columns[key], name=name, line={'color': color},
                              mode='markers' if key == 'intervention' else 'lines',
                              marker={'size': 5}, visible=index == 0, connectgaps=False), row=3, col=1)
  buttons = [dict(label=label, method='update', args=[{'visible': [j // ntraces == i for j in range(len(fig.data))]}])
             for i, label in enumerate(labels)]
  fig.update_layout(template='plotly_white', height=1050, margin={'t': 165},
                    title={'text': '308 T9 · pédale conducteur et suivi vision', 'x': 0.06, 'y': 0.98},
                    legend={'orientation': 'h', 'y': -0.08},
                    updatemenus=[dict(buttons=buttons, x=0, xanchor='left', y=1.10, direction='right', type='buttons')])
  fig.update_yaxes(title_text='%', row=1, col=1)
  fig.update_yaxes(tickvals=[0, 1], ticktext=['Inactif', 'Actif'], row=2, col=1)
  fig.update_yaxes(title_text='km/h', row=3, col=1)
  fig.update_xaxes(title_text='Minutes depuis le début CAN du trajet', row=3, col=1)
  html = fig.to_html(full_html=True, include_plotlyjs=True)
  intro = ('<main style="font:16px system-ui;max-width:1100px;margin:24px auto"><h1>Accélérateur : la distinction confirmée</h1>'
           + ''.join(f'<p>{s}</p>' for s in summaries)
           + '<p>Les courbes de suivi sont des propositions calculées sur les logs. Aucune commande n’a été envoyée. '
           'Le plafond vient de la consigne conducteur : les panneaux CVM ne sont pas encore identifiés. '
           'Le RVV ne commande pas le frein de service ; les points rouges signalent une limite du suivi par consigne seule.</p></main>')
  html = html.replace('<body>', '<body>' + intro, 1)
  output = args.archive / 'validation-pedale-suivi.html'
  output.write_text(html)
  print(output)


if __name__ == '__main__':
  main()
