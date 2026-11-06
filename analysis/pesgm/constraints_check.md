# Constraint layer: code and data check for Section D / Table II

Branch `yc/reedssurr`. Code paths are relative to `postprocessing/reedssurr/Stage2/code/`.
The numbers come from `analysis/pesgm/09_constraints_check.py`, run in the `reeds2` env. The raw
tables are in `results_09.md` and the full results in `data/09_constraints_check.json`.

**Method.** The out-of-fold (OOF) predictions are random-forest (RF) predictions from 10-fold
cross-validation (seed 42), from `pesgm_common.rf_oof`. This reproduces the pipeline's
`compute_oof_predictions`. Two sets were fitted per layer:

- **P0** is trained on the raw targets.
- **P1** is trained on clipped targets, exactly as `load_data` produces them. P1 matches the
  pipeline's stored OOF predictions to float32 precision (largest relative difference 3.6e-8).

The prediction-time rules are applied with the code's own `apply_constraints`, row by row, using
the `Stage2InferenceConfig` switches. They are not re-implemented. System rows are constrained
first, then each regional row gets the constrained system row as `overall_pred`.

Units: capacity in MW, generation in MWh, cost in 2050 dollars from ReEDS `systemcost.csv`. The
dollar year is not stated in the extraction code (`Stage1/data_processing/build_overall.py:115-127`).

---

## Key findings

1. **Execution order:** DistPV override, then regional rescale, then clip, then cost identity.
   Clipping comes after rescaling. In the OOF predictions this never breaks a regional sum,
   because the forest trained on clipped targets never predicts a negative value.
2. **Training-time clipping is effectively a no-op.** It changes 4 cells, all in
   `cost_op_h2_transport_intrareg*`, by at most 3e-6 dollars. A random forest averages training
   targets, so with non-negative targets it cannot predict negatives. The prediction-time clip
   therefore also does nothing for the RF.
3. **Regional additivity is never applied anywhere.** It is off by default and nothing calls
   `enforce_additivity`. If switched on, the coded function has three defects:
   - It ignores regions dropped as constant columns. This inflates `cap_nuclear_p65`, giving a
     regional mean R² of −1349.
   - It does not match the transmission corridor columns.
   - It skips any quantity whose regional sum or system value is not positive.
4. **The DistPV override is dead code in `predict()`.** `cap_distpv` is constant in all 486 runs,
   so it is dropped before training and is never in the prediction vector. The override that
   takes effect is a separate one in the dashboard. It uses a placeholder ±5% linear curve, not a
   dGen lookup. Because the demand dial is a slider, the override also fires at Lo and Hi demand
   training points. There it moves `cap_distpv` 5% away from the ReEDS value.
5. **The cost identity holds exactly in the ReEDS data.** The largest relative gap is 8.2e-16.
   Summing the predicted components raises cost_total R² from 0.8975 to 0.9117. RMSE falls from
   $2.74B to $2.54B. The dashboard's OOF path skips this rule, so training-grid designs show the
   directly predicted total.
6. **The paper's 0.29%, 355-of-486 and 64% figures reproduce exactly. The 92% does not come from
   the code.** It came from a re-implementation in `04_ablation.py` that handles constant regions
   and transmission. With the code's own function, violations fall by 87% (14,937 to 1,976), and
   regional R² collapses.

---

## 1. Execution order at prediction time

The order is fixed in `surrogate_constraints.py:318-329`:

```python
# surrogate_constraints.py:318-329
    cfg = config or Stage2InferenceConfig()
    out = pred
    if cfg.apply_dgen_distpv and x_dem_value is not None and "cap_distpv" in out.index:
        out = out.copy()
        out["cap_distpv"] = dgen_distpv_cap_mw(x_dem_value)
    if cfg.apply_additivity and overall_pred is not None:
        out = enforce_additivity(out, overall_pred)
    if cfg.apply_non_negativity:
        out = clip_predictions(out)
    if cfg.apply_cost_decomposition:
        out = derive_cost_total(out)
    return out
```

The order is: (1) exogenous DistPV override, (2) regional rescaling, (3) non-negativity clip,
(4) cost identity. **Clipping runs after rescaling.**

