import argparse
import json
import sys
import time
from pathlib import Path

import highspy
import numpy as np
import polars as pl
import pyoframe as pf
import scipy.sparse as sp

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reeds.open import build_linopy, build_pyoframe, contract, gdx_io, prep, solvers  # noqa: E402

BUILDERS = {"pyoframe": build_pyoframe, "linopy": build_linopy}
from reeds.open.prep import FLOW_IDX, GEN_IDX, ROUTE_IDX, RSC_IDX, V4  # noqa: E402

VAR_DIMS = {
    "LOAD": ("r", "h", "t"),
    "GEN": tuple(GEN_IDX),
    "CAP": tuple(V4),
    "CAP_ENERGY": tuple(V4),
    "INV": tuple(V4),
    "INV_ENERGY": tuple(V4),
    "INV_RSC": tuple(RSC_IDX),
    "STORAGE_IN": tuple(GEN_IDX),
    "STORAGE_LEVEL": tuple(GEN_IDX),
    "FLOW": tuple(FLOW_IDX),
    "CAPTRAN_ENERGY": tuple(ROUTE_IDX),
    "CAPTRAN_PRM": tuple(ROUTE_IDX),
    "EMIT": ("etype", "e", "r", "t"),
    "DROPPED": ("r", "h", "t"),
    "EXCESS": ("r", "h", "t"),
    "INV_REFURB": tuple(V4),
    "EXTRA_PRESCRIP": tuple(V4),
    "EXTRA_PRESCRIP_ENERGY": tuple(V4),
    "CAP_RSC": tuple(RSC_IDX),
    "UPGRADES": tuple(V4),
    "UPGRADES_RETIRE": tuple(V4),
    "INV_CAP_UP": tuple(RSC_IDX),
    "INV_ENER_UP": tuple(RSC_IDX),
    "OPRES": ("ortype", "i", "v", "r", "h", "t"),
    "OPRES_FLOW": ("ortype", "r", "rr", "h", "t"),
    "RAMPUP": ("i", "r", "h", "hh", "t"),
    "BIOUSED": ("bioclass", "r", "t"),
    "INVTRAN": tuple(ROUTE_IDX),
    "INVTRAN_AC": ("r", "rr", "tscbin", "t"),
    "TRAN_CAPEX_BINS": ("r", "rr", "tscbin", "t"),
    "INV_POI": ("r", "t"),
    "CAP_CONVERTER": ("r", "t"),
    "INV_CONVERTER": ("r", "t"),
    "CONVERSION": ("r", "h", "intype", "outtype", "t"),
    "CAPTRAN_GRP": ("transgrp", "transgrpp", "t"),
    "RECS": ("rpscat", "i", "st", "ast", "t"),
    "ACP_PURCHASES": ("rpscat", "st", "t"),
    "CAP_ABOVE_LIM": ("tg", "r", "t"),
    "GROWTH_BIN": ("gbin", "i", "st", "t"),
    "VGASBINQ_REGIONAL": ("fuelbin", "cendiv", "t"),
    "VGASBINQ_NATIONAL": ("fuelbin", "t"),
    "PRODUCE": ("p", "i", "v", "r", "h", "t"),
    "H2_FLOW": ("r", "rr", "h", "t"),
    "H2_TRANSPORT_INV": ("r", "rr", "t"),
    "H2_STOR_IN": ("h2_stor", "r", "h", "t"),
    "H2_STOR_OUT": ("h2_stor", "r", "h", "t"),
    "H2_STOR_LEVEL_SZN": ("h2_stor", "r", "actualszn", "t"),
    "H2_STOR_CAP": ("h2_stor", "r", "t"),
    "H2_STOR_INV": ("h2_stor", "r", "t"),
    "CREDIT_H2PTC": tuple(GEN_IDX),
    "AVAIL_SITE": ("x", "h", "t"),
    "CAP_SPUR": ("x", "t"),
    "INV_SPUR": ("x", "t"),
}

