import argparse
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reeds.open import derive  # noqa: E402
from reeds.open.gdxcheck import GdxOracle, compare  # noqa: E402

SET_CHECKS = {
    "tmodel": ["t"], "tfix": ["t"], "h": ["h"], "h_rep": ["h"], "h_stress": ["h"], "nexth": ["h", "hh"],
    "szn": ["szn"], "h_szn": ["h", "szn"], "land": ["r"], "ban": ["i"], "bannew": ["i"], "upgrade": ["i"],
    "upgrade_to": ["i", "ii"], "upgrade_from": ["i", "ii"],
    "battery": ["i"], "storage": ["i"], "storage_standalone": ["i"], "storage_hybrid": ["i"], "storage_interday": ["i"],
    "evmc_storage": ["i"], "csp": ["i"], "nondispatch": ["i"], "rsc_i": ["i"], "upv": ["i"], "wind": ["i"],
    "distpv": ["i"], "vre": ["i"], "psh": ["i"], "hydro_d": ["i"], "hydro": ["i"], "dispatchtech": ["i"],
    "cf_tech": ["i"], "gas": ["i"], "coal": ["i"], "nuclear": ["i"], "geo": ["i"], "onswind": ["i"], "ofswind": ["i"],
    "consume": ["i"], "ccs": ["i"], "bio": ["i"], "cofire": ["i"], "conv": ["i"], "h2_gen": ["i"], "pvb": ["i"],
    "rsc_agg": ["i", "ii"], "i_c": ["i", "c"], "r_st": ["r", "st"], "stfeas": ["st"], "hyd_add_pump": ["i"],
    "sccapcosttech": ["i"], "spur_techs": ["i"], "tfirst": ["t"], "tprev": ["t", "tt"],
    "ivt": ["i", "v", "t"], "one_newv": ["i"], "forced_retire": ["i", "r", "t"], "exog_rsc": ["i"],
    "prescription_check": ["i", "v", "r", "t"], "rscfeas": ["i", "r", "rscbin"],
    "valcap": ["i", "v", "r", "t"], "valinv": ["i", "v", "r", "t"], "valgen": ["i", "v", "r", "t"],
    "valcap_irt": ["i", "r", "t"], "valcap_iv": ["i", "v"], "valcap_ir": ["i", "r"], "valcap_i": ["i"],
    "inv_cond": ["i", "v", "r", "t", "tt"], "retiretech": ["i", "v", "r", "t"], "biofeas": ["r"],
    "routes": ["r", "rr", "trtype", "t"], "routes_inv": ["r", "rr", "trtype", "t"], "routes_prm": ["r", "rr"],
    "m_rscfeas": ["r", "i", "rscbin"], "m_rsc_con": ["r", "i"], "emit_modeled": ["e", "r", "t"], "emit_capped": ["e"],
    "rsc_capacity_scalar_i": ["i"], "fuel2tech": ["f", "i"],
    "valret": ["i", "v"], "noretire": ["i"], "noret_upgrade_tech": ["i"], "refurbtech": ["i"], "m_refurb_cond": ["i", "v", "r", "t", "tt"],
    "valcap_ivr": ["i", "v", "r"], "valgen_irt": ["i", "r", "t"], "valinv_irt": ["i", "r", "t"], "force_prescribe": ["i", "v", "r", "t"],
    "rggi_r": ["r"], "nuclear_ba_ban": ["r"], "upgrade_link": ["i", "ii", "iii"], "ccs_mod": ["i"], "ccs_max": ["i"], "coal_ccs": ["i"],
    "gas_cc_ccs": ["i"], "h2_combustion": ["i"], "smr": ["i"], "canada": ["i"], "beccs": ["i"],
    "ortype": ["ortype"], "opres_model": ["ortype"], "opres_h": ["h"], "opres_routes": ["r", "rr", "t"], "dayhours": ["h"],
    "hour_szn_group": ["h", "hh"], "thermal_storage": ["i"], "bioclass": ["bioclass"], "usda_region": ["usda_region"], "r_usda": ["r", "usda_region"],
    "tscbin": ["tscbin"], "transgrp": ["transgrp"], "transreg": ["transreg"], "trtypemax": ["trtype"],
    "routes_transgroup": ["transgrp", "transgrpp", "r", "rr"], "routes_transreg": ["transreg", "transregg", "r", "rr"],
    "stfeas": ["st"], "r_st_rps": ["r", "st"], "rectech": ["rpscat", "i", "st", "t"], "recmap": ["i", "rpscat", "st", "ast", "t"],
    "recstates": ["rpscat", "st", "t"], "rectrade": ["rpscat", "st", "ast", "t"], "st_unbundled_limit": ["rpscat", "st"],
    "csapr_group_st": ["csapr_group", "st"], "tg_i": ["tg", "i"], "valinv_tg": ["st", "tg", "t"], "gbin": ["gbin"],
    "cendiv": ["cendiv"], "fuelbin": ["fuelbin"], "r_cendiv": ["r", "cendiv"],
    "p": ["p"], "i_p": ["i", "p"], "h2_routes": ["r", "rr"], "h2_routes_inv": ["r", "rr"], "h2_stor": ["h2_stor"], "h2_stor_r": ["h2_stor", "r"],
    "actualszn": ["actualszn"], "nextszn": ["actualszn", "actualsznn"], "h_actualszn": ["h", "actualszn"], "r_h2ptcreg": ["r", "h2ptcreg"],
    "h2_ptc_years": ["t"], "valgen_h2ptc": ["i", "v", "r", "t"],
    "x": ["x"], "x_r": ["x", "r"], "xfeas": ["x"], "spurline_sitemap": ["i", "r", "rscbin", "x"],
}
PAR_CHECKS = {
    "growth_bin_limit": ["gbin", "st", "tg", "t"], "cost_growth": ["i", "st", "t"], "last_year_max_growth": ["st", "tg", "t"],
    "growth_penalty": ["gbin"], "gbin_min": ["tg"], "growth_bin_size_mult": ["gbin"],
    "gassupply_ele": ["cendiv", "t"], "gasusage_national": ["t"], "cd_beta": ["cendiv", "t"], "nat_beta": ["t"],
    "gasbinwidth_regional": ["fuelbin", "cendiv", "t"], "gasbinwidth_national": ["fuelbin", "t"],
    "gasbinp_regional": ["fuelbin", "cendiv", "t"], "gasbinp_national": ["fuelbin", "t"], "gasmultterm": ["cendiv", "t"],
    "cendiv_weights": ["r", "cendiv"],
    "hours": ["h"], "hours_daily": ["h"], "trans_cap_delta": ["h", "t"], "frac_h_quarter_weights": ["h", "quarter"],
    "szn_quarter_weights": ["szn", "quarter"],
    "ivt_num": ["i", "allt"], "countnc": ["i", "v"], "firstyear": ["i"], "firstyear_v": ["i", "v"], "lastyear_v": ["i", "v"],
    "maxage": ["i"], "capacity_exog": ["i", "v", "r", "t"], "capacity_exog_energy": ["i", "v", "r", "t"],
    "capacity_exog_rsc": ["i", "v", "r", "rscbin", "t"], "m_capacity_exog": ["i", "v", "r", "t"],
    "m_capacity_exog_energy": ["i", "v", "r", "t"], "m_required_prescriptions": ["i", "v", "r", "t"],
    "degrade_new": ["i", "t", "tt"], "degrade_init": ["i", "v", "r", "t"], "prescribed_build": ["i", "v", "r", "t"],
    "prescribed_retirements": ["i", "v", "r", "t", "tt"], "r_offshore": ["r", "t"], "exog_onlineyear": ["i", "v", "r", "allt"],
    "plant_char0": ["i", "allt", "plantcat"], "cost_cap": ["i", "t"], "cost_cap_energy": ["i", "t"], "cost_vom": ["i", "v", "r", "t"],
    "cost_fom": ["i", "v", "r", "t"], "cost_fom_energy": ["i", "v", "r", "t"], "heat_rate": ["i", "v", "r", "t"],
    "fuel_price": ["i", "r", "t"], "storage_eff": ["i", "t"], "ilr": ["i"], "bcr": ["i"], "resourcescaler": ["i"],
    "storage_duration_m": ["i", "v", "r"], "winter_cap_frac_delta": ["i", "v", "r"],
    "quarter_cap_frac_delta": ["i", "v", "r", "quarter", "allt"], "cf_adj_t": ["i", "c", "v", "t"],
    "ptc_value_scaled": ["i", "v", "t"], "co2_captured_incentive": ["i", "v", "r", "allt"], "emit_rate_fuel": ["i", "etype", "e"],
    "capture_rate_fuel": ["i", "e"], "emit_rate": ["etype", "eall", "i", "v", "r", "t"], "capture_rate": ["e", "i", "v", "r", "t"],
    "emit_cap": ["eall", "t"], "cost_hurdle": ["r", "rr", "allt"], "transmission_line_fom": ["r", "rr", "trtype"],
    "tranloss": ["r", "rr", "trtype"], "m_rsc_dat": ["r", "i", "rscbin", "sc_cat"], "rsc_capacity_scalar": ["i", "r", "t"],
    "geo_discovery": ["i", "r", "allt"], "plant_age": ["i", "v", "r", "t"], "hydro_capcredit_delta": ["i", "allt"],
    "hyd_add_upg_cap": ["r", "i", "rscbin", "allt"], "trans_cost_cap_fin_mult": ["t"],
    "avail": ["i", "r", "h"], "derate_geo_vintage": ["i", "v"], "seas_cap_frac_delta": ["i", "v", "r", "szn", "t"],
    "cf_in": ["i", "c", "r", "h"], "m_cf": ["i", "c", "v", "r", "h", "t"], "cap_hyd_szn_adj": ["i", "szn", "r"],
    "load_exog_static": ["r", "h", "t"], "gasprice_adj_r": ["r", "h"], "tc_phaseout_mult_t": ["i", "t"],
    "tc_phaseout_mult": ["i", "v", "t"], "cost_cap_fin_mult": ["i", "r", "t"], "rsc_fin_mult": ["i", "r", "t"],
    "ng_crf_penalty_nat": ["i", "t"], "pvf_onm": ["t"], "pvf_capital": ["t"],
    "cost_upgrade": ["i", "v", "r", "t"], "upgrade_derate": ["i", "v", "r", "t"], "eval_period_adj_mult": ["i", "t"],
    "can_exports_h": ["r", "h", "t"], "can_imports_szn": ["r", "szn", "t"], "load_exog": ["r", "h", "t"], "prm": ["r", "t"],
    "m_capacity_exog0": ["i", "v", "r", "t"], "m_required_prescriptions_energy": ["i", "v", "r", "t"],
    "prescribed_build_energy": ["i", "v", "r", "t"], "prescribed_retirements_energy": ["i", "v", "r", "t", "tt"],
    "avail_retire_exog_rsc": ["i", "v", "r", "t"], "capture_rate_input": ["i", "e"], "cap_prescribed": ["i", "r", "t"],
    "geo_bin1_add": ["i", "r"], "storage_duration": ["i"], "state_cap": ["st", "t"], "rggi_cap": ["t"], "tech_banned": ["i", "r"],
    "trancap_init_energy": ["r", "rr", "trtype"], "trancap_init_prm": ["r", "rr", "trtype"], "cf_hyd": ["i", "szn", "r", "t"],
    "hintage_data": ["i", "v", "r", "allt", "hintage_char"], "binned_capacity": ["i", "v", "r", "allt"],
    "reserve_frac": ["i", "ortype"], "orperc": ["ortype", "orcat"], "ramprate": ["i"], "cost_opres": ["i", "ortype", "t"],
    "storinmaxfrac": ["i", "v", "r"], "minstorfrac": ["i", "v", "r"], "startcost": ["i"], "numhours_nexth": ["h", "hh"],
    "m_cf_szn": ["i", "v", "r", "szn", "t"], "mingen_fixed": ["i"], "minCF": ["i", "t"], "maxdailycf": ["i", "t"],
    "tsc_binwidth": ["r", "rr", "tscbin"], "tsc_forward": ["r", "rr", "tscbin"], "tsc_reverse": ["r", "rr", "tscbin"], "distance": ["r", "rr", "trtype"],
    "transmission_cost_nonac": ["r", "rr", "trtype"], "poi_cap_init": ["r"], "trancap_init_transgroup": ["transgrp", "transgrpp", "trtype"],
    "spurline_cost": ["x"],
    "firm_import_limit": ["transreg", "t"], "peakload_transreg": ["transreg", "t"], "trans_inv_max": ["t"], "invtran_exog": ["r", "rr", "trtype", "t"],
    "recperc": ["rpscat", "st", "t"], "rpstechmult": ["rpscat", "i", "st"], "rec_unbundled_limit": ["rpscat", "st", "t"], "rps_oosfrac": ["st"],
    "h_weight_csapr": ["h"], "queue_limit": ["tg", "r", "t"], "cap_penalty": ["tg"], "acp_price": ["st", "t"],
    "prod_conversion_rate": ["i", "v", "r", "t"], "h2_exogenous_demand_regional": ["r", "p", "h", "t"], "prod_emit_rate": ["etype", "e", "i", "t"],
    "h2_ptc": ["i", "v", "r", "t"], "cost_h2_storage_cap": ["h2_stor", "t"], "cost_h2_storage_fom": ["h2_stor", "t"], "cost_prod": ["i", "v", "r", "t"],
    "crf_h2_incentive": ["t"], "h2_network_load": ["h2_st", "t"],
    "slice_cap_coef": ["i", "v", "r", "h", "t"], "slice_stor_cap_coef": ["i", "v", "r", "h", "t"], "slice_dur_coef": ["i", "v", "r"],
    "slice_prescr_ret": ["i", "v", "r", "t"], "slice_prescr_ret_energy": ["i", "v", "r", "t"], "slice_rsc_cap": ["r", "i", "rscbin", "t"],
    "slice_rsc_cost": ["r", "i", "rscbin"], "slice_objinv_INV": ["i", "v", "r", "t"], "slice_objinv_INV_ENERGY": ["i", "v", "r", "t"],
    "slice_objinv_INV_RSC": ["i", "v", "r", "rscbin", "t"], "slice_objop_GEN": ["i", "v", "r", "h", "t"], "slice_objop_CAP": ["i", "v", "r", "t"],
    "slice_objop_CAP_ENERGY": ["i", "v", "r", "t"], "slice_objop_CAPTRAN_ENERGY": ["r", "rr", "trtype", "t"],
    "slice_objop_FLOW": ["r", "rr", "h", "t", "trtype"], "slice_objop_EMIT": ["etype", "e", "r", "t"],
    "slice_objop_DROPPED": ["r", "h", "t"], "slice_objop_EXCESS": ["r", "h", "t"],
}
YEAR_ONLY = {"m_cf_szn", "load_exog", "prm", "m_capacity_exog", "m_capacity_exog_energy", "trans_cap_delta", "seas_cap_frac_delta", "m_cf", "load_exog_static",
             "tc_phaseout_mult", "tc_phaseout_mult_t", "cost_cap_fin_mult", "rsc_fin_mult", "ng_crf_penalty_nat",
             "growth_bin_limit", "cost_growth", "last_year_max_growth", "valinv_tg"}
