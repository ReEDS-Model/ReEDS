## 4. Constraint and class-merging ablation (RF, 10-fold OOF, seed 42)

Without merging, the RF scored on the 86 per-class system outputs has mean / median R-squared 0.756 / 0.893 (41 outputs >= 0.9), and on the 382 per-class regional outputs 0.667 / 0.778 (113 >= 0.9); these are the pre-merge numbers in the repo's *_premerge folders and are not comparable to the merged numbers because the output sets differ.
Summing the per-class predictions to the merged quantities and scoring on the same 66 / 308 outputs gives 0.749 / 0.882 (system) and 0.625 / 0.715 (regional), versus 0.749 / 0.882 and 0.625 / 0.715 when the merged quantities are predicted directly, so merging changes the aggregate R-squared by +0.000 (system mean) and -0.000 (regional mean).
Non-negativity: the unconstrained merged RF produces 86 negative cells in 86 runs on the system layer (0.29 % of must-be-positive cells, 1 output affected: cost_op_h2_transport_intrareg) and 69 cells in 63 runs on the regional layer (0.05 %, 2 outputs: cost_op_h2_transport_intrareg_p60; cost_op_h2_transport_intrareg_p62); the train clip plus prediction clip removes all of them and moves the mean R-squared by -0.0000 (system) and -0.0000 (regional).
Configuration C scored against the pipeline's clipped targets is the draft number: mean / median 0.749 / 0.882 system and 0.625 / 0.715 regional; against the raw targets it is 0.749 / 0.882 and 0.625 / 0.715.
The DistPV dgen override has no measurable effect in cross-validation because cap_distpv is constant across all 486 runs and is dropped before fitting; it only changes predictions at off-grid demand values.
Cost identity: the directly predicted cost_total differs from the sum of predicted components by more than 1 % in 355 of 486 runs (median gap 2.28 %); deriving cost_total from the components removes the violation by construction and changes its R-squared from 0.8975 to 0.9117 and its MAE from 7.41 % to 6.81 % of the mean.
Additivity: before rescaling, the regional sums differ from the system prediction by more than 1 % in 14943 of 23544 (run, quantity) pairs (63.5 %; median gap 2.21 %) across 63 quantities present in both layers; rescaling removes them and changes the regional mean / median R-squared from 0.625 / 0.715 to 0.630 / 0.714 (1167 pairs remain because the rescale skips quantities whose regional sum or system prediction is not positive). Note the dashboard does not apply this rescale, so deployed regional predictions carry the pre-rescale inconsistency.

Ablation table:

| config | layer | n_outputs | r2_mean | r2_median | n_ge_0_9 | neg_cells | neg_runs | add_viol_pairs | add_pairs | cost_viol_runs | note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A | system | 86 | 0.756 | 0.893 | 41 | 86 | 86 |  |  | 355.000 | scored on 86 per-class outputs |
| A | regional | 382 | 0.667 | 0.778 | 113 | 69 | 63 | 14828.000 | 23549.000 |  | scored on 382 per-class outputs |
| A (summed to merged outputs) | system | 66 | 0.749 | 0.882 | 29 | 86 | 86 |  |  | 355.000 | per-class predictions summed |
| A (summed to merged outputs) | regional | 308 | 0.625 | 0.715 | 75 | 69 | 63 | 14828.000 | 23549.000 |  | per-class predictions summed |
| B | system | 66 | 0.749 | 0.882 | 29 | 86 | 86 |  |  | 355.000 |  |
| B | regional | 308 | 0.625 | 0.715 | 76 | 69 | 63 | 14953.000 | 23549.000 |  |  |
| C | system | 66 | 0.749 | 0.882 | 29 | 0 | 0 |  |  | 355.000 | train clip + predict clip |
| C | regional | 308 | 0.625 | 0.715 | 76 | 0 | 0 | 14943.000 | 23544.000 |  | train clip + predict clip |
| D | system | 66 | 0.749 | 0.882 | 29 | 0 | 0 |  |  | 355.000 | cap_distpv constant -> dropped; no CV effect |
| D | regional | 308 | 0.625 | 0.715 | 76 | 0 | 0 | 14943.000 | 23544.000 |  | no CV effect |
| E | system | 66 | 0.749 | 0.882 | 30 | 0 | 0 |  |  | 0.000 | cost_total := sum(components) |
| E | regional | 308 | 0.625 | 0.715 | 76 | 0 | 0 | 14943.000 | 23544.000 |  | no regional cost_total |
| F | system | 66 | 0.749 | 0.882 | 30 | 0 | 0 |  |  | 0.000 | unchanged |
| F | regional | 308 | 0.630 | 0.714 | 76 | 0 | 0 | 1167.000 | 23544.000 |  | regional rescaled to system prediction |
