from __future__ import annotations

import argparse
import sys
from pathlib import Path

import gams.transfer as gt
import pandas as pd
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reeds.open import postsolve  # noqa: E402
from reeds.open.derive import derive  # noqa: E402
from reeds.open.derive_case import state_tables  # noqa: E402
from reeds.open.gdxcheck import compare  # noqa: E402


def gdx_records(container: gt.Container, name: str, dims: list[str], field: str) -> pl.DataFrame:
    if name not in container or container[name].records is None:
        return pl.DataFrame({d: pl.Series([], dtype=pl.Utf8) for d in dims} | {field: pl.Series([], dtype=pl.Float64)})
    df = container[name].records.copy()
    cols = list(df.columns[: len(dims)])
    df = df[cols + [field]].rename(columns=dict(zip(cols, dims)))
    for d in dims:
        df[d] = df[d].astype(str).str.lower()
    out = pl.from_pandas(df).with_columns(pl.col(field).cast(pl.Float64))
    return out.filter(pl.col(field) != 0.0) if field != "marginal" else out


def levels_from_gdx(path: Path) -> tuple[dict, dict]:
    c = gt.Container(load_from=str(path))
    lv = {name: gdx_records(c, name, dims, "level") for name, dims in postsolve.DUMP_VARIABLES.items()}
    eqm = {name: gdx_records(c, name, dims, "marginal") for name, dims in postsolve.DUMP_EQUATIONS.items()}
    lv["prm_solved"] = gdx_records(c, "prm", ["r", "t"], "value")
    return lv, eqm


def reference_tables(path: Path) -> dict[str, pl.DataFrame]:
    c = gt.Container(load_from=str(path))
    out = {}
    for name, sym in c.data.items():
        df = sym.records
        labels = list(sym.domain_labels) if getattr(sym, "domain_labels", None) else []
        if df is None:
            cols = labels + ["value"]
            out[name] = pl.DataFrame({k: pl.Series([], dtype=pl.Utf8) for k in labels} | {"value": pl.Series([], dtype=pl.Float64)})
            continue
        df = df.copy()
        dims = list(df.columns[: len(labels)])
        if isinstance(sym, gt.Set):
            df = df[dims]
            df["value"] = 1.0
        else:
            df = df[dims + ["value"]]
        df = df.rename(columns=dict(zip(dims, labels)))
        out[name] = pl.from_pandas(df.astype({d: str for d in labels})).with_columns(pl.col("value").cast(pl.Float64))
    return out


def mine_to_polars(df: pd.DataFrame) -> pl.DataFrame:
    out = df.copy()
    if "Value" in out.columns:
        out["Value"] = out["Value"].map(lambda x: 1.0 if x is True else float(x)).astype(float)
        out = out.rename(columns={"Value": "value"})
    for c in out.columns:
        if c != "value":
            out[c] = out[c].astype(str)
    out = out.rename(columns={"*": "uni"})
    return pl.from_pandas(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("casepath")
    ap.add_argument("year", type=int)
    ap.add_argument("alldata", help="gdx with every GAMS level and marginal at the end of the solve year")
    ap.add_argument("--stress", default=None)
    ap.add_argument("--tol", type=float, default=1e-9)
    ap.add_argument("--cache", default=None, help="pickle file holding the derived symbols (written if absent)")
    args = ap.parse_args(argv)
    case = Path(args.casepath).resolve()
    years = pd.read_csv(case / "inputs_case" / "modeledyears.csv").columns.astype(int).tolist()
    next_year = min([y for y in years if y > args.year], default=args.year)
    alldata = Path(args.alldata)
    state = state_tables(alldata, [y for y in years if y < args.year])
    import pickle
    if args.cache and Path(args.cache).is_file():
        S = pickle.load(open(args.cache, "rb"))
    else:
        S = derive(case / "inputs_case" / "inputs.h5", args.year, args.stress or f"{args.year}i0", state=state)
        if args.cache:
            pickle.dump(S, open(args.cache, "wb"))
    lv, eqm = levels_from_gdx(alldata)
    mine, domains = postsolve.reeds_data(S, lv, eqm, args.year, next_year)
    prev_years = [y for y in years if y < args.year]
    if prev_years:
        prev_ref = reference_tables(case / "handoff" / "reeds_data" / f"reeds_data_{prev_years[-1]}.gdx")
        prev_pd = {}
        for name, df in prev_ref.items():
            pdf = df.to_pandas().rename(columns={"value": "Value"})
            if name in mine and mine[name]["Value"].dtype == bool:
                pdf["Value"] = True
            prev_pd[name] = pdf
        mine = postsolve.accumulate(prev_pd, mine, domains)
    ref = reference_tables(case / "handoff" / "reeds_data" / f"reeds_data_{args.year}.gdx")
    n_bad = 0
    for name, ref_df in ref.items():
        if name not in mine:
            print(f"MISSING {name}: not produced by postsolve.reeds_data")
            n_bad += 1
            continue
        if not [c for c in ref_df.columns if c != "value"]:
            a = float(mine[name]["Value"].iloc[0]) if len(mine[name]) else 0.0
            b = float(ref_df["value"][0]) if ref_df.height else 0.0
            ok = abs(a - b) <= args.tol * max(1.0, abs(b))
            print(f"{'PASS' if ok else 'FAIL'} dump:{name:23s} mine {a} gams {b}")
            n_bad += 0 if ok else 1
            continue
        try:
            res = compare(f"dump:{name}", mine_to_polars(mine[name]), ref_df, tol=args.tol, show=4)
        except Exception as err:
            print(f"ERROR dump:{name}: {err}; mine columns {mine[name].dtypes.to_dict()}; ref columns {ref_df.schema}")
            n_bad += 1
            continue
        n_bad += 0 if res["pass"] else 1
    extra = [k for k in mine if k not in ref]
    if extra:
        print("produced but not in the reference:", extra)
    print(f"{len(ref) - n_bad}/{len(ref)} data-dump symbols match the GAMS reference")
    tc = postsolve.tc_phaseout_emissions(S, lv, [y for y in years if y <= args.year])
    tcref = reference_tables(case / "outputs" / "tc_phaseout_data" / f"emit_for_tc_phaseout_calc_{args.year}.gdx")
    for name in tcref:
        res = compare(f"tc:{name}", mine_to_polars(tc[name]), tcref[name], tol=args.tol, show=4)
        n_bad += 0 if res["pass"] else 1
    return 1 if n_bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
