# ReEDS surrogate (ReEDS-Proxy) - PESGM supporting analysis

All numbers below were produced by the scripts in this folder from the stored
Stage 2 training tables (`postprocessing/reedssurr/Stage2/inputs/*_ml_numeric_merged.csv`),
the stored model artefacts (OneDrive `reedssurr_models/Stage2/<layer>/models/*.joblib`,
which carry the 10-fold out-of-fold residuals) and the Stage 2 surrogate code.
No ReEDS run was repeated. Random seed 42 and the same `KFold(10, shuffle=True)`
split as the pipeline are used throughout; the re-computed RF out-of-fold
predictions match the stored residuals to float32 precision (NGBoost is not
bit-reproducible because its tree learner is unseeded, but its aggregate R-squared is).
Environment: conda env `reeds2` (Python 3.11, scikit-learn 1.2.2, xgboost 3.2.0,
ngboost 0.5.8), 14 logical cores.

Scripts: `00_pipeline_summary.py` ... `07_regional.py` (one per item), `08_ercot_map.py`
(map of the seven ERCOT BAs, `figs/fig08_ercot_bas`), shared
helpers in `pesgm_common.py`, this assembler in `build_results.py`.
Figures are in `figs/` as PDF and 300-dpi PNG (3.5 in wide, 8 pt Arial,
no titles, colour-blind-safe palette); tables and per-output values are in `data/`.

## Where the results contradict or qualify the draft

- **Coverage.** The draft's split-conformal 90 % band is calibrated and
  evaluated on the same residuals in the existing code, so any coverage
  number taken from `surrogate_eval` (89.9-91.2 %) is circular. The honest
  cross-fold number is in item 1. The RF conformal band is in fact well calibrated
  (90.2 % cross-fold); the NGBoost native interval is slightly under-covered
  (88-89 %) and the conformal correction reported there fixes it.
- **"Four domain constraints".** The constraints module implements five; for
  the RF surrogate the paper reports, only three act at inference
  (non-negativity, DistPV override, cost decomposition). The regional
  additivity rescale is implemented but never called by the dashboard, and the
  monotone hints apply to XGBoost only. See items 0, 4 and 7.
- **Output count.** One of the 66 system outputs is `runtime_seconds` (ReEDS
  solve time), so 65 are energy-system quantities.
- **No hyperparameter search.** All model hyperparameters are fixed constants
  in the code; there is no grid.
- **Extrapolation.** Leave-one-level-out (item 3) shows the RF cannot
  extrapolate to an unsampled dial level or interpolate the middle level from
  the two outer ones; the continuous dashboard sliders therefore interpolate
  tree plateaus, not physics.
- **Inference latency.** The deployed RF artefact takes seconds, not
  milliseconds, per single-design prediction on Windows because of joblib
  multiprocess dispatch inside `MultiOutputRegressor` (item 0). Any
  "speed-up" figure should be stated with the measured latency.
- The headline R-squared values in the draft (RF system 0.75 / 0.88, regional
  0.63 / 0.72) are reproduced exactly and are not contradicted.


## 0. Pipeline summary (what the code actually does)

The training table has 486 rows (one per ReEDS run, the full 3^5 x 2 factorial) and 81 columns in the system file (372 in the regional file): a case name, 6 dial columns, and 74 (365) output columns; every output is the 2050 value only, no other solve years are included.
Dials are ordinal integers: Dem, Fuel, REcost, Batt and Siting are coded 0/1/2 (Lo/Md/Hi, or Open/Ref/Lim for Siting) and Pol is 0/1 (IRA/OBBBA); they are standardised inside each fold and the dashboard feeds non-integer slider values to the same encoding.
Dropping zero-variance outputs removes 8 system columns (cap_distpv, cap_hydED, cap_hydEND, cap_lfill-gas, gen_Gas-CT_H2-CT, gen_coal-igcc, gen_coal-new, gen_wind-ofs) and 57 regional columns, leaving 66 system and 308 regional modelled outputs; the 66 system outputs include runtime_seconds, which is a ReEDS solve time, not an energy-system quantity.
System outputs by category: {'gen': 22, 'cost': 22, 'cap': 19, 'tran': 2, 'runtime': 1}; regional: {'cost': 126, 'gen': 91, 'cap': 81, 'tran': 10} (regional cost columns are per-BA cost components, there is no regional cost_total).
Hyperparameters are fixed, there is no grid search or tuning loop in the code: RF n_estimators=200, max_depth=None, min_samples_leaf=2; XGBoost n_estimators=200, max_depth=6, learning_rate=0.1 with per-output monotone constraints; MLP hidden (64, 32), relu, adam, alpha=1e-3, max_iter=3000, no early stopping; Ridge alpha=1.0; Lasso alpha=0.1; k-NN k=3 distance-weighted; NGBoost n_estimators=200, learning_rate=0.05, Normal distribution.
The random seed is 42 everywhere (KFold shuffle, RF, XGB, MLP, NGBoost); the CV is 10-fold with shuffle, and every model family is wrapped in MultiOutputRegressor so one independent model is fitted per output.
Reported R-squared values are computed on the raw out-of-fold predictions before any constraint is applied (no clipping, no cost decomposition, no additivity), and NN/NGBoost targets are standardised per fold.
The 90 % interval for RF (and every non-NGBoost model) is split-conformal: the dashboard adds +/- the 0.90 quantile of |OOF residual| per output (symmetric band, from surrogate_uq.conformal_widths) around the point prediction; for NGBoost the native interval is mean +/- 1.645 sigma from the predicted Normal, de-standardised with the training-set scaler.
The existing coverage check in surrogate_eval and the Stage 1 status note (89.9-91.2 % coverage) evaluate the conformal band on the same OOF residuals used to set its width, so that number is circular and cannot be cited as empirical coverage; item 1 below replaces it.
Each ERCOT ReEDS run took 46.6 min on average (median 46.3, range 37-63 min) according to runtime_seconds.
The cost identity holds exactly in the training data: the 21 cost_inv_* and cost_op_* components sum to cost_total with max relative error 8.2e-16.

**Claims in the draft the code does not support**

- 'Four domain constraints': surrogate_constraints.py implements five (non-negativity, XGB monotone hints, regional-to-system additivity, dgen DistPV curve, cost decomposition). For the RF surrogate that the paper reports, only three are actually applied at inference: non-negativity clip, the DistPV override, and cost decomposition. The additivity rescale is implemented but not called anywhere in the dashboard (reeds_proxy.py) or in surrogate_predict.predict, and the monotone hints only exist for XGBoost.
- The 'dgen curve' for DistPV is a hand-set placeholder (a linear +/-5 % per demand level around the constant 12,994.6 MW), not a dGen output; cap_distpv is constant across all 486 runs so this cannot be validated from the data.
- None of the constraints enter the training objective except the non-negativity clip of the targets, which changes only one modelled column (cost_op_h2_transport_intrareg, negative in 2 runs); storage gen_* and *_negative cost columns are exempt.
- If the draft says '66 system outputs' are energy-system quantities, note that one of them is runtime_seconds; the energy-system count is 65.
- The XGBoost artefacts (overall and regional xgb.joblib) were pickled while surrogate_ml_models.py ran as __main__, so their MonotoneXGBMultiOutput wrapper cannot be unpickled by any other script (AttributeError on MonotoneXGBMultiOutput in __main__); the dashboard and surrogate_eval therefore cannot load the XGB model unless the class is aliased into __main__ first. This script does that alias for the timing below.
- The headline R-squared values (RF system mean 0.749 / median 0.882; regional 0.625 / 0.715) reproduce exactly from the stored residuals and from a fresh re-run with seed 42, so those are fine.

**Training and single-design inference time (this machine, 14 logical cores, env reeds2)**

