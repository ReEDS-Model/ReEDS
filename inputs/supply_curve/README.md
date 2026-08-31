## Renewable Energy Supply Curve Input Files

- CSP (concentrated solar thermal power): 
  - The CSP resource classes are defined as follows: 
    - 1: CF < 0.23
    - 2: 0.23 ≤ CF <0.26
    - 3: 0.26 ≤ CF
  - Site-level CSP supply curve costs are copied from the site-level supply curve costs for utility-scale photovoltaics (UPV). The mapping code is available on the [ReEDS input-processing repo](https://github.com/ReEDS-Model/ReEDS_Input_Processing/tree/main/csp).

- `bio_supplycurve.csv`: Biomass supply [million dry tons] and cost [$/dry ton] by USDA region and biomass supply curve class
	- Dollar year: 2015

- `dollaryear.csv`: U.S. dollar year for each cost-related input file in this folder

- `classification_geothermal.csv`: Geothermal resource class definitions, giving the reV mean resource temperature range [deg C] spanned by each class for each siting access case

- `dr_shed_cap_demo_data_January_2025.csv`: Available shed demand response capacity [MW] by technology and state
  - Selected by the `dr_shedscen` switch

- `dr_shed_cost_demo_data_January_2025.csv`: Cost [$/MW] of shed demand response supply by technology and state
  - Deflated to 2004$ during input processing using the `dr_shed` dollar year in `dollaryear.csv`
  - Selected by the `dr_shedscen` switch; deflated to 2004$ during input processing using the `dr_shed` dollar year in `dollaryear.csv`

- `hyd_add_upg_cap.csv`: Cumulative increase in available hydropower upgrade capacity [MW] relative to the base year, by region, technology, resource bin, and year

- `hydcap.csv`: Available hydropower supply curve capacity [MW] by technology, resource class, and region

- `hydcost.csv`: Hydropower supply curve capital cost [$/kW] by technology, resource class, and region
  - Converted to $/MW when loaded into `rsc_dat`; the dollar year is given in `dollaryear.csv`

- `interconnection_land.h5`: Land-based interconnection characteristics for each reV supply curve point (`sc_point_gid`): site and point-of-interconnection coordinates, FIPS code, transmission line GID and type, spur line and network reinforcement distances [km], and spur, POI, reinforcement, and total transmission costs [$/MW]
  - Written by `hourlize/write_site_parameters.py`; the dollar year is stored as an attribute on the h5 file

- `interconnection_offshore.h5`: Offshore interconnection characteristics for each reV supply curve point, in the same format as `interconnection_land.h5`
  - Written by `hourlize/write_site_parameters.py`

- `PSH_supply_curves_capacity_*.csv`: Pumped storage hydropower supply curve capacity as used in 2025 Annual Technology Baseline. Citation: [https://www.nlr.gov/gis/psh-supply-curves](https://www.nlr.gov/gis/psh-supply-curves)
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

- `PSH_supply_curves_cost_*.csv`: Pumped storage hydropower supply curve cost as used in 2025 Annual Technology Baseline. Citation: [https://www.nlr.gov/gis/psh-supply-curves](https://www.nlr.gov/gis/psh-supply-curves)
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

- `rev_paths.csv`: Paths to the reV supply curve and generation runs backing each technology, giving the siting access switch and case, supply curve and capacity factor paths, and the original reV case and supply curve file names

- `supplycurve_egs-reference.csv`: Enhanced geothermal (EGS) supply curve by reV supply curve point: resource class, available capacity [MW], capital cost adder [$/MW], capacity factor, and mean resource temperature [deg C]

- `supplycurve_upv-*.csv`: UPV supply curve from reV. Capacity numbers are in MW_DC and cost numbers are in $/MW_AC. Citation: [https://docs.nlr.gov/docs/fy25osti/91900.pdf](https://docs.nlr.gov/docs/fy25osti/91900.pdf)
  - `supplycurve_upv-limited.csv`: limited siting scenario
  - `supplycurve_upv-open.csv`: open siting scenario
  - `supplycurve_upv-reference.csv`: reference siting scenario

- `supplycurve_wind-ofs-*.csv`: Offshore wind supply curve from reV. Citation: [https://docs.nlr.gov/docs/fy25osti/91900.pdf](https://docs.nlr.gov/docs/fy25osti/91900.pdf)
  - `supplycurve_wind-ofs-limited.csv`: limited siting scenario
  - `supplycurve_wind-ofs-open.csv`: open siting scenario 
  - `supplycurve_wind-ofs-reference.csv`: reference siting scenario

- `supplycurve_wind-ons-*.csv`: Land-based wind supply curve. Citation: [https://docs.nlr.gov/docs/fy25osti/91900.pdf](https://docs.nlr.gov/docs/fy25osti/91900.pdf)
  - `supplycurve_wind-ons-limited.csv`: limited siting scenario
  - `supplycurve_wind-ons-open.csv`: open siting scenario
  - `supplycurve_wind-ons-reference.csv`: reference siting scenario

- `trans_intra_cost_adder.csv`: Intra-zone transmission cost adder [2004$/kW] by technology
