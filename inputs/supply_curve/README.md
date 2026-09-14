# Renewable Energy Supply Curves
## CSP (Concentrated Solar thermal Power)
The CSP resource classes are defined as follows:
* 1:        CF < 0.23
* 2: 0.23 ≤ CF < 0.26
* 3: 0.26 ≤ CF

Site-level CSP supply curve costs are copied from the site-level supply curve costs for utility-scale photovoltaics (UPV). The mapping code is available on the [ReEDS input-processing repo](https://github.com/ReEDS-Model/ReEDS_Input_Processing/tree/main/csp).

## PSH (Pumped-Storage Hydropower)
Each PSH supply curve filename is formatted as: `supplycurve_psh-{exclusion_scenario}{PSH_storage_duration}hr.csv`

The exclusion scenarios are defined by the inclusion of the following exclusion layers:
* `open`: census urbanized and global human settlement layer (GHSL) developed areas, existing waterbodies, permanent, or intermittent streams and 100yr flood plains, PAD-US prtected areas, conservation easements, areas of critical environmental concern, state and local protected areas, glaciers national land cover database (NLCD) permanent snow/ice and wetland ecosystmens, and airports/airstrips/helipads
* `reference`: all open exclusions [plus] ephemeral streams, critical habitat for endangered species, railway, pipelines, and major roads with 30m buffer, and National Wetlands Inventory (including small, localized riparian environments aroud rivers, streams, and lakes)
* `limited`: all reference exclusions [plus] agricultural easements, farm trust conservation land, and nationally important agricultural land, mature forests on federal lands, **all** building footprints, and Census and BIA-defined "tribal areas" (reservations and off-reservation trust land)