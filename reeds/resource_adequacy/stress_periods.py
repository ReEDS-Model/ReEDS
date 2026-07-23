#%%### General imports
import os
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Literal

import reeds
from reeds.input_processing import hourly_writetimeseries

# #%% Debugging
# sw['reeds_path'] = os.path.expanduser('~/github/ReEDS/')
# sw['casedir'] = os.path.join(sw['reeds_path'],'runs','v20230123_prmM3_Pacific_d7sIrh4sh2_y2')
# import importlib
# importlib.reload(functions)


#%%### Constants
RA_SWITCHES = {
    i.lower(): f'GSw_PRM_StressThreshold{i}'
    for i in ['Depth', 'Duration', 'LOLD', 'LOLE', 'LOLH', 'NEUE']
}
SWITCH_METRIC = {
    'depth': 'euemax_peakloadfrac',
    'duration': 'max_duration',
    'lold': 'lold_peryear',
    'lole': 'lole_peryear',
    'lolh': 'lolh_peryear',
    'neue': 'neue_ppm',
}


#%%### Functions
def get_pras_shortfall(case, t, iteration=0):
    """
    Returns: dict of timeseries-indexed dataframes with two keys: 'EUE' and 'LOLE'
    """
    ### Get PRAS outputs
    dfpras = reeds.io.read_pras_results(
        os.path.join(case, 'handoff', 'PRAS', f"PRAS_{t}i{iteration}.h5")
    )
    ### Create the time index
    sw = reeds.io.get_switches(case)
    dfpras.index = reeds.timeseries.get_timeindex(sw['resource_adequacy_years'])

    ### Keep the metric columns by zone
    dictout = {}
    for metric in ['EUE', 'LOLE']:
        metric_tail = '_' + metric.upper()
        dfmetric = dfpras[[
            c for c in dfpras
            if (c.endswith(metric_tail) and not c.startswith('USA'))
        ]].copy()
        ## Drop the tailing metric tail
        dictout[metric] = dfmetric.rename(
            columns=dict(zip(
                dfmetric.columns,
                [c[:-len(metric_tail)] for c in dfmetric]
            ))
        )

    return dictout


def get_events(ds:pd.Series, threshold:float=0) -> pd.DataFrame:
    """Return a dataframe of events with max and duration"""
    starts = (
        ## Convert values > threshold to 1
        (ds > threshold).astype(int)
        ## +1 if changes from 0->1, -1 if changes from 1->0
        .diff()
        ## If the first value is > threshold, count it as a start
        .fillna((ds > threshold).astype(int))
        ## Only keep the beginnings
        > 0
    )
    starts = starts.loc[starts > 0].index
    ## Same idea for ends but reverse
    ends = (
        (ds > threshold).astype(int)
        .diff(-1)
        .fillna((ds > threshold).astype(int))
        > 0
    )
    ends = ends.loc[ends > 0].index
    assert len(starts) == len(ends), "Error in event start/end calculation"
    ## Get some metrics for each event
    events = []
    for start, end in zip(starts, ends):
        event = ds.loc[start:end]
        events.append({
            'start': start,
            'end': end,
            'timesteps': len(event),
            'max': event.max(),
            'sum': event.sum(),
            'profile': event.round(1).values,
        })
    if len(events):
        dfout = pd.DataFrame(events)
    else:
        dfout = pd.DataFrame(columns=['start','end','timesteps','max','sum','profile'])
    return dfout


def calc_lold(dflole_agg, threshold=0):
    """Count a day as an event-day if at least one hour has LOLE > threshold"""
    ## Take the max for each day
    ## (That's not quite right if the events are independent)
    daily_max = dflole_agg.resample('D').max()
    ## Sum the probability across days
    lold = daily_max.sum()
    return lold


def calc_lole(dflole_agg, threshold=0):
    """Number of events, where an event is >threshold LOLE in contiguous hours"""
    ## Get the loss-of-load events, keeping the max hourly probability for each
    ## (not really right probabilistically)
    lole = pd.Series({
        r: get_events(dflole_agg[r], threshold)['max'].sum() for r in dflole_agg
    })
    return lole


