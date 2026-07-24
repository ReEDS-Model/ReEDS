import os
import sys
import numpy as np
import pandas as pd

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds


def get_timeindex(
    years=list(range(2007, 2014)) + list(range(2016, 2024)),
    tz='Etc/GMT+6',
):
    """
    ReEDS time indices are in Central Standard Time,
    and leap years drop Dec 31 instead of Feb 29
    """
    _years = [int(y) for y in years.split('_')] if isinstance(years, str) else years
    timeindex = np.ravel(
        [
            pd.date_range(
                f'{y}-01-01',
                f'{y + 1}-01-01',
                freq='h',
                inclusive='left',
                tz=tz,
            )[:8760]
            for y in _years
        ]
    )
    return timeindex


def h2timestamp(h, tz='Etc/GMT+6'):
    """
    Map ReEDS timeslice to actual timestamp
    """
    hr = int(h.split('h')[1]) - 1 if 'h' in h else 0
    if 'd' in h:
        y = int(h.strip('sy').split('d')[0])
        d = int(h.split('d')[1].split('h')[0])
    else:
        y = int(h.strip('sy').split('w')[0])
        w = int(h.split('w')[1].split('h')[0])
        d = (w - 1) * 5 + 1 + hr // 24
    out = pd.to_datetime(f'y{y}d{d}h{hr % 24}', format='y%Yd%jh%H').tz_localize(tz)
    return out


def timestamp2h(ts, GSw_HourlyType='day'):
    """
    Map actual timestamp to ReEDS period
    """
    y = ts.year
    d = int(ts.strftime('%j').lstrip('0'))
    if GSw_HourlyType == 'wek':
        w = d // 5
        h = (d % 5) * 24 + ts.hour + 1
        out = f'y{y}w{w:>03}h{h:>03}'
    else:
        h = ts.hour + 1
        out = f'y{y}d{d:>03}h{h:>03}'
    return out


def szn2yearperiod(szn):
    """
    szn's are formatted as 'y{20xx}{d or w}{day of year or wek of year}'
    where a 'wek' is a 5-day period (5*73 = 365)
    """
    year, period = szn.split('d') if 'd' in szn else szn.split('w')
    return int(year.strip('y')), int(period)


def szn2period(szn):
    """
    szn's are formatted as 'y{20xx}{d or w}{day of year or wek of year}'
    where a 'wek' is a 5-day period (5*73 = 365)
    """
    year, period = szn.split('d') if 'd' in szn else szn.split('w')
    return int(period)


def timeslice_to_timestamp(case, param):
    ### Load the timestamps and other ReEDS settings
    h_dt_szn = pd.read_csv(os.path.join(case, 'inputs_case', 'rep', 'h_dt_szn.csv'))
    sw = reeds.io.get_switches(case)
    sw['GSw_HourlyWeatherYears'] = [int(y) for y in sw['GSw_HourlyWeatherYears'].split('_')]
    ### Get the timestamps for the modeled weather yeras
    hs = h_dt_szn.loc[h_dt_szn.year.isin(sw['GSw_HourlyWeatherYears']), 'h'].to_frame()
    hs['timestamp'] = pd.concat(
        [
            pd.Series(
                pd.date_range(
                    f'{y}-01-01',
                    f'{y + 1}-01-01',
                    inclusive='left',
                    freq='h',
                    tz='Etc/GMT+6',
                )[:8760]
            )
            for y in sw['GSw_HourlyWeatherYears']
        ]
    ).values
    hs = hs.set_index('timestamp').h.tz_localize('UTC').tz_convert('Etc/GMT+6')
    ### Load the ReEDS output file
    rename = {'allh': 'h', 'allt': 't'}
    dfin_timeslice = reeds.io.read_output(case, param).rename(columns=rename)
    ## check if empty
    if dfin_timeslice.empty:
        raise Exception(f'{param}.csv is empty; skipping timestamp processing')
    indices = [c for c in dfin_timeslice if c != 'Value']
    if 'h' not in indices:
        raise Exception(f"{param} does not have an h index: {indices}")
    indices_fixed = [c for c in indices if c != 'h']
    ### Convert to an hourly timeseries
    dfout_h = (
        dfin_timeslice.pivot(index='h', columns=indices_fixed, values='Value')
        ## Create entries for each timestamp but labeled by timeslices
        .loc[hs]
        .fillna(0)
        ## Add the timestamp index
        .set_index(hs.index)
    )
    return dfout_h


