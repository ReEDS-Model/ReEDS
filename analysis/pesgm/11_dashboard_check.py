"""Item 11 - check the fixed constraint layer inside the ReEDS-Proxy dashboard.

Executes Stage2/code/reeds_proxy.py in-process on a fresh Bokeh document (the
same script `bokeh serve` runs per session), drives its widgets and calls its
own `_redraw()`, then reads what the Predict tab shows:

  (a) regional values sum to the system value for cap_nuclear, tran_total
      and gen_wind-ons (prediction vectors) and the Nuclear / Onshore Wind
      regional bars sum to the system bar, on a training-grid design (OOF
      path) and an off-grid design (final-model path);
  (b) total cost equals the sum of components on both paths (data and the
      "System cost" line versus the cost bars);
  (c) the DPV capacity bar is 12,994.6 MW at Lo, Md and Hi demand (and
      off-grid);
  (d) the CI (uncertainty) panel is populated without errors.

The prediction vectors are recorded by wrapping the dashboard's own
`predict` / `apply_constraints` names, so they are exactly what `_redraw`
used. Writes data/11_dashboard_check.json. Run with the reeds2 env.
"""
from __future__ import annotations

import json
import re
import runpy
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from bokeh.document import Document
from bokeh.io.doc import set_curdoc

HERE = Path(__file__).resolve().parent
APP = HERE.parents[1] / "postprocessing" / "reedssurr" / "Stage2" / "code" / "reeds_proxy.py"
DISTPV_MW = 12994.628099
GRID = {"Dem": 1.0, "Fuel": 1.0, "REcost": 1.0, "Siting": 1.0, "Batt": 1.0, "Pol": "IRA"}
OFFGRID = {"Dem": 0.5, "Fuel": 1.35, "REcost": 0.8, "Siting": 1.6, "Batt": 1.25, "Pol": "OBBBA"}


def load_app():
    set_curdoc(Document())
    sys.argv = [str(APP)]
    ns = runpy.run_path(str(APP), run_name="reeds_proxy_check")
    g = ns["_redraw"].__globals__          # live module globals
    rec = []
    real_predict, real_apply = g["predict"], g["apply_constraints"]

    def predict(*a, **k):
        out = real_predict(*a, **k)
        rec.append(("predict", out))
        return out

    def apply_constraints(*a, **k):
        out = real_apply(*a, **k)
        rec.append(("apply_constraints", out))
        return out
    g["predict"], g["apply_constraints"] = predict, apply_constraints
    return g, rec


def set_design(g, levels):
    for dim, v in levels.items():
        g["design_selects"][dim].value = v


def stage_label(g, layer):
    return next(k for k in g["STAGE_CONFIG"] if k.lower().startswith(layer))


def redraw(g, rec, layer, variable, levels, model):
    g["_set_active_stage"](stage_label(g, layer))
    g["variable_select"].value = variable
    g["model_select"].value = model
    set_design(g, levels)
    rec.clear()
    g["_redraw"]()
    bars = pd.DataFrame(dict(g["bars_pred_source"].data))
    return list(rec), bars


def bar_sum(bars, tech):
    return float(bars.loc[bars.tech == tech, "value"].sum()) if not bars.empty else float("nan")


def regional_sum(pred, parent, constants):
    if parent == "tran_total":
        cols = [c for c in pred.index if c.startswith("tran_p")]
    else:
        cols = [c for c in pred.index if re.fullmatch(re.escape(parent) + r"_p\d+", c)]
    return float(pred[cols].sum()), cols


def cost_line(text):
    m = re.search(r"predicted \$([\d,.\-]+) B", text)
    return float(m.group(1).replace(",", "")) if m else float("nan")


