# Power sector employment data
## Data input options
- `employment_factor_plant_jedi.csv`: Employment factor data for power plants of different technologies, taken from the JEDI/WIRED model.
Sources for employment data of individual technologies in JEDI/WIRED are shown in the table below.

| Technology              | Source                                                              |
|-------------------------|---------------------------------------------------------------------|
| Biopower                | [JEDI Biofuels Model (B12.23.16)](https://www.nlr.gov/analysis/jedi/biofuels)                                             |
| Battery                 | WIRED Battery Storage Model (BESS.2025.09.30) based on [Ramasamy et al. (2022)](https://docs.nlr.gov/docs/fy22osti/83586.pdf).                                  |
| Coal-IGCC               | WIRED Coal Model (COAL.2025.09.30) based on NETL's studies - [Schmitt et al. (2022)](https://www.osti.gov/servlets/purl/1893822/), [Turner et al. (2023)](https://www.osti.gov/servlets/purl/1968040/), and [Buchheit et al. (2023)](https://www.osti.gov/biblio/1968037)  . |
| Coal-PC                 | WIRED Coal Model (COAL.2025.09.30) based on NETL's studies - [Schmitt et al. (2022)](https://www.osti.gov/servlets/purl/1893822/), [Turner et al. (2023)](https://www.osti.gov/servlets/purl/1968040/), and [Buchheit et al. (2023)](https://www.osti.gov/biblio/1968037)  . |
| Coal-CCS RT             | WIRED Coal Model (COAL.2025.09.30) based on NETL's studies - [Schmitt et al. (2022)](https://www.osti.gov/servlets/purl/1893822/), [Turner et al. (2023)](https://www.osti.gov/servlets/purl/1968040/), and [Buchheit et al. (2023)](https://www.osti.gov/biblio/1968037)  .  |
| Coal-CCS GF             | WIRED Coal Model (COAL.2025.09.30) based on NETL's studies - [Schmitt et al. (2022)](https://www.osti.gov/servlets/purl/1893822/), [Turner et al. (2023)](https://www.osti.gov/servlets/purl/1968040/), and [Buchheit et al. (2023)](https://www.osti.gov/biblio/1968037)  . |
| DPV                     | [JEDI Photovoltaics Model (PV05.20.21)](https://www.nlr.gov/analysis/jedi/pv)                                             |
| Geothermal-Hydrothermal | WIRED Geothermal Model (CPG.2025.09.30) based on [NLR's SAM-GETEM](https://sam.nlr.gov/geothermal.html)                                                  |
| Geothermal-EGS          | WIRED Geothermal Model (CPG.2025.09.30) based on [NLR's SAM-GETEM](https://sam.nlr.gov/geothermal.html)                                                     |
| Hydropower              | [JEDI Conventional Hydro Model (CH12.23.16)](https://www.nlr.gov/analysis/jedi/conventional-hydro)                                             |
| Land-based Wind         | [JEDI Onshore Wind Model (W2000)](https://www.nlr.gov/analysis/jedi/wind)                                             |
| NG-CC                   | WIRED Natural Gas Model (NG.2025.09.30) based on NETL's studies - [Schmitt et al. (2022)](https://www.osti.gov/servlets/purl/1893822/), [Oakes et al. (2023)](https://www.osti.gov/biblio/1973266), and [Schmitt and Homsy (2023)](https://www.netl.doe.gov/projects/files/CostandPerformanceofRetrofittingNGCCUnitsforCarbonCaptureRevision3_031723.pdf)   |
| NG-CC-CCS RT            | WIRED Natural Gas Model (NG.2025.09.30) based on NETL's studies - [Schmitt et al. (2022)](https://www.osti.gov/servlets/purl/1893822/), [Oakes et al. (2023)](https://www.osti.gov/biblio/1973266), and [Schmitt and Homsy (2023)](https://www.netl.doe.gov/projects/files/CostandPerformanceofRetrofittingNGCCUnitsforCarbonCaptureRevision3_031723.pdf)|
| NG-CC-CCS GF            | WIRED Natural Gas Model (NG.2025.09.30) based on NETL's studies - [Schmitt et al. (2022)](https://www.osti.gov/servlets/purl/1893822/), [Oakes et al. (2023)](https://www.osti.gov/biblio/1973266), and [Schmitt and Homsy (2023)](https://www.netl.doe.gov/projects/files/CostandPerformanceofRetrofittingNGCCUnitsforCarbonCaptureRevision3_031723.pdf)|
| NG-CT                   | WIRED Natural Gas Model (NG.2025.09.30) based on NETL's studies - [Schmitt et al. (2022)](https://www.osti.gov/servlets/purl/1893822/), [Oakes et al. (2023)](https://www.osti.gov/biblio/1973266), and [Schmitt and Homsy (2023)](https://www.netl.doe.gov/projects/files/CostandPerformanceofRetrofittingNGCCUnitsforCarbonCaptureRevision3_031723.pdf)|
| Nuclear Conventional    | [Abou-Jaoude et al. (2023)](https://gain.inl.gov/content/uploads/4/2024/11/INL-RPT-23-72972-Literature-Review-of-Adv-Reactor-Cost-Estimates.pdf)                                      |
| Nuclear SMR             | [Asuega et al. (2023)](https://www.sciencedirect.com/science/article/pii/S0306261923000338)                                           |
| Offshore Wind           | [Hammond and Cooperman (2022)](https://www.osti.gov/servlets/purl/1894867/) and [Nunemaker et al. (2020)](https://www.osti.gov/servlets/purl/1660132/) |
| Transmission-500kW AC   | WIRED Transmission Line Model (TL.12.23.16) based on [JEDI Transmission Line Model](https://www.nlr.gov/analysis/jedi/transmission-line)                                              |
| Transmission-230kW AC   | WIRED Transmission Line Model (TL.12.23.16) based on [JEDI Transmission Line Model](https://www.nlr.gov/analysis/jedi/transmission-line)                                               |
| UPV                     | [JEDI Photovoltaics Model (PV05.20.21)](https://www.nlr.gov/analysis/jedi/pv)                                             |

- `employment_factor_plant_mayfield.csv`, `employment_factor_plant_rutovitz.csv`, and `employment_factor_plant_ram.csv`: Employment factor data for power plants of different technologies, taken from literature -- [Mayfield et al. (2023)](https://doi.org/10.1016/j.enpol.2023.113516), [Rutovitz et al. (2024)](https://doi.org/10.1016/j.rser.2025.115339), and [Ram et al. (2020)](https://doi.org/10.1016/j.techfore.2019.06.008), respectively.

- `employment_factor_inter_transmission.csv`: Employment factor data for transmission line construction, taken from the four data source mentioned above - [JEDI/WIRED models](https://www.nlr.gov/analysis/jedi/transmission-line), [Mayfield et al. (2023)](https://doi.org/10.1016/j.enpol.2023.113516), [Rutovitz et al. (2024)](https://doi.org/10.1016/j.rser.2025.115339) and [Ram et al. (2020)](https://doi.org/10.1016/j.techfore.2019.06.008).

## Employment factor units
- Power plants:
  - Construction: [job-years/MW]
  - FOM: [job-years/MW-year]
  - VOM: [job-years/MWh]
- Transmission lines:
  - Construction: [job-years/(2004$)]

