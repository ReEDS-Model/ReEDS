#%%### Imports
import os
import sys
import pandas as pd
import geopandas as gpd
from tqdm import tqdm
import time
import datetime
from lxml import etree as ET
import shutil
pd.options.display.max_rows = 20
pd.options.display.max_columns = 200

import warnings
warnings.filterwarnings("ignore")

### Local imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
import reeds
from reeds import plots
plots.plotparams()


#%%### GENERAL FUNCTIONS

# produce Scenarios.csv
def create_scenarios_csv(output_dir,cases):

    # the csv that reads in the filepaths cannot have quoted values per report_utils, Line 111
    # so read in the extra user specified data that gets this formatted nicely
    scenarios = pd.read_csv(os.path.join(reeds_path,'postprocessing','tableau','scenarios.csv'))

    # the original cases file the user specified, with renamed columns for Tableau
    cases_df = pd.DataFrame([{'machine_readable_scenario_name': key, 'filepath': value} for key, value in cases.items()])

    # merge them together 
    df = pd.merge(scenarios,cases_df,left_on='machine_readable_scenario_name',right_on='machine_readable_scenario_name',how='right')

    missing_scenarios_set = set(cases_df['machine_readable_scenario_name']) - set(scenarios['machine_readable_scenario_name'])
    missing_scenarios = [*missing_scenarios_set]

    # if Scenarios.csv is not populated for the desired scenarios, automatically create it
    if missing_scenarios:
        print(f'Scenarios.csv is missing some scenarios that are present in your cases file: {missing_scenarios}.')
        print('Automatically creating Scenarios.csv from the switch values for those runs.')

        for scenario in missing_scenarios:
            sw = reeds.io.get_switches(cases[scenario])

            # Assign a Transmission Representation
            if sw.GSw_TransCostMult == 1 and sw.GSw_TransRestrict == 'country':
                df.loc[df['machine_readable_scenario_name'] == scenario, 'Transmission Framework'] = 'Default'
            elif sw.GSw_TransCostMult == 1 and sw.GSw_TransRestrict != 'country':
                df.loc[df['machine_readable_scenario_name'] == scenario, 'Transmission Framework'] = f'Interregional Transmission Restriction: {sw.GSw_TransRestrict}'
            elif sw.GSw_TransCostMult != 1 and sw.GSw_TransRestrict == 'country':
                df.loc[df['machine_readable_scenario_name'] == scenario, 'Transmission Framework'] = f'{sw.GSw_TransCostMult}x Transmission Cost Multiplier' 
            else:  
                df.loc[df['machine_readable_scenario_name'] == scenario, 'Transmission Framework'] = f'{sw.GSw_TransCostMult}x Transmission Cost Multiplier' 
            
            # Assign a Load Profile
            try:
                df.loc[df['machine_readable_scenario_name'] == scenario, 'Demand'] = sw.GSw_LoadProfiles
            except Exception:
                df.loc[df['machine_readable_scenario_name'] == scenario, 'Demand'] = sw.GSw_EFS1_AllYearLoad
            
            # Assign a Policy
            if int(sw.GSw_AnnualCap) != 0:
                df.loc[df['machine_readable_scenario_name'] == scenario, 'Policy'] = f'co2_cap_{sw.GSw_AnnualCapScen}'
            else: 
                df.loc[df['machine_readable_scenario_name'] == scenario, 'Policy'] = f'incentives_{sw.incentives_suffix}'
                 
            # Assign a Sensitivity and Scenario Name         
            df.loc[df['machine_readable_scenario_name'] == scenario, 'Sensitivity'] = scenario
            df.loc[df['machine_readable_scenario_name'] == scenario, 'Scenario Name'] = scenario

    # If it is still not fully populated, break 
    if df.isnull().values.any():
        missing_scenarios = df[df.isnull().any(axis=1)]['machine_readable_scenario_name'].tolist()
        raise ValueError(f'We could not automatically populate all of the necessary columns in Scenarios.csv for the following scenarios: {missing_scenarios}. Please populate these scenarios in Scenarios.csv and re-run the script.')
  
    # make sure 'Scenario Name' comes last and 'filepath' and 'machine_readable_scenario_name' come first - the middle columns will vary based on the study
    cols_always_first = ['filepath','machine_readable_scenario_name','Transmission Framework','Demand','Policy','Sensitivity','Scenario Name']
    cols_remaining = [col for col in df.columns if col not in cols_always_first]
    df = df[cols_always_first + cols_remaining]

    df.to_csv(os.path.join(output_dir,'Scenarios.csv'),index=False)
    return df

