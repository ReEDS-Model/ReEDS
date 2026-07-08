# POI / Network-Reinforcement Cost Supply Curve

## Overview

ReEDS charges new capacity in each zone a point-of-interconnection (POI) / network-reinforcement cost through the `INV_POI` variable and `eq_POI_cap`, which requires POI capacity to cover all generation capacity built in the zone.
By default this cost is a single flat adder (`GSw_TransIntraCost`, applied to every technology).
This feature replaces the flat adder with an **increasing-cost supply curve**: successive amounts of new capacity in a zone cost more per MW, so the marginal reinforcement cost steps up with cumulative build.

The bin structure reuses the VRE resource-supply-curve pattern (`rscbin`): each bin has an incremental capacity width and a per-bin cost, and the LP fills the cheapest bins first under cost minimization — no ordering / SOS constraint is needed as long as bin costs strictly increase.
The flat cost is the degenerate one-bin case, so legacy results are reproduced exactly with `numpoibins = 1`.

## Switches (`cases.csv`)

- `numpoibins` — number of cost bins. `1` (default) reproduces the legacy flat `GSw_TransIntraCost`; `>1` activates the binned curve re-segmented to that many bins; `0` uses the native curve (one bin per raw supply-curve segment).
- `GSw_POIUpperCost` — `[USD2004/kW]` cost of the unlimited backstop bin (`bin_upper`) applied above the finite binned capacities; only active when `numpoibins > 1`.

## Inputs

The zonal curve is built at run time by `reeds/input_processing/transmission.py`:

- `write_poi_supply_curve` writes `inputs_case/poi_supply_curve.csv` (`*r, rtscbin, sc_cat in {cost, cap}, value`).
  With `numpoibins = 1` it is the flat `GSw_TransIntraCost`.
  Otherwise the zonal bins are built from `raw_interconnection_TSC_data.csv` via `make_poi_supply_curve.make_regional_poi_bins` (optimal capacity-weighted least-squares segmentation to `numpoibins` bins), with an unlimited `bin_upper` backstop appended at `GSw_POIUpperCost`.

Input costs are `USD2024` (registered in `dollaryear.csv`) and deflated to the model dollar year (`2004$`) at read time; `b_inputs.gms` then converts `$/kW → $/MW`.
See `README.md` in this folder for the input-file provenance.

## GAMS implementation

The bin dimension folds straight into the existing `INV_POI` mechanism (`INV_POI(r,t)` → `INV_POI(r,rtscbin,t)`):

- `b_inputs.gms` — set `rtscbin`; parameters `cost_poi_bin(r,rtscbin)` `[$/MW]`, `cap_poi_bin(r,rtscbin)` `[MW]` (incremental bin width, `0 = unlimited`), and `poi_bin_feas(r,rtscbin)`. Any region the file omits defaults to the flat `Sw_TransIntraCost`.
- `c_model.gms` — variable `INV_POI(r,rtscbin,t)`; `eq_POI_cap` (POI covers all zone capacity, now summed over `rtscbin`); `eq_POI_binlim(r,rtscbin,t)` caps cumulative `INV_POI` at each bin width, which is what makes the marginal cost step up.
- `d_objective.gms` — the capital and FOM terms use `cost_poi_bin` summed over `rtscbin` in place of the flat `Sw_TransIntraCost` scalar.
- `5_varfix.gms`, `report.gms`, `report_params.csv` — `INV_POI` fixing and reporting take the `rtscbin` index. Reported `poi_capacity` is a cost-accounting quantity, **not** deliverable transmission capacity, and relieves no flow.

### Avoiding double-counting with the VRE supply curve

The wind / solar / CSP / geo resource supply curves already embed a network-reinforcement cost (`cost_reinforcement_usd_per_mw`).
When the binned POI method is active (`numpoibins > 1` **and** `GSw_TransIntraCost > 0`), `reeds/io.py` drops that embedded reinforcement for all regions (recomputing `cost_total_trans` as spur + POI connection only) so it is not counted twice.
With `numpoibins = 1` it is retained unchanged, preserving legacy results.

## Notes and assumptions

- **Validate before switching real scenarios to multi-bin.** Confirm the single-bin (`numpoibins = 1`) case reproduces current flat-cost results, and that the binned costs and dollar year are correct, before relying on multi-bin runs.
- The binned POI is zonal and technology-agnostic: it replaces the site / bin / region-specific VRE reinforcement granularity with a zonal representation, and extends reinforcement pricing to **all** technologies (not just VRE).
- A parallel-variable alternative (`INV_REINF`, leaving `INV_POI` untouched) was considered but not implemented; extending `INV_POI` in place avoids duplicate POI accounting.
