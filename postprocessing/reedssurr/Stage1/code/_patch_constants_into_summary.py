"""One-shot script: scan training CSVs for zero-variance Y columns and
inject the resulting ``constant_outputs`` block into existing
``outputs/<layer>/summary.json`` files so the dashboard can surface those
columns as point-estimate predictions without re-training all models.

After ``surrogate_ml_models.py`` is next run, the trainer itself emits
``constant_outputs`` automatically and this script becomes a no-op.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

STAGE1 = Path(__file__).resolve().parent.parent
THRESHOLD = 1e-10
Y_PREFIXES = ("cap_", "cost_", "gen_", "runtime_", "tran_")

LAYERS = {
    "overall": STAGE1 / "inputs" / "overall_ml_numeric.csv",
    "regional": STAGE1 / "inputs" / "regional_ml_numeric.csv",
}

for layer, csv in LAYERS.items():
    summary_path = STAGE1 / "outputs" / layer / "summary.json"
    if not (csv.exists() and summary_path.exists()):
        print(f"[skip] {layer}: csv={csv.exists()}, summary={summary_path.exists()}")
        continue
    df = pd.read_csv(csv)
    y_cols = [c for c in df.columns if c.startswith(Y_PREFIXES)]
    Y = df[y_cols].to_numpy(dtype=float)
    y_var = Y.var(axis=0)
    constants: dict[str, float] = {}
    for i, var in enumerate(y_var):
        if var <= THRESHOLD:
            constants[y_cols[i]] = float(Y[:, i].mean())

    summary = json.loads(summary_path.read_text())
    summary["constant_outputs"] = constants
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"[ok]   {layer}: wrote {len(constants)} constant_outputs to {summary_path.name}")
    nz = sum(1 for v in constants.values() if v != 0.0)
    print(f"        ({nz} non-zero, {len(constants) - nz} all-zero)")
