# ReEDS slice: per-constraint comparison of GAMS, pyoframe and Pyomo

Oct 5, 2026 · exported from the claude.ai doc https://claude.ai/code/artifact/c66f0283-965f-4993-b76f-43e8c9966fca

## Summary

pyoframe and Pyomo build the same LP from all 17 slice constraints, and that LP follows the ReEDS GAMS equations term for term under the slice switch profile. pyoframe needs 49 lines of model code against Pyomo's 128, and builds the 378k-row case in 4.1 s against Pyomo's 37 s.

- **Same model in both tools.** Row counts match per constraint, objectives match to 1e-9, and each tool's solution satisfies the other's model. The cross-check and KKT gates pass at 2.8k and 102k rows.
- **Pyomo's time is mostly the handoff.** 29 s of its 37 s goes to passing rows to HiGHS, with both Pyomo HiGHS interfaces. Model construction alone takes 8.2 s, about 2× pyoframe.
- **Duals.** 7 of 17 constraints give identical duals in both tools. The other 10 differ on degenerate rows (3 to 6,478 rows each), where both tools' duals pass the KKT check.
- **Not yet compared numerically with GAMS.** The GAMS column below is a code comparison. The numerical checks ran pyoframe against Pyomo on synthetic data; a Pacific export from your ReEDS machine closes that gap.

## How to read the comparison

Each constraint shows the same equation three times: GAMS, then pyoframe, then Pyomo, followed by a short note on how each tool handles it.

| Item | What it is |
| --- | --- |
| GAMS code | `reeds/core/setup/c_model.gms` at ReEDS commit ea3bcbf (5 Oct 2026), comments removed and trimmed to the terms active in the slice. Terms switched off are listed under each block. |
| pyoframe code | `reeds_slice/build_pyoframe.py` (pyoframe 1.9.1). `P(df)` turns a coefficient table into a parameter; `U(...)` adds terms whose label sets differ, counting a missing term as zero. |
| Pyomo code | `reeds_slice/build_pyomo.py` (Pyomo 6.10.1). `coef_map` and `group` pre-index a table into Python dicts once, so each rule is a dictionary lookup. |
| `K`, `C`, `V` | Coefficient tables, constraint domains and variable domains, built once in polars by `prep.py` and shared by both tools. |
| Orientation | Both tools write (GAMS left side) − (GAMS right side) ≥, = or ≤ 0, so each dual has the GAMS marginal sign. |
| Precomposed terms | Pure parameter algebra (for example the availability factor κ on CAP) is computed in GAMS at export, so the Python code sees one coefficient where GAMS shows several. |
| Row counts | From the 102k-row synthetic case (40 zones, 12 representative days, 2 stress days, one solve year). |

GAMS stores no zeros, and a `$param` condition means "nonzero". The shared data layer keeps that rule: a missing coefficient removes a term, but the row itself still exists.

## Load and energy balance

These two equations set the energy price: the balance dual is the zonal marginal cost of energy in every timeslice.

### eq\_loadcon(r,h,t): load definition, 3,360 rows

```gams
* GAMS: c_model.gms line 350
eq_loadcon(r,h,t)$tmodel(t)..
    LOAD(r,h,t) =e= load_exog_static(r,h,t) ;
```

Switched off in the slice: Canada exports, EV charging load, EFS flexible load, H2 and DAC production load, H2 compressor load, flexibly sited load.

```python
# pyoframe
m.eq_loadcon = m.LOAD - P(K["load"]) == 0
```

```python
# Pyomo
load = coef_map(K["load"], ["r", "h", "t"])
m.eq_loadcon = pyo.Constraint(_idx(m, "eq_loadcon", C["eq_loadcon"]),
    rule=lambda m, r, h, t: LOAD[r, h, t] - load[r, h, t] == 0)
```

The load table is filled with zeros on the full (r,h,t) domain, because the GAMS row exists even where load is zero. pyoframe needs no domain argument here: the row set is the join of `LOAD` and the table.

### eq\_supply\_demand\_balance(r,h,t): energy balance, 3,360 rows

```gams
* GAMS: c_model.gms line 1400
eq_supply_demand_balance(r,h,t)$tmodel(t)..
    sum{(i,v)$[valgen(i,v,r,t)$land(r)], GEN(i,v,r,h,t) }
  + sum{(trtype,rr)$[routes(rr,r,trtype,t)$notvsc(trtype)],
        (1-tranloss(rr,r,trtype)) * FLOW(rr,r,h,t,trtype) }
  - sum{(trtype,rr)$[routes(r,rr,trtype,t)$notvsc(trtype)], FLOW(r,rr,h,t,trtype) }
  - sum{(i,v)$[valcap(i,v,r,t)$storage_standalone(i)], STORAGE_IN(i,v,r,h,t) }
  =e= LOAD(r,h,t) ;
```

Switched off: VSC converter flows, hybrid grid charging, pumped-hydro add-ons, and `DROPPED`/`EXCESS` (allowed only before `Sw_StartMarkets`).

```python
# pyoframe
gen = m.GEN.to_expr().within(K["bal_gen"]).sum_by("r", "h", "t")
imports = (P(K["bal_import"]) * m.FLOW).sum_by("rr", "h", "t").rename({"rr": "r"})
exports = m.FLOW.sum_by("r", "h", "t")
stor_in = m.STORAGE_IN.to_expr().within(K["bal_stor_in"]).sum_by("r", "h", "t")
supply = U(gen, imports, -1 * exports, -1 * stor_in)
m.eq_supply_demand_balance = supply.keep_extras() - m.LOAD.keep_extras() == 0
```

