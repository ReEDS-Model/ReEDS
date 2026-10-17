eq_cap_init_noret(i,v,r,t)$[valcap(i,v,r,t)$tmodel(t)$initv(v)$(not upgrade(i))
                           $(not retiretech(i,v,r,t))$(not Sw_PCM)]..

    m_capacity_exog(i,v,r,t) * degrade_init(i,v,r,t)

* Account for capacity upsizing within init vintages
    + sum{(tt,rscbin)$[(tmodel(tt) or tfix(tt))$allow_cap_up(i,v,r,rscbin,tt)],
                      degrade_new(i,tt,t) * INV_CAP_UP(i,v,r,rscbin,tt) }

    =e=

    CAP(i,v,r,t)

    + sum{(ii,tt)$[(tfix(tt) or tmodel(tt))$(yeart(tt)<=yeart(t))
                   $valcap(ii,v,r,tt)$upgrade_from(ii,i)],
                     UPGRADES(ii,v,r,tt) 
                     - (UPGRADES_RETIRE(ii,v,r,tt)$[not noret_upgrade_tech(ii)])}
                       $[(Sw_Upgrades = 1)]

* include contemporaneous upgrades when they are intended to
* persist as new bintages with sw_upgrades = 2
    + sum{(ii)$[upgrade_from(ii,i)$valcap(ii,v,r,t)$(not sameas(ii,'hydEND_hydED'))], 
            UPGRADES(ii,v,r,t) }$[Sw_Upgrades = 2]

    + sum{ii$[valcap(ii,v,r,t)$upgrade_from(ii,i)$sameas(ii,'hydEND_hydED')],
          CAP(ii,v,r,t) }$[Sw_Upgrades = 2]
;
