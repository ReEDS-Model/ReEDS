from __future__ import annotations

import math

import pandas as pd
import polars as pl

from .derive import Symbols, anti, fsum_by, gams_round, isin, members, one_col, semi
from .derive_capacity import V4, yr

GEN_IDX = ["i", "v", "r", "h", "t"]
DUMP_VARIABLES = {
    "CAP": V4, "CAP_ENERGY": V4, "INV": V4, "INV_ENERGY": V4, "INV_REFURB": V4, "UPGRADES": V4,
    "GEN": GEN_IDX, "PRODUCE": ["p", "i", "v", "r", "h", "t"], "BIOUSED": ["bioclass", "r", "t"],
    "GASUSED": ["cendiv", "gb", "h", "t"], "CAPTRAN_ENERGY": ["r", "rr", "trtype", "t"], "CAPTRAN_PRM": ["r", "rr", "trtype", "t"],
    "CAP_CONVERTER": ["r", "t"], "FLEX": ["flex_type", "r", "h", "t"], "CAP_LOADSITE": ["r", "t"],
}
DUMP_EQUATIONS = {
    "eq_supply_demand_balance": ["r", "h", "t"], "eq_annual_cap": ["eall", "t"], "eq_RGGI_cap": ["t"], "eq_state_cap": ["st", "t"],
    "eq_h2_demand_regional": ["r", "h", "t"], "eq_h2_demand": ["p", "t"],
}


def _empty(cols: list[str], value_col: str = "level") -> pl.DataFrame:
    return pl.DataFrame({c: pl.Series([], dtype=pl.Utf8) for c in cols} | {value_col: pl.Series([], dtype=pl.Float64)})


def level(lv: dict[str, pl.DataFrame], name: str) -> pl.DataFrame:
    if name not in lv or lv[name].height == 0:
        return _empty(DUMP_VARIABLES[name])
    df = lv[name]
    if df["t"].dtype != pl.Utf8:
        df = df.with_columns(pl.col("t").cast(pl.Utf8))
    return df.select(DUMP_VARIABLES[name] + ["level"])


def marginal(eqm: dict[str, pl.DataFrame], name: str) -> pl.DataFrame:
    if name not in eqm or eqm[name].height == 0:
        return _empty(DUMP_EQUATIONS[name], "marginal")
    df = eqm[name]
    if df["t"].dtype != pl.Utf8:
        df = df.with_columns(pl.col("t").cast(pl.Utf8))
    return df.select(DUMP_EQUATIONS[name] + ["marginal"])


def _sum(df: pl.DataFrame, keys: list[str], col: str = "level") -> pl.DataFrame:
    return fsum_by(df.select(keys + [pl.col(col).alias("value")]), keys)


def emit_r_tc(S: Symbols, lv: dict[str, pl.DataFrame], years: list[int]) -> pl.DataFrame:
    hours_rep = semi(S.hours, S.h_rep, ["h"]).rename({"value": "hrs"})
    er = (S.emit_rate.filter((pl.col("etype") == "process") & (pl.col("e") == "co2")).select(V4 + [pl.col("value").alias("er")]))
    gen = (level(lv, "GEN").filter(isin("t", {str(y) for y in years}))
           .join(semi(S.valgen, S.valgen, V4), on=V4, how="semi")
           .join(hours_rep, on="h", how="inner").join(er, on=V4, how="inner")
           .with_columns((pl.col("hrs") * pl.col("er") * pl.col("level")).alias("value")).select(["r", "t", "value"]))
    per = S.prod_emit_rate.filter((pl.col("etype") == "process") & (pl.col("e") == "co2")).select(["i", "t", pl.col("value").alias("per")])
    prod = (level(lv, "PRODUCE").filter(isin("t", {str(y) for y in years}))
            .join(S.valcap, on=V4, how="semi").join(S.i_p, on=["i", "p"], how="semi")
            .join(hours_rep, on="h", how="inner").join(per, on=["i", "t"], how="inner")
            .with_columns((pl.col("hrs") * pl.col("per") * pl.col("level")).alias("value")).select(["r", "t", "value"]))
    both = pl.concat([gen, prod])
    if both.height == 0:
        return _empty(["r", "t"], "value")
    return fsum_by(both, ["r", "t"])


def co2_emit_rate_r(S: Symbols, lv: dict[str, pl.DataFrame], emit_r: pl.DataFrame, year: int) -> pl.DataFrame:
    y = str(year)
    hours = S.hours.rename({"value": "hrs"})
    gen = (level(lv, "GEN").filter(pl.col("t") == y).join(S.valgen, on=V4, how="semi")
           .join(hours, on="h", how="inner").with_columns((pl.col("hrs") * pl.col("level")).alias("value")).select(["r", "value"]))
    gen_r = fsum_by(gen, ["r"]) if gen.height else _empty(["r"], "value")
    emit_y = emit_r.filter(pl.col("t") == y).select(["r", "value"])
    lvl = str(S.csw["GSw_StateCO2ImportLevel"]).lower()
    if lvl == "r":
        rate = (gen_r.rename({"value": "den"}).join(emit_y.rename({"value": "num"}), on="r", how="left")
                .with_columns(pl.col("num").fill_null(0.0)).filter(pl.col("den") != 0.0)
                .with_columns((pl.col("num") / pl.col("den")).alias("value")).select(["r", "value"]))
    else:
        reg = S.hierarchy.select(["r", lvl]).unique()
        num = fsum_by(emit_y.join(reg, on="r", how="inner").select([lvl, "value"]), [lvl]).rename({"value": "num"})
        den = fsum_by(gen_r.join(reg, on="r", how="inner").select([lvl, "value"]), [lvl]).rename({"value": "den"})
        rr = (den.join(num, on=lvl, how="left").with_columns(pl.col("num").fill_null(0.0)).filter(pl.col("den") != 0.0)
              .with_columns((pl.col("num") / pl.col("den")).alias("value")).select([lvl, "value"]))
        rate = reg.join(rr, on=lvl, how="inner").select(["r", "value"])
    return rate.with_columns(pl.lit(y).alias("t")).select(["r", "t", "value"]).filter(pl.col("value") != 0.0)


