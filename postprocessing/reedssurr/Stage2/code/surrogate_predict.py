"""
Load a saved surrogate model and predict outputs for an arbitrary design point.

Usage (CLI)
-----------
    python surrogate_predict.py \
        --artifact ../outputs/overall/models/rf.joblib \
        --Dem Md --Fuel Hi --REcost Md --Siting Ref --Batt Md --Pol IRA

Usage (library)
---------------
    from surrogate_predict import load_artifact, predict
    art = load_artifact("../outputs/overall/models/rf.joblib")
    y = predict(art, {"Dem": "Md", "Fuel": "Hi", "REcost": "Md",
                      "Siting": "Ref", "Batt": "Md", "Pol": "IRA"})

The returned ``y`` is a ``pandas.Series`` indexed by the original Y column
names from the training CSV (e.g. ``cap_upv_1``, ``cap_wind-ons``,
``gen_gas-cc``, ``cost_total``, ...).
"""

from __future__ import annotations

import argparse
import pickle
from pathlib import Path

import numpy as np
import pandas as pd


# Must match DIMENSION_ENCODING in surrogate_stage1_system.py / stage2.
DIMENSION_ENCODING = {
    "Dem":    {"Lo": 0, "Md": 1, "Hi": 2},
    # Fuel = natural gas price dial. Lo / Md / Hi are the AEO 2025 low / reference /
    # high gas SUPPLY cases, i.e. HIGH / reference / LOW price (dashboard label:
    # "Natural gas price" High / Reference / Low). Encoding unchanged.
    "Fuel":   {"Lo": 0, "Md": 1, "Hi": 2},
    "REcost": {"Lo": 0, "Md": 1, "Hi": 2},
    "Siting": {"Open": 0, "Ref": 1, "Lim": 2},
    "Batt":   {"Lo": 0, "Md": 1, "Hi": 2},
    "Pol":    {"IRA": 0, "OBBBA": 1},
}


def load_artifact(path: str | Path) -> dict:
    """Load a saved model artifact written by ``surrogate_ml_models.py``."""
    with open(path, "rb") as f:
        return pickle.load(f)


def encode_design(levels: dict, x_cols: list[str]) -> np.ndarray:
    """Encode a per-dimension design point to the numeric X vector.

    STAGE 2: ``levels[dim]`` can be either

    - a string label from ``DIMENSION_ENCODING`` (Stage 1 API — still supported),
    - or a numeric value (int/float).  In continuous mode the caller passes
      the slider value directly, so a Dem slider at 1.35 becomes x_Dem = 1.35.

    The Pol dial remains discrete (IRA / OBBBA) because the underlying policy
    switch has no continuous interpretation; passing a float still works but
    is treated as-is (typically 0.0 or 1.0).
    """
    x = np.zeros(len(x_cols), dtype=np.float64)
    for i, col in enumerate(x_cols):
        dim = col[2:] if col.startswith("x_") else col
        if dim not in levels:
            raise ValueError(f"Missing level for dimension '{dim}'. "
                             f"Provided: {list(levels.keys())}")
        raw = levels[dim]
        # Numeric (continuous) input — take as-is.
        if isinstance(raw, (int, float, np.integer, np.floating)) and not isinstance(raw, bool):
            x[i] = float(raw)
            continue
        # Categorical (Stage 1 style).
        encoding = DIMENSION_ENCODING.get(dim)
        if encoding is None:
            raise ValueError(f"Unknown design dimension '{dim}'. "
                             f"Known: {list(DIMENSION_ENCODING.keys())}")
        if raw not in encoding:
            raise ValueError(
                f"Invalid level '{raw}' for dimension '{dim}'. "
                f"Valid: {list(encoding.keys())} (or numeric)"
            )
        x[i] = float(encoding[raw])
    return x


def predict(
    artifact: dict,
    levels: dict,
    overall_pred: pd.Series | None = None,
    constants: dict | None = None,
    floors: dict | None = None,
) -> pd.Series:
    """Predict Y for a single design point and return a labelled Series.

    STAGE 2: predictions are passed through the full domain-constraint
    stack (constant override + non-negativity + regional additivity + cost
    decomposition; see ``surrogate_constraints.apply_constraints``).

    For a regional artifact pass ``overall_pred``, the constrained
    system-level prediction for the same design, so regional values are
    rescaled to the system totals.  ``constants`` is the layer's
    ``summary.json["constant_outputs"]``; when given, those outputs are
    included in the result at their ReEDS value.  ``floors`` are lower bounds
    kept by the regional rescale (``surrogate_constraints.transmission_floors``).
    """
    from surrogate_constraints import apply_constraints  # local import
    x = encode_design(levels, artifact["x_cols"])
    x_s = artifact["scaler_x"].transform(x.reshape(1, -1))
    y_pred = artifact["model"].predict(x_s)
    scaler_y = artifact.get("scaler_y")
    if scaler_y is not None:
        y_pred = scaler_y.inverse_transform(y_pred)
    y_arr = np.asarray(y_pred).ravel()
    series = pd.Series(y_arr, index=artifact["y_cols"], name="prediction")
    return apply_constraints(series, overall_pred=overall_pred, constants=constants,
                             floors=floors)


