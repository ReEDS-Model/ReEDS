#!/usr/bin/env python3
"""Calculate screening pairwise TTCs for the 121-region DC network.

For each adjacent aggregate-region pair, inject 1 MW at one retained bus and
withdraw 1 MW at the other. Scale that transaction until any rated AC branch or
transformer reaches its continuous thermal limit. The result is an N-0 pairwise
TTC, not a simultaneous or contingency-constrained transfer limit.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import splu


BRANCH_TYPES = (
    "Line",
    "MonitoredLine",
    "Transformer2W",
    "TapTransformer",
    "PhaseShiftingTransformer",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def component_type(component: dict[str, Any]) -> str:
    return component.get("__metadata__", {}).get("type", "")


def uuid_of(component: dict[str, Any]) -> str:
    return component["internal"]["uuid"]["value"]


def ref_of(component: dict[str, Any], field: str) -> str:
    return component[field]["value"]


def electrical_model(
    system_json: Path, retained_buses: list[int], unlimited_rating_mw: float
) -> tuple[list[int], dict[int, int], Any, list[dict[str, Any]]]:
    with system_json.open(encoding="utf-8") as stream:
        system = json.load(stream)
    components = system["data"]["components"]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for component in components:
        grouped[component_type(component)].append(component)
    base_mva = float(system.get("units_settings", {}).get("base_value", 100.0))
    buses = {uuid_of(bus): bus for bus in grouped["Bus"]}
    arcs = {uuid_of(arc): arc for arc in grouped["Arc"]}
    branches: list[dict[str, Any]] = []
    adjacency: dict[int, set[int]] = defaultdict(set)
    for kind in BRANCH_TYPES:
        for component in grouped.get(kind, []):
            if not component.get("available", True):
                continue
            arc = arcs[ref_of(component, "arc")]
            from_bus = int(buses[ref_of(arc, "from")]["number"])
            to_bus = int(buses[ref_of(arc, "to")]["number"])
            reactance = float(component["x"])
            rate = component.get("rate")
            rate_mw = None if rate is None else float(rate) * base_mva
            branches.append(
                {
                    "branch_type": kind,
                    "branch_name": component.get("name", ""),
                    "from_bus": from_bus,
                    "to_bus": to_bus,
                    "x_pu": reactance,
                    "rate_mw": rate_mw,
                    "constrained": bool(
                        rate_mw is not None and 0 < rate_mw < unlimited_rating_mw
                    ),
                }
            )
            adjacency[from_bus].add(to_bus)
            adjacency[to_bus].add(from_bus)

    source = retained_buses[0]
    connected = {source}
    queue = [source]
    while queue:
        bus = queue.pop()
        for neighbor in adjacency[bus]:
            if neighbor not in connected:
                connected.add(neighbor)
                queue.append(neighbor)
    if not set(retained_buses).issubset(connected):
        raise ValueError("Retained buses are not in one connected electrical component")
    bus_numbers = sorted(connected)
    position = {bus: index for index, bus in enumerate(bus_numbers)}
    matrix_row: list[int] = []
    matrix_col: list[int] = []
    matrix_data: list[float] = []
    for branch in branches:
        if branch["from_bus"] not in position or branch["to_bus"] not in position:
            continue
        susceptance = 1.0 / branch["x_pu"]
        left, right = position[branch["from_bus"]], position[branch["to_bus"]]
        matrix_row.extend((left, left, right, right))
        matrix_col.extend((left, right, left, right))
        matrix_data.extend((susceptance, -susceptance, -susceptance, susceptance))
    size = len(bus_numbers)
    bbus = coo_matrix(
        (matrix_data, (matrix_row, matrix_col)), shape=(size, size)
    ).tocsc()
    slack_position = position[source]
    non_slack = np.array([index for index in range(size) if index != slack_position])
    factorization = splu(bbus[non_slack][:, non_slack])
    model = {
        "non_slack": non_slack,
        "factorization": factorization,
        "size": size,
    }
    return bus_numbers, position, model, branches


def transaction_angles(
    source: int, sink: int, position: dict[int, int], model: dict[str, Any]
) -> np.ndarray:
    injection = np.zeros(model["size"])
    injection[position[source]] = 1.0
    injection[position[sink]] = -1.0
    angles = np.zeros(model["size"])
    non_slack = model["non_slack"]
    angles[non_slack] = model["factorization"].solve(injection[non_slack])
    return angles


def branch_factor(
    branch: dict[str, Any], angles: np.ndarray, position: dict[int, int]
) -> float:
    if branch["from_bus"] not in position or branch["to_bus"] not in position:
        return 0.0
    return (
        angles[position[branch["from_bus"]]] - angles[position[branch["to_bus"]]]
    ) / branch["x_pu"]


def calculate_itls(
    interfaces: list[dict[str, str]],
    regions: dict[str, int],
    position: dict[int, int],
    model: dict[str, Any],
    branches: list[dict[str, Any]],
    derate: float,
    unbounded_interface_mw: float,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    constrained = [branch for branch in branches if branch["constrained"]]
    for interface in interfaces:
        left, right = interface["r"], interface["rr"]
        angles = transaction_angles(regions[left], regions[right], position, model)
        limits = []
        for branch in constrained:
            factor = branch_factor(branch, angles, position)
            if abs(factor) <= 1e-9:
                continue
            limits.append((float(branch["rate_mw"]) / abs(factor), branch, factor))
        if limits:
            raw_ttc, binding, factor = min(limits, key=lambda item: item[0])
            capped = raw_ttc > unbounded_interface_mw
            ttc = min(raw_ttc, unbounded_interface_mw)
            binding_values = {
                "binding_branch_type": binding["branch_type"],
                "binding_branch_name": binding["branch_name"],
                "binding_branch_from_bus": binding["from_bus"],
                "binding_branch_to_bus": binding["to_bus"],
                "binding_branch_rate_mw": binding["rate_mw"],
                "binding_transaction_factor": factor,
            }
        else:
            raw_ttc = None
            ttc = unbounded_interface_mw
            capped = True
            binding_values = {
                "binding_branch_type": "unrated_placeholder_path",
                "binding_branch_name": "",
                "binding_branch_from_bus": "",
                "binding_branch_to_bus": "",
                "binding_branch_rate_mw": "",
                "binding_transaction_factor": "",
            }
        capacity = ttc * derate
        output.append(
            {
                "r": left,
                "rr": right,
                "MW_forward": capacity,
                "MW_reverse": capacity,
                "un_derated_pairwise_ttc_mw": "" if raw_ttc is None else raw_ttc,
                "unbounded_screen_applied": capped,
                "unbounded_screen_mw": unbounded_interface_mw,
                "contingency_derate": derate,
                **binding_values,
                "method": "dc_pairwise_retained_bus_transaction_n0_continuous_ratings",
            }
        )
    return output


def validate_against_exported_ptdf(
    ptdf_csv: Path,
    validation_pair: tuple[int, int],
    angles: np.ndarray,
    position: dict[int, int],
    branches: list[dict[str, Any]],
) -> dict[str, Any]:
    source, sink = validation_pair
    exported: dict[tuple[str, int, int, float], dict[int, float]] = defaultdict(dict)
    with ptdf_csv.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            bus = int(row["ACBus_Name"])
            if bus not in validation_pair:
                continue
            key = (
                row["Line_Name"],
                int(row["From_Bus"]),
                int(row["To_Bus"]),
                round(float(row["Line_Rate"]), 9),
            )
            exported[key][bus] = float(row["PTDF_Value"])
    local: dict[tuple[int, int, float], list[float]] = defaultdict(list)
    for branch in branches:
        if branch["branch_type"] not in {"Line", "MonitoredLine"}:
            continue
        rate_pu = round(float(branch["rate_mw"] or 0.0) / 100.0, 9)
        local[(branch["from_bus"], branch["to_bus"], rate_pu)].append(
            branch_factor(branch, angles, position)
        )
    differences = []
    for (_, from_bus, to_bus, rate_pu), values in exported.items():
        if source not in values or sink not in values:
            continue
        candidates = local.get((from_bus, to_bus, rate_pu), [])
        reverse = [-value for value in local.get((to_bus, from_bus, rate_pu), [])]
        candidates = candidates + reverse
        if len(candidates) != 1:
            continue
        expected = values[source] - values[sink]
        differences.append(abs(expected - candidates[0]))
    if not differences:
        raise ValueError("Could not match local branches to exported PTDF rows")
    return {
        "transaction_source_bus": source,
        "transaction_sink_bus": sink,
        "matched_line_rows": len(differences),
        "mean_absolute_factor_difference": float(np.mean(differences)),
        "maximum_absolute_factor_difference": float(np.max(differences)),
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    region_rows = read_csv(args.regions)
    regions = {row["r"]: int(row["bus_number"]) for row in region_rows}
    interfaces = read_csv(args.interfaces)
    _, position, model, branches = electrical_model(
        args.system_json, list(regions.values()), args.unlimited_rating_mw
    )
    output = calculate_itls(
        interfaces,
        regions,
        position,
        model,
        branches,
        args.contingency_derate,
        args.unbounded_interface_mw,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "interfaces_itl.csv", output)
    validation_pair = (regions[interfaces[0]["r"]], regions[interfaces[0]["rr"]])
    validation_angles = transaction_angles(*validation_pair, position, model)
    validation = validate_against_exported_ptdf(
        args.ptdf_csv, validation_pair, validation_angles, position, branches
    )
    capacities = np.array([row["MW_forward"] for row in output])
    qa = {
        "settings": {
            "interfaces": len(interfaces),
            "continuous_rating_upper_bound_treated_as_unlimited_mw": args.unlimited_rating_mw,
            "contingency_derate": args.contingency_derate,
            "unbounded_interface_screen_mw": args.unbounded_interface_mw,
            "method": "pairwise retained-bus transaction using full JSON AC branch topology",
            "tap_handling": "tap magnitudes ignored in linear sensitivities",
            "base_flow": "zero; JSON active branch flows are zero",
        },
        "capacity_summary_mw": {
            "minimum": float(capacities.min()),
            "median": float(np.median(capacities)),
            "maximum": float(capacities.max()),
        },
        "binding_branch_types": {
            str(kind): int(count)
            for kind, count in zip(
                *np.unique(
                    [row["binding_branch_type"] for row in output], return_counts=True
                )
            )
        },
        "interfaces_with_unbounded_screen": sum(
            bool(row["unbounded_screen_applied"]) for row in output
        ),
        "exported_ptdf_validation": validation,
        "warnings": [
            "These are N-0 pairwise TTCs, not N-1 or simultaneous ITLs.",
            "ReEDS uses a transport representation and will not reproduce AC loop flows.",
            "Forward and reverse capacities are equal because the source model has zero base flows.",
        ],
    }
    with (args.output_dir / "itl_qa.json").open("w", encoding="utf-8") as stream:
        json.dump(qa, stream, indent=2)
        stream.write("\n")
    return qa


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).resolve().parent
    root = Path("/projects/aiplusinvest")
    network = here / "outputs" / "network_115plus"
    parser.add_argument(
        "--system-json",
        type=Path,
        default=root / "base_case" / "ebb45e39-4c77-4115-b183-b001079430f1.json",
    )
    parser.add_argument("--regions", type=Path, default=network / "regions.csv")
    parser.add_argument(
        "--interfaces", type=Path, default=network / "interfaces_screening.csv"
    )
    parser.add_argument(
        "--ptdf-csv", type=Path, default=root / "base_case" / "ptdf_output.csv"
    )
    parser.add_argument("--unlimited-rating-mw", type=float, default=5_000.0)
    parser.add_argument("--contingency-derate", type=float, default=1.0)
    parser.add_argument("--unbounded-interface-mw", type=float, default=5_000.0)
    parser.add_argument("--output-dir", type=Path, default=here / "outputs" / "case_defaults")
    return parser.parse_args()


if __name__ == "__main__":
    summary = build(parse_args())
    print(json.dumps(summary, indent=2))