```python
# Pyomo
gen_rt = group(K["bal_gen"].select(["i", "v", "r", "t"]).unique(), ["r", "t"], ["i", "v"])
sin_rt = group(K["bal_stor_in"].select(["i", "v", "r", "t"]).unique(), ["r", "t"], ["i", "v"])
imp = group(K["bal_import"], ["rr", "t"], ["r", "trtype"], with_value=True)   # into rr
exp = group(K["bal_import"], ["r", "t"], ["rr", "trtype"])                     # out of r

def balance(m, r, h, t):
    return (
        sum(GEN[i, v, r, h, t] for (i, v) in gen_rt.get((r, t), ()))
        + sum(c * FLOW[rf, r, h, t, tr] for ((rf, tr), c) in imp.get((r, t), ()))
        - sum(FLOW[r, rt, h, t, tr] for (rt, tr) in exp.get((r, t), ()))
        - sum(SIN[i, v, r, h, t] for (i, v) in sin_rt.get((r, t), ()))
        - LOAD[r, h, t]
        == 0
    )

m.eq_supply_demand_balance = pyo.Constraint(
    _idx(m, "eq_supply_demand_balance", C["eq_supply_demand_balance"]), rule=balance)
```

Four sums over different index sets are where the tools differ most. pyoframe refuses to add expressions whose zones differ unless told how (`keep_extras`), which catches the missing-zone bugs GAMS fills with zeros silently. Pyomo behaves like GAMS here: `.get(key, ())` returns an empty sum. Imports need the zone index swapped: a `rename` in pyoframe, a dict keyed on the receiving zone in Pyomo.

## Dispatch limits

The capacity limit is the largest family in the model, 53,760 of 102,400 rows, so its build cost dominates both tools.

### eq\_capacity\_limit(i,v,r,h,t): dispatchable and VRE output limit, 53,760 rows

```gams
* GAMS: c_model.gms line 1187
eq_capacity_limit(i,v,r,h,t)$[tmodel(t)$valgen(i,v,r,t)$(not spur_techs(i))
    $(not storage_standalone(i))$(not storage_hybrid(i)$(not csp(i)))$(not nondispatch(i))]..
    avail(i,r,h)$[dispatchtech(i)$(not hydro_d(i))] * derate_geo_vintage(i,v)
      * (1 + sum{szn, h_szn(h,szn) * seas_cap_frac_delta(i,v,r,szn,t)}) * CAP(i,v,r,t)
  + avail(i,r,h)$hydro_d(i) * CAP(i,v,r,t) * sum{szn$h_szn(h,szn), cap_hyd_szn_adj(i,szn,r)}
      * (1 + hydro_capcredit_delta(i,t)$[h_stress(h)])
  + (sum{c$i_c(i,c), m_cf(i,c,v,r,h,t)} * CAP(i,v,r,t))$[not dispatchtech(i)]
  =g= GEN(i,v,r,h,t) ;
```

Switched off: capacity and energy upsizing (`INV_CAP_UP`, `INV_ENER_UP`), EV charging shapes, operating reserves, flexible CCS power. The three CAP coefficients are precomposed in GAMS into one factor κ(i,v,r,h,t).

```python
# pyoframe
m.eq_capacity_limit = (P(K["caplim"]) * m.CAP) - m.GEN.drop_extras() >= 0
```

```python
# Pyomo
cl = coef_map(K["caplim"], ["i", "v", "r", "h", "t"])
m.eq_capacity_limit = pyo.Constraint(
    _idx(m, "eq_capacity_limit", C["eq_capacity_limit"]),
    rule=lambda m, i, v, r, h, t: cl[i, v, r, h, t] * CAP[i, v, r, t] - GEN[i, v, r, h, t] >= 0)
```

In pyoframe the κ table defines the row set: joining it to the 4-index `CAP` broadcasts CAP over hours, as GAMS does. `GEN.drop_extras()` acts as the GAMS `$` filter, discarding `GEN` for storage and non-dispatchable techs. Pyomo writes the row set explicitly and reads κ from a dict.

### eq\_capacity\_limit\_nd(i,v,r,h,t): non-dispatchable output, 3,360 rows

```gams
* GAMS: c_model.gms line 1257
eq_capacity_limit_nd(i,v,r,h,t)$[tmodel(t)$valgen(i,v,r,t)$nondispatch(i)]..
    sum{c$i_c(i,c), m_cf(i,c,v,r,h,t)} * CAP(i,v,r,t) =e= GEN(i,v,r,h,t) ;
```

Switched off: operating reserves.

```python
# pyoframe
m.eq_capacity_limit_nd = (P(K["caplim_nd"]) * m.CAP) - m.GEN.drop_extras() == 0
```

```python
# Pyomo
cln = coef_map(K["caplim_nd"], ["i", "v", "r", "h", "t"])
m.eq_capacity_limit_nd = pyo.Constraint(
    _idx(m, "eq_capacity_limit_nd", C["eq_capacity_limit_nd"]),
    rule=lambda m, i, v, r, h, t: cln[i, v, r, h, t] * CAP[i, v, r, t] - GEN[i, v, r, h, t] == 0)
```

Same pattern as the dispatchable limit, with an equality. Only distributed PV and non-dispatchable hydro land here; without this row their generation would be unbounded.

## Capacity stock

These equations carry capacity from year to year. Their main translation change is how past years enter: GAMS sums investment over `tmodel` and `tfix` years and relies on `.fx` plus `holdfixed`, while both Python tools read past investment from a state table as a constant.

### eq\_cap\_init\_noret(i,v,r,t): existing capacity, 320 rows

```gams
* GAMS: c_model.gms line 585
eq_cap_init_noret(i,v,r,t)$[valcap(i,v,r,t)$tmodel(t)$initv(v)$(not upgrade(i))
                           $(not retiretech(i,v,r,t))$(not Sw_PCM)]..
    m_capacity_exog(i,v,r,t) * degrade_init(i,v,r,t) =e= CAP(i,v,r,t) ;
```

Switched off: capacity upsizing within existing vintages and upgrades (`Sw_Upgrades`).

```python
# pyoframe
m.eq_cap_init_noret = P(K["cap_init"]) - m.CAP.drop_extras() == 0
```

```python
# Pyomo
ci = coef_map(K["cap_init"], ["i", "v", "r", "t"])
m.eq_cap_init_noret = pyo.Constraint(
    _idx(m, "eq_cap_init_noret", C["eq_cap_init_noret"]),
    rule=lambda m, i, v, r, t: ci[i, v, r, t] - CAP[i, v, r, t] == 0)
```

The product `m_capacity_exog × degrade_init` is formed once in the shared data layer, so both tools see a single constant per row.

