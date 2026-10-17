from __future__ import annotations

import polars as pl

from .derive import anti, fsum_by, isin, members, semi
from .postsolve import _slice_scalar
from .report_ctx import Ctx, empty

V4 = ["i", "v", "r", "t"]
DERIVED_SWITCHES = {"Sw_Prod", "Sw_VSC"}
INLINE_CONSTANTS = {"bio_energy_content", "smr_methane_rate"}


# ----------------------------------------------------------------------------- algebra helpers
def val(df: pl.DataFrame, name: str) -> pl.DataFrame:
    return df.rename({"value": name})


def mul(a: pl.DataFrame, b: pl.DataFrame, on: list[str], how: str = "inner") -> pl.DataFrame:
    out = a.join(val(b, "_b"), on=on, how=how)
    if how == "left":
        out = out.with_columns(pl.col("_b").fill_null(0.0))
    return out.with_columns((pl.col("value") * pl.col("_b")).alias("value")).drop("_b")


def div(num: pl.DataFrame, den: pl.DataFrame, on: list[str]) -> pl.DataFrame:
    out = num.join(val(den, "_d"), on=on, how="inner").filter(pl.col("_d") != 0.0)
    return out.with_columns((pl.col("value") / pl.col("_d")).alias("value")).drop("_d")


def add(frames: list[pl.DataFrame], dims: list[str]) -> pl.DataFrame:
    parts = [f.select(dims + ["value"]) for f in frames if f.height]
    if not parts:
        return empty(dims)
    return pl.concat(parts).group_by(dims, maintain_order=True).agg(pl.col("value").sum())


def sub(a: pl.DataFrame, b: pl.DataFrame, dims: list[str]) -> pl.DataFrame:
    return add([a, b.with_columns(-pl.col("value"))], dims)


def total(df: pl.DataFrame, dims: list[str]) -> pl.DataFrame:
    if not df.height:
        return empty(dims)
    return df.group_by(dims, maintain_order=True).agg(pl.col("value").sum())


def scale(df: pl.DataFrame, factor: float) -> pl.DataFrame:
    return df.with_columns((pl.col("value") * factor).alias("value"))


def lit(df: pl.DataFrame, **cols: str) -> pl.DataFrame:
    return df.with_columns([pl.lit(v).alias(k) for k, v in cols.items()])


def nz(df: pl.DataFrame) -> pl.DataFrame:
    return df.filter(pl.col("value") != 0.0)


