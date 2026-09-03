"""
Reserve-margin stress-period prices and dispatch for a finished ReEDS case, read from
{case}/outputs/outputs.h5.

The price plots show whether a stress day's high price is a narrow single-hour spike or a
broad window, which determines how much of it a short-duration resource can capture. The
dispatch plots show the generation stack behind a particular region and day, e.g. whether a
flat price reflects ample local capacity or heavy reliance on imports.

Usage
-----
    python stress_period_plots.py <path-to-case>
    python stress_period_plots.py <path-to-case> --region TX_W
    python stress_period_plots.py <path-to-case> --dispatch-region western \\
        --dispatch-level interconnect --dispatch-year 2050 --dispatch-day y2009d342

Run with --help for the full list of options.

Outputs
-------
Written to {case}/outputs/plots/stress_periods/ by default:
- prices/{region}_{year}.png -- one small-multiples price figure per region, plus a
  national quantity-weighted average
- dispatch/{region}_{year}_{day}.png -- one dispatch stack per --dispatch-region call
"""
import argparse
import os
import sys
import warnings

import matplotlib
## This script only calls savefig(); an interactive backend can crash without a display
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import lines as mlines
from matplotlib import patches as mpatches
import numpy as np
import pandas as pd

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds
from reeds import plots
import tech_eval_utils as teu


