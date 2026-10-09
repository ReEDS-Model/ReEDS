'''
This script handles the modification of load data. Specifically, it converts
state-level hourly end-use load to model region-level busbar load by doing
the following:

- Allocate state load to model regions according to the method specified
    in GSw_LoadAllocationMethod
- Apply scenario-specific modifications:
    EER scenarios:
    - Append historical load for pre-2021 model years
    - Interpolate projected load for missing model years
    - Apply calibration factors to projected load based on the difference
        between historical and projected load in the latest year for which
        historical and projected load data exist
    Historical:
    - Apply annual load growth factors
    Other:
    - If needed, replicate the dataset to match the number of weather years
        specified for this run
- Apply a distribution loss factor

The script also calculates peak load for each region level.
'''

#%% ===========================================================================
### --- IMPORTS ---
### ===========================================================================

import argparse
import datetime
import numpy as np
import os
import pandas as pd
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
import reeds


#%% ===========================================================================
### --- FUNCTIONS ---
### ===========================================================================

def get_historical_state_load_for_model_year(
    historical_state_load_annual: pd.DataFrame,
    model_year: int
) -> pd.Series:
    """
    Get historical annual state loads in MWh for the model year.
    
    Args:
        historical_state_load_annual: Annual historical state loads in MWh.
        model_year: Year to retrieve load values for.

    Returns:
        pd.Series
    """
    return (
        historical_state_load_annual
        .loc[historical_state_load_annual.year == model_year]
        .set_index('st')
        ['MWh']
    )

def scale_historical_hourly_state_load_to_model_year(
    historical_state_load_hourly: pd.DataFrame,
    historical_state_load_annual: pd.DataFrame,
    model_year: int
) -> pd.DataFrame:
    """
    Scale historical hourly state load profiles to match historical
    annual totals for the specified model year.
    
    Args:
        historical_state_load_hourly: Hourly historical state load profiles
            in MWh.
        historical_state_load_annual: Annual historical state loads in MWh.
        model_year: Year of annual load to scale hourly load by.

    Returns:
        pd.DataFrame
    """
    historical_model_year_state_load = get_historical_state_load_for_model_year(
        historical_state_load_annual,
        model_year
    )
    # Calculate total state loads for each weather year
    # of the historical hourly state load profiles
    historical_weather_year_state_loads = (
        historical_state_load_hourly.groupby(
            historical_state_load_hourly.index.get_level_values('datetime').year
        )
        .transform('sum')
    )
    # Scale the historical hourly state load profiles so that total state
    # loads for each weather year match state loads for the model year
    historical_state_load_hourly_scaled = (
        historical_state_load_hourly
        / historical_weather_year_state_loads
        * historical_model_year_state_load
    )

    return historical_state_load_hourly_scaled

def interpolate_missing_model_years(
    load_hourly: pd.DataFrame,
    endyear: int
) -> pd.DataFrame:
    """
    Linearly interpolate hourly load values for missing model years between
    the first year of the load profiles and the specified end year.
    
    Args:
        load_hourly: Hourly load profiles.
        endyear: Final model year of resulting load profiles.

    Returns:
        pd.DataFrame
    """
    model_years = [
        year for year in
        range(load_hourly.index.get_level_values('year').min(), endyear + 1)
    ]
    known_model_years = [
        year for year in
        model_years if year in load_hourly.index.get_level_values('year')
    ]

    dictload = {}
    for model_year in model_years:
        #find known years that bound this year
        for i, known_model_year in enumerate(known_model_years):
            if(known_model_year > model_year):
                section_end_model_year = known_model_year
                section_start_model_year = known_model_years[i-1]
                break
        
        #grab dataframes for linear interpolation
        df_load_beg = load_hourly.loc[section_start_model_year]
        df_load_end = load_hourly.loc[section_end_model_year]
        
        #linear interpolation:
        # y = y1 + (y2-y1)/(x2-x1)*(x-x1). x is year; y is value
        df_load = (
            df_load_beg +
            (df_load_end - df_load_beg)
            / (section_end_model_year - section_start_model_year)
            * (model_year-section_start_model_year)
        )

        dictload[model_year] = df_load

    load_hourly = pd.concat(dictload, names=('year',))

    return load_hourly

