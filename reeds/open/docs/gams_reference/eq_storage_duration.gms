eq_storage_duration(i,v,r,h,t)$[valgen(i,v,r,t)$valcap(i,v,r,t)
                               $storage(i)
                               $tmodel(t)
                               $(not storage_interday(i))]..

* [plus] storage duration times storage capacity for fixed-duration techs
    storage_duration_m(i,v,r) * CAP(i,v,r,t) * (1$CSP_Storage(i) + 1$psh(i) + bcr(i)$pvb(i))

* [plus] EVMC storage has time-varying energy capacity
    + evmc_storage_energy_hours(i,r,h,t) * CAP(i,v,r,t) * (bcr(i)$evmc_storage(i))

* [plus] battery storage capacity
    + CAP_ENERGY(i,v,r,t)$battery(i)

    =g=

    STORAGE_LEVEL(i,v,r,h,t)
;
