import pandas as pd
import os
import sys

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


def check_GSw_StateRPS_StressLevel(sw):
    """
    GSw_StateRPS_Stress=2 weights a state's stress-period RPS/CES by only
    the state's seeded peak-load stress period(s), which are only ever identified
    when GSw_PRM_CapCredit=0 and GSw_PRM_StressSeedLoadLevel is enabled. If
    either condition fails, there are no load-peak stress periods for
    GSw_StateRPS_Stress=2 to weight against.
    """
    if int(sw['GSw_StateRPS_Stress']) != 2:
        return
    if int(sw['GSw_PRM_CapCredit']):
        raise ValueError(
            "GSw_StateRPS_Stress=2 requires GSw_PRM_CapCredit=0 (the stress-period "
            "PRM formulation) since load-peak stress periods are only seeded in that case."
        )
    level = sw['GSw_PRM_StressSeedLoadLevel']
    if level.lower() in ['false', 'none']:
        raise ValueError(
            "GSw_StateRPS_Stress=2 requires GSw_PRM_StressSeedLoadLevel to be set to a "
            f"hierarchy level (it is currently set to {level}) so that a peak-load stress "
            "period exists to weight against."
        )


def check_switches(sw):
    """Run all the checks"""
    check_GSw_LoadSiteReg(sw)
    check_GSw_StateRPS_StressLevel(sw)
