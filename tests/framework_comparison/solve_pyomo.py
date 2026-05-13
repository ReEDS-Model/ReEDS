"""
Pyomo implementation of the ReEDS-representative LP test problem.

All constraint and variable names mirror the GAMS originals in
reeds/core/setup/c_model.gms and reeds/core/setup/d_objective.gms.

Key pyomo patterns used:
- ConcreteModel with Set, Var, Constraint, Objective
- @m.Constraint decorator style — one rule per constraint family
- VALCAP / VGEN sparse sets filter to active (i,r,t) combinations
- active_i / active_storage_i lookup precomputed per (r,t)
- h_next / h_next_wrap dicts map each hour to its successor
- cf is [i,r,h]: data.cf[ii[i], ri[r], hi[h]]
"""

from __future__ import annotations
import time
import pyomo.environ as pyo
from pyomo.opt import SolverFactory

from data_generator import ProblemData


def solve(data: ProblemData, solver: str = "highs", build_only: bool = False) -> tuple[float, float, float]:
    R, I, H, T = data.regions, data.techs, data.hours, data.years
    ri, ii, hi, ti = data.r_idx, data.i_idx, data.h_idx, data.t_idx

    # Tech classification lists
    disp_techs    = [i for i in I if not data.is_vre[ii[i]] and not data.is_storage[ii[i]]]
    storage_techs = [i for i in I if data.is_storage[ii[i]]]

    # Hour successor maps
    h_next      = {H[k]: H[k+1] for k in range(len(H)-1)}         # no wrap
    h_next_wrap = {H[k]: H[(k+1) % len(H)] for k in range(len(H))} # with wrap

    # Neighbour lookups for supply-demand
    imports_from = {r: [] for r in R}
    exports_to   = {r: [] for r in R}
    for (r_from, r_to) in data.routes:
        imports_from[r_to].append(r_from)
        exports_to[r_from].append(r_to)

    # Sparse index sets derived from valcap
    valcap_irt  = [(i, r, t) for i in I for r in R for t in T
                   if data.valcap[ii[i], ri[r], ti[t]]]
    valcap_irht = [(i, r, h, t) for (i, r, t) in valcap_irt for h in H]

    # Per-(r,t): active techs and active storage techs
    active_i         = {(r,t): [i for i in I if data.valcap[ii[i], ri[r], ti[t]]]
                        for r in R for t in T}
    active_storage_i = {(r,t): [i for i in storage_techs
                                 if data.valcap[ii[i], ri[r], ti[t]]]
                        for r in R for t in T}

    # Mingen sparse set
    mingen_irht = [(i, r, h, t) for (i, r, t) in valcap_irt for h in H
                   if data.minloadfrac[ii[i]] > 0]

    # RAMPUP sparse set: dispatchable, h in H[:-1]
    rampup_irht = [(i, r, h, t) for i in disp_techs for r in R
                   for h in H[:-1] for t in T
                   if data.valcap[ii[i], ri[r], ti[t]]]

    # Storage index sets
    storage_irht = [(i, r, h, t) for i in storage_techs for r in R
                    for h in H for t in T
                    if data.valcap[ii[i], ri[r], ti[t]]]
    storage_irt  = [(i, r, t) for i in storage_techs for r in R for t in T
                    if data.valcap[ii[i], ri[r], ti[t]]]

    # min_cf sparse set (non-VRE, non-storage)
    mincf_irt = [(i, r, t) for (i, r, t) in valcap_irt
                 if not data.is_vre[ii[i]] and not data.is_storage[ii[i]]]
    total_hw   = float(data.hours_weight.sum())

    # ------------------------------------------------------------------ build
    t0 = time.perf_counter()
    m = pyo.ConcreteModel()

    m.R       = pyo.Set(initialize=R)
    m.I       = pyo.Set(initialize=I)
    m.H       = pyo.Set(initialize=H)
    m.T       = pyo.Set(initialize=T)
    m.ROUTES  = pyo.Set(initialize=data.routes, dimen=2)
    m.VALCAP  = pyo.Set(initialize=valcap_irt,  dimen=3)
    m.VGEN    = pyo.Set(initialize=valcap_irht, dimen=4)
    m.MINGEN  = pyo.Set(initialize=mingen_irht, dimen=4)
    m.RAMPUP_SET = pyo.Set(initialize=rampup_irht,  dimen=4)
    m.STOR_IRHT  = pyo.Set(initialize=storage_irht, dimen=4)
    m.STOR_IRT   = pyo.Set(initialize=storage_irt,  dimen=3)
    m.MINCF      = pyo.Set(initialize=mincf_irt,    dimen=3)

    m.GEN    = pyo.Var(m.VGEN,        within=pyo.NonNegativeReals)
    m.CAP    = pyo.Var(m.VALCAP,      within=pyo.NonNegativeReals)
    m.INV    = pyo.Var(m.VALCAP,      within=pyo.NonNegativeReals)
    m.FLOW   = pyo.Var(m.ROUTES, m.H, m.T, within=pyo.NonNegativeReals)
    m.RAMPUP = pyo.Var(m.RAMPUP_SET,  within=pyo.NonNegativeReals)
    m.CHARGE = pyo.Var(m.STOR_IRHT,   within=pyo.NonNegativeReals)
    m.SOC    = pyo.Var(m.STOR_IRHT,   within=pyo.NonNegativeReals)

    # -- eq_cap_accum
    @m.Constraint(m.VALCAP)
    def eq_cap_accum(m, i, r, t):
        return m.CAP[i, r, t] == (
            data.cap_init[ii[i], ri[r]]
            + sum(m.INV[i, r, tt] for tt in T
                  if tt <= t and data.valcap[ii[i], ri[r], ti[tt]])
        )

    # -- eq_cap_limit: GEN <= cf[i,r,h] * CAP
    @m.Constraint(m.VGEN)
    def eq_cap_limit(m, i, r, h, t):
        return m.GEN[i, r, h, t] <= data.cf[ii[i], ri[r], hi[h]] * m.CAP[i, r, t]

    # -- eq_mingen
    @m.Constraint(m.MINGEN)
    def eq_mingen(m, i, r, h, t):
        return m.GEN[i, r, h, t] >= data.minloadfrac[ii[i]] * m.CAP[i, r, t]

    # -- eq_supply_demand_balance
    @m.Constraint(m.R, m.H, m.T)
    def eq_supply_demand_balance(m, r, h, t):
        gen    = sum(m.GEN[i, r, h, t] for i in active_i[(r, t)])
        imp_   = sum((1 - data.tranloss) * m.FLOW[rf, r, h, t]
                     for rf in imports_from[r])
        exp_   = sum(m.FLOW[r, rt, h, t] for rt in exports_to[r])
        charge = sum(m.CHARGE[i, r, h, t] for i in active_storage_i[(r, t)])
        return gen + imp_ - exp_ - charge == data.load[ri[r], hi[h], ti[t]]

    # -- eq_reserve_margin
    @m.Constraint(m.R, m.T)
    def eq_reserve_margin(m, r, t):
        peak = float(data.load[ri[r], :, ti[t]].max())
        return (sum(m.CAP[i, r, t] for i in active_i[(r, t)])
                >= (1 + data.prm) * peak)

    # -- eq_transmission_limit
    @m.Constraint(m.ROUTES, m.H, m.T)
    def eq_transmission_limit(m, r, rr, h, t):
        return m.FLOW[r, rr, h, t] <= data.transcap[(r, rr)]

    # -- eq_emit_cap
    @m.Constraint(m.T)
    def eq_emit_cap(m, t):
        return (
            sum(data.emit_rate[ii[i]] * data.hours_weight[hi[h]] * m.GEN[i, r, h, t]
                for i in I for r in R for h in H
                if data.valcap[ii[i], ri[r], ti[t]] and data.emit_rate[ii[i]] > 0)
            <= data.emit_cap[ti[t]]
        )

    # -- eq_ramping: RAMPUP[i,r,h,t] >= GEN[i,r,h+1,t] - GEN[i,r,h,t]
    @m.Constraint(m.RAMPUP_SET)
    def eq_ramping(m, i, r, h, t):
        return m.RAMPUP[i, r, h, t] >= m.GEN[i, r, h_next[h], t] - m.GEN[i, r, h, t]

    # -- eq_min_cf: annual generation >= min_cf * CAP * total_hours
    @m.Constraint(m.MINCF)
    def eq_min_cf(m, i, r, t):
        return (sum(data.hours_weight[hi[h]] * m.GEN[i, r, h, t] for h in H)
                >= data.min_cf[ii[i]] * m.CAP[i, r, t] * total_hw)

    # -- eq_soc: SOC[h_next] = SOC[h] + eff*CHARGE[h] - GEN_storage[h]
    @m.Constraint(m.STOR_IRHT)
    def eq_soc(m, i, r, h, t):
        hn = h_next_wrap[h]
        return (m.SOC[i, r, hn, t]
                == m.SOC[i, r, h, t]
                + data.charge_eff * m.CHARGE[i, r, h, t]
                - m.GEN[i, r, h, t])

    # -- eq_soc_cap: SOC <= duration_h * CAP
    @m.Constraint(m.STOR_IRHT)
    def eq_soc_cap(m, i, r, h, t):
        return m.SOC[i, r, h, t] <= data.duration_h * m.CAP[i, r, t]

    # -- eq_charge_cap: CHARGE <= CAP
    @m.Constraint(m.STOR_IRHT)
    def eq_charge_cap(m, i, r, h, t):
        return m.CHARGE[i, r, h, t] <= m.CAP[i, r, t]

    # -- Objective
    @m.Objective(sense=pyo.minimize)
    def obj(m):
        return (
            sum(data.pvf[ti[t]] * data.cost_inv[ii[i]] * m.INV[i, r, t]
                for (i, r, t) in valcap_irt)
            + sum(data.pvf[ti[t]] * data.cost_op[ii[i]]
                  * data.hours_weight[hi[h]] * m.GEN[i, r, h, t]
                  for (i, r, h, t) in valcap_irht)
            + sum(data.pvf[ti[t]] * data.startcost[ii[i]] * m.RAMPUP[i, r, h, t]
                  for (i, r, h, t) in rampup_irht)
        )

    build_s = time.perf_counter() - t0
    if build_only:
        return float("nan"), build_s, 0.0

    # ------------------------------------------------------------------ solve
    t1 = time.perf_counter()
    slvr = SolverFactory(solver)
    options = {"solver": "ipm"} if solver == "highs" else {}
    slvr.solve(m, tee=False, options=options)
    solve_s = time.perf_counter() - t1

    return float(pyo.value(m.obj)), build_s, solve_s


if __name__ == "__main__":
    import sys
    sys.path.insert(0, __file__.rsplit("\\", 1)[0])
    from data_generator import make_problem
    for size in ("small", "medium", "large", "xlarge"):
        data = make_problem(size)
        obj, b, s = solve(data)
        print(f"{size:6s}  obj={obj:>18,.0f}  build={b:.3f}s  solve={s:.3f}s")
