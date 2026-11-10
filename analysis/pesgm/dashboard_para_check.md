# Dashboard paragraph check (read-only, 2026-11-09)

Checked against `postprocessing/reedssurr/Stage2/code/reeds_proxy.py`, `surrogate_uq.py`,
`surrogate_constraints.py` (working tree, uncommitted constraint fix included), the stored RF
artefacts and the training tables. No code, artefact or figure was changed; the two measurements
below ran from scratch copies outside the repo.

## 1. Dashboard features — TRUE, with one wording point (CI vs PI)

- **Six controls.** `design_selects` builds a Bokeh `Slider` for Dem, Fuel, REcost, Siting and Batt
  (range 0 to 2, step 0.05, default 1 = Md/Ref) and a `Select` for Pol (IRA / OBBBA)
  (`reeds_proxy.py:534-556`). Five sliders + one policy selector: TRUE.
- **System / regional toggle.** `stage_select` ("Layer") switches between the Overall and Regional
  layers in place (`:570-576`); a Model selector and a variable selector (Capacity / Generation /
  System cost / Transmission) sit beside it. TRUE.
- **90 % band displayed.** The bottom panel colours each predicted slice by 90 % half-width / |value|,
  the hover tooltips print "90% CI: ±…", and a colour bar is titled "90% CI / |value| (%)"
  (`:777, :974-977, :1004, :1682`). TRUE.
- **Band label in the UI.** The header text says "90% conformal CI" and every tooltip, title and colour
  bar says "CI" (`:650, :777, :974, :1004, :1564, :1682`). The band is a prediction interval for a new
  design, so if the paper calls it a PI the UI label disagrees: NEEDS REWORDING (either say
  "90 % conformal interval (labelled CI in the dashboard)" or keep "90% bands" as the paragraph does).
- **In-between slider positions.** The header says "Continuous dials for Dem / Natural gas price /
  REcost / Siting / Batt (Pol stays binary)" (`:646`). For any design that is not an exact training
  combination the status line reads "This exact design isn't in the training data — showing the
  ReEDS-Proxy prediction only." (`:1880-1881`) and the metrics panel adds "No training run matches
  this exact design — showing the ReEDS-Proxy prediction only." (`:1720`). There is no note that
  in-between positions are interpolations of a tree ensemble. The paragraph's "Other settings,
  including positions between levels, require running the trained models" is TRUE.
- Extra: on off-grid designs the metrics panel prints a speed-up computed against a fixed 30 min
  ("ReEDS reference: ~30–60 min ⇒ ~N× speedup", `:1683`), not against the 37–63 min range in the
  paragraph.

## 2. Band construction — TRUE

- `surrogate_uq.conformal_widths` returns `np.quantile(|oof_residuals|, 0.90, axis=0)` per output
  (`surrogate_uq.py:40-52`), with `CONFORMAL_ALPHA = 0.1` in the dashboard (`reeds_proxy.py:113`).
  Per-output 90th percentile of absolute OOF residuals: TRUE.
- The width depends only on the stored residuals, not on the design, so it is the same at every
  slider position (`_half_agg_for_view`, `:1121-1145`, takes no design argument). TRUE.
- It is applied symmetrically, point ± half (`prediction_interval`, `surrogate_uq.py:56-78`; the
  dashboard tooltip prints "±"). TRUE.
- **Which residuals when the model is switched.** `_half_agg_for_view(artifact, …)` is called with
  `artifact = _get_artifact(model_name)` for the model currently selected (`:1535, :1817`), and
  `_get_artifact` reloads the artefact when the model or layer changes (`:494-510`). So the band always
  uses the selected model's own OOF residuals on the active layer. Held-constant outputs get zero width;
  the derived `cost_total` keeps the width of its own stored residuals.

## 3. Coverage after the constraint layer — TRUE (still about 0.90)

Method (evaluation only, 43 s): for each of the 486 runs the stored RF OOF prediction (training value
minus stored residual) was passed through the dashboard's OOF path, `apply_constraints(...)` with the
layer's constants and transmission floors, and for the regional layer with `overall_pred` = the
constrained system OOF of the same run. The stored per-output 90 % half-widths were then applied to the
constrained prediction and coverage = fraction of the 486 runs with |truth − prediction| ≤ half-width.
"Before" is the same statistic on the raw OOF prediction (the in-sample 0.899 the paper quotes).

| Layer | Outputs | Median coverage before | Median after | Mean after | Min after | Outputs < 0.85 after | Outputs whose prediction the layer changed | Outputs whose coverage moved |
|---|---|---|---|---|---|---|---|---|
| System | 66 | 0.899 | 0.899 | 0.903 | 0.899 | 0 | 3 | 1 |
| Regional | 308 | 0.899 | 0.899 | 0.902 | 0.856 | 0 | 274 | 234 |