def calibrate_hourly_state_load_to_historical_annuals(
    state_load_hourly: pd.DataFrame,
    historical_state_load_annual: pd.DataFrame
) -> pd.DataFrame:
    """
    For historical model years, scale hourly state load profiles to match
    historical annual totals. For post-historical model years, scale hourly
    state load profiles to increase the projected annual totals by the
    difference between historical and projected annual totals for the
    latest historical model year.
    
    Args:
        state_load_hourly: Hourly state load profiles in MWh.
        historical_state_load_annual: Annual historical state loads in MWh.

    Returns:
        pd.DataFrame
    """
    df_list = []

    # For the model years for which we have historical annual loads, scale
    # state_load_hourly so that its annual totals match each model year's
    # historical annual loads
    min_projected_model_year = (
        state_load_hourly.index.get_level_values('year').min()
    )
    max_historical_model_year = historical_state_load_annual['year'].max()
    for model_year in range(
        min_projected_model_year,
        max_historical_model_year + 1
    ):
        model_year_historical_load = get_historical_state_load_for_model_year(
            historical_state_load_annual,
            model_year
        )
        state_load_hourly_model_year = (
            state_load_hourly
            .loc[(
                state_load_hourly.index.get_level_values('year') == model_year
            )]
            .copy()
        )
        calibration_factors = 1 / (
            state_load_hourly_model_year
            .groupby(
                state_load_hourly_model_year.index
                .get_level_values('datetime')
                .year
            )
            .transform('sum')
        ).div(model_year_historical_load)
        state_load_hourly_model_year_scaled = (
            state_load_hourly_model_year.mul(calibration_factors)
        )
        df_list.append(state_load_hourly_model_year_scaled)

    # For the latest model year for which we have historical annual loads
    # (the calibration year), calculate the differences between
    # the historical annual loads and projected annual loads
    calibration_year_historical_load = (
        get_historical_state_load_for_model_year(
            historical_state_load_annual,
            max_historical_model_year
        )
    )
    state_load_hourly_calibration_year = (
        state_load_hourly.loc[max_historical_model_year]
    )
    calibration_diffs = -(
        state_load_hourly_calibration_year
        .groupby(
            state_load_hourly_calibration_year.index
            .get_level_values('datetime')
            .year
        )
        .transform('sum')
    ).sub(calibration_year_historical_load)

    # For post-historical model years, scale state_load_hourly so that its
    # annual totals match the sum of each model year's projected annual loads
    # and the historical/projected load differences in the calibration year
    max_projected_model_year = (
        state_load_hourly.index.get_level_values('year').max()
    )
    for model_year in range(
        max_historical_model_year + 1,
        max_projected_model_year + 1
    ):
        state_load_hourly_model_year = state_load_hourly.loc[model_year]
        model_year_projected_load = (
            state_load_hourly_model_year
            .groupby(
                state_load_hourly_model_year.index
                .get_level_values('datetime')
                .year
            )
            .transform('sum')
        )
        calibration_factors = (
            model_year_projected_load.add(calibration_diffs)
            .div(model_year_projected_load)
        )
        state_load_hourly_model_year_scaled = (
            state_load_hourly_model_year
            .mul(calibration_factors)
            .assign(year=model_year)
            .set_index('year', append=True)
            .reorder_levels(['year', 'datetime'])
        )
        df_list.append(state_load_hourly_model_year_scaled)
    
    state_load_hourly = pd.concat(df_list)

    return state_load_hourly

def prepend_historical_hourly_state_load(
    state_load_hourly: pd.DataFrame,
    historical_state_load_hourly: pd.DataFrame,
    historical_state_load_annual: pd.DataFrame
) -> pd.DataFrame:
    """
    Create hourly state load profiles for historical model years and
    prepend them to state_load_hourly.
    
    Args:
        state_load_hourly: Hourly state load profiles in MWh.
        historical_state_load_hourly: Hourly historical state load profiles
            in MWh.
        historical_state_load_annual: Annual historical state loads in MWh.

    Returns:
        pd.DataFrame
    """
    historical_load_dict = {}
    
    # For historical model years with no projected load profiles, create load
    # profiles for each model year by scaling the historical load profiles to
    # match annual totals for the model year
    min_historical_model_year = historical_state_load_annual['year'].min()
    min_projected_model_year = (
        state_load_hourly.index.get_level_values('year').min()
    )
    for model_year in range(
        min_historical_model_year, min_projected_model_year
    ):
        historical_state_load_hourly_scaled = (
            scale_historical_hourly_state_load_to_model_year(
                historical_state_load_hourly,
                historical_state_load_annual,
                model_year
            )
        )
        historical_load_dict[model_year] = historical_state_load_hourly_scaled

    historical_state_load_hourly = pd.concat(
        historical_load_dict,
        names=('year',)
    )
    state_load_hourly = pd.concat([
        historical_state_load_hourly,
        state_load_hourly
    ])

    return state_load_hourly

