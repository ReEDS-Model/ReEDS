eq_cap_new_noret(i,v,r,t)$[valcap(i,v,r,t)$tmodel(t)$newv(v)$(not upgrade(i))
                          $(not retiretech(i,v,r,t))$(not Sw_PCM)]..
    
    sum{tt$[inv_cond(i,v,r,t,tt)$(tmodel(tt) or tfix(tt))$valcap(i,v,r,tt)],
              degrade_new(i,tt,t) * (INV(i,v,r,tt) + INV_REFURB(i,v,r,tt)$[refurbtech(i)$Sw_Refurb])
        }

    - sum{(tt,ttt)$[inv_cond(i,v,r,tt,ttt)$(tmodel(tt) or tfix(tt))$valcap(i,v,r,ttt)$(tt.val>=ttt.val)$(t.val>=tt.val)],
               degrade_new(i,ttt,tt) * prescribed_retirements(i,v,r,tt,ttt)
        }

* Account for capacity upsizing within new vintages
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
