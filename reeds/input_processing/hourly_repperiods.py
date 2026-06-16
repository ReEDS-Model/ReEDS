"""
The purpose of this script is to collect 8760 data as it is output by
hourlize and perform a temporal aggregation to produce load and capacity 
factor parameters for the representative days that will be read by ReEDS. 
The other outputs are the hours/seasons to be modeled in ReEDS and linking 
sets used in the model.

General notes:
* h: a timeslice with an h prefix, starting at h1
* hour: an hour of the full period, starting at 1 ([1-8760] for 1 year or [1-61320] for 7 years)
* dayhour: a clock hour starting at 1 [1-24]
* period: a day (if GSw_HourlyType=='day') or a wek (if GSw_HourlyType=='wek')
* wek: A consecutive 5-day period (365 is only divisible by 1, 5, 73, and 365)

This script is currently not compatible with:
* Climate impacts (climateprep.py)
* Beyond-2050 modeling (forecast.py)
* Flexible demand
"""

#%% ===========================================================================
### --- IMPORTS ---
### ===========================================================================
import argparse
import json
import os
import sys
import datetime
import numpy as np
import pandas as pd
import scipy
import sklearn.neighbors
import traceback
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))
import reeds
from reeds.input_processing import hourly_writetimeseries
from reeds.input_processing import hourly_plots
## Time the operation of this script
tic = datetime.datetime.now()


#%%#################
### FIXED INPUTS ###

decimals = 3
### Whether to show plots interactively [default False]
interactive = False
### VRE techs considered for GSw_PRM_StressSeedMinRElevel and GSw_HourlyMinRElevel
techs_min_vre = ['upv', 'wind-ons']

#%%### Functions
def get_load(inputs_case, keep_modelyear=None, keep_weatheryears=[2012]):
    """
    """
    ### Subset to modeled regions
    load = reeds.io.read_file(os.path.join(inputs_case,'load.h5'), parse_timestamps=True)
    ### Subset to keep_modelyear if provided
    if keep_modelyear:
        load = load.loc[keep_modelyear].copy()
    ### load.h5 is busbar load, but b_inputs.gms ingests end-use load, so scale down by distloss
    scalars = reeds.io.get_scalars(inputs_case)
    load *= (1 - scalars['distloss'])

    ### Downselect to weather years if provided
    if isinstance(keep_weatheryears, list):
        load = load.loc[load.index.year.isin(keep_weatheryears)]

    return load


def identify_peak_containing_periods(df, hierarchy, level):
    """
    Identify the period containing the peak value.
    Set of (region,reason,year,yperiod), with yperiod starting from 1.
    """
    ### Map columns to level, then sum
    if level == 'r':
        rmap = pd.Series(hierarchy.index, index=hierarchy.index)
    else:
        rmap = hierarchy[level]
    dfmod = df.copy()
    dfmod.columns = dfmod.columns.map(lambda x: x.split('|')[-1]).map(rmap)
    dfmod = dfmod.groupby(axis=1, level=0).sum()
    ### Get the max value by (year,yperiod)
    dfmax = dfmod.groupby(['year','yperiod']).max()
    ### Get the max (year,yperiod) for each column
    forceperiods = set([(c, 'peak-containing', *dfmax[c].nlargest(1).index[0]) for c in dfmax])

    return forceperiods


def identify_min_periods(df, hierarchy, level, prefix=''):
    """
    Identify the period with the minimum average value.
    Set of (region,reason,year,yperiod), with yperiod starting from 1.
    """
    ### Map columns to level, then sum
    if level == 'r':
        rmap = pd.Series(hierarchy.index, index=hierarchy.index)
    else:
        rmap = hierarchy[level]
    dfmod = df[[c for c in df if c.startswith(prefix)]].copy()
    dfmod.columns = dfmod.columns.map(lambda x: x.split('|')[-1]).map(rmap)
    dfmod = dfmod.groupby(axis=1, level=0).sum()
    ### Get the mean value by (year,yperiod)
    dfmean = dfmod.groupby(['year','yperiod']).mean()
    ### Get the min (year,yperiod) for each column
    forceperiods = set([(c, 'min average', *dfmean[c].nsmallest(1).index[0]) for c in dfmean])

    return forceperiods


