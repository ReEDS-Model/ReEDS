#!/usr/bin/env python3
"""Build the case-specific inputs for the PR100 1LM ReEDS mirror case.

This script only turns public PR100 data and explicitly documented proxies into
native ReEDS inputs.  It does not force the endogenous utility-scale renewable
portfolio to equal the published PR100 answer.  The published answer is staged
separately as a benchmark for post-solve comparison.
"""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

import h5py
import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
REEDS_PATH = HERE.parents[1]
OUTPUTS = HERE / "outputs"
DEFAULTS = OUTPUTS / "case_defaults"
NETWORK = OUTPUTS / "network_115plus"
MIRROR = OUTPUTS / "pr100_1LM_mirror"
PR100_ROOT = Path("/projects/aiplusinvest/pr100_all")
REV_ROOT = Path("/projects/aiplusinvest/pr100_rev")
CAPACITY_ARCHIVE = PR100_ROOT / "data" / "IntegratedCapacityInvestment.zip"
CAPACITY_MEMBER = "AnnualCapacities/energy_cap_1LM.csv"
SOLVE_YEARS = [2022, 2025, 2028, 2030, 2035, 2040, 2045, 2050]
MODEL_YEARS = [2010, *SOLVE_YEARS]


TECH_MAP = {
    "10hr Storage": "Battery Storage",
    "2hr Storage": "Battery Storage",
    "4hr Storage": "Battery Storage",
    "6hr Storage": "Battery Storage",
    "8hr Storage": "Battery Storage",
    "Biodiesel": "Liquid Fuel / Biodiesel",
    "Coal": "Coal",
    "Diesel": "Liquid Fuel / Biodiesel",
    "Distributed PV": "Distributed PV",
    "Fuel Oil No. 6": "Liquid Fuel / Biodiesel",
    "Hydropower": "Hydropower",
    "Land-based Wind": "Land-based Wind",
    "Landfill Gas": "Landfill Gas",
    "Natural Gas Combined Cycle": "Natural Gas",
    "Natural Gas Steam Turbine": "Natural Gas",
    "Offshore Wind": "Offshore Wind",
    "Planned Utility PV": "Utility PV",
    "Utility PV": "Utility PV",
}


def interpolate(anchors: dict[int, float], years=range(2022, 2051)) -> pd.Series:
    series = pd.Series(anchors, dtype=float).sort_index()
    return series.reindex(years).interpolate().bfill().ffill()


def read_official_capacity() -> pd.DataFrame:
    with zipfile.ZipFile(CAPACITY_ARCHIVE) as archive, archive.open(CAPACITY_MEMBER) as source:
        frame = pd.read_csv(source)
    frame = frame.rename(columns={
        "Technology": "pr100_technology",
        "Energy Capacity (MW)": "capacity_mw",
        "Year": "year",
    })
    frame = frame[["pr100_technology", "year", "capacity_mw"]].copy()
    frame["year"] = frame["year"].astype(int)
    frame["capacity_mw"] = frame["capacity_mw"].astype(float)
    frame["reeds_comparison_category"] = frame["pr100_technology"].map(TECH_MAP)
    if frame["reeds_comparison_category"].isna().any():
        missing = frame.loc[frame["reeds_comparison_category"].isna(), "pr100_technology"].unique()
        raise ValueError(f"Missing PR100-to-ReEDS capacity mappings: {missing}")
    return frame


def write_benchmarks(capacity: pd.DataFrame) -> None:
    capacity.to_csv(MIRROR / "official_capacity_1LM.csv", index=False)
    grouped = (
        capacity.groupby(["reeds_comparison_category", "year"], as_index=False)
        ["capacity_mw"].sum()
    )
    grouped.to_csv(MIRROR / "official_capacity_1LM_reeds_groups.csv", index=False)


