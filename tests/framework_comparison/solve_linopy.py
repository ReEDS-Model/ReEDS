"""
linopy implementation of the ReEDS-representative LP test problem.

All constraint and variable names mirror the GAMS originals in
reeds/core/setup/c_model.gms and reeds/core/setup/d_objective.gms.

Key linopy patterns used:
- Variables: m.add_variables(lower=0, coords=..., mask=valcap_da)
  mask=valcap_da excludes inactive (i,r,t) combinations
- Constraints: m.add_constraints(lhs == rhs, name="eq_name", mask=...)
- cf is [i,r,h] (region-specific VRE profiles)
- RAMPUP uses h=H[:-1] as the starting hour; gen_next relabeled via
  .assign_coords so both sides share the same h coordinate labels
- SOC wrap-around: SOC.roll(h=-1, roll_coords=False) shifts data one
  step forward in h (so rolled[h=k] = original SOC[h=k+1]) with the
  last hour wrapping to h=0, enforcing cyclic energy balance
"""

from __future__ import annotations
import time
import numpy as np
import xarray as xr
import linopy

from data_generator import ProblemData


def solve(data: ProblemData, solver: str = "highs", build_only: bool = False) -> tuple[float, float, float]:
    R, I, H, T = data.regions, data.techs, data.hours, data.years
    nRoutes = len(data.routes)
    xp = data.as_xarray()

    valcap_da = xp["valcap"]  # [i, r, t] bool

    disp_techs    = [i for i in I if not data.is_vre[data.i_idx[i]]
                                  and not data.is_storage[data.i_idx[i]]]
    storage_techs = [i for i in I if data.is_storage[data.i_idx[i]]]

    # Net-flow incidence matrix [r x routes]
    flow_mat = np.zeros((len(R), nRoutes))
    for k, (r_from, r_to) in enumerate(data.routes):
        flow_mat[data.r_idx[r_to],   k] += (1 - data.tranloss)
        flow_mat[data.r_idx[r_from], k] -= 1.0
    flow_da = xr.DataArray(flow_mat, dims=["r", "route"],
                           coords={"r": R, "route": list(range(nRoutes))})

    # ------------------------------------------------------------------ build
    t0 = time.perf_counter()
    m = linopy.Model()

    GEN  = m.add_variables(lower=0,
                            coords=[("i",I),("r",R),("h",H),("t",T)],
                            name="GEN", mask=valcap_da)
    CAP  = m.add_variables(lower=0,
                            coords=[("i",I),("r",R),("t",T)],
                            name="CAP", mask=valcap_da)
    INV  = m.add_variables(lower=0,
                            coords=[("i",I),("r",R),("t",T)],
                            name="INV", mask=valcap_da)
    FLOW = m.add_variables(lower=0,
                            coords=[("route",list(range(nRoutes))),("h",H),("t",T)],
                            name="FLOW")

    # RAMPUP: indexed by starting hour h = H[:-1]
    rampup_mask = valcap_da.sel(i=disp_techs)       # [i_disp, r, t]
    RAMPUP = m.add_variables(lower=0,
                              coords=[("i",disp_techs),("r",R),("h",H[:-1]),("t",T)],
                              name="RAMPUP", mask=rampup_mask)

    # Storage: CHARGE and SOC (only for sizes with battery)
    if storage_techs:
        valcap_storage = valcap_da.sel(i=storage_techs)  # [i_s, r, t]
        CHARGE = m.add_variables(lower=0,
                                  coords=[("i",storage_techs),("r",R),("h",H),("t",T)],
                                  name="CHARGE", mask=valcap_storage)
        SOC    = m.add_variables(lower=0,
                                  coords=[("i",storage_techs),("r",R),("h",H),("t",T)],
                                  name="SOC",    mask=valcap_storage)

    # -- eq_cap_accum: CAP[i,r,t] = cap_init[i,r] + sum_{tt<=t} INV[i,r,tt]
    for k, yr in enumerate(T):
        past_inv = INV.sel(t=T[:k+1]).sum("t")
        m.add_constraints(
            CAP.sel(t=yr) - past_inv == xp["cap_init"],
            name=f"eq_cap_accum_{yr}", mask=valcap_da.sel(t=yr),
        )

    # -- eq_cap_limit: GEN[i,r,h,t] <= cf[i,r,h] * CAP[i,r,t]
    m.add_constraints(GEN <= xp["cf"] * CAP,
                      name="eq_cap_limit", mask=valcap_da)

    # -- eq_mingen: GEN >= minloadfrac * CAP  (dispatchable non-storage only)
    has_mingen = valcap_da & (xp["minloadfrac"] > 0) & ~xp["is_storage"]
    m.add_constraints(GEN >= xp["minloadfrac"] * CAP,
                      name="eq_mingen", mask=has_mingen)

    # -- eq_supply_demand_balance
    net_import = (flow_da * FLOW).sum("route")
    if storage_techs:
        lhs = GEN.sum("i") - CHARGE.sum("i") + net_import
    else:
        lhs = GEN.sum("i") + net_import
    m.add_constraints(lhs == xp["load"], name="eq_supply_demand_balance")

    # -- eq_reserve_margin: sum_i CAP[i,r,t] >= (1+prm) * peak_load[r,t]
    peak_load = xr.DataArray(data.load.max(axis=1),
                             dims=["r","t"], coords={"r":R,"t":T})
    m.add_constraints(
        CAP.sum("i") >= (1 + data.prm) * peak_load,
        name="eq_reserve_margin",
    )

    # -- eq_transmission_limit
    tcap = xr.DataArray([data.transcap[rt] for rt in data.routes],
                        dims=["route"], coords={"route": list(range(nRoutes))})
    m.add_constraints(FLOW <= tcap, name="eq_transmission_limit")

    # -- eq_emit_cap (pre-filter to emitting techs)
    emit_i = xp["emit_rate"].coords["i"].values[xp["emit_rate"].values > 0]
    emissions = (
        xp["emit_rate"].sel(i=emit_i) * xp["hours_weight"] * GEN.sel(i=emit_i)
    ).sum(["i", "r", "h"])
    m.add_constraints(emissions <= xp["emit_cap"], name="eq_emit_cap")

    # -- eq_ramping: RAMPUP[i,r,h,t] >= GEN[i,r,h+1,t] - GEN[i,r,h,t]
    # gen_next has h coords H[1:]; relabel to H[:-1] so both sides align
    gen_disp      = GEN.sel(i=disp_techs)
    gen_curr      = gen_disp.sel(h=H[:-1])
    gen_next      = gen_disp.sel(h=H[1:]).assign_coords({"h": H[:-1]})
    m.add_constraints(
        RAMPUP >= gen_next - gen_curr,
        name="eq_ramping", mask=rampup_mask,
    )

    # -- eq_min_cf: annual generation >= min_cf * CAP * total_hours
    total_hours = float(xp["hours_weight"].sum())
    gen_annual  = (xp["hours_weight"] * GEN).sum("h")   # [i, r, t]
    min_cf_mask = valcap_da & (xp["min_cf"] > 0)
    m.add_constraints(
        gen_annual >= xp["min_cf"] * CAP * total_hours,
        name="eq_min_cf", mask=min_cf_mask,
    )

    if storage_techs:
        cap_storage = CAP.sel(i=storage_techs)

        # -- eq_soc_cap: SOC[i,r,h,t] <= duration_h * CAP[i,r,t]
        m.add_constraints(
            SOC <= data.duration_h * cap_storage,
            name="eq_soc_cap", mask=valcap_storage,
        )

        # -- eq_charge_cap: CHARGE[i,r,h,t] <= CAP[i,r,t]
        m.add_constraints(
            CHARGE <= cap_storage,
            name="eq_charge_cap", mask=valcap_storage,
        )

        # -- eq_soc: SOC[h+1] = SOC[h] + eff*CHARGE[h] - GEN_storage[h]
        # roll(h=-1, roll_coords=False): shifted[h=k] = original[h=k+1], wrap at end
        soc_next = SOC.roll(h=-1, roll_coords=False)
        m.add_constraints(
            soc_next == SOC + data.charge_eff * CHARGE - GEN.sel(i=storage_techs),
            name="eq_soc", mask=valcap_storage,
        )

    # -- Objective
    obj = (xp["pvf"] * xp["cost_inv"] * INV).sum() \
        + (xp["pvf"] * xp["cost_op"] * xp["hours_weight"] * GEN).sum() \
        + (xp["pvf"] * xp["startcost"].sel(i=disp_techs) * RAMPUP).sum()
    m.add_objective(obj)

    build_s = time.perf_counter() - t0
    if build_only:
        return float("nan"), build_s, 0.0

    # ------------------------------------------------------------------ solve
    t1 = time.perf_counter()
    if solver == "highs":
        m.solve(solver, io_api="direct", output_flag=False, solver="ipm")
    else:
        m.solve(solver)
    solve_s = time.perf_counter() - t1

    return float(m.objective.value), build_s, solve_s


if __name__ == "__main__":
    import sys
    sys.path.insert(0, __file__.rsplit("\\", 1)[0])
    from data_generator import make_problem
    for size in ("small", "medium", "large", "xlarge"):
        data = make_problem(size)
        obj, b, s = solve(data)
        print(f"{size:6s}  obj={obj:>18,.0f}  build={b:.3f}s  solve={s:.3f}s")
