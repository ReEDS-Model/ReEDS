eq_rsc_INVlim(r,i,rscbin,t)$[tmodel(t)
                            $rsc_i(i)
                            $m_rscfeas(r,i,rscbin)
                            $m_rsc_con(r,i)
                            $(not flag_eq_rsc_INVlim(r,i,rscbin,t))
                            $(not Sw_PCM)]..
*With water constraints, some RSC techs are expanded to include cooling technologies
*but the combination of m_rsc_con and rsc_agg allows for those investments
*to be limited by the numeraire techs' m_rsc_dat

*capacity indicated by the resource supply curve minus exogenous (pre-start-year)
*capacity (scaled by rsc_capacity_scalar)
    (m_rsc_dat(r,i,rscbin,"cap")
     - sum{(ii,v,tt)$[tfirst(tt)$rsc_agg(i,ii)$exog_rsc(i)],
         capacity_exog_rsc(ii,v,r,rscbin,tt) } )
        * (1$[not rsc_capacity_scalar_i(i)]
           + rsc_capacity_scalar(i,r,t)$rsc_capacity_scalar_i(i))
* available hydro upgrade capacity
    + hyd_add_upg_cap(r,i,rscbin,t)$(Sw_HydroCapEnerUpgradeType=1)

    =g=

*must exceed the cumulative invested capacity in that region/class/bin...
    sum{(ii,v,tt)$[valinv(ii,v,r,tt)$(yeart(tt) <= yeart(t))$rsc_agg(i,ii)],
         INV_RSC(ii,v,r,rscbin,tt) * resourcescaler(ii) }

;