def write_distpv_inputs(capacity: pd.DataFrame) -> dict[str, object]:
    source = pd.read_csv(DEFAULTS / "distributed_pv.csv")
    source = source.loc[source["year"].isin(SOLVE_YEARS)]
    wide = source.pivot_table(index="region", columns="year", values="capacity_mw", aggfunc="sum")
    wide = wide.reindex(columns=SOLVE_YEARS).fillna(0.0)
    archive_totals = wide.sum()
    engage_totals = (
        capacity.loc[capacity["pr100_technology"] == "Distributed PV"]
        .set_index("year")["capacity_mw"].reindex(SOLVE_YEARS)
    )
    # The published Engage baseline omits existing DPV (0 MW in 2022), while
    # the DER archive contains 450.793 MW.  Retain the DER baseline, then use
    # the final Engage totals in every investment year.
    targets = engage_totals.copy()
    targets.loc[2022] = archive_totals.loc[2022]
    for year in SOLVE_YEARS:
        if archive_totals.loc[year] <= 0:
            raise ValueError(f"No DER spatial weights for {year}")
        wide[year] *= targets.loc[year] / archive_totals.loc[year]
    # Write every calendar year because WriteHintage consumes the full DPV
    # history before it subsets to ReEDS solve years.  Hold the observed 2022
    # baseline backward to the required 2010 bookkeeping year and linearly
    # interpolate between the eight published PR100 capacity years.
    wide[2010] = wide[2022]
    wide = (
        wide.reindex(columns=range(2010, 2051))
        .interpolate(axis=1)
        .bfill(axis=1)
        .ffill(axis=1)
    )
    wide.index.name = "r"
    destination = REEDS_PATH / "inputs" / "dgen_model_inputs" / "pr100_1LM"
    destination.mkdir(parents=True, exist_ok=True)
    wide.to_csv(destination / "distpvcap_pr100_1LM.csv")
    audit = pd.DataFrame({
        "year": SOLVE_YEARS,
        "der_archive_mw": archive_totals.reindex(SOLVE_YEARS).values,
        "engage_capacity_output_mw": engage_totals.reindex(SOLVE_YEARS).values,
        "forced_reeds_mw": wide.sum().reindex(SOLVE_YEARS).values,
    })
    audit.to_csv(MIRROR / "distpv_total_reconciliation.csv", index=False)
    return {
        "forced_mw": {str(year): float(wide[year].sum()) for year in SOLVE_YEARS},
        "method": "2022 DER archive baseline; 2025-2050 final Engage totals distributed using DER archive spatial shares",
    }


def write_distpv_profile() -> dict[str, object]:
    """Create a regional DPV proxy from the registered PR100 UPV profiles."""
    supply = pd.read_csv(
        REEDS_PATH / "inputs" / "supply_curve"
        / "supplycurve_upv-pr100-moderate-limited-35.csv"
    )
    profile_path = (
        REEDS_PATH / "inputs" / "profiles_cf"
        / "cf_upv_pr100-moderate-limited-35.h5"
    )
    regions = pd.read_csv(NETWORK / "regions.csv").set_index("r")
    destination = REEDS_PATH / "inputs" / "profiles_cf" / "cf_distpv_pr100_1LM.h5"
    with h5py.File(profile_path, "r") as source:
        gids = [int(value) for value in source["columns"][:]]
        gid_index = {gid: index for index, gid in enumerate(gids)}
        supply = supply.loc[supply["sc_point_gid"].isin(gid_index)].copy()
        source_regions = sorted(supply["region"].unique())
        nearest = {}
        for region in regions.index:
            if region in source_regions:
                nearest[region] = region
                continue
            point = regions.loc[region, ["latitude", "longitude"]].astype(float)
            candidates = regions.loc[source_regions, ["latitude", "longitude"]].astype(float)
            distance2 = (candidates["latitude"] - point["latitude"]) ** 2 + (
                candidates["longitude"] - point["longitude"]
            ) ** 2
            nearest[region] = str(distance2.idxmin())

        with h5py.File(destination, "w") as output:
            output.create_dataset("columns", data=np.asarray(regions.index, dtype="S20"))
            output.attrs["source"] = "capacity-weighted PR100 utility-PV profile proxy"
            output.attrs["caveat"] = "PR100 public data do not include nodal rooftop-PV profiles"
            for key in source:
                if not key.startswith("cf_profile_"):
                    continue
                raw = np.asarray(source[key][:], dtype=float)
                by_source_region = {}
                for region, rows in supply.groupby("region"):
                    indices = [gid_index[int(gid)] for gid in rows["sc_point_gid"]]
                    weights = rows["capacity"].to_numpy(dtype=float)
                    by_source_region[str(region)] = np.average(raw[:, indices], axis=1, weights=weights)
                matrix = np.column_stack([
                    by_source_region[nearest[str(region)]] for region in regions.index
                ])
                output.create_dataset(key, data=matrix, compression="gzip", compression_opts=4)
    return {
        "path": str(destination),
        "regions": int(len(regions)),
        "native_profile_regions": int(len(source_regions)),
        "nearest_profile_proxy_regions": int(len(regions) - len(source_regions)),
    }


