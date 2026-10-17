from __future__ import annotations

from pathlib import Path

import h5py
import pandas as pd

import reeds


def write_handoff_h5(tables: dict[str, pd.DataFrame], path: str | Path, label_case: dict[str, str] | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        path.unlink()
    for key, df in tables.items():
        out = df.copy()
        for col in out.columns:
            if col == "Value":
                continue
            out[col] = out[col].astype(str)
            if label_case:
                out[col] = out[col].map(lambda x: label_case.get(x.lower(), x))
        if "Value" in out.columns and out["Value"].dtype != bool:
            out["Value"] = out["Value"].astype(float)
        reeds.io.write_to_h5(out, key, str(path), attrs={"written_by": "reeds.open.handoff"}, overwrite=True)
    return path


def read_handoff_h5(path: str | Path) -> dict[str, pd.DataFrame]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with h5py.File(path, "r") as f:
        keys = list(f.keys())
    out = {}
    for key in keys:
        df = reeds.io.read_h5(path, key)
        if "Value" in df.columns and len(df) == 0:
            df["Value"] = df["Value"].astype(float)
        out[key] = df
    return out