| layer | model | display | n_outputs | train_s | predict_single_ms | predict_batch486_ms | artifact_predict_ms | artifact_predict_njobs1_ms |
|---|---|---|---|---|---|---|---|---|
| system | knn | k-NN (k=3, baseline) | 66 | 5.40 | 208.30 | 247.79 | 226.77 | 68.52 |
| system | ridge | Ridge Regression | 66 | 0.18 | 164.87 | 176.87 | 158.60 | 12.89 |
| system | lasso | Lasso Regression | 66 | 0.17 | 157.61 | 179.81 | 164.88 | 17.83 |
| system | rf | Random Forest | 66 | 7.77 | 2624.00 | 2063.73 | 3014.61 | 559.35 |
| system | xgb | XGBoost (Gradient Boosting, monotone) | 66 | 19.48 | 86.03 | 140.96 | 70.21 |  |
| system | nn | Neural Network (MLP (64, 32)) | 66 | 14.17 | 281.38 | 245.13 | 267.95 | 12.69 |
| system | ngboost | NGBoost (distributional, UQ-native) | 66 | 37.10 | 6303.95 | 5782.09 | 7307.97 | 3993.65 |
| regional | knn | k-NN (k=3, baseline) | 308 | 0.55 | 498.69 | 417.46 | 291.60 | 121.10 |
| regional | ridge | Ridge Regression | 308 | 1.79 | 212.19 | 236.33 | 192.73 | 31.11 |
| regional | lasso | Lasso Regression | 308 | 0.24 | 222.55 | 262.26 | 614.22 | 38.57 |
| regional | rf | Random Forest | 308 | 97.13 | 15905.91 | 17670.43 | 16449.20 | 3690.66 |
| regional | xgb | XGBoost (Gradient Boosting, monotone) | 308 | 130.39 | 419.00 | 696.77 | 377.52 |  |
| regional | nn | Neural Network (MLP (64, 32)) | 308 | 89.56 | 1924.60 | 1900.27 | 856.20 | 39.40 |
| regional | ngboost | NGBoost (distributional, UQ-native) | 308 | 92.06 | 22034.75 | 23086.38 | 23456.70 | 13216.40 |

The regional k-NN and MLP artefact timings were re-measured in a separate run because the first pass recorded a multi-minute stall (OneDrive / worker-pool hiccup) that did not reproduce.
artifact_predict_ms is the dashboard path (unpickled MultiOutputRegressor(n_jobs=-1) + constraint stack); predict_single_ms is the same model object right after fitting; artifact_predict_njobs1_ms is the same artefact with the per-output dispatch forced in-process. predict_batch486_ms is one call for all 486 designs.
The deployed RF needs 3.0 s per single-design prediction on the system layer and 16.4 s on the regional layer with the pipeline's n_jobs=-1 dispatch, versus 0.56 s and 3.69 s in-process; a batch of all 486 designs takes 2.1 s (system), so the per-call overhead, not the trees, sets the latency. Against a 47-minute ReEDS run the speed-up is about 927x as deployed and 4,996x in-process (system layer).

## 1. Interval calibration (10-fold OOF, seed 42)

The RF out-of-fold predictions used here reproduce the stored residuals exactly (max relative difference 9.4e-07 of the output std). NGBoost had to be re-run to obtain the predicted sigma; its default tree learner is unseeded (random_state=None), so individual predictions differ from the stored run (max relative difference 0.44 std) while the aggregate accuracy is unchanged: re-run mean / median R-squared 0.7109 / 0.8149 (system) and 0.5589 / 0.5898 (regional) versus stored 0.7107 / 0.8147 and 0.5588 / 0.5898.
**system layer (66 outputs)**

The deployed RF split-conformal 90 % band, calibrated on the other nine folds and evaluated on the held-out fold, covers the true value in 90.2 % of held-out runs on average across outputs (median 89.9 %, range 89.3-100.0 %); 97 % of outputs are within 5 points of nominal.
At 50/80/95 % nominal the RF conformal band covers 56.3/80.9/95.0 %.
The in-sample number the existing eval code reports for the same band is 90.3 % at 90 % nominal; it is circular (width and coverage from the same residuals) and should not be cited.
The RF-native per-tree 5-95 % quantile band is badly under-covered: 85.9 % mean coverage at 90 % nominal (64.5/80.2/89.3 % at 50/80/95 %), which is why the conformal wrapper is needed.
The NGBoost native Normal 90 % interval covers 88.2 % on average (median 88.6 %, 5 % of outputs under-covered by more than 10 points); at 50/80/95 % it covers 48.4/78.1/93.3 %.
A split-conformal correction of the NGBoost sigma (cross-fold quantile of |residual|/sigma replacing z) restores 89.8 % coverage at 90 % nominal (50.1/79.8/94.8 % at 50/80/95 %).
Sharpness at 90 %: median half-width / std(y) is 0.29 for RF conformal, 0.24 for the RF per-tree band and 0.41 for NGBoost native.
Most under-covered outputs for the RF conformal 90 % band: cost_inv_itc_payments_negative (89 %), gen_wind-ons (90 %), gen_H2-CT (90 %), gen_battery_li (90 %), gen_CoalOldScr (90 %). Most over-covered: gen_distpv (100 %), gen_hydEND (100 %), cap_nuclear (93 %), cap_gas-cc-ccs_mod (90 %), cost_inv_transmission_intrazone_investment (90 %).
Most under-covered outputs for the NGBoost native 90 % band: gen_wind-ons (78 %), cost_op_fom_costs (80 %), cost_op_vom_costs (80 %), gen_upv (80 %), cap_wind-ons (81 %).

**regional layer (308 outputs)**

The deployed RF split-conformal 90 % band, calibrated on the other nine folds and evaluated on the held-out fold, covers the true value in 90.2 % of held-out runs on average across outputs (median 89.9 %, range 89.1-100.0 %); 97 % of outputs are within 5 points of nominal.
At 50/80/95 % nominal the RF conformal band covers 57.2/80.9/95.0 %.
The in-sample number the existing eval code reports for the same band is 90.3 % at 90 % nominal; it is circular (width and coverage from the same residuals) and should not be cited.
The RF-native per-tree 5-95 % quantile band is badly under-covered: 87.9 % mean coverage at 90 % nominal (68.2/82.6/91.1 % at 50/80/95 %), which is why the conformal wrapper is needed.
The NGBoost native Normal 90 % interval covers 89.4 % on average (median 90.3 %, 1 % of outputs under-covered by more than 10 points); at 50/80/95 % it covers 49.8/79.9/94.1 %.
A split-conformal correction of the NGBoost sigma (cross-fold quantile of |residual|/sigma replacing z) restores 89.8 % coverage at 90 % nominal (50.2/79.9/94.7 % at 50/80/95 %).
Sharpness at 90 %: median half-width / std(y) is 0.44 for RF conformal, 0.30 for the RF per-tree band and 0.49 for NGBoost native.
Most under-covered outputs for the RF conformal 90 % band: cost_op_h2_transport_intrareg_p63 (89 %), cap_gas-cc_p63 (89 %), cap_H2-CT_p61 (89 %), cost_op_fom_costs_p60 (89 %), cap_H2-CT_p63 (89 %). Most over-covered: gen_hydEND_p63 (100 %), gen_hydEND_p65 (100 %), gen_distpv_p62 (100 %), gen_distpv_p63 (100 %), gen_distpv_p64 (100 %).
Most under-covered outputs for the NGBoost native 90 % band: cap_upv_p65 (78 %), cap_gas-cc_p63 (78 %), cost_op_fuelcosts_objfn_p67 (80 %), gen_upv_p65 (80 %), cap_gas-ct_p60 (80 %).

Summary table (mean coverage over outputs):

