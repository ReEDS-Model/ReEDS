* Round problematic variables  
* Non-rounded parameters can sometimes cause numerical issues when summing over tfix in model equations  
if(Sw_RemoveSmallNumbers = 1,
    CAP.l(i,v,r,tfix)$[abs(CAP.l(i,v,r,tfix)) < rhs_tolerance] = 0 ;
    CAP_ENERGY.l(i,v,r,tfix)$[abs(CAP_ENERGY.l(i,v,r,tfix)) < rhs_tolerance] = 0 ;
    UPGRADES.l(i,v,r,tfix)$[abs(UPGRADES.l(i,v,r,tfix)) < rhs_tolerance] = 0 ;
    CAP_ABOVE_LIM.l(tg,r,tfix)$[abs(CAP_ABOVE_LIM.l(tg,r,tfix)) < rhs_tolerance] = 0 ;
    INV.l(i,v,r,tfix)$[abs(INV.l(i,v,r,tfix)) < rhs_tolerance] = 0 ;
    INV_ENERGY.l(i,v,r,tfix)$[abs(INV_ENERGY.l(i,v,r,tfix)) < rhs_tolerance] = 0 ;
    INV_RSC.l(i,v,r,rscbin,tfix)$[abs(INV_RSC.l(i,v,r,rscbin,tfix)) < rhs_tolerance] = 0 ;
    INV_POI.l(r,tfix)$[abs(INV_POI.l(r,tfix)) < rhs_tolerance] = 0 ;
    H2_STOR_INV.l(h2_stor,r,tfix)$[abs(H2_STOR_INV.l(h2_stor,r,tfix)) < rhs_tolerance] = 0 ;
    H2_TRANSPORT_INV.l(r,rr,tfix) $[abs(H2_TRANSPORT_INV.l(r,rr,tfix) ) < rhs_tolerance] = 0 ;
);
    
*load variable
LOAD.fx(s,r,h,tfix) = LOAD.l(s,r,h,tfix) ;
FLEX.fx(flex_type,r,h,tfix)$Sw_EFS_flex  = FLEX.l(flex_type,r,h,tfix) ;
*     PEAK_FLEX.fx(r,ccseason,tfix)$Sw_EFS_flex = PEAK_FLEX.l(r,ccseason,tfix) ;
DROPPED.fx(r,h,tfix)$[(yeart(tfix)<Sw_StartMarkets)] = DROPPED.l(r,h,tfix) ;
EXCESS.fx(r,h,tfix)$[(yeart(tfix)<Sw_StartMarkets)] = EXCESS.l(r,h,tfix) ;
CAP_LOADSITE.fx(r,tfix)$[Sw_LoadSiteCF$val_loadsite(r)] = CAP_LOADSITE.l(r,tfix) ;
INV_LOADSITE.fx(r,tfix)$[Sw_LoadSiteCF$val_loadsite(r)] = INV_LOADSITE.l(r,tfix) ;
OP_LOADSITE.fx(s,r,h,tfix)$[Sw_LoadSiteCF$(Sw_LoadSiteCF<1)$val_loadsite(r)] = OP_LOADSITE.l(s,r,h,tfix) ;

* capacity and investment variables
CAP.fx(i,v,r,tfix)$[valcap(i,v,r,tfix)] = CAP.l(i,v,r,tfix) ;
CAP_ENERGY.fx(i,v,r,tfix)$[valcap(i,v,r,tfix)$battery(i)] = CAP_ENERGY.l(i,v,r,tfix) ;
CAP_ABOVE_LIM.fx(tg,r,tfix)$[(yeart(tfix)>=model_builds_start_yr)
                                $(sum{(tgg,rr), queue_limit(tgg,rr,tfix)})
                                $sum{(i,newv)$tg_i(tg,i), valinv(i,newv,r,tfix)}] = CAP_ABOVE_LIM.l(tg,r,tfix) ;
