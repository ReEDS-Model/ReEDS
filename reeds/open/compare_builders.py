from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reeds.open import build_linopy, build_pyoframe, inputs_h5, prep, solvers, validate_slice  # noqa: E402
from reeds.open.derive import Inputs, derive  # noqa: E402
from reeds.open.derive_case import to_case  # noqa: E402
from reeds.open.levels import Levels, state_tables  # noqa: E402
from reeds.open.run_case import HIGHS_OPTIONS, REDUCED_COST_VARIABLES  # noqa: E402

BUILDERS = {"pyoframe": build_pyoframe, "linopy": build_linopy}


def prepared_from_case(casedir: Path, year: int) -> prep.Prepared:
    stress_year = f"{year}i0"
    h5 = casedir / "inputs_case" / "inputs.h5"
    inputs_h5.ingest(casedir, stress_year)
    I = Inputs(h5)
    scalars = I.scalars("scalars")
    gsw = I.scalars("gswitches")
    years = pd.read_csv(casedir / "inputs_case" / "modeledyears.csv").columns.astype(int).tolist()
    tfix_years = [y for y in years if y < year]
    store = Levels(casedir / "handoff" / "open" / "levels.h5")
    missing = [y for y in tfix_years if not store.has_year(y)]
    if missing:
        raise RuntimeError(f"levels for {missing} are not in {store.path}; solve those years first")
    state = state_tables(store, tfix_years, bool(int(gsw["Sw_RemoveSmallNumbers"])), float(scalars["rhs_tolerance"]))
    S = derive(h5, year, stress_year, state=state)
    return prep.prepare(to_case(S, state=state))


def aligned_matrices(a: dict, b: dict, tol: float) -> dict:
    out = {"cols_a": len(a["cols"]), "cols_b": len(b["cols"]), "rows_a": len(a["rows"]), "rows_b": len(b["rows"]),
           "nnz_a": int(a["A"].nnz), "nnz_b": int(b["A"].nnz)}
    cols_only_a = sorted(set(a["cols"]) - set(b["cols"]))
    cols_only_b = sorted(set(b["cols"]) - set(a["cols"]))
    rows_only_a = sorted(set(a["rows"]) - set(b["rows"]))
    rows_only_b = sorted(set(b["rows"]) - set(a["rows"]))
    out.update({"cols_only_a": cols_only_a[:20], "n_cols_only_a": len(cols_only_a), "cols_only_b": cols_only_b[:20],
                "n_cols_only_b": len(cols_only_b), "rows_only_a": rows_only_a[:20], "n_rows_only_a": len(rows_only_a),
                "rows_only_b": rows_only_b[:20], "n_rows_only_b": len(rows_only_b)})
    if cols_only_a or cols_only_b or rows_only_a or rows_only_b:
        out["pass"] = False
        return out
    ca = {n: j for j, n in enumerate(a["cols"])}
    ra = {n: i for i, n in enumerate(a["rows"])}
    col_perm = np.array([ca[n] for n in b["cols"]])
    row_perm = np.array([ra[n] for n in b["rows"]])
    A_a = a["A"][row_perm][:, col_perm].tocsr()
    diff = (A_a - b["A"]).tocoo()
    ref = np.maximum(1.0, np.asarray(np.abs(b["A"])[diff.row, diff.col]).ravel()) if diff.nnz else np.array([])
    out["max_coefficient_rel_diff"] = float((np.abs(diff.data) / ref).max()) if diff.nnz else 0.0
    out["max_objective_rel_diff"] = float((np.abs(a["c"][col_perm] - b["c"]) / np.maximum(1.0, np.abs(b["c"]))).max())

    def bound_rel_diff(x, y):
        finite = np.isfinite(x) & np.isfinite(y)
        mismatch_inf = (np.isinf(x) | np.isinf(y)) & ~(np.isinf(x) & np.isinf(y) & (np.sign(x) == np.sign(y)))
        if mismatch_inf.any():
            return float("inf")
        if not finite.any():
            return 0.0
        return float((np.abs(x[finite] - y[finite]) / np.maximum(1.0, np.abs(y[finite]))).max())

    out["max_row_bound_rel_diff"] = max(bound_rel_diff(a["row_lo"][row_perm], b["row_lo"]), bound_rel_diff(a["row_up"][row_perm], b["row_up"]))
    out["max_col_bound_rel_diff"] = max(bound_rel_diff(a["col_lo"][col_perm], b["col_lo"]), bound_rel_diff(a["col_up"][col_perm], b["col_up"]))
    out["pass"] = all(out[k] <= tol for k in ("max_coefficient_rel_diff", "max_objective_rel_diff", "max_row_bound_rel_diff", "max_col_bound_rel_diff"))
    return out


