eq_annual_cap(eall,t)$[sum{tt, emit_cap(eall,tt) }$tmodel(t)$(Sw_AnnualCap>0)]..

* exogenous CO2 cap (Sw_AnnualCap = 1) or CO2e cap (Sw_AnnualCap > 1)
    emit_cap(eall,t)

    =g=

* must exceed annual endogenous emissions by CO2 pollutant (when Sw_AnnualCap=1) or CO2e pollutants (CO2, CH4, NO2 pollutants when Sw_AnnualCap=2 and additional H2 leakage when Sw_AnnualCap=3)
    sum{(e,r)$emit_capped(e), (EMIT("process",e,r,t) + EMIT("upstream",e,r,t)$Sw_Upstream) * gwp(e) }    
;