CAP_SDBIN.fx(i,v,r,ccseason,sdbin,tfix)$[valcap(i,v,r,tfix)$(storage(i) or hyd_add_pump(i))$(not csp(i))$Sw_PRM_CapCredit] = CAP_SDBIN.l(i,v,r,ccseason,sdbin,tfix) ;
CAP_SDBIN_ENERGY.fx(i,v,r,ccseason,sdbin,tfix)$[valcap(i,v,r,tfix)$battery(i)$Sw_PRM_CapCredit] = CAP_SDBIN_ENERGY.l(i,v,r,ccseason,sdbin,tfix) ;
GROWTH_BIN.fx(gbin,i,st,tfix)$[sum{r$[r_st(r,st)], valinv_irt(i,r,tfix) }$stfeas(st)$Sw_GrowthPenalties$(yeart(tfix)<=Sw_GrowthPenLastYear)] = GROWTH_BIN.l(gbin,i,st,tfix) ;
INV.fx(i,v,r,tfix)$[valinv(i,v,r,tfix)] = INV.l(i,v,r,tfix) ;
INV_ENERGY.fx(i,v,r,tfix)$[valinv(i,v,r,tfix)$battery(i)] = INV_ENERGY.l(i,v,r,tfix) ;
INV_REFURB.fx(i,v,r,tfix)$[valinv(i,v,r,tfix)$refurbtech(i)] = INV_REFURB.l(i,v,r,tfix) ;
INV_RSC.fx(i,v,r,rscbin,tfix)$[valinv(i,v,r,tfix)$rsc_i(i)$m_rscfeas(r,i,rscbin)] = INV_RSC.l(i,v,r,rscbin,tfix) ;
CAP_RSC.fx(i,v,r,rscbin,tfix)$[valcap(i,v,r,tfix)$rsc_i(i)$m_rscfeas(r,i,rscbin)] = CAP_RSC.l(i,v,r,rscbin,tfix) ;
INV_CAP_UP.fx(i,v,r,rscbin,tfix)$[allow_cap_up(i,v,r,rscbin,tfix)] = INV_CAP_UP.l(i,v,r,rscbin,tfix) ;
INV_ENER_UP.fx(i,v,r,rscbin,tfix)$[allow_ener_up(i,v,r,rscbin,tfix)] = INV_ENER_UP.l(i,v,r,rscbin,tfix) ;
UPGRADES.fx(i,v,r,tfix)$[valcap(i,v,r,tfix)$upgrade(i)] = UPGRADES.l(i,v,r,tfix) ;
UPGRADES_RETIRE.fx(i,v,r,tfix)$[valcap(i,v,r,tfix)$upgrade(i)] = UPGRADES_RETIRE.l(i,v,r,tfix) ;
EXTRA_PRESCRIP.fx(i,v,r,tfix)$[force_prescribe(i,v,r,tfix)$valinv(i,v,r,tfix)] = EXTRA_PRESCRIP.l(i,v,r,tfix) ;
EXTRA_PRESCRIP_ENERGY.fx(i,v,r,tfix)$[force_prescribe(i,v,r,tfix)$valinv(i,v,r,tfix)] = EXTRA_PRESCRIP_ENERGY.l(i,v,r,tfix) ;

