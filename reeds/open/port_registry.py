from __future__ import annotations

GROUPS: dict[str, dict] = {
    "slice": {
        "equations": [
            "eq_loadcon", "eq_supply_demand_balance", "eq_capacity_limit", "eq_capacity_limit_nd",
            "eq_cap_init_noret", "eq_cap_new_noret", "eq_cap_energy_new_noret", "eq_rsc_inv_account", "eq_rsc_INVlim",
            "eq_storage_capacity", "eq_storage_duration", "eq_storage_level", "eq_CAPTRAN_ENERGY", "eq_CAPTRAN_PRM",
            "eq_transmission_limit", "eq_emit_accounting", "eq_annual_cap",
        ],
        "variables": [
            "LOAD", "GEN", "CAP", "CAP_ENERGY", "INV", "INV_ENERGY", "INV_RSC", "STORAGE_IN", "STORAGE_LEVEL",
            "FLOW", "CAPTRAN_ENERGY", "CAPTRAN_PRM", "EMIT", "DROPPED", "EXCESS",
        ],
    },
    "stock": {
        "equations": [
            "eq_cap_init_retmo", "eq_cap_init_retub", "eq_cap_new_retmo", "eq_cap_new_retub",
            "eq_forceprescription_power", "eq_forceprescription_energy", "eq_refurblim", "eq_cap_rsc",
            "eq_cap_upgrade", "eq_cap_up", "eq_ener_up",
        ],
        "variables": [
            "INV_REFURB", "EXTRA_PRESCRIP", "EXTRA_PRESCRIP_ENERGY", "CAP_RSC", "UPGRADES", "UPGRADES_RETIRE",
            "INV_CAP_UP", "INV_ENER_UP",
        ],
    },
    "ops": {
        "equations": [
            "eq_OpRes_requirement", "eq_storage_opres", "eq_storage_thermalres", "eq_storage_in_cap", "eq_storage_in_minloading",
            "eq_minloading", "eq_battery_minduration", "eq_ramping", "eq_dhyd_dispatch", "eq_Canadian_Imports", "eq_mingen_fixed",
            "eq_min_cf", "eq_max_daily_cf", "eq_caa_max_cf", "eq_caa_rate_standard", "eq_bioused", "eq_biousedlimit", "eq_batterymandate",
            "eq_gasaccounting_regional", "eq_gasaccounting_national", "eq_gasbinlimit_regional", "eq_gasbinlimit_national",
        ],
        "variables": ["OPRES", "OPRES_FLOW", "RAMPUP", "BIOUSED", "VGASBINQ_REGIONAL", "VGASBINQ_NATIONAL"],
    },
    "trans": {
        "equations": [
            "eq_INVTRAN_DC", "eq_INVTRAN_AC_forward", "eq_INVTRAN_AC_reverse", "eq_INVTRAN_AC", "eq_TRAN_CAPEX_BINS", "eq_invtran_exog",
            "eq_prescribed_transmission", "eq_POI_cap", "eq_CAPTRAN_GRP", "eq_transgrp_limit_energy", "eq_firm_transfer_limit",
            "eq_transmission_investment_max", "eq_CAPTRAN_max", "eq_CAPTRAN_max_total", "eq_offshore_no_backflow",
            "eq_CAP_CONVERTER", "eq_CONVERSION_limit_energy", "eq_vsc_flow", "eq_converter_max",
        ],
        "variables": ["INVTRAN", "INVTRAN_AC", "TRAN_CAPEX_BINS", "INV_POI", "CAPTRAN_GRP", "CAP_CONVERTER", "INV_CONVERTER", "CONVERSION"],
    },
    "spur": {
        "equations": ["eq_site_cf", "eq_spurclip", "eq_spur_noclip", "eq_capacity_limit_hybrid", "eq_CAP_SPUR"],
        "variables": ["AVAIL_SITE", "CAP_SPUR", "INV_SPUR"],
    },
    "policy": {
        "equations": [
            "eq_RGGI_cap", "eq_state_cap", "eq_CSAPR_Budget", "eq_CSAPR_Assurance", "eq_emit_rate_limit", "eq_bankborrowcap", "eq_cdr_cap",
            "eq_REC_Generation", "eq_REC_Requirement", "eq_REC_BundleLimit", "eq_REC_unbundledLimit", "eq_REC_ooslim", "eq_REC_launder",
            "eq_RPS_OFSWind", "eq_national_gen", "eq_interconnection_queues", "eq_growthlimit_relative", "eq_growthbin_limit",
            "eq_growthlimit_absolute",
        ],
        "variables": ["RECS", "ACP_PURCHASES", "CAP_ABOVE_LIM", "GROWTH_BIN"],
    },
    "h2": {
        "equations": [
            "eq_prod_capacity_limit", "eq_h2_demand", "eq_h2_demand_regional", "eq_h2_transport_caplimit", "eq_h2_storage_level",
            "eq_h2_storage_level_szn", "eq_h2_storage_capacity", "eq_h2_min_storage_cap", "eq_h2_storage_flowlimit", "eq_h2_storage_caplimit",
            "eq_h2_storage_caplimit_szn", "eq_h2_ptc_region_balance", "eq_h2_ptc_region_hour_balance", "eq_h2_ptc_creditgen",
        ],
        "variables": ["PRODUCE", "H2_FLOW", "H2_TRANSPORT_INV", "H2_STOR_IN", "H2_STOR_OUT", "H2_STOR_LEVEL_SZN", "H2_STOR_CAP", "H2_STOR_INV",
                      "CREDIT_H2PTC"],
    },
}


def resolve(group_names: list[str]) -> tuple[list[str], list[str]]:
    equations: list[str] = []
    variables: list[str] = []
    for g in group_names:
        if g not in GROUPS:
            raise KeyError(f"unknown port group {g}; known groups: {sorted(GROUPS)}")
        for e in GROUPS[g]["equations"]:
            if e not in equations:
                equations.append(e)
        for v in GROUPS[g]["variables"]:
            if v not in variables:
                variables.append(v)
    return equations, variables
