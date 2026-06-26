#%%### General imports
import os
import traceback
import pandas as pd
import numpy as np
from glob import glob
import re
import matplotlib.pyplot as plt
from typing import Literal

import reeds
from reeds.input_processing import hourly_writetimeseries

# #%% Debugging
# sw['reeds_path'] = os.path.expanduser('~/github/ReEDS/')
# sw['casedir'] = os.path.join(sw['reeds_path'],'runs','v20230123_prmM3_Pacific_d7sIrh4sh2_y2')
# import importlib
# importlib.reload(functions)

CVAR_METRICS = {'CVAR', 'NCVAR'}


#%%### Functions
def get_pras_stress_metric(case, t, iteration=0, stress_metric:Literal['EUE','LOLE']='EUE'):  
    """
    """
    ### Get PRAS outputs

    dfpras = reeds.io.read_pras_results(
        os.path.join(case, 'handoff', 'PRAS', f"PRAS_{t}i{iteration}.h5")
    )
    ### Create the time index
    sw = reeds.io.get_switches(case)
    dfpras.index = reeds.timeseries.get_timeindex(sw['resource_adequacy_years'])

    ### Keep the metric columns by zone
    metric_tail = '_' + stress_metric.upper()
    dfmetric = dfpras[[
        c for c in dfpras
        if (c.endswith(metric_tail) and not c.startswith('USA'))
    ]].copy()
    ## Drop the tailing metric tail
    dfmetric = dfmetric.rename(
        columns=dict(zip(dfmetric.columns, [c[:-len(metric_tail)] for c in dfmetric])))

    return dfmetric


def get_stress_metric_periods(
        case, t, iteration=0,
        hierarchy_level='transgrp',
        stress_metric='EUE',
        period_agg_method='sum',
    ):
    """_summary_

    Args:
        sw (pd.series): ReEDS switches for this run.
        t (int): Model solve year.
        iteration (int, optional): Iteration number of this solve year. Defaults to 0.
        hierarchy_level (str, optional): column of hierarchy.csv specifying the spatial
            level over which to calculate stress_metric. Defaults to 'country'.
        stress_metric (str, optional): 'EUE' or 'NEUE'. Defaults to 'EUE'.
        period_agg_method (str, optional): 'sum' or 'max', indicating how to aggregate
            over the hours in each period. Defaults to 'sum'.

    Raises:
        NotImplementedError: if invalid value for stress_metric or GSw_PRM_StressModel

    Returns:
        pd.DataFrame: Table of periods sorted in descending order by stress metric.
    """
    sw = reeds.io.get_switches(case)
    ### Get the region aggregator
    rmap = reeds.io.get_rmap(case=case, hierarchy_level=hierarchy_level)

    ### Get stress metric from PRAS
    # Use EUE metric for both EUE and NEUE calculations, since the load division to get NEUE is
    # peformed afterwards based on agg_period. 
    use_metric_for_pras = {'EUE':'EUE', 'NEUE':'EUE', 'LOLH':'LOLE'}
    dfmetric = get_pras_stress_metric(
        case=case,
        t=t,
        iteration=iteration,
        stress_metric=use_metric_for_pras.get(stress_metric)
    )
    ## Aggregate to hierarchy_level
    dfmetric = (
        dfmetric
        .rename_axis('r', axis=1).rename_axis('h', axis=0)
        .rename(columns=rmap).groupby(axis=1, level=0).sum()
    )

    ###### Calculate the stress metric by period
    dfmetric_period = (
        dfmetric
        .groupby([dfmetric.index.year, dfmetric.index.month, dfmetric.index.day])
        .agg(period_agg_method)
        .rename_axis(['y','m','d'])
    )  

    ### Sort and drop zeros and duplicates
    dfmetric_top = (
        dfmetric_period.stack('r')
        .sort_values(ascending=False)
        .replace(0,np.nan).dropna()
        .reset_index().drop_duplicates(['y','m','d'], keep='first')
        .set_index(['y','m','d','r']).squeeze(1).rename(stress_metric)
        .reset_index('r')
    )
    ## Convert to timestamp, then to ReEDS period
    dfmetric_top['actual_period'] = [
        reeds.timeseries.timestamp2h(pd.Timestamp(*d), sw['GSw_HourlyType']).split('h')[0]
        for d in dfmetric_top.index.values
    ]

    return dfmetric_top


def plot_stress_diagnostics(sw, t, iteration, high_stress_periods):
    try:
        dates = (
            pd.concat(high_stress_periods)
            .reset_index().actual_period.map(reeds.timeseries.h2timestamp)
            .dt.strftime('%Y-%m-%d')
            .tolist()
        )
        vmax = {'forced': 40, 'scheduled': 25, 'both': 50}
        aggfunc = 'max'
        for outage_type in vmax:
            savename = f'map-outage_{outage_type}_{aggfunc}-{t}i{iteration}.png'
            plt.close()
            f, ax, _ = reeds.reedsplots.map_outage_days(
                sw.casedir,
                dates=dates,
                outage_type=outage_type,
                aggfunc=aggfunc,
                vmax=vmax[outage_type],
            )
            plt.savefig(
                os.path.join(sw.casedir, 'outputs', 'figures', 'resource_adequacy', savename)
            )
            plt.close()
    except Exception as err:
        print(err)


