#!/usr/bin/env python3
"""Build 121-region ReEDS load from official PR100 municipality forecasts."""

from __future__ import annotations

import argparse
import csv
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pandas as pd

from pr100_common import (
    municipality_region_weights,
    normalize_name,
    read_csv,
    write_csv,
)


LOAD_COLUMNS = [
    "Fiscal Year",
    "Calendar Year",
    "Month",
    "Day",
    "Hour",
    "Total - Final (MW)",
]


def member_municipality(archive: zipfile.ZipFile, member: str) -> str:
    with archive.open(member) as binary:
        text = io.TextIOWrapper(binary, encoding="cp1252", newline="")
        first = next(csv.reader(text))
    return first[0].strip()


def municipality_members(
    archive: zipfile.ZipFile, scenario_directory: str
) -> dict[str, tuple[str, str]]:
    output: dict[str, tuple[str, str]] = {}
    for member in archive.namelist():
        normalized_path = member.replace("\\", "/")
        if (
            not normalized_path.lower().endswith(".csv")
            or "__MACOSX" in normalized_path
            or scenario_directory not in normalized_path
        ):
            continue
        municipality = member_municipality(archive, member)
        key = normalize_name(municipality)
        if key == "all municipalities":
            continue
        if key in output:
            raise ValueError(f"Duplicate PR100 load file for {municipality!r}")
        output[key] = (municipality, member)
    return output


def read_municipality_load(
    archive: zipfile.ZipFile, member: str, solve_years: list[int]
) -> dict[int, np.ndarray]:
    with archive.open(member) as source:
        frame = pd.read_csv(source, skiprows=2, usecols=LOAD_COLUMNS, encoding="cp1252")
    for column in LOAD_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    output: dict[int, np.ndarray] = {}
    for year in solve_years:
        block = frame.loc[frame["Fiscal Year"] == year].copy()
        if len(block) != 8_760:
            raise ValueError(
                f"{member} has {len(block)} rows for fiscal year {year}; expected 8760"
            )
        # A PR100 fiscal year is Jul-Jun. Sorting by month/day/hour creates a
        # Jan-Dec representative year while preserving that fiscal year's total.
        block.sort_values(["Month", "Day", "Hour"], inplace=True)
        keys = block[["Month", "Day", "Hour"]].astype(int)
        if keys.duplicated().any():
            raise ValueError(f"Duplicate month/day/hour in {member}, fiscal year {year}")
        values = block["Total - Final (MW)"].to_numpy(dtype=np.float64)
        if not np.isfinite(values).all() or values.min() < 0:
            raise ValueError(f"Invalid load values in {member}, fiscal year {year}")
        output[year] = values
    return output


def write_load_h5(
    path: Path,
    columns: list[str],
    data: np.ndarray,
    model_year_index: np.ndarray,
    datetime_index: np.ndarray,
    scenario: str,
    solve_years: list[int],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as target:
        target.attrs["source"] = "PR100 OEDI Electric Load Hourly"
        target.attrs["pr100_scenario"] = scenario
        target.attrs["source_calendar"] = "fiscal-year rows reordered Jan-Dec"
        target.attrs["solve_years"] = np.asarray(solve_years, dtype=np.int16)
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
    regions = [row["r"] for row in read_csv(args.regions)]
    region_position = {region: index for index, region in enumerate(regions)}
    weights, weight_audit = municipality_region_weights(
        args.bus_to_region, args.assets
    )
    write_csv(
        args.output_dir / "municipality_region_load_weights.csv",
        weight_audit,
        list(weight_audit[0]),
    )

    solve_years = list(args.solve_years)
    regional_by_year = {
        year: np.zeros((8_760, len(regions)), dtype=np.float64)
        for year in solve_years
    }
    municipality_energy: dict[str, dict[int, float]] = {}
    with zipfile.ZipFile(args.pr100_load_zip) as archive:
        members = municipality_members(archive, args.scenario_directory)
        missing = sorted(set(weights) - set(members))
        extra = sorted(set(members) - set(weights))
        if missing or extra:
            raise ValueError(
                "Municipality mismatch between PR100 and the bus map: "
                f"missing={missing}, extra={extra}"
            )
        for key in sorted(weights):
            source_label, member = members[key]
            source_by_year = read_municipality_load(archive, member, solve_years)
            municipality_energy[source_label] = {
                year: float(values.sum()) for year, values in source_by_year.items()
            }
            for region, weight in weights[key]:
                column = region_position[region]
                for year, values in source_by_year.items():
                    regional_by_year[year][:, column] += values * weight

    blocks: list[np.ndarray] = []
    model_year_index: list[int] = []
    datetime_index: list[bytes] = []
    for model_year in solve_years:
        for weather_year in args.weather_years:
            blocks.append(regional_by_year[model_year])
            model_year_index.extend([model_year] * 8_760)
            target_time = pd.date_range(
                f"{weather_year}-01-01 00:00:00",
                periods=8_760,
                freq="h",
                tz="Etc/GMT+4",
            )
            datetime_index.extend(timestamp.isoformat().encode() for timestamp in target_time)
    output_data = np.concatenate(blocks, axis=0)
    output_h5 = args.output_dir / "load.h5"
    write_load_h5(
        output_h5,
        regions,
        output_data,
        np.asarray(model_year_index),
        np.asarray(datetime_index),
        args.scenario,
        solve_years,
    )

    reference_year = solve_years[0]
    summary_rows = []
    for region, position in region_position.items():
        values = regional_by_year[reference_year][:, position]
        summary_rows.append(
            {
                "region": region,
                "reference_year": reference_year,
                "peak_mw": float(values.max()),
                "energy_mwh": float(values.sum()),
            }
        )
    write_csv(
        args.output_dir / "load_base_region_summary.csv",
        summary_rows,
        list(summary_rows[0]),
    )

    annual = {
        str(year): {
            "peak_mw": float(regional_by_year[year].sum(axis=1).max()),
            "energy_mwh": float(regional_by_year[year].sum()),
        }
        for year in solve_years
    }
    qa = {
        "source": {
            "archive": str(args.pr100_load_zip),
            "official_url": "https://data.openei.org/files/5749/LoadDataHourly.zip",
            "pr100_scenario": args.scenario,
            "scenario_directory": args.scenario_directory,
            "municipality_files": len(weights),
            "source_time_basis": "fiscal year (Jul-Jun)",
            "output_time_basis": "same fiscal-year observations reordered Jan-Dec",
            "load_column": "Total - Final (MW)",
        },
        "settings": {
            "model_years": solve_years,
            "weather_years": args.weather_years,
            "timezone": "Etc/GMT+4",
            "municipality_to_region_method": "active StandardLoad capacity share; bus-count fallback",
            "weather_year_treatment": "PR100 load duplicated for 2018 and 2019 renewable weather blocks",
        },
        "annual_system_load": annual,
        "output": {
            "regions": len(regions),
            "rows": int(output_data.shape[0]),
            "columns": int(output_data.shape[1]),
            "h5": str(output_h5),
            "h5_size_bytes": output_h5.stat().st_size,
        },
        "warnings": [
            "PR100 load is a forecast, not observed 2018/2019 load.",
            "Within-municipality nodal allocation is fixed over time using base-case load shares.",
            "Fiscal-year rows are reordered into Jan-Dec month order; weekday continuity breaks at the Jun/Jul join.",
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
    output = here / "outputs"
    network = output / "network_115plus"
    parser.add_argument(
        "--pr100-load-zip",
        type=Path,
        default=root / "pr100_all" / "data" / "LoadDataHourly.zip",
    )
    parser.add_argument("--scenario", default="1LM")
    parser.add_argument("--scenario-directory", default="PR100 Sales Data_Mid-Case")
    parser.add_argument("--regions", type=Path, default=network / "regions.csv")
    parser.add_argument(
        "--bus-to-region", type=Path, default=network / "bus_to_region.csv"
    )
    parser.add_argument("--assets", type=Path, default=network / "assets.csv")
    parser.add_argument(
        "--solve-years",
        type=int,
        nargs="+",
        default=[2022, 2025, 2028, 2030, 2035, 2040, 2045, 2050],
    )
    parser.add_argument("--weather-years", type=int, nargs="+", default=[2018, 2019])
    parser.add_argument(
        "--output-dir", type=Path, default=output / "case_defaults"
    )
    return parser.parse_args()


if __name__ == "__main__":
    result = build(parse_args())
    print(json.dumps(result["output"], indent=2))
