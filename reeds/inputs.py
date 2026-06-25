### Imports
import os
import re
import sys
import yaml
import hashlib
import shapely
import numpy as np
import pandas as pd
import sklearn.cluster
import geopandas as gpd
from pathlib import Path
from warnings import warn
from typing import Literal
sys.path.append(str(Path(__file__).parent.parent))
import reeds
from reeds.input_processing import mcs_sampler

### Functions
def parse_regions(case:str|Path|None=None, **kwargs) -> list:
    """
    Get the list of active model zones.

    Inputs
    ------
    case: Filepath to a ReEDS case or None. If None, the defaults from cases.csv are used.
    **kwargs: key/value pairs from cases.csv that override the values in the provided case.
        The only relevant switches here are GSw_ZoneSet and GSw_Region.

    Returns
    -------
    list of zone names

    Examples
    --------
    parse_regions(GSw_ZoneSet='z134', GSw_Region='transreg/NYISO') -> ['p127', 'p128']
    parse_regions(GSw_ZoneSet='z134', GSw_Region='st/PA') -> ['p115', 'p119', 'p120', 'p122']
    parse_regions(GSw_ZoneSet='z132', GSw_Region='st/PA') -> ['p115', 'p120', 'z122']
    """
    sw = reeds.io.get_switches(case, **kwargs)
    hierarchy = reeds.io.assemble_hierarchy(case, **kwargs)
    region_groups = sw.GSw_Region.split('//')
    zones = []
    for region_group in region_groups:
        level, _regions = region_group.split('/')
        regions = _regions.split('.')
        zones.extend(hierarchy.loc[hierarchy[level].isin(regions), 'r'].tolist())
    return zones


def parse_yearset(yearset:str) -> list:
    """
    Parses a ReEDS-formatted yearset and returns a list of integer years.

    Args:
        yearset (str): _-delimited list of individual years OR bash-formatted year ranges

    Returns:
        list of integer years (sorted)
    
    Examples:
        '2010' -> [2010]
        '2010_2015_2020' -> [2010, 2015, 2020]
        '2010..2020..5' -> [2010, 2015, 2020]
        '2010_2015_2020..2050..3' -> [
            2010, 2015,
            2020, 2023, 2026, 2029, 2032, 2035, 2038, 2041, 2044, 2047, 2050
        ]
        '2010..2035..5_2040..2100..10' -> [
            2010, 2015, 2020, 2025, 2030, 2035,
            2040, 2050, 2060, 2070, 2080, 2090, 2100
        ]
    """
    pattern = r'^2\d{3}(\.\.2\d{3}(\.\.\d+)?)?(_2\d{3}(\.\.2\d{3}(\.\.\d+)?)?)*$'
    helper = (
        "For formatting notes and examples, run the following commands:\n"
        "$ python\n"
        ">>> import reeds\n"
        ">>> help(reeds.inputs.parse_yearset)"
    )
    if not re.match(pattern, yearset):
        err = f"Invalid yearset ({yearset}); must match {pattern}. {helper}"
        raise ValueError(err)
    yearstrings = yearset.split('_')
    years = []
    for y in yearstrings:
        subyears = [int(i) for i in y.split('..')]
        if len(subyears) == 1:
            years.append(subyears[0])
        elif len(subyears) == 2:
            years.extend(range(subyears[0], subyears[1]+1))
        elif len(subyears) == 3:
            years.extend(range(subyears[0], subyears[1]+1, subyears[2]))
        else:
            err = f"Invalid subyears ({subyears}) in yearset {yearset}. {helper}"
            raise ValueError(err)
    out = sorted(set(years))
    return out


def add_intermediate_switches(dfcases:pd.DataFrame) -> pd.DataFrame:
    """Determine some switch settings from other switches"""
    ignore_columns = ['Choices', 'Description', 'Default Value']
    cases = [i for i in dfcases if i not in ignore_columns]
    new_switches = {}
    for case in cases:
        sw = dfcases[case]
        new_switches[case] = {}
        ### TEMPORARY 20260402: Turn off itlgrp constraint until it's fixed
        new_switches[case]['GSw_itlgrpConstraint'] = '0'
        ## 'meshed' offshore files are only used when offshore zones are turned on
        new_switches[case]['GSw_OffshoreFiles'] = (
            'meshed' if int(sw['GSw_OffshoreZones']) else 'radial'
        )
        ## Load site region level (GSw_LoadSiteReg) is embedded in GSw_LoadSiteTrajectory
        new_switches[case]['GSw_LoadSiteReg'] = sw['GSw_LoadSiteTrajectory'].split('_')[0]
        ## Get numbins from the max of individual technology bins
        new_switches[case]['numbins'] = str(max(
            int(sw['numbins_windons']),
            int(sw['numbins_windofs']),
            int(sw['numbins_upv']),
            15,
        ))
    dfcases_out = pd.concat([dfcases, pd.DataFrame(new_switches)])
    return dfcases_out


