# Paper claims vs code and stored results

Checked on 2026-11-06 against commit `3a407ae3` (branch `yc/reedssurr`) and the stored OOF
predictions. Nothing was fixed. Code paths are under `postprocessing/reedssurr/Stage2/code/`. The
numbers come from `13_claims_check.py` (`data/13_claims_numbers.json`), `10_after_fix.py`
(`results_after_fix.md`) and `00_pipeline_summary.py` (`results_00.md`). R² values are RF raw
out-of-fold (OOF), scored against the raw ReEDS targets, unless a row says otherwise.

**Verdict counts: 11 FALSE, 20 NEEDS REWORDING, 29 TRUE, 1 not checkable.** The FALSE rows are 1b
(fuel dial direction), 6 (system constants), 11 (grid search), 13 (interval method), 14 (1 ms), 40
(543 MW), and in the draft D3 (2025), D6 (interval), D9 (rule order), D12 (0.630) and D13 (dGen
curve).

## Design and data

| # | Claim | Verdict | Evidence | Suggested wording |
|---|---|---|---|---|
| 1 | Six dials: demand, gas/coal price, wind+solar capex, wind+solar siting, battery capex at Lo/Md/Hi, policy IRA/OBBBA | NEEDS REWORDING | `inputs/casematrix_surrogate_ercot.yaml`: the fuel dial sets only `ngscen` (AEO 2025 low / reference / high oil-and-gas), so coal price is not varied. The RE cost dial switches ATB 2024 advanced / moderate / conservative for UPV, onshore **and offshore** wind. Siting switches UPV, onshore and offshore wind open / reference / limited. Battery uses ATB 2024 advanced / moderate / conservative. Demand uses EER2025 load profiles (Baseline_AEO2023 / IRAlow / 100by2050). Policy is the `incentives_suffix` ira / obbba, with tax credits phased out by 2032 under OBBBA. | "natural gas price (AEO 2025 low/reference/high)", "wind and solar technology cost (ATB 2024 advanced/moderate/conservative)" |
| 1b | Fuel dial levels Lo/Md/Hi mean low/medium/high gas price | FALSE | **The levels run in the opposite direction to price.** FuelLo = `AEO_2025_LOG` (low oil-and-gas supply) is the **highest** price: 8.46 $/MMBtu in 2050 for East North Central (`inputs/fuelprices/ng_AEO_2025_LOG.csv`). FuelHi = `AEO_2025_HOG` is the lowest, at 2.42. The ReEDS outputs agree: mean gas-CC generation is 62 / 249 / 329 TWh at x_Fuel = 0 / 1 / 2. Knock-on: the XGBoost monotone hints assume a higher x_Fuel means a higher price (`surrogate_constraints.py:163, 179`), so they point the wrong way for this dial (see `known_limits.md`). | "natural gas supply (AEO 2025 low / reference / high supply, i.e. high / reference / low price)", or relabel the levels by price |
| 2 | 3^5 × 2 = 486 runs, all through 2050 | TRUE | 486 rows in the training CSV; the case-matrix header says 3×3×3×3×3×2 = 486; `cases.csv:7` endyear = 2050 | |
| 3 | Outputs at the 2050 solve year | TRUE | `Stage1/data_processing/build_overall.py:49` and `build_regional.py:48` set `TARGET_YEAR = 2050` | |
| 4 | Inputs encoded ordinal 0/1/2 for the five dials, one-hot (or 0/1) for policy | NEEDS REWORDING | Six numeric columns. `x_Dem`, `x_Fuel`, `x_REcost`, `x_Siting`, `x_Batt` take 0/1/2 (Siting: Open = 0, Ref = 1, Lim = 2). `x_Pol` is a single 0/1 column (IRA = 0, OBBBA = 1), not one-hot. All six are standardized per training fold (`surrogate_ml_models.py:406`). The dashboard sliders accept any value in 0-2 (`reeds_proxy.py:536`). | "five ordinal dials coded 0/1/2 and a binary policy flag (0 = IRA, 1 = OBBBA), standardized before fitting" |
| 5 | 66 system and 308 regional outputs after dropping constants | TRUE | `load_data` with `min_variance_threshold` = 1e-10. One of the 66 is `runtime_seconds`, a ReEDS solve time, so 65 are energy-system outputs. | Optionally: "65 system quantities plus the ReEDS run time" |
| 6 | 7 system and 57 regional constant columns held at their ReEDS value | FALSE (system count) | **8** system constants: cap_distpv 12,994.6 MW, cap_hydED 142, cap_hydEND 405.8, cap_lfill-gas 24.4, and gen_Gas-CT_H2-CT, gen_coal-igcc, gen_coal-new, gen_wind-ofs, which are all 0. There are 57 regional constants, 18 of them non-zero. | "8 system (4 of them always zero) and 57 regional constant columns" |
| 7 | Wind and solar resource classes merged into one aggregate per technology before training | TRUE | The `*_merged.csv` inputs come from `merge_resource_classes.py` (wind-ons, wind-ofs and UPV classes). Before merging, 2 system and 4 regional class outputs had R² < 0 (minimum −0.25 / −0.30). After merging, system wind and UPV R² ≥ 0.96, and aggregate R² is unchanged (`results_04.md`). | |
| 8 | Output families: capacity (MW), generation (MWh), 21 cost components + cost_total, transmission (11 corridors + tran_total) | NEEDS REWORDING | System: 19 cap, 22 gen, 22 cost (21 components + cost_total), **2** tran (tran_total and tran_AC_total, which are identical), and 1 runtime. Regional: 81 cap, 91 gen, 126 cost, **10** modelled corridors; the 11th, p63-p64, is constant. Cost is in dollars for the 2050 solve year from ReEDS `systemcost`. The dollar basis was not verified, and the dashboard axis says "$B, NPV" (`reeds_proxy.py:1071`). | "transmission: tran_total at system level and 11 interzonal corridors (10 modelled, 1 constant)" |