def scale_historical_state_load_to_baseline_year(
    historical_state_load_hourly: pd.DataFrame,
    historical_state_load_annual: pd.DataFrame,
    inputs_case: str
) -> pd.DataFrame:
    """
    Scale hourly historical state load profiles to match historical annual
    totals for the load multiplier baseline year. Load growth from the
    baseline year is applied later, at model-region (BA) resolution, by
    apply_ba_load_growth().

    Args:
        historical_state_load_hourly: Hourly historical state load
            profiles in MWh.
        historical_state_load_annual: Annual state loads in MWh
            for historical years.
        inputs_case: Path to the inputs case directory.

    Returns:
        pd.DataFrame: datetime-indexed hourly state load (columns = states)
            scaled to the load multiplier baseline year.
    """
    # Read annual multipliers only to recover the baseline year
    load_multiplier = pd.read_csv(
        os.path.join(inputs_case, 'load_multiplier.csv')
    )
    load_multiplier_baseline_year = load_multiplier['year'].min()
    # Scale the historical load profiles to match annual totals
    # for the baseline year
    historical_state_load_hourly = (
        scale_historical_hourly_state_load_to_model_year(
            historical_state_load_hourly,
            historical_state_load_annual,
            load_multiplier_baseline_year
        )
    )
    return historical_state_load_hourly

def apply_ba_load_growth(
    regional_load_hourly: pd.DataFrame,
    inputs_case: str,
    hierarchy: pd.DataFrame,
    solveyears: list[int] | None = None
) -> pd.DataFrame:
    """
    Multiply baseline-year hourly model-region (BA) load profiles by annual
    load growth factors to create projected load profiles for each model
    year.

    Growth is applied at BA resolution so that multipliers which vary within
    a state (e.g. a MISO BA following a different trajectory than the rest of
    its state) are honored. For backward compatibility, a state-keyed
    load_multiplier.csv is expanded to its BAs via the hierarchy; because
    state load is allocated to BAs linearly, applying a uniform state
    multiplier to each of the state's BAs reproduces the previous
    state-level result exactly.

    Args:
        regional_load_hourly: datetime-indexed hourly BA load profiles
            (columns = model regions), scaled to the load multiplier
            baseline year.
        inputs_case: Path to the inputs case directory.
        hierarchy: Model region hierarchy (index = BA 'r', includes 'st').
        solveyears: Optional list of model years to filter load
            multipliers down to.

    Returns:
        pd.DataFrame: (year, datetime)-indexed hourly BA load profiles.
    """
    # Read annual region multipliers representing projected load growth
    # from the baseline year
    load_multiplier = pd.read_csv(
        os.path.join(inputs_case, 'load_multiplier.csv')
    )
    # Subset load multipliers for solve years only
    if solveyears is not None:
        load_multiplier = (
            load_multiplier[load_multiplier['year'].isin(solveyears)]
            [['year', 'r', 'multiplier']]
        )
    else:
        load_multiplier = load_multiplier[['year', 'r', 'multiplier']]

    # Detect whether load_multiplier is keyed by model region (BA) or by
    # state. State-keyed files are expanded to every BA in the state so that
    # growth can be applied uniformly at BA resolution (numerically identical
    # to the previous state-level application); BA-keyed files are used as-is.
    multiplier_regions = set(load_multiplier['r'].unique())
    ba_regions = set(hierarchy.index)
    state_regions = set(hierarchy['st'].unique())
    if multiplier_regions <= ba_regions:
        pass  # already keyed by model region
    elif multiplier_regions <= state_regions:
        ba_to_state = (
            hierarchy['st'].rename('st').rename_axis('r').reset_index()
        )
        load_multiplier = (
            load_multiplier.rename(columns={'r': 'st'})
            .merge(ba_to_state, on='st', how='inner')
            [['year', 'r', 'multiplier']]
        )
    else:
        unrecognized = sorted(
            multiplier_regions - ba_regions - state_regions
        )[:10]
        raise ValueError(
            "load_multiplier.csv 'r' values are neither a subset of model "
            "regions nor of states. Unrecognized regions (first few): "
            f"{unrecognized}"
        )

    # Reformat hourly BA load profiles to merge with load multipliers
    regional_load_hourly = regional_load_hourly.reset_index(drop=False)
    regional_load_hourly = pd.melt(
        regional_load_hourly,
        id_vars=['datetime'],
        var_name='r',
        value_name='load'
    )
    # Merge load multipliers into hourly load profiles
    regional_load_hourly = regional_load_hourly.merge(
        load_multiplier,
        on=['r'],
        how='outer'
    )
    regional_load_hourly.sort_values(
        by=['r', 'year'],
        ascending=True,
        inplace=True
    )
    regional_load_hourly['load'] *= regional_load_hourly['multiplier']
    regional_load_hourly = regional_load_hourly[
        ['year', 'datetime', 'r', 'load']
    ]
    # Reformat hourly load profiles for GAMS
    regional_load_hourly = regional_load_hourly.pivot_table(
        index=['year', 'datetime'], columns='r', values='load')
    # Convert 'year' index to integers
    regional_load_hourly.index = (
        regional_load_hourly.index
        .set_levels(
            [
                regional_load_hourly.index.levels[0].astype(int),
                regional_load_hourly.index.levels[1]
            ],
            level=['year', 'datetime']
        )
    )

    return regional_load_hourly

