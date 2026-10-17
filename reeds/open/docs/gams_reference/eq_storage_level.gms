eq_storage_level(i,v,r,h,t)$[valgen(i,v,r,t)$storage(i)$tmodel(t)]..

*[plus] storage level in h+1
    sum{(hh)$[nexth(h,hh)], STORAGE_LEVEL(i,v,r,hh,t)}$(not storage_interday(i))

*[plus] the net dispatch of inter-day storage technologies
    + STORAGE_INTERDAY_DISPATCH(i,v,r,h,t)$(storage_interday(i)) * hours_daily(h)

    =e=

* only want to include storage_level from periods that have had a previous storage_level
* otherwise it becomes a free variable, implying you can charge storage without bound
    STORAGE_LEVEL(i,v,r,h,t)$(not storage_interday(i))

*[plus] storage charging
    + storage_eff(i,t) *  hours_daily(h) * (
*energy into stand-alone storage (not CSP-TES) and hydropower that adds pumping
          STORAGE_IN(i,v,r,h,t)$[storage_standalone(i) or hyd_add_pump(i)]

*energy into storage from CSP field
        + (CAP(i,v,r,t) * csp_sm(i) * sum{c$i_c(i,c), m_cf(i,c,v,r,h,t) }
          )$[CSP_Storage(i)$valcap(i,v,r,t)]
      )
*[plus] water inflow energy available for hydropower that adds pumping
    + (CAP(i,v,r,t) * avail(i,r,h) * hours_daily(h) *
        sum{szn$h_szn(h,szn), m_cf_szn(i,v,r,szn,t) }
        )$hyd_add_pump(i)

*[plus] energy into hybrid plant storage
*hybrid+storage plant: plant charging
    + storage_eff_pvb_p(i,t) * hours_daily(h)
      * STORAGE_IN_PLANT(i,v,r,h,t)$[storage_hybrid(i)$(not csp(i))$dayhours(h)$Sw_HybridPlant]

*hybrid+storage plant: grid charging
    + storage_eff_pvb_g(i,t) * hours_daily(h) 
      * STORAGE_IN_GRID(i,v,r,h,t)$[storage_hybrid(i)$(not csp(i))$Sw_HybridPlant]

*[minus] generation from stand-alone storage (discharge) and CSP
*exclude hybrid+storage plant because GEN refers to output from both the plant and the battery
    - hours_daily(h) * GEN(i,v,r,h,t)$[not storage_hybrid(i)$(not csp(i))]

*[minus] Generation from Battery (discharge) of hybrid+storage plant
    - hours_daily(h) * GEN_STORAGE(i,v,r,h,t) $[storage_hybrid(i)$(not csp(i))$Sw_HybridPlant]

*[minus] losses from reg reserves (only half because only charging half
*the time while providing reg reserves)
    - (hours_daily(h)
       * (OPRES("reg",i,v,r,h,t)$[Sw_OpRes=1] + OPRES("combo",i,v,r,h,t)$[Sw_OpRes=2])
       * (1 - storage_eff(i,t)) / 2 * reg_energy_frac
    )$[opres_h(h)]
;
