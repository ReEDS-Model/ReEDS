## Plant Characteristics Input Files

Most files in this folder give the cost and performance trajectory for one technology
family, and are selected by the matching `plantchar_{tech}` switch in `cases.csv`,
which is set to the full file name without the extension
(e.g. `plantchar_coal = coal_ATB_2024_moderate`).

The most common column schema is `i,t,capcost,fom,vom,heatrate`:

| Column | Meaning | Units |
| --- | --- | --- |
| `i` / `type` / `tech` | Technology | |
| `t` | Year | |
| `capcost` | Overnight capital cost | $/kW |
| `capcost_energy` | Overnight capital cost of the energy component (storage) | $/kWh |
| `fom` | Fixed O&M cost | $/kW-yr |
| `fom_energy` | Fixed O&M cost of the energy component (storage) | $/kWh-yr |
| `vom` | Variable O&M cost | $/MWh |
| `heatrate` | Heat rate | MMBtu/MWh |
| `rte` | Round-trip efficiency | fraction |
| `cf_improvement` | Capacity factor improvement multiplier (UPV) | fraction |

The wind and geothermal files instead carry their units in the column headers
(`Overnight Cap Cost $/kW`, `Fixed O&M $/(kW-yr)`, `Var O&M $/MWh`,
`Cap cost 1000$/MW`, `Fixed O&M 1000$/MW-yr`) and add a `CF_mult` capacity factor
multiplier; the offshore wind and geothermal-class files also add `rsc_mult`, a
supply-curve cost reduction multiplier.

Costs are in the dollar year listed for that scenario in `dollaryear.csv` and are
deflated to 2004$ during input processing. `advanced`, `moderate`, and `conservative`
refer to the Annual Technology Baseline (ATB) cost scenarios of the same names.

- `battery_ATB_2024_*.csv`: Battery cost and performance from the 2024 ATB, including separate power and energy cost components; selected by `plantchar_battery`
  - `battery_ATB_2024_advanced.csv`: Advanced scenario
  - `battery_ATB_2024_conservative.csv`: Conservative scenario
  - `battery_ATB_2024_moderate.csv`: Moderate scenario

- `beccs_BVRE_2021_*.csv`: BECCS cost and performance from the BVRE 2021 dataset; selected by `plantchar_beccs`
  - `beccs_BVRE_2021_high.csv`: High cost scenario
  - `beccs_BVRE_2021_low.csv`: Low cost scenario
  - `beccs_BVRE_2021_mid.csv`: Mid cost scenario

- `beccs_lowcost.csv`: BECCS cost and performance for a low-cost scenario

- `beccs_reference.csv`: BECCS cost and performance for the reference scenario

- `biopower_ATB_2024_moderate.csv`: Biopower cost and performance from the 2024 ATB, moderate scenario; selected by `plantchar_biopower`

- `ccsflex_ATB_2020_*.csv`: Flexible CCS cost and performance based on the 2020 ATB; selected by `ccsflexscen` and used only when one of the `GSw_CCSFLEX_*` switches is on
  - `ccsflex_ATB_2020_cost.csv`: Cost and heat rate trajectory for the flexible CCS technologies
  - `ccsflex_ATB_2020_perf.csv`: Performance characteristics of the flexible CCS technologies: storage efficiency (`stor_eff`), storage duration (`stor_dur`) [hours], CO<sub>2</sub> capture efficiency at 90% and 95% capture (`co2_eff_90`, `co2_eff_95`), and the power limit (`pow_lim`)

- `coal-ccs_ATB_2024_*.csv`: Coal CCS cost and performance from the 2024 ATB; selected by `plantchar_coal_ccs`
  - `coal-ccs_ATB_2024_advanced.csv`: Advanced scenario
  - `coal-ccs_ATB_2024_conservative.csv`: Conservative scenario
  - `coal-ccs_ATB_2024_moderate.csv`: Moderate scenario

- `coal_ATB_2024_moderate.csv`: Coal cost and performance from the 2024 ATB, moderate scenario; selected by `plantchar_coal`

- `cost_opres_*.csv`: Cost of providing operating reserves [$/MWh] by technology and reserve type (regulation, flexibility, spinning); used only when `GSw_OpRes` is on
  - `cost_opres_default.csv`: Default costs, which charge only for regulation reserves
  - `cost_opres_market.csv`: Market-based costs, which charge for all three reserve types