def cluster_profiles(profiles_fitperiods, sw, forceperiods_yearperiod):
    """
    Cluster the load and (optionally) RE profiles to find representative days for dispatch in ReEDS.

    Args:
        GSw_HourlyClusterRegionLevel: Level of inputs/hierarchy.csv at which to aggregate
        profiles for clustering. VRE profiles are converted to available-capacity-weighted
        averages. That's not the best - it would be better to weight sites that are more likely
        to be developed more strongly - but it's better than not weighting at all.

    Returns:
        cf_representative - hourly profile of centroid or medoid capacity factor values
                            for all regions and technologies
        load_representative - hourly profile of centroid or medoid load values for all regions
    period_szn - day indices of each cluster center
    """
    ###### Run the clustering
    print(f"Performing {sw.GSw_HourlyClusterAlgorithm} clustering")
    if (
        sw['GSw_HourlyClusterAlgorithm'].startswith('hierarchical')
        or sw['GSw_HourlyClusterAlgorithm'].lower().startswith('kme')
    ):
        ### Generate the fits
        cluster_assignment = reeds.timeseries.get_clusters(
            profiles_fitperiods,
            GSw_HourlyClusterAlgorithm=sw.GSw_HourlyClusterAlgorithm,
            GSw_HourlyNumClusters=int(sw.GSw_HourlyNumClusters),
        )
        ### Get nearest period to each centroid
        centroids = pd.DataFrame(
            sklearn.neighbors.NearestCentroid()
            .fit(profiles_fitperiods, cluster_assignment).centroids_,
            columns=profiles_fitperiods.columns,
        )
        nearest_period = {
            i:
            profiles_fitperiods.loc[:,cluster_assignment==i,:].apply(
                lambda row: scipy.spatial.distance.euclidean(row, centroids.loc[i]),
                axis=1
            ).nsmallest(1).index[0]
            for i in range(int(sw['GSw_HourlyNumClusters']))
        }

        period_szn = pd.DataFrame({
            'period': profiles_fitperiods.index.values,
            'szn': [f"y{i[0]}{sw['GSw_HourlyType'][0]}{i[1]:>03}"
                       for i in pd.Series(cluster_assignment).map(nearest_period)]
        ### Add the force-include periods to the end of the list of seasons
        })
        period_szn = pd.concat([
            period_szn,
            pd.DataFrame({
                'period': list(forceperiods_yearperiod),
                'szn': [f"y{i[0]}{sw['GSw_HourlyType'][0]}{i[1]:>03}"
                        for i in forceperiods_yearperiod]
            })
        ]).sort_values('period').set_index('period').szn

    elif sw['GSw_HourlyClusterAlgorithm'] in ['opt','optimized','optimize']:
        profiles_period_mean = (
            profiles_fitperiods.groupby(['property','region'], axis=1)
            .mean()
        )
        ### Optimize the weights of representative days
        iweights, weights = reeds.timeseries.optimize_period_weights(
            profiles_period_mean=profiles_period_mean,
            GSw_HourlyNumClusters=int(sw['GSw_HourlyNumClusters']),
        )
        ### Optimize the assignment of actual days to representative days
        mapfunc = {
            'milp': reeds.timeseries.match_act2rep_milp,
            'bestfirst': reeds.timeseries.match_act2rep_bestfirst,
        }[sw.get('GSw_HourlyClusterMapMethod', 'milp')]
        a2r = mapfunc(
            profiles_period_mean=profiles_period_mean.round(4),
            iweights=iweights,
        )

        if len(iweights) < int(sw['GSw_HourlyNumClusters']):
            print(
                'Asked for {} representative periods but only needed {}'.format(
                    sw['GSw_HourlyNumClusters'], len(iweights)))

        period_szn = pd.concat([
            a2r.reset_index().rename(columns={'act':'period','rep':'szn'}),
            pd.DataFrame({'period':list(forceperiods_yearperiod),
                          'szn':list(forceperiods_yearperiod)})
            if len(forceperiods_yearperiod) else None
        ]).sort_values('period').set_index('period').szn
        period_szn = period_szn.map(lambda x: f'y{x[0]}{sw.GSw_HourlyType[0]}{x[1]:>03}')

    elif 'user' in sw['GSw_HourlyClusterAlgorithm'].lower():
        print('Using user-defined representative period weights')
        period_szn = pd.read_csv(
            os.path.join(inputs_case,'period_szn_user.csv')
        ).set_index('actual_period').rep_period.rename('szn')
        period_szn.index = period_szn.index.map(reeds.timeseries.szn2yearperiod).values
        period_szn.index = period_szn.index.rename('period')


    ### Get the list of representative periods for convenience
    rep_periods = sorted(period_szn.map(reeds.timeseries.szn2yearperiod).unique())

    return rep_periods, period_szn


