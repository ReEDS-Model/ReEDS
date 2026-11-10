# Independent cross validation and uncertainty audit

Completed 2026-11-10. **Table III and current fold-local training pass the executed checks. The original UQ procedure fails the description “split conformal” and is not independently validated by its existing cross-fold coverage diagnostic. A new, separate split-conformal RF evaluation obtains approximately 90.8% average coverage, but rare nonzero outcomes remain poorly covered.**

No production pipeline, trained artifact, existing analysis, or manuscript was modified. No ReEDS simulations were run. New RF fits were confined to this standalone validation. This report supersedes neither the production UQ implementation nor its saved artifacts.

## Audit table

PASS means the stated check was executed and passed; it does not mean every possible generalization claim has been established.

| Check | Verdict | Executed evidence or limitation |
|---|---|---|
| Scenario uniqueness and system/regional alignment | PASS | 486 unique six-input vectors, exactly the 3^5 x 2 Cartesian design; input vectors and case-name order match across layers. |
| Current CV train/test separation and OOF placement | PASS | Ten disjoint splits, test sizes 49 x 6 and 48 x 4, zero overlapping rows; every row tested once. Instrumented the actual CV function for RF, MLP and NGBoost on both layers: 60 successful fit/predict checks. |
| Feature and target preprocessing | PASS | Executed spies verify scaler fit inputs equal training rows, model fit targets equal training targets (scaled where required), and prediction inputs equal held-out rows. NGBoost's fold-constant branch uses training statistics. |
| Global constant filtering | NEEDS REVIEW | Filtering uses the full target table before CV. In these data all 8/57 excluded outputs have exactly zero range and are constant within every training fold; no demonstrated inflation of the reported scores. Do not describe all target-dependent decisions as fold-local. |
| Table III and reported output counts | PASS | Independent SSE/SST calculation from saved OOF predictions/residuals matches all 42 numerical cells in the latest manuscript, across 66 system and 308 regional modeled outputs. |
| Historical model selection independence | NEEDS REVIEW | The current CV run uses fixed settings and does not fit to held-out targets. However, comments document prior MLP configuration changes, and RF is selected from the same CV comparison. No untouched model-selection test set or complete historical decision log was established. |
| Original intervals are split conformal | FAIL | Widths are ordinary pooled OOF-residual quantiles, applied around a different final/constrained predictor. There is no separate calibration set or split-conformal finite-sample rank in that path. |
| Original coverage is independent validation | FAIL | Production coverage reuses calibration residuals. The separate cross-fold diagnostic excludes the tested fold's residuals, but every model supplying other-fold residuals was trained on that tested fold. |
| New outer-test/proper-training/calibration isolation | PASS | All ten folds executed; 327–328 proper-training, 110 calibration, 48–49 test rows; all three sets pairwise disjoint. Each scenario has one outer-test prediction. |
| New finite-sample quantile | PASS | In every fold, q is the 100th order statistic among 110 calibration scores: ceil((110+1)*0.9)=100. Independently verified against sorted scores for every output and predictor. |
| New average 90% coverage result | PASS | Measured 90.86%/90.78% before constraints and 90.84%/90.76% after separate calibration of constrained predictions, system/regional respectively. This is an average, not a minimum per-output or simultaneous guarantee. |
| Rare-technology interval usefulness | NEEDS REVIEW | SMR capacity covers 0/9 nonzero cases; gas-CC CCS retrofit capacity 1/11. Approximately 90% overall coverage masks poor coverage when these technologies occur. |

Machine-readable checks: [cv_checks.json](cv_checks.json), [verification.json](verification.json), [audit_table.csv](audit_table.csv). Source hashes and environment versions: [manifest.json](manifest.json).

## Exact production code locations

All paths below are relative to the repository root.

