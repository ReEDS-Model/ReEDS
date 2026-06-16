###########
"""
Preprocessing script to calculate cost adjustment multipliers for EGS based on differences in drilling costs at specific depths and plant cycle-related costs
"""

#%% IMPORTS
import os
import argparse
import pandas as pd
import numpy as np
import reeds
import traceback

#############
#%% FUNCTION DEFINITION

def main(inputs_case, plantchar_geo, tech_type=None, output_multipliers=True):

    sw = reeds.io.get_switches(inputs_case)
    tech_types = [tech_type] if tech_type else ['egs', 'geohydro']
    active_tech_types = []
    for tech in tech_types:
        numbins = int(sw.get(f'numbins_{tech}_depth', 1))
        if numbins <= 1:
            out_path = os.path.join(inputs_case, f'{tech}_cap_cost_mult.csv')
            pd.DataFrame(columns=['*i','r','value']).to_csv(out_path, index=False)
            print(f"numbins_{tech}_depth=1: skipping cost adjustment, writing empty {tech}_cap_cost_mult.csv")
        else:
            active_tech_types.append(tech)
    if not active_tech_types:
        return None
    tech_types = active_tech_types

    ## load drilling cost curves
    geo_cost_curves = pd.read_csv(os.path.join(inputs_case, 'geo_cost_curves.csv'))
    geo_cost_coeffs = geo_cost_curves[geo_cost_curves['scenario'] == plantchar_geo].iloc[0]
    c1, c2, c3 = geo_cost_coeffs['c1'], geo_cost_coeffs['c2'], geo_cost_coeffs['c3']

    ## load ATB reference data
    geo_atb_ref = pd.read_csv(os.path.join(inputs_case, 'geo_ATB_reference.csv'))
    ## placeholders for drilling cost as share of total capital cost
    drilling_percent = {1: 23, 2: 25, 3: 25, 4: 25, 5: 25, 6: 25, 7: 30, 8: 30, 9: 30, 10: 30, }

    ## function to calculate drilling cost adjustment based on depth
    def calc_drilling_cost(depth):
        return c1 * (depth**2) + c2 * depth + c3
    
    all_multipliers = []

    for tech in tech_types:
        depths_file = os.path.join(inputs_case, f'{tech}_rep_depths.csv')
        if not os.path.exists(depths_file):
            print(f"Warning: no file found for {tech}")
            continue
        depths_data = pd.read_csv(depths_file)

        # get reference depths
        tech_ref_data = geo_atb_ref[(geo_atb_ref['tech'] == tech) & (geo_atb_ref['geoscen'] == plantchar_geo)]
        if tech_ref_data.empty:
            print(f"Warning: no ATB reference data found for {tech} and ATB scenario: {plantchar_geo}")
            continue
        class_to_ref_depth = tech_ref_data.set_index('geo_class')['ref_depth'].to_dict()
        ## calculate cost multipliers for each depth record
        # drop rows whose class has no ATB reference depth
        depths_data = depths_data[depths_data['class'].isin(class_to_ref_depth)].copy()

        # vectorized multiplier calculation
        depths_data['ref_depth']       = depths_data['class'].map(class_to_ref_depth)
        depths_data['drill_ratio']     = (
            calc_drilling_cost(depths_data['rep_depth']) /
            calc_drilling_cost(depths_data['ref_depth'])
        )
        depths_data['drill_pct']       = depths_data['class'].map(lambda c: drilling_percent.get(c, 50))
        depths_data['occ_mult']        = (
            1 + (depths_data['drill_pct'] / 100) * (depths_data['drill_ratio'] - 1)
        ).round(4)

        binary_cost_conv = 1.0
        ff = depths_data['flash_fraction'].fillna(np.nan)
        depths_data['plant_cost_mult'] = np.where(
            ff.isna(), 1.0,
            np.where(
                depths_data['class'] <= 6,
                ff + (1 - ff) * binary_cost_conv,
                ff / binary_cost_conv + (1 - ff)
            )
        ).round(6)

        all_multipliers.append(depths_data[['r','tech','bin','ref_depth','rep_depth',
                                            'occ_mult','plant_cost_mult','capacity']])
    
    if not all_multipliers:
        return None  
    cost_multipliers = pd.concat(all_multipliers, ignore_index=True)

    # aggregate to one occ_mult & plant_cost_mult per (r,tech) using capacity weights when available
    cost_multipliers['capacity'] = cost_multipliers['capacity'].fillna(0.0)
    use_weights = cost_multipliers['capacity'].sum() > 0

    def wavg(g, col):
        return (np.average(g[col], weights=g['capacity'])
                if use_weights else g[col].mean())

    agg = (
        cost_multipliers.groupby(['r','tech'])
        .apply(lambda g: pd.Series({
            'occ_mult':        wavg(g, 'occ_mult'),
            'plant_cost_mult': wavg(g, 'plant_cost_mult'),
        }))
        .reset_index()
    )

    # combine into a single total multiplier if you prefer
    agg['total_mult'] = (agg['occ_mult'].astype(float) * agg['plant_cost_mult'].astype(float))

    # write fractional diff values for egs_cost_cap_mult.csv
    agg['value'] = agg['total_mult'] - 1.0
    
    ret = agg.copy()
    # rename tech -> *i
    ret = ret.rename(columns={'tech': '*i'})
    # keep only requested columns in the exact order
    ret = ret[['*i', 'r', 'value']]

    # overwrite aggregated output file with the exact long format expected downstream
    out_agg_long = os.path.join(inputs_case, f'{tech_type}_cap_cost_mult.csv' if tech_type else 'geo_cap_cost_mult.csv')
    ret.to_csv(out_agg_long, index=False)

    return ret
