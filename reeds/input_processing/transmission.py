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

    ### TEMPORARY 20260402: Drop county interfaces with no distance/cost
    if (level == 'r') and (sw.GSw_RegionResolution in ['county', 'mixed']):
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


#%% ===========================================================================
### --- PROCEDURE ---
### ===========================================================================

#%% Limits on PRMTRADE across nercr boundaries
if not int(sw.GSw_PRM_NetImportLimit):
    ## No limit
    firm_import_limit = pd.DataFrame(columns=['*nercr','t','fraction']).set_index(['*nercr','t'])
else:
    limits = pd.Series(
        {int(i.split('_')[0]): i.split('_')[1] for i in sw.GSw_PRM_NetImportLimitScen.split('/')}
    )

    solveyears = pd.read_csv(
        os.path.join(inputs_case,'modeledyears.csv')
    ).columns.astype(int).tolist()
    startyear = min(solveyears)
    endyear = max(solveyears)
    allyears = range(startyear, max(endyear, limits.index.max())+1)

    ## calculate the historical net_firm_import fraction for each region and drop negative values
    peak_net_imports = pd.read_csv(
        os.path.join(inputs_case,'peak_net_imports.csv'),
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
        .unstack('t').rename('fraction').rename_axis(['*nercr','t'])
    )

firm_import_limit.to_csv(os.path.join(inputs_case, 'firm_import_limit.csv'))


#%% Load the transmission scalars
scalars = reeds.io.get_scalars(inputs_case)
### Put some in dicts for easier access
tranloss_permile = {
    'AC': scalars['tranloss_permile_ac'],
    ### B2B converters are AC-AC/DC-DC/AC-AC, so use AC per-mile losses
    'B2B': scalars['tranloss_permile_ac'],
    'LCC': scalars['tranloss_permile_dc'],
    'VSC': scalars['tranloss_permile_dc'],
}
tranloss_fixed = {
    'AC': 1 - scalars['converter_efficiency_ac'],
    'B2B': 1 - scalars['converter_efficiency_lcc'],
    'LCC': 1 - scalars['converter_efficiency_lcc'],
    'VSC': 1 - scalars['converter_efficiency_vsc'],
}


#%% Get single-link distances and losses
interface_params = pd.read_csv(
    os.path.join(inputs_case,'transmission_distance.csv'),
)
interface_params['r_rr'] = interface_params.r + '_' + interface_params.rr

# Apply the distance multiplier
interface_params['miles'] = interface_params['miles'] * float(sw.GSw_TransSquiggliness)

# Make sure there are no duplicates
if interface_params[['r','rr']].duplicated().sum():
    print(
        interface_params.loc[
            interface_params[['r','rr']].duplicated(keep=False)
        ].sort_values(['r','rr'])
    )
    raise Exception('Duplicate entries in transmission_distance.csv')

### Calculate losses
def getloss(row, trtype='AC'):
    """
    Fixed losses are entered as per-endpoint values (e.g. for each AC/DC converter station
    on a LCC DC line). There are two endpoints per line, so multiply fixed losses by 2.
    Note that this approach only applies for LCC DC lines; VSC AC/DC losses are applied later.
    """
    return row.miles * tranloss_permile[trtype] + tranloss_fixed[trtype] * 2

trtypes = ['AC', 'LCC', 'B2B', 'VSC']
interface_params = pd.concat(
    {
        trtype:
        interface_params.assign(loss=interface_params.apply(getloss, args=(trtype,), axis=1))
        for trtype in trtypes
    },
    axis=0,
    names=('trtype',),
).reset_index(level='trtype').set_index(['r','rr','trtype'])


#%% Include distances for existing lines
transmission_distance = interface_params.miles.copy()

#%% Write the line-specific transmission FOM costs [$/MW/year]
trans_fom_region_mult = int(scalars['trans_fom_region_mult'])
trans_fom_frac = scalars['trans_fom_frac']

### For simplicity we just take the unweighted average base cost across
### the four regions for which we have transmission cost data.
### Future work should identify a better assumption.
rev_transcost_base = pd.read_csv(
    os.path.join(inputs_case,'rev_transmission_basecost.csv'),
    header=[0], skiprows=[1],
).replace({'500ACsingle':'AC','500DCbipole':'LCC'}).set_index('Voltage')

