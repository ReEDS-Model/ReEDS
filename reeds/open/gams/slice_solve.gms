$setglobal ds \

$ifthen.unix %system.filesys% == UNIX
$setglobal ds /
$endif.unix

$if not set slice_dir $setglobal slice_dir slice

tload(t) = no ;

tmodel(t) = no ;
tmodel("%cur_year%") = yes ;

$log 'Solving ReEDS slice for...'
$log '  Case: %case%'
$log '  Year: %cur_year%'

$onMultiR
$include reeds%ds%core%ds%solve%ds%2_temporal_params.gms
$offMulti

$ifthene.post_startyear %cur_year%>%startyear%
rhs_eq_rsc_INVlim(r,i,rscbin,t)$[tmodel(t)$rsc_i(i)$m_rscfeas(r,i,rscbin)$m_rsc_con(r,i)] =
    ( m_rsc_dat(r,i,rscbin,"cap")
      - sum{(ii,v,tt)$[tfirst(tt)$rsc_agg(i,ii)$exog_rsc(i)],
             capacity_exog_rsc(ii,v,r,rscbin,tt) } )
        * (1$[not rsc_capacity_scalar_i(i)]
           + rsc_capacity_scalar(i,r,t)$rsc_capacity_scalar_i(i))
    + hyd_add_upg_cap(r,i,rscbin,t)$(Sw_HydroCapEnerUpgradeType=1)
    - sum{(ii,v,tt)$[valinv(ii,v,r,tt)$(yeart(tt) < yeart(t))$rsc_agg(i,ii)],
         INV_RSC.l(ii,v,r,rscbin,tt) * resourcescaler(ii) }
;

flag_eq_rsc_INVlim(r,i,rscbin,t)$tmodel(t) = no ;

flag_eq_rsc_INVlim(r,i,rscbin,t)$[tmodel(t)$rsc_i(i)$m_rscfeas(r,i,rscbin)$m_rsc_con(r,i)
                                 $(rhs_eq_rsc_INVlim(r,i,rscbin,t) > -rhs_tolerance)
                                 $(rhs_eq_rsc_INVlim(r,i,rscbin,t) < rhs_tolerance)] = yes ;

loop(i$rsc_i(i),
    INV_RSC.fx(ii,v,r,rscbin,t)$[tmodel(t)$m_rscfeas(r,i,rscbin)$m_rsc_con(r,i)
                                $(flag_eq_rsc_INVlim(r,i,rscbin,t))$(valinv(ii,v,r,t)$rsc_agg(i,ii))] = 0 ;
) ;
$endif.post_startyear

$ifthene.tcheck %cur_year%>%GSw_SkipRAyear%
tload("%cur_year%") = yes ;

$gdxin handoff%ds%reeds_data%ds%ccdata_%prev_year%.gdx
$loaddcr cc_old_load = cc_old
$loaddcr cc_mar_load = cc_mar
$loaddcr cc_evmc_load = cc_evmc
$loaddcr sdbin_size_load = sdbin_size
$loaddcr mean_forced_outage_rate_load = mean_forced_outage_rate
$gdxin

cc_old(i,r,ccseason,t)$[tload(t)$(vre(i) or csp(i) or pvb(i))] =
    sum{ccreg$r_ccreg(r,ccreg), cc_old_load(i,r,ccreg,ccseason,t) } ;

m_cc_mar(i,r,ccseason,t)$[tload(t)$(vre(i) or csp(i) or pvb(i))] =
    sum{ccreg$r_ccreg(r,ccreg), cc_mar_load(i,r,ccreg,ccseason,t) } ;

sdbin_size(ccreg,ccseason,sdbin,t)$tload(t) = sdbin_size_load(ccreg,ccseason,sdbin,t) ;

m_cc_mar(i,r,ccseason,t)$[tload(t)$pvb(i)] = min{ m_cc_mar(i,r,ccseason,t), 1 / ilr(i) - bcr(i) } ;

