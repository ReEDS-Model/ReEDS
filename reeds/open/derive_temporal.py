from __future__ import annotations

import math

import polars as pl

from .derive import Symbols, anti, fsum_by, gams_round, gams_round_float, isin, members, nonzero, one_col, semi
from .derive_capacity import V4, _assign, yr


def _rep_stress(I, key: str, dims: list[str], stress_year: str) -> pl.DataFrame:
    frames = [I.par(f"rep__{key}", dims)]
    skey = f"stress__{key}__{stress_year}"
    if skey in I:
        frames.append(I.par(skey, dims))
    return pl.concat(frames).unique(subset=dims, keep="last", maintain_order=True)


def tc_phaseout_rows(S: Symbols, year: str) -> tuple[pl.DataFrame | None, pl.DataFrame | None]:
    sw, csw = S.sw, S.csw
    skip = int(sw["Sw_SkipRAyear"]) if "Sw_SkipRAyear" in sw else int(csw["GSw_SkipRAyear"])
    if int(year) <= skip:
        return None, None
    tmodel_y = one_col([year], "t")
    loaded = semi(S._inputs.par(f"tc_phaseout_mult_t__{year}", ["i", "t"]), tmodel_y, ["t"])
    if int(sw["Sw_TCPhaseout"]) <= 0:
        return loaded, None
    fyv = S.firstyear_v.rename({"value": "fyv"})
    upd = (S.i.join(S.v, how="cross").join(tmodel_y, how="cross").join(fyv, on=["i", "v"], how="inner")
           .filter(pl.col("fyv") >= float(year))
           .join(nonzero(loaded).rename({"value": "new"}), on=["i", "t"], how="left")
           .with_columns(pl.col("new").fill_null(0.0).alias("value")).select(["i", "v", "t", "value"]))
    return loaded, upd


def tc_phaseout_mult_all_years(S: Symbols, years: list[str]) -> pl.DataFrame:
    tcm = S.i.join(S.v, how="cross").join(S.tmodel_new, how="cross").with_columns(pl.lit(1.0).alias("value"))
    for y in years:
        _, upd = tc_phaseout_rows(S, y)
        if upd is not None:
            tcm = _assign(tcm, upd, ["i", "v", "t"])
    return nonzero(tcm)


