#%% Imports
import argparse
import os
import sys

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds

reeds_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
reeds.plots.plotparams()


#%% Plotting

def plot_hourly_demand_profiles(cases, colors, year='last', weatheryear=2012):
    """
    Compare hourly demand profiles across cases for a given weather year.
    Overlays the selected weather year demand and fills envelope of min/max across weather years.
    """
    if len(cases) < 2:
        raise ValueError('Need at least 2 cases to compare inputs.')

    plt.close()
    f, ax = plt.subplots(figsize=(12, 4.5))
    x_start, x_end = None, None

    for idx, (casename, casepath) in enumerate(cases.items()):
        print(f'  {casename}: loading hourly demand...')
        color = colors.get(casename, f'C{idx}')

        # Parse inputs
        sw = reeds.io.get_switches(casepath)
        t = reeds.io.get_years(casepath)[-1] if year in [0, None, 'last'] else year
        rs = reeds.inputs.parse_regions(casepath)

        case_weatheryears = sw.resource_adequacy_years_list

        # Load demand profile
        dfprofile = (
            reeds.io.read_file(
                os.path.join(casepath, 'inputs_case', 'load.h5'),
                parse_timestamps=True,
            )
            / 1e3
        )
        dfprofile = (
            dfprofile
            .loc[t, [r for r in dfprofile if r in rs]]
            .sum(axis=1)
        )

        # Slice to weather years range
        dfprofile = dfprofile.loc[
            str(min(case_weatheryears)) : str(max(case_weatheryears))
        ].copy()
        dfprofile.index = pd.to_datetime(dfprofile.index)
        
        # Group by day of year (1-365/366) across all weather years
        doy = dfprofile.index.dayofyear
        hourly_stats = dfprofile.groupby(doy).agg(['min', 'max'])
        hourly_stats.columns = ['min', 'max']

        selected_profile = dfprofile.loc[dfprofile.index.year == int(weatheryear)]
        if selected_profile.empty:
            available_years = sorted(dfprofile.index.year.unique().tolist())
            raise ValueError(
                f'Weather year {weatheryear} not found for case {casename}. '
                f'Available weather years: {available_years}'
            )
        hourly_stats['selected'] = selected_profile.groupby(selected_profile.index.dayofyear).mean()

        # Create date x-axis for a standard year
        date_range = pd.date_range('2025-01-01', periods=len(hourly_stats), freq='D')
        if x_start is None:
            x_start, x_end = date_range[0], date_range[-1]

        # Plot selected weather year
        ax.plot(date_range, hourly_stats['selected'], lw=1.0, color=color, label=casename)

        # Fill envelope (min/max across weather years)
        ax.fill_between(
            date_range, hourly_stats['max'], hourly_stats['min'],
            lw=0, alpha=0.15, color=color,
        )

        # Plot min/max dotted lines
        ax.plot(date_range, hourly_stats['max'], lw=0.5, linestyle=':', color=color, alpha=0.6)
        ax.plot(date_range, hourly_stats['min'], lw=0.5, linestyle=':', color=color, alpha=0.6)

    ax.yaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(2))
    ax.set_ylabel('Daily mean electricity demand [GW]')
    ax.set_ylim(0)
    
    # Format x-axis dates
    ax.xaxis.set_major_locator(mpl.dates.MonthLocator())
    ax.xaxis.set_major_formatter(mpl.dates.DateFormatter('%b-1'))
    ax.tick_params(axis='x', rotation=45)
    if x_start is not None and x_end is not None:
        ax.set_xlim(x_start, x_end)
    ax.margins(x=0)
    ax.grid(True, which='major', axis='y', alpha=0.3)

    yearlabel = year if year not in [0, None, 'last'] else 'last model year'
    ax.set_title(
        f'Daily mean demand in {yearlabel} for weather year {weatheryear} with min/max envelope across all weather years',
        x=0, ha='left'
    )
    ax.legend(frameon=False, loc='lower center', ncol=len(cases))
    reeds.plots.despine(ax)

    return f, ax


