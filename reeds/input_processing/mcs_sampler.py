"""
This module performs the Monte Carlo sampling for ReEDS.
"""


#%% ===========================================================================
### --- IMPORTS ---
### ===========================================================================
import argparse
import copy
import datetime
import numpy as np
import os
import pandas as pd
import scipy.stats
import sys
import yaml
from typing import Tuple, List
from collections import defaultdict

# Local Imports
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))
import reeds
from reeds.input_processing import copy_files


#%% ===========================================================================
### --- CONSTANTS ---
### ===========================================================================
class MCSConstants:
    """
    Configuration constants for the Monte Carlo Sampling (MCS) process in ReEDS.
    Contains synonyms, file names for special treatment, and valid distribution identifiers.
    """
    ### --- Synonyms
    TECH_DESCRIPTOR = ['i', 'type', 'Tech', 'Geo class', 'Depth', 'Turbine', 'tech', '*tech', 'class']
    YEAR_SYNONYMS = ['t', 'Year', 'year']
    REGION_SYNONYMS = ['r', 'region', 'cendiv', 'sc_point_gid', 'FIPS']

    ### --- Fixed columns that should not be modified in most cases
    OTHER_INDICES = ['columns', 'p', '*p'] # 'p' is used in h2_exog_cap.csv
    NONMODIFIABLE_FINANCIAL_COLUMNS = ['debt_fraction', 'tax_rate']
    FIXED_COLUMN_NAMES = YEAR_SYNONYMS + TECH_DESCRIPTOR + OTHER_INDICES + NONMODIFIABLE_FINANCIAL_COLUMNS + REGION_SYNONYMS

    ### --- Files that require special treatment
    SUPPLY_CURVE_FILES = [
        "supplycurve_upv.csv",
        "supplycurve_wind-ofs.csv",
        "supplycurve_wind-ons.csv",
    ]
    EXOG_CAP_FILES = ["exog_cap_upv.csv", "exog_cap_wind-ons.csv"]
    PRESCRIBED_BUILDS_FILES = ["prescribed_builds_wind-ofs.csv", "prescribed_builds_wind-ons.csv"]
    RECF_FILES = ["recf_wind-ons.h5", "recf_wind-ofs.h5", "recf_upv.h5"]

    ### --- Switch-File(s) combinations hardcoded in copy_files.py
    # These files are explicitly handled in copy_files.py, bypassing the standard
    # runfiles.csv instructions. In these cases, the switch is often used as a filter
    # to select specific rows or columns within the file.
    HARD_CODED_SWITCH_TO_FILE_READ = {
        'GSw_H2_Demand_Case': ["h2_exogenous_demand.csv"],
    }

    SITING_SWITCHES = ["GSw_SitingUPV", "GSw_SitingWindOfs", "GSw_SitingWindOns"]

    ### --- Distribution categories (used outside validation, e.g. WeightCalculator)
    MULTIPLICATIVE_DISTRIBUTIONS = ["uniform_multiplier", "triangular_multiplier"]


#%% ===========================================================================
### --- Auxiliary functions ---
### ===========================================================================
def max_decimal_places(data, columns: list = None) -> dict:
    """
    Calculate the maximum number of decimal places in a single number, specific columns, or all columns of a DataFrame.
    
    Args:
    data (pd.DataFrame or numeric): The input DataFrame or a single numeric value (float or int).
    columns (list or None): List of column names to analyze if data is a DataFrame. If None, all columns will be analyzed.
    
    Returns:
    int or dict: 
        - If data is a single number, returns the number of decimal places in the number.
        - If data is a DataFrame, returns a dictionary with column names as keys and their respective maximum number of decimal places as values.
    """
    # Function to count the number of decimals in a single number
    def count_decimals(data):
        if isinstance(data, (float, int, str)) and '.' in str(data):
            return len(str(data).split('.')[1])
        else:
            return 0

    # If we have a single number or a list of numbers
    if not isinstance(data, pd.DataFrame):
        if isinstance(data, (list, np.ndarray)):
            return max([count_decimals(val) for val in data])
        else:
            return count_decimals(data)

    else:
        # If columns is None, analyze all columns
        if columns is None:
            columns = data.keys()

    # Compute the maximum number of decimal places for each specified column
    return {col: data[col].apply(count_decimals).max() for col in columns}


def read_exception_file(sw_assignment: str, file_name: str, file_path: str) -> pd.DataFrame:
    """
    Handles exceptions for files that are hardcoded in copy_files.py
    and written directly without using runfiles.csv.

    This function allows you to manually support special cases where
    a switch-file combination is not automatically handled by the MCS module.
    If you encounter a new unsupported case, you can add it here.

    Args:
        sw_assignment (str): The switch assignment.
        file_name (str): Name of the file (output filename).
        file_path (str): Path to the reference file (inputs folder).

    Returns:
        pd.DataFrame: A DataFrame formatted as expected before being written 
        to the inputs_case folder (as in copy_files.py).
    """
    if file_name == 'h2_exogenous_demand.csv':
        # h2_exogenous_demand.csv has a path in runfiles.csv (considered a non-region file)
        df = pd.read_csv(file_path, index_col=['p', 't'])
        df = df[sw_assignment].round(3).rename_axis(['*p', 't']).reset_index()

        # Rename the value column to 'million_tons' to avoid issues in writecapdat.py
        df.rename(columns={sw_assignment: 'million_tons'}, inplace=True)
        return df

    return None


def read_csv_h5_file(sw_runfiles_csv, aux_files, reeds_path, inputs_case) -> pd.DataFrame:
    """
    This function reads a csv or h5 file based on a row of runfiles.csv and returns a dataframe with the data
    in the ReEDS format.

    Args:
        sw_runfiles_csv (pd.Series): A row of runfiles.csv with sw preassigned to the filepath.
        aux_files (dict): A dictionary with auxiliary information for the copy_files.py module.
        reeds_path (str): The path to the ReEDS directory.
        inputs_case (str): The path to the inputs case directory.

    Returns:
        pd.DataFrame: A DataFrame with the data in the ReEDS format.
    """
    # Obtain the data used by copy_files.py to filter regions and create tailored dataframes 
    nonregion_files = aux_files['nonregion_files']
    region_files = aux_files['region_files']
    file_name = sw_runfiles_csv['filename']
    file_path = os.path.join(reeds_path, sw_runfiles_csv['full_filepath'])

    # Try to read the file using the read_exception_file function first
    df = read_exception_file(sw_runfiles_csv['sw_assignment'], file_name, file_path)
    if df is not None:
        return df
    
    if file_name in region_files['filename'].values:
        # Regional file (works for both csv and h5)
        df = copy_files.subset_to_valid_regions(
            aux_files['sw'],
            sw_runfiles_csv,
            aux_files['agglevel_variables'],
            aux_files['regions_and_agglevel'],
            inputs_case,
            agg=False,
        )

    elif file_name in nonregion_files['filename'].values:
        files_not_supported = ['scalars.csv']
        if file_path.endswith('.csv') and file_name not in files_not_supported:
            # read the csv file
            df = pd.read_csv(file_path)
        else:
            #File not implemented yet
            error_message = 'The file %s has not been implemented yet' % sw_runfiles_csv['filename']
            raise ValueError(error_message + ' improve function read_csv_h5_file')

    elif file_name in ['switches.csv']:
        df = pd.read_csv(os.path.join(inputs_case, file_name),
            header = None, index_col=0, dtype=str)
    
    elif file_name == 'load.h5':
        # special handling for load file since it is processed downstream of copyfiles.py
        sw_mc = sw.copy()
        sw_mc.GSw_LoadProfiles = sw_runfiles_csv.sw_assignment
        # read load.h5 file directly from the repo
        df = reeds.io.get_load_hourly(GSw_LoadProfiles=sw_runfiles_csv.sw_assignment)

    else:
        error_message = (
            f"The file '{file_name}' is not classified under nonregion_files or region_files, "
            "and it is not currently handled by the read_exception_file function. "
            "If you want to use this switch-file combination in MCS, please update the read_exception_file function "
            "and add an entry to MCSConstants.HARD_CODED_SWITCH_TO_FILE_READ."
        )
        raise ValueError(error_message)

    return df


def get_hierarchy_file(inputs_case: str, ReEDS_resolution: str) -> pd.DataFrame:
    """
    The hierarchy file in `{inputs_case}/hierarchy.csv` does not contain a
    differentiation between "ba" and "aggreg" resolution. This function
    reconstructs the hierarchy file with all possible combinations relevant
    to the MCS.

    Args:
        inputs_case (str): Path to the inputs case directory.
        ReEDS_resolution (str): The spatial resolution used in ReEDS (e.g., 'ba', 'aggreg').

    Returns:
        pd.DataFrame: A DataFrame with the hierarchy information relevant to the regions
            considered in the inputs_casse run.
    """
    original_hierarchy_file = pd.read_csv(
        os.path.join(inputs_case, "hierarchy_original.csv")
    )

    valid_regions = pd.read_csv(
        os.path.join(inputs_case, "hierarchy.csv")
    )['*r'].values

    filtered_hierarchy  = original_hierarchy_file[
        original_hierarchy_file[ReEDS_resolution].isin(valid_regions)
    ].reset_index(drop=True)

    return filtered_hierarchy

def check_lhs_param_order(lower, upper):
    """Ensure lower bounds are less than upper bounds, swapping where necessary.

    Args:
        lower (np.ndarray or float): Lower bound value(s).
        upper (np.ndarray or float): Upper bound value(s).

    Returns:
        Tuple[np.ndarray, np.ndarray]: Corrected (lower, upper) arrays.
    """
    # ensure that lower (loc) < upper (loc + scale)
    lower_new = np.where(lower > upper, upper, lower)
    upper_new = np.where(lower > upper, lower, upper)

    return lower_new, upper_new