#%% ===========================================================================
### --- MAIN FUNCTION ---
### ===========================================================================

def main(
    sw,
    reeds_path,
    inputs_case,
    periodtype='rep',
    minimal=0,
):
    """
    """
    #%% Parse inputs if necessary
    if not isinstance(sw['GSw_HourlyClusterWeights'], pd.Series):
        sw['GSw_HourlyClusterWeights'] = pd.Series(json.loads(
            '{"'
            + (':'.join(','.join(sw['GSw_HourlyClusterWeights'].split('/')).split('_'))
            .replace(':','":').replace(',',',"'))
            +'}'
        ))
        sw['GSw_HourlyClusterWeights'].index = sw['GSw_HourlyClusterWeights'].index.rename('property')
        sw['GSw_HourlyClusterWeights'] = (
            sw['GSw_HourlyClusterWeights'].loc[sw['GSw_HourlyClusterWeights'] != 0]
        ).copy()
    if not isinstance(sw['GSw_HourlyWeatherYears'], list):
        sw['GSw_HourlyWeatherYears'] = [int(y) for y in sw['GSw_HourlyWeatherYears'].split('_')]
    if not isinstance(sw['GSw_CSP_Types'], list):
        sw['GSw_CSP_Types'] = [int(i) for i in sw['GSw_CSP_Types'].split('_')]
    ## VRE techs that can be used for profiles
    techs_vre = ['upv', 'wind-ons', 'wind-ofs'] if int(sw.GSw_OfsWind) else ['upv', 'wind-ons']

    #%% Direct plots to outputs folder
    figpath = os.path.join(inputs_case,'..', 'outputs', 'figures')
    os.makedirs(figpath, exist_ok=True)
    os.makedirs(os.path.join(inputs_case, periodtype), exist_ok=True)

    val_r_all = pd.read_csv(
        os.path.join(inputs_case, 'val_r_all.csv'), header=None).squeeze(1).tolist()
    modelyears = pd.read_csv(
        os.path.join(inputs_case, 'modeledyears.csv')).columns.astype(int)
    # Use agglevel_variables function to obtain spatial resolution variables 
    agglevel_variables  = reeds.spatial.get_agglevel_variables(reeds_path, inputs_case)

    #%% Get map from yperiod, hour, and h_of_period to timestamp
    timestamps = reeds.timeseries.make_timestamps(sw)
    timestamps_myr = timestamps.loc[timestamps.year.isin(sw['GSw_HourlyWeatherYears'])].copy()

    ### Get region hierarchy for use with GSw_HourlyClusterRegionLevel
    hierarchy = pd.read_csv(
        os.path.join(inputs_case,'hierarchy.csv')).rename(columns={'*r':'r'}).set_index('r')
    hierarchy_orig = pd.read_csv(
        os.path.join(inputs_case,'hierarchy_original.csv'))
    
    if sw.GSw_HourlyClusterRegionLevel == 'r':
        rmap = pd.Series(hierarchy_orig.index, index=hierarchy_orig.index)
    elif agglevel_variables['agglevel'] == 'county' or 'county' in agglevel_variables['agglevel']:
        rmap = hierarchy[sw['GSw_HourlyClusterRegionLevel']]
    elif agglevel_variables['agglevel'] in ['ba','aggreg']:
        rmap = (hierarchy_orig.loc[hierarchy_orig['ba'].isin(val_r_all)]
                [['aggreg',sw['GSw_HourlyClusterRegionLevel']]]
                .drop_duplicates().set_index('aggreg')).squeeze(1)

    #%% Load supply curves to use for available capacity weighting
    sc = {
        tech: pd.read_csv(
            os.path.join(inputs_case, f'supplycurve_{tech}.csv')
        ).groupby(['region','class'], as_index=False).capacity.sum()
        for tech in techs_vre
    }
    sc = (
        pd.concat(sc, names=['tech','drop'], axis=0)
        .reset_index(level='drop', drop=True).reset_index())
    ### Downselect to modeled regions
    sc = sc.loc[sc.region.isin(val_r_all)].copy()
    sc['i'] = sc.tech+'_'+sc['class'].astype(str)
    sc['resource'] = sc.i + '|' + sc.region
    sc['aggreg'] = sc.region.map(rmap)

    #%%### Load RE CF data, then take available-capacity-weighted average by (tech,region)
    print("Collecting 8760 capacity factor data")
    recf_ra = reeds.io.read_file(os.path.join(inputs_case, 'recf.h5'), parse_timestamps=True)
    ### Downselect to techs used for rep-period selection
    recf_ra = recf_ra[[c for c in recf_ra if any([c.startswith(p) for p in techs_vre])]].copy()
    ### Multiply by available capacity for weighted average
    recf_ra *= sc.set_index('resource')['capacity']
    ### Downselect to modeled years, add descriptive time index
    recf = recf_ra.loc[recf_ra.index.year.isin(sw['GSw_HourlyWeatherYears'])]
    recf.index = timestamps_myr.set_index(['year','yperiod','h_of_period']).index
    recf_ra.index = timestamps.set_index(['year','yperiod','h_of_period']).index

    ### Identify outlying periods if using capacity credit instead of stress periods
    if (int(sw.GSw_PRM_CapCredit)
        and (sw['GSw_HourlyMinRElevel'].lower() not in ['false','none'])):
        forceperiods_minre = {
            tech: identify_min_periods(
                df=recf, hierarchy=hierarchy,
                level=sw['GSw_HourlyMinRElevel'], prefix=tech)
            for tech in techs_min_vre
        }
    else:
        forceperiods_minre = {tech: set() for tech in techs_min_vre}

    ### Aggregate to (tech,GSw_HourlyClusterRegionLevel)
    recf_agg = recf.copy()
    tmp = (
        pd.DataFrame({'resource':recf.columns}).set_index('resource')
        .merge(sc.set_index('resource')[['tech','region']], left_index=True, right_index=True)
        )
    columns = tmp.loc[tmp.index.isin(recf.columns)]
    recf_agg = recf_agg[tmp.index]
    columns['region'] = columns.region.map(rmap)
    recf_agg.columns = pd.MultiIndex.from_frame(columns[['tech','region']])
    recf_agg = recf_agg.groupby(axis=1, level=['tech','region']).sum()

    ### Divide by aggregated capacity to get back to CF
    recf_agg /= sc.groupby(['tech','aggreg']).capacity.sum().rename_axis(['tech','region'])

    ### Load load data (Eastern time)
    print("Collecting 8760 load data")
    load = get_load(
        inputs_case=inputs_case,
        keep_modelyear=(int(sw['GSw_HourlyClusterYear'])
                  if int(sw['GSw_HourlyClusterYear']) in modelyears
                  else max(modelyears)),
        keep_weatheryears=sw.GSw_HourlyWeatherYears,
    )
    ## Add descriptive index
    load.index = timestamps_myr.set_index(['year','yperiod','h_of_period']).index

    ### Identify outlying periods if using capacity credit instead of stress periods
    if (int(sw.GSw_PRM_CapCredit)
        and (sw['GSw_HourlyPeakLevel'].lower() not in ['false','none'])
    ):
        forceperiods_load = identify_peak_containing_periods(
            df=load, hierarchy=hierarchy, level=sw['GSw_HourlyPeakLevel'])
    else:
        forceperiods_load = set()

    ### Aggregate to GSw_HourlyClusterRegionLevel
    load_agg = load.copy()
    load_agg.columns = load_agg.columns.map(rmap)
    load_agg = load_agg.groupby(axis=1, level=0).sum()
    match sw.GSw_HourlyClusterLoadNorm:
        case 'none':
            ## Don't normalize load
            pass
        case 'regionmax':
            ## Normalize each region to [0,1]
            load_agg /= load_agg.max()
        case 'maxmax':
            ## Divide each region by largest regional max across all regions
            load_agg /= load_agg.max().max()
        case 'maxmin':
            ## Divide each region by smallest regional max across all regions
            load_agg /= load_agg.max().min()
        case _:
            ## Like 'maxmin' but scaled by the provided numeric value
            load_agg /= load_agg.max().min() * float(sw.GSw_HourlyClusterLoadNorm)

    ### Get the full list of forced periods
    forceperiods = forceperiods_load.copy()
    for tech in forceperiods_minre:
        forceperiods.update(forceperiods_minre[tech])
    ## Make a simpler list without the metadata to use for indexing below
    ## (use list(set()) to drop duplicate force-periods)
    forceperiods_yearperiod = list(set([(i[2], i[3]) for i in forceperiods]))
    ### Add number of force-include periods to GSw_HourlyNumClusters for total number of periods
    num_rep_periods = int(sw['GSw_HourlyNumClusters']) + len(forceperiods)
    ### Record the force-included periods
    print('representative periods: {}'.format(sw['GSw_HourlyNumClusters']))
    print('force-include periods: {}'.format(len(forceperiods)))
    print('    peak-load periods: {}'.format(len(forceperiods_load)))
    for tech in forceperiods_minre:
        print('    min-{} periods: {}'.format(tech, len(forceperiods_minre[tech])))
    print('total periods: {}'.format(num_rep_periods))


    forceperiods_write = pd.DataFrame(
        [['load'] + list(i) for i in forceperiods_load]
        + [[k]+list(i) for k,v in forceperiods_minre.items() for i in v],
        columns=['property','region','reason','year','yperiod'],
    )
    forceperiods_write['szn'] = (
        'y' + forceperiods_write.year.astype(str)
        + ('d' if sw.GSw_HourlyType=='year' else sw.GSw_HourlyType[0])
        + forceperiods_write.yperiod.map('{:>03}'.format)
    )
    forceperiods_write.drop_duplicates('szn', inplace=True)

    ### Package profiles into one dataframe
    profiles = pd.concat({
        **{'load': load_agg},
        **{tech: recf_agg[tech] for tech in techs_vre if tech in recf_agg}
    },
        axis=1,
        names=('property', 'region'),
    ).unstack('h_of_period')

    ### Drop forceperiods for clustering
    profiles_fitperiods_hourly = profiles.loc[~profiles.index.isin(forceperiods_yearperiod)].copy()
    ## Normalize the profiles if desired
    if int(sw.GSw_HourlyNormProfiles):
        profiles_fitperiods_hourly /= profiles_fitperiods_hourly.stack('h_of_period').max()

    ### Aggregate from hours to periods if necessary
    if sw.GSw_HourlyClusterTimestep in ['period','day','wek','week']:
        profiles_fitperiods = (
            profiles_fitperiods_hourly.groupby(axis=1, level=['property','region']).mean())
    else:
        profiles_fitperiods = profiles_fitperiods_hourly.copy()

    #%% Plots
    if int(sw.debug):
        try:
            hourly_plots.plot_unclustered_periods(profiles, sw, reeds_path, figpath)
        except Exception as err:
            print('plot_unclustered_periods failed with the following error:\n{}'.format(err))

        try:
            hourly_plots.plot_feature_scatter(profiles_fitperiods, reeds_path, figpath)
        except Exception as err:
            print('plot_feature_scatter failed with the following error:\n{}'.format(err))


    #%%### Determine representative periods
    print("Identify and weight representative periods")
    ## First weight the profiles
    profiles_fitperiods_weighted = (
        profiles_fitperiods
        .multiply(sw.GSw_HourlyClusterWeights, axis=1, level='property')
        .dropna(axis=1, how='all')
    )

    ## Representative days or weeks
    if sw['GSw_HourlyType'] in ['day','wek']:
        rep_periods, period_szn = cluster_profiles(
            profiles_fitperiods=profiles_fitperiods_weighted,
            sw=sw,
            forceperiods_yearperiod=forceperiods_yearperiod,
        )
        print("Clustering complete")

    ## 8760
    elif sw['GSw_HourlyType']=='year':
        ### For 8760 we use the original seasons
        month2quarter = pd.read_csv(
            os.path.join(inputs_case, 'month2quarter.csv'),
            index_col='month',
        ).squeeze(1).map(lambda x: x[:4])

        period_szn = pd.Series(
            index=timestamps_myr.drop_duplicates('yperiod').yperiod.values,
            data=timestamps_myr.drop_duplicates('yperiod').index.month.map(month2quarter),
            name='szn',
        ).rename_axis('period')

        rep_periods = period_szn.index.tolist()
        forceperiods_write = pd.DataFrame(columns=['property','region','reason','year','yperiod'])


    #%%### Identify a (potentially different) collection of periods to use as initial stress periods
    if ((not int(sw.GSw_PRM_CapCredit))
        and (sw['GSw_PRM_StressSeedMinRElevel'].lower() not in ['false','none'])
    ):
        stressperiods_minre = {
            tech: identify_min_periods(
                df=recf_ra,
                hierarchy=hierarchy,
                level=sw['GSw_PRM_StressSeedMinRElevel'],
                prefix=tech,
            )
            for tech in techs_min_vre}
    else:
        stressperiods_minre = {tech: set() for tech in techs_min_vre}

    if ((not int(sw.GSw_PRM_CapCredit))
        and (sw['GSw_PRM_StressSeedLoadLevel'].lower() not in ['false','none'])
    ):
        ## Get load for all model and weather years
        load_allyears = get_load(inputs_case, keep_weatheryears='all').loc[modelyears]
        ## Add descriptive index
        load_allyears = load_allyears.merge(
            timestamps[['year', 'yperiod', 'h_of_period']], left_on='datetime', right_index=True)
        load_allyears = load_allyears.droplevel('datetime')
        load_allyears.index.names = ['modelyear']
        load_allyears = load_allyears.set_index(['year', 'yperiod', 'h_of_period'], append=True)
        stressperiods_load = {
            y: identify_peak_containing_periods(
                df=load_allyears.loc[y], hierarchy=hierarchy,
                level=sw['GSw_PRM_StressSeedLoadLevel'])
            for y in modelyears
        }
    else:
        stressperiods_load = {y: set() for y in modelyears}

    ## Combine dicts of load and min-wind/solar stress periods into a dataframe with
    ## (modelyear, property, region, reason) index and (weatheryear, period of year, szn)
    ## values.
    stressperiods_write = pd.concat(
        {y: pd.DataFrame(
            [['load'] + list(i) for i in stressperiods_load[y]]
            + [[k]+list(i) for k,v in stressperiods_minre.items() for i in v],
            columns=['property','region','reason','year','yperiod']
         ).drop_duplicates(subset=['year','yperiod'])
         for y in modelyears},
        axis=0, names=['modelyear','index'],
    ).reset_index(level='index', drop=True)
    stressperiods_write['szn'] = (
        'y' + stressperiods_write.year.astype(str)
        + ('d' if sw.GSw_HourlyType=='year' else sw.GSw_HourlyType[0])
        + stressperiods_write.yperiod.map('{:>03}'.format)
    )


    #%%### Get the representative and force periods
    period_szn_write = period_szn.rename('season').reset_index()
    if sw['GSw_HourlyType'] == 'year':
        period_szn_write['year'] = sorted(sw['GSw_HourlyWeatherYears']*365)
        period_szn_write['yperiod'] = period_szn_write.period
    else:
        period_szn_write['rep_period'] = period_szn_write['season'].copy()
        period_szn_write['year'] = period_szn_write.period.map(lambda x: x[0])
        period_szn_write['yperiod'] = period_szn_write.period.map(lambda x: x[1])
    period_szn_write['actual_period'] = (
        'y' + period_szn_write.year.astype(str)
        + ('w' if sw.GSw_HourlyType == 'wek' else 'd')
        + period_szn_write.yperiod.astype(str).map('{:>03}'.format)
    )
    if sw['GSw_HourlyType'] == 'year':
        period_szn_write['rep_period'] = period_szn_write['actual_period'].copy()


    #%% Get some other convenience sets
    timestamps_day = reeds.timeseries.make_timestamps(sw=pd.Series({**sw, **{'GSw_HourlyType':'day'}}))
    timestamps_wek = reeds.timeseries.make_timestamps(sw=pd.Series({**sw, **{'GSw_HourlyType':'wek'}}))
    ## Include all possible seasons so dispatch mode can be rerun with any of them
    quarters = reeds.io.read_input(inputs_case, 'quarter').squeeze(1).tolist()
    set_allszn = pd.Series(
        list(timestamps_day.period.unique())
        + list(timestamps_wek.period.unique())
        + quarters
    )
    ## Include stress periods
    set_allszn = pd.concat([set_allszn, 's'+set_allszn])

    set_allh = pd.concat([
        timestamps_day['timestamp'],
        timestamps_wek['timestamp'],
        's'+timestamps_day['timestamp'],
        's'+timestamps_wek['timestamp'],
    ])

    set_actualszn = (
        period_szn_write['season'].drop_duplicates() if sw['GSw_HourlyType'] == 'year'
        else period_szn_write['actual_period'])

    nextszn = pd.Series(
        index=set_actualszn, data=np.roll(set_actualszn.values, -1), name='actualszn',
    ).rename_axis('*actualszn')

    stress_period_szn = (
        stressperiods_write.assign(rep_period=stressperiods_write.szn)
        [['rep_period','year','yperiod','szn']].rename(columns={'szn':'actual_period'})
    )

    stressperiods_seed = (
        stressperiods_write
        .assign(szn='s'+stressperiods_write.szn)
        .reset_index().rename(columns={'modelyear':'t'})
        [['t','szn']]
    )


    #%%### Plot some stuff
    try:
        hourly_plots.plot_ldc(
            period_szn, profiles, rep_periods,
            forceperiods_write, sw, reeds_path, figpath)
    except Exception:
        print('plot_ldc failed:')
        print(traceback.format_exc())

    if int(sw.debug):
        try:
            hourly_plots.plot_load_days(profiles, rep_periods, period_szn, sw, reeds_path, figpath)
        except Exception:
            print('plot_load_days failed:')
            print(traceback.format_exc())

        try:
            hourly_plots.plot_8760(profiles, period_szn, sw, reeds_path, figpath)
        except Exception:
            print('plot_8760 failed:')
            print(traceback.format_exc())


    #%%### Write the outputs
    period_szn_write.drop('period', axis=1).to_csv(
        os.path.join(inputs_case, periodtype, 'period_szn.csv'), index=False)

    if 'user' not in sw['GSw_HourlyClusterAlgorithm']:
        forceperiods_write.to_csv(
            os.path.join(inputs_case, periodtype, 'forceperiods.csv'), index=False)

    timestamps.to_csv(
        os.path.join(inputs_case, periodtype, 'timestamps.csv'), index=False)

    set_actualszn.to_csv(
        os.path.join(inputs_case, periodtype, 'set_actualszn.csv'), header=False, index=False)

    if minimal:
        return period_szn_write

    #%% Write the sets over all possible periods (representative and stress)
    reeds.io.write_to_inputs_h5(
        set_allszn.rename(), 'allszn', inputs_case, gamstype='set',
        comment='all potentially modeled time periods (days/weks)',
    )
    reeds.io.write_to_inputs_h5(
        set_allh.rename(), 'allh', inputs_case, gamstype='set',
        comment='all potentially modeled time chunks (hour groupings)',
    )

    nextszn.to_csv(os.path.join(inputs_case, 'nextszn.csv'))

    #%% Write the seed stress periods to use for the PRM constraint
    if 'user' in sw.GSw_PRM_StressModel:
        stressperiods_seed = pd.read_csv(os.path.join(inputs_case, 'stressperiods_user.csv'))
        stressperiods_seed.to_csv(os.path.join(inputs_case, 'stressperiods_seed.csv'), index=False)
        _missing = [t for t in modelyears if t not in stressperiods_seed.t.unique()]
        if len(_missing):
            raise Exception(f"Missing user-defined stress periods for {','.join(map(str, _missing))}")
        for t in modelyears:
            ## Write the period_szn file
            szns = stressperiods_seed.loc[stressperiods_seed.t==t, 'szn'].values
            dfwrite = pd.DataFrame({
                'rep_period': [i.strip('s') for i in szns],
                'year': [int(i.strip('sy')[:4]) for i in szns],
                'yperiod': [int(i[-3:]) for i in szns],
                'actual_period': [i.strip('s') for i in szns],
            })
            os.makedirs(os.path.join(inputs_case, f'stress{t}i0'), exist_ok=True)
            dfwrite.to_csv(os.path.join(inputs_case, f'stress{t}i0', 'period_szn.csv'), index=False)
    else:
        stressperiods_seed.to_csv(os.path.join(inputs_case, 'stressperiods_seed.csv'), index=False)
        for t in modelyears:
            os.makedirs(os.path.join(inputs_case, f'stress{t}i0'), exist_ok=True)
            if stressperiods_write.empty:
                pd.DataFrame(columns=['property','region','reason','year','yperiod','szn']).to_csv(
                    os.path.join(inputs_case, f'stress{t}i0', 'forceperiods.csv'), index=False)
            else:
                stressperiods_write.loc[[t]].to_csv(
                    os.path.join(inputs_case, f'stress{t}i0', 'forceperiods.csv'), index=False)
            if stress_period_szn.empty:
                pd.DataFrame(columns=['rep_period','year','yperiod','actual_period']).to_csv(
                    os.path.join(inputs_case, f'stress{t}i0', 'period_szn.csv'), index=False)
            else:
                stress_period_szn.loc[[t]].to_csv(
                    os.path.join(inputs_case, f'stress{t}i0', 'period_szn.csv'), index=False)

    return period_szn_write


