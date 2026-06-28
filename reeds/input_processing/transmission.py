#%% Imports
import argparse
import geopandas as gpd
import pandas as pd
import numpy as np
import sys
import shapely
import datetime
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))
import reeds
tic = datetime.datetime.now()


#%% Functions and constants
METERS_PER_MILE = 1609.34

def sort_regions(df:pd.DataFrame) -> pd.DataFrame:
    """Sort r and rr columns alphabetically"""
    dfout = df.copy()
    dfout.r, dfout.rr = dfout[['r','rr']].min(axis=1), dfout[['r','rr']].max(axis=1)
    return dfout


def keep_longer_entry(df:pd.DataFrame) -> pd.DataFrame:
    """For duplicate entries, keep the version with the longer route"""
    dfout = (
        df.sort_values('length_miles', ascending=False)
        .drop_duplicates(['r','rr','polarity','voltage'], keep='first')
    )
    return dfout


def include_reverse_direction(df:pd.Series, indices=['r', 'rr', 'trtype']):
    """Add duplicate values for (rr,r) direction"""
    assert (('r' in indices) and ('rr' in indices))
    reverse = (
        df.reset_index().rename(columns={'r':'rr', 'rr':'r'})
        .set_index(indices).squeeze(1)
    )
    dfout = pd.concat([df, reverse])
    return dfout


def get_individual_lines(case, **kwargs):
    """Get individual lines existing, prescribed, or considered in this run"""
    sw = reeds.io.get_switches(case, **kwargs)
    fpaths = [
        Path(reeds.io.reeds_path, 'inputs', 'transmission', 'hvdc_existing.csv'),
        Path(reeds.io.reeds_path, 'inputs', 'transmission', 'hvdc_planned-baseline.csv'),
    ]
    if sw.GSw_TransScen != 'none':
        fpaths.append(
            Path(
                reeds.io.reeds_path, 'inputs', 'transmission',
                f'hvdc_planned-{sw.GSw_TransScen}.csv'
            )
        )
    lines = pd.concat([pd.read_csv(fpath, index_col='name') for fpath in fpaths])
    return lines


def _make_line(row):
    """Turn a lat/lon pair into a LineString geometry"""
    return shapely.LineString([[row.start_lon, row.start_lat], [row.end_lon, row.end_lat]])


