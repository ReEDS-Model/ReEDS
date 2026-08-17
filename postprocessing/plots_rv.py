#%% Imports
import os
import sys
import shutil
import cmocean
import subprocess
import pandas as pd
from tqdm import tqdm
from pathlib import Path
from datetime import datetime
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import patheffects as pe
sys.path.append(str(Path(__file__).parent.parent))
import reeds
reeds.plots.plotparams()

#%% Inputs
runspath = Path('/projects/reedsweto/pbrown/github2/ReEDS/runs')

_casebase = 'v20260720_mgasmallM0_Opt'
prefix = 'v20260720_mgasmallK0_MGAH_cost0p1_cap0_R0'
prefix = 'v20260720_mgasmallK0_MGAH_cost0p1_cap0p1_R0'
prefix = 'v20260720_mgasmallK0_MGAH_cost0p1_cap1_R0'
prefix = 'v20260720_mgasmallK0_MGAH_cost1_cap0_R0'
prefix = 'v20260720_mgasmallK0_MGAH_cost1_cap1_R0'
prefix = 'v20260720_mgasmallK0_MGAL_cost1_cap1_R0'
prefix = 'v20260720_mgasmallK0_MGAH_cost1_cap0p1_R0'

_casebase = 'v20260803_mgasmallK0_Opt'
prefix = 'v20260804_mgasmallK0_MGAH_cost5_cap0p1_R0'
prefix = 'v20260804_mgasmallK0_MGAH_cost2_cap0p1_R0'
prefix = 'v20260804_mgasmallK0_MGAH_cost1_cap0p1_R0'
prefix = 'v20260804_mgasmallK0_MGAH_cost1_cap0_R0'

casebase = str(Path(runspath, _casebase))
basename = 'opt'
cases = sorted(runspath.glob(f'{prefix}*'))
casenames = {
    casebase: basename,
    **{i: i.name[len(prefix):] for i in cases}
}
print(len(casenames))

#%%### Get data
dictin_cap = {}
for casepath, name in tqdm(casenames.items()):
    try:
        dictin_cap[name] = reeds.io.read_output(str(casepath), 'cap')
    except FileNotFoundError:
        print(f'Missing {name}')
        continue
    ## Simplify techs and convert to GW
    dictin_cap[name].i = reeds.reedsplots.simplify_techs(dictin_cap[name].i)
    dictin_cap[name] = dictin_cap[name].groupby(['t','i','r']).Value.sum() / 1e3

samplenames = [
    name for path,name in casenames.items()
    if (path in cases) and (name in dictin_cap)
]
print(len(samplenames))

#%%
dictin_stress = {}
for casepath, name in tqdm(casenames.items()):
    try:
        dictin_stress[name] = reeds.reedsplots.get_stressperiods(str(casepath))
    except FileNotFoundError:
        print(f'Missing {name}')
        continue


#%%### Plots ######
year = 2050
crs = 'EPSG:5070'
dfmap = reeds.io.get_dfmap(casebase)
for key, df in dfmap.items():
    dfmap[key] = df.to_crs(crs)
    ## TODO: Replace with simplify_geometry once we update the environment
    dfmap[key].geometry = dfmap[key].simplify(2000)
## Scale maps
bounds = dfmap['country'].bounds.squeeze(0)
mapsize = {
    'x': bounds.maxx - bounds.minx,
    'y': bounds.maxy - bounds.miny,
}
mapheight = mapsize['y'] / mapsize['x']
## Colors
plot_settings = reeds.io.get_plot_formatting()
tech_color = plot_settings['tech_color'].color

#%%### Capacity deviation from optimal
scale = 1
cmap = plt.cm.coolwarm
cmap = plt.cm.bwr
cmap = plt.cm.seismic
cmap = plt.cm.RdBu_r
cmap = cmocean.tools.crop_by_percent(plt.cm.RdBu_r, 10)

_diffmax = 20
techs = ['UPV', 'Onshore Wind', 'Battery', 'Gas-CT', 'Gas-CC']

nrows, ncols, coords = reeds.plots.get_coordinates(samplenames, aspect=1)
offset = {dim: size * 1.05 for dim, size in mapsize.items()}


