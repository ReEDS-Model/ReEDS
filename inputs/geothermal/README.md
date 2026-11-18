## Geothermal Input Files

- `geo_discovery_BAU.csv`: Business-as-usual trajectory for the fraction [fraction] of undiscovered geothermal resource that has been discovered, by year
  - selected with `geodiscov = BAU`

- `geo_discovery_factor_ATB_2023.csv`: Factor [fraction] representing the share of geothermal resource already discovered, by technology and region, from the ATB 2023 geohydro supply curve
  - Selected by the `geohydrosupplycurve` switch

- `geo_discovery_factor_reV.csv`: Factor [fraction] representing the share of geothermal resource already discovered, by technology and region, derived from reV
  - Selected by the `geohydrosupplycurve` switch

- `geo_discovery_TI.csv`: Accelerated trajectory for the fraction [fraction] of undiscovered geothermal resource that has been discovered, by year
  - selected with `geodiscov = TI`

- `geo_rsc_ATB_2023.csv`: Geothermal supply curve by technology and region for the EGS and geohydro technologies
  - `sc_cat = cap` gives available capacity [MW]; `sc_cat = cost` gives the supply-curve capital cost adder [$/MW], which is deflated during input processing
