* load
LOAD.lo(s,r,h,t_unfix) = 0 ;
LOAD.up(s,r,h,t_unfix) = +inf ;
FLEX.lo(s,flex_type,r,h,t_unfix)$Sw_EFS_flex  = 0 ;
FLEX.up(s,flex_type,r,h,t_unfix)$Sw_EFS_flex  = +inf ;
DROPPED.lo(s,r,h,t_unfix)$[(yeart(t_unfix)<Sw_StartMarkets) or (Sw_PCM=1)] = 0 ;
DROPPED.up(s,r,h,t_unfix)$[(yeart(t_unfix)<Sw_StartMarkets) or (Sw_PCM=1)] = +inf ;
EXCESS.lo(s,r,h,t_unfix)$[(yeart(t_unfix)<Sw_StartMarkets) or (Sw_PCM=1)] = 0 ;
EXCESS.up(s,r,h,t_unfix)$[(yeart(t_unfix)<Sw_StartMarkets) or (Sw_PCM=1)] = +inf ;

* generation and storage
GEN.lo(s,i,v,r,h,t_unfix)$valgen(i,v,r,t_unfix) = 0 ;
GEN.up(s,i,v,r,h,t_unfix)$valgen(i,v,r,t_unfix) = +inf ;
GEN_PLANT.lo(s,i,v,r,h,t_unfix)$[storage_hybrid(i)$(not csp(i))$valgen(i,v,r,t_unfix)$Sw_HybridPlant] = 0 ;
GEN_PLANT.up(s,i,v,r,h,t_unfix)$[storage_hybrid(i)$(not csp(i))$valgen(i,v,r,t_unfix)$Sw_HybridPlant] = +inf ;
GEN_STORAGE.lo(s,i,v,r,h,t_unfix)$[storage_hybrid(i)$(not csp(i))$valgen(i,v,r,t_unfix)$Sw_HybridPlant] = 0 ;
GEN_STORAGE.up(s,i,v,r,h,t_unfix)$[storage_hybrid(i)$(not csp(i))$valgen(i,v,r,t_unfix)$Sw_HybridPlant] = +inf ;
MINGEN.lo(s,r,szn,t_unfix)$Sw_Mingen = 0 ;
MINGEN.up(s,r,szn,t_unfix)$Sw_Mingen = +inf ;
STORAGE_IN.lo(s,i,v,r,h,t_unfix)$[valgen(i,v,r,t_unfix)$(storage_standalone(i) or hyd_add_pump(i))] = 0 ;
STORAGE_IN.up(s,i,v,r,h,t_unfix)$[valgen(i,v,r,t_unfix)$(storage_standalone(i) or hyd_add_pump(i))] = +inf ;
STORAGE_IN_PLANT.lo(s,i,v,r,h,t_unfix)$[valgen(i,v,r,t_unfix)$storage_hybrid(i)$(not csp(i))$Sw_HybridPlant] = 0 ;
STORAGE_IN_PLANT.up(s,i,v,r,h,t_unfix)$[valgen(i,v,r,t_unfix)$storage_hybrid(i)$(not csp(i))$Sw_HybridPlant] = +inf ;
STORAGE_IN_GRID.lo(s,i,v,r,h,t_unfix)$[valgen(i,v,r,t_unfix)$storage_hybrid(i)$(not csp(i))$Sw_HybridPlant] = 0 ;
STORAGE_IN_GRID.up(s,i,v,r,h,t_unfix)$[valgen(i,v,r,t_unfix)$storage_hybrid(i)$(not csp(i))$Sw_HybridPlant] = +inf ;
STORAGE_LEVEL.lo(s,i,v,r,h,t_unfix)$[valgen(i,v,r,t_unfix)$storage(i)] = 0 ;
STORAGE_LEVEL.up(s,i,v,r,h,t_unfix)$[valgen(i,v,r,t_unfix)$storage(i)] = +inf ;
STORAGE_INTERDAY_LEVEL.lo(s,i,v,r,allszn,t_unfix)$[valgen(i,v,r,t_unfix)$storage_interday(i)$numpartitions(allszn)] = 0 ;
STORAGE_INTERDAY_LEVEL.up(s,i,v,r,allszn,t_unfix)$[valgen(i,v,r,t_unfix)$storage_interday(i)$numpartitions(allszn)] = +inf ;
RAMPUP.lo(s,i,r,h,hh,t_unfix)$[Sw_StartCost$startcost(i)$numhours_nexth(h,hh)$valgen_irt(i,r,t_unfix)] = 0 ;
RAMPUP.up(s,i,r,h,hh,t_unfix)$[Sw_StartCost$startcost(i)$numhours_nexth(h,hh)$valgen_irt(i,r,t_unfix)] = +inf ;