def parse_cases(
    cases_filename:str='cases_test.csv',
    single:str='',
    skip_checks:bool=False,
) -> pd.DataFrame:
    """
    Read a ReEDS cases file, look up empty switch values from "Default Value" or cases.csv,
    and return a dataframe of all switches and values.

    Args:
        cases_filename (str): 'cases_{something}.csv' or 'cases.csv'
        single (str): If not '', specifies a single column to keep from cases_filename
        skip_checks (bool): Skip case validation (not recommended)

    Returns:
        pd.DataFrame
    """
    dfcases = pd.read_csv(
        os.path.join(reeds.io.reeds_path, 'cases.csv'), dtype=object, index_col=0)

    # If we have a case suffix, use cases_[suffix].csv for cases.
    if cases_filename != 'cases.csv':
        dfcases = dfcases[['Choices', 'Default Value']]
        dfcases_suf = pd.read_csv(
            os.path.join(reeds.io.reeds_path, cases_filename), dtype=object, index_col=0)
        # Replace periods and spaces in case names with _
        dfcases_suf.columns = [
            c.replace(' ','_').replace('.','_') if c != 'Default Value' else c
            for c in dfcases_suf.columns]

        # Check to make sure user-specified cases file has up-to-date switches
        missing_switches = [s for s in dfcases_suf.index if s not in dfcases.index]
        if len(missing_switches):
            error = (
                "The following switches are in {} but have changed names or are no longer "
                "supported by ReEDS:\n\n{} \n\nPlease update your cases file; "
                "for the full list of available switches see cases.csv. "
                "Note that switch names are case-sensitive."
            ).format(cases_filename, '\n'.join(missing_switches))
            raise ValueError(error)

        # First use 'Default Value' from cases_[suffix].csv to fill missing switches
        # Later, we will also use 'Default Value' from cases.csv to fill any remaining holes.
        if 'Default Value' in dfcases_suf.columns:
            case_i = dfcases_suf.columns.get_loc('Default Value') + 1
            casenames = dfcases_suf.columns[case_i:].tolist()
            for case in casenames:
                dfcases_suf[case] = dfcases_suf[case].fillna(dfcases_suf['Default Value'])
        dfcases_suf.drop(['Choices','Default Value'], axis='columns',inplace=True, errors='ignore')
        dfcases = dfcases.join(dfcases_suf, how='outer')

    casenames = [c for c in dfcases.columns if c not in ['Description','Default Value','Choices']]
    # Get the list of switch choices
    choices = dfcases.Choices.copy()

    for case in casenames:
        # Fill any missing switches with the defaults in cases.csv
        dfcases[case] = dfcases[case].fillna(dfcases['Default Value'])

        # If --single/-s was passed, only keep those cases (regardless of ignore)
        # otherwise, drop any case marked ignore
        if single:
            if case not in single.split(','):
                continue
        else:
            if int(dfcases.loc['ignore', case]) == 1:
                continue

        # Check to make sure the switch setting is valid
        for i, val in dfcases[case].items():
            if skip_checks:
                continue
            # check that the switch isn't duplicated
            if isinstance(choices[i], pd.Series) and len(choices[i]) > 1:
                error = (
                        f'Duplicate entries for "{i}", delete one and restart.'
                        )
                raise ValueError(error)
            ### Split choices by either '; ' or ','
            if choices[i] in ['N/A',None,np.nan]:
                pass
            elif choices[i].lower() in ['int','integer']:
                try:
                    int(val)
                except ValueError:
                    error = (
                        f'Invalid entry for "{i}" for case "{case}".\n'
                        f'Entered "{val}" but must be an integer.'
                    )
                    raise ValueError(error)
            elif choices[i].lower() in ['float','numeric','number','num']:
                try:
                    float(val)
                except ValueError:
                    error = (
                        f'Invalid entry for "{i}" for case "{case}".\n'
                        f'Entered "{val}" but must be a float (number).'
                    )
                    raise ValueError(error)
            else:
                i_choices = [
                    str(j).strip() for j in
                    np.ravel([i.split(',') for i in choices[i].split(';')]).tolist()
                ]
                matches = [re.match(choice, str(val)) for choice in i_choices]
                if not any(matches): 
                    error = (
                        f'Invalid entry for "{i}" for case "{case}".\n'
                        f'Entered "{val}" but must match one of the following:\n> '
                        + '\n> '.join(i_choices)
                        + f'\nOr, if "{val}" is intended, it must be added to the '
                        '"Choices" column in cases.csv.'
                    )
                    raise ValueError(error)

        # Check GSw_Region switch and ask user to correct if commas are used instead of
        # periods to list multiple regions
        if ',' in (dfcases[case].loc['GSw_Region']) :
            print("Please change the delimeter in the GSw_Region switch from ',' to '.'")
            quit()

    # If doing a Monte Carlo run, modify dfcases by adding new columns
    # for each scenario run. Also validate the distribution file.
    warned_about_cluster_alg = False
    if 'MCS_runs' in dfcases.index:
        for c in dfcases.columns:
            if (
                c not in ['Description','Default Value','Choices']
                and (int(dfcases.loc['MCS_runs',c]) > 0)
                and (not int(dfcases.loc['ignore',c]))
            ):
                # Warn user if the hourly clustering algorithm is not fixed for Monte Carlo runs
                if (
                    not dfcases.at['GSw_HourlyClusterAlgorithm', c].startswith('user')
                    and not warned_about_cluster_alg
                ):
                    print(f"\n[Warning] Case Column: '{c}'")
                    print(
                        "You are attempting to run a Monte Carlo simulation with "
                        "`GSw_HourlyClusterAlgorithm` set to a value other than 'user'.\n"
                        "This may result in inconsistent representative days across MCS runs.\n\n"
                        "To ensure consistency, we strongly recommend setting "
                        "`GSw_HourlyClusterAlgorithm = user` in your switch configuration.\n"
                        "Do you want to proceed with the current setup?"
                    )
                    user_input = input("Type 'yes' to proceed, or 'no' to exit: ").strip().lower()
                    if user_input not in ['yes', 'y']:
                        print("\nPlease update the `GSw_HourlyClusterAlgorithm` switch and restart.")
                        quit()
                    warned_about_cluster_alg = True
                    print()

                # Validate the distribution file
                sw = dfcases[c].fillna(dfcases['Default Value'])
                mcs_dist_path = os.path.join(
                    reeds.io.reeds_path, 'inputs', 'userinput',
                    'mcs_distributions_{}.yaml'.format(sw.MCS_dist)
                )
                mcs_sampler.general_mcs_dist_validation(reeds.io.reeds_path, mcs_dist_path, sw)

                # c (column) is a case with monte carlo runs.
                # replicate this column N (NumMonteCarloRuns) times
                NumMonteCarloRuns = int(dfcases.loc['MCS_runs',c])
                NewColumnNames = [
                    f"{c}_MC{i:0>4}"
                    for i in range(1, NumMonteCarloRuns + 1)
                ]

                # Each new column is a copy of the original column with name c_{MC1,MC2,...}
                dfcases_MC = pd.DataFrame(
                    data=np.array([dfcases[c].values]*NumMonteCarloRuns).T,
                    index=dfcases.index,
                    columns=NewColumnNames,
                )
                dfcases = pd.concat([dfcases, dfcases_MC], axis=1)
                # drop the original column
                dfcases.drop(c, axis=1, inplace=True)

    ## Add switches determined from other switches and remove unnecessary columns
    dfcases_out = (
        add_intermediate_switches(dfcases)
        .drop(columns=['Choices', 'Description', 'Default Value'], errors='ignore')
    )

    return dfcases_out


