* --- Ingest tax credit phaseout mult --- *

$gdxin outputs%ds%tc_phaseout_data%ds%tc_phaseout_mult_%cur_year%.gdx
$loaddcr tc_phaseout_mult_t_load = tc_phaseout_mult_t
$gdxin

tc_phaseout_mult_t(i,t)$tload(t) = tc_phaseout_mult_t_load(i,t) ;

* Storage-hybrid wrappers take the gen tech's phaseout multiplier: the wrapper
* rows in incentives.csv are unreliable (group-label cloning; SMR wrappers get
* safe_harbor=0), so the python-side wrapper multipliers phase out too early
tc_phaseout_mult_t(i,t)$[storage_hybrid(i)$tload(t)]
    = sum{ii$storage_hybrid_gentech(i,ii), tc_phaseout_mult_t(ii,t) } ;

* If tcphaseout is enabled, overwrite initialization
* This requires re-calculating cost_cap_fin_mult and its various permutations
if(Sw_TCPhaseout > 0,
* Apply the phaseout multiplier of the current level for current year
* and all future builds. Note that the value will remain the same for
* the cur_year-available vintage but can be updated for vintages whose
* first year hasn't solved yet. i.e. tc_phaseout_mult will remain constant for all
* current and historically-buildable plants but future plants may get updated.
tc_phaseout_mult(i,v,t)$[tload(t)$(firstyear_v(i,v)>=%cur_year%)] =
    tc_phaseout_mult_t(i,t) ;
);


* --- Start calculations of cost_cap_fin_mult family of parameters --- *

* The energy community bonus adds to the ITC only in years when the base ITC is available
* (cost_cap_fin_mult_storage_hybrid_s below copies this formula; keep the two in sync)
cost_cap_fin_mult(i,r,t) = ccmult(i,t) / (1.0 - tax_rate(t))
    * (1.0 - tax_rate(t)
             * (1.0 - (itc_frac_monetized(i,t) + itc_energy_comm_bonus(i,r)$itc_frac_monetized(i,t))
                      * tc_phaseout_mult_t(i,t) / 2.0)
             * pv_frac_of_depreciation(i,t)
       - (itc_frac_monetized(i,t) + itc_energy_comm_bonus(i,r)$itc_frac_monetized(i,t))
         * tc_phaseout_mult_t(i,t))
    * degradation_adj(i,t) * financing_risk_mult(i,t) * (1 + reg_cap_cost_diff(i,r))
    * eval_period_adj_mult(i,t) ;

cost_cap_fin_mult_noITC(i,r,t) = ccmult(i,t) / (1.0 - tax_rate(t))
    * (1.0-tax_rate(t)*pv_frac_of_depreciation(i,t)) * degradation_adj(i,t)
    * financing_risk_mult(i,t) * (1 + reg_cap_cost_diff(i,r)) * eval_period_adj_mult(i,t) ;

cost_cap_fin_mult_no_credits(i,r,t) = ccmult(i,t) * (1 + reg_cap_cost_diff(i,r)) ;

* Raw geo_storage technologies are costless storage-side placeholders; all costs
* come from storage-hybrid scaling in b_inputs.gms, so keep their multipliers neutral.
cost_cap_fin_mult(i,r,t)$[geo_storage(i)$(not storage_hybrid(i))] = 1 ;
cost_cap_fin_mult_noITC(i,r,t)$[geo_storage(i)$(not storage_hybrid(i))] = 1 ;
cost_cap_fin_mult_no_credits(i,r,t)$[geo_storage(i)$(not storage_hybrid(i))] = 1 ;

* Assign the PV portion of PVB the value of UPV
cost_cap_fin_mult_pvb_p(i,r,t)$pvb(i) =
    sum{ii$[upv(ii)$rsc_agg(ii,i)], cost_cap_fin_mult(ii,r,t) } ;

