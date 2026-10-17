from __future__ import annotations

import math

import polars as pl

from .derive import Symbols, anti, fsum_by, gams_round, isin, members, nonzero, one_col, semi
from .derive_capacity import V4, _assign, yr
from .derive_temporal import _rep_stress


def _rep_stress_set(I, key: str, dims: list[str], stress_year: str) -> pl.DataFrame:
    frames = [I.set(f"rep__{key}", dims)]
    skey = f"stress__{key}__{stress_year}"
    if skey in I:
        frames.append(I.set(skey, dims))
    return pl.concat(frames).unique(maintain_order=True)


def _empty(cols: list[str], value: bool = True) -> pl.DataFrame:
    schema = {c: pl.Utf8 for c in cols}
    if value:
        schema["value"] = pl.Float64
    return pl.DataFrame(schema=schema)


def operations(S: Symbols, stress_year: str) -> Symbols:
    I = S._inputs
    sw, sc, csw = S.sw, S.sc, S.csw
    year = str(S.year)
    t_all = S.t
    h = S.h
    valgen_y = S.valgen.filter(pl.col("t") == year)
    valcap_y = S.valcap.filter(pl.col("t") == year)
    upgrade_to = S.upgrade_to

    def from_to(table: pl.DataFrame, keys: list[str], link: pl.DataFrame) -> pl.DataFrame:
        other = [k for k in keys if k != "i"]
        return (link.join(table.rename({"i": "ii"}), on="ii", how="inner")
                .group_by(["i"] + other).agg(pl.col("value").sum()).select(["i"] + other + ["value"]))

    ortype = I.set("ortype", ["ortype"])
    orcat = I.set("orcat", ["orcat"])
    S["ortype"] = ortype
    opres_sw = int(sw["Sw_OpRes"])
    if opres_sw == 1:
        om = ortype.filter(pl.col("ortype") != "combo")
    elif opres_sw == 2:
        om = ortype.filter(pl.col("ortype") == "combo")
    else:
        om = ortype.head(0)
    S["opres_model"] = om
    periods = _rep_stress_set(I, "opres_periods", ["szn"], stress_year)
    S["opres_h"] = semi(S.h_szn.join(periods, on="szn", how="semi").select("h").unique(), h, ["h"])

    ramptime = I.par("ramptime", ["ortype"])
    nz = ramptime.filter(pl.col("value") != 0.0)
    if nz.height == 0:
        raise ValueError("ramptime.csv has no nonzero entries; the combo ramp time would divide by zero")
    combo_rt = math.fsum(nz["value"].to_list()) / float(nz.height)
    ramptime = _assign(ramptime, pl.DataFrame({"ortype": ["combo"], "value": [combo_rt]}), ["ortype"])
    orperc = I.par("orperc", ["ortype", "orcat"])
    combo = fsum_by(orperc, ["orcat"]).with_columns(pl.lit("combo").alias("ortype")).select(["ortype", "orcat", "value"])
    orperc = _assign(orperc, combo, ["ortype", "orcat"], domain=orcat.with_columns(pl.lit("combo").alias("ortype")).select(["ortype", "orcat"]))
    orperc = orperc.with_columns((pl.col("value") * float(sw["Sw_OpResReqMult"])).alias("value"))
    S["orperc"] = nonzero(orperc)

    ramprate = I.par("ramprate", ["i"])

    def named(name: str) -> float:
        v = ramprate.filter(pl.col("i") == name)["value"]
        return float(v[0]) if v.len() else 0.0

    ramprate = _assign(ramprate, S.hydro_d.with_columns(pl.lit(named("hydro")).alias("value")), ["i"], domain=S.hydro_d)
    ramprate = _assign(ramprate, S.geo.with_columns(pl.lit(named("geothermal")).alias("value")), ["i"], domain=S.geo)
    if int(sw["Sw_NukeFlex"]):
        ramprate = _assign(ramprate, S.nuclear.with_columns(pl.lit(named("coal-new")).alias("value")), ["i"], domain=S.nuclear)
    ramprate = _assign(ramprate, from_to(ramprate, ["i"], upgrade_to), ["i"], domain=S.upgrade)
    S["ramprate"] = ramprate
    rf = (S.i.join(ramptime.rename({"value": "rt"}), how="cross").join(ramprate.rename({"value": "rr"}), on="i", how="left")
          .with_columns(pl.min_horizontal(pl.lit(1.0), pl.col("rr").fill_null(0.0) * pl.col("rt")).alias("value"))
          .select(["i", "ortype", "value"]))
    rf = nonzero(rf)
    rf = _assign(rf, from_to(rf, ["i", "ortype"], upgrade_to), ["i", "ortype"], domain=S.upgrade.join(ortype, how="cross"))
    S["reserve_frac"] = rf

    coi = I.par(f"cost_opres_{csw['GSw_OpResCost']}", ["i", "ortype"])
    co = (S.i.join(ortype, how="cross").join(t_all, how="cross").join(coi, on=["i", "ortype"], how="left")
          .with_columns(pl.col("value").fill_null(0.0)))

    def copy_from(techs: pl.DataFrame, source: str) -> pl.DataFrame:
        src = co.filter(pl.col("i") == source).select(["ortype", "t", "value"])
        return techs.join(src, how="cross").select(["i", "ortype", "t", "value"])

    co = _assign(co, copy_from(S.geo, "geothermal"), ["i", "ortype", "t"], domain=S.geo.join(ortype, how="cross").join(t_all, how="cross"))
    co = _assign(co, copy_from(S.pvb, "battery_li"), ["i", "ortype", "t"], domain=S.pvb.join(ortype, how="cross").join(t_all, how="cross"))
    hrf = S.heat_rate_full
    hr_sum = fsum_by(hrf, ["i", "t"]).rename({"value": "s"})
    hr_cnt = hrf.filter(pl.col("value") != 0.0).group_by(["i", "t"]).len().rename({"len": "n"})
    hr_avg = hr_sum.filter(pl.col("s") != 0.0).join(hr_cnt, on=["i", "t"], how="inner").with_columns((pl.col("s") / pl.col("n")).alias("hr_avg")).select(["i", "t", "hr_avg"])
    fpr = S.fuel_price_raw
    fp_sum = fsum_by(fpr, ["i", "t"]).rename({"value": "s"})
    fp_cnt = fpr.filter(pl.col("value") != 0.0).group_by(["i", "t"]).len().rename({"len": "n"})
    fp_avg = fp_sum.filter(pl.col("s") != 0.0).join(fp_cnt, on=["i", "t"], how="inner").with_columns((pl.col("s") / pl.col("n")).alias("fp_avg")).select(["i", "t", "fp_avg"])
    spin_pen = I.par("heat_rate_penalty_spin", ["i"]).rename({"value": "pen"})
    spin_dom = co.filter((pl.col("ortype") == "spin") & (pl.col("value") == 0.0)).select(["i", "ortype", "t"])
    spin = (spin_dom.join(spin_pen, on="i", how="left").join(hr_avg, on=["i", "t"], how="left").join(fp_avg, on=["i", "t"], how="left")
            .with_columns((pl.col("pen").fill_null(0.0) * pl.col("hr_avg").fill_null(0.0) * pl.col("fp_avg").fill_null(0.0)).alias("value"))
            .select(["i", "ortype", "t", "value"]))
    co = _assign(co, spin, ["i", "ortype", "t"], domain=spin_dom)
    co = _assign(co, from_to(co, ["i", "ortype", "t"], upgrade_to), ["i", "ortype", "t"], domain=S.upgrade.join(ortype, how="cross").join(t_all, how="cross"))
    combo_cost = co.group_by(["i", "t"]).agg(pl.col("value").max()).with_columns(pl.lit("combo").alias("ortype")).select(["i", "ortype", "t", "value"])
    co = _assign(co, combo_cost, ["i", "ortype", "t"], domain=S.i.join(t_all, how="cross").with_columns(pl.lit("combo").alias("ortype")).select(["i", "ortype", "t"]))
    S["cost_opres"] = nonzero(co).with_columns(gams_round(pl.col("value"), 2).alias("value"))

    level = str(csw["GSw_OpResTradeLevel"])
    routes_ac = S.routes.filter(isin("trtype", members(S.aclike))).select(["r", "rr", "t"]).unique()
    if level == "r":
        opres_routes = routes_ac.head(0)
    else:
        region = S.hierarchy.select(["r", level]).unique()
        opres_routes = (routes_ac.join(region, on="r", how="inner").join(region.rename({"r": "rr", level: "lvl2"}), on="rr", how="inner")
                        .filter(pl.col(level) == pl.col("lvl2")).select(["r", "rr", "t"]))
    S["opres_routes"] = opres_routes

    pv_cf = (S.m_cf.filter(pl.col("t") == year).filter(isin("i", members(S.pv)))
             .join(valgen_y, on=V4, how="semi").join(S.i_c, on=["i", "c"], how="semi"))
    S["dayhours"] = semi(fsum_by(pv_cf, ["h"]).filter(pl.col("value") != 0.0).select("h"), h, ["h"])

    psh_ivr = S.valcap_ivr.filter(isin("i", members(S.psh)))
    mode = str(csw["GSw_HydroStorInMaxFrac"])
    if mode == "data":
        data = I.par("storinmaxfrac", ["i", "v", "r"]) if int(sw["Sw_Storage"]) == 1 else _empty(["i", "v", "r"])
        smf = semi(data, psh_ivr, ["i", "v", "r"])
    else:
        smf = psh_ivr.with_columns(pl.lit(float(mode)).alias("value"))
    standalone_pump = members(S.storage_standalone) | members(S.hyd_add_pump)
    fill = anti(S.valcap_ivr.filter(isin("i", standalone_pump)), nonzero(smf), ["i", "v", "r"]).with_columns(pl.lit(1.0).alias("value"))
    S["storinmaxfrac"] = nonzero(pl.concat([smf, fill]))
    S["minstorfrac"] = nonzero(psh_ivr.with_columns(pl.lit(float(csw["GSw_HydroStorInMinLoad"])).alias("value")))
    if members(S.evmc_storage):
        raise NotImplementedError("evmc_storage_charge_frac is not ported")
    S["evmc_storage_charge_frac"] = _empty(["i", "r", "h", "t"])

    startcost = I.par("startcost", ["i"])
    startcost = _assign(startcost, from_to(startcost, ["i"], upgrade_to), ["i"], domain=S.upgrade)
    mode_sc = int(sw["Sw_StartCost"])
    nuclear, ccs, coal = members(S.nuclear), members(S.ccs), members(S.coal)
    gas_cc, h2_cc = members(S.gas_cc), members(S.h2_cc)
    if mode_sc == 0:
        startcost = startcost.head(0)
    elif mode_sc == 1:
        startcost = startcost.filter(isin("i", nuclear))
    elif mode_sc == 2:
        startcost = startcost.filter(isin("i", nuclear | ccs | coal))
    elif mode_sc == 3:
        startcost = startcost.filter(isin("i", ccs | coal))
    elif mode_sc == 4:
        startcost = startcost.filter(isin("i", ccs | coal | gas_cc | h2_cc))
    elif mode_sc == 5:
        startcost = startcost.filter(~isin("i", nuclear))
    elif mode_sc == 6:
        pass
    else:
        raise ValueError(f"Sw_StartCost={mode_sc} is not a known setting")
    S["startcost"] = nonzero(startcost)
    S["mingen_fixed"] = I.par("mingen_fixed", ["i"])
    mincf = I.par("minCF_input", ["i"]).join(t_all, how="cross").select(["i", "t", "value"])
    mincf = _assign(mincf, from_to(mincf, ["i", "t"], upgrade_to), ["i", "t"], domain=S.upgrade.join(t_all, how="cross"))
    if int(sw["Sw_NukeFlex"]):
        mincf = _assign(mincf, S.nuclear.join(t_all, how="cross").with_columns(pl.lit(sc["minCF_nuclear_flex"]).alias("value")), ["i", "t"],
                        domain=S.nuclear.join(t_all, how="cross"))
    S["minCF"] = nonzero(mincf)
    maxcf = I.par("maxdailycf_input", ["i"]).join(t_all, how="cross").select(["i", "t", "value"])
    maxcf = _assign(maxcf, from_to(maxcf, ["i", "t"], upgrade_to), ["i", "t"], domain=S.upgrade.join(t_all, how="cross"))
    S["maxdailycf"] = nonzero(maxcf)

    hours_raw = S.hours_raw.rename({"value": "hours"})
    mcf = S.m_cf.filter(pl.col("t") == year)
    num = fsum_by(mcf.join(S.h_szn, on="h", how="inner").join(hours_raw, on="h", how="inner")
                  .with_columns((pl.col("hours") * pl.col("value")).alias("value")), ["i", "v", "r", "szn", "t"]).rename({"value": "num"})
    den = fsum_by(S.h_szn.join(hours_raw, on="h", how="inner").select(["szn", pl.col("hours").alias("value")]), ["szn"]).rename({"value": "den"})
    cf_tech, hydro_d, hyd_add_pump, psh = members(S.cf_tech), members(S.hydro_d), members(S.hyd_add_pump), members(S.psh)
    dom = valcap_y.filter(isin("i", cf_tech & (hydro_d | hyd_add_pump))).join(S.szn, how="cross").select(["i", "v", "r", "szn", "t"])
    mcs = (dom.join(num, on=["i", "v", "r", "szn", "t"], how="left").join(den, on="szn", how="inner")
           .with_columns((pl.col("num").fill_null(0.0) / pl.col("den")).alias("value")).select(["i", "v", "r", "szn", "t", "value"]))
    mcs = nonzero(mcs)
    k5 = ["i", "v", "r", "szn", "t"]
    up1 = valcap_y.filter(isin("i", cf_tech & members(S.upgrade) & (hydro_d | psh))).join(S.szn, how="cross").select(k5)
    rows = (up1.join(S.upgrade_from, on="i", how="inner").join(mcs.rename({"i": "ii"}), on=["ii", "v", "r", "szn", "t"], how="inner")
            .group_by(k5).agg(pl.col("value").sum()))
    mcs = _assign(mcs, rows, k5, domain=up1)
    up2 = anti(valcap_y.filter(isin("i", cf_tech & members(S.upgrade) & hydro_d)).join(S.szn, how="cross").select(k5), mcs, k5)
    rows = (up2.join(upgrade_to, on="i", how="inner").join(mcs.rename({"i": "ii"}), on=["ii", "v", "r", "szn", "t"], how="inner")
            .group_by(k5).agg(pl.col("value").sum()))
    mcs = _assign(mcs, rows, k5, domain=up2)
    up3 = anti(valcap_y.filter(isin("i", cf_tech & members(S.upgrade) & hydro_d)).join(S.szn, how="cross").select(k5), mcs, k5)
    mcs = pl.concat([mcs, up3.with_columns(pl.lit(1.0).alias("value"))])
    S["m_cf_szn"] = mcs

    nh = _rep_stress(I, "numhours_nexth", ["h", "hh"], stress_year)
    S["numhours_nexth"] = semi(semi(nh, h, ["h"]), h.rename({"h": "hh"}), ["hh"])
    hsg = _rep_stress_set(I, "hour_szn_group", ["h", "hh"], stress_year)
    hsg = semi(semi(hsg, h, ["h"]), h.rename({"h": "hh"}), ["hh"]).filter(pl.col("h") != pl.col("hh"))
    S["hour_szn_group"] = hsg

    bio = I.par("bio_supplycurve", ["usda_region", "bioclass", "cat"])
    content = 13.0
    S["bio_energy_content"] = content
    cap = (bio.filter(pl.col("cat") == "cap").with_columns((pl.col("value") * 1e6 * content * float(sw["Sw_BioSupply"])).alias("value"))
           .select(["usda_region", "bioclass", "value"]))
    price = bio.filter(pl.col("cat") == "price").with_columns((pl.col("value") / content).alias("value")).select(["usda_region", "bioclass", "value"])
    S["biosupply_cap"] = nonzero(cap.with_columns(gams_round(pl.col("value"), 3).alias("value")))
    S["biosupply_price"] = nonzero(price.with_columns(gams_round(pl.col("value"), 2).alias("value")))
    S["bioclass"] = I.set("bioclass", ["bioclass"])
    S["usda_region"] = I.set("usda_region", ["usda_region"])
    S["r_usda"] = S.hierarchy.select(["r", "usda_region"]).unique()
    bio_transport_cost = float(sw["Sw_BioTransportCost"]) / content

    hours = S.hours.rename({"value": "hours"})
    co_y = S.cost_opres.filter(pl.col("t") == year).rename({"value": "cost"})
    obj_opres = (om.join(valgen_y, how="cross").join(rf, on=["i", "ortype"], how="inner").join(S.opres_h, how="cross")
                 .join(co_y, on=["i", "ortype", "t"], how="inner").join(hours, on="h", how="inner")
                 .with_columns((pl.col("hours") * pl.col("cost")).alias("value")).select(["ortype", "i", "v", "r", "h", "t", "value"]))
    S["slice_objop_OPRES"] = nonzero(obj_opres)
    vg_irt = S.valgen_irt.filter(pl.col("t") == year)
    obj_ramp = (vg_irt.join(S.startcost.rename({"value": "sc"}), on="i", how="inner").join(S.numhours_nexth.rename({"value": "nh"}), how="cross")
                .with_columns((pl.col("sc") * pl.col("nh")).alias("value")).select(["i", "r", "h", "hh", "t", "value"]))
    if mode_sc == 0:
        obj_ramp = obj_ramp.head(0)
    S["slice_objop_RAMPUP"] = nonzero(obj_ramp)
    bio_r = valgen_y.filter(isin("i", members(S.bio) | members(S.cofire))).select(["r", "t"]).unique()
    price_r = fsum_by(S.r_usda.join(S.biosupply_price, on="usda_region", how="inner").select(["r", "bioclass", "value"]), ["r", "bioclass"])
    obj_bio = (bio_r.join(S.bioclass, how="cross").join(price_r, on=["r", "bioclass"], how="left")
               .with_columns((pl.col("value").fill_null(0.0) + bio_transport_cost).alias("value")).select(["bioclass", "r", "t", "value"]))
    S["slice_objop_BIOUSED"] = nonzero(obj_bio)

    fy_batt = S.firstyear.filter(isin("i", members(S.battery)))["value"]
    firstyear_battery = float(fy_batt.min()) if fy_batt.len() else 0.0
    extra = pl.DataFrame({
        "name": ["reg_energy_frac", "minbatteryduration", "caa_gas_max_cf", "caa_first_year", "caa_capture_rate_standard",
                 "bio_cofire_perc", "bio_transport_cost", "firstyear_battery", "Sw_StartMarkets", "Sw_OpRes", "Sw_StartCost",
                 "Sw_MingenFixed", "Sw_MinCF", "Sw_MaxDailyCF", "Sw_Clean_Air_Act", "Sw_BatteryMandate", "Sw_MinLoading",
                 "Sw_HybridPlant", "Sw_Canada"],
        "value": [sc["reg_energy_frac"], sc["minbatteryduration"], sc["caa_gas_max_cf"], sc["caa_first_year"], sc["caa_capture_rate_standard"],
                  sc["bio_cofire_perc"], bio_transport_cost, firstyear_battery, float(csw["GSw_StartMarkets"]), float(opres_sw), float(mode_sc),
                  float(sw["Sw_MingenFixed"]), float(sw["Sw_MinCF"]), float(sw["Sw_MaxDailyCF"]), float(sw["Sw_Clean_Air_Act"]),
                  float(sw["Sw_BatteryMandate"]), float(sw["Sw_MinLoading"]), float(sw["Sw_HybridPlant"]), float(sw["Sw_Canada"])]})
    S["slice_scalars"] = pl.concat([S.slice_scalars, extra])
    return S


