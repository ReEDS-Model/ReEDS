#%% ===========================================================================
### --- IMPORTS ---
### ===========================================================================
import os
import sys
import datetime
import numpy as np
import pandas as pd
import geopandas as gpd
import argparse

# Local Imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(os.path.realpath(__file__)),'..','..')))
import reeds

#%% ===========================================================================
### --- General Read Functions---
### ===========================================================================
def assign_gids_to_unitdata(df, offland_gdf, land_gdf):
    '''
    Function to merge NEMS unitdata with interconnection_land/offshore data by 
    mapping each unit in NEMS by lon/lat to its closest sc_point_gid
    '''

    offland_gdf['sc_point_gid'] = offland_gdf.index
    land_gdf['sc_point_gid'] = land_gdf.index

    # Technologies to map - pv, wind, and geothermal
    tech_match = {'upv': ['upv','dupv','pvb_pv','csp-wp','csp-ns'],
                  'wind-ons': ['wind-ons'], 
                  'wind-ofs': ['wind-ofs'],
                  'geohydro': ['geohydro_allkm', 'geothermal'],
                  'egs':['egs']}
    
    df_rev_list = []
    for tech in ['upv','wind-ons','wind-ofs','geohydro']:
        print(f'Assigning {tech} classes')
        tech_sub = tech_match[tech]

        df_sub = df[df.tech.isin(tech_sub)]
        # Read supply curves
        if tech == 'geohydro':
            # Use egs supply curve for geohydro for now
            geo_tech = 'egs'
            supply_curve = pd.read_csv(os.path.join(inputs_case,'supplycurve_'+geo_tech+'.csv'))
        else:
            supply_curve = pd.read_csv(os.path.join(inputs_case,'supplycurve_'+tech+'.csv'))

        # Only consider the sc_point_pids that are in supply curves
        # (to avoid unmatched units later)
        if tech == 'wind-ofs':
            sc_point_pid_pdf = offland_gdf[offland_gdf['sc_point_gid'].isin(supply_curve['sc_point_gid'].to_list())]
        else:
            sc_point_pid_pdf = land_gdf[land_gdf['sc_point_gid'].isin(supply_curve['sc_point_gid'].to_list())]
        
        sc_point_pid_pdf = sc_point_pid_pdf.rename(columns={'FIPS':'FIPS_nearest',
                                                            'latitude':'T_LAT_nearest',
                                                            'longitude':'T_LONG_nearest'})
        sc_point_pid_pdf['FIPS_nearest'] = 'p' + sc_point_pid_pdf['FIPS_nearest']
        
        gdf_joined = gpd.sjoin_nearest(df_sub, sc_point_pid_pdf, distance_col='distance', how='left')
        # Replace lon/lat and FIPS with the ones closest to them with resources
        gdf_joined['T_LONG'] = gdf_joined['T_LONG_nearest']
        gdf_joined['T_LAT'] = gdf_joined['T_LAT_nearest']
        gdf_joined['FIPS'] = gdf_joined['FIPS_nearest']

        # Update ba since FIPS have been updated
        df_county = pd.read_csv(os.path.join(inputs_case,'county2zone.csv'))
        df_county = df_county[['FIPS','ba']]
        df_county['FIPS'] = 'p' + df_county['FIPS'].astype(str)
        df_county = df_county.rename(columns={'ba':'reeds_ba_nearest'})

        gdf_joined = gdf_joined.merge(df_county, on='FIPS', how='left')
        gdf_joined['reeds_ba'] = gdf_joined['reeds_ba_nearest']

        # Merge unit database with VRE supply curves to assign AC capacity factors to VRE units
        # and mean resource temp for geothermal units
        df_rev = gdf_joined[['sc_point_gid'] + df.drop(columns=['geometry']).columns.to_list()]

        if len(df_rev) > 0:
            df_rev.loc[:, ['sc_point_gid']] = df_rev.loc[:, ['sc_point_gid']].fillna(0).astype(np.int64)
            if (tech == 'geohydro') or (tech == 'egs'):
                df_rev = df_rev.merge(supply_curve[['sc_point_gid','mean_resource_temp']],
                                        on='sc_point_gid',
                                        how='left').rename(columns={'mean_resource_temp':'reV_mean_resource_temp'})
            else:
                df_rev = df_rev.merge(supply_curve[['sc_point_gid','cf']],
                                        on='sc_point_gid',
                                        how='left').rename(columns={'cf':'reV_capacity_factor_ac'})
            df_rev_list = df_rev_list + [df_rev]

    df_rev = pd.concat(df_rev_list, ignore_index=False, sort=False)
    return df_rev

