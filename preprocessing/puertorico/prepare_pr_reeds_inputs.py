#!/usr/bin/env python3
"""Build native ReEDS supply-curve and provisional unit-database inputs for PR_explicit.

The source-network renewable and storage components include scenario builds and are
therefore not treated as existing capacity. Existing distributed PV/storage come
from the PR100 2022 trajectory, and committed Tranche 1 solar is prescribed in 2025.
Thermal and hydro records are restricted to source components with both status and
available set to true. Generator engineering/economic fields not present in the
Puerto Rico source are inherited from same-technology EIA-NEMS template records;
the QA output makes that provisional assumption explicit.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import h5py
import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
REEDS_PATH = HERE.parents[1]
STAGING = HERE / "outputs"
NETWORK = STAGING / "network_115plus"
DEFAULTS = STAGING / "case_defaults"
SUPPLY = STAGING / "pr100_moderate_limited_2035"
SCENARIO = "pr100-moderate-limited-35"
BASE_CASE = Path("/projects/aiplusinvest/base_case")
BASE_CASE_JSON = BASE_CASE / "ebb45e39-4c77-4115-b183-b001079430f1.json"
BASE_CASE_H5 = BASE_CASE / "ebb45e39-4c77-4115-b183-b001079430f1_time_series_storage.h5"


def as_bool(series: pd.Series) -> pd.Series:
    """Interpret source booleans without treating the string 'False' as true."""
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def build_region_tables() -> tuple[pd.DataFrame, dict[str, str]]:
    regions = pd.read_csv(NETWORK / "regions.csv").set_index("r")
    keys = pd.read_csv(DEFAULTS / "pr_explicit_region_keys.csv")
    fips = dict(zip(keys["r"], "p" + keys["synthetic_fips"].astype(str)))
    if set(regions.index) != set(fips):
        raise ValueError("Region keys and >=115-kV region table do not agree")
    return regions, fips


def required_upv_capacity_by_region() -> pd.Series:
    dpv = (
        pd.read_csv(DEFAULTS / "distributed_pv.csv")
        .query("year == 2022 and capacity_mw > 0")
        .groupby("region")["capacity_mw"].sum()
    )
    tranche1 = (
        pd.read_csv(DEFAULTS / "committed_tranche1_solar.csv")
        .groupby("region")["capacity_mw"].sum()
    )
    return dpv.add(tranche1, fill_value=0).rename("required_capacity_mw")


def build_supply_curves(
    regions: pd.DataFrame,
    fips: dict[str, str],
) -> tuple[
    dict[str, dict[str, object]],
    dict[str, pd.DataFrame],
    dict[str, dict[int, int]],
]:
    """Write fully assembled curves so ReEDS never invokes the CONUS site map."""
    destinations = REEDS_PATH / "inputs" / "supply_curve"
    destinations.mkdir(parents=True, exist_ok=True)
    summaries: dict[str, dict[str, object]] = {}
    expanded: dict[str, pd.DataFrame] = {}
    clone_maps: dict[str, dict[int, int]] = {}
    for tech in ["upv", "wind-ons", "wind-ofs"]:
        source = pd.read_csv(SUPPLY / f"supplycurve_{tech}.csv")
        if not set(source["region"]).issubset(fips):
            missing = sorted(set(source["region"]) - set(fips))
            raise ValueError(f"{tech} supply curve contains unknown regions: {missing}")
        clone_map: dict[int, int] = {}
        clone_audit: list[dict[str, object]] = []
        if tech == "upv":
            required = required_upv_capacity_by_region()
            next_gid = int(source["sc_point_gid"].max()) + 1
            clones: list[pd.Series] = []
            for region, capacity in required.items():
                if region in set(source["region"]):
                    continue
                donor = nearest_site(source, str(region), regions).copy()
                donor_gid = int(donor["sc_point_gid"])
                donor["sc_point_gid"] = next_gid
                donor["region"] = str(region)
                donor["capacity"] = float(capacity)
                donor["poi_bus"] = int(regions.loc[region, "bus_number"])
                donor["poi_name"] = str(regions.loc[region, "bus_name"])
                donor["poi_kv"] = float(regions.loc[region, "base_kv"])
                donor["mapping_method"] = "exogenous_capacity_profile_clone"
                donor["class_method"] = "nearest_pr100_site_profile_clone"
                clones.append(donor)
                clone_map[next_gid] = donor_gid
                clone_audit.append({
                    "new_sc_point_gid": next_gid,
                    "donor_sc_point_gid": donor_gid,
                    "region": str(region),
                    "capacity_mw": float(capacity),
                    "class": int(donor["class"]),
                    "cf": float(donor["cf"]),
                })
                next_gid += 1
            if clones:
                source = pd.concat([source, pd.DataFrame(clones)], ignore_index=True)
            pd.DataFrame(clone_audit).to_csv(
                DEFAULTS / "upv_exogenous_profile_clones.csv", index=False
            )
        out = pd.DataFrame({
            "sc_point_gid": source["sc_point_gid"].astype(int),
            "class": source["class"].astype(int),
            "capacity": source["capacity"].astype(float),
            "capital_adder_per_mw": source["capital_adder_per_mw"].astype(float),
            "cf": source["cf"].astype(float),
            "FIPS": source["region"].map(fips),
            "dist_spur_km": source["poi_distance_km"].astype(float),
            "dist_reinforcement_km": 0.0,
            "cost_spur_usd_per_mw": source["cost_total_trans_usd_per_mw"].astype(float),
            "cost_poi_usd_per_mw": 0.0,
            "cost_reinforcement_usd_per_mw": 0.0,
            "cost_total_trans_usd_per_mw": source["cost_total_trans_usd_per_mw"].astype(float),
            "region": source["region"],
            "supply_curve_cost_per_mw": source["supply_curve_cost_per_mw"].astype(float),
        })
        destination = destinations / f"supplycurve_{tech}-{SCENARIO}.csv"
        out.to_csv(destination, index=False)
        summaries[tech] = {
            "rows": int(len(out)),
            "capacity_mw": float(out["capacity"].sum()),
            "regions": int(out["region"].nunique()),
            "exogenous_profile_clones": clone_audit,
        }
        expanded[tech] = source
        clone_maps[tech] = clone_map
    return summaries, expanded, clone_maps


def register_cf_profiles(
    clone_maps: dict[str, dict[int, int]],
) -> dict[str, dict[str, object]]:
    """Register converted PR100 site profiles under the unified case label."""
    sources = {
        "upv": "cf_upv_pr100-moderate-limited-35.h5",
        "wind-ons": "cf_wind-ons_pr100-limited-35.h5",
        "wind-ofs": "cf_wind-ofs_pr100-35.h5",
    }
    destination_dir = REEDS_PATH / "inputs" / "profiles_cf"
    destination_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, dict[str, object]] = {}
    for tech, source_name in sources.items():
        source = SUPPLY / "profiles_cf" / source_name
        destination = destination_dir / f"cf_{tech}_{SCENARIO}.h5"
        clones = clone_maps.get(tech, {})
        if not clones:
            shutil.copy2(source, destination)
        else:
            temporary = destination.with_suffix(".tmp.h5")
            with h5py.File(source, "r") as source_h5, h5py.File(temporary, "w") as output_h5:
                for key, value in source_h5.attrs.items():
                    output_h5.attrs[key] = value
                source_columns_raw = source_h5["columns"][:]
                source_columns = [int(value) for value in source_columns_raw]
                column_index = {value: index for index, value in enumerate(source_columns)}
                new_gids = list(clones)
                output_h5.create_dataset(
                    "columns",
                    data=np.asarray(source_columns + new_gids, dtype=source_columns_raw.dtype),
                )
                for key in source_h5:
                    if key == "columns":
                        continue
                    if key.startswith("cf_profile_"):
                        original = source_h5[key][:]
                        appended = np.column_stack([
                            original[:, column_index[clones[new_gid]]]
                            for new_gid in new_gids
                        ])
                        dataset = output_h5.create_dataset(
                            key,
                            data=np.column_stack([original, appended]),
                            compression="gzip",
                            compression_opts=4,
                        )
                        for attr, value in source_h5[key].attrs.items():
                            dataset.attrs[attr] = value
                    else:
                        source_h5.copy(key, output_h5)
            temporary.replace(destination)
        with h5py.File(destination, "r") as profile:
            years = sorted(
                int(key.removeprefix("cf_profile_"))
                for key in profile if key.startswith("cf_profile_")
            )
            sites = int(len(profile["columns"]))
        summary[tech] = {
            "source": str(source),
            "destination": str(destination),
            "weather_years": years,
            "sites": sites,
        }
    return summary


def nearest_site(
    supply: pd.DataFrame,
    region: str,
    regions: pd.DataFrame,
) -> pd.Series:
    same_region = supply.loc[supply["region"] == region]
    if len(same_region):
        return same_region.sort_values("capacity", ascending=False).iloc[0]
    point = regions.loc[region, ["latitude", "longitude"]].astype(float).to_numpy()
    distance2 = (
        (supply["latitude"].astype(float) - point[0]) ** 2
        + (supply["longitude"].astype(float) - point[1]) ** 2
    )
    return supply.loc[distance2.idxmin()]


def build_hydro_monthly_cf() -> dict[str, object]:
    """Extract monthly existing-hydro availability from the Sienna source system."""
    assets = pd.read_csv(NETWORK / "assets.csv", low_memory=False)
    hydro = assets.loc[
        as_bool(assets["status"])
        & as_bool(assets["available"])
        & assets["region"].notna()
        & (assets["asset_type"] == "HydroDispatch")
        & (assets["capacity_mw"].fillna(0) > 0)
    ].copy()
    system = json.loads(BASE_CASE_JSON.read_text())
    components = {}
    for component in system["data"]["components"]:
        uuid = (((component.get("internal") or {}).get("uuid") or {}).get("value"))
        if uuid:
            components[uuid] = component

    rows: list[dict[str, object]] = []
    with h5py.File(BASE_CASE_H5, "r") as source_h5:
        for asset in hydro.itertuples(index=False):
            component = components[str(asset.asset_uuid)]
            metadata = next(
                item for item in component["time_series_container"]
                if item.get("name") == "max_active_power" and "length" in item
            )
            ts_uuid = metadata["time_series_uuid"]["value"]
            values = np.asarray(source_h5[f"time_series/{ts_uuid}/data"][:], dtype=float)
            timestamps = pd.date_range(
                start=metadata["initial_timestamp"],
                periods=len(values),
                freq=pd.to_timedelta(metadata["resolution"]["value"], unit="ms"),
            )
            monthly = pd.Series(values, index=timestamps).groupby(timestamps.month).mean()
            if set(monthly.index) != set(range(1, 13)):
                raise ValueError(f"Hydro profile {ts_uuid} does not cover all calendar months")
            fom_entry = (component.get("ext") or {}).get("fom")
            if fom_entry is None:
                raise ValueError(f"No ext.fom for hydro asset {asset.asset_uuid}")
            fom_value, fom_unit = fom_entry
            if fom_unit != "2018 USD kW^-1 yr^-1":
                raise ValueError(f"Unexpected fom unit '{fom_unit}' for hydro asset {asset.asset_uuid}")
            for month, value in monthly.items():
                rows.append({
                    "region": str(asset.region),
                    "tech": str(asset.reeds_tech_candidate),
                    "month": pd.Timestamp(2001, int(month), 1).strftime("%b"),
                    "capacity_factor": float(np.clip(value, 0, 1)),
                    "capacity_mw": float(asset.capacity_mw),
                    "fom_2018usd_per_kw_yr": float(fom_value),
                    "source_asset_uuid": str(asset.asset_uuid),
                    "source_time_series_uuid": ts_uuid,
                })
    output = pd.DataFrame(rows)
    output.to_csv(DEFAULTS / "hydro_monthly_cf.csv", index=False)
    return {
        "rows": int(len(output)),
        "plants": int(hydro.shape[0]),
        "capacity_mw": float(hydro["capacity_mw"].sum()),
        "mean_capacity_factor": float(
            np.average(output["capacity_factor"], weights=output["capacity_mw"])
        ),
        "source": str(BASE_CASE_H5),
    }


def build_unit_database(
    regions: pd.DataFrame,
    fips: dict[str, str],
    upv_supply: pd.DataFrame,
    include_der: bool,
    include_tranche1: bool,
) -> dict[str, object]:
    template_path = (
        REEDS_PATH / "inputs" / "capacity_exogenous"
        / "ReEDS_generator_database_final_EIA-NEMS.csv"
    )
    templates = pd.read_csv(template_path, low_memory=False)
    assets = pd.read_csv(NETWORK / "assets.csv", low_memory=False)
    assets = assets.loc[
        as_bool(assets["status"])
        & as_bool(assets["available"])
        & assets["region"].notna()
        & assets["asset_type"].isin(["ThermalStandard", "HydroDispatch"])
        & (assets["capacity_mw"].fillna(0) > 0)
    ].copy()

    retirement_columns = [column for column in templates if "RetireYear" in column]
    records: list[pd.Series] = []
    provenance: list[dict[str, object]] = []

    def add_record(
        *,
        source_id: str,
        source_kind: str,
        tech: str,
        region: str,
        capacity_mw: float,
        start_year: int,
        energy_mwh: float | None = None,
        site: pd.Series | None = None,
    ) -> None:
        if not np.isfinite(capacity_mw) or capacity_mw <= 0:
            return
        template_tech = "battery_li" if tech == "battery_4" else tech
        matches = templates.loc[templates["tech"] == template_tech]
        if matches.empty:
            raise ValueError(f"No EIA-NEMS template exists for PR technology {template_tech}")
        row = matches.iloc[0].copy()
        location = regions.loc[region]
        row["tech"] = template_tech
        row["summer_power_capacity_MW"] = float(capacity_mw)
        row["TC_WIN"] = float(capacity_mw)
        row["StartYear"] = int(start_year)
        row["IsExistUnit"] = bool(start_year < 2010)
        for column in retirement_columns:
            row[column] = 2051
        row["RetireYearGiven"] = False
        row["FIPS"] = fips[region]
        row["county"] = "Puerto Rico"
        row["TSTATE"] = "PR"
        row["T_LONG"] = float(location["longitude"])
        row["T_LAT"] = float(location["latitude"])
        row["r"] = region
        row["T_PID"] = f"PR_{source_id}"[:50]
        row["T_UID"] = source_id[:50]
        row["Unique ID"] = source_id
        if template_tech == "battery_li":
            if energy_mwh is None:
                energy_mwh = float(capacity_mw) * 4
            row["energy_capacity_MWh"] = float(energy_mwh)
            row["battery_duration"] = float(energy_mwh) / float(capacity_mw)
        else:
            row["energy_capacity_MWh"] = np.nan
            row["battery_duration"] = np.nan
        if site is not None:
            row["sc_point_gid"] = int(site["sc_point_gid"])
            row["reV_capacity_factor_ac"] = float(site["cf"])
        else:
            row["sc_point_gid"] = pd.NA
            row["reV_capacity_factor_ac"] = np.nan
        records.append(row)
        provenance.append({
            "source_id": source_id,
            "source_kind": source_kind,
            "tech": template_tech,
            "region": region,
            "capacity_mw": float(capacity_mw),
            "start_year": int(start_year),
            "energy_mwh": None if energy_mwh is None else float(energy_mwh),
        })

    for asset in assets.itertuples(index=False):
        add_record(
            source_id=str(asset.asset_uuid),
            source_kind=f"network_{asset.asset_type}",
            tech=str(asset.reeds_tech_candidate),
            region=str(asset.region),
            capacity_mw=float(asset.capacity_mw),
            start_year=2009,
        )

    if include_der:
        dpv = pd.read_csv(DEFAULTS / "distributed_pv.csv").query("year == 2022")
        for item in dpv.itertuples(index=False):
            site = nearest_site(upv_supply, str(item.region), regions)
            add_record(
                source_id=f"PR100_DPV_2022_{item.region}",
                source_kind="pr100_distributed_pv_2022",
                tech="dupv",
                region=str(item.region),
                capacity_mw=float(item.capacity_mw),
                start_year=2009,
                site=site,
            )
        storage = pd.read_csv(DEFAULTS / "distributed_storage.csv").query("year == 2022")
        for item in storage.itertuples(index=False):
            add_record(
                source_id=f"PR100_DST_2022_{item.region}",
                source_kind="pr100_distributed_storage_2022",
                tech="battery_li",
                region=str(item.region),
                capacity_mw=float(item.power_mw),
                energy_mwh=float(item.energy_mwh),
                start_year=2009,
            )

    if include_tranche1:
        tranche1 = pd.read_csv(DEFAULTS / "committed_tranche1_solar.csv")
        for item in tranche1.itertuples(index=False):
            site = nearest_site(upv_supply, str(item.region), regions)
            add_record(
                source_id=f"TRANCHE1_{item.project_id}",
                source_kind="committed_tranche1_solar",
                tech="upv",
                region=str(item.region),
                capacity_mw=float(item.capacity_mw),
                start_year=int(item.online_year_candidate),
                site=site,
            )

    unitdata = pd.DataFrame(records)
    ordered = list(templates.columns) + [
        column for column in ["r", "sc_point_gid", "reV_capacity_factor_ac"]
        if column not in templates.columns
    ]
    unitdata = unitdata.reindex(columns=ordered)
    destination = (
        REEDS_PATH / "inputs" / "capacity_exogenous"
        / "ReEDS_generator_database_final_PR-115plus.csv"
    )
    unitdata.to_csv(destination, index=False)

    provenance_frame = pd.DataFrame(provenance)
    provenance_path = DEFAULTS / "pr_reeds_unitdata_provenance.csv"
    provenance_frame.to_csv(provenance_path, index=False)
    by_source = (
        provenance_frame.groupby(["source_kind", "tech"], dropna=False)
        .agg(rows=("source_id", "size"), capacity_mw=("capacity_mw", "sum"))
        .reset_index().to_dict(orient="records")
    )
    excluded = pd.read_csv(NETWORK / "assets.csv", low_memory=False)
    excluded = excluded.loc[
        as_bool(excluded["status"])
        & excluded["region"].notna()
        & excluded["asset_type"].isin(["RenewableDispatch", "RenewableFix", "GenericBattery"])
    ]
    return {
        "rows": int(len(unitdata)),
        "capacity_mw": float(unitdata["summer_power_capacity_MW"].sum()),
        "by_source_and_tech": by_source,
        "assumptions": [
            "PR100 2022 DER is represented as pre-2010 existing capacity for ReEDS bookkeeping.",
            "Thermal/hydro source components require status=true and available=true.",
            "Source-network renewable/storage components are excluded because they include scenario builds that may overlap PR100 DER and Tranche 1.",
            "Missing engineering/economic generator fields use same-technology EIA-NEMS templates and require calibration before a production solve.",
            "All provisional records retire in 2051 unless replaced by a reviewed PR fleet table.",
        ],
        "excluded_source_network_scenario_assets": {
            "rows": int(len(excluded)),
            "capacity_mw": float(excluded["capacity_mw"].fillna(0).sum()),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--omit-der", action="store_true", help="Omit PR100 2022 DPV/storage")
    parser.add_argument(
        "--omit-tranche1", action="store_true", help="Omit prescribed Tranche 1 solar"
    )
    args = parser.parse_args()

    regions, fips = build_region_tables()
    supply_summary, expanded_supply, clone_maps = build_supply_curves(regions, fips)
    profile_summary = register_cf_profiles(clone_maps)
    hydro_summary = build_hydro_monthly_cf()
    unit_summary = build_unit_database(
        regions=regions,
        fips=fips,
        upv_supply=expanded_supply["upv"],
        include_der=not args.omit_der,
        include_tranche1=not args.omit_tranche1,
    )
    qa = {
        "zone_set": "PR_explicit",
        "voltage_threshold": ">=115 kV",
        "supply_curve_scenario": SCENARIO,
        "cost_basis": "real 2021 USD",
        "regions": int(len(regions)),
        "supply_curves": supply_summary,
        "site_cf_profiles": profile_summary,
        "existing_hydro_profile": hydro_summary,
        "unit_database": unit_summary,
        "production_ready": False,
    }
    qa_path = DEFAULTS / "pr_reeds_native_inputs_qa.json"
    qa_path.write_text(json.dumps(qa, indent=2) + "\n")
    print(json.dumps(qa, indent=2))


if __name__ == "__main__":
    main()