Additivity is off by default:

```python
# surrogate_constraints.py:293-298
@dataclass
class Stage2InferenceConfig:
    apply_non_negativity: bool = True
    apply_additivity: bool = False   # requires overall_pred, so opt-in
    apply_dgen_distpv: bool = True
    apply_cost_decomposition: bool = True
```

**Call sites.** A repository-wide search finds no call to `enforce_additivity` and no use of
`apply_additivity` outside `surrogate_constraints.py`. The constraint module is used in three
places:

| Where | What runs | Code |
|---|---|---|
| Training (`load_data`) | `clip_train_targets` only, after constant columns are dropped | `surrogate_ml_models.py:318-334` |
| Cross-validation (`compute_oof_predictions`) | Nothing. The model is fitted on the already-clipped `Y`; OOF predictions are stored raw | `surrogate_ml_models.py:442`, `:658` |
| `predict()`: off-grid designs in the dashboard, and `surrogate_uq.prediction_interval` | `apply_constraints` with the default switches: DistPV (no-op, see Q4), clip, cost identity. No additivity | `surrogate_predict.py:111`; `surrogate_uq.py:65` |
| Dashboard, training-grid design (OOF path) | `clip_physical_bounds` only, then constants spliced in, then the DistPV override. **No cost identity** | `reeds_proxy.py:1817`, `:1825-1836` |
| `surrogate_eval.py` (reported metrics) | `apply_physical_clipping` (same clip rule) only | `surrogate_eval.py:360-386` |

```python
# surrogate_ml_models.py:331-334
    # STAGE 2: enforce non-negativity on training targets so the fitter
    # never sees an impossible negative in cap_* / tran_* / non-storage gen_*
    # / non-incentive cost_*.  Stage 1 clipped only at inference time.
    Y = clip_train_targets(Y, y_cols)
```

```python
# reeds_proxy.py:1813-1836 (abridged)
            oof_pred_vec = actual_vec - oof_residuals[row_idx]
            predicted = pd.Series(oof_pred_vec, index=y_cols, name="prediction_oof")
            ...
            predicted = clip_physical_bounds(predicted)
            used_oof = True
        else:
            predicted = predict(artifact, levels)
        ...
        predicted = _augment_predicted_with_constants(
            predicted, _active_layer_short()
        )
        ...
        if "cap_distpv" in predicted.index:
            dem_val = levels.get("Dem")
            if isinstance(dem_val, (int, float)) and not isinstance(dem_val, bool):
                predicted = predicted.copy()
                predicted["cap_distpv"] = dgen_distpv_cap_mw(float(dem_val))
```

**Does clipping after rescaling break the regional sum in the OOF predictions?** No. I applied all
four rules with additivity switched on, using P1. The clip changed **0 cells** after rescaling.
The forest trained on clipped targets predicts no negative values in any must-be-positive column,
on either layer.

**Additivity after all four rules (code as written).** Here S is the regional sum, including the
regions dropped as constants, and T is the system prediction.

| | pairs |
|---|---|
| All (run, quantity) pairs, 63 quantities × 486 runs | 30,618 |
| T = 0, so the relative gap is undefined | 7,082 |
| of which S ≠ 0, a real inconsistency hidden by the % metric | 1,464 |
| T ≠ 0 | 23,536 |
| **gap > 1%** | **1,976 (8.4%)** |

Causes of the 1,976 violations:

| Cause | pairs | Quantities |
|---|---|---|
| Rescale skipped because S ≤ 0 or T ≤ 0 (`surrogate_constraints.py:227`) | 1,165 | Mostly `gen_battery_li` (451), `gen_pumped-hydro` (356), `cost_op_ptc_payments_negative` (224). Then small counts in the H2 and CCS techs |
| Regions dropped as constants are not in the prediction, so they are not rescaled | 569 | `cap_nuclear` (486; p63 constant 2,400 MW), `cap_pumped-hydro` (83; p64 constant 5 MW) |
| Quantity not matched by the regional regex | 242 | `tran_total` (corridor columns end in `_AC`) |
| **Clipping after rescale** | **0** | |

The regex only matches a trailing region tag:

```python
# surrogate_constraints.py:185
_BA_RE = __import__("re").compile(r"_(p\d+|s\d+|r\d+)$", flags=__import__("re").IGNORECASE)
```

Regional transmission columns are named like `tran_p60_p61_AC`, so they are never grouped. The
raw ReEDS data does satisfy additivity for all 63 quantities, `tran_total` included. The largest
relative gap is 3.3e-6, on `cap_H2-CT`, and its absolute size is 2e-6 MW.

## 2. Training-time clipping: which targets are negative

Every column with at least one negative value in the 486 runs:

| layer | column | negative rows | min | must be ≥ 0? |
|---|---|---|---|---|
| system | gen_battery_li | 486 | −1.18e7 MWh | exempt |
| system | gen_pumped-hydro | 486 | −8.31e5 MWh | exempt |
| system | cost_op_co2_incentive_negative | 9 | −8.78e8 $ | exempt |
| system | cost_op_ptc_payments_negative | 231 | −2.79e9 $ | exempt |
| system | **cost_op_h2_transport_intrareg** | **2** | **−3e-6 $** | **yes** |
| regional | gen_battery_li_p60 / p61 / p62 / p63 / p64 / p65 / p67 | 466 / 475 / 311 / 482 / 447 / 486 / 463 | down to −6.61e6 MWh | exempt |
| regional | gen_pumped-hydro_p61 / p64 | 12 / 486 | −8.28e5 / −3.49e3 MWh | exempt |
| regional | cost_op_co2_incentive_negative_p67 | 9 | −8.78e8 $ | exempt |
| regional | cost_op_ptc_payments_negative_p60 … p67 (7 cols) | 35 to 221 | down to −1.28e9 $ | exempt |
| regional | **cost_op_h2_transport_intrareg_p60** | **1** | **−3e-6 $** | **yes** |
| regional | **cost_op_h2_transport_intrareg_p62** | **1** | **−1e-6 $** | **yes** |

**Plain answer.** Outside the exempt groups, the only negative targets are 4 cells of
`cost_op_h2_transport_intrareg`, with values between −1e-6 and −3e-6 dollars. That is solver
rounding. Training-time clipping changes those 4 cells and nothing else (2 system cells, 2
regional cells). It is a no-op in practice, and the paper should not present it as a
constraint that matters.

Without training-time clipping, the RF's OOF predictions contain 86 negative system cells and 69
negative regional cells. All of them are in this same column, and none is below −3.1e-7 dollars.
With clipped targets there are 0. The paper's motivating example, "negative capacity", never
occurs in the RF predictions. Other learners, such as the neural net or Ridge, can extrapolate
below zero, but they were not checked here.

## 3. Exempt groups

The rule is in `surrogate_constraints.py:54-82`. An identical copy is in
`surrogate_predict.py:121-171` (`clip_physical_bounds`). The script checks that both copies give
the same mask on every column of both layers.

```python
# surrogate_constraints.py:54-58
_STORAGE_GEN_PREFIXES = (
    "battery", "pumped-hydro", "pumped_hydro", "phs", "caes",
)
# Cost columns tagged as *_negative (ITC/PTC/CO2 incentives) legitimately negative.
_NEGATIVE_COST_MARKER = "_negative"
```

```python
# surrogate_constraints.py:72-82
def non_negative_mask(y_cols: Sequence[str]) -> np.ndarray:
    """Boolean mask over ``y_cols``: True where the column MUST be ≥ 0."""
    mask = np.zeros(len(y_cols), dtype=bool)
    for i, c in enumerate(y_cols):
        if c.startswith(("cap_", "tran_")):
            mask[i] = True
        elif c.startswith("gen_") and not _is_storage_gen(c):
            mask[i] = True
        elif c.startswith("cost_") and not _is_negative_cost(c):
            mask[i] = True
    return mask
```

These name patterns select the exempt columns:

- **Storage net generation:** the name starts with `gen_`, and the rest, lower-cased, starts with
  `battery`, `pumped-hydro`, `pumped_hydro`, `phs` or `caes`.
- **Incentive costs:** the name starts with `cost_` and contains `_negative`, case-insensitive.
- **Anything without a `cap_`, `tran_`, `gen_` or `cost_` prefix** is also left unclipped.

