# Power sector employment data
## Data input options
- `employment_factor_plant_jedi.csv`: Employment factor data for power plants of different technologies, taken from the JEDI/WIRED model.
Sources for employment data of individual technologies in JEDI/WIRED are shown in the table below.

```{table} Employment factors for individual ReEDS technologies
:name: employment-factors
| Technology              | Source                                                              |
|-------------------------|---------------------------------------------------------------------|
| Biopower                | JEDI {cite}`JobsEconomicDevelopment`                                              |
| Battery                 | WIRED {cite}`ramasamyUSSolarPhotovoltaic2022`                                   |
| Coal-IGCC               | WIRED {cite}`schmitt_et_al_2022`, {cite}`james_et_al_2023` and {cite}`EliminatingDerateCarbon`. |
| Coal-PC                 | WIRED {cite}`schmitt_et_al_2022`, {cite}`james_et_al_2023` and {cite}`EliminatingDerateCarbon`. |
| Coal-CCS RT             | WIRED {cite}`schmitt_et_al_2022`, {cite}`james_et_al_2023` and {cite}`EliminatingDerateCarbon`. |
| Coal-CCS GF             | WIRED {cite}`schmitt_et_al_2022`, {cite}`james_et_al_2023` and {cite}`EliminatingDerateCarbon`. |
| DPV                     | JEDI {cite}`JobsEconomicDevelopment`                                              |
| Geothermal-Hydrothermal | WIRED {cite}`hansonGeothermalElectricityTechnology2013`                                                   |
| Geothermal-EGS          | WIRED {cite}`hansonGeothermalElectricityTechnology2013`                                                   |
| Hydropower              | JEDI {cite}`JEDI_2025`                                              |
| Land-based Wind         | JEDI {cite}`JEDI_2025`                                              |
| NG-CC                   | WIRED {cite}`schmitt_et_al_2022`, {cite}`oakesCostPerformanceBaseline2023` and {cite}`schmittCostPerformanceRetrofitting2023`   |
| NG-CC-CCS RT            | WIRED {cite}`schmitt_et_al_2022`, {cite}`oakesCostPerformanceBaseline2023` and {cite}`schmittCostPerformanceRetrofitting2023`   |
| NG-CC-CCS GF            | WIRED {cite}`schmitt_et_al_2022`, {cite}`oakesCostPerformanceBaseline2023` and {cite}`schmittCostPerformanceRetrofitting2023`   |
| NG-CT                   | WIRED {cite}`schmitt_et_al_2022`, {cite}`oakesCostPerformanceBaseline2023` and {cite}`schmittCostPerformanceRetrofitting2023`   |
| Nuclear Conventional    | {cite}`abou-jaoudeLiteratureReviewAdvanced2023`                                      |
| Nuclear SMR             | {cite}`asuegaTechnoeconomicAnalysisAdvanced2023`                                           |
| Offshore Wind           | {cite}`hammondWindfarmOperationsMaintenance2022` and {cite}`nunemakerORBITOffshoreRenewables2020` |
| Transmission-500kW AC   | JEDI {cite}`JobsEconomicDevelopment`                                              |
| Transmission-230kW AC   | JEDI {cite}`JobsEconomicDevelopment`                                              |                                            |
| UPV                     | JEDI {cite}`JobsEconomicDevelopment` 
```

- `employment_factor_plant_mayfield.csv`, `employment_factor_plant_rutovitz.csv`, and `employment_factor_plant_ram.csv`: Employment factor data for power plants of different technologies, taken from literature -- Mayfield et al. (2023) {cite}`mayfieldLaborPathwaysAchieve2023`, Rutovitz et al. (2024) {cite}`rutovitzUpdatedEmploymentFactors2025` and Ram et al. (2020) {cite}`ramJobCreationGlobal2020`.

- `employment_factor_inter_transmission.csv`: Employment factor data for transmission line construction, taken from the four data source mentioned above (JEDI/WIRED models), Mayfield et al. (2023), Rutovitz et al. (2024) and Ram et al. (2020).

## Employment factor unit
- Power plants:
  - Construction: [job-years/MW]
  - FOM: [job-years/MW-year]
  - VOM: [job-years/MWh]
- Transmission lines:
  - Construction: [job-years/(2004$)]