# produce the hierarchy file that Tableau needs for the spatial aggregation
def produce_hierarchy_file(output_dir,basecase):
    
    hierarchy = reeds.io.get_hierarchy(cases[basecase])
    sw = reeds.io.get_switches(cases[basecase])

    # hierarchy.csv has machine readable names - convert them to values from level_map
    for col in hierarchy.columns:
        if col in level_map:
            hierarchy = hierarchy.rename(columns={col:level_map[col]})

    # clean up region names, ex. turn 'NorthernGrid_West' to 'NorthernGrid West', replace all instances of '_' with ' ' in the entire dataframe
    hierarchy = hierarchy.replace('_',' ',regex=True)

    if sw.GSw_RegionResolution == "county" or sw.GSw_RegionResolution == "mixed":
        # county2zone has the county FIPS to ReEDS BA mapping
        county2zone = pd.read_csv(os.path.join(reeds_path, 'inputs', 'county2zone.csv'), dtype={'FIPS':str},)
        county2zone['Region'] = 'p' + county2zone.FIPS
        # Add BA info to hierarchy
        hierarchy = hierarchy.merge(county2zone.drop(columns=['state']), left_on='r', right_on='Region')
        # move the FIPS column to be the first column in the df
        hierarchy = hierarchy[['Region'] + [col for col in hierarchy.columns if col != 'Region']]
        # export
        hierarchy.to_csv(os.path.join(output_dir,'shapefiles','hierarchy.csv'),index=False)
    elif sw.GSw_RegionResolution == 'aggreg' or sw.GSw_RegionResolution == 'ba':
        # add columns to match the county-level hierarchy.csv format
        hierarchy = hierarchy.reset_index()
        hierarchy['ba'] = hierarchy['r']
        hierarchy = hierarchy.rename(columns={'r':'Region'})
        hierarchy['FIPS'] = '' # add a blank FIPS column so that the hierarchy.csv has the same columns as when using county-level runs
        hierarchy['county_name'] = '' # add a blank county_name column so that the hierarchy.csv has the same columns as when using county-level runs
        # then hierarchy.csv is already ready to export 
        hierarchy.to_csv(os.path.join(output_dir,'shapefiles','hierarchy.csv'),index=False)
    else:
        print('All levels must be either county or ba now, all aggregation will be done via a hierarchy mapping.')
        pass
    
    return

# produce the US_PCA.shp, with OSW zones added
def produce_shapefiles():

    try:
        for x in ['US_PCA']:
            os.mkdir(os.path.join(output_dir,'shapefiles',x))
            # read in the source file and check its columns
            dst_file  = os.path.join(output_dir,'shapefiles',x,f'{x}.shp')
            # Read the shapefile
            gdf = reeds.io.get_zonemap(cases[basecase])
            # rename for join in Tableau
            # Column names we need: ['OBJECTID_1', 'rb', 'st', 'rto', 'interconne', 'country', 'custreg', 'geometry']
            # ['geometry', 'node_longitude', 'node_latitude', 'x', 'y', 'offshore', 'centroid_x', 'centroid_y', 'km2', 'aggreg', 'nercr', 'transreg',  'transgrp', 'cendiv', 'st', 'interconnect', 'country', 'usda_region', 'h2ptcreg', 'hurdlereg'],
            gdf = gdf.reset_index()[['index', 'geometry', 'st', 'interconnect', 'country']].rename(columns={'index':'rb', 'interconnect':'interconne'})
            
            # fill in blank columns needed for Tableau join if they are not in the gdf but are in US_PCA shapefile``
            for x in ['OBJECTID_1','custreg','rto']:
                gdf[x]=''

            gdf.to_file(dst_file)

    except Exception as error:
        print(error)
    return