## Models and evaluation

| # | Claim | Verdict | Evidence | Suggested wording |
|---|---|---|---|---|
| 9 | Six families: Ridge/Lasso, kNN, RF, XGBoost, NGBoost, MLP | TRUE | `Config.models` = knn, ridge, lasso, rf, xgb, nn, ngboost, so 7 models in 6 families | |
| 10 | Each a multi-output regressor | NEEDS REWORDING | `single_output_mode=True` (`surrogate_ml_models.py:136`) wraps every model in `MultiOutputRegressor` (`:274`), so each output gets its own independent model. XGBoost uses a per-output wrapper with monotone constraints. | "one independent single-output model per output (scikit-learn MultiOutputRegressor)" |
| 11 | Hyperparameters set by a small grid search inside the training folds | FALSE | No search exists; all values are fixed. Ridge α = 1.0 (`:202`). Lasso α = 0.1 (`:204`). kNN k = 3, distance-weighted (`:125`). RF: 200 trees, no depth limit, min_samples_leaf = 2 (`:207`). XGBoost: 200 trees, depth 6, learning rate 0.1, per-output monotone hints (`:218`). MLP: (64, 32), relu, adam, α = 1e-3, 3,000 iterations, no early stopping (`:121`). NGBoost: 200 estimators, learning rate 0.05, Normal (`:128`). | "hyperparameters fixed at common defaults (listed in Table X); no tuning" |
| 12 | 10-fold OOF CV, seed 42, same folds for all models | TRUE | `KFold(n_splits=10, shuffle=True, random_state=42)` (`:391`, `:106-107`) on the same row order for every model, so the folds are identical | |
| 13 | 90% interval from the RF ensemble spread or NGBoost's predictive distribution | FALSE | The dashboard and `surrogate_uq.prediction_interval` use split-conformal intervals for every model: point ± the 90% quantile of the absolute OOF residual for each output (`surrogate_uq.py:41-53`, `reeds_proxy.py:111, 1116`). Tree spread is never used. `ngboost_interval` (Normal mean ± z·σ) exists but the dashboard does not call it. | "a 90% split-conformal interval: the prediction ± the 90th percentile of the model's absolute out-of-fold residual for that output" |
| 14 | Query time about 1 ms per prediction | FALSE | Dashboard path for one design (`results_00.md`): RF 3.0 s system and 16.4 s regional. With in-process dispatch it is 0.56 s and 3.7 s. MLP 0.27 s / 0.86 s, XGBoost 0.07 s / 0.38 s, Ridge 0.16 s / 0.19 s. None is near 1 ms. | "about a second per design for the system layer (RF), against 37-63 min per ReEDS run" |
| 15 | ERCOT ReEDS run 30-60 min | NEEDS REWORDING | `runtime_seconds`: 37.1-63.2 min, median 46.3 | "37-63 min (median 46)" |