cost_cap_fin_mult_pvb_p_noITC(i,r,t)$pvb(i) =
    sum{ii$[upv(ii)$rsc_agg(ii,i)], cost_cap_fin_mult_noITC(ii,r,t) } ;

cost_cap_fin_mult_pvb_p_no_credits(i,r,t)$pvb(i) =
    sum{ii$[upv(ii)$rsc_agg(ii,i)], cost_cap_fin_mult_no_credits(ii,r,t) } ;

* In the financing module (python), PVB refers to the battery portion of the hybrid.
* This convention is used to estimate the ITC benefit for the battery.
* Assign the battery portion of PVB the value computed in the financing module for PVB
cost_cap_fin_mult_pvb_b(i,r,t)$pvb(i) = cost_cap_fin_mult(i,r,t) ;
cost_cap_fin_mult_pvb_b_noITC(i,r,t)$pvb(i) = cost_cap_fin_mult_noITC(i,r,t) ;
cost_cap_fin_mult_pvb_b_no_credits(i,r,t)$pvb(i) = cost_cap_fin_mult_no_credits(i,r,t) ;

* Assign "cost_cap_fin_mult" for PVB to be the weighted average of the PV and battery portions
* The weighting is based on:
*   (1) the cost of each portion: PV=cost_cap_pvb_p; Battery=cost_cap_pvb_b
*   (2) the relative size of each portion: PV=1; Battery=bcr
* The "-1" and "+1" values are needed because the multipliers are adjustments off of 1.0
cost_cap_fin_mult(i,r,t)$pvb(i) =
    ( (cost_cap_fin_mult_pvb_p(i,r,t) - 1) * cost_cap_pvb_p(i,t)
    + bcr(i) * (cost_cap_fin_mult_pvb_b(i,r,t) - 1) * cost_cap_pvb_b(i,t) )
    / (cost_cap_pvb_p(i,t) + bcr(i) * cost_cap_pvb_b(i,t)) + 1 ;

cost_cap_fin_mult_noITC(i,r,t)$pvb(i) =
    ( (cost_cap_fin_mult_pvb_p_noITC(i,r,t) - 1) * cost_cap_pvb_p(i,t)
    + bcr(i) * (cost_cap_fin_mult_pvb_b_noITC(i,r,t) - 1) * cost_cap_pvb_b(i,t) )
    / (cost_cap_pvb_p(i,t) + bcr(i) * cost_cap_pvb_b(i,t)) + 1 ;

cost_cap_fin_mult_no_credits(i,r,t)$pvb(i) =
    ((cost_cap_fin_mult_pvb_p_no_credits(i,r,t) - 1) * cost_cap_pvb_p(i,t)
    + bcr(i) * (cost_cap_fin_mult_pvb_b_no_credits(i,r,t) - 1) * cost_cap_pvb_b(i,t))
    / (cost_cap_pvb_p(i,t) + bcr(i) * cost_cap_pvb_b(i,t)) + 1 ;

* --- Upgrades ---
* Assign upgraded techs the same multipliers as the techs they are upgraded from
* This assignment must take place after expanding for water techs, if applicable.

if(Sw_WaterMain=1,
cost_cap_fin_mult(i,r,t)$i_water_cooling(i) =
    sum{(ii)$[ctt_i_ii(i,ii)], cost_cap_fin_mult(ii,r,t) } ;

cost_cap_fin_mult_noITC(i,r,t)$i_water_cooling(i) =
    sum{(ii)$[ctt_i_ii(i,ii)], cost_cap_fin_mult_noITC(ii,r,t) } ;

cost_cap_fin_mult_no_credits(i,r,t)$i_water_cooling(i) =
    sum{(ii)$[ctt_i_ii(i,ii)], cost_cap_fin_mult_no_credits(ii,r,t) } ;
) ;