def make_timestamps(sw):
    ### Get some useful constants
    hoursperperiod = {'day':24, 'wek':120, 'year':24}
    periodsperyear = {'day':365, 'wek':73, 'year':365}
    weather_years = sw.resource_adequacy_years_list

    ### Get map from yperiod, hour, and h_of_period to timestamp
    timestamps = pd.DataFrame({
        'year': np.ravel([[y]*8760 for y in weather_years]),
        'h_of_year': np.ravel([list(range(1,8761)) * len(weather_years)]),
        'h_of_period': np.ravel(
            [f'{h+1:>03}' for h in range(hoursperperiod[sw['GSw_HourlyType']])]
            * periodsperyear[sw['GSw_HourlyType']] * len(weather_years)),
        'yperiod': np.ravel(
            [p+1 for p in range(periodsperyear[sw['GSw_HourlyType']])
             for h in range(hoursperperiod[sw['GSw_HourlyType']])]
            * len(weather_years)),
        'h_of_day': np.ravel(
            [f'{h+1:>03}' for h in range(hoursperperiod['day'])]
            * periodsperyear['day'] * len(weather_years)),
        'yday': np.ravel(
            [p+1 for p in range(periodsperyear['day'])
             for h in range(hoursperperiod['day'])]
            * len(weather_years)),
        'h_of_wek': np.ravel(
            [f'{h+1:>03}' for h in range(hoursperperiod['wek'])]
            * periodsperyear['wek'] * len(weather_years)),
        'ywek': np.ravel(
            [p+1 for p in range(periodsperyear['wek'])
             for h in range(hoursperperiod['wek'])]
            * len(weather_years)),
    })
    timestamps['timestamp'] = (
        'y' + timestamps.year.astype(str)
        ## d for day and w for wek 
        + ('w' if sw.GSw_HourlyType == 'wek' else 'd')
        + timestamps.yperiod.astype(str).map('{:>03}'.format)
        + 'h' + timestamps.h_of_period
    )
    timestamps['period'] = timestamps['timestamp'].map(lambda x: x.split('h')[0])
    timestamps['day'] = (
        'y' + timestamps.year.astype(str)
        + 'd' + timestamps.yday.astype(str).map('{:>03}'.format)
    )
    timestamps['wek'] = (
        'y' + timestamps.year.astype(str)
        + 'w' + timestamps.ywek.astype(str).map('{:>03}'.format)
    )
    timestamps.index = np.ravel([
        pd.date_range(
            f'{y}-01-01', f'{y+1}-01-01',
            freq='h', inclusive='left', tz='Etc/GMT+6',
        )[:8760]
        for y in weather_years
    ])

    return timestamps


### Timeseries reduction
def get_clusters(
    profiles_fitperiods,
    GSw_HourlyClusterAlgorithm='hierarchical',
    GSw_HourlyNumClusters:int=35,
):
    """
    Hierarchical, k-means, or k-medoids clustering.
    Returns an array of the same length as profiles_fitperiods,
    with values ranging from 0 to GSw_HourlyNumClusters indicating the assignment
    of each period to a cluster.
    """
    import sklearn.cluster
    if GSw_HourlyClusterAlgorithm.startswith('hierarchical'):
        args = GSw_HourlyClusterAlgorithm.split('_')
        if len(args) > 1:
            metric = args[1]
            linkage = args[2]
        else:
            metric = 'euclidean'
            linkage = 'ward'
        clusters = sklearn.cluster.AgglomerativeClustering(
            n_clusters=GSw_HourlyNumClusters,
            metric=metric, linkage=linkage,
        )
    elif GSw_HourlyClusterAlgorithm.lower().startswith('kmeans'):
        clusters = sklearn.cluster.KMeans(
            n_clusters=GSw_HourlyNumClusters,
            random_state=0, n_init='auto', max_iter=1000,
        )
    elif GSw_HourlyClusterAlgorithm.lower().startswith('kmedoids'):
        import sklearn_extra.cluster
        args = GSw_HourlyClusterAlgorithm.split('_')
        if len(args) > 1:
            metric = args[1]
            init = args[2]
        else:
            metric = 'euclidean'
            init = 'heuristic'
        clusters = sklearn_extra.cluster.KMedoids(
            n_clusters=GSw_HourlyNumClusters,
            metric=metric, init=init, method='pam',
            max_iter=1000, random_state=0,
        )
    ### Fit it
    cluster_assignment = clusters.fit_predict(profiles_fitperiods)
    return cluster_assignment


