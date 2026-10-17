# ReEDS slice formulation

This is the math implemented identically in `build_pyoframe.py` and `build_pyomo.py`. Each equation keeps its ReEDS name and its GAMS orientation, written as (left side) − (right side) ⋚ 0. That way the solver dual, the derivative of the objective with respect to the right-hand side, carries the GAMS marginal sign.

The goal of the slice is **identical math across implementations**, not reproducing full ReEDS results.

## Switch profile (on the ReEDS side, when exporting)

Use the Pacific test case with these settings:

- **On:**
  - `GSw_AnnualCap=1`, so there is a CO2 dual. Pick a cap scenario that binds.
  - `GSw_GasCurve=2` (static gas prices), so `fuel_price` covers gas.
- **At their defaults:** `GSw_PRM_CapCredit=0` (stress-period formulation), `GSw_CSP=0` and `GSw_Upstream=0`.
- **Off:** retirements (`GSw_Retire=0`), upgrades, refurbishment, operating reserves, H2, hybrids, Canada, EFS flex, EVMC, load siting, interday storage, VSC and water.

## Indices and domains

| Symbol | Meaning |
|---|---|
| i, ii | technology (ii is the investing tech under `rsc_agg(i,ii)`) |
| v | vintage (`initv`, `newv`) |
| r, rr | zone |
| h, hh | timeslice in the current solve: representative (`h_rep`) ∪ stress (`h_stress`) |
| t | current solve year(s) (`tmodel`) |
| tt | investment year; past years are `tfix` |
| τ | `trtype` |
| b | `rscbin` |
| e, etype, eall | emission species, emission type, cap group |

Shorthand: VG = `valgen`, VC = `valcap`, VI = `valinv`, all restricted to `tmodel`.

## Variables

All variables are ≥ 0 except EMIT, which is free.

| Variable | Domain |
|---|---|
| LOAD(r,h,t) | r × h × tmodel |
| GEN(i,v,r,h,t) | VG × h |
| CAP(i,v,r,t) | VC |
| CAP_ENERGY(i,v,r,t) | VC ∩ battery |
| INV(i,v,r,t) | VI |
| INV_ENERGY(i,v,r,t) | VI ∩ battery |
| INV_RSC(i,v,r,b,t) | (VI ∩ rsc_i) ⋈ m_rscfeas, minus bins zero-fixed by eq. 9 |
| STORAGE_IN(i,v,r,h,t) | (VG ∩ storage_standalone) × h |
| STORAGE_LEVEL(i,v,r,h,t) | (VG ∩ storage ∖ storage_interday) × h |
| FLOW(r,rr,h,t,τ) | routes × h |
| CAPTRAN_ENERGY(r,rr,τ,t) | routes |
| CAPTRAN_PRM(r,rr,τ,t) | routes ∩ routes_prm |
| INVTRAN(r,rr,τ,t) | routes_inv (only with `--transmission-investment`; otherwise fixed at 0) |
| EMIT(etype,e,r,t) | etype × emit_modeled |

Prior-year decisions enter as constants from the state tables: INVˢ, INV_ENERGYˢ, INV_RSCˢ and INVTRANˢ for tt ∈ tfix. This replaces `.fx` fixing plus `holdfixed`.

## Equations

**1. eq_loadcon(r,h,t)**
LOAD = load_exog_static

**2. eq_supply_demand_balance(r,h,t)**
Σ_{(i,v): VG, r∈land} GEN
+ Σ_{(rr,τ): routes(rr,r,τ,t)} (1 − tranloss(rr,r,τ))·FLOW(rr,r,h,t,τ)
− Σ_{(rr,τ): routes(r,rr,τ,t)} FLOW(r,rr,h,t,τ)
− Σ_{(i,v): VC ∩ storage_standalone} STORAGE_IN
= LOAD

**3. eq_capacity_limit(i,v,r,h,t)**
Domain: VG, with i ∉ spur_techs ∪ storage_standalone ∪ (storage_hybrid ∖ csp) ∪ nondispatch.
κ(i,v,r,h,t)·CAP ≥ GEN

