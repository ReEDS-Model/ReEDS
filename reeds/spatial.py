import os
import sys
import pandas as pd
import geopandas as gpd
from pathlib import Path
from typing import Literal
sys.path.append(str(Path(__file__).parent.parent))
import reeds


def assign_to_offshore_zones(unitdata):
    """Map offshore wind units to offshore zones based on lat/lon and zone outlines"""
    ### Get offshore zones
    dfzones = gpd.read_file(
        os.path.join(reeds.io.reeds_path, 'inputs', 'shapefiles', 'offshore_zones.gpkg')
    ).set_index('zone')

    dfwind = unitdata.loc[unitdata.tech=='wind-ofs'].copy()
    dfwind['latitude'] = dfwind['T_LAT'].abs()
    dfwind['longitude'] = -dfwind['T_LONG'].abs()
    dfwind = reeds.plots.df2gdf(dfwind, crs=dfzones.crs)

    ## Only keep matches within 100 km since some areas only have radial sites
    index2offshorezone = dfwind.sjoin_nearest(dfzones, max_distance=1e5)['index_right']

    dfout = unitdata.copy()
    dfout.loc[index2offshorezone.index, 'r'] = index2offshorezone.values

    return dfout


def get_map(resolution='county', source='tiger', crs='ESRI:102008'):
    """
    Download (if necessary) and read a U.S. map.

    Parent URL:
    https://www.census.gov/geographies/mapping-files/time-series/geo/carto-boundary-file.html
    or
    https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html
    """
    urls = {
        'county': (
            'https://www2.census.gov/geo/tiger/GENZ2018/shp/cb_2018_us_county_500k.zip'
            if source.lower() == 'census' else
            'https://www2.census.gov/geo/tiger/TIGER2022/COUNTY/tl_2022_us_county.zip'
        ),
        'country': 'https://www2.census.gov/geo/tiger/GENZ2018/shp/cb_2018_us_nation_5m.zip',
        'state': (
            'https://www2.census.gov/geo/tiger/GENZ2018/shp/cb_2018_us_state_500k.zip'
            if source.lower() == 'census' else
            'https://www2.census.gov/geo/tiger/TIGER2025/STATE/tl_2025_us_state.zip'
        ),
        'urban': 'https://www2.census.gov/geo/tiger/GENZ2018/shp/cb_2018_us_ua10_500k.zip',
    }
    index = {
        'state': 'STUSPS',
        'country': 'GEOID',
        'county': 'GEOID',
        'urban': 'GEOID10',
    }
    drop = {
        'state': {'STUSPS': ['AK', 'AS', 'HI', 'VI', 'PR', 'MP', 'GU']},
        'county': {'STATEFP': ['02', '60', '15', '78', '72', '69', '66']}
    }
    aliases = {
        'state': ['st', 'states'],
        'county': ['counties', 'fips'],
        'country': ['nation', 'usa', 'u.s.a.'],
        'urban': ['city', 'cities'],
    }
    for key, val in aliases.items():
        for v in val:
            urls[v] = urls[key]
            if key in index:
                index[v] = index[key]
            if key in drop:
                drop[v] = drop[key]

    ## Parse and load it
    url = urls[resolution.lower()]
    cachepath = Path(reeds.io.reeds_path, 'inputs', 'shapefiles', 'cache')
    cachepath.mkdir(exist_ok=True, parents=True)
    fpath = Path(cachepath, Path(url).stem)
    try:
        df = gpd.read_file(fpath)
    except Exception:
        reeds.remote.download(url, fpath, unzip=True)
        df = gpd.read_file(fpath)
    df = df.to_crs(crs)
    ## Downselect if necessary
    for key, val in drop.get(resolution, {}).items():
        df = df.loc[~df[key].isin(val)].copy()
    if resolution in index:
        df = df.set_index(index[resolution]).copy()

    return df


def apply_uniform_disaggregation(
    df: pd.DataFrame,
    region_col: str
):
    """
    Disaggregate a dataframe whose regional scope is the 134 legacy
    zones (as specified in the dataframe's 'region_col' column) to
    the county level by copying the zonal values to their constituent counties.
    """
    county2zone = reeds.io.get_county2zone(GSw_ZoneSet='z134', as_map=False)
    county2zone['FIPS'] = 'p' + county2zone.FIPS
    df = (
        df
        .merge(county2zone[['r', 'FIPS']], left_on=region_col, right_on='r')
        .drop(columns=[region_col, 'r'])
        .rename(columns={'FIPS': region_col})
        [df.columns]
    )

    return df


