from __future__ import annotations

import argparse
import json
import os
from io import BytesIO
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import matplotlib
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

matplotlib.use("Agg")
import matplotlib.pyplot as plt


DEFAULT_EIA = (
    "https://raw.githubusercontent.com/ReEDS-Model/ReEDS/main/"
    "inputs/capacity_exogenous/ReEDS_generator_database_final_EIA-NEMS.csv"
)
DEFAULT_WIND_SC = (
    r"\\nrelnas01\ReEDS\Supply_Curve_Data\ONSHORE\2025_08_31_NewSites"
    r"\reV\wind_reference\wind_reference_supply-curve.csv"
)
DEFAULT_UPV_SC = (
    r"\\nrelnas01\ReEDS\Supply_Curve_Data\UPV\2025_09_29_Update"
    r"\reV\01_reference\01_reference_supply-curve.csv"
)
DEFAULT_EIA_STATE_GENERATION = (
    "https://www.eia.gov/electricity/data/state/annual_generation_state.xls"
)
DEFAULT_EIA_LOAD_API = (
    "https://api.eia.gov/v2/electricity/state-electricity-profiles/"
    "source-disposition/data/"
)
DEFAULT_OUTPUT = "existing_wind_upv_rev_lcoe_cf.csv"
DEFAULT_MARKET_DATA_OUTPUT = "eia_state_generation_load_1990_2024.csv"
DEFAULT_CHARTS_DIR = "charts"

EIA_COLUMNS = [
    "tech",
    "summer_power_capacity_MW",
    "StartYear",
    "T_LAT",
    "T_LONG",
    "county",
    "TSTATE",
]
SC_COLUMNS = [
    "sc_point_gid",
    "latitude",
    "longitude",
    "capacity_ac_mw",
    "capacity_factor_ac",
    "lcoe_site_usd_per_mwh",
    "lcot_usd_per_mwh",
    "lcoe_all_in_usd_per_mwh",
]
GENERATION_COLUMNS = [
    "YEAR",
    "STATE",
    "TYPE OF PRODUCER",
    "ENERGY SOURCE",
    "GENERATION (Megawatthours)",
]
TOTAL_POWER_INDUSTRY = "Total Electric Power Industry"
TECH_GENERATION_COLUMN = {
    "wind-ons": "wind_generation_mwh",
    "upv": "upv_generation_mwh",
}
EARTH_RADIUS_KM = 6371.0088
MWH_PER_TWH = 1_000_000
HOURS_PER_YEAR = 8760
STATE_FIPS_TO_ABBR = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA",
    "08": "CO", "09": "CT", "10": "DE", "11": "DC", "12": "FL",
    "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN",
    "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME",
    "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS",
    "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
    "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
    "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
    "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI",
    "56": "WY",
}
STATE_NAME_TO_ABBR = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR",
    "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT",
    "DELAWARE": "DE", "DISTRICT OF COLUMBIA": "DC", "FLORIDA": "FL",
    "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL",
    "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS", "KENTUCKY": "KY",
    "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN",
    "MISSISSIPPI": "MS", "MISSOURI": "MO", "MONTANA": "MT",
    "NEBRASKA": "NE", "NEVADA": "NV", "NEW HAMPSHIRE": "NH",
    "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH",
    "OKLAHOMA": "OK", "OREGON": "OR", "PENNSYLVANIA": "PA",
    "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX",
    "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA",
    "WASHINGTON": "WA", "WEST VIRGINIA": "WV", "WISCONSIN": "WI",
    "WYOMING": "WY",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a CSV of existing EIA onshore wind and UPV plants with "
            "nearest positive-capacity reV LCOE/capacity factor, EIA state and "
            "national generation market shares, and fitted charts."
        )
    )
    parser.add_argument("--eia", default=DEFAULT_EIA, help="EIA generator database CSV path or URL.")
    parser.add_argument("--wind-sc", default=DEFAULT_WIND_SC, help="Onshore wind reV supply-curve CSV path.")
    parser.add_argument("--upv-sc", default=DEFAULT_UPV_SC, help="UPV reV supply-curve CSV path.")
    parser.add_argument(
        "--eia-state-generation",
        default=DEFAULT_EIA_STATE_GENERATION,
        help="EIA annual state generation XLS path or URL.",
    )
    parser.add_argument(
        "--eia-api-key",
        default=os.environ.get("EIA_API_KEY", "DEMO_KEY"),
        help="EIA API key for state retail-sales/direct-use data; defaults to EIA_API_KEY or DEMO_KEY.",
    )
    parser.add_argument("--out", default=DEFAULT_OUTPUT, help="Enriched plant CSV output path.")
    parser.add_argument(
        "--market-data-out",
        default=DEFAULT_MARKET_DATA_OUTPUT,
        help="Processed annual EIA state/national market data CSV output path.",
    )
    parser.add_argument("--charts-dir", default=DEFAULT_CHARTS_DIR, help="Chart output directory.")
    parser.add_argument("--no-charts", action="store_true", help="Do not create chart outputs.")
    return parser.parse_args()


