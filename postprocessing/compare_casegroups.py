"""
Things to try:
- Identify descending/ascending pairs of high/low values and shade between them (to avoid
  overemphasizing the max and min values)
"""

#%% Imports
import os
import sys
import shapely
import cmocean
import argparse
import numpy as np
import pandas as pd
import geopandas as gpd
from pathlib import Path
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import patheffects as pe
from tqdm import tqdm

sys.path.append(str(Path(__file__).parent.parent))
import reeds

reeds.plots.plotparams()


#%% Fixed inputs
keep_incomplete = False
interactive = False


#%% Argument inputs
parser = argparse.ArgumentParser(
    description='Compare groups of Monte Carlo samples',
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
)
parser.add_argument(
    'caselist', type=str, nargs='+',
    help=(
        'space-delimited list of dfcases to plot, OR csv file of dfcases (both with glob '
        'controls included). The first case is treated as the base case '
        'unless a different one is provided via the --basecase/-b argument.'
    ))
parser.add_argument(
    '--casenames', '-n', type=str, default='',
    help='comma-delimited list of shorter case names to use in plots')
parser.add_argument(
    '--titleshorten', '-s', type=str, default='',
    help='characters to cut from start of case name (only used if no casenames)')
parser.add_argument(
    '--basepath', '-b', type=str, default='',
    help='Substring of case path to use as default (if empty, uses first case in list)')
parser.add_argument(
    '--write', '-w', choices=['pdf', 'png', 'ppt', 'pptx'], default='png',
    help='Output format (png or pptx)')


# #%% Inputs for testing
# caselist = [str(Path(reeds.io.reeds_path,'postprocessing','example.csv'))]
# casenames = ''
# titleshorten = ''
# basepath = str(Path('~/Projects/Uncertainty/runs/20250829/v20250829_mcK0_Central').expanduser())
# write = 'png'
# interactive = True

#%% Parse inputs
args = parser.parse_args()
caselist = args.caselist
casenames = args.casenames
write = args.write.strip('.')
try:
    titleshorten = int(args.titleshorten)
except ValueError:
    titleshorten = len(args.titleshorten)
if args.basepath == '':
    basepath = None
else:
    basepath = args.basepath
    if not Path(basepath).is_dir():
        print(f'{basepath=} does not exist; using first sample instead')
        basepath = None


#%%### Procedure
#%% Parse arguments
casepaths, nicelabels, colors = reeds.report_utils.parse_caseglobs(
    caselist,
    casenames,
    basepath,
    titleshorten,
    keep_incomplete=keep_incomplete,
)

#%% Create output container
if basepath is not None:
    savepath = Path(basepath, 'outputs', 'comparisons')
else:
    ## Put it in the first sample if no basepath is specified
    firstcase = casepaths[list(casepaths.keys())[0]][0]
    savepath = Path(firstcase, 'outputs', 'comparisons')

if write in ['pdf', 'png']:
    savepath.mkdir(parents=True, exist_ok=True)

    def saveit(savename):
        outpath = Path(savepath, savename.replace(' ', '') + f'.{write}')
        plt.savefig(outpath)
        print(outpath)
        if interactive:
            plt.show()

elif write in ['ppt', 'pptx']:
    label = ','.join(nicelabels.values()).replace(' ','')
    outpath = os.path.join(savepath, f'comparegroup-{label}.pptx')
    prs = reeds.report_utils.init_pptx()
    def saveit(savename, **kwargs):
        reeds.report_utils.add_to_pptx(savename, prs=prs, **kwargs)
        if interactive:
            plt.show()


#%% Colors
plot_settings = reeds.io.get_plot_formatting()
colors_tech = plot_settings['tech_color']


#%% Cases
# dfcases = pd.DataFrame(casepaths)
## Allow for different numbers of samples across dfcases
dfcases = pd.concat({k: pd.Series(v) for k,v in casepaths.items()}, axis=1)
dfcases.columns = dfcases.columns.rename('caseprefix')
dfcases = dfcases.stack().rename('path').dropna().reset_index(level='caseprefix')
dfcases['number'] = dfcases.path.map(lambda x: int(x.split('_')[-1].strip('MC')))
## Add central case
if basepath is not None:
    dfcases = pd.concat([
        dfcases,
        pd.DataFrame({'caseprefix':'central', 'path':basepath, 'number':0}, index=[0])
    ])
dfcases = dfcases.set_index(['caseprefix','number']).sort_index()
samples = [i for i in dfcases.index.get_level_values('number').unique() if i != 0]
## Instantiate the data containers
# dfcases['object'] = dfcases.path.map(lambda x: reeds.objects.ReEDScase(x))
# dfcases['object'] = [reeds.objects.ReEDScase(x) for x in dfcases.path]
# case
cases = {
    key: [reeds.objects.ReEDScase(x) for x in caselist]
    for key, caselist in casepaths.items()
}


#%% Shared inputs
basecase = dfcases.iloc[0].name
sw = reeds.io.get_switches(basepath)
inflatable = reeds.io.get_inflatable()
dollaryear_reeds = 2004
dollaryear_output = 2024
inflator = inflatable[dollaryear_reeds, dollaryear_output]
hierarchy = reeds.io.get_hierarchy(basepath)
hierarchy['r'] = hierarchy.index
dfmap = reeds.io.get_dfmap(basepath)

scco2_pindyck = 290

### Historical emissions
try:
    ### EIA emissions https://www.eia.gov/totalenergy/data/monthly/
    ## https://www.eia.gov/totalenergy/data/browser/csv.php?tbl=T11.06
    baseline = pd.read_csv(
        # os.path.expanduser('~/Projects/Data/EIA/MER_T11_06.csv'),
        'https://www.eia.gov/totalenergy/data/browser/csv.php?tbl=T11.06',
        dtype={'Value':float}, na_values=['Not Available'],
    )

    baseline_elec = baseline.loc[
        baseline.Description == 'Total Energy Electric Power Sector CO2 Emissions'
    ].copy()
    baseline_elec['year'] = baseline_elec.YYYYMM.map(lambda x: int(str(x)[:4]))
    baseline_elec['month'] = baseline_elec.YYYYMM.map(lambda x: int(str(x)[4:]))

    baseline_emissions = baseline_elec.loc[baseline_elec.month==13,['year','Value']].set_index('year').Value
except Exception as err:
    print(err)

### State subplots
state_subplots = reeds.reedsplots.get_state_subplots()


#%%### Inputs

#%% Tech cost (wind, solar, batteries)
dictin_cap_cost = {}
for case, row in tqdm(dfcases.iterrows(), desc='cap_cost', total=len(dfcases)):
    try:
        dictin_cap_cost[case] = pd.read_csv(
            os.path.join(row.path, 'inputs_case', 'plantcharout.csv'),
            index_col=['variable','*i','t'],
        ).loc['capcost'].value.unstack('*i').rename_axis('i', axis=1) * inflator / 1e3
        dictin_cap_cost[case].columns = dictin_cap_cost[case].columns.str.lower()
    except FileNotFoundError as err:
        print(err)
        continue

#%% Siting availability
dictin_sc = {}
for case, row in tqdm(dfcases.iterrows(), desc='supplycurve', total=len(dfcases)):
    try:
        dictin_sc[case] = (
            pd.read_csv(os.path.join(row.path, 'inputs_case', 'rsc_combined.csv'))
            .rename(columns={'*i':'i'}).set_index('sc_cat').loc['cap']
            .groupby(['i','r']).value.sum()
            / 1e3
        ).reset_index()
        dictin_sc[case]['i'] = dictin_sc[case]['i'].str.strip('_0123456789')
        dictin_sc[case] = dictin_sc[case].groupby(['i','r']).value.sum()
    except FileNotFoundError as err:
        print(err)
        continue


#%%### Inputs plots
#%% Demand
for caseprefix in casepaths:
    f, ax, dfplot = reeds.mcplots.plot_demand_lines(cases[caseprefix])
    savename = f'demand-{nicelabels[caseprefix]}'
    saveit(savename)


#%% Fuel price
for caseprefix in casepaths:
    f, ax, dfplot = reeds.mcplots.plot_fuelprice_lines(cases[caseprefix])
    savename = f'gasprice-{nicelabels[caseprefix]}'
    saveit(savename)












#%% Capital cost
labels = {
    'upv_3': 'PV',
    'wind-ons_3': 'Wind',
    'battery_li': 'Battery',
    # 'nuclear': 'Nuclear',
    # 'Gas-CC',
    # 'Geothermal',
    # 'Hydro',
}
ncols = len(labels)
bins = 31

for caseprefix in casepaths:
    caseprefix_samples = sorted([s for (c,s) in dictin_cap_cost if c == caseprefix])
    dfplot = pd.concat(
        {
            sample: (
                dictin_cap_cost[caseprefix,sample][list(labels.keys())]
                .rename(columns=labels)
            )
            for sample in caseprefix_samples
        },
        axis=1, names=['s','i'],
    ).reorder_levels(['i','s'], axis=1).loc[tstart:]

    ### Plot it
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
    plt.savefig(
        os.path.join(savepath, f"capcost-{','.join(list(labels.values()))}-{caseprefix}.png")
    )
    plt.show()


#%% Supply curves
techs = ['upv', 'wind-ons']
for caseprefix in casepaths:
    caseprefix_samples = sorted([s for (c,s) in dictin_sc if c == caseprefix])
    dfplot = pd.concat(
        {
            sample: dictin_sc[caseprefix,sample]
            for sample in caseprefix_samples
        },
        axis=1,
    ).loc[techs]
    dfplot['geometry'] = dfplot.index.get_level_values('r').map(dfmap['r'].geometry)
    dfplot = gpd.GeoDataFrame(dfplot, crs=dfmap['r'].crs)

    ### Get coordinates
    nrows, ncols, coords = reeds.plots.get_coordinates(samples, aspect=1.2)
    print(nrows, ncols)
    scale = 1

    bounds = dfmap['country'].bounds.squeeze(0)
    xspan = bounds.maxx - bounds.minx
    yspan = bounds.maxy - bounds.miny

    ### Plot relative difference
    cmap = plt.cm.RdBu_r
    dfstates = dfmap['st'].copy()
    dfstates.geometry = dfstates.simplify(1000)

    for tech in techs:
        central = dictin_sc['central',0].loc[tech].rename('val')
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
        plt.savefig(os.path.join(savepath, f"supplycurve-{tech.replace('-','')}-{caseprefix}.png"))
        plt.show()










#%%
#%%
#%% Results
dictin_cap_r = {}
for case, row in tqdm(dfcases.iterrows(), desc='output capacity', total=len(dfcases)):
    ### Generation capacity
    try:
        dictin_cap_r[case] = reeds.io.read_output(row.path, 'cap', valname='MW')
    except FileNotFoundError as _err:
        # print(f'Missing {case}')
        continue
    ## Simplify techs
    dictin_cap_r[case].i = reeds.reedsplots.simplify_techs(dictin_cap_r[case].i)
    dictin_cap_r[case] = dictin_cap_r[case].groupby(['i','r','t'], as_index=False).MW.sum()

dictin_trans_r = {}
for case, row in tqdm(dfcases.iterrows(), desc='output transmission', total=len(dfcases)):
    ### Transmission capacity
    try:
        dictin_trans_r[case] = reeds.io.read_output(row.path, 'tran_out', valname='MW')
    except FileNotFoundError as _err:
        # print(f'Missing {case}')
        continue
    ## Add interregional info
    for level in ['st', 'transgrp', 'transreg', 'interconnect']:
        dictin_trans_r[case][f'inter_{level}'] = (
            dictin_trans_r[case].r.map(hierarchy[level])
            != dictin_trans_r[case].rr.map(hierarchy[level])
        ).astype(int)

dictin_gen_r = {}
for case, row in tqdm(dfcases.iterrows(), desc='output generation', total=len(dfcases)):
    ### Generation
    try:
        dictin_gen_r[case] = reeds.io.read_output(row.path, 'gen_ann', valname='TWh')
    except FileNotFoundError as _err:
        # print(f'Missing {case}')
        continue
    ## Simplify techs
    dictin_gen_r[case].i = reeds.reedsplots.simplify_techs(dictin_gen_r[case].i)
    dictin_gen_r[case] = dictin_gen_r[case].groupby(['i','r','t']).TWh.sum() / 1e6

val2sheet = reeds.io.get_report_sheetmap(basepath)
dictin_scoe = {}
for case, row in tqdm(dfcases.iterrows(), desc='output scoe', total=len(dfcases)):
    try:
        dictin_scoe[case] = (
            reeds.io.read_report(row.path, 'National Average Electricity', val2sheet)
            .pivot(index='year', columns='cost_cat', values='Average cost ($/MWh)').fillna(0)
        )
    except FileNotFoundError as _err:
        # print(f'Missing {case}')
        continue

dictin_npv = {}
for case, row in tqdm(dfcases.iterrows(), desc='output npv', total=len(dfcases)):
    try:
        dictin_npv[case] = (
            reeds.io.read_report(row.path, 'Present Value of System Cost', val2sheet)
            .set_index('cost_cat')['Discounted Cost (Bil $)']
        ).rename('billionUSD')
    except FileNotFoundError as _err:
        # print(f'Missing {case}')
        continue

dictin_emissions = {}
for case, row in tqdm(dfcases.iterrows(), desc='output emissions', total=len(dfcases)):
    try:
        dictin_emissions[case] = (
            reeds.io.read_output(row.path, 'emit_nat', valname='ton')
        )
        dictin_emissions[case] = (
            dictin_emissions[case]
            .set_index(['etype','e','t'])
            .groupby(['etype','e','t']).ton.sum()
            .unstack('etype').unstack('e')
        )
    except FileNotFoundError as _err:
        # print(f'Missing {case}')
        continue

central_health = {'cr':'ACS', 'model':'EASIUR'}
dictin_health = {}
dictin_health_central = {}
dictin_health_central_mort = {}
for case, row in tqdm(dfcases.iterrows(), desc='health damages', total=len(dfcases)):
    try:
        dictin_health[case] = (
            reeds.io.read_output(row.path, 'health_damages_caused_r.csv')
            .groupby(['year','pollutant','model','cr'])
            [['tons','md','damage_$','mortality']].sum()
        )
        dictin_health_central[case] = (
            dictin_health[case]
            .xs(central_health['cr'], level='cr')
            .xs(central_health['model'], level='model')
            .groupby('year').sum()
            ['damage_$']
            ### Inflate from dollaryear_reeds to dollaryear_output
            * inflator
        )
        dictin_health_central_mort[case] = (
            dictin_health[case]
            .xs(central_health['cr'], level='cr')
            .xs(central_health['model'], level='model')
            .groupby('year').sum()
            ['mortality']
        )
    except FileNotFoundError as _err:
        continue

# print(sorted(pd.concat(dictin_cap_r).i.unique()))
# print(sorted(pd.concat(dictin_gen_r).i.unique()))

# years = sorted(pd.concat(dictin_cap_r).t.unique())
years = sorted(dictin_cap_r[list(dictin_cap_r.keys())[0]].t.unique())




#%% Total number of samples
df = {}
for caseprefix in casepaths:
    caseprefix_samples = sorted([s for (c,s) in dictin_cap_r if c == caseprefix])
    df[nicelabels.get(caseprefix,caseprefix)] = len(caseprefix_samples)
df = pd.Series(df).sort_index()
print(df)
print(df.sum())


###### Results plots
#%% Regional capacity by technology for a single caseprefix

level = 'transreg'
tstart = 2020
alpha = 0.5
yaxis = 'shared'
ystep = {'major': 50, 'minor': 10}
ystep = {'major': 20, 'minor': 5}
ystep = {'major': 100, 'minor': 20}
binstep = 2

## Sort regions west to east
regions = dfmap[level].loc[hierarchy[level].unique()].bounds.minx.sort_values().index
ncols = len(regions)

techs = [
    'PV',
    'Wind',
    # 'Storage',
    'Nuclear',
    # 'Fossil',
    'Gas',
    'Coal',
    # 'Geothermal',
    # 'Hydro',
]
nrows = len(techs) + 1

for caseprefix in casepaths:
    caseprefix_samples = sorted([s for (c,s) in dictin_cap_r if c == caseprefix])
    dfplot = {}
    for region in regions:
        rs = hierarchy.loc[hierarchy[level]==region].index.values
        dfregion = {
            sample: (
                dictin_cap_r[caseprefix,sample]
                .loc[dictin_cap_r[caseprefix,sample].r.isin(rs)]
                .groupby(['i','t']).MW.sum()
                .rename('GW')
                / 1e3
            )
            for sample in caseprefix_samples
        }
        for tech in techs:
            dfplot[tech,region] = (
                pd.DataFrame(
                    {sample: dfregion[sample].get(tech, pd.Series(index=years))
                    for sample in caseprefix_samples}
                )
                .reindex(years).fillna(0).loc[tstart:]
            )

    dfplot = pd.concat(dfplot, names=('tech','region',))
    ymax = dfplot.max(axis=1).groupby('tech').max()
    if yaxis == 'shared':
        ymax = {tech: ymax.max() for tech in techs}
    bins = {tech: np.arange(0, ymax[tech]+0.1, binstep) for tech in techs}

    plt.close()
    f,ax = plt.subplots(
        nrows, ncols, sharex='row', sharey='row', figsize=(1.25*ncols, (nrows*1.5+0.5)),
        gridspec_kw={'hspace':0.1, 'height_ratios':[0.2]+[1/(nrows-1)]*(nrows-1)},
        dpi=300,
    )
    for col, region in enumerate(regions):
        ## Maps on top
        dfmap[level].plot(ax=ax[0,col], facecolor='0.99', edgecolor='0.75', lw=0.2)
        dfmap[level].loc[[region]].plot(ax=ax[0,col], facecolor='k', edgecolor='none')
        ax[0,col].axis('off')
        ax[0,col].patch.set_facecolor('none')
        ## Data
        # rs = hierarchy.loc[hierarchy[level]==region].index.values
        # dfregion = {
        #     case: (
        #         dictin_cap_r[case]
        #         .loc[dictin_cap_r[case].r.isin(rs)]
        #         .groupby(['i','t']).MW.sum()
        #         .rename('GW')
        #         / 1e3
        #     )
        #     for case in dictin_cap_r
        # }
        for _row, tech in enumerate(techs):
            row = _row + 1
            # df = (
            #     pd.DataFrame({case: dfregion[case].loc[tech] for case in dictin_cap_r})
            #     .reindex(years).fillna(0).loc[tstart:]
            # )
            df = dfplot.loc[tech].loc[region]
            ## Background
            ax[row,col].fill_between(
                df.index, df.max(axis=1), df.min(axis=1),
                color=colors_tech[tech], alpha=alpha, lw=0,
            )
            ## Lines
            df.plot(
                ax=ax[row,col], legend=False,
                lw=0.5, color='k', alpha=0.25,
            )
            ## Histogram
            reeds.plots.hist_last(
                ax[row,col], df, color=colors_tech[tech], bins=bins[tech], alpha=alpha,
                xpad=1, xscale=4,
            )
    ## Formatting
    ymax = 0
    ax[1,0].set_title('Capacity [GW]', weight='bold', x=0, ha='left')
    for _row, tech in enumerate(techs):
        row = _row + 1
        ax[row,0].set_ylabel(f"{tech}")
        ax[row,0].yaxis.set_minor_locator(mpl.ticker.MultipleLocator(ystep['minor']))
        ax[row,0].yaxis.set_major_locator(mpl.ticker.MultipleLocator(ystep['major']))
        ymax = max(ymax, ax[row,0].get_ylim()[1])
    for _row, tech in enumerate(techs):
        ax[_row+1,0].set_ylim(0, ymax)

    for col, region in enumerate(regions):
        # ax[0,col].set_title(region)
        ax[-1,col].set_xlabel(None)
        ax[-1,0].xaxis.set_minor_locator(mpl.ticker.MultipleLocator(10))
        ax[-1,0].xaxis.set_major_locator(mpl.ticker.MultipleLocator(20))

    reeds.plots.despine(ax)
    savename = f"out_cap-line_{level}-{','.join(techs)}-{caseprefix}.png"
    print(savename)
    plt.savefig(os.path.join(savepath, savename))
    plt.show()