def apply_miso_peak_reshape(
    regional_load_hourly: pd.DataFrame,
    inputs_case: str,
) -> pd.DataFrame:
    """
    Reshape MISO BA hourly load to match the MISO LTLF coincident load factor
    per subregion, preserving each BA's annual energy.

    MISO LTLF projects an improving load factor (peak grows more slowly than
    energy), but flat annual load growth freezes the historical hourly shape,
    so ReEDS keeps a constant (too low) load factor and overshoots the LTLF
    coincident peak. This applies an energy-preserving affine pivot around
    each BA's annual mean:

        L'(h) = mean_BA + alpha_sub * (L(h) - mean_BA)

    The same alpha_sub is applied to every MISO BA in a subregion, so the
    subregion coincident peak pivots by alpha while each BA's annual energy is
    preserved exactly (the hourly deviations from the mean sum to zero):

        alpha_sub = (1/LF_target_sub - 1) / (1/LF_current_sub - 1)

    LF_target_sub is the LTLF coincident load factor (peak_load_factor.csv,
    staged by copy_files). LF_current_sub is measured per model year from the
    grown hourly shape at the MISO-footprint coincident peak hour, averaged
    over weather years, matching the MISO LTLF coincident-peak definition
    (each subregion's demand at the hour the full MISO footprint peaks).

    Only MISO BAs listed in peak_load_factor.csv are reshaped; all other
    regions and any model year without a target pass through unchanged. If the
    targets file is absent (non-MISO-LTLF runs) load is returned as-is.

    Args:
        regional_load_hourly: (year, datetime)-indexed hourly BA load profiles.
        inputs_case: Path to the inputs case directory.

    Returns:
        pd.DataFrame: reshaped (year, datetime)-indexed hourly BA load profiles.
    """
    targets_path = os.path.join(inputs_case, 'peak_load_factor.csv')
    if not os.path.exists(targets_path):
        return regional_load_hourly

    targets = pd.read_csv(targets_path)
    required_cols = {'r', 'subregion', 'year', 'target_lf'}
    if not required_cols.issubset(targets.columns):
        raise ValueError(
            "peak_load_factor.csv is missing columns "
            f"{sorted(required_cols - set(targets.columns))}"
        )
    targets = targets.dropna(subset=['target_lf'])
    ba_to_sub = dict(zip(targets['r'], targets['subregion']))
    target_lf_lookup = {
        (int(y), s): lf
        for y, s, lf in zip(
            targets['year'], targets['subregion'], targets['target_lf']
        )
    }
    miso_bas_all = sorted(set(targets['r']))
    subregions = sorted(set(targets['subregion']))

    print('Applying MISO LTLF peak / load-factor reshape')
    model_years = regional_load_hourly.index.get_level_values('year').unique()
    reshaped = {}
    for model_year in model_years:
        load_my = regional_load_hourly.xs(model_year, level='year').copy()
        bas_present = [b for b in miso_bas_all if b in load_my.columns]
        year_targets = {
            s: target_lf_lookup.get((int(model_year), s)) for s in subregions
        }
        has_target = any(
            lf is not None and not np.isnan(lf) for lf in year_targets.values()
        )
        if not bas_present or not has_target:
            reshaped[model_year] = load_my
            continue

        # Weather year of each hour (datetime index of this model year).
        dt_index = load_my.index
        if not isinstance(dt_index, pd.DatetimeIndex):
            dt_index = pd.to_datetime(dt_index)
        wy_arr = np.asarray(dt_index.year)

        # MISO-footprint coincident peak hour position per weather year.
        miso_hourly = load_my[bas_present].sum(axis=1).to_numpy()
        peak_pos = np.array([
            positions[np.argmax(miso_hourly[positions])]
            for positions in (
                np.where(wy_arr == u)[0] for u in np.unique(wy_arr)
            )
        ])

        # Per-subregion compression factor alpha.
        sub_alpha = {}
        for s in subregions:
            lf_target = year_targets[s]
            if lf_target is None or np.isnan(lf_target) or lf_target <= 0:
                continue
            sub_bas = [b for b in bas_present if ba_to_sub[b] == s]
            if not sub_bas:
                continue
            sub_hourly = load_my[sub_bas].sum(axis=1)
            mean_load = sub_hourly.mean()
            coincident_peak = sub_hourly.to_numpy()[peak_pos].mean()
            # Degenerate / already-flat shapes: skip (leave load unchanged).
            if mean_load <= 0 or coincident_peak <= mean_load:
                continue
            lf_current = mean_load / coincident_peak
            denom = (1.0 / lf_current) - 1.0
            if denom <= 0:
                continue
            alpha = ((1.0 / lf_target) - 1.0) / denom
            sub_alpha[s] = alpha
            print(f"  {model_year} {s}: LF_current={lf_current:.3f} "
                  f"LF_target={lf_target:.3f} alpha={alpha:.3f}")
            if alpha > 1.0:
                print(f"  [warn] {model_year} {s}: alpha>1 (LTLF peakier than "
                      f"ReEDS); expanding peak.")

        # Energy-preserving affine pivot per BA about its annual mean.
        for b in bas_present:
            alpha = sub_alpha.get(ba_to_sub[b])
            if alpha is None:
                continue
            mean_ba = load_my[b].mean()
            load_my[b] = mean_ba + alpha * (load_my[b] - mean_ba)

        # Diagnostic: confirm the MISO-footprint peak hour is unchanged (the
        # per-subregion alphas can in principle shift the coincident hour).
        if sub_alpha:
            miso_after = load_my[bas_present].sum(axis=1).to_numpy()
            moved = sum(
                int(positions[np.argmax(miso_after[positions])]
                    != peak_pos[i])
                for i, positions in enumerate(
                    np.where(wy_arr == u)[0] for u in np.unique(wy_arr)
                )
            )
            if moved:
                print(f"  [warn] {model_year}: MISO coincident peak hour "
                      f"shifted for {moved} weather year(s) after reshape.")

        reshaped[model_year] = load_my

    out = pd.concat(reshaped, names=['year'])
    out = out.reorder_levels(['year', 'datetime']).sort_index()
    return out[regional_load_hourly.columns]

