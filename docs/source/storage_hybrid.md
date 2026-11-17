# Storage-Hybrid Technologies

A storage-hybrid technology pairs one generation technology (the "gen tech") with one storage technology (the "storage tech") behind a shared point of interconnection. Examples are nuclear with molten-salt thermal energy storage (TES), gas-cc with a battery, upv with a battery, and enhanced geothermal (EGS) with in-reservoir pressure storage.

ReEDS does not ship fixed storage-hybrid technologies. Instead, preprocessing creates one *wrapper* technology for each pairing that the case switches request. A wrapper is a run-specific entry in the technology set `i`. It takes its generation-side data from its gen tech and its storage-side data from its storage tech.

The wrapper formulation reuses the hybrid-plant equations that PV+battery (PVB) uses. The tech subset that holds PVB and CSP is therefore named `HYBRID_PLANT` (`hybrid_plant(i)` in GAMS). The name `STORAGE_HYBRID` (`storage_hybrid(i)`) now means the wrappers. See [Changes to existing behavior](#changes-to-existing-behavior).

## Conceptual model

Each wrapper has three capacities:

| Quantity | Model term |
| --- | --- |
| Generation-side power capacity | `CAP(i,v,r,t)` |
| Storage charge and discharge power capacity | `bcr(i) * CAP(i,v,r,t)` |
| Storage energy capacity | `CAP_ENERGY(i,v,r,t)`, built through `INV_ENERGY` |

The wrapper may also charge from the grid, up to `gridcharge_ratio(i) * CAP(i,v,r,t)`.

Wrappers use the hybrid-plant dispatch variables:

| Variable | Meaning |
| --- | --- |
| `GEN_PLANT(i,v,r,h,t)` | Generation-side output, including the energy sent to storage. |
| `STORAGE_IN_PLANT(i,v,r,h,t)` | Storage charging from the coupled generator. |
| `STORAGE_IN_GRID(i,v,r,h,t)` | Storage charging from the grid. |
| `GEN_STORAGE(i,v,r,h,t)` | Storage discharge. |
| `GEN(i,v,r,h,t)` | Net output to the grid. |

`eq_plant_total_gen` defines the net output:

```text
GEN = GEN_PLANT + GEN_STORAGE - STORAGE_IN_PLANT
```

Grid charging is not part of `GEN`. Instead, the supply-demand balance subtracts `STORAGE_IN_GRID` as load.

Fuel use and emissions follow `GEN_PLANT`, because the generator burns fuel for every MWh it produces, including the energy it sends to storage. Storage discharge burns no fuel.

## Switches

| Switch | Meaning |
| --- | --- |
| `GSw_StorageHybrid` | Turns wrappers on (`1`) or off (`0`). The default is `0`. |
| `GSw_StorageHybrid_Types` | `_`-delimited configuration IDs, for example `1_2_3`. Each ID is a label made of letters and digits; IDs are not technology names. |
| `GSw_StorageHybrid_GenTechs` | `_`-delimited gen techs, or numbered families that expand to their classes. |
| `GSw_StorageHybrid_StorageTechs` | `_`-delimited storage techs. |
| `GSw_StorageHybrid_BCR` | `_`-delimited storage power capacity per MW of generation capacity (BCR, the battery-to-capacity ratio). |
| `GSw_StorageHybrid_GridCharging` | `_`-delimited grid-charging power capacity per MW of generation capacity. `0` disables grid charging. |
| `GSw_StorageHybrid_CostMult` | Multiplier on wrapper capital cost (`cost_cap` and `cost_cap_energy`). **For testing only**: the CI case uses it so that a small case builds wrappers. The default `1` changes nothing. |
| `plantchar_tes` | TES cost and performance file, for example `tes_ATB_2024_moderate`. |
| `plantchar_flex_geo` | Placeholder inputs for in-reservoir geothermal storage (`flex_geo_placeholder`). |
| `heaterscen` | Resistive-heater cost file for grid charging of TES (`heater_sams_2020`). |

Each list switch takes either one value, which applies to every configuration, or one value per entry of `GSw_StorageHybrid_Types`. Switch values use hyphens, because underscores delimit the lists. Preprocessing matches hyphens and underscores interchangeably, so `battery-li` resolves to `battery_li`.

`GSw_StorageHybrid_GenTechs` accepts a single technology (for example `upv_3` or `egs_allkm_1`) or one of these families: `upv`, `wind-ons`, `wind-ofs`, `geohydro-allkm`, `egs-allkm` and `egs-nearfield`. A family expands to every numbered class of that family in `i`, so one configuration ID can create several wrappers.

Each wrapper is named `storage-hybrid-{ID}-{gen tech}`, for example `storage-hybrid-3-gas-cc` or `storage-hybrid-5-upv_3`.

### Example

```csv
GSw_StorageHybrid,1
GSw_StorageHybrid_Types,1_2_3_4
GSw_StorageHybrid_GenTechs,nuclear-smr_gas-cc_upv_egs-allkm
GSw_StorageHybrid_StorageTechs,tes-ms_battery-li_battery-li_flex-geo-med
GSw_StorageHybrid_BCR,0.5_0.25_0.5_0.5
GSw_StorageHybrid_GridCharging,0.0_0.25_0.25_0.5
```

| Wrapper(s) | Gen tech | Storage tech | BCR | Grid charging |
| --- | --- | --- | --- | --- |
| `storage-hybrid-1-nuclear-smr` | `nuclear-smr` | `tes_ms` | 0.5 | 0 |
| `storage-hybrid-2-gas-cc` | `gas-cc` | `battery_li` | 0.25 | 0.25 |
| `storage-hybrid-3-upv_1` ... `storage-hybrid-3-upv_10` | `upv_1` ... `upv_10` | `battery_li` | 0.5 | 0.25 |
| `storage-hybrid-4-egs_allkm_1` ... `storage-hybrid-4-egs_allkm_10` | `egs_allkm_1` ... | `flex_geo_med` | 0.5 | 0.5 |

### Validation

`check_storage_hybrid` in `reeds/checks.py` runs before a case starts, but only when `GSw_StorageHybrid=1`. It stops the run if any of these rules fails:

- `GSw_HybridPlant` must be `2` or `3`. Wrappers are hybrid plants, so `GSw_HybridPlant` `0` or `1` would ban them.
- `GSw_StorageHybrid_Types` must be non-empty, and its IDs must be alphanumeric and unique.
- Each list switch must have 1 value or one value per ID.
- Every BCR must be greater than 0, and every grid-charging ratio must lie between 0 and its BCR.
- `GSw_StorageHybrid_CostMult` must be a number greater than 0.
- A gen tech must be in `GENTECH`. It must not be any of these:
  - an upgrade tech or a cooling-water variant;
  - a storage, hydro or distributed-PV tech;
  - a tech that burns hydrogen, coal or biomass (`coal`, `cofire`, `bio`, `beccs`);
  - a tech that captures CO2 (`ccs`, `ccsflex`).

  The model's rules for those fuels and for CO2 capture have no wrapper terms yet; see [Limitations](#limitations).
- A storage tech must be in `STORAGE`. It must not be a hybrid plant, demand-flexibility or resource-supply-curve tech.
- TES may not pair with a VRE gen tech, and in-reservoir geothermal storage (`flex_geo*`) needs a geothermal gen tech.

## Preprocessing

`reeds/input_processing/copy_files.py` builds the wrappers.

### Configuration and generated files
`build_storage_hybrid_configs` resolves the switches into a list of wrappers. `write_storage_hybrid_case_inputs` then writes these files to `inputs_case`:

| File | Contents |
| --- | --- |
| `storage_hybrid_gentechs.csv` | wrapper → gen tech |
| `storage_hybrid_storagetechs.csv` | wrapper → storage tech |
| `storage_hybrid_bcr.csv` | wrapper → BCR |
| `storage_hybrid_gridcharging.csv` | wrapper → grid-charging ratio |
| `storage_hybrid_rsc_agg.csv` | gen tech → wrapper, for wrappers that share their gen tech's resource supply curve |

When `GSw_StorageHybrid=0`, these files are empty, and the GAMS sets they fill stay empty.

Preprocessing also extends three case inputs:
- It appends the wrappers to the `i` set in `inputs.h5`.
- It adds wrapper rows to the case copy of `tech-subset-table.csv`. Every wrapper is in `STORAGE`, `HYBRID_PLANT` and `STORAGE-HYBRID`. It also takes its gen tech's `RSC` and `cf_tech` flags.
- It copies the gen tech's vintage schedule into `ivt.csv`.

The repository inputs list only real technologies; wrappers exist only in `inputs_case`.

### Row-cloning registry
Many inputs are indexed by technology name, so each wrapper needs its own rows. `STORAGE_HYBRID_ROW_CLONES` in `copy_files.py` lists every input file and `inputs.h5` key that gets wrapper rows, with its technology column and its precedence:

| Precedence | Behavior | Examples |
| --- | --- | --- |
| `gen` | Copy the gen tech's rows; fall back to the storage tech's rows. | `years_until_endogenous`, `firstyear`, `maxage`, `unitsize`, `degradation_annual`, `i_c`, `nat_gen_tech_frac`, `employment_factor_plant` |
| `gen_only` | Copy the gen tech's rows; never fall back to the storage tech. | `outage_forced_static`, `outage_scheduled_static`, `mttr` |
| `storage` | Copy the storage tech's rows; fall back to the gen tech's rows. | `ramprate`, `cost_opres_*`, `construction_times`, `startcost` |

Before the next tech is tried, each tech is followed by its family root (for example `upv_3`, then `upv`). Geothermal gen techs also fall back to `geothermal`, the name that the outage files use for every geothermal class.

New rows are appended as text, so the existing lines of each file stay byte for byte the same. Range rows such as `upv_1*upv_10` match each class in the range.

The registry leaves some inputs out on purpose:
- inputs indexed by technology group (`cap_penalty`, `queue_limit`, `gbin_min`, `interconnection_queues`): wrappers join their gen tech's technology group, so they already count against its limits;
- existing and prescribed capacity: copies would add capacity the wrapper does not have;
- upgrade and cooling-water link files: wrappers are never upgrades or cooling variants;
- the supply-curve aggregation sets (`tg_rsc_upvagg`, `tg_rsc_cspagg`);
- inputs that GAMS or `plantcostprep.py` derives from the component techs, such as incentives and emission rates.

### Other preprocessing
- **Financial inputs:** `calc_financial_inputs.py` gives each wrapper its gen tech's financing rows and incentive (ITC) rows.
- **Outages:** `outage_rates.py` gives each wrapper its gen tech's hourly forced-outage profile.
- **Battery refurbishment:** `plantcostprep.py` adds the battery energy refurbishment cost (see [Costs](#costs)).

## Sets

`b_inputs.gms` builds these sets:

| Set | Members |
| --- | --- |
| `storage_hybrid(i)` | all wrappers |
| `storage_hybrid_gentech(i,ii)` | wrapper `i` → gen tech `ii` |
| `storage_hybrid_stortech(i,ii)` | wrapper `i` → storage tech `ii` |
| `storage_hybrid_vre(i)` | wrappers whose gen tech is VRE |
| `storage_hybrid_dispatchable(i)` | wrappers whose gen tech is not VRE |
| `storage_hybrid_with_tes(i)` | wrappers whose storage tech is TES; these also join `tes(i)` |
| `storage_hybrid_battery(i)` | wrappers whose storage tech is a battery |
| `storage_hybrid_gas(i)` | wrappers whose gen tech burns natural gas |
| `storage_hybrid_ofswind(i)` | wrappers whose gen tech is offshore wind |
| `geo_storage(i)` | the `flex_geo*` techs, and wrappers whose storage tech is one of them |
| `storage_hybrid_rsc_agg(i,ii)` | gen tech `i` → wrapper `ii`, for wrappers that share a supply curve; added to `rsc_agg` |

Wrappers also join their gen tech's technology groups through `tg_i`, which governs growth limits and interconnection-queue limits.

### Bans and timing
- A wrapper inherits `ban`, `bannew` and the state technology bans from both of its component techs. For example, `GSw_Nuclear=0` bans every wrapper on nuclear.
- The standalone `tes_ms` and `flex_geo*` techs are `bannew` in every run. They exist only as storage-side data sources for wrappers.
- A wrapper can first be built in its gen tech's first build year (`firstyear`), for example 2034 for nuclear under default settings.
- A wrapper takes `maxage`, `min_retire_age`, degradation and `nat_gen_tech_frac` from its gen tech.
- A wrapper is retirable when its gen tech is retirable under `GSw_Retire`. Its energy capacity can then retire with its power capacity (`eq_cap_energy_new_retub` and `eq_cap_energy_new_retmo`).
- Wrappers have no refurbishment or upgrade option.

## Costs

### Capital cost
Each wrapper's capital cost per MW of `CAP` is built from three component costs: the gen tech's capital cost (`cost_cap_storage_hybrid_p`), the storage tech's power capital cost (`cost_cap_storage_hybrid_s`), and the gen tech's powerblock cost. The powerblock cost is the gen tech's capital cost times the gen tech's powerblock share in `inputs/plant_characteristics/storage_hybrid_powerblock_share.csv`. The shares are 0.1024 for nuclear, 0.1332 for nuclear-SMR and 0.248 for the geothermal classes; all other gen techs get 0.

| Storage tech | `cost_cap` per MW of `CAP` |
| --- | --- |
| TES | gen capex − powerblock cost + (1 + BCR) × storage power capex + grid-charging ratio × heater capex |
| battery | gen capex + BCR × storage power capex |
| in-reservoir geothermal storage | gen capex + BCR × powerblock cost |

The rules differ by storage tech for these reasons:
- A TES wrapper discharges through the gen tech's turbine. The wrapper therefore pays once for an enlarged powerblock, priced through the TES power cost, instead of paying for two turbines.
- A battery wrapper has its own inverter, so it pays the full gen capex plus the battery's power capex.
- Geothermal reservoir storage discharges through the plant's turbine, so its storage-side power cost is the powerblock cost per MW of storage power.

Storage energy capacity costs `cost_cap_energy`, the storage tech's energy capex, per MWh of `INV_ENERGY`.

**Battery refurbishment:** upstream adds one discounted battery energy refurbishment to `battery_li`'s energy capex. A battery wrapper lives as long as its gen tech, so it needs one refurbishment every `batt_years_until_refurb` years over the gen tech's `maxage`. `plantcostprep.py` writes the discounted cost of the extra refurbishments to `storage_hybrid_refurb_energy.csv`, and GAMS adds it to the wrapper's energy capex.

### Operating costs
- Fixed O&M is the gen tech's FOM plus BCR times the storage tech's power FOM, per MW of `CAP`. Energy-capacity FOM (`cost_fom_energy`) applies to `CAP_ENERGY`.
- Variable O&M on `GEN_PLANT` uses the gen tech's VOM. Variable O&M on `GEN_STORAGE` uses the storage tech's VOM (`cost_vom_storage_hybrid_s`).
- Heat rate, VOM and FOM are averaged over the gen tech's vintages in the same way as for the gen tech itself.
- Fuel cost applies to `GEN_PLANT`. Gas wrappers (`storage_hybrid_gas`) enter the gas supply curve, the gas accounting and the seasonal gas-price multiplier `gasprice_adj_r` in the same way as their gen tech. They are left out of the fixed-price fuel term.
- Wrappers inherit their gen tech's emission rates, capture rate and upstream methane. Gas wrappers carry the gas cost-recovery penalty.

### Financing
- The generation side uses the gen tech's capital multiplier (`cost_cap_fin_mult_storage_hybrid_p`).
- The storage side uses the storage tech's multiplier, rescaled to the gen tech's financing risk (`cost_cap_fin_mult_storage_hybrid_s`). The exception is in-reservoir geothermal storage, whose storage-side multiplier is 1, because its cost is a share of the powerblock rather than a standalone storage cost.
  - The storage tech's multiplier includes its incentives. `TES` rows in `inputs/financials/incentives_*.csv` copy the `BATTERY` rows, because both are energy storage; `tests/test_storage_hybrid.py` checks that they stay equal.
- `cost_cap_fin_mult` for `INV` is the cost-weighted average of the two sides, weighted the same way as `cost_cap`.
- `INV_ENERGY` uses the storage-side multiplier.
- Wrappers on supply-curve gen techs pay their gen tech's `rsc_fin_mult`.

### Interconnection
A wrapper can inject its plant output and its storage discharge at the same time. It therefore pays for interconnection of `CAP/ILR + BCR × CAP`:
- `eq_POI_cap` counts that amount for wrappers without endogenous spur lines.
- Under `GSw_SpurScen=0`, the supply-curve spur cost is multiplied by `(1 + BCR × ILR)`.
- Under `GSw_SpurScen=1`, `eq_spur_noclip` and `eq_spurclip` reserve `BCR × CAP_RSC` of spur capacity at the wrapper's sites.

## Operations

| Equation | Rule for wrappers |
| --- | --- |
| `eq_hybrid_plant_energy_limit` | VRE wrappers: `GEN_PLANT ≤ m_cf × CAP`. Dispatchable wrappers: `GEN_PLANT ≤ avail × CAP × (1 + seasonal capacity change)`, where `avail` holds the gen tech's forced and scheduled outages. |
| `eq_hybrid_plant_storage_limit` | `STORAGE_IN_PLANT ≤ GEN_PLANT` |
| `eq_plant_capacity_limit` | `GEN_PLANT − STORAGE_IN_PLANT + GEN_STORAGE + STORAGE_IN_GRID + reserves ≤ (1 + BCR) × CAP` |
| `eq_hybrid_storage_capacity_limit` | `GEN_STORAGE + STORAGE_IN_PLANT + STORAGE_IN_GRID ≤ BCR × CAP` |
| `eq_storage_capacity` | the same activity, plus reserves, ≤ `BCR × CAP × avail`; the storage side shares the plant's outages |
| `eq_cap_storage_in_grid` | `STORAGE_IN_GRID ≤ gridcharge_ratio × CAP` |
| `eq_storage_hybrid_geo_storage_grid_only` | in-reservoir geothermal storage charges only from the grid: `STORAGE_IN_PLANT = 0` |
| `eq_storage_level` | stored energy gains `eff_p × STORAGE_IN_PLANT + eff_g × STORAGE_IN_GRID` and loses `GEN_STORAGE` |
| `eq_storage_duration` | `STORAGE_LEVEL ≤ CAP_ENERGY` |
| `eq_battery_minduration` | new builds: `CAP_ENERGY ≥ BCR × CAP × minimum duration` of the storage class: `minbatteryduration` (0.1 h) for batteries, `mintesduration` (2 h) for TES, none for geothermal reservoir storage |
| `eq_mingen_fixed` | dispatchable wrappers apply minimum generation to `GEN_PLANT`, not `GEN` |

Charging efficiencies:
- `eff_g` (grid charging) is the storage tech's round-trip efficiency.
- `eff_p` (plant charging) is the same for batteries but 0.999 for TES. Plant-to-TES transfer is nearly lossless, and the value is slightly below 1 so that the model does not cycle TES without reason.

**Operating reserves:**
- Wrappers take the storage tech's ramp rate and reserve cost, because reserves come from the storage or powerblock and not from cycling the generator.
- `eq_storage_opres` lets a dispatchable wrapper back reserves with its unused generator headroom (`avail × CAP − GEN_PLANT`) as well as with stored energy.
- The `flex_geo*` techs have Geothermal's ramp rate (0.04), so geothermal reservoir wrappers can provide reserves.

### VRE wrappers
- A wrapper on upv, wind-ons or wind-ofs uses its gen tech's capacity factors: GAMS copies `cf_in` for the wrapper's resource class.
- The wrapper takes the gen tech's inverter loading ratio (ILR), so its `CAP` and BCR are on the DC basis, like PVB.
- The wrapper shares its gen tech's resource supply curve through `storage_hybrid_rsc_agg`. Its investment counts against the same `eq_rsc_INVlim` bins as the gen tech, and the objective charges its supply-curve cost once.
- With endogenous spur lines, the wrapper joins the gen tech's sites, and only its `GEN_PLANT` counts against site availability.

### Geothermal wrappers
Geothermal wrappers share the parent geothermal supply curve through the same `storage_hybrid_rsc_agg` mapping. Discovery scaling and exogenous supply-curve reductions stay on the parent tech. The wrapper still feels them, because the shared `eq_rsc_INVlim` row binds both.

## Policies

- **Production tax credit:** a wrapper earns the PTC on `GEN_PLANT`, the same as a standalone generator with separately metered storage. Grid-charged energy never enters `GEN_PLANT`.
- **RPS and CES:** a wrapper inherits every RPS and CES category, the voluntary REC market and the partial CES credit of its gen tech. It generates RECs on `GEN_PLANT`. The REC requirement subtracts wrapper grid charging from the load that the requirement covers. Wrappers also inherit `techs_banned_imports_rps`.
- **Battery mandate:** `eq_batterymandate` counts `BCR × CAP` of battery wrappers. TES and geothermal reservoir storage do not count.
- **Offshore wind mandate:** `eq_RPS_OFSWind` counts the turbine investment of wind-ofs wrappers.
- **Clean Air Act section 111:** `eq_caa_max_cf` limits gas wrappers' `GEN_PLANT` to `caa_gas_max_cf` of `CAP`.
- **CSAPR:** NOx is counted on `GEN_PLANT`.

## Resource adequacy

### Capacity credit (`GSw_PRM_CapCredit=1`)
- **Generation side:** a dispatchable wrapper gets firm capacity of `CAP × (1 + seasonal capacity change) × (1 − mean forced outage rate)`, using its gen tech's outage rates. `capacity_credit.py` gives the wrapper its gen tech's hourly forced-outage column through `reeds.techs.add_storage_hybrid_gentech_members`.
- **Storage side:** the storage side enters the storage-duration bins (`CAP_SDBIN`) with `cc_storage`, like a battery. VRE wrappers also take the PVB-style `hybrid_cc_derate`.
- **VRE generation side:** VRE wrappers get capacity credit from their own resources, which reuse the gen tech's profile.
- **Bin sizing:** `capacity_credit.py` sizes the storage-duration bins from standalone storage only.

### PRAS and stress periods
`reeds2pras` turns each regional wrapper fleet into PRAS `GeneratorStorage` units (`process_storage_hybrids` in `reeds_data_parsing.jl`):
- Units have the gen tech's unit size, the same as thermal units. When `pras_max_unitsize_prm=1` (the default), the unit size is capped at the zone's PRM-based maximum. A fleet with no forced outages stays one unit.
- For a unit of capacity `U`, the unit gets:
  - charge capacity = discharge capacity = `BCR × U`;
  - energy capacity = `CAP_ENERGY × U / CAP`;
  - grid withdrawal = `gridcharge_ratio × U`;
  - grid injection = `(1 + BCR) × U`.
- The inflow is `U` for a dispatchable gen tech. For a VRE gen tech, it is the gen tech's available-output profile.
- Outage rates come from the wrapper's rows, with a fallback to its gen tech.
- A unit's forced outage takes its storage offline too. That is physical for TES behind a shared powerblock. For gas with a battery it is conservative: in a test system it gave about 6% more expected unserved energy than independent generator and battery units.
- The LP caps charge plus discharge jointly at `BCR × CAP`, while PRAS caps each one separately. PRAS gains nothing by charging and discharging in the same hour, so the two should agree in practice.

`prep_data.py` writes `handoff/reeds_data/hybrid_config_{t}.csv` for PRAS. It collapses wrapper vintages like standalone storage and never drops wrappers as too small. `run_pras.jl` exports GeneratorStorage energy for stress-period selection.

## Outputs

| Output | Contents |
| --- | --- |
| `cap_ivrt`, `cap` | wrapper power capacity `CAP` |
| `cap_energy_ivrt` | `CAP_ENERGY` for batteries, TES and wrappers |
| `gen_h`, `gen_ann` | net output, less grid charging |
| `gen_plant_h`, `gen_plant_ivrt` | generation-side output |
| `gen_storage_h` | storage discharge |
| `storage_in_plant_h`, `storage_in_grid_h` | charging from the plant and from the grid (reported as negative values) |
| `gen_plant_h_stress`, `gen_storage_h_stress` | the same components in stress periods |
| `stor_inout`, `stor_in`, `stor_out` | storage throughput (charging and `GEN_STORAGE`), not total plant output |
| `storage_duration_out` | `CAP_ENERGY / (BCR × CAP)` |
| `systemcost`, `systemcost_techba` | wrapper capital, FOM, VOM and fuel costs |
| `repgasquant_irt` | wrapper gas burn on `GEN_PLANT` |

Bokeh maps wrappers to the `storage-hybrid` style through a wildcard row in `tech_map.csv`.

## Testing

- `tests/test_storage_hybrid.py` holds unit tests for configuration parsing, family expansion, the `ivt` append, the row-cloning registry and the validation rules. CI runs it.
- The CI scenario `github_StorageHybrid` in `cases_test.csv` is `github_Pacific` with three wrapper types: nuclear+TES, gas-cc+battery with grid charging, and upv+battery. It sets `GSw_StorageHybrid_CostMult=0.5`, so it builds upv+battery wrappers by 2030. A CI step fails if `cap.csv` has no wrapper capacity.
  - The case ends in 2030, so the nuclear wrapper exercises only setup.
- `tests/objective_function_params.yaml` lets `check_inputs.py` check the wrapper cost parameters, BCR and heat rate on every case. `gridcharge_ratio` is not checked, because 0 is a valid value that GAMS does not store.
- `cases_hybridtest.csv` holds Utah and z54 verification cases.

## Changes to existing behavior

This feature changes some code that runs even when `GSw_StorageHybrid=0`.

**Verified scope:** on the Utah case (`base_ut`, z54 zones, Utah only, to 2040), this branch and upstream give identical `systemcost`, `cap` and `gen_ann` in every year, and identical LP equations. The branch adds two LP columns per solve: the queue-overflow slacks for the new `tes` and `geo-storage` technology groups. Each column has only an objective coefficient, so neither can change the solution. This check covers neither PVB runs (`GSw_PVB=1`) nor regions with CSP.

1. **Subset rename (breaking change for external tools).** The tech-subset column `STORAGE_HYBRID` (PV+battery and CSP) is now `HYBRID_PLANT`, and the GAMS set `storage_hybrid(i)` is now `hybrid_plant(i)`. The name `STORAGE_HYBRID`/`storage_hybrid(i)` now means wrappers.
   - Every in-repo consumer was updated: GAMS, `prep_data.py`, `i_subtech.csv`, the tech-subset table and `tests/objective_function_params.yaml`.
   - External tools that read the `STORAGE_HYBRID` column, such as R2X, need the same rename.
   - The new name matches the existing `GSw_HybridPlant` switch and the `cost_vom_hybrid_plant` naming.
2. **New technologies and groups:**
   - `tes_ms` and `flex_geo`, `flex_geo_high`, `flex_geo_med` and `flex_geo_low` are added to `i`, with input rows. They are `bannew` and never appear in a base LP.
   - New technology groups `tes` and `geo-storage` are in `tg.csv` and `cap_penalty.csv`.
   - New tech-subset columns: `TES`, `GEO_STORAGE`, `STORAGE-HYBRID`.
3. **PV+battery formulation (only with `GSw_PVB=1`).** The hybrid-plant equations were generalized for wrappers, which changes PVB:
   - Plant charging is no longer restricted to `dayhours` in `eq_plant_total_gen`, `eq_storage_capacity` and `eq_storage_level`. Solar output is already zero at night, so the restriction was redundant.
   - `eq_hybrid_plant_energy_limit` no longer adds `STORAGE_IN_PLANT` to `GEN_PLANT`. Instead, `GEN_PLANT` now includes the energy sent to storage, and the new `eq_hybrid_plant_storage_limit` caps plant charging at `GEN_PLANT`. `eq_plant_capacity_limit` subtracts `STORAGE_IN_PLANT`, because plant-to-storage flow never crosses the inverter's grid side.
   - The new `eq_hybrid_storage_capacity_limit` caps total storage activity at `BCR × CAP`, which is the physical battery limit.
   - REC and PTC accounting subtract PVB grid charging without the factor `storage_eff_pvb_g`. Before, the credit was netted by the energy stored rather than the energy drawn from the grid.
   - Reporting changes for PVB: VOM split, `gen_h`, `stor_inout`/`stor_out` (now storage throughput), storage losses, charging cost (`revenue('charge')`), `valnew` and `powfrac_calc.gms`.
4. **Energy capacity for batteries, TES and hybrid plants.**
   - `eq_cap_energy_new_noret` now covers `tes(i)` and `hybrid_plant(i)` as well as batteries, but only for tuples that cannot retire.
   - Retirable tuples use the new `eq_cap_energy_new_retub` and `eq_cap_energy_new_retmo`, so energy capacity can retire with power capacity. This affects batteries under `GSw_Retire=4`.
   - The objective has a matching energy-capacity retirement penalty.
   - The storage-duration bins, `eq_storage_duration` and `eq_battery_minduration` cover TES and wrappers.
5. **Prescribed energy capacity.** `eq_forceprescription_energy` covers TES and wrappers. It also allows energy slack (`EXTRA_PRESCRIP_ENERGY`) for any tuple with a power prescription but no energy prescription, even before the tech's first year. Without the slack, the equality would force zero energy capacity while `eq_battery_minduration` requires a positive minimum.
6. **Removed equation.** `eq_storage_thermalres` is gone. Upstream's `THERMAL_STORAGE` subset was empty, so the equation never generated a row.
7. **Reporting.**
   - `stor_energy_cap` and `cap_energy_ivrt` report `CAP_ENERGY` for techs with endogenous energy capacity.
   - LCOE includes energy capital and energy FOM for TES and wrappers.
   - `report.gms` no longer multiplies energy-capacity FOM by ILR.
8. **Upstream bug fixes found while testing** (each is independent of wrappers):
   - `reeds2pras` `make_pras_interfaces` raised `BoundsError` for a system with no lines (any single-region run). It now returns empty Lines and Interfaces.
   - `report_calcs.py` raised `KeyError` when `FLOW` is empty (single-region runs). It now skips the transmission report.
   - `process_storages` in `reeds2pras` now looks up energy capacity by key, not by position.
   - `writecapdat.py` matched vintage rows by substring, so a wrapper named after upv or wind doubled that tech's prescribed builds. It now leaves wrapper rows out.

## Limitations

- **Rejected gen techs.** Coal, biomass, BECCS, gas-CCS and hydrogen gen techs are rejected rather than supported. Supporting them needs wrapper terms in these rules:
  - coal: `eq_caa_rate_standard` and the forced coal retirements;
  - biomass: `eq_bioused`, `eq_biousedlimit` and the biomass cost;
  - BECCS: `eq_cdr_cap`;
  - CCS: 45Q, CO2 transport and storage, `CO2_CAPTURED` and the CCS clean-energy exclusion;
  - hydrogen: the H2 balance.
- **Rules that use net output.** Some rules count `GEN` (net output) for wrappers rather than `GEN_PLANT`: `eq_min_cf`, `eq_national_gen`, `eq_REC_launder`, `eq_h2_ptc_creditgen`, minimum loading (`eq_minloading`, `eq_mingen_lb`/`ub`) and the `GSw_StartCost` 5 and 6 ramps. Each is off by default or has a small effect.
- **Water.** Water accounting (`GSw_WaterMain=1`) does not cover wrappers.
- **FINITO.** The linked ReEDS-FINITO model (`FINITO=1`) is rejected, because its fuel accounting does not include wrapper fuel use.
- **Off-default switches that skip wrappers.** `GSw_OffshoreZones=1` drops wind-ofs wrappers, flex-geo wrappers are never interday storage, and the stress-hour availability override excludes wrappers.
- **Seasonal derate.** Wrappers apply the seasonal capacity change to storage discharge as well as to plant output. That is physical for TES, which discharges through the shared powerblock. It is approximate for batteries, and it only matters when `thermal_summer_cap_delta` is nonzero.
- **Financing and growth.** The storage share is financed at the gen tech's risk multiplier, and the growth-penalty basis includes storage power capex.
- **No upgrades.** Gas wrappers have no upgrade path to CCS or hydrogen.
- **Battery degradation.** On VRE wrappers, the storage degrades at the PV or wind rate, as it does for PVB.
- **VRE wrapper gaps.** VRE wrappers add no operating-reserve requirement, unlike PV and PVB, and the curtailment reports leave them out.
- **Reporting gaps:**
  - `load_cat('stor_charge')` includes plant charging;
  - `revenue('rps')` uses net `GEN`;
  - LCOE VOM omits the storage-side VOM;
  - `postprocessing/tech_aggregation.csv` has no wrapper rows.
- **Capacity credit.** `hybrid_cc_derate` is always 1, for PVB and wrappers alike. The intertemporal capacity-credit terms `cc_int` and `cc_excess` would stack for wrappers; sequential solves set them to 0.
- **MGA.** MGA weights a wrapper once for each subset it belongs to.

## Key files

| File | Role |
| --- | --- |
| `cases.csv` | wrapper switches |
| `reeds/checks.py` | `check_storage_hybrid` validation |
| `reeds/input_processing/copy_files.py` | configurations, generated files, `i`/subset/`ivt` appends, row-cloning registry |
| `reeds/input_processing/calc_financial_inputs.py`, `outage_rates.py`, `plantcostprep.py` | financing, outage and cost inputs for wrappers |
| `reeds/techs.py` | `add_storage_hybrid_gentech_members` for tech-group lists |
| `inputs/plant_characteristics/tes_ATB_2024_*.csv`, `flex_geo_placeholder.csv`, `heater_sams_2020.csv`, `storage_hybrid_powerblock_share.csv` | storage-side and powerblock inputs |
| `reeds/core/setup/b_inputs.gms` | sets, bans, inherited parameters, cost composition |
| `reeds/core/solve/2_financials.gms` | generation-side, storage-side and composed financial multipliers |
| `reeds/core/solve/2_temporal_params.gms` | wrapper capacity factors and outages |
| `reeds/core/setup/c_model.gms` | dispatch, storage, interconnection, policy and adequacy constraints |
| `reeds/core/setup/d_objective.gms` | wrapper capital, O&M, fuel and tax-credit terms |
| `reeds/core/solve/6_data_dump.gms` | handoff of energy capacity and gas burn |
| `reeds/core/terminus/report.gms` | wrapper outputs and system cost |
| `reeds/resource_adequacy/prep_data.py`, `reeds2pras/src/utils/reeds_data_parsing.jl`, `run_pras.jl` | PRAS GeneratorStorage units |