#%% National capacity for all scenarios
dictplot = {}
for caseprefix in casepaths:
    caseprefix_samples = sorted([s for (c,s) in dictin_cap_r if c == caseprefix])
    # print(f'{caseprefix}: {(len(caseprefix_samples))}')
    dictplot[caseprefix] = pd.concat({
        sample: (
            dictin_cap_r[caseprefix,sample]
            .groupby(['i','t']).MW.sum()
            .rename('GW')
            / 1e3
        )
        for sample in caseprefix_samples
    }, axis=1)

dfplot = pd.concat(dictplot, axis=1, names=('caseprefix','sample'))

### Plot it
tstart = 2020
alpha = 0.1 # 0.5 when just plotting min/max range
techs = [
    'Gas',
    'PV',
    'Wind',
    'Nuclear',
    'Storage',
    'Coal+CCS',
    'Offshore wind',
    'Gas+CCS',
    'Coal',
    # 'Fossil',
    # 'Geothermal',
    # 'Hydro',
]
ymin = 0.
numbins = 71
xscale = 4.0
ymax = dfplot.loc[techs].max().max()
bins = np.linspace(ymin, ymax, numbins)
nrows = 1
ncols = len(techs)

plotcaseprefixes = [
    'v20250829_mcK0_MC_flat_state_IRA',
    'v20250829_mcK0_MC_flat_state_MC',
    'v20250829_mcK0_MC_flat_state_CAA0',
]
plotlabels = {
    **nicelabels,
    'v20250829_mcK0_MC_flat_state_MC': 'CurrentPol',
}

plotcaseprefixes = [
    'v20250829_mcK0_MC_flat_state_MC',
    'v20250829_mcK0_MC_flat_country',
    'v20250911_mcK0_MC_tri_state',
    'v20250922_mcK0_MC_tri_country',
]
plotlabels = nicelabels

print(
    dfplot.xs(2050,0,'t')
    [plotcaseprefixes]
    .mean(axis=1).sort_values(ascending=False)
    .rename('2050 capacity')
)
print(
    dfplot.xs(2050,0,'t').sub(dfplot.xs(2020,0,'t'), fill_value=0)
    [plotcaseprefixes]
    .mean(axis=1).sort_values(ascending=False)
    .rename('Capacity additions through 2050')
)


plt.close()
f,ax = plt.subplots(
    nrows, ncols, sharex='row', sharey='row', figsize=(1.7*ncols, 3.75),
    gridspec_kw={'wspace':0.3},
    dpi=300,
)
for col, tech in enumerate(techs):
    _ax = ax[col]
    _ax.set_title(tech, weight='bold', fontsize='x-large')
    for i, caseprefix in enumerate(plotcaseprefixes):
        df = dfplot[caseprefix].loc[tech].reindex(years).fillna(0)
        ## Background
        _ax.fill_between(
            df.index, df.max(axis=1), df.min(axis=1),
            color=colors[caseprefix], alpha=alpha, lw=0,
            label=(
                f'{plotlabels.get(caseprefix,caseprefix)}'
                # f' ({df.shape[1]})'
            ),
        )
        # ## Max and min
        # for agg in ['min', 'max']:
        #     _ax.plot(
        #         df.index, df.agg(agg, axis=1), lw=0.5,
        #         color=colors[caseprefix],
        #         label='_nolabel',
        #     )

        ## Lines
        # df.plot(ax=_ax, legend=False, lw=0.5, color='k', alpha=0.25)
        for s in df:
            _ax.plot(
                df.index, df[s].values, color=colors[caseprefix],
                lw=0.5, alpha=0.25, label='_nolabel',
            )

        ## Histogram
        reeds.plots.hist_last(
            _ax, df, color=colors[caseprefix], bins=bins, alpha=1,
            xpad=1+((xscale+0.5)*i), xscale=xscale,
            # percentiles=[0.5],
            # percentiles=[0.05, 0.5, 0.95],
        )
## Formatting
ax[0].set_xlim(tstart)
ax[0].set_ylabel('Capacity [GW]')
ax[0].set_ylim(0)
ax[0].yaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(2))
ax[0].set_xticks([2020,2035,2050])
ax[0].xaxis.set_minor_locator(mpl.ticker.FixedLocator(list(range(2020,2051,5))))
## Legend
handles = [
    mpl.patches.Patch(
        facecolor=colors[caseprefix], edgecolor='none',
        label=plotlabels.get(caseprefix,caseprefix)
    )
    for caseprefix in plotcaseprefixes
]
ax[-1].legend(
    handles=handles, frameon=False, loc='upper left', bbox_to_anchor=(-0.05,1),
    fontsize='x-large',
    handletextpad=0.3, handlelength=0.7,
)

reeds.plots.despine(ax)
plt.draw()
reeds.plots.shorten_years(ax[0])
savename = (
    f"out_cap-line_country-{','.join(techs)}-"
    f"{','.join([plotlabels.get(c,c).title().replace(' ','') for c in plotcaseprefixes])}.png"
)
print(savename)
# plt.savefig(os.path.join(savepath, savename))
plt.show()

#%% Capacity stats
dfwrite = (
    dfplot[plotcaseprefixes].rename(columns=plotlabels)
    .xs(2050,0,'t')
    .fillna(0)
    .stack(['caseprefix','sample'])
    .groupby(['i','caseprefix'])
    .describe(percentiles=[0.05,0.25,0.5,0.75,0.95])
    .round(0).astype(int)
    .loc[techs]
)
dfwrite.to_csv(os.path.join(savepath, savename.replace('.png','.csv')))
dfwrite

#%% Capacity diff stats
dfwrite = (
    dfplot[plotcaseprefixes].xs(2050,0,'t')
    .sub(dfplot[plotcaseprefixes].xs(2020,0,'t'), fill_value=0)
    .rename(columns=plotlabels)
    .fillna(0)
    .stack(['caseprefix','sample'])
    .groupby('i')
    .describe(percentiles=[0.05,0.25,0.5,0.75,0.95])
    .round(0).astype(int)
    .loc[techs]
)
dfwrite.to_csv(os.path.join(savepath, savename.replace('.png','.csv').replace('_cap-','_cap_diff-')))
dfwrite


#%% National capacity for all scenarios: just histogram
t = 2050
tstart = 2020

dictplot = {}
for caseprefix in casepaths:
    caseprefix_samples = sorted([s for (c,s) in dictin_cap_r if c == caseprefix])
    # print(f'{caseprefix}: {(len(caseprefix_samples))}')
    dictplot[caseprefix] = pd.concat({
        sample: (
            dictin_cap_r[caseprefix,sample]
            .loc[dictin_cap_r[caseprefix,sample].t==t]
            .groupby('i').MW.sum()
            .rename('GW')
            / 1e3
        )
        for sample in caseprefix_samples
    }, axis=1)

dfplot = pd.concat(dictplot, axis=1, names=('caseprefix','sample'))

dfstart = (
    dictin_cap_r[basecase]
    .loc[dictin_cap_r[basecase].t==tstart]
    .groupby('i').MW.sum()
    .rename('GW') / 1e3
)

### Plot it
techs = [
    'Gas',
    'PV',
    'Wind',
    'Nuclear',
    'Storage',
    'Coal+CCS',
    'Offshore wind',
    'Gas+CCS',
    'Coal',
    # 'Fossil',
    # 'Geothermal',
    # 'Hydro',
]
ymin = 0.
numbins = 71
xscale = 4.0
ymax = dfplot.loc[techs].max().max()
bins = np.linspace(ymin, ymax, numbins)
nrows = 1
ncols = len(techs)

# plotcaseprefixes = [
#     'v20250829_mcK0_MC_flat_state_IRA',
#     'v20250829_mcK0_MC_flat_state_MC',
#     'v20250829_mcK0_MC_flat_state_CAA0',
# ]
# plotlabels = {
#     **nicelabels,
#     'v20250829_mcK0_MC_flat_state_MC': 'CurrentPol',
# }
# figwidth = 1.7

# plotcaseprefixes = [
#     'v20250829_mcK0_MC_flat_state_MC',
#     'v20250911_mcK0_MC_tri_state',
#     'v20250829_mcK0_MC_flat_country',
#     'v20250922_mcK0_MC_tri_country',
# ]
# plotlabels = nicelabels
# figwidth = 1.7

plotcaseprefixes = [
    'v20250922_mcK0_MC_tri_country',
    'v20250829_mcK0_MC_flat_country',
    'v20250911_mcK0_MC_tri_state',
    'v20250829_mcK0_MC_flat_state_MC',
    'v20250829_mcK0_MC_flat_state_IRA',
    'v20250829_mcK0_MC_flat_state_CAA0',
]
plotlabels = nicelabels
figwidth = 2.0


plt.close()
f,ax = plt.subplots(
    nrows, ncols, sharex='row', sharey='row', figsize=(figwidth*ncols, 2.5),
    gridspec_kw={'wspace':0.3},
    dpi=300,
)
for col, tech in enumerate(techs):
    _ax = ax[col]
    _ax.set_title(tech, weight='bold', fontsize='x-large')
    for x, caseprefix in enumerate(plotcaseprefixes):
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
            color=colors[caseprefix],
        )
    ## Starting capacity
    ax[col].axhline(dfstart.get(tech,0), c='k', ls='--', lw=0.75)
    ## Formatting
    ax[col].set_xticks(range(len(plotcaseprefixes)))
    ax[col].set_xticklabels(
        [plotlabels.get(caseprefix,caseprefix) for caseprefix in plotcaseprefixes],
        rotation=90, weight='bold',
    )
    colors = [colors[c] for c in plotcaseprefixes]
    for x, xtick in enumerate(ax[col].get_xticklabels()):
        xtick.set_color(colors[x])

## Formatting
ax[0].set_ylabel(f'Capacity, {t} [GW]')
ax[0].set_ylim(0)
ax[0].yaxis.set_major_locator(mpl.ticker.MultipleLocator(400))
ax[0].yaxis.set_minor_locator(mpl.ticker.MultipleLocator(100))
ax[0].set_xlim(-0.15, len(plotcaseprefixes))
# ## Legend
# handles = [
#     mpl.patches.Patch(
#         facecolor=colors[caseprefix], edgecolor='none',
#         label=plotlabels.get(caseprefix,caseprefix)
#     )
#     for caseprefix in plotcaseprefixes
# ]
# ax[-1].legend(
#     handles=handles, frameon=False, loc='upper left', bbox_to_anchor=(-0.05,1),
#     fontsize='x-large',
#     handletextpad=0.3, handlelength=0.7,
# )

reeds.plots.despine(ax)
savename = (
    f"out_cap-hist-{','.join(techs)}-"
    f"{','.join([plotlabels.get(c,c).title().replace(' ','') for c in plotcaseprefixes])}.png"
)
print(savename)
plt.savefig(os.path.join(savepath, savename))
plt.show()


#%% Zonal generation capacity maps: Absolute difference from central
cmap = plt.cm.RdBu_r
techs = ['PV', 'Wind', 'Nuclear', 'Gas+CCS', 'Coal+CCS']
techs = ['Nuclear', 'Gas+CCS', 'Coal+CCS']
techs = ['Wind', 'PV']
t = 2050
central_value = 'central_case'
central_value = 'median'
difftype, vlim = 'percent', 100
difftype, vlim = 'absolute', 10

units = 'GW' if difftype == 'absolute' else '%'

for tech in techs:
    for caseprefix in casepaths:
        caseprefix_samples = sorted([s for (c,s) in dictin_cap_r if c in [caseprefix]])
        dfplot = pd.concat(
            {
                sample: dictin_cap_r[caseprefix,sample].loc[
                    (dictin_cap_r[caseprefix,sample].t==t)
                    & (dictin_cap_r[caseprefix,sample].i==tech)
                ].set_index('r').MW
                for sample in caseprefix_samples
            },
            axis=1,
        ).fillna(0)
        ### Take the diff and convert to GW
        if central_value == 'central_case':
            central = dictin_cap_r['central',0].loc[
                (dictin_cap_r['central',0].t==t)
                & (dictin_cap_r['central',0].i==tech)
            ].set_index('r').MW
        else:
            central = dfplot.agg(central_value, axis=1)

        regions = list(set(dfplot.index.tolist() + central.index.tolist()))

        _dfdiff = (
            dfplot.reindex(regions).fillna(0)
            .subtract(central.reindex(regions).fillna(0), axis=0)
        )
        if difftype == 'absolute':
            dfdiff = _dfdiff / 1e3
        else:
            dfdiff = _dfdiff.divide(central.reindex(regions).fillna(0), axis=0) * 100

        if vlim == 'auto':
            _vlim = max(dfdiff.max().max(), abs(dfdiff.min().min()))
            vmin, vmax = -_vlim, _vlim
        else:
            vmin, vmax = -vlim, vlim

        ## Get coordinates
        nrows, ncols, coords = reeds.plots.get_coordinates(caseprefix_samples, aspect=1.2)
        print(nrows, ncols, len(caseprefix_samples))
        scale = 1

        ## Add geo info
        dfdiff['geometry'] = dfdiff.index.map(dfmap['r'].geometry)
        dfdiff = gpd.GeoDataFrame(dfdiff, crs=dfmap['r'].crs)
        geom = dfmap['r'].geometry.simplify(1000)

        bounds = dfmap['country'].bounds.squeeze(0)
        xspan = bounds.maxx - bounds.minx
        yspan = bounds.maxy - bounds.miny

        dfstates = dfmap['st'].copy()
        dfstates.geometry = dfstates.simplify(1000)

        plt.close()
        f,ax = plt.subplots(figsize=(ncols*scale, nrows*scale*0.8))
        for sample in tqdm(caseprefix_samples):
            row, col = coords[sample]
            ## Data
            df = dfdiff[[sample, 'geometry']].rename(columns={sample:'val'}).copy()
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
        ## Colorbar-histogram across all samples and zones
        reeds.plots.addcolorbarhist(
            f=f, ax0=ax,
            data=dfdiff.drop(columns='geometry').stack(),
            cmap=cmap, vmin=vmin, vmax=vmax,
            cbarleft=1.01, cbarheight=0.9,
        )
        ## Formatting
        ax.set_title(
            f"{tech} {t} capacity, difference from {central_value} "
            f"[{units}]: "
            f"{nicelabels.get(caseprefix,caseprefix)} (n = {len(caseprefix_samples)})"
        )
        ax.axis('off')
        savename = f"out_cap_r-map_{units}-{tech.replace('-','')}-{caseprefix}.png"
        print(savename)
        plt.savefig(os.path.join(savepath, savename))
        plt.show()


#%% National capacity stack bar for all scenarios
t = 2050
scale = 0.02
scale = 0.1
barwidth = 1.0
for sortby in [
    None,
    'PV',
    'Wind',
    ['PV', 'Wind'],
    'Nuclear',
    'Gas',
    'Coal',
    ['Gas+CCS', 'Coal+CCS'],
]:
    for caseprefix in casepaths:
        caseprefix_samples = sorted([s for (c,s) in dictin_cap_r if c in [caseprefix]])
        dfin = pd.concat(
            {
                sample: dictin_cap_r[caseprefix,sample].loc[
                    (dictin_cap_r[caseprefix,sample].t==t)
                ].groupby('i').MW.sum().rename('GW') / 1e3
                for sample in caseprefix_samples
            },
            axis=1,
        ).fillna(0)

        missing = [i for i in dfin.index if i not in colors_tech]
        print(f"missing colors: {', '.join(missing)}")
        dfplot = dfin.reindex(list(colors_tech.keys())).fillna(0).T.reset_index(drop=True)
        ## Get the order
        if sortby is None:
            order = dfplot.index
            label = 'None'
        elif isinstance(sortby, str):
            order = dfplot.sort_values(sortby).index
            label = sortby
        elif isinstance(sortby, list):
            order = dfplot[sortby].sum(axis=1).sort_values().index
            label = ' + '.join([i.replace(' ','').replace('+','') for i in sortby])
        else:
            raise NotImplementedError(f'sortby={sortby}')
        dfplot = dfplot.loc[order].reset_index(drop=True).copy()

        ## Plot it
        plt.close()
        f,ax = plt.subplots(figsize=(scale*len(caseprefix_samples), 3.75))
        reeds.plots.stackbar(df=dfplot, ax=ax, colors=colors_tech, width=barwidth, net=False)
        ## Legend
        handles = [
            mpl.patches.Patch(facecolor=colors_tech[i], edgecolor='none', label=i)
            for i in colors_tech if i in dfplot
        ]
        leg = ax.legend(
            handles=handles[::-1],
            loc='upper left', bbox_to_anchor=(1,1), frameon=False,
            fontsize='large', labelspacing=0.3,
            handletextpad=0.3, handlelength=0.7,
        )
        ## Formatting
        ax.set_title(nicelabels.get(caseprefix,caseprefix), x=0, ha='left')
        ax.set_xlim(-0.5, len(dfplot)-0.5)
        ax.set_ylabel(f"{t} capacity [GW]"+('\n'f'sorted by {label}' if sortby is not None else ''))
        ax.set_xlabel(f'Sample number (n = {len(caseprefix_samples)})')
        ax.xaxis.set_major_locator(mpl.ticker.MultipleLocator(20))
        ax.xaxis.set_minor_locator(mpl.ticker.MultipleLocator(10))
        reeds.plots.despine(ax)
        savename = (
            f"out_cap-bar_country-by_{label}-"
            f"{nicelabels.get(caseprefix,caseprefix).title()}.png"
        ).replace(' ','')
        print(savename)
        plt.savefig(os.path.join(savepath, savename))
        plt.show()


