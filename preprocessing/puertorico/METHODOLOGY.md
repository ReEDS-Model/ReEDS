# Puerto Rico 115 kV+ Nodal ReEDS Case: Methodology and Reproduction Guide

## 1. Objective, Scope, and Current Status

This directory prepares and registers the Puerto Rico power system as a high-voltage-bus-based ReEDS case. A candidate ReEDS region is defined by each connected bus with a nominal voltage **greater than or equal to 115 kV**. Lower-voltage buses, existing assets, load, and PR100 renewable resources are subsequently assigned to these regions.

The resulting dataset contains **121 regions**. The `PR_explicit` spatial adapter is implemented in this ReEDS checkout: it bypasses CONUS county aggregation, accepts the already-regional Puerto Rico inputs, and registers the corresponding hierarchy, unit database, supply curves, profiles, load, and fixed transmission interfaces. `cases_pr.csv` contains an earlier `PR_115plus_input` smoke case and the calibrated `PR100_1LM_mirror` comparison case; the latter is the active 2050 study configuration.

As of August 2026, the smoke case has passed the complete Python input pipeline, HDF5-to-GDX conversion, GAMS model creation, and first-year GAMS formulation. Its 2010 formulation generated an LP with 50,719 rows, 59,061 columns, and 208,317 nonzeros. The 2050 mirror case has been tested separately as documented in Section 11. An optimization result has not yet been obtained on the current machine because its GAMS license has neither a full CPLEX entitlement nor a HiGHS entitlement. This is an execution-environment limitation, not evidence that the model is infeasible. Section 14 distinguishes exact public PR100 inputs from documented proxies.

The approach follows the general nodal ReEDS workflow described by Akash Karmakar and Wesley Cole: transmission-network nodes define the spatial regions; load, existing assets, and renewable resources are assigned to those nodes; and interregional transmission limits are derived from the network model. The sections below document the specific implementation for the available Puerto Rico datasets and the additional compatibility inputs needed by ReEDS.

## 2. Code and Source Data

Code directory:

```text
/projects/aiplusinvest/ychen10/ReEDS/preprocessing/puertorico
```

Primary source data:

```text
/projects/aiplusinvest/base_case/node_locations_corrected.csv
/projects/aiplusinvest/base_case/municipality_bus_mapping.csv
/projects/aiplusinvest/base_case/*.json
/projects/aiplusinvest/pr100_all
/projects/aiplusinvest/pr100_rev
/projects/aiplusinvest/pr100_rev_profiles
/projects/aiplusinvest/pr100_rev_scripts
/projects/aiplusinvest/pr100_all/data/LoadDataHourly.zip
/projects/aiplusinvest/pr100_all/data/DERInvestments.zip
/projects/aiplusinvest/pr100_all/data/IntegratedCapacityInvestment.zip
```

- `node_locations_corrected.csv` provides bus coordinates.
- `municipality_bus_mapping.csv` provides the municipality-to-bus mapping. Its bus lists are interpreted as positional indices into the source-system arrays; they are not always identical to PSS/E bus numbers.
- The Sienna JSON files in `base_case` provide buses, lines, transformers, generators, storage, loads, and load time series.
- `pr100_rev` and `pr100_rev_profiles` provide the PR100 utility PV, onshore wind, and offshore wind supply curves and 2018–2019 capacity-factor profiles.
- `LoadDataHourly.zip` is the official PR100 municipal hourly-load archive downloaded from OEDI.
- `DERInvestments.zip` is the official PR100 municipal distributed-PV and storage trajectory archive downloaded from OEDI.
- `IntegratedCapacityInvestment.zip` is the official PR100 Engage capacity-output archive. `AnnualCapacities/energy_cap_1LM.csv` supplies the original technology/year benchmark and the aggregate capacity/retirement prescriptions used by the mirror case.
- `puerto_rico_tranche1_pv_bess.csv` and `proyectos_exhibit_2.gpkg` provide committed-project attributes and available project geometries.

The declared bus counts for Hormigueros and San Germán in `municipality_bus_mapping.csv` do not match the actual list lengths. The preprocessing uses the complete parsable lists and records the discrepancy in QA instead of truncating them to the declared counts.

## 3. Construction of the 121 Network Regions

Implementation: `prepare_pr_nodal.py`

### 3.1 Selection of 115 kV+ Seeds