def produce_transmission_endpoints():

    os.mkdir(os.path.join(output_dir,'shapefiles','transmission_endpoints'))
    
    try:
        if dictin_sw[basecase].GSw_RegionResolution == "county" or dictin_sw[basecase].GSw_RegionResolution == "mixed":
            
            src_file  = os.path.join(reeds_path,'inputs','shapefiles','US_COUNTY_2022','US_COUNTY_2022.shp')
            dst_file  = os.path.join(output_dir,'shapefiles','transmission_endpoints','transmission_endpoints.shp')

            # Read the shapefile
            gdf = gpd.read_file(src_file)

            # Compute centroids
            gdf['geometry'] = gdf.geometry.centroid

            # add 'BA' column to this shapefile, needed for the Tableau join
            # county2zone has the county FIPS to ReEDS BA mapping, must be the mapping from the ReEDS repo not inputs_case (which does not have all regions if not running nationally)
            county2zone = pd.read_csv(os.path.join(reeds_path,'inputs','county2zone.csv'), dtype={'FIPS':str},index_col='FIPS').squeeze(1)

            gdf['BA'] = gdf['FIPS'].map(lambda x: county2zone['ba'][x])

            # rename for join in Tableau
            gdf = gdf.rename(columns={'rb':'Region'})

            # Export to shapefile
            gdf.to_file(dst_file)
        else:
            src_file  = os.path.join(reeds_path,'inputs','shapefiles','transmission_endpoints','transmission_endpoints.shp')
            dst_file  = os.path.join(output_dir,'shapefiles','transmission_endpoints','transmission_endpoints.shp')

            gdf = reeds.io.get_zonemap(cases[basecase]).reset_index().rename(columns={'index':'Region',
                                                                                    'country':'COUNTRY',
                                                                                    'st':'STATE',})
            # columns we have: ['geometry', 'node_longitude', 'node_latitude', 'x', 'y', 'offshore', 'centroid_x', 'centroid_y', 'km2', 'aggreg', 'nercr', 'transreg', 'transgrp', 'cendiv', 'st', 'interconnect', 'country', 'usda_region', 'h2ptcreg', 'hurdlereg'],
            # columns we need: ['Region', 'FIPS', 'NAME', 'NAMELSAD', 'COUNTYFP', 'STATE', 'STCODE', 'STATEFP', 'COUNTRY', 'BA', 'geometry']
            gdf['geometry'] = gpd.points_from_xy(gdf['x'], gdf['y'])
            gdf['BA'] = gdf['Region']

            # only keep columns needed for Tableau join
            keep_cols = ['Region','STATE','COUNTRY','BA','geometry']
            gdf = gdf[keep_cols]

            # add blank columns (ideally these would be populated correctly or removed but they are not used in the merge)
            for col in ['FIPS', 'NAME', 'NAMELSAD', 'COUNTYFP', 'STATE', 'STCODE', 'STATEFP', 'COUNTRY']:
                # if that column is not in the gdf, add it as a blank column
                if col not in gdf.columns:
                    gdf[col] = ''

            gdf.to_file(dst_file)
    except Exception as error:
        print(error)

    return

# produce the Prefences.tps file that Tableau reads in for its color palettes
def produce_preferences_file(tableau_path,dictin_color,overwrite=True):
    # note: on Kestrel, Tableau is not installed so there will not be a Preferences.tps file
    try:
        file_path = os.path.join(tableau_path,'Preferences.tps')
        
        # loop through every color palette and add it to the Preferences.tps file
        for key in dictin_color.keys():

            # Define the new palettes
            new_palette_name = f"{key} Color Palette"
            hex_colors = dictin_color.get(key)

            # Call the function
            add_custom_palette(file_path, new_palette_name, hex_colors, overwrite)
    except Exception as error:
        print(error)
        pass

    return

def add_custom_palette(file_path, palette_name, color_list, overwrite):
    """
    Adds a custom color palette to a Tableau Preferences.tps file.
    """
    # If the Prefences.tps file has not already been created, create a new one with a basic structure
    file_path = os.path.join(output_dir, 'Preferences.tps')
    if not os.path.exists(file_path):
        root = ET.Element('workbook')
        tree = ET.ElementTree(root)
    else:
        # if file_path does exist, parse the existing file
        tree = ET.parse(file_path)
        root = tree.getroot()

    # Add a <preferences> tag if it doesn't exist
    preferences_tag = root.find('preferences')
    if preferences_tag is None:
        preferences_tag = ET.SubElement(root, 'preferences')
    
    color_palette = ET.SubElement(preferences_tag, 'color-palette')
    color_palette.set('name', palette_name)
    color_palette.set('type', 'regular')
    ET.indent(tree, '  ') 

    for color_hex in color_list:
        color = ET.SubElement(color_palette, 'color')
        # add spacing so that the <color>#5e1688</color> parts are not all on one line, making it difficult to read
        ET.indent(tree, '  ')
        color.text = color_hex

    # Write the modified XML back to the file with proper formatting
    tree.write(file_path, encoding='utf-8', xml_declaration=True, pretty_print=True)
    return

