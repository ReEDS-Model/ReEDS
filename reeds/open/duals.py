"""Every equation's dual, in the layout of a GAMS results.gdx equation record.

For each equation family and each row:

  Level     sum of the variable terms (GAMS moves constants to the right)
  Lower     right-hand side for =g= and =e= rows, -inf for =l=
  Upper     right-hand side for =l= and =e= rows, +inf for =g=
  Marginal  dual in the GAMS convention: d(objective)/d(right-hand side),
            so >= 0 on =g= rows and <= 0 on =l= rows when minimizing.
            The KKT gate verifies this convention for every tool.
  Slack     distance from the binding side (0 on =e= rows)

Marginals are raw: in objective units (x cost_scale, present value). ReEDS
converts the ones it reports as prices with (1/cost_scale)*(1/pvf_onm(t))
[/hours(h)], see report.reeds_outputs -> reqt_price, co2_price.

Level/Lower/Upper are evaluated on the Pyomo model at the given primal point
(the two models are identical, as gates 1-4 establish).
"""
from __future__ import annotations

from pathlib import Path

import polars as pl
import pyomo.environ as pyo
from pyomo.repn import generate_standard_repn

from .build_pyomo import rows
from .kkt import load_primal
from .prep import Prepared

INF = float("inf")


def equation_tables(m, P: Prepared, primal: dict, duals: dict) -> dict[str, pl.DataFrame]:
    load_primal(m, P, primal)
    out = {}
    for name, dom in P.con.items():
        con = getattr(m, name, None)
        if con is None or name not in duals:
            continue
        dual_map = dict(zip(rows(duals[name], dom.columns), duals[name]["dual"].to_list()))
        lev, lo, up, mar, sense = [], [], [], [], []
        for k in rows(dom):
            c = con[k[0] if len(k) == 1 else k]
            repn = generate_standard_repn(c.body, compute_values=True)
            c0 = repn.constant or 0.0
            level = sum(a * (v.value or 0.0) for v, a in zip(repn.linear_vars, repn.linear_coefs))
            lb = (c.lb - c0) if c.lb is not None else -INF
            ub = (c.ub - c0) if c.ub is not None else INF
            lev.append(level)
            lo.append(lb)
            up.append(ub)
            y = dual_map.get(k)
            mar.append(0.0 if y is None else y)
            sense.append("=e=" if c.equality else ("=g=" if c.ub is None else "=l="))
        df = dom.with_columns(
            pl.Series("Level", lev, dtype=pl.Float64),
            pl.Series("Lower", lo, dtype=pl.Float64),
            pl.Series("Upper", up, dtype=pl.Float64),
            pl.Series("Marginal", mar, dtype=pl.Float64),
            pl.Series("sense", sense),
        )
        df = df.with_columns(
            pl.when(pl.col("sense") == "=e=").then(0.0)
            .when(pl.col("sense") == "=g=").then(pl.col("Level") - pl.col("Lower"))
            .otherwise(pl.col("Upper") - pl.col("Level")).alias("Slack"))
        out[name] = df
    return out


def compare(tables: dict[str, dict[str, pl.DataFrame]], tol: float = 1e-6) -> pl.DataFrame:
    """One long table: every row of every equation, marginals side by side."""
    (ta, A), (tb, B) = list(tables.items())[:2]
    parts = []
    for name, a in A.items():
        b = B[name]
        keys = P_keys = [c for c in a.columns if c not in ("Level", "Lower", "Upper", "Marginal", "sense", "Slack")]
        j = a.select(P_keys + ["sense", "Slack", "Marginal"]).rename({"Marginal": f"Marginal_{ta}",
                                                                      "Slack": f"Slack_{ta}"}).join(
            b.select(keys + ["Slack", "Marginal"]).rename({"Marginal": f"Marginal_{tb}", "Slack": f"Slack_{tb}"}),
            on=keys, how="inner")
        j = j.with_columns(
            pl.concat_str([pl.col(k).cast(pl.Utf8) for k in keys], separator=".").alias("index"),
            pl.lit(name).alias("equation"),
            (pl.col(f"Marginal_{ta}") - pl.col(f"Marginal_{tb}")).abs().alias("abs_diff"),
        ).with_columns(
            ((pl.col(f"Slack_{ta}").abs() < tol) & (pl.col(f"Slack_{tb}").abs() < tol)).alias("binding_both"),
            (pl.col("abs_diff") > tol * pl.max_horizontal(pl.lit(1.0), pl.col(f"Marginal_{ta}").abs()))
            .alias("differs"),
        )
        parts.append(j.select(["equation", "index", "sense", f"Marginal_{ta}", f"Marginal_{tb}", "abs_diff",
                               f"Slack_{ta}", f"Slack_{tb}", "binding_both", "differs"]))
    return pl.concat(parts)


def summary(cmp: pl.DataFrame) -> pl.DataFrame:
    cols = [c for c in cmp.columns if c.startswith("Marginal_")]
    return (cmp.group_by("equation", maintain_order=True)
            .agg(pl.len().alias("rows"),
                 (pl.col(cols[0]).abs() > 1e-12).sum().alias(f"nonzero_{cols[0][9:]}"),
                 (pl.col(cols[1]).abs() > 1e-12).sum().alias(f"nonzero_{cols[1][9:]}"),
                 pl.col("differs").sum().alias("rows_differing"),
                 pl.col("abs_diff").max().alias("max_abs_diff"),
                 pl.col(cols[0]).abs().max().alias("max_abs_marginal")))


def write(tables: dict[str, pl.DataFrame], outdir: str | Path) -> Path:
    from .report import write_reeds_h5
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.write_csv(outdir / f"{name}.csv")
    write_reeds_h5(tables, outdir / "duals.h5")
    return outdir