def get_and_write_neue(sw, write=True):
    """
    Write dropped load across all completed years to outputs
    so it can be plotted alongside other ReEDS outputs.

    Notes
    -----
    * The denominator of NEUE is exogenous electricity demand; it does not include
    endogenous load from losses or H2 production or exogenous H2 demand.
    """
    infiles = [
        i for i in sorted(glob(
            os.path.join(sw['casedir'], 'handoff', 'PRAS', 'PRAS_*.h5')))
        if re.match(r"PRAS_[0-9]+i[0-9]+.h5", os.path.basename(i))
    ]
    eue = {}
    for infile in infiles:
        year_iteration = os.path.basename(infile)[len('PRAS_'):-len('.h5')].split('i')
        year = int(year_iteration[0])
        iteration = int(year_iteration[1])
        eue[year,iteration] = reeds.io.read_pras_results(infile)['USA_EUE'].sum()
    eue = pd.Series(eue).rename('MWh')
    eue.index = eue.index.rename(['year','iteration'])

    load = reeds.io.read_file(os.path.join(sw['casedir'],'inputs_case','load.h5'))
    loadyear = load.sum(axis=1).groupby('year').sum()

    neue = (
        (eue / loadyear * 1e6).rename('NEUE [ppm]')
        .rename_axis(['t','iteration']).sort_index()
    )

    if write:
        neue.to_csv(os.path.join(sw['casedir'],'outputs','neue.csv'))
        eue.to_csv(os.path.join(sw['casedir'],'outputs','eue.csv'))
    return neue

def get_cvar_alpha(sw):
    alpha = float(sw.GSw_PRM_CVARAlpha)
    if not (0 <= alpha < 1):
        raise ValueError(f"GSw_PRM_CVARAlpha must be in [0, 1). Got {alpha}")
    return alpha


def get_shortfall_totals_by_sample(case, t, iteration=0):
    filepath = os.path.join(case, 'handoff', 'PRAS', f'PRAS_{t}i{iteration}-shortfall_totals_by_sample.h5')
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"{filepath} not found. Re-run PRAS with --write_shortfall_samples_totals 1.")
    df = reeds.io.read_pras_results(filepath)
    df.columns = df.columns.astype(str)
    if 'sample' in df.columns:
        df = df.set_index('sample')
    elif df.index.name != 'sample':
        df.index = pd.RangeIndex(1, len(df) + 1, name='sample')
    return df.apply(pd.to_numeric, errors='coerce').clip(lower=0)


def _sample_cvar(samples, alpha=0.95):
    x = pd.Series(samples).dropna().astype(float)
    if x.empty:
        return np.nan
    n_tail = max(1, int(np.ceil((1 - alpha) * len(x))))
    return x.sort_values(ascending=False).iloc[:n_tail].mean()


def get_annual_cvar_stress_metric(case, t, stress_metric='NCVAR', iteration=0, alpha=0.95):
    stress_metric = stress_metric.upper()
    if stress_metric not in CVAR_METRICS:
        raise NotImplementedError(f"get_annual_cvar_stress_metric only supports {CVAR_METRICS}. Got {stress_metric}.")

    ### Read per-sample total shortfall by region from PRAS.
    shortfall_samples = get_shortfall_totals_by_sample(case=case, t=t, iteration=iteration).drop(columns=['USA'], errors='ignore')

    ### Read hourly PRAS load. This is used to normalize CVAR into NCVAR.
    dfload = reeds.io.read_h5py_file(os.path.join(case, 'handoff', 'reeds_data', f'pras_load_{t}.h5'))

    ### Calculate CVAR/NCVAR at each supported hierarchy level.
    levels = ['country','interconnect','nercr','transreg','transgrp','st','r']
    _metric = {}
    for hierarchy_level in levels:
        ### Aggregate sample-level regional shortfall to the requested hierarchy level.
        rmap = reeds.io.get_rmap(case=case, hierarchy_level=hierarchy_level)
        regions = [c for c in shortfall_samples.columns if c in rmap.index]
        if not regions:
            continue

        shortfall_agg = shortfall_samples[regions].rename(columns=rmap).groupby(axis=1, level=0).sum()

        ### CVAR is the average of the highest-shortfall samples in the alpha tail.
        cvar = shortfall_agg.apply(lambda s: _sample_cvar(s, alpha=alpha), axis=0)

        if stress_metric == 'NCVAR':
            ### NCVAR normalizes CVAR by total load over the PRAS time period and reports ppm.
            load_regions = [c for c in dfload.columns if c in rmap.index]
            load_agg = dfload[load_regions].rename(columns=rmap).groupby(axis=1, level=0).sum().sum()
            cvar = cvar / load_agg.reindex(cvar.index) * 1e6

        _metric[hierarchy_level,'cvar'] = cvar

    return pd.concat(_metric, names=['level','metric','region']).rename(stress_metric)

