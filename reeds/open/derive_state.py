from __future__ import annotations

import polars as pl

from .derive import Symbols, anti, semi
from .derive_capacity import yr

V4 = ["i", "v", "r", "t"]


def _years_int(df: pl.DataFrame, col: str) -> pl.DataFrame:
    return df.with_columns(pl.col(col).cast(pl.Int64).alias(f"_{col}"))


def adjust_costs_for_upgrades(S: Symbols, state_upgrades: pl.DataFrame) -> Symbols:
    if not int(S.sw["Sw_Upgrades"]) or state_upgrades.height == 0:
        return S
    length = float(S.sc["co2_capture_incentive_length"])
    valcap = S.valcap
    inc = S.co2_captured_incentive
    fom = S.cost_fom
    ups = _years_int(state_upgrades.filter(pl.col("value") != 0.0), "tt")
    for y in sorted(ups["_tt"].unique().to_list()):
        up_y = ups.filter(pl.col("_tt") == y).select(["i", "v", "r"]).unique()
        earlier = ups.filter(pl.col("_tt") < y).select(["i", "v", "r"]).unique()
        first_time = anti(up_y, earlier, ["i", "v", "r"])
        at_y = inc.filter(pl.col("t") == str(y)).select(["i", "v", "r", pl.col("value").alias("new")])
        extend_dom = (semi(valcap, first_time, ["i", "v", "r"]).filter((yr("t") >= y) & (yr("t") < y + length)).select(V4)
                      .join(at_y, on=["i", "v", "r"], how="inner"))
        inc = pl.concat([anti(inc, extend_dom, V4), extend_dom.select(V4 + [pl.col("new").alias("value")])]).filter(pl.col("value") != 0.0)
        zero_dom = semi(valcap, up_y, ["i", "v", "r"]).filter(yr("t") >= y + length).select(V4)
        inc = anti(inc, zero_dom, V4)
        from_rows = up_y.join(S.upgrade_from, on="i", how="inner").select([pl.col("ii").alias("i"), "v", "r"]).unique()
        dom = semi(valcap, from_rows, ["i", "v", "r"]).filter(yr("t") >= y).select(V4)
        up_fom = (dom.join(S.upgrade_from.rename({"i": "iu", "ii": "i"}), on="i", how="inner")
                  .join(fom.rename({"i": "iu", "value": "fu"}), on=["iu", "v", "r", "t"], how="inner")
                  .group_by(V4).agg(pl.col("fu").sum()))
        current = dom.join(fom, on=V4, how="left").with_columns(pl.col("value").fill_null(0.0))
        raised = (current.join(up_fom, on=V4, how="left").with_columns(pl.col("fu").fill_null(0.0))
                  .with_columns(pl.max_horizontal("value", "fu").alias("value")).select(V4 + ["value"]))
        fom = pl.concat([anti(fom, raised, V4), raised]).filter(pl.col("value") != 0.0)
    S["co2_captured_incentive"] = inc
    S["cost_fom"] = fom
    return S


def adjust_capacity_exog_for_upgrades(S: Symbols, state_upgrades: pl.DataFrame, years: list[int]) -> Symbols:
    if int(S.sw["Sw_Upgrades"]) != 1 or state_upgrades.height == 0:
        return S
    lifespan = float(S.sw["Sw_UpgradeLifespan"])
    ups = _years_int(state_upgrades.filter(pl.col("value") != 0.0), "tt")
    ups = semi(ups, S.valcap.rename({"t": "tt"}), ["i", "v", "r", "tt"])
    link = S.upgrade_from.rename({"i": "ii", "ii": "i"})
    mce = S.m_capacity_exog
    m0 = S.m_capacity_exog0.rename({"value": "m0"})
    for y in years:
        if y <= min(S.years):
            continue
        window = ups.filter((pl.col("_tt") < y) & ((y - pl.col("_tt")) <= lifespan)).rename({"i": "ii"})
        tot = (window.join(link, on="ii", how="inner").group_by(["i", "v", "r"]).agg(pl.col("value").sum().alias("up")))
        rows = (S.valcap.filter(pl.col("t") == str(y)).join(tot, on=["i", "v", "r"], how="inner").filter(pl.col("up") != 0.0)
                .join(m0, on=V4, how="left").with_columns(pl.col("m0").fill_null(0.0))
                .with_columns(pl.max_horizontal("m0", "up").alias("value")).select(V4 + ["value"]))
        mce = pl.concat([anti(mce, rows, V4), rows]).filter(pl.col("value") != 0.0)
    S["m_capacity_exog"] = mce
    return S