transfom_USDperMWmileyear = {
    trtype: (
        rev_transcost_base.loc[trtype][['TEPPC','SCE','MISO','Southeast']].mean()
        * trans_fom_frac
    )
    for trtype in ['AC','LCC']
}
### B2B is treated like (AC line)-(AC/DC converter)-(AC/DC converter)-(AC line) so uses AC line FOM
transfom_USDperMWmileyear['B2B'] = transfom_USDperMWmileyear['AC']
transfom_USDperMWmileyear['VSC'] = transfom_USDperMWmileyear['LCC']

if trans_fom_region_mult:
    ### Multiply line-specific $/MW by FOM fraction to get $/MW/year
    transmission_line_fom = interface_params[costcol] * trans_fom_frac
    ### Use regional average * distance_initial for existing lines
    append = transmission_distance.loc[
        transmission_distance.reset_index().trtype.isin(
            ['AC','LCC','B2B','VSC']).set_axis(transmission_distance.index)
    ]
else:
    ### Multiply $/MW/mile/year by distance [miles] to get $/MW/year for ALL lines
    transmission_line_fom = (
        transmission_distance.reset_index().trtype.map(transfom_USDperMWmileyear)
        * transmission_distance.values
    ).set_axis(transmission_distance.index).rename('USDperMWyear')


#%%### Write files for ReEDS (adding * to make GAMS read column names as comment)
### transmission_distance
transmission_distance.round(3).reset_index().rename(columns={'r':'*r'}).to_csv(
    os.path.join(inputs_case,'transmission_miles.csv'), index=False)

### tranloss
tranloss = interface_params['loss'].reset_index()
tranloss.round(decimals).rename(columns={'r':'*r'}).to_csv(
    os.path.join(inputs_case,'tranloss.csv'), index=False, header=True)

### transmission_line_fom
transmission_line_fom.round(2).rename_axis(('*r','rr','trtype')).to_csv(
    os.path.join(inputs_case,'transmission_line_fom.csv'))

#%% Write the initial capacities
case = Path(inputs_case).parent
trancap_init = {}
for captype, level in [
    ('energy', 'r'),
    ('transgroup', 'transgrp'),
]:
    trancap_init[captype] = get_trancap_init(
        case=case, networksource=sw.GSw_TransNetworkSource, level=level)
    ### TEMPORARY 20260402: Drop county interfaces with no distance/cost
    if (level == 'r') and (sw.GSw_RegionResolution in ['county', 'mixed']):
        indices = ['r', 'rr', 'trtype']
        drop = (
            trancap_init[captype]
            .merge(transmission_line_fom.reset_index(), on=indices, how='left')
        )
        drop = list(drop.loc[drop.USDperMWyear.isnull(), indices].itertuples(index=False))
        trancap_init[captype] = trancap_init[captype].set_index(indices).drop(drop).reset_index()
    trancap_init[captype].rename(columns={level:'*'+level}).round(3).to_csv(
        os.path.join(inputs_case,f'trancap_init_{captype}.csv'),
        index=False,
    )
trancap_init['energy'].rename(columns={'r':'*r'}).round(3).to_csv(
    os.path.join(inputs_case,'trancap_init_prm.csv'),
    index=False,
)
### TEMPORARY 20260402: Skip itlgrp functionality until we fix it
# ### Also write itlgrp capacity
# trancap_itlgrp = trancap_init['energy'].copy()
# ## Map counties to itlgrp's
# hierarchy_itlgrp = pd.read_csv(os.path.join(inputs_case, 'hierarchy_itlgrp.csv'))
# itl_d = dict(zip(hierarchy_itlgrp['*r'], hierarchy_itlgrp['itlgrp']))
# for r in ['r', 'rr']:
#     trancap_itlgrp[r] = trancap_itlgrp[r].map(lambda x: itl_d.get(x,x))
# trancap_itlgrp.rename(columns={'r':'*itlgrp', 'rr':'itlgrpp'}).round(3).to_csv(
#     os.path.join(inputs_case, 'trancap_init_itlgrp.csv'),
#     index=False,
# )