* generation and storage variables
GEN.fx(s,i,v,r,h,tfix)$valgen(i,v,r,tfix) = GEN.l(s,i,v,r,h,tfix) ;
GEN_PLANT.fx(s,i,v,r,h,tfix)$[storage_hybrid(i)$(not csp(i))$valgen(i,v,r,tfix)$Sw_HybridPlant] = GEN_PLANT.l(s,i,v,r,h,tfix) ;
GEN_STORAGE.fx(s,i,v,r,h,tfix)$[storage_hybrid(i)$(not csp(i))$valgen(i,v,r,tfix)$Sw_HybridPlant] = GEN_STORAGE.l(s,i,v,r,h,tfix) ;
MINGEN.fx(s,r,szn,tfix)$Sw_Mingen = MINGEN.l(s,r,szn,tfix) ;
STORAGE_IN.fx(s,i,v,r,h,tfix)$[valgen(i,v,r,tfix)$(storage_standalone(i) or hyd_add_pump(i))] = STORAGE_IN.l(s,i,v,r,h,tfix) ;
STORAGE_IN_PLANT.fx(s,i,v,r,h,tfix)$[valgen(i,v,r,tfix)$storage_hybrid(i)$(not csp(i))$Sw_HybridPlant] = STORAGE_IN_PLANT.l(s,i,v,r,h,tfix) ;
STORAGE_IN_GRID.fx(s,i,v,r,h,tfix)$[valgen(i,v,r,tfix)$storage_hybrid(i)$(not csp(i))$Sw_HybridPlant] = STORAGE_IN_GRID.l(s,i,v,r,h,tfix) ;
STORAGE_LEVEL.fx(s,i,v,r,h,tfix)$[valgen(i,v,r,tfix)$storage(i)$(not storage_interday(i))] = STORAGE_LEVEL.l(s,i,v,r,h,tfix) ;
STORAGE_INTERDAY_LEVEL.fx(s,i,v,r,allszn,tfix)$[valgen(i,v,r,tfix)$storage_interday(i)] = STORAGE_INTERDAY_LEVEL.l(s,i,v,r,allszn,tfix) ;
STORAGE_INTERDAY_DISPATCH.fx(s,i,v,r,allh,tfix)$[valgen(i,v,r,tfix)$storage_interday(i)] = STORAGE_INTERDAY_DISPATCH.l(s,i,v,r,allh,tfix) ;
STORAGE_INTERDAY_LEVEL_MAX_DAY.fx(s,i,v,r,allszn,tfix)$[valgen(i,v,r,tfix)$storage_interday(i)] = STORAGE_INTERDAY_LEVEL_MAX_DAY.l(s,i,v,r,allszn,tfix) ;
STORAGE_INTERDAY_LEVEL_MIN_DAY.fx(s,i,v,r,allszn,tfix)$[valgen(i,v,r,tfix)$storage_interday(i)] = STORAGE_INTERDAY_LEVEL_MIN_DAY.l(s,i,v,r,allszn,tfix) ;
AVAIL_SITE.fx(x,h,tfix)$[Sw_SpurScen$xfeas(x)] = AVAIL_SITE.l(x,h,tfix) ;
RAMPUP.fx(s,i,r,h,hh,tfix)$[Sw_StartCost$startcost(i)$numhours_nexth(h,hh)$valgen_irt(i,r,tfix)] = RAMPUP.l(s,i,r,h,hh,tfix) ;

* flexible CCS variables
CCSFLEX_POW.fx(s,i,v,r,h,tfix)$[ccsflex(i)$valgen(i,v,r,tfix)$(Sw_CCSFLEX_BYP OR Sw_CCSFLEX_STO OR Sw_CCSFLEX_DAC)] = CCSFLEX_POW.l(s,i,v,r,h,tfix) ;
CCSFLEX_POWREQ.fx(s,i,v,r,h,tfix)$[ccsflex_sto(i)$valgen(i,v,r,tfix)$Sw_CCSFLEX_STO] = CCSFLEX_POWREQ.l(s,i,v,r,h,tfix) ;
CCSFLEX_STO_STORAGE_LEVEL.fx(s,i,v,r,h,tfix)$[ccsflex_sto(i)$valgen(i,v,r,tfix)$Sw_CCSFLEX_STO] = CCSFLEX_STO_STORAGE_LEVEL.l(s,i,v,r,h,tfix) ;
CCSFLEX_STO_STORAGE_CAP.fx(i,v,r,tfix)$[ccsflex_sto(i)$valcap(i,v,r,tfix)$Sw_CCSFLEX_STO] = CCSFLEX_STO_STORAGE_CAP.l(i,v,r,tfix) ;

* trade variables
FLOW.fx(s,r,rr,h,tfix,trtype)$routes(r,rr,trtype,tfix) = FLOW.l(s,r,rr,h,tfix,trtype) ;
OPRES_FLOW.fx(s,ortype,r,rr,h,tfix)$[Sw_OpRes$opres_model(ortype)$opres_routes(r,rr,tfix)$opres_h(h)] = OPRES_FLOW.l(s,ortype,r,rr,h,tfix) ;
PRMTRADE.fx(s,r,rr,trtype,ccseason,tfix)$[routes(r,rr,trtype,tfix)$routes_prm(r,rr)] = PRMTRADE.l(s,r,rr,trtype,ccseason,tfix) ;

