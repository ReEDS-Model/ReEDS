from __future__ import annotations

import polars as pl

from .derive import Symbols, anti, cross, fsum_by, gams_round, isin, lookup, members, nonzero, one_col, semi

V4 = ["i", "v", "r", "t"]


def yr(col: str) -> pl.Expr:
    return pl.col(col).cast(pl.Int64)


def _sum_over(df: pl.DataFrame, keys: list[str]) -> pl.DataFrame:
    return df.group_by(keys).agg(pl.col("value").sum())


def _assign(target: pl.DataFrame, new: pl.DataFrame, keys: list[str], domain: pl.DataFrame | None = None) -> pl.DataFrame:
    """GAMS assignment: rows of `target` inside `domain` are replaced by `new` (zeros dropped)."""
    if domain is None:
        domain = new.select(keys)
    else:
        new = new.join(domain.select(keys).unique(), on=keys, how="semi")
    kept = anti(target, domain, keys)
    return pl.concat([kept.select(keys + ["value"]), nonzero(new.select(keys + ["value"]))])


def _empty(cols: list[str], value: bool = True) -> pl.DataFrame:
    frame = {c: pl.Series([], dtype=pl.Utf8) for c in cols}
    if value:
        frame["value"] = pl.Series([], dtype=pl.Float64)
    return pl.DataFrame(frame)


def _next_modeled(years: list[int], y: int) -> int | float:
    later = [x for x in years if x >= y]
    if not later:
        return float("inf")
    return later[0]