#%% ===========================================================================
### --- FILE PATHS & DISTRIBUTION INSTRUCTIONS ---
### ===========================================================================
def mcs_find_copy_paths(
    sw_name: str,
    sw_assignments: list,
    runfiles: pd.DataFrame,
    reeds_path: str,
    inputs_case: str,
) -> Tuple[list, pd.DataFrame]:
    """
    Find the paths where the MCS samples should be copied to and the associated runfiles.csv rows.

    Args:
        sw_name (str): The name of the switch being sampled.
        sw_assignments (list): The assignments for the switch.
        runfiles (pd.DataFrame): The runfiles.csv DataFrame.
        reeds_path (str): The path to the ReEDS directory.
        inputs_case (str): The path to the inputs case directory.

    Returns:
        save_path_list: A list of destination paths for the MCS samples.
        runfile_instructions: The runfiles.csv rows associated with the switch.
    """
    # Find if the switch name needs to be assigned to a specific file path in runfiles.csv
    rf_contains_sw = runfiles['filepath'].fillna('').str.contains('{' + sw_name + '}')
    if any(rf_contains_sw):
        runfile_instructions = runfiles[rf_contains_sw].reset_index(drop=True)
    # load files are processed downstream by hourly_load.py and do not have a path 
    # in runfiles so they need special treatment here
    elif sw_name == 'GSw_LoadProfiles':
        runfile_instructions = runfiles[runfiles.filename == 'load.h5'].copy()
        runfile_instructions['filepath'] = 'inputs/profiles_demand/demand_{GSw_LoadProfiles}.h5'
    elif sw_name in MCSConstants.HARD_CODED_SWITCH_TO_FILE_READ:
        # If the switch name is found in the hardcoded exceptions, find the rows 
        # in runfiles.csv that contain all the files associated with the switch.
        runfile_instructions = runfiles[
            runfiles['filename'].isin(MCSConstants.HARD_CODED_SWITCH_TO_FILE_READ[sw_name])
        ].reset_index(drop=True)
    else:
        # If the switch name is not found in runfiles.csv, or in the hardcoded exceptions, 
        # assume it is only part of switches.csv
        print(f'Path to file specified by {sw_name} was not found in runfiles;' 
              ' treating this as a value in switches.csv'
        )
        runfile_instructions = runfiles[runfiles['filename'] == 'switches.csv'].reset_index(drop=True)

    # Reorder rows: if any filename has "supply_curve", place those rows first.
    # For siting data we need to sample the supply curve data first 
    # (CF,... is dependent on the supply curve data)
    if runfile_instructions['filename'].str.contains('supply_curve', na=False).any():
        supply_curve_rows = runfile_instructions[runfile_instructions['filename'].str.contains('supply_curve', na=False)]
        other_rows = runfile_instructions[~runfile_instructions['filename'].str.contains('supply_curve', na=False)]
        runfile_instructions = pd.concat([supply_curve_rows, other_rows], ignore_index=True)

    # Iterate through each instruction to determine the destination paths.
    # Since some switches point to multiple files, you can have multiple destination paths.
    save_path_list = []
    for _, row in runfile_instructions.iterrows():
        file_name = row['filename']
        dest_path = os.path.join(inputs_case, file_name)
        save_path_list.append(dest_path)
    
    # Supply curve files are used in other distributions, so they need to be first in the list.
    # This should be cleaned up.
    if any([os.path.basename(i).startswith('supplycurve') for i in save_path_list]):
        supplycurve_index = [
            i for (i,f) in enumerate(save_path_list)
            if os.path.basename(f).startswith('supplycurve')
        ][0]
        other_indices = [i for i in range(len(save_path_list)) if i != supplycurve_index]
        index_order = [supplycurve_index] + other_indices
        save_path_list = [save_path_list[i] for i in index_order]
        runfile_instructions = runfile_instructions.loc[index_order].reset_index(drop=True)

    return save_path_list, runfile_instructions

def general_mcs_dist_validation(reeds_path: str, mcs_dist_path: str, sw: pd.Series) -> None:
    """
    Validate the contents of mcs_distributions_{MCS_dist}.yaml used for Monte Carlo sampling.
    Distribution validation rules are defined in mcs_distribution_rules.yaml.  
    All violations are collected and raised together in a single ``ValueError`` at the end.

    Args:
        reeds_path (str): Path to the ReEDS directory.
        mcs_dist_path (str): Path to the input .yaml file.
        sw (pd.Series): Case switches.

    Raises:
        ValueError: If any structure or content in the .yaml file is invalid.
    """
    print('Validating the input distribution information for Monte Carlo sampling...')

    # load distribution rules
    rules_path = os.path.join(reeds_path, 'inputs', 'userinput', 'mcs_distribution_rules.yaml')
    with open(rules_path, 'r') as f:
        data = yaml.safe_load(f)
        dist_rules = pd.DataFrame(data).T
    
    # load distribution settings file 
    with open(mcs_dist_path, 'r') as f:
        data = yaml.safe_load(f)
        df_input_dist = pd.DataFrame(data)

    # get relevant switch settings
    mcs_dist_groups = sw['MCS_dist_groups'].split('.')
    sampling_method = 'lhs' if int(sw.MCS_lhs) else 'random'

    ## Verify that all dist group names are unique
    if df_input_dist['name'].nunique() != len(df_input_dist):
        raise ValueError(
            'The distribution names in mcs_distributions.yaml are not unique.'
            'Please correct the file.'
        )

    ## Ensure all MCS_dist_groups options are present, and if so subset
    missing = set(mcs_dist_groups) - set(df_input_dist['name'].unique())
    if missing:
        raise ValueError(
            f"The following MCS_dist_groups switch options are missing in mcs_distributions.yaml {missing}"
        )        
    # subset to groups selected in mcs_dist_groups
    df_input_dist = df_input_dist[df_input_dist['name'].isin(mcs_dist_groups)].reset_index(drop=True)

    ## Validate mandatory keys in df_input_dist
    required_keys = {'name', 'assignments_list', 'dist', 'dist_params', 'weight_r'}
    missing_keys = required_keys - set(df_input_dist.columns)
    if missing_keys:
        raise ValueError(f"Missing mandatory keys in mcs_distributions.yaml object: {missing_keys}")

    ## Make sure that dist_params is a list if required
    bad_params = [
        df_input_dist.at[i, 'name']
        for i in range(len(df_input_dist))
        if 'dist_params' in dist_rules.loc[df_input_dist.at[i, 'dist']]['required_keys']
            and not isinstance(df_input_dist.at[i, 'dist_params'], list)
    ]
    if bad_params:
        raise ValueError(
            f"The dist_params field must be a list for: {bad_params}"
        )

    ## Check for missing data in required columns
    df_supplied = ~df_input_dist.isnull()
    df_required = df_input_dist['dist'].apply(
        lambda d: pd.Series({
            col: col in dist_rules.loc[d, 'required_keys']
            for col in df_input_dist.columns
        })
    )
    missing_data = ~(df_supplied == df_required)
    if missing_data.any().any():
        raise ValueError(
            f"The following dist names have missing data: "
            f"{df_input_dist.loc[missing_data.sum(axis=1) > 0, 'name'].values}. "
            "Make sure you have all mandatory fields in the input distribution file."
        )
    
    ## Extract derived columns for batch checks
    df_input_dist['switch_names'] = df_input_dist['assignments_list'].apply(
        lambda al: [next(iter(d)) for d in al]
    )
    df_input_dist['sw_assignments'] = df_input_dist['assignments_list'].apply(
        lambda al: [next(iter(d.values())) for d in al]
    )
    df_input_dist['num_sw_assignments'] = df_input_dist['sw_assignments'].apply(
        lambda sa: [len(c) for c in sa]
    )

    ## check that all distributions are valid
    valid_distributions = list(dist_rules.index)
    invalid_dists = set(df_input_dist['dist']) - set(valid_distributions)
    if invalid_dists:
        raise ValueError(
            f"The following distributions are not supported: {invalid_dists}. "
            f"Please choose from: {valid_distributions}"
        )

    ## check that all switches are valid  
    cases_default = pd.read_csv(os.path.join(reeds_path, 'cases.csv'))
    valid_switches = set(cases_default.iloc[:, 0].values)
    all_switch_names = {
        sw_name
        for switch_list in df_input_dist['switch_names']
        for sw_name in switch_list
    }
    invalid_switches = all_switch_names - valid_switches
    if invalid_switches:
        raise ValueError(
            f"The following switches are not valid (check cases.csv): {invalid_switches}"
        )

    ## sampling using siting switches is currently disabled
    siting_set = set(MCSConstants.SITING_SWITCHES)
    used_siting = all_switch_names & siting_set
    if used_siting:
        raise ValueError(
            f"Sampling using siting switches {MCSConstants.SITING_SWITCHES} is "
            "currently disabled. For details see "
            "https://github.com/ReEDS-Model/ReEDS/issues/41."
        )

    ## siting switches can only use specific distributions
    for _, row in df_input_dist.iterrows():
        if set(row['switch_names']) & siting_set:
            if row['dist'] not in ['dirichlet', 'discrete']:
                raise ValueError(
                    f"[{row['name']}] Siting switches can only be sampled "
                    "using a dirichlet or discrete distribution."
                )

    ## check that all distributions are compatible with selected sampling method
    unsupported_sampling = dist_rules.loc[
        df_input_dist.dist.unique(), 'sampling_methods'].apply(lambda x: sampling_method not in x)
    if unsupported_sampling.any():
        unsupported_dists = list(unsupported_sampling[unsupported_sampling].index)
        unsupported_sampling_entries = list(df_input_dist.loc[df_input_dist.dist.isin(unsupported_dists), 'name'])
        raise ValueError(
            f"{sampling_method} not support with the following distributions: "
            f"{unsupported_dists}. Adjust the distribution choices for {unsupported_sampling_entries} "
            "or change the sampling method set by 'MCS_lhs'."
        )

    ## regional sampling currently only supported with random sampling method
    regional_rows = df_input_dist.loc[df_input_dist.weight_r != 'country']
    if sampling_method == 'lhs' and len(regional_rows) > 0:
        raise ValueError(
            "Latin hypercube sampling not supported for regional-level sampling. "
            f"Adjust the sampling choice for {df_input_dist['name'].to_list()} or set 'MCS_lhs=0'."
        )

    ## validate assignments_list structure (each item: single-key dict -> list)
    for _, row in df_input_dist.iterrows():
        for d in row['assignments_list']:
            if not (isinstance(d, dict) and len(d) == 1):
                raise ValueError(
                    f"[{row['name']}] Each item in assignments_list must be a "
                    "single-key dictionary."
                )
            val = next(iter(d.values()))
            if not isinstance(val, list):
                raise ValueError(
                    f"[{row['name']}] The value in each assignments_list "
                    "dictionary must be a list."
                )

    ## check switch assignment and number of distribution parameters
    for i, sample_group in df_input_dist.iterrows():
        assignment_rule = dist_rules.loc[sample_group['dist'],'num_assignments']
        n_params = len(sample_group['dist_params']) if isinstance(sample_group['dist_params'], list) else None
        n_sw_assignments = [len(c) for c in sample_group['sw_assignments']]

        if assignment_rule == 'match_dist_params':
            # rules for distributions that match switch and dist_params
            if len(set(n_sw_assignments)) != 1 or n_sw_assignments[0] != n_params:
                raise ValueError(
                        f"{sample_group['dist']} for {sample_group['name']} requires the same "
                        f"number of switch assignments and distribution parameters "
                )
        else:
            # multiplicative distribution rules
            if dist_rules.loc[sample_group['dist'],'multiplicative']:
                if n_params != assignment_rule:
                    raise ValueError(
                        f"{sample_group['dist']} for {sample_group['name']} requires "
                        f"{assignment_rule} entries for 'dist_params'."
                    )
                num_files = np.max(n_sw_assignments) 
                if num_files > 1:
                    raise ValueError(
                        f"{sample_group['dist']} for {sample_group['name']} " 
                        "can only have a single reference file/value per switch."
                    )
            else: 
                # other distributions
                if len(set(n_sw_assignments)) != 1 or n_sw_assignments[0] != assignment_rule:
                    raise ValueError(
                        f"{sample_group['dist']} for {sample_group['name']} requires "
                        f"{assignment_rule} entries for each switch assignment."
                    )
    
            
