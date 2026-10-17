from __future__ import annotations

import argparse
import sys
from pathlib import Path

import gams.transfer as gt
import h5py
import pandas as pd
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import reeds  # noqa: E402
from reeds.open import report_case  # noqa: E402
from reeds.open.derive import Inputs, derive  # noqa: E402
from reeds.open.derive_case import state_tables  # noqa: E402
from reeds.open.derive_temporal import tc_phaseout_mult_all_years  # noqa: E402
from reeds.open.report_ctx import EQ_DIMS, REDUCED_COST_VARIABLES, VAR_DIMS, Ctx, empty  # noqa: E402

SKIP_PAST_YEARS = {"reduced_cost"}


def records(c: gt.Container, name: str, dims: list[str], field: str) -> pl.DataFrame:
    if name not in c or c[name].records is None:
        return empty(dims)
    df = c[name].records.copy()
    cols = list(df.columns[: len(dims)])
    df = df[cols + [field]].rename(columns=dict(zip(cols + [field], dims + ["value"])))
    for d in dims:
        df[d] = df[d].astype(str).str.lower()
    out = pl.from_pandas(df).with_columns(pl.col("value").cast(pl.Float64))
    return out.filter(pl.col("value") != 0.0)


def ctx_from_gdx(S, years: list[int], alldata: Path) -> Ctx:
    c = gt.Container(load_from=str(alldata))
    lv = {name: records(c, name, dims, "level") for name, dims in VAR_DIMS.items() if name in c}
    eqm = {name: records(c, name, dims, "marginal") for name, dims in EQ_DIMS.items() if name in c}
    rc = {name: records(c, name, VAR_DIMS[name], "marginal") for name in REDUCED_COST_VARIABLES}
    z_rep = {int(k): float(v) for k, v in zip(c["z_rep"].records.iloc[:, 0], c["z_rep"].records["value"])}
    objfn = float(c["Z"].records["level"][0])
    return Ctx(S=S, years=years, lv=lv, eqm=eqm, rc=rc, h_t=empty(["h", "t"]).drop("value"), h_stress_t=empty(["h", "t"]).drop("value"),
               hours_t=empty(["h", "t"]), prm=records(c, "prm", ["r", "t"], "value"), co2_emit_rate_r=records(c, "co2_emit_rate_r", ["r", "t"], "value"),
               z_rep=z_rep, objfn_raw=objfn)


def reference(c: gt.Container, name: str) -> pl.DataFrame | None:
    low = {k.lower(): k for k in c.data}
    if name.lower() not in low:
        return None
    sym = c[low[name.lower()]]
    df = sym.records
    labels = list(sym.domain_labels) if getattr(sym, "domain_labels", None) else []
    ndim = len(sym.domain)
    if df is None:
        return pl.DataFrame({f"d{k}": pl.Series([], dtype=pl.Utf8) for k in range(ndim)} | {"value": pl.Series([], dtype=pl.Float64)})
    df = df.copy()
    cols = list(df.columns[:ndim])
    if isinstance(sym, gt.Set):
        df = df[cols]
        df["value"] = 1.0
    else:
        df = df[cols + ["value"]]
    df = df.rename(columns=dict(zip(cols, [f"d{k}" for k in range(ndim)])))
    out = pl.from_pandas(df.astype({f"d{k}": str for k in range(ndim)}))
    out = out.with_columns([pl.col(f"d{k}").str.to_lowercase() for k in range(ndim)] + [pl.col("value").cast(pl.Float64)])
    return out.filter(pl.col("value") != 0.0)


def reference_h5(path: Path, key: str) -> pl.DataFrame | None:
    with h5py.File(path, "r") as f:
        if key not in f:
            return None
    df = reeds.io.read_h5(path, key)
    if "Value" not in df.columns:
        df["Value"] = 1.0
    elif not pd.api.types.is_numeric_dtype(df["Value"]):
        df["Value"] = df["Value"].map(lambda x: 1.0 if x in (True, "", b"") else float(x))
    ndim = len(df.columns) - 1
    df.columns = [f"d{k}" for k in range(ndim)] + ["value"]
    out = pl.from_pandas(df.astype({f"d{k}": str for k in range(ndim)}))
    out = out.with_columns([pl.col(f"d{k}").str.to_lowercase() for k in range(ndim)] + [pl.col("value").cast(pl.Float64)])
    return out.filter(pl.col("value") != 0.0)