def round_to_integers(rweights, num_actual_periods, increment=1e-6):
    ### Convert to integers
    iweights = rweights.round(0).astype(int)
    ### Scale all weights little by little until they sum to number of actual days
    sumweights = iweights.sum()
    diffweights = sumweights - num_actual_periods
    _increment = increment * (1 if diffweights < 0 else -1)
    for i in range(int(10/increment)):
        iweights = (rweights * (1 + _increment*i)).round(0).astype(int)
        if iweights.sum() == num_actual_periods:
            break

    iweights = iweights.replace(0,np.nan).dropna().astype(int)
    ### Make sure it worked
    if iweights.sum() != num_actual_periods:
        raise ValueError(f'Sum of rounded weights = {iweights.sum()} != {num_actual_periods}')
    return iweights


def minimize_abs_error_in_means(basis_periods, target_feature_mean):
    """
    Weight days from basis_periods to minimize the sum of absolute error vs
    target_feature_mean values by feature & region.
    The method is described at https://doi.org/10.1016/j.energy.2025.135830.
    """
    import pulp
    ### Input processing
    assert (target_feature_mean.index == basis_periods.columns).all()

    days = basis_periods.index.values

    ### Optimization: minimize sum of absolute errors
    m = pulp.LpProblem('LinearDaySelection', pulp.LpMinimize)
    ###### Variables
    ### day weights
    WEIGHT = pulp.LpVariable.dicts('WEIGHT', (d for d in days), lowBound=0, cat='Continuous')
    ### errors
    ERROR_POS = pulp.LpVariable.dicts(
        'ERROR_POS', (c for c in basis_periods.columns), lowBound=0, cat='Continuous')
    ERROR_NEG = pulp.LpVariable.dicts(
        'ERROR_NEG', (c for c in basis_periods.columns), lowBound=0, cat='Continuous')
    ###### Constraints
    ### weights must sum to 1
    m += pulp.lpSum([WEIGHT[d] for d in days]) == 1
    ### definition of errors
    for c in basis_periods.columns:
        m += (
            ### Full error for column (given by positive component minus negative component)...
            ERROR_POS[c] - ERROR_NEG[c]
            ### ...plus sum of values for weighted representative days...
            + pulp.lpSum([WEIGHT[d] * basis_periods[c][d] for d in days])
            ### ...equals the mean for that column
            == target_feature_mean[c])
    ###### Objective: minimize the sum of absolute values of errors across all columns
    m += pulp.lpSum([
        ERROR_POS[c] + ERROR_NEG[c]
        for c in basis_periods.columns
    ])

    ### Solve it
    m.solve(solver=pulp.PULP_CBC_CMD(msg=True))

    ### Collect weights
    weights = pd.Series({d:WEIGHT[d].varValue for d in days})
    return weights


def optimize_period_weights(
    profiles_period_mean,
    target_feature_mean=None,
    GSw_HourlyNumClusters=35,
):
    """
    """
    ### Input processing
    if target_feature_mean is None:
        target_feature_mean = profiles_period_mean.mean()
    else:
        assert (target_feature_mean.index == profiles_period_mean.mean().index).all()
        assert target_feature_mean.isnull().sum() == 0

    ### Get weights and scale by number of days
    weights = minimize_abs_error_in_means(
        basis_periods=profiles_period_mean,
        target_feature_mean=target_feature_mean,
    )

    ### Truncate based on GSw_HourlyNumClusters, scale appropriately, and convert to integers
    ### Keep the the 'GSw_HourlyNumClusters' highest-weighted days
    rweights = (weights.sort_values(ascending=False)[:GSw_HourlyNumClusters])
    ### Scale so that the weights sum to numperiods (have to do if GSw_HourlyNumClusters is small)
    num_actual_periods = len(profiles_period_mean)
    rweights *= num_actual_periods / rweights.sum()
    iweights = round_to_integers(rweights, num_actual_periods)

    return iweights, weights


