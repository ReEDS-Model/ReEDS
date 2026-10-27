import sys
import shapely
import pandas as pd
import geopandas as gpd
from pathlib import Path
import matplotlib as mpl
from typing import Literal
import matplotlib.pyplot as plt
# from matplotlib import patheffects as pe
from tqdm import tqdm
sys.path.append(str(Path(__file__).parent.parent))
import reeds


def plot_demand_lines(
    plotcases:list,
    level='st',
    ncols=8,
    tstart=2020,
    figsize=(11,6),
    color='C7',
    alpha=0.5,
    bins=21,
):
    """
    Sum of input electricity demand
    Lines with vertical histograms at the end for each region in level [TWh]
    """
    hierarchy = plotcases[0].hierarchy
    r2region = hierarchy[level]
    regions = sorted(hierarchy[level].unique())
    nrows, ncols, coords = reeds.plots.get_coordinates(regions, ncols=ncols)
    dfplot = pd.concat({
        i: (
            case.demand_rt
            .rename(r2region, axis=0, level='r')
            .groupby(['r','t']).sum()
        )
        for i, case in enumerate(plotcases)
    }, axis=1).loc[:, tstart:, :]

    ### Plot it
    plt.close()
    f,ax = plt.subplots(
        nrows, ncols, figsize=figsize, sharex=True,
        gridspec_kw={'wspace':0.5},
    )
    for r in tqdm(regions):
        _ax = ax[coords[r]]
        df = dfplot.loc[r]
        ## Background
        _ax.fill_between(
            df.index, df.max(axis=1), df.min(axis=1),
            color=color, alpha=alpha, lw=0,
        )
        ## Lines
        df.plot(
            ax=_ax, legend=False,
            lw=0.5, color='k', alpha=0.25,
        )
        ## Histogram
        reeds.plots.hist_last(
            _ax, df, color=color, bins=bins, alpha=alpha,
            xpad=1, xscale=4,
        )
        ## Formatting
        _ax.annotate(
            r, (0.05, 0.05), xycoords='axes fraction', va='bottom', weight='bold',
        )
        _ax.set_xlabel(None)
        _ax.set_ylim(0)
    _ax.xaxis.set_major_locator(mpl.ticker.MultipleLocator(20))
    _ax.xaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(2))
    ax[-1,0].set_ylabel('Electricity demand [TWh]', y=0, va='bottom', ha='left')
    reeds.plots.despine(ax)
    plt.draw()
    reeds.plots.shorten_years(_ax)
    return f, ax, dfplot


def plot_fuelprice_lines(
    plotcases:list,
    fuel:Literal['gas','coal','uranium','h2']='gas',
    tstart=2020,
    color='C7',
    bins=21,
    alpha=0.5,
):
    """
    All-region unweighted average fuel price
    Lines with vertical historgram at end [$/MMBtu]
    """
    colname = {'gas':'naturalgas', 'h2':'h2fuel'}
    dfplot = pd.concat({
        i: case.fprice.groupby('t')[colname.get(fuel,fuel)].mean()
        for i, case in enumerate(plotcases)
    }, axis=1).loc[tstart:]

    ### Plot it
    plt.close()
    f,ax = plt.subplots(figsize=(2, 3.75))
    ## Background
    ax.fill_between(
        dfplot.index, dfplot.max(axis=1), dfplot.min(axis=1),
        color=color, alpha=alpha, lw=0,
    )
    ## Lines
    dfplot.plot(
        ax=ax, legend=False,
        lw=0.5, color='k', alpha=0.25,
    )
    ## Histogram
    reeds.plots.hist_last(
        ax, dfplot, color=color, bins=bins, alpha=alpha,
        xpad=1, xscale=4,
    )
    ## Formatting
    ax.set_ylim(0)
    ax.set_ylabel(f'{fuel.title()} price [$/MMBtu]')
    ax.set_xlabel(None)
    ax.xaxis.set_minor_locator(mpl.ticker.MultipleLocator(10))
    reeds.plots.despine(ax)
    return f, ax, dfplot


