import os
import re
import sys
import importlib
import numpy as np
import pandas as pd
from pathlib import Path
from warnings import warn

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds


ISLAND_EXCEPTIONS = ['TX', 'ERCOT', 'TX_ERCOT']


def check_compatibility(sw):
    if int(sw['startyear']) != 2010:
        raise ValueError(f"startyear = {sw['startyear']} but must be = 2010")

    if int(sw['GSw_SkipRAyear']) <= int(sw['startyear']):
            raise ValueError(f"GSw_SkipRAyear = {sw['GSw_SkipRAyear']} but must be > {sw['startyear']}")

    if (sw['GSw_HourlyType'] in ['year']) and int(sw['GSw_InterDayLinkage']):
        raise ValueError(
            "GSw_HourlyType cannot be 'year' when GSw_InterDayLinkage is enabled. "
            f"Current values: GSw_HourlyType={sw['GSw_HourlyType']}, GSw_InterDayLinkage={sw['GSw_InterDayLinkage']}"
        )

    if 24 % (int(sw['GSw_HourlyWindowOverlap']) * int(sw['GSw_HourlyChunkLengthRep'])):
        raise ValueError(
            ('24 must be divisible by GSw_HourlyWindowOverlap * GSw_HourlyChunkLengthRep:'
            '\nGSw_HourlyWindowOverlap = {}\nGSw_HourlyChunkLengthRep = {}'.format(
                sw['GSw_HourlyWindowOverlap'], sw['GSw_HourlyChunkLengthRep'])))

    if int(sw['GSw_HourlyWindow']) <= int(sw['GSw_HourlyWindowOverlap']):
        raise ValueError(
            ('GSw_HourlyWindow must be greater than GSw_HourlyWindowOverlap:'
            '\nGSw_HourlyWindow = {}\nGSw_HourlyWindowOverlap = {}'.format(
                sw['GSw_HourlyWindow'], sw['GSw_HourlyWindowOverlap'])))

    if ((sw['GSw_HourlyClusterAlgorithm'] not in ['hierarchical','optimized','kmeans','kmedoids'])
        and ('user' not in sw['GSw_HourlyClusterAlgorithm'])
    ):
        if sw['GSw_HourlyClusterAlgorithm'].startswith('hierarchical'):
            args = sw['GSw_HourlyClusterAlgorithm'].split('_')
            assert len(args) == 3
            ## https://scikit-learn.org/stable/modules/generated/sklearn.cluster.AgglomerativeClustering.html
            assert args[1] in ['euclidean','l1','l2','manhattan','cosine']
            assert args[2] in ['ward', 'complete', 'average', 'single']
            if args[2] == 'ward':
                assert args[1] == 'euclidean'
        elif sw['GSw_HourlyClusterAlgorithm'].startswith('kmedoids'):
            args = sw['GSw_HourlyClusterAlgorithm'].split('_')
            assert len(args) == 3
            assert args[1] in ['euclidean','l1','l2','manhattan','cosine']
            assert args[2] in ['heuristic','k-medoids++','random','build']
        else:
            raise ValueError(
                "GSw_HourlyClusterAlgorithm must be set to 'hierarchical', 'optimized', "
                "'kmeans', or 'kmedoids', or must "
                "contain the substring 'user' and match a scenario in "
                "inputs/temporal/period_szn_user.csv"
            )

    if ((sw['GSw_PRM_StressModel'].lower() not in ['pras'])
        and ('user' not in sw['GSw_PRM_StressModel'])):
        raise ValueError(
            "GSw_PRM_StressModel must be set to 'pras' or must "
            "contain the substring 'user' and match a scenario at "
            "inputs/temporal/stressperiods_{GSw_PRM_StressModel}.csv"
        )

    if (int(sw['GSw_H2_PTC']) == 1) and (int(sw['GSw_H2']) != 2):
        raise ValueError(
            'When running with the H2 PTC enabled, GSw_H2 should be set to 2.\n'
            f"GSw_H2_PTC={sw['GSw_H2_PTC']}, GSw_H2={sw['GSw_H2']}"
        )

    if int(sw['GSw_H2_SMR']) == 0 and sw['GSw_H2_Demand_Case'] in ['BAU', 'Aggressive', 'Decarb_with_BAU']:
        raise ValueError(
            f"GSw_H2_SMR is set to 0, but GSw_H2_Demand_Case is set to '{sw['GSw_H2_Demand_Case']}', which requires SMR set to 1.\n"
            "When GSw_H2_SMR is 0, GSw_H2_Demand_Case must be one of: 'none', 'Decarb', or 'LTS'."
        )

    if ('usa' not in sw['GSw_Region'].lower()) and (int(sw['GSw_GasCurve']) != 2):
        raise ValueError(
            'Should use GSw_GasCurve=2 (fixed prices) when running sub-nationally\n'
            f"GSw_Region={sw['GSw_Region']}, GSw_GasCurve={sw['GSw_GasCurve']}"
        )

    if (int(sw['MCS_runs']) > 1 and int(sw['GSw_MGA_RV_runs']) > 1):
        raise ValueError(
            'Running Monte Carlo analysis (MCS_runs > 1) and random vector \n'
            'MGA sampling (GSw_MGA_RV_runs > 1) simultaneously is not yet supported.'
        )
        
    reeds.inputs.validate_zoneset(sw['GSw_ZoneSet'])

    ### Parsed string switches
    ## Automatic inputs
    hierarchy = reeds.io.get_hierarchy(GSw_ZoneSet=sw['GSw_ZoneSet']).reset_index()

    ### Check that the stress metrics specified in GSw_PRM_StressThresholdMetrics
    ### are allowed and have well-formed GSw_PRM_StressThreshold{metric} entries
    ra_switches = {
        i.lower(): f'GSw_PRM_StressThreshold{i}'
        for i in ['Depth', 'Duration', 'LOLD', 'LOLE', 'LOLH', 'NEUE']
    }
    used_metrics = [i.lower() for i in sw['GSw_PRM_StressThresholdMetrics'].split('/')]
    allowed_levels = ['country','interconnect','nercr','transreg','transgrp','st','r']

    for metric in used_metrics:
        if metric not in ra_switches:
            raise NotImplementedError(f"GSw_PRM_StressThresholdMetrics = {metric} is not supported")

        for threshold in sw[ra_switches[metric]].split('/'):
            ## Example: GSw_PRM_StressThresholdNEUE = 'transgrp_1'
            (hierarchy_level, stress_value) = threshold.split('_')
            if hierarchy_level not in allowed_levels:
                raise ValueError(
                    f"{ra_switches[metric]}: level={hierarchy_level} but must be in:\n"
                    + '\n'.join(allowed_levels)
                )
            if not (float(stress_value) >= 0):
                raise ValueError(
                    f"stress value in {ra_switches[metric]} must be a positive number "
                    f"but '{stress_value}' was provided"
                )

    ### GSw_PRM_UpdateMethod 1-3 (static or PRAS-informed PRM update) is computed from the
    ### NEUE-based shortfall, so it requires NEUE to be an active stress metric
    if int(sw['GSw_PRM_UpdateMethod']) in [1, 2, 3] and 'neue' not in used_metrics:
        raise ValueError(
            f"GSw_PRM_UpdateMethod={sw['GSw_PRM_UpdateMethod']} requires 'NEUE' to be included "
            f"in GSw_PRM_StressThresholdMetrics (={sw['GSw_PRM_StressThresholdMetrics']}), "
            "since PRM updates are computed from the NEUE-based shortfall."
        )

    if sw['GSw_PRM_StressStorageCutoff'].lower() not in ['off','0','false']:
        metric, value = sw['GSw_PRM_StressStorageCutoff'].split('_')
        if metric.lower()[:3] not in ['eue', 'cap', 'abs']:
            raise ValueError(
                "The first argument of GSw_PRM_StressStorageCutoff must be in "
                f"['eue', 'cap', 'abs'] but {metric} was provided"
            )
        try:
            float(value)
        except ValueError:
            raise ValueError(
                "The second argument of GSw_PRM_StressStorageCutoff must be a number "
                f"but {value} was provided"
            )
        if (metric.lower()[:3] == 'abs') and (int(value) != 1):
            raise NotImplementedError(
                "GSw_PRM_StressStorageCutoff: only abs_1 is implemented for abs but "
                f"{metric}_{value} was provided"
            )

    for keyval in sw['GSw_PRM_NetImportLimitScen'].split('/'):
        err = (
            "GSw_PRM_NetImportLimitScen accepts inputs in the format "
            "{year1}_{'hist' or float}/{year2}_{float}/{year3}_{float} "
            "or a single value given as {year1}_{'hist' or float}. Examples are "
            "2024_hist/2035_40, 2025_20/2032_40, 2024_hist, 2025_20/2032_40/2050_60. "
            f"You entered {sw['GSw_PRM_NetImportLimitScen']}."
        )
        year, limit = keyval.split('_')
        try:
            int(year)
        except ValueError:
            raise ValueError(err)
        if limit not in ['hist', 'histmax']:
            try:
                float(limit)
            except ValueError:
                raise ValueError(err)

    if int(sw['GSw_PRM_UpdateMethod']) == 0 and int(sw['GSw_PRM_CapCredit']) == 1 and int(sw['GSw_PRM_StressIterateMax']) > 0:
        raise ValueError(
            "The combination of GSw_PRM_UpdateMethod=0, GSw_PRM_CapCredit=1, "
            "and GSw_PRM_StressIterateMax>0 is not supported.\n"
            "To iteratively update the PRM, set GSw_PRM_UpdateMethod to an integer between 1-3:"
            "\n1: static update set by GSw_PRM_UpdateFraction; "
            "\n2: dynamic update informed by PRAS; "
            "\n3: dynamic update but only after all new stress periods have been added"
        )

    for bir in sw['GSw_PVB_BIR'].split('_'):
        if not (float(bir) >= 0):
            raise ValueError("Fix GSw_PVB_BIR")

    for ilr in sw['GSw_PVB_ILR'].split('_'):
        if not (float(ilr) >= 0):
            raise ValueError("Fix GSw_PVB_ILR")

    for pvbtype in sw['GSw_PVB_Types'].split('_'):
        if not (1 <= int(pvbtype) <= 3):
            raise ValueError("Fix GSw_PVB_Types")

    try:
        prm = float(sw['GSw_PRM_scenario'])
        if prm >= 1:
            raise Exception(
                f"GSw_PRM_scenario={sw['GSw_PRM_scenario']} but should be formatted as a "
                "fraction, not a percent"
            )
    except ValueError:
        pass

    scalars = reeds.io.get_scalars()
    ilr_upv = scalars['ilr_utility'] * 100

    if (
        int(sw['GSw_PVB'])
        and not all([np.isclose(float(ilr), ilr_upv) for ilr in sw['GSw_PVB_ILR'].split('_')])
    ):
        raise ValueError(
            f"GSw_PVB_ILR = {sw['GSw_PVB_ILR']} but all entries must be {int(ilr_upv)}"
        )

    allowed_years = list(range(2007,2014)) + list(range(2016,2024))
    allowed_years_string = ','.join([str(year) for year in allowed_years])

    resource_adequacy_years = [int(y) for y in sw['resource_adequacy_years'].split('_')]
    for year in resource_adequacy_years:
        if year not in allowed_years:
            raise ValueError(
                f"resource_adequacy_years must be in {allowed_years_string} but is "
                f"{sw['resource_adequacy_years']}"
            )

    for year in sw['GSw_HourlyWeatherYears'].split('_'):
        if int(year) not in allowed_years:
            raise ValueError(
                f"GSw_HourlyWeatherYears must be in {allowed_years_string} but is "
                f"{sw['GSw_HourlyWeatherYears']}"
            )

        if int(year) not in resource_adequacy_years:
            raise ValueError(
                "GSw_HourlyWeatherYears must be a subset of resource_adequacy_years but "
                f"GSw_HourlyWeatherYears={sw['GSw_HourlyWeatherYears']} and "
                f"resource_adequacy_years={sw['resource_adequacy_years']}"
            )

    solveyears = reeds.inputs.parse_yearset(sw['yearset'])
    if int(sw['endyear']) not in solveyears:
        err = f"`endyear` = {sw['endyear']} but must be in `yearset`: {sw['yearset']}"
        raise ValueError(err)

    # Add a row for each county
    county2zone = reeds.io.get_county2zone(GSw_ZoneSet=sw['GSw_ZoneSet'], as_map=False)
    county2zone['county'] = 'p' + county2zone.FIPS
    # Add county info to hierarchy
    hierarchy = hierarchy.merge(county2zone.drop(columns=['FIPS','state']), on='r')

    # Make sure specified regions are allowed for the specified hierarchy level
    region_groups = sw['GSw_Region'].split('//') if '//' in sw['GSw_Region'] else [sw['GSw_Region']]
    for group in region_groups:
        level, regions = group.split('/')
        if level not in hierarchy:
            err = (
                f"The specified hierarchy level '{level}' does not exist in the hierarchy file."
                f"\nUpdate GSw_Region={sw['GSw_Region']} to specify a valid level."
            )
            raise ValueError(err)
        invalid_regions = [
            region for region in regions.split('.')
            if region.lower() not in hierarchy[level].str.lower().values
        ]
        if invalid_regions:
            err = f"GSw_Region: {', '.join(invalid_regions)} need to be in {hierarchy[level].unique()}"
            raise Exception(err)

    ### Compatible switch combinations
    if sw['GSw_LoadProfiles'] == 'historic':
        if ('demand_' + sw['demandscen'] +'.csv') not in os.listdir(os.path.join(reeds.io.reeds_path, 'inputs','load')) :
            raise ValueError("The demand file specified by the demandscen switch is not in the inputs/load folder")

    if (
        re.match(r'(\/|[a-zA-Z]:[\\\/]).+$', sw['GSw_LoadProfiles'])
        and not Path(sw['GSw_LoadProfiles']).is_file()
    ):
        err = f"GSw_LoadProfiles={sw['GSw_LoadProfiles']} but the specified file does not exist"
        raise FileNotFoundError(err)

    if sw['GSw_LoadProfiles'].startswith('EER2023'):
        allowed_ra_years = range(2007,2014)
        if not all([y in allowed_ra_years for y in resource_adequacy_years]):
            err = (
                f"GSw_LoadProfiles={sw['GSw_LoadProfiles']} only supports resource_adequacy_years="
                f"{list(allowed_ra_years)} but {resource_adequacy_years} was supplied"
            )
            raise ValueError(err)

    if (sw['GSw_MGA_Objective'] not in ['capacity', 'generation']) and int(sw['GSw_MGA_RV_runs']) > 0:
        raise NotImplementedError(
            f"GSw_MGA_Objective='{sw['GSw_MGA_Objective']}' is not yet supported for MGA random vector sampling."
        )

    ### Dependent model availability
    if (
        ((int(sw['pras']) == 2) or int(sw['GSw_PRM_StressIterateMax']))
        and (not os.path.isfile(os.path.join(reeds.io.reeds_path, 'Manifest.toml')))
    ):
        err = (
            "Manifest.toml does not exist. "
            "Please set up julia by following the instructions at "
            "https://reeds-model.github.io/ReEDS/setup.html#reeds2pras-julia-and-stress-periods-setup"
        )
        raise Exception(err)

    ### Land use and reeds_to_rev
    if (int(sw['land_use_analysis'])) and (not int(sw['reeds_to_rev'])):
        raise ValueError(
            "'reeds_to_rev' must be enable for land_use analysis to run."
        )

    disallowed_characters = ['~', '|', '*']
    invalid_switches = [
        key for key, val in sw.items()
        if any([char in val for char in disallowed_characters])
    ]
    if len(invalid_switches) > 0:
        raise ValueError(
            "The following switches have values with disallowed characters "
            f"({', '.join(disallowed_characters)}): {', '.join(invalid_switches)}"
        )

    ### Uncommonly used packages
    if sw['GSw_HourlyClusterAlgorithm'].lower().startswith('kmedoids'):
        if importlib.util.find_spec("sklearn_extra") is None:
            err = (
                "The scikit-learn-extra package is required for GSw_HourlyClusterAlgorithm="
                f"{sw['GSw_HourlyClusterAlgorithm']} but is not available in your conda "
                "environment. Please install it by running:\n"
                "    pip install 'scikit-learn-extra>=0.2.0,<0.3.0'"
                "\nor:\n"
                "    conda install -c conda-forge scikit-learn-extra=0.2"
            )
            raise ModuleNotFoundError(err)


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
            'GSw_HourlyType': 'day',
            'GSw_ZoneSet': 'z90',
            'GSw_Region': 'cendiv/Pacific',
            'GSw_HourlyClusterRegionLevel': 'transgrp',
            'GSw_HourlyClusterWeights': 'load_1/upv_1/wind-ons_1/wind-ofs_0',
        }
    """
    if sw['GSw_HourlyType'] == 'year':
        numperiods = 365 * len(sw['GSw_HourlyWeatherYears'].split('_'))
    elif str(sw['GSw_HourlyClusterAlgorithm']).startswith(('hierarchical','kmeans','kmedoids')):
        numperiods = int(sw['GSw_HourlyNumClusters'])
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
            '\nThe estimated number of representative periods for your switch settings is '
            f'{numperiods}, which is less than the threshold of {threshold}.\n'
            'These conditions should only be used for testing and are not appropriate for '
            'analysis.\nSee '
            'https://reeds-model.github.io/ReEDS/user_guide.html#temporal-resolution-switches '
            'for suggestions on how to increase the number of representative periods when '
            'using a small number of regions.\n'
            'The simplest approach is to set GSw_HourlyClusteAlgorithm to "hierarchical" '
            f'and GSw_HourlyNumClusters ≥ {threshold}.\n'
        )
        print(msg)
        err = f'Insufficient representative periods: {numperiods}'
        if force:
            warn(err)
        else:
            proceed = str(input(f'Do you want to proceed with {numperiods} periods? y/[n]') or 'n')
            if proceed.lower() not in ['y','yes']:
                raise ValueError(err)


def check_islands(sw, force=0):
    """
    Check if the choice of region resolution results in islanded zones
    (which can lead to resource adequacy challenges) or a single zone
    (which is not supported by ReEDS2PRAS)

    Inputs for testing:
        sw = {
            'GSw_ZoneSet': 'z90',
            'GSw_Region': 'transreg/PJM',
            'pras': '2',
        }
    """
    zones = reeds.inputs.parse_regions(**sw)
    itls = reeds.inputs.get_itls(GSw_ZoneSet=sw['GSw_ZoneSet'])
    dfitl = itls.loc[(itls.r.isin(zones)) & (itls.rr.isin(zones))].copy()
    not_islands = dfitl[['r','rr']].stack().unique().tolist()
    islands = [r for r in zones if r not in not_islands + ISLAND_EXCEPTIONS]

    if (len(zones) == 1) and int(sw['pras']):
        err = (
            f'\nThe system specified by GSw_ZoneSet = {sw["GSw_ZoneSet"]} and '
            f'GSw_Region = {sw["GSw_Region"]} results in a single zone: {zones[0]}.\n'
            'ReEDS2PRAS does not support single-zone systems. Please run a larger system.'
        )
        raise ValueError(err)

    if not len(islands):
        return
    else:
        msg = (
            f'\nThe system specified by GSw_ZoneSet = {sw["GSw_ZoneSet"]} and '
            f'GSw_Region = {sw["GSw_Region"]} results in {len(islands)} islanded zones:\n    '
            f'{"\n    ".join(islands)}\n'
            f'This approach may lead to resource adequacy challenges.\n'
            f'Consider running a larger system.\n'
            f'If you proceed with this system, be sure to check the resource adequacy results.'
        )
        print(msg)
        err = f'{len(islands)} islanded zones: {islands}'
        if force:
            warn(err)
        else:
            proceed = str(input(f'Do you want to proceed with {len(islands)} islanded zones? y/[n]'))
            if proceed.lower() not in ['y','yes']:
                raise ValueError(err)


def check_switches(sw, force=0):
    """Run all the checks"""
    check_numperiods(sw, force=force)
    check_islands(sw, force=force)
    if force < 2:
        check_compatibility(sw)
        check_GSw_LoadSiteReg(sw)