#%% State stack bars
t = 2050
nrows = state_subplots['row'].max() + 1
ncols = state_subplots['col'].max() + 1
states = sorted(state_subplots.index.tolist())
scale = 1.2
barwidth = 1.0
for caseprefix in casepaths:
    caseprefix_samples = sorted([s for (c,s) in dictin_cap_r if c in [caseprefix]])
    dfin = pd.concat(
        {
            sample: (
                dictin_cap_r[caseprefix,sample]
                .loc[(dictin_cap_r[caseprefix,sample].t==t)]
                .assign(st=dictin_cap_r[caseprefix,sample].r.map(hierarchy.st))
                .groupby(['st','i']).MW.sum().rename('GW') / 1e3
            )
            for sample in caseprefix_samples
        },
        axis=1,
    ).fillna(0)

    missing = [i for i in dfin.index.get_level_values('i').unique() if i not in colors_tech]
    print(f"missing colors: {', '.join(missing)}")

    ## Plot it
    plt.close()
    f,ax = plt.subplots(
        nrows, ncols, figsize=(ncols*scale, nrows*scale),
        gridspec_kw={'hspace':0.4, 'wspace':0.5},
        sharex=True,
    )
    # for state in ['CA','TX','FL']:
    # for state in list(set(np.random.choice(states, 10))):
    for state in states:
        _ax = ax[state_subplots.loc[state,'ax']]
        dfplot = dfin.loc[state].reindex(list(colors_tech.keys())).fillna(0).T.reset_index(drop=True)
        dfplot = dfplot.reset_index(drop=True).copy()
        reeds.plots.stackbar(df=dfplot, ax=_ax, colors=colors_tech, width=barwidth, net=False)
        ## Formatting
        _ax.annotate(
            state,
            (0.05, 0.95), xycoords='axes fraction', ha='left', va='top',
            color='k', fontsize='large',
            path_effects=[pe.withStroke(linewidth=3.0, foreground='w', alpha=0.5)],
            zorder=1e6,
        )
    ## Turn off unused axes
    subplots_used = state_subplots['ax'].tolist()
    for row in range(nrows):
        for col in range(ncols):
            if (row,col) not in subplots_used:
                ax[row,col].axis('off')
    ## Legend
    handles = [
        mpl.patches.Patch(facecolor=colors_tech[i], edgecolor='none', label=i)
        for i in colors_tech if i in dfplot
    ]
    leg = ax[-1,-1].legend(
        handles=handles[::-1],
        loc='lower left', bbox_to_anchor=(-0.5,-0.2), frameon=False,
        fontsize='large', labelspacing=0.3,
        handletextpad=0.3, handlelength=0.7,
    )
    ## Formatting
    ax[0,0].annotate(
        f"{nicelabels.get(caseprefix,caseprefix)} (n = {len(caseprefix_samples)})",
        (0.05, 0.9), xycoords='axes fraction', ha='left', va='top',
        color='k', fontsize='xx-large',
    )
    ax[state_subplots.loc['MS','ax']].set_xlim(-0.5, len(dfplot)-0.5)
    # ax.set_ylabel(f"{t} capacity [GW]"+('\n'f'sorted by {label}' if sortby is not None else ''))
    ax[state_subplots.loc['MS','ax']].set_xlabel(
        f'Sample number (n = {len(caseprefix_samples)})', fontsize='xx-large')
    ax[state_subplots.loc['OR','ax']].set_ylabel(
        f"{t} capacity [GW]", labelpad=15, fontsize='xx-large')
    # ax.xaxis.set_major_locator(mpl.ticker.MultipleLocator(20))
    # ax.xaxis.set_minor_locator(mpl.ticker.MultipleLocator(10))
    reeds.plots.despine(ax)
    savename = (
        f"out_cap-bar_st-"
        f"{nicelabels.get(caseprefix,caseprefix).title()}.png"
    ).replace(' ','')
    print(savename)
    plt.savefig(os.path.join(savepath, savename))
    plt.show()

#%%
#%%


#%% National capacity stack bar with different inputs
t = 2050
scale = 0.1
barwidth = 1.0

input_plots = [
    {'data':'demand', 'label':'Demand\n[TWh]', 'color':'k'},
    {'data':'gasprice', 'label':'Gas\nprice\n[$/MMBtu]', 'color':'C4'},
    {'data':'cap_cost', 'label':'PV\ncap cost\n[$/kW]', 'tech':'upv_3', 'color':'C1'},
    {'data':'cap_cost', 'label':'Wind\ncap cost\n[$/kW]', 'tech':'wind-ons_5', 'color':'C0'},
    {'data':'cap_cost', 'label':'Nuclear\ncap cost\n[$/kW]', 'tech':'nuclear', 'color':'C3'},
    {'data':'sc', 'label':'PV\navailability\n[TW]', 'tech':'upv', 'color':'C1'},
    {'data':'sc', 'label':'Wind\navailability\n[TW]', 'tech':'wind-ons', 'color':'C0'},
]

for sortby in [
    ## Unsorted
    None,
    ## Capacity
    'PV',
    'Wind',
    ['PV', 'Wind'],
    'Nuclear',
    'Gas',
    'Coal',
    ['Gas+CCS', 'Coal+CCS'],
    ## Inputs
    'gasprice',
    'demand',
]:
    for caseprefix in casepaths:
        ## Capacity
        caseprefix_samples = sorted([s for (c,s) in dictin_cap_r if c in [caseprefix]])
        dfcap_in = pd.concat(
            {
                sample: dictin_cap_r[caseprefix,sample].loc[
                    (dictin_cap_r[caseprefix,sample].t==t)
                ].groupby('i').MW.sum().rename('GW') / 1e3
                for sample in caseprefix_samples
            },
            axis=1,
        ).fillna(0)

        missing = [i for i in dfcap_in.index if i not in colors_tech]
        print(f"missing colors: {', '.join(missing)}")
        dfcap = dfcap_in.reindex(list(colors_tech.keys())).fillna(0).T
        ## Get the order
        if sortby is None:
            order = dfcap.index
            label = 'None'
        elif sortby == 'gasprice':
            order = pd.Series({
                sample: dictin_gasprice[caseprefix,sample].mean(axis=1).loc[t]
                for sample in caseprefix_samples
            }).sort_values().index
            label = 'gas price'
        elif sortby == 'demand':
            order = pd.Series({
                sample: dictin_demand[caseprefix,sample].groupby('t').sum().loc[t]
                for sample in caseprefix_samples
            }).sort_values().index
            label = sortby
        elif isinstance(sortby, str):
            order = dfcap.sort_values(sortby).index
            label = sortby
        elif isinstance(sortby, list):
            order = dfcap[sortby].sum(axis=1).sort_values().index
            label = ' + '.join([i.replace(' ','').replace('+','') for i in sortby])
        else:
            raise NotImplementedError(f'sortby={sortby}')
        dfcap = dfcap.loc[order].reset_index(drop=True).copy()
        dfcap.index += 0.5

        ## Set up plots
        ncols = 1
        nrows = 1 + len(input_plots)
        xscale = 0.08
        yscale = 1.25
        yratio = 3

        ### Plot it
        plt.close()
        f,ax = plt.subplots(
            nrows, ncols, figsize=(xscale*len(caseprefix_samples), yscale*nrows),
            sharex=True, gridspec_kw={'height_ratios':[yratio]+[1]*len(input_plots)}
        )
        ### Capacity
        _ax = ax[0]
        reeds.plots.stackbar(df=dfcap, ax=_ax, colors=colors_tech, width=barwidth, net=False)
        ## Legend
        handles = [
            mpl.patches.Patch(facecolor=colors_tech[i], edgecolor='none', label=i)
            for i in colors_tech if i in dfcap
        ]
        leg = _ax.legend(
            handles=handles[::-1],
            loc='upper left', bbox_to_anchor=(1,1), frameon=False,
            fontsize='large', labelspacing=0.3,
            handletextpad=0.3, handlelength=0.7,
        )
        ## Formatting
        _ax.set_title(
            nicelabels.get(caseprefix,caseprefix)
            + (', 'f'sorted by {label} capacity' if sortby is not None else ''),
            x=0, ha='left',
        )
        _ax.set_ylabel(f'{t} capacity [GW]')
        ### Inputs
        for i, settings in enumerate(input_plots):
            _ax = ax[i+1]
            if settings['data'] == 'demand':
                df = pd.Series({
                    sample: dictin_demand[caseprefix,sample].groupby('t').sum().loc[t]
                    for sample in caseprefix_samples
                }).loc[order].reset_index(drop=True)
            elif settings['data'] == 'gasprice':
                df = pd.Series({
                    sample: dictin_gasprice[caseprefix,sample].mean(axis=1).loc[t]
                    for sample in caseprefix_samples
                }).loc[order].reset_index(drop=True)
            elif settings['data'] == 'cap_cost':
                df = pd.Series({
                    sample: dictin_cap_cost[caseprefix,sample].loc[t, settings['tech']]
                    for sample in caseprefix_samples
                }).loc[order].reset_index(drop=True)
            elif settings['data'] == 'sc':
                df = pd.Series({
                    sample: dictin_sc[caseprefix,sample].loc[settings['tech']].sum() / 1e3
                    for sample in caseprefix_samples
                }).loc[order].reset_index(drop=True)
            else:
                raise NotImplementedError(settings['data'])
            df.index += 0.5

            _ax.bar(df.index, df.values, color=settings['color'], width=barwidth)
            _ax.set_ylabel(
                settings['label'], rotation=0, ha='right', y=0, color=settings['color'],
            )

        ### More formatting
        for row in range(nrows):
            ax[row].grid(axis='x', which='major', c='w', ls=(0, (2, 5)), lw=0.75, alpha=0.5, zorder=1e6)
        _ax.set_xlim(0, len(dfcap))
        _ax.set_xlabel(f'Sample number (n = {len(caseprefix_samples)})')
        _ax.xaxis.set_minor_locator(mpl.ticker.MultipleLocator(5))
        _ax.xaxis.set_major_locator(mpl.ticker.MultipleLocator(10))
        reeds.plots.despine(ax)
        savename = (
            f"out_cap-bar_country-inputs-by_{label}-"
            f"{nicelabels.get(caseprefix,caseprefix).title()}.png"
        ).replace(' ','')
        print(savename)
        plt.savefig(os.path.join(savepath, savename))
        plt.show()


#%% Grid of scatter plots: regions on axes, histograms on diagonal, scatter plots on off-diagonal
level = 'transreg'
binstep = 5
alpha = 0.5
color = 'C2'
year = 2050
year_baseline = 2020
scale = 1.75
techs = [
    'PV',
    'Wind',
    'Nuclear',
    # 'Gas',
    # 'Coal',
]
## Sort regions west to east
regions = dfmap[level].loc[hierarchy[level].unique()].bounds.minx.sort_values().index
ncols = nrows = len(regions)

for tech in techs:
    for caseprefix in casepaths:
        caseprefix_samples = sorted([s for (c,s) in dictin_trans_r if c == caseprefix])
        dfplot = pd.concat(
            {
                sample: (
                    dictin_cap_r[caseprefix,sample].loc[
                        (dictin_cap_r[caseprefix,sample].t==year)
                        & (dictin_cap_r[caseprefix,sample].i==tech)
                    ].groupby('r').MW.sum()
                    - dictin_cap_r[caseprefix,sample].loc[
                        (dictin_cap_r[caseprefix,sample].t==year_baseline)
                        & (dictin_cap_r[caseprefix,sample].i==tech)
                    ].groupby('r').MW.sum()
                )
                for sample in caseprefix_samples
            },
            names=('case',),
        ).reset_index()
        dfplot['region'] = dfplot.r.map(hierarchy[level])
        dfplot = dfplot.groupby(['region','case']).MW.sum().rename('GW') / 1e3
        ## Fill empties with zero
        dfplot = dfplot.unstack('case').reindex(regions).fillna(0).stack('case')

        ymax = dfplot.max()
        bins = np.arange(0, ymax+0.1, binstep)

        plt.close()
        f,ax = plt.subplots(
            nrows, ncols, figsize=(scale*ncols, scale*nrows), sharex=True,
        )
        for row, region_y in enumerate(regions):
            for col, region_x in enumerate(regions):
                ## Don't keep the upper right half
                if col > row:
                    ax[row,col].axis('off')
                    continue
                ## If the same, plot histogram
                if region_y == region_x:
                    ax[row,col].hist(
                        x=dfplot.loc[region_y].values,
                        bins=bins,
                        color=colors[caseprefix],
                    )
                    # reeds.plots.despine(ax[row,col], left=False)
                    ax[row,col].set_yticks([])
                ## If different, plot scatter
                else:
                    ax[row,col].plot(
                        dfplot.loc[region_x].values,
                        dfplot.loc[region_y].values,
                        lw=0, marker='o', alpha=0.2, markeredgewidth=0,
                        color=colors[caseprefix],
                    )
                    ax[row,col].set_ylim(0,ymax)
                    # ax[row,col].yaxis.set_major_locator(mpl.ticker.MultipleLocator(50))
                    if col > 0:
                        ax[row,col].set_yticklabels([])
                ## Formatting
                # ax[row,col].set_xlim(0,ymax)
                if row == nrows - 1:
                    ax[row,col].set_xlabel(region_x.replace('|','\n'))
                if col == 0:
                    ax[row,col].set_ylabel(region_y.replace('|','\n'), rotation=0, ha='right', va='center')
        # ## Formatting
        # ax[-1,0].xaxis.set_major_locator(mpl.ticker.MultipleLocator(50))
        ax[-1,0].set_xlim(0,ymax)
        ax[0,0].set_title(
            f'{tech} capacity added by {year} [GW]: '
            f'{nicelabels.get(caseprefix,caseprefix).title()} (n = {len(caseprefix_samples)})',
            x=0, ha='left', fontsize=16, weight='bold',
        )
        reeds.plots.despine(ax)
        savename = f"out_cap-region_vs_region_{year}-{level}-{tech.replace('-','')}-{caseprefix}.png"
        print(savename)
        plt.savefig(os.path.join(savepath, savename))
        plt.show()


#%% One scatter plot: Two inputs on different axes, marker size = added capacity
tech_cap = 'Nuclear'
cost_tech = 'nuclear'
t = 2050
tstart = 2025
zoom = True
zoom = False
if not zoom:
    ymax = pd.concat(dictin_cap_cost).xs(t,0,'t')[cost_tech].max()
    xmax = pd.concat(dictin_gasprice).xs(t,0,'t').mean(axis=1).max()

for caseprefix in casepaths:
    caseprefix_samples = sorted([s for (c,s) in dictin_cap_r if c == caseprefix])
    ## Marker size
    dfsize = pd.Series(
        {
            sample: (
                dictin_cap_r[caseprefix,sample].loc[
                    (dictin_cap_r[caseprefix,sample].t==t)
                    & (dictin_cap_r[caseprefix,sample].i==tech_cap)
                ].MW.sum()
                - dictin_cap_r[caseprefix,sample].loc[
                    (dictin_cap_r[caseprefix,sample].t==tstart)
                    & (dictin_cap_r[caseprefix,sample].i==tech_cap)
                ].MW.sum()
            ) / 1e3
            for sample in caseprefix_samples
        }
    ).clip(lower=0)
    sizelabel = f'{tech_cap} capacity'
    ## x axis: Gas price
    dfx = pd.Series({
        sample: dictin_gasprice[caseprefix,sample].mean(axis=1).loc[t]
        for sample in caseprefix_samples
    })
    xlabel = 'Gas price [$/MMBtu]'
    ## y axis: Nuclear cost
    dfy = pd.Series({
        sample: dictin_cap_cost[caseprefix,sample].loc[t,cost_tech]
        for sample in caseprefix_samples
    })
    ylabel = f'{cost_tech.title()} cost [$/kW]'
    ## Combine
    dfplot = pd.concat({'x':dfx, 'y':dfy, 'markersize':dfsize}, axis=1)
    ### Plot it
    plt.close()
    f,ax = plt.subplots()
    ## Circles for nonzero
    scatter_nonzero = ax.scatter(
        dfplot['x'].values, dfplot['y'].values, s=dfplot['markersize'].values,
        marker='o', alpha=0.9, lw=0,
    )
    ## x's for zero
    dfzero = dfplot.loc[dfplot['markersize'] <= 0]
    if len(dfzero):
        scatter_zero = ax.scatter(
            dfzero['x'].values, dfzero['y'].values, s=10,
            marker='x', alpha=0.9, color='C3', lw=1.0,
        )
    ## Legend
    handles, labels = scatter_nonzero.legend_elements(
        prop='sizes', alpha=0.9, color='C0',
        # num='auto',
        num=len(np.arange(0, dfplot['markersize'].max(), 50)),
    )
    legend = ax.legend(
        handles, labels, loc='center left', bbox_to_anchor=(1,0.5), frameon=False,
        # title=f'{t}\n{tech_cap}\ncapacity\n[GW]',
        title=f'{tech_cap}\nadditions\nthrough\n{t}\n[GW]'
    )
    ## Formatting
    ax.set_title(
        f"{nicelabels.get(caseprefix,caseprefix)} (n = {len(caseprefix_samples)})",
        x=0, ha='left',
    )
    if not zoom:
        ax.grid(axis='both', which='major', c='0.7', ls=(1,(1,5)), lw=0.5, zorder=-1e6)
        ax.set_axisbelow(True)
        ax.set_xlim(0, xmax)
        ax.set_ylim(0, ymax)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    reeds.plots.despine(ax)
    savename = (
        "out_cap-scatter-x_gasprice-y_cost_nuclear-size_cap_nuclear-"
        + ('zoom-' if zoom else '')
        + f"{nicelabels.get(caseprefix,caseprefix).title()}.png"
    ).replace(' ','')
    print(savename)
    plt.savefig(os.path.join(savepath, savename))
    plt.show()


#%% One set of scatter plots for multiple scenarios:
### Two inputs on different axes, marker size = added capacity
tech_cap = 'Nuclear'
cost_tech = 'nuclear'
t = 2050
tstart = 2025
zoom = False
alpha = 0.7
plotcaseprefixes = [
    'v20250829_mcK0_MC_flat_state_MC',
    'v20250829_mcK0_MC_flat_country',
    'v20250911_mcK0_MC_tri_state',
    'v20250922_mcK0_MC_tri_country',
]
plotlabels = nicelabels

ncols = len(plotcaseprefixes)

if not zoom:
    ymax = pd.concat(dictin_cap_cost).xs(t,0,'t')[cost_tech].max()
    xmax = pd.concat(dictin_gasprice).xs(t,0,'t').mean(axis=1).max()

### Plot it
dictplot = {}
scatter_nonzero = {}
plt.close()
f,ax = plt.subplots(1, ncols, sharex=True, sharey=True, figsize=(8, 3.75))
for col, caseprefix in enumerate(plotcaseprefixes):
    caseprefix_samples = sorted([s for (c,s) in dictin_cap_r if c == caseprefix])
    ## Marker size
    dfsize = pd.Series(
        {
            sample: (
                dictin_cap_r[caseprefix,sample].loc[
                    (dictin_cap_r[caseprefix,sample].t==t)
                    & (dictin_cap_r[caseprefix,sample].i==tech_cap)
                ].MW.sum()
                - dictin_cap_r[caseprefix,sample].loc[
                    (dictin_cap_r[caseprefix,sample].t==tstart)
                    & (dictin_cap_r[caseprefix,sample].i==tech_cap)
                ].MW.sum()
            ) / 1e3
            for sample in caseprefix_samples
        }
    ).clip(lower=0)
    sizelabel = f'{tech_cap} capacity'
    ## x axis: Gas price
    dfx = pd.Series({
        sample: dictin_gasprice[caseprefix,sample].mean(axis=1).loc[t]
        for sample in caseprefix_samples
    })
    xlabel = f'{t} gas price [$/MMBtu]'
    ## y axis: Nuclear cost
    dfy = pd.Series({
        sample: dictin_cap_cost[caseprefix,sample].loc[t,cost_tech]
        for sample in caseprefix_samples
    })
    ylabel = f'{t} {cost_tech.lower()} cost [$/kW]'
    ## Combine
    dfplot = pd.concat({'x':dfx, 'y':dfy, 'markersize':dfsize}, axis=1)
    dictplot[plotlabels.get(caseprefix,caseprefix)] = dfplot
    ## Circles for nonzero
    scatter_nonzero[plotlabels.get(caseprefix,caseprefix)] = ax[col].scatter(
        dfplot['x'].values, dfplot['y'].values, s=dfplot['markersize'].values,
        marker='o', alpha=alpha,
        lw=0, color='C0',
        # lw=1.0, facecolor='none', edgecolor='C0',
    )
    ## x's for zero
    dfzero = dfplot.loc[dfplot['markersize'] <= 0]
    if len(dfzero):
        scatter_zero = ax[col].scatter(
            dfzero['x'].values, dfzero['y'].values, s=10,
            marker='x', alpha=0.9, color='C3', lw=1.0,
        )
    ## Formatting
    ax[col].set_title(
        f"{plotlabels.get(caseprefix,caseprefix)}",
        # f" (n = {len(caseprefix_samples)})",
        x=0, ha='left',
    )
    ax[col].grid(axis='both', which='major', c='0.7', ls=(1,(1,5)), lw=0.5, zorder=-1e6)
    ax[col].set_axisbelow(True)
