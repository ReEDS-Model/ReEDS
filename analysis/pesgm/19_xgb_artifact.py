"""Item 19 - replace the dashboard's XGBoost artifacts with the no-hints refit.

Same procedure as 18_xgb_nohints.py (commit 5417cc13): surrogate_ml_models
with disable_monotone_xgb=True, 10-fold OOF (seed 42), 200 trees, depth 6,
lr 0.1. For each layer this does what run_pipeline does for one model, and
nothing more (run_pipeline would also redraw the all-model comparison plots
from a single model):

  1. copy the old models/xgb.joblib to ../_before_xgb_nohints_<date>/
  2. OOF predictions (checked equal to data/18_xgb_nohints_oof.npz)
  3. final model on all 486 runs; artifact dict with the pipeline's keys
     -> models/xgb.joblib (plain MultiOutputRegressor(XGBRegressor), so it
     unpickles anywhere)
  4. summary.json "xgb" entry and per_output_metrics_xgb.csv in
     Stage2/outputs/<layer>/

  python 19_xgb_artifact.py fit     steps 1-4, both layers
  python 19_xgb_artifact.py eval    re-run surrogate_eval.run_eval for both
                                    layers (rebuilds eval/ from the stored
                                    OOF residuals of all 7 models; no refit)
"""
from __future__ import annotations

import json
import pickle
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from pesgm_common import DATA, LAYERS, resolve_models_dir
from surrogate_ml_models import (
    Config, compute_oof_predictions, evaluate_predictions, load_data, train_final_model,
)

FOLDER = {"system": "overall", "regional": "regional"}
STAMP = "2026-11-06"


def fit():
    nh = np.load(DATA / "18_xgb_nohints_oof.npz")
    for layer in ("system", "regional"):
        out_dir = Path(LAYERS[layer]["out"])
        models_dir = resolve_models_dir(out_dir)
        art_path = models_dir / "xgb.joblib"
        backup = models_dir.parent / f"_before_xgb_nohints_{STAMP}"
        backup.mkdir(exist_ok=True)
        if not (backup / "xgb.joblib").exists():
            shutil.copy2(art_path, backup / "xgb.joblib")
            print(f"backed up {art_path} -> {backup}")

        config = Config(data_path=str(LAYERS[layer]["data"]), output_dir=str(out_dir),
                        disable_monotone_xgb=True)
        X, Y, x_cols, y_cols, case_names, constants = load_data(config)
        config.x_cols, config.y_cols = list(x_cols), list(y_cols)
        n = X.shape[0]
        cv_type = "LOO-CV" if config.n_folds >= n else f"{config.n_folds}-fold CV"

        t = time.perf_counter()
        oof = compute_oof_predictions(X, Y, "xgb", config)
        assert list(nh[f"{layer}_cols"]) == list(y_cols)
        diff = float(np.abs(oof - nh[f"{layer}_oof"]).max())
        print(f"{layer}: OOF {time.perf_counter() - t:.0f} s, max |diff| vs 18_xgb_nohints = {diff:.3g}")
        metrics = evaluate_predictions(Y, oof, y_cols)
        agg = metrics["aggregate"]
        model, scaler_x, scaler_y, display_name = train_final_model(X, Y, "xgb", config)
        assert type(model).__name__ == "MultiOutputRegressor", type(model)

        artifact = {
            "model": model, "scaler_x": scaler_x, "scaler_y": scaler_y,
            "x_cols": list(x_cols), "y_cols": list(y_cols),
            "model_name": "xgb", "display_name": display_name,
            "data_path": config.data_path, "n_samples": int(n), "cv_type": cv_type,
            "oof_r2_mean": float(agg["r2_mean"]), "oof_r2_median": float(agg["r2_median"]),
            "oof_residuals": (Y - oof).astype(np.float32),
        }
        blob = pickle.dumps(artifact)
        assert b"__main__" not in blob
        art_path.write_bytes(blob)
        print(f"  wrote {art_path} ({display_name})")

        summary_path = out_dir / "summary.json"
        summary = json.loads(summary_path.read_text())
        summary["models"]["xgb"] = {
            "display_name": display_name,
            "oof_r2_mean": agg["r2_mean"], "oof_r2_median": agg["r2_median"],
            "oof_r2_min": agg["r2_min"], "oof_r2_max": agg["r2_max"],
            "n_outputs_r2_above_0.9": agg["n_outputs_r2_above_0.9"],
            "n_outputs_r2_above_0.95": agg["n_outputs_r2_above_0.95"],
            "artifact": "models/xgb.joblib",
        }
        summary_path.write_text(json.dumps(summary, indent=2))
        per_out = pd.DataFrame(metrics["per_output"]).T
        per_out.index.name = "output"
        per_out.to_csv(out_dir / "per_output_metrics_xgb.csv")
        print(f"  {layer}: OOF R2 mean {agg['r2_mean']:.4f}, median {agg['r2_median']:.4f}, "
              f">0.9 {agg['n_outputs_r2_above_0.9']}/{agg['n_outputs_total']}")


def run_eval_both():
    from surrogate_eval import EvalConfig, run_eval
    for layer in ("system", "regional"):
        out_dir = Path(LAYERS[layer]["out"])
        t = time.perf_counter()
        # Same guard as run_pipeline: in reeds2 the final REPORT.md step fails
        # (pandas needs `tabulate`) after every CSV and figure has been written.
        try:
            run_eval(EvalConfig(output_dir=out_dir, data_path=Path(LAYERS[layer]["data"]),
                                layer=out_dir.name))
        except Exception as exc:  # noqa: BLE001
            print(f"[eval] {layer}: stopped at the report step ({type(exc).__name__}: {exc})")
        print(f"{layer}: eval {time.perf_counter() - t:.0f} s")


if __name__ == "__main__":
    {"fit": fit, "eval": run_eval_both}[sys.argv[1]]()
