import sys
import shapely
import numpy as np
import pandas as pd
import geopandas as gpd
from pathlib import Path
import matplotlib as mpl
from typing import Literal
import matplotlib.pyplot as plt
from matplotlib import patheffects as pe
from tqdm import tqdm
sys.path.append(str(Path(__file__).parent.parent))
import reeds


#   #### ##    ## ########  ##     ## ########  ######  
#    ##  ###   ## ##     ## ##     ##    ##    ##    ## 
#    ##  ####  ## ##     ## ##     ##    ##    ##       
#    ##  ## ## ## ########  ##     ##    ##     ######  
#    ##  ##  #### ##        ##     ##    ##          ## 
#    ##  ##   ### ##        ##     ##    ##    ##    ## 
#   #### ##    ## ##         #######     ##     ######  


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


#    #######  ##     ## ######## ########  ##     ## ########  ######  
#   ##     ## ##     ##    ##    ##     ## ##     ##    ##    ##    ## 
#   ##     ## ##     ##    ##    ##     ## ##     ##    ##    ##       
#   ##     ## ##     ##    ##    ########  ##     ##    ##     ######  
#   ##     ## ##     ##    ##    ##        ##     ##    ##          ## 
#   ##     ## ##     ##    ##    ##        ##     ##    ##    ##    ## 
#    #######   #######     ##    ##         #######     ##     ######  

def plot_cap_gen_hist(
    cases,
    casebase=None,
    nicelabels=None,
    colors=None,
    t=2050,
    tstart=2020,
    techs=[
        'UPV',
        'Gas-CC',
        'Onshore Wind',
        'Gas-CT',
        'Nuclear',
        'Battery',
        'Offshore Wind',
        'Coal-CCS',
        'Gas-CC-CCS',
        'Coal',
        'Nuclear-SMR',
    ],
    numbins=71,
    plotwidth=2,
    histwidth=None,
    legend=False,
):
    """
    Vertical histograms for generation capacity [GW] in final solve year
    x axis = scenarios (sample groups)
    subplots (columns) = technologies

    Args:
        cases: Dictionary of lists of ReEDScase objects with caseprefix keys
        casebase: ReEDScase of base case (if not provided, the first sample is used)
        nicelabels: Dictionary of caseprefix keys to nice labels used in plot
        colors: Dictionary of nice label keys to colors used in plot
        plotwidth: Subplot width [inches]
        histwidth: Histogram width [inches]. If provided, overrides plotwidth.
        techs: int or list of tech name strings.
            If an int, plot the top {techs} techs by average capacity.
            If a list of strings, must match postprocessing/tech_aggregation.csv.
    """
    ## Parse inputs
    if nicelabels is None:
        nicelabels = dict(zip(cases.keys(), cases.keys()))
    if colors is None:
        colors = reeds.plots.rainbowmapper(nicelabels)
    if casebase is None:
        casebase = cases[list(cases.keys())[0]][0]
    if histwidth:
        plotwidth = histwidth * len(cases)
    ## Get data
    dictplot = {}
    for caseprefix, plotcases in cases.items():
        dictplot[caseprefix] = pd.concat({
            i: (
                case.cap
                .loc[case.cap.t==t]
                .groupby('i').Value.sum()
                .rename('GW')
                / 1e3
            )
            for i, case in enumerate(plotcases)
        }, axis=1)

    dfplot = pd.concat(dictplot, axis=1, names=('caseprefix','sample'))
    ## Simplify techs
    dfplot.index = reeds.reedsplots.simplify_techs(dfplot.index)
    dfplot = dfplot.groupby('i').sum()

    dfstart = (
        casebase.cap
        .loc[casebase.cap.t==tstart]
        .groupby('i').Value.sum()
        .rename('GW') / 1e3
    )

    ## Take the top techs by capacity if desired
    if isinstance(techs, int):
        techs = dfplot.mean(axis=1).nlargest(techs).index.tolist()

    ### Plot it
    ymin = 0.
    ymax = dfplot.loc[techs].max().max()
    bins = np.linspace(ymin, ymax, numbins)
    nrows = 1
    ncols = len(techs)

    plt.close()
    f,ax = plt.subplots(
        nrows, ncols, sharex='row', sharey='row', figsize=(plotwidth*ncols, 2.5),
        gridspec_kw={'wspace':0.3},
        dpi=300,
    )
    for col, tech in enumerate(techs):
        _ax = ax[col]
        _ax.set_title(tech, weight='bold', fontsize='x-large')
        for x, caseprefix in enumerate(cases):
            df = dfplot[caseprefix].loc[tech].fillna(0)
            ## Histogram
            hist_val, hist_y = np.histogram(df.values, bins=bins)
            height = hist_y[1] - hist_y[0]
            ax[col].barh(
                y=hist_y[:-1],
                width=(hist_val / max(hist_val) * 0.9),
                height=height,
                align='edge',
                left=x,
                color=colors[nicelabels[caseprefix]],
            )
        ## Starting capacity
        ax[col].axhline(dfstart.get(tech,0), c='k', ls='--', lw=0.75)
        ## Formatting
        ax[col].set_xticks(range(len(cases)))
        ax[col].set_xticklabels(
            [nicelabels.get(caseprefix,caseprefix) for caseprefix in cases],
            rotation=90, weight='bold',
        )
        colorlist = [colors[nicelabels[c]] for c in cases]
        for x, xtick in enumerate(ax[col].get_xticklabels()):
            xtick.set_color(colorlist[x])

    ## Formatting
    ax[0].set_ylabel(f'Capacity, {t} [GW]')
    ax[0].set_ylim(0)
    ax[0].yaxis.set_major_locator(mpl.ticker.MultipleLocator(400))
    ax[0].yaxis.set_minor_locator(mpl.ticker.MultipleLocator(100))
    ax[0].set_xlim(-0.15, len(cases))
    ## Legend
    if legend:
        handles = [
            mpl.patches.Patch(
                facecolor=colors[nicelabels[c]], edgecolor='none',
                label=nicelabels.get(c,c)
            )
            for c in cases
        ]
        ax[-1].legend(
            handles=handles, frameon=False, loc='upper left',
            bbox_to_anchor=(1,1.1), fontsize='x-large',
            handletextpad=0.3, handlelength=0.7,
        )
    reeds.plots.despine(ax)
    return f, ax, dfplot.loc[techs]