Exempt columns in the data:

| layer | columns | reason |
|---|---|---|
| system | gen_battery_li, gen_pumped-hydro | storage net generation |
| system | cost_inv_itc_payments_negative, cost_op_co2_incentive_negative, cost_op_ptc_payments_negative | `_negative` cost |
| system | runtime_seconds | no prefix (not an energy quantity) |
| regional | gen_battery_li_p60, _p61, _p62, _p63, _p64, _p65, _p67; gen_pumped-hydro_p61, _p64 | storage net generation |
| regional | cost_inv_itc_payments_negative_p63; cost_op_co2_incentive_negative_p67; cost_op_ptc_payments_negative_p60, _p61, _p62, _p63, _p64, _p65, _p67 | `_negative` cost |

That makes 60 of the 66 modelled system columns must-be-positive, and 290 of the 308 regional ones.

## 4. Exogenous DistPV

**(a) Constant or varying?** `cap_distpv` is **identical in all 486 runs**: 12,994.628099 MW at
every demand level. Each regional `cap_distpv_pNN` is also constant, and they sum to the same
12,994.628 MW. `gen_distpv` is **not** constant. It takes 9 distinct values (25.7 to 30.0 TWh) and
is modelled by the RF.

**(b) Removed or trained and overridden?** It is removed, but only by the generic zero-variance
filter, not by any DistPV-specific rule:

```python
# surrogate_ml_models.py:318-328 (abridged)
    y_var = Y.var(axis=0)
    valid_mask = y_var > config.min_variance_threshold
    ...
            constants[y_cols[i]] = float(Y[:, i].mean())
    ...
    Y = Y[:, valid_mask]
```

As a result, the override inside `apply_constraints` (`surrogate_constraints.py:320`, guarded by
`"cap_distpv" in out.index`) **never fires**: `predict()` returns only modelled columns. The
override that takes effect is the separate one in the dashboard. It runs after the constants are
spliced back in (`reeds_proxy.py:1825-1836`, quoted in Q1).

**(c) Formula:**

```python
# surrogate_constraints.py:250-256
DGEN_DISTPV_MED = 12994.628
DGEN_DISTPV_SLOPE_PER_UNIT_DEM = 0.05 * DGEN_DISTPV_MED   # +5% per +1 in x_Dem

def dgen_distpv_cap_mw(x_dem_value: float) -> float:
    """Return exogenous cap_distpv (MW) for a given continuous x_Dem value."""
    return float(DGEN_DISTPV_MED + DGEN_DISTPV_SLOPE_PER_UNIT_DEM * (float(x_dem_value) - 1.0))
```

The formula is `cap_distpv = 12,994.628 × (1 + 0.05 × (x_Dem − 1))` MW, with x_Dem from 0 (Lo) to
2 (Hi). That gives 12,344.9, 12,994.6 and 13,644.4 MW at Lo, Md and Hi demand. The code comment
(`surrogate_constraints.py:242-249`) calls it a "very simple placeholder" and says to replace it
with a dGen lookup when available. It is not a dGen output.

Consequences:

- **The override fires at training points too.** The dashboard's Dem dial is always a numeric
  slider (`reeds_proxy.py:517`), so the override runs on training-grid designs as well. At Lo and
  Hi demand it shows ±5% where ReEDS has 12,994.6 MW.
- **Only system capacity is overridden.** On the regional layer, the `cap_distpv_pNN` values stay
  at their constants, so their sum no longer equals the overridden system value.
- **Generation does not follow capacity.** `gen_distpv` comes from the model and is not tied to
  the overridden capacity.

**(d) Other exogenous outputs.** No other output has an override rule. The dashboard splices in
every dropped zero-variance column as a fixed constant (`reeds_proxy.py:260-280`), with no demand
scaling:

- **System:** cap_hydED 142 MW, cap_hydEND 405.8 MW, cap_lfill-gas 24.4 MW, and four columns that
  are always 0 (gen_Gas-CT_H2-CT, gen_coal-igcc, gen_coal-new, gen_wind-ofs).
- **Regional:** 57 constant columns, 18 of them non-zero. These include cap_nuclear_p63 at
  2,400 MW and tran_p63_p64_AC at 6,539 MW.

