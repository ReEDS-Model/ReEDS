from __future__ import annotations

from pathlib import Path

import gams.transfer as gt
import polars as pl


class GdxOracle:
    def __init__(self, path: str | Path):
        self.container = gt.Container(load_from=str(path))

    def table(self, name: str, dims: list[str] | None = None, field: str = "value") -> pl.DataFrame:
        sym = self.container[name]
        df = sym.records
        n = len(sym.domain)
        if df is None:
            cols = dims or [f"d{k}" for k in range(n)]
            return pl.DataFrame({c: pl.Series([], dtype=pl.Utf8) for c in cols} | (
                {"value": pl.Series([], dtype=pl.Float64)} if field else {}))
        df = df.copy()
        for col in df.columns[:n]:
            df[col] = df[col].astype(str).str.lower()
        out = pl.from_pandas(df)
        cols = list(out.columns[:n])
        if dims:
            out = out.rename(dict(zip(cols, dims)))
            cols = list(dims)
        if field and field in out.columns:
            return out.select(cols + [pl.col(field).cast(pl.Float64).alias("value")])
        return out.select(cols)


def lower(df: pl.DataFrame, keys: list[str]) -> pl.DataFrame:
    return df.with_columns([pl.col(k).cast(pl.Utf8).str.to_lowercase() for k in keys])


def compare(name: str, mine: pl.DataFrame, ref: pl.DataFrame, tol: float = 0.0, show: int = 8) -> dict:
    keys = [c for c in ref.columns if c != "value"]
    is_par = "value" in ref.columns
    a = lower(mine, keys)
    b = lower(ref, keys)
    if is_par:
        a = a.filter(pl.col("value") != 0.0)
        b = b.filter(pl.col("value") != 0.0)
    a = a.unique(subset=keys)
    b = b.unique(subset=keys)
    only_a = a.join(b, on=keys, how="anti")
    only_b = b.join(a, on=keys, how="anti")
    result = {"name": name, "mine": a.height, "gams": b.height, "only_mine": only_a.height, "only_gams": only_b.height}
    if is_par:
        j = a.join(b.rename({"value": "gams"}), on=keys, how="inner")
        j = j.with_columns(((pl.col("value") - pl.col("gams")).abs()
                            / pl.max_horizontal(pl.lit(1.0), pl.col("gams").abs())).alias("rel"))
        bad = j.filter(pl.col("rel") > tol).sort("rel", descending=True)
        result["value_mismatches"] = bad.height
        result["max_rel_diff"] = float(j["rel"].max()) if j.height else 0.0
    else:
        bad = pl.DataFrame()
        result["value_mismatches"] = 0
    result["pass"] = result["only_mine"] == 0 and result["only_gams"] == 0 and result["value_mismatches"] == 0
    status = "PASS" if result["pass"] else "FAIL"
    print(f"{status} {name:28s} mine {result['mine']:7d} gams {result['gams']:7d} "
          f"only_mine {result['only_mine']:6d} only_gams {result['only_gams']:6d} "
          f"value_mismatches {result['value_mismatches']:6d}" + (f" max_rel {result['max_rel_diff']:.3g}" if is_par else ""))
    if not result["pass"] and show:
        if only_a.height:
            print("  only mine:", only_a.head(show).to_dicts())
        if only_b.height:
            print("  only gams:", only_b.head(show).to_dicts())
        if is_par and bad.height:
            print("  value diffs:", bad.head(show).to_dicts())
    return result