def calc_lolh(dflole_agg):
    """Event-hours, given by the sum of hourly LOLP across hours"""
    lolh = dflole_agg.sum()
    return lolh


def calc_max_duration(dfeue_agg, threshold=0):
    """Max event duration, where an event is >threshold EUE [MW] in contiguous hours"""
    max_duration = pd.Series({
        r: get_events(dfeue_agg[r], threshold)['timesteps'].max() for r in dfeue_agg
    }).fillna(0).astype(int)
    return max_duration


def calc_neue(dfeue_agg, dfload_agg):
    """NEUE (sum of EUE / sum of load) in units of ppm"""
    neue = dfeue_agg.sum() / dfload_agg.sum() * 1e6
    return neue


def calc_peak_eue(dfeue_agg, dfload_agg, norm:Literal['peak','hourly','absolute']='peak'):
    """
    Get the peak hourly outage magnitude

    Args:
        norm: How to normalize the hourly EUE [MW]
            - 'peak': Divide hourly EUE by peak load -> returns fraction
            - 'hourly': Divide hourly EUE by hourly load -> returns fraction
            - 'absolute': Do not normalize -> returns MW
    """
    match norm:
        case 'peak':
            peak_eue = dfeue_agg.max() / dfload_agg.max()
        case 'hourly':
            peak_eue = (dfeue_agg / dfload_agg).max()
        case 'absolute':
            peak_eue = dfeue_agg.max()
    return peak_eue


def calc_ra_metrics(
    case:str|Path,
    t:int,
    iteration:int=0,
    levels=['country', 'interconnect', 'nercr', 'transreg', 'transgrp', 'st', 'r'],
):
    """
    Calculate all resource adequacy metrics for the specified year/iteration
    and regional aggregation levels.
    """
    ### Validate inputs
    hierarchy = reeds.io.get_hierarchy(case).reset_index()
    wrong = [i for i in levels if i not in hierarchy]
    if len(wrong):
        raise ValueError(f'Invalid levels: {wrong}')

    ### Get values from PRAS
    pras_shortfall = get_pras_shortfall(case, t, iteration)
    dfeue = pras_shortfall['EUE']
    dflole = pras_shortfall['LOLE']

    ### Get load and number of years (for normalization)
    dfload = reeds.io.read_h5py_file(
        Path(case,'handoff','reeds_data',f'pras_load_{t}.h5')
    )
    dfload.index = dfeue.index
    sw = reeds.io.get_switches(case)
    numyears = len(sw.resource_adequacy_years_list)

    ### Loop over aggregation levels and calculate all metrics
    ra_metrics = {}
    for level in levels:
        print(f'Calculating RA metrics at {level} level')
        ### Aggregate the shortfall and load to this hierarchy level
        rmap = reeds.io.get_rmap(case=case, hierarchy_level=level)
        ## If multiple zones in one level and hour have LOLE, count that as one event,
        ## so take the max LOLE across the zones
        dflole_agg = dflole.rename(columns=rmap).groupby(axis=1, level=0).max()
        dfeue_agg = dfeue.rename(columns=rmap).groupby(axis=1, level=0).sum()
        dfload_agg = dfload.rename(columns=rmap).groupby(axis=1, level=0).sum()
        ## Calculate the full-timeseries metrics for each region
        ra_metrics[level, 'lold_peryear'] = calc_lold(dflole_agg) / numyears
        ra_metrics[level, 'lole_peryear'] = calc_lole(dflole_agg) / numyears
        ra_metrics[level, 'lolh_peryear'] = calc_lolh(dflole_agg) / numyears
        ra_metrics[level, 'max_duration'] = calc_max_duration(dfeue_agg)
        ra_metrics[level, 'neue_ppm'] = calc_neue(dfeue_agg, dfload_agg)
        ra_metrics[level, 'euemax_peakloadfrac'] = calc_peak_eue(dfeue_agg, dfload_agg, 'peak')
        ra_metrics[level, 'euemax_hourlyloadfrac'] = calc_peak_eue(dfeue_agg, dfload_agg, 'hourly')
        ra_metrics[level, 'euemax_mw'] = calc_peak_eue(dfeue_agg, dfload_agg, 'absolute')

    ### Combine it
    dfout = pd.concat(ra_metrics, names=['level','metric','region']).rename('value')

    return dfout


