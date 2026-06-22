#%% Imports
import pandas as pd
import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt
import os
import sys
import argparse
import subprocess as sp
import platform
import cmocean
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds
from reeds.report_utils import SLIDE_HEIGHT

reeds_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
reeds.plots.plotparams()


#%% Argument inputs
parser = argparse.ArgumentParser(
    description='Compare multiple ReEDS cases',
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
)
parser.add_argument(
    'caselist', type=str, nargs='+',
    help=('space-delimited list of cases to plot, OR shared casename prefix, '
          'OR csv file of cases. The first case is treated as the base case '
          'unless a different one is provided via the --basecase/-b argument.'))
parser.add_argument(
    '--casenames', '-n', type=str, default='',
    help='comma-delimited list of shorter case names to use in plots')
parser.add_argument(
    '--titleshorten', '-s', type=str, default='',
    help='characters to cut from start of case name (only used if no casenames)')
parser.add_argument(
    '--plotyear', '-y', type=int, default=0,
    help='Year to plot (or 0 for last year)')
parser.add_argument(
    '--label', '-l', type=str, default='d1h',
    help='Label for PCM outputs (same as in run_pcm.py)')
parser.add_argument(
    '--basecase', '-b', type=str, default='',
    help='Substring of case path to use as default (if empty, uses first case in list)')

args = parser.parse_args()
caselist = args.caselist
casenames = args.casenames
try:
    titleshorten = int(args.titleshorten)
except ValueError:
    titleshorten = len(args.titleshorten)
plotyear = args.plotyear
label = args.label
basecase_in = args.basecase
interactive = False

#%% Inputs for testing
# reeds_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# caselist = [os.path.join(reeds_path,'postprocessing','example.csv')]
# casenames = ''
# titleshorten = 0
# plotyear = 2035
# label = 'd1h'
# basecase_in = ''
# interactive = True

#%%### Fixed inputs
cmap = cmocean.cm.rain
cmap_diff = plt.cm.RdBu_r

#%% Colors and mapping
output_formatting = reeds.io.get_plot_formatting()
aggregation_mapping = pd.read_csv(
        os.path.join(reeds_path,'postprocessing','tech_aggregation.csv'))

#%% Parse arguments
cases, colors, basecase, basemap = reeds.report_utils.parse_caselist(
    caselist,
    casenames,
    basecase_in,
    titleshorten,
)
maxlength = max([len(c) for c in cases])
if not plotyear:
    plotyear = max(
        pd.read_csv(os.path.join(cases[basecase], 'inputs_case', 'modeledyears.csv'))
        .columns.astype(int)
        .values
    )

## Arrange the maps
nrows, ncols, coords = reeds.plots.get_coordinates(cases, aspect=2)

### Set up powerpoint file
prs = reeds.report_utils.init_pptx()


#%% Create output folder
firstcasepath = list(cases.values())[0]
outpath = os.path.join(firstcasepath, 'outputs', 'comparisons')
os.makedirs(outpath, exist_ok=True)
## Remove disallowed characters and clip filename to max length
max_filename_length = 250
savename = os.path.join(
    outpath,
    (f"pcm_{label}_{plotyear}-{','.join(cases.keys())}"
     .replace(':','').replace('/','').replace(' ','').replace('\\n','').replace('\n','')
     [:max_filename_length-len('.pptx')]) + '.pptx'
)
print(f'Saving results to {savename}')


#%%### Read outputs ######
dictin_dropped = {
    case: reeds.io.read_output(
        os.path.join(cases[case], 'outputs', f'pcm_{label}_{plotyear}', 'outputs.h5'),
        'dropped_load',
    )
    for case in cases
}

dictin_revenue = {
    case: reeds.io.read_output(
        os.path.join(cases[case], 'outputs', f'pcm_{label}_{plotyear}', 'outputs.h5'),
        'revenue',
    )
    for case in cases
}

dictin_cap = {
    case: reeds.io.read_output(
        os.path.join(cases[case], 'outputs', f'pcm_{label}_{plotyear}', 'outputs.h5'),
        'cap',
    )
    for case in cases
}

dictin_price = {
    case: reeds.io.read_output(
        os.path.join(cases[case], 'outputs', f'pcm_{label}_{plotyear}', 'outputs.h5'),
        'reqt_price',
    )
    for case in cases
}

dictin_gen = {
    case: reeds.io.read_output(
        os.path.join(cases[case], 'outputs', f'pcm_{label}_{plotyear}', 'outputs.h5'),
        'gen_ann',
    )
    for case in cases
}

###### Plots ######
#%% Total dropped load
dfdropped = pd.Series({
    case:
    dictin_dropped[case].loc[dictin_dropped[case].t==plotyear].Value.sum() / 1e3
    for case in cases
})