cc_old(i,r,ccseason,t)$[tload(t)$pvb(i)$sum{(v,tt)$tprev(t,tt), CAP.l(i,v,r,tt)}] =
    min{ cc_old(i,r,ccseason,t) / sum{(v,tt)$tprev(t,tt), CAP.l(i,v,r,tt)}, 1 / ilr(i) - bcr(i) }
    * sum{(v,tt)$tprev(t,tt), CAP.l(i,v,r,tt)};

mean_forced_outage_rate(i,r,ccseason,t)$tload(t) = mean_forced_outage_rate_load(i,r,ccseason,t) ;
$endif.tcheck

$include reeds%ds%core%ds%solve%ds%2_financials.gms

FLEX.fx(flex_type,r,h,t)$tmodel(t) = 0 ;
DROPPED.fx(r,h,t)$tmodel(t) = 0 ;
EXCESS.fx(r,h,t)$tmodel(t) = 0 ;
CAP_LOADSITE.fx(r,t)$[tmodel(t)$val_loadsite(r)] = 0 ;
OP_LOADSITE.fx(r,h,t)$[tmodel(t)$val_loadsite(r)] = 0 ;
INV_CAP_UP.fx(i,v,r,rscbin,t)$[tmodel(t)$allow_cap_up(i,v,r,rscbin,t)] = 0 ;
INV_ENER_UP.fx(i,v,r,rscbin,t)$[tmodel(t)$allow_ener_up(i,v,r,rscbin,t)] = 0 ;
INV_REFURB.fx(i,v,r,t)$[tmodel(t)$valinv(i,v,r,t)$refurbtech(i)] = 0 ;
UPGRADES.fx(i,v,r,t)$[tmodel(t)$valcap(i,v,r,t)$upgrade(i)] = 0 ;
UPGRADES_RETIRE.fx(i,v,r,t)$[tmodel(t)$valcap(i,v,r,t)$upgrade(i)] = 0 ;
GEN_STORAGE.fx(i,v,r,h,t)$[tmodel(t)$valgen(i,v,r,t)$storage_hybrid(i)] = 0 ;
STORAGE_IN_PLANT.fx(i,v,r,h,t)$[tmodel(t)$valgen(i,v,r,t)$storage_hybrid(i)] = 0 ;
STORAGE_IN_GRID.fx(i,v,r,h,t)$[tmodel(t)$valgen(i,v,r,t)$storage_hybrid(i)] = 0 ;
STORAGE_INTERDAY_DISPATCH.fx(i,v,r,h,t)$[tmodel(t)$valgen(i,v,r,t)$storage_interday(i)] = 0 ;
CCSFLEX_POW.fx(i,v,r,h,t)$[tmodel(t)$valgen(i,v,r,t)$ccsflex(i)] = 0 ;
CCSFLEX_POWREQ.fx(i,v,r,h,t)$[tmodel(t)$valgen(i,v,r,t)$ccsflex(i)] = 0 ;
OPRES.fx(ortype,i,v,r,h,t)$[tmodel(t)$valgen(i,v,r,t)$reserve_frac(i,ortype)] = 0 ;
OPRES_FLOW.fx(ortype,r,rr,h,t)$[tmodel(t)$opres_routes(r,rr,t)] = 0 ;
INVTRAN.fx(r,rr,trtype,t)$[tmodel(t)$routes_inv(r,rr,trtype,t)] = 0 ;
CONVERSION.fx(r,h,intype,outtype,t)$[tmodel(t)$val_converter(r,t)] = 0 ;
PRODUCE.fx(p,i,v,r,h,t)$[tmodel(t)$valcap(i,v,r,t)$i_p(i,p)] = 0 ;
H2_FLOW.fx(r,rr,h,t)$[tmodel(t)$h2_routes(r,rr)] = 0 ;
H2_STOR_IN.fx(h2_stor,r,h,t)$[tmodel(t)$h2_stor_r(h2_stor,r)] = 0 ;
H2_STOR_OUT.fx(h2_stor,r,h,t)$[tmodel(t)$h2_stor_r(h2_stor,r)] = 0 ;

