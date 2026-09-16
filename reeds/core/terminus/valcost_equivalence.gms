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
* entirely, and the ForceMandate multiplier does not scale it (it scales
* cost_fom, not this), so in a forced run it is charged at full cost while
* every other component is scaled down - by 2050 in the onswind run it is 3.4x
* the plant FOM. Without it the identity shows a 67% hole on 2050 builds that
* looks like profit and is not. Its dual sits on eq_cap_rsc, which is how it was
* found: that equation carried exactly the missing amount.
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

* Techs to evaluate. Every rsc tech is fine, but start narrow: the rest of the
* identity (curtailment, opres) is written for VRE.
set vc_tech(i) "techs given the equivalence check" ;
vc_tech(i)$[wind(i) or pv(i)] = yes ;

* The new vintage of each (i,r,t): valinv(i,v,r,t) is exactly that.
set vc_new(i,v,r,t) "new-vintage plants to check" ;
vc_new(i,v,r,t)$[vc_tech(i)$valinv(i,v,r,t)$tmodel_new(t)$(INV.l(i,v,r,t) > 0)] = yes ;

scalar vc_dual "dual scaling, 1/(cost_scale*pvf_onm), applied per year below" ;

set vc_stream "cost and value streams" /
  cost_capex        "annualised capital, crf * cost_cap_fin_mult * cost_cap * INV"
  cost_rsc          "annualised supply-curve cost, crf * m_rsc_dat(cost) * rsc_fin_mult * INV_RSC"
  cost_fom          "fixed O&M on the new vintage's CAP"
  cost_transfom     "fixed O&M on supply-curve transmission, m_rsc_dat(cost_trans) * trans_fom_frac * CAP_RSC"
  cost_vom          "variable O&M on the new vintage's GEN"
  cost_total        "sum of cost streams"
  val_load          "energy value at rep hours, GEN * marginal of eq_supply_demand_balance"
  val_resmarg       "reserve-margin value at stress hours, same equation"
  val_rsc           "resource rent, INV_RSC * marginal of eq_rsc_INVlim. NOT added to val_total: see residual"
  val_curt          "curtailment-balance value, (m_cf*CAP - GEN) * marginal of eq_curt_gen_balance"
  val_opres         "operating-reserve requirement induced, -orperc*GEN * marginal of eq_OpRes_requirement"
  val_total         "sum of value streams"
  residual          "val_total - cost_total - val_rsc; zero if every stream is accounted for"
  inv_mw            "INV level, MW"
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
    sum{v$vc_new(i,v,r,t), cost_fom(i,v,r,t) * CAP.l(i,v,r,t) } ;

* Transmission FOM on the new vintage's bin capacity. CAP_RSC is cumulative over
* years, but for the new vintage in year t it equals this year's INV_RSC.
valcost('cost_transfom',i,r,t)$sum{v, vc_new(i,v,r,t)} =
    sum{(v,rscbin)$[vc_new(i,v,r,t)$m_rscfeas(r,i,rscbin)$rsc_i(i)$(not spur_techs(i))$(not sccapcosttech(i))],
        m_rsc_dat(r,i,rscbin,"cost_trans") * trans_fom_frac * CAP_RSC.l(i,v,r,rscbin,t) } ;

valcost('cost_vom',i,r,t)$sum{v, vc_new(i,v,r,t)} =
    sum{(v,h)$[vc_new(i,v,r,t)$valgen(i,v,r,t)], cost_vom(i,v,r,t) * GEN.l(i,v,r,h,t) * hours(h) } ;

valcost('cost_total',i,r,t) =
    valcost('cost_capex',i,r,t) + valcost('cost_rsc',i,r,t)
  + valcost('cost_fom',i,r,t)   + valcost('cost_transfom',i,r,t)
  + valcost('cost_vom',i,r,t) ;

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
        GEN.l(i,v,r,h,t) * eq_supply_demand_balance.m(r,h,t) } ;

