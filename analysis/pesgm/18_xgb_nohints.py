"""Item 18 - XGBoost 10-fold OOF without monotone hints (both layers).

Refits ONLY XGBoost with the pipeline's own code path: surrogate_ml_models.
compute_oof_predictions(X, Y, "xgb", Config(disable_monotone_xgb=True)),
i.e. plain XGBRegressor(n_estimators=200, max_depth=6, learning_rate=0.1,
random_state=42) per output in MultiOutputRegressor, KFold(10, shuffle,
seed 42), trained on the clipped targets exactly like the stored artefacts.
No other model, stored artefact, constraint code or dashboard file is
touched.

  python 18_xgb_nohints.py probe       time the system CV + one regional fold
  python 18_xgb_nohints.py fit         full CV, both layers -> OOF files
  python 18_xgb_nohints.py reproduce   system CV WITH hints vs the stored OOF
                                       (checks that only the hints differ)
  python 18_xgb_nohints.py report      scores, bounds audit, Table III,
                                       model_comparison figure, xgb_nohints.md

OOF files: data/18_xgb_nohints_oof.npz (here) and xgb_nohints_oof.npz beside
xgb.joblib in each OneDrive models folder (.npz, so the dashboard, which
loads *.joblib, ignores it).
"""
from __future__ import annotations

import importlib
import json
import sys
import time

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold
from sklearn.preprocessing import StandardScaler

from pesgm_common import DATA, HERE, LAYERS, load_layer, resolve_models_dir
from surrogate_ml_models import Config, compute_oof_predictions, get_model

OUT = DATA / "18_xgb_nohints_oof.npz"
TIMES = DATA / "18_fit_times.json"
REPRO = DATA / "18_reproduce_hints_system.json"


def cfg(layer, x_cols, y_cols, hints=False):
    c = Config(data_path=str(LAYERS[layer]["data"]), output_dir=str(LAYERS[layer]["out"]),
               disable_monotone_xgb=not hints)
    c.x_cols, c.y_cols = list(x_cols), list(y_cols)   # as run_pipeline sets them
    return c


def probe():
    X, Y, xc, yc, _, _ = load_layer("system")
    t = time.perf_counter()
    compute_oof_predictions(X, Y, "xgb", cfg("system", xc, yc))
    ts = time.perf_counter() - t
    X, Y, xc, yc, _, _ = load_layer("regional")
    c = cfg("regional", xc, yc)
    tr, va = next(KFold(10, shuffle=True, random_state=42).split(X))
    sx = StandardScaler().fit(X[tr])
    m, name = get_model("xgb", Y.shape[1], c)
    t = time.perf_counter()
    m.fit(sx.transform(X[tr]), Y[tr])
    tf = time.perf_counter() - t
    print(f"model: {name} / {type(m).__name__}({type(m.estimator).__name__})")
    print(f"system 10-fold CV: {ts:.1f} s; regional one fold: {tf:.1f} s "
          f"-> regional CV estimate {10 * tf:.0f} s; total estimate {(ts + 10 * tf) / 60:.1f} min")


def fit():
    oof, times = {}, {}
    for layer in ("system", "regional"):
        X, Y, xc, yc, _, _ = load_layer(layer)
        c = cfg(layer, xc, yc)
        m, name = get_model("xgb", Y.shape[1], c)
        assert type(m).__name__ == "MultiOutputRegressor" and \
            m.estimator.get_params()["monotone_constraints"] is None, name
        t = time.perf_counter()
        P = compute_oof_predictions(X, Y, "xgb", c)
        times[layer] = time.perf_counter() - t
        print(f"{layer}: {name}, {times[layer]:.1f} s", flush=True)
        oof[f"{layer}_oof"] = P.astype(np.float64)
        oof[f"{layer}_cols"] = np.array(yc)
    np.savez_compressed(OUT, **oof)
    TIMES.write_text(json.dumps(times, indent=1))
    for layer in ("system", "regional"):
        d = resolve_models_dir(LAYERS[layer]["out"])
        np.savez_compressed(d / "xgb_nohints_oof.npz", oof=oof[f"{layer}_oof"], y_cols=oof[f"{layer}_cols"],
                            note=np.array("XGBoost 10-fold OOF predictions, no monotone hints "
                                          "(analysis/pesgm/18_xgb_nohints.py); not a dashboard artefact"))
        print("wrote", d / "xgb_nohints_oof.npz")


