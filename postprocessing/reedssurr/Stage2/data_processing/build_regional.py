"""
Regional extractor: pulls X (design inputs) and Y (regionally-resolved 2050 outputs)
out of completed ReEDS surrogate runs and writes them as a single CSV.

Y outputs (all for ERCOT, year 2050, resolved by region):
  - Capacity by technology and region (MW)
  - Generation by technology and region (MWh)
  - Transmission capacity by corridor (MW)
  - System cost by category and region ($)

Output: A single CSV with one row per run, columns for X features and Y outputs.
        Column names encode region: e.g., cap_upv_3_p60, gen_wind-ons_7_p61, tran_p60_p61_AC

Usage:
    python build_regional.py --runs_dir /path/to/runs --output ../inputs/regional_ml.csv
"""

import argparse
import re
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional


# ============================================================================
# X DESIGN ENCODING
# ============================================================================
DIMENSION_ENCODING = {
    "Dem": {"Lo": 0, "Md": 1, "Hi": 2},
    "Fuel": {"Lo": 0, "Md": 1, "Hi": 2},
    "REcost": {"Lo": 0, "Md": 1, "Hi": 2},
    "Siting": {"Open": 0, "Ref": 1, "Lim": 2},
    "Batt": {"Lo": 0, "Md": 1, "Hi": 2},
    "Pol": {"IRA": 0, "OBBBA": 1},
}

CASE_PATTERN = re.compile(
    r"^(?P<prefix>[^_]+)_"
    r"Dem(?P<Dem>Lo|Md|Hi)_"
    r"Fuel(?P<Fuel>Lo|Md|Hi)_"
    r"REcost(?P<REcost>Lo|Md|Hi)_"
    r"Siting(?P<Siting>Open|Ref|Lim)_"
    r"Batt(?P<Batt>Lo|Md|Hi)_"
    r"Pol(?P<Pol>IRA|OBBBA)$"
)

TARGET_YEAR = 2050


def parse_case_name(case_name: str) -> Optional[dict]:
    """Parse a surrogate case directory name into X feature values."""
    match = CASE_PATTERN.match(case_name)
    if not match:
        return None
    features = {}
    for dim, levels in DIMENSION_ENCODING.items():
        level = match.group(dim)
        features[f"x_{dim}"] = levels[level]
        features[f"x_{dim}_label"] = level
    return features


# ============================================================================
# Y EXTRACTORS (all filtered to 2050, regionally resolved)
# ============================================================================

def extract_capacity_regional_2050(run_dir: Path) -> dict:
    """
    Capacity by tech and region in 2050 (MW).
    Source: outputs/cap.csv (i, r, t, Value)
    Returns: {f"cap_{tech}_{region}": MW}
    """
    path = run_dir / "outputs" / "cap.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    df = df[df["t"] == TARGET_YEAR]
    result = {}
    for _, row in df.iterrows():
        result[f"cap_{row['i']}_{row['r']}"] = row["Value"]
    return result


def extract_generation_regional_2050(run_dir: Path) -> dict:
    """
    Generation by tech and region in 2050 (MWh).
    Source: outputs/gen_ann.csv (i, r, t, Value)
    Returns: {f"gen_{tech}_{region}": MWh}
    """
    path = run_dir / "outputs" / "gen_ann.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    df = df[df["t"] == TARGET_YEAR]
    result = {}
    for _, row in df.iterrows():
        result[f"gen_{row['i']}_{row['r']}"] = row["Value"]
    return result


def extract_transmission_regional_2050(run_dir: Path) -> dict:
    """
    Transmission capacity by corridor in 2050 (MW).
    Source: outputs/tran_out.csv (r, rr, trtype, t, Value)
    Returns: {f"tran_{r}_{rr}_{trtype}": MW}
    """
    path = run_dir / "outputs" / "tran_out.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    df = df[df["t"] == TARGET_YEAR]
    result = {}
    for _, row in df.iterrows():
        result[f"tran_{row['r']}_{row['rr']}_{row['trtype']}"] = row["Value"]
    return result


def extract_systemcost_regional_2050(run_dir: Path) -> dict:
    """
    System cost by category and region in 2050 ($).
    Source: outputs/systemcost_ba.csv (sys_costs, r, t, Value)
    Returns: {f"cost_{category}_{region}": $}
    """
    path = run_dir / "outputs" / "systemcost_ba.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    df = df[df["t"] == TARGET_YEAR]
    result = {}
    for _, row in df.iterrows():
        result[f"cost_{row['sys_costs']}_{row['r']}"] = row["Value"]
    return result


# ============================================================================
# MAIN PROCESSING
# ============================================================================