#%% ===========================================================================
### --- PROCEDURE ---
### ===========================================================================
def main(inputs_case):

    # Read unitdata
    unitdata = pd.read_csv(os.path.join(inputs_case, 'unitdata_orig.csv'))
    unitdata = unitdata.rename(columns={'r':'reeds_ba'})
    
    ## Assign sc_point_gids and pv, wind capacity factors, and geothermal resource temperature to NEMS unit
    # Using 'EPSG:5070' projection for nearest distance calculation
    crs = 'EPSG:5070'
    # Convert NEMS data base to geopandas dataframe by lon/lat
    unitdata = reeds.plots.df2gdf(
        unitdata,
        lat='T_LAT',
        lon='T_LONG',
        crs=crs)
    
    unitdata['temp_id'] = unitdata.index
    
    # Assign sc_point_gids to units based on distance
    land_gdf = reeds.io.get_sitemap(crs=crs)
    offland_gdf = reeds.io.get_sitemap(offshore=True, crs=crs)
    
    # Merge NEMS unitdata with interconnection_land/offshore data by 
    # mapping each unit in NEMS by lon/lat to its closest sc_point_gid  
    df_rev = assign_gids_to_unitdata(unitdata, offland_gdf, land_gdf)
        
    # Clean up merged data
    unitdata = unitdata.rename(columns={'FIPS':'FIPS_org',
                                        'T_LONG':'T_LONG_org',
                                        'T_LAT':'T_LAT_org',
                                        'reeds_ba':'reeds_ba_org'})   
    if 'reV_mean_resource_temp' in df_rev.columns:
        unitdata = unitdata.merge(df_rev[['sc_point_gid','temp_id',
                                          'reV_capacity_factor_ac',
                                          'reV_mean_resource_temp',
                                          'T_LONG','T_LAT','FIPS',
                                          'reeds_ba']],
                                          on = 'temp_id',how = 'left') 
    else:
        unitdata = unitdata.merge(df_rev[['sc_point_gid','temp_id',
                                          'reV_capacity_factor_ac',
                                          'T_LONG','T_LAT','FIPS',
                                          'reeds_ba']],
                                          on = 'temp_id',how = 'left') 
    
    unitdata['FIPS'] = unitdata['FIPS'].fillna(unitdata['FIPS_org'])
    unitdata['T_LONG'] = unitdata['T_LONG'].fillna(unitdata['T_LONG_org'])
    unitdata['T_LAT'] = unitdata['T_LAT'].fillna(unitdata['T_LAT_org'])
    unitdata['reeds_ba'] = unitdata['reeds_ba'].fillna(unitdata['reeds_ba_org'])

    # Rearrange column orders
    cols = df_rev.columns.to_list()
    unitdata = unitdata[cols].drop(columns=['temp_id'])
    unitdata = unitdata.rename(columns={'reeds_ba':'r'})
    
    # Save processed unitdata
    unitdata.to_csv(os.path.join(inputs_case,'unitdata.csv'),index=False)

if __name__ == '__main__':
    ### Time the operation of this script
    tic = datetime.datetime.now()
    
    ### Parse arguments
    parser = argparse.ArgumentParser(description="""This file processes NEMS unitdata""")
    parser.add_argument('reeds_path', help="ReEDS directory")
    parser.add_argument('inputs_case', help="path to runs/{case}/inputs_case")

    args = parser.parse_args()
    reeds_path = args.reeds_path
    inputs_case = args.inputs_case
    
    # for testing
    # reeds_path = reeds.io.reeds_path
    # inputs_case = os.path.join(reeds_path,'runs','test_Pacific','inputs_case')

    #%% Set up logger
    log = reeds.log.makelog(
        scriptname=__file__,
        logpath=os.path.join(inputs_case,'..','gamslog.txt'),
    )
    print('Starting process_unitdata.py')
    main(inputs_case)
    print('Complete processsing process_unitdata.py')
