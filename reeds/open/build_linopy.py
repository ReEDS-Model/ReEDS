from __future__ import annotations

import numpy as np
import pandas as pd
import polars as pl
import xarray as xr
import linopy

from .algebra import FREE_VARIABLES, ROWS, Row, Term
from .prep import Prepared

COL = "_col"
ROW = "_row"


class LinopyModel:
    def __init__(self) -> None:
        self.m = linopy.Model()
        self.var_dom: dict[str, pl.DataFrame] = {}
        self.row_dom: dict[str, pl.DataFrame] = {}
        self.status: str | None = None
        self.condition: str | None = None

    def has_variable(self, name: str) -> bool:
        return name in self.var_dom

    def has_constraint(self, name: str) -> bool:
        return name in self.row_dom


def _labeled(lm: LinopyModel, name: str) -> pl.DataFrame:
    labels = lm.m.variables[name].labels.values.ravel()
    return lm.var_dom[name].with_columns(pl.Series(COL, labels))


def _term_entries(name: str, term: Term, K: dict, labeled: dict[str, pl.DataFrame]) -> pl.DataFrame | None:
    if term.coef not in K or term.var not in labeled:
        return None
    df = K[term.coef]
    if df.height == 0:
        return None
    vd = labeled[term.var]
    if term.rename:
        vd = vd.rename(term.rename)
    common = [c for c in df.columns if c != "value" and c in vd.columns]
    if not common:
        raise ValueError(f"{name}: coefficient table {term.coef} shares no index column with {term.var}")
    joined = df.join(vd, on=common, how="inner")
    keys = term.sum_by or [c for c in joined.columns if c not in ("value", COL)]
    out = joined.select(keys + [COL, "value"])
    if term.post:
        out = out.rename(term.post)
    return out


def _add_row(lm: LinopyModel, name: str, row: Row, C: dict, K: dict, labeled: dict[str, pl.DataFrame]) -> None:
    if name not in C or C[name].height == 0:
        return
    parts = []
    for term in row.terms:
        entries = _term_entries(name, term, K, labeled)
        if entries is not None:
            parts.append(entries)
    const = K[row.const] if row.const else None
    if not parts and const is None:
        raise ValueError(f"{name}: no coefficient table and no constant; the row set is undefined")
    key_sets = [sorted(c for c in p.columns if c not in (COL, "value")) for p in parts]
    if const is not None:
        key_sets.append(sorted(c for c in const.columns if c != "value"))
    if any(k != key_sets[0] for k in key_sets):
        raise ValueError(f"{name}: terms carry different row indices {key_sets}")
    keys = [c for c in (parts[0] if parts else const).columns if c not in (COL, "value")]
    row_tables = [p.select(keys) for p in parts]
    if const is not None:
        row_tables.append(const.select(keys))
    rows = pl.concat(row_tables).unique().sort(keys).with_row_index(ROW)
    n = rows.height
    dim = f"{name}_idx"
    if parts:
        entries = (pl.concat([p.select(keys + [COL, "value"]) for p in parts])
                   .join(rows, on=keys, how="inner")
                   .group_by([ROW, COL]).agg(pl.col("value").sum())
                   .filter(pl.col("value") != 0.0)
                   .sort([ROW, COL])
                   .with_columns(pl.int_range(pl.len()).over(ROW).alias("_pos")))
        width = int(entries["_pos"].max()) + 1 if entries.height else 1
        coeffs = np.zeros((n, width))
        vars_ = np.full((n, width), -1, dtype=np.int64)
        r = entries[ROW].to_numpy()
        pos = entries["_pos"].to_numpy()
        coeffs[r, pos] = entries["value"].to_numpy()
        vars_[r, pos] = entries[COL].to_numpy()
    else:
        coeffs = np.zeros((n, 1))
        vars_ = np.full((n, 1), -1, dtype=np.int64)
    if const is not None:
        rhs_values = -(rows.join(const.select(keys + ["value"]), on=keys, how="left")
                       .with_columns(pl.col("value").fill_null(0.0))["value"].to_numpy())
    else:
        rhs_values = np.zeros(n)
    data = xr.Dataset({"coeffs": ((dim, "_term"), coeffs), "vars": ((dim, "_term"), vars_)},
                      coords={dim: pd.RangeIndex(n)})
    expr = linopy.LinearExpression(data, lm.m)
    rhs = xr.DataArray(rhs_values, dims=[dim], coords={dim: pd.RangeIndex(n)})
    lm.m.add_constraints(expr, row.sense, rhs, name=name)
    lm.row_dom[name] = rows.select(keys)


def build(prep: Prepared) -> LinopyModel:
    V, C, K, O = prep.var, prep.con, prep.coef, prep.obj
    lm = LinopyModel()
    for name, dom in V.items():
        if dom.height == 0:
            continue
        lower = -np.inf if name in FREE_VARIABLES else 0.0
        lm.m.add_variables(lower=lower, coords=[pd.RangeIndex(dom.height, name=f"{name}_idx")], name=name)
        lm.var_dom[name] = dom
    labeled = {name: _labeled(lm, name) for name in lm.var_dom}
    for name, row in ROWS.items():
        _add_row(lm, name, row, C, K, labeled)
    obj_parts = []
    for name, df in O.items():
        if df.height == 0 or name not in labeled:
            continue
        keys = [c for c in df.columns if c != "value"]
        obj_parts.append(df.join(labeled[name], on=keys, how="inner").select([COL, "value"]))
    obj = pl.concat(obj_parts).group_by(COL).agg(pl.col("value").sum()).filter(pl.col("value") != 0.0).sort(COL)
    data = xr.Dataset({"coeffs": (("_term",), obj["value"].to_numpy()), "vars": (("_term",), obj[COL].to_numpy())})
    lm.m.add_objective(linopy.LinearExpression(data, lm.m), sense="min")
    return lm


