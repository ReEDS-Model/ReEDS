from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
from pathlib import Path

import pandas as pd
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import reeds  # noqa: E402
from reeds.core.terminus import report_dump  # noqa: E402
from reeds.open import postsolve, report_core, report_costs, report_trans  # noqa: E402
from reeds.open.derive import Inputs, Symbols, derive, gams_round, isin, members  # noqa: E402
from reeds.open.derive_temporal import tc_phaseout_mult_all_years  # noqa: E402
from reeds.open.postsolve import _slice_scalar  # noqa: E402
from reeds.open.levels import Levels, state_tables  # noqa: E402
from reeds.open.report_core import Helpers, empty  # noqa: E402
from reeds.open.report_ctx import Ctx, from_store  # noqa: E402

INPUT_DUMPS = {
    "bcr": ["i"], "biosupply": ["usda_region", "bioclass", "*"], "cap_hyd_szn_adj": ["i", "allszn", "r"], "capture_rate": ["e", "i", "v", "r", "t"],
    "cf_adj_t": ["i", "c", "v", "t"], "cf_hyd": ["i", "allszn", "r", "allt"], "cost_cap": ["i", "t"], "cost_cap_energy": ["i", "t"],
    "cost_cap_fin_mult": ["i", "r", "t"], "cost_cap_fin_mult_noITC": ["i", "r", "t"], "cost_hurdle": ["r", "rr", "allt"], "cost_scale": [],
    "cost_vom": ["i", "v", "r", "t"], "cendiv": ["*"], "degrade_annual": ["i"], "e": ["eall"], "emit_rate": ["etype", "eall", "i", "v", "r", "t"],
    "fuel_price": ["i", "r", "t"], "fuel2tech": ["f", "i"], "h_szn": ["allh", "allszn"], "heat_rate": ["i", "v", "r", "t"],
    "hierarchy": ["r", "nercr", "transreg", "transgrp", "cendiv", "st", "interconnect", "country", "usda_region", "h2ptcreg", "hurdlereg", "gasreg", "ccreg"],
    "hours": ["allh"], "hydmin": ["i", "r", "allszn"], "ilr": ["i"], "outage_scheduled_h": ["i", "allh"], "pvf_capital": ["t"], "pvf_onm": ["t"], "r": ["*"],
    "rsc_dat": ["i", "r", "sc_cat", "rscbin"], "storage_duration": ["i"], "storage_duration_m": ["i", "v", "r"], "storage_eff": ["i", "t"],
    "szn_stress_t": ["allszn", "allt"], "tc_phaseout_mult": ["i", "v", "t"], "tranloss": ["r", "rr", "trtype"], "v": ["*"], "valcap_i": ["i"], "z_rep": ["t"],
}

OUTPUT_COLUMN_ORDER = {
    "tran_flow_all_rep": ["r", "rr", "allh", "t", "trtype"], "tran_flow_rep": ["r", "rr", "allh", "t", "trtype"],
    "tran_util_h_rep": ["r", "rr", "allh", "t", "trtype"],
}


def read_params(reeds_path: Path) -> tuple[dict[str, list[str]], dict[str, str], list[str]]:
    df = pd.read_csv(reeds_path / "reeds" / "core" / "terminus" / "report_params.csv", comment="#")
    dims: dict[str, list[str]] = {}
    inputs: list[str] = []
    rename: dict[str, str] = {}
    for _, row in df.iterrows():
        text = str(row["param"]).strip()
        m = re.match(r"^([A-Za-z0-9_]+)(?:\((.*)\))?$", text)
        if not m:
            raise ValueError(f"cannot parse report parameter {text!r}")
        name = m.group(1)
        if pd.notna(row["input"]) and int(row["input"]) == 1:
            inputs.append(name)
            continue
        dims[name] = [d.strip() for d in m.group(2).split(",")] if m.group(2) else []
        if isinstance(row["output_rename"], str) and row["output_rename"].strip():
            rename[name] = row["output_rename"].strip()
    return dims, rename, inputs


def per_year_tables(I: Inputs, years: list[int], iterations: dict[int, int]) -> dict[str, pl.DataFrame]:
    h_t, h_stress_t, hours_t, szn_stress_t = [], [], [], []
    rep_h = I.set("rep__set_h", ["h"])
    rep_hours = I.par("rep__numhours", ["h"])
    for y in years:
        tag = f"{y}i{iterations[y]}"
        stress_h = I.set(f"stress__set_h__{tag}", ["h"])
        stress_hours = I.par(f"stress__numhours__{tag}", ["h"])
        h_all = pl.concat([rep_h, stress_h]).unique(maintain_order=True).with_columns(pl.lit(str(y)).alias("t"))
        h_t.append(h_all)
        h_stress_t.append(stress_h.with_columns(pl.lit(str(y)).alias("t")))
        hours = pl.concat([rep_hours, stress_hours]).join(h_all.select("h"), on="h", how="semi").with_columns(pl.lit(str(y)).alias("t"))
        hours_t.append(hours.select(["h", "t", "value"]))
        szn_stress_t.append(I.set(f"stress__set_szn__{tag}", ["szn"]).with_columns(pl.lit(str(y)).alias("t")))
    return {"h_t": pl.concat(h_t), "h_stress_t": pl.concat(h_stress_t), "hours_t": pl.concat(hours_t), "szn_stress_t": pl.concat(szn_stress_t)}