| layer | method | 0.5 | 0.8 | 0.9 | 0.95 |
|---|---|---|---|---|---|
| regional | ngb_conformal | 0.502 | 0.799 | 0.898 | 0.947 |
| regional | ngb_native | 0.498 | 0.799 | 0.894 | 0.941 |
| regional | rf_conformal | 0.572 | 0.809 | 0.902 | 0.950 |
| regional | rf_conformal_insample | 0.572 | 0.811 | 0.903 | 0.950 |
| regional | rf_tree_quantile | 0.682 | 0.826 | 0.879 | 0.911 |
| system | ngb_conformal | 0.501 | 0.798 | 0.898 | 0.948 |
| system | ngb_native | 0.484 | 0.781 | 0.882 | 0.933 |
| system | rf_conformal | 0.563 | 0.809 | 0.902 | 0.950 |
| system | rf_conformal_insample | 0.563 | 0.811 | 0.903 | 0.950 |
| system | rf_tree_quantile | 0.645 | 0.802 | 0.859 | 0.893 |

Figures: figs/fig01a_reliability (nominal vs empirical, solid = system, dotted = regional), figs/fig01b_coverage_hist (per-output 90 % coverage).

## 2. Learning curve (RF, system layer, 10-fold OOF, 5 repeats)

At the full n = 486 the mean / median OOF R-squared is 0.752 / 0.880 (repeat 0 is the draft seed; the five fold-assignment seeds span 0.748-0.756 mean and 0.873-0.884 median), with 29.2 outputs at R-squared >= 0.9 on average (range 29-30).
With n = 50 runs the OOF mean / median R-squared is 0.455 / 0.531 (repeat spread 0.418-0.529 on the mean) and 2.8 outputs reach R-squared >= 0.9 (range 1-5); scored on the 436 undrawn runs the mean R-squared is 0.499 (pooled-variance R-squared).
With n = 100 runs the OOF mean / median R-squared is 0.555 / 0.677 (repeat spread 0.505-0.597 on the mean) and 11.2 outputs reach R-squared >= 0.9 (range 9-13); scored on the 386 undrawn runs the mean R-squared is 0.610 (pooled-variance R-squared).
With n = 150 runs the OOF mean / median R-squared is 0.626 / 0.743 (repeat spread 0.591-0.645 on the mean) and 15.2 outputs reach R-squared >= 0.9 (range 13-17); scored on the 336 undrawn runs the mean R-squared is 0.651 (pooled-variance R-squared).
With n = 200 runs the OOF mean / median R-squared is 0.666 / 0.789 (repeat spread 0.661-0.671 on the mean) and 19.4 outputs reach R-squared >= 0.9 (range 18-21); scored on the 286 undrawn runs the mean R-squared is 0.676 (pooled-variance R-squared).
With n = 300 runs the OOF mean / median R-squared is 0.695 / 0.822 (repeat spread 0.679-0.718 on the mean) and 22.4 outputs reach R-squared >= 0.9 (range 21-24); scored on the 186 undrawn runs the mean R-squared is 0.706 (pooled-variance R-squared).
With n = 400 runs the OOF mean / median R-squared is 0.734 / 0.872 (repeat spread 0.717-0.757 on the mean) and 28.0 outputs reach R-squared >= 0.9 (range 27-29); scored on the 86 undrawn runs the mean R-squared is 0.785 (pooled-variance R-squared).
Half of the R-squared gain between n = 50 and n = 486 is reached by n = 150, and n = 400 is the first size within 5 % of the full-table mean R-squared; the curve has not flattened at 486, so a national design with more dials should expect to need more than 486 runs for the same per-output accuracy.

Per-size summary (mean over 5 repeats; min-max in the CSV):

| eval | n | r2_mean | r2_mean_sd | r2_median | r2_median_sd | n_ge_0_9 |
|---|---|---|---|---|---|---|
| external | 50 | 0.499 | 0.037 | 0.566 | 0.069 | 2.600 |
| external | 100 | 0.610 | 0.015 | 0.716 | 0.046 | 11.200 |
| external | 150 | 0.651 | 0.025 | 0.785 | 0.036 | 16.200 |
| external | 200 | 0.676 | 0.038 | 0.830 | 0.023 | 20.200 |
| external | 300 | 0.706 | 0.026 | 0.867 | 0.032 | 26.400 |
| external | 400 | 0.785 | 0.017 | 0.896 | 0.014 | 32.000 |
| oof | 50 | 0.455 | 0.049 | 0.531 | 0.076 | 2.800 |
| oof | 100 | 0.555 | 0.036 | 0.677 | 0.025 | 11.200 |
| oof | 150 | 0.626 | 0.023 | 0.743 | 0.031 | 15.200 |
| oof | 200 | 0.666 | 0.005 | 0.789 | 0.028 | 19.400 |
| oof | 300 | 0.695 | 0.017 | 0.822 | 0.031 | 22.400 |
| oof | 400 | 0.734 | 0.014 | 0.872 | 0.006 | 28.000 |
| oof | 486 | 0.752 | 0.003 | 0.880 | 0.005 | 29.200 |

Figure: figs/fig02_learning_curve (shaded = min-max over 5 repeats).

## 3. Leave-one-level-out validation (RF, system layer)

