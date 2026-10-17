from __future__ import annotations

from dataclasses import dataclass

from .prep import GEN_IDX, V4


@dataclass(frozen=True)
class Term:
    coef: str
    var: str
    rename: dict[str, str] | None = None
    sum_by: list[str] | None = None
    post: dict[str, str] | None = None


@dataclass(frozen=True)
class Row:
    const: str | None
    terms: tuple[Term, ...]
    sense: str


II = {"i": "ii"}
SWAP = {"r": "rr", "rr": "r"}
TT = {"t": "tt"}
VV = {"v": "vv"}
OR4 = ["ortype", "r", "h", "t"]
RHT = ["r", "h", "t"]
RAMP = ["i", "r", "h", "hh", "t"]
DH = ["i", "v", "r", "szn", "t"]
MDC = ["i", "r", "szn", "t"]
TSC = ["r", "rr", "tscbin", "t"]
GRP = ["transgrp", "transgrpp", "t"]
RG = ["rpscat", "i", "st", "t"]
RQ = ["rpscat", "st", "t"]
RECS_V = {"rpscat": "rpscat_v", "st": "st_v"}
EM4 = ["etype", "e", "r", "t"]
HS4 = ["h2_stor", "r", "actualszn", "t"]


def _ge(const, *terms):
    return Row(const, tuple(terms), ">=")


def _eq(const, *terms):
    return Row(const, tuple(terms), "==")


