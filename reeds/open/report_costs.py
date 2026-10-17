from __future__ import annotations

import polars as pl

from .derive import anti, isin, members, semi
from .report_core import Helpers, add, div, empty, lit, mul, nz, scale, sub, total, val

V4 = ["i", "v", "r", "t"]

SYS_COSTS = [
    "inv_co2_network_pipe", "inv_co2_network_spur", "inv_converter_costs", "inv_dac", "inv_h2_pipeline", "inv_h2_production",
    "inv_h2_storage", "inv_investment_capacity_costs", "inv_investment_refurbishment_capacity",
    "inv_investment_spurline_costs_rsc_technologies", "inv_investment_water_access", "inv_itc_payments_negative",
    "inv_itc_payments_negative_refurbishments", "inv_spurline_investment", "inv_transmission_interzone_ac_investment",
    "inv_transmission_interzone_dc_investment", "inv_transmission_intrazone_investment", "op_acp_compliance_costs",
    "op_co2_incentive_negative", "op_co2_network_fom_pipe", "op_co2_network_fom_spur", "op_co2_storage", "op_co2_transport_storage",
    "op_consume_fom", "op_consume_vom", "op_emissions_taxes", "op_fom_costs", "op_fuelcosts_objfn", "op_h2combustion_fuel_costs",
    "op_h2_fuel_costs", "op_h2_revenue_exog", "op_h2_transport", "op_h2_transport_intrareg", "op_h2_storage", "op_h2_vom",
    "op_h2_ptc_payments_negative", "op_operating_reserve_costs", "op_ptc_payments_negative", "op_rect_fuel_costs", "op_spurline_fom",
    "op_startcost", "op_transmission_fom", "op_transmission_intrazone_fom", "op_vom_costs",
]
SYS_COSTS_INV = [c for c in SYS_COSTS if c.startswith("inv_")]
SYS_COSTS_OP = [c for c in SYS_COSTS if c.startswith("op_")]


def _cat(df: pl.DataFrame, cat: str, dims: list[str]) -> pl.DataFrame:
    return df.select([pl.lit(cat).alias("sys_costs")] + [pl.col(d) for d in dims] + [pl.col("value")])


