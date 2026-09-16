#%%### Imports
import sys
import pandas as pd
from pathlib import Path
import matplotlib as mpl
import matplotlib.pyplot as plt
sys.path.append(str(Path(__file__).parent.parent))
import reeds


#%%### Inputs
rtypes = ['NLR', 'NLR_clipped', 'DLR']
periodtype = 'rep'
nicelabels = {
    'NLR': 'AAR',
    'NLR_clipped': 'AAR (clipped)',
    'DLR': 'DLR',
}
colors = {
    'NLR': 'C0',
    'NLR_clipped': 'C2',
    'DLR': 'C3',
}


#%%### Get data
dictin = {
    rtype: reeds.io.get_trans_cap_delta_hourly(
        periodtype=periodtype,
        GSw_HourlyLineRatingTypeRep=rtype,
        GSw_HourlyLineRatingTypeStress=rtype,
    )
    for rtype in rtypes
}

dictin['NLR_clipped'] = dictin['NLR'].clip(lower=0)

### Downselect to ReEDS ITLs and flatten column names
dfitls = reeds.inputs.get_itls()
r_rrs = pd.concat([
    dfitls[['r','rr']],
    dfitls[['rr','r']].rename(columns={'r':'rr','rr':'r'}),
])
r_rrs = list(r_rrs.itertuples(index=False, name=None))
for key, df in dictin.items():
    dictin[key] = dictin[key][r_rrs].copy()
    dictin[key].columns = dictin[key].columns.map(lambda x: '~~'.join(list(x)))


#%%### Distributions
import importlib
importlib.reload(reeds.plots)
ncols = len(rtypes)
percentiles = [0.01, 0.1, 0.2]
ylim = (-20, 80)

#%% By hour
plt.close()
f,ax = plt.subplots(1, ncols, figsize=(1.5*ncols, 3.75), sharex=True, sharey=True)
for col, rtype in enumerate(rtypes):
    _ax = ax[col]
    _ax.set_title(nicelabels.get(rtype,rtype))
    reeds.plots.plot_distribution(
        dfraw=dictin[rtype]*100,
        ax=_ax,
        percentiles=percentiles,
        color=colors[rtype],
        drawlegend=True,
    )
ax[0].set_ylabel('ITL increase [%]')
ax[1].set_xlabel('Percent of hours [%]')
ax[0].set_ylim(*ylim)
reeds.plots.despine(ax)
plt.show()


#%% By interface and direction
plt.close()
f,ax = plt.subplots(1, ncols, figsize=(1.5*ncols, 3.75), sharex=True, sharey=True)
for col, rtype in enumerate(rtypes):
    _ax = ax[col]
    _ax.set_title(nicelabels.get(rtype,rtype))
    reeds.plots.plot_distribution(
        dfraw=dictin[rtype].T*100,
        ax=_ax,
        percentiles=percentiles,
        color=colors[rtype],
        drawlegend=True,
    )
ax[0].set_ylabel('ITL increase [%]')
ax[1].set_xlabel('Percent of interfaces and directions [%]')
## Fiddles
ax[-1].axhline(0, c='0.8', ls=':', lw=0.75)
ax[0].set_ylim(*ylim)
reeds.plots.despine(ax)
plt.show()