def get_interface_params(case, **kwargs):
    """Get cost and distance for every interface that might be used in this run"""
    sw = reeds.io.get_switches(case, **kwargs)
    scalars = reeds.io.get_scalars(case)

    interface_params = reeds.inputs.get_distances(case)
    ## Apply the minimum-squiggliness factor
    interface_params['geometry'] = interface_params.apply(_make_line, axis=1)
    interface_params = gpd.GeoDataFrame(interface_params, crs='EPSG:4326')
    interface_params['straight_miles'] = (
        interface_params.geometry.to_crs('EPSG:5070').length
        / METERS_PER_MILE
    )
    interface_params['squiggliness'] = interface_params.length_miles / interface_params.straight_miles
    interface_params['multiplier'] = (
        float(sw['GSw_TransSquigglinessMin']) / interface_params['squiggliness']
    ).clip(lower=1)
    interface_params.loc[:, ['cost_MUSD', 'length_miles']] = (
        interface_params[['cost_MUSD', 'length_miles']]
        .multiply(interface_params['multiplier'], axis=0)
    )
    ## Swapping the start/end points sometimes gives slightly different routes,
    ## resulting in duplicate values. So drop duplicates, keeping the longer route.
    interface_params = keep_longer_entry(interface_params)
    ## Include info for individual lines
    lines = get_individual_lines(case, **kwargs)
    individual_lines = reeds.inputs.map_hvdc_lines_to_interfaces(
        case=case, filename='transmission_cost_distance_lines.csv',
        dtype='cost',
    )
    individual_lines = individual_lines.loc[individual_lines.name.isin(lines.index)].copy()
    individual_lines = keep_longer_entry(sort_regions(individual_lines))
    keepcols = ['r', 'rr', 'polarity', 'voltage', 'cost_MUSD', 'length_miles']
    ## Only keep the individual-line values that are not already included.
    ## (We want to use the zone-geometry-specific endpoints wherever possible;
    ## the individual-line values are just a fallback.)
    interface_params = (
        pd.concat([interface_params[keepcols], individual_lines[keepcols]])
        .drop_duplicates(['r','rr','polarity','voltage'], keep='first')
    )
    ## Make sure there are no duplicates
    if interface_params[['r','rr','polarity']].duplicated().sum():
        dup = interface_params.loc[
            interface_params[['r','rr','polarity']].duplicated(keep=False)
        ].sort_values(['r','rr','polarity'])
        print(dup)
        raise Exception(f'{len(dup)} duplicate entries in interface_params')

    ## Get representative line capacity [MW] and calculate $/MW
    _line_params = {}
    for polarity in ['ac', 'dc']:
        if polarity == 'ac':
            fpath = Path(
                reeds.io.reeds_path, 'inputs', 'transmission',
                f'conductor_{polarity}_{sw.GSw_TransConductor}.csv',
            )
            df = pd.read_csv(fpath)
            df['MVA'] = df.voltage_kv * df.amp * np.sqrt(3) / 1e3
            df['MW'] = df['MVA'] * scalars['power_factor_ac']
        else:
            fpath = Path(reeds.io.reeds_path, 'inputs', 'transmission', f'conductor_{polarity}.csv')
            df = pd.read_csv(fpath)
        _line_params[polarity] = df
    line_params = pd.concat(
        {key: df.set_index('voltage_kv') for key, df in _line_params.items()},
        names=('polarity','voltage'),
    ).MW
    interface_params = interface_params.merge(line_params, on=['polarity','voltage'], how='left')

    ## Convert to output dollaryear
    inflatable = reeds.io.get_inflatable()
    input_dollar_year = pd.read_csv(
        Path(reeds.io.reeds_path, 'inputs', 'transmission', 'dollaryear.csv'), index_col=0,
    ).squeeze(1)

    deflator = inflatable[input_dollar_year['transmission_cost_distance.csv'], int(sw.dollar_year)]
    interface_params[f'USD{sw.dollar_year}perMW'] = (
        interface_params['cost_MUSD'] * 1e6
        / interface_params['MW']
        * deflator
    )
    interface_params[f'USD{sw.dollar_year}perMWmile'] = (
        interface_params[f'USD{sw.dollar_year}perMW']
        / interface_params['length_miles']
    )
    interface_params[f'USD{sw.dollar_year}perMile'] = (
        interface_params['cost_MUSD'] * 1e6 / interface_params['length_miles']
    )

    ### Calculate losses
    tranloss_fixed = {
        'AC': 1 - scalars['converter_efficiency_ac'],
        'B2B': 1 - scalars['converter_efficiency_lcc'],
        'LCC': 1 - scalars['converter_efficiency_lcc'],
        'VSC': 1 - scalars['converter_efficiency_vsc'],
    }
    ## B2B converters are AC-AC/DC-DC/AC-AC, so use AC per-mile losses
    trtypes = {'AC':'ac', 'B2B':'ac', 'LCC':'dc', 'VSC':'dc'}
    tranloss_permile = {
        trtype: scalars[f'tranloss_permile_{polarity}'] for trtype, polarity in trtypes.items()
    }
    def _getloss(row):
        """
        Fixed losses are entered as per-endpoint values (e.g. for each AC/DC converter station
        on a LCC DC line). There are two endpoints per line, so multiply fixed losses by 2.
        Note that this approach only applies for LCC DC lines; VSC AC/DC losses are applied later.
        """
        return row.length_miles * tranloss_permile[row.trtype] + tranloss_fixed[row.trtype] * 2

    interface_params = pd.concat({
        trtype: interface_params.loc[interface_params.polarity == polarity]
        for trtype, polarity in trtypes.items()
    }, names=('trtype', 'drop')).reset_index().drop(columns=['drop'])
    interface_params['loss'] = interface_params.apply(lambda row: _getloss(row), axis=1)

    return interface_params.rename(columns={'length_miles':'miles'})