def match_act2rep_milp(profiles_period_mean, iweights):
    """
    Assign representative periods to actual periods to minimize sum of errors in
    feature values by period (MILP optimization)
    """
    ### Imports
    import pulp

    ### Input processing
    actualdays = profiles_period_mean.index.values
    repdays = list(iweights.index)

    ### Optimization: minimize sum of absolute errors
    m = pulp.LpProblem('RepDayAssignment', pulp.LpMinimize)
    ###### Variables
    ### Weighting of rep days (r) for each actual day (a).
    ### Can only use whole days, so it's a binary variable.
    WEIGHT = pulp.LpVariable.dicts(
        'WEIGHT', ((a,r) for a in actualdays for r in repdays),
        lowBound=0, upBound=1, cat=pulp.LpInteger)
    ### Errors. These are defined for features (c) and for actual days (a).
    ERROR_POS = pulp.LpVariable.dicts(
        'ERROR_POS', ((a,c) for a in actualdays for c in profiles_period_mean.columns),
        lowBound=0, cat='Continuous')
    ERROR_NEG = pulp.LpVariable.dicts(
        'ERROR_NEG', ((a,c) for a in actualdays for c in profiles_period_mean.columns),
        lowBound=0, cat='Continuous')
    ###### Constraints
    ### Each actual day can only be assigned to one representative day
    for a in actualdays:
        m += pulp.lpSum([WEIGHT[a,r] for r in repdays]) == 1
    ### Each representative day must be used a number of times equal to its weight
    for r in repdays:
        m += pulp.lpSum([WEIGHT[a,r] for a in actualdays]) == iweights[r]
    ### Define the error variables
    for a in actualdays:
        for c in profiles_period_mean.columns:
            m += (
                ### Full error for column on actual day (given by positive
                ### component minus negative component)...
                ERROR_POS[a,c] - ERROR_NEG[a,c]
                ### ...plus value for its representative day (since WEIGHT is binary)...
                + pulp.lpSum([WEIGHT[a,r] * profiles_period_mean[c][r] for r in repdays])
                ### ...equals the actual value for that column and day
                == profiles_period_mean[c][a])
    ###### Objective: minimize the sum of absolute values of errors
    m += pulp.lpSum([
        ERROR_POS[a,c] + ERROR_NEG[a,c]
        for a in actualdays for c in profiles_period_mean.columns
    ])

    ### Solve it
    m.solve(solver=pulp.PULP_CBC_CMD(msg=True))

    ### Collect assignments
    assignments = pd.Series(
        {(a,r):WEIGHT[a,r].varValue for a in actualdays for r in repdays}).astype(int)
    assignments.index = assignments.index.rename(['act','rep'])
    a2r = assignments.replace(0,np.nan).dropna().reset_index(level='rep').rep

    return a2r


def _plot_weights(iweights, remaining_weights, i):
    import cmocean
    from pathlib import Path
    from datetime import datetime
    import matplotlib as mpl
    import matplotlib.pyplot as plt
    today = datetime.now().strftime("%Y%m%d")

    plotweights = remaining_weights.copy()
    plotweights.index = plotweights.index.map(
        lambda x: pd.to_datetime(f'y{x[0]}d{x[1]}h0', format='y%Yd%jh%H').strftime('%-m/%-d')
    )
    monthday2val = reeds.reedsplots.make_dayofyear_colormap()

    plt.close()
    f,ax = plt.subplots(figsize=(3,7))
    ax.barh(
        plotweights.index, plotweights.values,
        color=[cmocean.cm.phase(monthday2val[i]) for i in plotweights.index],
    )
    ax.plot(
        [1]*len(plotweights), range(len(plotweights)),
        marker='|', color='k', lw=0, markersize=9,
    )
    ax.set_ylim(-0.5,len(iweights)-0.5)
    ax.set_xlim(0, iweights.max())
    ax.xaxis.set_minor_locator(mpl.ticker.MultipleLocator(1))
    reeds.plots.despine(ax)
    fpath = Path(f'~/scratch/{today}/weights_{i}.png').expanduser()
    fpath.parent.mkdir(exist_ok=True, parents=True)
    plt.savefig(fpath)