### eq\_cap\_new\_noret(i,v,r,t): new capacity from investment, 480 rows

```gams
* GAMS: c_model.gms line 693
eq_cap_new_noret(i,v,r,t)$[valcap(i,v,r,t)$tmodel(t)$newv(v)$(not upgrade(i))
                          $(not retiretech(i,v,r,t))$(not Sw_PCM)]..
    sum{tt$[inv_cond(i,v,r,t,tt)$(tmodel(tt) or tfix(tt))$valcap(i,v,r,tt)],
        degrade_new(i,tt,t) * INV(i,v,r,tt) }
  - sum{(tt,ttt)$[inv_cond(i,v,r,tt,ttt)$(tmodel(tt) or tfix(tt))$valcap(i,v,r,ttt)
                  $(tt.val>=ttt.val)$(t.val>=tt.val)],
        degrade_new(i,ttt,tt) * prescribed_retirements(i,v,r,tt,ttt) }
  =e= CAP(i,v,r,t) ;
```

Switched off: refurbishment (`INV_REFURB`), upsizing, upgrades. The prescribed-retirement double sum is precomposed in GAMS as `slice_prescr_ret`.

```python
# pyoframe
inv_new = (P(K["cap_new_inv"]) * m.INV.rename({"t": "tt"})).sum_by(*V4)
lhs = U(inv_new, P(K["cap_new_const"]))
m.eq_cap_new_noret = lhs - m.CAP.drop_extras() == 0
```

```python
# Pyomo (stock_rule is shared with the battery energy equation)
def stock_rule(var, inv_var, inv_tab, const_tab):
    terms = group(inv_tab, ["i", "v", "r", "t"], ["tt"], with_value=True)
    const = coef_map(const_tab, ["i", "v", "r", "t"])

    def rule(m, i, v, r, t):
        return (sum(c * inv_var[i, v, r, tt] for ((tt,), c) in terms.get((i, v, r, t), ()))
                + const[i, v, r, t] - var[i, v, r, t] == 0)
    return rule

m.eq_cap_new_noret = pyo.Constraint(
    _idx(m, "eq_cap_new_noret", C["eq_cap_new_noret"]),
    rule=stock_rule(CAP, m.INV, K["cap_new_inv"], K["cap_new_const"]))
```

The `tt` sum is a join on the `inv_cond` table in pyoframe: rename `INV`'s year to `tt`, multiply by `degrade_new`, and sum back to the row index. Pyomo uses a dict from row to its list of (tt, coefficient) pairs. Both are exact; pyoframe's version reads closer to the GAMS sum.

### eq\_cap\_energy\_new\_noret(i,v,r,t): battery energy capacity, 80 rows

```gams
* GAMS: c_model.gms line 730
eq_cap_energy_new_noret(i,v,r,t)$[valcap(i,v,r,t)$tmodel(t)$battery(i)$(not Sw_PCM)]..
    sum{tt$[inv_cond(i,v,r,t,tt)$(tmodel(tt) or tfix(tt))$valcap(i,v,r,tt)],
        degrade_new(i,tt,t) * INV_ENERGY(i,v,r,tt) }
  - sum{(tt,ttt)$[inv_cond(i,v,r,tt,ttt)$(tmodel(tt) or tfix(tt))$valcap(i,v,r,ttt)
                  $(tt.val>=ttt.val)$(t.val>=tt.val)],
        degrade_new(i,ttt,tt) * prescribed_retirements_energy(i,v,r,tt,ttt) }
  + m_capacity_exog_energy(i,v,r,t)
  =e= CAP_ENERGY(i,v,r,t) ;
```

Nothing switched off: this is the full GAMS equation.

```python
# pyoframe
inv_e = (P(K["cap_energy_inv"]) * m.INV_ENERGY.rename({"t": "tt"})).sum_by(*V4)
lhs_e = U(inv_e, P(K["cap_energy_const"]))
m.eq_cap_energy_new_noret = lhs_e.keep_extras() - m.CAP_ENERGY.keep_extras() == 0
```

```python
# Pyomo
m.eq_cap_energy_new_noret = pyo.Constraint(
    _idx(m, "eq_cap_energy_new_noret", C["eq_cap_energy_new_noret"]),
    rule=stock_rule(m.CAP_ENERGY, m.INV_ENERGY, K["cap_energy_inv"], K["cap_energy_const"]))
```

Unlike `eq_cap_new_noret`, the domain has no `newv` filter, so existing battery vintages get rows with no investment term. pyoframe needs `keep_extras` on both sides to keep those rows; Pyomo needs nothing extra.

## Resource supply curves

These equations split wind and solar investment into supply-curve bins and cap each bin. The bin limit also carries a numerical safeguard from the GAMS solve script that both Python versions had to reproduce.

### eq\_rsc\_inv\_account(i,v,r,t): investment equals the sum over bins, 120 rows

```gams
* GAMS: c_model.gms line 1008
eq_rsc_inv_account(i,v,r,t)$[tmodel(t)$valinv(i,v,r,t)$rsc_i(i)$(not Sw_PCM)]..
    sum{rscbin$m_rscfeas(r,i,rscbin), INV_RSC(i,v,r,rscbin,t) } =e= INV(i,v,r,t) ;
```

Nothing switched off.

```python
# pyoframe
inv_rsc_sum = m.INV_RSC.sum_by(*V4)
inv_rsc_rows = m.INV.to_expr().within(C["eq_rsc_inv_account"])
m.eq_rsc_inv_account = inv_rsc_sum.keep_extras() - inv_rsc_rows.keep_extras() == 0
```

```python
# Pyomo
bins = group(V["INV_RSC"], ["i", "v", "r", "t"], ["rscbin"])
m.eq_rsc_inv_account = pyo.Constraint(
    _idx(m, "eq_rsc_inv_account", C["eq_rsc_inv_account"]),
    rule=lambda m, i, v, r, t: sum(m.INV_RSC[i, v, r, b, t] for (b,) in bins.get((i, v, r, t), ()))
    - m.INV[i, v, r, t] == 0)
```

`INV.within(...)` restricts `INV` to supply-curve techs, the pyoframe form of `$rsc_i(i)`. `keep_extras` keeps rows where every bin was removed by the flag below, which then force `INV` to zero, as in GAMS.

