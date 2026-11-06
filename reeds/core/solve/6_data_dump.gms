$ontext
This file creates a gdx file with all of the data necessary for the resource adequacy calculations:
    - Generator capacities
    - Exogenous retirments (sequential solves only)
    - Wind capacity by build year (because wind CFs change by build year)
    - heat rates, fuel costs, and vom costs
    - capacity factors (hydro, wind)
    - availability rates (1 - outage rates)
    - transmission capacities and loss rates
    - technology sets
$offtext

$if not set start_year $setglobal start_year %startyear%

*===============================
* Set and parameter definitions
*===============================

set rfeas(r)                 "list of feasible r regions"
    trange(t)                "range from first year to current year"
    tcur(t)                  "current year"
    tnext(t)                 "next year"
    valcap_i_filt(i)         "subset of valcap"
    valcap_ir_filt(i,r)      "subset of valcap"
    valcap_iv_filt(i,v)      "subset of valcap"
    routes_filt(r,rr,trtype) "set of transmission connections"
;

parameter
avail_filt(i,v,r,allszn)           "--fraction-- fraction of capacity available for generation by season"
can_exports_h_filt(r,allh)         "--MW-- Canada exports by region and timeslice filtered for the previous solve year"
can_imports_cap(i,v,r)             "--MW-- Canadian import max capacity"
can_imports_szn_filt(r,allszn)     "--MWh-- Canada imports by region and season filtered for the previous solve year"
cap_converter_filt(r)              "--MW-- VSC AC/DC converter capacity"
cap_exist_i(i)                     "--MW-- technologies with existing capacity in the current solve year"
cap_exist_ir(i,r)                  "--MW-- technology-region combinations with existing capacity in the current solve year"
cap_exist_iv(i,v)                  "--MW-- technology-vintage combinations with existing capacity in the current solve year"
cap_exist(i,v,r)                   "--MW-- capacity that exists in the current solve year"
cap_exog_filt(i,v,r)               "--MW-- exogenous capacity"
cap_hyd_szn_adj_filt(i,allszn,r)   "--fraction-- seasonal hydro capacity adjustment filtered for the previous solve year"
cap_init(i,v,r)                    "--MW-- initial capacity"
cap_ivrt(i,v,r,t)                  "--MW-- generation power capacity"
cap_energy_ivrt(i,v,r,t)           "--MWh-- generation energy capacity"
cap_pvb(i,v,r)                     "--MW-- Hybrid PV+battery capacity (PV)"
cap_trans_energy(r,rr,trtype)      "--MW-- transmission capacity for energy trading"
cap_trans_prm(r,rr,trtype)         "--MW-- transmission capacity for PRM trading"
cf_adj_t_filt(i,v,t)               "--fraction-- capacity factor adjustment for wind"
cost_cap_filt(i,t)                 "--2004$/MW-- technology capital costs"
cost_cap_fin_mult_filt(i,r,t)      "--unitless-- capital cost financial multipliers"
cost_vom_filt(i,v,r)               "--$/MWh-- VO&M costs filtered for the previous solve year and existing capacity"
ctt_i_ii_filt(i,ii)                "--set-- set linking watercooling techs i to numeraire techs ii filtered for existing watercooling techs"
ctt_i_ii_psh(i,ii)                 "--set-- set linking PSH techs with water i to numeraire techs ii filtered for valid capacity techs"
emit_rate_filt(e,i,v,r)            "--metric tons/MWh-- emission rate for the previous solve year"
flex_load_opt(r,allh)              "--MW-- model results for optimizing flexible load"
flex_load(r,allh)                  "--MW-- total exogenously defined flexible load"
gen_h_stress_filt(s,i,r,allh,t)      "--MW-- generation by stress timeslice with charge and production load as negative generation"
heat_rate_filt(i,v,r)              "--MMBtu/MWh-- heat rate"
inv_cond_filt(i,v,t)               "--set-- vintage-year mapping for investments by technology"
inv_ivrt(i,v,r,t)                  "--MW-- investments in power generation capacity"
inv_energy_ivrt(i,v,r,t)           "--MWh-- investments in energy generation capacity"
m_cf_filt(i,v,r,allh)              "--fraction-- capacity factor used in the model"
m_cf_szn_filt(i,v,r,allszn)        "--fraction-- modelled capacity factors filtered for hydro resources to set seasonal energy constraints"
minloadfrac_filt(r,i,allszn)       "--fraction-- modelled mingen fraction filtered for hydro resources to set mingen constraints"
prod_filt(s,i,v,r,allh)              "--MW-- power consumed for PRODUCE.l"
ra_cap_loadsite(r,t)               "--MW-- capacity of flexibly sited load"
ret_ivrt(i,v,r,t)                  "--MW-- retirements of generation capacity"
ret(i,v,r)                         "--MW-- retirements of generation capacity"
rsc_dat_filt(i,r,sc_cat,rscbin)    "--$/MW-- capital costs filtered for pumped-hydro so arbitrage value doesn't exceed capital costs"
storage_eff_filt(i)                "--fraction-- storage efficiency filtered for the next solve year"
upgrade_to_filt(i,ii)              "--set-- set linking upgrade techs to the tech the upgraded from filtered for existing upgrades"
;

