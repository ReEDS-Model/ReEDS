# POI / Network-Reinforcement Cost Supply Curve

## Overview

ReEDS charges new capacity in each zone a point-of-interconnection (POI) / network-reinforcement cost through the `INV_POI` variable and `eq_POI_cap`, which requires POI capacity to cover all generation capacity built in the zone.
By default this cost is a single flat adder (`GSw_TransIntraCost`, applied to every technology).
This feature replaces the flat adder with a **regional increasing-cost supply curve**: successive amounts of new capacity in a zone cost more per MW, so the marginal reinforcement cost steps up with cumulative build.

The bin structure reuses the VRE resource-supply-curve pattern (`rscbin`): each bin has an incremental capacity width and a per-bin cost, and the LP fills the cheapest bins first under cost minimization — no ordering / SOS constraint is needed as long as bin costs strictly increase.
The flat cost is the degenerate one-bin case, so legacy results are reproduced exactly with `GSw_RegIntraCurve = 0`.

The curve is **native**: one bin per segment of the raw cumulative interconnection curve, at the raw data's own resolution.
There is no re-segmentation and no bin-count switch — the number of bins per zone follows the input data (currently 0–5 finite bins per zone, plus the backstop).

## Switches (`cases.csv`)

- `GSw_RegIntraCurve` — `0` (default) uses the legacy flat `GSw_TransIntraCost`; `1` activates the regional native curve. Requires `GSw_TransIntraCost > 0` (enforced in `runreeds.check_compatibility`, since the GAMS equations are gated on that switch).
- `GSw_POIUpperCost` — `[USD2025/kW]` cost of the unlimited backstop bin (`bin_upper`); only active when `GSw_RegIntraCurve = 1`.

## Inputs

The zonal curve is built at run time by `reeds/input_processing/transmission.py`:

- `write_poi_supply_curve` writes `inputs_case/poi_supply_curve.csv` (`*r, rtscbin, sc_cat in {cost, cap}, value`) and `inputs_case/rtscbin.csv` (the bin label set, used to size the GAMS `rtscbin` set).
  With `GSw_RegIntraCurve = 0` it is the flat `GSw_TransIntraCost` in a single `bin1`.
  With `GSw_RegIntraCurve = 1` the zonal bins are built natively from `raw_interconnection_TSC_data.csv` by `regional_poi_bins` — one bin per raw segment, sorted by increasing cost — with an unlimited `bin_upper` backstop appended at `GSw_POIUpperCost`.

`raw_interconnection_TSC_data.csv` is the single source of these curves for every spatial resolution (like the hashed transmission cost files) — there is no per-zone-set fallback. When `GSw_RegIntraCurve = 1`, a run whose model regions the file does not cover fails loudly (matching the transmission cost/distance validation).

### Dollar years

Three different dollar years meet here, and the order of operations matters:

- Raw curve costs are `USD2024` (registered in `dollaryear.csv`).
- `GSw_POIUpperCost` is `USD2025` (`GSW_POIUPPERCOST_DOLLAR_YEAR` in `transmission.py`), unlike `GSw_TransIntraCost`, which is already in the model dollar year.
- Both are deflated to the model dollar year (`2004$`) **before** they are compared, and `poi_supply_curve.csv` is written entirely in model dollars. `b_inputs.gms` then only converts `$/kW → $/MW`.

Deflating before the comparison is essential: comparing raw `USD2024` costs against a `USD2004` (or `USD2025`) threshold silently mis-prices the capped bins.

### The backstop and the cost cap

`bin_upper` is an unlimited bin priced at `GSw_POIUpperCost`, so reinforcement demand beyond the finite binned capacities stays feasible.
Raw segments priced **at or above** the backstop are dropped rather than emitted as finite bins: because the backstop is unlimited at exactly that price the two are equivalent for the LP, and dropping keeps bin costs strictly increasing (no ties with the backstop) and avoids redundant variables.
The dropped capacity is printed at build time so the truncation is visible in the run log rather than silent.

A zone whose every segment is priced at or above the backstop legitimately ends up with **zero finite bins** and sits entirely on `bin_upper` (a flat cost at `GSw_POIUpperCost`).
This is why region coverage is validated against the raw data rather than against the binned result, and why `bin_upper` is written for every model region — a region with no cost row at all would be silently exempted from `eq_POI_cap` and could build unlimited capacity free of reinforcement cost.

## GAMS implementation

The bin dimension folds straight into the existing `INV_POI` mechanism (`INV_POI(r,t)` → `INV_POI(r,rtscbin,t)`):

- `b_inputs.gms` — set `rtscbin`, always loaded from `rtscbin.csv` (the native bin count is not known at compile time); parameters `cost_poi_bin(r,rtscbin)` `[$/MW]`, `cap_poi_bin(r,rtscbin)` `[MW]` (incremental bin width, `0 = unlimited`), and `poi_bin_feas(r,rtscbin)`. A region the file omits **entirely** falls back to the flat `Sw_TransIntraCost` in `bin1`; that fallback is conditioned on the region having no POI cost of any kind, because a blanket `bin1` default would give a zero-finite-bin zone unlimited capacity (`cap_poi_bin = 0`) at the cheap flat cost and silently bypass its curve.
- `c_model.gms` — variable `INV_POI(r,rtscbin,t)`; `eq_POI_cap` (POI covers all zone capacity, now summed over `rtscbin`); `eq_POI_binlim(r,rtscbin,t)` caps cumulative `INV_POI` at each bin width, which is what makes the marginal cost step up.
- `d_objective.gms` — the capital and FOM terms use `cost_poi_bin` summed over `rtscbin` in place of the flat `Sw_TransIntraCost` scalar.
- `5_varfix.gms`, `report.gms`, `report_params.csv` — `INV_POI` fixing and reporting take the `rtscbin` index. Reported `poi_capacity` is a cost-accounting quantity, **not** deliverable transmission capacity, and relieves no flow.

### Avoiding double-counting with the VRE supply curve

The wind / solar / CSP / geo resource supply curves already embed a network-reinforcement cost (`cost_reinforcement_usd_per_mw`).
When the regional POI curve is active (`GSw_RegIntraCurve = 1` **and** `GSw_TransIntraCost > 0`), `reeds/io.py` drops that embedded reinforcement for all regions (recomputing `cost_total_trans` as spur + POI connection only) so it is not counted twice.
With `GSw_RegIntraCurve = 0` it is retained unchanged, preserving legacy results.

## Notes and assumptions

- **Validate before switching real scenarios to the regional curve.** Confirm the `GSw_RegIntraCurve = 0` case reproduces current flat-cost results, and that the curve costs and dollar years are correct, before relying on regional runs.
- The regional curve is far more expensive than the legacy flat adder for the current dataset (bin costs run from ~43 to ~1,177 `USD2004`/kW against a flat `GSw_TransIntraCost` of 65), so it is not a drop-in substitution — expect materially different build patterns.
- The POI curve is zonal and technology-agnostic: it replaces the site / bin / region-specific VRE reinforcement granularity with a zonal representation, and extends reinforcement pricing to **all** technologies (not just VRE).
- A parallel-variable alternative (`INV_REINF`, leaving `INV_POI` untouched) was considered but not implemented; extending `INV_POI` in place avoids duplicate POI accounting.