def solvestring_sequential(
        batch_case, caseSwitches,
        cur_year, next_year, prev_year, restartfile,
        toLogGamsString=' logOption=4 logFile=gamslog.txt appendLog=1 ',
        hpc=0, iteration=0, stress_year=None,
        temporal_inputs='rep',
    ):
    """
    Typical inputs:
    * restartfile: batch_case if first solve year else {batch_case}_{prev_year}
    * caseSwitches: loaded from {batch_case}/inputs_case/switches.csv
    """
    savefile = f"{batch_case}_{cur_year}i{iteration}"
    _stress_year = f"{cur_year}i0" if stress_year is None else stress_year
    out = (
        f"gams {Path('reeds','core','solve','3_solve_oneyear.gms')}"
        + (" license=gamslice.txt" if hpc else '')
        + " o=" + os.path.join("lstfiles", f"{savefile}.lst")
        + " r=" + os.path.join("g00files", restartfile)
        + " gdxcompress=1"
        + " xs=" + os.path.join("g00files", savefile)
        + toLogGamsString
        + f" --case={batch_case}"
        + f" --cur_year={cur_year}"
        + f" --next_year={next_year}"
        + f" --prev_year={prev_year}"
        + f" --stress_year={_stress_year}"
        + f" --temporal_inputs={temporal_inputs}"
        + ''.join([f" --{s}={caseSwitches[s]}" for s in [
            'GSw_Canada',
            'GSw_ClimateHydro',
            'GSw_ClimateWater',
            'GSw_gopt',
            'GSw_HourlyChunkLengthRep',
            'GSw_HourlyChunkLengthStress',
            'GSw_HourlyType',
            'GSw_HourlyWrapLevel',
            'GSw_MGA_CostDelta',
            'GSw_MGA_Direction',
            'GSw_PVB_Dur',
            'GSw_SkipRAyear',
            'GSw_StateCO2ImportLevel',
            'GSw_StartMarkets',
            'GSw_ValStr',
            'solver',
            'debug',
            'startyear',
            'diagnose',
            'diagnose_year'
        ]])
        + '\n'
    )

    return out