* flexible CCS
CCSFLEX_POW.lo(s,i,v,r,h,t_unfix)$[ccsflex(i)$valgen(i,v,r,t_unfix)$(Sw_CCSFLEX_BYP OR Sw_CCSFLEX_STO OR Sw_CCSFLEX_DAC)] = 0 ;
CCSFLEX_POW.up(s,i,v,r,h,t_unfix)$[ccsflex(i)$valgen(i,v,r,t_unfix)$(Sw_CCSFLEX_BYP OR Sw_CCSFLEX_STO OR Sw_CCSFLEX_DAC)] = +inf ;
CCSFLEX_POWREQ.lo(s,i,v,r,h,t_unfix)$[ccsflex_sto(i)$valgen(i,v,r,t_unfix)$Sw_CCSFLEX_STO] = 0 ;
CCSFLEX_POWREQ.up(s,i,v,r,h,t_unfix)$[ccsflex_sto(i)$valgen(i,v,r,t_unfix)$Sw_CCSFLEX_STO] = +inf ;
CCSFLEX_STO_STORAGE_LEVEL.lo(s,i,v,r,h,t_unfix)$[ccsflex_sto(i)$valgen(i,v,r,t_unfix)$Sw_CCSFLEX_STO] = 0 ;
CCSFLEX_STO_STORAGE_LEVEL.up(s,i,v,r,h,t_unfix)$[ccsflex_sto(i)$valgen(i,v,r,t_unfix)$Sw_CCSFLEX_STO] = +inf ;

* trade
FLOW.lo(s,r,rr,h,t_unfix,trtype)$routes(r,rr,trtype,t_unfix) = 0 ;
FLOW.up(s,r,rr,h,t_unfix,trtype)$routes(r,rr,trtype,t_unfix) = +inf ;
OPRES_FLOW.lo(s,ortype,r,rr,h,t_unfix)$[Sw_OpRes$opres_model(ortype)$opres_routes(r,rr,t_unfix)$opres_h(h)] = 0 ;
OPRES_FLOW.up(s,ortype,r,rr,h,t_unfix)$[Sw_OpRes$opres_model(ortype)$opres_routes(r,rr,t_unfix)$opres_h(h)] = +inf ;
PRMTRADE.lo(s,r,rr,trtype,ccseason,t_unfix)$[routes(r,rr,trtype,t_unfix)$routes_prm(r,rr)] = 0 ;
PRMTRADE.up(s,r,rr,trtype,ccseason,t_unfix)$[routes(r,rr,trtype,t_unfix)$routes_prm(r,rr)] = +inf ;

* operating reserve
OPRES.lo(s,ortype,i,v,r,h,t_unfix)$[Sw_OpRes$valgen(i,v,r,t_unfix)$reserve_frac(i,ortype)$opres_h(h)] = 0 ;
OPRES.up(s,ortype,i,v,r,h,t_unfix)$[Sw_OpRes$valgen(i,v,r,t_unfix)$reserve_frac(i,ortype)$opres_h(h)] = +inf ;

