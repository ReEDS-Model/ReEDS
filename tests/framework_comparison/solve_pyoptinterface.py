"""
pyoptinterface implementation of the ReEDS-representative LP test problem.

All constraint and variable names mirror the GAMS originals in
reeds/core/setup/c_model.gms and reeds/core/setup/d_objective.gms.

Key pyoptinterface patterns used:
- Variables: m.add_variable(lb=0.0) returns a VariableIndex handle
- Constraints: m.add_linear_constraint(expr, poi.Eq/Leq/Geq, rhs)
- Expressions: arithmetic on VariableIndex objects + poi.quicksum()
- Objective: m.set_objective(expr, poi.ObjectiveSense.Minimize)
- cf is [i,r,h]: data.cf[ii[i], ri[r], hi[h]]

OBJ_SCALE divides all cost coefficients to keep objective magnitudes in a
reasonable range; result is multiplied back at the end.
"""

from __future__ import annotations
import time
import pyoptinterface as poi
from pyoptinterface import highs, xpress
from pyoptinterface._src.attributes import ModelAttribute, TerminationStatusCode

from data_generator import ProblemData


def solve(data: ProblemData, solver: str = "highs", build_only: bool = False) -> tuple[float, float, float]:
    if solver not in {"highs", "xpress"}:
        raise ValueError("solve_pyoptinterface only supports solver='highs' or solver='xpress'")

    R, I, H, T = data.regions, data.techs, data.hours, data.years
    ri, ii, hi, ti = data.r_idx, data.i_idx, data.h_idx, data.t_idx

    disp_techs    = [i for i in I if not data.is_vre[ii[i]] and not data.is_storage[ii[i]]]
    storage_techs = [i for i in I if data.is_storage[ii[i]]]

    h_next      = {H[k]: H[k+1] for k in range(len(H)-1)}
    h_next_wrap = {H[k]: H[(k+1) % len(H)] for k in range(len(H))}

    imports_from = {r: [] for r in R}
    exports_to   = {r: [] for r in R}
    for (r_from, r_to) in data.routes:
        imports_from[r_to].append(r_from)
        exports_to[r_from].append(r_to)

    active_storage_i = {(r, t): [i for i in storage_techs
                                   if data.valcap[ii[i], ri[r], ti[t]]]
                        for r in R for t in T}

    # ------------------------------------------------------------------ build
    t0 = time.perf_counter()
    model_class = highs.Model if solver == "highs" else xpress.Model
    m = model_class()
    m.set_model_attribute(ModelAttribute.Silent, True)
    if solver == "highs":
        m.set_raw_parameter("solver", "ipm")

    GEN    = {}
    CAP    = {}
    INV    = {}
    FLOW   = {}
    RAMPUP = {}
    CHARGE = {}
    SOC    = {}

    # Variables
    for i in I:
        for r in R:
            for t in T:
                if data.valcap[ii[i], ri[r], ti[t]]:
                    CAP[(i, r, t)] = m.add_variable(lb=0.0)
                    INV[(i, r, t)] = m.add_variable(lb=0.0)
                    for h in H:
                        GEN[(i, r, h, t)] = m.add_variable(lb=0.0)
                    if not data.is_vre[ii[i]] and not data.is_storage[ii[i]]:
                        for h in H[:-1]:
                            RAMPUP[(i, r, h, t)] = m.add_variable(lb=0.0)
                    if data.is_storage[ii[i]]:
                        for h in H:
                            CHARGE[(i, r, h, t)] = m.add_variable(lb=0.0)
                            SOC[(i, r, h, t)]    = m.add_variable(lb=0.0)

    for (r_from, r_to) in data.routes:
        for h in H:
            for t in T:
                FLOW[(r_from, r_to, h, t)] = m.add_variable(lb=0.0)

    # -- eq_cap_accum
    for i in I:
        for r in R:
            for t in T:
                if data.valcap[ii[i], ri[r], ti[t]]:
                    lhs = CAP[(i, r, t)] - poi.quicksum(
                        INV[(i, r, tt)] for tt in T
                        if tt <= t and data.valcap[ii[i], ri[r], ti[tt]]
                    )
                    m.add_linear_constraint(lhs, poi.Eq,
                                            data.cap_init[ii[i], ri[r]])

    # -- eq_cap_limit: GEN[i,r,h,t] <= cf[i,r,h] * CAP[i,r,t]
    for i in I:
        for r in R:
            for t in T:
                if not data.valcap[ii[i], ri[r], ti[t]]:
                    continue
                cap_var = CAP[(i, r, t)]
                for h in H:
                    m.add_linear_constraint(
                        GEN[(i, r, h, t)] - data.cf[ii[i], ri[r], hi[h]] * cap_var,
                        poi.Leq, 0.0,
                    )

    # -- eq_mingen
    for i in I:
        mf = data.minloadfrac[ii[i]]
        if mf <= 0 or data.is_storage[ii[i]]:
            continue
        for r in R:
            for t in T:
                if not data.valcap[ii[i], ri[r], ti[t]]:
                    continue
                cap_var = CAP[(i, r, t)]
                for h in H:
                    m.add_linear_constraint(
                        GEN[(i, r, h, t)] - mf * cap_var, poi.Geq, 0.0,
                    )

    # -- eq_supply_demand_balance
    for r in R:
        for h in H:
            for t in T:
                lhs = poi.quicksum(
                    GEN[(i, r, h, t)] for i in I
                    if data.valcap[ii[i], ri[r], ti[t]]
                )
                for rf in imports_from[r]:
                    lhs += (1 - data.tranloss) * FLOW[(rf, r, h, t)]
                for rt in exports_to[r]:
                    lhs -= FLOW[(r, rt, h, t)]
                for i in active_storage_i[(r, t)]:
                    lhs -= CHARGE[(i, r, h, t)]
                m.add_linear_constraint(lhs, poi.Eq,
                                        data.load[ri[r], hi[h], ti[t]])

    # -- eq_reserve_margin
    for r in R:
        for t in T:
            peak = float(data.load[ri[r], :, ti[t]].max())
            lhs = poi.quicksum(
                CAP[(i, r, t)] for i in I
                if data.valcap[ii[i], ri[r], ti[t]]
            )
            m.add_linear_constraint(lhs, poi.Geq, (1 + data.prm) * peak)

    # -- eq_transmission_limit
    for (r_from, r_to) in data.routes:
        cap_val = data.transcap[(r_from, r_to)]
        for h in H:
            for t in T:
                m.add_linear_constraint(
                    FLOW[(r_from, r_to, h, t)], poi.Leq, cap_val,
                )

    # -- eq_emit_cap
    for t in T:
        lhs = poi.quicksum(
            data.emit_rate[ii[i]] * data.hours_weight[hi[h]] * GEN[(i, r, h, t)]
            for i in I for r in R for h in H
            if data.valcap[ii[i], ri[r], ti[t]] and data.emit_rate[ii[i]] > 0
        )
        m.add_linear_constraint(lhs, poi.Leq, data.emit_cap[ti[t]])

    # -- eq_ramping: RAMPUP[i,r,h,t] >= GEN[i,r,h+1,t] - GEN[i,r,h,t]
    for i in disp_techs:
        for r in R:
            for t in T:
                if not data.valcap[ii[i], ri[r], ti[t]]:
                    continue
                for h in H[:-1]:
                    m.add_linear_constraint(
                        RAMPUP[(i, r, h, t)]
                        - GEN[(i, r, h_next[h], t)]
                        + GEN[(i, r, h, t)],
                        poi.Geq, 0.0,
                    )

    # -- eq_min_cf: sum_h hw[h]*GEN[i,r,h,t] >= min_cf[i]*CAP[i,r,t]*total_hw
    total_hw = float(data.hours_weight.sum())
    for i in I:
        mcf = data.min_cf[ii[i]]
        if mcf <= 0:
            continue
        for r in R:
            for t in T:
                if not data.valcap[ii[i], ri[r], ti[t]]:
                    continue
                lhs = poi.quicksum(
                    data.hours_weight[hi[h]] * GEN[(i, r, h, t)] for h in H
                ) - mcf * total_hw * CAP[(i, r, t)]
                m.add_linear_constraint(lhs, poi.Geq, 0.0)

    # Storage constraints
    for i in storage_techs:
        for r in R:
            for t in T:
                if not data.valcap[ii[i], ri[r], ti[t]]:
                    continue
                cap_var = CAP[(i, r, t)]
                for h in H:
                    # eq_soc_cap: SOC <= duration_h * CAP
                    m.add_linear_constraint(
                        SOC[(i, r, h, t)] - data.duration_h * cap_var,
                        poi.Leq, 0.0,
                    )
                    # eq_charge_cap: CHARGE <= CAP
                    m.add_linear_constraint(
                        CHARGE[(i, r, h, t)] - cap_var, poi.Leq, 0.0,
                    )
                    # eq_soc: SOC[h_next] = SOC[h] + eff*CHARGE[h] - GEN[h]
                    hn = h_next_wrap[h]
                    m.add_linear_constraint(
                        SOC[(i, r, hn, t)]
                        - SOC[(i, r, h, t)]
                        - data.charge_eff * CHARGE[(i, r, h, t)]
                        + GEN[(i, r, h, t)],
                        poi.Eq, 0.0,
                    )

    # -- Objective (scaled to avoid HiGHS 1.13 dual simplex ratio errors)
    OBJ_SCALE = 1e6
    obj = poi.ExprBuilder()
    for k, t in enumerate(T):
        pv = data.pvf[k]
        for i in I:
            cinv = data.cost_inv[ii[i]] / OBJ_SCALE
            cop  = data.cost_op[ii[i]]  / OBJ_SCALE
            sc   = data.startcost[ii[i]] / OBJ_SCALE
            for r in R:
                if not data.valcap[ii[i], ri[r], ti[t]]:
                    continue
                obj += pv * cinv * INV[(i, r, t)]
                hw = data.hours_weight
                for h in H:
                    obj += pv * cop * hw[hi[h]] * GEN[(i, r, h, t)]
                if not data.is_vre[ii[i]] and not data.is_storage[ii[i]]:
                    for h in H[:-1]:
                        obj += pv * sc * RAMPUP[(i, r, h, t)]
    m.set_objective(obj, poi.ObjectiveSense.Minimize)

    build_s = time.perf_counter() - t0
    if build_only:
        return float("nan"), build_s, 0.0

    # ------------------------------------------------------------------ solve
    t1 = time.perf_counter()
    m.optimize()
    solve_s = time.perf_counter() - t1

    status = m.get_model_attribute(ModelAttribute.TerminationStatus)
    if status != TerminationStatusCode.OPTIMAL:
        raise RuntimeError(f"{solver} did not find an optimal solution: {status.name}")

    obj_val = m.get_model_attribute(ModelAttribute.ObjectiveValue)
    return float(obj_val * OBJ_SCALE), build_s, solve_s


if __name__ == "__main__":
    import sys
    sys.path.insert(0, __file__.rsplit("\\", 1)[0])
    from data_generator import make_problem
    for size in ("small", "medium", "large", "xlarge"):
        data = make_problem(size)
        obj, b, s = solve(data)
        print(f"{size:6s}  obj={obj:>18,.0f}  build={b:.3f}s  solve={s:.3f}s")