def evaluate_cvar_target_check(sw, t, iteration=0, stress_metrics=None):
    if stress_metrics is None:
        stress_metrics = sw.GSw_PRM_StressThresholdMetrics.split('/')

    ### Only evaluate CVAR/NCVAR here. Standard metrics are handled by _evaluate_stress_threshold_criterion(), which can add stress periods.
    stress_metrics = [m.upper() for m in stress_metrics if str(m).strip()]
    cvar_metrics = [m for m in stress_metrics if m in CVAR_METRICS]
    if not cvar_metrics:
        return pd.DataFrame()

    records = []
    for metric in cvar_metrics:
        switch_name = f'GSw_PRM_StressThreshold{metric}'
        if switch_name not in sw.index:
            print(f"Warning: {metric} is listed in GSw_PRM_StressThresholdMetrics, but {switch_name} is not defined. Skipping {metric} target check.")
            continue

        for criterion in str(sw[switch_name]).split('/'):
            criterion = criterion.strip()
            if not criterion:
                continue

            ### CVAR/NCVAR criteria are check-only and use: HierarchyLevel_Threshold_Metric_cvar
            hierarchy_level, stress_level, stress_metric, metric_name = criterion.split('_')
            stress_metric = stress_metric.upper()
            metric_name = metric_name.lower()

            if stress_metric not in CVAR_METRICS:
                raise ValueError(f"Invalid CVAR criterion: {criterion}. Metric must be one of {CVAR_METRICS}.")
            if metric_name != 'cvar':
                raise ValueError(f"Invalid CVAR criterion: {criterion}. The fourth field must be 'cvar'.")

            ### Read the annual CVAR/NCVAR metric written earlier in main().
            stress_vals = pd.read_csv(
                os.path.join(sw.casedir, 'outputs', f'{stress_metric.lower()}_{t}i{iteration}.csv'),
                index_col=['level','metric','region'],
            ).squeeze(1)

            ### Compare each region against the check-only threshold.
            this_test = stress_vals.xs((hierarchy_level, 'cvar'), level=['level','metric'])
            threshold = float(stress_level)

            for region, value in this_test.items():
                records.append({'criterion':criterion, 'level':hierarchy_level, 'metric':stress_metric, 'region':region, 'alpha':get_cvar_alpha(sw), 'threshold':threshold, 'value':value, 'passed':value <= threshold})

            failed = this_test.loc[this_test > threshold]
            if len(failed):
                print(f"GSw_PRM_StressThreshold = {criterion} failed for:")
                print(failed)
                print(f"{stress_metric} is check-only: no stress periods and no PRM increment will be added.")
            else:
                print(f"GSw_PRM_StressThreshold = {criterion} passed")

    dfcheck = pd.DataFrame(records)
    if not dfcheck.empty:
        dfcheck.to_csv(os.path.join(sw.casedir, 'outputs', f'cvar_target_check_{t}i{iteration}.csv'), index=False)
    return dfcheck

def get_annual_stress_metric(case, t, stress_metric, iteration=0):
    """
    """
    ### Get values from PRAS
    use_metric_for_pras = {'EUE':'EUE', 'NEUE':'EUE', 'LOLH':'LOLE'}  
    dfmetric = get_pras_stress_metric(  
        case=case,  
        t=t,  
        iteration=iteration,  
        stress_metric=use_metric_for_pras[stress_metric],  
    )  

    ### Get load (for calculating NEUE)
    if stress_metric.upper() == 'NEUE':
        dfload = reeds.io.read_h5py_file(
            os.path.join(
                case,'handoff','reeds_data',f'pras_load_{t}.h5')
        )
        dfload.index = dfmetric.index

    levels = ['country','interconnect','nercr','transreg','transgrp','st','r']
    _metric = {}
    for hierarchy_level in levels:
        ### Get the region aggregator
        rmap = reeds.io.get_rmap(case=case, hierarchy_level=hierarchy_level)

        ### Get stress metric summed over year
        _metric[hierarchy_level,'sum'] = dfmetric.rename(columns=rmap).groupby(axis=1, level=0).sum().sum()

        ### Get max stress metric hour
        _metric[hierarchy_level,'max'] = dfmetric.rename(columns=rmap).groupby(axis=1, level=0).sum().max()

        if stress_metric.upper() == 'NEUE':
            _metric[hierarchy_level,'sum'] = (
                dfmetric.rename(columns=rmap).groupby(axis=1, level=0).sum().sum()
                / dfload.rename(columns=rmap).groupby(axis=1, level=0).sum().sum()
            ) * 1e6
            ### Get max NEUE hour
            _metric[hierarchy_level,'max'] = (
                dfmetric.rename(columns=rmap).groupby(axis=1, level=0).sum()
                / dfload.rename(columns=rmap).groupby(axis=1, level=0).sum()
            ).max() * 1e6
        


    ### Combine it
    metric = pd.concat(_metric, names=['level','metric','region']).rename(f'{stress_metric}')

    return metric