plt.close()
f,ax = plt.subplots()
ax.bar(
    x=dfdropped.index,
    height=dfdropped.values,
    color=[colors[case] for case in dfdropped.index],
)
ax.set_ylabel(f'Dropped load {plotyear} [GWh]')
ax.set_xticks(range(len(cases)))
ax.set_xticklabels(cases.keys(), rotation=45, rotation_mode='anchor', ha='right')
reeds.plots.despine(ax)
## Save it
title = 'Total dropped load'
slide = reeds.report_utils.add_to_pptx(title, prs=prs, width=None, height=SLIDE_HEIGHT)
if interactive:
    plt.show()


#%% Regions
scale = 3
cmap = cmocean.cm.rain
dfmaps = {case: reeds.io.get_dfmap(cases[case]) for case in cases}

nrows, ncols, coords = reeds.plots.get_coordinates(cases)

plt.close()
f,ax = plt.subplots(
    nrows, ncols, figsize=(scale*ncols, scale*nrows*0.75), sharex=True, sharey=True,
    gridspec_kw={'wspace':0, 'hspace':-0.1}, dpi=200,
)
for case in cases:
    _ax = ax[coords[case]]
    dfmaps[case]['st'].plot(ax=_ax, facecolor='none', edgecolor='C7', lw=0.1)
    dfmaps[case]['transreg'].plot(ax=_ax, facecolor='none', edgecolor='k', lw=0.2)
    for r, row in dfmaps[case]['r'].iterrows():
        _ax.annotate(
            r.strip('p'), (row.centroid_x, row.centroid_y),
            ha='center', va='center', fontsize=3,
            color='0.8',
        )
    df = dfmaps[case]['r'].copy()
    df['GWh'] = (
        dictin_dropped[case].loc[dictin_dropped[case].t==plotyear]
        .groupby('r').Value.sum()
        / 1e3
    )
    df.plot(ax=_ax, column='GWh', cmap=cmap)
    _ax.axis('off')
    _ax.set_title(case, y=0.9)
reeds.plots.trim_subplots(ax, nrows, ncols, len(cases))
## Save it
title = 'Dropped load'
slide = reeds.report_utils.add_to_pptx(title, prs=prs)
if interactive:
    plt.show()


#%% Timing of dropped load
dfdropped = pd.Series({
    case:
    dictin_dropped[case].loc[dictin_dropped[case].t==plotyear].Value.sum() / 1e3
    for case in cases
})

for case in dfdropped.loc[dfdropped > 0].index:
    sw = reeds.io.get_switches(cases[case])
    y = int(sw.GSw_HourlyWeatherYears.split('_')[0])
    fullyear = pd.date_range(f'{y}-01-01', f'{y+1}-01-01', freq='H', tz='Etc/GMT+6')[:8760]
    df = (dictin_dropped[case].loc[dictin_dropped[case].t==plotyear]).groupby('h').Value.sum()
    df.index = df.index.map(reeds.timeseries.h2timestamp)
    df = df.reindex(fullyear).fillna(0)

    plt.close()
    f, ax = reeds.plots.plotyearbymonth(df, colors='r')
    # ax[0].set_title(case, fontsize=14)
    ## Save it
    title = f'Dropped load ({case})'
    slide = reeds.report_utils.add_to_pptx(title, prs=prs)
    if interactive:
        plt.show()


#%%### Dispatch
max_regions = 3
max_arrows = 100

dfdropped = pd.concat({
    case: (
        dictin_dropped[case].loc[dictin_dropped[case].t==plotyear]
        .groupby('r').Value.sum()
    )
    for case in cases
})

plot_regions = list(
    dfdropped
    .groupby('r').max()
    .sort_values(ascending=False)
    .index[:max_regions]
)

