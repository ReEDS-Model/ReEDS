#!/usr/bin/env python3
"""Convert selected PR100 reV profiles into ReEDS site-profile HDF5 files.

Run with an environment containing h5py, numpy, and pandas. On the current
cluster, `/home/ychen10/.conda-envs/reeds2/bin/python` satisfies these imports.
"""

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


def read_selected(path: Path) -> dict[str, list[int]]:
    selected: dict[str, list[int]] = {}
    for row in read_csv(path):
        selected.setdefault(row["tech"], []).append(int(row["sc_point_gid"]))
    return {tech: sorted(set(gids)) for tech, gids in selected.items()}


def source_paths(root: Path) -> dict[str, dict[int, Path]]:
    return {
        "upv": {
            year: root / f"upv_fixed_moderate_limited_35_rep-profiles_{year}.h5"
            for year in (2018, 2019)
        },
        "wind-ons": {
            year: root / f"wind_onshore_limited_35_rep-profiles_{year}.h5"
            for year in (2018, 2019)
        },
        "wind-ofs": {
            year: root / f"wind_offshore_35_rep-profiles_{year}.h5"
            for year in (2018, 2019)
        },
    }


def hourly_source(
    path: Path, selected_gids: list[int]
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    with h5py.File(path, "r") as source:
        gids = source["meta"]["sc_point_gid"][:].astype(int)
        position = {int(gid): index for index, gid in enumerate(gids)}
        missing = sorted(set(selected_gids) - set(position))
        if missing:
            raise ValueError(f"{path.name} omits selected sc_point_gid values {missing[:20]}")
        indices = np.array([position[gid] for gid in selected_gids], dtype=int)
        # h5py requires increasing fancy indices. selected_gids and metadata are
        # both gid ordered in these PR100 files, but assert rather than assume.
        if not np.all(indices[:-1] < indices[1:]):
            raw = source["rep_profiles_0"][:, :][:, indices]
        else:
            raw = source["rep_profiles_0"][:, indices]
        time_index = source["time_index"][:]

    source_rows = raw.shape[0]
    if source_rows == 17_520:
        parsed = pd.to_datetime(time_index.astype(str), utc=True)
        deltas = np.diff(parsed.asi8)
        expected = pd.Timedelta(minutes=30).value
        if not np.all(deltas == expected):
            raise ValueError(f"{path.name} is 17,520 rows but is not uniform half-hour data")
        raw = raw.reshape(8_760, 2, raw.shape[1]).mean(axis=1)
        time_index = time_index[::2]
        conversion = "mean_of_two_half_hour_intervals"
    elif source_rows == 8_760:
        conversion = "already_hourly"
    else:
        raise ValueError(f"{path.name} has unsupported row count {source_rows}")
    if raw.shape != (8_760, len(selected_gids)):
        raise AssertionError(f"Unexpected converted shape {raw.shape}")
    if np.nanmin(raw) < -1e-6 or np.nanmax(raw) > 1.01:
        raise ValueError(f"{path.name} contains capacity factors outside [0, 1.01]")
    return raw.astype(np.float32), time_index, {
        "source_rows": source_rows,
        "target_rows": raw.shape[0],
        "sites": raw.shape[1],
        "time_conversion": conversion,
        "minimum_cf": float(np.nanmin(raw)),
        "maximum_cf": float(np.nanmax(raw)),
        "mean_cf": float(np.nanmean(raw)),
    }


def write_reeds_site_h5(
    path: Path,
    selected_gids: list[int],
    yearly: dict[int, tuple[np.ndarray, np.ndarray]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as target:
        target.create_dataset("columns", data=np.asarray(selected_gids, dtype=np.int32))
        for year, (profiles, time_index) in sorted(yearly.items()):
            dataset = target.create_dataset(
                f"cf_profile_{year}",
                data=profiles,
                dtype=np.float32,
                compression="gzip",
                compression_opts=4,
            )
            dataset.attrs["scale"] = 1.0
            target.create_dataset(f"time_index_{year}", data=time_index, dtype="S25")


def build(args: argparse.Namespace) -> dict[str, Any]:
    selected = read_selected(args.selection)
    sources = source_paths(args.profile_root)
    filenames = {
        "upv": "cf_upv_pr100-moderate-limited-35.h5",
        "wind-ons": "cf_wind-ons_pr100-limited-35.h5",
        "wind-ofs": "cf_wind-ofs_pr100-35.h5",
    }
    qa: dict[str, Any] = {
        "weather_years": [2018, 2019],
        "timezone": "source and output timestamps remain UTC; ReEDS converts to Etc/GMT+4",
        "technologies": {},
    }
    for tech, gids in selected.items():
        yearly: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        tech_qa: dict[str, Any] = {"selected_sites": len(gids), "years": {}}
        for year, source_path in sources[tech].items():
            profiles, time_index, year_qa = hourly_source(source_path, gids)
            yearly[year] = profiles, time_index
            tech_qa["years"][str(year)] = {"source_h5": str(source_path), **year_qa}
        target = args.output_dir / filenames[tech]
        write_reeds_site_h5(target, gids, yearly)
        tech_qa["output_h5"] = str(target)
        tech_qa["output_size_bytes"] = target.stat().st_size
        qa["technologies"][tech] = tech_qa
    with (args.output_dir / "profile_conversion_qa.json").open("w", encoding="utf-8") as stream:
        json.dump(qa, stream, indent=2)
        stream.write("\n")
    return qa


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).resolve().parent
    staging = here / "outputs" / "pr100_moderate_limited_2035"
    parser.add_argument(
        "--selection", type=Path, default=staging / "profile_site_selection.csv"
    )
    parser.add_argument(
        "--profile-root",
        type=Path,
        default=Path("/projects/aiplusinvest/pr100_rev_profiles"),
    )
    parser.add_argument("--output-dir", type=Path, default=staging / "profiles_cf")
    return parser.parse_args()


if __name__ == "__main__":
    summary = build(parse_args())
    print(json.dumps(summary, indent=2))
