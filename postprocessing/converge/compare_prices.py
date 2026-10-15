"""
Compare rep-year hourly energy prices across two or more ReEDS runs, region by region:
    prices_diurnal-{name}.png:       average price by hour of day, one column per season,
                                     one row per (region, solve year)
    prices_duration_week-{name}.png: 8760-hour price duration curve and a sample week,
                                     one row per (region, solve year)
Energy prices are the eq_supply_demand_balance marginals mapped back to the hours of the rep
year using each run's hmap (see geothermal_lvoe.get_energy_prices_hourly).

Usage:
    python postprocessing/converge/compare_prices.py runs/{case1} runs/{case2} [...]
        [--labels "StartCost=5,StartCost=3"] [--regions CO,NM] [--years 2035,2040]
Outputs are written to runs/{case1}/outputs/converge/compare/ unless --outpath is given.
"""
#%% Imports
import os
import sys
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from geothermal_lvoe import get_prices, get_energy_prices_hourly, DEFAULT_DOLLAR_YEAR

## Red then blue, so a two-run comparison reads as base (red) vs alternative (blue)
COLORS = ['C3', 'C0', 'C2', 'C1', 'C4', 'C5']
SEASONS = {
    'Winter (DJF)': [12, 1, 2],
    'Spring (MAM)': [3, 4, 5],
    'Summer (JJA)': [6, 7, 8],
    'Fall (SON)': [9, 10, 11],
}


#%% Functions
def get_hourly(case, dollar_year=DEFAULT_DOLLAR_YEAR):
    """Hourly energy price with index = timestamp and columns = (t, r)"""
    prices = get_prices(case, dollar_year)
    return get_energy_prices_hourly(case, prices)


def get_rows(hourly, regions, years):
    """(region, year) pairs present in every run"""
    available = set.intersection(*[set(df.columns) for df in hourly.values()])
    return [(r, t) for r in regions for t in years if (t, r) in available]


def plot_diurnal(hourly, rows, unit, title, savepath):
    fig, axes = plt.subplots(
        len(rows), len(SEASONS), figsize=(14, 2.75 * len(rows)),
        sharex=True, sharey=True, squeeze=False, layout='constrained',
    )
    for i, (r, t) in enumerate(rows):
        for j, (season, months) in enumerate(SEASONS.items()):
            ax = axes[i, j]
            for k, (label, df) in enumerate(hourly.items()):
                s = df[t, r]
                s = s.loc[s.index.month.isin(months)]
                ax.plot(s.groupby(s.index.hour).mean(), color=COLORS[k], lw=2, label=label)
            ax.grid(alpha=0.3)
            ax.tick_params(labelsize=10, top=False, right=False)
            if i == 0:
                ax.set_title(season, fontsize=12)
            if j == 0:
                ax.set_ylabel(f'{r} {t}\n{unit}', fontsize=11, fontweight='normal')
    for ax in axes[-1]:
        ax.set_xlabel('Hour of day', fontsize=11, fontweight='normal')
        ax.set_xticks(range(0, 24, 6))
    axes[0, 0].legend(loc='upper left', fontsize=9)
    fig.suptitle(title, fontsize=13)
    fig.savefig(savepath, dpi=110)
    plt.close(fig)


def plot_duration_week(hourly, rows, week, unit, title, savepath):
    fig, axes = plt.subplots(
        len(rows), 2, figsize=(13, 4 * len(rows)), sharey=True, squeeze=False,
        layout='constrained',
    )
    for i, (r, t) in enumerate(rows):
        for k, (label, df) in enumerate(hourly.items()):
            s = df[t, r]
            axes[i, 0].plot(np.sort(s.values)[::-1], color=COLORS[k], lw=2, label=label)
            ## The rep year can differ by run, so build the week from each run's own year
            start = pd.Timestamp(f'{s.index[0].year}-{week}', tz=s.index.tz)
            w = s.loc[start:start + pd.Timedelta(days=7) - pd.Timedelta(hours=1)]
            axes[i, 1].plot(w.index, w.values, color=COLORS[k], lw=1.5, label=label)
        axes[i, 0].set_ylabel(f'{r} {t}\n{unit}', fontsize=11, fontweight='normal')
        for ax in axes[i]:
            ax.grid(alpha=0.3)
            ax.tick_params(labelsize=10, top=False, right=False)
        axes[i, 1].tick_params(axis='x', labelrotation=30)
    start = pd.Timestamp(f'2000-{week}')
    end = start + pd.Timedelta(days=6)
    axes[0, 0].set_title(f'Price duration curve ({len(s)} h)', fontsize=12)
    axes[0, 1].set_title(f'Sample week ({start:%b %-d}–{end:%b %-d})', fontsize=12)
    axes[-1, 0].set_xlabel('Hours', fontsize=11, fontweight='normal')
    axes[0, 0].legend(fontsize=9)
    fig.suptitle(title, fontsize=13)
    fig.savefig(savepath, dpi=110)
    plt.close(fig)