def table_diff(a: pl.DataFrame, b: pl.DataFrame, value: str) -> float:
    keys = [c for c in a.columns if c != value]
    joined = a.join(b.rename({value: "_b"}), on=keys, how="full", coalesce=True)
    x = joined[value].fill_null(0.0).to_numpy()
    y = joined["_b"].fill_null(0.0).to_numpy()
    return float(np.abs(x - y).max()) if len(x) else 0.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build one case-year with pyoframe and linopy and compare matrices, solutions and timings")
    ap.add_argument("casepath", help="open-model case directory with handoff/open/levels.h5 holding the earlier years")
    ap.add_argument("year", type=int)
    ap.add_argument("--out", default=None, help="json report path (default: <casepath>/outputs/compare_builders_<year>.json)")
    ap.add_argument("--matrix-tol", type=float, default=1e-9, help="relative tolerance on coefficients, bounds and costs (the pyoframe matrix is read back from an MPS file)")
    args = ap.parse_args(argv)
    casedir = Path(args.casepath).resolve()
    out_path = Path(args.out) if args.out else casedir / "outputs" / f"compare_builders_{args.year}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    solvers.load_highs()
    P = prepared_from_case(casedir, args.year)
    report = {"case": casedir.name, "year": args.year, "size": P.summary()}
    models, matrices = {}, {}
    for name, module in BUILDERS.items():
        t0 = time.perf_counter()
        m = module.build(P)
        build_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        status = module.solve(m, silent=True, **HIGHS_OPTIONS)
        solve_s = time.perf_counter() - t0
        models[name] = m
        report[name] = {"build_s": build_s, "solve_s": solve_s, "status": status, "objective": module.objective_value(m)}
        print(f"{name}: build {build_s:.1f}s, solve {solve_s:.1f}s, status {status}, objective {module.objective_value(m):.10e}", flush=True)
    matrices["pyoframe"] = validate_slice.python_matrix(P, out_path.with_suffix(".mps"), "pyoframe")
    matrices["linopy"] = build_linopy.matrix(models["linopy"], validate_slice.VAR_DIMS, validate_slice.EQ_DIMS)
    report["matrix"] = aligned_matrices(matrices["pyoframe"], matrices["linopy"], args.matrix_tol)
    print("matrix identical" if report["matrix"]["pass"] else f"matrix differs: {report['matrix']}", flush=True)
    obj = {k: report[k]["objective"] for k in BUILDERS}
    report["objective_rel_diff"] = abs(obj["pyoframe"] - obj["linopy"]) / max(1.0, abs(obj["pyoframe"]))
    var_py, eq_py = build_pyoframe.solution_tables(models["pyoframe"], P)
    var_lp, eq_lp = build_linopy.solution_tables(models["linopy"], P)
    rc_py = build_pyoframe.reduced_costs(models["pyoframe"], P, REDUCED_COST_VARIABLES)
    rc_lp = build_linopy.reduced_costs(models["linopy"], P, REDUCED_COST_VARIABLES)
    report["max_primal_diff"] = {name: table_diff(var_py[name], var_lp[name], "level") for name in var_py}
    report["max_dual_diff"] = {name: table_diff(eq_py[name], eq_lp[name], "marginal") for name in eq_py if name in eq_lp}
    report["max_reduced_cost_diff"] = {name: table_diff(rc_py[name], rc_lp[name], "marginal") for name in rc_py}
    print(f"objective rel diff {report['objective_rel_diff']:.3e}")
    print(f"largest primal diff {max(report['max_primal_diff'].values()):.3e}, "
          f"largest dual diff {max(report['max_dual_diff'].values()):.3e}, "
          f"largest reduced-cost diff {max(report['max_reduced_cost_diff'].values()):.3e} "
          f"(alternative optima make these nonzero; the matrix and objective checks are the exact ones)")
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"report -> {out_path}")
    return 0 if report["matrix"]["pass"] and report["objective_rel_diff"] <= 1e-6 else 1


if __name__ == "__main__":
    raise SystemExit(main())