1. Read each bus and its nominal voltage from the system JSON.
2. Select buses with `base_kv >= 115` as candidate region seeds.
3. Retain only seeds connected to another bus through the active line/transformer network.
4. Remove the isolated high-voltage bus `MORVIS-SOLAR-97074` (bus 97074), because it does not form a usable network connection.
5. Assign a stable, unique region ID to each remaining seed.

The source system has 1,411 buses, of which 1,393 have coordinates. A total of 122 buses satisfy the `>=115 kV` criterion. After removing the isolated high-voltage bus, **121 regions** remain.

### 3.2 Assignment of Lower-Voltage Buses

All active lines and transformers form a weighted undirected graph. The weight of each device is the magnitude of its series impedance:

```text
w = sqrt(r^2 + x^2)
```

A multi-source shortest-path calculation is performed using all 115 kV+ seeds as simultaneous sources. Each lower-voltage bus is assigned to the seed with the minimum total impedance distance. Exact ties are resolved using a stable region/bus ordering so that repeated runs produce identical results.

This method partitions the network according to electrical proximity, not geographic distance or municipality boundaries. A disconnected lower-voltage network that cannot reach any high-voltage seed is not forcibly assigned.

Result: 1,390 buses are assigned to 121 regions.

- `regions.csv` contains the region seeds, coordinates, and aggregate statistics.
- `bus_to_region.csv` contains each bus, its coordinates and voltage, municipality, assigned region, and impedance distance.

### 3.3 Aggregation of Lines and Transformers

The terminal buses of each active line or transformer are converted to regions using `bus_to_region.csv`:

- If both terminals belong to the same region, the device is internal and does not create a ReEDS interface.
- If the terminals belong to different regions, the device is aggregated into an undirected region pair.
- Out-of-service equipment is excluded from the active topology and transfer-capacity calculation.

The resulting topology has **184 region-to-region interfaces**. All 121 regions belong to a single connected component.

## 4. Existing-Asset Mapping

Generators, storage devices, and loads are first located at their source JSON buses and then mapped through `bus_to_region.csv`. The output preserves the source asset name, source type, capacity, status, and original bus for traceability. A total of **1,783 active assets** are included in the staging dataset.

This asset-level crosswalk remains the source-network staging layer used by the smoke case. The `PR100_1LM_mirror` case does not use its provisional capacities or retirement dates directly. Instead, `prepare_pr100_mirror.py` sets aggregate technology capacities and retirement steps equal to the public 1LM Engage output and allocates each aggregate across regions in proportion to the corresponding source-network units. Technology proxies and remaining source limitations are listed in Section 14.

For the source-network staging layer, the following items remain candidates rather than final plant records:

- Fuel and technology assignments for thermal generators.
- The boundary between hydro, distributed generation, and utility-scale generation.
- Battery power capacity, duration, and committed status.
- Announced retirements and committed new projects.

## 5. PR100 Renewable Resources

Implementation: `prepare_pr_supply_curves.py`

The selected PR100 combination is **Moderate / Limited / 2035**:

- Utility PV: `upv_fixed_moderate_limited_35`
- Onshore wind: `wind_onshore_limited_35`
- Offshore wind: `wind_offshore_35`

### 5.1 Site-to-Region Assignment

Utility-PV and onshore-wind sites use the PR100 connection tables. Each source site is linked to its PR100 point of interconnection (POI), the POI substation is matched to its source-system bus, and that bus is electrically rolled up through `bus_to_region.csv`. This preserves the PR100 connection choice rather than substituting a geographically nearest bus.

The PR100 offshore curve has no equivalent connection table. It is therefore assigned to the nearest retained 115 kV+ seed with the haversine great-circle distance. The source curve already applies the exclusions in the PR100 `wind_offshore_35` aggregation configuration, including protected/restricted areas, marine protected areas, cable buffers, ocean-disposal sites, unexploded-ordnance areas, and the USVI three-nautical-mile buffer. The preprocessing then adds two explicit screens: source country must be `United States`, and the nearest retained Puerto Rico seed must be no more than **75 km** away.

These are reproducible PR100 study-siting assumptions, not a formal legal Puerto Rico offshore boundary. The output records the aggregation-config path, the additional screen, excluded site IDs, and exclusion reasons.

The retained source resources are:

- UPV: 442 sites and 14.220 GW
- Onshore wind: 102 sites and 1.608 GW
- Offshore wind: 123 sites and 36.077 GW

The native ReEDS UPV curve contains 36 additional profile-clone rows for regions with committed or distributed solar capacity but no native retained UPV site. Each clone uses the capacity-factor profile and resource class of the geographically nearest retained PR100 UPV site while retaining its required region and capacity. The clone mapping is written to `upv_exogenous_profile_clones.csv`. The final registered curves contain:

- UPV: 478 rows, 14.739 GW, and 95 regions
- Onshore wind: 102 rows, 1.608 GW, and 48 regions
- Offshore wind: 123 rows, 36.077 GW, and 36 regions

### 5.2 Resource Classes and Costs

Sites are ordered by capacity factor and divided into deterministic equal-capacity classes: five classes for UPV, ten for onshore wind, and five for offshore wind. This is a transparent staging proxy; a production calibration may instead rerun the standard ReEDS resource-class clustering.

The supply-curve tables retain source CAPEX, fixed O&M, fixed charge rate, site LCOE, total LCOE, and connection/spur cost. The cost basis is confirmed as **real 2021 USD**:

- UPV was based on the 2022 ATB in 2020 dollars and multiplied by `1.001004` in the PR100 setup script to convert to 2021 dollars.
- Onshore and offshore wind costs were multiplied by `1.143251327963817` in the PR100 workflow to convert from 2015 to 2021 dollars.

The smoke case uses the selected standard ReEDS technology-cost trajectory and retains the PR100 site-specific connection/spur component in the supply curve. The mirror case instead selects `upv_PR100_1LM`, `ons-wind_PR100_1LM`, `ofs-wind_PR100_1LM`, and `battery_PR100_1LM`. Those files provide annual real-2021 costs through 2050; the public PR100 reV/ATB annual shapes are normalized to the published PR100 first-availability values. The spatial supply-curve geometry remains the 2035 Moderate/Limited set because this ReEDS version accepts one resource geometry for a run. This is not an exact implementation of year-varying site availability; Section 14 records the approximation.

## 6. Renewable Capacity-Factor Profiles

Implementation: `convert_pr_profiles.py`

1. Select the corresponding PR100 profile columns using the source site IDs retained in the supply-curve outputs.
2. Align those profiles with the final region and resource IDs.
3. Retain weather years 2018 and 2019.
4. The source UPV profiles are at 30-minute resolution. Each pair of consecutive time steps is arithmetically averaged to produce hourly values.
5. The wind profiles are already hourly and are not downsampled again.
6. Write the profiles to HDF5 and preserve the column manifest and conversion QA.

Output files:

```text
outputs/pr100_moderate_limited_2035/profiles_cf/
  cf_upv_pr100-moderate-limited-35.h5
  cf_wind-ons_pr100-limited-35.h5
  cf_wind-ofs_pr100-35.h5
```

## 7. PR100 1LM Load Construction

Implementation: `prepare_pr100_load.py`

The former Sienna-load-plus-1%-growth placeholder has been replaced. The current `load.h5` comes from the official PR100 OEDI `LoadDataHourly.zip` archive, using the full-study **1LM** selection: Economic DER Adoption, Less Land, and Mid-Case load.

Each of the 78 municipal files reports 8,760 observations per fiscal year (July through June). For each selected fiscal year, rows are sorted by month, day, and hour into January-through-December order while preserving every source value and the annual energy total. The fiscal-year label is used as the ReEDS solve year. This introduces a weekday-sequence break at the June/July join, which is recorded in `load_qa.json`.

Municipal load is allocated to the 121 electrical regions using each region's share of active `StandardLoad` nameplate capacity inside that municipality. A mapped-bus-count share is used only if a municipality has no active load component. These weights are fixed across years and are written to `municipality_region_load_weights.csv`.

The solve years are:

```text
2022, 2025, 2028, 2030, 2035, 2040, 2045, 2050
```

Each solve-year forecast is duplicated for the 2018 and 2019 renewable-weather blocks because the PR100 load archive is a forecast, not weather-matched historical load. The final matrix has shape 140,160 × 121:

```text
8 solve years × 2 weather years × 8,760 hours × 121 regions
```

## 8. Distributed Resources and Tranche 1 Commitments

Implementation: `prepare_pr100_der_committed.py`

### 8.1 Distributed PV and Storage

The script reads `der_capacity_municipality_mw_1LM.csv` directly from the official `DERInvestments.zip` archive. It sums agents within each municipality and retains three source quantities: distributed PV MW, storage MW, and storage MWh. PR100 reports even years from 2020 through 2050; missing solve years such as 2025 and 2035 are linearly interpolated between adjacent source years.

Municipal totals are allocated using the same fixed load-based weights as the hourly load. The outputs cover every combination of 121 regions and eight solve years. The 2050 system totals are 2,473.945 MW of distributed PV, 1,146.250 MW of storage power, and 4,585.001 MWh of storage energy.

### 8.2 Tranche 1 Solar

The committed-project table contains 18 executed-PPOA solar projects totaling **844.8 MW**. Fourteen projects are assigned using the centroid of their matching Exhibit 2 geometry and the nearest retained region. The four projects without matching geometry—two in Naguabo and two in Yabucoa—use the highest base-load-share region in the named municipality.

The project table does not report battery power or energy, so the generic staging file does not infer paired storage. In the mirror case, the public final Engage result is used instead: 740 MW of four-hour storage is prescribed in 2025 and another 750 MW in 2028, while the published ten-hour resource-adequacy additions are prescribed at their reported years. The spatial shares follow the 18 project locations. This reproduces the public aggregate trajectory but is not a reconstruction of the unavailable project-by-project battery workbook. A candidate online year of 2025 is used for the 18 solar projects. Project `AQ-1-P` is explicitly marked low confidence because the Tranche 1 table says Cabo Rojo while the matching Exhibit 2 record is labeled `CS/UR Juncos`.

## 9. Interregional Transfer Limits (ITLs)

Implementation: `calculate_pr_itl.py`

### 9.1 DC Network Model

All active lines and transformers are used to construct the full-bus DC susceptance matrix. For each cross-region interface, a unit transaction is applied between the two regions, and DC voltage angles and equipment-flow sensitivities are solved.

The locally calculated sensitivities were cross-checked against the provided PTDF data. Across 1,267 matched samples, the mean absolute error is approximately 0.000199 and the maximum absolute error is approximately 0.01028.

### 9.2 Smoke-Case N-0 Pairwise TTC

For a unit transaction between a region pair, let the flow factor on device `l` be `PTDF_l`, and let its continuous rating be `rating_l`. The maximum transaction permitted by that device is:

```text
TTC_l = rating_l / abs(PTDF_l)
```

The interface TTC is the minimum of these limits across all applicable equipment constraints. The current calculation assumes:

- N-0 topology.
- Continuous equipment ratings.
- Zero base flow.
- Symmetric forward and reverse capacity.
- No transmission expansion within ReEDS.

Twelve interfaces without usable ratings, or represented as project interfaces, receive a provisional 5,000 MW screening cap so that an unknown capacity is not incorrectly interpreted as zero. These interfaces must be reviewed before a production run. Across the 184 interfaces, the median ITL is approximately 275.79 MW and the minimum is approximately 67.66 MW.

These values are retained for the `PR_115plus_input` smoke case. They are not final security-constrained transfer capabilities. A production case should provide or establish the following where possible:

- Base-case branch flows.
- A contingency list.
- Emergency ratings.
- An N-1 derating method.
- Final treatment of transformer phase shifts and tap ratios.
- Region-to-region transmission losses.

### 9.3 PR100 Mirror Transmission Treatment

The PR100 report describes Engage interface capacity as the sum of continuous ratings for the lines and transformers crossing each regional boundary. `prepare_pr100_mirror.py` applies that method to 172 of the 184 interfaces. The other 12 have no usable rated boundary element and retain the staged N-0 TTC as an explicit fallback rather than receiving an arbitrary zero. Interface losses are calculated as rated-current `I^2R` loss divided by aggregate interface MW and clipped to a maximum of 20%. ReEDS transmission expansion is disabled with `GSw_TransRestrict=r`.

## 10. Native ReEDS Integration

Implementations: `prepare_pr_explicit_zone.py`, `prepare_pr_reeds_inputs.py`, `prepare_pr100_mirror.py`, and the guarded `PR_explicit` branches under `reeds/`.

The adapter is isolated behind `GSw_ZoneSet=PR_explicit`. It performs the following operations:

1. Registers the 121 electrical nodes as authoritative ReEDS regions in `inputs/zones/PR_explicit` while supplying compatibility keys required by legacy county-indexed code.
2. Uses already-regional PR100 load and renewable inputs instead of CONUS county allocation.
3. Registers the PR100 site supply curves and 2018–2019 HDF5 capacity-factor profiles under a common siting scenario.
4. Writes the `PR-115plus` integration-test database and the separate `PR100-1LM` calibrated database.
5. Converts the 184 interfaces to ReEDS directional energy and planning-reserve transfer inputs and disables transmission expansion.
6. Supplies explicit neutral or zero tables for disabled features that still require nonempty GAMS declarations, including underground hydrogen storage regions, ACP prices, hydrogen BA shares, regional capital-cost adjustments, hydro seasonal capacity adjustment, and spur-site metadata.
7. Bypasses CONUS-only remote-data synchronization and polygon-map operations for this point-node geography.
8. For `unitdata=PR100-1LM`, replaces the generic policy, fuel, transmission, DER, and technology-cost selections with the staged mirror inputs. The case-specific DFO/RFO technology mapping is written to both CSV and `inputs.h5`.

