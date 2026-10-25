import sys
import pandas as pd
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