| Operation | Location |
|---|---|
| Hyperparameters and defaults | `postprocessing/reedssurr/Stage2/code/surrogate_ml_models.py:105`, `:189`; prior MLP adjustment comments at `:120` and `:241` |
| Full-table constant filter and saved values | `surrogate_ml_models.py:315` through `:329`; variance threshold 1e-10 at `:119` |
| Deterministic target clipping | `surrogate_ml_models.py:335`; `surrogate_constraints.py:105` |
| KFold split | `surrogate_ml_models.py:392` (shuffle=True, random_state=42) |
| Training/validation row selection | `surrogate_ml_models.py:401` |
| Feature scaler fitted on training rows | `surrogate_ml_models.py:406` |
| NGBoost training-only constant mask and scaling | `surrogate_ml_models.py:418` |
| MLP target scaling | `surrogate_ml_models.py:437` |
| Model fitting, held-out prediction and OOF placement | `surrogate_ml_models.py:423`, `:430`, `:439`, `:443` |
| Per-output R2 and mean/median | `surrogate_ml_models.py:344` through `:375` |
| OOF evaluation before separate full-data final fit | `surrogate_ml_models.py:638` through `:659` |
| Production OOF residual quantile | `postprocessing/reedssurr/Stage2/code/surrogate_uq.py:41` through `:53` |
| Constrained prediction with raw-residual width | `surrogate_uq.py:72` through `:77` |
| Same-residual coverage computation | `surrogate_uq.py:140` through `:153` |
| Other-fold residual diagnostic | `analysis/pesgm/01_calibration.py:86` through `:95`; RF OOF generation at `:143` |
| New executed control-flow audit | `analysis/pesgm/independent_cv_uq_audit.py:79` |
| New independent Table III reconstruction | `independent_cv_uq_audit.py:147` |
| New finite-sample quantile | `independent_cv_uq_audit.py:218` |
| New proper/calibration/test split and fits | `independent_cv_uq_audit.py:249` |
| New coverage/width summaries | `independent_cv_uq_audit.py:307` |

The full-data constants have range exactly zero. Their training-fold means differ from full-table means by at most 1.82e-12, attributable to floating-point arithmetic. Near-constant nuclear capacity remains in R2 aggregation; there is no broad near-constant exclusion rule. The training clip changes only two system cells and two regional cells, by at most 3e-6 in the stored dollar units. It is a fixed physical transformation, not an estimated preprocessing statistic. Corridor minima agree across all ten original training folds; this check does not rely on a held-out target value to improve the reported original bounds.

## Table III independently reproduced

The scores below use raw ReEDS targets. For six models, predictions are reconstructed as clipped training targets minus cached float32 OOF residuals; unhinted XGBoost uses its saved float64 OOF predictions. Columns and row alignment are checked. All mean differences from the current summary files are below 2.2e-9, and all median differences below 5.0e-9. The independent SSE/SST implementation also agrees with the pipeline scoring function. These checks verify numerical consistency and current control flow, not the historical provenance of every cached fit.

| Model | System mean | System median | System >0.9 | Regional mean | Regional median | Regional >0.9 |
|---|---:|---:|---:|---:|---:|---:|
| Random Forest | 0.749017 | 0.881858 | 29 | 0.625074 | 0.715130 | 76 |
| MLP | 0.712187 | 0.869586 | 28 | 0.547186 | 0.679189 | 76 |
| NGBoost | 0.710678 | 0.814737 | 23 | 0.558842 | 0.589776 | 59 |
| XGBoost | 0.676198 | 0.881946 | 29 | 0.398697 | 0.667805 | 77 |
| k-NN | 0.595155 | 0.695485 | 7 | 0.452153 | 0.536366 | 1 |
| Ridge | 0.445424 | 0.449229 | 3 | 0.308396 | 0.259140 | 0 |
| Lasso | 0.444865 | 0.449208 | 3 | 0.308400 | 0.259097 | 0 |

Full precision: [table_iii_recomputed.csv](table_iii_recomputed.csv). Every individual R2: [table_iii_per_output.csv](table_iii_per_output.csv). Eight system and 57 regional constants are excluded, not credited with perfect R2. The 66 system outputs include run time and two identical transmission totals; that matches the latest manuscript's explicit inventory.

## What the original uncertainty diagnostics establish

