* Custom Reporting to add to Reeds standard reporting

Parameters
material_demand "material demand for each technology category (including transmissions) by state"
material_supply "material supply for each material"
rep_mat "reporting parameter for aggregate material demand, supply, and slack" 
;

* -- Material demand by technology category and state
material_demand(tcat,mat,st,t)$tmodel_new(t) = 
* Materials needed for investment in new capacity 
* material (metric ton / MW) * capacity investment (MW)
        (sum{(i,v,r)$[valinv(i,v,r,t)$i_int(i,mat)$i_tcat(i,tcat)$r_st(r,st)],
            i_int(i,mat) * INV.l(i,v,r,t) }

* Materials needed for upgrades of existing capacity
* materials (metric ton / MW) * capacity upgraded (MW)
        + sum{(i,v,r)$[valcap(i,v,r,t)$upgrade(i)$Sw_Upgrades$i_int(i,mat)$i_tcat(i,tcat)$r_st(r,st)],
            i_int(i,mat) * UPGRADES.l(i,v,r,t) }
        )
            / yearweight(t)
;

* -- Material demand for transmission by state
material_demand('transmission',mat,st,t)$tmodel_new(t) = 
*intra-state transmission
    (sum((r,rr,trtype)$[routes_inv(r,rr,trtype,t)$r_st(r,st)$r_st(rr,st)$trt_int(trtype,mat)],
        trt_int(trtype,mat) * (INVTRAN.l(r,rr,trtype,t) + invtran_exog(r,rr,trtype,t)) * distance(r,rr,trtype)) 
* inter-state transmission
* each state gets half of the investment
    + sum((r,rr,trtype)$[routes_inv(r,rr,trtype,t)$r_st(r,st)$(not r_st(rr,st))$trt_int(trtype,mat)],
        trt_int(trtype,mat) * (INVTRAN.l(r,rr,trtype,t) + invtran_exog(r,rr,trtype,t)) * distance(r,rr,trtype)) / 2
    )
    / yearweight(t)

;

material_supply(tcat,mat,t)$[tmodel_new(t)$(not sameas(mat,'%GSw_matsupply_spec%'))] =
* domestic production 
      (Sw_prod_multiplier_usa * sum{mat_ctry$[usa(mat_ctry)], mat_prod(mat,mat_ctry)} * yearweight(t))$Sw_mat_domestic
* add global production outside US 
    + (sum{mat_ctry$[(not usa(mat_ctry))], mat_prod(mat,mat_ctry)} * yearweight(t))$Sw_mat_glb
* add domestic byproduct recovery 
    + (sum{mat_ctry$[usa(mat_ctry)], mat_byproduct(mat,mat_ctry)} * yearweight(t))$Sw_mat_byproduct
* add domestic reserves 
    + (sum{mat_ctry$[usa(mat_ctry)], mat_reserve(mat,mat_ctry)} * yearweight(t))$Sw_mat_reserve
* add allied production
    + (sum{mat_ctry$[allies(mat_ctry)], mat_prod(mat,mat_ctry)} * yearweight(t))$Sw_mat_allies
;


* reporting parameters for material demand and production
rep_mat(mat,t,'demand')$tmodel_new(t) = MAT_DEMAND.l(mat,t) / yearweight(t) ;
rep_mat(mat,t,'supply')$tmodel_new(t) = MAT_SUPPLY.l(mat,t) / yearweight(t) ;
rep_mat(mat,t,'slack')$tmodel_new(t) =  MAT_SLACK.l(mat,t) / yearweight(t) ;
rep_mat(mat,t,'applied_price')$tmodel_new(t) = matprice_multiplier(mat,t) * mat_price(mat) ;

execute_unload 'runs/cmm_custom_2026/cmm_report_%case%.gdx' rep_mat, material_demand, material_supply ;
*execute_unload 'runs/cmm_custom_2026/outputs_%case%.gdx'