rfeas(r) = yes ;

trange(t) = no ;
loop(t$[(yeart(t)>%start_year%)$(yeart(t)<=%next_year%)],
trange(t) = yes ;
) ;
trange("%next_year%") = no ;
trange("%cur_year%") = yes ;

tcur(t) = no ;
tcur("%cur_year%") = yes ;

tnext(t) = no ;
tnext("%next_year%") = yes ;

*populate reduced-form sets
valcap_iv_filt(i,v) = sum{(r,t)$tcur(t), valcap(i,v,r,t)} ;
valcap_i_filt(i) = sum{v, valcap_iv_filt(i,v)} ;
valcap_ir_filt(i,r) = sum{t$tcur(t), valcap_irt(i,r,t)} ;

*=======================================
* Removing banned technologies from sets
*=======================================

csp_sm(i) = csp_sm(i)$(not ban(i)) ;
geo(i) = geo(i)$(not ban(i)) ;
hydro_d(i) = hydro_d(i)$(not ban(i)) ;
hydro_nd(i) = hydro_nd(i)$(not ban(i)) ;
nuclear(i) = nuclear(i)$(not ban(i)) ;
storage_duration(i) = storage_duration(i)$(not ban(i)) ;
storage_eff(i,t) = storage_eff(i,t)$(not ban(i)) ;
storage_standalone(i) = storage_standalone(i)$(not ban(i)) ;

*==============================
* Get ReEDS generation capacity
*==============================

cap_exist(i,v,r)$valcap_ivr(i,v,r) = sum{t$tcur(t), CAP.l(i,v,r,t) } ;
cap_exist_ir(i,r)$valcap_ir_filt(i,r) = sum{v, cap_exist(i,v,r) } ;
cap_exist_iv(i,v)$valcap_iv_filt(i,v) = sum{r, cap_exist(i,v,r) } ;
cap_exist_i(i)$valcap_i_filt(i) = sum{(r,v), cap_exist(i,v,r) } ;

cap_ivrt(i,v,r,t)$([not (upv(i) or wind(i) or distpv(i))]$valcap(i,v,r,t)$trange(t)) = CAP.l(i,v,r,t) ;
cap_energy_ivrt(i,v,r,t)$[valcap(i,v,r,t)$trange(t)$battery(i)] = CAP_ENERGY.l(i,v,r,t) ;
cap_ivrt(i,v,r,t)$([upv(i) or wind(i) or distpv(i)]$valcap(i,v,r,t)) =
    m_capacity_exog(i,v,r,t)$trange(t)
    + sum{tt$[inv_cond(i,v,r,t,tt)$trange(tt)],
          INV.l(i,v,r,tt) + INV_REFURB.l(i,v,r,tt)$[refurbtech(i)$Sw_Refurb]} ;
cap_init(i,v,r)$([not distpv(i)]$valcap_ivr(i,v,r)) = sum{t$tcur(t), cap_ivrt(i,v,r,t)$initv(v) } ;
cap_init(i,v,r)$(distpv(i)$valcap_ivr(i,v,r)) = sum{t$tfirst(t), cap_ivrt(i,v,r,t) } ;
inv_ivrt(i,v,r,t)$[valcap(i,v,r,t)$trange(t)] = [INV.l(i,v,r,t) + INV_REFURB.l(i,v,r,t)]$valinv(i,v,r,t) + UPGRADES.l(i,v,r,t)$[upgrade(i)$valcap(i,v,r,t)$Sw_Upgrades] ;
inv_energy_ivrt(i,v,r,t)$[valcap(i,v,r,t)$trange(t)$battery(i)] = INV_ENERGY.l(i,v,r,t);
inv_ivrt("distpv",v,r,t)$([trange(t)$(not tfirst(t))]$valcap("distpv",v,r,t)) = cap_ivrt("distpv",v,r,t) - sum{tt$tprev(t,tt), cap_ivrt("distpv",v,r,tt) } ;
inv_ivrt("distpv","init-1",r,"%next_year%") = inv_distpv(r,"%next_year%") ;