cost_cap_fin_mult(i,r,t)$upgrade(i) = sum{ii$upgrade_to(i,ii), cost_cap_fin_mult(ii,r,t) } ;
cost_cap_fin_mult_noITC(i,r,t)$upgrade(i) = sum{ii$upgrade_to(i,ii), cost_cap_fin_mult_noITC(ii,r,t) } ;

* --- Nuclear Ban ---
* Assign increased cost multipliers to regions with state nuclear bans
if(Sw_NukeStateBan = 2,
  cost_cap_fin_mult(i,r,t)$[nuclear(i)$nuclear_ba_ban(r)] =
    cost_cap_fin_mult(i,r,t) * nukebancostmult ;

  cost_cap_fin_mult_noITC(i,r,t)$[nuclear(i)$nuclear_ba_ban(r)] =
    cost_cap_fin_mult_noITC(i,r,t) * nukebancostmult ;
) ;

* Start by setting all multipliers to 1
rsc_fin_mult(i,r,t)$[valcap_irt(i,r,t)$rsc_i(i)] = 1 ;
rsc_fin_mult_noITC(i,r,t)$[valcap_irt(i,r,t)$rsc_i(i)] = 1 ;

* Hydro, pumped-hydro, and dr-shed have capital costs included in the supply curve,
* so change their multiplier to be the same as cost_cap_fin_mult adjusted by their
* capital cost multipliers.
rsc_fin_mult(i,r,t)$hydro(i) = cost_cap_fin_mult('hydro',r,t) * hydrocapmult(t,i) ;
rsc_fin_mult_noITC(i,r,t)$hydro(i) = cost_cap_fin_mult_noITC('hydro',r,t) * hydrocapmult(t,i) ;
rsc_fin_mult(i,r,t)$psh(i) = cost_cap_fin_mult(i,r,t) * hydrocapmult(t,i) ;
rsc_fin_mult_noITC(i,r,t)$psh(i) = cost_cap_fin_mult_noITC(i,r,t) * hydrocapmult(t,i) ;
rsc_fin_mult(i,r,t)$dr_shed(i) = cost_cap_fin_mult(i,r,t)* dr_shed_capmult(i,r,t) ;
rsc_fin_mult_noITC(i,r,t)$dr_shed(i) = cost_cap_fin_mult_noITC(i,r,t)* dr_shed_capmult(i,r,t) ;

* Create a new parameter to hold capital financing multipliers with and without ITC for OSW transmission costs inside the resource supply curve cost
* Currently, OSW receives federal incentives in both its capital and transmission costs, hence this custom application for OSW
rsc_fin_mult(i,r,t)$ofswind(i) = cost_cap_fin_mult(i,r,t) * ofswind_rsc_mult(t,i) ;
rsc_fin_mult_noITC(i,r,t)$ofswind(i) = cost_cap_fin_mult_noITC(i,r,t) ;

* Storage-hybrid wrappers on supply-curve gen techs pay their gen tech's supply-curve multiplier
rsc_fin_mult(i,r,t)$[storage_hybrid(i)$rsc_i(i)$sum{ii$storage_hybrid_gentech(i,ii), rsc_fin_mult(ii,r,t) }] =
    sum{ii$storage_hybrid_gentech(i,ii), rsc_fin_mult(ii,r,t) } ;
rsc_fin_mult_noITC(i,r,t)$[storage_hybrid(i)$rsc_i(i)$sum{ii$storage_hybrid_gentech(i,ii), rsc_fin_mult_noITC(ii,r,t) }] =
    sum{ii$storage_hybrid_gentech(i,ii), rsc_fin_mult_noITC(ii,r,t) } ;

