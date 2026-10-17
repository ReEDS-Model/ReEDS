from __future__ import annotations

from pathlib import Path

import gams.transfer as gt
import polars as pl

from .contract import SCHEMA, Case, from_tables
from .derive import Symbols, derive


def state_tables(solution_gdx: str | Path, tfix_years: list[int]) -> dict[str, pl.DataFrame]:
    c = gt.Container(load_from=str(solution_gdx))
    out = {}
    specs = {"state_INV": ("INV", ["i", "v", "r", "tt"]), "state_INV_ENERGY": ("INV_ENERGY", ["i", "v", "r", "tt"]),
             "state_INV_RSC": ("INV_RSC", ["i", "v", "r", "rscbin", "tt"]), "state_INVTRAN": ("INVTRAN", ["r", "rr", "trtype", "tt"]),
             "state_CAP": ("CAP", ["i", "v", "r", "tt"]), "state_UPGRADES": ("UPGRADES", ["i", "v", "r", "tt"]),
             "state_UPGRADES_RETIRE": ("UPGRADES_RETIRE", ["i", "v", "r", "tt"]), "state_INV_REFURB": ("INV_REFURB", ["i", "v", "r", "tt"]),
             "state_INV_CAP_UP": ("INV_CAP_UP", ["i", "v", "r", "rscbin", "tt"]), "state_INV_ENER_UP": ("INV_ENER_UP", ["i", "v", "r", "rscbin", "tt"]),
             "state_INVTRAN_AC": ("INVTRAN_AC", ["r", "rr", "tscbin", "tt"]), "state_INV_POI": ("INV_POI", ["r", "tt"]),
             "state_INV_CONVERTER": ("INV_CONVERTER", ["r", "tt"]), "state_INV_SPUR": ("INV_SPUR", ["x", "tt"]),
             "state_growth_bin_limit": ("growth_bin_limit", ["gbin", "st", "tg", "tt"]),
             "state_co2_emit_rate_r": ("co2_emit_rate_r", ["r", "tt"]), "state_prm": ("prm", ["r", "tt"]),
             "state_H2_STOR_INV": ("H2_STOR_INV", ["h2_stor", "r", "tt"]), "state_H2_TRANSPORT_INV": ("H2_TRANSPORT_INV", ["r", "rr", "tt"])}
    for name, (sym, dims) in specs.items():
        if sym not in c:
            raise KeyError(f"{sym} is not in {solution_gdx}; prior-year levels for {name} cannot be read")
        df = c[sym].records
        if df is None:
            out[name] = pl.DataFrame({d: pl.Series([], dtype=pl.Utf8) for d in dims} | {"value": pl.Series([], dtype=pl.Float64)})
            continue
        df = df.copy()
        cols = list(df.columns[: len(dims)])
        field = "level" if "level" in df.columns else "value"
        df = df[cols + [field]].rename(columns=dict(zip(cols + [field], dims + ["value"])))
        for d in dims:
            df[d] = df[d].astype(str).str.lower()
        pdf = pl.from_pandas(df).with_columns(pl.col("value").cast(pl.Float64))
        pdf = pdf.filter(pl.col("tt").cast(pl.Int64).is_in(tfix_years) & (pl.col("value") != 0.0))
        out[name] = pdf
    out["state_UPGRADES_unrounded"] = out["state_UPGRADES"]
    return out


