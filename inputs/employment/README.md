# Power sector employment data
## Data input options
- `employment_factor_plant_jedi.csv`: Employment factor data for power plants of different technologies, taken from the JEDI/WIRED model.
Sources for employment data of individual technologies in JEDI/WIRED are shown in the table below.

| Technology              | Source                                                              |
|-------------------------|---------------------------------------------------------------------|
| Biopower                | [JEDI Biofuels Model (B12.23.16)](nlr.gov/analysis/jedi/biofuels)                                             |
| Battery                 | WIRED Battery Storage Model (BESS.2025.09.30) based on [Ramasamy et al. (2022)](https://research-hub.nlr.gov/en/publications/us-solar-photovoltaic-system-and-energy-storage-cost-benchmarks-w/).                                  |
| Coal-IGCC               | WIRED Coal Model (COAL.2025.09.30) based on NETL's studies - [Schmitt et al. (2022)](https://www.osti.gov/servlets/purl/1893822/), [Turner et al. (2023)](https://www.osti.gov/servlets/purl/1968040/), and [Buchheit et al. (2023)](https://www.osti.gov/biblio/1968037)  . |
| Coal-PC                 | WIRED Coal Model (COAL.2025.09.30) based on NETL's studies - [Schmitt et al. (2022)](https://www.osti.gov/servlets/purl/1893822/), [Turner et al. (2023)](https://www.osti.gov/servlets/purl/1968040/), and [Buchheit et al. (2023)](https://www.osti.gov/biblio/1968037)  . |
| Coal-CCS RT             | WIRED Coal Model (COAL.2025.09.30) based on NETL's studies - [Schmitt et al. (2022)](https://www.osti.gov/servlets/purl/1893822/), [Turner et al. (2023)](https://www.osti.gov/servlets/purl/1968040/), and [Buchheit et al. (2023)](https://www.osti.gov/biblio/1968037)  .  |
| Coal-CCS GF             | WIRED Coal Model (COAL.2025.09.30) based on NETL's studies - [Schmitt et al. (2022)](https://www.osti.gov/servlets/purl/1893822/), [Turner et al. (2023)](https://www.osti.gov/servlets/purl/1968040/), and [Buchheit et al. (2023)](https://www.osti.gov/biblio/1968037)  . |
| DPV                     | [JEDI Photovoltaics Model (PV05.20.21)](https://www.nlr.gov/analysis/jedi/pv)                                             |
| Geothermal-Hydrothermal | WIRED {cite}`hansonGeothermalElectricityTechnology2013`                                                   |
| Geothermal-EGS          | WIRED {cite}`hansonGeothermalElectricityTechnology2013`                                                   |
| Hydropower              | [JEDI Conventional Hydro Model (CH12.23.16)](https://www.nlr.gov/analysis/jedi/conventional-hydro)                                             |
| Land-based Wind         | [JEDI Onshore Wind Model (W2000)](https://www.nlr.gov/analysis/jedi/wind)                                             |
| NG-CC                   | WIRED {cite}`schmitt_et_al_2022`, {cite}`oakesCostPerformanceBaseline2023` and {cite}`schmittCostPerformanceRetrofitting2023`   |
| NG-CC-CCS RT            | WIRED {cite}`schmitt_et_al_2022`, {cite}`oakesCostPerformanceBaseline2023` and {cite}`schmittCostPerformanceRetrofitting2023`   |
| NG-CC-CCS GF            | WIRED {cite}`schmitt_et_al_2022`, {cite}`oakesCostPerformanceBaseline2023` and {cite}`schmittCostPerformanceRetrofitting2023`   |
| NG-CT                   | WIRED {cite}`schmitt_et_al_2022`, {cite}`oakesCostPerformanceBaseline2023` and {cite}`schmittCostPerformanceRetrofitting2023`   |
| Nuclear Conventional    | {cite}`abou-jaoudeLiteratureReviewAdvanced2023`                                      |
| Nuclear SMR             | {cite}`asuegaTechnoeconomicAnalysisAdvanced2023`                                           |
| Offshore Wind           | {cite}`hammondWindfarmOperationsMaintenance2022` and {cite}`nunemakerORBITOffshoreRenewables2020` |
| Transmission-500kW AC   | WIRED Transmission Line Model (TL.12.23.16) based on JEDI Transmission Line Model[^1]                                              |
| Transmission-230kW AC   | WIRED Transmission Line Model (TL.12.23.16) based on JEDI Transmission Line Model[^1]                                              |
| UPV                     | [JEDI Photovoltaics Model (PV05.20.21)](https://www.nlr.gov/analysis/jedi/pv)                                             |

- `employment_factor_plant_mayfield.csv`, `employment_factor_plant_rutovitz.csv`, and `employment_factor_plant_ram.csv`: Employment factor data for power plants of different technologies, taken from literature -- Mayfield et al. (2023) {cite}`mayfieldLaborPathwaysAchieve2023`, Rutovitz et al. (2024) {cite}`rutovitzUpdatedEmploymentFactors2025` and Ram et al. (2020) {cite}`ramJobCreationGlobal2020`.

- `employment_factor_inter_transmission.csv`: Employment factor data for transmission line construction, taken from the four data source mentioned above (JEDI/WIRED models), Mayfield et al. (2023), Rutovitz et al. (2024) and Ram et al. (2020).

## Employment factor unit
- Power plants:
  - Construction: [job-years/MW]
  - FOM: [job-years/MW-year]
  - VOM: [job-years/MWh]
- Transmission lines:
  - Construction: [job-years/(2004$)]

