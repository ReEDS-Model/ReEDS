#!/usr/bin/env python3
"""Generate a ReEDS zone set for the 121 explicit Puerto Rico regions.

The synthetic FIPS identifiers are compatibility keys only. They allow the
current ReEDS hierarchy reader to carry explicit electrical regions without
claiming that those regions are counties. All Puerto Rico case data must remain
region-indexed and must not be disaggregated through these identifiers.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
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
        writer.writerows(rows)


def region_number(region: str) -> int:
    if not region.startswith("pr") or not region[2:].isdigit():
        raise ValueError(f"Unexpected Puerto Rico region ID: {region!r}")
    return int(region[2:])


def build(args: argparse.Namespace) -> dict[str, Any]:
    regions = sorted(read_csv(args.regions), key=lambda row: region_number(row["r"]))
    if len(regions) != 121 or len({row["r"] for row in regions}) != 121:
        raise ValueError("PR_explicit requires exactly 121 unique source regions")

    hierarchy = []
    county2zone = []
    zonehash = []
    audit = []
    for position, source in enumerate(regions, start=1):
        region = source["r"]
        synthetic_fips = f"{99000 + position:05d}"
        hierarchy.append(
            {
                "r": region,
                "nercr": "PR",
                "transreg": "PR",
                "transgrp": "PR",
                "st": "PR",
                "interconnect": "PR",
                "hurdlereg": "PR",
            }
        )
        county2zone.append({"FIPS": synthetic_fips, "r": region})
        zonehash.append(
            {
                "r": region,
                "md5": hashlib.md5(synthetic_fips.encode("utf-8")).hexdigest(),
                "node_lat": source["latitude"],
                "node_lon": source["longitude"],
            }
        )
        audit.append(
            {
                "r": region,
                "synthetic_fips": synthetic_fips,
                "source_bus_number": source["bus_number"],
                "source_bus_name": source["bus_name"],
                "municipality": source["municipality"],
                "latitude": source["latitude"],
                "longitude": source["longitude"],
                "meaning": "compatibility key only; not a Census county",
            }
        )

    write_csv(
        args.output_dir / "hierarchy.csv",
        hierarchy,
        ["r", "nercr", "transreg", "transgrp", "st", "interconnect", "hurdlereg"],
    )
    write_csv(
        args.output_dir / "county2zone.csv", county2zone, ["FIPS", "r"]
    )
    write_csv(
        args.output_dir / "zonehash.csv",
        zonehash,
        ["r", "md5", "node_lat", "node_lon"],
    )
    interfaces = read_csv(args.interfaces)
    expected_regions = {row["r"] for row in regions}
    invalid_interfaces = [
        row for row in interfaces
        if row["r"] not in expected_regions or row["rr"] not in expected_regions
    ]
    if invalid_interfaces:
        raise ValueError("Puerto Rico interfaces reference an unknown explicit region")
    write_csv(args.output_dir / "b2b.csv", [], ["r", "rr", "MW"])
    write_csv(
        args.output_dir / "interfaces_r.csv",
        [
            {"interconnect": "PR", "interface": f"{row['r']}~~{row['rr']}"}
            for row in interfaces
        ],
        ["interconnect", "interface"],
    )
    write_csv(
        args.output_dir / "interfaces_transgrp.csv",
        [],
        ["interconnect", "interface"],
    )
    write_csv(
        args.audit_output,
        audit,
        [
            "r",
            "synthetic_fips",
            "source_bus_number",
            "source_bus_name",
            "municipality",
            "latitude",
            "longitude",
            "meaning",
        ],
    )
    qa = {
        "status": "valid",
        "regions": len(regions),
        "zone_set": "PR_explicit",
        "state": "PR",
        "interconnect": "PR",
        "interfaces": len(interfaces),
        "synthetic_fips_range": [county2zone[0]["FIPS"], county2zone[-1]["FIPS"]],
        "synthetic_fips_use": (
            "compatibility keys for the current hierarchy reader; never use for "
            "county disaggregation or attribution"
        ),
        "output_dir": str(args.output_dir),
    }
    args.qa_output.parent.mkdir(parents=True, exist_ok=True)
    with args.qa_output.open("w", encoding="utf-8") as stream:
        json.dump(qa, stream, indent=2)
        stream.write("\n")
    return qa


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).resolve().parent
    reeds_path = here.parents[1]
    parser.add_argument(
        "--regions",
        type=Path,
        default=here / "outputs" / "network_115plus" / "regions.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=reeds_path / "inputs" / "zones" / "PR_explicit",
    )
    parser.add_argument(
        "--interfaces",
        type=Path,
        default=here / "outputs" / "case_defaults" / "interfaces_itl.csv",
    )
    parser.add_argument(
        "--audit-output",
        type=Path,
        default=here / "outputs" / "case_defaults" / "pr_explicit_region_keys.csv",
    )
    parser.add_argument(
        "--qa-output",
        type=Path,
        default=here / "outputs" / "case_defaults" / "pr_explicit_zone_qa.json",
    )
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(build(parse_args()), indent=2))