def write_policy_inputs() -> None:
    annual = pd.DataFrame({"t": range(2010, 2051)})
    annual["st"] = "PR"
    annual["rps_all"] = annual["t"].map(
        lambda year: 0.0 if year < 2025 else (
            0.40 if year < 2040 else (0.60 if year < 2050 else 1.00)
        )
    )
    annual["rps_solar"] = 0.0
    annual["rps_wind"] = 0.0
    annual.to_csv(MIRROR / "rps_fraction.csv", index=False)
    pd.DataFrame([["PR", "RPS_All", 1]], columns=["*st", "RPSCat", "val"]).to_csv(
        MIRROR / "acp_disallowed.csv", index=False
    )
    pd.DataFrame([["PR", "RPS_All", 2]], columns=["*st", "RPSCat", "style"]).to_csv(
        MIRROR / "recstyle.csv", index=False
    )
    pd.DataFrame([["PR", 1]], columns=["st", "PR"]).to_csv(
        MIRROR / "rectable.csv", index=False
    )
    pd.DataFrame([["PR", 1.0, 1.0]], columns=["st", "RPS_All", "CES"]).to_csv(
        MIRROR / "hydrofrac_policy.csv", index=False
    )
    pd.DataFrame([["PR", 0.0]], columns=["*st", "value"]).to_csv(
        MIRROR / "oosfrac.csv", index=False
    )
    years = list(range(2010, 2051))
    pd.DataFrame([["PR", *([0.0] * len(years))]], columns=["st", *years]).to_csv(
        MIRROR / "acp_prices.csv", index=False
    )


def weighted_mean(path: Path, value: str) -> float:
    frame = pd.read_csv(path)
    return float(np.average(frame[value], weights=frame["capacity"]))


def annual_rev_costs(prefix: str, years: list[int], cap_col: str, fom_col: str) -> pd.DataFrame:
    records = []
    for year in years:
        path = REV_ROOT / f"{prefix}_{str(year)[-2:]}_supply-curve.csv"
        records.append({
            "source_year": year,
            "capcost": weighted_mean(path, cap_col),
            "fom": weighted_mean(path, fom_col),
        })
    return pd.DataFrame(records).set_index("source_year")


def reindex_costs(source: pd.DataFrame, hold_after: bool = False) -> pd.DataFrame:
    years = range(2010, 2051)
    output = source.reindex(years).interpolate()
    if hold_after:
        output = output.ffill()
    return output.bfill().ffill()


