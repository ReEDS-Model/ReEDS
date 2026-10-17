eq_capacity_limit(i,v,r,h,t)
    $[tmodel(t)$valgen(i,v,r,t)
    $(not spur_techs(i))
    $(not storage_standalone(i))$(not storage_hybrid(i)$(not csp(i)))$(not nondispatch(i))]..
    
*total amount of dispatchable, non-hydro capacity
    avail(i,r,h)$[dispatchtech(i)$(not hydro_d(i))]
    * derate_geo_vintage(i,v)
    * (1 + sum{szn, h_szn(h,szn) * seas_cap_frac_delta(i,v,r,szn,t)})
    * CAP(i,v,r,t)

*total amount of dispatchable hydro capacity
    + avail(i,r,h)$hydro_d(i)
      * CAP(i,v,r,t) 
      * sum{szn$h_szn(h,szn), cap_hyd_szn_adj(i,szn,r) }
      * (1 + hydro_capcredit_delta(i,t)$[h_stress(h)])

*sum of non-dispatchable capacity multiplied by its rated capacity factor,
*only vre technologies are curtailable.
* This term accounts for energy-only and capacity-only upsizing,
* which is initially implemented only for hydro.
    + (sum{c$i_c(i,c), m_cf(i,c,v,r,h,t) }
        * (CAP(i,v,r,t)
*add energy embedded in energy-only upsizing
            + sum{(tt,rscbin)$[(tmodel(tt) or tfix(tt))],
                INV_ENER_UP(i,v,r,rscbin,tt)$allow_ener_up(i,v,r,rscbin,tt)
*subtract energy that would be embedded in a capacity-only upsizing
                - degrade_new(i,tt,t) * INV_CAP_UP(i,v,r,rscbin,tt)$allow_cap_up(i,v,r,rscbin,tt) })
      )$[not dispatchtech(i)]
*add EVMC shape generation
    + (evmc_shape_gen(i,r,h) * CAP(i,v,r,t))

    =g=

*must exceed generation
    GEN(i,v,r,h,t)

*[plus] sum of operating reserves by type
    + sum{ortype$[Sw_OpRes$reserve_frac(i,ortype)$opres_h(h)$opres_model(ortype)],
          OPRES(ortype,i,v,r,h,t) }

*[plus] power consumed for flexible ccs
    + CCSFLEX_POW(i,v,r,h,t) $[ccsflex(i)$(Sw_CCSFLEX_BYP OR Sw_CCSFLEX_STO OR Sw_CCSFLEX_DAC)]
;
