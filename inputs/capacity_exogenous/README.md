## Capacity Exogenous Input Files

- `cappayments.csv`: 

- `cappayments_ba.csv`: 

- `demonstration_plants.csv`: Nuclear-smr demonstration plants [MW]
  - Active when `GSw_NuclearDemo = 1`
  - For more information, refer to the **notes** section of [https://www.energy.gov/oced/advanced-reactor-demonstration-projects-0](https://www.energy.gov/oced/advanced-reactor-demonstration-projects-0)

- `exog_cap_geohydro_allkm_reference.csv`: 

- `exog_cap_geohydro_reference.csv`: 

- `exog_cap_upv_*.csv`:
  - `exog_cap_upv_limited.csv`: 
  - `exog_cap_upv_open.csv`: 
  - `exog_cap_upv_reference.csv`: 

- `exog_cap_wind-ons_*.csv`:
  - `exog_cap_wind-ons_limited.csv`: 
  - `exog_cap_wind-ons_open.csv`: 
  - `exog_cap_wind-ons_reference.csv`: 

- `interconnection_queues.csv`: Active interconnection queue capacity [MW] by ReEDS county (`r`), technology group (`tg`), and interconnection agreement (IA) status (`ia_executed`), from the LBNL queue data (currently requests through 2025). Produced by `interconnection_queues/process_interconnection_queues.py` in the ReEDS_Input_Processing repository.
  - `ia_executed = 1`: active requests with an executed IA ("IA Executed" capacity); `ia_executed = 0`: active requests without a confirmed executed IA, including missing IA status. "All Active" capacity is the sum of both rows.
  - A `capacity_mw` of 0 means no active queue capacity in that category (not missing data); counties absent from the file had no active requests.
  - The annual capacity deployment limit (`queue_limit(tg,r,allt)`) is built in `copy_files.py` (see `reeds.inputs.get_queue_limit`): IA Executed capacity 2 years after the queue data year (2027 for the 2025 data), All Active capacity 5 years after (2030), linear interpolation in between, and All Active capacity afterward, for the `GSw_QueueConstraintYears` (default 3) calendar years starting from the first anchor year.

- `prescribed_builds_wind-ofs_meshed_*.csv`:
  - `prescribed_builds_wind-ofs_meshed_limited.csv`: 
  - `prescribed_builds_wind-ofs_meshed_open.csv`: 
  - `prescribed_builds_wind-ofs_meshed_reference.csv`: 

- `prescribed_builds_wind-ofs_radial_*.csv`:
  - `prescribed_builds_wind-ofs_radial_limited.csv`: 
  - `prescribed_builds_wind-ofs_radial_open.csv`: 
  - `prescribed_builds_wind-ofs_radial_reference.csv`: 

- `prescribed_builds_wind-ons_*.csv`:
  - `prescribed_builds_wind-ons_limited.csv`: 
  - `prescribed_builds_wind-ons_open.csv`:  
  - `prescribed_builds_wind-ons_reference.csv`: 

- `ReEDS_generator_database_final_EIA-NEMS.csv`: ReEDS generator database derived from the EIA NEMS plant file and EIA 860M. See https://github.com/ReEDS-Model/ReEDS_Input_Processing/tree/main/nems_database_processing.