The smoke-case database contains 191 rows and 4,669.428 MW. The mirror database contains 164 records representing historical and future capacity vintages; summing all vintages gives 9,995.015 MW and is not a simultaneous-system capacity. Its active capacity in each PR100 year is defined by start and retirement years taken from the official aggregate 1LM output. Distributed PV is provided through the dedicated dGen input rather than this unit table.

## 11. Validation and Execution Status

Implementation: `validate_pr_staging.py` and unit tests under `tests/`.

The staging validator checks that:

- Region IDs are unique and the region count is 121.
- Every bus, active asset, and branch endpoint references a valid region.
- The 184 interfaces contain no duplicate pairs, self-loops, or unknown regions.
- The region graph is one connected component containing all 121 nodes.
- Supply-curve sites and capacity-factor profile columns are aligned.
- The profile weather years are 2018 and 2019.
- The load region columns exactly match the region master list.
- The load time and region dimensions match the expected values, its scenario attribute is 1LM, and its solve years match the staging configuration.
- Distributed PV and storage contain all 121-region/eight-year combinations with nonnegative values and consistent storage duration.
- The committed-project table contains 18 projects totaling 844.8 MW and uses only valid regions.
- Renewable rows use the confirmed real-2021 source-cost basis and offshore rows retain PR100 exclusion provenance.

The validation summary is written to `outputs/case_defaults/staging_validation.json`; its status is `staging_valid`. Unit tests cover impedance shortest paths, deterministic tie-breaking, internal versus cross-region branch classification, haversine distance, and supply-curve class construction.

Both the native smoke case and the `PR100_1LM_mirror` case have passed the following execution ladder:

1. ReEDS launcher, file copy, unit-data processing, and all Python input-processing scripts.
2. Representative-period clustering and seeded stress-period generation for the modeled years.
3. HDF5-to-GDX conversion.
4. `a_createmodel.gms`, including creation of `inputs.gdx` and a GAMS restart file.
5. First-year `3_solve_oneyear.gms` model compilation and LP generation.

The final validation run `pr100_mirror_final_PR100_1LM_mirror` generated a 2010 LP with 43,512 rows, 51,742 columns, and 168,239 nonzeros. The custom RPS, annual DPV, PR100 ITC path, fuel mapping, new-fossil ban with prescribed-build exemptions, calibrated unit records, cost files, and transmission inputs all passed the GAMS input domains and model compilation. The only observed blocker after LP generation is solver licensing: CPLEX exceeds the installed demo entitlement, and the installed GAMS license has no HiGHS entitlement. Therefore this validation establishes buildability through the solver boundary but does not yet establish feasibility or optimality.

## 12. Reproduction and Run Commands

Run the following commands from the ReEDS repository root. The `reeds` conda environment contains the pandas, NumPy, SciPy, h5py, and other ReEDS dependencies used by all stages.

```bash
cd /projects/aiplusinvest/ychen10/ReEDS

/home/ychen10/.conda-envs/reeds/bin/python \
  preprocessing/puertorico/prepare_pr_nodal.py
/home/ychen10/.conda-envs/reeds/bin/python \
  preprocessing/puertorico/prepare_pr_supply_curves.py
/home/ychen10/.conda-envs/reeds/bin/python \
  preprocessing/puertorico/convert_pr_profiles.py
/home/ychen10/.conda-envs/reeds/bin/python \
  preprocessing/puertorico/prepare_pr100_load.py
/home/ychen10/.conda-envs/reeds/bin/python \
  preprocessing/puertorico/prepare_pr100_der_committed.py
/home/ychen10/.conda-envs/reeds/bin/python \
  preprocessing/puertorico/calculate_pr_itl.py
/home/ychen10/.conda-envs/reeds/bin/python \
  preprocessing/puertorico/validate_pr_staging.py
/home/ychen10/.conda-envs/reeds/bin/python \
  preprocessing/puertorico/prepare_pr_explicit_zone.py
/home/ychen10/.conda-envs/reeds/bin/python \
  preprocessing/puertorico/prepare_pr_reeds_inputs.py
/home/ychen10/.conda-envs/reeds/bin/python \
  preprocessing/puertorico/prepare_pr100_mirror.py

/home/ychen10/.conda-envs/reeds/bin/python -m unittest discover \
  -s preprocessing/puertorico/tests -v
```