## Legend
dfdata = pd.concat(dictplot, names=('caseprefix','sample'))
dfstats = dfdata.groupby('caseprefix').markersize.describe()
label_scen = dfstats['max'].idxmax()
handles, labels = scatter_nonzero[label_scen].legend_elements(
    prop='sizes', alpha=alpha, color='C0',
    # num='auto',
    # num=len(np.arange(0, dfstats['max'].max(), 50)),
    num=[10,50,100,200,300],
    # num=9,
)
## Add the zero
handles = [
    mpl.lines.Line2D(
        [], [], marker='x', alpha=0.9, color='C3', markeredgewidth=1, lw=0,
        markersize=np.sqrt(10),
    )
] + handles
labels = ['0'] + labels
legend = ax[-1].legend(
    handles, labels, loc='center left', bbox_to_anchor=(1,0.5),
    # title=f'{t}\n{tech_cap}\ncapacity\n[GW]',
    title=f'{tech_cap}\nadditions\nthrough\n{t}\n[GW]',
    labelspacing=1.,
    frameon=False,
)
# ax[0].set_xlim(0, xmax)
ax[0].set_ylim(0, 6450)
ax[0].set_xlim(1.923, 5.9)
ax[0].xaxis.set_major_locator(mpl.ticker.MultipleLocator(1))
ax[0].set_xlabel(xlabel, x=0, ha='left')
ax[0].set_ylabel(ylabel)
reeds.plots.despine(ax)
savename = (
    "out_cap-scatter-x_gasprice-y_cost_nuclear-size_cap_nuclear-"
    + ('zoom-' if zoom else '')
    + f"{','.join([plotlabels.get(caseprefix,caseprefix).title() for caseprefix in plotcaseprefixes])}"
    ".png"
).replace(' ','')
print(savename)
plt.savefig(os.path.join(savepath, savename))
plt.show()

#%% Nuclear capacity stats
pd.concat(
    {y: dfdata.loc[dfdata.markersize > y].y.describe() for y in [0, 1, 2, 5, 10]},
    axis=1, names='GW_threshold',
).round(0).astype(int)


#%%
#%% More dimensions
sorted(dictin_cap_cost[caseprefix,caseprefix_samples[0]].columns)
cost_techs = [
    {'i': 'battery_li', 'label':'Battery'},
    {'i': 'upv_3', 'label':'PV'},
    {'i': 'wind-ons_5', 'label':'Wind (land)'},
    {'i': 'wind-ofs_5', 'label':'Wind (offshore fixed)'},
    {'i': 'geohydro_allkm_1', 'label':'Geothermal'},
    {'i': 'gas-cc-ccs_mod', 'label':'Gas+CCS'},
    {'i': 'coal-ccs_mod', 'label':'Coal+CCS'},
    {'i': 'nuclear', 'label':'Nuclear'},
]
x_datums = ['gasprice', 'demand', 'sc_wind']
x_labels = ['Gas price [$/MMBtu]', 'Demand [PWh]', 'Wind avail [TW]']

tech_cap, sizescale = 'Wind', 0.1
tech_cap, sizescale = 'PV', 0.1
tech_cap, sizescale = 'Nuclear', 1
t = 2050
tstart = 2025
cmap = cmocean.tools.crop_by_percent(plt.cm.turbo, 10)
zoom = True
zoom = False

ncols = len(x_datums)
nrows = len(cost_techs)

for caseprefix in casepaths:
    caseprefix_samples = sorted([s for (c,s) in dictin_cap_r if c == caseprefix])
    ## Marker size
    dfsize = pd.Series(
        {
            sample: (
                dictin_cap_r[caseprefix,sample].loc[
                    (dictin_cap_r[caseprefix,sample].t==t)
                    & (dictin_cap_r[caseprefix,sample].i==tech_cap)
                ].MW.sum()
                - dictin_cap_r[caseprefix,sample].loc[
                    (dictin_cap_r[caseprefix,sample].t==tstart)
                    & (dictin_cap_r[caseprefix,sample].i==tech_cap)
                ].MW.sum()
            ) / 1e3
            for sample in caseprefix_samples
        }
    ).clip(lower=0).rename('capacity').to_frame()
    sizelabel = f'{tech_cap} capacity'
    ### x-axis variables
    xdata = pd.concat({
        'gasprice': pd.Series({
            sample: dictin_gasprice[caseprefix,sample].mean(axis=1).loc[t]
            for sample in caseprefix_samples
        }),
        'demand': pd.Series({
            sample: dictin_demand[caseprefix,sample].groupby('t').sum().loc[t] / 1e3
            for sample in caseprefix_samples
        }),
        'sc_wind': pd.Series({
            sample: dictin_sc[caseprefix,sample].loc['wind-ons'].sum() / 1e3
            for sample in caseprefix_samples
        }),
    }, axis=1)
    ### y axes: Generation capex costs
    ydata = pd.concat({
        cost_tech['label']: pd.Series({
            sample: dictin_cap_cost[caseprefix,sample].loc[t,cost_tech['i']]
            for sample in caseprefix_samples
        })
        for cost_tech in cost_techs
    }, axis=1)
    ylabels = {}
    for cost_tech in cost_techs:
        sep = ' ' if cost_tech['label'] in ['Battery', 'PV', 'Wind (land)'] else '\n'
        ylabels[cost_tech['label']] = f"{cost_tech['label']}{sep}cost [$/kW]"
    ## Combine
    dfplot = pd.concat({'size':dfsize, 'x':xdata, 'y':ydata}, axis=1)
    ## Get the y ranges
    ymax = ydata.max() + (0 if zoom else 100)
    ymin = ydata.min()
    yspan = ymax - ymin
    ### Plot it
    plt.close()
    f,ax = plt.subplots(
        nrows, ncols, figsize=(6.5, 9), sharex='col', sharey='row',
        gridspec_kw={'height_ratios':(yspan.values if zoom else ymax.values)},
    )
    for row, ydatum in enumerate(dfplot['y'].columns):
        for col, xdatum in enumerate(dfplot['x'].columns):
            ## Circles for nonzero
            scatter_nonzero = ax[row,col].scatter(
                dfplot['x'][xdatum].values,
                dfplot['y'][ydatum].values,
                s=dfplot['size']['capacity'].values * sizescale,
                marker='o',
                # lw=0, facecolor='C0', edgecolor='none', alpha=0.7,
                # lw=1.0, facecolor='none', edgecolor='C0',
                c=dfplot['size']['capacity'].values, cmap=cmap,
                zorder=1e3,
            )
            ## x's for zero
            dfzero = dfplot.loc[dfplot['size']['capacity'] <= 0]
            if len(dfzero):
                scatter_zero = ax[row,col].scatter(
                    dfzero['x'][xdatum].values,
                    dfzero['y'][ydatum].values,
                    s=10,
                    marker='x', alpha=0.9, color='C7', lw=1.0,
                    zorder=1e2,
                )
            ## Formatting
            if col == 0:
                ax[row,col].set_ylabel(ylabels[ydatum], rotation=0, ha='right', va='center')
                if not zoom:
                    ax[row,col].set_ylim(0, ymax[ydatum])
            if row == nrows - 1:
                ax[row,col].set_xlabel(x_labels[col])
    ## Legend
    handles, labels = scatter_nonzero.legend_elements(
        # prop='sizes', alpha=0.7, color='C0', num='auto', func=lambda x: x/sizescale,
    )
    legend = ax[-1,-1].legend(
        handles, labels, loc='lower left', bbox_to_anchor=(1,0), frameon=False,
        # title=f'{t}\n{tech_cap}\ncapacity\n[GW]',
        title=f'{tech_cap}\nadditions\nthrough\n{t}\n[GW]'
    )
    # ## Formatting
    ax[0,0].set_title(
        f"{nicelabels.get(caseprefix,caseprefix)} (n = {len(caseprefix_samples)})",
        x=0, ha='left',
    )
    # if not zoom:
    #     ax.set_xlim(0)
    #     ax.set_ylim(0)
    reeds.plots.despine(ax)
    # savename = (
    #     "out_cap-scatter-x_gasprice-y_cost_nuclear-size_cap_nuclear-"
    #     + ('zoom-' if zoom else '')
    #     + f"{nicelabels.get(caseprefix,caseprefix).title()}.png"
    # ).replace(' ','')
    # print(savename)
    # plt.savefig(os.path.join(savepath, savename))
    plt.show()


#%% Scatter plot: Capacity vs inputs
cost_techs = [
    {'tech_cost': 'battery_li', 'tech_cap':'Storage', 'label':'Battery'},
    {'tech_cost': 'upv_3', 'tech_cap':'PV', 'label':'PV'},
    {'tech_cost': 'wind-ons_5', 'tech_cap':'Wind', 'label':'Wind'},
    # {'tech_cost': 'wind-ofs_5', 'label':'Wind (offshore fixed)'},
    # {'tech_cost': 'geohydro_allkm_1', 'label':'Geothermal'},
    # {'tech_cost': 'gas-cc-ccs_mod', 'label':'Gas+CCS'},
    # {'tech_cost': 'coal-ccs_mod', 'label':'Coal+CCS'},
    {'tech_cost':'nuclear', 'tech_cap':'Nuclear', 'label':'Nuclear'},
]
cap_techs = ['PV', 'Wind', 'Gas', 'Storage', 'Nuclear']
x_datums = ['gasprice', 'demand', 'sc_wind']
x_labels = {
    'gasprice':'Gas price\n[$/MMBtu]',
    'demand':'Demand\n[PWh]',
    'sc_wind':'Wind avail\n[TW]',
    'cost_Wind':'Wind cost\n[$/kW]',
    'cost_PV':'PV cost\n[$/kW]',
    'cost_Battery':'Battery cost\n[$/kW]',
    'cost_Nuclear':'Nuclear cost\n[$/kW]',
}

tech_cap, sizescale = 'Wind', 0.1
tech_cap, sizescale = 'PV', 0.1
tech_cap, sizescale = 'Nuclear', 1
t = 2050
tstart = 2025
zoom = False
zoom = True
corr_methods = ['pearson', 'spearman', 'kendall']
corr_name = {'pearson': 'p', 'spearman': 's', 'kendall': 'k'}
cmap = cmocean.tools.crop_by_percent(plt.cm.turbo, 10)
cmap = plt.cm.Spectral_r
cmap = plt.cm.turbo
cmap, cmin, cmax = plt.cm.coolwarm, -0.8, 0.8
# cmap = plt.cm.berlin
# cmap = cmocean.tools.crop_by_percent(
#     cmocean.tools.crop_by_percent(cmocean.cm.phase, 17, 'min'),
#     50, 'max'
# )
# cmap.name = 'phase_17_50'
# cmap = cmocean.tools.crop_by_percent(plt.cm.coolwarm, 10)
norm = mpl.colors.Normalize(vmin=cmin, vmax=cmax)

ncols = len(x_datums) + len(cost_techs)
nrows = len(cap_techs)

for caseprefix in casepaths:
    caseprefix_samples = sorted([s for (c,s) in dictin_cap_r if c == caseprefix])
    ## Marker size
    dfcap = pd.Series(
        {
            (tech, sample): (
                dictin_cap_r[caseprefix,sample].loc[
                    (dictin_cap_r[caseprefix,sample].t==t)
                    & (dictin_cap_r[caseprefix,sample].i==tech)
                ].MW.sum()
                - dictin_cap_r[caseprefix,sample].loc[
                    (dictin_cap_r[caseprefix,sample].t==tstart)
                    & (dictin_cap_r[caseprefix,sample].i==tech)
                ].MW.sum()
            ) / 1e3
            for sample in caseprefix_samples
            for tech in cap_techs
        }
    ).clip(lower=0).unstack(level=0)
    dfcap.columns = 'cap_' + dfcap.columns
    sizelabel = f'{tech_cap} capacity'
    ### x-axis variables
    xdata = pd.concat({
        'gasprice': pd.Series({
            sample: dictin_gasprice[caseprefix,sample].mean(axis=1).loc[t]
            for sample in caseprefix_samples
        }),
        'demand': pd.Series({
            sample: dictin_demand[caseprefix,sample].groupby('t').sum().loc[t] / 1e3
            for sample in caseprefix_samples
        }),
        'sc_wind': pd.Series({
            sample: dictin_sc[caseprefix,sample].loc['wind-ons'].sum() / 1e3
            for sample in caseprefix_samples
        }),
    }, axis=1)
    ### Generation capex costs
    costdata = pd.concat({
        f"cost_{cost_tech['label']}": pd.Series({
            sample: dictin_cap_cost[caseprefix,sample].loc[t,cost_tech['tech_cost']]
            for sample in caseprefix_samples
        })
        for cost_tech in cost_techs
    }, axis=1)
    xdata = pd.concat([xdata, costdata], axis=1)
    # ylabels = {}
    # for cost_tech in cost_techs:
    #     sep = ' ' if cost_tech['label'] in ['Battery', 'PV', 'Wind (land)'] else '\n'
    #     ylabels[cost_tech['label']] = f"{cost_tech['label']}{sep}cost [$/kW]"
    ## Combine
    dfplot = pd.concat([dfcap, xdata], axis=1)
    # ## Get the y ranges
    # ymax = ydata.max() + (0 if zoom else 100)
    # ymin = ydata.min()
    # yspan = ymax - ymin
    ### Plot it
    ycols = [c for c in dfplot if c.startswith('cap_')]
    xcols = xdata.columns
    ycols = ['cap_Gas', 'cap_Wind', 'cap_PV', 'cap_Storage', 'cap_Nuclear']
    xcols = ['gasprice', 'cost_Wind', 'cost_PV', 'cost_Battery', 'cost_Nuclear', 'demand', 'sc_wind']
    nrows = len(ycols)
    ncols = len(xcols)
    plt.close()
    f,ax = plt.subplots(
        nrows, ncols, figsize=(ncols*2, nrows*2), sharex='col', sharey='row',
        # gridspec_kw={'height_ratios':(yspan.values if zoom else ymax.values)},
    )
    for row, ycol in enumerate(ycols):
        for col, xcol in enumerate(xcols):
            ax[row,col].scatter(
                dfplot[xcol], dfplot[ycol], marker='o', lw=0, s=20,
                color='k', alpha=0.2,
            )
            corrcoef = {
                corr_method: dfplot[ycol].corr(dfplot[xcol], method=corr_method)
                for corr_method in corr_methods
            }
            for i, corr_method in enumerate(corr_methods):
                ax[row,col].annotate(
                    f"{corr_name[corr_method]}: {corrcoef[corr_method]:+.2f}",
                    (0.05, 0.95 - i * 0.12), xycoords='axes fraction',
                    ha='left', va='top', fontsize='large',
                    path_effects=[pe.withStroke(linewidth=3.0, foreground='w', alpha=0.9)],
                    # color=cmap(norm(corrcoef[corr_method])),
                    color=(
                        '0.7' if abs(corrcoef[corr_method]) <= 0.2
                        else cmap(norm(corrcoef[corr_method]))
                    ),
                    # path_effects=[pe.withStroke(linewidth=3.0, foreground=plt.cm.coolwarm(norm(corrcoef)), alpha=1)],
                    # color='k',
                )
            ## Formatting
            if col == 0:
                ax[row,col].set_ylabel(ycol[len('cap_'):])
                # if not zoom:
                #     ax[row,col].set_ylim(0, ymax[ydatum])
            if row == nrows - 1:
                ax[row,col].set_xlabel(x_labels.get(xcol,xcol))
    ## Formatting
    ax[2,0].annotate(
        f'Capacity additions through {t} [GW]', (-0.6, 0.5), xycoords='axes fraction',
        ha='center', va='center', annotation_clip=False,
        rotation=90, weight='bold', fontsize='xx-large',
    )
    ax[-1,0].annotate(
        f'{t}:', (0.0, -0.24), xycoords='axes fraction',
        ha='right', va='top', annotation_clip=False,
        weight='bold', fontsize='x-large',
    )
    ax[0,0].set_title(
        f"{nicelabels.get(caseprefix,caseprefix)} (n = {len(caseprefix_samples)})",
        x=0, ha='left',
    )
    if not zoom:
        ax.set_xlim(0)
        ax.set_ylim(0)
    reeds.plots.despine(ax)
    savename = (
        f"out_cap-scatter-x_everything-y_cap-corr_{','.join(list(corr_name.values()))}_{cmap.name}-"
        + ('zoom-' if zoom else '')
        + f"{nicelabels.get(caseprefix,caseprefix).title()}.png"
    ).replace(' ','')
    print(savename)
    plt.savefig(os.path.join(savepath, savename))
    plt.show()


#%% Scatter plot: Capacity vs inputs, markers colored by single correlation metric
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
x_datums = ['gasprice', 'demand', 'sc_wind']
cap_techs = [
    'PV',
    'Wind',
    'Storage',
    'Nuclear',
    'Gas+CCS',
    'Gas',
]
ycols = [f'cap_{i}' for i in cap_techs]
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

t = 2050
tstart = 2025
zoom = False
zoom = True
corr_method = 'spearman'
cmap = cmocean.tools.crop_by_percent(plt.cm.turbo, 10)
cmap = plt.cm.Spectral_r
cmap = plt.cm.turbo
cmap, cmin, cmax = plt.cm.coolwarm, -0.8, 0.8
# cmap = plt.cm.berlin
# cmap = cmocean.tools.crop_by_percent(
#     cmocean.tools.crop_by_percent(cmocean.cm.phase, 17, 'min'),
#     50, 'max'
# )
# cmap.name = 'phase_17_50'
# cmap = cmocean.tools.crop_by_percent(plt.cm.coolwarm, 10)
norm = mpl.colors.Normalize(vmin=cmin, vmax=cmax)
figscale = 1.3

nrows = len(ycols)
ncols = len(xcols)

