# Constraint-layer fix: changelog, tests, and decisions

Branch `yc/reedssurr`, 2026-11-06. Nothing is committed. No model was retrained, and no `.joblib`
artifact or stored OOF prediction was modified. Paths are relative to
`postprocessing/reedssurr/Stage2/`. There were two rounds: the first fix, then your decisions on the
three side effects.

## Code changes

| File:line | Change |
|---|---|
| `code/surrogate_constraints.py:21-42` | Module docstring describes the rules and their order. |
| `code/surrogate_constraints.py:67-71` | Comment on the exemptions: the authoritative list is the ReEDS `sys_costs` set (`reeds/core/terminus/report.gms:11`), and `op_h2_revenue_exog` must be exempt if it ever appears. The rule itself is unchanged. |
| `code/surrogate_constraints.py:12-18, 114-139, 441` | **Round 3:** rule 1 is generalized from "clip at zero" to "clip at the known lower bound". `clip_predictions(pred, floors)` keeps the zero clip and raises each regional transmission corridor to its floor (initial capacity). `apply_constraints` passes the floors to the clip, which runs before the rescale. Training-time clipping is unchanged. |
| `code/surrogate_constraints.py:224-246` | `_TRAN_RE` and `_additivity_key`: transmission corridors `tran_pA_pB_<type>` map to `tran_total`. Each interface is keyed by its sorted region pair, so it counts once. |
| `code/surrogate_constraints.py:250-268` | **New** `transmission_floors(train_df)`: the floor of each regional corridor is its minimum over the training runs. **Round 4:** `system_transmission_floors(corridor_floors)` gives the system `tran_total` floor, the sum of the corridor floors (34,478.6 MW); the same rule-1 clip applies it. |
| `code/surrogate_constraints.py:261-345` | `enforce_additivity(regional, overall, constants, floors)`, described below. |
| `code/surrogate_constraints.py:349-365` | `dgen_distpv_cap_mw` and the `DGEN_*` constants are removed. New `hold_constants(pred, constants)` sets every zero-variance output to its ReEDS value. |
| `code/surrogate_constraints.py:402-446` | `Stage2InferenceConfig`: `apply_additivity` defaults to `True`, and `apply_dgen_distpv` is renamed `apply_constant_override`. `apply_constraints(pred, *, overall_pred, constants, floors, config)` runs (i) hold constants, (ii) clip, (iii) regional rescale, (iv) cost identity. The `x_dem_value` argument and the dead DistPV branch are removed. |
| `code/surrogate_predict.py:87-117` | `predict(artifact, levels, overall_pred=None, constants=None, floors=None)` passes all three to `apply_constraints`. |
| `code/surrogate_predict.py:132-133` | Pointer to the exemption note. |
| `code/surrogate_uq.py:56-78` | `prediction_interval(..., overall_pred, constants, floors)`. Half-widths are aligned to the point index, with zero width for held constants and a derived regional `cost_total`. This also fixes a crash for regional artifacts. |
| `code/reeds_proxy.py:75-80` | Imports `apply_constraints`, `transmission_floors` and `system_transmission_floors`. The DistPV and `clip_physical_bounds` imports are removed. |
| `code/reeds_proxy.py:440-476` | New `_layer_floors` (round 4): corridor floors on the regional layer, the `tran_total` floor on the system layer. New `_system_pred_for_additivity`: the constrained system prediction from the same model, using the OOF path for training runs and the final model otherwise. |
| `code/reeds_proxy.py:617-619` | Header text no longer mentions the dgen DistPV override. |
| `code/reeds_proxy.py:1823-1855` | Both Predict-tab paths run the full stack with the layer's constants and floors. On the regional layer they also pass `overall_pred`. The OOF path now applies the cost identity. The DistPV-curve override and `_augment_predicted_with_constants` are removed. |
| `tests/test_surrogate_constraints.py` (new) | 15 unit tests. |

`surrogate_ml_models.py`, the training code, and all artifacts are untouched. `logs/_make_figures.py`
was changed in round 1 to read constrained OOF predictions. It was restored to its committed version
in round 2, because the figures use the raw OOF scores.

### Regional additivity rule as shipped (`enforce_additivity`)

