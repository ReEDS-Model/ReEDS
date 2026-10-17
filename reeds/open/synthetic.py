"""Synthetic case in the contract format, for logic tests and scaling runs.

Shaped like a ReEDS sequential solve year: existing and new vintages,
investments carried in from two earlier solve years, rsc supply-curve
bins (one bin deliberately exhausted to exercise the rhs_tolerance flag),
representative + stress timeslices, a ring transmission network, a
binding CO2 cap, batteries (energy decoupled) and pumped hydro.

Numbers are plausible magnitudes, not ReEDS data.
"""
from __future__ import annotations

import numpy as np
import polars as pl

from .contract import Case, from_tables

T, TFIX = 2032, (2026, 2029)

TECHS = {
    #  name         dispatch  new   fuel  heat  co2t/MWh  vom   fom      capex     init_MW
    "gas-cc":      (True,  True,  4.0,  6.5,  0.35,  2.0,  14_000,  1.10e6,  1200),
    "gas-ct":      (True,  True,  4.0,  10.0, 0.54,  4.0,  12_000,  0.90e6,  600),
    "coal-old":    (True,  False, 2.2,  10.5, 0.95,  4.5,  45_000,  0.0,     900),
    "nuclear":     (True,  False, 0.7,  10.4, 0.0,   2.5,  130_000, 0.0,     500),
    "upv_1":       (False, True,  0.0,  0.0,  0.0,   0.0,  18_000,  0.95e6,  300),
    "upv_2":       (False, True,  0.0,  0.0,  0.0,   0.0,  18_000,  0.95e6,  0),
    "wind-ons_1":  (False, True,  0.0,  0.0,  0.0,   0.0,  38_000,  1.35e6,  400),
    "hydND":       (False, False, 0.0,  0.0,  0.0,   0.0,  30_000,  0.0,     250),
    "battery_li":  (True,  True,  0.0,  0.0,  0.0,   0.0,  15_000,  0.12e6,  0),
    "pumped-hydro": (True, False, 0.0,  0.0,  0.0,   0.0,  25_000,  0.0,     300),
}
RSC = ["upv_1", "upv_2", "wind-ons_1"]
STORAGE = ["battery_li", "pumped-hydro"]
NEW_TECHS = [k for k, v in TECHS.items() if v[1]]
# typical project sizes, MW per unit (illustrative, not ReEDS data)
UNIT_MW = {"gas-cc": 450.0, "gas-ct": 230.0, "upv_1": 100.0, "upv_2": 100.0,
           "wind-ons_1": 200.0, "battery_li": 100.0}
INIT_TECHS = [k for k, v in TECHS.items() if v[8] > 0]


def _df(rows, cols):
    return pl.DataFrame(rows, schema=cols, orient="row")