**4. eq_capacity_limit_nd(i,v,r,h,t)**
Domain: VG ∩ nondispatch.
κ·CAP = GEN

**5. eq_cap_init_noret(i,v,r,t)**
Domain: VC, v ∈ initv, i ∉ upgrade, not retiretech.
m_capacity_exog·degrade_init = CAP

**6. eq_cap_new_noret(i,v,r,t)**
Domain: VC, v ∈ newv, i ∉ upgrade, not retiretech.
Σ_{tt ∈ tmodel: inv_cond(i,v,r,t,tt), VI} degrade_new(i,tt,t)·INV(i,v,r,tt)
+ Σ_{tt ∈ tfix: inv_cond} degrade_new·INVˢ
− π(i,v,r,t)
= CAP

**7. eq_cap_energy_new_noret(i,v,r,t)**
Domain: VC ∩ battery.
Same as eq. 6 with INV_ENERGY and πᴱ, plus m_capacity_exog_energy, = CAP_ENERGY

**8. eq_rsc_inv_account(i,v,r,t)**
Domain: VI ∩ rsc_i.
Σ_b INV_RSC = INV

**9. eq_rsc_INVlim(r,i,b,t)**
Domain: rsc_i ∩ m_rscfeas ∩ m_rsc_con, |ρ| ≥ rhs_tolerance.
ρ(r,i,b,t) ≥ Σ_{(ii,v): rsc_agg(i,ii)} resourcescaler(ii)·INV_RSC(ii,v,r,b,t)

Here ρ = slice_rsc_cap − Σ_{tt∈tfix, tt≤t} Σ_{(ii,v): rsc_agg(i,ii)} resourcescaler(ii)·INV_RSCˢ.

When |ρ| < rhs_tolerance, the row is dropped and the matching INV_RSC(ii,·,r,b,t) are removed, exactly as `3_solve_oneyear.gms` does.

**10. eq_storage_capacity(i,v,r,h,t)**
Domain: VG ∩ storage_standalone ∖ evmc_storage.
σ·CAP ≥ GEN + STORAGE_IN

**11. eq_storage_duration(i,v,r,h,t)**
Domain: VG ∩ VC ∩ storage ∖ storage_interday.
δ(i,v,r)·CAP + CAP_ENERGY [battery only] ≥ STORAGE_LEVEL

**12. eq_storage_level(i,v,r,h,t)**
Σ_{hh: nexth(h,hh)} STORAGE_LEVEL(hh)
= STORAGE_LEVEL(h) + storage_eff(i,t)·hours_daily(h)·STORAGE_IN − hours_daily(h)·GEN

**13. eq_CAPTRAN_ENERGY(r,rr,τ,t)**
Domain: routes.
CAPTRAN_ENERGY = trancap_init_energy + Σ_{tt∈tfix, tt≤t} INVTRANˢ + INVTRAN

**14. eq_CAPTRAN_PRM(r,rr,τ,t)**
Domain: routes ∩ routes_prm.
CAPTRAN_PRM = trancap_init_prm + (1 − Sw_TransInvPRMderate)·(Σ INVTRANˢ + INVTRAN)

**15. eq_transmission_limit(r,rr,h,t,τ)**
(1+Δ(h,t))·CAPTRAN_ENERGY [h ∈ h_rep]
+ (1+Δ(h,t))·CAPTRAN_PRM [h ∈ h_stress, routes_prm]
≥ FLOW

On stress hours of routes outside routes_prm the left side is 0, so FLOW ≤ 0.

**16. eq_emit_accounting(etype,e,r,t)**
EMIT = Σ_{(i,v): VG} Σ_{h ∈ h_rep} hours(h)·emit_rate(etype,e,i,v,r,t)·GEN

**17. eq_annual_cap(eall,t)**
Domain: eall with Σ_tt emit_cap(eall,tt) ≠ 0.
emit_cap(eall,t) ≥ Σ_{e ∈ emit_capped, r} gwp(e)·EMIT("process",e,r,t)

