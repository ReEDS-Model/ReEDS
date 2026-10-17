eq_ObjFn_inv(t)$tmodel(t)..

         Z_inv(t)

         =e=

         pvf_capital(t) *

              (
* --- investment costs ---
                  + sum{(i,v,r)$valinv(i,v,r,t),
                       cost_cap_fin_mult(i,r,t) * cost_cap(i,t) * INV(i,v,r,t)
                      }

                  + sum{(i,v,r)$[valinv(i,v,r,t)$battery(i)],
                       cost_cap_fin_mult(i,r,t) * cost_cap_energy(i,t) * INV_ENERGY(i,v,r,t) 
                      }

* --- penalty for exceeding interconnection queue limit  ---
                  + sum{(tg,r), cap_penalty(tg) * CAP_ABOVE_LIM(tg,r,t) }    

* --- growth penalties ---
                  + sum{(gbin,i,st)$[sum{r$[r_st(r,st)], valinv_irt(i,r,t) }$stfeas(st)],
                        cost_growth(i,st,t) * growth_penalty(gbin) * (yeart(t) - sum{tt$[tprev(t,tt)], yeart(tt) }) * GROWTH_BIN(gbin,i,st,t)
                       }$[(yeart(t)>=model_builds_start_yr)$Sw_GrowthPenalties$(yeart(t)<=Sw_GrowthPenLastYear)]

* --- cost of upgrading---
                  + sum{(i,v,r)$[upgrade(i)$valcap(i,v,r,t)$Sw_Upgrades],
                         cost_upgrade(i,v,r,t) * cost_cap_fin_mult(i,r,t) * UPGRADES(i,v,r,t) }

* --- costs of resource supply curve spur line investment if not modeling explicitly---
*Note that cost_cap for hydro, pumped-hydro, and geo techs are zero
*but hydro and geo rsc_fin_mult is equal to the same value as cost_cap_fin_mult
* Note: for OSW, export cable, inter-array and POI/substations are eligible for ITC. The rest are not. 
* However we apply the ITC to all transmission costs to be consistent with LBW format
                  + sum{(i,v,r,rscbin)$[m_rscfeas(r,i,rscbin)$valinv(i,v,r,t)$rsc_i(i)$(not spur_techs(i))],
                      m_rsc_dat(r,i,rscbin,"cost") * rsc_fin_mult(i,r,t) * sum{ii$rsc_agg(i,ii), INV_RSC(ii,v,r,rscbin,t) } }

* ---cost of spur lines modeled explicitly---
* NOTE: no rsc_fin_mult(i,r,t) here, but it's 1 for upv and wind-ons anyway
                  + sum{x$[Sw_SpurScen$xfeas(x)],
                        spurline_cost(x) * Sw_SpurCostMult * INV_SPUR(x,t) }

* --- cost of intra-zone network reinforcement (a.k.a. point-of-interconnection capacity or POI)
* Sw_TransIntraCost is in $/kW, so multiply by 1000 to convert to $/MW
                  + sum{r$Sw_TransIntraCost,
                        trans_cost_cap_fin_mult(t) * Sw_TransIntraCost * 1000 * INV_POI(r,t) }

* --- cost of water access---
                  + [ (8760/1E6) * sum{ (i,v,w,r)$[i_w(i,w)$valinv(i,v,r,t)], sum{wst$i_wst(i,wst),
                                     m_watsc_dat(wst,"cost",r,t) } * water_rate(i,w) *
                                        ( INV(i,v,r,t) + INV_REFURB(i,v,r,t)$[refurbtech(i)$Sw_Refurb] ) }
                      + sum{(rscbin,i,v,r)$[m_rscfeas(r,i,rscbin)$psh(i)],
                              sum{wst$i_wst(i,wst), m_watsc_dat(wst,"cost",r,t) } *
                              ( INV_RSC(i,v,r,rscbin,t) * water_req_psh(r,rscbin) ) }$Sw_PSHwatercon
                    ]$Sw_WaterMain

*slack variable to update water source type (wst) in the unit database
*Note that existing wst data is not consistent with availability of water source in the region
                  + sum{(wst,r), 1E6 * WATER_CAPACITY_LIMIT_SLACK(wst,r,t) }$[Sw_WaterMain$Sw_WaterCapacity]

* --- cost of refurbishments of RSC tech---
                  + sum{(i,v,r)$[Sw_Refurb$valinv(i,v,r,t)$refurbtech(i)],
                      cost_cap_fin_mult(i,r,t) * cost_cap(i,t) * INV_REFURB(i,v,r,t)
                      }

* --- cost of interzonal AC transmission---
                  + sum{(r,rr,tscbin)$[routes_inv(r,rr,"AC",t)$tsc_binwidth(r,rr,tscbin)],
                        trans_cost_cap_fin_mult(t) * TRAN_CAPEX_BINS(r,rr,tscbin,t) }

* --- cost of interzonal HVDC transmission---
* transmission lines: 1 MW adds 1 MW to both INVTRAN(r,rr) and INVTRAN(rr,r) so divide by 2
                  + sum{(r,rr,trtype)$[routes_inv(r,rr,trtype,t)$(not aclike(trtype))],
                        trans_cost_cap_fin_mult(t)
                        * transmission_cost_nonac(r,rr,trtype)
                        * INVTRAN(r,rr,trtype,t)
                        / 2 }

* LCC and B2B AC/DC converter stations: each interface has two, one on either side of the interface,
* but each interface shows up in both INVTRAN(r,rr) and INVTRAN(rr,r) so don't multiply by 2
                  + sum{(r,rr,trtype)$[lcclike(trtype)$routes_inv(r,rr,trtype,t)],
                        trans_cost_cap_fin_mult(t) * cost_acdc_lcc * INVTRAN(r,rr,trtype,t) }

* VSC AC/DC converter stations
                  + sum{r$val_converter(r,t),
                        trans_cost_cap_fin_mult(t) * cost_acdc_vsc * INV_CONVERTER(r,t) }

* --- storage capacity credit---
*small cost penalty to incentivize solver to fill shorter-duration bins first
                  + sum{(i,v,r,ccseason,sdbin)$[valcap(i,v,r,t)$(storage(i) or hyd_add_pump(i))$(not csp(i))$Sw_PRM_CapCredit$Sw_StorageBinPenalty],
                         bin_penalty(sdbin) * CAP_SDBIN(i,v,r,ccseason,sdbin,t) }

* cost of capacity upsizing
                  + sum{(i,v,r,rscbin)$allow_cap_up(i,v,r,rscbin,t),
                            cost_cap_fin_mult(i,r,t) * INV_CAP_UP(i,v,r,rscbin,t) * cost_cap_up(i,v,r,rscbin,t) }

* cost of energy upsizing
                  + sum{(i,v,r,rscbin)$allow_ener_up(i,v,r,rscbin,t),
                            cost_cap_fin_mult(i,r,t) * INV_ENER_UP(i,v,r,rscbin,t) * cost_ener_up(i,v,r,rscbin,t) }

* H2 transport network investment costs
                  + sum{(r,rr)$h2_routes_inv(r,rr), cost_h2_transport_cap(r,rr,t) * H2_TRANSPORT_INV(r,rr,t) }$(Sw_H2 = 2)

* H2 storage investment costs 
                  + sum{(h2_stor,r)$h2_stor_r(h2_stor,r), cost_h2_storage_cap(h2_stor,t) * H2_STOR_INV(h2_stor,r,t) }$(Sw_H2 = 2)

* CO2 pipeline investment costs
                  + sum{(r,rr)$co2_routes(r,rr), cost_co2_pipeline_cap(r,rr,t) * CO2_TRANSPORT_INV(r,rr,t)
                                                  }$[Sw_CO2_Detail$(yeart(t)>=co2_detail_startyr)]

                  + sum{(r,cs)$[csfeas(cs)$r_cs(r,cs)], cost_co2_spurline_cap(r,cs,t) * CO2_SPURLINE_INV(r,cs,t)
                                                  }$[Sw_CO2_Detail$(yeart(t)>=co2_detail_startyr)]

*end to multiplier by pvf_capital
            )
;