#%%### Future transmission capacity
## note that '0' is used as a filler value in the t column for firstyear_trans, which is defined
## in inputs/scalars.csv. So we replace it whenever we load a transmission_capacity_future file.
trancap_fut = (
    pd.concat(
        [
            pd.read_csv(
                os.path.join(inputs_case, 'transmission_capacity_future_baseline.csv'),
                comment='#',
            ),
            pd.read_csv(
                os.path.join(inputs_case, 'transmission_capacity_future.csv'),
                comment='#',
            )
        ],
        axis=0,
        ignore_index=True,
    )
    .astype({'t': int})
    .drop(['Notes', 'notes', 'Note', 'note'], axis=1, errors='ignore')
    .replace({'t': {0: int(scalars['firstyear_trans_longterm'])}})
)

### Drop prospective AC lines from years <= trans_init_year
trancap_fut = trancap_fut.drop(
    trancap_fut.loc[
        (trancap_fut.t <= trans_init_year)
        & (trancap_fut.trtype == 'AC')
    ].index,
).copy()

trancap_fut.rename(columns={'r':'*r'}).astype({'t':int}).round(3).to_csv(
    os.path.join(inputs_case,'trancap_fut.csv'), index=False)


#%%### Transmission upgrade supply curve
transmission_cost_ac = pd.read_csv(
    os.path.join(inputs_case, 'transmission_cost_ac.csv')
)
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

labels = {
    'binwidth_USD2004': 'binwidth',
    'USD2004perMW_forward': 'forward',
    'USD2004perMW_reverse': 'reverse',
}
for col, label in labels.items():
    transmission_cost_ac[['r','rr','tscbin',col]].rename(columns={'r':'*r'}).round(2).to_csv(
        os.path.join(inputs_case, f'tsc_{label}.csv'),
        index=False,
    )
reeds.io.write_to_inputs_h5(
    df=transmission_cost_ac.tscbin.drop_duplicates().rename(),
    key='tscbin',
    case=inputs_case,
    gamstype='set',
    comment='transmission upgrade supply curve bins',
)


#%% DC and B2B transmission cost
## Get DC line cost
transmission_cost_dc = pd.read_csv(os.path.join(inputs_case, 'transmission_cost_dc.csv'))

## B2B is: (zone center)--------(AC/DC converter)(DC/AC converter)--------(zone center)
##                         ^ AC line                                 ^ AC line
## so use AC per-mile costs.
b2b_links = trancap_init['energy'].loc[
    (trancap_init['energy'].trtype=='B2B')
    & (trancap_init['energy'].r < trancap_init['energy'].rr)
].set_index(['r','rr']).index
## Take the weighted average of the whole supply curve (for the default 500 kV assumption
## the supply curve only has one bin per interface, so it doesn't matter; when we add the
## full supply curve, we'll need to include entries for these B2B-containing interfaces).
df = transmission_cost_ac.set_index(['r','rr']).loc[b2b_links].copy()
df['cost_weighted'] = (
    df.binwidth_USD2004
    * df.USD2004perMW_forward
)
transmission_cost_b2b = (
    df.groupby(['r','rr','tscbin']).cost_weighted.sum()
    / df.groupby(['r','rr','tscbin']).binwidth_USD2004.sum()
).reset_index(level='tscbin', drop=True).rename('USD2004perMW').reset_index()
## Add the reverse direction and write it
transmission_cost_b2b = pd.concat([
    transmission_cost_b2b,
    transmission_cost_b2b.rename(columns={'r':'rr', 'rr':'r'})
])

### Write the combined cost table
transmission_cost_nonac = (
    pd.concat({
        'LCC': transmission_cost_dc,
        'B2B': transmission_cost_b2b,
        'VSC': transmission_cost_dc,
    }, names=('trtype','drop'))
    .reset_index('drop', drop=True)
    .reset_index()
    .rename(columns={'r':'*r'})
    [['*r','rr','trtype','USD2004perMW']]
)
transmission_cost_nonac.round(2).to_csv(
    os.path.join(inputs_case, 'transmission_cost_nonac.csv'),
    index=False,
)


#%%### Hurdle rates
hurdle_levels = [1, 2]
cost_hurdle_intra = (
    pd.read_csv(os.path.join(inputs_case, 'cost_hurdle_intra.csv'))
    .rename(columns={'t':'*t'}).set_index('*t').round(3)
)
cost_hurdle_rate = {
    i: (
        cost_hurdle_intra[sw[f'GSw_TransHurdleLevel{i}']] if int(sw.GSw_TransHurdleRate)
        else pd.Series(name='region').rename_axis('*t')
    )
    for i in hurdle_levels
}
for i in hurdle_levels:
    cost_hurdle_rate[i].to_csv(os.path.join(inputs_case, f'cost_hurdle_rate{i}.csv'))


