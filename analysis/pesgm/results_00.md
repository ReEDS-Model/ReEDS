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
