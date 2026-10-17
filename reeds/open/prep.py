"""Shared data layer for the slice (polars).

Turns the raw contract tables into, for every variable and constraint,
(a) its index domain and (b) the coefficient tables of each term. Both
builders consume exactly these tables, so any difference between the
pyoframe and Pyomo models is a difference in how the algebra is written,
not in the data.

Conventions
-----------
* Index column order follows GAMS: GEN(i,v,r,h,t), FLOW(r,rr,h,t,trtype).
* Coefficient tables carry the full index of the *term* (constraint index
  plus any summed index) and a ``value`` column.
* Constants used as right-hand sides are materialized on the constraint
  domain with zeros filled, because a GAMS row exists whether or not its
  constant is nonzero.
* Every constraint is later written as (GAMS LHS) - (GAMS RHS) <sense> 0,
  so the solver dual d(obj)/d(rhs) carries the GAMS marginal sign.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl

from .contract import Case

V4 = ["i", "v", "r", "t"]
GEN_IDX = ["i", "v", "r", "h", "t"]
FLOW_IDX = ["r", "rr", "h", "t", "trtype"]
ROUTE_IDX = ["r", "rr", "trtype", "t"]
RSC_IDX = ["i", "v", "r", "rscbin", "t"]


def _in(df: pl.DataFrame, col: str, members) -> pl.DataFrame:
    return df.filter(pl.col(col).is_in(list(members)))


def _not_in(df: pl.DataFrame, col: str, members) -> pl.DataFrame:
    return df.filter(~pl.col(col).is_in(list(members)))


def _on_domain(domain: pl.DataFrame, par: pl.DataFrame, keys: list[str]) -> pl.DataFrame:
    """Left-join a parameter onto a domain and fill missing values with 0."""
    out = domain.join(par.select(keys + ["value"]), on=keys, how="left")
    return out.with_columns(pl.col("value").fill_null(0.0))


def _add(left: pl.DataFrame, right: pl.DataFrame, on: list[str], sign: float = 1.0) -> pl.DataFrame:
    out = left.join(right.select(on + ["value"]).rename({"value": "_v2"}), on=on, how="left")
    return out.with_columns((pl.col("value") + sign * pl.col("_v2").fill_null(0.0)).alias("value")).drop("_v2")


def _fsum_all(values: pl.Series) -> float:
    import math
    return math.fsum(values.to_list())


def _fsum(df: pl.DataFrame, keys: list[str]) -> pl.DataFrame:
    from .derive import fsum_by
    return fsum_by(df.select(keys + ["value"]), keys)


def _signed(df: pl.DataFrame, keys: list[str], sign: float) -> pl.DataFrame:
    return df.select(keys).with_columns(pl.lit(float(sign)).alias("value"))


def _mul(left: pl.DataFrame, right: pl.DataFrame, on: list[str]) -> pl.DataFrame:
    """Inner-join two coefficient tables and multiply their values (GAMS: missing = 0)."""
    out = left.join(right.rename({"value": "_v2"}), on=on, how="inner")
    return out.with_columns((pl.col("value") * pl.col("_v2")).alias("value")).drop("_v2")


@dataclass
class Prepared:
    var: dict[str, pl.DataFrame] = field(default_factory=dict)   # variable -> domain
    con: dict[str, pl.DataFrame] = field(default_factory=dict)   # constraint -> domain
    coef: dict[str, pl.DataFrame] = field(default_factory=dict)  # term name -> coefficients
    obj: dict[str, pl.DataFrame] = field(default_factory=dict)   # variable -> objective coefficients
    options: dict = field(default_factory=dict)

    def summary(self) -> dict:
        return {
            "variables": {k: v.height for k, v in self.var.items()},
            "constraints": {k: v.height for k, v in self.con.items()},
        }


def prepare(case: Case, transmission_investment: bool = True) -> Prepared:
    P = Prepared(options={"transmission_investment": transmission_investment})
    tmodel = case["tmodel"]
    tfix = case["tfix"]
    h = case["h"]
    h_rep = case.members("h_rep")
    h_stress = case.members("h_stress")

    S = {name: case.members(name) for name in (
        "storage", "storage_standalone", "storage_hybrid", "storage_interday", "evmc_storage",
        "csp", "nondispatch", "spur_techs", "battery", "upgrade", "rsc_i", "land",
        "initv", "newv", "emit_capped", "etype",
        "bio", "cofire", "wind", "pv", "pvb", "hydro_d", "hyd_add_pump", "thermal_storage", "gas", "ccs", "coal", "canada",
        "distpv", "re", "refurbtech", "ofswind", "stfeas", "rggi_r", "consume", "h2", "h2_gen", "h2_stor")}

    valcap = case["valcap"].join(tmodel, on="t", how="semi")
    valgen = case["valgen"].join(tmodel, on="t", how="semi")
    valinv = case["valinv"].join(tmodel, on="t", how="semi")
    routes = case["routes"].join(tmodel, on="t", how="semi")
    routes_prm = case["routes_prm"]
    routes_inv = case["routes_inv"].join(tmodel, on="t", how="semi")
    retiretech = case["retiretech"]

    # ------------------------------------------------------------------ variables
    rht = case["r"].join(h, how="cross").join(tmodel, how="cross")
    P.var["LOAD"] = rht.select(["r", "h", "t"])
    P.var["GEN"] = valgen.join(h, how="cross").select(GEN_IDX)
    P.var["CAP"] = valcap.select(V4)
    P.var["CAP_ENERGY"] = _in(valcap, "i", S["battery"]).select(V4)
    P.var["INV"] = valinv.select(V4)
    P.var["INV_ENERGY"] = _in(valinv, "i", S["battery"]).select(V4)

    stor_in_techs = S["storage_standalone"]  # hyd_add_pump is off in the slice
    P.var["STORAGE_IN"] = _in(P.var["GEN"], "i", stor_in_techs)
    lvl_techs = S["storage"] - S["storage_interday"]
    P.var["STORAGE_LEVEL"] = _in(P.var["GEN"], "i", lvl_techs)

    P.var["FLOW"] = routes.join(h, how="cross").select(FLOW_IDX)
    P.var["CAPTRAN_ENERGY"] = routes.select(ROUTE_IDX)
    P.var["CAPTRAN_PRM"] = routes.join(routes_prm, on=["r", "rr"], how="semi").select(ROUTE_IDX)
    if transmission_investment and routes_inv.height:
        P.var["INVTRAN"] = routes_inv.select(ROUTE_IDX)

    emit_modeled = case["emit_modeled"].join(tmodel, on="t", how="semi")
    P.var["EMIT"] = case["etype"].join(emit_modeled, how="cross").select(["etype", "e", "r", "t"])

    # INV_RSC: valinv rsc techs x feasible bins, minus bins fixed at zero below
    rsc_valinv = _in(valinv, "i", S["rsc_i"])
    inv_rsc = rsc_valinv.join(case["m_rscfeas"], on=["r", "i"], how="inner").select(RSC_IDX)

    # ------------------------------------------- eq_rsc_INVlim RHS and zero flags
    rsc_agg = case["rsc_agg"]  # (i, ii): i is the numeraire tech, ii the investing tech
    lim_dom = (
        _in(case["m_rscfeas"], "i", S["rsc_i"])
        .join(case["m_rsc_con"], on=["r", "i"], how="semi")
        .join(tmodel, how="cross")
        .select(["r", "i", "rscbin", "t"])
    )
    gross = _on_domain(lim_dom, case["slice_rsc_cap"], ["r", "i", "rscbin", "t"])
    past = (
        case["state_INV_RSC"]
        .join(tfix.rename({"t": "tt"}), on="tt", how="semi")
        .rename({"i": "ii"})
        .join(rsc_agg, on="ii", how="inner")
        .join(case["resourcescaler"].rename({"i": "ii", "value": "scaler"}), on="ii", how="left")
        .with_columns((pl.col("value") * pl.col("scaler").fill_null(0.0)).alias("value"))
        .join(tmodel, how="cross")
        .filter(pl.col("tt") <= pl.col("t"))
        .group_by(["r", "i", "rscbin", "t"])
        .agg(pl.col("value").sum())
    )
    rhs = (
        gross.join(past.rename({"value": "past"}), on=["r", "i", "rscbin", "t"], how="left")
        .with_columns((pl.col("value") - pl.col("past").fill_null(0.0)).alias("value"))
        .drop("past")
    )
    tol = case.scalar("rhs_tolerance")
    flagged = rhs.filter(pl.col("value").abs() < tol)
    # GAMS fixes INV_RSC(ii,v,r,rscbin,t)=0 for flagged bins; holdfixed=1 removes them.
    fixed = (
        flagged.join(rsc_agg, on="i", how="inner")
        .select(pl.col("ii").alias("i"), "r", "rscbin", "t")
        .unique()
    )
    P.var["INV_RSC"] = inv_rsc.join(fixed, on=["i", "r", "rscbin", "t"], how="anti")
    lim_rows = rhs.join(flagged, on=["r", "i", "rscbin", "t"], how="anti").select(["r", "i", "rscbin", "t"])
    # term: resourcescaler(ii) * INV_RSC(ii,v,r,rscbin,t) contributes to row (r,i,rscbin,t)
    P.coef["rsc_lim_use"] = (
        P.var["INV_RSC"].rename({"i": "ii"})
        .join(rsc_agg, on="ii", how="inner")
        .join(lim_rows, on=["r", "i", "rscbin", "t"], how="semi")
        .join(case["resourcescaler"].rename({"i": "ii"}), on="ii", how="inner")
        .with_columns((-pl.col("value")).alias("value"))
        .select(["r", "i", "rscbin", "t", "ii", "v", "value"])
    )
    lim_rows = lim_rows.join(P.coef["rsc_lim_use"], on=["r", "i", "rscbin", "t"], how="semi")
    P.con["eq_rsc_INVlim"] = lim_rows
    P.coef["rsc_lim_rhs"] = rhs.join(lim_rows, on=["r", "i", "rscbin", "t"], how="semi")

    # ------------------------------------------------------------- eq_loadcon
    P.con["eq_loadcon"] = P.var["LOAD"]
    P.coef["load"] = _add(_on_domain(P.var["LOAD"], case["load_exog_static"], ["r", "h", "t"]), case["can_exports_h"], ["r", "h", "t"])
    P.coef["load_neg"] = P.coef["load"].with_columns((-pl.col("value")).alias("value"))
    P.coef["load_var"] = _signed(P.var["LOAD"], ["r", "h", "t"], 1.0)

    # ------------------------------------------------ eq_supply_demand_balance
    P.con["eq_supply_demand_balance"] = P.var["LOAD"]
    P.coef["bal_gen"] = _signed(_in(P.var["GEN"], "r", S["land"]), GEN_IDX, 1.0)
    routes_notvsc = _in(routes, "trtype", case.members("notvsc"))
    P.coef["bal_import"] = (                                 # (1 - tranloss) on FLOW(r->rr), AC and LCC routes only
        routes_notvsc.join(case["tranloss"], on=["r", "rr", "trtype"], how="left")
        .with_columns((1.0 - pl.col("value").fill_null(0.0)).alias("value"))
        .select(ROUTE_IDX + ["value"])
    )
    P.coef["bal_export"] = _signed(routes_notvsc, ROUTE_IDX, -1.0)
    P.coef["bal_stor_in"] = _signed(P.var["STORAGE_IN"].join(valcap, on=V4, how="semi"), GEN_IDX, -1.0)
    P.coef["bal_load"] = _signed(P.var["LOAD"], ["r", "h", "t"], -1.0)

    # ---------------------------------------- eq_capacity_limit / _nd
    cl_techs = (set(P.var["GEN"]["i"].unique().to_list())
                - S["spur_techs"] - S["storage_standalone"]
                - (S["storage_hybrid"] - S["csp"]) - S["nondispatch"])
    P.con["eq_capacity_limit"] = _in(P.var["GEN"], "i", cl_techs)
    P.coef["caplim"] = _on_domain(P.con["eq_capacity_limit"], case["slice_cap_coef"], GEN_IDX)
    P.coef["caplim_gen"] = _signed(P.con["eq_capacity_limit"], GEN_IDX, -1.0)
    P.con["eq_capacity_limit_nd"] = _not_in(_in(P.var["GEN"], "i", S["nondispatch"]), "i", S["spur_techs"])
    P.coef["caplim_nd"] = _on_domain(P.con["eq_capacity_limit_nd"], case["slice_cap_coef"], GEN_IDX)
    P.coef["caplim_nd_gen"] = _signed(P.con["eq_capacity_limit_nd"], GEN_IDX, -1.0)

    # ---------------------------------------------------- capacity stock
    not_ret = valcap.join(retiretech, on=V4, how="anti")
    not_ret = _not_in(not_ret, "i", S["upgrade"])
    P.con["eq_cap_init_noret"] = _in(not_ret, "v", S["initv"]).select(V4)
    exog = _mul(case["m_capacity_exog"], case["degrade_init"], V4)
    P.coef["cap_init"] = _on_domain(P.con["eq_cap_init_noret"], exog, V4)

    def _stock_terms(domain, inv_var, state_name, ret_name=None, extra_name=None):
        """Coefficient of current-year investment and the constant from past years."""
        if inv_var not in P.var:
            return (pl.DataFrame(schema={c: pl.Utf8 for c in ["i", "v", "r"]} | {"t": pl.Int64, "tt": pl.Int64, "value": pl.Float64}),
                    domain.select(V4).with_columns(pl.lit(0.0).alias("value")))
        cond = case["inv_cond"].join(domain, on=V4, how="semi")
        dn = case["degrade_new"]
        cur = (cond.join(tmodel.rename({"t": "tt"}), on="tt", how="semi")
               .join(P.var[inv_var].rename({"t": "tt"}), on=["i", "v", "r", "tt"], how="semi")
               .join(dn, on=["i", "tt", "t"], how="inner")
               .select(V4 + ["tt", "value"]))
        past_c = (cond.join(tfix.rename({"t": "tt"}), on="tt", how="semi")
                  .join(dn, on=["i", "tt", "t"], how="inner")
                  .join(case[state_name].rename({"value": "lvl"}), on=["i", "v", "r", "tt"], how="inner")
                  .with_columns((pl.col("value") * pl.col("lvl")).alias("value"))
                  .group_by(V4).agg(pl.col("value").sum()))
        const = _on_domain(domain, past_c, V4)
        if ret_name is not None:
            const = _add(const, case[ret_name], V4, sign=-1.0)
        if extra_name is not None:
            ex = case[extra_name].select(V4 + ["value"])
            const = (const.join(ex.rename({"value": "ex"}), on=V4, how="left")
                     .with_columns((pl.col("value") + pl.col("ex").fill_null(0.0)).alias("value"))
                     .drop("ex"))
        return cur, const

    P.con["eq_cap_new_noret"] = _in(not_ret, "v", S["newv"]).select(V4)
    P.coef["cap_new_inv"], P.coef["cap_new_const"] = _stock_terms(
        P.con["eq_cap_new_noret"], "INV", "state_INV", "slice_prescr_ret")

    P.con["eq_cap_energy_new_noret"] = _in(valcap, "i", S["battery"]).select(V4)
    P.coef["cap_energy_inv"], P.coef["cap_energy_const"] = _stock_terms(
        P.con["eq_cap_energy_new_noret"], "INV_ENERGY", "state_INV_ENERGY",
        "slice_prescr_ret_energy", extra_name="m_capacity_exog_energy")
    P.coef["cap_energy_cap"] = _signed(P.var["CAP_ENERGY"], V4, -1.0)

    # --------------------------------------------------- eq_rsc_inv_account
    P.con["eq_rsc_inv_account"] = rsc_valinv.select(V4)
    P.coef["rscacc_rsc"] = _signed(P.var["INV_RSC"], RSC_IDX, 1.0)
    P.coef["rscacc_inv"] = _signed(P.var["INV"].join(P.con["eq_rsc_inv_account"], on=V4, how="semi"), V4, -1.0)

    sw_up = int(case.scalar("Sw_Upgrades"))
    sw_ref = int(case.scalar("Sw_Refurb"))
    sw_fp = int(case.scalar("Sw_ForcePrescription"))
    if int(case.scalar("Sw_PCM")):
        raise NotImplementedError("Sw_PCM=1 is not ported")
    if sw_up == 2:
        raise NotImplementedError("Sw_Upgrades=2 stock equations are not ported")
    refurb = case.members("refurbtech")
    noret = case.members("noret_upgrade_tech")
    coal = case.members("coal")
    valcap_tfix = case["valcap_tfix"]
    valinv_tfix = case["valinv_tfix"]
    tfix_tt = tfix.rename({"t": "tt"})
    tmodel_tt = tmodel.rename({"t": "tt"})
    link = case["upgrade_from"].rename({"i": "ii", "ii": "i"})   # ii: upgrade tech, i: the tech it is upgraded from
    tprev = case["tprev"].join(tmodel, on="t", how="semi")
    dn = case["degrade_new"]

    if sw_ref:
        P.var["INV_REFURB"] = _in(valinv, "i", refurb).select(V4)
    if sw_up:
        P.var["UPGRADES"] = _in(valcap, "i", S["upgrade"]).select(V4)
        P.var["UPGRADES_RETIRE"] = _not_in(P.var["UPGRADES"], "i", noret)
    allow_cap = case["allow_cap_up"].join(tmodel, on="t", how="semi").select(RSC_IDX)
    allow_ener = case["allow_ener_up"].join(tmodel, on="t", how="semi").select(RSC_IDX)
    if allow_cap.height:
        P.var["INV_CAP_UP"] = allow_cap
    if allow_ener.height:
        P.var["INV_ENER_UP"] = allow_ener

    def _netup_cur(domain):
        rows = domain.select(V4).join(link, on="i", how="inner")
        up = rows.join(P.var["UPGRADES"].rename({"i": "ii"}), on=["ii", "v", "r", "t"], how="semi") if "UPGRADES" in P.var else rows.head(0)
        ret = (rows.join(P.var["UPGRADES_RETIRE"].rename({"i": "ii"}), on=["ii", "v", "r", "t"], how="semi")
               if "UPGRADES_RETIRE" in P.var else rows.head(0))
        return _signed(up, V4 + ["ii"], -1.0), _signed(ret, V4 + ["ii"], 1.0)

    def _netup_past(domain, upto):
        rows = domain.join(link, on="i", how="inner")
        st_up = case["state_UPGRADES"].rename({"i": "ii"}).join(valcap_tfix.rename({"i": "ii"}), on=["ii", "v", "r", "tt"], how="semi")
        st_ret = case["state_UPGRADES_RETIRE"].rename({"i": "ii"}).join(valcap_tfix.rename({"i": "ii"}), on=["ii", "v", "r", "tt"], how="semi")
        st_ret = _not_in(st_ret, "ii", noret)
        st_up = st_up.rename({"tt": "ttt"})
        st_ret = st_ret.rename({"tt": "ttt"})
        up = rows.join(st_up, on=["ii", "v", "r"], how="inner").filter(pl.col("ttt") <= pl.col(upto))
        ret = rows.join(st_ret, on=["ii", "v", "r"], how="inner").filter(pl.col("ttt") <= pl.col(upto))
        both = pl.concat([up.select(V4 + ["value"]), ret.with_columns((-pl.col("value")).alias("value")).select(V4 + ["value"])])
        return both.group_by(V4).agg(pl.col("value").sum())

    def _prev_cap(domain, degrade):
        prev = (domain.join(tprev, on="t", how="inner")
                .join(valcap_tfix, on=["i", "v", "r", "tt"], how="semi")
                .join(case["state_CAP"].rename({"value": "cap_prev"}), on=["i", "v", "r", "tt"], how="left")
                .with_columns(pl.col("cap_prev").fill_null(0.0)))
        if degrade:
            prev = (prev.join(dn, on=["i", "tt", "t"], how="left")
                    .with_columns((pl.col("cap_prev") * pl.col("value").fill_null(0.0)).alias("cap_prev")).drop("value"))
        const = _on_domain(domain, prev.select(V4 + [pl.col("cap_prev").alias("value")]), V4)
        const = _add(const, _netup_past(prev.select(V4 + ["tt"]), "tt"), V4)
        return _add(const, _netup_past(domain, "t"), V4, sign=-1.0)

    def _capup_terms(domain, degrade):
        cur = allow_cap.join(domain, on=V4, how="semi")
        if degrade:
            cur = (cur.join(dn.filter(pl.col("tt") == pl.col("t")).select(["i", "t", "value"]), on=["i", "t"], how="left")
                   .with_columns(pl.col("value").fill_null(0.0)))
        else:
            cur = cur.with_columns(pl.lit(1.0).alias("value"))
        past = (case["state_INV_CAP_UP"].join(tfix_tt, on="tt", how="semi")
                .join(case["allow_cap_up"].rename({"t": "tt"}), on=["i", "v", "r", "rscbin", "tt"], how="semi")
                .join(domain, on=["i", "v", "r"], how="inner"))
        if degrade:
            past = past.join(dn, on=["i", "tt", "t"], how="inner").with_columns((pl.col("value") * pl.col("value_right")).alias("value"))
        past = past.group_by(V4).agg(pl.col("value").sum())
        return cur.select(RSC_IDX + ["value"]), past

    noret_init = P.con["eq_cap_init_noret"]
    capup_cur, capup_past = _capup_terms(noret_init, degrade=True)
    P.coef["cap_init"] = _add(_add(P.coef["cap_init"], capup_past, V4), _netup_past(noret_init, "t"), V4, sign=-1.0)
    P.coef["noret_init_capup"] = capup_cur
    P.coef["noret_init_up"], P.coef["noret_init_ret"] = _netup_cur(noret_init)
    P.coef["noret_init_cap"] = _signed(noret_init, V4, -1.0)
    noret_new = P.con["eq_cap_new_noret"]
    P.coef["noret_new_refurb"], const_ref = _stock_terms(noret_new, "INV_REFURB", "state_INV_REFURB")
    capup_cur, capup_past = _capup_terms(noret_new, degrade=True)
    const = _add(_add(P.coef["cap_new_const"], const_ref, V4), capup_past, V4)
    P.coef["cap_new_const"] = _add(const, _netup_past(noret_new, "t"), V4, sign=-1.0)
    P.coef["noret_new_capup"] = capup_cur
    P.coef["noret_new_up"], P.coef["noret_new_ret"] = _netup_cur(noret_new)
    P.coef["noret_new_cap"] = _signed(noret_new, V4, -1.0)

    ret_rows = _not_in(valcap.join(retiretech, on=V4, how="semi"), "i", S["upgrade"]).select(V4)
    ret_init = _in(ret_rows, "v", S["initv"])
    ret_new = _in(ret_rows, "v", S["newv"])

    P.con["eq_cap_init_retmo"] = ret_init
    P.coef["retmo_init_const"] = _prev_cap(ret_init, degrade=False)
    P.coef["retmo_init_up"], P.coef["retmo_init_ret"] = _netup_cur(ret_init)
    P.coef["retmo_init_cap"] = _signed(ret_init, V4, -1.0)
    P.coef["retmo_init_capup"], _ = _capup_terms(ret_init, degrade=False)

    P.con["eq_cap_init_retub"] = ret_init
    capup_cur, capup_past = _capup_terms(ret_init, degrade=True)
    const = _add(_on_domain(ret_init, exog, V4), capup_past, V4)
    P.coef["retub_init_const"] = _add(const, _netup_past(ret_init, "t"), V4, sign=-1.0)
    P.coef["retub_init_capup"] = capup_cur
    P.coef["retub_init_up"], P.coef["retub_init_ret"] = _netup_cur(ret_init)
    P.coef["retub_init_cap"] = _signed(ret_init, V4, -1.0)

    P.con["eq_cap_new_retmo"] = ret_new
    P.coef["retmo_new_const"] = _prev_cap(ret_new, degrade=True)
    P.coef["retmo_new_inv"] = _signed(P.var["INV"].join(ret_new, on=V4, how="semi"), V4, 1.0)
    P.coef["retmo_new_refurb"] = (_signed(P.var["INV_REFURB"].join(ret_new, on=V4, how="semi"), V4, 1.0)
                                  if "INV_REFURB" in P.var else _signed(ret_new.head(0), V4, 1.0))
    P.coef["retmo_new_capup"], _ = _capup_terms(ret_new, degrade=False)
    P.coef["retmo_new_up"], P.coef["retmo_new_ret"] = _netup_cur(ret_new)
    P.coef["retmo_new_cap"] = _signed(ret_new, V4, -1.0)

    P.con["eq_cap_new_retub"] = ret_new
    P.coef["retub_new_inv"], const = _stock_terms(ret_new, "INV", "state_INV", "slice_prescr_ret")
    P.coef["retub_new_refurb"], const_ref = _stock_terms(ret_new, "INV_REFURB", "state_INV_REFURB")
    const = _add(const, const_ref, V4)
    capup_cur, capup_past = _capup_terms(ret_new, degrade=True)
    const = _add(const, capup_past, V4)
    P.coef["retub_new_const"] = _add(const, _netup_past(ret_new, "t"), V4, sign=-1.0)
    P.coef["retub_new_capup"] = capup_cur
    P.coef["retub_new_up"], P.coef["retub_new_ret"] = _netup_cur(ret_new)
    P.coef["retub_new_cap"] = _signed(ret_new, V4, -1.0)

    if sw_fp:
        fp_dom = _in(case["force_prescribe"].join(valinv, on=V4, how="semi"), "v", S["newv"]).select(V4)
        fy = case["firstyear"].rename({"value": "fy"})
        k1 = (fp_dom.join(fy, on="i", how="left")
              .with_columns(pl.when(pl.col("t") >= pl.col("fy").fill_null(0.0)).then(1.0).otherwise(0.0).alias("k1")).drop("fy"))
        off = (_in(fp_dom, "i", case.members("ofswind"))
               .join(case["r_offshore"], on=["r", "t"], how="semi")
               .filter(pl.col("t") >= case.scalar("firstyear_RPS"))
               .join(case["r_st"], on="r", how="inner")
               .join(case["offshore_cap_req"], on=["st", "t"], how="inner")
               .select(V4).unique().with_columns(pl.lit(1.0).alias("k2")))
        k = (k1.join(off, on=V4, how="left").with_columns((pl.col("k1") + pl.col("k2").fill_null(0.0)).alias("value"))
             .select(V4 + ["value"]).filter(pl.col("value") != 0.0))
        P.con["eq_forceprescription_power"] = fp_dom
        P.coef["fp_build"] = _on_domain(fp_dom, case["prescribed_build"], V4).with_columns((-pl.col("value")).alias("value"))
        P.coef["fp_inv"] = _signed(fp_dom, V4, 1.0)
        P.coef["fp_refurb"] = (_signed(P.var["INV_REFURB"].join(fp_dom, on=V4, how="semi"), V4, 1.0)
                               if "INV_REFURB" in P.var else _signed(fp_dom.head(0), V4, 1.0))
        P.coef["fp_extra"] = k.with_columns((-pl.col("value")).alias("value"))
        P.var["EXTRA_PRESCRIP"] = k.select(V4)
        fpe_dom = _in(fp_dom, "i", S["battery"])
        P.con["eq_forceprescription_energy"] = fpe_dom
        P.coef["fpe_build"] = _on_domain(fpe_dom, case["prescribed_build_energy"], V4).with_columns((-pl.col("value")).alias("value"))
        P.coef["fpe_inv"] = _signed(fpe_dom, V4, 1.0)
        ke = k1.filter(pl.col("k1") != 0.0).join(fpe_dom, on=V4, how="semi").select(V4)
        P.coef["fpe_extra"] = _signed(ke, V4, -1.0)
        P.var["EXTRA_PRESCRIP_ENERGY"] = ke

    if sw_ref:
        rl_dom = case["refurbtech"].join(case["r"], how="cross").join(tmodel, how="cross").select(["i", "r", "t"])
        mrc = case["m_refurb_cond"].join(tmodel, on="t", how="semi")
        cur_inv = (mrc.join(tmodel_tt, on="tt", how="semi")
                   .join(P.var["INV"].rename({"t": "tt"}), on=["i", "v", "r", "tt"], how="semi")
                   .select(["i", "r", "t", pl.col("v").alias("vv")]).with_columns(pl.lit(1.0).alias("value")))
        past_inv = (mrc.join(tfix_tt, on="tt", how="semi").join(valinv_tfix, on=["i", "v", "r", "tt"], how="semi")
                    .join(case["state_INV"], on=["i", "v", "r", "tt"], how="inner").group_by(["i", "r", "t"]).agg(pl.col("value").sum()))
        avail = (case["avail_retire_exog_rsc"].rename({"t": "tt"}).join(tmodel, how="cross").filter(pl.col("tt") <= pl.col("t"))
                 .group_by(["i", "r", "t"]).agg(pl.col("value").sum()))
        icond = case["inv_cond"].join(tmodel, on="t", how="semi")
        cur_ref = (icond.join(tmodel_tt, on="tt", how="semi")
                   .join(P.var["INV_REFURB"].rename({"t": "tt"}), on=["i", "v", "r", "tt"], how="semi")
                   .select(["i", "r", "t", pl.col("v").alias("vv")]).with_columns(pl.lit(-1.0).alias("value")))
        past_ref = (icond.join(tfix_tt, on="tt", how="semi").join(valinv_tfix, on=["i", "v", "r", "tt"], how="semi")
                    .join(case["state_INV_REFURB"], on=["i", "v", "r", "tt"], how="inner").group_by(["i", "r", "t"]).agg(pl.col("value").sum()))
        rl_rows = (pl.concat([cur_inv.select(["i", "r", "t"]), cur_ref.select(["i", "r", "t"])]).unique()
                   .join(rl_dom, on=["i", "r", "t"], how="semi"))
        const = _add(_on_domain(rl_rows, past_inv, ["i", "r", "t"]), avail, ["i", "r", "t"])
        P.coef["refurblim_const"] = _add(const, past_ref, ["i", "r", "t"], sign=-1.0)
        P.coef["refurblim_inv"] = cur_inv
        P.coef["refurblim_refurb"] = cur_ref
        P.con["eq_refurblim"] = rl_rows
        P.options["refurblim_rows_without_variables"] = rl_dom.height - rl_rows.height

    rsc_cap_dom = (_not_in(_in(valcap, "i", S["rsc_i"]), "i", case.members("sccapcosttech"))
                   .join(case["rscbin"], how="cross").select(RSC_IDX))
    P.var["CAP_RSC"] = rsc_cap_dom
    P.con["eq_cap_rsc"] = rsc_cap_dom
    exog0 = (_in(case["capacity_exog_rsc"], "i", case.members("exog_rsc")).join(case["tfirst"], on="t", how="semi")
             .group_by(["i", "v", "r", "rscbin"]).agg(pl.col("value").sum()).join(tmodel, how="cross"))
    past_rsc = (case["state_INV_RSC"].join(tfix_tt, on="tt", how="semi")
                .join(case["m_rscfeas"], on=["r", "i", "rscbin"], how="semi")
                .join(valinv_tfix, on=["i", "v", "r", "tt"], how="semi")
                .join(tmodel, how="cross").filter(pl.col("tt") <= pl.col("t"))
                .group_by(RSC_IDX).agg(pl.col("value").sum()))
    P.coef["cap_rsc_const"] = _add(_on_domain(rsc_cap_dom, exog0, RSC_IDX), past_rsc, RSC_IDX)
    P.coef["cap_rsc_inv"] = _signed(P.var["INV_RSC"].join(rsc_cap_dom, on=RSC_IDX, how="semi"), RSC_IDX, 1.0)
    P.coef["cap_rsc_cap"] = _signed(rsc_cap_dom, RSC_IDX, -1.0)

    if sw_up:
        uy = case.scalar("Sw_UpgradeYear")
        caa = case.scalar("caa_coal_retire_year")
        up_dom = P.var["UPGRADES"]
        from_ok = (up_dom.join(case["upgrade_from"], on="i", how="inner")
                   .join(valcap.rename({"i": "ii"}), on=["ii", "v", "r", "t"], how="semi").select(V4).unique())
        cur = (from_ok.filter((pl.col("t") >= uy) & (~pl.col("i").is_in(list(coal)) | (pl.col("t") <= caa)))
               .join(case["upgrade_derate"], on=V4, how="left")
               .with_columns((1.0 - pl.col("value").fill_null(0.0)).alias("value")))
        from_ok_fix = (case["state_UPGRADES"].join(valcap_tfix, on=["i", "v", "r", "tt"], how="semi")
                       .join(case["upgrade_from"], on="i", how="inner")
                       .join(valcap_tfix.rename({"i": "ii"}), on=["ii", "v", "r", "tt"], how="semi")
                       .select(["i", "v", "r", "tt", "value"]).unique(subset=["i", "v", "r", "tt"]))
        past = (from_ok_fix.join(tmodel, how="cross")
                .filter((pl.col("tt") >= uy) & (pl.col("tt") <= pl.col("t")) & (~pl.col("i").is_in(list(coal)) | (pl.col("tt") <= caa)))
                .join(case["upgrade_derate"].rename({"t": "tt", "value": "derate"}), on=["i", "v", "r", "tt"], how="left")
                .with_columns((pl.col("value") * (1.0 - pl.col("derate").fill_null(0.0))).alias("value"))
                .group_by(V4).agg(pl.col("value").sum()))
        ret_past = (_not_in(case["state_UPGRADES_RETIRE"], "i", noret).join(valcap_tfix, on=["i", "v", "r", "tt"], how="semi")
                    .join(tmodel, how="cross").group_by(V4).agg(pl.col("value").sum()))
        const = _add(_on_domain(up_dom, past, V4), ret_past, V4, sign=-1.0)
        P.con["eq_cap_upgrade"] = up_dom
        P.coef["cap_upgrade_const"] = const
        P.coef["cap_upgrade_up"] = cur.select(V4 + ["value"])
        P.coef["cap_upgrade_ret"] = _signed(P.var["UPGRADES_RETIRE"], V4, -1.0)
        P.coef["cap_upgrade_cap"] = _signed(up_dom, V4, -1.0)

    for name, allow_now, var, cap_tab, state in (("eq_cap_up", allow_cap, "INV_CAP_UP", "cap_cap_up", "state_INV_CAP_UP"),
                                                   ("eq_ener_up", allow_ener, "INV_ENER_UP", "cap_ener_up", "state_INV_ENER_UP")):
        if allow_now.height:
            past = (case[state].join(tfix_tt, on="tt", how="semi").join(allow_now, on=["i", "v", "r", "rscbin"], how="inner")
                    .group_by(RSC_IDX).agg(pl.col("value").sum()))
            P.con[name] = allow_now
            P.coef[f"{name}_const"] = _add(_on_domain(allow_now, case[cap_tab], RSC_IDX), past, RSC_IDX, sign=-1.0)
            P.coef[f"{name}_inv"] = _signed(P.var[var], RSC_IDX, -1.0)

    # ------------------------------------------------------------ storage
    sc_techs = (S["storage_standalone"] - S["evmc_storage"])  # hybrids off in the slice
    P.con["eq_storage_capacity"] = _in(P.var["GEN"], "i", sc_techs)
    P.coef["stor_cap"] = _on_domain(P.con["eq_storage_capacity"], case["slice_stor_cap_coef"], GEN_IDX)
    P.coef["stor_cap_gen"] = _signed(P.con["eq_storage_capacity"], GEN_IDX, -1.0)
    P.coef["stor_cap_in"] = _signed(P.var["STORAGE_IN"].join(P.con["eq_storage_capacity"], on=GEN_IDX, how="semi"), GEN_IDX, -1.0)

    P.con["eq_storage_duration"] = P.var["STORAGE_LEVEL"].join(valcap, on=V4, how="semi")
    # coefficients carried on the row index (i,v,r,h,t) so no broadcasting is needed
    P.coef["stor_dur_cap"] = (P.con["eq_storage_duration"]
                              .join(case["slice_dur_coef"], on=["i", "v", "r"], how="inner"))
    P.coef["stor_dur_energy"] = _in(P.con["eq_storage_duration"], "i", S["battery"]).with_columns(
        pl.lit(1.0).alias("value"))
    P.coef["stor_dur_level"] = _signed(P.var["STORAGE_LEVEL"], GEN_IDX, -1.0)

    P.con["eq_storage_level"] = P.var["STORAGE_LEVEL"]
    P.coef["stor_lvl_next"] = case["nexth"].select(["h", "hh"]).with_columns(pl.lit(1.0).alias("value"))
    P.coef["stor_lvl_this"] = _signed(P.var["STORAGE_LEVEL"], GEN_IDX, -1.0)
    eff = case["storage_eff"].join(case["hours_daily"].rename({"value": "hd"}), how="cross")
    P.coef["stor_lvl_in"] = (eff.with_columns((-(pl.col("value") * pl.col("hd"))).alias("value"))
                             .select(["i", "h", "t", "value"]))
    P.coef["stor_lvl_gen"] = (P.con["eq_storage_level"].join(case["hours_daily"], on="h", how="inner")
                              .select(GEN_IDX + ["value"]))

    # ------------------------------------------------------- transmission
    P.con["eq_CAPTRAN_ENERGY"] = P.var["CAPTRAN_ENERGY"]
    P.con["eq_CAPTRAN_PRM"] = P.var["CAPTRAN_PRM"]
    derate = case.scalar("Sw_TransInvPRMderate")
    past_tran = (case["state_INVTRAN"].join(tfix.rename({"t": "tt"}), on="tt", how="semi")
                 .join(tmodel, how="cross").filter(pl.col("tt") <= pl.col("t"))
                 .group_by(ROUTE_IDX).agg(pl.col("value").sum()))
    ce = _on_domain(P.var["CAPTRAN_ENERGY"], case["trancap_init_energy"], ["r", "rr", "trtype"])
    ce = _on_domain(ce.rename({"value": "init"}), past_tran, ROUTE_IDX)
    P.coef["captran_e_const"] = ce.with_columns((-(pl.col("init") + pl.col("value"))).alias("value")).drop("init")
    P.coef["captran_e_cap"] = _signed(P.var["CAPTRAN_ENERGY"], ROUTE_IDX, 1.0)
    cp = _on_domain(P.var["CAPTRAN_PRM"], case["trancap_init_prm"], ["r", "rr", "trtype"])
    cp = _on_domain(cp.rename({"value": "init"}), past_tran, ROUTE_IDX)
    P.coef["captran_p_const"] = cp.with_columns(
        (-(pl.col("init") + (1.0 - derate) * pl.col("value"))).alias("value")).drop("init")
    P.coef["captran_p_cap"] = _signed(P.var["CAPTRAN_PRM"], ROUTE_IDX, 1.0)
    if "INVTRAN" in P.var:
        P.coef["captran_e_inv"] = _signed(P.var["INVTRAN"].join(P.var["CAPTRAN_ENERGY"], on=ROUTE_IDX, how="semi"), ROUTE_IDX, -1.0)
        P.coef["captran_p_inv"] = _signed(P.var["INVTRAN"].join(P.var["CAPTRAN_PRM"], on=ROUTE_IDX, how="semi"), ROUTE_IDX, -(1.0 - derate))

    P.con["eq_transmission_limit"] = P.var["FLOW"]
    ht = h.join(tmodel, how="cross")
    delta = _on_domain(ht, case["trans_cap_delta"], ["h", "t"]).with_columns((1.0 + pl.col("value")).alias("value"))
    P.coef["tlim_rep"] = (_in(P.con["eq_transmission_limit"], "h", h_rep)
                          .join(delta, on=["h", "t"], how="inner").select(FLOW_IDX + ["value"]))
    P.coef["tlim_stress"] = (_in(P.con["eq_transmission_limit"], "h", h_stress)
                             .join(P.var["CAPTRAN_PRM"], on=ROUTE_IDX, how="semi")
                             .join(delta, on=["h", "t"], how="inner").select(FLOW_IDX + ["value"]))
    P.coef["tlim_flow"] = _signed(P.con["eq_transmission_limit"], FLOW_IDX, -1.0)

    # ---------------------------------------------------------- emissions
    P.con["eq_emit_accounting"] = P.var["EMIT"]
    P.coef["emit_hours"] = _in(case["hours"], "h", h_rep)  # hours(h) on representative hours only
    P.coef["emit_rate"] = (case["emit_rate"].join(tmodel, on="t", how="semi")
                           .join(valgen, on=V4, how="semi")
                           .join(P.var["EMIT"], on=["etype", "e", "r", "t"], how="semi"))
    P.coef["emit_var"] = _signed(P.var["EMIT"], ["etype", "e", "r", "t"], 1.0)
    P.coef["emit_gen"] = (P.coef["emit_rate"].join(P.coef["emit_hours"].rename({"value": "hrs"}), how="cross")
                          .with_columns((-(pl.col("hrs") * pl.col("value"))).alias("value")).select(["etype", "e", "r", "t", "i", "v", "h", "value"]))
    cap_any = case["emit_cap"].group_by("eall").agg(pl.col("value").sum()).filter(pl.col("value") != 0)
    ac_dom = cap_any.select("eall").join(tmodel, how="cross")
    P.con["eq_annual_cap"] = ac_dom
    P.coef["annual_cap_rhs"] = _on_domain(ac_dom, case["emit_cap"], ["eall", "t"])
    cap_etypes = ["process", "upstream"] if int(case.scalar("Sw_Upstream")) else ["process"]
    P.coef["annual_cap_gwp"] = (cap_any.select("eall").join(_in(case["gwp"], "e", S["emit_capped"]), how="cross")
                                .join(pl.DataFrame({"etype": cap_etypes}), how="cross")
                                .with_columns((-pl.col("value")).alias("value")).select(["eall", "etype", "e", "value"]))

    sw_opres = int(case.scalar("Sw_OpRes"))
    sw_sc = int(case.scalar("Sw_StartCost"))
    if int(case.scalar("Sw_MinLoading")):
        raise NotImplementedError("Sw_MinLoading=1 (eq_minloading, eq_storage_in_minloading) is not ported")
    hybrid_non_csp = S["storage_hybrid"] - S["csp"]
    if int(case.scalar("Sw_HybridPlant")) and _in(valgen, "i", hybrid_non_csp).height:
        raise NotImplementedError("hybrid plant variables (GEN_STORAGE, GEN_PLANT) are not ported")
    before_markets = bool((tmodel["t"].cast(pl.Int64) < int(case.scalar("Sw_StartMarkets"))).all())
    if before_markets:
        P.var["DROPPED"] = rht.select(["r", "h", "t"])
        P.var["EXCESS"] = rht.select(["r", "h", "t"])
        P.coef["bal_dropped"] = _signed(P.var["DROPPED"], ["r", "h", "t"], 1.0)
        P.coef["bal_excess"] = _signed(P.var["EXCESS"], ["r", "h", "t"], -1.0)
    opres_model = case["opres_model"]
    opres_h = case["opres_h"]
    hours = case["hours"]
    hd = case["hours_daily"].rename({"value": "hd"})
    szn_all = case["szn"]
    h_szn = case["h_szn"]
    hrs_szn = h_szn.join(hours, on="h", how="inner")
    sum_hours_szn = _fsum(hrs_szn, ["szn"]).rename({"value": "sumh"})
    hours_rep = _in(hours, "h", h_rep)
    sum_hours_rep = float(_fsum_all(hours_rep["value"]))
    valgen_irt = valgen.select(["i", "r", "t"]).unique()
    bio_r = _in(valgen, "i", S["bio"] | S["cofire"]).select(["r", "t"]).unique()

    if sw_opres:
        P.var["OPRES"] = (opres_model.join(valgen, how="cross").join(case["reserve_frac"], on=["i", "ortype"], how="semi")
                          .join(opres_h, how="cross").select(["ortype", "i", "v", "r", "h", "t"]))
        P.var["OPRES_FLOW"] = (opres_model.join(case["opres_routes"].join(tmodel, on="t", how="semi"), how="cross")
                               .join(opres_h, how="cross").select(["ortype", "r", "rr", "h", "t"]))
    if sw_sc:
        P.var["RAMPUP"] = (valgen_irt.join(case["startcost"], on="i", how="semi")
                           .join(case["numhours_nexth"].select(["h", "hh"]), how="cross").select(["i", "r", "h", "hh", "t"]))
    P.var["BIOUSED"] = case["bioclass"].join(bio_r, how="cross").select(["bioclass", "r", "t"])

    if sw_opres:
        OR4 = ["ortype", "r", "h", "t"]
        req = opres_model.join(case["r"], how="cross").join(opres_h, how="cross").join(tmodel, how="cross").select(OR4)
        P.con["eq_OpRes_requirement"] = req
        P.coef["opres_gen"] = _signed(P.var["OPRES"], ["ortype", "i", "v", "r", "h", "t"], 1.0)
        P.coef["opres_dropped"] = (_signed(req.join(P.var["DROPPED"], on=["r", "h", "t"], how="semi"), OR4, 1.0)
                                   if "DROPPED" in P.var else _signed(req.head(0), OR4, 1.0))
        loss = case["tranloss"].filter(pl.col("trtype") == "ac").select(["r", "rr", pl.col("value").alias("loss")])
        P.coef["opres_import"] = (P.var["OPRES_FLOW"].join(loss, on=["r", "rr"], how="left")
                                  .with_columns((1.0 - pl.col("loss").fill_null(0.0)).alias("value")).select(["ortype", "r", "rr", "h", "t", "value"]))
        P.coef["opres_export"] = _signed(P.var["OPRES_FLOW"], ["ortype", "r", "rr", "h", "t"], -1.0)
        orp = case["orperc"]

        def orp_val(cat):
            return orp.filter(pl.col("orcat") == cat).select(["ortype", pl.col("value").alias("k")])

        P.coef["opres_load"] = (req.join(orp_val("or_load"), on="ortype", how="inner")
                                .with_columns((-pl.col("k")).alias("value")).select(OR4 + ["value"]))
        wind_gen = _in(P.var["GEN"], "i", S["wind"]).join(opres_h, on="h", how="semi")
        P.coef["opres_wind"] = (opres_model.join(wind_gen, how="cross").join(orp_val("or_wind"), on="ortype", how="inner")
                                .with_columns((-pl.col("k")).alias("value")).select(["ortype", "i", "v", "r", "h", "t", "value"]))
        pv_cap = _in(valcap, "i", S["pv"] | S["pvb"]).join(case["ilr"].rename({"value": "ilr"}), on="i", how="left")
        if pv_cap.filter(pl.col("ilr").is_null()).height:
            raise ValueError("ilr is missing for a PV technology in valcap (GAMS would divide by zero)")
        day = case["dayhours"].join(opres_h, on="h", how="semi")
        P.coef["opres_pv"] = (opres_model.join(pv_cap, how="cross").join(day, how="cross").join(orp_val("or_pv"), on="ortype", how="inner")
                              .with_columns((-((1.0 / pl.col("ilr")) * pl.col("k"))).alias("value")).select(["ortype", "i", "v", "r", "h", "t", "value"]))

        so_dom = (_in(P.var["GEN"], "i", S["storage_standalone"] | hybrid_non_csp | S["hyd_add_pump"])
                  .join(opres_h, on="h", how="semi").select(GEN_IDX))
        P.con["eq_storage_opres"] = so_dom
        P.coef["sopres_level"] = _signed(P.var["STORAGE_LEVEL"].join(so_dom, on=GEN_IDX, how="semi"), GEN_IDX, 1.0)
        P.coef["sopres_gen"] = (_not_in(so_dom, "i", hybrid_non_csp).join(hd, on="h", how="inner")
                                .with_columns((-pl.col("hd")).alias("value")).select(GEN_IDX + ["value"]))
        opres_rows = P.var["OPRES"].join(so_dom, on=GEN_IDX, how="semi")
        reg_type = "reg" if sw_opres == 1 else "combo"
        eff = case["storage_eff"].rename({"value": "eff"})
        ref = case.scalar("reg_energy_frac")
        P.coef["sopres_reg"] = (opres_rows.filter(pl.col("ortype") == reg_type).join(hd, on="h", how="inner").join(eff, on=["i", "t"], how="left")
                                .with_columns((-(((pl.col("hd") * (1.0 - pl.col("eff").fill_null(0.0))) / 2.0) * ref)).alias("value"))
                                .select(["ortype", "i", "v", "r", "h", "t", "value"]))
        P.coef["sopres_all"] = (opres_rows.join(hd, on="h", how="inner").with_columns((-pl.col("hd")).alias("value"))
                                .select(["ortype", "i", "v", "r", "h", "t", "value"]))

        st_dom = _in(valgen, "i", S["thermal_storage"]).join(h, how="cross").join(opres_h, on="h", how="semi").select(GEN_IDX)
        P.con["eq_storage_thermalres"] = st_dom
        P.coef["sthermal_in"] = _signed(P.var["STORAGE_IN"].join(st_dom, on=GEN_IDX, how="semi"), GEN_IDX, 1.0)
        P.coef["sthermal_opres"] = (P.var["OPRES"].join(st_dom, on=GEN_IDX, how="semi")
                                    .join(case["reserve_frac"].rename({"value": "rf"}), on=["i", "ortype"], how="inner")
                                    .with_columns((-pl.col("rf")).alias("value")).select(["ortype", "i", "v", "r", "h", "t", "value"]))

    smf = case["storinmaxfrac"].rename({"value": "smf"})
    sic_rows = (_in(valgen.join(valcap, on=V4, how="semi"), "i", S["storage_standalone"] | S["hyd_add_pump"])
                .join(smf, on=["i", "v", "r"], how="left").with_columns(pl.col("smf").fill_null(0.0)).filter(pl.col("smf") < 1.0))
    sic_dom = sic_rows.select(V4).join(h, how="cross").select(GEN_IDX)
    P.con["eq_storage_in_cap"] = sic_dom
    seas = (h_szn.join(case["seas_cap_frac_delta"].rename({"value": "d"}), on="szn", how="inner")
            .group_by(["i", "v", "r", "h", "t"]).agg(pl.col("d").sum()))
    charge = case["evmc_storage_charge_frac"].rename({"value": "cf"})
    P.coef["sincap_cap"] = (sic_rows.select(V4 + ["smf"]).join(h, how="cross")
                            .join(case["avail"].rename({"value": "avail"}), on=["i", "r", "h"], how="left")
                            .join(seas, on=GEN_IDX, how="left").join(charge, on=["i", "r", "h", "t"], how="left")
                            .with_columns((((pl.col("avail").fill_null(0.0) * pl.col("smf")) * (1.0 + pl.col("d").fill_null(0.0)))
                                           * pl.when(pl.col("i").is_in(list(S["evmc_storage"]))).then(pl.col("cf").fill_null(0.0)).otherwise(1.0)).alias("value"))
                            .select(GEN_IDX + ["value"]))
    P.coef["sincap_in"] = _signed(P.var["STORAGE_IN"].join(sic_dom, on=GEN_IDX, how="semi"), GEN_IDX, -1.0)

    bmd_dom = _in(_in(valcap, "v", S["newv"]), "i", S["battery"]).select(V4)
    P.con["eq_battery_minduration"] = bmd_dom
    P.coef["bmd_energy"] = _signed(P.var["CAP_ENERGY"].join(bmd_dom, on=V4, how="semi"), V4, 1.0)
    P.coef["bmd_cap"] = _signed(bmd_dom, V4, -case.scalar("minbatteryduration"))

    if sw_sc:
        RAMP = ["i", "r", "h", "hh", "t"]
        P.con["eq_ramping"] = P.var["RAMPUP"]
        P.coef["ramp_up"] = _signed(P.var["RAMPUP"], RAMP, 1.0)
        vrows = P.var["RAMPUP"].join(valgen.select(["i", "v", "r", "t"]), on=["i", "r", "t"], how="inner")
        P.coef["ramp_gen_hh"] = _signed(vrows, RAMP + ["v"], -1.0)
        P.coef["ramp_gen_h"] = _signed(vrows, RAMP + ["v"], 1.0)

    DH = ["i", "v", "r", "szn", "t"]
    dh_dom = _in(valgen, "i", S["hydro_d"]).join(szn_all, how="cross").select(DH)
    P.con["eq_dhyd_dispatch"] = dh_dom
    P.coef["dhyd_cap"] = (dh_dom.join(sum_hours_szn, on="szn", how="inner").join(case["m_cf_szn"].rename({"value": "mcs"}), on=DH, how="left")
                          .with_columns((pl.col("sumh") * pl.col("mcs").fill_null(0.0)).alias("value")).select(DH + ["value"]))
    P.coef["dhyd_gen"] = (dh_dom.join(hrs_szn, on="szn", how="inner").with_columns((-pl.col("value")).alias("value")).select(DH + ["h", "value"]))
    if sw_opres:
        P.coef["dhyd_opres"] = (dh_dom.join(hrs_szn, on="szn", how="inner").join(opres_h, on="h", how="semi")
                                .join(P.var["OPRES"].filter(pl.col("ortype") == reg_type), on=GEN_IDX, how="inner")
                                .with_columns((-(pl.col("value") * ref)).alias("value")).select(DH + ["ortype", "h", "value"]))
    else:
        P.coef["dhyd_opres"] = pl.DataFrame(schema={c: pl.Utf8 for c in DH + ["ortype", "h"]} | {"value": pl.Float64}).with_columns(pl.col("t").cast(pl.Int64))

    if int(case.scalar("Sw_Canada")) == 1:
        ci = case["can_imports_szn"].join(tmodel, on="t", how="semi")
        can_gen = (_in(P.var["GEN"], "i", S["canada"]).join(h_szn, on="h", how="inner").join(hours.rename({"value": "hrs"}), on="h", how="inner")
                   .join(ci.select(["r", "szn", "t"]), on=["r", "szn", "t"], how="semi")
                   .with_columns((-pl.col("hrs")).alias("value")).select(["r", "szn", "t", "i", "v", "h", "value"]))
        ci_rows = ci.join(can_gen.select(["r", "szn", "t"]).unique(), on=["r", "szn", "t"], how="semi")
        P.con["eq_Canadian_Imports"] = ci_rows.select(["r", "szn", "t"])
        P.coef["canimp_const"] = ci_rows.select(["r", "szn", "t", "value"])
        P.coef["canimp_gen"] = can_gen

    if int(case.scalar("Sw_MingenFixed")):
        mgf = case["mingen_fixed"].rename({"value": "mf"})
        mgf_dom = valgen.join(mgf, on="i", how="inner").filter(pl.col("t") >= case.scalar("Sw_StartMarkets")).join(h, how="cross")
        P.con["eq_mingen_fixed"] = mgf_dom.select(GEN_IDX)
        P.coef["mgf_gen"] = _signed(mgf_dom, GEN_IDX, 1.0)
        P.coef["mgf_cap"] = (mgf_dom.join(case["avail"].rename({"value": "avail"}), on=["i", "r", "h"], how="left")
                             .with_columns((-(pl.col("mf") * pl.col("avail").fill_null(0.0))).alias("value")).select(GEN_IDX + ["value"]))

    if int(case.scalar("Sw_MinCF")):
        mc = case["minCF"].rename({"value": "mcf"})
        mc_dom = valgen_irt.join(mc, on=["i", "t"], how="inner")
        P.con["eq_min_cf"] = mc_dom.select(["i", "r", "t"])
        P.coef["mincf_gen"] = (valgen.join(mc_dom.select(["i", "r", "t"]), on=["i", "r", "t"], how="semi").join(hours_rep, how="cross")
                               .select(["i", "r", "t", "v", "h", "value"]))
        P.coef["mincf_cap"] = (valgen.join(mc_dom, on=["i", "r", "t"], how="inner")
                               .with_columns((-((1.0 * sum_hours_rep) * pl.col("mcf"))).alias("value")).select(["i", "r", "t", "v", "value"]))

    if int(case.scalar("Sw_MaxDailyCF")):
        MDC = ["i", "r", "szn", "t"]
        mdc = case["maxdailycf"].rename({"value": "mdc"})
        av = case["avail"].rename({"value": "avail"})
        av_szn = _fsum(h_szn.join(av, on="h", how="inner").select(["i", "r", "szn", pl.col("avail").alias("value")]), ["i", "r", "szn"])
        ha_szn = _fsum(hrs_szn.join(av, on="h", how="inner").with_columns((pl.col("value") * pl.col("avail")).alias("value"))
                       .select(["i", "r", "szn", "value"]), ["i", "r", "szn"]).rename({"value": "ha"})
        md_dom = (valgen_irt.join(mdc, on=["i", "t"], how="inner").join(szn_all, how="cross")
                  .join(av_szn.filter(pl.col("value") != 0.0).select(["i", "r", "szn"]), on=["i", "r", "szn"], how="semi"))
        P.con["eq_max_daily_cf"] = md_dom.select(MDC)
        P.coef["maxcf_cap"] = (valgen.join(md_dom, on=["i", "r", "t"], how="inner").join(ha_szn, on=["i", "r", "szn"], how="inner")
                               .with_columns(((1.0 * pl.col("ha")) * pl.col("mdc")).alias("value")).select(MDC + ["v", "value"]))
        P.coef["maxcf_gen"] = (valgen.join(md_dom.select(MDC), on=["i", "r", "t"], how="inner").join(hrs_szn, on="szn", how="inner")
                               .with_columns((-pl.col("value")).alias("value")).select(MDC + ["v", "h", "value"]))

    if int(case.scalar("Sw_Clean_Air_Act")):
        caa_dom = (_not_in(_in(valgen, "i", S["gas"]), "i", S["ccs"]).join(case["heat_rate"], on=V4, how="semi")
                   .join(case["firstyear_v"].rename({"value": "fyv"}), on=["i", "v"], how="inner")
                   .filter((pl.col("fyv") >= case.scalar("caa_first_year")) & (pl.col("t") >= case.scalar("caa_coal_retire_year"))).select(V4))
        P.con["eq_caa_max_cf"] = caa_dom
        P.coef["caa_cap"] = _signed(caa_dom, V4, sum_hours_rep * case.scalar("caa_gas_max_cf"))
        P.coef["caa_gen"] = caa_dom.join(hours_rep, how="cross").with_columns((-pl.col("value")).alias("value")).select(V4 + ["h", "value"])
        std = case.scalar("caa_capture_rate_standard")
        er = case["emit_rate"].filter((pl.col("etype") == "process") & (pl.col("e") == "co2")).select(V4 + [pl.col("value").alias("er")])
        cr = case["capture_rate"].filter(pl.col("e") == "co2").select(V4 + [pl.col("value").alias("cr")])
        coal_gen = (_not_in(_in(valgen, "i", S["coal"]), "i", S["cofire"]).join(case["r_st"], on="r", how="inner")
                    .filter(pl.col("t") >= case.scalar("caa_coal_retire_year"))
                    .join(er, on=V4, how="left").join(cr, on=V4, how="left").join(hours_rep, how="cross")
                    .with_columns(pl.col("er").fill_null(0.0), pl.col("cr").fill_null(0.0))
                    .with_columns((((pl.col("value") * (pl.col("er") + pl.col("cr"))) * (1.0 - std)) + (-(pl.col("value") * pl.col("er")))).alias("value"))
                    .select(["st", "t", "i", "v", "r", "h", "value"]))
        P.con["eq_caa_rate_standard"] = coal_gen.select(["st", "t"]).unique()
        P.coef["caars_gen"] = coal_gen

    P.con["eq_bioused"] = bio_r
    P.coef["bio_used"] = _signed(P.var["BIOUSED"], ["bioclass", "r", "t"], 1.0)
    hr = case["heat_rate"].rename({"value": "hr"})
    bcp = case.scalar("bio_cofire_perc")
    bio_gen = (_in(P.var["GEN"], "i", S["bio"] | S["cofire"]).join(hr, on=V4, how="inner").join(hours.rename({"value": "hrs"}), on="h", how="inner")
               .with_columns(pl.when(pl.col("i").is_in(list(S["cofire"]))).then(-((bcp * pl.col("hrs")) * pl.col("hr")))
                             .otherwise(-(pl.col("hrs") * pl.col("hr"))).alias("value"))
               .select(["r", "t", "i", "v", "h", "value"]))
    P.coef["bio_gen"] = bio_gen
    bl_dom = case["bioclass"].join(case["usda_region"], how="cross").join(tmodel, how="cross").select(["bioclass", "usda_region", "t"])
    bl_used = (P.var["BIOUSED"].join(case["r_usda"], on="r", how="inner").select(["bioclass", "usda_region", "t", "r"])
               .with_columns(pl.lit(-1.0).alias("value")))
    bl_rows = bl_dom.join(bl_used.select(["bioclass", "usda_region", "t"]).unique(), on=["bioclass", "usda_region", "t"], how="semi")
    P.con["eq_biousedlimit"] = bl_rows
    P.coef["biolim_const"] = _on_domain(bl_rows, case["biosupply_cap"], ["usda_region", "bioclass"])
    P.coef["biolim_used"] = bl_used

    if int(case.scalar("Sw_BatteryMandate")):
        bm = case["batterymandate"].join(tmodel, on="t", how="semi").filter(pl.col("t") >= case.scalar("firstyear_battery"))
        bm_cap = (_in(valcap, "i", S["battery"] | S["pvb"]).join(case["r_st"], on="r", how="inner")
                  .join(bm.select(["st", "t"]), on=["st", "t"], how="semi")
                  .join(case["bcr"], on="i", how="left").with_columns(pl.col("value").fill_null(0.0)).select(["st", "t", "i", "v", "r", "value"]))
        bm_rows = bm.join(bm_cap.select(["st", "t"]).unique(), on=["st", "t"], how="semi")
        P.con["eq_batterymandate"] = bm_rows.select(["st", "t"])
        P.coef["bmand_const"] = bm_rows.with_columns((-pl.col("value")).alias("value")).select(["st", "t", "value"])
        P.coef["bmand_cap"] = bm_cap

    CONV = ["r", "h", "intype", "outtype", "t"]
    conv_dom = case["val_converter"].join(tmodel, on="t", how="semi").select(["r", "t"])
    if int(case.scalar("Sw_VSC")):
        eff_vsc = case.scalar("converter_efficiency_vsc")
        P.var["CAP_CONVERTER"] = conv_dom
        P.var["INV_CONVERTER"] = conv_dom
        directions = pl.DataFrame({"intype": ["ac", "vsc"], "outtype": ["vsc", "ac"]})
        P.var["CONVERSION"] = conv_dom.join(h, how="cross").join(directions, how="cross").select(CONV)
        conv_sign = (P.var["CONVERSION"]
                     .with_columns(pl.when(pl.col("intype") == "vsc").then(eff_vsc).otherwise(-1.0 / eff_vsc).alias("value")))
        P.coef["bal_conv"] = conv_sign
        vsc_flow = P.var["FLOW"].filter(pl.col("trtype") == "vsc")
        P.coef["vsc_import"] = (vsc_flow.join(case["tranloss"], on=["r", "rr", "trtype"], how="left")
                                .with_columns((1.0 - pl.col("value").fill_null(0.0)).alias("value"))
                                .rename({"r": "rr", "rr": "r"}).select(FLOW_IDX + ["value"]))
        P.coef["vsc_export"] = _signed(vsc_flow, FLOW_IDX, -1.0)
        P.coef["vsc_conv"] = (P.var["CONVERSION"]
                              .with_columns(pl.when(pl.col("intype") == "ac").then(eff_vsc).otherwise(-1.0 / eff_vsc).alias("value")))
        P.coef["vsc_offgen"] = _signed(_in(P.var["GEN"], "r", case.members("offshore")), GEN_IDX, 1.0)
        P.con["eq_vsc_flow"] = pl.concat([
            P.coef["vsc_import"].select(["r", "h", "t"]), P.coef["vsc_export"].select(["r", "h", "t"]),
            P.coef["vsc_conv"].select(["r", "h", "t"]), P.coef["vsc_offgen"].select(["r", "h", "t"]),
        ]).unique()
        val_conv_fixed = case["val_converter"].join(tfix, on="t", how="semi").select(["r", pl.col("t").alias("tt")])
        past_conv = (case["state_INV_CONVERTER"].join(val_conv_fixed, on=["r", "tt"], how="semi").join(tmodel, how="cross")
                     .filter(pl.col("tt") <= pl.col("t")).group_by(["r", "t"]).agg(pl.col("value").sum()))
        P.con["eq_CAP_CONVERTER"] = conv_dom
        P.coef["capconv_const"] = _on_domain(conv_dom, past_conv, ["r", "t"]).with_columns((-pl.col("value")).alias("value"))
        P.coef["capconv_cap"] = _signed(conv_dom, ["r", "t"], 1.0)
        val_conv_tfix = case["val_converter"].join(tfix, on="t", how="semi").select(["r", "t"])
        conv_unfixed_past = (conv_dom.select("r").unique().join(tfix, how="cross")
                             .join(val_conv_tfix, on=["r", "t"], how="anti").select(["r", "t"]))
        P.var["INV_CONVERTER"] = pl.concat([conv_dom, conv_unfixed_past]).unique()
        conv_cols = P.var["INV_CONVERTER"].rename({"t": "tt"})
        P.coef["capconv_inv"] = (conv_cols.join(conv_dom, on="r", how="inner").filter(pl.col("tt") <= pl.col("t"))
                                 .with_columns(pl.lit(-1.0).alias("value")).select(["r", "tt", "t", "value"]))
        P.con["eq_CONVERSION_limit_energy"] = conv_dom.join(h, how="cross").select(["r", "h", "t"])
        P.coef["convlim_cap"] = _signed(P.con["eq_CONVERSION_limit_energy"], ["r", "h", "t"], 1.0)
        P.coef["convlim_conv"] = _signed(P.var["CONVERSION"], CONV, -1.0)
        conv_max = case.scalar("Sw_VSC_ConverterMax")
        if conv_max:
            P.con["eq_converter_max"] = conv_dom
            P.coef["convmax_const"] = conv_dom.with_columns(pl.lit(float(conv_max)).alias("value"))
            P.coef["convmax_cap"] = _signed(conv_dom, ["r", "t"], -1.0)
    P.coef["poi_conv"] = _signed(conv_dom if "CAP_CONVERTER" in P.var else conv_dom.head(0), ["r", "t"], -1.0)
    if int(case.scalar("Sw_SpurScen")):
        xfeas = case["xfeas"]
        x_all = case["x"]
        sitemap = case["spurline_sitemap"]
        x_r = case["x_r"]
        XT = ["x", "t"]
        XHT = ["x", "h", "t"]
        xt = xfeas.join(tmodel, how="cross").select(XT)
        site_rows = xfeas.join(h, how="cross").join(tmodel, how="cross").select(XHT)
        P.var["AVAIL_SITE"] = site_rows
        P.var["CAP_SPUR"] = x_all.join(tmodel, how="cross").select(XT)
        spur_unfixed_past = x_all.join(xfeas, on="x", how="anti").join(tfix, how="cross").select(XT)
        P.var["INV_SPUR"] = pl.concat([x_all.join(tmodel, how="cross").select(XT), spur_unfixed_past])
        spur_gen = _in(valgen, "i", S["spur_techs"])
        P.con["eq_site_cf"] = site_rows
        P.coef["sitecf_rsc"] = (spur_gen.join(case["spur_cf"], on=V4, how="inner")
                                .join(sitemap, on=["i", "r"], how="inner")
                                .join(case["m_rscfeas"], on=["r", "i", "rscbin"], how="semi")
                                .join(x_r, on=["x", "r"], how="semi")
                                .join(xfeas, on="x", how="semi")
                                .select(XHT + ["i", "v", "r", "rscbin", "value"]))
        P.coef["sitecf_avail"] = _signed(site_rows, XHT, -1.0)
        P.con["eq_spurclip"] = site_rows
        P.coef["spurclip_cap"] = _signed(site_rows, XHT, 1.0)
        P.coef["spurclip_avail"] = _signed(site_rows, XHT, -1.0)
        if not int(case.scalar("Sw_SpurShare")):
            P.con["eq_spur_noclip"] = xt
            P.coef["noclip_cap"] = _signed(xt, XT, 1.0)
            noclip_rows = (sitemap.join(valcap, on=["i", "r"], how="inner")
                           .join(case["ilr"].rename({"value": "ilr"}), on="i", how="left"))
            if noclip_rows.filter(pl.col("ilr").is_null() | (pl.col("ilr") == 0.0)).height:
                raise ValueError("ilr is missing for a spur-line technology (GAMS would divide by zero in eq_spur_noclip)")
            P.coef["noclip_rsc"] = (noclip_rows.join(xt, on=XT, how="semi")
                                    .with_columns((-(1.0 / pl.col("ilr"))).alias("value")).select(XT + ["i", "v", "r", "rscbin", "value"]))
        hyb_avail = (x_r.join(xfeas, on="x", how="semi").join(tmodel, how="cross")
                     .select(["r", "x", "t"]).with_columns(pl.lit(1.0).alias("value")))
        hyb_gen = _signed(_in(P.var["GEN"], "i", S["spur_techs"]), GEN_IDX, -1.0)
        P.coef["hyb_avail"] = hyb_avail
        P.coef["hyb_gen"] = hyb_gen
        P.con["eq_capacity_limit_hybrid"] = pl.concat([
            hyb_avail.select(["r", "t"]).unique().join(h, how="cross").select(["r", "h", "t"]),
            hyb_gen.select(["r", "h", "t"]),
        ]).unique()
        if "OPRES" in P.var:
            P.coef["hyb_opres"] = _signed(_in(P.var["OPRES"], "i", S["spur_techs"]), ["ortype", "i", "v", "r", "h", "t"], -1.0)
        P.con["eq_CAP_SPUR"] = P.var["CAP_SPUR"]
        P.coef["capspur_cap"] = _signed(P.var["CAP_SPUR"], XT, 1.0)
        spur_inv_cols = P.var["INV_SPUR"].rename({"t": "tt"}).join(tmodel, how="cross").filter(pl.col("tt") <= pl.col("t"))
        P.coef["capspur_inv"] = spur_inv_cols.select(["x", "tt", "t"]).with_columns(pl.lit(-1.0).alias("value"))
        past_spur = (case["state_INV_SPUR"].join(xfeas, on="x", how="semi").join(tfix_tt, on="tt", how="semi")
                     .join(tmodel, how="cross").filter(pl.col("tt") <= pl.col("t")).group_by(XT).agg(pl.col("value").sum()))
        P.coef["capspur_const"] = _on_domain(P.var["CAP_SPUR"], past_spur, XT).with_columns((-pl.col("value")).alias("value"))
    R3 = ["r", "rr", "trtype"]
    TSC = ["r", "rr", "tscbin", "t"]
    tscbin = case["tscbin"]
    rinv_ac = routes_inv.filter(pl.col("trtype") == "ac").select(["r", "rr", "t"])
    rinv_all = case["routes_inv"]
    if "INVTRAN" in P.var:
        P.var["INVTRAN_AC"] = rinv_ac.join(tscbin, how="cross").select(TSC)
        binw = case["tsc_binwidth"]
        P.var["TRAN_CAPEX_BINS"] = rinv_ac.join(binw.select(["r", "rr", "tscbin"]), on=["r", "rr"], how="inner").select(TSC)
    if int(case.scalar("Sw_TransIntraCost")):
        P.var["INV_POI"] = case["r"].join(tmodel, how="cross").select(["r", "t"])
    rtg = case["routes_transgroup"]
    grp_pairs = rtg.select(["transgrp", "transgrpp"]).unique()
    if int(case.scalar("Sw_TransGroupContraint")) and grp_pairs.height:
        P.var["CAPTRAN_GRP"] = grp_pairs.join(tmodel, how="cross").select(["transgrp", "transgrpp", "t"])

    if "INVTRAN" in P.var:
        inv = P.var["INVTRAN"]
        dc = _not_in(inv, "trtype", case.members("aclike"))
        P.con["eq_INVTRAN_DC"] = dc
        P.coef["invdc_fwd"] = _signed(dc, ROUTE_IDX, 1.0)
        P.coef["invdc_rev"] = _signed(dc, ROUTE_IDX, -1.0)

        rinv_tfix = case["routes_inv_tfix"]
        past_ac = (case["state_INVTRAN_AC"].join(tfix_tt, on="tt", how="semi")
                   .join(rinv_tfix.filter(pl.col("trtype") == "ac").select(["r", "rr", "tt"]), on=["r", "rr", "tt"], how="semi")
                   .join(tmodel, how="cross").filter(pl.col("tt") <= pl.col("t")).group_by(TSC).agg(pl.col("value").sum()))
        bins_dom = P.var["TRAN_CAPEX_BINS"]
        fwd = case["tsc_forward"].rename({"value": "k"})
        rev = case["tsc_reverse"].rename({"value": "k"})
        P.con["eq_INVTRAN_AC_forward"] = bins_dom
        P.coef["acfwd_const"] = (_on_domain(bins_dom, past_ac, TSC).join(fwd, on=["r", "rr", "tscbin"], how="left")
                                 .with_columns((pl.col("value") * pl.col("k").fill_null(0.0)).alias("value")).select(TSC + ["value"]))
        P.coef["acfwd_inv"] = (bins_dom.join(P.var["INVTRAN_AC"], on=TSC, how="semi").join(fwd, on=["r", "rr", "tscbin"], how="left")
                               .with_columns(pl.col("k").fill_null(0.0).alias("value")).select(TSC + ["value"]))
        P.coef["acfwd_bins"] = _signed(bins_dom, TSC, -1.0)
        P.con["eq_INVTRAN_AC_reverse"] = bins_dom
        past_rev = past_ac.rename({"r": "rr", "rr": "r"}).select(TSC + ["value"])
        P.coef["acrev_const"] = (_on_domain(bins_dom, past_rev, TSC).join(rev, on=["r", "rr", "tscbin"], how="left")
                                 .with_columns((pl.col("value") * pl.col("k").fill_null(0.0)).alias("value")).select(TSC + ["value"]))
        P.coef["acrev_inv"] = (bins_dom.join(P.var["INVTRAN_AC"].rename({"r": "rr", "rr": "r"}), on=TSC, how="semi")
                               .join(rev, on=["r", "rr", "tscbin"], how="left")
                               .with_columns(pl.col("k").fill_null(0.0).alias("value")).select(TSC + ["value"]))
        P.coef["acrev_bins"] = _signed(bins_dom, TSC, -1.0)
        P.con["eq_INVTRAN_AC"] = rinv_ac
        P.coef["invac_tran"] = _signed(rinv_ac.with_columns(pl.lit("ac").alias("trtype")), ROUTE_IDX, 1.0)
        P.coef["invac_bins"] = _signed(P.var["INVTRAN_AC"], TSC, -1.0)
        P.con["eq_TRAN_CAPEX_BINS"] = bins_dom
        P.coef["capexbin_const"] = _on_domain(bins_dom, binw, ["r", "rr", "tscbin"])
        P.coef["capexbin_bins"] = _signed(bins_dom, TSC, -1.0)
        exog = case["invtran_exog"].join(inv, on=ROUTE_IDX, how="semi")
        P.con["eq_invtran_exog"] = exog.select(ROUTE_IDX)
        P.coef["invexog_const"] = exog.with_columns((-pl.col("value")).alias("value"))
        P.coef["invexog_inv"] = _signed(exog, ROUTE_IDX, 1.0)
        fut = case["trancap_fut_possible"]
        near = case.scalar("firstyear_trans_nearterm")
        fut_cum = (fut.rename({"t": "tt"}).join(tmodel, how="cross").filter(pl.col("tt") <= pl.col("t")).group_by(ROUTE_IDX).agg(pl.col("value").sum()))
        pres_dom = inv.filter(pl.col("t") < near).join(fut_cum.filter(pl.col("value") != 0.0), on=ROUTE_IDX, how="semi")
        past_inv = (case["state_INVTRAN"].join(tfix_tt, on="tt", how="semi")
                    .join(rinv_tfix, on=["r", "rr", "trtype", "tt"], how="semi")
                    .join(tmodel, how="cross").filter(pl.col("tt") <= pl.col("t")).group_by(ROUTE_IDX).agg(pl.col("value").sum()))
        P.con["eq_prescribed_transmission"] = pres_dom
        P.coef["prestran_const"] = _add(_on_domain(pres_dom, fut_cum, ROUTE_IDX), past_inv, ROUTE_IDX, sign=-1.0)
        P.coef["prestran_inv"] = _signed(pres_dom, ROUTE_IDX, -1.0)

    if "INV_POI" in P.var:
        poi_dom = P.var["INV_POI"]
        past_poi = (case["state_INV_POI"].join(tfix_tt, on="tt", how="semi").join(tmodel, how="cross")
                    .filter(pl.col("tt") <= pl.col("t")).group_by(["r", "t"]).agg(pl.col("value").sum()))
        const = _add(_on_domain(poi_dom, case["poi_cap_init"], ["r"]), past_poi, ["r", "t"])
        lcc_past = (case["state_INVTRAN"].filter(pl.col("trtype") == "lcc").join(case["routes_inv_tfix"], on=["r", "rr", "trtype", "tt"], how="semi")
                    .join(rinv_all.filter(pl.col("trtype") == "lcc").select(["r", "rr", "t"]), on=["r", "rr"], how="inner")
                    .filter(pl.col("tt") <= pl.col("t")).join(tmodel, on="t", how="semi").group_by(["r", "t"]).agg(pl.col("value").sum()))
        P.coef["poi_const"] = _add(const, lcc_past, ["r", "t"], sign=-1.0)
        P.con["eq_POI_cap"] = poi_dom
        P.coef["poi_inv"] = _signed(poi_dom, ["r", "t"], 1.0)
        cap_rows = _not_in(valcap, "i", S["spur_techs"]).join(case["ilr"].rename({"value": "ilr"}), on="i", how="left")
        if cap_rows.filter(pl.col("ilr").is_null() | (pl.col("ilr") == 0.0)).height:
            raise ValueError("ilr is missing for a technology in valcap (GAMS would divide by zero in eq_POI_cap)")
        P.coef["poi_cap"] = cap_rows.with_columns((-(1.0 / pl.col("ilr"))).alias("value")).select(V4 + ["value"])
        if "CAP_SPUR" in P.var:
            P.coef["poi_spur"] = (case["x_r"].join(case["xfeas"], on="x", how="semi").join(tmodel, how="cross")
                                  .select(["r", "x", "t"]).with_columns(pl.lit(-1.0).alias("value")))
        if "INVTRAN" in P.var:
            lcc_now = P.var["INVTRAN"].filter(pl.col("trtype") == "lcc")
            lcc_unfixed_past = (lcc_now.select(["r", "rr", "trtype"]).join(tfix_tt, how="cross")
                                .join(case["routes_inv_tfix"], on=["r", "rr", "trtype", "tt"], how="anti")
                                .rename({"tt": "t"}).select(ROUTE_IDX))
            P.var["INVTRAN"] = pl.concat([P.var["INVTRAN"], lcc_unfixed_past]).unique()
            lcc_rows = case["routes_inv"].filter(pl.col("trtype") == "lcc").join(tmodel, on="t", how="semi").select(["r", "rr", "trtype", "t"])
            lcc_cols = pl.concat([lcc_now, lcc_unfixed_past]).rename({"t": "tt"})
            P.coef["poi_lcc"] = (lcc_cols.join(lcc_rows, on=["r", "rr", "trtype"], how="inner").filter(pl.col("tt") <= pl.col("t"))
                                 .with_columns(pl.lit(-1.0).alias("value")).select(["r", "rr", "trtype", "tt", "t", "value"]))
        else:
            P.coef["poi_lcc"] = (_signed(rinv_all.head(0), ROUTE_IDX, -1.0).rename({"t": "tt"})
                                 .with_columns(pl.col("tt").alias("t")).select(["r", "rr", "trtype", "tt", "t", "value"]))

    if "CAPTRAN_GRP" in P.var:
        GRP = ["transgrp", "transgrpp", "t"]
        grp_dom = P.var["CAPTRAN_GRP"]
        derate_g = case.scalar("Sw_TransGroupDerate")
        init_g = case["trancap_init_transgroup"].filter(pl.col("trtype") == "ac").select(["transgrp", "transgrpp", "value"])
        past_g = (case["state_INVTRAN"].filter(pl.col("trtype") == "ac").join(tfix_tt, on="tt", how="semi")
                  .join(case["routes_inv_tfix"].filter(pl.col("trtype") == "ac").select(["r", "rr", "tt"]), on=["r", "rr", "tt"], how="semi")
                  .join(rtg, on=["r", "rr"], how="inner").join(tmodel, how="cross").filter(pl.col("tt") <= pl.col("t"))
                  .with_columns((pl.col("value") * (1.0 - derate_g)).alias("value")).group_by(GRP).agg(pl.col("value").sum()))
        const = _add(_on_domain(grp_dom, init_g, ["transgrp", "transgrpp"]), past_g, GRP)
        P.con["eq_CAPTRAN_GRP"] = grp_dom
        P.coef["grp_const"] = const.with_columns((-pl.col("value")).alias("value"))
        P.coef["grp_cap"] = _signed(grp_dom, GRP, 1.0)
        P.coef["grp_inv"] = ((P.var["INVTRAN"].join(tmodel, on="t", how="semi").filter(pl.col("trtype") == "ac").join(rtg, on=["r", "rr"], how="inner")
                              .with_columns(pl.lit(-(1.0 - derate_g)).alias("value")).select(["transgrp", "transgrpp"] + ROUTE_IDX + ["value"]))
                             if "INVTRAN" in P.var else _signed(rinv_all.head(0).with_columns(pl.lit("").alias("transgrp"), pl.lit("").alias("transgrpp")), ["transgrp", "transgrpp"] + ROUTE_IDX, 1.0))
        lim_dom = grp_dom.join(h, how="cross").select(["transgrp", "transgrpp", "h", "t"])
        delta_ht = _on_domain(h.join(tmodel, how="cross"), case["trans_cap_delta"], ["h", "t"])
        P.con["eq_transgrp_limit_energy"] = lim_dom
        P.coef["grplim_cap"] = (lim_dom.join(delta_ht.rename({"value": "d"}), on=["h", "t"], how="inner")
                                .with_columns((1.0 + pl.col("d")).alias("value")).select(["transgrp", "transgrpp", "h", "t", "value"]))
        P.coef["grplim_flow"] = (P.var["FLOW"].filter(pl.col("trtype") == "ac").join(rtg, on=["r", "rr"], how="inner")
                                 .with_columns(pl.lit(-1.0).alias("value")).select(["transgrp", "transgrpp"] + FLOW_IDX + ["value"]))

    if int(case.scalar("Sw_PRM_NetImportLimit")):
        rtr = case["routes_transreg"]
        flow_prm = P.var["FLOW"].join(routes_prm, on=["r", "rr"], how="semi").join(_in(h, "h", h_stress), on="h", how="semi")
        imports = (flow_prm.join(rtr.rename({"transreg": "transregg", "transregg": "transreg"}), on=["r", "rr"], how="inner")
                   .join(case["tranloss"].rename({"value": "loss"}), on=R3, how="left")
                   .with_columns((-(1.0 - pl.col("loss").fill_null(0.0))).alias("value")).select(["transreg"] + FLOW_IDX + ["value"]))
        exports = (flow_prm.join(rtr, on=["r", "rr"], how="inner").with_columns(pl.lit(1.0).alias("value"))
                   .select(["transreg"] + FLOW_IDX + ["value"]))
        firm_flow = pl.concat([imports, exports])
        firm_rows = firm_flow.select(["transreg", "h", "t"]).unique()
        lim = case["firm_import_limit"].rename({"value": "lim"})
        peak = case["peakload_transreg"].rename({"value": "peak"})
        P.con["eq_firm_transfer_limit"] = firm_rows
        P.coef["firm_const"] = (firm_rows.join(lim, on=["transreg", "t"], how="left").join(peak, on=["transreg", "t"], how="left")
                                .with_columns((pl.col("lim").fill_null(0.0) * pl.col("peak").fill_null(0.0)).alias("value"))
                                .select(["transreg", "h", "t", "value"]))
        P.coef["firm_flow"] = firm_flow

    tim_types = int(case.scalar("Sw_TransInvMaxTypes"))
    if tim_types and "INVTRAN" in P.var:
        tim = case["trans_inv_max"].join(tmodel, on="t", how="semi")
        prev = case["tprev"].join(tmodel, on="t", how="semi")
        tim_rows = tim.join(prev, on="t", how="inner").with_columns(
            ((pl.col("value") * 1e6) * (pl.col("t") - pl.col("tt")).cast(pl.Float64)).alias("value")).select(["t", "value"])
        P.con["eq_transmission_investment_max"] = tim_rows.select("t")
        P.coef["tim_const"] = tim_rows
        dist = case["distance"].rename({"value": "d"})
        inv = P.var["INVTRAN"].join(tmodel, on="t", how="semi")
        fwd_rows = inv.join(dist, on=R3, how="left").with_columns((-(0.5 * pl.col("d").fill_null(0.0))).alias("value")).select(ROUTE_IDX + ["value"])
        rev_rows = (inv.join(dist, on=R3, how="left").with_columns((-(0.5 * pl.col("d").fill_null(0.0))).alias("value"))
                    .select([pl.col("rr").alias("r"), pl.col("r").alias("rr"), "trtype", "t", "value"]))
        P.coef["tim_inv"] = pl.concat([fwd_rows, rev_rows]).group_by(ROUTE_IDX).agg(pl.col("value").sum()).select(ROUTE_IDX + ["value"])
        if tim_types in (2, 3):
            dr = case["distance_reinforcement"].rename({"value": "dr"})
            ds = case["distance_spur"].rename({"value": "ds"})
            rsc_rows = (P.var["INV_RSC"].join(dr, on=["i", "r", "rscbin"], how="left").join(ds, on=["i", "r", "rscbin"], how="left")
                        .with_columns((-(pl.col("dr").fill_null(0.0) + (pl.col("ds").fill_null(0.0) if tim_types == 3 else 0.0))).alias("value"))
                        .select(RSC_IDX + ["value"]))
            P.coef["tim_rsc"] = rsc_rows
        else:
            P.coef["tim_rsc"] = pl.DataFrame(schema={"t": pl.Int64, "i": pl.Utf8, "v": pl.Utf8, "r": pl.Utf8, "rscbin": pl.Utf8, "value": pl.Float64})

    tmax = case.members("trtypemax")
    each = case.scalar("Sw_TransCapMaxEachType")
    if each and tmax:
        dom = _in(P.var["CAPTRAN_ENERGY"], "trtype", tmax)
        P.con["eq_CAPTRAN_max"] = dom
        P.coef["ctmax_const"] = dom.with_columns(pl.lit(each * 1000.0).alias("value"))
        P.coef["ctmax_cap"] = _signed(dom, ROUTE_IDX, -1.0)
    allt = case.scalar("Sw_TransCapMaxAllTypes")
    if allt and tmax:
        dom = _in(P.var["CAPTRAN_ENERGY"], "trtype", tmax)
        rows = dom.select(["r", "rr", "t"]).unique()
        P.con["eq_CAPTRAN_max_total"] = rows
        P.coef["ctmaxt_const"] = rows.with_columns(pl.lit(allt * 1000.0).alias("value"))
        P.coef["ctmaxt_cap"] = _signed(dom, ROUTE_IDX, -1.0)
    if not int(case.scalar("Sw_OffshoreBackflow")):
        off = case.members("offshore")
        dom = _in(_in(P.var["FLOW"], "r", S["land"]), "rr", off)
        P.con["eq_offshore_no_backflow"] = dom.select(["r", "rr", "trtype", "h", "t"])
        P.coef["offbf_flow"] = _signed(dom, FLOW_IDX, 1.0)

    for name, msg in (("Sw_BankBorrowCap", "eq_bankborrowcap"), ("Sw_NoFossilOffsetCDR", "eq_cdr_cap"), ("Sw_GenMandate", "eq_national_gen"),
                      ("Sw_GrowthAbsCon", "absolute growth limits")):
        if int(case.scalar(name)):
            raise NotImplementedError(f"{name}=1 ({msg}) is not ported")
    if case["emit_rate_con"].height:
        raise NotImplementedError("emit_rate_con rows exist (eq_emit_rate_limit) but are not ported")
    emit_co2 = P.var["EMIT"].filter((pl.col("etype") == "process") & (pl.col("e") == "co2"))
    if int(case.scalar("Sw_RGGI")):
        rg = _in(emit_co2, "r", S["rggi_r"]).filter(pl.col("t") >= case.scalar("RGGI_start_yr"))
        rows = rg.select("t").unique()
        P.con["eq_RGGI_cap"] = rows
        P.coef["rggi_const"] = _on_domain(rows, case["rggi_cap"], ["t"])
        P.coef["rggi_emit"] = _signed(rg, ["etype", "e", "r", "t"], -1.0)
    if int(case.scalar("Sw_StateCap")):
        sc_states = case["co2_state_cap"].select("st").unique()
        sc_rows = (sc_states.join(tmodel, how="cross").filter(pl.col("t") >= case.scalar("state_cap_start_yr")))
        emit_st = emit_co2.join(case["r_st"], on="r", how="inner").join(sc_rows, on=["st", "t"], how="semi")
        cap_on = int(case.scalar("Sw_AnnualCap")) > 0
        emit_cap_t = case["emit_cap"].filter(pl.col("eall").is_in(["co2", "co2e"])).select("t").unique()
        flow_rows = (P.var["FLOW"].join(_in(h, "h", h_rep), on="h", how="semi")
                     .join(case["r_st"].rename({"st": "st_from"}), on="r", how="left")
                     .join(case["r_st"].rename({"r": "rr"}), on="rr", how="inner").join(sc_rows, on=["st", "t"], how="semi")
                     .filter(pl.col("st_from").is_null() | (pl.col("st_from") != pl.col("st"))))
        if cap_on:
            flow_rows = flow_rows.join(emit_cap_t, on="t", how="semi")
        rate = (case["state_co2_emit_rate_r"].rename({"value": "rate"})
                .join(case["tprev"].join(tmodel, on="t", how="semi"), on="tt", how="inner").select(["r", "t", "rate"]))
        stcap_flow = (flow_rows.join(hours.rename({"value": "hrs"}), on="h", how="inner").join(rate, on=["r", "t"], how="left")
                      .with_columns((-(pl.col("hrs") * pl.col("rate").fill_null(0.0))).alias("value"))
                      .select(["st"] + FLOW_IDX + ["value"]).filter(pl.col("value") != 0.0))
        rows = pl.concat([emit_st.select(["st", "t"]), stcap_flow.select(["st", "t"])]).unique()
        P.con["eq_state_cap"] = rows
        P.coef["stcap_const"] = _on_domain(rows, case["co2_state_cap"], ["st", "t"])
        P.coef["stcap_emit"] = _signed(emit_st, ["st", "etype", "e", "r", "t"], -1.0)
        P.coef["stcap_flow"] = stcap_flow
    if int(case.scalar("Sw_CSAPR")):
        nox = (case["emit_rate"].filter((pl.col("etype") == "process") & (pl.col("e") == "nox")).select(V4 + [pl.col("value").alias("er")])
               .join(valgen, on=V4, how="semi"))
        hw = case["h_weight_csapr"].rename({"value": "hw"})
        gen_nox = (nox.join(hours_rep.rename({"value": "hrs"}), how="cross").join(hw, on="h", how="inner")
                   .join(case["r_st"], on="r", how="inner")
                   .with_columns((-((pl.col("hw") * pl.col("hrs")) * pl.col("er"))).alias("value")))
        start = case.scalar("csapr_startyr")
        ccap = case["csapr_cap"].join(tmodel, on="t", how="semi").filter(pl.col("t") >= start)
        grp = case["csapr_group_st"]
        if grp.height:
            budget = (ccap.filter(pl.col("csapr_cat") == "budget").join(grp, on="st", how="inner").join(case["stfeas"], on="st", how="semi")
                      .group_by(["csapr_group", "t"]).agg(pl.col("value").sum()))
            csb_gen = gen_nox.join(grp, on="st", how="inner").select(["csapr_group"] + GEN_IDX + ["value"])
            rows = grp.select("csapr_group").unique().join(tmodel, how="cross").filter(pl.col("t") >= start)
            rows = rows.join(csb_gen.select(["csapr_group", "t"]).unique(), on=["csapr_group", "t"], how="semi")
            P.con["eq_CSAPR_Budget"] = rows
            P.coef["csb_const"] = _on_domain(rows, budget, ["csapr_group", "t"])
            P.coef["csb_gen"] = csb_gen
        assure = ccap.filter(pl.col("csapr_cat") == "assurance").join(case["stfeas"], on="st", how="semi").select(["st", "t", "value"])
        csa_gen = gen_nox.join(assure.select(["st", "t"]), on=["st", "t"], how="semi").select(["st"] + GEN_IDX + ["value"])
        rows = assure.join(csa_gen.select(["st", "t"]).unique(), on=["st", "t"], how="semi")
        P.con["eq_CSAPR_Assurance"] = rows.select(["st", "t"])
        P.coef["csa_const"] = rows
        P.coef["csa_gen"] = csa_gen

    if int(case.scalar("Sw_StateRPS")):
        fy = case.scalar("firstyear_RPS")
        dl = case.scalar("distloss")
        rec_t = tmodel.join(case["tfirst"], on="t", how="anti").filter(pl.col("t") >= fy)
        stfeas = case["stfeas"]
        st_or_vol = pl.concat([stfeas, pl.DataFrame({"st": ["voluntary"]})]).unique()
        recmap = case["recmap"].join(rec_t, on="t", how="semi")
        rectech = case["rectech"].join(rec_t, on="t", how="semi")
        recperc = case["recperc"].join(rec_t, on="t", how="semi")
        unbundled = {"rps_bundled", "ces_bundled"}
        RECS5 = ["rpscat", "i", "st", "ast", "t"]
        recs_dom = (recmap.join(stfeas, on="st", how="semi").join(st_or_vol.rename({"st": "ast"}), on="ast", how="semi")
                    .select(RECS5))
        recs_dom = recs_dom.filter(~(pl.col("rpscat").is_in(list(unbundled)) & (pl.col("st") == pl.col("ast"))))
        P.var["RECS"] = recs_dom
        RG = ["rpscat", "i", "st", "t"]
        gen_dom = (rectech.filter(~pl.col("rpscat").is_in(list(unbundled))).join(stfeas, on="st", how="semi").select(RG))
        mult = case["rpstechmult"].rename({"value": "mult"})
        recgen_gen = (gen_dom.join(P.var["GEN"], on=["i", "t"], how="inner").join(case["r_st"], on=["r", "st"], how="semi")
                      .join(hours_rep.rename({"value": "hrs"}), on="h", how="inner").join(mult, on=["rpscat", "i", "st"], how="left")
                      .with_columns((pl.col("mult").fill_null(0.0) * pl.col("hrs")).alias("value")).select(RG + ["v", "r", "h", "value"]))
        own = recs_dom.join(gen_dom, on=RG, how="semi")
        rb = (recs_dom.filter((pl.col("rpscat") == "rps_bundled") & (pl.col("st") != pl.col("ast"))).join(stfeas.rename({"st": "ast"}), on="ast", how="semi")
              .with_columns(pl.lit("rps_all").alias("rpscat_row")))
        cb = (recs_dom.filter((pl.col("rpscat") == "ces_bundled") & (pl.col("st") != pl.col("ast"))).join(stfeas.rename({"st": "ast"}), on="ast", how="semi")
              .with_columns(pl.lit("ces").alias("rpscat_row")))
        bundled_rows = pl.concat([rb, cb]).join(gen_dom.rename({"rpscat": "rpscat_row"}), on=["rpscat_row", "i", "st", "t"], how="semi")
        recgen_recs = pl.concat([own.with_columns(pl.col("rpscat").alias("rpscat_row")), bundled_rows]).with_columns(pl.lit(-1.0).alias("value"))
        recgen_recs = recgen_recs.select([pl.col("rpscat_row").alias("rpscat"), "i", "st", "t", pl.col("rpscat").alias("rpscat_var"), "ast", "value"])
        P.con["eq_REC_Generation"] = gen_dom
        P.coef["recgen_gen"] = recgen_gen
        P.coef["recgen_recs"] = recgen_recs.rename({"rpscat": "rpscat", "rpscat_var": "rpscat_v"})
        style = case["recstyle"].rename({"value": "style"})
        ce = case["can_exports_h"].rename({"value": "ce"}) if int(case.scalar("Sw_Canada")) == 1 else case["can_exports_h"].head(0).rename({"value": "ce"})
        distpv_gen = _in(P.var["GEN"], "i", S["distpv"])

        def load_terms(rows, region_map, ces_exports):
            rr = rows.join(style, on=["st", "rpscat"], how="left").with_columns(pl.col("style").fill_null(0.0))
            reg = rr.join(region_map, on="st", how="inner").join(hours_rep.rename({"value": "hrs"}), how="cross")
            f01 = pl.when(pl.col("style") == 0.0).then((1.0 - dl) * pl.col("hrs")).when(pl.col("style") == 1.0).then(pl.col("hrs")).otherwise(None)
            load = (reg.filter(pl.col("style") < 2.0).with_columns((-(f01 * pl.col("mult"))).alias("value"))
                    .select(RQ + ["r", "h", "value"]))
            gen_d = (reg.filter(pl.col("style") < 2.0).join(distpv_gen, on=["r", "h", "t"], how="inner")
                     .with_columns((f01 * pl.col("mult")).alias("value")).select(RQ + ["i", "v", "r", "h", "value"]))
            gen2 = (reg.filter(pl.col("style") == 2.0).join(_not_in(P.var["GEN"], "i", S["storage_standalone"]), on=["r", "h", "t"], how="inner")
                    .with_columns((-((pl.when(pl.col("i").is_in(list(S["distpv"]))).then(1.0 + (-dl)).otherwise(1.0) * pl.col("hrs")) * pl.col("mult"))).alias("value"))
                    .select(RQ + ["i", "v", "r", "h", "value"]))
            c = (reg.join(ce, on=["r", "h", "t"], how="inner")
                 .with_columns(pl.when(pl.col("style") == 0.0).then(((pl.col("ce") * (1.0 - dl)) * pl.col("hrs")) * pl.col("mult"))
                               .when(pl.col("style") == 1.0).then((pl.col("ce") * pl.col("hrs")) * pl.col("mult"))
                               .otherwise(pl.when(pl.col("rpscat") == "ces").then((pl.col("ce") * pl.col("hrs")) * pl.col("mult")).otherwise(0.0) if ces_exports else 0.0).alias("value"))
                 .group_by(RQ).agg(pl.col("value").sum()))
            return c, load, pl.concat([gen_d, gen2])

        RQ = ["rpscat", "st", "t"]
        req_dom = (recperc.filter(~pl.col("rpscat").is_in(list(unbundled))).join(st_or_vol, on="st", how="semi"))
        req_rows = req_dom.select(RQ)
        rr_map = case["r_st_rps"]
        const, load_c, gen_c = load_terms(req_dom.rename({"value": "mult"}), rr_map, True)
        exp_c = (req_rows.filter(pl.col("rpscat") == "ces").join(case["r_st"], on="st", how="inner").join(hours_rep.rename({"value": "hrs"}), how="cross")
                 .join(ce, on=["r", "h", "t"], how="inner").with_columns((-(pl.col("ce") * pl.col("hrs"))).alias("value")).group_by(RQ).agg(pl.col("value").sum()))
        P.con["eq_REC_Requirement"] = req_rows
        P.coef["recreq_const"] = _add(_on_domain(req_rows, const, RQ), exp_c, RQ)
        P.coef["recreq_load"] = load_c
        P.coef["recreq_gen"] = gen_c
        def into(rows, sign, strict):
            base = recs_dom.join(stfeas, on="st", how="semi").with_columns(pl.col("ast").alias("st_row"))
            if strict:
                base = base.filter(pl.col("st") != pl.col("ast"))
            return base.join(rows.rename({"st": "st_row"}).select(["rpscat", "st_row", "t"]), on=["rpscat", "st_row", "t"], how="semi").with_columns(pl.lit(float(sign)).alias("value"))

        def outof(rows, sign, allow_voluntary):
            dest = st_or_vol if allow_voluntary else stfeas
            base = (recs_dom.filter(pl.col("st") != pl.col("ast")).join(dest.rename({"st": "ast"}), on="ast", how="semi")
                    .with_columns(pl.col("st").alias("st_row")))
            return base.join(rows.rename({"st": "st_row"}).select(["rpscat", "st_row", "t"]), on=["rpscat", "st_row", "t"], how="semi").with_columns(pl.lit(float(sign)).alias("value"))

        imp = into(req_rows, 1.0, False)
        exp = outof(req_rows, -1.0, False)

        def bundled_terms(rows_cat, cat_b, sign, direction):
            base = recs_dom.filter((pl.col("rpscat") == cat_b) & (pl.col("st") != pl.col("ast"))).join(stfeas.rename({"st": "ast"}), on="ast", how="semi")
            if direction == "in":
                base = base.join(stfeas, on="st", how="semi")
                keyed = base.with_columns(pl.col("ast").alias("st_row"))
            else:
                keyed = base.with_columns(pl.col("st").alias("st_row"))
            keyed = keyed.join(rows_cat.rename({"st": "st_row"}).select(["st_row", "t"]), on=["st_row", "t"], how="semi")
            return keyed.with_columns(pl.lit(float(sign)).alias("value"))

        def recs_coef(parts, row_cat_col):
            out = []
            for p, rowcat in parts:
                out.append(p.select([pl.lit(rowcat).alias("rpscat_row") if rowcat else pl.col("rpscat").alias("rpscat_row"),
                                     pl.col("st_row") if "st_row" in p.columns else pl.col("st").alias("st_row"), "t",
                                     pl.col("rpscat").alias("rpscat_v"), "i", "st", "ast", "value"]))
            return pl.concat(out)

        req_all = req_rows.filter(pl.col("rpscat") == "rps_all")
        req_ces = req_rows.filter(pl.col("rpscat") == "ces")
        rq_parts = [(imp, None), (exp, None),
                    (bundled_terms(req_all, "rps_bundled", 1.0, "in"), "rps_all"), (bundled_terms(req_all, "rps_bundled", -1.0, "out"), "rps_all"),
                    (bundled_terms(req_ces, "ces_bundled", 1.0, "in"), "ces"), (bundled_terms(req_ces, "ces_bundled", -1.0, "out"), "ces")]
        P.coef["recreq_recs"] = recs_coef(rq_parts, None).rename({"rpscat_row": "rpscat", "st_row": "st_r"}).select(
            ["rpscat", pl.col("st_r").alias("st"), "t", "rpscat_v", "i", pl.col("st").alias("st_v"), "ast", "value"])
        acp_rows = req_rows.join(case["acp_disallowed"].select(["st", "rpscat"]), on=["st", "rpscat"], how="anti")
        P.coef["recreq_acp"] = _signed(acp_rows, RQ, 1.0)
        BL = ["rpscat", "st", "ast", "t"]
        bl_dom = (recmap.filter(pl.col("rpscat").is_in(list(unbundled)) & (pl.col("st") != pl.col("ast"))).join(stfeas, on="st", how="semi")
                  .join(stfeas.rename({"st": "ast"}), on="ast", how="semi").select(BL).unique())
        bl_flow = (bl_dom.join(case["r_st"], on="st", how="inner").join(case["r_st"].rename({"r": "rr", "st": "ast"}), on="ast", how="inner")
                   .join(P.var["FLOW"].join(_in(h, "h", h_rep), on="h", how="semi"), on=["r", "rr", "t"], how="inner")
                   .join(hours_rep.rename({"value": "hrs"}), on="h", how="inner").with_columns(pl.col("hrs").alias("value"))
                   .select(BL + ["r", "rr", "h", "trtype", "value"]))
        bl_recs = recs_dom.join(bl_dom, on=BL, how="semi").with_columns(pl.lit(-1.0).alias("value")).select(BL + ["i", "value"])
        P.con["eq_REC_BundleLimit"] = bl_dom
        P.coef["recbl_flow"] = bl_flow
        P.coef["recbl_recs"] = bl_recs
        unb = (case["rec_unbundled_limit"].join(rec_t, on="t", how="semi").join(case["st_unbundled_limit"], on=["rpscat", "st"], how="semi")
               .join(stfeas, on="st", how="semi").filter(pl.col("rpscat").is_in(["rps_all", "ces"])))
        unb = unb.join(recperc.rename({"value": "rp"}), on=RQ, how="left").with_columns((pl.col("value") * pl.col("rp").fill_null(0.0)).alias("mult"))
        unb_rows = unb.select(RQ)
        const, load_c, gen_c = load_terms(unb.select(RQ + ["mult"]).with_columns(pl.lit(0.0).alias("style_override")).drop("style_override"), case["r_st"], False)
        P.con["eq_REC_unbundledLimit"] = unb_rows
        P.coef["recunb_const"] = _on_domain(unb_rows, const, RQ).with_columns((-pl.col("value")).alias("value"))
        P.coef["recunb_load"] = load_c.with_columns((-pl.col("value")).alias("value"))
        P.coef["recunb_gen"] = gen_c.with_columns((-pl.col("value")).alias("value"))
        unb_all = unb_rows.filter(pl.col("rpscat") == "rps_all")
        unb_ces = unb_rows.filter(pl.col("rpscat") == "ces")
        imp_u = into(unb_rows, -1.0, True)
        ub_parts = [(imp_u, None), (bundled_terms(unb_all, "rps_bundled", 1.0, "in"), "rps_all"), (bundled_terms(unb_ces, "ces_bundled", 1.0, "in"), "ces")]
        P.coef["recunb_recs"] = recs_coef(ub_parts, None).select(
            [pl.col("rpscat_row").alias("rpscat"), pl.col("st_row").alias("st"), "t", "rpscat_v", "i", pl.col("st").alias("st_v"), "ast", "value"])
        oos = (recperc.filter(~pl.col("rpscat").is_in(list(unbundled))).join(stfeas, on="st", how="semi")
               .join(case["rps_oosfrac"].rename({"value": "oos"}), on="st", how="inner")
               .with_columns((pl.col("oos") * pl.col("value")).alias("mult")))
        oos_rows = oos.select(RQ)
        const, load_c, gen_c = load_terms(oos.select(RQ + ["mult"]), case["r_st"], False)
        P.con["eq_REC_ooslim"] = oos_rows
        P.coef["recoos_const"] = _on_domain(oos_rows, const, RQ).with_columns((-pl.col("value")).alias("value"))
        P.coef["recoos_load"] = load_c.with_columns((-pl.col("value")).alias("value"))
        P.coef["recoos_gen"] = gen_c.with_columns((-pl.col("value")).alias("value"))
        oos_all = oos_rows.filter(pl.col("rpscat") == "rps_all")
        oos_ces = oos_rows.filter(pl.col("rpscat") == "ces")
        imp_o = into(oos_rows, -1.0, True)
        oo_parts = [(imp_o, None), (bundled_terms(oos_all, "rps_bundled", -1.0, "in"), "rps_all"), (bundled_terms(oos_ces, "ces_bundled", -1.0, "in"), "ces")]
        P.coef["recoos_recs"] = recs_coef(oo_parts, None).select(
            [pl.col("rpscat_row").alias("rpscat"), pl.col("st_row").alias("st"), "t", "rpscat_v", "i", pl.col("st").alias("st_v"), "ast", "value"])
        lau_rows = (case["recstates"].join(rec_t, on="t", how="semi").join(stfeas, on="st", how="semi")
                    .filter(~pl.col("rpscat").is_in(list(unbundled))).select(RQ))
        lau_gen = (lau_rows.join(rectech, on=RQ, how="inner").join(P.var["GEN"], on=["i", "t"], how="inner")
                   .join(case["r_st"], on=["r", "st"], how="semi").join(hours_rep.rename({"value": "hrs"}), on="h", how="inner")
                   .with_columns(pl.col("hrs").alias("value")).select(RQ + ["i", "v", "r", "h", "value"]))
        lau_acp = _signed(lau_rows.join(case["acp_disallowed"].select(["st", "rpscat"]), on=["st", "rpscat"], how="anti"), RQ, -10.0)
        exp_l = outof(lau_rows, -1.0, True)
        lau_all = lau_rows.filter(pl.col("rpscat") == "rps_all")
        lau_ces = lau_rows.filter(pl.col("rpscat") == "ces")
        la_parts = [(exp_l, None), (bundled_terms(lau_all, "rps_bundled", -1.0, "out"), "rps_all"), (bundled_terms(lau_ces, "ces_bundled", -1.0, "out"), "ces")]
        P.con["eq_REC_launder"] = lau_rows
        P.coef["reclau_gen"] = lau_gen
        P.coef["reclau_acp"] = lau_acp
        P.coef["reclau_recs"] = recs_coef(la_parts, None).select(
            [pl.col("rpscat_row").alias("rpscat"), pl.col("st_row").alias("st"), "t", "rpscat_v", "i", pl.col("st").alias("st_v"), "ast", "value"])
        acp_cols = pl.concat([acp_rows, lau_rows.join(case["acp_disallowed"].select(["st", "rpscat"]), on=["st", "rpscat"], how="anti"),
                              case["slice_objop_ACP_PURCHASES"].select(RQ)]).unique()
        P.var["ACP_PURCHASES"] = acp_cols
        ofs_req = (case["offshore_cap_req"].join(tmodel, on="t", how="semi").join(stfeas, on="st", how="semi").filter(pl.col("t") >= fy))
        ofs_cap = _in(valcap, "i", S["ofswind"]).join(case["r_st"], on="r", how="inner").select(["st", "t"]).unique()
        ofs_rows = ofs_req.join(ofs_cap, on=["st", "t"], how="semi")
        if ofs_rows.height:
            exog = (_in(case["m_capacity_exog"], "i", S["ofswind"]).join(case["r_st"], on="r", how="inner").group_by(["st", "t"]).agg(pl.col("value").sum()))
            cond = case["inv_cond"].join(_in(valcap, "i", S["ofswind"]).select(V4), on=V4, how="semi").join(case["r_st"], on="r", how="inner")
            cur_inv = (cond.join(tmodel_tt, on="tt", how="semi").join(P.var["INV"].rename({"t": "tt"}), on=["i", "v", "r", "tt"], how="semi")
                       .select(["st", "t", "i", "v", "r", "tt"]).with_columns(pl.lit(1.0).alias("value")))
            past = (cond.join(tfix_tt, on="tt", how="semi").join(case["state_INV"], on=["i", "v", "r", "tt"], how="inner").group_by(["st", "t"]).agg(pl.col("value").sum()))
            if "INV_REFURB" in P.var:
                cur_ref = (cond.join(tmodel_tt, on="tt", how="semi").join(P.var["INV_REFURB"].rename({"t": "tt"}), on=["i", "v", "r", "tt"], how="semi")
                           .select(["st", "t", "i", "v", "r", "tt"]).with_columns(pl.lit(1.0).alias("value")))
                past_ref = (cond.join(tfix_tt, on="tt", how="semi").join(case["state_INV_REFURB"], on=["i", "v", "r", "tt"], how="inner")
                            .join(_in(valcap.select("i").unique(), "i", refurb), on="i", how="semi").group_by(["st", "t"]).agg(pl.col("value").sum()))
            else:
                cur_ref = cur_inv.head(0)
                past_ref = past.head(0)
            const = _add(_add(_on_domain(ofs_rows.select(["st", "t"]), exog, ["st", "t"]), past, ["st", "t"]), past_ref, ["st", "t"])
            cur_inv = cur_inv.join(ofs_rows.select(["st", "t"]), on=["st", "t"], how="semi")
            cur_ref = cur_ref.join(ofs_rows.select(["st", "t"]), on=["st", "t"], how="semi")
            with_vars = pl.concat([cur_inv.select(["st", "t"]), cur_ref.select(["st", "t"])]).unique()
            P.con["eq_RPS_OFSWind"] = ofs_rows.select(["st", "t"]).join(with_vars, on=["st", "t"], how="semi")
            P.coef["ofs_const"] = _add(const, ofs_rows.select(["st", "t", "value"]), ["st", "t"], sign=-1.0).join(with_vars, on=["st", "t"], how="semi")
            P.coef["ofs_inv"] = cur_inv
            P.coef["ofs_refurb"] = cur_ref

    if int(case.scalar("Sw_GrowthPenalties")):
        year = int(tmodel["t"][0])
        prev_years = case["tprev"].join(tmodel, on="t", how="semi")["tt"].to_list()
        gap = float(year - (int(prev_years[0]) if prev_years else 0))
        if case.scalar("model_builds_start_yr") <= year <= case.scalar("Sw_GrowthPenLastYear"):
            gbin = case["gbin"]
            IST = ["i", "st", "t"]
            inv_st = valinv.join(case["r_st"], on="r", how="inner").join(case["stfeas"], on="st", how="semi")
            grl_rows = inv_st.select(IST).unique()
            gbl_rows = gbin.join(case["valinv_tg"].join(tmodel, on="t", how="semi").join(case["stfeas"], on="st", how="semi"), how="cross")
            gbl_rows = gbl_rows.select(["gbin", "st", "tg", "t"])
            tg_cols = gbl_rows.select(["st", "tg", "t"]).unique().join(case["tg_i"], on="tg", how="inner").select(IST).unique()
            P.var["GROWTH_BIN"] = pl.concat([gbin.join(grl_rows, how="cross"), gbin.join(tg_cols, how="cross")]).unique().select(["gbin"] + IST)
            P.con["eq_growthlimit_relative"] = grl_rows
            P.coef["grl_bin"] = gbin.join(grl_rows, how="cross").with_columns(pl.lit(gap).alias("value")).select(["gbin"] + IST + ["value"])
            P.coef["grl_inv"] = inv_st.select(V4 + ["st"]).with_columns(pl.lit(-1.0).alias("value"))
            P.con["eq_growthbin_limit"] = gbl_rows
            P.coef["gbl_const"] = _on_domain(gbl_rows, case["growth_bin_limit"], ["gbin", "st", "tg", "t"])
            P.coef["gbl_bin"] = (gbl_rows.join(case["tg_i"], on="tg", how="inner").with_columns(pl.lit(-1.0).alias("value"))
                                 .select(["gbin", "i", "st", "t", "tg", "value"]))

    if int(case.scalar("Sw_QueueConstraintYears")):
        P.var["CAP_ABOVE_LIM"] = case["slice_objinv_CAP_ABOVE_LIM"].join(tmodel, on="t", how="semi").select(["tg", "r", "t"])
        ql = case["queue_limit"].join(tmodel, on="t", how="semi")
        if ql.height:
            mbs = case.scalar("model_builds_start_yr")
            istart = case.scalar("interconnection_start")
            tgi = case["tg_i"]
            q_rows = (tgi.select("tg").unique().join(case["r"], how="cross").join(tmodel, how="cross").filter(pl.col("t") >= mbs))
            has_inv = _in(valinv, "v", S["newv"]).join(tgi, on="i", how="inner").select(["tg", "r", "t"]).unique()
            q_rows = q_rows.join(has_inv, on=["tg", "r", "t"], how="semi").select(["tg", "r", "t"])
            cur_inv = (P.var["INV"].filter(pl.col("v").is_in(list(S["newv"])) & (pl.col("t") >= istart)).join(tgi, on="i", how="inner")
                       .join(q_rows, on=["tg", "r", "t"], how="semi").with_columns(pl.lit(-1.0).alias("value")).select(["tg"] + V4 + ["value"]))
            past = (case["state_INV"].join(tfix_tt, on="tt", how="semi").join(valinv_tfix, on=["i", "v", "r", "tt"], how="semi")
                    .filter(pl.col("v").is_in(list(S["newv"])) & (pl.col("tt") >= istart)).join(tgi, on="i", how="inner")
                    .join(tmodel, how="cross").group_by(["tg", "r", "t"]).agg(pl.col("value").sum()))
            if "INV_REFURB" in P.var:
                cur_ref = (P.var["INV_REFURB"].filter(pl.col("v").is_in(list(S["newv"])) & (pl.col("t") >= istart)).join(tgi, on="i", how="inner")
                           .join(q_rows, on=["tg", "r", "t"], how="semi").with_columns(pl.lit(-1.0).alias("value")).select(["tg"] + V4 + ["value"]))
                past_ref = (case["state_INV_REFURB"].join(tfix_tt, on="tt", how="semi").join(valinv_tfix, on=["i", "v", "r", "tt"], how="semi")
                            .filter(pl.col("v").is_in(list(S["newv"])) & (pl.col("tt") >= istart)).join(tgi, on="i", how="inner")
                            .join(_in(valcap.select("i").unique(), "i", refurb), on="i", how="semi")
                            .join(tmodel, how="cross").group_by(["tg", "r", "t"]).agg(pl.col("value").sum()))
            else:
                cur_ref = cur_inv.head(0)
                past_ref = past.head(0)
            const = _add(_add(_on_domain(q_rows, ql, ["tg", "r", "t"]), past, ["tg", "r", "t"], sign=-1.0), past_ref, ["tg", "r", "t"], sign=-1.0)
            P.con["eq_interconnection_queues"] = q_rows
            P.coef["queue_const"] = const
            P.coef["queue_above"] = _signed(q_rows, ["tg", "r", "t"], 1.0)
            P.coef["queue_inv"] = cur_inv
            P.coef["queue_refurb"] = cur_ref
            P.var["CAP_ABOVE_LIM"] = pl.concat([q_rows, P.var["CAP_ABOVE_LIM"]]).unique()

    sw_h2 = int(case.scalar("Sw_H2"))
    sw_prod = int(case.scalar("Sw_Prod"))
    if sw_h2 == 1:
        raise NotImplementedError("Sw_H2=1 (eq_h2_demand) is not ported")
    if sw_h2 == 2 and int(case.scalar("Sw_H2_StorTimestep")) == 2:
        raise NotImplementedError("Sw_H2_StorTimestep=2 (hourly hydrogen storage level) is not ported")
    if int(case.scalar("Sw_H2_CompressorLoad")):
        raise NotImplementedError("Sw_H2_CompressorLoad is not ported")
    P6 = ["p", "i", "v", "r", "h", "t"]
    h2_start = case.scalar("h2_demand_start")
    if sw_prod:
        prod_dom = (_in(valcap, "i", S["consume"]).join(case["i_p"], on="i", how="inner").join(_in(h, "h", h_rep), how="cross").select(P6))
        P.var["PRODUCE"] = prod_dom
        pcr = case["prod_conversion_rate"].rename({"value": "pcr"})
        P.coef["load_produce"] = (prod_dom.filter(pl.col("i") != "dac_gas").join(pcr, on=V4, how="inner")
                                  .with_columns((-(1.0 / pl.col("pcr"))).alias("value")).select(P6 + ["value"]))
        per = case["prod_emit_rate"].rename({"value": "per"})
        P.coef["emit_produce"] = (prod_dom.join(per, on=["i", "t"], how="inner").join(hours_rep.rename({"value": "hrs"}), on="h", how="inner")
                                  .join(P.var["EMIT"].select(["etype", "e", "r", "t"]), on=["etype", "e", "r", "t"], how="semi")
                                  .with_columns((-(pl.col("hrs") * pl.col("per"))).alias("value")).select(["etype", "e"] + P6 + ["value"]))
        pc_dom = prod_dom.select(GEN_IDX).unique()
        P.con["eq_prod_capacity_limit"] = pc_dom
        seas_p = (h_szn.join(case["seas_cap_frac_delta"].rename({"value": "d"}), on="szn", how="inner").group_by(GEN_IDX).agg(pl.col("d").sum()))
        P.coef["prodcap_cap"] = (pc_dom.join(case["avail"].rename({"value": "avail"}), on=["i", "r", "h"], how="left")
                                 .join(pcr, on=V4, how="left").join(seas_p, on=GEN_IDX, how="left")
                                 .with_columns((((pl.col("avail").fill_null(0.0) * pl.when(pl.col("i") == "dac_gas").then(1.0).otherwise(pl.col("pcr").fill_null(0.0))))
                                                * (1.0 + pl.col("d").fill_null(0.0))).alias("value")).select(GEN_IDX + ["value"]))
        P.coef["prodcap_produce"] = _signed(prod_dom, P6, -1.0)
    else:
        P.coef["load_produce"] = pl.DataFrame(schema={c: pl.Utf8 for c in P6} | {"value": pl.Float64}).with_columns(pl.col("t").cast(pl.Int64))
        P.coef["emit_produce"] = pl.DataFrame(schema={c: pl.Utf8 for c in ["etype", "e"] + P6} | {"value": pl.Float64}).with_columns(pl.col("t").cast(pl.Int64))
    if sw_h2 == 2 and (tmodel["t"] >= h2_start).all():
        RHT = ["r", "h", "t"]
        h2_stor_r = case["h2_stor_r"]
        P.var["H2_STOR_CAP"] = h2_stor_r.join(tmodel, how="cross").select(["h2_stor", "r", "t"])
        P.var["H2_STOR_INV"] = P.var["H2_STOR_CAP"]
        P.var["H2_STOR_IN"] = h2_stor_r.join(_in(h, "h", h_rep).join(tmodel, how="cross"), how="cross").select(["h2_stor", "r", "h", "t"])
        P.var["H2_STOR_OUT"] = P.var["H2_STOR_IN"]
        P.var["H2_STOR_LEVEL_SZN"] = h2_stor_r.join(case["actualszn"], how="cross").join(tmodel, how="cross").select(["h2_stor", "r", "actualszn", "t"])
        routes_h2 = case["h2_routes"]
        if routes_h2.height:
            raise NotImplementedError("hydrogen pipeline routes are not ported")
        hci = case.scalar("h2_combustion_intensity")
        hr = case["heat_rate"].rename({"value": "hr"})
        h2gen = (_in(P.var["GEN"], "i", S["h2_gen"]).join(_in(h, "h", h_rep), on="h", how="semi").join(hr, on=V4, how="inner")
                 .with_columns((-(hci * pl.col("hr"))).alias("value")).select(GEN_IDX + ["value"]))
        prod_h2 = _in(P.var["PRODUCE"], "i", S["h2"]).with_columns(pl.lit(1.0).alias("value")).select(P6 + ["value"])
        stor_rows = P.var["H2_STOR_OUT"].join(_in(h, "h", h_rep), on="h", how="semi")
        dem_rows = pl.concat([h2gen.select(RHT), prod_h2.select(RHT), stor_rows.select(RHT)]).unique()
        exog = case["h2_exogenous_demand_regional"].group_by(RHT).agg(pl.col("value").sum())
        P.con["eq_h2_demand_regional"] = dem_rows
        P.coef["h2dem_const"] = _on_domain(dem_rows, exog, RHT).with_columns((-pl.col("value")).alias("value"))
        P.coef["h2dem_produce"] = prod_h2
        P.coef["h2dem_stor_out"] = _signed(stor_rows, ["h2_stor", "r", "h", "t"], 1.0)
        P.coef["h2dem_stor_in"] = _signed(stor_rows, ["h2_stor", "r", "h", "t"], -1.0)
        P.coef["h2dem_gen"] = h2gen
        P.coef["h2dem_flow_in"] = pl.DataFrame(schema={"r": pl.Utf8, "rr": pl.Utf8, "h": pl.Utf8, "t": pl.Int64, "value": pl.Float64})
        P.coef["h2dem_flow_out"] = P.coef["h2dem_flow_in"]
        for key in ["h2tc_const", "h2tc_inv_fwd", "h2tc_inv_rev", "h2tc_flow_fwd", "h2tc_flow_rev"]:
            P.coef[key] = P.coef["h2dem_flow_in"]
        HS4 = ["h2_stor", "r", "actualszn", "t"]
        lvl_dom = P.var["H2_STOR_LEVEL_SZN"]
        nxt = case["nextszn"]
        P.con["eq_h2_storage_level_szn"] = lvl_dom
        P.coef["h2lvl_next"] = lvl_dom.join(nxt, on="actualszn", how="inner").with_columns(pl.lit(1.0).alias("value")).select(HS4 + ["actualsznn", "value"])
        P.coef["h2lvl_this"] = _signed(lvl_dom, HS4, -1.0)
        hd_act = case["h_actualszn"].join(hd, on="h", how="inner")
        P.coef["h2lvl_in"] = (lvl_dom.join(hd_act, on="actualszn", how="inner").with_columns((-pl.col("hd")).alias("value")).select(HS4 + ["h", "value"]))
        P.coef["h2lvl_out"] = (lvl_dom.join(hd_act, on="actualszn", how="inner").with_columns(pl.col("hd").alias("value")).select(HS4 + ["h", "value"]))
        cap_dom = P.var["H2_STOR_CAP"]
        past = (case["state_H2_STOR_INV"].join(tfix_tt, on="tt", how="semi").join(tmodel, how="cross").filter(pl.col("tt") <= pl.col("t"))
                .group_by(["h2_stor", "r", "t"]).agg(pl.col("value").sum()))
        P.con["eq_h2_storage_capacity"] = cap_dom
        P.coef["h2cap_const"] = _on_domain(cap_dom, past, ["h2_stor", "r", "t"])
        P.coef["h2cap_inv"] = _signed(cap_dom, ["h2_stor", "r", "t"], 1.0)
        P.coef["h2cap_cap"] = _signed(cap_dom, ["h2_stor", "r", "t"], -1.0)
        msh = case.scalar("Sw_H2_MinStorHours")
        if msh:
            gen_cap = (_in(valcap, "i", S["h2_gen"]).join(hr, on=V4, how="inner")
                       .with_columns((-(((1.0 * pl.col("hr")) * hci) * msh)).alias("value")).select(V4 + ["value"]))
            min_rows = pl.concat([cap_dom.select(["r", "t"]), gen_cap.select(["r", "t"])]).unique()
            P.con["eq_h2_min_storage_cap"] = min_rows
            P.coef["h2min_cap"] = _signed(cap_dom, ["h2_stor", "r", "t"], 1.0)
            P.coef["h2min_gen"] = gen_cap
        fl_dom = stor_rows.select(["h2_stor", "r", "h", "t"])
        P.con["eq_h2_storage_flowlimit"] = fl_dom
        P.coef["h2fl_cap"] = fl_dom.with_columns(pl.lit(1.0 / case.scalar("h2_storage_duration")).alias("value"))
        P.coef["h2fl_in"] = _signed(fl_dom, ["h2_stor", "r", "h", "t"], -1.0)
        P.coef["h2fl_out"] = _signed(fl_dom, ["h2_stor", "r", "h", "t"], -1.0)
        P.con["eq_h2_storage_caplimit_szn"] = lvl_dom
        P.coef["h2cl_cap"] = _signed(lvl_dom, HS4, 1.0)
        P.coef["h2cl_lvl"] = _signed(lvl_dom, HS4, -1.0)
    if int(case.scalar("Sw_H2_PTC")) and sw_h2:
        ptc_year = tmodel.join(case["h2_ptc_years"], on="t", how="semi").filter(pl.col("t") >= h2_start)
        vg_ptc = case["valgen_h2ptc"].join(tmodel, on="t", how="semi")
        credit_base = vg_ptc.join(_in(h, "h", h_rep), how="cross").select(GEN_IDX)
        credit_used = []
        if ptc_year.height:
            credit_used.append(credit_base)
            P.con["eq_h2_ptc_creditgen"] = credit_base
            P.coef["ptcg_gen"] = _signed(P.var["GEN"].join(credit_base, on=GEN_IDX, how="semi"), GEN_IDX, 1.0)
            P.coef["ptcg_credit"] = _signed(credit_base, GEN_IDX, -1.0)
            match_year = case.scalar("h2_ptc_temporal_match_year")
            rreg = case["r_h2ptcreg"]
            ele = (P.var["PRODUCE"].filter((pl.col("p") == "h2") & (pl.col("i") == "electrolyzer")).join(case["prod_conversion_rate"].rename({"value": "pcr"}), on=V4, how="inner")
                   .join(rreg, on="r", how="inner").with_columns((-(1.0 / pl.col("pcr"))).alias("value")))
            cred = credit_base.join(rreg, on="r", how="inner").with_columns(pl.lit(1.0).alias("value"))
            if (tmodel["t"] < match_year).all():
                rows = pl.concat([cred.select(["h2ptcreg", "t"]), ele.select(["h2ptcreg", "t"])]).unique()
                P.con["eq_h2_ptc_region_balance"] = rows
                P.coef["ptcb_credit"] = cred.select(["h2ptcreg"] + GEN_IDX + ["value"])
                P.coef["ptcb_produce"] = ele.select(["h2ptcreg"] + P6 + ["value"])
            else:
                rows = pl.concat([cred.select(["h2ptcreg", "h", "t"]), ele.select(["h2ptcreg", "h", "t"])]).unique()
                P.con["eq_h2_ptc_region_hour_balance"] = rows
                P.coef["ptch_credit"] = cred.select(["h2ptcreg"] + GEN_IDX + ["value"])
                P.coef["ptch_produce"] = ele.select(["h2ptcreg"] + P6 + ["value"])
        if "eq_REC_Generation" in P.con:
            mult = case["rpstechmult"].rename({"value": "mult"})
            P.coef["recgen_credit"] = (P.con["eq_REC_Generation"].join(credit_base, on=["i", "t"], how="inner")
                                       .join(case["r_st"], on=["r", "st"], how="semi").join(hours_rep.rename({"value": "hrs"}), on="h", how="inner")
                                       .join(mult, on=["rpscat", "i", "st"], how="left")
                                       .with_columns((-(pl.col("mult").fill_null(0.0) * pl.col("hrs"))).alias("value")).select(["rpscat", "i", "st", "t", "v", "r", "h", "value"])
                                       .filter(pl.col("value") != 0.0))
            credit_used.append(P.coef["recgen_credit"].select(GEN_IDX))
        if "eq_REC_launder" in P.con:
            P.coef["reclau_credit"] = (P.con["eq_REC_launder"].join(case["rectech"].join(tmodel, on="t", how="semi"), on=["rpscat", "st", "t"], how="inner")
                                       .join(credit_base, on=["i", "t"], how="inner").join(case["r_st"], on=["r", "st"], how="semi")
                                       .join(hours_rep.rename({"value": "hrs"}), on="h", how="inner")
                                       .with_columns((-pl.col("hrs")).alias("value")).select(["rpscat", "st", "t", "i", "v", "r", "h", "value"]))
            credit_used.append(P.coef["reclau_credit"].select(GEN_IDX))
        if credit_used:
            P.var["CREDIT_H2PTC"] = pl.concat(credit_used).unique().select(GEN_IDX)
    for key in ["recgen_credit", "reclau_credit"]:
        if key not in P.coef:
            P.coef[key] = pl.DataFrame(schema={c: pl.Utf8 for c in ["rpscat", "st", "t", "i", "v", "r", "h"]} | {"value": pl.Float64}).with_columns(pl.col("t").cast(pl.Int64))

    for name, what in (("Sw_LoadSiteCF", "load siting (eq_loadsite_*)"), ("Sw_Mingen", "eq_mingen_lb/eq_mingen_ub"),
                       ("Sw_PRM_CapCredit", "the capacity-credit reserve-margin family"), ("Sw_itlgrpConstraint", "ITL group limits"),
                       ("Sw_CO2_Detail", "CO2 transport and storage detail"), ("Sw_CCSFLEX_BYP", "flexible CCS"), ("Sw_CCSFLEX_STO", "flexible CCS"),
                       ("Sw_CCSFLEX_DAC", "flexible CCS")):
        if int(case.scalar(name)):
            raise NotImplementedError(f"{name} is on but {what} is not ported")
    if int(case.scalar("Sw_GasCurve")) in (0, 3):
        raise NotImplementedError("Sw_GasCurve=0/3 (eq_gasused, gas bins) is not ported")
    if int(case.scalar("Sw_GasCurve")) == 1:
        cendiv = case["cendiv"]
        fuelbin = case["fuelbin"]
        FC = ["fuelbin", "cendiv", "t"]
        P.var["VGASBINQ_REGIONAL"] = fuelbin.join(cendiv, how="cross").join(tmodel, how="cross").select(FC)
        P.var["VGASBINQ_NATIONAL"] = fuelbin.join(tmodel, how="cross").select(["fuelbin", "t"])
        gas_gen = (_in(valgen, "i", S["gas"]).join(case["heat_rate"].rename({"value": "hr"}), on=V4, how="inner")
                   .join(case["hours"].rename({"value": "hrs"}), how="cross")
                   .with_columns((-(pl.col("hrs") * pl.col("hr"))).alias("value")).select(GEN_IDX + ["value"]))
        P.con["eq_gasaccounting_regional"] = cendiv.join(tmodel, how="cross").select(["cendiv", "t"])
        P.coef["gasacc_reg_bin"] = _signed(P.var["VGASBINQ_REGIONAL"], FC, 1.0)
        P.coef["gasacc_reg_gen"] = gas_gen.join(case["r_cendiv"], on="r", how="inner").select(GEN_IDX + ["cendiv", "value"])
        P.con["eq_gasaccounting_national"] = tmodel.select("t")
        P.coef["gasacc_nat_bin"] = _signed(P.var["VGASBINQ_NATIONAL"], ["fuelbin", "t"], 1.0)
        P.coef["gasacc_nat_gen"] = gas_gen
        P.con["eq_gasbinlimit_regional"] = P.var["VGASBINQ_REGIONAL"]
        P.coef["gasbin_reg_width"] = _on_domain(P.var["VGASBINQ_REGIONAL"], case["gasbinwidth_regional"], FC)
        P.coef["gasbin_reg_var"] = _signed(P.var["VGASBINQ_REGIONAL"], FC, -1.0)
        P.con["eq_gasbinlimit_national"] = P.var["VGASBINQ_NATIONAL"]
        P.coef["gasbin_nat_width"] = _on_domain(P.var["VGASBINQ_NATIONAL"], case["gasbinwidth_national"], ["fuelbin", "t"])
        P.coef["gasbin_nat_var"] = _signed(P.var["VGASBINQ_NATIONAL"], ["fuelbin", "t"], -1.0)
    if _in(valgen, "i", S["storage_interday"]).height:
        raise NotImplementedError("interday storage equations are not ported")

    for name in ["eq_cap_init_retmo", "eq_cap_init_retub", "eq_cap_new_retmo", "eq_cap_new_retub", "eq_forceprescription_power",
                 "eq_forceprescription_energy", "eq_refurblim", "eq_cap_rsc", "eq_cap_upgrade", "eq_cap_up", "eq_ener_up",
                 "eq_OpRes_requirement", "eq_storage_opres", "eq_storage_thermalres", "eq_storage_in_cap", "eq_battery_minduration",
                 "eq_ramping", "eq_dhyd_dispatch", "eq_Canadian_Imports", "eq_mingen_fixed", "eq_min_cf", "eq_max_daily_cf",
                 "eq_caa_max_cf", "eq_caa_rate_standard", "eq_bioused", "eq_biousedlimit", "eq_batterymandate",
                 "eq_INVTRAN_DC", "eq_INVTRAN_AC_forward", "eq_INVTRAN_AC_reverse", "eq_INVTRAN_AC", "eq_TRAN_CAPEX_BINS", "eq_invtran_exog",
                 "eq_prescribed_transmission", "eq_POI_cap", "eq_CAPTRAN_GRP", "eq_transgrp_limit_energy", "eq_firm_transfer_limit",
                 "eq_transmission_investment_max", "eq_CAPTRAN_max", "eq_CAPTRAN_max_total", "eq_offshore_no_backflow",
                 "eq_RGGI_cap", "eq_state_cap", "eq_CSAPR_Budget", "eq_CSAPR_Assurance", "eq_REC_Generation", "eq_REC_Requirement",
                 "eq_REC_BundleLimit", "eq_REC_unbundledLimit", "eq_REC_ooslim", "eq_REC_launder", "eq_RPS_OFSWind", "eq_interconnection_queues",
                 "eq_prod_capacity_limit", "eq_h2_demand_regional", "eq_h2_storage_level_szn", "eq_h2_storage_capacity", "eq_h2_min_storage_cap",
                 "eq_h2_storage_flowlimit", "eq_h2_storage_caplimit_szn", "eq_h2_ptc_region_balance", "eq_h2_ptc_region_hour_balance",
                 "eq_h2_ptc_creditgen", "eq_site_cf", "eq_spurclip", "eq_spur_noclip", "eq_capacity_limit_hybrid", "eq_CAP_SPUR"]:
        if name in P.con and P.con[name].height == 0:
            del P.con[name]

    # ---------------------------------------------------------- objective
    cs = case.scalar("cost_scale")
    pvc = case["pvf_capital"].rename({"value": "pvc"})
    pvo = case["pvf_onm"].rename({"value": "pvo"})

    def _scale(df, pv, pvname):
        return (df.join(pv, on="t", how="inner")
                .with_columns((cs * pl.col("value") * pl.col(pvname)).alias("value")).drop(pvname))

    def _objective(var, table, pv, pvname):
        keys = list(P.var[var].columns)
        coef = case[table].select(keys + ["value"])
        on_domain = coef.join(P.var[var], on=keys, how="semi")
        P.options["objective_rows_off_domain"][table] = coef.height - on_domain.height
        return _scale(on_domain, pv, pvname)

    P.options["objective_rows_off_domain"] = {}
    inv_terms = {"INV": "slice_objinv_INV", "INV_ENERGY": "slice_objinv_INV_ENERGY", "INV_CONVERTER": "slice_objinv_INV_CONVERTER",
                 "INV_RSC": "slice_objinv_INV_RSC", "UPGRADES": "slice_objinv_UPGRADES", "INV_REFURB": "slice_objinv_INV_REFURB",
                 "INV_CAP_UP": "slice_objinv_INV_CAP_UP", "INV_ENER_UP": "slice_objinv_INV_ENER_UP",
                 "INVTRAN": "slice_objinv_INVTRAN", "TRAN_CAPEX_BINS": "slice_objinv_TRAN_CAPEX_BINS", "INV_POI": "slice_objinv_INV_POI",
                 "CAP_ABOVE_LIM": "slice_objinv_CAP_ABOVE_LIM", "GROWTH_BIN": "slice_objinv_GROWTH_BIN", "H2_STOR_INV": "slice_objinv_H2_STOR_INV",
                 "H2_TRANSPORT_INV": "slice_objinv_H2_TRANSPORT_INV", "INV_SPUR": "slice_objinv_INV_SPUR"}
    op_terms = {"GEN": "slice_objop_GEN", "CAP": "slice_objop_CAP", "INV": "slice_objop_INV", "CAP_CONVERTER": "slice_objop_CAP_CONVERTER",
                "CAP_ENERGY": "slice_objop_CAP_ENERGY", "CAPTRAN_ENERGY": "slice_objop_CAPTRAN_ENERGY",
                "FLOW": "slice_objop_FLOW", "EMIT": "slice_objop_EMIT", "CAP_RSC": "slice_objop_CAP_RSC",
                "INV_REFURB": "slice_objop_INV_REFURB", "UPGRADES": "slice_objop_UPGRADES",
                "OPRES": "slice_objop_OPRES", "RAMPUP": "slice_objop_RAMPUP", "BIOUSED": "slice_objop_BIOUSED",
                "INV_POI": "slice_objop_INV_POI", "ACP_PURCHASES": "slice_objop_ACP_PURCHASES",
                "PRODUCE": "slice_objop_PRODUCE", "H2_STOR_CAP": "slice_objop_H2_STOR_CAP", "H2_TRANSPORT_INV": "slice_objop_H2_TRANSPORT_INV",
                "DROPPED": "slice_objop_DROPPED", "EXCESS": "slice_objop_EXCESS",
                "VGASBINQ_REGIONAL": "slice_objop_VGASBINQ_REGIONAL", "VGASBINQ_NATIONAL": "slice_objop_VGASBINQ_NATIONAL",
                "CAP_SPUR": "slice_objop_CAP_SPUR"}
    for var, table in inv_terms.items():
        if var not in P.var:
            continue
        P.obj[var] = _objective(var, table, pvc, "pvc")
    for var, table in op_terms.items():
        if var not in P.var:
            continue
        term = _objective(var, table, pvo, "pvo")
        if var in P.obj:
            keys = list(P.var[var].columns)
            P.obj[var] = (pl.concat([P.obj[var], term]).group_by(keys).agg(pl.col("value").sum()))
        else:
            P.obj[var] = term
    for var in list(P.obj):
        P.obj[var] = P.obj[var].filter(pl.col("value") != 0.0)
    if "INVTRAN" in P.var and case["slice_trans_cost"].height:
        P.obj["INVTRAN"] = _scale(
            P.var["INVTRAN"].join(tmodel, on="t", how="semi").join(case["slice_trans_cost"], on=["r", "rr", "trtype"], how="inner"),
            pvc, "pvc")
    return _sorted(P)


def _sorted(P: Prepared) -> Prepared:
    """Sort every table by its index columns.

    polars joins and group_bys do not guarantee row order, and row/column
    order decides which optimal vertex a degenerate LP lands on. Sorting makes
    primal and dual solutions reproducible from run to run.
    """
    for store in (P.var, P.con, P.coef, P.obj):
        for k, df in store.items():
            if isinstance(df, pl.DataFrame) and df.height:
                keys = [c for c in df.columns if c != "value"]
                store[k] = df.sort(keys)
    return P
