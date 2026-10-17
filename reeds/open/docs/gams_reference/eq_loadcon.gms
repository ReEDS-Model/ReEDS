eq_loadcon(r,h,t)$tmodel(t)..

    LOAD(r,h,t)

    =e=

*[plus] the static, exogenous load
    + load_exog_static(r,h,t)

*[plus] exogenously defined exports to Canada
* note net canadian load (when Sw_Canada = 2) is included
* in eq_supply_demand since LOAD needs to stay positive
* while net_trade can be negative and cause infeasibilities
    + can_exports_h(r,h,t)$[Sw_Canada=1]

*[plus] load from EV charging (baseline/unmanaged)
    + evmc_baseline_load(r,h,t)$Sw_EVMC

*[plus] shifted load from adopted EVMC shape resources
    + sum{(i,v)$[evmc_shape(i)$valcap(i,v,r,t)], evmc_shape_load(i,r,h) * CAP(i,v,r,t)}

*[plus] load shifted from other timeslices
    + sum{flex_type, FLEX(flex_type,r,h,t) }$Sw_EFS_flex

*[plus] Load created by production activities - only tracked during representative hours
* [metric tons/hour] / [metric tons/MWh] = [MW]
    + sum{(p,i,v)$[consume(i)$valcap(i,v,r,t)$i_p(i,p)$(not sameas(i,"dac_gas"))],
          PRODUCE(p,i,v,r,h,t) / prod_conversion_rate(i,v,r,t) }$[Sw_Prod$h_rep(h)]

*[plus] load for compressors associated with hydrogen storage injections or withdrawals
* metric tons/hour * MWh/metric tons = MW
    + sum{h2_stor$h2_stor_r(h2_stor,r),
        h2_network_load(h2_stor,t)
        * ( H2_STOR_IN(h2_stor,r,h,t) + H2_STOR_OUT(h2_stor,r,h,t) ) }$Sw_H2_CompressorLoad

* [plus] load for hydrogen pipeline compressors
* metric tons/hour * MWh/metric tons = MW
    + sum{rr$h2_routes(r,rr),
        h2_network_load("h2_compressor",t)
        * (( H2_FLOW(r,rr,h,t) + H2_FLOW(rr,r,h,t) ) / 2) }$Sw_H2_CompressorLoad

* Operations of flexibly sited load:
* - OP_LOADSITE is used when 0 < Sw_LoadSiteCF < 1
* - CAP_LOADSITE is used when Sw_LoadSiteCF = 1 because OP_LOADSITE = CAP_LOADSITE
*   (the effect is the same but avoiding the h-indexed OP_LOADSITE reduces solve time)
    + OP_LOADSITE(r,h,t)$[Sw_LoadSiteCF$(Sw_LoadSiteCF<1)$val_loadsite(r)]
    + CAP_LOADSITE(r,t)$[(Sw_LoadSiteCF=1)$val_loadsite(r)]
;
