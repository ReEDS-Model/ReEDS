### Sectoral load replacement
Hourlize uses the settings in `sector_config.json` to replace endogenous sector-specific load with load from exogenous sources. The sectoral settings are outlined below.

| Setting | Description |
| :------ | :---------- |
| subsectors | Dictionary listing the relevant sectors (keys) and subsectors (values) whose load should be replaced. Keys and values should correspond to entries of the "sector" and "subsector" columns of the input load profiles respectively |
| model_years | Model years in which load should be replaced. |
| filepaths | Paths to files containing exogenous sectoral load. The values in these files are combined and aggregated to the state level and then added to the input load profiles after removing endogenous sectoral load and aggregating to the state level. |
| unit_conversion_factor | Factor by which to multiply exogenous load to convert to MWh. |
| timezone | Timezone of the exogenous load profiles. This is used to convert exogenous load to the timezone of the input load profiles. |
| regional_scope | Regional scope of exogenous load. This is used to convert exogenous load to the state level (the scope of the input load). |

#### Data Centers
The "Data Centers" sector is treated as a special case, using a more complex pipeline mostly designed to ingest data center demand projections from the reVeal tool. This pipeline is contained in the `hourlize/reveal2reeds` folder. It takes annual national data center load and then splits it into hourly IT and cooling profiles for each state based on assumptions of state load participation, power usage effectiveness, and hourly propagation that are specified in the config. Unlike the other scenarios, this pipeline provides an option to add exogenous load to endogenous load rather than just replacing it. The relevant settings are outlined below.

| Setting | Description |
| :------ | :---------- |
| replace_existing_data_center_demand | Controls whether exogenous data center demand replaces the endogeous data center demand or adds to it. Replacement is the default behavior. |
| national_demand_source | Filepath to annual data center demand projections. The file must have columns "year" and "total_data_center_mw". Sub-national scope is allowed; in these cases, demand values are summed for each year to arrive at annual national demand values. |
| cooling_proportions_source | Filepath to hourly (weather year), state-level proportions of data center demand that should be attributed to cooling. The file must have columns "weather_datetime", "state", and "cooling_prop".
| state_proportions_source | Dictionary providing the filepath to annual percentages of national data center demand that should be attributed to each state and the scenario that should be taken from that file. The file must have columns "Run Name", "State", "Year", and "% of Total Data Center Load", and the "scenario" value of the dictionary must correspond to an entry in the "Run Name" column of the file.
| weather_year_propagation_source | Dictionary providing the filepath to annual (weather year) propagation factors and the scenario that should be taken from that file. Propagation factors represent the percentage of projected national data center demand for a given model year that is expected to be realized during each hour of each weather year. The file must have columns "year" (representing the weather year), "scenario" and "avg_prop", and the "scenario" value of the dictionary must correspond to an entry in the "scenario" column of the file.