def unit_sphere_xyz(latitude: Iterable[float], longitude: Iterable[float]) -> np.ndarray:
    lat_rad = np.radians(np.asarray(latitude, dtype=float))
    lon_rad = np.radians(np.asarray(longitude, dtype=float))
    cos_lat = np.cos(lat_rad)
    return np.column_stack(
        [
            cos_lat * np.cos(lon_rad),
            cos_lat * np.sin(lon_rad),
            np.sin(lat_rad),
        ]
    )


def chord_to_km(chord_distance: np.ndarray) -> np.ndarray:
    angular_distance = 2 * np.arcsin(np.minimum(1, chord_distance / 2))
    return angular_distance * EARTH_RADIUS_KM


def read_eia(path_or_url: str) -> pd.DataFrame:
    eia = pd.read_csv(path_or_url, usecols=EIA_COLUMNS)
    eia = eia[eia["tech"].isin(["wind-ons", "upv"])].copy()
    for column in ["T_LAT", "T_LONG", "StartYear", "summer_power_capacity_MW"]:
        eia[column] = pd.to_numeric(eia[column], errors="coerce")
    eia["TSTATE"] = eia["TSTATE"].astype(str).str.strip().str.upper()
    eia = eia.dropna(subset=["T_LAT", "T_LONG"])
    return eia


def find_column(columns: Iterable[str], candidates: Iterable[str]) -> Optional[str]:
    lookup = {str(column).strip().lower(): column for column in columns}
    for candidate in candidates:
        if candidate.lower() in lookup:
            return lookup[candidate.lower()]
    return None


def normalize_state(value: object) -> Optional[str]:
    if pd.isna(value):
        return None
    text = str(value).strip().upper()
    if len(text) == 2 and text.isalpha():
        return text
    if text.startswith("US-") and len(text) == 5:
        return text[-2:]
    if text in STATE_NAME_TO_ABBR:
        return STATE_NAME_TO_ABBR[text]

    try:
        numeric_value = float(text.replace(",", ""))
    except ValueError:
        numeric_value = np.nan
    if np.isfinite(numeric_value) and numeric_value.is_integer():
        digits = str(int(numeric_value))
    else:
        digits = "".join(character for character in text if character.isdigit())
    if not digits:
        return None
    if len(digits) <= 2:
        state_fips = digits.zfill(2)
    else:
        state_fips = digits.zfill(5)[:2]
    return STATE_FIPS_TO_ABBR.get(state_fips)


def read_supply_curve(path: str) -> pd.DataFrame:
    columns = pd.read_csv(path, nrows=0).columns.tolist()
    state_column = find_column(
        columns,
        ["state", "state_abbr", "state_code", "tstate"],
    )
    county_fips_column = find_column(
        columns,
        ["cnty_fips", "county_fips", "county_fips_code", "fips"],
    )
    geography_column = state_column or county_fips_column
    if geography_column is None:
        raise ValueError(
            f"Supply curve {path} has no recognized state or county-FIPS column. "
            f"Available columns: {columns}"
        )

    use_columns = list(dict.fromkeys(SC_COLUMNS + [geography_column]))
    supply_curve = pd.read_csv(path, usecols=use_columns)
    geography = supply_curve[geography_column].copy()
    supply_curve["state"] = geography.map(normalize_state)
    supply_curve["capacity_ac_mw"] = pd.to_numeric(supply_curve["capacity_ac_mw"], errors="coerce")
    supply_curve = supply_curve[supply_curve["capacity_ac_mw"] > 0].copy()
    if supply_curve.empty:
        raise ValueError(f"No positive-capacity supply-curve sites found in {path}")

    for column in [
        "latitude",
        "longitude",
        "capacity_factor_ac",
        "lcoe_site_usd_per_mwh",
        "lcot_usd_per_mwh",
        "lcoe_all_in_usd_per_mwh",
    ]:
        supply_curve[column] = pd.to_numeric(supply_curve[column], errors="coerce")
    supply_curve = supply_curve.dropna(subset=["latitude", "longitude"])
    if supply_curve.empty:
        raise ValueError(f"No supply-curve sites with usable coordinates found in {path}")
    return supply_curve.reset_index(drop=True)


def build_cumulative_rev_curve(
    supply_curve: pd.DataFrame,
    maximum_generation_twh: float,
    lcoe_column: str,
    state: Optional[str] = None,
) -> pd.DataFrame:
    curve = supply_curve
    if state is not None:
        curve = curve[curve["state"] == state]
    curve = curve[
        [
            "capacity_ac_mw",
            "capacity_factor_ac",
            lcoe_column,
        ]
    ].copy()
    for column in curve.columns:
        curve[column] = pd.to_numeric(curve[column], errors="coerce")
    curve = curve.dropna()
    curve = curve[
        (curve["capacity_ac_mw"] > 0)
        & (curve["capacity_factor_ac"] > 0)
        & (curve[lcoe_column] >= 0)
    ].copy()
    if curve.empty or not np.isfinite(maximum_generation_twh) or maximum_generation_twh <= 0:
        return pd.DataFrame(
            columns=["cumulative_generation_twh", lcoe_column]
        )

    curve["annual_generation_twh"] = (
        curve["capacity_ac_mw"]
        * curve["capacity_factor_ac"]
        * HOURS_PER_YEAR
        / MWH_PER_TWH
    )
    curve = curve.sort_values(
        [lcoe_column, "annual_generation_twh"],
        kind="mergesort",
    )
    curve["cumulative_generation_twh"] = curve["annual_generation_twh"].cumsum()
    curve = curve[curve["cumulative_generation_twh"] <= maximum_generation_twh]
    return curve[
        ["cumulative_generation_twh", lcoe_column]
    ].reset_index(drop=True)


