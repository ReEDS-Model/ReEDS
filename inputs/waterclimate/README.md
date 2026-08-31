## Waterclimate Input Files

- `cost_cap_mult.csv`: Capital cost multiplier [fraction] used to differentiate cooling technology types, by technology and cooling technology type

- `cost_vom_mult.csv`: VOM cost multiplier [fraction] used to differentiate cooling technology types, by technology and cooling technology type

- `heat_rate_mult.csv`: Heat rate multiplier [fraction] used to differentiate cooling technology types, by technology and cooling technology type

- `i_coolingtech_watersource.csv`: List of the expanded (non-numeraire) technologies formed by combining each technology with a cooling technology type and water source type
  - Names follow the pattern `{tech}_{ctt}_{wst}`, e.g. `coal-CCS_mod_o_fsu`

- `i_coolingtech_watersource_link.csv`: Link from each expanded cooling/water technology to its base technology (`ii`), cooling technology type (`ctt`), and water source type (`wst`)

- `tg_rsc_cspagg_tmp.csv`: Expanded CSP resource aggregation mapping, extending `tg_rsc_cspagg(i,ii)` to include the non-numeraire CSP technologies

- `unapp_water_sea_distr.csv`: Fractional quarterly allocation [fraction] of unappropriated water, by water source type and region
  - Quarterly values sum to 1 for each water source type and region that has an allocation; regions with no unappropriated water of that type are all zero

- `wat_access_cap_cost.csv`: Water supply curve for post-2010 capacity, by water source type and region
  - `sc_cat = cap` gives available supply [million gallons/year]; `sc_cat = cost` gives the access cost [$/(million gallons/year)]
  - `sc_cat = cap` gives available supply [million gallons/year]; `sc_cat = cost` gives access cost [$ per million gallons/year]

- `water_req_psh_10h_1_51.csv`: Water required to fill the reservoir during PSH construction [Mgal/MW/year], by region and resource bin
  - Used only when both `GSw_PSHwatercon` and `GSw_WaterMain` are on

- `water_with_cons_rate.csv`: Water withdrawal and consumption rate [gal/MWh] by technology, cooling technology type, and form of water use (`w` = `with` or `cons`)