# ----------------------------------------------------------------------------- capex and tech|BA system costs
def capex_and_techba(H: Helpers, R: dict) -> None:
    S, C = H.S, H.C
    inv = semi(H.L("INV"), S.valcap, V4)
    inv_energy = semi(H.L("INV_ENERGY"), S.valcap, V4)
    inv_rsc = semi(H.L("INV_RSC"), S.valcap, V4).join(S.m_rscfeas, on=["r", "i", "rscbin"], how="semi")
    refurb = semi(H.L("INV_REFURB"), S.valcap, V4).filter(isin("i", H.set_members("refurbtech"))) if H.swi("Sw_Refurb") else empty(V4)
    upgrades = semi(H.L("UPGRADES"), S.valcap, V4).filter(isin("i", H.set_members("upgrade"))) if H.swi("Sw_Upgrades") else empty(V4)
    ncr = S.cost_cap_fin_mult_no_credits
    rsc_cost = S.m_rsc_dat.filter(pl.col("sc_cat") == "cost").select(["r", "i", "rscbin", "value"])
    capex = add([mul(mul(inv, ncr, ["i", "r", "t"]), S.cost_cap, ["i", "t"]),
                 mul(mul(inv_energy, ncr, ["i", "r", "t"]), S.cost_cap_energy, ["i", "t"]),
                 total(mul(mul(inv_rsc, rsc_cost, ["r", "i", "rscbin"]), ncr, ["i", "r", "t"]), V4),
                 mul(mul(refurb, ncr, ["i", "r", "t"]), S.cost_cap, ["i", "t"]),
                 mul(mul(upgrades, S.cost_upgrade, V4), ncr, ["i", "r", "t"])], V4)
    R["capex_ivrt"] = nz(capex)

    inv_v = semi(H.L("INV"), S.valinv, V4)
    inv_e = semi(H.L("INV_ENERGY"), S.valinv, V4).filter(isin("i", H.set_members("battery")))
    rsc = H.set_members("rsc_i")
    scc = H.set_members("sccapcosttech")
    spur = H.set_members("spur_techs")
    inv_rsc_v = semi(H.L("INV_RSC"), S.valinv, V4).join(S.m_rscfeas, on=["r", "i", "rscbin"], how="semi").filter(isin("i", rsc))
    mrd = lambda cat: S.m_rsc_dat.filter(pl.col("sc_cat") == cat).select(["r", "i", "rscbin", "value"])  # noqa: E731
    inv_cap_up = semi(H.L("INV_CAP_UP"), S.allow_cap_up, V4 + ["rscbin"]) if S.allow_cap_up.height else empty(V4 + ["rscbin"])
    inv_ener_up = semi(H.L("INV_ENER_UP"), S.allow_ener_up, V4 + ["rscbin"]) if S.allow_ener_up.height else empty(V4 + ["rscbin"])
    irt = ["i", "r", "t"]

    def capacity_costs(fin: pl.DataFrame, rsc_fin: pl.DataFrame) -> pl.DataFrame:
        parts = [mul(mul(inv_v, fin, irt), S.cost_cap, ["i", "t"]),
                 mul(mul(inv_e, fin, irt), S.cost_cap_energy, ["i", "t"]),
                 mul(mul(inv_rsc_v.filter(~isin("i", scc) & ~isin("i", spur)), mrd("cost_cap"), ["r", "i", "rscbin"]), rsc_fin, irt),
                 mul(mul(inv_rsc_v.filter(isin("i", scc)), mrd("cost"), ["r", "i", "rscbin"]), rsc_fin, irt),
                 mul(mul(upgrades, S.cost_upgrade, V4), fin, irt),
                 mul(mul(inv_cap_up, fin, irt), S.cap_cap_up, V4 + ["rscbin"]) if inv_cap_up.height else empty(V4),
                 mul(mul(inv_ener_up, fin, irt), S.cap_ener_up, V4 + ["rscbin"]) if inv_ener_up.height else empty(V4)]
        return total(add(parts, V4), irt)

    def spurline_costs(rsc_fin: pl.DataFrame) -> pl.DataFrame:
        return total(mul(mul(inv_rsc_v.filter(~isin("i", scc) & ~isin("i", spur)), mrd("cost_trans"), ["r", "i", "rscbin"]), rsc_fin, irt), irt)

    tb: dict[str, pl.DataFrame] = {}
    cap_noitc = capacity_costs(S.cost_cap_fin_mult_noITC, S.rsc_fin_mult_noITC)
    spur_noitc = spurline_costs(S.rsc_fin_mult_noITC)
    tb["inv_investment_capacity_costs"] = cap_noitc
    tb["inv_investment_spurline_costs_rsc_technologies"] = spur_noitc
    tb["inv_itc_payments_negative"] = add([capacity_costs(S.cost_cap_fin_mult_out, S.rsc_fin_mult), scale(cap_noitc, -1.0),
                                           spurline_costs(S.rsc_fin_mult), scale(spur_noitc, -1.0)], irt)
    dac = H.set_members("dac")
    h2 = H.set_members("h2")
    consume = H.set_members("consume")
    tb["inv_dac"] = cap_noitc.filter(isin("i", dac))
    tb["inv_h2_production"] = cap_noitc.filter(isin("i", h2))
    tb["inv_investment_capacity_costs"] = cap_noitc.filter(~isin("i", consume))
    refurb_v = semi(H.L("INV_REFURB"), S.valinv, V4).filter(isin("i", H.set_members("refurbtech"))) if H.swi("Sw_Refurb") else empty(V4)
    ref_noitc = total(mul(mul(refurb_v, S.cost_cap_fin_mult_noITC, irt), S.cost_cap, ["i", "t"]), irt)
    tb["inv_investment_refurbishment_capacity"] = ref_noitc
    tb["inv_itc_payments_negative_refurbishments"] = add([total(mul(mul(refurb_v, S.cost_cap_fin_mult_out, irt), S.cost_cap, ["i", "t"]), irt),
                                                          scale(ref_noitc, -1.0)], irt)
    if H.swi("Sw_WaterMain"):
        raise NotImplementedError("water access costs are not ported")
    tb["inv_investment_water_access"] = empty(irt)

    gen = semi(H.L("GEN", rep=True), S.valgen, V4)
    hrs = H.hours.rename({"hours": "value"})
    gen_h = mul(gen, hrs, ["h"])
    vom = total(mul(gen_h, S.cost_vom, V4), irt)
    produce = semi(H.L("PRODUCE", rep=True), S.valcap, V4).join(S.i_p, on=["i", "p"], how="semi")
    prod_h = mul(produce, hrs, ["h"])
    if H.swi("Sw_Prod"):
        vom = add([vom, total(mul(prod_h.filter(isin("i", h2 | dac)), S.cost_prod, V4), irt)], irt)
    tb["op_consume_vom"] = vom.filter(isin("i", consume))
    tb["op_vom_costs"] = vom.filter(~isin("i", consume))
    one_newv = H.set_members("one_newv")
    cap_ivrt = R["_cap_ivrt"]
    ilr = val(S.ilr, "ilr")
    ret_rows = S.retiretech.select(V4)
    fom_a = semi(cap_ivrt, pl.concat([S.valcap.filter(~isin("i", one_newv)).select(V4), ret_rows]).unique(), V4)
    fom_a = mul(mul(fom_a, S.cost_fom, V4), S.ilr, ["i"])
    solved = C.tmodel_new.rename({"t": "tt"})
    cond = semi(S.inv_cond.filter(isin("i", one_newv)), solved, ["tt"])
    cond = anti(cond, S.retiretech.rename({"t": "tt"}), ["i", "v", "r", "tt"])
    inv_tt = val(H.L("INV"), "iv").rename({"t": "tt"})
    inve_tt = val(H.L("INV_ENERGY"), "iv").rename({"t": "tt"})
    fom_tt = val(S.cost_fom, "f").rename({"t": "tt"})
    fome_tt = val(S.cost_fom_energy, "f").rename({"t": "tt"})
    fom_b = (cond.join(inv_tt, on=["i", "v", "r", "tt"], how="inner").join(fom_tt, on=["i", "v", "r", "tt"], how="inner").join(ilr, on="i", how="inner")
             .with_columns((pl.col("iv") * pl.col("f") * pl.col("ilr")).alias("value")))
    fom_c = (cond.join(inve_tt, on=["i", "v", "r", "tt"], how="inner").join(fome_tt, on=["i", "v", "r", "tt"], how="inner").join(ilr, on="i", how="inner")
             .with_columns((pl.col("iv") * pl.col("f") * pl.col("ilr")).alias("value")))
    fom = total(add([total(fom_a, V4), total(fom_b, V4), total(fom_c, V4)], V4), irt)
    tb["op_consume_fom"] = fom.filter(isin("i", consume))
    tb["op_fom_costs"] = fom.filter(~isin("i", consume))
    opres = semi(H.L("OPRES", rep=True), S.valgen, V4)
    tb["op_operating_reserve_costs"] = total(mul(mul(opres, hrs, ["h"]), S.cost_opres, ["i", "ortype", "t"]), irt)

    gas, bio, cofire = H.set_members("gas"), H.set_members("bio"), H.set_members("cofire")
    h2_gen = H.set_members("h2_gen")
    hr = val(S.heat_rate, "hr")
    fp = val(S.fuel_price, "fp")
    sw_h2 = H.swi("Sw_H2")
    stress = members(S.h_stress)
    f1 = (gen_h.filter(~isin("i", gas) & ~isin("i", bio) & ~isin("i", cofire))
          .filter(~isin("i", h2_gen) | (pl.lit(sw_h2 == 0)) | isin("h", stress))
          .join(hr, on=V4, how="inner").join(fp, on=irt, how="inner")
          .with_columns((pl.col("value") * pl.col("hr") * pl.col("fp")).alias("value")))
    coal_fp = val(S.fuel_price.filter(pl.col("i") == "coal-new").select(["r", "t", "value"]), "fp")
    f2 = (gen_h.filter(isin("i", cofire)).join(hr, on=V4, how="inner").join(coal_fp, on=["r", "t"], how="inner")
          .with_columns(((1.0 - H.scalar("bio_cofire_perc")) * pl.col("value") * pl.col("hr") * pl.col("fp")).alias("value")))
    r_cendiv = S.hierarchy.select(["r", "cendiv"]).unique()
    f3 = total(mul(r_cendiv.join(R["gascost_cendiv"], on="cendiv", how="inner").select(["r", "cendiv", "t", "value"]), R["gasshare_techba"], ["r", "cendiv", "t"]), irt)
    bioused = H.L("BIOUSED")
    bec = H.scalar("bio_energy_content")
    btc = H.swf("Sw_BioTransportCost") / bec
    price_r = S.r_usda.join(S.biosupply_price, on="usda_region", how="inner").select(["r", "bioclass", "value"])
    bio_cost = total(bioused.join(val(price_r, "p"), on=["r", "bioclass"], how="left").with_columns((pl.col("value") * (pl.col("p").fill_null(0.0) + btc)).alias("value")), ["r", "t"])
    f4 = mul(R["bioshare_techba"], bio_cost, ["r", "t"])
    tb["op_fuelcosts_objfn"] = add([total(f1, irt), total(f2, irt), f3, f4], irt)
    if S.emit_tax.height:
        raise NotImplementedError("emission taxes are not ported")
    tb["op_emissions_taxes"] = empty(irt)
    tb["op_h2_fuel_costs"] = empty(irt)
    if "h2_fuel_cost" in S and S.h2_fuel_cost.height:
        raise NotImplementedError("h2_fuel_cost is not ported")
    comb = (gen_h.filter(isin("i", h2_gen)).join(hr, on=V4, how="inner")
            .with_columns((pl.col("value") * pl.col("hr") * H.scalar("h2_combustion_intensity")).alias("value")))
    if sw_h2 == 2:
        m = val(H.M("eq_h2_demand_regional"), "m")
        comb = (comb.join(m, on=["r", "h", "t"], how="left").join(H.hours, on="h", how="inner")
                .with_columns((pl.col("value") * pl.col("m").fill_null(0.0) / pl.col("hours")).alias("value")))
        tb["op_h2combustion_fuel_costs"] = mul(total(comb, irt), H.inv_pvf, ["t"])
    elif sw_h2 == 1:
        m = val(H.M("eq_h2_demand").filter(pl.col("p") == "h2"), "m").select(["t", "m"])
        tb["op_h2combustion_fuel_costs"] = mul(total(comb.join(m, on="t", how="left").with_columns((pl.col("value") * pl.col("m").fill_null(0.0)).alias("value")), irt), H.inv_pvf, ["t"])
    else:
        tb["op_h2combustion_fuel_costs"] = empty(irt)
    tb["op_h2_vom"] = empty(irt)
    if "h2_vom" in S and S.h2_vom.height:
        raise NotImplementedError("h2_vom is not ported")
    if not H.swi("Sw_CO2_Detail"):
        tb["op_co2_transport_storage"] = scale(R["emit_captured_irt"], H.swf("Sw_CO2_Storage"))
    else:
        tb["op_co2_transport_storage"] = empty(irt)
    crf_ratio = S.crf.join(val(S.crf_co2_incentive, "c"), on="t", how="inner").with_columns((pl.col("value") / pl.col("c")).alias("value")).select(["t", "value"])
    capr = S.capture_rate.filter(pl.col("e") == "co2").select(V4 + ["value"])
    inc = S.co2_captured_incentive
    g_inc = total(mul(mul(mul(gen_h, inc, V4), capr, V4), crf_ratio, ["t"]), irt)
    p_inc = total(mul(mul(prod_h.filter(isin("i", dac)), inc, V4), crf_ratio, ["t"]), irt)
    tb["op_co2_incentive_negative"] = scale(add([g_inc, p_inc], irt), -1.0)
    ptc = mul(S.ptc_value_scaled, S.tc_phaseout_mult, ["i", "v", "t"])
    tb["op_ptc_payments_negative"] = scale(total(mul(gen_h, ptc, ["i", "v", "t"]), irt), -1.0)
    tb["op_h2_ptc_payments_negative"] = empty(irt)
    if H.swi("Sw_H2_PTC") and sw_h2:
        ptc_years = members(S.h2_ptc_years)
        start = H.scalar("h2_demand_start")
        el = (prod_h.filter((pl.col("i") == "electrolyzer") & (pl.col("p") == "h2") & isin("t", ptc_years)).filter(pl.col("t").cast(pl.Int64) >= start)
              .join(val(S.h2_ptc, "ptc"), on=V4, how="inner").join(val(S.crf, "crf"), on="t", how="inner").join(val(S.crf_h2_incentive, "ci"), on="t", how="inner")
              .with_columns((pl.col("value") * pl.col("crf") / pl.col("ci") * pl.col("ptc") * 1e3).alias("value")))
        tb["op_h2_ptc_payments_negative"] = scale(total(el, irt), -1.0)
    tb["op_startcost"] = empty(irt)
    if H.swi("Sw_StartCost"):
        ramp = semi(H.L("RAMPUP"), S.valgen_irt, irt)
        ramp = (ramp.join(val(S.numhours_nexth, "n"), on=["h", "hh"], how="inner").join(val(S.startcost, "sc"), on="i", how="inner")
                .with_columns((pl.col("sc") * pl.col("n") * pl.col("value")).alias("value")))
        tb["op_startcost"] = total(ramp, irt)
    for name in ["op_h2_revenue_exog", "op_rect_fuel_costs"]:
        tb[name] = empty(irt)
    techba = pl.concat([_cat(nz(df), k, irt) for k, df in tb.items() if df.height])
    R["systemcost_techba"] = techba
    undisc = val(S.pvf_onm_undisc, "u")
    bulk = techba.join(undisc, on="t", how="left").with_columns(
        pl.when(isin("sys_costs", set(SYS_COSTS_OP))).then(pl.col("value") * pl.col("u").fill_null(0.0)).otherwise(pl.col("value")).alias("value")).drop("u")
    R["systemcost_techba_bulk"] = nz(bulk)
    ew = pl.concat([bulk.filter(isin("sys_costs", set(SYS_COSTS_OP)) & (pl.col("t") != C.tlast)), techba.filter(isin("sys_costs", set(SYS_COSTS_INV)) | (pl.col("t") == C.tlast))])
    R["systemcost_techba_bulk_ew"] = nz(ew)
    R["_techba"] = tb