- `csp_ATB_2023_*.csv`: CSP cost and performance from the 2023 ATB by CSP configuration; selected by `plantchar_csp`
  - `csp_ATB_2023_advanced.csv`: Advanced scenario
  - `csp_ATB_2023_conservative.csv`: Conservative scenario
  - `csp_ATB_2023_moderate.csv`: Moderate scenario

- `csp_ATB_2024_*.csv`: CSP cost and performance from the 2024 ATB by CSP configuration; selected by `plantchar_csp`
  - `csp_ATB_2024_advanced.csv`: Advanced scenario
  - `csp_ATB_2024_conservative.csv`: Conservative scenario
  - `csp_ATB_2024_moderate.csv`: Moderate scenario

- `csp_SunShot2030.csv`: CSP costs from the SunShot2030 cost scenario

- `dollaryear.csv`: Dollar year mapping for each plant cost scenario

- `dr_shed_*_demo_data_January_2025.csv`: Shed demand response cost trajectories by technology, region, and year; selected by `dr_shedscen` and used only when `GSw_DRShed` is on
  - `dr_shed_capcost_scalars_demo_data_January_2025.csv`: Capital cost scalar [unitless] applied over time
  - `dr_shed_fom_demo_data_January_2025.csv`: Fixed O&M cost [$/kW-yr]
  - `dr_shed_vom_demo_data_January_2025.csv`: Variable O&M cost [$/MWh]

- `evmc_*_Baseline.csv`: Electric vehicle managed charging (EVMC) cost and performance by year; selected by `evmcscen`
  - `evmc_shape_Baseline.csv`: Load-shaping (shift) EVMC resources
  - `evmc_storage_Baseline.csv`: Storage-like (bidirectional) EVMC resources

- `fuelcell_ATB_2024_*.csv`: Fuel cell cost and performance from the 2024 ATB; selected by `plantchar_fuelcell`
  - `fuelcell_ATB_2024_advanced.csv`: Advanced scenario
  - `fuelcell_ATB_2024_moderate.csv`: Moderate scenario

- `gas-ccs_ATB_2024_*.csv`: Natural gas CCS cost and performance from the 2024 ATB; selected by `plantchar_gas_ccs`
  - `gas-ccs_ATB_2024_advanced.csv`: Advanced scenario
  - `gas-ccs_ATB_2024_conservative.csv`: Conservative scenario
  - `gas-ccs_ATB_2024_moderate.csv`: Moderate scenario

- `gas_ATB_2024_moderate.csv`: Natural gas cost and performance from the 2024 ATB, moderate scenario; selected by `plantchar_gas`

- `geo_ATB_2023_*.csv`: Geothermal cost and performance from the 2023 ATB by technology, resource class, and depth; selected by `plantchar_geo`
  - `geo_ATB_2023_advanced.csv`: Advanced scenario
  - `geo_ATB_2023_conservative.csv`: Conservative scenario
  - `geo_ATB_2023_moderate.csv`: Moderate scenario

- `geo_ATB_2024_*.csv`: Geothermal cost and performance from the 2024 ATB by technology, resource class, and depth; selected by `plantchar_geo`
  - `geo_ATB_2024_advanced.csv`: Advanced scenario
  - `geo_ATB_2024_conservative.csv`: Conservative scenario
  - `geo_ATB_2024_moderate.csv`: Moderate scenario

- `h2-combustion_ATB_202*.csv`: Hydrogen CT and CC plant cost and performance, generated in preprocessing from ATB moderate case data; selected by `plantchar_h2combustion` and used only when `GSw_H2Combustion` is on
  - `h2-combustion_ATB_2023.csv`: Generated from moderate case NREL ATB 2023 data
  - `h2-combustion_ATB_2024.csv`: Hydrogen CT and CC plant costs generated in preprocessing from moderate case NREL ATB 2024 data

- `h2fuelcell_*.csv`: Hydrogen fuel cell cost and performance; selected by `plantchar_h2fuelcell`
  - `h2fuelcell_advanced.csv`: Advanced scenario
  - `h2fuelcell_conservative.csv`: Conservative scenario
  - `h2fuelcell_moderate.csv`: Moderate scenario

- `heat_rate_adj.csv`: Heat rate adjustment multiplier [unitless] by technology

- `heat_rate_penalty_spin.csv`: Heat rate penalty [fraction] incurred for providing spinning reserves, by technology

- `hydro_ATB_2019_*.csv`: Hydropower cost from the 2019 ATB; selected by `plantchar_hydro`
  - `hydro_ATB_2019_constant.csv`: Hydro costs from the 2019 ATB constant cost scenario
  - `hydro_ATB_2019_low.csv`: Hydro costs from the 2019 ATB low cost scenario
  - `hydro_ATB_2019_mid.csv`: Hydro costs from the 2019 ATB mid cost scenario

