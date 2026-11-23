
* Author: Kelly Eurek
* Date: 2019/08/14
* Source Bialek (1996). Tracing the flow of electricity

* ======================
* Calculate Flow Factors
* ======================

* --- calculate inflows, outflows, and flows between BAs ---

parameter
  flow_in(s,rr,allh,t)      "--MW-- average flow of power into BA rr during time-slice h"
  flow_out(s,r,allh,t)      "--MW-- average flow of power out of BA r during time-slice h"
  flow_ba2ba(s,r,rr,allh,t) "--MW-- average flow of power out of BA r into BA rr during time-slice h"
;

flow_in(s,rr,h,t)$tmodel_new(t) = sum{(r,trtype)$routes(rr,r,trtype,t), FLOW.l(s,r,rr,h,t,trtype) } ;
flow_out(s,r,h,t)$tmodel_new(t) = sum{(rr,trtype)$routes(rr,r,trtype,t), FLOW.l(s,r,rr,h,t,trtype) } ;
flow_ba2ba(s,r,rr,h,t)$[tmodel_new(t)$sum{trtype,routes(rr,r,trtype,t) }] =
    sum{(trtype)$[routes(rr,r,trtype,t)], FLOW.l(s,r,rr,h,t,trtype) } ;

* --- calculate the "total load" ---

Parameter totload(s,r,allh,t) "--MW-- load modified to include charging of storage and transmission losses" ;

totload(s,r,h,t)$[tmodel_new(t)] =
    load_exog(r,h,t) + can_exports_h(r,h,t)
  + sum{(i,v)$[valcap(i,v,r,t)$(storage_standalone(i) or hyd_add_pump(i))], STORAGE_IN.l(s,i,v,r,h,t)}
  + sum{(rr,trtype)$routes(rr,r,trtype,t), tranloss(rr,r,trtype) * FLOW.l(s,rr,r,h,t,trtype)}
;

* --- calcultate power flowing through a balancing area ---

Parameter flow_through(s,r,allh,t) "--MW-- flow through balancing area r during time-slice h: inflow + total generation" ;

flow_through(s,r,h,t)$tmodel_new(t) = totload(s,r,h,t) + flow_out(s,r,h,t)

* --- calculate total generation (including storage discharge) ---

Parameter totgen(s,r,allh,t) "--MW-- total generation in region r during time-slice h" ;

totgen(s,r,h,t)$tmodel_new(t) =
    load_exog(r,h,t) + can_exports_h(r,h,t)

  + sum{(i,v)$[valcap(i,v,r,t)$(storage_standalone(i) or hyd_add_pump(i))], STORAGE_IN.l(s,i,v,r,h,t) }

  + sum{(rr,trtype)$routes(rr,r,trtype,t),
      + FLOW.l(s,r,rr,h,t,trtype)
      - FLOW.l(s,rr,r,h,t,trtype)
  }

;

* --- define upstream and downstream power matricies ---

Parameter A_upstream(s,rr,r,allh,t) "upstream power distribution matrix" ;
* see equation (4) in Bialek (1996)
A_upstream(s,rr,r,h,t)$tmodel_new(t) = 0 ;
A_upstream(s,r,r,h,t)$tmodel_new(t) = 1 ;
A_upstream(s,rr,r,h,t)$[(flow_ba2ba(s,r,rr,h,t)>0)$(flow_through(s,r,h,t)>0)$tmodel_new(t)] = - flow_ba2ba(s,r,rr,h,t) / flow_through(s,r,h,t) ;

Parameter A_downstream(s,r,rr,allh,t) "downstream power distribution matrix" ;
* see equation (10) in Bialek (1996)
A_downstream(s,r,rr,h,t)$tmodel_new(t) = 0 ;
A_downstream(s,r,r,h,t)$tmodel_new(t) = 1 ;
A_downstream(s,r,rr,h,t)$[(flow_ba2ba(s,r,rr,h,t)>0)$(flow_through(s,rr,h,t)>0)$tmodel_new(t)] = -flow_ba2ba(s,r,rr,h,t) / flow_through(s,rr,h,t) ;