#%%### POI / network-reinforcement cost supply curve
# Write the model-facing inputs_case/poi_supply_curve.csv in long format
# (*poigroup, r, rtscbin, sc_cat in {cost ($/kW), cap (MW)}, value), plus rtscbin.csv (the bin
# label set, used to size the GAMS rtscbin set when numpoibins=0). b_inputs.gms converts cost
# $/kW -> $/MW (*1000) and charges each POI group on its own curve via eq_POI_cap(poigroup,r,t).
#
# POI_cost_type = 'regional' (default): one zonal curve for all techs (poigroup='all'). numpoibins=1
#   (or POI_validate) -> flat GSw_TransIntraCost. Otherwise the zonal bins are built from the raw
#   cumulative interconnection curve (inputs/transmission/raw_interconnection_TSC_data.csv) via
#   make_poi_supply_curve.make_regional_poi_bins: numpoibins=0 -> native (one bin per raw segment),
#   numpoibins>1 -> re-binned to numpoibins; both append the unlimited GSw_POIUpperCost backstop
#   bin_upper. If the raw file is absent it falls back to the copied per-zone-set poi_supply_curve.csv.
# POI_cost_type = 'techspecific': wind (wind-ons) and PV (upv) each get their OWN per-region
#   reinforcement curve from the reV supply-curve cost_reinforcement_usd_per_mw (deflated to
#   USD2004); 'other' (all non-VRE techs) gets the flat GSw_TransIntraCost floor. numpoibins=0 ->
#   full reV resolution; numpoibins>0 -> sampled to numpoibins unique-width bins minimizing the
#   native-vs-binned difference (optimal capacity-weighted least-squares segmentation).
numpoibins = int(sw.numpoibins)
poicosttype = str(sw.get('POI_cost_type', 'regional'))
## POI_validate (binning-sweep mode) routes numpoibins to the embedded VRE reinforcement
## (handled in writesupplycurves.coarsen_reinforcement), so here the zonal POI is forced to the
## flat GSw_TransIntraCost layer and held fixed across the sweep.
poi_validate = int(sw.get('POI_validate', 0) or 0)