- `maxage.csv`: Maximum age [years] allowed for each technology

- `maxdailycf.csv`: Maximum capacity factor [fraction] within each representative period, by technology
  - Enforced per technology and zone when `Sw_MaxDailyCF` is on: fleet generation may not exceed
    capacity x available hours x `maxdailycf`
  - The shed demand response supply curves it is set for assume one 4-hour event per day

- `minCF.csv`: Minimum annual capacity factor [fraction] for each technology fleet
  - Enforced per technology and zone when `Sw_MinCF` is on: fleet generation must be at least
    capacity x hours x `minCF`

- `min_retire_age.csv`: Minimum retirement age [years] for given technology

- `mingen_fixed.csv`: Fixed minimum generation level [fraction of capacity] applied across all hours, by technology; used only when `GSw_MingenFixed` is on

- `minloadfrac0.csv`: Initial minimum loading fraction [fraction] by technology

- `mttr.csv`: Mean time to repair [hours] by technology, used by the resource adequacy module to model outage duration

- `nuclear-smr_ATB_2024_*.csv`: Small modular reactor (SMR) cost and performance from the 2024 ATB; selected by `plantchar_nuclear_smr`
  - `nuclear-smr_ATB_2024_advanced.csv`: Advanced scenario
  - `nuclear-smr_ATB_2024_conservative.csv`: Conservative scenario
  - `nuclear-smr_ATB_2024_moderate.csv`: Moderate scenario

- `nuclear_ATB_2024_*.csv`: Large nuclear cost and performance from the 2024 ATB; selected by `plantchar_nuclear`
  - `nuclear_ATB_2024_advanced.csv`: Advanced scenario
  - `nuclear_ATB_2024_conservative.csv`: Conservative scenario
  - `nuclear_ATB_2024_moderate.csv`: Moderate scenario