parameter
    slice_cap_coef(i,v,r,allh,t)
    slice_stor_cap_coef(i,v,r,allh,t)
    slice_dur_coef(i,v,r)
    slice_prescr_ret(i,v,r,t)
    slice_prescr_ret_energy(i,v,r,t)
    slice_rsc_cap(r,i,rscbin,t)
    slice_rsc_cost(r,i,rscbin)
    slice_objinv_INV(i,v,r,t)
    slice_objinv_INV_ENERGY(i,v,r,t)
    slice_objinv_INV_RSC(i,v,r,rscbin,t)
    slice_objop_GEN(i,v,r,allh,t)
    slice_objop_CAP(i,v,r,t)
    slice_objop_INV(i,v,r,t)
    slice_objop_CAP_ENERGY(i,v,r,t)
    slice_objop_CAPTRAN_ENERGY(r,rr,trtype,t)
    slice_objop_FLOW(r,rr,allh,t,trtype)
    slice_objop_EMIT(etype,eall,r,t)
    slice_scalars(*)
    state_INV(i,v,r,t)
    state_INV_ENERGY(i,v,r,t)
    state_INV_RSC(i,v,r,rscbin,t)
    state_INVTRAN(r,rr,trtype,t)
;

slice_cap_coef(i,v,r,h,t)$[tmodel(t)$valgen(i,v,r,t)] =
    avail(i,r,h)$[dispatchtech(i)$(not hydro_d(i))]
      * derate_geo_vintage(i,v)
      * (1 + sum{szn, h_szn(h,szn) * seas_cap_frac_delta(i,v,r,szn,t)})
  + avail(i,r,h)$hydro_d(i)
      * sum{szn$h_szn(h,szn), cap_hyd_szn_adj(i,szn,r) }
      * (1 + hydro_capcredit_delta(i,t)$[h_stress(h)])
  + sum{c$i_c(i,c), m_cf(i,c,v,r,h,t) }$[not dispatchtech(i)]
  + evmc_shape_gen(i,r,h) ;

slice_stor_cap_coef(i,v,r,h,t)$[tmodel(t)$valgen(i,v,r,t)$valcap(i,v,r,t)$storage_standalone(i)] =
    bcr(i) * avail(i,r,h) * (1 + sum{szn, h_szn(h,szn) * seas_cap_frac_delta(i,v,r,szn,t)}) ;

slice_dur_coef(i,v,r) = storage_duration_m(i,v,r) * (1$CSP_Storage(i) + 1$psh(i) + bcr(i)$pvb(i)) ;

slice_prescr_ret(i,v,r,t)$tmodel(t) =
    sum{(tt,ttt)$[inv_cond(i,v,r,tt,ttt)$(tmodel(tt) or tfix(tt))$valcap(i,v,r,ttt)
                  $(tt.val>=ttt.val)$(t.val>=tt.val)],
        degrade_new(i,ttt,tt) * prescribed_retirements(i,v,r,tt,ttt) } ;

slice_prescr_ret_energy(i,v,r,t)$tmodel(t) =
    sum{(tt,ttt)$[inv_cond(i,v,r,tt,ttt)$(tmodel(tt) or tfix(tt))$valcap(i,v,r,ttt)
                  $(tt.val>=ttt.val)$(t.val>=tt.val)],
        degrade_new(i,ttt,tt) * prescribed_retirements_energy(i,v,r,tt,ttt) } ;

slice_rsc_cap(r,i,rscbin,t)$tmodel(t) =
    ( m_rsc_dat(r,i,rscbin,"cap")
      - sum{(ii,v,tt)$[tfirst(tt)$rsc_agg(i,ii)$exog_rsc(i)], capacity_exog_rsc(ii,v,r,rscbin,tt)} )
    * (1$[not rsc_capacity_scalar_i(i)] + rsc_capacity_scalar(i,r,t)$rsc_capacity_scalar_i(i))
    + hyd_add_upg_cap(r,i,rscbin,t)$(Sw_HydroCapEnerUpgradeType=1) ;

