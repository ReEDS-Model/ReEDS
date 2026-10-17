from __future__ import annotations

import math

import polars as pl

from .derive import Symbols, anti, fsum_by, gams_round, isin, members, nonzero, one_col, semi
from .derive_capacity import V4, _assign, yr


def _par_over(domain: pl.DataFrame, value: float) -> pl.DataFrame:
    return domain.with_columns(pl.lit(float(value)).alias("value"))


def _avg_over_ivt(S: Symbols, table: pl.DataFrame, keys: list[str]) -> pl.DataFrame:
    """sum{tt$ivt(i,newv,tt), table(i,tt)} / countnc(i,newv) -> (i, v, value)."""
    joined = S.ivt.rename({"t": "tt"}).join(table.rename({"t": "tt"}), on=["i", "tt"], how="inner")
    summed = joined.group_by(["i", "v"]).agg(pl.col("value").sum())
    return (summed.join(S.countnc.rename({"value": "n"}), on=["i", "v"], how="inner")
            .with_columns((pl.col("value") / pl.col("n")).alias("value")).select(["i", "v", "value"]))


def gas_curve(S: Symbols) -> Symbols:
    I = S._inputs
    sc, csw = S.sc, S.csw
    year = str(S.year)
    t_all = S.t
    cendiv = I.set("cendiv", ["cendiv"])
    fuelbin = I.set("fuelbin", ["fuelbin"])
    S["cendiv"] = cendiv
    S["fuelbin"] = fuelbin
    S["r_cendiv"] = S.hierarchy.select(["r", "cendiv"]).unique()
    t_vals = sorted(int(x) for x in t_all["t"].to_list())
    if t_vals != list(range(t_vals[0], t_vals[-1] + 1)):
        raise ValueError("the t set must be consecutive years for the two-year gas lag (t-2) to be a year offset")
    supply = semi(I.par("ng_demand_elec", ["cendiv", "allt"]).rename({"allt": "t"}), t_all, ["t"])
    supply = nonzero(semi(supply, cendiv, ["cendiv"]).with_columns((1e9 * pl.col("value")).alias("value")))
    S["gassupply_ele"] = supply
    usage = fsum_by(supply.select(["t", "value"]), ["t"])
    S["gasusage_national"] = nonzero(usage)
    sector = csw["GSw_GasSector"]
    if sector == "energy_sector":
        beta0 = I.par("cd_beta0_allsector", ["cendiv"])
        nat_beta_val = sc["nat_beta_energy"]
    elif sector == "electric_sector":
        beta0 = I.par("cd_beta0", ["cendiv"])
        nat_beta_val = sc["nat_beta_nonenergy"]
    else:
        raise ValueError(f"GSw_GasSector={sector!r} is not electric_sector or energy_sector")
    t_after = t_all.filter(yr("t") > 2010)
    cd_beta = nonzero(semi(beta0, cendiv, ["cendiv"]).join(t_after, how="cross").select(["cendiv", "t", "value"]))
    nat_beta = t_after.with_columns(pl.lit(float(nat_beta_val)).alias("value"))
    S["cd_beta"] = cd_beta
    S["nat_beta"] = nat_beta
    n = fuelbin.height
    width = (sc["normfuelbinmax"] - sc["normfuelbinmin"]) / (n - 2)
    bot = sc["normfuelbinmin"]
    top = sc["topfuelbinwidth"]
    ordf = fuelbin.with_row_index("ord", offset=1).with_columns(pl.col("ord").cast(pl.Float64))
    binmult = pl.when(pl.col("ord") == 1).then(bot).when(pl.col("ord") == n).then(top).otherwise(width)
    qq_frac = bot + (pl.col("ord") - 1) * width - width / 2
    dom_reg = ordf.join(cendiv, how="cross").join(t_all, how="cross")
    reg = (dom_reg.join(supply.rename({"value": "sup"}), on=["cendiv", "t"], how="left")
           .join(cd_beta.rename({"value": "beta"}), on=["cendiv", "t"], how="left")
           .with_columns(pl.col("sup").fill_null(0.0), pl.col("beta").fill_null(0.0)))
    gbw_reg = reg.with_columns((pl.col("sup") * binmult).alias("value"))
    gbw_reg = gbw_reg.with_columns(pl.when(pl.col("value") < 10.0).then(10.0).otherwise(pl.col("value")).alias("value"))
    S["gasbinwidth_regional"] = gbw_reg.select(["fuelbin", "cendiv", "t", "value"])
    gbp_reg = (reg.with_columns((pl.col("sup") * qq_frac).alias("qq"))
               .with_columns(gams_round((pl.col("beta") * (pl.col("qq") - pl.col("sup"))) / 1e9, 5).alias("value")))
    S["gasbinp_regional"] = nonzero(gbp_reg.select(["fuelbin", "cendiv", "t", "value"]))
    dom_nat = ordf.join(t_all, how="cross")
    nat = (dom_nat.join(usage.rename({"value": "use"}), on="t", how="left").join(nat_beta.rename({"value": "beta"}), on="t", how="left")
           .with_columns(pl.col("use").fill_null(0.0), pl.col("beta").fill_null(0.0)))
    S["gasbinwidth_national"] = nonzero(nat.with_columns((pl.col("use") * binmult).alias("value")).select(["fuelbin", "t", "value"]))
    gbp_nat = (nat.with_columns((pl.col("use") * qq_frac).alias("qq"))
               .with_columns(gams_round(pl.col("beta") * (pl.col("qq") - pl.col("use")) / 1e9, 5).alias("value")))
    S["gasbinp_national"] = nonzero(gbp_nat.select(["fuelbin", "t", "value"]))
    alpha = semi(I.par("alpha", ["allt", "cendiv"]).rename({"allt": "t"}), t_all, ["t"])
    lag = t_all.with_columns((yr("t") - 2).cast(pl.Int64).cast(pl.Utf8).alias("tlag"))
    gmt = (cendiv.join(t_all, how="cross").join(lag, on="t", how="inner")
           .join(alpha.rename({"value": "alpha"}), on=["t", "cendiv"], how="left")
           .join(nat_beta.rename({"value": "nb"}), on="t", how="left")
           .join(usage.rename({"value": "use", "t": "tlag"}), on="tlag", how="left")
           .join(cd_beta.rename({"value": "cb"}), on=["cendiv", "t"], how="left")
           .join(supply.rename({"value": "sup", "t": "tlag"}), on=["cendiv", "tlag"], how="left")
           .with_columns([pl.col(c).fill_null(0.0) for c in ["alpha", "nb", "use", "cb", "sup"]])
           .with_columns((pl.col("alpha") + pl.col("nb") * pl.col("use") / 1e9 + pl.col("cb") * pl.col("sup") / 1e9).alias("value")))
    S["gasmultterm"] = nonzero(gmt.select(["cendiv", "t", "value"])).with_columns(gams_round(pl.col("value"), 3).alias("value"))
    weights = semi(I.par("cendivweights", ["r", "cendiv"]), cendiv, ["cendiv"])
    S["cendiv_weights"] = nonzero(weights).with_columns(gams_round(pl.col("value"), 3).alias("value"))
    S["gasmult_r"] = nonzero(fsum_by(S.cendiv_weights.rename({"value": "w"}).join(S.gasmultterm, on="cendiv", how="inner")
                                     .with_columns((pl.col("value") * pl.col("w")).alias("value")).select(["r", "t", "value"]), ["r", "t"]))
    S["slice_objop_VGASBINQ_REGIONAL"] = S.gasbinp_regional.filter(pl.col("t") == year)
    S["slice_objop_VGASBINQ_NATIONAL"] = S.gasbinp_national.filter(pl.col("t") == year)
    return S