for tech in techs:
    ## Get diffs
    dictplot = {}
    for name in samplenames:
        dictplot[name] = (
            dictin_cap[name].loc[year].loc[tech]
            - dictin_cap[basename].loc[year].loc[tech]
        )
    dfplot = pd.concat(dictplot)
    diffmax = dfplot.abs().max() if not _diffmax else _diffmax

    # ### Subplots (slower)
    # plt.close()
    # f,ax = plt.subplots(
    #     nrows, ncols, figsize=(ncols*scale, nrows*scale*mapheight),
    #     sharex=True, sharey=True,
    #     gridspec_kw={'hspace':0, 'wspace':0},
    # )
    # ## Data
    # for name in samplenames:
    #     _ax = ax[coords[name]]
    #     dfmap['country'].plot(ax=_ax, facecolor='none', edgecolor='k', lw=0.1)
    # ## Formatting
    # for row in range(nrows):
    #     for col in range(ncols):
    #         ax[row,col].axis('off')
    # plt.show()

    ### One plot
    plt.close()
    f,ax = plt.subplots(figsize=(ncols*scale, nrows*scale*mapheight))
    for name in samplenames:
        row, col = coords[name]
        country = dfmap['country'].translate(row*offset['x'], col*offset['y'])
        country.plot(ax=ax, facecolor='none', edgecolor='k', lw=0.1, zorder=1e9)
        ## Data
        df = dfmap['r'].copy()
        df['capdiff'] = dfplot.loc[name]
        df.geometry = df.geometry.translate(row*offset['x'], col*offset['y'])
        df.plot(ax=ax, column='capdiff', cmap=cmap, vmin=-diffmax, vmax=diffmax)
    ## Colorbar
    reeds.plots.addcolorbarhist(
        f, ax, dfplot.values, cmap=cmap, vmin=-diffmax, vmax=diffmax,
        nbins=51, cbarwidth=0.02, histratio=2,
        title=f'{tech}\ndiff from\noptimal,\n{year}\n[GW]',
    )
    ## Formatting
    ax.axis('off')
    plt.show()


#%% Capacity stack bars: national
dfplot = pd.concat(
    {name: dictin_cap[name].loc[year].groupby('i').sum() for name in samplenames},
    axis=1,
).fillna(0)
dfplot.columns = range(dfplot.shape[1])
order = [
    i for i in tech_color.index
    if (
        (i in dfplot.index.get_level_values('i'))
        and (i not in ['Canadian Imports', 'Electrolyzer'])
    )
]

plt.close()
f,ax = plt.subplots(figsize=(3,2.5))
df = dfplot.reindex(order).dropna(how='all').fillna(0).T
reeds.plots.stackbar(
    df, ax, colors=tech_color, net=False,
)
## Legend
handles = [
    mpl.patches.Patch(facecolor=tech_color[tech], edgecolor='none', label=tech)
    for tech in order
]
ax.legend(
    handles=handles[::-1],
    loc='upper left', bbox_to_anchor=(1, 1), frameon=False,
    handletextpad=0.3, handlelength=0.7,
    ncols=2, columnspacing=0.5,
)
## Formatting
ax.set_ylabel(f'{year} capacity [GW]')
ax.set_xlabel('Sample number')
ax.set_xlim(-0.5, df.shape[0]-0.5)
ax.xaxis.set_major_locator(mpl.ticker.MultipleLocator(10))
reeds.plots.despine(ax)
plt.show()


#%% Capacity diff bars: national
dfplot = pd.concat(
    {
        name:
        dictin_cap[name].loc[year].groupby('i').sum() - dictin_cap['opt'].loc[year].groupby('i').sum()
        for name in samplenames},
    axis=1,
).fillna(0)
dfplot.columns = range(dfplot.shape[1])
order = [
    i for i in tech_color.index
    if (
        (i in dfplot.index.get_level_values('i'))
        and (i not in ['Canadian Imports', 'Electrolyzer'])
    )
]

plt.close()
f,ax = plt.subplots(figsize=(3,2.5))
df = dfplot.reindex(order).dropna(how='all').fillna(0).T
reeds.plots.stackbar(
    df, ax, colors=tech_color, net=False,
)
## Legend
handles = [
    mpl.patches.Patch(facecolor=tech_color[tech], edgecolor='none', label=tech)
    for tech in order
]
ax.legend(
    handles=handles[::-1],
    loc='upper left', bbox_to_anchor=(1, 1), frameon=False,
    handletextpad=0.3, handlelength=0.7,
    ncols=2, columnspacing=0.5,
)
## Formatting
ax.set_ylabel(f'{year} capacity [GW]')
ax.set_xlabel('Sample number')
ax.set_xlim(-0.5, df.shape[0]-0.5)
ax.xaxis.set_major_locator(mpl.ticker.MultipleLocator(10))
reeds.plots.despine(ax)
plt.show()


#%%### Number of extra stress periods
dfplot = pd.concat(
    {
        name:
        # dictin_stress[name].loc[(dictin_stress[name].reset_index().iteration > 0).values]
        dictin_stress[name].groupby(['year','iteration']).count().groupby('year').max()
        - dictin_stress[name].groupby(['year','iteration']).count().groupby('year').min()
        # .groupby('year').count().squeeze(1)
        # .xs(1,0,'iteration').groupby('year').count().squeeze(1)
        for name in samplenames
    },
    axis=1,
).fillna(0).astype(int)
dfplot.columns = range(dfplot.shape[1])