#%% ===========================================================================
### --- PROCEDURE ---
### ===========================================================================

if __name__ == '__main__':

    #%% Parse arguments
    parser = argparse.ArgumentParser(
        description='Create the necessary 8760 and capacity factor data for hourly resolution')
    parser.add_argument('reeds_path', help='ReEDS directory')
    parser.add_argument('inputs_case', help='ReEDS/runs/{case}/inputs_case directory')

    args = parser.parse_args()
    reeds_path = args.reeds_path
    inputs_case = args.inputs_case

    # #%% Settings for testing
    # reeds_path = reeds.io.reeds_path
    # inputs_case = os.path.join(
    #     reeds_path,'runs',
    #     'v20260525_repM0_USA_fast','inputs_case','')
    # interactive = True

    #%% Set up logger
    log = reeds.log.makelog(
        scriptname=__file__,
        logpath=os.path.join(inputs_case,'..','gamslog.txt'),
    )
    print('Starting hourly_repperiods.py')
    #%% Inputs from switches
    sw = reeds.io.get_switches(inputs_case)

    #######################################
    #%% Identify the representative periods
    main(sw=sw, reeds_path=reeds_path, inputs_case=inputs_case)

    ####################################################
    #%% Write timeseries data for representative periods
    hourly_writetimeseries.main(
        sw=sw, reeds_path=reeds_path, inputs_case=inputs_case,
        periodtype='rep',
        make_plots=1,
    )

    ############################################
    #%% Write timeseries data for stress periods
    modelyears = pd.read_csv(
        os.path.join(inputs_case, 'modeledyears.csv')).columns.astype(int)
    for t in modelyears:
        print(f'Writing seed stress periods for {t}')
        hourly_writetimeseries.main(
            sw=sw, reeds_path=reeds_path, inputs_case=inputs_case,
            periodtype=f'stress{t}i0',
            make_plots=0,
        )

    #%% All done
    reeds.log.toc(tic=tic, year=0, process='input_processing/hourly_repperiods.py', 
        path=os.path.join(inputs_case,'..'))
    print('Finished hourly_repperiods.py')
