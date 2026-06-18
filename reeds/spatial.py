import os
import sys
import pandas as pd
import geopandas as gpd
from pathlib import Path
from typing import Literal
sys.path.append(str(Path(__file__).parent.parent))
import reeds


def get_agglevel_variables(reeds_path, inputs_case):
    '''
    This function produces a dictionary with an assortment of variables that are necessary for
    mixed resolution runs.

    ReEDS supports multiple agglevels
    The 'lvl' variable is set to 'mult' for instances where county is included as a desired resolution.
    This ensures that both BA and county data are copied to the inputs_case folder
    The 'lvl' variable also ensures that BA and larger spatial aggregations use BA data and procedure

    ###### variables output by function:   #######
    lvl - indicator if one of the desired resolutions in a mixed resolution run is county or not
    agglevel - single or multiple values to indicate resolution(s)
    ba_regions - list of regions in a mixed resolution run that use BA resolution data
    county_regions - list of regions in a mixed resolution run that use county resolution data
    county_regions2ba - map county resolution regions to their BA
    BA_county_list - list of counties that belong to regions being solved at BA
    BA_2_county - map counties that belong to BA resolution regions back to their BA
    ba_transgrp - list of transgroups associated with regions being solved at ba resolution
    county_transgrp - list of transgroups associated with regions being solved at ba resolution

    '''

    agglevel = pd.read_csv(os.path.join(inputs_case, 'agglevels.csv'))

    if len(agglevel) > 1:
        agglevel = agglevel.squeeze().tolist()
    else:
        agglevel = agglevel.squeeze().split()

    # Compile lists of regions in the run to be considered at ba level
    hierarchy = pd.read_csv(
        os.path.join(inputs_case, 'hierarchy_with_res.csv'), usecols=['*r', 'resolution']
    )
    hierarchy_org = pd.read_csv(os.path.join(inputs_case, 'hierarchy_original.csv'))
    rb_aggreg = pd.read_csv(os.path.join(inputs_case, 'rb_aggreg.csv'))
    ba_regions = hierarchy[hierarchy['resolution'] == 'ba']['*r'].to_list()
    aggreg_regions = hierarchy[hierarchy['resolution'] == 'aggreg']['*r'].to_list()
    aggreg_regions2ba = hierarchy_org[hierarchy_org['aggreg'].isin(aggreg_regions)]['ba'].to_list()
    ba_regions = list(set(ba_regions + aggreg_regions + aggreg_regions2ba))
    transgrp_regions_ba = list(set(hierarchy_org[hierarchy_org['ba'].isin(ba_regions)]['transgrp']))

    ### Procedure for handling mixed-resolution ReEDS runs
    if len(agglevel) > 1:
        if 'county' in agglevel:
            lvl = 'mult'
        else:
            lvl = 'ba'

        # Create dictionaries which map county resolution regions to their BAs and which map
        # the counties of BA resolution regions to their BA
        # These lists/dictionaries are necessary to filter county and BA resolution data correctly

        if 'county' in agglevel:
            county_regions = hierarchy[hierarchy['resolution'] == 'county']['*r'].to_list()
            r_ba = pd.read_csv(os.path.join(inputs_case, 'r_ba.csv'))
            r_ba_dict = r_ba.set_index('r')['ba'].to_dict()
            # List of BAs associated with county resolution regions
            county_regions2ba = pd.DataFrame(county_regions)[0].map(r_ba_dict).unique().tolist()
            # Need list of transgrps associated with regions being solved at county resolution
            transgrp_regions_county = list(
                set(hierarchy_org[hierarchy_org['ba'].isin(county_regions2ba)]['transgrp'])
            )
            # Need county2zone
            ## TEMPORARY 20260402
            county2zone = reeds.io.get_county2zone(GSw_ZoneSet='z134', as_map=False)
            # Need to create mapping between aggreg and county
            if 'aggreg' in agglevel:
                county2zone = county2zone[county2zone['r'].isin(rb_aggreg['ba'])]
                county2zone['ba'] = county2zone['r'].map(
                    rb_aggreg.set_index('ba')['aggreg'].to_dict()
                )
                # Add BAs associated with aggreg regions to ba_regions list
                aggreg_regions_2_ba = [
                    x
                    for x in rb_aggreg['ba']
                    if x not in aggreg_regions and x not in county_regions2ba
                ]
                ba_regions = list(set(ba_regions + aggreg_regions_2_ba))
            # Create list of counties that belong to regions being solved at BA
            BA_county_list = county2zone[county2zone['r'].isin(ba_regions)].copy()
            BA_county_list.loc[:,'FIPS'] = 'p' + BA_county_list['FIPS'].astype(str)
            # Map these counties to their BA
            BA_2_county = BA_county_list.set_index('FIPS')['r'].to_dict()
            BA_county_list = BA_county_list['FIPS'].tolist()

    ### Procedure for handling single-resolution ReEDS runs
    else:
        agglevel = agglevel[0]
        lvl = 'ba' if agglevel in ['ba', 'aggreg'] else 'county'

        if lvl == 'county':
            county_regions = hierarchy[hierarchy['resolution'] == 'county']['*r'].to_list()
            r_ba = pd.read_csv(os.path.join(inputs_case, 'r_ba.csv'))
            r_ba_dict = r_ba.set_index('r')['ba'].to_dict()
            # List of BAs associated with county resolution regions
            county_regions2ba = pd.DataFrame(county_regions)[0].map(r_ba_dict).unique().tolist()
            transgrp_regions_county = list(
                set(hierarchy_org[hierarchy_org['ba'].isin(county_regions2ba)]['transgrp'])
            )

        else:
            county_regions = []
            county_regions2ba = []
            transgrp_regions_county = []

        BA_county_list = []
        BA_2_county = []

    return {
        'lvl': lvl,
        'agglevel': agglevel,
        'ba_regions': ba_regions,
        'county_regions': county_regions,
        'county_regions2ba': county_regions2ba,
        'BA_county_list': BA_county_list,
        'BA_2_county': BA_2_county,
        'ba_transgrp': transgrp_regions_ba,
        'county_transgrp': transgrp_regions_county,
    }


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
    dfout.loc[index2offshorezone.index, 'reeds_ba'] = index2offshorezone.values

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
            right_on=['PCA_REG', 'i']
        )
    else:
        df = df.merge(
            disagg_data[['PCA_REG', 'FIPS', 'fracdata']],
            left_on=region_col,
            right_on='PCA_REG'
        )

    # Replace legacy zones in region_col with the county FIPS codes
    df = (
        df.drop(columns=[region_col, 'PCA_REG'])
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