for r in plot_regions:
    for case in cases:
        try:
            title = f"{case}: {r} ({dfdropped[case][r]/1e3:.1f} GWh)"
        except KeyError:
            continue
        sw = reeds.io.get_switches(cases[case])
        y = int(sw.GSw_HourlyWeatherYears.split('_')[0])
        fullyear = pd.date_range(f'{y}-01-01', f'{y+1}-01-01', freq='H', tz='Etc/GMT+6')[:8760]
        ## Dispatch
        plt.close()
        f, ax, dfplot = reeds.reedsplots.plot_dispatch_yearbymonth(
            case=cases[case],
            t=plotyear,
            periodtype=f'pcm_{label}',
            highlight_rep_periods=False,
            region=f'r/{r}',
        )
        ## Dropped, as white areas at the bottom
        df = (
            dictin_dropped[case]
            .loc[
                (dictin_dropped[case].t==plotyear)
                & (dictin_dropped[case].r==r)
            ]
        ).groupby('h').Value.sum()
        df.index = df.index.map(reeds.timeseries.h2timestamp)
        df = df.reindex(fullyear).fillna(0) / 1e3
        reeds.plots.plotyearbymonth(df, colors='w', f=f, ax=ax)
        ## Annotate the hours with dropped load
        nonzero_dropped_load = df.loc[df > 0].sort_values(ascending=False)
        for i in range(min(max_arrows, len(nonzero_dropped_load))):
            dt = nonzero_dropped_load.index[i]
            row = dt.month - 1
            ## plots.plotyearbymonth() plots each month as January 2001
            _dt = pd.Timestamp(f'2001-01-{dt.day:02} {dt.hour}:00:00')
            ax[row].annotate(
                '',
                xy=(_dt, -ax[row].get_ylim()[1]*0.05),
                xytext=(_dt, -ax[row].get_ylim()[1]*0.25),
                arrowprops={
                    'headwidth':2.5,
                    'headlength':3,
                    'width':0.5,
                    'color':'k',
                    'lw':0.5,
                },
                annotation_clip=False,
            )
        ## Save it
        slide = reeds.report_utils.add_to_pptx(title, prs=prs)
        if interactive:
            plt.show()

#%%### Revenue irt
# histogram of revenue from different cases
# from reeds import reedsplots
use_tech_categories = True

renametechs = {
    'h2-cc_upgrade':'h2-cc',
    'h2-ct_upgrade':'h2-ct',
    'gas-cc-ccs_mod_upgrade':'gas-cc-ccs_mod',
    'coal-ccs_mod_upgrade':'coal-ccs_mod',
}
techmap = {
    **{f'upv_{i}':'upv' for i in range(20)},
    **{f'wind-ons_{i}':'wind-ons' for i in range(20)},
    **{f'wind-ofs_{i}':'wind-ofs' for i in range(20)},
    **{f'egs_nearfield_{i}':'geothermal' for i in range(20)},
    **{f'geohydro_allkm_{i}':'geothermal' for i in range(20)},
    **dict(zip(
        ['hydend','hyded','hydnpnd','hydnpnd','hydud','hydund','hydsnd','hydnd'],
        ['hydro']*20)),
    **dict(zip(
        ['coal-igcc', 'coaloldscr', 'coalolduns', 'coal-new'],
        ['coal']*20)),
    **dict(zip(
        ['coaloldscr_coal-ccs_mod','coalolduns_coal-ccs_mod','cofirenew_coal-ccs_mod',
         'cofireold_coal-ccs_mod','coal-igcc_coal-ccs_mod','coal-new_coal-ccs_mod',
        ],
        ['coal-ccs_mod']*20)),
    **dict(zip(
        ['coal-new_coal-ccs_max','coaloldscr_coal-ccs_max','coalolduns_coal-ccs_max',
         'cofirenew_coal-ccs_max','cofireold_coal-ccs_max','coal-igcc_coal-ccs_max',],
        ['coal-ccs_max']*20)),
    **dict(zip(
        ['gas-cc_gas-cc-ccs_mod','gas-cc_gas-cc-ccs_max','gas-cc-ccs_mod',
         ],
        ['gas-cc-ccs_mod']*20)),
    **dict(zip(
        ['gas-cc_gas-cc-ccs_max','gas-cc-ccs_max'],
        ['gas-cc-ccs_max']*20)), 
}

techcatmap = {
    **dict(zip(
        ['distpv','upv', 'wind-ons', 'wind-ofs',
        'geothermal','hydro','lfill-gas','can-imports',
        'nuclear','nuclear-smr',
        ],
        ['High fixed cost generation']*20)),
    **dict(zip(
        ['biopower','coal',
         'gas-cc_re-cc','gas-ct_re-ct','re-cc','re-ct',
         'gas-ct_h2-ct','h2-ct','gas-cc_h2-cc','h2-cc',
         'gas-cc','gas-ct', 'o-g-s',
         'gas-cc-ccs_mod','gas-cc-ccs_max',
         'coal-ccs_mod','coal-ccs_max',
         ],
        ['High operational cost generation']*40)),
    **dict(zip(
        ['battery_li','pumped-hydro'],
        ['Storage']*20)),    
}

# simplify technologies
for case in cases:
    ### Simplify techs
    dictin_revenue[case].i = dictin_revenue[case].i.map(lambda x: renametechs.get(x,x))
    dictin_revenue[case].i = dictin_revenue[case].i.str.lower().map(lambda x: techmap.get(x,x))
    dictin_cap[case].i = dictin_cap[case].i.map(lambda x: renametechs.get(x,x))
    dictin_cap[case].i = dictin_cap[case].i.str.lower().map(lambda x: techmap.get(x,x))
    dictin_gen[case].i = dictin_gen[case].i.map(lambda x: renametechs.get(x,x))
    dictin_gen[case].i = dictin_gen[case].i.str.lower().map(lambda x: techmap.get(x,x))
    # if use_tech_categories:

