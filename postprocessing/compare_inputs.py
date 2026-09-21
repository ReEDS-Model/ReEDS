#%% Imports
import argparse
import os
import re
import sys
import textwrap
import traceback
import cmocean

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import patheffects as pe
import pandas as pd

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds
from postprocessing import input_plots

reeds_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
reeds.plots.plotparams()

#%% Global Variables
# Define regions for which hourly demand profiles will be plotted
hourly_regions = {
    'IL':['IL_MISO','IL_PJM'],
    'TX':['TX_ERCOT_E', 'TX_ERCOT_W', 'TX_MISO', 'TX_SPP'],
}
cmap = cmocean.cm.tempo
cmap_diff = plt.cm.RdBu_r

#%% Plotting

def _parse_weatheryears(weatheryear):
    """Parse a weather-year input into a sorted list of unique integer years."""
    if isinstance(weatheryear, int):
        return [weatheryear]

    if isinstance(weatheryear, str):
        tokens = [tok.strip() for tok in re.split(r'[_\s]+', weatheryear) if tok.strip()]
    else:
        try:
            tokens = list(weatheryear)
        except TypeError as exc:
            raise ValueError(
                f'Invalid weather year input: {weatheryear}. Provide an integer year '
                'or comma/space-delimited list of years.'
            ) from exc

    if not tokens:
        raise ValueError('No weather years provided.')

    try:
        years = sorted(set(int(token) for token in tokens))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f'Invalid weather year input: {weatheryear}. All weather years must be integers.'
        ) from exc

    return years

def _validate_selected_weatheryears(selected_years, available_years, case_label, modelyear=None):
    """Ensure selected weather years exist in available years for a given case/model year."""
    missing = sorted(set(selected_years) - set(available_years))
    if missing:
        where = f' for case {case_label}'
        if modelyear is not None:
            where += f', model year {modelyear}'
        raise ValueError(
            f'Weather year(s) {missing} not found{where}. '
            f'Available weather years: {sorted(available_years)}'
        )

def plot_hourly_demand_profiles(cases, colors, year='last', weatheryear=2012, region=None,):
    if len(cases) < 2:
        raise ValueError('Need at least 2 cases to compare inputs.')

    selected_weatheryears = _parse_weatheryears(weatheryear)

    plt.close()
    f, ax = plt.subplots(figsize=(13.33, 4))
    
    for idx, (casename, casepath) in enumerate(cases.items()):
        color = colors.get(casename, f'C{idx}')

        input_plots.plot_profile(
            casepath, datum='demand', year=year, weatheryears=selected_weatheryears,
            reg_sub=region, color=color, label=casename, f=f, ax=ax, hourly=True,
        )
    ax.margins(x=0)
    ax.grid(True, which='major', axis='y', alpha=0.3)
    
    ax.legend(frameon=False, loc='lower center', ncol=len(cases))
    plt.autoscale(enable=True, axis='y')
    ax.set_ylim(0)

    return f, ax

def plot_demand_yearbymonth(cases, colors, year='last', weatheryear=2012):
    selected_weatheryears = _parse_weatheryears(weatheryear)

    plt.close()
    for idx, (casename, casepath) in enumerate(cases.items()):
        t = reeds.io.get_years(casepath)[-1] if year in [0, None, 'last'] else year
        color = colors.get(casename, f'C{idx}')
        
        dfprofile = (
            reeds.results.summarize_load_data(
                casepath, 
                use_run=True,
                agg_reg_lvl='all',
                model_year_sub=[t], 
                weather_year_sub=selected_weatheryears,
            )
            / 1e3
        )
        dfprofile.index = pd.to_datetime(dfprofile.index.get_level_values('datetime'))
        if idx == 0:
            f,ax = reeds.plots.plotyearbymonth(
                dfprofile.rename({'load_MWh': casename}), 
                style='line', colors=[color]
            )
        else:
            reeds.plots.plotyearbymonth(
                dfprofile.rename({'load_MWh': casename}),
                style='line', colors=[color], f=f, ax=ax
            )
                   
    ax[0].legend(loc='upper left', bbox_to_anchor=(1,1), frameon=False, fontsize='x-large')
    
    return f, ax