def apply_variable_disaggregation(
    df: pd.DataFrame,
    region_col: str,
    fix_cols: list[str],
    inputs_case: str,
    disagg_variable: Literal['hydroexist', 'geosize', 'population', 'state_lpf']
):
    """
    Disaggregate a dataframe whose regional scope is the 134 legacy zones
    (as specified in the dataframe's 'region_col' column) to the county level
    by allocating zonal values to their corresponding counties according to
    each county's share of 'disagg_variable'.

    The county shares of 'disagg_variable' are read from the provided
    'inputs_case' folder. The 'fix_cols' argument lists columns that
    should be considered part of the dataframe's index.
    """
    # Save the dataframe's original columns
    # (used later to put the output in the correct format)
    original_columns = df.columns

    # Get legacy zone-to-county allocation factors for disagg_variable
    disagg_data = reeds.io.get_disagg_data(
        os.path.dirname(inputs_case),
        disagg_variable
    )

    # Append the allocation factors to the dataframe
    if disagg_variable == 'hydroexist':
        df = df.merge(
            disagg_data,
            left_on=[region_col, 'i'],
            right_on=['legacy_ba', 'i']
        )
    else:
        df = df.merge(
            disagg_data[['legacy_ba', 'FIPS', 'fracdata']],
            left_on=region_col,
            right_on='legacy_ba'
        )

    # Replace legacy zones in region_col with the county FIPS codes
    df = (
        df.drop(columns=[region_col, 'legacy_ba'])
        .rename(columns={'FIPS': region_col})
    )

    # If the dataframe values are 'wide', set the dataframe index
    # and then multiply all values by their allocation factor.
    # Otherwise, multiply the 'value' and allocation factor columns.
    if 'wide' in fix_cols:
        index_cols = (
            [col for col in fix_cols if col in original_columns]
            + [region_col]
        )
        df = df.set_index(index_cols)
        df = (
            df.mul(df['fracdata'], axis='index')
            .reset_index()
            [original_columns]
        )
    else:
        df = (
            df.assign(value=lambda x: x['value'] * x['fracdata'])
            [original_columns]
        )

    return df


def apply_supply_curve_disaggregation(
    df: pd.DataFrame,
    region_col: str,
    fix_cols: list[str],
    inputs_case: str,
    disagg_variable: Literal['hydroexist', 'geosize', 'population', 'state_lpf']
):
    """
    Disaggregate a supply curve dataframe whose regional scope is the 134
    legacy zones (as specified in the dataframe's 'region_col' column) to
    the county level by allocating zonal capacities to their corresponding
    counties according to each county's share of 'disagg_variable' and
    assigning zonal costs to counties uniformly.

    The county shares of 'disagg_variable' are read from the provided
    'inputs_case' folder. The 'fix_cols' argument lists columns that
    should be considered part of the dataframe's index.
    """
    # Disaggregate zonal capacities to counties according to disagg_variable
    df_cap = df.loc[df['sc_cat'] == 'cap'].drop(columns='sc_cat')
    df_cap = apply_variable_disaggregation(
        df_cap,
        region_col,
        fix_cols,
        inputs_case,
        disagg_variable
    )

    # Disaggregate zonal costs to counties uniformly
    df_cost = df.loc[df['sc_cat'] == 'cost'].drop(columns='sc_cat')
    df_cost = apply_uniform_disaggregation(df_cost, region_col)

    # Combine capacities and costs and return to original format
    df = (
        pd.concat(
            [df_cap.assign(sc_cat='cap'), df_cost.assign(sc_cat='cost')],
            ignore_index=True
        )
        [df.columns]
    )

    return df


