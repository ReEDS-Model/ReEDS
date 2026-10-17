"""Data contract: the raw tables the slice consumes.

One table per symbol, stored as ``{name}.parquet`` in a case directory.
Columns are the GAMS domain names; parameters add a ``value`` column.
Years (``t``, ``tt``) are integers; every other index is a string.

GAMS semantics are preserved on load:
* zeros are dropped from parameters (GAMS never stores zeros, and a
  ``$param`` condition means "nonzero");
* a missing parameter entry is treated as 0 wherever it is used.

Symbols prefixed ``slice_`` are coefficients precomposed in GAMS at export
time (see FORMULATION.md, "Export"). Symbols prefixed ``state_`` are levels
of prior-year (tfix) decisions.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

YEAR_DIMS = {"t", "tt"}

# name -> (kind, domain)
SCHEMA: dict[str, tuple[str, tuple[str, ...]]] = {
    # ---- years and time ----
    "tmodel": ("set", ("t",)),
    "tfix": ("set", ("t",)),
    "h": ("set", ("h",)),
    "h_rep": ("set", ("h",)),
    "h_stress": ("set", ("h",)),
    "nexth": ("set", ("h", "hh")),
    # ---- space ----
    "r": ("set", ("r",)),
    "land": ("set", ("r",)),
    # ---- validity sets ----
    "valcap": ("set", ("i", "v", "r", "t")),
    "valgen": ("set", ("i", "v", "r", "t")),
    "valinv": ("set", ("i", "v", "r", "t")),
    "initv": ("set", ("v",)),
    "newv": ("set", ("v",)),
    "inv_cond": ("set", ("i", "v", "r", "t", "tt")),
    "retiretech": ("set", ("i", "v", "r", "t")),
    "valcap_tfix": ("set", ("i", "v", "r", "tt")),
    "valinv_tfix": ("set", ("i", "v", "r", "tt")),
    "tprev": ("set", ("t", "tt")),
    "tfirst": ("set", ("t",)),
    # ---- stock group: retirements, prescriptions, refurbishments, upgrades ----
    "upgrade_from": ("set", ("i", "ii")),
    "noret_upgrade_tech": ("set", ("i",)),
    "refurbtech": ("set", ("i",)),
    "m_refurb_cond": ("set", ("i", "v", "r", "t", "tt")),
    "force_prescribe": ("set", ("i", "v", "r", "t")),
    "exog_rsc": ("set", ("i",)),
    "sccapcosttech": ("set", ("i",)),
    "coal": ("set", ("i",)),
    "ofswind": ("set", ("i",)),
    "r_st": ("set", ("r", "st")),
    "rscbin": ("set", ("rscbin",)),
    "r_offshore": ("par", ("r", "t")),
    "offshore_cap_req": ("par", ("st", "t")),
    "firstyear": ("par", ("i",)),
    "prescribed_build": ("par", ("i", "v", "r", "t")),
    "prescribed_build_energy": ("par", ("i", "v", "r", "t")),
    "avail_retire_exog_rsc": ("par", ("i", "v", "r", "t")),
    "capacity_exog_rsc": ("par", ("i", "v", "r", "rscbin", "t")),
    "upgrade_derate": ("par", ("i", "v", "r", "t")),
    "allow_cap_up": ("par", ("i", "v", "r", "rscbin", "t")),
    "allow_ener_up": ("par", ("i", "v", "r", "rscbin", "t")),
    "cap_cap_up": ("par", ("i", "v", "r", "rscbin", "t")),
    "cap_ener_up": ("par", ("i", "v", "r", "rscbin", "t")),
    "can_exports_h": ("par", ("r", "h", "t")),
    # ---- operations group: reserves, ramping, dispatch limits, biomass, mandates ----
    "ortype": ("set", ("ortype",)),
    "opres_model": ("set", ("ortype",)),
    "opres_h": ("set", ("h",)),
    "opres_routes": ("set", ("r", "rr", "t")),
    "dayhours": ("set", ("h",)),
    "hour_szn_group": ("set", ("h", "hh")),
    "szn": ("set", ("szn",)),
    "h_szn": ("set", ("h", "szn")),
    "thermal_storage": ("set", ("i",)),
    "hydro_d": ("set", ("i",)),
    "hyd_add_pump": ("set", ("i",)),
    "pv": ("set", ("i",)),
    "pvb": ("set", ("i",)),
    "cofire": ("set", ("i",)),
    "bio": ("set", ("i",)),
    "gas": ("set", ("i",)),
    "ccs": ("set", ("i",)),
    "canada": ("set", ("i",)),
    "bioclass": ("set", ("bioclass",)),
    "usda_region": ("set", ("usda_region",)),
    "r_usda": ("set", ("r", "usda_region")),
    "reserve_frac": ("par", ("i", "ortype")),
    "orperc": ("par", ("ortype", "orcat")),
    "storinmaxfrac": ("par", ("i", "v", "r")),
    "minstorfrac": ("par", ("i", "v", "r")),
    "evmc_storage_charge_frac": ("par", ("i", "r", "h", "t")),
    "startcost": ("par", ("i",)),
    "numhours_nexth": ("par", ("h", "hh")),
    "m_cf_szn": ("par", ("i", "v", "r", "szn", "t")),
    "mingen_fixed": ("par", ("i",)),
    "minCF": ("par", ("i", "t")),
    "maxdailycf": ("par", ("i", "t")),
    "avail": ("par", ("i", "r", "h")),
    "seas_cap_frac_delta": ("par", ("i", "v", "r", "szn", "t")),
    "can_imports_szn": ("par", ("r", "szn", "t")),
    "biosupply_cap": ("par", ("usda_region", "bioclass")),
    "biosupply_price": ("par", ("usda_region", "bioclass")),
    "batterymandate": ("par", ("st", "t")),
    "firstyear_v": ("par", ("i", "v")),
    "bcr": ("par", ("i",)),
    "capture_rate": ("par", ("e", "i", "v", "r", "t")),
    "slice_objop_OPRES": ("par", ("ortype", "i", "v", "r", "h", "t")),
    "slice_objop_RAMPUP": ("par", ("i", "r", "h", "hh", "t")),
    "slice_objop_BIOUSED": ("par", ("bioclass", "r", "t")),
    # ---- transmission investment group ----
    "tscbin": ("set", ("tscbin",)),
    "transgrp": ("set", ("transgrp",)),
    "transreg": ("set", ("transreg",)),
    "routes_transgroup": ("set", ("transgrp", "transgrpp", "r", "rr")),
    "routes_transreg": ("set", ("transreg", "transregg", "r", "rr")),
    "trtypemax": ("set", ("trtype",)),
    "aclike": ("set", ("trtype",)),
    "lcclike": ("set", ("trtype",)),
    "offshore": ("set", ("r",)),
    "tsc_binwidth": ("par", ("r", "rr", "tscbin")),
    "tsc_forward": ("par", ("r", "rr", "tscbin")),
    "tsc_reverse": ("par", ("r", "rr", "tscbin")),
    "invtran_exog": ("par", ("r", "rr", "trtype", "t")),
    "trancap_fut_possible": ("par", ("r", "rr", "trtype", "t")),
    "poi_cap_init": ("par", ("r",)),
    "trancap_init_transgroup": ("par", ("transgrp", "transgrpp", "trtype")),
    "firm_import_limit": ("par", ("transreg", "t")),
    "peakload_transreg": ("par", ("transreg", "t")),
    "trans_inv_max": ("par", ("t",)),
    "distance": ("par", ("r", "rr", "trtype")),
    "distance_reinforcement": ("par", ("i", "r", "rscbin")),
    "distance_spur": ("par", ("i", "r", "rscbin")),
    "slice_objinv_INVTRAN": ("par", ("r", "rr", "trtype", "t")),
    "slice_objinv_TRAN_CAPEX_BINS": ("par", ("r", "rr", "tscbin", "t")),
    "slice_objinv_INV_POI": ("par", ("r", "t")),
    "slice_objop_INV_POI": ("par", ("r", "t")),
    "val_converter": ("set", ("r", "t")),
    "routes_inv_tfix": ("set", ("r", "rr", "trtype", "tt")),
    "notvsc": ("set", ("trtype",)),
    "slice_objinv_INV_CONVERTER": ("par", ("r", "t")),
    "slice_objop_CAP_CONVERTER": ("par", ("r", "t")),
    "x": ("set", ("x",)),
    "x_r": ("set", ("x", "r")),
    "xfeas": ("set", ("x",)),
    "spurline_sitemap": ("set", ("i", "r", "rscbin", "x")),
    "spurline_cost": ("par", ("x",)),
    "spur_cf": ("par", ("i", "v", "r", "h", "t")),
    "slice_objinv_INV_SPUR": ("par", ("x", "t")),
    "slice_objop_CAP_SPUR": ("par", ("x", "t")),
    # ---- policy group ----
    "st": ("set", ("st",)),
    "rpscat": ("set", ("rpscat",)),
    "tg": ("set", ("tg",)),
    "stfeas": ("set", ("st",)),
    "r_st_rps": ("set", ("r", "st")),
    "re": ("set", ("i",)),
    "rggi_r": ("set", ("r",)),
    "rectech": ("set", ("rpscat", "i", "st", "t")),
    "recmap": ("set", ("i", "rpscat", "st", "ast", "t")),
    "recstates": ("set", ("rpscat", "st", "t")),
    "st_unbundled_limit": ("set", ("rpscat", "st")),
    "csapr_group_st": ("set", ("csapr_group", "st")),
    "tg_i": ("set", ("tg", "i")),
    "gbin": ("set", ("gbin",)),
    "valinv_tg": ("set", ("st", "tg", "t")),
    "growth_penalty": ("par", ("gbin",)),
    "growth_bin_limit": ("par", ("gbin", "st", "tg", "t")),
    "cost_growth": ("par", ("i", "st", "t")),
    "slice_objinv_GROWTH_BIN": ("par", ("gbin", "i", "st", "t")),
    # ---- gas supply curves (Sw_GasCurve=1) ----
    "cendiv": ("set", ("cendiv",)),
    "fuelbin": ("set", ("fuelbin",)),
    "r_cendiv": ("set", ("r", "cendiv")),
    "gasbinwidth_regional": ("par", ("fuelbin", "cendiv", "t")),
    "gasbinwidth_national": ("par", ("fuelbin", "t")),
    "slice_objop_VGASBINQ_REGIONAL": ("par", ("fuelbin", "cendiv", "t")),
    "slice_objop_VGASBINQ_NATIONAL": ("par", ("fuelbin", "t")),
    "emit_rate_con": ("set", ("e", "r", "t")),
    "recperc": ("par", ("rpscat", "st", "t")),
    "rpstechmult": ("par", ("rpscat", "i", "st")),
    "acp_disallowed": ("par", ("st", "rpscat")),
    "recstyle": ("par", ("st", "rpscat")),
    "rps_oosfrac": ("par", ("st",)),
    "rec_unbundled_limit": ("par", ("rpscat", "st", "t")),
    "rggi_cap": ("par", ("t",)),
    "co2_state_cap": ("par", ("st", "t")),
    "csapr_cap": ("par", ("st", "csapr_cat", "t")),
    "h_weight_csapr": ("par", ("h",)),
    "queue_limit": ("par", ("tg", "r", "t")),
    "emit_rate_limit": ("par", ("e", "r", "t")),
    "slice_objop_ACP_PURCHASES": ("par", ("rpscat", "st", "t")),
    "slice_objinv_CAP_ABOVE_LIM": ("par", ("tg", "r", "t")),
    # ---- hydrogen / production group ----
    "consume": ("set", ("i",)),
    "h2": ("set", ("i",)),
    "h2_gen": ("set", ("i",)),
    "p": ("set", ("p",)),
    "i_p": ("set", ("i", "p")),
    "h2_routes": ("set", ("r", "rr")),
    "h2_routes_inv": ("set", ("r", "rr")),
    "h2_stor": ("set", ("h2_stor",)),
    "h2_stor_r": ("set", ("h2_stor", "r")),
    "actualszn": ("set", ("actualszn",)),
    "nextszn": ("set", ("actualszn", "actualsznn")),
    "h_actualszn": ("set", ("h", "actualszn")),
    "h2ptcreg": ("set", ("h2ptcreg",)),
    "r_h2ptcreg": ("set", ("r", "h2ptcreg")),
    "h2_ptc_years": ("set", ("t",)),
    "valgen_h2ptc": ("set", ("i", "v", "r", "t")),
    "prod_conversion_rate": ("par", ("i", "v", "r", "t")),
    "h2_exogenous_demand_regional": ("par", ("r", "p", "h", "t")),
    "prod_emit_rate": ("par", ("etype", "e", "i", "t")),
    "h2_ptc": ("par", ("i", "v", "r", "t")),
    "cost_h2_transport_cap": ("par", ("r", "rr", "t")),
    "cost_h2_transport_fom": ("par", ("r", "rr", "t")),
    "cost_h2_storage_cap": ("par", ("h2_stor", "t")),
    "cost_h2_storage_fom": ("par", ("h2_stor", "t")),
    "cost_prod": ("par", ("i", "v", "r", "t")),
    "crf": ("par", ("t",)),
    "crf_h2_incentive": ("par", ("t",)),
    "slice_objop_PRODUCE": ("par", ("p", "i", "v", "r", "h", "t")),
    "slice_objinv_H2_STOR_INV": ("par", ("h2_stor", "r", "t")),
    "slice_objop_H2_STOR_CAP": ("par", ("h2_stor", "r", "t")),
    "slice_objinv_H2_TRANSPORT_INV": ("par", ("r", "rr", "t")),
    "slice_objop_H2_TRANSPORT_INV": ("par", ("r", "rr", "t")),
    # ---- technology subsets ----
    "storage": ("set", ("i",)),
    "storage_standalone": ("set", ("i",)),
    "storage_hybrid": ("set", ("i",)),
    "storage_interday": ("set", ("i",)),
    "evmc_storage": ("set", ("i",)),
    "csp": ("set", ("i",)),
    "nondispatch": ("set", ("i",)),
    "spur_techs": ("set", ("i",)),
    "battery": ("set", ("i",)),
    "upgrade": ("set", ("i",)),
    "rsc_i": ("set", ("i",)),
    # ---- subsets used only by ReEDS-style reporting (report.gms) ----
    "upv": ("set", ("i",)),
    "wind": ("set", ("i",)),
    "distpv": ("set", ("i",)),
    "vre": ("set", ("i",)),
    "psh": ("set", ("i",)),
    "ilr": ("par", ("i",)),
    # ---- PTDF network (ptdf.py only); all optional ----
    "ptdf_line": ("set", ("line", "r", "rr")),     # physical AC lines (from r to rr); default: one per AC route pair
    "ptdf_x": ("par", ("line",)),                  # series reactance, any consistent unit; default 1
    "ptdf_limit": ("par", ("line",)),              # MW limit, representative hours; default: route capacity
    "ptdf_limit_prm": ("par", ("line",)),          # MW limit, stress hours; default: ptdf_limit
    "ptdf_ref": ("set", ("r",)),                   # reference (slack) zone, one per AC island
    "ptdf": ("par", ("line", "r")),                # user-supplied PTDF matrix (overrides ptdf_x)
    # ---- integer investment (build_pyoframe_mip only) ----
    "unit_size": ("par", ("i",)),   # MW per unit; techs listed here are built in whole units
    # ---- resource supply curves ----
    "m_rscfeas": ("set", ("r", "i", "rscbin")),
    "m_rsc_con": ("set", ("r", "i")),
    "rsc_agg": ("set", ("i", "ii")),
    # ---- transmission ----
    "routes": ("set", ("r", "rr", "trtype", "t")),
    "routes_prm": ("set", ("r", "rr")),
    "routes_inv": ("set", ("r", "rr", "trtype", "t")),
    # ---- emissions ----
    "etype": ("set", ("etype",)),
    "emit_modeled": ("set", ("e", "r", "t")),
    "emit_capped": ("set", ("e",)),
    # ---- parameters: load and operations ----
    "load_exog_static": ("par", ("r", "h", "t")),
    "tranloss": ("par", ("r", "rr", "trtype")),
    "slice_cap_coef": ("par", ("i", "v", "r", "h", "t")),
    "slice_stor_cap_coef": ("par", ("i", "v", "r", "h", "t")),
    "slice_dur_coef": ("par", ("i", "v", "r")),
    "storage_eff": ("par", ("i", "t")),
    "hours_daily": ("par", ("h",)),
    "hours": ("par", ("h",)),
    # ---- parameters: capacity stock ----
    "m_capacity_exog": ("par", ("i", "v", "r", "t")),
    "degrade_init": ("par", ("i", "v", "r", "t")),
    "m_capacity_exog_energy": ("par", ("i", "v", "r", "t")),
    "degrade_new": ("par", ("i", "tt", "t")),
    "slice_prescr_ret": ("par", ("i", "v", "r", "t")),
    "slice_prescr_ret_energy": ("par", ("i", "v", "r", "t")),
    # ---- parameters: supply curves ----
    "slice_rsc_cap": ("par", ("r", "i", "rscbin", "t")),
    "slice_rsc_cost": ("par", ("r", "i", "rscbin")),
    "resourcescaler": ("par", ("i",)),
    # ---- parameters: transmission ----
    "trancap_init_energy": ("par", ("r", "rr", "trtype")),
    "trancap_init_prm": ("par", ("r", "rr", "trtype")),
    "trans_cap_delta": ("par", ("h", "t")),
    "slice_trans_cost": ("par", ("r", "rr", "trtype")),
    # ---- parameters: emissions ----
    "emit_rate": ("par", ("etype", "e", "i", "v", "r", "t")),
    "gwp": ("par", ("e",)),
    "emit_cap": ("par", ("eall", "t")),  # all years, not only tmodel
    # ---- parameters: objective ----
    "pvf_capital": ("par", ("t",)),
    "pvf_onm": ("par", ("t",)),
    "cost_cap_fin_mult": ("par", ("i", "r", "t")),
    "cost_cap": ("par", ("i", "t")),
    "cost_cap_energy": ("par", ("i", "t")),
    "rsc_fin_mult": ("par", ("i", "r", "t")),
    "cost_vom": ("par", ("i", "v", "r", "t")),
    "cost_fom": ("par", ("i", "v", "r", "t")),
    "cost_fom_energy": ("par", ("i", "v", "r", "t")),
    "heat_rate": ("par", ("i", "v", "r", "t")),
    "fuel_price": ("par", ("i", "r", "t")),
    # ---- parameters: objective coefficients precomposed in GAMS (before pvf and cost_scale) ----
    "slice_objinv_INV": ("par", ("i", "v", "r", "t")),
    "slice_objinv_INV_ENERGY": ("par", ("i", "v", "r", "t")),
    "slice_objinv_INV_RSC": ("par", ("i", "v", "r", "rscbin", "t")),
    "slice_objop_GEN": ("par", ("i", "v", "r", "h", "t")),
    "slice_objop_CAP": ("par", ("i", "v", "r", "t")),
    "slice_objop_INV": ("par", ("i", "v", "r", "t")),
    "slice_objop_CAP_ENERGY": ("par", ("i", "v", "r", "t")),
    "slice_objop_CAPTRAN_ENERGY": ("par", ("r", "rr", "trtype", "t")),
    "slice_objop_FLOW": ("par", ("r", "rr", "h", "t", "trtype")),
    "slice_objop_EMIT": ("par", ("etype", "e", "r", "t")),
    "slice_objop_DROPPED": ("par", ("r", "h", "t")),
    "slice_objop_EXCESS": ("par", ("r", "h", "t")),
    "slice_objinv_UPGRADES": ("par", ("i", "v", "r", "t")),
    "slice_objinv_INV_REFURB": ("par", ("i", "v", "r", "t")),
    "slice_objinv_INV_CAP_UP": ("par", ("i", "v", "r", "rscbin", "t")),
    "slice_objinv_INV_ENER_UP": ("par", ("i", "v", "r", "rscbin", "t")),
    "slice_objop_CAP_RSC": ("par", ("i", "v", "r", "rscbin", "t")),
    "slice_objop_INV_REFURB": ("par", ("i", "v", "r", "t")),
    "slice_objop_UPGRADES": ("par", ("i", "v", "r", "t")),
    # ---- scalars (name, value) ----
    "scalars": ("scalars", ("name",)),
    # ---- state: prior-year decisions (tt in tfix) ----
    "state_INV": ("par", ("i", "v", "r", "tt")),
    "state_INV_ENERGY": ("par", ("i", "v", "r", "tt")),
    "state_INV_RSC": ("par", ("i", "v", "r", "rscbin", "tt")),
    "state_INVTRAN": ("par", ("r", "rr", "trtype", "tt")),
    "state_CAP": ("par", ("i", "v", "r", "tt")),
    "state_UPGRADES": ("par", ("i", "v", "r", "tt")),
    "state_UPGRADES_unrounded": ("par", ("i", "v", "r", "tt")),
    "state_UPGRADES_RETIRE": ("par", ("i", "v", "r", "tt")),
    "state_INV_REFURB": ("par", ("i", "v", "r", "tt")),
    "state_INV_CAP_UP": ("par", ("i", "v", "r", "rscbin", "tt")),
    "state_INV_ENER_UP": ("par", ("i", "v", "r", "rscbin", "tt")),
    "state_INVTRAN_AC": ("par", ("r", "rr", "tscbin", "tt")),
    "state_INV_POI": ("par", ("r", "tt")),
    "state_INV_CONVERTER": ("par", ("r", "tt")),
    "state_INV_SPUR": ("par", ("x", "tt")),
    "state_growth_bin_limit": ("par", ("gbin", "st", "tg", "tt")),
    "state_co2_emit_rate_r": ("par", ("r", "tt")),
    "state_prm": ("par", ("r", "tt")),
    "state_H2_STOR_INV": ("par", ("h2_stor", "r", "tt")),
    "state_H2_TRANSPORT_INV": ("par", ("r", "rr", "tt")),
}

SCALAR_DEFAULTS = {"cost_scale": 1.0, "rhs_tolerance": 1e-6, "Sw_TransInvPRMderate": 0.0,
                   "Sw_Upgrades": 0.0, "Sw_Refurb": 0.0, "Sw_ForcePrescription": 0.0, "Sw_RetirePenalty": 0.0, "Sw_PCM": 0.0,
                   "Sw_UpgradeYear": 0.0, "caa_coal_retire_year": 0.0, "firstyear_RPS": 0.0,
                   "reg_energy_frac": 0.0, "minbatteryduration": 0.0, "caa_gas_max_cf": 0.0, "caa_first_year": 0.0,
                   "caa_capture_rate_standard": 0.0, "bio_cofire_perc": 0.0, "bio_transport_cost": 0.0, "firstyear_battery": 0.0,
                   "Sw_StartMarkets": 0.0, "Sw_OpRes": 0.0, "Sw_StartCost": 0.0, "Sw_MingenFixed": 0.0, "Sw_MinCF": 0.0,
                   "Sw_MaxDailyCF": 0.0, "Sw_Clean_Air_Act": 0.0, "Sw_BatteryMandate": 0.0, "Sw_MinLoading": 0.0,
                   "Sw_HybridPlant": 0.0, "Sw_Canada": 0.0,
                   "Sw_VSC": 0.0, "Sw_TransIntraCost": 0.0, "Sw_TransGroupContraint": 0.0, "Sw_TransGroupDerate": 0.0,
                   "Sw_PRM_NetImportLimit": 0.0, "Sw_TransInvMaxTypes": 0.0, "Sw_TransCapMaxEachType": 0.0, "Sw_TransCapMaxAllTypes": 0.0,
                   "Sw_OffshoreBackflow": 0.0, "Sw_SpurScen": 0.0, "Sw_SpurShare": 0.0, "Sw_SpurCostMult": 1.0, "firstyear_trans_nearterm": 0.0, "trans_fom_frac": 0.0,
                   "Sw_StateRPS": 0.0, "Sw_CSAPR": 0.0, "Sw_RGGI": 0.0, "Sw_StateCap": 0.0, "Sw_BankBorrowCap": 0.0, "Sw_GenMandate": 0.0,
                   "Sw_GrowthPenalties": 0.0, "Sw_GrowthAbsCon": 0.0, "Sw_NoFossilOffsetCDR": 0.0, "Sw_QueueConstraintYears": 0.0,
                   "Sw_Upstream": 0.0, "Sw_AnnualCap": 0.0, "RGGI_start_yr": 0.0, "state_cap_start_yr": 0.0, "csapr_startyr": 0.0,
                   "distloss": 0.0, "interconnection_start": 0.0, "model_builds_start_yr": 0.0, "Sw_GrowthPenLastYear": 0.0,
                   "Sw_H2": 0.0, "Sw_Prod": 0.0, "Sw_H2_PTC": 0.0, "Sw_H2_StorTimestep": 0.0, "Sw_H2_MinStorHours": 0.0,
                   "Sw_H2_CompressorLoad": 0.0, "Sw_H2_Transport": 0.0, "h2_demand_start": 0.0, "h2_storage_duration": 0.0,
                   "h2_combustion_intensity": 0.0, "h2_tranloss": 0.0, "h2_ptc_temporal_match_year": 0.0,
                   "Sw_LoadSiteCF": 0.0, "Sw_Mingen": 0.0, "Sw_PRM_CapCredit": 0.0, "Sw_itlgrpConstraint": 0.0, "Sw_CO2_Detail": 0.0,
                   "Sw_CCSFLEX_BYP": 0.0, "Sw_CCSFLEX_STO": 0.0, "Sw_CCSFLEX_DAC": 0.0, "Sw_GasCurve": 2.0}


def _dtype(col: str):
    if col in YEAR_DIMS:
        return pl.Int64
    if col == "value":
        return pl.Float64
    return pl.Utf8


def empty(name: str) -> pl.DataFrame:
    kind, dims = SCHEMA[name]
    cols = list(dims) + (["value"] if kind in ("par", "scalars") else [])
    return pl.DataFrame(schema={c: _dtype(c) for c in cols})


def normalize(name: str, df: pl.DataFrame) -> pl.DataFrame:
    """Cast to contract dtypes, order columns, apply GAMS zero semantics."""
    kind, dims = SCHEMA[name]
    cols = list(dims) + (["value"] if kind in ("par", "scalars") else [])
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{name}: missing columns {missing}")
    df = df.select([pl.col(c).cast(_dtype(c)) for c in cols])
    if kind == "par":
        df = df.filter(pl.col("value") != 0.0)
    return df.unique(subset=list(dims), keep="last", maintain_order=True)


class Case(dict):
    """Mapping of symbol name -> normalized polars DataFrame (empty if absent)."""

    def __missing__(self, name: str) -> pl.DataFrame:
        if name not in SCHEMA:
            raise KeyError(name)
        df = empty(name)
        self[name] = df
        return df

    def scalar(self, name: str) -> float:
        s = self["scalars"].filter(pl.col("name") == name)
        return float(s["value"][0]) if s.height else SCALAR_DEFAULTS[name]

    def members(self, name: str) -> set:
        df = self[name]
        return set(df[df.columns[0]].to_list())


def from_tables(tables: dict[str, pl.DataFrame]) -> Case:
    case = Case()
    for name, df in tables.items():
        case[name] = normalize(name, df)
    return case


def load_case(path: str | Path) -> Case:
    path = Path(path)
    tables = {}
    for name in SCHEMA:
        f = path / f"{name}.parquet"
        if f.exists():
            tables[name] = pl.read_parquet(f)
    return from_tables(tables)


def save_case(case: Case, path: str | Path) -> None:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    for name, df in case.items():
        df.write_parquet(path / f"{name}.parquet")


def check(case: Case) -> list[str]:
    """Contract checks. Returns a list of problems (empty = OK)."""
    problems = []
    k = ["i", "v", "r", "t"]
    if case["valgen"].join(case["valcap"], on=k, how="anti").height:
        problems.append("valgen is not a subset of valcap (CAP would be uncosted in eq_capacity_limit)")
    if case["tmodel"].height == 0:
        problems.append("tmodel is empty")
    bad_next = case["nexth"].join(case["h"], on="h", how="anti").height
    if bad_next:
        problems.append(f"nexth references {bad_next} timeslices not in h")
    both = case["h_rep"].join(case["h_stress"], on="h", how="inner").height
    if both:
        problems.append("h_rep and h_stress overlap")
    return problems
