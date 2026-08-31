## Financials Input Files

- `cap_penalty.csv`: Cost penalty [$/MW] for deploying capacity above the interconnection cap limit, by technology group

- `construction_schedules_default.csv`: Fraction of total construction expenditure incurred in each year of construction, by schedule name
  - Columns are the schedule identifiers referenced by the `construction_sch` column of the `financials_tech_*` and `financials_transmission_*` files; selected by the `construction_schedules_suffix` switch

- `construction_times_default.csv`: Construction time [years] by technology and online year
  - Selected by the `construction_times_suffix` switch

- `currency_incentives.csv`: Dollar year of the `ptc_value` column in each incentives file

- `deflator.csv`: Dollar year deflator to convert values to 2004$

- `depreciation_schedules_default.csv`: Fraction of capital depreciated in each year, by depreciation schedule
  - Column names are the schedule identifiers (e.g. `5`, `7`, `15`, `20`) referenced by the `depreciation_sch` column of the financials files; selected by the `depreciation_schedules_suffix` switch

- `energy_communities.csv`: Counties that qualify as energy communities for the purposes of the tax credit bonus
  - See `nuclear_energy_communities.csv` for the separate nuclear-specific list

- `financials_hydrogen.csv`: Financial assumptions for hydrogen production capacity: construction start year, depreciation schedule, construction time and schedule, real financing differential, ITC fraction, tax equity penalty, and annual degradation

- `financials_sys_ATB2023.csv`: System-wide financial assumptions by year from the 2023 ATB: nominal interest rate, nominal return on equity, debt fraction, and tax rate
  - Selected with `financials_sys_suffix = ATB2023`

- `financials_sys_ATB2024.csv`: System-wide financial assumptions by year from the 2024 ATB: nominal interest rate, nominal return on equity, debt fraction, and tax rate
  - Selected with `financials_sys_suffix = ATB2024`

- `financials_tech_ATB2023_CRP20.csv`: Same as `financials_tech_ATB2023.csv` but with a 20-year capital recovery period
  - Selected with `financials_tech_suffix = ATB2023_CRP20`

- `financials_tech_ATB2023.csv`: Technology-specific financial assumptions by technology and year from the 2023 ATB: depreciation schedule, evaluation period [years], construction schedule, and real financing differential
  - Selected with `financials_tech_suffix = ATB2023`

- `financials_tech_ATB2024.csv`: Technology-specific financial assumptions by technology and year from the 2024 ATB: depreciation schedule, evaluation period [years], construction schedule, and real financing differential
  - Selected with `financials_tech_suffix = ATB2024`

- `financials_transmission_30ITC_0pen_2022_2031.csv`: Transmission financial assumptions with a 30% ITC and no tax equity penalty applied over 2022-2031

- `financials_transmission_default.csv`: Default financial assumptions for transmission capacity by construction start year: depreciation schedule, construction time and schedule, real financing differential, ITC fraction, and tax equity penalty
  - Selected by the `financials_trans_suffix` switch

- `incentives_*.csv`: Federal tax incentive definitions by technology and construction start year, selected by the `incentives_suffix` switch
  - Columns cover the production tax credit (`ptc_value`, `ptc_perc_bonus`, `ptc_dur`, `ptc_tax_equity_penalty`), the investment tax credit (`itc_frac`, `itc_energy_comm_bonus`, `itc_percpt_domestic_bonus`, `itc_tax_equity_penalty`), the 45Q carbon capture credit (`co2_capture_value`, `co2_capture_dur`), and the 45V hydrogen credit (`h2_ptc_value`, `h2_ptc_dur`), together with the eligibility window (`safe_harbor`, `t_max_online`)
  - `ptc_value` is in the dollar year given by `currency_incentives.csv`
  - `incentives_annual.csv`: Pre-IRA incentives with credit values given for each individual year
  - `incentives_biennial.csv`: Pre-IRA incentives with credit values set to two-year averages of the `incentives_annual.csv` values during credit step-down periods, for runs that solve every two years
  - `incentives_ira_45q_45v_extension.csv`: Inflation Reduction Act incentives with the 45Q (carbon capture) and 45V (clean hydrogen) credits extended
  - `incentives_ira.csv`: Incentives as defined by the Inflation Reduction Act of 2022
  - `incentives_noira.csv`: Incentives as they stood before the Inflation Reduction Act
  - `incentives_none.csv`: No incentives
  - `incentives_obbba_conservative.csv`: A more conservative interpretation of the One Big Beautiful Bill Act (OBBBA) incentives
  - `incentives_obbba.csv`: Incentives as defined by the One Big Beautiful Bill Act (OBBBA) of 2025

- `inflation_default.csv`: Annual inflation factors from 1914 through 2200
  - historical values use the avg-avg values from [https://www.usinflationcalculator.com/inflation/consumer-price-index-and-annual-percent-changes-from-1913-to-2008/](https://www.usinflationcalculator.com/inflation/consumer-price-index-and-annual-percent-changes-from-1913-to-2008/)

- `nuclear_energy_communities.csv`: Counties belonging to metropolitan statistical areas (MSAs) for which at least 0.17% of direct employment has been related to nuclear power at any point since 2010
  - These are determined partly by following the process described in Section 2.6 of [https://home.treasury.gov/system/files/8861/EnergyCommunities_Data_Documentation.pdf](https://home.treasury.gov/system/files/8861/EnergyCommunities_Data_Documentation.pdf) and substituting in the NAICS code for nuclear electric power generation (221113) and partly by determining counties that belong to MSAs where the number of people employed by national labs engaged in nuclear research and development (PNNL, INL, ORNL, SNL, LLNL, Argonne, and LANL) has been at least 0.17 percent of the MSA's total employment at any point since 2010
  - Generated by [`financials/`](https://github.com/ReEDS-Model/ReEDS_Input_Processing/tree/main/financials) in the ReEDS_Input_Processing repo (`calculate_nuclear_energy_communities.py`)

- `reg_cap_cost_diff_default.csv`: Region-specific capital cost difference [fraction] for each technology group
  - Applied as `1 + reg_cap_cost_diff`, so 0 means no regional adjustment
  - Add 1 to produce a multiplier
  - Generated by [`capital_cost_multipliers/`](https://github.com/ReEDS-Model/ReEDS_Input_Processing/tree/main/capital_cost_multipliers) in the ReEDS_Input_Processing repo

- `retire_penalty.csv`: Penalty for retiring a power plant, expressed as a fraction of FOM, by year

- `tc_phaseout_schedule_ira2022.csv`: Tax credit phaseout multiplier by the number of years after the phaseout trigger is met, following the Inflation Reduction Act of 2022
  - Selected by the `GSw_TCPhaseout_schedule` switch; the phaseout starts the year after the emissions threshold is met