The checked-in `cases_pr.csv` sets `input_processing_only=0`, so the launcher proceeds through model compilation and solution when a licensed solver is available. The PR100 comparison invocation is:

```bash
module use /nopt/nrel/apps/software/gams/modulefiles
module load gams/53.5.1

env -u NREL_CLUSTER \
  PATH=/home/ychen10/.conda-envs/reeds/bin:/nopt/nrel/apps/software/gams/53.5.1:/usr/local/bin:/usr/bin:/bin \
  /home/ychen10/.conda-envs/reeds/bin/python -u runreeds.py \
  -b pr100_mirror -c pr -s PR100_1LM_mirror -l -f
```

Omit `-l` to use the repository's normal cluster submission path. The `-f` flag skips launcher environment checks; it does not bypass input validation or GAMS errors. A full run requires a GAMS environment licensed for a solver large enough for the generated model. After completion, generate the technology/year comparison with:

```bash
/home/ychen10/.conda-envs/reeds/bin/python \
  preprocessing/puertorico/compare_pr100_capacity.py \
  runs/pr100_mirror_PR100_1LM_mirror
```

## 13. Output Inventory

```text
outputs/network_115plus/
  regions.csv                         121-region master table
  bus_to_region.csv                   Complete bus-to-region mapping
  branch_to_region.csv                Line/transformer region mapping
  interfaces_screening.csv            Initial topology interfaces
  assets.csv                          Asset-level mapping and candidate crosswalk
  assets_by_region.csv                Region-aggregated asset capacity
  qa_summary.json                     Network and mapping QA

outputs/pr100_moderate_limited_2035/
  supplycurve_upv.csv
  supplycurve_wind-ons.csv
  supplycurve_wind-ofs.csv
  wind_ofs_excluded_sites.csv
  profile_site_selection.csv
  profile_manifest.csv
  profiles_cf/*.h5
  qa_summary.json

outputs/case_defaults/
  load.h5
  load_base_region_summary.csv
  municipality_region_load_weights.csv
  distributed_pv.csv
  distributed_storage.csv
  der_municipality_summary.csv
  municipality_region_der_weights.csv
  committed_tranche1_solar.csv
  interfaces_itl.csv
  upv_exogenous_profile_clones.csv
  pr_explicit_zone_qa.json
  pr_reeds_native_inputs_qa.json
  pr_reeds_unit_provenance.csv
  load_qa.json
  der_committed_qa.json
  itl_qa.json
  staging_validation.json

outputs/pr100_1LM_mirror/
  official_capacity_1LM.csv            Untouched public technology/year benchmark
  official_capacity_1LM_reeds_groups.csv
  distpv_total_reconciliation.csv
  annual_renewable_costs_2021usd.csv
  unitdata_provenance.csv
  fuel_prices.csv
  interfaces_itl_pr100.csv
  rps_fraction.csv and policy tables
  qa.json

inputs/zones/PR_explicit/
  hierarchy.csv
  county2zone.csv
  zonehash.csv
  b2b.csv
  interfaces_r.csv
  interfaces_transgrp.csv

inputs/supply_curve/
  supplycurve_upv-pr100-moderate-limited-35.csv
  supplycurve_wind-ons-pr100-moderate-limited-35.csv
  supplycurve_wind-ofs-pr100-moderate-limited-35.csv
```

The native-input generators also register capacity-factor HDF5 files under `inputs/profiles_cf`, annual technology costs under `inputs/plant_characteristics`, the PR100 ITC path at `inputs/financials/incentives_PR100_1LM.csv`, the annual DPV trajectory under `inputs/dgen_model_inputs/pr100_1LM`, and the calibrated generator database at `inputs/capacity_exogenous/ReEDS_generator_database_final_PR100-1LM.csv`.

## 14. PR100 1LM Mirror Calibration

Implementation: `prepare_pr100_mirror.py`

The `PR100_1LM_mirror` column is designed for like-for-like comparison with the publicly released PR100 1LM Engage result. It uses a 2010 initialization/bookkeeping period required by this ReEDS version, followed by the official result years:

```text
2022, 2025, 2028, 2030, 2035, 2040, 2045, 2050
```

### 14.1 Annual DER trajectory