def plot_peak_and_total_load(cases, colors, weatheryear=2012):
    """
    Compare annual total load and annual peak load by model year.
    For each model year and case, compute min/max across weather years and
    the value for each selected weather year.
    """
    if len(cases) < 2:
        raise ValueError('Need at least 2 cases to compare inputs.')

    selected_weatheryears = _parse_weatheryears(weatheryear)

    f, (ax_total, ax_peak) = plt.subplots(
        1, 2, figsize=(12, 4.5), constrained_layout=True
    )
    stats_by_case = {}
    for idx, (casename, casepath) in enumerate(cases.items()):
        print(f'  {casename}: loading annual and peak stats by model year...')
        color = colors.get(casename, f'C{idx}')

        sw = reeds.io.get_switches(casepath)
        modelyears = reeds.io.get_years(casepath)
        case_weatheryears = sw.resource_adequacy_years_list

        dfprofile = (
            reeds.results.summarize_load_data(
                casepath, 
                use_run=True, 
            )
            / 1e3
        )

        rows = []
        for t in modelyears:
            profile = dfprofile.loc[t].sum(axis=1)
            profile.index = pd.to_datetime(profile.index)

            # profile is in GW and timestamps are hourly, so annual sum is GWh.
            # Convert to TWh for plotting.
            annual_total_by_wy = profile.groupby(profile.index.year).sum() / 1e3
            annual_peak_by_wy = profile.groupby(profile.index.year).max()

            _validate_selected_weatheryears(
                selected_weatheryears,
                annual_total_by_wy.index.tolist(),
                casename,
                modelyear=t,
            )

            rows.append(
                {
                    't': t,
                    'total_min': annual_total_by_wy.min(),
                    'total_max': annual_total_by_wy.max(),
                    'peak_min': annual_peak_by_wy.min(),
                    'peak_max': annual_peak_by_wy.max(),
                    **{
                        f'total_selected_{wy}': annual_total_by_wy.loc[wy]
                        for wy in selected_weatheryears
                    },
                    **{
                        f'peak_selected_{wy}': annual_peak_by_wy.loc[wy]
                        for wy in selected_weatheryears
                    },
                }
            )

        dfstats = pd.DataFrame(rows).set_index('t').sort_index()
        stats_by_case[casename] = dfstats

        x = dfstats.index.values

        avg_total = dfstats[[f'total_selected_{wy}' for wy in selected_weatheryears]].mean(axis=1)
        ax_total.plot(
            x, avg_total.values, lw=1.2, color=color, label=casename,
        )
        ax_total.fill_between(x, dfstats['total_max'].values, dfstats['total_min'].values, lw=0, alpha=0.15, color=color)
        ax_total.plot(x, dfstats['total_max'].values, lw=0.8, linestyle=':', color=color, alpha=0.7)
        ax_total.plot(x, dfstats['total_min'].values, lw=0.8, linestyle=':', color=color, alpha=0.7)

        avg_peak = dfstats[[f'peak_selected_{wy}' for wy in selected_weatheryears]].mean(axis=1)
        ax_peak.plot(
            x, avg_peak.values, lw=1.2, color=color, label=casename,
        )
        ax_peak.fill_between(x, dfstats['peak_max'].values, dfstats['peak_min'].values, lw=0, alpha=0.15, color=color)
        ax_peak.plot(x, dfstats['peak_max'].values, lw=0.8, linestyle=':', color=color, alpha=0.7)
        ax_peak.plot(x, dfstats['peak_min'].values, lw=0.8, linestyle=':', color=color, alpha=0.7)

    ax_total.yaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(2))
    ax_total.set_ylabel('Annual total load [TWh]')
    ax_total.legend(frameon=False, loc='best')
    ax_total.margins(x=0)
    ax_total.set_xlim(left=2020)
    ax_total.grid(True, which='major', axis='y', alpha=0.3)
    reeds.plots.despine(ax_total)

    ax_peak.yaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(2))
    ax_peak.set_xlabel('Model year')
    ax_peak.set_ylabel('Annual peak load [GW]')
    ax_peak.legend(frameon=False, loc='best')
    ax_peak.margins(x=0)
    ax_peak.set_xlim(left=2020)
    ax_peak.grid(True, which='major', axis='y', alpha=0.3)
    reeds.plots.despine(ax_peak)

    plt.draw()


    return f, (ax_total, ax_peak), stats_by_case

