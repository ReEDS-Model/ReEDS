#!/usr/bin/env python3
"""Stage PR100 1LM distributed resources and Tranche 1 committed solar."""

from __future__ import annotations

import argparse
import json
import math
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from pr100_common import (
    municipality_region_weights,
    normalize_name,
    read_csv,
    write_csv,
)


SOLVE_YEARS = [2022, 2025, 2028, 2030, 2035, 2040, 2045, 2050]

# Project IDs are stable across the Tranche 1 cost table and Exhibit 2 map.
PROJECT_GEOMETRY_ALIASES = {
    "AJ-1-P": "Solarblue Bemoga",
    "AD-1-P": "Putnam Bridge Ciro Two Salinas",
    "I-1-P": "Convergent Coamo Solar",
    "AQ-1-P": "CS/UR Juncos",
    "W-3-P": "Pattern Barceloneta",
    "O-2-P": "Diversys Mayaguez",
    "O-1-P": "Diverxia Cabo Rojo = Enerxia?",
    "C-1-P": "AES Salinas Solar",
    "A-1-P": "AES Jobos",
    "AB-1-P": "Pattern Vega Baja",
    "AI-1-P": "Solaner San German PR One",
    "N-1-P": "Coqui Power ETC Esmeralda",
    "AS-1-P": "Yarotek Tetris",
    "AE-1-P": "Putnam Bridge Guayama",
}

PROJECT_MUNICIPALITY_FALLBACKS = {
    "B-2-P": "Naguabo",
    "B-1-P": "Naguabo",
    "AK-1-P": "Yabucoa",
    "AT-1-P": "Yabucoa",
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    value = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlon / 2) ** 2
    )
    return 6371.0088 * 2 * math.asin(math.sqrt(value))


def interpolate_der(
    archive_path: Path,
    member: str,
    solve_years: list[int],
) -> tuple[dict[str, dict[str, dict[int, float]]], list[int]]:
    with zipfile.ZipFile(archive_path) as archive, archive.open(member) as source:
        frame = pd.read_csv(source)
    frame.columns = [str(column).strip() for column in frame.columns]
    available_years = sorted(
        int(column) for column in frame.columns if str(column).isdigit()
    )
    if min(solve_years) < min(available_years) or max(solve_years) > max(available_years):
        raise ValueError("Requested DER years fall outside the PR100 source range")
    expected_techs = {"pv_mw", "storage_mw", "storage_mwh"}
    if set(frame["tech"].unique()) != expected_techs:
        raise ValueError(f"Unexpected PR100 DER technologies: {frame['tech'].unique()}")

    grouped = frame.groupby(["county", "tech"])[[str(y) for y in available_years]].sum()
    output: dict[str, dict[str, dict[int, float]]] = defaultdict(dict)
    source_x = np.asarray(available_years, dtype=float)
    target_x = np.asarray(solve_years, dtype=float)
    for (county, tech), row in grouped.iterrows():
        key = normalize_name(county)
        values = np.interp(target_x, source_x, row.to_numpy(dtype=float))
        output[key][tech] = {
            year: float(value) for year, value in zip(solve_years, values)
        }
    return dict(output), available_years


def stage_der(
    args: argparse.Namespace,
    regions: list[str],
    weights: dict[str, list[tuple[str, float]]],
) -> dict[str, Any]:
    der, source_years = interpolate_der(
        args.der_zip, args.der_member, list(args.solve_years)
    )
    missing = sorted(set(weights) - set(der))
    extra = sorted(set(der) - set(weights))
    if missing or extra:
        raise ValueError(
            f"DER municipality mismatch: missing={missing}, extra={extra}"
        )

    pv_values = defaultdict(float)
    storage_power = defaultdict(float)
    storage_energy = defaultdict(float)
    municipality_rows: list[dict[str, Any]] = []
    for municipality in sorted(der):
        techs = der[municipality]
        if set(techs) != {"pv_mw", "storage_mw", "storage_mwh"}:
            raise ValueError(f"Incomplete DER technologies for {municipality}")
        for year in args.solve_years:
            municipality_rows.append(
                {
                    "municipality_key": municipality,
                    "year": year,
                    "pv_mw": techs["pv_mw"][year],
                    "storage_mw": techs["storage_mw"][year],
                    "storage_mwh": techs["storage_mwh"][year],
                }
            )
            for region, weight in weights[municipality]:
                pv_values[(region, year)] += techs["pv_mw"][year] * weight
                storage_power[(region, year)] += techs["storage_mw"][year] * weight
                storage_energy[(region, year)] += techs["storage_mwh"][year] * weight

    common = {
        "source_scenario": "PR100 1LM",
        "mapping_method": "municipality_active_standard_load_share",
    }
    pv_rows = [
        {
            "region": region,
            "year": year,
            "capacity_mw": pv_values[(region, year)],
            **common,
        }
        for year in args.solve_years
        for region in regions
    ]
    storage_rows = []
    for year in args.solve_years:
        for region in regions:
            power = storage_power[(region, year)]
            energy = storage_energy[(region, year)]
            storage_rows.append(
                {
                    "region": region,
                    "year": year,
                    "power_mw": power,
                    "energy_mwh": energy,
                    "duration_hours": energy / power if power else 0.0,
                    **common,
                }
            )

    write_csv(
        args.output_dir / "distributed_pv.csv", pv_rows, list(pv_rows[0])
    )
    write_csv(
        args.output_dir / "distributed_storage.csv",
        storage_rows,
        list(storage_rows[0]),
    )
    write_csv(
        args.output_dir / "der_municipality_summary.csv",
        municipality_rows,
        list(municipality_rows[0]),
    )
    totals = {
        str(year): {
            "pv_mw": sum(pv_values[(region, year)] for region in regions),
            "storage_mw": sum(storage_power[(region, year)] for region in regions),
            "storage_mwh": sum(storage_energy[(region, year)] for region in regions),
        }
        for year in args.solve_years
    }
    return {
        "source_archive": str(args.der_zip),
        "source_member": args.der_member,
        "source_years": source_years,
        "interpolation": "linear between PR100 even-year values",
        "municipalities": len(der),
        "regions": len(regions),
        "solve_years": list(args.solve_years),
        "totals": totals,
    }


def clean_row(row: dict[str, str]) -> dict[str, str]:
    return {key.strip(): (value.strip() if isinstance(value, str) else value) for key, value in row.items()}


def stage_committed(
    args: argparse.Namespace,
    region_rows: list[dict[str, str]],
    weights: dict[str, list[tuple[str, float]]],
) -> dict[str, Any]:
    projects = [clean_row(row) for row in read_csv(args.tranche1)]
    geometry = gpd.read_file(args.project_geometry)
    if geometry.crs is None:
        raise ValueError("Tranche 1 geometry has no CRS")
    geometry = geometry.to_crs(geometry.estimate_utm_crs())
    centroids = geometry.geometry.centroid
    points = gpd.GeoDataFrame(
        geometry.drop(columns="geometry"), geometry=centroids, crs=geometry.crs
    ).to_crs(4326)
    point_lookup = {
        str(row.project_name): (float(row.geometry.x), float(row.geometry.y))
        for _, row in points.iterrows()
    }

    output: list[dict[str, Any]] = []
    for project in projects:
        project_id = project["Project ID"]
        longitude: float | str = ""
        latitude: float | str = ""
        source_project = PROJECT_GEOMETRY_ALIASES.get(project_id, "")
        note = ""
        if source_project:
            longitude, latitude = point_lookup[source_project]
            candidates = [
                (
                    haversine_km(
                        float(latitude),
                        float(longitude),
                        float(region["latitude"]),
                        float(region["longitude"]),
                    ),
                    region["r"],
                )
                for region in region_rows
            ]
            distance, region = min(candidates, key=lambda item: (item[0], item[1]))
            mapping_method = "exhibit_2_centroid_nearest_retained_bus"
            confidence = "high"
            municipality = ""
            if project_id == "AQ-1-P":
                confidence = "low"
                note = "PR100 table says Cabo Rojo; Exhibit 2 geometry is labeled CS/UR Juncos."
        else:
            municipality = PROJECT_MUNICIPALITY_FALLBACKS[project_id]
            municipality_key = normalize_name(municipality)
            region, _ = max(weights[municipality_key], key=lambda item: item[1])
            distance = ""
            mapping_method = "municipality_highest_base_load_share_fallback"
            confidence = "medium"
            note = "No matching project geometry in PR100 Exhibit 2."
        output.append(
            {
                "project_id": project_id,
                "proponent": project["Proponent Name"],
                "project_name": project["Project Name"],
                "technology": "upv",
                "capacity_mw": float(project["Nominal MW"]),
                "online_year_candidate": args.committed_online_year,
                "interconnection_voltage_kv": float(project["Interconnection Voltage"]),
                "region": region,
                "longitude": longitude,
                "latitude": latitude,
                "nearest_region_distance_km": distance,
                "mapping_method": mapping_method,
                "mapping_confidence": confidence,
                "source_project_geometry": source_project,
                "source_2021_real_lcoe_usd_per_mwh": float(
                    project["$2021 Real LCOE (IEA) $/MWh"]
                ),
                "source_first_year_interconnection_nominal_usd_per_mwh": float(
                    project["1st Year Interconnection, Nominal $/MWh"]
                ),
                "source_contract_status": project["Source of Price Stream Data"],
                "municipality_fallback": municipality,
                "note": note,
            }
        )

    if len(output) != 18 or not math.isclose(
        sum(row["capacity_mw"] for row in output), 844.8, abs_tol=0.1
    ):
        raise ValueError("Unexpected Tranche 1 project count or capacity")
    write_csv(
        args.output_dir / "committed_tranche1_solar.csv", output, list(output[0])
    )
    return {
        "source_table": str(args.tranche1),
        "source_geometry": str(args.project_geometry),
        "projects": len(output),
        "solar_capacity_mw": sum(row["capacity_mw"] for row in output),
        "online_year_candidate": args.committed_online_year,
        "geometry_mapped_projects": sum(bool(row["source_project_geometry"]) for row in output),
        "municipality_fallback_projects": sum(bool(row["municipality_fallback"]) for row in output),
        "battery_treatment": "not staged; source table does not report battery MW or MWh",
        "warnings": [
            "The 2025 online year is a staging assumption and must be confirmed against commercial-operation records.",
            "AQ-1-P has inconsistent table and Exhibit 2 location labels and is marked low confidence.",
        ],
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    region_rows = read_csv(args.regions)
    regions = [row["r"] for row in region_rows]
    weights, weight_audit = municipality_region_weights(
        args.bus_to_region, args.assets
    )
    write_csv(
        args.output_dir / "municipality_region_der_weights.csv",
        weight_audit,
        list(weight_audit[0]),
    )
    qa = {
        "distributed_resources": stage_der(args, regions, weights),
        "committed_tranche1": stage_committed(args, region_rows, weights),
    }
    with (args.output_dir / "der_committed_qa.json").open("w", encoding="utf-8") as stream:
        json.dump(qa, stream, indent=2)
        stream.write("\n")
    return qa


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).resolve().parent
    root = Path("/projects/aiplusinvest")
    output = here / "outputs"
    network = output / "network_115plus"
    parser.add_argument(
        "--der-zip", type=Path, default=root / "pr100_all" / "data" / "DERInvestments.zip"
    )
    parser.add_argument("--der-member", default="der_capacity_municipality_mw_1LM.csv")
    parser.add_argument(
        "--tranche1",
        type=Path,
        default=root / "pr100_all" / "data" / "tables" / "puerto_rico_tranche1_pv_bess.csv",
    )
    parser.add_argument(
        "--project-geometry",
        type=Path,
        default=root
        / "pr100_all"
        / "data"
        / "shapefiles"
        / "existing_plants"
        / "proyectos_exhibit_2.gpkg",
    )
    parser.add_argument("--regions", type=Path, default=network / "regions.csv")
    parser.add_argument("--bus-to-region", type=Path, default=network / "bus_to_region.csv")
    parser.add_argument("--assets", type=Path, default=network / "assets.csv")
    parser.add_argument("--solve-years", type=int, nargs="+", default=SOLVE_YEARS)
    parser.add_argument("--committed-online-year", type=int, default=2025)
    parser.add_argument("--output-dir", type=Path, default=output / "case_defaults")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(build(parse_args()), indent=2))