def to_case(S: Symbols, solution_gdx: str | Path | None = None, state: dict[str, pl.DataFrame] | None = None) -> Case:
    year = str(S.year)
    this_year = lambda df: df.filter(pl.col("t") == year)  # noqa: E731
    tables: dict[str, pl.DataFrame] = {}
    tables["tmodel"] = S.tmodel
    tables["tfix"] = S.tfix
    tables["h"] = S.h
    tables["h_rep"] = S.h_rep
    tables["h_stress"] = S.h_stress
    tables["nexth"] = S.nexth
    tables["r"] = S.r
    tables["land"] = S.land
    tables["valcap"] = this_year(S.valcap)
    tables["valgen"] = this_year(S.valgen)
    tables["valinv"] = this_year(S.valinv)
    tables["initv"] = S.initv
    tables["newv"] = S.newv
    tables["inv_cond"] = this_year(S.inv_cond)
    tables["retiretech"] = S.retiretech
    tfix_t = S.tfix.rename({"t": "tt"})
    tables["valcap_tfix"] = S.valcap.rename({"t": "tt"}).join(tfix_t, on="tt", how="semi")
    tables["valinv_tfix"] = S.valinv.rename({"t": "tt"}).join(tfix_t, on="tt", how="semi")
    tables["routes_inv_tfix"] = S.routes_inv.rename({"t": "tt"}).join(tfix_t, on="tt", how="semi")
    tables["tprev"] = S.tprev
    tables["tfirst"] = S.tfirst
    tables["upgrade_from"] = S.upgrade_from
    tables["noret_upgrade_tech"] = S.noret_upgrade_tech
    tables["refurbtech"] = S.refurbtech
    tables["m_refurb_cond"] = this_year(S.m_refurb_cond)
    tables["force_prescribe"] = this_year(S.force_prescribe)
    for name in ["exog_rsc", "sccapcosttech", "coal", "ofswind", "r_st", "rscbin", "firstyear", "capacity_exog_rsc", "upgrade_derate",
                 "allow_ener_up", "cap_cap_up", "cap_ener_up"]:
        tables[name] = S[name]
    tables["allow_cap_up"] = S.allow_cap_up.with_columns(pl.lit(1.0).alias("value")) if "value" not in S.allow_cap_up.columns else S.allow_cap_up
    tables["r_offshore"] = this_year(S.r_offshore)
    tables["offshore_cap_req"] = S.offshore_cap_req.rename({"allt": "t"})
    tables["prescribed_build"] = this_year(S.prescribed_build)
    tables["prescribed_build_energy"] = this_year(S.prescribed_build_energy)
    tables["avail_retire_exog_rsc"] = S.avail_retire_exog_rsc.filter(pl.col("t").cast(pl.Int64) <= S.year)
    tables["can_exports_h"] = this_year(S.can_exports_h)
    for name in ["ortype", "opres_model", "opres_h", "dayhours", "hour_szn_group", "szn", "h_szn", "thermal_storage", "hydro_d",
                 "hyd_add_pump", "pv", "pvb", "cofire", "bio", "gas", "ccs", "canada", "bioclass", "usda_region", "r_usda",
                 "reserve_frac", "orperc", "storinmaxfrac", "minstorfrac", "startcost", "numhours_nexth", "m_cf_szn", "mingen_fixed",
                 "avail", "biosupply_cap", "biosupply_price", "firstyear_v", "bcr", "slice_objop_OPRES", "slice_objop_RAMPUP", "slice_objop_BIOUSED"]:
        tables[name] = S[name]
    for name in ["opres_routes", "evmc_storage_charge_frac", "minCF", "maxdailycf", "seas_cap_frac_delta", "can_imports_szn", "capture_rate"]:
        tables[name] = this_year(S[name])
    for name in ["tscbin", "transgrp", "transreg", "routes_transgroup", "routes_transreg", "trtypemax", "aclike", "lcclike", "offshore",
                 "tsc_binwidth", "tsc_forward", "tsc_reverse", "poi_cap_init", "trancap_init_transgroup", "distance",
                 "distance_reinforcement", "distance_spur", "slice_objinv_INVTRAN", "slice_objinv_TRAN_CAPEX_BINS",
                 "slice_objinv_INV_POI", "slice_objop_INV_POI", "val_converter", "slice_objinv_INV_CONVERTER", "slice_objop_CAP_CONVERTER", "notvsc",
                 "x", "x_r", "xfeas", "spurline_sitemap", "spurline_cost", "spur_cf", "slice_objinv_INV_SPUR", "slice_objop_CAP_SPUR"]:
        tables[name] = S[name]
    for name in ["invtran_exog", "trancap_fut_possible", "firm_import_limit", "peakload_transreg", "trans_inv_max"]:
        tables[name] = this_year(S[name])
    for name in ["st", "rpscat", "tg", "stfeas", "r_st_rps", "re", "rggi_r", "st_unbundled_limit", "csapr_group_st", "tg_i",
                 "rpstechmult", "acp_disallowed", "recstyle", "rps_oosfrac", "rggi_cap", "h_weight_csapr",
                 "slice_objop_ACP_PURCHASES", "slice_objinv_CAP_ABOVE_LIM"]:
        tables[name] = S[name]
    for name in ["rectech", "recmap", "recstates", "emit_rate_con", "recperc", "rec_unbundled_limit", "csapr_cap", "queue_limit", "emit_rate_limit"]:
        tables[name] = this_year(S[name])
    for name in ["gbin", "growth_penalty", "slice_objinv_GROWTH_BIN", "cendiv", "fuelbin", "r_cendiv",
                 "slice_objop_VGASBINQ_REGIONAL", "slice_objop_VGASBINQ_NATIONAL"]:
        tables[name] = S[name]
    for name in ["valinv_tg", "growth_bin_limit", "cost_growth", "gasbinwidth_regional", "gasbinwidth_national"]:
        tables[name] = this_year(S[name])
    tables["co2_state_cap"] = S.state_cap
    for name in ["consume", "h2", "h2_gen", "p", "i_p", "h2_routes", "h2_routes_inv", "h2_stor", "h2_stor_r", "actualszn", "nextszn", "h_actualszn",
                 "h2ptcreg", "r_h2ptcreg", "h2_ptc_years", "crf", "crf_h2_incentive", "slice_objop_PRODUCE", "slice_objinv_H2_STOR_INV",
                 "slice_objop_H2_STOR_CAP", "slice_objinv_H2_TRANSPORT_INV", "slice_objop_H2_TRANSPORT_INV", "cost_h2_storage_cap",
                 "cost_h2_storage_fom", "prod_emit_rate"]:
        tables[name] = S[name]
    for name in ["valgen_h2ptc", "prod_conversion_rate", "h2_exogenous_demand_regional", "h2_ptc", "cost_h2_transport_cap", "cost_h2_transport_fom", "cost_prod"]:
        tables[name] = this_year(S[name])
    bm = S.batterymandate
    tables["batterymandate"] = bm.rename({"allt": "t"}) if "allt" in bm.columns else bm
    for name in ["storage", "storage_standalone", "storage_hybrid", "storage_interday", "evmc_storage", "csp", "nondispatch",
                 "spur_techs", "battery", "upgrade", "rsc_i", "upv", "wind", "distpv", "vre", "psh"]:
        tables[name] = S[name]
    tables["ilr"] = S.ilr
    tables["m_rscfeas"] = S.m_rscfeas
    tables["m_rsc_con"] = S.m_rsc_con
    tables["rsc_agg"] = S.rsc_agg
    tables["routes"] = this_year(S.routes)
    tables["routes_prm"] = S.routes_prm
    tables["routes_inv"] = this_year(S.routes_inv)
    tables["etype"] = S.etype
    tables["emit_modeled"] = this_year(S.emit_modeled)
    tables["emit_capped"] = S.emit_capped
    tables["load_exog_static"] = this_year(S.load_exog_static)
    tables["tranloss"] = S.tranloss
    tables["slice_cap_coef"] = S.slice_cap_coef
    tables["slice_stor_cap_coef"] = S.slice_stor_cap_coef
    tables["slice_dur_coef"] = S.slice_dur_coef
    tables["storage_eff"] = this_year(S.storage_eff)
    tables["hours_daily"] = S.hours_daily
    tables["hours"] = S.hours
    tables["m_capacity_exog"] = this_year(S.m_capacity_exog)
    tables["degrade_init"] = this_year(S.degrade_init)
    tables["m_capacity_exog_energy"] = this_year(S.m_capacity_exog_energy)
    tables["degrade_new"] = S.degrade_new.rename({"t": "tt", "tt": "t"}).select(["i", "tt", "t", "value"])
    tables["slice_prescr_ret"] = S.slice_prescr_ret
    tables["slice_prescr_ret_energy"] = S.slice_prescr_ret_energy
    tables["slice_rsc_cap"] = S.slice_rsc_cap
    tables["slice_rsc_cost"] = S.slice_rsc_cost
    tables["resourcescaler"] = S.resourcescaler
    tables["trancap_init_energy"] = S.trancap_init_energy
    tables["trancap_init_prm"] = S.trancap_init_prm
    tables["trans_cap_delta"] = S.trans_cap_delta
    tables["emit_rate"] = this_year(S.emit_rate)
    tables["gwp"] = S.gwp
    tables["emit_cap"] = S.emit_cap
    tables["pvf_capital"] = S.pvf_capital
    tables["pvf_onm"] = S.pvf_onm
    tables["cost_cap_fin_mult"] = this_year(S.cost_cap_fin_mult)
    tables["cost_cap"] = this_year(S.cost_cap)
    tables["cost_cap_energy"] = this_year(S.cost_cap_energy)
    tables["rsc_fin_mult"] = this_year(S.rsc_fin_mult)
    tables["cost_vom"] = this_year(S.cost_vom)
    tables["cost_fom"] = this_year(S.cost_fom)
    tables["cost_fom_energy"] = this_year(S.cost_fom_energy)
    tables["heat_rate"] = this_year(S.heat_rate)
    tables["fuel_price"] = this_year(S.fuel_price)
    for name in ["slice_objinv_INV", "slice_objinv_INV_ENERGY", "slice_objinv_INV_RSC", "slice_objop_GEN", "slice_objop_CAP",
                 "slice_objop_INV", "slice_objop_CAP_ENERGY", "slice_objop_CAPTRAN_ENERGY", "slice_objop_FLOW", "slice_objop_EMIT",
                 "slice_objop_DROPPED", "slice_objop_EXCESS",
                 "slice_objinv_UPGRADES", "slice_objinv_INV_REFURB", "slice_objinv_INV_CAP_UP", "slice_objinv_INV_ENER_UP",
                 "slice_objop_CAP_RSC", "slice_objop_INV_REFURB", "slice_objop_UPGRADES"]:
        tables[name] = S[name]
    tables["scalars"] = S.slice_scalars
    if solution_gdx is not None and state is not None:
        raise ValueError("pass either solution_gdx or state, not both")
    if solution_gdx is not None:
        tfix_years = [int(y) for y in S.tfix["t"].to_list()]
        state = state_tables(solution_gdx, tfix_years)
    if state is not None:
        tables.update(state)
    for name, df in tables.items():
        kind, dims = SCHEMA[name]
        cols = list(dims) + (["value"] if kind in ("par", "scalars") else [])
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise ValueError(f"{name}: derived table lacks columns {missing}; has {df.columns}")
        tables[name] = df.select(cols)
    return from_tables(tables)


def derive_case(h5path: str | Path, year: int, stress_year: str, solution_gdx: str | Path | None = None,
                state: dict[str, pl.DataFrame] | None = None) -> Case:
    if solution_gdx is not None:
        from .derive import Inputs, members
        years = sorted(int(x) for x in members(Inputs(h5path).set("tmodel_new", ["t"])))
        state = state_tables(solution_gdx, [y for y in years if y < year])
        solution_gdx = None
    S = derive(h5path, year, stress_year, state=state)
    return to_case(S, state=state)