- `ofs-wind_ATB_2023_*.csv`: Offshore wind cost and performance from the 2023 ATB by resource class and year; selected by `plantchar_ofswind` and used only when `GSw_OfsWind` is on
  - `ofs-wind_ATB_2023_advanced.csv`: 2023 advanced ofs-wind capital, fixed O&M, var O&M costs and rsc_mult (SC cost reduction mult) by class and year
  - `ofs-wind_ATB_2023_conservative.csv`: 2023 conservative ofs-wind capital, fixed O&M, var O&M costs and rsc_mult (SC cost reduction mult) by class and year
  - `ofs-wind_ATB_2023_moderate.csv`: 2023 moderate ofs-wind capital, fixed O&M, var O&M costs and rsc_mult (SC cost reduction mult) by class and year
  - `ofs-wind_ATB_2023_moderate_noFloating.csv`: 2023 moderate_noFloating ofs-wind capital (5x floating capital cost), fixed O&M, var O&M costs and rsc_mult (SC cost reduction mult) by class and year
  - Generated by [`wind/`](https://github.com/ReEDS-Model/ReEDS_Input_Processing/tree/main/wind) in the ReEDS_Input_Processing repo from ATB data and LBNL wind market reports

- `ofs-wind_ATB_2024_*.csv`: Offshore wind cost and performance from the 2024 ATB by resource class and year; selected by `plantchar_ofswind` and used only when `GSw_OfsWind` is on
  - `ofs-wind_ATB_2024_advanced.csv`: 2024 advanced ofs-wind capital, fixed O&M, var O&M costs and rsc_mult (SC cost reduction mult) by class and year
  - `ofs-wind_ATB_2024_conservative.csv`: 2024 conservative ofs-wind capital, fixed O&M, var O&M costs and rsc_mult (SC cost reduction mult) by class and year
  - `ofs-wind_ATB_2024_moderate.csv`: 2024 moderate ofs-wind capital, fixed O&M, var O&M costs and rsc_mult (SC cost reduction mult) by class and year
  - `ofs-wind_ATB_2024_moderate_noFloating.csv`: 2024 moderate_noFloating ofs-wind capital (5x floating capital cost), fixed O&M, var O&M costs and rsc_mult (SC cost reduction mult) by class and year
  - Generated by [`wind/`](https://github.com/ReEDS-Model/ReEDS_Input_Processing/tree/main/wind) in the ReEDS_Input_Processing repo from ATB data and LBNL wind market reports

- `ons-wind_ATB_2023_*.csv`: Land-based wind cost and performance from the 2023 ATB by resource class and year; selected by `plantchar_onswind`
  - `ons-wind_ATB_2023_advanced.csv`: Advanced cost and performance inputs from the 2023 Annual Technology Baseline for land-based wind
  - `ons-wind_ATB_2023_conservative.csv`: Conservative cost and performance inputs from the 2023 Annual Technology Baseline for land-based wind
  - `ons-wind_ATB_2023_moderate.csv`: Moderate cost and performance inputs from the 2023 Annual Technology Baseline for land-based wind
  - Generated by [`wind/`](https://github.com/ReEDS-Model/ReEDS_Input_Processing/tree/main/wind) in the ReEDS_Input_Processing repo from ATB data and LBNL wind market reports

- `ons-wind_ATB_2024_*.csv`: Land-based wind cost and performance from the 2024 ATB by resource class and year; selected by `plantchar_onswind`
  - `ons-wind_ATB_2024_advanced.csv`: Advanced cost and performance inputs from the 2024 Annual Technology Baseline for land-based wind
  - `ons-wind_ATB_2024_conservative.csv`: Conservative cost and performance inputs from the 2024 Annual Technology Baseline for land-based wind
  - `ons-wind_ATB_2024_moderate.csv`: Moderate cost and performance inputs from the 2024 Annual Technology Baseline for land-based wind
  - Generated by [`wind/`](https://github.com/ReEDS-Model/ReEDS_Input_Processing/tree/main/wind) in the ReEDS_Input_Processing repo from ATB data and LBNL wind market reports

- `other_plantchar.csv`: Cost and performance for the landfill gas (`lfill-gas`) and oil-gas-steam (`o-g-s`) technologies; selected by `plantchar_other`

- `outage_forced_*.csv`: Forced outage rates by technology
  - `outage_forced_static.csv`: Forced outage rates by technology
  - `outage_forced_temperature_murphy2019.csv`: Temperature-dependent forced outage rate [fraction] by prime mover and temperature [deg C], from [Murphy et al. 2019](https://doi.org/10.1016/j.apenergy.2019.113513); selected by `GSw_OutageScen`

- `outage_scheduled_*.csv`: Scheduled (planned maintenance) outage rates by technology
  - `outage_scheduled_monthly.csv`: Scheduled outage rate [fraction] by prime mover and month
  - `outage_scheduled_static.csv`: Scheduled outage rate by technology

- `pcm_defaults.json`: Default unit-level operating parameters by technology - average, minimum, and maximum unit capacity [MW], forced outage and maintenance rates, mean time to repair [hours], ramp limits, minimum up/down time, minimum stable level, and start cost [$/MW]

- `pvb_benchmark2020.csv`: Benchmark PV+battery system cost components used to derive hybrid PV+battery costs, with the units, dollar year, and source given per row

- `ramprate.csv`: Generator ramp rate [fraction/min] by technology

- `startcost.csv`: Linearized generator startup cost [2004$/MW] by technology
  - Most startup costs are taken from Lew et al 2013 - Western Wind and Solar Integration Study Phase 2 [(NREL/TP-5500-55588)](https://www.nlr.gov/docs/fy13osti/55588.pdf)
  - The original data, reported in $2011/MW in Table 7 are:
    - Coal: 124
    - Gas-CC: 81
    - Gas-CT: 67
    - Steam: 86
    - Nuclear: 155
  - RPM uses 466 $2011/MW for nuclear, but we don't have a citable source for that number
  - CCS startup costs are assumed to be the startup cost for the non-CCS version multiplied by the ratio of 2035 VOM costs between gas-cc-ccs and gas-cc in ATB 2023

- `unitsize_atb.csv`: Representative unit size [MW] by technology with the source given per row, used by the resource adequacy module when `pras_unitsize_source = atb`

- `upv_ATB_2023_*.csv`: Utility-scale PV cost and performance from the 2023 ATB; selected by `plantchar_upv`
  - `upv_ATB_2023_advanced.csv`: Advanced scenario
  - `upv_ATB_2023_conservative.csv`: Conservative scenario
  - `upv_ATB_2023_moderate.csv`: Moderate scenario

- `upv_ATB_2024_*.csv`: Utility-scale PV cost and performance from the 2024 ATB; selected by `plantchar_upv`
  - `upv_ATB_2024_advanced.csv`: Advanced scenario
  - `upv_ATB_2024_conservative.csv`: Conservative scenario
  - `upv_ATB_2024_moderate.csv`: Moderate scenario

- `years_until_endogenous.csv`: Number of years from the current year until each technology becomes available for endogenous (model-chosen) builds, used to build the tech-specific `firstyear` parameter