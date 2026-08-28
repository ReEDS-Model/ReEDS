### Imports
import os
import sys
import csv
import shutil
import numpy as np
import pandas as pd
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
import reeds


#%% ===========================================================================
### --- FUNCTIONS ---
### ===========================================================================

# (ReEDS-FINITO) update 'df_cases' to include FINITO switches
def linked_cases(df_cases, case):
    """
    Updates the cases dataframe to include FINITO-specific switches.
    When a switch is duplicated in FINITO and ReEDS, then we default to
    the ReEDS value.

    For the FINITO switches, the combined cases file defaults to the case-specific
    'Default Value' in cases_linked.csv first, before using the universal FINITO
    'Default Value' in cases.csv for any un-assigned switches.
    """
    # check for valid finito_dir
    if not os.path.isdir(df_cases[case]['finito_dir']):
        raise ValueError(
            f"finito_dir = {df_cases[case]['finito_dir']} is not a valid path. "
            "Please ensure this path points to a cloned version of the FINITO repository. "
        )

    # define path to and read the FINITO check_inputs function
    finito_check_inputs_path = os.path.join(df_cases[case]['finito_dir'], 'input_processing', 'processing')
    sys.path.append(finito_check_inputs_path)
    from check_inputs import check_inputs

    ### load the default values for all FINITO switches from ~\FINITO\cases.csv
    df_cases_finito = pd.read_csv(os.path.join(df_cases[case]['finito_dir'],'cases.csv'), dtype=object, index_col=0)
    df_cases_finito = df_cases_finito[['Choices', 'Default Value']]

    ### load the scenario-specific switches from ~\FINITO\cases_linked.csv
    cases_linked_path = os.path.join(df_cases[case]['finito_dir'],f"cases_{df_cases[case]['finito_cases_file']}.csv")
    df_cases_suf_finito = pd.read_csv(cases_linked_path, dtype=object, index_col=0)
    ## check that case names are unique in cases_linked.csv
    # grab the scenario names **exactly** as they appear in the csv file
    with open(cases_linked_path, 'r', newline='') as csvfile:
        reader = csv.reader(csvfile)
        header = next(reader)
    # find the duplicate column names and raise an error if any are found
    duplicate_columns = set([x for x in header if header.count(x) > 1])
    if duplicate_columns:
        raise ValueError(f"The FINITO cases_{df_cases[case]['finito_cases_file']}.csv has the following duplicate column names: {duplicate_columns}")
    ### identify the FINITO case
    if df_cases[case]['finito_case'] == 'same':
        finito_case=case
    else:
        finito_case=df_cases[case]['finito_case']
    # ensures **exact** match of names between the ReEDS cases_{}.csv and the FINITO cases_linked.csv
    if finito_case not in (df_cases_suf_finito.columns):
        raise ValueError(f"The 'finito_case' input '{finito_case}' in the ReEDS cases file does not exist in FINITO's cases_{df_cases[case]['finito_cases_file']}.csv.")

    ### first use 'Default Value' from the FINITO cases_linked.csv to fill missing switches
    if 'Default Value' in df_cases_suf_finito.columns:
        df_cases_suf_finito[finito_case] = df_cases_suf_finito[finito_case].fillna(df_cases_suf_finito['Default Value'])
    ### then, use 'Default Value' from the FINITO cases.csv to fill un-assigned switches
    df_cases_suf_finito.drop(['Choices','Default Value'], axis='columns',inplace=True, errors='ignore')
    df_cases_finito = df_cases_finito.join(df_cases_suf_finito, how='outer')
    df_cases_finito[finito_case] = df_cases_finito[finito_case].fillna(df_cases_finito['Default Value'])

    #### create new dataframe for the combined ReEDS and FINITO switches
    df_cases_combine = pd.concat([df_cases[case],df_cases_finito[finito_case]])
    ### drop duplicated switches, defaulting to reeds
    df_cases_combine = df_cases_combine[~df_cases_combine.index.duplicated(keep='first')]

    #%% Check for incompatibility of FINITO switches
    model_sectors = df_cases_finito['Default Value']['focus_sectors'].split('.')
    check_inputs(case = case, df_case = df_cases_combine, model_sectors=model_sectors)

    return df_cases_combine