slice_rsc_cost(r,i,rscbin) = m_rsc_dat(r,i,rscbin,"cost") ;

slice_objinv_INV(i,v,r,t)$[tmodel(t)$valinv(i,v,r,t)] =
    cost_cap_fin_mult(i,r,t) * cost_cap(i,t) ;

slice_objinv_INV_ENERGY(i,v,r,t)$[tmodel(t)$valinv(i,v,r,t)$battery(i)] =
    cost_cap_fin_mult(i,r,t) * cost_cap_energy(i,t) ;

slice_objinv_INV_RSC(ii,v,r,rscbin,t)$tmodel(t) =
    sum{i$[rsc_agg(i,ii)$m_rscfeas(r,i,rscbin)$valinv(i,v,r,t)$rsc_i(i)$(not spur_techs(i))],
        m_rsc_dat(r,i,rscbin,"cost") * rsc_fin_mult(i,r,t) } ;

slice_objop_GEN(i,v,r,h,t)$[tmodel(t)$valgen(i,v,r,t)] = hours(h) * (
    cost_vom(i,v,r,t)$[cost_vom(i,v,r,t)$(not storage_hybrid(i)$(not csp(i)))]
  + (heat_rate(i,v,r,t) * fuel_price(i,r,t))
      $[heat_rate(i,v,r,t)$(not gas(i))$(not bio(i))$(not cofire(i))
        $((not h2_gen(i)) or h2_gen(i)$[(Sw_H2=0) or h_stress(h)])]
  + ((1-bio_cofire_perc) * heat_rate(i,v,r,t) * fuel_price("coal-new",r,t))$[cofire(i)$heat_rate(i,v,r,t)]
  + (heat_rate(i,v,r,t) * fuel_price(i,r,t) * gasprice_adj_r(r,h))$[gas(i)$heat_rate(i,v,r,t)$(Sw_GasCurve = 2)]
  + (sum{cendiv, gasmultterm(cendiv,t) * cendiv_weights(r,cendiv) } * heat_rate(i,v,r,t) * gasprice_adj_r(r,h))$[gas(i)$(Sw_GasCurve = 1)]
  + (capture_rate("CO2",i,v,r,t) * Sw_CO2_Storage)$[not Sw_CO2_Detail]
  - ((crf(t) / crf_co2_incentive(t)) * co2_captured_incentive(i,v,r,t) * capture_rate("CO2",i,v,r,t))$co2_captured_incentive(i,v,r,t)
  - (ptc_value_scaled(i,v,t) * tc_phaseout_mult(i,v,t))$ptc_value_scaled(i,v,t)
  ) ;

slice_objop_CAP(i,v,r,t)$[tmodel(t)$valcap(i,v,r,t)] =
    cost_fom(i,v,r,t)
  - (cost_fom(i,v,r,t) * retire_penalty(t))$[retiretech(i,v,r,t)$Sw_RetirePenalty] ;

slice_objop_INV(i,v,r,t)$[tmodel(t)$valcap(i,v,r,t)$retiretech(i,v,r,t)$Sw_RetirePenalty$valinv(i,v,r,t)] =
    cost_fom(i,v,r,t) * retire_penalty(t) ;

slice_objop_CAP_ENERGY(i,v,r,t)$[tmodel(t)$valcap(i,v,r,t)$battery(i)] = cost_fom_energy(i,v,r,t) ;

slice_objop_CAPTRAN_ENERGY(r,rr,trtype,t)$[tmodel(t)$routes(r,rr,trtype,t)] =
    transmission_line_fom(r,rr,trtype) / 2
  + (cost_acdc_lcc * trans_fom_frac)$lcclike(trtype) ;

slice_objop_FLOW(r,rr,h,t,trtype)$[tmodel(t)$routes(r,rr,trtype,t)$cost_hurdle(r,rr,t)] =
    cost_hurdle(r,rr,t) * hours(h) ;