def downscale_from_legacy_zone_to_county(
    df: pd.DataFrame,
    region_col: str,
    fix_cols: list[str],
    inputs_case: str,
    disaggfunc: str
):
    """
    Disaggregate a dataframe whose regional scope is the 134 legacy zones
    (as specified in the dataframe's 'region_col' column) to the county level
    according to the specified disaggregation function ('disaggfunc').

    If 'disaggfunc' is a variable by which zonal values are allocated to
    counties (e.g., population), county shares of the variable are read from
    the provided 'inputs_case' folder. The 'fix_cols' argument lists columns
    that should be considered part of the dataframe's index.
    """
    # If 'region_col' is 'wide' (zones are contained in the column headers
    # rather than one of the columns), temporarily reformat the dataframe
    # to 'long' format, specifying zones in a new 'r' column
    if region_col == 'wide':
        df = pd.melt(df, id_vars=fix_cols, var_name='r')
        region_col = 'r'
        # Indicate that the dataframe should be reformatted
        # to its original (wide) format after disaggregation
        reformat_to_wide = True
    else:
        reformat_to_wide = False

    # Apply disaggregation according to 'disaggfunc'
    match disaggfunc:
        case 'uniform':
            df = apply_uniform_disaggregation(df, region_col)
        case 'geosize' | 'hydroexist' | 'population' | 'state_lpf':
            if 'sc_cat' in df.columns:
                df = apply_supply_curve_disaggregation(
                    df,
                    region_col,
                    fix_cols,
                    inputs_case,
                    disaggfunc
                )
            else:
                df = apply_variable_disaggregation(
                    df,
                    region_col,
                    fix_cols,
                    inputs_case,
                    disaggfunc
                )
        case 'ignore':
            pass
        case _:
            raise NotImplementedError(
                f"Disaggfunc '{disaggfunc}' has not been implemented."
            )

    # If applicable, restore original (wide) format
    if reformat_to_wide:        
        df = (
            pd.pivot_table(df, values='value', index=fix_cols, columns=['r'])
            .reset_index()
            .rename_axis('', axis=1)
        )

    return df


def apply_supply_curve_aggregation(
    df: pd.DataFrame,
    region_col: str,
    groupby_cols: list[str],
    county_r_map: dict[str, str],
):
    """
    Aggregate a supply curve dataframe with county-level regional scope
    (as specified in the dataframe's 'region_col' column) to the zone level
    (using zones corresponding to 'county_r_map') by combining capacities
    via sum and combining costs via capacity-weighted average. The
    'groupby_cols' argument lists columns that should be grouped before
    aggregation.
    """
    # Save the dataframe's original columns
    # (used later to put the output in the correct format)
    original_columns = df.columns

    # Reformat dataframe so that capacities and costs are listed
    # side-by-side for each group (based on 'groupby_cols')
    df_cap = (
        df.loc[df.sc_cat == 'cap']
        .drop(columns='sc_cat')
        .set_index(groupby_cols)
        ['value']
        .rename('cap')
    )
    df_cost = (
        df.loc[df.sc_cat == 'cost']
        .drop(columns='sc_cat')
        .set_index(groupby_cols)
        ['value']
        .rename('cost')
    )
    df = (
        pd.concat([df_cap, df_cost], axis=1)
        .reset_index()
    )

    # Calculate products of weights (capacities) and costs, which will be
    # used to calculate capacity-weighted costs. Where capacities are
    # null or 0, we use 1 MW as the weight.
    df['cap_weight'] = df['cap'].fillna(1).replace(0, 1)
    df['cap_weight_times_cost'] = df['cap_weight'] * df['cost']

    # Map counties to zones
    df[region_col] = df[region_col].map(county_r_map)

    # Calculate capacity/cost/weight totals for each group
    # and then divide total weight*cost by total weight to derive
    # capacity-weighted cost for each group.
    df = (
        df.groupby(groupby_cols)
        .sum()
        .assign(cost=lambda x: x['cap_weight_times_cost'] / x['cap_weight'])
        .reset_index()
        .drop(columns=['cap_weight', 'cap_weight_times_cost'])
    )

    # Restore original format
    df = pd.melt(
        df,
        id_vars=groupby_cols,
        value_vars=['cap', 'cost'],
        var_name='sc_cat'
    )
    df = df[original_columns]

    return df