EQ_DIMS = {
    "eq_loadcon": ("r", "h", "t"),
    "eq_supply_demand_balance": ("r", "h", "t"),
    "eq_capacity_limit": tuple(GEN_IDX),
    "eq_capacity_limit_nd": tuple(GEN_IDX),
    "eq_cap_init_noret": tuple(V4),
    "eq_cap_new_noret": tuple(V4),
    "eq_cap_energy_new_noret": tuple(V4),
    "eq_rsc_inv_account": tuple(V4),
    "eq_rsc_INVlim": ("r", "i", "rscbin", "t"),
    "eq_storage_capacity": tuple(GEN_IDX),
    "eq_storage_duration": tuple(GEN_IDX),
    "eq_storage_level": tuple(GEN_IDX),
    "eq_CAPTRAN_ENERGY": tuple(ROUTE_IDX),
    "eq_CAPTRAN_PRM": tuple(ROUTE_IDX),
    "eq_transmission_limit": tuple(FLOW_IDX),
    "eq_vsc_flow": ("r", "h", "t"),
    "eq_CAP_CONVERTER": ("r", "t"),
    "eq_CONVERSION_limit_energy": ("r", "h", "t"),
    "eq_converter_max": ("r", "t"),
    "eq_emit_accounting": ("etype", "e", "r", "t"),
    "eq_annual_cap": ("eall", "t"),
    "eq_cap_init_retmo": tuple(V4),
    "eq_cap_init_retub": tuple(V4),
    "eq_cap_new_retmo": tuple(V4),
    "eq_cap_new_retub": tuple(V4),
    "eq_forceprescription_power": tuple(V4),
    "eq_forceprescription_energy": tuple(V4),
    "eq_refurblim": ("i", "r", "t"),
    "eq_cap_rsc": tuple(RSC_IDX),
    "eq_cap_upgrade": tuple(V4),
    "eq_cap_up": tuple(RSC_IDX),
    "eq_ener_up": tuple(RSC_IDX),
    "eq_OpRes_requirement": ("ortype", "r", "h", "t"),
    "eq_storage_opres": tuple(GEN_IDX),
    "eq_storage_thermalres": tuple(GEN_IDX),
    "eq_storage_in_cap": tuple(GEN_IDX),
    "eq_storage_in_minloading": ("i", "v", "r", "h", "hh", "t"),
    "eq_minloading": ("i", "v", "r", "h", "hh", "t"),
    "eq_battery_minduration": tuple(V4),
    "eq_ramping": ("i", "r", "h", "hh", "t"),
    "eq_dhyd_dispatch": ("i", "v", "r", "szn", "t"),
    "eq_Canadian_Imports": ("r", "szn", "t"),
    "eq_mingen_fixed": tuple(GEN_IDX),
    "eq_min_cf": ("i", "r", "t"),
    "eq_max_daily_cf": ("i", "r", "szn", "t"),
    "eq_caa_max_cf": tuple(V4),
    "eq_caa_rate_standard": ("st", "t"),
    "eq_bioused": ("r", "t"),
    "eq_biousedlimit": ("bioclass", "usda_region", "t"),
    "eq_batterymandate": ("st", "t"),
    "eq_INVTRAN_DC": tuple(ROUTE_IDX),
    "eq_INVTRAN_AC_forward": ("r", "rr", "tscbin", "t"),
    "eq_INVTRAN_AC_reverse": ("r", "rr", "tscbin", "t"),
    "eq_INVTRAN_AC": ("r", "rr", "t"),
    "eq_TRAN_CAPEX_BINS": ("r", "rr", "tscbin", "t"),
    "eq_invtran_exog": tuple(ROUTE_IDX),
    "eq_prescribed_transmission": tuple(ROUTE_IDX),
    "eq_POI_cap": ("r", "t"),
    "eq_CAPTRAN_GRP": ("transgrp", "transgrpp", "t"),
    "eq_transgrp_limit_energy": ("transgrp", "transgrpp", "h", "t"),
    "eq_firm_transfer_limit": ("transreg", "h", "t"),
    "eq_transmission_investment_max": ("t",),
    "eq_CAPTRAN_max": tuple(ROUTE_IDX),
    "eq_CAPTRAN_max_total": ("r", "rr", "t"),
    "eq_offshore_no_backflow": ("r", "rr", "trtype", "h", "t"),
    "eq_RGGI_cap": ("t",),
    "eq_growthlimit_relative": ("i", "st", "t"),
    "eq_growthbin_limit": ("gbin", "st", "tg", "t"),
    "eq_gasaccounting_regional": ("cendiv", "t"),
    "eq_gasaccounting_national": ("t",),
    "eq_gasbinlimit_regional": ("fuelbin", "cendiv", "t"),
    "eq_gasbinlimit_national": ("fuelbin", "t"),
    "eq_state_cap": ("st", "t"),
    "eq_CSAPR_Budget": ("csapr_group", "t"),
    "eq_CSAPR_Assurance": ("st", "t"),
    "eq_emit_rate_limit": ("e", "r", "t"),
    "eq_REC_Generation": ("rpscat", "i", "st", "t"),
    "eq_REC_Requirement": ("rpscat", "st", "t"),
    "eq_REC_BundleLimit": ("rpscat", "st", "ast", "t"),
    "eq_REC_unbundledLimit": ("rpscat", "st", "t"),
    "eq_REC_ooslim": ("rpscat", "st", "t"),
    "eq_REC_launder": ("rpscat", "st", "t"),
    "eq_RPS_OFSWind": ("st", "t"),
    "eq_interconnection_queues": ("tg", "r", "t"),
    "eq_prod_capacity_limit": tuple(GEN_IDX),
    "eq_h2_demand_regional": ("r", "h", "t"),
    "eq_h2_transport_caplimit": ("r", "rr", "h", "t"),
    "eq_h2_storage_level_szn": ("h2_stor", "r", "actualszn", "t"),
    "eq_h2_storage_capacity": ("h2_stor", "r", "t"),
    "eq_h2_min_storage_cap": ("r", "t"),
    "eq_h2_storage_flowlimit": ("h2_stor", "r", "h", "t"),
    "eq_h2_storage_caplimit_szn": ("h2_stor", "r", "actualszn", "t"),
    "eq_h2_ptc_region_balance": ("h2ptcreg", "t"),
    "eq_h2_ptc_region_hour_balance": ("h2ptcreg", "h", "t"),
    "eq_h2_ptc_creditgen": tuple(GEN_IDX),
    "eq_site_cf": ("x", "h", "t"),
    "eq_spurclip": ("x", "h", "t"),
    "eq_spur_noclip": ("x", "t"),
    "eq_capacity_limit_hybrid": ("r", "h", "t"),
    "eq_CAP_SPUR": ("x", "t"),
}

