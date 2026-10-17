from __future__ import annotations

import argparse
import datetime
import importlib.util
import os
import sys
from pathlib import Path

import pandas as pd
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import reeds  # noqa: E402
from reeds.open import build_linopy, build_pyoframe, inputs_h5, postsolve, prep, solvers  # noqa: E402
from reeds.open.derive import Inputs, derive  # noqa: E402
from reeds.open.derive_case import to_case  # noqa: E402
from reeds.open.handoff import read_handoff_h5, write_handoff_h5  # noqa: E402
from reeds.open.levels import Levels, state_tables  # noqa: E402

UNSUPPORTED = {"GSw_ValStr": "value streams", "GSw_NewValCapShrink": "post-solve valcap shrinking", "GSw_MGA_CostDelta": "modeling to generate alternatives"}
REDUCED_COST_VARIABLES = ("CAP", "INV", "INV_RSC")
BUILDERS = {"pyoframe": build_pyoframe, "linopy": build_linopy}
HIGHS_OPTIONS = {"solver": "ipm", "run_crossover": "on", "user_objective_scale": -4}


def as_text_years(tables: dict[str, pl.DataFrame]) -> dict[str, pl.DataFrame]:
    return {k: v.with_columns(pl.col("t").cast(pl.Utf8)) for k, v in tables.items()}