def final_symbols(casedir: Path, years: list[int], store: Levels) -> tuple[Symbols, dict[int, int]]:
    iterations = {y: int(store.meta(y)["iteration"]) for y in years}
    last = years[-1]
    h5 = casedir / "inputs_case" / "inputs.h5"
    I = Inputs(h5)
    scalars = I.scalars("scalars")
    gsw = I.scalars("gswitches")
    state = state_tables(store, years, bool(int(gsw["Sw_RemoveSmallNumbers"])), float(scalars["rhs_tolerance"]))
    S = derive(h5, last, f"{last}i{iterations[last]}", state=state)
    return S, iterations


NEVER_ASSIGNED = {
    "cap_energy_new_out": ["i", "v", "r", "t"], "cap_out_ivrt": ["i", "v", "r", "t"], "cost_vom_rr": ["i", "v", "rr", "t"],
    "curt_rr": ["i", "r", "h", "t"], "curt_new": ["i", "r", "h", "t"],
}


def objective_constant(C: Ctx, year: int) -> float:
    S = C.S
    intra = float(S.sw["Sw_TransIntraCost"])
    if intra == 0:
        return 0.0
    poi = C.L("INV_POI").with_columns(pl.col("t").cast(pl.Int64))
    past = float(poi.filter(pl.col("t") < year)["value"].sum())
    pvf = S.pvf_onm.filter(pl.col("t") == str(year))
    if pvf.height != 1:
        raise KeyError(f"pvf_onm has {pvf.height} rows for {year}")
    return _slice_scalar(S, "cost_scale") * float(pvf["value"][0]) * intra * 1000.0 * float(S.sc["trans_fom_frac"]) * past


def add_objective_constant(C: Ctx) -> None:
    for y in C.years:
        C.z_rep[y] = C.z_rep[y] + objective_constant(C, y)
    C.objfn_raw = C.z_rep[C.years[-1]]


def compute(C: Ctx) -> dict[str, pl.DataFrame]:
    H = Helpers(C)
    R: dict = {}
    report_core.lcoe(H, R)
    report_core.requirements(H, R)
    report_core.policy_and_fuel(H, R)
    report_core.generation(H, R)
    report_core.water(H, R)
    report_core.reserves_and_losses(H, R)
    report_core.capacity(H, R)
    report_core.revenue(H, R)
    report_core.emissions(H, R)
    report_costs.capex_and_techba(H, R)
    report_costs.systemcost_ba(H, R)
    report_costs.error_check(H, R)
    report_costs.transmission(H, R)
    report_costs.production_and_loads(H, R)
    report_trans.interconnection_and_co2(H, R)
    report_trans.transmission_calcs(H, R)
    for name, dims in NEVER_ASSIGNED.items():
        R[name] = empty(dims)
    R["prm"] = C.prm
    R["cost_cap_fin_mult"] = C.S.cost_cap_fin_mult
    return R


def input_tables(S: Symbols, C: Ctx, per_year: dict[str, pl.DataFrame]) -> dict[str, pl.DataFrame]:
    out: dict[str, pl.DataFrame] = {}
    bio = pl.concat([S.biosupply_cap.with_columns(pl.lit("cap").alias("sc_cat")), S.biosupply_price.with_columns(pl.lit("price").alias("sc_cat"))])
    out["biosupply"] = bio.select(["usda_region", "bioclass", "sc_cat", "value"])
    out["cendiv"] = S.hierarchy.select("cendiv").unique(maintain_order=True)
    out["cost_scale"] = pl.DataFrame({"value": [report_core._slice_scalar(S, "cost_scale")]})
    out["outage_scheduled_h"] = S._outage_scheduled_h
    out["hydmin"] = postsolve.hydmin(S)
    out["szn_stress_t"] = per_year["szn_stress_t"]
    out["z_rep"] = pl.DataFrame({"t": [str(y) for y in C.years], "value": [C.z_rep[y] for y in C.years]})
    for name in INPUT_DUMPS:
        if name in out:
            continue
        if name not in S:
            raise KeyError(f"input dump {name} is not among the derived symbols")
        out[name] = S[name]
    return out