### eq\_rsc\_INVlim(r,i,rscbin,t): bin capacity limit, 359 rows

```gams
* GAMS: c_model.gms line 1024
eq_rsc_INVlim(r,i,rscbin,t)$[tmodel(t)$rsc_i(i)$m_rscfeas(r,i,rscbin)$m_rsc_con(r,i)
                            $(not flag_eq_rsc_INVlim(r,i,rscbin,t))$(not Sw_PCM)]..
    (m_rsc_dat(r,i,rscbin,"cap")
     - sum{(ii,v,tt)$[tfirst(tt)$rsc_agg(i,ii)$exog_rsc(i)], capacity_exog_rsc(ii,v,r,rscbin,tt)})
      * (1$[not rsc_capacity_scalar_i(i)] + rsc_capacity_scalar(i,r,t)$rsc_capacity_scalar_i(i))
  + hyd_add_upg_cap(r,i,rscbin,t)$(Sw_HydroCapEnerUpgradeType=1)
  =g=
    sum{(ii,v,tt)$[valinv(ii,v,r,tt)$(yeart(tt) <= yeart(t))$rsc_agg(i,ii)],
        INV_RSC(ii,v,r,rscbin,tt) * resourcescaler(ii) } ;
```

Nothing switched off. The left side is precomposed in GAMS as `slice_rsc_cap`. In `3_solve_oneyear.gms`, ReEDS also drops the row and fixes the matching `INV_RSC` to zero when the bin's remaining capacity is within `rhs_tolerance` of zero; the shared data layer does the same.

```python
# pyoframe
use = (P(K["rsc_lim_use"]) * m.INV_RSC.rename({"i": "ii"})).sum_by("r", "i", "rscbin", "t")
m.eq_rsc_INVlim = P(K["rsc_lim_rhs"]).keep_extras() - use.keep_extras() >= 0
```

```python
# Pyomo
rhs = coef_map(K["rsc_lim_rhs"], ["r", "i", "rscbin", "t"])
use = group(K["rsc_lim_use"], ["r", "i", "rscbin", "t"], ["ii", "v"], with_value=True)
m.eq_rsc_INVlim = pyo.Constraint(
    _idx(m, "eq_rsc_INVlim", C["eq_rsc_INVlim"]),
    rule=lambda m, r, i, b, t: rhs[r, i, b, t]
    - sum(c * m.INV_RSC[ii, v, r, b, t] for ((ii, v), c) in use.get((r, i, b, t), ())) >= 0)
```

The `rsc_agg(i,ii)` mapping is a rename plus a join in pyoframe: the investing tech becomes `ii`, and the coefficient table maps it to the numeraire tech `i`. Past years' investment (`tt` in `tfix`) is subtracted on the right-hand side in the data layer instead of appearing as fixed variables.

## Storage

Storage brings the one time-shifted index in the slice, the next-timeslice link `nexth`, and the biggest gap in Pyomo handoff time.

### eq\_storage\_capacity(i,v,r,h,t): charge plus discharge within power capacity, 10,080 rows

```gams
* GAMS: c_model.gms line 3001
eq_storage_capacity(i,v,r,h,t)$[valgen(i,v,r,t)$storage_standalone(i)$(not evmc_storage(i))$tmodel(t)]..
    (CAP(i,v,r,t) * bcr(i) * avail(i,r,h)
       * (1 + sum{szn, h_szn(h,szn) * seas_cap_frac_delta(i,v,r,szn,t)}))$valcap(i,v,r,t)
  =g= GEN(i,v,r,h,t) + STORAGE_IN(i,v,r,h,t) ;
```

Switched off: EV storage charge and discharge fractions, PV-plus-battery hybrid terms, operating reserves. The CAP coefficient is precomposed as σ.

```python
# pyoframe
m.eq_storage_capacity = (
    (P(K["stor_cap"]) * m.CAP) - m.GEN.drop_extras() - m.STORAGE_IN.drop_extras() >= 0
)
```

```python
# Pyomo
sc = coef_map(K["stor_cap"], ["i", "v", "r", "h", "t"])
m.eq_storage_capacity = pyo.Constraint(
    _idx(m, "eq_storage_capacity", C["eq_storage_capacity"]),
    rule=lambda m, i, v, r, h, t: sc[i, v, r, h, t] * CAP[i, v, r, t]
    - GEN[i, v, r, h, t] - SIN[i, v, r, h, t] >= 0)
```

Same pattern as the capacity limit: σ defines the rows, and `drop_extras` filters `GEN` and `STORAGE_IN` to storage techs.

### eq\_storage\_duration(i,v,r,h,t): state of charge within energy capacity, 10,080 rows

```gams
* GAMS: c_model.gms line 3143
eq_storage_duration(i,v,r,h,t)$[valgen(i,v,r,t)$valcap(i,v,r,t)$storage(i)$tmodel(t)
                               $(not storage_interday(i))]..
    storage_duration_m(i,v,r) * CAP(i,v,r,t) * (1$CSP_Storage(i) + 1$psh(i) + bcr(i)$pvb(i))
  + CAP_ENERGY(i,v,r,t)$battery(i)
  =g= STORAGE_LEVEL(i,v,r,h,t) ;
```

Switched off: EV storage energy hours. The duration coefficient is precomposed as δ(i,v,r).

```python
# pyoframe
lhs_d = U(P(K["stor_dur_cap"]) * m.CAP, P(K["stor_dur_energy"]) * m.CAP_ENERGY)
m.eq_storage_duration = lhs_d.keep_extras() - m.STORAGE_LEVEL.keep_extras() >= 0
```

```python
# Pyomo
dcap = coef_map(K["stor_dur_cap"], ["i", "v", "r", "h", "t"])
dene = coef_map(K["stor_dur_energy"], ["i", "v", "r", "h", "t"])

def duration(m, i, v, r, h, t):
    k = (i, v, r, h, t)
    lhs = 0
    if k in dcap:
        lhs = lhs + dcap[k] * CAP[i, v, r, t]
    if k in dene:
        lhs = lhs + dene[k] * m.CAP_ENERGY[i, v, r, t]
    return lhs - LVL[k] >= 0

m.eq_storage_duration = pyo.Constraint(
    _idx(m, "eq_storage_duration", C["eq_storage_duration"]), rule=duration)
```