* variable fuel amounts
GASUSED.lo(s,cendiv,gb,h,t_unfix)$[(Sw_GasCurve=0)$h_rep(h)] = 0 ;
GASUSED.up(s,cendiv,gb,h,t_unfix)$[(Sw_GasCurve=0)$h_rep(h)] = +inf ;
VGASBINQ_NATIONAL.lo(s,fuelbin,t_unfix)$[Sw_GasCurve=1] = 0 ;
VGASBINQ_NATIONAL.up(s,fuelbin,t_unfix)$[Sw_GasCurve=1] = +inf ;
VGASBINQ_REGIONAL.lo(s,fuelbin,cendiv,t_unfix)$[Sw_GasCurve=1] = 0 ;
VGASBINQ_REGIONAL.up(s,fuelbin,cendiv,t_unfix)$[Sw_GasCurve=1] = +inf ;
BIOUSED.lo(s,bioclass,r,t_unfix)$[sum{(i,v)$(bio(i) or cofire(i)), valgen(i,v,r,t_unfix) }] = 0 ;
BIOUSED.up(s,bioclass,r,t_unfix)$[sum{(i,v)$(bio(i) or cofire(i)), valgen(i,v,r,t_unfix) }] = +inf ;

* RECS
RECS.lo(s,RPSCat,i,st,ast,t_unfix)$[stfeas(st)$RecMap(i,RPSCat,st,ast,t_unfix)$(stfeas(ast) or sameas(ast,"voluntary"))$Sw_StateRPS] = 0 ;
RECS.up(s,RPSCat,i,st,ast,t_unfix)$[stfeas(st)$RecMap(i,RPSCat,st,ast,t_unfix)$(stfeas(ast) or sameas(ast,"voluntary"))$Sw_StateRPS] = +inf ;
ACP_PURCHASES.lo(s,RPSCat,st,t_unfix)$[(stfeas(st) or sameas(st,"voluntary"))$Sw_StateRPS] = 0 ;
ACP_PURCHASES.up(s,RPSCat,st,t_unfix)$[(stfeas(st) or sameas(st,"voluntary"))$Sw_StateRPS] = +inf ;

* transmission
CONVERSION.lo(s,r,h,intype,outtype,t_unfix)$Sw_VSC = 0 ;
CONVERSION.up(s,r,h,intype,outtype,t_unfix)$Sw_VSC = +inf ;
CONVERSION_PRM.lo(s,r,ccseason,intype,outtype,t_unfix)$Sw_VSC = 0 ;
CONVERSION_PRM.up(s,r,ccseason,intype,outtype,t_unfix)$Sw_VSC = +inf ;

* water
WAT.lo(s,i,v,w,r,h,t_unfix)$[i_water(i)$valgen(i,v,r,t_unfix)$Sw_WaterMain] = 0 ;
WAT.up(s,i,v,w,r,h,t_unfix)$[i_water(i)$valgen(i,v,r,t_unfix)$Sw_WaterMain] = +inf ;