def downselect_to_model_years(
    load_hourly: pd.DataFrame,
    model_years: list[int]
) -> pd.DataFrame:
    """
    Retrieve the subset of hourly load profiles corresponding
    to the given model years.

    Args:
        load_hourly: Hourly load profiles.
        model_years: List of model years used to filter load_hourly.
            These years should correspond to load_hourly's "year"
            index level.

    Returns:
        pd.DataFrame
    """
    return (
        load_hourly.loc[(
            load_hourly.index
            .get_level_values('year')
            .isin(model_years)
        )]
    )

def downselect_to_weather_years(
    load_hourly: pd.DataFrame,
    weather_years: list[int]
) -> pd.DataFrame:
    """
    Retrieve the subset of hourly load profiles corresponding
    to the given weather years.
    
    Args:
        load_hourly: Hourly load profiles.
        weather_years: List of weather years used to filter load_hourly.
            These years should correspond to the years of load_hourly's
            "datetime" index level.

    Returns:
        pd.DataFrame
    """
    return (
        load_hourly.loc[(
            load_hourly.index
            .get_level_values('datetime')
            .year
            .isin(weather_years)
        )]
    )

def duplicate_weather_years(load_hourly, weather_years):
    """
    Replicate hourly load profiles to match the number of weather years.
    
    Args:
        load_hourly: Hourly load profiles with only one weather year of data.
        weather_years: List of weather years to replicate load profiles for.

    Returns:
        pd.DataFrame
    """
    # Copy the load profiles n times for the number of weather years and
    # concatenate them
    num_years = len(weather_years)
    load_hourly_wide = load_hourly.unstack('year')

    if len(load_hourly_wide) != 8760:
        raise ValueError(
            "The provided dataframe has more than one weather year of data."
        )

    load_hourly = (
        pd.concat([load_hourly_wide] * num_years, axis=0, ignore_index=True)
        .rename_axis('hour').stack('year')
        .reorder_levels(['year','hour']).sort_index(axis=0, level=['year','hour'])
    )
    # Update the time index of the concatenated load profile to contain
    # the hours of each weather year
    fulltimeindex = pd.Series(reeds.timeseries.get_timeindex(weather_years))
    load_hourly['datetime'] = (
        load_hourly.index.get_level_values('hour').map(fulltimeindex)
    )
    load_hourly = load_hourly.set_index('datetime', append=True).droplevel('hour')

    return load_hourly