The two left-side terms cover different techs: pumped hydro through δ × CAP, batteries through `CAP_ENERGY`. pyoframe carries both coefficients on the full hourly row index so that the 4-index capacity variables broadcast over hours; GAMS does that implicitly. Pyomo branches per row. This family also takes the longest Pyomo handoff (scorecard), because it is the first to register `STORAGE_LEVEL` with HiGHS.

### eq\_storage\_level(i,v,r,h,t): state-of-charge balance, 10,080 rows

```gams
* GAMS: c_model.gms line 3044
eq_storage_level(i,v,r,h,t)$[valgen(i,v,r,t)$storage(i)$tmodel(t)]..
    sum{(hh)$[nexth(h,hh)], STORAGE_LEVEL(i,v,r,hh,t)}$(not storage_interday(i))
  =e=
    STORAGE_LEVEL(i,v,r,h,t)$(not storage_interday(i))
  + storage_eff(i,t) * hours_daily(h) * STORAGE_IN(i,v,r,h,t)$storage_standalone(i)
  - hours_daily(h) * GEN(i,v,r,h,t)$[not storage_hybrid(i)$(not csp(i))] ;
```

Switched off: interday storage dispatch, CSP thermal storage, pumped-hydro add-ons, hybrids, and the energy cost of regulation reserves.

```python
# pyoframe
nxt = m.STORAGE_LEVEL.rename({"h": "hh"}).map(K["nexth"])
charge = P(K["stor_lvl_in"]) * m.STORAGE_IN
discharge = P(K["stor_lvl_gen"]) * m.GEN.to_expr().within(C["eq_storage_level"])
rhs = U(m.STORAGE_LEVEL.to_expr(), charge, -1 * discharge)
m.eq_storage_level = nxt.keep_extras() - rhs.keep_extras() == 0
```

```python
# Pyomo
nxt = group(K["nexth"], ["h"], ["hh"])
eff = coef_map(K["stor_lvl_in"], ["i", "h", "t"])
hd = coef_map(K["stor_lvl_gen"], ["h"])
sin_set = set(rows(V["STORAGE_IN"]))

def level(m, i, v, r, h, t):
    k = (i, v, r, h, t)
    charge = eff.get((i, h, t), 0.0) * SIN[k] if k in sin_set and (i, h, t) in eff else 0
    discharge = hd[(h,)] * GEN[k] if (h,) in hd else 0
    return (sum(LVL[i, v, r, hh, t] for (hh,) in nxt.get((h,), ()))
            - (LVL[k] + charge - discharge) == 0)

m.eq_storage_level = pyo.Constraint(_idx(m, "eq_storage_level", C["eq_storage_level"]), rule=level)
```

`nexth` wraps within each representative day, not across the whole year, so pyoframe's built-in `.next("h", wrap_around=True)` would link the wrong timeslices. Both versions use the exported `nexth` table instead: a `rename` plus `map` in pyoframe, a dict in Pyomo.

## Transmission

Two accounting equations set interface capacity for energy and for stress periods, and one limit applies the right capacity in each timeslice. In the base slice, new transmission (`INVTRAN`) is fixed at zero; `--transmission-investment` turns it on, and the code below shows that branch.

### eq\_CAPTRAN\_ENERGY(r,rr,trtype,t): energy-trading capacity, 80 rows

```gams
* GAMS: c_model.gms line 1907
eq_CAPTRAN_ENERGY(r,rr,trtype,t)$[routes(r,rr,trtype,t)$tmodel(t)$(not Sw_PCM)]..
    CAPTRAN_ENERGY(r,rr,trtype,t) =e= trancap_init_energy(r,rr,trtype)
  + sum{tt$[(yeart(tt) <= yeart(t))$(tmodel(tt) or tfix(tt))$routes_inv(r,rr,trtype,tt)],
        INVTRAN(r,rr,trtype,tt) } ;
```

Nothing switched off.

```python
# pyoframe
inv_tran = m.INVTRAN.to_expr()
m.eq_CAPTRAN_ENERGY = m.CAPTRAN_ENERGY - U(P(K["captran_e_const"]), inv_tran) == 0
```

```python
# Pyomo (ce, inv_tran, inv_set shared with eq_CAPTRAN_PRM)
ce = coef_map(K["captran_e_const"], ["r", "rr", "trtype", "t"])
inv_tran = getattr(m, "INVTRAN", None)
inv_set = set(rows(V["INVTRAN"])) if inv_tran is not None else set()
m.eq_CAPTRAN_ENERGY = pyo.Constraint(
    _idx(m, "eq_CAPTRAN_ENERGY", C["eq_CAPTRAN_ENERGY"]),
    rule=lambda m, r, rr, tr, t: m.CAPTRAN_ENERGY[r, rr, tr, t]
    - (ce[r, rr, tr, t] + (inv_tran[r, rr, tr, t] if (r, rr, tr, t) in inv_set else 0)) == 0)
```

The constant holds initial capacity plus all past-year investment. The year comparison `yeart(tt) <= yeart(t)` becomes a filter on the state table in the data layer.

### eq\_CAPTRAN\_PRM(r,rr,trtype,t): stress-period capacity, 80 rows

```gams
* GAMS: c_model.gms line 1932
eq_CAPTRAN_PRM(r,rr,trtype,t)$[routes(r,rr,trtype,t)$routes_prm(r,rr)$tmodel(t)$(not Sw_PCM)]..
    CAPTRAN_PRM(r,rr,trtype,t) =e= trancap_init_prm(r,rr,trtype)
  + sum{tt$[(yeart(tt) <= yeart(t))$(tmodel(tt) or tfix(tt))$routes_inv(r,rr,trtype,tt)],
        INVTRAN(r,rr,trtype,tt) * (1 - Sw_TransInvPRMderate) } ;
```

Nothing switched off.

```python
# pyoframe
m.eq_CAPTRAN_PRM = (
    m.CAPTRAN_PRM
    - U(P(K["captran_p_const"]), K["captran_p_inv_mult"] * inv_tran.within(V["CAPTRAN_PRM"]))
    == 0
)
```

