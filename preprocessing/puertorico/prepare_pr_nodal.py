#!/usr/bin/env python3
"""Build auditable Puerto Rico nodal staging inputs for ReEDS.

The stock ReEDS spatial pipeline aggregates US counties and cannot natively split
one county into several electrical nodes.  This script therefore creates a
standalone, model-agnostic staging layer.  It does not modify stock ReEDS inputs.

Only the Python standard library is required.
"""

from __future__ import annotations

import argparse
import ast
import csv
import heapq
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Optional


BRANCH_TYPES = (
    "Line",
    "MonitoredLine",
    "Transformer2W",
    "TapTransformer",
    "PhaseShiftingTransformer",
)
ASSET_TYPES = (
    "StandardLoad",
    "ThermalStandard",
    "RenewableFix",
    "RenewableDispatch",
    "HydroDispatch",
    "GenericBattery",
)


def uuid_of(component: dict[str, Any]) -> str:
    return component["internal"]["uuid"]["value"]


def ref_of(component: dict[str, Any], field: str) -> str:
    return component[field]["value"]


def component_type(component: dict[str, Any]) -> str:
    return component.get("__metadata__", {}).get("type", "")


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


def region_id(bus_number: int) -> str:
    return f"pr{bus_number}"


def read_components(path: Path) -> tuple[dict[str, list[dict[str, Any]]], float]:
    with path.open(encoding="utf-8") as stream:
        system = json.load(stream)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for component in system["data"]["components"]:
        grouped[component_type(component)].append(component)
    base_mva = float(system.get("units_settings", {}).get("base_value", 100.0))
    return grouped, base_mva


def read_locations(path: Path) -> tuple[dict[int, dict[str, Any]], dict[int, int]]:
    locations: dict[int, dict[str, Any]] = {}
    index_to_bus: dict[int, int] = {}
    for index, row in enumerate(read_csv(path), start=1):
        number = int(row["number"])
        if number in locations:
            raise ValueError(f"Duplicate bus number in node locations: {number}")
        locations[number] = {
            "location_index": index,
            "location_name": row["name"],
            "longitude": float(row["longitude"]),
            "latitude": float(row["latitude"]),
            "area": int(row["area"]),
            "synthetic": row.get("synthetic", "").lower() == "true",
            "adjusted": row.get("adjusted", "").lower() == "true",
        }
        index_to_bus[index] = number
    return locations, index_to_bus


def read_municipalities(
    path: Path, index_to_bus: dict[int, int]
) -> tuple[dict[int, dict[str, str]], list[dict[str, Any]]]:
    bus_to_municipality: dict[int, dict[str, str]] = {}
    mismatches: list[dict[str, Any]] = []
    seen_indices: set[int] = set()
    for row in read_csv(path):
        indices = [int(value) for value in ast.literal_eval(row["PSSE_Bus_Index"])]
        declared = int(row["Number_of_Buses"])
        if declared != len(indices):
            mismatches.append(
                {
                    "municipio": row["municipio"],
                    "declared": declared,
                    "listed": len(indices),
                }
            )
        for index in indices:
            if index in seen_indices:
                raise ValueError(f"Municipality mapping repeats positional index {index}")
            if index not in index_to_bus:
                raise ValueError(f"Municipality mapping has unknown positional index {index}")
            seen_indices.add(index)
            bus_to_municipality[index_to_bus[index]] = {
                "municipality": row["municipio"],
                "county_fips": row["cntyidfp"],
                "countyfp": row["countyfp"],
                "statefp": row["statefp"],
            }
    missing = sorted(set(index_to_bus) - seen_indices)
    if missing:
        raise ValueError(f"Municipality mapping omits positional indices: {missing[:20]}")
    return bus_to_municipality, mismatches