def solve(lm: LinopyModel, log_file: str | None = None, silent: bool = True, **highs_options) -> str:
    options = dict(highs_options)
    options["output_flag"] = (log_file is not None) or (not silent)
    options["log_to_console"] = not silent
    lm.status, lm.condition = lm.m.solve(solver_name="highs", io_api="direct", log_fn=log_file, **options)
    return str(lm.condition)


def objective_value(lm: LinopyModel) -> float:
    return float(lm.m.objective.value)


def _primal(lm: LinopyModel, name: str, column: str) -> pl.DataFrame:
    dom = lm.var_dom[name]
    return dom.with_columns(pl.Series(column, np.asarray(lm.m.solution[name].values, dtype=float).ravel()))


def _dual(lm: LinopyModel, name: str, column: str) -> pl.DataFrame:
    rows = lm.row_dom[name]
    return rows.with_columns(pl.Series(column, np.asarray(lm.m.dual[name].values, dtype=float).ravel()))


def results(lm: LinopyModel, prep: Prepared) -> dict:
    out = {"objective": objective_value(lm), "primal": {}, "dual": {}}
    for name, dom in prep.var.items():
        if name in lm.var_dom:
            out["primal"][name] = _primal(lm, name, "solution")
        else:
            out["primal"][name] = dom.with_columns(pl.Series("solution", [], dtype=pl.Float64))
    for name in prep.con:
        if name in lm.row_dom:
            out["dual"][name] = _dual(lm, name, "dual")
    return out


def solution_tables(lm: LinopyModel, prep: Prepared) -> tuple[dict[str, pl.DataFrame], dict[str, pl.DataFrame]]:
    variables, equations = {}, {}
    for name, dom in prep.var.items():
        if name in lm.var_dom:
            sol = _primal(lm, name, "level")
        else:
            sol = dom.with_columns(pl.Series("level", [], dtype=pl.Float64))
        variables[name] = sol.with_columns(pl.col("t").cast(pl.Int64))
    for name in prep.con:
        if name not in lm.row_dom:
            continue
        equations[name] = _dual(lm, name, "marginal").with_columns(pl.col("t").cast(pl.Int64))
    return variables, equations


def _dual_vector(lm: LinopyModel, clabels: np.ndarray) -> np.ndarray:
    by_label = np.zeros(int(clabels.max()) + 1 if clabels.size else 0)
    for name in lm.row_dom:
        con = lm.m.constraints[name]
        by_label[con.labels.values.ravel()] = np.asarray(lm.m.dual[name].values, dtype=float).ravel()
    return by_label[clabels]


def reduced_costs(lm: LinopyModel, prep: Prepared, names: tuple[str, ...]) -> dict[str, pl.DataFrame]:
    M = lm.m.matrices
    y = _dual_vector(lm, M.clabels)
    rc = M.c - M.A.T @ y
    by_label = np.zeros(int(M.vlabels.max()) + 1)
    by_label[M.vlabels] = rc
    out = {}
    for name in names:
        dom = prep.var[name]
        if name in lm.var_dom:
            labels = lm.m.variables[name].labels.values.ravel()
            df = dom.with_columns(pl.Series("marginal", by_label[labels]))
        else:
            df = dom.with_columns(pl.Series("marginal", [], dtype=pl.Float64))
        out[name] = df.with_columns(pl.col("t").cast(pl.Int64))
    return out


def _names(df: pl.DataFrame, symbol: str, dims: tuple[str, ...]) -> list[str]:
    parts = [pl.col(d).cast(pl.Utf8) for d in dims]
    joined = pl.concat_str([p for pair in zip(parts, [pl.lit(",")] * len(parts)) for p in pair][:-1])
    return df.select((pl.lit(symbol.lower() + "(") + joined.str.to_lowercase() + pl.lit(")")).alias("name"))["name"].to_list()


def matrix(lm: LinopyModel, var_dims: dict, eq_dims: dict) -> dict:
    M = lm.m.matrices
    cols, col_labels = [], []
    for name in lm.var_dom:
        var = lm.m.variables[name]
        cols.extend(_names(lm.var_dom[name], name, tuple(var_dims[name])))
        col_labels.append(var.labels.values.ravel())
    rows, row_labels = [], []
    for name in lm.row_dom:
        con = lm.m.constraints[name]
        rows.extend(_names(lm.row_dom[name], name, tuple(eq_dims[name])))
        row_labels.append(con.labels.values.ravel())
    if not np.array_equal(np.concatenate(col_labels), M.vlabels):
        raise ValueError("variable labels are not in creation order; column names would be misaligned")
    if not np.array_equal(np.concatenate(row_labels), M.clabels):
        raise ValueError("constraint labels are not in creation order; row names would be misaligned")
    b = np.asarray(M.b, dtype=float)
    sense = np.asarray(M.sense)
    row_lo = np.where(sense == "<", -np.inf, b)
    row_up = np.where(sense == ">", np.inf, b)
    return {"model": lm, "A": M.A.tocsr(), "cols": cols, "rows": rows, "c": np.asarray(M.c, dtype=float),
            "col_lo": np.asarray(M.lb, dtype=float), "col_up": np.asarray(M.ub, dtype=float),
            "row_lo": row_lo, "row_up": row_up}
