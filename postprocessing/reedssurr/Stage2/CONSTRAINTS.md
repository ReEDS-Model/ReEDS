# ReEDS-Proxy constraint layer (Stage 2)

The surrogate models predict every output independently, so their raw predictions can break
physical rules. A prediction-time layer corrects them. This note says what it does, in which
order, and where it stops. The code is in `code/surrogate_constraints.py`, and the entry point
is `apply_constraints()`.

## Where it runs

- **Dashboard** (`code/reeds_proxy.py`, `_redraw`): every query, on both the final-model
  (off-grid) path and the out-of-fold (training-grid) path. On the regional layer it first
  predicts and constrains the system layer, then passes that result in as `overall_pred`.
- **Python API**: `surrogate_predict.predict()` and `surrogate_uq.prediction_interval()`.
- **Not in training metrics**: `summary.json`, `per_output_metrics_*.csv`, `eval/` and the
  dashboard's Evaluation tab score the raw out-of-fold predictions, with no constraints.

The only training-time step is a clip of the targets at 0 before fitting
(`clip_train_targets`, same columns as rule 2).

## The four rules, in order

Each rule sees the output of the rule before it.

1. **Hold constants.** Outputs that are identical in all 486 training runs are dropped before
   fitting. Their values are recorded in `summary.json["constant_outputs"]`, and they are set
   back to those values (`hold_constants`). For example, `cap_distpv` is the same in every run.
2. **Clip at the known lower bound** (`clip_predictions`). The bound is 0 for capacity,
   transmission, non-storage generation and cost columns. Storage generation and `*_negative`
   cost columns are exempt, because they can legitimately be negative. Transmission columns
   also have a floor (see below), and a value below its floor is raised to it.
3. **Regional additivity** (`enforce_additivity`, regional layer only). For each system-level
   quantity, the regional values are rescaled so that they sum to the system prediction:
   y' = f + s (y − f), where f is each region's floor.
   - Constant regions are held fixed, and their sum is subtracted from the system target.
   - Transmission corridors map to `tran_total`. Each interface counts once, whatever its
     direction.
   - If the target is at or below the sum of the floors, the values are set to their floors.
4. **Cost identity** (`derive_cost_total`). `cost_total` is replaced by the sum of the
   `cost_inv_*` and `cost_op_*` components.

## Floor sources

| Column | Floor | Source |
|---|---|---|
| Regional corridors `tran_pNN_pMM_AC` | Minimum over the 486 runs | `transmission_floors(training_df)` |
| System `tran_total` and `tran_AC_total` | Sum of the corridor floors (34,478.6 MW for ERCOT) | `system_transmission_floors` |
| All other non-negative columns | 0 | rule 2 |

ReEDS does not retire interzonal transmission. So the minimum over the runs equals the initial
corridor capacity, (forward + reverse ITL) / 2 as reported in `tran_out`. This was checked
exactly for all 11 corridors in `analysis/pesgm/12_corridor_floors.py`. `tran_AC_total`
equals `tran_total` in every run, because all corridors are AC.

## Mixed-sign guard and other skips in rule 3

The rescale is skipped for a quantity, and its regional values are left as they are, when:

- **A value is below its floor** by more than a 1e-6 relative tolerance. With a floor of 0,
  that means a negative value, such as storage net generation or PTC payments. With mixed
  signs, the sum of increments can be a near-cancelling small number, and the scale factor
  explodes.
- **The regional increments sum to 0 or less.** Then there is nothing to scale.
- **The target is 0 or less and the quantity has no floors.** The system predicts 0, so
  the regional values are left alone.
- **The scale factor is within 1e-6 of 1.** The values already agree.

## Known limits

The full list with counts is `analysis/pesgm/known_limits.md`. The open ones:

- **Capacity factor:** no rule ties generation to capacity. About 3% of regional predictions
  exceed the highest capacity factor seen in the runs.
- **Signed quantities:** the guard skips them, so their regional sums can differ from the
  system value. Examples are battery and pumped-hydro generation and PTC payments.
- **Rare technologies:** when the regional predictions are 0 but the system prediction is
  positive, or the other way round, additivity is not enforced.
- **Regional cost line:** the regional "System cost" total is the sum of the regional cost
  components. It can differ from the system-layer `cost_total`, and the dashboard labels it
  that way.
- **Rare-H2 amplification:** for the MLP, a spurious system H2 value can be rescaled into
  one region.
- **XGBoost monotone hints:** the hints in `_monotone_rules_for` point the wrong way for the
  fuel and siting dials. The deployed XGBoost is fitted without them. The training CLI still
  applies them unless `--no_monotone` is passed.
- **Not implemented:** an energy balance, a storage identity, joint projection across
  outputs, and special handling of sparse technologies.

## Tests

`tests/test_surrogate_constraints.py` covers each rule, the floors, the guard and the order.
`analysis/pesgm/11_dashboard_check.py` runs 56 end-to-end checks against the dashboard.
