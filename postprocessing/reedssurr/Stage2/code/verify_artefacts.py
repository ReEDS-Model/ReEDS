"""Verify all surrogate artefacts load + their UQ pathways work.

Run after a training pipeline finishes to confirm everything is in order
before the dashboard relies on them.

Example
-------
    python verify_artefacts.py                                 # defaults to overall layer
    python verify_artefacts.py --results-dir ../outputs/regional
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from surrogate_predict import load_artifact, predict  # noqa: E402
from surrogate_uq import (  # noqa: E402
    conformal_widths,
    empirical_coverage,
    ngboost_interval,
    prediction_interval,
)


def verify_one(path: Path, levels: dict[str, str]) -> dict:
    art = load_artifact(path)
    name = art.get("display_name", path.stem)
    point = predict(art, levels)

    out: dict = {
        "path": str(path),
        "name": name,
        "n_outputs": len(art["y_cols"]),
        "has_oof_residuals": "oof_residuals" in art,
        "r2_mean": art.get("oof_r2_mean"),
        "r2_median": art.get("oof_r2_median"),
    }
    if "oof_residuals" in art:
        out["conformal"] = empirical_coverage(art, alpha=0.1)
        _, lo, hi = prediction_interval(art, levels, alpha=0.1)
        cap_lo = lo[[c for c in lo.index if c.startswith("cap_")]].sum() / 1e3
        cap_hi = hi[[c for c in hi.index if c.startswith("cap_")]].sum() / 1e3
        out["cap_total_ci_gw"] = f"[{cap_lo:.1f}, {cap_hi:.1f}]"
    if art["model_name"] == "ngboost":
        ng = ngboost_interval(art, levels, alpha=0.1)
        if ng is not None:
            _, lo, hi = ng
            cap_lo = lo[[c for c in lo.index if c.startswith("cap_")]].sum() / 1e3
            cap_hi = hi[[c for c in hi.index if c.startswith("cap_")]].sum() / 1e3
            out["ngboost_cap_total_ci_gw"] = f"[{cap_lo:.1f}, {cap_hi:.1f}]"
    cap_total = point[[c for c in point.index if c.startswith("cap_")]].sum() / 1e3
    out["cap_total_gw"] = round(float(cap_total), 1)
    return out


def main(results_dir: Path):
    levels = {
        "Dem": "Md", "Fuel": "Md", "REcost": "Md",
        "Siting": "Ref", "Batt": "Md", "Pol": "IRA",
    }
    print(f"Reference design: {levels}\n")
    models_dir = results_dir / "models"
    if not models_dir.exists():
        print(f"!! No models/ dir under {results_dir}")
        sys.exit(1)
    rows = []
    for joblib_path in sorted(models_dir.glob("*.joblib")):
        try:
            rows.append(verify_one(joblib_path, levels))
        except Exception as exc:
            print(f"!! {joblib_path.name}: {exc}")
    print(f"{'Model':<40} {'n_out':>6} {'R²_mean':>8} {'R²_med':>8} {'Cap (GW)':>10} {'Conformal 90% CI':>22}")
    print("-" * 100)
    for r in rows:
        cov = r.get("conformal", {}).get("coverage_mean", None)
        cov_str = f"{cov:.3f}" if cov is not None else "n/a"
        ci = r.get("cap_total_ci_gw", "—")
        r2m = r.get("r2_mean")
        r2d = r.get("r2_median")
        r2m_str = f"{r2m:.3f}" if r2m is not None else "n/a"
        r2d_str = f"{r2d:.3f}" if r2d is not None else "n/a"
        print(f"{r['name']:<40} {r['n_outputs']:>6d} {r2m_str:>8} {r2d_str:>8} "
              f"{r['cap_total_gw']:>10.1f}  {ci:>20}  (cov={cov_str})")
        if "ngboost_cap_total_ci_gw" in r:
            print(f"   -> NGBoost-native 90% CI: {r['ngboost_cap_total_ci_gw']} GW")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", type=Path,
                    default=HERE.parent / "outputs" / "overall")
    args = ap.parse_args()
    main(args.results_dir)