def write_technology_costs() -> dict[str, object]:
    """Write annual real-2021 cost inputs calibrated to published PR100 values.

    The public Engage workbook is not released.  The annual shape is therefore
    taken from the public PR100 reV/ATB inputs and normalized to the published
    PR100 first-availability cost reported in NREL/TP-6A20-88384.
    """
    upv_raw = annual_rev_costs(
        "upv_fixed_moderate_limited", [2022, 2030, 2035, 2040, 2045, 2050],
        "mean_capital_cost", "mean_fixed_operating_cost",
    )
    upv = reindex_costs(upv_raw)
    upv.loc[:, "capcost"] *= 1657.0 / upv.loc[2025, "capcost"]
    upv.loc[:, "fom"] *= 29.09 / upv.loc[2025, "fom"]
    upv["vom"] = 0.0
    upv["cf_improvement"] = 1.0
    upv.reset_index(names="t").to_csv(
        REEDS_PATH / "inputs" / "plant_characteristics" / "upv_PR100_1LM.csv", index=False
    )

    onshore_raw = annual_rev_costs(
        "wind_onshore_limited", [2022, 2030, 2035], "capex_per_kw", "opex_per_kw"
    )
    onshore = reindex_costs(onshore_raw, hold_after=True)
    onshore.loc[:, "capcost"] *= 3772.0 / onshore.loc[2025, "capcost"]
    onshore.loc[:, "fom"] *= 98.51 / onshore.loc[2025, "fom"]
    pd.DataFrame({
        "Turbine": "PR100",
        "Year": onshore.index,
        "CF_mult": 1.0,
        "Overnight Cap Cost $/kW": onshore["capcost"].values,
        "Fixed O&M $/(kW-yr)": onshore["fom"].values,
        "Var O&M $/MWh": 0.0,
    }).to_csv(
        REEDS_PATH / "inputs" / "plant_characteristics" / "ons-wind_PR100_1LM.csv",
        index=False,
    )

    offshore_raw = annual_rev_costs(
        "wind_offshore", [2030, 2035], "capex_per_kw", "opex_per_kw"
    )
    offshore = reindex_costs(offshore_raw, hold_after=True)
    offshore.loc[:, "capcost"] *= 4690.0 / offshore.loc[2035, "capcost"]
    offshore.loc[:, "fom"] *= 144.60 / offshore.loc[2035, "fom"]
    pd.DataFrame({
        "Turbine": "fixed",
        "Year": offshore.index,
        "CF_mult": 1.0,
        "Overnight Cap Cost $/kW": offshore["capcost"].values,
        "Fixed O&M $/(kW-yr)": offshore["fom"].values,
        "Var O&M $/MWh": 0.0,
        "rsc_mult": 1.0,
    }).to_csv(
        REEDS_PATH / "inputs" / "plant_characteristics" / "ofs-wind_PR100_1LM.csv",
        index=False,
    )

    battery_source = pd.read_csv(
        REEDS_PATH / "inputs" / "plant_characteristics" / "battery_ATB_2024_moderate.csv"
    ).drop(columns="i").set_index("t").reindex(range(2010, 2051)).interpolate().bfill().ffill()
    battery = battery_source.copy()
    for column, target in {
        "capcost": 672.90,
        "capcost_energy": 644.10,
        "fom": 16.8125,
        "fom_energy": 18.11875,
    }.items():
        battery[column] *= target / battery.loc[2025, column]
    battery["rte"] = 0.85
    battery.insert(0, "i", "battery_li")
    battery.reset_index(names="t").to_csv(
        REEDS_PATH / "inputs" / "plant_characteristics" / "battery_PR100_1LM.csv",
        index=False,
    )

    audit = pd.concat({
        "upv": upv[["capcost", "fom"]],
        "wind-ons": onshore[["capcost", "fom"]],
        "wind-ofs": offshore[["capcost", "fom"]],
    }, names=["technology", "year"]).reset_index()
    audit.to_csv(MIRROR / "annual_renewable_costs_2021usd.csv", index=False)
    return {
        "basis": "real 2021 USD",
        "annual_shape": "public PR100 reV cost trajectories",
        "normalization": "published PR100 first-availability costs",
        "onshore_after_2035": "held at 2035 because later public PR100 curves were not released",
        "offshore_after_2035": "held at 2035 because later public PR100 curves were not released",
        "battery": "ATB annual shape normalized to published PR100 2025 power/energy/FOM values",
    }


def write_pr100_incentives() -> dict[str, object]:
    """Write the report's explicit ITC path without ReEDS IRA/OBBBA bonuses.

    PR100 used a 30% ITC through 2033 and reduced it to zero by the end of
    2035.  A 15% 2034 midpoint is the transparent linear interpretation; the
    2035 and later rows are zero.  Safe harbor and tax-equity penalties are
    disabled because those values are not published in the Engage inputs.
    """
    columns = [
        "i", "country", "t_start_construction", "safe_harbor", "t_max_online",
        "ptc_value", "ptc_perc_bonus", "ptc_dur", "ptc_tax_equity_penalty",
        "itc_frac", "itc_energy_comm_bonus", "itc_percpt_domestic_bonus",
        "itc_tax_equity_penalty", "co2_capture_value", "co2_capture_dur",
        "co2_capture_tax_equity_penalty", "h2_ptc_value", "h2_ptc_dur",
        "h2_ptc_tax_equity_penalty",
    ]
    rows = []
    for technology in ["PV", "ONSWIND", "OFSWIND", "BATTERY"]:
        for year in range(2010, 2051):
            itc = 0.30 if year <= 2033 else (0.15 if year == 2034 else 0.0)
            rows.append([
                technology, "usa", year, 0, year,
                0.0, 0.0, 0, 0.0,
                itc, 0.0, 0.0, 0.0,
                0.0, 0, 0.0, 0.0, 0, 0.0,
            ])
    destination = (
        REEDS_PATH / "inputs" / "financials" / "incentives_PR100_1LM.csv"
    )
    pd.DataFrame(rows, columns=columns).to_csv(destination, index=False)
    return {
        "technologies": ["PV", "ONSWIND", "OFSWIND", "BATTERY"],
        "itc": "30% through 2033, 15% in 2034, 0% from 2035",
        "ptc": "none",
        "safe_harbor_and_tax_equity_penalty": (
            "zero because PR100 PPOA values are proprietary"
        ),
    }


