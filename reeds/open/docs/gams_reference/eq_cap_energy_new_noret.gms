eq_cap_energy_new_noret(i,v,r,t)$[valcap(i,v,r,t)$tmodel(t)$battery(i)$(not Sw_PCM)]..
    
    sum{tt$[inv_cond(i,v,r,t,tt)$(tmodel(tt) or tfix(tt))$valcap(i,v,r,tt)],
              degrade_new(i,tt,t) * (INV_ENERGY(i,v,r,tt))
        }
        
    - sum{(tt,ttt)$[inv_cond(i,v,r,tt,ttt)$(tmodel(tt) or tfix(tt))$valcap(i,v,r,ttt)$(tt.val>=ttt.val)$(t.val>=tt.val)],
               degrade_new(i,ttt,tt) * prescribed_retirements_energy(i,v,r,tt,ttt)
        }

    + m_capacity_exog_energy(i,v,r,t)

    =e=

    CAP_ENERGY(i,v,r,t)

;
