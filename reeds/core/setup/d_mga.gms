*==============================================
* -- Modeling to Generate Alternatives (MGA) --
*==============================================

Equation eq_MGA_CostEnvelope(t) "--$-- System cost must be within allowed envelope" ;
eq_MGA_CostEnvelope(t)$[tmodel(t)$Sw_MGA]..
    (z_rep_inv(t) + z_rep_op(t)) * (1 + Sw_MGA_CostDelta)
    =g=
    Z_inv(t) + Z_op(t)
;

* ---------------------------------------------------------------------------

Equation eq_MGA_CapEnvelopeHi(tg,t) "--MW-- National capacity must be within allowed envelope" ;
eq_MGA_CapEnvelopeHi(tg,t)$[tmodel(t)$Sw_MGA$Sw_MGA_CapDelta]..
    cap_tg_total(tg,t) * (1 + Sw_MGA_CapDelta)
    =g=
    sum{(i,v,r)$[valcap(i,v,r,t)$tg_i(tg,i)], CAP(i,v,r,t)}
;

* ---------------------------------------------------------------------------

Equation eq_MGA_CapEnvelopeLo(tg,t) "--MW-- National capacity must be within allowed envelope" ;
eq_MGA_CapEnvelopeLo(tg,t)$[tmodel(t)$Sw_MGA$Sw_MGA_CapDelta]..
    sum{(i,v,r)$[valcap(i,v,r,t)$tg_i(tg,i)], CAP(i,v,r,t)}
    =g=
    cap_tg_total(tg,t) * (1 - Sw_MGA_CapDelta)
;

* ---------------------------------------------------------------------------
$ifthen.mgaobj %GSw_MGA_Objective% == 'capacity'
Equation eq_MGA_Objective "--MW-- Defines generation capacity for MGA" ;
Variable MGA_OBJ "--MW-- Capacity of technology to be minimized/maximied" ;
eq_MGA_Objective$Sw_MGA..
    MGA_OBJ
    =e=
    sum{(i,v,r,t)
        $[tmodel(t)
        $valcap(i,v,r,t)
        $%GSw_MGA_SubObjective%(i)],
        CAP(i,v,r,t) 
        * sum{i_subtech$i_subsets(i,i_subtech), mga_weights(r,i_subtech)}
    }
;

* ---------------------------------------------------------------------------

$elseif.mgaobj %GSw_MGA_Objective% == 'generation'
Equation eq_MGA_Objective "--MW-- Defines generation for MGA" ;
Variable MGA_OBJ "--MWh-- Generation of technology to be minimized/maximied" ;
eq_MGA_Objective$Sw_MGA..
    MGA_OBJ
    =e=
    sum{(i,v,r,h,t)
        $[tmodel(t)
        $valgen(i,v,r,t)
        $%GSw_MGA_SubObjective%(i)],
        GEN(i,v,r,h,t) * hours(h) 
        * sum{i_subtech$i_subsets(i,i_subtech), mga_weights(r,i_subtech)}
    }
;

* ---------------------------------------------------------------------------

$elseif.mgaobj %GSw_MGA_Objective% == 'transmission'
Equation eq_MGA_Objective "--MW-- Defines transmission capacity for MGA" ;
Variable MGA_OBJ "--MW-- Transmission capacity of all types" ;
eq_MGA_Objective$Sw_MGA..
    MGA_OBJ
    =e=
    sum{(r,rr,trtype,t)
        $[tmodel(t)
        $routes(r,rr,trtype,t)],
        CAPTRAN_ENERGY(r,rr,trtype,t)
    }
;

* ---------------------------------------------------------------------------

$elseif.mgaobj %GSw_MGA_Objective% == 'rasharing'
Equation eq_MGA_Objective "--MWh-- Defines RA flows for MGA" ;
Variable MGA_OBJ "--MWh-- Flows between NERC regions during stress periods" ;
eq_MGA_Objective$Sw_MGA..
    MGA_OBJ
    =e=
    sum{(r,rr,h,trtype,nercr,nercrr,t)
        $[tmodel(t)
        $routes(r,rr,trtype,t)
        $routes_prm(r,rr)
        $routes_nercr(nercr,nercrr,r,rr)
        $h_stress(h)],
        FLOW(r,rr,h,t,trtype) * hours(h)
    }
;

* ---------------------------------------------------------------------------

$elseif.mgaobj %GSw_MGA_Objective% == 'co2'
Equation eq_MGA_Objective "--tonne-- Defines CO2 emissions for MGA" ;
Variable MGA_OBJ "--tonne-- Direct (process) CO2 emissions" ;
eq_MGA_Objective$Sw_MGA..
    MGA_OBJ
    =e=
    sum{(r,t)
        $[tmodel(t)],
        EMIT("process","CO2",r,t)
    }
;

* ---------------------------------------------------------------------------

$elseif.mgaobj %GSw_MGA_Objective% == 'employment'
Equation eq_MGA_Objective "--job-years-- Defines number of job-years for MGA" ;
Variable MGA_OBJ "--job-years-- Total job-years to be minimized/maximized" ;
eq_MGA_Objective$Sw_MGA..
    MGA_OBJ
    =e=
    sum{(i,v,r,t)
        $[tmodel(t)
        $valcap(i,v,r,t)],
        CAP(i,v,r,t) * pvf_onm(t) * employment_factor_plant(i,"fom")
    }
    + sum{(i,v,r,h,t)
          $[tmodel(t)
          $valgen(i,v,r,t)],
          GEN(i,v,r,h,t) * pvf_onm(t) * hours(h) * employment_factor_plant(i,"vom")
    }
    + sum{(i,v,r,t)
          $[tmodel(t)
          $valinv(i,v,r,t)],
          INV(i,v,r,t) * pvf_capital(t) * employment_factor_plant(i,"construction")
    }
    
    # AC construction employment formula here is slightly different than in
    # e_report.gms as only cumulative term TRAN_CAPEX_BINS is included here vs
    # annual term used in e_report.gms
    + sum{(r,rr,tscbin,t)
          $[tmodel(t)
          $routes_inv(r,rr,"AC",t)
          $tsc_binwidth(r,rr,tscbin)],
          trans_cost_cap_fin_mult(t) 
          * ((TRAN_CAPEX_BINS(r,rr,tscbin,t)) 
          * pvf_capital(t)
          * employment_factor_inter_transmission("construction"))}

    + sum{trtype
          $[routes_inv(r,rr,trtype,t)
          $(not aclike(trtype))],
          trans_cost_cap_fin_mult(t)
          * transmission_cost_nonac(r,rr,trtype)
          * INVTRAN(r,rr,trtype,t)
          * employment_factor_inter_transmission("construction") / 2 }      
    
    + sum{(r,rr,trtype,t)
          $[tmodel(t)
          $routes(r,rr,trtype,t)],
          CAPTRAN_ENERGY(r,rr,trtype,t) 
          * pvf_onm(t)
          * employment_factor_inter_transmission("fom")  }
;


$endif.mgaobj
