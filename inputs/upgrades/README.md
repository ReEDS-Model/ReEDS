## Upgrades Input Files

- `i_coolingtech_watersource_upgrades.csv`: List of cooling technologies for water sources that can be upgraded.

- `i_coolingtech_watersource_upgrades_link.csv`: List of cooling technologies for water sources that can be upgraded + their to, from, ctt (cooling technology type) and wst (water source type)

- `upgrade_costs_ccs_coal.csv`: Exogenous capital cost [$/kW] to upgrade a coal plant to coal-CCS, by year and cost scenario
  - Used only when the `upgradescen` switch is not `default`; `default` instead derives the cost from the difference between the from- and to-technology

- `upgrade_costs_ccs_gas.csv`: Exogenous capital cost [$/kW] to upgrade a gas plant to gas-CCS, by year and cost scenario
  - Used only when the `upgradescen` switch is not `default`; `default` instead derives the cost from the difference between the from- and to-technology

- `upgrade_link.csv`: Techs that can be upgraded including the original technology, the technology it is upgrading to, and the delta.

- `upgrade_mult_atb23_ccs_*.csv`: Cost adjustment over various years for upgrade technologies
  - `upgrade_mult_atb23_ccs_adv.csv`: advanced
  - `upgrade_mult_atb23_ccs_con.csv`: conservative
  - `upgrade_mult_atb23_ccs_mid.csv`: Mid

- `upgradelink_water.csv`: Water techs that can be upgraded including the original technology, the technology it is upgrading to, and the delta