The case sets `GSw_distpv=1` and forces distributed-PV capacity using `distpvcap_pr100_1LM.csv`. Every calendar year from 2010 through 2050 is present because `WriteHintage.py` consumes an annual history before selecting solve years. Values between PR100 reporting years are linearly interpolated by region.

The final Engage capacity output reports zero distributed PV in 2022 even though the official DER archive contains 450.793456 MW. The mirror therefore holds the DER-archive 2022 baseline backward through the 2010 bookkeeping period and uses the final Engage totals from 2025 onward: 771.534085, 954.541736, 1,063.448165, 1,246.199758, 1,443.744307, 1,855.672698, and 2,473.946481 MW. `distpv_total_reconciliation.csv` preserves both source series. Regional production uses a capacity-weighted PR100 utility-PV proxy; 95 regions have native profiles and 26 use the nearest available profile region.

Distributed storage from the DER archive is documented but is not made dispatchable, matching the PR100 Engage treatment described in the report.

### 14.2 Renewable targets

`GSw_StateRPS=1` applies a Puerto Rico all-renewable-energy standard with no alternative-compliance-payment escape:

- 0% before 2025;
- 40% from 2025 through 2039;
- 60% from 2040 through 2049; and
- 100% in 2050.

The policy is represented by `rps_fraction.csv`, `recstyle.csv`, `rectable.csv`, `acp_disallowed.csv`, and the associated neutral compatibility inputs. The 40% value is intentionally held through 2039; no unsupported intermediate target is invented.

### 14.3 Annual supply-curve and technology costs

All custom files use real 2021 dollars. Annual public PR100 reV cost shapes are normalized to published first-availability PR100 costs:

- UPV in 2025: 1,657 $/kW capital and 29.09 $/kW-year fixed O&M;
- onshore wind in 2025: 3,772 $/kW and 98.51 $/kW-year;
- offshore wind in 2035: 4,690 $/kW and 144.60 $/kW-year; and
- battery in 2025: 672.90 $/kW power, 644.10 $/kWh energy, and 85% round-trip efficiency.

UPV has public annual-shape source points through 2050. Public onshore and offshore inputs stop at 2035, so those costs are held at their 2035 values afterward. Battery costs use the annual ATB shape normalized to the published PR100 values. The ReEDS supply-curve quantity, POI, and capacity-factor topology remains the selected 2035 Moderate/Limited resource set. Consequently, the case implements year-varying costs but not year-varying site geometry; this is a structural approximation rather than an exact Engage replica.

The default 2026 ReEDS OBBBA incentives are not used. `incentives_PR100_1LM.csv` applies the PR100 report assumption of a 30% ITC through 2033, a linear midpoint of 15% in 2034, and zero from 2035 onward to PV, onshore wind, offshore wind, and batteries. PTCs, bonuses, safe harbor, and tax-equity penalties are zero, and dynamic ReEDS tax-credit phaseout is disabled. The proprietary PPOA inflation and contractual-financing terms cannot be reconstructed from the public report, so standard ReEDS financing remains an approximation around the published underlying costs and explicit ITC path.

### 14.4 Existing fleet, retirements, fuel, and storage

The official `energy_cap_1LM.csv` output is authoritative for aggregate capacity steps. The calibrated unit database applies the following principal schedule:

- 454 MW coal retires in 2028;
- diesel falls from 1,341 MW in 2022 to 941 MW in 2025 and 621 MW in 2030, with the remainder retired by 2050;
- No. 6 fuel oil falls from 1,235 MW in 2022 to 880 MW in 2025 and retires in 2028;
- aggregate natural gas starts at 1,230 MW, adds 400 MW in 2025, and retires in 2050;
- 10 MW hydro, 4.8 MW landfill gas, 75 MW onshore wind, and 143.1 MW existing/planned utility PV persist;
- the 2025 planned-PV addition is scaled to the exact official aggregate while retaining the 18 Tranche 1 project shares;
- four-hour storage is prescribed at 740 MW in 2025 and 1,490 MW cumulative in 2028; and
- the published ten-hour resource-adequacy storage increments and 2050 biodiesel capacity are prescribed in their reported years.

Source-network unit locations determine regional allocation. Diesel is represented by `gas-ct` with a DFO price, No. 6 fuel oil and 2050 biodiesel by `o-g-s` with an RFO/B100 trajectory, and natural-gas combined-cycle plus steam capacity by aggregate `gas-cc`. These mappings are ReEDS technology proxies; public data do not support exact unit-level reproduction.