def tc_phaseout_module(casedir: Path):
    spec = importlib.util.spec_from_file_location("tc_phaseout", casedir / "reeds" / "core" / "solve" / "1_tc_phaseout.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def solve_year(casedir: Path, year: int, iteration: int, sw: pd.Series, years: list[int], store: Levels, builder: str) -> None:
    tic = datetime.datetime.now()
    tnext = min([y for y in years if y > year], default=year)
    stress_year = f"{year}i{iteration}"
    h5 = casedir / "inputs_case" / "inputs.h5"
    inputs_h5.ingest(casedir, stress_year)
    I = Inputs(h5)
    scalars = I.scalars("scalars")
    gsw = I.scalars("gswitches")
    tfix_years = [y for y in years if y < year]
    missing = [y for y in tfix_years if not store.has_year(y)]
    if missing:
        raise RuntimeError(f"levels for {missing} are not in {store.path}; solve those years first")
    state = state_tables(store, tfix_years, bool(int(gsw["Sw_RemoveSmallNumbers"])), float(scalars["rhs_tolerance"]))
    S = derive(h5, year, stress_year, state=state)
    case = to_case(S, state=state)
    reeds.log.toc(tic=tic, year=year, process="open/derive", path=str(casedir))

    tic = datetime.datetime.now()
    P = prep.prepare(case)
    module = BUILDERS[builder]
    if builder == "pyoframe":
        solvers.load_highs()
    m = module.build(P)
    log_dir = casedir / "lstfiles"
    log_dir.mkdir(exist_ok=True)
    status = module.solve(m, log_file=str(log_dir / f"highs_{year}i{iteration}.log"), silent=False, **HIGHS_OPTIONS)
    if "OPTIMAL" not in status.upper():
        raise RuntimeError(f"{year}i{iteration}: solver status {status}")
    objective = module.objective_value(m)
    variables, equations = module.solution_tables(m, P)
    reeds.log.toc(tic=tic, year=year, process=f"open/solve ({builder})", path=str(casedir))
    print(f"{year}i{iteration}: objective {objective:.6e}, {sum(v.height for v in variables.values()):,} columns, status {status}")

    tic = datetime.datetime.now()
    solved = [y for y in years if y <= year]
    lv = {}
    for name in postsolve.DUMP_VARIABLES:
        parts = [store.variable(name, tfix_years)] if any(store.has("var", name, y) for y in tfix_years) else []
        if name in variables:
            parts.append(variables[name])
        if parts:
            lv[name] = pl.concat(parts, how="vertical_relaxed")
    prm_parts = [store.table("derived", "prm", tfix_years)] if tfix_years else []
    prm_parts.append(S.prm.with_columns(pl.col("t").cast(pl.Int64)))
    lv["prm_solved"] = pl.concat(prm_parts, how="vertical_relaxed")
    lv = as_text_years(lv)
    eqm = as_text_years({name: equations[name] for name in postsolve.DUMP_EQUATIONS if name in equations})
    emit_r = postsolve.emit_r_tc(S, lv, solved)
    rate = postsolve.co2_emit_rate_r(S, lv, emit_r, year)
    derived = {
        "prm": S.prm.with_columns(pl.col("t").cast(pl.Int64)),
        "co2_emit_rate_r": rate.with_columns(pl.col("t").cast(pl.Int64)),
        "h_t": S.h.with_columns(pl.lit(year).alias("t")),
        "h_stress_t": S.h_stress.with_columns(pl.lit(year).alias("t")),
        "hours_t": S.hours.with_columns(pl.lit(year).alias("t")).select(["h", "t", "value"]),
    }
    if int(gsw["Sw_GrowthPenalties"]):
        derived["growth_bin_limit"] = S.growth_bin_limit.with_columns(pl.col("t").cast(pl.Int64))
    reduced = module.reduced_costs(m, P, REDUCED_COST_VARIABLES)
    store.save_year(year, iteration, objective, status, variables, equations, derived, reduced)
    dump, domains = postsolve.reeds_data(S, lv, eqm, year, tnext)
    previous = read_handoff_h5(casedir / "handoff" / "reeds_data" / f"reeds_data_{tfix_years[-1]}.h5") if tfix_years else None
    dump = postsolve.accumulate(previous, dump, domains)
    label_case = I.label_case()
    write_handoff_h5(dump, casedir / "handoff" / "reeds_data" / f"reeds_data_{year}.h5", label_case)
    tc = postsolve.tc_phaseout_emissions(S, lv, solved)
    write_handoff_h5(tc, casedir / "outputs" / "tc_phaseout_data" / f"emit_for_tc_phaseout_calc_{year}.h5", label_case)
    reeds.log.toc(tic=tic, year=year, process="open/postsolve", path=str(casedir))

    if tnext > int(sw.GSw_SkipRAyear):
        reeds.resource_adequacy.ra_calcs.main(t=year, tnext=tnext, casedir=str(casedir), iteration=iteration)


def run_year(casedir: Path, year: int, overwrite: bool = False, builder: str = "pyoframe") -> None:
    casedir = Path(casedir).resolve()
    os.chdir(casedir)
    sw = reeds.io.get_switches(casedir)
    for name, what in UNSUPPORTED.items():
        if float(sw[name]) != 0:
            raise NotImplementedError(f"{name}={sw[name]} ({what}) is not supported by the Python port")
    years = pd.read_csv(casedir / "inputs_case" / "modeledyears.csv").columns.astype(int).tolist()
    store = Levels(casedir / "handoff" / "open" / "levels.h5")
    tc = tc_phaseout_module(casedir)
    iterations = max(1, int(sw.GSw_PRM_StressIterateMax))
    for iteration in range(iterations):
        done = (store.has_year(year) and store.meta(year)["iteration"] >= iteration
                and (casedir / "handoff" / "reeds_data" / f"reeds_data_{year}.h5").is_file())
        if done and not overwrite:
            print(f"{year}i{iteration} already solved; continuing")
        else:
            tc.calc_tc_phaseout_mult(year, str(casedir))
            solve_year(casedir, year, iteration, sw, years, store, builder)
        if not (casedir / "inputs_case" / f"stress{year}i{iteration + 1}" / "set_h.csv").is_file():
            print(f"{year}: no new stress periods after iteration {iteration}, moving on")
            break
        print(f"{year}: adequacy threshold not met, iteration {iteration + 1}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Solve one ReEDS year with the Python port (no GAMS)")
    ap.add_argument("casepath")
    ap.add_argument("year", type=int)
    ap.add_argument("--overwrite", "-o", action="store_true")
    ap.add_argument("--builder", default="pyoframe", choices=sorted(BUILDERS))
    args = ap.parse_args(argv)
    log = reeds.log.makelog(scriptname=__file__, logpath=os.path.join(args.casepath, "gamslog.txt"))
    run_year(Path(args.casepath), args.year, overwrite=args.overwrite, builder=args.builder)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