## Results (raw OOF, no constraints)

| # | Claim | Verdict | Evidence | Suggested wording |
|---|---|---|---|---|
| 16 | RF 0.75/0.88/29 system, 0.63/0.72/76 regional | TRUE | 0.749 / 0.882 / 29; 0.625 / 0.715 / 76 (0.6251 rounds to 0.63). Matches `summary.json`. | |
| 17 | MLP 0.71/0.87/28, 0.55/0.68/76 | TRUE | 0.712 / 0.870 / 28; 0.547 / 0.679 / 76 | |
| 18 | NGBoost 0.71/0.81/23, 0.56/0.59/59 | TRUE | 0.711 / 0.815 / 23; 0.559 / 0.590 / 59 | |
| 19 | kNN 0.60/0.70/7, 0.45/0.54/1 | TRUE | 0.595 / 0.696 / 7; 0.452 / 0.536 / 1 | |
| 20 | XGBoost 0.53/0.82/21, 0.24/0.48/42 | NEEDS REWORDING | Those are the hinted model (stored OOF: 0.532 / 0.820 / 21; 0.241 / 0.484 / 42), whose hints point the wrong way for the fuel and siting dials. Refit without hints, which is now the dashboard model: 0.676 / 0.882 / 29 (system) and 0.399 / 0.668 / 77 (regional) (`xgb_nohints.md`) | "XGBoost 0.68/0.88/29, 0.40/0.67/77" |
| 21 | Ridge/Lasso 0.45/0.45/3, 0.31/0.26/0 | NEEDS REWORDING | Ridge 0.4454 / 0.449 / 3. **Lasso mean is 0.4449, which rounds to 0.44.** Regional 0.308 / 0.259 / 0 for both. | "Ridge 0.45 / 0.45 / 3, Lasso 0.44 / 0.45 / 3" |
| 22 | Buckets, RF: system 44% / 53% / 3% (≥0.9, 0-0.9, <0); regional 25% / 68% / 8% | TRUE | System 29 / 35 / 2 of 66 = 43.9 / 53.0 / 3.0%. Regional 76 / 208 / 24 of 308 = 24.7 / 67.5 / 7.8%. | |
| 23 | cost_total R² 0.90 | TRUE | 0.8975 | |
| 24 | Operating cost components 0.92-0.98 | NEEDS REWORDING | Of the 13 `cost_op_*` outputs, 10 are 0.918-0.993. cost_op_startcost is 0.878, and cost_op_co2_incentive_negative is 0.259 (active in only 9 runs). | "most operating cost components 0.92-0.99 (start-up cost 0.88; CO2 incentive 0.26)" |
| 25 | tran_total R² 0.97 | TRUE | 0.9746 | |
| 26 | Wind / UPV / gas-CC / battery capacity and generation 0.93-0.99 | TRUE | cap / gen: wind-ons 0.989 / 0.986, UPV 0.967 / 0.963, gas-CC 0.953 / 0.990, battery 0.926 / 0.941 | |
| 27 | cap_nuclear R² = −0.36 with negligible absolute error | TRUE | R² −0.362. ReEDS cap_nuclear takes only 2 values (4,980 and 4,897.9 MW), with σ = 3.7 MW. MAE 0.58 MW (0.01% of the mean), worst error 82 MW. | |
| 28 | H2 production/storage, H2-CT, SMR, CCS retrofits built in <10% of the 486 runs | NEEDS REWORDING | Share of runs with a non-zero value: H2 production 2.1%, H2 storage 2.9%, SMR 1.9%, gas-CC CCS retrofit 2.3%. But **H2-CT 15.4%**, **coal CCS retrofit 76.5%**, gas-CC-CCS new 35%, H2-CC 14.4%, electrolyzer 16.9%. | "H2 production and storage, nuclear SMR and gas-CC CCS retrofits are built in under 3% of runs; H2 turbines and electrolyzers in 14-17%" |
| 29 | Per-BA: the poorly predicted band is the same sparse/near-constant set in every region | NEEDS REWORDING | 63 of the 83 regional outputs with R² < 0.5 are sparse (built in < 50% of runs) or near-constant (CV < 5%). Of the 47 variables modelled in at least 3 BAs, only 2 are poor in every BA. 15 are never poor, and 30 are poor in some BAs only. Region mean R² ranges from 0.54 (p60) to 0.74 (p61). | "poorly predicted per-BA outputs are mostly sparse or near-constant technologies (63 of 83 with R² < 0.5), but which BAs are poor varies by technology" |

