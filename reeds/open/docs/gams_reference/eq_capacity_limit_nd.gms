eq_capacity_limit_nd(i,v,r,h,t)$[tmodel(t)$valgen(i,v,r,t)$nondispatch(i)]..

*sum of non-dispatchable capacity multiplied by its rated capacity factor,
    + sum{c$i_c(i,c), m_cf(i,c,v,r,h,t) } * CAP(i,v,r,t)

    =e=

*must be equal to generation
    GEN(i,v,r,h,t)

*[plus] sum of operating reserves by type
    + sum{ortype$[Sw_OpRes$opres_model(ortype)$reserve_frac(i,ortype)$opres_h(h)],
          OPRES(ortype,i,v,r,h,t) }
;