# ----------------------------------------------------------------------------- BA-level and national system costs
def systemcost_ba(H: Helpers, R: dict) -> None:
    S, C = H.S, H.C
    rt = ["r", "t"]
    ba: dict[str, pl.DataFrame] = {}
    for cat, df in R["_techba"].items():
        ba[cat] = total(df, rt)
    tcfm = val(S.trans_cost_cap_fin_mult, "m")
    aclike = members(S.aclike)
    lcclike = members(S.lcclike)
    invtran = semi(H.L("INVTRAN"), S.routes_inv, ["r", "rr", "trtype", "t"])
    dc = (invtran.filter(~isin("trtype", aclike)).join(tcfm, on="t", how="inner").join(val(S.transmission_cost_nonac, "c"), on=["r", "rr", "trtype"], how="inner")
          .with_columns((pl.col("m") * pl.col("c") * pl.col("value") / 2.0).alias("value")))
    ba["inv_transmission_interzone_dc_investment"] = total(dc, rt)
    binw = S._inputs.par("tsc_binwidth", ["r", "rr", "tscbin"]).filter(pl.col("value") != 0.0)
    bins = H.L("TRAN_CAPEX_BINS")
    ac_routes = S.routes_inv.filter(pl.col("trtype") == "ac").select(["r", "rr", "t"])
    rows = semi(semi(bins, ac_routes, ["r", "rr", "t"]), binw, ["r", "rr", "tscbin"])
    capex_ac = add([total(rows, rt), total(rows, ["rr", "t"]).rename({"rr": "r"})], rt)
    capex_ac = scale(mul(capex_ac, S.trans_cost_cap_fin_mult, ["t"]), 0.5)
    tprev = C.tprev()
    ac_inv = (capex_ac.join(tprev, on="t", how="inner").join(val(capex_ac, "p").rename({"t": "tt"}), on=["r", "tt"], how="left")
              .with_columns((pl.col("value") - pl.col("p").fill_null(0.0)).alias("value")).select(rt + ["value"]))
    ba["inv_transmission_interzone_ac_investment"] = ac_inv
    R["_capex_transmission_interzone_ac"] = capex_ac
    intra = H.swf("Sw_TransIntraCost")
    inv_poi = H.L("INV_POI")
    ba["inv_transmission_intrazone_investment"] = scale(mul(inv_poi, S.trans_cost_cap_fin_mult, ["t"]), intra * 1000.0) if intra else empty(rt)
    captran = semi(H.L("CAPTRAN_ENERGY"), S.routes, ["r", "rr", "trtype", "t"])
    fom_line = scale(total(mul(captran, S.transmission_line_fom, ["r", "rr", "trtype"]), rt), 0.5)
    trans_fom_frac = H.scalar("trans_fom_frac")
    fom_lcc = scale(total(captran.filter(isin("trtype", lcclike)), rt), H.scalar("cost_acdc_lcc") * trans_fom_frac)
    fom_vsc = scale(H.L("CAP_CONVERTER"), H.scalar("cost_acdc_vsc") * trans_fom_frac)
    ba["op_transmission_fom"] = add([fom_line, fom_lcc, fom_vsc], rt)
    cum_poi = (inv_poi.rename({"t": "tt"}).join(C.tmodel_new, how="cross").filter(pl.col("tt").cast(pl.Int64) <= pl.col("t").cast(pl.Int64)))
    ba["op_transmission_intrazone_fom"] = scale(total(cum_poi, rt), intra * 1000.0 * trans_fom_frac) if intra else empty(rt)
    conv = scale(total(mul(invtran.filter(isin("trtype", lcclike)), S.trans_cost_cap_fin_mult, ["t"]), rt), H.scalar("cost_acdc_lcc"))
    conv_vsc = scale(mul(H.L("INV_CONVERTER"), S.trans_cost_cap_fin_mult, ["t"]), H.scalar("cost_acdc_vsc"))
    ba["inv_converter_costs"] = add([conv, conv_vsc], rt)
    xr_feas = S.x_r.join(S.xfeas, on="x", how="semi")
    if H.swi("Sw_SpurScen"):
        inv_spur = mul(H.L("INV_SPUR"), S.spurline_cost, ["x"]).join(xr_feas, on="x", how="inner")
        ba["inv_spurline_investment"] = scale(total(inv_spur, rt), float(H.S.sw["Sw_SpurCostMult"]))
        cap_spur = mul(H.L("CAP_SPUR"), S.spurline_cost, ["x"]).join(xr_feas, on="x", how="inner")
        fom_spur = scale(total(cap_spur, rt), trans_fom_frac)
    else:
        ba["inv_spurline_investment"] = empty(rt)
        fom_spur = empty(rt)
    rsc, spur, scc = H.set_members("rsc_i"), H.set_members("spur_techs"), H.set_members("sccapcosttech")
    cap_rsc = (semi(H.L("CAP_RSC"), S.valcap, V4).join(S.m_rscfeas, on=["r", "i", "rscbin"], how="semi")
               .filter(isin("i", rsc) & ~isin("i", spur) & ~isin("i", scc)))
    ct = S.m_rsc_dat.filter(pl.col("sc_cat") == "cost_trans").select(["r", "i", "rscbin", "value"])
    ba["op_spurline_fom"] = add([fom_spur, scale(total(mul(cap_rsc, ct, ["r", "i", "rscbin"]), rt), trans_fom_frac)], rt)
    if H.swi("Sw_CO2_Detail"):
        raise NotImplementedError("CO2 network costs are not ported")
    for name in ["inv_co2_network_pipe", "inv_co2_network_spur", "op_co2_storage", "op_co2_network_fom_pipe", "op_co2_network_fom_spur"]:
        ba[name] = empty(rt)
    sw_h2 = H.swi("Sw_H2")
    if sw_h2 == 2:
        h2inv = H.L("H2_TRANSPORT_INV")
        ba["inv_h2_pipeline"] = total(mul(semi(h2inv, S.h2_routes_inv, ["r", "rr"]), S.cost_h2_transport_cap, ["r", "rr", "t"]), rt)
        ba["inv_h2_storage"] = total(mul(semi(H.L("H2_STOR_INV"), S.h2_stor_r, ["h2_stor", "r"]), S.cost_h2_storage_cap, ["h2_stor", "t"]), rt)
        ba["op_h2_transport"] = total(mul(semi(h2inv, S.h2_routes_inv, ["r", "rr"]), S.cost_h2_transport_fom, ["r", "rr", "t"]), rt)
        ba["op_h2_storage"] = total(mul(semi(H.L("H2_STOR_CAP"), S.h2_stor_r, ["h2_stor", "r"]), S.cost_h2_storage_fom, ["h2_stor", "t"]), rt)
    else:
        for name in ["inv_h2_pipeline", "inv_h2_storage", "op_h2_transport", "op_h2_storage"]:
            ba[name] = empty(rt)
    if sw_h2:
        produce = semi(H.L("PRODUCE", rep=True), S.valcap, V4).filter(isin("v", H.newv) & (pl.col("p") == "h2"))
        produce = produce.join(S.i_p.filter(pl.col("p") == "h2"), on=["i", "p"], how="semi")
        ba["op_h2_transport_intrareg"] = scale(total(mul(produce, H.hours.rename({"hours": "value"}), ["h"]), rt), H.swf("Sw_H2_IntraReg_Transport") * 1e3)
    else:
        ba["op_h2_transport_intrareg"] = empty(rt)
    acp = H.L("ACP_PURCHASES")
    q_rps = R["reqt_quant"].filter(pl.col("cat") == "state_rps").select([pl.col("sub").alias("rpscat"), "r", "t", "value"])
    stfeas = members(S.stfeas)
    q_st = total(S.r_st.join(q_rps, on="r", how="inner"), ["rpscat", "st", "t"])
    acp_st = (acp.filter(isin("st", stfeas)).join(val(S.acp_price, "p"), on=["st", "t"], how="inner").join(S.recperc.select(["rpscat", "st", "t"]), on=["rpscat", "st", "t"], how="semi")
              .join(val(q_st, "q"), on=["rpscat", "st", "t"], how="inner").filter(pl.col("q") != 0.0)
              .with_columns((pl.col("p") * pl.col("value") / pl.col("q")).alias("value")).select(["rpscat", "st", "t", "value"]))
    acp_r = total(mul(S.r_st.join(acp_st, on="st", how="inner"), q_rps, ["rpscat", "r", "t"]), rt)
    vol = (acp.filter(pl.col("st") == "voluntary").join(S.recperc.filter(pl.col("st") == "voluntary").select(["rpscat", "t"]), on=["rpscat", "t"], how="semi")
           .join(val(S.acp_price.filter(pl.col("st") == "voluntary"), "p"), on=["st", "t"], how="inner")
           .with_columns((pl.col("p") * pl.col("value")).alias("value")))
    vol_r = mul(S.r.join(total(vol, ["t"]), how="cross"), R["load_frac_rt"], rt)
    first_rps = H.scalar("firstyear_rps")
    ba["op_acp_compliance_costs"] = add([acp_r, vol_r], rt).filter(pl.col("t").cast(pl.Int64) >= first_rps)
    ba["op_co2_incentive_negative"] = total(R["_techba"]["op_co2_incentive_negative"], rt)
    sc_ba = pl.concat([_cat(nz(df), k, rt) for k, df in ba.items() if df.height])
    R["systemcost_ba_retailrate"] = sc_ba
    sc_ba = sc_ba.filter(pl.col("sys_costs") != "op_h2combustion_fuel_costs")
    R["systemcost_ba"] = sc_ba
    undisc = val(S.pvf_onm_undisc, "u")
    is_op = isin("sys_costs", set(SYS_COSTS_OP))
    bulk = sc_ba.join(undisc, on="t", how="left").with_columns(pl.when(is_op).then(pl.col("value") * pl.col("u").fill_null(0.0)).otherwise(pl.col("value")).alias("value")).drop("u")
    R["systemcost_ba_bulk"] = nz(bulk)
    R["systemcost_ba_bulk_ew"] = nz(pl.concat([bulk.filter(is_op & (pl.col("t") != C.tlast)), sc_ba.filter(~is_op | (pl.col("t") == C.tlast))]))
    sc = total(sc_ba, ["sys_costs", "t"])
    R["systemcost"] = nz(sc)
    bulk_n = sc.join(undisc, on="t", how="left").with_columns(pl.when(is_op).then(pl.col("value") * pl.col("u").fill_null(0.0)).otherwise(pl.col("value")).alias("value")).drop("u")
    R["systemcost_bulk"] = nz(bulk_n)
    R["systemcost_bulk_ew"] = nz(pl.concat([bulk_n.filter(is_op & (pl.col("t") != C.tlast)), sc.filter(~is_op | (pl.col("t") == C.tlast))]))
    R["tax_expenditure_itc"] = nz(total(sc.filter(isin("sys_costs", {"inv_itc_payments_negative", "inv_itc_payments_negative_refurbishments"})), ["t"]))
    R["tax_expenditure_ptc"] = nz(total(sc.filter(isin("sys_costs", {"op_ptc_payments_negative", "op_co2_incentive_negative"})), ["t"]))
    raw_inv = total(sc.filter(isin("sys_costs", set(SYS_COSTS_INV))), ["t"])
    raw_op = total(sc.filter(isin("sys_costs", set(SYS_COSTS_OP))), ["t"])
    R["raw_inv_cost"] = nz(raw_inv)
    R["raw_op_cost"] = nz(raw_op)
    R["_ba"] = ba
    R["_raw_inv"] = raw_inv
    R["_raw_op"] = raw_op