def capacity(S: Symbols) -> Symbols:
    I = S._inputs
    sw, sc, csw = S.sw, S.sc, S.csw
    t_all = S.t
    tfirst_year = S.years[0]
    ban = members(S.ban)
    bannew = members(S.bannew)
    tmodel_new = S.tmodel_new
    tmodel_new_years_str = {str(y) for y in S.years}
    upgrades_on = int(sw["Sw_Upgrades"])
    upgrade = members(S.upgrade)
    upgrade_to = S.upgrade_to
    upgrade_from = S.upgrade_from
    is_new = isin("v", members(S.newv))

    # ------------------------------------------------------------- switch-derived years
    uy = int(float(csw["GSw_UpgradeYear"]))
    S["Sw_UpgradeYear"] = uy if uy in S.years else _next_modeled(S.years, uy)
    if "caa_coal_retire_year" not in sc:
        raise KeyError("caa_coal_retire_year scalar is missing from scalars.txt")
    caa = int(float(sc["caa_coal_retire_year"]))
    caa = caa if caa in S.years else _next_modeled(S.years, caa)
    if int(sw["Sw_Clean_Air_Act"]) == 0:
        caa = S.years[-1]
    S["caa_coal_retire_year"] = caa

    # ------------------------------------------------------------- vintages
    newv_ord = pl.DataFrame({"v": S.newv["v"].to_list(), "ord": [float(k + 1) for k in range(S.newv.height)]})
    S["ivt_num"] = I.par("ivt", ["i", "allt"])
    ivt_num = semi(S.ivt_num.rename({"allt": "t"}), t_all, ["t"])
    ivt = (ivt_num.join(newv_ord, left_on="value", right_on="ord", how="inner").select(["i", "v", "t"]).unique())
    if upgrades_on:
        up_rows = (upgrade_to.join(ivt.rename({"i": "ii"}), on="ii", how="inner").filter(yr("t") >= S.Sw_UpgradeYear)
                   .select(["i", "v", "t"]).unique())
        dom = S.upgrade.join(S.newv, how="cross").join(t_all, how="cross").filter(yr("t") >= S.Sw_UpgradeYear).select(["i", "v", "t"])
        ivt = pl.concat([anti(ivt, dom, ["i", "v", "t"]), up_rows]).unique()
    S["ivt"] = ivt
    S["countnc"] = ivt.group_by(["i", "v"]).agg(pl.len().cast(pl.Float64).alias("value"))
    has_new1 = set(ivt.filter(pl.col("v") == "new1")["i"].to_list())
    has_other = set(ivt.filter(pl.col("v") != "new1")["i"].to_list())
    S["one_newv"] = one_col(has_new1 - has_other, "i")
    fy_v = ivt.group_by(["i", "v"]).agg(yr("t").min().alias("first"), yr("t").max().alias("last"))
    S["firstyear_v"] = fy_v.select(["i", "v", pl.col("first").cast(pl.Float64).alias("value")])
    S["lastyear_v"] = fy_v.select(["i", "v", pl.col("last").cast(pl.Float64).alias("value")])

    # ------------------------------------------------------------- first years
    firstyear = I.par("firstyear", ["i"])
    firstyear_min = sc["firstyear_min"]
    firstyear = firstyear.with_columns(
        pl.when(pl.col("value") < firstyear_min).then(firstyear_min).otherwise(pl.col("value")).alias("value"))
    excluded = members(S.gas_ct) | members(S.distpv) | upgrade | ban
    model_builds_start_yr = firstyear.filter(~isin("i", excluded))["value"].min()
    S["model_builds_start_yr"] = model_builds_start_yr
    firstyear = pl.concat([firstyear, anti(S.i, firstyear).with_columns(pl.lit(float(model_builds_start_yr)).alias("value"))])
    up_fy = upgrade_to.join(firstyear.rename({"i": "ii"}), on="ii", how="inner").group_by("i").agg(pl.col("value").sum())
    firstyear = _assign(firstyear, up_fy, ["i"], domain=S.upgrade)
    S["firstyear"] = firstyear
    fy = dict(zip(firstyear["i"], firstyear["value"]))

    # ------------------------------------------------------------- existing capacity inputs
    capnonrsc = I.par("capnonrsc", ["i", "r"])
    capnonrsc_energy = I.par("capnonrsc_energy", ["i", "r"])
    caprsc = I.par("caprsc", ["i", "v", "r"])
    prescribednonrsc = I.par("prescribed_nonRSC", ["i", "v", "r", "allt"])
    prescribednonrsc_energy = I.par("prescribed_nonRSC_energy", ["i", "v", "r", "allt"])
    prescribedrsc = I.par("prescribed_rsc", ["i", "v", "r", "allt"])
    prescribedretirements = I.par("retirements", ["i", "v", "r", "allt", "alltt", "captype"])
    prescribedretirements_energy = I.par("retirements_energy", ["v", "r", "i", "allt", "alltt", "captype"])
    forced_retirements = I.par("forced_retirements", ["i", "st"])
    forced_retire = (forced_retirements.join(S.r_st, on="st", how="inner").join(t_all, how="cross")
                     .filter(yr("t") >= pl.col("value")).select(["i", "r", "t"]).unique())
    up_fr = upgrade_to.join(forced_retire.rename({"i": "ii"}), on="ii", how="inner").select(["i", "r", "t"]).unique()
    S["forced_retire"] = pl.concat([forced_retire, up_fr]).unique()
    hintage = I.par("hintage_data", ["i", "v", "r", "allt", "hintage_char"])
    if not int(sw["Sw_UpgradeHeatRateAdj"]):
        hr = hintage.filter((pl.col("hintage_char") == "whr") & isin("v", members(S.initv)))
        retro = hintage.filter((pl.col("hintage_char") == "wccs_retro_hr") & isin("v", members(S.initv))).select(["i", "v", "r", "allt"])
        new_retro = semi(hr, retro, ["i", "v", "r", "allt"]).with_columns(pl.lit("wccs_retro_hr").alias("hintage_char"))
        hintage = _assign(hintage, new_retro.select(["i", "v", "r", "allt", "hintage_char", "value"]), ["i", "v", "r", "allt", "hintage_char"],
                          domain=retro.with_columns(pl.lit("wccs_retro_hr").alias("hintage_char")))
    if upgrades_on:
        uhc = I.set("upgrade_hintage_char", ["hintage_char"])
        from_techs = upgrade_from.select(pl.col("ii").alias("i")).unique()
        cap_uy = (hintage.filter((pl.col("hintage_char") == "cap") & (pl.col("allt") == str(S.Sw_UpgradeYear)))
                  .select(["i", "v", "r"]).unique())
        eligible = semi(cap_uy, from_techs, ["i"]).join(uhc, how="cross")
        prev_model = {str(y): str(S.years[k - 1]) for k, y in enumerate(S.years) if k > 0}
        for tt in S.years[1:]:
            tts = str(tt)
            have = hintage.filter(pl.col("allt") == tts).select(["i", "v", "r", "hintage_char"])
            need = anti(eligible, have, ["i", "v", "r", "hintage_char"])
            src = hintage.filter(pl.col("allt") == prev_model[tts]).select(["i", "v", "r", "hintage_char", "value"])
            rows = need.join(src, on=["i", "v", "r", "hintage_char"], how="inner").with_columns(pl.lit(tts).alias("allt"))
            hintage = pl.concat([hintage, nonzero(rows.select(["i", "v", "r", "allt", "hintage_char", "value"]))])
    S["hintage_data"] = hintage
    binned_capacity = hintage.filter(pl.col("hintage_char") == "cap").select(["i", "v", "r", "allt", "value"])
    S["binned_capacity"] = binned_capacity
    S["binned_heatrates"] = hintage.filter(pl.col("hintage_char") == "whr").select(["i", "v", "r", "allt", "value"])
    maxage = I.par("maxage", ["i"])
    maxage = pl.concat([maxage, anti(S.i, maxage).with_columns(pl.lit(float(sc["maxage_default"])).alias("value"))])
    up_ma = upgrade_to.join(maxage.rename({"i": "ii"}), on="ii", how="inner").group_by("i").agg(pl.col("value").sum())
    maxage = _assign(maxage, up_ma, ["i"], domain=S.upgrade)
    S["maxage"] = maxage
    ma = dict(zip(maxage["i"], maxage["value"]))
    S["batterymandate"] = I.par("storage_mandates", ["st", "allt"])
    S["offshore_cap_req"] = I.par("offshore_req", ["st", "allt"])
    S["r_offshore"] = (semi(S.offshore_cap_req.rename({"allt": "t"}), t_all, ["t"]).join(S.r_st, on="st", how="inner")
                       .select(["r", "t"]).unique().with_columns(pl.lit(1.0).alias("value")))
    geo_cap_exog = I.par("geoexist", ["i", "r"])
    S["geo_cap_exog"] = geo_cap_exog
    exog_wind_ons_rsc = I.par("exog_wind_ons_rsc", ["i", "r", "rscbin", "allt"])
    exog_wind_ofs_rsc = I.par("exog_wind_ofs_rsc", ["i", "r", "rscbin", "allt"])
    exog_upv_rsc = I.par("exog_upv_rsc", ["i", "r", "rscbin", "allt"])
    exog_onlineyear = I.par("exog_onlineyear", ["i", "v", "r", "allt"])
    if csw["geohydrosupplycurve"] == "reV":
        raise NotImplementedError("geohydrosupplycurve=reV exogenous geothermal is not ported")
    S["exog_rsc"] = one_col(members(S.onswind) | members(S.upv), "i")

    # ------------------------------------------------------------- capacity_exog
    all_t = t_all["t"].to_list()
    cap = _empty(V4)
    geo_init = (geo_cap_exog.filter(isin("i", members(S.geo_hydro) | members(S.geo_egs)))
                .with_columns(pl.lit("init-1").alias("v")).join(t_all, how="cross").select(V4 + ["value"]))
    cap = _assign(cap, geo_init, V4)
    ret_existing = (prescribedretirements.filter(pl.col("captype") == "existing")
                    .join(t_all, how="cross").filter(yr("allt") <= yr("t"))
                    .group_by(["i", "v", "r", "t"]).agg(pl.col("value").sum().alias("ret")))
    age_ok = (S.i.join(t_all, how="cross")
              .with_columns(pl.col("i").replace_strict(ma).alias("maxage"))
              .filter((yr("t") - tfirst_year) < pl.col("maxage")).select(["i", "t"]))
    dom = age_ok.join(S.r, how="cross").with_columns(pl.lit("init-1").alias("v")).select(V4)
    init = (dom.join(capnonrsc.rename({"value": "cap"}), on=["i", "r"], how="left")
            .join(ret_existing, on=V4, how="left")
            .with_columns(pl.max_horizontal(pl.lit(0.0), pl.col("cap").fill_null(0.0) - pl.col("ret").fill_null(0.0)).alias("value"))
            .select(V4 + ["value"]))
    cap = _assign(cap, init, V4, domain=dom)
    ret_e = (prescribedretirements_energy.filter(pl.col("captype") == "existing")
             .join(t_all, how="cross").filter(yr("allt") <= yr("t"))
             .group_by(["i", "v", "r", "t"]).agg(pl.col("value").sum().alias("ret")))
    cap_e = (dom.join(capnonrsc_energy.rename({"value": "cap"}), on=["i", "r"], how="left")
             .join(ret_e, on=V4, how="left")
             .with_columns(pl.max_horizontal(pl.lit(0.0), pl.col("cap").fill_null(0.0) - pl.col("ret").fill_null(0.0)).alias("value"))
             .select(V4 + ["value"]))
    cap_e = nonzero(cap_e)
    binned_it = (semi(binned_capacity, S.initv, ["v"]).rename({"allt": "t"}).select(["i", "t"]).unique())
    cap = anti(cap, binned_it.join(S.initv, how="cross"), ["i", "t", "v"])
    for hyd in ("hyded", "hydend"):
        cap = cap.filter(pl.col("i") != hyd)
        rows = caprsc.filter(pl.col("i") == hyd).join(t_all, how="cross").select(V4 + ["value"])
        cap = pl.concat([cap, rows])
    binned_ivr = binned_capacity.select(["i", "v", "r"]).unique()
    cap = anti(cap, binned_ivr, ["i", "v", "r"])
    cap = pl.concat([cap, semi(binned_capacity.rename({"allt": "t"}), t_all, ["t"]).select(V4 + ["value"])])
    cap_rsc = _empty(["i", "v", "r", "rscbin", "t"])
    for techs, exog, clear in ((members(S.onswind), exog_wind_ons_rsc, members(S.wind)),
                               (members(S.ofswind), exog_wind_ofs_rsc, set()),
                               (members(S.upv), exog_upv_rsc, members(S.upv))):
        if clear:
            cap = cap.filter(~isin("i", clear))
        ex = semi(exog.filter(isin("i", techs)).rename({"allt": "t"}), t_all, ["t"])
        tot = ex.group_by(["i", "r", "t"]).agg(pl.col("value").sum()).with_columns(pl.lit("init-1").alias("v"))
        cap = pl.concat([cap, tot.select(V4 + ["value"])])
        cap_rsc = pl.concat([cap_rsc, ex.with_columns(pl.lit("init-1").alias("v")).select(["i", "v", "r", "rscbin", "t", "value"])])
    cap = cap.filter(~isin("i", {"geothermal", "hydro"}))
    if int(sw["Sw_H2"]):
        smr = I.par("h2_existing_smr_cap", ["r", "t"])
        cap = _assign(cap, smr.with_columns(pl.lit("smr").alias("i"), pl.lit("init-1").alias("v")).select(V4 + ["value"]), V4,
                      domain=S.r.join(t_all, how="cross").with_columns(pl.lit("smr").alias("i"), pl.lit("init-1").alias("v")).select(V4))
    if int(sw["Sw_Canada"]) == 1:
        can_cap = I.par("can_imports_capacity", ["r", "allt"]).rename({"allt": "t"})
        dom = S.r.join(t_all, how="cross").with_columns(pl.lit("can-imports").alias("i"), pl.lit("init-1").alias("v")).select(V4)
        cap = _assign(cap, dom.join(can_cap, on=["r", "t"], how="inner").select(V4 + ["value"]), V4, domain=dom)
    cap = nonzero(cap)
    S["capacity_exog"] = cap
    S["capacity_exog_energy"] = cap_e
    S["capacity_exog_rsc"] = nonzero(cap_rsc)
    refurb = members(S.refurbtech)
    prev_t = {all_t[k]: all_t[k - 1] for k in range(1, len(all_t))}
    next_t = {v: k for k, v in prev_t.items()}
    cap_prev = (cap.filter(isin("t", set(next_t))).with_columns(pl.col("t").replace_strict(next_t).alias("t"))
                .rename({"value": "prev"}))
    are = (cap_prev.filter(isin("i", refurb) & isin("v", members(S.initv)))
           .join(cap.rename({"value": "cur"}), on=V4, how="left")
           .with_columns(pl.col("cur").fill_null(0.0))
           .filter(pl.col("prev") > pl.col("cur"))
           .with_columns((pl.col("prev") - pl.col("cur")).alias("value")).select(V4 + ["value"]))
    m_cap = cap
    m_cap = _assign(m_cap, geo_cap_exog.filter(isin("i", members(S.geo))).with_columns(pl.lit("init-1").alias("v"))
                    .join(t_all, how="cross").select(V4 + ["value"]), V4,
                    domain=S.geo.join(S.r, how="cross").join(t_all, how="cross").with_columns(pl.lit("init-1").alias("v")).select(V4))
    m_cap_e = cap_e

    # ------------------------------------------------------------- prescriptions
    pres_nonrsc_cum = (prescribednonrsc.join(tmodel_new, how="cross").filter(yr("allt") <= yr("t"))
                       .group_by(V4).agg(pl.col("value").sum()))
    mrp = pres_nonrsc_cum
    pres_rsc_cum = (prescribedrsc.join(tmodel_new, how="cross").filter(yr("allt") <= yr("t"))
                    .group_by(V4).agg(pl.col("value").sum().alias("rsc")))
    rsc_dom = (pres_rsc_cum.select(V4).vstack(semi(m_cap, tmodel_new, ["t"]).select(V4)).unique()
               .filter(isin("i", members(S.rsc_i))))
    rsc_mrp = (rsc_dom.join(pres_rsc_cum, on=V4, how="left").join(m_cap.rename({"value": "cap"}), on=V4, how="left")
               .with_columns((pl.col("rsc").fill_null(0.0) + pl.col("cap").fill_null(0.0)).alias("value")).select(V4 + ["value"]))
    mrp = _assign(mrp, rsc_mrp, V4)
    S["m_required_prescriptions"] = nonzero(mrp)
    S["m_required_prescriptions_energy"] = (prescribednonrsc_energy.join(tmodel_new, how="cross")
                                            .filter(yr("allt") <= yr("t")).group_by(V4).agg(pl.col("value").sum()))
    degrade_annual = I.par("degradation_annual", ["i"])
    S["degrade_annual"] = degrade_annual
    da = dict(zip(degrade_annual["i"], degrade_annual["value"]))
    tt_pairs = t_all.join(t_all.rename({"t": "tt"}), how="cross").filter(yr("tt") >= yr("t"))
    dn = (anti(S.i, S.ban).join(tt_pairs, how="cross")
          .with_columns(pl.col("i").replace_strict(da, default=0.0).alias("d"))
          .with_columns(((1.0 - pl.col("d")) ** (yr("tt") - yr("t")).cast(pl.Float64)).alias("value"))
          .select(["i", "t", "tt", "value"]))
    S["degrade_new"] = dn.with_columns(gams_round(pl.col("value"), 3).alias("value"))
    online = hintage.filter((pl.col("hintage_char") == "wonlineyear") & isin("v", members(S.initv))).select(["i", "v", "r", "allt", "value"])
    exog_onlineyear = _assign(exog_onlineyear, online, ["i", "v", "r", "allt"])
    S["exog_onlineyear"] = semi(exog_onlineyear, t_all.rename({"t": "allt"}), ["allt"])
    has_cap = semi(m_cap, S.initv, ["v"]).select(["i", "v", "r"]).unique()
    di = has_cap.join(t_all, how="cross").with_columns(pl.lit(1.0).alias("value")).select(V4 + ["value"])
    di2 = (semi(exog_onlineyear.rename({"allt": "t"}), t_all, ["t"]).filter(isin("v", members(S.initv)))
           .with_columns(pl.col("i").replace_strict(da, default=0.0).alias("d"))
           .filter(pl.col("d") != 0.0)
           .with_columns(((1.0 - pl.col("d")) ** pl.max_horizontal(pl.lit(0.0), yr("t").cast(pl.Float64) - pl.col("value"))).alias("value"))
           .select(V4 + ["value"]))
    S["degrade_init"] = _assign(di, di2, V4)
    prev = {str(y): (str(S.years[k - 1]) if k > 0 else "0") for k, y in enumerate(S.years)}
    build_src = fsum_by(pl.concat([prescribednonrsc, prescribedrsc]), ["i", "v", "r", "allt"])
    pb = fsum_by(build_src.join(tmodel_new, how="cross")
                 .with_columns(pl.col("t").replace_strict(prev).cast(pl.Int64).alias("prev"))
                 .filter((yr("allt") <= yr("t")) & (yr("allt") > pl.col("prev"))), V4)
    S["prescribed_build"] = nonzero(pb)
    S["prescribed_build_energy"] = nonzero(
        prescribednonrsc_energy.join(tmodel_new, how="cross")
        .with_columns(pl.col("t").replace_strict(prev).cast(pl.Int64).alias("prev"))
        .filter((yr("allt") <= yr("t")) & (yr("allt") > pl.col("prev")))
        .group_by(V4).agg(pl.col("value").sum()))
    S["prescribed_retirements"] = (prescribedretirements.filter(pl.col("captype") == "prescribed")
                                   .rename({"allt": "t", "alltt": "tt"})
                                   .filter(isin("t", tmodel_new_years_str) & isin("tt", tmodel_new_years_str))
                                   .select(["i", "v", "r", "t", "tt", "value"]))
    S["prescribed_retirements_energy"] = (prescribedretirements_energy.filter(pl.col("captype") == "prescribed")
                                          .rename({"allt": "t", "alltt": "tt"})
                                          .filter(isin("t", tmodel_new_years_str) & isin("tt", tmodel_new_years_str))
                                          .select(["i", "v", "r", "t", "tt", "value"]))
    S["prescription_check"] = (semi(S.prescribed_build, ivt, ["i", "v", "t"]).filter(~isin("i", ban))
                               .filter(is_new).select(V4))

    # ------------------------------------------------------------- supply curves and feasibility
    rsc_dat = I.par("rsc_combined", ["i", "r", "sc_cat", "rscbin"])
    cost_mult = pl.when(isin("i", members(S.hydro) | {"pumped-hydro"}) & (pl.col("sc_cat") == "cost")).then(1000.0).otherwise(1.0)
    rsc_dat = rsc_dat.with_columns((pl.col("value") * cost_mult).alias("value"))
    psh_fixed = rsc_dat.filter(pl.col("i") == "pumped-hydro")
    flex_cap = psh_fixed.filter(pl.col("sc_cat") == "cap").with_columns(pl.lit("pumped-hydro-flex").alias("i"))
    flex_cost = (psh_fixed.filter(pl.col("sc_cat") == "cost")
                 .with_columns(pl.lit("pumped-hydro-flex").alias("i"), (pl.col("value") * float(csw["GSw_HydroVarPumpCostRatio"])).alias("value")))
    rsc_dat = rsc_dat.filter(~((pl.col("i") == "pumped-hydro-flex") & isin("sc_cat", {"cap", "cost"})))
    rsc_dat = pl.concat([rsc_dat, flex_cap, flex_cost])
    S["rsc_dat"] = rsc_dat
    rscfeas = rsc_dat.filter(pl.col("sc_cat") == "cap").select(["i", "r", "rscbin"]).unique()
    csp1 = members(S.csp1)
    for sub in (S.csp2, S.csp3, S.csp4):
        link = S.tg_rsc_cspagg.filter(isin("i", csp1) & isin("ii", members(sub)))
        extra = (link.join(rscfeas, on="i", how="inner").select([pl.col("ii").alias("i"), "r", "rscbin"]).unique())
        rscfeas = pl.concat([rscfeas, extra]).unique()
    rscfeas = rscfeas.filter(~isin("i", ban))
    S["rscfeas"] = rscfeas
    m_rscfeas = rscfeas.select(["r", "i", "rscbin"])
    csp_link = S.tg_rsc_cspagg.filter(~isin("i", ban) & isin("ii", members(S.csp) - ban))
    extra = csp_link.join(m_rscfeas, on="i", how="inner").select(["r", pl.col("ii").alias("i"), "rscbin"]).unique()
    m_rscfeas = pl.concat([m_rscfeas, extra]).unique()
    bin1_add = (semi(S.prescribed_build.filter(is_new), tmodel_new, ["t"])
                .filter(isin("i", members(S.rsc_i)) & ~isin("i", bannew)).select(["r", "i"]).unique())
    has_cap_rsc = rsc_dat.filter(pl.col("sc_cat") == "cap").group_by(["i", "r"]).agg(pl.col("value").sum()).filter(pl.col("value") != 0).select(["r", "i"])
    bin1_add = anti(bin1_add, has_cap_rsc, ["r", "i"]).with_columns(pl.lit("bin1").alias("rscbin"))
    m_rscfeas = pl.concat([m_rscfeas, bin1_add]).unique()
    S["m_rscfeas_initial"] = m_rscfeas

    # ------------------------------------------------------------- valcap
    ivt_cum = (ivt.rename({"t": "tt"}).join(t_all, how="cross").filter(yr("tt") <= yr("t")).select(["i", "v", "t"]).unique())
    valcap = semi(m_cap, tmodel_new, ["t"]).filter(~isin("i", ban)).select(V4)
    if upgrades_on:
        from_techs = upgrade_from.select(pl.col("ii").alias("i")).unique()
        at_uy = m_cap.filter(pl.col("t") == str(S.Sw_UpgradeYear)).select(["i", "v", "r"]).unique()
        keep = (semi(at_uy, from_techs, ["i"]).filter(~isin("i", ban)).join(tmodel_new, how="cross")
                .filter(yr("t") >= S.Sw_UpgradeYear).select(V4))
        valcap = pl.concat([valcap, keep]).unique()
    base_new = (semi(ivt_cum, tmodel_new, ["t"]).filter(~isin("i", ban | bannew | upgrade))
                .join(S.r, how="cross").select(V4))
    nonrsc_new = base_new.filter(~isin("i", members(S.rsc_i)))
    feas_ir = m_rscfeas.select(["r", "i"]).unique()
    rsc_new = semi(base_new.filter(isin("i", members(S.rsc_i))), feas_ir, ["i", "r"])
    valcap = pl.concat([valcap, nonrsc_new, rsc_new]).unique()
    mrp_new = S.m_required_prescriptions.filter(is_new & ~isin("i", ban))
    mrp_ivt = (mrp_new.rename({"t": "tt"}).select(["i", "v", "r", "tt"]).join(ivt.rename({"t": "tt"}), on=["i", "v", "tt"], how="semi"))
    mrp_ok = (mrp_new.select(V4).join(mrp_ivt, on=["i", "v", "r"], how="inner").filter(yr("tt") <= yr("t")).select(V4).unique())
    valcap = pl.concat([valcap, mrp_ok.filter(~isin("i", members(S.rsc_i))),
                        semi(mrp_ok.filter(isin("i", members(S.rsc_i))), feas_ir, ["i", "r"])]).unique()
    valcap = valcap.filter(~(isin("i", bannew) & is_new))
    pb_ivt = semi(S.prescribed_build, ivt, ["i", "v", "t"]).select(["i", "v", "r"]).unique()
    addback = (pb_ivt.filter(isin("i", bannew - ban)).join(tmodel_new, how="cross").select(V4).filter(is_new))
    valcap = pl.concat([valcap, addback]).unique()
    bm_rt = (S.batterymandate.rename({"allt": "t"}).join(S.r_st, on="st", how="inner").select(["r", "t"]).unique())
    mandate = pl.concat([
        S.r_offshore.select(["r", "t"]).join(S.ofswind, how="cross").select(["i", "r", "t"]),
        bm_rt.join(S.battery, how="cross").select(["i", "r", "t"]),
    ]).unique()
    vc = valcap.with_columns(pl.col("i").replace_strict(fy).alias("fy"))
    vc = vc.join(S.m_required_prescriptions.select(V4).with_columns(pl.lit(True).alias("has_mrp")), on=V4, how="left")
    vc = vc.join(mandate.with_columns(pl.lit(True).alias("mand")), on=["i", "r", "t"], how="left")
    vc = vc.with_columns(pl.col("has_mrp").fill_null(False), pl.col("mand").fill_null(False))
    vc = vc.filter(~(is_new & ~pl.col("has_mrp") & (yr("t") < pl.col("fy")) & ~pl.col("mand")))
    lyv = dict(zip(zip(fy_v["i"], fy_v["v"]), fy_v["last"]))
    mrp_before_last = (S.m_required_prescriptions.select(V4).rename({"t": "tt"})
                       .with_columns(pl.struct(["i", "v"]).map_elements(lambda s: float(lyv.get((s["i"], s["v"]), -1)), return_dtype=pl.Float64).alias("last"))
                       .filter(yr("tt").cast(pl.Float64) <= pl.col("last")).select(["i", "v", "r"]).unique()
                       .with_columns(pl.lit(True).alias("mrp_before_last")))
    vc = vc.join(mrp_before_last, on=["i", "v", "r"], how="left").with_columns(pl.col("mrp_before_last").fill_null(False))
    vc = vc.with_columns(pl.struct(["i", "v"]).map_elements(lambda s: float(lyv.get((s["i"], s["v"]), 1e9)), return_dtype=pl.Float64).alias("last"))
    vc = vc.filter(~(is_new & ~pl.col("mrp_before_last") & (pl.col("last") < pl.col("fy")) & ~pl.col("mand")))
    pc_cum = (S.prescription_check.rename({"t": "tt"}).join(tmodel_new, how="cross").filter(yr("tt") <= yr("t"))
              .select(V4).unique().with_columns(pl.lit(True).alias("pc")))
    vc = vc.join(pc_cum, on=V4, how="left").with_columns(pl.col("pc").fill_null(False))
    vc = vc.filter(~(is_new & (pl.col("i") != "gas-ct") & (yr("t") < pl.col("fy")) & ~pl.col("pc") & ~pl.col("mand")))
    valcap = vc.select(V4)
    valcap = semi(valcap, tmodel_new, ["t"])
    ivt_modeled = semi(ivt, tmodel_new, ["t"]).select(["i", "v"]).unique()
    valcap = pl.concat([valcap.filter(~is_new), semi(valcap.filter(is_new), ivt_modeled, ["i", "v"])])
    if upgrades_on:
        to_ban = set(upgrade_to.filter(isin("ii", ban))["i"].to_list())
        up_ok = S.upgrade.filter(~isin("i", ban | to_ban)).with_columns(pl.col("i").replace_strict(fy).alias("fy"))
        init_rows = (up_ok.join(upgrade_from, on="i", how="inner")
                     .join(valcap.filter(~is_new).rename({"i": "ii"}), on="ii", how="inner")
                     .filter((yr("t") >= S.Sw_UpgradeYear) & (yr("t").cast(pl.Float64) >= pl.col("fy"))).select(V4).unique())
        new_rows = (up_ok.join(upgrade_to, on="i", how="inner")
                    .join(valcap.filter(is_new).rename({"i": "ii"}), on="ii", how="inner")
                    .filter((yr("t") >= S.Sw_UpgradeYear) & (yr("t").cast(pl.Float64) >= pl.col("fy")))
                    .select(V4).unique())
        new_rows = semi(new_rows, ivt_cum, ["i", "v", "t"])
        valcap = pl.concat([valcap, init_rows, new_rows]).unique()
    valcap = valcap.filter(~(isin("i", upgrade) & (yr("t") < S.Sw_UpgradeYear)))
    if not upgrades_on:
        valcap = valcap.filter(~isin("i", upgrade))
    valcap = anti(valcap, S.forced_retire, ["i", "r", "t"])
    fr = S.forced_retire.with_columns(pl.lit(True).alias("fr"))
    can_upgrade = (upgrade_from.select(["i", "ii"]).join(S.r, how="cross").join(t_all, how="cross")
                   .join(S.forced_retire.with_columns(pl.lit(True).alias("x")), on=["i", "r", "t"], how="left")
                   .filter(pl.col("x").is_null()).select([pl.col("ii").alias("i"), "r", "t"]).unique()
                   .with_columns(pl.lit(True).alias("can_up")))
    mc = m_cap.join(fr, on=["i", "r", "t"], how="left").join(can_upgrade, on=["i", "r", "t"], how="left")
    mc = mc.with_columns(pl.col("fr").fill_null(False), pl.col("can_up").fill_null(False))
    coal_noccs = members(S.coal_noccs)
    mc = mc.filter(~(pl.col("fr") & ~pl.col("can_up")))
    mc = mc.filter(~(pl.col("fr") & ~isin("i", coal_noccs) & pl.col("can_up")))
    if not int(sw["Sw_Clean_Air_Act"]):
        mc = mc.filter(~(pl.col("fr") & isin("i", coal_noccs) & pl.col("can_up")))
    mc = mc.filter(~(pl.col("fr") & isin("i", coal_noccs) & (yr("t") > S.caa_coal_retire_year) & pl.col("can_up")))
    m_cap = mc.select(V4 + ["value"])
    valcap = valcap.filter(~(isin("i", upgrade) & isin("i", ban)))
    if int(sw["Sw_NukeStateBan"]) == 1:
        valcap = valcap.filter(~(isin("i", members(S.nuclear)) & is_new & isin("r", members(S.nuclear_ba_ban))))
    if int(csw["GSw_hydED"]) == 0:
        valcap = valcap.filter(~(isin("i", members(S.hydro)) & (pl.col("i") != "hyded")))
    valcap = pl.concat([valcap.filter(~is_new), semi(valcap.filter(is_new), ivt_modeled, ["i", "v"])])
    valcap = valcap.filter(~(isin("r", members(S.offshore)) & ~isin("i", members(S.ofswind))))
    valcap = valcap.unique()

    # ------------------------------------------------------------- valinv, valgen, inv_cond
    valinv = semi(valcap, ivt, ["i", "v", "t"])
    tb = S.tech_banned.select(["i", "r"])
    valinv = valinv.join(tb.with_columns(pl.lit(True).alias("tb")), on=["i", "r"], how="left")
    valinv = valinv.join(S.prescribed_build.select(V4).with_columns(pl.lit(True).alias("pb")), on=V4, how="left")
    valinv = valinv.with_columns(pl.col("tb").fill_null(False), pl.col("pb").fill_null(False))
    valinv = valinv.filter(~(pl.col("tb") & ~pl.col("pb")))
    valinv = valinv.filter(~isin("i", upgrade))
    ofs_rt = (S.offshore_cap_req.rename({"allt": "t"}).join(S.r_st, on="st", how="inner").select(["r", "t"]).unique())
    valinv = valinv.with_columns(pl.col("i").replace_strict(fy).alias("fy"))
    valinv = valinv.join(bm_rt.with_columns(pl.lit(True).alias("bm")), on=["r", "t"], how="left").with_columns(pl.col("bm").fill_null(False))
    valinv = valinv.join(ofs_rt.with_columns(pl.lit(True).alias("ofs")), on=["r", "t"], how="left").with_columns(pl.col("ofs").fill_null(False))
    valinv = valinv.filter(~((yr("t") < pl.col("fy")) & ~pl.col("pb")
                             & ~(pl.col("bm") & isin("i", members(S.battery)))
                             & ~(pl.col("ofs") & isin("i", members(S.ofswind)))))
    valinv = valinv.select(V4)
    valgen = valcap.filter(~isin("i", members(S.consume)))
    valgen = anti(valgen, S.forced_retire, ["i", "r", "t"])
    bio = I.par("bio_supplycurve", ["usda_region", "bioclass", "cat"])
    biofeas = (bio.filter((pl.col("cat") == "cap") & (pl.col("value") != 0)).select("usda_region").unique()
               .join(S.r_usda_region, on="usda_region", how="inner").select("r").unique())
    S["biofeas"] = biofeas
    bio_techs = members(S.cofire) | members(S.bio)
    for name, df in (("valcap", valcap), ("valgen", valgen), ("valinv", valinv)):
        df = df.filter(~(isin("i", bio_techs) & ~isin("r", members(biofeas))))
        S[name] = df
    S["valgen"] = semi(S.valgen, S.valcap, V4)
    S["valinv"] = semi(S.valinv, S.valcap, V4)
    S["valcap_irt"] = S.valcap.select(["i", "r", "t"]).unique()
    S["valcap_iv"] = S.valcap.select(["i", "v"]).unique()
    S["valcap_ir"] = S.valcap.select(["i", "r"]).unique()
    S["valcap_i"] = S.valcap.select(["i"]).unique()
    S["valcap_ivr"] = S.valcap.select(["i", "v", "r"]).unique()
    S["valinv_irt"] = S.valinv.select(["i", "r", "t"]).unique()
    S["valgen_irt"] = S.valgen.select(["i", "r", "t"]).unique()
    t_ord = {t: k for k, t in enumerate(all_t)}
    ic = (S.valinv.filter(is_new).rename({"t": "tt"})
          .join(tmodel_new, how="cross").filter(yr("tt") <= yr("t"))
          .with_columns(pl.col("t").replace_strict(t_ord).alias("ot"), pl.col("tt").replace_strict(t_ord).alias("ott"),
                        pl.col("i").replace_strict(ma).alias("maxage"))
          .filter((pl.col("ot") - pl.col("ott")).cast(pl.Float64) < pl.col("maxage"))
          .filter(~isin("i", ban) & ~isin("i", upgrade)).select(["i", "v", "r", "t", "tt"]).unique())
    S["inv_cond"] = ic
    S["noret_upgrade_tech"] = one_col(members(S.hyd_add_pump) | (
        ((members(S.coal_ccs) | members(S.gas_cc_ccs)) & upgrade) if int(sw["Sw_CCS_NoRetire"]) else set()), "i")
    mrc = (S.valinv.filter(is_new & isin("i", refurb)).rename({"t": "tt"}).join(tmodel_new, how="cross")
           .filter(yr("tt") < yr("t")).with_columns(pl.col("i").replace_strict(ma).alias("maxage"))
           .filter((yr("t") - yr("tt")).cast(pl.Float64) > pl.col("maxage"))
           .join(S.valcap, on=V4, how="semi").select(["i", "v", "r", "t", "tt"]).unique())
    S["m_refurb_cond"] = mrc
    S["avail_retire_exog_rsc"] = pl.concat([semi(are, S.valcap, V4).with_columns(gams_round(pl.col("value"), 3).alias("value")),
                                            anti(are, S.valcap, V4)])
    fp = (S.i.join(S.newv, how="cross").join(S.r, how="cross").join(t_all, how="cross")
          .with_columns(pl.col("i").replace_strict(fy).alias("fy")).filter(yr("t").cast(pl.Float64) < pl.col("fy")).select(V4))
    S["force_prescribe"] = pl.concat([fp, S.prescribed_build.select(V4)]).unique()
    S["m_capacity_exog"] = semi(m_cap, S.valcap, V4)
    S["m_capacity_exog0"] = S.m_capacity_exog
    S["m_capacity_exog_energy"] = m_cap_e
    _retiretech(S)
    return S