## plot generation bars
#%%### Capacity and generation bars
casebase, casecomp = list(cases.values())
casebase_name, casecomp_name = list(cases.keys())

toplot = {
    'Capacity': {
        'data': dictin_cap,
        'colors':output_formatting['tech_color'].squeeze(),
        'columns':'tech',
        'values':'Capacity (GW)',
        'label':'Capacity [GW]',
        'conversionfactor':1e3 # to GW
    },
    'Generation': {
        'data': dictin_gen,
        'colors':output_formatting['tech_color'].squeeze(),
        'columns':'tech',
        'values':'Generation (TWh)',
        'label':'Generation [TWh]',
        'conversionfactor':1e6 # to TWh
    },
}
plotwidth = 2.0
figwidth = plotwidth * len(cases)
dfbase = {}
for slidetitle, data in toplot.items():
    plt.close()
    f,ax = plt.subplots(
        2, len(cases), figsize=(figwidth, 6.8),
        sharex=True, sharey=False, dpi=None,
    )
    ax[0,0].set_ylabel(data['label'], y=-0.075)
    ax[0,0].set_xlim(2017.5, plotyear+2.5)
    ax[1,0].annotate(
        f'Diff\nfrom\n{basecase}', (0.03,0.03), xycoords='axes fraction',
        fontsize='x-large', weight='bold')
    ###### Absolute
    alltechs = set()
    for col, case in enumerate(cases):
        if case not in data['data']:
            continue
        dfplot = data['data'][case].pivot_table(index='t', columns='i', values='Value',aggfunc='sum')
        dfplot = (
            dfplot[[c for c in data['colors'] if c in dfplot]]
            .round(3).replace(0,np.nan)
            .dropna(axis=1, how='all')
            / data['conversionfactor'] # to GW or TWh
        )
        if case == basecase:
            dfbase[slidetitle] = dfplot.copy()
        alltechs.update(dfplot.columns)
        reeds.plots.stackbar(df=dfplot, ax=ax[0,col], colors=data['colors'], net=False)
        ax[0,col].set_title(
            reeds.plots.wraptext(case, width=plotwidth*0.9, fontsize=14),
            fontsize=14, weight='bold', x=0, ha='left', pad=8,)
        ax[0,col].xaxis.set_major_locator(mpl.ticker.MultipleLocator(10))
        ax[0,col].xaxis.set_minor_locator(mpl.ticker.MultipleLocator(5))


    ### Legend
    handles = [
        mpl.patches.Patch(
            facecolor=data['colors'][i], edgecolor='none',
            label=i.replace('Canada','imports').split('/')[-1]
        )
        for i in data['colors'] if i in alltechs
    ]
    leg = ax[0,-1].legend(
        handles=handles[::-1], loc='upper left', bbox_to_anchor=(1.0,1.0), 
        fontsize='medium', ncol=1,  frameon=False,
        handletextpad=0.3, handlelength=0.7, columnspacing=0.5, 
    )

    ###### Difference
    for col, case in enumerate(cases):
        ax[1,col].xaxis.set_major_locator(mpl.ticker.MultipleLocator(10))
        ax[1,col].xaxis.set_minor_locator(mpl.ticker.MultipleLocator(5))
        ax[1,col].axhline(0,c='k',ls='--',lw=0.75)

        if (case not in data['data']) or (case == basecase):
            continue
        dfplot = data['data'][case].pivot_table(index='t', columns='i', values='Value',aggfunc='sum')
        dfplot = (
            dfplot
            .round(3).replace(0,np.nan)
            .dropna(axis=1, how='all')
            / data['conversionfactor'] # to GW or TWh
        )
        dfplot = dfplot.subtract(dfbase[slidetitle], fill_value=0)
        dfplot = dfplot[[c for c in data['colors'] if c in dfplot]].copy()
        alltechs.update(dfplot.columns)
        reeds.plots.stackbar(df=dfplot, ax=ax[1,col], colors=data['colors'], net=True)

    reeds.plots.despine(ax)
    plt.draw()
    reeds.plots.shorten_years(ax[1,0])
    ### Save it
    slide = reeds.report_utils.add_to_pptx(
        slidetitle+' stack', prs=prs, width=None, height=SLIDE_HEIGHT)
    if interactive:
        plt.show()

for case in cases:
    print('Using tech categories...')
    dictin_revenue[case].i = dictin_revenue[case].i.str.lower().map(lambda x: techcatmap.get(x,x))
    dictin_cap[case].i = dictin_cap[case].i.str.lower().map(lambda x: techcatmap.get(x,x))

rev_techs = dictin_revenue[case].i.unique()