def temporal(S: Symbols, stress_year: str, state: dict[str, pl.DataFrame] | None = None) -> Symbols:
    I = S._inputs
    sw, sc, csw = S.sw, S.sc, S.csw
    year = str(S.year)
    t_all = S.t
    h = S.h
    valcap_y = S.valcap.filter(pl.col("t") == year)
    initv, newv = members(S.initv), members(S.newv)

    # ------------------------------------------------------------- availability
    of = semi(_rep_stress(I, "outage_forced_h", ["i", "r", "h"], stress_year), h, ["h"])
    geo_of = of.filter(pl.col("i") == "geothermal").select(["r", "h", "value"])
    of = _assign(of, S.geo.join(geo_of, how="cross").select(["i", "r", "h", "value"]), ["i", "r", "h"],
                 domain=S.geo.join(S.r, how="cross").join(h, how="cross").select(["i", "r", "h"]))
    os_ = semi(_rep_stress(I, "outage_scheduled_h", ["i", "h"], stress_year), h, ["h"])
    geo_os = os_.filter(pl.col("i") == "geothermal").select(["h", "value"])
    os_ = _assign(os_, S.geo.join(geo_os, how="cross").select(["i", "h", "value"]), ["i", "h"],
                  domain=S.geo.join(h, how="cross").select(["i", "h"]))
    avail = (S.valcap_ir.join(h, how="cross")
             .join(of.rename({"value": "of"}), on=["i", "r", "h"], how="left")
             .join(os_.rename({"value": "os"}), on=["i", "h"], how="left")
             .with_columns(((1.0 - pl.col("of").fill_null(0.0)) * (1.0 - pl.col("os").fill_null(0.0))).alias("value"))
             .select(["i", "r", "h", "value"]))
    if members(S.dr_shed):
        raise NotImplementedError("dr_shed availability is not ported")
    if int(sw["Sw_Upgrades"]):
        up_i = semi(S.upgrade, S.valcap_i, ["i"])
        up_rows = (up_i.join(S.upgrade_to, on="i", how="inner")
                   .join(avail.rename({"i": "ii"}), on="ii", how="inner")
                   .group_by(["i", "r", "h"]).agg(pl.col("value").sum()))
        avail = _assign(avail, up_rows, ["i", "r", "h"], domain=up_i.join(S.r, how="cross").join(h, how="cross").select(["i", "r", "h"]))
    if int(sw["Sw_PRM_StressOutages"]) == 0:
        raise NotImplementedError("Sw_PRM_StressOutages=0 is not ported")
    avail_raw = avail
    of_report, os_report = of, os_
    if int(sw["Sw_Upgrades"]):
        up_all = S.upgrade.join(S.upgrade_to, on="i", how="inner")
        of_up = up_all.join(of.rename({"i": "ii"}), on="ii", how="inner").group_by(["i", "r", "h"]).agg(pl.col("value").sum())
        of_report = _assign(of, of_up, ["i", "r", "h"], domain=S.upgrade.join(S.r, how="cross").join(h, how="cross").select(["i", "r", "h"]))
        os_up = up_all.join(os_.rename({"i": "ii"}), on="ii", how="inner").group_by(["i", "h"]).agg(pl.col("value").sum())
        os_report = _assign(os_, os_up, ["i", "h"], domain=S.upgrade.join(h, how="cross").select(["i", "h"]))
    S["_outage_forced_h"] = of_report
    S["_outage_scheduled_h"] = os_report
    S["avail"] = nonzero(avail.with_columns(gams_round(pl.col("value"), 3).alias("value")))
    hours = S.hours_raw.rename({"value": "hours"})
    geo_iv = semi(S.valcap_iv.filter(isin("i", members(S.geo)) & isin("v", initv)), S.valcap_iv, ["i", "v"])
    num = fsum_by(avail_raw.join(hours, on="h", how="inner").with_columns((pl.col("value") * pl.col("hours")).alias("value")), ["i"])
    den = fsum_by(S.valcap_ir.join(h, how="cross").join(hours, on="h", how="inner").select(["i", pl.col("hours").alias("value")]), ["i"])
    dgv = (geo_iv.join(num.rename({"value": "num"}), on="i", how="inner").join(den.rename({"value": "den"}), on="i", how="inner")
           .with_columns((sc["geothermal_availability"] / (pl.col("num") / pl.col("den"))).alias("value")).select(["i", "v", "value"]))
    S["derate_geo_vintage"] = _assign(S.derate_geo_vintage, dgv, ["i", "v"])

    # ------------------------------------------------------------- seasonal capacity delta
    q = S.quarter_cap_frac_delta
    scfd = (S.szn_quarter_weights.rename({"value": "w"}).join(q.rename({"value": "d"}), on="quarter", how="inner")
            .with_columns((pl.col("w") * pl.col("d")).alias("value")))
    scfd = fsum_by(scfd, ["i", "v", "r", "szn", "t"])
    scfd = semi(scfd, S.valcap, V4)
    S["seas_cap_frac_delta"] = nonzero(scfd.with_columns(gams_round(pl.col("value"), 3).alias("value")))

    # ------------------------------------------------------------- capacity factors
    cf_in = semi(_rep_stress(I, "cf_vre", ["i", "c", "r", "h"], stress_year), h, ["h"])
    S["cf_in"] = cf_in
    cf_tech = members(S.cf_tech)

    def _m_cf(yy: str):
        valcap_yy = S.valcap.filter(pl.col("t") == yy)
        tmodel_yy = one_col([yy], "t")
        cf_rsc = (valcap_yy.filter(isin("i", cf_tech)).join(cf_in, on=["i", "r"], how="inner")
                  .select(["i", "c", "v", "r", "h", "t", "value"]))
        cf_hyd = _rep_stress(I, "cf_hyd", ["i", "szn", "r", "allt"], stress_year).rename({"allt": "t"})
        hyd_up = S.upgrade.filter(isin("i", members(S.hydro) | members(S.psh)))
        if hyd_up.height:
            dom = hyd_up.join(S.szn, how="cross").join(S.r, how="cross").join(t_all, how="cross").select(["i", "szn", "r", "t"])
            rows = (hyd_up.join(S.upgrade_from, on="i", how="inner").join(cf_hyd.rename({"i": "ii"}), on=["ii", "szn", "r", "t"], how="inner")
                    .group_by(["i", "szn", "r", "t"]).agg(pl.col("value").sum()))
            cf_hyd = _assign(cf_hyd, rows, ["i", "szn", "r", "t"], domain=dom)
        hyd = (valcap_yy.filter(isin("i", members(S.hydro))).join(S.i_c, on="i", how="inner")
               .join(S.h_szn, how="cross").join(cf_hyd, on=["i", "szn", "r", "t"], how="left")
               .with_columns(pl.col("value").fill_null(0.0)))
        hyd = fsum_by(hyd, ["i", "c", "v", "r", "h", "t"])
        cf_rsc = _assign(cf_rsc, hyd, ["i", "c", "v", "r", "h", "t"],
                         domain=valcap_yy.filter(isin("i", members(S.hydro))).join(S.i_c, on="i", how="inner").join(h, how="cross").select(["i", "c", "v", "r", "h", "t"]))
        exog_ivr = S.capacity_exog.select(["i", "v", "r"]).unique().filter(isin("i", members(S.rsc_i)))
        init1 = cf_rsc.filter(pl.col("v") == "init-1").select(["i", "c", "r", "h", "t", "value"])
        copy = exog_ivr.join(init1, on=["i", "r"], how="inner").select(["i", "c", "v", "r", "h", "t", "value"])
        dom = exog_ivr.join(S.i_c, on="i", how="inner").join(h, how="cross").join(tmodel_yy, how="cross").select(["i", "c", "v", "r", "h", "t"])
        cf_rsc = _assign(cf_rsc, copy, ["i", "c", "v", "r", "h", "t"], domain=dom)
        cf_rsc = nonzero(cf_rsc)
        if yy == year:
            S["cf_hyd"] = cf_hyd
        adj = S.cf_adj_t.filter(pl.col("t") == yy).rename({"value": "adj"})
        pvb_or_hydro = members(S.pvb) | members(S.hydro)
        m_cf = (semi(cf_rsc, valcap_yy, V4).filter(isin("i", cf_tech))
                .join(adj, on=["i", "c", "v", "t"], how="inner")
                .join(avail_raw.rename({"value": "av"}), on=["i", "r", "h"], how="left")
                .with_columns(pl.when(isin("i", pvb_or_hydro)).then(1.0).otherwise(pl.col("av").fill_null(0.0)).alias("av"))
                .with_columns((pl.col("value") * pl.col("adj") * pl.col("av")).alias("value"))
                .select(["i", "c", "v", "r", "h", "t", "value"]))
        ivt_cum = (S.ivt.rename({"t": "tt"}).join(tmodel_yy, how="cross").filter(yr("tt") <= yr("t")).select(["i", "v", "t"]).unique())
        m_cf = pl.concat([m_cf.filter(~isin("v", newv)), semi(m_cf.filter(isin("v", newv)), ivt_cum, ["i", "v", "t"])])
        m_cf = m_cf.filter(pl.col("value") >= 0.01)
        return cf_rsc, nonzero(m_cf.with_columns(gams_round(pl.col("value"), 3).alias("value")))

    cf_parts, mcf_parts = [], []
    for yy in sorted(S.valcap["t"].unique().to_list(), key=int):
        cf_yy, mcf_yy = _m_cf(yy)
        cf_parts.append(cf_yy)
        mcf_parts.append(mcf_yy)
    S["cf_rsc"] = pl.concat(cf_parts)
    S["m_cf"] = pl.concat(mcf_parts)
    S["spur_cf"] = fsum_by(S.m_cf.filter((pl.col("t") == year) & isin("i", members(S.spur_techs))), ["i", "v", "r", "h", "t"])
    later = [y for y in S.years if y > int(year)]
    S["m_cf_next"] = S.m_cf.filter(pl.col("t") == (str(later[0]) if later else year))
    has_cf = S.m_cf.select(V4).unique()
    rounded = S.m_capacity_exog.with_columns(pl.when(pl.col("i") != "smr").then(gams_round(pl.col("value"), 3)).otherwise(pl.col("value")).alias("value"))
    S["m_capacity_exog0"] = nonzero(rounded)
    drop = anti(rounded.filter(isin("v", initv) & isin("i", cf_tech)), has_cf, V4)
    S["m_capacity_exog"] = nonzero(anti(rounded, drop, V4))
    S["m_capacity_exog_energy"] = nonzero(S.m_capacity_exog_energy.with_columns(gams_round(pl.col("value"), 3).alias("value")))
    chsa = semi(_rep_stress(I, "cap_hyd_szn_adj", ["i", "szn", "r"], stress_year), S.szn, ["szn"])
    S["cap_hyd_szn_adj"] = nonzero(chsa.with_columns(gams_round(pl.col("value"), 3).alias("value")))

    # ------------------------------------------------------------- load
    load = semi(_rep_stress(I, "load_allyear", ["r", "h", "allt"], stress_year).rename({"allt": "t"}), t_all, ["t"])
    load = semi(load, h, ["h"])
    prm = I.par(f"stress__prm__{stress_year}", ["r"]).rename({"value": "prm"})
    S["prm"] = prm.with_columns(pl.lit(year).alias("t")).select(["r", "t", pl.col("prm").alias("value")])
    prm_t = S.prm.rename({"value": "prm"})
    if state is not None:
        prm_t = pl.concat([state["state_prm"].rename({"tt": "t", "value": "prm"}).filter(pl.col("t") != year), prm_t])
    load = (load.join(prm_t, on=["r", "t"], how="left")
            .with_columns(pl.when(isin("h", members(S.h_stress))).then(pl.col("value") * (1.0 + pl.col("prm").fill_null(0.0))).otherwise(pl.col("value")).alias("value"))
            .select(["r", "h", "t", "value"]))
    canmex = semi(_rep_stress(I, "canmexload", ["r", "h"], stress_year), h, ["h"])
    if canmex.height:
        mex = I.par("mex_growth_rate", ["allt"]).rename({"allt": "t", "value": "g"})
        load_t = load.select("t").unique()
        rows = (canmex.join(load_t, how="cross").join(mex, on="t", how="left")
                .with_columns((pl.col("g").fill_null(0.0) * pl.col("value")).alias("value")).select(["r", "h", "t", "value"]))
        load = _assign(load, rows, ["r", "h", "t"], domain=rows.select(["r", "h", "t"]))
    can_growth = I.par("cangrowth", ["st", "allt"]).rename({"allt": "t"})
    r_growth = S.r_st.join(can_growth, on="st", how="inner").group_by(["r", "t"]).agg(pl.col("value").sum().alias("g")).filter(pl.col("g") != 0.0)
    if r_growth.height:
        dom = semi(r_growth, load.select("t").unique(), ["t"]).join(h, how="cross")
        rows = (dom.join(canmex.rename({"value": "cm"}), on=["r", "h"], how="left")
                .with_columns((pl.col("cm").fill_null(0.0) * pl.col("g")).alias("value")).select(["r", "h", "t", "value"]))
        load = _assign(load, rows, ["r", "h", "t"], domain=dom.select(["r", "h", "t"]))
    if int(sw["Sw_Canada"]) == 1:
        imp = I.par("can_imports", ["r", "allt"]).rename({"allt": "t"})
        exp = I.par("can_exports", ["r", "allt"]).rename({"allt": "t"})
        szn_frac = semi(_rep_stress(I, "can_imports_szn_frac", ["szn"], stress_year), S.szn, ["szn"])
        h_frac = semi(_rep_stress(I, "can_exports_h_frac", ["h"], stress_year), h, ["h"])
        can_imports_szn = (semi(imp, t_all, ["t"]).join(szn_frac.rename({"value": "frac"}), how="cross")
                           .with_columns((pl.col("value") * pl.col("frac")).alias("value")).select(["r", "szn", "t", "value"]))
        can_exports_h = (semi(exp, t_all, ["t"]).join(h_frac.rename({"value": "frac"}), how="cross")
                         .join(S.hours_raw.rename({"value": "hours"}), on="h", how="inner")
                         .with_columns((pl.col("value") * pl.col("frac") / pl.col("hours")).alias("value")).select(["r", "h", "t", "value"]))
        S["can_imports_szn"] = nonzero(can_imports_szn).with_columns(gams_round(pl.col("value"), 3).alias("value"))
        S["can_exports_h"] = nonzero(can_exports_h).with_columns(gams_round(pl.col("value"), 3).alias("value"))
    else:
        S["can_imports_szn"] = pl.DataFrame({c: pl.Series([], dtype=pl.Utf8) for c in ["r", "szn", "t"]} | {"value": pl.Series([], dtype=pl.Float64)})
        S["can_exports_h"] = pl.DataFrame({c: pl.Series([], dtype=pl.Utf8) for c in ["r", "h", "t"]} | {"value": pl.Series([], dtype=pl.Float64)})
    if int(sw["Sw_EFS_Flex"]):
        raise NotImplementedError("flexible load is not ported")
    S["load_exog"] = nonzero(load.with_columns(gams_round(pl.col("value"), 3).alias("value")))
    S["load_exog_static"] = S.load_exog
    gpa = semi(I.par("rep__daily_gasprice_multipliers_r", ["r", "h"]), h, ["h"])
    method = int(sw["Sw_GasPriceAdjMethod"])
    if method == 0:
        gpa = S.r.join(h, how="cross").with_columns(pl.lit(1.0).alias("value"))
    elif method == 1:
        raise NotImplementedError("Sw_GasPriceAdjMethod=1 is not ported")
    S["gasprice_adj_r"] = nonzero(gpa.with_columns(gams_round(pl.col("value"), 3).alias("value")))

    # ------------------------------------------------------------- financial multipliers
    loaded, upd = tc_phaseout_rows(S, year)
    tcm_t = S.i.join(S.tmodel_new, how="cross").with_columns(pl.lit(1.0).alias("value"))
    if loaded is not None:
        tcm_t = _assign(tcm_t, loaded, ["i", "t"], domain=S.i.join(S.tmodel, how="cross").select(["i", "t"]))
    S["tc_phaseout_mult_t"] = nonzero(tcm_t)
    tcm = S.i.join(S.v, how="cross").join(S.tmodel_new, how="cross").with_columns(pl.lit(1.0).alias("value"))
    if upd is not None:
        tcm = _assign(tcm, upd, ["i", "v", "t"])
    S["tc_phaseout_mult"] = nonzero(tcm)
    ccmult = I.par("ccmult", ["i", "t"]).rename({"value": "ccmult"})
    tax = I.par("tax_rate", ["t"]).rename({"value": "tax"})
    itcm = I.par("itc_frac_monetized", ["i", "t"]).rename({"value": "itcm"})
    itcb = I.par("itc_energy_comm_bonus", ["i", "r"]).rename({"value": "itcb"})
    pvd = I.par("pv_frac_of_depreciation", ["i", "t"]).rename({"value": "pvd"})
    dadj = I.par("degradation_adj", ["i", "t"]).rename({"value": "dadj"})
    frm = I.par("financing_risk_mult", ["i", "t"]).rename({"value": "frm"})
    rcd = I.par("reg_cap_cost_diff", ["i", "r"]).rename({"value": "rcd"})
    epa = I.par("eval_period_adj_mult", ["i", "t"]).rename({"value": "epa"})
    tcmt = S.tc_phaseout_mult_t.rename({"value": "tcm"})
    dom = ccmult.select(["i", "t"]).join(S.r, how="cross")
    f = (dom.join(ccmult, on=["i", "t"], how="left").join(tax, on="t", how="left").join(itcm, on=["i", "t"], how="left")
         .join(itcb, on=["i", "r"], how="left").join(pvd, on=["i", "t"], how="left").join(dadj, on=["i", "t"], how="left")
         .join(frm, on=["i", "t"], how="left").join(rcd, on=["i", "r"], how="left").join(epa, on=["i", "t"], how="left")
         .join(tcmt, on=["i", "t"], how="left"))
    f = f.with_columns([pl.col(c).fill_null(0.0) for c in ["ccmult", "tax", "itcm", "itcb", "pvd", "dadj", "frm", "rcd", "epa", "tcm"]])
    f = f.with_columns((pl.col("ccmult") / (1.0 - pl.col("tax"))
                        * (1.0 - pl.col("tax") * (1.0 - (pl.col("itcm") * pl.col("itcb") * pl.col("tcm") / 2.0)) * pl.col("pvd")
                           - pl.col("itcm") * pl.col("tcm"))
                        * pl.col("dadj") * pl.col("frm") * (1.0 + pl.col("rcd")) * pl.col("epa")).alias("value"))
    ccfm = f.select(["i", "r", "t", "value"])
    ccfm = nonzero(ccfm)
    noitc = nonzero(f.with_columns((pl.col("ccmult") / (1.0 - pl.col("tax")) * (1.0 - pl.col("tax") * pl.col("pvd"))
                                    * pl.col("dadj") * pl.col("frm") * (1.0 + pl.col("rcd")) * pl.col("epa")).alias("value"))
                    .select(["i", "r", "t", "value"]))
    nocred = nonzero(f.with_columns((pl.col("ccmult") * (1.0 + pl.col("rcd"))).alias("value")).select(["i", "r", "t", "value"]))
    if int(sw["Sw_Upgrades"]):
        up_dom = S.upgrade.join(S.r, how="cross").join(t_all, how="cross").select(["i", "r", "t"])
        up_rows = (S.upgrade.join(S.upgrade_to, on="i", how="inner")
                   .join(ccfm.rename({"i": "ii"}), on="ii", how="inner")
                   .group_by(["i", "r", "t"]).agg(pl.col("value").sum()))
        ccfm = _assign(ccfm, up_rows, ["i", "r", "t"], domain=up_dom)
        up_rows_noitc = (S.upgrade.join(S.upgrade_to, on="i", how="inner")
                         .join(noitc.rename({"i": "ii"}), on="ii", how="inner")
                         .group_by(["i", "r", "t"]).agg(pl.col("value").sum()))
        noitc = _assign(noitc, up_rows_noitc, ["i", "r", "t"], domain=up_dom)
    hydromult = S.hydrocapmult.rename({"value": "hm"})
    rsc_fin = S.valcap_irt.filter(isin("i", members(S.rsc_i))).with_columns(pl.lit(1.0).alias("value"))
    hydro_src = ccfm.filter(pl.col("i") == "hydro").select(["r", "t", pl.col("value").alias("base")])
    hy = (S.hydro.join(hydro_src, how="cross").join(hydromult, on=["i", "t"], how="left")
          .with_columns((pl.col("base") * pl.col("hm").fill_null(0.0)).alias("value")).select(["i", "r", "t", "value"]))
    rsc_fin = _assign(rsc_fin, hy, ["i", "r", "t"], domain=S.hydro.join(S.r, how="cross").join(t_all, how="cross").select(["i", "r", "t"]))
    ps = (ccfm.filter(isin("i", members(S.psh))).join(hydromult, on=["i", "t"], how="left")
          .with_columns((pl.col("value") * pl.col("hm").fill_null(0.0)).alias("value")).select(["i", "r", "t", "value"]))
    rsc_fin = _assign(rsc_fin, ps, ["i", "r", "t"], domain=S.psh.join(S.r, how="cross").join(t_all, how="cross").select(["i", "r", "t"]))
    if members(S.dr_shed):
        raise NotImplementedError("dr_shed financial multipliers are not ported")
    ofs = (ccfm.filter(isin("i", members(S.ofswind))).join(S.ofswind_rsc_mult.rename({"value": "om"}), on=["i", "t"], how="left")
           .with_columns((pl.col("value") * pl.col("om").fill_null(0.0)).alias("value")).select(["i", "r", "t", "value"]))
    rsc_fin = _assign(rsc_fin, ofs, ["i", "r", "t"], domain=S.ofswind.join(S.r, how="cross").join(t_all, how="cross").select(["i", "r", "t"]))
    S["rsc_fin_mult"] = nonzero(rsc_fin.with_columns(gams_round(pl.col("value"), 3).alias("value")))
    rsc_noitc = S.valcap_irt.filter(isin("i", members(S.rsc_i))).with_columns(pl.lit(1.0).alias("value"))
    hydro_src_noitc = noitc.filter(pl.col("i") == "hydro").select(["r", "t", pl.col("value").alias("base")])
    hy_noitc = (S.hydro.join(hydro_src_noitc, how="cross").join(hydromult, on=["i", "t"], how="left")
                .with_columns((pl.col("base") * pl.col("hm").fill_null(0.0)).alias("value")).select(["i", "r", "t", "value"]))
    rsc_noitc = _assign(rsc_noitc, hy_noitc, ["i", "r", "t"], domain=S.hydro.join(S.r, how="cross").join(t_all, how="cross").select(["i", "r", "t"]))
    ps_noitc = (noitc.filter(isin("i", members(S.psh))).join(hydromult, on=["i", "t"], how="left")
                .with_columns((pl.col("value") * pl.col("hm").fill_null(0.0)).alias("value")).select(["i", "r", "t", "value"]))
    rsc_noitc = _assign(rsc_noitc, ps_noitc, ["i", "r", "t"], domain=S.psh.join(S.r, how="cross").join(t_all, how="cross").select(["i", "r", "t"]))
    ofs_noitc = noitc.filter(isin("i", members(S.ofswind))).select(["i", "r", "t", "value"])
    rsc_noitc = _assign(rsc_noitc, ofs_noitc, ["i", "r", "t"], domain=S.ofswind.join(S.r, how="cross").join(t_all, how="cross").select(["i", "r", "t"]))
    S["rsc_fin_mult_noITC"] = nonzero(rsc_noitc)
    keep = S.valinv_irt.select(["i", "r", "t"]).unique()
    keep_all = pl.concat([keep, S.upgrade.join(S.r, how="cross").join(t_all, how="cross").select(["i", "r", "t"])])
    ccfm = semi(ccfm, keep_all, ["i", "r", "t"])
    ccfm = ccfm.with_columns(gams_round(pl.col("value"), 3).alias("value"))
    S["cost_cap_fin_mult_noITC"] = nonzero(semi(noitc, keep_all, ["i", "r", "t"]).with_columns(gams_round(pl.col("value"), 3).alias("value")))
    S["cost_cap_fin_mult_no_credits"] = nonzero(semi(nocred, keep_all, ["i", "r", "t"]).with_columns(gams_round(pl.col("value"), 3).alias("value")))
    S["cost_cap_fin_mult_out"] = nonzero(ccfm)
    nglife = I.par("ng_crf_penalty", ["allt"]).rename({"allt": "t", "value": "adj"})
    gas_irt = S.valcap_irt.filter(isin("i", members(S.gas)))
    pen = (gas_irt.select(["i", "t"]).unique().join(nglife, on="t", how="left")
           .with_columns(((pl.col("adj").fill_null(0.0) - 1.0) * 0.2 + 1.0).alias("value"))
           .with_columns(pl.when(isin("i", members(S.ccs))).then(1.0).otherwise(pl.col("value")).alias("value")).select(["i", "t", "value"]))
    S["ng_crf_penalty_nat"] = pen
    st_pen = I.par("ng_crf_penalty_st", ["allt", "st"]).rename({"allt": "t"})
    r_pen = S.r_st.join(st_pen, on="st", how="inner").group_by(["r", "t"]).agg(pl.col("value").sum().alias("stpen"))
    state_on = int(sw["Sw_StateRPS"]) != 0
    gpen = (semi(ccfm, gas_irt, ["i", "r", "t"]).join(pen.rename({"value": "pen"}), on=["i", "t"], how="left")
            .join(r_pen, on=["r", "t"], how="left")
            .with_columns(pl.when(pl.lit(state_on) & ~isin("i", members(S.ccs)) & (yr("t") >= sc["firstyear_RPS"]))
                          .then(pl.col("stpen").fill_null(0.0)).otherwise(0.0).alias("stpen"))
            .with_columns((pl.col("value") * pl.max_horizontal(pl.col("stpen"), pl.col("pen").fill_null(0.0))).alias("value")).select(["i", "r", "t", "value"]))
    ccfm = _assign(ccfm, gpen, ["i", "r", "t"], domain=gas_irt)
    S["cost_cap_fin_mult"] = nonzero(ccfm)
    S["pvf_capital"] = t_all.with_columns(pl.lit(1.0).alias("value"))
    S["tlast"] = one_col([str(max(S.years))], "t")
    crf = I.par("crf", ["t"])
    S["pvf_onm"] = (semi(crf, S.tmodel_new, ["t"]).with_columns(gams_round(1.0 / pl.col("value"), 6).alias("value")))
    pvf_onm_int = I.par("pvf_onm", ["t"])
    pvf_capital_int = I.par("pvf_capital", ["t"]).rename({"value": "pvc"})
    S["pvf_onm_undisc"] = (semi(pvf_onm_int, t_all, ["t"]).join(pvf_capital_int, on="t", how="inner").filter(pl.col("pvc") != 0.0)
                           .with_columns((pl.col("value") / pl.col("pvc")).alias("value")).select(["t", "value"]))
    return S


