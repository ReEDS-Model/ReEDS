# Figure captions (suggestions)

All figures are PDF + 300 dpi PNG in this folder; `contact_sheet.png` shows them all with their file
names. R² values come from 10-fold out-of-fold (OOF) predictions of the stored models, scored
against the raw ReEDS outputs, **without the constraint layer**, unless a caption says otherwise.
"RF" is the Random Forest. The numbers quoted below are in `../data/14_figure_numbers.json`.

## New figures (from `14_paper_figures.py` and `15_dashboard_screenshots.py`)

**ercot_map.** *Single column.* The seven ReEDS balancing areas of the ERCOT interconnection (p60–p65
and p67) used by the regional layer, shown inside the Texas state outline. Note that p66 is not an
ERCOT region. The outline includes the parts of Texas outside ERCOT.

**case_design.** *Single column.* Full-factorial case design: five three-level dials and a two-level
policy switch, 3⁵ × 2 = 486 ReEDS runs for ERCOT through 2050. The column headers give each
level's input encoding (0/1/2). The natural gas dial is labelled by AEO 2025 *supply* case, so its
"Lo" level is the high-price case. *Replaces `fig1_case_design.png` in the OneDrive folder.*

**buckets_rf.** *Single column.* Distribution of RF per-output OOF R². System layer (66 outputs):
29 (44%) ≥ 0.9, 25 (38%) 0.5–0.9, 10 (15%) 0–0.5, and 2 (3%) < 0. Regional layer (308 outputs): 76
(25%), 147 (48%), 61 (20%) and 24 (8%).

**r2_ranking_system.** *Single column, full column height.* RF OOF R² of the 66 system outputs,
ranked and coloured by family. The dashed line marks R² = 0.9. Bars are cut at −0.5, and negative
values are printed. The two outputs below zero are cap_nuclear (−0.36), which varies by at most
82 MW across the 486 runs, and cost_inv_h2_storage (−0.09), which is non-zero in 2.9% of runs.

**r2_ranking_regional.** *Single column.* RF OOF R² of the 308 regional (per-BA) outputs ranked from
best to worst, coloured by family. The dashed line marks R² = 0.9. 76 outputs reach 0.9, and 24
fall below 0, all of them above −0.5.

**ba_heatmap.** *Single column, tall.* RF OOF R² for each regional output (rows) and balancing area
(columns). Grey cells are not modelled: the technology is never built in that BA, or its value is
the same in all runs. The 29 rows above the line are regular outputs. The 33 rows below are mostly
sparse (non-zero in under half the runs) or near-constant (CV < 2%), and they hold most of the
poorly predicted cells.

**model_comparison.** *Single column.* Mean and median OOF R² of the seven models on the system
(top) and regional (bottom) layers, without constraints. XGBoost is refitted without monotone hints
(`../xgb_nohints.md`). RF has the highest mean on both layers, at 0.749 / 0.882 for the system layer
and 0.625 / 0.715 regional. XGBoost ties RF on the system median (0.882). *An alternative to Table III.*

**pred_vs_actual.** *Double column.* RF OOF prediction against the ReEDS value for six headline
outputs across the 486 runs, with the 1:1 line:
(a) total system cost, R² 0.90;
(b) transmission capacity, 0.97;
(c) onshore wind capacity, 0.99;
(d) utility PV capacity, 0.97;
(e) battery capacity, 0.93;
(f) gas-CC generation, 0.99.

**failure_classes.** *Single column.* RF OOF R² against the share of runs in which the output is
non-zero, for the system (66) and regional (308) outputs. The poorly predicted outputs are rarely
built technologies, such as H2 production and storage, nuclear SMR and gas-CC CCS retrofits, plus
cap_nuclear, which is almost constant. The diagnostic table classes 23 of 66 system outputs and
129 of 308 regional outputs as sparse.

**constraints_effect.** *Single column. Uses the constraint layer.* Counts of physically
inconsistent predictions without and with the prediction-time rules (log scale; 0 is printed):
- **Cost identity:** cost_total more than 1% from the sum of its 21 components, in 355 of 486 runs → 0.
- **Additivity:** regional sums more than 1% from the system prediction, in 14,943 of 23,544
  run-quantity pairs → 1,167. All 1,167 are pairs the guard skips: signed quantities, or a zero
  regional sum.
- **Below the floor:** corridor predictions more than 1% below the initial corridor capacity, out
  of 4,860: RF 0 → 0, MLP 1,144 → 0, Ridge 1,022 → 0.

All counts are for RF unless the bar names another model.

**dial_sensitivity.** *Single column.* Share of the variance of eight headline ReEDS outputs
explained by each dial's main effect (exact ANOVA on the balanced full factorial, no model). The
grey segment is all interactions. Natural gas supply dominates: it explains 60% of total cost, 71%
of transmission, 73% of wind capacity and 72% of gas-CC generation. Battery cost drives battery
capacity (59%). Interactions account for 6–28%.

**ci_coverage.** *Single column. Uses existing cross-validation results; nothing refitted.* Empirical
coverage of the deployed 90% split-conformal interval for each output. The interval width for each
fold is calibrated on the other nine folds, so the check is not circular. The median coverage is
0.899 for both layers, and no output is below 0.89. Twelve outputs reach 0.95–1.0: gen_distpv and
gen_hydEND at system level and in their BAs, which are almost exactly predictable. They are drawn
in the last bin.

**learning_curve.** *Single column. Uses existing results from `02_learning_curve.py`; nothing
refitted.* Mean RF OOF R² over the 66 system outputs against the number of training runs: 5 random
subsets at each n, with their mean. The mean rises from 0.46 (n = 50) to 0.70 (n = 300) and 0.75
(n = 486), and has not levelled off.

**dashboard_predict.** *Screenshot, 1,767 px wide.* ReEDS-Proxy Predict view for a held-out
case: the Md/Ref/IRA training run, shown with its RF out-of-fold prediction from the model that
excluded it. Bars compare ReEDS and surrogate 2050 capacity by technology.

**dashboard_ci.** *Screenshot, 1,767 px wide.* The same case's predicted capacity stack, with each
technology coloured by the width of its 90% interval relative to its value. The colour scale is
the dashboard's own red–green scale, which is not colorblind-safe. If the paper uses this figure,
mention that it is a screenshot.

## Earlier figures in this folder (from items 1–10)

- **buckets, r2_ranking_rf, ba_heatmap_rf** (`10_after_fix.py`): the same raw-OOF RF data in an
  earlier style. Superseded by buckets_rf, r2_ranking_system and ba_heatmap.
- **fig01a_reliability**: coverage against nominal level (0.5–0.95) for RF conformal, RF tree
  quantiles, NGBoost native and NGBoost conformal. **fig01b_coverage_hist**: per-output 90% coverage
  by method.
- **fig02_learning_curve**: an earlier learning curve with OOF and external-test panels.
- **fig03_lolo_headline**: leave-one-level-out extrapolation test.
- **fig05a_variance_shares** and **fig05b_truth_vs_rf**: the ANOVA shares for 14 outputs, and ReEDS
  against RF shares.
- **fig06_r2_vs_activation_cv**: an earlier two-panel version of failure_classes.
- **fig07_region_r2**: mean and median R² per BA.
- **fig08_ercot_bas**: a coloured BA map with county lines (an alternative to ercot_map).