**Objective**

min Z = cost_scale · Σ_t [ pvf_capital(t)·Z_inv(t) + pvf_onm(t)·Z_op(t) ]

where:

- **Z_inv** = Σ_VI cost_cap_fin_mult·cost_cap·INV
  + Σ_{VI∩battery} cost_cap_fin_mult·cost_cap_energy·INV_ENERGY
  + Σ_{(i,v,r,b): VI, rsc_i, m_rscfeas, ∉ spur} slice_rsc_cost(r,i,b)·rsc_fin_mult(i,r,t)·Σ_{ii: rsc_agg(i,ii)} INV_RSC(ii,v,r,b,t)
  [+ slice_trans_cost·INVTRAN]
- **Z_op** = Σ_{VG × h} hours(h)·(cost_vom + heat_rate·fuel_price)·GEN
  + Σ_VC cost_fom·CAP
  + Σ_{VC∩battery} cost_fom_energy·CAP_ENERGY

## Precomposed coefficients (computed in GAMS at export)

These are pure parameter algebra. Computing them in GAMS keeps the bake-off about the modeling language, not the data port.

```gams
* kappa: eq_capacity_limit / eq_capacity_limit_nd coefficient on CAP
slice_cap_coef(i,v,r,h,t)$[tmodel(t)$valgen(i,v,r,t)] =
    avail(i,r,h)$[dispatchtech(i)$(not hydro_d(i))] * derate_geo_vintage(i,v)
      * (1 + sum{szn, h_szn(h,szn) * seas_cap_frac_delta(i,v,r,szn,t)})
  + avail(i,r,h)$hydro_d(i) * sum{szn$h_szn(h,szn), cap_hyd_szn_adj(i,szn,r)}
      * (1 + hydro_capcredit_delta(i,t)$h_stress(h))
  + sum{c$i_c(i,c), m_cf(i,c,v,r,h,t)}$[not dispatchtech(i)] ;

* sigma: eq_storage_capacity
slice_stor_cap_coef(i,v,r,h,t)$[tmodel(t)$valgen(i,v,r,t)$storage_standalone(i)] =
    bcr(i) * avail(i,r,h) * (1 + sum{szn, h_szn(h,szn) * seas_cap_frac_delta(i,v,r,szn,t)}) ;

* delta: eq_storage_duration
slice_dur_coef(i,v,r) = storage_duration_m(i,v,r) * (1$CSP_Storage(i) + 1$psh(i) + bcr(i)$pvb(i)) ;

* pi: prescribed retirements of new vintages (eq_cap_new_noret); the energy analog uses
*     prescribed_retirements_energy
slice_prescr_ret(i,v,r,t)$tmodel(t) =
    sum{(tt,ttt)$[inv_cond(i,v,r,tt,ttt)$(tmodel(tt) or tfix(tt))$valcap(i,v,r,ttt)
                  $(tt.val>=ttt.val)$(t.val>=tt.val)],
        degrade_new(i,ttt,tt) * prescribed_retirements(i,v,r,tt,ttt) } ;

* gross supply-curve capacity (eq_rsc_INVlim before subtracting past use)
slice_rsc_cap(r,i,rscbin,t)$tmodel(t) =
    ( m_rsc_dat(r,i,rscbin,"cap")
      - sum{(ii,v,tt)$[tfirst(tt)$rsc_agg(i,ii)$exog_rsc(i)], capacity_exog_rsc(ii,v,r,rscbin,tt)} )
    * (1$[not rsc_capacity_scalar_i(i)] + rsc_capacity_scalar(i,r,t)$rsc_capacity_scalar_i(i))
    + hyd_add_upg_cap(r,i,rscbin,t)$(Sw_HydroCapEnerUpgradeType=1) ;

slice_rsc_cost(r,i,rscbin) = m_rsc_dat(r,i,rscbin,"cost") ;
```