# ---------------------------------------------------------------------------
# Physical-bound clipping
# ---------------------------------------------------------------------------

# Storage technologies — their NET annual generation (discharge minus charge)
# is legitimately negative due to round-trip losses, so we must NOT clip
# ``gen_*`` columns whose tech token starts with one of these.
_STORAGE_GEN_PREFIXES = ("battery", "pumped-hydro", "pumped_hydro", "phs", "caes")

# Cost columns containing this substring are stored as negative on purpose
# (tax credits / incentives that reduce total system cost — ITC, PTC, 45Q).
# The ReEDS exporter tags them with a literal "_negative" segment.
# The authoritative cost list is the ReEDS sys_costs set; see the note in
# surrogate_constraints.py (op_h2_revenue_exog must be exempt if it appears).
_NEGATIVE_COST_MARKER = "_negative"


def _is_storage_gen(col: str) -> bool:
    """True if ``col`` is a ``gen_*`` column for a storage technology."""
    if not col.startswith("gen_"):
        return False
    rest = col[len("gen_"):].lower()
    return any(rest.startswith(p) for p in _STORAGE_GEN_PREFIXES)


def _is_negative_cost(col: str) -> bool:
    """True if ``col`` is a ``cost_*`` column that can legitimately be negative."""
    return col.startswith("cost_") and _NEGATIVE_COST_MARKER in col.lower()


def clip_physical_bounds(pred: pd.Series) -> pd.Series:
    """Clip surrogate predictions to physically meaningful bounds.

    Applied per-column based on the ReEDS naming convention:

    - ``cap_*``  -> ``max(0, x)``   (capacity is always non-negative)
    - ``tran_*`` -> ``max(0, x)``   (transmission capacity is non-negative)
    - ``gen_*``  -> ``max(0, x)`` UNLESS the tech is storage
                    (battery / pumped-hydro / PHS / CAES net gen can be
                    negative due to round-trip losses)
    - ``cost_*`` -> ``max(0, x)`` UNLESS the column carries the ``_negative``
                    marker (ITC / PTC / CO2 incentive payments — these are
                    stored as negative on purpose to subtract from total cost)
    - everything else is returned unchanged.

    Returns a new Series; the input is not mutated.
    """
    if pred.empty:
        return pred
    vals = pred.to_numpy(dtype=float, copy=True)
    for i, col in enumerate(pred.index):
        if vals[i] >= 0:
            continue  # already non-negative — nothing to clip
        if col.startswith(("cap_", "tran_")):
            vals[i] = 0.0
        elif col.startswith("gen_") and not _is_storage_gen(col):
            vals[i] = 0.0
        elif col.startswith("cost_") and not _is_negative_cost(col):
            vals[i] = 0.0
    return pd.Series(vals, index=pred.index, name=pred.name)


def main():
    parser = argparse.ArgumentParser(
        description="Predict Y from a single design point using a saved surrogate model."
    )
    parser.add_argument("--artifact", required=True,
                        help="Path to a *.joblib artifact in surrogate_ml_results/models/")
    for dim, levels in DIMENSION_ENCODING.items():
        parser.add_argument(f"--{dim}", required=True, choices=sorted(levels),
                            help=f"Level for design dimension {dim}.")
    parser.add_argument("--top_n", type=int, default=20,
                        help="Print the top-N largest predicted outputs.")
    args = parser.parse_args()

    artifact = load_artifact(args.artifact)
    levels = {dim: getattr(args, dim) for dim in DIMENSION_ENCODING}
    y = predict(artifact, levels)

    print(f"Model: {artifact.get('display_name', '?')}  "
          f"(OOF R² mean = {artifact.get('oof_r2_mean', float('nan')):.4f})")
    print(f"Design: {levels}")
    print(f"\nTop {args.top_n} predicted outputs (by absolute value):")
    print(y.reindex(y.abs().sort_values(ascending=False).index).head(args.top_n).to_string())


if __name__ == "__main__":
    main()