* Assign the generation portion of storage_hybrid the configured gen tech multiplier
* NOTE: This must happen BEFORE the trim step below, because the trim zeros out
* cost_cap_fin_mult for component techs (nuclear-smr, tes-ms) that may not be
* independently in valinv_irt for a given region.
cost_cap_fin_mult_storage_hybrid_p(i,r,t)$storage_hybrid(i) = sum{ii$ storage_hybrid_gentech(i,ii), cost_cap_fin_mult(ii,r,t)};
cost_cap_fin_mult_storage_hybrid_p_noITC(i,r,t)$storage_hybrid(i) = sum{ii$ storage_hybrid_gentech(i,ii), cost_cap_fin_mult_noITC(ii,r,t) } ;
cost_cap_fin_mult_storage_hybrid_p_no_credits(i,r,t)$storage_hybrid(i) = sum{ii$ storage_hybrid_gentech(i,ii), cost_cap_fin_mult_no_credits(ii,r,t) } ;

* Assign the storage portion of storage_hybrid the storage tech multiplier, with two
* inputs swapped for the wrapper's own: the storage-side ITC, which uses the larger of
* the gen and storage techs' eligibility windows (itc_frac_monetized_storage_hybrid_s),
* and the wrapper's phaseout multiplier, which is the gen tech's (set at the top of this file).
* KEEP IN SYNC with cost_cap_fin_mult above; the abort below catches a mismatch.
cost_cap_fin_mult_storage_hybrid_s(i,r,t)$storage_hybrid(i) =
    sum{ii$storage_hybrid_stortech(i,ii),
        ccmult(ii,t) / (1.0 - tax_rate(t))
        * (1.0 - tax_rate(t)
                 * (1.0 - (itc_frac_monetized_storage_hybrid_s(i,t)
                           + itc_energy_comm_bonus(ii,r)$itc_frac_monetized_storage_hybrid_s(i,t))
                          * tc_phaseout_mult_t(i,t) / 2.0)
                 * pv_frac_of_depreciation(ii,t)
           - (itc_frac_monetized_storage_hybrid_s(i,t)
              + itc_energy_comm_bonus(ii,r)$itc_frac_monetized_storage_hybrid_s(i,t))
             * tc_phaseout_mult_t(i,t))
        * degradation_adj(ii,t) * financing_risk_mult(ii,t) * (1 + reg_cap_cost_diff(ii,r))
        * eval_period_adj_mult(ii,t) } ;

* Where the swapped inputs equal the storage tech's own, the result must equal the storage
* tech's cost_cap_fin_mult; otherwise the formula above has drifted from the one it copies
parameter storage_hybrid_s_formula_diff(i,r,t) "--fraction-- check of cost_cap_fin_mult_storage_hybrid_s against cost_cap_fin_mult" ;
storage_hybrid_s_formula_diff(i,r,t)
    $[storage_hybrid(i)$(not geo_storage(i))
     $sum{ii$[storage_hybrid_stortech(i,ii)
             $(itc_frac_monetized_storage_hybrid_s(i,t) = itc_frac_monetized(ii,t))
             $(tc_phaseout_mult_t(i,t) = tc_phaseout_mult_t(ii,t))], 1 }] =
    abs(cost_cap_fin_mult_storage_hybrid_s(i,r,t)
        - sum{ii$storage_hybrid_stortech(i,ii), cost_cap_fin_mult(ii,r,t) }) ;
abort$[smax{(i,r,t), storage_hybrid_s_formula_diff(i,r,t) } > 1e-6]
    "cost_cap_fin_mult_storage_hybrid_s has drifted from cost_cap_fin_mult; update its formula in 2_financials.gms",
    storage_hybrid_s_formula_diff ;
cost_cap_fin_mult_storage_hybrid_s_noITC(i,r,t)$storage_hybrid(i) = sum{ii$ storage_hybrid_stortech(i,ii), cost_cap_fin_mult_noITC(ii,r,t)} ;
cost_cap_fin_mult_storage_hybrid_s_no_credits(i,r,t)$storage_hybrid(i) = sum{ii$ storage_hybrid_stortech(i,ii), cost_cap_fin_mult_no_credits(ii,r,t)} ;