def get_shoulder_periods(sw, criterion, dfenergy_r, high_eue_periods, stress_metric):
    ## Stop if not needed
    if sw.GSw_PRM_StressStorageCutoff.lower() in ['off', '0', 'false']:
        print(
            f"GSw_PRM_StressStorageCutoff={sw.GSw_PRM_StressStorageCutoff} "
            "so not adding shoulder stress periods based on storage level"
        )
        return {}
    if dfenergy_r.empty:
        print(
            "No storage capacity, so no shoulder stress periods will be added "
            "based on storage level"
        )
        return {}

    ## Parse inputs
    hierarchy = reeds.io.get_hierarchy(sw.casedir)
    timeindex = reeds.timeseries.get_timeindex(sw['resource_adequacy_years'])
    cutofftype, cutoff = sw.GSw_PRM_StressStorageCutoff.lower().split('_')
    periodhours = {'day':24, 'wek':24*5, 'year':24}[sw.GSw_HourlyType]
    (hierarchy_level, stress_value, period_agg_method) = criterion.split('_')

    ## Aggregate storage energy to hierarchy_level
    dfenergy_agg = (
        dfenergy_r.rename(columns=hierarchy[hierarchy_level])
        .groupby(axis=1, level=0).sum()
    )
    dfheadspace_MWh = dfenergy_agg.max() - dfenergy_agg
    dfheadspace_frac = dfheadspace_MWh / dfenergy_agg.max()

    shoulder_periods = {}
    for i, row in high_eue_periods[criterion, f'high_{stress_metric}'].iterrows():
        if row.r not in dfheadspace_MWh:
            continue

        day = pd.Timestamp('-'.join(row[['y','m','d']].astype(str).tolist()))

        start_headspace_MWh = dfheadspace_MWh.loc[day.strftime('%Y-%m-%d'),row.r].iloc[0]
        end_headspace_MWh = dfheadspace_MWh.loc[day.strftime('%Y-%m-%d'),row.r].iloc[-1]

        start_headspace_frac = dfheadspace_frac.loc[day.strftime('%Y-%m-%d'),row.r].iloc[0]
        end_headspace_frac = dfheadspace_frac.loc[day.strftime('%Y-%m-%d'),row.r].iloc[-1]

        day_eue = high_eue_periods[criterion, f'high_{stress_metric}'].loc[i,'EUE']
        day_index = np.where(
            timeindex == dfenergy_agg.loc[day.strftime('%Y-%m-%d')].iloc[0].name
        )[0][0]

        day_before = timeindex[day_index - periodhours]
        day_after = timeindex[(day_index + periodhours) % len(timeindex)]

        if (
            ((cutofftype == 'eue') and (end_headspace_MWh / day_eue >= float(cutoff)))
            or ((cutofftype[:3] == 'cap') and (end_headspace_frac  >= float(cutoff)))
            or (cutofftype[:3] == 'abs')
        ):
            shoulder_periods[criterion, f'after_{row.name}'] = pd.Series({
                'actual_period':day_after.strftime('y%Yd%j'),
                'y':day_after.year, 'm':day_after.month, 'd':day_after.day, 'r':row.r,
            }).to_frame().T.set_index('actual_period')
            print(f"Added {day_after} as shoulder stress period after {day}")

        if (
            ((cutofftype == 'eue') and (start_headspace_MWh / day_eue >= float(cutoff)))
            or ((cutofftype[:3] == 'cap') and (start_headspace_frac  >= float(cutoff)))
            or (cutofftype[:3] == 'abs')
        ):
            shoulder_periods[criterion, f'before_{row.name}'] = pd.Series({
                'actual_period':day_before.strftime('y%Yd%j'),
                'y':day_before.year, 'm':day_before.month, 'd':day_before.day, 'r':row.r,
            }).to_frame().T.set_index('actual_period')
            print(f"Added {day_before} as shoulder stress period before {day}")

    return shoulder_periods


def _evaluate_stress_threshold_criterion(  
    stress_criteria,  
    criterion,  
    sw,  
    t,  
    iteration,  
    dfenergy_r,  
    stressperiods_this_iteration,  
    stress_metric,  
): 
    _stress_sorted_periods = stress_criteria['stress_sorted_periods']
    _failed = stress_criteria['failed']
    _high_stress_periods = stress_criteria['high_stress_periods']
    _shoulder_periods = stress_criteria['shoulder_periods']
                                                                                                        
    ## NEUE Example: criterion = 'transgrp_1_sum' 
    (hierarchy_level, stress_value, period_agg_method) = criterion.split('_')

    ### Get stored stress metric
    stress_vals = pd.read_csv(
        os.path.join(sw.casedir, 'outputs', f'{stress_metric.lower()}_{t}i{iteration}.csv'),
        index_col=['level', 'metric', 'region'],
    ).squeeze(1)

    stress_periods = get_stress_metric_periods(
        case=sw.casedir, t=t, iteration=iteration,
        hierarchy_level=hierarchy_level,
        stress_metric=stress_metric,
        period_agg_method=period_agg_method,
    )

    ### Sort in descending stress_metric order
    _stress_sorted_periods[criterion] = (
        stress_periods
        .sort_values(stress_metric, ascending=False)
        .reset_index().set_index('actual_period')
    )

    ### Get the threshold(s) and see if any of them failed
    this_test = stress_vals[hierarchy_level][period_agg_method]

    if (this_test > float(stress_value)).any():
        _failed[criterion] = this_test.loc[this_test > float(stress_value)]
        print(f"GSw_PRM_StressThreshold = {criterion} failed for:")
        print(_failed[criterion])
        ###### Add GSw_PRM_StressIncrement periods to the list for the next iteration
        _high_stress_periods[criterion, f'high_{stress_metric}'] = (
            _stress_sorted_periods[criterion].loc[
                ## Only include new stress periods for the region(s) that failed
                _stress_sorted_periods[criterion].r.isin(_failed[criterion].index)
                ## Don't repeat existing stress periods
                & ~(_stress_sorted_periods[criterion].index.isin(
                    stressperiods_this_iteration.actual_period))
            ]
            ## Don't add dates more than once
            .drop_duplicates(subset=['y','m','d'])
            ## Keep the GSw_PRM_StressIncrement worst periods for each region.
            ## If you instead want to keep the GSw_PRM_StressIncrement worst periods
            ## overall, use .nlargest(int(sw.GSw_PRM_StressIncrement), stress_metric)
            .groupby('r').head(int(sw.GSw_PRM_StressIncrement))
        )
        for period, row in _high_stress_periods[criterion, f'high_{stress_metric}'].iterrows():
            print(
                f"Added {period} "
                f"({reeds.timeseries.h2timestamp(period).strftime('%Y-%m-%d')}) "
                f"as stress period for {row.r} "
                f"({stress_metric} = {row[stress_metric]})"
            )

        ### Include "shoulder periods" before or after each period
        ### if the storage state of charge is low
        use_metric_for_shoulder_periods = {'EUE':'EUE', 'NEUE':'NEUE', 'LOLH':'EUE'}  
        _shoulder_periods = {
            **_shoulder_periods,
            **get_shoulder_periods(sw, criterion, dfenergy_r, _high_stress_periods, stress_metric=use_metric_for_shoulder_periods.get(stress_metric))
        }

        stress_criteria['stress_sorted_periods'] = _stress_sorted_periods
        stress_criteria['failed'] = _failed
        stress_criteria['high_stress_periods'] = _high_stress_periods
        stress_criteria['shoulder_periods'] = _shoulder_periods
        
    else:
        print(f"GSw_PRM_StressThreshold = {criterion} passed")

    return stress_criteria
    

def get_stress_metrics_sorted_periods(sw, t, iteration):
    stress_metric_switches = [m.upper() for m in sw.GSw_PRM_StressThresholdMetrics.split('/') if str(m).strip() and m.upper() not in CVAR_METRICS]
    if not stress_metric_switches:
        return {}, None, None

    ### Get storage state of charge (SOC) to use in selection of "shoulder" stress periods
    dfenergy = reeds.io.read_pras_results(
        os.path.join(sw['casedir'], 'handoff', 'PRAS', f"PRAS_{t}i{iteration}-energy.h5")
    )
    timeindex = reeds.timeseries.get_timeindex(sw['resource_adequacy_years'])
    dfenergy.index = timeindex
    ## Sum by region
    dfenergy_r = (
        dfenergy
        .rename(columns={c: c.split('|')[1] for c in dfenergy.columns})
        .groupby(axis=1, level=0).sum()
    )

    ### Load this year's stress periods so we don't duplicate
    stressperiods_this_iteration = pd.read_csv(
        os.path.join(
            sw['casedir'], 'inputs_case', f'stress{t}i{iteration}', 'period_szn.csv')
    )

    ### Check all stress criteria; for regions that fail, add new stress periods
    stress_criteria = {'stress_sorted_periods': {}, 'failed': {}, 'high_stress_periods': {}, 'shoulder_periods': {}}
  
    # stress periods column names for writing outputs
    stress_metrics_units = {'EUE':'MWh/year', 'NEUE':'ppm', 'LOLH':'event-h/year', 'LOLE':'event-day/year'}
    stress_metrics_col_names = {m:f'{m}_{stress_metrics_units[m]}' for m in 
                                stress_metric_switches}
    
    for stress_metric in stress_metric_switches:
        for criterion in sw[f'GSw_PRM_StressThreshold{stress_metric.upper()}'].split('/'):
            print(f"Evaluating GSw_PRM_StressThreshold {stress_metric.upper()} with criterion: {criterion}")
            stress_criteria = _evaluate_stress_threshold_criterion(
                stress_criteria,
                criterion,
                sw,
                t,
                iteration,
                dfenergy_r,
                stressperiods_this_iteration,
                stress_metric
            )
            
    stress_sorted_periods = stress_criteria['stress_sorted_periods']
    failed = stress_criteria['failed']
    high_stress_periods = stress_criteria['high_stress_periods']
    shoulder_periods = stress_criteria['shoulder_periods']

    stress_sorted_periods = pd.concat(stress_sorted_periods, names=['criterion'])

    ### Get lists of stress periods: new (added this iteration) and all
    ##TODO: What if same high stress period is added for multiple criteria?
    # Currently the duplicates are dropped. 
    if len(failed):
        new_stress_periods = pd.concat(
            {**high_stress_periods, **shoulder_periods}, names=['criterion','periodtype'],
        ).reset_index().drop_duplicates(subset='actual_period', keep='first')
    else:
        return failed, None, None

    ## Reproduce the format of inputs_case/stress_period_szn.csv
    p = 'w' if sw.GSw_HourlyType == 'wek' else 'd'
    new_stressperiods_write = pd.DataFrame({
        'rep_period': new_stress_periods.actual_period,
        'year': new_stress_periods.actual_period.map(
            lambda x: int(x.strip('sy').split(p)[0])),
        'yperiod': new_stress_periods.actual_period.map(
            lambda x: int(x.strip('sy').split(p)[1])),
        'actual_period': new_stress_periods.actual_period,
    })

    ### Add new stress periods to the stress periods used for this year/iteration, then write
    newstresspath = f'stress{t}i{iteration+1}'
    os.makedirs(os.path.join(sw['casedir'], 'inputs_case', newstresspath), exist_ok=True)
    outpath = os.path.join(sw['casedir'], 'inputs_case', newstresspath, 'period_szn.csv')

    combined_periods_write = pd.concat(
        [stressperiods_this_iteration, new_stressperiods_write],
        axis=0,
    ).drop_duplicates(keep='first')

    if int(sw.GSw_PRM_CapCredit):
        pd.DataFrame(columns=['rep_period','year','yperiod','actual_period']).to_csv(
            outpath,
            index=False,
        )
    else:
        combined_periods_write.to_csv(outpath, index=False)

    ### Tables and plots for debugging
    stress_sorted_periods.round(2).rename(columns=stress_metrics_col_names).to_csv(
        os.path.join(sw.casedir, 'inputs_case', newstresspath, 'stress_metrics_sorted_periods.csv')
    )
    new_stress_periods.round(2).rename(columns=stress_metrics_col_names).to_csv(
        os.path.join(sw.casedir, 'inputs_case', newstresspath, 'new_stress_periods.csv'),
        index=False,
    )
    plot_stress_diagnostics(sw, t, iteration, high_stress_periods)

    return failed, new_stressperiods_write, combined_periods_write


def prm_increment_pras(sw, t, iteration, combined_periods_write, failed_regions):
    try:
        hmap = pd.read_csv(
            os.path.join(sw.casedir, 'inputs_case', f'stress{t}i{iteration+1}', 'hmap_allyrs.csv')
        )
        stress_hours = hmap.loc[
            hmap.actual_period.str.contains('|'.join(combined_periods_write.actual_period))
        ]
    except FileNotFoundError:
        # if there are no stress periods being modeled, use dispatch year to
        # fill in for stress hours
        stress_hours = pd.read_csv(
            os.path.join(sw.casedir, 'inputs_case', 'rep', 'hmap_myr.csv')
        )

    ## shortfall data
    net_short_totals = get_shortfall_totals_by_sample(case=sw['casedir'], t=t, iteration=iteration)
    n_samples = len(net_short_totals)
    net_short_crit = (
        net_short_totals
        .drop(columns=['USA'], errors='ignore')
        .reset_index()
        .melt(id_vars='sample', var_name='r', value_name='net_short_mwh')
    )
    net_short_crit['net_short_mwh'] = net_short_crit['net_short_mwh'].clip(lower=0)

    ## get load data
    dfload = reeds.io.read_file(
        os.path.join(
        sw['casedir'],'handoff','reeds_data',f'pras_load_{t}.h5'),
        parse_timestamps=True
    )

    # add an index to represent each hour
    dfload = dfload.reset_index().reset_index().rename(columns={"index":"hour"})

    # melt to long
    dfload = dfload.melt(id_vars=['datetime', 'hour'], var_name='r', value_name='load_mwh')

    ## get regional load for (1) all hours (2) just the stress periods
    ## total load is used to translate the ppm target to EUE, whereas
    ## the stress period load is used to back-calculate the incremental prm
    ## needed to get to the target

    # total load by r
    dfload_all = dfload.groupby(['r'], as_index=False)['load_mwh'].sum()

    # total stress period load by r
    # note: use hour0 to subset to stress periods here since load data starts with hour index 0
    dfload_stress = dfload.loc[dfload.hour.isin(stress_hours.hour0)]
    dfload_stress = dfload_stress.groupby(['r'], as_index=False)['load_mwh'].sum()
    dfload_stress = dfload_stress.rename(columns={'load_mwh':'stress_load_mwh'})

    # combine
    dfload_all = dfload_all.merge(dfload_stress)

    # transform the reliability target criteria by region from ppm into
    # unserved energy (MWh)
    dfload_all = dfload_all.merge(failed_regions, on='r')
    dfload_all['target_eue_mwh'] = (
        dfload_all['ppm'] / 1e6 * dfload_all['load_mwh']
    )

    ## calculate piece-wise linear function (plf) that estimates the change in EUE
    ## across the samples as a function of the amount of surplus added added to address
    ## unserved energy in each sample each segment of the plf is defined by a slope and
    ## two points: (x1, y1) and (x2, y2)
    plfs = net_short_crit.loc[net_short_crit.net_short_mwh > 0].copy()
    ## y-intercept: initial EUE
    plfs['intercept'] = plfs.groupby('r')['net_short_mwh'].transform('sum') / n_samples
    ## slope: computed from the lolp based on the remaining periods with unserved energy
    ## as surplus is added sort unserved by descending first to calculate slopes
    plfs = plfs.sort_values(['r', 'net_short_mwh'], ascending=False)
    plfs['slope'] = -1
    plfs['slope'] = plfs.groupby(['r'])['slope'].transform('cumsum') / n_samples
    # resort in ascending order for later calculations
    plfs = plfs.sort_values(['r', 'net_short_mwh'], ascending=True)
    ## x1: surplus to add to eliminate unserved energy from previous sample
    plfs['x1'] = plfs.groupby('r')['net_short_mwh'].shift(1, fill_value=0)
    ## x2: surplus to add to eliminate unserved energy from this sample
    plfs['x2'] = plfs['net_short_mwh']
    # compute change in y value over each segment
    plfs['Dy'] = plfs['slope'] * (plfs['x2']-plfs['x1'])
    # check: Dy should never be positive
    assert plfs['Dy'].max() <= 0, "Error in Dy calculation"
    ## y1: intercept + cumulative change in unserved (Dy)
    plfs['y1'] = plfs['intercept'] + plfs.groupby('r')['Dy'].transform(
                                                lambda x: x.cumsum().shift(1, fill_value=0))
    ## y2: y1 + change over that segment (next y1 value)
    plfs['y2'] = plfs.groupby('r')['y1'].shift(-1, fill_value=0)

    # now merge load merge with plf functions to find the segment that captures the target
    plfs = plfs.merge(dfload_all, on='r')
    plfs['seg'] = 0
    plfs.loc[(plfs['target_eue_mwh']<=plfs['y1']) & (
        plfs['target_eue_mwh']>=plfs['y2']), 'seg'] = 1
    # calculate the energy surplus to add by backtracking from the target_eue on the
    # relevant segment(y): y=a+b*x => x=(y-a)/b
    prm_increment = plfs.loc[plfs['seg']==1].copy()
    prm_increment['surplus_mwh'] = prm_increment['x1'] + (
        prm_increment['target_eue_mwh'] - prm_increment['y1']) * (1 / prm_increment['slope'])
    # calculate the prm increase as the required surplus as a fraction of
    # load during stress periods
    prm_increment['fraction'] = (
        prm_increment['surplus_mwh'] / prm_increment['stress_load_mwh']
    )
    prm_increment = prm_increment[['r','fraction']].reset_index(drop=True)
    return prm_increment