def transmission(S: Symbols) -> Symbols:
    I = S._inputs
    sw, sc, csw = S.sw, S.sc, S.csw
    year = str(S.year)
    t_all = S.t
    R3 = ["r", "rr", "trtype"]

    S["tscbin"] = I.set("tscbin", ["tscbin"])
    S["transgrp"] = I.set("transgrp", ["transgrp"])
    S["transreg"] = I.set("transreg", ["transreg"])
    for name in ("tsc_binwidth", "tsc_forward", "tsc_reverse"):
        S[name] = I.par(name, ["r", "rr", "tscbin"]).with_columns(gams_round(pl.col("value"), 2).alias("value"))
    S["distance"] = I.par("distance", R3).with_columns(gams_round(pl.col("value"), 3).alias("value"))
    S["transmission_cost_nonac"] = I.par("transmission_cost_nonac", R3).with_columns(gams_round(pl.col("value"), 2).alias("value"))
    S["poi_cap_init"] = I.par("poi_cap_init", ["r"])
    S["trancap_init_transgroup"] = I.par("trancap_init_transgroup", ["transgrp", "transgrpp", "trtype"])
    S["firm_import_limit"] = I.par("firm_import_limit", ["transreg", "allt"]).rename({"allt": "t"})
    S["peakload_transreg"] = I.par("peakload_transreg", ["transreg", "t"])
    S["distance_reinforcement"] = I.par("distance_reinforcement", ["i", "r", "rscbin"])
    S["distance_spur"] = I.par("distance_spur", ["i", "r", "rscbin"])
    near, long_ = sc["firstyear_trans_nearterm"], sc["firstyear_trans_longterm"]
    tim = S.tmodel_new.with_columns(
        pl.when((yr("t") >= near) & (yr("t") < long_)).then(float(sw["Sw_TransInvMaxNearterm"]))
        .when(yr("t") >= long_).then(float(sw["Sw_TransInvMaxLongterm"])).otherwise(0.0).alias("value"))
    S["trans_inv_max"] = nonzero(tim)
    mode = int(sw["Sw_TransCapMaxTypes"])
    trtype = S.trtype
    if mode == 0:
        tmax = trtype.head(0)
    elif mode == 1:
        tmax = trtype
    elif mode == 2:
        tmax = trtype.filter(pl.col("trtype") == "vsc")
    elif mode == 3:
        tmax = trtype.filter(pl.col("trtype") != "ac")
    else:
        raise ValueError(f"Sw_TransCapMaxTypes={mode} is not a known setting")
    S["trtypemax"] = tmax
    ac_pairs = S.routes.filter(pl.col("trtype") == "ac").select(["r", "rr"]).unique()
    any_pairs = S.routes.select(["r", "rr"]).unique()
    rg = S.r_transgrp
    S["routes_transgroup"] = (ac_pairs.join(rg, on="r", how="inner").join(rg.rename({"r": "rr", "transgrp": "transgrpp"}), on="rr", how="inner")
                              .filter((pl.col("transgrp") != pl.col("transgrpp")) & (pl.col("r") != pl.col("rr")))
                              .select(["transgrp", "transgrpp", "r", "rr"]))
    rt = S.r_transreg
    S["routes_transreg"] = (any_pairs.join(rt, on="r", how="inner").join(rt.rename({"r": "rr", "transreg": "transregg"}), on="rr", how="inner")
                            .filter((pl.col("transreg") != pl.col("transregg")) & (pl.col("r") != pl.col("rr")))
                            .select(["transreg", "transregg", "r", "rr"]))
    tfut = I.par("trancap_fut", ["r", "rr", "trancap_fut_cat", "trtype", "t"])
    S["trancap_fut_possible"] = tfut.filter(pl.col("trancap_fut_cat") == "possible").select(R3 + ["t", "value"])

    tccfm = S.trans_cost_cap_fin_mult.filter(pl.col("t") == year).rename({"value": "fm"})
    rinv_y = S.routes_inv.filter(pl.col("t") == year)
    aclike, lcclike = members(S.aclike), members(S.lcclike)
    nonac = (rinv_y.filter(~isin("trtype", aclike)).join(S.transmission_cost_nonac.rename({"value": "cost"}), on=R3, how="inner")
             .join(tccfm, on="t", how="inner").with_columns(((pl.col("fm") * pl.col("cost")) / 2.0).alias("value")).select(R3 + ["t", "value"]))
    lcc = (rinv_y.filter(isin("trtype", lcclike)).join(tccfm, on="t", how="inner")
           .with_columns((pl.col("fm") * sc["cost_acdc_lcc"]).alias("value")).select(R3 + ["t", "value"]))
    S["slice_objinv_INVTRAN"] = nonzero(fsum_by(pl.concat([nonac, lcc]), R3 + ["t"]))
    bins = (rinv_y.filter(pl.col("trtype") == "ac").select(["r", "rr", "t"]).join(S.tsc_binwidth.select(["r", "rr", "tscbin"]), on=["r", "rr"], how="inner")
            .join(tccfm, on="t", how="inner").select(["r", "rr", "tscbin", "t", pl.col("fm").alias("value")]))
    S["slice_objinv_TRAN_CAPEX_BINS"] = nonzero(bins)
    intra = float(sw["Sw_TransIntraCost"])
    poi_dom = S.r.join(S.tmodel, how="cross")
    S["slice_objinv_INV_POI"] = nonzero(poi_dom.join(tccfm, on="t", how="inner").with_columns((pl.col("fm") * intra * 1000.0).alias("value")).select(["r", "t", "value"]))
    S["slice_objop_INV_POI"] = nonzero(poi_dom.with_columns(pl.lit(intra * 1000.0 * sc["trans_fom_frac"]).alias("value")))
    conv_dom = S.val_converter.filter(pl.col("t") == year)
    S["slice_objinv_INV_CONVERTER"] = nonzero(conv_dom.join(tccfm, on="t", how="inner").with_columns((pl.col("fm") * sc["cost_acdc_vsc"]).alias("value")).select(["r", "t", "value"]))
    S["slice_objop_CAP_CONVERTER"] = nonzero(conv_dom.with_columns(pl.lit(sc["cost_acdc_vsc"] * sc["trans_fom_frac"]).alias("value")))
    spur_xt = S.xfeas.join(S.tmodel, how="cross").select(["x", "t"])
    spur_cost = S.spurline_cost.rename({"value": "cost"})
    if int(sw["Sw_SpurScen"]):
        S["slice_objinv_INV_SPUR"] = nonzero(spur_xt.join(spur_cost, on="x", how="inner")
                                             .with_columns((pl.col("cost") * float(sw["Sw_SpurCostMult"])).alias("value")).select(["x", "t", "value"]))
        S["slice_objop_CAP_SPUR"] = nonzero(spur_xt.join(spur_cost, on="x", how="inner")
                                            .with_columns((pl.col("cost") * sc["trans_fom_frac"]).alias("value")).select(["x", "t", "value"]))
    else:
        S["slice_objinv_INV_SPUR"] = _empty(["x", "t"])
        S["slice_objop_CAP_SPUR"] = _empty(["x", "t"])
    extra = pl.DataFrame({
        "name": ["Sw_VSC", "Sw_TransIntraCost", "Sw_TransGroupContraint", "Sw_TransGroupDerate", "Sw_PRM_NetImportLimit", "Sw_TransInvMaxTypes",
                 "Sw_TransCapMaxEachType", "Sw_TransCapMaxAllTypes", "Sw_OffshoreBackflow", "Sw_SpurScen", "firstyear_trans_nearterm", "trans_fom_frac",
                 "Sw_VSC_ConverterMax", "converter_efficiency_vsc", "Sw_SpurShare", "Sw_SpurCostMult"],
        "value": [float(S.Sw_VSC), intra, float(sw["Sw_TransGroupContraint"]), float(sw["Sw_TransGroupDerate"]), float(sw["Sw_PRM_NetImportLimit"]),
                  float(sw["Sw_TransInvMaxTypes"]), float(sw["Sw_TransCapMaxEachType"]), float(sw["Sw_TransCapMaxAllTypes"]),
                  float(sw["Sw_OffshoreBackflow"]), float(sw["Sw_SpurScen"]), float(near), float(sc["trans_fom_frac"]),
                  float(sw["Sw_VSC_ConverterMax"]), float(sc["converter_efficiency_vsc"]), float(sw["Sw_SpurShare"]), float(sw["Sw_SpurCostMult"])]})
    S["slice_scalars"] = pl.concat([S.slice_scalars, extra])
    return S