# ----------------------------------------------------------------------------- error check
def error_check(H: Helpers, R: dict) -> None:
    S, C = H.S, H.C
    t_last = C.tlast
    sel = lambda df: df.filter(pl.col("t") == t_last)  # noqa: E731
    raw_inv = float(sel(R["_raw_inv"])["value"].sum())
    raw_op = float(sel(R["_raw_op"])["value"].sum())
    pvf_cap = float(S.pvf_capital.filter(pl.col("t") == t_last)["value"][0])
    pvf_onm = float(S.pvf_onm.filter(pl.col("t") == t_last)["value"][0])
    z = C.objfn_raw
    adj = H.cost_scale * (pvf_cap * raw_inv + pvf_onm * raw_op)
    if H.swi("Sw_GrowthPenalties") and H.scalar("model_builds_start_yr") <= int(t_last) <= H.swf("Sw_GrowthPenLastYear"):
        gb = sel(H.L("GROWTH_BIN"))
        inv_st = S.valinv_irt.filter(pl.col("t") == t_last).join(S.r_st, on="r", how="inner").select(["i", "st", "t"]).unique()
        gb = semi(gb, inv_st.join(S.stfeas, on="st", how="semi"), ["i", "st", "t"])
        growth_cost = mul(mul(gb, S.cost_growth, ["i", "st", "t"]), S.growth_penalty, ["gbin"])
        gap = float(C.year_gap().filter(pl.col("t") == t_last)["gap"][0])
        adj += pvf_cap * float(growth_cost["value"].sum()) * gap
    if H.swi("Sw_PRM_CapCredit") and H.swi("Sw_StorageBinPenalty"):
        raise NotImplementedError("storage bin penalties are not ported")
    hrs = H.hours.rename({"hours": "value"})
    if H.swi("Sw_RetirePenalty"):
        cap = sel(semi(H.L("CAP"), S.retiretech, V4))
        inv = sel(H.L("INV"))
        refurb = sel(H.L("INV_REFURB")).filter(isin("i", H.set_members("refurbtech"))) if H.swi("Sw_Refurb") else empty(V4)
        up = sel(H.L("UPGRADES")).filter(isin("i", H.set_members("upgrade"))) if H.swi("Sw_Upgrades") else empty(V4)
        net = semi(add([cap, scale(inv, -1.0), scale(refurb, -1.0), scale(up, -1.0)], V4), cap, V4)
        rp = S._inputs.par("retire_penalty", ["t"]).with_columns(pl.col("t").cast(pl.Utf8))
        rp_t = float(rp.filter(pl.col("t") == t_last)["value"][0]) if rp.filter(pl.col("t") == t_last).height else 0.0
        adj -= pvf_onm * float(mul(net, S.cost_fom, V4)["value"].sum()) * rp_t
    hurdle = sel(R["tran_hurdle_cost_ann"])
    adj += pvf_onm * float(hurdle["value"].sum())
    dropped = add([sel(H.rep(H.L("DROPPED"))), sel(H.rep(H.L("EXCESS")))], ["r", "h", "t"])
    adj += pvf_onm * float(mul(dropped, hrs, ["h"])["value"].sum()) * H.scalar("cost_dropped_load")
    if H.swf("Sw_RetailAdder") and H.swi("Sw_Prod"):
        raise NotImplementedError("retail adder accounting is not ported")
    one_newv = H.set_members("one_newv")
    cap_all = sel(semi(H.L("CAP"), S.valcap, V4))
    cap_ivrt = sel(R["_cap_ivrt"])
    dom_a = pl.concat([S.valcap.filter(~isin("i", one_newv)).select(V4), S.retiretech.select(V4)]).unique()
    diff_a = semi(sub(cap_all, mul(cap_ivrt, S.ilr, ["i"]), V4), dom_a, V4)
    adj += pvf_onm * float(mul(diff_a, S.cost_fom, V4)["value"].sum())
    dom_b = anti(S.valcap.filter(isin("i", one_newv)), S.retiretech, V4).filter(pl.col("t") == t_last)
    cond = anti(semi(S.inv_cond, dom_b, V4), S.retiretech.rename({"t": "tt"}), ["i", "v", "r", "tt"])
    inv_tt = val(H.L("INV"), "iv").rename({"t": "tt"})
    fom_tt = val(S.cost_fom, "f").rename({"t": "tt"})
    term_b = (cond.join(inv_tt, on=["i", "v", "r", "tt"], how="inner").join(fom_tt, on=["i", "v", "r", "tt"], how="inner").join(val(S.ilr, "ilr"), on="i", how="inner")
              .with_columns((pl.col("iv") * pl.col("f") * pl.col("ilr")).alias("value")))
    adj += pvf_onm * (float(mul(semi(cap_all, dom_b, V4), S.cost_fom, V4)["value"].sum()) - float(term_b["value"].sum()))
    inve_tt = val(H.L("INV_ENERGY"), "iv").rename({"t": "tt"})
    fome_tt = val(S.cost_fom_energy, "f").rename({"t": "tt"})
    term_c = (cond.join(inve_tt, on=["i", "v", "r", "tt"], how="inner").join(fome_tt, on=["i", "v", "r", "tt"], how="inner").join(val(S.ilr, "ilr"), on="i", how="inner")
              .with_columns((pl.col("iv") * pl.col("f") * pl.col("ilr")).alias("value")))
    cap_e = sel(semi(H.L("CAP_ENERGY"), dom_b, V4))
    adj += pvf_onm * (float(mul(cap_e, S.cost_fom_energy, V4)["value"].sum()) - float(term_c["value"].sum()))
    ac_inv = float(sel(R["_ba"]["inv_transmission_interzone_ac_investment"])["value"].sum())
    adj -= ac_inv - float(sel(R["_capex_transmission_interzone_ac"])["value"].sum())
    dfin = sub(S.cost_cap_fin_mult, S.cost_cap_fin_mult_out, ["i", "r", "t"])
    inv_v = sel(semi(H.L("INV"), S.valinv, V4))
    inv_e = sel(semi(H.L("INV_ENERGY"), S.valinv, V4)).filter(isin("i", H.set_members("battery")))
    up_v = sel(semi(H.L("UPGRADES"), S.valcap, V4)).filter(isin("i", H.set_members("upgrade"))) if H.swi("Sw_Upgrades") else empty(V4)
    refurb_v = sel(semi(H.L("INV_REFURB"), S.valinv, V4)).filter(isin("i", H.set_members("refurbtech"))) if H.swi("Sw_Refurb") else empty(V4)
    fin_terms = [mul(mul(inv_v, S.cost_cap, ["i", "t"]), dfin, ["i", "r", "t"]), mul(mul(inv_e, S.cost_cap_energy, ["i", "t"]), dfin, ["i", "r", "t"]),
                 mul(mul(up_v, S.cost_upgrade, V4), dfin, ["i", "r", "t"]), mul(mul(refurb_v, S.cost_cap, ["i", "t"]), dfin, ["i", "r", "t"])]
    if S.allow_cap_up.height or S.allow_ener_up.height:
        raise NotImplementedError("capacity upsizing in error_check is not ported")
    adj += pvf_cap * sum(float(f["value"].sum()) for f in fin_terms)
    above = sel(H.L("CAP_ABOVE_LIM"))
    adj += float(mul(above, S.cap_penalty, ["tg"])["value"].sum())
    err_z = round((z - adj) / z, 6)
    gen_bad = anti(H.L("GEN"), S.valgen, V4)
    R["error_gen"] = nz(gen_bad.select(["i", "v", "r", "h", "t", "value"]))
    cap_bad = anti(H.L("CAP"), S.valcap, V4)
    recs = H.L("RECS")
    recmap = S.recmap.select(["i", "rpscat", "st", "ast", "t"])
    rps_bad = anti(recs, recmap, ["rpscat", "i", "st", "ast", "t"]).filter(~isin("ast", members(S.stfeas)) | (pl.col("ast") != "voluntary"))
    opres_bad = anti(H.L("OPRES"), S.valgen, V4)
    mrd_cap = S.m_rsc_dat.filter(pl.col("sc_cat") == "cap").select(["r", "i", "rscbin", "value"])
    mrd_init = S.m_rsc_dat_init
    mrd_diff = float(sub(semi(mrd_init, mrd_cap, ["r", "i", "rscbin"]), mrd_cap, ["r", "i", "rscbin"])["value"].sum())
    start = H.swi("Sw_StartMarkets")
    late = lambda df: df.filter(pl.col("t").cast(pl.Int64) >= start)  # noqa: E731
    checks = {"z": err_z, "gen": float(gen_bad["value"].sum()), "cap": float(cap_bad["value"].sum()), "rps": float(rps_bad["value"].sum()),
              "opres": float(opres_bad["value"].sum()), "m_rsc_dat": mrd_diff,
              "dropped": float(late(H.L("DROPPED"))["value"].sum()), "excess": float(late(H.L("EXCESS"))["value"].sum())}
    R["error_check"] = nz(pl.DataFrame({"check": list(checks.keys()), "value": [float(v) for v in checks.values()]}))
    R["dropped_load"] = nz(H.rep(H.L("DROPPED")).select(["r", "h", "t", "value"]))
    R["excess_load"] = nz(H.rep(H.L("EXCESS")).select(["r", "h", "t", "value"]))