def get_bin(
    df_in,
    bin_num,
    bin_method='equal_cap_cut',
    bin_col='capacity_factor_ac',
    bin_out_col='bin',
    weight_col='capacity',
):
    """
    bin supply curve points based on a specified bin column. Used in hourlize to create 'bins'
    for the resource classes (typically using capacity factor) and then used by
    writesupplycurves.py to create bins based on supply curve cost.
    """
    df = df_in.copy()
    ser = df[bin_col]
    # If we have less than or equal unique points than bin_num,
    # we simply group the points with the same values.
    if ser.unique().size <= bin_num:
        bin_ser = ser.rank(method='dense')
        df[bin_out_col] = bin_ser.values
    elif bin_method == 'kmeans':
        nparr = ser.to_numpy().reshape(-1,1)
        weights = df[weight_col].to_numpy()
        kmeans = (
            sklearn.cluster.KMeans(n_clusters=bin_num, random_state=0, n_init=10)
            .fit(nparr, sample_weight=weights)
        )
        bin_ser = pd.Series(kmeans.labels_)
        # but kmeans doesn't necessarily label in order of increasing value because it is 2D,
        # so we replace labels with cluster centers, then rank
        kmeans_map = pd.Series(kmeans.cluster_centers_.flatten())
        bin_ser = bin_ser.map(kmeans_map).rank(method='dense')
        df[bin_out_col] = bin_ser.values
    elif bin_method == 'equal_cap_man':
        # using a manual method instead of pd.cut because i want the first bin to contain the
        # first sc point regardless, even if its weight_col value is more than the capacity
        # of the bin, and likewise for other bins, so i don't skip any bins.
        orig_index = df.index
        df.sort_values(by=[bin_col], inplace=True)
        cumcaps = df[weight_col].cumsum().tolist()
        totcap = df[weight_col].sum()
        vals = df[bin_col].tolist()
        bins = []
        curbin = 1
        for i, _v in enumerate(vals):
            bins.append(curbin)
            if cumcaps[i] >= totcap*curbin/bin_num:
                curbin += 1
        df[bin_out_col] = bins
        # we need the same index ordering for apply to work
        df = df.reindex(index=orig_index)
    elif bin_method == 'equal_cap_cut':
        # Use pandas.cut with cumulative capacity in each class. This will assume equal capacity bins
        # to bin the data.
        orig_index = df.index
        df.sort_values(by=[bin_col], inplace=True)
        df['cum_cap'] = df[weight_col].cumsum()
        bin_ser = pd.cut(df['cum_cap'], bin_num, labels=False)
        bin_ser = bin_ser.rank(method='dense')
        df[bin_out_col] = bin_ser.values
        # we need the same index ordering for apply to work
        df = df.reindex(index=orig_index)
    df[bin_out_col] = df[bin_out_col].astype(int)
    return df


def hash_string(string:str, hashfunc='md5') -> str:
    """Return the hash of a string"""
    _hashfunc = getattr(hashlib, hashfunc)
    return _hashfunc(string.encode()).hexdigest()


def hash_counties(countylist, delim_county=',', hashfunc='md5') -> list:
    """
    Takes a list of 5-digit county FIPS codes, sorts them, concatenates them into a string
    delimited by `delim_county`, and returns a hash using the hashlib function
    specified by `hashfunc`.
    """
    ## Validate the inputs
    invalid = [i for i in countylist if not re.match(r'^\d{5}$', i)]
    if len(invalid):
        err = (
            "The following entries in countylist do not look like 5-digit FIPS codes:\n"
            ','.join(invalid)
        )
        raise ValueError(err)
    delim_string = delim_county.join(sorted(countylist))
    return hash_string(delim_string, hashfunc=hashfunc)


