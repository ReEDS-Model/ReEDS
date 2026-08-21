"""
Research-grade evaluation for ReEDS-Proxy models.

This module is *strictly* additive to the existing pipeline:

* ``surrogate_predict.py`` is never imported in a way that mutates it; we only
  pull read-only helpers (``clip_physical_bounds``, ``_is_storage_gen``,
  ``_is_negative_cost``).
* ``surrogate_ml_models.py`` is left in place. We *reuse* the artifacts it
  writes to ``<output_dir>/models/<name>.joblib`` — every artifact already
  carries ``oof_residuals`` so we can reconstruct OOF predictions via
  ``Y_pred = Y_true - oof_residuals`` and never need to retrain.
* ``surrogate_uq.py`` is finally wired in for calibration / sharpness.

The module produces a folder ``<output_dir>/eval/`` containing:

* ``per_output_metrics_<model>.csv``      (parsed + bias + variance metrics)
* ``grouped_by_<dim>_<model>.csv``        (dim ∈ category / tech / region)
* ``calibration_<model>.csv``             (coverage vs nominal at each alpha)
* ``bias_by_design_<model>.csv``          (residual stats per (x_dim, level))
* ``distribution_fidelity_<model>.csv``   (KS, Spearman, std ratio per output)
* ``build_classification_<model>.csv``    (deployed-or-not accuracy for cap_*)
* ``per_case_error_ranking.csv``          (worst factorial corners)
* ``per_output_difficulty.csv``           (intrinsically vs model-specific hard)
* ``model_ranking_bootstrap.csv``         (CI on each model's mean/median R²)
* ``model_ranking_bootstrap_pwise.csv``   ("P(A > B)" matrix from bootstrap)
* ``clipping_delta_<model>.csv``          (metrics with vs without clipping)
* ``headline_scalars_<model>.csv``        (cost_total + total cap/gen point+CI)
* Figures under ``eval/figs/``.
* ``REPORT.md`` and ``REPORT.html`` consolidating the lot.

Run from the CLI:

    python surrogate_eval.py --output_dir ../outputs/overall --data ../inputs/overall_ml_numeric.csv

Or programmatically:

    from surrogate_eval import EvalConfig, run_eval
    run_eval(EvalConfig(
        output_dir=Path("../outputs/regional"),
        data_path=Path("../inputs/regional_ml_numeric.csv"),
        layer="regional",
    ))
"""

from __future__ import annotations

import argparse
import json
import pickle
import re
import sys
import textwrap
import traceback
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import (
    confusion_matrix,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)

# Read-only imports from the existing pipeline. We never edit these modules.
from surrogate_predict import (   # noqa: E402
    _is_negative_cost,
    _is_storage_gen,
    clip_physical_bounds,
)
from surrogate_paths import resolve_models_dir  # noqa: E402
from surrogate_uq import (        # noqa: E402
    _ngboost_estimators,
    conformal_widths,
    empirical_coverage,
)