def get_dist_instructions(reeds_path: str, inputs_case: str) -> Tuple[pd.DataFrame, dict]:
    """
    Obtain the instructions to sample the distributions for each switch 
    and organize information to facilitate the Monte Carlo sampling process.

    Args:
        reeds_path (str): The path to the ReEDS directory.
        inputs_case (str): The path to the inputs case directory.

    Returns:
        df_input_dist_ex: A DataFrame with the distribution instructions for each switch.
        aux_files: A dictionary with auxiliary information (mostly used in the copy_files.py module).
    """
    print('Reading the input distribution information for Monte Carlo sampling')

    # Read yaml file with the input distribution information.
    mcs_dist_path = os.path.join(inputs_case, 'mcs_distributions.yaml')
    with open(mcs_dist_path, 'r') as f:
        data = yaml.safe_load(f)
        df_input_dist = pd.DataFrame(data)

    sw = reeds.io.get_switches(inputs_case)
    mcs_dist_groups = sw['MCS_dist_groups'].split('.')

    # Ignore all cases not in mcs_dist_groups
    df_input_dist = df_input_dist[df_input_dist['name'].isin(mcs_dist_groups)].reset_index(drop=True)

    # Expand df_input_dist with new information to facilitate the Monte Carlo sampling process.
    # Sample ID here is used to uniquely identify each sample-process.
    df_input_dist_ex = df_input_dist.copy(deep=True)
    for col in ['Sample_ID', 'switch_names', 'sw_assignments', 'file_names', 'save_paths', 'runfiles_csv']:
        df_input_dist_ex[col] = [[] for _ in range(len(df_input_dist))]

    # Save reeds_path and inputs_case for future use.
    df_input_dist_ex['reeds_path'] = reeds_path
    df_input_dist_ex['inputs_case'] = inputs_case

    agglevel_variables = reeds.spatial.get_agglevel_variables(reeds_path, inputs_case)
    # Read runfiles.csv to get instructions on how files must be copied.
    runfiles, nonregion_files, region_files = copy_files.read_runfiles(
        reeds_path, inputs_case, sw, agglevel_variables)

    ReEDS_resolution = sw['GSw_RegionResolution']
    # Process each distribution instruction.
    for i, input_dist_row in df_input_dist.iterrows():

        # If ReEDS_resolution is aggreg but weight_r is 'ba' change it to aggreg
        if ReEDS_resolution == 'aggreg' and input_dist_row['weight_r'] == 'ba':
            df_input_dist_ex.at[i, 'weight_r'] = 'aggreg'
            print(f"[Warning]: The weight_r for {input_dist_row['name']} was changed to 'aggreg'")

        # Iterate over each switch in the instruction.
        for sw_i, assignments_list in enumerate(input_dist_row['assignments_list']):

            sw_name, sw_assignments = next(iter(assignments_list.items()))

            filepaths, runfiles_csv = mcs_find_copy_paths(
                sw_name, sw_assignments, runfiles, reeds_path, inputs_case
            )

            # handle cases where a single switch assignment is associated with multiple files and cases
            # related to switches.csv, where multiple float switches may be associated with the same file.
            for j in range(len(filepaths)):
                file_name = runfiles_csv.iloc[j]['filename']
                df_input_dist_ex.at[i, 'switch_names'].append(sw_name)
                df_input_dist_ex.at[i, 'sw_assignments'].append(sw_assignments)
                df_input_dist_ex.at[i, 'save_paths'].append(filepaths[j])
                df_input_dist_ex.at[i, 'runfiles_csv'].append(runfiles_csv.iloc[j])
                df_input_dist_ex.at[i, 'file_names'].append(runfiles_csv.iloc[j]['filename'])

                if file_name != 'switches.csv':
                    df_input_dist_ex.at[i, 'Sample_ID'].append(f'{file_name}')
                else:
                    df_input_dist_ex.at[i, 'Sample_ID'].append(f'{sw_name}')

    # Obtain the data used by copy_files.py to filter regions and create tailored dataframes.
    regions_and_agglevel = copy_files.get_regions_and_agglevel(
        reeds_path, inputs_case, save_regions_and_agglevel=False, overwrite=True)

    source_deflator_map = copy_files.get_source_deflator_map(reeds_path)

    hierarchy_file = get_hierarchy_file(inputs_case, sw['GSw_RegionResolution'])

    # Save the auxiliary info in a dictionary.
    aux_files = {
        'sw': sw,
        'nonregion_files': nonregion_files,
        'region_files': region_files,
        'source_deflator_map': source_deflator_map,
        'regions_and_agglevel': regions_and_agglevel,
        'agglevel_variables': agglevel_variables,
        'hierarchy_file': hierarchy_file,
    }

    return df_input_dist_ex, aux_files


#%% ===========================================================================
### --- WEIGHT CALCULATION ---
### ===========================================================================
def get_region_weights(distribution: str, dist_params: list) -> np.ndarray:
    """
    Generate weights for a single region based on the assigned distribution.

    Args:
        distribution (str): The distribution to use for sampling.
        dist_params (list): The parameters for the distribution.

    Returns:
        np.ndarray: The weights for the region-based sample ([n_samples, n_ref_files|values]).
    """
    # since we're only sample for a single ReEDS run, we only need to sample once
    n_samples_weight = 1

    if distribution == "dirichlet":
        r_weights = np.random.dirichlet(dist_params, n_samples_weight)
    elif distribution == "discrete":
        prob = np.array(dist_params) / np.sum(dist_params)
        sampled_index = np.random.choice(len(dist_params), n_samples_weight, p=prob)[0]
        r_weights = np.zeros(len(dist_params), dtype=int)
        r_weights[sampled_index] = 1
    elif distribution == "uniform_multiplier":
        r_weights = np.random.uniform(dist_params[0], dist_params[1], n_samples_weight)
    elif distribution == "triangular_multiplier":
        r_weights = np.random.triangular(dist_params[0], dist_params[1], dist_params[2], n_samples_weight)

    # convert to 1D array 
    if r_weights.ndim > 1:
        r_weights = r_weights[0,:]

    return r_weights


def get_all_region_weights(
    distribution: str,
    dist_params: list,
    hierarchy_file: pd.DataFrame,
    sample_hierarchy_lvl: str = 'country',
) -> dict:
    """
    Get the weights for all unique regions in sample_hierarchy_lvl and map them to the
    relevant BAs and cendivs, levels. Those may be adjusted later for supply curve files
    (in this case they may be combined with capacity data)

    Args:
        distribution (str): The distribution to use for sampling.
        dist_params (list): The parameters for the distribution.
        hierarchy_file (pd.DataFrame): DataFrame with the hierarchy information from get_hierarchy_file (.)
        sample_hierarchy_lvl (str): The hierarchy level which will be assigned unique weights.

    Returns:
        dict: Dictionary with the weights for each region.
    """

    # Only needs to map weights to 'ba', and 'cendiv'
    # levels since these are the only levels relevant to the files changed in the mcs sampling
    all_r_weights = {} 
    unique_sample_levels = hierarchy_file[sample_hierarchy_lvl].unique()

    for region in unique_sample_levels:
        # Generate region weights based on the specified distribution
        r_weights = get_region_weights(distribution, dist_params)

        # Retrieve all BAs linked to the current region
        bas = hierarchy_file.loc[hierarchy_file[sample_hierarchy_lvl] == region, "ba"].values

        # Assign weights to each BA, cendiv, and aggreg
        for ba in bas:
            all_r_weights[ba] = r_weights

        # Natural gas fuel prices are at the census division level, so save the cendiv weights 
        # if the sample_hierarchy_lvl is 'country' or 'cendiv'
        if sample_hierarchy_lvl in ["country", "cendiv"]:
            cendivs = hierarchy_file.loc[hierarchy_file[sample_hierarchy_lvl] == region, "cendiv"].unique()
            for cendiv in cendivs:
                all_r_weights[cendiv] = r_weights
        # Load data is at the state level, so save the state weights if
        # the sample_hierarchy_lvl is 'st'
        elif sample_hierarchy_lvl == "st":
            all_r_weights[region] = r_weights

    return all_r_weights


