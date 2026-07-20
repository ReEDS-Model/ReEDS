'''
This script calculates monthly hydro capacity factors (CFs) for each model
region and year. Historical CFs are calculated by taking the ratio of net and
max hydro generation for each region's existing hydro fleet.
Future CFs come from two sources:
1) In some cases, CFs are calculated by taking each plant's average net/max
generation across select years and calculating the ratio of total average net
and average max generation for each region's hydro fleet.
2) In other cases, capacity factors come from "hydcf_fixed.csv",
which contains pre-calculated CFs for the legacy 134 zones.
These are transformed into model region-level CFs by uniformly assigning the
zonal CFs to each legacy zone's counties and taking the average CF
across each model region's counties.
'''

import argparse
import numpy as np
import pandas as pd
import os
import sys
import datetime
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))
import reeds

def get_monthly_plant_generation(inputs_case: str) -> (
    tuple[pd.DataFrame, pd.DataFrame]
):
    """
    Get monthly net generation and maximum generation in MWh for
    each hydro plant. Net generation values are read from
    inputs_case/net_gen_existing_hydro.csv, while maximum generation values
    are derived from annual capcities (inputs_case/cap_existing_hydro.csv)
    by calculating monthly generation assuming 100% capacity factor.

    Args:
        inputs_case: Path to the inputs case directory.

    Returns:
        tuple[pd.DataFrame, pd.DataFrame]
    """
    # Read inputs
    annual_plant_capacities = pd.read_csv(
        os.path.join(inputs_case, 'cap_existing_hydro.csv'),
        index_col='t'
    )
    monthly_plant_net_generation = pd.read_csv(
        os.path.join(inputs_case, 'net_gen_existing_hydro.csv'),
        index_col=['t', 'month']
    )
    # Expand annual capacity data to monthly
    monthly_plant_capacities = annual_plant_capacities.reindex(
        monthly_plant_net_generation.index,
        level=0
    )
    # Assign number of hours to each month
    monthly_plant_capacities['date'] = pd.to_datetime(
        (
            monthly_plant_capacities.index.get_level_values('t').astype(str)
            + '-'
            + monthly_plant_capacities.index.get_level_values('month')
        ),
        format='%Y-%b'
    )
    monthly_plant_capacities['num_hours'] = (
        monthly_plant_capacities['date'].dt.daysinmonth * 24
    )
    # Multiply monthly capacities by number of hours in each month
    monthly_plant_max_generation = (
        monthly_plant_capacities.drop(columns=['date', 'num_hours'])
        .mul(monthly_plant_capacities['num_hours'], axis=0)
    )
    # Align null values across datasets
    monthly_plant_max_generation[monthly_plant_net_generation.isna()] = np.nan
    monthly_plant_net_generation[monthly_plant_max_generation.isna()] = np.nan

    return monthly_plant_net_generation, monthly_plant_max_generation


def calculate_regional_generation(
    plant_generation: pd.DataFrame,
    hydro_plants: pd.DataFrame
) -> pd.DataFrame:
    """
    Calculate total generation for each model region in MWh.

    Args:
        plant_generation: Plant-level generation in MWh.
        hydro_plants: Tech and region information for each hydro plant.

    Returns:
        pd.DataFrame
    """
    # Reformat plant generation data and append tech and region information
    index_cols = list(plant_generation.index.names)
    plant_generation = pd.melt(
        plant_generation.reset_index(),
        id_vars=index_cols,
        var_name='EIA_PlantID'
    )
    plant_generation = (
        plant_generation.merge(
            hydro_plants,
            left_on=['EIA_PlantID'],
            right_index=True
        )
        .rename(columns={'tech': '*i'})
    )
    # Group by tech and region and calculate total generation
    groupby_cols = index_cols + ['*i', 'r']
    regional_generation = plant_generation.groupby(groupby_cols).sum()
    regional_generation = (
        pd.pivot_table(
            regional_generation,
            index=['*i'] + index_cols,
            columns=['r'],
            values=['value']
        )
        .droplevel(level=0, axis=1)
        .rename_axis(columns=[''])
    )

    return regional_generation


