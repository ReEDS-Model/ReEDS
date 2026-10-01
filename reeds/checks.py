import pandas as pd
import os
import sys
from pathlib import Path
from warnings import warn

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds


def check_GSw_LoadSiteReg(sw):
    """
    Ensure the region entries in loadsite_{GSw_LoadSiteTrajectory} obey the hierarchy
    level specified by GSw_LoadSiteTrajectory
    """
    hierarchy = reeds.io.get_hierarchy()
    ## Make sure the file exists
    infile = os.path.join(
        reeds.io.reeds_path, 'inputs', 'load', f"loadsite_{sw['GSw_LoadSiteTrajectory']}.csv",
    )
    if not os.path.exists(infile):
        err = (
            f"GSw_LoadSiteTrajectory = {sw['GSw_LoadSiteTrajectory']} but {infile} does not exist"
        )
        print(err)
        raise FileNotFoundError(infile)
    ## Make sure the regions obey the hierarchy level
    level = sw['GSw_LoadSiteTrajectory'].split('_')[0]
    allowed = hierarchy[level].unique()
    df = pd.read_csv(infile, comment='#', index_col=0)
    regions = df.index.unique()
    wrong = [r for r in regions if r not in allowed]
    if len(wrong):
        err = f"{infile} contains [{', '.join(wrong)}] but can only contain [{', '.join(allowed)}]"
        raise ValueError(err)


def estimate_numperiods(sw):
    """
    Estimate the number of representative periods for the supplied switch settings.
    Mostly only matters if using GSw_HourlyClusterAlgorithm = 'optimized'.

    Caveats:
    - Will overestimate the number of periods if the following three are true:
        - GSw_HourlyClusterAlgorithm = 'optimized'
        - GSw_HourlyClusterWeights has nonzero weight for 'wind-ofs'
        - The combination of GSw_ZoneSet, GSw_Region, and GSw_HourlyClusterRegionLevel
          specifies regions that do not include offshore wind resources

    Inputs for testing:
        sw = {
            'GSw_ZoneSet': 'z90',
            'GSw_Region': 'cendiv/Pacific',
            'GSw_HourlyClusterRegionLevel': 'transgrp',
            'GSw_HourlyClusterWeights': 'load_1/upv_1/wind-ons_1/wind-ofs_0',
        }
    """
    if str(sw['GSw_HourlyClusterAlgorithm']).startswith(('hierarchical','kmeans','kmedoids')):
        numperiods = int(sw['GSw_HourlyNumPeriods'])
    elif sw['GSw_HourlyClusterAlgorithm'] == 'optimized':
        zones = reeds.inputs.parse_regions(**sw)
        hierarchy = reeds.io.assemble_hierarchy(**sw).set_index('r').loc[zones]
        level = sw['GSw_HourlyClusterRegionLevel']
        levels = sorted(hierarchy[level].unique())
        featureweights = sw['GSw_HourlyClusterWeights'].split('/')
        features = [i for i in featureweights if float(i.rsplit('_',1)[-1]) > 0]
        numperiods = len(levels) * len(features)
    elif str(sw['GSw_HourlyClusterAlgorithm']).startswith('user'):
        fpath = Path(
            reeds.io.reeds_path, 'inputs', 'temporal',
            f'period_szn_{sw["GSw_HourlyClusterAlgorithm"]}.csv',
        )
        period_szn = pd.read_csv(fpath)
        numperiods = len(period_szn.rep_period.unique())
    else:
        raise ValueError(f"GSw_HourlyClusterAlgorithm = {sw['GSw_HourlyClusterAlgorithm']}")

    return numperiods


def check_numperiods(sw, threshold=24, force=0):
    """
    If the estimated number of representative periods is under the specified threshold,
    ask the user if they want to proceed.
    If force > 0, skip the prompt and print the estimated number of periods.
    """
    numperiods = estimate_numperiods(sw)
    if numperiods >= threshold:
        return
    else:
        msg = (
            'The estimated number of representative periods for your switch settings is '
            f'{numperiods}, which is less than the threshold of {threshold}.\n'
            'These conditions should only be used for testing and are not appropriate for '
            'analysis.\nSee '
            'https://reeds-model.github.io/ReEDS/user_guide.html#temporal-resolution-switches '
            'for suggestions on how to increase the number of representative periods when '
            'using a small number of regions.\n'
            'The simplest approach is to set GSw_HourlyClusteAlgorithm to "hierarchical" '
            f'and GSw_HourlyNumClusters ≥ {threshold}.'
        )
        print(msg)
        err = f'Insufficient representative periods: {numperiods}'
        if force:
            warn(err)
        else:
            proceed = str(input(f'Do you want to proceed with {numperiods} periods? y/[n]') or 'n')
            if proceed.lower() not in ['y','yes']:
                raise ValueError(err)


def check_switches(sw, force=0):
    """Run all the checks"""
    check_GSw_LoadSiteReg(sw)
    check_numperiods(sw, force=force)
