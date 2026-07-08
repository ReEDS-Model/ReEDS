# Power sector employment data
## Data input options
- `employment_factor_plant_jedi.csv`: Employment factor data for power plants of different technologies, taken from the JEDI/WIRED model.
Sources for employment data of individual technologies in JEDI/WIRED are shown in the table below.

| Technology              | Source                                                              |
|-------------------------|---------------------------------------------------------------------|
| Biopower                | JEDI Biopower Model (B12.23.16)[^1]                                             |
| Battery                 | WIRED {cite}`ramasamyUSSolarPhotovoltaic2022`                                   |
| Coal-IGCC               | WIRED {cite}`schmitt_et_al_2022`, {cite}`james_et_al_2023` and {cite}`EliminatingDerateCarbon`. |
| Coal-PC                 | WIRED {cite}`schmitt_et_al_2022`, {cite}`james_et_al_2023` and {cite}`EliminatingDerateCarbon`. |
| Coal-CCS RT             | WIRED {cite}`schmitt_et_al_2022`, {cite}`james_et_al_2023` and {cite}`EliminatingDerateCarbon`. |
| Coal-CCS GF             | WIRED {cite}`schmitt_et_al_2022`, {cite}`james_et_al_2023` and {cite}`EliminatingDerateCarbon`. |
| DPV                     | JEDI Photovoltaics Model (PV05.20.21)[^1]                                             |
| Geothermal-Hydrothermal | WIRED {cite}`hansonGeothermalElectricityTechnology2013`                                                   |
| Geothermal-EGS          | WIRED {cite}`hansonGeothermalElectricityTechnology2013`                                                   |
| Hydropower              | JEDI Conventional Hydro Model (CH12.23.16)[^1]                                              |
| Land-based Wind         | JEDI Onshore Wind Model (W2000)[^1]                                              |
| NG-CC                   | WIRED {cite}`schmitt_et_al_2022`, {cite}`oakesCostPerformanceBaseline2023` and {cite}`schmittCostPerformanceRetrofitting2023`   |
| NG-CC-CCS RT            | WIRED {cite}`schmitt_et_al_2022`, {cite}`oakesCostPerformanceBaseline2023` and {cite}`schmittCostPerformanceRetrofitting2023`   |
| NG-CC-CCS GF            | WIRED {cite}`schmitt_et_al_2022`, {cite}`oakesCostPerformanceBaseline2023` and {cite}`schmittCostPerformanceRetrofitting2023`   |
| NG-CT                   | WIRED {cite}`schmitt_et_al_2022`, {cite}`oakesCostPerformanceBaseline2023` and {cite}`schmittCostPerformanceRetrofitting2023`   |
| Nuclear Conventional    | {cite}`abou-jaoudeLiteratureReviewAdvanced2023`                                      |
| Nuclear SMR             | {cite}`asuegaTechnoeconomicAnalysisAdvanced2023`                                           |
| Offshore Wind           | {cite}`hammondWindfarmOperationsMaintenance2022` and {cite}`nunemakerORBITOffshoreRenewables2020` |
| Transmission-500kW AC   | WIRED Transmission Line Model (TL.12.23.16) based on JEDI Transmission Line Model[^1]                                              |
| Transmission-230kW AC   | WIRED Transmission Line Model (TL.12.23.16) based on JEDI Transmission Line Model[^1]                                              |
| UPV                     | JEDI Photovoltaics Model (PV05.20.21)[^1]                                              |

- `employment_factor_plant_mayfield.csv`, `employment_factor_plant_rutovitz.csv`, and `employment_factor_plant_ram.csv`: Employment factor data for power plants of different technologies, taken from literature -- Mayfield et al. (2023) {cite}`mayfieldLaborPathwaysAchieve2023`, Rutovitz et al. (2024) {cite}`rutovitzUpdatedEmploymentFactors2025` and Ram et al. (2020) {cite}`ramJobCreationGlobal2020`.

- `employment_factor_inter_transmission.csv`: Employment factor data for transmission line construction, taken from the four data source mentioned above (JEDI/WIRED models), Mayfield et al. (2023), Rutovitz et al. (2024) and Ram et al. (2020).

## Employment factor unit
- Power plants:
  - Construction: [job-years/MW]
  - FOM: [job-years/MW-year]
  - VOM: [job-years/MWh]
- Transmission lines:
  - Construction: [job-years/(2004$)]

[^1] NLR. Jobs and economic development impact models, 2025. https://www.nlr.gov/analysis/jedi/