RENAME_MINE = {"quarter_cap_frac_delta": {"t": "allt"}, "co2_captured_incentive": {"t": "allt"}, "cost_hurdle": {"t": "allt"},
               "geo_discovery": {"t": "allt"}, "hydro_capcredit_delta": {"t": "allt"}, "hyd_add_upg_cap": {"t": "allt"},
               "plant_char0": {"t": "allt"}, "emit_rate": {"e": "eall"}}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("casepath")
    ap.add_argument("year", type=int)
    ap.add_argument("--stress", default=None)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--tol", type=float, default=1e-12)
    ap.add_argument("--oracle", default=None, help="GDX with every GAMS symbol (default <case>/slice/slice_inputs_<year>.gdx)")
    ap.add_argument("--state_gdx", default=None, help="GDX holding prior-year levels (e.g. the port_solution gdx) for symbols that depend on them")
    args = ap.parse_args(argv)
    case = Path(args.casepath).resolve()
    stress = args.stress or f"{args.year}i0"
    state = None
    if args.state_gdx:
        from reeds.open.derive_case import state_tables
        years = [int(y) for y in derive.Inputs(case / "inputs_case" / "inputs.h5").set("tmodel_new", ["t"])["t"].to_list()]
        state = state_tables(args.state_gdx, [y for y in years if y < args.year])
    S = derive.derive(case / "inputs_case" / "inputs.h5", args.year, stress, state=state)
    oracle = GdxOracle(args.oracle or case / "slice" / f"slice_inputs_{args.year}.gdx")
    results = []
    skipped = []
    for name, dims in SET_CHECKS.items():
        if args.only and name not in args.only:
            continue
        if name not in oracle.container:
            skipped.append(name)
            continue
        mine = S[name]
        ref = oracle.table(name, dims, field=None)
        if "t" in dims and name in ("tmodel",):
            mine = mine.filter(pl.col("t") == str(args.year))
        results.append(compare(name, mine, ref))
    for name, dims in PAR_CHECKS.items():
        if args.only and name not in args.only:
            continue
        if name not in oracle.container:
            skipped.append(name)
            continue
        ref = oracle.table(name, dims)
        mine = S[name]
        if name in RENAME_MINE:
            mine = mine.rename(RENAME_MINE[name])
        if name == "exog_onlineyear":
            ref = ref.filter(pl.col("allt").is_in(S["t"]["t"].to_list()))
        if name in YEAR_ONLY:
            ref = ref.filter(pl.col("t") == str(args.year))
            mine = mine.filter(pl.col("t") == str(args.year))
        results.append(compare(name, mine, ref, tol=args.tol))
    n_fail = sum(1 for r in results if not r["pass"])
    if skipped:
        print(f"SKIP {len(skipped)} symbols absent from the oracle: {skipped}")
    print(f"{len(results) - n_fail}/{len(results)} symbols match")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