ret_ivrt(i,v,r,t)$([trange(t)$(not tfirst(t))$newv(v)]$valcap(i,v,r,t)) = sum{tt$tprev(t,tt), cap_ivrt(i,v,r,tt)} - cap_ivrt(i,v,r,t) + inv_ivrt(i,v,r,t) ;
ret_ivrt(i,v,r,t)$([abs(ret_ivrt(i,v,r,t) < 1e-6)]$valcap(i,v,r,t)) = 0 ;

ret(i,v,r)$valcap_ivr(i,v,r) = sum{t, ret_ivrt(i,v,r,t) } ;

cap_exog_filt(i,v,r)$([not canada(i)]$valcap_ivr(i,v,r)) = sum{t$tnext(t), m_capacity_exog(i,v,r,t) } ;

gen_h_stress_filt(s,i,r,allh,t)$[tcur(t)$valgen_irt(i,r,t)$h_stress_t(allh,t)] =
  sum{v$valgen(i,v,r,t), GEN.l(s,i,v,r,allh,t)}
;

*============================
* Filter necessary input data
*============================

avail_filt(i,v,r,szn)$[cap_exist_iv(i,v)$(not vre(i))] =
    smax{h$h_szn(h,szn), avail(i,r,h) * derate_geo_vintage(i,v) } ;

can_exports_h_filt(r,h) = sum{t$tcur(t), can_exports_h(r,h,t)} ;

can_imports_cap(i,v,r)$canada(i) = sum{t$tcur(t), m_capacity_exog(i,v,r,t) } ;

can_imports_szn_filt(r,szn) = sum{t$tcur(t), can_imports_szn(r,szn,t)} ;

*can_exports_h_filt(r,h)$[Sw_Canada = 2] = 0 ;
*can_imports_cap(i,v,r)$[Sw_Canada = 2] = 0 ;
*can_imports_szn_filt(r,szn)$[Sw_Canada = 2] = 0 ;

cap_hyd_szn_adj_filt(i,szn,r)$[cap_exist_ir(i,r)$hydro_d(i)] = cap_hyd_szn_adj(i,szn,r) ;

cost_cap_filt(i,t)$[storage_standalone(i)] = cost_cap(i,t)$tnext(t) ;

cost_cap_fin_mult_filt(i,r,t)$([storage_standalone(i)]) = cost_cap_fin_mult(i,r,t)$tnext(t) ;

cost_vom_filt(i,v,r)$cap_exist(i,v,r) = sum{t$tcur(t), cost_vom(i,v,r,t) } ;

cf_adj_t_filt(i,v,t)$[cap_exist_iv(i,v)$trange(t)] = sum{c$i_c(i,c), cf_adj_t(i,c,v,t) } ;
cf_adj_t_filt(i,v,"%next_year%") = sum{c$i_c(i,c), cf_adj_t(i,c,v,"%next_year%") }$(vre(i) or pvb(i)) ;

ctt_i_ii_filt(i,ii) = ctt_i_ii(i,ii)$cap_exist_i(i) ;

ctt_i_ii_psh(i,ii) = ctt_i_ii(i,ii)$[valcap_i_filt(i)$psh(i)] ;

emit_rate_filt(e,i,v,r)$cap_exist(i,v,r) = sum{(t,etype)$tcur(t), emit_rate(etype,e,i,v,r,t) } ;

heat_rate_filt(i,v,r)$cap_exist(i,v,r) = sum{t$tcur(t), heat_rate(i,v,r,t) } ;

inv_cond_filt(i,v,t)$[(vre(i) or pvb(i))$tnext(t)] = sum{(tt,r), inv_cond(i,v,r,tt,t) } ;

m_cf_filt(i,v,r,h)$[(vre(i) or pvb(i))$cap_exist(i,v,r)] = sum{(t,c)$[tnext(t)$i_c(i,c)], m_cf(i,c,v,r,h,t) } ;