# for caseprefix in casepaths[3:4]:
for caseprefix in casepaths:
    caseprefix_samples = sorted([s for (c,s) in dictin_cap_r if c == caseprefix])
    ## Marker size
    dfcap = pd.Series(
        {
            (tech, sample): (
                dictin_cap_r[caseprefix,sample].loc[
                    (dictin_cap_r[caseprefix,sample].t==t)
                    & (dictin_cap_r[caseprefix,sample].i==tech)
                ].MW.sum()
                - dictin_cap_r[caseprefix,sample].loc[
                    (dictin_cap_r[caseprefix,sample].t==tstart)
                    & (dictin_cap_r[caseprefix,sample].i==tech)
                ].MW.sum()
            ) / 1e3
            for sample in caseprefix_samples
            for tech in cap_techs
        }
    ).clip(lower=0).unstack(level=0)
    dfcap.columns = 'cap_' + dfcap.columns
    ### x-axis variables
    xdata = pd.concat({
        'gasprice': pd.Series({
            sample: dictin_gasprice[caseprefix,sample].mean(axis=1).loc[t]
            for sample in caseprefix_samples
        }),
        'demand': pd.Series({
            sample: dictin_demand[caseprefix,sample].groupby('t').sum().loc[t] / 1e3
            for sample in caseprefix_samples
        }),
        'sc_wind': pd.Series({
            sample: dictin_sc[caseprefix,sample].loc['wind-ons'].sum() / 1e3
            for sample in caseprefix_samples
        }),
    }, axis=1)
    ### Generation capex costs
    costdata = pd.concat({
        f"cost_{cost_tech['label']}": pd.Series({
            sample: dictin_cap_cost[caseprefix,sample].loc[t,cost_tech['tech_cost']]
            for sample in caseprefix_samples
        })
        for cost_tech in cost_techs
    }, axis=1)
    xdata = pd.concat([xdata, costdata], axis=1)
    # ylabels = {}
    # for cost_tech in cost_techs:
    #     sep = ' ' if cost_tech['label'] in ['Battery', 'PV', 'Wind (land)'] else '\n'
    #     ylabels[cost_tech['label']] = f"{cost_tech['label']}{sep}cost [$/kW]"
    ## Combine
    dfplot = pd.concat([dfcap, xdata], axis=1)
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
                ax[row,col].set_ylabel(ycol[len('cap_'):])
            if row == nrows - 1:
                ax[row,col].set_xlabel(
                    x_labels.get(xcol,xcol), rotation=45, rotation_mode='anchor', ha='right',
                )
            if xcol == 'cost_Nuclear':
                # ax[-1,col].xaxis.set_major_locator(mpl.ticker.MultipleLocator(3000))
                ax[-1,col].xaxis.set_major_locator(mpl.ticker.FixedLocator([3000, 5500]))
    ## Formatting
    ax[2,0].annotate(
        f'Capacity additions through {t} [GW]', (-0.95, 0.5), xycoords='axes fraction',
        ha='center', va='center', annotation_clip=False,
        rotation=90, weight='bold', fontsize='xx-large',
    )
    ax[-1,0].annotate(
        f'{t}:', (-0.35, -0.8), xycoords='axes fraction',
        ha='right', va='top', annotation_clip=False,
        weight='bold', fontsize='x-large',
    )
    ax[0,0].set_title(
        f"{nicelabels.get(caseprefix,caseprefix)} (n = {len(caseprefix_samples)})",
        x=0, ha='left',
    )
    if not zoom:
        ax.set_xlim(0)
        ax.set_ylim(0)
    reeds.plots.despine(ax)
    savename = (
        f"out_cap-scatter-x_everything-y_cap-corr_{corr_method}_{cmap.name}-"
        + ('zoom-' if zoom else '')
        + f"{nicelabels.get(caseprefix,caseprefix).title()}.png"
    ).replace(' ','')
    print(savename)
    plt.savefig(os.path.join(savepath, savename))
    plt.show()


#%% Scatter plot: More outputs vs inputs, markers colored by single correlation metric
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
x_datums = ['gasprice', 'demand', 'sc_wind']
cap_techs = [
    'PV',
    'Wind',
    'Storage',
    'Nuclear',
    'Gas+CCS',
    'Gas',
]
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

t = 2050
tstart = 2025
zoom = False
zoom = True
corr_method = 'spearman'
cmap = cmocean.tools.crop_by_percent(plt.cm.turbo, 10)
cmap = plt.cm.Spectral_r
cmap = plt.cm.turbo
cmap, cmin, cmax = plt.cm.coolwarm, -0.8, 0.8
# cmap = plt.cm.berlin
# cmap = cmocean.tools.crop_by_percent(
#     cmocean.tools.crop_by_percent(cmocean.cm.phase, 17, 'min'),
#     50, 'max'
# )
# cmap.name = 'phase_17_50'
# cmap = cmocean.tools.crop_by_percent(plt.cm.coolwarm, 10)
norm = mpl.colors.Normalize(vmin=cmin, vmax=cmax)
figscale = 1.3
co2years = range(2025,2051)

nrows = len(ycols)
ncols = len(xcols)

