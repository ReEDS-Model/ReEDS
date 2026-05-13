# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "arco",
#   "numpy",
# ]
#
# [tool.uv.sources]
# arco = { git = "https://github.com/NatLabRockies/arco.git", rev = "main", subdirectory = "bindings/python" }
# ///

"""
Arco-Python implementation of the ReEDS-representative LP test problem.

All constraint and variable names mirror the GAMS originals in
reeds/core/setup/c_model.gms and reeds/core/setup/d_objective.gms.
"""

from __future__ import annotations

import time

import arco
import numpy as np

from data_generator import ProblemData


def solve(
    data: ProblemData,
    solver: str = "highs",
    build_only: bool = False,
) -> tuple[float, float, float]:
    if solver not in {"highs", "scip", "xpress"}:
        raise ValueError("solve_arco only supports solver='highs', solver='scip', or solver='xpress'")

    regions, techs, hours, years = data.regions, data.techs, data.hours, data.years
    region_index = data.r_idx
    total_hours_weight = float(np.sum(data.hours_weight))

    n_regions = len(regions)
    route_names = [f"{r_from}->{r_to}" for r_from, r_to in data.routes]
    transcap_vector = np.zeros(len(data.routes), dtype=float)
    net_flow_incidence = np.zeros((n_regions, len(data.routes)), dtype=float)
    for route_idx, (r_from, r_to) in enumerate(data.routes):
        from_idx = region_index[r_from]
        to_idx = region_index[r_to]
        transcap_vector[route_idx] = float(data.transcap[(r_from, r_to)])
        net_flow_incidence[to_idx, route_idx] += 1.0 - float(data.tranloss)
        net_flow_incidence[from_idx, route_idx] -= 1.0

    t0 = time.perf_counter()
    model = arco.Model()

    I = arco.IndexSet("i", members=techs)
    R = arco.IndexSet("r", members=regions)
    H = arco.IndexSet("h", members=hours)
    T = arco.IndexSet("t", members=years)
    H_ramp = H[:-1]
    L = arco.IndexSet("route", members=route_names)

    valcap = arco.param(data.valcap, I, R, T)
    is_vre = arco.param(data.is_vre, I)
    is_storage = arco.param(data.is_storage, I)
    is_dispatch = ~is_vre & ~is_storage
    storage_active = valcap & is_storage
    dispatch_active = valcap & is_dispatch

    cf = arco.param(data.cf, I, R, H)
    cap_init = arco.param(data.cap_init, I, R)
    load = arco.param(data.load, R, H, T)
    peak_load = arco.param(data.load.max(axis=1), R, T)
    minloadfrac = arco.param(data.minloadfrac, I)
    min_cf = arco.param(data.min_cf, I)
    emit_rate = arco.param(data.emit_rate, I)
    emit_cap = arco.param(data.emit_cap, T)
    hours_weight = arco.param(data.hours_weight, H)
    pvf = arco.param(data.pvf, T)
    cost_inv = arco.param(data.cost_inv, I)
    cost_op = arco.param(data.cost_op, I)
    startcost = arco.param(data.startcost, I)

    transcap = arco.param(transcap_vector, L)
    net_flow_coeff = arco.param(net_flow_incidence, R, L)

    cap = model.add_variables(
        I,
        R,
        T,
        bounds=arco.NonNegativeFloat,
        active=valcap,
        name="CAP",
    )
    inv = model.add_variables(
        I,
        R,
        T,
        bounds=arco.NonNegativeFloat,
        active=valcap,
        name="INV",
    )
    gen = model.add_variables(
        I,
        R,
        H,
        T,
        bounds=arco.NonNegativeFloat,
        active=valcap,
        name="GEN",
    )
    flow = model.add_variables(
        L,
        H,
        T,
        bounds=arco.Bounds(0, transcap),
        name="FLOW",
    )
    rampup = model.add_variables(
        I,
        R,
        H_ramp,
        T,
        bounds=arco.NonNegativeFloat,
        active=dispatch_active,
        name="RAMPUP",
    )
    charge = model.add_variables(
        I,
        R,
        H,
        T,
        bounds=arco.NonNegativeFloat,
        active=storage_active,
        name="CHARGE",
    )
    soc = model.add_variables(
        I,
        R,
        H,
        T,
        bounds=arco.NonNegativeFloat,
        active=storage_active,
        name="SOC",
    )

    model.add_constraints(
        cap == cap_init + np.cumsum(inv, axis=T),
        name="eq_cap_accum",
    )
    model.add_constraints(
        gen <= cf * cap,
        name="eq_cap_limit",
    )
    model.add_constraints(
        gen >= minloadfrac * cap,
        active=valcap & (minloadfrac > 0) & ~is_storage,
        name="eq_mingen",
    )

    net_flow = (net_flow_coeff * flow) @ L
    model.add_constraints(
        (gen @ I) + net_flow - (charge @ I) == load,
        name="eq_supply_demand_balance",
    )
    model.add_constraints(
        (cap @ I) >= (1.0 + float(data.prm)) * peak_load,
        name="eq_reserve_margin",
    )
    model.add_constraints(
        (emit_rate * hours_weight * gen) @ (I, R, H) <= emit_cap,
        name="eq_emit_cap",
    )
    model.add_constraints(
        rampup >= np.diff(gen, axis=H),
        active=dispatch_active,
        name="eq_ramping",
    )
    model.add_constraints(
        (hours_weight * gen) @ H >= min_cf * total_hours_weight * cap,
        active=valcap & (min_cf > 0),
        name="eq_min_cf",
    )
    model.add_constraints(
        soc <= float(data.duration_h) * cap,
        active=storage_active,
        name="eq_soc_cap",
    )
    model.add_constraints(
        charge <= cap,
        active=storage_active,
        name="eq_charge_cap",
    )
    model.add_constraints(
        np.roll(soc, -1, axis=H) == soc + float(data.charge_eff) * charge - gen,
        active=storage_active,
        name="eq_soc",
    )

    objective = (pvf * cost_inv * inv).sum()
    objective += (pvf * cost_op * hours_weight * gen).sum()
    objective += (pvf * startcost * rampup).sum()
    model.minimize(objective)

    build_s = time.perf_counter() - t0
    if build_only:
        return float("nan"), build_s, 0.0

    solver_options = {
        "highs": arco.HiGHS(
            log_to_console=False,
            parameters={"solver": "ipm", "arco.fingerprint": "false"},
        ),
        "scip": arco.Scip(log_to_console=False),
        "xpress": arco.Xpress(log_to_console=False),
    }

    t1 = time.perf_counter()
    result = model.solve(solver=solver_options[solver])
    solve_s = time.perf_counter() - t1

    if not result.is_optimal():
        raise RuntimeError(f"{solver} did not find an optimal solution: {result.status}")

    return float(result.objective_value), build_s, solve_s


if __name__ == "__main__":
    import sys

    sys.path.insert(0, __file__.rsplit("\\", 1)[0])
    from data_generator import make_problem

    for size in ("small", "medium", "large", "xlarge"):
        data = make_problem(size)
        obj, b, s = solve(data)
        print(f"{size:6s}  obj={obj:>18,.0f}  build={b:.3f}s  solve={s:.3f}s")