#%% ===========================================================================
### --- ARGUMENTS ---
### ===========================================================================
def parse_args():
    parser = argparse.ArgumentParser(
        description='Plot reserve-margin stress-period prices and dispatch for a ReEDS case.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    teu.add_case_arg(parser)
    parser.add_argument(
        '--savepath', type=str, default=None,
        help='output directory (default: {case}/outputs/plots/stress_periods)',
    )

    price = parser.add_argument_group('price plots (prices/)')
    price.add_argument(
        '--year', type=int, default=None,
        help='solve year to plot prices for (default: the last solve year)',
    )
    price.add_argument(
        '--region', type=str, default=None,
        help='single BA to plot prices for; default is one plot per region plus a national one',
    )

    dispatch = parser.add_argument_group('dispatch plot (dispatch/)')
    teu.add_region_args(dispatch, name='dispatch-region', level_name='dispatch-level')
    dispatch.add_argument(
        '--dispatch-year', type=int, default=None,
        help='solve year for --dispatch-region (default: the last solve year)',
    )
    dispatch.add_argument(
        '--dispatch-day', type=str, default=None,
        help=(
            'stress day to plot, e.g. y2009d342 (see the price panel titles for valid labels); '
            'required if --dispatch-region is given'
        ),
    )

    args = parser.parse_args()
    case = teu.resolve_case(args)
    if args.dispatch_region and not args.dispatch_day:
        raise ValueError('--dispatch-day is required when --dispatch-region is given')
    return args, case


#%% ===========================================================================
### --- DATA LOADING ---
### ===========================================================================
def parse_stress_hours(df):
    """Parse stress-period hour labels like 'sy2009d016h003' (synthetic year, day of year,
    hour) into sortable (stress_year, stress_day, hour) columns plus a 'day_label'."""
    parsed = df['h'].str.extract(r's?y(\d+)d(\d+)h(\d+)')
    df['stress_year'] = parsed[0].astype(int)
    df['stress_day'] = parsed[1].astype(int)
    df['hour'] = parsed[2].astype(int)
    df['day_label'] = 'y' + df['stress_year'].astype(str) + 'd' + df['stress_day'].astype(str).str.zfill(3)
    return df.sort_values(['stress_year', 'stress_day', 'hour'])


def select_stress_year(df, year):
    """Filter a price frame to res_marg/na and one solve year, defaulting to the last year
    present. Returns (sub, year); sub is empty if nothing matches."""
    df = df[(df.reqt == 'res_marg') & (df.subcat == 'na')].copy()
    df['t'] = df['t'].astype(int)
    if df.empty:
        return df, year
    year = df['t'].max() if year is None else year
    return df[df.t == year].copy(), year


def load_stress_period_prices(case, year=None, national=False):
    """
    Reserve-margin stress-period price by stress-period timestep for one solve year, parsed
    into (stress_day, hour) so it can be plotted as a within-day timeseries. `national=True`
    reads `reqt_price_sys`, GAMS's own quantity-weighted average across regions; otherwise
    `reqt_price` is returned for every region at once, with an 'r' column.

    Units are $/kW per stress timeslice, not $/MWh: GAMS reports $/MW and does not divide by
    hours(h) for the stress-period formulation. Returns (sub, year); sub is empty if the case
    has no stress-period price data for `year`.
    """
    key = 'reqt_price_sys' if national else 'reqt_price'
    prices = reeds.io.read_output(case, key).rename(
        columns={'*': 'reqt', '*.1': 'subcat', '*.2': 'h', 'Value': 'price'})
    sub, year = select_stress_year(prices, year)
    if sub.empty:
        return sub, year
    sub['price'] = sub['price'] / 1000
    return parse_stress_hours(sub), year


def load_dispatch_stress(case, regions, year=None):
    """
    Stress-period generation by tech (GW) and load (GW) summed across `regions`, for every
    stress day in one solve year.

    Net imports are included as a pseudo-tech: in-region generation is frequently well below
    load, so without them the stack understates supply and looks like an unexplained deficit.
    Summing net imports across `regions` is exact -- flows between two regions inside the
    aggregate cancel, leaving only the net flow across its outer boundary.

    Returns (gen, load, year); both frames are empty if the case has no data for
    `regions`/`year`.
    """
    gen = reeds.io.read_output(case, 'gen_h_stress', valname='GW')
    gen = gen[gen.r.isin(regions)].copy()
    gen['t'] = gen['t'].astype(int)
    if gen.empty:
        return gen, pd.DataFrame(), year

    year = gen['t'].max() if year is None else year
    gen = gen[gen.t == year].copy()
    if gen.empty:
        return gen, pd.DataFrame(), year
    gen['GW'] = gen['GW'] / 1000
    gen['i'] = reeds.reedsplots.simplify_techs(gen['i'])
    gen = gen.groupby(['i', 't', 'h'], as_index=False)['GW'].sum()

    net_imports = reeds.io.read_output(case, 'net_import_h_stress', valname='GW')
    net_imports = net_imports[(net_imports.r.isin(regions)) & (net_imports.t.astype(int) == year)].copy()
    if not net_imports.empty:
        net_imports['GW'] = net_imports['GW'] / 1000
        net_imports = net_imports.groupby(['t', 'h'], as_index=False)['GW'].sum()
        net_imports['i'] = 'Net imports'
        gen = pd.concat([gen, net_imports[['i', 't', 'h', 'GW']]], ignore_index=True)
    gen = parse_stress_hours(gen)

    load = reeds.io.read_output(case, 'load_stress', valname='GW')
    load = load[(load.r.isin(regions)) & (load.t.astype(int) == year)].copy()
    if not load.empty:
        load['GW'] = load['GW'] / 1000
        load = load.groupby(['t', 'h'], as_index=False)['GW'].sum()
        load = parse_stress_hours(load)
    return gen, load, year


#%% ===========================================================================
### --- PLOTTING ---
### ===========================================================================
def plot_stress_period_prices(sub, year, savepath, region=None):
    """
    One panel per stress day, hour of day on the x-axis, on a shared linear scale so the
    genuinely expensive days stand out. Each panel is labeled with that day's share of the
    year's total stress price -- the same weight used for price-weighted capacity value in
    compare_tech_value.py.
    """
    label = region if region is not None else 'national'
    if sub.empty:
        warnings.warn(f'No stress-period price data for {label}, year {year}; skipping plot')
        return

    days = sub[['day_label', 'stress_year', 'stress_day']].drop_duplicates().sort_values(
        ['stress_year', 'stress_day'])
    ndays = len(days)
    ncols = min(5, ndays)
    nrows = int(np.ceil(ndays / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(2.4 * ncols, 2.0 * nrows), sharex=True, sharey=True)
    axes = np.atleast_1d(axes).flatten()

    pct_by_day = sub.groupby('day_label')['price'].sum() / sub['price'].sum() * 100
    for ax, day_label in zip(axes, days['day_label']):
        day = sub[sub.day_label == day_label].sort_values('hour')
        ax.plot(day['hour'], day['price'], marker='o', ms=3, color='0.15', lw=1.1)
        ax.set_title(day_label, fontsize=7.5)
        ax.text(
            0.5, 0.92, f'{pct_by_day[day_label]:.0f}%', transform=ax.transAxes,
            ha='center', va='top', fontsize=7, color='0.35',
        )
        ax.tick_params(labelsize=6.5)
    for ax in axes[ndays:]:
        ax.axis('off')

    fig.supxlabel('Hour of day')
    fig.supylabel(teu.wrap_label(
        f'Reserve margin stress price, {label} {year} [$/kW per stress timeslice]', width=32))
    plt.tight_layout()
    plt.savefig(os.path.join(savepath, f'{label}_{year}.png'))
    plt.close()


def plot_dispatch_stress_day(gen, load, label, year, day_label, savepath):
    """Single-day dispatch stack (GW) with a load line overlay, for one region or aggregate."""
    day = gen[gen.day_label == day_label]
    if day.empty:
        warnings.warn(f'No dispatch data for {label}, {year}, {day_label}; skipping plot')
        return

    tech_color = reeds.io.get_plot_formatting()['tech_color'].squeeze(1).copy()
    tech_color['Net imports'] = '0.65'
    dfday = day.pivot_table(index='hour', columns='i', values='GW', aggfunc='sum').fillna(0)
    ## Keep a consistent stacking order and drop techs that are zero all day
    dfday = dfday[[c for c in tech_color.index if c in dfday.columns and dfday[c].abs().sum() > 0]]

    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    plots.stackbar(dfday, ax, colors=tech_color, net=False, align='center', width=2.6)

    handles = [
        mpatches.Patch(facecolor=tech_color[c], edgecolor='none', label=c)
        for c in dfday.columns
    ][::-1]
    if not load.empty:
        lday = load[load.day_label == day_label].set_index('hour')['GW'].reindex(dfday.index)
        ax.plot(lday.index, lday.values, color='k', lw=1.75, marker='o', ms=4, label='Load')
        handles.append(mlines.Line2D(
            [], [], color='k', lw=1.75, marker='o', ms=4, label='Load'))

    ax.axhline(0, color='0.4', lw=0.8)
    ax.set_title(f'{label}, {year}, {day_label}')
    ax.set_xlabel('Hour of day')
    ax.set_ylabel('GW')
    ax.legend(handles=handles, frameon=False, fontsize=7, loc='upper left', bbox_to_anchor=(1.02, 1))
    plots.despine(ax)
    plt.tight_layout()
    plt.savefig(os.path.join(savepath, f'{label}_{year}_{day_label}.png'))
    plt.close()


#%% ===========================================================================
### --- MAIN ---
### ===========================================================================
def main():
    args, case = parse_args()
    savepath = args.savepath or os.path.join(case, 'outputs', 'plots', 'stress_periods')
    price_savepath = os.path.join(savepath, 'prices')
    os.makedirs(price_savepath, exist_ok=True)

    plots.plotparams()

    national, year = load_stress_period_prices(case, year=args.year, national=True)
    plot_stress_period_prices(national, year, price_savepath, region=None)

    regional, _ = load_stress_period_prices(case, year=year, national=False)
    price_regions = [args.region] if args.region is not None else sorted(regional.r.unique())
    for region in price_regions:
        plot_stress_period_prices(regional[regional.r == region], year, price_savepath, region=region)
    print(f'Wrote price figures to {price_savepath}')

    if args.dispatch_region:
        dispatch_savepath = os.path.join(savepath, 'dispatch')
        os.makedirs(dispatch_savepath, exist_ok=True)
        dispatch_regions = teu.resolve_regions(case, args.dispatch_region, level=args.dispatch_level)
        gen, load, dispatch_year = load_dispatch_stress(case, dispatch_regions, year=args.dispatch_year)
        plot_dispatch_stress_day(
            gen, load, args.dispatch_region, dispatch_year, args.dispatch_day, dispatch_savepath)
        print(f'Wrote dispatch figures to {dispatch_savepath}')


if __name__ == '__main__':
    main()