def get_trancap_fut(case):
    """Get certain and possible transmission additions"""
    sw = reeds.io.get_switches(case)
    scalars = reeds.io.get_scalars(case)
    ## Always-included lines
    planned_capacity = reeds.inputs.map_hvdc_lines_to_interfaces(
        case=case, filename='hvdc_planned-baseline.csv',
    )
    ## Scenario-specific lines
    if sw.GSw_TransScen != 'none':
        planned_capacity = pd.concat([
            planned_capacity,
            reeds.inputs.map_hvdc_lines_to_interfaces(
                case=case, filename=f'hvdc_planned-{sw.GSw_TransScen}.csv',
            )
        ])
    ## Offshore lines
    if int(sw.GSw_OffshoreZones):
        zonepath = Path(reeds.io.reeds_path, 'inputs', 'zones', sw.GSw_ZoneSet)
        ## Land-to-offshore links (these are only built for offshore wind delivery
        ## so they won't be built early unless there's exogenous offshore wind)
        fpath_land = Path(zonepath, 'newlinks_offshore_radial.csv')
        offshore_land = (
            pd.read_csv(fpath_land)
            .assign(year_online=int(sw.startyear))
            .assign(name='radial')
        )
        ## Offshore-to-offshore backbone links
        fpath_offshore = Path(
            reeds.io.reeds_path, 'inputs', 'transmission', 'newlinks_offshore_backbone.csv',
        )
        offshore_offshore = (
            pd.read_csv(fpath_offshore)
            .assign(year_online=0)
            .assign(name='backbone')
        )
        offshore_links = (
            pd.concat([offshore_land, offshore_offshore])
            .assign(trtype='VSC')
            .assign(certain=0)
            .assign(MW=100000)
        ).set_index(['r','rr','trtype','year_online','certain'])
        planned_capacity = pd.concat([planned_capacity, offshore_links])
    trancap_fut = (
        planned_capacity.reset_index()
        .rename(columns={'year_online':'t', 'certain':'status'})
        .astype({'t':int})
        ## '0' is used as a filler value in the t column for firstyear_trans,
        ## so we replace it whenever we load a transmission_capacity_future file.
        .replace({
            't': {0: int(scalars['firstyear_trans_longterm'])},
            'status': {0:'possible', 1:'certain'}
        })
        [['r', 'rr', 'status', 'trtype', 't', 'MW']]
        .astype({'t':int}).round(3)
    )

    return trancap_fut


def get_firm_import_limit(case):
    """Limits on PRMTRADE across nercr boundaries"""
    sw = reeds.io.get_switches(case)
    if not int(sw.GSw_PRM_NetImportLimit):
        ## No limit
        firm_import_limit = pd.DataFrame(columns=['nercr','t','fraction']).set_index(['nercr','t'])
    else:
        limits = pd.Series(
            {int(i.split('_')[0]): i.split('_')[1] for i in sw.GSw_PRM_NetImportLimitScen.split('/')}
        )

        solveyears = pd.read_csv(
            Path(case, 'inputs_case', 'modeledyears.csv')
        ).columns.astype(int).tolist()
        startyear = min(solveyears)
        endyear = max(solveyears)
        allyears = range(startyear, max(endyear, limits.index.max())+1)

        ## calculate the historical net_firm_import fraction for each region and drop negative values
        peak_net_imports = pd.read_csv(
            Path(case, 'inputs_case', 'peak_net_imports.csv'),
            index_col=['nercr']
        )
        net_firm_import_frac = (
            peak_net_imports.MW / peak_net_imports.MW_TotalDemand
        ).clip(lower=0)
        nercrs = net_firm_import_frac.index

        _dfout = {}
        for key, val in limits.items():
            ## If 'hist' is in GSw_PRM_NetImportLimitScen,
            ## all years up until that year use the historical regional max
            if val == 'hist':
                for y in range(startyear, key+1):
                    _dfout[y] = net_firm_import_frac
            ## If 'histmax', all prior years use the historical max across all regions
            elif val == 'histmax':
                for y in range(startyear, key+1):
                    _dfout[y] = net_firm_import_frac.clip(lower=net_firm_import_frac.max())
            else:
                ## Input values are percentages so convert to fractions
                _dfout[key] = pd.Series(index=nercrs, data=float(val) / 100)

        firm_import_limit = (
            pd.concat(_dfout, names=('t',)).unstack('nercr')
            ## Linear interpolation between values; flat projections before and after
            .reindex(allyears).interpolate('linear').bfill().ffill()
            .loc[solveyears]
            .unstack('t').rename('fraction')
        )

    return firm_import_limit.reset_index()


