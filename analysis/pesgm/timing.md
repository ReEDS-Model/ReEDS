# Dashboard query timing (RF)

Measured 2026-11-06 with `17_timing.py` (reeds2 env) on YCHEN10-42133S: Intel64 Family 6 Model 170 Stepping 4, GenuineIntel, 14 logical CPUs, Windows 10. The dashboard script ran in-process and its own `_redraw()` was called. After one warm-up redraw, each case was timed 10 times; the values are medians in milliseconds. No code was changed: the dashboard's functions were wrapped with timers only. The full run log is in `data/17_timing.csv`.

**What each column measures:**

- **(a) Model inference:** the RF model call inside `predict`, excluding its constraint step. A regional query runs two models: the system RF for the rescale target, and the regional RF. For a training-grid design the dashboard skips the model and shows the stored out-of-fold prediction, so (a) is only a lookup.
- **(b) Constraint layer:** `apply_constraints`, plus computing the transmission floors from the training data.
- **(c) Conformal interval:** every `conformal_widths` call in the redraw. Each call recomputes the 90% quantile of the stored |residuals|.
- **(d) Rendering:** the rest of `_redraw`, which aggregates to display categories and updates the Bokeh data sources and figures on the server. **The browser's drawing time is not included.**

| Layer | Path | (a) inference | (b) constraints | (c) conformal | (d) rendering | Total | model calls | conformal calls |
|---|---|---|---|---|---|---|---|---|
| system | off-grid (final model) | 2,042.5 | 3.4 | 1.3 | 10.8 | 2,059.0 | 1 | 2 |
| system | training grid (OOF) | 0.0 | 2.8 | 1.8 | 17.2 | 21.8 | 0 | 3 |
| regional | off-grid (final model) | 11,196.7 | 45.7 | 6.9 | 40.0 | 11,289.1 | 2 | 2 |
| regional | training grid (OOF) | 0.0 | 40.5 | 8.1 | 63.3 | 112.6 | 0 | 3 |

First (warm-up) redraw totals in ms, which include loading the model files into the cache on first use: system off-grid (final model) 2,193; system training grid (OOF) 22; regional off-grid (final model) 11,744; regional training grid (OOF) 115.

**Notes:**

- **Training-grid designs:** the out-of-fold lookup (stored value minus stored residual) runs inside `_redraw`, so it is counted in (d). It takes well under 1 ms.
- **Why inference dominates:** the stored RF is a scikit-learn `MultiOutputRegressor` with `n_jobs=-1`. Every query sends one forest per output (66 system, 308 regional) to a joblib worker pool, and on Windows that overhead is most of the cost. The earlier pipeline timing (`results_00.md`) ran the same forests in-process: 0.56 s system and 3.7 s regional. Nothing was changed here.
- **Run-to-run spread:** model inference varies between runs of the script because of the worker
  pool and other machine load. In the first run of the same script on the same machine, the
  system off-grid median was 3,782 ms for inference and 3,813 ms in total, and the regional
  off-grid medians were 11,037 ms and 11,123 ms. Parts (b) to (d) were within a few milliseconds
  of the values above. The table shows the second run.