* operating reserve variables
OPRES.fx(s,ortype,i,v,r,h,tfix)$[Sw_OpRes$valgen(i,v,r,tfix)$reserve_frac(i,ortype)$opres_h(h)] = OPRES.l(s,ortype,i,v,r,h,tfix) ;

* variable fuel amounts
GASUSED.fx(s,cendiv,gb,h,tfix)$[(Sw_GasCurve=0)$h_rep(h)] = GASUSED.l(s,cendiv,gb,h,tfix) ;
VGASBINQ_NATIONAL.fx(s,fuelbin,tfix)$[Sw_GasCurve=1] = VGASBINQ_NATIONAL.l(s,fuelbin,tfix) ;
VGASBINQ_REGIONAL.fx(s,fuelbin,cendiv,tfix)$[Sw_GasCurve=1] = VGASBINQ_REGIONAL.l(s,fuelbin,cendiv,tfix) ;
BIOUSED.fx(s,bioclass,r,tfix)$[sum{(i,v)$(bio(i) or cofire(i)), valgen(i,v,r,tfix) }] = BIOUSED.l(s,bioclass,r,tfix) ;

* RECS variables
RECS.fx(RPSCat,i,st,ast,tfix)$[stfeas(st)$RecMap(i,RPSCat,st,ast,tfix)$(stfeas(ast) or sameas(ast,"voluntary"))$Sw_StateRPS] = RECS.l(RPSCat,i,st,ast,tfix) ;
ACP_Purchases.fx(RPSCat,st,tfix)$[(stfeas(st) or sameas(st,"voluntary"))$Sw_StateRPS] = ACP_Purchases.l(RPSCat,st,tfix) ;
EMIT.fx(s,etype,e,r,tfix)$emit_modeled(s,e,r,tfix) = EMIT.l(s,etype,e,r,tfix) ;

* transmission variables
CAPTRAN_ENERGY.fx(r,rr,trtype,tfix)$routes(r,rr,trtype,tfix) = CAPTRAN_ENERGY.l(r,rr,trtype,tfix) ;
CAPTRAN_PRM.fx(r,rr,trtype,tfix)$[routes(r,rr,trtype,tfix)$routes_prm(r,rr)] = CAPTRAN_PRM.l(r,rr,trtype,tfix) ;
CAPTRAN_GRP.fx(transgrp,transgrpp,tfix)$trancap_init_transgroup(transgrp,transgrpp,"AC") = CAPTRAN_GRP.l(transgrp,transgrpp,tfix) ;
INVTRAN.fx(r,rr,trtype,tfix)$routes_inv(r,rr,trtype,tfix) = INVTRAN.l(r,rr,trtype,tfix) ;
INVTRAN_AC.fx(r,rr,tscbin,tfix)$routes_inv(r,rr,"AC",tfix) = INVTRAN_AC.l(r,rr,tscbin,tfix) ;
INV_CONVERTER.fx(r,tfix)$val_converter(r,tfix) = INV_CONVERTER.l(r,tfix) ;
CAP_CONVERTER.fx(r,tfix)$val_converter(r,tfix) = CAP_CONVERTER.l(r,tfix) ;
CONVERSION.fx(s,r,h,intype,outtype,tfix)$Sw_VSC = CONVERSION.l(s,r,h,intype,outtype,tfix) ;
CONVERSION_PRM.fx(s,r,ccseason,intype,outtype,tfix)$Sw_VSC = CONVERSION_PRM.l(s,r,ccseason,intype,outtype,tfix) ;
CAP_SPUR.fx(x,tfix)$[Sw_SpurScen$xfeas(x)] = CAP_SPUR.l(x,tfix) ;
INV_SPUR.fx(x,tfix)$[Sw_SpurScen$xfeas(x)] = INV_SPUR.l(x,tfix) ;
INV_POI.fx(r,tfix)$Sw_TransIntraCost = INV_POI.l(r,tfix) ;
TRAN_CAPEX_BINS.fx(r,rr,tscbin,tfix)$[routes_inv(r,rr,"AC",tfix)$tsc_binwidth(r,rr,tscbin)] = TRAN_CAPEX_BINS.l(r,rr,tscbin,tfix) ;