def make_case(n_regions: int = 3, n_rep_days: int = 4, chunks_per_day: int = 6,
              n_stress_days: int = 1, seed: int = 7, co2_cap_frac: float = 0.25) -> Case:
    rng = np.random.default_rng(seed)
    R = [f"z{k + 1}" for k in range(n_regions)]
    chunk_len = 24 // chunks_per_day
    rep = [f"d{d + 1}h{c + 1}" for d in range(n_rep_days) for c in range(chunks_per_day)]
    stress = [f"s{d + 1}h{c + 1}" for d in range(n_stress_days) for c in range(chunks_per_day)]
    H = rep + stress

    def day_cycle(prefix, n_days):
        out = []
        for d in range(n_days):
            hs = [f"{prefix}{d + 1}h{c + 1}" for c in range(chunks_per_day)]
            out += [(hs[k], hs[(k + 1) % len(hs)]) for k in range(len(hs))]
        return out

    nexth = day_cycle("d", n_rep_days) + day_cycle("s", n_stress_days)
    hour_of = {hh: (int(hh.split("h")[1]) - 1) * chunk_len + chunk_len / 2 for hh in H}
    weight = 365.0 / n_rep_days
    # stress timeslices carry no hours in ReEDS ("stress periods have no hours", report.gms)
    hours = [(hh, weight * chunk_len) for hh in rep] + [(hh, 0.0) for hh in stress]

    tb: dict[str, pl.DataFrame] = {}
    tb["tmodel"] = _df([(T,)], ["t"])
    tb["tfix"] = _df([(y,) for y in TFIX], ["t"])
    tb["h"] = _df([(x,) for x in H], ["h"])
    tb["h_rep"] = _df([(x,) for x in rep], ["h"])
    tb["h_stress"] = _df([(x,) for x in stress], ["h"])
    tb["nexth"] = _df(nexth, ["h", "hh"])
    tb["r"] = _df([(x,) for x in R], ["r"])
    tb["land"] = tb["r"]
    tb["hours"] = _df(hours, ["h", "value"])
    tb["hours_daily"] = _df([(x, float(chunk_len)) for x in H], ["h", "value"])

    # vintages: init-1 existing; new1 built 2026/2029; new2 built in the solve year
    tb["initv"] = _df([("init-1",)], ["v"])
    tb["newv"] = _df([("new1",), ("new2",)], ["v"])
    valcap, valinv, inv_cond, exog = [], [], [], []
    state_inv, state_inv_e = [], []
    for r in R:
        scale_r = rng.uniform(0.6, 1.4)
        for i in INIT_TECHS:
            mw = TECHS[i][8] * scale_r
            valcap.append((i, "init-1", r, T))
            exog.append((i, "init-1", r, T, mw))
        for i in NEW_TECHS:
            valcap += [(i, "new1", r, T), (i, "new2", r, T)]
            valinv.append((i, "new2", r, T))
            inv_cond += [(i, "new1", r, T, 2026), (i, "new1", r, T, 2029), (i, "new2", r, T, T)]
            for tt in TFIX:
                past = rng.uniform(0, 150) if i not in ("upv_1",) else 0.0
                state_inv.append((i, "new1", r, tt, past))
                if i == "battery_li":
                    state_inv_e.append((i, "new1", r, tt, 4 * past))
    tb["valcap"] = _df(valcap, ["i", "v", "r", "t"])
    tb["valgen"] = tb["valcap"]
    tb["valinv"] = _df(valinv, ["i", "v", "r", "t"])
    tb["inv_cond"] = _df(inv_cond, ["i", "v", "r", "t", "tt"])
    tb["m_capacity_exog"] = _df(exog, ["i", "v", "r", "t", "value"])
    tb["degrade_init"] = tb["m_capacity_exog"].with_columns(pl.lit(0.995).alias("value"))
    tb["degrade_new"] = _df([(i, tt, T, 1.0 - 0.002 * (T - tt)) for i in NEW_TECHS for tt in (*TFIX, T)],
                            ["i", "tt", "t", "value"])
    tb["state_INV"] = _df(state_inv, ["i", "v", "r", "tt", "value"])
    tb["state_INV_ENERGY"] = _df(state_inv_e, ["i", "v", "r", "tt", "value"])

    # tech subsets
    tb["storage"] = _df([(x,) for x in STORAGE], ["i"])
    tb["storage_standalone"] = tb["storage"]
    tb["storinmaxfrac"] = (tb["valcap"].filter(pl.col("i").is_in(STORAGE)).select(["i", "v", "r"]).unique()
                           .with_columns(pl.lit(1.0).alias("value")))
    tb["battery"] = _df([("battery_li",)], ["i"])
    tb["nondispatch"] = _df([("hydND",)], ["i"])
    tb["rsc_i"] = _df([(x,) for x in RSC], ["i"])
    tb["upv"] = _df([("upv_1",), ("upv_2",)], ["i"])
    tb["wind"] = _df([("wind-ons_1",)], ["i"])
    tb["vre"] = _df([(x,) for x in RSC], ["i"])
    tb["psh"] = _df([("pumped-hydro",)], ["i"])
    tb["ilr"] = _df([("upv_1", 1.34), ("upv_2", 1.34)], ["i", "value"])
    # unit sizes for integer investment (MW per unit; used only by build_pyoframe_mip)
    tb["unit_size"] = _df([(i, UNIT_MW[i]) for i in NEW_TECHS if i in UNIT_MW], ["i", "value"])
    tb["rsc_agg"] = _df([(x, x) for x in RSC], ["i", "ii"])
    tb["resourcescaler"] = _df([(x, 1.0) for x in RSC], ["i", "value"])

    # capacity coefficients by hour
    cap_coef, stor_coef = [], []
    for r in R:
        lat = rng.uniform(0.85, 1.1)
        wind_r = rng.uniform(0.7, 1.2)
        for hh in H:
            hr = hour_of[hh]
            is_stress = hh in stress
            solar = round(max(0.0, np.sin(np.pi * (hr - 6) / 12)) * 0.85 * lat * (0.4 if is_stress else 1.0), 6)
            wind = (0.38 + 0.12 * np.cos(np.pi * hr / 12)) * wind_r * (0.5 if is_stress else 1.0)
            for i, v in [(i, v) for (i, v, rr_, _) in valcap if rr_ == r]:
                if i in STORAGE:
                    stor_coef.append((i, v, r, hh, T, 0.97))
                elif i.startswith("upv"):
                    cap_coef.append((i, v, r, hh, T, solar * (1.0 if i == "upv_1" else 0.9)))
                elif i.startswith("wind"):
                    cap_coef.append((i, v, r, hh, T, wind))
                elif i == "hydND":
                    cap_coef.append((i, v, r, hh, T, 0.42))
                else:
                    cap_coef.append((i, v, r, hh, T, 0.90 if is_stress else 0.94))
    tb["slice_cap_coef"] = _df(cap_coef, ["i", "v", "r", "h", "t", "value"])
    tb["slice_stor_cap_coef"] = _df(stor_coef, ["i", "v", "r", "h", "t", "value"])
    tb["slice_dur_coef"] = _df([("pumped-hydro", "init-1", r, 8.0) for r in R], ["i", "v", "r", "value"])
    tb["storage_eff"] = _df([("battery_li", T, 0.85), ("pumped-hydro", T, 0.80)], ["i", "t", "value"])

    # supply curves: three bins; z1/upv_1/bin1 is exactly used up by past builds (flag test)
    feas, rcap, rcost, st_rsc = [], [], [], []
    for r in R:
        for i in RSC:
            for b, (cap, cost) in enumerate([(800, 30_000), (1500, 90_000), (4000, 250_000)]):
                bin_ = f"bin{b + 1}"
                feas.append((r, i, bin_))
                rcap.append((r, i, bin_, T, float(cap)))
                rcost.append((r, i, bin_, float(cost)))
        st_rsc.append(("upv_1", "new1", r, "bin1", 2026, 800.0 if r == "z1" else 100.0))
    tb["m_rscfeas"] = _df(feas, ["r", "i", "rscbin"])
    tb["m_rsc_con"] = tb["m_rscfeas"].select(["r", "i"]).unique()
    tb["slice_rsc_cap"] = _df(rcap, ["r", "i", "rscbin", "t", "value"])
    tb["slice_rsc_cost"] = _df(rcost, ["r", "i", "rscbin", "value"])
    tb["state_INV_RSC"] = _df(st_rsc, ["i", "v", "r", "rscbin", "tt", "value"])

    # load: diurnal shape, higher on stress days
    load = []
    for r in R:
        base = rng.uniform(3200, 4200)
        for hh in H:
            hr = hour_of[hh]
            shape = 0.8 + 0.25 * np.sin(np.pi * (hr - 8) / 12)
            load.append((r, hh, T, base * shape * (1.25 if hh in stress else 1.0)))
    tb["load_exog_static"] = _df(load, ["r", "h", "t", "value"])

    # ring network, both directions
    routes, loss, ce, cp, tcost, st_tran = [], [], [], [], [], []
    pairs = [(R[k], R[(k + 1) % len(R)]) for k in range(len(R))] if len(R) > 1 else []
    pairs = sorted({tuple(sorted(p)) for p in pairs if p[0] != p[1]})  # sorted: deterministic RNG order
    for a, b in pairs:
        cap = rng.uniform(300, 900)
        for x, y in ((a, b), (b, a)):
            routes.append((x, y, "AC", T))
            loss.append((x, y, "AC", 0.01 + 0.01 * rng.random()))
            ce.append((x, y, "AC", cap))
            cp.append((x, y, "AC", 0.9 * cap))
            tcost.append((x, y, "AC", 1.2e6))
            st_tran.append((x, y, "AC", 2029, 25.0))
    tb["routes"] = _df(routes, ["r", "rr", "trtype", "t"])
    tb["routes_prm"] = tb["routes"].select(["r", "rr"]).unique()
    tb["routes_inv"] = tb["routes"]
    tb["tranloss"] = _df(loss, ["r", "rr", "trtype", "value"])
    tb["trancap_init_energy"] = _df(ce, ["r", "rr", "trtype", "value"])
    tb["trancap_init_prm"] = _df(cp, ["r", "rr", "trtype", "value"])
    tb["trans_cap_delta"] = _df([(hh, T, -0.05) for hh in stress], ["h", "t", "value"])
    tb["slice_trans_cost"] = _df(tcost, ["r", "rr", "trtype", "value"])
    tb["state_INVTRAN"] = _df(st_tran, ["r", "rr", "trtype", "tt", "value"])
    # physical AC lines for ptdf.py: one per route pair, reactance from its own RNG so the rest
    # of the case is unchanged; limits are left to ptdf.py's default (the route capacity)
    rng_x = np.random.default_rng(seed + 1)
    lines = [(f"L{a}-{b}", a, b) for a, b in pairs]
    tb["ptdf_line"] = _df(lines, ["line", "r", "rr"])
    tb["ptdf_x"] = _df([(ln, float(rng_x.uniform(0.02, 0.08))) for ln, _, _ in lines], ["line", "value"])

    # emissions: process + upstream accounted, cap on process CO2 only
    tb["etype"] = _df([("process",), ("upstream",)], ["etype"])
    tb["emit_modeled"] = _df([("co2", r, T) for r in R], ["e", "r", "t"])
    tb["emit_capped"] = _df([("co2",)], ["e"])
    tb["gwp"] = _df([("co2", 1.0)], ["e", "value"])
    er = []
    for (i, v, r, t) in valcap:
        rate = TECHS[i][4]
        if rate > 0:
            er.append(("process", "co2", i, v, r, t, rate))
            er.append(("upstream", "co2", i, v, r, t, 0.05 * rate))
    tb["emit_rate"] = _df(er, ["etype", "e", "i", "v", "r", "t", "value"])
    total_load = sum(w * v for (r, hh, t, v) in load for (h2, w) in hours if h2 == hh and hh in rep)
    tb["emit_cap"] = _df([("CO2", T, co2_cap_frac * 0.45 * total_load), ("CO2", 2050, 0.0)],
                         ["eall", "t", "value"])

    # costs
    tb["pvf_capital"] = _df([(T, 1.0)], ["t", "value"])
    tb["pvf_onm"] = _df([(T, 8.5)], ["t", "value"])
    tb["cost_cap"] = _df([(i, T, TECHS[i][7]) for i in NEW_TECHS], ["i", "t", "value"])
    tb["cost_cap_energy"] = _df([("battery_li", T, 0.08e6)], ["i", "t", "value"])
    tb["cost_cap_fin_mult"] = _df([(i, r, T, rng.uniform(1.0, 1.12)) for i in NEW_TECHS for r in R],
                                  ["i", "r", "t", "value"])
    tb["rsc_fin_mult"] = _df([(i, r, T, 1.05) for i in RSC for r in R], ["i", "r", "t", "value"])
    tb["cost_vom"] = _df([(i, v, r, t, TECHS[i][5]) for (i, v, r, t) in valcap], ["i", "v", "r", "t", "value"])
    tb["cost_fom"] = _df([(i, v, r, t, TECHS[i][6]) for (i, v, r, t) in valcap], ["i", "v", "r", "t", "value"])
    tb["cost_fom_energy"] = _df([(i, v, r, t, 5_000.0) for (i, v, r, t) in valcap if i == "battery_li"],
                                ["i", "v", "r", "t", "value"])
    tb["heat_rate"] = _df([(i, v, r, t, TECHS[i][3]) for (i, v, r, t) in valcap], ["i", "v", "r", "t", "value"])
    tb["fuel_price"] = _df([(i, r, T, TECHS[i][2]) for i in TECHS for r in R], ["i", "r", "t", "value"])
    # objective coefficients precomposed as GAMS exports them (before pvf and cost_scale)
    fin = tb["cost_cap_fin_mult"].rename({"value": "fin"})
    tb["slice_objinv_INV"] = (
        tb["valinv"].join(fin, on=["i", "r", "t"], how="inner")
        .join(tb["cost_cap"].rename({"value": "cc"}), on=["i", "t"], how="inner")
        .with_columns((pl.col("fin") * pl.col("cc")).alias("value"))
        .select(["i", "v", "r", "t", "value"]))
    tb["slice_objinv_INV_ENERGY"] = (
        tb["valinv"].join(tb["battery"], on="i", how="semi")
        .join(fin, on=["i", "r", "t"], how="inner")
        .join(tb["cost_cap_energy"].rename({"value": "cc"}), on=["i", "t"], how="inner")
        .with_columns((pl.col("fin") * pl.col("cc")).alias("value"))
        .select(["i", "v", "r", "t", "value"]))
    tb["slice_objinv_INV_RSC"] = (
        tb["valinv"].join(tb["rsc_i"], on="i", how="semi")
        .join(tb["m_rscfeas"], on=["r", "i"], how="inner")
        .join(tb["slice_rsc_cost"].rename({"value": "cost"}), on=["r", "i", "rscbin"], how="inner")
        .join(tb["rsc_fin_mult"].rename({"value": "fin"}), on=["i", "r", "t"], how="inner")
        .with_columns((pl.col("cost") * pl.col("fin")).alias("value"))
        .join(tb["rsc_agg"], on="i", how="inner")
        .group_by(["ii", "v", "r", "rscbin", "t"]).agg(pl.col("value").sum())
        .rename({"ii": "i"})
        .select(["i", "v", "r", "rscbin", "t", "value"]))
    fuel = (tb["heat_rate"].rename({"value": "hr"})
            .join(tb["fuel_price"].rename({"value": "fp"}), on=["i", "r", "t"], how="inner")
            .with_columns((pl.col("hr") * pl.col("fp")).alias("fuel")).select(["i", "v", "r", "t", "fuel"]))
    opc = (tb["cost_vom"].rename({"value": "vom"})
           .join(fuel, on=["i", "v", "r", "t"], how="full", coalesce=True)
           .with_columns((pl.col("vom").fill_null(0.0) + pl.col("fuel").fill_null(0.0)).alias("c"))
           .select(["i", "v", "r", "t", "c"]))
    tb["slice_objop_GEN"] = (
        tb["valgen"].join(tb["h"], how="cross")
        .join(tb["hours"].rename({"value": "hours"}), on="h", how="inner")
        .join(opc, on=["i", "v", "r", "t"], how="inner")
        .with_columns((pl.col("hours") * pl.col("c")).alias("value"))
        .select(["i", "v", "r", "h", "t", "value"]))
    tb["slice_objop_CAP"] = tb["cost_fom"].select(["i", "v", "r", "t", "value"])
    tb["slice_objop_CAP_ENERGY"] = tb["cost_fom_energy"].select(["i", "v", "r", "t", "value"])

    tb["scalars"] = _df([("cost_scale", 1e-6), ("rhs_tolerance", 1e-6), ("Sw_TransInvPRMderate", 0.0)],
                        ["name", "value"])
    return from_tables(tb)