if poicosttype == 'techspecific' and not poi_validate:
    def _segment_curve(costs, caps, nbins, maxpts=400):
        """Return [(cap_mw, cost_usd_per_mw), ...] bins for one region/tech curve.
        nbins<=0 -> full native (distinct cost levels). nbins>0 -> optimal capacity-weighted L2
        piecewise-constant segmentation (bin widths minimize the native-vs-binned difference)."""
        df = (pd.DataFrame({'cost': costs, 'cap': caps})
              .groupby('cost', as_index=False)['cap'].sum().sort_values('cost').reset_index(drop=True))
        x = df['cost'].to_numpy(float); w = df['cap'].to_numpy(float); n = len(x)
        if (nbins <= 0) or (nbins >= n):
            return list(zip(w, x))
        ## Pre-aggregate to <=maxpts capacity-quantile micro-bins to bound the DP cost
        if n > maxpts:
            cum = np.cumsum(w)
            bounds = np.unique(np.concatenate(
                [[0], np.clip(np.searchsorted(cum, np.linspace(0, cum[-1], maxpts + 1)[1:-1]), 0, n - 1) + 1, [n]]))
            xs, ws = [], []
            for a, b in zip(bounds[:-1], bounds[1:]):
                sw = w[a:b].sum()
                if sw > 0:
                    ws.append(sw); xs.append((w[a:b] * x[a:b]).sum() / sw)
            x = np.array(xs); w = np.array(ws); n = len(x)
        W = np.concatenate([[0], np.cumsum(w)]); WX = np.concatenate([[0], np.cumsum(w * x)])
        WX2 = np.concatenate([[0], np.cumsum(w * x * x)])
        def sse(a, b):
            sw = W[b] - W[a]
            return 0.0 if sw <= 0 else (WX2[b] - WX2[a]) - (WX[b] - WX[a]) ** 2 / sw
        INF = float('inf'); dp = np.full((nbins + 1, n + 1), INF); cut = np.zeros((nbins + 1, n + 1), int)
        dp[0, 0] = 0.0
        for k in range(1, nbins + 1):
            for j in range(k, n + 1):
                best, ba = INF, k - 1
                for a in range(k - 1, j):
                    v = dp[k - 1, a] + sse(a, j)
                    if v < best:
                        best, ba = v, a
                dp[k, j] = best; cut[k, j] = ba
        bins = []; j = n
        for k in range(nbins, 0, -1):
            a = cut[k, j]; sw = W[j] - W[a]
            bins.append((sw, (WX[j] - WX[a]) / sw)); j = a
        return list(reversed(bins))

    def _interconnection_deflator():
        """Multiplier converting reV interconnection costs to USD2004 (the GSw_TransIntraCost basis)."""
        try:
            import h5py
            with h5py.File(os.path.join(
                    reeds_path, 'inputs', 'supply_curve', 'interconnection_land.h5'), 'r') as f:
                revyear = int(f['data'].attrs['dollaryear'])
            defl = pd.read_csv(
                os.path.join(reeds_path, 'inputs', 'financials', 'deflator.csv'),
                header=0, names=['Dollar.Year', 'Deflator'], index_col='Dollar.Year')['Deflator']
            return float(defl.loc[revyear])
        except Exception as e:
            print(f'WARNING: could not compute reV->USD2004 deflator ({e}); using 1.0')
            return 1.0

    def _binned_reinforcement(scfile, poigroup, nbins, deflator):
        sc = pd.read_csv(scfile)
        ## The binned-POI method zeroes cost_reinforcement_usd_per_mw in the supply curve (so it
        ## is not charged on INV_RSC) and relocates it to the zonal INV_POI curve we build here.
        ## Read the preserved native reinforcement so the relocation actually carries the cost;
        ## fall back to the live column if the native one is absent (e.g. reinforcement not dropped).
        reinfcol = (
            'cost_reinforcement_usd_per_mw_native'
            if 'cost_reinforcement_usd_per_mw_native' in sc.columns
            else 'cost_reinforcement_usd_per_mw'
        )
        sc = sc[['region', 'capacity', reinfcol]].dropna()
        sc = sc.loc[sc['capacity'] > 0]
        rows = []
        for r, g in sc.groupby('region'):
            if g['capacity'].sum() <= 0:
                continue
            curve = _segment_curve(g[reinfcol].values, g['capacity'].values, nbins)
            for k, (cap_mw, cost_mw) in enumerate(curve, start=1):
                ## reV $/MW -> USD2004 $/kW
                rows.append([poigroup, r, f'bin{k}', round(cost_mw * deflator / 1e3, 2), round(cap_mw, 1)])
        return pd.DataFrame(rows, columns=['poigroup', 'r', 'rtscbin', 'cost_usd_per_kw', 'cap_mw'])

    deflator = _interconnection_deflator()
    parts = []
    for poigroup, fname in {'wind': 'supplycurve_wind-ons.csv', 'pv': 'supplycurve_upv.csv'}.items():
        fpath = os.path.join(inputs_case, fname)
        if os.path.exists(fpath):
            parts.append(_binned_reinforcement(fpath, poigroup, numpoibins, deflator))
    bytech = (pd.concat(parts, ignore_index=True) if parts
              else pd.DataFrame(columns=['poigroup', 'r', 'rtscbin', 'cost_usd_per_kw', 'cap_mw']))
    ## 'other' group (all non-wind/non-PV techs): flat GSw_TransIntraCost (USD2004/kW), unlimited
    ## (single bin1, no cap). Defined for every model region.
    other = pd.DataFrame({
        'poigroup': 'other', 'r': valid_regions['r'], 'rtscbin': 'bin1',
        'cost_usd_per_kw': float(sw.GSw_TransIntraCost), 'cap_mw': np.nan,
    })
    bytech = pd.concat([bytech, other], ignore_index=True)
    bytech.to_csv(os.path.join(inputs_case, 'poi_supply_curve_bytech.csv'), index=False)
    ## Melt to long format (cost rows always; cap rows where a finite width is defined)
    cost_rows = (bytech[['poigroup', 'r', 'rtscbin', 'cost_usd_per_kw']]
                 .rename(columns={'cost_usd_per_kw': 'value'}).assign(sc_cat='cost'))
    cap_rows = (bytech.loc[bytech['cap_mw'].notna(), ['poigroup', 'r', 'rtscbin', 'cap_mw']]
                .rename(columns={'cap_mw': 'value'}).assign(sc_cat='cap'))
    poi_model = pd.concat([cost_rows, cap_rows], ignore_index=True)[
        ['poigroup', 'r', 'rtscbin', 'sc_cat', 'value']]