def plot_cap_trans_hist(
    cases,
    casebase=None,
    nicelabels=None,
    colors=None,
    level='transreg',
    t=2050,
    tstart=2020,
    binstep=1,
    plotwidth=1.45,
    histwidth=None,
    regioncolors=['k','0.7'],
):
    ## Parse inputs
    if nicelabels is None:
        nicelabels = dict(zip(cases.keys(), cases.keys()))
    if colors is None:
        colors = reeds.plots.rainbowmapper(nicelabels)
    if casebase is None:
        casebase = cases[list(cases.keys())[0]][0]
    if histwidth:
        plotwidth = histwidth * len(cases)
    ## Get data
    hierarchy = casebase.hierarchy
    dfmap = casebase.dfmap
    baseline = (
        casebase.tran_out.loc[casebase.tran_out.t==tstart]
        .groupby(['r','rr'], as_index=False).Value.sum()
    )
    baseline['level'] = baseline.r.map(hierarchy[level])
    baseline['levell'] = baseline.rr.map(hierarchy[level])
    baseline = baseline.loc[baseline.level != baseline.levell].copy()
    baseline['interface'] = baseline.apply(
        lambda row: '|'.join(sorted([row.level, row.levell])),
        axis=1,
    )
    baseline = baseline.groupby('interface').Value.sum().rename('GW') / 1e3

    dfplot = {}
    for caseprefix, plotcases in cases.items():
        df = pd.concat(
            {
                i: case.tran_out.loc[
                    case.tran_out.t==t
                ].groupby(['r','rr']).Value.sum()
                for i, case in enumerate(plotcases)
            },
            names=('case',),
        ).reset_index()
        df['level'] = df.r.map(hierarchy[level])
        df['levell'] = df.rr.map(hierarchy[level])
        df = df.loc[df.level != df.levell].copy()
        df['interface'] = df.apply(
            lambda row: '|'.join(sorted([row.level, row.levell])),
            axis=1,
        )
        df = df.groupby(['interface','case']).Value.sum().rename('GW') / 1e3
        dfplot[caseprefix] = df
    dfplot = pd.concat(dfplot, names=('caseprefix',))

    ## Sort the interfaces from west to east
    interfaces_unsorted = dfplot.index.get_level_values('interface').unique()
    interfaces = {}
    for i in interfaces_unsorted:
        region, regionn = i.split('|')
        interfaces[i] = dfmap[level].loc[[region,regionn]].dissolve().bounds.minx.squeeze()
    interfaces = pd.Series(interfaces).sort_values().index.values

    ymax = dfplot.max()
    bins = np.arange(0, ymax+0.1, binstep)
    ncols = len(interfaces)
    nrows = 2

    plt.close()
    f,ax = plt.subplots(
        nrows, ncols, sharex='row', sharey='row', figsize=(plotwidth*ncols, 3),
        gridspec_kw={'hspace':0.0, 'height_ratios':[0.5, 1]},
        dpi=300,
    )
    for col, interface in enumerate(interfaces):
        ### Maps on top
        dfmap[level].plot(ax=ax[0,col], facecolor='0.99', edgecolor='0.75', lw=0.2)
        dfmap[level].loc[[interface.split('|')[0]]].plot(
            ax=ax[0,col], facecolor=regioncolors[0], edgecolor='w', lw=0.5)
        dfmap[level].loc[[interface.split('|')[1]]].plot(
            ax=ax[0,col], facecolor=regioncolors[1], edgecolor='w', lw=0.5)
        ax[0,col].axis('off')
        ax[0,col].patch.set_facecolor('none')
        ### Data
        row = 1
        for x, caseprefix in enumerate(cases):
            df = dfplot.loc[caseprefix].loc[interface]
            ## Histogram
            hist_val, hist_y = np.histogram(df.values, bins=bins)
            height = hist_y[1] - hist_y[0]
            ax[row,col].barh(
                y=hist_y[:-1],
                width=(hist_val / max(hist_val) * 0.9),
                height=height,
                align='edge',
                left=x,
                color=colors[nicelabels[caseprefix]],
            )
        ax[row,col].axhline(baseline[interface], c='k', ls='--', lw=0.75)
    ## Formatting
    ax[1,0].set_ylabel(f'Interface capacity, {t} [GW]')
    ax[1,0].yaxis.set_major_locator(mpl.ticker.MultipleLocator(20))
    ax[1,0].yaxis.set_minor_locator(mpl.ticker.MultipleLocator(10))
    ax[1,0].set_ylim(0)
    ax[1,0].set_xlim(-0.15, len(cases))

    reeds.plots.despine(ax)
    for col, interface in enumerate(interfaces):
        ax[1,col].set_xlabel(None)
        ax[0,col].annotate(
            interface.replace('|', '\n'),
            (0.05, 1.0), xycoords='axes fraction',
            va='bottom', fontsize=10,
        )
        ax[1,col].set_xticks(range(len(cases)))
        ax[1,col].set_xticklabels(
            [nicelabels.get(caseprefix,caseprefix) for caseprefix in cases],
            rotation=90, weight='bold',
        )
        _colors = [colors[nicelabels[c]] for c in cases]
        for x, xtick in enumerate(ax[1,col].get_xticklabels()):
            xtick.set_color(_colors[x])
    return f, ax, dfplot


