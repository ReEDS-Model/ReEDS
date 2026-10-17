eq_supply_demand_balance(r,h,t)$tmodel(t)..

* generation from all land-based sources, including storage discharge
    sum{(i,v)$[valgen(i,v,r,t)$land(r)], GEN(i,v,r,h,t) }

* [plus] net AC and LCC DC transmission with imports reduced by losses
    + sum{(trtype,rr)$[routes(rr,r,trtype,t)$notvsc(trtype)],
          (1-tranloss(rr,r,trtype)) * FLOW(rr,r,h,t,trtype) }
    - sum{(trtype,rr)$[routes(r,rr,trtype,t)$notvsc(trtype)],
          FLOW(r,rr,h,t,trtype) }

* [plus] net AC/DC conversion through VSC converter stations
* Note that we only need "AC" in the CONVERSION variable (not LCC, B2B, etc)
* since all it does here is act as a catch-all for "not VSC"
    + (CONVERSION(r,h,"VSC","AC",t) * converter_efficiency_vsc)$[Sw_VSC$val_converter(r,t)]
    - (CONVERSION(r,h,"AC","VSC",t) / converter_efficiency_vsc)$[Sw_VSC$val_converter(r,t)]

* [minus] storage charging; not hybrid+storage
    - sum{(i,v)$[valcap(i,v,r,t)$(storage_standalone(i) or hyd_add_pump(i))], STORAGE_IN(i,v,r,h,t) }

* [minus] energy into storage for hybrid+storage from grid
    - sum{(i,v)$[valcap(i,v,r,t)$storage_hybrid(i)$(not csp(i))], STORAGE_IN_GRID(i,v,r,h,t) }$Sw_HybridPlant

* [plus] dropped/excess load ONLY if before Sw_StartMarkets
    + DROPPED(r,h,t)$[(yeart(t)<Sw_StartMarkets) or (Sw_PCM=1)]
    - EXCESS(r,h,t)$[(yeart(t)<Sw_StartMarkets) or (Sw_PCM=1)]

    =e=

* must equal demand
    LOAD(r,h,t)
;