def _retiretech(S: Symbols) -> None:
    I = S._inputs
    sw = S.sw
    retire = int(sw["Sw_Retire"])
    initv = members(S.initv)
    noretire = members(I.set("noretire", ["i"])) | members(S.storage_standalone) | members(S.hyd_add_pump)
    S["noretire"] = one_col(noretire, "i")
    fossil_like = members(S.coal) | members(S.gas) | members(S.nuclear) | members(S.ogs) | members(S.h2_gen) | members(S.h2)
    iv = S.i.join(S.v, how="cross")
    if retire == 0:
        valret = iv.head(0)
    elif retire == 1:
        valret = iv.filter(isin("v", initv) & ~isin("i", noretire))
    elif retire == 2:
        valret = iv.filter(isin("v", initv) & ~isin("i", noretire) & isin("i", members(S.coal) | members(S.gas) | members(S.ogs)))
    elif retire in (3, 5):
        valret = iv.filter(~isin("i", noretire) & isin("i", fossil_like))
    elif retire == 4:
        valret = iv.filter(~isin("i", noretire))
    else:
        raise NotImplementedError(f"Sw_Retire={retire} is not ported")
    S["valret"] = valret
    rt = semi(S.valcap, valret, ["i", "v"])
    if retire in (3, 5):
        hint = S.hintage_data
        startyear = str(int(S.csw["startyear"]))
        online = hint.filter((pl.col("hintage_char") == "wonlineyear") & (pl.col("allt") == startyear)).select(["i", "v", "r", pl.col("value").alias("online")])
        age = (S.valcap.filter(isin("v", initv)).join(online, on=["i", "v", "r"], how="inner")
               .with_columns(pl.max_horizontal(pl.lit(0.0), yr("t").cast(pl.Float64) - pl.col("online")).alias("age")).select(V4 + ["age"]))
        mra = I.par("min_retire_age", ["i"])
        if int(sw["Sw_Clean_Air_Act"]):
            mra = mra.filter(~isin("i", members(S.coal)))
        young = (rt.filter(isin("v", initv) & ~isin("i", noretire) & isin("i", fossil_like))
                 .join(age, on=V4, how="left").with_columns(pl.col("age").fill_null(0.0))
                 .join(mra.rename({"value": "mra"}), on="i", how="left").with_columns(pl.col("mra").fill_null(0.0))
                 .filter(pl.col("age") <= pl.col("mra")).select(V4))
        rt = anti(rt, young, V4)
    if retire == 5:
        rt = rt.filter(~(isin("i", members(S.nuclear)) & (yr("t") <= 2030)))
    subs = I.par("nuclear_subsidies", ["st"]).rename({"value": "until"})
    sub_rt = S.r_st.join(subs, on="st", how="inner").select(["r", "until"])
    nuke_sub = (rt.filter(isin("v", initv) & isin("i", members(S.nuclear))).join(sub_rt, on="r", how="inner")
                .filter(yr("t").cast(pl.Float64) < pl.col("until")).select(V4))
    rt = anti(rt, nuke_sub, V4)
    if int(sw["Sw_NukeNoRetire"]) == 1:
        rt = rt.filter(~(isin("i", members(S.nuclear)) & (yr("t") <= int(sw["Sw_NukeNoRetireYear"]))))
    rt = rt.filter(yr("t") >= int(sw["Sw_Retireyear"]))
    if int(sw["Sw_Upgrades"]) == 2:
        raise NotImplementedError("Sw_Upgrades=2 retirement rules are not ported")
    S["retiretech"] = rt.select(V4).unique()
