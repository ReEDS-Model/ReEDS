"""
Compare flat-generator (e.g. geothermal) LVOE by service across two or more ReEDS runs for one
solve year, one panel per region:
    lvoe_{tech}-{year}-{profile}-{name}.png: stacked bars by service, one bar per run
    lvoe_{tech}-{year}-{profile}-{name}.csv: the same values in $/MWh, with a Total column
    lvoe_{tech}-all_runs-{name}.csv:         every year, region, profile, and service for each run
Reads runs/{case}/outputs/converge/lvoe_{tech}.csv, so run geothermal_lvoe.py on each case first.

Usage:
    python postprocessing/converge/compare_lvoe.py runs/{case1} runs/{case2} [...]
        [--labels "default,highgas"] [--regions CO_E,CO_W] [--year 2050]
Outputs are written to runs/{case1}/outputs/converge/compare/ unless --outpath is given.
"""
#%% Imports
import os
import sys
import argparse
import pandas as pd
import matplotlib.pyplot as plt
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from geothermal_lvoe import DEFAULT_DOLLAR_YEAR

SERVICES = ['Energy', 'Reserve margin', 'State RPS/CES', 'National CES']
COLORS = {'Energy': 'C0', 'Reserve margin': 'C3', 'State RPS/CES': 'C2', 'National CES': 'C4'}


#%% Functions
def get_lvoe(cases, labels, tech='geothermal'):
    """Concatenated lvoe_{tech}.csv from each run, with a 'run' column"""
    dfs = []
    for label, case in zip(labels, cases):
        fpath = os.path.join(case, 'outputs', 'converge', f'lvoe_{tech}.csv')
        if not os.path.exists(fpath):
            raise FileNotFoundError(f'{fpath} not found; run geothermal_lvoe.py on {case} first')
        dfs.append(pd.read_csv(fpath).assign(run=label))
    return pd.concat(dfs, ignore_index=True)


def get_table(lvoe, labels, regions, year, profile):
    """$/MWh by service with index = (r, run) and a Total column"""
    df = lvoe.loc[(lvoe.t == year) & (lvoe.profile == profile) & lvoe.r.isin(regions)]
    table = df.pivot_table(index=['r', 'run'], columns='service', values='usd_per_mwh', aggfunc='sum')
    table = table[[s for s in SERVICES if s in table.columns]]
    table['Total'] = table.sum(axis=1)
    return table.reindex(pd.MultiIndex.from_product([regions, labels], names=['r', 'run']))


def plot_bars(table, regions, unit, title, savepath):
    fig, axes = plt.subplots(
        1, len(regions), figsize=(3.6 * len(regions), 5.0), sharey=True, squeeze=False,
        layout='constrained',
    )
    axes = axes[0]
    services = [s for s in SERVICES if s in table.columns]
    for ax, r in zip(axes, regions):
        sub = table.loc[r]
        bottom = pd.Series(0.0, index=sub.index)
        for s in services:
            ax.bar(sub.index, sub[s].fillna(0), bottom=bottom, color=COLORS[s], label=s)
            bottom += sub[s].fillna(0)
        for x, v in enumerate(sub['Total']):
            ax.text(x, v + 0.8, f'{v:.0f}', ha='center', fontsize=9)
        ax.set_title(r, fontsize=12)
        ax.tick_params(axis='x', labelrotation=90, labelsize=9)
        ax.grid(axis='y', alpha=0.3)
    axes[0].set_ylim(0, table['Total'].max() * 1.1)
    axes[0].set_ylabel(unit, fontsize=11)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='outside lower center', ncols=len(labels), fontsize=10)
    fig.suptitle(title, fontsize=13)
    fig.savefig(savepath, dpi=110)
    plt.close(fig)


#%% Main
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Compare flat-generator LVOE by service across ReEDS runs',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('cases', type=str, nargs='+', help='paths to ReEDS run folders')
    parser.add_argument('--labels', '-l', type=str, default='',
                        help='comma-delimited bar labels (default: run folder names)')
    parser.add_argument('--regions', '-r', type=str, default='',
                        help='comma-delimited zones to include (default: zones in every run)')
    parser.add_argument('--year', '-y', type=int, default=0,
                        help='solve year (default: last year in every run)')
    parser.add_argument('--tech', '-i', type=str, default='geothermal',
                        help='tech name used in the lvoe_{tech}.csv filename')
    parser.add_argument('--dollar_year', '-d', type=int, default=DEFAULT_DOLLAR_YEAR,
                        help='dollar year geothermal_lvoe.py was run with (for labels only)')
    parser.add_argument('--name', '-n', type=str, default='',
                        help='suffix for output filenames (default: labels joined by _vs_)')
    parser.add_argument('--outpath', '-o', type=str, default='',
                        help='output folder (default: {case1}/outputs/converge/compare)')
    args = parser.parse_args()
    cases = [os.path.abspath(c) for c in args.cases]
    if len(cases) < 2:
        raise ValueError('Provide at least two runs to compare')
    labels = args.labels.split(',') if args.labels else [os.path.basename(c) for c in cases]
    if len(labels) != len(cases):
        raise ValueError(f'Got {len(labels)} labels for {len(cases)} runs')

    lvoe = get_lvoe(cases, labels, args.tech)
    common = set.intersection(*[set(zip(df.t, df.r)) for _, df in lvoe.groupby('run')])
    year = args.year or max(t for (t, r) in common)
    regions = (
        args.regions.split(',') if args.regions
        else sorted({r for (t, r) in common if t == year})
    )
    missing = [r for r in regions if (year, r) not in common]
    if missing:
        raise ValueError(f'{missing} in {year} not present in every run')

    outpath = args.outpath or os.path.join(cases[0], 'outputs', 'converge', 'compare')
    os.makedirs(outpath, exist_ok=True)
    name = args.name or '_vs_'.join(labels)
    name = ''.join(c if (c.isalnum() or c in '-_.') else '' for c in name)
    unit = f'{args.dollar_year}$/MWh'

    lvoe.round(4).to_csv(os.path.join(outpath, f'lvoe_{args.tech}-all_runs-{name}.csv'), index=False)
    for profile in ['avail', 'flat']:
        table = get_table(lvoe, labels, regions, year, profile)
        table.round(2).to_csv(os.path.join(outpath, f'lvoe_{args.tech}-{year}-{profile}-{name}.csv'))
        plot_bars(
            table, regions, unit,
            title=f'{args.tech.capitalize()} LVOE by service, {year} ({profile} profile)',
            savepath=os.path.join(outpath, f'lvoe_{args.tech}-{year}-{profile}-{name}.png'),
        )
        if profile == 'flat':
            print(f'\n{args.tech} LVOE {year}, flat profile [{unit}]:')
            print(table.round(1).to_string())
    print(f'\nOutputs written to {outpath}')