## 5. Cost identity

**(a) The 21 components summed** (`surrogate_constraints.py:263`, prefixes
`("cost_inv_", "cost_op_")`). None of them is dropped as a constant:

cost_inv_h2_production, cost_inv_h2_storage, cost_inv_investment_capacity_costs,
cost_inv_investment_refurbishment_capacity, cost_inv_investment_spurline_costs_rsc_technologies,
cost_inv_itc_payments_negative, cost_inv_transmission_interzone_ac_investment,
cost_inv_transmission_intrazone_investment, cost_op_co2_incentive_negative,
cost_op_co2_transport_storage, cost_op_consume_fom, cost_op_fom_costs, cost_op_fuelcosts_objfn,
cost_op_h2_storage, cost_op_h2_transport_intrareg, cost_op_ptc_payments_negative,
cost_op_spurline_fom, cost_op_startcost, cost_op_transmission_fom,
cost_op_transmission_intrazone_fom, cost_op_vom_costs.

```python
# surrogate_constraints.py:272-286
def derive_cost_total(pred: pd.Series) -> pd.Series:
    ...
    comps = cost_component_cols(pred.index)
    if not comps:
        return pred
    total = float(pred[comps].sum())
    out = pred.copy()
    out[_COST_TOTAL] = total
    return out
```

On a regional prediction, `derive_cost_total` *appends* a `cost_total` entry equal to the sum of
the regional cost columns. This was observed in the check. It does not affect any scored column.

**(b) Does it hold in the data?** Yes. ReEDS's `cost_total` is built as the sum of every
`systemcost.csv` row for 2050 (`build_overall.py:126`). The largest discrepancy against the
21-component sum is **1.5e-5 dollars absolute and 8.2e-16 relative**. After training-time
clipping the largest absolute gap is still 1.5e-5 dollars.

**(c) Direct versus summed prediction** (RF OOF, 486 runs; mean cost_total is $26.2B):

| | R² | RMSE ($B) | MAE ($B) |
|---|---|---|---|
| cost_total predicted directly | 0.8975 | 2.738 | 1.942 |
| sum of 21 predicted components | **0.9117** | **2.541** | **1.785** |

The values are the same, to the digits shown, for P0 and for P1 with the clip.

## 6. Ablation numbers

### The four numbers in the paper, reproduced

| Paper number | Reproduced | How it was computed |
|---|---|---|
| Negative values in 0.29% of must-be-positive system cells | 86 / 29,160 = **0.295%** | P0 (trained on raw targets, no clip). System layer: the 60 must-be-positive modelled columns × 486 runs. A cell counts if the prediction is < 0. All 86 cells are in `cost_op_h2_transport_intrareg`, one per run, all ≥ −3.0e-7 dollars. |
| cost_total off by > 1% in 355 of 486 runs | **355 / 486** (median gap 2.28%) | Stored pipeline OOF + prediction clip (`04_ablation.py` configuration C). Per run, \|Σ 21 predicted components − predicted cost_total\| / \|predicted cost_total\| > 0.01. |
| Regional sums off by > 1% in 64% of run-quantity pairs | 14,943 / 23,544 = **63.5%** (median gap 2.21%) | Configuration C on both layers. The 63 quantities come from `pesgm_common.regional_groups`: the `_pNN` suffix plus transmission corridors mapped to `tran_total`. S = Σ modelled regional predictions + dropped-constant regional columns; T = system prediction. Violation if \|S−T\|/\|T\| > 0.01. **The 7,074 pairs with T = 0 are excluded from the denominator.** 1,458 of those have S ≠ 0. |
| Additivity violations fall by 92% | 1 − 1,167/14,943 = **92.2%** | Rescaling with `04_ablation.enforce_additivity_matrix`, **a re-implementation, not the code's `enforce_additivity`**. It subtracts the constant regional columns from the target, it includes `tran_total`, and it does not clip afterwards. System side: clip + cost identity. |

### Cumulative ablation in the paper's order, with the code's own `apply_constraints`