else:
    if (numpoibins == 1) or poi_validate:
        ## Flat legacy POI: a single unlimited bin1 at GSw_TransIntraCost for every model region
        ## (b_inputs.gms also defaults any region the file omits to this same flat cost).
        reg = pd.DataFrame({
            'r': valid_regions['r'], 'rtscbin': 'bin1', 'sc_cat': 'cost',
            'value': float(sw.GSw_TransIntraCost)})
    else:
        ## Build the zonal curve from the raw cumulative interconnection data, re-binned to
        ## numpoibins (numpoibins=0 -> native: one bin per raw segment), cost capped at
        ## GSw_POIUpperCost. See inputs/transmission/make_poi_supply_curve.py.
        raw_poi = os.path.join(
            reeds_path, 'inputs', 'transmission', 'raw_interconnection_TSC_data.csv')
        if os.path.exists(raw_poi):
            import importlib.util
            _spec = importlib.util.spec_from_file_location(
                'make_poi_supply_curve',
                os.path.join(reeds_path, 'inputs', 'transmission', 'make_poi_supply_curve.py'))
            _poigen = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_poigen)
            reg = (
                _poigen.make_regional_poi_bins(
                    raw_poi, numpoibins=numpoibins, upper_cost=float(sw.GSw_POIUpperCost))
                .rename(columns={'*r': 'r'}))
            reg = reg.loc[reg['r'].isin(valid_regions['r'])].copy()
        else:
            ## Fall back to the committed per-zone-set poi_supply_curve.csv (copied to inputs_case).
            ## numpoibins=0 keeps all of its bins; numpoibins>1 keeps bin1..binN.
            reg = pd.read_csv(os.path.join(inputs_case, 'poi_supply_curve.csv'))
            reg = reg.rename(columns={reg.columns[0]: 'r'})
            if numpoibins > 1:
                keep_bins = [f'bin{n}' for n in range(1, numpoibins + 1)]
                reg = reg.loc[reg['rtscbin'].isin(keep_bins)].copy()
        ## GSw_POIUpperCost: unlimited backstop bin (cost row only, no cap) so reinforcement above
        ## the finite binned capacities stays feasible at a high price.
        reg = pd.concat([reg, pd.DataFrame({
            'r': reg['r'].unique(), 'rtscbin': 'bin_upper', 'sc_cat': 'cost',
            'value': float(sw.GSw_POIUpperCost)})], ignore_index=True)
    poi_model = reg.assign(poigroup='all')[['poigroup', 'r', 'rtscbin', 'sc_cat', 'value']]

## Write the model-facing curve (leading '*' so GAMS treats the header row as a comment)
poi_model.rename(columns={'poigroup': '*poigroup'}).to_csv(
    os.path.join(inputs_case, 'poi_supply_curve.csv'), index=False)

## Write the rtscbin label set (bin1..binN in order, bin_upper last) for GAMS set sizing
def _binkey(b):
    return (1, 0) if b == 'bin_upper' else (0, int(str(b).replace('bin', '')))
rtscbins = sorted(poi_model['rtscbin'].unique(), key=_binkey)
pd.Series(rtscbins).to_csv(os.path.join(inputs_case, 'rtscbin.csv'), index=False, header=False)


#%%### H2 pipeline cost multipliers
# Calculate H2 pipeline cost multipliers by dividing the [$/mile] cost of DC transmission
# between each pair of regions by the minimum interface [$/mile] cost for DC transmission
# and subtracting 1 to get a fractional adder (which is then added to 1 in b_inputs.gms)
fpath = os.path.join(inputs_case, 'pipeline_cost_mult.csv')
if len(transmission_cost_nonac):
    dc_cost_permile = (
        transmission_cost_nonac.rename(columns={'*r':'r'})
        .set_index(['trtype','r','rr']).loc['LCC'].squeeze(1)
        / interface_params.xs('LCC', 0, 'trtype').miles
    )
    pipeline_cost_mult = dc_cost_permile.rename('multiplier') / dc_cost_permile.min() - 1

    pipeline_cost_mult.reset_index().rename(columns={'r':'*r'}).round(3).to_csv(
        fpath,
        index=False,
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
