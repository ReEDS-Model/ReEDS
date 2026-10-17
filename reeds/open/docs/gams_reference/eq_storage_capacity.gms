eq_storage_capacity(i,v,r,h,t)$[valgen(i,v,r,t)
    $(storage_standalone(i)$(not evmc_storage(i))
        or evmc_storage(i)
            $[evmc_storage_charge_frac(i,r,h,t)$evmc_storage_discharge_frac(i,r,h,t)]
        or storage_hybrid(i)$(not csp(i)))
    $tmodel(t)]..

* [plus] Capacity of all storage technologies
    (CAP(i,v,r,t) * bcr(i) * avail(i,r,h)
       * (1 + sum{szn, h_szn(h,szn) * seas_cap_frac_delta(i,v,r,szn,t)})
    )$valcap(i,v,r,t)

    =g=

* [plus] Generation from storage, excluding hybrid+storage and adjusting evmc_storage for time-varying discharge (deferral) availability
    GEN(i,v,r,h,t)$(not storage_hybrid(i)$(not csp(i))) / (1$(not evmc_storage(i)) + evmc_storage_discharge_frac(i,r,h,t)$evmc_storage(i))

* [plus] Generation from battery of hybrid+storage
    + GEN_STORAGE(i,v,r,h,t)$[storage_hybrid(i)$(not csp(i))$Sw_HybridPlant]

* [plus] Storage charging
* excludes hybrid plant+storage and adjusting evmc_storage for time-varying charge (add back deferred EV load) availability
    + STORAGE_IN(i,v,r,h,t)$[not storage_hybrid(i)$(not csp(i))] / (1$(not evmc_storage(i)) + evmc_storage_charge_frac(i,r,h,t)$evmc_storage(i)) 
   
* hybrid+storage plant: plant generation
    + STORAGE_IN_PLANT(i,v,r,h,t)$[storage_hybrid(i)$(not csp(i))$dayhours(h)$Sw_HybridPlant]
* hybrid+storage plant: Grid generation
    + STORAGE_IN_GRID(i,v,r,h,t)$[storage_hybrid(i)$(not csp(i))$Sw_HybridPlant]

* [plus] Operating reserves
    + sum{ortype$[Sw_OpRes$opres_model(ortype)$opres_h(h)],
          reserve_frac(i,ortype) * OPRES(ortype,i,v,r,h,t) }
;