def _plot_act2repday(a2r, i):
    from pathlib import Path
    from datetime import datetime
    import matplotlib.pyplot as plt

    today = datetime.now().strftime("%Y%m%d")
    actualday2repday = pd.Series(a2r).map(
        lambda x: pd.to_datetime(f'y{x[0]}d{x[1]}h0', format='y%Yd%jh%H')
    )
    actualday2repday.index = actualday2repday.index.map(
        lambda x: pd.to_datetime(f'y{x[0]}d{x[1]}h0', format='y%Yd%jh%H')
    )

    plt.close()
    f, ax, df = reeds.reedsplots.plot_repdays(actualday2repday=actualday2repday)
    fpath = Path(f'~/scratch/{today}/a2r_{i}.png').expanduser()
    plt.savefig(fpath)


def match_act2rep_bestfirst(
    profiles_period_mean,
    iweights,
    metric:str='seuclidean',
    verbose:int=0,
):
    """
    Assign actual periods to representative periods using a simple heuristic algorithm:

    1. Begin with a table of weights for each representative (rep) period
    2. Calculate the distance in (feature × region)-dimensional space between each actual
       and rep period.
    3. While there is still weight remaining in the rep-period weight table:
        a. Match each rep period to the single remaining actual period that is closest to it,
           recording its match in the actual-to-rep-period table
        b. Decrement the remaining weight for each rep period. If any weights reach zero,
           remove them from future consideration for matches. (So the lowest-weighted rep
           periods will fill up and drop out of consideration first.)
        c. Remove the actual periods that were matched from the table of distances
        d. Return to 3.a. and repeat until there are no remaining weights in the rep-period
           weight table (and no remaining unmatched actual periods)

    Args:
        profiles_period_mean (pd.DataFrame): (year, yperiod) x (feature, region)
        iweights (pd.Series): Integer weights for rep periods; (year, yperiod) index
        metric (string): Passed to scipy.spatial.distance.cdist()
        verbose (int): How much extra information to print for debugging.
            If ≥3, saves plots to your ~/scratch/{today} folder.

    """
    import scipy.spatial
    ### Get the distance
    keep_basis = profiles_period_mean.loc[iweights.index]
    distance = pd.DataFrame(
        data=scipy.spatial.distance.cdist(
            keep_basis,
            profiles_period_mean,
            metric=metric,
        ),
        index=keep_basis.index,
        columns=profiles_period_mean.index,
    )

    a2r = {}
    num_actual_periods = len(profiles_period_mean)
    remaining_weights = iweights.copy()
    remaining_distance = distance.copy()
    if verbose:
        print('Original weights:')
        print(remaining_weights)
    for i in range(num_actual_periods):
        if verbose:
            print(f'Iteration {i}:')
        if verbose > 2:
            _plot_weights(iweights, remaining_weights, i)
        ## Loop over the remaining weights
        for repday in remaining_weights.index:
            ## Keep the best match
            actday = remaining_distance.columns[np.argmin(remaining_distance.loc[repday])]
            a2r[actday] = repday
            if verbose > 1:
                print(f'{actday} → {repday}')
            ## Decrement the remaining weight
            remaining_distance.drop(columns=actday, inplace=True)
            remaining_weights.loc[repday] -= 1
        if verbose:
            print(remaining_weights)
        if verbose > 2:
            _plot_act2repday(a2r, i)
        ## If any remaining rep days have zero weight, drop them
        if (remaining_weights == 0).any():
            remaining_weights = remaining_weights.loc[remaining_weights > 0]
        if not len(remaining_weights):
            break

    out = pd.Series(a2r, name='rep')
    out.index = out.index.tolist()
    out.index = out.index.rename('act')
    return out