OBJECTIVE_ROWS = ("eq_objfn_slice", "eq_objfn_slice_inv", "eq_objfn_slice_op", "eq_objfn", "eq_objfn_inv", "eq_objfn_op")
OBJECTIVE_COLS = ("z_slice", "z_slice_inv", "z_slice_op", "z", "z_inv", "z_op")
CONSTANT_COL = "one"


def canonical(name: str) -> str:
    name = name.strip().replace("[", "(").replace("]", ")").replace("'", "").replace('"', "")
    return name.replace(" ", "").lower()


def symbol_of(name: str) -> str:
    return name.split("(", 1)[0]


def reorder(name: str, m: pf.Model, dims_by_symbol: dict) -> str:
    symbol = symbol_of(name)
    by_lower = {k.lower(): k for k in dims_by_symbol}
    if symbol not in by_lower or "(" not in name:
        return name
    labels = name[len(symbol) + 1:-1].split(",")
    dims_by_symbol = {k.lower(): v for k, v in dims_by_symbol.items()}
    py_dims = list(getattr(m, by_lower[symbol]).dimensions)
    gams_dims = list(dims_by_symbol[symbol])
    if py_dims == gams_dims:
        return name
    if sorted(py_dims) != sorted(gams_dims) or len(labels) != len(py_dims):
        raise ValueError(f"{symbol}: pyoframe dimensions {py_dims} do not match GAMS dimensions {gams_dims}")
    by_dim = dict(zip(py_dims, labels))
    return symbol + "(" + ",".join(by_dim[d] for d in gams_dims) + ")"


def record_names(df: pl.DataFrame, symbol: str, dims: tuple[str, ...]) -> pl.Series:
    parts = [pl.col(d).cast(pl.Utf8) for d in dims]
    return df.select(pl.concat_str([pl.lit(symbol + "(")] + [
        x for pair in zip(parts, [pl.lit(",")] * len(parts)) for x in pair][:-1] + [pl.lit(")")]
    ).alias("name"))["name"]