class WeightCalculator:
    """
    Computes region-based weights for Monte Carlo Sampling in ReEDS.

    Args:
        sample_group (pd.Series): a series with information about the sample group - from get_dist_instructions(.).
            This contains the distribution, dist_params, switch_names, sw_assignments, file_names, save_paths, ...
            It is a row of the df_input_dist_ex DataFrame.
        aux_files (dict): Dictionary with auxiliary information - from get_dist_instructions (.)
    """
    def __init__(
        self,
        sample_group: pd.Series,
        aux_files: dict,
    ):
        self.sample_group = sample_group
        self.aux_files = aux_files
        self.distribution = sample_group['dist']
        self.dist_params = sample_group['dist_params']
        self.sample_hierarchy_lvl = sample_group['weight_r'].lower()
        self.hierarchy_file = aux_files['hierarchy_file']

        # Get all general region weights
        self.r_weights = get_all_region_weights(
            self.distribution, self.dist_params, self.hierarchy_file, self.sample_hierarchy_lvl)
        ## Include aggregated region weights
        if aux_files['sw']['GSw_RegionResolution'] == 'aggreg':
            self.r_weights = {
                **self.r_weights,
                **{
                    aux_files['hierarchy_file'].set_index('ba').aggreg.get(k,k): v
                    for k,v in self.r_weights.items()
                },
            }

        # Store the weights for the recf files (CF files)
        # Those are computed during the the supply curve file sampling 
        self.recf_weights_map = {}

        # Flag to validate that recf_weights_map was normalized
        self.flag_recf_normalization = defaultdict(lambda: False)

    def _validate_inputs(self, dist_files: list, sw_name: str, file_name: str) -> None:
        """
        Validate inputs

        Args:
            dist_files (list of pd.DataFrame): List of reference dataframes (ajusted to have the same # of rows)
            sw_name (str): Name of the switch we are getting the weights for.
            file_name (str): Name of the file we are getting the weights for.
        """
        # Identify relevant columns that exist in the hierarchy
        #Examples: p1, p2, New_England, ...(covers NG and LOAD)
        columns_in_hierarchy = [col for col in dist_files[0].keys() if col in set(self.r_weights.keys())]

        # Columns that start with region, r, ...
        generic_region_columns = [col for col in dist_files[0].keys() if col in MCSConstants.REGION_SYNONYMS]

        # We have as many unique weights as len(unique_sample_levels)
        unique_sample_levels = self.hierarchy_file[self.sample_hierarchy_lvl].unique()
        single_r_weight = len(unique_sample_levels) == 1

        # Group files that require special treatment
        except_files = MCSConstants.SUPPLY_CURVE_FILES + MCSConstants.EXOG_CAP_FILES + (
            MCSConstants.PRESCRIBED_BUILDS_FILES + MCSConstants.RECF_FILES)

        # Return an error if you have multiple weight assignments but the mcs_distributions.yaml object is
        # pointing to a set of switches that have no region columns
        # e.g. asking for a region-based sampling for swicthes.csv, or plantchar type files.
        if not single_r_weight and not columns_in_hierarchy and not generic_region_columns and ( 
            file_name not in except_files):
            raise ValueError(
                f"Invalid sampling configuration for file: {file_name}\n"
                f"Switch: {sw_name}\n"
                f"weight_r group: {self.sample_hierarchy_lvl}\n"
                "[Error] Either:\n"
                "  1. The file does not contain any regional columns but was assigned"
                " to a region-based sampling group different than country, or\n"
                "  2. The selected weight_r resolution is not valid for this file"
                " (e.g., BA for NG fuel prices, which are based on cendiv).\n\n"
                "Please review the `mcs_distributions.yaml` configuration."
            )

        # Check if all elements in dist_files have the same index
        if not all(df.index.equals(dist_files[0].index) for df in dist_files):
            raise ValueError(
                f"Invalid sampling configuration for file: {file_name}\n"
                f"Switch: {sw_name}\n"
                "All reference files must have the same indexes"
            )

        # Check if the distribution is multiplicative and the file has a year column
        if self.distribution in MCSConstants.MULTIPLICATIVE_DISTRIBUTIONS:
            if dist_files[0].columns.isin(MCSConstants.YEAR_SYNONYMS).any():
                raise ValueError(
                    "Files with year columns are not supported for multiplicative distributions. "
                    f"Change the distribution for switch {sw_name}"
                )

    def get_df_weights(
        self,
        dist_files: list,
        modifiable_columns: list,
        sw_name: str,
        file_name: str,
    ) -> dict:
        """
        Dispatch to the appropriate method based on file type.

        Args:
            dist_files (list of pd.DataFrame): List of reference dataframes (ajusted to have the same # of rows)
            modifiable_columns (list of str): List of columns that can be directly multiplied by the weights.
            sw_name (str): Name of the switch we are getting the weights for.
            file_name (str): Name of the file we are getting the weights for.

        Returns:
            Dict[int, pd.DataFrame | float]: Dictionary mapping reference file index to
                the weight values for that file.
        """

        self._validate_inputs(dist_files, sw_name, file_name)

        if file_name in MCSConstants.SUPPLY_CURVE_FILES:
            return self._get_weights_supply_curve(dist_files, modifiable_columns, sw_name)
        elif file_name in MCSConstants.RECF_FILES:
            return self._get_weights_recf(sw_name)
        elif file_name in MCSConstants.EXOG_CAP_FILES + MCSConstants.PRESCRIBED_BUILDS_FILES:
            return self._get_weights_exog_prescribed(dist_files)
        else:
            return self._get_weights_general(dist_files, modifiable_columns, sw_name, file_name)

    def _get_weights_general(
        self,
        dist_files: list,
        modifiable_columns: list,
        sw_name: str,
        file_name: str
    ) -> dict:  
        """
        Get weights for a general file that does not require special treatment.
        Files that require special treatment are those associated with 
        supply curve switches.

        Args:
            dist_files (list of pd.DataFrame): List of reference dataframes (ajusted to have the same # of rows)
            modifiable_columns (list of str): List of columns that can be directly multiplied by the weights.
            sw_name (str): Name of the switch we are getting the weights for.
            file_name (str): Name of the file we are getting the weights for.

        Returns:
            Dict[int, pd.DataFrame | float]: Dictionary mapping reference file index to
                the weight values for that file.
        """
        # Number of reference files/values. Since all sw_assignments
        # have the same number of files, we can use the first one.
        n_files = len(self.sample_group["sw_assignments"][0]) 

        # Identify relevant columns that exist in the hierarchy
        #Examples: p1, p2, New_England, ME ...(covers NG and LOAD)
        columns_in_hierarchy = [col for col in dist_files[0].keys() if col in set(self.r_weights.keys())]

        # load files are subsetted to the relevant regions later in hourly_load.py, 
        # so here we add placeholder weights for any states not being modeled
        if file_name == 'load.h5':
            columns_other_states = [col for col in dist_files[0].keys() if col not in columns_in_hierarchy]
            if len(columns_other_states) > 0:
                # get the first entry of the regional weights as a placeholder
                first_region = list(self.r_weights)[0]
                generic_weight_matrix = self.r_weights[first_region]
                generic_weights = dict.fromkeys(columns_other_states, generic_weight_matrix)
                self.r_weights.update(generic_weights)
                columns_in_hierarchy = columns_in_hierarchy + columns_other_states


        # We have as many unique weights as len(unique_sample_levels)
        unique_sample_levels = self.hierarchy_file[self.sample_hierarchy_lvl].unique()
        single_r_weight = len(unique_sample_levels) == 1

        # Dictionary to store computed weights for the modifiable columns
        # file -> pd.DataFrame
        dict_df_weights = {}

        # Handle the simple case where there is only one weight for all regions 
        # (or no regions). 
        if single_r_weight:
            # Get the first region key
            first_region = list(self.r_weights)[0]
            weight_matrix = self.r_weights[first_region]

            if file_name == "switches.csv":
                for f in range(n_files):
                    dict_df_weights[f] = weight_matrix[f]
            else:
                for f in range(n_files):
                    dict_df_weights[f] = pd.DataFrame(
                            data=weight_matrix[f],
                            columns=modifiable_columns,
                            index=dist_files[0].index,
                    )

        # Cases that have regional columns from columns_in_hierarchy
        # and the weights are not the same for all regions
        elif not single_r_weight and len(columns_in_hierarchy) and file_name != "switches.csv" :
            for f in range(n_files):

                w_df_tmp = pd.DataFrame(
                    {col: self.r_weights[col][f] for col in columns_in_hierarchy},  
                    index=dist_files[0].index 
                )

                dict_df_weights[f] = w_df_tmp

        return dict_df_weights

    def _get_weights_supply_curve(
        self,
        dist_files: list,
        modifiable_columns: list,
        sw_name: str
    ) -> dict:
        """
        Get the weights for supply curve files. These files require special treatment
        because some columns are dependent on the capacity of each sc_point_gid.

        Args:
            dist_files (list of pd.DataFrame): List of reference dataframes (ajusted to have the same # of rows)
            modifiable_columns (list of str): List of columns that can be directly multiplied by the weights.
            sw_name (str): Name of the switch we are getting the weights for.

        Returns:
            Dict[int, pd.DataFrame]: Dictionary mapping reference file index to
                the weight DataFrame for that file.
        """
        # Dictionary to store computed weights for the modifiable columns
        # file index -> pd.DataFrame
        dict_df_weights = {}

        # Store weights to use later in the recf files (CF files)
        self.recf_weights_map[sw_name] = {}

        # Create a new column with the class|region combination (like in the CF file)
        dist_files_copy = [copy.deepcopy(df) for df in dist_files] 

        for df in dist_files_copy:
            df["old c|r"] = (
                df["class"].astype(int).astype(str) + "|" + df["region"].astype(str)
            )

        for f, df in enumerate(dist_files_copy):
            # Initial skeleton of the weights DataFrame
            w_df_tmp = df[["region", "sc_point_gid", "old c|r"]]

            # Create a mapping from each unique region to its corresponding weight
            region_to_weight = {
                r: self.r_weights[r][f]
                for r in w_df_tmp["region"].unique()
            }

            # Compute the region weights for each row
            region_weights = w_df_tmp["region"].map(region_to_weight).values

            # Build a new DataFrame for the modifiable columns using a dict comprehension.
            # For "capacity", we assign the raw region weight; for others, multiply by capacity.
            modifiable_df = pd.DataFrame({
                col: (region_weights if col == "capacity" else region_weights * df["capacity"])
                for col in modifiable_columns
            }, index=w_df_tmp.index)

            # Join the modifiable columns back into the original DataFrame
            w_df_tmp = w_df_tmp.join(modifiable_df)

            # Save the intermediate weights for the recf files (These are weights multiplied by capacity)
            self.recf_weights_map[sw_name][f] = w_df_tmp[["old c|r","class"]].rename(columns={"class": "weight"})

            # Store in dictionary
            dict_df_weights[f] = w_df_tmp.drop(columns=["old c|r"])

            # Normalize the weights to sum to 1
            # Divide the weights by the sum of the weights across all files
            sum_weights = sum(dict_df_weights[f][modifiable_columns] for f in range(len(dist_files)))
            sum_weights[sum_weights == 0] = 1

            for f in range(len(dist_files)):
                dict_df_weights[f][modifiable_columns] /= sum_weights
                # recf_weights_map is not normalized here because it will be normalized later
                # values need to be aggregated according to the new c|r column from supply curves

        return dict_df_weights

    def _get_weights_exog_prescribed(self, dist_files: list) -> dict:
        """
        Get the weights for exogenous capacity and prescribed builds files.

        Args:
            dist_files (list of pd.DataFrame): List of reference dataframes (ajusted to have the same # of rows)

        Returns:
            Dict[int, pd.DataFrame]: Dictionary mapping reference file index to
                the weight DataFrame for that file.
        """
        dict_df_weights = {}
        for f, df in enumerate(dist_files):

            region_to_weight = {
                r: self.r_weights[r][f]
                for r in df["region"].unique()
            }

            dict_df_weights[f] = pd.DataFrame(
                data=df["region"].map(region_to_weight).values,
                columns=["capacity"],
                index=df.index,
            )

        return dict_df_weights

    def _get_weights_recf(self, sw_name: str) -> dict:
        """
        Get the weights for the recf files (CF files). This file construction is 
        dependent on the new supply curve samples and therefore is computed after
        the supply curve files are sampled.

        Args:
            sw_name (str): Name of the switch we are getting the weights for.
        """
        # From get_dist_instructions(.) the supply curve file is deliberaly
        # placed before the recf files, so that recf_weights_map is already populated.

        # Check if recf_weights_map is not empty and that it was normalized.
        if not self.recf_weights_map[sw_name]:
            raise ValueError(
                f"The recf_weights_map for switch {sw_name} was not populated"
            )

        if not self.flag_recf_normalization[sw_name] :
            raise ValueError(
                f"The recf_weights_map for switch {sw_name} was not normalized"
            )

        return self.recf_weights_map[sw_name]

    def normalize_recf_weights_map(self, samples_sw: pd.DataFrame, sw_name: str) -> None:
        """
        The recf map is responsible for informing how the old class/region data files
        need to be put together (weights) to form the new class/region data.
        After creating the new supply curve sample, we normalize the weights to sum to 1.

        Args:
            samples_sw (pd.DataFrame): The sampled supply curve DataFrame.
            sw_name (str): Name of the switch being sampled.

        Updates:
            self.recf_weights_map (dict): Dictionary with the normalized weights for the recf files.
                Each element of this dictionary is a pd.DataFrame (for the reference file f)
                with the normalized weights, indexed by new and old class|region (c|r).
        """
        n_files = len({key[1] for key in self.recf_weights_map[sw_name].keys()})

        # The normalization can change depending on the sample #
        for f in range(n_files):
            # Add a new column with the new class|region combination
            self.recf_weights_map[sw_name][f]["new c|r"] = (
                samples_sw["class"].astype(str) + "|" +
                samples_sw["region"].astype(str)
            )

            # Sum the weights for each new class|region combination
            self.recf_weights_map[sw_name][f] = self.recf_weights_map[sw_name][f].groupby(
                ["new c|r","old c|r"], as_index=False).sum()

            # Remove cases with 0 weight (e.g  old c|r had no capacity -> class 0)
            self.recf_weights_map[sw_name][f] = self.recf_weights_map[sw_name][f][
                self.recf_weights_map[sw_name][f]["weight"] > 0
            ]

        # Go over all files and obtain the total sum of weights for each new class|region
        sum_weights_recf_map = (
            pd.concat(
                [self.recf_weights_map[sw_name][f] for f in range(n_files)]
            )
            .groupby("new c|r")["weight"]
            .sum()
            .to_dict()
        )

        for f in range(n_files):
            # Get current DataFrame
            df = self.recf_weights_map[sw_name][f]
            # Perform division using "new c|r" as the reference
            df["weight"] = df["weight"] / df["new c|r"].map(sum_weights_recf_map)
            # Assign back to original structure
            self.recf_weights_map[sw_name][f] = df.set_index(["new c|r", "old c|r"])   

        # Flag to validade that recf_weights_map was normalized
        self.flag_recf_normalization[sw_name] = True 