Each row trains on the runs at the other level(s) of one dial and predicts all runs at the held-out level; 'random' is the 10-fold OOF prediction on the same held-out runs. R-squared uses the pooled variance over all 486 runs as denominator (1 - MSE / Var_all) so that hold-outs are comparable; classic per-level R-squared is in data/03_lolo_per_output.csv.
Holding out Dem = Lo (extrapolation, 162 runs) gives mean / median pooled R-squared 0.580 / 0.792 versus 0.787 / 0.927 for random folds on the same runs; 12 outputs stay above 0.9 (random: 40) and 6 go negative; on the eight headline outputs the mean is 0.882 versus 0.953; the median MAE is 32.7 % of the held-out mean versus 18.7 %.
Holding out Dem = Hi (extrapolation, 162 runs) gives mean / median pooled R-squared 0.279 / 0.431 versus 0.758 / 0.884 for random folds on the same runs; 2 outputs stay above 0.9 (random: 29) and 20 go negative; on the eight headline outputs the mean is 0.675 versus 0.938; the median MAE is 37.1 % of the held-out mean versus 18.6 %.
Holding out Dem = Md (interpolation, 162 runs) gives mean / median pooled R-squared 0.528 / 0.799 versus 0.702 / 0.894 for random folds on the same runs; 8 outputs stay above 0.9 (random: 31) and 8 go negative; on the eight headline outputs the mean is 0.885 versus 0.954; the median MAE is 28.1 % of the held-out mean versus 18.1 %.
Holding out Fuel = Lo (extrapolation, 162 runs) gives mean / median pooled R-squared -0.782 / -0.832 versus 0.557 / 0.876 for random folds on the same runs; 7 outputs stay above 0.9 (random: 32) and 50 go negative; on the eight headline outputs the mean is -0.981 versus 0.938; the median MAE is 56.0 % of the held-out mean versus 17.3 %.
Holding out Fuel = Hi (extrapolation, 162 runs) gives mean / median pooled R-squared 0.278 / 0.600 versus 0.761 / 0.971 for random folds on the same runs; 17 outputs stay above 0.9 (random: 46) and 14 go negative; on the eight headline outputs the mean is 0.591 versus 0.955; the median MAE is 83.4 % of the held-out mean versus 24.0 %.
Holding out Fuel = Md (interpolation, 162 runs) gives mean / median pooled R-squared -0.493 / -0.555 versus 0.929 / 0.973 for random folds on the same runs; 7 outputs stay above 0.9 (random: 51) and 47 go negative; on the eight headline outputs the mean is -0.980 versus 0.953; the median MAE is 97.0 % of the held-out mean versus 19.1 %.
Holding out REcost = Lo (extrapolation, 162 runs) gives mean / median pooled R-squared 0.307 / 0.716 versus 0.694 / 0.931 for random folds on the same runs; 10 outputs stay above 0.9 (random: 37) and 13 go negative; on the eight headline outputs the mean is 0.735 versus 0.954; the median MAE is 33.0 % of the held-out mean versus 19.5 %.
Holding out REcost = Hi (extrapolation, 162 runs) gives mean / median pooled R-squared 0.301 / 0.599 versus 0.668 / 0.909 for random folds on the same runs; 13 outputs stay above 0.9 (random: 34) and 14 go negative; on the eight headline outputs the mean is 0.635 versus 0.941; the median MAE is 40.9 % of the held-out mean versus 20.4 %.
Holding out REcost = Md (interpolation, 162 runs) gives mean / median pooled R-squared 0.455 / 0.682 versus 0.885 / 0.948 for random folds on the same runs; 10 outputs stay above 0.9 (random: 45) and 10 go negative; on the eight headline outputs the mean is 0.735 versus 0.951; the median MAE is 31.2 % of the held-out mean versus 18.8 %.
Holding out Siting = Open (extrapolation, 162 runs) gives mean / median pooled R-squared 0.642 / 0.805 versus 0.806 / 0.898 for random folds on the same runs; 15 outputs stay above 0.9 (random: 32) and 6 go negative; on the eight headline outputs the mean is 0.895 versus 0.951; the median MAE is 25.9 % of the held-out mean versus 19.2 %.
Holding out Siting = Lim (extrapolation, 162 runs) gives mean / median pooled R-squared 0.203 / 0.487 versus 0.673 / 0.915 for random folds on the same runs; 7 outputs stay above 0.9 (random: 37) and 15 go negative; on the eight headline outputs the mean is 0.815 versus 0.946; the median MAE is 33.0 % of the held-out mean versus 21.5 %.
Holding out Siting = Ref (extrapolation, 162 runs) gives mean / median pooled R-squared 0.624 / 0.827 versus 0.768 / 0.919 for random folds on the same runs; 14 outputs stay above 0.9 (random: 36) and 8 go negative; on the eight headline outputs the mean is 0.903 versus 0.949; the median MAE is 25.2 % of the held-out mean versus 18.1 %.
Holding out Batt = Lo (extrapolation, 162 runs) gives mean / median pooled R-squared 0.671 / 0.848 versus 0.801 / 0.900 for random folds on the same runs; 23 outputs stay above 0.9 (random: 33) and 4 go negative; on the eight headline outputs the mean is 0.630 versus 0.939; the median MAE is 30.8 % of the held-out mean versus 19.5 %.
Holding out Batt = Hi (extrapolation, 162 runs) gives mean / median pooled R-squared 0.574 / 0.870 versus 0.674 / 0.888 for random folds on the same runs; 25 outputs stay above 0.9 (random: 30) and 8 go negative; on the eight headline outputs the mean is 0.832 versus 0.956; the median MAE is 21.9 % of the held-out mean versus 18.2 %.
Holding out Batt = Md (interpolation, 162 runs) gives mean / median pooled R-squared 0.671 / 0.865 versus 0.771 / 0.908 for random folds on the same runs; 25 outputs stay above 0.9 (random: 34) and 4 go negative; on the eight headline outputs the mean is 0.647 versus 0.951; the median MAE is 24.7 % of the held-out mean versus 18.2 %.
Holding out Pol = IRA (unseen category, 243 runs) gives mean / median pooled R-squared 0.080 / 0.314 versus 0.668 / 0.872 for random folds on the same runs; 3 outputs stay above 0.9 (random: 30) and 22 go negative; on the eight headline outputs the mean is 0.597 versus 0.949; the median MAE is 62.7 % of the held-out mean versus 20.5 %.
Holding out Pol = OBBBA (unseen category, 243 runs) gives mean / median pooled R-squared 0.180 / 0.425 versus 0.830 / 0.934 for random folds on the same runs; 3 outputs stay above 0.9 (random: 36) and 23 go negative; on the eight headline outputs the mean is 0.588 versus 0.948; the median MAE is 48.5 % of the held-out mean versus 17.3 %.
Averaged over the five continuous dials, leaving out the Lo/Open level gives mean pooled R-squared 0.283 (random folds on the same runs: 0.729), leaving out Hi/Lim gives 0.327 (random 0.707), and leaving out the middle level gives 0.290 (random 0.822); on the eight headline outputs the three numbers are 0.432, 0.710 and 0.322 against 0.947, 0.947 and 0.952.
A tree ensemble predicts a constant outside its training range, and with only the two outer levels left every split threshold sits exactly at the middle value, which sklearn resolves to the lower branch, so the middle level is predicted as if it were the low level; these numbers therefore bound what the surrogate can say beyond the sampled grid. It should be used inside the sampled levels only, and the continuous dial sliders in the dashboard interpolate tree plateaus rather than physics.
Holding out a policy level: mean pooled R-squared 0.080 when IRA runs are unseen and 0.180 when OBBBA runs are unseen (random folds: 0.668 and 0.830), so the surrogate cannot be transferred to an unseen policy case.
Worst headline-output extrapolations: gen_gas-ct with Fuel=Hi held out (pooled R-squared -2.31, bias -51 % of mean); cap_nuclear with Siting=Ref held out (pooled R-squared -2.01, bias +0 % of mean); cap_nuclear with REcost=Lo held out (pooled R-squared -2.01, bias +0 % of mean); cap_nuclear with Fuel=Hi held out (pooled R-squared -2.01, bias +0 % of mean); tran_total with Fuel=Lo held out (pooled R-squared -1.86, bias -32 % of mean).
Most robust: cap_nuclear with Fuel=Lo held out (pooled R-squared 1.00); cap_nuclear with REcost=Hi held out (pooled R-squared 1.00); gen_gas-cc with Siting=Ref held out (pooled R-squared 0.99).

Summary table (pooled R-squared unless marked classic):

| dial | held_out | kind | n_test | r2_pooled_lolo_mean | r2_pooled_lolo_median | r2_pooled_random_mean | r2_pooled_random_median | r2_pooled_headline_lolo | r2_pooled_headline_random | r2_classic_lolo_median | r2_classic_random_median | n_lolo_ge_0_9 | n_random_ge_0_9 | n_lolo_negative |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Dem | Lo | extrapolation | 162 | 0.580 | 0.792 | 0.787 | 0.927 | 0.882 | 0.953 | 0.751 | 0.904 | 12 | 40 | 6 |
| Dem | Hi | extrapolation | 162 | 0.279 | 0.431 | 0.758 | 0.884 | 0.675 | 0.938 | 0.583 | 0.899 | 2 | 29 | 20 |
| Dem | Md | interpolation | 162 | 0.528 | 0.799 | 0.702 | 0.894 | 0.885 | 0.954 | 0.703 | 0.821 | 8 | 31 | 8 |
| Fuel | Lo | extrapolation | 162 | -0.782 | -0.832 | 0.557 | 0.876 | -0.981 | 0.938 | -0.775 | 0.872 | 7 | 32 | 50 |
| Fuel | Hi | extrapolation | 162 | 0.278 | 0.600 | 0.761 | 0.971 | 0.591 | 0.955 | -0.722 | 0.807 | 17 | 46 | 14 |
| Fuel | Md | interpolation | 162 | -0.493 | -0.555 | 0.929 | 0.973 | -0.980 | 0.953 | -3.068 | 0.856 | 7 | 51 | 47 |
| REcost | Lo | extrapolation | 162 | 0.307 | 0.716 | 0.694 | 0.931 | 0.735 | 0.954 | 0.453 | 0.874 | 10 | 37 | 13 |
| REcost | Hi | extrapolation | 162 | 0.301 | 0.599 | 0.668 | 0.909 | 0.635 | 0.941 | 0.572 | 0.890 | 13 | 34 | 14 |
| REcost | Md | interpolation | 162 | 0.455 | 0.682 | 0.885 | 0.948 | 0.735 | 0.951 | 0.601 | 0.867 | 10 | 45 | 10 |
| Siting | Open | extrapolation | 162 | 0.642 | 0.805 | 0.806 | 0.898 | 0.895 | 0.951 | 0.805 | 0.883 | 15 | 32 | 6 |
| Siting | Lim | extrapolation | 162 | 0.203 | 0.487 | 0.673 | 0.915 | 0.815 | 0.946 | 0.560 | 0.869 | 7 | 37 | 15 |
| Siting | Ref | extrapolation | 162 | 0.624 | 0.827 | 0.768 | 0.919 | 0.903 | 0.949 | 0.807 | 0.885 | 14 | 36 | 8 |
| Batt | Lo | extrapolation | 162 | 0.671 | 0.848 | 0.801 | 0.900 | 0.630 | 0.939 | 0.815 | 0.868 | 23 | 33 | 4 |
| Batt | Hi | extrapolation | 162 | 0.574 | 0.870 | 0.674 | 0.888 | 0.832 | 0.956 | 0.861 | 0.874 | 25 | 30 | 8 |
| Batt | Md | interpolation | 162 | 0.671 | 0.865 | 0.771 | 0.908 | 0.647 | 0.951 | 0.858 | 0.877 | 25 | 34 | 4 |
| Pol | IRA | unseen category | 243 | 0.080 | 0.314 | 0.668 | 0.872 | 0.597 | 0.949 | 0.185 | 0.871 | 3 | 30 | 22 |
| Pol | OBBBA | unseen category | 243 | 0.180 | 0.425 | 0.830 | 0.934 | 0.588 | 0.948 | 0.574 | 0.873 | 3 | 36 | 23 |

