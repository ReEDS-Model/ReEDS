"""
Capacity and generation stacked-bar plots by technology, over time, for a chosen region of
a finished ReEDS case (e.g. a state).

Uses the same conventions as compare_cases.py's national capacity/generation stacks
(reeds.plots.stackbar, reeds.reedsplots.simplify_techs/get_tech_colors_order), restricted to
one region instead of the whole country.

Usage
-----
    python region_stack.py <path-to-case> --region WI --region-level st

Run with --help for the full list of options.

Outputs
-------
Written to {case}/outputs/plots/region_stack/ by default:
- region_stack.png -- capacity (GW) and generation (TWh) stacked by tech, one panel each;
  the generation panel overlays a `load_rt` load line, above which the region is a net
  importer that year and below which it is a net exporter
- region_cap.csv, region_gen.csv, region_load.csv -- the tidy data behind each panel/line
"""
import argparse
import os
import sys

import matplotlib
## This script only calls savefig(); an interactive backend can crash without a display
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import lines as mlines
from matplotlib import patches as mpatches

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds
from reeds import plots
from reeds import reedsplots
import tech_eval_utils as teu


#%% ===========================================================================
### --- ARGUMENTS ---
### ===========================================================================
def parse_args():
    parser = argparse.ArgumentParser(
        description='Capacity and generation stacked-bar plots by tech, over time, for a region.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    teu.add_case_arg(parser)
    parser.add_argument(
        '--savepath', type=str, default=None,
        help='output directory (default: {case}/outputs/plots/region_stack)',
    )
    teu.add_region_args(parser, required=True)
    parser.add_argument(
        '--simple-techs', type=str, default='display',
        help='tech_aggregation.csv column to aggregate raw tech names by (matches compare_cases.py)',
    )
    parser.add_argument(
        '--first-year', type=int, default=2026,
        help='first endogenous solve year; earlier years are fixed to historical/calibration data',
    )
    parser.add_argument('--last-year', type=int, default=2050, help='last year to show')

    args = parser.parse_args()
    return args, teu.resolve_case(args)


#%% ===========================================================================
### --- DATA LOADING ---
### ===========================================================================
def load_stack_data(case, filename, valname, regions, scale, simple_techs, first_year, last_year):
    """
    Load a (i, r, t, Value) output (e.g. 'cap' or 'gen_ann'), restrict to `regions` and
    [first_year, last_year], simplify tech names via reedsplots.simplify_techs, and sum to a
    tidy (tech, year) frame in the requested `scale` (e.g. 1e3 to convert MW -> GW).
    """
    df = reeds.io.read_output(case, filename, valname=valname, r_filter=regions)
    df = df.rename(columns={'i': 'tech', 't': 'year'})
    df['year'] = df['year'].astype(int)
    df = df[(df['year'] >= first_year) & (df['year'] <= last_year)].copy()
    df[valname] = df[valname] / scale
    df['tech'] = reedsplots.simplify_techs(df['tech'], display_level=simple_techs)
    return df.groupby(['tech', 'year'], as_index=False)[valname].sum()


def load_load_data(case, regions, scale, first_year, last_year):
    """
    Annual exogenous load (`load_rt(r,t)`, MWh) summed across `regions`, for the generation
    panel's load line. gen_ann is already net of storage charging and production load, so
    comparing the two is apples to apples.
    """
    df = reeds.io.read_output(case, 'load_rt', valname='Load (TWh)', r_filter=regions)
    df = df.rename(columns={'t': 'year'})
    df['year'] = df['year'].astype(int)
    df = df[(df['year'] >= first_year) & (df['year'] <= last_year)].copy()
    df['Load (TWh)'] = df['Load (TWh)'] / scale
    return df.groupby('year', as_index=False)['Load (TWh)'].sum()


#%% ===========================================================================
### --- PLOTTING ---
### ===========================================================================
def plot_region_stack(dfcap, dfgen, dfload, colors, savepath, region_label):
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.5), sharex=True)

    alltechs = set()
    for a, (df, valname, ylabel, title) in zip(ax, [
        (dfcap, 'Capacity (GW)', 'Capacity [GW]', 'Capacity'),
        (dfgen, 'Generation (TWh)', 'Generation [TWh]', 'Generation'),
    ]):
        dfplot = df.pivot(index='year', columns='tech', values=valname)
        ## Techs with no tech_color entry are dropped, matching compare_cases.py; warn when
        ## a dropped tech is more than float noise
        dropped = [c for c in dfplot.columns if c not in colors.index]
        for tech in dropped:
            if dfplot[tech].abs().max() > 0.01:
                print(f"  Warning: '{tech}' has no tech_color entry -- dropped from the {title} plot")
        dfplot = dfplot[[c for c in colors.index if c in dfplot.columns]].round(3)
        alltechs.update(dfplot.columns)

        years = sorted(dfplot.index)
        width = (years[-1] - years[-2]) if len(years) > 1 else 1
        plots.stackbar(df=dfplot, ax=a, colors=colors, width=width, net=False)
        a.set_ylabel(ylabel)
        a.set_xlabel('Year')
        a.set_title(title)
        plots.despine(a)

    ## Above the stack the region is a net importer that year, below it a net exporter
    dfload = dfload.sort_values('year')
    ax[1].plot(
        dfload['year'], dfload['Load (TWh)'], color='k', marker='o', ms=4, lw=1.5,
        label='Load', zorder=10,
    )

    handles = [
        mpatches.Patch(facecolor=colors[t], edgecolor='none', label=t)
        for t in colors.index if t in alltechs
    ]
    handles.append(mlines.Line2D([], [], color='k', marker='o', ms=4, lw=1.5, label='Load'))
    ax[-1].legend(
        handles=handles[::-1], loc='upper left', bbox_to_anchor=(1.02, 1),
        fontsize=8, frameon=False, handletextpad=0.4, handlelength=0.9,
    )
    fig.suptitle(region_label, y=1.03, fontsize=12, weight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(savepath, 'region_stack.png'))
    plt.close()


#%% ===========================================================================
### --- MAIN ---
### ===========================================================================
def main():
    args, case = parse_args()
    savepath = args.savepath or os.path.join(case, 'outputs', 'plots', 'region_stack')
    os.makedirs(savepath, exist_ok=True)

    plots.plotparams()
    regions = teu.resolve_regions(case, args.region, level=args.region_level)

    dfcap = load_stack_data(
        case, 'cap', 'Capacity (GW)', regions, 1e3, args.simple_techs, args.first_year, args.last_year)
    dfgen = load_stack_data(
        case, 'gen_ann', 'Generation (TWh)', regions, 1e6, args.simple_techs, args.first_year, args.last_year)
    dfload = load_load_data(case, regions, 1e6, args.first_year, args.last_year)

    colors, _ = reedsplots.get_tech_colors_order()

    dfcap.to_csv(os.path.join(savepath, 'region_cap.csv'), index=False)
    dfgen.to_csv(os.path.join(savepath, 'region_gen.csv'), index=False)
    dfload.to_csv(os.path.join(savepath, 'region_load.csv'), index=False)
    print(f'Wrote {os.path.join(savepath, "region_cap.csv")}')
    print(f'Wrote {os.path.join(savepath, "region_gen.csv")}')
    print(f'Wrote {os.path.join(savepath, "region_load.csv")}')

    plot_region_stack(dfcap, dfgen, dfload, colors, savepath, region_label=args.region)
    print(f'Wrote {os.path.join(savepath, "region_stack.png")}')


if __name__ == '__main__':
    main()