base_case = next(iter(cases))

# Revenue difference maps
### Shared data
base = cases[list(cases.keys())[0]]
val_r = dictin_cap[basecase].r.unique()
dfmap = reeds.io.get_dfmap(base)
dfba = dfmap['r']
dfstates = dfmap['st']

### set legend coords
#### Absolute maps
if (nrows == 1) or (ncols == 1):
    legendcoords = max(nrows, ncols) - 1
elif (nrows-1, ncols-1) in coords.values():
    legendcoords = (nrows-1, ncols-1)
else:
    legendcoords = (nrows-2, ncols-1)

# total  rervenue
### Set up plot
### Get limits
revenue = pd.concat({
    case:
    dictin_revenue[case].loc[
        (dictin_revenue[case].t==plotyear)
        ]
    .groupby('r').Value.sum()
    for case in cases
},axis=1).fillna(0)
cap = pd.concat({
    case:
    dictin_cap[case].loc[
        (dictin_cap[case].t==plotyear)
        ]
    .groupby('r').Value.sum() * 1e3 # sum of different subtechs
    for case in cases
},axis=1)
norm_revenue = revenue/cap
revdiff = revenue.subtract(revenue[basecase], axis=0)
print(f'Total national revenue difference: ' + str(revdiff.sum()))
dfdiff = norm_revenue.subtract(norm_revenue[basecase], axis=0)
print(f'Total normalized revenue difference summary:')
print(dfdiff.describe())
### Get colorbar limits
absmax = norm_revenue.stack().max()
diffmax = dfdiff.unstack().abs().max()

if np.isnan(absmax):
    absmax = 0.

### Set up plot
plt.close()
f,ax = plt.subplots(
    nrows, ncols, figsize=(scale*ncols, scale*nrows*0.75),
    gridspec_kw={'wspace':0.0,'hspace':-0.1},
)
### Plot it
for case in cases:
    dfplot = dfba.copy()
    dfplot['$/kW'] = norm_revenue[case] if case == basecase else dfdiff[case]

    ax[coords[case]].set_title(case)
    dfba.plot(
        ax=ax[coords[case]],
        facecolor='none', edgecolor='k', lw=0.1, zorder=10000)
    dfstates.plot(
        ax=ax[coords[case]],
        facecolor='none', edgecolor='k', lw=0.2, zorder=10001)
    dfplot.plot(
        ax=ax[coords[case]], column='$/kW',
        cmap=(cmap if case == basecase else cmap_diff),
        vmin=(0 if case == basecase else -diffmax),
        vmax=(absmax if case == basecase else diffmax),
        legend=False,
        missing_kwds={'color': 'darkgrey'}
    )
    ## Difference legend
    if coords[case] == legendcoords:
        reeds.plots.addcolorbarhist(
            f=f, ax0=ax[coords[case]], data=dfplot['$/kW'].values,
            title=f'Total {plotyear}\nrevenue, difference\nfrom {basecase} [$/kW]',
            title_fontsize = 'x-small',
            cmap=(cmap if case == basecase else cmap_diff),
            vmin=(0 if case == basecase else -diffmax),
            vmax=(absmax if case == basecase else diffmax),
            orientation='horizontal', labelpad=2.25, histratio=2.,
            cbarwidth=0.05, cbarheight=0.85,
            cbarbottom=-0.1, cbarhoffset=0.,
            histcolor='grey', nbins=25,
        )
## Absolute legend
reeds.plots.addcolorbarhist(
    f=f, ax0=ax[coords[basecase]], data=norm_revenue[basecase].values,
    title=f'Total {plotyear}\nrevenue [$/kW]',
    title_fontsize = 'x-small',
    cmap=cmap, vmin=0, vmax=absmax,
    orientation='horizontal', labelpad=2.25, histratio=2.,
    cbarwidth=0.05, cbarheight=0.85,
    cbarbottom=-0.1, cbarhoffset=0.,
    nbins=25,
)

for row in range(nrows):
    for col in range(ncols):
        if nrows == 1:
            ax[col].axis('off')
        elif ncols == 1:
            ax[row].axis('off')
        else:
            ax[row,col].axis('off')
### Save it
slide = reeds.report_utils.add_to_pptx(f'Total revenue {plotyear} [$/kW]', prs=prs)
if interactive:
    plt.show()

#TODO: map rev_cats to pretty names
renamecats = {
    'load':'Energy',
    'res_marg':'Capacity',
    'oper_res':'Operating reserves',
    'rps':'RPS',
    'charge':'Charging',
}
# revenue by revenue category
for case in cases:
    dictin_revenue[case].rev_cat = dictin_revenue[case].rev_cat.map(lambda x: renamecats.get(x,x))

rev_cats = dictin_revenue[basecase].rev_cat.unique()