# format the csvs for ease of unioning the data in Tableau 
def reformat(df,case,metric,years):

    sw = reeds.io.get_switches(cases[case])

    if df.empty:
        print(f'{case} {metric} df is empty, returning empty dataframe.')
        pass

    else:

        # keep desired range of years
        if 't' in df.columns:
            df = df.loc[(df.t >= min(years)) & (df.t <= max(years))] 

        # add scenario column
        df.loc[:,'Scenario'] = case

        if 'Transmission' in metric:        
            hierarchy = reeds.io.get_hierarchy(cases[case])

            # reformat tranmission type to desired display names
            df.trtype = df.trtype.str.lower().map(lambda x: output_formatting['trtype_map'].get(x,x))

            ## rename columns
            df['Region Begin'] = df['r']
            df['Region End'] = df['rr']
            del df['rr']
            df['Transmission Planning Subregion Begin'] = df['Region Begin'].map(hierarchy[trans_level]).str.replace('_',' ')
            df['Transmission Planning Subregion End'] = df['Region End'].map(hierarchy[trans_level]).str.replace('_',' ')
                    
            if trans_level == 'transgrp':
                df['Transmission Planning Subregion End'] = df['Transmission Planning Subregion End'].str.replace("_"," ") # turn NorthernGrid_West to 'NorthernGrid West'
                df['Transmission Planning Subregion Begin'] = df['Transmission Planning Subregion Begin'].str.replace("_"," ")

        if sw.GSw_RegionResolution == "county":
            # the 'r' column already has the 'p41003' format
            df = df.rename(columns={'r':'County'})
            # add a column with the FIPS code (remove the 'p' prefix and turn the value into a integer from the CountyName column)
            df['FIPS'] = df['County'].str.replace('p','').astype(int)

            # now need to aggregate up to BA level, county2zone has the county FIPS to ReEDS BA mapping
            county2zone = pd.read_csv(os.path.join(cases[case], 'inputs_case', 'county2zone.csv'), dtype={'FIPS':int},index_col='FIPS').squeeze(1)

            # aggregate up to BA level using the hierarchy mapping
            df['BA'] = df['FIPS'].map(lambda x: county2zone['ba'][x])
            del df['FIPS']
        elif sw.GSw_RegionResolution == 'aggreg' or sw.GSw_RegionResolution == 'ba':
            # the 'r' column already has the 'p4' BA format
            df = df.rename(columns={'r':'BA'})
            # make the county column blank as it will not be used when we are using BA-level runs
            df['County']=''
        else:
            print('All levels must be either county or ba now, all aggregation will be done via a hierarchy mapping.')
            pass

        # add a column named 'Metric' which helps in the Tableau union
        df.loc[:,'Metric'] = metric

        # Rename columns to match the expected format
        df = df.rename(columns={metric:'Value',
                                'i':'Technology',
                                'tech':'Technology',
                                'rb':'BA',
                                'r':'BA',
                                'region':'BA',
                                't':'Year',
                                'year':'Year',
                                'e':'Pollutant',
                                'trtype':'Transmission Type',
                                'cost_cat':'Cost Category',
                                'scenario':'Scenario'})
        
        if metric == 'Emissions (million metric tonnes)':
            df = df.loc[:,['Metric','Scenario','County','BA','Pollutant','Year','Value']]
        elif metric == 'Coincident Peak End-Use Electricity Demand (GW)':
            df = df.loc[:,['Metric','Scenario','County','BA','Year','Value']]
        elif metric == 'Annual End-Use Electricity Demand (TWh)':
            df = df.loc[:,['Metric','Scenario','County','BA','Year','Value','Measure']]
        elif metric in ['Transmission Capacity (TW-miles)']:
            df = df.loc[:,['Metric','Scenario','County','BA','Transmission Type','Region Begin','Region End','Transmission Planning Subregion Begin','Transmission Planning Subregion End','Value','Year','Measure']]
        elif metric in ['Interregional Transmission Capacity (GW)']:
            df = df.loc[:,['Metric','Scenario','County','BA','Transmission Type','Region Begin','Region End','Transmission Planning Subregion Begin','Transmission Planning Subregion End','Value','Year','Measure']]
        elif metric == 'System Cost (billion $)':
            df = df.loc[:,['Metric','Scenario','County','BA','Cost Category','Year','Value']]
        elif metric == 'Load-Normalized System Cost ($ per MWh)':
            df = df.loc[:,['Metric','Scenario','County','BA','Year','Value']]    
        elif metric == 'Hydrogen Production (million metric tonnes)':
            df = df.loc[:,['Metric','Scenario','County','BA','Technology','Year','Value']]
        elif metric == 'Load Site Capacity (MW)':
            df = df.loc[:,['Metric','Scenario','County','BA','Year','Value']]    
        else:
            df = df.loc[:,['Metric','Scenario','County','BA','Technology','Year','Value']]

        # remove any rows with techs we want to exclude, we want a minimum amount of data passed to Tableau as possible
        # For example: Technology is not a column in the system cost outputs therefore don't want to assess this for that metric
        if 'Technology' in df.columns:
            df = df.loc[df['Technology'] != 'Exclude'] 

        # reduce data size (be careful with this when using smaller regions than national which could have small values that get truncated)
        df['Value'] = df['Value'].round(3) 

        return df

