eq_Objfn_op(t)$tmodel(t)..

         Z_op(t)

         =e=

         pvf_onm(t) * (

* --- variable O&M costs---
* all technologies except hybrid plant and DAC
              sum{(i,v,r,h)$[valgen(i,v,r,t)$cost_vom(i,v,r,t)$(not storage_hybrid(i)$(not csp(i)))],
                   hours(h) * cost_vom(i,v,r,t) * GEN(i,v,r,h,t) }

* hybrid plant (plant)
            + sum{(i,v,r,h)$[valgen(i,v,r,t)$cost_vom_pvb_p(i,v,r,t)$storage_hybrid(i)$(not csp(i))],
                   hours(h) * cost_vom_pvb_p(i,v,r,t) * GEN_PLANT(i,v,r,h,t) }$Sw_HybridPlant

* hybrid plant (Battery)
            + sum{(i,v,r,h)$[valgen(i,v,r,t)$cost_vom_pvb_b(i,v,r,t)$storage_hybrid(i)$(not csp(i))],
                   hours(h) * cost_vom_pvb_b(i,v,r,t) * GEN_STORAGE(i,v,r,h,t) }$Sw_HybridPlant

* --- fixed O&M costs---
* generation
              + sum{(i,v,r)$[valcap(i,v,r,t)],
                   cost_fom(i,v,r,t) * CAP(i,v,r,t) }

              + sum{(i,v,r)$[valcap(i,v,r,t)$battery(i)],
                   cost_fom_energy(i,v,r,t) * CAP_ENERGY(i,v,r,t) }

* transmission lines (defined in both directions so divide by 2)
              + sum{(r,rr,trtype)$routes(r,rr,trtype,t),
                    transmission_line_fom(r,rr,trtype) * CAPTRAN_ENERGY(r,rr,trtype,t) / 2 }

* LCC and B2B AC/DC converter stations. For each MW of linking capacity we add 1 MW of converter
* capacity to each end of the link. But because CAPTRAN_ENERGY is defined in both directions
* (r < rr and rr < r), we already count the link capacity twice, so don't need to multiply
* by 2 to get the converter capacity.
              + sum{(r,rr,trtype)$[lcclike(trtype)$routes(r,rr,trtype,t)],
                    cost_acdc_lcc * trans_fom_frac * CAPTRAN_ENERGY(r,rr,trtype,t) }

* VSC AC/DC converter stations
              + sum{r$val_converter(r,t),
                    cost_acdc_vsc * trans_fom_frac * CAP_CONVERTER(r,t) }

* spur lines modeled as part of supply curve
              + sum{(i,v,r,rscbin)
                    $[m_rscfeas(r,i,rscbin)$valcap(i,v,r,t)
                    $rsc_i(i)$(not spur_techs(i))$(not sccapcosttech(i))],
                    m_rsc_dat(r,i,rscbin,"cost_trans") * trans_fom_frac * CAP_RSC(i,v,r,rscbin,t) }

* spur lines modeled explicitly
              + sum{x$[Sw_SpurScen$xfeas(x)],
                    spurline_cost(x) * trans_fom_frac * CAP_SPUR(x,t) }

* intra-zone network reinforcement (only for new capacity; don't include it for existing POI
* capacity because it's not a great estimate of the actual FOM cost of all existing transmission)
              + sum{r$Sw_TransIntraCost,
                    Sw_TransIntraCost * 1000 * trans_fom_frac
                    * sum{tt$[(yeart(tt)<=yeart(t))$(tmodel(tt) or tfix(tt))], INV_POI(r,tt) } }

* --- penalty for retiring a technology (represents friction in retirements)---
              - sum{(i,v,r)$[valcap(i,v,r,t)$retiretech(i,v,r,t)$Sw_RetirePenalty],
                   cost_fom(i,v,r,t) * retire_penalty(t) *
                   (CAP(i,v,r,t)
                    - INV(i,v,r,t)$valinv(i,v,r,t)
                    - INV_REFURB(i,v,r,t)$[valinv(i,v,r,t)$refurbtech(i)$Sw_Refurb] 
                    - UPGRADES(i,v,r,t)$[upgrade(i)$Sw_Upgrades] )
                   }

* ---operating reserve costs---
              + sum{(i,v,r,h,ortype)$[Sw_OpRes$valgen(i,v,r,t)$cost_opres(i,ortype,t)$reserve_frac(i,ortype)$opres_model(ortype)$opres_h(h)],
                   hours(h) * cost_opres(i,ortype,t) * OPRES(ortype,i,v,r,h,t) }


* --- cost of coal, nuclear, and other fixed-price fuels (except coal used for cofiring),
* plus cost of H2 fuel when using fixed price (Sw_H2=0) or during stress periods.
* When using endogenous H2 price (Sw_H2=1 or Sw_H2=2), H2 fuel cost is captured elsewhere
* via the capex + opex costs of H2 production and its associated electricity demand.
              + sum{(i,v,r,h)$[valgen(i,v,r,t)$heat_rate(i,v,r,t)
                             $(not gas(i))$(not bio(i))$(not cofire(i))
                             $((not h2_gen(i)) or h2_gen(i)$[(Sw_H2=0) or h_stress(h)])],
                   hours(h) * heat_rate(i,v,r,t) * fuel_price(i,r,t) * GEN(i,v,r,h,t) }

* --- startup/ramping costs
              + sum{(i,r,h,hh)$[Sw_StartCost$startcost(i)$numhours_nexth(h,hh)$valgen_irt(i,r,t)],
                    startcost(i) * numhours_nexth(h,hh) * RAMPUP(i,r,h,hh,t) }

* --cofire coal consumption---
* cofire bio consumption already accounted for in accounting of BIOUSED
              + sum{(i,v,r,h)$[valgen(i,v,r,t)$cofire(i)$heat_rate(i,v,r,t)],
                   (1-bio_cofire_perc) * hours(h) * heat_rate(i,v,r,t)
                   * fuel_price("coal-new",r,t) * GEN(i,v,r,h,t) }

* --- cost of natural gas---
*Sw_GasCurve = 2 (static natural gas prices)
*first - gas consumed for electricity generation
              + sum{(i,v,r,h)$[valgen(i,v,r,t)$gas(i)$heat_rate(i,v,r,t)$(Sw_GasCurve = 2)],
                   hours(h) * heat_rate(i,v,r,t) * fuel_price(i,r,t) * GEN(i,v,r,h,t) * gasprice_adj_r(r,h) }

*second - gas consumed by gas-powered DAC
              + sum{(v,r,h)$[valcap("dac_gas",v,r,t)$(Sw_GasCurve = 2)],
                   hours(h) * dac_gas_cons_rate("dac_gas",v,t) * PRODUCE("DAC","dac_gas",v,r,h,t) }$Sw_DAC_Gas

*Sw_GasCurve = 0 (census division supply curves natural gas prices)
              + sum{(cendiv,gb), sum{h, hours(h) * GASUSED(cendiv,gb,h,t) * gasprice_adj_cendiv(cendiv,h) }
                   * gasprice(cendiv,gb,t)
                   }$(Sw_GasCurve = 0)

*Sw_GasCurve = 3 (national supply curve for natural gas prices with census division multipliers)
              + sum{(h,cendiv,gb), hours(h) * GASUSED(cendiv,gb,h,t)
                   * gasadder_cd(cendiv,t,h) * gasprice_adj_cendiv(cendiv,h) + gasprice_nat_bin(gb,t)
                   }$(Sw_GasCurve = 3)

*Sw_GasCurve = 1 (national and census division supply curves for natural gas prices)
*first - anticipated costs of gas consumption given last year's amount
              + (sum{(i,r,v,cendiv,h)$[valgen(i,v,r,t)$gas(i)],
                   gasmultterm(cendiv,t) * cendiv_weights(r,cendiv) *
                   hours(h) * heat_rate(i,v,r,t) * GEN(i,v,r,h,t) * gasprice_adj_r(r,h) }

*second - adjustments based on changes from last year's consumption at the regional and national level
              + sum{(fuelbin,cendiv),
                   gasbinp_regional(fuelbin,cendiv,t) * VGASBINQ_REGIONAL(fuelbin,cendiv,t) }

              + sum{(fuelbin),
                   gasbinp_national(fuelbin,t) * VGASBINQ_NATIONAL(fuelbin,t) }

              )$[Sw_GasCurve = 1]

* ---cost of biofuel consumption and biomass transport---
              + sum{(r,bioclass)$[sum{(i,v)$(bio(i) or cofire(i)), valgen(i,v,r,t) }],
                   BIOUSED(bioclass,r,t) *
                   (sum{usda_region$r_usda(r,usda_region), biosupply(usda_region, bioclass, "price") } + bio_transport_cost) }

* --- hurdle costs for transmission flow ---
              + sum{(r,rr,h,trtype)$[routes(r,rr,trtype,t)$cost_hurdle(r,rr,t)],
                   cost_hurdle(r,rr,t) * FLOW(r,rr,h,t,trtype) * hours(h) }

* --- taxes on emissions---
              + sum{(e,r), (EMIT("process",e,r,t) + EMIT("upstream",e,r,t)$Sw_Upstream) * emit_tax(e,r,t) }

* --cost of CO2 transport and storage from CCS--
              + sum{(i,v,r,h)$[valgen(i,v,r,t)],
                              hours(h) * capture_rate("CO2",i,v,r,t) * GEN(i,v,r,h,t) * Sw_CO2_Storage }$[not Sw_CO2_Detail]

* --cost of CO2 transport and storage from SMR CCS--
              + sum{(p,v,r,h)$[i_p("smr_ccs",p)$valcap("smr_ccs",v,r,t)],
                              hours(h) * smr_capture_rate * smr_co2_intensity * PRODUCE(p,"smr_ccs",v,r,h,t) * Sw_CO2_Storage }$[Sw_H2$(not Sw_CO2_Detail)]

* --cost of CO2 transport and storage from DAC--
              + sum{(p,i,v,r,h)$[dac(i)$valcap(i,v,r,t)$i_p(i,p)],
                              hours(h) * PRODUCE(p,i,v,r,h,t) * Sw_CO2_Storage }$[Sw_DAC$(not Sw_CO2_Detail)]

* ---State RPS alternative compliance payments---
              + sum{(RPSCat,st)$[(stfeas(st) or sameas(st,"voluntary"))$RecPerc(RPSCat,st,t)$(not acp_disallowed(st,RPSCat))],
                    acp_price(st,t) * ACP_PURCHASES(RPSCat,st,t)
                   }$[(yeart(t)>=firstyear_RPS)$Sw_StateRPS]

* --- dropped/excess load (ONLY if before Sw_StartMarkets)
              + sum{(r,h)$[(yeart(t)<Sw_StartMarkets) or (Sw_PCM=1)],
                    (DROPPED(r,h,t) + EXCESS(r,h,t) ) * hours(h) * cost_dropped_load }

* --- costs from producing products (for now DAC and/or H2)---
              + sum{(p,i,v,r,h)$[(h2(i) or dac(i))$valcap(i,v,r,t)$i_p(i,p)$h_rep(h)],
                    hours(h) * cost_prod(i,v,r,t) * PRODUCE(p,i,v,r,h,t) }$Sw_Prod

* --- H2 transport network fixed OM costs (compute cumulative sum of investments to get total capacity)
               + sum{(r,rr)$h2_routes_inv(r,rr), cost_h2_transport_fom(r,rr,t) 
                              * sum{tt$[(tfix(tt) or tmodel(tt))$(yeart(tt)<=yeart(t))],
                                   H2_TRANSPORT_INV(r,rr,t) } }$[Sw_H2 = 2]

* -- H2 intra-regional transport investment costs, levelized per kg of H2 produced --
* Unit conversion: [hours] * [tonnes/hour] * [$/kg] * [kg/tonne] = [$]
               + sum{(i,v,r,h)$[valcap(i,v,r,t)$newv(v)$i_p(i,"H2")$h_rep(h)], 
                    hours(h) * PRODUCE("H2",i,v,r,h,t) * (Sw_H2_IntraReg_Transport * 1e3)}$[Sw_H2]

* --- H2 storage fixed OM costs (compute cumulative sum of investments to get total capacity)
               + sum{(h2_stor,r)$h2_stor_r(h2_stor,r),
                     cost_h2_storage_fom(h2_stor,t) * H2_STOR_CAP(h2_stor,r,t) }$(Sw_H2=2)

* --- Retail adder for electricity consuming technologies ---
               + sum{(p,i,v,r,h)$[valcap(i,v,r,t)$i_p(i,p)$h_rep(h)$Sw_RetailAdder$Sw_Prod],
                    hours(h) * Sw_RetailAdder * PRODUCE(p,i,v,r,h,t) / prod_conversion_rate(i,v,r,t) }

* --- CO2 pipeline fixed OM costs
              + sum{(r,rr)$co2_routes(r,rr), cost_co2_pipeline_fom(r,rr,t)
                              * sum{tt$[(tfix(tt) or tmodel(tt))$(yeart(tt)<=yeart(t))],
                                   CO2_TRANSPORT_INV(r,rr,tt) } }$[Sw_CO2_Detail$(yeart(t)>=co2_detail_startyr)]

* --- CO2 spurline fixed OM costs
              + sum{(r,cs)$[csfeas(cs)$r_cs(r,cs)], cost_co2_spurline_fom(r,cs,t)
                              * sum{tt$[(tfix(tt) or tmodel(tt))$(yeart(tt)<=yeart(t))],
                                   CO2_SPURLINE_INV(r,cs,tt) } }$[Sw_CO2_Detail$(yeart(t)>=co2_detail_startyr)]

* --- CO2 injection break even costs
              + sum{(r,cs,h)$r_cs(r,cs), hours(h) * CO2_STORED(r,cs,h,t) * cost_co2_stor_bec(cs) }$[Sw_CO2_Detail$(yeart(t)>=co2_detail_startyr)]

* --- Tax credit for CO2 stored ---
* note conversion to 12-year CRF given length of CO2 captured incentive payments
              - sum{(i,v,r,h)$[valgen(i,v,r,t)$co2_captured_incentive(i,v,r,t)],
                              (crf(t) / crf_co2_incentive(t)) * co2_captured_incentive(i,v,r,t) * hours(h) * capture_rate("CO2",i,v,r,t) * GEN(i,v,r,h,t)}

* --- Tax credit for CO2 stored for DAC ---
              - sum{(p,i,v,r,h)$[dac(i)$valcap(i,v,r,t)$i_p(i,p)$h_rep(h)],
                              (crf(t) / crf_co2_incentive(t)) * co2_captured_incentive(i,v,r,t) * hours(h) * PRODUCE(p,i,v,r,h,t)}

* --- PTC value for electric power generation ---
              - sum{(i,v,r,h)$[valgen(i,v,r,t)$ptc_value_scaled(i,v,t)],
                    hours(h) * ptc_value_scaled(i,v,t) * tc_phaseout_mult(i,v,t) * 
                    (GEN(i,v,r,h,t) - (STORAGE_IN_GRID(i,v,r,h,t) * storage_eff_pvb_g(i,t))$[pvb(i)$Sw_PVB])
                   }

* --- PTC value for hydrogen production ---
* Note: all electrolyzers which produce H2 are assuming to be receiving the hydrogen production tax credit during eligible years  
              - sum{(p,v,r,h)$[valcap("electrolyzer",v,r,t)$(sameas(p,"H2"))$h2_ptc("electrolyzer",v,r,t)$h_rep(h)],
                  hours(h) * PRODUCE(p,"electrolyzer",v,r,h,t) *
                   (crf(t) / crf_h2_incentive(t)) * h2_ptc("electrolyzer",v,r,t) * 1e3} 
                   $[Sw_H2_PTC$Sw_H2$h2_ptc_years(t)$(yeart(t) >= h2_demand_start)]

*end multiplier for pvf_onm
         )
;