def assemble(R: dict, inputs: dict[str, pl.DataFrame], dims: dict[str, list[str]]) -> dict[str, pd.DataFrame]:
    tables: dict[str, pd.DataFrame] = {}
    missing = [name for name in dims if name not in R]
    if missing:
        raise KeyError(f"report outputs not produced: {missing}")
    for name, gdims in dims.items():
        df = R[name]
        if not isinstance(df, pl.DataFrame):
            tables[name] = pd.DataFrame({"Value": [float(df)]})
            continue
        cols = [c for c in df.columns if c != "value"]
        if len(cols) != len(gdims):
            raise ValueError(f"{name}: produced columns {cols} do not match report dimensions {gdims}")
        pdf = df.select(cols + ["value"]).to_pandas()
        pdf.columns = list(gdims) + ["Value"]
        if name in OUTPUT_COLUMN_ORDER:
            pdf = pdf[OUTPUT_COLUMN_ORDER[name] + ["Value"]]
        tables[name] = pdf
    for name, gdims in INPUT_DUMPS.items():
        df = inputs[name]
        cols = [c for c in df.columns if c != "value"]
        if len(cols) != len(gdims):
            raise ValueError(f"{name}: produced columns {cols} do not match dump dimensions {gdims}")
        pdf = df.select(cols + (["value"] if "value" in df.columns else [])).to_pandas()
        if "value" in df.columns:
            pdf.columns = list(gdims) + ["Value"]
        else:
            pdf.columns = list(gdims)
            pdf["Value"] = ""
        tables[name] = pdf
    return tables


def restore_case(df: pd.DataFrame, label_case: dict[str, str]) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if col == "Value":
            continue
        out[col] = out[col].map(lambda x: label_case.get(str(x).lower(), x))
    return out


def write_outputs(tables: dict[str, pd.DataFrame], outputs_path: Path, rename: dict[str, str], label_case: dict[str, str],
                  decimals: int = 6) -> None:
    h5path = outputs_path / "outputs.h5"
    if h5path.is_file():
        h5path.unlink()
    for name, df in tables.items():
        key = rename.get(name, name)
        out = restore_case(df, label_case)
        reeds.io.write_output_to_h5(df=out, key=key, filepath=str(h5path), overwrite=True)
        out.round(decimals).to_csv(outputs_path / f"{key}.csv", index=False)


DERIVED_INPUTS = {"cost_cap": ["i", "t"], "cost_cap_energy": ["i", "t"], "cost_cap_fin_mult_out": ["i", "r", "t"],
                  "rsc_dat": ["i", "r", "sc_cat", "rscbin"]}


def write_derived_inputs(S: Symbols, casedir: Path, label_case: dict[str, str]) -> Path:
    path = casedir / "inputs_case" / "inputs_derived.h5"
    if path.is_file():
        path.unlink()
    for name, gdims in DERIVED_INPUTS.items():
        df = S[name]
        cols = [c for c in df.columns if c != "value"]
        if cols != gdims:
            raise ValueError(f"{name}: derived columns {cols} do not match {gdims}")
        pdf = df.select(cols + ["value"]).to_pandas()
        pdf.columns = gdims + ["Value"]
        reeds.io.write_output_to_h5(df=restore_case(pdf, label_case), key=name, filepath=str(path), overwrite=True)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Write the ReEDS report outputs from the Python port's stored levels (no GAMS)")
    ap.add_argument("casepath")
    args = ap.parse_args(argv)
    casedir = Path(args.casepath).resolve()
    tic = datetime.datetime.now()
    reeds.log.makelog(scriptname=__file__, logpath=os.path.join(casedir, "gamslog.txt"))
    years = pd.read_csv(casedir / "inputs_case" / "modeledyears.csv").columns.astype(int).tolist()
    store = Levels(casedir / "handoff" / "open" / "levels.h5")
    missing = [y for y in years if not store.has_year(y)]
    if missing:
        raise RuntimeError(f"levels for {missing} are not in {store.path}")
    S, iterations = final_symbols(casedir, years, store)
    C = from_store(S, store, years)
    per_year = per_year_tables(Inputs(casedir / "inputs_case" / "inputs.h5"), years, iterations)
    C.h_t, C.h_stress_t, C.hours_t = per_year["h_t"], per_year["h_stress_t"], per_year["hours_t"]
    S["tc_phaseout_mult"] = tc_phaseout_mult_all_years(S, [str(y) for y in years])
    add_objective_constant(C)
    R = compute(C)
    dims, rename, _ = read_params(casedir)
    tables = assemble(R, input_tables(S, C, per_year), dims)
    outputs_path = casedir / "outputs"
    outputs_path.mkdir(exist_ok=True)
    label_case = Inputs(casedir / "inputs_case" / "inputs.h5").label_case()
    write_outputs(tables, outputs_path, rename, label_case)
    write_derived_inputs(S, casedir, label_case)
    report_dump.calculate_historical_capex.main(str(casedir))
    report_dump.postprocess_outputs(str(casedir), outputs_path=str(outputs_path))
    if C.absent_variables:
        print(f"variables treated as zero (not in the port): {sorted(C.absent_variables)}")
    if C.absent_equations:
        print(f"equations treated as zero marginal (not in the port): {sorted(C.absent_equations)}")
    reeds.log.toc(tic=tic, year=0, path=str(casedir), process="open/report_case.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