valcost('val_resmarg',i,r,t)$[sum{v, vc_new(i,v,r,t)}$(Sw_PRM_CapCredit=0)] =
    (1 / cost_scale) * (1 / pvf_onm(t)) *
    sum{(v,allh)$[vc_new(i,v,r,t)$valgen(i,v,r,t)$h_stress_t(allh,t)],
        GEN.l(i,v,r,allh,t) * eq_supply_demand_balance.m(r,allh,t) } ;

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
valcost('val_curt',i,r,t)$sum{v, vc_new(i,v,r,t)} =
    (1 / cost_scale) * (1 / pvf_onm(t)) *
    sum{(v,h)$[vc_new(i,v,r,t)$valcap(i,v,r,t)$h_t(h,t)$(not h_stress_t(h,t))],
        ( m_cf(i,v,r,h,t) * CAP.l(i,v,r,t)
        - GEN.l(i,v,r,h,t)$valgen(i,v,r,t) )
        * eq_curt_gen_balance.m(r,h,t) } ;

* eq_OpRes_requirement: wind GEN raises the requirement by orperc(or_wind), PV
* CAP/ilr by orperc(or_pv) in daylight. A requirement the plant creates, so it
* enters as a negative value, matching valnew's sign convention.
valcost('val_opres',i,r,t)$[sum{v, vc_new(i,v,r,t)}$Sw_OpRes$wind(i)] =
    -1 * (1 / cost_scale) * (1 / pvf_onm(t)) *
    sum{(v,ortype,h)$[vc_new(i,v,r,t)$valgen(i,v,r,t)$opres_model(ortype)$opres_h(h)],
        orperc(ortype,"or_wind") * GEN.l(i,v,r,h,t) * eq_OpRes_requirement.m(ortype,r,h,t) } ;
valcost('val_opres',i,r,t)$[sum{v, vc_new(i,v,r,t)}$Sw_OpRes$(pv(i) or pvb(i))] =
    -1 * (1 / cost_scale) * (1 / pvf_onm(t)) *
    sum{(v,ortype,h)$[vc_new(i,v,r,t)$valcap(i,v,r,t)$opres_model(ortype)$opres_h(h)$dayhours(h)],
        orperc(ortype,"or_pv") * CAP.l(i,v,r,t) / ilr(i) * eq_OpRes_requirement.m(ortype,r,h,t) } ;

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
  + valcost('val_curt',i,r,t) + valcost('val_opres',i,r,t) ;

valcost('residual',i,r,t)$sum{v, vc_new(i,v,r,t)} =
    valcost('val_total',i,r,t) - valcost('cost_total',i,r,t) - valcost('val_rsc',i,r,t) ;

* ---- quantities, for whatever normalisation the reader wants ----
valcost('inv_mw',i,r,t)$sum{v, vc_new(i,v,r,t)} = sum{v$vc_new(i,v,r,t), INV.l(i,v,r,t) } ;
valcost('gen_mwh',i,r,t)$sum{v, vc_new(i,v,r,t)} =
    sum{(v,h)$[vc_new(i,v,r,t)$valgen(i,v,r,t)$h_t(h,t)$(not h_stress_t(h,t))], GEN.l(i,v,r,h,t) * hours(h) } ;
valcost('gen_uncurt_mwh',i,r,t)$sum{v, vc_new(i,v,r,t)} =
    sum{(v,h)$[vc_new(i,v,r,t)$valcap(i,v,r,t)$h_t(h,t)$(not h_stress_t(h,t))], m_cf(i,v,r,h,t) * CAP.l(i,v,r,t) * hours(h) } ;

* Also keep the raw reduced cost of INV_RSC on built bins. It should be zero;
* where it is not, the bin is degenerate and the per-stream split is not unique
* even though the total still closes.
parameter valcost_rc(i,r,t) "INV_RSC-weighted mean reduced cost of built bins, $/MW" ;
valcost_rc(i,r,t)$sum{(v,rscbin)$vc_new(i,v,r,t), INV_RSC.l(i,v,r,rscbin,t)} =
    sum{(v,rscbin)$vc_new(i,v,r,t), INV_RSC.l(i,v,r,rscbin,t) * INV_RSC.m(i,v,r,rscbin,t) }
  / sum{(v,rscbin)$vc_new(i,v,r,t), INV_RSC.l(i,v,r,rscbin,t) } ;

execute_unload "outputs%ds%valcost_equivalence_%fname%.gdx" valcost, valcost_rc ;