The deployment function takes an ordinary 90th percentile of the same pooled absolute OOF residuals used by `empirical_coverage`. Approximately 90% inclusion in that self-check is largely imposed by choosing that percentile. It cannot validate coverage for new cases.

The supporting cross-fold check is different: it excludes fold k's residuals when setting the width for fold k. But for any other fold j, the model producing residuals in j was trained on the complement of j, which includes k. Executed index checks confirm this dependency for every pair of distinct folds. Excluding residual entries alone does not create an independent outer test. This procedure is neither split conformal nor CV+ as implemented.

| Existing diagnostic | System mean coverage | Regional mean coverage | Regional minimum |
|---|---:|---:|---:|
| Pooled residual self-check, raw predictions | 90.276% | 90.306% | 89.918% |
| Other-fold raw residual widths, raw predictions | 90.214% | 90.213% | 89.095% |
| Other-fold raw residual widths, saved constrained predictions | 90.245% | 90.143% | 85.597% |

The manuscript's “about 90% ... both before and after” is numerically consistent as an average retrospective diagnostic. It is not independent evidence that each deployed band has 90% coverage. Furthermore, the dashboard may aggregate output widths into display categories; the new per-output evaluation below does not validate those aggregate bands. Full existing diagnostics: [existing_raw_and_constrained_coverage.csv](existing_raw_and_constrained_coverage.csv).

## New independent uncertainty evaluation

Settings were fixed before inspecting the results. Ten outer KFold splits use seed 42. Within each outer development set, a random 25% calibration subset uses seed 1042 + fold index. The six outer folds with 49 test cases use 327 proper-training and 110 calibration cases; the four with 48 test cases use 328 proper-training and 110 calibration cases.

Feature scaling, constant detection and corridor minima use only proper training. Every output is fitted separately with the study's RF settings (200 trees, minimum leaf size 2, no depth limit, seed 42). A proper-training-constant output receives its training mean. All 74 system and 365 regional original columns are processed; the full-data 66/308 mask is used only to present the same output population as Table III, never to decide which outputs can be learned in a fold. Outputs constant in proper training but varying later remain in evaluation.

For each fold, calibration and test rows are predicted by the same fitted model. Raw and constrained point predictors are evaluated separately. For the constrained predictor, the complete rule stack—including system predictions used for regional rescaling—is applied to both calibration and test predictions before calculating calibration residuals. No true system target is supplied to regional rescaling. No refit follows calibration.