Figure: figs/fig03_lolo_headline (bars = mean over the five continuous dials, whiskers = min-max across dials, clipped at -0.5; 'random 10-fold' is the full 486-run OOF R-squared).

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

## 5. Dial sensitivity from the full factorial (exact ANOVA shares)

cost_total: main effects explain 79 % of its variance across the 486 runs (largest Fuel 60 %, then Pol 10 %, REcost 8 %), two-way interactions 10 % and higher-order terms 11 %; the RF OOF predictions attribute 67 % to Fuel and 10 % to two-way terms, and RF permutation importance ranks Fuel (62 %) then REcost (16 %).
tran_total: main effects explain 86 % of its variance across the 486 runs (largest Fuel 71 %, then REcost 4 %, Siting 4 %), two-way interactions 11 % and higher-order terms 3 %; the RF OOF predictions attribute 74 % to Fuel and 10 % to two-way terms, and RF permutation importance ranks Fuel (71 %) then Siting (10 %).
cap_wind-ons: main effects explain 94 % of its variance across the 486 runs (largest Fuel 73 %, then REcost 14 %, Dem 5 %), two-way interactions 4 % and higher-order terms 1 %; the RF OOF predictions attribute 74 % to Fuel and 4 % to two-way terms, and RF permutation importance ranks Fuel (73 %) then REcost (14 %).
gen_wind-ons: main effects explain 95 % of its variance across the 486 runs (largest Fuel 66 %, then REcost 19 %, Dem 6 %), two-way interactions 4 % and higher-order terms 1 %; the RF OOF predictions attribute 67 % to Fuel and 4 % to two-way terms, and RF permutation importance ranks Fuel (66 %) then REcost (19 %).
cap_upv: main effects explain 85 % of its variance across the 486 runs (largest Fuel 49 %, then Dem 18 %, Pol 7 %), two-way interactions 12 % and higher-order terms 3 %; the RF OOF predictions attribute 52 % to Fuel and 12 % to two-way terms, and RF permutation importance ranks Fuel (54 %) then Dem (18 %).
gen_upv: main effects explain 85 % of its variance across the 486 runs (largest Fuel 41 %, then Dem 21 %, REcost 8 %), two-way interactions 12 % and higher-order terms 3 %; the RF OOF predictions attribute 44 % to Fuel and 13 % to two-way terms, and RF permutation importance ranks Fuel (46 %) then Dem (21 %).
cap_gas-cc: main effects explain 86 % of its variance across the 486 runs (largest Fuel 48 %, then REcost 23 %, Pol 8 %), two-way interactions 10 % and higher-order terms 4 %; the RF OOF predictions attribute 51 % to Fuel and 9 % to two-way terms, and RF permutation importance ranks Fuel (52 %) then REcost (25 %).
gen_gas-cc: main effects explain 93 % of its variance across the 486 runs (largest Fuel 72 %, then REcost 14 %, Dem 4 %), two-way interactions 5 % and higher-order terms 2 %; the RF OOF predictions attribute 73 % to Fuel and 5 % to two-way terms, and RF permutation importance ranks Fuel (72 %) then REcost (17 %).
cap_battery_li: main effects explain 77 % of its variance across the 486 runs (largest Batt 59 %, then Fuel 16 %, Pol 1 %), two-way interactions 13 % and higher-order terms 9 %; the RF OOF predictions attribute 64 % to Batt and 13 % to two-way terms, and RF permutation importance ranks Batt (61 %) then Fuel (24 %).
gen_battery_li: main effects explain 80 % of its variance across the 486 runs (largest Batt 57 %, then Fuel 19 %, Siting 2 %), two-way interactions 11 % and higher-order terms 8 %; the RF OOF predictions attribute 62 % to Batt and 10 % to two-way terms, and RF permutation importance ranks Batt (58 %) then Fuel (25 %).
cap_gas-ct: main effects explain 72 % of its variance across the 486 runs (largest REcost 20 %, then Fuel 17 %, Pol 16 %), two-way interactions 20 % and higher-order terms 8 %; the RF OOF predictions attribute 22 % to REcost and 19 % to two-way terms, and RF permutation importance ranks Fuel (29 %) then REcost (24 %).
gen_gas-ct: main effects explain 58 % of its variance across the 486 runs (largest Fuel 29 %, then Dem 13 %, Batt 8 %), two-way interactions 30 % and higher-order terms 13 %; the RF OOF predictions attribute 37 % to Fuel and 29 % to two-way terms, and RF permutation importance ranks Fuel (44 %) then Dem (26 %).
cap_nuclear: main effects explain 2 % of its variance across the 486 runs (largest Dem 0 %, then Fuel 0 %, REcost 0 %), two-way interactions 10 % and higher-order terms 87 %; the RF OOF predictions attribute 0 % to Dem and 33 % to two-way terms, and RF permutation importance ranks Fuel (29 %) then REcost (22 %).
gen_nuclear: main effects explain 68 % of its variance across the 486 runs (largest Fuel 36 %, then REcost 22 %, Batt 7 %), two-way interactions 15 % and higher-order terms 17 %; the RF OOF predictions attribute 43 % to Fuel and 16 % to two-way terms, and RF permutation importance ranks Fuel (42 %) then REcost (24 %).

Across the 14 headline outputs and 6 dials, the RF share of each main effect differs from the ReEDS share by 1.3 points on average (max 7.4 points, for Fuel on gen_nuclear); on average the RF predictions put +4.7 points more of their variance into main effects, +1.5 points into two-way interactions and -6.1 points into higher-order terms than the ReEDS outputs do, i.e. the out-of-fold surrogate reproduces the main-effect and pairwise structure and smooths away part of the three-way-and-higher variance.
The dominant dial is the same in ReEDS and in the RF predictions for 93 % of headline outputs, and permutation importance picks the same dominant dial for 86 %.
Averaged over the headline outputs the dials rank Fuel (43 %), Batt (11 %), REcost (10 %), Dem (6 %), Pol (4 %), Siting (2 %), with two-way interactions at 12 % and higher-order terms at 12 %.

Variance shares (ReEDS outputs):