def get_itl_config() -> dict:
    configpath = Path(reeds.io.reeds_path, 'inputs', 'transmission', 'itl_config.yaml')
    with open(configpath, 'r') as f:
        config = yaml.safe_load(f)
    return config


def get_itl(r, rr, case=None, errors='raise', **kwargs) -> dict:
    """
    Get the ITL for a single interface from zone `r` to `rr`.
    The resolution can be provided by:
        - Providing a path to a ReEDS run via `case`
        - Providing `GSw_ZoneSet` as a keyword argument
    """
    sw = reeds.io.get_switches(case, **kwargs)
    config = get_itl_config()
    hashfunc = config['hashfunc']
    county2zone = reeds.io.get_county2zone(case, **kwargs)
    rs = county2zone.unique()
    for _r, rlabel in [(r, 'r'), (rr, 'rr')]:
        if _r not in rs:
            err = f"{rlabel} = {_r} is not defined for GSw_ZoneSet = {sw.GSw_ZoneSet}"
            raise KeyError(err)
    ## Get the ITLs for all interfaces
    itlspath = Path(reeds.io.reeds_path, 'inputs', 'transmission', 'itl_NARIS.csv')
    itls = pd.read_csv(itlspath, index_col=[f'{hashfunc}_from', f'{hashfunc}_to'])
    ## Look up the desired interface
    rhash = hash_counties(county2zone.loc[county2zone==r].index.tolist())
    rrhash = hash_counties(county2zone.loc[county2zone==rr].index.tolist())
    try:
        itl = itls.loc[rhash, rrhash].to_dict()
    except KeyError:
        try:
            ## Check for the other direction. If it exists, reverse the definition of
            ## 'forward' and 'reverse' to match the user-provided 'r' and 'rr'.
            _itl = itls.loc[rrhash, rhash].to_dict()
            itl = {'MW_forward': _itl['MW_reverse'], 'MW_reverse': _itl['MW_forward']}
        except KeyError:
            ## The requested interface is not in the table
            itl = {'MW_forward':0, 'MW_reverse':0}
            interfacepath = Path(reeds.io.reeds_path, 'inputs', 'zones', sw.GSw_ZoneSet)
            err = (
                f"The interface defined by r = {r} and rr = {rr} with "
                f"GSw_ZoneSet = {sw.GSw_ZoneSet} does not have an ITL in {itlspath}. "
                "It either has not been calculated or the provided zones are not "
                f"connected. Check {interfacepath} to see if a value is expected for "
                "this interface."
            )
            if errors == 'raise':
                raise KeyError(err)
            elif errors == 'warn':
                warn(err)
    return itl