For output j, the interval is prediction +/- q_j, where q_j is the 100th-smallest of 110 absolute calibration residuals. This is the exact finite-sample order statistic ceil((m+1)(1-alpha)), with no linear interpolation. The implementation also checks the infinite-width edge case when the requested rank exceeds m. The construction follows the split-conformal rank principle in [Angelopoulos and Bates, Section 1.1](https://arxiv.org/html/2107.07511v6).

| Point predictor | Outputs | Mean coverage | Median coverage | Minimum coverage | Outputs below 90% | Median across outputs of mean full width / output SD |
|---|---:|---:|---:|---:|---:|---:|
| System raw | 66 | 90.856% | 90.741% | 88.477% | 17 | 0.7575 |
| System constrained | 66 | 90.844% | 90.741% | 88.477% | 17 | 0.7575 |
| Regional raw | 308 | 90.781% | 90.535% | 87.243% | 89 | 1.0900 |
| Regional constrained | 308 | 90.756% | 90.535% | 87.037% | 95 | 1.0971 |

Every output is evaluated on 486 outer-test cases, one prediction per case. Width means weight folds by their number of test cases. Normalization uses full-table SD only as a descriptive reporting scale, not to construct intervals. Coverage below 90% for individual outputs is not, by itself, proof of a conformal implementation failure; finite observed coverage fluctuates, and multiple outputs are being examined.

### Headline system outputs after constraints

Widths below are **full interval widths**, not half-widths, averaged over outer-test cases. Complete raw and constrained results for every output, including all regional outputs, are in [uq_per_output.csv](uq_per_output.csv).

| Output | Coverage | Mean full width |
|---|---:|---:|
| Total cost | 91.15% | 8.560 billion USD |
| Total transmission | 89.09% | 7.440 GW |
| Wind capacity | 91.77% | 13.936 GW |
| Wind generation | 91.98% | 54.051 TWh |
| Solar capacity | 89.92% | 17.696 GW |
| Solar generation | 89.51% | 44.835 TWh |
| Gas-CC capacity | 91.98% | 15.623 GW |
| Gas-CC generation | 90.53% | 52.637 TWh |
| Battery capacity | 91.98% | 9.331 GW |
| Battery generation | 90.53% | 2.961 TWh |
| Conventional nuclear capacity | 93.62% | 1.082 MW |

The lowest constrained regional coverage is 87.04% for `cost_inv_transmission_intrazone_investment_p65`; its mean full width is 368.757 million USD. Per-region and per-fold detail is available in the CSV outputs.

### Rare technologies

“Active” here means absolute target greater than 1e-8 in native units; it is a diagnostic subset defined only after prediction. The conditional counts are descriptive and small, not a separate conformal guarantee.

| System output, constrained | Overall coverage | Nonzero cases covered / total | Coverage when nonzero | Mean full width |
|---|---:|---:|---:|---:|
| Nuclear SMR capacity | 90.33% | 0 / 9 | 0.00% | 107.224 MW |
| Gas-CC CCS retrofit capacity | 90.95% | 1 / 11 | 9.09% | 236.053 MW |
| H2 production investment cost | 90.95% | 2 / 10 | 20.00% | 8.806 million USD |
| H2 storage investment cost | 89.51% | 2 / 14 | 14.29% | 3.615 million USD |
| H2-CC capacity | 90.53% | 31 / 70 | 44.29% | 620.912 MW |
| H2-CT capacity | 90.74% | 34 / 75 | 45.33% | 839.411 MW |

Marginal coverage can be near nominal because zero outcomes dominate. A 90% absolute-residual quantile is not evidence of useful uncertainty for rare builds. [uq_rare_outputs.csv](uq_rare_outputs.csv) includes every modeled output nonzero in fewer than 10% of scenarios, at both layers; [uq_headline_outputs.csv](uq_headline_outputs.csv) includes the broader technology examples above.

## Full factorial and interpretation limits

- The target population is uniformly weighted combinations of the six sampled scenario levels. Shared levels between training and test folds are part of this question, not leakage. There are no duplicate input vectors.
- Deterministic simulator outputs do not inherently prevent conformal inference. Random allocation of the remaining fixed scenario catalogue can supply the symmetry needed for a marginal rank argument for a randomly selected held-out scenario, conditional on the proper-training set. It does not give a guarantee for a chosen scenario, a rare-build subgroup, intermediate inputs, new levels, or the national model.
- Outer folds reuse cases in other folds' training/calibration sets. Within each fold the separation is strict, but the 486 coverage indicators and the per-output results are not independent Bernoulli trials. No naive binomial confidence interval or assertion of independent fold repetitions is made.
- This new result validates the stated split-conformal protocol with 327–328 training cases, not the production forest refitted on all 486 cases with pooled OOF widths. It cannot be silently substituted as validation of the deployed dashboard method. The RF family and settings were inherited from an already developed study; this is not a nested assessment of the entire historical model-selection process.
- Calibration after constraints is essential to the interpretation here. Bands are per-output and need not satisfy the constraints jointly. Simultaneous coverage and the dashboard's grouped categories were not evaluated. The broad-band averages do not resolve the rare-build failure illustrated above.

## Comparison with the current manuscript and minimal wording corrections

Reviewed `PESGM2027_ReEDS_Surrogate_0.docx`, last locally modified 2026-11-10. Its SHA256 and executed direct comparison are in `verification.json`; relevant extracted paragraphs are in `manuscript_claims.txt`.

1. **Table III:** retain all values. All 42 numerical cells match. The counts 66/308 and excluded constants 8/57 are correct. No R2 update is needed.
2. **III.C model settings:** “We keep model settings fixed rather than choosing them based on test results” is stronger than can be verified about development history. Use: **“For the reported cross-validation, model settings were fixed and no automated hyperparameter search was performed. Model comparisons are exploratory and use the same folds.”**
3. **III.C deployed UQ method:** replace “following split conformal prediction” with **“using pooled absolute out-of-fold residuals.”** Add: **“These deployed bands are empirical residual-based bands; their existing cross-fold coverage check is a retrospective diagnostic, not independent validation.”**
4. **If reporting the new experiment in III.C/IV.E:** **“We separately evaluated RF uncertainty with ten outer test folds. Each outer development set was split into 327–328 proper-training and 110 calibration cases. We calibrated raw and constrained predictors separately using the 100th-smallest absolute calibration error per output. Mean outer-test coverage was 90.86%/90.78% for system/regional raw predictions and 90.84%/90.76% after constraints. This validates the separate split-conformal protocol, not the deployed pooled-OOF bands.”**
5. **Abstract and conclusion:** replace language that attributes independently validated 90% coverage directly to dashboard bands with **“A separate RF split-conformal evaluation achieved about 91% average coverage at a nominal 90%, although coverage was poor for rare technologies when built.”** If not including the new experiment, use **“The dashboard displays nominal 90% residual-based bands; independent coverage of the deployed bands remains unestablished.”**
6. **Limitations:** add **“Coverage is marginal over sampled scenario combinations, not simultaneous across outputs or conditional on a technology being built. For example, SMR capacity had 90.3% overall coverage but none of its nine nonzero cases was covered.”**

These are proposed text changes only. The manuscript and production pipeline remain untouched.

## Reproduction and delivered files

From `C:\ReEDS\ReEDS`, using the existing study environment:

```powershell
$py = 'C:\Users\ychen10\AppData\Local\anaconda3\envs\reeds2\python.exe'
$env:PYTHONDONTWRITEBYTECODE = '1'
& $py -B analysis\pesgm\independent_cv_uq_audit.py --jobs 10
& $py -B analysis\pesgm\verify_independent_audit.py
```

The executed RF fits and constraint processing took approximately 157 seconds across ten folds on this machine. The sandbox initially denied joblib's CPU-affinity/process access before any fold was fitted; the same script then completed with approved process access. No statistical settings changed. `--jobs 1` avoids the worker pool if necessary; the RF seed and statistical procedure are unchanged.

To recompute metrics from saved predictions without refitting:

```powershell
& $py -B analysis\pesgm\independent_cv_uq_audit.py --summarize-only
& $py -B analysis\pesgm\verify_independent_audit.py
```

- `manifest.json`: dependency versions, seeds, source/input hashes and completion flag.
- `cv_checks.json`, `verification.json`: executed assertions and manuscript matching.
- `table_iii_recomputed.csv`, `table_iii_per_output.csv`: all model comparisons.
- `existing_coverage_diagnostics.csv`, `existing_raw_and_constrained_coverage.csv`: old-method diagnostics, clearly distinct from independent evaluation.
- `split_assignments.csv`, `outer_folds.json`: every scenario's role in each fold, sizes, constants, floors and fit times.
- `outer_fold_00.npz` through `outer_fold_09.npz`: proper/calibration/test indices, fitted scaler statistics, fold-constant masks, calibration predictions/scores, test predictions and quantiles.
- `test_predictions_<layer>_<method>.npz`: all 486 test predictions, widths, targets and column names.
- `uq_summary.csv`, `uq_per_output.csv`, `uq_per_output_per_fold.csv`, `uq_headline_outputs.csv`, `uq_rare_outputs.csv`: coverage and interval widths, with native units and nonzero-case counts.
- `manuscript_claims.txt`: extracted current wording, without modifying the Word file.

The verification script independently checked saved quantiles against sorted calibration scores, all split disjointness, training-only scaler/constant statistics, coverage and widths, source hashes and all 42 manuscript Table III cells. All verification assertions passed. No new simulations, model-selection search, or changes to the existing pipeline were performed.