def python_matrix(P: prep.Prepared, mps_path: Path, builder: str = "pyoframe") -> dict:
    if builder == "linopy":
        lm = build_linopy.build(P)
        return build_linopy.matrix(lm, VAR_DIMS, EQ_DIMS)
    orig = pf.Model
    pf.Model = lambda solver="highs", **k: orig(solver=solver, solver_uses_variable_names=True)
    try:
        m = build_pyoframe.build(P)
    finally:
        pf.Model = orig
    m.write(str(mps_path))
    h = highspy.Highs()
    h.silent()
    h.readModel(str(mps_path))
    lp = h.getLp()
    ncol, nrow = lp.num_col_, lp.num_row_
    A = sp.csc_matrix((np.array(lp.a_matrix_.value_), np.array(lp.a_matrix_.index_),
                       np.array(lp.a_matrix_.start_)), shape=(nrow, ncol)).tocsr()
    cols = [reorder(canonical(c), m, VAR_DIMS) for c in lp.col_names_]
    rows = [reorder(canonical(r), m, EQ_DIMS) for r in lp.row_names_]
    c = np.array(lp.col_cost_)
    col_lo, col_up = np.array(lp.col_lower_), np.array(lp.col_upper_)
    row_lo, row_up = np.array(lp.row_lower_), np.array(lp.row_upper_)
    if CONSTANT_COL in cols:
        k = cols.index(CONSTANT_COL)
        const = A[:, k].toarray().ravel() * col_lo[k]
        row_lo = row_lo - const
        row_up = row_up - const
        keep = np.array([j != k for j in range(ncol)])
        A = A[:, keep]
        cols = [x for j, x in enumerate(cols) if j != k]
        c, col_lo, col_up = c[keep], col_lo[keep], col_up[keep]
    return {"model": m, "A": A.tocsr(), "cols": cols, "rows": rows, "c": c,
            "col_lo": col_lo, "col_up": col_up, "row_lo": row_lo, "row_up": row_up}


def gams_matrix(jac: dict, cost_scale: float) -> dict:
    rows = jac["rows"].with_columns(pl.col("name").map_elements(canonical, return_dtype=pl.Utf8))
    cols = jac["cols"].with_columns(pl.col("name").map_elements(canonical, return_dtype=pl.Utf8))
    row_id = dict(zip(rows["row"].to_list(), rows["name"].to_list()))
    col_id = dict(zip(cols["col"].to_list(), cols["name"].to_list()))
    A = jac["A"].with_columns(
        pl.col("row").replace_strict(row_id).alias("row_name"),
        pl.col("col").replace_strict(col_id).alias("col_name"))
    is_obj_row = pl.col("row_name").map_elements(lambda s: symbol_of(s) in OBJECTIVE_ROWS, return_dtype=pl.Boolean)
    is_obj_col = pl.col("col_name").map_elements(lambda s: symbol_of(s) in OBJECTIVE_COLS, return_dtype=pl.Boolean)
    obj_rows = A.filter(is_obj_row & ~is_obj_col)
    objective = (obj_rows.with_columns((-cost_scale * pl.col("value")).alias("value"))
                 .group_by("col_name").agg(pl.col("value").sum()))
    body = A.filter(~is_obj_row & ~is_obj_col).select(["row_name", "col_name", "value"])
    e = jac["e"]
    obj_row_names = {k: v for k, v in row_id.items() if symbol_of(v) in OBJECTIVE_ROWS}
    constant = 0.0
    for row, lower in zip(e["row"].to_list(), e["lower"].to_list()):
        if row in obj_row_names and symbol_of(obj_row_names[row]) != "eq_objfn":
            constant += float(lower)
    constant *= cost_scale
    bounds = pl.DataFrame({"row": e["row"].to_list()})
    for field in ("lower", "upper"):
        if field in e.columns:
            bounds = bounds.with_columns(e[field].alias(field))
        else:
            bounds = bounds.with_columns(pl.lit(0.0).alias(field))
    bounds = (bounds.with_columns(pl.col("row").replace_strict(row_id).alias("row_name"))
              .filter(~pl.col("row_name").map_elements(lambda s: symbol_of(s) in OBJECTIVE_ROWS,
                                                        return_dtype=pl.Boolean)))
    x = jac["x"]
    vb = pl.DataFrame({"col": x["col"].to_list()})
    vb = vb.with_columns(x["lower"].alias("lower") if "lower" in x.columns else pl.lit(0.0).alias("lower"))
    vb = vb.with_columns(x["upper"].alias("upper") if "upper" in x.columns else pl.lit(np.inf).alias("upper"))
    vb = (vb.with_columns(pl.col("col").replace_strict(col_id).alias("col_name"))
          .filter(~pl.col("col_name").map_elements(lambda s: symbol_of(s) in OBJECTIVE_COLS,
                                                    return_dtype=pl.Boolean)))
    return {"A": body, "objective": objective, "row_bounds": bounds, "col_bounds": vb, "constant": constant}