def get_trancap_init(case, interface_params, level='r'):
    """
    AC capacity is defined for each direction and calculated using the scripts at
    https://github.nrel.gov/ReEDS/TSC
    """
    sw = reeds.io.get_switches(case)
    trancap_init_ac = (
        reeds.inputs.get_itls(case, level=level, GSw_ZoneSet=sw.GSw_ZoneSet)
        [['r', 'rr', 'MW_forward', 'MW_reverse']]
        .assign(trtype='AC')
    )
    valid_regions = {}
    for i in ['r', 'itlgrp', 'transgrp']:
        valid_regions[i] = reeds.io.read_input(case, i).squeeze(1).tolist()

    ### DC
    if level == 'r':
        ## transgrp capacity is only defined for AC
        hvdc = (
            reeds.inputs.map_hvdc_lines_to_interfaces(case, filename='hvdc_existing.csv')
            .reset_index()
        )
        b2b = reeds.inputs.get_b2b(case).assign(trtype='B2B')
        ## DC capacity is only defined in one direction,
        ## so duplicate it for the opposite direction
        trancap_init_nonac_undup = pd.concat([hvdc, b2b])[['r', 'rr', 'trtype', 'MW']]
        trancap_init_nonac = pd.concat([
            trancap_init_nonac_undup,
            trancap_init_nonac_undup.rename(columns={'r':'rr', 'rr':'r'})
        ], axis=0)
    else:
        trancap_init_nonac = pd.DataFrame(columns=['r', 'rr', 'trtype', 'MW'])

    ### Initial trading limit, using contingency levels specified by contingency level
    ### (but assuming full capacity of DC is available for both energy and capcity)
    dfout = (
        pd.concat(
            [
                ## AC
                pd.concat([
                    ## Forward direction
                    (trancap_init_ac[['r', 'rr', 'trtype', 'MW_forward']]
                    .rename(columns={'MW_forward':'MW'})),
                    ## Reverse direction
                    (trancap_init_ac[['r', 'rr', 'trtype', 'MW_reverse']]
                    .rename(columns={'r':'rr', 'rr':'r', 'MW_reverse':'MW'}))
                ], axis=0),
                ## DC
                trancap_init_nonac[['r', 'rr', 'trtype', 'MW']]
            ],
            axis=0
        )
        ## Drop entries with zero capacity
        .replace(0.,np.nan).dropna()
        .groupby(['r', 'rr', 'trtype']).sum().reset_index()
    )
    dfout = dfout.loc[
        dfout['r'].isin(valid_regions[level])
        & dfout['rr'].isin(valid_regions[level])
    ].copy()

    ### Drop county interfaces with no distance/cost if applicable
    drop_interfaces = sw.GSw_ZoneSet in reeds.inputs.get_applicable_zonesets(
        'drop_interfaces_missing_cost'
    )
    if (level == 'r') and drop_interfaces:
        transmission_line_fom = get_transmission_fom(case, interface_params)
        indices = ['r', 'rr', 'trtype']
        drop = (
            dfout
            .merge(transmission_line_fom.reset_index(), on=indices, how='left')
        )
        drop = list(drop.loc[drop.USDperMWyear.isnull(), indices].itertuples(index=False))
        dfout = dfout.set_index(indices).drop(drop).reset_index()

    ## Get alias for level (e.g. rr, transgrpp)
    levell = level + level[-1]
    dfout = (
        dfout
        .rename(columns={'r':level, 'rr':levell})
        .round(3)
    )
    return dfout