* The storage multipliers above use the standalone storage tech's financing_risk_mult.
* For a storage-hybrid plant, the whole project carries gen-tech-level financing risk,
* so replace the storage tech's financing_risk_mult with the configured gen tech's.
* financing_risk_mult is a simple multiplicative factor in cost_cap_fin_mult and _noITC,
* so the adjustment is: adjusted_s = s * (gen_risk / storage_risk).
* _no_credits does not include financing_risk_mult, so no adjustment is needed.
* Guard: skip adjustment if the storage tech has no financing_risk_mult (avoids division by zero).
cost_cap_fin_mult_storage_hybrid_s(i,r,t)$[storage_hybrid(i)$sum{ii$storage_hybrid_stortech(i,ii), financing_risk_mult(ii,t)}] =
    cost_cap_fin_mult_storage_hybrid_s(i,r,t)
    * sum{ii$storage_hybrid_gentech(i,ii), financing_risk_mult(ii,t)}
    / sum{ii$storage_hybrid_stortech(i,ii), financing_risk_mult(ii,t)} ;

cost_cap_fin_mult_storage_hybrid_s_noITC(i,r,t)$[storage_hybrid(i)$sum{ii$storage_hybrid_stortech(i,ii), financing_risk_mult(ii,t)}] =
    cost_cap_fin_mult_storage_hybrid_s_noITC(i,r,t)
    * sum{ii$storage_hybrid_gentech(i,ii), financing_risk_mult(ii,t)}
    / sum{ii$storage_hybrid_stortech(i,ii), financing_risk_mult(ii,t)} ;

* Geo-storage storage-side costs are derived from b_inputs.gms scaling, not from flex_geo.
cost_cap_fin_mult_storage_hybrid_s(i,r,t)$[storage_hybrid(i)$geo_storage(i)] = 1 ;
cost_cap_fin_mult_storage_hybrid_s_noITC(i,r,t)$[storage_hybrid(i)$geo_storage(i)] = 1 ;
cost_cap_fin_mult_storage_hybrid_s_no_credits(i,r,t)$[storage_hybrid(i)$geo_storage(i)] = 1 ;

* Trim the cost_cap_fin_mult parameters to reduce file sizes
cost_cap_fin_mult(i,r,t)$[(not valinv_irt(i,r,t))$(not upgrade(i))
                         $(not sum{(v,rscbin), allow_cap_up(i,v,r,rscbin,t) })
                         $(not sum{(v,rscbin), allow_ener_up(i,v,r,rscbin,t) })] = 0 ;

cost_cap_fin_mult_noITC(i,r,t)$[(not valinv_irt(i,r,t))$(not upgrade(i))
                               $(not sum{(v,rscbin), allow_cap_up(i,v,r,rscbin,t) })
                               $(not sum{(v,rscbin), allow_ener_up(i,v,r,rscbin,t) })] = 0 ;

cost_cap_fin_mult_no_credits(i,r,t)$[(not valinv_irt(i,r,t))$(not upgrade(i))
                                    $(not sum{(v,rscbin), allow_cap_up(i,v,r,rscbin,t) })
                                    $(not sum{(v,rscbin), allow_ener_up(i,v,r,rscbin,t) })] = 0 ;

* Round the cost_cap_fin_mult parameters, since they were re-calculated
cost_cap_fin_mult(i,r,t)$cost_cap_fin_mult(i,r,t)
  = round(cost_cap_fin_mult(i,r,t),3) ;

cost_cap_fin_mult_noITC(i,r,t)$cost_cap_fin_mult_noITC(i,r,t)
  = round(cost_cap_fin_mult_noITC(i,r,t),3) ;

cost_cap_fin_mult_no_credits(i,r,t)$cost_cap_fin_mult_no_credits(i,r,t)
  = round(cost_cap_fin_mult_no_credits(i,r,t),3) ;