def policies(S: Symbols) -> Symbols:
    I = S._inputs
    sw, sc, csw = S.sw, S.sc, S.csw
    year = str(S.year)
    t_all = S.t
    h = S.h
    K3 = ["rpscat", "st", "t"]
    st = I.set("st", ["st"])
    rpscat = I.set("RPSCat", ["rpscat"])
    S["st"] = st
    S["rpscat"] = rpscat
    S["tg"] = I.set("tg", ["tg"])
    S["csapr_cat"] = I.set("csapr_cat", ["csapr_cat"])
    S["csapr_group"] = I.set("csapr_group", ["csapr_group"])
    stfeas = S.r_st.select("st").unique()
    S["stfeas"] = stfeas
    r_st_rps = pl.concat([S.r_st, S.r.with_columns(pl.lit("voluntary").alias("st"))]).unique()
    S["r_st_rps"] = r_st_rps
    all_st_t = rpscat.join(st, how="cross").join(t_all, how="cross").select(K3)

    rpsf = semi(I.par("rps_fraction", ["t", "st", "rpscat"]), t_all, ["t"]).select(K3 + ["value"])
    if not int(sw["Sw_StateRPS_Carveouts"]):
        rpsf = rpsf.filter(~isin("rpscat", {"rps_solar", "rps_wind"}))
    ces = semi(I.par("ces_fraction", ["t", "st"]), t_all, ["t"]).with_columns(pl.lit("ces").alias("rpscat")).select(K3 + ["value"])
    ces_dom = all_st_t.filter(pl.col("rpscat") == "ces")
    recperc = _assign(rpsf, ces, K3, domain=ces_dom)
    rps_all = recperc.filter(pl.col("rpscat") == "rps_all").select(["st", "t", pl.col("value").alias("ra")])
    ces_max = (ces_dom.join(recperc, on=K3, how="left").join(rps_all, on=["st", "t"], how="left")
               .with_columns(pl.max_horizontal(pl.col("value").fill_null(0.0), pl.col("ra").fill_null(0.0)).alias("value")).select(K3 + ["value"]))
    recperc = _assign(recperc, ces_max, K3, domain=ces_dom)
    S["recperc"] = nonzero(recperc).with_columns(gams_round(pl.col("value"), 3).alias("value"))
    rectable = I.par("rectable", ["st", "ast"])
    S["acp_price"] = I.par("acp_prices", ["st", "t"]).with_columns(gams_round(pl.col("value"), 2).alias("value"))
    traded_into = rectable.rename({"st": "ast", "ast": "st"}).select("st").unique()
    recstates = pl.concat([S.recperc.select(K3), rpscat.join(traded_into, how="cross").join(t_all, how="cross").select(K3)]).unique()
    S["recstates"] = recstates
    rt1 = rectable.filter(pl.col("value") == 1.0).select(["st", "ast"])
    rt2 = rectable.filter(pl.col("value") == 2.0).select(["st", "ast"])
    rt1 = rt1.rename({"st": "ast", "ast": "st"})
    rt2 = rt2.rename({"st": "ast", "ast": "st"})
    rectrade = (rt1.join(recstates.rename({"st": "ast"}), on="ast", how="inner").select(["rpscat", "st", "ast", "t"]))
    rb = rt2.join(recstates.filter(pl.col("rpscat") == "rps_all").rename({"st": "ast"}).select(["ast", "t"]), on="ast", how="inner").with_columns(pl.lit("rps_bundled").alias("rpscat"))
    cb = rt2.join(recstates.filter(pl.col("rpscat") == "ces").rename({"st": "ast"}).select(["ast", "t"]), on="ast", how="inner").with_columns(pl.lit("ces_bundled").alias("rpscat"))
    rectrade = pl.concat([rectrade, rb.select(["rpscat", "st", "ast", "t"]), cb.select(["rpscat", "st", "ast", "t"])]).unique()
    S["rectrade"] = rectrade

    banned_rps = I.par("techs_banned_rps", ["i", "st"]).select(["i", "st"])
    banned_ces = I.par("techs_banned_ces", ["i", "st"]).select(["i", "st"])
    vci = S.valcap_i
    re_, wind, pv, pvb = members(S.re), members(S.wind), members(S.pv), members(S.pvb)
    nuclear, hydro, ccs, canada = members(S.nuclear), members(S.hydro), members(S.ccs), members(S.canada)

    def cat(name, techs):
        return anti(one_col(techs, "i").join(vci, on="i", how="semi").join(st, how="cross"), banned_rps, ["i", "st"]).with_columns(pl.lit(name).alias("rpscat"))

    rc_all = cat("rps_all", re_)
    rc_wind = cat("rps_wind", wind)
    rc_solar = cat("rps_solar", pv | pvb)
    ces_base = pl.concat([rc_all.select(["i", "st"]), one_col(nuclear | hydro | ccs | canada, "i").join(st, how="cross")]).unique()
    rc_ces = anti(ces_base.join(vci, on="i", how="semi"), banned_ces, ["i", "st"]).with_columns(pl.lit("ces").alias("rpscat"))
    rpscat_i = pl.concat([x.select(["rpscat", "i", "st"]) for x in (rc_all, rc_wind, rc_solar, rc_ces)]).unique()
    K4 = ["rpscat", "i", "st", "t"]
    rectech = rpscat_i.join(recstates, on=["rpscat", "st"], how="inner").select(K4)
    hyd_rows = rectech.filter(pl.col("i") == "hydro").select(["rpscat", "st", "t"]).join(one_col(hydro, "i").join(vci, on="i", how="semi"), how="cross").select(K4)
    rectech = pl.concat([rectech, hyd_rows]).unique()
    rectech = pl.concat([rectech, rectech.filter(pl.col("rpscat") == "rps_all").with_columns(pl.lit("rps_bundled").alias("rpscat")),
                         rectech.filter(pl.col("rpscat") == "ces").with_columns(pl.lit("ces_bundled").alias("rpscat"))]).unique()
    vol = rpscat.join(one_col(re_, "i"), how="cross").join(t_all, how="cross").with_columns(pl.lit("voluntary").alias("st")).select(K4)
    rectech = pl.concat([rectech, vol]).unique()
    has_gen = S.valgen.join(r_st_rps, on="r", how="inner").select(["i", "st", "t"]).unique()
    rectech = rectech.join(has_gen, on=["i", "st", "t"], how="semi")
    if int(sw["Sw_CCS_NotRecTech"]):
        rectech = rectech.filter(~isin("i", ccs))
    S["rectech"] = rectech
    hydrofrac = I.par("hydrofrac_policy", ["st", "rpscat"])
    K3i = ["rpscat", "i", "st"]
    rtm = rectech.select(K3i).unique().with_columns(pl.lit(1.0).alias("value"))
    hyd_dom = rpscat.join(one_col(hydro, "i").join(vci, on="i", how="semi"), how="cross").join(st, how="cross").select(K3i)
    rtm = _assign(rtm, hyd_dom.join(hydrofrac, on=["st", "rpscat"], how="inner").select(K3i + ["value"]), K3i, domain=hyd_dom)
    for cat_to, cat_from in (("rps_bundled", "rps_all"), ("ces_bundled", "ces")):
        dom = hyd_dom.filter(pl.col("rpscat") == cat_to)
        src = rtm.filter(pl.col("rpscat") == cat_from).select(["i", "st", "value"])
        rtm = _assign(rtm, dom.join(src, on=["i", "st"], how="inner").select(K3i + ["value"]), K3i, domain=dom)
    distloss = sc["distloss"]
    dpv = rtm.filter(isin("i", members(S.distpv))).with_columns(pl.lit(1.0 - distloss).alias("value"))
    rtm = _assign(rtm, dpv, K3i)
    ccs_dom = (one_col(ccs - members(S.beccs), "i").join(st, how="cross").join(pl.DataFrame({"rpscat": ["ces", "ces_bundled"]}), how="cross").select(K3i))
    cri = S.capture_rate_input.filter(pl.col("e") == "co2").select(["i", "value"])
    rtm = _assign(rtm, ccs_dom.join(cri, on="i", how="inner").select(K3i + ["value"]), K3i, domain=ccs_dom)
    S["rpstechmult"] = nonzero(rtm)

    K5 = ["i", "rpscat", "st", "ast", "t"]
    rt_ast = rectech.rename({"st": "ast"})
    rp_ast = S.recperc.rename({"st": "ast"}).select(["rpscat", "ast", "t"])
    m1 = (rectrade.join(rp_ast, on=["rpscat", "ast", "t"], how="semi").join(rectech, on=["rpscat", "st", "t"], how="inner")
          .join(rt_ast, on=["rpscat", "i", "ast", "t"], how="semi").select(K5))
    def bundled(cat_b, cat_p):
        trade = rectrade.filter(pl.col("rpscat") == cat_b)
        perc = S.recperc.filter(pl.col("rpscat") == cat_p).rename({"st": "ast"}).select(["ast", "t"])
        return (trade.join(perc, on=["ast", "t"], how="semi").join(rectech.filter(pl.col("rpscat") == cat_b), on=["rpscat", "st", "t"], how="inner")
                .join(rt_ast.filter(pl.col("rpscat") == cat_b), on=["rpscat", "i", "ast", "t"], how="semi").select(K5))
    m2 = bundled("rps_bundled", "rps_all")
    m3 = bundled("ces_bundled", "ces")
    m4 = (rectech.join(S.recperc.select(K3), on=K3, how="semi").filter(pl.col("st") != "voluntary")
          .with_columns(pl.col("st").alias("ast")).select(K5))
    recmap = pl.concat([m1, m2, m3, m4]).unique()
    hyd_map = recmap.filter(pl.col("i") == "hydro").select(["rpscat", "st", "ast", "t"])
    m5 = (one_col(hydro, "i").join(vci, on="i", how="semi").join(hyd_map, how="cross")
          .join(S.rpstechmult.select(K3i), on=K3i, how="semi")
          .join(S.rpstechmult.rename({"st": "ast"}).select(["rpscat", "i", "ast"]), on=["rpscat", "i", "ast"], how="semi").select(K5))
    recmap = pl.concat([recmap, m5]).unique()
    banned_imp = I.par("techs_banned_imports_rps", ["i", "st"]).select(["i", pl.col("st").alias("ast")])
    drop1 = recmap.filter(isin("rpscat", {"rps_all", "rps_bundled"}) & (pl.col("st") != pl.col("ast"))).join(banned_imp, on=["i", "ast"], how="semi")
    recmap = anti(recmap, drop1, K5)
    recmap = recmap.filter(~((pl.col("ast") == "voluntary") & ~isin("i", re_) & isin("rpscat", {"ces", "ces_bundled"})))
    recmap = recmap.filter(~((pl.col("ast") == "voluntary") & isin("i", canada)))
    S["recmap"] = recmap
    S["rps_oosfrac"] = I.par("oosfrac", ["st"])
    unb = pl.concat([I.par("unbundled_limit_rps", ["st", "t"]).with_columns(pl.lit("rps_all").alias("rpscat")),
                     I.par("unbundled_limit_ces", ["st", "t"]).with_columns(pl.lit("ces").alias("rpscat"))]).select(K3 + ["value"])
    S["rec_unbundled_limit"] = semi(unb, t_all, ["t"])
    S["st_unbundled_limit"] = unb.select(["rpscat", "st"]).unique()
    S["acp_disallowed"] = I.par("acp_disallowed", ["st", "rpscat"])
    S["recstyle"] = I.par("recstyle", ["st", "rpscat"])

    csapr_cap = semi(I.par("csapr_ozone_season", ["st", "csapr_cat", "t"]), t_all, ["t"])
    S["csapr_cap"] = csapr_cap
    budget_st = csapr_cap.filter(pl.col("csapr_cat") == "budget").select("st").unique().join(stfeas, on="st", how="semi")
    ex1 = I.set("csapr_group1_ex", ["st"])
    ex2 = I.set("csapr_group2_ex", ["st"])
    S["csapr_group_st"] = pl.concat([anti(budget_st, ex1, ["st"]).with_columns(pl.lit("cg1").alias("csapr_group")),
                                     anti(budget_st, ex2, ["st"]).with_columns(pl.lit("cg2").alias("csapr_group"))]).select(["csapr_group", "st"])
    qw = pl.DataFrame({"quarter": ["spri", "summ", "fall"], "w": [0.333, 1.0, 0.333]})
    hw = fsum_by(S.frac_h_quarter_weights.join(qw, on="quarter", how="inner").with_columns((pl.col("value") * pl.col("w")).alias("value")).select(["h", "value"]), ["h"])
    S["h_weight_csapr"] = nonzero(semi(hw, h, ["h"]).with_columns(gams_round(pl.col("value"), 3).alias("value")))
    tg_rules = [("wind-ons", members(S.onswind)), ("wind-ofs", members(S.ofswind)), ("pv", (pv | pvb) - members(S.distpv)), ("csp", members(S.csp)),
                ("gas", members(S.gas)), ("coal", members(S.coal)), ("nuclear", nuclear), ("battery", members(S.battery)), ("hydro", hydro),
                ("h2", members(S.h2_gen)), ("geothermal", members(S.geo)), ("biomass", members(S.bio)), ("pumped-hydro", members(S.psh)),
                ("dr_shed", members(S.dr_shed))]
    S["tg_i"] = pl.concat([one_col(techs, "i").with_columns(pl.lit(name).alias("tg")).select(["tg", "i"]) for name, techs in tg_rules]).unique()
    S["queue_limit"] = I.par("queue_limit", ["tg", "r", "t"])
    S["cap_penalty"] = I.par("cap_penalty", ["tg"])
    S["emit_rate_con"] = pl.DataFrame(schema={"e": pl.Utf8, "r": pl.Utf8, "t": pl.Utf8})
    S["emit_rate_limit"] = pl.DataFrame(schema={"e": pl.Utf8, "r": pl.Utf8, "t": pl.Utf8, "value": pl.Float64})

    fy = sc["firstyear_RPS"]
    acp_dom = (S.recperc.filter((pl.col("t") == year) & (yr("t") >= fy)).select(K3)
               .filter(isin("st", members(stfeas) | {"voluntary"})))
    acp_dom = anti(acp_dom, S.acp_disallowed.select(["st", "rpscat"]), ["st", "rpscat"])
    acp = acp_dom.join(S.acp_price, on=["st", "t"], how="inner").select(K3 + ["value"])
    if not int(sw["Sw_StateRPS"]):
        acp = acp.head(0)
    S["slice_objop_ACP_PURCHASES"] = nonzero(acp)
    S["slice_objinv_CAP_ABOVE_LIM"] = nonzero(S.cap_penalty.join(S.r, how="cross").with_columns(pl.lit(year).alias("t")).select(["tg", "r", "t", "value"]))
    extra = pl.DataFrame({
        "name": ["Sw_StateRPS", "Sw_CSAPR", "Sw_RGGI", "Sw_StateCap", "Sw_BankBorrowCap", "Sw_GenMandate", "Sw_GrowthPenalties", "Sw_GrowthAbsCon",
                 "Sw_NoFossilOffsetCDR", "Sw_QueueConstraintYears", "Sw_Upstream", "Sw_AnnualCap", "RGGI_start_yr", "state_cap_start_yr",
                 "csapr_startyr", "distloss", "interconnection_start", "model_builds_start_yr", "Sw_GrowthPenLastYear"],
        "value": [float(sw["Sw_StateRPS"]), float(sw["Sw_CSAPR"]), float(sw["Sw_RGGI"]), float(sw["Sw_StateCap"]), float(sw["Sw_BankBorrowCap"]),
                  float(sw["Sw_GenMandate"]), float(sw["Sw_GrowthPenalties"]), float(sw["Sw_GrowthAbsCon"]), float(sw["Sw_NoFossilOffsetCDR"]),
                  float(sw["Sw_QueueConstraintYears"]), float(sw["Sw_Upstream"]), float(sw["Sw_AnnualCap"]), float(sc["RGGI_start_yr"]),
                  float(sc["state_cap_start_yr"]), float(sc["csapr_startyr"]), float(distloss), float(sc["interconnection_start"]),
                  float(S.model_builds_start_yr), float(sw["Sw_GrowthPenLastYear"])]})
    S["slice_scalars"] = pl.concat([S.slice_scalars, extra])
    return S