plt.close()
f,ax = plt.subplots(figsize=(3,1.2))
dfplot.sum().plot.bar(ax=ax, width=1)
## Formatting
ax.set_ylabel('Dynamic\nstress days')
ax.set_xlabel('Sample number')
ax.set_xlim(-0.5, df.shape[0]-0.5)
ax.xaxis.set_major_locator(mpl.ticker.MultipleLocator(10))
ax.yaxis.set_major_locator(mpl.ticker.MultipleLocator(10))
reeds.plots.despine(ax)
plt.show()

#%%### Capacity stack bars: zones
level = 'r'
zones = sorted(dfmap[level].index)
year = 2050
labelalpha = 0.7
nrows, ncols, coords = reeds.plots.get_coordinates(zones, aspect=0.7)
print(nrows, ncols)
figsize = (10, 6)
sharey = True
sharey = False

dfplot = pd.concat(
    {name: dictin_cap[name].loc[year] for name in samplenames},
    axis=1,
).reorder_levels(['r','i']).fillna(0)
dfplot.columns = range(dfplot.shape[1])
order = [
    i for i in tech_color.index
    if (
        (i in dfplot.index.get_level_values('i'))
        and (i not in ['Canadian Imports', 'Electrolyzer'])
    )
]

plt.close()
f,ax = plt.subplots(
    nrows, ncols, figsize=figsize, sharex=True, sharey=sharey,
    gridspec_kw={'hspace':0.3, 'wspace':0.3},
)
for zone in tqdm(zones):
    _ax = ax[coords[zone]]
    df = dfplot.loc[zone].reindex(order).dropna(how='all').fillna(0).T
    reeds.plots.stackbar(
        df, _ax, colors=tech_color, net=False,
    )
    _ax.annotate(
        zone, (0,0), xytext=(3,3), textcoords='offset points',
        color='k', fontsize=12, alpha=labelalpha, weight='bold',
        path_effects=[pe.withStroke(linewidth=1.5, foreground='w', alpha=labelalpha)],
    )
## Legend
handles = [
    mpl.patches.Patch(facecolor=tech_color[tech], edgecolor='none', label=tech)
    for tech in order
]
ax[0,-1].legend(
    handles=handles[::-1],
    loc='upper left', bbox_to_anchor=(1, 1), frameon=False,
    handletextpad=0.3, handlelength=0.7,
)
## Formatting
ax[-1,0].set_ylabel(f'{year} capacity [GW]', y=0, ha='left')
ax[-1,0].set_xlabel('Sample number', x=0, ha='left')
ax[0,0].set_xlim(-0.5, df.shape[0]-0.5)
reeds.plots.trim_subplots(ax, nrows, ncols, len(zones))
reeds.plots.despine(ax)
plt.show()


#%%### Jitter video loop ######
today = datetime.now().strftime("%Y%m%d")
scratch = Path(reeds.io.reeds_path, 'runs', today)
scratch.mkdir(parents=True, exist_ok=True)
for f in scratch.glob('*.png'):
    f.unlink()
#%% Copy the frames
for casepath, name in tqdm(casenames.items()):
    inpath = Path(casepath, 'outputs', 'figures', 'map_gencap_transcap-2050.png')
    if inpath.is_file():
        shutil.copy(inpath, Path(scratch, f'map_gencap_transcap-{name}.png'))
    else:
        print(f'Missing {inpath}')

#%% Make the video (if it doesn't work, run the printed command from the command line)
command = (
    "ffmpeg "
    "-framerate {fps} "
    "-pattern_type glob "
    "-i '{figpath}{sep}map_gencap_transcap-*.png' "
    "-pix_fmt yuv420p "
    "-vf 'crop=trunc(iw/2)*2:trunc(ih/2)*2' "
    "{figpath}{sep}map_gencap_transcap-{prefix}.mp4"
).format(
    fps=24, sep=os.sep, figpath=scratch, prefix=prefix,
)
print(command)
result = subprocess.run(command, shell=True)

#%%### Debugging
#%% Why do some cases deviate more than indicated?
# prefix = 'v20260720_mgasmallK0_MGAH_cost1_cap0p1_R0'
casename = '008'
year = 2050
dfbase = dictin_cap['opt'].loc[year]
dfcomp = dictin_cap[casename].loc[year]
print(dfbase.sum())
print(dfcomp.sum())
print(1 - dfcomp.sum() / dfbase.sum())

#%%
dfcomp.groupby('i').sum() / dfbase.groupby('i').sum()
