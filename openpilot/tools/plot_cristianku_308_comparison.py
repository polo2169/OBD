#!/usr/bin/env python3
"""Summarize offline replay outputs and create a standalone comparison plot."""
import argparse
import csv
import gzip
import json
from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots


def load_trace(path):
  with gzip.open(path, 'rt') as f:
    return list(csv.DictReader(f))


def changed_points(rows, field, cast=float):
  points = []
  last = None
  for i, row in enumerate(rows):
    value = cast(row[field])
    if value != last or i == len(rows)-1:
      points.append((float(row['t_s']), value))
      last = value
  return points


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('results', type=Path)
  args = parser.parse_args()
  out = args.results
  ours = load_trace(out/'installed-PSA_PEUGEOT_308_T9-long.csv.gz')
  theirs = load_trace(out/'reference-PSA_PEUGEOT_3008-long.csv.gz')
  mapped = load_trace(out/'reference-PSA_PEUGEOT_3008-long-adapt-observed-buses.csv.gz')
  assert len(ours) == len(theirs) == len(mapped)
  assert all(a['ns'] == b['ns'] == c['ns'] for a,b,c in zip(ours,theirs,mapped,strict=True))
  safety = json.loads((out/'safety-long-param0.json').read_text())
  differences = {}
  for variant, rows in [('original', theirs), ('bus_mapping_only', mapped)]:
    diffs = {}
    for field in ('vEgoRawKph','steeringAngleDeg','steeringRateDeg','steeringTorque','gasPressed',
                  'brakePressed','leftBlinker','rightBlinker','gearShifter','cruiseEnabled'):
      n = 0
      for a, b in zip(ours, rows, strict=True):
        if float(a['t_s']) < 2:
          continue
        try:
          mismatch = abs(float(a[field])-float(b[field])) > 1e-4
        except ValueError:
          mismatch = a[field] != b[field]
        n += mismatch
      diffs[field] = n
    differences[variant] = diffs

  # Identify contiguous engine-state 4/5 intervals and C-hook low pulses inside.
  periods = []
  start = None
  for row in ours:
    is_stop = row['engine_state'] in ('4','5')
    if is_stop and start is None:
      start = float(row['t_s'])
    elif not is_stop and start is not None:
      periods.append((start, float(row['t_s'])))
      start = None
  affected = []
  for lo, hi in periods:
    pulses = [e for e in safety['ignition_edges'] if lo <= e['t_s'] < hi and not e['value']]
    if pulses:
      affected.append({'start_s': lo, 'end_s': hi, 'low_pulses': len(pulses), 'first_pulse': pulses[0]})
  summary = {'long_samples': len(ours), 'differences_after_2s': differences,
             'engine_state_4_5_periods': periods, 'periods_with_ignition_low_edge': affected,
             'interpretation': 'Reference outputs are observed despite canValid=false; not valid vehicle estimates. '
                               'Ignition is the raw C hook, not the complete device startup state machine.'}
  (out/'comparison-summary.json').write_text(json.dumps(summary,indent=2)+'\n')

  fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.065,
                      subplot_titles=['Contact : T15 reçu et fonction C de cristianku',
                                      'État moteur reçu (4/5 : Stop & Start)',
                                      'Frein décodé — sorties cristianku invalides / canValid=false',
                                      'Régulateur actif — sorties cristianku invalides / canValid=false'])
  def line(points, name, row, color, dash=None):
    x,y=zip(*points)
    fig.add_trace(go.Scatter(x=list(x),y=list(y),name=name,mode='lines',
                            line=dict(color=color,shape='hv',width=2,dash=dash)),row=row,col=1)
  to_bool=lambda value: int(value == 'True')
  line(changed_points(ours,'t15',to_bool),'T15 reçu',1,'#10b981')
  edges=[(0,0)]+[(e['t_s'],int(e['value'])) for e in safety['ignition_edges']]
  edges.append((float(ours[-1]['t_s']),edges[-1][1]))
  line(edges,'Contact cristianku (fonction C)',1,'#ef4444','dot')
  line(changed_points(ours,'engine_state'),'État moteur brut',2,'#6366f1')
  line(changed_points(ours,'brakePressed',to_bool),'Frein — port 308',3,'#10b981')
  line(changed_points(theirs,'brakePressed',to_bool),'Frein — cristianku original',3,'#ef4444','dot')
  line(changed_points(mapped,'brakePressed',to_bool),'Frein — bus adaptés virtuellement',3,'#f59e0b','dash')
  line(changed_points(ours,'cruiseEnabled',to_bool),'RVV — port 308',4,'#10b981')
  line(changed_points(theirs,'cruiseEnabled',to_bool),'RVV — cristianku',4,'#ef4444','dot')
  stop_zoom=affected[0] if affected else {'start_s':150,'end_s':180}
  ranges=[('Trajet entier',[0,float(ours[-1]['t_s'])]),('Démarrages',[8,39]),
          ('Stop & Start',[max(0,stop_zoom['start_s']-2),stop_zoom['end_s']+2])]
  fig.update_layout(template='plotly_white',height=1100,
                    title=dict(text='308 T9 — comparaison hors ligne, branche cristianku a4a565a<br><sup>Aucune commande envoyée. Temps relatif au premier lot CAN ; aucune heure civile déduite.</sup>',
                               x=0.05,y=0.995,xanchor='left',yanchor='top'),
                    legend=dict(orientation='h',y=-0.12),margin=dict(b=180,t=155),
                    updatemenus=[dict(type='buttons',direction='right',x=0,y=1.11,
                                     buttons=[dict(label=label,method='relayout',args=[{f'xaxis{n if n>1 else ""}.range':r for n in range(1,5)}])
                                              for label,r in ranges])])
  for row in (1,3,4):
    fig.update_yaxes(tickvals=[0,1],range=[-0.15,1.15],row=row,col=1)
  fig.update_xaxes(title_text='Secondes depuis le premier lot CAN conservé',row=4,col=1)
  fig.write_html(out/'comparaison-interactive.html',include_plotlyjs=True,full_html=True)
  print(json.dumps(summary,indent=2))


if __name__ == '__main__':
  main()
