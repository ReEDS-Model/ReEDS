"""
Stage 2 domain constraints for the ReEDS surrogate.

Stage 1 treated every Y column as an independent unbounded scalar.
Stage 2 layers five physics-aware constraints on top of the same
X→Y contract.  Each helper here is a pure function so it can be used
both at training time (regularise the fit) and at inference time
(post-hoc correct predictions).

Constraints implemented
-----------------------
1.  Non-negativity clip — applied at train time (clips y_train before
    fit) AND at predict time.  `capacity`, `transmission`, and non-storage
    `gen_*` columns must be ≥ 0; storage `gen_*` and "*_negative" cost
    columns are exempted (same rules as Stage 1's clip_physical_bounds).

2.  XGB monotone constraints — every XGB output uses a monotone hint
    vector aligned to `x_cols`.  Rules encoded in `_monotone_rules_for`
    below; anything not covered is left unconstrained (0).

3.  Regional → system additivity — after regional prediction, rescale
    each per-BA vector so that ΣBA(tech) matches the overall model's
    prediction for the same tech.  Preserves the *shape* the regional
    RF learned but pins the sum.

4.  DistPV / non-cap-expansion techs from dgen curve — cap_distpv is
    exogenous.  In Stage 1 it was constant across all 486 samples; in
    Stage 2 we replace the constant with a linear function of the
    continuous `x_Dem` dial (see `DGEN_DISTPV_CURVE`).

5.  Cost decomposition — cost_total is derived from cost components
    (Σ cost_inv_* + Σ cost_op_*), not predicted directly.  Reduces
    error accumulation and enforces the accounting identity.

Nothing here mutates the Stage 1 code path — Stage 2 imports these
helpers deliberately, Stage 1 does not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# 1. Non-negativity  ---------------------------------------------------------
# ---------------------------------------------------------------------------

# Storage techs whose gen_* net values can legitimately be negative
# (round-trip losses).  Keep in sync with surrogate_predict._STORAGE_GEN_PREFIXES.
_STORAGE_GEN_PREFIXES = (
    "battery", "pumped-hydro", "pumped_hydro", "phs", "caes",
)
# Cost columns tagged as *_negative (ITC/PTC/CO2 incentives) legitimately negative.
_NEGATIVE_COST_MARKER = "_negative"


def _is_storage_gen(col: str) -> bool:
    if not col.startswith("gen_"):
        return False
    rest = col[len("gen_"):].lower()
    return any(rest.startswith(p) for p in _STORAGE_GEN_PREFIXES)


def _is_negative_cost(col: str) -> bool:
    return col.startswith("cost_") and _NEGATIVE_COST_MARKER in col.lower()


def non_negative_mask(y_cols: Sequence[str]) -> np.ndarray:
    """Boolean mask over ``y_cols``: True where the column MUST be ≥ 0."""
    mask = np.zeros(len(y_cols), dtype=bool)
    for i, c in enumerate(y_cols):
        if c.startswith(("cap_", "tran_")):
            mask[i] = True
        elif c.startswith("gen_") and not _is_storage_gen(c):
            mask[i] = True
        elif c.startswith("cost_") and not _is_negative_cost(c):
            mask[i] = True
    return mask


def clip_train_targets(Y: np.ndarray, y_cols: Sequence[str]) -> np.ndarray:
    """Clip training targets to ≥0 where physics requires it.

    Applied before the model sees Y; a fitter that is only ever shown
    non-negative training data has no incentive to produce negatives.
    Returns a new array (input untouched).
    """
    mask = non_negative_mask(y_cols)
    if not mask.any():
        return Y
    Y_out = Y.copy()
    Y_out[:, mask] = np.maximum(Y_out[:, mask], 0.0)
    return Y_out


def clip_predictions(pred: pd.Series) -> pd.Series:
    """Post-hoc clip a single-design prediction (same rules as train-time)."""
    if pred.empty:
        return pred
    vals = pred.to_numpy(dtype=float, copy=True)
    for i, col in enumerate(pred.index):
        if vals[i] >= 0:
            continue
        if col.startswith(("cap_", "tran_")):
            vals[i] = 0.0
        elif col.startswith("gen_") and not _is_storage_gen(col):
            vals[i] = 0.0
        elif col.startswith("cost_") and not _is_negative_cost(col):
            vals[i] = 0.0
    return pd.Series(vals, index=pred.index, name=pred.name)


# ---------------------------------------------------------------------------
# 2. XGB monotone constraints  ----------------------------------------------
# ---------------------------------------------------------------------------

# Design-dial names (x_<Dim>).  Kept centralised so tweaks propagate.
_DIMS = ("Batt", "Dem", "Fuel", "Pol", "REcost", "Siting")


def _monotone_rules_for(y_name: str) -> dict[str, int]:
    """Return {dim: +1 | -1} rules for a single Y column.

    Rules are conservative — only enforce a sign when the physics is
    unambiguous.  Anything unspecified is 0 (unconstrained).
    """
    rules: dict[str, int] = {}
    # ---- costs -----------------------------------------------------------
    if y_name.startswith("cost_") and _NEGATIVE_COST_MARKER not in y_name.lower():
        # Higher demand → higher cost.  Higher fuel price → higher fuel cost.
        rules["Dem"] = +1
        if "fuel" in y_name.lower():
            rules["Fuel"] = +1
    # ---- capacity --------------------------------------------------------
    if y_name.startswith("cap_"):
        # Renewable capacity: higher REcost or tighter Siting => less RE.
        if any(t in y_name.lower() for t in ("upv", "wind", "solar", "distpv")):
            rules["REcost"] = -1
            rules["Siting"] = -1
        # Battery capacity: higher Batt cost => less battery.
        if "battery" in y_name.lower():
            rules["Batt"] = -1
    # ---- generation ------------------------------------------------------
    if y_name.startswith("gen_"):
        low = y_name.lower()
        # Higher fuel price => less gas / coal gen (feasible when RE is
        # available to displace it).
        if "gas" in low or "coal" in low:
            rules["Fuel"] = -1
        if any(t in low for t in ("upv", "wind", "solar", "distpv")):
            rules["REcost"] = -1
            rules["Siting"] = -1
    return rules


def xgb_monotone_vector(y_name: str, x_cols: Sequence[str]) -> tuple[int, ...]:
    """Build an XGBoost `monotone_constraints` tuple aligned to ``x_cols``.

    Returns a tuple of length ``len(x_cols)`` with entries in {-1, 0, +1}.
    """
    rules = _monotone_rules_for(y_name)
    out: list[int] = []
    for xc in x_cols:
        dim = xc[2:] if xc.startswith("x_") else xc
        out.append(int(rules.get(dim, 0)))
    return tuple(out)


def any_monotone(y_name: str) -> bool:
    """True if this Y column has at least one monotone rule attached."""
    return bool(_monotone_rules_for(y_name))


# ---------------------------------------------------------------------------
# 3. Regional → system additivity  ------------------------------------------
# ---------------------------------------------------------------------------

# Regional columns come out of ReEDS as `<var>_<tech>_<pXX>` (e.g.
# ``cap_upv_3_p61``).  A helper to parse the trailing region tag and the
# leading system-level counterpart:
_BA_RE = __import__("re").compile(r"_(p\d+|s\d+|r\d+)$", flags=__import__("re").IGNORECASE)


def _split_regional(col: str) -> tuple[str, str] | None:
    """('cap_upv_3', 'p61') for 'cap_upv_3_p61'; None if not a regional col."""
    m = _BA_RE.search(col)
    if not m:
        return None
    return col[: m.start()], m.group(1)


def enforce_additivity(
    regional_pred: pd.Series,
    overall_pred: pd.Series | None,
) -> pd.Series:
    """Rescale regional predictions so ΣBA(tech) == overall_pred(tech).

    - Applied per system-level tech that is present in BOTH predictions.
    - Only rescales when Σregional > 0 and overall_pred > 0 (avoids
      dividing by zero and preserves sign for cost incentive columns).
    - Regional columns without a matching overall prediction are left alone.
    - `overall_pred=None` → no-op (caller can pass this at training time
      before the overall model exists).

    Returns a new Series; input is not mutated.
    """
    if overall_pred is None or regional_pred.empty:
        return regional_pred
    out = regional_pred.copy()
    # Group regional cols by their system-level parent name.
    groups: dict[str, list[str]] = {}
    for col in out.index:
        split = _split_regional(col)
        if split is None:
            continue
        parent, _ = split
        groups.setdefault(parent, []).append(col)
    for parent, cols in groups.items():
        if parent not in overall_pred.index:
            continue
        target = float(overall_pred[parent])
        current = float(out[cols].sum())
        if current <= 0 or target <= 0:
            continue
        scale = target / current
        # Only rescale when the correction is meaningful (avoid amplifying
        # numerical noise when the two agree already).
        if abs(scale - 1.0) < 1e-6:
            continue
        out.loc[cols] = out.loc[cols].to_numpy() * scale
    return out


# ---------------------------------------------------------------------------
# 4. DistPV / non-cap-expansion techs from dgen curve  ----------------------
# ---------------------------------------------------------------------------

# Very simple placeholder dgen curve:  cap_distpv (GW) as a function of the
# continuous demand dial x_Dem ∈ [0, 2] (0=Lo, 1=Md, 2=Hi).
#
# Anchor points are calibrated so that at x_Dem = 1 (Med) the curve equals
# the Stage 1 constant (12994.628).  Slope is a demand-elasticity estimate
# taken from dGen adoption curves — DistPV grows ~10% between Lo and Hi
# scenarios.  When a real dgen curve is available, replace this block with
# a lookup / interpolation of that table.
DGEN_DISTPV_MED = 12994.628
DGEN_DISTPV_SLOPE_PER_UNIT_DEM = 0.05 * DGEN_DISTPV_MED   # +5% per +1 in x_Dem


def dgen_distpv_cap_mw(x_dem_value: float) -> float:
    """Return exogenous cap_distpv (MW) for a given continuous x_Dem value."""
    return float(DGEN_DISTPV_MED + DGEN_DISTPV_SLOPE_PER_UNIT_DEM * (float(x_dem_value) - 1.0))


# ---------------------------------------------------------------------------
# 5. Cost decomposition  ----------------------------------------------------
# ---------------------------------------------------------------------------

_COST_COMPONENT_PREFIXES = ("cost_inv_", "cost_op_")
_COST_TOTAL = "cost_total"


def cost_component_cols(y_cols: Iterable[str]) -> list[str]:
    """Return the ordered list of cost-component column names in ``y_cols``."""
    return [c for c in y_cols if c.startswith(_COST_COMPONENT_PREFIXES)]


def derive_cost_total(pred: pd.Series) -> pd.Series:
    """Replace ``cost_total`` in ``pred`` with the sum of its components.

    - If ``cost_total`` is not in the prediction, one is appended.
    - If no cost components exist, the prediction is returned unchanged.
    """
    if pred.empty:
        return pred
    comps = cost_component_cols(pred.index)
    if not comps:
        return pred
    total = float(pred[comps].sum())
    out = pred.copy()
    out[_COST_TOTAL] = total
    return out


# ---------------------------------------------------------------------------
# One-stop post-processing at inference time
# ---------------------------------------------------------------------------

@dataclass
class Stage2InferenceConfig:
    apply_non_negativity: bool = True
    apply_additivity: bool = False   # requires overall_pred, so opt-in
    apply_dgen_distpv: bool = True
    apply_cost_decomposition: bool = True


def apply_constraints(
    pred: pd.Series,
    *,
    x_dem_value: float | None = None,
    overall_pred: pd.Series | None = None,
    config: Stage2InferenceConfig | None = None,
) -> pd.Series:
    """Apply the Stage 2 physical constraints to a raw ML prediction.

    Order matters: constraints run innermost → outermost so that
    downstream steps see the already-corrected values.

        1) dgen DistPV override         (fixes cap_distpv)
        2) additivity rescale           (regional only, if overall given)
        3) non-negativity clip
        4) cost decomposition           (derives cost_total from components)
    """
    cfg = config or Stage2InferenceConfig()
    out = pred
    if cfg.apply_dgen_distpv and x_dem_value is not None and "cap_distpv" in out.index:
        out = out.copy()
        out["cap_distpv"] = dgen_distpv_cap_mw(x_dem_value)
    if cfg.apply_additivity and overall_pred is not None:
        out = enforce_additivity(out, overall_pred)
    if cfg.apply_non_negativity:
        out = clip_predictions(out)
    if cfg.apply_cost_decomposition:
        out = derive_cost_total(out)
    return out