def build_branches(
    grouped: dict[str, list[dict[str, Any]]], base_mva: float
) -> tuple[list[dict[str, Any]], dict[int, list[tuple[int, float]]]]:
    buses_by_uuid = {uuid_of(bus): bus for bus in grouped["Bus"]}
    arcs_by_uuid = {uuid_of(arc): arc for arc in grouped["Arc"]}
    branches: list[dict[str, Any]] = []
    adjacency: dict[int, list[tuple[int, float]]] = defaultdict(list)

    for kind in BRANCH_TYPES:
        for component in grouped.get(kind, []):
            if not component.get("available", True):
                continue
            arc = arcs_by_uuid[ref_of(component, "arc")]
            from_bus = buses_by_uuid[ref_of(arc, "from")]
            to_bus = buses_by_uuid[ref_of(arc, "to")]
            from_number, to_number = int(from_bus["number"]), int(to_bus["number"])
            reactance = float(component.get("x") or 0.0)
            resistance = float(component.get("r") or 0.0)
            impedance_weight = max(math.hypot(reactance, resistance), 1e-9)
            rate_pu = component.get("rate")
            rate_mw = "" if rate_pu is None else float(rate_pu) * base_mva
            branches.append(
                {
                    "branch_uuid": uuid_of(component),
                    "branch_type": kind,
                    "branch_name": component.get("name", ""),
                    "from_bus": from_number,
                    "to_bus": to_number,
                    "from_kv": float(from_bus["base_voltage"]),
                    "to_kv": float(to_bus["base_voltage"]),
                    "r_pu": resistance,
                    "x_pu": reactance,
                    "rate_input_pu": "" if rate_pu is None else float(rate_pu),
                    "rate_mw_assuming_system_base": rate_mw,
                    "suspect_unlimited_rating": bool(rate_mw != "" and rate_mw > 5000),
                }
            )
            adjacency[from_number].append((to_number, impedance_weight))
            adjacency[to_number].append((from_number, impedance_weight))
    return branches, adjacency


def multi_source_assignment(
    bus_numbers: Iterable[int],
    retained: Iterable[int],
    adjacency: dict[int, list[tuple[int, float]]],
) -> tuple[dict[int, int], dict[int, float], dict[int, int]]:
    """Assign each connected bus to its closest retained bus by impedance."""
    owner: dict[int, int] = {}
    distance: dict[int, float] = {}
    hops: dict[int, int] = {}
    heap: list[tuple[float, int, int, int]] = []
    for source in sorted(retained):
        owner[source] = source
        distance[source] = 0.0
        hops[source] = 0
        heapq.heappush(heap, (0.0, source, source, 0))

    while heap:
        current_distance, source, node, current_hops = heapq.heappop(heap)
        best = (distance.get(node, math.inf), owner.get(node, math.inf))
        if (current_distance, source) != best:
            continue
        for neighbor, weight in adjacency.get(node, []):
            candidate = (current_distance + weight, source)
            existing = (distance.get(neighbor, math.inf), owner.get(neighbor, math.inf))
            if candidate < existing:
                distance[neighbor] = candidate[0]
                owner[neighbor] = source
                hops[neighbor] = current_hops + 1
                heapq.heappush(heap, (candidate[0], source, neighbor, current_hops + 1))

    # Keep explicit entries only for assigned buses. The caller reports isolated buses.
    _ = bus_numbers
    return owner, distance, hops


def nested_number(component: dict[str, Any], *path: str) -> Optional[float]:
    value: Any = component
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def original_capacity(component: dict[str, Any]) -> Optional[float]:
    original = component.get("ext", {}).get("original_max_active_power")
    if isinstance(original, list) and original:
        try:
            return float(original[0])
        except (TypeError, ValueError):
            pass
    return None