def allocate(total: float, candidates: pd.DataFrame) -> pd.DataFrame:
    candidates = candidates.loc[candidates["region"].notna() & (candidates["capacity_mw"] > 0)].copy()
    if candidates.empty:
        raise ValueError("No spatial candidates for PR100 capacity allocation")
    weights = candidates.groupby("region")["capacity_mw"].sum()
    weights /= weights.sum()
    return weights.mul(total).rename("capacity_mw").reset_index()


def build_unit_database(capacity: pd.DataFrame) -> dict[str, object]:
    template_path = (
        REEDS_PATH / "inputs" / "capacity_exogenous"
        / "ReEDS_generator_database_final_EIA-NEMS.csv"
    )
    templates = pd.read_csv(template_path, low_memory=False)
    regions = pd.read_csv(NETWORK / "regions.csv").set_index("r")
    keys = pd.read_csv(DEFAULTS / "pr_explicit_region_keys.csv")
    fips = dict(zip(keys["r"], "p" + keys["synthetic_fips"].astype(str)))
    assets = pd.read_csv(NETWORK / "assets.csv", low_memory=False)
    upv_supply = pd.read_csv(
        REEDS_PATH / "inputs" / "supply_curve"
        / "supplycurve_upv-pr100-moderate-limited-35.csv"
    )
    wind_supply = pd.read_csv(
        REEDS_PATH / "inputs" / "supply_curve"
        / "supplycurve_wind-ons-pr100-moderate-limited-35.csv"
    )
    records = []
    provenance = []
    retirement_columns = [column for column in templates if "RetireYear" in column]
    official_table = capacity.pivot(
        index="pr100_technology", columns="year", values="capacity_mw"
    )

    def official(technology: str, year: int) -> float:
        return float(official_table.loc[technology, year])

    def nearest_site(supply: pd.DataFrame, region: str) -> pd.Series:
        same = supply.loc[supply["region"] == region]
        if len(same):
            return same.sort_values("capacity", ascending=False).iloc[0]
        point = regions.loc[region, ["latitude", "longitude"]].astype(float)
        candidate_regions = regions.loc[supply["region"].unique(), ["latitude", "longitude"]]
        distance2 = (candidate_regions["latitude"] - point["latitude"]) ** 2 + (
            candidate_regions["longitude"] - point["longitude"]
        ) ** 2
        donor_region = str(distance2.idxmin())
        return supply.loc[supply["region"] == donor_region].sort_values("capacity", ascending=False).iloc[0]

    def nearest_resource_region(supply: pd.DataFrame, region: str) -> str:
        if region in set(supply["region"]):
            return region
        point = regions.loc[region, ["latitude", "longitude"]].astype(float)
        candidates = regions.loc[supply["region"].unique(), ["latitude", "longitude"]]
        distance2 = (candidates["latitude"] - point["latitude"]) ** 2 + (
            candidates["longitude"] - point["longitude"]
        ) ** 2
        return str(distance2.idxmin())

    def add(
        source_id: str,
        source_kind: str,
        tech: str,
        region: str,
        mw: float,
        start: int,
        retire: int,
        duration: float | None = None,
    ) -> None:
        if mw <= 1e-8:
            return
        matches = templates.loc[templates["tech"].str.lower() == tech.lower()]
        if matches.empty:
            raise ValueError(f"No unit template for {tech}")
        row = matches.iloc[0].copy()
        row["tech"] = tech
        row["summer_power_capacity_MW"] = mw
        row["TC_WIN"] = mw
        row["StartYear"] = start
        row["IsExistUnit"] = start < 2010
        for column in retirement_columns:
            row[column] = retire
        row["RetireYearGiven"] = True
        row["FIPS"] = fips[region]
        row["county"] = "Puerto Rico"
        row["TSTATE"] = "PR"
        row["T_LONG"] = regions.loc[region, "longitude"]
        row["T_LAT"] = regions.loc[region, "latitude"]
        row["r"] = region
        row["T_PID"] = source_id[:50]
        row["T_UID"] = source_id[:50]
        row["Unique ID"] = source_id
        if duration is not None:
            row["energy_capacity_MWh"] = mw * duration
            row["battery_duration"] = duration
        else:
            row["energy_capacity_MWh"] = np.nan
            row["battery_duration"] = np.nan
        if tech in {"upv", "wind-ons"}:
            site = nearest_site(upv_supply if tech == "upv" else wind_supply, region)
            row["sc_point_gid"] = int(site["sc_point_gid"])
            row["reV_capacity_factor_ac"] = float(site["cf"])
        else:
            row["sc_point_gid"] = pd.NA
            row["reV_capacity_factor_ac"] = np.nan
        records.append(row)
        provenance.append({
            "source_id": source_id, "source_kind": source_kind, "tech": tech,
            "region": region, "capacity_mw": mw, "start_year": start,
            "retire_year": retire, "duration_hours": duration,
        })

    thermal = assets.loc[assets["asset_type"] == "ThermalStandard"].copy()
    fuel_candidates = {
        "coal": thermal.loc[thermal["fuel"] == "COAL"],
        "diesel": thermal.loc[thermal["fuel"] == "DISTILLATE_FUEL_OIL"],
        "fuel_oil": thermal.loc[thermal["fuel"] == "RESIDUAL_FUEL_OIL"],
        "natural_gas": thermal.loc[thermal["fuel"] == "NATURAL_GAS"],
    }
    tranches = [
        ("coal", "coaloldscr", official("Coal", 2022), 2009, 2028),
        ("diesel", "gas-ct", official("Diesel", 2022) - official("Diesel", 2025), 2009, 2025),
        ("diesel", "gas-ct", official("Diesel", 2028) - official("Diesel", 2030), 2009, 2030),
        ("diesel", "gas-ct", official("Diesel", 2030), 2009, 2050),
        ("fuel_oil", "o-g-s", official("Fuel Oil No. 6", 2022) - official("Fuel Oil No. 6", 2025), 2009, 2025),
        ("fuel_oil", "o-g-s", official("Fuel Oil No. 6", 2025), 2009, 2028),
        ("natural_gas", "gas-cc", official("Natural Gas Combined Cycle", 2022) + official("Natural Gas Steam Turbine", 2022), 2009, 2050),
        ("natural_gas", "gas-cc", official("Natural Gas Combined Cycle", 2025) - official("Natural Gas Combined Cycle", 2022), 2025, 2050),
    ]
    for group, tech, total, start, retire in tranches:
        for item in allocate(total, fuel_candidates[group]).itertuples(index=False):
            add(
                f"PR100_{group}_{start}_{retire}_{item.region}",
                f"official_PR100_{group}", tech, str(item.region),
                float(item.capacity_mw), start, retire,
            )

    # The public PR100 annual output is authoritative for these aggregate values.
    # The capacity CSV reports hydro as zero after 2022, but Section 8.2.6.1.6
    # of the final report explicitly says Engage retained 10 MW throughout the
    # PR100 horizon.  Use the documented model assumption and leave the raw CSV
    # untouched in the benchmark so the discrepancy remains visible.
    add(
        "PR100_HYDRO_2022", "PR100_report_10MW_hydro_throughout_horizon",
        "hydED", "pr169", official("Hydropower", 2022), 2009, 2051,
    )
    add("PR100_LFG_2022", "official_PR100_landfill_gas", "lfill-gas", "pr63", official("Landfill Gas", 2022), 2009, 2051)
    wind_region = nearest_resource_region(wind_supply, "pr8")
    add(
        "PR100_WIND_2022", "official_PR100_existing_wind_nearest_valid_resource_region",
        "wind-ons", wind_region, official("Land-based Wind", 2022), 2009, 2051,
    )
    add("PR100_UPV_2022", "official_PR100_existing_planned_pv", "upv", "pr8", official("Planned Utility PV", 2022), 2009, 2051)

    tranche = pd.read_csv(DEFAULTS / "committed_tranche1_solar.csv")
    planned_addition = official("Planned Utility PV", 2025) - official("Planned Utility PV", 2022)
    scale = planned_addition / tranche["capacity_mw"].sum()
    for item in tranche.itertuples(index=False):
        add(
            f"TRANCHE1_{item.project_id}", "PR100_Tranche1_and_17MW_reconciliation",
            "upv", str(item.region), float(item.capacity_mw) * scale, 2025, 2051,
        )

    storage_regions = (
        tranche.groupby("region")["capacity_mw"].sum().div(tranche["capacity_mw"].sum())
    )
    storage_builds = [
        ("Tranche1_4h_2025", official("4hr Storage", 2025), 2025, 4.0),
        ("Tranche1_4h_2028", official("4hr Storage", 2028) - official("4hr Storage", 2025), 2028, 4.0),
        ("RA_10h_2025", official("10hr Storage", 2025), 2025, 10.0),
        ("RA_10h_2030", official("10hr Storage", 2030) - official("10hr Storage", 2028), 2030, 10.0),
        ("RA_10h_2045", official("10hr Storage", 2045) - official("10hr Storage", 2040), 2045, 10.0),
        ("RA_10h_2050", official("10hr Storage", 2050) - official("10hr Storage", 2045), 2050, 10.0),
    ]
    for label, total, year, duration in storage_builds:
        for region, weight in storage_regions.items():
            add(
                f"PR100_{label}_{region}", "official_PR100_storage_prescription",
                "battery_li", str(region), total * float(weight), year, 2051, duration,
            )
    add(
        "PR100_RA_BIODIESEL_2050", "official_PR100_RA_biodiesel_proxy",
        "o-g-s", "pr106", official("Biodiesel", 2050), 2050, 2051,
    )

    unitdata = pd.DataFrame(records)
    ordered = list(templates.columns) + [
        column for column in ["r", "sc_point_gid", "reV_capacity_factor_ac"]
        if column not in templates.columns
    ]
    unitdata = unitdata.reindex(columns=ordered)
    destination = (
        REEDS_PATH / "inputs" / "capacity_exogenous"
        / "ReEDS_generator_database_final_PR100-1LM.csv"
    )
    unitdata.to_csv(destination, index=False)
    provenance_frame = pd.DataFrame(provenance)
    provenance_frame.to_csv(MIRROR / "unitdata_provenance.csv", index=False)
    return {
        "path": str(destination),
        "rows": int(len(unitdata)),
        "capacity_mw": float(unitdata["summer_power_capacity_MW"].sum()),
        "spatial_method": "source-unit proportional allocation; published aggregate totals",
        "technology_proxies": {
            "diesel": "gas-ct with DFO price",
            "fuel_oil_and_2050_biodiesel": "o-g-s with RFO/B100 price trajectory",
            "natural_gas_cc_and_steam": "gas-cc aggregate",
        },
    }


