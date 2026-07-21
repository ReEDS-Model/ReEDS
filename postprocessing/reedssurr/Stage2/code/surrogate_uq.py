"""
Uncertainty quantification for ReEDS surrogate models.

This module provides two complementary UQ methods that both ride on top of
the artifacts produced by ``surrogate_ml_models.py``:

1. **Split-conformal prediction intervals** (works for *any* trained model).
   Reuses the per-output OOF residuals already stored in each artifact under
   the key ``oof_residuals``. For a target miscoverage ``alpha`` we read off
   the empirical ``(1-alpha)``-quantile of |residual| per output and add it
   as a symmetric band around the point prediction. This is calibrated only
   marginally (per-output, ignoring joint coverage) but is fast, distribution
   -free, and finite-sample valid for exchangeable data.

2. **NGBoost native distributional intervals** (only available when the model
   is an NGBoost regressor — i.e. when ``artifact["model_name"] == "ngboost"``).
   NGBoost predicts a Normal distribution per output, so we read off the
   ``alpha/2`` and ``1 - alpha/2`` quantiles of that Normal directly.

Usage
-----
    from surrogate_uq import prediction_interval
    art = load_artifact("../outputs/overall/models/xgb.joblib")
    point, lo, hi = prediction_interval(art, levels, alpha=0.1)
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from surrogate_predict import encode_design, predict


# ---------------------------------------------------------------------------
# Split-conformal
# ---------------------------------------------------------------------------

def conformal_widths(artifact: dict, alpha: float = 0.1) -> np.ndarray:
    """Half-width of the per-output conformal interval at miscoverage ``alpha``.

    Returns a 1-D array of length ``len(artifact["y_cols"])``. Reads the
    pre-computed OOF residuals stored in the artifact under ``oof_residuals``.
    """
    resid = artifact.get("oof_residuals")
    if resid is None:
        # Fall back to zero-width intervals so callers can still operate.
        return np.zeros(len(artifact["y_cols"]), dtype=np.float64)
    resid = np.asarray(resid, dtype=np.float64)
    # |residual| quantile per output (axis 0 = samples).
    return np.quantile(np.abs(resid), 1.0 - alpha, axis=0)


def prediction_interval(
    artifact: dict, levels: dict[str, str], alpha: float = 0.1,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (point, lower, upper) Series for a single design point.

    The interval is symmetric (point ± conformal half-width). For NGBoost
    artifacts you can also use :func:`ngboost_interval` which produces
    asymmetric bands from the predicted Normal distribution.
    """
    point = predict(artifact, levels)
    half = conformal_widths(artifact, alpha=alpha)
    lo = pd.Series(point.values - half, index=point.index, name="lower")
    hi = pd.Series(point.values + half, index=point.index, name="upper")
    return point, lo, hi


# ---------------------------------------------------------------------------
# NGBoost native distributional intervals
# ---------------------------------------------------------------------------

def _ngboost_estimators(model) -> Optional[list]:
    """Return the list of per-output NGBRegressor instances, or None."""
    # MultiOutputRegressor wraps single-output regressors in ``estimators_``.
    estimators = getattr(model, "estimators_", None)
    if estimators is None:
        # Single-output: the model itself is the NGBRegressor.
        if hasattr(model, "pred_dist"):
            return [model]
        return None
    if any(not hasattr(e, "pred_dist") for e in estimators):
        return None
    return list(estimators)


def ngboost_interval(
    artifact: dict, levels: dict[str, str], alpha: float = 0.1,
) -> Optional[tuple[pd.Series, pd.Series, pd.Series]]:
    """Asymmetric (mean ± z·sigma) intervals from the NGBoost predicted Normal.

    Returns None if the artifact wasn't trained with NGBoost.
    """
    estimators = _ngboost_estimators(artifact["model"])
    if estimators is None:
        return None
    x = encode_design(levels, artifact["x_cols"])
    x_s = artifact["scaler_x"].transform(x.reshape(1, -1))
    means = np.empty(len(estimators))
    stds = np.empty(len(estimators))
    for i, est in enumerate(estimators):
        dist = est.pred_dist(x_s)
        # NGBoost Normal: ``loc`` and ``scale`` attributes.
        means[i] = float(np.asarray(dist.loc).ravel()[0])
        stds[i] = float(np.asarray(dist.scale).ravel()[0])
    # Inverse-scale back to original Y units if needed.
    scaler_y = artifact.get("scaler_y")
    if scaler_y is not None:
        # StandardScaler: y_orig = y_s * sigma + mu; sigma_orig = y_sigma * scale_
        y_scale = np.asarray(scaler_y.scale_).ravel()
        y_mean = np.asarray(scaler_y.mean_).ravel()
        means = means * y_scale + y_mean
        stds = stds * y_scale
    # Two-sided alpha → quantile multiplier from the standard Normal.
    from scipy.stats import norm
    z = float(norm.ppf(1.0 - alpha / 2.0))
    y_cols = artifact["y_cols"]
    point = pd.Series(means, index=y_cols, name="prediction")
    lo = pd.Series(means - z * stds, index=y_cols, name="lower")
    hi = pd.Series(means + z * stds, index=y_cols, name="upper")
    return point, lo, hi


# ---------------------------------------------------------------------------
# Empirical coverage check
# ---------------------------------------------------------------------------

def empirical_coverage(artifact: dict, alpha: float = 0.1) -> dict:
    """Sanity-check the marginal coverage of the conformal intervals.

    Uses the stored OOF residuals as the calibration set. For a well-calibrated
    set of intervals we'd expect ~(1 - alpha) of the residuals to land inside
    [-half, +half] per output. Reported as a single fraction averaged over
    outputs.
    """
    resid = artifact.get("oof_residuals")
    if resid is None:
        return {"alpha": alpha, "coverage": float("nan"), "n_outputs": 0}
    resid = np.asarray(resid, dtype=np.float64)
    half = conformal_widths(artifact, alpha=alpha)
    inside = (np.abs(resid) <= half[None, :]).mean(axis=0)
    return {
        "alpha": alpha,
        "coverage_mean": float(inside.mean()),
        "coverage_min": float(inside.min()),
        "coverage_max": float(inside.max()),
        "target": 1.0 - alpha,
        "n_outputs": int(resid.shape[1]),
    }