def compare_matrices(py: dict, g: dict, tol: float) -> dict:
    py_rows = set(py["rows"])
    py_cols = set(py["cols"])
    g_rows = set(g["row_bounds"]["row_name"].to_list())
    g_cols = set(g["col_bounds"]["col_name"].to_list())
    out = {
        "rows_python": len(py_rows), "rows_gams": len(g_rows),
        "cols_python": len(py_cols), "cols_gams": len(g_cols),
        "rows_only_python": sorted(py_rows - g_rows)[:50], "n_rows_only_python": len(py_rows - g_rows),
        "rows_only_gams": sorted(g_rows - py_rows)[:50], "n_rows_only_gams": len(g_rows - py_rows),
        "cols_only_python": sorted(py_cols - g_cols)[:50], "n_cols_only_python": len(py_cols - g_cols),
        "cols_only_gams": sorted(g_cols - py_cols)[:50], "n_cols_only_gams": len(g_cols - py_cols),
    }
    A = py["A"].tocoo()
    py_entries = pl.DataFrame({
        "row_name": [py["rows"][i] for i in A.row],
        "col_name": [py["cols"][j] for j in A.col],
        "value": A.data,
    }).group_by(["row_name", "col_name"]).agg(pl.col("value").sum()).filter(pl.col("value") != 0.0)
    g_entries = g["A"].group_by(["row_name", "col_name"]).agg(pl.col("value").sum()).filter(pl.col("value") != 0.0)
    joined = py_entries.join(g_entries.rename({"value": "gams"}), on=["row_name", "col_name"], how="full",
                             coalesce=True)
    joined = joined.with_columns(
        pl.col("value").fill_null(0.0), pl.col("gams").fill_null(0.0)).with_columns(
        ((pl.col("value") - pl.col("gams")).abs()
         / pl.max_horizontal(pl.lit(1.0), pl.col("gams").abs())).alias("rel_diff"))
    bad = joined.filter(pl.col("rel_diff") > tol)
    out["nonzeros_python"] = py_entries.height
    out["nonzeros_gams"] = g_entries.height
    out["coefficient_mismatches"] = bad.height
    out["max_coefficient_rel_diff"] = float(joined["rel_diff"].max() or 0.0)
    rb = pl.DataFrame({"row_name": py["rows"], "lo_py": py["row_lo"], "up_py": py["row_up"]}).join(
        g["row_bounds"].select(["row_name", "lower", "upper"]), on="row_name", how="inner")
    rb = rb.with_columns(
        (pl.col("lo_py") - pl.col("lower")).abs().alias("dlo"),
        (pl.col("up_py") - pl.col("upper")).abs().alias("dup"))
    rb = rb.with_columns(
        pl.when(pl.col("lo_py").is_infinite() & pl.col("lower").is_infinite()).then(0.0).otherwise(pl.col("dlo")).alias("dlo"),
        pl.when(pl.col("up_py").is_infinite() & pl.col("upper").is_infinite()).then(0.0).otherwise(pl.col("dup")).alias("dup"))
    scale = pl.max_horizontal(pl.lit(1.0), pl.col("lower").abs(), pl.col("upper").abs())
    rb_bad = rb.filter((pl.col("dlo") / scale > tol) | (pl.col("dup") / scale > tol))
    out["row_bound_mismatches"] = rb_bad.height
    cb = pl.DataFrame({"col_name": py["cols"], "lo_py": py["col_lo"], "up_py": py["col_up"]}).join(
        g["col_bounds"].select(["col_name", "lower", "upper"]), on="col_name", how="inner")
    cb_bad = cb.filter(
        ((pl.col("lo_py") - pl.col("lower")).abs() > tol) & ~(pl.col("lo_py").is_infinite() & pl.col("lower").is_infinite())
        | ((pl.col("up_py") - pl.col("upper")).abs() > tol) & ~(pl.col("up_py").is_infinite() & pl.col("upper").is_infinite()))
    out["col_bound_mismatches"] = cb_bad.height
    ob = pl.DataFrame({"col_name": py["cols"], "c_py": py["c"]}).join(
        g["objective"].rename({"col_name": "col_name", "value": "c_gams"}), on="col_name", how="full", coalesce=True)
    ob = ob.with_columns(pl.col("c_py").fill_null(0.0), pl.col("c_gams").fill_null(0.0)).with_columns(
        ((pl.col("c_py") - pl.col("c_gams")).abs() / pl.max_horizontal(pl.lit(1.0), pl.col("c_gams").abs())).alias("rel_diff"))
    ob_bad = ob.filter(pl.col("rel_diff") > tol)
    out["objective_mismatches"] = ob_bad.height
    out["max_objective_rel_diff"] = float(ob["rel_diff"].max() or 0.0)
    out["pass"] = (out["n_rows_only_python"] == out["n_rows_only_gams"] == out["n_cols_only_python"]
                   == out["n_cols_only_gams"] == 0
                   and out["coefficient_mismatches"] == 0 and out["row_bound_mismatches"] == 0
                   and out["col_bound_mismatches"] == 0 and out["objective_mismatches"] == 0)
    return out, {"coefficients": bad, "row_bounds": rb_bad, "col_bounds": cb_bad, "objective": ob_bad}


