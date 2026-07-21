"""Merge ReEDS resource-class outputs into single tech columns.

For prototype simplicity we sum numeric resource classes so the ML pipeline
learns aggregate `cap_wind-ons` instead of per-class `cap_wind-ons_3..10`.
Matches the dashboard legend, which already renders these as a single color.

Regex: (cap|gen)_(wind-ons|wind-ofs|upv)_<digit(s)>[_pXX]
  → summed into  (cap|gen)_(wind-ons|wind-ofs|upv)[_pXX]

Non-matching columns (hydED/hydEND/hydUD, nuclear/nuclear-smr, gas-cc variants,
CoalOldScr etc.) are passed through untouched.

Usage:
    python merge_resource_classes.py               # reads/writes default paths
    python merge_resource_classes.py --dry_run     # print merge groups only
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).resolve().parent
_STUDY_ROOT = _HERE.parent
_INPUTS = _STUDY_ROOT / "inputs"

# Techs whose numeric class suffix is a resource bin we want to collapse.
_MERGE_TECHS = ("wind-ons", "wind-ofs", "upv")

# Matches e.g. cap_upv_3, gen_wind-ons_10_p65, cap_wind-ofs_2_p67.
_PATTERN = re.compile(
    r"^(?P<prefix>cap|gen)_(?P<tech>{techs})_\d+(?P<region>_p\d+)?$".format(
        techs="|".join(re.escape(t) for t in _MERGE_TECHS)
    )
)


def _merged_name(m: re.Match) -> str:
    region = m.group("region") or ""
    return f"{m.group('prefix')}_{m.group('tech')}{region}"


def merge_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """Return (merged_df, groups) where groups maps merged_name -> [source cols]."""
    groups: dict[str, list[str]] = {}
    for col in df.columns:
        m = _PATTERN.match(col)
        if m:
            groups.setdefault(_merged_name(m), []).append(col)

    if not groups:
        return df.copy(), {}

    to_drop = [c for cols in groups.values() for c in cols]
    out = df.drop(columns=to_drop).copy()
    for merged, sources in groups.items():
        out[merged] = df[sources].sum(axis=1)
    return out, groups


def _process(src: Path, dst: Path, dry_run: bool = False) -> None:
    df = pd.read_csv(src)
    merged, groups = merge_dataframe(df)
    print(f"\n[{src.name}]  {df.shape[1]} -> {merged.shape[1]} columns")
    for name, cols in sorted(groups.items()):
        print(f"  {name:40s} <- {cols}")
    if not dry_run:
        merged.to_csv(dst, index=False)
        print(f"  wrote {dst}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--overall_in",  type=Path, default=_INPUTS / "overall_ml_numeric.csv")
    ap.add_argument("--regional_in", type=Path, default=_INPUTS / "regional_ml_numeric.csv")
    ap.add_argument("--overall_out",  type=Path, default=_INPUTS / "overall_ml_numeric_merged.csv")
    ap.add_argument("--regional_out", type=Path, default=_INPUTS / "regional_ml_numeric_merged.csv")
    ap.add_argument("--dry_run", action="store_true", help="print merge groups without writing")
    args = ap.parse_args()

    _process(args.overall_in,  args.overall_out,  args.dry_run)
    _process(args.regional_in, args.regional_out, args.dry_run)


if __name__ == "__main__":
    main()
