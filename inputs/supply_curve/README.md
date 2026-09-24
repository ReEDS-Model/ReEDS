## Renewable Energy Supply Curve Input Files

- CSP (concentrated solar thermal power): 
  - The CSP resource classes are defined as follows: 
    - 1: CF < 0.23
    - 2: 0.23 ≤ CF <0.26
    - 3: 0.26 ≤ CF
  - Site-level CSP supply curve costs are copied from the site-level supply curve costs for utility-scale photovoltaics (UPV). The mapping code is available on the [ReEDS input-processing repo](https://github.com/ReEDS-Model/ReEDS_Input_Processing/tree/main/csp).

- Each PSH supply curve filename is formatted as: `supplycurve_psh-{exclusion_scenario}{PSH_storage_duration}hr.csv`
- The exclusion scenarios are defined by the inclusion of the following exclusion layers:
  - `open`: census urbanized and global human settlement layer (GHSL) developed areas, existing waterbodies, permanent, or intermittent streams and 100yr flood plains, PAD-US prtected areas, conservation easements, areas of critical environmental concern, state and local protected areas, glaciers national land cover database (NLCD) permanent snow/ice and wetland ecosystmens, and airports/airstrips/helipads
  - `reference`: all open exclusions [plus] ephemeral streams, critical habitat for endangered species, railway, pipelines, and major roads with 30m buffer, and National Wetlands Inventory (including small, localized riparian environments aroud rivers, streams, and lakes)
  - `limited`: all reference exclusions [plus] agricultural easements, farm trust conservation land, and nationally important agricultural land, mature forests on federal lands, **all** building footprints, and Census and BIA-defined "tribal areas" (reservations and off-reservation trust land)

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

- `rev_paths.csv`:

- `sc_point_gid_old2new.csv`:

- `sitemap.h5`:

- `supplycurve_egs-reference.csv`:

- `supplycurve_psh-*.csv`: Pumped storage hydropower supply curve. Citation: [https://www.nlr.gov/gis/psh-supply-curves](https://www.nlr.gov/gis/psh-supply-curves)
  - `supplycurve_psh-limited8hr.csv`: assuming 8 hour duration for the limited siting scenario
  - `supplycurve_psh-open8hr.csv`: assuming 8 hour duration for the open siting scenario
  - `supplycurve_psh-reference8hr.csv`: assuming 8 hour duration for the reference siting scenario
  - `supplycurve_psh-limited10hr.csv`: assuming 10 hour duration for the limited siting scenario
  - `supplycurve_psh-open10hr.csv`: assuming 10 hour duration for the open siting scenario
  - `supplycurve_psh-reference10hr.csv`: assuming 10 hour duration for the reference siting scenario
  - `supplycurve_psh-limited12hr.csv`: assuming 12 hour duration for the limited siting scenario
  - `supplycurve_psh-open12hr.csv`: assuming 12 hour duration for the open siting scenario
  - `supplycurve_psh-reference12hr.csv`: assuming 12 hour duration for the reference siting scenario

- `supplycurve_upv-*.csv:`: UPV supply curve from reV. Capacity numbers are in MW_DC and cost numbers are in $/MW_AC. Citation: [https://docs.nlr.gov/docs/fy25osti/91900.pdf](https://docs.nlr.gov/docs/fy25osti/91900.pdf)
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

- `trans_intra_cost_adder.csv`:
