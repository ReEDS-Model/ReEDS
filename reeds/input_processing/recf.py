'''
This script handles the modifications of static inputs for the first solve year. These inputs
include the 8760 renewable energy capacity factor (RECF) profiles. RECF and resource data for
various technologies are combined into single files for output:

Resources:
        - Creates a resource-to-(i,r,ccreg) lookup table for use in hourly_writesupplycurves.py 
          and resource adequacy calculations
        - Add the distributed PV resources
RECF:
        - Add the distributed PV recf profiles
        - Sort the columns in recf to be in the same order as the rows in resources
        - Scale distributed resource CF profiles by distribution loss factor and tiein loss factor
'''

#%% ===========================================================================
### --- IMPORTS ---
### ===========================================================================

import argparse
import datetime
import numpy as np
import os
import pandas as pd
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))
import reeds


#%% ===========================================================================
### --- FUNCTIONS ---
### ===========================================================================

def csp_dispatch(cfcsp, sm=2.4, storage_duration=10):
    """
    Use a simple no-foresight heuristic to dispatch CSP.
    Excess energy from the solar field (i.e. energy above the max plant power output)
    is sent to storage, and energy in storage is dispatched as soon as possible.

    --- Inputs ---
    cfcsp: hourly energy output of solar field [fraction of max field output]
    sm: solar multiple [solar field max output / plant max power output]
    storage_duration: hours of storage as multiple of plant max power output
    """
    ### Calculate derived dataframes
    ## Field energy output as fraction of plant max output
    dfcf = cfcsp * sm
    ## Excess energy as fraction of plant max output
    clipped = (dfcf - 1).clip(lower=0)
    ## Remaining generator capacity after direct dispatch (can be used for storage dispatch)
    headspace = (1 - dfcf).clip(lower=0)
    ## Direct generation from solar field
    direct_dispatch = dfcf.clip(upper=1)

    ### Numpy arrays
    clipped_val = clipped.values
    headspace_val = headspace.values
    hours = range(len(clipped_val))
    storage_dispatch = np.zeros(clipped_val.shape)
    ## Need one extra storage hour at the end, though it doesn't affect dispatch
    storage_energy_hourstart = np.zeros((len(hours)+1, clipped_val.shape[1]))

    ### Loop over all hours and simulate dispatch
    for h in hours:
        ### storage dispatch is...
        storage_dispatch[h] = np.where(
            clipped_val[h],
            ## zero if there's clipping in hour
            0,
            ## otherwise...
            np.where(
                headspace_val[h] > storage_energy_hourstart[h],
                ## storage energy at start of hour if more headspace than energy
                storage_energy_hourstart[h],
                ## headspace if more storage energy than headspace
                headspace_val[h]
            )
        )
        ### storage energy at start of next hour is...
        storage_energy_hourstart[h+1] = np.where(
            clipped_val[h],
            ## storage energy in current hour plus clipping if clipping
            storage_energy_hourstart[h] + clipped_val[h],
            ## storage energy in current hour minus dispatch if not clipping
            storage_energy_hourstart[h] - storage_dispatch[h]
        )
        storage_energy_hourstart[h+1] = np.where(
            storage_energy_hourstart[h+1] > storage_duration,
            ## clip storage energy to storage duration if energy > duration
            storage_duration,
            ## otherwise no change
            storage_energy_hourstart[h+1]
        )

    ### Format as dataframe and calculate total plant dispatch
    storage_dispatch = pd.DataFrame(
        index=clipped.index, columns=clipped.columns, data=storage_dispatch)

    total_dispatch = direct_dispatch + storage_dispatch

    return total_dispatch


def make_fake_profiles(
    sitecf:pd.Series,
    timeindex:pd.DatetimeIndex,
    seed:None|int=17,
) -> pd.DataFrame:
    """
    Make a dataframe of fake CF profiles, len(timeindex) rows × len(sitecf) columns.
    To make them somewhat realistic in terms of min/mean/max (but not temporal shape),
    we randomly sample from the two-state [0,1] array, where probaility(1) = CF [fraction].
    These profiles should NOT be used for any kind of analysis; they are just for testing
    when you want to avoid downloading the actual data via reeds/remote.py.

    Args:
        sitecf (pd.Series): index = sc_point_gids, values = capacity factor [fraction]
        timeindex (pd.DatetimeIndex): Time index for the output dataframe
        seed (int): (optional) Random number generator (RNG) seed

    Returns:
        pd.DataFrame: len(timeindex) rows × len(sitecf) columns

    Inputs for testing:
        sitecf = pd.Series{{36432:0.24, 37116:0.59, 37787:0.07, 38464:0.27})
        timeindex = pd.date_range(
            '2007-01-01', '2008-01-01', freq='h', inclusive='left', tz='UTC'
        )[:8760]
        seed = 17
    """
    rng = np.random.default_rng(seed)
    choices = [0, 1]
    ## Site-specific CF
    prob1 = sitecf.values
    prob0 = 1 - prob1
    probs = list(zip(prob0, prob1))
    dfout = pd.concat(
        {
            s: pd.Series(rng.choice(a=choices, size=len(timeindex), p=p))
            for s, p in zip(sitecf.index, probs)
        },
        axis=1,
    )
    dfout.index = timeindex

    return dfout


def calculate_class_region_cf_hourly(
    inputs_case,
    tech,
    weather_years,
    tz_out='Etc/GMT+6'
):
    if not tz_out.startswith('Etc/GMT'):
        raise ValueError("tz_out must be formatted as 'Etc/GMT[+/-][number].")

    sw = reeds.io.get_switches(inputs_case)
    # Get supply curve information
    df_sc = reeds.io.assemble_supplycurve(
        os.path.join(inputs_case, f'supplycurve_{tech}.csv'),
        case=os.path.dirname(inputs_case),
        agg=True,
    )
    # Calculate total capacity for each class-region pair
    df_sc['class_region'] = (
        df_sc['class'].astype(str) + '|' + df_sc['region']
    )
    class_region_cap = (
        df_sc.groupby('class_region')
        ['capacity']
        .sum()
    )
    # Note we calculate on a per-year basis to avoid loading
    # all of the site-level hourly data in memory at once
    df_list = []
    for year in weather_years:
        print(f'Processing {tech} CF for {year}')
        # Get site-level hourly CFs
        if int(sw.GSw_FakeData):
            weather_year_site_cf_hourly = make_fake_profiles(
                sitecf=df_sc['cf'],
                timeindex=reeds.timeseries.get_timeindex([year], tz='UTC'),
            )
        else:
            weather_year_site_cf_hourly = reeds.io.get_site_cf_hourly(
                tech=tech,
                year=year,
                case=inputs_case,
            )
        # Downselect to relevant sites
        weather_year_site_cf_hourly = weather_year_site_cf_hourly[df_sc.index]
        # Calculate the capacity-weighted average CF for each class-region pair
        weather_year_class_region_cf_hourly = (
            weather_year_site_cf_hourly.mul(df_sc['capacity'])
            .rename(columns=df_sc['class_region'])
            .groupby(axis=1, level=0)
            .sum()
            .div(class_region_cap)
        )
        # For timezone conversion, we need a few hours of CF data for the next
        # year. If we don't have data for the next year, assume the profile
        # for the last day of this year is repeated for the first day of
        # the next year and append to the end of the set of profiles.
        next_year = year + 1
        if next_year not in weather_years:
            next_year_first_day_data = (
                weather_year_class_region_cf_hourly.tail(24)
            )
            next_year_first_day_data.index += pd.Timedelta(days=1)
            weather_year_class_region_cf_hourly = (
                pd.concat([
                    weather_year_class_region_cf_hourly,
                    next_year_first_day_data
                ])
            )
        # Append to list of yearly data
        df_list.append(weather_year_class_region_cf_hourly)

    # Concatenate all CF data
    class_region_cf_hourly = pd.concat(df_list)

    # Shift timezone from UTC to tz_out and trim to modeled years
    timeindex = reeds.timeseries.get_timeindex(weather_years)
    utc_offset = -1 * int(tz_out.split('Etc/GMT')[1])
    class_region_cf_hourly = (
        class_region_cf_hourly.shift(utc_offset)
        .tz_localize(None)
        .tz_localize(tz_out)
        .loc[timeindex]
    )
    class_region_cf_hourly.index.names = ['datetime']

    return class_region_cf_hourly


