#%%### Imports
import os
import sys
import numpy as np
import pandas as pd
from tqdm import tqdm
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds


#%%### Fixed inputs
if reeds.io.hpc:
    remotepath = '/kfs2/shared-projects/reeds'
    filepaths = {
        'land': os.path.join(
            '/projects', 'rev', 'data', 'transmission', 'north_america', 'conus', 'fy25',
            'nrel_build', 'build', 'final',  'all_interconnection_costs.csv'
        ),
        'offshore_meshed': os.path.join(
            '/projects', 'rev', 'data', 'transmission', 'north_america', 'conus', 'fy25',
            'nrel_build', 'build', 'offshore', 'osw_interregional',
            'open_supply-curve_post_proc_interregional.csv',
        ),
        'offshore_radial': os.path.join(
            '/projects', 'rev', 'projects', 'weto', 'fy25', 'standard_scenarios', 'osw',
            'rev', 'aggregation', 'open', 'open_supply-curve_post_proc.csv',
        ),
        'esri_102008': os.path.join(
            '/projects', 'alcaps', 'jcarag', 'process_resource_profiles', 'rev_grid_conus_template_128.csv'
        ),
        'interzonal': os.path.join(
            '/projects', 'rev', 'data', 'transmission', 'north_america', 'conus', 'fy25',
            'nrel_build', 'build', 'offshore', 'osw_interregional', 'interregional_costs.csv',
        )
    }
else:
    remotepath = os.path.join(('/Volumes' if os.name == 'posix' else '//nrelnas01'), 'ReEDS')
    filepath_base = os.path.join(
        remotepath, 'Supply_Curve_Data', 'interconnection', '20250811',
    )
    filepaths = {
        'land': os.path.join(filepath_base, 'all_interconnection_costs.csv'),
        'offshore_meshed': os.path.join(filepath_base, 'open_supply-curve_post_proc_interregional.csv'),
        'offshore_radial': os.path.join(filepath_base, 'open_supply-curve_post_proc.csv'),
        'esri_102008': os.path.join(filepath_base, 'rev_grid_conus_template_128.csv'),
        'interzonal': os.path.join(filepath_base, 'interregional_costs_offshore.csv')
    }
## Use the new CRS whenever possible since it minimizes distortion
crs = 'EPSG:5070'
crs_old = 'ESRI:102008'
dollaryear = 2023


#%%### Shared offshore data
old2new = pd.read_csv(
    os.path.join(
        reeds.io.reeds_path, 'hourlize', 'inputs', 'resource', 'offshore_zone_names.csv',
    ),
    header=None, index_col=0,
).squeeze(1)



#%%### Shared data from ReEDS
dfmap = reeds.io.get_dfmap()

dfcounties = reeds.io.get_countymap().to_crs(crs)[['FIPS','STATE','geometry']]

inflatable = reeds.io.get_inflatable()


#%%#################################################################################
#   -- PROCEDURE 1: Create sitemap.h5 from full raster and supply-curve sites --   #
####################################################################################
#%% Get the full raster from Gabe Zuckerman 20250819
dfraster = pd.read_csv(
    filepaths['esri_102008'],
    comment='#',
    index_col='sc_point_gid',
).drop(columns=['Unnamed: 0'], errors='ignore')

## Geohydro has some weird off-grid sites so leave them out
techs = ['upv', 'wind-ons', 'wind-ofs']
#%% Get all sc_point_gid's included in all supply curves
rev_paths = pd.read_csv(
    os.path.join(reeds.io.reeds_path, 'inputs', 'supply_curve', 'rev_paths.csv')
)
rev_paths = rev_paths.loc[rev_paths.tech.isin(techs)].copy()
dictin_sc = {}
for i, row in tqdm(rev_paths.iterrows(), total=len(rev_paths)):
    dictin_sc[row.tech, row.access_case] = pd.read_csv(
        os.path.join(
            remotepath,
            'Supply_Curve_Data',
            row.sc_path,
            'reV',
            row.original_sc_file,
        ),
        usecols=['sc_point_gid','latitude','longitude']
    )
sites = sorted(pd.concat(dictin_sc).sc_point_gid.unique())
#%% Keep those points from the raster and match them to the nearest county
sitemap = (
    reeds.plots.df2gdf(dfraster.loc[sites], crs=crs)
    .sjoin_nearest(dfcounties, how='left')
    .drop(columns=['index_right', 'geometry', 'STATE'], errors='ignore')
)
## Make sure it worked
if len(sitemap) != len(sites):
    err = f"Mismatched lengths after county match: {len(sites)} before, {len(sitemap)} after"
    raise IndexError(err)
