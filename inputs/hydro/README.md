## Hydro Input Files

- `cap_existing_hydro.csv`: Annual capacities [MW] for hydro plants spanning 2007-2022, which come from ORNL's Existing Hydropower Assets dataset

- `hyd_fom.csv`: Regional fixed O&M cost [$/MW-year] for hydro technologies

- `hydcf_fixed.csv`: Fixed monthly zonal hydro capacity factor data partially created by ORNL and partially derived from ORNL's Existing Hydropower Assets dataset

- `hydro_mingen.csv`: Minimum hydropower loading factor [fraction of capacity] by technology, region, and quarter

- `net_gen_existing_hydro.csv`: Monthly net generation values [MWh] for hydro plants spanning 2007-2022, which come from ORNL's Existing Hydropower Assets dataset

- `SeaCapAdj_hy.csv`: Maximum capacity adjustment [fraction] for dispatchable hydro by technology, month, and region
  - Weighted into seasonal values during input processing to produce `cap_hyd_szn_adj`
