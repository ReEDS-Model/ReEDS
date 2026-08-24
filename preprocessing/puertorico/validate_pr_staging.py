#!/usr/bin/env python3
"""Cross-check all generated Puerto Rico staging artifacts."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import h5py
import numpy as np


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def connected_components(regions: set[str], pairs: set[tuple[str, str]]) -> list[set[str]]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for left, right in pairs:
        adjacency[left].add(right)
        adjacency[right].add(left)
    remaining = set(regions)
    output = []
    while remaining:
        start = next(iter(remaining))
        component = {start}
        queue = [start]
        remaining.remove(start)
        while queue:
            node = queue.pop()
            for neighbor in adjacency[node]:
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    component.add(neighbor)
                    queue.append(neighbor)
        output.append(component)
    return output


def build(args: argparse.Namespace) -> dict[str, Any]:
    region_rows = read_csv(args.network / "regions.csv")
    regions = {row["r"] for row in region_rows}
    solve_years = {2022, 2025, 2028, 2030, 2035, 2040, 2045, 2050}
    require(len(regions) == 121, f"Expected 121 unique regions, found {len(regions)}")

    bus_rows = read_csv(args.network / "bus_to_region.csv")
    mapped = [row for row in bus_rows if row["mapped"] == "True"]
    require({row["region"] for row in mapped}.issubset(regions), "Bus map uses unknown regions")
    assets = read_csv(args.network / "assets.csv")
    active_unmapped = [
        row for row in assets if row["available"] == "True" and not row["region"]
    ]
    require(not active_unmapped, f"Found {len(active_unmapped)} active unmapped assets")

    screening = read_csv(args.network / "interfaces_screening.csv")
    screening_pairs = {(row["r"], row["rr"]) for row in screening}
    require(len(screening_pairs) == 184, "Expected 184 unique screening interfaces")
    components = connected_components(regions, screening_pairs)
    require([len(component) for component in components] == [121], "Interface graph disconnected")

    itls = read_csv(args.defaults / "interfaces_itl.csv")
    itl_pairs = {(row["r"], row["rr"]) for row in itls}
    require(itl_pairs == screening_pairs, "ITL and screening interface sets differ")
    require(all(float(row["MW_forward"]) > 0 for row in itls), "Non-positive ITL")

    supply_counts = {}
    selected_by_tech: dict[str, set[int]] = defaultdict(set)
    for row in read_csv(args.supply / "profile_site_selection.csv"):
        selected_by_tech[row["tech"]].add(int(row["sc_point_gid"]))
    for tech in ("upv", "wind-ons", "wind-ofs"):
        rows = read_csv(args.supply / f"supplycurve_{tech}.csv")
        require({row["region"] for row in rows}.issubset(regions), f"{tech} uses unknown region")
        require(
            {int(row["sc_point_gid"]) for row in rows} == selected_by_tech[tech],
            f"{tech} profile selection differs from supply curve",
        )
        require(
            {row["cost_dollar_year"] for row in rows} == {"2021"},
            f"{tech} cost dollar year is not uniformly 2021",
        )
        require(
            {row["cost_basis"] for row in rows} == {"real_2021_usd"},
            f"{tech} cost basis is not real 2021 USD",
        )
        for field in (
            "source_capex_usd_per_kw",
            "source_opex_usd_per_kw_year",
            "source_fixed_charge_rate",
            "source_lcoe_usd_per_mwh",
            "source_total_lcoe_usd_per_mwh",
        ):
            require(all(float(row[field]) > 0 for row in rows), f"Invalid {tech} {field}")
        if tech == "wind-ofs":
            require(
                {row["pr100_exclusions_applied"] for row in rows} == {"True"},
                "Offshore rows lack PR100 exclusion provenance",
            )
            require(
                all(row["pr100_exclusions_config"] for row in rows),
                "Offshore rows lack the exclusion config path",
            )
        supply_counts[tech] = len(rows)

    profile_files = {
        "upv": "cf_upv_pr100-moderate-limited-35.h5",
        "wind-ons": "cf_wind-ons_pr100-limited-35.h5",
        "wind-ofs": "cf_wind-ofs_pr100-35.h5",
    }
    for tech, filename in profile_files.items():
        with h5py.File(args.supply / "profiles_cf" / filename, "r") as profile:
            columns = set(profile["columns"][:].astype(int).tolist())
            require(columns == selected_by_tech[tech], f"{tech} HDF5 columns differ")
            for year in (2018, 2019):
                data = profile[f"cf_profile_{year}"]
                require(data.shape == (8760, len(columns)), f"Unexpected {tech} {year} shape")
                require(data.attrs["scale"] == 1.0, f"Unexpected {tech} scale")

    with h5py.File(args.defaults / "load.h5", "r") as load:
        columns = {value.decode() for value in load["columns"][:]}
        require(columns == regions, "Load columns differ from region set")
        require(load["data"].shape == (140160, 121), "Unexpected load matrix shape")
        require(float(np.min(load["data"])) >= 0, "Negative load value")
        require(load.attrs["pr100_scenario"] == "1LM", "Load scenario is not PR100 1LM")
        require(
            set(load.attrs["solve_years"].astype(int).tolist()) == solve_years,
            "Load solve years differ from the case",
        )

    distributed_pv = read_csv(args.defaults / "distributed_pv.csv")
    require(len(distributed_pv) == len(regions) * len(solve_years), "Incomplete DPV grid")
    require({row["region"] for row in distributed_pv} == regions, "DPV regions differ")
    require({int(row["year"]) for row in distributed_pv} == solve_years, "DPV years differ")
    require(all(float(row["capacity_mw"]) >= 0 for row in distributed_pv), "Negative DPV")

    distributed_storage = read_csv(args.defaults / "distributed_storage.csv")
    require(
        len(distributed_storage) == len(regions) * len(solve_years),
        "Incomplete distributed storage grid",
    )
    require({row["region"] for row in distributed_storage} == regions, "Storage regions differ")
    require(
        {int(row["year"]) for row in distributed_storage} == solve_years,
        "Storage years differ",
    )
    require(
        all(float(row["power_mw"]) >= 0 and float(row["energy_mwh"]) >= 0 for row in distributed_storage),
        "Negative distributed storage",
    )
    require(
        all(
            np.isclose(
                float(row["duration_hours"]),
                float(row["energy_mwh"]) / float(row["power_mw"])
                if float(row["power_mw"]) else 0.0,
            )
            for row in distributed_storage
        ),
        "Distributed storage duration is inconsistent",
    )

    committed = read_csv(args.defaults / "committed_tranche1_solar.csv")
    require(len(committed) == 18, "Expected 18 Tranche 1 projects")
    require({row["region"] for row in committed}.issubset(regions), "Committed project region differs")
    require(
        np.isclose(sum(float(row["capacity_mw"]) for row in committed), 844.8),
        "Unexpected Tranche 1 solar capacity",
    )
    require(
        {int(row["online_year_candidate"]) for row in committed} == {2025},
        "Unexpected Tranche 1 candidate online year",
    )

    summary = {
        "status": "staging_valid",
        "regions": len(regions),
        "mapped_buses": len(mapped),
        "active_assets": sum(row["available"] == "True" for row in assets),
        "interfaces": len(screening_pairs),
        "interface_components": [len(component) for component in components],
        "supply_curve_sites": supply_counts,
        "profile_weather_years": [2018, 2019],
        "load_shape": [140160, 121],
        "load_scenario": "PR100 1LM Mid-Case",
        "solve_years": sorted(solve_years),
        "distributed_resources_2050": {
            "pv_mw": sum(
                float(row["capacity_mw"])
                for row in distributed_pv
                if int(row["year"]) == 2050
            ),
            "storage_mw": sum(
                float(row["power_mw"])
                for row in distributed_storage
                if int(row["year"]) == 2050
            ),
            "storage_mwh": sum(
                float(row["energy_mwh"])
                for row in distributed_storage
                if int(row["year"]) == 2050
            ),
        },
        "committed_tranche1_solar": {"projects": 18, "capacity_mw": 844.8},
        "renewable_cost_basis": "real_2021_usd",
    }
    with (args.output / "staging_validation.json").open("w", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2)
        stream.write("\n")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).resolve().parent
    output = here / "outputs"
    parser.add_argument("--network", type=Path, default=output / "network_115plus")
    parser.add_argument(
        "--supply", type=Path, default=output / "pr100_moderate_limited_2035"
    )
    parser.add_argument("--defaults", type=Path, default=output / "case_defaults")
    parser.add_argument("--output", type=Path, default=output / "case_defaults")
    return parser.parse_args()


if __name__ == "__main__":
    result = build(parse_args())
    print(json.dumps(result, indent=2))
