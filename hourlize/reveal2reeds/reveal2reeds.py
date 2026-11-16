import numpy as np
import pandas as pd

def get_national_model_year_data_center_demand(
    national_demand_source_path: str,
    model_year: int
) -> int:
    data_center_demand = pd.read_csv(national_demand_source_path)
    model_year_data_center_demand = (
        data_center_demand.loc[(
            data_center_demand.year == model_year
        )]
        .copy()
    )
    national_model_year_data_center_demand = (
        model_year_data_center_demand['total_data_center_mw'].sum()
    )

    return national_model_year_data_center_demand

def get_propagation_by_weather_year(
    propagation_source: dict[str, str],
) -> pd.Series:
    propagation_by_weather_year = pd.read_csv(propagation_source['filepath'])
    propagation_by_weather_year = (
        propagation_by_weather_year.loc[(
            propagation_by_weather_year.scenario == propagation_source['scenario']
        )]
        .set_index('year')
        ['avg_prop']
    )

    return propagation_by_weather_year
    

def calculate_national_data_center_demand_hourly(
    df_load: pd.DataFrame,
    model_year: int,
    national_demand_source_path: str,
    weather_year_propagation_source: str
):
    # Calculate national projected data center demand for the model year
    national_data_center_demand = get_national_model_year_data_center_demand(
        national_demand_source_path,
        model_year
    )

    # Get propagation factors by weather year.
    # Propagation factors represent the percentage of projected national
    # data center demand for the model year that is expected to be
    # realized during each hour of each weather year.
    propagation_by_weather_year = get_propagation_by_weather_year(
        weather_year_propagation_source
    )

    # Estimate national hourly load values for each weather year
    # by multiplying the propagation factors by national data
    # center demand for the model year.
    national_data_center_demand_hourly = pd.DataFrame(
        index=df_load['weather_datetime'].drop_duplicates()
    )
    national_data_center_demand_hourly['propagation_factor'] = (
        national_data_center_demand_hourly.index.year
        .map(propagation_by_weather_year)
    )
    national_data_center_demand_hourly['demand_MW'] = (
        national_data_center_demand_hourly['propagation_factor']
        * national_data_center_demand
    )
    national_data_center_demand_hourly = (
        national_data_center_demand_hourly['demand_MW']
    )

    return national_data_center_demand_hourly

def get_data_center_cooling_weights(
    cooling_proportions_source_path: str
) -> pd.DataFrame:
    state_cooling_weights = pd.read_csv(cooling_proportions_source_path)
    state_cooling_weights["weather_datetime"] = (
        pd.to_datetime(state_cooling_weights["weather_datetime"])
    )
    national_cooling_weights = (
        state_cooling_weights.groupby("weather_datetime")
        ["cooling_prop"]
        .mean()
    )

    return national_cooling_weights

def get_data_center_state_weights(
    state_proportions_source: dict[str, str],
    model_year: int
) -> pd.DataFrame:
    data_center_year = 2024 if model_year == 2025 else model_year
    state_weights = pd.read_excel(state_proportions_source['filepath'])
    state_weights = (
        state_weights.loc[
            (state_weights['Run Name'] == state_proportions_source['scenario'])
            & (state_weights['Year'] == data_center_year)
        ]
        .set_index('State')
        ["% of Total Data Center Load"]
    )

    return state_weights


def apply_state_and_subsector_weights(
    national_demand: pd.DataFrame,
    state_weights: pd.Series,
    subsector_weights: pd.Series,
    subsector: str,
):
    national_subsector_demand = national_demand * subsector_weights
    state_subsector_demand = pd.DataFrame(
        np.outer(national_subsector_demand, state_weights),
        index=national_subsector_demand.index,
        columns=state_weights.index
    )
    state_subsector_demand = (
        state_subsector_demand.reset_index()
        .assign(
            sector='commercial',
            subsector=subsector,
            dispatch_feeder='Commercial'
        )
        .rename_axis(columns='')
    )

    return state_subsector_demand

def calculate_state_subsector_data_center_demand_hourly(
    df_load: pd.DataFrame,
    model_year: int,
    national_demand_source_path: str,
    cooling_proportions_source_path: str,
    weather_year_propagation_source: str,
    state_proportions_source: str
) -> pd.DataFrame:
    # Calculate hourly national data center demand
    national_data_center_demand_hourly = (
        calculate_national_data_center_demand_hourly(
            df_load,
            model_year,
            national_demand_source_path,
            weather_year_propagation_source
        )
    )
    # Calculate proportion of national demand attributable to each state
    state_weights = get_data_center_state_weights(
        state_proportions_source,
        model_year
    )
    state_weights = state_weights.loc[state_weights.index.isin(df_load.columns)]
    # Get proportion of hourly demand attributable to cooling
    data_center_cooling_weights = get_data_center_cooling_weights(
        cooling_proportions_source_path
    )
    # Calculate state-by-state hourly demand for data center cooling subsector
    state_data_center_cooling_demand_hourly = apply_state_and_subsector_weights(
        national_demand=national_data_center_demand_hourly,
        state_weights=state_weights,
        subsector_weights=data_center_cooling_weights,
        subsector='data center cooling',
    )
    # Calculate state-by-state hourly demand for data center IT subsector
    data_center_it_weights = 1 - data_center_cooling_weights
    state_data_center_it_demand_hourly = apply_state_and_subsector_weights(
        national_demand=national_data_center_demand_hourly,
        state_weights=state_weights,
        subsector_weights=data_center_it_weights,
        subsector='data center it',
    )
    # Concatenate all state subsector-level demand
    state_subsector_data_center_demand_hourly = (
        pd.concat(
            [
                state_data_center_cooling_demand_hourly,
                state_data_center_it_demand_hourly
            ],
            ignore_index=True
        )
        .fillna(0)
    )
    return state_subsector_data_center_demand_hourly

def apply_custom_data_center_demand_projections(
    df_load: pd.DataFrame,
    model_year: int,
    cf: dict
):
    state_subsector_data_center_demand_hourly = (
        calculate_state_subsector_data_center_demand_hourly(
            df_load,
            model_year,
            cf['national_demand_source'],
            cf['cooling_proportions_source'],
            cf['weather_year_propagation_source'],
            cf['state_proportions_source']
        )
    )

    if cf['replace_existing_data_center_demand']:
        data_center_subsectors = cf['subsectors']['commercial']
        df_load = pd.concat(
            [
                df_load.loc[~df_load.subsector.isin(data_center_subsectors)],
                state_subsector_data_center_demand_hourly
            ],
            ignore_index=True
        )
    else:
        df_load = (
            pd.concat(
                [df_load, state_subsector_data_center_demand_hourly],
                ignore_index=True
            )
            .groupby(
                [
                    'weather_datetime',
                    'sector',
                    'subsector',
                ],
                as_index=False
            )
            .sum(numeric_only=True)
        )

    return df_load