ROWS: dict[str, Row] = {
    "eq_loadcon": _eq("load_neg", Term("load_var", "LOAD"), Term("load_produce", "PRODUCE", sum_by=RHT)),
    "eq_supply_demand_balance": _eq(
        None,
        Term("bal_gen", "GEN", sum_by=RHT),
        Term("bal_import", "FLOW", sum_by=["rr", "h", "t"], post={"rr": "r"}),
        Term("bal_export", "FLOW", sum_by=RHT),
        Term("bal_stor_in", "STORAGE_IN", sum_by=RHT),
        Term("bal_conv", "CONVERSION", sum_by=RHT),
        Term("bal_dropped", "DROPPED"),
        Term("bal_excess", "EXCESS"),
        Term("bal_load", "LOAD")),
    "eq_capacity_limit": _ge(None, Term("caplim", "CAP"), Term("caplim_gen", "GEN")),
    "eq_capacity_limit_nd": _eq(None, Term("caplim_nd", "CAP"), Term("caplim_nd_gen", "GEN")),
    "eq_site_cf": _ge(None, Term("sitecf_rsc", "CAP_RSC", sum_by=["x", "h", "t"]), Term("sitecf_avail", "AVAIL_SITE")),
    "eq_spurclip": _ge(None, Term("spurclip_cap", "CAP_SPUR"), Term("spurclip_avail", "AVAIL_SITE")),
    "eq_spur_noclip": _ge(None, Term("noclip_cap", "CAP_SPUR"), Term("noclip_rsc", "CAP_RSC", sum_by=["x", "t"])),
    "eq_capacity_limit_hybrid": _ge(
        None, Term("hyb_avail", "AVAIL_SITE", sum_by=RHT), Term("hyb_gen", "GEN", sum_by=RHT), Term("hyb_opres", "OPRES", sum_by=RHT)),
    "eq_cap_init_noret": _eq(
        "cap_init",
        Term("noret_init_cap", "CAP"), Term("noret_init_capup", "INV_CAP_UP", sum_by=V4),
        Term("noret_init_up", "UPGRADES", II, V4), Term("noret_init_ret", "UPGRADES_RETIRE", II, V4)),
    "eq_cap_new_noret": _eq(
        "cap_new_const",
        Term("noret_new_cap", "CAP"), Term("cap_new_inv", "INV", TT, V4), Term("noret_new_refurb", "INV_REFURB", TT, V4),
        Term("noret_new_capup", "INV_CAP_UP", sum_by=V4), Term("noret_new_up", "UPGRADES", II, V4),
        Term("noret_new_ret", "UPGRADES_RETIRE", II, V4)),
    "eq_cap_energy_new_noret": _eq(
        "cap_energy_const", Term("cap_energy_inv", "INV_ENERGY", TT, V4), Term("cap_energy_cap", "CAP_ENERGY")),
    "eq_rsc_inv_account": _eq(None, Term("rscacc_rsc", "INV_RSC", sum_by=V4), Term("rscacc_inv", "INV")),
    "eq_rsc_INVlim": _ge("rsc_lim_rhs", Term("rsc_lim_use", "INV_RSC", II, ["r", "i", "rscbin", "t"])),
    "eq_storage_capacity": _ge(None, Term("stor_cap", "CAP"), Term("stor_cap_gen", "GEN"), Term("stor_cap_in", "STORAGE_IN")),
    "eq_storage_duration": _ge(
        None, Term("stor_dur_cap", "CAP"), Term("stor_dur_energy", "CAP_ENERGY"), Term("stor_dur_level", "STORAGE_LEVEL")),
    "eq_storage_level": _eq(
        None,
        Term("stor_lvl_next", "STORAGE_LEVEL", {"h": "hh"}, GEN_IDX), Term("stor_lvl_this", "STORAGE_LEVEL"),
        Term("stor_lvl_in", "STORAGE_IN"), Term("stor_lvl_gen", "GEN")),
    "eq_CAPTRAN_ENERGY": _eq("captran_e_const", Term("captran_e_cap", "CAPTRAN_ENERGY"), Term("captran_e_inv", "INVTRAN")),
    "eq_CAPTRAN_PRM": _eq("captran_p_const", Term("captran_p_cap", "CAPTRAN_PRM"), Term("captran_p_inv", "INVTRAN")),
    "eq_transmission_limit": _ge(
        None, Term("tlim_rep", "CAPTRAN_ENERGY"), Term("tlim_stress", "CAPTRAN_PRM"), Term("tlim_flow", "FLOW")),
    "eq_emit_accounting": _eq(
        None, Term("emit_var", "EMIT"), Term("emit_gen", "GEN", sum_by=EM4), Term("emit_produce", "PRODUCE", sum_by=EM4)),
    "eq_annual_cap": _ge("annual_cap_rhs", Term("annual_cap_gwp", "EMIT", sum_by=["eall", "t"])),
    "eq_cap_init_retmo": _ge(
        "retmo_init_const",
        Term("retmo_init_cap", "CAP"), Term("retmo_init_up", "UPGRADES", II, V4), Term("retmo_init_ret", "UPGRADES_RETIRE", II, V4),
        Term("retmo_init_capup", "INV_CAP_UP", sum_by=V4)),
    "eq_cap_init_retub": _ge(
        "retub_init_const",
        Term("retub_init_cap", "CAP"), Term("retub_init_up", "UPGRADES", II, V4), Term("retub_init_ret", "UPGRADES_RETIRE", II, V4),
        Term("retub_init_capup", "INV_CAP_UP", sum_by=V4)),
    "eq_cap_new_retmo": _ge(
        "retmo_new_const",
        Term("retmo_new_cap", "CAP"), Term("retmo_new_inv", "INV"), Term("retmo_new_refurb", "INV_REFURB"),
        Term("retmo_new_up", "UPGRADES", II, V4), Term("retmo_new_ret", "UPGRADES_RETIRE", II, V4),
        Term("retmo_new_capup", "INV_CAP_UP", sum_by=V4)),
    "eq_cap_new_retub": _ge(
        "retub_new_const",
        Term("retub_new_cap", "CAP"), Term("retub_new_inv", "INV", TT, V4), Term("retub_new_refurb", "INV_REFURB", TT, V4),
        Term("retub_new_up", "UPGRADES", II, V4), Term("retub_new_ret", "UPGRADES_RETIRE", II, V4),
        Term("retub_new_capup", "INV_CAP_UP", sum_by=V4)),
    "eq_forceprescription_power": _eq(
        "fp_build", Term("fp_inv", "INV"), Term("fp_refurb", "INV_REFURB"), Term("fp_extra", "EXTRA_PRESCRIP")),
    "eq_forceprescription_energy": _eq("fpe_build", Term("fpe_inv", "INV_ENERGY"), Term("fpe_extra", "EXTRA_PRESCRIP_ENERGY")),
    "eq_refurblim": _ge(
        "refurblim_const", Term("refurblim_inv", "INV", VV, ["i", "r", "t"]), Term("refurblim_refurb", "INV_REFURB", VV, ["i", "r", "t"])),
    "eq_cap_rsc": _eq("cap_rsc_const", Term("cap_rsc_inv", "INV_RSC"), Term("cap_rsc_cap", "CAP_RSC")),
    "eq_cap_upgrade": _eq(
        "cap_upgrade_const", Term("cap_upgrade_up", "UPGRADES"), Term("cap_upgrade_ret", "UPGRADES_RETIRE"), Term("cap_upgrade_cap", "CAP")),
    "eq_cap_up": _ge("eq_cap_up_const", Term("eq_cap_up_inv", "INV_CAP_UP")),
    "eq_ener_up": _ge("eq_ener_up_const", Term("eq_ener_up_inv", "INV_ENER_UP")),
    "eq_OpRes_requirement": _ge(
        None,
        Term("opres_gen", "OPRES", sum_by=OR4), Term("opres_import", "OPRES_FLOW", sum_by=["ortype", "rr", "h", "t"], post={"rr": "r"}),
        Term("opres_export", "OPRES_FLOW", sum_by=OR4), Term("opres_dropped", "DROPPED"), Term("opres_load", "LOAD"),
        Term("opres_wind", "GEN", sum_by=OR4), Term("opres_pv", "CAP", sum_by=OR4)),
    "eq_storage_opres": _ge(
        None,
        Term("sopres_level", "STORAGE_LEVEL"), Term("sopres_gen", "GEN"),
        Term("sopres_reg", "OPRES", sum_by=GEN_IDX), Term("sopres_all", "OPRES", sum_by=GEN_IDX)),
    "eq_storage_thermalres": _ge(None, Term("sthermal_in", "STORAGE_IN"), Term("sthermal_opres", "OPRES", sum_by=GEN_IDX)),
    "eq_storage_in_cap": _ge(None, Term("sincap_cap", "CAP"), Term("sincap_in", "STORAGE_IN")),
    "eq_battery_minduration": _ge(None, Term("bmd_energy", "CAP_ENERGY"), Term("bmd_cap", "CAP")),
    "eq_ramping": _ge(
        None, Term("ramp_up", "RAMPUP"), Term("ramp_gen_hh", "GEN", {"h": "hh"}, RAMP), Term("ramp_gen_h", "GEN", sum_by=RAMP)),
    "eq_dhyd_dispatch": _ge(None, Term("dhyd_cap", "CAP"), Term("dhyd_gen", "GEN", sum_by=DH), Term("dhyd_opres", "OPRES", sum_by=DH)),
    "eq_Canadian_Imports": _ge("canimp_const", Term("canimp_gen", "GEN", sum_by=["r", "szn", "t"])),
    "eq_mingen_fixed": _ge(None, Term("mgf_gen", "GEN"), Term("mgf_cap", "CAP")),
    "eq_min_cf": _ge(None, Term("mincf_gen", "GEN", sum_by=["i", "r", "t"]), Term("mincf_cap", "CAP", sum_by=["i", "r", "t"])),
    "eq_max_daily_cf": _ge(None, Term("maxcf_cap", "CAP", sum_by=MDC), Term("maxcf_gen", "GEN", sum_by=MDC)),
    "eq_caa_max_cf": _ge(None, Term("caa_cap", "CAP"), Term("caa_gen", "GEN", sum_by=V4)),
    "eq_caa_rate_standard": _ge(None, Term("caars_gen", "GEN", sum_by=["st", "t"])),
    "eq_bioused": _eq(None, Term("bio_used", "BIOUSED", sum_by=["r", "t"]), Term("bio_gen", "GEN", sum_by=["r", "t"])),
    "eq_biousedlimit": _ge("biolim_const", Term("biolim_used", "BIOUSED", sum_by=["bioclass", "usda_region", "t"])),
    "eq_batterymandate": _ge("bmand_const", Term("bmand_cap", "CAP", sum_by=["st", "t"])),
    "eq_INVTRAN_DC": _eq(None, Term("invdc_fwd", "INVTRAN"), Term("invdc_rev", "INVTRAN", SWAP)),
    "eq_INVTRAN_AC_forward": _eq("acfwd_const", Term("acfwd_inv", "INVTRAN_AC"), Term("acfwd_bins", "TRAN_CAPEX_BINS")),
    "eq_INVTRAN_AC_reverse": _eq("acrev_const", Term("acrev_inv", "INVTRAN_AC", SWAP), Term("acrev_bins", "TRAN_CAPEX_BINS")),
    "eq_INVTRAN_AC": _eq(
        None, Term("invac_tran", "INVTRAN", sum_by=["r", "rr", "t"]), Term("invac_bins", "INVTRAN_AC", sum_by=["r", "rr", "t"])),
    "eq_TRAN_CAPEX_BINS": _ge("capexbin_const", Term("capexbin_bins", "TRAN_CAPEX_BINS")),
    "eq_invtran_exog": _ge("invexog_const", Term("invexog_inv", "INVTRAN")),
    "eq_prescribed_transmission": _ge("prestran_const", Term("prestran_inv", "INVTRAN")),
    "eq_POI_cap": _ge(
        "poi_const",
        Term("poi_inv", "INV_POI"), Term("poi_cap", "CAP", sum_by=["r", "t"]), Term("poi_lcc", "INVTRAN", TT, ["r", "t"]),
        Term("poi_conv", "CAP_CONVERTER"), Term("poi_spur", "CAP_SPUR", sum_by=["r", "t"])),
    "eq_vsc_flow": _eq(
        None,
        Term("vsc_import", "FLOW", SWAP, RHT), Term("vsc_export", "FLOW", sum_by=RHT),
        Term("vsc_conv", "CONVERSION", sum_by=RHT), Term("vsc_offgen", "GEN", sum_by=RHT)),
    "eq_CAP_CONVERTER": _eq(
        "capconv_const", Term("capconv_cap", "CAP_CONVERTER"), Term("capconv_inv", "INV_CONVERTER", TT, ["r", "t"])),
    "eq_CAP_SPUR": _eq("capspur_const", Term("capspur_cap", "CAP_SPUR"), Term("capspur_inv", "INV_SPUR", TT, ["x", "t"])),
    "eq_CONVERSION_limit_energy": _ge(None, Term("convlim_cap", "CAP_CONVERTER"), Term("convlim_conv", "CONVERSION", sum_by=RHT)),
    "eq_converter_max": _ge("convmax_const", Term("convmax_cap", "CAP_CONVERTER")),
    "eq_CAPTRAN_GRP": _eq("grp_const", Term("grp_cap", "CAPTRAN_GRP"), Term("grp_inv", "INVTRAN", sum_by=GRP)),
    "eq_transgrp_limit_energy": _ge(
        None, Term("grplim_cap", "CAPTRAN_GRP"), Term("grplim_flow", "FLOW", sum_by=["transgrp", "transgrpp", "h", "t"])),
    "eq_firm_transfer_limit": _ge("firm_const", Term("firm_flow", "FLOW", sum_by=["transreg", "h", "t"])),
    "eq_transmission_investment_max": _ge("tim_const", Term("tim_inv", "INVTRAN", sum_by=["t"]), Term("tim_rsc", "INV_RSC", sum_by=["t"])),
    "eq_CAPTRAN_max": _ge("ctmax_const", Term("ctmax_cap", "CAPTRAN_ENERGY")),
    "eq_CAPTRAN_max_total": _ge("ctmaxt_const", Term("ctmaxt_cap", "CAPTRAN_ENERGY", sum_by=["r", "rr", "t"])),
    "eq_offshore_no_backflow": _eq(None, Term("offbf_flow", "FLOW")),
    "eq_RGGI_cap": _ge("rggi_const", Term("rggi_emit", "EMIT", sum_by=["t"])),
    "eq_state_cap": _ge("stcap_const", Term("stcap_emit", "EMIT", sum_by=["st", "t"]), Term("stcap_flow", "FLOW", sum_by=["st", "t"])),
    "eq_CSAPR_Budget": _ge("csb_const", Term("csb_gen", "GEN", sum_by=["csapr_group", "t"])),
    "eq_CSAPR_Assurance": _ge("csa_const", Term("csa_gen", "GEN", sum_by=["st", "t"])),
    "eq_REC_Generation": _ge(
        None, Term("recgen_gen", "GEN", sum_by=RG), Term("recgen_credit", "CREDIT_H2PTC", sum_by=RG),
        Term("recgen_recs", "RECS", {"rpscat": "rpscat_v"}, RG)),
    "eq_REC_Requirement": _ge(
        "recreq_const",
        Term("recreq_recs", "RECS", RECS_V, RQ), Term("recreq_acp", "ACP_PURCHASES"),
        Term("recreq_load", "LOAD", sum_by=RQ), Term("recreq_gen", "GEN", sum_by=RQ)),
    "eq_REC_BundleLimit": _ge(
        None, Term("recbl_flow", "FLOW", sum_by=["rpscat", "st", "ast", "t"]), Term("recbl_recs", "RECS", sum_by=["rpscat", "st", "ast", "t"])),
    "eq_REC_unbundledLimit": _ge(
        "recunb_const", Term("recunb_recs", "RECS", RECS_V, RQ), Term("recunb_load", "LOAD", sum_by=RQ), Term("recunb_gen", "GEN", sum_by=RQ)),
    "eq_REC_ooslim": _ge(
        "recoos_const", Term("recoos_recs", "RECS", RECS_V, RQ), Term("recoos_load", "LOAD", sum_by=RQ), Term("recoos_gen", "GEN", sum_by=RQ)),
    "eq_REC_launder": _ge(
        None, Term("reclau_gen", "GEN", sum_by=RQ), Term("reclau_credit", "CREDIT_H2PTC", sum_by=RQ), Term("reclau_acp", "ACP_PURCHASES"),
        Term("reclau_recs", "RECS", RECS_V, RQ)),
    "eq_RPS_OFSWind": _ge("ofs_const", Term("ofs_inv", "INV", TT, ["st", "t"]), Term("ofs_refurb", "INV_REFURB", TT, ["st", "t"])),
    "eq_interconnection_queues": _ge(
        "queue_const", Term("queue_above", "CAP_ABOVE_LIM"), Term("queue_inv", "INV", sum_by=["tg", "r", "t"]),
        Term("queue_refurb", "INV_REFURB", sum_by=["tg", "r", "t"])),
    "eq_growthlimit_relative": _ge(
        None, Term("grl_bin", "GROWTH_BIN", sum_by=["i", "st", "t"]), Term("grl_inv", "INV", sum_by=["i", "st", "t"])),
    "eq_growthbin_limit": _ge("gbl_const", Term("gbl_bin", "GROWTH_BIN", sum_by=["gbin", "st", "tg", "t"])),
    "eq_gasaccounting_regional": _eq(
        None, Term("gasacc_reg_bin", "VGASBINQ_REGIONAL", sum_by=["cendiv", "t"]), Term("gasacc_reg_gen", "GEN", sum_by=["cendiv", "t"])),
    "eq_gasaccounting_national": _eq(
        None, Term("gasacc_nat_bin", "VGASBINQ_NATIONAL", sum_by=["t"]), Term("gasacc_nat_gen", "GEN", sum_by=["t"])),
    "eq_gasbinlimit_regional": _ge("gasbin_reg_width", Term("gasbin_reg_var", "VGASBINQ_REGIONAL")),
    "eq_gasbinlimit_national": _ge("gasbin_nat_width", Term("gasbin_nat_var", "VGASBINQ_NATIONAL")),
    "eq_prod_capacity_limit": _ge(None, Term("prodcap_cap", "CAP"), Term("prodcap_produce", "PRODUCE", sum_by=GEN_IDX)),
    "eq_h2_demand_regional": _eq(
        "h2dem_const",
        Term("h2dem_produce", "PRODUCE", sum_by=RHT), Term("h2dem_flow_in", "H2_FLOW", sum_by=["rr", "h", "t"], post={"rr": "r"}),
        Term("h2dem_flow_out", "H2_FLOW", sum_by=RHT), Term("h2dem_stor_out", "H2_STOR_OUT", sum_by=RHT),
        Term("h2dem_stor_in", "H2_STOR_IN", sum_by=RHT), Term("h2dem_gen", "GEN", sum_by=RHT)),
    "eq_h2_transport_caplimit": _ge(
        "h2tc_const",
        Term("h2tc_inv_fwd", "H2_TRANSPORT_INV"), Term("h2tc_inv_rev", "H2_TRANSPORT_INV", SWAP),
        Term("h2tc_flow_fwd", "H2_FLOW"), Term("h2tc_flow_rev", "H2_FLOW", SWAP)),
    "eq_h2_storage_level_szn": _eq(
        None,
        Term("h2lvl_next", "H2_STOR_LEVEL_SZN", {"actualszn": "actualsznn"}, HS4), Term("h2lvl_this", "H2_STOR_LEVEL_SZN"),
        Term("h2lvl_in", "H2_STOR_IN", sum_by=HS4), Term("h2lvl_out", "H2_STOR_OUT", sum_by=HS4)),
    "eq_h2_storage_capacity": _eq("h2cap_const", Term("h2cap_inv", "H2_STOR_INV"), Term("h2cap_cap", "H2_STOR_CAP")),
    "eq_h2_min_storage_cap": _ge(None, Term("h2min_cap", "H2_STOR_CAP", sum_by=["r", "t"]), Term("h2min_gen", "CAP", sum_by=["r", "t"])),
    "eq_h2_storage_flowlimit": _ge(
        None, Term("h2fl_cap", "H2_STOR_CAP"), Term("h2fl_in", "H2_STOR_IN"), Term("h2fl_out", "H2_STOR_OUT")),
    "eq_h2_storage_caplimit_szn": _ge(None, Term("h2cl_cap", "H2_STOR_CAP"), Term("h2cl_lvl", "H2_STOR_LEVEL_SZN")),
    "eq_h2_ptc_region_balance": _eq(
        None, Term("ptcb_credit", "CREDIT_H2PTC", sum_by=["h2ptcreg", "t"]), Term("ptcb_produce", "PRODUCE", sum_by=["h2ptcreg", "t"])),
    "eq_h2_ptc_region_hour_balance": _eq(
        None, Term("ptch_credit", "CREDIT_H2PTC", sum_by=["h2ptcreg", "h", "t"]), Term("ptch_produce", "PRODUCE", sum_by=["h2ptcreg", "h", "t"])),
    "eq_h2_ptc_creditgen": _ge(None, Term("ptcg_gen", "GEN"), Term("ptcg_credit", "CREDIT_H2PTC")),
}

FREE_VARIABLES = ("EMIT",)