def process_runs(runs_dir: Path, batch_prefix: Optional[str] = None) -> pd.DataFrame:
    """Process all surrogate runs, extract regionally-resolved 2050 outputs."""
    rows = []
    run_dirs = sorted(runs_dir.iterdir()) if runs_dir.is_dir() else []

    print(f"Scanning runs in: {runs_dir}")
    print(f"Target year: {TARGET_YEAR}")
    n_found = 0
    n_processed = 0
    n_skipped = 0

    for run_path in run_dirs:
        if not run_path.is_dir():
            continue
        case_name = run_path.name

        if batch_prefix and not case_name.startswith(batch_prefix):
            continue

        features = parse_case_name(case_name)
        if features is None:
            continue

        n_found += 1

        if not (run_path / "outputs").exists():
            print(f"  Skipping {case_name}: no outputs/ directory")
            n_skipped += 1
            continue

        # Extract all regionally-resolved Y outputs for 2050
        cap_data = extract_capacity_regional_2050(run_path)
        gen_data = extract_generation_regional_2050(run_path)
        tran_data = extract_transmission_regional_2050(run_path)
        cost_data = extract_systemcost_regional_2050(run_path)

        if not cap_data and not gen_data:
            print(f"  Skipping {case_name}: no 2050 regional output data found")
            n_skipped += 1
            continue

        # Combine into single row
        row = {"case_name": case_name}
        row.update(features)
        row.update(cap_data)
        row.update(gen_data)
        row.update(tran_data)
        row.update(cost_data)
        rows.append(row)
        n_processed += 1

    print(f"\nSummary: Found {n_found} surrogate cases, processed {n_processed}, skipped {n_skipped}")

    if not rows:
        print("WARNING: No data extracted!")
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Sort columns: case_name, X features, Y outputs (grouped by type)
    x_num_cols = sorted([c for c in df.columns if c.startswith("x_") and not c.endswith("_label")])
    x_label_cols = sorted([c for c in df.columns if c.endswith("_label")])
    cap_cols = sorted([c for c in df.columns if c.startswith("cap_")])
    gen_cols = sorted([c for c in df.columns if c.startswith("gen_")])
    tran_cols = sorted([c for c in df.columns if c.startswith("tran_")])
    cost_cols = sorted([c for c in df.columns if c.startswith("cost_")])

    col_order = (
        ["case_name"] + x_num_cols + x_label_cols
        + cap_cols + gen_cols + tran_cols + cost_cols
    )
    col_order = [c for c in col_order if c in df.columns]
    df = df[col_order]

    # Fill missing Y values with 0
    y_cols = cap_cols + gen_cols + tran_cols + cost_cols
    for c in y_cols:
        if c in df.columns:
            df[c] = df[c].fillna(0.0)

    return df


def main():
    parser = argparse.ArgumentParser(
        description="Regional: Extract regionally-resolved 2050 outputs from ReEDS surrogate runs."
    )
    _HERE = Path(__file__).resolve().parent
    _STUDY_ROOT = _HERE.parent
    parser.add_argument(
        "--runs_dir", type=str, default=None,
        help="Path to runs directory. Default: <repo_root>/runs",
    )
    parser.add_argument(
        "--output", type=str,
        default=str(_STUDY_ROOT / "inputs" / "regional_ml.csv"),
        help="Output CSV filename.",
    )
    parser.add_argument(
        "--batch_prefix", type=str, default=None,
        help="Only process runs starting with this prefix (e.g., 'test0').",
    )
    parser.add_argument(
        "--parquet", action="store_true",
        help="Also save as parquet.",
    )
    args = parser.parse_args()

    # Determine runs directory
    if args.runs_dir:
        runs_dir = Path(args.runs_dir)
    else:
        repo_root = Path(__file__).resolve().parent.parent
        runs_dir = repo_root / "runs"

    if not runs_dir.exists():
        print(f"ERROR: Runs directory not found: {runs_dir}")
        return

    # Process
    df = process_runs(runs_dir, batch_prefix=args.batch_prefix)
    if df.empty:
        return

    # Summary
    x_cols = [c for c in df.columns if c.startswith("x_") and not c.endswith("_label")]
    cap_cols = [c for c in df.columns if c.startswith("cap_")]
    gen_cols = [c for c in df.columns if c.startswith("gen_")]
    tran_cols = [c for c in df.columns if c.startswith("tran_")]
    cost_cols = [c for c in df.columns if c.startswith("cost_")]

    print(f"\nDataset shape: {df.shape}")
    print(f"  X features: {len(x_cols)}")
    print(f"  Y capacity cols (tech x region): {len(cap_cols)}")
    print(f"  Y generation cols (tech x region): {len(gen_cols)}")
    print(f"  Y transmission cols (corridor): {len(tran_cols)}")
    print(f"  Y cost cols (category x region): {len(cost_cols)}")
    print(f"  Total Y columns: {len(cap_cols) + len(gen_cols) + len(tran_cols) + len(cost_cols)}")
    print(f"  Runs: {len(df)}")

    # Save
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"\nSaved: {output_path.resolve()}")

    # Numeric-only version (for direct ML use). case_name is kept as the first column
    # so downstream tools can join predictions back to specific runs.
    y_all = cap_cols + gen_cols + tran_cols + cost_cols
    ml_cols = ["case_name"] + x_cols + [c for c in y_all if c in df.columns]
    df_ml = df[ml_cols].copy()
    ml_path = output_path.with_stem(output_path.stem + "_numeric")
    df_ml.to_csv(ml_path, index=False)
    print(f"Saved numeric-only: {ml_path.resolve()}")

    if args.parquet:
        df.to_parquet(output_path.with_suffix(".parquet"), index=False)
        print(f"Saved parquet: {output_path.with_suffix('.parquet').resolve()}")


if __name__ == "__main__":
    main()