def plot_capcost_lines(
    plotcases:list,
    labels={
        'upv_3': 'UPV',
        'wind-ons_3': 'Wind',
        'battery_li': 'Battery',
        # 'nuclear': 'Nuclear',
        # 'gas-cc': 'Gas-CC',
        # 'geothermal': 'Geothermal',
        # 'hydro': 'Hydropower',
    },
    tstart=2020,
    bins=31,
    alpha=0.5,
):
    """
    Capex cost for technologies specified by labels
        keys = technology name used in ReEDS
        values = "nice" name used in tech_style.csv
    Lines with vertical historgram at end [$/MMBtu]
    """
    colors_tech = reeds.io.get_plot_formatting()['tech_color'].squeeze(1)
    dfplot = pd.concat(
        {
            # i: (
            #     case.plantcharout.set_index(['variable','*i','t'])
            #     .loc['capcost'].value.unstack('*i').rename_axis('i', axis=1)
            #     [list(labels.keys())]
            #     # * inflator
            #     / 1e3
            #     .rename(columns=labels)
            # )
            i: case.capcost.rename(columns=labels)
            for i, case in enumerate(plotcases)
        },
        axis=1, names=['s','i'],
    ).reorder_levels(['i','s'], axis=1).loc[tstart:]

    ### Plot it
    ncols = len(labels)
    plt.close()
    f,ax = plt.subplots(1, ncols, sharex=True, sharey=True, figsize=(2*ncols, 3.75))
    for col, tech in enumerate(labels.values()):
        _ax = ax[col]
        df = dfplot[tech]
        ## Background
        _ax.fill_between(
            df.index, df.max(axis=1), df.min(axis=1),
            color=colors_tech[tech], alpha=alpha, lw=0,
        )
        ## Lines
        df.plot(
            ax=_ax, legend=False,
            lw=0.5, color='k', alpha=0.1,
        )
        ## Histogram
        reeds.plots.hist_last(
            _ax, df, color=colors_tech[tech], bins=bins, alpha=alpha,
            xpad=1, xscale=4,
        )
        ## Formatting
        _ax.set_title(tech, color=colors_tech[tech], weight='bold')
        _ax.set_xlabel(None)

    ax[0].xaxis.set_major_locator(mpl.ticker.MultipleLocator(10))
    ax[0].xaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(2))
    ax[0].set_ylabel('Capex cost [$/kW]')
    ax[0].set_ylim(0)
    ax[0].yaxis.set_major_locator(mpl.ticker.MultipleLocator(500))
    ax[0].yaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(5))
    reeds.plots.despine(ax)
    plt.draw()
    reeds.plots.shorten_years(ax[0])
    return f, ax, dfplot


def map_supplycurve_diff(
    plotcases,
    casebase,
    tech='upv',
    dfmap=None,
    cmap=plt.cm.RdBu_r,
):
    """
    Difference map [GW] between sample supply curves and casebase
    """
    if dfmap is None:
        dfmap = plotcases[0].dfmap
    dfplot = pd.concat(
        {
            i: case.supplycurve
            for i, case in enumerate(plotcases)
        },
        axis=1,
    )
    samples = dfplot.columns.values
    dfplot['geometry'] = dfplot.index.get_level_values('r').map(dfmap['r'].geometry)
    dfplot = gpd.GeoDataFrame(dfplot, crs=dfmap['r'].crs)

    ### Get coordinates
    nrows, ncols, coords = reeds.plots.get_coordinates(samples, aspect=1.2)
    scale = 1

    bounds = dfmap['country'].bounds.squeeze(0)
    xspan = bounds.maxx - bounds.minx
    yspan = bounds.maxy - bounds.miny

    ### Plot relative difference
    dfstates = dfmap['st'].copy()
    dfstates.geometry = dfstates.simplify(1000)

    central = casebase.supplycurve.loc[tech].rename('val')
    geom = dfmap['r'].geometry.simplify(1000)
    # vmin = dfplot.loc[tech, samples].min().min()
    # vmin = 0
    # vmax = dfplot.loc[tech, samples].max().max()
    vmin, vmax = -100, 100

    plt.close()
    f,ax = plt.subplots(figsize=(ncols*scale, nrows*scale*0.8))
    for sample in tqdm(samples):
        row, col = coords[sample]
        ## Data
        df = dfplot.loc[tech, [sample, 'geometry']].rename(columns={sample:'val'}).copy()
        df.val = (df.val / central - 1) * 100
        df.geometry = geom.map(
            lambda x: shapely.affinity.translate(x, xoff=xspan*col, yoff=-yspan*row)
        )
        df.plot(ax=ax, column='val', cmap=cmap, vmin=vmin, vmax=vmax)
        ## States
        _dfstates = dfstates.copy()
        _dfstates.geometry = _dfstates.geometry.map(
            lambda x: shapely.affinity.translate(x, xoff=xspan*col, yoff=-yspan*row)
        )
        _dfstates.plot(ax=ax, facecolor='none', edgecolor='k', lw=0.1)
        # ax.annotate(
        #     sample,
        #     (x + xspan * col, y - yspan * row),
        #     ha='center', va='center',
        # )
    ax.set_title(f'{tech} availability relative to central case')
    ax.axis('off')
    return f, ax, dfplot