# for caseprefix in ['v20250829_mcK0_MC_flat_country']:
for caseprefix in casepaths:
    caseprefix_samples = sorted([s for (c,s) in dictin_cap_r if c == caseprefix])
    ## Marker size
    dfcap = pd.Series(
        {
            (tech, sample): (
                dictin_cap_r[caseprefix,sample].loc[
                    (dictin_cap_r[caseprefix,sample].t==t)
                    & (dictin_cap_r[caseprefix,sample].i==tech)
                ].MW.sum()
                - dictin_cap_r[caseprefix,sample].loc[
                    (dictin_cap_r[caseprefix,sample].t==tstart)
                    & (dictin_cap_r[caseprefix,sample].i==tech)
                ].MW.sum()
            ) / 1e3
            for sample in caseprefix_samples
            for tech in cap_techs
        }
    ).clip(lower=0).unstack(level=0)
    dfcap.columns = 'cap_' + dfcap.columns
    ## More outputs
    dfnpv = pd.Series(
        {sample: dictin_npv[caseprefix,sample].sum() for sample in caseprefix_samples},
        name='npv',
    ) / 1e3
    dfscoe = pd.Series(
        {sample: dictin_scoe[caseprefix,sample].loc[2050].sum() for sample in caseprefix_samples},
        name='scoe',
    )
    dfco2 = pd.Series(
        {
            sample: (
                dictin_emissions[caseprefix,sample]['process']['CO2']
                .reindex(co2years).interpolate('index').sum()
                / 1e9
            )
            for sample in caseprefix_samples
        },
        name='co2',
    )
    ### x-axis variables
    xdata = pd.concat({
        'gasprice': pd.Series({
            sample: dictin_gasprice[caseprefix,sample].mean(axis=1).loc[t]
            for sample in caseprefix_samples
        }),
        'demand': pd.Series({
            sample: dictin_demand[caseprefix,sample].groupby('t').sum().loc[t] / 1e3
            for sample in caseprefix_samples
        }),
        'sc_wind': pd.Series({
            sample: dictin_sc[caseprefix,sample].loc['wind-ons'].sum() / 1e3
            for sample in caseprefix_samples
        }),
    }, axis=1)
    ### Generation capex costs
    costdata = pd.concat({
        f"cost_{cost_tech['label']}": pd.Series({
            sample: dictin_cap_cost[caseprefix,sample].loc[t,cost_tech['tech_cost']]
            for sample in caseprefix_samples
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
    # ax[2,0].annotate(
    #     f'Capacity additions through {t} [GW]', (-0.95, 0.5), xycoords='axes fraction',
    #     ha='center', va='center', annotation_clip=False,
    #     rotation=90, weight='bold', fontsize='xx-large',
    # )
    ax[-1,0].annotate(
        f'{t}:', (-0.35, -0.8), xycoords='axes fraction',
        ha='right', va='top', annotation_clip=False,
        weight='bold', fontsize='x-large',
    )
    ax[0,0].set_title(
        f"{nicelabels.get(caseprefix,caseprefix)} (n = {len(caseprefix_samples)})",
        x=0, ha='left',
    )
    if not zoom:
        ax.set_xlim(0)
        ax.set_ylim(0)
    reeds.plots.despine(ax)
    savename = (
        f"out_everything-scatter-x_everything-y_cap-corr_{corr_method}_{cmap.name}-"
        + ('zoom-' if zoom else '')
        + f"{nicelabels.get(caseprefix,caseprefix).title()}.png"
    ).replace(' ','')
    print(savename)
    plt.savefig(os.path.join(savepath, savename))
    plt.show()


#%%
#%% Scatter by STATE: y = tech cost, x = gas price or avail, size = demand, color = cap
tech_cap, cost_tech = 'Nuclear', 'nuclear'
tech_cap, cost_tech = 'Gas', 'gas-cc'
tech_cap, cost_tech = 'Storage', 'battery_li'
tech_cap, cost_tech = 'PV', 'upv_3'
tech_cap, cost_tech = 'Wind', 'wind-ons_5'
t = 2050
tstart = 2025
zoom = True
xaxis, yaxis = 'sc_wind', 'demand'
xaxis, yaxis = 'sc_wind', 'capcost'
xaxis, yaxis = 'sc_wind', 'gasprice'
xaxis, yaxis = 'gasprice', 'demand'
xaxis, yaxis = 'gasprice', 'capcost'
markersize = 'demand'
markersize = 5
markersize = 'cap'
color = 'cap'
sizescale = 0.3
cmap = cmocean.cm.rain
cmap = plt.cm.turbo
color_share = 0
# color_sort: Use with caution as setting to True makes the plot look less random
color_sort = False
color_sort = True

## Get plot info
nrows = state_subplots['row'].max() + 1
ncols = state_subplots['col'].max() + 1
scale = 1
states = sorted(state_subplots.index.tolist())
rs = hierarchy.index.values
sharey = True if yaxis in ['capcost', 'gasprice'] else False
sharex = True if xaxis in ['capcost', 'gasprice'] else False
axislabels = {
    'demand':f'{t} demand [TWh]',
    'gasprice':f'{t} gas price [$/MMBtu]',
    'sc_wind':'Wind avail [GW]',
}
ylabel = (
    f'{t} {tech_cap.lower()} cost [$kW]' if yaxis == 'capcost'
    else axislabels.get(yaxis,yaxis)
)
xlabel = (
    f'{t} {tech_cap.lower()} cost [$kW]' if xaxis == 'capcost'
    else axislabels.get(xaxis,xaxis)
)

# for caseprefix in ['v20251014_mcK0_MC_flat_state_SitingDemand']:
for caseprefix in ['v20250829_mcK0_MC_flat_state_MC']:
# for caseprefix in casepaths:
    caseprefix_samples = sorted([s for (c,s) in dictin_cap_r if c == caseprefix])
    savename = (
        f"out_cap-scatter-x_{xaxis}-y_{yaxis+(('_'+tech_cap) if yaxis == 'capcost' else '')}-"
        f"size_{markersize+(('_'+tech_cap) if markersize == 'cap' else '')}-"
        f"color_{color+(('_'+tech_cap) if color == 'cap' else '')}-"
        # + ('zoom-' if zoom else '')
        f"colorshare{int(color_share)}-"
        f"colorsort{int(color_sort)}-"
        + f"{nicelabels.get(caseprefix,caseprefix).title()}.png"
    ).replace(' ','')
    print(savename)
    ## Capacity
    dfcap = pd.concat(
        {
            sample: (
                dictin_cap_r[caseprefix,sample].loc[
                    (dictin_cap_r[caseprefix,sample].t==t)
                    & (dictin_cap_r[caseprefix,sample].i==tech_cap)
                ].set_index('r').MW.reindex(rs).fillna(0)
                - dictin_cap_r[caseprefix,sample].loc[
                    (dictin_cap_r[caseprefix,sample].t==tstart)
                    & (dictin_cap_r[caseprefix,sample].i==tech_cap)
                ].set_index('r').MW.reindex(rs).fillna(0)
            ) / 1e3
            for sample in caseprefix_samples
        }, axis=1
    )
    dfcap.index = dfcap.index.map(hierarchy.st).rename('st')
    dfcap = dfcap.groupby('st').sum().T
    ## PV/wind fraction
    dfpvfrac = pd.concat(
        {
            sample: (
                dictin_cap_r[caseprefix,sample].loc[
                    (dictin_cap_r[caseprefix,sample].t==t)
                    & (dictin_cap_r[caseprefix,sample].i=='PV')
                ].set_index('r').MW.reindex(rs).fillna(0)
            ) / (
                dictin_cap_r[caseprefix,sample].loc[
                    (dictin_cap_r[caseprefix,sample].t==t)
                    & (dictin_cap_r[caseprefix,sample].i.isin(['PV','Wind']))
                ].groupby('r').MW.sum().reindex(rs).fillna(0)
            )
            for sample in caseprefix_samples
        }, axis=1
    )
    ### Other dimensions
    dictplot = {
        'cap': dfcap,
        'pvfrac': dfpvfrac,
        'gasprice': pd.Series({
            sample: dictin_gasprice[caseprefix,sample].mean(axis=1).loc[t]
            for sample in caseprefix_samples
        }),
        'demand': pd.concat({
            sample: (
                dictin_demand[caseprefix,sample].to_frame()
                .assign(st=dictin_demand[caseprefix,sample].index.get_level_values('r').map(hierarchy.st))
                .xs(t,0,'t')
                .groupby('st').TWh.sum()
            )
            for sample in caseprefix_samples
        }, axis=1).T,
        'sc_wind': pd.concat({
            sample: (
                dictin_sc[caseprefix,sample].to_frame()
                .assign(st=dictin_sc[caseprefix,sample].index.get_level_values('r').map(hierarchy.st))
                .loc['wind-ons']
                .groupby('st').value.sum()
            )
            for sample in caseprefix_samples
        }, axis=1).T,
        'capcost': pd.Series({
            sample: dictin_cap_cost[caseprefix,sample].loc[t,cost_tech]
            for sample in caseprefix_samples
        })
    }
    ## More settings
    vmin = 0
    vmax = dictplot['cap'].max().max()
    scatter_nonzero = {}
    ### Plot it
    plt.close()
    f,ax = plt.subplots(
        nrows, ncols, figsize=(ncols*scale, nrows*scale),
        sharex=sharex, sharey=sharey,
        gridspec_kw={'hspace':(0.4 if sharex else 0.4), 'wspace':(None if sharey else 0.6)},
    )
    for state in states:
        _ax = ax[state_subplots.loc[state,'ax']]
        ## Combine data for state
        dfplot = pd.concat({
            'cap': dictplot['cap'][state],
            'markersize': (
                pd.Series({sample:markersize for sample in caseprefix_samples})
                if isinstance(markersize, (float,int))
                else dictplot[markersize][state]
            ),
            'color': dictplot[color][state],
            'x': (dictplot[xaxis][state] if xaxis in ['demand', 'sc_wind'] else dictplot[xaxis]),
            'y': (dictplot[yaxis][state] if yaxis in ['demand', 'sc_wind'] else dictplot[yaxis]),
        }, axis=1)
        if color_sort:
            dfplot = dfplot.sort_values('color')
        dfnonzero = dfplot.loc[dfplot.cap > 0]
        dfzero = dfplot.loc[dfplot.cap <= 0]
        ## x's for zero
        scatter_zero = _ax.scatter(
            dfzero.x.values, dfzero.y.values,
            marker='x', alpha=0.8, color='k', lw=0.5, s=5,
            zorder=1e3
        )
        ## Circles for nonzero
        scatter_nonzero[state] = _ax.scatter(
            dfnonzero.x.values, dfnonzero.y.values,
            s=dfnonzero.markersize.values * sizescale,
            c=dfnonzero['color'].values,
            cmap=cmap,
            vmin=(0 if color_share else None),
            vmax=(vmax if color_share else None),
            zorder=1e4,
        )
        ## Formatting
        _ax.annotate(
            state,
            (0.05, 0.95), xycoords='axes fraction', ha='left', va='top',
            color='k', fontsize='large',
            path_effects=[pe.withStroke(linewidth=3.0, foreground='w', alpha=0.9)],
            zorder=1e6,
        )
        _ax.tick_params(axis='both', which='major', labelsize=8)
    ## Turn off unused axes
    subplots_used = state_subplots['ax'].tolist()
    for row in range(nrows):
        for col in range(ncols):
            if (row,col) not in subplots_used:
                ax[row,col].axis('off')
    ## Formatting
    ax[0,0].annotate(
        f"{nicelabels.get(caseprefix,caseprefix)} (n = {len(caseprefix_samples)})",
        (0.05, 0.95), xycoords='axes fraction', ha='left', va='top',
        color='k', fontsize='x-large',
    )
    ax[state_subplots.loc['MS','ax']].set_xlabel(xlabel)
    ax[state_subplots.loc['OR','ax']].set_ylabel(ylabel)
    ## Manual cleanups
    if xaxis == 'sc_wind':
        ax[state_subplots.loc['WA','ax']].set_xticks([150,250])
        ax[state_subplots.loc['ID','ax']].set_xticks([100,300])
        ax[state_subplots.loc['MT','ax']].set_xticks([500,700])
        ax[state_subplots.loc['NV','ax']].set_xticks([100,300])
        ax[state_subplots.loc['IN','ax']].set_xticks([50,150])
        ax[state_subplots.loc['VA','ax']].set_xticks([50,150])
        ax[state_subplots.loc['MO','ax']].set_xticks([100,300])
        ax[state_subplots.loc['TX','ax']].set_xticks([800,1200])
        ax[state_subplots.loc['OK','ax']].set_xticks([100,300])
        ax[state_subplots.loc['LA','ax']].set_xticks([50,150])
    ## Legend
    dfstats = pd.concat(dictplot).loc['cap']
    state = dfstats.max().idxmax()
    handles, labels = scatter_nonzero[state].legend_elements(
        prop='sizes', color='C7',
        # num=int(dfstats.max().max() // 10),
        # num=3,
        # num=[10, 20, 40, int(dfstats.max().max())],
        # num=[10, 20, 40, max(80, int(dfstats.max().max()))],
        num=[10, 20, 40, 80],
        func=lambda x: x/sizescale,
    )
    ## Add the zero
    ## Add the zero
    handles = [
        mpl.lines.Line2D(
            [], [], marker='x', alpha=0.8, color='k', markeredgewidth=0.5, lw=0,
            markersize=np.sqrt(5),
        )
    ] + handles
    labels = ['0'] + labels
    # handles = [
    #     mpl.lines.Line2D(
    #         [], [], marker='o', color='C7', markeredgewidth=0, lw=0,
    #         markersize=np.sqrt(i), label=int(i),
    #     ) for i in [10, 20, 50, 100]
    #     # np.arange(10, dfstats.max().max(), 10)
    # ] 
    # legend = ax[state_subplots.loc['DE','ax']].legend(
    legend = ax[-1,-2].legend(
        handles=handles, labels=labels,
        loc='lower left', bbox_to_anchor=(1,-0.5), frameon=False,
        # title=f'{t}\n{tech_cap}\ncapacity\n[GW]',
        title=f'Absolute\n{tech_cap.lower()}\nadditions\nthrough\n{t}\n[GW]',
        handletextpad=0.5,
    )
    reeds.plots.despine(ax)
    # plt.savefig(os.path.join(savepath, savename))
    plt.show()

#%%
dfplot

#%% Scatter by STATE: y = tech cost, x = gas price or avail, size = demand, color = PV frac
t = 2050
zoom = True
xaxis, yaxis = 'sc_wind', 'demand'
xaxis, yaxis = 'sc_wind', 'capcost'
xaxis, yaxis = 'sc_wind', 'gasprice'
xaxis, yaxis = 'gasprice', 'capcost'
xaxis, yaxis = 'gasprice', 'demand'
markersize = 'demand'
markersize = 5
markersize = 'cap'
color = 'pvfrac'
sizescale = 0.3
cmap = cmocean.cm.rain
cmap = plt.cm.turbo
# color_sort: Use with caution as setting to True makes the plot look less random
color_sort = True
color_sort = False

## Get plot info
nrows = state_subplots['row'].max() + 1
ncols = state_subplots['col'].max() + 1
scale = 1
states = sorted(state_subplots.index.tolist())
rs = hierarchy.index.values
sharey = True if yaxis in ['capcost', 'gasprice'] else False
sharex = True if xaxis in ['capcost', 'gasprice'] else False
axislabels = {
    'demand':f'{t} demand [TWh]',
    'gasprice':f'{t} gas price [$/MMBtu]',
    'sc_wind':'Wind avail [GW]',
}
ylabel = axislabels.get(yaxis,yaxis)
xlabel = axislabels.get(xaxis,xaxis)

# for caseprefix in ['v20251014_mcK0_MC_flat_state_SitingDemand']:
# for caseprefix in ['v20250829_mcK0_MC_flat_state_MC']:
for caseprefix in casepaths:
    caseprefix_samples = sorted([s for (c,s) in dictin_cap_r if c == caseprefix])
    savename = (
        f"out_pvfrac-scatter-x_{xaxis}-y_{yaxis+(('_'+tech_cap) if yaxis == 'capcost' else '')}-"
        f"size_cap_PV,Wind-"
        f"color_pvfrac-"
        # + ('zoom-' if zoom else '')
        f"colorsort{int(color_sort)}-"
        + f"{nicelabels.get(caseprefix,caseprefix).title()}.png"
    ).replace(' ','')
    print(savename)
    ## Capacity
    dfcap = pd.concat(
        {
            sample: (
                dictin_cap_r[caseprefix,sample]
                .assign(st=dictin_cap_r[caseprefix,sample].r.map(hierarchy.st))
                .loc[
                    (dictin_cap_r[caseprefix,sample].t==t)
                    & (dictin_cap_r[caseprefix,sample].i.isin(['PV','Wind']))
                ].groupby('st').MW.sum().reindex(states).fillna(0)
            ) / 1e3
            for sample in caseprefix_samples
        }, axis=1
    ).T
    ## PV/wind fraction
    dfpvfrac = pd.concat(
        {
            sample: (
                dictin_cap_r[caseprefix,sample]
                .assign(st=dictin_cap_r[caseprefix,sample].r.map(hierarchy.st))
                .loc[
                    (dictin_cap_r[caseprefix,sample].t==t)
                    & (dictin_cap_r[caseprefix,sample].i=='PV')
                ].groupby('st').MW.sum().reindex(states).fillna(0)
            ) / (
                dictin_cap_r[caseprefix,sample]
                .assign(st=dictin_cap_r[caseprefix,sample].r.map(hierarchy.st))
                .loc[
                    (dictin_cap_r[caseprefix,sample].t==t)
                    & (dictin_cap_r[caseprefix,sample].i.isin(['PV','Wind']))
                ].groupby('st').MW.sum().reindex(states).fillna(0)
            )
            for sample in caseprefix_samples
        }, axis=1
    ).T
    ### Other dimensions
    dictplot = {
        'cap': dfcap,
        'pvfrac': dfpvfrac,
        'gasprice': pd.Series({
            sample: dictin_gasprice[caseprefix,sample].mean(axis=1).loc[t]
            for sample in caseprefix_samples
        }),
        'demand': pd.concat({
            sample: (
                dictin_demand[caseprefix,sample].to_frame()
                .assign(st=dictin_demand[caseprefix,sample].index.get_level_values('r').map(hierarchy.st))
                .xs(t,0,'t')
                .groupby('st').TWh.sum()
            )
            for sample in caseprefix_samples
        }, axis=1).T,
        'sc_wind': pd.concat({
            sample: (
                dictin_sc[caseprefix,sample].to_frame()
                .assign(st=dictin_sc[caseprefix,sample].index.get_level_values('r').map(hierarchy.st))
                .loc['wind-ons']
                .groupby('st').value.sum()
            )
            for sample in caseprefix_samples
        }, axis=1).T,
        'capcost': pd.Series({
            sample: dictin_cap_cost[caseprefix,sample].loc[t,cost_tech]
            for sample in caseprefix_samples
        })
    }
    ## More settings
    vmin = 0
    vmax = dictplot['cap'].max().max()
    scatter_nonzero = {}
    ### Plot it
    plt.close()
    f,ax = plt.subplots(
        nrows, ncols, figsize=(ncols*scale, nrows*scale),
        sharex=sharex, sharey=sharey,
        gridspec_kw={'hspace':(0.4 if sharex else 0.4), 'wspace':(None if sharey else 0.6)},
    )
    for state in states:
        _ax = ax[state_subplots.loc[state,'ax']]
        ## Combine data for state
        dfplot = pd.concat({
            'cap': dictplot['cap'][state],
            'pvfrac': dictplot['pvfrac'][state],
            'markersize': (
                pd.Series({sample:markersize for sample in caseprefix_samples})
                if isinstance(markersize, (float,int))
                else dictplot[markersize][state]
            ),
            'color': dictplot[color][state],
            'x': (dictplot[xaxis][state] if xaxis in ['demand', 'sc_wind'] else dictplot[xaxis]),
            'y': (dictplot[yaxis][state] if yaxis in ['demand', 'sc_wind'] else dictplot[yaxis]),
        }, axis=1)
        if color_sort:
            dfplot = dfplot.sort_values('color')
        # dfnonzero = dfplot.loc[dfplot.cap > 0]
        # dfzero = dfplot.loc[dfplot.cap <= 0]
        # ## x's for zero
        # scatter_zero = _ax.scatter(
        #     dfzero.x.values, dfzero.y.values,
        #     marker='x', alpha=0.8, color='k', lw=0.5, s=5,
        #     zorder=1e3
        # )
        ## Circles for nonzero
        scatter_nonzero[state] = _ax.scatter(
            dfplot.x.values, dfplot.y.values,
            s=dfplot.markersize.values * sizescale,
            c=dfplot['color'].values,
            cmap=cmap,
            vmin=0, vmax=1,
            zorder=1e4,
        )
        ## Formatting
        _ax.annotate(
            state,
            (0.05, 0.95), xycoords='axes fraction', ha='left', va='top',
            color='k', fontsize='large',
            path_effects=[pe.withStroke(linewidth=3.0, foreground='w', alpha=0.9)],
            zorder=1e6,
        )
        _ax.tick_params(axis='both', which='major', labelsize=8)
    ## Turn off unused axes
    subplots_used = state_subplots['ax'].tolist()
    for row in range(nrows):
        for col in range(ncols):
            if (row,col) not in subplots_used:
                ax[row,col].axis('off')
    ## Formatting
    ax[0,0].annotate(
        f"{nicelabels.get(caseprefix,caseprefix)} (n = {len(caseprefix_samples)})",
        (0.05, 0.95), xycoords='axes fraction', ha='left', va='top',
        color='k', fontsize='x-large',
    )
    ax[state_subplots.loc['MS','ax']].set_xlabel(xlabel)
    ax[state_subplots.loc['OR','ax']].set_ylabel(ylabel)
    ## Manual cleanups
    if xaxis == 'sc_wind':
        ax[state_subplots.loc['WA','ax']].set_xticks([150,250])
        ax[state_subplots.loc['ID','ax']].set_xticks([100,300])
        ax[state_subplots.loc['MT','ax']].set_xticks([500,700])
        ax[state_subplots.loc['NV','ax']].set_xticks([100,300])
        ax[state_subplots.loc['IN','ax']].set_xticks([50,150])
        ax[state_subplots.loc['VA','ax']].set_xticks([50,150])
        ax[state_subplots.loc['MO','ax']].set_xticks([100,300])
        ax[state_subplots.loc['TX','ax']].set_xticks([800,1200])
        ax[state_subplots.loc['OK','ax']].set_xticks([100,300])
        ax[state_subplots.loc['LA','ax']].set_xticks([50,150])
    ## Legend
    dfstats = pd.concat(dictplot).loc['cap']
    state = dfstats.max().idxmax()
    handles, labels = scatter_nonzero[state].legend_elements(
        prop='sizes', color='C7',
        # num=int(dfstats.max().max() // 10),
        num=5,
        # num=[10, 20, 40, int(dfstats.max().max())],
        # num=[10, 20, 40, max(80, int(dfstats.max().max()))],
        # num=[10, 20, 40, 80],
        func=lambda x: x/sizescale,
    )
    legend = ax[-1,-2].legend(
        handles=handles, labels=labels,
        loc='lower left', bbox_to_anchor=(1,-0.5), frameon=False,
        title=f'{t}\nPV+wind\ncapacity\n[GW]',
        handletextpad=0.5,
    )
    reeds.plots.despine(ax)
    plt.savefig(os.path.join(savepath, savename))
    plt.show()


#%%
#%%# Scatter plot: Different techs against each other
t = 2050
gen_techs = ['PV', 'Wind', 'Storage', 'Nuclear', 'Gas']
markersize = 'demand'
color = 'gasprice'
scale = 1
sizescale = 1e-3
color_share = True
vmin = min([dictin_gasprice[key].mean(axis=1).loc[t] for key in dictin_gasprice])
vmax = max([dictin_gasprice[key].mean(axis=1).loc[t] for key in dictin_gasprice])
cmap = plt.cm.turbo

for caseprefix in casepaths:
    caseprefix_samples = sorted([s for (c,s) in dictin_cap_r if c == caseprefix])

    ## Capacity
    dfcap = pd.concat(
        {
            sample: (
                dictin_cap_r[caseprefix,sample].loc[
                    (dictin_cap_r[caseprefix,sample].t==t)
                    & (dictin_cap_r[caseprefix,sample].i.isin(gen_techs))
                ].groupby('i').MW.sum().reindex(gen_techs)
                - dictin_cap_r[caseprefix,sample].loc[
                    (dictin_cap_r[caseprefix,sample].t==tstart)
                    & (dictin_cap_r[caseprefix,sample].i.isin(gen_techs))
                ].groupby('i').MW.sum().reindex(gen_techs)
            ) / 1e3
            for sample in caseprefix_samples
            for tech in gen_techs
        }, axis=1
    ).T
    ## Other dimensions
    dfplot = pd.concat(
        {
            'gasprice': pd.Series({
                sample: dictin_gasprice[caseprefix,sample].mean(axis=1).loc[t]
                for sample in caseprefix_samples
            }),
            'demand': pd.Series({
                sample: dictin_demand[caseprefix,sample].groupby('t').sum().loc[t]
                for sample in caseprefix_samples
            }),
        },
        axis=1,
    )

    ## Plot it
    nrows = ncols = len(gen_techs)
    plt.close()
    f,ax = plt.subplots(
        nrows, ncols, figsize=(ncols*scale, nrows*scale),
        # sharex='col', sharey='row',
        sharex=True, sharey=True,
    )
    for row, ytech in enumerate(gen_techs):
        for col, xtech in enumerate(gen_techs):
            _ax = ax[row,col]
            if col >= row:
                _ax.axis('off')
                continue
            scatter = _ax.scatter(
                dfcap[xtech].values, dfcap[ytech].values,
                s=dfplot[markersize].values * sizescale,
                c=dfplot[color].values,
                cmap=cmap,
                vmin=vmin,
                vmax=vmax,
                zorder=1e4,
            )
            ## Formatting
            if row == nrows - 1:
                _ax.set_xlabel(xtech)
            if col == 0:
                _ax.set_ylabel(ytech)
            if (row, col) == (0, 0):
                _ax.set_title(
                    f"{nicelabels.get(caseprefix,caseprefix)} (n = {len(caseprefix_samples)})",
                    x=0, ha='left',
                )
    ## Formatting
    reeds.plots.despine(ax)
    plt.show()


#%% Simple histograms of gen capacity at different resolutions
t = 2050
tech = 'Wind'
levels = ['st', 'country']
rs = hierarchy.index.values
bins = 41

for caseprefix in casepaths:
    caseprefix_samples = sorted([s for (c,s) in dictin_cap_r if c == caseprefix])
    for level in levels:
        regions = sorted(hierarchy[level].unique())
        nrows = len(regions)
        ## Capacity
        dfcap = pd.concat(
            {
                sample: (
                    dictin_cap_r[caseprefix,sample].loc[
                        (dictin_cap_r[caseprefix,sample].t==t)
                        & (dictin_cap_r[caseprefix,sample].i==tech)
                    ].set_index('r').MW.reindex(rs).fillna(0)
                    - dictin_cap_r[caseprefix,sample].loc[
                        (dictin_cap_r[caseprefix,sample].t==tstart)
                        & (dictin_cap_r[caseprefix,sample].i==tech)
                    ].set_index('r').MW.reindex(rs).fillna(0)
                ) / 1e3
                for sample in caseprefix_samples
            }, axis=1
        )
        dfcap.index = dfcap.index.map(hierarchy[level]).rename(level)
        dfcap = dfcap.groupby(level).sum().T

        ## Plot it
        plt.close()
        f,ax = plt.subplots(nrows, figsize=(5, 0.15*nrows))
        for row, region in enumerate(regions):
            xmax = dfcap[region].max()
            _ax = ax[row] if nrows > 1 else ax
            _ax.hist(dfcap[region].values, bins=bins)
            _ax.set_xlim(0, xmax)
            _ax.set_yticks([])
            _ax.set_xticks([])
            # _ax.annotate(
            #     region, (-0.01, 0), xycoords='axes fraction',
            #     ha='right', annotation_clip=False,
            # )
            _ax.annotate(
                f'{xmax:>3.0f} ' + f'({region})',
                (1.01, 0), xycoords='axes fraction',
                ha='left', va='center',annotation_clip=False,
            )
        ## Formatting
        reeds.plots.despine(ax, left=False, bottom=False)
        (ax[0] if nrows > 1 else ax).set_title(
            f"{tech}, {nicelabels.get(caseprefix,caseprefix)} "
            f"(n = {len(caseprefix_samples)})",
            x=0, ha='left',
        )
        plt.show()


#%% Quantify variability / central
t = 2050
tech = 'Wind'
levels = ['r', 'st', 'transreg', 'country']
rs = hierarchy.index.values
bins = 41
min_gw_median = 1

ncols = len(levels)
percentiles = [0.1, 0.9]


for tech in [
    'PV',
    'Wind',
    'Storage',
    # 'Nuclear',
    'Gas',
]:
    ## Set up plot
    plt.close()
    f,ax = plt.subplots(1, ncols, figsize=(8, 2.5), sharey=True)
    for caseprefix in casepaths:
        caseprefix_samples = sorted([s for (c,s) in dictin_cap_r if c == caseprefix])
        for col, level in enumerate(levels):
            _ax = ax[col]
            regions = sorted(hierarchy[level].unique())
            ## Capacity
            dfcap = pd.concat(
                {
                    sample: (
                        dictin_cap_r[caseprefix,sample].loc[
                            (dictin_cap_r[caseprefix,sample].t==t)
                            & (dictin_cap_r[caseprefix,sample].i==tech)
                        ].set_index('r').MW.reindex(rs).fillna(0)
                        - dictin_cap_r[caseprefix,sample].loc[
                            (dictin_cap_r[caseprefix,sample].t==tstart)
                            & (dictin_cap_r[caseprefix,sample].i==tech)
                        ].set_index('r').MW.reindex(rs).fillna(0)
                    ) / 1e3
                    for sample in caseprefix_samples
                }, axis=1
            )
            dfcap.index = dfcap.index.map(hierarchy[level]).rename(level)
            dfcap = dfcap.groupby(level).sum().T

            keep = dfcap.median().loc[dfcap.median() >= min_gw_median].index

            dfdescribe = dfcap[keep].describe(percentiles=percentiles)
            # dfplot = (
            #     (dfdescribe.loc['90%'] - dfdescribe.loc['10%']) / dfdescribe.loc['50%']
            # ).replace(np.inf, np.nan).dropna().sort_values()
            # ylabel = '(P90 – P10) / P50'
            dfplot = (
                dfcap[keep].std() / dfcap[keep].mean()
            ).replace(np.inf, np.nan).dropna().sort_values()
            ylabel = 'stdev / mean'
            # dfplot = dfdescribe.loc['90%'] / dfdescribe.loc['10%']
            # dfdescribe.loc['50%'].sort_values()

            ## Plot it
            _ax.plot(
                range(1, len(dfplot)+1), dfplot.values,
                marker='o', markersize=5, markeredgewidth=0,
                color=colors[caseprefix],
                label=f"{nicelabels.get(caseprefix,caseprefix)} (n = {len(caseprefix_samples)})",
            )
            _ax.annotate(
                level, (0.05, 0.97), xycoords='axes fraction', fontsize='large', va='top',
            )
    ## Formatting
    reeds.plots.despine(ax)
    ax[0].set_title(
        f"{tech} additions",
        # f", {nicelabels.get(caseprefix,caseprefix)} "
        # f"(n = {len(caseprefix_samples)})",
        x=0, ha='left', fontsize='x-large', weight='bold',
    )
    ax[0].set_ylabel(ylabel)
    ax[0].set_xlabel('Regions', x=0, ha='left')
    ax[0].set_ylim(0, 2)
    ax[0].yaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(2))
    ax[-1].legend(
        loc='center left', bbox_to_anchor=(1, 0.5), frameon=False,
    )
    plt.show()


#%% Rug plot
# (
#     dictin_cap_r[caseprefix,caseprefix_samples[0]].loc[
#         (dictin_cap_r[caseprefix,caseprefix_samples[0]].i=='Geothermal')
#         & (dictin_cap_r[caseprefix,caseprefix_samples[0]].t==2050)
#     ].MW.sum()
#     - dictin_cap_r[caseprefix,caseprefix_samples[0]].loc[
#         (dictin_cap_r[caseprefix,caseprefix_samples[0]].i=='Geothermal')
#         & (dictin_cap_r[caseprefix,caseprefix_samples[0]].t==2020)
#     ].MW.sum()
# )



#%%### Costs, emissions, reliability ######
### Set up plots
tstart = 2020
alpha = 0.5
ymin = 0.
numbins = 71
xscale = 2
percentiles = [0.025, 0.05, 0.1, 0.25, 0.75, 0.9, 0.95, 0.975]
decimals = -1

# plotcaseprefixes = list(casepaths.keys())
# plotlabels = nicelabels

plotcaseprefixes = [
    'v20250829_mcK0_MC_flat_state_IRA',
    'v20250829_mcK0_MC_flat_state_MC',
    'v20250829_mcK0_MC_flat_state_CAA0',
]
plotlabels = {
    **nicelabels,
    'v20250829_mcK0_MC_flat_state_MC': 'Flat state (current policies)',
}

# plotcaseprefixes = [
#     'v20250829_mcK0_MC_flat_state_MC',
#     'v20250829_mcK0_MC_flat_country',
#     'v20250911_mcK0_MC_tri_state',
#     'v20250922_mcK0_MC_tri_country',
# ]
# plotlabels = nicelabels

#%% SCOE
dictplot = {}
for caseprefix in casepaths:
    caseprefix_samples = sorted([s for (c,s) in dictin_scoe if c == caseprefix])
    # print(f'{caseprefix}: {(len(caseprefix_samples))}')
    dictplot[caseprefix] = pd.concat({
        sample: dictin_scoe[caseprefix,sample].sum(axis=1)
        for sample in caseprefix_samples
    }, axis=1)

dfplot = pd.concat(dictplot, axis=1, names=('caseprefix','sample'))

ymax = dfplot.max().max()
bins = np.linspace(ymin, ymax, numbins)

### Plot it
plt.close()
f,ax = plt.subplots(figsize=(5, 3.75))
for i, caseprefix in enumerate(plotcaseprefixes):
    df = dfplot[caseprefix].reindex(years).fillna(0)
    ## Fill between max and min
    ax.fill_between(
        df.index, df.max(axis=1), df.min(axis=1),
        color=colors[caseprefix], alpha=alpha, lw=0,
        label=f'{plotlabels.get(caseprefix,caseprefix)} ({df.shape[1]})',
    )
    ## Max and min lines
    for agg in ['min', 'max']:
        ax.plot(
            df.index, df.agg(agg, axis=1), lw=0.5,
            color=colors[caseprefix],
            label='_nolabel',
        )
    ## Lines
    # df.plot(
    #     ax=ax, legend=False,
    #     lw=0.5, color='k', alpha=0.25,
    # )
    ## Histogram
    reeds.plots.hist_last(
        ax, df, color=colors[caseprefix], bins=bins, alpha=alpha,
        xpad=1+((xscale+0.5)*i), xscale=xscale,
    )
## Legend
ax.legend(
    frameon=False, loc='lower left', bbox_to_anchor=(0,0),
    fontsize='x-large',
    handletextpad=0.3, handlelength=0.7,
)
## Formatting
ax.set_xlim(tstart)
ax.set_ylabel('System cost [$/MWh]')
ax.set_ylim(0)
ax.yaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(2))
ax.set_xticks([2020,2030,2040,2050])
reeds.plots.despine(ax)
plt.draw()
reeds.plots.shorten_years(ax)
savename = (
    f"out_scoe-line_country-"
    f"{','.join([plotlabels.get(c,c).title().replace(' ','') for c in plotcaseprefixes])}.png"
)
print(savename)
plt.savefig(os.path.join(savepath, savename))
plt.show()

#%% NPV
dictplot = {}
for caseprefix in casepaths:
    caseprefix_samples = sorted([s for (c,s) in dictin_npv if c == caseprefix])
    # print(f'{caseprefix}: {(len(caseprefix_samples))}')
    dictplot[caseprefix] = pd.concat({
        sample: dictin_npv[caseprefix,sample]
        for sample in caseprefix_samples
    }, axis=1)

dfplot = pd.concat(dictplot, axis=1, names=('caseprefix','sample')).sum()
describe = (
    dfplot.groupby('caseprefix')
    .describe(percentiles=percentiles)
    .loc[plotcaseprefixes].T
    # .round(0).astype(int)
)
print(describe.round(-1).astype(int).rename(columns=nicelabels))

ymax = dfplot.max()
bins = np.linspace(ymin, ymax, numbins)
ynote = dfplot.min()

### Plot it
plt.close()
f,ax = plt.subplots(figsize=(3, 3.75))
for x, caseprefix in enumerate(plotcaseprefixes):
    df = dfplot[caseprefix]
    ## Histogram
    hist_val, hist_y = np.histogram(df.values, bins=bins)
    height = hist_y[1] - hist_y[0]
    ax.barh(
        y=hist_y[:-1],
        width=(hist_val / max(hist_val) * 0.9),
        height=height,
        align='edge',
        left=x,
        color=colors[caseprefix],
        label=f'{plotlabels.get(caseprefix,caseprefix)} ({len(df)})',
    )
    ## Values
    note = (
        f"{np.around(describe.loc['mean',caseprefix], decimals):.0f} (mean)\n"
        f"{np.around(describe.loc['50%',caseprefix], decimals):.0f} (50%)\n"
        f"{np.around(describe.loc['5%',caseprefix], decimals):.0f}"
        f"–{np.around(describe.loc['95%',caseprefix], decimals):.0f} (central 90%)"
    )
    # ax.annotate(
    #     note, (x, ynote),
    #     xytext=(0, -10), textcoords='offset points',
    #     ha='left', va='top', rotation=90,
    # )
    print()
    print(plotlabels.get(caseprefix,caseprefix))
    print(note)
## Formatting
ax.set_xticks(range(len(plotcaseprefixes)))
ax.set_xticklabels(
    [
        f'{plotlabels.get(caseprefix,caseprefix)} ({len(dfplot[caseprefix])})'
        for caseprefix in plotcaseprefixes
    ],
    rotation=45, rotation_mode='anchor', ha='right',
)
for xtick, caseprefix in zip(ax.get_xticklabels(), plotcaseprefixes):
    xtick.set_color(colors[caseprefix])
ax.set_ylabel('Net present value of system\ncost through 2050 [$B]')
ax.set_ylim(0)
ax.set_xlim(-0.1, len(plotcaseprefixes))
ax.yaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(2))
reeds.plots.despine(ax)
savename = (
    f"out_npv-line_country-"
    f"{','.join([plotlabels.get(c,c).title().replace(' ','') for c in plotcaseprefixes])}.png"
)
print(savename)
plt.savefig(os.path.join(savepath, savename))
plt.show()


#%% NPV of system, health, and climate costs
pv_year = 2025
lastyear = 2050
discountrate_social = 0.02
discounts = pd.Series(
    index=range(pv_year,lastyear+1),
    data=[1/(1+discountrate_social)**(y-pv_year)
          for y in range(pv_year,lastyear+1)]
).rename_axis('t')

dictplot_npv = {}
dictplot_health = {}
dictplot_climate = {}
for caseprefix in plotcaseprefixes:
    caseprefix_samples = sorted([s for (c,s) in dictin_npv if c == caseprefix])
    dictplot_npv[caseprefix] = pd.Series({
        sample: dictin_npv[caseprefix,sample].sum()
        for sample in caseprefix_samples
    })
    dictplot_climate[caseprefix] = pd.Series({
        sample: (
            dictin_emissions[caseprefix,sample]['process']['CO2']
            .reindex(discounts.index).interpolate('index')
            * scco2_pindyck
            # * scghg_central['CO2']
            / 1e9 # convert to $billion
        ).multiply(discounts).sum()
        for sample in caseprefix_samples
    })
    dictplot_health[caseprefix] = pd.Series({
        sample: (
            dictin_health_central[caseprefix,sample]
            .reindex(discounts.index).interpolate('index')
            / 1e9 # convert to $billion
        ).multiply(discounts).sum()
        for sample in caseprefix_samples
    })

dfplot = pd.concat(
    {
        'system':pd.concat(dictplot_npv, axis=1),
        'climate':pd.concat(dictplot_climate, axis=1),
        'health':pd.concat(dictplot_health, axis=1),
    },
    axis=1, names=('costtype','caseprefix')
)
describe = (
    dfplot.stack(['costtype','caseprefix'])
    .groupby(['costtype','caseprefix'])
    .describe(percentiles=percentiles)
    .T
)

ymax = dfplot.groupby(axis=1, level='caseprefix').sum().max().max()
binstep = 100
ymax = np.ceil(ymax / binstep) * binstep
number_of_bins = int(ymax / binstep) + 1
bins = np.linspace(0., ymax, number_of_bins)

### Plot it
ncols = 4
nrows = 1
costtypes = ['system', 'health', 'climate', 'total']
plt.close()
f,ax = plt.subplots(
    nrows, ncols, figsize=(ncols*1.5, 3.75),
    sharex=True, sharey=True,
)
for col, costtype in enumerate(costtypes):
    if costtype == 'total':
        df = dfplot.groupby(axis=1, level='caseprefix').sum()
    else:
        df = dfplot[costtype]
    df = df[plotcaseprefixes].rename(columns=plotlabels)
    reeds.plots.plotquarthist(
        ax=ax[col], dfplot=df,
        histcolor={plotlabels[k]:v for k,v in colors.items()},
        hist_range=(0., ymax), number_of_bins=number_of_bins,
        pad=0.04, alpha=1, density=True,
    )
    # for x, caseprefix in enumerate(plotcaseprefixes):
    #     df = dfplot[caseprefix]
    #     ## Histogram
    #     hist_val, hist_y = np.histogram(df.values, bins=bins)
    #     height = hist_y[1] - hist_y[0]
    #     ax[col].barh(
    #         y=hist_y[:-1],
    #         width=(hist_val / max(hist_val) * 0.9),
    #         height=height,
    #         align='edge',
    #         left=x,
    #         color=colors[caseprefix],
    #         label=f'{plotlabels.get(caseprefix,caseprefix)} ({len(df)})',
    #     )
    ## Formatting
    ax[col].set_title(costtype.title(), weight='bold')
    ax[col].set_xticks(range(len(plotcaseprefixes)))
    ax[col].set_xticklabels(
        [
            f"{plotlabels.get(caseprefix,caseprefix)}"
            # f" ({len(dfplot['system'][caseprefix].dropna())})"
            for caseprefix in plotcaseprefixes
        ],
        rotation=45, rotation_mode='anchor', ha='right',
    )
    ax[col].set_xlim(-0.1, len(plotcaseprefixes))
    for xtick, caseprefix in zip(ax[col].get_xticklabels(), plotcaseprefixes):
        xtick.set_color(colors[caseprefix])
ax[0].set_ylabel(f'Net present value of costs,\n{pv_year}–{lastyear} [$billion]')
ax[0].set_ylim(0)
ax[0].yaxis.set_major_locator(mpl.ticker.MultipleLocator(4000))
ax[0].yaxis.set_minor_locator(mpl.ticker.MultipleLocator(1000))
reeds.plots.despine(ax)
savename = (
    f"out_npv-system,health,climate,total-"
    f"{','.join([plotlabels.get(c,c).title().replace(' ','') for c in plotcaseprefixes])}.png"
)
print(savename)
plt.savefig(os.path.join(savepath, savename))
plt.show()

#%% Cost stats
dfwrite = pd.concat([
    (
        dfplot.rename(columns=plotlabels)
        .stack(['costtype','caseprefix'])
        .groupby(['costtype','caseprefix']).describe(percentiles=[0.05,0.5,0.95])
    ),
    (
        # dfplot.groupby(axis=1, level='caseprefix').sum()
        dfplot
        .rename(columns=plotlabels)
        .rename_axis('sample').unstack().dropna()
        .groupby(['caseprefix','sample']).sum()
        .groupby('caseprefix').describe(percentiles=[0.05,0.5,0.95])
        .assign(costtype='total').reset_index().set_index(['costtype','caseprefix'])
    )
]).round(0).astype(int)
dfwrite.to_csv(os.path.join(savepath, savename.replace('.png','.csv')))
dfwrite



#%%
#%% Emissions
etype = 'process'
pollutant = 'CO2'
dictplot = {}
for caseprefix in casepaths:
    caseprefix_samples = sorted([s for (c,s) in dictin_emissions if c == caseprefix])
    # print(f'{caseprefix}: {(len(caseprefix_samples))}')
    dictplot[caseprefix] = pd.concat({
        sample: dictin_emissions[caseprefix,sample][etype][pollutant]
        for sample in caseprefix_samples
    }, axis=1) / 1e6

dfplot = pd.concat(dictplot, axis=1, names=('caseprefix','sample'))

ymax = dfplot.max().max()
bins = np.linspace(ymin, ymax, numbins)

### Plot it
plt.close()
f,ax = plt.subplots(figsize=(5, 3.25))
for i, caseprefix in enumerate(plotcaseprefixes):
    df = dfplot[caseprefix].reindex(years).fillna(0)
    ## Fill between max and min
    ax.fill_between(
        df.index, df.max(axis=1), df.min(axis=1),
        color=colors[caseprefix], alpha=0.2, lw=0,
        label=f'{plotlabels.get(caseprefix,caseprefix)} ({df.shape[1]})',
    )
    ## Max and min lines
    # for agg in ['min', 'max']:
    #     ax.plot(
    #         df.index, df.agg(agg, axis=1), lw=0.5,
    #         color=colors[caseprefix],
    #         label='_nolabel',
    #     )
    ## Lines
    # df.plot(ax=ax, legend=False, lw=0.5, color='k', alpha=0.25)
    for s in df:
        ax.plot(
            df.index, df[s].values, color=colors[caseprefix],
            lw=0.5, alpha=0.25,
            label='_nolabel',
        )
    ## Histogram
    reeds.plots.hist_last(
        ax, df, color=colors[caseprefix], bins=bins, alpha=alpha,
        xpad=1+((xscale+0.5)*i), xscale=xscale,
    )
## Legend
handles = [
    mpl.patches.Patch(
        facecolor=colors[caseprefix], edgecolor='none',
        label=plotlabels.get(caseprefix,caseprefix)
    )
    for caseprefix in plotcaseprefixes
]
if 'v20250829_mcK0_MC_flat_state_IRA' in plotcaseprefixes:
    handles = handles[::-1]
ax.legend(
    handles=handles, frameon=False, loc='upper left', bbox_to_anchor=(-0.02,1.05),
    fontsize='x-large',
    handletextpad=0.3, handlelength=0.7,
)
## Formatting
ax.set_xlim(tstart)
# ax.set_ylabel(f'{pollutant} emissions [MMT/year]')
ax.set_ylabel('CO' + r'$\bf{_2}$' + ' emissions [MT/year]')
ax.set_ylim(0)
ax.yaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(2))
ax.set_xticks([2020,2030,2040,2050])
ax.xaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(2))
reeds.plots.despine(ax)
# plt.draw()
# reeds.plots.shorten_years(ax)
savename = (
    f"out_{pollutant.lower()}-line_country-"
    f"{','.join([plotlabels.get(c,c).title().replace(' ','') for c in plotcaseprefixes])}.png"
)
print(savename)
plt.savefig(os.path.join(savepath, savename))
plt.show()