slice_objop_EMIT("process",e,r,t)$[tmodel(t)$emit_modeled(e,r,t)] = emit_tax(e,r,t) ;
slice_objop_EMIT("upstream",e,r,t)$[tmodel(t)$emit_modeled(e,r,t)$Sw_Upstream] = emit_tax(e,r,t) ;

slice_scalars("cost_scale") = cost_scale ;
slice_scalars("rhs_tolerance") = rhs_tolerance ;
slice_scalars("Sw_TransInvPRMderate") = Sw_TransInvPRMderate ;

state_INV(i,v,r,t)$tfix(t) = INV.l(i,v,r,t) ;
state_INV_ENERGY(i,v,r,t)$tfix(t) = INV_ENERGY.l(i,v,r,t) ;
state_INV_RSC(i,v,r,rscbin,t)$tfix(t) = INV_RSC.l(i,v,r,rscbin,t) ;
state_INVTRAN(r,rr,trtype,t)$tfix(t) = INVTRAN.l(r,rr,trtype,t) ;

variable Z_slice, Z_slice_inv(t), Z_slice_op(t) ;
equation eq_ObjFn_slice, eq_ObjFn_slice_inv(t), eq_ObjFn_slice_op(t) ;

eq_ObjFn_slice.. Z_slice =e= cost_scale * sum{t$tmodel(t), Z_slice_inv(t) + Z_slice_op(t) } ;

eq_ObjFn_slice_inv(t)$tmodel(t)..
    Z_slice_inv(t)
    =e=
    pvf_capital(t) * (
        sum{(i,v,r)$slice_objinv_INV(i,v,r,t), slice_objinv_INV(i,v,r,t) * INV(i,v,r,t) }
      + sum{(i,v,r)$slice_objinv_INV_ENERGY(i,v,r,t), slice_objinv_INV_ENERGY(i,v,r,t) * INV_ENERGY(i,v,r,t) }
      + sum{(i,v,r,rscbin)$slice_objinv_INV_RSC(i,v,r,rscbin,t),
            slice_objinv_INV_RSC(i,v,r,rscbin,t) * INV_RSC(i,v,r,rscbin,t) }
    ) ;

eq_ObjFn_slice_op(t)$tmodel(t)..
    Z_slice_op(t)
    =e=
    pvf_onm(t) * (
        sum{(i,v,r,h)$slice_objop_GEN(i,v,r,h,t), slice_objop_GEN(i,v,r,h,t) * GEN(i,v,r,h,t) }
      + sum{(i,v,r)$slice_objop_CAP(i,v,r,t), slice_objop_CAP(i,v,r,t) * CAP(i,v,r,t) }
      + sum{(i,v,r)$slice_objop_INV(i,v,r,t), slice_objop_INV(i,v,r,t) * INV(i,v,r,t) }
      + sum{(i,v,r)$slice_objop_CAP_ENERGY(i,v,r,t), slice_objop_CAP_ENERGY(i,v,r,t) * CAP_ENERGY(i,v,r,t) }
      + sum{(r,rr,trtype)$slice_objop_CAPTRAN_ENERGY(r,rr,trtype,t),
            slice_objop_CAPTRAN_ENERGY(r,rr,trtype,t) * CAPTRAN_ENERGY(r,rr,trtype,t) }
      + sum{(r,rr,h,trtype)$slice_objop_FLOW(r,rr,h,t,trtype), slice_objop_FLOW(r,rr,h,t,trtype) * FLOW(r,rr,h,t,trtype) }
      + sum{(etype,e,r)$slice_objop_EMIT(etype,e,r,t), slice_objop_EMIT(etype,e,r,t) * EMIT(etype,e,r,t) }
    ) ;