The state tables are the `.l` levels of INV, INV_ENERGY, INV_RSC and INVTRAN for tfix years. Everything else in `contract.py` is an existing ReEDS symbol, exported as is.

Reporting adds tech subsets (`upv`, `wind`, `distpv`, `vre`, `psh`) and `ilr(i)`, the inverter loading ratio. ilr defaults to 1, as in `b_inputs.gms`. These are used only by `report.py` and do not enter the model.

## Conventions that keep the three implementations identical

- **Zeros:** GAMS never stores zeros, and `$param` means "nonzero". The loader drops zero values. A missing coefficient removes the term, but the row still exists.
- **Duals:** for ≥ rows, y ≥ 0; for ≤ rows, y ≤ 0; this is the GAMS marginal before reporting adjustments (÷ cost_scale, ÷ pvf_onm, ÷ hours). `kkt.py` verifies any dual vector against the model, so degenerate rows don't cause false failures.
- **Domains:** valgen ⊆ valcap is enforced by `contract.check`. Otherwise CAP would be uncosted inside eq. 3.

## What the slice leaves out

- Mingen, ramping and startup costs; growth and queue limits.
- State policies, RPS/CES, hydro energy budgets and the PRM capacity-credit formulation.
- Dropped and excess load (the slice assumes year ≥ Sw_StartMarkets).
- AC transmission supply-curve bins: INVTRAN uses a flat per-MW cost in the extension.
- The full objective: gas supply curves, transmission FOM, spur lines and penalties.

## Integer plant investment (`build_pyoframe_mip.py`)

The second pyoframe formulation keeps all 17 equations and the objective unchanged. It reuses `build_pyoframe.build` and adds one integer variable family and one linking equation.

| Symbol | Domain | Meaning |
|---|---|---|
| unit_size(i) | contract table `unit_size` | MW per unit. Techs listed here (or the subset passed as `--integer-techs`) are built in whole units; all others stay continuous. |
| N_UNITS(i,v,r,t) | VI restricted to those techs | Units built, integer ≥ 0 |

**18. eq_inv_units(i,v,r,t)**
INV(i,v,r,t) = unit_size(i) · N_UNITS(i,v,r,t)

In GAMS this would be:

```gams
integer variable N_UNITS(i,v,r,t) ;
eq_inv_units(i,v,r,t)$[valinv(i,v,r,t)$unit_size(i)$tmodel(t)]..
    INV(i,v,r,t) =e= unit_size(i) * N_UNITS(i,v,r,t) ;
solve ReEDSmodel minimizing z using mip ;
```

What stays continuous:
- The split of INV across supply-curve bins (eq. 8), so a 200 MW wind unit can draw from two bins.
- Battery energy capacity (INV_ENERGY).
- Dispatch and every other variable.

**Prices: fix and re-solve.** A MIP has no duals, so the energy, CO2 and capacity prices come from a second solve:
1. Solve the MIP. HiGHS stops at `mip_rel_gap` (default 1e-3).
2. Round N_UNITS, make it continuous, and fix it there (lower = upper bound).
3. Re-solve the LP and read the duals. They are the prices given the integer build decisions.

The fixed re-solve can improve on the MIP incumbent's dispatch, but it can never beat the MIP dual bound. `run_mip.py` checks both.

**Warm start.** `run_mip.py` passes HiGHS the LP investment rounded up to whole units as a MIP start (`warm_start`, turn off with `--no-warm-start`). Rounding up stays feasible because extra capacity never breaks a balance. It cut the all-tech 102k-row MIP from 694 s to 449 s; with only gas and batteries integer it took longer (1,016 s against 896 s) but reached a tighter gap. Rounding to the nearest unit gives a better start on the small case, but at 102k rows it left stress hours short and HiGHS discarded it.

The eq_inv_units dual after fixing is the marginal value of 1 MW more of that tech at the fixed unit counts. A negative value means more capacity would lower cost. `run_mip.py` writes it as `value_of_1MW_more_$` and `value_of_1unit_more_$` (divided by cost_scale, present value).