def apply_distribution_loss_factor(
    load_hourly: pd.DataFrame,
    distloss: float = 0.05
) -> pd.DataFrame:
    """
    Adjust hourly end-use load profiles to account for energy
    lost during transmission and distribution.
    
    Args:
        load_hourly: Hourly load profiles.
        distloss: Percentage of busbar load lost during
            transmission and distribution.

    Returns:
        pd.DataFrame
    """
    return load_hourly / (1 - distloss)

def calculate_peak_load(
    load_hourly: pd.DataFrame,
    hierarchy: pd.DataFrame
) -> pd.DataFrame:
    """
    Calculate coincident peak demand at all region hierarchy levels.
    
    Args:
        load_hourly: Hourly load profiles.
        hierarchy: Model region hierarchy levels.

    Returns:
        pd.DataFrame
    """
    _peakload = {}
    for _level in hierarchy.columns:
        _peakload[_level] = (
            ## Aggregate to level
            load_hourly.rename(columns=hierarchy[_level])
            .T.groupby(level=0).sum().T
            ## Calculate peak
            .groupby(level='year').max()
            .T
        )

    ## Also calculate it at r level
    _peakload['r'] = load_hourly.groupby(level='year').max().T
    peakload = pd.concat(_peakload, names=['level','region']).round(3)

    return peakload

def reaggregate_to_model_regions(
    state_load_hourly: pd.DataFrame,
    inputs_case: str,
    GSw_LoadAllocationMethod: str,
    dr_data: bool = False
) -> pd.DataFrame:
    """
    Allocate hourly state load to model regions according to the provided
    load allocation method (e.g., according to each region's share of 
    state population).
    
    Args:
        state_load_hourly: Hourly state load profiles.
        inputs_case: Path to the inputs case directory.
        GSw_LoadAllocationMethod: Method by which to allocate state
            load to model regions.

    Returns:
        pd.DataFrame
    """
    # Get state/region-to-county disaggregation factors
    disagg_data = reeds.io.get_disagg_data(
        os.path.dirname(inputs_case),
        disagg_variable=GSw_LoadAllocationMethod
    )
    # Calculate state-to-region aggregation/disaggregation factors
    state_region_factors = (
        disagg_data.groupby(['state', 'r'], as_index=False)
        ['state_frac']
        .sum()
        .pivot(index='state', columns='r', values='state_frac')
        .rename_axis(None, axis=1)
        .fillna(0)
    )
    # Identify regions with aggregation/disaggregation factors of 0
    # and raise an error if any exist 
    if state_region_factors.sum().min() == 0:
        regional_factors = state_region_factors.sum()
        no_load_regions = (
            regional_factors.loc[regional_factors == 0].index.tolist()
        )
        raise ValueError(
            f"Load allocation method {GSw_LoadAllocationMethod} produced the "
            "following regions with 0 load. Update GSw_LoadAllocationMethod "
            "in your cases file:\n{}\n"
            .format('\n'.join(no_load_regions))
        )
    # Demand response data may not be populated for every state
    if dr_data:
        state_region_factors = state_region_factors.loc[state_region_factors.index.intersection(state_load_hourly.columns), :]
    
    # Multiply the hourly state load profiles by the state-to-region factors
    regional_load_hourly = (
        state_load_hourly[state_region_factors.index]
        .dot(state_region_factors)
    )

    return regional_load_hourly