def set_zero_values(dictin):
    
    # concat all dataframes in dictionrary to 1 for ease of grabbing all unique values across the dataframes
    df = pd.concat(dictin.values(), axis=0, ignore_index=True)
    # create all combinations
        # combinations must be from all scenarios otherwise scenarios with no offshore wind will still have 0 values
    idx = pd.MultiIndex.from_product(
        [df['Metric'].unique(),
        df['Scenario'].unique(),
        df['County'].unique(),
        df['BA'].unique(),
        df['Technology'].unique(),
        # ['Offshore Wind'], # done this way, only OSW is populated, would need to apply set_zero_values() separately for each technology if we want to do this for all technologies, which could be a future improvement but for now just doing this for OSW to reduce the size of the data being passed to Tableau and make it easier to read in Tableau
        df['Year'].unique()],
        names=['Metric','Scenario','County','BA','Technology','Year']) # 
    template = pd.DataFrame(index=idx).reset_index()
    
    # loop through the dictionary of dataframes and set any values that are very close to zero (but not exactly zero) to be exactly zero, this is to reduce the size of the data being passed to Tableau and make it easier to read in Tableau
    for scen in dictin.keys():
        template_scen = template.loc[template['Scenario']==scen]
        # merge with existing data
        df = template_scen.merge(dictin[scen], how='left')
        df['Value'] = df['Value'].fillna(0)
        dictin[scen] = df

    return dictin

def calc_peakload(
    case: str,
    levels:list,
    years:list,
) -> pd.DataFrame:
    """
    Calculate coincident peak demand from ReEDS inputs.

    Args:
        case (str): Path to the ReEDS run case or outputs.h5 file.
        levels (list): list of desired hierarchy levels
        years (list): list of integer years 
    Returns:
        df (pandas dataframe): Peak load (GW) with these columns:
            r (string): region
            Spatial Resolution (string): hierarchy level at which peak load is assessed
            t (int): year
            Value (float): Peak load (GW)
    """
    ### Peak load
    df = pd.read_csv(
        os.path.join(case,'inputs_case','peakload.csv'),
        index_col=['level','region'],
    ).rename(columns=int)

    dictout = {}
    level_map = reeds.results.get_level_map(case)
    for level in levels:
        df_level = df.loc[level,years].stack().rename_axis(['r','t']).rename('Value').reset_index().astype({'t':int}).set_index(['r','t']).squeeze().reset_index()
        df_level['Spatial Resolution'] = level_map[level]
        dictout[level_map[level]] = df_level
    # convert this dictionary to a data frame concatted across the 'Spatial Resolution' column
    df = pd.concat(dictout.values(), axis=0, ignore_index=True) 

    # # convert MW to GW for national data
    df = reeds.results.scale_column(df,**{'scale_factor': 1e-3, 'column':'Value'})

    return df

def calc_subtract_baseyear(tran_out):
    # make one df with only new transmission
    subtract_baseyear = 2020
    trtypes=['AC','B2B','LCC','VSC','LCC (initial)']
    newyears = [x for x in tran_out.t.unique() if x > subtract_baseyear]

    tran_new = pd.DataFrame()
    
    for year in newyears:
        # df for one final year 
        dfplot = tran_out.loc[
            (tran_out.t==(tran_out.t.max() if year=='last' else year))
            & (tran_out.trtype.isin(trtypes))
        ].copy()

        dfplot = (dfplot.set_index(['r','rr','trtype']).Value - tran_out.loc[
            (tran_out.t==subtract_baseyear)
            & (tran_out.trtype.isin(trtypes))
        ].set_index(['r','rr','trtype']).Value.reindex(
            dfplot.set_index(['r','rr','trtype']).index).fillna(0)).clip(lower=0).reset_index()
        # dfplot = dfplot.loc[dfplot.Value>0].copy()

        dfplot['t'] = year
        tran_new = pd.concat([tran_new, dfplot], axis=0)

    tran_new['Measure'] = f'New: deployed since {subtract_baseyear}'
    return tran_new