#%% Write it
dfwrite = sitemap.astype({'latitude':np.float32, 'longitude':np.float32}).copy()
## Make sure no missing values
assert (dfwrite.isnull().sum() == 0).all()
## Make sure int32 is ok for the index
assert dfwrite.index.max() <= 2**31-1
dfwrite.index = dfwrite.index.astype(np.int32)
outpath = os.path.join('/projects', 'alcaps', 'jcarag', 'process_resource_profiles', 'sitemap.h5')
if os.path.exists(outpath):
    os.remove(outpath)
reeds.io.write_to_h5(
    dfwrite.reset_index(),
    'data',
    outpath,
    attrs={'index':'sc_point_gid', 'crs':crs_old},
)
#%% Make sure it worked
assert (dfwrite == reeds.io.read_h5_groups(outpath)).all().all()
#%% Take a look
dfplot = reeds.plots.df2gdf(dfwrite, crs=crs_old)
dfplot.plot(figsize=(14,11), lw=0, marker='s', markersize=1.5)
m = dfplot.explore(color='red')
# m.save(os.path.expanduser('~/Desktop/sitemap.html'))
m.save(os.path.join('/projects','alcaps','jcarag','process_resource_profiles','sitemap.html'))



#%%### Procedure 2: Format interconnection costs into .h5 files used in ReEDS ######
#%% Get data - instead of reading in all_interconnection_costs.csv, read in one of the 
#              post_processed_supply_curves for upv/wind-ons for a given ESM and combine to 
#              get all available sc_point_gids.
#   NOTE: An assertion check confirms that once filtered for output columns...
#           - the post_processed_supply_curve files for different decades of the same ESM are identical 
#           - the post_processed_supply_curve files for the same decade of different ESMs are identical
#           - the above two bullet points are true for both upv and lbw
#         thus, we can choose any supply curve file for any ESM/year combination in the following procedures
"""
Steps:
0. Output columns = ['sc_point_gid','latitude','longitude','latitude_poi','longitude_poi',
                     'latitude_reinforcement_poi','longitude_reinforcement_poi','trans_gid',
                     'transtype','dist_spur_km','dist_reinforcement_km','cost_spur_usd_per_mw',
                     'cost_poi_usd_per_mw','cost_reinforcement_usd_per_mw','cost_total_trans_usd_per_mw'
                     ]
    
1. Load in upv supply curve and filter for output columns sans FIPS (added later)
2. Load in wind-ons supply curve and filter for output columns sans FIPS (added later)
3. Concat upv and wind-ons supply curves, using outer join to capture all possible sc_point_gid
    a. If both supply curves have same sc_point_gid, ensure data is the same
"""

outcols = {
    'sc_point_gid': np.int32,
    'latitude': np.float32,
    'longitude': np.float32,

    'latitude_poi': np.float32,
    'longitude_poi': np.float32,

    'latitude_reinforcement_poi': np.float32,
    'longitude_reinforcement_poi': np.float32,

    'trans_gid': np.int32,
    'trans_type': str,
    'FIPS': str,

    'dist_spur_km': np.float32,
    'dist_reinforcement_km': np.float32,

    'cost_spur_usd_per_mw': np.float32,
    'cost_poi_usd_per_mw': np.float32,
    'cost_reinforcement_usd_per_mw': np.float32,
    'cost_total_trans_usd_per_mw': np.float32,
}

# Arbitrarily select TaiESM 2050s as ESM/decade (see NOTE above)
dfsc_upv_in = pd.read_csv(os.path.join('/kfs2','shared-projects','reeds','Supply_Curve_Data',
                                       'UPV','2024_10_23_PACES','reV','post_processed_supply_curves','upv_01_reference_supply-curve_taiesm1_ssp245_2050.csv')
                                       )[[col for col in outcols.keys() if col != 'FIPS']]
dfsc_lbw_in = pd.read_csv(os.path.join('/kfs2','shared-projects','reeds','Supply_Curve_Data',
                                       'ONSHORE','2024_10_18_PACES','reV','lbw_taiesm1_ssp245_2050','lbw_wind_reference_supply-curve_taiesm1_ssp245_2050.csv')
                                       )[[col for col in outcols.keys() if col != 'FIPS']]