rsc_fin_mult(i,r,t)$rsc_fin_mult(i,r,t) = round(rsc_fin_mult(i,r,t),3) ;

* Set cost_cap_fin_mult_out equal to cost_cap_fin_mult before we alter cost_cap_fin_mult
* for state fossil retirement policies and/or a full-region zero-carbon policy.
cost_cap_fin_mult_out(i,r,t) = cost_cap_fin_mult(i,r,t) ;

* Penalize new gas built within cost recovery period of 20 years for states that require 
* fossil retirements if Sw_StateRPS=1 and/or within 20 years of a zero-carbon policy
cost_cap_fin_mult(i,r,t)$[gas(i)$valcap_irt(i,r,t)] =
    cost_cap_fin_mult(i,r,t) 
    * max(sum{st$r_st(r,st), ng_crf_penalty_st(t,st) }$(not ccs(i))$Sw_StateRPS$(yeart(t)>=firstyear_RPS), 
          ng_crf_penalty_nat(i,t) ) ;


* Compute cost-weighted average of generation and storage financial multipliers.
* The storage multipliers retain the storage tech's ccmult (IDC) and depreciation schedule
* (5-year MACRS for storage vs the gen tech schedule), but now carry gen-tech financing risk.
parameter storage_hybrid_cost_p(i,t)  "--$/MW-- generation-side cost weight for storage_hybrid"
          storage_hybrid_cost_s(i,t) "--$/MW-- storage-side cost weight for storage_hybrid";

* Default (non-thermal-storage): total capex = gen tech + bcr * storage, as in cost_cap(i,t)
* (the gen tech and the storage discharge do not share a powerblock)
storage_hybrid_cost_p(i,t)$storage_hybrid(i) = cost_cap_storage_hybrid_p(i,t);
storage_hybrid_cost_s(i,t)$storage_hybrid(i) = bcr(i) * cost_cap_storage_hybrid_s(i,t);

* Thermal-storage: align with cost_cap(i,t) composition
storage_hybrid_cost_p(i,t)$[storage_hybrid(i)$thermal_storage(i)] = cost_cap_storage_hybrid_p(i,t)
    - powerblock_cost_storage_hybrid(i,t);

storage_hybrid_cost_s(i,t)$[storage_hybrid(i)$thermal_storage(i)] = (1 + bcr(i)) * cost_cap_storage_hybrid_s(i,t)
    + gridcharge_ratio(i) * sum{ii$[storage_hybrid_stortech(i,ii)$heater_char(ii,t,"capcost")], heater_char(ii,t,"capcost") };

* Geo-storage: align with cost_cap(i,t) composition
storage_hybrid_cost_p(i,t)$[storage_hybrid(i)$geo_storage(i)] = cost_cap_storage_hybrid_p(i,t);
storage_hybrid_cost_s(i,t)$[storage_hybrid(i)$geo_storage(i)] = bcr(i) * powerblock_cost_storage_hybrid(i,t);

* A wrapper with zero total capex keeps its gen tech's multiplier
cost_cap_fin_mult(i,r,t)$[storage_hybrid(i)$valinv_irt(i,r,t)] = cost_cap_fin_mult_storage_hybrid_p(i,r,t) ;
cost_cap_fin_mult_noITC(i,r,t)$[storage_hybrid(i)$valinv_irt(i,r,t)] = cost_cap_fin_mult_storage_hybrid_p_noITC(i,r,t) ;
cost_cap_fin_mult_no_credits(i,r,t)$[storage_hybrid(i)$valinv_irt(i,r,t)] = cost_cap_fin_mult_storage_hybrid_p_no_credits(i,r,t) ;

