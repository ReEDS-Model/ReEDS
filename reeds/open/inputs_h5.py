from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import reeds  # noqa: E402

MANIFEST = Path(__file__).resolve().parent / "gams_includes.csv"
WRITER = "inputs_h5.py"
GAMS_SCALAR = re.compile(r"^\s*scalar\s+(\w+)\s+(?:\"[^\"]*\"\s+)?/\s*([^/]*?)\s*/\s*;", re.I)



RANGE = re.compile(r"^(.*?)(\d+)\s*\*\s*(.*?)(\d+)$")


def _expand_label(label: str) -> list[str]:
    m = RANGE.match(label)
    if not m or m.group(1) != m.group(3):
        return [label]
    lo, hi = int(m.group(2)), int(m.group(4))
    return [f"{m.group(1)}{k}" for k in range(lo, hi + 1)]


def expand_ranges(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    if df.empty:
        return df
    for col in cols:
        if not df[col].astype(str).str.contains(r"\d\s*\*", regex=True).any():
            continue
        df = df.assign(**{col: df[col].astype(str).map(_expand_label)}).explode(col, ignore_index=True)
    return df

def _unique_columns(dims: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for d in dims:
        seen[d] = seen.get(d, 0) + 1
        out.append(d if seen[d] == 1 else f"{d}{seen[d]}")
    return out


def _data_lines(path: Path) -> list[list[str]]:
    rows = []
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if not raw.strip() or raw.lstrip().startswith("*"):
            continue
        rows.append([x.strip() for x in raw.split(",")])
    return rows


def read_long(path: Path, dims: list[str], kind: str) -> pd.DataFrame:
    rows = _data_lines(path)
    cols = _unique_columns(dims)
    if kind == "set":
        data = [r[: len(cols)] for r in rows]
        return expand_ranges(pd.DataFrame(data, columns=cols, dtype=str), cols)
    data = [r[: len(cols)] + [float(r[len(cols)])] for r in rows]
    df = pd.DataFrame(data, columns=cols + ["value"])
    df[cols] = df[cols].astype(str)
    return expand_ranges(df, cols)


def read_table(path: Path, dims: list[str]) -> pd.DataFrame:
    cols = _unique_columns(dims)
    if not _data_lines(path):
        return pd.DataFrame({c: pd.Series(dtype=str) for c in cols} | {"value": pd.Series(dtype=float)})
    wide = pd.read_csv(path, dtype=str, keep_default_na=False)
    wide.columns = [str(c).strip() for c in wide.columns]
    nrow = len(dims) - 1
    row_cols = list(wide.columns[:nrow])
    value_cols = list(wide.columns[nrow:])
    long = wide.melt(id_vars=row_cols, value_vars=value_cols, var_name=cols[-1], value_name="value")
    long = long.rename(columns=dict(zip(row_cols, cols[:-1])))
    long = long[long["value"].astype(str).str.strip() != ""]
    long["value"] = long["value"].map(_table_value)
    for c in cols:
        long[c] = long[c].astype(str).str.strip()
    return expand_ranges(long[cols + ["value"]].reset_index(drop=True), cols)


def _table_value(x: str) -> float:
    s = str(x).strip()
    if s.upper() == "YES":
        return 1.0
    if s.upper() == "NO":
        return 0.0
    return float(s)


def read_list(path: Path, dims: list[str]) -> pd.DataFrame:
    rows = _data_lines(path)
    cols = _unique_columns(dims) if dims else ["uni"]
    return expand_ranges(pd.DataFrame([r[: len(cols)] for r in rows], columns=cols, dtype=str), cols)


def read_scalar(path: Path) -> pd.DataFrame:
    rows = _data_lines(path)
    if len(rows) != 1 or len(rows[0]) != 1:
        raise ValueError(f"{path}: expected one scalar value")
    return pd.DataFrame({"value": [float(rows[0][0])]})


def read_gams_scalars(path: Path) -> pd.DataFrame:
    names, values = [], []
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        m = GAMS_SCALAR.match(raw)
        if m:
            names.append(m.group(1))
            values.append(float(m.group(2)))
    if not names:
        raise ValueError(f"{path}: no scalar definitions found")
    return pd.DataFrame({"name": names, "value": values})


def read_tc_phaseout(path: Path) -> pd.DataFrame:
    if path.suffix == ".gdx":
        import gams.transfer as gt
        df = gt.Container(load_from=str(path))["tc_phaseout_mult_t"].records.copy()
    else:
        from reeds.open.handoff import read_handoff_h5
        df = read_handoff_h5(path)["tc_phaseout_mult_t"].copy()
    df.columns = ["i", "t", "value"]
    df["i"] = df["i"].astype(str)
    df["t"] = df["t"].astype(str)
    df["value"] = df["value"].astype(float)
    return df


def h5_key(folder: str, file: str, stress_year: str | None) -> str:
    stem = Path(file).stem
    if folder == "rep":
        return f"rep__{stem}"
    if folder == "stress":
        return f"stress__{stem}__{stress_year}"
    return stem


def resolve_file(file: str, switches: dict) -> str:
    def sub(m):
        return str(switches[m.group(1)])
    return re.sub(r"%(\w+)%", sub, file)


def write(h5path: Path, key: str, df: pd.DataFrame, attrs: dict) -> None:
    with h5py.File(h5path, "a") as f:
        if key in f:
            if f[key].attrs.get("written_by", "") != WRITER:
                raise ValueError(f"{key} already exists in {h5path} and was not written by {WRITER}")
            del f[key]
    if "value" in df.columns:
        df = df.copy()
        df["value"] = df["value"].astype(np.float64)
    reeds.io.write_to_h5(df, key, str(h5path), attrs={**attrs, "written_by": WRITER})


def ingest(casepath: Path, stress_year: str, manifest: Path = MANIFEST) -> dict:
    inputs_case = casepath / "inputs_case"
    h5path = inputs_case / "inputs.h5"
    man = pl.read_csv(manifest).fill_null("")
    switches = {r["name"]: r["value"] for r in read_gams_scalars(inputs_case / "gswitches.txt").to_dict("records")}
    switches_raw = reeds.io.get_switches(casepath).to_dict()
    written, missing = [], []
    for row in man.to_dicts():
        file = resolve_file(row["file"], switches_raw)
        folder = row["folder"]
        if folder == "rep":
            path = inputs_case / "rep" / file
        elif folder == "stress":
            path = inputs_case / f"stress{stress_year}" / file
        else:
            path = inputs_case / file
        key = h5_key(folder, file, stress_year)
        if not path.is_file():
            missing.append((key, str(path)))
            continue
        dims = [d for d in row["dims"].split(",") if d]
        layout = row["layout"]
        if layout == "gams_scalars":
            df = read_gams_scalars(path)
            gamstype = "parameter"
        elif layout == "scalar":
            df = read_scalar(path)
            gamstype = "parameter"
        elif layout == "table":
            df = read_table(path, dims)
            gamstype = "parameter"
        elif layout == "list":
            df = read_list(path, dims)
            gamstype = "set"
        else:
            df = read_long(path, dims, row["kind"])
            gamstype = "set" if row["kind"] == "set" else "parameter"
        attrs = {"gamstype": gamstype, "symbol": row["symbol"], "source": str(path.relative_to(casepath)),
                 "layout": layout, "dims": row["dims"], "gams_source": f"{row['source']}:{row['line']}"}
        write(h5path, key, df, attrs)
        written.append(key)
    switches_df = pd.read_csv(inputs_case / "switches.csv", header=None, names=["name", "setting"], dtype=str, keep_default_na=False)
    write(h5path, "switches", switches_df,
          {"gamstype": "set", "symbol": "switches", "source": "inputs_case/switches.csv", "layout": "list",
           "dims": "name,setting", "gams_source": "runreeds.py"})
    written.append("switches")
    year = stress_year.split("i")[0]
    tc = casepath / "outputs" / "tc_phaseout_data" / f"tc_phaseout_mult_{year}.h5"
    if not tc.is_file() and tc.with_suffix(".gdx").is_file():
        tc = tc.with_suffix(".gdx")
    if tc.is_file():
        write(h5path, f"tc_phaseout_mult_t__{year}", read_tc_phaseout(tc),
              {"gamstype": "parameter", "symbol": "tc_phaseout_mult_t", "source": str(tc.relative_to(casepath)),
               "layout": "long", "dims": "i,t", "gams_source": "2_financials.gms:4"})
        written.append(f"tc_phaseout_mult_t__{year}")
    else:
        missing.append((f"tc_phaseout_mult_t__{year}", str(tc)))
    return {"written": written, "missing": missing, "h5": h5path}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Load every CSV and text input the GAMS core reads into inputs.h5")
    ap.add_argument("casepath")
    ap.add_argument("stress_year", help="stress folder suffix, for example 2030i0")
    args = ap.parse_args()
    out = ingest(Path(args.casepath).resolve(), args.stress_year)
    print(f"wrote {len(out['written'])} keys to {out['h5']}")
    if out["missing"]:
        print(f"{len(out['missing'])} manifest entries had no file in this case (switch-gated includes):")
        for key, path in out["missing"]:
            print(f"  {key}: {path}")