def calculate_regional_distpv_cf(inputs_case, cap_min=0.0001):
    # Get county-to-region mapping
    county2zone = reeds.io.get_county2zone(os.path.dirname(inputs_case))
    county2zone.index = 'p' + county2zone.index
    # Read county-level distpv capacity factors and
    # downselect to relevant counties
    county_distpv_cf = reeds.io.get_distpv_cf_hourly()
    county_distpv_cf = county_distpv_cf[county2zone.index]
    # Read county- and model region-level distpv capacities to use
    # in capacity-weighted averages
    sw = reeds.io.get_switches(inputs_case)
    county_distpv_cap = reeds.io.get_distpv_capacities(distpvscen=sw.distpvscen)
    regional_distpv_cap = reeds.io.get_distpv_capacities(inputs_case)
    # Increment hourly cluster year if there is no data for the provided year
    GSw_HourlyClusterYear = sw.GSw_HourlyClusterYear
    if GSw_HourlyClusterYear not in county_distpv_cap:
        GSw_HourlyClusterYear = str(int(GSw_HourlyClusterYear) + 1)
    # Downselect to relevant counties and hourly cluster year values.
    # Some counties (and regions defined by small groups of counties) have zero
    # distpv capacity. We assign these an arbitrarily small capacity for the
    # weighting to avoid division-by-zero errors.
    county_distpv_cap = (
        county_distpv_cap.loc[county_distpv_cf.columns, GSw_HourlyClusterYear]
        .clip(lower=cap_min)
    )
    regional_distpv_cap = regional_distpv_cap[GSw_HourlyClusterYear].clip(lower=cap_min)
    # Calculate capacity-weighted average capacity factors by calculating
    # regional distpv generation and dividing by each region's distpv capacity
    regional_distpv_cf = (
        county_distpv_cf.mul(county_distpv_cap)
        .rename(columns=county2zone)
        .groupby(axis=1, level=0)
        .sum()
        .div(regional_distpv_cap)
    )

    return regional_distpv_cf


#%% ===========================================================================
### --- MAIN FUNCTION ---
### ===========================================================================
def main(reeds_path, inputs_case):
    print('Starting recf.py')
    
    # #%% Settings for testing
    # reeds_path = reeds.io.reeds_path
    # inputs_case = os.path.join(
    #     reeds_path,'runs','v20260601_repM0_USA_H20_ramp3_yr12_ys1623','inputs_case')

    #%% Inputs from switches
    sw = reeds.io.get_switches(inputs_case)
    resource_adequacy_years = sw['resource_adequacy_years_list']
    GSw_CSP_Types = [int(i) for i in sw.GSw_CSP_Types.split('_')]
    GSw_PVB_Types = sw.GSw_PVB_Types
    GSw_PVB = int(sw.GSw_PVB)


    #%%### Load inputs
    ### Load the input parameters
    scalars = reeds.io.get_scalars(inputs_case)
    ### distloss
    distloss = scalars['distloss']

    ### Load spatial hierarchy
    hierarchy = pd.read_csv(
        os.path.join(inputs_case,'hierarchy.csv')
    ).rename(columns={'*r':'r'}).set_index('r')
    hierarchy_original = (
        pd.read_csv(os.path.join(inputs_case, 'hierarchy_original.csv'))
        .rename(columns={'ba':'r'})
        .set_index('r')
    )
    ### Add ccreg column with the desired hierarchy level
    if sw['capcredit_hierarchy_level'] == 'r':
        hierarchy['ccreg'] = hierarchy.index.copy()
        hierarchy_original['ccreg'] = hierarchy_original.index.copy()
    else:
        hierarchy['ccreg'] = hierarchy[sw.capcredit_hierarchy_level].copy()
        hierarchy_original['ccreg'] = hierarchy_original[sw.capcredit_hierarchy_level].copy()
    ### Map regions to new ccreg's
    r2ccreg = hierarchy['ccreg']

    # Get technology subsets
    tech_table = pd.read_csv(
        os.path.join(inputs_case,'tech-subset-table.csv'), index_col=0).fillna(False).astype(bool)
    techs = {tech:list() for tech in list(tech_table)}
    for tech in techs.keys():
        techs[tech] = tech_table[tech_table[tech]].index.values.tolist()
        techs[tech] = [x.lower() for x in techs[tech]]
        temp_save = []
        temp_remove = []
        # Interpreting GAMS syntax in tech-subset-table.csv
        for subset in techs[tech]:
            if '*' in subset:
                temp_remove.append(subset)
                temp = subset.split('*')
                temp2 = temp[0].split('_')
                temp_low = pd.to_numeric(temp[0].split('_')[-1])
                temp_high = pd.to_numeric(temp[1].split('_')[-1])
                temp_tech = ''
                for n in range(0,len(temp2)-1):
                    temp_tech += temp2[n]
                    if not n == len(temp2)-2:
                        temp_tech += '_'
                for c in range(temp_low,temp_high+1):
                    temp_save.append('{}_{}'.format(temp_tech,str(c)))
        for subset in temp_remove:
            techs[tech].remove(subset)
        techs[tech].extend(temp_save)
    vre_dist = techs['VRE_DISTRIBUTED']

    #%% Read capacity factor profiles

    ### Onshore Wind
    df_windons = calculate_class_region_cf_hourly(
        inputs_case,
        'wind-ons',
        resource_adequacy_years
    )
    df_windons.columns = ['wind-ons_' + col for col in df_windons]
    ### Don't do aggregation in this case, so make a 1:1 lookup table
    lookup = pd.DataFrame({'ragg':df_windons.columns.values})
    lookup['r'] = lookup.ragg.map(lambda x: x.rsplit('|',1)[1])
    lookup['i'] = lookup.ragg.map(lambda x: x.rsplit('|',1)[0])

    ### Offshore Wind
    if int(sw['GSw_OfsWind']) != 0:
        df_windofs = calculate_class_region_cf_hourly(
            inputs_case,
            'wind-ofs',
            resource_adequacy_years
        )
        df_windofs.columns = ['wind-ofs_' + col for col in df_windofs]

    ### UPV
    df_upv = calculate_class_region_cf_hourly(
        inputs_case,
        'upv',
        resource_adequacy_years
    )
    df_upv.columns = ['upv_' + col for col in df_upv]

    # If DistPV is turned off, create an empty dataframe with the same index as df_upv to concat
    if int(sw['GSw_distpv']) == 0: 
        df_distpv = pd.DataFrame(index=df_upv.index)
    else:
        df_distpv = calculate_regional_distpv_cf(inputs_case)
        df_distpv.columns = [f"distpv|{col}" for col in df_distpv.columns]

    ### CSP
    # If CSP is turned off, create an empty dataframe with the same index as df_upv to concat
    if int(sw['GSw_CSP']) == 0:
        cspcf = pd.DataFrame(index=df_upv.index)
    else:
        cspcf = reeds.io.read_file(
            os.path.join(inputs_case, 'recf_csp.h5'),
            parse_timestamps=True,
        )

    ### Format PV+battery profiles
    # Get the PVB types
    pvb_ilr = pd.read_csv(
        os.path.join(inputs_case, 'pvb_ilr.csv'),
        header=0, names=['pvb_type','ilr'], index_col='pvb_type').squeeze(1)
    df_pvb = {}
    # Override GSw_PVB_Types if GSw_PVB is turned off
    GSw_PVB_Types = (
        [int(i) for i in GSw_PVB_Types.split('_')] if int(GSw_PVB)
        else []
    )
    for pvb_type in GSw_PVB_Types:
        ilr = int(pvb_ilr['pvb{}'.format(pvb_type)] * 100)
        # If PVB uses same ILR as UPV then use its profile
        infile = 'recf_upv' if ilr == scalars['ilr_utility'] * 100 else f'recf_upv_{ilr}AC'
        df_pvb[pvb_type] = reeds.io.read_file(
            os.path.join(inputs_case,infile+'.h5'),
            parse_timestamps=True,
        )
        df_pvb[pvb_type].columns = [f'pvb{pvb_type}_{c}'
                                    for c in df_pvb[pvb_type].columns]
        df_pvb[pvb_type].index = df_upv.index.copy()

    ### Concat RECF data
    recf = pd.concat(
        [df_windons, df_windofs, df_upv, df_distpv]
        + [df_pvb[pvb_type] for pvb_type in df_pvb],
        sort=False, axis=1, copy=False)
    
    ### Downselect RECF data to resource adequacy and weather years
    recf = recf.loc[recf.index.year.isin(resource_adequacy_years)]

    ### Add the other recf techs to the resources lookup table
    toadd = pd.DataFrame({'ragg': [c for c in recf.columns if c not in lookup.ragg.values]})
    toadd['r'] = [c.rsplit('|', 1)[1] for c in toadd.ragg.values]
    toadd['i'] = [c.rsplit('|', 1)[0] for c in toadd.ragg.values]
    resources = (
        pd.concat([lookup, toadd], axis=0, ignore_index=True)
        .rename(columns={'ragg':'resource','r':'area','i':'tech'})
        .sort_values('resource').reset_index(drop=True)
    )

    #%%%#############################################
    #    -- Performing Resource Modifications --    #
    #################################################
    if int(sw['GSw_OfsWind']) == 0:
        wind_ofs_resource = ['wind-ofs_' + str(n) for n in range(1,16)]
        resources = resources[~resources['tech'].isin(wind_ofs_resource)]
    
    # Sorting profiles of resources to match the order of the rows in resources
    resources = resources.sort_values(['resource','area'])
    recf = recf.reindex(labels=resources['resource'].drop_duplicates(), axis=1, copy=False)

    ### Scale up distpv by 1/(1-distloss)
    recf.loc[
        :, resources.loc[resources.tech.isin(vre_dist),'resource'].values
    ] /= (1 - distloss)

    # Set the column names for resources to match ReEDS
    resources['ccreg'] = resources.area.map(r2ccreg)
    resources.rename(columns={'area':'r','tech':'i'}, inplace=True)
    resources = resources[['r','i','ccreg','resource']]


    #%%### Concentrated solar thermal power (CSP)
    ### Create CSP resource label for each CSP type (labeled by "tech" as csp1, csp2, etc)
    csptechs = [f'csp{c}' for c in GSw_CSP_Types]
    csp_resources = pd.concat({
        tech:
        pd.DataFrame({
            'resource': cspcf.columns,
            'r': cspcf.columns.map(lambda x: x.split('|')[1]),
            'class': cspcf.columns.map(lambda x: x.split('|')[0]),
        })
        for tech in csptechs
    }, axis=0, names=('tech',)).reset_index(level='tech')

    csp_resources = (
        csp_resources
        .assign(i=csp_resources['tech'] + '_' + csp_resources['class'].astype(str))
        .assign(resource=csp_resources['tech'] + '_' + csp_resources['resource'])
        .assign(ccreg=csp_resources.r.map(r2ccreg))
        [['i','r','resource','ccreg']]
    )    
    ###### Simulate CSP dispatch for each design
    ### Get solar multiples
    sms = {tech: scalars[f'csp_sm_{tech.strip("csp")}'] for tech in csptechs}
    ### Get storage durations
    storage_duration = pd.read_csv(
        os.path.join(inputs_case,'storage_duration.csv'), header=None, index_col=0).squeeze(1)
    ## All CSP resource classes have the same duration for a given tech, so just take the first one
    durations = {tech: storage_duration[f'csp{tech.strip("csp")}_1'] for tech in csptechs}
    ### Run the dispatch simulation for modeled regions

    csp_system_cf = pd.concat({
        tech: csp_dispatch(cspcf, sm=sms[tech], storage_duration=durations[tech])
        for tech in csptechs
    }, axis=1)
    ## Collapse multiindex column labels to single strings
    csp_system_cf.columns = ['_'.join(c) for c in csp_system_cf.columns]

    ### Add CSP to RE output dataframes
    csp_system_cf = csp_system_cf.loc[recf.index]
    recf = pd.concat([recf, csp_system_cf], axis=1)
    resources = pd.concat([resources, csp_resources], axis=0)

    #%% Check for errors
    nulls = recf.isnull().sum()
    missing = nulls.loc[nulls > 0]
    if len(missing):
        print(missing)
        err = f"Missing RECF values for {len(missing)} columns"
        raise ValueError(err)


    #%%###########################
    #    -- Data Write-Out --    #
    ##############################

    reeds.io.write_profile_to_h5(recf.astype(np.float16), 'recf.h5', inputs_case)
    resources.to_csv(os.path.join(inputs_case,'resources.csv'), index=False)
    ### Write the CSP solar field CF (no SM or storage) for hourly_writetimeseries.py
    cspcf = cspcf.rename(columns=dict(zip(cspcf.columns, [f'csp_{i}' for i in cspcf.columns])))
    reeds.io.write_profile_to_h5(cspcf.astype(np.float32), 'csp.h5', inputs_case)
    ### Overwrite the original hierarchy.csv based on capcredit_hierarchy_level
    hierarchy.rename_axis('*r').to_csv(
        os.path.join(inputs_case, 'hierarchy.csv'), index=True, header=True)
    ccreg = pd.Series(hierarchy.ccreg.unique())
    reeds.io.write_to_inputs_h5(
        ccreg, 'ccreg', inputs_case, gamstype='set', comment='capacity credit region',
    )



#%% ===========================================================================
### --- PROCEDURE ---
### ===========================================================================

if __name__ == '__main__':
    # Time the operation of this script
    tic = datetime.datetime.now()

    ### Parse arguments
    parser = argparse.ArgumentParser(
        description='Create run-specific hourly profiles',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('reeds_path', help='ReEDS directory')
    parser.add_argument('inputs_case', help='ReEDS/runs/{case}/inputs_case directory')

    args = parser.parse_args()
    reeds_path = args.reeds_path
    inputs_case = args.inputs_case

    #%% Set up logger
    log = reeds.log.makelog(
        scriptname=__file__,
        logpath=os.path.join(inputs_case,'..','gamslog.txt'),
    )

    #%% Run it
    main(reeds_path=reeds_path, inputs_case=inputs_case)

    reeds.log.toc(tic=tic, year=0, process='input_processing/recf.py',
        path=os.path.join(inputs_case,'..'))
    
    print('Finished recf.py')