#%% ===========================================================================
### --- MAIN SAMPLING CLASS ---
### ===========================================================================
class MCS_Sampler:
    """
    Monte Carlo Sampling Distribution Manager for ReEDS.

    This class allows enforcing sampling variability at different ReEDS regions
    (st, ba, ...) and enforcing correlation between samples from different switches.

    See distribution options listed in /inputs/userinput/mcs_distribution_rules.yaml

    """
    def __init__(self, sample_group, aux_files, n_samples, mcs_run_number, lhs_samples=None):
        self.sample_group = sample_group
        self.aux_files = aux_files
        self.n_samples = n_samples

        # sampling method (random or latin hypercube)
        if lhs_samples is None:
            self.sampling_method = 'random'
        else:
            self.sampling_method = 'latin hypercube'
            self.lhs_samples = lhs_samples
            # for each ReEDS run the sample id corresponds to the run number (-1 for 0 index)
            self.sample_num = mcs_run_number - 1

        # Derive parameters from inputs
        self.reeds_path = sample_group['reeds_path']
        self.inputs_case = sample_group['inputs_case']
        self.distribution = sample_group['dist']
        self.dist_params = sample_group['dist_params']
        self.ReEDS_resolution = aux_files['sw']['GSw_RegionResolution']
        if self.ReEDS_resolution=='aggreg' and sample_group['weight_r']=='ba':
            self.sample_hierarchy_lvl = 'aggreg'
        else:
            self.sample_hierarchy_lvl = sample_group['weight_r']

        # Inputs that require special treatment
        self.hierarchy_file = get_hierarchy_file(self.inputs_case, self.ReEDS_resolution)

        # Store the samples for each switch (a single sw may have multiple files that is
        # why we refer to the switch by its adjusted name)
        self.samples = {sw_name: [] for sw_name in self.sample_group['Sample_ID']}

    @staticmethod
    def prepare_ref_data(
        dist_files: list,
        file_name: str,
        sw_name: str | list,
        aux_files,
    ) -> Tuple[list, list, dict]:
        """
        This function prepares the reference dataframes for the Monte Carlo sampling.
        For some files like those related to supply curves we need to expand/modify
        the reference files to include additional rows/columns. 

        Args:
            dist_files (list of pd.DataFrame): List of reference dataframes to be modified.
            file_name (str): name given by reeds to the files in dist_files.
            sw_name (str or list): Name of the switch being sampled. For the special case
                of float switches, this will be a list of switch names.

        Returns:
            list of pd.DataFrame: List of modified reference dataframes.
            list of str: List of columns that can be directly multiplied by the weights.
            dict: Dictionary with the number of decimal places for columns we will modify
        """
        ### ===========================================================================
        ### --- Expand dist_files if necessary ---
        ### ===========================================================================
        # For each file map the columns we need to verify in the df expansion
        # (e.g For the supply curves we will make sure that all files are
        # ajusted to contain all regions and sc_point_gid combinations)
        map_files2ref_columns = {
            **{file: ["region", "sc_point_gid"] for file in MCSConstants.SUPPLY_CURVE_FILES},
            **{file: ["region", "year", "sc_point_gid"] for file in MCSConstants.EXOG_CAP_FILES},
            **{file: ["region", "year"] for file in MCSConstants.PRESCRIBED_BUILDS_FILES},
        }

        if file_name in map_files2ref_columns:
            ref_columns = map_files2ref_columns[file_name]

            # Get all unique combination for the reference columns
            unique_reg_gid_point = pd.concat(
                [df[ref_columns] for df in dist_files],
                ignore_index=True
            ).drop_duplicates().reset_index(drop=True)

            # Modify dfs in the dist_files list adding missing ref_columns combinations
            # and initializing the modifiable rows with 0
            for i, df in enumerate(dist_files):
                dist_files[i] = unique_reg_gid_point.merge(
                    df.reset_index(drop=True),
                    on=ref_columns,
                    how="left",
                ).fillna(0).sort_values(by=ref_columns).reset_index(drop=True)

        ### ===========================================================================
        ### --- Get a list of the columns we are allowed to apply weights directly ---
        ### ===========================================================================
        # Get the base set of general (modifiable) columns from dist_files[0]
        general_mult_columns = {
            col for col in dist_files[0].keys() if col not in MCSConstants.FIXED_COLUMN_NAMES
        }

        # Ensure all dist_files have the same set of general columns
        if file_name not in MCSConstants.RECF_FILES:
            for i, df in enumerate(dist_files[1:], start=1):
                current_cols = {col for col in df.keys() if col not in MCSConstants.FIXED_COLUMN_NAMES}
                if current_cols != general_mult_columns:
                    error_msg = (
                        f"Column mismatch between dist_files[0] and dist_files[i]:\n"
                        "This usually happens when you run MCS on a file whose columns "
                        "vary by switch assignment (e.g. RECF_FILES).\n If you really need to support "
                        f"'{file_name}' here, add the necessary handling in prepare_ref_data()."
                    )
                    raise ValueError(error_msg)

        exceptions_mult_col = {
            **{file: ["class"] + list(general_mult_columns) for file in MCSConstants.SUPPLY_CURVE_FILES},
            **{file: ["capacity"] for file in MCSConstants.EXOG_CAP_FILES},
            **{file: ["capacity"] for file in MCSConstants.PRESCRIBED_BUILDS_FILES},
            **{file: [] for file in MCSConstants.RECF_FILES}, # treated separately
        }
        modifiable_columns = exceptions_mult_col.get(file_name, list(general_mult_columns))

        ### ===========================================================================
        ### --- Map for the number of decimals in each column we will change
        ### ===========================================================================
        if file_name in ["switches.csv"]:
            n_decimals = max_decimal_places(dist_files[0].loc[sw_name,1])
        else:
            n_decimals_list = [
                max_decimal_places(df[modifiable_columns]) for df in dist_files
            ]

            # Take the max decimal count per column across all files, capped at 6
            n_decimals = {
                col: min(max(d[col] for d in n_decimals_list), 6)
                for col in n_decimals_list[0]
            }

        return dist_files, modifiable_columns, n_decimals

    def load_ref_files(self, sample_idx: int) -> List[pd.DataFrame]:
        """
        Load the reference files associated with the sample.

        Args:
            sample_idx (int): Index of the Sample_ID in sample_group.
            Some switches have multiple files associated with them that is why we
            track samples using Sample_ID in the sample_group.

        Returns:
            List[pd.DataFrame]: List of DataFrames with the switch files.
        """

        sw_name = self.sample_group['switch_names'][sample_idx]

        # Create a list of dataframes with the data related to the switch
        dist_files = []

        for sw_assignment in self.sample_group['sw_assignments'][sample_idx]:

            sw_runfiles_csv = self.sample_group['runfiles_csv'][sample_idx].copy(deep=True)
            sw_runfiles_csv['sw_assignment'] = sw_assignment

            if not pd.isna(sw_runfiles_csv['filepath']):
                sw_runfiles_csv['full_filepath'] = os.path.join(
                    self.reeds_path,
                    sw_runfiles_csv['filepath'].replace(f'{{{sw_name}}}', sw_assignment),
                )

            df = read_csv_h5_file(sw_runfiles_csv, self.aux_files, self.reeds_path, self.inputs_case)
            dist_files.append(df)

        return dist_files

    # ----------------------- Weight Application Helpers -----------------------
    def _adjust_supply_curve_sample(self, samples_sw: pd.DataFrame, sw_name: str, sample_idx: int) -> pd.DataFrame:
        """
        Adjust samples for supply curve files:
          - Convert the 'class' column to integers.
          - Normalize the weights map.
          - Remove rows with no capacity.

        Args:
            samples_sw (pd.DataFrame): The sampled supply curve DataFrame.
            sw_name (str): Name of the switch being sampled.
            sample_idx (int): Index of the Sample_ID in sample_group.

        Returns:
            pd.DataFrame: Adjusted supply curve sample.
        """

        # Convert class to integer
        samples_sw["class"] = samples_sw["class"].astype(int)

        # Update the recf weights map (weight_calc.recf_weights_map)
        self.weight_calc.normalize_recf_weights_map(samples_sw, sw_name)

        # Remove samples with no capacity. 
        # Need to do this after normalizing the recf weights
        samples_sw = samples_sw[samples_sw["capacity"] > 0]
        
        return samples_sw

    def _adjust_exog_cap_samples(self, samples_sw: pd.DataFrame, file_name: str) -> pd.DataFrame:
        """
        Adjust samples for exogenous capacity files:
          - Remove rows with no capacity.
          - Adjust the tech classes based on available classes per sc_point_gid.

        Args:
            samples_sw (pd.DataFrame): The sampled exogenous capacity DataFrame.
            file_name (str): Name of the file being sampled.

        Returns:
            pd.DataFrame: Adjusted exogenous capacity sample.
        """
        # Remove samples with no capacity
        samples_sw = samples_sw[samples_sw["capacity"] > 0].copy()

        tech_mapping = {
            "exog_cap_upv.csv": ("upv", "supplycurve_upv.csv"),
            "exog_cap_wind-ons.csv": ("wind-ons", "supplycurve_wind-ons.csv"),
        }
        tech_name, Sample_ID = tech_mapping[file_name]

        # Get the class available for each sc_point_gid
        class_sc_point_map = self.samples[Sample_ID][["sc_point_gid", "class"]]
        class_sc_point_map = class_sc_point_map.set_index("sc_point_gid").to_dict()["class"]

        # Remove any rows from samples_sw that cannot be mapped
        # These are cases with zero supply in the region
        valid_sc_point_gids = samples_sw["sc_point_gid"].isin(class_sc_point_map.keys())
        samples_sw = samples_sw[valid_sc_point_gids].copy()

        # Create a new tech name for each sc_point_gid
        new_tech_name = [tech_name + "_" + str(int(c)) for c in 
            samples_sw["sc_point_gid"].map(class_sc_point_map).values]

        samples_sw["*tech"] = new_tech_name

        return samples_sw

    def _apply_weights_general(
        self,
        dist_files: list,
        modifiable_columns: list,
        n_decimals: dict|int,
        dict_df_weights: dict,
        sample_idx: int
    ):
        """
        Apply the distribution weights to the reference files. 
        Applicable to all cases but recf files and switches.csv.

        Args:
            dist_files (List[pd.DataFrame]): List of input DataFrames for sampling.
            modifiable_columns (List[str]): List of columns that can be directly multiplied by the weights.
            n_decimals (Dict[str, int]): Dictionary with the number of decimal places for each column.
            dict_df_weights (Dict[int, pd.DataFrame]): Dictionary mapping reference file index to
                the weight DataFrame for that file.
            sample_idx (int): Index of the Sample_ID in sample_group.

        Update:
            self.samples (Dict[str, pd.DataFrame]): Dictionary with the samples for each switch/file_name.
        """

        Sample_ID = self.sample_group['Sample_ID'][sample_idx]
        sw_name = self.sample_group['switch_names'][sample_idx]
        file_name = self.sample_group["runfiles_csv"][sample_idx]["filename"]

        # Initialize samples with zero values
        samples_sw = dist_files[0].copy()
        # Initialize with zeros
        samples_sw[modifiable_columns] = 0  

        for f, df in enumerate(dist_files):
            samples_sw[modifiable_columns] += df[modifiable_columns] * dict_df_weights[f][modifiable_columns] 
        samples_sw = samples_sw.round(n_decimals)

        if file_name in MCSConstants.SUPPLY_CURVE_FILES:
            adjusted_samples = self._adjust_supply_curve_sample(samples_sw, sw_name, sample_idx)

        elif file_name in MCSConstants.EXOG_CAP_FILES:
            adjusted_samples = self._adjust_exog_cap_samples(samples_sw, file_name)

        elif file_name in MCSConstants.PRESCRIBED_BUILDS_FILES:
            # Remove samples with no capacity
            adjusted_samples = samples_sw[samples_sw["capacity"] > 0]

        else:
            # For all other files we can directly apply the weights
            adjusted_samples = samples_sw

        # Save the adjusted samples.
        self.samples[Sample_ID] = adjusted_samples

    def _apply_weights_recf(
        self,
        dist_files: list,
        sample_idx: int
    ):
        """
        Apply the distribution weights to the recf files.
        This file gets compleatly overwriten so need to be treated separately

        Args:
            dist_files (List[pd.DataFrame]): List of input DataFrames for sampling.
            sample_idx (int): Index of the Sample_ID in sample_group.

        Update:
            self.samples (Dict[str, pd.DataFrame]): Dictionary with the samples for each switch/file_name.
        """

        Sample_ID = self.sample_group['Sample_ID'][sample_idx]
        sw_name = self.sample_group['switch_names'][sample_idx]

        # For the recf files we need to apply the weights to the old class|region combinations
        weights = self.weight_calc.recf_weights_map[sw_name]
        # Index is the same for all files (time)
        indexes = dist_files[0].index 

        # get initial switch values
        sample_sw = defaultdict(int)

        for f, df in enumerate(dist_files):
            # Get the old and new class|region combinations from weights[(s, f)]
            for (new_c_r, old_c_r) in weights[f].index:
                sample_sw[new_c_r] += df[old_c_r] * weights[f].loc[(new_c_r,old_c_r)].values[0]

        # Round numbers to 9 decimal places and allow min/max values of 0 and 1
        for new_c_r in sample_sw.keys():
            sample_sw[new_c_r] = sample_sw[new_c_r].round(9).clip(0,1)

        self.samples[Sample_ID] = pd.DataFrame(sample_sw, index=indexes)

    def _apply_weights_switches_csv(
        self,
        dist_files: list,
        n_decimals: dict,
        dict_df_weights: dict,
        sample_idx: int,
    ):
        """
        Apply the distribution weights to the switches.csv file.

        Args:
            dist_files (List[pd.DataFrame]): List of input DataFrames for sampling.
            n_decimals (Dict[str, int]): Dictionary with the number of decimal places for each column.
            dict_df_weights (Dict[int, float]): Dictionary mapping reference file/assignment index
                to the scalar weight for that assignment.
            sample_idx (int): Index of the Sample_ID in sample_group.

        Update:
            self.samples (Dict[str, str]): Dictionary with the sampled switch value.
        """
        # Switches are saved only for the rows changed because this allow 
        # multiple json objects changing different switches using different distributions

        sw_name = self.sample_group['switch_names'][sample_idx]
        samples_sw = [None for n in range(self.n_samples)]
        sw_assignments = self.sample_group['sw_assignments'][sample_idx]

        for assingment_idx, sw_assignment in enumerate(sw_assignments):

            # The switch assignments case can be a int, a float or a string
            # If it is a str or int it must be used in a discrete distribution
            if isinstance(sw_assignment, (str, int)):
                # Check if we have a discrete distribution
                if self.distribution != "discrete":
                    raise ValueError(
                        f"You specified a str/int assignment for switch '{sw_name}', "
                        "but the distribution is not set to 'discrete'. "
                        "This file is likely hard-coded in `copy_files.py`.\n\n"
                        "To fix this, you can try to:\n"
                        "  - Change the distribution to 'discrete'\n"
                        "  - Use a float assignment instead, or\n"
                        "  - Add support for this switch's files\n\n"
                        "A good place to start is the `read_exception_file()` function."
                    )

                if isinstance(sw_assignment, str) and dict_df_weights[assingment_idx]:
                    # dict_df_weights[s,f] is a one hot encoding of the sw_assignment options
                    samples_sw = sw_assignment

                elif isinstance(sw_assignment, int) and dict_df_weights[assingment_idx]:
                    # dict_df_weights[s,f] is a one hot encoding of the sw_assignment options
                    samples_sw = str(sw_assignment)

            elif isinstance(sw_assignment, float):
                if self.distribution == "discrete":
                    # dict_df_weights[s,f] is a one hot encoding of the sw_assignment options
                    samples_sw = str(sw_assignment)

                elif self.distribution in MCSConstants.MULTIPLICATIVE_DISTRIBUTIONS:
                    # We have a validation process that makes sure that we only have one file
                    samples_sw = (
                        str(np.round(sw_assignment * dict_df_weights[0], n_decimals+1))
                    )
                else:
                    raise ValueError(
                        f"Float assignments can only be used with a discrete or multiplicative distribution. "
                        f"Check the distribution for switch '{sw_name}'."
                    )

        self.samples[sw_name] = samples_sw

    def assign_weight_calculator(self):
        self.weight_calc = WeightCalculator(self.sample_group, self.aux_files)

    def record_group_weights(self, inputs_case: str) -> None:
        """
        Record the weights for each distribution group in 
        inputs_case/mcs_group_weights.csv. Appends to the file if it exists.

        Args:
            mcs_sampler (MCS): The MCS object containing the distribution groups and weights.
            inputs_case (str): Directory where the weights file will be stored.
        """
        save_path = os.path.join(inputs_case, 'mcs_group_weights.csv')
        r_weights = self.weight_calc.r_weights
        group_name = self.sample_group["name"]
        assignments_list = self.sample_group["assignments_list"]

        # Build column names
        columns = ['group_name', 'switch_name', 'sw_assignment', 'r', 'weight']
        data = []

        for switch_idx, switch_dict in enumerate(assignments_list):
            sw_name, sw_assignment = next(iter(switch_dict.items()))
            for r in r_weights.keys():
                for assignment_idx, assignment_value in enumerate(sw_assignment):
                    weight = r_weights[r][assignment_idx]  # column for this switch
                    row = [group_name, sw_name, assignment_value, r, weight]
                    data.append(row)

        weight_record_df = pd.DataFrame(data, columns=columns)

        # drop regionality levels that aren't used
        print(f"recording weights for {sw_name}")
        unique_sample_levels = self.hierarchy_file[self.sample_hierarchy_lvl].unique()
        if self.sample_group.weight_r == 'country':
            weight_record_df['r'] = 'country'
            weight_record_df = weight_record_df.drop_duplicates()
        else:  
            weight_record_df = weight_record_df.loc[weight_record_df.r.isin(unique_sample_levels)]

        # Append if file exists, else write with header
        if os.path.exists(save_path):
            weight_record_df.to_csv(save_path, mode='a', index=False, header=False)
        else:
            weight_record_df.to_csv(save_path, mode='w', index=False, header=True)

    # ----------------------- End of Weight Application Helpers -----------------------

    def sample_lhs_uniform(self, sample_num, dim_num, lower, upper):
        """Draw a sample from a uniform distribution using the LHS quantile matrix.

        Args:
            sample_num (int): Row index into self.lhs_samples for this run.
            dim_num (int): Column index (dimension) into self.lhs_samples for this sample group.
            lower (np.ndarray or float): Lower bound(s) of the uniform distribution.
            upper (np.ndarray or float): Upper bound(s) of the uniform distribution.

        Returns:
            np.ndarray or float: Sampled value(s) from the uniform distribution.
        """
        # check order
        lower_new, upper_new = check_lhs_param_order(lower, upper)
        # set uniform distribution parameters: location (loc) and scale
        unif_loc = lower_new
        unif_scale = upper_new - lower_new
        # extract sample
        lhs_vals = scipy.stats.uniform.ppf(self.lhs_samples[sample_num, dim_num], loc=unif_loc, scale=unif_scale)
        
        return lhs_vals

    def sample_lhs_triangular(self, sample_num, dim_num, lower, mode, upper):
        """Draw a sample from a triangular distribution using the LHS quantile matrix.

        Args:
            sample_num (int): Row index into self.lhs_samples for this run.
            dim_num (int): Column index (dimension) into self.lhs_samples for this sample group.
            lower (np.ndarray or float): Lower bound(s) of the triangular distribution.
            mode (np.ndarray or float): Mode (peak) value(s) of the triangular distribution.
            upper (np.ndarray or float): Upper bound(s) of the triangular distribution.

        Returns:
            np.ndarray or float: Sampled value(s) from the triangular distribution.
        """
        # check order
        lower_new, upper_new = check_lhs_param_order(lower, upper)
        # set triangular distribution parametesr: location (loc), scale, and center (c)
        tri_loc = lower_new
        tri_scale = upper_new - lower_new
        tri_c = (mode - tri_loc) / tri_scale

        # draw lhs samples; 'sample_num' matches the sample row for the relevant ReEDS run and
        # 'dim_num' matches the relevant column for the dimension
        lhs_vals = scipy.stats.triang.ppf(self.lhs_samples[sample_num, dim_num], c=tri_c, loc=tri_loc, scale=tri_scale)
        
        return lhs_vals

    def sample_lhs_discrete(self, sample_num, dim_num):
        """Select a discrete option index using the LHS quantile matrix.

        Uses the distribution parameters as unnormalized probabilities to
        define CDF bins, then maps the LHS quantile to a discrete index.

        Args:
            sample_num (int): Row index into self.lhs_samples for this run.
            dim_num (int): Column index (dimension) into self.lhs_samples for this sample group.

        Returns:
            int: Index of the selected discrete option.
        """
        # normalize probabilities
        probs = np.array(self.sample_group.dist_params) / np.sum(self.sample_group.dist_params)
        # get CDF bins
        bins = np.cumsum(probs)
        # get index of discrete option selected
        lhs_vals = np.array(np.arange(0, len(bins)))[np.digitize(self.lhs_samples[sample_num, dim_num], bins)]

        return lhs_vals

    def apply_lhs_switches_csv(self, sample_group_num, sample_idx, dist_files, n_decimals):
        """Apply LHS sampling to a switches.csv entry.

        Draws a sample for the switch value based on the configured distribution
        and stores the result as a string in self.samples.

        Args:
            sample_group_num (int): Index of the sample group (LHS dimension).
            sample_idx (int): Index of the Sample_ID in sample_group.
            dist_files (List[pd.DataFrame]): Reference DataFrames for the switch.
            n_decimals (int): Number of decimal places for rounding the result.
        """
        sw_name = self.sample_group['switch_names'][sample_idx]
        sw_assignments = self.sample_group['sw_assignments'][sample_idx]

        if self.distribution == "triangular":
            lower, mode, upper = sw_assignments
            # get sample values
            lhs_sw_val = self.sample_lhs_triangular(self.sample_num, sample_group_num, lower, mode, upper)
        elif self.distribution == "triangular_multiplier":
            lower, mode, upper = self.sample_group.dist_params
            # get multipler and apply to switch
            lhs_sw_mult = self.sample_lhs_triangular(self.sample_num, sample_group_num, lower, mode, upper)
            lhs_sw_val = lhs_sw_mult * sw_assignments[0]
        elif self.distribution == "uniform":
            lower, upper = sw_assignments
            # get sample values
            lhs_sw_val = self.sample_lhs_uniform(self.sample_num, sample_group_num, lower, upper)
        elif self.distribution == "uniform_multiplier":
            lower, upper = self.sample_group.dist_params
            # get multipler and apply to switch
            lhs_sw_mult = self.sample_lhs_uniform(self.sample_num, sample_group_num, lower, upper)
            lhs_sw_val = lhs_sw_mult * sw_assignments[0]
        elif self.distribution == "discrete":
            lhs_sw_index = self.sample_lhs_discrete(self.sample_num, sample_group_num)
            lhs_sw_val = sw_assignments[lhs_sw_index]

        # format as a string
        self.samples[sw_name] = str(np.round(lhs_sw_val, n_decimals+1))


    def apply_lhs_general(self, sample_group_num, Sample_ID, dist_files, aux_files, modifiable_columns):
        """Apply LHS sampling to a general (non-switch, non-RECF) file.

        For each modifiable column, draws values from the configured distribution
        using the LHS quantile matrix and stores the resulting DataFrame in self.samples.

        Args:
            sample_group_num (int): Index of the sample group (LHS dimension).
            Sample_ID (str): Identifier for this sample in self.samples.
            dist_files (List[pd.DataFrame]): Reference DataFrames providing distribution bounds.
            aux_files (dict): Auxiliary files dictionary.
            modifiable_columns (List[str]): Columns to sample new values for.
        """
        # set up final data
        samples_sw = dist_files[0].copy()
        # iterate over columns to update with lhs 
        for mod_col in modifiable_columns:
      
            if self.distribution == "triangular":
                # get triangular distribution parameters (ordering checked in sample_lhs_triangular function)
                lower = np.array(dist_files[0][mod_col])
                mode = np.array(dist_files[1][mod_col])
                upper = np.array(dist_files[2][mod_col])                
                # get new values
                lhs_vals = self.sample_lhs_triangular(self.sample_num, sample_group_num, lower, mode, upper)
                # replace file data with with lhs sample values
                # for NA values from sampling (occurs if lower == upper), use existing values file values
                samples_sw[mod_col] = np.where(np.isnan(lhs_vals), samples_sw[mod_col], lhs_vals)
            
            elif self.distribution == "uniform":
                lower = np.array(dist_files[0][mod_col])
                upper = np.array(dist_files[1][mod_col])
                # get new values
                lhs_vals = self.sample_lhs_uniform(self.sample_num, sample_group_num, lower, upper)
                samples_sw[mod_col] = np.where(np.isnan(lhs_vals), samples_sw[mod_col], lhs_vals)

            elif self.distribution == "discrete":
                lhs_index = self.sample_lhs_discrete(self.sample_num, sample_group_num)
                samples_sw[mod_col] = dist_files[lhs_index][mod_col]

            elif self.distribution == "uniform_multiplier":
                lower = np.array(dist_files[0][mod_col]) * self.dist_params[0]
                upper = np.array(dist_files[0][mod_col]) * self.dist_params[1]
                # get new values
                lhs_vals = self.sample_lhs_uniform(self.sample_num, sample_group_num, lower, upper)
                samples_sw[mod_col] = np.where(np.isnan(lhs_vals), samples_sw[mod_col], lhs_vals)

            elif self.distribution == "triangular_multiplier":
                lower = np.array(dist_files[0][mod_col]) * self.dist_params[0]
                mode = np.array(dist_files[0][mod_col]) * self.dist_params[1]
                upper = np.array(dist_files[0][mod_col]) * self.dist_params[2]                
                # get new values
                lhs_vals = self.sample_lhs_triangular(self.sample_num, sample_group_num, lower, mode, upper)
                # replace file data with with lhs sample values
                # for NA values from sampling (occurs if lower == upper), use existing values file values
                samples_sw[mod_col] = np.where(np.isnan(lhs_vals), samples_sw[mod_col], lhs_vals)


        self.samples[Sample_ID] = samples_sw
        # output: dictionary of sample values by filename (see samples_dict)

    def get_samples(self, aux_files, sample_group_num):
        """
        Generates Monte Carlo samples for each switch and applies the appropriate weight assignment.

        Returns:
            Dict[str, List[pd.DataFrame]]: Dictionary with the samples for each switch/file_name.
        """

        # assign Weight Calculator to sample group when using random sampling approach
        if self.sampling_method == 'random':
            self.assign_weight_calculator()

        # Iterate over each switch file and apply the appropriate weight assignment method
        for sample_idx, sample_ID in enumerate(self.sample_group['Sample_ID']):
            sw_name = self.sample_group['switch_names'][sample_idx]
            file_name = self.sample_group["file_names"][sample_idx]
            Sample_ID = self.sample_group['Sample_ID'][sample_idx]
            dist_files = self.load_ref_files(sample_idx)

            #In some small cases all dist_files are empty
            if not all([len(df) for df in dist_files]):
                self.samples[sample_ID] = [dist_files[0] for s in range(self.n_samples)]
                continue

            # Extend/modify dist_files if necessary (e.g supply curve related data)
            dist_files, modifiable_columns, n_decimals = self.prepare_ref_data(
                dist_files, file_name, sw_name, aux_files,
            )

            # Get weights we will apply to the reference files
            if self.sampling_method == 'latin hypercube':
                # apply latin hybercube sampling based on file type
                if file_name == "switches.csv":
                    self.apply_lhs_switches_csv(sample_group_num, sample_idx, dist_files, n_decimals)
                elif file_name in MCSConstants.RECF_FILES:
                    self._apply_weights_recf(dist_files, sample_idx)
                else:
                    self.apply_lhs_general(sample_group_num, Sample_ID, dist_files, aux_files, modifiable_columns)
            else:
                dict_df_weights = self.weight_calc.get_df_weights(dist_files, modifiable_columns, sw_name, file_name)
                # Dispatch weight application based on file type
                if file_name == "switches.csv":
                    self._apply_weights_switches_csv(dist_files, n_decimals, dict_df_weights, sample_idx)
                elif file_name in MCSConstants.RECF_FILES:
                    self._apply_weights_recf(dist_files, sample_idx)
                else:
                    self._apply_weights_general(dist_files, modifiable_columns, n_decimals, dict_df_weights, sample_idx)

        return self.samples


