## Summary

Replaces the flat intra-zone point-of-interconnection (POI) / network-reinforcement adder (`GSw_TransIntraCost`) with an optional **increasing-cost supply curve**. Successive amounts of new capacity built in a zone pay a higher marginal reinforcement cost, applied to **all** technologies through the existing `INV_POI` / `eq_POI_cap` mechanism.

While this is referred to as the POI in the code currently, this is purely the scaffolding that was used to implement the inclusion. POI in reV is separate from the reinforcement costs (POI is not the network costs). In this implementation, the POI from reV is still included but the reinforcement assumptions previously in reV are stripped out and replaced by the binned costs.

The bin structure reuses the VRE resource-supply-curve pattern (`rtscbin` as the indexer rather than `rscbin`): each bin has an incremental capacity width and a per-bin cost. The flat cost is the degenerate one-bin case, so **`numpoibins = 1` (the default) reproduces current behavior exactly** — the binned method is fully opt-in.

Method documentation: [`inputs/transmission/poi_supply_curve.md`](inputs/transmission/poi_supply_curve.md).

> **Scope:** this PR is the zonal / technology-agnostic reinforcement supply curve only. A wind-specific limit that caps how much wind fits in each reinforcement bin (`GSw_WindReinf`, `INV_WPOI`) is developed on a separate branch and will be proposed as a follow-on once this base mechanism is reviewed.

## Technical details

### Implementation notes

- **Input processing** (`reeds/input_processing/`): `make_poi_supply_curve.py` (new) builds the zonal cost bins from `raw_interconnection_TSC_data.csv` via optimal capacity-weighted least-squares segmentation. `transmission.py::write_poi_supply_curve` writes `poi_supply_curve.csv` (flat `GSw_TransIntraCost` when `numpoibins=1`, otherwise the binned curve with an unlimited `GSw_POIUpperCost` backstop bin). `raw_interconnection_TSC_data.csv` is the single source for every spatial resolution (like the hashed transmission cost files) — no per-zone-set fallback; a run whose regions it does not cover fails loudly (matching the transmission cost/distance validation).
- **GAMS**: `INV_POI(r,t)` → `INV_POI(r,rtscbin,t)`; new set `rtscbin`, params `cost_poi_bin`/`cap_poi_bin`/`poi_bin_feas`, and `eq_POI_binlim` (incremental bin-width cap) in `b_inputs.gms`/`c_model.gms`. Objective (`d_objective.gms`), var-fixing (`5_varfix.gms`), and reporting (`report.gms`, `report_params.csv`) updated to carry the `rtscbin` index. The single zonal curve applies to every technology (the free existing capacity `poi_cap_init` and the non-generator POI terms — spur, converter, LCC — attach here too).
- **Double-counting avoided**: when the curve is active (`numpoibins != 1` and `GSw_TransIntraCost > 0`), `reeds/io.py` drops the reinforcement cost already embedded in the VRE resource supply curves (all regions, since coverage is enforced), so it is not counted twice. Retained unchanged when `numpoibins = 1`.

### Additional changes

- `reeds/reedsplots.py` + `postprocessing/single_case_plots.py`: plotting helper for the POI supply curve.
- `inputs/transmission/README.md`: provenance for the raw input file; `dollaryear.csv` entry added (`raw_interconnection_TSC_data.csv`, USD2024). The per-zone-set `poi_supply_curve_{GSw_ZoneSet}.csv` placeholder files and their `runfiles.csv` copy entry were removed — the curve is built at run time from the single raw source.

### Switches added/removed/changed

| Switch | Change | Description |
|---|---|---|
| `numpoibins` | **added** | Number of POI cost bins. `1` (default) = legacy flat `GSw_TransIntraCost`; `>1` = binned curve; `0` = native (one bin per raw segment). |
| `GSw_POIUpperCost` | **added** | [USD2004/kW] cost of the unlimited backstop bin above the finite binned capacities; only active when `numpoibins != 1`. |
| `GSw_TransIntraCost` | unchanged | Now also serves as the `numpoibins = 1` flat-cost value. |

### Known incompatibilities

- `numpoibins != 1` (binned or native curve) requires `GSw_TransIntraCost > 0`; the curve is gated on that switch, so the combination `numpoibins != 1` with `GSw_TransIntraCost = 0` is rejected with a `ValueError` in `runreeds.py` rather than silently charging no reinforcement.
- `numpoibins = 1` (the default) reproduces the legacy flat-cost behavior exactly.