def plot_regional_peak_demand_maps(cases, year='last'):
    """
    Map the max peak demand per state, comparing across cases.

    For each state, peak demand is the highest simultaneous (summed across
    BAs in that state) hourly value across ALL available weather years for
    the given model year.

    Layout: 1 row x N-cases columns.
      Base case (first case): absolute peak demand [GW] with a sequential colormap.
      All other cases: percent difference vs. the base case with a diverging colormap.

    Parameters
    ----------
    cases : dict  {casename: casepath}
    year : int or 'last'
        Model year to plot. Defaults to the last solved year of the base case.

    Returns
    -------
    f, ax, df_peak
        df_peak has one column per case, indexed by state, values in GW.
    """
    if len(cases) < 2:
        raise ValueError('Need at least 2 cases to compare inputs.')

    basecasename = list(cases.keys())[0]
    basecasepath = list(cases.values())[0]

    if year in [0, None, 'last']:
        t = reeds.io.get_years(basecasepath)[-1]
    else:
        t = int(year)

    dfmap = reeds.io.get_dfmap(basecasepath)
    dfstates = dfmap['st']

    peak_st = {}
    for casename, casepath in cases.items():
        print(f'  {casename}: loading state-level peak demand...')
        sw = reeds.io.get_switches(casepath)
        case_weatheryears = sw.resource_adequacy_years_list
        region_to_state = reeds.io.get_hierarchy(casepath)['st']

        dfprofile = (
            reeds.results.summarize_load_data(
                casepath, 
                use_run=True, 
                model_year_sub=[t], 
            )
            / 1e3
        )

        try:
            df_t = dfprofile.loc[t].copy()
        except KeyError:
            raise KeyError(f'Model year {t} not found in load.h5 for case {casename}.')

        df_t.index = pd.to_datetime(df_t.index)
        # Aggregate BAs to states, then take the max simultaneous hour
        df_t_st = df_t.T.groupby(df_t.columns.map(region_to_state)).sum().T
        peak_st[casename] = df_t_st.max()

    ncols = len(cases)
    cmap_abs = cmap

    plt.close()
    f, ax = plt.subplots(
        1, ncols,
        figsize=(max(5 * ncols, 10), 5),
        gridspec_kw={'wspace': 0.0},
    )
    if ncols == 1:
        ax = [ax]

    base_vals = peak_st[basecasename]
    abs_vmax = max(
        (peak_st[c].reindex(dfstates.index).fillna(0).max() for c in cases),
        default=0.0,
    )
    pct_diffs = {
        c: ((peak_st[c] - base_vals) / base_vals * 100)
           .replace([float('inf'), float('-inf')], float('nan'))
        for c in list(cases.keys())[1:]
    }
    diff_absmax = max(
        (pct_diffs[c].abs().max()
         for c in pct_diffs if not pct_diffs[c].dropna().empty),
        default=1.0,
    )

    for col, casename in enumerate(cases):
        _ax = ax[col]
        dfplot = dfstates.copy()

        if casename == basecasename:
            dfplot['val'] = base_vals.reindex(dfstates.index).fillna(0)
            _cmap, vmin, vmax = cmap_abs, 0, abs_vmax
            cbar_label = 'Peak demand [GW]'
        else:
            dfplot['val'] = pct_diffs[casename].reindex(dfstates.index)
            _cmap, vmin, vmax = cmap_diff, -diff_absmax, diff_absmax
            cbar_label = f'Change in peak demand [%]'

        dfstates.plot(ax=_ax, facecolor='none', edgecolor='k', lw=0.2, zorder=10000)
        dfplot.plot(ax=_ax, column='val', cmap=_cmap, vmin=vmin, vmax=vmax, legend=False)

        # Value labels for states
        reeds.reedsplots.label_region_value(
            dfplot,
            ax=_ax,
            column='val',
            fmt='{:.0f}' if casename == basecasename else '{:+.0f}',
            text_kwargs={'fontsize': 7, 'ha': 'center', 'va': 'center', 'color': 'k'},
            pe_kwargs={'linewidth': 1.5, 'foreground': 'white'}
        )

        if col == 0 or col == 1:
            reeds.plots.addcolorbarhist(
                f=f, ax0=_ax, data=dfplot['val'].dropna().values,
                title=cbar_label, cmap=_cmap, vmin=vmin, vmax=vmax,
                orientation='horizontal', labelpad=2.25, histratio=0.,
                cbarwidth=0.05, cbarheight=0.85,
                cbarbottom=-0.05, cbarhoffset=0.,
                title_fontsize=18, ticklabel_fontsize=16
            )

        _ax.annotate(casename, (0.1, 1), xycoords='axes fraction', fontsize=18)
        _ax.axis('off')

    df_peak = pd.DataFrame(peak_st).reindex(dfstates.index)
    return f, ax, df_peak