* water climate variables
WATCAP.fx(i,v,r,tfix)$[valcap(i,v,r,tfix)$Sw_WaterMain$Sw_WaterCapacity] = WATCAP.l(i,v,r,tfix) ;
WAT.fx(s,i,v,w,r,h,tfix)$[i_water(i)$valgen(i,v,r,tfix)$Sw_WaterMain] = WAT.l(s,i,v,w,r,h,tfix) ;
WATER_CAPACITY_LIMIT_SLACK.fx(wst,r,tfix)$[Sw_WaterMain$Sw_WaterCapacity] = WATER_CAPACITY_LIMIT_SLACK.l(wst,r,tfix) ;

*H2 and DAC production variables
PRODUCE.fx(s,p,i,v,r,h,tfix)$[consume(i)$i_p(i,p)$valcap(i,v,r,tfix)$h_rep(h)$Sw_Prod] = PRODUCE.l(s,p,i,v,r,h,tfix) ;
H2_FLOW.fx(s,r,rr,h,tfix)$[h2_routes(r,rr)$(Sw_H2 = 2)] = H2_FLOW.l(s,r,rr,h,tfix) ;
H2_TRANSPORT_INV.fx(r,rr,tfix)$[h2_routes(r,rr)$(Sw_H2 = 2)] = H2_TRANSPORT_INV.l(r,rr,tfix) ;
H2_STOR_INV.fx(h2_stor,r,tfix)$[(h2_stor_r(h2_stor,r))$(Sw_H2=2)] = H2_STOR_INV.l(h2_stor,r,tfix) ;
H2_STOR_CAP.fx(h2_stor,r,tfix)$[(h2_stor_r(h2_stor,r))$(Sw_H2=2)] = H2_STOR_CAP.l(h2_stor,r,tfix) ;
H2_STOR_IN.fx(s,h2_stor,r,h,tfix)$[(h2_stor_r(h2_stor,r))$(Sw_H2=2)] = H2_STOR_IN.l(s,h2_stor,r,h,tfix) ;
H2_STOR_OUT.fx(s,h2_stor,r,h,tfix)$[(h2_stor_r(h2_stor,r))$(Sw_H2=2)] = H2_STOR_OUT.l(s,h2_stor,r,h,tfix) ;
H2_STOR_LEVEL.fx(s,h2_stor,r,actualszn,h,tfix)$[(h2_stor_r(h2_stor,r))$(Sw_H2=2)$(Sw_H2_StorTimestep=2)] = H2_STOR_LEVEL.l(s,h2_stor,r,actualszn,h,tfix) ;
H2_STOR_LEVEL_SZN.fx(s,h2_stor,r,actualszn,tfix)$[(h2_stor_r(h2_stor,r))$(Sw_H2=2)$(Sw_H2_StorTimestep=1)] = H2_STOR_LEVEL_SZN.l(s,h2_stor,r,actualszn,tfix) ;

*CO2-related variables
CO2_CAPTURED.fx(s,r,h,tfix)$Sw_CO2_Detail = CO2_CAPTURED.l(s,r,h,tfix) ;
CO2_STORED.fx(s,r,cs,h,tfix)$[Sw_CO2_Detail$r_cs(r,cs)] = CO2_STORED.l(s,r,cs,h,tfix) ;
CO2_FLOW.fx(s,r,rr,h,tfix)$[Sw_CO2_Detail$co2_routes(r,rr)] = CO2_FLOW.l(s,r,rr,h,tfix) ;
CO2_TRANSPORT_INV.fx(r,rr,tfix)$[Sw_CO2_Detail$co2_routes(r,rr)] = CO2_TRANSPORT_INV.l(r,rr,tfix) ;
CO2_SPURLINE_INV.fx(r,cs,tfix)$[Sw_CO2_Detail$r_cs(r,cs)] = CO2_SPURLINE_INV.l(r,cs,tfix) ;
