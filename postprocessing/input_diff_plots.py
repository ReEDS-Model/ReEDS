#%% Imports
import os
import sys
import argparse
import pandas as pd
import geopandas as gpd
from pathlib import Path
from typing import Literal
import matplotlib.pyplot as plt
from matplotlib import patheffects as pe
import cmocean
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds


#%% User-defined plot settings
## Percent absolute difference in CF
diffmax = 2


#%% Plotting functions
def plot_diff_maps(
    dfmap,
    data,
    title='',
    cmap=plt.cm.turbo,
    cmap_diff=plt.cm.RdBu_r,
    diffmax=None,
    scale=1,
    value_name='CF',
    units='%',
    vmin=None,
    vmax=None,
):
    """
    Plot absolute and difference maps.

    Args:
        dfmap: Either standard dictionary of geodataframes from `reeds.io.get_dfmap()`
            or a single geodataframe with `r` index
        data: Dictionary of pd.Series with `old` and `new` keys and `r` index
        title: String to print in top left of maps
        value_name: Value label used in colorbar titles
        cmap: Colormap object for absolute maps
        cmap_diff: Colormap object for difference map
        diffmax: Color axis limit for difference plots [%]
    
    Returns:
        Tuple: (f, ax)
    """
    nrows = 1
    ncols = 3
    figscale = 4
    vmin = (0. if vmin is None else vmin) * scale
    vmax = (max([data[case].max() for case in data]) if vmax is None else vmax) * scale

    dfr = (dfmap['r'] if isinstance(dfmap, dict) else dfmap)

    plt.close()
    f,ax = plt.subplots(
        nrows, ncols, sharex=True, sharey=True, figsize=(figscale*ncols, figscale*nrows*0.75),
        gridspec_kw={'wspace':0},
    )
    ## Absolute
    for (col, case) in enumerate(data.keys()):
        _ax = ax[col]
        df = dfr.copy()
        df['value'] = data[case] * scale
        if 'st' in dfmap:
            dfmap['st'].plot(ax=_ax, facecolor='none', edgecolor='w', lw=0.1, zorder=1e7)
        if 'country' in dfmap:
            dfmap['country'].plot(ax=_ax, facecolor='none', edgecolor='k', lw=0.2, zorder=1e8)
        df.plot(ax=_ax, column='value', vmin=vmin, vmax=vmax, cmap=cmap)
        reeds.plots.addcolorbarhist(
            f, _ax, df['value'].values, vmin=vmin, vmax=vmax, cmap=cmap,
            title=f"{value_name} ({case}) [{units}]",
            nbins=51, cbarheight=0.8, cbarwidth=0.04, histratio=2,
            orientation='horizontal', cbarbottom=-0.1, labelpad=3.3,
        )
        _ax.axis('off')
    ## Difference
    col = 2
    _ax = ax[col]
    df = dfr.copy()
    df['value'] = (data['new'] - data['old']) * scale
    _diffmax = max((df['value'].abs().max() if not diffmax else diffmax), 0.1)
    if 'st' in dfmap:
        dfmap['st'].plot(ax=_ax, facecolor='none', edgecolor='0.9', lw=0.1, zorder=1e7)
    if 'country' in dfmap:
        dfmap['country'].plot(ax=_ax, facecolor='none', edgecolor='k', lw=0.2, zorder=1e8)
    df.plot(ax=_ax, column='value', vmin=-_diffmax, vmax=_diffmax, cmap=cmap_diff)
    reeds.plots.addcolorbarhist(
        f, _ax, df['value'].values, vmin=-_diffmax, vmax=_diffmax, cmap=cmap_diff,
        title=f"{value_name} diff (new - old) [{units}]",
        nbins=51, cbarheight=0.8, cbarwidth=0.04, histratio=2,
        orientation='horizontal', cbarbottom=-0.1, labelpad=3.3,
    )
    ## Label zones with differences above diffmax
    for r, row in df.iterrows():
        if abs(row.value) > _diffmax:
            _ax.annotate(
                f"{row.value:+.0f}", (row.geometry.centroid.x, row.geometry.centroid.y),
                ha='center', va='center', fontsize=8, alpha=0.8, zorder=1e9,
                path_effects=[pe.withStroke(linewidth=2.5, foreground='#ffff00', alpha=0.8)],
            )
    _ax.axis('off')
    ## Formatting
    ax[0].set_title(
        title, weight='bold', fontsize='x-large',
        x=0.05, ha='left', y=0.95,
    )
    return f, ax