def get_interface_data(
    case=None,
    datafile:Literal['itl_NARIS.csv', 'transmission_cost_distance.csv']='itl_NARIS.csv',
    level:str='r',
    interfaces:bool=True,
    errors='raise',
    **kwargs,
) -> pd.DataFrame:
    """
    Get all the transmission interface data for the specified resolution.
    The resolution can be specified by:
        - Providing a path to a ReEDS run via `case`
        - Providing `GSw_ZoneSet` as a keyword argument
    If neither `case` nor `GSw_ZoneSet` are provided, the default resolution from
    `cases.csv` is used.

    Args:
        datafile (str): 'itl_NARIS.csv' or 'transmission_cost_distance.csv'
        level (str): 'r' or 'transgrp'
        interfaces (bool): If True, return values for
            inputs/zones/{GSw_ZoneSet}/interfaces_{level}.csv;
            if False, return values for all start/end zone pairs in GSw_ZoneSet
    """
    ## Derivative inputs
    datacols = {
        'itl_NARIS.csv': ['MW_forward', 'MW_reverse'],
        'transmission_cost_distance.csv': ['polarity', 'voltage', 'cost_MUSD', 'length_miles'],
    }[datafile]
    ## Get some settings
    sw = reeds.io.get_switches(case, **kwargs)
    inputs = Path(reeds.io.reeds_path, 'inputs')
    config = get_itl_config()
    hashfunc = config['hashfunc']
    ## Get the data for all interfaces
    fpath = Path(inputs, 'transmission', datafile)
    dfin = (
        pd.read_csv(fpath)
        .rename(columns={
            f'{hashfunc}_from': 'start',
            f'{hashfunc}_to': 'end',
        })
    )
    if dfin.index.duplicated().sum():
        raise ValueError(f'Duplicate entries in {datafile}')
    ### Get the zone hashes
    zone_node = pd.read_csv(
        Path(inputs, 'zones', sw.GSw_ZoneSet, 'zonehash.csv'),
        index_col='r',
    )
    if level == 'r':
        ## We save the zonehash for level == 'r' directly for peace of mind
        zonehash = zone_node[hashfunc]
    else:
        ## For other levels, we calculate the zonehash from the hierarchy
        hierarchy = reeds.io.assemble_hierarchy(case, **kwargs).set_index('r')
        county2zone = reeds.io.get_county2zone(case=None, **kwargs)
        county2level = county2zone.map(hierarchy[level]).rename(level)
        if county2level.isnull().sum():
            print(county2level.loc[county2level.isnull()])
            err = (
                "Model zones in county2zone.csv and hierarchy.csv "
                f"for GSw_ZoneSet={sw.GSw_ZoneSet} do not match"
            )
            raise ValueError(err)
        zonehash = county2level.reset_index().groupby(level).FIPS.agg(hash_counties)
    ### Get the data for the defined interfaces
    if interfaces:
        interfacepath = Path(inputs, 'zones', sw.GSw_ZoneSet, f'interfaces_{level}.csv')
        dfout = pd.read_csv(interfacepath)
        for i, (r, side) in enumerate([('r', 'start'), ('rr', 'end')]):
            dfout[r] = dfout.interface.str.split(config['idelim']).str[i]
            dfout[side] = dfout[r].map(zonehash)
        dfout = dfout.merge(dfin, on=['start', 'end'], how='left')
    else:
        ## Include any connections to offshore zones for now
        dfoffshore = reeds.io.get_offshore_zones()
        offshore_zones = dfoffshore.index.values.tolist()
        dfout = dfin.loc[
            dfin.start.isin(zonehash.tolist()+offshore_zones)
            & dfin.end.isin(zonehash.tolist()+offshore_zones)
        ].copy()
        hash2zone = pd.Series(
            data=zonehash.index.tolist()+offshore_zones,
            index=zonehash.values.tolist()+offshore_zones,
        )
        for r, side in [('r', 'start'), ('rr', 'end')]:
            dfout[r] = dfout[side].map(hash2zone)
        ## Keep them sorted
        dfout.r, dfout.rr = dfout[['r','rr']].min(axis=1), dfout[['r','rr']].max(axis=1)
        ## Include the lat/lon for plotting and straight-line distance
        zone2latlon = pd.concat([
            dfoffshore[['node_lat','node_lon']],
            zone_node.set_index(hashfunc)[['node_lat','node_lon']],
        ])
        for side in ['start', 'end']:
            for datum in ['lat', 'lon']:
                dfout[f'{side}_{datum}'] = dfout[side].map(zone2latlon[f'node_{datum}'])
    ### Make sure it worked
    missing = dfout.loc[dfout[datacols].isnull().any(axis=1)]
    if len(missing):
        print(missing)
        err = f'Missing data from {datafile} for {len(missing)} interfaces'
        if len(missing) <= 10:
            err += ': ' + (' '.join(missing.interface))
        if errors == 'raise':
            raise KeyError(err)
        elif errors == 'warn':
            warn(err)
    return dfout.dropna()


def get_itls(case=None, level:str='r', errors='raise', **kwargs) -> pd.DataFrame:
    """
    Get all the ITLs for the specified resolution using get_interface_data().
    The resolution can be specified by:
        - Providing a path to a ReEDS run via `case`
        - Providing `GSw_ZoneSet` as a keyword argument
    If neither `case` nore `GSw_ZoneSet` are provided, the default resolution from
    `cases.csv` is used.

    Args:
        level (str): 'r' or 'transgrp'

    Inputs for testing:
        case = None
        level = 'r'
        kwargs = {}
        errors = 'raise'
    """
    return get_interface_data(
        case=case,
        datafile='itl_NARIS.csv',
        level=level,
        interfaces=True,
        errors=errors,
        **kwargs,
    )


def get_distances(case=None, errors='raise', **kwargs) -> pd.DataFrame:
    """
    """
    distances = get_interface_data(
        case=case,
        datafile='transmission_cost_distance.csv',
        level='r',
        interfaces=False,
        errors=errors,
        **kwargs,
    )
    return distances


def _make_line(row):
    return shapely.LineString([[row.from_lon, row.from_lat], [row.to_lon, row.to_lat]])