def gams_vectors(solution: dict, py: dict) -> dict:
    col_index = {name: j for j, name in enumerate(py["cols"])}
    row_index = {name: i for i, name in enumerate(py["rows"])}
    x = np.zeros(len(py["cols"]))
    xm = np.zeros(len(py["cols"]))
    missing_cols = 0
    for var, dims in VAR_DIMS.items():
        df = solution["variables"][var]
        if df.height == 0:
            continue
        names = record_names(df, var, dims).to_list()
        for name, lvl, mrg in zip(names, df["level"].to_list(), df["marginal"].to_list()):
            j = col_index.get(canonical(name))
            if j is None:
                missing_cols += (lvl != 0.0)
                continue
            x[j] = lvl
            xm[j] = mrg
    y = np.zeros(len(py["rows"]))
    missing_rows = 0
    for eq, dims in EQ_DIMS.items():
        df = solution["equations"][eq]
        if df.height == 0:
            continue
        names = record_names(df, eq, dims).to_list()
        for name, mrg in zip(names, df["marginal"].to_list()):
            i = row_index.get(canonical(name))
            if i is None:
                missing_rows += 1
                continue
            y[i] = mrg
    return {"x": x, "x_marginal": xm, "y": y, "gams_levels_without_python_column": int(missing_cols),
            "gams_rows_without_python_row": int(missing_rows)}


def primal_check(py: dict, x: np.ndarray, tol: float) -> dict:
    Ax = py["A"] @ x
    scale = np.maximum(1.0, np.maximum(np.abs(np.where(np.isfinite(py["row_lo"]), py["row_lo"], 0.0)),
                                       np.abs(np.where(np.isfinite(py["row_up"]), py["row_up"], 0.0))))
    viol = np.maximum(np.where(np.isfinite(py["row_lo"]), py["row_lo"] - Ax, 0.0),
                      np.where(np.isfinite(py["row_up"]), Ax - py["row_up"], 0.0)) / scale
    bviol = np.maximum(py["col_lo"] - x, x - py["col_up"]) / np.maximum(1.0, np.abs(x))
    worst = {}
    for i in np.argsort(viol)[-5:][::-1]:
        if viol[i] > tol:
            worst[py["rows"][i]] = float(viol[i])
    return {"max_scaled_row_violation": float(viol.max()), "max_scaled_bound_violation": float(bviol.max()),
            "objective_at_gams_point": float(py["c"] @ x), "worst_rows": worst,
            "pass": bool(viol.max() <= tol and bviol.max() <= tol)}