def setup_finito(casedir, caseSwitches, BatchName):
    #%% Copy FINITO code folders and inputs into [casedir]/finito
    # ... finito directory within the case directory
    casedir_finito = os.path.join(casedir,'finito')
    # ... define the inputs case directory for FINITO
    inputs_case_finito = os.path.join(casedir,'finito','inputs_case')

    # copy directories
    os.makedirs(casedir_finito, exist_ok=True)
    shutil.copytree(os.path.join(caseSwitches['finito_dir'], 'inputs'),os.path.join(casedir,'finito', 'inputs'))
    shutil.copytree(os.path.join(caseSwitches['finito_dir'], 'input_processing'),os.path.join(casedir,'finito', 'input_processing'))
    shutil.copytree(os.path.join(caseSwitches['finito_dir'], 'model'),os.path.join(casedir,'finito', 'model'))
    shutil.copytree(os.path.join(caseSwitches['finito_dir'], 'visualization'),os.path.join(casedir, 'finito', 'visualization'))

    # copy over the FINITO cases files
    shutil.copy2(os.path.join(caseSwitches['finito_dir'], 'cases.csv'), os.path.join(casedir, 'finito'))
    shutil.copy2(os.path.join(caseSwitches['finito_dir'], f"cases_{caseSwitches['finito_cases_file']}.csv"), os.path.join(casedir, 'finito'))

    #%% (GSw_Trade_PriceResponse > 0) If doing a price-responsive trade run, retrieve the reference exports/imports prices
    if int(caseSwitches['GSw_Trade_PriceResponse']) > 0:
        initialize_price_response_path = os.path.join(casedir_finito, 'input_processing', 'processing', 'initialize_price_response.py')
        # Collect all arguments for initialize_price_response.py
        initialize_price_response_args = f" -c {casedir} -b {BatchName} -cr {caseSwitches['GSw_Trade_PriceResponse_RefScen']} -l {caseSwitches['GSw_FINITO_Link']}"
        # Call initialize_price_response.py file before starting the runs
        os.system('python ' + initialize_price_response_path + initialize_price_response_args)

    #%% Filter and copy all input files for each scenario
    # Call FINITO copy_files.py file before starting the runs
    copy_files_run = os.system(
        'python ' + os.path.join(caseSwitches['finito_dir'], 'input_processing', 'processing', 'copy_files.py') +
        f" -c {casedir_finito} -d {inputs_case_finito} --link"
        )

    # Print an error message if copy_files.py encounters any issue
    if copy_files_run != 0:
        print("\nERROR: FINITO copy_files.py encountered an issue and did not complete successfully.")
        print("Please check the console output above for details.")
        print("The issue could be due to regionality, focus sector filtering, or file reading errors.")
        os._exit(1)

    ## Populate sets for each linked run using autopop_set.py
    os.system(
        'python ' + os.path.join(caseSwitches['finito_dir'], 'input_processing', 'processing', 'autopop_set.py') +
        f" -c {casedir_finito} -d {inputs_case_finito} --link"
    )

    ## Call read_mecs_heat.py to generate heat/nonheat/feedstock ratios for FINITO Rest of Industry (ROI)
    mecs_sectors = caseSwitches['focus_sectors'].replace('.', ' ')
    read_mecs_path = os.path.join(caseSwitches['finito_dir'], 'input_processing', 'processing', 'mecs', 'read_mecs_heat.py')
    # Collect all arguments for read_mecs_heat.py
    read_mecs_args = f' -s {mecs_sectors} -d {inputs_case_finito}'
    os.system('python ' + read_mecs_path + read_mecs_args)


#TODO: add docstrings
def get_hourly_finito_load(
    inputs_case: str,
) -> pd.DataFrame:
    # load reference FINITO load
    inputs_case_finito = Path(inputs_case).parent / 'finito' / Path(inputs_case).name
    load_finito = pd.read_csv(inputs_case_finito / "load_finito.csv")

    # reshape to match load data. with year in index and region in columns
    load_finito = load_finito.melt(id_vars='r', var_name='year', value_name='load_MWh')
    load_finito.year = load_finito.year.astype(int)
    load_finito = load_finito.pivot(index='year', columns='r', values='load_MWh')
    load_finito.columns.name = None

    # load_finito.csv is at z134 (p) resolution, so aggregate to this
    # run's model regions
    county2p = reeds.io.get_county2zone(GSw_ZoneSet='z134')
    county2zone = reeds.io.get_county2zone(case=Path(inputs_case).parent)
    p2zone = (
        pd.concat({'p': county2p, 'zone': county2zone}, axis=1)
        .dropna()
        .drop_duplicates()
    )
    zones_per_p = p2zone.groupby('p')['zone'].nunique()
    if (zones_per_p > 1).any():
        raise ValueError(
            'Cannot aggregate load_finito.csv from z134 to model regions because '
            'these p regions span multiple model regions: '
            f'{zones_per_p.loc[zones_per_p > 1].index.tolist()}'
        )
    p2zone = p2zone.set_index('p')['zone']
    load_finito = load_finito.rename(columns=p2zone).T.groupby(level=0).sum().T

    # allocate annual load to hours, assuming flat demand
    # TODO: should this use h_weight_finito?
    hours_per_year = 8760
    load_hourly_finito = load_finito / hours_per_year
    load_hourly_finito = load_hourly_finito.astype(np.float32)

    return load_hourly_finito


def remove_finito_load(
    load_hourly: pd.DataFrame,
    inputs_case: str,
    distloss: float,
) -> pd.DataFrame:

    # get FINITO reference load
    load_hourly_finito = get_hourly_finito_load(inputs_case)

    # Convert to busbar
    load_hourly_finito = load_hourly_finito / (1 - distloss)

    # subtract FINITO reference load from ReEDS load data,
    # aligning by model year (index) and region (columns)
    result = load_hourly - load_hourly_finito

    # any missing region or model year in load_finito.csv shows up as NaN
    if result.isnull().any().any():
        raise ValueError(
            'FINITO reference load is missing regions or years present in the '
            'ReEDS load data; check load_finito.csv'
        )

    # Validation check: FINITO reference load should not exceed baseline load.
    # If it does, clip to zero and report
    negative = result < 0
    if negative.any().any():
        clipped = (-result[negative]).groupby('year').sum()
        clipped = clipped.stack().loc[lambda x: x > 0].rename('clipped_MWh')
        print(
            'WARNING: FINITO reference load exceeds baseline load; clipping '
            f'{clipped.sum():.0f} MWh (summed over weather years) to zero.\n'
            'Clipped MWh by (year, region):\n'
            + clipped.to_string()
        )
        result = result.clip(lower=0)

    return result
