"""Item 17 - time one ReEDS-Proxy dashboard query (RF), split into parts.

Runs Stage2/code/reeds_proxy.py in-process on a fresh Bokeh document (the
script `bokeh serve` runs per session) and calls its own `_redraw()`. The
dashboard's own names are wrapped with timers (no code change):

  (a) model inference   time inside `predict` minus its constraint step
                        (system and regional model for a regional query);
                        for a training-grid design the dashboard uses the
                        stored OOF prediction, so (a) is the residual lookup
  (b) constraint layer  `apply_constraints` (+ the floors it is given)
  (c) conformal interval all `conformal_widths` calls in the redraw
  (d) rendering         the rest of `_redraw`: aggregation to display
                        categories and the Bokeh ColumnDataSource / figure
                        updates on the server. Browser paint is not included.

One warm-up redraw, then 10 timed redraws per case; medians reported.
Writes data/17_timing.csv and timing.md.
"""
from __future__ import annotations

import os
import platform
import runpy
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from bokeh.document import Document
from bokeh.io.doc import set_curdoc

HERE = Path(__file__).resolve().parent
APP = HERE.parents[1] / "postprocessing" / "reedssurr" / "Stage2" / "code" / "reeds_proxy.py"
GRID = {"Dem": 1.0, "Fuel": 1.0, "REcost": 1.0, "Siting": 1.0, "Batt": 1.0, "Pol": "IRA"}
OFFGRID = {"Dem": 0.5, "Fuel": 1.35, "REcost": 0.8, "Siting": 1.6, "Batt": 1.25, "Pol": "OBBBA"}
N_REP = 10


def main():
    set_curdoc(Document())
    sys.argv = [str(APP)]
    ns = runpy.run_path(str(APP), run_name="reeds_proxy_timing")
    g = ns["_redraw"].__globals__
    sc_mod = sys.modules["surrogate_constraints"]
    log = []                                     # (kind, seconds) within one redraw

    def wrap(name, kind):
        real = g[name]

        def f(*a, **k):
            t = time.perf_counter()
            out = real(*a, **k)
            log.append((kind, time.perf_counter() - t))
            return out
        g[name] = f

    # predict() calls surrogate_constraints.apply_constraints internally: time that too
    real_apply_mod = sc_mod.apply_constraints

    def apply_mod(*a, **k):
        t = time.perf_counter()
        out = real_apply_mod(*a, **k)
        log.append(("constraints_in_predict", time.perf_counter() - t))
        return out
    sc_mod.apply_constraints = apply_mod
    wrap("predict", "predict_total")             # model + its constraint step
    wrap("apply_constraints", "constraints")     # OOF path / system-for-additivity path
    wrap("conformal_widths", "conformal")
    wrap("_layer_floors", "floors")

    rows = []
    for layer in ("overall", "regional"):
        label = next(k for k in g["STAGE_CONFIG"] if k.lower().startswith(layer))
        g["_set_active_stage"](label)
        g["variable_select"].value = "Capacity (GW)"
        g["model_select"].value = "rf"
        for path, levels in (("off-grid (final model)", OFFGRID), ("training grid (OOF)", GRID)):
            for dim, v in levels.items():
                g["design_selects"][dim].value = v
            for rep in range(N_REP + 1):         # rep 0 = warm-up
                log.clear()
                t = time.perf_counter()
                g["_redraw"]()
                total = time.perf_counter() - t
                s = lambda k: sum(v for kk, v in log if kk == k)
                cons = s("constraints") + s("constraints_in_predict") + s("floors")
                infer = s("predict_total") - s("constraints_in_predict")
                conf = s("conformal")
                rows.append(dict(layer="system" if layer == "overall" else "regional", path=path, rep=rep,
                                 a_inference_ms=1e3 * infer, b_constraints_ms=1e3 * cons,
                                 c_conformal_ms=1e3 * conf,
                                 d_render_ms=1e3 * (total - infer - cons - conf),
                                 total_ms=1e3 * total, n_conformal_calls=sum(1 for kk, _ in log if kk == "conformal"),
                                 n_predict_calls=sum(1 for kk, _ in log if kk == "predict_total")))
            print(f"{layer} {path}: done", flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(HERE / "data" / "17_timing.csv", index=False)
    med = (df[df.rep > 0].groupby(["layer", "path"], sort=False)
           [["a_inference_ms", "b_constraints_ms", "c_conformal_ms", "d_render_ms", "total_ms",
             "n_predict_calls", "n_conformal_calls"]].median())
    warm = df[df.rep == 0].set_index(["layer", "path"])["total_ms"]
    print(med.round(1).to_string())

    L = ["# Dashboard query timing (RF)\n",
         f"Measured {time.strftime('%Y-%m-%d')} with `17_timing.py` (reeds2 env) on {platform.node()}: "
         f"{platform.processor() or platform.machine()}, {os.cpu_count()} logical CPUs, Windows "
         f"{platform.release()}. The dashboard script ran in-process and its own `_redraw()` was "
         f"called. After one warm-up redraw, each case was timed {N_REP} times; the values are "
         "medians in milliseconds. No code was changed: the dashboard's functions were wrapped "
         "with timers only. The full run log is in `data/17_timing.csv`.\n",
         "**What each column measures:**\n",
         "- **(a) Model inference:** the RF model call inside `predict`, excluding its constraint "
         "step. A regional query runs two models: the system RF for the rescale target, and the "
         "regional RF. For a training-grid design the dashboard skips the model and shows the "
         "stored out-of-fold prediction, so (a) is only a lookup.",
         "- **(b) Constraint layer:** `apply_constraints`, plus computing the transmission floors "
         "from the training data.",
         "- **(c) Conformal interval:** every `conformal_widths` call in the redraw. Each call "
         "recomputes the 90% quantile of the stored |residuals|.",
         "- **(d) Rendering:** the rest of `_redraw`, which aggregates to display categories and "
         "updates the Bokeh data sources and figures on the server. **The browser's drawing time is "
         "not included.**\n",
         "| Layer | Path | (a) inference | (b) constraints | (c) conformal | (d) rendering | Total | "
         "model calls | conformal calls |",
         "|---|---|---|---|---|---|---|---|---|"]
    for (layer, path), r in med.iterrows():
        L.append(f"| {layer} | {path} | {r.a_inference_ms:,.1f} | {r.b_constraints_ms:,.1f} | "
                 f"{r.c_conformal_ms:,.1f} | {r.d_render_ms:,.1f} | {r.total_ms:,.1f} | "
                 f"{int(r.n_predict_calls)} | {int(r.n_conformal_calls)} |")
    L.append("")
    L.append("First (warm-up) redraw totals in ms, which include loading the model files into "
             "the cache on first use: " +
             "; ".join(f"{l} {p} {v:,.0f}" for (l, p), v in warm.items()) + ".")
    L.append("")
    L.append("**Notes:**\n")
    L.append("- **Training-grid designs:** the out-of-fold lookup (stored value minus stored residual) "
             "runs inside `_redraw`, so it is counted in (d). It takes well under 1 ms.")
    L.append("- **Why inference dominates:** the stored RF is a scikit-learn `MultiOutputRegressor` "
             "with `n_jobs=-1`. Every query sends one forest per output (66 system, 308 regional) to "
             "a joblib worker pool, and on Windows that overhead is most of the cost. The earlier "
             "pipeline timing (`results_00.md`) ran the same forests in-process: 0.56 s system and "
             "3.7 s regional. Nothing was changed here.")
    (HERE / "timing.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote timing.md")


if __name__ == "__main__":
    main()