- System: only `cost_total` moves (0.899 → 0.922, because the derived total is more accurate than the
  directly predicted one); the clip touches nothing at these predictions.
- Regional: the additivity rescale shifts 274 outputs; coverage moves by at most ±0.04 on individual
  outputs and the median is unchanged. Largest drops: `gen_hydEND_p63/p64/p65` 1.000 → 0.885 (near-
  constant outputs whose raw prediction was exact; the rescale moves them by a few MWh), `cap_gas-ct_p63`
  0.899 → 0.856, `gen_wind-ons_p64` 0.899 → 0.856. Largest gains: `cost_op_h2_transport_intrareg_p63`
  0.899 → 0.938, `gen_wind-ons_p63` 0.899 → 0.934.

Sentence to paste: "Applying the stored 90 % band widths to the constrained out-of-fold predictions
leaves the median per-output coverage at 0.899 on both layers (mean 0.903 system, 0.902 regional) with
no output below 0.85, so the constraint layer does not degrade the band's empirical coverage."

Caveat the paragraph already makes: this is the in-sample check (widths and coverage from the same
486 residuals). The honest cross-fold number for the raw RF band is 0.902 (results_01.md); the
cross-fold check was not repeated with the constraint layer.

## 4. Timing — training grid TRUE in spirit, off-grid regional NEEDS REWORDING

Re-run of the `17_timing.py` measurement from a scratch copy (outputs kept outside the repo; the
committed `timing.md` / `data/17_timing.csv` of 2026-11-06 were not touched). Same method: the
dashboard script runs in-process, its own `_redraw()` is called, one warm-up then 10 timed redraws per
case, medians reported; browser paint is not included. Machine: YCHEN10-42133S laptop, Intel Core
Ultra (family 6 model 170, 14 logical CPUs), Windows 11 Enterprise build 26200 (platform.release()
reports it as "10"), env reeds2, RF model, otherwise idle.

| Layer | Path | Inference | Constraints | Conformal | Rendering | **Total median** | Total min–max (10 reps) | 2026-11-06 total |
|---|---|---|---|---|---|---|---|---|
| System | training grid (OOF lookup) | 0.0 | 3.8 | 2.5 | 24.9 | **32 ms** | 22–47 ms | 22 ms |
| Regional | training grid (OOF lookup) | 0.0 | 39.0 | 7.6 | 67.8 | **121 ms** | 97–184 ms | 113 ms |
| System | off-grid (final model) | 2,889.6 | 7.1 | 2.5 | 19.9 | **2.91 s** | 2.51–3.21 s | 2.06 s |
| Regional | off-grid (final model) | 14,835.0 | 80.5 | 9.1 | 72.6 | **15.0 s** | 7.8–16.8 s | 11.3 s |

- "about 20 ms" system-wide on the training grid: measured 22 ms on 11-06 and 32 ms today. NEEDS
  REWORDING to "about 20–30 ms" (or "tens of milliseconds").
- "110 ms" regional on the training grid: 113 ms and 121 ms. TRUE as "about 110–120 ms".
- "2–4 s" system off-grid: medians 2.06 s and 2.91 s, today's spread 2.5–3.2 s. TRUE; the range holds.
- "11 s" regional off-grid: 11.3 s on 11-06 but 15.0 s today (spread 7.8–16.8 s; the earlier run
  also noted 11.0–11.2 s). NEEDS REWORDING to a range, e.g. "11–15 s". The variation is the joblib
  worker-pool dispatch of 308 + 66 forests on Windows, not the trees.
- Consequence for item 5: with 11–15 s the regional speed-up is 2,220 / 15 = 148 to 3,780 / 11 = 344,
  i.e. "about 150–350 times" instead of "200–350 times"; the system-wide "550–1,900" still holds.

## 5. Arithmetic — TRUE as rounded

37 min = 2,220 s and 63 min = 3,780 s; 2,220 / 4 = 555, 3,780 / 2 = 1,890 (system), 2,220 / 11 = 201.8,
3,780 / 11 = 343.6 (regional). The paragraph's "about 550–1,900" and "200–350" are correct roundings.
With the exact run times (2,228 s and 3,791 s) the figures are 557–1,895 and 203–345.

## 6. ReEDS run time — TRUE

`runtime_seconds` over the 486 runs: min 2,228.3 s = 37.1 min, max 3,791.0 s = 63.2 min, median
2,779.1 s = 46.3 min, mean 46.6 min. "37–63 minute" is the min–max: TRUE. The dashboard's own speed-up
line uses 30 min instead (item 1).