* H2 and DAC production
PRODUCE.lo(s,p,i,v,r,h,t_unfix)$[consume(i)$i_p(i,p)$valcap(i,v,r,t_unfix)$h_rep(h)$Sw_Prod] = 0 ;
PRODUCE.up(s,p,i,v,r,h,t_unfix)$[consume(i)$i_p(i,p)$valcap(i,v,r,t_unfix)$h_rep(h)$Sw_Prod] = +inf ;
H2_FLOW.lo(s,r,rr,h,t_unfix)$[h2_routes(r,rr)$(Sw_H2=2)] = 0 ;
H2_FLOW.up(s,r,rr,h,t_unfix)$[h2_routes(r,rr)$(Sw_H2=2)] = +inf ;
H2_STOR_IN.lo(s,h2_stor,r,h,t_unfix)$[(h2_stor_r(h2_stor,r))$(Sw_H2=2)] = 0 ;
H2_STOR_IN.up(s,h2_stor,r,h,t_unfix)$[(h2_stor_r(h2_stor,r))$(Sw_H2=2)] = +inf ;
H2_STOR_OUT.lo(s,h2_stor,r,h,t_unfix)$[(h2_stor_r(h2_stor,r))$(Sw_H2=2)] = 0 ;
H2_STOR_OUT.up(s,h2_stor,r,h,t_unfix)$[(h2_stor_r(h2_stor,r))$(Sw_H2=2)] = +inf ;
H2_STOR_LEVEL.lo(s,h2_stor,r,actualszn,h,t_unfix)$[(h2_stor_r(h2_stor,r))$(Sw_H2=2)$(Sw_H2_StorTimestep=2)] = 0 ;
H2_STOR_LEVEL.up(s,h2_stor,r,actualszn,h,t_unfix)$[(h2_stor_r(h2_stor,r))$(Sw_H2=2)$(Sw_H2_StorTimestep=2)] = +inf ;
H2_STOR_LEVEL_SZN.lo(s,h2_stor,r,actualszn,t_unfix)$[(h2_stor_r(h2_stor,r))$(Sw_H2=2)$(Sw_H2_StorTimestep=1)] = 0 ;
H2_STOR_LEVEL_SZN.up(s,h2_stor,r,actualszn,t_unfix)$[(h2_stor_r(h2_stor,r))$(Sw_H2=2)$(Sw_H2_StorTimestep=1)] = +inf ;
CREDIT_H2PTC.lo(s,i,v,r,h,t_unfix)$[valgen_h2ptc(i,v,r,t_unfix)$h_rep(h)$Sw_H2_PTC$h2_ptc_years(t_unfix)$(yeart(t_unfix)>=h2_demand_start)] = 0 ;
CREDIT_H2PTC.up(s,i,v,r,h,t_unfix)$[valgen_h2ptc(i,v,r,t_unfix)$h_rep(h)$Sw_H2_PTC$h2_ptc_years(t_unfix)$(yeart(t_unfix)>=h2_demand_start)] = +inf ;

* CO2 capture and storage
CO2_CAPTURED.lo(s,r,h,t_unfix)$Sw_CO2_Detail = 0 ;
CO2_CAPTURED.up(s,r,h,t_unfix)$Sw_CO2_Detail = +inf ;
CO2_STORED.lo(s,r,cs,h,t_unfix)$[Sw_CO2_Detail$r_cs(r,cs)] = 0 ;
CO2_STORED.up(s,r,cs,h,t_unfix)$[Sw_CO2_Detail$r_cs(r,cs)] = +inf ;
CO2_FLOW.lo(s,r,rr,h,t_unfix)$[Sw_CO2_Detail$co2_routes(r,rr)] = 0 ;
CO2_FLOW.up(s,r,rr,h,t_unfix)$[Sw_CO2_Detail$co2_routes(r,rr)] = +inf ;

* Positive/negative variables
EMIT.lo(s,etype,e,r,t_unfix)$emit_modeled(s,e,r,t_unfix) = -inf ;
EMIT.up(s,etype,e,r,t_unfix)$emit_modeled(s,e,r,t_unfix) = +inf ;
STORAGE_INTERDAY_DISPATCH.lo(s,i,v,r,h,t_unfix)$[storage_interday(i)$valgen(i,v,r,t_unfix)] = -inf ;
STORAGE_INTERDAY_DISPATCH.up(s,i,v,r,h,t_unfix)$[storage_interday(i)$valgen(i,v,r,t_unfix)] = +inf ;
STORAGE_INTERDAY_LEVEL_MAX_DAY.lo(s,i,v,r,allszn,t_unfix)$[storage_interday(i)$valgen(i,v,r,t_unfix)] = -inf ;
STORAGE_INTERDAY_LEVEL_MAX_DAY.up(s,i,v,r,allszn,t_unfix)$[storage_interday(i)$valgen(i,v,r,t_unfix)] = +inf ;
STORAGE_INTERDAY_LEVEL_MIN_DAY.lo(s,i,v,r,allszn,t_unfix)$[storage_interday(i)$valgen(i,v,r,t_unfix)] = -inf ;
STORAGE_INTERDAY_LEVEL_MIN_DAY.up(s,i,v,r,allszn,t_unfix)$[storage_interday(i)$valgen(i,v,r,t_unfix)] = +inf ;