def attach_nearest_rev_sites(existing: pd.DataFrame, supply_curve: pd.DataFrame) -> pd.DataFrame:
    tree = cKDTree(unit_sphere_xyz(supply_curve["latitude"], supply_curve["longitude"]))
    chord_distance, nearest_index = tree.query(unit_sphere_xyz(existing["T_LAT"], existing["T_LONG"]), k=1)
    nearest = supply_curve.iloc[nearest_index].reset_index(drop=True)
    matched = existing.reset_index(drop=True).copy()
    matched["rev_sc_point_gid"] = nearest["sc_point_gid"].to_numpy()
    matched["rev_latitude"] = nearest["latitude"].to_numpy()
    matched["rev_longitude"] = nearest["longitude"].to_numpy()
    matched["rev_distance_km"] = chord_to_km(chord_distance)
    matched["capacity_factor_ac"] = nearest["capacity_factor_ac"].to_numpy()
    matched["lcoe_site_usd_per_mwh"] = nearest["lcoe_site_usd_per_mwh"].to_numpy()
    matched["lcot_usd_per_mwh"] = nearest["lcot_usd_per_mwh"].to_numpy()
    matched["lcoe_all_in_usd_per_mwh"] = nearest["lcoe_all_in_usd_per_mwh"].to_numpy()
    return matched


def read_excel_source(path_or_url: str) -> pd.DataFrame:
    if path_or_url.lower().startswith(("http://", "https://")):
        request = Request(path_or_url, headers={"User-Agent": "ReEDS-existing-site-market-share/1.0"})
        with urlopen(request, timeout=180) as response:
            source = BytesIO(response.read())
        return pd.read_excel(source, header=1, usecols=GENERATION_COLUMNS)
    return pd.read_excel(path_or_url, header=1, usecols=GENERATION_COLUMNS)


def read_eia_generation(path_or_url: str) -> pd.DataFrame:
    generation = read_excel_source(path_or_url)
    generation = generation[generation["TYPE OF PRODUCER"] == TOTAL_POWER_INDUSTRY].copy()
    generation["YEAR"] = pd.to_numeric(generation["YEAR"], errors="coerce")
    generation["STATE"] = generation["STATE"].astype(str).str.strip().str.upper()
    generation["STATE"] = generation["STATE"].replace({"US-TOTAL": "US"})
    generation["GENERATION (Megawatthours)"] = pd.to_numeric(
        generation["GENERATION (Megawatthours)"], errors="coerce"
    )
    generation = generation.dropna(subset=["YEAR", "GENERATION (Megawatthours)"])
    generation["YEAR"] = generation["YEAR"].astype(int)

    pivot = generation.pivot_table(
        index=["YEAR", "STATE"],
        columns="ENERGY SOURCE",
        values="GENERATION (Megawatthours)",
        aggfunc="sum",
    )
    for source in ["Total", "Pumped Storage", "Wind", "Solar Thermal and Photovoltaic"]:
        if source not in pivot.columns:
            pivot[source] = 0.0

    market_generation = pivot.reset_index()
    market_generation = market_generation[
        market_generation["STATE"].str.fullmatch(r"(US|[A-Z]{2})", na=False)
    ].copy()
    market_generation["wind_generation_mwh"] = market_generation["Wind"].fillna(0)
    market_generation["upv_generation_mwh"] = market_generation[
        "Solar Thermal and Photovoltaic"
    ].fillna(0)
    market_generation["pumped_storage_generation_mwh"] = market_generation[
        "Pumped Storage"
    ].fillna(0)
    market_generation["total_nonstorage_generation_mwh"] = (
        market_generation["Total"] - market_generation["pumped_storage_generation_mwh"]
    )
    return market_generation[
        [
            "YEAR",
            "STATE",
            "wind_generation_mwh",
            "upv_generation_mwh",
            "pumped_storage_generation_mwh",
            "total_nonstorage_generation_mwh",
        ]
    ].rename(columns={"YEAR": "year", "STATE": "state"})