def plot_scatter_everything(
    plotcases,
    corr_method:Literal['pearson','kendall','spearman']='spearman',
    zoom=True,
    t=2050,
    tstart=2020,
    cmap=plt.cm.coolwarm,
    cmin=-0.8,
    cmax=0.8,
    figscale=1.3,
):
    """
    Scatter plot of many outputs against many inputs, colored by correlation coefficient
    """
    cost_techs = [
        {'tech_cost': 'battery_li', 'tech_cap':'Storage', 'label':'Battery'},
        {'tech_cost': 'upv_3', 'tech_cap':'PV', 'label':'PV'},
        {'tech_cost': 'wind-ons_5', 'tech_cap':'Wind', 'label':'Wind'},
        # {'tech_cost': 'wind-ofs_5', 'label':'Wind (offshore fixed)'},
        # {'tech_cost': 'geohydro_allkm_1', 'label':'Geothermal'},
        # {'tech_cost': 'coal-ccs_mod', 'label':'Coal+CCS'},
        {'tech_cost':'nuclear', 'tech_cap':'Nuclear', 'label':'Nuclear'},
        {'tech_cost':'gas-cc-ccs_mod', 'tech_cap':'Gas+CCS', 'label':'Gas+CCS'},
    ]
    x_labels = {
        'gasprice':'Gas price [$/MMBtu]',
        'demand':'Demand [PWh]',
        'sc_wind':'Wind avail [TW]',
        'cost_Wind':'Wind cost [$/kW]',
        'cost_PV':'PV cost [$/kW]',
        'cost_Battery':'Battery cost [$/kW]',
        'cost_Nuclear':'Nuclear cost [$/kW]',
        'cost_Gas+CCS':'Gas+CCS cost [$/kW]',
    }
    cap_techs = {
        'PV': ['UPV'],
        'Wind': ['Onshore Wind'],
        'Storage': ['Battery', 'Pumped-Hydro'],
        'Nuclear': ['Nuclear', 'Nuclear-SMR'],
        'Gas+CCS': ['Gas-CC-CCS'],
        'Gas': ['Gas-CT', 'Gas-CC'],
    }
    ycols = (
        []
        + [f'cap_{i}' for i in cap_techs]
        + ['scoe', 'npv', 'co2']
    )
    ylabels = {
        'cap_PV': 'PV',
        'cap_Wind': 'Wind',
        'cap_Storage': 'Storage',
        'cap_Nuclear': 'Nuclear',
        'cap_Gas+CCS': 'Gas+CCS',
        'cap_Gas': 'Gas',
        'npv': 'NPC\n[$trillion]',
        'scoe': 'SCOE\n[$/MWh]',
        'co2': 'CO' + r'$\bf{_2}$' + '\n[GT]',
    }
    xcols = [
        'cost_PV',
        'cost_Wind',
        'cost_Battery',
        'cost_Nuclear',
        'cost_Gas+CCS',
        'gasprice',
        'demand',
        'sc_wind',
    ]
    norm = mpl.colors.Normalize(vmin=cmin, vmax=cmax)
    co2years = range(2025,2051)

    nrows = len(ycols)
    ncols = len(xcols)

    ## Capacity
    for case in plotcases:
        case.capagg = case.cap.copy()
        case.capagg.i = reeds.reedsplots.simplify_techs(case.capagg.i)
        case.capagg = case.capagg.groupby(['t','i']).Value.sum()
    dfcap = pd.Series({
        (techlabel, i): (
            case.capagg.loc[t].reindex(techgroup).sum()
            - case.capagg.loc[tstart].reindex(techgroup).sum()
            # case.cap.loc[case.cap.t==t].groupby('i').Value.sum()
            # - case.cap.loc[case.cap.t==tstart].groupby('i').Value.sum()
        ) / 1e3
        for i, case in enumerate(plotcases)
        for techlabel, techgroup in cap_techs.items()
    }).clip(lower=0).unstack(level=0)
    dfcap.columns = 'cap_' + dfcap.columns
    ## More outputs
    dfnpv = pd.Series(
        {i: case.npv.sum() for i, case in enumerate(plotcases)},
        name='npv',
    ) / 1e3
    dfscoe = pd.Series(
        {i: case.scoe.loc[t].sum() for i, case in enumerate(plotcases)},
        name='scoe',
    )
    dfco2 = pd.Series(
        {
            i: (
                case.emit_nat.loc[(case.emit_nat.etype=='process') & (case.emit_nat.e=='CO2')]
                .set_index('t').Value.reindex(co2years).interpolate('index').sum()
                / 1e9
            )
            for i, case in enumerate(plotcases)
        },
        name='co2',
    )
    ### x-axis variables
    xdata = pd.concat({
        'gasprice': pd.Series({
            i: case.fprice.groupby('t')['naturalgas'].mean().loc[t]
            for i, case in enumerate(plotcases)
        }),
        'demand': pd.Series({
            i: case.demand_rt.groupby('t').sum().loc[t] / 1e3
            for i, case in enumerate(plotcases)
        }),
        'sc_wind': pd.Series({
            i: case.supplycurve.loc['wind-ons'].sum() / 1e3
            for i, case in enumerate(plotcases)
        }),
    }, axis=1)
    ### Generation capex costs
    costdata = pd.concat({
        f"cost_{cost_tech['label']}": pd.Series({
            i: case.capcost.loc[t,cost_tech['tech_cost']]
            for i, case in enumerate(plotcases)
        })
        for cost_tech in cost_techs
    }, axis=1)
    xdata = pd.concat([xdata, costdata], axis=1)
    # ylabels = {}
    # for cost_tech in cost_techs:
    #     sep = ' ' if cost_tech['label'] in ['Battery', 'PV', 'Wind (land)'] else '\n'
    #     ylabels[cost_tech['label']] = f"{cost_tech['label']}{sep}cost [$/kW]"
    ## Combine
    dfplot = pd.concat([dfcap, dfnpv, dfscoe, dfco2, xdata], axis=1)
    # ## Get the y ranges
    # ymax = ydata.max() + (0 if zoom else 100)
    # ymin = ydata.min()
    # yspan = ymax - ymin
    ### Plot it
    plt.close()
    f,ax = plt.subplots(
        nrows, ncols, figsize=(ncols*figscale, nrows*figscale), sharex='col', sharey='row',
        # gridspec_kw={'height_ratios':(yspan.values if zoom else ymax.values)},
    )
    for row, ycol in enumerate(ycols):
        for col, xcol in enumerate(xcols):
            corrcoef = dfplot[ycol].corr(dfplot[xcol], method=corr_method)
            color = '0.7' if abs(corrcoef) <= 0.2 else cmap(norm(corrcoef))
            ax[row,col].scatter(
                dfplot[xcol], dfplot[ycol], marker='o', lw=0, s=20,
                color=color, alpha=0.2,
            )
            for c, a, p in [(color, 1, 1), ('k', 0.2, 0)]:
                ax[row,col].annotate(
                    f"{corrcoef:+.2f}",
                    (0.95, 0.95), xycoords='axes fraction',
                    ha='right', va='top', fontsize='x-large',
                    path_effects=(
                        [pe.withStroke(linewidth=3.0, foreground='w', alpha=0.9)]
                        if p else []
                    ),
                    # color='k',
                    color=c, alpha=a,
                )
            ## Formatting
            if col == 0:
                ax[row,col].set_ylabel(ylabels.get(ycol,ycol))
            if row == nrows - 1:
                ax[row,col].set_xlabel(
                    x_labels.get(xcol,xcol), rotation=45, rotation_mode='anchor', ha='right',
                )
            if xcol == 'cost_Nuclear':
                # ax[-1,col].xaxis.set_major_locator(mpl.ticker.MultipleLocator(3000))
                ax[-1,col].xaxis.set_major_locator(mpl.ticker.FixedLocator([3000, 5500]))
    ## Formatting
    ax[2,0].annotate(
        f'Capacity additions through {t} [GW]', (-0.95, -0.075), xycoords='axes fraction',
        ha='center', va='center', annotation_clip=False,
        rotation=90, weight='bold', fontsize='xx-large',
    )
    ax[-1,0].annotate(
        f'{t}:', (-0.35, -0.8), xycoords='axes fraction',
        ha='right', va='top', annotation_clip=False,
        weight='bold', fontsize='x-large',
    )
    if not zoom:
        ax.set_xlim(0)
        ax.set_ylim(0)
    reeds.plots.despine(ax)
    return f, ax, dfplot