# ----------------------------------------------------------------------------- transmission, expenditures, reduced costs
def transmission(H: Helpers, R: dict) -> None:
    S, C = H.S, H.C
    flow = semi(H.L("FLOW"), S.routes, ["r", "rr", "trtype", "t"])
    flow_rep = H.rep(flow)
    hrs = H.hours.rename({"hours": "value"})
    imp = (flow_rep.join(val(S.tranloss, "tl"), on=["r", "rr", "trtype"], how="left")
           .with_columns((pl.col("value") * (1.0 - pl.col("tl").fill_null(0.0))).alias("value")))
    imp_h = total(imp, ["rr", "h", "t"]).rename({"rr": "r"})
    exp_h = total(flow_rep, ["r", "h", "t"])
    R["import_h_rep"] = nz(imp_h)
    R["export_h_rep"] = nz(exp_h)
    R["import_ann_rep"] = nz(total(mul(imp_h, hrs, ["h"]), ["r", "t"]))
    R["export_ann_rep"] = nz(total(mul(exp_h, hrs, ["h"]), ["r", "t"]))
    net_h = sub(imp_h, exp_h, ["r", "h", "t"])
    R["net_import_h_rep"] = nz(net_h)
    flow_s = semi(flow, C.h_stress_t, ["h", "t"])
    imp_s = total(flow_s.join(val(S.tranloss, "tl"), on=["r", "rr", "trtype"], how="left")
                  .with_columns((pl.col("value") * (1.0 - pl.col("tl").fill_null(0.0))).alias("value")), ["rr", "h", "t"]).rename({"rr": "r"})
    net_s = sub(imp_s, total(flow_s, ["r", "h", "t"]), ["r", "h", "t"])
    R["net_import_h_stress"] = nz(net_s)
    R["net_import_ann_rep"] = nz(total(mul(net_h, hrs, ["h"]), ["r", "t"]))
    R["net_import_ann_stress"] = nz(total(mul(net_s, C.hours_t, ["h", "t"]), ["r", "t"]))
    poi = H.L("INV_POI").rename({"t": "tt"}).join(C.tmodel_new, how="cross").filter(pl.col("tt").cast(pl.Int64) <= pl.col("t").cast(pl.Int64))
    R["poi_capacity"] = nz(add([S.poi_cap_init.join(C.tmodel_new, how="cross"), total(poi, ["r", "t"])], ["r", "t"]))

    price = R["reqt_price"]
    p_load = price.filter(pl.col("cat") == "load").select(["r", pl.col("slot").alias("h"), "t", "value"])
    p_rm = price.filter(pl.col("cat") == "res_marg").select(["r", pl.col("slot").alias("h"), "t", "value"])
    p_or = price.filter(pl.col("cat") == "oper_res").select([pl.col("sub").alias("ortype"), "r", pl.col("slot").alias("h"), "t", "value"])
    flow_rr = total(flow_rep, ["r", "rr", "h", "t"])
    e_load = lit(total(mul(mul(flow_rr, hrs, ["h"]), p_load, ["r", "h", "t"]), ["r", "rr", "t"]), cat="load")
    if H.swi("Sw_PRM_CapCredit"):
        raise NotImplementedError("expenditure_flow res_marg for Sw_PRM_CapCredit=1 is not ported")
    flow_prm = semi(total(flow_s, ["r", "rr", "h", "t"]), S.routes_prm, ["r", "rr"])
    e_rm = lit(total(mul(flow_prm, p_rm, ["r", "h", "t"]), ["r", "rr", "t"]), cat="res_marg_ann")
    oflow = H.L("OPRES_FLOW", rep=True)
    oflow = semi(oflow, S.routes.select(["r", "rr", "t"]).unique(), ["r", "rr", "t"])
    e_or = lit(total(mul(mul(oflow, hrs, ["h"]), p_or, ["ortype", "r", "h", "t"]), ["r", "rr", "t"]), cat="oper_res")
    R["expenditure_flow"] = nz(pl.concat([e_load, e_rm, e_or]).select(["cat", "r", "rr", "t", "value"]))
    recs = total(H.L("RECS"), ["rpscat", "st", "ast", "t"])
    m_rec = val(H.M("eq_REC_Requirement"), "m").rename({"st": "ast"})
    rps = (recs.join(m_rec, on=["rpscat", "ast", "t"], how="inner").filter(pl.col("st") != pl.col("ast"))
           .with_columns((pl.col("m") * pl.col("value")).alias("value")))
    R["expenditure_flow_rps"] = nz(mul(total(rps, ["st", "ast", "t"]), H.inv_pvf, ["t"]))
    gen = semi(H.L("GEN", rep=True), S.valgen, V4).filter(isin("i", H.set_members("canada")))
    can_rev = total(mul(mul(gen, hrs, ["h"]), p_load, ["r", "h", "t"]), ["r", "t"])
    can_exp = total(mul(mul(H.rep(S.can_exports_h), hrs, ["h"]), p_load, ["r", "h", "t"]), ["r", "t"])
    R["expenditure_flow_int"] = nz(sub(can_rev, can_exp, ["r", "t"]))

    inv_pvf_cap = S.pvf_capital.with_columns((1.0 / (1000.0 * H.cost_scale * pl.col("value"))).alias("value"))
    rows = []
    for name, slot in [("CAP", "nobin"), ("INV", "nobin")]:
        rc = semi(H.C.RC(name), S.valinv, V4)
        rows.append(lit(mul(rc, inv_pvf_cap, ["t"]), rscbin=slot, var=name).select(V4 + ["rscbin", "var", "value"]))
    rc_rsc = semi(H.C.RC("INV_RSC"), S.valinv, V4).filter(isin("i", H.set_members("rsc_i"))).join(S.m_rscfeas, on=["r", "i", "rscbin"], how="semi")
    rows.append(lit(mul(rc_rsc, inv_pvf_cap, ["t"]), var="INV_RSC").select(V4 + ["rscbin", "var", "value"]))
    R["reduced_cost"] = nz(pl.concat(rows))