for cat in rev_cats:
    ### Get limits
    revenue = pd.concat({
        case:
        dictin_revenue[case].loc[
            (dictin_revenue[case].t==plotyear)
            &(dictin_revenue[case].rev_cat==cat)
            ]
        .groupby('r').Value.sum()
        for case in cases
    },axis=1).fillna(0)
    cap = pd.concat({
        case:
        dictin_cap[case].loc[
            (dictin_cap[case].t==plotyear)
            ]
        .groupby('r').Value.sum() * 1e3 # sum of different subtechs
        for case in cases
    },axis=1)
    norm_revenue = revenue/cap
    revdiff = revenue.subtract(revenue[basecase], axis=0)
    print(f'{cat} national revenue difference: ' + str(revdiff.sum()))
    dfdiff = norm_revenue.subtract(norm_revenue[basecase], axis=0)
    print(f'{cat} normalized revenue difference summary:')
    print(dfdiff.describe())
    ### Get colorbar limits
    absmax = norm_revenue.stack().max()
    diffmax = dfdiff.unstack().abs().max()

    if np.isnan(absmax):
        absmax = 0.
    if not absmax:
        print(f'{cat} has zero capacity in {plotyear}, so skipping maps')
        continue
    ### Set up plot
    plt.close()
    f,ax = plt.subplots(
        nrows, ncols, figsize=(scale*ncols, scale*nrows*0.75),
        gridspec_kw={'wspace':0.0,'hspace':-0.1},
    )
    ### Plot it
    for case in cases:
        dfplot = dfba.copy()
        dfplot['$/kW'] = norm_revenue[case] if case == basecase else dfdiff[case]

        ax[coords[case]].set_title(case)
        dfba.plot(
            ax=ax[coords[case]],
            facecolor='none', edgecolor='k', lw=0.1, zorder=10000)
        dfstates.plot(
            ax=ax[coords[case]],
            facecolor='none', edgecolor='k', lw=0.2, zorder=10001)
        dfplot.plot(
            ax=ax[coords[case]], column='$/kW',
            cmap=(cmap if case == basecase else cmap_diff),
            vmin=(0 if case == basecase else -diffmax),
            vmax=(absmax if case == basecase else diffmax),
            legend=False,
            missing_kwds={'color': 'darkgrey'}
        )
        ## Difference legend
        if coords[case] == legendcoords:
            reeds.plots.addcolorbarhist(
                f=f, ax0=ax[coords[case]], data=dfplot['$/kW'].values,
                title=f'{cat} {plotyear}\nrevenue, difference\nfrom {basecase} [$/kW]',
                title_fontsize = 'x-small',
                cmap=(cmap if case == basecase else cmap_diff),
                vmin=(0 if case == basecase else -diffmax),
                vmax=(absmax if case == basecase else diffmax),
                orientation='horizontal', labelpad=2.25, histratio=2.,
                cbarwidth=0.05, cbarheight=0.85,
                cbarbottom=-0.1, cbarhoffset=0.,
                histcolor='grey',nbins=25,
            )
    ## Absolute legend
    reeds.plots.addcolorbarhist(
        f=f, ax0=ax[coords[basecase]], data=norm_revenue[basecase].values,
        title=f'{cat} {plotyear}\nrevenue [$/kW]',
        title_fontsize = 'x-small',
        cmap=cmap, vmin=0, vmax=absmax,
        orientation='horizontal', labelpad=2.25, histratio=2.,
        cbarwidth=0.05, cbarheight=0.85,
        cbarbottom=-0.1, cbarhoffset=0.,
        nbins=25,
    )

    for row in range(nrows):
        for col in range(ncols):
            if nrows == 1:
                ax[col].axis('off')
            elif ncols == 1:
                ax[row].axis('off')
            else:
                ax[row,col].axis('off')
    ### Save it
    slide = reeds.report_utils.add_to_pptx(f'{cat} revenue {plotyear} [$/kW]', prs=prs)
    if interactive:
        plt.show()

