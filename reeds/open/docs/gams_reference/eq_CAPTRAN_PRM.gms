eq_CAPTRAN_PRM(r,rr,trtype,t)
    $[routes(r,rr,trtype,t)
    $routes_prm(r,rr)
    $tmodel(t)
    $(not Sw_PCM)]..

    CAPTRAN_PRM(r,rr,trtype,t)

    =e=

* [plus] initial transmission capacity
    + trancap_init_prm(r,rr,trtype)

* [plus] capacity additions up to and including the present year,
* derated by Sw_TransInvPRMderate
    + sum{tt
          $[(yeart(tt) <= yeart(t))
          $(tmodel(tt) or tfix(tt))
          $routes_inv(r,rr,trtype,tt)],
          INVTRAN(r,rr,trtype,tt)
          * (1 - Sw_TransInvPRMderate)
    }
;