def get_transmission_fom(case, interface_params):
    """Get transmission fixed operations & maintenance (FOM) costs"""
    sw = reeds.io.get_switches(case)
    scalars = reeds.io.get_scalars(case)

    ### Get the line-specific transmission FOM costs [$/MW/year]
    trans_fom_frac = scalars['trans_fom_frac']

    ### For simplicity we just take the unweighted average greenfield $/MWmile cost
    ### across all interfaces.
    ### Future work should identify a better assumption.
    transfom_USDperMWmileyear = (
        interface_params.groupby('trtype')[f'USD{sw.dollar_year}perMWmile'].mean()
        * trans_fom_frac
    )

    ### Multiply $/MW/mile/year by distance [miles] to get $/MW/year for ALL lines
    transmission_line_fom = interface_params.copy()
    transmission_line_fom['USDperMWyear'] = transmission_line_fom.apply(
        lambda row: transfom_USDperMWmileyear[row.trtype] * row.miles,
        axis=1
    )
    transmission_line_fom = (
        transmission_line_fom
        .set_index(['r','rr','trtype'])
        .USDperMWyear
        .round(2)
    )
    ## Include both directions
    transmission_line_fom = include_reverse_direction(transmission_line_fom)
    dups = transmission_line_fom.index.duplicated()
    if dups.sum():
        print(transmission_line_fom.loc[dups])
        raise ValueError(f'{len(dups)} duplicate values in transmission_line_fom')
    return transmission_line_fom


def convert_to_tsc(interface_params, dollar_year=2004):
    """Convert greenfield costs into single-bin transmission upgrade supply curves (TSC)"""
    transmission_cost_ac = interface_params.loc[
        interface_params.trtype=='AC',
        ['r', 'rr', f'USD{dollar_year}perMW']
    ].copy()
    transmission_cost_ac = (
        transmission_cost_ac
        .rename(columns={f'USD{dollar_year}perMW':f'USD{dollar_year}perMW_forward'})
        .assign(**{f'USD{dollar_year}perMW_reverse':transmission_cost_ac[f'USD{dollar_year}perMW']})
        .assign(tscbin='t0')
        .assign(**{f'binwidth_USD{dollar_year}':1e12})
        [[
            'r', 'rr', 'tscbin', f'binwidth_USD{dollar_year}',
            f'USD{dollar_year}perMW_forward', f'USD{dollar_year}perMW_reverse',
        ]]
    )
    _test = transmission_cost_ac.r < transmission_cost_ac.rr
    if not _test.all():
        print(transmission_cost_ac.loc[~_test])
        raise ValueError('Region must be lexicographically sorted so r < rr')
    return transmission_cost_ac


def get_transmission_cost(case, interface_params):
    """Get ReEDS-formatted AC transmission upgrade cost curves"""
    sw = reeds.io.get_switches(case)
    if sw.GSw_TransUpgradeMethod == 'greenfield':
        transmission_cost_ac = convert_to_tsc(interface_params, sw.dollar_year)
    else:
        fpath = Path(
            reeds.io.reeds_path, 'inputs', 'transmission',
            f'transmission_cost_ac_{sw.GSw_TransUpgradeMethod}_{sw.GSw_ZoneSet}.h5'
        )
        transmission_cost_ac = reeds.io.read_file(fpath).reset_index()
        for col in ['r', 'rr', 'tscbin']:
            transmission_cost_ac[col] = transmission_cost_ac[col].str.decode('utf-8')
    ### Interfaces are always defined with the zones sorted in lexicographic order
    reverse_interfaces = transmission_cost_ac.loc[
        transmission_cost_ac.apply(lambda row: row.r > row.rr, axis=1)
    ]
    for i, row in reverse_interfaces.iterrows():
        transmission_cost_ac.loc[i, ['r', 'rr']] = transmission_cost_ac.loc[i, ['rr', 'r']].values
        transmission_cost_ac.loc[i, ['USD2004perMW_forward', 'USD2004perMW_reverse']] = (
            transmission_cost_ac.loc[i, ['USD2004perMW_reverse', 'USD2004perMW_forward']].values
        )

    _test = transmission_cost_ac.apply(lambda row: row.r < row.rr, axis=1)
    if not _test.all():
        print(transmission_cost_ac.loc[~_test])
        err = (
            "Must have r < rr in AC transmission cost inputs but the interfaces "
            "listed above are out of order"
        )
        raise ValueError(err)
    return transmission_cost_ac


def get_transmission_cost_nonac(case, interface_params):
    """Get HVDC and B2B costs"""
    transmission_cost_nonac = interface_params.loc[
        interface_params.trtype != 'AC',
        ['r', 'rr', 'trtype', f'USD{reeds.io.get_switches(case).dollar_year}perMW']
    ].round(2).set_index(['r','rr','trtype']).squeeze(1)
    transmission_cost_nonac = include_reverse_direction(transmission_cost_nonac).reset_index()
    return transmission_cost_nonac


