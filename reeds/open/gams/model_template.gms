$setglobal ds \

$ifthen.unix %system.filesys% == UNIX
$setglobal ds /
$endif.unix

$if not set port_dir $setglobal port_dir port

tload(t) = no ;

tmodel(t) = no ;
tmodel("%cur_year%") = yes ;

$log 'Solving ReEDS port model %%MODEL%% for...'
$log '  Case: %case%'
$log '  Year: %cur_year%'

$onMultiR
$include reeds%ds%core%ds%solve%ds%2_temporal_params.gms
$offMulti

$ifthene.post_startyear %cur_year%>%startyear%
rhs_eq_rsc_INVlim(r,i,rscbin,t)$[tmodel(t)$rsc_i(i)$m_rscfeas(r,i,rscbin)$m_rsc_con(r,i)] =
    ( m_rsc_dat(r,i,rscbin,"cap")
      - sum{(ii,v,tt)$[tfirst(tt)$rsc_agg(i,ii)$exog_rsc(i)],
             capacity_exog_rsc(ii,v,r,rscbin,tt) } )
        * (1$[not rsc_capacity_scalar_i(i)]
           + rsc_capacity_scalar(i,r,t)$rsc_capacity_scalar_i(i))
    + hyd_add_upg_cap(r,i,rscbin,t)$(Sw_HydroCapEnerUpgradeType=1)
    - sum{(ii,v,tt)$[valinv(ii,v,r,tt)$(yeart(tt) < yeart(t))$rsc_agg(i,ii)],
         INV_RSC.l(ii,v,r,rscbin,tt) * resourcescaler(ii) }
;

flag_eq_rsc_INVlim(r,i,rscbin,t)$tmodel(t) = no ;

flag_eq_rsc_INVlim(r,i,rscbin,t)$[tmodel(t)$rsc_i(i)$m_rscfeas(r,i,rscbin)$m_rsc_con(r,i)
                                 $(rhs_eq_rsc_INVlim(r,i,rscbin,t) > -rhs_tolerance)
                                 $(rhs_eq_rsc_INVlim(r,i,rscbin,t) < rhs_tolerance)] = yes ;

loop(i$rsc_i(i),
    INV_RSC.fx(ii,v,r,rscbin,t)$[tmodel(t)$m_rscfeas(r,i,rscbin)$m_rsc_con(r,i)
                                $(flag_eq_rsc_INVlim(r,i,rscbin,t))$(valinv(ii,v,r,t)$rsc_agg(i,ii))] = 0 ;
) ;

if(Sw_Upgrades = 1,
    m_capacity_exog(i,v,r,t)$[valcap(i,v,r,t)$sameas(t,"%cur_year%")
                         $(sum{(ii,tt)$[(tt.val <= t.val)$(t.val - tt.val <= Sw_UpgradeLifespan)
                                       $valcap(ii,v,r,tt)$upgrade_from(ii,i)], UPGRADES.l(ii,v,r,tt) } ) ] =
                    max( m_capacity_exog0(i,v,r,t),
                    sum{(ii,tt)$[(tt.val <= t.val)$(t.val - tt.val <= Sw_UpgradeLifespan)
                                 $valcap(ii,v,r,tt)$upgrade_from(ii,i)],
                                 UPGRADES.l(ii,v,r,tt) }
    ) ;
) ;

if(Sw_GrowthPenalties > 0,

* Calculate the maximum deployment that could have been achieved in the last modeled
* year. For example, if tmodel is 2023 and the prior two solve years were 2020 and 
* 2015, then we are calculating the maximum deployment that could have occured in
* 2020 at the growth rate specified in gbin1. This requires looking back to tprev
* and the solve year before tprev, hence the need for the yeart(ttt).
* The denominator is simply a discount term, and the multiplication is an associated
* compounding term.
    last_year_max_growth(st,tg,t)$tmodel(t) = 
        sum{(i,v,r,tt)$[valinv(i,v,r,tt)$r_st(r,st)$tg_i(tg,i)$tprev(t,tt)],
            INV.l(i,v,r,tt) } 
        / sum{allt$[(allt.val>sum{tt$tprev(t,tt), sum{ttt$tprev(tt,ttt), yeart(ttt) } })
                   $(allt.val<=sum{tt$tprev(t,tt), yeart(tt) })],
              (growth_bin_size_mult("gbin1") ** (allt.val - sum{tt$tprev(t,tt), sum{ttt$tprev(tt,ttt), yeart(ttt) } } - 1)) }
        * (growth_bin_size_mult("gbin1") ** ((sum{tt$tprev(t,tt), yeart(tt) - sum{ttt$tprev(tt,ttt), yeart(ttt) } }) - 1)) ;

* Now calculate the growth bin size for the current solve year, assuming that the 
* maximum growth allowed in gbin1 happens each year over the current solve period.
    growth_bin_limit("gbin1",st,tg,t)$tmodel(t) = 
        sum{allt$[(allt.val>sum{tt$tprev(t,tt), yeart(tt) })
                 $(allt.val<=yeart(t))],
            last_year_max_growth(st,tg,t) * growth_bin_size_mult("gbin1") ** (allt.val - sum{tt$tprev(t,tt), yeart(tt) }) }
        / (yeart(t) - sum{tt$tprev(t,tt), yeart(tt) }) ;

* Do not allow growth_bin_limit to decline over time (i.e., if a higher growth
* rate was achieved in the past, allow the model to start from that higher level)
    growth_bin_limit("gbin1",st,tg,t)$tmodel(t) = smax{tt, growth_bin_limit("gbin1",st,tg,tt) } ;
   
* If the calculated  gbin1 value is less than the minimum bin size, then set it to the minimum bin size
    growth_bin_limit("gbin1",st,tg,t)$[tmodel(t)$(growth_bin_limit("gbin1",st,tg,t) < gbin_min(tg))$stfeas(st)] = gbin_min(tg) ;

* Now set the size of the remaining bins
    growth_bin_limit(gbin,st,tg,t)$[tmodel(t)$(not sameas(gbin,"gbin1"))] = 
        growth_bin_limit("gbin1",st,tg,t) * (growth_bin_size_mult(gbin) - growth_bin_size_mult("gbin1")) ;

    growth_bin_limit(gbin,st,tg,t)$growth_bin_limit(gbin,st,tg,t) = round(growth_bin_limit(gbin,st,tg,t),0) ;

) ;
$endif.post_startyear