model ReEDSslice /
    eq_loadcon
    eq_supply_demand_balance
    eq_capacity_limit
    eq_capacity_limit_nd
    eq_cap_init_noret
    eq_cap_new_noret
    eq_cap_energy_new_noret
    eq_rsc_inv_account
    eq_rsc_INVlim
    eq_storage_capacity
    eq_storage_duration
    eq_storage_level
    eq_CAPTRAN_ENERGY
    eq_CAPTRAN_PRM
    eq_transmission_limit
    eq_emit_accounting
    eq_annual_cap
    eq_ObjFn_slice
    eq_ObjFn_slice_inv
    eq_ObjFn_slice_op
/ ;

ReEDSslice.holdfixed = 1 ;

execute_unload '%slice_dir%%ds%slice_inputs_%cur_year%.gdx' ;

OPTION lp = convert ;
ReEDSslice.optfile = 1 ;
$echo dumpgdx %slice_dir%%ds%slice_jacobian_%cur_year%.gdx > convert.opt
solve ReEDSslice minimizing Z_slice using lp ;

OPTION lp = %solver% ;
ReEDSslice.optfile = %GSw_gopt% ;
solve ReEDSslice minimizing Z_slice using lp ;

execute_unload '%slice_dir%%ds%slice_solution_%cur_year%.gdx',
    tmodel, tfix, h, h_rep, h_stress, nexth, r, land,
    valcap, valgen, valinv, initv, newv, inv_cond, retiretech,
    storage, storage_standalone, storage_hybrid, storage_interday, evmc_storage, csp, nondispatch,
    spur_techs, battery, upgrade, rsc_i, upv, wind, distpv, vre, psh, ilr,
    m_rscfeas, m_rsc_con, rsc_agg, routes, routes_prm, routes_inv,
    etype, emit_modeled, emit_capped,
    load_exog_static, tranloss, storage_eff, hours_daily, hours,
    m_capacity_exog, degrade_init, m_capacity_exog_energy, degrade_new,
    resourcescaler, trancap_init_energy, trancap_init_prm, trans_cap_delta,
    emit_rate, gwp, emit_cap, pvf_capital, pvf_onm,
    cost_cap_fin_mult, cost_cap, cost_cap_energy, rsc_fin_mult,
    cost_vom, cost_fom, cost_fom_energy, heat_rate, fuel_price,
    slice_cap_coef, slice_stor_cap_coef, slice_dur_coef, slice_prescr_ret, slice_prescr_ret_energy,
    slice_rsc_cap, slice_rsc_cost,
    slice_objinv_INV, slice_objinv_INV_ENERGY, slice_objinv_INV_RSC,
    slice_objop_GEN, slice_objop_CAP, slice_objop_INV, slice_objop_CAP_ENERGY,
    slice_objop_CAPTRAN_ENERGY, slice_objop_FLOW, slice_objop_EMIT,
    slice_scalars, state_INV, state_INV_ENERGY, state_INV_RSC, state_INVTRAN,
    rhs_eq_rsc_INVlim, flag_eq_rsc_INVlim,
    LOAD, GEN, CAP, CAP_ENERGY, INV, INV_ENERGY, INV_RSC, STORAGE_IN, STORAGE_LEVEL,
    FLOW, CAPTRAN_ENERGY, CAPTRAN_PRM, INVTRAN, EMIT, Z_slice, Z_slice_inv, Z_slice_op,
    eq_loadcon, eq_supply_demand_balance, eq_capacity_limit, eq_capacity_limit_nd,
    eq_cap_init_noret, eq_cap_new_noret, eq_cap_energy_new_noret, eq_rsc_inv_account, eq_rsc_INVlim,
    eq_storage_capacity, eq_storage_duration, eq_storage_level, eq_CAPTRAN_ENERGY, eq_CAPTRAN_PRM,
    eq_transmission_limit, eq_emit_accounting, eq_annual_cap,
    eq_ObjFn_slice, eq_ObjFn_slice_inv, eq_ObjFn_slice_op ;

if (ReEDSslice.modelStat > 1,
    abort "Slice model did not solve to optimality", ReEDSslice.modelStat) ;
