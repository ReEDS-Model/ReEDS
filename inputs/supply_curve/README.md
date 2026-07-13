## Renewable Energy Supply Curve Files

- CSP (concentrated solar thermal power): 
  - The CSP resource classes are defined as follows: 
    - 1: CF < 0.23
    - 2: 0.23 ≤ CF <0.26
    - 3: 0.26 ≤ CF
  - Site-level CSP supply curve costs are copied from the site-level supply curve costs for utility-scale photovoltaics (UPV). The mapping code is available on the [ReEDS input-processing repo](https://github.com/ReEDS-Model/ReEDS_Input_Processing/tree/main/csp).

- `bio_supplycurve.csv`: Regional biomass supply and costs by resource class
	- Dollar year: 2015

- `dollaryear.csv`:

- `dr_shed_cap_demo_data_January_2025.csv`:

- `dr_shed_cost_demo_data_January_2025.csv`:

- `hyd_add_upg_cap.csv`:

- `hydcap.csv`:

- `hydcost.csv`:

- `interconnection_land.h5`:

- `interconnection_offshore.h5`:

- `PSH_supply_curves_capacity_*.csv`: Pumped storage hydropower supply curve capacity as used in 2025 Annual Technology Baseline. Citation: https://www.nlr.gov/gis/psh-supply-curves
  - `PSH_supply_curves_capacity_10hr_ref_apr2025.csv`: supply curve capacity assuming 10 hour duration and reference exclusions
  - `PSH_supply_curves_capacity_10hr_wEph_apr2025.csv`: supply curve capacity assuming 10 hour duration and allowing sites on ephemeral streams 
  - `PSH_supply_curves_capacity_10hr_wExist_apr2025.csv`: supply curve capacity assuming 10 hour duration and allowing sites using existing reservoirs 
  - `PSH_supply_curves_capacity_10hr_wExist_wEph_apr2025.csv`: supply curve capacity assuming 10 hour duration and allowing sites using existing reservoirs and on ephemeral streams 
  - `PSH_supply_curves_capacity_12hr_ref_apr2025.csv`: supply curve capacity assuming 12 hour duration and reference exclusions
  - `PSH_supply_curves_capacity_12hr_wEph_apr2025.csv`: supply curve capacity assuming 12 hour duration and allowing sites on ephemeral streams
  - `PSH_supply_curves_capacity_12hr_wExist_apr2025.csv`: supply curve capacity assuming 12 hour duration and allowing sites using existing reservoirs 
  - `PSH_supply_curves_capacity_12hr_wExist_wEph_apr2025.csv`: supply curve capacity assuming 12 hour duration and allowing sites using existing reservoirs and on ephemeral streams
  - `PSH_supply_curves_capacity_8hr_ref_apr2025.csv`: supply curve capacity assuming 8 hour duration and reference exclusions
  - `PSH_supply_curves_capacity_8hr_wEph_apr2025.csv`: supply curve capacity assuming 8 hour duration and allowing sites on ephemeral streams
  - `PSH_supply_curves_capacity_8hr_wExist_apr2025.csv`: supply curve capacity assuming 8 hour duration and allowing sites using existing reservoirs
  - `PSH_supply_curves_capacity_8hr_wExist_wEph_apr2025.csv`: supply curve capacity assuming 8 hour duration and allowing sites using existing reservoirs and on ephemeral streams

- `PSH_supply_curves_cost_*.csv`: Pumped storage hydropower supply curve cost as used in 2025 Annual Technology Baseline. Citation: https://www.nlr.gov/gis/psh-supply-curves
  - `PSH_supply_curves_cost_10hr_ref_apr2025.csv`: assuming 10 hour duration and reference exclusions 
  - `PSH_supply_curves_cost_10hr_wEph_apr2025.csv`: assuming 10 hour duration and allowing sites on ephemeral streams
  - `PSH_supply_curves_cost_10hr_wExist_apr2025.csv`: assuming 10 hour duration and allowing sites using existing reservoirs
  - `PSH_supply_curves_cost_10hr_wExist_wEph_apr2025.csv`: assuming 10 hour duration and allowing sites using existing reservoirs and on ephemeral streams 
  - `PSH_supply_curves_cost_12hr_ref_apr2025.csv`: assuming 12 hour duration and reference exclusions 
  - `PSH_supply_curves_cost_12hr_wEph_apr2025.csv`: assuming 12 hour duration and allowing sites on ephemeral streams
  - `PSH_supply_curves_cost_12hr_wExist_apr2025.csv`: assuming 12 hour duration and allowing sites using existing reservoirs
  - `PSH_supply_curves_cost_12hr_wExist_wEph_apr2025.csv`: assuming 12 hour duration and allowing sites using existing reservoirs and on ephemeral streams 
  - `PSH_supply_curves_cost_8hr_ref_apr2025.csv`: assuming 8 hour duration and reference exclusions 
  - `PSH_supply_curves_cost_8hr_wEph_apr2025.csv`: assuming 8 hour duration and allowing sites on ephemeral streams
  - `PSH_supply_curves_cost_8hr_wExist_apr2025.csv`: assuming 8 hour duration and allowing sites using existing reservoirs  	
  - `PSH_supply_curves_cost_8hr_wExist_wEph_apr2025.csv`: assuming 8 hour duration and allowing sites using existing reservoirs and on ephemeral streams 

- `rev_paths.csv`:

- `sc_point_gid_old2new.csv`:

- `sitemap.h5`:

- `supplycurve_egs-reference.csv`:

- `supplycurve_upv-*.csv:`: UPV supply curve from reV. Capacity numbers are in MW_DC and cost numbers are in $/MW_AC. Citation: https://docs.nlr.gov/docs/fy25osti/91900.pdf
  - `supplycurve_upv-limited.csv`: limited siting scenario
  - `supplycurve_upv-open.csv`: open siting scenario
  - `supplycurve_upv-reference.csv`: reference siting scenario

- `supplycurve_wind-ofs-*.csv`: Offshore wind supply curve from reV. Citation: https://docs.nlr.gov/docs/fy25osti/91900.pdf
  - `supplycurve_wind-ofs-limited.csv`: limited siting scenario
  - `supplycurve_wind-ofs-open.csv`: open siting scenario 
  - `supplycurve_wind-ofs-reference.csv`: reference siting scenario

- `supplycurve_wind-ons-*.csv`: Land-based wind supply curve. Citation: https://docs.nlr.gov/docs/fy25osti/91900.pdf
  - `supplycurve_wind-ons-limited.csv`: limited siting scenario
  - `supplycurve_wind-ons-open.csv`: open siting scenario
  - `supplycurve_wind-ons-reference.csv`: reference siting scenario

- `trans_intra_cost_adder.csv`:
