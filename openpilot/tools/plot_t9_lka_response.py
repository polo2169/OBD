#!/usr/bin/env python3
"""Standalone offline charts of measured factory commands and steering response."""
import argparse
import csv
import html
import json
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('analysis', type=Path)
  args = parser.parse_args()
  report = json.loads((args.analysis / 'report.json').read_text())
  fragments = []
  for route_index, meta in enumerate(report['routes']):
    route = meta['route']
    with (args.analysis / (route + '.csv')).open() as f:
      rows = list(csv.DictReader(f))
    data = {key: np.asarray([float(r[key]) if r[key] not in ('True', 'False') else r[key] == 'True'
                            for r in rows]) for key in rows[0]}
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=.055,
                        subplot_titles=('Commande usine et effort conducteur', 'Réponse mesurée et modèle',
                                        'Angle et vitesse du volant', 'Facteur LKA et acquittement EPS'),
                        specs=[[{}], [{}], [{'secondary_y': True}], [{'secondary_y': True}]])
    subset = np.arange(0, len(rows), 4)  # Display at 5 Hz; model fitting remains 20 Hz.
    t = data['t'][subset]
    def add(name, y, row, color, secondary=None):
      kwargs = {'secondary_y': secondary} if secondary is not None else {}
      fig.add_trace(go.Scatter(x=t, y=y[subset], name=name, mode='lines',
                              line={'color': color, 'width': 1.5}), row=row, col=1, **kwargs)
    add('Couple usine brut', data['torque'], 1, '#2563eb')
    add('Effort conducteur brut', data['driver'], 1, '#a855f7')
    add('Vitesse × lacet CAN', data['can_lat'], 2, '#16a34a')
    add('Vitesse × lacet comma (signe aligné)', data['pose_lat'], 2, '#0891b2')
    x = np.c_[np.ones(len(rows)), np.roll(data['torque'], 3), np.roll(data['driver'], 3),
              np.clip(data['rate'], -1, 1)]
    coef = report['fits']['can_lat']['routes'][route_index]['signed_rate_model']['coefficients']
    prediction = x @ coef
    model_selected = ((data['selected'] == 1) & (np.roll(data['episode'], 3) == data['episode'])
                      & (np.roll(data['factor'], 3) == 100) & (np.abs(np.roll(data['driver'], 3)) <= 5))
    prediction[~model_selected] = np.nan
    add('Modèle à 150 ms, points retenus', prediction, 2, '#dc2626')
    add('Angle volant (°)', data['angle'], 3, '#2563eb', False)
    add('Vitesse volant (°/s)', data['rate'], 3, '#ea580c', True)
    add('Facteur brut', data['factor'], 4, '#64748b', False)
    add('État EPS', data['eps'], 4, '#16a34a', True)
    for episode in meta['episodes']:
      if episode['duration_s'] >= 2:
        fig.add_vrect(x0=episode['start_s'], x1=episode['start_s']+episode['duration_s'],
                      fillcolor='#86efac', opacity=.13, line_width=0, row='all', col=1)
    initial = [meta['episodes'][0]['start_s'] - 5, meta['episodes'][-1]['start_s'] + 10]
    fig.update_xaxes(range=initial, title_text='Secondes depuis la première trame CAN', row=4, col=1)
    fig.update_yaxes(title_text='raw', row=1, col=1)
    fig.update_yaxes(title_text='m/s²', row=2, col=1)
    fig.update_yaxes(title_text='°', row=3, col=1, secondary_y=False)
    fig.update_yaxes(title_text='°/s', row=3, col=1, secondary_y=True)
    fig.update_layout(height=920, template='plotly_white', hovermode='x unified',
                      legend={'orientation': 'h', 'y': 1.16}, margin={'t': 145})
    graph_id = f'route-{route_index}'
    def response_ranges(start, end):
      mask = (data['t'] >= start) & (data['t'] <= end)
      result = {}
      groups = [('yaxis', [data['torque'], data['driver']], 1.),
                ('yaxis2', [data['can_lat'], data['pose_lat'], prediction], .05),
                ('yaxis3', [data['angle']], .5), ('yaxis4', [data['rate']], .5)]
      for axis, values, minimum_pad in groups:
        values = np.concatenate([v[mask] for v in values]); values = values[np.isfinite(values)]
        lo, hi = values.min(), values.max(); pad = max(minimum_pad, float(hi-lo)*.12)
        result[axis + '.range'] = [float(lo-pad), float(hi+pad)]
        result[axis + '.autorange'] = False
      return result
    # Avoid flattening the small LKA movements with full-route parking angles.
    for key, value in response_ranges(*initial).items():
      axis, field = key.split('.')
      fig.layout[axis][field] = value
    chart = fig.to_html(full_html=False, include_plotlyjs=route_index == 0, div_id=graph_id)
    episodes = []
    for e in meta['episodes']:
      start, duration = e['start_s'], e['duration_s']
      zoom = json.dumps({f'xaxis{k if k > 1 else ""}.range': [start-2, start+duration+2] for k in range(1, 5)}
                        | response_ranges(start-2, start+duration+2))
      onclick = html.escape(f'Plotly.relayout("{graph_id}", {zoom}); document.getElementById("{graph_id}").scrollIntoView();', quote=True)
      ack = e['eps_ack_delay_s']
      ack_label = 'déjà à 3' if ack == 0 else (f'{round(1000*ack)} ms' if ack is not None else '—')
      episodes.append(f'<tr><td><button onclick="{onclick}">{e["number"]}</button></td>'
        f'<td>{int(start)//60}:{start%60:04.1f}</td><td>{duration:.2f} s</td>'
        f'<td>{ack_label}</td>'
        f'<td>{e["torque_min_raw"]:g} à {e["torque_max_raw"]:g}</td>'
        f'<td>{e["retained_20hz_samples"]}</td></tr>')
    fragments.append(f'<section><h2>{html.escape(route)}</h2><p>{len(meta["episodes"])} activations ; '
      f'{meta["factory_active_s"]:.1f} s actives. Cliquer sur un numéro pour examiner la réaction.</p>{chart}'
      '<table><tr><th>Séquence</th><th>Début</th><th>Durée</th><th>Acquittement EPS</th><th>Couple raw</th><th>Points retenus</th></tr>'
      + ''.join(episodes) + '</table></section>')
  fit = report['fits']['can_lat']
  scatter = go.Figure()
  for i, meta in enumerate(report['routes']):
    data = np.genfromtxt(args.analysis / (meta['route']+'.csv'), delimiter=',', names=True, dtype=None, encoding='utf8')
    keep = data['selected'].astype(bool)
    index = np.flatnonzero(keep); source = index-3
    keep2 = (data['episode'][source] == data['episode'][index]) & (data['factor'][source] == 100) & (np.abs(data['driver'][source]) <= 5)
    index = index[keep2]; source = source[keep2]
    co = fit['routes'][i]['linear']['coefficients']
    scatter.add_trace(go.Scatter(x=data['torque'][source], y=data['can_lat'][index]-co[2]*data['driver'][source],
      mode='markers', name=f'Trajet {i+1}, effort conducteur corrigé', marker={'size': 4, 'opacity': .25}))
    u = np.array([-35, 35])
    scatter.add_trace(go.Scatter(x=u, y=co[0]+co[1]*u, name=f'Gain trajet {i+1} : {co[1]:.5f}', mode='lines'))
  scatter.update_layout(template='plotly_white', title='Commande usine et accélération CAN, retard de 150 ms',
                        xaxis_title='Couple brut 0x3F2 à facteur 100', yaxis_title='Accélération latérale corrigée (m/s²)', height=560)
  body = '''<!doctype html><html lang="fr"><meta charset="utf-8"><title>308 T9 — LKA usine mesuré</title>
<style>body{font:16px system-ui;color:#172033;margin:35px auto;max-width:1400px;padding:0 24px}section{margin:55px 0}p{line-height:1.6}table{border-collapse:collapse;width:100%}td,th{padding:9px;text-align:left;border-bottom:1px solid #ddd}button{cursor:pointer;padding:6px 16px}.card{padding:22px;background:#eef6ff;border-radius:12px}h1{font-size:30px}</style>
<h1>Peugeot 308 T9 — réponse réelle du LKA d’origine</h1>
<div class="card"><b>26 activations, 139,5 secondes LKA actives.</b> Gain candidat : 0,042 m/s²/raw ; délai apparent : 150 ms ; constante de réponse : 140 ms. Frottement candidat : 1,4 raw à ce délai.</div>
<p>Le CAN contient des commandes du calculateur d’origine et leur retour EPS. Le comma était en observation.
Les fonds verts indiquent les activations d’au moins deux secondes. Le modèle n’est tracé que sur les points retenus.
Le frottement estimé dépend du délai : il devient proche de zéro à 300 ms. Le facteur 100 est une condition du calcul, pas une consigne transmise.
Les données, les graphiques et Plotly sont embarqués : cette page fonctionne sans Internet.</p>'''
  (args.analysis / 'index.html').write_text(body + ''.join(fragments) + scatter.to_html(full_html=False, include_plotlyjs=False) + '</html>')
  print(args.analysis / 'index.html')


if __name__ == '__main__':
  main()
