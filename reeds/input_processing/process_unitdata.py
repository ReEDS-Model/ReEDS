#%% ===========================================================================
### --- IMPORTS ---
### ===========================================================================
import os
import sys
import datetime
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
    Merge NEMS unitdata with interconnection_land/offshore data by 
    mapping each unit in NEMS by lon/lat to its closest sc_point_gid
    '''

    offland_gdf['gid'] = offland_gdf.index
    land_gdf['gid'] = land_gdf.index

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

        # Only consider the sc_point_gids that are in supply curves
        # (to avoid unmatched units later)
        if tech == 'wind-ofs':
            sc_point_gid_gdf = offland_gdf[offland_gdf['gid'].isin(supply_curve['sc_point_gid'].to_list())]
        else:
            sc_point_gid_gdf = land_gdf[land_gdf['gid'].isin(supply_curve['sc_point_gid'].to_list())]
        # Rename FIPS and lon/lat as nearest FIPS and lon/lat #
        # as after matching them to units in unitdata by distance later 
        # these FIPS and lon/lat are the nearest ones to these units 
        # and not the FIPS and lon/lat these units are located at  
        sc_point_gid_gdf = sc_point_gid_gdf.rename(columns={'FIPS':'FIPS_nearest',
                                                            'latitude':'T_LAT_nearest',
                                                            'longitude':'T_LONG_nearest'})
        sc_point_gid_gdf['FIPS_nearest'] = 'p' + sc_point_gid_gdf['FIPS_nearest']
        
        gdf_joined = gpd.sjoin_nearest(df_sub, sc_point_gid_gdf, distance_col='distance', how='left')
        # Replace lon/lat and FIPS with the ones closest to them with resources
        # (This is to make sure all units are matched to available resources 
        # and their associated FIPS and lon/lat are those of the resources 
        # they are matched to, and not necessarily their actual physical locations) 
        gdf_joined['T_LONG'] = gdf_joined['T_LONG_nearest']
        gdf_joined['T_LAT'] = gdf_joined['T_LAT_nearest']
        gdf_joined['FIPS'] = gdf_joined['FIPS_nearest']

        # Update ReEDS region (r) since FIPS have been updated to FIPS_nearest
        # Load FIPS-r mapping
        sw = reeds.io.get_switches(inputs_case)
        county2zone = reeds.io.get_county2zone(GSw_ZoneSet=sw['GSw_ZoneSet'], as_map=False)
        county2zone['FIPS'] = 'p' + county2zone.FIPS
        county2zone = county2zone[['FIPS','r']]
        # Convert r into r_nearest as these are the regions
        # matched with FIPS_nearest of units in unitdata
        county2zone = county2zone.rename(columns={'r':'r_nearest'})

        gdf_joined = gdf_joined.merge(county2zone, on='FIPS', how='left')
        # Assign units' regions as regions with resources they are matched to
        gdf_joined['r'] = gdf_joined['r_nearest']

        # Merge unit database with VRE supply curves to assign AC capacity factors to VRE units
        # and mean resource temp for geothermal units
        df_rev = gdf_joined[['sc_point_gid'] + df.drop(columns=['geometry']).columns.to_list()]

        if len(df_rev) > 0:
            df_rev.loc[:, ['sc_point_gid']] = df_rev.loc[:, ['sc_point_gid']].fillna(0)
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
    
    ## Assign sc_point_gids and pv, wind capacity factors, and geothermal resource temperature to NEMS unit
    # Using 'EPSG:5070' projection for nearest distance calculation
    crs = 'EPSG:5070'
    # Convert unitdata to geopandas dataframe by lon/lat
    unitdata = reeds.plots.df2gdf(
        unitdata,
        lat='T_LAT',
        lon='T_LONG',
        crs=crs)
    
    unitdata['temp_id'] = unitdata.index
    
    # Assign sc_point_gids to units based on distance using interconnection_land/offshore data
    land_gdf = reeds.io.get_sitemap(crs=crs)
    offland_gdf = reeds.io.get_sitemap(offshore=True, crs=crs)
    
    # Merge NEMS unitdata with interconnection_land/offshore data by 
    # mapping each unit in NEMS by lon/lat to its closest sc_point_gid  
    df_rev = assign_gids_to_unitdata(unitdata, offland_gdf, land_gdf)
        
    # Clean up merged data
    # Keep the original FIPS, r, and lon/lat data to separate them 
    # from the FIPS, r, and lon/lat (which are the nearest ones) 
    # in df_rev which will be merged in
    unitdata = unitdata.rename(columns={'FIPS':'FIPS_orig',
                                        'T_LONG':'T_LONG_orig',
                                        'T_LAT':'T_LAT_orig',
                                        'r':'r_orig'})   
    if 'reV_mean_resource_temp' in df_rev.columns:
        unitdata = unitdata.merge(df_rev[['sc_point_gid','temp_id',
                                          'reV_capacity_factor_ac',
                                          'reV_mean_resource_temp',
                                          'T_LONG','T_LAT','FIPS',
                                          'r']],
                                          on = 'temp_id',how = 'left') 
    else:
        unitdata = unitdata.merge(df_rev[['sc_point_gid','temp_id',
                                          'reV_capacity_factor_ac',
                                          'T_LONG','T_LAT','FIPS',
                                          'r']],
                                          on = 'temp_id',how = 'left') 
    
    # Return original FIPS, r, and lon/lat to non rsc (pv, wind) and 
    # non-geothermal units since these units are not assigned to nearest 
    # FIPS, r, and lon/lat with resources
    unitdata['FIPS'] = unitdata['FIPS'].fillna(unitdata['FIPS_orig'])
    unitdata['T_LONG'] = unitdata['T_LONG'].fillna(unitdata['T_LONG_orig'])
    unitdata['T_LAT'] = unitdata['T_LAT'].fillna(unitdata['T_LAT_orig'])
    unitdata['r'] = unitdata['r'].fillna(unitdata['r_orig'])

    # Rearrange column orders
    cols = df_rev.columns.to_list()
    unitdata = unitdata[cols].drop(columns=['temp_id'])
    # Make sure sc_point_gid is saved as integer
    unitdata['sc_point_gid'] = unitdata['sc_point_gid'].astype('Int64')
    
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
    #reeds_path = reeds.io.reeds_path
    #inputs_case = os.path.join(reeds_path,'runs','test_Pacific','inputs_case')

    #%% Set up logger
    log = reeds.log.makelog(
        scriptname=__file__,
        logpath=os.path.join(inputs_case,'..','gamslog.txt'),
    )
    print('Starting process_unitdata.py')
    main(inputs_case)
    print('Finished process_unitdata.py')