def main():
    g, rec = load_app()
    out = {"checks": [], "notes": []}

    def check(name, ok, **detail):
        out["checks"].append(dict(name=name, ok=bool(ok), **detail))
        print(("PASS " if ok else "FAIL ") + name + "  " + json.dumps(detail, default=float))

    for model in ("rf", "nn"):
        for tag, levels in (("training grid (OOF path)", GRID), ("off-grid (final model)", OFFGRID)):
            # ---------------- (a) data level, regional stage
            calls, bars_reg_cap = redraw(g, rec, "regional", "Capacity (GW)", levels, model)
            used_oof = "Matched training run" in g["status_div"].text
            # regional stage: 1st recorded vector = system prediction used for the
            # rescale, 2nd = the regional prediction shown
            assert len(calls) >= 2, calls
            sys_pred, reg_pred = calls[0][1], calls[1][1]
            for parent in ("cap_nuclear", "tran_total", "gen_wind-ons"):
                s, cols = regional_sum(reg_pred, parent, {})
                t = float(sys_pred[parent])
                check(f"(a) {model} {tag}: sum regional {parent} = system", abs(s - t) <= 1e-6 * max(1, abs(t)),
                      regional_sum=s, system=t, n_regional_cols=len(cols), oof_path=used_oof)
            # ---------------- (a') transmission corridors stay at or above their floor
            floors = g["transmission_floors"](g["_training_df_for_layer"]("regional"))
            worst = min(float(reg_pred[c]) - f for c, f in floors.items() if c in reg_pred.index)
            check(f"(a') {model} {tag}: every corridor >= its floor (initial capacity)",
                  worst >= -1e-6, min_margin_MW=worst, n_corridors=len(floors))
            # ---------------- (a'') system tran_total >= sum of corridor floors
            sys_floor = sum(floors.values())
            check(f"(a'') {model} {tag}: system tran_total >= sum of corridor floors",
                  float(sys_pred["tran_total"]) >= sys_floor - 1e-6,
                  tran_total=float(sys_pred["tran_total"]), floor_sum=sys_floor)
            # ---------------- (a) bar level: Nuclear (capacity), Onshore Wind (generation)
            _, bars_sys_cap = redraw(g, rec, "overall", "Capacity (GW)", levels, model)
            check(f"(a) {model} {tag}: Nuclear bars, regional sum = system bar",
                  abs(bar_sum(bars_reg_cap, "Nuclear") - bar_sum(bars_sys_cap, "Nuclear")) < 1e-6,
                  regional=bar_sum(bars_reg_cap, "Nuclear"), system=bar_sum(bars_sys_cap, "Nuclear"))
            _, bars_reg_gen = redraw(g, rec, "regional", "Generation (TWh)", levels, model)
            _, bars_sys_gen = redraw(g, rec, "overall", "Generation (TWh)", levels, model)
            check(f"(a) {model} {tag}: Onshore Wind bars, regional sum = system bar",
                  abs(bar_sum(bars_reg_gen, "Onshore Wind") - bar_sum(bars_sys_gen, "Onshore Wind")) < 1e-6,
                  regional=bar_sum(bars_reg_gen, "Onshore Wind"), system=bar_sum(bars_sys_gen, "Onshore Wind"))
            # ---------------- (b) cost identity, both layers
            for layer in ("overall", "regional"):
                calls, bars_cost = redraw(g, rec, layer, "System cost ($B)", levels, model)
                pred = calls[0][1] if layer == "overall" else calls[1][1]
                comps = [c for c in pred.index if c.startswith(("cost_inv_", "cost_op_"))]
                tot = float(pred["cost_total"])
                check(f"(b) {model} {tag} {layer}: cost_total = sum of components",
                      abs(tot - pred[comps].sum()) <= 1e-6 * abs(tot),
                      cost_total_B=tot / 1e9, n_components=len(comps))
                shown = cost_line(g["metrics_div"].text)
                bars_total = float(bars_cost["value"].sum())
                if np.isfinite(shown):
                    check(f"(b) {model} {tag} {layer}: 'System cost' line = sum of cost bars",
                          abs(shown - bars_total) < 0.006, line_B=shown, bars_B=bars_total)
                else:
                    out["notes"].append(f"{model} {tag} {layer}: no 'System cost' line (off-grid "
                                        "designs show only the runtime line)")
            # ---------------- (d) CI panel
            for layer in ("overall", "regional"):
                redraw(g, rec, layer, "Capacity (GW)", levels, model)
                uq = dict(g["uq_source"].data)
                n = len(next(iter(uq.values()))) if uq else 0
                check(f"(d) {model} {tag} {layer}: CI panel populated", n > 0, rows=n, keys=sorted(uq)[:6])

        # ---------------- (c) DistPV at Lo / Md / Hi demand and off-grid
        for dem in (0.0, 1.0, 2.0, 0.5):
            lv = dict(GRID, Dem=dem)
            _, bars = redraw(g, rec, "overall", "Capacity (GW)", lv, model)
            v = bar_sum(bars, "DPV") * 1e3
            check(f"(c) {model} Dem={dem}: DPV bar = 12,994.6 MW", abs(v - DISTPV_MW) < 0.05, dpv_MW=v)

    out["n_pass"] = sum(c["ok"] for c in out["checks"])
    out["n_checks"] = len(out["checks"])
    (HERE / "data" / "11_dashboard_check.json").write_text(json.dumps(out, indent=2, default=float))
    print(f"{out['n_pass']} / {out['n_checks']} checks passed")


if __name__ == "__main__":
    main()