def slice_coefficients(S: Symbols) -> Symbols:
    sw, sc = S.sw, S.sc
    year = str(S.year)
    valgen_y = S.valgen.filter(pl.col("t") == year)
    valcap_y = S.valcap.filter(pl.col("t") == year)
    valinv_y = S.valinv.filter(pl.col("t") == year)
    h = S.h
    hours = S.hours.rename({"value": "hours"})
    h_stress = members(S.h_stress)

    # kappa
    dispatch = members(S.dispatchtech)
    hydro_d = members(S.hydro_d)
    seas = (S.h_szn.join(S.seas_cap_frac_delta.filter(pl.col("t") == year).rename({"value": "d"}), on="szn", how="inner")
            .select(["i", "v", "r", "h", "d"]))
    base = valgen_y.join(h, how="cross").join(S.avail.rename({"value": "avail"}), on=["i", "r", "h"], how="left").with_columns(pl.col("avail").fill_null(0.0))
    base = base.join(seas, on=["i", "v", "r", "h"], how="left").with_columns(pl.col("d").fill_null(0.0))
    base = base.join(S.derate_geo_vintage.rename({"value": "dgv"}), on=["i", "v"], how="left").with_columns(pl.col("dgv").fill_null(0.0))
    chsa = S.h_szn.join(S.cap_hyd_szn_adj.rename({"value": "hadj"}), on="szn", how="inner").select(["i", "r", "h", "hadj"])
    base = base.join(chsa, on=["i", "r", "h"], how="left").with_columns(pl.col("hadj").fill_null(0.0))
    hcd = S.hydro_capcredit_delta.filter(pl.col("t") == year).rename({"value": "hcd"}).select(["i", "hcd"])
    base = base.join(hcd, on="i", how="left").with_columns(pl.col("hcd").fill_null(0.0))
    mcf = fsum_by(S.m_cf.filter(pl.col("t") == year), ["i", "v", "r", "h", "t"]).rename({"value": "mcf"})
    base = base.join(mcf, on=["i", "v", "r", "h", "t"], how="left").with_columns(pl.col("mcf").fill_null(0.0))
    term1 = pl.when(isin("i", dispatch - hydro_d)).then(pl.col("avail") * pl.col("dgv") * (1.0 + pl.col("d"))).otherwise(0.0)
    term2 = pl.when(isin("i", hydro_d)).then(pl.col("avail") * pl.col("hadj") * (1.0 + pl.when(isin("h", h_stress)).then(pl.col("hcd")).otherwise(0.0))).otherwise(0.0)
    term3 = pl.when(~isin("i", dispatch)).then(pl.col("mcf")).otherwise(0.0)
    S["slice_cap_coef"] = nonzero(base.with_columns((term1 + term2 + term3).alias("value")).select(["i", "v", "r", "h", "t", "value"]))
    bcr = S.bcr.rename({"value": "bcr"})
    stor = (semi(valgen_y.filter(isin("i", members(S.storage_standalone))), valcap_y, V4).join(h, how="cross")
            .join(bcr, on="i", how="left").join(S.avail.rename({"value": "avail"}), on=["i", "r", "h"], how="left")
            .join(seas, on=["i", "v", "r", "h"], how="left")
            .with_columns((pl.col("bcr").fill_null(0.0) * pl.col("avail").fill_null(0.0) * (1.0 + pl.col("d").fill_null(0.0))).alias("value"))
            .select(["i", "v", "r", "h", "t", "value"]))
    S["slice_stor_cap_coef"] = nonzero(stor)
    mult = (pl.when(isin("i", members(S.csp_storage))).then(1.0).otherwise(0.0)
            + pl.when(isin("i", members(S.psh))).then(1.0).otherwise(0.0)
            + pl.when(isin("i", members(S.pvb))).then(pl.col("bcr").fill_null(0.0)).otherwise(0.0))
    S["slice_dur_coef"] = nonzero(S.storage_duration_m.join(bcr, on="i", how="left").with_columns((pl.col("value") * mult).alias("value")).select(["i", "v", "r", "value"]))
    # prescribed retirements of new vintages
    years = {str(y) for y in S.years}

    def prescr(ret: pl.DataFrame) -> pl.DataFrame:
        cond = S.inv_cond.rename({"t": "tt", "tt": "ttt"}).filter(isin("tt", years) & isin("ttt", years))
        cond = semi(cond, valcap_y.select(["i", "v", "r"]).unique(), ["i", "v", "r"])
        cond = semi(cond, S.valcap.rename({"t": "ttt"}), ["i", "v", "r", "ttt"])
        cond = cond.filter((yr("tt") >= yr("ttt")) & (yr("tt") <= int(year)))
        dn = S.degrade_new.rename({"t": "ttt", "tt": "tt", "value": "dn"})
        j = (cond.join(dn, on=["i", "ttt", "tt"], how="inner")
             .join(ret.rename({"t": "tt", "tt": "ttt", "value": "ret"}), on=["i", "v", "r", "tt", "ttt"], how="inner")
             .with_columns((pl.col("dn") * pl.col("ret")).alias("value"), pl.lit(year).alias("t")))
        return nonzero(fsum_by(j, V4))

    S["slice_prescr_ret"] = prescr(S.prescribed_retirements)
    S["slice_prescr_ret_energy"] = prescr(S.prescribed_retirements_energy)
    # gross supply-curve capacity
    cap = S.m_rsc_dat.filter(pl.col("sc_cat") == "cap").select(["r", "i", "rscbin", "value"])
    cer = S.capacity_exog_rsc.filter(pl.col("t") == str(S.years[0]))
    exog = (S.rsc_agg.join(cer.rename({"i": "ii"}), on="ii", how="inner").filter(isin("i", members(S.exog_rsc))))
    exog = fsum_by(exog, ["r", "i", "rscbin"]).rename({"value": "exog"})
    rcs = S.rsc_capacity_scalar.filter(pl.col("t") == year).rename({"value": "scal"}).select(["i", "r", "scal"])
    rcs_i = members(S.rsc_capacity_scalar_i)
    hau = S.hyd_add_upg_cap.filter(pl.col("t") == year).rename({"value": "hau"}).select(["r", "i", "rscbin", "hau"])
    dom = pl.concat([cap.select(["r", "i", "rscbin"]), hau.select(["r", "i", "rscbin"])]).unique()
    g = (dom.join(cap, on=["r", "i", "rscbin"], how="left").with_columns(pl.col("value").fill_null(0.0))
         .join(exog, on=["r", "i", "rscbin"], how="left").join(rcs, on=["i", "r"], how="left").join(hau, on=["r", "i", "rscbin"], how="left")
         .with_columns(((pl.col("value") - pl.col("exog").fill_null(0.0))
                        * (pl.when(isin("i", rcs_i)).then(pl.col("scal").fill_null(0.0)).otherwise(1.0))
                        + (pl.col("hau").fill_null(0.0) if int(S.csw["GSw_HydroCapEnerUpgradeType"]) == 1 else 0.0)).alias("value"),
                       pl.lit(year).alias("t")))
    S["slice_rsc_cap"] = nonzero(g.select(["r", "i", "rscbin", "t", "value"]))
    S["slice_rsc_cost"] = S.m_rsc_dat.filter(pl.col("sc_cat") == "cost").select(["r", "i", "rscbin", "value"])
    # objective coefficients
    ccfm = S.cost_cap_fin_mult.filter(pl.col("t") == year).rename({"value": "fin"})
    cc = S.cost_cap.filter(pl.col("t") == year).rename({"value": "cc"})
    S["slice_objinv_INV"] = nonzero(valinv_y.join(ccfm, on=["i", "r", "t"], how="inner").join(cc, on=["i", "t"], how="inner")
                                    .with_columns((pl.col("fin") * pl.col("cc")).alias("value")).select(V4 + ["value"]))
    cce = S.cost_cap_energy.filter(pl.col("t") == year).rename({"value": "cc"})
    S["slice_objinv_INV_ENERGY"] = nonzero(valinv_y.filter(isin("i", members(S.battery))).join(ccfm, on=["i", "r", "t"], how="inner")
                                           .join(cce, on=["i", "t"], how="inner").with_columns((pl.col("fin") * pl.col("cc")).alias("value")).select(V4 + ["value"]))
    rfm = S.rsc_fin_mult.filter(pl.col("t") == year).rename({"value": "rfm"})
    numeraire = (valinv_y.filter(isin("i", members(S.rsc_i)) & ~isin("i", members(S.spur_techs)))
                 .join(S.m_rscfeas, on=["r", "i"], how="inner")
                 .join(S.slice_rsc_cost.rename({"value": "cost"}), on=["r", "i", "rscbin"], how="inner")
                 .join(rfm, on=["i", "r", "t"], how="inner")
                 .with_columns((pl.col("cost") * pl.col("rfm")).alias("value")))
    S["slice_objinv_INV_RSC"] = nonzero(fsum_by(numeraire.join(S.rsc_agg, on="i", how="inner").drop("i").rename({"ii": "i"}),
                                                ["i", "v", "r", "rscbin", "t"]))
    vom = S.cost_vom.filter(pl.col("t") == year).rename({"value": "vom"})
    hr = S.heat_rate.filter(pl.col("t") == year).rename({"value": "hr"})
    fp = S.fuel_price.filter(pl.col("t") == year).rename({"value": "fp"})
    coal_fp = fp.filter(pl.col("i") == "coal-new").select(["r", pl.col("fp").alias("coalfp")])
    gpa = S.gasprice_adj_r.rename({"value": "gpa"})
    capr = S.capture_rate.filter((pl.col("e") == "co2") & (pl.col("t") == year)).rename({"value": "capr"}).select(V4 + ["capr"])
    inc = S.co2_captured_incentive.filter(pl.col("t") == year).rename({"value": "inc"})
    crf = S._inputs.par("crf", ["t"]).rename({"value": "crf"})
    S["crf_co2_incentive"] = S._inputs.par("crf_co2_incentive", ["t"])
    crf_inc = S.crf_co2_incentive.rename({"value": "crfi"})
    ptc = S.ptc_value_scaled.filter(pl.col("t") == year).rename({"value": "ptc"})
    tcm = S.tc_phaseout_mult.filter(pl.col("t") == year).rename({"value": "tcm"})
    gas, bio, cofire, h2_gen = members(S.gas), members(S.bio), members(S.cofire), members(S.h2_gen)
    hybrid_non_csp = members(S.storage_hybrid) - members(S.csp)
    gasmult = S.gasmult_r.filter(pl.col("t") == year).rename({"value": "gm"})
    g = (valgen_y.join(h, how="cross").join(hours, on="h", how="inner")
         .join(vom, on=V4, how="left").join(hr, on=V4, how="left").join(fp, on=["i", "r", "t"], how="left")
         .join(coal_fp, on="r", how="left").join(gpa, on=["r", "h"], how="left").join(capr, on=V4, how="left")
         .join(inc, on=V4, how="left").join(crf, on="t", how="left").join(crf_inc, on="t", how="left")
         .join(ptc, on=["i", "v", "t"], how="left").join(tcm, on=["i", "v", "t"], how="left")
         .join(gasmult, on=["r", "t"], how="left"))
    g = g.with_columns([pl.col(c).fill_null(0.0) for c in ["vom", "hr", "fp", "coalfp", "gpa", "capr", "inc", "crf", "crfi", "ptc", "tcm", "gm"]])
    fixed_fuel = ~isin("i", gas) & ~isin("i", bio) & ~isin("i", cofire) & (~isin("i", h2_gen) | (isin("i", h2_gen) & (pl.lit(int(sw["Sw_H2"]) == 0) | isin("h", h_stress))))
    co2_storage = float(sw["Sw_CO2_Storage"]) if not int(sw["Sw_CO2_Detail"]) else 0.0
    gascurve = int(sw["Sw_GasCurve"])
    terms = (pl.when(~isin("i", hybrid_non_csp)).then(pl.col("vom")).otherwise(0.0)
             + pl.when(fixed_fuel & (pl.col("hr") != 0)).then(pl.col("hr") * pl.col("fp")).otherwise(0.0)
             + pl.when(isin("i", cofire) & (pl.col("hr") != 0)).then((1.0 - sc["bio_cofire_perc"]) * pl.col("hr") * pl.col("coalfp")).otherwise(0.0)
             + pl.when(isin("i", gas) & (pl.col("hr") != 0) & pl.lit(gascurve == 2)).then(pl.col("hr") * pl.col("fp") * pl.col("gpa")).otherwise(0.0)
             + pl.when(isin("i", gas) & pl.lit(gascurve == 1)).then(pl.col("hr") * pl.col("gm") * pl.col("gpa")).otherwise(0.0)
             + pl.col("capr") * co2_storage
             - pl.when(pl.col("inc") != 0).then((pl.col("crf") / pl.col("crfi")) * pl.col("inc") * pl.col("capr")).otherwise(0.0)
             - pl.when(pl.col("ptc") != 0).then(pl.col("ptc") * pl.col("tcm")).otherwise(0.0))
    S["slice_objop_GEN"] = nonzero(g.with_columns((pl.col("hours") * terms).alias("value")).select(["i", "v", "r", "h", "t", "value"]))
    fom = S.cost_fom.filter(pl.col("t") == year)
    fom_cap = semi(fom, valcap_y, V4)
    rp = S._inputs.par("retire_penalty", ["allt"]).rename({"allt": "t", "value": "rp"})
    ret_y = S.retiretech.filter(pl.col("t") == year)
    pen = (fom_cap.join(ret_y, on=V4, how="semi").join(rp, on="t", how="inner")
           .with_columns((pl.col("value") * pl.col("rp")).alias("value")).select(V4 + ["value"]))
    if not int(sw["Sw_RetirePenalty"]):
        pen = pen.head(0)
    S["slice_objop_CAP"] = nonzero(fom_cap.join(pen.rename({"value": "pen"}), on=V4, how="left")
                                   .with_columns((pl.col("value") - pl.col("pen").fill_null(0.0)).alias("value")).select(V4 + ["value"]))
    S["slice_objop_INV"] = nonzero(semi(pen, valinv_y, V4))
    refurb_inv = valinv_y.filter(isin("i", members(S.refurbtech))) if int(sw["Sw_Refurb"]) else valinv_y.head(0)
    S["slice_objop_INV_REFURB"] = nonzero(semi(pen, refurb_inv, V4))
    up_cap = valcap_y.filter(isin("i", members(S.upgrade))) if int(sw["Sw_Upgrades"]) else valcap_y.head(0)
    S["slice_objop_UPGRADES"] = nonzero(semi(pen, up_cap, V4))
    S["slice_objinv_INV_REFURB"] = nonzero(refurb_inv.join(ccfm, on=["i", "r", "t"], how="inner").join(cc, on=["i", "t"], how="inner")
                                           .with_columns((pl.col("fin") * pl.col("cc")).alias("value")).select(V4 + ["value"]))
    cu = S.cost_upgrade.filter(pl.col("t") == year).rename({"value": "cu"})
    S["slice_objinv_UPGRADES"] = nonzero(up_cap.join(cu, on=V4, how="inner").join(ccfm, on=["i", "r", "t"], how="inner")
                                         .with_columns((pl.col("cu") * pl.col("fin")).alias("value")).select(V4 + ["value"]))
    rsc5 = ["i", "v", "r", "rscbin", "t"]
    empty5 = pl.DataFrame({c: pl.Series([], dtype=pl.Utf8) for c in rsc5} | {"value": pl.Series([], dtype=pl.Float64)})
    if S.allow_cap_up.height:
        raise NotImplementedError("allow_cap_up rows exist but cost_cap_up / cap_cap_up are not ported")
    S["slice_objinv_INV_CAP_UP"] = empty5
    S["slice_objinv_INV_ENER_UP"] = empty5
    S["allow_ener_up"] = empty5
    S["cap_cap_up"] = empty5
    S["cap_ener_up"] = empty5
    cost_trans = S.m_rsc_dat.filter(pl.col("sc_cat") == "cost_trans").select(["r", "i", "rscbin", pl.col("value").alias("ct")])
    cap_rsc_obj = (valcap_y.filter(isin("i", members(S.rsc_i)) & ~isin("i", members(S.spur_techs)) & ~isin("i", members(S.sccapcosttech)))
                   .join(S.m_rscfeas, on=["r", "i"], how="inner")
                   .join(cost_trans, on=["r", "i", "rscbin"], how="inner")
                   .with_columns((pl.col("ct") * sc["trans_fom_frac"]).alias("value")).select(rsc5 + ["value"]))
    S["slice_objop_CAP_RSC"] = nonzero(cap_rsc_obj)
    S["slice_objop_CAP_ENERGY"] = nonzero(semi(S.cost_fom_energy.filter(pl.col("t") == year), valcap_y.filter(isin("i", members(S.battery))), V4))
    routes_y = S.routes.filter(pl.col("t") == year)
    tlf = S.transmission_line_fom.rename({"value": "fom"})
    cap_tran = (routes_y.join(tlf, on=["r", "rr", "trtype"], how="left")
                .with_columns((pl.col("fom").fill_null(0.0) / 2.0
                               + pl.when(isin("trtype", members(S.lcclike))).then(sc["cost_acdc_lcc"] * sc["trans_fom_frac"]).otherwise(0.0)).alias("value"))
                .select(["r", "rr", "trtype", "t", "value"]))
    S["slice_objop_CAPTRAN_ENERGY"] = nonzero(cap_tran)
    hurdle = S.cost_hurdle.filter(pl.col("t") == year).rename({"value": "hurdle"})
    flow = (routes_y.join(hurdle, on=["r", "rr", "t"], how="inner").join(h, how="cross").join(hours, on="h", how="inner")
            .with_columns((pl.col("hurdle") * pl.col("hours")).alias("value")).select(["r", "rr", "h", "t", "trtype", "value"]))
    S["slice_objop_FLOW"] = nonzero(flow)
    S["slice_objop_EMIT"] = pl.DataFrame({c: pl.Series([], dtype=pl.Utf8) for c in ["etype", "e", "r", "t"]} | {"value": pl.Series([], dtype=pl.Float64)})
    dropped = (S.r.join(h, how="cross").join(hours, on="h", how="inner")
               .with_columns((pl.col("hours") * sc["cost_dropped_load"]).alias("value"), pl.lit(year).alias("t"))
               .select(["r", "h", "t", "value"]))
    if int(year) >= int(float(S.csw["GSw_StartMarkets"])):
        dropped = dropped.head(0)
    S["slice_objop_DROPPED"] = nonzero(dropped)
    S["slice_objop_EXCESS"] = nonzero(dropped)
    S["slice_scalars"] = pl.DataFrame({
        "name": ["cost_scale", "rhs_tolerance", "Sw_TransInvPRMderate", "Sw_Upgrades", "Sw_Refurb", "Sw_ForcePrescription",
                 "Sw_RetirePenalty", "Sw_PCM", "Sw_UpgradeYear", "caa_coal_retire_year", "firstyear_RPS"],
        "value": [1.0, sc["rhs_tolerance"], float(sw["Sw_TransInvPRMderate"]), float(sw["Sw_Upgrades"]), float(sw["Sw_Refurb"]),
                  float(sw["Sw_ForcePrescription"]), float(sw["Sw_RetirePenalty"]), 0.0, float(S.Sw_UpgradeYear),
                  float(S.caa_coal_retire_year), float(sc["firstyear_RPS"])]})
    return S