def reproduce():
    X, Y, xc, yc, _, _ = load_layer("system")
    t = time.perf_counter()
    P = compute_oof_predictions(X, Y, "xgb", cfg("system", xc, yc, hints=True))
    t = time.perf_counter() - t
    S = Y - np.load(DATA / "10_stored_residuals.npz")["system_xgb"].astype(float)
    d = np.abs(P - S)
    rel = (d / (np.abs(S).max(axis=0) + 1e-9)).max()
    REPRO.write_text(json.dumps(dict(seconds=t, max_abs_diff=float(d.max()), max_rel_diff=float(rel))))
    print(f"with-hints system CV {t:.0f} s; max abs diff {d.max():.4g}; max diff / column max {rel:.3g}")


def report():
    A = importlib.import_module("10_after_fix")          # cf_audit, tran_audit, constrain, scores
    from surrogate_constraints import Stage2InferenceConfig, transmission_floors
    nh = np.load(OUT)
    res = np.load(DATA / "10_stored_residuals.npz")
    L_ = {}
    for layer in ("system", "regional"):
        _, Yc, _, yc, _, const = load_layer(layer)
        _, Yraw, _, _, _, _ = load_layer(layer, clip=False)
        assert list(nh[f"{layer}_cols"]) == list(yc)
        L_[layer] = dict(cols=list(yc), const=const, Y=Yraw, df=pd.read_csv(LAYERS[layer]["data"]),
                         old=Yc - res[f"{layer}_xgb"].astype(float), new=nh[f"{layer}_oof"])
    floors = transmission_floors(L_["regional"]["df"])
    full = Stage2InferenceConfig()
    con = {}
    for which in ("old", "new"):
        print(f"  constraining {which}", flush=True)
        S, R = A.constrain(L_["system"][which], L_["regional"][which], L_["system"]["cols"],
                           L_["regional"]["cols"], L_["system"]["const"], L_["regional"]["const"],
                           full, floors)
        con[which] = {"system": S, "regional": R}

    rows, aud, per_out = [], [], {}
    for layer, d in L_.items():
        for which, lab in (("old", "with hints (stored)"), ("new", "no hints (refit)")):
            s_, r2 = A.scores(d["Y"], d[which], d["cols"])
            rows.append(dict(layer=layer, xgb=lab, mean=s_["mean"], median=s_["median"],
                             n_gt_0_9=s_["n_gt_0_9"], n=len(d["cols"])))
            per_out[(layer, which)] = r2
            for pred, P in (("raw OOF", d[which]), ("after constraint layer", con[which][layer])):
                cf = A.cf_audit(d["df"], P, d["cols"], d["const"])
                tr = A.tran_audit(d["df"], P, d["cols"])
                aud.append(dict(layer=layer, xgb=lab, predictions=pred,
                                cf_over=int(cf.n_over.sum()), cf_eval=int(cf.n_eval.sum()),
                                cf_detail="; ".join(f"{r.gen} {r.n_over}" for r in cf[cf.n_over > 0].itertuples()),
                                tran_below=int(tr.n_below.sum()), tran_eval=int(tr.n_eval.sum()),
                                tran_detail="; ".join(f"{r.column} {r.n_below}"
                                                      for r in tr[tr.n_below > 0].itertuples())))
    sc = pd.DataFrame(rows)
    au = pd.DataFrame(aud)
    sc.to_csv(DATA / "18_scores.csv", index=False)
    au.to_csv(DATA / "18_bounds_audit.csv", index=False)
    po = pd.concat([pd.DataFrame({"layer": layer, "output": per_out[(layer, "old")].index,
                                  "r2_hints": per_out[(layer, "old")].to_numpy(),
                                  "r2_nohints": per_out[(layer, "new")].to_numpy()})
                    for layer in ("system", "regional")], ignore_index=True)
    po.to_csv(DATA / "18_per_output_r2.csv", index=False)

    # Table III: stored raw OOF for every model, XGBoost row replaced by the no-hints refit
    t3 = pd.read_csv(DATA / "10_table3.csv")[["model", "layer", "old_mean", "old_median", "old_n_gt_0_9"]]
    t3.columns = ["model", "layer", "mean", "median", "n_gt_0_9"]
    for layer in ("system", "regional"):
        r = sc[(sc.layer == layer) & (sc.xgb == "no hints (refit)")].iloc[0]
        t3.loc[(t3.model == "XGBoost") & (t3.layer == layer), ["mean", "median", "n_gt_0_9"]] = \
            [r["mean"], r["median"], r["n_gt_0_9"]]
    t3.to_csv(DATA / "18_table3_xgb_nohints.csv", index=False)

    # model_comparison figure (14_paper_figures.py now reads the no-hints XGBoost OOF)
    F = importlib.import_module("14_paper_figures")
    F.model_comparison()
    nj = DATA / "14_figure_numbers.json"
    N = json.loads(nj.read_text())
    N["model_comparison"] = F.N["model_comparison"]
    nj.write_text(json.dumps(N, indent=1, default=str))

    write_md(sc, au, t3, json.loads(TIMES.read_text()), json.loads(REPRO.read_text()), po)