def growth(S: Symbols, state: dict[str, pl.DataFrame] | None) -> Symbols:
    I = S._inputs
    sw = S.sw
    year = str(S.year)
    yint = int(S.year)
    years = S.years
    GB = ["gbin", "st", "tg", "t"]
    ST3 = ["st", "tg", "t"]
    gbin = I.set("gbin", ["gbin"])
    S["gbin"] = gbin
    S["growth_penalty"] = I.par("growth_penalty", ["gbin"])
    gbin_min = I.par("gbin_min", ["tg"])
    S["gbin_min"] = gbin_min
    size_mult = I.par("growth_bin_size_mult", ["gbin"])
    S["growth_bin_size_mult"] = size_mult
    mult1 = float(size_mult.filter(pl.col("gbin") == "gbin1")["value"][0])
    stfeas = S.stfeas
    tg = S.tg
    S["valinv_tg"] = (S.valinv_irt.join(S.r_st, on="r", how="inner").join(S.tg_i, on="i", how="inner").select(ST3).unique())
    on = int(sw["Sw_GrowthPenalties"]) != 0
    first = yint == years[0]
    init = (gbin.join(stfeas, how="cross").join(gbin_min, how="cross")
            .with_columns(pl.lit(year).alias("t")).select(GB + ["value"]))
    S["last_year_max_growth"] = _empty(ST3)
    if first or not on:
        S["growth_bin_limit"] = nonzero(init) if first else _empty(GB)
    else:
        if state is None:
            raise ValueError("growth bin limits for a year after the first need the prior-year investment levels (state)")
        prev_y = max(y for y in years if y < yint)
        earlier = [y for y in years if y < prev_y]
        prev2_y = max(earlier) if earlier else 0
        inv_prev = state["state_INV"].filter(pl.col("tt") == str(prev_y))
        valinv_prev = S.valinv.filter(pl.col("t") == str(prev_y)).rename({"t": "tt"})
        numer = (inv_prev.join(valinv_prev, on=["i", "v", "r", "tt"], how="semi").join(S.r_st, on="r", how="inner")
                 .join(S.tg_i, on="i", how="inner").group_by(["st", "tg"]).agg(pl.col("value").sum().alias("num")))
        allt = sorted(int(x) for x in S.allt["allt"].to_list())
        denom = 0.0
        for a in allt:
            if prev2_y < a <= prev_y:
                denom = denom + mult1 ** (a - prev2_y - 1)
        comp = mult1 ** ((prev_y - prev2_y) - 1)
        lymg = numer.with_columns(((pl.col("num") / denom) * comp).alias("value")).select(["st", "tg", "value"])
        S["last_year_max_growth"] = nonzero(lymg.with_columns(pl.lit(year).alias("t")).select(ST3 + ["value"]))
        gap = yint - prev_y
        growth_sum = pl.lit(0.0)
        for a in allt:
            if prev_y < a <= yint:
                growth_sum = growth_sum + pl.col("value") * (mult1 ** (a - prev_y))
        current = lymg.with_columns((growth_sum / gap).alias("value"))
        prior = state["state_growth_bin_limit"].filter(pl.col("gbin") == "gbin1").select(["st", "tg", "value"])
        init1 = init.filter(pl.col("gbin") == "gbin1").select(["st", "tg", "value"])
        domain = stfeas.join(tg, how="cross").with_columns(pl.lit(0.0).alias("value"))
        best = (pl.concat([domain, current, prior, init1]).group_by(["st", "tg"]).agg(pl.col("value").max()))
        floored = (best.join(gbin_min.rename({"value": "gm"}), on="tg", how="left")
                   .with_columns(pl.when(pl.col("value") < pl.col("gm").fill_null(0.0)).then(pl.col("gm")).otherwise(pl.col("value")).alias("value"))
                   .select(["st", "tg", "value"]))
        bin1 = floored.with_columns(pl.lit("gbin1").alias("gbin"))
        others = (floored.join(size_mult.filter(pl.col("gbin") != "gbin1").rename({"value": "m"}), how="cross")
                  .with_columns((pl.col("value") * (pl.col("m") - mult1)).alias("value")))
        gbl = pl.concat([bin1.select(["gbin", "st", "tg", "value"]), others.select(["gbin", "st", "tg", "value"])])
        gbl = nonzero(gbl).with_columns(gams_round(pl.col("value"), 0).alias("value"), pl.lit(year).alias("t")).select(GB + ["value"])
        S["growth_bin_limit"] = nonzero(gbl)

    IST = ["i", "st", "t"]
    vir = (S.valinv_irt.filter(pl.col("t") == year).join(S.r_st, on="r", how="inner").join(stfeas, on="st", how="semi"))
    if on:
        ccfm = S.cost_cap_fin_mult.filter(pl.col("t") == year).rename({"value": "fin"})
        cc = S.cost_cap.filter(pl.col("t") == year).rename({"value": "cc"})
        scc = members(S.sccapcosttech)
        plain = vir.filter(~isin("i", scc))
        cg_plain = (plain.join(ccfm, on=["i", "r", "t"], how="inner").join(cc, on=["i", "t"], how="inner")
                    .with_columns((pl.col("fin") * pl.col("cc")).alias("value")).group_by(IST).agg(pl.col("value").min()))
        rfm = S.rsc_fin_mult.filter(pl.col("t") == year).rename({"value": "rfm"})
        cost = S.m_rsc_dat.filter(pl.col("sc_cat") == "cost").select(["r", "i", "rscbin", pl.col("value").alias("cost")])
        sc_rows = vir.filter(isin("i", scc))
        cg_sc = (sc_rows.join(rfm, on=["i", "r", "t"], how="inner").join(S.rscbin, how="cross")
                 .join(cost, on=["r", "i", "rscbin"], how="left")
                 .with_columns((pl.col("rfm") * pl.col("cost").fill_null(0.0)).alias("value")).group_by(IST).agg(pl.col("value").min()))
        cg = pl.concat([cg_plain, cg_sc])
        missing = anti(vir.select(IST).unique(), cg, IST)
        if missing.height:
            raise ValueError(f"cost_growth is undefined (GAMS smin over an empty set) for {missing.head(5).rows()}")
        S["cost_growth"] = nonzero(cg.with_columns(gams_round(pl.col("value"), 3).alias("value")))
    else:
        S["cost_growth"] = _empty(IST)
    prev = [y for y in years if y < yint]
    gap_obj = yint - (max(prev) if prev else 0)
    last = float(sw["Sw_GrowthPenLastYear"])
    mbs = float(S.model_builds_start_yr)
    coef = (vir.select(IST).unique().join(gbin, how="cross")
            .join(S.cost_growth.rename({"value": "cg"}), on=IST, how="inner")
            .join(S.growth_penalty.rename({"value": "gp"}), on="gbin", how="inner")
            .with_columns((pl.col("cg") * pl.col("gp") * float(gap_obj)).alias("value")).select(GB[:1] + IST + ["value"]))
    if not (on and mbs <= yint <= last):
        coef = coef.head(0)
    S["slice_objinv_GROWTH_BIN"] = nonzero(coef)
    return S