def update_prm(sw, t, iteration, failed, combined_periods_write):
    """Update the energy reserve margin by region r for stress periods, either using a
    static increment (GSw_PRM_UpdateMethod=1) or based on the estimated surplus needed by PRAS
    to recover the desired reliabiliaty criteria (GSw_PRM_UpdateMethod>1).

    Args:
        sw (pd.series): ReEDS switches for this run.
        t (int): Model solve year.
        iteration (int): ReEDS-PRAS iteration
        failed (dict): Dictionary of regions with unserved energy at the hierarchy_level
                       and their criterion evaluations
        combined_periods_write (pd.DataFrame): Data frame of combined stress periods
    

    Returns:
        pd.DataFrame: Table of prm levels for the next PRAS iteration
    """
    # Get regions that failed criteria
    # Use NEUE-based failed regions only
    _failed_regions = []
    for criterion in failed:
        if not failed[criterion].name == 'NEUE':
            continue
        # Example: criterion = 'transgrp_10_sum'
        (hierarchy_level, stress_value, __) = criterion.split('_')
        # Recover regions where the PRM criterion failed
        rmap = reeds.io.get_rmap(sw['casedir'], hierarchy_level=hierarchy_level).reset_index()
        df = rmap.loc[
            rmap[hierarchy_level].isin(failed[criterion].index)
        ].rename(columns={hierarchy_level:'region'})
        df['hierarchy_level'] = hierarchy_level
        df['stress_value'] = float(stress_value)
        _failed_regions.append(df)
    # For zones that failed multiple criteria, use the most stringent (lowest EUE target)
    failed_regions = (
        pd.concat(_failed_regions)
        .sort_values(by=['stress_value'])
        .drop_duplicates(subset='r', keep='first')
    )    

    ## Fixed-increment update
    if int(sw.GSw_PRM_UpdateMethod) == 1:
        prm_increment = failed_regions.copy()
        prm_increment['fraction'] = float(sw['GSw_PRM_UpdateFraction'])
    ## PRAS-informed PRM update
    else:
        prm_increment = prm_increment_pras(
            sw,
            t,
            iteration,
            combined_periods_write,
            failed_regions,
        )
    prm_increment = (
        prm_increment.rename(columns={'r':'*r'})
        .set_index('*r').fraction
    )

    ## Add the PRM increment to last iteration's PRM
    prm = pd.read_csv(
        os.path.join(sw['casedir'], 'inputs_case', f'stress{t}i{iteration}', 'prm.csv'),
        index_col='*r',
    ).fraction
    prm_next_iteration = prm.add(prm_increment, fill_value=0).round(3)

    return prm_next_iteration