def plot_regional_total_demand_maps(cases, colors, year='last', weatheryear=2012):
    """
    Map total annual demand per state, comparing across cases.

    For each state, total demand is summed across all BAs in that state over
    the selected weather year(s) and averaged if more than one year is given.

    Layout: 1 row x N-cases columns.
      Base case (first case): absolute total demand [TWh] with a sequential colormap.
      All other cases: percent difference vs. the base case with a diverging colormap.

    Parameters
    ----------
    cases : dict  {casename: casepath}
    colors : dict {casename: color}  (unused in maps but kept for API parity)
    year : int or 'last'
        Model year to plot. Defaults to the last solved year of the base case.
    weatheryear : int, str, or iterable
        Weather year(s) to use. Values are averaged when multiple are given.

    Returns
    -------
    f, ax, df_total
        df_total has one column per case, indexed by state, values in TWh.
        df_total has one column per case, indexed by region, values in TWh.
    """
    if len(cases) < 2:
        raise ValueError('Need at least 2 cases to compare inputs.')

    selected_weatheryears = _parse_weatheryears(weatheryear)
    basecasename = list(cases.keys())[0]
    basecasepath = list(cases.values())[0]

    if year in [0, None, 'last']:
        t = reeds.io.get_years(basecasepath)[-1]
    else:
        t = int(year)

    dfmap = reeds.io.get_dfmap(basecasepath)
    dfstates = dfmap['st']

    total_st = {}
    for casename, casepath in cases.items():
        print(f'  {casename}: loading state-level total demand...')
        sw = reeds.io.get_switches(casepath)
        case_weatheryears = sw.resource_adequacy_years_list
        region_to_state = reeds.io.get_hierarchy(casepath)['st']

        dfprofile = (
            reeds.results.summarize_load_data(
                casepath, 
                use_run=True, 
                model_year_sub=[t], 
                weather_year_sub=selected_weatheryears,
            )
            / 1e3
        )
        dfprofile.index = pd.to_datetime(dfprofile.index.get_level_values('datetime'))
        dfprofile = dfprofile.loc[
            str(min(case_weatheryears)) : str(max(case_weatheryears))
        ]
        available_wy = sorted(dfprofile.index.year.unique().tolist())
        _validate_selected_weatheryears(selected_weatheryears, available_wy, casename, t)

        # Aggregate BAs to states, then average annual total across ALL available weather years
        dfprofile_st = dfprofile.T.groupby(dfprofile.columns.map(region_to_state)).sum().T
        wy_totals = pd.concat(
            [dfprofile_st.loc[dfprofile_st.index.year == wy].sum() / 1e3  # GWh -> TWh
             for wy in available_wy],
            axis=1,
        ).mean(axis=1)
        total_st[casename] = wy_totals

    ncols = len(cases)
    cmap_abs = cmap

    plt.close()
    f, ax = plt.subplots(
        1, ncols,
        figsize=(max(5 * ncols, 10), 5),
        gridspec_kw={'wspace': 0.0},
    )
    if ncols == 1:
        ax = [ax]

    base_vals = total_st[basecasename]
    abs_vmax = max(
        (total_st[c].reindex(dfstates.index).fillna(0).max() for c in cases),
        default=0.0,
    )
    pct_diffs = {
        c: ((total_st[c] - base_vals) / base_vals * 100)
           .replace([float('inf'), float('-inf')], float('nan'))
        for c in list(cases.keys())[1:]
    }
    diff_absmax = max(
        (pct_diffs[c].abs().max()
         for c in pct_diffs if not pct_diffs[c].dropna().empty),
        default=1.0,
    )

    for col, casename in enumerate(cases):
        _ax = ax[col]
        dfplot = dfstates.copy()

        if casename == basecasename:
            dfplot['val'] = base_vals.reindex(dfstates.index).fillna(0)
            _cmap, vmin, vmax = cmap_abs, 0, abs_vmax
            cbar_label = 'Annual demand [TWh]'
        else:
            dfplot['val'] = pct_diffs[casename].reindex(dfstates.index)
            _cmap, vmin, vmax = cmap_diff, -diff_absmax, diff_absmax
            cbar_label = f'Change in annual demand [%]'

        dfstates.plot(ax=_ax, facecolor='none', edgecolor='k', lw=0.2, zorder=10000)
        dfplot.plot(ax=_ax, column='val', cmap=_cmap, vmin=vmin, vmax=vmax, legend=False)

        # Value labels for states
        reeds.reedsplots.label_region_value(
            dfplot,
            ax=_ax,
            column='val',
            fmt='{:.0f}' if casename == basecasename else '{:+.0f}',
            text_kwargs={'fontsize': 7, 'ha': 'center', 'va': 'center', 'color': 'k'},
            pe_kwargs={'linewidth': 1.5, 'foreground': 'white'}
        )
        
        if col == 0 or col == 1:
            reeds.plots.addcolorbarhist(
                f=f, ax0=_ax, data=dfplot['val'].dropna().values,
                title=cbar_label, cmap=_cmap, vmin=vmin, vmax=vmax,
                orientation='horizontal', labelpad=2.25, histratio=0.,
                cbarwidth=0.05, cbarheight=0.85,
                cbarbottom=-0.05, cbarhoffset=0.,
                title_fontsize=18, ticklabel_fontsize=16
            )

        _ax.annotate(casename, (0.1, 1), xycoords='axes fraction', fontsize=18)
        _ax.axis('off')


    df_total = pd.DataFrame(total_st).reindex(dfstates.index)
    return f, ax, df_total