# ----------------------------------------------------------------------------- flexible load, production, H2, load types, employment
def production_and_loads(H: Helpers, R: dict) -> None:
    S, C = H.S, H.C
    R["flex_load_out"] = nz(H.rep(H.L("FLEX")).select(["flex_type", "r", "h", "t", "value"]))
    R["peak_load_adj"] = empty(["r", "ccseason", "t"])
    if H.swf("Sw_LoadSiteCF"):
        raise NotImplementedError("flexibly sited load outputs are not ported")
    R["loadsite_cap"] = empty(["r", "t"])
    R["loadsite_op"] = empty(["r", "h", "t"])
    hrs = H.hours.rename({"hours": "value"})
    consume = H.set_members("consume")
    prod_load = R["_prod_load_h"].filter(isin("i", consume)) if H.swi("Sw_Prod") else empty(["i", "r", "h", "t"])
    R["prod_load"] = nz(prod_load)
    prod_load_ann = total(mul(prod_load, hrs, ["h"]), ["i", "r", "t"])
    R["prod_load_ann"] = nz(prod_load_ann)
    cap = semi(H.L("CAP"), S.valcap, V4).filter(isin("i", consume))
    R["prod_cap"] = nz(mul(cap, S.prod_conversion_rate, V4)) if H.swi("Sw_Prod") else empty(V4)
    produce = semi(H.L("PRODUCE", rep=True), S.valcap, V4).join(S.i_p, on=["i", "p"], how="semi")
    pp = semi(total(produce.filter(isin("i", consume)), ["i", "r", "h", "t"]), S.valcap_irt, ["i", "r", "t"]) if H.swi("Sw_Prod") else empty(["i", "r", "h", "t"])
    R["prod_produce"] = nz(pp)
    R["prod_produce_ann"] = nz(total(mul(pp, hrs, ["h"]), ["i", "r", "t"]))
    sw_h2 = H.swi("Sw_H2")
    h2_gen = H.set_members("h2_gen")
    gen = semi(H.L("GEN", rep=True), S.valgen, V4)
    hci = H.scalar("h2_combustion_intensity")
    usage_gen = total(mul(gen.filter(isin("i", h2_gen)), S.heat_rate, V4).with_columns((pl.col("value") * hci).alias("value")), ["r", "h", "t"])
    exog_reg = S.h2_exogenous_demand_regional.filter(pl.col("p") == "h2").select(["r", "h", "t", "value"])
    usage = add([semi(exog_reg, C.tmodel_new, ["t"]), usage_gen], ["r", "h", "t"])
    R["h2_usage"] = nz(usage)
    m_reg = val(H.M("eq_h2_demand_regional"), "m")
    if sw_h2 == 2:
        usage_hrs = mul(usage, hrs, ["h"])
        num = total(usage_hrs.join(m_reg, on=["r", "h", "t"], how="left").join(H.hours, on="h", how="inner")
                    .with_columns((pl.col("m").fill_null(0.0) / pl.col("hours") * pl.col("value")).alias("value")), ["t"])
        price = div(num, total(usage_hrs, ["t"]), ["t"])
    elif sw_h2 == 1:
        price = H.M("eq_h2_demand").filter(pl.col("p") == "h2").select(["t", "value"])
    else:
        price = empty(["t"])
    price = mul(price, H.inv_pvf, ["t"])
    R["prod_h2_price"] = nz(lit(price, p="h2").select(["p", "t", "value"]))
    R["prod_h2comb_cost"] = nz(lit(scale(price, hci), p="h2").select(["p", "t", "value"])) if sw_h2 else empty(["p", "t"])
    R["prod_syscosts"] = nz(R["systemcost_techba"].filter(isin("i", consume))) if H.swi("Sw_Prod") else empty(["sys_costs", "i", "r", "t"])
    smr = H.set_members("smr")
    if smr:
        raise NotImplementedError("SMR emissions are not ported")
    R["prod_SMR_emit"] = empty(["e", "r", "t"])
    exog_nat = S._inputs.par("h2_exogenous_demand", ["p", "t"]).with_columns(pl.col("t").cast(pl.Utf8)) if "h2_exogenous_demand" in S._inputs else empty(["p", "t"])
    cross = lit(total(exog_nat, ["t"]), sector="cross-sector")
    elec = lit(total(mul(mul(gen.filter(isin("i", h2_gen)), hrs, ["h"]), S.heat_rate, V4).with_columns((pl.col("value") * hci).alias("value")), ["t"]), sector="electricity")
    R["h2_demand_by_sector"] = nz(pl.concat([cross, elec]).select(["sector", "t", "value"]))
    ph = (semi(m_reg.rename({"m": "value"}), C.tmodel_new, ["t"]).join(H.hours, on="h", how="inner")
          .with_columns((pl.col("value") / pl.col("hours") / 1000.0).alias("value")).select(["r", "h", "t", "value"]))
    ph = mul(ph, H.inv_pvf, ["t"])
    R["h2_price_h"] = nz(ph)
    szn_num = total(H.h_szn.join(mul(ph, hrs, ["h"]), on="h", how="inner"), ["r", "szn", "t"])
    szn_den = total(H.h_szn.join(H.hours, on="h", how="inner").rename({"hours": "value"}), ["szn"])
    R["h2_price_szn"] = nz(div(szn_num, szn_den, ["szn"]))
    if H.swi("Sw_H2_PTC"):
        credit = H.L("CREDIT_H2PTC", rep=True)
        R["h2_ptc_generation"] = nz(mul(credit, hrs, ["h"]).select(["i", "v", "r", "h", "t", "value"]))
        R["h2_ptc_marginal_region"] = nz(mul(H.M("eq_h2_ptc_region_balance"), H.inv_pvf, ["t"]).select(["h2ptcreg", "t", "value"]))
        R["h2_ptc_marginal_region_hour"] = nz(mul(H.M("eq_h2_ptc_region_hour_balance"), H.inv_pvf, ["t"]).select(["h2ptcreg", "h", "t", "value"]))
    else:
        R["h2_ptc_generation"] = empty(["i", "v", "r", "h", "t"])
        R["h2_ptc_marginal_region"] = empty(["h2ptcreg", "t"])
        R["h2_ptc_marginal_region_hour"] = empty(["h2ptcreg", "h", "t"])

    distloss = H.scalar("distloss")
    load_exog = semi(H.rep(S.load_exog), C.tmodel_new, ["t"])
    le = total(mul(load_exog, hrs, ["h"]), ["r", "t"])
    flow = H.rep(semi(H.L("FLOW"), S.routes, ["r", "rr", "trtype", "t"]))
    tl = total(mul(mul(flow, S.tranloss, ["r", "rr", "trtype"]), hrs, ["h"]), ["r", "t"])
    rows = [lit(scale(le, 1.0 - distloss), loadtype="end_use"), lit(scale(le, distloss), loadtype="dist_loss"), lit(tl, loadtype="trans_loss"),
            lit(total(R["stor_inout"].filter(pl.col("slot") == "in"), ["r", "t"]), loadtype="stor_charge"),
            lit(total(prod_load_ann.filter(isin("i", H.set_members("h2"))), ["r", "t"]), loadtype="h2_prod"),
            lit(total(prod_load_ann.filter(isin("i", H.set_members("dac"))), ["r", "t"]), loadtype="dac")]
    if H.swi("Sw_H2_CompressorLoad"):
        raise NotImplementedError("H2 compressor load is not ported")
    R["load_cat"] = nz(pl.concat([r.select(["loadtype", "r", "t", "value"]) for r in rows]))

    if sw_h2 == 2:
        sin = semi(H.L("H2_STOR_IN", rep=True), S.h2_stor_r, ["h2_stor", "r"])
        sout = semi(H.L("H2_STOR_OUT", rep=True), S.h2_stor_r, ["h2_stor", "r"])
        R["h2_inout"] = nz(pl.concat([lit(sin, slot="in"), lit(sout, slot="out")]).select(["h2_stor", "r", "h", "t", "slot", "value"]))
        R["h2_storage_level"] = nz(semi(semi(H.L("H2_STOR_LEVEL"), S.h_actualszn, ["h", "actualszn"]), S.h2_stor_r, ["h2_stor", "r"]).select(["h2_stor", "r", "actualszn", "h", "t", "value"]))
        R["h2_storage_level_szn"] = nz(semi(H.L("H2_STOR_LEVEL_SZN"), S.h2_stor_r, ["h2_stor", "r"]).select(["h2_stor", "r", "actualszn", "t", "value"]))
    else:
        R["h2_inout"] = empty(["h2_stor", "r", "h", "t", "slot"])
        R["h2_storage_level"] = empty(["h2_stor", "r", "actualszn", "h", "t"])
        R["h2_storage_level_szn"] = empty(["h2_stor", "r", "actualszn", "t"])
    h2flow = semi(H.L("H2_FLOW", rep=True), S.h2_routes, ["r", "rr"])
    ordered = h2flow.filter(pl.col("r") < pl.col("rr"))
    back = h2flow.filter(pl.col("r") > pl.col("rr")).rename({"r": "rr", "rr": "r"})
    R["h2_trans_flow"] = nz(sub(ordered, back, ["r", "rr", "h", "t"]))
    R["h2_trans_flow_all"] = nz(h2flow.select(["r", "rr", "h", "t", "value"]))
    R["h2_storage_cap"] = nz(H.L("H2_STOR_CAP").select(["h2_stor", "r", "t", "value"]))
    h2inv = H.L("H2_TRANSPORT_INV")
    cum = pl.concat([h2inv, h2inv.rename({"r": "rr", "rr": "r"}).select(h2inv.columns)]).filter(pl.col("r") < pl.col("rr")).rename({"t": "tt"})
    cum = cum.join(C.tmodel_new, how="cross").filter(pl.col("tt").cast(pl.Int64) <= pl.col("t").cast(pl.Int64))
    R["h2_trans_cap"] = nz(total(cum, ["r", "rr", "t"]))

    efp = S._inputs.par("employment_factor_plant", ["i", "jtype"])
    eft = S._inputs.par("employment_factor_inter_transmission", ["jtype"])
    cap_v = semi(H.L("CAP"), S.valcap, V4)
    e_fom = lit(total(mul(total(cap_v, ["i", "r", "t"]), efp.filter(pl.col("jtype") == "fom").select(["i", "value"]), ["i"]), ["i", "r", "t"]), jtype="fom")
    e_vom = lit(total(mul(total(mul(gen, hrs, ["h"]), ["i", "r", "t"]), efp.filter(pl.col("jtype") == "vom").select(["i", "value"]), ["i"]), ["i", "r", "t"]), jtype="vom")
    inv_v = semi(H.L("INV"), S.valinv, V4)
    e_con = lit(total(mul(total(inv_v, ["i", "r", "t"]), efp.filter(pl.col("jtype") == "construction").select(["i", "value"]), ["i"]), ["i", "r", "t"]), jtype="construction")
    R["employment_generator"] = nz(pl.concat([e_fom, e_vom, e_con]).select(["i", "jtype", "r", "t", "value"]))
    ef_con = float(eft.filter(pl.col("jtype") == "construction")["value"][0]) if eft.filter(pl.col("jtype") == "construction").height else 0.0
    binw = S._inputs.par("tsc_binwidth", ["r", "rr", "tscbin"]).filter(pl.col("value") != 0.0)
    bins = H.L("TRAN_CAPEX_BINS")
    tprev = C.tprev()
    bins_prev = bins.join(tprev, on="t", how="inner").join(val(bins, "p").rename({"t": "tt"}), on=["r", "rr", "tscbin", "tt"], how="left")
    bins_d = pl.concat([bins.filter(pl.col("t") == C.tfirst), bins_prev.with_columns((pl.col("value") - pl.col("p").fill_null(0.0)).alias("value")).select(["r", "rr", "tscbin", "t", "value"])])
    ac_routes = S.routes_inv.filter(pl.col("trtype") == "ac").select(["r", "rr", "t"])
    rows = semi(semi(bins_d, ac_routes, ["r", "rr", "t"]), binw, ["r", "rr", "tscbin"])
    ac_r = add([total(rows, ["r", "t"]), total(rows, ["rr", "t"]).rename({"rr": "r"})], ["r", "t"])
    invtran = semi(H.L("INVTRAN"), S.routes_inv, ["r", "rr", "trtype", "t"]).filter(~isin("trtype", members(S.aclike)))
    dc = total(mul(invtran, S.transmission_cost_nonac, ["r", "rr", "trtype"]), ["r", "t"])
    con = scale(mul(add([ac_r, dc], ["r", "t"]), S.trans_cost_cap_fin_mult, ["t"]), ef_con / 2.0)
    captran = semi(H.L("CAPTRAN_ENERGY"), S.routes, ["r", "rr", "trtype", "t"])
    fom = scale(total(mul(captran, S.transmission_line_fom, ["r", "rr", "trtype"]), ["r", "t"]), ef_con / 2.0)
    et = pl.concat([lit(con, jtype="construction"), lit(fom, jtype="fom")])
    et_r = scale(total(et, ["jtype", "r", "t"]), 0.5)
    R["employment_transmission"] = nz(et_r)
    R["employment_tot"] = nz(add([total(R["employment_generator"], ["r", "t"]), total(et_r, ["r", "t"])], ["r", "t"]))