m_cf_szn_filt(i,v,r,szn)$[hydro(i)$cap_exist(i,v,r)] = sum{t$tcur(t), m_cf_szn(i,v,r,szn,t) } ;

minloadfrac_filt(r,i,szn)$[hydro(i)$cap_exist_ir(i,r)$szn_rep(szn)] =
    sum{h$h_szn(h,szn), minloadfrac(r,i,h) * hours(h) } / sum{h$h_szn(h,szn), hours(h) } ;

rsc_dat_filt(i,r,"cost",rscbin)$[storage_standalone(i)$cap_exist_ir(i,r)] = rsc_dat(i,r,"cost",rscbin) ;


storage_eff_filt(i)$storage(i) = sum{t$tnext(t), storage_eff(i,t) } ;

upgrade_to_filt(i,ii) = upgrade_to(i,ii)$cap_exist_i(i) ;

*============================
* Get ReEDS transmission data
*============================

cap_trans_energy(r,rr,trtype) = sum{t$tcur(t), CAPTRAN_ENERGY.l(r,rr,trtype,t) } ;
cap_trans_prm(r,rr,trtype) = sum{t$tcur(t), CAPTRAN_PRM.l(r,rr,trtype,t) } ;

cap_converter_filt(r) = sum{t$tcur(t), CAP_CONVERTER.l(r,t) } ;

* In resource adequacy calculations, trtype="AC" includes everything except for VSC
routes_filt(r,rr,trtype) = sum{t$tcur(t), routes(r,rr,trtype,t) } ;

*============================
* Flexible load data
*============================

flex_load(r,h) = sum{(flex_type,t)$tcur(t), load_exog_flex(flex_type,r,h,t) } ;

flex_load_opt(r,h) = sum{(flex_type,t)$tcur(t), FLEX.l(flex_type,r,h,t) } ;

ra_cap_loadsite(r,t)$[Sw_LoadSiteCF$val_loadsite(r)] = CAP_LOADSITE.l(r,t) ;

*============================
* Extra consumption data
*============================

prod_filt(s,i,v,r,h)$[sum{t$tcur(t), valcap(i,v,r,t)}$consume(i)$hours(h)] =
                sum{(p,t)$[i_p(i,p)$tcur(t)], PRODUCE.l(s,p,i,v,r,h,t) / prod_conversion_rate(i,v,r,t) } ;

*=======================================
* Unload all relevant data to a gdx file
*=======================================

execute_unload 'handoff%ds%reeds_data%ds%reeds_data_%cur_year%.gdx'
    avail_filt
    bcr
    bir_pvb_config
    can_exports_h_filt
    can_imports_cap
    can_imports_szn_filt
    cap_converter_filt
    cap_exog_filt
    cap_hyd_szn_adj_filt
    cap_init
    cap_ivrt
    cap_energy_ivrt
    cap_trans_energy
    cap_trans_prm
    cf_adj_t_filt
    converter_efficiency_vsc
    cost_cap_filt
    cost_cap_fin_mult_filt
    cost_vom_filt
    csp_sm
    ctt_i_ii_filt
    ctt_i_ii_psh
    degrade_annual
    emit_rate_filt
    flex_load
    flex_load_opt
    fuel2tech
    gen_h_stress_filt
    geo
    h_szn
    heat_rate_filt
    hierarchy
    hydro_d
    hydro_nd
    hours
    hydmin
    i
    ilr
    ilr_pvb_config
    i_subsets
    inv_cond_filt
    inv_ivrt
    inv_energy_ivrt
    ivt_num
    m_cf_filt
    m_cf_szn_filt
    maxage
    minloadfrac_filt
    notvsc
    nuclear
    prm
    prod_filt
    pvf_onm
    r
    rfeas
    r_cendiv
    ra_cap_loadsite
    ret
    ret_ivrt
    routes_filt
    rsc_dat_filt
    sdbin
    storage_duration
    storage_eff
    storage_eff_filt
    storage_standalone
    Sw_VSC
    szn
    tfirst
    tmodel_new
    tranloss
    trtype
    upgrade_to_filt
    v
    vom_hyd
;


*** dump data for tax credit phaseout calculations
execute_unload "outputs%ds%tc_phaseout_data%ds%emit_for_tc_phaseout_calc_%cur_year%.gdx"
  emit_nat_tc, emit_r_tc
;
