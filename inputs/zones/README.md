# Model zone definitions

Model zones are defined by the following user-generated files:

- `county2zone.csv`: Maps from counties (`FIPS` column) to ReEDS zones (`ba` column)
- `hierarchy.csv`: Maps from ReEDS zones (`r` column) to the larger region hierarchy levels
- `b2b.csv`: Back-to-back converter (B2B) capacity [MW] between model zones
- `newlinks_offshore_radial.csv`: Candiate connections between offshore and coastal land-based zones

And the following automatically generated files:

- `interfaces_r.csv`: Lists the pairs of zones that are connected by alternating current (AC) transmission lines
  - Specific to a nodal dataset (e.g., NARIS); changing the nodal dataset
  (which may entail adding lines or shifting the estimated substation locations)
  can change the set of connected interfaces, particularly for small or sparsely connected zones
- `interfaces_transgrp.csv`: The same as `interfaces_r.csv` but for the larger `transgrp` regions defined in `hierarchy.csv`
- `zonehash.csv`: The string identifier and node lat/lon for each model zone.
The lat/lon is used for plotting, representative least-cost paths and greenfield costs, and interzonal distances for losses and TW-mile calculations.
  - If the centroid is within the polygon defining a zone, the centroid is used as the node location.
  - If the centroid is NOT within the zone polygon, the node location is the "most interior" point in the polygon
  (determined by iteratively inward-buffering the polygon until it disappears, then keeping the centroid of the penultimate iteration).


## Notes on zone options

- `z3109`: 1:1 mapping from counties to zones
  - Not all counties have high-voltage load buses, so if `GSw_LoadAllocationMethod = state_lpf`, some counties may have zero load.


## Creating a new set of model zones