# revenue by technology type
### Set up plot
for tech in rev_techs:
    ### Get limits
    revenue = pd.concat({
        case:
        dictin_revenue[case].loc[
            (dictin_revenue[case].t==plotyear)
            &(dictin_revenue[case].i==tech)
            ]
        .groupby('r').Value.sum() # sum of different revenue categories and subtechs
        for case in cases
    },axis=1).fillna(0)
    cap = pd.concat({
        case:
        dictin_cap[case].loc[
            (dictin_cap[case].t==plotyear)
            &(dictin_cap[case].i==tech)
            ]
        .groupby('r').Value.sum() * 1e3 # sum of different subtechs
        for case in cases
    },axis=1)
    norm_revenue = revenue/cap
    revdiff = revenue.subtract(revenue[basecase], axis=0)
    print(f'{tech} national revenue difference: ' + str(revdiff.sum()))
    dfdiff = norm_revenue.subtract(norm_revenue[basecase], axis=0)
    print(f'{tech} normalized revenue difference summary:')
    print(dfdiff.describe())
    ### Get colorbar limits
    absmax = norm_revenue.stack().max()
    diffmax = dfdiff.unstack().abs().max()

    if np.isnan(absmax):
        absmax = 0.
    if not absmax:
        print(f'{tech} has zero capacity in {plotyear}, so skipping maps')
        continue
    ### Set up plot
    plt.close()
    f,ax = plt.subplots(
        nrows, ncols, figsize=(scale*ncols, scale*nrows*0.75),
        gridspec_kw={'wspace':0.0,'hspace':-0.1},
    )
    ### Plot it
    for case in cases:
        dfplot = dfba.copy()
        dfplot['$/kW'] = norm_revenue[case] if case == basecase else dfdiff[case]

        ax[coords[case]].set_title(case)
        dfba.plot(
            ax=ax[coords[case]],
            facecolor='none', edgecolor='k', lw=0.1, zorder=10000)
        dfstates.plot(
            ax=ax[coords[case]],
            facecolor='none', edgecolor='k', lw=0.2, zorder=10001)
        dfplot.plot(
            ax=ax[coords[case]], column='$/kW',
            cmap=(cmap if case == basecase else cmap_diff),
            vmin=(0 if case == basecase else -diffmax),
            vmax=(absmax if case == basecase else diffmax),
            legend=False,
            missing_kwds={'color': 'darkgrey'}
        )
        ## Difference legend
        if coords[case] == legendcoords:
            reeds.plots.addcolorbarhist(
                f=f, ax0=ax[coords[case]], data=dfplot['$/kW'].values,
                title=f'{tech} {plotyear}\nrevenue, difference\nfrom {basecase} [$/kW]',
                title_fontsize = 'x-small',
                cmap=(cmap if case == basecase else cmap_diff),
                vmin=(0 if case == basecase else -diffmax),
                vmax=(absmax if case == basecase else diffmax),
                orientation='horizontal', labelpad=2.25, histratio=2.,
                cbarwidth=0.05, cbarheight=0.85,
                cbarbottom=-0.1, cbarhoffset=0.,
                histcolor='grey',nbins=25,
            )
    ## Absolute legend
    reeds.plots.addcolorbarhist(
        f=f, ax0=ax[coords[basecase]], data=norm_revenue[basecase].values,
        title=f'{tech} {plotyear}\nrevenue [$/kW]',
        title_fontsize = 'x-small',
        cmap=cmap, vmin=0, vmax=absmax,
        orientation='horizontal', labelpad=2.25, histratio=2.,
        cbarwidth=0.05, cbarheight=0.85,
        cbarbottom=-0.1, cbarhoffset=0.,
        nbins=25,
    )

    for row in range(nrows):
        for col in range(ncols):
            if nrows == 1:
                ax[col].axis('off')
            elif ncols == 1:
                ax[row].axis('off')
            else:
                ax[row,col].axis('off')
    ### Save it
    slide = reeds.report_utils.add_to_pptx(f'{tech} revenue {plotyear} [$/kW]', prs=prs)
    if interactive:
        plt.show()

#%%### Price maps by category
renameprice = {
    'load': 'Energy',
    'res_marg': 'Capacity (seasonal)',
    'res_marg_ann': 'Capacity (annual)',
    'oper_res': 'Operating reserves',
    'state_rps': 'State RPS',
    'nat_gen': 'National gen standard',
    'annual_cap': 'Annual emissions cap',
    'eq_loadcon': 'Load constraint',
}

price_units = {
    'load': '$/MWh',
    'oper_res': '$/MWh',
    'res_marg': '$/MW-day',
    'res_marg_ann': '$/MW-day',
    'state_rps': '$/MWh',
    'nat_gen': '$/MWh',
    'eq_loadcon': '$/MW-yr',
}

price_col = '*'  # first column of reqt_price: the price category
price_time_col = '*.2'  # timeslice/season column in reqt_price

price_cats = dictin_price[basecase][price_col].unique()

