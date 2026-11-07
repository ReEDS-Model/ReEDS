# XGBoost without monotone hints

Written by `18_xgb_nohints.py` on 2026-11-06 (reeds2 env).

**What was refitted:** only XGBoost, 10-fold out-of-fold (OOF) on both layers, with the pipeline's own `compute_oof_predictions` and its existing switch `disable_monotone_xgb=True`. Everything else is as stored: the same folds (KFold, shuffle, seed 42), 200 trees, depth 6, learning rate 0.1, one model per output, trained on the clipped targets. No Stage 2 code changed. No other model, stored artifact, constraint code or dashboard file was touched.

**Run time:** 20 s system and 77 s regional.

**Check that only the hints differ:** refitting the system layer the same way with the hints on reproduces the stored XGBoost OOF to within 4.6e-08 of each output's maximum, which is float32 storage precision (110 s).

**Files:** the new OOF predictions are `data/18_xgb_nohints_oof.npz`, with a copy named `xgb_nohints_oof.npz` beside `xgb.joblib` in each OneDrive models folder. The dashboard loads only `.joblib` files, so it does not see them. Per-output R²: `data/18_per_output_r2.csv`.

## 1. Raw OOF R², no constraints

| Layer | XGBoost | Mean R² | Median R² | Outputs with R² > 0.9 |
|---|---|---|---|---|
| system | with hints (stored) | 0.532 | 0.820 | 21 of 66 |
| system | no hints (refit) | 0.676 | 0.882 | 29 of 66 |
| regional | with hints (stored) | 0.241 | 0.484 | 42 of 308 |
| regional | no hints (refit) | 0.399 | 0.668 | 77 of 308 |

- **System outputs:** 26 improve and 3 get worse by more than 0.005 R². The largest gain is gen_gas-cc (-0.798 → 0.994). The largest loss is cost_inv_h2_production (-0.664 → -1.046).
- **Regional outputs:** 160 improve and 24 get worse by more than 0.005 R². The largest gain is gen_gas-cc_p67 (-1.041 → 0.976). The largest loss is cost_inv_h2_production_p61 (-0.367 → -2.527).

## 2. Bounds audit for XGBoost (same definitions as `results_after_fix.md` Part 3)

CF ceiling: predicted gen / (8760 × cap) more than 1% above the maximum over the 486 runs, for predictions with cap ≥ 1 MW, storage skipped. Below floor: transmission predictions more than 1% below the minimum over the 486 runs (regional: the corridors; system: `tran_total` and `tran_AC_total`).

| Layer | XGBoost | Predictions | CF ceiling exceedances | Transmission below floor |
|---|---|---|---|---|
| system | with hints (stored) | raw OOF | 585 of 7,653 | 52 of 972 |
| system | with hints (stored) | after constraint layer | 585 of 7,653 | 26 of 972 |
| system | no hints (refit) | raw OOF | 359 of 7,653 | 52 of 972 |
| system | no hints (refit) | after constraint layer | 359 of 7,653 | 26 of 972 |
| regional | with hints (stored) | raw OOF | 1,882 of 30,685 | 980 of 4,860 |
| regional | with hints (stored) | after constraint layer | 1,974 of 30,652 | 0 of 4,860 |
| regional | no hints (refit) | raw OOF | 1,138 of 30,726 | 980 of 4,860 |
| regional | no hints (refit) | after constraint layer | 1,472 of 30,693 | 0 of 4,860 |

Detail by technology and column: `data/18_bounds_audit.csv`.

## 3. Table III with XGBoost refitted without hints (raw OOF, no constraints)

The other six rows are the stored OOF scores, unchanged from `results_after_fix.md`.

| Model | System mean | System median | System > 0.9 | Regional mean | Regional median | Regional > 0.9 |
|---|---|---|---|---|---|---|
| Ridge | 0.445 | 0.449 | 3 | 0.308 | 0.259 | 0 |
| Lasso | 0.445 | 0.449 | 3 | 0.308 | 0.259 | 0 |
| k-NN | 0.595 | 0.695 | 7 | 0.452 | 0.536 | 1 |
| Random Forest | 0.749 | 0.882 | 29 | 0.625 | 0.715 | 76 |
| XGBoost (no hints) | 0.676 | 0.882 | 29 | 0.399 | 0.668 | 77 |
| MLP | 0.712 | 0.870 | 28 | 0.547 | 0.679 | 76 |
| NGBoost | 0.711 | 0.815 | 23 | 0.559 | 0.590 | 59 |

**RF against XGBoost without hints:** RF keeps the highest mean on both layers (0.7490 vs 0.6762 system, 0.6251 vs 0.3987 regional) and the highest regional median (0.7151 vs 0.6678). The system median is a tie at three decimals (RF 0.8819, XGBoost 0.8819). Outputs above 0.9: 29 vs 29 system and 76 vs 77 regional.

`figs/model_comparison` (PDF and PNG) was regenerated with these numbers. CSV: `data/18_table3_xgb_nohints.csv`.

**Not changed:** the stored `xgb.joblib` artifacts still have the hints, so the dashboard's XGBoost and the Table III in `results_after_fix.md` are as before.