$ifthene.tcheck %cur_year%>%GSw_SkipRAyear%
tload("%cur_year%") = yes ;

$gdxin handoff%ds%reeds_data%ds%ccdata_%prev_year%.gdx
$loaddcr cc_old_load = cc_old
$loaddcr cc_mar_load = cc_mar
$loaddcr cc_evmc_load = cc_evmc
$loaddcr sdbin_size_load = sdbin_size
$loaddcr mean_forced_outage_rate_load = mean_forced_outage_rate
$gdxin

cc_old(i,r,ccseason,t)$[tload(t)$(vre(i) or csp(i) or pvb(i))] =
    sum{ccreg$r_ccreg(r,ccreg), cc_old_load(i,r,ccreg,ccseason,t) } ;

m_cc_mar(i,r,ccseason,t)$[tload(t)$(vre(i) or csp(i) or pvb(i))] =
    sum{ccreg$r_ccreg(r,ccreg), cc_mar_load(i,r,ccreg,ccseason,t) } ;

sdbin_size(ccreg,ccseason,sdbin,t)$tload(t) = sdbin_size_load(ccreg,ccseason,sdbin,t) ;

m_cc_mar(i,r,ccseason,t)$[tload(t)$pvb(i)] = min{ m_cc_mar(i,r,ccseason,t), 1 / ilr(i) - bcr(i) } ;

cc_old(i,r,ccseason,t)$[tload(t)$pvb(i)$sum{(v,tt)$tprev(t,tt), CAP.l(i,v,r,tt)}] =
    min{ cc_old(i,r,ccseason,t) / sum{(v,tt)$tprev(t,tt), CAP.l(i,v,r,tt)}, 1 / ilr(i) - bcr(i) }
    * sum{(v,tt)$tprev(t,tt), CAP.l(i,v,r,tt)};

mean_forced_outage_rate(i,r,ccseason,t)$tload(t) = mean_forced_outage_rate_load(i,r,ccseason,t) ;
$endif.tcheck

$include reeds%ds%core%ds%solve%ds%2_financials.gms

if(Sw_GrowthPenalties > 0,
*rsc_fin_mult holds the multipliers for sccapcosttech, so don't include them here
    cost_growth(i,st,t)$[tmodel(t)$sum{r$[r_st(r,st)], valinv_irt(i,r,t) }$stfeas(st)$(not sccapcosttech(i))] = 
        smin{r$[valinv_irt(i,r,t)$r_st(r,st)$cost_cap_fin_mult(i,r,t)],
            cost_cap_fin_mult(i,r,t) * cost_cap(i,t) } ;

*rsc_fin_mult holds the capital costs for sccapcosttech
    cost_growth(i,st,t)$[tmodel(t)$sum{r$[r_st(r,st)], valinv_irt(i,r,t) }$stfeas(st)$sccapcosttech(i)] = 
        smin{(r,rscbin)$[valinv_irt(i,r,t)$r_st(r,st)$rsc_fin_mult(i,r,t)],
            rsc_fin_mult(i,r,t) * m_rsc_dat(r,i,rscbin,"cost") } ;

    cost_growth(i,st,t)$cost_growth(i,st,t) = round(cost_growth(i,st,t),3) ;
) ;

%%PINS%%

model %%MODEL%% /
%%EQUATIONS%%
/ ;

%%MODEL%%.holdfixed = 1 ;

execute_unload '%port_dir%%ds%port_inputs_%cur_year%.gdx' ;

OPTION lp = convert ;
%%MODEL%%.optfile = 1 ;
$echo dumpgdx %port_dir%%ds%port_jacobian_%cur_year%.gdx > convert.opt
solve %%MODEL%% minimizing z using lp ;

OPTION lp = %solver% ;
%%MODEL%%.optfile = %GSw_gopt% ;
solve %%MODEL%% minimizing z using lp ;

execute_unload '%port_dir%%ds%port_solution_%cur_year%.gdx' ;

if (%%MODEL%%.modelStat > 1,
    abort "Port model did not solve to optimality", %%MODEL%%.modelStat) ;
