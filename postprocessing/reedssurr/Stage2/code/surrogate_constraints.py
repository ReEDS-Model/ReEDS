"""
Stage 2 domain constraints for ReEDS-Proxy.

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
    At predict time the bound generalises to a known lower bound: 0 for
    those columns, the initial corridor capacity for regional transmission
    corridors and their sum for the system ``tran_total`` (``floors``).

2.  XGB monotone constraints — every XGB output uses a monotone hint
    vector aligned to `x_cols`.  Rules encoded in `_monotone_rules_for`
    below; anything not covered is left unconstrained (0).

3.  Regional → system additivity — after regional prediction, rescale
    each per-BA vector so that ΣBA(tech) matches the overall model's
    prediction for the same tech.  Preserves the *shape* the regional
    RF learned but pins the sum.  Regional columns that the trainer
    dropped as constants are held fixed and subtracted from the system
    target first; transmission corridors (``tran_pNN_pMM_AC``) map to
    ``tran_total``.

4.  Constant outputs held at their ReEDS value — columns with zero
    variance across the training runs (e.g. cap_distpv, which is
    identical in all 486 runs) are dropped before fitting and spliced
    back into the prediction at their constant value.

5.  Cost decomposition — cost_total is derived from cost components
    (Σ cost_inv_* + Σ cost_op_*), not predicted directly.  Reduces
    error accumulation and enforces the accounting identity.

Rules 1, 3, 4 and 5 run at prediction time through `apply_constraints`;
rule 2 only shapes the XGBoost fit.

Nothing here mutates the Stage 1 code path — Stage 2 imports these
helpers deliberately, Stage 1 does not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

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
# The authoritative list of cost terms is the ReEDS ``sys_costs`` set
# (reeds/core/terminus/report.gms); a cost_* column built from any term in it
# that can be negative must be exempt here.  In particular op_h2_revenue_exog
# (exogenous H2 revenue) is negative but has no "_negative" marker: if it ever
# appears as a cost_* column it must be added to the exemptions.
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


def clip_predictions(pred: pd.Series, floors: Mapping[str, float] | None = None) -> pd.Series:
    """Post-hoc clip a single-design prediction at its known lower bound.

    The bound is 0 for the must-be-non-negative columns (same rules as
    train-time) and, for columns in ``floors``, the floor itself (regional
    transmission corridors: their initial capacity, see
    :func:`transmission_floors`; system ``tran_total``: their sum, see
    :func:`system_transmission_floors`).
    """
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
    if floors:
        for i, col in enumerate(pred.index):
            f = floors.get(col)
            if f is not None and vals[i] < f:
                vals[i] = float(f)
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


# Regional transmission columns name an interface between two regions,
# ``tran_<rA>_<rB>[_<trtype>]`` (e.g. ``tran_p60_p61_AC``); their system-level
# counterpart is ``tran_total``.
_TRAN_RE = __import__("re").compile(
    r"^tran_((?:p|s|r)\d+)_((?:p|s|r)\d+)(?:_(.+))?$", flags=__import__("re").IGNORECASE
)
_TRAN_PARENT = "tran_total"


def _additivity_key(col: str) -> tuple[str, tuple] | None:
    """(system parent, quantity key) for a regional column; None otherwise.

    The key identifies one physical quantity: ``(region,)`` for a per-BA
    column and ``((rA, rB), trtype)`` with the region pair sorted for a
    transmission interface, so ``tran_p60_p61_AC`` and ``tran_p61_p60_AC``
    are the same interface and are counted once.
    """
    m = _TRAN_RE.match(col)
    if m:
        pair = tuple(sorted((m.group(1).lower(), m.group(2).lower())))
        return _TRAN_PARENT, (pair, (m.group(3) or "").lower())
    split = _split_regional(col)
    if split is None:
        return None
    parent, region = split
    return parent, (region.lower(),)


def transmission_floors(train_df: pd.DataFrame) -> dict[str, float]:
    """Lower bound of every regional transmission corridor column.

    The floor is the minimum over the training runs.  ReEDS does not retire
    interzonal transmission, so this equals the initial corridor capacity
    ((forward + reverse ITL) / 2, as reported in tran_out); for the 486
    ERCOT runs the two agree exactly for all 11 corridors.
    """
    return {c: float(train_df[c].min()) for c in train_df.columns
            if isinstance(c, str) and _TRAN_RE.match(c)}


def system_transmission_floors(corridor_floors: Mapping[str, float]) -> dict[str, float]:
    """System-level floor: ``tran_total`` >= the sum of the corridor floors
    (total initial interzonal capacity; 34,478.6 MW for the ERCOT runs).
    ``tran_AC_total`` gets the same floor: every corridor is AC, so it equals
    ``tran_total`` in all training runs."""
    if not corridor_floors:
        return {}
    f = float(sum(corridor_floors.values()))
    return {_TRAN_PARENT: f, "tran_AC_total": f}


def enforce_additivity(
    regional_pred: pd.Series,
    overall_pred: pd.Series | None,
    constants: Mapping[str, float] | None = None,
    floors: Mapping[str, float] | None = None,
) -> pd.Series:
    """Rescale regional predictions so ΣBA(tech) == overall_pred(tech).

    - Applied per system-level quantity present in ``overall_pred`` that has
      at least one modelled regional column.
    - ``constants`` are the regional columns the trainer dropped as
      zero-variance (``summary.json["constant_outputs"]``).  They are held
      fixed: their sum is subtracted from the system target and only the
      remaining (modelled) regional columns are scaled.
    - ``floors`` are known lower bounds f_r (transmission corridors, see
      :func:`transmission_floors`; 0 for every other column).  Only the
      increment above the floor is scaled, y_r' = f_r + s (y_r - f_r), with
      s chosen so that Σ y_r' matches the target.  With all f_r = 0 this is
      the plain proportional rescale.
    - Transmission corridors map to ``tran_total``; each interface counts once.
    - Skips when Σ (y_r - f_r) <= 0.  When the adjusted target is at or
      below Σ f_r, a quantity with floors is set to its floors (s = 0) and
      one without floors is skipped.  Every value stays at or above its
      floor, and signs are preserved for storage and incentive columns.
    - Also skips a quantity when any modelled regional value is below its
      floor (with f_r = 0: negative, e.g. storage net generation or PTC
      payments): with mixed signs the sum of increments can be a
      near-cancelling small number and the scale factor explodes.
    - ``overall_pred=None`` → no-op.

    Returns a new Series; input is not mutated.
    """
    if overall_pred is None or regional_pred.empty:
        return regional_pred
    constants = dict(constants or {})
    floors = dict(floors or {})
    out = regional_pred.copy()
    # parent -> {quantity key: [modelled columns]}, and the fixed constants.
    scalable: dict[str, dict[tuple, list[str]]] = {}
    for col in out.index:
        if col in constants:
            continue
        key = _additivity_key(col)
        if key is not None:
            scalable.setdefault(key[0], {}).setdefault(key[1], []).append(col)
    fixed: dict[str, dict[tuple, float]] = {}
    for col, val in constants.items():
        key = _additivity_key(col)
        if key is not None:
            fixed.setdefault(key[0], {}).setdefault(key[1], float(val))
    for parent, by_key in scalable.items():
        if parent not in overall_pred.index:
            continue
        cols = [c for group in by_key.values() for c in group]
        floor = np.array([floors.get(c, 0.0) for c in cols], dtype=float)
        vals = out[cols].to_numpy(dtype=float)
        # Values within round-off of their floor count as at the floor (an
        # average of training values equal to the floor, or an OOF value
        # rebuilt from float32 residuals, can land slightly below it).
        tol = 1e-6 * np.maximum(1.0, np.maximum(np.abs(floor), np.abs(vals)))
        if (vals < floor - tol).any():
            continue
        inc = np.maximum(vals - floor, 0.0)
        # Each quantity counts once: its first column carries value and floor.
        first_idx = [cols.index(group[0]) for group in by_key.values()]
        floor_sum = float(floor[first_idx].sum())
        target = (float(overall_pred[parent]) - sum(fixed.get(parent, {}).values())
                  - floor_sum)
        current = float(inc[first_idx].sum())
        if current <= 0:
            continue
        if target <= 0:
            # System value at or below the sum of the floors: s' = 0, i.e. no
            # expansion above any floor (the closest floor-respecting answer).
            # Without floors (all f = 0) this is the usual skip.
            if floor_sum > 0:
                out.loc[cols] = floor
            continue
        scale = target / current
        # Only rescale when the correction is meaningful (avoid amplifying
        # numerical noise when the two agree already).
        if abs(scale - 1.0) < 1e-6:
            continue
        out.loc[cols] = floor + scale * inc
    return out


# ---------------------------------------------------------------------------
# 4. Constant outputs  -------------------------------------------------------
# ---------------------------------------------------------------------------

def hold_constants(pred: pd.Series, constants: Mapping[str, float] | None) -> pd.Series:
    """Set every known-constant output to its ReEDS value.

    The trainer drops zero-variance Y columns (e.g. cap_distpv, identical in
    all 486 ReEDS runs) before fitting and records their value in
    ``summary.json["constant_outputs"]``.  They are not predicted; they are
    held at that value (appended if missing).  Returns a new Series.
    """
    if not constants:
        return pred
    out = pred.copy()
    for col, val in constants.items():
        out[col] = float(val)
    return out


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
    apply_additivity: bool = True    # regional only; no-op without overall_pred
    apply_constant_override: bool = True
    apply_cost_decomposition: bool = True


def apply_constraints(
    pred: pd.Series,
    *,
    overall_pred: pd.Series | None = None,
    constants: Mapping[str, float] | None = None,
    floors: Mapping[str, float] | None = None,
    config: Stage2InferenceConfig | None = None,
) -> pd.Series:
    """Apply the Stage 2 physical constraints to a raw ML prediction.

    Order matters: each step sees the values corrected by the step before.

        1) constant override     (zero-variance outputs held at their ReEDS value)
        2) lower-bound clip      (0, or the corridor floor for transmission)
        3) additivity rescale    (regional only, when ``overall_pred`` is given;
                                  positive scale factor on the increment above
                                  each floor, so signs and floors are kept)
        4) cost decomposition    (derives cost_total from the components)

    ``overall_pred`` is the already-constrained system-level prediction for
    the same design and model; ``constants`` are the layer's
    ``summary.json["constant_outputs"]``; ``floors`` are known lower bounds
    (regional transmission corridors, :func:`transmission_floors`).  The
    additivity step uses ``constants`` even when the constant override is
    switched off.
    """
    cfg = config or Stage2InferenceConfig()
    out = pred
    if cfg.apply_constant_override:
        out = hold_constants(out, constants)
    if cfg.apply_non_negativity:
        out = clip_predictions(out, floors)
    if cfg.apply_additivity and overall_pred is not None:
        out = enforce_additivity(out, overall_pred, constants, floors)
    if cfg.apply_cost_decomposition:
        out = derive_cost_total(out)
    return out