## Constraints (RF unless stated)

| # | Claim | Verdict | Evidence | Suggested wording |
|---|---|---|---|---|
| 30 | Order: constants held, clip to lower bound, floor-preserving rescale with mixed-sign guard, cost identity | TRUE | `surrogate_constraints.py:447-454` | |
| 31 | Without rules: cost_total >1% off in 355/486 runs | TRUE | 355 (stored OOF + clip, no cost identity) | |
| 32 | Without rules: regional sums >1% off in 63.5% of 23,544 pairs | TRUE | 14,943 / 23,544. Of 30,618 pairs, the 7,074 with a system value of 0 are excluded; worth saying in the paper. | "...of the 23,544 run-quantity pairs with a non-zero system value" |
| 33 | With rules: cost identity exact | TRUE | 0 runs off by more than 1%; the identity holds by construction | |
| 34 | Additivity violations cut 92.2%, 1,167 remain, all skipped by the mixed-sign/zero-sum guard | TRUE | 14,943 → 1,167. All 1,167 are pairs where the rescale was not applied: 1,031 signed quantities (battery and pumped-hydro net generation, PTC payments) and 136 with a zero regional sum. | |
| 35 | Regional mean/median R² 0.625/0.715 → 0.632/0.714 | TRUE | 0.6251 / 0.7151 → 0.6316 / 0.7137 | |
| 36 | System mean unchanged at 0.749 | TRUE | 0.7490 → 0.7492; the only system change is cost_total | |
| 37 | cost_total 0.898 → 0.912 | TRUE | 0.8975 → 0.9117 | |
| 38 | RF never predicts below a bound | NEEDS REWORDING | 0 of 4,860 corridor predictions are below the floor. But the stored RF OOF has 5 system cells below 0, all ≥ −0.028 dollars; this is float32 round-off in the stored residuals. Fitted in float64 there are none, because RF averages non-negative targets. | "RF never predicts below a bound beyond round-off" |
| 39 | MLP and Ridge predict below a bound on 1,144 and 1,022 of 4,860 corridor predictions | TRUE | 1,144 and 1,022 (more than 1% below the initial capacity) | |
| 40 | ...by up to 543 MW | FALSE | 543 MW was one dashboard design. Over all stored OOF predictions the largest shortfall is **1,104 MW for MLP** and **4,456 MW for Ridge**. | "by up to 1.1 GW (MLP) and 4.5 GW (Ridge)" |
| 41 | 0 below bound after the rules | TRUE | 0 corridors (MLP, Ridge, RF), and 0 system tran_total predictions below 34,478.6 MW. The duplicate `tran_AC_total` is not floored (37 MLP and 90 Ridge runs; `known_limits.md`). | |
| 42 | Corridor floor = min over training runs = initial capacity, all 11 corridors | TRUE | `data/12_corridor_floor_vs_init.csv`: the difference is 0.0 for all 11 (initial capacity = (forward + reverse ITL) / 2, z134) | |
| 43 | tran_total floor 34,478.6 MW | TRUE | Sum of the corridor floors = 34,478.6 MW = the minimum observed tran_total | |
| 44 | CF exceedances (regional, >1% above observed max): 796 raw → 993 after rules, of 29,519 | NEEDS REWORDING | 796 of **29,658** raw and 993 of 29,519 after the rules. The denominators differ because only predictions with predicted cap ≥ 1 MW are evaluated. | "796 of 29,658 → 993 of 29,519" |
| 45 | Dashboard: all 52 checks pass | NEEDS REWORDING | 56 of 56 now pass: the original 52, plus 4 for the system tran_total floor added in the final change (`data/11_dashboard_check.json`) | "all 56 checks pass" |

