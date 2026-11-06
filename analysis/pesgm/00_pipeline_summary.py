"""Item 0 - pipeline facts + training / inference timing per model family.

Reads the training tables and the stored summary.json files, then re-fits
each model family on all 486 runs with the pipeline's own ``train_final_model``
to measure wall-clock training time, and times single-design inference on
(a) the freshly fitted model and (b) the pickled artefact the dashboard loads.

Writes data/00_pipeline_facts.json, data/00_timing.csv, results_00.md.
Run on an otherwise idle machine (timings are wall clock, 14 logical cores).
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from pesgm_common import (
    DATA, HERE, INPUTS, LAYERS, OUTPUTS, SEED, X_COLS, Config, Timer,
    load_artifact, load_layer, write_json, md_table,
)
import sys

from surrogate_ml_models import train_final_model, get_model, MonotoneXGBMultiOutput  # noqa: E402
from surrogate_predict import encode_design, predict  # noqa: E402
from sklearn.multioutput import MultiOutputRegressor  # noqa: E402

# The xgb artefact was pickled while surrogate_ml_models ran as __main__, so
# the class must be visible under __main__ to unpickle it (same trick the
# dashboard needs).
setattr(sys.modules["__main__"], "MonotoneXGBMultiOutput", MonotoneXGBMultiOutput)

MODELS = ["knn", "ridge", "lasso", "rf", "xgb", "nn", "ngboost"]
REF_DESIGN = {"Dem": "Md", "Fuel": "Md", "REcost": "Md", "Siting": "Ref", "Batt": "Md", "Pol": "IRA"}


def table_facts(layer: str) -> dict:
    raw = pd.read_csv(LAYERS[layer]["data"])
    y_all = [c for c in raw.columns if not c.startswith("x_") and c != "case_name"]
    X, Y, x_cols, y_cols, case_names, constants = load_layer(layer)
    summ = json.loads((LAYERS[layer]["out"] / "summary.json").read_text())
    cats = pd.Series([c.split("_")[0] for c in y_cols]).value_counts().to_dict()
    neg_cols = {c: int((raw[c] < 0).sum()) for c in y_all if (raw[c] < 0).any()}
    out = dict(
        n_rows=int(raw.shape[0]), n_columns=int(raw.shape[1]),
        n_x=len(x_cols), x_cols=x_cols,
        n_y_in_csv=len(y_all), n_y_constant_dropped=len(constants), n_y_modelled=len(y_cols),
        constant_outputs=constants, y_by_category=cats,
        includes_runtime_seconds=("runtime_seconds" in y_cols),
        negative_training_targets=neg_cols,
        dial_levels={c: sorted(raw[c].unique().tolist()) for c in x_cols},
        summary_models={k: {kk: v[kk] for kk in ("oof_r2_mean", "oof_r2_median",
                                                   "n_outputs_r2_above_0.9", "n_outputs_r2_above_0.95")}
                        for k, v in summ["models"].items()},
        cv=summ["config"],
    )
    if layer == "system":
        comps = [c for c in y_cols if c.startswith(("cost_inv_", "cost_op_"))]
        out["cost_identity_max_rel_err"] = float(
            ((raw[comps].sum(axis=1) - raw["cost_total"]).abs() / raw["cost_total"].abs()).max())
        out["n_cost_components"] = len(comps)
        out["runtime_minutes"] = dict(mean=float(raw.runtime_seconds.mean() / 60),
                                      median=float(raw.runtime_seconds.median() / 60),
                                      min=float(raw.runtime_seconds.min() / 60),
                                      max=float(raw.runtime_seconds.max() / 60))
    return out


def time_models(layer: str, n_pred_calls: int = 20) -> list[dict]:
    X, Y, x_cols, y_cols, _, _ = load_layer(layer)
    cfg = Config(data_path=str(LAYERS[layer]["data"]), output_dir=str(LAYERS[layer]["out"]))
    cfg.x_cols, cfg.y_cols = list(x_cols), list(y_cols)
    rows = []
    # Warm up the joblib/loky worker pool so the first model's timing does not
    # include ~10 s of process start-up.
    from sklearn.linear_model import Ridge
    MultiOutputRegressor(Ridge(), n_jobs=-1).fit(X, Y[:, :4])
    for m in MODELS:
        print(f"  [{layer}] fitting {m} on all {len(X)} runs ...", flush=True)
        t = Timer()
        model, sx, sy, disp = train_final_model(X, Y, m, cfg)
        fit_s = t.lap()
        x = sx.transform(encode_design(REF_DESIGN, x_cols).reshape(1, -1))
        model.predict(x)                      # warm-up (joblib worker spin-up)
        t.lap()
        for _ in range(n_pred_calls):
            model.predict(x)
        pred_ms = t.lap() / n_pred_calls * 1e3
        # Batch inference: the whole 486-run factorial in one call
        Xs = sx.transform(X)
        t.lap()
        model.predict(Xs)
        batch_ms = t.lap() * 1e3
        # Dashboard path: pickled artefact + full constraint stack (predict()).
        art_ms = art1_ms = float("nan")
        try:
            art = load_artifact(layer, m)
            predict(art, REF_DESIGN)          # warm-up
            t.lap()
            for _ in range(n_pred_calls):
                predict(art, REF_DESIGN)
            art_ms = t.lap() / n_pred_calls * 1e3
            # Same artefact with the per-output dispatch forced in-process
            # (n_jobs=1): isolates the multiprocess overhead of the deployed path.
            if hasattr(art["model"], "n_jobs"):
                art["model"].n_jobs = 1
                predict(art, REF_DESIGN)
                t.lap()
                for _ in range(n_pred_calls):
                    predict(art, REF_DESIGN)
                art1_ms = t.lap() / n_pred_calls * 1e3
        except Exception as exc:  # noqa: BLE001
            print(f"    (artifact predict failed: {exc})")
        rows.append(dict(layer=layer, model=m, display=disp, n_outputs=len(y_cols),
                         train_s=fit_s, predict_single_ms=pred_ms,
                         predict_batch486_ms=batch_ms, artifact_predict_ms=art_ms,
                         artifact_predict_njobs1_ms=art1_ms))
        print(f"    train {fit_s:.1f} s, single predict {pred_ms:.1f} ms, "
              f"artefact predict {art_ms:.1f} ms", flush=True)
    return rows


def main():
    facts = {layer: table_facts(layer) for layer in ("system", "regional")}
    write_json(facts, "00_pipeline_facts.json")
    rows = time_models("system") + time_models("regional")
    df = pd.DataFrame(rows)
    df.to_csv(DATA / "00_timing.csv", index=False)
    print(df.to_string())

    # ----- results fragment -----
    s, r = facts["system"], facts["regional"]
    rt = s["runtime_minutes"]
    L = []
    L.append("## 0. Pipeline summary (what the code actually does)\n")
    L.append(f"The training table has {s['n_rows']} rows (one per ReEDS run, the full 3^5 x 2 factorial) "
             f"and {s['n_columns']} columns in the system file ({r['n_columns']} in the regional file): "
             f"a case name, {s['n_x']} dial columns, and {s['n_y_in_csv']} ({r['n_y_in_csv']}) output columns; "
             f"every output is the 2050 value only, no other solve years are included.")
    L.append(f"Dials are ordinal integers: Dem, Fuel, REcost, Batt and Siting are coded 0/1/2 "
             f"(Lo/Md/Hi, or Open/Ref/Lim for Siting) and Pol is 0/1 (IRA/OBBBA); they are standardised "
             f"inside each fold and the dashboard feeds non-integer slider values to the same encoding.")
    L.append(f"Dropping zero-variance outputs removes {s['n_y_constant_dropped']} system columns "
             f"({', '.join(s['constant_outputs'])}) and {r['n_y_constant_dropped']} regional columns, "
             f"leaving {s['n_y_modelled']} system and {r['n_y_modelled']} regional modelled outputs; "
             f"the {s['n_y_modelled']} system outputs include runtime_seconds, which is a ReEDS solve time, "
             f"not an energy-system quantity.")
    L.append(f"System outputs by category: {s['y_by_category']}; regional: {r['y_by_category']} "
             f"(regional cost columns are per-BA cost components, there is no regional cost_total).")
    L.append("Hyperparameters are fixed, there is no grid search or tuning loop in the code: "
             "RF n_estimators=200, max_depth=None, min_samples_leaf=2; XGBoost n_estimators=200, max_depth=6, "
             "learning_rate=0.1 with per-output monotone constraints; MLP hidden (64, 32), relu, adam, alpha=1e-3, "
             "max_iter=3000, no early stopping; Ridge alpha=1.0; Lasso alpha=0.1; k-NN k=3 distance-weighted; "
             "NGBoost n_estimators=200, learning_rate=0.05, Normal distribution.")
    L.append(f"The random seed is {SEED} everywhere (KFold shuffle, RF, XGB, MLP, NGBoost); the CV is 10-fold "
             f"with shuffle, and every model family is wrapped in MultiOutputRegressor so one independent "
             f"model is fitted per output.")
    L.append("Reported R-squared values are computed on the raw out-of-fold predictions before any constraint "
             "is applied (no clipping, no cost decomposition, no additivity), and NN/NGBoost targets are "
             "standardised per fold.")
    L.append("The 90 % interval for RF (and every non-NGBoost model) is split-conformal: the dashboard adds "
             "+/- the 0.90 quantile of |OOF residual| per output (symmetric band, from surrogate_uq.conformal_widths) "
             "around the point prediction; for NGBoost the native interval is mean +/- 1.645 sigma from the "
             "predicted Normal, de-standardised with the training-set scaler.")
    L.append("The existing coverage check in surrogate_eval and the Stage 1 status note (89.9-91.2 % coverage) "
             "evaluate the conformal band on the same OOF residuals used to set its width, so that number is "
             "circular and cannot be cited as empirical coverage; item 1 below replaces it.")
    L.append(f"Each ERCOT ReEDS run took {rt['mean']:.1f} min on average (median {rt['median']:.1f}, "
             f"range {rt['min']:.0f}-{rt['max']:.0f} min) according to runtime_seconds.")
    L.append(f"The cost identity holds exactly in the training data: the {s['n_cost_components']} cost_inv_* and "
             f"cost_op_* components sum to cost_total with max relative error {s['cost_identity_max_rel_err']:.1e}.")
    L.append("\n**Claims in the draft the code does not support**\n")
    L.append("- 'Four domain constraints': surrogate_constraints.py implements five (non-negativity, XGB monotone "
             "hints, regional-to-system additivity, dgen DistPV curve, cost decomposition). For the RF surrogate "
             "that the paper reports, only three are actually applied at inference: non-negativity clip, the "
             "DistPV override, and cost decomposition. The additivity rescale is implemented but not called "
             "anywhere in the dashboard (reeds_proxy.py) or in surrogate_predict.predict, and the monotone "
             "hints only exist for XGBoost.")
    L.append("- The 'dgen curve' for DistPV is a hand-set placeholder (a linear +/-5 % per demand level around the "
             "constant 12,994.6 MW), not a dGen output; cap_distpv is constant across all 486 runs so this cannot "
             "be validated from the data.")
    L.append("- None of the constraints enter the training objective except the non-negativity clip of the "
             "targets, which changes only one modelled column (cost_op_h2_transport_intrareg, negative in "
             f"{s['negative_training_targets'].get('cost_op_h2_transport_intrareg', 0)} runs); storage gen_* and "
             "*_negative cost columns are exempt.")
    L.append("- If the draft says '66 system outputs' are energy-system quantities, note that one of them is "
             "runtime_seconds; the energy-system count is 65.")
    L.append("- The XGBoost artefacts (overall and regional xgb.joblib) were pickled while surrogate_ml_models.py "
             "ran as __main__, so their MonotoneXGBMultiOutput wrapper cannot be unpickled by any other script "
             "(AttributeError on MonotoneXGBMultiOutput in __main__); the dashboard and surrogate_eval therefore "
             "cannot load the XGB model unless the class is aliased into __main__ first. This script does that "
             "alias for the timing below.")
    L.append("- The headline R-squared values (RF system mean 0.749 / median 0.882; regional 0.625 / 0.715) "
             "reproduce exactly from the stored residuals and from a fresh re-run with seed 42, so those are fine.")
    L.append("\n**Training and single-design inference time (this machine, 14 logical cores, env reeds2)**\n")
    L.append(md_table(df.round(2), "{:.2f}"))
    rf_s = df[(df.layer == "system") & (df.model == "rf")].iloc[0]
    rf_r = df[(df.layer == "regional") & (df.model == "rf")].iloc[0]
    L.append("\nartifact_predict_ms is the dashboard path (unpickled MultiOutputRegressor(n_jobs=-1) + constraint "
             "stack); predict_single_ms is the same model object right after fitting; artifact_predict_njobs1_ms "
             "is the same artefact with the per-output dispatch forced in-process. predict_batch486_ms is one call "
             "for all 486 designs.")
    L.append(f"The deployed RF needs {rf_s.artifact_predict_ms / 1e3:.1f} s per single-design prediction on the system "
             f"layer and {rf_r.artifact_predict_ms / 1e3:.1f} s on the regional layer with the pipeline's n_jobs=-1 "
             f"dispatch, versus {rf_s.artifact_predict_njobs1_ms / 1e3:.2f} s and {rf_r.artifact_predict_njobs1_ms / 1e3:.2f} s "
             f"in-process; a batch of all 486 designs takes {rf_s.predict_batch486_ms / 1e3:.1f} s (system), so the "
             f"per-call overhead, not the trees, sets the latency. Against a {rt['mean']:.0f}-minute ReEDS run the "
             f"speed-up is about {rt['mean'] * 60 / (rf_s.artifact_predict_ms / 1e3):,.0f}x as deployed and "
             f"{rt['mean'] * 60 / (rf_s.artifact_predict_njobs1_ms / 1e3):,.0f}x in-process (system layer).")
    (HERE / "results_00.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote results_00.md")


if __name__ == "__main__":
    main()