for cat in price_cats:
    unit = price_units.get(cat, '$/unit')

    cat_time_values = [None]
    if cat == 'res_marg':
        cat_time_values = sorted(
            dictin_price[basecase].loc[
                (dictin_price[basecase].t == plotyear)
                & (dictin_price[basecase][price_col] == cat),
                price_time_col,
            ].dropna().unique()
        )
        if len(cat_time_values) > 24:
            print(
                f'res_marg has {len(cat_time_values)} time slices in {plotyear}; '
                'skipping per-slice maps and using aggregate map instead.'
            )
            cat_time_values = [None]

    for time_val in cat_time_values:
        time_suffix = '' if time_val is None else f' ({time_val})'

        ### Get average price per region for this category/slice
        price = pd.concat({
            case:
            dictin_price[case].loc[
                (dictin_price[case].t == plotyear)
                & (dictin_price[case][price_col] == cat)
                & (
                    (dictin_price[case][price_time_col] == time_val)
                    if time_val is not None else True
                )
            ]
            .groupby('r').Value.mean()
            for case in cases
        }, axis=1).fillna(0)

        # Convert reserve margin prices from $/MW-year to $/MW-day.
        if cat in ['res_marg', 'res_marg_ann']:
            price = price / 365.0

        pricediff = price.subtract(price[basecase], axis=0)
        print(
            f"{renameprice.get(cat, cat)}{time_suffix} national average price difference "
            f"[{unit}]"
        )
        print(pricediff.mean().to_string())

        ### Get colorbar limits
        absmax = price.stack().max()
        diffmax = pricediff.unstack().abs().max()

        if np.isnan(absmax) or not absmax:
            print(f'{cat}{time_suffix} has zero price in {plotyear}, so skipping maps')
            continue

        ### Set up plot
        plt.close()
        f, ax = plt.subplots(
            nrows, ncols, figsize=(scale * ncols, scale * nrows * 0.75),
            gridspec_kw={'wspace': 0.0, 'hspace': -0.1},
        )
        ### Plot it
        for case in cases:
            dfplot = dfba.copy()
            dfplot[unit] = price[case] if case == basecase else pricediff[case]

            ax[coords[case]].set_title(case)
            dfba.plot(
                ax=ax[coords[case]],
                facecolor='none', edgecolor='k', lw=0.1, zorder=10000)
            dfstates.plot(
                ax=ax[coords[case]],
                facecolor='none', edgecolor='k', lw=0.2, zorder=10001)
            dfplot.plot(
                ax=ax[coords[case]], column=unit,
                cmap=(cmap if case == basecase else cmap_diff),
                vmin=(0 if case == basecase else -diffmax),
                vmax=(absmax if case == basecase else diffmax),
                legend=False,
                missing_kwds={'color': 'darkgrey'}
            )
            ## Difference legend
            if coords[case] == legendcoords:
                reeds.plots.addcolorbarhist(
                    f=f, ax0=ax[coords[case]], data=dfplot[unit].values,
                    title=(f'{renameprice.get(cat, cat)}{time_suffix} {plotyear}\n'
                           f'price, difference\nfrom {basecase} [{unit}]'),
                    title_fontsize='x-small',
                    cmap=(cmap if case == basecase else cmap_diff),
                    vmin=(0 if case == basecase else -diffmax),
                    vmax=(absmax if case == basecase else diffmax),
                    orientation='horizontal', labelpad=2.25, histratio=2.,
                    cbarwidth=0.05, cbarheight=0.85,
                    cbarbottom=-0.1, cbarhoffset=0.,
                    histcolor='grey', nbins=25,
                )
        ## Absolute legend
        reeds.plots.addcolorbarhist(
            f=f, ax0=ax[coords[basecase]], data=price[basecase].values,
            title=f'{renameprice.get(cat, cat)}{time_suffix} {plotyear}\nprice [{unit}]',
            title_fontsize='x-small',
            cmap=cmap, vmin=0, vmax=absmax,
            orientation='horizontal', labelpad=2.25, histratio=2.,
            cbarwidth=0.05, cbarheight=0.85,
            cbarbottom=-0.1, cbarhoffset=0.,
            nbins=25,
        )

        for row in range(nrows):
            for col in range(ncols):
                if nrows == 1:
                    ax[col].axis('off')
                elif ncols == 1:
                    ax[row].axis('off')
                else:
                    ax[row, col].axis('off')
        ### Save it
        slide = reeds.report_utils.add_to_pptx(
            f'{renameprice.get(cat, cat)}{time_suffix} price {plotyear} [{unit}]', prs=prs)
        if interactive:
            plt.show()


# total generation difference check
gen = pd.concat({
    case:
    dictin_gen[case].loc[
        (dictin_gen[case].t==plotyear)
        ].groupby('i').Value.sum()
    for case in cases
},axis=1).fillna(0)

gendiff = gen.subtract(gen[basecase], axis=0)

print(f'National generation difference: ' + str(gendiff.sum()/1e6) + ' TWh')



#%% Save the powerpoint file
prs.save(savename)
print(f'\ncompare_casegroup.py results saved to:\n{savename}')

### Open it
if sys.platform == 'darwin':
    sp.run(f"open '{savename}'", shell=True)
elif platform.system() == 'Windows':
    sp.run(f'"{savename}"', shell=True)