def _last_valid(cap: pl.DataFrame, valcap: pl.DataFrame, keys: list[str], year: int) -> pl.DataFrame:
    solved = cap.select("t").unique().with_columns(pl.col("t").cast(pl.Int64).alias("_t")).filter(pl.col("_t") <= year)
    last = (valcap.select(keys + ["t"]).unique().join(solved, on="t", how="inner")
            .group_by(keys).agg(pl.col("_t").max().alias("_t")))
    tot = (semi(cap, valcap.select(["i", "v", "r"]).unique(), ["i", "v", "r"]).with_columns(pl.col("t").cast(pl.Int64).alias("_t"))
           .join(last, on=keys + ["_t"], how="inner").group_by(keys).agg(pl.col("level").sum().alias("value")))
    return tot.filter(pl.col("value") != 0.0)


def _slice_scalar(S: Symbols, name: str) -> float:
    rows = S.slice_scalars.filter(pl.col("name") == name)
    if rows.height != 1:
        raise KeyError(f"{name} is not a unique slice scalar ({rows.height} rows)")
    return float(rows["value"][0])


def _par(df: pl.DataFrame, cols: dict[str, str], value: str = "value") -> pd.DataFrame:
    out = df.select(list(cols) + [value]).rename(dict(cols) | {value: "Value"}).filter(pl.col("Value") != 0.0)
    pdf = out.to_pandas()
    for c in pdf.columns:
        if c != "Value":
            pdf[c] = pdf[c].astype(str)
    return pdf


def _set(df: pl.DataFrame, cols: dict[str, str]) -> pd.DataFrame:
    out = df.select(list(cols)).unique(maintain_order=True).rename(dict(cols)).to_pandas()
    for c in out.columns:
        out[c] = out[c].astype(str)
    out["Value"] = True
    return out


def _scalar(value: float) -> pd.DataFrame:
    return pd.DataFrame({"Value": [float(value)]})


def hydmin(S: Symbols) -> pl.DataFrame:
    hydmin_q = S._inputs.par("hydro_mingen", ["i", "r", "quarter"]).rename({"value": "hq"})
    out = (S.szn_quarter_weights.rename({"value": "w"}).join(hydmin_q, on="quarter", how="inner")
           .with_columns((pl.col("w") * pl.col("hq")).alias("value")))
    out = fsum_by(out.select(["i", "r", "szn", "value"]), ["i", "r", "szn"]).with_columns(gams_round(pl.col("value"), 3).alias("value"))
    return out.filter(pl.col("value") != 0.0)