#%% ===========================================================================
### --- MAIN FUNCTION ---
### ===========================================================================
def main(reeds_path, inputs_case):
    print('Starting hourly_load.py')

    #%%### Load inputs
    ### Load the input parameters
    sw = reeds.io.get_switches(inputs_case)
    weather_years = sw.resource_adequacy_years_list
    scalars = reeds.io.get_scalars(inputs_case)
    solveyears = reeds.io.get_years(os.path.dirname(inputs_case))
    hierarchy = reeds.io.get_hierarchy(os.path.dirname(inputs_case))

    #%%%#########################################
    #    -- Get load profiles --    #
    #############################################

    state_load_hourly = reeds.io.get_load_hourly(inputs_case)
    state_load_hourly = downselect_to_weather_years(
        state_load_hourly,
        weather_years
    )
    historical_state_load_annual = reeds.io.get_historical_state_load_annual()

    match sw.GSw_LoadProfiles:
        case _ if (
            sw.GSw_LoadProfiles.startswith('EER')
            or Path(sw.GSw_LoadProfiles).is_file()
        ):
            endyear = int(sw.endyear)
            state_load_hourly = interpolate_missing_model_years(
                state_load_hourly,
                endyear
            )
            state_load_hourly = (
                calibrate_hourly_state_load_to_historical_annuals(
                    state_load_hourly,
                    historical_state_load_annual
                )
            )
            historical_state_load_hourly = reeds.io.get_load_hourly(
                GSw_LoadProfiles='historic'
            )
            historical_state_load_hourly = downselect_to_weather_years(
                historical_state_load_hourly,
                weather_years
            )
            state_load_hourly = prepend_historical_hourly_state_load(
                state_load_hourly,
                historical_state_load_hourly,
                historical_state_load_annual
            )
            state_load_hourly = downselect_to_model_years(
                state_load_hourly,
                solveyears
            )
        case 'historic':
            state_load_hourly = (
                scale_historical_state_load_to_baseline_year(
                    state_load_hourly,
                    historical_state_load_annual,
                    inputs_case
                )
            )
        case _:
            state_load_hourly = downselect_to_model_years(
                state_load_hourly,
                solveyears
            )
            if len(state_load_hourly.unstack('year')) == 8760:
                state_load_hourly = duplicate_weather_years(
                    state_load_hourly,
                    weather_years
                )

    regional_load_hourly = reaggregate_to_model_regions(
        state_load_hourly,
        inputs_case,
        sw.GSw_LoadAllocationMethod
    )

    # For the 'historic' profile, load growth is applied here, at
    # model-region (BA) resolution, after the baseline-year state load has
    # been allocated to BAs. This lets BA-level load multipliers (e.g. a MISO
    # BA on a different trajectory than the rest of its state) be honored; a
    # state-keyed load_multiplier.csv is expanded to BAs and reproduces the
    # previous state-level result exactly.
    if sw.GSw_LoadProfiles == 'historic':
        regional_load_hourly = apply_ba_load_growth(
            regional_load_hourly,
            inputs_case,
            hierarchy,
            solveyears
        )
        # Reshape MISO BA hourly load to the LTLF coincident load factor
        # (energy-preserving). No-op when peak_load_factor.csv is absent.
        regional_load_hourly = apply_miso_peak_reshape(
            regional_load_hourly,
            inputs_case,
        )

    #%%%#########################################
    #    -- Performing Load Modifications --    #
    #############################################

    regional_load_hourly = apply_distribution_loss_factor(
        regional_load_hourly,
        scalars['distloss']
    )
    regional_load_hourly = regional_load_hourly.astype(np.float32)

    #%%%#########################################
    #    -- Peak Load Calculation --    #
    #############################################

    peakload = calculate_peak_load(regional_load_hourly, hierarchy)

    #%%%#########################################
    #    -- DR Shed Load Modifications --    #
    #############################################

    if int(sw.GSw_DRShed): 
        state_dr_shed_hourly = reeds.io.read_file(os.path.join(inputs_case, 'dr_shed_hourly.h5'))
        dr_types = list({x.split('|')[0] for x in state_dr_shed_hourly.columns[1:]})

        # Reformat to match state load profiles
        state_dr_shed_hourly = state_dr_shed_hourly.reset_index().set_index(['year','datetime'])
        regional_dr_shed_hourly = {}
        for dr_type in dr_types:
            type_cols = [col for col in state_dr_shed_hourly.columns if col.startswith(dr_type)]
            reg_shed = state_dr_shed_hourly[type_cols].copy()
            reg_shed.columns = [col.split('|')[1] for col in reg_shed.columns]
            reg_shed = reaggregate_to_model_regions(
                reg_shed,
                inputs_case,
                'state_lpf',
                dr_data=True
            )
            # Add back dr type to column header 
            reg_shed.columns = [f"{dr_type}|{col}" for col in reg_shed.columns]            
            reg_shed = reg_shed.reset_index()
            if isinstance(reg_shed['datetime'].iloc[0], bytes):
                reg_shed['datetime'] = reg_shed['datetime'].str.decode('utf-8')
            reg_shed['datetime'] = pd.to_datetime(reg_shed['datetime'])
            reg_shed = reg_shed.set_index(['year','datetime'])
            regional_dr_shed_hourly[dr_type] = reg_shed

        # Combined dr shed types
        regional_dr_shed_hourly = pd.concat(regional_dr_shed_hourly.values(), axis=1)
        regional_dr_shed_hourly = regional_dr_shed_hourly.astype(np.float32)
        regional_dr_shed_hourly = regional_dr_shed_hourly.reset_index().set_index(['datetime'])

    #%%###########################
    #    -- Data Write-Out --    #
    ##############################

    reeds.io.write_profile_to_h5(regional_load_hourly, 'load.h5', inputs_case)
    peakload.to_csv(os.path.join(inputs_case,'peakload.csv'))
    ### Write peak demand by transmission region to use in firm net import constraint
    peakload_transreg = (
        peakload.loc['transreg']
        .stack('year')
        .rename_axis(['transreg','t'])
        .rename('MW')
    )
    reeds.io.write_to_inputs_h5(
        peakload_transreg, 'peakload_transreg', inputs_case, gamstype='parameter',
        units='MW', comment='Peak exogenous demand across all weather years by transmission region',
    )
    if int(sw.GSw_DRShed):
        reeds.io.write_profile_to_h5(regional_dr_shed_hourly, 'dr_shed_hourly.h5', inputs_case)

#%% ===========================================================================
### --- PROCEDURE ---
### ===========================================================================

if __name__ == '__main__':
    # Time the operation of this script
    tic = datetime.datetime.now()

    ### Parse arguments
    parser = argparse.ArgumentParser(
        description='Create run-specific hourly profiles',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('reeds_path', help='ReEDS directory')
    parser.add_argument('inputs_case', help='ReEDS/runs/{case}/inputs_case directory')

    args = parser.parse_args()
    reeds_path = args.reeds_path
    inputs_case = args.inputs_case

    # #%% Inputs for testing
    # reeds_path = reeds.io.reeds_path
    # inputs_case = str(Path(reeds_path, 'runs', 'v20260610_envM0_Pacific', 'inputs_case'))

    #%% Set up logger
    log = reeds.log.makelog(
        scriptname=__file__,
        logpath=os.path.join(inputs_case,'..','gamslog.txt'),
    )

    #%% Run it
    main(reeds_path=reeds_path, inputs_case=inputs_case)

    reeds.log.toc(tic=tic, year=0, process='input_processing/hourly_load.py',
        path=os.path.join(inputs_case,'..'))
    
    print('Finished hourly_load.py')