def calc_transmission_map(case,level='transgrp'):
    trans_total_new = pd.DataFrame()

    ### produce the data for the transmission map
    tran_out = reeds.io.read_output(case, 'tran_out') 
    # tran_out = tran_out.loc[tran_out['Value'] != 0] 

    # make one df with the total installed
    tran_total = tran_out.copy()
    tran_total['Measure'] = 'Total installed'
    trans_total_new = pd.concat([trans_total_new, tran_total], axis=0)

    # make one df with the new capacity 
    tran_new = calc_subtract_baseyear(tran_out)
    
    # combine them
    trans_total_new = pd.concat([trans_total_new, tran_new], axis=0)

    # convert MW to GW
    trans_total_new = reeds.results.scale_column(trans_total_new,**{'scale_factor': 1e-3, 'column':'Value'})   

    return trans_total_new
    
# export all results to csv
def export(dictin,output_dir):
    ### ------ EXPORT -----
    start = time.process_time() # start time

    for metric, dictin_data in dictin.items():

        try:
            df = pd.concat(dictin_data.values(), axis=0, ignore_index=True)
            df.to_csv(os.path.join(output_dir,'data',f'{metric}.csv'),index=False)
        except Exception:
            print(f'{metric} is empty, not printing this to csv.')
            # create a blank df to export so that the csv still gets created and Tableau does not break when trying to read in the data
            df_blank = pd.DataFrame(columns=['Metric','Scenario','County','BA','Year','Value'])
            df_blank.to_csv(os.path.join(output_dir,'data',f'{metric}.csv'),index=False)
            pass

    end = time.process_time() 
    print(f'It took {round(end-start,3)} seconds to export the data.')
    return