def reeds_data(S: Symbols, lv: dict[str, pl.DataFrame], eqm: dict[str, pl.DataFrame], year: int, next_year: int) -> tuple[dict[str, pd.DataFrame], dict[str, pl.DataFrame]]:
    I = S._inputs
    sw, sc, csw = S.sw, S.sc, S.csw
    cur = str(year)
    nxt = str(next_year)
    start = int(S.years[0])
    trange = {str(y) for y in S.years if start < y <= year} | {cur}
    valcap, valgen = S.valcap, S.valgen
    valcap_cur = valcap.filter(pl.col("t") == cur)
    cap = level(lv, "CAP")
    cap_cur = cap.filter(pl.col("t") == cur)
    cap_exist = semi(cap_cur, S.valcap_ivr, ["i", "v", "r"]).select(["i", "v", "r", "level"]).filter(pl.col("level") != 0.0)
    cap_exist_ir = _last_valid(cap, valcap, ["i", "r"], year)
    cap_exist_iv = _last_valid(cap, valcap, ["i", "v"], year)
    cap_exist_i = _last_valid(cap, valcap, ["i"], year)
    out: dict[str, pd.DataFrame] = {}
    dom: dict[str, pl.DataFrame] = {}

    vre_like = members(S.upv) | members(S.wind) | members(S.distpv)
    cap_non = (cap.filter(isin("t", trange) & ~isin("i", vre_like)).join(valcap, on=V4, how="semi").select(V4 + ["level"]))
    inv = level(lv, "INV")
    refurb = level(lv, "INV_REFURB")
    inv_both = pl.concat([inv, refurb.filter(isin("i", members(S.refurbtech))) if int(sw["Sw_Refurb"]) else refurb.head(0)])
    inv_both = fsum_by(inv_both.select(V4 + [pl.col("level").alias("value")]), V4).rename({"t": "tt", "value": "inv"}).filter(isin("tt", trange))
    cap_vre_dom = valcap.filter(isin("i", vre_like)).select(V4)
    exog_part = cap_vre_dom.join(S.m_capacity_exog, on=V4, how="left").with_columns(
        pl.when(isin("t", trange)).then(pl.col("value").fill_null(0.0)).otherwise(0.0).alias("value"))
    inv_part = (S.inv_cond.join(cap_vre_dom, on=V4, how="semi").join(inv_both, on=["i", "v", "r", "tt"], how="inner")
                .group_by(V4).agg(pl.col("inv").sum().alias("value")))
    cap_vre = (exog_part.join(inv_part.rename({"value": "iv"}), on=V4, how="left")
               .with_columns((pl.col("value") + pl.col("iv").fill_null(0.0)).alias("level")).select(V4 + ["level"]))
    cap_ivrt = pl.concat([cap_non, cap_vre])
    out["cap_ivrt"] = _par(cap_ivrt, {"i": "i", "v": "v", "r": "r", "t": "t"}, "level")
    dom["cap_ivrt"] = pl.concat([valcap.filter(isin("t", trange) & ~isin("i", vre_like)).select(V4), cap_vre_dom])
    cap_energy = level(lv, "CAP_ENERGY").filter(isin("t", trange) & isin("i", members(S.battery))).join(valcap, on=V4, how="semi")
    out["cap_energy_ivrt"] = _par(cap_energy, {"i": "i", "v": "v", "r": "r", "t": "t"}, "level")
    dom["cap_energy_ivrt"] = valcap.filter(isin("t", trange) & isin("i", members(S.battery))).select(V4)

    cap_init = pl.concat([
        cap_ivrt.filter((pl.col("t") == cur) & ~isin("i", members(S.distpv)) & isin("v", members(S.initv))),
        cap_ivrt.filter((pl.col("t") == str(start)) & isin("i", members(S.distpv))),
    ]).join(S.valcap_ivr, on=["i", "v", "r"], how="semi")
    out["cap_init"] = _par(cap_init, {"i": "i", "v": "v", "r": "r"}, "level")
    dom["cap_init"] = S.valcap_ivr

    up = level(lv, "UPGRADES").filter(isin("i", members(S.upgrade))) if int(sw["Sw_Upgrades"]) else level(lv, "UPGRADES").head(0)
    inv_ivrt = pl.concat([
        semi(inv_both.rename({"tt": "t", "inv": "level"}), S.valinv, V4),
        up.join(valcap, on=V4, how="semi").select(V4 + ["level"]),
    ]).filter(isin("t", trange)).join(valcap, on=V4, how="semi")
    inv_ivrt = fsum_by(inv_ivrt.select(V4 + [pl.col("level").alias("value")]), V4).rename({"value": "level"})
    distpv_cap = cap_ivrt.filter(isin("i", members(S.distpv)))
    distpv_inv = (distpv_cap.join(S.tprev, on="t", how="inner")
                  .join(distpv_cap.rename({"t": "tt", "level": "prev"}), on=["i", "v", "r", "tt"], how="left")
                  .with_columns((pl.col("level") - pl.col("prev").fill_null(0.0)).alias("level"))
                  .filter(isin("t", trange) & (pl.col("t") != str(start))).select(V4 + ["level"]))
    inv_ivrt = pl.concat([anti(inv_ivrt, distpv_inv, V4), distpv_inv])
    mce_d = S.m_capacity_exog.filter(isin("i", members(S.distpv)))
    inv_distpv = (mce_d.join(S.tprev, on="t", how="left")
                  .join(mce_d.rename({"t": "tt", "value": "prev"}), on=["i", "v", "r", "tt"], how="left")
                  .with_columns((pl.col("value") - pl.col("prev").fill_null(0.0)).alias("value"))
                  .group_by(["r", "t"]).agg(pl.col("value").sum()))
    inv_distpv_next = (inv_distpv.filter(pl.col("t") == nxt).with_columns(pl.lit("distpv").alias("i"), pl.lit("init-1").alias("v"))
                       .select(V4 + [pl.col("value").alias("level")]))
    inv_ivrt = pl.concat([anti(inv_ivrt, inv_distpv_next, V4), inv_distpv_next])
    out["inv_ivrt"] = _par(inv_ivrt, {"i": "i", "v": "v", "r": "r", "t": "t"}, "level")
    dom["inv_ivrt"] = pl.concat([valcap.filter(isin("t", trange)).select(V4), inv_distpv_next.select(V4)])
    inv_energy = level(lv, "INV_ENERGY").filter(isin("t", trange) & isin("i", members(S.battery))).join(valcap, on=V4, how="semi")
    out["inv_energy_ivrt"] = _par(inv_energy, {"i": "i", "v": "v", "r": "r", "t": "t"}, "level")
    dom["inv_energy_ivrt"] = dom["cap_energy_ivrt"]

    ret_dom = valcap.filter(isin("t", trange) & (pl.col("t") != str(start)) & isin("v", members(S.newv))).select(V4)
    ret = (ret_dom.join(S.tprev, on="t", how="inner")
           .join(cap_ivrt.rename({"t": "tt", "level": "prev"}), on=["i", "v", "r", "tt"], how="left")
           .join(cap_ivrt.rename({"level": "now"}), on=V4, how="left")
           .join(inv_ivrt.rename({"level": "inv"}), on=V4, how="left")
           .with_columns((pl.col("prev").fill_null(0.0) - pl.col("now").fill_null(0.0) + pl.col("inv").fill_null(0.0)).alias("level"))
           .select(V4 + ["level"]))
    ret = ret.with_columns(pl.when(pl.col("level") < 1e-6).then(0.0).otherwise(pl.col("level")).alias("level"))
    out["ret_ivrt"] = _par(ret, {"i": "i", "v": "v", "r": "r", "t": "t"}, "level")
    dom["ret_ivrt"] = valcap.filter(isin("t", trange) & (pl.col("t") != str(start)) & isin("v", members(S.newv))).select(V4)
    ret_ivr = fsum_by(ret.select(["i", "v", "r", pl.col("level").alias("value")]), ["i", "v", "r"])
    out["ret"] = _par(semi(ret_ivr, S.valcap_ivr, ["i", "v", "r"]), {"i": "i", "v": "v", "r": "r"})
    dom["ret"] = S.valcap_ivr

    cap_exog = semi(S.m_capacity_exog.filter((pl.col("t") == nxt) & ~isin("i", members(S.canada))), S.valcap_ivr, ["i", "v", "r"])
    out["cap_exog_filt"] = _par(cap_exog, {"i": "i", "v": "v", "r": "r"})
    dom["cap_exog_filt"] = S.valcap_ivr.filter(~isin("i", members(S.canada)))

    gen = level(lv, "GEN")
    gen_cur = gen.filter(pl.col("t") == cur).join(valgen, on=V4, how="semi")
    gen_stress = fsum_by(gen_cur.filter(isin("h", members(S.h_stress))).select(["i", "r", "h", "t", pl.col("level").alias("value")]), ["i", "r", "h", "t"])
    out["gen_h_stress_filt"] = _par(gen_stress, {"i": "i", "r": "r", "h": "allh", "t": "t"})
    dom["gen_h_stress_filt"] = (S.valgen_irt.filter(pl.col("t") == cur).join(S.h_stress, how="cross").select(["i", "r", "h", "t"]))

    cs = _slice_scalar(S, "cost_scale")
    pvf_onm_cur = float(S.pvf_onm.filter(pl.col("t") == cur)["value"][0])
    fuel_price = semi(S.fuel_price.filter(pl.col("t") == cur).select(["i", "r", "value"]), cap_exist_ir, ["i", "r"])
    hours = S.hours.rename({"value": "hrs"})
    hci = _slice_scalar(S, "h2_combustion_intensity")
    if int(sw["Sw_H2"]) and year >= _slice_scalar(S, "h2_demand_start"):
        h2gen = (gen_cur.filter(isin("i", members(S.h2_gen))).join(S.heat_rate.filter(pl.col("t") == cur).rename({"value": "hr"}), on=V4, how="inner")
                 .with_columns((pl.col("level") * hci * pl.col("hr")).alias("value")).select(["r", "h", "value"]))
        exog = (S.h2_exogenous_demand_regional.filter((pl.col("t") == cur) & (pl.col("p") == "h2")).select(["r", "h", "value"]))
        usage = (fsum_by(pl.concat([h2gen, exog]), ["r", "h"]).join(hours, on="h", how="inner")
                 .with_columns((pl.col("hrs") * pl.col("value")).alias("usage")).select(["r", "h", "usage"]))
        if int(sw["Sw_H2"]) == 2:
            m = marginal(eqm, "eq_h2_demand_regional").filter(pl.col("t") == cur)
            w = (usage.join(m, on=["r", "h"], how="left").join(hours, on="h", how="inner")
                 .with_columns(((pl.col("marginal").fill_null(0.0) / pl.col("hrs")) * pl.col("usage")).alias("num")))
            agg = w.group_by("r").agg(pl.col("num").sum(), pl.col("usage").sum()).filter(pl.col("usage") != 0.0)
            price = agg.with_columns(((1.0 / cs) * (1.0 / pvf_onm_cur) * hci * (pl.col("num") / pl.col("usage"))).alias("value")).select(["r", "value"])
        else:
            m = marginal(eqm, "eq_h2_demand").filter((pl.col("t") == cur) & (pl.col("p") == "h2"))
            val = (1.0 / cs) * (1.0 / pvf_onm_cur) * hci * (float(m["marginal"][0]) if m.height else 0.0)
            price = S.r.with_columns(pl.lit(val).alias("value"))
        h2_rows = cap_exist_ir.filter(isin("i", members(S.h2_gen))).select(["i", "r"]).join(price, on="r", how="inner")
        fuel_price = pl.concat([anti(fuel_price, h2_rows, ["i", "r"]), h2_rows.select(["i", "r", "value"])])
    out["fuel_price_filt"] = _par(fuel_price, {"i": "i", "r": "r"})
    dom["fuel_price_filt"] = cap_exist_ir.select(["i", "r"])

    bio_transport = _slice_scalar(S, "bio_transport_cost")
    price_r = fsum_by(S.r_usda.join(S.biosupply_price, on="usda_region", how="inner").select(["r", "bioclass", "value"]), ["r", "bioclass"])
    bio_raw = I.par("bio_supplycurve", ["usda_region", "bioclass", "cat"])
    content = 13.0
    price_raw = bio_raw.filter(pl.col("cat") == "price").with_columns((pl.col("value") / content).alias("value")).select(["usda_region", "bioclass", "value"])
    cap_raw = (bio_raw.filter(pl.col("cat") == "cap").with_columns((pl.col("value") * 1e6 * content * float(sw["Sw_BioSupply"])).alias("value"))
               .select(["usda_region", "bioclass", "value"]))
    price_raw_r = fsum_by(S.r_usda.join(price_raw, on="usda_region", how="inner").select(["r", "bioclass", "value"]), ["r", "bioclass"])
    cap_r = fsum_by(S.r_usda.join(cap_raw, on="usda_region", how="inner").select(["r", "bioclass", "value"]), ["r", "bioclass"])
    unused = (price_raw_r.join(cap_r.filter(pl.col("value") != 0.0).select(["r", "bioclass"]), on=["r", "bioclass"], how="semi")
              .group_by("r").agg(pl.col("value").min()).with_columns((pl.col("value") + bio_transport).alias("value")))
    bioused = level(lv, "BIOUSED")
    used_cur = bioused.filter((pl.col("t") == cur) & (pl.col("level") != 0.0)).select(["bioclass", "r"])
    rep = (price_r.join(used_cur, on=["r", "bioclass"], how="semi").group_by("r").agg(pl.col("value").max())
           .with_columns((pl.col("value") + bio_transport).alias("value")))
    any_use = bioused.filter(pl.col("level") != 0.0).select("r").unique()
    rep = semi(rep, any_use, ["r"]).filter(pl.col("value") > 0.0)
    repbio = pl.concat([rep, anti(unused, rep, ["r"])])
    out["repbioprice_filt"] = _par(repbio, {"r": "r"})
    dom["repbioprice_filt"] = S.r

    dgv = S.derate_geo_vintage.rename({"value": "dgv"})
    avail_f = (semi(S.avail, S.valcap_ir if "valcap_ir" in S else valcap.select(["i", "r"]).unique(), ["i", "r"])
               .join(S.h_szn, on="h", how="inner")
               .join(cap_exist_iv.select(["i", "v"]), on="i", how="inner").filter(~isin("i", members(S.vre)))
               .join(dgv, on=["i", "v"], how="inner")
               .with_columns((pl.col("value") * pl.col("dgv")).alias("value"))
               .group_by(["i", "v", "r", "szn"]).agg(pl.col("value").max()))
    out["avail_filt"] = _par(avail_f, {"i": "i", "v": "v", "r": "r", "szn": "allszn"})
    dom["avail_filt"] = (cap_exist_iv.select(["i", "v"]).filter(~isin("i", members(S.vre))).join(S.r, how="cross").join(S.szn, how="cross").select(["i", "v", "r", "szn"]))
    out["can_exports_h_filt"] = _par(S.can_exports_h.filter(pl.col("t") == cur), {"r": "r", "h": "allh"})
    out["can_imports_cap"] = _par(S.m_capacity_exog.filter((pl.col("t") == cur) & isin("i", members(S.canada))), {"i": "i", "v": "v", "r": "r"})
    dom["can_imports_cap"] = S.canada.join(S.v, how="cross").join(S.r, how="cross").select(["i", "v", "r"])
    out["can_imports_szn_filt"] = _par(S.can_imports_szn.filter(pl.col("t") == cur), {"r": "r", "szn": "allszn"})
    chsa = semi(S.cap_hyd_szn_adj.filter(isin("i", members(S.hydro_d))), cap_exist_ir, ["i", "r"])
    out["cap_hyd_szn_adj_filt"] = _par(chsa, {"i": "i", "szn": "allszn", "r": "r"})
    dom["cap_hyd_szn_adj_filt"] = cap_exist_ir.filter(isin("i", members(S.hydro_d))).select(["i", "r"]).join(S.szn, how="cross").select(["i", "szn", "r"])
    out["cost_cap_filt"] = _par(S.cost_cap.filter((pl.col("t") == nxt) & isin("i", members(S.storage_standalone))), {"i": "i", "t": "t"})
    dom["cost_cap_filt"] = S.storage_standalone.join(S.t, how="cross").select(["i", "t"])
    out["cost_cap_fin_mult_filt"] = _par(S.cost_cap_fin_mult.filter((pl.col("t") == nxt) & isin("i", members(S.storage_standalone))), {"i": "i", "r": "r", "t": "t"})
    dom["cost_cap_fin_mult_filt"] = S.storage_standalone.join(S.r, how="cross").join(S.t, how="cross").select(["i", "r", "t"])
    out["cost_vom_filt"] = _par(semi(S.cost_vom.filter(pl.col("t") == cur), cap_exist, ["i", "v", "r"]), {"i": "i", "v": "v", "r": "r"})
    dom["cost_vom_filt"] = cap_exist.select(["i", "v", "r"])
    cfa = fsum_by(S.cf_adj_t.select(["i", "v", "t", "value"]), ["i", "v", "t"])
    cfa_tr = semi(cfa.filter(isin("t", trange)), cap_exist_iv, ["i", "v"])
    cfa_next = cfa.filter((pl.col("t") == nxt) & isin("i", members(S.vre) | members(S.pvb)))
    out["cf_adj_t_filt"] = _par(pl.concat([cfa_tr.filter(pl.col("t") != nxt), cfa_next]), {"i": "i", "v": "v", "t": "t"})
    dom["cf_adj_t_filt"] = pl.concat([cap_exist_iv.select(["i", "v"]).join(one_col(sorted(trange), "t"), how="cross"), S.i.join(S.v, how="cross").with_columns(pl.lit(nxt).alias("t"))]).select(["i", "v", "t"])
    out["ctt_i_ii_filt"] = pd.DataFrame({"i": pd.Series([], dtype=str), "ii": pd.Series([], dtype=str), "Value": pd.Series([], dtype=float)})
    out["ctt_i_ii_psh"] = out["ctt_i_ii_filt"].copy()
    er = fsum_by(S.emit_rate.filter((pl.col("t") == cur) & isin("e", members(S.e))).select(["e", "i", "v", "r", "value"]), ["e", "i", "v", "r"])
    out["emit_rate_filt"] = _par(semi(er, cap_exist, ["i", "v", "r"]), {"e": "e", "i": "i", "v": "v", "r": "r"})
    dom["emit_rate_filt"] = S.e.join(cap_exist.select(["i", "v", "r"]), how="cross").select(["e", "i", "v", "r"])
    out["heat_rate_filt"] = _par(semi(S.heat_rate.filter(pl.col("t") == cur), cap_exist, ["i", "v", "r"]), {"i": "i", "v": "v", "r": "r"})
    dom["heat_rate_filt"] = cap_exist.select(["i", "v", "r"])
    icf = (S.inv_cond.filter((pl.col("tt") == nxt) & isin("i", members(S.vre) | members(S.pvb)))
           .select(["i", "v"]).unique().with_columns(pl.lit(1.0).alias("value"), pl.lit(nxt).alias("t")))
    out["inv_cond_filt"] = _par(icf, {"i": "i", "v": "v", "t": "t"})
    dom["inv_cond_filt"] = one_col(sorted(members(S.vre) | members(S.pvb)), "i").join(S.v, how="cross").with_columns(pl.lit(nxt).alias("t")).select(["i", "v", "t"])
    mcf_next = fsum_by(S.m_cf_next.filter(pl.col("t") == nxt).select(["i", "v", "r", "h", "value"]), ["i", "v", "r", "h"])
    mcf_next = semi(mcf_next.filter(isin("i", members(S.vre) | members(S.pvb))), cap_exist, ["i", "v", "r"])
    out["m_cf_filt"] = _par(mcf_next, {"i": "i", "v": "v", "r": "r", "h": "allh"})
    dom["m_cf_filt"] = cap_exist.filter(isin("i", members(S.vre) | members(S.pvb))).select(["i", "v", "r"]).join(S.h, how="cross").select(["i", "v", "r", "h"])
    mcs = semi(S.m_cf_szn.filter((pl.col("t") == cur) & isin("i", members(S.hydro))), cap_exist, ["i", "v", "r"])
    out["m_cf_szn_filt"] = _par(mcs, {"i": "i", "v": "v", "r": "r", "szn": "allszn"})
    dom["m_cf_szn_filt"] = cap_exist.filter(isin("i", members(S.hydro))).select(["i", "v", "r"]).join(S.szn, how="cross").select(["i", "v", "r", "szn"])

    hydmin_szn = hydmin(S)
    out["hydmin"] = _par(hydmin_szn, {"i": "i", "r": "r", "szn": "allszn"})
    ml0 = I.par("minloadfrac0", ["i"]).rename({"value": "ml0"})
    hyd_ir = cap_exist_ir.filter(isin("i", members(S.hydro))).select(["i", "r"])
    base = (hyd_ir.join(S.h_szn.join(hours, on="h", how="inner"), how="cross")
            .join(ml0, on="i", how="left").with_columns(pl.col("ml0").fill_null(0.0)))
    hydmin_h = (S.h_szn.join(hydmin_szn, on="szn", how="inner").group_by(["i", "r", "h"]).agg(pl.col("value").sum().alias("hm")))
    mlf = (base.join(hydmin_h, on=["i", "r", "h"], how="left")
           .with_columns(pl.when(pl.col("hm").fill_null(0.0) != 0.0).then(pl.col("hm")).otherwise(pl.col("ml0")).alias("mlf"))
           .filter(isin("szn", members(S.szn_rep)))
           .group_by(["r", "i", "szn"]).agg((pl.col("mlf") * pl.col("hrs")).sum().alias("num"), pl.col("hrs").sum().alias("den"))
           .with_columns((pl.col("num") / pl.col("den")).alias("value")))
    out["minloadfrac_filt"] = _par(mlf, {"r": "r", "i": "i", "szn": "allszn"})
    dom["minloadfrac_filt"] = hyd_ir.join(S.szn_rep, how="cross").select(["r", "i", "szn"])
    rsc = S.rsc_dat.filter((pl.col("sc_cat") == "cost") & isin("i", members(S.storage_standalone)))
    out["rsc_dat_filt"] = _par(semi(rsc, cap_exist_ir, ["i", "r"]), {"i": "i", "r": "r", "sc_cat": "sc_cat", "rscbin": "rscbin"})
    dom["rsc_dat_filt"] = cap_exist_ir.filter(isin("i", members(S.storage_standalone))).select(["i", "r"]).with_columns(pl.lit("cost").alias("sc_cat")).join(S.rscbin, how="cross").select(["i", "r", "sc_cat", "rscbin"])
    out["storage_eff_filt"] = _par(S.storage_eff.filter((pl.col("t") == nxt) & isin("i", members(S.storage))), {"i": "i"})
    dom["storage_eff_filt"] = S.storage
    out["upgrade_to_filt"] = _par(semi(S.upgrade_to, cap_exist_i, ["i"]).with_columns(pl.lit(1.0).alias("value")), {"i": "i", "ii": "ii"})

    out["cap_trans_energy"] = _par(level(lv, "CAPTRAN_ENERGY").filter(pl.col("t") == cur), {"r": "r", "rr": "rr", "trtype": "trtype"}, "level")
    out["cap_trans_prm"] = _par(level(lv, "CAPTRAN_PRM").filter(pl.col("t") == cur), {"r": "r", "rr": "rr", "trtype": "trtype"}, "level")
    out["cap_converter_filt"] = _par(level(lv, "CAP_CONVERTER").filter(pl.col("t") == cur), {"r": "r"}, "level")
    out["routes_filt"] = _set(S.routes.filter(pl.col("t") == cur), {"r": "r", "rr": "rr", "trtype": "trtype"})
    flex = level(lv, "FLEX").filter(pl.col("t") == cur)
    out["flex_load"] = pd.DataFrame({"r": pd.Series([], dtype=str), "allh": pd.Series([], dtype=str), "Value": pd.Series([], dtype=float)})
    out["flex_load_opt"] = _par(fsum_by(flex.select(["r", "h", pl.col("level").alias("value")]), ["r", "h"]), {"r": "r", "h": "allh"})
    out["ra_cap_loadsite"] = _par(level(lv, "CAP_LOADSITE").filter(pl.col("t") == cur), {"r": "r", "t": "t"}, "level")
    dom["ra_cap_loadsite"] = level(lv, "CAP_LOADSITE").filter(pl.col("t") == cur).select(["r", "t"])
    pcr = S.prod_conversion_rate.filter(pl.col("t") == cur).rename({"value": "pcr"})
    prod = (level(lv, "PRODUCE").filter(pl.col("t") == cur).join(S.i_p, on=["i", "p"], how="semi").join(valcap_cur, on=V4, how="semi")
            .filter(isin("i", members(S.consume))).join(hours, on="h", how="inner").join(pcr, on=V4, how="inner")
            .with_columns((pl.col("level") / pl.col("pcr")).alias("value")))
    out["prod_filt"] = _par(fsum_by(prod.select(["i", "v", "r", "h", "value"]), ["i", "v", "r", "h"]), {"i": "i", "v": "v", "r": "r", "h": "allh"})
    dom["prod_filt"] = valcap_cur.filter(isin("i", members(S.consume))).select(["i", "v", "r"]).join(hours.filter(pl.col("hrs") != 0.0).select("h"), how="cross").select(["i", "v", "r", "h"])

    tax = S.emit_tax.filter(pl.col("t") == cur).select(["e", "r", "value"])
    cap_m = marginal(eqm, "eq_annual_cap").filter(pl.col("t") == cur).select([pl.col("eall").alias("e"), "marginal"])
    ep = (S.e.join(S.r, how="cross").join(cap_m, on="e", how="left").join(tax, on=["e", "r"], how="left")
          .with_columns(((1.0 / cs) * ((1.0 / pvf_onm_cur) * pl.col("marginal").fill_null(0.0) + pl.col("value").fill_null(0.0))).alias("value"))
          .select(["e", "r", "value"]))
    rggi_m = marginal(eqm, "eq_RGGI_cap").filter(pl.col("t") == cur)
    rggi_val = float(rggi_m["marginal"][0]) if rggi_m.height else 0.0
    st_m = marginal(eqm, "eq_state_cap").filter(pl.col("t") == cur).select(["st", "marginal"])
    co2_add = (S.r.join(S.r_st, on="r", how="left").join(st_m, on="st", how="left")
               .with_columns((pl.col("marginal").fill_null(0.0) + pl.when(isin("r", members(S.rggi_r))).then(rggi_val).otherwise(0.0)).alias("add"))
               .group_by("r").agg(pl.col("add").sum()).with_columns(pl.lit("co2").alias("e")))
    ep = (ep.join(co2_add, on=["e", "r"], how="left")
          .with_columns((pl.col("value") + (1.0 / cs) * (1.0 / pvf_onm_cur) * pl.col("add").fill_null(0.0)).alias("value")).select(["e", "r", "value"]))
    out["emissions_price"] = _par(ep, {"e": "e", "r": "r"})
    bal = marginal(eqm, "eq_supply_demand_balance").filter(pl.col("t") == cur)
    energy = (bal.join(hours, on="h", how="inner").filter(pl.col("hrs") != 0.0)
              .with_columns(((1.0 / cs) * (1.0 / pvf_onm_cur) * pl.col("marginal") / pl.col("hrs")).alias("value")).select(["r", "h", "value"]))
    out["energy_price"] = _par(energy, {"r": "r", "h": "allh"})

    out["bcr"] = _par(S.bcr, {"i": "i"})
    out["bir_pvb_config"] = _par(I.par("pvb_bir", ["pvb_config"]), {"pvb_config": "pvb_config"})
    out["ilr_pvb_config"] = _par(I.par("pvb_ilr", ["pvb_config"]), {"pvb_config": "pvb_config"})
    out["converter_efficiency_vsc"] = _scalar(sc["converter_efficiency_vsc"])
    out["csp_sm"] = _par(anti(S.csp_sm, S.ban, ["i"]), {"i": "i"})
    out["degrade_annual"] = _par(S.degrade_annual, {"i": "i"})
    out["fuel2tech"] = _set(S.fuel2tech, {"f": "f", "i": "i"})
    out["geo"] = _set(S.geo, {"i": "i"})
    out["h_szn"] = _set(S.h_szn, {"h": "allh", "szn": "allszn"})
    out["hierarchy"] = _set(S.hierarchy, {c: c for c in S.hierarchy.columns})
    out["hydro_d"] = _set(S.hydro_d, {"i": "i"})
    out["hydro_nd"] = _set(S.hydro_nd, {"i": "i"})
    out["hours"] = _par(S.hours, {"h": "allh"})
    out["i"] = _set(S.i, {"i": "*"})
    out["ilr"] = _par(S.ilr, {"i": "i"})
    out["i_subsets"] = _par(i_subsets(S), {"i": "i", "i_subtech": "i_subtech"})
    out["ivt_num"] = _par(S.ivt_num, {"i": "i", "allt": "allt"})
    out["maxage"] = _par(S.maxage, {"i": "i"})
    out["notvsc"] = _set(S.notvsc, {"trtype": "trtype"})
    out["nuclear"] = _set(S.nuclear, {"i": "i"})
    out["prm"] = _par(prm_all_years(S, lv), {"r": "r", "t": "t"})
    out["pvf_onm"] = _par(S.pvf_onm, {"t": "t"})
    out["r"] = _set(S.r, {"r": "*"})
    out["rfeas"] = _set(S.r, {"r": "r"})
    out["r_cendiv"] = _set(S.r_cendiv, {"r": "r", "cendiv": "cendiv"})
    out["sdbin"] = _set(I.set("sdbin", ["sdbin"]), {"sdbin": "*"})
    out["storage_duration"] = _par(S.storage_duration, {"i": "i"})
    out["storage_eff"] = _par(S.storage_eff, {"i": "i", "t": "t"})
    out["storage_standalone"] = _set(S.storage_standalone, {"i": "i"})
    out["Sw_VSC"] = _scalar(float(S.Sw_VSC))
    out["szn"] = _set(S.szn, {"szn": "allszn"})
    out["tfirst"] = _set(S.tfirst, {"t": "t"})
    out["tmodel_new"] = _set(S.tmodel_new, {"t": "allt"})
    out["tranloss"] = _par(S.tranloss, {"r": "r", "rr": "rr", "trtype": "trtype"})
    out["trtype"] = _set(S.trtype, {"trtype": "*"})
    out["v"] = _set(S.v, {"v": "*"})
    out["vom_hyd"] = _scalar(sc["vom_hyd"])
    return out, dom