The rules are added in the paper's order. Within each configuration, the enabled rules run in the
code's order from Q1. "none" uses P0 with no rules. The other rows use P1, which includes the
training clip. R² is against the raw ReEDS targets: 66 system outputs and 308 regional outputs.
The additivity metric is the one from the 64% row above.

| Rules | System R² mean / median | Regional R² mean / median | cost_total R² | Negative system cells | cost_total > 1% off (runs) | Regional sum > 1% off (pairs) |
|---|---|---|---|---|---|---|
| none | 0.7490 / 0.8819 | 0.6251 / 0.7151 | 0.8975 | 86 (0.29%) | 355 | 14,953 / 23,549 (63.5%) |
| +1 non-negativity | 0.7490 / 0.8819 | 0.6251 / 0.7151 | 0.8975 | 0 | 355 | 14,937 / 23,536 (63.5%) |
| +1, 2 additivity | 0.7490 / 0.8819 | **−1348.8** / 0.7137 | 0.8975 | 0 | 355 | 1,976 / 23,536 (8.4%) |
| +1, 2, 3 DistPV | 0.7490 / 0.8819 | −1348.8 / 0.7137 | 0.8975 | 0 | 355 | 1,976 / 23,536 (8.4%) |
| all four | 0.7492 / 0.8819 | −1348.8 / 0.7137 | 0.9117 | 0 | 0 | 1,976 / 23,536 (8.4%) |

For comparison, the paper's figures come from the `04_ablation.py` re-implementation of rule 2.
It gives regional R² 0.630 / 0.714 with 1,167 / 23,544 violations.

**Which rules change R² by more than 0.005:**

- **Rules 1 and 3:** no output's R² changes by more than 5e-6.
- **Rule 4:** only cost_total changes, by +0.014. The system mean moves by +0.0002.
- **Rule 2 as coded:** 162 regional outputs change by more than 0.005 (88 worse, 74 better).
  `cap_nuclear_p65` drops from −0.36 to −415,618. The function scales p65 up to the full system
  nuclear total, but p63 is a constant 2,400 MW that is not part of the prediction vector.
  Leaving out the two broken outputs (`cap_nuclear_p65`, `cap_pumped-hydro_p61`), the mean over
  the other 306 regional outputs goes from 0.6285 to 0.6351, and the median from 0.7173 to 0.7144.

## 7. Regional additivity edge cases

The skip condition is at `surrogate_constraints.py:227`:

```python
        if current <= 0 or target <= 0:
            continue
```

Here `current` is the sum of the modelled regional predictions, and `target` is the system
prediction after the system rules.

**8,885 of 30,618 run-quantity pairs skip the rescale.** They split as follows:

| Split | pairs | Meaning |
|---|---|---|
| T = 0 and S = 0 | 5,618 | harmless; the technology is not built |
| T = 0 and S ≠ 0 | 1,464 | inconsistent, and hidden by the relative-gap metric. The median \|S\| is 653 in the quantity's own unit (MW, MWh or $); the largest is 6.9e6 $, in `cost_op_h2_transport_intrareg` |
| T ≠ 0 | 1,803 | 1,165 of these exceed the 1% gap |

Of the 8,885, 2,376 belong to the five quantities that are negative by definition
(`gen_battery_li`, `gen_pumped-hydro`, `cost_op_ptc_payments_negative`,
`cost_op_co2_incentive_negative`, `cost_inv_itc_payments_negative`).

Skipped pairs by quantity:

| quantity | skipped | of which regional sum ≤ 0 | of which system ≤ 0 | > 1% violations |
|---|---|---|---|---|
| gen_battery_li | 486 | 486 | 486 | 451 |
| gen_pumped-hydro | 486 | 486 | 486 | 356 |
| cost_op_ptc_payments_negative | 486 | 486 | 486 | 224 |
| cost_op_co2_incentive_negative | 486 | 486 | 486 | 0 |
| cost_inv_itc_payments_negative | 432 | 432 | 432 | 0 |
| cap_Gas-CC_Gas-CC-CCS_mod | 421 | 421 | 421 | 0 |
| gen_Gas-CC_Gas-CC-CCS_mod | 418 | 418 | 418 | 0 |
| cap_nuclear-smr / gen_nuclear-smr | 409 / 409 | 409 / 409 | 409 / 409 | 0 |
| cap_pumped-hydro | 395 | 395 | 0 | 1 |
| cap_hydUD / gen_hydUD | 358 / 358 | 358 / 358 | 358 / 358 | 0 |
| cost_inv_h2_production | 353 | 310 | 340 | 13 |
| cost_inv_h2_storage | 327 | 263 | 315 | 12 |
| cap_Gas-CC_H2-CC / gen_Gas-CC_H2-CC | 315 / 296 | 221 / 218 | 311 / 287 | 4 / 9 |
| cap_H2-CC / gen_H2-CC | 275 / 275 | 159 / 158 | 251 / 252 | 24 / 23 |
| cost_op_consume_fom | 266 | 128 | 256 | 10 |
| cap_electrolyzer | 266 | 127 | 257 | 9 |
| cap_H2-CT / gen_H2-CT | 262 / 261 | 161 / 157 | 254 / 256 | 8 / 5 |
| cost_op_h2_storage | 255 | 110 | 244 | 11 |
| cap_gas-cc-ccs_mod / gen_gas-cc-ccs_mod | 245 / 176 | 190 / 141 | 243 / 176 | 2 / 0 |
| cost_op_h2_transport_intrareg | 50 | 3 | 50 | 0 |
| cost_inv_transmission_interzone_ac_investment | 42 | 16 | 41 | 1 |
| gen_CoalOldScr | 19 | 2 | 19 | 0 |
| cap_CoalOldScr_coal-CCS_mod / gen_CoalOldScr_coal-CCS_mod | 12 / 12 | 4 / 4 | 11 / 11 | 1 / 1 |
| gen_coal-ccs_mod / cap_coal-ccs_mod | 12 / 11 | 12 / 11 | 12 / 11 | 0 |
| cap_CoalOldScr | 6 | 1 | 6 | 0 |
| cost_inv_investment_spurline_costs_rsc_technologies | 5 | 0 | 5 | 0 |

`cap_pumped-hydro` is skipped because the modelled region, p61, is predicted as 0. The constant
5 MW in p64 is outside the prediction vector. All other skips occur because the technology is not
built (zero) or the quantity is negative by definition.

---

## Corrected Table II (matches the code as it stands)

| # | Rule | Applies to | How and when enforced |
|---|---|---|---|
| 1 | Non-negativity | Columns starting `cap_`, `tran_`, `gen_` (except storage: battery, pumped-hydro) and `cost_` (except `*_negative` incentive terms). That is 60 of the 66 system outputs and 290 of the 308 regional outputs | Training targets are clipped at 0 before fitting. In this data that changes 4 cells by ≤ 3e-6 dollars. Predictions are clipped at 0 after prediction. For the random forest this never binds. |
| 2 | Regional additivity | Regional `_pNN` columns whose system-level counterpart is modelled (62 quantities; transmission corridors not matched) | Implemented as a post-hoc rescale (`enforce_additivity`) but **off by default and never called**. It is not applied to deployed predictions or to any reported R². |
| 3 | Exogenous distributed PV | System `cap_distpv` only | Constant in all 486 runs, so dropped before training by the zero-variance filter. The dashboard sets it after prediction to 12,994.6 × (1 + 0.05 (x_Dem − 1)) MW. This is a placeholder linear curve, not a dGen lookup. Regional `cap_distpv_pNN` stay constant, and `gen_distpv` is predicted by the model. |
| 4 | Cost identity | `cost_total` = sum of the 21 `cost_inv_*` / `cost_op_*` components | Prediction time only, as the last step, inside `predict()` (off-grid designs). Not applied on the dashboard path for training-grid designs. |

If the paper is to keep "four rules enforced at prediction time", the code needs two changes,
which I have not made:

- **Fix `enforce_additivity`.** Subtract the constant regional columns from the target, and match
  the `_AC` corridor names to `tran_total`.
- **Turn it on.** Call it in the dashboard, and apply the cost identity on the OOF path too.

Otherwise, Table II should describe rule 2 as an optional consistency step evaluated offline,
using the corrected re-implementation numbers. It should describe rule 1 as a safeguard that
never binds for the RF.