def get_hvdc_lines(filename='hvdc_existing.csv'):
    """Load data for individual HVDC lines"""
    datapath = Path(reeds.io.reeds_path, 'inputs', 'transmission', filename)
    dfdc = pd.read_csv(datapath)
    dfdc['geometry'] = dfdc.apply(_make_line, axis=1)
    dfdc = gpd.GeoDataFrame(dfdc, crs='EPSG:4326')
    for i, side in enumerate(['from', 'to']):
        dfdc[f'{side}_latlon'] = dfdc.geometry.map(lambda x: shapely.geometry.Point(x.coords[i]))
    return dfdc


def map_hvdc_lines_to_interfaces(
    case=None,
    filename='hvdc_existing.csv',
    dtype:Literal['capacity', 'cost']='capacity',
    **kwargs,
) -> pd.DataFrame:
    """
    Assign HVDC line capacity to interfaces by mapping start/end points to zones

    Inputs for testing:
        case = None
        kwargs = {'GSw_ZoneSet': 'z132'}
        for filename in [
            'hvdc_existing.csv',
            'hvdc_planned-baseline.csv',
            'hvdc_planned-NTP_MT.csv',
            'hvdc_planned-NTP_P2P.csv',
        ]:
            map_hvdc_lines_to_interfaces(case=case, filename=filename, kwargs=kwargs)
    """
    dfzones = reeds.io.get_zones(reeds.io.standardize_case(case), **kwargs)
    dfdc = get_hvdc_lines(filename=filename).to_crs(dfzones.crs)
    for i, side in enumerate(['from', 'to']):
        dfdc[f'zone_{side}'] = gpd.sjoin(
            dfdc.set_geometry(f'{side}_latlon').set_crs('EPSG:4326').to_crs(dfzones.crs),
            dfzones.reset_index(),
            how='left',
        )['r']

    dfcap = (
        dfdc.loc[dfdc.zone_from != dfdc.zone_to].dropna()
        .rename(columns={'zone_from':'r', 'zone_to':'rr'})
    ).copy()
    ## Normalize from/to order
    for index, row in dfcap.iterrows():
        for side, r in enumerate(['r', 'rr']):
            dfcap.loc[index, r] = sorted(row[['r','rr']])[side]
    if dtype == 'capacity':
        ## Sum capacity for each interface
        dfout = (
            dfcap
            .groupby(['r', 'rr', 'trtype', 'year_online', 'certain'])
            [['name', 'MW']].agg({'MW':sum, 'name':list})
        )
    else:
        dfout = dfcap.copy()
    return dfout


def get_b2b(case=None, **kwargs) -> pd.DataFrame:
    """
    Get back-to-back (B2B) converter capacity for specified zone resolution.
    Check it against the sum of known individual converter capacities.

    Inputs for testing:
        case = None
        kwargs = {}
    """
    sw = reeds.io.get_switches(case, **kwargs)
    b2bpath = Path(reeds.io.reeds_path, 'inputs', 'zones', sw.GSw_ZoneSet, 'b2b.csv')
    b2b = pd.read_csv(b2bpath).drop(columns=['name', 'notes'], errors='ignore')

    ## Take the sum by interconnection for validation
    hierarchy = reeds.io.assemble_hierarchy(case, **kwargs).set_index('r')
    _b2b = b2b.copy()
    for i, (r, side) in enumerate([('r', 'from'), ('rr', 'to')]):
        _b2b[f'interconnect_{side}'] = _b2b[r].map(hierarchy.interconnect)
    _b2b['interface'] = _b2b.apply(
        lambda row: '~~'.join(sorted([row.interconnect_from, row.interconnect_to])),
        axis=1
    )
    b2b_interconnect = _b2b.groupby('interface').MW.sum()

    ## Get data for individual converters
    vpath = Path(reeds.io.reeds_path, 'inputs', 'transmission', 'b2b_converters.csv')
    converters = pd.read_csv(vpath)
    converters['interface'] = converters.apply(
        lambda row: '~~'.join(sorted([row.interconnection_from, row.interconnection_to])),
        axis=1
    )
    converters_interconnect = converters.groupby('interface').MW.sum()

    ## Interface capacity should match sum of individual converters
    if (b2b_interconnect != converters_interconnect).any():
        err = (
            f"The B2B interface capacity in {b2bpath} does not match the sum of "
            f"individual B2B converter capacity in {vpath}"
        )
        raise ValueError(err)

    return b2b


def get_zoneset_config() -> dict:
    configpath = Path(reeds.io.reeds_path, 'inputs', 'zones', 'zoneset_config.yaml')
    with open(configpath, 'r') as f:
        config = yaml.safe_load(f)
    return config