| output | Batt | Dem | Fuel | Pol | REcost | Siting | two-way | higher |
|---|---|---|---|---|---|---|---|---|
| cost_total | 0.1 | 1.1 | 59.5 | 9.6 | 7.7 | 0.9 | 10.5 | 10.6 |
| tran_total | 0.2 | 3.8 | 70.6 | 2.8 | 4.4 | 4.3 | 11.0 | 3.0 |
| cap_wind-ons | 0.9 | 5.0 | 72.9 | 1.6 | 13.8 | 0.2 | 4.4 | 1.1 |
| gen_wind-ons | 0.4 | 5.9 | 65.6 | 1.9 | 18.7 | 2.8 | 3.7 | 1.0 |
| cap_upv | 4.1 | 17.8 | 49.1 | 7.4 | 5.2 | 1.8 | 11.7 | 2.9 |
| gen_upv | 5.8 | 20.7 | 40.9 | 5.7 | 7.8 | 3.8 | 12.2 | 3.1 |
| cap_gas-cc | 0.2 | 3.9 | 48.3 | 7.6 | 23.1 | 2.8 | 9.7 | 4.3 |
| gen_gas-cc | 0.0 | 4.5 | 71.9 | 2.6 | 14.0 | 0.1 | 5.2 | 1.7 |
| cap_battery_li | 58.6 | 0.3 | 15.9 | 1.1 | 0.6 | 0.8 | 13.2 | 9.4 |
| gen_battery_li | 56.6 | 0.7 | 18.8 | 0.9 | 1.3 | 2.0 | 11.4 | 8.2 |
| cap_gas-ct | 15.1 | 1.7 | 16.6 | 16.2 | 20.0 | 2.1 | 20.4 | 7.9 |
| gen_gas-ct | 8.5 | 12.8 | 29.2 | 1.2 | 0.1 | 5.9 | 29.6 | 12.7 |
| cap_nuclear | 0.4 | 0.4 | 0.4 | 0.2 | 0.4 | 0.4 | 10.3 | 87.4 |
| gen_nuclear | 7.4 | 1.0 | 35.8 | 2.1 | 22.1 | 0.0 | 14.7 | 16.9 |

Variance shares (RF OOF predictions):

| output | Batt | Dem | Fuel | Pol | REcost | Siting | two-way | higher |
|---|---|---|---|---|---|---|---|---|
| cost_total | 0.0 | 0.5 | 66.8 | 10.0 | 7.9 | 1.0 | 9.9 | 3.8 |
| tran_total | 0.1 | 3.4 | 73.8 | 2.4 | 4.2 | 3.9 | 10.3 | 1.8 |
| cap_wind-ons | 0.4 | 4.7 | 74.5 | 1.2 | 13.9 | 0.1 | 4.4 | 0.8 |
| gen_wind-ons | 0.1 | 5.1 | 67.2 | 1.2 | 19.3 | 2.0 | 4.4 | 0.8 |
| cap_upv | 2.9 | 18.7 | 51.6 | 6.8 | 5.5 | 0.8 | 11.7 | 1.8 |
| gen_upv | 4.4 | 22.4 | 43.6 | 4.7 | 7.5 | 2.2 | 13.1 | 2.2 |
| cap_gas-cc | 0.0 | 3.6 | 51.5 | 7.2 | 24.4 | 2.2 | 8.8 | 2.3 |
| gen_gas-cc | 0.0 | 4.2 | 72.8 | 2.5 | 14.2 | 0.1 | 5.0 | 1.1 |
| cap_battery_li | 63.7 | 0.3 | 17.0 | 0.7 | 0.4 | 0.7 | 12.9 | 4.3 |
| gen_battery_li | 62.2 | 0.4 | 20.1 | 0.6 | 0.9 | 1.7 | 9.9 | 4.1 |
| cap_gas-ct | 15.7 | 1.6 | 18.6 | 18.2 | 21.8 | 1.2 | 19.3 | 3.6 |
| gen_gas-ct | 7.9 | 15.1 | 36.6 | 1.2 | 0.2 | 5.1 | 29.3 | 4.7 |
| cap_nuclear | 0.4 | 0.5 | 7.1 | 2.9 | 7.1 | 0.7 | 33.3 | 48.1 |
| gen_nuclear | 7.7 | 0.4 | 43.3 | 1.7 | 26.0 | 0.0 | 15.9 | 5.1 |

RF permutation importance (normalised share, %):

| output | Batt | Dem | Fuel | Pol | REcost | Siting |
|---|---|---|---|---|---|---|
| cost_total | 1.3 | 4.8 | 61.7 | 10.9 | 16.4 | 5.0 |
| tran_total | 0.5 | 8.2 | 71.0 | 4.6 | 5.9 | 9.8 |
| cap_wind-ons | 1.4 | 7.0 | 73.1 | 2.4 | 14.4 | 1.7 |
| gen_wind-ons | 0.6 | 7.9 | 66.2 | 2.6 | 19.2 | 3.4 |
| cap_upv | 5.6 | 18.3 | 53.5 | 9.9 | 9.8 | 2.9 |
| gen_upv | 7.6 | 21.0 | 46.4 | 8.0 | 11.7 | 5.2 |
| cap_gas-cc | 0.7 | 7.2 | 51.8 | 10.3 | 25.0 | 5.0 |
| gen_gas-cc | 0.2 | 5.6 | 72.4 | 4.4 | 16.5 | 0.8 |
| cap_battery_li | 61.1 | 3.4 | 23.8 | 3.5 | 3.3 | 4.9 |
| gen_battery_li | 57.9 | 3.7 | 25.1 | 3.8 | 3.7 | 5.8 |
| cap_gas-ct | 15.6 | 6.8 | 28.9 | 21.0 | 23.8 | 4.0 |
| gen_gas-ct | 10.3 | 25.7 | 43.5 | 3.7 | 4.8 | 11.9 |
| cap_nuclear | 11.6 | 13.4 | 28.6 | 12.9 | 21.6 | 11.9 |
| gen_nuclear | 11.7 | 6.0 | 42.0 | 5.0 | 24.2 | 11.1 |

Figures: figs/fig05a_variance_shares (stacked shares, ReEDS outputs), figs/fig05b_truth_vs_rf (ReEDS vs RF share per output-dial pair).

## 6. Failure classes: sparse and near-constant outputs

**system layer (66 outputs)**: 23 outputs are sparse (non-zero in fewer than 50 % of runs) with mean / median R-squared 0.56 / 0.55; 2 are near-constant (CV < 2 %) with mean / median R-squared 0.32 / 0.32; the remaining 41 regular outputs have mean / median R-squared 0.877 / 0.925.
Of the 12 system outputs with R-squared below 0.5, 11 are sparse and 1 are near-constant, so 100 % of the low-R-squared outputs fall in the two failure classes.
Spearman correlation of per-output R-squared with activation frequency is 0.61 and with coefficient of variation -0.62 (system).
**regional layer (308 outputs)**: 129 outputs are sparse (non-zero in fewer than 50 % of runs) with mean / median R-squared 0.42 / 0.52; 5 are near-constant (CV < 2 %) with mean / median R-squared 0.73 / 1.00; the remaining 174 regular outputs have mean / median R-squared 0.775 / 0.832.
Of the 85 regional outputs with R-squared below 0.5, 62 are sparse and 1 are near-constant, so 74 % of the low-R-squared outputs fall in the two failure classes.
Spearman correlation of per-output R-squared with activation frequency is 0.69 and with coefficient of variation -0.63 (regional).

cap_nuclear takes only 2 distinct values across the 486 runs (CV 0.07 %); its OOF R-squared is -0.36 but its MAE is 0.012 % of the mean, so the low R-squared is a metric artefact of a near-constant denominator, not a prediction failure.
Headline-output absolute errors (RF, 10-fold OOF): cost_total R-squared 0.90, MAE 7.4 % of mean; tran_total R-squared 0.97, MAE 2.8 % of mean; cap_wind-ons R-squared 0.99, MAE 2.8 % of mean; gen_wind-ons R-squared 0.99, MAE 3.0 % of mean; cap_upv R-squared 0.97, MAE 4.0 % of mean; gen_upv R-squared 0.96, MAE 4.5 % of mean; cap_gas-cc R-squared 0.95, MAE 4.6 % of mean; gen_gas-cc R-squared 0.99, MAE 4.5 % of mean; cap_battery_li R-squared 0.93, MAE 12.8 % of mean; gen_battery_li R-squared 0.94, MAE 13.9 % of mean; cap_gas-ct R-squared 0.89, MAE 8.0 % of mean; gen_gas-ct R-squared 0.87, MAE 12.1 % of mean; cap_nuclear R-squared -0.36, MAE 0.0 % of mean; gen_nuclear R-squared 0.84, MAE 0.6 % of mean.