### Relevant sources or documentation

- Interconnection cost data from the [TSC](https://github.nrel.gov/ReEDS/TSC) model with still to be PR-ed interconnection optimization. **TODO:** Add in the exact links and docs (noted in `inputs/transmission/README.md`).

## Validation, testing, and comparison report(s)

- [ ] **Pending.** This is a model + data change, so full-US reference and full-US decarb comparison reports are required and will be added before merge.
- Test-case configs are included for exercising the feature at ERCOT resolution: `cases_transmission_test.csv` (`ERCOT_default` = flat legacy, `ERCOT_0` = near-zero flat, `ERCOT_regional` = binned curve).
- Default-case impact is expected to be zero because `numpoibins` defaults to `1` (legacy flat cost).

## Checklist for author

### Details to double-check
- [ ] Charge code provided to reviewers
- [ ] Included comparison reports for appropriate test cases *(pending)*
- [x] Documentation updated (`inputs/transmission/README.md`, `inputs/transmission/poi_supply_curve.md`, `docs/source/model_documentation.md`)
- If input data added/modified:
  - [x] Dollar year recorded (`dollaryear.csv`, USD2024) and converted to 2004$ for GAMS
  - [x] Units are specified
  - [ ] Preprocessing steps documented/committed to ReEDS_Input_Processing *(TSC-side; to confirm)*
  - [x] New large data files handled with .h5 instead of .csv *(only `raw_interconnection_TSC_data.csv` is added, which is small; the per-zone-set curve files were removed in favor of the single raw source)*
- [x] Code formatting standardized
- [x] Reusable functions used where possible instead of copy/pasted code

### General information to guide review
- [ ] Zero impact on results of default case (`numpoibins=1` default)
- [x] No large data file(s) added/modified *(only the small `raw_interconnection_TSC_data.csv`)*
- [ ] No substantive impact on runtime for full-US reference case
- [x] No change to package requirements
- [ ] No change to process flow *(`runreeds.py` gains one compatibility check: `numpoibins != 1` requires `GSw_TransIntraCost > 0`)*

#### Did you use LLM tools (chatbot or copilot) in the preparation of this PR? If so, describe how

Yes. Claude Code (Anthropic) was used across several sessions as a pair-programming and drafting assistant, with the author directing the design and reviewing/testing all changes:

- **Feature implementation**: planning and scaffolding the conversion of the flat `INV_POI` adder into a binned supply curve — GAMS sets/params/equations (`b_inputs.gms`, `c_model.gms`, `d_objective.gms`), `make_poi_supply_curve.py`, the `transmission.py` writer, and the objective/report/var-fix wiring.
- **Visualization**: regional POI maps and supply-curve comparison plots (`reedsplots.py`, `postprocessing/single_case_plots.py`).
- **Hardening & hygiene**: the USD2024→2004$ dollar-year conversion via `get_inflatable()`/`dollaryear.csv`; replacing most silent-default `sw.get()` switch lookups with direct indexing (keeping `.get()` only where switches are re-read from pre-feature runs); relocating `make_poi_supply_curve.py` into `reeds/input_processing/`; renaming the mislabeled `capacity_MW`→`capacity_GW` column; consolidating and restyling the documentation; and diff-hygiene cleanup.
- **Review response**: a multi-agent code review of the branch drove several fixes — gating the double-count reinforcement drop on `numpoibins != 1` (so native mode doesn't double-count), a `runreeds.py` guard rejecting `numpoibins != 1` with `GSw_TransIntraCost = 0`, consolidating the curves to the single `raw_interconnection_TSC_data.csv` source with fail-loud region-coverage validation (removing the per-zone-set placeholder files), and the `sw.get()` backward-compat for postprocessing on older runs.

All LLM-assisted changes were reviewed, directed, and tested by the author.

_Note: parts of this PR — including the summary of LLM usage above — were themselves drafted by Claude Code (from the branch diff and prior session history) and reviewed by the author. (but I have checked and edited a fair amount)_

<!-- Points of contact for review -->
<!-- - [ ] Transmission: @patrickbrown4 -->
<!-- - [ ] Supply curves, hourlize, reeds_to_rev: @bsergi -->
<!-- - [ ] Wind: @mmowers -->
