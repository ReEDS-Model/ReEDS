#!/usr/bin/env python3
"""Compare a completed ReEDS PR100 mirror run with official PR100 1LM capacity."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
DEFAULT_BENCHMARK = HERE / "outputs" / "pr100_1LM_mirror" / "official_capacity_1LM_reeds_groups.csv"


def category(technology: str) -> str | None:
    tech = technology.lower()
    if tech == "distpv":
        return "Distributed PV"
    if tech.startswith("upv") or tech.startswith("pvb"):
        return "Utility PV"
    if tech.startswith("wind-ons"):
        return "Land-based Wind"
    if tech.startswith("wind-ofs"):
        return "Offshore Wind"
    if tech == "battery_li":
        return "Battery Storage"
    if tech.startswith("coal"):
        return "Coal"
    if tech == "gas-cc" or tech.startswith("gas-cc_"):
        return "Natural Gas"
    if tech in {"gas-ct", "o-g-s"}:
        return "Liquid Fuel / Biodiesel"
    if tech.startswith("hyd"):
        return "Hydropower"
    if tech == "lfill-gas":
        return "Landfill Gas"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="Completed ReEDS run directory")
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    cap_path = args.run / "outputs" / "cap.csv"
    if not cap_path.exists():
        raise FileNotFoundError(f"Run has no capacity output: {cap_path}")
    reeds = pd.read_csv(cap_path).rename(columns={"i": "technology", "Value": "reeds_mw"})
    reeds["reeds_comparison_category"] = reeds["technology"].map(category)
    unmapped = reeds.loc[
        reeds["reeds_comparison_category"].isna() & (reeds["reeds_mw"].abs() > 1e-6),
        "technology",
    ].drop_duplicates().sort_values()
    if len(unmapped):
        print("Unmapped ReEDS technologies (excluded):", ", ".join(unmapped))
    reeds = (
        reeds.dropna(subset=["reeds_comparison_category"])
        .groupby(["reeds_comparison_category", "t"], as_index=False)["reeds_mw"].sum()
        .rename(columns={"t": "year"})
    )
    official = pd.read_csv(args.benchmark).rename(columns={"capacity_mw": "pr100_mw"})
    # The 2010 ReEDS period is an initialization requirement, not a PR100
    # result year, so compare only years present in the official archive.
    reeds = reeds.loc[reeds["year"].isin(official["year"].unique())]
    comparison = official.merge(
        reeds, on=["reeds_comparison_category", "year"], how="outer"
    ).fillna({"pr100_mw": 0.0, "reeds_mw": 0.0})
    comparison["difference_mw"] = comparison["reeds_mw"] - comparison["pr100_mw"]
    comparison["absolute_difference_mw"] = comparison["difference_mw"].abs()
    comparison["difference_percent_of_pr100"] = (
        100 * comparison["difference_mw"] / comparison["pr100_mw"].replace(0, pd.NA)
    )
    output = args.output or (args.run / "outputs" / "pr100_capacity_comparison.csv")
    comparison.sort_values(["year", "reeds_comparison_category"]).to_csv(output, index=False)
    summary = comparison.groupby("year").agg(
        absolute_difference_mw=("absolute_difference_mw", "sum"),
        reeds_total_mw=("reeds_mw", "sum"),
        pr100_total_mw=("pr100_mw", "sum"),
    )
    summary.to_csv(output.with_name(output.stem + "_summary.csv"))
    print(output)


if __name__ == "__main__":
    main()