def fetch_eia_load(api_key: str) -> pd.DataFrame:
    parameters = [
        ("api_key", api_key),
        ("frequency", "annual"),
        ("data[0]", "total-elect-indust"),
        ("data[1]", "direct-use"),
        ("start", "1990"),
        ("end", "2024"),
        ("sort[0][column]", "period"),
        ("sort[0][direction]", "asc"),
        ("offset", "0"),
        ("length", "5000"),
    ]
    request = Request(
        f"{DEFAULT_EIA_LOAD_API}?{urlencode(parameters)}",
        headers={"User-Agent": "ReEDS-existing-site-market-share/1.0"},
    )
    with urlopen(request, timeout=180) as response:
        payload = json.load(response)

    response = payload.get("response", {})
    records = response.get("data", [])
    total_records = int(response.get("total", len(records)))
    if len(records) != total_records:
        raise ValueError(
            f"EIA load API returned {len(records):,} of {total_records:,} records; "
            "increase the requested length."
        )

    load = pd.DataFrame.from_records(records)
    required = {"period", "state", "total-elect-indust", "direct-use"}
    missing = required.difference(load.columns)
    if missing:
        raise ValueError(f"EIA load API response is missing columns: {sorted(missing)}")

    load["year"] = pd.to_numeric(load["period"], errors="coerce")
    load["state"] = load["state"].astype(str).str.strip().str.upper()
    load["retail_sales_mwh"] = pd.to_numeric(load["total-elect-indust"], errors="coerce")
    load["direct_use_mwh"] = pd.to_numeric(load["direct-use"], errors="coerce")
    load["total_load_mwh"] = load["retail_sales_mwh"] + load["direct_use_mwh"]
    load = load.dropna(subset=["year"])
    load["year"] = load["year"].astype(int)
    return load[
        ["year", "state", "retail_sales_mwh", "direct_use_mwh", "total_load_mwh"]
    ]


def build_market_data(generation: pd.DataFrame, load: pd.DataFrame) -> pd.DataFrame:
    market = generation.merge(load, on=["year", "state"], how="left", validate="one_to_one")
    denominator = market["total_nonstorage_generation_mwh"]
    market["wind_market_share_pct"] = np.where(
        denominator > 0,
        100 * market["wind_generation_mwh"] / denominator,
        np.nan,
    )
    market["upv_market_share_pct"] = np.where(
        denominator > 0,
        100 * market["upv_generation_mwh"] / denominator,
        np.nan,
    )
    return market.sort_values(["year", "state"]).reset_index(drop=True)