```python
# Pyomo
cp = coef_map(K["captran_p_const"], ["r", "rr", "trtype", "t"])
mult = K["captran_p_inv_mult"]
m.eq_CAPTRAN_PRM = pyo.Constraint(
    _idx(m, "eq_CAPTRAN_PRM", C["eq_CAPTRAN_PRM"]),
    rule=lambda m, r, rr, tr, t: m.CAPTRAN_PRM[r, rr, tr, t]
    - (cp[r, rr, tr, t] + (mult * inv_tran[r, rr, tr, t] if (r, rr, tr, t) in inv_set else 0)) == 0)
```

`inv_tran.within(V["CAPTRAN_PRM"])` is the pyoframe form of `$routes_prm(r,rr)`. Both tools apply the derate as a scalar.

### eq\_transmission\_limit(r,rr,h,t,trtype): flow limit, 6,720 rows

```gams
* GAMS: c_model.gms line 2015
eq_transmission_limit(r,rr,h,t,trtype)$[tmodel(t)$routes(r,rr,trtype,t)]..
    (CAPTRAN_ENERGY(r,rr,trtype,t) * (1 + trans_cap_delta(h,t)))$h_rep(h)
  + (CAPTRAN_PRM(r,rr,trtype,t) * (1 + trans_cap_delta(h,t)))$[h_stress(h)$routes_prm(r,rr)]
  =g= FLOW(r,rr,h,t,trtype) ;
```

Switched off: operating-reserve flows.

```python
# pyoframe
cap_rep = P(K["tl_rep"]) * m.CAPTRAN_ENERGY
cap_str = P(K["tl_stress"]) * m.CAPTRAN_PRM
lhs_t = U(cap_rep, cap_str)
m.eq_transmission_limit = lhs_t.keep_extras() - m.FLOW.keep_extras() >= 0
```

```python
# Pyomo
rep = coef_map(K["tl_rep"], ["h", "t"])
strs = coef_map(K["tl_stress"], ["h", "t"])
prm_set = set(rows(V["CAPTRAN_PRM"]))

def tran_limit(m, r, rr, h, t, tr):
    k4 = (r, rr, tr, t)
    lhs = 0
    if (h, t) in rep:
        lhs = lhs + rep[h, t] * m.CAPTRAN_ENERGY[k4]
    if (h, t) in strs and k4 in prm_set:
        lhs = lhs + strs[h, t] * m.CAPTRAN_PRM[k4]
    return lhs - FLOW[r, rr, h, t, tr] >= 0

m.eq_transmission_limit = pyo.Constraint(
    _idx(m, "eq_transmission_limit", C["eq_transmission_limit"]), rule=tran_limit)
```

The `$h_rep(h)` and `$h_stress(h)` conditions pick which capacity variable applies in each hour. pyoframe does it with two coefficient tables that exist only on representative or stress hours, so the join itself selects the variable. Pyomo uses two `if` branches. Stress hours on routes outside `routes_prm` keep a row with no capacity, which holds that flow at zero, as GAMS does.

## Emissions

Emissions accounting has few rows but long sums, and the cap supplies the CO2 price. Both tools give identical duals for both equations.

### eq\_emit\_accounting(etype,e,r,t): emissions by zone, 80 rows

```gams
* GAMS: c_model.gms line 2370
eq_emit_accounting(etype,e,r,t)$[emit_modeled(e,r,t)$tmodel(t)]..
    EMIT(etype,e,r,t) =e=
    sum{(i,v,h)$[valgen(i,v,r,t)$h_rep(h)],
        hours(h) * emit_rate(etype,e,i,v,r,t) * GEN(i,v,r,h,t) } ;
```

Switched off: flexible CCS power, production emissions (H2, DAC), CCS bypass and storage credits.

```python
# pyoframe
gen_mwh = (P(K["emit_hours"]) * m.GEN).sum_by(*V4)
emis = (P(K["emit_rate"]) * gen_mwh).sum_by("etype", "e", "r", "t")
m.eq_emit_accounting = m.EMIT.keep_extras() - emis.keep_extras() == 0
```

```python
# Pyomo
hrs = coef_map(K["emit_hours"], ["h"])
rate = group(K["emit_rate"], ["etype", "e", "r", "t"], ["i", "v"], with_value=True)
h_rep = [h for (h,) in hrs]
gen_set = set(rows(V["GEN"]))

def emit(m, et, e, r, t):
    return m.EMIT[et, e, r, t] - sum(
        c * hrs[(h,)] * GEN[i, v, r, h, t]
        for ((i, v), c) in rate.get((et, e, r, t), ())
        for h in h_rep if (i, v, r, h, t) in gen_set
    ) == 0

m.eq_emit_accounting = pyo.Constraint(_idx(m, "eq_emit_accounting", C["eq_emit_accounting"]), rule=emit)
```

pyoframe splits the triple sum in two steps: hours × GEN summed to annual MWh per plant, then × emission rate summed to the zone. That avoids building the 6-index product. The Pyomo rule loops over plants and representative hours per row, which makes it Pyomo's slowest family to construct relative to pyoframe (1.1 s against 0.2 s at 378k rows).

### eq\_annual\_cap(eall,t): CO2 cap, 1 row

```gams
* GAMS: c_model.gms line 2493
eq_annual_cap(eall,t)$[sum{tt, emit_cap(eall,tt)}$tmodel(t)$(Sw_AnnualCap>0)]..
    emit_cap(eall,t) =g=
    sum{(e,r)$emit_capped(e), EMIT("process",e,r,t) * gwp(e) } ;
```

Switched off: upstream emissions (`Sw_Upstream = 0`).

```python
# pyoframe
if C["eq_annual_cap"].height:
    proc = m.EMIT.to_expr().filter(pl.col("etype") == "process")
    capped = (P(K["annual_cap_gwp"]) * proc).sum_by("eall", "t")
    m.eq_annual_cap = P(K["annual_cap_rhs"]).keep_extras() - capped.keep_extras() >= 0
```