def i_subsets(S: Symbols) -> pl.DataFrame:
    I = S._inputs
    raw = I.raw("tech-subset-table")
    cols = list(raw.columns)
    if "value" in [c.lower() for c in cols]:
        value_col = [c for c in cols if c.lower() == "value"][-1]
        df = raw.select([cols[0], cols[1], value_col]).rename({cols[0]: "i", cols[1]: "i_subtech", value_col: "value"})
    else:
        df = raw.unpivot(index=cols[0], variable_name="i_subtech", value_name="value").rename({cols[0]: "i"})
    df = df.with_columns(pl.col("i").cast(pl.Utf8).str.strip_chars().str.to_lowercase(), pl.col("i_subtech").cast(pl.Utf8).str.strip_chars(),
                         pl.col("value").cast(pl.Float64)).filter(pl.col("value") != 0.0)
    if int(S.sw["Sw_Upgrades"]):
        link = I.set("upgrade_link", ["i", "ii", "iii"])
        upgrade = set(link["i"].to_list())
        upgrade_to = link.select(["i", pl.col("iii").alias("ii")]).unique()
        expanded = (upgrade_to.join(df.rename({"i": "ii"}), on="ii", how="inner")
                    .group_by(["i", "i_subtech"]).agg(pl.col("value").sum()).filter(pl.col("value") != 0.0))
        df = pl.concat([df.filter(~isin("i", upgrade)), expanded.select(["i", "i_subtech", "value"])])
    return df