#%% Print distribution of 2050 emissions
dfplot.loc[2050].groupby('caseprefix').describe().round(0)

#%% Distribution of 2050 emissions relative to 2005 (both MMT)
co2_pct_reduction = ((1 - dfplot.loc[2050] / baseline_emissions[2005]) * 100)
dfwrite = (
    co2_pct_reduction
    .groupby('caseprefix')
    .describe().round(0).astype(int)
    .T.rename(columns=plotlabels).T
)
dfwrite

thresholds = [60, 65, 70, 75, 80, 85, 90, 95]
dfwrite = (
    pd.concat({
        threshold: (
            co2_pct_reduction.loc[co2_pct_reduction >= threshold].groupby('caseprefix').count()
            / co2_pct_reduction.groupby('caseprefix').count()
        ).fillna(0) * 100
        for threshold in thresholds
    }, axis=1)
    .T.rename(columns=plotlabels).T.round(0).astype(int)
    .rename_axis(columns='% below 2005').rename_axis(index='% of samples')
)
dfwrite

#%% Print distribution of phaseout years
ira = 'v20250829_mcK0_MC_flat_state_IRA'


#%% Emissions difference
numbins = 31
etype = 'process'
pollutant = 'CO2'
caseprefix_central = 'v20250829_mcK0_MC_flat_state_MC'
caseprefix_compare = [
    'v20250829_mcK0_MC_flat_state_CAA0',
    'v20250829_mcK0_MC_flat_state_IRA',
]
plotlabels = {**nicelabels, 'v20250829_mcK0_MC_flat_state_MC': 'CurrentPol'}
samples = pd.concat({
    caseprefix:
    pd.Series(index=sorted([s for (c,s) in dictin_emissions if c == caseprefix]), data=1)
    for caseprefix in [caseprefix_central] + caseprefix_compare
}, axis=1).dropna(how='any').index.values
ylabels = {
    # 'annual': 'Annual CO' + r'$\bf{_2}$' + '\nemissions difference\n[MMT/yr]',
    # 'cumulative': 'Cumulative CO' + r'$\bf{_2}$' + '\nemissions difference\n[MMT]',
    'annual': 'Emissions difference,\nannual [MT CO' + r'$\bf{_2}$' + '/yr]',
    'cumulative': 'Emissions difference,\ncumulative [GT CO' + r'$\bf{_2}$' + ']',
}

dictplot = {}
for caseprefix in caseprefix_compare:
    dictplot[caseprefix] = (
        pd.concat({
            sample: dictin_emissions[caseprefix,sample][etype][pollutant]
            for sample in samples
        }, axis=1)
        - pd.concat({
            sample: dictin_emissions[caseprefix_central,sample][etype][pollutant]
            for sample in samples
        }, axis=1)
    ) / 1e6

dfplot = pd.concat(dictplot, axis=1, names=('caseprefix','sample'))

### Plot it
phaseout_color = 'C3'
plt.close()
f,ax = plt.subplots(2, 1, figsize=(4.25, 5.75), sharex=True, gridspec_kw={'hspace':0.1})
for i, caseprefix in enumerate(caseprefix_compare):
    for row, plottype in [(0, 'annual'), (1, 'cumulative')]:
        _ax = ax[row]
        df = dfplot[caseprefix].reindex(years).fillna(0).reindex(range(2020,2051)).interpolate('linear')
        if plottype == 'cumulative':
            df = df.cumsum() / 1e3
        ## Fill between max and min
        _ax.fill_between(
            df.index, df.max(axis=1), df.min(axis=1),
            color=colors[caseprefix], alpha=0.4, lw=0,
            label=f'{plotlabels.get(caseprefix,caseprefix)}',
        )
        # ## Max and min lines
        # for agg in ['min', 'max']:
        #     _ax.plot(
        #         df.index, df.agg(agg, axis=1), lw=0.5,
        #         color=colors[caseprefix],
        #         label='_nolabel',
        #     )
        ## Lines
        for s in df:
            phaseout = reeds.io.get_phaseout_year(caseprefix[s])
            if phaseout_color and ('IRA' in caseprefix):
            # if phaseout_color:
                before = df.loc[:phaseout[s]]
                after = df.loc[phaseout[s]:]
                for _df, color, _alpha in [(before, 'k', 0.3), (after, phaseout_color, 0.5)]:
                    _ax.plot(
                        _df.index, _df[s].values, label='_nolabel',
                        lw=0.7, color=color, alpha=_alpha,
                    )
            else:
                _ax.plot(
                    df.index, df[s].values, label='_nolabel',
                    lw=0.7, color='k', alpha=0.3,
                )
        ## Histogram
        reeds.plots.hist_last(
            _ax, df, color=colors[caseprefix], bins=numbins, alpha=alpha,
            xpad=0.5, xscale=xscale,
        )
## Formatting
for row, plottype in [(0, 'annual'), (1, 'cumulative')]:
    ax[row].axhline(0, c='C7', ls='--', lw=0.75, zorder=-1e3)
    ax[row].set_xlim(tstart)
    ax[row].set_ylabel(ylabels[plottype])
    ax[row].yaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(2))
    ax[row].xaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(2))
## Legend
# ax[0].legend(
#     frameon=False, loc='upper left', bbox_to_anchor=(0,1),
#     fontsize='x-large',
#     handletextpad=0.3, handlelength=0.7,
# )
handles = [
    mpl.patches.Patch(
        facecolor=colors[caseprefix], edgecolor='none',
        label=plotlabels.get(caseprefix,caseprefix)
    )
    for caseprefix in caseprefix_compare
]
ax[0].legend(
    handles=handles, frameon=False, loc='upper left', bbox_to_anchor=(-0.02,1),
    fontsize='x-large',
    handletextpad=0.3, handlelength=0.7,
)
# ax.set_ylim(0)
ax[0].set_xticks([2020,2030,2040,2050])
ax[1].yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter('{x:,.0f}'))
# ax[1].yaxis.set_major_formatter(mpl.ticker.FuncFormatter('{:,.0f}'.format))
reeds.plots.despine(ax)
# plt.draw()
# reeds.plots.shorten_years(ax[1])
savename = (
    f"out_{pollutant.lower()}_diff-line_country-"
    f"{','.join([plotlabels.get(c,c).title().replace(' ','') for c in caseprefix_compare])}.png"
)
print(savename)
plt.savefig(os.path.join(savepath, savename))
plt.show()

#%% Print stats
(
    dfplot
    .reindex(range(2025,2051)).interpolate('linear')
    .rename(columns=plotlabels)
    .sum()
    .groupby('caseprefix').describe(percentiles=[0.05,0.5,0.95]).T
    .round(0).astype(int)
)




#%%### Transmission ######
#%% Regional transmission for a single caseprefix
level = 'transreg'
binstep = 2
alpha = 0.5
color = 'C2'
nrows = 2
regioncolors = [plt.cm.PiYG(0.1), plt.cm.PiYG(0.9)]
regioncolors = ['C0', 'C1']

