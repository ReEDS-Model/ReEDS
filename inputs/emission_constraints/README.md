## Emission Constraints Input Files
### CO<sub>2</sub> and CO<sub>2</sub>e Caps
CO<sub>2</sub> and CO<sub>2</sub>e emissions caps are defined in `co2_cap.csv`, which includes a range of different emission cap trajectories until 2050. CO<sub>2</sub> tax for varying scenarios are defined in `co2_tax.csv`.

### Emission Rates
Upstream and process emission rates by technology and pollutant used in ReEDS are defined in `emitrate.csv`. These emission rates are taken from Table A-9 in Appendix A.5 of NLR's Standard Scenarios 2024 ([https://www.nlr.gov/docs/fy25osti/92256.pdf](https://www.nlr.gov/docs/fy25osti/92256.pdf)), which details the multiple sources that these emission rates are obtained from such as U.S. Life Cycle Inventory Database, EPA's Emissions & Generation Resource Integrated Database, California Air Resources Board, etc.

Note that CH<sub>4</sub> upstream emission rate for natural gas is zero in `emitrate.csv` as we use CH<sub>4</sub> methane leakage defined using the `GSw_MethaneLeakageScen` switch to calculate it.

### Global Warming Potentials
A range of values for global warming potentials (GWP) of CH<sub>4</sub> and N<sub>2</sub>O are taken from the most recent IPCC assessment reports (AR4 to AR6). Summary of the ranges of GWPs for these pollutants can be found in Table 7.15, page 1017 of the IPCC AR6 report ([https://www.ipcc.ch/report/ar6/wg1/downloads/report/IPCC_AR6_WGI_FullReport.pdf](https://www.ipcc.ch/report/ar6/wg1/downloads/report/IPCC_AR6_WGI_FullReport.pdf)).

### Natural Gas Capital Recovery Factor (CRF) Penalties
`ng_crf_penalty.csv` contains a cost adjustment for NG techs in scenarios with national decarbonization targets. For more information on how these were calculated, refer to [PR #1220](https://github.nrel.gov/ReEDS/ReEDS-2.0/pull/1220).

### The Regional Greenhouse Gas Initiative (RGGI)
- `rggi_states.csv`: List of participating RGGI states
  - Citation: [https://www.rggi.org/program-overview-and-design/elements](https://www.rggi.org/program-overview-and-design/elements)

- `rggicon.csv`: CO<sub>2</sub> cap [metric tons] for RGGI states
  - Citation: [https://www.rggi.org/allowance-tracking/allowance-distribution](https://www.rggi.org/allowance-tracking/allowance-distribution)

### Other files
- `ccs_link.csv`: Link from each CCS technology to its uncontrolled (non-CCS) counterpart

- `ccs_link_water.csv`: Same as `ccs_link.csv` for the expanded cooling/water technologies

- `co2_tax.csv`: CO<sub>2</sub> tax [2004$/metric ton] by year, with one column per tax scenario
  - Applied to CO<sub>2</sub> emissions in all regions when `GSw_CarbTax` is on; the scenario column is selected by `GSw_CarbTaxOption`
  - Scenario columns are named `t{level}_{year}`, ramping to $`{level}`/metric ton by `{year}` and holding flat thereafter; the `default` column escalates over the full horizon instead
  - Enters the objective function as a cost on process (and, with `Sw_Upstream`, upstream) emissions

- `county_co2_share_egrid_2022.csv`: Share [fraction] of national 2022 CO<sub>2</sub> emissions attributable to each county, calculated from 2022 eGRID data
  - Summed over the counties in `GSw_Region` to scale national emission caps down to the modeled region

- `csapr_group1_ex.csv`: CSAPR states that cannot trade allowances with those in group 2

- `csapr_group2_ex.csv`: CSAPR states that cannot trade allowances with those in group 1

- `csapr_ozone_season.csv`: CSAPR ozone-season NO<sub>x</sub> budget and assurance levels by state and year
  - Active when `GSw_CSAPR` is on

- `gwp.csv`: Global warming potentials by pollutant for each IPCC report and time horizon (`AR4-100`, `AR6-20`, etc.)
  - The column used is selected by the `GSw_GWP` switch; see the Global Warming Potentials section above

- `h2_leakage_rate.csv`: Hydrogen leakage rate [fraction] from upstream and process emissions by hydrogen production technology
  - Columns are named `{study}/{Low,Med,High}`; the column used is selected by the `GSw_H2LeakageScen` switch

- `methane_leakage_rate.csv`: Fractional leakage of methane from upstream natural gas production by year, for a range of named scenarios
  - The column used is selected by the `GSw_MethaneLeakageScen` switch, which also accepts a fixed float rate

- `state_cap.csv`: State-level CO<sub>2</sub> cap [metric tons CO<sub>2</sub>] by state and year
  - Active when `GSw_StateCap` is on