Headline table:

| output | r2 | activation | cv | mae_pct_of_mean | rmse_pct_of_range | class |
|---|---|---|---|---|---|---|
| cost_total | 0.898 | 1.000 | 0.326 | 7.408 | 6.215 | regular |
| tran_total | 0.975 | 1.000 | 0.267 | 2.797 | 3.480 | regular |
| cap_wind-ons | 0.989 | 1.000 | 0.350 | 2.832 | 2.438 | regular |
| gen_wind-ons | 0.986 | 1.000 | 0.332 | 3.019 | 2.406 | regular |
| cap_upv | 0.967 | 1.000 | 0.288 | 3.962 | 4.012 | regular |
| gen_upv | 0.963 | 1.000 | 0.303 | 4.486 | 4.264 | regular |
| cap_gas-cc | 0.953 | 1.000 | 0.272 | 4.580 | 5.444 | regular |
| gen_gas-cc | 0.990 | 1.000 | 0.618 | 4.491 | 3.074 | regular |
| cap_battery_li | 0.926 | 1.000 | 0.659 | 12.777 | 6.857 | regular |
| gen_battery_li | 0.941 | 1.000 | 0.807 | 13.866 | 6.413 | regular |
| cap_gas-ct | 0.893 | 1.000 | 0.308 | 7.969 | 6.541 | regular |
| gen_gas-ct | 0.869 | 1.000 | 0.568 | 12.053 | 5.097 | regular |
| cap_nuclear | -0.362 | 1.000 | 0.001 | 0.012 | 5.288 | near-constant |
| gen_nuclear | 0.842 | 1.000 | 0.023 | 0.648 | 6.709 | regular |

Figure: figs/fig06_r2_vs_activation_cv (left: R-squared vs activation frequency; right: vs CV, log scale; large markers = system layer, faint = regional; near-constant and low-R-squared sparse system outputs labelled).

## 7. Regional layer detail (RF, 10-fold OOF)

The regional layer has 308 modelled outputs across 298 BA-resolved columns in 7 balancing areas plus 10 transmission corridors (an 11th corridor is constant and dropped); per region: corridor 10 outputs, mean / median R-squared 0.79 / 0.86, 3 at >= 0.9; p60 35 outputs, mean / median R-squared 0.54 / 0.61, 2 at >= 0.9; p61 36 outputs, mean / median R-squared 0.74 / 0.84, 8 at >= 0.9; p62 37 outputs, mean / median R-squared 0.57 / 0.66, 4 at >= 0.9; p63 50 outputs, mean / median R-squared 0.64 / 0.81, 16 at >= 0.9; p64 45 outputs, mean / median R-squared 0.64 / 0.60, 13 at >= 0.9; p65 49 outputs, mean / median R-squared 0.62 / 0.75, 14 at >= 0.9; p67 46 outputs, mean / median R-squared 0.59 / 0.79, 16 at >= 0.9.
The best-predicted region is corridor (mean R-squared 0.79) and the worst is p60 (0.54); mean activation frequency of the outputs is 1.00 versus 0.58, so regional difficulty tracks how many sparse tech-region combinations a BA has.
By category within region, cap outputs have mean R-squared from 0.52 (p65) to 0.70 (p61).
By category within region, gen outputs have mean R-squared from 0.55 (p62) to 0.77 (p61).
By category within region, cost outputs have mean R-squared from 0.49 (p60) to 0.74 (p61).

Additivity before rescaling: across the 63 quantities present in both layers, the sum of the raw regional RF predictions differs from the system RF prediction by a median of 2.21 % of the system value (median over quantities of the per-quantity median absolute gap), exceeds 1 % in 59 % of (run, quantity) pairs and 5 % in 31 %.
For the headline quantities the median absolute gap is cap_wind-ons 2.14 % (p90 5.9 %), cap_upv 2.74 % (p90 6.7 %), cap_gas-cc 1.60 % (p90 4.1 %), cap_battery_li 5.23 % (p90 14.4 %), cap_gas-ct 3.49 % (p90 8.6 %), gen_wind-ons 2.12 % (p90 5.4 %), gen_upv 2.71 % (p90 7.2 %), gen_gas-cc 2.07 % (p90 7.0 %), tran_total 0.99 % (p90 4.2 %).
The sum of regional predictions is itself a competitive estimate of the system total: R-squared against the ReEDS system value is cap_wind-ons 0.988 (system model 0.989), cap_upv 0.972 (system model 0.967), cap_gas-cc 0.961 (system model 0.953), cap_battery_li 0.932 (system model 0.926), cap_gas-ct 0.918 (system model 0.893), gen_wind-ons 0.987 (system model 0.986), gen_upv 0.969 (system model 0.963), gen_gas-cc 0.991 (system model 0.990), tran_total 0.982 (system model 0.975).
Quantities whose regional sum misses the system prediction by more than 5 % in over a quarter of runs: cost_inv_investment_capacity_costs, cost_inv_investment_spurline_costs_rsc_technologies, cost_inv_transmission_interzone_ac_investment, cost_inv_transmission_intrazone_investment, cost_op_ptc_payments_negative, cost_op_startcost, cost_inv_investment_refurbishment_capacity, gen_upv, cost_op_co2_transport_storage, gen_gas-ct, cost_op_h2_transport_intrareg, cost_op_consume_fom, gen_battery_li, cost_op_h2_storage, cost_inv_h2_production, gen_CoalOldScr, gen_CoalOldScr_coal-CCS_mod, cost_inv_h2_storage, gen_o-g-s, gen_H2-CT, gen_H2-CC, cap_gas-ct, gen_Gas-CC_H2-CC, cap_battery_li, cap_gas-cc-ccs_mod, cap_CoalOldScr_coal-CCS_mod, cap_CoalOldScr, cap_H2-CT, cap_electrolyzer, cap_H2-CC, cap_Gas-CC_H2-CC.
Because the dashboard does not call enforce_additivity, these pre-rescale gaps are what a user sees when comparing the regional and system views.

Per-region table:

| region | n_outputs | r2_mean | r2_median | n_ge_0_9 | n_below_0_5 | mean_activation |
|---|---|---|---|---|---|---|
| corridor | 10 | 0.786 | 0.856 | 3 | 2 | 1.000 |
| p60 | 35 | 0.540 | 0.607 | 2 | 13 | 0.581 |
| p61 | 36 | 0.738 | 0.839 | 8 | 5 | 0.623 |
| p62 | 37 | 0.568 | 0.656 | 4 | 13 | 0.561 |
| p63 | 50 | 0.639 | 0.814 | 16 | 16 | 0.568 |
| p64 | 45 | 0.641 | 0.595 | 13 | 11 | 0.615 |
| p65 | 49 | 0.616 | 0.750 | 14 | 12 | 0.579 |
| p67 | 46 | 0.592 | 0.793 | 16 | 13 | 0.621 |

Additivity residual table (sorted by magnitude of the quantity):