#%% ===========================================================================
### --- OUTPUT FUNCTIONS ---
### ===========================================================================
def write_samples(
    sample_group: pd.Series,
    samples_dict: dict,
    aux_files: dict,
):
    """
    Write the samples to the appropriate locations

    Args:
        sample_group (pd.Series): Row of the input file with the sampling instructions.
        samples_dict (dict): Dictionary with the samples for each switch/file_name.
        aux_files (dict): Dictionary with the auxiliary files needed for sampling.
    """

    inputs_case = sample_group['inputs_case']
    for sample_idx, sample_ID in enumerate(samples_dict.keys()):
        sample_values = samples_dict[sample_ID]
        sw_name = sample_group['switch_names'][sample_idx]
        save_path = sample_group['save_paths'][sample_idx]  # Where the samples will be copied to
        
        file_name = sample_group["file_names"][sample_idx]
        file_termination = os.path.splitext(save_path)[-1]  # File termination (.csv, .h5, etc.)

        ## save file method varies depending on...
        # ...if we have a region-indexed file
        if file_name in aux_files['region_files']['filename'].values:
            # Get destination directory instead of save_path
            dir_dst = os.path.dirname(save_path)
            # Get the row of the region-indexed file
            region_files_row = aux_files['region_files'].query('filename == @file_name').iloc[0]
            copy_files.write_region_indexed_file(sample_values, dir_dst, aux_files['source_deflator_map'],
                                                    aux_files['sw'], region_files_row,
                                                    aux_files['regions_and_agglevel'])
        # ...if we have a csv file that isn't region-indexed (including switches.csv)
        elif file_termination == '.csv':
            if file_name == 'switches.csv':
                # Read the original switches.csv file
                original_switches = pd.read_csv(save_path, header=None, index_col=0)
                # Update the original switches.csv file with the new samples
                original_switches.loc[sw_name] = sample_values
                original_switches.to_csv(save_path, header=False)
                # Create gswitches.csv and .txt files 
                gswitches_path = reeds.io.write_gswitches(original_switches, inputs_case)
                copy_files.scalar_csv_to_txt(gswitches_path)
            else:
                sample_values.to_csv(save_path, index=False)
        # ...if we are saving load
        elif file_name == 'load.h5':
            reeds.io.write_profile_to_h5(sample_values, 'load.h5', inputs_case)
        # ...not one of these file methods then raise an exception
        else:
            raise NotImplementedError(
                f"Writing samples for '{file_name}' with extension '{file_termination}' is not supported"
            )
                            
        reduced_path = os.sep.join(save_path.strip(os.sep).split(os.sep)[-3:])
        print(f"...Sample related to switch {sw_name} was copied to {reduced_path}")