#%%### PROCEDURE
if __name__ == '__main__':
    #%%### ARGUMENT INPUTS
    import argparse
    parser = argparse.ArgumentParser(
        description='Create the necessary csv files for Tableau to ingest and visualize from ReEDS outputs')
    parser.add_argument(
        '--reeds_path', default=os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')), 
        help='ReEDS directory')
    parser.add_argument(
        '--tableau_path', default=os.path.expanduser('~\Documents\My Tableau Repository'), 
        help='ReEDS directory')    
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
        '--basecase', '-b', type=str, default='',
        help='Substring of case path to use as default (if empty, uses first case in list)')
    parser.add_argument(
        '--levels', 
        nargs="+",     # '+' means one or more arguments
        default=['r'], # this can be 'ba','county','aggreg', depending on the run
        help="Spatial resolution for results")
    parser.add_argument(
        '--trans_level', type=str, default='transgrp',
        help="Hierachy level at which interregional and intra-regional transmisison are defined at")
    parser.add_argument(
        '--region_filter',  type=str, default='country/USA', 
        help="'Regions you want to visualize. Same format as GSw_Region in cases.csv. Ex. only Utah --> 'st/UT'")
    parser.add_argument(
        '--years', type=list, default=list(range(2025,2051)), 
        help='Solve years to include')

    args = parser.parse_args()
    reeds_path = args.reeds_path
    bp_path = f'{reeds_path}/postprocessing/bokehpivot'
    tableau_path = args.tableau_path
    caselist = args.caselist
    casenames = args.casenames
    try:
        titleshorten = int(args.titleshorten)
    except ValueError:
        titleshorten = len(args.titleshorten)
    basecase_in = args.basecase
    levels = args.levels
    trans_level = args.trans_level
    region_filter = args.region_filter
    years = args.years

    #%%### Inputs for debugging
    # reeds_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
    # caselist = r'C:\Users\ahamilto\Documents\GitHub\ReEDS\postprocessing\example.csv'
    # years = list(range(2025-2050))
    # python tableau_viz_suite.py C:\Users\ahamilto\Documents\GitHub\ReEDS\postprocessing\example.csv --reeds_path C:\Users\ahamilto\Documents\GitHub\ReEDS
    
    #%%###os globals
    this_dir_path = os.path.dirname(os.path.realpath(__file__))
    outpath = this_dir_path + '/out'
    # create an 'out' directory if one does not exist
    if not os.path.exists(outpath):
        os.mkdir(outpath)
    # create a directory specifically for these run results
    timenow = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    output_dir = os.path.join(outpath,f'report-{timenow}')
    os.mkdir(output_dir)
    os.mkdir(os.path.join(output_dir,'data'))
    os.mkdir(os.path.join(output_dir,'shapefiles'))

    # copy this script, the inputs cases .csv file (if applicable) to the output directory
    shutil.copy2(os.path.join(this_dir_path, 'tableau_viz_suite.py'), os.path.join(output_dir))
    shutil.copy2(caselist[0], os.path.join(output_dir))

    #%%### formatting
    # pull in the cases, colors and basemap via existing reeds functions
    cases, colors, basecase, basemap = reeds.report_utils.parse_caselist(caselist,casenames,basecase_in,titleshorten)

    # Technology, cost and transmission colors and mapping is from bokehpivot inputs
    output_formatting = reeds.io.get_plot_formatting()

    # Edit Preferences.tps file, used for custom color palettes in Tableau, and update it with the bokeh colors
    dictin_color = {'Technology':output_formatting['tech_color'].values.tolist()[::-1],
                    'Cost':output_formatting['cost_cat_colors'].values.tolist()[::-1],
                    'Transmission':output_formatting['trtype_colors'].values.tolist()[::-1]}
    
    # if these color palettes exist, indicate if they should be overwritten
    overwrite = True 
    produce_preferences_file(tableau_path,dictin_color,overwrite)
    
    # Create a csv named Scenarios.csv which contains the scenario names and filepaths (see examples in README.md)
    create_scenarios_csv(output_dir,cases)

    # Grab clean display names for the levels
    level_map = reeds.results.get_level_map(cases[basecase])

    # import some key inputs from ReEDS
    dictin_sw = {case: reeds.io.get_switches(cases[case]) for case in cases}
    dictin_hierarchy = {case: reeds.io.get_hierarchy(cases[case]) for case in cases}
    dictin_scalars = {case: reeds.io.get_scalars(cases[case]) for case in cases}

    # produce hierachy.csv for Tableau to use
    produce_hierarchy_file(output_dir,basecase)

    # copy transmission_endpoints.shp or US_COUNTY_2022.shp if runs are at county resolution
    produce_transmission_endpoints()

    # copy US_PCA.shp
    produce_shapefiles()

    # find the commonality of desired years to plot and modeled years
    modeledyears = {case: reeds.io.get_years(cases[case]) for case in cases}
    years = {case: [y for y in years if y in modeledyears[case]] for case in cases}

    #%%### create a dictionary of all the metrics and their dictionaries to export them
    dictin = {}

    #%%### grab all the metrics (make this separate function?)
    ### CAP
    dictin_cap = {}
    metric = 'Capacity (GW)'
    for case in tqdm(cases, desc=metric):
        dictin_cap[case] = reeds.results.calc_cap(cases[case])
        dictin_cap[case] = reformat(dictin_cap[case],case,metric,years[case])
    dictin_cap = set_zero_values(dictin_cap)
    dictin[metric] = dictin_cap

    ### GEN
    dictin_gen = {}
    metric = 'Generation (TWh)'
    for case in tqdm(cases, desc=metric):
        dictin_gen[case] = reeds.results.calc_gen(cases[case])
        dictin_gen[case] = reformat(dictin_gen[case],case,metric,years[case])
    dictin_gen = set_zero_values(dictin_gen)
    dictin[metric] = dictin_gen

    ### EMIT
    dictin_emissions = {}
    metric = 'Emissions (million metric tonnes)'
    for case in tqdm(cases, desc=metric):
        dictin_emissions[case] = reeds.results.calc_emissions(cases[case])
        dictin_emissions[case] = dictin_emissions[case].loc[dictin_emissions[case]['e'] != 'H2'] # remove hydrogen emissions from the dataframe
        dictin_emissions[case] = reformat(dictin_emissions[case],case,metric,years[case])
    dictin[metric] = dictin_emissions
    
    ### PEAK LOAD
    dictin_peakload = {}
    metric = 'Coincident Peak End-Use Electricity Demand (GW)'
    for case in tqdm(cases, desc=metric):
        dictin_peakload[case] = calc_peakload(cases[case],levels,years[case])
        dictin_peakload[case] = reformat(dictin_peakload[case],case,metric,years[case])
    dictin[metric] = dictin_peakload

    ### ANNUAL DEMAND
    dictin_annualload = {}
    metric = 'Annual End-Use Electricity Demand (TWh)'
    for case in tqdm(cases, desc=metric):
        dictin_annualload[case] = reeds.results.calc_annualload(cases[case],dictin_scalars[case]) 
        dictin_annualload[case] = reformat(dictin_annualload[case],case,metric,years[case])
    dictin[metric] = dictin_annualload

    ### ANNUAL SYSTEM COST
    dictin_systemcost = {}
    metric = 'System Cost (billion $)'
    for case in tqdm(cases, desc=metric):
        dictin_systemcost[case] = reeds.results.calc_systemcost(cases[case],group_r=False,drop_zeros=False).rename(columns={'year':'t','Discounted Cost (Bil $)':'Value'})
        del dictin_systemcost[case]['Cost (Bil $)']
        dictin_systemcost[case].cost_cat = dictin_systemcost[case].cost_cat.map(lambda x: output_formatting['cost_cat_map'].get(x,x))
        dictin_systemcost[case] = reformat(dictin_systemcost[case],case,metric,years[case])
    dictin[metric] = dictin_systemcost

    ### LOAD-NORMALIZED SYSTEM COST
    dictin_norm_sys_cost = {}
    metric = 'Load-Normalized System Cost ($ per MWh)'
    for case in tqdm(cases, desc=metric): 
        systemcost_total = dictin_systemcost[case].drop(columns=['Metric','Cost Category']).groupby(['Scenario','County','BA','Year'], as_index=False).sum()
        # Filter to the "Total Demand" in the "Measure" column to avoid double counting
        annualload_total = dictin_annualload[case][dictin_annualload[case]['Measure'] == 'Total Demand'].drop(columns=['Metric','Measure'])
        dictin_norm_sys_cost[case] = pd.merge(
            systemcost_total,
            annualload_total,
            on=['Scenario','County','BA','Year'],
            suffixes=('_systemcost','_annualload'),
            how='right')
        # Convert TWh to MWh and billion dollars to dollars, then calculate $/MWh
        dictin_norm_sys_cost[case]['Value'] = (dictin_norm_sys_cost[case]['Value_systemcost']*1e9)/ (dictin_norm_sys_cost[case]['Value_annualload']*1e6) 
        dictin_norm_sys_cost[case] = dictin_norm_sys_cost[case].drop(columns=['Value_systemcost','Value_annualload'])
        dictin_norm_sys_cost[case] = reformat(dictin_norm_sys_cost[case],case,metric,years[case])
    dictin[metric] = dictin_norm_sys_cost

    ### TRANSMISSION - TOTAL
    dictin_trans_total = {}
    metric = 'Transmission Capacity (TW-miles)'
    for case in tqdm(cases, desc=metric):
        # pull the total installed transmission capacity from ReEDS outputs
        dictin_trans_total[case], _ = reeds.results.calc_transmission_capacity(cases[case],levels=['transgrp'])
        tran_total = dictin_trans_total[case]
        tran_total['Measure'] = 'Total installed'
        # make one df with the new capacity 
        tran_new = calc_subtract_baseyear(dictin_trans_total[case])
        # combine them
        dictin_trans_total[case] = pd.concat([tran_total, tran_new], axis=0)
        dictin_trans_total[case].Value /= 10**3 # convert GW-miles to TW-miles
        dictin_trans_total[case] = reformat(dictin_trans_total[case],case,metric,years[case])
    dictin[metric] = dictin_trans_total

    ## TRANSMISSION - INTERREGIONAL
    dictin_trans_interregional = {}
    metric = 'Interregional Transmission Capacity (GW)'
    for case in tqdm(cases, desc=metric):
        dictin_trans_interregional[case] = calc_transmission_map(cases[case],level='transgrp')
        dictin_trans_interregional[case] = reformat(dictin_trans_interregional[case],case,metric,years[case])
    dictin[metric] = dictin_trans_interregional

    ## HYDROGEN PRODUCTION
    dictin_h2prod = {}
    metric = 'Hydrogen Production (million metric tonnes)'
    for case in tqdm(cases, desc=metric):
        dictin_h2prod[case] = reeds.results.calc_h2prod(cases[case])
        dictin_h2prod[case] = reformat(dictin_h2prod[case],case,metric,years[case])
    dictin[metric] = dictin_h2prod

    ## LOAD SITED CAPACITY
    dictin_sited_load = {}
    metric = 'Load Site Capacity (MW)'
    for case in tqdm(cases, desc=metric):
        dictin_sited_load[case] = reeds.results.calc_sited_load(cases[case])
        dictin_sited_load[case] = reformat(dictin_sited_load[case],case,metric,years[case])
    dictin[metric] = dictin_sited_load

    ### export all data
    export(dictin,output_dir)

print('Successfully completed tableau_viz_suite.py')