#%% Main
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Compare hourly energy prices across ReEDS runs',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('cases', type=str, nargs='+', help='paths to ReEDS run folders')
    parser.add_argument('--labels', '-l', type=str, default='',
                        help='comma-delimited legend labels (default: run folder names)')
    parser.add_argument('--regions', '-r', type=str, default='',
                        help='comma-delimited zones to include (default: zones in every run)')
    parser.add_argument('--years', '-y', type=str, default='',
                        help='comma-delimited solve years (default: last two years in every run)')
    parser.add_argument('--week', '-w', type=str, default='07-15',
                        help='MM-DD start of the 7-day sample week')
    parser.add_argument('--dollar_year', '-d', type=int, default=DEFAULT_DOLLAR_YEAR,
                        help='output dollar year')
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
    if len(cases) > len(COLORS):
        raise ValueError(f'At most {len(COLORS)} runs can be compared')

    hourly = {label: get_hourly(case, args.dollar_year) for label, case in zip(labels, cases)}
    common = set.intersection(*[set(df.columns) for df in hourly.values()])
    regions = (
        args.regions.split(',') if args.regions
        else sorted({r for (t, r) in common})
    )
    years = (
        [int(t) for t in args.years.split(',')] if args.years
        else sorted({t for (t, r) in common})[-2:]
    )
    rows = get_rows(hourly, regions, years)
    if not rows:
        raise ValueError(f'No (region, year) in {regions} x {years} is present in every run')
    missing = [(r, t) for r in regions for t in years if (r, t) not in rows]
    if missing:
        print(f'Skipping (region, year) not present in every run: {missing}')

    outpath = args.outpath or os.path.join(cases[0], 'outputs', 'converge', 'compare')
    os.makedirs(outpath, exist_ok=True)
    name = args.name or '_vs_'.join(labels)
    name = ''.join(c if (c.isalnum() or c in '-_.') else '' for c in name)
    unit = f'{args.dollar_year}$/MWh'

    plot_diurnal(
        hourly, rows, unit,
        title=f'Average hourly energy price by season: {" vs ".join(labels)}',
        savepath=os.path.join(outpath, f'prices_diurnal-{name}.png'),
    )
    plot_duration_week(
        hourly, rows, args.week, unit,
        title=f'Hourly energy prices: {" vs ".join(labels)}',
        savepath=os.path.join(outpath, f'prices_duration_week-{name}.png'),
    )

    ## Summary table
    stats = []
    for (r, t) in rows:
        for label, df in hourly.items():
            s = df[t, r].astype(float)
            evening = s.loc[s.index.hour.isin(range(17, 22))]
            stats.append({
                'run': label, 'r': r, 't': t, 'mean': s.mean(), 'std': s.std(),
                'p95': s.quantile(0.95), 'max': s.max(), 'evening_mean': evening.mean(),
                'hours_lt_5': int((s < 5).sum()),
            })
    stats = pd.DataFrame(stats).set_index(['r', 't', 'run'])
    stats.round(2).to_csv(os.path.join(outpath, f'prices_stats-{name}.csv'))
    print(f'\nHourly energy price [{unit}]; evening = hours 17-21:')
    print(stats.round(1).to_string())
    print(f'\nOutputs written to {outpath}')