def get_eue_events(
    case:str|Path,
    t:int,
    iteration:int=0,
    levels=['country', 'interconnect', 'nercr', 'transreg', 'transgrp', 'st', 'r'],
):
    ### Get values from PRAS
    dfeue = get_pras_shortfall(case, t, iteration)['EUE']

    ### Get the list of events at all hierarchy levels
    events = {}
    for level in levels:
        rmap = reeds.io.get_rmap(case=case, hierarchy_level=level)
        dfeue_agg = dfeue.rename(columns=rmap).groupby(axis=1, level=0).sum()
        events[level] = pd.concat({r: get_events(dfeue_agg[r]) for r in dfeue_agg})
    dfout = pd.concat(events, names=['level','region','number'])
    return dfout


def get_shortfall_periods(
    dsmetric:pd.Series,
    aggmethod:Literal['max','sum']='sum',
    GSw_HourlyType:Literal['day','wek','year']='day',
):
    ## Keep days with nonzero metric
    metric_day = dsmetric.resample('D').agg(aggmethod).replace(0, np.nan).dropna()
    ## Convert to ReEDS period
    metric_day.index = metric_day.index.map(
        lambda x: reeds.timeseries.timestamp2h(x, GSw_HourlyType).split('h')[0]
    )
    ## Sort by value
    metric_period = metric_day.groupby(metric_day.index).sum().sort_values(ascending=False)
    return metric_period


def get_longest_events(
    dsmetric,
    sw,
    num_events:int=1,
):
    eue_events = (
        get_events(dsmetric)
        .sort_values('timesteps', ascending=False)
        .head(num_events)
    )
    ## Get the datetimes in each event and keep all unique
    dates = []
    for i, row in eue_events.iterrows():
        dates.append(
            pd.Series(index=pd.date_range(row.start, row.end, freq='H'), data=1)
            .resample('D').count()
        )
    if len(dates):
        metric_period = pd.concat(dates)
        metric_period.index = metric_period.index.map(
            lambda x: reeds.timeseries.timestamp2h(x, sw.GSw_HourlyType).split('h')[0]
        )
        metric_period = metric_period.groupby(level=0).sum()
    else:
        metric_period = pd.Series(dtype=int)
    return metric_period


def get_shoulder_periods(sw, criterion, dfenergy_agg, high_stress_periods):
    ## Stop if not needed
    if sw.GSw_PRM_StressStorageCutoff.lower() in ['off', '0', 'false']:
        print(
            f"GSw_PRM_StressStorageCutoff={sw.GSw_PRM_StressStorageCutoff} "
            "so not adding shoulder stress periods based on storage level"
        )
        return {}
    if dfenergy_agg.empty:
        print(
            "No storage capacity, so no shoulder stress periods will be added "
            "based on storage level"
        )
        return {}

    ## Parse inputs
    timeindex = reeds.timeseries.get_timeindex(sw['resource_adequacy_years'])
    cutofftype, cutoff = sw.GSw_PRM_StressStorageCutoff.lower().split('_')
    periodhours = {'day':24, 'wek':24*5, 'year':24}[sw.GSw_HourlyType]
    fmt = '%Y-%m-%d'

    dfheadspace_MWh = dfenergy_agg.max() - dfenergy_agg
    dfheadspace_frac = dfheadspace_MWh / dfenergy_agg.max()

    _shoulder_periods = {}
    for i, row in high_stress_periods.iterrows():
        if row.region not in dfheadspace_MWh:
            continue

        day = reeds.timeseries.h2timestamp(row.period)

        start_headspace_MWh = dfheadspace_MWh.loc[day.strftime(fmt), row.region].iloc[0]
        end_headspace_MWh = dfheadspace_MWh.loc[day.strftime(fmt), row.region].iloc[-1]

        start_headspace_frac = dfheadspace_frac.loc[day.strftime(fmt), row.region].iloc[0]
        end_headspace_frac = dfheadspace_frac.loc[day.strftime(fmt), row.region].iloc[-1]

        day_eue = high_stress_periods.loc[i, 'value']
        day_index = np.where(
            timeindex == dfenergy_agg.loc[day.strftime(fmt)].iloc[0].name
        )[0][0]

        ## Loop around with % len(timeindex) if on the first or last day
        day_before = timeindex[(day_index - periodhours) % len(timeindex)]
        day_after = timeindex[(day_index + periodhours) % len(timeindex)]

        if (
            ((cutofftype == 'eue') and (end_headspace_MWh / day_eue >= float(cutoff)))
            or ((cutofftype[:3] == 'cap') and (end_headspace_frac  >= float(cutoff)))
            or (cutofftype[:3] == 'abs')
        ):
            _shoulder_periods[f'after_{row.period}'] = pd.Series({
                'region':row.region,
                'period':day_after.strftime('y%Yd%j'),
            })
            print(
                f"Added {day_after.strftime(fmt)} as shoulder stress period "
                f"after {day.strftime(fmt)}"
            )

        if (
            ((cutofftype == 'eue') and (start_headspace_MWh / day_eue >= float(cutoff)))
            or ((cutofftype[:3] == 'cap') and (start_headspace_frac  >= float(cutoff)))
            or (cutofftype[:3] == 'abs')
        ):
            _shoulder_periods[f'before_{row.period}'] = pd.Series({
                'region':row.region,
                'period':day_before.strftime('y%Yd%j'),
            })
            print(
                f"Added {day_before.strftime(fmt)} as shoulder stress period "
                f"before {day.strftime(fmt)}"
            )
    if len(_shoulder_periods):
        shoulder_periods = (
            pd.concat(_shoulder_periods).unstack(level=1).reset_index()
            .rename(columns={'index':'value'})[['region','period','value']]
        )
    else:
        shoulder_periods = pd.DataFrame(columns=['region','period','value'])
    return shoulder_periods


def check_threshold_and_choose_periods(
    stress_metric:str,
    criterion:str,
    sw,
    t:int,
    iteration:int,
    dfeue_agg,
    dflole_agg,
    dfenergy_agg,
):
    ## NEUE Example: criterion = 'transgrp_1'
    hierarchy_level, metric_threshold = criterion.split('_')
    metric_threshold = float(metric_threshold)
    GSw_HourlyType = sw.GSw_HourlyType

    ### Get stored stress metric
    ra_metrics = pd.read_csv(
        os.path.join(sw.casedir, 'outputs', f'ra_metrics_{t}i{iteration}.csv'),
        index_col=['level', 'metric', 'region'],
    ).squeeze(1)

    ### Get the threshold(s) and see if any of them failed
    this_test = ra_metrics[hierarchy_level][SWITCH_METRIC[stress_metric]]
    failed = this_test.loc[this_test > metric_threshold]
    if not len(failed):
        print(f"{RA_SWITCHES[stress_metric]} = {criterion} passed:")
        for i, val in this_test.items():
            print(f'{i}: {val} {stress_metric}')
    else:
        print(f"{RA_SWITCHES[stress_metric]} = {criterion} failed for:")
        for i, val in failed.items():
            print(f'{i}: {val} {stress_metric}')
        ## Get new stress periods since the metric failed
        match stress_metric:
            case 'depth':
                metric_periods = {
                    region: (
                        get_shortfall_periods(dfeue_agg[region], 'max', GSw_HourlyType)
                        .head(int(sw.GSw_PRM_StressIncrement))
                    )
                    for region in failed.index
                }
            case 'duration':
                ## NOTE: This approach adds the next-longest event if the longest event is
                ## already included as a stress period (since we've dropped the already-
                ## included stress periods from dfeue_agg above). That's less likely to
                ## help meet a max-duration threshold than adding the next-worst EUE day
                ## is to help meet a NEUE threshold. So consider if there's something else
                ## we should do if the longest-event day is already a stress period but
                ## we're still not meeting the duration threshold.
                metric_periods = {
                    region: get_longest_events(
                        dfeue_agg[region], sw=sw,
                        num_events=int(sw.GSw_PRM_StressIncrement),
                    )
                    for region in failed.index
                }
            case 'lold' | 'lole':
                ## TODO: Double check this approach for LOLD and LOLE
                metric_periods = {
                    region: (
                        get_shortfall_periods(dflole_agg[region], 'max', GSw_HourlyType)
                        .head(int(sw.GSw_PRM_StressIncrement))
                    )
                    for region in failed.index
                }
            case 'lolh':
                metric_periods = {
                    region: (
                        get_shortfall_periods(dflole_agg[region], 'sum', GSw_HourlyType)
                        .head(int(sw.GSw_PRM_StressIncrement))
                    )
                    for region in failed.index
                }
            case 'neue':
                metric_periods = {
                    region: (
                        get_shortfall_periods(dfeue_agg[region], 'sum', GSw_HourlyType)
                        .head(int(sw.GSw_PRM_StressIncrement))
                    )
                    for region in failed.index
                }
        high_stress_periods = (
            pd.concat(metric_periods, names=['region','period'])
            .rename('value')
            .reset_index()
        )
        ### Include "shoulder periods" before or after each period
        ### if the storage state of charge is low
        if stress_metric.lower() == 'neue':
            shoulder_periods = get_shoulder_periods(
                sw,
                criterion,
                dfenergy_agg,
                high_stress_periods,
            )
        else:
            shoulder_periods = pd.DataFrame()

        return {
            'failed': failed,
            'high_stress_periods': high_stress_periods,
            'shoulder_periods': shoulder_periods,
        }


def get_stress_periods(case, sw, t, iteration):
    ### Get values from PRAS
    pras_shortfall = get_pras_shortfall(case, t, iteration)
    dfeue = pras_shortfall['EUE']
    dflole = pras_shortfall['LOLE']
    ## Storage state of charge (SOC) to use in selection of "shoulder" stress periods
    dfenergy_unit = reeds.io.read_pras_results(
        os.path.join(sw['casedir'], 'handoff', 'PRAS', f"PRAS_{t}i{iteration}-energy.h5")
    )
    timeindex = reeds.timeseries.get_timeindex(sw['resource_adequacy_years'])
    dfenergy_unit.index = timeindex
    ## Sum over units
    dfenergy = (
        dfenergy_unit
        .rename(columns={c: c.split('|')[1] for c in dfenergy_unit.columns})
        .groupby(axis=1, level=0).sum()
    )

    ### Load this year's stress periods so we don't duplicate
    stressperiods_this_iteration = pd.read_csv(
        os.path.join(
            sw['casedir'], 'inputs_case', f'stress{t}i{iteration}', 'period_szn.csv')
    )
    stressperiods_this_iteration['start'] = (
        stressperiods_this_iteration.actual_period.map(reeds.timeseries.h2timestamp)
    )
    stressperiods_this_iteration['end'] = (
        stressperiods_this_iteration['start']
        + (
            (pd.Timedelta('5D') if sw.GSw_HourlyType == 'wek' else pd.Timedelta('1D'))
             - pd.Timedelta('1H')
        )
    )
    ## Get already-modeled stress hours so we can exclude them from the hourly
    ## EUE and LOLE profiles used to determine new stress periods
    covered_hours = [
        pd.date_range(row.start, row.end, freq='1H')
        for i,row in stressperiods_this_iteration.iterrows()
    ]
    covered_hours = [i for sublist in covered_hours for i in sublist]

    ### Check all stress criteria; for regions that fail, add new stress periods
    _failed = {}
    _high_stress_periods = {}
    _shoulder_periods = {}

    stress_metrics = [i.lower() for i in sw.GSw_PRM_StressThresholdMetrics.split('/')]
    for stress_metric in stress_metrics:
        switch = RA_SWITCHES[stress_metric]
        for criterion in sw[switch].split('/'):
            ### Aggregate the shortfall and load to this hierarchy level
            ## Example: criterion = 'transgrp_1'
            hierarchy_level, metric_threshold = criterion.split('_')
            rmap = reeds.io.get_rmap(case=case, hierarchy_level=hierarchy_level)
            dfeue_agg = dfeue.rename(columns=rmap).groupby(axis=1, level=0).sum().drop(covered_hours)
            dflole_agg = dflole.rename(columns=rmap).groupby(axis=1, level=0).max().drop(covered_hours)
            dfenergy_agg = dfenergy.rename(columns=rmap).groupby(axis=1, level=0).sum().drop(covered_hours)
            ## Get the stress periods
            dictout = check_threshold_and_choose_periods(
                stress_metric,
                criterion,
                sw,
                t,
                iteration,
                dfeue_agg,
                dflole_agg,
                dfenergy_agg,
            )
            if dictout is not None:
                _failed[stress_metric, criterion] = dictout['failed']
                _high_stress_periods[stress_metric, criterion] = dictout['high_stress_periods']
                _shoulder_periods[stress_metric, criterion] = dictout['shoulder_periods']

    ### Get lists of stress periods: new (added this iteration) and all
    if len(_failed):
        failed = pd.concat(_failed, names=['stress_metric', 'criterion'])
        high_stress_periods = pd.concat(_high_stress_periods)
        shoulder_periods = pd.concat(_shoulder_periods)
        new_stress_periods = pd.concat(
            {'stress':high_stress_periods, 'shoulder':shoulder_periods},
            names=['periodtype','metric','criterion','num'],
        ).reset_index()
        print('All identified stress periods:')
        print(new_stress_periods)
        ## Remove the existing stress periods and duplicates across regions
        new_stress_periods = new_stress_periods.loc[
            ~new_stress_periods.period.isin(stressperiods_this_iteration.actual_period)
        ].copy()
        new_stress_periods = new_stress_periods.drop_duplicates('period')
        print('New stress periods after dropping duplicates:')
        print(new_stress_periods)
    else:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    ## Reproduce the format of inputs_case/stress_period_szn.csv
    p = 'w' if sw.GSw_HourlyType == 'wek' else 'd'
    new_stressperiods_write = pd.DataFrame({
        'rep_period': new_stress_periods.period,
        'year': new_stress_periods.period.map(
            lambda x: int(x.strip('sy').split(p)[0])),
        'yperiod': new_stress_periods.period.map(
            lambda x: int(x.strip('sy').split(p)[1])),
        'actual_period': new_stress_periods.period,
    })

    ### Add new stress periods to the stress periods used for this year/iteration,
    ### drop duplicates, then write
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

    ### Tables for debugging
    new_stress_periods.to_csv(
        os.path.join(sw.casedir, 'inputs_case', newstresspath, 'new_stress_periods.csv'),
        index=False,
    )

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
    # read the net shortfall (positive) and net surplus (negative) results
    # by sample from PRAS run (MWh)
    filepath = os.path.join(sw['casedir'], 'handoff', 'PRAS',
                            f'PRAS_{sw["t"]}i{iteration}-shortfall_samples.h5')
    net_short = reeds.io.read_pras_results(filepath)
    # get number of samples
    n_samples = len(net_short)
    # collapse dict of dataframes by sample in 1 dataframe (keep index to preserve hours)
    net_short = pd.concat(
        (df.assign(**{"sample": k}) for k, df in net_short.items()), ignore_index=False)
    # convert to long format with shortfall by sample, hour, and r
    net_short.index.names=['hour']
    net_short = net_short.reset_index().set_index(['sample','hour'])
    net_short = net_short.sort_index(level=['sample', 'hour'], ascending=[True, True])
    net_short = net_short.melt(
        ignore_index=False, var_name='r', value_name='net_short_mwh').reset_index()

    # zero-out negative values (net surplus) for determining regional unserved energy totals
    net_short['net_short_mwh'] = net_short['net_short_mwh'].clip(lower=0)
    # calaculate total regional net shortfall for all hours by sample
    net_short_crit = net_short.groupby(['r','sample'], as_index=False)['net_short_mwh'].sum()

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
        failed (pd.Series): Series of failed regions with unserved energy at the
                       hierarchy_level, indexed by (stress_metric, criterion, region)
        combined_periods_write (pd.DataFrame): Data frame of combined stress periods

    Returns:
        pd.DataFrame: Table of prm levels for the next PRAS iteration
    """
    ## Existing PRM, in case there's nothing to update it with below
    prm = pd.read_csv(
        os.path.join(sw['casedir'], 'inputs_case', f'stress{t}i{iteration}', 'prm.csv'),
        index_col='*r',
    ).fraction

    # Get regions that failed criteria
    # Use NEUE-based failed regions only, since the PRM update is computed from the
    # NEUE-based shortfall (in ppm) and doesn't generalize to the other stress metrics.
    # NEUE may not appear in `failed` at all this iteration (either it's not a configured
    # stress metric, or it simply didn't fail while another metric did) -- in that case
    # there's nothing to update the PRM with, so leave it unchanged.
    _failed_regions = []
    if 'neue' in failed.index.get_level_values('stress_metric'):
        neue_failed = failed.xs('neue', level='stress_metric')
        for criterion in neue_failed.index.get_level_values('criterion').unique():
            sub = neue_failed.xs(criterion, level='criterion')
            # Example: criterion = 'transgrp_10'
            hierarchy_level, metric_threshold = criterion.split('_')
            # Recover regions where the PRM criterion failed
            rmap = reeds.io.get_rmap(sw['casedir'], hierarchy_level=hierarchy_level).reset_index()
            df = rmap.loc[
                rmap[hierarchy_level].isin(sub.index)
            ].rename(columns={hierarchy_level:'region'})
            df['hierarchy_level'] = hierarchy_level
            df['ppm'] = float(metric_threshold)
            _failed_regions.append(df)

    if not len(_failed_regions):
        return prm.round(3)

    # For zones that failed multiple criteria, use the most stringent (lowest EUE target)
    failed_regions = (
        pd.concat(_failed_regions)
        .sort_values(by=['ppm'])
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
    prm_next_iteration = prm.add(prm_increment, fill_value=0).round(3)

    return prm_next_iteration


#%%### Procedure
def main(sw, t, iteration=0, logging=True):
    """
    """
    #%% Write consolidated stress metrics
    ra_metrics = calc_ra_metrics(case=sw.casedir, t=t, iteration=iteration)
    ra_metrics.round(3).to_csv(
        os.path.join(sw.casedir, 'outputs', f'ra_metrics_{t}i{iteration}.csv')
    )

    #%% Write EUE events
    eue_events = get_eue_events(case=sw.casedir, t=t, iteration=iteration)
    ## Store the profile as a |-delimited string
    eue_events.profile = eue_events.profile.map(lambda x: '|'.join(str(i) for i in x))
    eue_events.round(3).to_csv(
        os.path.join(sw.casedir, 'outputs', f'eue_events_{t}i{iteration}.csv')
    )

    #%% Stop here if not iterating or if before ReEDS can build new capacity
    if (not int(sw.GSw_PRM_StressIterateMax)) or (t < int(sw['GSw_StartMarkets'])):
        return

    #%% Identify and write new stress periods
    failed, new_stressperiods_write, combined_periods_write = get_stress_periods(
        case=sw.casedir, sw=sw, t=t, iteration=iteration,
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


# #%%### Option to run script directly for debugging
# if __name__ == '__main__':
#     casedir =  "/path/to/ReEDS/runs/runname"
#     t = 2030 # previous solve year
#     iteration = 0
#     # load switches
#     sw = reeds.io.get_switches(casedir)
#     sw['t'] = t
#     sw['GSw_PRM_UpdateMethod'] = 2
#     #%%###
#     main(sw, t, iteration, logging=False)
