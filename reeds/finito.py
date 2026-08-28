"""
Functions relevant to setting up a linked ReEDS-FINITO run
"""

### Imports
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

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
    finito_check_inputs_path = os.path.join(
        df_cases[case]['finito_dir'], 'input_processing', 'processing')
    sys.path.append(finito_check_inputs_path)
    from check_inputs import check_inputs

    ### load the default values for all FINITO switches from ~\FINITO\cases.csv
    df_cases_finito = pd.read_csv(
        os.path.join(df_cases[case]['finito_dir'], 'cases.csv'), dtype=object, index_col=0)
    df_cases_finito = df_cases_finito[['Choices', 'Default Value']]

    ### load the scenario-specific switches from ~\FINITO\cases_linked.csv
    cases_linked_path = os.path.join(
        df_cases[case]['finito_dir'], f"cases_{df_cases[case]['finito_cases_file']}.csv")
    df_cases_suf_finito = pd.read_csv(cases_linked_path, dtype=object, index_col=0)
    ## check that case names are unique in cases_linked.csv
    # grab the scenario names **exactly** as they appear in the csv file
    header = pd.read_csv(cases_linked_path, header=None).iloc[0].values
    # find the duplicate column names and raise an error if any are found
    duplicate_columns = {x for x in header if list(header).count(x) > 1}
    if duplicate_columns:
        raise ValueError(
            f"The FINITO cases_{df_cases[case]['finito_cases_file']}.csv has the "
            f"following duplicate column names: {duplicate_columns}"
        )
    ### identify the FINITO case
    if df_cases[case]['finito_case'] == 'same':
        finito_case = case
    else:
        finito_case = df_cases[case]['finito_case']
    # ensures **exact** match of names between the ReEDS cases_{}.csv and the FINITO cases_linked.csv
    if finito_case not in (df_cases_suf_finito.columns):
        raise ValueError(
            f"The 'finito_case' input '{finito_case}' in the ReEDS cases file does not "
            f"exist in FINITO's cases_{df_cases[case]['finito_cases_file']}.csv."
        )

    ### first use 'Default Value' from the FINITO cases_linked.csv to fill missing switches
    if 'Default Value' in df_cases_suf_finito.columns:
        df_cases_suf_finito[finito_case] = (
            df_cases_suf_finito[finito_case].fillna(df_cases_suf_finito['Default Value'])
        )
    ### then, use 'Default Value' from the FINITO cases.csv to fill un-assigned switches
    df_cases_suf_finito.drop(
        ['Choices', 'Default Value'], axis='columns', inplace=True, errors='ignore')
    df_cases_finito = df_cases_finito.join(df_cases_suf_finito, how='outer')
    df_cases_finito[finito_case] = (
        df_cases_finito[finito_case].fillna(df_cases_finito['Default Value'])
    )

    #### create new dataframe for the combined ReEDS and FINITO switches
    df_cases_combine = pd.concat([df_cases[case], df_cases_finito[finito_case]])
    ### drop duplicated switches, defaulting to reeds
    df_cases_combine = df_cases_combine[~df_cases_combine.index.duplicated(keep='first')]

    #%% Check for incompatibility of FINITO switches
    model_sectors = df_cases_finito['Default Value']['focus_sectors'].split('.')
    check_inputs(case=case, df_case=df_cases_combine, model_sectors=model_sectors)

    return df_cases_combine


def setup_finito(casedir, caseSwitches, BatchName):
    #%% Copy FINITO code folders and inputs into [casedir]/finito
    finito_dir = Path(caseSwitches['finito_dir'])
    # ... finito directory within the case directory
    casedir_finito = Path(casedir, 'finito')
    # ... define the inputs case directory for FINITO
    inputs_case_finito = Path(casedir, 'finito', 'inputs_case')

    # copy directories
    casedir_finito.mkdir(parents=True, exist_ok=True)
    shutil.copytree(finito_dir / 'inputs', casedir_finito / 'inputs')
    shutil.copytree(finito_dir / 'input_processing', casedir_finito / 'input_processing')
    shutil.copytree(finito_dir / 'model', casedir_finito / 'model')
    shutil.copytree(finito_dir / 'visualization', casedir_finito / 'visualization')

    # copy over the FINITO cases files
    shutil.copy2(finito_dir / 'cases.csv', casedir_finito)
    shutil.copy2(finito_dir / f"cases_{caseSwitches['finito_cases_file']}.csv", casedir_finito)

    #%% (GSw_Trade_PriceResponse > 0) If doing a price-responsive trade run, retrieve the reference exports/imports prices
    if int(caseSwitches['GSw_Trade_PriceResponse']) > 0:
        initialize_price_response_path = (
            casedir_finito / 'input_processing' / 'processing' / 'initialize_price_response.py'
        )
        subprocess.run(
            [
                'python', str(initialize_price_response_path),
                '-c', str(casedir),
                '-b', str(BatchName),
                '-cr', str(caseSwitches['GSw_Trade_PriceResponse_RefScen']),
                '-l', str(caseSwitches['GSw_FINITO_Link']),
            ],
            check=True,
        )

    #%% Filter and copy all input files for each scenario
    # Call FINITO copy_files.py file before starting the runs
    copy_files_run = subprocess.run(
        [
            'python', str(finito_dir / 'input_processing' / 'processing' / 'copy_files.py'),
            '-c', str(casedir_finito),
            '-d', str(inputs_case_finito),
            '--link',
        ],
        check=False,
    )

    # Raise an error if copy_files.py encounters any issue
    if copy_files_run.returncode != 0:
        raise RuntimeError(
            "FINITO copy_files.py encountered an issue and did not complete successfully. "
            "Please check the console output above for details. "
            "The issue could be due to regionality, focus sector filtering, or file reading errors."
        )

    ## Populate sets for each linked run using autopop_set.py
    subprocess.run(
        [
            'python', str(finito_dir / 'input_processing' / 'processing' / 'autopop_set.py'),
            '-c', str(casedir_finito),
            '-d', str(inputs_case_finito),
            '--link',
        ],
        check=True,
    )

    ## Call read_mecs_heat.py to generate heat/nonheat/feedstock ratios for FINITO Rest of Industry (ROI)
    mecs_sectors = caseSwitches['focus_sectors'].replace('.', ' ')
    read_mecs_path = (
        finito_dir / 'input_processing' / 'processing' / 'mecs' / 'read_mecs_heat.py'
    )
    subprocess.run(
        ['python', str(read_mecs_path), '-s', mecs_sectors, '-d', str(inputs_case_finito)],
        check=True,
    )


def get_hourly_finito_load(
    inputs_case: str,
) -> pd.DataFrame:
    """
    Load FINITO's reference annual industrial demand (load_finito.csv), aggregate it
    to this run's model regions, and spread it evenly across all hours.

    Returns an hourly load dataframe (year index, model-region columns, MW).
    """
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