Start by copying the `county2zone.csv` and `hierarchy.csv` file for an existing set of zones to a new folder (named with a memorable name for your new set of zones) in the [ReEDS_Input_Processing/zones](https://github.com/ReEDS-Model/ReEDS_Input_Processing/tree/main/zones) directory.


### Deciding on the zones

The [ReEDS_Input_Processing/zones/make_maps.py](https://github.com/ReEDS-Model/ReEDS_Input_Processing/tree/main/zones/make_maps.py) script creates a collection of static and interactive maps based on the user-supplied `county2zone.csv` and `hierarchy.csv` files, intended to help decide on the new zone boundaries.
These maps show the new zones alongside existing grid features (transmission lines and planning area boundaries from various sources) and geographic features (mountain ranges).
Maps are also created to show the average load and sum of existing generation capacity by zone.
The resulting static maps are saved to a `.pptx` file, and an interactive/zoomable map is saved to a `.html` file.


### Generating the rest of the inputs

```{CEII}
The following steps require CEII access and are only available to NLR staff.
For questions, contact [Patrick Brown](patrick.brown@nlr.gov).
```

Once you're happy with your zone and hierarchy level definitions, run the following processing steps:

1. Run the [TSC/analysis/make_zone_shapefiles.py](https://github.nrel.gov/ReEDS/TSC/blob/pb/itldb/analysis/make_zone_shapefiles.py) script.
    - This script creates:
        - Zone shapefiles at the `r` and `transgrp` resolutions
        - Lists of interfaces at the `r` and `transgrp` resolutions that are connected by AC transmission lines
        - Maps of existing back-to-back (B2B) converters, to help decide which zonal interfaces to assign their capacity to.
        (Because some zone definitions put the interconnection seams quite far from their actual locations, this step is not automated and relies on user judgment.)
    - It also checks to make sure the user-specified `interconnect` for each zone matches the interconnection for the majority of network buses located within that zone.
1. Calculate the AC interface transfer limits (ITLs) by running [TSC/interfacemax.py](https://github.nrel.gov/ReEDS/TSC/blob/pb/itldb/interfacemax.py)
    - Include the `--dbpath={path/to/ITL folder}` argument and point it to the existing directory of ITLs to avoid recalculating ITLs for interfaces that already have data
1. Calculate the length and cost of new greenfield transmission lines between zones
    - Write the new interzonal endpoint pairs using [TSC/analysis/zone_links.py](https://github.nrel.gov/ReEDS/TSC/blob/main/analysis/zone_links.py)
        - Write pairs that require offshore routes (the links between land-based and offshore zones, new backbone links between offshore zones, and/or new exogenous offshore HVDC lines) into their own file, separate from routes that should be land-only
    - Send these files (with a note on which should allow offshore paths and which should not) to a member of the reV team who can calculate the interzonal least-cost paths using the [reVRt](https://github.com/NatLabRockies/reVRt) tool
1. Write the resulting files to the ReEDS repo by running [TSC/analysis/write_for_reeds.py](https://github.nrel.gov/ReEDS/TSC/blob/pb/itldb/analysis/write_for_reeds.py). This script:
    - Copies the `interface_r.csv` and `interface_transgrp.csv` files
    - Creates the `zonehash.csv` file
    - Rewrites the `itl_NARIS.csv`, `transmission_cost_distance.csv`, and `transmission_cost_distance_lines.csv` files
    (existing data in the file are preserved, so you should only see new rows added, typically at the bottom of the file)
1. If the new zone set requires special processing in ReEDS, add it to the appropriate sections of `inputs/zones/zoneset_config.yaml` (see below)
1. Add the new zone definition to the choices for the `GSw_ZoneSet` switch in `cases.csv`
1. To make sure it worked (or just to read the ITLs in general), you can run `import reeds` and then `reeds.inputs.get_itls(GSw_ZoneSet='your new zoneset name')` in Python with the `reeds2` conda environment activated.
1. Try a ReEDS run.
    - The following checks will be performed; if any of them fail, the run will stop.
        - `b2b.csv`, `county2zone.csv`, `hierarchy.csv`, `zonehash.csv`, `interfaces_r.csv`, and `interfaces_transgrp.csv` should all be preset in the `inputs/zones/{GSw_ZoneSet}` folder
        - All the interfaces specified by `interfaces_r.csv`, and `interfaces_transgrp.csv` should have data in `itl_NARIS.csv`
        - `hierarchy.csv` should have all the required columns (`st`, `interconnect`, `transreg`, `transgrp`, and `nercr`)

## Additional input files

- `county_state.csv`: Mapping from 5-digit county FIPS codes to county names and 2-letter state abbreviations.

- `hierarchy_offshore.csv`: Spatial hierarchy levels for offshore zones.
Only used when `GSw_OffshoreZones = 1`.
The offshore zones are not user-adjustable.

- `state_groups.csv`: Spatial hierarchy levels defined by groups of states.
  - `country`: Nation
  - `cendiv`: [Census divisions](https://www2.census.gov/geo/pdfs/maps-data/maps/reference/us_regdiv.pdf)
  - `usda_region`: [USDA Farm Production Regions](https://www.ers.usda.gov/data-products/arms-farm-financial-and-crop-production-practices/documentation)
  - `h2ptcreg`: Hydrogen tax credit regions ([DOE 2023, Figure 2](https://www.energy.gov/sites/default/files/2023-12/greet-manual_2023-12-20.pdf))
  - `gasreg`: Gas price regions. These are specific to the ReEDS model and are based on a mix of [census divisions](https://www2.census.gov/geo/pdfs/maps-data/maps/reference/us_regdiv.pdf), EIA-NEMS natural gas regions used to report regional flows and capacity ([EIA Natural Gas Market Module of the National Energy Modeling System: Model Documentation 2025, Figure 2.5](https://www.eia.gov/outlooks/aeo/nems/documentation/ngmm/pdf/NGMM_AEO2025.pdf)), and EIA-NEMS Natural Gas-Electricity Market Module regions ([EIA Natural Gas Market Module of the National Energy Modeling System: Model Documentation 2025, Figure 2.7](https://www.eia.gov/outlooks/aeo/nems/documentation/ngmm/pdf/NGMM_AEO2025.pdf))

- `zoneset_config.yaml`: Settings for zoneset-specific processing.
If `GSw_ZoneSet` is listed beneath one of the following switch names, the described behavior is applied during input processing at the beginning of each ReEDS run using that `GSw_ZoneSet`.
  - `drop_single_county_reinforcement_cost`: Drop the network reinforcement cost (a component of the interconnection cost) for new wind/solar capacity in single-county zones
  - `drop_interfaces_missing_cost`: If an AC transmission interface has existing capacity but no expansion cost or representative distance, remove its existing capacity and do not allow it to be expanded.
  (Turned off for most zone sets because we'd rather stop the run and add the missing data.
  Turned on for some zone sets with single-county zones that have no high-voltage transmission lines crossing the single-county zone boundaries.)
  - `reeds2pras_unitsize_unconstrain_counties`: Do not specify max unit sizes using the planning reserve margin (PRM) for single-county zones during ReEDS2PRAS unit disaggregation