def calculate_historical_monthly_regional_cf(
    monthly_plant_net_generation: pd.DataFrame,
    monthly_plant_max_generation: pd.DataFrame,
    hydro_plants: pd.DataFrame,
    inputs_case: str
) -> pd.DataFrame:
    """
    Calculate monthly CFs for each model region in historical years.
    In historical years, CFs are calculated by aggregating plant-level
    generation to the region level and taking the ratio of each region's
    total net generation and total max generation.

    Args:
        monthly_plant_net_generation: Monthly plant net generation in MWh.
        monthly_plant_max_generation: Monthly plant max generation in MWh.
        hydro_plants: Tech and region information for each hydro plant.
        inputs_case: Path to the inputs case directory.

    Returns:
        pd.DataFrame
    """
    # Calculate monthly net and max generation for each model region
    monthly_regional_net_generation = calculate_regional_generation(
        monthly_plant_net_generation,
        hydro_plants
    )
    monthly_regional_max_generation = calculate_regional_generation(
        monthly_plant_max_generation,
        hydro_plants
    )
    # Calculate monthly CFs for each model region
    monthly_regional_cf = (
        monthly_regional_net_generation.div(
            monthly_regional_max_generation.replace(0, np.nan)
        )
        .rename_axis(columns=['r'])
        .reorder_levels(order=['t', '*i', 'month'])
    )
    # Downselect to model years
    sw = reeds.io.get_switches(inputs_case)
    startyear = int(sw.startyear)
    monthly_regional_cf = monthly_regional_cf.loc[(
        monthly_regional_cf.index.get_level_values('t') >= startyear
    )]
    
    return monthly_regional_cf


def calculate_regional_average_generation(
    monthly_plant_generation: pd.DataFrame,
    hydro_plants: pd.DataFrame,
    future_hydcf_rep_years: list[int]
) -> pd.DataFrame:
    """
    Calculate average generation across years for each plant
    in each month and then aggregate to the model region level. 

    Args:
        monthly_plant_generation: Monthly plant-level generation in MWh.
        hydro_plants: Tech and region information for each hydro plant.
        future_hydcf_rep_years: Set of years from which to calculate
            future hydro CFs.

    Returns:
        pd.DataFrame
    """
    # Subset generation data to years representing future hydro
    monthly_plant_generation = monthly_plant_generation.loc[(
        monthly_plant_generation.index
        .get_level_values('t')
        .isin(future_hydcf_rep_years)
    )]
    # Calculate average generation across years for each plant in each month
    plant_average_generation = (
        monthly_plant_generation.groupby(level='month')
        .mean()
    )
    # Aggregate average plant-level generation to the model region level
    regional_average_generation = calculate_regional_generation(
        plant_average_generation,
        hydro_plants
    )

    return regional_average_generation


def calculate_future_monthly_regional_cf(
    monthly_plant_net_generation: pd.DataFrame,
    monthly_plant_max_generation: pd.DataFrame,
    hydro_plants: pd.DataFrame,
    inputs_case: str,
):
    """
    Calculate monthly CFs for each model region in future years.
    Future CFs come from two sources:
    1) In some cases, CFs are calculated by taking each plant's average net/max
       generation across select years (based on the GSw_FutureHydCF_RepYears
       switch) and calculating the ratio of total average
       net and average max generation for each region's hydro fleet.
    2) In other cases, capacity factors come from inputs_case/hydcf_fixed.csv,
       which contains pre-calculated CFs for the legacy 134 zones.
       These are transformed into model region-level CFs by uniformly
       assigning the zonal CFs to each legacy zone's counties and taking
       the average CF across each model region's counties.

    In cases where data for a given time and region exist in both sources,
    the first source (i.e., plant-level data) takes precedence.

    Args:
        monthly_plant_net_generation: Monthly plant net generation in MWh.
        monthly_plant_max_generation: Monthly plant max generation in MWh.
        hydro_plants: Tech and region information for each hydro plant.
        inputs_case: Path to the inputs case directory.

    Returns:
        pd.DataFrame
    """
    # Get the set of years that represents future hydro
    sw = reeds.io.get_switches(inputs_case)
    future_hydcf_rep_years = sw['future_hydcf_rep_years_list']
    # Calculate average net and max generation for each plant
    # and aggregate to the model region level
    regional_average_net_generation = calculate_regional_average_generation(
        monthly_plant_net_generation,
        hydro_plants,
        future_hydcf_rep_years
    )
    regional_average_max_generation = calculate_regional_average_generation(
        monthly_plant_max_generation,
        hydro_plants,
        future_hydcf_rep_years
    )
    # Calculate monthly CFs for each model region
    future_cf_existing_techs = regional_average_net_generation.div(
        regional_average_max_generation.replace(0, np.nan)
    )
    # Duplicate monthly CF data for existing techs to derive CFs for
    # upgrade techs, re-assigning "ED/END" hydro categories to "UD/UND"
    upgrade_dict = {"hydED": "hydUD", "hydEND": "hydUND"}
    future_cf_upgrade_techs = (
        future_cf_existing_techs.loc[(
            future_cf_existing_techs.index
            .get_level_values('*i')
            .isin(upgrade_dict.keys())
        )]
        .reset_index()
        .replace(upgrade_dict)
        .set_index(['*i', 'month'])
    )
    # Read pre-calculated fixed CFs and reformat
    future_cf_fixed = pd.read_csv(
        os.path.join(inputs_case, 'hydcf_fixed.csv')
    )
    future_cf_fixed = future_cf_fixed.pivot_table(
        index=['*i', 'month'],
        columns='r',
        values='value'
    )
    ## Concatenate all future CFs
    # Note that we don't simply call pd.concat because the component dataframes
    # are not guaranteed to be mutually exclusive (i.e., we may have both fixed
    # CFs and CFs derived from plant data for a given region and tech), so
    # pd.concat could result in duplicate indices with different values.
    # Instead, we use the concatenation operation below, which is structured so
    # that the CFs calculated from plant data are prioritized over the fixed
    # CFs in cases of duplicate indices.
    future_cf_columns = (
        future_cf_fixed.columns
        .union(future_cf_existing_techs.columns)
        .union(future_cf_upgrade_techs.columns)
    )
    future_cf_index = (
        future_cf_fixed.index
        .union(future_cf_existing_techs.index)
        .union(future_cf_upgrade_techs.index)
    )
    future_cf = pd.DataFrame(
        columns=future_cf_columns,
        index=future_cf_index
    )
    future_cf.update(future_cf_fixed)
    future_cf.update(future_cf_existing_techs)
    future_cf.update(future_cf_upgrade_techs)

    return future_cf


def get_hydro_plants(inputs_case: str) -> pd.DataFrame:
    """
    Reads the EIA plant database from inputs_case/unitdata.csv and
    filters down to hydro plants (plants whose tech starts with "hyd").
    
    Args:
        inputs_case: Path to the inputs case directory.

    Returns:
        pd.DataFrame
    """
    # Get plant database and filter down to hydro plants
    gendb = pd.read_csv(
        os.path.join(inputs_case, 'unitdata.csv'),
        usecols=['T_PID', 'tech', 'r']
    )
    hydro_plants = (
        gendb.loc[gendb.tech.str.startswith('hyd')]
        .drop_duplicates('T_PID')
        .set_index('T_PID')
    )
    hydro_plants.index = hydro_plants.index.astype(str)

    return hydro_plants


def assemble_hydcf(
    historical_monthly_regional_cf: pd.DataFrame,
    future_monthly_regional_cf: pd.DataFrame,
    inputs_case: str
) -> pd.DataFrame:
    """
    Combines monthly historical and future hydro CF data,
    forward-filling the future data up to the ReEDS model end year.
    
    Args:
        historical_monthly_regional_cf: Monthly regional CFs
            in historical years.
        future_monthly_regional_cf: Monthly regional CFs
            in an unspecified future year. These CFs are duplicated
            across years from the end of the historical period
            to the model end year.
        inputs_case: Path to the inputs case directory.

    Returns:
        pd.DataFrame
    """
    # Assign a year to the future CFs corresponding to the
    # year after the final year of historical CFs
    historical_endyear = (
        historical_monthly_regional_cf.index.get_level_values('t').max()
    )
    future_monthly_regional_cf = (
        future_monthly_regional_cf.assign(t=historical_endyear+1)
        .set_index('t', append=True)
        .reorder_levels(historical_monthly_regional_cf.index.names)
    )
    # Concatenate historical and future CFs
    hydcf = pd.concat([
        historical_monthly_regional_cf,
        future_monthly_regional_cf
    ])
    # Reformat so that hydcf is indexed by year and
    # has column levels for tech, month, and region
    hydcf = (
        hydcf.stack()
        .rename_axis(['t','*i','month','r'])
        .rename('value')
        .to_frame()
        .reset_index()
        .pivot_table(index='t', columns=['*i','month','r'], values='value')
    )
    # Forward-fill years up to model end year
    sw = reeds.io.get_switches(inputs_case)
    model_endyear = int(sw.endyear)
    data_endyear = hydcf.index.max()
    reindex = (
        hydcf.index.tolist()
        + np.arange(data_endyear+1, model_endyear+1).tolist()
    )
    hydcf = hydcf.reindex(reindex)
    hydcf.loc[data_endyear:] = hydcf.loc[data_endyear:].ffill()
    # Convert from "wide" to "long" format
    hydcf = hydcf.stack(['*i', 'month']).stack().rename('value').to_frame()

    return hydcf

def apply_hydro_climate_adjustments(
    hydcf_unadjusted: pd.DataFrame,
    inputs_case: str
) -> pd.DataFrame:
    """
    Applies climate adjustment factors to hydropower capacity factors, if applicable.
    
    Non-dispatchable hydro gets new seasonal profiles as well as annually-varying CFs.
    Dispatchable hydro keeps the original seasonal profiles; only annual CF changes. 
        Reflects the assumption that reservoirs will be utilized in the same seasonal pattern 
        even if seasonal inflows change.
    
    Args:
        hydcf_unadjusted: Monthly regional CFs prior to climate adjustments
        inputs_case: Path to the inputs case directory.
    Returns:
        pd.DataFrame
    """
    # Exit function if climate adjustments to hydropower are turned OFF, otherwise continue
    sw = reeds.io.get_switches(inputs_case)
    if not int(sw.GSw_ClimateHydro):
        return hydcf_unadjusted
    
    # Get sets for dispatchable/non-dispatchable hydro from tech subset table
    tech_subsets = pd.read_csv(
        os.path.join(inputs_case, 'tech-subset-table.csv'),
        index_col=0
    )
    hydro_d = set(tech_subsets.loc[tech_subsets['HYDRO_D']=='YES'].index)
    hydro_nd = set(tech_subsets.loc[tech_subsets['HYDRO_ND']=='YES'].index)
    
    # Separate data into dispatchable vs non-dispatchable hydropower
    hydcf_d = hydcf_unadjusted[hydcf_unadjusted.index.isin(hydro_d, level='*i')].reset_index().copy()
    hydcf_nd = hydcf_unadjusted[hydcf_unadjusted.index.isin(hydro_nd, level='*i')].reset_index().copy()
    assert len(hydcf_d)+len(hydcf_nd) == len(hydcf_unadjusted), "At least 1 hydro tech is unaccounted for from hydcf.csv"
    
    # Read hydropower CF climate adjustment factors
    adj_factors_ann = pd.read_csv(
        os.path.join(inputs_case, 'climate_hydadjann.csv'),
        dtype={'r':str,'t':int}
    ).rename(columns={'Value':'Factor'})
    adj_factors_sea = pd.read_csv(
        os.path.join(inputs_case, 'climate_hydadjsea.csv'),
        dtype={'r':str,'t':int,'month':str}
    ).rename(columns={'Value':'Factor'})
    
    # Apply adjustment factors only to years >= GSw_ClimateStartYear - set years before to 1
    adj_factors_ann.loc[adj_factors_ann['t'] < int(sw.GSw_ClimateStartYear),'Factor'] = 1
    adj_factors_sea.loc[adj_factors_sea['t'] < int(sw.GSw_ClimateStartYear),'Factor'] = 1
    
    # Merge and apply adjustment factors
    hydcf_d = pd.merge(hydcf_d, adj_factors_ann, how='left', on=['r','t'])
    hydcf_d['value_adj'] = hydcf_d['value'] * hydcf_d['Factor']
    hydcf_d = hydcf_d.drop(columns=['value','Factor']).rename(columns={'value_adj':'value'})
    hydcf_nd = pd.merge(hydcf_nd, adj_factors_sea, how='left', on=['r','month','t'])
    hydcf_nd['value_adj'] = hydcf_nd['value'] * hydcf_nd['Factor']
    hydcf_nd = hydcf_nd.drop(columns=['value','Factor']).rename(columns={'value_adj':'value'})
    
    # Reassemble hydcf
    hydcf = pd.concat([hydcf_d,hydcf_nd],axis=0).set_index(['t','*i','month','r'])
    

    return hydcf

#%% ===========================================================================
### --- MAIN FUNCTION ---
### ===========================================================================
def main(reeds_path, inputs_case):
    print('Starting hydcf.py')

    monthly_plant_net_generation, monthly_plant_max_generation = (
        get_monthly_plant_generation(inputs_case)
    )
    hydro_plants = get_hydro_plants(inputs_case)
    historical_monthly_regional_cf = calculate_historical_monthly_regional_cf(
        monthly_plant_net_generation,
        monthly_plant_max_generation,
        hydro_plants,
        inputs_case
    )
    future_monthly_regional_cf = calculate_future_monthly_regional_cf(
        monthly_plant_net_generation,
        monthly_plant_max_generation,
        hydro_plants,
        inputs_case
    )
    hydcf = assemble_hydcf(
        historical_monthly_regional_cf,
        future_monthly_regional_cf,
        inputs_case
    )
    hydcf = apply_hydro_climate_adjustments(
        hydcf,
        inputs_case
    )

    hydcf.to_csv(os.path.join(inputs_case, 'hydcf.csv'))



#%% ===========================================================================
### --- PROCEDURE ---
### ===========================================================================

if __name__ == '__main__':
    # Time the operation of this script
    tic = datetime.datetime.now()

    ### Parse arguments
    parser = argparse.ArgumentParser(
        description='Process hydro capacity factors',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('reeds_path', help='ReEDS directory')
    parser.add_argument('inputs_case', help='ReEDS/runs/{case}/inputs_case directory')

    args = parser.parse_args()
    reeds_path = args.reeds_path
    inputs_case = args.inputs_case

    # #%% Settings for testing
    # reeds_path = reeds.io.reeds_path
    # inputs_case = os.path.join(
    #     reeds_path,'runs',
    #     'InstantiateRepo_USA_defaults','inputs_case')

    #%% Set up logger
    log = reeds.log.makelog(
        scriptname=__file__,
        logpath=os.path.join(inputs_case,'..','gamslog.txt'),
    )

    #%% Run it
    main(reeds_path=reeds_path, inputs_case=inputs_case)

    reeds.log.toc(tic=tic, year=0, process='input_processing/hydcf.py',
        path=os.path.join(inputs_case,'..'))
    
    print('Finished hydcf.py')