def plot_cf_diff(
    repo_old,
    repo_new,
    tech='wind-ons',
    access='reference',
    special='',
    cmap=plt.cm.turbo,
    cmap_diff=plt.cm.RdBu_r,
    diffmax=2,
):
    """
    Plot absolute difference in regional CF between repo_old and repo_new.

    Args:
        repo_old: Path to old ReEDS directory
        repo_new: Path to new ReEDS directory
        diffmax: Color axis limit for difference plots [%]
    
    Returns:
        Tuple: (f, ax)
    """
    ### Collect inputs
    repos = {'old': repo_old, 'new':repo_new}
    dfcf = {
        case: reeds.io.read_file(
            os.path.join(
                repos[case], 'inputs', 'profiles_cf',
                f"cf_{tech}{f'_{special}' if special else ''}_{access}_ba.h5",
            )
        ).mean()
        for case in repos
    }

    ###
    cf = {}
    for case in repos:
        cf[case] = dfcf[case].rename('cf').reset_index()
        cf[case]['class'] = cf[case]['index'].map(lambda x: int(x.split('|')[0]))
        cf[case]['region'] = cf[case]['index'].map(lambda x: x.split('|')[1])
        cf[case] = cf[case].set_index(['class','region']).cf

    ### Get available-capacity-weighted CF by zone
    dfmap = reeds.io.get_dfmap()
    if special == 'meshed':
        dfmap['r'] = pd.concat([
            dfmap['r'], 
            gpd.read_file(
                os.path.join(reeds.io.reeds_path, 'inputs', 'shapefiles', 'offshore_zones.gpkg')
            ).set_index('zone').to_crs(dfmap['r'].crs),
        ])
    supplycurve = reeds.io.assemble_supplycurve(
        scfile=os.path.join(
            repos['new'], 'inputs', 'supply_curve', f'supplycurve_{tech}-{access}.csv',
        ),
        GSw_OffshoreZones=(1 if special == 'meshed' else 0),
    )

    cap_ir = supplycurve.groupby(['class','region']).capacity.sum()
    cf_weighted = {
        case: (cf[case] * cap_ir).groupby('region').sum() / cap_ir.groupby('region').sum()
        for case in repos
    }

    ### Plot it
    f, ax = plot_diff_maps(
        dfmap=dfmap,
        data=cf_weighted,
        title=f"{tech} {access}",
        cmap=cmap,
        cmap_diff=cmap_diff,
        diffmax=diffmax,
        scale=100,
    )

    return f, ax


def get_supplycurves(
    repo_old,
    repo_new,
    tech:Literal['upv','wind-ons','egs',None]='wind-ons',
    access:Literal['limited','reference','open',None]='reference',
    crs:str='EPSG:5070',
) -> dict:
    """Get supply curves from two repos"""
    dfs = {}
    for label, repo in [('old', repo_old), ('new', repo_new)]:
        sitespath = Path(repo, 'inputs', 'supply_curve', 'interconnection_land.h5')
        dfsites = reeds.plots.df2gdf(
            reeds.io.floatify(reeds.io.read_h5_groups(sitespath)),
            crs=crs,
        )
        dfsites = reeds.spatial.site2poly_buffer(dfsites)
        if (tech is not None) and (access is not None):
            scpath = Path(repo, 'inputs', 'supply_curve', f'supplycurve_{tech}-{access}.csv')
            dfsc = pd.read_csv(scpath, index_col='sc_point_gid')
            dfs[label] = dfsites.merge(dfsc, left_index=True, right_index=True, how='right')
        elif (tech is None) and (access is None):
            dfs[label] = dfsites
        else:
            raise ValueError(f'If providing tech ({tech}) must provide access ({access})')
    return dfs


def plot_sc_diffs(
    repo_old,
    repo_new,
    tech:Literal['upv','wind-ons','egs',None]='wind-ons',
    access:Literal['limited','reference','open',None]='reference',
    crs:str='EPSG:5070',
    cmap=cmocean.cm.rain,
    cmap_diff=plt.cm.RdBu_r,
    interconnection=False,
):
    """Plot difference maps of supply curve columns"""
    data = get_supplycurves(repo_old, repo_new, tech, access, crs)
    if tech and access:
        column_units = {
            'capacity': 'MW',
            'capital_adder_per_mw': '$/MW',
            'cf': '.',
            'class': 'n/a',
        }
    else:
        column_units = {}
    if interconnection:
        column_units.update({
            'dist_spur_km': 'km',
            'dist_reinforcement_km': 'km',
            'cost_spur_usd_per_mw': '$/MW',
            'cost_reinforcement_usd_per_mw': '$/MW',
            'cost_total_trans_usd_per_mw': '$/MW',
    })
    for column, units in column_units.items():
        dfs = {key: df[column] for key, df in data.items()}
        f, ax = plot_diff_maps(
            dfmap=data['old'][['geometry']],
            data=dfs,
            title=f"{tech} {access}",
            cmap=cmap, cmap_diff=cmap_diff,
            value_name=column, units=units,
        )
        yield f, ax, column


def plot_distpv_diff(
    repo_old,
    repo_new,
    cmap=plt.cm.turbo,
    cmap_diff=plt.cm.RdBu_r,
    diffmax=2,
):
    repos = {'old': repo_old, 'new':repo_new}
    dfcf = {}
    for case in repos:
        dfcf[case] = reeds.io.read_file(
            os.path.join(
                repos[case], 'inputs', 'profiles_cf',
                'cf_distpv_county.h5',
            )
        ).mean()
        dfcf[case].index = dfcf[case].index.map(lambda x: x.split('|')[-1])

    dfmap = (
        reeds.io.get_countymap(exclude_water_areas=True)
        .rename(columns={'rb':'r'}).set_index('r')
    )

    f, ax = plot_diff_maps(
        dfmap=dfmap,
        data=dfcf,
        title='distpv',
        cmap=cmap,
        cmap_diff=cmap_diff,
        diffmax=diffmax,
        scale=100,
    )

    return f, ax


