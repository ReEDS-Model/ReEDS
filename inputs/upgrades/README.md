## Upgrades Input Files

- `i_coolingtech_watersource_upgrades.csv`: List of cooling technologies for water sources that can be upgraded.

- `i_coolingtech_watersource_upgrades_link.csv`: List of cooling technologies for water sources that can be upgraded + their to, from, ctt (cooling technology type) and wst (water source type)

- `upgrade_costs_ccs_coal.csv`: Capital cost [2004$/kW] to upgrade a coal plant to coal-CCS, by year and cost scenario
  - The scenario column is selected by the `ccs_upgrade_cost_case` switch; applied to all coal-CCS upgrade technologies
  - Data come from the ATB 2025 coal retrofit costs with 90% capture. See https://github.com/ReEDS-Model/ReEDS_Input_Processing/tree/main/atb

- `upgrade_costs_ccs_gas.csv`: Capital cost [2004$/kW] to upgrade a gas plant to gas-CCS, by year and cost scenario
  - The scenario column is selected by the `ccs_upgrade_cost_case` switch; applied to all gas-CC-CCS upgrade technologies
  - Data come from the ATB 2025 natural gas combined cycle (F-Class) retrofit costs with 90% capture. See https://github.com/ReEDS-Model/ReEDS_Input_Processing/tree/main/atb

- `upgrade_link.csv`: Techs that can be upgraded including the original technology, the technology it is upgrading to, and the delta.

- `upgrade_mult_atb23_ccs_*.csv`: Capital cost multiplier [unitless] by upgrade technology and year, from ATB 2023 (no longer used)
  - `upgrade_mult_atb23_ccs_adv.csv`: advanced
  - `upgrade_mult_atb23_ccs_con.csv`: conservative
  - `upgrade_mult_atb23_ccs_mid.csv`: Mid

- `upgrade_mult_atb25_ccs_*.csv`: Capital cost multiplier [unitless] by upgrade technology and year
  - Selected by the `GSw_UpgradeCost_Mult` switch (`0` = mid, `1` = advanced, `2` = conservative)
  - Data come from the ATB 2025 retrofit costs, divided by the Moderate cost in 2028. See https://github.com/ReEDS-Model/ReEDS_Input_Processing/tree/main/atb
  - `upgrade_mult_atb25_ccs_adv.csv`: advanced
  - `upgrade_mult_atb25_ccs_con.csv`: conservative
  - `upgrade_mult_atb25_ccs_mid.csv`: Mid

- `upgradelink_water.csv`: Water techs that can be upgraded including the original technology, the technology it is upgrading to, and the delta