def capacity_mw(component: dict[str, Any], kind: str) -> float:
    base = float(component.get("base_power") or 0.0)
    if kind == "StandardLoad":
        return base * sum(
            float(component.get(field) or 0.0)
            for field in (
                "max_constant_active_power",
                "max_current_active_power",
                "max_impedance_active_power",
            )
        )
    if original_capacity(component) is not None:
        return float(original_capacity(component))
    if kind == "GenericBattery":
        limit = nested_number(component, "output_active_power_limits", "max")
        return base * (limit if limit is not None else float(component.get("rating") or 0.0))
    limit = nested_number(component, "active_power_limits", "max")
    if limit is not None:
        return base * limit
    return base * float(component.get("rating") or 1.0)


def active_power_mw(component: dict[str, Any], kind: str) -> float:
    base = float(component.get("base_power") or 0.0)
    if kind == "StandardLoad":
        return base * sum(
            float(component.get(field) or 0.0)
            for field in ("constant_active_power", "current_active_power", "impedance_active_power")
        )
    return base * float(component.get("active_power") or 0.0)


def reeds_technology(component: dict[str, Any], kind: str) -> tuple[str, str]:
    fuel = str(component.get("fuel") or "")
    prime = str(component.get("prime_mover") or "")
    name = str(component.get("name") or "").lower()
    if kind == "StandardLoad":
        return "load", "high"
    if kind == "HydroDispatch" or prime == "HY":
        return "hydED", "high"
    if kind == "GenericBattery" or prime == "BA":
        return "battery_4", "medium"
    if kind in {"RenewableFix", "RenewableDispatch"}:
        if prime == "WT" or "wind" in name:
            return "wind-ons", "medium"
        if "distributed" in name or kind == "RenewableFix":
            return "dupv", "medium"
        return "upv", "medium"
    if fuel == "COAL":
        return "coaloldscr", "medium"
    if fuel in {"NATURAL_GAS", "OTHER_GAS"} and prime == "CA":
        return "gas-cc", "medium"
    if fuel in {"NATURAL_GAS", "OTHER_GAS"} and prime in {"CT", "GT"}:
        return "gas-ct", "medium"
    if kind == "ThermalStandard":
        return "o-g-s", "low"
    return "unknown", "low"


def build_assets(
    grouped: dict[str, list[dict[str, Any]]],
    buses_by_uuid: dict[str, dict[str, Any]],
    owner: dict[int, int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for kind in ASSET_TYPES:
        for component in grouped.get(kind, []):
            bus = buses_by_uuid[ref_of(component, "bus")]
            number = int(bus["number"])
            source = owner.get(number)
            technology, confidence = reeds_technology(component, kind)
            rows.append(
                {
                    "asset_uuid": uuid_of(component),
                    "asset_type": kind,
                    "asset_name": component.get("name", ""),
                    "bus_number": number,
                    "region": "" if source is None else region_id(source),
                    "available": bool(component.get("available", True)),
                    "status": bool(component.get("status", True)),
                    "capacity_mw": capacity_mw(component, kind),
                    "active_power_mw": active_power_mw(component, kind),
                    "fuel": component.get("fuel", ""),
                    "prime_mover": component.get("prime_mover", ""),
                    "reeds_tech_candidate": technology,
                    "tech_mapping_confidence": confidence,
                }
            )
    return rows


def aggregate_assets(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    totals: dict[tuple[Any, ...], dict[str, Any]] = {}
    for asset in assets:
        key = (
            asset["region"],
            asset["asset_type"],
            asset["reeds_tech_candidate"],
            asset["fuel"],
            asset["prime_mover"],
            asset["available"],
        )
        if key not in totals:
            totals[key] = {
                "region": key[0],
                "asset_type": key[1],
                "reeds_tech_candidate": key[2],
                "fuel": key[3],
                "prime_mover": key[4],
                "available": key[5],
                "asset_count": 0,
                "capacity_mw": 0.0,
                "active_power_mw": 0.0,
            }
        totals[key]["asset_count"] += 1
        totals[key]["capacity_mw"] += float(asset["capacity_mw"])
        totals[key]["active_power_mw"] += float(asset["active_power_mw"])
    return sorted(totals.values(), key=lambda row: tuple(str(value) for value in row.values()))


def build_interfaces(branches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    totals: dict[tuple[str, str], dict[str, Any]] = {}
    for branch in branches:
        left, right = branch.get("from_region", ""), branch.get("to_region", "")
        if not left or not right or left == right:
            continue
        key = tuple(sorted((left, right)))
        if key not in totals:
            totals[key] = {
                "r": key[0],
                "rr": key[1],
                "branch_count": 0,
                "rated_branch_count": 0,
                "boundary_rate_sum_mw_screening_only": 0.0,
                "suspect_rating_count": 0,
                "capacity_method": "sum_of_boundary_ratings_not_validated_ITL",
            }
        total = totals[key]
        total["branch_count"] += 1
        rate = branch["rate_mw_assuming_system_base"]
        if rate != "":
            total["rated_branch_count"] += 1
            total["boundary_rate_sum_mw_screening_only"] += float(rate)
        total["suspect_rating_count"] += int(branch["suspect_unlimited_rating"])
    return sorted(totals.values(), key=lambda row: (row["r"], row["rr"]))


def build(args: argparse.Namespace) -> dict[str, Any]:
    grouped, base_mva = read_components(args.system_json)
    locations, index_to_bus = read_locations(args.node_locations)
    municipalities, municipality_mismatches = read_municipalities(
        args.municipality_mapping, index_to_bus
    )
    buses = grouped["Bus"]
    buses_by_uuid = {uuid_of(bus): bus for bus in buses}
    buses_by_number = {int(bus["number"]): bus for bus in buses}
    if len(buses_by_number) != len(buses):
        raise ValueError("System JSON contains duplicate bus numbers")
    if set(locations) - set(buses_by_number):
        raise ValueError("Some coordinate buses are missing from the system JSON")

    branches, adjacency = build_branches(grouped, base_mva)
    retained = sorted(
        number
        for number in locations
        if float(buses_by_number[number]["base_voltage"]) >= args.voltage_threshold
        and adjacency.get(number)
    )
    if args.expected_regions and len(retained) != args.expected_regions:
        raise ValueError(
            f"Expected {args.expected_regions} retained regions, found {len(retained)}"
        )
    owner, distance, hops = multi_source_assignment(buses_by_number, retained, adjacency)

    regions: list[dict[str, Any]] = []
    for number in retained:
        bus, location = buses_by_number[number], locations[number]
        municipality = municipalities[number]
        regions.append(
            {
                "r": region_id(number),
                "bus_number": number,
                "bus_name": bus["name"],
                "base_kv": float(bus["base_voltage"]),
                "longitude": location["longitude"],
                "latitude": location["latitude"],
                "municipality": municipality["municipality"],
                "county_fips": municipality["county_fips"],
                "state": "PR",
                "country": "USA",
                "interconnect": "PR",
                "transmission_group": "PR",
            }
        )

    bus_rows: list[dict[str, Any]] = []
    for number, bus in sorted(buses_by_number.items()):
        source = owner.get(number)
        location = locations.get(number, {})
        municipality = municipalities.get(number, {})
        source_municipality = municipalities.get(source, {}) if source is not None else {}
        bus_rows.append(
            {
                "bus_number": number,
                "bus_name": bus["name"],
                "base_kv": float(bus["base_voltage"]),
                "location_index": location.get("location_index", ""),
                "longitude": location.get("longitude", bus.get("ext", {}).get("longitude", "")),
                "latitude": location.get("latitude", bus.get("ext", {}).get("latitude", "")),
                "municipality": municipality.get("municipality", ""),
                "region": "" if source is None else region_id(source),
                "region_bus_number": "" if source is None else source,
                "region_municipality": source_municipality.get("municipality", ""),
                "electrical_distance_pu": distance.get(number, ""),
                "hop_count": hops.get(number, ""),
                "retained_region_bus": number in retained,
                "has_original_coordinate": number in locations,
                "mapped": source is not None,
            }
        )

    for branch in branches:
        from_source = owner.get(branch["from_bus"])
        to_source = owner.get(branch["to_bus"])
        branch["from_region"] = "" if from_source is None else region_id(from_source)
        branch["to_region"] = "" if to_source is None else region_id(to_source)
        branch["is_region_boundary"] = bool(
            from_source is not None and to_source is not None and from_source != to_source
        )
    interfaces = build_interfaces(branches)
    assets = build_assets(grouped, buses_by_uuid, owner)
    asset_totals = aggregate_assets(assets)

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "regions.csv", regions, list(regions[0]))
    write_csv(output / "bus_to_region.csv", bus_rows, list(bus_rows[0]))
    write_csv(output / "branch_to_region.csv", branches, list(branches[0]))
    write_csv(output / "interfaces_screening.csv", interfaces, list(interfaces[0]))
    write_csv(output / "assets.csv", assets, list(assets[0]))
    write_csv(output / "assets_by_region.csv", asset_totals, list(asset_totals[0]))

    unmapped_buses = [row for row in bus_rows if not row["mapped"]]
    active_unmapped_assets = [
        row for row in assets if row["available"] and not row["region"]
    ]
    excluded_high_voltage = sorted(
        number
        for number in locations
        if float(buses_by_number[number]["base_voltage"]) >= args.voltage_threshold
        and number not in retained
    )
    qa = {
        "settings": {
            "voltage_threshold_kv": args.voltage_threshold,
            "expected_regions": args.expected_regions,
            "system_base_mva": base_mva,
            "assignment_method": "multi_source_shortest_path_weighted_by_abs_series_impedance",
        },
        "counts": {
            "system_buses": len(buses),
            "coordinate_buses": len(locations),
            "retained_regions": len(regions),
            "mapped_buses": len(bus_rows) - len(unmapped_buses),
            "unmapped_buses": len(unmapped_buses),
            "available_branches": len(branches),
            "region_boundary_branches": sum(row["is_region_boundary"] for row in branches),
            "interfaces": len(interfaces),
            "assets": len(assets),
            "active_unmapped_assets": len(active_unmapped_assets),
        },
        "excluded_high_voltage_buses": excluded_high_voltage,
        "unmapped_bus_numbers": [row["bus_number"] for row in unmapped_buses],
        "active_unmapped_assets": [row["asset_name"] for row in active_unmapped_assets],
        "municipality_declared_count_mismatches": municipality_mismatches,
        "component_counts": {kind: len(values) for kind, values in sorted(grouped.items())},
        "warnings": [
            "interfaces_screening.csv is a topology/rating audit, not a validated simultaneous or directional ITL.",
            "Branch MW ratings are JSON per-unit ratings multiplied by the 100-MVA system base; placeholder unlimited ratings are flagged.",
            "reeds_tech_candidate is a draft crosswalk and low/medium-confidence rows require review before a capacity-expansion solve.",
            "Stock ReEDS county aggregation cannot consume these 121 regions without a standalone-region input adapter.",
        ],
    }
    with (output / "qa_summary.json").open("w", encoding="utf-8") as stream:
        json.dump(qa, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    return qa


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path("/projects/aiplusinvest")
    base = root / "base_case"
    parser.add_argument(
        "--system-json",
        type=Path,
        default=base / "ebb45e39-4c77-4115-b183-b001079430f1.json",
    )
    parser.add_argument(
        "--node-locations", type=Path, default=base / "node_locations_corrected.csv"
    )
    parser.add_argument(
        "--municipality-mapping",
        type=Path,
        default=base / "municipality_bus_mapping.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "outputs" / "network_115plus",
    )
    parser.add_argument("--voltage-threshold", type=float, default=115.0)
    parser.add_argument("--expected-regions", type=int, default=121)
    return parser.parse_args()


if __name__ == "__main__":
    summary = build(parse_args())
    print(json.dumps(summary["counts"], indent=2))