def write_md(sc, au, t3, times, rep, po):
    def f3(v):
        return f"{v:.3f}"
    L = ["# XGBoost without monotone hints\n",
         f"Written by `18_xgb_nohints.py` on {time.strftime('%Y-%m-%d')} (reeds2 env).\n",
         "**What was refitted:** only XGBoost, 10-fold out-of-fold (OOF) on both layers, with the "
         "pipeline's own `compute_oof_predictions` and its existing switch `disable_monotone_xgb=True`. "
         "Everything else is as stored: the same folds (KFold, shuffle, seed 42), 200 trees, depth 6, "
         "learning rate 0.1, one model per output, trained on the clipped targets. No Stage 2 code "
         "changed. No other model, stored artifact, constraint code or dashboard file was touched.\n",
         f"**Run time:** {times['system']:.0f} s system and {times['regional']:.0f} s regional.\n",
         "**Check that only the hints differ:** refitting the system layer the same way with the hints on "
         f"reproduces the stored XGBoost OOF to within {rep['max_rel_diff']:.1e} of each output's maximum, "
         f"which is float32 storage precision ({rep['seconds']:.0f} s).\n",
         "**Files:** the new OOF predictions are `data/18_xgb_nohints_oof.npz`, with a copy named "
         "`xgb_nohints_oof.npz` beside `xgb.joblib` in each OneDrive models folder. The dashboard loads "
         "only `.joblib` files, so it does not see them. Per-output R²: `data/18_per_output_r2.csv`.\n",
         "## 1. Raw OOF R², no constraints\n",
         "| Layer | XGBoost | Mean R² | Median R² | Outputs with R² > 0.9 |",
         "|---|---|---|---|---|"]
    for r in sc.itertuples():
        L.append(f"| {r.layer} | {r.xgb} | {f3(r.mean)} | {f3(r.median)} | {r.n_gt_0_9} of {r.n} |")
    L.append("")
    for layer in ("system", "regional"):
        g = po[po.layer == layer].set_index("output")
        d = g.r2_nohints - g.r2_hints
        L.append(f"- **{layer.capitalize()} outputs:** {int((d > 0.005).sum())} improve and "
                 f"{int((d < -0.005).sum())} get worse by more than 0.005 R². The largest gain is "
                 f"{d.idxmax()} ({f3(g.r2_hints[d.idxmax()])} → {f3(g.r2_nohints[d.idxmax()])}). "
                 f"The largest loss is {d.idxmin()} ({f3(g.r2_hints[d.idxmin()])} → "
                 f"{f3(g.r2_nohints[d.idxmin()])}).")
    L.append("")
    L.append("## 2. Bounds audit for XGBoost (same definitions as `results_after_fix.md` Part 3)\n")
    L.append("CF ceiling: predicted gen / (8760 × cap) more than 1% above the maximum over the 486 runs, "
             "for predictions with cap ≥ 1 MW, storage skipped. Below floor: transmission predictions "
             "more than 1% below the minimum over the 486 runs (regional: the corridors; system: "
             "`tran_total` and `tran_AC_total`).\n")
    L.append("| Layer | XGBoost | Predictions | CF ceiling exceedances | Transmission below floor |")
    L.append("|---|---|---|---|---|")
    for r in au.itertuples():
        L.append(f"| {r.layer} | {r.xgb} | {r.predictions} | {r.cf_over:,} of {r.cf_eval:,} | "
                 f"{r.tran_below:,} of {r.tran_eval:,} |")
    L.append("")
    L.append("Detail by technology and column: `data/18_bounds_audit.csv`.\n")
    L.append("## 3. Table III with XGBoost refitted without hints (raw OOF, no constraints)\n")
    L.append("The other six rows are the stored OOF scores, unchanged from `results_after_fix.md`.\n")
    L.append("| Model | System mean | System median | System > 0.9 | Regional mean | Regional median | "
             "Regional > 0.9 |")
    L.append("|---|---|---|---|---|---|---|")
    for m, g in t3.groupby("model", sort=False):
        s_, r_ = g[g.layer == "system"].iloc[0], g[g.layer == "regional"].iloc[0]
        L.append(f"| {m}{' (no hints)' if m == 'XGBoost' else ''} | {f3(s_['mean'])} | {f3(s_['median'])} | "
                 f"{int(s_['n_gt_0_9'])} | {f3(r_['mean'])} | {f3(r_['median'])} | {int(r_['n_gt_0_9'])} |")
    L.append("")
    T = t3.set_index(["model", "layer"])
    rf_, xg = T.loc["Random Forest"], T.loc["XGBoost"]
    L.append("**RF against XGBoost without hints:** RF keeps the highest mean on both layers "
             f"({rf_.loc['system', 'mean']:.4f} vs {xg.loc['system', 'mean']:.4f} system, "
             f"{rf_.loc['regional', 'mean']:.4f} vs {xg.loc['regional', 'mean']:.4f} regional) and the "
             f"highest regional median ({rf_.loc['regional', 'median']:.4f} vs "
             f"{xg.loc['regional', 'median']:.4f}). The system median is a tie at three decimals "
             f"(RF {rf_.loc['system', 'median']:.4f}, XGBoost {xg.loc['system', 'median']:.4f}). Outputs "
             f"above 0.9: {int(rf_.loc['system', 'n_gt_0_9'])} vs {int(xg.loc['system', 'n_gt_0_9'])} system "
             f"and {int(rf_.loc['regional', 'n_gt_0_9'])} vs {int(xg.loc['regional', 'n_gt_0_9'])} regional.\n")
    L.append("`figs/model_comparison` (PDF and PNG) was regenerated with these numbers. CSV: "
             "`data/18_table3_xgb_nohints.csv`.\n")
    L.append("**Not changed:** the stored `xgb.joblib` artifacts still have the hints, so the dashboard's "
             "XGBoost and the Table III in `results_after_fix.md` are as before.")
    (HERE / "xgb_nohints.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote xgb_nohints.md")


if __name__ == "__main__":
    {"probe": probe, "fit": fit, "reproduce": reproduce, "report": report}[sys.argv[1]]()