New `gas-cc`, `gas-ct`, and `o-g-s` investments are banned in every region unless they are explicitly prescribed. ReEDS exempts prescribed capacity from the regional technology ban, so the known 2025 natural-gas addition and published 2050 biodiesel addition remain available while the model cannot introduce unmodeled fossil expansion. Because a fully calibrated PR100 biofuel investment option is not public, this mirror prescribes the official final biodiesel capacity instead of allowing the generic `o-g-s` proxy to compete endogenously.

There is one explicit source reconciliation: the public capacity CSV reports hydro as zero after 2022, while Section 8.2.6.1.6 of the final report states that the capacity-expansion model represents 10 MW of existing hydro throughout the PR100 horizon. The calibrated model follows the documented modeling assumption. The benchmark CSV remains untouched, so the capacity comparison will expose a 10 MW difference rather than hiding the source inconsistency.

Coal, natural gas, DFO, and RFO/B100 annual prices are staged separately. The public release contains these trajectories only as Figure 132, so the values are approximate digitizations in real 2021 $/MMBtu. The RFO proxy transitions to the published 2050 B100 price. The mirror does not use the former South Atlantic generic fuel trajectory.

### 14.5 Transmission, reserves, and reliability

Transmission expansion is disabled. Boundary continuous ratings are summed on 172 interfaces using the PR100 report method; 12 unrated interfaces use the documented N-0 TTC fallback. Interface losses use rated-current `I^2R` estimates.

Engage did not model operating reserves, startup costs, or the U.S. Clean Air Act Section 111 constraints, so `GSw_OpRes`, `GSw_StartCost`, and `GSw_Clean_Air_Act` are zero. Endogenous capacity-credit PRM and stress-period iteration are also disabled; the public ten-hour storage augmentation is prescribed instead. Adequacy checking is requested for every PR100 expansion year from 2025 through 2050 using 2019 weather and 10,000 Monte Carlo samples. `pras_trans_contingency=1` uses the PRM transfer capacities, including the configured 15% transmission derate, as a public-data proxy for the PR100 transmission-outage treatment. Static ReEDS generator outages are used because PR100 event-level generator and line outage draws are not public. The report's 2.4 event-hour LOLE criterion is a post-run interpretation target, not an optimization constraint in this case.

### 14.6 Original capacity benchmark

The official archive is read directly from:

```text
/projects/aiplusinvest/pr100_all/data/IntegratedCapacityInvestment.zip
  AnnualCapacities/energy_cap_1LM.csv
```

`official_capacity_1LM.csv` retains all 144 technology/year records. A second file aggregates only categories that can be compared consistently with ReEDS. After a licensed run, `compare_pr100_capacity.py` combines `outputs/cap.csv` with this benchmark and reports ReEDS MW, PR100 MW, absolute difference, and percent difference for every technology group and year. ReEDS output cannot uniquely separate battery duration or planned versus endogenous utility PV, so those categories are compared in aggregated form.

### 14.7 Exact and approximate boundaries

Exact public inputs include the eight official capacity-result years, aggregate technology capacities used for prescriptions and retirements, reported-year DPV totals after the documented 2022 reconciliation, renewable target schedule, public load/DER archives, and public renewable sites/profiles.

The following remain approximations because the underlying PR100 data are not public or because ReEDS uses a different model structure:

1. Engage/LUMA unit-level fleet, heat rates, future PPOA workbook, and operating costs.
2. Proprietary PPOA inflation, financing, safe-harbor, and tax-equity terms; only the public ITC path is reproduced.
3. Figure-digitized fuel prices.
4. Regional utility-PV profiles used for DPV.
5. Static 2035 resource geometry with annual costs rather than annual site curves.
6. Natural-gas steam/combined-cycle aggregation and liquid-fuel technology proxies.
7. Static PRAS generator outages and a 15% transfer derate in place of PR100 event-level generator and transmission outage draws.
8. N-0 fallback capacity on 12 interfaces without usable continuous ratings.
9. The fiscal-year-to-calendar-year load transformation, AST-to-ReEDS-time-zone convention, and the offshore 75-km study screen.
10. The public hydro-capacity CSV/report inconsistency described in Section 14.4.
11. Temporal sampling: Engage used three custom extreme periods at hourly resolution and six-hour resolution for the rest of the year. This ReEDS case uses its optimized representative-day formulation with three-hour dispatch chunks, so chronological operating detail is not identical.

The first required next step is a licensed solve followed by feasibility review and the generated capacity comparison. Any claim of exact PR100 reproduction should be limited to the inputs explicitly identified above; the model is a documented public-data mirror, not the proprietary original Engage case.