#%% ===========================================================================
### --- MAIN PROCEDURE ---
### ===========================================================================
def main(
    reeds_path: str,
    inputs_case: str,
    n_samples: int = 1,
    lhs_sampling: int = 1,
    seed: int = 0,
):
    """
    Create samples for the Monte Carlo Simulation (MCS).

    Args:
        reeds_path (str): Path to the ReEDS directory.
        inputs_case (str): Path to the inputs_case directory.
        n_samples (int): Number of samples to generate.
        lhs_sampling (int): whether to use random (0) or latin hypercube (1) sampling.
        seed (int): global seed value for the random number generator.

    """

    # get sample number associated with this ReEDS run
    runs_folder_name = os.path.basename(os.path.dirname(inputs_case.rstrip(os.path.sep)))
    mcs_run_number = int((runs_folder_name.split('_')[-1]).replace('MC', ''))

    # Obtain instructions to sample the distributions for each switch
    df_input_dist_instructions, aux_files = get_dist_instructions(reeds_path, inputs_case)

    # if using latin hypercube sampling (lhs), set up the sampler and draw samples from cdf
    lhs_samples = None
    if lhs_sampling:
        # number of dimensions for lhs = number of sample groups 
        lhs_dim = df_input_dist_instructions.shape[0]
        # lhs requires drawing all samples simultaneously, so rather than using
        # a run-specific seed we draw for all runs at once using the global seed value 
        lhs_sampler = scipy.stats.qmc.LatinHypercube(d=lhs_dim, seed=seed)
        # lhs_samples are arranged n x d (n = samples, d = dimensions)
        lhs_samples = lhs_sampler.random(n=n_samples)
        # record the lhs sampling matrix in each run folder
        lhs_samples_out = pd.DataFrame({'run': [f"MC{i:0>4}" for i in range(1, n_samples + 1)]})
        lhs_samples_out = pd.concat(
            [lhs_samples_out, pd.DataFrame(lhs_samples.round(6), columns=df_input_dist_instructions.name.values)], axis=1
        )
        lhs_samples_out.to_csv(os.path.join(inputs_case, "mcs_latin_hypercube_samples.csv"), index=False)

    # if using random sampling, set random seed using the global seed + MCS run number 
    # to allow reproducibility without having the same sample for each MCS-ReEDS call
    else:
        np.random.seed(seed + mcs_run_number)

    print('Sampling...')
    for sample_group_num, sample_group in df_input_dist_instructions.iterrows():
        dist_switches = sample_group['switch_names']
        unique_switches = set(dist_switches)

        print(f"Sampling for switch(es): {unique_switches}")
        # create sampling object and draw samples
        mcs_sampler = MCS_Sampler(sample_group, aux_files, n_samples, mcs_run_number, lhs_samples)
        samples_dict = mcs_sampler.get_samples(aux_files, sample_group_num)     
        
        # Record the weights of each sample group
        if not lhs_sampling:
            mcs_sampler.record_group_weights(inputs_case)

        # Write Samples
        write_samples(sample_group, samples_dict, aux_files)