def upscale_from_county_to_zone(
    df: pd.DataFrame,
    region_col: str,
    fix_cols: list[str],
    inputs_case: str,
    aggfunc: str
):
    """
    Aggregate a dataframe with county-level regional scope (as specified in
    the dataframe's 'region_col' column) to the zone level (using zones
    corresponding to 'inputs_case') according to the specified aggregation
    function ('aggfunc'). The 'fix_cols' argument lists columns that should
    be considered part of the dataframe's index.
    """
    # If 'region_col' is 'r_cendiv', counties are stored in the 'r' column
    # and dataframe values are stored in columns whose headers are cendivs,
    # so for this function, 'r' can be treated as the region column.
    if region_col == 'r_cendiv':
        region_col = 'r'
    
    # If 'region_col' is 'wide' (zones are contained in the column headers
    # rather than one of the columns), temporarily reformat the dataframe
    # to 'long' format, specifying zones in a new 'r' column
    if region_col == 'wide':
        df = pd.melt(df, id_vars=fix_cols, var_name='r')
        region_col = 'r'
        # Indicate that the dataframe should be reformatted
        # to its original (wide) format after aggregation
        reformat_to_wide = True
    else:
        reformat_to_wide = False

    # Identify columns that should be grouped before aggregation
    groupby_cols = (
        [col for col in fix_cols if col in df.columns]
        + [region_col]
    )

    # Get county-to-zone map
    county_r_map = reeds.io.get_county2zone(os.path.dirname(inputs_case))
    county_r_map.index = 'p' + county_r_map.index.str.zfill(5)

    # Apply aggregation according to 'aggfunc'
    match aggfunc:
        case 'sc_cat':
            df = apply_supply_curve_aggregation(
                df,
                region_col,
                groupby_cols,
                county_r_map
            )
        case 'sum' | 'mean':
            df[region_col] = df[region_col].map(county_r_map)
            df = (
                df.groupby(groupby_cols, as_index=False)
                .agg(aggfunc)
                [df.columns]
            )
        case 'ignore':
            pass
        case _:
            raise NotImplementedError(
                f"Aggfunc '{aggfunc}' has not been implemented."
            )


    # If applicable, restore original (wide) format
    if reformat_to_wide:
        df = (
            pd.pivot_table(df, values='value', index=fix_cols, columns=['r'])
            .reset_index()
            .rename_axis('', axis=1)
        )

    return df


def calculate_region_aggregion_population_weights(
    inputs_case: str | Path,
    region_level: str,
    aggregion_level: str,
) -> pd.Series:
    """
    For a given region level and aggregated region (aggregion)
    level, calculate each region's share of its corresponding
    aggregion's total population.
    
    Args:
        inputs_case: Path to the inputs case directory.
        region_level: Region level (example: 'state')
        aggregion_level: Aggregated region level
            (example: 'cendiv')

    Returns:
        pd.Series
    """
    # Get county populations
    county_populations = reeds.inputs.get_county_populations()
    county_populations = county_populations.rename(
        columns={'value': 'population'}
    )

    # Get county-to-region mapping
    county2zone = reeds.io.get_county2zone(
        os.path.dirname(inputs_case),
        as_map=False
    )
    county2zone['FIPS'] = (
        'p' + county2zone['FIPS'].astype(str).str.zfill(5)
    )
    state_groups = reeds.inputs.get_state_groups()
    county2zone = county2zone.merge(
        state_groups,
        left_on='state',
        right_on='st'
    )
    county_region_map = county2zone.set_index('FIPS')[region_level]

    # Calculate regional populations
    county_populations[region_level] = (
        county_populations['FIPS'].map(county_region_map)
    )
    region_populations = (
        county_populations.groupby(region_level, as_index=False)
        ['population']
        .sum()
    )

    # Calculate each region's percentage of aggregion population
    region2aggregion = dict(zip(
        county2zone[region_level],
        county2zone[aggregion_level]
    ))
    region_populations[aggregion_level] = (
        region_populations[region_level].map(region2aggregion)
    )
    region_populations['weight'] = (
        region_populations['population']
        / (
            region_populations.groupby(aggregion_level)
            ['population']
            .transform('sum')
        )
    )
    region_aggregion_weights = (
        region_populations.set_index(region_level)['weight']
    )

    return region_aggregion_weights


def aggregate_by_weighted_average(
    regional_data: pd.DataFrame,
    region_aggregion_weights: pd.Series,
    region2aggregion: dict[str, str]
) -> pd.DataFrame:
    """
    Aggregate region-level data to the aggregated region
    ("aggregion") level via weighted average.

    Args:
        regional_data: Region-level data.
        region_aggregion_weights: The "weight" of each region
            corresponding to its aggregion to use in weighted
            average calculation.
        region2aggregion: Mapping between regions and aggregions.

    Returns:
        pd.DataFrame
    """
    aggregional_data = (
        regional_data.mul(region_aggregion_weights)
        .transpose()
        .rename(region2aggregion)
        .groupby(level=0)
        .sum()
        .transpose()
    )
    return aggregional_data
