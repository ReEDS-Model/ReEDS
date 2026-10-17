"""Slice formulation in pyoframe (polars-backed, joins = GAMS $-conditions).

Every constraint is written as (GAMS LHS) - (GAMS RHS) <sense> 0 so that
``Constraint.dual`` equals the GAMS marginal before reporting adjustments.

Join rules used below:
* ``Param * Variable`` is an inner join: a missing coefficient drops the
  term, exactly like a GAMS parameter that is zero.
* Adding expressions with different label sets requires a modifier.
  ``U(...)`` takes the union (missing terms count as 0); ``.drop_extras()``
  restricts a variable to the labels of the other side (a $-filter).
"""
from __future__ import annotations

from functools import reduce

import polars as pl
import pyoframe as pf

from .algebra import FREE_VARIABLES, ROWS, Row
from .prep import Prepared


def P(df: pl.DataFrame) -> pf.Expression:
    return pf.Param(df)


def U(*terms):
    """Union-sum of expressions (labels missing in one term count as zero)."""
    return reduce(lambda a, b: a.keep_extras() + b.keep_extras(), terms)


def _row(m: pf.Model, C: dict, K: dict, name: str, row: Row) -> None:
    if name not in C or C[name].height == 0:
        return
    parts = [P(K[row.const])] if row.const else []
    for term in row.terms:
        if term.coef not in K or not hasattr(m, term.var):
            continue
        df = K[term.coef]
        if df.height == 0:
            continue
        v = getattr(m, term.var)
        if term.rename:
            v = v.rename(term.rename)
        e = P(df) * v
        if term.sum_by:
            e = e.sum_by(*term.sum_by)
        if term.post:
            e = e.rename(term.post)
        parts.append(e)
    expr = U(*parts)
    setattr(m, name, expr >= 0 if row.sense == ">=" else expr == 0)


def build(prep: Prepared, solver: str = "highs") -> pf.Model:
    V, C, K, O = prep.var, prep.con, prep.coef, prep.obj
    m = pf.Model(solver=solver)
    for name, dom in V.items():
        if name in FREE_VARIABLES:
            setattr(m, name, pf.Variable(dom))
        else:
            setattr(m, name, pf.Variable(dom, lb=0))
    for name, row in ROWS.items():
        _row(m, C, K, name, row)
    terms = [(P(df) * getattr(m, name)).sum() for name, df in O.items() if df.height]
    m.minimize = reduce(lambda a, b: a + b, terms)
    return m


def solve(m: pf.Model, log_file: str | None = None, silent: bool = True, **highs_options) -> str:
    m.attr.Silent = silent
    if log_file is not None:
        m.params.log_file = log_file
    for k, v in highs_options.items():
        setattr(m.params, k, v)
    m.optimize()
    return str(m.attr.TerminationStatus)


def objective_value(m: pf.Model) -> float:
    return float(m.objective.value)


def results(m: pf.Model, prep: Prepared) -> dict:
    out = {"objective": m.objective.value, "primal": {}, "dual": {}}
    for name in prep.var:
        out["primal"][name] = getattr(m, name).solution
    for name in prep.con:
        if hasattr(m, name):
            out["dual"][name] = getattr(m, name).dual
    return out


def solution_tables(m: pf.Model, prep: Prepared) -> tuple[dict[str, pl.DataFrame], dict[str, pl.DataFrame]]:
    variables, equations = {}, {}
    for name in prep.var:
        sol = getattr(m, name).solution.rename({"solution": "level"})
        variables[name] = sol.with_columns(pl.col("t").cast(pl.Int64))
    for name in prep.con:
        if not hasattr(m, name):
            continue
        dual = getattr(m, name).dual.rename({"dual": "marginal"})
        equations[name] = dual.with_columns(pl.col("t").cast(pl.Int64), pl.col("marginal").fill_null(0.0))
    return variables, equations


def reduced_costs(m: pf.Model, prep: Prepared, names: tuple[str, ...]) -> dict[str, pl.DataFrame]:
    out = {}
    for name in names:
        rc = getattr(m, name).attr.ReducedCost.rename({"ReducedCost": "marginal"})
        out[name] = rc.with_columns(pl.col("t").cast(pl.Int64))
    return out