* --- calculate the inverse of the upstream and downstream power matricies ---

parameter
  Ainv_upstream(s,r,rr,allh,t) "inverse of A_upstream"
  Ainv_downstream(s,r,rr,allh,t) "inverse of A_downstream"
  a(r,rr) "temp matrix for A"
  ainv(r,rr) "temp matrix for A-inverse"
;

Ainv_upstream(s,r,rr,h,t)$sum{trtype,routes(rr,r,trtype,t) } = 0 ;
Ainv_downstream(s,r,rr,h,t)$sum{trtype,routes(rr,r,trtype,t) } = 0 ;
a(r,rr) = 0 ;
ainv(r,rr) = 0 ;

Loop((s,h,t)$[tmodel_new(t)],
a(rr,r) = A_upstream(s,rr,r,h,t) ;
execute_unload 'outputs%ds%gdxforinverse.gdx' r, a ;
executeTool 'invert r a ainv gdxIn=outputs%ds%gdxforinverse.gdx  gdxOut=outputs%ds%gdxfrominverse.gdx' ;
execute_load 'outputs%ds%gdxfrominverse.gdx', ainv ;
Ainv_upstream(s,rr,r,h,t) = ainv(rr,r) ;
) ;

Loop((s,h,t)$[tmodel_new(t)],
a(r,rr) = A_downstream(s,r,rr,h,t) ;
execute_unload 'outputs%ds%gdxforinverse.gdx' r, a ;
executeTool 'invert r a ainv gdxIn=outputs%ds%gdxforinverse.gdx  gdxOut=outputs%ds%gdxfrominverse.gdx' ;
execute_load 'outputs%ds%gdxfrominverse.gdx', ainv ;
Ainv_downstream(s,r,rr,h,t) = ainv(r,rr) ;
) ;

* --- remove gdx files that were created to do the inverse calculation ---
execute 'rm outputs%ds%gdxforinverse.gdx' ;
execute 'rm outputs%ds%gdxfrominverse.gdx' ;
execute 'rm outputs%ds%invert1.log' ;
execute 'rm outputs%ds%invert2.log' ;

* --- calculate upsteram and downstream power fractions ---

parameter
  powerfrac_upstream(s,rr,r,allh,t)     "--unitless-- power fraction upstream  : fraction of power at BA rr that was generated at BA r during time-slice h"
  powerfrac_downstream(s,r,rr,allh,t)   "--unitless-- power fraction downstream: fraction of power generated at BA r that serves load at BA rr during time-slice h"
;

powerfrac_upstream(s,r,rr,h,t)$sum{trtype,routes(rr,r,trtype,t) } = 0 ;
powerfrac_downstream(s,r,rr,h,t)$sum{trtype,routes(rr,r,trtype,t) } = 0 ;

* see equation (6) in Bialek (1996)
powerfrac_upstream(s,rr,r,h,t)$[(flow_through(s,rr,h,t)>0)$tmodel_new(t)] = 1 / flow_through(s,rr,h,t) * Ainv_upstream(s,rr,r,h,t) * totgen(s,r,h,t) ;
powerfrac_upstream(s,rr,r,h,t)$[(powerfrac_upstream(s,rr,r,h,t)<1e-3)$tmodel_new(t)] = 0 ;

* see equation (12) in Bialek (1996)
powerfrac_downstream(s,r,rr,h,t)$[(flow_through(s,r,h,t)>0)$tmodel_new(t)] = 1 / flow_through(s,r,h,t) * Ainv_downstream(s,r,rr,h,t) * totload(s,rr,h,t) ;
powerfrac_downstream(s,r,rr,h,t)$[(powerfrac_downstream(s,r,rr,h,t)<1e-3)$tmodel_new(t)] = 0 ;

* --- write the outputs ---
execute_unload "outputs%ds%rep_powerfrac_%fname%.gdx" powerfrac_downstream, powerfrac_upstream ;