def plot_prm_diff(
    repo_old,
    repo_new,
    prm_column='nerc',
    year=None,
    cmap=cmocean.cm.tempo,
    cmap_diff=plt.cm.RdBu_r,
    diffmax=None,
):
    repos = {'old': repo_old, 'new': repo_new}
    dfprm = {}
    for case in repos:
        dfprm[case] = pd.read_csv(
            os.path.join(
                repos[case], 'inputs', 'reserves', 'prm_annual.csv',
            )
        ).rename(columns={'*nercr': 'nercr'})
        if prm_column not in dfprm[case].columns:
            raise KeyError(f"Column '{prm_column}' not found in prm_annual.csv for {case}")

    common_years = sorted(set(dfprm['old'].t) & set(dfprm['new'].t))
    if not common_years:
        raise ValueError('No overlapping years found in prm_annual.csv between old and new repos')
    plot_year = max(common_years) if year is None else year
    if plot_year not in common_years:
        raise ValueError(
            f"Year {plot_year} is not available in both old and new prm_annual.csv files"
        )

    _data = {
        case: (
            dfprm[case]
            .loc[dfprm[case].t == plot_year, ['nercr', prm_column]]
            .set_index('nercr')
            .squeeze(1)
        )
        for case in repos
    }

    dfmap = reeds.io.get_dfmap()
    hierarchy = reeds.io.get_hierarchy()
    data = {key: pd.Series(hierarchy['nercr'].map(_data[key]), hierarchy.index) for key in _data}

    f, ax = plot_diff_maps(
        dfmap=dfmap,
        data=data,
        title=f"PRM {prm_column} ({plot_year})",
        value_name='PRM',
        cmap=cmap,
        cmap_diff=cmap_diff,
        diffmax=diffmax,
        scale=100,
    )

    return f, ax


def main(repo_old, repo_new, outpath):
    ## Check inputs
    for repo in [repo_old, repo_new]:
        if not os.path.exists(repo):
            raise FileNotFoundError(repo)
    os.makedirs(outpath, exist_ok=True)

    ## Capacity factors
    for tech, special in [
        ('wind-ofs', 'meshed'),
        ('wind-ofs', 'radial'),
        ('upv', ''),
        ('wind-ons', ''),
    ]:
        for access in ['reference', 'limited', 'open']:
            f, ax = plot_cf_diff(
                repo_old, repo_new, tech=tech, access=access, special=special, diffmax=diffmax,
            )
            plt.savefig(os.path.join(
                outpath,
                f"cf_diff-{tech}{f'_{special}' if special else ''}-{access}.png"
            ))

    plot_distpv_diff(repo_old, repo_new, diffmax=diffmax)
    plt.savefig(os.path.join(outpath, 'cf_diff-distpv.png'))

    ## Planning reserve margin
    plot_prm_diff(repo_old, repo_new, prm_column='nerc')
    plt.savefig(os.path.join(outpath, 'prm_diff-nerc.png'))

    ## Supply curves
    tech_accesses = [
        ('upv', 'limited'),
        ('upv', 'reference'),
        ('upv', 'open'),
        ('wind-ons', 'limited'),
        ('wind-ons', 'reference'),
        ('wind-ons', 'open'),
        ('egs', 'reference'),
        (None, None),
    ]
    for tech, access in tech_accesses:
        label = 'interconnection' if tech is None else f"{tech.replace('-','')}-{access}"
        plot_generator = plot_sc_diffs(
            repo_old, repo_new, tech=tech, access=access,
            interconnection=(True if tech is None else False),
        )
        while True:
            try:
                f, ax, column = next(plot_generator)
                fpath = Path(outpath, f'sc_diff-{label}-{column}.png')
                plt.savefig(fpath)
                print(fpath)
            except StopIteration:
                break


#%% Procedure
if __name__ == '__main__':
    #%% Argument inputs
    parser = argparse.ArgumentParser(
        description='Plot differences in input data between ReEDS repos',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('old', help='path to old ReEDS directory')
    parser.add_argument('new', help='path to new ReEDS directory')
    parser.add_argument(
        '--outpath', '-o', default='~/Desktop',
        help='directory path to save figures to', 
    )
    args = parser.parse_args()
    repo_old = os.path.expanduser(args.old)
    repo_new = os.path.expanduser(args.new)
    outpath = os.path.expanduser(args.outpath)

    # #%% Inputs for testing
    # repo_old = Path('~/github2/ReEDS').expanduser()
    # repo_new = Path('~/github3/ReEDS').expanduser()
    # from datetime import datetime
    # today = datetime.now().strftime('%Y%m%d')
    # outpath = Path(f'~/scratch/{today}').expanduser()
    # outpath.mkdir(exist_ok=True, parents=True)

    #%% Run it
    main(repo_old, repo_new, outpath)