def get_hurdle_rates(case, hurdle_level=1):
    """Get hurdle rates on transmission flows (wheeling charges) used in this run"""
    sw = reeds.io.get_switches(case)
    cost_hurdle_intra = (
        pd.read_csv(Path(reeds.io.reeds_path, 'inputs', 'transmission', 'cost_hurdle_intra.csv'))
        .set_index('t').round(3)
    )
    cost_hurdle_rate = (
        cost_hurdle_intra[sw[f'GSw_TransHurdleLevel{hurdle_level}']].rename('USDperMWh')
        if int(sw.GSw_TransHurdleRate)
        else pd.Series(name='USDperMWh').rename_axis('t')
    )
    return cost_hurdle_rate.reset_index()


def calculate_adjacent_routes(case):
    """Determine which pairs of model regions are adjacent to each other"""
    dfzones = reeds.io.get_dfmap(case, levels=['r'], exclude_water_areas=True)['r']
    routes_adjacent = dfzones.copy()
    routes_adjacent['r_adj'] = routes_adjacent.apply(
        axis=1,
        func=lambda x: (
            routes_adjacent.loc[(
                routes_adjacent.touches(x['geometry'])
                | routes_adjacent.overlaps(x['geometry'])
            )]
            .index
            .values
            .tolist()
        )
    )
    # Reformat so that each row represents a pair of regions
    routes_adjacent = (
        routes_adjacent.drop(columns='geometry')
        .explode('r_adj')
        .reset_index(names=['r'])
        .rename(columns={'r_adj': 'rr'})
        [['r', 'rr']]
        .dropna()
    )

    return routes_adjacent


def get_pipeline_cost_mult(case, interface_params, transmission_cost_nonac):
    """
    Calculate H2 pipeline cost multipliers by dividing the [$/mile] cost of DC transmission
    between each pair of regions by the minimum interface [$/mile] cost for DC transmission
    and subtracting 1 to get a fractional adder (which is then added to 1 in b_inputs.gms)
    """
    sw = reeds.io.get_switches(case)
    if len(transmission_cost_nonac):
        dc_cost_permile = (
            interface_params.loc[interface_params.trtype=='VSC']
            .set_index(['r','rr'])[f'USD{sw.dollar_year}perMile']
        )
        pipeline_cost_mult = (
            (dc_cost_permile.rename('multiplier') / dc_cost_permile.min() - 1)
            .reset_index().round(3)
        )
    else:
        pipeline_cost_mult = pd.DataFrame(columns=['r','rr','multiplier'])
    return pipeline_cost_mult


def calculate_co2_storage_routes(dfzones, max_miles=200):
    """
    Determine spurline routes from model regions to carbon storage sites.
    Keep storage sites that are within {max_miles} miles
    of each region's transmission endpoint.
    """
    scalars = reeds.io.get_scalars(case)
    co2_storage_sites = reeds.io.get_co2_storage_sites()
    dfzones = reeds.io.get_dfmap(case, levels=['r'], exclude_water_areas=True)['r']
    region_centroids = (
        gpd.GeoDataFrame(
            dfzones[['x', 'y']],
            geometry=gpd.points_from_xy(dfzones.x, dfzones.y),
            crs=dfzones.crs
        )
        [['geometry']]
        .rename_axis(index='r')
        .reset_index()
    )
    region_centroids['cs'] = region_centroids.apply(
        axis=1,
        func=lambda x: (
            co2_storage_sites.loc[(
                co2_storage_sites.distance(x['geometry']) / METERS_PER_MILE <= max_miles
            )]
            ['cs']
            .tolist()
        )
    )

    # Calculate the lengths of the spurlines between regions and storage sites,
    # excluding routes not completely within the U.S.
    routes_cs = (
        region_centroids.explode('cs')
        .merge(
            co2_storage_sites[['cs', 'geometry']],
            on='cs',
            suffixes=('_region', '_site')
        )
        .assign(
            geometry=lambda x: (
                gpd.GeoSeries(x['geometry_region'])
                .shortest_line(gpd.GeoSeries(x['geometry_site']))
            )
        )
        [['r', 'cs', 'geometry']]
    )
    routes_cs = gpd.GeoDataFrame(routes_cs, geometry='geometry', crs=dfzones.crs)
    routes_cs = routes_cs.loc[(
        routes_cs.within(
            reeds.io.get_dfmap(levels=['country'])['country'].loc['USA','geometry']
        )
        | (routes_cs.length == 0)
    )]
    routes_cs['distance_m'] = routes_cs.length
    ## Wherever BA centroids fall within formation boundaries, assume some minimal
    # spur line distance to connect a CCS or DAC plant with an injection site
    routes_cs['miles'] = (
        (routes_cs['distance_m'] / METERS_PER_MILE)
        .clip(lower=scalars.min_co2_spurline_miles)
        .round(2)
    )

    return routes_cs