#%% Main



if __name__ == '__main__':
    #%% Argument inputs
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
        help='Case-path suffix to force as base case.',
    )
    parser.add_argument(
        '--output', '-o', choices=['png', 'ppt', 'pptx'], default='png',
        help='Output format (png or pptx)')
    parser.add_argument(
        '--year', '-y', type=str, default='2050',
        help='Model year for hourly demand plot (integer year or "last").',
    )
    parser.add_argument(
        '--weatheryear', '-w', type=str, default=None,
        help=(
            'Weather year(s) to plot (single year or comma/space-delimited list, e.g., '
            '"2012" or "2007,2012"). Defaults to GSw_HourlyWeatherYears from the first case.'
        ),
    )
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

    #%% Create output container
    suffix = args.output.strip('.')
    if suffix in ['pdf', 'png']:
        savepath = os.path.join(firstcasepath, 'outputs', 'comparisons','inputs')
        os.makedirs(savepath, exist_ok=True)

        def saveit(savename):
            outpath = os.path.join(savepath, savename.lower().replace(' ', '-') + f'.{suffix}')
            plt.savefig(outpath)
            print(os.path.basename(outpath))
            if mpl.interactive:
                plt.show()

    elif suffix in ['ppt', 'pptx']:
        savepath = os.path.join(firstcasepath, 'outputs', 'comparisons', 'inputs', 'inputs.pptx')
        prs = reeds.report_utils.init_pptx()
        def saveit(savename, **kwargs):
            reeds.report_utils.add_to_pptx(savename, prs=prs, **kwargs)
            if mpl.interactive:
                plt.show()

    try:
        year = int(args.year)
    except ValueError:
        year = args.year

    if args.weatheryear is None:
        sw = reeds.io.get_switches(firstcasepath)
        selected_weatheryears = sw.GSw_HourlyWeatherYears
    else:
        selected_weatheryears = _parse_weatheryears(args.weatheryear)

    try:
        f, ax = plot_hourly_demand_profiles(
            cases,
            colors,
            year=year,
            weatheryear=selected_weatheryears,
        )
        saveit(f'Demand hourly profile {selected_weatheryears}')
    except Exception as e:
        print(traceback.format_exc())
    
    for region_label, region_list in hourly_regions.items():
        try:
            f, ax = plot_hourly_demand_profiles(
                cases,
                colors,
                year=year,
                weatheryear=selected_weatheryears,
                region=region_list,
            )
            saveit(f'Demand hourly profile {selected_weatheryears} {region_label}')
        except Exception as e:
            print(traceback.format_exc())
    
    try:
        f, ax = plot_demand_yearbymonth(
            cases,
            colors,
            year=year,
            weatheryear=selected_weatheryears,
        )
        saveit(f'Demand by year and month {year}')
    except Exception as e:
        print(traceback.format_exc())
    
    try:
        f_modelyear, _, _ = plot_peak_and_total_load(
            cases,
            colors,
            weatheryear=selected_weatheryears,
        )
        saveit(f'Demand by year')
    except Exception as e:
        print(traceback.format_exc())
    
    try:
        f_peak, _, _ = plot_regional_peak_demand_maps(
            cases,
            year=year,
        )
        saveit(f'Demand peak by region {year}')
    except Exception as e:
        print(traceback.format_exc())

    try:
        f_total, _, _ = plot_regional_total_demand_maps(
            cases,
            colors,
            year=year,
            weatheryear=selected_weatheryears,
        )
        saveit(f'Demand total by region {year}')
    except Exception as e:
        print(traceback.format_exc())

    #%% Save the powerpoint file if necessary
    if suffix in ['ppt', 'pptx']:
        print(f'\ninput_plots.py results saved to:\n{savepath}')
        prs.save(savepath)