## Additional claims found in the Word draft (`IEEE PES 2027/ReEDS_surrogate_IEEEPES_v0.docx`)

| # | Claim (draft) | Verdict | Evidence | Suggested wording |
|---|---|---|---|---|
| D1 | "a single case through 2050 solves in 30-60 minutes on the Kestrel HPC" | NEEDS REWORDING | 37-63 min, median 46 (`runtime_seconds`) | "about 45 minutes (37-63)" |
| D2 | "seven model balancing areas"; "ReEDS has resolution of 134 model balancing areas"; "roughly 400 switches" | TRUE | z134 `hierarchy.csv` has 134 regions; ERCOT = p60-p65 and p67 (**p66 is MISO**); `cases.csv` has 383 switch rows | For figure labels: "p60-p65, p67" (not p60-p67) |
| D3 | "all at the 2050 solve year. The years can be any future years but we use 2025 as the example" | FALSE | All outputs are 2050 (`TARGET_YEAR = 2050`) | "...but we use 2050" |
| D4 | Outputs reported in GW, TWh and billion dollars | NEEDS REWORDING | The stored data is MW, MWh and dollars; GW, TWh and $B are display units | Keep the display units, but convert any numbers taken from the data |
| D5 | "merged the classes ... This removed the worst group of failures at no cost to the quantities users consume" | NEEDS REWORDING | Merging removed 2 system and 4 regional class outputs with R² < 0, and aggregate R² is unchanged. The worst failures overall (cap_nuclear, H2 costs) are unrelated to merging. | "...removed the negative-R² resource-class outputs without changing aggregate accuracy" |
| D6 | "Uncertainty is reported as a 90% interval from the spread of the Random Forest ensemble, or from NGBoost's predictive distribution" | FALSE | See row 13 | See row 13 |
| D7 | "The model and its loss function are untouched" | NEEDS REWORDING | True for the loss function. Training targets are clipped at 0 before fitting, which changes 4 cells by ≤ 3e-6 dollars. | "...the loss is untouched; only 4 training targets (solver round-off) are clipped" |
| D8 | "In early testing we saw all three: negative values, ..." | NEEDS REWORDING | Negative predictions appear only in an RF fitted to raw targets: 0.29% of cells, all in cost_op_h2_transport_intrareg, all ≥ −3e-7 dollars. "Negative capacity" never occurs for RF. | "negative values (rare and tiny for RF; frequent for MLP and Ridge)" |
| D9 | "At prediction time the rules run in a fixed order: exogenous override, regional rescaling, clipping, then the cost identity" | FALSE | The committed order is constants held → clip to lower bound → regional rescale → cost identity (row 30) | Use the order in row 30 |
| D10 | "Regional additivity scales all regional predictions of a quantity by one factor, s = y_sys / Σ_r y_r" | NEEDS REWORDING | Constant regions are held and subtracted from the target; only the increment above each floor is scaled; quantities with negative values are skipped | "...scales the regional increments above each known floor by one factor so that they sum to the system prediction (constant regions held fixed; signed quantities skipped)" |
| D11 | "Without them, the Random Forest gives negative values in 0.29% of must-be-positive system cells" | TRUE (with a caveat) | 86 of 29,160 cells, from the RF fitted to raw targets. The stored model is trained on clipped targets and has none beyond round-off. | Add: "(when fitted to unclipped targets)" |
| D12 | "regional ... slightly higher (0.630)" | FALSE (stale) | Now 0.632 / 0.714 (row 35) | "0.632" |
| D13 | Table II row 3: "set from the dGen [16] curve scaled with the demand input" | FALSE | The dGen curve is removed; cap_distpv is held at 12,994.6 MW, identical in all 486 runs | "Held at its ReEDS value (identical in all runs)" |
| D14 | Table II row 1: "Clip at zero, on training targets before fit and on predictions" | NEEDS REWORDING | The prediction-time bound is now 0, the initial capacity for corridors, and 34,478.6 MW for tran_total. The training-time clip is negligible (4 cells). | "Clip at the known lower bound (0; initial corridor capacity; total initial capacity for tran_total)" |
| D15 | "ERCOT has no synchronous ties to the rest of the country, so it can be run on its own" | not checkable | This is domain knowledge, not something the code shows | |