def get_applicable_zonesets(setting: str) -> list[str]:
    """
    Get the list of zonesets that a setting should apply to. The provided
    setting should be a field in 'inputs/zones/zoneset_config.yaml'.
    """
    zoneset_config = get_zoneset_config()
    if setting not in zoneset_config:
        raise NotImplementedError(
            f"The provided setting '{setting}' is invalid. "
            "Update inputs/zones/zoneset_config.yaml to include it."
        )
    return zoneset_config[setting]


def validate_zoneset(GSw_ZoneSet):
    """
    Make sure all the required inputs are supplied for GSw_ZoneSet

    Test all options:
        GSw_ZoneSets = [
            'z48',
            'z54',
            'z69',
            'z90',
            'z132',
            'z134',
            # 'z153',
            # 'z1259',
            # 'z2972',
            'z3109',
            'UTcounty',
            'PJMcounty',
        ]
        for GSw_ZoneSet in GSw_ZoneSets:
            print(GSw_ZoneSet)
            validate_zoneset(GSw_ZoneSet)
    """
    zonepath = Path(reeds.io.reeds_path, 'inputs', 'zones', GSw_ZoneSet)
    ## Do all the files exist?
    required_files = [
        'b2b.csv',
        'county2zone.csv',
        'hierarchy.csv',
        'interfaces_r.csv',
        'interfaces_transgrp.csv',
        'zonehash.csv',
    ]
    missing = [f for f in required_files if not Path(zonepath, f).is_file()]
    if len(missing):
        err = f'Missing these files from {zonepath}: ' + ' '.join(missing)
        raise FileNotFoundError(err)
    ## Are all/only the right counties included?
    fpath_county2zone = Path(zonepath, 'county2zone.csv')
    fpath_countystate = Path(reeds.io.reeds_path, 'inputs', 'zones', 'county_state.csv')
    county2zone = pd.read_csv(fpath_county2zone, dtype=str)
    county_state = pd.read_csv(fpath_countystate, dtype=str)
    extra_fips = county2zone.loc[~county2zone.FIPS.isin(county_state.FIPS), 'FIPS'].values
    missing_fips = county_state.loc[~county_state.FIPS.isin(county2zone.FIPS), 'FIPS'].values
    if len(extra_fips):
        raise ValueError(
            f"{len(extra_fips)} counties should NOT be in {fpath_county2zone}: "
            f"{', '.join(extra_fips)}"
        )
    if len(missing_fips):
        raise ValueError (
            f"{len(missing_fips)} counties are missing from {fpath_county2zone}: "
            f"{', '.join(missing_fips)}"
        )
    ## Do the zone definitions in county2zone.csv match zonehash.csv?
    config = get_itl_config()
    hashfunc = config['hashfunc']
    zonehash = pd.read_csv(Path(zonepath, 'zonehash.csv'), index_col='r')[hashfunc]
    checkhash = county2zone.groupby('r').FIPS.agg(hash_counties)
    if (zonehash != checkhash).any():
        _df = pd.concat({'zonehash.csv':zonehash, 'county2zone.csv':checkhash}, axis=1)
        wrong = _df.loc[_df['zonehash.csv'] != _df['county2zone.csv']]
        print(wrong)
        raise ValueError(
            f"zonehash.csv and county2zone.csv in inputs/zones/{GSw_ZoneSet} do not "
            f"match for {len(wrong)} zones: {', '.join(wrong.index)}"
        )
    ## Do all the zone interfaces have ITLs?
    dfitl = get_itls(GSw_ZoneSet=GSw_ZoneSet, errors='raise')
    ## Do all the transgrp interfaces have ITLs?
    get_itls(GSw_ZoneSet=GSw_ZoneSet, level='transgrp', errors='raise')
    ## Do all interfaces with ITLs have distances and costs?
    dfdistance = get_distances(GSw_ZoneSet=GSw_ZoneSet)
    dftest = dfitl.merge(dfdistance.loc[dfdistance.polarity=='ac'], on=['r','rr'], how='left')
    nulls = dftest.loc[dftest[['cost_MUSD','length_miles']].isnull().sum(axis=1) > 0]
    if len(nulls):
        print(nulls)
        raise ValueError(f'Missing transmission distance/cost for {len(nulls)} interfaces')
    ## Do the hierarchy files have all the required columns?
    required_levels = ['st', 'transreg', 'transgrp', 'nercr', 'interconnect']
    hierarchy = reeds.io.assemble_hierarchy(GSw_ZoneSet=GSw_ZoneSet).set_index('r')
    missing = [i for i in required_levels if i not in hierarchy]
    if len(missing):
        hierarchypath = Path(zonepath, 'hierarchy.csv')
        err = f'The following columns are missing from {hierarchypath}: ' + ' '.join(missing)
        raise KeyError(err)
