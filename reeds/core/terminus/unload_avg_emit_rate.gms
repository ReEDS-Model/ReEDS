
*** Calculate national average emissions rate --tonnes CO2/MWh
*----- inputs ------*
$if not set gdx_folder $setglobal gdx_folder "gdx_TEST"
set inc_t(t) /2030, 2035, 2040, 2045, 2050/ ; 
 

*------- Emissions -----*
parameter emit_out;
parameter emit_st ; 

* EMIT needs to include  GEN, GEN_INCU_LOAD, GEN_INCR_LOAD * emit_rate, don't base it off of EMIT.l like how its done in e_report.gms

emit_out(e,r,t) = 
    sum{(i,v,h)$[valgen(i,v,r,t)$h_rep(h)],
        hours(h) * emit_rate("process",e,i,v,r,t)
        * (GEN.l(i,v,r,h,t) - (GEN.l(i,v,r,h,t)/storage_eff(i,t))$storage(i)
* do not include GEN_INCR_LOAD.l(i,v,r,h,t)$Sw_Incr_Load_Perc because it is a subset of GEN!!! already accounted for!
           + CCSFLEX_POW.l(i,v,r,h,t)$[ccsflex(i)$(Sw_CCSFLEX_BYP OR Sw_CCSFLEX_STO OR Sw_CCSFLEX_DAC)])
       }

* Plus emissions produced via production activities (SMR, SMR-CCS, DAC)
* The "production" of negative CO2 emissions via DAC is also included here
    + sum{(p,i,v,h)$[valcap(i,v,r,t)$i_p(i,p)$h_rep(h)],
          hours(h) * prod_emit_rate("process",e,i,t)
          * PRODUCE.l(p,i,v,r,h,t)
         }

*[minus] co2 reduce from flexible CCS capture
*capture = capture per energy used by the ccs system * CCS energy

* Flexible CCS - bypass
    - (sum{(i,v,h)$[valgen(i,v,r,t)$ccsflex_byp(i)$h_rep(h)],
        ccsflex_co2eff(i,t) * hours(h) * CCSFLEX_POW.l(i,v,r,h,t) }) $[sameas(e,"co2")]$Sw_CCSFLEX_BYP

* Flexible CCS - storage
    - (sum{(i,v,h)$[valgen(i,v,r,t)$ccsflex_sto(i)$h_rep(h)],
        ccsflex_co2eff(i,t) * hours(h) * CCSFLEX_POWREQ.l(i,v,r,h,t) }) $[sameas(e,"co2")]$Sw_CCSFLEX_STO
;


emit_st(st,t)$inc_t(t) = 
    sum((r)$r_st(r,st), emit_out("co2",r,t)) ; 

parameter emit_nat;
emit_nat(t)$inc_t(t) = 
    sum(r, emit_out("co2",r,t)) ; 

*------- Generation -----*
parameter gen_h;
parameter gen_st_vintage;

* Calculate generation and include charging, pumping, DR shifted load, and production as negative values
gen_h(i,v,r,h,t)$[valgen(i,v,r,t)$h_rep(h)] =
  GEN.l(i,v,r,h,t)
* less storage charging
  - STORAGE_IN.l(i,v,r,h,t)$[storage_standalone(i) or hyd_add_pump(i)]
* less DR shifting
*  - sum{(hh)$[dr1(i)$DR_SHIFT.l(i,v,r,h,hh,t)], DR_SHIFT.l(i,v,r,h,hh,t) / hours(h) / storage_eff(i,t)} 
* less load from hydrogen production
  - sum{(p)$[consume(i)$valcap(i,v,r,t)$i_p(i,p)], PRODUCE.l(p,i,v,r,h,t) / prod_conversion_rate(i,v,r,t)}$Sw_Prod
;
* A small amount of upv capacity is actually csp-ns, so convert it back now.
* UPV capacity is already in MWac at this point (matching csp-ns),
* so don't need to account for ILR.
gen_h("csp-ns",v,r,h,t)$[cap_cspns(r,t)]
    = cap_cspns(r,t) * m_cf("upv_6","new1",r,h,t) ;
* We have to take csp-ns generation from somewhere, so take it from upv_6 (which all the
* csp-ns-containing regions have)
gen_h("upv_6",v,r,h,t)$[cap_cspns(r,t)]
    = gen_h("upv_6",v,r,h,t) - gen_h("csp-ns",v,r,h,t) ;
* Make sure it doesn't go negative, just in case
gen_h("upv_6",v,r,h,t)$[cap_cspns(r,t)$(gen_h("upv_6",v,r,h,t) < 0)] = 0 ;


* from gen_h, aggregate up
gen_st_vintage(st,i,v,t)$inc_t(t)
    =sum((r,h)$[valgen(i,v,r,t)$r_st(r,st)$h_rep(h)], hours(h) * gen_h(i,v,r,h,t)) ; 




*------- Carbon intensity (tonnes/MWh) -----*
parameter carbon_intensity_total;

carbon_intensity_total(t)$[inc_t(t)] = 
*national, annual emissions from generation
    sum{st, emit_st(st,t)}
     /
* total generation
    sum((st,i,v)$(not storage(i)),gen_st_vintage(st,i,v,t))
;
*------- unload -----*
execute_unload 'emit_rate_v20251105_2_CES_NationalAnnualNoVint.gdx' emit_st, emit_nat, gen_st_vintage, carbon_intensity_total
;
