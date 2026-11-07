# PESGM supporting analysis for the ReEDS surrogate (ReEDS-Proxy)

One script per item of the paper's depth request; `results.md` collects every
number as a sentence, `figs/` holds the IEEE single-column figures (PDF +
300-dpi PNG) and `data/` the per-output tables behind them.

| Item | Script | Main outputs |
|---|---|---|
| 0 pipeline facts + timing | `00_pipeline_summary.py` | `data/00_pipeline_facts.json`, `data/00_timing.csv` |
| 1 interval calibration | `01_calibration.py` | `fig01a_reliability`, `fig01b_coverage_hist`, `data/01_*` |
| 2 learning curve | `02_learning_curve.py` | `fig02_learning_curve`, `data/02_*` |
| 3 leave-one-level-out | `03_leave_level_out.py` | `fig03_lolo_headline`, `data/03_*` |
| 4 constraint / merging ablation | `04_ablation.py` | `data/04_ablation.csv` (table in results.md) |
| 5 dial sensitivity (ANOVA) | `05_anova_sensitivity.py` | `fig05a_variance_shares`, `fig05b_truth_vs_rf`, `data/05_*` |
| 6 failure classes | `06_failure_classes.py` | `fig06_r2_vs_activation_cv`, `data/06_*` |
| 7 regional detail | `07_regional.py` | `fig07_region_r2`, `data/07_*` |
| 9 constraint-layer check (pre-fix code; no longer runs) | `09_constraints_check.py` | `constraints_check.md`, `data/09_*` |
| 10 results after the constraint fix | `10_after_fix.py` | `results_after_fix.md`, `buckets`, `r2_ranking_rf`, `ba_heatmap_rf` (raw OOF scores), `data/10_*`, `data/after_fix/` (constrained per-output metrics, reference only); reads `data/12_corridor_floor_vs_init.csv` |
| 11 dashboard check | `11_dashboard_check.py` | `data/11_dashboard_check.json` |
| 12 corridor floors vs initial capacity | `12_corridor_floors.py` | `data/12_corridor_floor_vs_init.csv` |
| 13 numbers behind the claims check | `13_claims_check.py` | `claims_check.md`, `data/13_claims_numbers.json` |
| 14 candidate paper figures (no fitting) | `14_paper_figures.py` | `figs/*` (ercot_map … learning_curve), `figs/captions.md`, `data/14_figure_numbers.json` |
| 15 dashboard screenshots (needs a running server + Chrome) | `15_dashboard_screenshots.py` | `figs/dashboard_predict`, `figs/dashboard_ci` |
| 16 contact sheet | `16_contact_sheet.py` | `figs/contact_sheet.png` |
| 18 XGBoost without monotone hints (refits XGBoost only, ~2 min) | `18_xgb_nohints.py` | `xgb_nohints.md`, `data/18_*`, `figs/model_comparison` |

The constraint fix itself is described in `constraint_fix_changelog.md`.

Run everything from this folder with the `reeds2` conda env (the env the
stored artefacts were trained in; sklearn 1.2.2, xgboost 3.2.0, ngboost 0.5.8):

```powershell
$py = "C:\Users\ychen10\AppData\Local\anaconda3\envs\reeds2\python.exe"
& $py 00_pipeline_summary.py   # ~5 min (fits all 7 model families twice)
& $py 01_calibration.py        # ~20 min (RF + NGBoost 10-fold CV, both layers)
& $py 02_learning_curve.py     # ~20 min (35 RF cross-validations)
& $py 03_leave_level_out.py    # ~2 min
& $py 04_ablation.py           # ~6 min
& $py 05_anova_sensitivity.py  # ~1 min
& $py 06_failure_classes.py    # seconds
& $py 07_regional.py           # seconds
& $py build_results.py         # assembles results.md
```

The scripts import the Stage 2 surrogate modules from
`postprocessing/reedssurr/Stage2/code` (data loading, target clipping,
constraint helpers) and read the stored out-of-fold residuals from the model
artefacts resolved by `surrogate_paths.resolve_models_dir` (OneDrive, or the
`REEDSSURR_MODELS_DIR` environment variable). Nothing is written back to the
Stage 2 folders and no ReEDS run is repeated.