def ones(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns(pl.lit(1.0).alias("value"))


def smax(df: pl.DataFrame, dims: list[str]) -> pl.DataFrame:
    if not df.height:
        return empty(dims)
    return df.group_by(dims, maintain_order=True).agg(pl.col("value").max())


def cond_year(df: pl.DataFrame, years: list[str]) -> pl.DataFrame:
    return df.filter(isin("t", set(years)))


def gams_round(expr: pl.Expr, digits: int) -> pl.Expr:
    factor = 10.0 ** digits
    return (expr * factor + pl.when(expr >= 0).then(0.5).otherwise(-0.5)).cast(pl.Int64).cast(pl.Float64) / factor


class Helpers:
    def __init__(self, C: Ctx):
        S = C.S
        self.C, self.S = C, S
        self.sw, self.sc = S.sw, S.sc
        self.h_rep = members(S.h_rep)
        self.szn_rep = members(S.szn_rep)
        self.hours = val(S.hours.filter(isin("h", self.h_rep)), "hours")
        self.h_szn = S.h_szn.filter(isin("h", self.h_rep) & isin("szn", self.szn_rep))
        self.cost_scale = _slice_scalar(S, "cost_scale")
        self.pvf_onm = val(S.pvf_onm, "pvf_onm")
        self.inv_pvf = S.pvf_onm.with_columns((1.0 / self.cost_scale / pl.col("value")).alias("value"))
        self.years = [str(y) for y in C.years]
        self.valcap, self.valgen, self.valinv = S.valcap, S.valgen, S.valinv
        self.valcap_irt, self.valgen_irt, self.valinv_irt = S.valcap_irt, S.valgen_irt, S.valinv_irt
        self.newv, self.initv = members(S.newv), members(S.initv)

    def rep(self, df: pl.DataFrame) -> pl.DataFrame:
        return df.filter(isin("h", self.h_rep))

    def L(self, name: str, rep: bool = False) -> pl.DataFrame:
        df = self.C.L(name)
        return self.rep(df) if rep else df

    def M(self, name: str) -> pl.DataFrame:
        return self.C.M(name)

    def P(self, name: str) -> pl.DataFrame:
        return self.S[name]

    def set_members(self, name: str) -> set[str]:
        return members(self.S[name])

    def swf(self, name: str) -> float:
        if name in DERIVED_SWITCHES:
            return _slice_scalar(self.S, name)
        return float(self.sw[name])

    def swi(self, name: str) -> int:
        return int(self.swf(name))

    def scalar(self, name: str) -> float:
        if name in self.sc:
            return float(self.sc[name])
        if name in INLINE_CONSTANTS:
            return float(self.S[name])
        return _slice_scalar(self.S, name)

    def hours_sum(self, df: pl.DataFrame, dims: list[str]) -> pl.DataFrame:
        return total(mul(self.rep(df), self.hours.rename({"hours": "value"}), ["h"]), dims)

    def year_t(self, df: pl.DataFrame) -> pl.DataFrame:
        return df.with_columns(pl.col("t").cast(pl.Int64).alias("_yr"))


# ----------------------------------------------------------------------------- LCOE
def lcoe(H: Helpers, R: dict) -> None:
    S, C = H.S, H.C
    dgv = val(S.derate_geo_vintage, "dgv")
    avg_avail = (S.avail.filter(isin("h", H.h_rep)).join(H.hours, on="h", how="inner").join(dgv, on="i", how="inner")
                 .with_columns((pl.col("hours") * pl.col("value") * pl.col("dgv")).alias("value")))
    avg_avail = scale(total(avg_avail, ["i", "v", "r"]), 1.0 / 8760.0)
    R["avg_avail"] = nz(avg_avail)
    cap = H.L("CAP")
    gen = H.L("GEN", rep=True)
    rsc = H.set_members("rsc_i")
    gen_hours = H.hours_sum(gen, V4)
    seas = (H.h_szn.join(val(S.seas_cap_frac_delta, "d"), on="szn", how="inner")
            .group_by(["i", "v", "r", "h", "t"]).agg(pl.col("d").sum()))
    cap_h = (cap.filter(~isin("i", rsc)).join(S.h.filter(isin("h", H.h_rep)), how="cross")
             .join(seas, on=["i", "v", "r", "h", "t"], how="left").with_columns(pl.col("d").fill_null(0.0))
             .join(H.hours, on="h", how="inner")
             .with_columns((pl.col("value") * (1.0 + pl.col("d")) * pl.col("hours")).alias("value")))
    cap_h = total(cap_h, V4)
    R["avg_cf"] = nz(div(gen_hours.filter(~isin("i", rsc)), cap_h, V4))

    crf = val(S.crf, "crf")
    ccfm = val(S.cost_cap_fin_mult, "ccfm")
    ccfm_noitc = val(S.cost_cap_fin_mult_noITC, "ccfm")
    cost_cap = val(S.cost_cap, "cc")
    cost_fom = val(S.cost_fom, "fom")
    cost_vom = val(S.cost_vom, "vom")
    hr_fp = (S.heat_rate.join(val(S.fuel_price, "fp"), on=["i", "r", "t"], how="inner")
             .with_columns((pl.col("value") * pl.col("fp")).alias("value")).select(V4 + ["value"]))
    ivt = S.ivt
    base = semi(semi(S.valcap, ivt, ["i", "v", "t"]), C.tmodel_new, ["t"])

    def capital_annual(fin: pl.DataFrame, dom: pl.DataFrame) -> pl.DataFrame:
        part = (dom.join(crf, on="t", how="inner").join(fin, on=["i", "r", "t"], how="left").join(cost_cap, on=["i", "t"], how="left")
                .with_columns([pl.col("ccfm").fill_null(0.0), pl.col("cc").fill_null(0.0)])
                .with_columns(pl.when(isin("v", H.newv)).then(pl.col("crf") * pl.col("ccfm") * pl.col("cc")).otherwise(0.0).alias("value")))
        return part.select(V4 + ["value"])

    def nonrsc(denom: pl.DataFrame, fin: pl.DataFrame) -> pl.DataFrame:
        dom = base.filter(~isin("i", rsc))
        num = add([capital_annual(fin, dom), semi(S.cost_fom, dom, V4)], V4)
        num = dom.join(num, on=V4, how="left").with_columns(pl.col("value").fill_null(0.0))
        out = div(num, denom, V4 if "v" in denom.columns else ["i", "r"])
        out = add([out, semi(S.cost_vom, out, V4), semi(hr_fp, out, V4)], V4)
        return lit(out, rscbin="bin1")

    avail_den = scale(avg_avail, 8760.0)
    avail_den = avail_den.join(C.tmodel_new, how="cross")
    lcoe_non = nonrsc(avail_den, ccfm)

    gen_rsc = (base.filter(isin("i", rsc)).join(S.i_c, on="i", how="inner")
               .join(S.m_cf.filter(isin("h", H.h_rep)), on=["i", "c", "v", "r", "t"], how="inner")
               .join(H.hours, on="h", how="inner").with_columns((pl.col("value") * pl.col("hours")).alias("value")))
    gen_rsc = total(gen_rsc, V4)
    R["gen_rsc"] = nz(gen_rsc)
    rsc_cost = val(S.m_rsc_dat.filter(pl.col("sc_cat") == "cost").select(["r", "i", "rscbin", "value"]), "rc")
    spur = H.set_members("spur_techs")

    def rsc_lcoe(fin: pl.DataFrame) -> pl.DataFrame:
        dom = (base.filter(isin("i", rsc)).join(S.m_rscfeas, on=["r", "i"], how="inner")
               .join(gen_rsc.filter(pl.col("value") != 0.0).select(V4), on=V4, how="semi"))
        part = (dom.join(crf, on="t", how="inner").join(fin, on=["i", "r", "t"], how="left").join(cost_cap, on=["i", "t"], how="left")
                .join(rsc_cost, on=["r", "i", "rscbin"], how="left").join(cost_fom, on=V4, how="left")
                .with_columns([pl.col(c).fill_null(0.0) for c in ["ccfm", "cc", "rc", "fom"]])
                .with_columns(pl.when(isin("v", H.newv) & ~isin("i", spur)).then(pl.col("rc")).otherwise(0.0).alias("rc"))
                .with_columns((pl.col("crf") * (pl.col("ccfm") * pl.col("cc") + pl.col("rc")) + pl.col("fom")).alias("value")))
        out = div(part.select(V4 + ["rscbin", "value"]), gen_rsc, V4)
        out = out.join(cost_vom, on=V4, how="left").with_columns((pl.col("value") + pl.col("vom").fill_null(0.0)).alias("value")).drop("vom")
        return out.select(V4 + ["rscbin", "value"])

    lcoe_rsc = rsc_lcoe(ccfm)
    R["lcoe"] = nz(pl.concat([lcoe_non.select(V4 + ["rscbin", "value"]), lcoe_rsc]))
    cf_den = scale(R["avg_cf"], 8760.0)
    R["lcoe_cf_act"] = nz(pl.concat([nonrsc(cf_den, ccfm).select(V4 + ["rscbin", "value"]), lcoe_rsc]))
    R["lcoe_nopol"] = nz(pl.concat([lcoe_non.select(V4 + ["rscbin", "value"]), rsc_lcoe(ccfm_noitc)]))
    R["lcoe_fullpol"] = R["lcoe"]

    inv = H.L("INV")
    up = H.L("UPGRADES") if H.swi("Sw_Upgrades") else empty(V4)
    inv_energy = H.L("INV_ENERGY")
    inv_rsc = H.L("INV_RSC")
    battery = H.set_members("battery")
    upgrade = H.set_members("upgrade")
    inv_v = semi(inv, S.valinv, V4)
    up_v = semi(up.filter(isin("i", upgrade)), S.valcap, V4)
    gen_inv = semi(gen, inv_v.filter(pl.col("value") != 0.0).select(V4), V4)
    gen_up = semi(gen, up_v.filter(pl.col("value") != 0.0).select(V4), V4)
    gen_built = add([H.hours_sum(gen_inv, ["i", "r", "t"]), H.hours_sum(gen_up, ["i", "r", "t"])], ["i", "r", "t"])
    capcost = add([mul(mul(inv_v, S.cost_cap_fin_mult, ["i", "r", "t"]), S.cost_cap, ["i", "t"]),
                   mul(mul(semi(inv_energy, S.valinv, V4).filter(isin("i", battery)), S.cost_cap_fin_mult, ["i", "r", "t"]), S.cost_cap_energy, ["i", "t"])],
                  ["i", "r", "t"])
    upgradecost = add([mul(mul(up_v, S.cost_upgrade, V4), S.cost_cap_fin_mult, ["i", "r", "t"])], ["i", "r", "t"])
    inv_cap_up = H.L("INV_CAP_UP")
    inv_ener_up = H.L("INV_ENER_UP")
    if S.allow_cap_up.height:
        upgradecost = add([upgradecost, mul(mul(semi(inv_cap_up, S.allow_cap_up, V4 + ["rscbin"]), S.cost_cap_fin_mult, ["i", "r", "t"]),
                                            S.cap_cap_up, V4 + ["rscbin"])], ["i", "r", "t"])
    if S.allow_ener_up.height:
        upgradecost = add([upgradecost, mul(mul(semi(inv_ener_up, S.allow_ener_up, V4 + ["rscbin"]), S.cost_cap_fin_mult, ["i", "r", "t"]),
                                            S.cap_ener_up, V4 + ["rscbin"])], ["i", "r", "t"])
    rsc_inv = (semi(inv_rsc, S.valinv, V4).filter(isin("i", rsc)).join(S.m_rscfeas, on=["r", "i", "rscbin"], how="semi"))
    rsccost = total(mul(mul(rsc_inv, rsc_cost.rename({"rc": "value"}), ["r", "i", "rscbin"]), S.rsc_fin_mult, ["i", "r", "t"]), ["i", "r", "t"])
    fomcost = add([mul(inv_v, S.cost_fom, V4), mul(semi(inv_energy, S.valinv, V4).filter(isin("i", battery)), S.cost_fom_energy, V4),
                   mul(up_v, S.cost_fom, V4)], ["i", "r", "t"])
    vom_fp = add([S.cost_vom, hr_fp], V4)
    vomcost = add([H.hours_sum(mul(gen_inv, vom_fp, V4), ["i", "r", "t"]), H.hours_sum(mul(gen_up, vom_fp, V4), ["i", "r", "t"])], ["i", "r", "t"])
    built_num = add([mul(add([capcost, mul(up_v, mul(S.cost_upgrade, S.cost_cap_fin_mult, ["i", "r", "t"]), V4), rsccost], ["i", "r", "t"])
                         .join(crf, on="t", how="inner").with_columns((pl.col("value") * pl.col("crf")).alias("value")).drop("crf"),
                         ones(gen_built.select(["i", "r", "t"])), ["i", "r", "t"], how="inner"),
                     semi(fomcost, gen_built, ["i", "r", "t"]), semi(vomcost, gen_built, ["i", "r", "t"])], ["i", "r", "t"])
    R["lcoe_built"] = nz(div(built_num, gen_built, ["i", "r", "t"]))
    inv_sum = total(inv_v, ["i", "r", "t"])
    R["lcoe_built_nat"] = nz(div(total(mul(R["lcoe_built"], inv_sum, ["i", "r", "t"]), ["i", "t"]), total(inv_sum, ["i", "t"]), ["i", "t"]))
    pieces = {"capcost": capcost, "upgradecost": upgradecost, "rsccost": rsccost, "fomcost": fomcost, "vomcost": vomcost, "gen": gen_built}
    R["lcoe_pieces"] = nz(pl.concat([lit(df, lcoe_cat=k).select(["lcoe_cat", "i", "r", "t", "value"]) for k, df in pieces.items()]))
    R["lcoe_pieces_nat"] = nz(total(R["lcoe_pieces"], ["lcoe_cat", "i", "t"]))


# ----------------------------------------------------------------------------- requirement prices and quantities
def requirements(H: Helpers, R: dict) -> None:
    S, C = H.S, H.C
    R["objfn_raw"] = C.objfn_raw
    load = H.L("LOAD")
    load_rep = H.rep(load)
    load_hours = mul(load_rep, H.hours.rename({"hours": "value"}), ["h"])
    load_rt_sum = total(load_hours, ["r", "t"])
    R["load_frac_rt"] = nz(div(load_rt_sum, total(load_hours, ["t"]), ["t"]))
    inv_pvf = val(H.inv_pvf, "f")
    price: list[pl.DataFrame] = []
    quant: list[pl.DataFrame] = []
    cols = ["cat", "sub", "r", "slot", "t", "value"]

    def pq(df: pl.DataFrame, cat: str, sub_col: str | None, slot_col: str | None, sub: str = "na", slot: str = "ann") -> pl.DataFrame:
        out = df
        out = out.with_columns(pl.col(sub_col).alias("sub")) if sub_col else out.with_columns(pl.lit(sub).alias("sub"))
        out = out.with_columns(pl.col(slot_col).alias("slot")) if slot_col else out.with_columns(pl.lit(slot).alias("slot"))
        return out.with_columns(pl.lit(cat).alias("cat")).select(cols)

    m_bal = H.M("eq_supply_demand_balance")
    p_load = (H.rep(m_bal).join(inv_pvf, on="t", how="inner").join(H.hours, on="h", how="inner")
              .with_columns((pl.col("f") * pl.col("value") / pl.col("hours")).alias("value")).select(["r", "h", "t", "value"]))
    price.append(pq(p_load, "load", None, "h"))
    m_or = H.M("eq_OpRes_requirement")
    p_or = (H.rep(m_or).join(inv_pvf, on="t", how="inner").join(H.hours, on="h", how="inner")
            .with_columns((pl.col("f") * pl.col("value") / pl.col("hours")).alias("value")).select(["ortype", "r", "h", "t", "value"]))
    price.append(pq(p_or, "oper_res", "ortype", "h"))
    m_rec = H.M("eq_REC_Requirement")
    p_rps = total(S.r_st.join(m_rec, on="st", how="inner").join(inv_pvf, on="t", how="inner")
                  .with_columns((pl.col("f") * pl.col("value")).alias("value")), ["rpscat", "r", "t"])
    price.append(pq(p_rps, "state_rps", "rpscat", None))
    m_nat = H.M("eq_national_gen")
    p_nat = (S.r.join(m_nat, how="cross").join(inv_pvf, on="t", how="inner").with_columns((pl.col("f") * pl.col("value")).alias("value")))
    price.append(pq(p_nat.select(["r", "t", "value"]), "nat_gen", None, None))
    m_cap = H.M("eq_annual_cap")
    e_col = "eall" if "eall" in m_cap.columns else "e"
    p_cap = (S.r.join(m_cap.filter(isin(e_col, members(S.e))), how="cross").join(inv_pvf, on="t", how="inner")
             .with_columns((pl.col("f") * pl.col("value")).alias("value")).rename({e_col: "e"}))
    price.append(pq(p_cap.select(["e", "r", "t", "value"]), "annual_cap", "e", None))
    capcredit = H.swi("Sw_PRM_CapCredit")
    if capcredit:
        m_rm = H.M("eq_reserve_margin")
        p_rm = m_rm.join(inv_pvf, on="t", how="inner").with_columns((pl.col("f") * pl.col("value")).alias("value")).select(["r", "ccseason", "t", "value"])
        price.append(pq(p_rm, "res_marg", None, "ccseason"))
    else:
        p_rm = (semi(m_bal, C.h_stress_t, ["h", "t"]).join(inv_pvf, on="t", how="inner")
                .with_columns((pl.col("f") * pl.col("value")).alias("value")).select(["r", "h", "t", "value"]))
        price.append(pq(p_rm, "res_marg", None, "h"))
    p_rm_ann = total(p_rm, ["r", "t"])
    price.append(pq(p_rm_ann, "res_marg_ann", None, None))
    m_lc = H.M("eq_loadcon")
    p_lc = (semi(m_lc, C.h_t, ["h", "t"]).join(inv_pvf, on="t", how="inner").with_columns((pl.col("f") * pl.col("value")).alias("value"))
            .select(["r", "h", "t", "value"]))
    price.append(pq(p_lc, "eq_loadcon", None, "h"))

    produce = H.L("PRODUCE", rep=True)
    consume = H.set_members("consume")
    prod_load_h = empty(["i", "r", "h", "t"])
    if H.swi("Sw_Prod"):
        prod_load_h = (produce.filter(isin("i", consume)).join(S.valcap, on=V4, how="semi").join(S.i_p, on=["i", "p"], how="semi")
                       .join(val(S.prod_conversion_rate, "pcr"), on=V4, how="inner")
                       .with_columns((pl.col("value") / pl.col("pcr")).alias("value")))
        prod_load_h = total(prod_load_h, ["i", "r", "h", "t"])
    R["_prod_load_h"] = prod_load_h
    q_load = mul(sub(load_rep, prod_load_h, ["r", "h", "t"]), H.hours.rename({"hours": "value"}), ["h"])
    quant.append(pq(q_load, "load", None, "h"))
    if capcredit:
        raise NotImplementedError("reqt_quant res_marg for Sw_PRM_CapCredit=1 is not ported")
    q_rm = semi(load, C.h_stress_t, ["h", "t"]).select(["r", "h", "t", "value"])
    quant.append(pq(q_rm, "res_marg", None, "h"))
    q_rm_ann = smax(q_rm, ["r", "t"])
    quant.append(pq(q_rm_ann, "res_marg_ann", None, None))
    gen = H.L("GEN", rep=True)
    cap = H.L("CAP")
    orperc = S.orperc
    wind = H.set_members("wind")
    pv = H.set_members("pv")
    dayhours = members(S.dayhours)
    gen_wind = total(semi(gen.filter(isin("i", wind)), S.valgen, V4), ["r", "h", "t"])
    cap_pv = total(semi(cap.filter(isin("i", pv)), S.valcap, V4), ["r", "t"]).join(S.h.filter(isin("h", H.h_rep & dayhours)), how="cross")
    q_or_parts = []
    for ortype in S.ortype["ortype"].to_list():
        perc = {row["orcat"]: row["value"] for row in orperc.filter(pl.col("ortype") == ortype).iter_rows(named=True)}
        parts = [scale(load_rep, perc["or_load"]) if "or_load" in perc else empty(["r", "h", "t"]),
                 scale(gen_wind, perc["or_wind"]) if "or_wind" in perc else empty(["r", "h", "t"]),
                 scale(cap_pv.select(["r", "h", "t", "value"]), perc["or_pv"]) if "or_pv" in perc else empty(["r", "h", "t"])]
        q = mul(add(parts, ["r", "h", "t"]), H.hours.rename({"hours": "value"}), ["h"])
        q_or_parts.append(lit(q, ortype=ortype))
    q_or = pl.concat(q_or_parts) if q_or_parts else empty(["ortype", "r", "h", "t"])
    quant.append(pq(q_or, "oper_res", "ortype", "h"))
    distloss = H.scalar("distloss")
    canada = H.swi("Sw_Canada") == 1
    can_exp = semi(H.rep(S.can_exports_h), H.C.tmodel_new, ["t"]) if canada else empty(["r", "h", "t"])
    distpv_gen = total(semi(gen.filter(pl.col("i") == "distpv"), S.valgen, V4), ["r", "h", "t"])
    style0 = scale(sub(sub(load_rep, can_exp, ["r", "h", "t"]), distpv_gen, ["r", "h", "t"]), 1.0 - distloss)
    style1 = sub(sub(load_rep, can_exp, ["r", "h", "t"]), distpv_gen, ["r", "h", "t"])
    stor_sa = H.set_members("storage_standalone")
    stor_hyb = H.set_members("storage_hybrid") - H.set_members("csp")
    gen_all = semi(gen.filter(~isin("i", stor_sa)), S.valgen, V4)
    gen_all = gen_all.with_columns(pl.when(pl.col("i") == "distpv").then(pl.col("value") * (1.0 - distloss)).otherwise(pl.col("value")).alias("value"))
    style2_base = total(gen_all, ["r", "h", "t"])
    if "storage_eff_pvb_g" in S and S.storage_eff_pvb_g.height:
        raise NotImplementedError("RecStyle=2 with hybrid storage grid charging is not ported")
    recstyle = S.recstyle
    rows = []
    for rpscat in S.rpscat["rpscat"].to_list():
        rs = recstyle.filter(pl.col("rpscat") == rpscat)
        for st in S.r_st_rps["st"].unique().to_list():
            style = rs.filter(pl.col("st") == st)
            style = int(style["value"][0]) if style.height else 0
            rr = S.r_st_rps.filter(pl.col("st") == st).select("r")
            if style == 0:
                base = style0
            elif style == 1:
                base = style1
            else:
                base = sub(style2_base, can_exp if rpscat == "ces" else empty(["r", "h", "t"]), ["r", "h", "t"])
            perc = S.recperc.filter((pl.col("rpscat") == rpscat) & (pl.col("st") == st)).select(["t", "value"])
            q = mul(mul(semi(base, rr, ["r"]), perc, ["t"]), H.hours.rename({"hours": "value"}), ["h"])
            rows.append(lit(total(q, ["r", "t"]), rpscat=rpscat))
    q_rps = pl.concat(rows) if rows else empty(["r", "t", "rpscat"])
    q_rps = total(q_rps, ["rpscat", "r", "t"])
    quant.append(pq(q_rps, "state_rps", "rpscat", None))
    mandate = H.swi("Sw_GenMandate")
    ngf = S._inputs.par("national_gen_frac", ["t"]).with_columns(pl.col("t").cast(pl.Utf8)) if mandate else empty(["t"])
    if mandate == 1:
        flow = H.L("FLOW", rep=True)
        loss_in = total(mul(mul(semi(flow, S.routes, ["r", "rr", "trtype", "t"]), S.tranloss, ["r", "rr", "trtype"]), H.hours.rename({"hours": "value"}), ["h"]),
                        ["rr", "t"]).rename({"rr": "r"})
        q_nat = mul(add([load_rt_sum, loss_in], ["r", "t"]), ngf, ["t"])
    elif mandate == 2:
        q_nat = mul(total(mul(sub(scale(sub(load_rep, can_exp, ["r", "h", "t"]), 1.0 - distloss), distpv_gen, ["r", "h", "t"]),
                              H.hours.rename({"hours": "value"}), ["h"]), ["r", "t"]), ngf, ["t"])
    else:
        q_nat = empty(["r", "t"])
    quant.append(pq(q_nat, "nat_gen", None, None))
    q_cap = (S.emit_cap.filter(isin("eall", members(S.e))).rename({"eall": "e"}).join(val(R["load_frac_rt"], "lf"), on="t", how="inner")
             .with_columns((pl.col("value") * pl.col("lf")).alias("value")).select(["e", "r", "t", "value"]))
    quant.append(pq(q_cap, "annual_cap", "e", None))
    q_lc = semi(load, C.h_t, ["h", "t"]).select(["r", "h", "t", "value"])
    quant.append(pq(q_lc, "eq_loadcon", None, "h"))

    reqt_price = nz(pl.concat(price))
    reqt_quant = nz(pl.concat(quant))
    R["reqt_price"] = reqt_price
    R["reqt_quant"] = reqt_quant
    sys_cats = ["load", "oper_res", "state_rps", "nat_gen", "annual_cap", "res_marg", "res_marg_ann"]
    q_sys = total(reqt_quant.filter(isin("cat", set(sys_cats))), ["cat", "sub", "slot", "t"])
    R["reqt_quant_sys"] = nz(q_sys)
    pq_prod = (reqt_price.join(val(reqt_quant, "q"), on=["cat", "sub", "r", "slot", "t"], how="inner")
               .with_columns((pl.col("value") * pl.col("q")).alias("value")))
    p_sys = div(total(pq_prod.filter(isin("cat", set(sys_cats))), ["cat", "sub", "slot", "t"]), q_sys, ["cat", "sub", "slot", "t"])
    R["reqt_price_sys"] = nz(p_sys)

    R["load_rt"] = nz(total(mul(H.rep(S.load_exog), H.hours.rename({"hours": "value"}), ["h"]), ["r", "t"]))
    R["load_stress"] = nz(semi(load, C.h_stress_t, ["h", "t"]).select(["r", "h", "t", "value"]))
    R["co2_price"] = nz(m_cap.filter(pl.col(e_col) == "co2").join(inv_pvf, on="t", how="inner")
                        .with_columns((pl.col("f") * pl.col("value")).alias("value")).select(["t", "value"]))
    R["rggi_price"] = nz(H.M("eq_RGGI_cap").join(inv_pvf, on="t", how="inner").with_columns((pl.col("f") * pl.col("value")).alias("value")).select(["t", "value"]))
    R["rggi_quant"] = nz(semi(S.rggi_cap, C.tmodel_new, ["t"]))
    R["state_cap_and_trade_price"] = nz(H.M("eq_state_cap").join(inv_pvf, on="t", how="inner")
                                        .with_columns((pl.col("f") * pl.col("value")).alias("value")).select(["st", "t", "value"]))
    R["state_cap_and_trade_quant"] = nz(semi(S.state_cap, C.tmodel_new, ["t"]))
    flow = H.L("FLOW", rep=True)
    hurdle = (semi(flow, S.routes, ["r", "rr", "trtype", "t"]).join(val(S.cost_hurdle, "ch"), on=["r", "rr", "t"], how="inner")
              .join(H.hours, on="h", how="inner").with_columns((pl.col("hours") * pl.col("ch") * pl.col("value")).alias("value")))
    R["tran_hurdle_cost_ann"] = nz(total(hurdle, ["r", "rr", "trtype", "t"]))


# ----------------------------------------------------------------------------- RPS, CES, tax credits, fuel
def policy_and_fuel(H: Helpers, R: dict) -> None:
    S, C = H.S, H.C
    recs = H.L("RECS")
    stfeas = members(S.stfeas)
    R["rec_outputs"] = nz(recs.filter(isin("st", stfeas) & (isin("ast", stfeas) | (pl.col("ast") == "voluntary"))).select(["rpscat", "i", "st", "ast", "t", "value"]))
    R["acp_purchases_out"] = nz(H.L("ACP_PURCHASES").select(["rpscat", "st", "t", "value"]))
    R["ptc_out"] = nz(mul(semi(S.ptc_value_scaled, C.tmodel_new, ["t"]), S.tc_phaseout_mult, ["i", "v", "t"]))

    bioused = H.L("BIOUSED")
    m_bio = H.M("eq_bioused")
    m_lim = H.M("eq_biousedlimit")
    lim_r = total(S.r_usda.join(m_lim, on="usda_region", how="inner"), ["bioclass", "r", "t"])
    cand = (bioused.select(["bioclass", "r", "t"]).join(val(m_bio, "mb"), on=["r", "t"], how="left")
            .join(val(lim_r, "ml"), on=["bioclass", "r", "t"], how="left")
            .with_columns((pl.col("mb").fill_null(0.0) - pl.col("ml").fill_null(0.0)).alias("value")))
    best = smax(cand, ["r", "t"]).with_columns(pl.max_horizontal(pl.lit(0.0), pl.col("value")).alias("value"))
    best = S.r.join(C.tmodel_new, how="cross").join(best, on=["r", "t"], how="left").with_columns(pl.col("value").fill_null(0.0))
    R["repbioprice"] = nz(div(best, S.pvf_onm, ["t"]))
    bec = H.scalar("bio_energy_content")
    R["bioused_out"] = nz(scale(bioused, 1.0 / bec).select(["bioclass", "r", "t", "value"]))
    R["bioused_usda"] = nz(total(S.r_usda.join(R["bioused_out"], on="r", how="inner"), ["bioclass", "usda_region", "t"]))

    gascurve = H.swi("Sw_GasCurve")
    if gascurve not in (1, 2):
        raise NotImplementedError(f"Sw_GasCurve={gascurve} gas reporting is not ported")
    gen = H.L("GEN", rep=True)
    gas = H.set_members("gas")
    hr = val(S.heat_rate, "hr")
    r_cendiv = S.hierarchy.select(["r", "cendiv"]).unique()
    gas_gen = (semi(gen.filter(isin("i", gas)), S.valgen, V4).join(hr, on=V4, how="inner").join(H.hours, on="h", how="inner")
               .with_columns((pl.col("hours") * pl.col("hr") * pl.col("value")).alias("value")))
    produce = H.L("PRODUCE", rep=True)
    smr = H.set_members("smr")
    dac_term = empty(["i", "r", "t"])
    if H.swi("Sw_DAC_Gas"):
        raise NotImplementedError("Sw_DAC_Gas gas accounting is not ported")
    smr_term = empty(["i", "r", "t"])
    if H.swi("Sw_H2") and smr:
        smr_term = scale(total(semi(produce.filter(isin("i", smr)), S.valcap, V4).join(H.hours, on="h", how="inner")
                               .with_columns((pl.col("hours") * pl.col("value")).alias("value")), ["i", "r", "t"]), H.scalar("smr_methane_rate"))
    rq_irt = scale(add([total(gas_gen, ["i", "r", "t"]), dac_term, smr_term], ["i", "r", "t"]), 1e-9)
    R["repgasquant_irt"] = nz(rq_irt)
    rq = total(r_cendiv.join(rq_irt, on="r", how="inner"), ["cendiv", "t"])
    R["repgasquant"] = nz(rq)
    R["repgasquant_gb"] = empty(["cendiv", "gb", "t"])
    R["repgasquant_nat"] = nz(total(rq, ["t"]))
    gpa = val(S.gasprice_adj_r, "gpa")
    fp = val(S.fuel_price, "fp")
    gp_num = (gas_gen.join(fp, on=["i", "r", "t"], how="inner").join(gpa, on=["r", "h"], how="inner")
              .with_columns((pl.col("value") * pl.col("fp") * pl.col("gpa")).alias("value")))
    gp_num_cd = total(r_cendiv.join(gp_num, on="r", how="inner"), ["cendiv", "t"])
    if gascurve == 2:
        R["repgasprice"] = nz(div(gp_num_cd, scale(rq, 1e9), ["cendiv", "t"]))
        R["repgasprice_r"] = nz(total(r_cendiv.join(R["repgasprice"], on="cendiv", how="inner"), ["r", "t"]))
    else:
        gmt = val(S.gasmultterm, "gmt")
        wts = val(S.cendiv_weights, "w")
        base_num = (wts.join(gmt, on="cendiv", how="inner").join(gpa, on="r", how="inner").join(H.hours, on="h", how="inner")
                    .with_columns((pl.col("gmt") * pl.col("w") * pl.col("hours") * pl.col("gpa")).alias("value")))
        base = scale(total(base_num, ["r", "t"]), 1.0 / float(H.hours["hours"].sum()))
        vreg = H.L("VGASBINQ_REGIONAL")
        vnat = H.L("VGASBINQ_NATIONAL")
        reg_max = (r_cendiv.join(vreg.select(["fuelbin", "cendiv", "t"]), on="cendiv", how="inner")
                   .join(S.gasbinp_regional, on=["fuelbin", "cendiv", "t"], how="inner").group_by(["r", "t"]).agg(pl.col("value").max()))
        nat_max = vnat.select(["fuelbin", "t"]).join(S.gasbinp_national, on=["fuelbin", "t"], how="inner").group_by("t").agg(pl.col("value").max())
        dom = S.r.join(H.C.tmodel_new, how="cross")
        price_r = (dom.join(base.rename({"value": "b"}), on=["r", "t"], how="left").join(reg_max.rename({"value": "rm"}), on=["r", "t"], how="left")
                   .join(nat_max.rename({"value": "nm"}), on="t", how="left")
                   .with_columns((pl.col("b").fill_null(0.0) + pl.col("rm").fill_null(float("-inf")) + pl.col("nm").fill_null(float("-inf"))).alias("value")))
        R["repgasprice_r"] = nz(price_r.select(["r", "t", "value"]))
        price_num = total(r_cendiv.join(mul(rq_irt, R["repgasprice_r"], ["r", "t"]), on="r", how="inner"), ["cendiv", "t"])
        R["repgasprice"] = nz(div(price_num, rq, ["cendiv", "t"]))
    R["repgasprice_nat"] = nz(div(total(mul(R["repgasprice"], rq, ["cendiv", "t"]), ["t"]), total(rq, ["t"]), ["t"]))
    share_ba = div(total(semi(rq_irt.filter(isin("i", gas)), S.valgen_irt, ["i", "r", "t"]).join(r_cendiv, on="r", how="inner"), ["r", "cendiv", "t"]),
                   rq, ["cendiv", "t"])
    R["gasshare_ba"] = nz(share_ba)
    R["gasshare_techba"] = nz(div(rq_irt.filter(isin("i", gas)).join(r_cendiv, on="r", how="inner").select(["i", "r", "cendiv", "t", "value"]), rq, ["cendiv", "t"]))
    R["gasshare_cendiv"] = nz(div(rq, total(rq, ["t"]), ["t"]))
    bio = H.set_members("bio")
    cofire = H.set_members("cofire")
    gp_num_noncofire = gp_num.filter(~isin("i", bio) & ~isin("i", cofire))
    if gascurve == 2:
        R["gascost_cendiv"] = nz(total(r_cendiv.join(gp_num_noncofire, on="r", how="inner"), ["cendiv", "t"]))
    else:
        use_r = total(gas_gen.join(gpa, on=["r", "h"], how="inner").with_columns((pl.col("value") * pl.col("gpa")).alias("value")), ["r", "t"])
        anticipated = total(use_r.join(wts, on="r", how="inner").join(gmt, on=["cendiv", "t"], how="inner")
                            .with_columns((pl.col("value") * pl.col("w") * pl.col("gmt")).alias("value")), ["cendiv", "t"])
        reg_cost = total(mul(vreg, S.gasbinp_regional, ["fuelbin", "cendiv", "t"]), ["cendiv", "t"])
        nat_cost = mul(R["gasshare_cendiv"], total(mul(vnat, S.gasbinp_national, ["fuelbin", "t"]), ["t"]), ["t"])
        R["gascost_cendiv"] = nz(add([anticipated, reg_cost, nat_cost], ["cendiv", "t"]))
    cofire_perc = H.scalar("bio_cofire_perc")
    bio_gen = (semi(gen.filter(isin("i", bio | cofire)), S.valgen, V4).join(hr, on=V4, how="inner").join(H.hours, on="h", how="inner")
               .with_columns((pl.when(isin("i", cofire)).then(cofire_perc).otherwise(1.0) * pl.col("hours") * pl.col("hr") * pl.col("value")).alias("value")))
    bio_irt = total(bio_gen, ["i", "r", "t"])
    R["bioshare_techba"] = nz(div(bio_irt, total(bio_irt, ["r", "t"]), ["r", "t"]))


# ----------------------------------------------------------------------------- generation and storage
def generation(H: Helpers, R: dict) -> None:
    S, C = H.S, H.C
    gen = H.L("GEN")
    gen_rep = H.rep(gen)
    stor_in = H.L("STORAGE_IN")
    charge_techs = H.set_members("storage_standalone") | H.set_members("hyd_add_pump")
    prod_load_h = R["_prod_load_h"]

    def gen_h_of(gen_df: pl.DataFrame, stin_df: pl.DataFrame, prod: pl.DataFrame) -> pl.DataFrame:
        g = semi(gen_df, S.valgen, V4)
        s = semi(stin_df.filter(isin("i", charge_techs)), S.valgen, V4)
        out = sub(total(g, ["i", "r", "h", "t"]), total(s, ["i", "r", "h", "t"]), ["i", "r", "h", "t"])
        out = sub(out, prod, ["i", "r", "h", "t"])
        return semi(out, S.valgen_irt, ["i", "r", "t"])

    gen_h = gen_h_of(gen_rep, H.rep(stor_in), prod_load_h)
    cspns = S._inputs.par("cap_cspns", ["r", "t"]) if "cap_cspns" in S._inputs else empty(["r", "t"])
    cspns = cspns.with_columns(pl.col("t").cast(pl.Utf8)).filter(pl.col("value") != 0.0)
    cspns = semi(cspns, C.tmodel_new, ["t"])
    if cspns.height:
        mcf5 = (S.m_cf.filter((pl.col("i") == "upv_5") & (pl.col("v") == "new1") & isin("h", H.h_rep)).join(S.i_c.filter(pl.col("i") == "upv_5"), on=["i", "c"], how="semi")
                .group_by(["r", "h", "t"]).agg(pl.col("value").sum()))
        gen_cspns = mul(cspns.join(S.h.filter(isin("h", H.h_rep)), how="cross").select(["r", "h", "t", "value"]), mcf5, ["r", "h", "t"], how="left")
        gen_cspns = lit(gen_cspns, i="csp-ns").select(["i", "r", "h", "t", "value"])
        upv5 = gen_h.filter(pl.col("i") == "upv_5")
        upv5_new = (cspns.select(["r", "t"]).join(S.h.filter(isin("h", H.h_rep)), how="cross").join(upv5, on=["r", "h", "t"], how="left")
                    .with_columns(pl.col("value").fill_null(0.0)).join(val(gen_cspns, "c"), on=["r", "h", "t"], how="left")
                    .with_columns(pl.max_horizontal(pl.lit(0.0), pl.col("value") - pl.col("c").fill_null(0.0)).alias("value"))
                    .with_columns(pl.lit("upv_5").alias("i")).select(["i", "r", "h", "t", "value"]))
        drop_rows = pl.concat([lit(cspns.select(["r", "t"]), i="upv_5"), lit(cspns.select(["r", "t"]), i="csp-ns")]).select(["i", "r", "t"])
        gen_h = pl.concat([anti(gen_h, drop_rows, ["i", "r", "t"]), upv5_new, gen_cspns])
    R["gen_h"] = nz(gen_h)
    R["gen_h_nat"] = nz(total(gen_h, ["i", "h", "t"]))
    gen_stress = gen_h_of(semi(gen, C.h_stress_t, ["h", "t"]), semi(stor_in, C.h_stress_t, ["h", "t"]),
                          (semi(H.L("PRODUCE"), C.h_stress_t, ["h", "t"]).filter(isin("i", H.set_members("consume"))).join(S.valcap, on=V4, how="semi")
                           .join(S.i_p, on=["i", "p"], how="semi").join(val(S.prod_conversion_rate, "pcr"), on=V4, how="inner")
                           .with_columns((pl.col("value") / pl.col("pcr")).alias("value")).pipe(total, ["i", "r", "h", "t"]))
                          if H.swi("Sw_Prod") else empty(["i", "r", "h", "t"]))
    R["gen_h_stress"] = nz(gen_stress)
    R["gen_h_stress_nat"] = nz(total(gen_stress, ["i", "h", "t"]))
    gen_ann = total(mul(gen_h, H.hours.rename({"hours": "value"}), ["h"]), ["i", "r", "t"])
    R["gen_ann"] = nz(gen_ann)
    R["gen_ann_nat"] = nz(total(gen_ann, ["i", "t"]))
    gen_ivrt = H.hours_sum(semi(gen_rep, S.valgen, V4), V4)
    R["gen_ivrt"] = nz(gen_ivrt)
    vre = H.set_members("vre")
    hyb = H.set_members("storage_hybrid") - H.set_members("csp")
    cap = H.L("CAP")
    mcf_ivrht = total(S.m_cf.filter(isin("h", H.h_rep)).join(S.i_c, on=["i", "c"], how="semi"), ["i", "v", "r", "h", "t"])
    uncurt = (semi(cap.filter(isin("i", vre | hyb)), S.valgen, V4).join(val(mcf_ivrht, "cf"), on=V4, how="inner")
              .join(H.hours, on="h", how="inner").with_columns((pl.col("cf") * pl.col("value") * pl.col("hours")).alias("value")))
    gen_ivrt_uncurt = total(uncurt, V4)
    R["gen_ivrt_uncurt"] = nz(gen_ivrt_uncurt)
    R["_mcf_cap_h"] = semi(cap, S.valcap, V4).join(val(mcf_ivrht, "cf"), on=V4, how="inner").with_columns((pl.col("cf") * pl.col("value")).alias("value")).select(["i", "v", "r", "h", "t", "value"])
    gu = add([total(semi(gen_ivrt.filter(~isin("i", vre)), S.valgen_irt, ["i", "r", "t"]), ["i", "r", "t"]),
              total(semi(gen_ivrt_uncurt.filter(isin("i", vre)), S.valgen_irt, ["i", "r", "t"]), ["i", "r", "t"])], ["i", "r", "t"])
    R["gen_uncurtailed"] = nz(gu)
    R["gen_uncurtailed_nat"] = nz(total(gu, ["i", "t"]))
    storage = H.set_members("storage")
    stin_v = semi(H.rep(stor_in).filter(isin("i", storage - hyb)), S.valgen, V4)
    s_in = lit(H.hours_sum(stin_v, V4), slot="in")
    s_out = lit(semi(gen_ivrt.filter(isin("i", storage)), S.valgen, V4), slot="out")
    R["stor_inout"] = nz(pl.concat([s_in, s_out]).select(V4 + ["slot", "value"]))
    R["stor_in"] = nz(stin_v.select(["i", "v", "r", "h", "t", "value"]))
    R["stor_out"] = nz(semi(gen_rep.filter(isin("i", storage)), S.valgen, V4).select(["i", "v", "r", "h", "t", "value"]))
    R["stor_level"] = nz(semi(H.rep(H.L("STORAGE_LEVEL")).filter(isin("i", storage)), S.valgen, V4).select(["i", "v", "r", "h", "t", "value"]))
    interday = H.set_members("storage_interday")
    R["stor_interday_level"] = nz(semi(H.L("STORAGE_INTERDAY_LEVEL").filter(isin("i", interday)), S.valgen, V4).select(["i", "v", "r", "szn", "t", "value"]))
    R["stor_interday_dispatch"] = nz(semi(H.rep(H.L("STORAGE_INTERDAY_DISPATCH")).filter(isin("i", interday)), S.valgen, V4).select(["i", "v", "r", "h", "t", "value"]))


# ----------------------------------------------------------------------------- water
def water(H: Helpers, R: dict) -> None:
    S = H.S
    if H.swi("Sw_WaterMain"):
        raise NotImplementedError("water accounting outputs are not ported")
    for name, dims in [("water_withdrawal_ivrt", V4), ("water_consumption_ivrt", V4), ("watcap_ivrt", V4), ("watcap_out", ["i", "r", "t"]),
                       ("watcap_new_out", ["i", "r", "t"]), ("watcap_new_ivrt", V4), ("watcap_new_ann_out", V4), ("watret_out", ["i", "r", "t"]),
                       ("watret_ivrt", V4), ("watret_ann_out", V4)]:
        R[name] = empty(dims)


# ----------------------------------------------------------------------------- operating reserves, losses, curtailment
def reserves_and_losses(H: Helpers, R: dict) -> None:
    S, C = H.S, H.C
    opres = H.L("OPRES", rep=True)
    rf = S.reserve_frac.select(["i", "ortype"])
    sup_h = total(semi(opres, rf, ["i", "ortype"]), ["ortype", "i", "r", "h", "t"])
    R["opRes_supply_h"] = nz(sup_h)
    R["opRes_supply"] = nz(total(mul(sup_h, H.hours.rename({"hours": "value"}), ["h"]), ["ortype", "i", "r", "t"]))
    oflow = H.L("OPRES_FLOW", rep=True)
    R["opres_trade"] = nz(total(mul(semi(oflow, S.opres_routes, ["r", "rr", "t"]), H.hours.rename({"hours": "value"}), ["h"]), ["ortype", "r", "rr", "t"]))

    vre = H.set_members("vre")
    hyb = H.set_members("storage_hybrid") - H.set_members("csp")
    inv = H.L("INV")
    refurb = H.L("INV_REFURB")
    mcf_ivrht = total(S.m_cf.filter(isin("h", H.h_rep)).join(S.i_c, on=["i", "c"], how="semi"), ["i", "v", "r", "h", "t"])
    new = semi(add([inv, refurb], V4).filter(isin("i", vre | hyb)), S.valinv, V4)
    gnu = (new.join(val(mcf_ivrht, "cf"), on=V4, how="inner").join(H.hours, on="h", how="inner")
           .with_columns((pl.col("value") * pl.col("cf") * pl.col("hours")).alias("value")))
    R["gen_new_uncurt"] = nz(semi(total(gnu, ["i", "r", "h", "t"]), S.valcap_irt, ["i", "r", "t"]))
    mcf_cap = R["_mcf_cap_h"].filter(isin("i", vre | hyb))
    gen = H.L("GEN", rep=True)
    gen_vre = semi(gen.filter(isin("i", vre)), S.valgen, V4)
    gen_plant = semi(H.rep(H.L("GEN_PLANT")).filter(isin("i", hyb)), S.valgen, V4) if H.swi("Sw_HybridPlant") else empty(["i", "v", "r", "h", "t"])
    opres_h = members(S.opres_h)
    opres_vre = semi(opres.filter(isin("i", vre) & isin("h", opres_h)), rf, ["i", "ortype"]) if H.swi("Sw_OpRes") else empty(["ortype", "i", "v", "r", "h", "t"])
    opres_vre = semi(opres_vre, S.valgen, V4)
    curt_h = sub(sub(sub(total(mcf_cap, ["r", "h", "t"]), total(gen_vre, ["r", "h", "t"]), ["r", "h", "t"]), total(gen_plant, ["r", "h", "t"]), ["r", "h", "t"]),
                 total(opres_vre, ["r", "h", "t"]), ["r", "h", "t"])
    R["curt_h"] = nz(curt_h)
    curt_ann = total(mul(curt_h, H.hours.rename({"hours": "value"}), ["h"]), ["r", "t"])
    R["curt_ann"] = nz(curt_ann)
    hrs = H.hours.rename({"hours": "value"})
    curt_tech = sub(sub(total(mul(mcf_cap.filter(isin("i", vre)), hrs, ["h"]), ["i", "r", "t"]), total(mul(gen_vre, hrs, ["h"]), ["i", "r", "t"]), ["i", "r", "t"]),
                    total(mul(opres_vre, hrs, ["h"]), ["i", "r", "t"]), ["i", "r", "t"])
    R["curt_tech"] = nz(curt_tech)
    gen_ann = R["gen_ann"]
    den = add([semi(gen_ann, curt_tech.select(["i", "r", "t"]), ["i", "r", "t"]).filter(isin("i", vre)), curt_tech], ["i", "r", "t"])
    R["curt_rate_tech"] = nz(div(curt_tech, den, ["i", "r", "t"]))
    den_t = add([total(gen_ann.filter(isin("i", vre | hyb)), ["t"]), total(curt_ann, ["t"])], ["t"])
    R["curt_rate"] = nz(div(total(curt_ann, ["t"]), den_t, ["t"]))

    stor_sa = H.set_members("storage_standalone")
    stin = semi(H.L("STORAGE_IN", rep=True).filter(isin("i", stor_sa)), S.valcap, V4)
    gsa = semi(gen.filter(isin("i", stor_sa)), S.valcap, V4)
    l_stor = lit(sub(total(mul(stin, hrs, ["h"]), ["t"]), total(mul(gsa, hrs, ["h"]), ["t"]), ["t"]), cat="storage")
    flow = H.L("FLOW", rep=True)
    tl = (semi(flow, S.routes, ["r", "rr", "trtype", "t"]).join(val(S.tranloss, "tl"), on=["r", "rr", "trtype"], how="inner")
          .with_columns((pl.col("tl") * pl.col("value")).alias("value")))
    if H.swi("Sw_VSC"):
        conv = H.rep(semi(H.L("CONVERSION"), S.val_converter, ["r", "t"]))
        conv_loss = scale(total(conv, ["r", "h", "t"]), 1.0 - H.scalar("converter_efficiency_vsc"))
        conv_rows = (S.routes.join(C.tmodel_new, on="t", how="semi").join(conv_loss.rename({"r": "rr"}), on=["rr", "t"], how="inner")
                     .select(["r", "rr", "h", "trtype", "t", "value"]))
        tl = add([tl.select(["r", "rr", "h", "trtype", "t", "value"]), conv_rows], ["r", "rr", "h", "trtype", "t"])
    l_tran = lit(total(mul(tl, hrs, ["h"]), ["t"]), cat="trans")
    l_curt = lit(total(curt_ann, ["t"]), cat="curt")
    l_load = lit(total(mul(H.L("LOAD", rep=True), hrs, ["h"]), ["t"]), cat="load")
    R["losses_ann"] = nz(pl.concat([l_stor, l_tran, l_curt, l_load]).select(["cat", "t", "value"]))
    R["losses_tran_h"] = nz(tl.rename({"r": "rr", "rr": "r"}).select(["rr", "r", "h", "trtype", "t", "value"]))


# ----------------------------------------------------------------------------- capacity
def capacity(H: Helpers, R: dict) -> None:
    S, C = H.S, H.C
    cap = semi(H.L("CAP"), S.valcap, V4)
    ilr = val(S.ilr, "ilr")
    cap_deg = cap.join(ilr, on="i", how="inner").with_columns((pl.col("value") / pl.col("ilr")).alias("value")).select(V4 + ["value"])
    R["cap_deg_ivrt"] = nz(cap_deg)
    degr = H.set_members("upv") | H.set_members("wind") | H.set_members("distpv")
    inv = H.L("INV")
    refurb = H.L("INV_REFURB") if H.swi("Sw_Refurb") else empty(V4)
    refurbtech = H.set_members("refurbtech")
    inv_both = add([inv, refurb.filter(isin("i", refurbtech))], V4)
    solved = C.tmodel_new
    cond = semi(semi(S.inv_cond, S.valcap, V4).filter(isin("i", degr)), solved.rename({"t": "tt"}), ["tt"])
    inv_part = total(cond.join(val(inv_both, "iv").rename({"t": "tt"}), on=["i", "v", "r", "tt"], how="inner").rename({"iv": "value"}), V4)
    exog = semi(S.m_capacity_exog.filter(isin("i", degr)), C.tmodel_new, ["t"])
    cap_degr = semi(add([exog, inv_part], V4), S.valcap, V4).join(ilr, on="i", how="inner").with_columns((pl.col("value") / pl.col("ilr")).alias("value")).select(V4 + ["value"])
    cap_ivrt = pl.concat([cap_deg.filter(~isin("i", degr)), cap_degr])
    R["cap_ivrt"] = nz(cap_ivrt)
    cap_out = semi(total(cap_ivrt, ["i", "r", "t"]), S.valcap_irt, ["i", "r", "t"])
    cspns = S._inputs.par("cap_cspns", ["r", "t"]).with_columns(pl.col("t").cast(pl.Utf8)) if "cap_cspns" in S._inputs else empty(["r", "t"])
    cspns = semi(cspns.filter(pl.col("value") != 0.0), C.tmodel_new, ["t"])
    if cspns.height:
        upv5 = cap_out.filter(pl.col("i") == "upv_5")
        upv5_new = (cspns.select(["r", "t"]).join(upv5, on=["r", "t"], how="left").with_columns(pl.col("value").fill_null(0.0))
                    .join(val(cspns, "c"), on=["r", "t"], how="inner")
                    .with_columns(pl.max_horizontal(pl.lit(0.0), pl.col("value") - pl.col("c")).alias("value")).with_columns(pl.lit("upv_5").alias("i")))
        cap_out = pl.concat([anti(cap_out, upv5_new, ["i", "r", "t"]), upv5_new.select(["i", "r", "t", "value"]),
                             lit(cspns, i="csp-ns").select(["i", "r", "t", "value"])])
    R["cap_out"] = nz(cap_out)
    R["cap_nat"] = nz(total(cap_out, ["i", "t"]))
    R["cap_exog"] = nz(semi(S.m_capacity_exog, C.tmodel_new, ["t"]))

    upgrade = H.set_members("upgrade")
    up = semi(H.L("UPGRADES").filter(isin("i", upgrade)), S.valcap, V4) if H.swi("Sw_Upgrades") else empty(V4)
    upret = semi(H.L("UPGRADES_RETIRE").filter(isin("i", upgrade)), S.valcap, V4) if H.swi("Sw_Upgrades") else empty(V4)
    derate = S.upgrade_derate
    up_net = (sub(up, upret, V4).join(val(derate, "d"), on=V4, how="left")
              .with_columns((pl.col("value") * (1.0 - pl.col("d").fill_null(0.0))).alias("value")))
    new_ivrt = add([semi(inv_both, S.valinv, V4), up_net], V4)
    new_ivrt = semi(new_ivrt, S.valcap, V4).join(ilr, on="i", how="inner").with_columns((pl.col("value") / pl.col("ilr")).alias("value")).select(V4 + ["value"])
    tprev = C.tprev()
    distpv = H.set_members("distpv")
    d_ivrt = cap_ivrt.filter(isin("i", distpv))
    d_prev = d_ivrt.join(tprev, on="t", how="inner").join(val(d_ivrt, "p").rename({"t": "tt"}), on=["i", "v", "r", "tt"], how="left")
    d_new = pl.concat([d_ivrt.filter(pl.col("t") == C.tfirst),
                       d_prev.with_columns((pl.col("value") - pl.col("p").fill_null(0.0)).alias("value")).select(V4 + ["value"])])
    new_ivrt = pl.concat([new_ivrt.filter(~isin("i", distpv)), d_new])
    R["cap_new_ivrt"] = nz(new_ivrt)
    new_out = semi(total(new_ivrt.filter(~isin("i", distpv)), ["i", "r", "t"]), S.valcap_irt, ["i", "r", "t"])
    d_out = cap_out.filter(isin("i", distpv))
    d_out_prev = d_out.join(tprev, on="t", how="inner").join(val(d_out, "p").rename({"t": "tt"}), on=["i", "r", "tt"], how="left")
    d_out_new = pl.concat([d_out.filter(pl.col("t") == C.tfirst), d_out_prev.with_columns((pl.col("value") - pl.col("p").fill_null(0.0)).alias("value")).select(["i", "r", "t", "value"])])
    new_out = pl.concat([new_out, semi(d_out_new, S.valcap_irt, ["i", "r", "t"])])
    R["cap_new_out"] = nz(new_out)
    gap = C.year_gap()
    R["cap_new_ann"] = nz(new_out.join(gap, on="t", how="inner").with_columns((pl.col("value") / pl.col("gap")).alias("value")).drop("gap"))
    R["cap_new_ann_nat"] = nz(total(R["cap_new_ann"], ["i", "t"]))
    rsc = H.set_members("rsc_i")
    inv_rsc = H.L("INV_RSC")
    bin_rsc = semi(inv_rsc.filter(isin("i", rsc)), S.valinv, V4)
    bin_non = lit(semi(inv.filter(~isin("i", rsc)), S.valinv, V4), rscbin="bin1")
    cnb = pl.concat([bin_rsc.select(V4 + ["rscbin", "value"]), bin_non.select(V4 + ["rscbin", "value"])])
    cnb = cnb.join(ilr, on="i", how="inner").with_columns((pl.col("value") / pl.col("ilr")).alias("value")).select(V4 + ["rscbin", "value"])
    R["cap_new_bin_out"] = nz(cnb)
    R["cap_new_ivrt_refurb"] = nz(semi(refurb, S.valinv, V4).join(ilr, on="i", how="inner").with_columns((pl.col("value") / pl.col("ilr")).alias("value")).select(V4 + ["value"]))
    R["site_spurinv"] = nz(semi(H.L("INV_SPUR"), S.xfeas, ["x"]))
    R["site_spurcap"] = nz(semi(H.L("CAP_SPUR"), S.xfeas, ["x"]))
    sitemap = S._inputs.set("spurline_sitemap", ["i", "r", "rscbin", "x"]) if "spurline_sitemap" in S._inputs else empty(["i", "r", "rscbin", "x"]).drop("value")
    cnb_ilr = mul(cnb, S.ilr, ["i"]).rename({"t": "tt"})
    site = (sitemap.join(cnb_ilr, on=["i", "r", "rscbin"], how="inner").join(C.tmodel_new, how="cross")
            .filter(pl.col("tt").cast(pl.Int64) <= pl.col("t").cast(pl.Int64)))
    R["site_cap"] = nz(total(site, ["i", "x", "t"]))
    R["site_gir"] = nz(div(R["site_cap"], R["site_spurcap"], ["x", "t"]))
    upv = H.set_members("upv")
    spur_techs = H.set_members("spur_techs")
    pvfrac = div(total(R["site_cap"].filter(isin("i", upv)), ["x", "t"]), total(R["site_cap"].filter(isin("i", spur_techs)), ["x", "t"]), ["x", "t"])
    R["site_pv_fraction"] = nz(pvfrac)
    R["site_hybridization"] = nz(pvfrac.with_columns((1.0 - 2.0 * (pl.col("value") - 0.5).abs()).abs().alias("value")))

    mrd_cap = S.m_rsc_dat.filter(pl.col("sc_cat") == "cap").select(["r", "i", "rscbin", "value"])
    avail_dom = (semi(S.m_rscfeas.join(S.m_rsc_con, on=["r", "i"], how="semi"), S.rsc_i, ["i"]).join(C.tmodel_new, how="cross"))
    base = avail_dom.join(val(mrd_cap, "cap"), on=["r", "i", "rscbin"], how="left").with_columns(pl.col("cap").fill_null(0.0))
    if H.swi("Sw_HydroCapEnerUpgradeType") == 1:
        base = base.join(val(S.hyd_add_upg_cap, "hau"), on=["r", "i", "rscbin", "t"], how="left").with_columns((pl.col("cap") + pl.col("hau").fill_null(0.0)).alias("cap"))
    agg = S.rsc_agg
    scaler = val(S.resourcescaler, "rs")
    used = (semi(inv_rsc, S.valinv, V4).rename({"i": "ii", "t": "tt"}).join(agg, on="ii", how="inner").join(scaler.rename({"i": "ii"}), on="ii", how="left")
            .with_columns((pl.col("value") * pl.col("rs").fill_null(0.0)).alias("value")))
    used = used.join(C.tmodel_new, how="cross").filter(pl.col("tt").cast(pl.Int64) < pl.col("t").cast(pl.Int64))
    used = total(used, ["i", "r", "rscbin", "t"])
    exog_rsc = H.set_members("exog_rsc")
    cer = (S.capacity_exog_rsc.filter(pl.col("t") == C.tfirst).rename({"i": "ii"}).join(agg.filter(isin("i", exog_rsc)), on="ii", how="inner"))
    cer = total(cer, ["i", "r", "rscbin"]).join(C.tmodel_new, how="cross")
    cap_avail = (base.join(val(used, "u"), on=["i", "r", "rscbin", "t"], how="left").join(val(cer, "x"), on=["i", "r", "rscbin", "t"], how="left")
                 .with_columns((pl.col("cap") - pl.col("u").fill_null(0.0) - pl.col("x").fill_null(0.0)).alias("value")))
    R["cap_avail"] = nz(cap_avail.select(["i", "r", "t", "rscbin", "value"]))
    hset = pl.concat([C.h_stress_t, S.h_rep.join(C.tmodel_new, how="cross")]).unique()
    offline = (cap_out.join(hset, on="t", how="inner").join(val(S.avail, "a"), on=["i", "r", "h"], how="left")
               .with_columns((pl.col("value") * (1.0 - pl.col("a").fill_null(0.0))).alias("value")))
    R["capacity_offline"] = nz(semi(offline, S.valcap_irt, ["i", "r", "t"]).select(["i", "r", "h", "t", "value"]))
    of = S._outage_forced_h if "_outage_forced_h" in S else None
    if of is None:
        raise KeyError("outage_forced_h was not kept by derive_temporal; the forced_outage output needs it")
    hours_rep_total = float(H.hours["hours"].sum())
    num = total(of.join(H.hours, on="h", how="inner").with_columns((pl.col("value") * pl.col("hours")).alias("value")), ["i"])
    den = hours_rep_total * S.r.height
    R["forced_outage"] = nz(scale(num, 1.0 / den))
    os_ = S._outage_scheduled_h
    num_s = total(os_.join(H.hours, on="h", how="inner").with_columns((pl.col("value") * pl.col("hours")).alias("value")), ["i"])
    R["planned_outage"] = nz(scale(num_s, 1.0 / hours_rep_total))

    up_d = up.join(val(derate, "d"), on=V4, how="left").with_columns((pl.col("value") * (1.0 - pl.col("d").fill_null(0.0))).alias("value"))
    R["cap_upgrade"] = nz(semi(total(up_d, ["i", "r", "t"]), S.valcap_irt, ["i", "r", "t"]))
    R["cap_upgrade_ivrt"] = nz(up_d.select(V4 + ["value"]))

    up_from = S.upgrade_from.rename({"i": "ii", "ii": "i"})
    up_src = total(up.rename({"i": "ii"}).join(up_from, on="ii", how="inner"), V4)
    dom = pl.concat([cap_ivrt.select(V4), new_ivrt.select(V4), up_src.select(V4)]).unique().filter(pl.col("t") != C.tfirst)
    prev_all = (val(cap_ivrt, "p").rename({"t": "tt"}).join(tprev, on="tt", how="inner").select(V4 + [pl.col("p").alias("value")]))
    dom = pl.concat([dom, prev_all.select(V4)]).unique()
    ret = (dom.join(val(prev_all, "p"), on=V4, how="left").join(val(cap_ivrt, "c"), on=V4, how="left").join(val(new_ivrt, "n"), on=V4, how="left")
           .join(val(up_src, "u"), on=V4, how="left")
           .with_columns((pl.col("p").fill_null(0.0) - pl.col("c").fill_null(0.0) + pl.col("n").fill_null(0.0) - pl.col("u").fill_null(0.0)).alias("value")))
    ret = ret.with_columns(pl.when(pl.col("value").abs() < 1e-6).then(0.0).otherwise(pl.col("value")).alias("value")).select(V4 + ["value"])
    R["ret_ivrt"] = nz(ret)
    ret_out = total(ret, ["i", "r", "t"]).with_columns(pl.when(pl.col("value").abs() < 1e-6).then(0.0).otherwise(pl.col("value")).alias("value"))
    R["ret_out"] = nz(ret_out)
    R["ret_ann"] = nz(ret_out.join(gap, on="t", how="inner").with_columns((pl.col("value") / pl.col("gap")).alias("value")).drop("gap"))
    R["ret_ann_nat"] = nz(total(R["ret_ann"], ["i", "t"]))

    R["cap_sdbin_out"] = nz(semi(total(H.L("CAP_SDBIN"), ["i", "r", "ccseason", "sdbin", "t"]), S.valcap_irt, ["i", "r", "t"]))
    csp_stor = H.set_members("csp_storage")
    psh = H.set_members("psh")
    battery = H.set_members("battery")
    hyb = H.set_members("storage_hybrid") - H.set_members("csp")
    bcr = val(S.bcr, "bcr")
    sec = (cap.join(val(S.storage_duration_m, "sd"), on=["i", "v", "r"], how="inner").join(bcr, on="i", how="left")
           .with_columns((pl.when(isin("i", csp_stor)).then(1.0).otherwise(0.0) + pl.when(isin("i", psh)).then(1.0).otherwise(0.0)
                          + pl.when(isin("i", battery | hyb)).then(pl.col("bcr").fill_null(0.0)).otherwise(0.0)).alias("mult"))
           .with_columns((pl.col("sd") * pl.col("value") * pl.col("mult")).alias("value")).select(V4 + ["value"]))
    R["stor_energy_cap"] = nz(sec)
    cap_energy = semi(H.L("CAP_ENERGY"), S.valcap, V4)
    psh_energy = cap.filter(isin("i", psh)).join(val(S.storage_duration_m, "sd"), on=["i", "v", "r"], how="inner").with_columns((pl.col("value") * pl.col("sd")).alias("value")).select(V4 + ["value"])
    R["cap_energy_ivrt"] = nz(pl.concat([anti(cap_energy, psh_energy, V4), psh_energy]))
    R["storage_duration_out"] = nz(div(cap_energy.filter(isin("i", battery)), cap.filter(isin("i", battery)), V4))

    cc_i = H.set_members("vre") | H.set_members("csp") | H.set_members("storage") | hyb
    R["cc_all_out"] = empty(["i", "v", "r", "ccseason", "t"])
    cc_techs = H.set_members("vre") | H.set_members("storage") | hyb
    new_ivt = semi(new_ivrt.filter(isin("i", cc_techs)), S.ivt, ["i", "v", "t"])
    new_cc = semi(total(new_ivt, ["i", "r", "t"]), S.valcap_irt, ["i", "r", "t"])
    ccseason = S._inputs.set("ccseason", ["ccseason"])
    R["cap_new_cc"] = nz(new_cc.join(ccseason, how="cross").select(["i", "r", "ccseason", "t", "value"]))
    R["cc_new"] = empty(["i", "r", "ccseason", "t"])
    R["cap_firm"] = empty(["i", "r", "ccseason", "t"])
    if H.swi("Sw_PRM_CapCredit"):
        raise NotImplementedError("capacity-credit outputs for Sw_PRM_CapCredit=1 are not ported")
    R["captrade"] = nz(semi(semi(H.L("PRMTRADE"), S.routes, ["r", "rr", "trtype", "t"]), S.routes_prm, ["r", "rr"]).select(["r", "rr", "trtype", "ccseason", "t", "value"]))
    R["_cap_out"] = cap_out
    R["_cap_ivrt"] = cap_ivrt
    R["_new_ivrt"] = new_ivrt
    R["_inv_both"] = inv_both


# ----------------------------------------------------------------------------- revenue, value of new builds
def revenue(H: Helpers, R: dict) -> None:
    S, C = H.S, H.C
    price = R["reqt_price"]
    quant = R["reqt_quant"]
    p_load = price.filter(pl.col("cat") == "load").select(["r", pl.col("slot").alias("h"), "t", "value"])
    p_rm = price.filter(pl.col("cat") == "res_marg").select(["r", pl.col("slot").alias("h"), "t", "value"])
    p_or = price.filter(pl.col("cat") == "oper_res").select([pl.col("sub").alias("ortype"), "r", pl.col("slot").alias("h"), "t", "value"])
    p_rps = price.filter(pl.col("cat") == "state_rps").select([pl.col("sub").alias("rpscat"), "r", "t", "value"])
    gen = semi(H.L("GEN", rep=True), S.valgen, V4)
    hrs = H.hours.rename({"hours": "value"})
    rev_load = semi(total(mul(mul(gen, hrs, ["h"]), p_load, ["r", "h", "t"]), ["i", "r", "t"]), S.valgen_irt, ["i", "r", "t"])
    stor_sa = H.set_members("storage_standalone")
    stin = semi(H.L("STORAGE_IN", rep=True).filter(isin("i", stor_sa)), S.valgen, V4)
    rev_charge = scale(semi(total(mul(mul(stin, hrs, ["h"]), p_load, ["r", "h", "t"]), ["i", "r", "t"]), S.valgen_irt, ["i", "r", "t"]), -1.0)
    rev_rm = semi(total(mul(R["gen_h_stress"], p_rm, ["r", "h", "t"]), ["i", "r", "t"]), S.valgen_irt, ["i", "r", "t"])
    opres = semi(H.L("OPRES", rep=True), S.valgen, V4)
    rev_or = semi(total(mul(mul(opres, hrs, ["h"]), p_or, ["ortype", "r", "h", "t"]), ["i", "r", "t"]), S.valgen_irt, ["i", "r", "t"])
    rectech_r = S.r_st.join(S.rectech, on="st", how="inner").select(["rpscat", "i", "r", "t"]).unique()
    mult_r = total(S.r_st.join(S.rpstechmult, on="st", how="inner"), ["rpscat", "i", "r"])
    rps_gen = (mul(gen, hrs, ["h"]).join(S.rpscat, how="cross").join(rectech_r, on=["rpscat", "i", "r", "t"], how="semi")
               .join(val(mult_r, "m"), on=["rpscat", "i", "r"], how="left").join(val(p_rps, "p"), on=["rpscat", "r", "t"], how="left")
               .with_columns((pl.col("value") * pl.col("m").fill_null(0.0) * pl.col("p").fill_null(0.0)).alias("value")))
    rev_rps = semi(total(rps_gen, ["i", "r", "t"]), S.valgen_irt, ["i", "r", "t"])
    rev = pl.concat([lit(rev_load, rev_cat="load"), lit(rev_charge, rev_cat="charge"), lit(rev_rm, rev_cat="res_marg"),
                     lit(rev_or, rev_cat="oper_res"), lit(rev_rps, rev_cat="rps")]).select(["rev_cat", "i", "r", "t", "value"])
    R["revenue"] = nz(rev)
    rev_nat = total(rev, ["rev_cat", "i", "t"])
    R["revenue_nat"] = nz(rev_nat)
    vre = H.set_members("vre")
    gen_irt = total(mul(R["gen_h"], hrs, ["h"]), ["i", "r", "t"])
    gen_irt = semi(gen_irt, S.valgen_irt, ["i", "r", "t"])
    uncurt_irt = total(mul(R["_mcf_cap_h"], hrs, ["h"]), ["i", "r", "t"])
    den_en = pl.concat([gen_irt.filter(~isin("i", vre)), uncurt_irt.filter(isin("i", vre))])
    R["revenue_en"] = nz(div(rev, den_en, ["i", "r", "t"]))
    den_en_nat = pl.concat([total(gen_irt.filter(~isin("i", vre)), ["i", "t"]), total(uncurt_irt.filter(isin("i", vre)), ["i", "t"])])
    R["revenue_en_nat"] = nz(div(rev_nat, den_en_nat, ["i", "t"]))
    cap_out = R["_cap_out"]
    R["revenue_cap"] = nz(div(rev, cap_out, ["i", "r", "t"]))
    R["revenue_cap_nat"] = nz(div(rev_nat, total(semi(cap_out, S.valcap_irt, ["i", "r", "t"]), ["i", "t"]), ["i", "t"]))

    inv_both = R["_inv_both"]
    inv_v = semi(inv_both, S.valinv, V4)
    ilr = val(S.ilr, "ilr")
    mw = semi(total(inv_v.filter(pl.col("t") != C.tfirst), ["i", "r", "t"]), S.valcap_irt, ["i", "r", "t"])
    mw = mw.join(ilr, on="i", how="inner").with_columns((pl.col("value") / pl.col("ilr")).alias("value")).select(["i", "r", "t", "value"])
    mw = nz(mw)
    cap = H.L("CAP")
    ratio = total(div(inv_v, cap, V4), ["i", "r", "t"])
    ratio = semi(ratio, mw, ["i", "r", "t"])
    gen_ivrt = R["gen_ivrt"]
    mwh = mul(total(semi(gen_ivrt, S.valinv, V4), ["i", "r", "t"]), ratio, ["i", "r", "t"])
    unc = total(semi(R["gen_ivrt_uncurt"], S.valinv, V4), ["i", "r", "t"]).filter(pl.col("value") != 0.0)
    mwh = pl.concat([anti(mwh, unc, ["i", "r", "t"]), mul(unc, ratio, ["i", "r", "t"])])
    mwh = semi(mwh, mw, ["i", "r", "t"])
    q_load = quant.filter(pl.col("cat") == "load").select(["r", pl.col("slot").alias("h"), "t", "value"])
    q_rm = quant.filter(pl.col("cat") == "res_marg").select(["r", pl.col("slot").alias("h"), "t", "value"])
    q_rm_ann = quant.filter(pl.col("cat") == "res_marg_ann").select(["r", "t", "value"])
    q_or = quant.filter(pl.col("cat") == "oper_res").select([pl.col("sub").alias("ortype"), "r", pl.col("slot").alias("h"), "t", "value"])
    q_rps = quant.filter(pl.col("cat") == "state_rps").select([pl.col("sub").alias("rpscat"), "r", "t", "value"])
    p_sys = R["reqt_price_sys"]
    ps_load = p_sys.filter(pl.col("cat") == "load").select([pl.col("slot").alias("h"), "t", "value"])
    ps_rm = p_sys.filter(pl.col("cat") == "res_marg").select([pl.col("slot").alias("h"), "t", "value"])
    ps_or = p_sys.filter(pl.col("cat") == "oper_res").select([pl.col("sub").alias("ortype"), pl.col("slot").alias("h"), "t", "value"])
    ps_rps = p_sys.filter(pl.col("cat") == "state_rps").select([pl.col("sub").alias("rpscat"), "t", "value"])
    charge_techs = stor_sa | H.set_members("hyd_add_pump")
    gen_all = H.L("GEN")
    stin_all = H.L("STORAGE_IN").filter(isin("i", charge_techs))
    net = semi(sub(gen_all, stin_all, ["i", "v", "r", "h", "t"]), S.valinv, V4)
    net_rep = H.rep(net)
    rows = []

    def add_row(cat: str, df: pl.DataFrame, r_col: str = "r"):
        rows.append(df.select([pl.lit(cat).alias("cat"), pl.col("i"), pl.col(r_col).alias("r"), pl.col("t"), pl.col("value")]))

    def bench(cat: str, df_r: pl.DataFrame, df_sys: pl.DataFrame):
        rows.append(df_r.select([pl.lit(cat).alias("cat"), pl.lit("benchmark").alias("i"), pl.col("r"), pl.col("t"), pl.col("value")]))
        rows.append(df_sys.select([pl.lit(cat).alias("cat"), pl.lit("benchmark").alias("i"), pl.lit("sys").alias("r"), pl.col("t"), pl.col("value")]))

    add_row("MW", mw)
    add_row("inv_cap_ratio", ratio)
    add_row("MWh", mwh)
    bench("MWh", total(q_load, ["r", "t"]), total(q_load, ["t"]))
    bench("MW", q_rm_ann, total(q_rm_ann, ["t"]))
    v_load = mul(total(mul(mul(net_rep, hrs, ["h"]), p_load, ["r", "h", "t"]), ["i", "r", "t"]), ratio, ["i", "r", "t"])
    add_row("val_load", semi(v_load, mw, ["i", "r", "t"]))
    v_load_sys = mul(total(mul(mul(net_rep, hrs, ["h"]), ps_load, ["h", "t"]), ["i", "r", "t"]), ratio, ["i", "r", "t"])
    add_row("val_load_sys", semi(v_load_sys, mw, ["i", "r", "t"]))
    pq_load = mul(p_load, q_load, ["r", "h", "t"])
    bench("val_load", total(pq_load, ["r", "t"]), total(pq_load, ["t"]))
    net_stress = semi(net, C.h_stress_t, ["h", "t"])
    v_rm = mul(total(mul(net_stress, p_rm, ["r", "h", "t"]), ["i", "r", "t"]), ratio, ["i", "r", "t"])
    add_row("val_resmarg", semi(v_rm, mw, ["i", "r", "t"]))
    v_rm_sys = mul(total(mul(net_stress, ps_rm, ["h", "t"]), ["i", "r", "t"]), ratio, ["i", "r", "t"])
    add_row("val_resmarg_sys", semi(v_rm_sys, mw, ["i", "r", "t"]))
    pq_rm = mul(p_rm, q_rm, ["r", "h", "t"])
    bench("val_resmarg", total(pq_rm, ["r", "t"]), total(pq_rm, ["t"]))
    wind = H.set_members("wind")
    pv_all = H.set_members("pv") | H.set_members("pvb")
    opres_inv = semi(opres, S.valinv, V4)
    v_or = mul(total(mul(mul(opres_inv.filter(~isin("i", wind | pv_all)), hrs, ["h"]), p_or, ["ortype", "r", "h", "t"]), ["i", "r", "t"]), ratio, ["i", "r", "t"])
    v_or_sys = mul(total(mul(mul(opres_inv.filter(~isin("i", wind | pv_all)), hrs, ["h"]), ps_or, ["ortype", "h", "t"]), ["i", "r", "t"]), ratio, ["i", "r", "t"])
    if H.swi("Sw_OpRes") and members(S.opres_h):
        raise NotImplementedError("valnew val_opres for wind and PV with active operating-reserve hours is not ported")
    add_row("val_opres", semi(v_or, mw, ["i", "r", "t"]))
    add_row("val_opres_sys", semi(v_or_sys, mw, ["i", "r", "t"]))
    pq_or = mul(p_or, q_or, ["ortype", "r", "h", "t"])
    bench("val_opres", total(pq_or, ["r", "t"]), total(pq_or, ["t"]))
    gen_inv = semi(gen, S.valinv, V4)
    rps_inv = (mul(gen_inv, hrs, ["h"]).join(S.rpscat, how="cross").join(rectech_r, on=["rpscat", "i", "r", "t"], how="semi")
               .join(val(mult_r, "m"), on=["rpscat", "i", "r"], how="left"))
    v_rps = mul(total(rps_inv.join(val(p_rps, "p"), on=["rpscat", "r", "t"], how="left")
                      .with_columns((pl.col("value") * pl.col("m").fill_null(0.0) * pl.col("p").fill_null(0.0)).alias("value")), ["i", "r", "t"]), ratio, ["i", "r", "t"])
    add_row("val_rps", semi(v_rps, mw, ["i", "r", "t"]))
    v_rps_sys = mul(total(rps_inv.join(val(ps_rps, "p"), on=["rpscat", "t"], how="left")
                          .with_columns((pl.col("value") * pl.col("m").fill_null(0.0) * pl.col("p").fill_null(0.0)).alias("value")), ["i", "r", "t"]), ratio, ["i", "r", "t"])
    add_row("val_rps_sys", semi(v_rps_sys, mw, ["i", "r", "t"]))
    pq_rps = mul(p_rps, q_rps, ["rpscat", "r", "t"])
    bench("val_rps", total(pq_rps, ["r", "t"]), total(pq_rps, ["t"]))
    R["valnew"] = nz(pl.concat(rows))


# ----------------------------------------------------------------------------- emissions
def emissions(H: Helpers, R: dict) -> None:
    S, C = H.S, H.C
    gen = semi(H.L("GEN", rep=True), S.valgen, V4)
    hrs = H.hours.rename({"hours": "value"})
    er = S.emit_rate.filter(isin("e", members(S.e)))
    e_gen = total(mul(mul(gen, hrs, ["h"]), er, V4).select(["etype", "e", "i", "r", "t", "value"]), ["etype", "e", "i", "r", "t"])
    produce = semi(H.L("PRODUCE", rep=True), S.valcap, V4).join(S.i_p, on=["i", "p"], how="semi")
    e_prod = total(mul(mul(produce, hrs, ["h"]), S.prod_emit_rate.filter(isin("e", members(S.e))), ["i", "t"]).select(["etype", "e", "i", "r", "t", "value"]), ["etype", "e", "i", "r", "t"])
    if H.swi("Sw_CCSFLEX_BYP") or H.swi("Sw_CCSFLEX_STO") or H.swi("Sw_CCSFLEX_DAC"):
        raise NotImplementedError("flexible CCS emissions are not ported")
    emit_r = total(add([e_gen, e_prod], ["etype", "e", "i", "r", "t"]), ["etype", "e", "r", "t"])
    co2e = total(mul(emit_r, S.gwp, ["e"]), ["etype", "r", "t"]).with_columns(pl.lit("co2e").alias("e"))
    emit_r = pl.concat([emit_r, co2e.select(["etype", "e", "r", "t", "value"])])
    R["emit_r"] = nz(emit_r)
    R["emit_nat"] = nz(total(emit_r, ["etype", "e", "t"]))
    e_irt = add([semi(e_gen, S.valgen_irt, ["i", "r", "t"]), e_prod], ["etype", "e", "i", "r", "t"])
    co2e_irt = total(mul(e_irt, S.gwp, ["e"]), ["etype", "i", "r", "t"]).with_columns(pl.lit("co2e").alias("e"))
    e_irt = pl.concat([e_irt, co2e_irt.select(["etype", "e", "i", "r", "t", "value"])])
    R["emit_irt"] = nz(e_irt)
    R["emit_nat_tech"] = nz(total(e_irt, ["etype", "e", "i", "t"]))
    R["emit_weighted"] = nz(total(mul(R["emit_nat"].filter(pl.col("t") == C.tlast), S.pvf_onm, ["t"]), ["etype", "e"]))
    R["emit_rate_regional"] = nz(C.co2_emit_rate_r)
    capr = S.capture_rate.filter(pl.col("e") == "co2").select(V4 + ["value"])
    cap_irt = total(mul(mul(gen, hrs, ["h"]), capr, V4), ["i", "r", "t"])
    smr_ccs = produce.filter(pl.col("i") == "smr_ccs")
    if smr_ccs.height:
        cap_irt = pl.concat([cap_irt.filter(pl.col("i") != "smr_ccs"),
                             scale(total(mul(smr_ccs, hrs, ["h"]), ["i", "r", "t"]), H.scalar("smr_capture_rate") * H.scalar("smr_co2_intensity"))])
    dac = H.set_members("dac")
    if dac:
        cap_irt = pl.concat([cap_irt.filter(~isin("i", dac)), total(mul(produce.filter(isin("i", dac)), hrs, ["h"]), ["i", "r", "t"])])
    R["emit_captured_irt"] = nz(cap_irt)
    R["emit_captured_nat"] = nz(total(cap_irt, ["i", "t"]))
    R["RE_gen_price_nat"] = nz(H.M("eq_national_gen").join(val(S.crf, "crf"), on="t", how="inner")
                               .with_columns((pl.col("value") * pl.col("crf") / H.cost_scale).alias("value")).select(["t", "value"]))