# dfsc = dfsc_upv_in.set_index('sc_point_gid').join(dfsc_lbw_in.set_index('sc_point_gid'), how='outer', lsuffix='_upv', rsuffix='_lbw').reset_index()
## Merge upv and wind sc data with outer join
# dfland = (pd.concat([dfsc_upv_in,dfsc_lbw_in])
#         .groupby(['sc_point_gid','trans_type'], as_index=False)
#         .mean()
#         .set_index('sc_point_gid')
#         )
dfland = (pd.concat([dfsc_upv_in,dfsc_lbw_in])
          .sort_values(
              by="trans_type",
              key=lambda x: x.eq("TransLine"),
              ascending=False
          ).drop_duplicates(subset='sc_point_gid', keep='first')
        .set_index('sc_point_gid')
        )
assert dfland.index.is_unique, "There are still duplicate sc_point_gid - resolve the duplicates to continue"

#%%####################
#   -- 2.1: Land --   #
#######################
print(f'Creating interconnection_land.h5...')

#%% Map location to county
dfland = reeds.plots.df2gdf(dfland, crs=crs)

dfland['FIPS'] = (
    dfland[['geometry']]
    .sjoin_nearest(dfcounties[['FIPS','geometry']], how='left')
    .FIPS
)
assert dfland.FIPS.isnull().sum() == 0

#%% Format it
drop = ['export', 'lcoe', 'lcot', 'offshore', 'geometry']
dfland = dfland.drop(columns=[i for i in dfland if any([c in i for c in drop])]).reset_index()

_diff = len(outcols) - dfland.shape[1]
assert _diff == 0, _diff

dfland = dfland[list(outcols.keys())].astype(outcols)
dfland = dfland.sort_values(by='sc_point_gid')

#%% Write it
drop = ['trans_gid', 'trans_type']
drop = []
landpath = os.path.join(reeds.io.reeds_path, 'inputs', 'supply_curve', 'interconnection_land.h5')
if os.path.exists(landpath):
    os.remove(landpath)
reeds.io.write_to_h5(
    dfland.drop(columns=drop),
    key='data',
    filepath=landpath,
    overwrite=True,
    compression_opts=4,
    attrs={'index':'sc_point_gid', 'crs':crs, 'dollaryear':dollaryear},
)


#%%########################
#   -- 2.2: Offshore --   #
###########################
# # Map POI to county
# dfradial = reeds.plots.df2gdf(
#     dictin['offshore_radial'],
#     lat='latitude_poi',
#     lon='longitude_poi',
#     crs=crs,
# ).copy()

# Arbitrarily select TaiESM 2050s as ESM/decade (see NOTE above)
dfsc_osw_in = pd.read_csv(os.path.join('/kfs2','shared-projects','reeds','Supply_Curve_Data',
                                       'OFFSHORE','2024_10_18_PACES','reV','osw_taiesm1_ssp245_2050',
                                       'osw_reference_supply-curve_post_proc_taiesm1_ssp245_2050.csv'),
                          index_col='sc_point_gid',
                        )
# Map POI to county
dfradial = reeds.plots.df2gdf(
    dfsc_osw_in,
    lat='latitude_poi',
    lon='longitude_poi',
    crs=crs,
).copy()

scpointgid2fips = (
    dfradial[['geometry']]
    .sjoin_nearest(dfcounties[['FIPS','geometry']], how='left')
    .FIPS
)

#%% Add FIPS to radial
# dictin['offshore_radial']['FIPS'] = dictin['offshore_radial'].index.map(scpointgid2fips)

dfsc_osw = dfsc_osw_in.copy()
dfsc_osw['FIPS'] = dfsc_osw.index.map(scpointgid2fips)

#%% These combine columns that are filled for one and empty for the other.
### Keep the radial version since it's uniformly the one with more values.
columns_same = [
    'latitude',
    'longitude',

    # 'node_latitude',
    # 'node_longitude',

    'latitude_poi',
    'longitude_poi',

    'latitude_reinforcement_poi',
    'longitude_reinforcement_poi',

    'trans_gid',
    'FIPS',

    'dist_spur_km',
    'dist_reinforcement_km',

    'cost_spur_usd_per_mw',
    'cost_poi_usd_per_mw',
    'cost_reinforcement_usd_per_mw',
]

columns_different = [
    'dist_export_km',

    'cost_export_usd_per_mw',
    'cost_total_trans_usd_per_mw',
]

columns_meshed = {'Zone_ReEDS':'ba'}