def write_fuel_prices() -> None:
    # Public PR100 Figure 132 is the only released fuel-price trajectory.  These
    # anchors are digitized in 2021 real $/MMBtu and are intentionally labeled
    # approximate rather than presented as proprietary LUMA source values.
    anchors = {
        "coal": {2022: 3.7, 2025: 3.7, 2050: 3.7},
        "naturalgas": {2022: 11.3, 2025: 11.5, 2030: 12.1, 2040: 13.0, 2050: 12.7},
        "dfo": {2022: 24.0, 2025: 24.0, 2028: 22.8, 2030: 23.0, 2040: 24.4, 2050: 25.8},
        "rfo": {2022: 19.2, 2025: 19.5, 2030: 20.1, 2040: 21.4, 2049: 22.6, 2050: 41.0},
    }
    rows = []
    for fuel, values in anchors.items():
        for year, value in interpolate(values, range(2010, 2051)).items():
            rows.append({
                "t": int(year), "fuel": fuel, "cost_2021_per_mmbtu": float(value),
                "source": "digitized NREL/TP-6A20-88384 Figure 132",
                "quality": "approximate_public_figure",
            })
    pd.DataFrame(rows).to_csv(MIRROR / "fuel_prices.csv", index=False)


def write_transmission_inputs() -> dict[str, object]:
    screening = pd.read_csv(NETWORK / "interfaces_screening.csv")
    current = pd.read_csv(DEFAULTS / "interfaces_itl.csv")
    branches = pd.read_csv(NETWORK / "branch_to_region.csv")
    boundary = branches.loc[
        branches["is_region_boundary"].astype(str).str.lower().eq("true")
        & branches["rate_mw_assuming_system_base"].notna()
        & ~branches["suspect_unlimited_rating"].astype(str).str.lower().eq("true")
        & (branches["rate_mw_assuming_system_base"] > 0)
    ].copy()
    boundary["r"] = boundary[["from_region", "to_region"]].min(axis=1)
    boundary["rr"] = boundary[["from_region", "to_region"]].max(axis=1)
    boundary["loss_mw_at_rating"] = (
        (boundary["rate_mw_assuming_system_base"] / 100.0) ** 2
        * boundary["r_pu"].clip(lower=0) * 100.0
    )
    grouped = boundary.groupby(["r", "rr"]).agg(
        MW=("rate_mw_assuming_system_base", "sum"),
        loss_mw=("loss_mw_at_rating", "sum"),
        branch_count=("branch_uuid", "size"),
    ).reset_index()
    grouped["loss"] = (grouped["loss_mw"] / grouped["MW"]).clip(0, 0.20)
    output = screening[["r", "rr"]].merge(grouped, on=["r", "rr"], how="left")
    fallback = current[["r", "rr", "MW_forward"]].rename(columns={"MW_forward": "fallback_mw"})
    output = output.merge(fallback, on=["r", "rr"], how="left")
    output["method"] = np.where(
        output["MW"].notna(), "sum_of_boundary_continuous_ratings", "N0_TTC_fallback_no_rated_boundary"
    )
    output["MW"] = output["MW"].fillna(output["fallback_mw"])
    output["loss"] = output["loss"].fillna(0.0)
    destination = output[["r", "rr", "MW", "loss", "branch_count", "method"]].copy()
    destination["branch_count"] = destination["branch_count"].fillna(0).astype(int)
    destination.to_csv(MIRROR / "interfaces_itl_pr100.csv", index=False)
    return {
        "interfaces": int(len(destination)),
        "summed_rating_interfaces": int((destination["method"] == "sum_of_boundary_continuous_ratings").sum()),
        "fallback_interfaces": int((destination["method"] != "sum_of_boundary_continuous_ratings").sum()),
        "loss_method": "rated-current I^2R loss divided by aggregate interface MW",
        "expansion": "disabled in the case via GSw_TransRestrict=r",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    MIRROR.mkdir(parents=True, exist_ok=True)
    capacity = read_official_capacity()
    write_benchmarks(capacity)
    qa = {
        "scenario": "PR100 1LM",
        "solve_years": SOLVE_YEARS,
        "official_capacity_rows": int(len(capacity)),
        "distpv": write_distpv_inputs(capacity),
        "distpv_profile": write_distpv_profile(),
        "technology_costs": write_technology_costs(),
        "incentives": write_pr100_incentives(),
    }
    write_policy_inputs()
    write_fuel_prices()
    qa["unit_database"] = build_unit_database(capacity)
    qa["transmission"] = write_transmission_inputs()
    qa["known_non_exact_inputs"] = [
        "PR100 Engage/LUMA unit-level fleet and future PPOA workbooks are not public.",
        "Fuel prices are digitized from the public PR100 report figure.",
        "Distributed PV uses a regional PR100 utility-PV profile proxy.",
        "ReEDS uses one static 2035 resource/profile topology; public PR100 annual costs are applied by year.",
        "PR100 NG steam and NGCC are aggregated to ReEDS gas-cc.",
        "The report retains 10 MW hydro through 2050, while the public capacity CSV reports zero after 2022; the model follows the report and the benchmark remains untouched.",
        "PRAS validation uses ReEDS static outage inputs because PR100 event-level outage draws are not public.",
    ]
    (MIRROR / "qa.json").write_text(json.dumps(qa, indent=2) + "\n")
    print(json.dumps(qa, indent=2))


if __name__ == "__main__":
    main()
