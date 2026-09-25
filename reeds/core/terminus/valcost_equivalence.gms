* valcost_equivalence.gms
* ---------------------------------------------------------------------------
* Cost-value equivalence for each new build, from the final restart file.
*
* At an LP optimum every variable with a positive level has zero reduced cost,
* and reduced cost is the objective coefficient minus the sum over all
* constraints of (coefficient x marginal). Summing over every variable that
* belongs to one plant - INV_RSC, INV, CAP, GEN - the constraints that connect
* those variables only to each other (eq_rsc_inv_account, eq_cap_new_*,
* eq_capacity_limit) cancel out, and what remains is an identity in dollars:
*
*     revenue the plant collects  =  objective cost  +  resource rent
*
* where revenue is GEN times the load-balance duals (rep and stress hours) and
* resource rent is INV_RSC times the dual on the bin capacity limit. Rent is on
* the cost side of the equals sign: it is what remains of revenue after costs,
* assigned by the LP to the scarce site, not an extra payment to the plant.
*
* This file computes both sides for the new vintage of each (i,r,t) - valinv -
* and writes the residual. A residual near zero says every stream is
* accounted for; a nonzero residual IS the contribution of a constraint not
* listed below, which is the point of computing it. The identity is exact in
* dollars, so no MWh normalisation is applied here; that is a presentation
* choice left to whatever reads the output.
*
* External constraints a new wind or solar build enters, and the stream each
* one contributes (all duals scaled by 1/(cost_scale*pvf_onm), as report.gms
* does for reqt_price, so both sides are in the same year-t dollars):
*
*   eq_supply_demand_balance  (rep hours)     GEN        -> val_load
*   eq_supply_demand_balance  (stress hours)  GEN        -> val_resmarg
*   eq_rsc_INVlim                             INV_RSC    -> val_rsc  (resource rent)
*   eq_curt_gen_balance                       CAP, GEN   -> val_curt
*   eq_OpRes_requirement                      GEN        -> val_opres (a requirement
*                                                            wind induces, so negative)
*
* One cost stream is easy to miss and is the largest one late in a forced run:
* the fixed O&M on supply-curve transmission, charged in the objective as
* m_rsc_dat(cost_trans) * trans_fom_frac * CAP_RSC. The lcoe output omits it
* entirely. Until 2026-09 the ForceMandate multiplier did not scale it either
* (it scaled cost_fom, not this), so in a forced run it was charged at full cost
* while every other component was scaled down - by 2050 in the onswind run it
* was 3.4x the plant FOM, and the identity showed a 67% hole on 2050 builds that
* looked like profit and was not. Its dual sits on eq_cap_rsc, which is how it
* was found: that equation carried exactly the missing amount. The objective now
* multiplies the term by forcetechmult, and so does this file.
*
* A restart-file hazard, for anyone extending this. 2_temporal_params.gms runs
* every solve year and begins with m_cf(i,v,r,allh,t) = 0 over ALL years before
* refilling only the current year's active timeslices. In the final restart,
* m_cf for a prior year is therefore zero at any stress day that year used but
* the final year does not - 112 of 184 timeslices for 2030 in the upv run. The
* representative days are fixed across years (clustered once, on
* GSw_HourlyClusterYear) and survive; only stress days move. GEN.l is fixed by
* 5_varfix.gms after each solve and is preserved. So: m_cf is safe on rep hours
* for any year, and on stress hours only for the restart year. Every stress-hour
* term here uses GEN.l for that reason, and at a binding capacity limit
* GEN = m_cf * CAP so nothing is lost. Reading m_cf at a prior year's stress
* hours silently undercounts, and by an amount that grows the further the year
* is from the restart.
*
* Storage: the streams here are right but the identity does NOT close for it,
* and the reason is worth knowing before trusting this file on any multi-year
* vintage. Dumping the 2050 matrix and reading every column a battery enters
* (dump_jacobian.gms, jacobian_column.py) gives seven variables and, besides the
* objective, only rows internal to the plant - eq_storage_level,
* eq_storage_capacity, eq_storage_duration, eq_battery_minduration and the two
* capacity-accounting rows all pair the plant's own variables. There is no
* resource limit, no mandate (GSw_BatteryMandate=0) and no capacity-credit row
* (GSw_PRM_CapCredit=0 routes storage's firm capacity through stress-hour GEN).
* So a battery should show revenue = cost with no rent term. It does not: the
* median build is exact but only a quarter are within 1%, and the error tracks
* build size - a 4.9 GW build closes to the dollar, a 1.8 MW one is off 4x.
*
* The cause is the pro-rating above, not a missing stream. Battery's vintage
* spans many solve years, so CAP is mostly earlier years' investment, and
* INV/CAP attributes the vintage's AVERAGE value to this year's marginal MW.
* For a single-year vintage (wind, PV, coal) the ratio is 1 and the question
* does not arise; for nuclear the per-MW value barely moves across the vintage
* so it is close; for storage it moves a lot, and INV_ENERGY moves independently
* of INV, so the average is the wrong number for the margin.
*
* The exact test for storage is the LP's own optimality condition on the
* investment variables, which needs no pro-rating:
*     crf * cost_cap_fin_mult * cost_cap        = eq_cap_new_noret.m
*     crf * cost_cap_fin_mult * cost_cap_energy = eq_cap_energy_new_noret.m
* both scaled by (1/cost_scale)(1/pvf_onm). Checked on 2042 builds those close
* to 1e-8 relative for INV at every build size, and for INV_ENERGY wherever it
* is off its bound - where INV_ENERGY sits at zero its reduced cost is properly
* nonzero and the plant is adding power to energy capacity it already has.
*
* Sequential solves see one year of value against one year of annualised cost
* (pvf_onm = 1/crf), so the identity closes within the year and vintages need
* no forward tracing.
*
* Run after the model, restarting from the final g00, the same way report.gms is:
*   gams reeds/core/terminus/valcost_equivalence.gms r=g00files/<case> --fname=<case>
* Then reeds/core/terminus/valcost_equivalence.py turns the gdx into a csv.
* ---------------------------------------------------------------------------

$setglobal ds \
$ifthen.unix %system.filesys% == UNIX
$setglobal ds /
$endif.unix
$if not set fname $setglobal fname ref

* Techs to evaluate. VRE, storage, and the thermal techs whose fuel is a fixed
* price per MWh generated: coal, nuclear, and gas ONLY when GSw_GasCurve=2.
*
* Gas is conditional because the switch decides which objective term pays for
* its fuel. At GSw_GasCurve=2 there is a per-tech term of the same form as the
* generic one - hours * heat_rate * fuel_price * GEN - so gas behaves exactly
* like coal, which the 2050 matrix confirms: dumping the gas run and reading
* every column gas-cc enters (dump_jacobian.gms, jacobian_column.py) gives the
* same four variable families and the same equation families as coal-new, with
* no gas-specific row. At any other setting the fuel cost moves onto GASUSED,
* which carries no tech index, and the plant's GEN instead enters eq_gasused;
* that is a different accounting this file does not implement, so gas is left
* out rather than silently mis-costed.
*
* CCS techs are excluded throughout: they would need the CO2 storage and 45Q
* terms.
set vc_tech(i) "techs given the equivalence check" ;
vc_tech(i)$[wind(i) or pv(i) or (coal(i) and not ccs(i)) or nuclear(i)
            or (battery(i) and storage_standalone(i))
            or (gas(i) and (not ccs(i)) and (Sw_GasCurve = 2))] = yes ;

* The new vintage of each (i,r,t): valinv(i,v,r,t) is exactly that.
set vc_new(i,v,r,t) "new-vintage plants to check" ;
vc_new(i,v,r,t)$[vc_tech(i)$valinv(i,v,r,t)$tmodel_new(t)$(INV.l(i,v,r,t) > 0)] = yes ;

* A vintage can span several solve years (ivt.csv: nuclear's new7 is 2046-2050;
* wind, PV and coal get a fresh vintage each year). CAP and GEN belong to the
* whole vintage, INV to this year. The reduced-cost identities are per MW of
* each variable, so every CAP-, GEN- and CAP_RSC-based stream is scaled by
* INV/CAP to credit this year's investment its pro-rata share - the same
* inv_cap_ratio that valnew in report.gms applies. Without it, the second and
* later years of a multi-year vintage show value/cost well above 1 (nuclear
* 2038: 1.4) because a whole vintage's revenue is set against one year's capex.
parameter vc_ratio(i,v,r,t) "INV/CAP of the new vintage" ;
vc_ratio(i,v,r,t)$[vc_new(i,v,r,t)$CAP.l(i,v,r,t)] = INV.l(i,v,r,t) / CAP.l(i,v,r,t) ;

* Storage carries a second capacity variable, and its own ratio: a battery is
* sized by power (CAP, MW) and by energy (CAP_ENERGY, MWh), bought and paid for
* separately, so the energy streams are pro-rated on INV_ENERGY/CAP_ENERGY.
parameter vc_ratio_energy(i,v,r,t) "INV_ENERGY/CAP_ENERGY of the new vintage" ;
vc_ratio_energy(i,v,r,t)$[vc_new(i,v,r,t)$CAP_ENERGY.l(i,v,r,t)] =
    INV_ENERGY.l(i,v,r,t) / CAP_ENERGY.l(i,v,r,t) ;

scalar vc_dual "dual scaling, 1/(cost_scale*pvf_onm), applied per year below" ;

set vc_stream "cost and value streams" /
  cost_capex        "annualised capital, crf * cost_cap_fin_mult * cost_cap * INV"
  cost_rsc          "annualised supply-curve cost, crf * m_rsc_dat(cost) * rsc_fin_mult * INV_RSC"
  cost_fom          "fixed O&M on the new vintage's CAP"
  cost_capex_energy "annualised energy-capacity capital, crf * cost_cap_fin_mult * cost_cap_energy * INV_ENERGY (storage)"
  cost_fom_energy   "fixed O&M on the new vintage's CAP_ENERGY (storage)"
  cost_transfom     "fixed O&M on supply-curve transmission, m_rsc_dat(cost_trans) * trans_fom_frac * CAP_RSC"
  cost_vom          "variable O&M on the new vintage's GEN"
  cost_fuel         "fuel, hours * heat_rate * fuel_price * GEN (fixed-price fuels only)"
  cost_total        "sum of cost streams"
  val_load          "energy value at rep hours, GEN * marginal of eq_supply_demand_balance"
  val_resmarg       "reserve-margin value at stress hours, same equation"
  val_rsc           "resource rent, INV_RSC * marginal of eq_rsc_INVlim. NOT added to val_total: see residual"
  val_csapr         "NOx-cap rent, h_weight_csapr*hours*emit_rate(NOX)*GEN * marginal of eq_CSAPR_Assurance. Also a rent: see residual"
  val_prescribed    "prescription rent, INV * marginal of eq_forceprescription_power; negative when a mandated plant does not earn its cost. Rent side"
  val_curt          "curtailment-balance value, (m_cf*CAP - GEN) * marginal of eq_curt_gen_balance"
  val_opres         "operating-reserve requirement induced, -orperc*GEN * marginal of eq_OpRes_requirement"
  val_mincf         "minimum-CF credit, (sum_h hours*GEN - H*minCF*CAP) * marginal of eq_min_cf"
  val_ramp          "start-cost share, -(GEN(hh)-GEN(h)) * marginal of eq_ramping"
  val_total         "sum of value streams"
  residual          "val_total - cost_total - val_rsc - val_csapr - val_prescribed; zero if every stream is accounted for"
  inv_mw            "INV level, MW"
  prescribed_mw     "prescribed capacity for this tech's pcat in this region-year, MW. Nonzero marks a mandated build: filter these out of any zero-profit statistic"
  gen_mwh           "GEN summed over rep hours, MWh (curtailed)"
  gen_uncurt_mwh    "m_cf*CAP summed over rep hours, MWh (uncurtailed)"
/ ;

parameter valcost(vc_stream,i,r,t) "cost-value equivalence of each new build, $ (year-t dollars)" ;

* ---- cost side: the objective's charges on this plant, annualised at crf ----
* rsc_fin_mult_out, not rsc_fin_mult. 2_financials.gms applies the ForceMandate
* multiplier to rsc_fin_mult for the current solve year only, so in the final
* restart file rsc_fin_mult holds the last year's scaling for that year and the
* UNSCALED value for every earlier one. rsc_fin_mult_out is the copy taken each
* year to preserve the history, and is what lcoe and systemcost use.
* The objective enters capex at pvf_capital=1 (a lump sum) and everything else
* at pvf_onm=1/crf; dividing through by pvf_onm puts capex on a crf basis,
* which is what lcoe reports and what the duals below are scaled to.
valcost('cost_capex',i,r,t)$sum{v, vc_new(i,v,r,t)} =
    sum{v$vc_new(i,v,r,t), crf(t) * cost_cap_fin_mult(i,r,t) * cost_cap(i,t) * INV.l(i,v,r,t) } ;

valcost('cost_rsc',i,r,t)$sum{v, vc_new(i,v,r,t)} =
    sum{(v,rscbin)$[vc_new(i,v,r,t)$m_rscfeas(r,i,rscbin)],
        crf(t) * m_rsc_dat(r,i,rscbin,"cost") * rsc_fin_mult_out(i,r,t) * INV_RSC.l(i,v,r,rscbin,t) } ;

valcost('cost_fom',i,r,t)$sum{v, vc_new(i,v,r,t)} =
    sum{v$vc_new(i,v,r,t), cost_fom(i,v,r,t) * vc_ratio(i,v,r,t) * CAP.l(i,v,r,t) } ;

* Transmission FOM on the new vintage's bin capacity. CAP_RSC is cumulative over
* years, but for the new vintage in year t it equals this year's INV_RSC.
* Storage energy capacity: a separate purchase from power capacity, with its own
* capital and O&M terms in the objective (d_objective.gms:43 and :176).
valcost('cost_capex_energy',i,r,t)$sum{v, vc_new(i,v,r,t)} =
    sum{v$vc_new(i,v,r,t),
        crf(t) * cost_cap_fin_mult(i,r,t) * cost_cap_energy(i,t) * INV_ENERGY.l(i,v,r,t) } ;

valcost('cost_fom_energy',i,r,t)$sum{v, vc_new(i,v,r,t)} =
    sum{v$vc_new(i,v,r,t),
        cost_fom_energy(i,v,r,t) * vc_ratio_energy(i,v,r,t) * CAP_ENERGY.l(i,v,r,t) } ;

valcost('cost_transfom',i,r,t)$sum{v, vc_new(i,v,r,t)} =
    sum{(v,rscbin)$[vc_new(i,v,r,t)$m_rscfeas(r,i,rscbin)$rsc_i(i)$(not spur_techs(i))$(not sccapcosttech(i))],
        m_rsc_dat(r,i,rscbin,"cost_trans") * trans_fom_frac * forcetechmult(i,t) * vc_ratio(i,v,r,t) * CAP_RSC.l(i,v,r,rscbin,t) } ;

valcost('cost_vom',i,r,t)$sum{v, vc_new(i,v,r,t)} =
    sum{(v,h)$[vc_new(i,v,r,t)$valgen(i,v,r,t)], cost_vom(i,v,r,t) * vc_ratio(i,v,r,t) * GEN.l(i,v,r,h,t) * hours(h) } ;

* Fuel. Two objective terms share this form: the generic one, which excludes
* gas, bio, cofire and endogenous H2, and the GSw_GasCurve=2 one for gas. One
* expression covers both, with gas admitted only at that switch setting -
* vc_tech keeps gas out otherwise, and the condition is repeated here so this
* line reads correctly on its own. fuel_price is scaled once per year in
* 2_financials.gms on its own value, so prior years keep theirs in the restart.
valcost('cost_fuel',i,r,t)$sum{v, vc_new(i,v,r,t)} =
    sum{(v,h)$[vc_new(i,v,r,t)$valgen(i,v,r,t)$heat_rate(i,v,r,t)
               $(not bio(i))$(not cofire(i))$(not h2_combustion(i))
               $((not gas(i)) or (Sw_GasCurve = 2))],
        hours(h) * heat_rate(i,v,r,t) * fuel_price(i,r,t) * vc_ratio(i,v,r,t) * GEN.l(i,v,r,h,t) } ;

valcost('cost_total',i,r,t) =
    valcost('cost_capex',i,r,t) + valcost('cost_rsc',i,r,t)
  + valcost('cost_fom',i,r,t)   + valcost('cost_transfom',i,r,t)
  + valcost('cost_vom',i,r,t)   + valcost('cost_fuel',i,r,t)
  + valcost('cost_capex_energy',i,r,t) + valcost('cost_fom_energy',i,r,t) ;

* ---- value side: level x coefficient x marginal, per external constraint ----
* Marginals are scaled exactly as report.gms scales reqt_price. The per-hour
* marginal is already per hour-weighted MW, hence the /hours(h) there and the
* *hours(h) here cancel: GEN*hours*(m/hours) = GEN*m.
* Representative hours only. h_t includes the stress hours, which carry the
* reserve-margin dual on the same equation and are counted in val_resmarg below;
* summing them here too double counts them, and by a growing amount as the stress
* duals grow. This matches valnew's val_load, which sums over h, not allh.
valcost('val_load',i,r,t)$sum{v, vc_new(i,v,r,t)} =
    (1 / cost_scale) * (1 / pvf_onm(t)) *
    sum{(v,h)$[vc_new(i,v,r,t)$valgen(i,v,r,t)$h_t(h,t)$(not h_stress_t(h,t))],
        vc_ratio(i,v,r,t) * (GEN.l(i,v,r,h,t) - STORAGE_IN.l(i,v,r,h,t)$storage_standalone(i))
        * eq_supply_demand_balance.m(r,h,t) } ;

valcost('val_resmarg',i,r,t)$[sum{v, vc_new(i,v,r,t)}$(Sw_PRM_CapCredit=0)] =
    (1 / cost_scale) * (1 / pvf_onm(t)) *
    sum{(v,allh)$[vc_new(i,v,r,t)$valgen(i,v,r,t)$h_stress_t(allh,t)],
        vc_ratio(i,v,r,t) * (GEN.l(i,v,r,allh,t) - STORAGE_IN.l(i,v,r,allh,t)$storage_standalone(i))
        * eq_supply_demand_balance.m(r,allh,t) } ;

valcost('val_rsc',i,r,t)$sum{v, vc_new(i,v,r,t)} =
    (1 / cost_scale) * (1 / pvf_onm(t)) *
    sum{(v,rscbin)$[vc_new(i,v,r,t)$m_rscfeas(r,i,rscbin)],
        INV_RSC.l(i,v,r,rscbin,t) * eq_rsc_INVlim.m(r,i,rscbin,t) } ;

* eq_curt_gen_balance: m_cf*CAP on the >= side, GEN on the <= side, so the
* plant's net contribution is (m_cf*CAP - GEN) x marginal. Where the constraint
* binds that slack is zero, and where it is slack the marginal is zero, so this
* stream is identically zero for a single plant - the constraint is internal to
* the VRE fleet and cancels, as eq_capacity_limit does. Kept so the cancellation
* is visible in the output rather than assumed.
* Only VRE (and hybrid storage) enter eq_curt_gen_balance, so only they get this
* stream. Applied to a thermal tech it becomes -GEN * lambda_curt for a
* constraint the plant is not in, and silently charged coal 80% of its cost
* in states where VRE curtailment binds (SC, NH, the Southeast).
valcost('val_curt',i,r,t)$[sum{v, vc_new(i,v,r,t)}$(vre(i) or storage_hybrid(i))] =
    (1 / cost_scale) * (1 / pvf_onm(t)) *
    sum{(v,h)$[vc_new(i,v,r,t)$valcap(i,v,r,t)$h_t(h,t)$(not h_stress_t(h,t))],
        ( m_cf(i,v,r,h,t) * vc_ratio(i,v,r,t) * CAP.l(i,v,r,t)
        - vc_ratio(i,v,r,t) * GEN.l(i,v,r,h,t)$valgen(i,v,r,t) )
        * eq_curt_gen_balance.m(r,h,t) } ;

* eq_OpRes_requirement: wind GEN raises the requirement by orperc(or_wind), PV
* CAP/ilr by orperc(or_pv) in daylight. A requirement the plant creates, so it
* enters as a negative value, matching valnew's sign convention.
valcost('val_opres',i,r,t)$[sum{v, vc_new(i,v,r,t)}$Sw_OpRes$wind(i)] =
    -1 * (1 / cost_scale) * (1 / pvf_onm(t)) *
    sum{(v,ortype,h)$[vc_new(i,v,r,t)$valgen(i,v,r,t)$opres_model(ortype)$opres_h(h)],
        orperc(ortype,"or_wind") * vc_ratio(i,v,r,t) * GEN.l(i,v,r,h,t) * eq_OpRes_requirement.m(ortype,r,h,t) } ;
valcost('val_opres',i,r,t)$[sum{v, vc_new(i,v,r,t)}$Sw_OpRes$(pv(i) or pvb(i))] =
    -1 * (1 / cost_scale) * (1 / pvf_onm(t)) *
    sum{(v,ortype,h)$[vc_new(i,v,r,t)$valcap(i,v,r,t)$opres_model(ortype)$opres_h(h)$dayhours(h)],
        orperc(ortype,"or_pv") * vc_ratio(i,v,r,t) * CAP.l(i,v,r,t) / ilr(i) * eq_OpRes_requirement.m(ortype,r,h,t) } ;

* eq_min_cf(i,r,t): sum over vintages of hours*GEN >= sum of CAP * H * minCF.
* External to a single vintage because it sums over v, so its dual does not
* cancel plant-internally. The vintage's net contribution is its GEN term less
* its CAP term. Binding means the fleet is forced to run at hours where price is
* below marginal cost; the dual credits that forced generation, so this is
* usually a positive value stream that offsets a fuel cost with no revenue.
valcost('val_mincf',i,r,t)$[sum{v, vc_new(i,v,r,t)}$Sw_MinCF$minCF(i,t)] =
    (1 / cost_scale) * (1 / pvf_onm(t)) * (
        sum{(v,h)$[vc_new(i,v,r,t)$valgen(i,v,r,t)$h_rep(h)], hours(h) * vc_ratio(i,v,r,t) * GEN.l(i,v,r,h,t) }
      - sum{v$[vc_new(i,v,r,t)$valgen(i,v,r,t)], vc_ratio(i,v,r,t) * CAP.l(i,v,r,t) } * sum{h$h_rep(h), hours(h) } * minCF(i,t)
    ) * eq_min_cf.m(i,r,t) ;

* eq_ramping(i,r,h,hh,t): RAMPUP >= sum over vintages of GEN(hh) - GEN(h). Start
* costs sit on RAMPUP, shared across vintages, so the objective cannot attribute
* them; the vintage's share is its GEN swing times the dual, and it is a cost,
* hence the sign. Only rep hours are ramp-linked (numhours_nexth), so no
* restart hazard.
valcost('val_ramp',i,r,t)$[sum{v, vc_new(i,v,r,t)}$Sw_StartCost$startcost(i)] =
    -1 * (1 / cost_scale) * (1 / pvf_onm(t)) *
    sum{(v,h,hh)$[vc_new(i,v,r,t)$valgen(i,v,r,t)$numhours_nexth(h,hh)],
        (vc_ratio(i,v,r,t) * GEN.l(i,v,r,hh,t) - vc_ratio(i,v,r,t) * GEN.l(i,v,r,h,t)) * eq_ramping.m(i,r,h,hh,t) } ;

* eq_CSAPR_Assurance(st,t): a state ozone-season NOx cap. Found the way the
* transmission FOM was found - the coal identity failed only in CSAPR states
* (TX, PA), by a constant per rep day, and the LP column of a GEN variable,
* dumped with CONVERT, showed this equation with coefficient
* h_weight_csapr*hours*emit_rate. It is NOT gated on Sw_CSAPR (eq_CSAPR_Budget
* is), so it binds in runs that think CSAPR is off. Under forced coal the Texas
* cap's dual reached 99,600 $/ton. Like val_rsc this is rent the LP assigns to
* a scarce allowance out of the plant's revenue, so it sits on the rent side.
valcost('val_csapr',i,r,t)$[sum{v, vc_new(i,v,r,t)}$sum{st$r_st(r,st), csapr_cap(st,"Assurance",t)}] =
    (1 / cost_scale) * (1 / pvf_onm(t)) *
    sum{(v,h,st)$[vc_new(i,v,r,t)$valgen(i,v,r,t)$r_st(r,st)$h_rep(h)],
        h_weight_csapr(h) * hours(h) * emit_rate("process","NOX",i,v,r,t) * vc_ratio(i,v,r,t) * GEN.l(i,v,r,h,t)
        * eq_CSAPR_Assurance.m(st,t) } ;

* eq_forceprescription_power(pcat,r,t): cumulative INV of the techs in pcat must
* equal the prescribed amount (Vogtle, Watts Bar, the nuclear restarts, and so
* on). An equality, so its dual takes either sign; for a plant the LP would not
* have built it is negative by the shortfall. Zero-profit does not apply to a
* prescribed build, and this stream is what says so: the residual closes once
* it is on the rent side, and the reader can filter on it (prescribed_mw).
* Known gap: in the ref run the pre-2026 prescriptions (Vogtle, Watts Bar)
* close to the dollar with this stream, but the 2026-2030 nuclear restarts do
* not - the stored dual is 2.8-3.5x the shortfall and the reason could not be
* read without that year's restart file. Forced runs on this branch drop
* prescriptions from ForceStartYear (commit 20b335e0), so it only shows in ref.
valcost('val_prescribed',i,r,t)$[sum{v, vc_new(i,v,r,t)}$Sw_ForcePrescription] =
    -1 * (1 / cost_scale) * (1 / pvf_onm(t)) *
    sum{(v,pcat)$[vc_new(i,v,r,t)$prescriptivelink(pcat,i)$force_pcat(pcat,t)],
        INV.l(i,v,r,t) * eq_forceprescription_power.m(pcat,r,t) } ;

* val_total is what the plant COLLECTS: its generation times the prices it faces.
* Resource rent is deliberately not in it. The plant does not receive rent on
* top of its revenue; rent is the part of that revenue left over after every
* cost, and the LP assigns it to the binding resource constraint. So the
* identity is  revenue = cost + rent, or  val_total - cost_total - val_rsc = 0.
* Adding val_rsc to the value side counts it twice, which shows up as a
* one-sided "profit" of exactly val_rsc on every build with an exhausted bin -
* large for wind, which fills its bins, and invisible for UPV, which does not.
valcost('val_total',i,r,t) =
    valcost('val_load',i,r,t) + valcost('val_resmarg',i,r,t)
  + valcost('val_curt',i,r,t) + valcost('val_opres',i,r,t)
  + valcost('val_mincf',i,r,t) + valcost('val_ramp',i,r,t) ;

valcost('residual',i,r,t)$sum{v, vc_new(i,v,r,t)} =
    valcost('val_total',i,r,t) - valcost('cost_total',i,r,t)
  - valcost('val_rsc',i,r,t) - valcost('val_csapr',i,r,t) - valcost('val_prescribed',i,r,t) ;

* ---- quantities, for whatever normalisation the reader wants ----
valcost('inv_mw',i,r,t)$sum{v, vc_new(i,v,r,t)} = sum{v$vc_new(i,v,r,t), INV.l(i,v,r,t) } ;
valcost('prescribed_mw',i,r,t)$sum{v, vc_new(i,v,r,t)} = sum{pcat$prescriptivelink(pcat,i), noncumulative_prescriptions(pcat,r,t) } ;
valcost('gen_mwh',i,r,t)$sum{v, vc_new(i,v,r,t)} =
    sum{(v,h)$[vc_new(i,v,r,t)$valgen(i,v,r,t)$h_t(h,t)$(not h_stress_t(h,t))], vc_ratio(i,v,r,t) * GEN.l(i,v,r,h,t) * hours(h) } ;
valcost('gen_uncurt_mwh',i,r,t)$sum{v, vc_new(i,v,r,t)} =
    sum{(v,h)$[vc_new(i,v,r,t)$valcap(i,v,r,t)$h_t(h,t)$(not h_stress_t(h,t))], m_cf(i,v,r,h,t) * vc_ratio(i,v,r,t) * CAP.l(i,v,r,t) * hours(h) } ;

* Also keep the raw reduced cost of INV_RSC on built bins. It should be zero;
* where it is not, the bin is degenerate and the per-stream split is not unique
* even though the total still closes.
parameter valcost_rc(i,r,t) "INV_RSC-weighted mean reduced cost of built bins, $/MW" ;
valcost_rc(i,r,t)$sum{(v,rscbin)$vc_new(i,v,r,t), INV_RSC.l(i,v,r,rscbin,t)} =
    sum{(v,rscbin)$vc_new(i,v,r,t), INV_RSC.l(i,v,r,rscbin,t) * INV_RSC.m(i,v,r,rscbin,t) }
  / sum{(v,rscbin)$vc_new(i,v,r,t), INV_RSC.l(i,v,r,rscbin,t) } ;

execute_unload "outputs%ds%valcost_equivalence_%fname%.gdx" valcost, valcost_rc ;