def kkt_check(py: dict, x: np.ndarray, y: np.ndarray, tol: float) -> dict:
    A = py["A"]
    Ax = A @ x
    z = py["c"] - A.T @ y
    scale_c = np.maximum(1.0, np.abs(py["c"]))
    at_lo = np.isfinite(py["col_lo"]) & (np.abs(x - py["col_lo"]) <= tol * np.maximum(1.0, np.abs(x)))
    at_up = np.isfinite(py["col_up"]) & (np.abs(x - py["col_up"]) <= tol * np.maximum(1.0, np.abs(x)))
    stationarity = np.where(at_lo, np.maximum(-z, 0.0), np.where(at_up, np.maximum(z, 0.0), np.abs(z))) / scale_c
    row_scale = np.maximum(1.0, np.abs(y))
    active_lo = np.isfinite(py["row_lo"]) & (np.abs(Ax - py["row_lo"]) <= tol * np.maximum(1.0, np.abs(Ax)))
    active_up = np.isfinite(py["row_up"]) & (np.abs(Ax - py["row_up"]) <= tol * np.maximum(1.0, np.abs(Ax)))
    equality = np.isfinite(py["row_lo"]) & np.isfinite(py["row_up"]) & (py["row_up"] - py["row_lo"] <= tol)
    dual_sign = np.where(equality, 0.0,
                         np.where(active_lo & ~active_up, np.maximum(-y, 0.0),
                                  np.where(active_up & ~active_lo, np.maximum(y, 0.0),
                                           np.where(active_lo & active_up, 0.0, np.abs(y))))) / row_scale
    worst_cols = {py["cols"][j]: float(stationarity[j]) for j in np.argsort(stationarity)[-5:][::-1]
                  if stationarity[j] > tol}
    worst_rows = {py["rows"][i]: float(dual_sign[i]) for i in np.argsort(dual_sign)[-5:][::-1]
                  if dual_sign[i] > tol}
    return {"max_stationarity_violation": float(stationarity.max()),
            "max_dual_sign_or_complementarity_violation": float(dual_sign.max()),
            "worst_columns": worst_cols, "worst_rows": worst_rows,
            "pass": bool(stationarity.max() <= tol and dual_sign.max() <= tol)}


