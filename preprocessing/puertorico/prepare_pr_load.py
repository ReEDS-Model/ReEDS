#!/usr/bin/env python3
"""Aggregate LUMA load time series to 121 regions and apply 1% annual growth."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pandas as pd


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def component_type(component: dict[str, Any]) -> str:
    return component.get("__metadata__", {}).get("type", "")


def uuid_of(component: dict[str, Any]) -> str:
    return component["internal"]["uuid"]["value"]


def ref_of(component: dict[str, Any], field: str) -> str:
    return component[field]["value"]


def full_series_uuid(component: dict[str, Any]) -> str:
    candidates = [
        metadata
        for metadata in component.get("time_series_container", [])
        if metadata.get("__metadata__", {}).get("type") == "SingleTimeSeriesMetadata"
        and metadata.get("name") == "max_active_power"
    ]
    if len(candidates) != 1:
        raise ValueError(
            f"Expected one full max_active_power series for {component['name']}, "
            f"found {len(candidates)}"
        )
    return candidates[0]["time_series_uuid"]["value"]


def load_capacity_mw(component: dict[str, Any]) -> float:
    base = float(component["base_power"])
    return base * sum(
        float(component.get(field) or 0.0)
        for field in (
            "max_constant_active_power",
            "max_current_active_power",
            "max_impedance_active_power",
        )
    )


def representative_calendar_positions() -> tuple[pd.DatetimeIndex, np.ndarray]:
    source_index = pd.date_range("2024-07-01", periods=13_152, freq="h")
    first = np.flatnonzero((source_index.year == 2025) & (source_index.month <= 6))
    second = np.flatnonzero((source_index.year == 2024) & (source_index.month >= 7))
    positions = np.concatenate([first, second])
    if len(positions) != 8_760:
        raise AssertionError(f"Representative calendar has {len(positions)} hours")
    representative = source_index[positions]
    expected_months = np.concatenate(
        [np.repeat(np.arange(1, 13), [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])]
    )
    if not np.array_equal(representative.month.values[::24], expected_months):
        raise AssertionError("Representative source calendar is not Jan-Dec ordered")
    return representative, positions


def write_load_h5(
    path: Path,
    columns: list[str],
    data: np.ndarray,
    model_year_index: np.ndarray,
    datetime_index: np.ndarray,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as target:
        target.create_dataset("index_0", data=model_year_index.astype(np.int16))
        target.create_dataset("index_1", data=datetime_index, dtype="S30")
        target.create_dataset("index_names", data=[b"year", b"datetime"], dtype="S8")
        width = max(len(column) for column in columns)
        target.create_dataset("columns", data=np.asarray(columns, dtype=f"S{width}"))
        target.create_dataset(
            "data",
            data=data.astype(np.float32),
            dtype=np.float32,
            compression="gzip",
            compression_opts=4,
        )


def build(args: argparse.Namespace) -> dict[str, Any]:
    with args.system_json.open(encoding="utf-8") as stream:
        components = json.load(stream)["data"]["components"]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for component in components:
        grouped.setdefault(component_type(component), []).append(component)
    buses_by_uuid = {uuid_of(bus): bus for bus in grouped["Bus"]}
    bus_to_region = {
        int(row["bus_number"]): row["region"]
        for row in read_csv(args.bus_to_region)
        if row["region"]
    }
    regions = [row["r"] for row in read_csv(args.regions)]
    region_position = {region: index for index, region in enumerate(regions)}
    source_hours = 13_152
    regional_source = np.zeros((source_hours, len(regions)), dtype=np.float64)
    active_loads = [
        component
        for component in grouped["StandardLoad"]
        if component.get("available", True)
    ]
    load_capacity_by_region = {region: 0.0 for region in regions}
    with h5py.File(args.time_series_h5, "r") as time_series:
        storage = time_series["time_series"]
        for load in active_loads:
            bus = buses_by_uuid[ref_of(load, "bus")]
            region = bus_to_region.get(int(bus["number"]))
            if region is None:
                raise ValueError(f"Active load {load['name']} is on an unmapped bus")
            capacity = load_capacity_mw(load)
            uuid = full_series_uuid(load)
            multiplier = storage[uuid]["data"][:]
            if multiplier.shape != (source_hours,):
                raise ValueError(f"Unexpected load series shape {multiplier.shape} for {load['name']}")
            if multiplier.min() < 0 or multiplier.max() > 1.000001:
                raise ValueError(f"Load multiplier outside [0,1] for {load['name']}")
            regional_source[:, region_position[region]] += multiplier * capacity
            load_capacity_by_region[region] += capacity

    source_calendar, positions = representative_calendar_positions()
    base_shape = regional_source[positions]
    solve_years = list(range(args.start_year, args.end_year + 1, args.year_step))
    if solve_years[-1] != args.end_year:
        solve_years.append(args.end_year)
    blocks: list[np.ndarray] = []
    model_year_index: list[int] = []
    datetime_index: list[bytes] = []
    for model_year in solve_years:
        factor = (1 + args.annual_growth) ** (model_year - args.reference_year)
        for weather_year in args.weather_years:
            blocks.append(base_shape * factor)
            model_year_index.extend([model_year] * 8_760)
            target_time = pd.date_range(
                f"{weather_year}-01-01 00:00:00",
                periods=8_760,
                freq="h",
                tz="Etc/GMT+4",
            )
            datetime_index.extend(timestamp.isoformat().encode("utf-8") for timestamp in target_time)
    output_data = np.concatenate(blocks, axis=0)
    output_h5 = args.output_dir / "load.h5"
    write_load_h5(
        output_h5,
        regions,
        output_data,
        np.asarray(model_year_index),
        np.asarray(datetime_index),
    )

    summary_rows = []
    for region, index in region_position.items():
        summary_rows.append(
            {
                "region": region,
                "connected_load_capacity_mw": load_capacity_by_region[region],
                "representative_peak_mw": float(base_shape[:, index].max()),
                "representative_energy_mwh": float(base_shape[:, index].sum()),
            }
        )
    with (args.output_dir / "load_base_region_summary.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary_rows[0]))
        writer.writeheader()
        writer.writerows(summary_rows)

    qa = {
        "source": {
            "active_load_components": len(active_loads),
            "source_hours": source_hours,
            "source_start": "2024-07-01T00:00:00",
            "source_end": "2025-12-30T23:00:00",
            "representative_calendar": "2025 Jan-Jun followed by 2024 Jul-Dec",
            "representative_source_first": source_calendar[0].isoformat(),
            "representative_source_last": source_calendar[-1].isoformat(),
        },
        "settings": {
            "model_years": solve_years,
            "weather_years": args.weather_years,
            "reference_year": args.reference_year,
            "annual_growth": args.annual_growth,
            "timezone": "Etc/GMT+4",
            "load_level": "busbar from power-system load components; no extra distribution-loss uplift",
        },
        "output": {
            "regions": len(regions),
            "rows": int(output_data.shape[0]),
            "columns": int(output_data.shape[1]),
            "base_system_peak_mw": float(base_shape.sum(axis=1).max()),
            "base_system_energy_mwh": float(base_shape.sum()),
            "connected_load_capacity_mw": float(sum(load_capacity_by_region.values())),
            "h5": str(output_h5),
            "h5_size_bytes": output_h5.stat().st_size,
        },
        "warnings": [
            "The source is a 2024-2025 projection, not measured 2018/2019 load.",
            "Weather-year timestamps are labels for the composite seasonal shape; weekday alignment is not historical.",
            "The 1% growth path is an agreed scenario assumption, not a PR100 electrification forecast.",
        ],
    }
    with (args.output_dir / "load_qa.json").open("w", encoding="utf-8") as stream:
        json.dump(qa, stream, indent=2)
        stream.write("\n")
    return qa


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).resolve().parent
    root = Path("/projects/aiplusinvest")
    base = root / "base_case"
    network = here / "outputs" / "network_115plus"
    parser.add_argument(
        "--system-json",
        type=Path,
        default=base / "ebb45e39-4c77-4115-b183-b001079430f1.json",
    )
    parser.add_argument(
        "--time-series-h5",
        type=Path,
        default=base / "ebb45e39-4c77-4115-b183-b001079430f1_time_series_storage.h5",
    )
    parser.add_argument(
        "--bus-to-region", type=Path, default=network / "bus_to_region.csv"
    )
    parser.add_argument("--regions", type=Path, default=network / "regions.csv")
    parser.add_argument("--start-year", type=int, default=2020)
    parser.add_argument("--end-year", type=int, default=2050)
    parser.add_argument("--year-step", type=int, default=3)
    parser.add_argument("--reference-year", type=int, default=2024)
    parser.add_argument("--annual-growth", type=float, default=0.01)
    parser.add_argument("--weather-years", type=int, nargs="+", default=[2018, 2019])
    parser.add_argument(
        "--output-dir", type=Path, default=here / "outputs" / "case_defaults"
    )
    return parser.parse_args()


if __name__ == "__main__":
    result = build(parse_args())
    print(json.dumps(result["output"], indent=2))
