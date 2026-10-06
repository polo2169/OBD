#!/usr/bin/env python3
"""Plot offline driver-effort audit windows; requires matplotlib."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    report = json.loads(args.report.read_text())
    cuts = [(Path(s['source']).parent.name, cut)
            for s in report['segments'] for cut in s['driver_cuts']]
    if not cuts:
        parser.error('No recorded driver-effort cuts to plot')
    fig, axes = plt.subplots(2, len(cuts), figsize=(6 * len(cuts), 6), sharex='col', squeeze=False)
    for column, (name, cut) in enumerate(cuts):
        top, bottom = axes[:, column]
        now = cut['ns']
        driver = cut['window_driver_samples']
        eps = cut['window_eps_samples']
        top.plot([(r['ns'] - now) / 1e6 for r in driver],
                 [r['driver_raw'] if r['valid'] else float('nan') for r in driver],
                 '.-', color='#176b9d', markersize=3, label='Effort CAN0 reçu')
        limit = report['driver_limit_raw_observed_in_current_port']
        top.axhline(limit, color='#b35400', linestyle='--', label='Seuil actuel ±5')
        top.axhline(-limit, color='#b35400', linestyle='--')
        top.set_title(f'{name}\nDécision à {now / 1e9:.3f} s')
        top.set_ylabel('Effort conducteur (raw)')
        top.legend(fontsize=8, loc='upper left')
        bottom.step([(r['ns'] - now) / 1e6 for r in eps],
                    [r['state'] if r['valid'] else float('nan') for r in eps],
                    where='post', color='#5c427d', marker='.', label='État EPS reçu')
        bottom.set_yticks([0, 1, 2, 3, 4], ['Non autorisé', 'Autorisé', 'Disponible', 'Actif', 'Défaut'])
        bottom.set_ylim(-0.25, 4.25)
        bottom.set_xlabel('Temps relatif à la décision de coupure (ms)')
        bottom.legend(fontsize=8, loc='upper left')
        for axis in (top, bottom):
            axis.axvline(0, color='#222222', linewidth=1)
            axis.grid(alpha=0.2)
            axis.set_xlim(-500, 500)
    fig.suptitle('308 T9 — effort enregistré et retour physique de la direction')
    fig.text(0.5, 0.01, 'Intention conducteur non étiquetée. Un pic bref ne prouve pas un parasite.',
             ha='center', fontsize=9)
    fig.tight_layout(rect=[0, 0.04, 1, 0.96])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=170)
    plt.close(fig)


if __name__ == '__main__':
    main()