def attach_market_data(plants: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    available_years = market.loc[market["state"] == "US", "year"]
    if available_years.empty:
        raise ValueError("EIA market data does not contain national rows with state='US'.")
    minimum_year = int(available_years.min())
    maximum_year = int(available_years.max())

    enriched = plants.copy()
    start_year = pd.to_numeric(enriched["StartYear"], errors="coerce")
    market_year_available = start_year.between(minimum_year, maximum_year)
    enriched["eia_market_year"] = start_year.where(market_year_available)
    enriched["eia_market_year_out_of_range"] = (
        start_year.notna() & ~market_year_available
    )

    state_columns = [
        "year",
        "state",
        "wind_generation_mwh",
        "upv_generation_mwh",
        "total_nonstorage_generation_mwh",
        "retail_sales_mwh",
        "direct_use_mwh",
        "total_load_mwh",
        "wind_market_share_pct",
        "upv_market_share_pct",
    ]
    state_market = market.loc[market["state"] != "US", state_columns].rename(
        columns={
            "year": "eia_market_year",
            "state": "TSTATE",
            **{
                column: f"state_{column}"
                for column in state_columns
                if column not in {"year", "state"}
            },
        }
    )
    national_market = market.loc[market["state"] == "US", state_columns].drop(
        columns="state"
    ).rename(
        columns={
            "year": "eia_market_year",
            **{
                column: f"national_{column}"
                for column in state_columns
                if column not in {"year", "state"}
            },
        }
    )

    enriched = enriched.merge(
        state_market,
        on=["eia_market_year", "TSTATE"],
        how="left",
        validate="many_to_one",
    )
    enriched = enriched.merge(
        national_market,
        on="eia_market_year",
        how="left",
        validate="many_to_one",
    )

    is_wind = enriched["tech"].eq("wind-ons")
    enriched["state_tech_generation_mwh"] = np.where(
        is_wind,
        enriched["state_wind_generation_mwh"],
        enriched["state_upv_generation_mwh"],
    )
    enriched["state_market_share_pct"] = np.where(
        is_wind,
        enriched["state_wind_market_share_pct"],
        enriched["state_upv_market_share_pct"],
    )
    enriched["national_tech_generation_mwh"] = np.where(
        is_wind,
        enriched["national_wind_generation_mwh"],
        enriched["national_upv_generation_mwh"],
    )
    enriched["national_market_share_pct"] = np.where(
        is_wind,
        enriched["national_wind_market_share_pct"],
        enriched["national_upv_market_share_pct"],
    )

    drop_columns = [
        f"{scope}_{tech}_{metric}"
        for scope in ["state", "national"]
        for tech in ["wind", "upv"]
        for metric in ["generation_mwh", "market_share_pct"]
    ]
    enriched = enriched.drop(columns=drop_columns)
    enriched["eia_market_year"] = enriched["eia_market_year"].astype("Int64")
    return enriched


def capacity_weighted_annual_averages(
    frame: pd.DataFrame,
    x_column: str,
    lcoe_column: str,
    group_column: str,
) -> pd.DataFrame:
    average_data = frame[
        [
            group_column,
            lcoe_column,
            "summer_power_capacity_MW",
        ]
    ].copy()
    average_data["_x_value"] = frame[x_column]
    for column in [
        group_column,
        "_x_value",
        lcoe_column,
        "summer_power_capacity_MW",
    ]:
        average_data[column] = pd.to_numeric(average_data[column], errors="coerce")
    average_data = average_data.dropna()
    average_data = average_data[average_data["summer_power_capacity_MW"] > 0].copy()
    average_data["_weighted_lcoe"] = (
        average_data[lcoe_column]
        * average_data["summer_power_capacity_MW"]
    )

    annual = (
        average_data.groupby(group_column, as_index=False)
        .agg(
            x_value=("_x_value", "first"),
            weighted_lcoe_sum=("_weighted_lcoe", "sum"),
            total_capacity_mw=("summer_power_capacity_MW", "sum"),
            plant_count=(lcoe_column, "size"),
        )
        .sort_values(group_column)
    )
    annual["capacity_weighted_lcoe"] = (
        annual["weighted_lcoe_sum"] / annual["total_capacity_mw"]
    )
    return annual[
        [
            group_column,
            "x_value",
            "capacity_weighted_lcoe",
            "total_capacity_mw",
            "plant_count",
        ]
    ].reset_index(drop=True)


def calculate_linear_fit(
    frame: pd.DataFrame, x_column: str, y_column: str
) -> Optional[dict]:
    fit_data = frame[[x_column, y_column]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(fit_data) < 2 or fit_data[x_column].nunique() < 2:
        return None

    x_values = fit_data[x_column].to_numpy(dtype=float)
    y_values = fit_data[y_column].to_numpy(dtype=float)
    slope, intercept = np.polyfit(x_values, y_values, 1)
    predicted = slope * x_values + intercept
    residual_sum = np.sum((y_values - predicted) ** 2)
    total_sum = np.sum((y_values - np.mean(y_values)) ** 2)
    r_squared = np.nan if total_sum == 0 else 1 - residual_sum / total_sum
    return {
        "n": len(fit_data),
        "slope": slope,
        "intercept": intercept,
        "r_squared": r_squared,
        "x_min": float(np.min(x_values)),
        "x_max": float(np.max(x_values)),
    }


def format_coefficient(value: float) -> str:
    absolute_value = abs(value)
    if absolute_value >= 1000 or (0 < absolute_value < 0.01):
        return f"{value:.3e}"
    return f"{value:.3f}"


def format_equation(fit: dict) -> str:
    slope = format_coefficient(fit["slope"])
    intercept = format_coefficient(abs(fit["intercept"]))
    sign = "+" if fit["intercept"] >= 0 else "-"
    return f"y = {slope}x {sign} {intercept}"


def draw_fit(
    axis: plt.Axes,
    fit: Optional[dict],
    line_label: Optional[str],
    annotation_label: str,
    slope_units: str,
    color: str,
    annotation_y: float,
    fontsize: float = 8,
    linewidth: float = 2,
) -> None:
    if fit is None:
        annotation = f"{annotation_label}: fit unavailable"
    else:
        x_line = np.linspace(fit["x_min"], fit["x_max"], 100)
        y_line = fit["slope"] * x_line + fit["intercept"]
        axis.plot(
            x_line,
            y_line,
            color=color,
            linewidth=linewidth,
            label=line_label,
            zorder=4,
        )
        annotation = (
            f"{annotation_label}: {format_equation(fit)}\n"
            f"R^2={fit['r_squared']:.3f}; n={fit['n']:,}; "
            f"m units={slope_units}"
        )
    axis.text(
        0.03,
        annotation_y,
        annotation,
        transform=axis.transAxes,
        ha="left",
        va="top",
        fontsize=fontsize,
        bbox={"facecolor": "white", "alpha": 0.78, "edgecolor": "none"},
        zorder=6,
    )


def add_fit_record(
    records: list,
    scope: str,
    tech: str,
    state: str,
    lcoe_metric: str,
    x_column: str,
    slope_units: str,
    fit_source: str,
    fit: Optional[dict],
    fit_points: int,
    plant_rows: int = 0,
    total_capacity_mw: float = 0,
) -> None:
    record = {
        "scope": scope,
        "tech": tech,
        "state": state,
        "lcoe_metric": lcoe_metric,
        "x_variable": x_column,
        "slope_units": slope_units,
        "fit_source": fit_source,
        "n_fit_points": fit_points,
        "n_plant_rows": plant_rows,
        "total_capacity_mw": total_capacity_mw,
        "slope": np.nan,
        "intercept": np.nan,
        "r_squared": np.nan,
    }
    if fit is not None:
        record.update({key: fit[key] for key in ["slope", "intercept", "r_squared"]})
    records.append(record)


def plot_national_relationship(
    tech_data: pd.DataFrame,
    tech: str,
    lcoe_column: str,
    lcoe_label: str,
    group_column: str,
    x_column: str,
    x_label: str,
    x_scale: float,
    slope_units: str,
    output_path: Path,
    fit_records: list,
    supply_curve: Optional[pd.DataFrame] = None,
) -> None:
    plot_data = tech_data.copy()
    plot_data["_chart_x"] = pd.to_numeric(plot_data[x_column], errors="coerce") / x_scale
    figure, axis = plt.subplots(figsize=(8, 5.5))
    axis.scatter(
        plot_data["_chart_x"],
        plot_data[lcoe_column],
        s=18,
        alpha=0.35,
        color="#2878b5",
        edgecolors="none",
        label="Individual plant",
    )
    averages = capacity_weighted_annual_averages(
        plot_data,
        "_chart_x",
        lcoe_column,
        group_column,
    )
    axis.scatter(
        averages["x_value"],
        averages["capacity_weighted_lcoe"],
        s=48,
        alpha=0.95,
        color="#f28e2b",
        edgecolors="black",
        linewidths=0.45,
        zorder=3,
        label="Annual capacity-weighted average",
    )
    fit = calculate_linear_fit(averages, "x_value", "capacity_weighted_lcoe")
    draw_fit(
        axis,
        fit,
        "Fit of annual averages",
        "Existing avg fit",
        slope_units,
        "#c83e4d",
        0.97,
    )
    fit_x_column = x_column.replace("_mwh", "_twh") if x_scale == MWH_PER_TWH else x_column
    add_fit_record(
        fit_records,
        "national",
        tech,
        "US",
        lcoe_column,
        fit_x_column,
        slope_units,
        "annual_capacity_weighted_average",
        fit,
        len(averages),
        int(averages["plant_count"].sum()) if not averages.empty else 0,
        float(averages["total_capacity_mw"].sum()) if not averages.empty else 0,
    )

    if supply_curve is not None:
        maximum_generation_twh = pd.to_numeric(
            plot_data["_chart_x"], errors="coerce"
        ).max()
        rev_curve = build_cumulative_rev_curve(
            supply_curve,
            maximum_generation_twh,
            lcoe_column,
        )
        axis.plot(
            rev_curve["cumulative_generation_twh"],
            rev_curve[lcoe_column],
            color="#2a9d8f",
            linewidth=1.3,
            alpha=0.9,
            label="Raw reV supply curve",
            zorder=2,
        )
        rev_fit = calculate_linear_fit(
            rev_curve,
            "cumulative_generation_twh",
            lcoe_column,
        )
        draw_fit(
            axis,
            rev_fit,
            "Linear fit of reV supply curve",
            "reV curve fit",
            "($/MWh)/TWh",
            "#7b2cbf",
            0.77,
        )
        add_fit_record(
            fit_records,
            "national",
            tech,
            "US",
            lcoe_column,
            "cumulative_generation_twh",
            "($/MWh)/TWh",
            "rev_supply_curve",
            rev_fit,
            len(rev_curve),
        )
        if np.isfinite(maximum_generation_twh) and maximum_generation_twh > 0:
            axis.set_xlim(0, maximum_generation_twh * 1.02)

    relationship_label = f"{x_label[:1].lower()}{x_label[1:]}"
    axis.set_title(
        f"{tech}: reV {lcoe_label} vs {relationship_label} - national"
    )
    axis.set_xlabel(x_label)
    axis.set_ylabel(f"reV {lcoe_label} ($/MWh)")
    axis.grid(alpha=0.2)
    axis.legend(loc="upper right", fontsize=7.5)
    figure.tight_layout()
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def plot_state_relationship(
    tech_data: pd.DataFrame,
    tech: str,
    lcoe_column: str,
    lcoe_label: str,
    group_column: str,
    x_column: str,
    x_label: str,
    x_scale: float,
    slope_units: str,
    output_path: Path,
    fit_records: list,
    supply_curve: Optional[pd.DataFrame] = None,
) -> None:
    states = sorted(
        state
        for state in tech_data["TSTATE"].dropna().unique()
        if len(str(state)) == 2
    )
    columns = 4
    rows = int(np.ceil(len(states) / columns))
    figure, axes = plt.subplots(
        rows,
        columns,
        figsize=(16, max(4, 2.9 * rows)),
        sharey=True,
        squeeze=False,
    )
    for axis, state in zip(axes.flat, states):
        state_data = tech_data[tech_data["TSTATE"] == state].copy()
        state_data["_chart_x"] = (
            pd.to_numeric(state_data[x_column], errors="coerce") / x_scale
        )
        axis.scatter(
            state_data["_chart_x"],
            state_data[lcoe_column],
            s=13,
            alpha=0.4,
            color="#2878b5",
            edgecolors="none",
            label="Individual plant",
        )
        averages = capacity_weighted_annual_averages(
            state_data,
            "_chart_x",
            lcoe_column,
            group_column,
        )
        axis.scatter(
            averages["x_value"],
            averages["capacity_weighted_lcoe"],
            s=30,
            alpha=0.95,
            color="#f28e2b",
            edgecolors="black",
            linewidths=0.35,
            zorder=3,
            label="Annual capacity-weighted average",
        )
        fit = calculate_linear_fit(averages, "x_value", "capacity_weighted_lcoe")
        draw_fit(
            axis,
            fit,
            "Fit of annual averages",
            "Existing avg",
            slope_units,
            "#c83e4d",
            0.98,
            fontsize=6.2,
            linewidth=1.5,
        )
        fit_x_column = (
            x_column.replace("_mwh", "_twh")
            if x_scale == MWH_PER_TWH
            else x_column
        )
        add_fit_record(
            fit_records,
            "state",
            tech,
            state,
            lcoe_column,
            fit_x_column,
            slope_units,
            "annual_capacity_weighted_average",
            fit,
            len(averages),
            int(averages["plant_count"].sum()) if not averages.empty else 0,
            float(averages["total_capacity_mw"].sum()) if not averages.empty else 0,
        )

        x_values = pd.to_numeric(state_data["_chart_x"], errors="coerce").dropna()
        if supply_curve is not None:
            maximum_generation_twh = x_values.max() if not x_values.empty else np.nan
            rev_curve = build_cumulative_rev_curve(
                supply_curve,
                maximum_generation_twh,
                lcoe_column,
                state=state,
            )
            axis.plot(
                rev_curve["cumulative_generation_twh"],
                rev_curve[lcoe_column],
                color="#2a9d8f",
                linewidth=1.0,
                alpha=0.9,
                label="Raw reV supply curve",
                zorder=2,
            )
            rev_fit = calculate_linear_fit(
                rev_curve,
                "cumulative_generation_twh",
                lcoe_column,
            )
            draw_fit(
                axis,
                rev_fit,
                "Fit of reV supply curve",
                "reV curve",
                "($/MWh)/TWh",
                "#7b2cbf",
                0.76,
                fontsize=6.2,
                linewidth=1.3,
            )
            add_fit_record(
                fit_records,
                "state",
                tech,
                state,
                lcoe_column,
                "cumulative_generation_twh",
                "($/MWh)/TWh",
                "rev_supply_curve",
                rev_fit,
                len(rev_curve),
            )
            if np.isfinite(maximum_generation_twh) and maximum_generation_twh > 0:
                axis.set_xlim(0, maximum_generation_twh * 1.02)
        elif x_values.nunique() == 1:
            center = float(x_values.iloc[0])
            padding = 1.0 if x_column == "StartYear" else max(0.1, abs(center) * 0.05)
            axis.set_xlim(center - padding, center + padding)

        axis.set_title(
            f"{state} (plants={len(state_data):,}; avg={len(averages):,})",
            fontsize=9,
        )
        axis.grid(alpha=0.2)

    for axis in axes.flat[len(states) :]:
        axis.set_visible(False)
    for axis in axes[-1, :]:
        if axis.get_visible():
            axis.set_xlabel(x_label)
    for axis in axes[:, 0]:
        if axis.get_visible():
            axis.set_ylabel(f"reV {lcoe_label} ($/MWh)")

    relationship_label = f"{x_label[:1].lower()}{x_label[1:]}"
    figure.suptitle(
        f"{tech}: reV {lcoe_label} vs {relationship_label} - state panels",
        fontsize=15,
        y=0.998,
    )
    legend_lookup = {}
    for axis in axes.flat:
        axis_handles, axis_labels = axis.get_legend_handles_labels()
        for handle, label in zip(axis_handles, axis_labels):
            if label and label not in legend_lookup:
                legend_lookup[label] = handle
    legend_order = [
        "Individual plant",
        "Annual capacity-weighted average",
        "Fit of annual averages",
        "Raw reV supply curve",
        "Fit of reV supply curve",
    ]
    labels = [label for label in legend_order if label in legend_lookup]
    handles = [legend_lookup[label] for label in labels]
    if handles:
        figure.legend(
            handles,
            labels,
            loc="upper center",
            bbox_to_anchor=(0.5, 0.982),
            ncol=min(5, len(handles)),
            fontsize=7,
        )
    figure.tight_layout(rect=[0, 0, 1, 0.955])
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def create_charts(
    plants: pd.DataFrame,
    charts_dir: Path,
    lcoe_column: str,
    lcoe_label: str,
    supply_curves: Optional[dict] = None,
) -> list:
    charts_dir.mkdir(parents=True, exist_ok=True)
    fit_records = []
    output_paths = []
    supply_curves = supply_curves or {}
    chart_specs = [
        (
            "national_market_share_pct",
            "state_market_share_pct",
            "National generation market share (%)",
            "State generation market share (%)",
            "market_share",
            1,
            "($/MWh)/percentage point",
            False,
            "eia_market_year",
            True,
        ),
        (
            "national_tech_generation_mwh",
            "state_tech_generation_mwh",
            "National {technology} generation (TWh)",
            "State {technology} generation (TWh)",
            "generation",
            MWH_PER_TWH,
            "($/MWh)/TWh",
            True,
            "eia_market_year",
            True,
        ),
        (
            "StartYear",
            "StartYear",
            "Plant start year",
            "Plant start year",
            "year",
            1,
            "($/MWh)/year",
            False,
            "StartYear",
            False,
        ),
    ]

    for tech in ["wind-ons", "upv"]:
        tech_data = plants[plants["tech"] == tech].copy()
        safe_tech = tech.replace("-", "_")
        technology = "wind" if tech == "wind-ons" else "solar"
        for (
            national_x,
            state_x,
            national_label,
            state_label,
            suffix,
            x_scale,
            slope_units,
            include_supply_curve,
            group_column,
            require_market_year,
        ) in chart_specs:
            chart_data = tech_data
            if require_market_year:
                chart_data = tech_data[tech_data["eia_market_year"].notna()].copy()
            national_label = national_label.format(technology=technology)
            state_label = state_label.format(technology=technology)
            supply_curve = supply_curves.get(tech) if include_supply_curve else None
            national_output = charts_dir / f"{safe_tech}_national_lcoe_vs_{suffix}.png"
            plot_national_relationship(
                chart_data,
                tech,
                lcoe_column,
                lcoe_label,
                group_column,
                national_x,
                national_label,
                x_scale,
                slope_units,
                national_output,
                fit_records,
                supply_curve,
            )
            output_paths.append(national_output)

            state_output = charts_dir / f"{safe_tech}_state_lcoe_vs_{suffix}.png"
            plot_state_relationship(
                chart_data,
                tech,
                lcoe_column,
                lcoe_label,
                group_column,
                state_x,
                state_label,
                x_scale,
                slope_units,
                state_output,
                fit_records,
                supply_curve,
            )
            output_paths.append(state_output)

    fit_output = charts_dir / "linear_fit_statistics.csv"
    pd.DataFrame(fit_records).to_csv(fit_output, index=False)
    output_paths.append(fit_output)
    return output_paths


def main() -> None:
    args = parse_args()

    eia = read_eia(args.eia)
    wind_sc = read_supply_curve(args.wind_sc)
    upv_sc = read_supply_curve(args.upv_sc)
    generation = read_eia_generation(args.eia_state_generation)
    load = fetch_eia_load(args.eia_api_key)
    market = build_market_data(generation, load)

    available_market_years = market.loc[market["state"] == "US", "year"]
    if available_market_years.empty:
        raise ValueError("EIA market data does not contain national rows with state='US'.")
    maximum_market_year = int(available_market_years.max())
    future_record = eia["StartYear"] > maximum_market_year
    excluded_future_count = int(future_record.sum())
    eia = eia[~future_record].copy()

    wind_existing = eia[eia["tech"] == "wind-ons"]
    upv_existing = eia[eia["tech"] == "upv"]
    matched = pd.concat(
        [
            attach_nearest_rev_sites(wind_existing, wind_sc),
            attach_nearest_rev_sites(upv_existing, upv_sc),
        ],
        ignore_index=True,
    )
    enriched = attach_market_data(matched, market)

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(output_path, index=False)

    market_output_path = Path(args.market_data_out)
    market_output_path.parent.mkdir(parents=True, exist_ok=True)
    market.to_csv(market_output_path, index=False)

    chart_outputs = []
    if not args.no_charts:
        supply_curves = {
            "wind-ons": wind_sc,
            "upv": upv_sc,
        }
        chart_suites = [
            ("site_lcoe", "lcoe_site_usd_per_mwh", "site LCOE"),
            ("all_in_lcoe", "lcoe_all_in_usd_per_mwh", "all-in LCOE"),
        ]
        for directory, lcoe_column, lcoe_label in chart_suites:
            chart_outputs.extend(
                create_charts(
                    enriched,
                    Path(args.charts_dir) / directory,
                    lcoe_column,
                    lcoe_label,
                    supply_curves,
                )
            )

    out_of_range_count = int(enriched["eia_market_year_out_of_range"].sum())
    print(f"Wrote {len(enriched):,} rows to {output_path}")
    print(enriched["tech"].value_counts().to_string())
    print(
        f"Wrote EIA market data for {market['year'].min()}-{market['year'].max()} "
        f"to {market_output_path}"
    )
    print(
        f"Excluded {excluded_future_count:,} generator rows with StartYear after "
        f"{maximum_market_year}"
    )
    print(
        f"Retained {out_of_range_count:,} pre-{market['year'].min()} plant rows "
        "without market-year data"
    )
    if chart_outputs:
        chart_count = sum(path.suffix.lower() == ".png" for path in chart_outputs)
        statistics_count = sum(path.name == "linear_fit_statistics.csv" for path in chart_outputs)
        print(
            f"Wrote {chart_count} charts and {statistics_count} fit-statistics files "
            f"to {args.charts_dir}"
        )


if __name__ == "__main__":
    main()