```python
# Pyomo
if C["eq_annual_cap"].height:
    cap = coef_map(K["annual_cap_rhs"], ["eall", "t"])
    gwp = group(K["annual_cap_gwp"], ["eall"], ["e"], with_value=True)
    emit_by_et = group(V["EMIT"].filter(pl.col("etype") == "process"), ["e", "t"], ["r"])
    m.eq_annual_cap = pyo.Constraint(
        _idx(m, "eq_annual_cap", C["eq_annual_cap"]),
        rule=lambda m, ea, t: cap[ea, t] - sum(
            g * m.EMIT["process", e, r, t]
            for ((e,), g) in gwp.get((ea,), ()) for (r,) in emit_by_et.get((e, t), ())) >= 0)
```

The domain condition `sum{tt, emit_cap(eall,tt)}` keeps the row when a cap exists in any year, even if this year's cap is zero; the data layer computes it once. The literal index `"process"` is a polars filter in pyoframe and a plain index in Pyomo. The dual gives `co2_price` after the ReEDS conversion (÷ `cost_scale`, ÷ `pvf_onm`): $91.29 per metric ton in the 102k-row case, the same in both tools.

## Objective function

GAMS splits the objective into three equations with helper variables `Z_inv(t)` and `Z_op(t)`. Both Python versions substitute those away and minimize one sum, so the objective-row duals in GAMS have no counterpart in the slice.

```gams
* GAMS: d_objective.gms, slice terms only
eq_ObjFn.. Z =e= cost_scale * sum{t$tmodel(t), Z_inv(t) + Z_op(t) } ;

eq_ObjFn_inv(t)$tmodel(t).. Z_inv(t) =e= pvf_capital(t) * (
    sum{(i,v,r)$valinv(i,v,r,t), cost_cap_fin_mult(i,r,t) * cost_cap(i,t) * INV(i,v,r,t) }
  + sum{(i,v,r)$[valinv(i,v,r,t)$battery(i)],
        cost_cap_fin_mult(i,r,t) * cost_cap_energy(i,t) * INV_ENERGY(i,v,r,t) }
  + sum{(i,v,r,rscbin)$[m_rscfeas(r,i,rscbin)$valinv(i,v,r,t)$rsc_i(i)$(not spur_techs(i))],
        m_rsc_dat(r,i,rscbin,"cost") * rsc_fin_mult(i,r,t)
        * sum{ii$rsc_agg(i,ii), INV_RSC(ii,v,r,rscbin,t) } } ) ;

eq_Objfn_op(t)$tmodel(t).. Z_op(t) =e= pvf_onm(t) * (
    sum{(i,v,r,h)$[valgen(i,v,r,t)$cost_vom(i,v,r,t)], hours(h) * cost_vom(i,v,r,t) * GEN(i,v,r,h,t) }
  + sum{(i,v,r)$valcap(i,v,r,t), cost_fom(i,v,r,t) * CAP(i,v,r,t) }
  + sum{(i,v,r)$[valcap(i,v,r,t)$battery(i)], cost_fom_energy(i,v,r,t) * CAP_ENERGY(i,v,r,t) }
  + sum{(i,v,r,h)$[valgen(i,v,r,t)$heat_rate(i,v,r,t)$(not gas(i))$(not bio(i))$(not cofire(i))],
        hours(h) * heat_rate(i,v,r,t) * fuel_price(i,r,t) * GEN(i,v,r,h,t) }
  + sum{(i,v,r,h)$[valgen(i,v,r,t)$gas(i)$heat_rate(i,v,r,t)$(Sw_GasCurve = 2)],
        hours(h) * heat_rate(i,v,r,t) * fuel_price(i,r,t) * GEN(i,v,r,h,t) * gasprice_adj_r(r,h) } ) ;
```

Switched off: transmission capital and fixed O&M, spur lines, growth and queue penalties, upgrades, refurbishment, water, startup costs, gas supply curves, biomass and cofiring, H2, DAC, CO2 transport, retirement penalties, operating-reserve costs and policy credits.

```python
# pyoframe
terms = [(P(df) * getattr(m, name)).sum() for name, df in O.items() if df.height]
m.minimize = reduce(lambda a, b: a + b, terms)
```

```python
# Pyomo
def objective(m):
    total = 0
    for name, df in O.items():
        var = getattr(m, name)
        for k, c in zip(rows(df, V[name].columns), df["value"].to_list()):
            total += c * var[k]
    return total

m.obj = pyo.Objective(rule=objective, sense=pyo.minimize)
```

The data layer folds `cost_scale`, the present-value factors, financing multipliers and `hours(h)` into one coefficient per variable, so both tools write a plain linear sum. At 378k rows that takes 0.11 s in pyoframe and 0.21 s in Pyomo, plus 0.58 s of Pyomo handoff.

**Gap to fix before the Pacific export.** The slice prices gas generation at `heat_rate × fuel_price`, without the hourly regional multiplier `gasprice_adj_r(r,h)` that ReEDS applies under `GSw_GasCurve = 2`. The export should carry an hourly fuel-cost coefficient, or confirm the multiplier is 1 in that case; otherwise GEN costs and the energy duals will not match GAMS.

## Per-constraint scorecard

pyoframe takes less code for 16 of 17 constraints and builds every constraint with more than 1,000 rows faster. Pyomo is faster only on two tiny families, by under 10 ms each.

