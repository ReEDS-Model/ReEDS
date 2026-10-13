"""Gas-CC start cost sensitivity: value factor, cost factor and value-cost factor against market
share for the UPV and battery forcing runs with gas-CC start costs on (GSw_StartCost=4, the core
runs) and off (GSw_StartCost=3, the upv_sc3 and battery_sc3 columns of cases_valcostfac.csv), as
points joined by lines with no fits.

Reads the valcostfac.csv written by postprocessing/bokehpivot/run_report_valcostfac.py, run on
scenarios_sc3.csv (upv, upv_sc3, battery and battery_sc3); both are kept in comparison_dir, and the
figure is written there too.

Usage:
    python valcostfac_startcost_comparison.py
"""
import os
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

comparison_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'bokehpivot', 'out',
                              'startcost_comparison')
valcostfac_path = os.path.join(comparison_dir, 'valcostfac.csv')
output_path = os.path.join(comparison_dir, 'startcost_comparison.png')

#(tech in valcostfac.csv, core scenario name), one row of panels each
rows = [('UPV', 'upv'), ('Battery', 'battery')]
panels = [('value_factor', 'Value factor'), ('cost_factor', 'Cost factor'),
          ('value_cost_factor', 'Value-cost factor')]
start_year = 2026


#(scenario suffix, legend label) for the start-cost-on core run and the start-cost-off sensitivity
series = [('', 'Gas-CC start costs on (GSw_StartCost=4)', '#2A6F8E', 'o', '-'),
          ('_sc3', 'Gas-CC start costs off (GSw_StartCost=3)', '#C0392B', 's', '--')]


def plot():
    df = pd.read_csv(valcostfac_path)
    df = df[df['year'] >= start_year]
    fig, axes = plt.subplots(len(rows), len(panels), figsize=(13.5, 3.8 * len(rows)), squeeze=False)
    for (tech, base), axrow in zip(rows, axes):
        for ax, (col, title) in zip(axrow, panels):
            for suf, lab, color, marker, ls in series:
                d = df[(df['tech'] == tech) & (df['scenario'] == base + suf)].sort_values('gen_frac')
                ax.plot(d['gen_frac'] * 100, d[col], color=color, ls=ls, lw=1.6, marker=marker,
                        ms=4, mec='white', mew=0.5, label=lab)
            ax.set_title(f'{tech}: {title}', fontsize=10, loc='left')
            ax.set_xlabel('Market share (% of generation)')
            ax.set_xlim(left=0)
            ax.set_ylim(bottom=0)
            ax.grid(alpha=0.25, lw=0.6)
            ax.axhline(1.0, color='0.35', lw=0.8, ls=':', zorder=0)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='lower center', ncol=2, fontsize=9, frameon=False)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(output_path, dpi=200)


if __name__ == '__main__':
    plot()
    print(f'Wrote {os.path.normpath(output_path)}')