# Shared plain-language captions (used here AND in surrogate_dashboard.py).
from surrogate_eval_captions import (   # noqa: E402
    auto_readout_extrapolation,
    auto_readout_r0,
    auto_readout_r5,
    md_explainer,
    md_intro,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# ReEDS Y-column categories we recognise. Anything else is grouped under "misc".
KNOWN_CATEGORIES: tuple[str, ...] = ("cap", "gen", "tran", "cost")

# Region tokens look like p60, s37, r12, st02. Matched at the END of the name.
_REGION_RE = re.compile(r"_(?P<region>(?:p|s|r|st|ba)\d+)$", re.IGNORECASE)


@dataclass
class EvalConfig:
    """Drives ``run_eval``. All thresholds + alphas live here, not in the body.

    Parameters
    ----------
    output_dir
        Layer's root directory (contains ``models/`` and ``summary.json``).
        The eval module writes everything under ``output_dir / "eval"``.
    data_path
        Path to ``<layer>_ml_numeric.csv`` containing ``case_name``, ``x_*``,
        and Y columns. Used to recover ``Y_true`` and the design matrix.
    layer
        Free-form label written into the report. We don't infer it from
        ``output_dir`` so the caller stays in control.
    alpha_levels
        Miscoverage levels for the calibration sweep. Default covers 50% to
        95% nominal coverage.
    mostly_zero_threshold
        An output is flagged "mostly zero" if the *fraction of training rows*
        where ``|y| > eps`` is below this threshold. Defaults to 0.05 (i.e.
        tech deployed in <5% of cases). ``eps`` is ``mostly_zero_eps``.
    mostly_zero_eps
        Absolute threshold under which a value is treated as "not deployed".
        Defaults to 1e-3 — small enough to ignore numerical noise but
        permissive enough not to drop tiny pilot capacity.
    bootstrap_n
        Resamples drawn over the 486 OOF rows for the ranking-robustness CI.
    bootstrap_seed
        Seed for reproducibility.
    structured_cv
        If True, additionally run a leave-one-level-out diagnostic for each
        design dimension to measure extrapolation. SLOW (re-trains models) —
        off by default.
    ngboost_native
        If True, additionally compute NGBoost native-distribution calibration
        by re-running OOF for the NGBoost artifact. Off by default because it
        roughly doubles the eval runtime when NGBoost is present.
    include_clipped
        If True (default), produce a side-by-side metrics table comparing
        unclipped vs clipped OOF predictions, since deployed predictions
        are clipped.
    skip_models
        Skip these model names (matched against ``model_name`` in artifacts).
        Useful to leave out heavy baselines for fast iteration.
    n_methods_compare
        Number of top methods to surface in cross-method comparison panels
        (e.g. §4 per-catalog, §5 cross-layer). Defaults to 6. The selection
        uses the honest §R0 ranking (per-output mean R² with bootstrap CIs),
        not §1's pooled score.
    """

    output_dir: Path
    data_path: Path
    layer: str = "overall"
    alpha_levels: Sequence[float] = (0.5, 0.3, 0.2, 0.1, 0.05)
    mostly_zero_threshold: float = 0.05
    mostly_zero_eps: float = 1e-3
    bootstrap_n: int = 500
    bootstrap_seed: int = 42
    structured_cv: bool = False
    ngboost_native: bool = False
    include_clipped: bool = True
    skip_models: tuple[str, ...] = ()
    n_methods_compare: int = 6

    @property
    def eval_dir(self) -> Path:
        return Path(self.output_dir) / "eval"

    @property
    def figs_dir(self) -> Path:
        return self.eval_dir / "figs"


# ---------------------------------------------------------------------------
# Output-name parsing + helpers
# ---------------------------------------------------------------------------

def parse_output_name(col: str) -> tuple[str, str, Optional[str]]:
    """Split a ReEDS Y column into ``(category, tech, region | None)``.

    Examples
    --------
    >>> parse_output_name("cap_upv")
    ('cap', 'upv', None)
    >>> parse_output_name("gen_gas-cc_p60")
    ('gen', 'gas-cc', 'p60')
    >>> parse_output_name("cost_op_vom_costs")
    ('cost', 'op_vom_costs', None)
    >>> parse_output_name("runtime_seconds")
    ('misc', 'runtime_seconds', None)
    """
    if not col:
        return "misc", col, None
    # Region tag at the end?
    region = None
    m = _REGION_RE.search(col)
    if m:
        region = m.group("region")
        col_core = col[: m.start()]
    else:
        col_core = col
    parts = col_core.split("_", 1)
    if len(parts) == 1:
        return "misc", parts[0], region
    head, tail = parts[0].lower(), parts[1]
    if head in KNOWN_CATEGORIES:
        return head, tail or "(unknown)", region
    return "misc", col_core, region


def _safe_div(num: float, den: float) -> float:
    if den == 0 or not np.isfinite(den):
        return float("nan")
    return float(num / den)


def _bootstrap_indices(n: int, n_resamples: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, n, size=(n_resamples, n))


# ---------------------------------------------------------------------------
# Artifact + OOF loading
# ---------------------------------------------------------------------------

@dataclass
class ModelOOF:
    """OOF predictions + metadata for one model in one layer."""

    name: str
    display_name: str
    Y_true: np.ndarray
    Y_pred: np.ndarray
    y_cols: list[str]
    artifact: dict
    artifact_path: Path
    reconstructed: bool   # True if rebuilt from oof_residuals (cheap)


def _load_training_arrays(cfg: EvalConfig) -> tuple[
    np.ndarray, np.ndarray, list[str], list[str], list[str]
]:
    """Load X, Y, x_cols, y_cols, case_names from the numeric training CSV.

    Y is filtered to the same non-constant columns the training pipeline saw,
    so the columns line up with what each artifact stores in ``y_cols``.
    """
    df = pd.read_csv(cfg.data_path)
    if "case_name" in df.columns:
        case_names = df["case_name"].astype(str).tolist()
    else:
        case_names = [f"case_{i:04d}" for i in range(len(df))]
    x_cols = [c for c in df.columns if c.startswith("x_")]
    y_cols_full = [c for c in df.columns if not c.startswith("x_") and c != "case_name"]
    X = df[x_cols].to_numpy(dtype=np.float64)
    Y_full = df[y_cols_full].to_numpy(dtype=np.float64)
    return X, Y_full, x_cols, y_cols_full, case_names


def _align_y_to_artifact(
    Y_full: np.ndarray, y_cols_full: list[str], target_cols: list[str]
) -> np.ndarray:
    """Slice ``Y_full`` to match the artifact's ``y_cols`` order.

    Returns a contiguous ``(n_samples, len(target_cols))`` array. Raises if
    a target column isn't present (would mean a stale artifact vs data).
    """
    idx = {c: i for i, c in enumerate(y_cols_full)}
    try:
        cols = [idx[c] for c in target_cols]
    except KeyError as exc:
        missing = exc.args[0]
        raise ValueError(
            f"Artifact references column '{missing}' that is no longer in "
            f"the training data. Retrain or restore the CSV."
        ) from exc
    return Y_full[:, cols]


def load_all_oof(cfg: EvalConfig) -> tuple[dict[str, ModelOOF], np.ndarray, list[str], list[str]]:
    """Load every model artifact under ``output_dir/models`` and rebuild OOF.

    Returns
    -------
    models
        Dict ``{model_name: ModelOOF}`` keyed by short artifact name.
    X
        Encoded design matrix (n_samples, n_x_features). Useful for residual-
        vs-design plots and (optional) structured CV.
    x_cols
        Names of the X columns (``x_Dem`` etc.).
    case_names
        Row labels for the 486 cases.
    """
    models_dir = resolve_models_dir(cfg.output_dir)
    if not models_dir.exists():
        raise FileNotFoundError(f"Models directory not found: {models_dir}")
    X, Y_full, x_cols, y_cols_full, case_names = _load_training_arrays(cfg)

    out: dict[str, ModelOOF] = {}
    for jp in sorted(models_dir.glob("*.joblib")):
        name = jp.stem
        if name in cfg.skip_models:
            continue
        try:
            with open(jp, "rb") as f:
                art = pickle.load(f)
        except Exception as exc:  # noqa: BLE001 - corrupt artifact, skip
            warnings.warn(f"Could not load {jp.name}: {exc}")
            continue
        y_cols_art = list(art.get("y_cols", []))
        if not y_cols_art:
            warnings.warn(f"Artifact {jp.name} has no y_cols, skipping")
            continue
        try:
            Y_true = _align_y_to_artifact(Y_full, y_cols_full, y_cols_art)
        except ValueError as exc:
            warnings.warn(f"{jp.name}: {exc}")
            continue
        resid = art.get("oof_residuals")
        if resid is None:
            warnings.warn(
                f"{jp.name} has no oof_residuals — skipping. Retrain to "
                f"populate (current training pipeline writes them)."
            )
            continue
        resid = np.asarray(resid, dtype=np.float64)
        if resid.shape != Y_true.shape:
            warnings.warn(
                f"{jp.name}: residual shape {resid.shape} != Y_true shape "
                f"{Y_true.shape}; skipping."
            )
            continue
        Y_pred = Y_true - resid
        out[name] = ModelOOF(
            name=name,
            display_name=str(art.get("display_name", name)),
            Y_true=Y_true,
            Y_pred=Y_pred,
            y_cols=y_cols_art,
            artifact=art,
            artifact_path=jp,
            reconstructed=True,
        )
    if not out:
        raise RuntimeError(
            f"No usable artifacts in {models_dir}. Train models first."
        )
    return out, X, x_cols, case_names


def apply_physical_clipping(Y_pred: np.ndarray, y_cols: list[str]) -> np.ndarray:
    """Apply the deployed clipping rules vectorised.

    Mirrors the rules in ``surrogate_predict.clip_physical_bounds`` (which we
    read but never edit): non-negativity is enforced for ``cap_*``, ``tran_*``,
    non-storage ``gen_*``, and non-incentive ``cost_*``. Storage ``gen_*`` and
    ``*_negative`` cost columns are left untouched. We use the predict.py
    helpers ``_is_storage_gen`` / ``_is_negative_cost`` to derive the per-
    column mask so any future relaxation in predict.py propagates here too.
    """
    clip_mask = np.zeros(len(y_cols), dtype=bool)   # True ⇒ floor at 0
    for i, col in enumerate(y_cols):
        if col.startswith("cap_") or col.startswith("tran_"):
            clip_mask[i] = True
        elif col.startswith("gen_"):
            clip_mask[i] = not _is_storage_gen(col)
        elif col.startswith("cost_"):
            clip_mask[i] = not _is_negative_cost(col)
        # otherwise leave as-is (matches predict.py "else: unchanged")
    out = Y_pred.copy()
    if clip_mask.any():
        # Only floor the columns that are clip-eligible AND have a value < 0.
        cols = np.where(clip_mask)[0]
        sub = out[:, cols]
        sub[sub < 0] = 0.0
        out[:, cols] = sub
    return out


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def per_output_metrics(
    Y_true: np.ndarray,
    Y_pred: np.ndarray,
    y_cols: list[str],
) -> pd.DataFrame:
    """Compute the per-output metric panel used by every downstream section.

    Columns
    -------
    output, category, tech, region, n_samples, y_mean, y_std, y_range,
    n_nonzero_cases, frac_nonzero, mostly_zero, r2, rmse, mae, nrmse,
    mean_signed_residual, normalized_bias_meanabs, normalized_bias_range,
    spearman, ks_stat, ks_p, std_ratio, mae_over_range
    """
    n_samples, n_outputs = Y_true.shape
    rows = []
    eps = 1e-12
    for i in range(n_outputs):
        col = y_cols[i]
        cat, tech, region = parse_output_name(col)
        yt = Y_true[:, i]
        yp = Y_pred[:, i]
        y_mean = float(np.mean(yt))
        y_std = float(np.std(yt))
        y_range = float(yt.max() - yt.min())
        nz_mask = np.abs(yt) > eps
        n_nonzero = int(nz_mask.sum())
        frac_nonzero = float(n_nonzero / n_samples) if n_samples else 0.0

        # r2_score is undefined when y_true is constant; report NaN.
        if y_std < eps:
            r2 = float("nan")
        else:
            r2 = float(r2_score(yt, yp))
        rmse = float(np.sqrt(mean_squared_error(yt, yp)))
        mae = float(mean_absolute_error(yt, yp))
        nrmse = _safe_div(rmse, y_range)
        signed = yp - yt
        mean_signed = float(signed.mean())
        mean_abs_true = float(np.mean(np.abs(yt)))
        norm_bias_meanabs = _safe_div(mean_signed, mean_abs_true)
        norm_bias_range = _safe_div(mean_signed, y_range)
        # Spearman: undefined for constants.
        if y_std < eps or np.std(yp) < eps:
            spearman = float("nan")
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                spearman = float(stats.spearmanr(yt, yp).statistic)
        # KS between marginal distributions of OOF prediction vs actual.
        if y_std < eps and np.std(yp) < eps:
            ks_stat, ks_p = float("nan"), float("nan")
        else:
            res = stats.ks_2samp(yt, yp)
            ks_stat = float(res.statistic)
            ks_p = float(res.pvalue)
        std_ratio = _safe_div(float(np.std(yp)), y_std)
        mae_over_range = _safe_div(mae, y_range)

        rows.append({
            "output": col,
            "category": cat,
            "tech": tech,
            "region": region or "",
            "n_samples": int(n_samples),
            "y_mean": y_mean,
            "y_std": y_std,
            "y_range": y_range,
            "n_nonzero_cases": n_nonzero,
            "frac_nonzero": frac_nonzero,
            "r2": r2,
            "rmse": rmse,
            "mae": mae,
            "nrmse": nrmse,
            "mean_signed_residual": mean_signed,
            "normalized_bias_meanabs": norm_bias_meanabs,
            "normalized_bias_range": norm_bias_range,
            "spearman": spearman,
            "ks_stat": ks_stat,
            "ks_p": ks_p,
            "std_ratio": std_ratio,
            "mae_over_range": mae_over_range,
        })
    df = pd.DataFrame(rows)
    df["mostly_zero"] = df["frac_nonzero"] < 0  # placeholder; set by caller with cfg
    return df


def _mark_mostly_zero(df: pd.DataFrame, cfg: EvalConfig) -> pd.DataFrame:
    df = df.copy()
    df["mostly_zero"] = df["frac_nonzero"] < cfg.mostly_zero_threshold
    return df


def _group_summary(df: pd.DataFrame, by: str) -> pd.DataFrame:
    """Aggregate the per-output panel by category / tech / region.

    Excludes mostly-zero outputs from the *headline* R² mean / median (those
    are reported separately as ``n_excluded_mostly_zero``).
    """
    if df.empty:
        return pd.DataFrame()
    active = df[~df["mostly_zero"]]
    grp = active.groupby(by)
    out = grp.agg(
        n_outputs=("output", "count"),
        r2_mean=("r2", "mean"),
        r2_median=("r2", "median"),
        rmse_mean=("rmse", "mean"),
        mae_mean=("mae", "mean"),
        nrmse_mean=("nrmse", "mean"),
        signed_bias_mean=("mean_signed_residual", "mean"),
        norm_bias_meanabs_median=("normalized_bias_meanabs", "median"),
        spearman_median=("spearman", "median"),
        std_ratio_median=("std_ratio", "median"),
    )
    # Tag how many were excluded for transparency.
    excluded = df[df["mostly_zero"]].groupby(by).size().rename("n_excluded_mostly_zero")
    out = out.join(excluded, how="left").fillna({"n_excluded_mostly_zero": 0})
    out["n_excluded_mostly_zero"] = out["n_excluded_mostly_zero"].astype(int)
    return out.reset_index().sort_values("r2_median", ascending=False)


# ---------------------------------------------------------------------------
# Section 2: bias diagnostics
# ---------------------------------------------------------------------------

def _plot_residual_vs_predicted(
    Y_true: np.ndarray, Y_pred: np.ndarray, y_cols: list[str],
    model_name: str, out_path: Path,
) -> None:
    """One scatter per category, colored by within-category density."""
    cats: dict[str, list[int]] = {}
    for i, col in enumerate(y_cols):
        cat, _, _ = parse_output_name(col)
        cats.setdefault(cat, []).append(i)
    cats = {k: v for k, v in cats.items() if k in KNOWN_CATEGORIES}
    if not cats:
        return
    fig, axes = plt.subplots(1, len(cats), figsize=(4 * len(cats), 4), squeeze=False)
    for ax, (cat, idxs) in zip(axes[0], cats.items()):
        yt = Y_true[:, idxs].ravel()
        yp = Y_pred[:, idxs].ravel()
        resid = yp - yt
        ax.scatter(yp, resid, s=4, alpha=0.25, color="steelblue", edgecolor="none")
        ax.axhline(0.0, color="red", linewidth=0.8, linestyle="--", alpha=0.6)
        ax.set_xlabel("Predicted")
        ax.set_ylabel("Residual (pred − actual)")
        ax.set_title(f"{cat}_* (n={len(idxs)} outputs)")
    fig.suptitle(f"Residual vs predicted — {model_name}", fontsize=11)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _plot_residual_by_design(
    X: np.ndarray, x_cols: list[str],
    Y_true: np.ndarray, Y_pred: np.ndarray, y_cols: list[str],
    model_name: str, out_path: Path,
) -> pd.DataFrame:
    """Boxplots of *normalized* residual (per-output range-scaled) by x level.

    The factorial-DoE killer view: bias by each design dimension separately
    shows whether the surrogate fails at specific corners (e.g. always under-
    predicts capacity at Hi demand).
    """
    # Per-output range for normalisation.
    y_range = (Y_true.max(axis=0) - Y_true.min(axis=0))
    with np.errstate(divide="ignore", invalid="ignore"):
        norm_resid = np.where(
            y_range > 0,
            (Y_pred - Y_true) / y_range[None, :],
            0.0,
        )
    # mean across outputs gives a scalar "bias signal" per case.
    case_mean_norm_resid = norm_resid.mean(axis=1)
    case_med_norm_resid = np.median(norm_resid, axis=1)

    rows = []
    n_dims = len(x_cols)
    fig, axes = plt.subplots(1, n_dims, figsize=(2.7 * n_dims, 3.6), squeeze=False)
    for j, col in enumerate(x_cols):
        ax = axes[0][j]
        levels = sorted(np.unique(X[:, j]).tolist())
        data = [case_mean_norm_resid[X[:, j] == lvl] for lvl in levels]
        # matplotlib renamed boxplot's ``labels`` -> ``tick_labels`` in 3.9;
        # set tick labels explicitly so we work on both old and new releases.
        ax.boxplot(data, showfliers=True, widths=0.6)
        ax.set_xticks(range(1, len(levels) + 1))
        ax.set_xticklabels([str(int(l)) for l in levels])
        ax.axhline(0.0, color="red", linewidth=0.8, linestyle="--", alpha=0.6)
        ax.set_title(col)
        ax.set_xlabel("level (int code)")
        if j == 0:
            ax.set_ylabel("mean of (pred − actual)/range\nacross outputs")
        for lvl, arr in zip(levels, data):
            rows.append({
                "x_dim": col,
                "level": int(lvl),
                "n_cases": int(len(arr)),
                "mean_norm_resid_mean": float(np.mean(arr)),
                "mean_norm_resid_median": float(np.median(arr)),
                "mean_norm_resid_std": float(np.std(arr)),
                "median_norm_resid_median": float(np.median(case_med_norm_resid[X[:, j] == lvl])),
            })
    fig.suptitle(f"Residual by design dimension — {model_name}", fontsize=11)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return pd.DataFrame(rows)


def _plot_qq_by_category(
    Y_true: np.ndarray, Y_pred: np.ndarray, y_cols: list[str],
    model_name: str, out_path: Path,
) -> None:
    """Q-Q plot of standardised residuals per category vs Normal."""
    cats: dict[str, list[int]] = {}
    for i, col in enumerate(y_cols):
        cat, _, _ = parse_output_name(col)
        cats.setdefault(cat, []).append(i)
    cats = {k: v for k, v in cats.items() if k in KNOWN_CATEGORIES}
    if not cats:
        return
    fig, axes = plt.subplots(1, len(cats), figsize=(4 * len(cats), 4), squeeze=False)
    for ax, (cat, idxs) in zip(axes[0], cats.items()):
        resid = (Y_pred[:, idxs] - Y_true[:, idxs]).ravel()
        sd = np.std(resid)
        if sd < 1e-12:
            ax.set_title(f"{cat}_* (constant residual)")
            continue
        std = (resid - resid.mean()) / sd
        # Use a subsample for very large pools to keep the plot legible.
        if std.size > 5000:
            rng = np.random.default_rng(0)
            std = rng.choice(std, size=5000, replace=False)
        stats.probplot(std, dist="norm", plot=ax)
        ax.set_title(f"{cat}_* residuals vs Normal")
    fig.suptitle(f"Q-Q of standardised residuals — {model_name}", fontsize=11)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Section 3: interval calibration (uses surrogate_uq)
# ---------------------------------------------------------------------------

def _coverage_table(
    art: dict, per_output_df: pd.DataFrame, alphas: Sequence[float],
) -> pd.DataFrame:
    """Per-alpha, per-category split-conformal coverage + sharpness."""
    resid = np.asarray(art.get("oof_residuals"), dtype=np.float64)
    y_cols = list(art["y_cols"])
    cats = np.array([parse_output_name(c)[0] for c in y_cols])
    techs = np.array([parse_output_name(c)[1] for c in y_cols])

    rows = []
    for alpha in alphas:
        half = conformal_widths(art, alpha=float(alpha))
        inside = np.abs(resid) <= half[None, :]   # (n_samples, n_outputs)
        cov_per_out = inside.mean(axis=0)
        # Sharpness: half-width / column range. Skip constants → NaN.
        y_range = per_output_df.set_index("output").loc[y_cols, "y_range"].to_numpy()
        with np.errstate(divide="ignore", invalid="ignore"):
            sharp_per_out = np.where(y_range > 0, 2.0 * half / y_range, np.nan)
        rows.append({
            "alpha": float(alpha),
            "nominal_coverage": 1.0 - float(alpha),
            "group": "ALL",
            "n_outputs": len(y_cols),
            "coverage_mean": float(np.nanmean(cov_per_out)),
            "coverage_min": float(np.nanmin(cov_per_out)),
            "coverage_max": float(np.nanmax(cov_per_out)),
            "sharpness_median": float(np.nanmedian(sharp_per_out)),
            "sharpness_p90": float(np.nanpercentile(sharp_per_out[~np.isnan(sharp_per_out)], 90))
                              if np.any(~np.isnan(sharp_per_out)) else float("nan"),
        })
        for cat in KNOWN_CATEGORIES:
            mask = cats == cat
            if not mask.any():
                continue
            rows.append({
                "alpha": float(alpha),
                "nominal_coverage": 1.0 - float(alpha),
                "group": f"category={cat}",
                "n_outputs": int(mask.sum()),
                "coverage_mean": float(np.nanmean(cov_per_out[mask])),
                "coverage_min": float(np.nanmin(cov_per_out[mask])),
                "coverage_max": float(np.nanmax(cov_per_out[mask])),
                "sharpness_median": float(np.nanmedian(sharp_per_out[mask])),
                "sharpness_p90": float(np.nanpercentile(
                    sharp_per_out[mask][~np.isnan(sharp_per_out[mask])], 90,
                )) if np.any(~np.isnan(sharp_per_out[mask])) else float("nan"),
            })
    return pd.DataFrame(rows)


def _plot_calibration(coverage_df: pd.DataFrame, out_path: Path,
                      models: Iterable[str]) -> None:
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot([0, 1], [0, 1], color="black", linewidth=0.8, alpha=0.5,
            label="Perfect calibration")
    for m in models:
        sub = coverage_df[(coverage_df["model"] == m) & (coverage_df["group"] == "ALL")]
        if sub.empty:
            continue
        sub = sub.sort_values("nominal_coverage")
        ax.plot(sub["nominal_coverage"], sub["coverage_mean"],
                marker="o", linewidth=1.2, label=m)
    ax.set_xlabel("Nominal coverage (1 − α)")
    ax.set_ylabel("Empirical coverage (mean across outputs)")
    ax.set_title("Split-conformal calibration sweep")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _ngboost_native_calibration(
    art: dict, X: np.ndarray, Y_true: np.ndarray, alphas: Sequence[float],
) -> Optional[pd.DataFrame]:
    """Approximate native-Normal calibration using the FINAL model.

    The artifact's NGBRegressor is trained on all 486 rows; calling
    ``pred_dist`` on the training X gives in-sample (loc, scale). Compared
    against the actual Y this is overoptimistic — but it lets us *quantify*
    how much sharper the native interval is relative to split-conformal.
    The report calls this out as in-sample.
    """
    estimators = _ngboost_estimators(art["model"])
    if estimators is None:
        return None
    x_s = art["scaler_x"].transform(X)
    means = np.empty((X.shape[0], len(estimators)))
    stds = np.empty_like(means)
    for j, est in enumerate(estimators):
        dist = est.pred_dist(x_s)
        means[:, j] = np.asarray(dist.loc).ravel()
        stds[:, j] = np.asarray(dist.scale).ravel()
    scaler_y = art.get("scaler_y")
    if scaler_y is not None:
        y_scale = np.asarray(scaler_y.scale_).ravel()
        y_mean = np.asarray(scaler_y.mean_).ravel()
        means = means * y_scale + y_mean
        stds = stds * y_scale
    rows = []
    for alpha in alphas:
        z = float(stats.norm.ppf(1.0 - alpha / 2.0))
        lo = means - z * stds
        hi = means + z * stds
        inside = (Y_true >= lo) & (Y_true <= hi)
        cov = inside.mean(axis=0)
        # Sharpness: native interval width / range
        y_range = (Y_true.max(axis=0) - Y_true.min(axis=0))
        with np.errstate(divide="ignore", invalid="ignore"):
            sharp = np.where(y_range > 0, 2.0 * z * stds.mean(axis=0) / y_range, np.nan)
        rows.append({
            "alpha": float(alpha),
            "nominal_coverage": 1.0 - float(alpha),
            "coverage_mean_insample": float(np.nanmean(cov)),
            "coverage_min_insample": float(np.nanmin(cov)),
            "coverage_max_insample": float(np.nanmax(cov)),
            "sharpness_median_insample": float(np.nanmedian(sharp)),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Section 5: distributional fidelity + decision-relevant
# ---------------------------------------------------------------------------

def _build_classification(
    Y_true: np.ndarray, Y_pred: np.ndarray, y_cols: list[str],
    eps: float,
) -> pd.DataFrame:
    """For each cap_* tech, classify "deployed (|y|>eps) vs not" per case.

    Reports accuracy, TPR, TNR per output. Outputs that are *always* one
    class (all deployed or never deployed) get NaN for the off-diagonal
    metrics so the user can see the support imbalance.
    """
    rows = []
    for i, col in enumerate(y_cols):
        cat, tech, region = parse_output_name(col)
        if cat != "cap":
            continue
        yt_bool = np.abs(Y_true[:, i]) > eps
        yp_bool = np.abs(Y_pred[:, i]) > eps
        n = len(yt_bool)
        n_pos = int(yt_bool.sum())
        n_neg = n - n_pos
        acc = float((yt_bool == yp_bool).mean())
        if n_pos > 0:
            tpr = float((yt_bool & yp_bool).sum() / n_pos)
        else:
            tpr = float("nan")
        if n_neg > 0:
            tnr = float((~yt_bool & ~yp_bool).sum() / n_neg)
        else:
            tnr = float("nan")
        rows.append({
            "output": col,
            "tech": tech,
            "region": region or "",
            "n_cases": n,
            "n_positive_true": n_pos,
            "n_negative_true": n_neg,
            "build_classification_accuracy": acc,
            "tpr": tpr,
            "tnr": tnr,
        })
    return pd.DataFrame(rows)


def _headline_scalars(
    Y_true: np.ndarray, Y_pred: np.ndarray, y_cols: list[str],
    art: dict, alpha: float = 0.1,
) -> pd.DataFrame:
    """Pick out cost_total + total-cap + total-gen as marquee numbers.

    For each headline, return the per-case point + symmetric conformal
    interval and the resulting R² across the 486 cases.
    """
    rows = []
    name_to_idx = {c: i for i, c in enumerate(y_cols)}
    half = conformal_widths(art, alpha=alpha)

    def _row(label: str, vec_true: np.ndarray, vec_pred: np.ndarray, hw: float):
        r2 = float(r2_score(vec_true, vec_pred)) if vec_true.std() > 1e-12 else float("nan")
        rmse = float(np.sqrt(mean_squared_error(vec_true, vec_pred)))
        return {
            "headline": label,
            "n_cases": len(vec_true),
            "y_mean_actual": float(vec_true.mean()),
            "y_mean_predicted": float(vec_pred.mean()),
            "mean_signed_residual": float((vec_pred - vec_true).mean()),
            "r2": r2,
            "rmse": rmse,
            "conformal_half_width_at_alpha_0p1": float(hw),
            "conformal_relative_width": _safe_div(2 * hw, float(vec_true.max() - vec_true.min())),
        }

    # cost_total
    if "cost_total" in name_to_idx:
        i = name_to_idx["cost_total"]
        rows.append(_row("cost_total", Y_true[:, i], Y_pred[:, i], half[i]))

    # totals over a category — sum across cap_/gen_/tran_ columns per case
    for cat in ("cap", "gen", "tran"):
        idxs = [name_to_idx[c] for c in y_cols
                if parse_output_name(c)[0] == cat and c in name_to_idx]
        if not idxs:
            continue
        totals_true = Y_true[:, idxs].sum(axis=1)
        totals_pred = Y_pred[:, idxs].sum(axis=1)
        # Conformal half-width for a sum-of-outputs is *not* sum-of-halves
        # in general — we approximate with the quadrature sum of halves
        # (would be exact under independence). Document the caveat in the
        # report.
        hw_total = float(np.sqrt(np.sum(half[idxs] ** 2)))
        rows.append(_row(f"total_{cat}", totals_true, totals_pred, hw_total))

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Section 6: worst-case attribution
# ---------------------------------------------------------------------------

def _per_case_error_ranking(
    Y_true: np.ndarray, Y_pred: np.ndarray, y_cols: list[str],
    X: np.ndarray, x_cols: list[str], case_names: list[str],
    per_output_df: pd.DataFrame,
) -> pd.DataFrame:
    """Rank the 486 cases by aggregate normalised error.

    Aggregate = mean across outputs of |resid| / column range, ignoring
    columns with zero range (constants) so they don't pull the mean toward 0.
    """
    y_range = per_output_df.set_index("output").loc[y_cols, "y_range"].to_numpy()
    abs_resid = np.abs(Y_pred - Y_true)
    with np.errstate(divide="ignore", invalid="ignore"):
        norm = np.where(y_range > 0, abs_resid / y_range[None, :], np.nan)
    case_mean = np.nanmean(norm, axis=1)
    case_max = np.nanmax(norm, axis=1)
    case_worst_output_idx = np.nanargmax(norm, axis=1)

    rows = []
    for i in range(Y_true.shape[0]):
        rows.append({
            "case_index": i,
            "case_name": case_names[i] if i < len(case_names) else f"case_{i:04d}",
            "mean_normalized_error": float(case_mean[i]),
            "max_normalized_error": float(case_max[i]),
            "worst_output": y_cols[int(case_worst_output_idx[i])],
            **{x_cols[j]: int(X[i, j]) for j in range(len(x_cols))},
        })
    df = pd.DataFrame(rows).sort_values("mean_normalized_error", ascending=False)
    df["rank"] = np.arange(1, len(df) + 1)
    return df.reset_index(drop=True)


def _output_difficulty_table(
    models: dict[str, ModelOOF], cfg: EvalConfig,
) -> pd.DataFrame:
    """Per-output R² across all models — flags 'intrinsic' vs 'model-specific' hard.

    An output is "intrinsically hard" if EVERY model has R² < 0.5; "model-
    specific hard" if at least one model exceeds 0.9 while another is below 0.
    """
    names = sorted(models.keys())
    if not names:
        return pd.DataFrame()
    cols = models[names[0]].y_cols
    rec: dict[str, dict[str, float]] = {c: {} for c in cols}
    for m in names:
        mo = models[m]
        for i, c in enumerate(mo.y_cols):
            yt = mo.Y_true[:, i]; yp = mo.Y_pred[:, i]
            if yt.std() < 1e-12:
                rec[c][m] = float("nan")
            else:
                rec[c][m] = float(r2_score(yt, yp))
    rows = []
    for c, scores in rec.items():
        vals = [v for v in scores.values() if np.isfinite(v)]
        if not vals:
            continue
        rmin, rmax = float(min(vals)), float(max(vals))
        all_bad = rmax < 0.5
        spread = rmax - rmin
        cat, tech, region = parse_output_name(c)
        rows.append({
            "output": c,
            "category": cat,
            "tech": tech,
            "region": region or "",
            "r2_min": rmin,
            "r2_max": rmax,
            "r2_spread": spread,
            "intrinsic_hard": bool(all_bad),
            "model_specific_hard": bool(rmax > 0.9 and rmin < 0.0),
            **scores,
        })
    return pd.DataFrame(rows).sort_values(["intrinsic_hard", "r2_max"],
                                          ascending=[False, True]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Section 7: bootstrap robustness of ranking
# ---------------------------------------------------------------------------

def _bootstrap_ranking(
    models: dict[str, ModelOOF], cfg: EvalConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bootstrap the 486 OOF rows and recompute mean / median R² per model.

    Returns (per-model CI table, pairwise P(A_mean_r2 > B_mean_r2) matrix).
    """
    names = sorted(models.keys())
    if not names:
        return pd.DataFrame(), pd.DataFrame()
    n_samples = models[names[0]].Y_true.shape[0]
    idx = _bootstrap_indices(n_samples, cfg.bootstrap_n, cfg.bootstrap_seed)

    # Vectorised across outputs: for each bootstrap, slice all outputs at once
    # and compute SS_res / SS_tot column-wise. This is ~100x faster than the
    # per-output Python loop on the 486 × 86 panel.
    #
    # Note on robustness: when a resampled column happens to have a tiny
    # within-bootstrap variance (rare resamples of a low-variability output),
    # R² can swing wildly negative. We clip per-output R² to [-1, ∞) before
    # taking the cross-output mean so that one pathological column does not
    # dominate the aggregate. This is a standard "bound the worst case at
    # mean-prediction performance" convention.
    boot_mean = {m: np.empty(cfg.bootstrap_n) for m in names}
    boot_med = {m: np.empty(cfg.bootstrap_n) for m in names}
    eps = 1e-12
    r2_floor = -1.0
    for m in names:
        mo = models[m]
        Yt, Yp = mo.Y_true, mo.Y_pred
        # Per-output validity mask: skip constants in the full data.
        col_valid = Yt.std(axis=0) > eps
        for b in range(cfg.bootstrap_n):
            sel = idx[b]
            Yt_b = Yt[sel, :]
            Yp_b = Yp[sel, :]
            ss_res = np.sum((Yt_b - Yp_b) ** 2, axis=0)
            mean_b = Yt_b.mean(axis=0)
            ss_tot = np.sum((Yt_b - mean_b) ** 2, axis=0)
            with np.errstate(divide="ignore", invalid="ignore"):
                r2 = np.where(ss_tot > 0, 1.0 - ss_res / ss_tot, np.nan)
            r2 = np.where(col_valid, r2, np.nan)
            r2 = np.maximum(r2, r2_floor)   # winsorise pathological tails
            boot_mean[m][b] = float(np.nanmean(r2))
            boot_med[m][b] = float(np.nanmedian(r2))

    per_model = pd.DataFrame({
        "model": names,
        "r2_mean_point": [float(np.mean(
            [r2_score(models[m].Y_true[:, j], models[m].Y_pred[:, j])
             for j in range(models[m].Y_true.shape[1])
             if models[m].Y_true[:, j].std() > eps]
        )) for m in names],
        "r2_mean_boot_mean": [float(np.mean(boot_mean[m])) for m in names],
        "r2_mean_ci_lo": [float(np.percentile(boot_mean[m], 2.5)) for m in names],
        "r2_mean_ci_hi": [float(np.percentile(boot_mean[m], 97.5)) for m in names],
        "r2_median_boot_mean": [float(np.mean(boot_med[m])) for m in names],
        "r2_median_ci_lo": [float(np.percentile(boot_med[m], 2.5)) for m in names],
        "r2_median_ci_hi": [float(np.percentile(boot_med[m], 97.5)) for m in names],
    }).sort_values("r2_mean_boot_mean", ascending=False).reset_index(drop=True)

    # Pairwise P(A_mean_r2 > B_mean_r2) over the bootstrap.
    pw = np.zeros((len(names), len(names)))
    for i, a in enumerate(names):
        for j, b in enumerate(names):
            if i == j:
                pw[i, j] = float("nan")
            else:
                pw[i, j] = float((boot_mean[a] > boot_mean[b]).mean())
    pwise = pd.DataFrame(pw, index=names, columns=names)
    pwise.index.name = "P(row > col, by mean R²)"
    return per_model, pwise


# ---------------------------------------------------------------------------
# Section 8: clipping consistency
# ---------------------------------------------------------------------------

def _clipping_delta_table(
    Y_true: np.ndarray, Y_pred_raw: np.ndarray, Y_pred_clipped: np.ndarray,
    y_cols: list[str],
) -> pd.DataFrame:
    """Per-output R² / RMSE before vs after clipping."""
    rows = []
    for i, c in enumerate(y_cols):
        yt = Y_true[:, i]
        if yt.std() < 1e-12:
            r2_raw, r2_clip = float("nan"), float("nan")
        else:
            r2_raw = float(r2_score(yt, Y_pred_raw[:, i]))
            r2_clip = float(r2_score(yt, Y_pred_clipped[:, i]))
        rows.append({
            "output": c,
            "r2_unclipped": r2_raw,
            "r2_clipped": r2_clip,
            "delta_r2": (r2_clip - r2_raw) if np.isfinite(r2_raw) else float("nan"),
            "rmse_unclipped": float(np.sqrt(mean_squared_error(yt, Y_pred_raw[:, i]))),
            "rmse_clipped": float(np.sqrt(mean_squared_error(yt, Y_pred_clipped[:, i]))),
        })
    df = pd.DataFrame(rows)
    df = df.sort_values("delta_r2", ascending=False, key=lambda s: s.abs(), na_position="last")
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Section 8b (optional): structured CV — leave-one-level-out
# ---------------------------------------------------------------------------

def _structured_cv_for_model(
    model_name: str, X: np.ndarray, Y: np.ndarray, x_cols: list[str],
    random_state: int = 42,
) -> pd.DataFrame:
    """Hold out an entire level of one dimension and measure R².

    Imports the training pipeline lazily so this stays optional. Skipped
    when the user doesn't pass ``--structured_cv``.
    """
    from surrogate_ml_models import Config, get_model  # local import
    from sklearn.preprocessing import StandardScaler

    cfg = Config()
    cfg.random_state = random_state
    rows = []
    for j, col in enumerate(x_cols):
        levels = sorted(np.unique(X[:, j]).astype(int).tolist())
        for lvl in levels:
            test_mask = X[:, j] == lvl
            train_mask = ~test_mask
            X_train, X_test = X[train_mask], X[test_mask]
            Y_train, Y_test = Y[train_mask], Y[test_mask]
            scaler_x = StandardScaler().fit(X_train)
            X_train_s = scaler_x.transform(X_train)
            X_test_s = scaler_x.transform(X_test)
            model, _ = get_model(model_name, Y.shape[1], cfg)
            try:
                if model_name in ("nn", "ngboost"):
                    sy = StandardScaler().fit(Y_train)
                    model.fit(X_train_s, sy.transform(Y_train))
                    Y_pred = sy.inverse_transform(model.predict(X_test_s))
                else:
                    model.fit(X_train_s, Y_train)
                    Y_pred = model.predict(X_test_s)
            except Exception as exc:  # noqa: BLE001
                rows.append({"x_dim": col, "held_out_level": int(lvl),
                             "r2_mean_held_out": float("nan"),
                             "error": str(exc)})
                continue
            r2_list = []
            for k in range(Y.shape[1]):
                yt = Y_test[:, k]
                if yt.std() < 1e-12:
                    continue
                r2_list.append(r2_score(yt, Y_pred[:, k]))
            rows.append({
                "x_dim": col,
                "held_out_level": int(lvl),
                "n_test": int(test_mask.sum()),
                "r2_mean_held_out": float(np.nanmean(r2_list)) if r2_list else float("nan"),
                "r2_median_held_out": float(np.nanmedian(r2_list)) if r2_list else float("nan"),
                "n_outputs_evaluated": len(r2_list),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Extrapolation aggregator (P1)
# ---------------------------------------------------------------------------

def _extrapolation_summary(
    cfg: EvalConfig,
    models: dict[str, "ModelOOF"],
    per_output_by_model: dict[str, pd.DataFrame],
) -> Optional[pd.DataFrame]:
    """Aggregate per-model ``structured_cv_<m>.csv`` into one cross-method
    table + a grouped bar figure (``figs/extrapolation_drop.png``).

    Returns the summary DataFrame (one row per model) with columns
    ``model``, ``oof_r2_mean``, ``oof_r2_median``, ``lolo_r2_mean``,
    ``lolo_r2_median``, ``hardest_dim``, ``hardest_dim_drop``,
    ``n_dims_evaluated``. Returns ``None`` if no LOLO CSVs are present.
    """
    rows = []
    per_dim_rows = []
    for name in sorted(models.keys()):
        path = cfg.eval_dir / f"structured_cv_{name}.csv"
        if not path.exists():
            continue
        try:
            lolo = pd.read_csv(path)
        except Exception as exc:  # noqa: BLE001
            warnings.warn(f"could not read {path}: {exc}")
            continue
        if lolo.empty or "r2_mean_held_out" not in lolo.columns:
            continue

        # Per-dim means: average held-out R² across the levels of each dim.
        dim_means = (
            lolo.dropna(subset=["r2_mean_held_out"])
                .groupby("x_dim", as_index=False)
                .agg(lolo_r2_mean=("r2_mean_held_out", "mean"),
                     lolo_r2_median=("r2_median_held_out", "mean"),
                     n_levels=("held_out_level", "nunique"))
        )
        if dim_means.empty:
            continue

        # OOF (interpolation) baseline from this layer's per-output CSV.
        per_out = per_output_by_model.get(name)
        if per_out is not None and "r2" in per_out.columns:
            mask = ~per_out.get("mostly_zero", False)
            non_const = per_out[mask] if mask.any() else per_out
            oof_mean = float(non_const["r2"].mean(skipna=True))
            oof_median = float(non_const["r2"].median(skipna=True))
        else:
            oof_mean = float("nan")
            oof_median = float("nan")

        # Hardest dimension = largest drop OOF -> LOLO mean.
        dim_means["r2_drop"] = oof_mean - dim_means["lolo_r2_mean"]
        idx = int(dim_means["r2_drop"].idxmax()) if dim_means["r2_drop"].notna().any() else None
        if idx is not None:
            hardest_dim = str(dim_means.loc[idx, "x_dim"])
            hardest_drop = float(dim_means.loc[idx, "r2_drop"])
        else:
            hardest_dim, hardest_drop = "", float("nan")

        rows.append({
            "model": name,
            "oof_r2_mean": oof_mean,
            "oof_r2_median": oof_median,
            "lolo_r2_mean": float(dim_means["lolo_r2_mean"].mean()),
            "lolo_r2_median": float(dim_means["lolo_r2_median"].mean()),
            "hardest_dim": hardest_dim,
            "hardest_dim_drop": hardest_drop,
            "n_dims_evaluated": int(len(dim_means)),
        })

        for _, dr in dim_means.iterrows():
            per_dim_rows.append({
                "model": name,
                "x_dim": dr["x_dim"],
                "lolo_r2_mean": float(dr["lolo_r2_mean"]),
                "lolo_r2_median": float(dr["lolo_r2_median"]),
                "n_levels": int(dr["n_levels"]),
                "oof_r2_mean": oof_mean,
                "r2_drop": float(oof_mean - dr["lolo_r2_mean"]),
            })

    if not rows:
        return None
    summary = pd.DataFrame(rows).sort_values("oof_r2_mean", ascending=False)
    summary.to_csv(
        cfg.eval_dir / "extrapolation_vs_interpolation.csv", index=False,
    )
    if per_dim_rows:
        pd.DataFrame(per_dim_rows).to_csv(
            cfg.eval_dir / "extrapolation_by_dim.csv", index=False,
        )

    # Grouped-bar figure: OOF (interpolation) vs LOLO (extrapolation).
    try:
        fig, ax = plt.subplots(
            figsize=(max(6.0, 1.0 * len(summary) + 2), 4.2),
            layout="constrained",
        )
        x = np.arange(len(summary))
        width = 0.36
        ax.bar(x - width / 2, summary["oof_r2_mean"], width,
               label="Interpolation (OOF)", color="#1f77b4")
        ax.bar(x + width / 2, summary["lolo_r2_mean"], width,
               label="Extrapolation (LOLO mean across dims)", color="#d97706")
        ax.set_xticks(x)
        ax.set_xticklabels(summary["model"], rotation=30, ha="right")
        ax.set_ylabel("Mean R² across non-constant outputs")
        ax.axhline(0.0, color="grey", lw=0.6)
        ax.set_title(
            "§8b Interpolation vs extrapolation R²  "
            "(higher = better; gap = extrapolation cost)"
        )
        ax.legend(loc="lower left", fontsize=9, frameon=False)
        ax.grid(axis="y", alpha=0.25)
        out = cfg.figs_dir / "extrapolation_drop.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=140)
        plt.close(fig)
    except Exception as exc:  # noqa: BLE001
        warnings.warn(f"extrapolation_drop figure failed: {exc}")

    return summary


# ---------------------------------------------------------------------------
# By-catalog distributional fidelity summary (P3b)
# ---------------------------------------------------------------------------

def _per_catalog_distribution_summary(
    cfg: EvalConfig,
    per_output_by_model: dict[str, pd.DataFrame],
    first_model_name: str,
) -> Optional[pd.DataFrame]:
    """Summarise std_ratio + Spearman per output catalog for the headline
    model (first_model_name). Writes a CSV + small grouped-bar figure.
    """
    df = per_output_by_model.get(first_model_name)
    if df is None or df.empty:
        return None
    needed = {"category", "std_ratio", "spearman"}
    if not needed.issubset(df.columns):
        return None

    work = df.copy()
    if "mostly_zero" in work.columns:
        work = work[~work["mostly_zero"].fillna(False)]
    if work.empty:
        return None

    # Order catalogs canonically; keep "misc" last.
    cat_order = list(KNOWN_CATEGORIES) + ["misc"]
    work["category"] = work["category"].fillna("misc")
    work = work[work["category"].isin(cat_order)]
    summary = (
        work.groupby("category", as_index=False)
            .agg(median_std_ratio=("std_ratio", "median"),
                 median_spearman=("spearman", "median"),
                 n_outputs=("std_ratio", "size"))
    )
    summary["category"] = pd.Categorical(
        summary["category"], categories=cat_order, ordered=True,
    )
    summary = summary.sort_values("category").reset_index(drop=True)
    summary["model"] = first_model_name
    summary.to_csv(
        cfg.eval_dir / "distribution_fidelity_by_catalog.csv", index=False,
    )

    try:
        fig, ax = plt.subplots(figsize=(7.0, 4.0), layout="constrained")
        x = np.arange(len(summary))
        width = 0.36
        ax.bar(x - width / 2, summary["median_std_ratio"], width,
               label="Median std(pred)/std(actual)", color="#1f77b4")
        ax.bar(x + width / 2, summary["median_spearman"], width,
               label="Median Spearman", color="#2ca02c")
        ax.axhline(1.0, color="grey", linestyle="--", linewidth=0.7,
                   label="ideal = 1.0")
        ax.set_xticks(x)
        ax.set_xticklabels(
            [str(c) for c in summary["category"]], rotation=0,
        )
        ax.set_ylabel("Median value")
        ax.set_ylim(0.0, max(1.05, float(summary[
            ["median_std_ratio", "median_spearman"]
        ].max().max() * 1.05)))
        ax.set_title(
            f"§5 Distributional fidelity by catalog ({first_model_name})"
        )
        ax.legend(loc="lower left", fontsize=9, frameon=False)
        ax.grid(axis="y", alpha=0.25)
        out = cfg.figs_dir / "distribution_fidelity_by_catalog.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=140)
        plt.close(fig)
    except Exception as exc:  # noqa: BLE001
        warnings.warn(f"distribution_fidelity_by_catalog figure failed: {exc}")

    return summary


# ---------------------------------------------------------------------------
# Cross-model assembly
# ---------------------------------------------------------------------------

def _model_x_category_heatmap(
    models: dict[str, ModelOOF], group_dfs: dict[str, pd.DataFrame],
    out_path: Path, dim: str,
) -> Optional[pd.DataFrame]:
    """Pivot model × group (category or tech) heatmap of median R²."""
    rows = []
    for name, df in group_dfs.items():
        if df is None or df.empty or dim not in df.columns:
            continue
        for _, r in df.iterrows():
            rows.append({"model": name, dim: r[dim], "r2_median": r["r2_median"]})
    if not rows:
        return None
    long = pd.DataFrame(rows)
    pivot = long.pivot(index="model", columns=dim, values="r2_median")
    # Order columns by global median to keep similar techs together.
    col_order = pivot.median(axis=0).sort_values(ascending=False).index
    pivot = pivot[col_order]
    pivot = pivot.reindex(index=sorted(pivot.index))

    fig, ax = plt.subplots(figsize=(max(6, 0.45 * pivot.shape[1] + 3), 0.4 * pivot.shape[0] + 2))
    im = ax.imshow(pivot.to_numpy(dtype=float), aspect="auto",
                   cmap="RdYlGn", vmin=-0.2, vmax=1.0)
    ax.set_xticks(range(pivot.shape[1]))
    ax.set_xticklabels(pivot.columns, rotation=60, ha="right", fontsize=8)
    ax.set_yticks(range(pivot.shape[0]))
    ax.set_yticklabels(pivot.index, fontsize=9)
    ax.set_title(f"Median R² — model × {dim}")
    fig.colorbar(im, ax=ax, shrink=0.7, label="R² median")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return pivot


def _plot_pred_vs_actual_std(
    models: dict[str, ModelOOF], out_path: Path,
) -> pd.DataFrame:
    """Compression-to-mean diagnostic: per-output std(pred) vs std(actual)."""
    fig, axes = plt.subplots(1, len(models), figsize=(3.6 * len(models), 4),
                             squeeze=False)
    rows = []
    for ax, (name, mo) in zip(axes[0], sorted(models.items())):
        std_t = mo.Y_true.std(axis=0)
        std_p = mo.Y_pred.std(axis=0)
        keep = std_t > 1e-12
        ax.scatter(std_t[keep], std_p[keep], s=8, alpha=0.5, color="steelblue",
                   edgecolor="none")
        mx = max(float(std_t[keep].max()), float(std_p[keep].max())) if keep.any() else 1.0
        ax.plot([0, mx], [0, mx], color="red", linewidth=0.8, linestyle="--",
                alpha=0.6)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("std(actual)")
        ax.set_ylabel("std(predicted)")
        ax.set_title(name)
        for i in range(len(mo.y_cols)):
            if not keep[i]:
                continue
            rows.append({"model": name, "output": mo.y_cols[i],
                         "std_actual": float(std_t[i]),
                         "std_predicted": float(std_p[i]),
                         "std_ratio": float(std_p[i] / std_t[i])})
    fig.suptitle("Predicted vs actual std per output  (log–log)", fontsize=11)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------

def _md_table(df: pd.DataFrame, max_rows: int = 12, float_fmt: str = "{:.4f}") -> str:
    if df is None or df.empty:
        return "_(empty)_\n"
    sub = df.head(max_rows).copy()
    for c in sub.select_dtypes(include=[float]).columns:
        sub[c] = sub[c].map(lambda v: float_fmt.format(v) if pd.notna(v) else "")
    return sub.to_markdown(index=False) + "\n"


def _render_report(
    cfg: EvalConfig, ctx: dict,
) -> tuple[str, str]:
    """Build the markdown report and a minimal self-contained HTML wrapper."""
    md: list[str] = []
    md.append(f"# ReEDS-Proxy evaluation report — *{cfg.layer}* layer\n")
    md.append(
        "Generated by `surrogate_eval.py` from existing artifacts in "
        f"`{Path(cfg.output_dir).as_posix()}/models/`. No retraining was "
        "performed (predictions reconstructed via "
        "`Y_pred = Y_true − oof_residuals`). Mostly-zero outputs "
        f"(frac_nonzero < {cfg.mostly_zero_threshold:.0%}) are flagged but "
        "excluded from headline R² aggregates.\n"
    )
    # Plain-language intro (shared with the bokeh dashboard).
    md.append("\n" + md_intro() + "\n")

    md.append("## 0. What ranking is best?\n")
    md.append(md_explainer("r0_ranking"))
    # Optional auto-readout (current run only — clearly labelled).
    _auto = auto_readout_r0(ctx.get("bootstrap_per_model"))
    if _auto:
        md.append(f"\n{_auto}\n")
    md.append(_md_table(ctx["bootstrap_per_model"]))
    md.append(
        "Each row is a model's mean / median R² across the OOF rows with a "
        f"95% bootstrap CI ({cfg.bootstrap_n} resamples). A pairwise "
        "`P(row > col)` matrix is in `model_ranking_bootstrap_pwise.csv`.\n"
    )

    md.append("\n## 1. Output taxonomy + grouped metrics\n")
    md.append(md_explainer("r1_grouped"))
    md.append(
        "Per-output metrics live in `per_output_metrics_<model>.csv` and "
        "are grouped into `grouped_by_category_<model>.csv` / "
        "`grouped_by_tech_<model>.csv` (+ `_by_region` for the regional layer).\n"
    )
    if "by_category_first" in ctx:
        md.append("### By category (first model only — see per-model CSVs for the rest)\n")
        md.append(_md_table(ctx["by_category_first"]))
    if "mostly_zero_summary" in ctx:
        md.append(f"\n**Mostly-zero outputs flagged:** {ctx['mostly_zero_summary']}.\n")

    md.append("\n## 2. Bias diagnostics\n")
    md.append(md_explainer("r2_bias_diagnostics"))
    md.append(
        "Three views per model under `figs/`:\n"
        "* `bias_residvspred_<m>.png` — heteroscedasticity per category.\n"
        "* `bias_byDesign_<m>.png` — boxplots of normalised residual vs each X dimension *(this is the factorial-DoE workhorse: it reveals systematic failure at specific corners — e.g. always under-predicting capacity at Hi demand)*.\n"
        "* `bias_qq_<m>.png` — Q-Q of standardised residuals vs Normal, per category.\n"
        "Numbers backing the boxplots are in `bias_by_design_<m>.csv`.\n"
    )
    md.append("\n### About the bias-by-design figure\n")
    md.append(md_explainer("bias_design"))

    md.append("\n## 3. Interval calibration\n")
    md.append(md_explainer("r3_calibration"))
    md.append(
        f"Split-conformal coverage sweep at alphas = {list(cfg.alpha_levels)}, "
        "see `calibration_<m>.csv` and `figs/calibration_overlay.png`. "
        "Coverage is also broken down by category (and by region in the "
        "regional layer). Sharpness is reported as `2·half_width / range` per "
        "output so it's unit-free.\n"
    )
    if "calibration_summary" in ctx:
        md.append(_md_table(ctx["calibration_summary"]))
    if "ngboost_native" in ctx and ctx["ngboost_native"] is not None:
        md.append("\n### NGBoost native vs conformal\n")
        md.append(
            "**Caveat:** native coverage is *in-sample* (NGBRegressor evaluated "
            "on its own training X), so it's optimistic. It still lets us "
            "compare *sharpness*.\n"
        )
        md.append(_md_table(ctx["ngboost_native"]))

    md.append("\n## 4. Regional vs overall\n")
    md.append(md_explainer("r4_regional_vs_overall"))
    md.append(
        "This run reports the **" + cfg.layer + "** layer. Generate both "
        "layers and diff the bootstrap CIs to quantify the resolution "
        "penalty. The bokeh dashboard already overlays both layers in "
        "section §5; the per-region heatmap (regional layer only) is "
        "`figs/heatmap_<m>_region.png` and `grouped_by_region_<m>.csv`.\n"
    )

    md.append("\n## 5. Distributional fidelity + decision metrics\n")
    md.append(md_explainer("r5_distributional"))
    md.append(
        "* `distribution_fidelity_<m>.csv` (Spearman, KS, std_ratio per output).\n"
        "* `build_classification_<m>.csv` — for every `cap_*` output, "
        "does the surrogate get *whether* a tech is deployed right? "
        f"Threshold |y| > {cfg.mostly_zero_eps:.1e}.\n"
        "* `headline_scalars_<m>.csv` — `cost_total`, `total_cap`, "
        "`total_gen`, `total_tran` with point + conformal interval at α=0.1.\n"
        "* `figs/pred_vs_actual_std.png` is the compression-to-mean check.\n"
    )
    md.append("\n### Headline scalars (plain-language read)\n")
    md.append(md_explainer("r5_headline"))
    if "headline_first" in ctx:
        # Optional auto-readout (current run only — clearly labelled).
        for _line in auto_readout_r5(ctx["headline_first"]):
            md.append(f"\n{_line}")
        md.append("\n### Headline scalars (first model)\n")
        md.append(_md_table(ctx["headline_first"]))

    md.append("\n## 6. Worst-case attribution\n")
    md.append(md_explainer("r6_worst_cases"))
    md.append(
        "`per_case_error_ranking.csv` lists all 486 cases by aggregate "
        "normalised |residual|. `per_output_difficulty.csv` cross-tabs every "
        "output's min/max R² across models — flagging `intrinsic_hard` "
        "(all models < 0.5) vs `model_specific_hard` (best > 0.9 with worst < 0).\n"
    )
    md.append("\n### Per-output difficulty (plain-language read)\n")
    md.append(md_explainer("r6_difficulty"))
    if "worst_cases" in ctx:
        md.append("### Top-10 hardest cases (first model)\n")
        md.append(_md_table(ctx["worst_cases"], max_rows=10))

    md.append("\n## 7. Ranking robustness (bootstrap)\n")
    md.append(md_explainer("r7_robustness"))
    md.append(_md_table(ctx["bootstrap_per_model"]))
    md.append("Pairwise `P(row > col)` is in `model_ranking_bootstrap_pwise.csv`.\n")

    md.append("\n## 8. Correctness fixes\n")
    md.append(md_explainer("r8_correctness"))
    md.append(
        "**8a. Clipping consistency.** Deployed predictions go through "
        "`clip_physical_bounds` in `surrogate_predict.py`; OOF predictions "
        "used by the existing eval pipeline are *unclipped*. We report both. "
        "`clipping_delta_<m>.csv` lists the per-output R² delta. Conformal "
        "half-widths derived from unclipped residuals can be very slightly "
        "miscalibrated near zero (the band's lower edge is below physical "
        "zero for non-storage `gen`, `cap`, `tran`, non-incentive `cost`).\n\n"
        "**8b. CV is interpolation, not extrapolation.** The OOF folds in "
        "`surrogate_ml_models.py` shuffle the full factorial, so the metric "
        "we report is *within-grid* interpolation accuracy. Outside the 486-"
        "case grid we have no guarantee. If you passed `--structured_cv` we "
        "also wrote `structured_cv_<m>.csv`: hold out one level of one X "
        "dimension at a time and measure held-out R² — this is the "
        "extrapolation diagnostic.\n"
    )
    md.append("\n### Clipping consistency (plain-language read)\n")
    md.append(md_explainer("r8_clipping"))

    # --- 8c: Extrapolation summary table (only if available) ---
    extrap_df = ctx.get("extrapolation_summary")
    if extrap_df is not None and len(extrap_df):
        md.append("\n### 8c. Extrapolation diagnostic (LOLO)\n")
        md.append(
            "Per-model summary (`extrapolation_vs_interpolation.csv`). "
            "`oof_r2_mean` is in-grid; `lolo_r2_mean` averages "
            "leave-one-level-out R² across design dimensions; "
            "`hardest_dim` is the dimension with the largest drop.\n"
        )
        md.append(_md_table(extrap_df.round(3)))
        readout = auto_readout_extrapolation(extrap_df)
        if readout:
            md.append(readout + "\n")

    # --- 5b: By-catalog distributional fidelity (only if available) ---
    distfid_df = ctx.get("distfid_by_catalog")
    if distfid_df is not None and len(distfid_df):
        md.append("\n### 5b. Distributional fidelity by catalog\n")
        md.append(md_explainer("s5_distfidelity"))
        md.append(_md_table(distfid_df.round(3)))

    # --- 9: Limitations & validity (paper-readiness) ---
    md.append("\n## 9. Limitations & validity\n")
    md.append(md_explainer("limitations"))
    md.append(
        "**One-line summary.** This surrogate is *validated* for "
        "interpolation inside the 486-case grid (§R0 mean / median R² with "
        "bootstrap CIs). It is *tested* for extrapolation via LOLO (§8c when "
        "present) and that score should be cited as a worst-case bound for "
        "predictions at unseen levels. Pooled R² in §1 is shown for context "
        "only; it is dominated by the largest-magnitude outputs and is "
        "**not** the metric to quote in the paper.\n"
    )
    md_text = "\n".join(md)

    html = f"""<!doctype html>
<html><head><meta charset=\"utf-8\">
<title>ReEDS-Proxy evaluation — {cfg.layer}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 1100px; margin: 2em auto; padding: 0 1em; color: #222; }}
h1, h2, h3 {{ color: #1f4e79; }}
code, pre {{ background: #f5f7fa; padding: 0.1em 0.3em; border-radius: 3px; }}
table {{ border-collapse: collapse; margin: 1em 0; }}
th, td {{ border: 1px solid #ddd; padding: 4px 8px; font-size: 12px; }}
th {{ background: #f0f4f8; }}
img {{ max-width: 100%; border: 1px solid #ddd; padding: 4px; background: white; }}
.caveat {{ background: #fff8e1; border-left: 3px solid #f0a050; padding: 6px 12px; }}
</style></head><body>
<pre style=\"white-space: pre-wrap; font-family: inherit; font-size: 14px;\">{md_text}</pre>
<h2>Figures</h2>
<ul>
"""
    fig_dir = cfg.figs_dir
    if fig_dir.exists():
        for p in sorted(fig_dir.glob("*.png")):
            rel = p.relative_to(cfg.eval_dir).as_posix()
            html += f"<li><b>{p.stem}</b><br><img src=\"{rel}\"></li>\n"
    html += "</ul></body></html>\n"
    return md_text, html


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def run_eval(cfg: EvalConfig) -> dict:
    """Run every evaluation section and write artefacts to ``cfg.eval_dir``.

    Returns a small dict of in-memory results in case callers want to
    inspect them (e.g. for the bokeh tab).
    """
    cfg.eval_dir.mkdir(parents=True, exist_ok=True)
    cfg.figs_dir.mkdir(parents=True, exist_ok=True)

    print(f"[eval] layer={cfg.layer}  output_dir={cfg.output_dir}")
    print(f"[eval] loading artifacts + reconstructing OOF...", flush=True)
    models, X, x_cols, case_names = load_all_oof(cfg)
    print(f"[eval]   loaded {len(models)} models: {sorted(models.keys())}", flush=True)

    # --- Section 1: per-output panel + grouped tables ---
    per_output_by_model: dict[str, pd.DataFrame] = {}
    group_cat: dict[str, pd.DataFrame] = {}
    group_tech: dict[str, pd.DataFrame] = {}
    group_region: dict[str, pd.DataFrame] = {}
    mostly_zero_count = 0
    n_outputs_total = 0
    first_model_name = sorted(models.keys())[0]

    print(f"[eval] (1/8) per-output + grouped metrics...", flush=True)
    for name, mo in models.items():
        df = per_output_metrics(mo.Y_true, mo.Y_pred, mo.y_cols)
        df = _mark_mostly_zero(df, cfg)
        per_output_by_model[name] = df
        df.to_csv(cfg.eval_dir / f"per_output_metrics_{name}.csv", index=False)

        gc = _group_summary(df, "category")
        gc.to_csv(cfg.eval_dir / f"grouped_by_category_{name}.csv", index=False)
        gt = _group_summary(df, "tech")
        gt.to_csv(cfg.eval_dir / f"grouped_by_tech_{name}.csv", index=False)
        gr = _group_summary(df[df["region"] != ""], "region") if (df["region"] != "").any() else pd.DataFrame()
        if not gr.empty:
            gr.to_csv(cfg.eval_dir / f"grouped_by_region_{name}.csv", index=False)
        group_cat[name] = gc
        group_tech[name] = gt
        group_region[name] = gr
        if name == first_model_name:
            mostly_zero_count = int(df["mostly_zero"].sum())
            n_outputs_total = len(df)

    # --- Section 2: bias diagnostics ---
    print(f"[eval] (2/8) bias diagnostics...", flush=True)
    bias_design_dfs = []
    for name, mo in models.items():
        _plot_residual_vs_predicted(
            mo.Y_true, mo.Y_pred, mo.y_cols, name,
            cfg.figs_dir / f"bias_residvspred_{name}.png",
        )
        bd = _plot_residual_by_design(
            X, x_cols, mo.Y_true, mo.Y_pred, mo.y_cols, name,
            cfg.figs_dir / f"bias_byDesign_{name}.png",
        )
        bd["model"] = name
        bias_design_dfs.append(bd)
        bd.to_csv(cfg.eval_dir / f"bias_by_design_{name}.csv", index=False)
        _plot_qq_by_category(
            mo.Y_true, mo.Y_pred, mo.y_cols, name,
            cfg.figs_dir / f"bias_qq_{name}.png",
        )

    # --- Section 3: calibration sweep ---
    print(f"[eval] (3/8) calibration sweep...", flush=True)
    calib_rows = []
    for name, mo in models.items():
        df = _coverage_table(mo.artifact, per_output_by_model[name], cfg.alpha_levels)
        df["model"] = name
        df.to_csv(cfg.eval_dir / f"calibration_{name}.csv", index=False)
        calib_rows.append(df)
    calib_all = pd.concat(calib_rows, ignore_index=True) if calib_rows else pd.DataFrame()
    if not calib_all.empty:
        calib_all.to_csv(cfg.eval_dir / "calibration_all_models.csv", index=False)
        _plot_calibration(calib_all, cfg.figs_dir / "calibration_overlay.png",
                          sorted(models.keys()))

    # Optional NGBoost native
    ngb_native_df = None
    if cfg.ngboost_native and "ngboost" in models:
        print(f"[eval] (3b/8) NGBoost native calibration (in-sample)...", flush=True)
        try:
            ngb_native_df = _ngboost_native_calibration(
                models["ngboost"].artifact, X, models["ngboost"].Y_true,
                cfg.alpha_levels,
            )
            if ngb_native_df is not None:
                ngb_native_df.to_csv(cfg.eval_dir / "calibration_ngboost_native.csv",
                                     index=False)
        except Exception as exc:  # noqa: BLE001
            warnings.warn(f"NGBoost native calibration failed: {exc}")

    # --- Section 5: distributional / decision ---
    print(f"[eval] (5/8) distributional + decision metrics...", flush=True)
    for name, mo in models.items():
        # The fidelity columns are already in per_output_metrics — extract.
        df = per_output_by_model[name][
            ["output", "category", "tech", "region", "frac_nonzero",
             "spearman", "ks_stat", "ks_p", "std_ratio"]
        ]
        df.to_csv(cfg.eval_dir / f"distribution_fidelity_{name}.csv", index=False)
        cls = _build_classification(mo.Y_true, mo.Y_pred, mo.y_cols,
                                    cfg.mostly_zero_eps)
        cls.to_csv(cfg.eval_dir / f"build_classification_{name}.csv", index=False)
        head = _headline_scalars(mo.Y_true, mo.Y_pred, mo.y_cols,
                                 mo.artifact, alpha=0.1)
        head.to_csv(cfg.eval_dir / f"headline_scalars_{name}.csv", index=False)

    std_df = _plot_pred_vs_actual_std(models, cfg.figs_dir / "pred_vs_actual_std.png")
    std_df.to_csv(cfg.eval_dir / "pred_vs_actual_std.csv", index=False)

    # --- Section 6: worst case / output difficulty ---
    print(f"[eval] (6/8) worst-case + output difficulty...", flush=True)
    worst_first = _per_case_error_ranking(
        models[first_model_name].Y_true, models[first_model_name].Y_pred,
        models[first_model_name].y_cols, X, x_cols, case_names,
        per_output_by_model[first_model_name],
    )
    worst_first["reference_model"] = first_model_name
    worst_first.to_csv(cfg.eval_dir / "per_case_error_ranking.csv", index=False)
    difficulty = _output_difficulty_table(models, cfg)
    difficulty.to_csv(cfg.eval_dir / "per_output_difficulty.csv", index=False)

    # --- Section 7: bootstrap ranking ---
    print(f"[eval] (7/8) bootstrap ranking (n={cfg.bootstrap_n})...", flush=True)
    boot_per_model, boot_pwise = _bootstrap_ranking(models, cfg)
    boot_per_model.to_csv(cfg.eval_dir / "model_ranking_bootstrap.csv", index=False)
    boot_pwise.to_csv(cfg.eval_dir / "model_ranking_bootstrap_pwise.csv")

    # --- Section 8: clipping ---
    print(f"[eval] (8/8) clipping consistency...", flush=True)
    clipping_summaries = []
    if cfg.include_clipped:
        for name, mo in models.items():
            try:
                Y_clip = apply_physical_clipping(mo.Y_pred, mo.y_cols)
            except Exception as exc:  # noqa: BLE001
                warnings.warn(f"Clipping failed for {name}: {exc}")
                continue
            cd = _clipping_delta_table(mo.Y_true, mo.Y_pred, Y_clip, mo.y_cols)
            cd["model"] = name
            cd.to_csv(cfg.eval_dir / f"clipping_delta_{name}.csv", index=False)
            clipping_summaries.append({
                "model": name,
                "n_outputs": int(len(cd)),
                "mean_delta_r2": float(cd["delta_r2"].mean(skipna=True)),
                "n_outputs_clipping_helps": int((cd["delta_r2"] > 0).sum()),
                "n_outputs_clipping_hurts": int((cd["delta_r2"] < 0).sum()),
            })
    if clipping_summaries:
        pd.DataFrame(clipping_summaries).to_csv(
            cfg.eval_dir / "clipping_summary.csv", index=False,
        )

    # --- Optional structured CV ---
    if cfg.structured_cv:
        # Load training data once for structured CV.
        X_full, Y_full, x_cols_full, y_cols_full, _ = _load_training_arrays(cfg)
        for name in sorted(models.keys()):
            print(f"[eval] structured CV for '{name}' (slow)...")
            try:
                # Align Y to the model's columns so we report comparable R².
                Y_aligned = _align_y_to_artifact(Y_full, y_cols_full, models[name].y_cols)
                df = _structured_cv_for_model(name, X_full, Y_aligned, x_cols_full)
                df.to_csv(cfg.eval_dir / f"structured_cv_{name}.csv", index=False)
            except Exception as exc:  # noqa: BLE001
                warnings.warn(f"structured CV failed for {name}: {exc}")

    # --- Always-on aggregators that consume any structured_cv_*.csv files
    #     already on disk from this or a prior run. Cheap, no refit.
    extrap_summary = _extrapolation_summary(cfg, models, per_output_by_model)

    # --- Per-catalog distributional fidelity summary (P3b) ---
    distfid_summary = _per_catalog_distribution_summary(
        cfg, per_output_by_model, first_model_name,
    )

    # --- Cross-model heatmaps ---
    _model_x_category_heatmap(
        models, group_cat, cfg.figs_dir / "heatmap_model_x_category.png",
        "category",
    )
    _model_x_category_heatmap(
        models, group_tech, cfg.figs_dir / "heatmap_model_x_tech.png",
        "tech",
    )
    if any(not gr.empty for gr in group_region.values()):
        _model_x_category_heatmap(
            models, group_region, cfg.figs_dir / "heatmap_model_x_region.png",
            "region",
        )

    # --- Report ---
    ctx = {
        "bootstrap_per_model": boot_per_model,
        "by_category_first": group_cat.get(first_model_name),
        "mostly_zero_summary": (
            f"{mostly_zero_count} of {n_outputs_total} outputs flagged "
            f"(< {cfg.mostly_zero_threshold:.0%} of cases deploy them)"
        ),
        "calibration_summary": (
            calib_all[(calib_all["group"] == "ALL")][
                ["model", "alpha", "nominal_coverage", "coverage_mean",
                 "sharpness_median"]
            ].sort_values(["model", "alpha"])
            if not calib_all.empty else None
        ),
        "ngboost_native": ngb_native_df,
        "headline_first": (
            _headline_scalars(
                models[first_model_name].Y_true, models[first_model_name].Y_pred,
                models[first_model_name].y_cols, models[first_model_name].artifact,
            )
        ),
        "worst_cases": worst_first,
        "extrapolation_summary": extrap_summary,
        "distfid_by_catalog": distfid_summary,
    }
    md_text, html_text = _render_report(cfg, ctx)
    (cfg.eval_dir / "REPORT.md").write_text(md_text, encoding="utf-8")
    (cfg.eval_dir / "REPORT.html").write_text(html_text, encoding="utf-8")

    # Index file for the dashboard tab (so it doesn't have to glob).
    index = {
        "layer": cfg.layer,
        "models": sorted(models.keys()),
        "alpha_levels": list(cfg.alpha_levels),
        "n_outputs": int(n_outputs_total),
        "mostly_zero_count": int(mostly_zero_count),
        "csvs": sorted(p.name for p in cfg.eval_dir.glob("*.csv")),
        "figs": sorted(p.name for p in cfg.figs_dir.glob("*.png")),
        "report_md": "REPORT.md",
        "report_html": "REPORT.html",
    }
    (cfg.eval_dir / "_index.json").write_text(json.dumps(index, indent=2),
                                              encoding="utf-8")
    print(f"[eval] wrote {len(index['csvs'])} CSVs + {len(index['figs'])} PNGs "
          f"to {cfg.eval_dir}")
    return {"index": index, "ctx": ctx}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--output_dir", required=True, type=Path,
                   help="Layer's output_dir (contains models/ + summary.json).")
    p.add_argument("--data", "--data_path", dest="data_path", required=True,
                   type=Path, help="Path to <layer>_ml_numeric.csv.")
    p.add_argument("--layer", default="overall",
                   help="Label written into the report (overall|regional|...).")
    p.add_argument("--alpha", nargs="+", type=float,
                   default=list(EvalConfig.alpha_levels),
                   help="Miscoverage levels for calibration sweep.")
    p.add_argument("--mostly_zero_threshold", type=float, default=0.05)
    p.add_argument("--mostly_zero_eps", type=float, default=1e-3)
    p.add_argument("--bootstrap_n", type=int, default=500)
    p.add_argument("--bootstrap_seed", type=int, default=42)
    p.add_argument("--structured_cv", "--extrapolation", action="store_true",
                   dest="structured_cv",
                   help="Run leave-one-level-out (LOLO) extrapolation "
                        "diagnostic. Refits each model per held-out level; "
                        "slow. --extrapolation is the paper-friendly alias.")
    p.add_argument("--ngboost_native", action="store_true",
                   help="Add NGBoost native-Normal calibration table.")
    p.add_argument("--no_clipped", action="store_true",
                   help="Skip the unclipped-vs-clipped delta table.")
    p.add_argument("--skip_models", nargs="*", default=[],
                   help="Skip these model names.")
    p.add_argument("--n_methods_compare", type=int, default=6,
                   help="Top-N for cross-method panels (§4, §5). "
                        "Default 6. Ranking is the honest §R0 metric.")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_argparser().parse_args(argv)
    cfg = EvalConfig(
        output_dir=Path(args.output_dir),
        data_path=Path(args.data_path),
        layer=args.layer,
        alpha_levels=tuple(args.alpha),
        mostly_zero_threshold=float(args.mostly_zero_threshold),
        mostly_zero_eps=float(args.mostly_zero_eps),
        bootstrap_n=int(args.bootstrap_n),
        bootstrap_seed=int(args.bootstrap_seed),
        structured_cv=bool(args.structured_cv),
        ngboost_native=bool(args.ngboost_native),
        include_clipped=not bool(args.no_clipped),
        skip_models=tuple(args.skip_models),
        n_methods_compare=int(args.n_methods_compare),
    )
    try:
        run_eval(cfg)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