| Constraint | Rows (102k case) | GAMS lines, full equation | pyoframe lines | Pyomo lines | Rows with differing duals |
| --- | --- | --- | --- | --- | --- |
| eq\_loadcon | 3,360 | 19 | 1 | 3 | 523 (16%) |
| eq\_supply\_demand\_balance | 3,360 | 15 | 6 | 15 | 523 (16%) |
| eq\_capacity\_limit | 53,760 | 25 | 1 | 4 | 6,478 (12%) |
| eq\_capacity\_limit\_nd | 3,360 | 7 | 1 | 4 | 523 (16%) |
| eq\_cap\_init\_noret | 320 | 17 | 1 | 4 | 0 |
| eq\_cap\_new\_noret | 480 | 22 | 3 | 10 | 3 (1%) |
| eq\_cap\_energy\_new\_noret | 80 | 11 | 3 | 3 | 0 |
| eq\_rsc\_inv\_account | 120 | 5 | 3 | 5 | 3 (3%) |
| eq\_rsc\_INVlim | 359 | 16 | 2 | 6 | 0 |
| eq\_storage\_capacity | 10,080 | 18 | 3 | 5 | 1,094 (11%) |
| eq\_storage\_duration | 10,080 | 10 | 2 | 12 | 589 (6%) |
| eq\_storage\_level | 10,080 | 24 | 5 | 11 | 1,991 (20%) |
| eq\_CAPTRAN\_ENERGY | 80 | 14 | 2 | 7 | 0 |
| eq\_CAPTRAN\_PRM | 80 | 16 | 5 | 6 | 0 |
| eq\_transmission\_limit | 6,720 | 8 | 4 | 13 | 365 (5%) |
| eq\_emit\_accounting | 80 | 17 | 3 | 11 | 0 |
| eq\_annual\_cap | 1 | 5 | 4 | 9 | 0 |
| **Total** | **102,400** | **249** | **49** | **128** |  |

Line counts are the non-blank lines of the code shown in each section; Pyomo's shared `stock_rule` (7 lines) is counted once, under `eq_cap_new_noret`. GAMS lines are for the full ReEDS equation, all switches included, so they are larger than the slice they correspond to. Dual differences compare pyoframe with one Pyomo run; both tools pass the KKT check.

Build time per constraint (median of 3 runs; synthetic 378k-row case: 80 zones, 24 representative days, 2 stress days; 2-CPU cloud container; pyoframe 1.9.1, Pyomo 6.10.1 appsi HiGHS interface, HiGHS 1.15.1). Excludes creating variables and the objective. In the original doc this was a chart; raw numbers are in `benchmarks/results/per_constraint_timing.json`.

| Constraint | Rows (378k case) | pyoframe build | Pyomo construction | Pyomo handoff to HiGHS | Pyomo total |
| --- | --- | --- | --- | --- | --- |
| eq\_storage\_duration | 37,440 | 213 ms | 718 ms | 11.4 s | 12.1 s |
| eq\_capacity\_limit | 199,680 | 1.3 s | 2.7 s | 5.2 s | 7.9 s |
| eq\_supply\_demand\_balance | 12,480 | 623 ms | 760 ms | 5.7 s | 6.5 s |
| eq\_storage\_capacity | 37,440 | 302 ms | 390 ms | 2.0 s | 2.4 s |
| eq\_storage\_level | 37,440 | 331 ms | 504 ms | 1.7 s | 2.2 s |
| eq\_loadcon | 12,480 | 71 ms | 61 ms | 1.7 s | 1.7 s |
| eq\_emit\_accounting | 160 | 214 ms | 1.1 s | 603 ms | 1.7 s |
| eq\_transmission\_limit | 24,960 | 128 ms | 181 ms | 631 ms | 812 ms |
| eq\_capacity\_limit\_nd | 12,480 | 103 ms | 440 ms | 364 ms | 804 ms |
| eq\_CAPTRAN\_ENERGY | 160 | 9 ms | 2 ms | 49 ms | 51 ms |
| eq\_CAPTRAN\_PRM | 160 | 8 ms | 1 ms | 50 ms | 51 ms |
| eq\_cap\_new\_noret | 960 | 23 ms | 8 ms | 20 ms | 29 ms |
| eq\_rsc\_INVlim | 719 | 14 ms | 6 ms | 16 ms | 22 ms |
| eq\_cap\_init\_noret | 640 | 10 ms | 4 ms | 13 ms | 17 ms |
| eq\_rsc\_inv\_account | 240 | 9 ms | 3 ms | 6 ms | 9 ms |
| eq\_cap\_energy\_new\_noret | 160 | 14 ms | 2 ms | 4 ms | 5 ms |
| eq\_annual\_cap | 1 | 9 ms | 2 ms | 1 ms | 3 ms |
| **Total, 17 constraints** | **377,600** | **3.4 s** | **6.9 s** | **29.5 s** | **36.4 s** |

Pyomo's handoff cost tracks the variables a constraint is first to register with HiGHS more than its row count. `eq_storage_duration` registers `STORAGE_LEVEL` and takes 11.4 s for 37,440 rows, while `eq_capacity_limit` takes 5.2 s for 199,680 rows whose variables are already registered.

## Findings and next steps

Constraint by constraint, pyoframe is the closer and faster translation of the ReEDS GAMS code. Pyomo's advantage remains solver coverage for the later integer and quadratic work.

- **pyoframe reads closer to GAMS.** Joins stand in for `$` conditions and `sum_by` for `sum{...}`, so most constraints are one to three lines. Every Pyomo constraint has two parts, a dict pre-index and a rule, which is what makes it fast enough to use.
- **pyoframe makes missing labels explicit.** 14 of 17 constraints need `keep_extras`, `drop_extras` or `U(...)` where GAMS silently treats a missing term as zero. That is extra code, but it turns a wrong domain into an error instead of a quietly different model.
- **Two GAMS patterns need care in both tools.** `nexth` must come in as a table because it wraps within each representative day. And GAMS broadcasts a 4-index capacity over hours implicitly; pyoframe needs the coefficient on the hourly index (`eq_storage_duration`).
- **Pyomo's cost is the handoff, not the rules.** At 378k rows, construction is 8.2 s and the handoff to HiGHS is 29 s, mostly in the families that first register a large variable set. Both Pyomo HiGHS interfaces take the same time.
- **Duals agree where the model is not degenerate.** Capacity stock, supply-curve limits, transmission capacity and emissions match to about 1e-14. Hourly operating rows differ, both tools pass the KKT check, and Pyomo's values change from run to run.

Next steps:

- [ ] Add the hourly gas price multiplier to the export (see the objective section).
- [ ] Export a Pacific case and run gates 1 to 4 against the GAMS solution, using the KKT gate on GAMS marginals.
- [ ] Test Pyomo's LP-file route to see whether it removes the 29 s handoff and the run-to-run variation.
- [ ] Add the extensions: integer transmission blocks, convex quadratic losses, and MIQCP (Pyomo with SCIP; pyoframe has no open-source solver for it).