| quantity | n_regions | median_abs_gap_vs_system_pred_pct | p90_abs_gap_vs_system_pred_pct | frac_gap_gt_1pct | frac_gap_gt_5pct | mean_signed_gap_pct | r2_sum_of_regional | r2_system_model |
|---|---|---|---|---|---|---|---|---|
| cost_inv_investment_capacity_costs | 7 | 5.281 | 15.942 | 0.884 | 0.520 | 2.239 | 0.918 | 0.911 |
| cost_op_fom_costs | 7 | 1.018 | 2.676 | 0.502 | 0.002 | 0.057 | 0.975 | 0.980 |
| cost_op_fuelcosts_objfn | 7 | 1.703 | 4.559 | 0.698 | 0.066 | -0.019 | 0.977 | 0.971 |
| cost_inv_investment_spurline_costs_rsc_technologies | 7 | 7.063 | 25.813 | 0.929 | 0.680 | 3953619.755 | 0.901 | 0.893 |
| cost_inv_transmission_interzone_ac_investment | 7 | 7.541 | 29.598 | 0.899 | 0.619 | 878541.838 | 0.882 | 0.873 |
| cost_op_vom_costs | 7 | 1.848 | 5.058 | 0.706 | 0.103 | 0.049 | 0.982 | 0.979 |
| cost_inv_transmission_intrazone_investment | 7 | 9.238 | 30.558 | 0.944 | 0.728 | 11.926 | 0.857 | 0.832 |
| cost_op_transmission_fom | 7 | 0.667 | 3.052 | 0.391 | 0.012 | 0.093 | 0.981 | 0.976 |
| cost_op_spurline_fom | 7 | 1.585 | 4.177 | 0.667 | 0.058 | 0.233 | 0.991 | 0.993 |
| gen_wind-ons | 7 | 2.117 | 5.367 | 0.747 | 0.123 | 0.483 | 0.987 | 0.986 |
| cost_op_ptc_payments_negative | 7 | 6.394 | 24.217 | 0.918 | 0.580 | -5.396 | 0.963 | 0.966 |
| cost_op_startcost | 7 | 5.937 | 13.856 | 0.889 | 0.566 | 1.066 | 0.889 | 0.878 |
| cost_op_transmission_intrazone_fom | 7 | 1.389 | 3.736 | 0.650 | 0.033 | 0.174 | 0.985 | 0.987 |
| cost_inv_investment_refurbishment_capacity | 5 | 13.736 | 51.266 | 0.973 | 0.792 | 9.277 | 0.608 | 0.541 |
| gen_gas-cc | 7 | 2.075 | 6.993 | 0.770 | 0.183 | 0.702 | 0.991 | 0.990 |
| gen_upv | 7 | 2.710 | 7.164 | 0.792 | 0.255 | 0.389 | 0.969 | 0.963 |
| cost_op_co2_transport_storage | 4 | 2.758 | 12.833 | 0.761 | 0.284 | 0.978 | 0.920 | 0.921 |
| gen_nuclear | 2 | 0.064 | 0.207 | 0.000 | 0.000 | -0.006 | 0.841 | 0.842 |
| gen_gas-ct | 7 | 3.522 | 9.933 | 0.848 | 0.348 | 0.701 | 0.872 | 0.869 |
| gen_distpv | 7 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 |
| cost_op_co2_incentive_negative | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.259 | 0.259 |
| gen_gas-cc-ccs_mod | 4 | 2.487 | 8.319 | 0.789 | 0.246 | 0.793 | 0.812 | 0.824 |
| cost_op_h2_transport_intrareg | 7 | 8.941 | 55.774 | 0.952 | 0.667 | 1482005610436140204032.000 | 0.919 | 0.924 |
| cost_op_consume_fom | 7 | 11.416 | 50.913 | 0.976 | 0.707 | 41.138 | 0.907 | 0.918 |
| gen_coal-ccs_mod | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.957 | 0.957 |
| gen_battery_li | 7 | 6.704 | 21.088 | 0.928 | 0.603 | -3.394 | 0.941 | 0.941 |
| cost_op_h2_storage | 7 | 10.655 | 49.900 | 0.945 | 0.659 | 17.779 | 0.938 | 0.944 |
| cost_inv_h2_production | 5 | 35.384 | 86.532 | 1.000 | 0.900 | -8.481 | -0.047 | 0.008 |
| gen_CoalOldScr | 4 | 3.967 | 16.170 | 0.865 | 0.434 | 14659.650 | 0.925 | 0.927 |
| gen_CoalOldScr_coal-CCS_mod | 4 | 5.358 | 17.399 | 0.874 | 0.524 | 4671.579 | 0.735 | 0.720 |
| gen_Gas-CC_Gas-CC-CCS_mod | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.269 | 0.269 |
| cost_inv_h2_storage | 5 | 40.408 | 299.267 | 0.929 | 0.786 | 83.576 | -0.094 | -0.092 |
| gen_o-g-s | 5 | 2.336 | 9.669 | 0.751 | 0.257 | 0.761 | 0.736 | 0.740 |
| gen_hydEND | 4 | 0.000 | 0.000 | 0.000 | 0.000 | -0.000 | 1.000 | 1.000 |
| gen_hydED | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.937 | 0.937 |
| gen_nuclear-smr | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.207 | 0.207 |
| gen_H2-CT | 7 | 12.303 | 51.287 | 0.933 | 0.693 | 3988235.331 | 0.890 | 0.882 |
| gen_H2-CC | 4 | 1.452 | 35.866 | 0.586 | 0.286 | 44.060 | 0.850 | 0.849 |
| gen_lfill-gas | 3 | 0.166 | 0.492 | 0.008 | 0.000 | -0.006 | 0.833 | 0.828 |
| cap_upv | 7 | 2.744 | 6.729 | 0.802 | 0.195 | 0.413 | 0.972 | 0.967 |
| cap_wind-ons | 7 | 2.142 | 5.889 | 0.737 | 0.144 | 0.449 | 0.988 | 0.989 |
| cap_gas-cc | 7 | 1.603 | 4.053 | 0.677 | 0.039 | 0.024 | 0.961 | 0.953 |
| tran_total | 10 | 0.987 | 4.238 | 0.498 | 0.064 | 0.284 | 0.982 | 0.975 |
| cap_gas-ct | 7 | 3.487 | 8.614 | 0.868 | 0.335 | 0.472 | 0.918 | 0.893 |
| gen_Gas-CC_H2-CC | 5 | 18.904 | 48.692 | 1.000 | 0.907 | -3.475 | 0.446 | 0.371 |
| cap_battery_li | 7 | 5.233 | 14.446 | 0.887 | 0.510 | 2.011 | 0.932 | 0.926 |
| gen_pumped-hydro | 2 | 2.205 | 8.711 | 0.733 | 0.212 | 0.041 | 0.566 | 0.568 |
| cap_nuclear | 1 | 0.000 | 0.000 | 0.000 | 0.000 | -0.000 | -0.362 | -0.362 |
| cap_gas-cc-ccs_mod | 4 | 2.761 | 12.072 | 0.708 | 0.327 | 1.728 | 0.871 | 0.872 |
| cap_CoalOldScr_coal-CCS_mod | 4 | 5.364 | 17.134 | 0.890 | 0.519 | 11160.451 | 0.736 | 0.720 |
| cap_coal-ccs_mod | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.925 | 0.925 |
| cap_o-g-s | 5 | 1.571 | 5.546 | 0.658 | 0.121 | 0.254 | 0.593 | 0.599 |
| cap_CoalOldScr | 4 | 4.991 | 16.593 | 0.853 | 0.500 | 5139.890 | 0.803 | 0.804 |
| cap_H2-CT | 7 | 12.141 | 50.590 | 0.933 | 0.693 | 4444657.038 | 0.890 | 0.882 |
| gen_hydUD | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.470 | 0.470 |
| cap_electrolyzer | 7 | 11.635 | 56.764 | 0.963 | 0.707 | 85187065.891 | 0.907 | 0.918 |
| cap_H2-CC | 4 | 1.412 | 36.060 | 0.600 | 0.300 | 26.922 | 0.850 | 0.849 |
| cap_Gas-CC_Gas-CC-CCS_mod | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.299 | 0.299 |
| cap_Gas-CC_H2-CC | 5 | 25.883 | 57.467 | 1.000 | 0.926 | -4.180 | 0.642 | 0.553 |
| cap_nuclear-smr | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.207 | 0.207 |
| cap_pumped-hydro | 1 | 0.000 | 0.324 | 0.080 | 0.033 | 0.021 | 0.562 | 0.561 |
| cost_inv_itc_payments_negative | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.057 | 0.057 |
| cap_hydUD | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.421 | 0.421 |

Figure: figs/fig07_region_r2.