For each system quantity with modelled regional columns, the rule works as follows. Here f_r is the
floor (the corridor's initial capacity for transmission, 0 for everything else) and C is the sum of
the dropped-constant regional columns.

1. **Mixed-sign guard (kept by your decision).** Skip the quantity if any modelled regional value is
   below its floor; with f_r = 0 that means negative. A tolerance of 1e-6 relative absorbs round-off
   (`:320-322`).
2. **Rescale above the floors.** y_r' = f_r + s'·(y_r − f_r), with s' = (T − C − Σf_r) / Σ(y_r − f_r),
   so Σ y_r' + C = T.
3. **Skip when there is nothing to scale.** Skip if Σ(y_r − f_r) ≤ 0.
4. **No room above the floors (my decision, `:332-338`).** If T − C − Σf_r ≤ 0, a quantity with floors
   is set to its floors (s' = 0). A quantity without floors is skipped, as before.

With every f_r = 0 this reduces to the round-1 rule.

## Tests

```
python -m pytest postprocessing/reedssurr/Stage2/tests -q      (reeds2 env)
17 passed
```

The tests cover:

- additivity with a constant region;
- a corridor mapped to `tran_total`;
- an interface listed in both directions counted once, and a constant corridor held fixed;
- skips when the regional sum or the target is ≤ 0;
- the mixed-sign skip;
- **the floor-preserving rescale.** Values stay at or above their floors, the sum matches, and the
  plain rescale would break the floor;
- **a system value at or below the floor sum,** which sets the corridors to their floors, while
  quantities without floors still skip;
- **a value below its floor,** which `enforce_additivity` alone skips, but which `apply_constraints`
  first raises to the floor and then rescales (round 3);
- **`transmission_floors`,** and the system `tran_total` floor (round 4);
- additivity on by default, and a no-op without `overall_pred`;
- clip before rescale;
- cost_total equal to the component sum;
- `cap_distpv` held at 12,994.628099 MW;
- regional DistPV constants not rescaled;
- `predict()` plumbing;
- `prediction_interval()` alignment.

**Dashboard.** `analysis/pesgm/11_dashboard_check.py` runs `reeds_proxy.py` in-process and calls its
own `_redraw`, for RF and MLP, on a training-grid design and an off-grid design. **All 56 checks
pass (round 4):** the original 52, plus 4 that check the system `tran_total` floor.

- **(a) Additivity:** regional `cap_nuclear`, `tran_total` and `gen_wind-ons` sum to the system
  value, and the Nuclear and Onshore Wind regional bars sum to the system bar.
- **(a') Floors:** every corridor is at or above its floor, and (a'') the system `tran_total` is at
  or above 34,478.6 MW.
- **(b) Cost identity:** cost_total equals the component sum, and the "System cost" line equals the
  sum of the cost bars.
- **(c) DistPV:** the DPV bar is 12,994.6 MW at Lo, Md and Hi demand and off-grid.
- **(d) CI panel:** it is populated.

In round 2, 48 of 52 passed. The 4 failures were MLP transmission: corridors predicted up to 543 MW
below their initial capacity. Since round 3 clips corridors to their floor before the rescale, MLP
corridors sum exactly to `tran_total` and none is below its floor. Results are in
`data/11_dashboard_check.json`.

**Live server (round 1).** `bokeh serve reeds_proxy.py` returned HTTP 200 with no errors in the log.

**Not tested:** a browser session, XGBoost in the dashboard (its artifacts cannot be unpickled
outside the training script, a pre-existing problem), and the GCP deployment.

## Decisions and flags

1. **Corridor floors.** For all 11 corridors, the minimum over the 486 runs equals the initial
   corridor capacity exactly. The initial capacity is (forward + reverse ITL) / 2 from
   `inputs/transmission/itl_NARIS.csv` for the `z134` zones, which is how `tran_out` is reported
   (`reeds/core/terminus/report.gms:1776`). See `data/12_corridor_floor_vs_init.csv`. The dashboard
   and the evaluation take floors from the training data (`transmission_floors`). In the
   cross-validation the floors include the held-out run, but they are input data (initial
   capacity), not a prediction.
2. **System value at or below the floor sum: corridors set to the floor.** This case is not in your
   spec. The formula gives s' = 0 when T equals the floor sum, and skipping would leave regional
   expansion that the system model does not predict. It happens in 27 RF runs, where T equals the
   floor sum to within 6e-6 MW of float32 round-off.
3. **Round-off tolerance (1e-6 relative).** Without it, RF values sitting exactly at a floor, rebuilt
   from float32 residuals, counted as "below the floor" and skipped the rescale.
4. **Mixed-sign guard kept.** Without it, regional R² collapses for models that predict mixed signs
   on signed quantities. Those are storage net generation and PTC payments, where the regional sum
   nearly cancels. Before the floor change, with the rule as you specified it, MLP regional mean R²
   was −13.97 and NGBoost 0.353. With the guard they were 0.004 and 0.557. RF is identical either
   way. Those comparisons are in `data/*_spec_exact_rule.csv`.
5. **Table III and the bucket and ranking figures use raw OOF scores** for all models, labelled that
   way in `results_after_fix.md`. Section D reports the constraint effect for RF only. The OneDrive
   figures were regenerated from the raw pipeline outputs under their old names. Their files match
   the August originals in size, so the folder is back to raw. The three IEEE figures in
   `analysis/pesgm/figs` also use the raw scores.
6. **Remaining side effects (RF).**
   - **CF ceiling:** the final count of regional predictions more than 1% above the observed maximum
     capacity factor is 993 of 29,519, against 796 of 29,658 without the constraint layer. Not fixed,
     per your decision.
   - **MLP rare H2:** the rescale can still put a spurious system H2 total into one region. This
     affects MLP only, not RF, and is outside Section D.
   - **MLP and Ridge transmission below the floor.** MLP and Ridge predict corridors below their
     initial capacity, unlike RF. Before any rescale, that happens for 1,144 of 4,860 MLP
     predictions and 1,022 of 4,860 Ridge predictions (Part 3). For those designs the transmission
     rescale is skipped and the values are left as predicted. One option, not implemented, is to
     raise corridors to their floor before the rescale, in the same step as the non-negativity clip.
     **Round 3 (approved): implemented.** Corridors are now clipped to their floor before the
     rescale. Predictions more than 1% below the floor, regional layer:

     | Model | Stored OOF (no rules) | Rules, before the floor clip | Rules, with the floor clip |
     |---|---|---|---|
     | MLP | 1,144 of 4,860 | 1,144 | 0 |
     | Ridge | 1,022 of 4,860 | 1,022 | 0 |
     | RF | 0 of 4,860 | 0 | 0 |

     No regional corridor prediction is below its floor by any amount after the rules. RF numbers
     are unchanged by the floor clip, because RF never predicts below a floor.
   - **System `tran_total` below the total initial capacity (round 4, approved: clipped).** The
     system prediction was more than 1% below 34,478.6 MW in 37 MLP runs and 90 Ridge runs, and in
     0 RF runs. Round 3 reported 74 and 180, but those counts covered two columns, `tran_total` and
     `tran_AC_total`. `tran_total` is now clipped to that floor, which brings the counts to 0 for all
     three models. The duplicate `tran_AC_total` is not clipped (37 MLP and 90 Ridge runs; see
     `known_limits.md`). RF results are unchanged.
7. **Dashboard artifacts needed no rebuild.** The constraint layer is applied in code. The constants
   come from the repo's `summary.json`, which is unchanged. The Evaluation tab still shows the
   pipeline's raw metrics, which is now consistent with Table III.
8. **OneDrive backup:** `_before_constraint_fix_2026-11-06` (46 files, 1.31 GB).
   `Final_Report.md:73` and `slides.html:146` there still describe the dGen curve and were not
   edited.
9. **Two API changes could break external callers.** `apply_constraints` lost `x_dem_value`, and
   `apply_dgen_distpv` was renamed `apply_constant_override`. `analysis/pesgm/09_constraints_check.py`
   relies on the removed DistPV function, so it no longer runs. It is kept as the record of the
   pre-fix check.
10. **Paper text.** In Section D and Table II:
    - **Rule order:** clipping now runs before the regional rescale.
    - **DistPV:** it is held constant, not set from a dGen curve.
    - **Rule 2:** it is now applied, and corridors are rescaled only above their initial capacity.
    - **RF numbers:** 0.29%, 355 of 486, 64%, and a 92.2% reduction in additivity violations.
      Regional mean / median R² goes from 0.625 / 0.715 to 0.632 / 0.714.

## Final state (round 4, the code freeze for the paper)

The four changes are:

1. **Floor-preserving regional rescale with the mixed-sign guard.**
2. **Clip to the known lower bound before the rescale:** 0 for most quantities, the initial
   capacity for corridors, and the sum of the corridor floors for the system `tran_total`.
3. **Cost identity on the OOF path.**
4. **DistPV held as a constant.**

Tests: 17 unit tests pass, and 56 of 56 dashboard checks pass. The remaining inconsistencies are
listed in `known_limits.md`; the code is not changed for them.