if __name__ == '__main__' and not hasattr(sys, 'ps1'):
    parser = argparse.ArgumentParser(description='Copy files needed for this run')
    parser.add_argument('reeds_path', help='ReEDS directory')
    parser.add_argument('inputs_case', help='Output directory')
    parser.add_argument('--nolog', '-n', default=False, action='store_true', help='turn off logging for debugging')
                    
    args = parser.parse_args()
    reeds_path = os.path.abspath(args.reeds_path)
    inputs_case = os.path.abspath(args.inputs_case)
    nolog = args.nolog

    # ---- Settings for testing ----
    # reeds_path = reeds.io.reeds_path
    # inputs_case = os.path.join(reeds_path,'runs','v20250825_revM2_MonteCarlo_MC1','inputs_case')
    # n_samples = 1
    # seed = 0

    # Set up logger
    tic = datetime.datetime.now()
    if not nolog:
        log = reeds.log.makelog(
            scriptname=__file__,
            logpath=os.path.join(os.path.dirname(inputs_case), 'gamslog.txt'),
        )
    
    # Read switches and check if MCS_runs is enabled.
    sw = reeds.io.get_switches(inputs_case)
    MCS_runs = int(sw.get('MCS_runs', 0))
    MCS_lhs = int(sw.get('MCS_lhs', 0))

    # get global seed from scalars (used to set the seed for a batch of runs)
    scalars = reeds.io.get_scalars()
    seed = int(scalars['MCS_seed'])

    if MCS_runs >= 1:
        print('Starting mcs_sampler.py')
        main(reeds_path, inputs_case, n_samples=MCS_runs, lhs_sampling=MCS_lhs, seed=seed)
    else:
        print('MCS_runs switch is set to 0 or not found. No Monte Carlo sampling will be performed')

    # Final log/timing update.
    reeds.log.toc(
        tic=tic, 
        year=0, 
        process='input_processing/mcs_sampler.py',
        path=os.path.join(os.path.dirname(inputs_case))
    )