Two traps:
- **pyoframe returns 0.0 for duals read after a MIP solve, with no error.** `build_pyoframe_mip.results` refuses to run until the integers are fixed.
- **Fixed-integer prices drop when every new tech is integer.** Once all capacity is fixed, nothing can expand at the margin, so energy and CO2 prices fall to short-run operating cost. With wind and solar left continuous, they set the margin and prices stay near the LP's (see `run_mip.py` results in the README).

## PTDF network (`ptdf.py`)

The network layer replaces the zone-to-zone interface limits on AC routes (the AC rows of eq. 15, `eq_transmission_limit`) with physical line limits from a DC power flow. The 17 equations are otherwise unchanged. DC routes (LCC, B2B, VSC) keep their interface limits. `--keep-interface-limits` keeps the AC limits as well.

| Symbol | Domain | Meaning |
|---|---|---|
| ptdf_line(l,r,rr) | user line list | Physical AC line l from zone r to zone rr. Lines need not match routes. Default: one line per AC route pair. |
| ptdf_x(l) | | Series reactance, any consistent unit (default 1) |
| ptdf_limit(l), ptdf_limit_prm(l) | | MW limit in representative and stress hours. Default: the route's current interface capacity in each direction. |
| ptdf_ref(r) | one per AC island | User-defined reference (slack) zone. Default: the first zone of each island. |
| ptdf(l,r) | optional | A user-supplied PTDF matrix, used instead of the reactances |
| NETINJ(r,h,t) | network zones | Net AC export of zone r (free) |
| LINEFLOW(l,h,t) | lines | Flow on line l, positive from r to rr (free) |

**19. eq_ptdf_netinj(r,h,t)**
NETINJ = Σ_{(rr,τ AC)} FLOW(r,rr,h,t,τ) − Σ_{(rr,τ AC)} FLOW(rr,r,h,t,τ)

**20. eq_ptdf_flow(l,h,t)**
LINEFLOW(l) = Σ_r PTDF(l,r) · NETINJ(r)

**21. eq_ptdf_limit_fwd(l,h,t)**
limit_fwd(l,h,t) − LINEFLOW ≥ 0

**22. eq_ptdf_limit_rev(l,h,t)**
limit_rev(l,h,t) + LINEFLOW ≥ 0

Limits scale by (1 + trans_cap_delta(h,t)) as eq. 15 does, using the stress limit in stress hours.

**PTDF.** For each AC island with reference zone s:
- B = Aᵀ diag(1/x) A, where A is the line-zone incidence matrix (+1 at the from zone, −1 at the to zone).
- PTDF = diag(1/x) A₋ₛ (B₋ₛ,₋ₛ)⁻¹, with column s set to zero.

NETINJ counts FLOW at the sending end, so it sums to zero on each island. Line flows are therefore the same for any choice of reference zone. The reference changes the PTDF values and the meaning of the NETINJ duals, not the dispatch. The transport-model losses stay on FLOW in the energy balance; the PTDF itself is lossless.

**Angle formulation (`--formulation angle`).** This is the same network, written with voltage angles instead of a dense PTDF:
- eq_angle_flow(l,h,t): LINEFLOW(l) = (THETA(from) − THETA(to)) / x(l)
- eq_angle_kcl(r,h,t), r ≠ ref: NETINJ(r) = Σ_{l from r} LINEFLOW − Σ_{l to r} LINEFLOW
- THETA(ref) = 0, by leaving the reference zone out of THETA

It gives identical line flows and objective with far fewer nonzeros (each PTDF row has one term per zone in the island). It needs reactances; a user PTDF matrix works only with `ptdf`.

Limits of the layer:
- No transmission investment, because the PTDF would change with what is built.
- No PTDF-based loss allocation.
- No contingency (N−1) constraints yet. These would use the same layer with LODF-adjusted rows.
- An AC route whose ends sit in different AC islands is rejected; make it DC.