#%%### Procedure
def main(sw, t, iteration=0, logging=True):
    """
    """
    #%% Write consolidated stress metrics so far
    try:
        ## TODO: Check if get_and_write_neue() is still needed.
        # get_and_write_neue() writes outputs/neue.csv and outputs/eue.csv across
        # completed PRAS years. The annual metric files below are still written per
        # solve year / iteration.
        _neue_simple = get_and_write_neue(sw, write=True)
        ## TODO: check if need to refactor or remove

        for stress_metric in ['EUE', 'NEUE', 'LOLH']:
            print(f"Calculating and writing annual {stress_metric} for iteration {iteration}")
            dfmetric = get_annual_stress_metric(sw.casedir, t, stress_metric, iteration=iteration)

            # Metric thresholds are defined on a per-year basis, but PRAS reports the total over all resource adequacy years,
            # For all metrics except NEUE, divide by the number of resource adequacy years to get the average per year
            if stress_metric != 'NEUE':
                dfmetric /=  len(sw['resource_adequacy_years'])

            dfmetric.round(2).to_csv(
                os.path.join(sw.casedir, 'outputs', f"{stress_metric.lower()}_{t}i{iteration}.csv")
            )

        # CVAR / NCVAR are additional check-only metrics. They do not replace or modify the standard EUE / NEUE / LOLH calculations above.
        cvar_metrics = [m.upper() for m in sw.GSw_PRM_StressThresholdMetrics.split('/') if str(m).strip() and m.upper() in CVAR_METRICS]

        for stress_metric in cvar_metrics:
            print(f"Calculating and writing annual {stress_metric} for iteration {iteration}")

            dfmetric = get_annual_cvar_stress_metric(case=sw.casedir, t=t, stress_metric=stress_metric, iteration=iteration, alpha=get_cvar_alpha(sw),)

            # CVAR is an absolute MWh metric calculated across all resource-adequacy years, so convert it to annual average.
            # NCVAR is already normalized by total load and remains in ppm.
            if stress_metric == 'CVAR':
                dfmetric /= len(sw['resource_adequacy_years'])

            dfmetric.round(2).to_csv(os.path.join(sw.casedir,'outputs', f"{stress_metric.lower()}_{t}i{iteration}.csv",))

        # CVAR / NCVAR are check-only: no stress periods and no PRM increment.
        evaluate_cvar_target_check(sw=sw, t=t, iteration=iteration, stress_metrics=cvar_metrics,)

    except Exception as err:
        if int(sw['pras']) == 2:
            print(traceback.format_exc())
        if int(sw.GSw_PRM_StressIterateMax):
            raise Exception(err)

    #%% Stop here if not iterating or if before ReEDS can build new capacity
    if (not int(sw.GSw_PRM_StressIterateMax)) or (t < int(sw['GSw_StartMarkets'])):
        return

    #%% Identify and write new stress periods
    failed, new_stressperiods_write, combined_periods_write = get_stress_metrics_sorted_periods(
        sw=sw, t=t, iteration=iteration,
    )

    #%% Stop here if all thresholds pass or if there are no new stress periods
    if (
        (not len(failed))
        or ((len(new_stressperiods_write) == 0) and (int(sw.GSw_PRM_UpdateMethod) == 0))
    ):
        print('No new stress periods and no PRM update, so stopping here')
        return

    #%% Write timeseries data for stress periods for the next iteration of ReEDS
    newstresspath = f'stress{t}i{iteration+1}'
    hourly_writetimeseries.main(
        sw=sw, reeds_path=sw['reeds_path'],
        inputs_case=os.path.join(sw['casedir'], 'inputs_case'),
        periodtype=newstresspath,
        make_plots=0,
        logging=logging
    )

    #%% Write updated PRM values
    if (
        (int(sw.GSw_PRM_UpdateMethod) == 0)
        or (len(new_stressperiods_write) and (int(sw.GSw_PRM_UpdateMethod) == 3))
    ):
        ## Not updating PRM, so copy last year's
        prm_next_iteration = pd.read_csv(
            os.path.join(sw.casedir, 'inputs_case', f'stress{t}i{iteration}', 'prm.csv'),
            index_col='*r',
        )
    else:
        prm_next_iteration = update_prm(sw, t, iteration, failed, combined_periods_write)

    prm_next_iteration.to_csv(
        os.path.join(sw.casedir, 'inputs_case', newstresspath, 'prm.csv'),
    )

    #%% Done
    return

# if __name__ == '__main__':
#     #%%###  option to run script directly for debugging
#     casedir =  "/path/to/ReEDS/runs/runname"
#     t = 2030 # previous solve year
#     iteration = 0
#     # load switches
#     sw = reeds.io.get_switches(casedir)
#     sw['t'] = t
#     sw['GSw_PRM_UpdateMethod'] = 2
#     #%%###
#     main(sw, t, iteration, logging=False)
