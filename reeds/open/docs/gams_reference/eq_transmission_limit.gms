eq_transmission_limit(r,rr,h,t,trtype)$[tmodel(t)$routes(r,rr,trtype,t)]..

* Representative periods use the energy capacity
    (CAPTRAN_ENERGY(r,rr,trtype,t) * (1 + trans_cap_delta(h,t)))$h_rep(h)
* Stress periods use the PRM capacity
* Because these periods are assumed to be mutually exclusive, each timeslice should only
* have a single capacity applied.
    + (CAPTRAN_PRM(r,rr,trtype,t) * (1 + trans_cap_delta(h,t)))$[h_stress(h)$routes_prm(r,rr)]

    =g=

*[plus] energy flows
    + FLOW(r,rr,h,t,trtype)


*[plus] operating reserve flows (operating reserves can only be transferred across AC lines)
    + sum{ortype$[Sw_OpRes$opres_h(h)$aclike(trtype)$opres_routes(r,rr,t)$opres_model(ortype)],
          OPRES_FLOW(ortype,r,rr,h,t) * opres_mult }
;