def prm_all_years(S: Symbols, lv: dict[str, pl.DataFrame]) -> pl.DataFrame:
    I = S._inputs
    prm = I.par("prm_initial", ["r", "t"])
    if "prm_solved" in lv and lv["prm_solved"].height:
        solved = lv["prm_solved"]
        if solved["t"].dtype != pl.Utf8:
            solved = solved.with_columns(pl.col("t").cast(pl.Utf8))
        solved = solved.select(["r", "t", "value"])
        prm = pl.concat([anti(prm, solved, ["r", "t"]), solved])
    return prm


def tc_phaseout_emissions(S: Symbols, lv: dict[str, pl.DataFrame], years: list[int]) -> dict[str, pd.DataFrame]:
    emit_r = emit_r_tc(S, lv, years)
    nat = fsum_by(emit_r.select(["t", "value"]), ["t"]) if emit_r.height else _empty(["t"], "value")
    return {"emit_r_tc": _par(emit_r, {"r": "r", "t": "t"}), "emit_nat_tc": _par(nat, {"t": "t"})}


def accumulate(previous: dict[str, pd.DataFrame] | None, current: dict[str, pd.DataFrame],
               domains: dict[str, pl.DataFrame]) -> dict[str, pd.DataFrame]:
    if previous is None:
        return current
    out = dict(current)
    for name, dom in domains.items():
        if name not in previous or len(previous[name]) == 0:
            continue
        prev = previous[name]
        new = current[name]
        if list(prev.columns) != list(new.columns):
            raise ValueError(f"{name}: previous dump columns {list(prev.columns)} differ from {list(new.columns)}")
        keys = [c for c in new.columns if c != "Value"]
        dom_pd = dom.to_pandas()
        dom_pd.columns = keys
        for c in keys:
            dom_pd[c] = dom_pd[c].astype(str).str.lower()
        prev = prev.copy()
        for c in keys:
            prev[c] = prev[c].astype(str).str.lower()
        stale = prev.merge(dom_pd.drop_duplicates(), on=keys, how="left", indicator=True)
        stale = stale.loc[stale["_merge"] == "left_only", prev.columns]
        out[name] = pd.concat([new, stale], ignore_index=True)
    return out