for caseprefix in casepaths:
    caseprefix_samples = sorted([s for (c,s) in dictin_trans_r if c == caseprefix])
    dfplot = pd.concat(
        {sample: dictin_trans_r[caseprefix,sample] for sample in caseprefix_samples},
        names=('case',)
    ).reset_index(level=1, drop=True)
    dfplot = dfplot.loc[dfplot[f'inter_{level}'] == 1].copy()
    dfplot['level'] = dfplot.r.map(hierarchy[level])
    dfplot['levell'] = dfplot.rr.map(hierarchy[level])
    dfplot['interface'] = dfplot.apply(
        lambda row: '|'.join(sorted([row.level, row.levell])),
        axis=1,
    )
    interfaces = dfplot.interface.unique()
    dfplot = dfplot.groupby(['case','t','interface']).MW.sum().rename('GW') / 1e3

    ymax = dfplot.groupby(level='interface', axis=0).max().max()
    bins = np.arange(0, ymax+0.1, binstep)
    ncols = len(interfaces)

    plt.close()
    f,ax = plt.subplots(
        nrows, ncols, sharex='row', sharey='row', figsize=(1.25*ncols, 4),
        gridspec_kw={'hspace':0.1, 'height_ratios':[0.3, 1]},
        dpi=300,
    )
    for col, interface in enumerate(interfaces):
        ### Maps on top
        dfmap[level].plot(ax=ax[0,col], facecolor='0.99', edgecolor='0.75', lw=0.2)
        dfmap[level].loc[[interface.split('|')[0]]].plot(
            ax=ax[0,col], facecolor=regioncolors[0], edgecolor='none')
        dfmap[level].loc[[interface.split('|')[1]]].plot(
            ax=ax[0,col], facecolor=regioncolors[1], edgecolor='none')
        ax[0,col].axis('off')
        ax[0,col].patch.set_facecolor('none')
        ### Data
        row = 1
        df = dfplot.xs(interface, 0, 'interface').unstack('case')
        ## Background
        ax[row,col].fill_between(
            df.index, df.max(axis=1), df.min(axis=1),
            color=color, alpha=alpha, lw=0,
        )
        ## Lines
        df.plot(
            ax=ax[row,col], legend=False,
            lw=0.5, color='k', alpha=0.25,
        )
        ## Histogram
        reeds.plots.hist_last(
            ax[row,col], df, color=color, bins=bins, alpha=alpha,
            xpad=1, xscale=4,
        )
    ## Formatting
    ax[1,0].set_ylabel('Interface capacity [GW]')
    ax[1,0].yaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(2))
    ax[1,0].xaxis.set_minor_locator(mpl.ticker.MultipleLocator(10))
    ax[1,0].xaxis.set_major_locator(mpl.ticker.MultipleLocator(20))
    ax[1,0].set_ylim(0)

    reeds.plots.despine(ax)
    for col, interface in enumerate(interfaces):
        ax[1,col].set_xlabel(None)
        ax[1,col].set_xlim(2020, 2057.25)
        ax[1,col].annotate(
            interface.replace('|', '\n'),
            (0.05, 0.98), xycoords='axes fraction',
            va='top', fontsize=10,
        )
    plt.draw()
    reeds.plots.shorten_years(ax[1,0])
    savename = f'out_trans-{level}-{caseprefix}.png'
    print(savename)
    plt.savefig(os.path.join(savepath, savename))
    plt.show()


#%% Regional transmission additions for all scenarios
level = 'transreg'
binstep = 1
alpha = 0.5
nrows = 2
regioncolors = ['C6', 'C9']
regioncolors = ['k', '0.7']
year = 2050
year_baseline = 2020

# plotcaseprefixes = list(casepaths.keys())
# plotlabels = nicelabels

plotcaseprefixes = [
    'v20250829_mcK0_MC_flat_state_IRA',
    'v20250829_mcK0_MC_flat_state_MC',
    'v20250829_mcK0_MC_flat_state_CAA0',
]
plotlabels = {
    **nicelabels,
    'v20250829_mcK0_MC_flat_state_MC': 'CurrentPol',
}

# plotcaseprefixes = [
#     'v20250829_mcK0_MC_flat_state_MC',
#     'v20250829_mcK0_MC_flat_country',
#     'v20250911_mcK0_MC_tri_state',
#     'v20250922_mcK0_MC_tri_country',
# ]
# plotlabels = nicelabels


dfplot = {}
for caseprefix in plotcaseprefixes:
    caseprefix_samples = sorted([s for (c,s) in dictin_trans_r if c == caseprefix])
    df = pd.concat(
        {
            sample: (
                dictin_trans_r[caseprefix,sample].loc[
                    dictin_trans_r[caseprefix,sample].t==year
                ].groupby(['r','rr']).MW.sum()
                - dictin_trans_r[caseprefix,sample].loc[
                    dictin_trans_r[caseprefix,sample].t==year_baseline
                ].groupby(['r','rr']).MW.sum()
            )
            for sample in caseprefix_samples
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
    df = df.groupby(['interface','case']).MW.sum().rename('GW') / 1e3
    dfplot[caseprefix] = df
dfplot = pd.concat(dfplot, names=('caseprefix',))

print(
    dfplot.loc[plotcaseprefixes].groupby('interface').mean()
    .sort_values(ascending=False)
)

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

plt.close()
f,ax = plt.subplots(
    nrows, ncols, sharex='row', sharey='row', figsize=(1.25*ncols, 4),
    gridspec_kw={'hspace':0.0, 'height_ratios':[0.3, 1]},
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
    for x, caseprefix in enumerate(plotcaseprefixes):
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
            color=colors[caseprefix],
        )
## Formatting
ax[1,0].set_ylabel(f'Interface capacity\nadded through {year} [GW]')
ax[1,0].yaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(2))
ax[1,0].set_ylim(0)
ax[1,0].set_xlim(-0.15, len(plotcaseprefixes))

reeds.plots.despine(ax)
for col, interface in enumerate(interfaces):
    ax[1,col].set_xlabel(None)
    ax[0,col].annotate(
        interface.replace('|', '\n'),
        (0.05, 1.0), xycoords='axes fraction',
        va='bottom', fontsize=10,
    )
    ax[1,col].set_xticks(range(len(plotcaseprefixes)))
    ax[1,col].set_xticklabels(
        [plotlabels.get(caseprefix,caseprefix) for caseprefix in plotcaseprefixes],
        rotation=90,
    )
savename = (
    f'out_trans-{level}-{year}_since{year_baseline}-'
    f"{','.join([plotlabels.get(c,c).title().replace(' ','') for c in plotcaseprefixes])}.png"
)
print(savename)
plt.savefig(os.path.join(savepath, savename))
plt.show()

#%% Transmission capacity stats
dfwrite = (
    dfplot.loc[plotcaseprefixes]
    .unstack('caseprefix').rename(columns=plotlabels).stack('caseprefix')
    .groupby(['interface','caseprefix'])
    .describe(percentiles=[0.05,0.25,0.5,0.75,0.95])
    .round(0).astype(int)
)
dfwrite.to_csv(os.path.join(savepath, savename.replace('.png','.csv')))
dfwrite


#%% Final regional transmission capacity for all scenarios
level = 'transreg'
binstep = 1
alpha = 0.5
nrows = 2
regioncolors = ['C6', 'C9']
regioncolors = ['k', '0.7']
year = 2050
year_baseline = 2020

# plotcaseprefixes = list(casepaths.keys())
# plotlabels = nicelabels

# plotcaseprefixes = [
#     'v20250829_mcK0_MC_flat_state_IRA',
#     'v20250829_mcK0_MC_flat_state_MC',
#     'v20250829_mcK0_MC_flat_state_CAA0',
# ]
# plotlabels = {
#     **nicelabels,
#     'v20250829_mcK0_MC_flat_state_MC': 'CurrentPol',
# }
# figsize = 1.25

# plotcaseprefixes = [
#     'v20250829_mcK0_MC_flat_state_MC',
#     'v20250911_mcK0_MC_tri_state',
#     'v20250829_mcK0_MC_flat_country',
#     'v20250922_mcK0_MC_tri_country',
# ]
# plotlabels = nicelabels
# figsize = 1.25

plotcaseprefixes = [
    'v20250922_mcK0_MC_tri_country',
    'v20250829_mcK0_MC_flat_country',
    'v20250911_mcK0_MC_tri_state',
    'v20250829_mcK0_MC_flat_state_MC',
    'v20250829_mcK0_MC_flat_state_IRA',
    'v20250829_mcK0_MC_flat_state_CAA0',
]
plotlabels = nicelabels
figwidth = 1.45


baseline = (
    dictin_trans_r[basecase].loc[dictin_trans_r[basecase].t==year_baseline]
    .groupby(['r','rr'], as_index=False).MW.sum()
)
baseline['level'] = baseline.r.map(hierarchy[level])
baseline['levell'] = baseline.rr.map(hierarchy[level])
baseline = baseline.loc[baseline.level != baseline.levell].copy()
baseline['interface'] = baseline.apply(
    lambda row: '|'.join(sorted([row.level, row.levell])),
    axis=1,
)
baseline = baseline.groupby('interface').MW.sum().rename('GW') / 1e3

dfplot = {}
for caseprefix in plotcaseprefixes:
    caseprefix_samples = sorted([s for (c,s) in dictin_trans_r if c == caseprefix])
    df = pd.concat(
        {
            sample: dictin_trans_r[caseprefix,sample].loc[
                dictin_trans_r[caseprefix,sample].t==year
            ].groupby(['r','rr']).MW.sum()
            for sample in caseprefix_samples
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
    df = df.groupby(['interface','case']).MW.sum().rename('GW') / 1e3
    dfplot[caseprefix] = df
dfplot = pd.concat(dfplot, names=('caseprefix',))

print(
    dfplot.loc[plotcaseprefixes].groupby('interface').mean()
    .sort_values(ascending=False)
)

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

plt.close()
## figsize, height_ratios: (4, [0.3,1]) pre-20260112
f,ax = plt.subplots(
    nrows, ncols, sharex='row', sharey='row', figsize=(figwidth*ncols, 3),
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
    for x, caseprefix in enumerate(plotcaseprefixes):
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
            color=colors[caseprefix],
        )
    ax[row,col].axhline(baseline[interface], c='k', ls='--', lw=0.75)
## Formatting
ax[1,0].set_ylabel(f'Interface capacity, {year} [GW]')
ax[1,0].yaxis.set_major_locator(mpl.ticker.MultipleLocator(20))
ax[1,0].yaxis.set_minor_locator(mpl.ticker.MultipleLocator(10))
ax[1,0].set_ylim(0)
ax[1,0].set_xlim(-0.15, len(plotcaseprefixes))

reeds.plots.despine(ax)
for col, interface in enumerate(interfaces):
    ax[1,col].set_xlabel(None)
    ax[0,col].annotate(
        interface.replace('|', '\n'),
        (0.05, 1.0), xycoords='axes fraction',
        va='bottom', fontsize=10,
    )
    ax[1,col].set_xticks(range(len(plotcaseprefixes)))
    ax[1,col].set_xticklabels(
        [plotlabels.get(caseprefix,caseprefix) for caseprefix in plotcaseprefixes],
        rotation=90, weight='bold',
    )
    _colors = [colors[c] for c in plotcaseprefixes]
    for x, xtick in enumerate(ax[1,col].get_xticklabels()):
        xtick.set_color(_colors[x])

savename = (
    f'out_trans-{level}-{year}-'
    f"{','.join([plotlabels.get(c,c).title().replace(' ','') for c in plotcaseprefixes])}.png"
)
print(savename)
plt.savefig(os.path.join(savepath, savename))
plt.show()

#%% Transmission capacity stats
dfwrite = (
    dfplot.loc[plotcaseprefixes]
    .unstack('caseprefix').rename(columns=plotlabels).stack('caseprefix')
    .groupby(['interface','caseprefix'])
    .describe(percentiles=[0.05,0.25,0.5,0.75,0.95])
    .round(0).astype(int)
)
dfwrite.to_csv(os.path.join(savepath, savename.replace('.png','.csv')))
dfwrite


#%%

#%% Grid of scatter plots: interfaces on axes, histograms on diagonal, scatter plots on off-diagonal
level = 'transreg'
binstep = 2
alpha = 0.5
color = 'C2'
nrows = 2
regioncolors = ['C0', 'C1']
year = 2050
year_baseline = 2020
scale = 1.75

for caseprefix in casepaths:
    caseprefix_samples = sorted([s for (c,s) in dictin_trans_r if c == caseprefix])
    dfplot = pd.concat(
        {
            sample: (
                dictin_trans_r[caseprefix,sample].loc[
                    dictin_trans_r[caseprefix,sample].t==year
                ].groupby(['r','rr']).MW.sum()
                - dictin_trans_r[caseprefix,sample].loc[
                    dictin_trans_r[caseprefix,sample].t==year_baseline
                ].groupby(['r','rr']).MW.sum()
            )
            for sample in caseprefix_samples
        },
        names=('case',),
    ).reset_index()
    dfplot['level'] = dfplot.r.map(hierarchy[level])
    dfplot['levell'] = dfplot.rr.map(hierarchy[level])
    dfplot = dfplot.loc[dfplot.level != dfplot.levell].copy()
    dfplot['interface'] = dfplot.apply(
        lambda row: '|'.join(sorted([row.level, row.levell])),
        axis=1,
    )
    dfplot = dfplot.groupby(['interface','case']).MW.sum().rename('GW') / 1e3

    ## Sort the interfaces from west to east
    interfaces_unsorted = dfplot.index.get_level_values('interface').unique()
    interfaces = {}
    for i in interfaces_unsorted:
        region, regionn = i.split('|')
        interfaces[i] = dfmap[level].loc[[region,regionn]].dissolve().bounds.minx.squeeze()
    interfaces = pd.Series(interfaces).sort_values().index.values

    ymax = dfplot.groupby(level='interface', axis=0).max().max()
    bins = np.arange(0, ymax+0.1, binstep)
    ncols = nrows = len(interfaces)

    plt.close()
    f,ax = plt.subplots(
        nrows, ncols, figsize=(scale*ncols, scale*nrows), sharex=True,
    )
    for row, interface_y in enumerate(interfaces):
        for col, interface_x in enumerate(interfaces):
            ## Don't keep the upper right half
            if col > row:
                ax[row,col].axis('off')
                continue
            ## If the same, plot histogram
            if interface_y == interface_x:
                ax[row,col].hist(
                    x=dfplot.loc[interface_y].values,
                    bins=bins,
                    color=colors[caseprefix],
                )
                # reeds.plots.despine(ax[row,col], left=False)
                ax[row,col].set_yticks([])
            ## If different, plot scatter
            else:
                ax[row,col].plot(
                    dfplot.loc[interface_x].values,
                    dfplot.loc[interface_y].values,
                    lw=0, marker='o', alpha=0.2, markeredgewidth=0,
                    color=colors[caseprefix],
                )
                ax[row,col].set_ylim(0,ymax)
                ax[row,col].yaxis.set_major_locator(mpl.ticker.MultipleLocator(20))
                if col > 0:
                    ax[row,col].set_yticklabels([])
            ## Formatting
            # ax[row,col].set_xlim(0,ymax)
            if row == nrows - 1:
                ax[row,col].set_xlabel(interface_x.replace('|','\n'))
            if col == 0:
                ax[row,col].set_ylabel(interface_y.replace('|','\n'), rotation=0, ha='right', va='center')
    # ## Formatting
    ax[-1,0].xaxis.set_major_locator(mpl.ticker.MultipleLocator(20))
    ax[-1,0].set_xlim(0,ymax)
    ax[0,0].set_title(
        f'Interface capacity added by {year} [GW]: '
        f'{nicelabels.get(caseprefix,caseprefix).title()} (n = {len(caseprefix_samples)})',
        x=0, ha='left', fontsize=16, weight='bold',
    )
    reeds.plots.despine(ax)
    savename = f'out_trans-interface_vs_interface_{year}_since{year_baseline}-{level}-{caseprefix}.png'
    print(savename)
    plt.savefig(os.path.join(savepath, savename))
    plt.show()


#%% Transmission additions: All samples on one map, shaded lines (for percentiles or overlapping?)
year = 2050
year_baseline = 2020
for caseprefix in casepaths:
    caseprefix_samples = sorted([s for (c,s) in dictin_trans_r if c == caseprefix])
    dfplot = pd.concat(
        {
            sample: (
                dictin_trans_r[caseprefix,sample].loc[
                    dictin_trans_r[caseprefix,sample].t==year
                ].groupby(['r','rr']).MW.sum()
                - dictin_trans_r[caseprefix,sample].loc[
                    dictin_trans_r[caseprefix,sample].t==year_baseline
                ].groupby(['r','rr']).MW.sum()
            )
            for sample in caseprefix_samples
        },
        names=('case',),
    ).reset_index()


#%%### Color bars
#%% Correlation
cmap = plt.cm.coolwarm
vmin, vmax = -1, 1
label = 'Correlation coefficient'
savelabel = label.replace(' ','').replace('%','').replace('\n','').replace('/','')
orientation, figwidth, figheight = 'horizontal', 4, 0.2

norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax)
plt.close()
f, ax = plt.subplots(figsize=(figwidth, figheight))
cb = mpl.colorbar.ColorbarBase(ax, cmap=cmap, norm=norm, orientation=orientation)
cb.set_label(label, weight='bold')
savename = f"cbar-{orientation[0]}-{cmap.name}-{savelabel}-v_{vmax}_{vmin}.png"
print(savename)
plt.savefig(os.path.join(savepath,savename))
plt.show()

#%% State deployment
cmap = plt.cm.turbo
vmin, vmax = -1, 1
label = 'Relative state capacity'
savelabel = label.replace(' ','').replace('%','').replace('\n','').replace('/','')
orientation, figwidth, figheight = 'vertical', 0.2, 4
orientation, figwidth, figheight = 'horizontal', 2.5, 0.2

norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax)
plt.close()
f, ax = plt.subplots(figsize=(figwidth, figheight))
cb = mpl.colorbar.ColorbarBase(ax, cmap=cmap, norm=norm, orientation=orientation)
cb.set_label(label, weight='bold')
if orientation == 'vertical':
    ax.set_yticks([vmin,vmax])
    ax.set_yticklabels(['Min','Max'])
else:
    ax.set_xticks([vmin,vmax])
    ax.set_xticklabels(['Min','Max'])
savename = f"cbar-{orientation[0]}-{cmap.name}-{savelabel}-v_{vmax}_{vmin}.png"
print(savename)
plt.savefig(os.path.join(savepath,savename))
plt.show()


#%%
cmap = plt.cm.turbo
vmin, vmax = -1, 1
label = ''
savelabel = label.replace(' ','').replace('%','').replace('\n','').replace('/','')
orientation, figwidth, figheight = 'horizontal', 2.5, 0.2
orientation, figwidth, figheight = 'vertical', 0.2, 1.3

norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax)
plt.close()
f, ax = plt.subplots(figsize=(figwidth, figheight))
cb = mpl.colorbar.ColorbarBase(ax, cmap=cmap, norm=norm, orientation=orientation)
if len(label):
    cb.set_label(label, weight='bold')
if orientation == 'vertical':
    ax.set_yticks([vmin,vmax])
    ax.set_yticklabels(['Min','Max'])
else:
    ax.set_xticks([vmin,vmax])
    ax.set_xticklabels(['Min','Max'])
savename = f"cbar-{orientation[0]}-{cmap.name}-{savelabel}-v_{vmax}_{vmin}.png"
print(savename)
plt.savefig(os.path.join(savepath,savename))
plt.show()