def costs(S: Symbols) -> Symbols:
    I = S._inputs
    sw, sc, csw = S.sw, S.sc, S.csw
    t_all = S.t
    startyear = str(int(csw["startyear"]))
    ban = members(S.ban)
    valcap, valgen, valinv = S.valcap, S.valgen, S.valinv
    initv, newv = members(S.initv), members(S.newv)
    upgrade = members(S.upgrade)
    upgrade_to, upgrade_from = S.upgrade_to, S.upgrade_from
    upgrades_on = int(sw["Sw_Upgrades"])
    uchar_year = str(int(sw["Sw_UpgradeChar_Year"]))
    unitspec = members(I.set("unitspec_upgrades", ["i"]))

    def nems_domain(techs: set) -> pl.DataFrame:
        return one_col(techs, "i").join(S.initv, how="cross").join(S.r, how="cross").join(t_all, how="cross").select(V4)

    def from_to(table: pl.DataFrame, keys: list[str], link: pl.DataFrame) -> pl.DataFrame:
        other = [k for k in keys if k != "i"]
        return (link.join(table.rename({"i": "ii"}), on="ii", how="inner")
                .group_by(["i"] + other).agg(pl.col("value").sum()).select(["i"] + other + ["value"]))

    # ------------------------------------------------------------- plant characteristics
    pc0 = I.par("plantcharout", ["i", "allt", "plantcat"]).rename({"allt": "t"})
    deflator = dict(zip(*[I.par("deflator", ["allt"])[c] for c in ("allt", "value")]))
    consume0 = I.par("consume_char", ["i", "allt", "cat"]).rename({"allt": "t"})
    consume0 = semi(consume0, t_all, ["t"])
    smr = members(S.smr)
    if smr:
        eff = consume0.filter(isin("i", smr) & (pl.col("cat") == "ele_efficiency")).select(["i", "t", pl.col("value").alias("eff")])
        for cat, out in (("cost_cap", "capcost"), ("fom", "fom")):
            dom = one_col(smr, "i").join(t_all, how="cross").with_columns(pl.lit(out).alias("plantcat")).select(["i", "t", "plantcat"])
            rows = (consume0.filter(isin("i", smr) & (pl.col("cat") == cat)).join(eff, on=["i", "t"], how="left")
                    .with_columns(pl.lit(out).alias("plantcat")))
            if rows.filter(pl.col("eff").is_null() | (pl.col("eff") == 0.0)).height:
                raise ValueError("consume_char ele_efficiency is missing or zero for an SMR technology")
            rows = rows.with_columns((pl.lit(deflator["2018"]) * pl.col("value") / pl.col("eff") * 24000.0
                                      * (1.0 - sc["forced_outage_rate_h2_smr"])).alias("value"))
            pc0 = _assign(pc0, rows.select(["i", "t", "plantcat", "value"]), ["i", "t", "plantcat"], domain=dom)
    dac_t = t_all
    ele = consume0.filter((pl.col("i") == "electrolyzer") & (pl.col("cat") == "cost_cap")).with_columns(
        (pl.lit(deflator["2022"]) * pl.col("value") * 1000.0).alias("value"), pl.lit("capcost").alias("plantcat"))
    fom = consume0.filter((pl.col("i") == "electrolyzer") & (pl.col("cat") == "fom")).with_columns(
        (pl.lit(deflator["2022"]) * pl.col("value") * 1000.0).alias("value"), pl.lit("fom").alias("plantcat"))
    pc0 = _assign(pc0, ele.select(["i", "t", "plantcat", "value"]), ["i", "t", "plantcat"],
                  domain=t_all.with_columns(pl.lit("electrolyzer").alias("i"), pl.lit("capcost").alias("plantcat")).select(["i", "t", "plantcat"]))
    pc0 = _assign(pc0, fom.select(["i", "t", "plantcat", "value"]), ["i", "t", "plantcat"],
                  domain=t_all.with_columns(pl.lit("electrolyzer").alias("i"), pl.lit("fom").alias("plantcat")).select(["i", "t", "plantcat"]))
    dac = semi(I.par("consumechardac", ["i", "allt", "consumecat"]).rename({"allt": "t"}), t_all, ["t"])
    dac_rate = dac.filter((pl.col("i") == "dac") & (pl.col("consumecat") == "conversionrate")).select(["t", pl.col("value").alias("rate")])
    if "dac" not in members(S.dac):
        dac_rate = dac_rate.with_columns(pl.lit(0.0).alias("rate"))
    for cat, out in (("capcost", "capcost"), ("vom", "vom")):
        rows = (dac.filter((pl.col("i") == "dac") & (pl.col("consumecat") == cat)).join(dac_rate, on="t", how="left")
                .with_columns((pl.col("value") * pl.col("rate").fill_null(0.0)).alias("value"), pl.lit(out).alias("plantcat"))
                .select(["i", "t", "plantcat", "value"]))
        pc0 = _assign(pc0, rows, ["i", "t", "plantcat"],
                      domain=t_all.with_columns(pl.lit("dac").alias("i"), pl.lit(out).alias("plantcat")).select(["i", "t", "plantcat"]))
    rows = dac.filter((pl.col("i") == "dac") & (pl.col("consumecat") == "fom")).with_columns(pl.lit("fom").alias("plantcat")).select(["i", "t", "plantcat", "value"])
    pc0 = _assign(pc0, rows, ["i", "t", "plantcat"],
                  domain=t_all.with_columns(pl.lit("dac").alias("i"), pl.lit("fom").alias("plantcat")).select(["i", "t", "plantcat"]))
    dac_gas_all = I.par("dac_gas", ["i", "allt", "consumecat"]).rename({"allt": "t"})
    dac_gas = semi(dac_gas_all, t_all, ["t"])
    dg2020 = dac_gas.filter(pl.col("t") == "2020").select(["i", "consumecat", pl.col("value").alias("v2020")])
    dac_gas = _assign(dac_gas, semi(dac_gas.select(["i", "consumecat"]).unique().join(t_all, how="cross").filter(yr("t") < 2020), t_all, ["t"])
                      .join(dg2020, on=["i", "consumecat"], how="left").with_columns(pl.col("v2020").fill_null(0.0).alias("value"))
                      .select(["i", "t", "consumecat", "value"]), ["i", "t", "consumecat"])
    for cat in ("capcost", "vom", "fom"):
        rows = dac_gas.filter((pl.col("i") == "dac_gas") & (pl.col("consumecat") == cat)).with_columns(pl.lit(cat).alias("plantcat")).select(["i", "t", "plantcat", "value"])
        pc0 = _assign(pc0, rows, ["i", "t", "plantcat"],
                      domain=t_all.with_columns(pl.lit("dac_gas").alias("i"), pl.lit(cat).alias("plantcat")).select(["i", "t", "plantcat"]))
    pc0 = nonzero(pc0)
    S["plant_char0"] = pc0

    def pchar(cat: str) -> pl.DataFrame:
        return pc0.filter(pl.col("plantcat") == cat).select(["i", "t", "value"])

    # ------------------------------------------------------------- capital cost
    cost_cap = semi(pchar("capcost"), t_all, ["t"])
    if float(csw["GSw_CCSFLEX_cost_mult"]) != 1.0:
        raise NotImplementedError("GSw_CCSFLEX_cost_mult != 1 is not ported")
    S["cost_cap"] = cost_cap.with_columns(gams_round(pl.col("value"), 2).alias("value"))
    epa = I.par("eval_period_adj_mult", ["i", "t"])
    if upgrades_on:
        epa = _assign(epa, from_to(epa, ["i", "t"], upgrade_to), ["i", "t"], domain=S.upgrade.join(t_all, how="cross"))
    S["eval_period_adj_mult"] = epa
    S["cost_cap_energy"] = (semi(pchar("capcost_energy"), t_all, ["t"]).filter(isin("i", members(S.battery)))
                            .with_columns(gams_round(pl.col("value"), 2).alias("value")))
    S["hydrocapmult"] = I.par("hydrocapcostmult", ["allt", "i"]).rename({"allt": "t"})
    S["ofswind_rsc_mult"] = I.par("ofswind_rsc_mult", ["allt", "i"]).rename({"allt": "t"})

    # ------------------------------------------------------------- variable O&M
    if int(sw["Sw_BinOM"]) != 1:
        raise NotImplementedError("Sw_BinOM=0 is not ported")
    hint = S.hintage_data.rename({"allt": "t"})
    vom_new = pchar("vom")
    cost_vom = semi(valgen.filter(isin("v", newv)), vom_new, ["i", "t"]).join(vom_new, on=["i", "t"], how="inner").select(V4 + ["value"])
    wvom = hint.filter(pl.col("hintage_char") == "wvom").select(V4 + ["value"])
    vom_init = semi(valgen.filter(isin("v", initv)), wvom, V4).join(wvom, on=V4, how="inner").select(V4 + ["value"])
    cost_vom = pl.concat([cost_vom, vom_init])
    vom_start = vom_new.filter(pl.col("t") == startyear).select(["i", pl.col("value")])
    fill = anti(valgen.filter(isin("v", initv)), cost_vom, V4).join(vom_start, on="i", how="inner").select(V4 + ["value"])
    cost_vom = pl.concat([cost_vom, fill])
    avg = _avg_over_ivt(S, vom_new, ["i", "v"])
    cost_vom = _assign(cost_vom, valgen.filter(isin("v", newv)).join(avg, on=["i", "v"], how="inner").select(V4 + ["value"]), V4,
                       domain=semi(valgen.filter(isin("v", newv)), S.countnc, ["i", "v"]).select(V4))
    cost_vom = _assign(cost_vom, _par_over(valcap.filter(isin("i", members(S.hydro))), sc["vom_hyd"]), V4)
    if members(S.dr_shed):
        raise NotImplementedError("dr_shed costs are not ported")
    if upgrades_on:
        char = vom_new.filter(pl.col("t") == uchar_year).select(["i", "value"])
        char = (char.join(semi(S.ivt.filter(pl.col("t") == uchar_year), S.newv, ["v"]).select("i").unique(), on="i", how="semi")
                .with_columns(pl.when(isin("i", members(S.hydro))).then(pl.col("value") + sc["vom_hyd"]).otherwise(pl.col("value")).alias("value")))
        up_init = (valcap.filter(isin("i", upgrade) & isin("v", initv)).join(upgrade_to, on="i", how="inner")
                   .join(char.rename({"i": "ii"}), on="ii", how="inner").group_by(V4).agg(pl.col("value").sum()))
        cost_vom = _assign(cost_vom, up_init, V4, domain=valcap.filter(isin("i", upgrade) & isin("v", initv)).select(V4))
        retro = hint.filter((pl.col("hintage_char") == "wccs_retro_vom") & isin("v", initv)).select(V4 + ["value"])
        nems = (nems_domain(upgrade & members(S.ccs) & unitspec)
                .join(upgrade_from, on="i", how="inner")
                .join(valcap.rename({"i": "ii"}), on=["ii", "v", "r", "t"], how="semi")
                .join(retro.rename({"i": "ii"}), on=["ii", "v", "r", "t"], how="inner")
                .group_by(V4).agg(pl.col("value").sum()))
        if int(sw["Sw_UpgradeVOM_Nems"]):
            cost_vom = _assign(cost_vom, nems, V4)
        up_new = (valcap.filter(isin("i", upgrade) & isin("v", newv)).join(upgrade_to, on="i", how="inner")
                  .join(cost_vom.rename({"i": "ii"}), on=["ii", "v", "r", "t"], how="inner").group_by(V4).agg(pl.col("value").sum()))
        cost_vom = _assign(cost_vom, up_new, V4, domain=valcap.filter(isin("i", upgrade) & isin("v", newv)).select(V4))
    cost_vom = _assign(cost_vom, _par_over(valcap.filter(isin("i", members(S.psh))), sc["cost_vom_psh"]), V4)
    stor_missing = anti(valgen.filter(isin("i", members(S.storage))), nonzero(cost_vom), V4)
    cost_vom = pl.concat([cost_vom, _par_over(stor_missing, sc["storage_vom_min"])])
    cost_vom = semi(nonzero(cost_vom), valgen, V4)
    S["cost_vom"] = cost_vom.with_columns(gams_round(pl.col("value"), 2).alias("value"))

    # ------------------------------------------------------------- fixed O&M
    fom_new = pchar("fom")
    cost_fom = semi(valcap.filter(isin("v", newv)), fom_new, ["i", "t"]).join(fom_new, on=["i", "t"], how="inner").select(V4 + ["value"])
    wfom = hint.filter(pl.col("hintage_char") == "wfom").select(V4 + ["value"])
    fom_init = semi(valcap.filter(isin("v", initv)), wfom, V4).join(wfom, on=V4, how="inner").select(V4 + ["value"])
    cost_fom = pl.concat([cost_fom, fom_init])
    fom_start = fom_new.filter(pl.col("t") == startyear).select(["i", "value"])
    fill = anti(valcap.filter(isin("v", initv)), cost_fom, V4).join(fom_start, on="i", how="inner").select(V4 + ["value"])
    cost_fom = pl.concat([cost_fom, fill])
    avg = _avg_over_ivt(S, fom_new, ["i", "v"])
    cost_fom = _assign(cost_fom, valcap.filter(isin("v", newv)).join(avg, on=["i", "v"], how="inner").select(V4 + ["value"]), V4,
                       domain=semi(valcap.filter(isin("v", newv)), S.countnc, ["i", "v"]).select(V4))
    one = valcap.filter((pl.col("v") == "new1") & isin("i", members(S.one_newv))).join(fom_new, on=["i", "t"], how="inner").select(V4 + ["value"])
    cost_fom = _assign(cost_fom, one, V4)
    online = hint.filter((pl.col("hintage_char") == "wonlineyear") & (pl.col("t") == startyear)).select(["i", "v", "r", pl.col("value").alias("online")])
    plant_age = (valcap.filter(isin("v", initv)).join(online, on=["i", "v", "r"], how="inner")
                 .with_columns(pl.max_horizontal(pl.lit(0.0), yr("t").cast(pl.Float64) - pl.col("online")).alias("value")).select(V4 + ["value"]))
    S["plant_age"] = plant_age
    nk = float(sw["Sw_NukeCoalFOM"])
    coal_rows = (cost_fom.join(plant_age.rename({"value": "age"}), on=V4, how="inner").filter(isin("i", members(S.coal)) & isin("v", initv))
                 .with_columns((pl.col("value") + sc["coal_fom_adj"] * pl.col("age") * nk).alias("value")).select(V4 + ["value"]))
    cost_fom = _assign(cost_fom, coal_rows, V4)
    nuke_rows = (cost_fom.join(plant_age.rename({"value": "age"}), on=V4, how="inner")
                 .filter(isin("i", members(S.nuclear)) & isin("v", initv) & (pl.col("age") > sc["nuke_fom_adj_age_threshold"]))
                 .with_columns((pl.col("value") + sc["nuke_fom_adj"] * nk).alias("value")).select(V4 + ["value"]))
    cost_fom = _assign(cost_fom, nuke_rows, V4)
    hyd_fom = I.par("hyd_fom", ["i", "r"])
    cost_fom = _assign(cost_fom, valcap.filter(isin("i", members(S.hydro))).join(hyd_fom, on=["i", "r"], how="inner").select(V4 + ["value"]), V4)
    if upgrades_on:
        char = fom_new.filter(pl.col("t") == uchar_year).select(["i", "value"])
        char = char.join(semi(S.ivt.filter(pl.col("t") == uchar_year), S.newv, ["v"]).select("i").unique(), on="i", how="semi")
        up_init = (valcap.filter(isin("i", upgrade) & isin("v", initv)).join(upgrade_to, on="i", how="inner")
                   .join(char.rename({"i": "ii"}), on="ii", how="inner")
                   .join(hyd_fom.rename({"i": "ii", "value": "hf"}), on=["ii", "r"], how="left")
                   .with_columns((pl.col("value") + pl.when(isin("ii", members(S.hydro))).then(pl.col("hf").fill_null(0.0)).otherwise(0.0)).alias("value"))
                   .group_by(V4).agg(pl.col("value").sum()))
        cost_fom = _assign(cost_fom, up_init, V4, domain=valcap.filter(isin("i", upgrade) & isin("v", initv)).select(V4))
        retro = hint.filter((pl.col("hintage_char") == "wccs_retro_fom") & isin("v", initv)).select(V4 + ["value"])
        nems = (nems_domain(upgrade & members(S.ccs) & unitspec)
                .join(upgrade_from, on="i", how="inner")
                .join(valcap.rename({"i": "ii"}), on=["ii", "v", "r", "t"], how="semi")
                .join(retro.rename({"i": "ii"}), on=["ii", "v", "r", "t"], how="inner")
                .group_by(V4).agg((1e3 * pl.col("value")).sum().alias("value")))
        if int(sw["Sw_UpgradeFOM_Nems"]):
            cost_fom = _assign(cost_fom, nems, V4)
        up_new = (valcap.filter(isin("i", upgrade) & isin("v", newv)).join(upgrade_to, on="i", how="inner")
                  .join(cost_fom.rename({"i": "ii"}), on=["ii", "v", "r", "t"], how="inner").group_by(V4).agg(pl.col("value").sum()))
        cost_fom = _assign(cost_fom, up_new, V4, domain=valcap.filter(isin("i", upgrade) & isin("v", newv)).select(V4))
    cost_fom = _assign(cost_fom, _par_over(valcap.filter(isin("i", members(S.psh))), sc["cost_fom_psh"]), V4)
    cost_fom = semi(nonzero(cost_fom), valcap, V4)
    S["cost_fom"] = cost_fom.with_columns(gams_round(pl.col("value"), 2).alias("value"))
    fome = pchar("fom_energy")
    S["cost_fom_energy"] = (valcap.filter(isin("i", members(S.battery))).join(fome, on=["i", "t"], how="inner").select(V4 + ["value"])
                            .with_columns(gams_round(pl.col("value"), 2).alias("value")))

    # ------------------------------------------------------------- heat rate
    hr_tab = pchar("heatrate")
    heat_rate = valcap.join(hr_tab, on=["i", "t"], how="inner").select(V4 + ["value"])
    avg = _avg_over_ivt(S, hr_tab, ["i", "v"])
    heat_rate = _assign(heat_rate, valcap.filter(isin("v", newv)).join(avg, on=["i", "v"], how="inner").select(V4 + ["value"]), V4,
                        domain=semi(valcap.filter(isin("v", newv)), S.countnc, ["i", "v"]).select(V4))
    hr_start = hr_tab.filter(pl.col("t") == startyear).select(["i", "value"])
    fill = anti(valcap.filter(isin("v", initv)), nonzero(heat_rate), V4).join(hr_start, on="i", how="inner").select(V4 + ["value"])
    heat_rate = pl.concat([heat_rate, fill])
    binned = semi(S.binned_heatrates.rename({"allt": "t"}), t_all, ["t"]).with_columns((pl.col("value") / 1000.0).alias("value"))
    heat_rate = _assign(heat_rate, semi(valcap, binned, V4).join(binned, on=V4, how="inner").select(V4 + ["value"]), V4)
    hra = I.par("heat_rate_adj", ["i", "prepost"])
    if upgrades_on:
        hra = _assign(hra, from_to(hra, ["i", "prepost"], upgrade_to), ["i", "prepost"], domain=S.upgrade.join(hra.select("prepost").unique(), how="cross"))
        char = hr_tab.filter(pl.col("t") == uchar_year).select(["i", "value"])
        char = char.join(semi(S.ivt.filter(pl.col("t") == uchar_year), S.newv, ["v"]).select("i").unique(), on="i", how="semi")
        up_init = (valcap.filter(isin("i", upgrade) & isin("v", initv)).join(upgrade_to, on="i", how="inner")
                   .join(char.rename({"i": "ii"}), on="ii", how="inner").group_by(V4).agg(pl.col("value").sum()))
        heat_rate = _assign(heat_rate, up_init, V4, domain=valcap.filter(isin("i", upgrade) & isin("v", initv)).select(V4))
        retro = hint.filter((pl.col("hintage_char") == "wccs_retro_hr") & isin("v", initv)).select(V4 + ["value"])
        nems = (nems_domain(upgrade & members(S.ccs))
                .join(upgrade_from, on="i", how="inner")
                .join(valcap.rename({"i": "ii"}), on=["ii", "v", "r", "t"], how="semi")
                .join(retro.rename({"i": "ii"}), on=["ii", "v", "r", "t"], how="inner")
                .group_by(V4).agg((pl.col("value") / 1000.0).sum().alias("value")))
        heat_rate = _assign(heat_rate, nems, V4)
        up_new = (valcap.filter(isin("i", upgrade) & isin("v", newv)).join(upgrade_to, on="i", how="inner")
                  .join(nonzero(heat_rate).rename({"i": "ii"}), on=["ii", "v", "r", "t"], how="inner").group_by(V4).agg(pl.col("value").sum()))
        heat_rate = _assign(heat_rate, up_new, V4, domain=valcap.filter(isin("i", upgrade) & isin("v", newv)).select(V4))
    pre = hra.filter(pl.col("prepost") == "pre2010").select(["i", pl.col("value").alias("adj")])
    post = hra.filter(pl.col("prepost") == "post2010").select(["i", pl.col("value").alias("adj")])
    heat_rate = (heat_rate.join(pre, on="i", how="left").with_columns(
        pl.when(isin("v", initv) & pl.col("adj").is_not_null()).then(pl.col("value") * pl.col("adj")).otherwise(pl.col("value")).alias("value")).drop("adj"))
    heat_rate = (heat_rate.join(post, on="i", how="left").with_columns(
        pl.when(isin("v", newv) & pl.col("adj").is_not_null()).then(pl.col("value") * pl.col("adj")).otherwise(pl.col("value")).alias("value")).drop("adj"))
    heat_rate_full = nonzero(heat_rate)
    S["heat_rate_full"] = heat_rate_full
    S["heat_rate"] = semi(heat_rate_full, valgen, V4).with_columns(gams_round(pl.col("value"), 2).alias("value"))

    # ------------------------------------------------------------- fuel price
    fuel2tech = S.fuel2tech
    extra = pl.concat([S.coal.with_columns(pl.lit("coal").alias("f")), S.gas.with_columns(pl.lit("naturalgas").alias("f")),
                       S.nuclear.with_columns(pl.lit("uranium").alias("f"))]).select(["f", "i"])
    fuel2tech = pl.concat([fuel2tech, extra]).unique()
    if upgrades_on:
        up_f = upgrade_to.join(fuel2tech.rename({"i": "ii"}), on="ii", how="inner").select(["f", "i"]).unique()
        fuel2tech = pl.concat([anti(fuel2tech, S.upgrade, ["i"]), up_f]).unique()
    S["fuel2tech"] = fuel2tech
    fprice = I.par("fprice", ["allt", "r", "f"]).rename({"allt": "t"})
    fp = (fuel2tech.join(semi(fprice, t_all, ["t"]), on="f", how="inner").group_by(["i", "r", "t"]).agg(pl.col("value").sum()))
    fp = nonzero(fp)
    means = fp.group_by(["i", "t"]).agg(pl.col("value").mean().alias("mean"))
    dom = fuel2tech.select("i").unique().join(S.r, how="cross").join(t_all, how="cross")
    missing = anti(dom, fp, ["i", "r", "t"]).join(means, on=["i", "t"], how="inner").select(["i", "r", "t", pl.col("mean").alias("value")])
    fp = pl.concat([fp, missing])
    if upgrades_on:
        fp = _assign(fp, from_to(fp, ["i", "r", "t"], upgrade_to), ["i", "r", "t"], domain=S.upgrade.join(S.r, how="cross").join(t_all, how="cross"))
    S["fuel_price_raw"] = nonzero(fp)
    S["fuel_price"] = fp.with_columns(gams_round(pl.col("value"), 2).alias("value"))

    # ------------------------------------------------------------- storage and misc tech parameters
    storage = S.storage
    eff = _par_over(storage.join(t_all, how="cross"), 1.0)
    eff = _assign(eff, _par_over(S.psh.join(t_all, how="cross"), sc["storage_eff_psh"]), ["i", "t"])
    rte = pchar("rte")
    eff = _assign(eff, semi(storage.join(t_all, how="cross"), rte, ["i", "t"]).join(rte, on=["i", "t"], how="inner").select(["i", "t", "value"]), ["i", "t"])
    if upgrades_on:
        eff = _assign(eff, from_to(eff, ["i", "t"], upgrade_to), ["i", "t"], domain=S.upgrade.join(t_all, how="cross"))
    S["storage_eff"] = nonzero(eff)
    ilr = _par_over(S.valcap_i, 1.0)
    ilr = _assign(ilr, _par_over(S.upv, sc["ilr_utility"]), ["i"])
    ilr = _assign(ilr, _par_over(S.distpv, sc["ilr_dist"]), ["i"])
    S["ilr"] = ilr
    S["bcr"] = _par_over(one_col(members(S.storage_standalone) | members(S.csp_storage) | members(S.hyd_add_pump), "i"), 1.0)
    csp_sm = pl.concat([_par_over(S[f"csp{k}"], sc[f"csp_sm_{k}"]) for k in (1, 2, 3, 4)]).unique(subset=["i"], keep="last")
    S["csp_sm"] = csp_sm
    rscaler = _par_over(anti(anti(S.i, S.csp_storage), S.ban), 1.0)
    rscaler = _assign(rscaler, semi(csp_sm, S.csp, ["i"]).with_columns((pl.col("value") / sc["csp_sm_baseline"]).alias("value")), ["i"],
                      domain=S.csp)
    S["resourcescaler"] = rscaler
    sdur = I.par("storage_duration", ["i"])
    psh_dur = I.scalars("psh_sc_duration")
    psh_sc_duration = float(list(psh_dur.values())[0]) if psh_dur else float(I.raw("psh_sc_duration")["value"][0])
    sdur = _assign(sdur, _par_over(S.psh, psh_sc_duration), ["i"])
    if upgrades_on:
        sdur = _assign(sdur, from_to(sdur, ["i"], upgrade_to), ["i"], domain=S.upgrade)
    S["storage_duration"] = anti(sdur, S.ban, ["i"])
    sdm = S.valcap_ivr.join(sdur, on="i", how="inner").select(["i", "v", "r", "value"])
    if int(csw["GSw_HydroPSHDurData"]) == 1:
        pshdata = I.par("storage_duration_pshdata", ["i", "v", "r"]).filter(isin("i", members(S.psh)))
        sdm = _assign(sdm, semi(pshdata, S.valcap_ivr, ["i", "v", "r"]), ["i", "v", "r"])
    S["storage_duration_m"] = sdm

    # ------------------------------------------------------------- seasonal capacity deltas
    cap_start = hint.filter((pl.col("hintage_char") == "cap") & (pl.col("t") == startyear)).select(["i", "v", "r", pl.col("value").alias("cap")])
    wint_start = hint.filter((pl.col("hintage_char") == "wintercap") & (pl.col("t") == startyear)).select(["i", "v", "r", pl.col("value").alias("wint")])
    ratio = _par_over(S.valcap_ivr, 1.0)
    init_ratio = (cap_start.join(wint_start, on=["i", "v", "r"], how="left").filter(isin("v", initv))
                  .with_columns((pl.col("wint").fill_null(0.0) / pl.col("cap")).alias("value")).select(["i", "v", "r", "value"]))
    ratio = _assign(ratio, init_ratio, ["i", "v", "r"])
    w = (init_ratio.join(wint_start, on=["i", "v", "r"], how="inner").group_by("i")
         .agg((pl.col("value") * pl.col("wint")).sum().alias("num"), pl.col("wint").sum().alias("den"))
         .filter(pl.col("den") != 0).with_columns((pl.col("num") / pl.col("den")).alias("value")).select(["i", "value"]))
    new_ratio = S.valcap_ivr.filter(isin("v", newv)).join(w, on="i", how="inner").select(["i", "v", "r", "value"])
    ratio = _assign(ratio, new_ratio, ["i", "v", "r"])
    for techs, src in ((members(S.h2_ct), "gas-ct"), (members(S.h2_cc), "gas-cc"), (members(S.nuclear), "nuclear")):
        srcrows = ratio.filter((pl.col("i") == src) & isin("v", newv)).select(["v", "r", "value"])
        rows = one_col(techs, "i").join(srcrows, how="cross").select(["i", "v", "r", "value"])
        dom = one_col(techs, "i").join(S.newv, how="cross").join(S.r, how="cross").select(["i", "v", "r"])
        ratio = _assign(ratio, rows, ["i", "v", "r"], domain=dom)
    if upgrades_on:
        up_ratio = (S.upgrade.join(upgrade_from, on="i", how="inner")
                    .join(ratio.filter(isin("v", newv)).rename({"i": "ii"}), on="ii", how="inner")
                    .group_by(["i", "v", "r"]).agg(pl.col("value").sum()))
        ratio = _assign(ratio, up_ratio, ["i", "v", "r"], domain=S.upgrade.join(S.newv, how="cross").join(S.r, how="cross"))
    ratio = semi(ratio, S.valcap_ivr, ["i", "v", "r"])
    delta = nonzero(ratio.with_columns(gams_round(pl.col("value") - 1.0, 3).alias("value")))
    S["winter_cap_frac_delta"] = delta
    qcfd = delta.with_columns(pl.lit("wint").alias("quarter")).join(t_all, how="cross").select(["i", "v", "r", "quarter", "t", "value"])
    thermal = S.climate_heuristics_finalyear.get("thermal_summer_cap_delta", 0.0)
    summ = (S.valcap_ivr.filter(isin("i", members(S.conv))).join(t_all, how="cross")
            .with_columns(pl.col("t").replace_strict(S.climate_heuristics_yearfrac, default=0.0).alias("yf"))
            .with_columns((pl.lit(thermal) * pl.col("yf")).alias("value"), pl.lit("summ").alias("quarter"))
            .select(["i", "v", "r", "quarter", "t", "value"]))
    S["quarter_cap_frac_delta"] = nonzero(pl.concat([qcfd, summ]))

    # ------------------------------------------------------------- capacity-factor adjustments over time
    i_c = S.i_c
    base = (valcap.select(["i", "v", "t"]).unique().join(i_c, on="i", how="inner")
            .filter(isin("i", members(S.rsc_i) | members(S.hydro))))
    cf_adj = _par_over(base.select(["i", "c", "v", "t"]), 1.0)
    wcf = I.par("windcfmult", ["allt", "i"]).rename({"allt": "t"})
    wind_init = (base.filter(isin("i", members(S.wind)) & isin("v", initv))
                 .join(wcf.filter(pl.col("t") == startyear).select(["i", "value"]), on="i", how="inner").select(["i", "c", "v", "t", "value"]))
    cf_adj = _assign(cf_adj, wind_init, ["i", "c", "v", "t"])
    wavg = _avg_over_ivt(S, wcf, ["i", "v"])
    wind_new = (base.filter(isin("i", members(S.wind)) & isin("v", newv)).join(wcf.select(["i", "t"]).unique(), on=["i", "t"], how="semi")
                .join(wavg, on=["i", "v"], how="inner").select(["i", "c", "v", "t", "value"]))
    cf_adj = _assign(cf_adj, wind_new, ["i", "c", "v", "t"])
    pvimp = I.par("pv_cf_improve", ["allt"]).rename({"allt": "t"})
    pvavg = (S.ivt.rename({"t": "tt"}).join(pvimp.rename({"t": "tt"}), on="tt", how="inner").group_by(["i", "v"]).agg(pl.col("value").sum())
             .join(S.countnc.rename({"value": "n"}), on=["i", "v"], how="inner").with_columns((pl.col("value") / pl.col("n")).alias("value")).select(["i", "v", "value"]))
    pv_new = base.filter(isin("i", members(S.pv) | members(S.pvb)) & isin("v", newv)).join(pvavg, on=["i", "v"], how="inner").select(["i", "c", "v", "t", "value"])
    cf_adj = _assign(cf_adj, pv_new, ["i", "c", "v", "t"])
    S["cf_adj_t"] = nonzero(cf_adj)
    S["derate_geo_vintage"] = _par_over(S.valcap_iv, 1.0)
    hcd = S.climate_heuristics_finalyear.get("hydro_capcredit_delta", 0.0)
    S["hydro_capcredit_delta"] = nonzero(S.hydro_d.join(t_all, how="cross")
                                         .with_columns(pl.col("t").replace_strict(S.climate_heuristics_yearfrac, default=0.0).alias("yf"))
                                         .with_columns((pl.lit(hcd) * pl.col("yf")).alias("value")).select(["i", "t", "value"]))

    # ------------------------------------------------------------- tax credits
    ptc = I.par("ptc_value_scaled", ["i", "v", "t"])
    S["ptc_value_scaled"] = ptc.with_columns(pl.when(isin("t", set(t_all["t"]))).then(gams_round(pl.col("value"), 2)).otherwise(pl.col("value")).alias("value"))
    inc_in = I.par("co2_captured_incentive_in", ["i", "v", "t"])
    inc = S.i.join(S.v, how="cross").join(S.r, how="cross").join(t_all, how="cross").join(inc_in, on=["i", "v", "t"], how="inner").select(V4 + ["value"])
    fyv = S.firstyear_v.rename({"value": "fyv"})
    if upgrades_on:
        up = (valcap.filter(isin("i", upgrade)).join(upgrade_to, on="i", how="inner")
              .join(inc.rename({"i": "ii"}), on=["ii", "v", "r", "t"], how="inner").group_by(V4).agg(pl.col("value").sum()))
        inc = _assign(inc, up, V4, domain=valcap.filter(isin("i", upgrade)).select(V4))
        last = sc["co2_capture_incentive_last_year_"]
        src = (upgrade_to.join(fyv.rename({"i": "ii"}), on="ii", how="inner")
               .filter(isin("v", newv) & (pl.col("fyv") == float(S.Sw_UpgradeYear)))
               .join(inc.filter(pl.col("t") == str(S.Sw_UpgradeYear)).rename({"i": "ii"}), on=["ii", "v"], how="inner")
               .group_by(["i", "r"]).agg(pl.col("value").sum()))
        dom = (valcap.filter(isin("i", upgrade) & isin("v", initv) & (yr("t") >= S.Sw_UpgradeYear) & (yr("t").cast(pl.Float64) <= last)).select(V4))
        inc = _assign(inc, dom.join(src, on=["i", "r"], how="inner").select(V4 + ["value"]), V4, domain=dom)
    inc = (inc.join(fyv, on=["i", "v"], how="left")
           .filter(~(isin("v", newv) & (yr("t").cast(pl.Float64) > pl.col("fyv") + sc["co2_capture_incentive_length"])))
           .filter(~(isin("v", newv) & (pl.col("fyv") > sc["co2_capture_incentive_last_year_"]))).select(V4 + ["value"]))
    S["co2_captured_incentive"] = nonzero(semi(inc, valcap, V4))

    # ------------------------------------------------------------- emissions
    erf = I.par("emitrate", ["i", "etype", "e"])
    ccs_link = I.set("ccs_link", ["i", "ii"])
    cri = pl.concat([_par_over(S.ccs_mod.with_columns(pl.lit("co2").alias("e")), sw["Sw_CCS_Rate_New_mod"]),
                     _par_over(S.ccs_max.with_columns(pl.lit("co2").alias("e")), sw["Sw_CCS_Rate_New_max"])])
    if upgrades_on:
        up_ccs = upgrade & (members(S.coal_ccs) | members(S.gas_cc_ccs))
        cri = pl.concat([cri,
                         _par_over(one_col(up_ccs & members(S.ccs_mod), "i").with_columns(pl.lit("co2").alias("e")), sw["Sw_CCS_Rate_Upgrade_mod"]),
                         _par_over(one_col(up_ccs & members(S.ccs_max), "i").with_columns(pl.lit("co2").alias("e")), sw["Sw_CCS_Rate_Upgrade_max"])])
    cri = cri.unique(subset=["i", "e"], keep="last")
    S["capture_rate_input"] = cri
    ccs_nb = members(S.ccs) - members(S.beccs)
    link_proc = ccs_link.join(erf.filter(pl.col("etype") == "process").rename({"i": "ii"}), on="ii", how="inner").group_by(["i", "etype", "e"]).agg(pl.col("value").sum())
    link_up = ccs_link.join(erf.filter(pl.col("etype") == "upstream").rename({"i": "ii"}), on="ii", how="inner").group_by(["i", "etype", "e"]).agg(pl.col("value").sum())
    proc_ccs = (link_proc.filter(isin("i", ccs_nb)).join(cri.rename({"value": "cr"}), on=["i", "e"], how="left")
                .with_columns(((1.0 - pl.col("cr").fill_null(0.0)) * pl.col("value")).alias("value")).select(["i", "etype", "e", "value"]))
    dom_proc = one_col(ccs_nb, "i").join(S.e, how="cross").with_columns(pl.lit("process").alias("etype")).select(["i", "etype", "e"])
    erf = _assign(erf, proc_ccs, ["i", "etype", "e"], domain=dom_proc)
    dom_up = one_col(ccs_nb, "i").join(S.e, how="cross").with_columns(pl.lit("upstream").alias("etype")).select(["i", "etype", "e"])
    erf = _assign(erf, link_up.filter(isin("i", ccs_nb)), ["i", "etype", "e"], domain=dom_up)
    flex = members(S.ccsflex)
    dom_flex = one_col(flex, "i").join(S.e, how="cross").with_columns(pl.lit("process").alias("etype")).select(["i", "etype", "e"])
    erf = _assign(erf, link_proc.filter(isin("i", flex)), ["i", "etype", "e"], domain=dom_flex)
    if upgrades_on:
        up_nonccs = one_col(upgrade - members(S.ccs), "i")
        proc_up = from_to(erf.filter(pl.col("etype") == "process"), ["i", "etype", "e"], upgrade_to)
        erf = _assign(erf, semi(proc_up, up_nonccs, ["i"]), ["i", "etype", "e"],
                      domain=up_nonccs.join(S.e, how="cross").with_columns(pl.lit("process").alias("etype")).select(["i", "etype", "e"]))
        up_all = from_to(erf.filter(pl.col("etype") == "upstream"), ["i", "etype", "e"], upgrade_to)
        erf = _assign(erf, up_all, ["i", "etype", "e"],
                      domain=S.upgrade.join(S.e, how="cross").with_columns(pl.lit("upstream").alias("etype")).select(["i", "etype", "e"]))
    S["emit_rate_fuel"] = erf
    crf_fuel = (cri.join(link_proc.select(["i", "e", pl.col("value").alias("lp")]), on=["i", "e"], how="inner")
                .with_columns((pl.col("value") * pl.col("lp")).alias("value")).select(["i", "e", "value"]))
    beccs_rows = erf.filter(isin("i", members(S.beccs)) & (pl.col("etype") == "process") & (pl.col("e") == "co2")).with_columns((-pl.col("value")).alias("value")).select(["i", "e", "value"])
    crf_fuel = _assign(crf_fuel, beccs_rows, ["i", "e"])
    S["capture_rate_fuel"] = nonzero(crf_fuel)
    gascc = erf.filter((pl.col("i") == "gas-cc") & (pl.col("etype") == "process") & (pl.col("e") == "co2"))["value"]
    methane_tonperMMBtu = float(gascc[0]) * sc["molWeightCH4"] / sc["molWeightCO2"] if gascc.len() else 0.0
    h2_ci = (1.0 / sc["h2_energy_intensity"]) * (1.0 / sc["lb_per_tonne"]) * 1e6
    hr_full = heat_rate_full
    hr_valcap = semi(hr_full, valcap, V4)
    er = (hr_valcap.join(erf.rename({"value": "rate"}), on="i", how="inner")
          .with_columns(gams_round(pl.col("value") * pl.col("rate"), 10).alias("value")).select(["etype", "e", "i", "v", "r", "t", "value"]))
    coal_new = erf.filter(pl.col("i") == "coal-new").select(["etype", "e", pl.col("value").alias("rate")])
    cof = (hr_valcap.filter(pl.col("i") == "cofire").join(coal_new, how="cross")
           .with_columns(gams_round((1.0 - sc["bio_cofire_perc"]) * pl.col("value") * pl.col("rate"), 10).alias("value"))
           .select(["etype", "e", "i", "v", "r", "t", "value"]))
    er = _assign(er, cof, ["etype", "e", "i", "v", "r", "t"])
    leak = I.par("methane_leakage_rate", ["t"]).rename({"value": "leak"})
    ch4 = (hr_full.filter(isin("i", members(S.gas))).join(leak, on="t", how="inner")
           .with_columns((pl.col("value") * methane_tonperMMBtu * pl.col("leak") / (1.0 - pl.col("leak"))).alias("value"),
                         pl.lit("upstream").alias("etype"), pl.lit("ch4").alias("e"))
           .select(["etype", "e", "i", "v", "r", "t", "value"]))
    er = _assign(er, ch4, ["etype", "e", "i", "v", "r", "t"])
    h2leak = I.par("h2_leakage_rate", ["i"]).rename({"value": "leak"})
    h2p = (hr_full.join(h2leak, on="i", how="inner")
           .with_columns((pl.col("value") * h2_ci * pl.col("leak") / (1.0 - pl.col("leak"))).alias("value"),
                         pl.lit("process").alias("etype"), pl.lit("h2").alias("e"))
           .select(["etype", "e", "i", "v", "r", "t", "value"]))
    er = _assign(er, h2p, ["etype", "e", "i", "v", "r", "t"])
    if upgrades_on:
        h2_up = (S.upgrade.join(upgrade_to, on="i", how="inner")
                 .join(er.filter((pl.col("etype") == "process") & (pl.col("e") == "h2")).rename({"i": "ii"}), on="ii", how="inner")
                 .group_by(["etype", "e", "i", "v", "r", "t"]).agg(pl.col("value").sum()))
        er = _assign(er, h2_up, ["etype", "e", "i", "v", "r", "t"],
                     domain=S.upgrade.join(S.v, how="cross").join(S.r, how="cross").join(t_all, how="cross")
                     .with_columns(pl.lit("process").alias("etype"), pl.lit("h2").alias("e")).select(["etype", "e", "i", "v", "r", "t"]))
    gwp = S.gwp.rename({"value": "gwp"})
    excl = (pl.col("e") != "h2") if int(sw["Sw_AnnualCap"]) == 2 else pl.lit(True)
    co2e = (er.join(gwp, on="e", how="inner").filter(excl).group_by(["etype", "i", "v", "r", "t"]).agg(pl.col("value").mul(pl.col("gwp")).sum())
            .with_columns(gams_round(pl.col("value"), 10).alias("value"), pl.lit("co2e").alias("e")).select(["etype", "e", "i", "v", "r", "t", "value"]))
    er = _assign(er, co2e, ["etype", "e", "i", "v", "r", "t"])
    er = nonzero(er)
    er = pl.concat([semi(er.filter(pl.col("e") != "co2e"), valgen, V4), er.filter(pl.col("e") == "co2e")])
    S["emit_rate"] = er.with_columns(gams_round(pl.col("value"), 10).alias("value"))
    cap_rate = (hr_valcap.join(crf_fuel.rename({"value": "cr"}), on="i", how="inner")
                .with_columns(gams_round(pl.col("value") * pl.col("cr"), 10).alias("value")).select(["e", "i", "v", "r", "t", "value"]))
    cap_rate_up = (hr_full.filter(isin("i", upgrade)).join(crf_fuel.rename({"value": "cr"}), on="i", how="inner")
                   .with_columns(gams_round(pl.col("value") * pl.col("cr"), 10).alias("value")).select(["e", "i", "v", "r", "t", "value"]))
    cap_rate = _assign(cap_rate, cap_rate_up, ["e"] + V4)
    cap_rate = nonzero(cap_rate)
    S["capture_rate"] = pl.concat([semi(cap_rate, valgen, V4).with_columns(gams_round(pl.col("value"), 6).alias("value")),
                                   anti(cap_rate.filter(isin("i", upgrade)), valgen, V4)])
    co2_cap = I.par("co2_cap", ["t"])
    cap_mode = int(sw["Sw_AnnualCap"])
    emit_cap = semi(co2_cap, t_all, ["t"]).with_columns(pl.lit("co2" if cap_mode == 1 else "co2e").alias("eall")).select(["eall", "t", "value"]) if cap_mode else co2_cap.head(0).with_columns(pl.lit("").alias("eall")).select(["eall", "t", "value"])
    S["emit_cap"] = emit_cap
    if int(sw["Sw_CarbTax"]) != 0:
        raise NotImplementedError("carbon tax is not ported")
    S["emit_tax"] = pl.DataFrame({"e": pl.Series([], dtype=pl.Utf8), "r": pl.Series([], dtype=pl.Utf8), "t": pl.Series([], dtype=pl.Utf8), "value": pl.Series([], dtype=pl.Float64)})
    em = pl.DataFrame({"e": pl.Series([], dtype=pl.Utf8), "r": pl.Series([], dtype=pl.Utf8), "t": pl.Series([], dtype=pl.Utf8)})
    rggi_states = I.set("rggi_states", ["st"])
    S["rggi_r"] = S.r_st.join(rggi_states, on="st", how="semi").select("r").unique()
    S["rggi_cap"] = I.par("rggicon", ["allt"]).rename({"allt": "t"}).with_columns(gams_round(pl.col("value"), 0).alias("value"))
    state_cap = I.par("state_cap", ["st", "allt"]).rename({"allt": "t"})
    S["state_cap"] = state_cap.with_columns(gams_round(pl.col("value"), 0).alias("value"))
    if int(sw["Sw_RGGI"]):
        rows = (S.rggi_r.join(S.tmodel_new, how="cross").filter(yr("t") >= sc["RGGI_start_yr"])
                .with_columns(pl.lit("co2").alias("e")).select(["e", "r", "t"]))
        em = pl.concat([em, rows])
    if int(sw["Sw_StateCap"]):
        cap_r = S.r_st.join(state_cap.select("st").unique(), on="st", how="semi").select("r").unique()
        rows = (cap_r.join(S.tmodel_new, how="cross").filter(yr("t") >= sc["state_cap_start_yr"])
                .with_columns(pl.lit("co2").alias("e")).select(["e", "r", "t"]))
        em = pl.concat([em, rows])
    gwp_e = S.gwp.select("e")
    em = pl.concat([em, gwp_e.join(S.r, how="cross").join(S.tmodel_new, how="cross").select(["e", "r", "t"])])
    if int(sw["Sw_BankBorrowCap"]):
        raise NotImplementedError("bank and borrow cap is not ported")
    S["emit_modeled"] = em.unique()
    if cap_mode == 0:
        capped = set()
    elif cap_mode == 1:
        capped = {"co2"}
    elif cap_mode == 2:
        capped = members(gwp_e) - {"h2"}
    else:
        capped = members(gwp_e)
    S["emit_capped"] = one_col(capped, "e")

    # ------------------------------------------------------------- transmission
    tie = I.par("trancap_init_energy", ["r", "rr", "trtype"])
    tip = I.par("trancap_init_prm", ["r", "rr", "trtype"])
    S["trancap_init_energy"], S["trancap_init_prm"] = tie, tip
    tfut = I.par("trancap_fut", ["r", "rr", "trancap_fut_cat", "trtype", "t"])
    S["invtran_exog"] = tfut.filter(pl.col("trancap_fut_cat") == "certain").select(["r", "rr", "trtype", "t", "value"])
    pairs = pl.concat([tie.select(["r", "rr", "trtype"]), tip.select(["r", "rr", "trtype"])]).unique()
    routes = pairs.join(t_all, how="cross").select(["r", "rr", "trtype", "t"])
    fut_pairs = (tfut.rename({"t": "tt"}).join(t_all, how="cross").filter(yr("tt") <= yr("t")).select(["r", "rr", "trtype", "t"]).unique())
    routes = pl.concat([routes, fut_pairs, S.invtran_exog.select(["r", "rr", "trtype", "t"])]).unique()
    routes = pl.concat([routes, routes.select([pl.col("rr").alias("r"), pl.col("r").alias("rr"), "trtype", "t"])]).unique()
    routes = semi(routes, S.tmodel_new, ["t"])
    ric = S.r_interconnect
    same_ic = ric.join(ric.rename({"r": "rr"}), on="interconnect", how="inner").select(["r", "rr"]).unique()
    routes = routes.join(same_ic.with_columns(pl.lit(True).alias("same")), on=["r", "rr"], how="left").with_columns(pl.col("same").fill_null(False))
    routes = routes.filter(~(isin("trtype", members(S.aclike)) & ~pl.col("same"))).drop("same")
    if not int(sw["Sw_OffshoreBackbone"]):
        off = members(S.offshore)
        routes = routes.filter(~(isin("r", off) & isin("rr", off)))
    S["routes"] = routes
    S["Sw_VSC"] = int(routes.filter(pl.col("trtype") == "vsc").height > 0)
    rinv = routes.filter(isin("trtype", members(S.notvsc)))
    rinv = rinv.filter(yr("t") >= sc["firstyear_trans_nearterm"])
    if not int(sw["Sw_TransInvNearTerm"]):
        rinv = rinv.filter(yr("t") >= sc["firstyear_trans_longterm"])
    fut_any = (tfut.rename({"t": "tt"}).join(t_all, how="cross").filter(yr("tt") <= yr("t")).select(["r", "rr", "trtype", "t"]))
    fut_any = pl.concat([fut_any, fut_any.select([pl.col("rr").alias("r"), pl.col("r").alias("rr"), "trtype", "t"])]).unique()
    rinv = pl.concat([rinv, semi(fut_any, routes, ["r", "rr", "trtype", "t"])]).unique()
    rinv = semi(rinv, rinv.select([pl.col("rr").alias("r"), pl.col("r").alias("rr"), "trtype", "t"]), ["r", "rr", "trtype", "t"])
    level = csw["GSw_TransRestrict"]
    if level == "r":
        rinv = rinv.head(0)
    else:
        lv = S[f"r_{level}"]
        same = lv.join(lv.rename({"r": "rr"}), on=level, how="inner").select(["r", "rr"]).unique()
        rinv = semi(rinv, same, ["r", "rr"])
    S["routes_inv"] = rinv
    vsc_inv = rinv.filter(pl.col("trtype") == "vsc")
    S["val_converter"] = pl.concat([vsc_inv.select(["r", "t"]), vsc_inv.select([pl.col("rr").alias("r"), "t"])]).unique(maintain_order=True)
    rprm = routes.select(["r", "rr"]).unique()
    level = csw["GSw_PRMTRADE_level"]
    if level == "r":
        rprm = rprm.head(0)
    else:
        lv = S[f"r_{level}"]
        same = lv.join(lv.rename({"r": "rr"}), on=level, how="inner").select(["r", "rr"]).unique()
        rprm = semi(rprm, same, ["r", "rr"])
    S["routes_prm"] = rprm
    tlf = I.par("transmission_line_fom", ["r", "rr", "trtype"])
    vsc_routes = routes.filter(pl.col("trtype") == "vsc").select(["r", "rr"]).unique()
    if vsc_routes.height:
        lcc = tlf.filter(pl.col("trtype") == "lcc").select(["r", "rr", "value"])
        tlf = _assign(tlf, vsc_routes.join(lcc, on=["r", "rr"], how="inner").with_columns(pl.lit("vsc").alias("trtype")).select(["r", "rr", "trtype", "value"]), ["r", "rr", "trtype"])
    S["transmission_line_fom"] = tlf.with_columns(gams_round(pl.col("value"), 3).alias("value"))
    S["tranloss"] = I.par("tranloss", ["r", "rr", "trtype"]).with_columns(gams_round(pl.col("value"), 3).alias("value"))
    tccfm = I.par("trans_cost_cap_fin_mult", ["t"])
    S["trans_cost_cap_fin_mult"] = tccfm.with_columns(pl.when(isin("t", set(t_all["t"]))).then(gams_round(pl.col("value"), 3)).otherwise(pl.col("value")).alias("value"))
    rc = S.r_country
    rr_pairs = routes.select(["r", "rr", "t"]).unique()
    hc = I.par("cost_hurdle_country", ["country"])
    h1 = I.par("cost_hurdle_rate1", ["t"]).rename({"value": "h1"})
    h2 = I.par("cost_hurdle_rate2", ["t"]).rename({"value": "h2"})
    cross_country = (rr_pairs.join(rc, on="r", how="inner").join(rc.rename({"r": "rr", "country": "country2"}), on="rr", how="inner")
                     .filter(pl.col("country") != pl.col("country2")))
    if cross_country.height and hc.height:
        raise NotImplementedError("international hurdle rates are not ported")
    grp1 = rr_pairs.join(h1, on="t", how="left").with_columns(pl.col("h1").fill_null(0.0).alias("g1"))
    grp2 = rr_pairs.join(h2, on="t", how="left").with_columns(pl.col("h2").fill_null(0.0).alias("g2"))
    for lvl, name in ((csw["GSw_TransHurdleLevel1"], "g1"), (csw["GSw_TransHurdleLevel2"], "g2")):
        if lvl == "r":
            continue
        lv = S[f"r_{lvl}"]
        same = lv.join(lv.rename({"r": "rr"}), on=lvl, how="inner").select(["r", "rr"]).unique().with_columns(pl.lit(True).alias("same"))
        if name == "g1":
            grp1 = grp1.join(same, on=["r", "rr"], how="left").with_columns(pl.when(pl.col("same").fill_null(False)).then(0.0).otherwise(pl.col("g1")).alias("g1")).drop("same")
        else:
            grp2 = grp2.join(same, on=["r", "rr"], how="left").with_columns(pl.when(pl.col("same").fill_null(False)).then(0.0).otherwise(pl.col("g2")).alias("g2")).drop("same")
    hurdle = (grp1.select(["r", "rr", "t", "g1"]).join(grp2.select(["r", "rr", "t", "g2"]), on=["r", "rr", "t"], how="inner")
              .with_columns(pl.max_horizontal(pl.col("g1"), pl.col("g2"), pl.lit(sc["hurdle_rate_floor"])).alias("value")).select(["r", "rr", "t", "value"]))
    S["cost_hurdle"] = nonzero(hurdle)

    # ------------------------------------------------------------- upgrade costs and derates
    up_valcap = valcap.filter(isin("i", upgrade))
    cc_to = from_to(S.cost_cap, ["i", "t"], upgrade_to).rename({"value": "to"})
    cc_from = from_to(S.cost_cap, ["i", "t"], upgrade_from).rename({"value": "from"})
    cu = (up_valcap.join(cc_to, on=["i", "t"], how="left").join(cc_from, on=["i", "t"], how="left")
          .with_columns(((pl.col("to").fill_null(0.0) - pl.col("from").fill_null(0.0)) * 1.01).alias("value")).select(V4 + ["value"]))
    gasct = S.cost_cap.filter(pl.col("i") == "gas-ct").select(["t", pl.col("value").alias("cc")])
    gascc = S.cost_cap.filter(pl.col("i") == "gas-cc").select(["t", pl.col("value").alias("cc")])
    h2ct_dom = valcap.filter(pl.col("i") == "gas-ct_h2-ct").select(V4)
    h2ct = h2ct_dom.join(gasct, on="t", how="left").with_columns((pl.col("cc").fill_null(0.0) * sc["cost_upgrade_gasct2h2ct"]).alias("value")).select(V4 + ["value"])
    cu = _assign(cu, h2ct, V4, domain=h2ct_dom)
    from_gascc = set(upgrade_from.filter(isin("ii", members(S.gas_cc)))["i"].to_list())
    h2cc_dom = up_valcap.filter(isin("i", members(S.h2_combustion) & from_gascc) & ~isin("i", members(S.ccs))).select(V4)
    h2cc = h2cc_dom.join(gascc, on="t", how="left").with_columns((pl.col("cc").fill_null(0.0) * sc["cost_upgrade_gascc2h2cc"]).alias("value")).select(V4 + ["value"])
    cu = _assign(cu, h2cc, V4, domain=h2cc_dom)
    upc = pchar("upgradecost")
    cu = _assign(cu, up_valcap.join(upc, on=["i", "t"], how="inner").select(V4 + ["value"]), V4)
    for igcc, newc in (("coal-igcc_coal-ccs_mod", "coal-new_coal-ccs_mod"), ("coal-igcc_coal-ccs_max", "coal-new_coal-ccs_max")):
        src = cu.filter(pl.col("i") == newc).select(["v", "r", "t", "value"])
        dom = valcap.filter(pl.col("i") == igcc).select(V4)
        cu = _assign(cu, dom.join(src, on=["v", "r", "t"], how="inner").select(V4 + ["value"]), V4, domain=dom)
    for hy, key in (("hydend_hyded", "GSw_HydroCostAddDispatch"), ("hyded_pumped-hydro", "GSw_HydroCostAddPump"), ("hyded_pumped-hydro-flex", "GSw_HydroCostAddPump")):
        dom = valcap.filter(pl.col("i") == hy).select(V4)
        cu = _assign(cu, _par_over(dom, float(csw[key])), V4, domain=dom)
    ccs_coal = I.par("upgrade_costs_ccs_coal", ["allt"]).rename({"allt": "t"})
    ccs_gas = I.par("upgrade_costs_ccs_gas", ["allt"]).rename({"allt": "t"})
    for techs, table in ((members(S.coal_ccs), ccs_coal), (members(S.gas_cc_ccs), ccs_gas)):
        dom = up_valcap.filter(isin("i", techs)).select(V4)
        cu = _assign(cu, dom.join(table, on="t", how="inner").with_columns((1e3 * pl.col("value")).alias("value")).select(V4 + ["value"]), V4, domain=dom)
    retro_cost = hint.filter((pl.col("hintage_char") == "wccs_retro_overnightcost") & isin("v", initv)).select(V4 + ["value"])
    rc = semi(retro_cost, valcap, V4).with_columns((sc["upgrade_inflator"] * 1e3 * pl.col("value")).alias("value"))
    cu = _assign(cu, rc, V4)
    cu = cu.with_columns(pl.when(isin("i", upgrade)).then(pl.max_horizontal(pl.lit(0.0), pl.col("value"))).otherwise(pl.col("value")).alias("value"))
    umult = I.par("upgrade_mult_final", ["i", "allt"]).rename({"allt": "t"})
    if not int(sw["Sw_UpgradeATBCosts"]):
        base = (valcap.filter(isin("v", initv) & isin("i", unitspec)).join(upgrade_from, on="i", how="inner")
                .join(cu.rename({"i": "ii"}), on=["ii", "v", "r", "t"], how="inner").group_by(V4).agg(pl.col("value").sum())
                .filter(pl.col("value") != 0.0)
                .join(umult.rename({"value": "um"}), on=["i", "t"], how="left")
                .with_columns((pl.col("um").fill_null(0.0) * pl.col("value")).alias("value")).select(V4 + ["value"]))
        cu = _assign(cu, base, V4)
    S["cost_upgrade"] = nonzero(cu).with_columns(gams_round(pl.col("value"), 2).alias("value"))
    whr = hint.filter((pl.col("hintage_char") == "whr") & isin("v", initv)).select(V4 + [pl.col("value").alias("whr")])
    rhr = hint.filter((pl.col("hintage_char") == "wccs_retro_hr") & isin("v", initv)).select(V4 + [pl.col("value").alias("rhr")])
    ud = (up_valcap.filter(isin("v", initv) & isin("i", members(S.ccs) & unitspec)).join(upgrade_from, on="i", how="inner")
          .join(whr.rename({"i": "ii"}), on=["ii", "v", "r", "t"], how="inner").join(rhr.rename({"i": "ii"}), on=["ii", "v", "r", "t"], how="inner")
          .group_by(V4).agg(pl.max_horizontal(pl.lit(0.0), 1.0 - (pl.col("whr") / pl.col("rhr")).sum()).alias("value")))
    ud = nonzero(ud)
    coal_up = up_valcap.filter(isin("i", members(S.ccs) & members(S.coal)))
    gas_up = up_valcap.filter(isin("i", members(S.ccs) & members(S.gas)))
    ud = pl.concat([ud, anti(coal_up.filter(isin("v", initv)), ud, V4).with_columns(pl.lit(0.29).alias("value")).select(V4 + ["value"]),
                    anti(gas_up.filter(isin("v", initv)), ud, V4).with_columns(pl.lit(0.14).alias("value")).select(V4 + ["value"])])
    ud = _assign(ud, coal_up.filter(isin("v", newv)).with_columns(pl.lit(0.29).alias("value")).select(V4 + ["value"]), V4)
    ud = _assign(ud, gas_up.filter(isin("v", newv)).with_columns(pl.lit(0.14).alias("value")).select(V4 + ["value"]), V4)
    ud = ud.filter(isin("i", members(S.noret_upgrade_tech)))
    if not int(sw["Sw_UpgradeDerate"]):
        ud = ud.head(0)
    S["upgrade_derate"] = ud.with_columns(gams_round(pl.col("value"), 3).alias("value"))

    # ------------------------------------------------------------- supply curve data (m_rsc_dat)
    rsc_dat = S.rsc_dat
    agg_ok = (S.rsc_agg.join(semi(S.valcap_irt, S.tmodel_new, ["t"]).rename({"i": "ii"}), on="ii", how="inner").select(["i", "r"]).unique())
    m = semi(rsc_dat, agg_ok, ["i", "r"]).select(["r", "i", "rscbin", "sc_cat", "value"])
    if int(sw["Sw_ReducedResource"]):
        raise NotImplementedError("Sw_ReducedResource is not ported")
    ilr_map = dict(zip(S.ilr["i"], S.ilr["value"]))
    cap_rows = m.filter(pl.col("sc_cat") == "cap").select(["r", "i", "rscbin"])
    upv_cost = (semi(m.filter((pl.col("sc_cat") == "cost") & isin("i", members(S.upv) | members(S.pvb))), cap_rows, ["r", "i", "rscbin"])
                .with_columns((pl.col("value") / pl.col("i").replace_strict(ilr_map, default=1.0)).alias("value")))
    m = _assign(m, upv_cost, ["r", "i", "rscbin", "sc_cat"])
    cost = m.filter(pl.col("sc_cat") == "cost").select(["r", "i", "rscbin", pl.col("value").alias("cost")])
    cost_cap = m.filter(pl.col("sc_cat") == "cost_cap").select(["r", "i", "rscbin", pl.col("value").alias("cc")])
    ct = (cost.filter(~isin("i", members(S.sccapcosttech))).join(cost_cap, on=["r", "i", "rscbin"], how="left")
          .with_columns((pl.col("cost") - pl.col("cc").fill_null(0.0)).alias("value"), pl.lit("cost_trans").alias("sc_cat")).select(["r", "i", "rscbin", "sc_cat", "value"]))
    m = _assign(m, ct, ["r", "i", "rscbin", "sc_cat"])
    cer = S.capacity_exog_rsc.filter(pl.col("t") == str(S.years[0]))
    exog_bin = (S.rsc_agg.join(cer.rename({"i": "ii"}), on="ii", how="inner").filter(isin("i", members(S.exog_rsc)))
                .group_by(["r", "i", "rscbin"]).agg(pl.col("value").sum().alias("exog")))
    capm = m.filter(pl.col("sc_cat") == "cap")
    short = (capm.join(exog_bin, on=["r", "i", "rscbin"], how="inner").filter(isin("i", members(S.rsc_i)) & (pl.col("value") < pl.col("exog")))
             .with_columns(((pl.col("exog") * 1000.0).ceil() / 1000.0).alias("value"), pl.lit("cap").alias("sc_cat")).select(["r", "i", "rscbin", "sc_cat", "value"]))
    missing_short = (anti(exog_bin, capm, ["r", "i", "rscbin"]).filter(isin("i", members(S.rsc_i)))
                     .with_columns(((pl.col("exog") * 1000.0).ceil() / 1000.0).alias("value"), pl.lit("cap").alias("sc_cat")).select(["r", "i", "rscbin", "sc_cat", "value"]))
    m = _assign(m, pl.concat([short, missing_short]), ["r", "i", "rscbin", "sc_cat"])
    cap_existing = fsum_by(cer.filter(isin("i", members(S.exog_rsc))), ["i", "r"]).rename({"value": "exist"})
    cap_prescribed = fsum_by(semi(S.prescribed_build, S.tmodel_new, ["t"]).filter(isin("i", members(S.rsc_i))), ["i", "r", "t"])
    S["cap_prescribed"] = cap_prescribed
    cap_prescribed_ir = fsum_by(cap_prescribed, ["i", "r"]).rename({"value": "presc"})
    has_newv = valcap.filter(isin("v", newv)).select(["i", "r"]).unique()
    avail_supply = (fsum_by(m.filter(pl.col("sc_cat") == "cap"), ["i", "r"]).rename({"value": "avail"})
                    .filter(isin("i", members(S.rsc_i)) & (pl.col("i") != "geothermal")))
    avail_supply = semi(avail_supply, has_newv, ["i", "r"])
    need = (avail_supply.join(cap_existing, on=["i", "r"], how="left").join(cap_prescribed_ir, on=["i", "r"], how="left")
            .with_columns((pl.col("exist").fill_null(0.0) + pl.col("presc").fill_null(0.0)).alias("need"))
            .filter((pl.col("need") > pl.col("avail")) & (pl.col("avail") != 0)).with_columns((pl.col("need") / pl.col("avail")).alias("mult")).select(["i", "r", "mult"]))
    scaled = (m.filter(pl.col("sc_cat") == "cap").join(need, on=["i", "r"], how="inner")
              .with_columns((pl.col("value") * pl.col("mult")).alias("value")).select(["r", "i", "rscbin", "sc_cat", "value"]))
    m = _assign(m, scaled, ["r", "i", "rscbin", "sc_cat"])
    no_supply = (cap_prescribed_ir.filter(pl.col("presc") > 0).join(semi(has_newv, S.rsc_i, ["i"]), on=["i", "r"], how="semi")
                 .filter(pl.col("i") != "geothermal"))
    no_supply = anti(no_supply, avail_supply.filter(pl.col("avail") != 0), ["i", "r"])
    bin1 = no_supply.with_columns(pl.lit("bin1").alias("rscbin"), pl.lit("cap").alias("sc_cat"), pl.col("presc").alias("value")).select(["r", "i", "rscbin", "sc_cat", "value"])
    m = _assign(m, bin1, ["r", "i", "rscbin", "sc_cat"])
    m = m.with_columns(pl.when(pl.col("sc_cat") == "cap").then((pl.col("value") * 1000.0).ceil() / 1000.0).otherwise(pl.col("value")).alias("value"))
    gdf = I.par("geo_discovery_factor", ["i", "r"]).rename({"value": "f"})
    gdr = I.par("geo_discovery_rate", ["allt"]).rename({"allt": "t", "value": "rate"})
    geo_disc = (S.geo_hydro.join(S.r, how="cross").join(S.tmodel_new, how="cross").join(gdf, on=["i", "r"], how="left").join(gdr, on="t", how="left")
                .with_columns(((1.0 - pl.col("f").fill_null(0.0)) * pl.col("rate").fill_null(0.0) + pl.col("f").fill_null(0.0)).alias("value")).select(["i", "r", "t", "value"]))
    geo_disc = nonzero(geo_disc)
    presc_geo = cap_prescribed_ir.filter(isin("i", members(S.geo_hydro)) & (pl.col("presc") != 0)).select(["i", "r"])
    fill1 = anti(presc_geo.join(S.tmodel_new, how="cross"), geo_disc, ["i", "r", "t"]).with_columns(pl.lit(1.0).alias("value"))
    geo_disc = pl.concat([geo_disc, fill1.select(["i", "r", "t", "value"])])
    S["geo_discovery"] = geo_disc
    cum_presc = (cap_prescribed.rename({"t": "tt"}).join(S.tmodel_new, how="cross").filter(yr("tt") <= yr("t")).group_by(["i", "r", "t"]).agg(pl.col("value").sum().alias("cum")))
    ratio = (geo_disc.join(cum_presc, on=["i", "r", "t"], how="inner").with_columns((pl.col("cum") / pl.col("value")).alias("q")).group_by(["i", "r"]).agg(pl.col("q").max().alias("qmax")))
    tot_cap = m.filter(pl.col("sc_cat") == "cap").group_by(["i", "r"]).agg(pl.col("value").sum().alias("tot"))
    gba = (ratio.join(tot_cap, on=["i", "r"], how="left").join(cap_existing, on=["i", "r"], how="left")
           .with_columns((pl.col("qmax") - (pl.col("tot").fill_null(0.0) - pl.col("exist").fill_null(0.0))).alias("add"))
           .filter(pl.col("add") > 0).select(["i", "r", "add"]))
    S["geo_bin1_add"] = gba.rename({"add": "value"})
    S["cap_existing"] = cap_existing.rename({"exist": "value"})
    S["available_supply"] = avail_supply.rename({"avail": "value"})
    S["m_rsc_dat_before_geo"] = m.filter(pl.col("sc_cat") == "cap")
    if gba.height:
        b1 = (m.filter((pl.col("sc_cat") == "cap") & (pl.col("rscbin") == "bin1")).join(gba, on=["i", "r"], how="inner")
              .with_columns((pl.col("value") + pl.col("add")).alias("value")).select(["r", "i", "rscbin", "sc_cat", "value"]))
        m = _assign(m, b1, ["r", "i", "rscbin", "sc_cat"])
    dr_scalar = I.par("dr_shed_capacity_scalar", ["i", "r", "allt"]).rename({"allt": "t"})
    rcs = (geo_disc.join(dr_scalar.rename({"value": "dr"}), on=["i", "r", "t"], how="full", coalesce=True)
           .with_columns(((1000.0 * pl.col("value").fill_null(0.0) + pl.col("dr").fill_null(0.0)).ceil() / 1000.0).alias("value")).select(["i", "r", "t", "value"]))
    S["rsc_capacity_scalar"] = semi(nonzero(rcs), t_all, ["t"])
    S["rsc_capacity_scalar_i"] = S.rsc_capacity_scalar.select("i").unique()
    S["m_rsc_con"] = m.filter(pl.col("sc_cat") == "cap").group_by(["r", "i"]).agg(pl.col("value").sum()).filter(pl.col("value") != 0).select(["r", "i"])
    feas = m.filter(pl.col("sc_cat") == "cap").select(["r", "i", "rscbin"]).unique()
    irt = semi(S.valcap_irt, S.tmodel_new, ["t"]).select(["i", "r"]).unique()
    extra = (S.tg_rsc_cspagg.rename({"i": "ii", "ii": "i"}).join(feas.rename({"i": "ii"}), on="ii", how="inner").select(["r", "i", "rscbin"]).unique())
    feas = pl.concat([feas, semi(extra, irt, ["i", "r"])]).unique()
    S["m_rscfeas"] = feas
    hydmult_cap, hydmult_cost = float(csw["GSw_HydroUpgradeCapMult"]), float(csw["GSw_HydroUpgradeCostMult"])
    m = m.with_columns(pl.when(isin("i", {"hydud", "hydund"}) & (pl.col("sc_cat") == "cap")).then(pl.col("value") * hydmult_cap)
                       .when(isin("i", {"hydud", "hydund"}) & (pl.col("sc_cat") == "cost")).then(pl.col("value") * hydmult_cost)
                       .otherwise(pl.col("value")).alias("value"))
    S["m_rsc_dat_init"] = nonzero(m.filter(pl.col("sc_cat") == "cap").select(["r", "i", "rscbin", "value"]))
    m = m.with_columns(pl.when(pl.col("sc_cat") == "cap").then((pl.col("value") * 1000.0).ceil() / 1000.0)
                       .when(isin("sc_cat", {"cost", "cost_trans"})).then(gams_round(pl.col("value"), 2))
                       .otherwise(pl.col("value")).alias("value"))
    S["m_rsc_dat"] = nonzero(m)
    S["hyd_add_upg_cap"] = I.par("hyd_add_upg_cap", ["r", "i", "rscbin", "allt"]).rename({"allt": "t"})
    S["allow_cap_up"] = pl.DataFrame({c: pl.Series([], dtype=pl.Utf8) for c in ["i", "v", "r", "rscbin", "t"]})
    if int(csw["GSw_HydroCapEnerUpgradeType"]) == 2:
        raise NotImplementedError("decoupled hydro capacity/energy upgrades are not ported")
    return S
