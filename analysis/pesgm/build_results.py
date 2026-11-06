"""Assemble results.md from the per-item fragments results_0X.md.

The header (scope, environment, contradictions with the draft) is written
here; every number in the body comes from the scripts.
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent

HEADER = """# ReEDS surrogate (ReEDS-Proxy) - PESGM supporting analysis

All numbers below were produced by the scripts in this folder from the stored
Stage 2 training tables (`postprocessing/reedssurr/Stage2/inputs/*_ml_numeric_merged.csv`),
the stored model artefacts (OneDrive `reedssurr_models/Stage2/<layer>/models/*.joblib`,
which carry the 10-fold out-of-fold residuals) and the Stage 2 surrogate code.
No ReEDS run was repeated. Random seed 42 and the same `KFold(10, shuffle=True)`
split as the pipeline are used throughout; the re-computed RF out-of-fold
predictions match the stored residuals to float32 precision (NGBoost is not
bit-reproducible because its tree learner is unseeded, but its aggregate R-squared is).
Environment: conda env `reeds2` (Python 3.11, scikit-learn 1.2.2, xgboost 3.2.0,
ngboost 0.5.8), 14 logical cores.

Scripts: `00_pipeline_summary.py` ... `07_regional.py` (one per item), `08_ercot_map.py`
(map of the seven ERCOT BAs, `figs/fig08_ercot_bas`), shared
helpers in `pesgm_common.py`, this assembler in `build_results.py`.
Figures are in `figs/` as PDF and 300-dpi PNG (3.5 in wide, 8 pt Arial,
no titles, colour-blind-safe palette); tables and per-output values are in `data/`.

## Where the results contradict or qualify the draft

- **Coverage.** The draft's split-conformal 90 % band is calibrated and
  evaluated on the same residuals in the existing code, so any coverage
  number taken from `surrogate_eval` (89.9-91.2 %) is circular. The honest
  cross-fold number is in item 1. The RF conformal band is in fact well calibrated
  (90.2 % cross-fold); the NGBoost native interval is slightly under-covered
  (88-89 %) and the conformal correction reported there fixes it.
- **"Four domain constraints".** The constraints module implements five; for
  the RF surrogate the paper reports, only three act at inference
  (non-negativity, DistPV override, cost decomposition). The regional
  additivity rescale is implemented but never called by the dashboard, and the
  monotone hints apply to XGBoost only. See items 0, 4 and 7.
- **Output count.** One of the 66 system outputs is `runtime_seconds` (ReEDS
  solve time), so 65 are energy-system quantities.
- **No hyperparameter search.** All model hyperparameters are fixed constants
  in the code; there is no grid.
- **Extrapolation.** Leave-one-level-out (item 3) shows the RF cannot
  extrapolate to an unsampled dial level or interpolate the middle level from
  the two outer ones; the continuous dashboard sliders therefore interpolate
  tree plateaus, not physics.
- **Inference latency.** The deployed RF artefact takes seconds, not
  milliseconds, per single-design prediction on Windows because of joblib
  multiprocess dispatch inside `MultiOutputRegressor` (item 0). Any
  "speed-up" figure should be stated with the measured latency.
- The headline R-squared values in the draft (RF system 0.75 / 0.88, regional
  0.63 / 0.72) are reproduced exactly and are not contradicted.

"""


def main():
    parts = [HEADER]
    for i in range(8):
        matches = sorted(HERE.glob(f"results_0{i}.md"))
        if not matches:
            parts.append(f"## {i}. (not generated)\n")
            continue
        parts.append(matches[0].read_text(encoding="utf-8"))
    (HERE / "results.md").write_text("\n".join(parts), encoding="utf-8")
    print("wrote results.md")


if __name__ == "__main__":
    main()