def plot_modelyear_load_stats(cases, colors, weatheryear=2012):
    """
    Compare annual total load and annual peak load by model year.
    For each model year and case, compute min/max across weather years and
    the value for the selected weather year.
    """
    if len(cases) < 2:
        raise ValueError('Need at least 2 cases to compare inputs.')

    f, (ax_total, ax_peak) = plt.subplots(
        1, 2, figsize=(12, 4.5), constrained_layout=True
    )
    stats_by_case = {}

    for idx, (casename, casepath) in enumerate(cases.items()):
        print(f'  {casename}: loading annual and peak stats by model year...')
        color = colors.get(casename, f'C{idx}')

        sw = reeds.io.get_switches(casepath)
        modelyears = reeds.io.get_years(casepath)
        rs = reeds.inputs.parse_regions(casepath)
        case_weatheryears = sw.resource_adequacy_years_list

        dfload = (
            reeds.io.read_file(
                os.path.join(casepath, 'inputs_case', 'load.h5'),
                parse_timestamps=True,
            )
            / 1e3
        )
        region_cols = [r for r in dfload if r in rs]

        rows = []
        for t in modelyears:
            profile = dfload.loc[t, region_cols].sum(axis=1)
            profile = profile.loc[
                str(min(case_weatheryears)) : str(max(case_weatheryears))
            ].copy()
            profile.index = pd.to_datetime(profile.index)

            # profile is in GW and timestamps are hourly, so annual sum is GWh.
            # Convert to TWh for plotting.
            annual_total_by_wy = profile.groupby(profile.index.year).sum() / 1e3
            annual_peak_by_wy = profile.groupby(profile.index.year).max()

            if int(weatheryear) not in annual_total_by_wy.index:
                available_years = sorted(annual_total_by_wy.index.tolist())
                raise ValueError(
                    f'Weather year {weatheryear} not found for case {casename}, '
                    f'model year {t}. Available weather years: {available_years}'
                )

            rows.append(
                {
                    't': t,
                    'total_min': annual_total_by_wy.min(),
                    'total_max': annual_total_by_wy.max(),
                    'total_selected': annual_total_by_wy.loc[int(weatheryear)],
                    'peak_min': annual_peak_by_wy.min(),
                    'peak_max': annual_peak_by_wy.max(),
                    'peak_selected': annual_peak_by_wy.loc[int(weatheryear)],
                }
            )

        dfstats = pd.DataFrame(rows).set_index('t').sort_index()
        stats_by_case[casename] = dfstats

        x = dfstats.index.values

        ax_total.plot(x, dfstats['total_selected'].values, lw=1.2, color=color, label=casename)
        ax_total.fill_between(x, dfstats['total_max'].values, dfstats['total_min'].values, lw=0, alpha=0.15, color=color)
        ax_total.plot(x, dfstats['total_max'].values, lw=0.8, linestyle=':', color=color, alpha=0.7)
        ax_total.plot(x, dfstats['total_min'].values, lw=0.8, linestyle=':', color=color, alpha=0.7)

        ax_peak.plot(x, dfstats['peak_selected'].values, lw=1.2, color=color, label=casename)
        ax_peak.fill_between(x, dfstats['peak_max'].values, dfstats['peak_min'].values, lw=0, alpha=0.15, color=color)
        ax_peak.plot(x, dfstats['peak_max'].values, lw=0.8, linestyle=':', color=color, alpha=0.7)
        ax_peak.plot(x, dfstats['peak_min'].values, lw=0.8, linestyle=':', color=color, alpha=0.7)

    ax_total.yaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(2))
    ax_total.set_ylabel('Annual total load [TWh]')
    ax_total.set_title(
        f'Annual total load by model year (weather year {weatheryear}, min/max envelope)',
        x=0,
        ha='left',
    )
    ax_total.legend(frameon=False, loc='best')
    ax_total.margins(x=0)
    ax_total.set_xlim(left=2020)
    ax_total.grid(True, which='major', axis='y', alpha=0.3)
    reeds.plots.despine(ax_total)

    ax_peak.yaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(2))
    ax_peak.set_xlabel('Model year')
    ax_peak.set_ylabel('Annual peak load [GW]')
    ax_peak.set_title(
        f'Annual peak load by model year (weather year {weatheryear}, min/max envelope)',
        x=0,
        ha='left',
    )
    ax_peak.legend(frameon=False, loc='best')
    ax_peak.margins(x=0)
    ax_peak.set_xlim(left=2020)
    ax_peak.grid(True, which='major', axis='y', alpha=0.3)
    reeds.plots.despine(ax_peak)

    return f, (ax_total, ax_peak), stats_by_case


#%% Main
parser = argparse.ArgumentParser(
    description='Compare ReEDS input data for multiple cases',
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
)
parser.add_argument(
    'caselist',
    type=str,
    nargs='+',
    help=(
        'Space-delimited list of case paths, OR shared case prefix, OR CSV '
        'with casepath/casename/color columns (e.g., postprocessing/example.csv).'
    ),
)
parser.add_argument(
    '--casenames', '-n', type=str, default='',
    help='Comma-delimited case names when not provided in CSV.',
)
parser.add_argument(
    '--titleshorten', '-s', type=str, default='',
    help='Characters to cut from start of case name (if not using CSV casenames).',
)
parser.add_argument(
    '--basecase', '-b', type=str, default='',
    help='Case-path suffix to force as base case (kept for parity with compare_cases.py).',
)
parser.add_argument(
    '--year', '-y', type=str, default='2050',
    help='Model year for hourly demand plot (integer year or "last").',
)
parser.add_argument(
    '--weatheryear', '-w', type=str, default='2012',
    help='Actual weather year to plot.',
)


if __name__ == '__main__':
    args = parser.parse_args()

    try:
        titleshorten = int(args.titleshorten)
    except ValueError:
        titleshorten = len(args.titleshorten)

    cases, colors, basecase, basemap = reeds.report_utils.parse_caselist(
        args.caselist,
        args.casenames,
        args.basecase,
        titleshorten,
    )

    firstcasepath = list(cases.values())[0]
    outpath = os.path.join(firstcasepath, 'outputs', 'comparisons','inputs')
    os.makedirs(outpath, exist_ok=True)

    try:
        year = int(args.year)
    except ValueError:
        year = args.year

    f, ax = plot_hourly_demand_profiles(
        cases,
        colors,
        year=year,
        weatheryear=args.weatheryear,
    )

    f_modelyear, _, _ = plot_modelyear_load_stats(
        cases,
        colors,
        weatheryear=args.weatheryear,
    )

    outfile = os.path.join(outpath, f'demand_daily-profile_{year}.png')
    f.savefig(outfile, dpi=250)
    print(f'Saved: {outfile}')

    outfile_modelyear = os.path.join(outpath, f'demand_annual-total-peak_by-modelyear_wy{args.weatheryear}.png')
    f_modelyear.savefig(outfile_modelyear, dpi=250)
    print(f'Saved: {outfile_modelyear}')