def check_nonac_costs(trancap_fut, trancap_init_energy, transmission_cost_nonac):
    """Make sure every non-AC transmission route has a cost"""
    routecols = ['r', 'rr', 'trtype']
    rename = {'r':'rr', 'rr':'r'}
    ## Add both directions and sort them
    routes = pd.concat([
        trancap_fut[routecols],
        trancap_fut.rename(columns=rename)[routecols],
        trancap_init_energy[routecols],
        trancap_init_energy.rename(columns=rename)[routecols],
    ])
    routes.r, routes.rr = routes[['r','rr']].min(axis=1), routes[['r','rr']].max(axis=1)
    routes = routes.loc[routes.trtype != 'AC'].drop_duplicates()
    ## Make sure each has a cost
    dfcost = transmission_cost_nonac.copy()
    dfcost.r, dfcost.rr = dfcost[['r','rr']].min(axis=1), dfcost[['r','rr']].max(axis=1)
    dftest = routes.merge(dfcost, on=routecols, how='left').set_index(routecols).squeeze(1)
    missing = dftest.loc[dftest.isnull()]
    if len(missing):
        print(missing)
        raise ValueError(f'Missing non-AC transmission costs for {len(missing)} routes')


#%% Main function
def main(case):
    #%% Calculate parameters
    outputs = {}
    outputs['firm_import_limit'] = get_firm_import_limit(case)

    interface_params = get_interface_params(case)

    outputs['transmission_miles'] = interface_params[['r','rr','trtype','miles']].round(3)
    outputs['tranloss'] = interface_params[['r','rr','trtype','loss']].round(5)
    outputs['transmission_line_fom'] = get_transmission_fom(case, interface_params).reset_index()
    outputs['trancap_fut'] = get_trancap_fut(case)
    outputs['transmission_cost_nonac'] = get_transmission_cost_nonac(case, interface_params)
    ## A few downstream processes expect a single distance for each zone pair;
    ## keep the longest
    outputs['transmission_distance'] = (
        outputs['transmission_miles'].drop(columns='trtype')
        .sort_values('miles', ascending=False).drop_duplicates(['r','rr'], keep='first')
        .sort_values(['r','rr'])
    )

    for hurdle_level in [1, 2]:
        outputs[f'cost_hurdle_rate{hurdle_level}'] = get_hurdle_rates(case, hurdle_level)

    for captype, level in [
        ('energy', 'r'),
        ('transgroup', 'transgrp'),
    ]:
        outputs[f'trancap_init_{captype}'] = get_trancap_init(
            case=case, interface_params=interface_params, level=level,
        )
    outputs['trancap_init_prm'] = outputs['trancap_init_energy']

    check_nonac_costs(
        trancap_fut=outputs['trancap_fut'],
        trancap_init_energy=outputs['trancap_init_energy'],
        transmission_cost_nonac=outputs['transmission_cost_nonac'],
    )

    ### TEMPORARY 20260402: Skip itlgrp functionality until we fix it
    # ### Also write itlgrp capacity
    # trancap_itlgrp = trancap_init['energy'].copy()
    # ## Map counties to itlgrp's
    # hierarchy_itlgrp = pd.read_csv(Path(inputs_case, 'hierarchy_itlgrp.csv'))
    # itl_d = dict(zip(hierarchy_itlgrp['r'], hierarchy_itlgrp['itlgrp']))
    # for r in ['r', 'rr']:
    #     trancap_itlgrp[r] = trancap_itlgrp[r].map(lambda x: itl_d.get(x,x))
    # outputs['trancap_itlgrp'] = (
    #     trancap_itlgrp
    #     .rename(columns={'r':'itlgrp', 'rr':'itlgrpp'}).round(3)
    # )

    ### Transmission upgrade supply curve
    transmission_cost_ac = get_transmission_cost(case, interface_params)
    labels = {
        'binwidth_USD2004': 'binwidth',
        'USD2004perMW_forward': 'forward',
        'USD2004perMW_reverse': 'reverse',
    }
    for col, label in labels.items():
        outputs[f'tsc_{label}'] = (
            transmission_cost_ac[['r','rr','tscbin',col]]
            .round(2)
        )
    outputs['tscbin'] = transmission_cost_ac.tscbin.drop_duplicates().rename()
    ## Write transmission_cost_ac for R2X
    outputs['transmission_cost_ac'] = transmission_cost_ac

    ### Pipelines
    outputs['pipeline_cost_mult'] = get_pipeline_cost_mult(
        case,
        interface_params,
        outputs['transmission_cost_nonac'],
    )
    outputs['routes_adjacent'] = calculate_adjacent_routes(case)

    ### CO2 storage sites
    routes_cs = calculate_co2_storage_routes(case)
    outputs['r_cs'] = routes_cs[['r', 'cs']]
    outputs['r_cs_distance_mi'] = routes_cs[['r', 'cs', 'miles']]

    # Determine sites that have valid routes to model regions
    val_cs = pd.Series(routes_cs['cs'].unique())
    outputs['val_cs'] = val_cs

    # Subset CO2 site characteristics data to valid sites
    co2_site_char = pd.read_csv(Path(reeds.io.reeds_path, 'inputs', 'ctus', 'co2_site_char.csv'))
    outputs['co2_site_char'] = co2_site_char.loc[co2_site_char['cs'].isin(val_cs)]

    #%% Downselect to active regions
    table = {'co2_site_char': True}
    hierarchy = reeds.io.get_hierarchy(case).reset_index()
    for key, df in outputs.items():
        columns = df.columns if isinstance(df, pd.DataFrame) else []
        for level in hierarchy:
            levell = level + level[-1]
            if level in columns:
                df = df.loc[df[level].isin(hierarchy[level])]
            if levell in columns:
                df = df.loc[df[levell].isin(hierarchy[level])]
        ### Add '*' to the beginning so GAMS reads the header as a comment
        if not table.get(key, False):
            if isinstance(df, pd.DataFrame):
                df = df.rename(columns={df.columns[0]: '*'+str(df.columns[0])})
            else:
                df = df.rename('*'+df.name) if df.name else df
        outputs[key] = df

    #%% Write the outputs
    header = {
        'val_cs': False,
        'tscbin': False,
    }
    inputs_h5 = {
        'tscbin': ('set', 'transmission upgrade supply curve bins'),
    }
    for key, df in outputs.items():
        if key in inputs_h5:
            gamstype, comment = inputs_h5[key]
            reeds.io.write_to_inputs_h5(df, key, case, gamstype=gamstype, comment=comment)
        else:
            df.to_csv(
                Path(case, 'inputs_case', f'{key}.csv'),
                index=False, header=header.get(key, True),
            )

    #%% Done
    return outputs


#%% Procedure
if __name__ == '__main__':
    #%% Parse arguments
    parser = argparse.ArgumentParser(description="Format and write climate inputs")
    parser.add_argument('reeds_path', help='ReEDS directory')
    parser.add_argument('inputs_case', help='output directory (inputs_case)')

    args = parser.parse_args()
    case = Path(args.inputs_case).parent

    # #%% Settings for testing ###
    # case = str(Path(reeds.io.reeds_path, 'runs', 'v20260601_transcostM1_USA_faster'))

    #%% Set up logger
    log = reeds.log.makelog(scriptname=__file__, logpath=Path(case, 'gamslog.txt'))
    print('Starting transmission.py', flush=True)

    #%% Run it
    main(case)

    #%% Finish the timer
    reeds.log.toc(tic=tic, year=0, process='input_processing/transmission.py', path=case)
    print('Finished transmission.py', flush=True)
