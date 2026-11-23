* Battery reserve-margin value by stress hour, for stressday_cc.py. Run from a final restart file:
*   gams stressday_resmarg.gms r=<run>/g00files/<case>_<endyear>i0 --outgdx=<path>.gdx
* Same terms as valnew('val_resmarg') in report.gms
* but without the sum over stress hours and without inv_cap_ratio (applied in python).
parameter resmarg_h(i,r,allh,t) "(GEN - STORAGE_IN) of valinv vintages * res_marg price, $" ;
parameter price_h(r,allh,t) "res_marg price, $/MW per stress timeslice" ;
price_h(r,allh,t)$[tmodel_new(t)$h_stress_t(allh,t)] =
    eq_supply_demand_balance.m(r,allh,t) * (1 / cost_scale) * (1 / pvf_onm(t)) ;
resmarg_h(i,r,allh,t)$[battery(i)$tmodel_new(t)$h_stress_t(allh,t)] =
    sum{v$valinv(i,v,r,t), GEN.l(i,v,r,allh,t) - STORAGE_IN.l(i,v,r,allh,t)} * price_h(r,allh,t) ;
execute_unload "%outgdx%" resmarg_h, price_h ;
