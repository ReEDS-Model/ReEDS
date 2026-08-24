#!/usr/bin/env python3.9
"""Map PR100 moderate/limited renewable sites to the 121 Puerto Rico regions.

This is a standard-library staging step. It deliberately does not rewrite the
source HDF5 profiles; instead, it emits an exact site/class/region selection and
a profile manifest for the later ReEDS-environment conversion step.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    value = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlon / 2) ** 2
    )
    return 6371.0088 * 2 * math.asin(math.sqrt(value))


def weighted_classes(rows: list[dict[str, Any]], class_count: int) -> None:
    """Assign deterministic equal-capacity CF classes, low CF to high CF."""
    ordered = sorted(rows, key=lambda row: (float(row["cf"]), int(row["sc_point_gid"])))
    total = sum(float(row["capacity"]) for row in ordered)
    cumulative = 0.0
    for row in ordered:
        capacity = float(row["capacity"])
        midpoint = cumulative + capacity / 2
        assigned = min(class_count, int(midpoint / total * class_count) + 1) if total else 1
        row["class"] = assigned
        row["class_method"] = "equal_capacity_cf_proxy_pending_reeds_kmeans"
        cumulative += capacity


def nearest_region(
    latitude: float, longitude: float, regions: list[dict[str, str]]
) -> tuple[dict[str, str], float]:
    candidates = [
        (
            haversine_km(
                latitude,
                longitude,
                float(region["latitude"]),
                float(region["longitude"]),
            ),
            region["r"],
            region,
        )
        for region in regions
    ]
    distance, _, region = min(candidates, key=lambda item: (item[0], item[1]))
    return region, distance


def connection_lookup(
    connection_path: Path,
    substations_path: Path,
    bus_regions: dict[int, str],
) -> dict[str, dict[str, Any]]:
    substations = {row["name"]: row for row in read_csv(substations_path)}
    output: dict[str, dict[str, Any]] = {}
    for row in read_csv(connection_path):
        name = row["substation_name"]
        if name not in substations:
            raise ValueError(f"Connection references unknown substation {name!r}")
        substation = substations[name]
        bus = int(substation["busid"])
        if bus not in bus_regions or not bus_regions[bus]:
            raise ValueError(f"POI bus {bus} for {name!r} has no 115-kV region assignment")
        output[row["sc_point_gid"]] = {
            "region": bus_regions[bus],
            "poi_bus": bus,
            "poi_name": name,
            "poi_kv": float(substation["basekv"]),
            "poi_distance_km": float(row["dist_mi"]) * 1.609344,
            "mapping_method": "pr100_connection_then_electrical_rollup",
        }
    return output


def common_row(
    source: dict[str, str],
    tech: str,
    mapping: dict[str, Any],
) -> dict[str, Any]:
    cf_field = "mean_cf"
    transmission_cost = float(source.get("trans_cap_cost_per_mw") or 0.0)
    if tech == "upv":
        source_capex = float(source["mean_capital_cost"])
        source_opex = float(source["mean_fixed_operating_cost"])
        source_lcoe = float(source["mean_lcoe"])
        source_fcr = float(source["mean_fixed_charge_rate"])
        cost_source = "PR100 2022 ATB moderate fixed-tilt PV, converted to 2021 real USD"
    else:
        source_capex = float(source["capex_per_kw"])
        source_opex = float(source["opex_per_kw"])
        source_lcoe = float(source["site_lcoe"])
        source_fcr = 0.0759 if tech == "wind-ons" else 0.0764
        cost_source = "PR100 wind cost workflow, converted from 2015 to 2021 real USD"
    row = {
        "tech": tech,
        "sc_point_gid": int(source["sc_point_gid"]),
        "region": mapping["region"],
        "class": "",
        "capacity": float(source["capacity"]),
        "capital_adder_per_mw": 0.0,
        "cost_total_trans_usd_per_mw": transmission_cost,
        "supply_curve_cost_per_mw": transmission_cost,
        "cf": float(source[cf_field]),
        "latitude": float(source["latitude"]),
        "longitude": float(source["longitude"]),
        "poi_bus": mapping["poi_bus"],
        "poi_name": mapping["poi_name"],
        "poi_kv": mapping["poi_kv"],
        "poi_distance_km": mapping["poi_distance_km"],
        "mapping_method": mapping["mapping_method"],
        "class_method": "",
        "source_country": mapping.get("source_country", "Puerto Rico"),
        "cost_dollar_year": 2021,
        "cost_basis": "real_2021_usd",
        "source_capex_usd_per_kw": source_capex,
        "source_opex_usd_per_kw_year": source_opex,
        "source_fixed_charge_rate": source_fcr,
        "source_lcoe_usd_per_mwh": source_lcoe,
        "source_total_lcoe_usd_per_mwh": float(source["total_lcoe"]),
        "cost_source": cost_source,
        "pr100_exclusions_applied": mapping.get("pr100_exclusions_applied", ""),
        "pr100_exclusions_config": mapping.get("pr100_exclusions_config", ""),
        "additional_geographic_screen": mapping.get("additional_geographic_screen", ""),
    }
    return row


def map_land_curve(
    curve_path: Path,
    tech: str,
    connections: dict[str, dict[str, Any]],
    class_count: int,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    missing: list[str] = []
    for source in read_csv(curve_path):
        gid = source["sc_point_gid"]
        if gid not in connections:
            missing.append(gid)
            continue
        output.append(common_row(source, tech, connections[gid]))
    if missing:
        raise ValueError(f"{tech} supply curve has {len(missing)} sites without PR100 POIs")
    weighted_classes(output, class_count)
    return sorted(output, key=lambda row: row["sc_point_gid"])


def map_offshore_curve(
    curve_path: Path,
    country_path: Path,
    regions: list[dict[str, str]],
    class_count: int,
    max_poi_distance_km: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    countries = {
        row["sc_point_gid"]: row.get("country", "") for row in read_csv(country_path)
    }
    output: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for source in read_csv(curve_path):
        gid = source["sc_point_gid"]
        country = countries.get(gid, "missing")
        region, distance = nearest_region(
            float(source["latitude"]), float(source["longitude"]), regions
        )
        reason = ""
        if country != "United States":
            reason = "country_not_united_states"
        elif distance > max_poi_distance_km:
            reason = "farther_than_pr_poi_distance_screen"
        if reason:
            excluded.append(
                {
                    "sc_point_gid": int(gid),
                    "latitude": source["latitude"],
                    "longitude": source["longitude"],
                    "capacity_mw": source["capacity"],
                    "source_country": country,
                    "nearest_region": region["r"],
                    "nearest_region_distance_km": distance,
                    "exclusion_reason": reason,
                }
            )
            continue
        mapping = {
            "region": region["r"],
            "poi_bus": int(region["bus_number"]),
            "poi_name": region["bus_name"],
            "poi_kv": float(region["base_kv"]),
            "poi_distance_km": distance,
            "mapping_method": "pr100_exclusions_then_nearest_retained_bus_75km",
            "source_country": country,
            "pr100_exclusions_applied": True,
            "pr100_exclusions_config": (
                "pr100_all/rev/wind/actuals/wind_offshore/aggregation/"
                "wind_offshore_35/config_aggregation.json"
            ),
            "additional_geographic_screen": (
                "United States source-country and nearest retained bus <= "
                f"{max_poi_distance_km:g} km"
            ),
        }
        output.append(common_row(source, "wind-ofs", mapping))
    weighted_classes(output, class_count)
    return sorted(output, key=lambda row: row["sc_point_gid"]), excluded


def profile_manifest(
    profile_root: Path, supply_rows: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    names = {
        "upv": "upv_fixed_moderate_limited_35_rep-profiles_{year}.h5",
        "wind-ons": "wind_onshore_limited_35_rep-profiles_{year}.h5",
        "wind-ofs": "wind_offshore_35_rep-profiles_{year}.h5",
    }
    output: list[dict[str, Any]] = []
    for tech, template in names.items():
        for year in (2018, 2019):
            path = profile_root / template.format(year=year)
            output.append(
                {
                    "tech": tech,
                    "weather_year": year,
                    "source_h5": str(path),
                    "source_exists": path.is_file(),
                    "source_dataset": "rep_profiles_0",
                    "selected_site_count": len(supply_rows[tech]),
                    "target_timezone": "Etc/GMT+4",
                    "conversion_status": "pending_h5py_reeds_environment",
                }
            )
    return output


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_region: dict[str, float] = defaultdict(float)
    for row in rows:
        by_region[row["region"]] += float(row["capacity"])
    return {
        "sites": len(rows),
        "capacity_mw": sum(float(row["capacity"]) for row in rows),
        "regions_with_resource": len(by_region),
        "classes": sorted({int(row["class"]) for row in rows}),
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    regions = read_csv(args.regions)
    bus_regions = {
        int(row["bus_number"]): row["region"] for row in read_csv(args.bus_to_region)
    }
    solar_connections = connection_lookup(
        args.solar_connections, args.substations, bus_regions
    )
    wind_connections = connection_lookup(
        args.wind_connections, args.substations, bus_regions
    )

    supply_rows = {
        "upv": map_land_curve(args.upv_curve, "upv", solar_connections, 5),
        "wind-ons": map_land_curve(
            args.wind_ons_curve, "wind-ons", wind_connections, 10
        ),
    }
    offshore, offshore_excluded = map_offshore_curve(
        args.wind_ofs_curve,
        args.offshore_country_table,
        regions,
        5,
        args.offshore_max_poi_distance_km,
    )
    supply_rows["wind-ofs"] = offshore

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    fields = list(supply_rows["upv"][0])
    for tech, rows in supply_rows.items():
        write_csv(output / f"supplycurve_{tech}.csv", rows, fields)
    exclusion_fields = list(offshore_excluded[0]) if offshore_excluded else ["sc_point_gid"]
    write_csv(output / "wind_ofs_excluded_sites.csv", offshore_excluded, exclusion_fields)

    selection = [
        {
            "tech": tech,
            "sc_point_gid": row["sc_point_gid"],
            "region": row["region"],
            "class": row["class"],
            "capacity_mw": row["capacity"],
        }
        for tech, rows in supply_rows.items()
        for row in rows
    ]
    write_csv(
        output / "profile_site_selection.csv",
        selection,
        ["tech", "sc_point_gid", "region", "class", "capacity_mw"],
    )
    manifest = profile_manifest(args.profile_root, supply_rows)
    write_csv(output / "profile_manifest.csv", manifest, list(manifest[0]))

    excluded_by_reason: dict[str, dict[str, float]] = defaultdict(
        lambda: {"sites": 0, "capacity_mw": 0.0}
    )
    for row in offshore_excluded:
        item = excluded_by_reason[row["exclusion_reason"]]
        item["sites"] += 1
        item["capacity_mw"] += float(row["capacity_mw"])
    qa = {
        "settings": {
            "scenario": "PR100 moderate/limited 2035",
            "weather_years": [2018, 2019],
            "offshore_country_filter": "United States",
            "offshore_max_nearest_retained_bus_distance_km": args.offshore_max_poi_distance_km,
            "offshore_pr100_exclusions": (
                "protected/restricted/marine/cable/disposal/ordnance/USVI masks "
                "from the PR100 wind_offshore_35 aggregation configuration"
            ),
            "class_method": "equal-capacity CF proxy; rerun k-means in ReEDS environment",
            "generation_cost_method": (
                "retain PR100 2021-real site CAPEX, fixed O&M, FCR, site LCOE, "
                "total LCOE, and connection adder as adapter-ready metadata"
            ),
            "cost_dollar_year": 2021,
            "cost_basis": "real_2021_usd",
        },
        "supply_curves": {tech: summarize(rows) for tech, rows in supply_rows.items()},
        "offshore_excluded": dict(excluded_by_reason),
        "profiles": {
            "manifest_rows": len(manifest),
            "all_source_files_exist": all(row["source_exists"] for row in manifest),
            "conversion_status": "pending_h5py_reeds_environment",
        },
        "warnings": [
            "PR100 offshore exclusions and the added 75-km screen are study-siting assumptions, not a legal Puerto Rico jurisdiction polygon.",
            "Offshore POIs use the nearest retained bus because the PR100 wind connection table covers onshore sites only.",
            "Resource classes are deterministic equal-capacity proxies pending the ReEDS k-means environment.",
            "The ReEDS adapter must decide whether to use these PR100 costs or a named ReEDS ATB trajectory; it must not combine both.",
        ],
    }
    with (output / "qa_summary.json").open("w", encoding="utf-8") as stream:
        json.dump(qa, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    return qa


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).resolve().parent
    root = Path("/projects/aiplusinvest")
    network = here / "outputs" / "network_115plus"
    parser.add_argument("--regions", type=Path, default=network / "regions.csv")
    parser.add_argument(
        "--bus-to-region", type=Path, default=network / "bus_to_region.csv"
    )
    parser.add_argument(
        "--upv-curve",
        type=Path,
        default=root / "pr100_rev" / "upv_fixed_moderate_limited_35_supply-curve.csv",
    )
    parser.add_argument(
        "--wind-ons-curve",
        type=Path,
        default=root / "pr100_rev" / "wind_onshore_limited_35_supply-curve.csv",
    )
    parser.add_argument(
        "--wind-ofs-curve",
        type=Path,
        default=root / "pr100_rev" / "wind_offshore_35_supply-curve.csv",
    )
    transmission = root / "pr100_all" / "data" / "tables" / "transmission"
    parser.add_argument(
        "--solar-connections", type=Path, default=transmission / "solar_connections.csv"
    )
    parser.add_argument(
        "--wind-connections", type=Path, default=transmission / "wind_connections.csv"
    )
    parser.add_argument(
        "--substations", type=Path, default=transmission / "substation_lat_longs_rev.csv"
    )
    parser.add_argument(
        "--offshore-country-table",
        type=Path,
        default=root
        / "pr100_all"
        / "data"
        / "tables"
        / "agtables"
        / "wind_offshore"
        / "wind_offshore_supply-curve-aggregation.csv",
    )
    parser.add_argument(
        "--profile-root", type=Path, default=root / "pr100_rev_profiles"
    )
    parser.add_argument("--offshore-max-poi-distance-km", type=float, default=75.0)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=here / "outputs" / "pr100_moderate_limited_2035",
    )
    return parser.parse_args()


if __name__ == "__main__":
    result = build(parse_args())
    print(json.dumps(result["supply_curves"], indent=2))