#%% Make combined dataframe
# dfwrite = dictin['offshore_radial'][columns_same].copy()
# for col in columns_different:
#     for offshoretype in ['radial', 'meshed']:
#         dfwrite[f'{col}|{offshoretype}'] = dictin[f'offshore_{offshoretype}'][col]

dfwrite = dfsc_osw[columns_same].copy()
for col in columns_different:
    for offshoretype in ['radial']:
        dfwrite[f'{col}|{offshoretype}'] = dfsc_osw[col]

# for col, name in columns_meshed.items():
#     dfwrite[name] = dictin['offshore_meshed'][col].map(lambda x: old2new.get(x,x))
# 
# ## Flag the sites that are always radial
# dfwrite['always_radial'] = (~dictin['offshore_meshed']['dist_spur_km'].isnull()).astype(int)

## Flag the sites that are always radial (create 'always_radial' column, as its expected in outputs)
dfwrite['always_radial'] = 1

# ## For always-radial sites, get the zone from the FIPS (which comes from the POI via
# ## scpointgid2fips) instead of from Zone_ReEDS
# county2zone = reeds.io.get_county2zone()
# dfwrite.loc[dfwrite.always_radial == 1, 'ba'] = (
#     dfwrite.loc[dfwrite.always_radial == 1, 'FIPS'].map(county2zone)
# )

county2zone = reeds.io.get_county2zone()
# Since all rows have "always_radial==1", we can simply create the 'ba' column using the county2zone
dfwrite['ba'] = dfwrite.loc[:, 'FIPS'].map(county2zone)

#%% Change types to 32-bit whenever possible
assert (
    dfwrite[[c for c in dfwrite if isinstance(dfwrite.dtypes[c], int)]].max() < 2**31-1
).all()
dfwrite_h5 = dfwrite.reset_index()
for col in dfwrite_h5:
    if dfwrite_h5[col].dtype == np.float64:
        dfwrite_h5 = dfwrite_h5.astype({col: np.float32})
    elif col == 'always_radial':
        dfwrite_h5 = dfwrite_h5.astype({col: bool})
    elif dfwrite_h5[col].dtype == np.int64:
        dfwrite_h5 = dfwrite_h5.astype({col: np.int32})

print(dfwrite_h5.dtypes)

print(' - Saving interconnection_offshore.h5...')
#%% Write it
offshorepath = os.path.join(reeds.io.reeds_path, 'inputs', 'supply_curve', 'interconnection_offshore.h5')
if os.path.exists(offshorepath):
    os.remove(offshorepath)
reeds.io.write_to_h5(
    dfwrite_h5,
    key='data',
    filepath=offshorepath,
    overwrite=True,
    compression_opts=4,
    attrs={'index':'sc_point_gid', 'crs':crs, 'dollaryear':dollaryear},
)


breakpoint()
#%%### Procedure 3: Offshore interzonal transmission costs and distances
### Get the raw data (in $2023, confirmed with Gabe 20250902)
dftrans = pd.read_csv(filepaths['interzonal']).rename(columns={'start':'r', 'end':'rr'})
for col in ['r', 'rr']:
    dftrans[col] = dftrans[col].map(lambda x: old2new.get(x,x))

## Add the other direction
dftrans_reverse = dftrans.copy()
dftrans_reverse.r, dftrans_reverse.rr = dftrans_reverse.rr, dftrans_reverse.r

dftrans = pd.concat([dftrans, dftrans_reverse], ignore_index=True)
assert len(dftrans) == len(dftrans.drop_duplicates(subset=['r','rr']))
dftrans = dftrans.drop_duplicates(subset=['r','rr'])

## Convert km to miles
dftrans['length_miles'] = dftrans['length_km'] / 1.60934

## Convert $2023 to $2004
dftrans['USD2004perMW'] = dftrans['total_cost_mw'] * inflatable[2023, 2004]

## Append to land transmission costs
fpath_in = os.path.join(
    reeds.io.reeds_path, 'inputs', 'transmission', 'transmission_distance_cost_500kVdc_ba.csv'
)
dftrans_in = pd.read_csv(fpath_in)
## TEMPORARILY drop the old costs (could break after we switch to non-p{num} zone names)
dftrans_in = dftrans_in.loc[
    ~(dftrans_in.r.str.startswith('o') | dftrans_in.rr.str.startswith('o'))
].copy()

dftrans_out = pd.concat(
    [dftrans_in, dftrans[['r', 'rr', 'length_miles', 'USD2004perMW']]],
    ignore_index=True,
)

## Write it
dftrans_out.round(2).to_csv(fpath_in, index=False)
