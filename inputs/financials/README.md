## Financials Input Files

- `cap_penalty.csv`: Penalty for capacity deployed above the interconnection queue limit (`queue_limit`), by technology group [$/MW in `cap_penalty_dollaryear` dollars (scalars.csv), currently 2024$]. Converted to 2004$/MW using `deflator.csv` and multiplied by the `queue_penalty_multiplier` scalar (scalars.csv) in `copy_files.py`.
  - The default of $300,000/MW ($300/kW, 2024$) is a provisional modeling proxy for sensitivity testing, informed by the average interconnection costs reported by Seel et al. (2026), *Generator Interconnection Costs to the Transmission System in non-ISO Balancing Authorities*, LBNL ([link](https://eta-publications.lbl.gov/publications/generator-interconnection-costs-0)): about $194/kW for completed, $294/kW for active, and $671/kW for withdrawn projects. These are observed interconnection costs, not measurements of the cost of exceeding a queue limit.
  - The penalty is charged on increases in the running maximum of capacity above the limit across consecutive constrained modeled years. If the excess falls, the previously penalized amount is retained; only excess beyond that amount incurs another penalty.

- `construction_schedules_default.csv`: 

- `construction_times_default.csv`: 

- `currency_incentives.csv`: 

- `deflator.csv`: Dollar year deflator to convert values to 2004$

- `depreciation_schedules_default.csv`: 

- `energy_communities.csv`: 

- `financials_hydrogen.csv`: 

- `financials_sys_ATB2023.csv`: 

- `financials_sys_ATB2024.csv`: 

- `financials_tech_ATB2023_CRP20.csv`: 

- `financials_tech_ATB2023.csv`: 

- `financials_tech_ATB2024.csv`: 

- `financials_transmission_30ITC_0pen_2022_2031.csv`: 

- `financials_transmission_default.csv`: 

- `incentives_*.csv`:
  - `incentives_annual.csv`: 
  - `incentives_biennial.csv`: 
  - `incentives_ira_45q_45v_extension.csv`: 
  - `incentives_ira.csv`: 
  - `incentives_noira.csv`: 
  - `incentives_none.csv`: 
  - `incentives_obbba_conservative.csv`: 
  - `incentives_obbba.csv`: 

- `inflation_default.csv`: Annual inflation factors from 1914 through 2200
  - historical values use the avg-avg values from [https://www.usinflationcalculator.com/inflation/consumer-price-index-and-annual-percent-changes-from-1913-to-2008/](https://www.usinflationcalculator.com/inflation/consumer-price-index-and-annual-percent-changes-from-1913-to-2008/)

- `nuclear_energy_communities.csv`: Counties belonging to metropolitan statistical areas (MSAs) for which at least 0.17% of direct employment has been related to nuclear power at any point since 2010
  - These are determined partly by following the process described in Section 2.6 of [https://home.treasury.gov/system/files/8861/EnergyCommunities_Data_Documentation.pdf](https://home.treasury.gov/system/files/8861/EnergyCommunities_Data_Documentation.pdf) and substituting in the NAICS code for nuclear electric power generation (221113) and partly by determining counties that belong to MSAs where the number of people employed by national labs engaged in nuclear research and development (PNNL, INL, ORNL, SNL, LLNL, Argonne, and LANL) has been at least 0.17 percent of the MSA's total employment at any point since 2010

- `reg_cap_cost_diff_default.csv`: Region-specific differences for capital cost of all resources
  - Add 1 to produce a multiplier

- `retire_penalty.csv`: 

- `supply_chain_adjust.csv`: 

- `tc_phaseout_schedule_ira2022.csv`: 

