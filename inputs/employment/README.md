# Power sector employment data
## Data input options
- `employment_factor_plant_jedi.csv`: Employment factor data for power plants of different technologies, taken from the JEDI/WIRED model.
Sources for employment data of individual technologies in JEDI/WIRED are shown in the table below.

| Technology              | Source                                                              |
|-------------------------|---------------------------------------------------------------------|
| Biopower                | JEDI {cite}`JEDI_2025`                                              |
| Battery                 | WIRED {cite}`Ramasamy_et_al_2022`                                   |
| Coal-IGCC               | WIRED {cite}`NETL_2022`, {cite}`NETL_2023a` and {cite}`NETL_2023c`. |
| Coal-PC                 | WIRED {cite}`NETL_2022`, {cite}`NETL_2023a` and {cite}`NETL_2023c`. |
| Coal-CCS RT             | WIRED {cite}`NETL_2022`, {cite}`NETL_2023a` and {cite}`NETL_2023c`. |
| Coal-CCS GF             | WIRED {cite}`NETL_2022`, {cite}`NETL_2023a` and {cite}`NETL_2023c`. |
| DPV                     | JEDI {cite}`JEDI_2025`                                              |
| Geothermal-Hydrothermal | WIRED {cite}`SAM`                                                   |
| Geothermal-EGS          | WIRED {cite}`SAM`                                                   |
| Hydropower              | JEDI {cite}`JEDI_2025`                                              |
| Land-based Wind         | JEDI {cite}`JEDI_2025`                                              |
| NG-CC                   | WIRED {cite}`NETL_2022`, {cite}`NETL_2023b` and {cite}`NETL_2025`   |
| NG-CC-CCS RT            | WIRED {cite}`NETL_2022`, {cite}`NETL_2023b` and {cite}`NETL_2025`   |
| NG-CC-CCS GF            | WIRED {cite}`NETL_2022`, {cite}`NETL_2023b` and {cite}`NETL_2025`   |
| NG-CT                   | WIRED {cite}`NETL_2022`, {cite}`NETL_2023b` and {cite}`NETL_2025`   |
| Nuclear Conventional    | {cite}`Abou_Jaoude_et_al_2023`                                      |
| Nuclear SMR             | {cite}`Asuega_et_al_2023`                                           |
| Offshore Wind           | {cite}`Hammond_and_Cooperman_2022` and {cite}`Nunemaker_et_al_2020` |
| Transmission-500kW AC   | JEDI {cite}`JEDI_2025`                                              |
| Transmission-230kW AC   | JEDI {cite}`JEDI_2025`                                              |                                            |
| UPV                     | JEDI {cite}`JEDI_2025` 

- `employment_factor_plant_mayfield.csv`, `employment_factor_plant_rutovitz.csv`, and `employment_factor_plant_ram.csv`: Employment factor data for power plants of different technologies, taken from literature -- Mayfield et al. (2023), Rutovitz et al. (2024) and Ram et al. (2020).

- `employment_factor_inter_transmission.csv`: Employment factor data for transmission line construction, taken from the four data source mentioned above (JEDI/WIRED models), Mayfield et al. (2023), Rutovitz et al. (2024) and Ram et al. (2020).

## Employment factor unit
- Power plants:
  - Construction: [job-years/MW]
  - FOM: [job-years/MW-year]
  - VOM: [job-years/MWh]
- Transmission lines:
  - Construction: [job-years/(2004$)]
