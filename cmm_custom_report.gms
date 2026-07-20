* Custom Reporting to add to Reeds standard reporting

set 
steeltype "types of steel"
/
carbon, 
hsla, 
stainless
/ 
; 

Parameters

steel_int_i(i,steeltype) "share of each steel type by model technology category (i)"
steel_int_tcat(tcat, steeltype) "share of each steel type by input technology category (tcat)"
/
Oil.carbon        0.93
Oil.hsla          0.03
Oil.stainless     0.035

Coal.carbon       0.91
Coal.hsla         0.04
Coal.stainless    0.045

CoalCCS.carbon    0.885
CoalCCS.hsla      0.04
CoalCCS.stainless 0.060

NaturalGas.carbon       0.91
NaturalGas.hsla         0.04
NaturalGas.stainless    0.045

NaturalGasCCS.carbon       0.885
NaturalGasCCS.hsla         0.04
NaturalGasCCS.stainless    0.060

Nuclear.carbon       0.885
Nuclear.hsla         0.035
Nuclear.stainless    0.060

BiomassAndWaste.carbon       0.89
BiomassAndWaste.hsla         0.04
BiomassAndWaste.stainless    0.055

BiomassCCS.carbon       0.865
BiomassCCS.hsla         0.04
BiomassCCS.stainless    0.070

Hydro.carbon       0.93
Hydro.hsla         0.04
Hydro.stainless    0.020

Geothermal.carbon       0.86
Geothermal.hsla         0.04
Geothermal.stainless    0.090

WindOnshore.carbon       0.275
WindOnshore.hsla         0.675
WindOnshore.stainless    0.020

WindOffshore.carbon       0.175
WindOffshore.hsla         0.725
WindOffshore.stainless    0.020

SolarPV.carbon       0.91
SolarPV.hsla         0.055
SolarPV.stainless    0.020

SolarCSP.carbon       0.86
SolarCSP.hsla         0.070
SolarCSP.stainless    0.045
/
steel_demand "steel demand for each technology category by steel type"
material_demand "material demand for each technology category (including transmissions) by state"
rep_mat "reporting parameter for aggregate material demand, production, and slack" 
;

* map the steel type shares from the input technology category to the model technology category using the tcat mapping
steel_int_i(i,steeltype) = sum(tcat$i_tcat(i,tcat),steel_int_tcat(tcat,steeltype)) ; 

* -- calculate steel demand by technology category and steel type
steel_demand(tcat,steeltype,t)$tmodel_new(t) = 
* the share of steel by type 
        steel_int_tcat(tcat,steeltype) * (
* Steel needed for investment in new capacity 
* material (metric ton / MW) * capacity investment (MW)
        sum{(i,v,r)$[valinv(i,v,r,t)$i_int(i,"Steel")$i_tcat(i,tcat)],
            i_int(i,"Steel") * INV.l(i,v,r,t)} 
* Steel needed for upgrades of existing capacity
* materials (metric ton / MW) * capacity upgraded (MW)
        + sum{(i,v,r)$[valcap(i,v,r,t)$upgrade(i)$Sw_Upgrades$i_int(i,"Steel")$i_tcat(i,tcat)],
            i_int(i,"Steel") * UPGRADES.l(i,v,r,t) }
        ) / yearweight(t);
    

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

* reporting parameters for material demand and production
rep_mat(mat,t,'demand')$tmodel_new(t) = MAT_DEMAND.l(mat,t) / yearweight(t) ;
rep_mat(mat,t,'usa_prod')$tmodel_new(t) = Sw_prod_multiplier_usa * sum{mat_ctry$[usa(mat_ctry)], mat_prod(mat,mat_ctry)} ;
rep_mat(mat,t,'allies_prod')$tmodel_new(t) = (Sw_prod_multiplier_allies * sum{mat_ctry$[allies(mat_ctry)], mat_prod(mat,mat_ctry)})$Sw_mat_allies ;
rep_mat(mat,t,'global_prod')$tmodel_new(t) = 
    (Sw_prod_multiplier_glb * sum{mat_ctry$[not usa(mat_ctry)], mat_prod(mat,mat_ctry)})$Sw_mat_glb 
    + (sum{mat_ctry$[glb_nochina(mat_ctry)], mat_prod(mat,mat_ctry)})$Sw_mat_glb_nochina
    + (sum{mat_ctry$[(not usa(mat_ctry))$(not sameas(mat,'Lithium'))], mat_prod(mat,mat_ctry)})$Sw_mat_glb_nolith
    + (sum{mat_ctry$[(not usa(mat_ctry))$(not sameas(mat,'Silicon'))], mat_prod(mat,mat_ctry)})$Sw_mat_glb_nosil
;
rep_mat(mat,t,'slack')$tmodel_new(t) =  MAT_SLACK.l(mat,t) / yearweight(t) ;

execute_unload 'runs/cmm_custom_2026/cmm_report_%case%.gdx' rep_mat, steel_int_i, steel_int_tcat, steel_demand, material_demand ;
*execute_unload 'runs/cmm_custom_2026/outputs_%case%.gdx'