def solve_python(m, highs_solver: str, builder: str = "pyoframe") -> dict:
    module = BUILDERS[builder]
    t0 = time.perf_counter()
    status = module.solve(m, solver=highs_solver)
    return {"objective": module.objective_value(m), "status": status, "solve_s": time.perf_counter() - t0}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Validate the pyoframe slice against a GAMS slice export")
    ap.add_argument("slice_dir", help="directory holding slice_solution_<year>.gdx and slice_jacobian_<year>.gdx")
    ap.add_argument("year", type=int)
    ap.add_argument("--tol", type=float, default=1e-6)
    ap.add_argument("--matrix-tol", type=float, default=1e-9)
    ap.add_argument("--highs-solver", default="choose")
    ap.add_argument("--out", help="output directory (default: <slice_dir>/validate_<year>)")
    ap.add_argument("--derived", action="store_true",
                    help="build the inputs with derive.py from inputs.h5 instead of reading the GAMS export")
    ap.add_argument("--stress", default=None, help="stress folder suffix for --derived (default <year>i0)")
    ap.add_argument("--prefix", default="slice", help="export file prefix: slice (slice_solve.gms) or port (model_template.gms)")
    ap.add_argument("--builder", default="pyoframe", choices=sorted(BUILDERS))
    args = ap.parse_args(argv)

    slice_dir = Path(args.slice_dir)
    out = Path(args.out) if args.out else slice_dir / f"validate_{args.year}"
    out.mkdir(parents=True, exist_ok=True)
    solvers.load_highs()

    solution_gdx = slice_dir / f"{args.prefix}_solution_{args.year}.gdx"
    jacobian_gdx = slice_dir / f"{args.prefix}_jacobian_{args.year}.gdx"
    case = gdx_io.load_case_from_gdx(solution_gdx)
    report_contract = None
    if args.derived:
        from reeds.open import derive_case
        from reeds.open.gdxcheck import compare
        h5 = slice_dir.parent / "inputs_case" / "inputs.h5"
        derived = derive_case.derive_case(h5, args.year, args.stress or f"{args.year}i0", solution_gdx)
        report_contract = {}
        n_bad = 0
        for name in contract.SCHEMA:
            if name not in case or name not in derived:
                continue
            kind, dims = contract.SCHEMA[name]
            if kind == "scalars":
                continue
            ref = case[name].with_columns([pl.col(d).cast(pl.Utf8) for d in dims])
            mine = derived[name].with_columns([pl.col(d).cast(pl.Utf8) for d in dims])
            if "t" in dims and name not in ("degrade_new", "emit_cap", "pvf_capital", "pvf_onm", "tfix", "trans_cap_delta"):
                ref = ref.filter(pl.col("t") == str(args.year))
                mine = mine.filter(pl.col("t") == str(args.year))
            res = compare(f"contract:{name}", mine, ref, tol=args.matrix_tol, show=4)
            report_contract[name] = res
            n_bad += 0 if res["pass"] else 1
        print(f"contract tables: {len(report_contract) - n_bad}/{len(report_contract)} match the GAMS export")
        case = derived
    problems = contract.check(case)
    if problems:
        print("CONTRACT PROBLEMS:\n  " + "\n  ".join(problems))
        return 2
    import shutil
    if (out / "case").exists():
        shutil.rmtree(out / "case")
    contract.save_case(case, out / "case")
    P = prep.prepare(case)
    report = {"year": args.year, "size": P.summary(), "objective_rows_off_domain": P.options["objective_rows_off_domain"],
              "inputs": "derived from inputs.h5" if args.derived else "GAMS export", "contract_tables": report_contract,
              "builder": args.builder}
    print(f"slice: {sum(report['size']['variables'].values()):,} columns, "
          f"{sum(report['size']['constraints'].values()):,} rows")

    t0 = time.perf_counter()
    py = python_matrix(P, out / "python_model.mps", args.builder)
    report["build_s"] = time.perf_counter() - t0
    print(f"{args.builder} build {report['build_s']:.1f}s")
    jac = gdx_io.load_jacobian(jacobian_gdx)
    g = gams_matrix(jac, case.scalar("cost_scale"))
    gate1, details = compare_matrices(py, g, args.matrix_tol)
    report["gate1_matrix"] = gate1
    for name, df in details.items():
        if df.height:
            df.write_csv(out / f"gate1_{name}_mismatches.csv")
    print(f"gate 1 matrix     {'PASS' if gate1['pass'] else 'FAIL'}  "
          f"rows {gate1['rows_python']}/{gate1['rows_gams']}  cols {gate1['cols_python']}/{gate1['cols_gams']}  "
          f"nnz {gate1['nonzeros_python']}/{gate1['nonzeros_gams']}  coef mismatches {gate1['coefficient_mismatches']}  "
          f"obj mismatches {gate1['objective_mismatches']}")

    solution = gdx_io.load_solution(solution_gdx, VAR_DIMS, EQ_DIMS)
    sol = solve_python(py["model"], args.highs_solver, args.builder)
    objconst = jac["objconst"] * case.scalar("cost_scale") + g["constant"]
    rel = abs(sol["objective"] + objconst - solution["objective"]) / max(1.0, abs(solution["objective"]))
    report["gate2_objective"] = {"python": sol["objective"], "gams": solution["objective"], "gams_constant": objconst,
                                 "rel_diff": rel, "status": sol["status"], "solve_s": sol["solve_s"], "pass": rel <= args.tol}
    print(f"gate 2 objective  {'PASS' if rel <= args.tol else 'FAIL'}  python {sol['objective']:.10g}  "
          f"gams {solution['objective']:.10g}  constant {objconst:.6g}  rel diff {rel:.3g}  ({sol['status']}, {sol['solve_s']:.1f}s)")

    vec = gams_vectors(solution, py)
    gate3 = primal_check(py, vec["x"], args.tol)
    gate3["gams_levels_without_python_column"] = vec["gams_levels_without_python_column"]
    gate3["gams_rows_without_python_row"] = vec["gams_rows_without_python_row"]
    gate3["objective_rel_diff"] = abs(gate3["objective_at_gams_point"] + objconst - solution["objective"]) / max(1.0, abs(solution["objective"]))
    gate3["pass"] = gate3["pass"] and gate3["objective_rel_diff"] <= args.tol
    report["gate3_gams_primal"] = gate3
    print(f"gate 3 primal     {'PASS' if gate3['pass'] else 'FAIL'}  max row violation {gate3['max_scaled_row_violation']:.3g}  "
          f"objective at GAMS point {gate3['objective_at_gams_point']:.10g}")

    gate4 = kkt_check(py, vec["x"], vec["y"], args.tol)
    report["gate4_kkt"] = gate4
    print(f"gate 4 kkt        {'PASS' if gate4['pass'] else 'FAIL'}  stationarity {gate4['max_stationarity_violation']:.3g}  "
          f"dual sign/complementarity {gate4['max_dual_sign_or_complementarity_violation']:.3g}")

    res = BUILDERS[args.builder].results(py["model"], P)
    for name, df in res["primal"].items():
        df.write_parquet(out / f"python_{name}.parquet")
    for name, df in res["dual"].items():
        df.write_parquet(out / f"python_dual_{name}.parquet")
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"report -> {out / 'report.json'}")
    return 0 if all(report[k]["pass"] for k in ("gate1_matrix", "gate2_objective", "gate3_gams_primal", "gate4_kkt")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
