eq_CAPTRAN_ENERGY(r,rr,trtype,t)
    $[routes(r,rr,trtype,t)
    $tmodel(t)
    $(not Sw_PCM)]..

    CAPTRAN_ENERGY(r,rr,trtype,t)

    =e=

* [plus] initial transmission capacity
    + trancap_init_energy(r,rr,trtype)

* [plus] capacity additions up to and including the present year
    + sum{tt
          $[(yeart(tt) <= yeart(t))
          $(tmodel(tt) or tfix(tt))
          $routes_inv(r,rr,trtype,tt)],
          INVTRAN(r,rr,trtype,tt)
    }
;