cost_cap_fin_mult(i,r,t)$[storage_hybrid(i)$valinv_irt(i,r,t)
                         $(storage_hybrid_cost_p(i,t) + storage_hybrid_cost_s(i,t))] =
    (storage_hybrid_cost_p(i,t) * cost_cap_fin_mult_storage_hybrid_p(i,r,t)
     + storage_hybrid_cost_s(i,t) * cost_cap_fin_mult_storage_hybrid_s(i,r,t))
    / (storage_hybrid_cost_p(i,t) + storage_hybrid_cost_s(i,t)) ;

cost_cap_fin_mult_noITC(i,r,t)$[storage_hybrid(i)$valinv_irt(i,r,t)
                               $(storage_hybrid_cost_p(i,t) + storage_hybrid_cost_s(i,t))] =
    (storage_hybrid_cost_p(i,t) * cost_cap_fin_mult_storage_hybrid_p_noITC(i,r,t)
     + storage_hybrid_cost_s(i,t) * cost_cap_fin_mult_storage_hybrid_s_noITC(i,r,t))
    / (storage_hybrid_cost_p(i,t) + storage_hybrid_cost_s(i,t)) ;

cost_cap_fin_mult_no_credits(i,r,t)$[storage_hybrid(i)$valinv_irt(i,r,t)
                                    $(storage_hybrid_cost_p(i,t) + storage_hybrid_cost_s(i,t))] =
    (storage_hybrid_cost_p(i,t) * cost_cap_fin_mult_storage_hybrid_p_no_credits(i,r,t)
     + storage_hybrid_cost_s(i,t) * cost_cap_fin_mult_storage_hybrid_s_no_credits(i,r,t))
    / (storage_hybrid_cost_p(i,t) + storage_hybrid_cost_s(i,t)) ;

* Round these entries because the global rounding happens earlier in this file.
cost_cap_fin_mult(i,r,t)$[storage_hybrid(i)$valinv_irt(i,r,t)] = round(cost_cap_fin_mult(i,r,t),3);
cost_cap_fin_mult_noITC(i,r,t)$[storage_hybrid(i)$valinv_irt(i,r,t)] = round(cost_cap_fin_mult_noITC(i,r,t),3);
cost_cap_fin_mult_no_credits(i,r,t)$[storage_hybrid(i)$valinv_irt(i,r,t)] = round(cost_cap_fin_mult_no_credits(i,r,t),3);
cost_cap_fin_mult_storage_hybrid_s(i,r,t)$[storage_hybrid(i)$valinv_irt(i,r,t)] = round(cost_cap_fin_mult_storage_hybrid_s(i,r,t),3);
cost_cap_fin_mult_storage_hybrid_s_noITC(i,r,t)$[storage_hybrid(i)$valinv_irt(i,r,t)] = round(cost_cap_fin_mult_storage_hybrid_s_noITC(i,r,t),3);
cost_cap_fin_mult_storage_hybrid_s_no_credits(i,r,t)$[storage_hybrid(i)$valinv_irt(i,r,t)] = round(cost_cap_fin_mult_storage_hybrid_s_no_credits(i,r,t),3);

* Keep reporting/system-cost multipliers in sync with the recomputed (rounded) storage_hybrid values.
cost_cap_fin_mult_out(i,r,t)$[storage_hybrid(i)$valinv_irt(i,r,t)] = cost_cap_fin_mult(i,r,t) ;

* Wrappers on gas gen techs carry the same new-gas cost recovery penalty as their gen tech (see above)
cost_cap_fin_mult(i,r,t)$[storage_hybrid(i)$valinv_irt(i,r,t)$sum{ii$storage_hybrid_gentech(i,ii), gas(ii) }] =
    cost_cap_fin_mult(i,r,t)
    * sum{ii$storage_hybrid_gentech(i,ii),
          max(1,
              sum{st$r_st(r,st), ng_crf_penalty_st(t,st) }$(not ccs(ii))$Sw_StateRPS$(yeart(t)>=firstyear_RPS),
              ng_crf_penalty_nat(ii,t)) } ;

* --- End calculations of cost_cap_fin_mult family of parameters --- *
