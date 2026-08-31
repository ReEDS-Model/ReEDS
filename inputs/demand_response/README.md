## Demand Response Input Files

- `dr_shed_avail_scalar.csv`: Peak availability [fraction of capacity] of shed demand response by year
  - The hourly shed-DR availability profile is normalized to its own maximum and then scaled by this value

- `dr_shed_capacity_scalar_demo_data_January_2025.csv`: Shed demand response capacity multiplier [unitless] over time by technology and region
  - The file is selected by the `dr_shedscen` switch and is only used when `GSw_DRShed` is on