def hydrogen(S: Symbols, stress_year: str) -> Symbols:
    I = S._inputs
    sw, sc, csw = S.sw, S.sc, S.csw
    year = str(S.year)
    t_all = S.t
    h = S.h
    valcap = S.valcap
    valcap_y = valcap.filter(pl.col("t") == year)
    initv, newv = members(S.initv), members(S.newv)
    sw_h2 = int(sw["Sw_H2"])
    sw_prod = 1 if (sw_h2 or int(sw["Sw_DAC"]) or int(sw["Sw_DAC_Gas"])) else 0

    S["p"] = I.set("p", ["p"])
    S["i_p"] = I.set("i_p", ["i", "p"])
    cc = I.par("consume_char", ["i", "t", "cat"])
    eff = cc.filter(pl.col("cat") == "ele_efficiency").select(["i", "t", pl.col("value").alias("eff")])
    h2 = members(S.h2)
    h2_new = (valcap.filter(isin("i", h2) & isin("v", newv)).select(["i", "v", "r", "t"]))
    avg = (S.ivt.rename({"t": "tt"}).filter(isin("v", newv)).join(eff.rename({"t": "tt"}), on=["i", "tt"], how="inner")
           .group_by(["i", "v"]).agg(pl.col("eff").sum()).join(S.countnc.rename({"value": "n"}), on=["i", "v"], how="inner")
           .with_columns((1.0 / (pl.col("eff") / pl.col("n"))).alias("value")).select(["i", "v", "value"]))
    hcr = h2_new.join(avg, on=["i", "v"], how="inner").select(V4 + ["value"])
    start = str(S.years[0])
    eff0 = eff.filter(pl.col("t") == start).select(["i", pl.col("eff").alias("e0")])
    hcr_init = (valcap.filter(isin("i", h2) & isin("v", initv)).join(eff0, on="i", how="inner")
                .with_columns((1.0 / pl.col("e0")).alias("value")).select(V4 + ["value"]))
    pcr = pl.concat([hcr, hcr_init])
    if members(S.dac):
        raise NotImplementedError("dac conversion rates are not ported")
    S["prod_conversion_rate"] = nonzero(pcr).with_columns(gams_round(pl.col("value"), 6).alias("value"))
    hci = (1.0 / sc["h2_energy_intensity"]) * (1.0 / sc["lb_per_tonne"]) * 1e6
    S["h2_combustion_intensity"] = hci

    demand = I.par("h2_exogenous_demand", ["p", "t"]).with_columns((pl.col("value") * 1e6).alias("value"))
    demand = semi(demand, t_all, ["t"])
    h2_gen_fy = S.firstyear.filter(isin("i", members(S.h2_gen)))["value"]
    h2_gen_firstyear = float(h2_gen_fy.min()) if h2_gen_fy.len() else float("inf")
    dem_years = fsum_by(demand.select(["t", "value"]), ["t"]).filter(pl.col("value") != 0.0)["t"].cast(pl.Int64)
    h2_demand_start = float(dem_years.min()) if dem_years.len() else float("inf")
    if h2_gen_firstyear < h2_demand_start:
        h2_demand_start = h2_gen_firstyear
    share = I.par("h2_ba_share", ["r", "t"]).rename({"value": "share"})
    reg = (semi(share, S.tmodel_new, ["t"]).join(demand.rename({"value": "dem"}), on="t", how="inner").join(h, how="cross")
           .with_columns((pl.col("share") * pl.col("dem") / 8760.0).alias("value")).select(["r", "p", "h", "t", "value"]))
    S["h2_exogenous_demand_regional"] = nonzero(reg)
    if int(sw["Sw_H2_Transport"]):
        raise NotImplementedError("hydrogen pipeline routes (Sw_H2_Transport) are not ported")
    S["h2_routes"] = pl.DataFrame(schema={"r": pl.Utf8, "rr": pl.Utf8})
    S["h2_routes_inv"] = S.h2_routes
    S["h2_stor"] = I.set("h2_stor", ["h2_stor"])
    S["h2_stor_r"] = I.set("h2_storage_rb", ["h2_stor", "r"])
    hcost = I.par("h2_transport_and_storage_costs", ["h2_st", "t", "cat"])
    mult_s = I.par("h2_cap_cost_mult_storage", ["t"]).rename({"value": "m"})
    scap = (hcost.filter(pl.col("cat") == "cost_cap").rename({"h2_st": "h2_stor"}).join(S.h2_stor, on="h2_stor", how="semi")
            .join(mult_s, on="t", how="left").with_columns((pl.col("value") * pl.col("m").fill_null(0.0)).alias("value")).select(["h2_stor", "t", "value"]))
    S["cost_h2_storage_cap"] = scap.with_columns(pl.when(isin("t", set(t_all["t"]))).then(gams_round(pl.col("value"), 2)).otherwise(pl.col("value")).alias("value"))
    S["cost_h2_storage_fom"] = (hcost.filter(pl.col("cat") == "fom").rename({"h2_st": "h2_stor"}).join(S.h2_stor, on="h2_stor", how="semi")
                                .select(["h2_stor", "t", "value"]))
    S["cost_h2_transport_cap"] = pl.DataFrame(schema={"r": pl.Utf8, "rr": pl.Utf8, "t": pl.Utf8, "value": pl.Float64})
    S["cost_h2_transport_fom"] = S.cost_h2_transport_cap
    S["h2_network_load"] = hcost.filter(pl.col("cat") == "electric_load").select(["h2_st", "t", "value"])
    fuel = cc.filter(pl.col("cat") == "gas_efficiency").select(["i", "t", pl.col("value").alias("ge")])
    fuel_avg = (S.ivt.rename({"t": "tt"}).filter(isin("v", newv)).join(fuel.rename({"t": "tt"}), on=["i", "tt"], how="inner")
                .group_by(["i", "v"]).agg(pl.col("ge").sum()).join(S.countnc.rename({"value": "n"}), on=["i", "v"], how="inner")
                .with_columns((1000.0 * (pl.col("ge") / pl.col("n"))).alias("fc")).select(["i", "v", "fc"]))
    fc_new = h2_new.join(fuel_avg, on=["i", "v"], how="inner")
    fc_init = (valcap.filter(isin("i", h2) & isin("v", initv)).join(fuel.filter(pl.col("t") == start).select(["i", "ge"]), on="i", how="inner")
               .with_columns((1000.0 * pl.col("ge")).alias("fc")).select(V4 + ["fc"]))
    fuel_cost = pl.concat([fc_new.select(V4 + ["fc"]), fc_init])
    deflator = dict(zip(*[I.par("deflator", ["allt"])[c] for c in ("allt", "value")]))
    vom = (cc.filter(pl.col("cat") == "vom").filter(isin("i", h2)).with_columns((deflator["2016"] * pl.col("value") * 1000.0).alias("vom"))
           .select(["i", "t", "vom"]))
    stor_tran = cc.filter(pl.col("cat") == "stortran_adder").select(["i", "t", pl.col("value").alias("st")])
    if sw_h2 == 1:
        raise NotImplementedError("Sw_H2=1 (national hydrogen demand, stortran adder) is not ported")
    cost_prod = (valcap.filter(isin("i", h2)).join(fuel_cost, on=V4, how="left").join(vom, on=["i", "t"], how="left")
                 .with_columns((pl.col("fc").fill_null(0.0) + pl.col("vom").fill_null(0.0)).alias("value")).select(V4 + ["value"]))
    S["cost_prod"] = nonzero(cost_prod).with_columns(gams_round(pl.col("value"), 2).alias("value"))

    ptc_in = I.par("h2_ptc_in", ["i", "v", "t"])
    h2_ptc = valcap.join(ptc_in, on=["i", "v", "t"], how="inner").select(V4 + ["value"])
    if not int(sw["Sw_H2_PTC"]):
        h2_ptc = h2_ptc.filter(pl.col("i") != "electrolyzer")
    S["h2_ptc"] = nonzero(h2_ptc)
    S["h2_ptc_years"] = S.tmodel_new.join(S.h2_ptc.select("t").unique(), on="t", how="semi")
    S["h2ptcreg"] = I.set("h2ptcreg", ["h2ptcreg"])
    S["r_h2ptcreg"] = S.hierarchy.select(["r", "h2ptcreg"]).unique()
    gen_ptc = I.set("i_h2_ptc_gen", ["i"])
    fyv = S.firstyear_v.rename({"value": "fyv"})
    S["valgen_h2ptc"] = (valcap.filter(isin("v", newv)).join(gen_ptc, on="i", how="semi").join(fyv, on=["i", "v"], how="inner")
                         .filter(pl.col("fyv") >= sc["h2_ptc_firstyear"]).select(V4))
    S["crf_h2_incentive"] = I.par("crf_h2_incentive", ["t"])
    S["crf"] = I.par("crf", ["t"])
    S["actualszn"] = I.set("rep__set_actualszn", ["actualszn"])
    S["nextszn"] = I.set("nextszn", ["actualszn", "actualsznn"])
    S["h_actualszn"] = semi(_rep_stress_set(I, "h_actualszn", ["h", "actualszn"], stress_year), h, ["h"])

    smr = members(S.smr)
    rows = []
    E6 = ["etype", "e", "i", "t"]
    for tech in ("smr", "smr_ccs"):
        if tech in members(S.i):
            v = sc["smr_co2_intensity"] * ((1.0 - sc["smr_capture_rate"]) if tech == "smr_ccs" else 1.0)
            rows.append(t_all.with_columns(pl.lit("process").alias("etype"), pl.lit("co2").alias("e"), pl.lit(tech).alias("i"), pl.lit(v).alias("value")).select(E6 + ["value"]))
    leak = I.par("methane_leakage_rate", ["t"]).rename({"value": "leak"})
    smr_methane_rate = sc["smr_co2_intensity"] * sc["molWeightCH4"] / sc["molWeightCO2"]
    S["smr_methane_rate"] = smr_methane_rate
    if smr:
        rows.append(one_col(smr, "i").join(semi(leak, t_all, ["t"]), how="cross")
                    .with_columns(pl.lit("upstream").alias("etype"), pl.lit("ch4").alias("e"),
                                  (smr_methane_rate * pl.col("leak") / (1.0 - pl.col("leak"))).alias("value")).select(E6 + ["value"]))
    h2leak = I.par("h2_leakage_rate", ["i"]).rename({"value": "lk"})
    rows.append(one_col(h2, "i").join(h2leak, on="i", how="inner").join(t_all, how="cross")
                .with_columns(pl.lit("process").alias("etype"), pl.lit("h2").alias("e"), (pl.col("lk") / (1.0 - pl.col("lk"))).alias("value")).select(E6 + ["value"]))
    S["prod_emit_rate"] = nonzero(pl.concat(rows)) if rows else pl.DataFrame(schema={c: pl.Utf8 for c in E6} | {"value": pl.Float64})

    hours = S.hours.rename({"value": "hours"})
    h_rep = S.h_rep
    prod_dom = (valcap_y.filter(isin("i", members(S.consume))).join(S.i_p, on="i", how="inner").join(h_rep, how="cross")
                .select(["p", "i", "v", "r", "h", "t"]))
    P6 = ["p", "i", "v", "r", "h", "t"]
    terms = []
    cp = S.cost_prod.filter(pl.col("t") == year).rename({"value": "cp"})
    terms.append(prod_dom.filter(isin("i", h2 | members(S.dac))).join(cp, on=V4, how="inner").join(hours, on="h", how="inner")
                 .with_columns((pl.col("hours") * pl.col("cp")).alias("value")).select(P6 + ["value"]))
    if sw_h2:
        intra = float(sw["Sw_H2_IntraReg_Transport"]) * 1e3
        terms.append(prod_dom.filter((pl.col("p") == "h2") & isin("v", newv)).join(hours, on="h", how="inner")
                     .with_columns((pl.col("hours") * intra).alias("value")).select(P6 + ["value"]))
        if "smr_ccs" in members(S.i) and not int(sw["Sw_CO2_Detail"]):
            terms.append(prod_dom.filter(pl.col("i") == "smr_ccs").join(hours, on="h", how="inner")
                         .with_columns((((pl.col("hours") * sc["smr_capture_rate"]) * sc["smr_co2_intensity"]) * float(sw["Sw_CO2_Storage"])).alias("value")).select(P6 + ["value"]))
    if int(sw["Sw_H2_PTC"]) and sw_h2 and year in set(S.h2_ptc_years["t"]) and int(year) >= h2_demand_start:
        crf = S.crf.rename({"value": "crf"})
        crfh = S.crf_h2_incentive.rename({"value": "crfh"})
        ptc = S.h2_ptc.filter((pl.col("i") == "electrolyzer") & (pl.col("t") == year)).rename({"value": "ptc"})
        terms.append(prod_dom.filter((pl.col("p") == "h2") & (pl.col("i") == "electrolyzer")).join(ptc, on=V4, how="inner")
                     .join(hours, on="h", how="inner").join(crf, on="t", how="inner").join(crfh, on="t", how="inner")
                     .with_columns((-(((pl.col("hours") * (pl.col("crf") / pl.col("crfh"))) * pl.col("ptc")) * 1e3)).alias("value")).select(P6 + ["value"]))
    if int(sw["Sw_RetailAdder"]):
        raise NotImplementedError("Sw_RetailAdder on PRODUCE is not ported")
    S["slice_objop_PRODUCE"] = nonzero(fsum_by(pl.concat(terms), P6)) if sw_prod else pl.DataFrame(schema={c: pl.Utf8 for c in P6} | {"value": pl.Float64})
    stor_dom = S.h2_stor_r.with_columns(pl.lit(year).alias("t"))
    S["slice_objinv_H2_STOR_INV"] = nonzero(stor_dom.join(S.cost_h2_storage_cap, on=["h2_stor", "t"], how="inner").select(["h2_stor", "r", "t", "value"])) if sw_h2 == 2 else stor_dom.head(0).with_columns(pl.lit(0.0).alias("value"))
    S["slice_objop_H2_STOR_CAP"] = nonzero(stor_dom.join(S.cost_h2_storage_fom, on=["h2_stor", "t"], how="inner").select(["h2_stor", "r", "t", "value"])) if sw_h2 == 2 else stor_dom.head(0).with_columns(pl.lit(0.0).alias("value"))
    S["slice_objinv_H2_TRANSPORT_INV"] = pl.DataFrame(schema={"r": pl.Utf8, "rr": pl.Utf8, "t": pl.Utf8, "value": pl.Float64})
    S["slice_objop_H2_TRANSPORT_INV"] = S.slice_objinv_H2_TRANSPORT_INV
    extra = pl.DataFrame({
        "name": ["Sw_H2", "Sw_Prod", "Sw_H2_PTC", "Sw_H2_StorTimestep", "Sw_H2_MinStorHours", "Sw_H2_CompressorLoad", "Sw_H2_Transport",
                 "h2_demand_start", "h2_storage_duration", "h2_combustion_intensity", "h2_tranloss", "h2_ptc_temporal_match_year",
                 "Sw_LoadSiteCF", "Sw_Mingen", "Sw_PRM_CapCredit", "Sw_itlgrpConstraint", "Sw_CO2_Detail", "Sw_CCSFLEX_BYP", "Sw_CCSFLEX_STO",
                 "Sw_CCSFLEX_DAC", "Sw_GasCurve"],
        "value": [float(sw_h2), float(sw_prod), float(sw["Sw_H2_PTC"]), float(sw["Sw_H2_StorTimestep"]), float(sw["Sw_H2_MinStorHours"]),
                  float(sw["Sw_H2_CompressorLoad"]), float(sw["Sw_H2_Transport"]), float(h2_demand_start), float(sc["h2_storage_duration"]),
                  float(hci), float(sc["h2_tranloss"]), float(sc["h2_ptc_temporal_match_year"]),
                  float(sw["Sw_LoadSiteCF"]), float(sw["Sw_Mingen"]), float(sw["Sw_PRM_CapCredit"]), float(sw["Sw_itlgrpConstraint"]),
                  float(sw["Sw_CO2_Detail"]), float(sw["Sw_CCSFLEX_BYP"]), float(sw["Sw_CCSFLEX_STO"]), float(sw["Sw_CCSFLEX_DAC"]),
                  float(sw["Sw_GasCurve"])]})
    S["slice_scalars"] = pl.concat([S.slice_scalars, extra])
    return S