def compare(name: str, mine: pd.DataFrame, ref: pl.DataFrame, rtol: float, atol: float, years_only: list[str] | None) -> tuple[bool, str]:
    pdf = mine.copy()
    ndim = len(pdf.columns) - 1
    pdf.columns = [f"d{k}" for k in range(ndim)] + ["value"]
    if not pd.api.types.is_numeric_dtype(pdf["value"]):
        pdf["value"] = pdf["value"].map(lambda x: 1.0 if x in (True, "") else float(x))
    m = pl.from_pandas(pdf.astype({f"d{k}": str for k in range(ndim)})).with_columns([pl.col(f"d{k}").str.to_lowercase() for k in range(ndim)] + [pl.col("value").cast(pl.Float64)])
    m = m.filter(pl.col("value") != 0.0)
    keys = [f"d{k}" for k in range(ndim)]
    if ref.width - 1 != ndim:
        return False, f"dimension mismatch mine {ndim} gams {ref.width - 1}"
    if years_only is not None and ndim:
        tcol = keys[-1]
        m = m.filter(pl.col(tcol).is_in(years_only))
        ref = ref.filter(pl.col(tcol).is_in(years_only))
    if ndim == 0:
        a = float(m["value"][0]) if m.height else 0.0
        b = float(ref["value"][0]) if ref.height else 0.0
        ok = abs(a - b) <= atol + rtol * abs(b)
        return ok, f"mine {a:.10g} gams {b:.10g}"
    j = m.join(ref, on=keys, how="full", coalesce=True, suffix="_g")
    j = j.with_columns([pl.col("value").fill_null(0.0), pl.col("value_g").fill_null(0.0)])
    j = j.with_columns((pl.col("value") - pl.col("value_g")).abs().alias("d"))
    bad = j.filter(pl.col("d") > atol + rtol * pl.col("value_g").abs())
    only_mine = int(m.join(ref, on=keys, how="anti").height)
    only_gams = int(ref.join(m, on=keys, how="anti").height)
    worst = bad.sort("d", descending=True).head(3)
    detail = ""
    if bad.height:
        detail = " worst: " + "; ".join(f"{tuple(row[k] for k in keys)} mine {row['value']:.6g} gams {row['value_g']:.6g}" for row in worst.iter_rows(named=True))
    return bad.height == 0, f"mine {m.height:6d} gams {ref.height:6d} only_mine {only_mine:5d} only_gams {only_gams:5d} mismatches {bad.height:5d}{detail}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run the Python reporter on GAMS levels and compare with the GAMS report outputs")
    ap.add_argument("casepath")
    ap.add_argument("alldata", help="gdx with every GAMS level and marginal after the last solve year")
    ap.add_argument("--rtol", type=float, default=1e-6)
    ap.add_argument("--atol", type=float, default=1e-6)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--reference_outputs", default=None, help="outputs folder of the GAMS run (default <casepath>/outputs)")
    ap.add_argument("--iterations", default="", help="final stress iteration per year, e.g. 2030=4,2035=4 (others 0)")
    args = ap.parse_args(argv)
    case = Path(args.casepath).resolve()
    years = pd.read_csv(case / "inputs_case" / "modeledyears.csv").columns.astype(int).tolist()
    last = years[-1]
    alldata = Path(args.alldata)
    state = state_tables(alldata, years)
    h5 = case / "inputs_case" / "inputs.h5"
    iterations = {y: 0 for y in years}
    for item in [x for x in args.iterations.split(",") if x]:
        y, k = item.split("=")
        iterations[int(y)] = int(k)
    S = derive(h5, last, f"{last}i{iterations[last]}", state=state)
    for name, dims in (("cost_fom", ["i", "v", "r", "t"]), ("co2_captured_incentive", ["i", "v", "r", "t"])):
        S[name] = records(gt.Container(load_from=str(alldata)), name, dims, "value")
    print("cost_fom and co2_captured_incentive taken from the GAMS dump: GAMS adjusts them in 4_post_solve_adjustments.gms on unrounded upgrade levels")
    S["tc_phaseout_mult"] = tc_phaseout_mult_all_years(S, [str(y) for y in years])
    C = ctx_from_gdx(S, years, alldata)
    per_year = report_case.per_year_tables(Inputs(h5), years, iterations)
    C.h_t, C.h_stress_t, C.hours_t = per_year["h_t"], per_year["h_stress_t"], per_year["hours_t"]
    R = report_case.compute(C)
    dims, rename, _ = report_case.read_params(case)
    tables = report_case.assemble(R, report_case.input_tables(S, C, per_year), dims)
    ref_dir = Path(args.reference_outputs) if args.reference_outputs else case / "outputs"
    ref_h5 = ref_dir / "outputs.h5"
    if not ref_h5.is_file():
        raise FileNotFoundError(ref_h5)
    n_bad = 0
    names = args.only or list(tables)
    for name in names:
        ref = reference_h5(ref_h5, rename.get(name, name))
        if ref is None:
            ref = pl.DataFrame({f"d{k}": pl.Series([], dtype=pl.Utf8) for k in range(len(tables[name].columns) - 1)} | {"value": pl.Series([], dtype=pl.Float64)})
        years_only = [str(last)] if name in SKIP_PAST_YEARS else None
        ok, msg = compare(name, tables[name], ref, args.rtol, args.atol, years_only)
        print(f"{'PASS' if ok else 'FAIL'} {name:40s} {msg}")
        n_bad += 0 if ok else 1
    print(f"{len(names) - n_bad}/{len(names)} report symbols match the GAMS reference")
    if C.absent_variables:
        print(f"variables treated as zero: {sorted(C.absent_variables)}")
    if C.absent_equations:
        print(f"equations treated as zero marginal: {sorted(C.absent_equations)}")
    return 1 if n_bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
