"""
Interactive Bokeh dashboard for the ReEDS surrogate model.

What you get
------------
- A **Layer** selector at the top that swaps between Overall (system-wide
  aggregates, ~86 outputs) and Regional (per-region decomposition, ~382
  outputs) without leaving the page.
- Six dropdowns (Dem, Fuel, REcost, Siting, Batt, Pol) for the design point.
- A model dropdown that lists every artifact in ``<results_dir>/models/``
  for the active layer.
- A side-by-side stacked-bar chart of Actual (if the picked design point
  matches a training run) vs Predicted capacity (GW), colored using
  ``bokehpivot/in/reeds2/tech_style.csv``.
- A small metrics panel: overall capacity total, system cost, runtime,
  per-tech error for the largest techs, and the OOF R² for the chosen model.

Launch (unified — both layers, one port)
----------------------------------------
    bokeh serve --show postprocessing/reedssurr/Stage1/code/surrogate_dashboard.py --port 5006

Defaults look for Overall in ``../outputs/overall/`` and Regional in
``../outputs/regional/`` (sibling of this file's parent). Override with:
    --args --overall_dir <dir> --overall_data <csv>
           --regional_dir <dir> --regional_data <csv>
Layers whose ``results_dir`` or ``data`` is missing are silently dropped
from the selector.

Legacy single-layer launch (``--results_dir`` / ``--data``) is still honoured
and maps onto Overall for back-compat with older shell scripts.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from bokeh.io import curdoc
from bokeh.layouts import column, gridplot, row
from bokeh.models import (
    BasicTicker,
    ColorBar,
    ColumnDataSource,
    DataTable,
    Div,
    FactorRange,
    HoverTool,
    LinearColorMapper,
    NumberFormatter,
    Range1d,
    Select,
    Slider,
    Span,
    TableColumn,
    TabPanel,
    Tabs,
)
from bokeh.palettes import Category10, Category20, RdYlGn11
from bokeh.plotting import figure
from bokeh.transform import dodge, jitter

# Local imports — keep the module path importable when launched via ``bokeh serve``.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from surrogate_predict import DIMENSION_ENCODING, clip_physical_bounds, load_artifact, predict   # noqa: E402
from surrogate_constraints import dgen_distpv_cap_mw   # STAGE 2
from surrogate_plots import (                                              # noqa: E402
    _build_tech_lookup,
    aggregate_cap_to_tech_region,
    aggregate_cap_to_techs,
    aggregate_cost_to_buckets,
    aggregate_cost_to_region_bucket,
    aggregate_transmission_by_corridor,
    aggregate_transmission_overall,
    cost_color,
    trtype_color,
    load_tech_map,
    load_tech_style,
    order_techs,
    raw_to_display,
    tech_color,
)
from surrogate_uq import conformal_widths                                  # noqa: E402
from surrogate_eval_captions import (                                      # noqa: E402
    auto_readout_r0,
    auto_readout_r5,
    bokeh_explainer_div,
    bokeh_intro_div,
)

# --- Tolerance bands for color-coded metrics (percent) ---
CAP_TOL_GOOD = 5.0       # |%| <= GOOD  → green
CAP_TOL_WARN = 15.0      # GOOD < |%| <= WARN → amber; > WARN → red
COST_TOL_GOOD = 5.0
COST_TOL_WARN = 15.0
CONFORMAL_ALPHA = 0.1    # 90% conformal interval


# ---------------------------------------------------------------------------
# CLI args (parsed via bokeh's --args passthrough)
# ---------------------------------------------------------------------------

# Stage1 study layout: code/ is sibling of inputs/ and outputs/.
_STUDY_ROOT = _HERE.parent
_DEFAULT_OVERALL_DIR = str(_STUDY_ROOT / "outputs" / "overall")
_DEFAULT_OVERALL_DATA = str(_STUDY_ROOT / "inputs" / "overall_ml_numeric_merged.csv")
_DEFAULT_REGIONAL_DIR = str(_STUDY_ROOT / "outputs" / "regional")
_DEFAULT_REGIONAL_DATA = str(_STUDY_ROOT / "inputs" / "regional_ml_numeric_merged.csv")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    # Legacy single-layer flags (back-compat)
    parser.add_argument("--results_dir", default=None)
    parser.add_argument("--data", default=None)
    # New per-layer flags
    parser.add_argument("--overall_dir", default=_DEFAULT_OVERALL_DIR)
    parser.add_argument("--overall_data", default=_DEFAULT_OVERALL_DATA)
    parser.add_argument("--regional_dir", default=_DEFAULT_REGIONAL_DIR)
    parser.add_argument("--regional_data", default=_DEFAULT_REGIONAL_DATA)
    # Bokeh injects argv past --args; everything else we ignore.
    known, _ = parser.parse_known_args()
    # Legacy override: --results_dir / --data takes precedence on Overall
    if known.results_dir is not None:
        known.overall_dir = known.results_dir
    if known.data is not None:
        known.overall_data = known.data
    return known


ARGS = _parse_args()

# ---------------------------------------------------------------------------
# Stage configuration — keyed by user-facing label
# ---------------------------------------------------------------------------

STAGE_CONFIG: dict[str, dict[str, Path]] = {}
for _label, _dir, _csv in [
    ("Overall (system, ~66 outputs)", Path(ARGS.overall_dir), Path(ARGS.overall_data)),
    ("Regional (per-BA, ~308 outputs)", Path(ARGS.regional_dir), Path(ARGS.regional_data)),
]:
    if _dir.exists() and _csv.exists():
        STAGE_CONFIG[_label] = {"results_dir": _dir, "data_path": _csv}

if not STAGE_CONFIG:
    raise SystemExit(
        "surrogate_dashboard: no layer found. Checked:\n"
        f"  Overall  dir : {ARGS.overall_dir}\n"
        f"  Overall  data: {ARGS.overall_data}\n"
        f"  Regional dir : {ARGS.regional_dir}\n"
        f"  Regional data: {ARGS.regional_data}"
    )

_INITIAL_STAGE = next(iter(STAGE_CONFIG))
# These globals are *mutable* — ``_set_active_stage`` rebinds them. All
# functions below look them up by name on every call (no closure capture),
# so reassignment is picked up automatically.
RESULTS_DIR: Path = STAGE_CONFIG[_INITIAL_STAGE]["results_dir"]
DATA_PATH: Path = STAGE_CONFIG[_INITIAL_STAGE]["data_path"]
MODELS_DIR: Path = RESULTS_DIR / "models"


# ---------------------------------------------------------------------------
# Cross-layer helpers — keyed by 'overall' / 'regional', persistent across
# stage switches. Used by sections (1) and (4) of the eval tab to keep the
# model-comparison view anchored to the OVERALL layer regardless of which
# stage is selected on the Predict tab.
# ---------------------------------------------------------------------------
OOF_CACHE_BY_LAYER: dict[tuple, tuple] = {}
TRAINING_CACHE_BY_LAYER: dict[str, pd.DataFrame] = {}
SUMMARY_CACHE_BY_LAYER: dict[str, dict] = {}


def _layer_paths(short: str):
    """Resolve (results_dir, data_path, models_dir) for ``short`` ('overall' or 'regional')."""
    target = "overall" if "overall" in short.lower() else "regional"
    for label, cfg in STAGE_CONFIG.items():
        if target in label.lower():
            return cfg["results_dir"], cfg["data_path"], cfg["results_dir"] / "models"
    return None, None, None


def _summary_for_layer(short: str) -> dict:
    """Load summary.json for the layer matching ``short``; cached, refreshable."""
    target = "overall" if "overall" in short.lower() else "regional"
    if target in SUMMARY_CACHE_BY_LAYER:
        return SUMMARY_CACHE_BY_LAYER[target]
    res_dir, _, _ = _layer_paths(target)
    if res_dir is None:
        SUMMARY_CACHE_BY_LAYER[target] = {}
        return {}
    p = res_dir / "summary.json"
    if not p.exists():
        SUMMARY_CACHE_BY_LAYER[target] = {}
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    SUMMARY_CACHE_BY_LAYER[target] = data
    return data


def _training_df_for_layer(short: str) -> pd.DataFrame:
    """Load the training CSV for a specific layer, cached."""
    target = "overall" if "overall" in short.lower() else "regional"
    if target in TRAINING_CACHE_BY_LAYER:
        return TRAINING_CACHE_BY_LAYER[target]
    _, data_path, _ = _layer_paths(target)
    if data_path is None or not data_path.exists():
        df = pd.DataFrame()
    else:
        try:
            df = pd.read_csv(data_path)
        except Exception:
            df = pd.DataFrame()
    TRAINING_CACHE_BY_LAYER[target] = df
    return df


def _constants_for_layer(short: str) -> dict[str, float]:
    """Return the ``constant_outputs`` dict written by ``surrogate_ml_models``.

    Each entry maps a Y column (e.g. ``cap_distpv``) to the constant value
    it takes across every training case. These columns were dropped from
    model fitting because their variance is below ``min_variance_threshold``,
    but we still know the exact value — so downstream the dashboard surfaces
    them as point estimates (\u03c3 = 0) instead of silently omitting them.

    Empty dict if the summary file is missing the key (e.g. an older
    training run that pre-dates this feature).
    """
    summary = _summary_for_layer(short)
    raw = summary.get("constant_outputs", {}) if isinstance(summary, dict) else {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def _augment_predicted_with_constants(predicted: pd.Series, short: str) -> pd.Series:
    """Append known-constant Y columns to a model's prediction Series.

    The trainer drops zero-variance columns before fitting (R\u00b2 is
    undefined, scalers divide by zero, NGBoost crashes). But for those
    columns we know the exact value (e.g. ``cap_distpv`` is always
    12,994.6 MW because DistPV is an exogenous policy input in this
    sweep). This helper splices those constants into the prediction so
    the Predict tab's bar charts include them. Existing entries take
    precedence so a model that did learn a column is never overwritten.
    """
    constants = _constants_for_layer(short)
    if not constants:
        return predicted
    if predicted is None or not isinstance(predicted, pd.Series):
        return predicted
    missing = {k: v for k, v in constants.items() if k not in predicted.index}
    if not missing:
        return predicted
    extra = pd.Series(missing, name=predicted.name)
    return pd.concat([predicted, extra])


def _models_for_layer(short: str) -> dict:
    """Discover ``.joblib`` artifacts for a specific layer."""
    target = "overall" if "overall" in short.lower() else "regional"
    _, _, models_dir = _layer_paths(target)
    if models_dir is None or not models_dir.exists():
        return {}
    return {p.stem: p for p in sorted(models_dir.glob("*.joblib"))}


def _artifact_for_layer(short: str, name: str):
    """Load a model artifact for ``short`` layer, returning ``None`` on failure."""
    target = "overall" if "overall" in short.lower() else "regional"
    cache_key = ("artifact", target, name)
    if cache_key in OOF_CACHE_BY_LAYER:
        return OOF_CACHE_BY_LAYER[cache_key]
    paths = _models_for_layer(target)
    if name not in paths:
        OOF_CACHE_BY_LAYER[cache_key] = None
        return None
    try:
        art = load_artifact(paths[name])
    except Exception:
        OOF_CACHE_BY_LAYER[cache_key] = None
        return None
    OOF_CACHE_BY_LAYER[cache_key] = art
    return art


def _get_oof_pred_for_layer(short: str, name: str):
    """Return ``(Y_true, Y_pred, y_cols)`` for ``short`` layer's ``name`` model."""
    target = "overall" if "overall" in short.lower() else "regional"
    cache_key = ("oof", target, name)
    if cache_key in OOF_CACHE_BY_LAYER:
        return OOF_CACHE_BY_LAYER[cache_key]
    art = _artifact_for_layer(target, name)
    if art is None:
        OOF_CACHE_BY_LAYER[cache_key] = None
        return None
    df = _training_df_for_layer(target)
    if df.empty:
        OOF_CACHE_BY_LAYER[cache_key] = None
        return None
    y_cols = list(art.get("y_cols", []))
    oof_res = art.get("oof_residuals")
    if oof_res is None or not y_cols:
        OOF_CACHE_BY_LAYER[cache_key] = None
        return None
    available = [c for c in y_cols if c in df.columns]
    if not available:
        OOF_CACHE_BY_LAYER[cache_key] = None
        return None
    Y_true = df[available].to_numpy(dtype=float)
    oof_arr = np.asarray(oof_res, dtype=float)
    col_idx = [
        y_cols.index(c) for c in available
        if y_cols.index(c) < oof_arr.shape[1]
    ]
    if not col_idx:
        OOF_CACHE_BY_LAYER[cache_key] = None
        return None
    Y_true = Y_true[:, : len(col_idx)]
    Y_pred = Y_true - oof_arr[:, col_idx]
    cols = available[: len(col_idx)]
    val = (Y_true, Y_pred, cols)
    OOF_CACHE_BY_LAYER[cache_key] = val
    return val


# Pooled R² per (layer, model). Loaded lazily because it needs OOF preds.
_POOLED_R2_CACHE: dict[tuple[str, str], float] = {}


def _pooled_r2_for_layer_model(layer_short: str, model_name: str) -> float:
    """Pooled R² across all (case × output) pairs for a model on a layer.

    Same definition used in the parity-grid panel titles: flatten the
    entire (Y_true, Y_pred) array and compute ``1 − SS_res/SS_tot``.
    Dominated by high-magnitude outputs (Capacity), so it stays close to
    1 for well-fitting methods. Cached per (layer, model).
    """
    target = "overall" if "overall" in layer_short.lower() else "regional"
    cache_key = (target, model_name)
    if cache_key in _POOLED_R2_CACHE:
        return _POOLED_R2_CACHE[cache_key]
    triple = _get_oof_pred_for_layer(target, model_name)
    if triple is None:
        _POOLED_R2_CACHE[cache_key] = float("nan")
        return float("nan")
    Y_true, Y_pred, _ = triple
    yt = np.asarray(Y_true, dtype=float).ravel()
    yp = np.asarray(Y_pred, dtype=float).ravel()
    finite = np.isfinite(yt) & np.isfinite(yp)
    yt = yt[finite]
    yp = yp[finite]
    if yt.size <= 1:
        _POOLED_R2_CACHE[cache_key] = float("nan")
        return float("nan")
    ss_tot = float(np.sum((yt - yt.mean()) ** 2))
    if ss_tot <= 0:
        _POOLED_R2_CACHE[cache_key] = float("nan")
        return float("nan")
    ss_res = float(np.sum((yt - yp) ** 2))
    r2 = 1.0 - ss_res / ss_tot
    _POOLED_R2_CACHE[cache_key] = r2
    return r2


def _refresh_layer_caches() -> None:
    """Drop disk-derived caches so a retrain is picked up on next access."""
    SUMMARY_CACHE_BY_LAYER.clear()
    TRAINING_CACHE_BY_LAYER.clear()
    OOF_CACHE_BY_LAYER.clear()
    _POOLED_R2_CACHE.clear()


# ---------------------------------------------------------------------------
# Load training data for the "Actual" lookup (re-loaded on layer change)
# ---------------------------------------------------------------------------

def _load_training_data() -> pd.DataFrame:
    if not DATA_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(DATA_PATH)


TRAINING_DF: pd.DataFrame = _load_training_data()
TECH_MAP_DF = load_tech_map()
TECH_STYLE_DF = load_tech_style()
# Pre-built lookups so per-output metric panels can merge raw tech names
# (e.g. ``wind-ons_4``) into the same display buckets the predict tab uses
# (e.g. ``Onshore Wind``) via :func:`raw_to_display`.
_TECH_EXACT_LOOKUP, _TECH_PREFIX_LOOKUP = _build_tech_lookup(TECH_MAP_DF)


def _tech_display_name(raw_tech: str) -> str:
    """Map a raw tech token (post-region-strip) to its bokehpivot display name.

    Falls back to the raw token unchanged when no rule matches, so non-tech
    outputs (e.g. ``inv_ltc_payments_negative``) stay readable instead of
    being silently relabelled.
    """
    if not raw_tech:
        return raw_tech
    return raw_to_display(raw_tech, _TECH_EXACT_LOOKUP, _TECH_PREFIX_LOOKUP)


def _find_actual_row(levels: dict) -> pd.Series | None:
    """Return the training row for the picked design point, or None.

    STAGE 2: ``levels[dim]`` may be either a categorical label ("Md") or a
    numeric value from a continuous slider (1.35).  Only exact integer
    matches to the discrete training grid resolve to a real row; anything
    in-between returns None (surrogate-only prediction, no actual overlay).
    """
    if TRAINING_DF.empty:
        return None
    df = TRAINING_DF
    for dim, label in levels.items():
        col = f"x_{dim}"
        if col not in df.columns:
            return None
        if isinstance(label, str):
            target = DIMENSION_ENCODING[dim].get(label)
            if target is None:
                return None
        else:
            # Numeric (slider) — only align to the discrete training grid
            # when the value is (numerically) integral.
            fv = float(label)
            if abs(fv - round(fv)) > 1e-9:
                return None
            target = int(round(fv))
        df = df[df[col] == target]
        if df.empty:
            return None
    return df.iloc[0]


# ---------------------------------------------------------------------------
# Model discovery
# ---------------------------------------------------------------------------

def _discover_models() -> dict[str, Path]:
    if not MODELS_DIR.exists():
        return {}
    return {p.stem: p for p in sorted(MODELS_DIR.glob("*.joblib"))}


MODEL_PATHS: dict[str, Path] = _discover_models()
MODEL_CACHE: dict[str, dict] = {}


def _get_artifact(name: str) -> dict | None:
    if name not in MODEL_PATHS:
        return None
    expected_path = MODEL_PATHS[name]
    cached = MODEL_CACHE.get(name)
    # Invalidate the cache if either (a) the artifact was never loaded, or
    # (b) the on-disk path now points to a different file than we cached
    # (layer switch), or (c) the file was rewritten since we cached it
    # (mid-session retrain).
    needs_reload = (
        cached is None
        or cached.get("_source_path") != str(expected_path)
        or cached.get("_source_mtime") != expected_path.stat().st_mtime
    )
    if needs_reload:
        art = load_artifact(expected_path)
        art["_source_path"] = str(expected_path)
        art["_source_mtime"] = expected_path.stat().st_mtime
        MODEL_CACHE[name] = art
    return MODEL_CACHE[name]


# ---------------------------------------------------------------------------
# Bokeh widgets
# ---------------------------------------------------------------------------

design_selects: dict = {}
for dim, levels in DIMENSION_ENCODING.items():
    # STAGE 2: continuous slider for every dial except Pol (binary policy
    # switch — no continuous interpretation).  The slider spans the same
    # 0..(N-1) numeric range the trainer saw for that dimension.
    if dim == "Pol" or len(levels) <= 2:
        default = "Md" if "Md" in levels else next(iter(levels))
        design_selects[dim] = Select(
            title=dim, value=default, options=list(levels.keys()), width=110,
        )
    else:
        max_val = max(levels.values())
        # Level labels sorted by numeric encoding for the slider tooltip.
        sorted_labels = sorted(levels.items(), key=lambda kv: kv[1])
        tick_hint = " → ".join(f"{v}={k}" for k, v in sorted_labels)
        default = float(levels.get("Md", levels.get("Ref", 1)))
        design_selects[dim] = Slider(
            title=f"{dim}  ({tick_hint})",
            start=0.0, end=float(max_val), value=default, step=0.05,
            width=220,
        )

if MODEL_PATHS:
    model_select = Select(
        title="Model", value=next(iter(MODEL_PATHS)),
        options=list(MODEL_PATHS.keys()), width=180,
    )
else:
    model_select = Select(
        title="Model (no artifacts found)", value="",
        options=[], width=240, disabled=True,
    )

# Layer selector — swap between Overall and Regional in-place. Disabled if
# only one layer was discovered at startup.
stage_select = Select(
    title="Layer",
    value=_INITIAL_STAGE,
    options=list(STAGE_CONFIG.keys()),
    width=260,
    disabled=len(STAGE_CONFIG) < 2,
)

# Variable selector — pick which output family the bar chart should show.
# Capacity is the default; Generation / System cost / Transmission are extra
# views that exercise the same Actual vs Predicted comparison on the other
# ReEDS output families pulled by the data_processing scripts.
VARIABLE_OPTIONS = [
    "Capacity (GW)",
    "Generation (TWh)",
    "System cost ($B)",
    "Transmission (GW)",
]
# Transmission is a corridor (r,rr) quantity, not per-region (r), so it does
# not fit the per-BA Regional layout. Hide it from the dropdown whenever the
# Layer selector is set to Regional.
_REGIONAL_HIDDEN_VARIABLES = {"Transmission (GW)"}


def _variable_options_for_stage(stage: str) -> list[str]:
    # STAGE_CONFIG keys are full labels (e.g. ``"Regional (per-BA, ~308 outputs)"``),
    # so we match on the leading word instead of an exact string.
    if stage.startswith("Regional"):
        return [v for v in VARIABLE_OPTIONS if v not in _REGIONAL_HIDDEN_VARIABLES]
    return list(VARIABLE_OPTIONS)


_initial_variable_options = _variable_options_for_stage(_INITIAL_STAGE)
variable_select = Select(
    title="Variable",
    value=_initial_variable_options[0],
    options=_initial_variable_options,
    width=200,
)


def _sync_variable_options_for_stage(stage: str) -> None:
    """Update the Variable dropdown so it only lists choices valid for ``stage``.

    If the current selection becomes invalid (e.g. Transmission while switching
    to Regional) we fall back to the first valid option. Setting ``.value``
    triggers ``_on_change`` -> ``_redraw`` automatically.
    """
    new_opts = _variable_options_for_stage(stage)
    if variable_select.options != new_opts:
        variable_select.options = new_opts
    if variable_select.value not in new_opts:
        variable_select.value = new_opts[0]

# (training-case shortcut removed: auto-detected from the 6 design dropdowns)


def _design_from_row(row: pd.Series) -> dict[str, str]:
    """Inverse of encode_design: read x_<dim> integer columns back to labels."""
    out: dict[str, str] = {}
    for dim, levels in DIMENSION_ENCODING.items():
        col = f"x_{dim}"
        if col not in row:
            continue
        target = int(row[col])
        for label, encoded in levels.items():
            if encoded == target:
                out[dim] = label
                break
    return out


header = Div(text="""
<h2 style='margin:0'>ReEDS Surrogate Model — <span style='color:#0b6efd'>Stage 2</span> Interactive Panel</h2>
<p style='color:#555;margin:2px 0 8px 0'>Continuous dials for Dem / Fuel / REcost / Siting / Batt (Pol stays binary).
Predictions pass through the Stage 2 constraint stack (non-negativity, XGB
monotone hints, dgen DistPV override, cost decomposition). The top panel
shows the ReEDS-style stacked portfolio (actual vs. surrogate
prediction). The bottom panel shows per-category surrogate uncertainty
(90% conformal CI). When the picked design matches a training run, the
&ldquo;Actual&rdquo; values are read from the stored ReEDS output; otherwise the
actual is left blank and only the surrogate prediction is shown.</p>
""")

status_div = Div(text="", width=420)
metrics_div = Div(text="", width=420)


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

source = ColumnDataSource(data={"x": [], "tech": [], "top": [], "color": []})

# Layout sizing
# -------------
# The legend lives in a SEPARATE Div widget (see ``legend_div`` below) that
# sits next to the plot in the row layout. This keeps the legend truly
# outside the plot — Bokeh never has to negotiate horizontal space between
# bars and legend, so we can't get clipping or label truncation no matter
# how many bars / cost buckets / tech categories are active.
_PLOT_WIDTH_SYSTEM = 460
_PLOT_HEIGHT = 520
# All three stacked panels (main bars / per-category error / UQ-coloured stack)
# share the same height so the figures line up as equal-size tiles. Inner-frame
# alignment is still guaranteed by ``min_border_left`` / ``min_border_right``
# being identical on each, and by ``x_range=plot.x_range`` on the lower panels.
_DIFF_HEIGHT = _PLOT_HEIGHT   # was 320 — match main bar plot
_UQ_HEIGHT = _PLOT_HEIGHT     # was 240 — match main bar plot
_LEGEND_WIDTH = 220
_BAR_PX = 55              # nominal pixels per stacked bar (Actual or Predicted)
_AXIS_PAD_PX = 100        # y-axis label + tick labels + plot margin
# Force the same left/right borders on the main plot AND every secondary
# panel below it so that, for equal ``width``, every plot has the same
# INNER frame width — which is what makes region groups in the bar plot
# line up vertically with the stacks/dots in the diff and UQ panels.
_BORDER_LEFT = 80
_BORDER_RIGHT = 20

plot = figure(
    height=_PLOT_HEIGHT, width=_PLOT_WIDTH_SYSTEM,
    x_range=FactorRange("Actual", "Predicted"),
    # Explicit Range1d so subsequent .update(start=..., end=...) calls
    # always propagate. The default DataRange1d would auto-fit to glyphs
    # but mixes badly with the "(custom)" -> rendered transition where
    # we manually set bounds.
    y_range=Range1d(start=0, end=1.0),
    title="Capacity portfolio (GW, 2050)",
    # Interactive zoom / pan / reset. ``toolbar_location='above'`` keeps the
    # total figure WIDTH unchanged across the three stacked panels so bars
    # in the main / diff / UQ plots stay pixel-aligned vertically.
    toolbar_location="above",
    tools="box_zoom,xbox_zoom,ybox_zoom,pan,reset,save",
    active_drag="box_zoom",
    y_axis_label="Capacity (GW)",
    sizing_mode="fixed",
    min_border_left=_BORDER_LEFT,
    min_border_right=_BORDER_RIGHT,
)
plot.toolbar.logo = None
plot.xgrid.grid_line_color = None
plot.title.text_font_size = "11pt"
plot.xaxis.major_label_orientation = 0.6  # angled labels for Regional nested factors

# ---------------------------------------------------------------------------
# Main-bar data sources & hover tooltip
# ---------------------------------------------------------------------------
# The Actual / Predicted stacks share x positions but have different tooltip
# needs: hovering a Predicted slice should reveal the per-slice 90% conformal
# interval, while Actual is just the ground-truth value. We therefore keep two
# pre-registered ColumnDataSources + vbar renderers, populated by the render
# functions via cheap ``source.data = dict(...)`` swaps. The HoverTool is
# attached ONLY to the Predicted renderer so users get UQ info exactly where
# the user asked for it ("put the cursor on the predicted item").
_BARS_ACTUAL_COLS = ("x", "bottom", "top", "color", "tech", "value", "subtitle", "unit")
_BARS_PRED_COLS = (
    "x", "bottom", "top", "color", "tech", "value",
    "ci_half", "ci_lo", "ci_hi", "subtitle", "unit",
)


def _empty_actual_bars_data() -> dict:
    return {c: [] for c in _BARS_ACTUAL_COLS}


def _empty_pred_bars_data() -> dict:
    return {c: [] for c in _BARS_PRED_COLS}


bars_actual_source = ColumnDataSource(data=_empty_actual_bars_data())
bars_pred_source = ColumnDataSource(data=_empty_pred_bars_data())

_actual_vbar = plot.vbar(
    x="x", bottom="bottom", top="top",
    width=0.7,
    color="color",
    source=bars_actual_source,
    line_color="white", line_width=0.5,
)
_pred_vbar = plot.vbar(
    x="x", bottom="bottom", top="top",
    width=0.7,
    color="color",
    source=bars_pred_source,
    line_color="white", line_width=0.5,
)

_actual_hover = HoverTool(
    renderers=[_actual_vbar],
    tooltips="""
        <div style="padding:4px;font-family:sans-serif;font-size:11px;max-width:240px">
          <div style="font-weight:600;font-size:12px;color:#222">@tech</div>
          <div style="color:#666;margin-bottom:6px">@subtitle &middot; <b>Actual</b></div>
          <div>Value: <b>@value{0,0.000}</b> @unit</div>
        </div>
    """,
    point_policy="follow_mouse",
)
_pred_hover = HoverTool(
    renderers=[_pred_vbar],
    tooltips="""
        <div style="padding:4px;font-family:sans-serif;font-size:11px;max-width:260px">
          <div style="font-weight:600;font-size:12px;color:#222">@tech</div>
          <div style="color:#666;margin-bottom:6px">@subtitle &middot; <b>Predicted</b></div>
          <div>Value: <b>@value{0,0.000}</b> @unit</div>
          <div style="color:#c0392b;margin-top:3px">
            90% CI: &plusmn;@ci_half{0,0.000} @unit
          </div>
          <div style="color:#888;font-size:10px">
            [@ci_lo{0,0.000}, @ci_hi{0,0.000}]
          </div>
        </div>
    """,
    point_policy="follow_mouse",
)
plot.add_tools(_actual_hover, _pred_hover)

# Standalone legend widget. We render the swatches + labels as HTML inside
# a ``Div`` so the legend lives in its OWN layout slot — totally separate
# from the plot figure. The plot stays compact and Bokeh has no chance to
# squeeze the legend into a too-narrow side panel.
legend_div = Div(
    text="",
    width=_LEGEND_WIDTH,
    height=_PLOT_HEIGHT,
    styles={
        "overflow-y": "auto",
        "overflow-x": "hidden",
        "padding": "24px 8px 8px 0",
        "font-size": "11px",
        "line-height": "1.45",
    },
)


def _build_legend_html(items: list[tuple[str, str]]) -> str:
    """Return HTML for the side legend given (label, color) pairs."""
    if not items:
        return ""
    rows = []
    for label, color in items:
        rows.append(
            f"<div style='display:flex;align-items:center;margin-bottom:3px'>"
            f"<span style='display:inline-block;width:14px;height:14px;"
            f"background:{color};border:1px solid rgba(0,0,0,0.15);"
            f"margin-right:6px;flex-shrink:0'></span>"
            f"<span style='color:#222'>{label}</span>"
            f"</div>"
        )
    return "<div><b style='color:#444'>Legend</b></div>" + "".join(rows)


# ---------------------------------------------------------------------------
# Diff panel (predicted − actual, per category)
# ---------------------------------------------------------------------------
# Sits between the main stacked bars and the UQ panel. Bars going UP (red)
# mean the surrogate over-predicts that category vs the ReEDS actual; bars
# going DOWN (blue) mean under-prediction. Aggregated to system-level the
# same way as the UQ panel, so the three stacked panels share the same
# category x-axis when an Actual run exists.
diff_plot = figure(
    height=_DIFF_HEIGHT,
    width=_PLOT_WIDTH_SYSTEM,
    # Share x_range with the MAIN plot (same trick the UQ panel uses) so the
    # diff stack lands pixel-aligned under the Predicted column above and is
    # exactly the same width as the UQ stack below.
    x_range=plot.x_range,
    y_range=Range1d(start=-1.0, end=1.0),
    title="Per-category prediction error (predicted − actual)",
    toolbar_location="above",
    tools="box_zoom,xbox_zoom,ybox_zoom,pan,reset,save",
    active_drag="box_zoom",
    y_axis_label="Error (GW)",
    sizing_mode="fixed",
    min_border_left=_BORDER_LEFT,
    min_border_right=_BORDER_RIGHT,
)
diff_plot.toolbar.logo = None
diff_plot.xaxis.major_label_orientation = 0.7

diff_source = ColumnDataSource(
    data=dict(x=[], bottom=[], top=[], color=[], tech=[],
              value=[], subtitle=[], unit=[])
)
# Separate source for the per-x-tick total dots (and, in Regional view,
# a system-wide "Total" dot at the right edge).
diff_total_source = ColumnDataSource(
    data=dict(x=[], y=[], subtitle=[], unit=[])
)

_diff_vbar = diff_plot.vbar(
    x="x", bottom="bottom", top="top",
    width=0.7,
    color="color",
    source=diff_source,
    line_color="white", line_width=0.5,
)
_diff_total_scatter = diff_plot.scatter(
    x="x", y="y",
    source=diff_total_source,
    size=12, marker="circle",
    fill_color="#000", line_color="#000",
)
# Hover tooltips: per-tech slice gets tech / region / signed value, the
# net dot gets the region and signed total.
_diff_slice_hover = HoverTool(
    renderers=[_diff_vbar],
    tooltips="""
        <div style="padding:4px;font-family:sans-serif;font-size:11px;max-width:260px">
          <div style="font-weight:600;font-size:12px;color:#222">@tech</div>
          <div style="color:#666;margin-bottom:4px">@subtitle &middot; <b>Prediction error slice</b></div>
          <div>predicted &minus; actual: <b>@value{+0,0.000}</b> @unit</div>
        </div>
    """,
    point_policy="follow_mouse",
)
_diff_total_hover = HoverTool(
    renderers=[_diff_total_scatter],
    tooltips="""
        <div style="padding:4px;font-family:sans-serif;font-size:11px;max-width:240px">
          <div style="font-weight:600;font-size:12px;color:#222">Net error</div>
          <div style="color:#666;margin-bottom:4px">@subtitle</div>
          <div>predicted &minus; actual: <b>@y{+0,0.000}</b> @unit</div>
        </div>
    """,
    point_policy="follow_mouse",
)
diff_plot.add_tools(_diff_slice_hover, _diff_total_hover)
diff_plot.add_layout(
    Span(location=0, dimension="width", line_color="#888", line_width=1)
)


# ---------------------------------------------------------------------------
# Uncertainty-quantification (UQ) panel
# ---------------------------------------------------------------------------
# Sits directly below the main stacked-bar plot. ONE colored vbar is drawn
# per Predicted column in the main plot — the UQ panel shares the main
# plot's ``x_range`` so each UQ bar lands pixel-aligned under the corresponding
# Predicted stack above (Actual columns are simply left empty in this panel).
#
# Bar HEIGHT = total predicted value at that x (so the UQ bar is the same
# height as the Predicted stack above it, in the same axis units).
# Bar COLOR = (90% CI half-width / |total predicted|) × 100%, mapped through
# a green→yellow→red gradient so a quick glance answers the question
# "how confident is the surrogate in this prediction?". A side colorbar
# shows the % scale.
#
# Half-widths are read from each artifact's stored OOF residuals via
# :func:`surrogate_uq.conformal_widths` and aggregated through the SAME
# ``agg_system`` / ``agg_regional`` pipeline that the values use, so the
# numerator and denominator of the ratio always come from matching slices.
# Colour-mapper for the UQ panel slices.  Linear green -> yellow -> red
# gradient runs over 0-50%.  Anything > 50% (including near-zero pred
# divide-by-zero blow-ups) gets painted SOLID BLACK via ``high_color``
# so outliers stand out without flattening the gradient for the rest.
UQ_CI_PCT_MAX = 50.0
UQ_HIGH_COLOR = "#000000"
uq_color_mapper = LinearColorMapper(
    # Bokeh's RdYlGn11 already goes GREEN -> YELLOW -> RED (idx 0 = #006837,
    # idx 10 = #a50026), which is exactly what we want for an "uncertainty"
    # scale: low CI%  -> green = good / confident prediction, high CI%  -> red
    # = bad / noisy prediction.  Used as-is (no reversal).
    palette=RdYlGn11,
    low=0.0,
    high=UQ_CI_PCT_MAX,
    high_color=UQ_HIGH_COLOR,
)
uq_plot = figure(
    height=_UQ_HEIGHT,
    width=_PLOT_WIDTH_SYSTEM,
    x_range=plot.x_range,   # shared with main plot → perfect column alignment
    y_range=Range1d(start=0, end=1.0),
    title="Predicted bar coloured by 90% CI / |value| (%)",
    toolbar_location="above",
    tools="box_zoom,xbox_zoom,ybox_zoom,pan,reset,save",
    active_drag="box_zoom",
    y_axis_label="Capacity (GW)",
    sizing_mode="fixed",
    min_border_left=_BORDER_LEFT,
    min_border_right=_BORDER_RIGHT,
)
uq_plot.toolbar.logo = None
uq_plot.xaxis.major_label_orientation = 0.6
uq_plot.xgrid.grid_line_color = None

uq_source = ColumnDataSource(data=dict(
    x=[], bottom=[], top=[], ci_pct=[], tech=[],
    pred=[], half=[], ci_lo=[], ci_hi=[], subtitle=[], unit=[],
))
_uq_vbar = uq_plot.vbar(
    x="x", bottom="bottom", top="top", width=0.7,
    source=uq_source,
    fill_color={"field": "ci_pct", "transform": uq_color_mapper},
    line_color="white", line_width=0.5,
)
uq_plot.add_tools(HoverTool(
    renderers=[_uq_vbar],
    tooltips="""
        <div style="padding:4px;font-family:sans-serif;font-size:11px;max-width:260px">
          <div style="font-weight:600;font-size:12px;color:#222">@tech</div>
          <div style="color:#666;margin-bottom:4px">@subtitle &middot; <b>Predicted slice</b></div>
          <div>Value: <b>@pred{0,0.000}</b> @unit</div>
          <div style="color:#c0392b">90% CI: &plusmn;@half{0,0.000} @unit</div>
          <div style="color:#888">[@ci_lo{0,0.000}, @ci_hi{0,0.000}]</div>
          <div style="margin-top:3px;font-weight:600">
            Relative CI: @ci_pct{0.0}%
          </div>
        </div>
    """,
    point_policy="follow_mouse",
))
# ----- Standalone CI colorbar (lives next to the tech legend) -----
# We DON'T attach the ColorBar to ``uq_plot.right`` any more, because that
# steals horizontal space from the UQ plot's inner frame and (a) breaks
# column alignment with the main plot above, (b) the colorbar title was
# being clipped by the available vertical space.  Hosting it in its own
# tiny figure next to ``legend_div`` keeps everything visible and aligned.
ci_colorbar_fig = figure(
    width=120,
    height=_PLOT_HEIGHT,
    toolbar_location=None,
    tools="",
    min_border_left=0,
    min_border_right=0,
    min_border_top=24,
    min_border_bottom=24,
    outline_line_color=None,
)
ci_colorbar_fig.axis.visible = False
ci_colorbar_fig.grid.visible = False
uq_colorbar = ColorBar(
    color_mapper=uq_color_mapper,
    title=f"90% CI / |value| (%)  — ≥{UQ_CI_PCT_MAX:.0f}% shown black",
    ticker=BasicTicker(desired_num_ticks=6),
    label_standoff=6,
    width=18,
    border_line_color=None,
    location=(0, 0),
)
ci_colorbar_fig.add_layout(uq_colorbar, "center")


# ---------------------------------------------------------------------------
# Update logic
# ---------------------------------------------------------------------------

def _row_to_cap_series(row: pd.Series | None) -> pd.Series:
    """Extract a cap_* slice from a training row. Empty Series if row is None."""
    if row is None:
        return pd.Series(dtype=float)
    cap_cols = [c for c in row.index if isinstance(c, str) and c.startswith("cap_")]
    return row[cap_cols].astype(float)


def _row_slice(row_or_series: pd.Series | None, prefix: str) -> pd.Series:
    """Generic prefix slice (cap_, gen_, cost_, tran_)."""
    if row_or_series is None or row_or_series.empty:
        return pd.Series(dtype=float)
    cols = [
        c for c in row_or_series.index
        if isinstance(c, str) and c.startswith(prefix)
    ]
    return row_or_series[cols].astype(float)


# ---------------------------------------------------------------------------
# Variable specs: drive what the bar chart shows. Each spec knows how to
# slice the row by prefix, aggregate it (system or regional), pick colors,
# and report units.
# ---------------------------------------------------------------------------

def _agg_techs(series: pd.Series, prefix: str) -> pd.Series:
    return aggregate_cap_to_techs(series, tech_map_df=TECH_MAP_DF, prefix=prefix)


def _agg_tech_region(series: pd.Series, prefix: str) -> pd.DataFrame:
    return aggregate_cap_to_tech_region(series, tech_map_df=TECH_MAP_DF, prefix=prefix)


def _order_techs_local(keys) -> list[str]:
    return order_techs(keys, style_df=TECH_STYLE_DF)


def _tech_color_local(k: str) -> str:
    return tech_color(k, style_df=TECH_STYLE_DF)


def _identity_order(keys) -> list[str]:
    """Order = whatever order the aggregator already gave us."""
    return list(keys)


VARIABLE_SPEC: dict[str, dict] = {
    "Capacity (GW)": {
        "prefix": "cap_",
        "scale": 1e-3,                       # MW  -> GW
        "axis_label": "Capacity (GW)",
        "title_noun": "Capacity portfolio",
        "agg_system": lambda s: _agg_techs(s, "cap_"),
        "agg_regional": lambda s: _agg_tech_region(s, "cap_"),
        "order": _order_techs_local,
        "color": _tech_color_local,
    },
    "Generation (TWh)": {
        "prefix": "gen_",
        "scale": 1e-6,                       # MWh -> TWh
        "axis_label": "Generation (TWh / yr)",
        "title_noun": "Annual generation",
        "agg_system": lambda s: _agg_techs(s, "gen_"),
        "agg_regional": lambda s: _agg_tech_region(s, "gen_"),
        "order": _order_techs_local,
        "color": _tech_color_local,
    },
    "System cost ($B)": {
        "prefix": "cost_",
        "scale": 1e-9,                       # $   -> $B
        "axis_label": "System cost ($B, NPV)",
        "title_noun": "System cost",
        "agg_system": aggregate_cost_to_buckets,
        "agg_regional": aggregate_cost_to_region_bucket,
        "order": _identity_order,            # buckets already canonically ordered
        "color": cost_color,
    },
    "Transmission (GW)": {
        "prefix": "tran_",
        "scale": 1e-3,                       # MW  -> GW
        "axis_label": "Transmission (GW)",
        "title_noun": "Transmission capacity",
        # For Transmission the "stack" is by trtype (always 1 entry in this
        # ERCOT dataset, but we keep the same machinery).
        "agg_system": aggregate_transmission_overall,
        # Regional view: one stacked bar per corridor (Actual vs Predicted).
        # Returns a DataFrame indexed by corridor with one column = trtype.
        "agg_regional": lambda s: (
            aggregate_transmission_by_corridor(s).to_frame(name="AC")
            if not aggregate_transmission_by_corridor(s).empty
            else pd.DataFrame()
        ),
        "order": _identity_order,
        "color": trtype_color,               # bokehpivot trtype palette
    },
}


def _active_spec() -> dict:
    return VARIABLE_SPEC.get(variable_select.value, VARIABLE_SPEC[VARIABLE_OPTIONS[0]])


def _half_agg_for_view(artifact: dict | None, spec: dict, is_regional: bool):
    """Return per-category 90% conformal half-widths in the active layout.

    Pulls the per-output conformal widths off the artifact and aggregates
    them through the same ``agg_system`` / ``agg_regional`` aggregator that
    the values use, so per-slice CI lookup is just a (cat,) or (region, cat)
    indexing operation. Returns an empty Series / DataFrame on any failure
    so hover tooltips just show ±0 instead of crashing.
    """
    empty = pd.DataFrame() if is_regional else pd.Series(dtype=float)
    if artifact is None:
        return empty
    try:
        half_raw = conformal_widths(artifact, alpha=CONFORMAL_ALPHA)
        y_cols = list(artifact.get("y_cols", []))
        half_series = pd.Series(half_raw, index=y_cols, dtype=float)
        prefix = spec["prefix"]
        half_var = half_series[half_series.index.str.startswith(prefix)]
        if half_var.empty:
            return empty
        agg_key = "agg_regional" if is_regional else "agg_system"
        return spec[agg_key](half_var)
    except Exception:  # noqa: BLE001 — UQ is best-effort
        return empty


def _render_system_bars(
    actual_raw: pd.Series, pred_raw: pd.Series,
    levels: dict[str, str], status_text_set: bool,
    artifact: dict | None = None,
) -> bool:
    """Draw Overall view: Actual vs Predicted stacked totals."""
    spec = _active_spec()
    scale = spec["scale"]
    actual_agg = spec["agg_system"](actual_raw) if not actual_raw.empty else pd.Series(dtype=float)
    pred_agg = spec["agg_system"](pred_raw) if not pred_raw.empty else pd.Series(dtype=float)
    half_agg = _half_agg_for_view(artifact, spec, is_regional=False)
    unit = spec["axis_label"].split("(")[-1].rstrip(")")

    plot.x_range.factors = ["Actual", "Predicted"]
    if plot.width != _PLOT_WIDTH_SYSTEM:
        plot.width = _PLOT_WIDTH_SYSTEM
    plot.yaxis.axis_label = spec["axis_label"]

    cats = spec["order"](set(actual_agg.index) | set(pred_agg.index))
    threshold = 1e-3  # smallest displayable in the chosen units
    cats = [
        c for c in cats
        if (abs(float(actual_agg.get(c, 0.0))) + abs(float(pred_agg.get(c, 0.0)))) * scale > threshold
    ]
    if not cats:
        bars_actual_source.data = _empty_actual_bars_data()
        bars_pred_source.data = _empty_pred_bars_data()
        return False

    # Stacks include negatives (e.g., ITC payments). Track top of stack
    # separately for positive and negative contributions so they stack cleanly.
    pos_base = {"Actual": 0.0, "Predicted": 0.0}
    neg_base = {"Actual": 0.0, "Predicted": 0.0}
    legend_pairs: list[tuple[str, str]] = []
    actual_rows: dict[str, list] = _empty_actual_bars_data()
    pred_rows: dict[str, list] = _empty_pred_bars_data()
    for cat in cats:
        actual_val = float(actual_agg.get(cat, 0.0)) * scale
        pred_val = float(pred_agg.get(cat, 0.0)) * scale
        half_val = (
            float(half_agg.get(cat, 0.0)) * scale
            if isinstance(half_agg, pd.Series) and not half_agg.empty else 0.0
        )
        color = spec["color"](cat)

        if actual_val >= 0:
            a_bot, a_top = pos_base["Actual"], pos_base["Actual"] + actual_val
            pos_base["Actual"] += actual_val
        else:
            a_top, a_bot = neg_base["Actual"], neg_base["Actual"] + actual_val
            neg_base["Actual"] += actual_val
        actual_rows["x"].append("Actual")
        actual_rows["bottom"].append(a_bot)
        actual_rows["top"].append(a_top)
        actual_rows["color"].append(color)
        actual_rows["tech"].append(cat)
        actual_rows["value"].append(actual_val)
        actual_rows["subtitle"].append("System")
        actual_rows["unit"].append(unit)

        if pred_val >= 0:
            p_bot, p_top = pos_base["Predicted"], pos_base["Predicted"] + pred_val
            pos_base["Predicted"] += pred_val
        else:
            p_top, p_bot = neg_base["Predicted"], neg_base["Predicted"] + pred_val
            neg_base["Predicted"] += pred_val
        pred_rows["x"].append("Predicted")
        pred_rows["bottom"].append(p_bot)
        pred_rows["top"].append(p_top)
        pred_rows["color"].append(color)
        pred_rows["tech"].append(cat)
        pred_rows["value"].append(pred_val)
        pred_rows["ci_half"].append(half_val)
        pred_rows["ci_lo"].append(pred_val - half_val)
        pred_rows["ci_hi"].append(pred_val + half_val)
        pred_rows["subtitle"].append("System")
        pred_rows["unit"].append(unit)

        legend_pairs.append((cat, color))

    bars_actual_source.data = actual_rows
    bars_pred_source.data = pred_rows
    legend_div.text = _build_legend_html(legend_pairs)
    ymax = max(pos_base.values()) if pos_base else 1.0
    ymin = min(neg_base.values()) if neg_base else 0.0
    plot.y_range.update(
        start=(ymin * 1.15) if ymin < 0 else 0,
        end=ymax * 1.15 if ymax > 0 else 1.0,
    )
    plot.title.text = f"{spec['title_noun']} ({unit}, 2050)"
    return True


def _render_regional_bars(
    actual_raw: pd.Series, pred_raw: pd.Series,
    levels: dict[str, str], status_text_set: bool,
    artifact: dict | None = None,
) -> bool:
    """Draw Regional view: one Actual / Predicted stacked pair per region."""
    spec = _active_spec()
    scale = spec["scale"]
    actual_tr = spec["agg_regional"](actual_raw) if not actual_raw.empty else pd.DataFrame()
    pred_tr = spec["agg_regional"](pred_raw) if not pred_raw.empty else pd.DataFrame()
    half_tr = _half_agg_for_view(artifact, spec, is_regional=True)
    unit = spec["axis_label"].split("(")[-1].rstrip(")")

    # Union of regions
    regions = sorted(
        set(actual_tr.index) | set(pred_tr.index),
        key=lambda r: (r[:1], int(r[1:])) if r[1:].isdigit() else (r, 0),
    )
    cats = spec["order"](set(actual_tr.columns) | set(pred_tr.columns))
    threshold = 1e-3
    cats = [
        c for c in cats
        if max(
            abs(float(actual_tr[c].sum())) if c in actual_tr.columns else 0.0,
            abs(float(pred_tr[c].sum())) if c in pred_tr.columns else 0.0,
        ) * scale > threshold
    ]
    if not regions or not cats:
        bars_actual_source.data = _empty_actual_bars_data()
        bars_pred_source.data = _empty_pred_bars_data()
        return False

    x_factors = [(r, kind) for r in regions for kind in ("Actual", "Predicted")]
    plot.x_range.factors = x_factors
    # Plot width grows with the number of bars. The legend lives in its own
    # Div widget (see ``legend_div``) so we don't reserve any horizontal
    # space for it here — keeps the plot compact and the legend never gets
    # clipped by Bokeh's side-panel layout.
    target_width = max(_PLOT_WIDTH_SYSTEM, _AXIS_PAD_PX + _BAR_PX * len(x_factors))
    if plot.width != target_width:
        plot.width = target_width
    plot.yaxis.axis_label = spec["axis_label"]

    pos_base: dict[tuple[str, str], float] = {x: 0.0 for x in x_factors}
    neg_base: dict[tuple[str, str], float] = {x: 0.0 for x in x_factors}
    legend_pairs: list[tuple[str, str]] = []
    actual_rows: dict[str, list] = _empty_actual_bars_data()
    pred_rows: dict[str, list] = _empty_pred_bars_data()
    for cat in cats:
        color = spec["color"](cat)
        for r in regions:
            a_val = (
                float(actual_tr.loc[r, cat]) * scale
                if r in actual_tr.index and cat in actual_tr.columns else 0.0
            )
            p_val = (
                float(pred_tr.loc[r, cat]) * scale
                if r in pred_tr.index and cat in pred_tr.columns else 0.0
            )
            half_val = (
                float(half_tr.loc[r, cat]) * scale
                if isinstance(half_tr, pd.DataFrame)
                and r in half_tr.index and cat in half_tr.columns else 0.0
            )

            # Actual slice
            key_a = (r, "Actual")
            if a_val >= 0:
                a_bot, a_top = pos_base[key_a], pos_base[key_a] + a_val
                pos_base[key_a] += a_val
            else:
                a_top, a_bot = neg_base[key_a], neg_base[key_a] + a_val
                neg_base[key_a] += a_val
            actual_rows["x"].append(key_a)
            actual_rows["bottom"].append(a_bot)
            actual_rows["top"].append(a_top)
            actual_rows["color"].append(color)
            actual_rows["tech"].append(cat)
            actual_rows["value"].append(a_val)
            actual_rows["subtitle"].append(f"Region {r}")
            actual_rows["unit"].append(unit)

            # Predicted slice
            key_p = (r, "Predicted")
            if p_val >= 0:
                p_bot, p_top = pos_base[key_p], pos_base[key_p] + p_val
                pos_base[key_p] += p_val
            else:
                p_top, p_bot = neg_base[key_p], neg_base[key_p] + p_val
                neg_base[key_p] += p_val
            pred_rows["x"].append(key_p)
            pred_rows["bottom"].append(p_bot)
            pred_rows["top"].append(p_top)
            pred_rows["color"].append(color)
            pred_rows["tech"].append(cat)
            pred_rows["value"].append(p_val)
            pred_rows["ci_half"].append(half_val)
            pred_rows["ci_lo"].append(p_val - half_val)
            pred_rows["ci_hi"].append(p_val + half_val)
            pred_rows["subtitle"].append(f"Region {r}")
            pred_rows["unit"].append(unit)
        legend_pairs.append((cat, color))

    bars_actual_source.data = actual_rows
    bars_pred_source.data = pred_rows
    legend_div.text = _build_legend_html(legend_pairs)
    ymax = max(pos_base.values()) if pos_base else 1.0
    ymin = min(neg_base.values()) if neg_base else 0.0
    plot.y_range.update(
        start=(ymin * 1.15) if ymin < 0 else 0,
        end=ymax * 1.15 if ymax > 0 else 1.0,
    )
    plot.title.text = (
        f"{spec['title_noun']} by region "
        f"({len(regions)} regions, {unit}, 2050)"
    )
    return True


def _render_diff_panel(
    actual_raw: pd.Series, pred_raw: pd.Series,
    is_regional: bool,
) -> None:
    """Update the diff panel: one stacked bar per x-tick, colored by tech.

    Each tech contributes its (predicted − actual) slice to a stack at the
    x-tick. Positive slices stack ABOVE zero, negative slices stack BELOW
    zero, so the visible height of the stack matches the magnitude of
    over/under-prediction by tech (matching the tech colors in the main
    legend on the right). A black dot at each x-tick marks the NET total
    diff at that tick.

    Layer behavior:
      * Overall  – one stack labelled "System".
      * Regional – one stack per region (p60, p61, …), plus a separate
        "Total" tick at the right edge whose black dot is the system-wide
        net error (sum of per-region totals).
    """
    spec = _active_spec()
    scale = spec["scale"]
    unit = spec["axis_label"].split("(")[-1].rstrip(")")
    diff_plot.yaxis.axis_label = f"Error ({unit})"

    has_actual = actual_raw is not None and not actual_raw.empty
    if not has_actual:
        diff_source.data = dict(
            x=[], bottom=[], top=[], color=[], tech=[],
            value=[], subtitle=[], unit=[],
        )
        diff_total_source.data = dict(x=[], y=[], subtitle=[], unit=[])
        # x_range is shared with the main plot, which manages it.
        # Sync width with main plot so this empty panel still takes the
        # right amount of horizontal real estate in regional view.
        if diff_plot.width != plot.width:
            diff_plot.width = plot.width
        diff_plot.y_range.update(start=-1.0, end=1.0)
        diff_plot.title.text = "Prediction error (predicted − actual)  [no actual data]"
        return

    # Build (x, tech) -> diff matrix in display units.
    if is_regional:
        actual_df = spec["agg_regional"](actual_raw)
        pred_df = (
            spec["agg_regional"](pred_raw)
            if pred_raw is not None and not pred_raw.empty
            else pd.DataFrame()
        )
        regions = sorted(
            set(actual_df.index) | set(pred_df.index),
            key=lambda r: (r[:1], int(r[1:])) if r[1:].isdigit() else (r, 0),
        )
        cats = spec["order"](set(actual_df.columns) | set(pred_df.columns))
        diff_at: dict[tuple[str, str], float] = {}
        for r in regions:
            for c in cats:
                a = (
                    float(actual_df.loc[r, c]) if (
                        r in actual_df.index and c in actual_df.columns
                    ) else 0.0
                )
                p = (
                    float(pred_df.loc[r, c]) if (
                        r in pred_df.index and c in pred_df.columns
                    ) else 0.0
                )
                diff_at[(r, c)] = (p - a) * scale
        # Two parallel lists:
        #   x_keys   = lookup key into diff_at (region string)
        #   x_factors = where the bar/dot is drawn on the SHARED x-axis,
        #               i.e. under the main plot's Predicted column for
        #               this region.
        x_keys = list(regions)
        x_factors = [(r, "Predicted") for r in regions]
    else:
        actual_agg = spec["agg_system"](actual_raw)
        pred_agg = (
            spec["agg_system"](pred_raw)
            if pred_raw is not None and not pred_raw.empty
            else pd.Series(dtype=float)
        )
        cats = spec["order"](set(actual_agg.index) | set(pred_agg.index))
        diff_at = {
            ("System", c): (
                float(pred_agg.get(c, 0.0)) - float(actual_agg.get(c, 0.0))
            ) * scale
            for c in cats
        }
        # Overall view: same idea — lookup by "System", draw under the main
        # plot's "Predicted" column so width / position match the UQ panel.
        x_keys = ["System"]
        x_factors = ["Predicted"]

    threshold = 1e-3
    cats = [
        c for c in cats
        if any(abs(diff_at.get((k, c), 0.0)) > threshold for k in x_keys)
    ]

    xs: list = []
    bottoms: list[float] = []
    tops: list[float] = []
    colors: list[str] = []
    techs: list[str] = []
    values: list[float] = []
    subtitles: list[str] = []
    units: list[str] = []
    totals: dict = {}
    total_subtitles: dict = {}
    for x_key, x_factor in zip(x_keys, x_factors):
        pos_base = 0.0
        neg_base = 0.0
        total = 0.0
        # Subtitle shown in the hover for slices/dots at this x position.
        subtitle = f"Region {x_key}" if is_regional else "System"
        for cat in cats:
            val = diff_at.get((x_key, cat), 0.0)
            total += val
            if val == 0:
                continue
            if val > 0:
                bot = pos_base
                top = pos_base + val
                pos_base = top
            else:
                top = neg_base
                bot = neg_base + val
                neg_base = bot
            xs.append(x_factor)
            bottoms.append(bot)
            tops.append(top)
            colors.append(spec["color"](cat))
            techs.append(cat)
            values.append(val)
            subtitles.append(subtitle)
            units.append(unit)
        totals[x_factor] = total
        total_subtitles[x_factor] = subtitle

    system_total = float(sum(totals.values()))
    total_xs: list = list(x_factors)
    total_ys: list[float] = [totals[xf] for xf in x_factors]
    total_subs: list[str] = [total_subtitles[xf] for xf in x_factors]
    total_units: list[str] = [unit] * len(x_factors)

    diff_source.data = dict(
        x=xs, bottom=bottoms, top=tops, color=colors, tech=techs,
        value=values, subtitle=subtitles, unit=units,
    )
    diff_total_source.data = dict(
        x=total_xs, y=total_ys, subtitle=total_subs, unit=total_units,
    )
    # x_range is shared with the main plot — do NOT overwrite its factors
    # here. We DO need to sync diff_plot.width with the main plot, because
    # ``_render_regional_bars`` grows ``plot.width`` based on the number of
    # factors so wide bars stay readable; without this sync the diff plot
    # stays at the original construction width and looks much narrower.
    if diff_plot.width != plot.width:
        diff_plot.width = plot.width
    if is_regional:
        diff_plot.title.text = (
            f"Regional prediction error  (system total = {system_total:+.2f} {unit})"
        )
    else:
        diff_plot.title.text = (
            f"Prediction error  (total = {system_total:+.2f} {unit})"
        )

    all_y = bottoms + tops + total_ys + [0.0]
    if not all_y:
        diff_plot.y_range.update(start=-1.0, end=1.0)
        return
    ymax = max(all_y)
    ymin = min(all_y)
    pad = max((ymax - ymin) * 0.10, 1e-6)
    diff_plot.y_range.update(start=ymin - pad, end=ymax + pad)


def _render_uq_panel(
    actual_raw: pd.Series, pred_raw: pd.Series,
    artifact: dict | None,
    is_regional: bool,
) -> None:
    """Update the UQ panel: stacked Predicted bar coloured by per-tech CI%.

    Mirrors the main plot's Predicted stack exactly (shared x_range, same
    tech slice heights), but instead of using tech colours each slice is
    coloured by its OWN relative uncertainty:

        slice colour <- (90% CI half-width for this tech)
                        / |predicted value for this tech| * 100%

    mapped through the green->yellow->red colorbar on the right. Hover any
    slice for tech name, predicted value, CI bounds, and the exact CI%.
    """
    spec = _active_spec()
    scale = spec["scale"]
    unit = spec["axis_label"].split("(")[-1].rstrip(")")
    uq_plot.yaxis.axis_label = spec["axis_label"]

    def _empty(reason: str = "no data") -> None:
        uq_source.data = dict(
            x=[], bottom=[], top=[], ci_pct=[], tech=[],
            pred=[], half=[], ci_lo=[], ci_hi=[], subtitle=[], unit=[],
        )
        uq_plot.y_range.update(start=0, end=1.0)
        uq_plot.title.text = f"Predicted stack coloured by 90% CI / |value| %  [{reason}]"

    if pred_raw is None or pred_raw.empty:
        _empty("no prediction")
        return

    half_agg = _half_agg_for_view(artifact, spec, is_regional=is_regional)
    no_uq = (
        (is_regional and (not isinstance(half_agg, pd.DataFrame) or half_agg.empty))
        or (not is_regional and (not isinstance(half_agg, pd.Series) or half_agg.empty))
    )
    if no_uq:
        _empty("no UQ available")
        return

    rows: dict[str, list] = dict(
        x=[], bottom=[], top=[], ci_pct=[], tech=[],
        pred=[], half=[], ci_lo=[], ci_hi=[], subtitle=[], unit=[],
    )
    threshold = 1e-3

    def _push(x_key, cat, pred_val, half_val, pos_base, neg_base, subtitle):
        """Append one stacked slice; returns updated (pos_base, neg_base)."""
        if abs(pred_val) <= threshold and abs(half_val) <= threshold:
            return pos_base, neg_base
        if pred_val >= 0:
            bot, top = pos_base, pos_base + pred_val
            pos_base = top
        else:
            top, bot = neg_base, neg_base + pred_val
            neg_base = bot
        # CI% relative to |value|. No clipping: 0-50% gets the green->
        # yellow->red gradient via the LinearColorMapper, >50% gets the
        # mapper's high_color (solid black) so outliers are visible but
        # don't flatten the gradient. For pred ~= 0 with non-zero CI we
        # have effectively infinite relative uncertainty -> assign a
        # large finite sentinel so the slice is coloured black and the
        # hover formatter still produces a readable number.
        if abs(pred_val) > threshold:
            pct = half_val / abs(pred_val) * 100.0
        else:
            pct = 999.0
        rows["x"].append(x_key)
        rows["bottom"].append(bot)
        rows["top"].append(top)
        rows["ci_pct"].append(pct)
        rows["tech"].append(cat)
        rows["pred"].append(pred_val)
        rows["half"].append(half_val)
        rows["ci_lo"].append(pred_val - half_val)
        rows["ci_hi"].append(pred_val + half_val)
        rows["subtitle"].append(subtitle)
        rows["unit"].append(unit)
        return pos_base, neg_base

    if is_regional:
        pred_tr = spec["agg_regional"](pred_raw)
        regions = sorted(
            set(pred_tr.index),
            key=lambda r: (r[:1], int(r[1:])) if r[1:].isdigit() else (r, 0),
        )
        cats = spec["order"](set(pred_tr.columns))
        cats = [
            c for c in cats
            if c in pred_tr.columns and abs(float(pred_tr[c].sum())) * scale > threshold
        ]
        for r in regions:
            pos_base = 0.0
            neg_base = 0.0
            for cat in cats:
                pred_val = (
                    float(pred_tr.loc[r, cat]) * scale
                    if r in pred_tr.index and cat in pred_tr.columns else 0.0
                )
                half_val = (
                    float(half_agg.loc[r, cat]) * scale
                    if isinstance(half_agg, pd.DataFrame)
                    and r in half_agg.index and cat in half_agg.columns else 0.0
                )
                pos_base, neg_base = _push(
                    (r, "Predicted"), cat, pred_val, half_val,
                    pos_base, neg_base, f"Region {r}",
                )
    else:
        pred_agg = spec["agg_system"](pred_raw)
        cats = spec["order"](set(pred_agg.index))
        cats = [
            c for c in cats
            if abs(float(pred_agg.get(c, 0.0))) * scale > threshold
        ]
        pos_base = 0.0
        neg_base = 0.0
        for cat in cats:
            pred_val = float(pred_agg.get(cat, 0.0)) * scale
            half_val = (
                float(half_agg.get(cat, 0.0)) * scale
                if isinstance(half_agg, pd.Series) else 0.0
            )
            pos_base, neg_base = _push(
                "Predicted", cat, pred_val, half_val,
                pos_base, neg_base, "System",
            )

    if not rows["x"]:
        _empty("no rows")
        return

    uq_source.data = rows
    if uq_plot.width != plot.width:
        uq_plot.width = plot.width

    ymax = max(rows["top"] + [0.0])
    ymin = min(rows["bottom"] + [0.0])
    pad = max((ymax - ymin) * 0.10, 1e-6)
    uq_plot.y_range.update(
        start=ymin - pad if ymin < 0 else 0,
        end=ymax + pad,
    )
    uq_plot.title.text = "Predicted stack coloured by 90% CI / |value| (%)"

def _tol_color(pct_err: float, good: float, warn: float) -> str:
    """Green / amber / red CSS color based on |pct_err|."""
    if not np.isfinite(pct_err):
        return "#777"
    a = abs(pct_err)
    if a <= good:
        return "#0a7a0a"
    if a <= warn:
        return "#c08000"
    return "#b00020"


def _format_metrics(
    levels: dict[str, str],
    artifact: dict | None,
    actual_row: pd.Series | None,
    predicted: pd.Series,
    surrogate_ms: float | None = None,
) -> str:
    lines = []
    lines.append(f"<b>Design point:</b> "
                 + ", ".join(f"{d}={v}" for d, v in levels.items()))
    if artifact is not None:
        lines.append(
            f"<b>Model:</b> {artifact.get('display_name', '?')} "
            f"(OOF R² mean = {artifact.get('oof_r2_mean', float('nan')):.3f}, "
            f"median = {artifact.get('oof_r2_median', float('nan')):.3f})"
        )
        lines.append(f"<b>Trained on:</b> {artifact.get('n_samples', '?')} runs "
                     f"({artifact.get('cv_type', '?')})")
    if actual_row is None:
        if surrogate_ms is not None:
            lines.append(
                f"<b>Surrogate runtime:</b> {surrogate_ms:.1f} ms "
                f"(ReEDS reference: ~30–60 min &rArr; <b>~{30*60_000/max(surrogate_ms,1):,.0f}&times; speedup</b>)"
            )
        lines.append("<i>No training run matches this exact design — "
                     "showing surrogate prediction only.</i>")
        return "<br/>".join(lines)

    # Numeric comparison of totals
    def _sum(prefix: str, series_or_row, columns=None):
        if columns is None:
            cols = [c for c in series_or_row.index
                    if isinstance(c, str) and c.startswith(prefix)]
        else:
            cols = [c for c in columns if c.startswith(prefix)]
        if not cols:
            return float("nan")
        return float(series_or_row[cols].astype(float).sum())

    actual_cap = _sum("cap_", actual_row) / 1e3
    pred_cap = _sum("cap_", predicted) / 1e3
    cap_err = (pred_cap - actual_cap) / actual_cap * 100 if actual_cap else float("nan")

    actual_cost = _sum("cost_total", actual_row)
    if np.isnan(actual_cost):
        actual_cost = _sum("cost_", actual_row)
    pred_cost = float(predicted.get("cost_total", float("nan")))
    if np.isnan(pred_cost):
        pred_cost = _sum("cost_", predicted)

    runtime_actual = float(actual_row.get("runtime_seconds", float("nan")))

    # ---- Conformal half-width on the *summed* capacity total, in GW ----
    cap_ci_gw = float("nan")
    if artifact is not None and predicted is not None and not predicted.empty:
        try:
            half = conformal_widths(artifact, alpha=CONFORMAL_ALPHA)  # per-output
            y_cols = list(artifact.get("y_cols", []))
            cap_idx = [i for i, c in enumerate(y_cols) if c.startswith("cap_")]
            if cap_idx:
                # Conservative joint band: sum of marginal half-widths (Bonferroni).
                cap_ci_gw = float(np.asarray(half)[cap_idx].sum()) / 1e3
        except Exception:  # noqa: BLE001 — UQ is best-effort
            cap_ci_gw = float("nan")

    cap_color = _tol_color(cap_err, CAP_TOL_GOOD, CAP_TOL_WARN)
    cap_line = (
        f"<b>Total capacity:</b> actual {actual_cap:,.1f} GW vs predicted {pred_cap:,.1f} GW "
        f"(<span style='color:{cap_color}'><b>{cap_err:+.1f}%</b></span> error"
    )
    if np.isfinite(cap_ci_gw):
        cap_line += f", &plusmn;{cap_ci_gw:.1f} GW 90% CI"
    cap_line += f"; tol &plusmn;{CAP_TOL_GOOD:.0f}%)"
    lines.append(cap_line)

    if not np.isnan(actual_cost) and not np.isnan(pred_cost):
        cost_err = (pred_cost - actual_cost) / actual_cost * 100 if actual_cost else float("nan")
        cost_color = _tol_color(cost_err, COST_TOL_GOOD, COST_TOL_WARN)
        lines.append(
            f"<b>System cost:</b> actual ${actual_cost/1e9:,.2f} B vs "
            f"predicted ${pred_cost/1e9:,.2f} B "
            f"(<span style='color:{cost_color}'><b>{cost_err:+.1f}%</b></span> error; "
            f"tol &plusmn;{COST_TOL_GOOD:.0f}%)"
        )

    if not np.isnan(runtime_actual) and surrogate_ms is not None and surrogate_ms > 0:
        speedup = runtime_actual * 1000.0 / surrogate_ms
        lines.append(
            f"<b>Runtime:</b> ReEDS {runtime_actual/60:,.1f} min vs surrogate "
            f"{surrogate_ms:.1f} ms &rArr; <b>{speedup:,.0f}&times; speedup</b>"
        )
    elif not np.isnan(runtime_actual):
        lines.append(f"<b>Actual ReEDS runtime:</b> {runtime_actual/60:,.1f} min")
    elif surrogate_ms is not None:
        lines.append(
            f"<b>Surrogate runtime:</b> {surrogate_ms:.1f} ms "
            f"(ReEDS reference: ~30–60 min)"
        )

    return "<br/>".join(lines)


def _is_regional_layout(cap_index) -> bool:
    """Return True if any ``cap_*`` name carries a region suffix (Stage-2)."""
    if cap_index is None or len(cap_index) == 0:
        return False
    df = aggregate_cap_to_tech_region(
        pd.Series(0.0, index=list(cap_index)), tech_map_df=TECH_MAP_DF,
    )
    return not df.empty


def _redraw():
    levels = {dim: design_selects[dim].value for dim in DIMENSION_ENCODING}
    model_name = model_select.value
    artifact = _get_artifact(model_name) if model_name else None

    actual_row = _find_actual_row(levels)
    # Always probe cap_* for the regional-layout detection — capacity columns
    # use the same `_<region>` suffix convention as the other families.
    actual_cap_raw = _row_to_cap_series(actual_row)

    # Slice for the active variable.
    active_prefix = _active_spec()["prefix"]
    actual_var_raw = _row_slice(actual_row, active_prefix)

    surrogate_ms: float | None = None
    predicted = pd.Series(dtype=float)
    pred_var_raw = pd.Series(dtype=float)
    pred_cap_raw = pd.Series(dtype=float)
    if artifact is None:
        status_div.text = ("<b style='color:#a00'>No trained model artifacts found.</b> "
                           "Run <code>python surrogate_ml_models.py</code> first.")
    else:
        t0 = time.perf_counter()
        # ---- Honest prediction policy --------------------------------------
        # If the picked design matches a training row, show the OOF (k-fold)
        # prediction — the model trained on the 9/10 of data that EXCLUDES
        # this case. Otherwise the final-model prediction (trained on all
        # 486 samples) would partially memorize the training case (KNN with
        # distance weighting hits it exactly), making Actual vs Predicted
        # look misleadingly perfect.
        # For custom / out-of-sample designs we fall back to the final model.
        used_oof = False
        oof_residuals = artifact.get("oof_residuals")
        if (actual_row is not None
                and oof_residuals is not None
                and isinstance(actual_row.name, (int, np.integer))
                and 0 <= int(actual_row.name) < oof_residuals.shape[0]):
            row_idx = int(actual_row.name)
            y_cols = artifact["y_cols"]
            actual_vec = actual_row.reindex(y_cols).astype(float).values
            oof_pred_vec = actual_vec - oof_residuals[row_idx]
            predicted = pd.Series(oof_pred_vec, index=y_cols, name="prediction_oof")
            # Apply the same physical-bound clipping used by predict() so
            # OOF and final-model paths produce comparable, plausible bars.
            predicted = clip_physical_bounds(predicted)
            used_oof = True
        else:
            predicted = predict(artifact, levels)
        # Splice in known-constant outputs the trainer dropped (zero
        # variance \u2192 R\u00b2 undefined / scaler divides by zero). Without
        # this, the Predicted bar misses things like cap_distpv that the
        # Actual bar shows, even though the value is known exactly.
        predicted = _augment_predicted_with_constants(
            predicted, _active_layer_short()
        )
        # STAGE 2: after augmenting with the trainer's constant_outputs
        # (which pinned cap_distpv at its Stage 1 mean), replace the DistPV
        # capacity with the demand-elasticity dgen curve so continuous
        # x_Dem values actually move the bar.
        if "cap_distpv" in predicted.index:
            dem_val = levels.get("Dem")
            if isinstance(dem_val, (int, float)) and not isinstance(dem_val, bool):
                predicted = predicted.copy()
                predicted["cap_distpv"] = dgen_distpv_cap_mw(float(dem_val))
        surrogate_ms = (time.perf_counter() - t0) * 1000.0
        pred_var_raw = _row_slice(predicted, active_prefix)
        pred_cap_raw = _row_slice(predicted, "cap_")
        if actual_row is None:
            status_div.text = ("<b style='color:#a60'>This exact design isn't in the training "
                               "data — showing the surrogate prediction only.</b>")
        elif used_oof:
            status_div.text = (
                f"<b style='color:#060'>Matched training run:</b> "
                f"<code>{actual_row.get('case_name', '(no case_name col)')}</code>"
                f" &nbsp;<span style='color:#555'>"
                f"(showing <b>k-fold OOF</b> prediction — the model trained on the "
                f"9/10 of cases that <i>excludes</i> this one)</span>"
            )
        else:
            status_div.text = (
                f"<b style='color:#060'>Matched training run:</b> "
                f"<code>{actual_row.get('case_name', '(no case_name col)')}</code>"
                f" &nbsp;<span style='color:#a60'>"
                f"(no OOF stored; showing final-model prediction — may overfit)</span>"
            )

    # Reset bar-source data (the vbar renderers + hover tools stay registered
    # across redraws — we just swap the data they're bound to).
    bars_actual_source.data = _empty_actual_bars_data()
    bars_pred_source.data = _empty_pred_bars_data()
    legend_div.text = ""

    # Decide layout from capacity columns, which are present in every dataset.
    combined_cap_index = list(set(actual_cap_raw.index) | set(pred_cap_raw.index))
    is_regional = _is_regional_layout(combined_cap_index)

    if is_regional:
        drew = _render_regional_bars(actual_var_raw, pred_var_raw, levels, True, artifact)
    else:
        drew = _render_system_bars(actual_var_raw, pred_var_raw, levels, True, artifact)

    if not drew:
        spec = _active_spec()
        plot.title.text = f"{spec['title_noun']} ({spec['axis_label']}) — no data"
        # No glyphs to scale against — collapse the axis to a neutral range.
        plot.y_range.update(start=0, end=1.0)

    _render_diff_panel(actual_var_raw, pred_var_raw, is_regional)
    _render_uq_panel(actual_var_raw, pred_var_raw, artifact, is_regional)

    metrics_div.text = _format_metrics(
        levels, artifact, actual_row, predicted, surrogate_ms=surrogate_ms,
    )


def _on_change(_attr, _old, _new):
    _redraw()


for sel in design_selects.values():
    sel.on_change("value", _on_change)
model_select.on_change("value", _on_change)
variable_select.on_change("value", _on_change)


# ---------------------------------------------------------------------------
# Evaluation tab — comparison table, OOF plots, per-output detail
# ---------------------------------------------------------------------------

def _load_summary() -> dict:
    p = RESULTS_DIR / "summary.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001 - best-effort load
        return {}


SUMMARY: dict = _load_summary()


def _img_html(rel_name: str) -> str:
    """Return an <img> tag with the named PNG inlined as base64, or a placeholder."""
    p = RESULTS_DIR / rel_name
    if not p.exists():
        return f"<i>{rel_name}: not found in {RESULTS_DIR}</i>"
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return (
        f"<img src='data:image/png;base64,{b64}' "
        f"style='max-width:100%;height:auto;border:1px solid #ddd;padding:4px'/>"
    )


def _img_div(rel_name: str, width: int = 900) -> Div:
    return Div(text=_img_html(rel_name), width=width)


def _distfid_by_catalog_html() -> str:
    """Render the by-catalog distributional fidelity summary (P3b).

    Reads ``eval/distribution_fidelity_by_catalog.csv`` from the active
    layer and produces a small HTML table + the matching PNG. Returns a
    helpful note when the artefacts are absent so the panel never breaks
    the eval tab.
    """
    # Local label map — keeps this helper independent of the global
    # ``_CATALOG_LABELS`` dict (which is defined further down in the file
    # and is therefore unavailable at module-load time when this helper
    # is first called for the initial Div text).
    _LBL = {"cap": "Capacity", "gen": "Generation",
            "cost": "System cost", "tran": "Transmission",
            "misc": "Misc"}
    csv = RESULTS_DIR / "eval" / "distribution_fidelity_by_catalog.csv"
    png_rel = "eval/figs/distribution_fidelity_by_catalog.png"
    if not csv.exists():
        return (
            "<p style='color:#a60;font-size:12px;margin:4px 0'>"
            "<code>eval/distribution_fidelity_by_catalog.csv</code> not "
            "found — re-run <code>python surrogate_eval.py</code> on this "
            "layer to populate.</p>"
        )
    try:
        df = pd.read_csv(csv)
    except Exception as exc:  # noqa: BLE001
        return (
            f"<p style='color:#c33;font-size:12px;margin:4px 0'>"
            f"Could not read distribution_fidelity_by_catalog.csv: {exc}</p>"
        )
    if df.empty:
        return "<p style='color:#888;font-size:12px'>No catalogs available.</p>"

    # Order canonically.
    order = ["cap", "gen", "cost", "tran", "misc"]
    df["category"] = df["category"].astype(str)
    df = (df.set_index("category")
            .reindex([c for c in order if c in df["category"].values])
            .reset_index())

    rows: list[str] = []
    for _, row in df.iterrows():
        cat = str(row.get("category", "?"))
        std_r = row.get("median_std_ratio")
        sp = row.get("median_spearman")
        n = row.get("n_outputs")
        std_str = (f"{float(std_r):.3f}" if pd.notna(std_r) else "—")
        sp_str = (f"{float(sp):.3f}" if pd.notna(sp) else "—")
        n_str = (f"{int(n)}" if pd.notna(n) else "—")
        # Colour-code std_ratio: red if < 0.7, amber 0.7-0.9, green ≥ 0.9.
        try:
            v = float(std_r)
            if v >= 0.9:
                clr = "#1a7f37"  # green
            elif v >= 0.7:
                clr = "#bf8700"  # amber
            else:
                clr = "#cf222e"  # red
            std_html = f"<span style='color:{clr};font-weight:bold'>{std_str}</span>"
        except (TypeError, ValueError):
            std_html = std_str
        rows.append(
            f"<tr>"
            f"<td style='padding:4px 8px;font-weight:bold'>"
            f"{_LBL.get(cat, cat.title())}</td>"
            f"<td style='padding:4px 8px;text-align:right'>{std_html}</td>"
            f"<td style='padding:4px 8px;text-align:right'>{sp_str}</td>"
            f"<td style='padding:4px 8px;text-align:right;color:#888'>{n_str}</td>"
            f"</tr>"
        )
    head_model = (
        df.iloc[0]["model"] if "model" in df.columns and len(df) else "?"
    )
    table_html = (
        "<style>"
        ".dfid-tbl{border-collapse:collapse;font-size:13px;margin:6px 0}"
        ".dfid-tbl th,.dfid-tbl td{border:1px solid #bbb}"
        ".dfid-tbl th{background:#eef;text-align:center;padding:4px 8px}"
        "</style>"
        "<table class='dfid-tbl'>"
        "<thead><tr>"
        "<th>Catalog</th>"
        "<th>Median std(pred)/std(actual)</th>"
        "<th>Median Spearman</th>"
        "<th># outputs</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        f"<p style='color:#888;font-size:11px;margin:0 0 6px 0'>"
        f"Headline model: <code>{head_model}</code>. "
        f"Coloured cells: green = good (\u2265 0.9), amber = 0.7-0.9, "
        f"red = compression (&lt; 0.7).</p>"
    )
    return table_html + _img_html(png_rel)


_SUMMARY_TABLE_BANNER = {
    "overall":  ("#1f77b4", "Overall layer (system-level outputs, ~66 outputs) — "
                            "fixed reference; used to pick the top-2 methods "
                            "compared in the per-case, per-catalog, and "
                            "Overall-vs-Regional sections below."),
    "regional": ("#d62728", "Regional layer (per-BA outputs, ~308 outputs) — "
                            "shown for comparison. Ranking here can differ from "
                            "Overall; the noisier per-BA targets penalize methods "
                            "differently."),
}

# Weights for the composite ranking score. Designed to balance:
#   - median R² (robust central tendency, insensitive to outlier outputs)
#   - fraction of outputs with R² > 0.9 (task-aligned: "how many usable?")
#   - mean R² (penalizes catastrophic single-output failures)
_COMPOSITE_W_MEDIAN = 0.5
_COMPOSITE_W_USABLE = 0.3   # weight on (n_outputs_r2_above_0.9 / n_y_outputs)
_COMPOSITE_W_MEAN   = 0.2


def _composite_score(m: dict, n_out) -> float:
    """Weighted blend of robust + task-aligned metrics; higher is better.

    score = 0.5·median + 0.3·(R²>0.9 fraction) + 0.2·mean

    Returns NaN if any component is missing / non-finite, so such models sink
    to the bottom of the leaderboard.
    """
    median = m.get("oof_r2_median", float("nan"))
    mean = m.get("oof_r2_mean", float("nan"))
    n_above_09 = m.get("n_outputs_r2_above_0.9", float("nan"))
    try:
        n_out_f = float(n_out)
    except (TypeError, ValueError):
        return float("nan")
    if n_out_f <= 0:
        return float("nan")
    if not (np.isfinite(median) and np.isfinite(mean) and np.isfinite(n_above_09)):
        return float("nan")
    frac_usable = n_above_09 / n_out_f
    return (
        _COMPOSITE_W_MEDIAN * median
        + _COMPOSITE_W_USABLE * frac_usable
        + _COMPOSITE_W_MEAN * mean
    )


def _rank_by_composite(summary: dict | None) -> list[str]:
    """Return model keys sorted by composite score descending (best first).

    NaN scores sink to the bottom; ties are broken by name for determinism.
    """
    if not summary:
        return []
    models = summary.get("models", {})
    n_out = summary.get("config", {}).get("n_y_outputs", 1)
    scores = {k: _composite_score(m, n_out) for k, m in models.items()}

    def _key(k: str) -> tuple:
        v = scores[k]
        if not np.isfinite(v):
            return (1, k)
        return (0, -v, k)
    return sorted(models.keys(), key=_key)


def _rank_by_pooled_r2(layer_short: str) -> list[str]:
    """Return model keys for ``layer_short`` ranked by pooled R² descending.

    Matches the ranking used in the Section 1 leaderboard tables.
    Models whose artifacts fail to load (NaN pooled R²) sink to the bottom;
    ties are broken by name.
    """
    summary = _summary_for_layer(layer_short)
    if not summary:
        return []
    names = list(summary.get("models", {}).keys())
    pooled = {n: _pooled_r2_for_layer_model(layer_short, n) for n in names}

    def _key(n: str) -> tuple:
        v = pooled[n]
        if not np.isfinite(v):
            return (1, n)
        return (0, -v, n)
    return sorted(names, key=_key)


# Weights for the Section 1 leaderboard rank score. Equal weight on
# pooled accuracy and per-output usability — surfaces models that win on
# the bulk of outputs even when a few high-magnitude outputs dominate
# pooled R².
_RANK_W_POOLED = 0.5
_RANK_W_USABLE = 0.5


def _rank_score_for_layer_model(
    layer_short: str,
    model_name: str,
    models_dict: dict | None = None,
    n_out: float | int | str | None = None,
) -> float:
    """Weighted leaderboard score for one (layer, model) pair.

    ``score = w_pooled · pooled_r2  +  w_usable · (n_outputs_r2_above_0.9 / n_y_outputs)``

    Returns NaN if either component is missing / non-finite (so the model
    sinks to the bottom of the leaderboard).
    """
    if models_dict is None or n_out is None:
        summary = _summary_for_layer(layer_short)
        if not summary:
            return float("nan")
        models_dict = summary.get("models", {})
        n_out = summary.get("config", {}).get("n_y_outputs", 1)
    m = models_dict.get(model_name, {}) if models_dict else {}
    pooled = _pooled_r2_for_layer_model(layer_short, model_name)
    n_good = m.get("n_outputs_r2_above_0.9")
    try:
        n_out_f = float(n_out)
    except (TypeError, ValueError):
        return float("nan")
    if not (np.isfinite(pooled)
            and isinstance(n_good, (int, float))
            and n_out_f > 0):
        return float("nan")
    good_frac = float(n_good) / n_out_f
    return _RANK_W_POOLED * pooled + _RANK_W_USABLE * good_frac


def _rank_by_score(layer_short: str) -> list[str]:
    """Return model keys for ``layer_short`` ranked by leaderboard Score.

    Score = ``_RANK_W_POOLED · pooled_r2 + _RANK_W_USABLE · good_frac``,
    where ``good_frac = n_outputs_r2_above_0.9 / n_y_outputs``.
    NaN scores sink to the bottom; ties are broken by name.
    """
    summary = _summary_for_layer(layer_short)
    if not summary:
        return []
    models_dict = summary.get("models", {})
    n_out = summary.get("config", {}).get("n_y_outputs", 1)
    names = list(models_dict.keys())
    scores = {n: _rank_score_for_layer_model(layer_short, n, models_dict, n_out)
              for n in names}

    def _key(n: str) -> tuple:
        v = scores[n]
        if not np.isfinite(v):
            return (1, n)
        return (0, -v, n)
    return sorted(names, key=_key)


# (P2c) Top-N methods used by §4 (per-catalog) and §5 (cross-layer).
# Default 6; can be overridden by setting SURROGATE_N_METHODS_COMPARE in
# the environment (kept as an env var rather than CLI to avoid threading
# new flags through the bokeh launcher).
N_METHODS_COMPARE: int = max(2, int(os.environ.get("SURROGATE_N_METHODS_COMPARE", 6)))


def _rank_by_honest_r0(layer_short: str) -> list[str]:
    """Return model keys ranked by §R0 honest mean R² for ``layer_short``.

    Reads ``model_ranking_bootstrap.csv`` (written by ``surrogate_eval.py``)
    and sorts by ``r2_mean_boot_mean`` descending. This is the "paper"
    ranking — per-output R² averaged with bootstrap CIs — and avoids the
    pooled-R² inflation discussed in §1's de-emphasis note.

    Falls back to ``_rank_by_score`` when the CSV is missing.
    """
    res_dir, _, _ = _layer_paths(layer_short)
    if res_dir is None:
        return _rank_by_score(layer_short)
    csv = res_dir / "eval" / "model_ranking_bootstrap.csv"
    if not csv.exists():
        return _rank_by_score(layer_short)
    try:
        df = pd.read_csv(csv)
    except Exception:  # noqa: BLE001
        return _rank_by_score(layer_short)
    if "model" not in df.columns or "r2_mean_boot_mean" not in df.columns:
        return _rank_by_score(layer_short)
    df = df.copy().sort_values(
        "r2_mean_boot_mean", ascending=False, kind="stable",
    )
    return [str(m) for m in df["model"].tolist()]


def _palette_for_n(n: int) -> list[str]:
    """Stable colour list of length ``n`` for ranked-method bars / dots."""
    if n <= 0:
        return []
    if n <= 10:
        return list(Category10[max(3, n)])[:n]
    # Cycle Category20 for >10 (rarely needed; we cap at the available models).
    pool = list(Category20[20])
    return [pool[i % len(pool)] for i in range(n)]


def _summary_table_html(layer_short: str = "overall") -> str:
    """Render the eval summary table for the requested layer."""
    summary = _summary_for_layer(layer_short)
    label_color, banner_text = _SUMMARY_TABLE_BANNER.get(
        layer_short, ("#444", f"{layer_short} layer."))
    if not summary:
        return (f"<i>summary.json not found for the <b>{layer_short}</b> "
                "layer — run <code>python surrogate_ml_models.py</code> "
                f"with the <code>{layer_short}</code> target to populate.</i>")
    cfg = summary.get("config", {})
    n_out = cfg.get("n_y_outputs", "?")
    models = summary.get("models", {})
    # Paper-readiness sort (P3a):
    #   Primary key   = n_outputs_r2_above_0.9 descending  (per-variable
    #                   usability — the metric we cite in the paper).
    #   Tie-breaker   = composite Score descending.
    #   Final tie     = name ascending (deterministic).
    # Pooled R² is shown for context but de-emphasised — see note line below.
    pooled = {name: _pooled_r2_for_layer_model(layer_short, name)
              for name in models.keys()}
    scores = {name: _rank_score_for_layer_model(layer_short, name, models, n_out)
              for name in models.keys()}

    def _good_count(name: str) -> float:
        v = models[name].get("n_outputs_r2_above_0.9")
        try:
            return float(v) if v is not None else float("nan")
        except (TypeError, ValueError):
            return float("nan")

    good_counts = {name: _good_count(name) for name in models.keys()}

    def _rank_key(name: str) -> tuple:
        g = good_counts[name]
        s = scores[name]
        # NaNs go last (priority bucket 1); finite values are bucket 0.
        if not np.isfinite(g) and not np.isfinite(s):
            return (1, name)
        # Negate so larger sorts first.
        g_sort = -g if np.isfinite(g) else float("inf")
        s_sort = -s if np.isfinite(s) else float("inf")
        return (0, g_sort, s_sort, name)
    ranked_names = sorted(models.keys(), key=_rank_key)
    try:
        n_out_f = float(n_out)
    except (TypeError, ValueError):
        n_out_f = float("nan")
    rows_html = []
    for i, name in enumerate(ranked_names):
        m = models[name]
        rank = i + 1
        prr = pooled[name]
        sc = scores[name]
        n_good = m.get("n_outputs_r2_above_0.9")
        bg = " style='background:#eaffea'" if rank == 1 else ""
        rank_cell = (
            f"<td style='text-align:center;font-weight:bold'>"
            f"{rank}{' &#11088;' if rank == 1 else ''}</td>"
        )
        score_str = f"{sc:.4f}" if np.isfinite(sc) else "—"
        # De-emphasise Pooled R² (P3a): smaller font + grey colour.
        prr_str = (
            f"<span style='color:#888;font-size:11px'>{prr:.4f}</span>"
            if np.isfinite(prr) else "<span style='color:#bbb'>—</span>"
        )
        if isinstance(n_good, (int, float)) and np.isfinite(n_out_f) and n_out_f > 0:
            pct = float(n_good) / n_out_f * 100.0
            # Outputs > 0.9 is now the headline metric — embolden the count.
            good_str = (
                f"<b>{int(n_good)}</b> / {int(n_out_f)} "
                f"<span style='color:#666'>({pct:.0f}%)</span>"
            )
        else:
            good_str = "—"
        rows_html.append(
            f"<tr{bg}>"
            + rank_cell
            + f"<td>{m.get('display_name', name)}</td>"
            f"<td style='text-align:right;font-weight:bold'>{good_str}</td>"
            f"<td style='text-align:right'>{score_str}</td>"
            f"<td style='text-align:right'>{prr_str}</td>"
            f"</tr>"
        )
    style = (
        "<style>"
        ".summ-tbl{border-collapse:collapse;font-size:13px;width:100%;margin:6px 0}"
        ".summ-tbl th,.summ-tbl td{border:1px solid #bbb;padding:6px 8px}"
        ".summ-tbl th{background:#eee;text-align:left}"
        "</style>"
    )
    score_help = (
        f"<span title='Score = {_RANK_W_POOLED}\u00b7Pooled R\u00b2 + "
        f"{_RANK_W_USABLE}\u00b7(Outputs &gt; 0.9 fraction). Tie-breaker on "
        "the leaderboard.'>Score \u24D8</span>"
    )
    r2_help = (
        "<span title='Pooled R² = 1 − SS_res / SS_tot on the flat "
        "(Y_true, Y_pred) array (all cases × outputs concatenated). "
        "Inflated by the largest-magnitude outputs; shown here for "
        "context only. The paper-quoted metric is the per-output mean / "
        "median R² with bootstrap CIs in §R0.'>Pooled R² \u24D8</span>"
    )
    good_help = (
        "<span title='Number of outputs (and percent) with per-output "
        "R² > 0.9. Headline ranking metric: a model that gets MORE "
        "individual variables right is more useful, even if a few "
        "high-magnitude outputs drag pooled R\u00b2 down.'>"
        "Outputs &gt; 0.9 \u24D8</span>"
    )
    return (
        style
        + f"<p style='margin:0 0 4px 0;color:{label_color};font-weight:bold'>"
        f"{banner_text}</p>"
        + f"<p style='margin:0 0 4px 0;font-size:12px;color:#555'>"
        f"<b>{cfg.get('n_samples', '?')}</b> cases &times; "
        f"<b>{cfg.get('n_x_features', '?')}</b> design dims &rarr; "
        f"<b>{n_out}</b> outputs &middot; "
        f"<i>{cfg.get('cv_type', '?')}</i>. "
        f"Ranked by <b>Outputs &gt; 0.9</b> (paper metric); "
        f"<b>Score</b> breaks ties."
        f"</p>"
        + f"<p style='margin:0 0 4px 0;font-size:11px;color:#888;"
          f"font-style:italic'>"
        + "Pooled R² is inflated by high-magnitude outputs; see <b>\u00a7R0</b> "
          "for the per-variable ranking used in the paper."
        + "</p>"
        + "<table class='summ-tbl'>"
        + "<thead><tr><th style='text-align:center'>#</th>"
        + "<th>Model</th>"
        + f"<th style='text-align:right'>{good_help}</th>"
        + f"<th style='text-align:right'>{score_help}</th>"
        + f"<th style='text-align:right'>{r2_help}</th>"
        + "</tr></thead>"
        + f"<tbody>{''.join(rows_html)}</tbody></table>"
    )


eval_summary_div = Div(text=_summary_table_html("overall"), width=520)
eval_summary_div_regional = Div(
    text=_summary_table_html("regional"), width=520)

# ---------------------------------------------------------------------------
# Eval tab — interactive Bokeh diagnostics
# ---------------------------------------------------------------------------
# Replaces several static matplotlib PNGs with hover-able / zoom-able views
# that directly answer the questions: (1) which model wins, (2) which
# outputs are hard to predict, (3) which techs / regions does the surrogate
# exhibit per-group bias in.
# ---------------------------------------------------------------------------

# Quality buckets used everywhere on the eval tab.
_R2_GOOD = "#2ca02c"
_R2_OK   = "#ff9f00"
_R2_BAD  = "#d62728"
_R2_NA   = "#888888"


def _r2_color(r2: float) -> str:
    """Green / amber / red based on R² quality bucket."""
    if r2 is None or not np.isfinite(r2):
        return _R2_NA
    if r2 >= 0.9:
        return _R2_GOOD
    if r2 >= 0.5:
        return _R2_OK
    return _R2_BAD


def _parse_output_name(output: str) -> tuple[str | None, str | None, str | None]:
    """Parse output names like ``cap_upv_p60`` -> (prefix, tech, region).

    * ``cap_upv``                       -> ("cap", "upv", None)
    * ``cap_CoalOldScr_coal-CCS_mod_p63``-> ("cap", "CoalOldScr_coal-CCS_mod", "p63")
    * ``cost_op_vom_costs_p64``         -> ("cost", "op_vom_costs", "p64")
    * unparseable                       -> (None, output, None)
    """
    if not output:
        return None, None, None
    parts = output.split("_")
    if len(parts) < 2:
        return None, output, None
    prefix = parts[0]
    rest = parts[1:]
    region = None
    if rest and rest[-1].startswith("p") and rest[-1][1:].isdigit():
        region = rest[-1]
        rest = rest[:-1]
    tech = "_".join(rest) if rest else None
    return prefix, tech, region


def _short_model_name(display_name: str) -> str:
    """Strip parenthetical suffix so the x-axis stays readable.

    ``"NGBoost (distributional, UQ-native)"`` -> ``"NGBoost"``.
    """
    if not display_name:
        return display_name
    return display_name.split(" (")[0].strip() or display_name


# ----- (1) Model comparison: grouped (dodged) bars per metric -------------
# One row per model with one column per metric, then four ``vbar`` renderers
# offset with ``dodge`` so the x-axis only carries ONE label per model.
# Metric -> color mapping lives in the legend (click any entry to hide).
MC_METRICS = [
    ("R² mean",     "r2_mean",         "#1f77b4"),
    ("R² median",   "r2_median",       "#ff7f0e"),
    ("frac ≥0.9",   "frac_above_0p9",  "#2ca02c"),
    ("frac ≥0.95",  "frac_above_0p95", "#9467bd"),
]
model_compare_source = ColumnDataSource(data=dict(
    model=[], r2_mean=[], r2_median=[], frac_above_0p9=[], frac_above_0p95=[],
))
model_compare_fig = figure(
    width=900, height=340,
    x_range=FactorRange(),
    y_range=Range1d(start=0, end=1.10),
    title="Model comparison — out-of-fold R² metrics (higher = better)",
    toolbar_location="above",
    tools="box_zoom,xbox_zoom,ybox_zoom,pan,reset,save",
    active_drag="box_zoom",
    y_axis_label="R²  /  fraction of outputs",
)
model_compare_fig.toolbar.logo = None
model_compare_fig.xaxis.major_label_orientation = 0.6
model_compare_fig.xgrid.grid_line_color = None
_mc_bar_w = 0.18  # leaves a small visual gap between groups
for _i, (_label, _col, _color) in enumerate(MC_METRICS):
    _offset = (_i - (len(MC_METRICS) - 1) / 2) * _mc_bar_w
    _r = model_compare_fig.vbar(
        x=dodge("model", _offset, range=model_compare_fig.x_range),
        top=_col, width=_mc_bar_w * 0.95,
        color=_color, source=model_compare_source,
        line_color="white", line_width=0.5,
        legend_label=_label,
    )
    model_compare_fig.add_tools(HoverTool(
        renderers=[_r],
        tooltips=[
            ("Model", "@model"),
            (_label, f"@{_col}{{0.000}}"),
        ],
        point_policy="follow_mouse",
    ))
model_compare_fig.legend.location = "top_right"
model_compare_fig.legend.click_policy = "hide"
model_compare_fig.legend.background_fill_alpha = 0.85
model_compare_fig.legend.label_text_font_size = "10pt"

# ----- (2) Model R² spread: min / median / max -----------------------------
model_range_source = ColumnDataSource(data=dict(
    model=[], r2_min=[], r2_median=[], r2_max=[],
))
model_range_fig = figure(
    width=900, height=340,
    x_range=FactorRange(),
    y_range=Range1d(start=-0.5, end=1.05),
    title="Model R² spread — min / median / max across all outputs "
          "(short bar = consistent, tall bar = uneven across outputs)",
    toolbar_location="above",
    tools="box_zoom,xbox_zoom,ybox_zoom,pan,reset,save",
    active_drag="box_zoom",
    y_axis_label="R²",
)
model_range_fig.toolbar.logo = None
model_range_fig.xaxis.major_label_orientation = 0.6
model_range_fig.xgrid.grid_line_color = None
model_range_fig.segment(
    x0="model", y0="r2_min", x1="model", y1="r2_max",
    source=model_range_source, line_width=10, line_color="#666",
    line_cap="round",
)
_mr_dots = model_range_fig.scatter(
    x="model", y="r2_median", source=model_range_source,
    size=14, marker="diamond", fill_color="#1f77b4", line_color="white",
    line_width=1.5,
)
model_range_fig.add_tools(HoverTool(
    renderers=[_mr_dots],
    tooltips=[
        ("Model", "@model"),
        ("R² min", "@r2_min{0.000}"),
        ("R² median", "@r2_median{0.000}"),
        ("R² max", "@r2_max{0.000}"),
    ],
    point_policy="follow_mouse",
))
for thr, col in ((0.9, _R2_GOOD), (0.5, _R2_OK), (0.0, _R2_BAD)):
    model_range_fig.add_layout(Span(
        location=thr, dimension="width", line_color=col,
        line_dash="dashed", line_width=1, line_alpha=0.7,
    ))

# ----- (3) Per-output R² for the SELECTED model ---------------------------
# Horizontal bars (one per output), sorted ascending so the worst outputs
# sit at the top. With 382 outputs in the regional layer we cap the number
# of bars shown at WORST_N and tell the user how many were trimmed.
EVAL_WORST_N = 60

per_output_bars_source = ColumnDataSource(data=dict(
    output=[], r2=[], color=[], rmse=[], mae=[], nrmse=[],
    prefix=[], tech=[], region=[],
))
per_output_bars_fig = figure(
    width=900, height=600,
    y_range=FactorRange(),
    x_range=Range1d(start=-0.2, end=1.05),
    title="Per-output R² (selected model) — worst at top",
    toolbar_location="above",
    tools="box_zoom,xbox_zoom,ybox_zoom,pan,reset,save",
    active_drag="ybox_zoom",
    x_axis_label="R²",
)
per_output_bars_fig.toolbar.logo = None
per_output_bars_fig.ygrid.grid_line_color = None
_po_bars = per_output_bars_fig.hbar(
    y="output", right="r2", height=0.85,
    color="color", source=per_output_bars_source,
    line_color="white", line_width=0.5,
)
per_output_bars_fig.add_tools(HoverTool(
    renderers=[_po_bars],
    tooltips=[
        ("Output", "@output"),
        ("Prefix / Tech / Region", "@prefix / @tech / @region"),
        ("R²", "@r2{0.000}"),
        ("RMSE", "@rmse{0,0.000}"),
        ("MAE", "@mae{0,0.000}"),
        ("NRMSE", "@nrmse{0.000}"),
    ],
    point_policy="follow_mouse",
))
for thr, col in ((0.9, _R2_GOOD), (0.5, _R2_OK), (0.0, _R2_BAD)):
    per_output_bars_fig.add_layout(Span(
        location=thr, dimension="height", line_color=col,
        line_dash="dashed", line_width=1, line_alpha=0.6,
    ))

# ----- (4) Bias by tech / by region (regional layer only) -----------------
# (P2a) Small-multiples: one panel per output catalog (Capacity, Generation,
# System cost, Transmission). Bars show MEDIAN R² per item — outputs flagged
# as ``mostly_zero`` (deployed in fewer than mostly_zero_threshold of cases)
# are filtered out to keep the chart readable. The panel-level catalog
# detection uses ``_parse_output_name`` on the original column.
PER_TECH_CATALOGS: tuple[tuple[str, str], ...] = (
    ("cap",  "Capacity"),
    ("gen",  "Generation"),
    ("cost", "System cost"),
    ("tran", "Transmission"),
)


def _make_per_tech_subfig(label: str):
    """Return ``(source, fig)`` for one bias-by-item small-multiple.

    The y-range covers ``[-1.0, 1.05]`` because catalogs like
    Capacity often contain low-deployment techs (Nuclear-SMR,
    Pumped-Hydro) whose OOF R² is strongly negative — the previous
    floor of -0.2 hid those bars entirely. Anything below -1.0 is
    clipped to -1.0 in the plotted value (the true R² is still
    surfaced in the hover tooltip via ``r2_actual``).
    """
    src = ColumnDataSource(data=dict(
        item=[], r2_median=[], r2_actual=[], r2_mean=[], n=[], color=[],
    ))
    fig = figure(
        width=440, height=300,
        x_range=FactorRange(),
        y_range=Range1d(start=-1.0, end=1.05),
        title=f"{label} — median R² per item (worst on the left)",
        toolbar_location="above",
        tools="box_zoom,xbox_zoom,ybox_zoom,pan,reset,save",
        active_drag="box_zoom",
        y_axis_label="R² (median; clipped at -1)",
    )
    fig.toolbar.logo = None
    fig.xaxis.major_label_orientation = 0.9
    fig.xgrid.grid_line_color = None
    bars = fig.vbar(
        x="item", top="r2_median", width=0.75,
        color="color", source=src,
        line_color="white", line_width=0.5,
    )
    fig.add_tools(HoverTool(
        renderers=[bars],
        tooltips=[
            ("Item", "@item"),
            ("R² median (true)", "@r2_actual{0.000}"),
            ("R² median (plotted)", "@r2_median{0.000}"),
            ("R² mean", "@r2_mean{0.000}"),
            ("# outputs", "@n"),
        ],
        point_policy="follow_mouse",
    ))
    for thr, col in ((0.9, _R2_GOOD), (0.5, _R2_OK), (0.0, _R2_BAD)):
        fig.add_layout(Span(
            location=thr, dimension="width", line_color=col,
            line_dash="dashed", line_width=1, line_alpha=0.6,
        ))
    return src, fig


per_tech_sources: dict[str, ColumnDataSource] = {}
per_tech_figs: dict[str, "object"] = {}
for _cat, _lbl in PER_TECH_CATALOGS:
    _src, _fig = _make_per_tech_subfig(_lbl)
    per_tech_sources[_cat] = _src
    per_tech_figs[_cat] = _fig

# Backward-compat alias: legacy code paths that referenced per_tech_source /
# per_tech_fig get the Capacity panel (the most-populated catalog).
per_tech_source = per_tech_sources["cap"]
per_tech_fig = per_tech_figs["cap"]

per_region_source = ColumnDataSource(data=dict(
    region=[], r2_mean=[], r2_median=[], r2_actual=[], n=[], color=[],
))
per_region_fig = figure(
    width=900, height=320,
    x_range=FactorRange(),
    y_range=Range1d(start=-1.0, end=1.05),
    title="Median R² per region (regional layer only) — worst on the left",
    toolbar_location="above",
    tools="box_zoom,xbox_zoom,ybox_zoom,pan,reset,save",
    active_drag="box_zoom",
    y_axis_label="R² (median across techs; clipped at -1)",
)
per_region_fig.toolbar.logo = None
per_region_fig.xaxis.major_label_orientation = 0.5
per_region_fig.xgrid.grid_line_color = None
_pr_bars = per_region_fig.vbar(
    x="region", top="r2_median", width=0.75,
    color="color", source=per_region_source,
    line_color="white", line_width=0.5,
)
per_region_fig.add_tools(HoverTool(
    renderers=[_pr_bars],
    tooltips=[
        ("Region", "@region"),
        ("R² median (true)", "@r2_actual{0.000}"),
        ("R² median (plotted)", "@r2_median{0.000}"),
        ("R² mean", "@r2_mean{0.000}"),
        ("# outputs", "@n"),
    ],
    point_policy="follow_mouse",
))
for thr, col in ((0.9, _R2_GOOD), (0.5, _R2_OK), (0.0, _R2_BAD)):
    per_region_fig.add_layout(Span(
        location=thr, dimension="width", line_color=col,
        line_dash="dashed", line_width=1, line_alpha=0.6,
    ))

per_output_summary_div = Div(text="", width=900)


# (P2a / P2b) Layout holders for §3 — built once, populated on each
# stage / layer change. ``bias_by_tech_grid`` is always the 2x2 catalog
# small-multiples; ``bias_by_region_holder`` swaps between the Bokeh
# region figure (Regional layer) and a Div note (Overall layer).
bias_by_tech_grid = gridplot(
    [[per_tech_figs["cap"],  per_tech_figs["gen"]],
     [per_tech_figs["cost"], per_tech_figs["tran"]]],
    toolbar_location="above",
    merge_tools=True,
    sizing_mode=None,
)

_BIAS_REGION_OVERALL_NOTE_HTML = (
    "<div style='background:#fff8e1;border-left:4px solid #f0a050;"
    "padding:10px 14px;margin:6px 0;border-radius:3px;font-size:13px;"
    "line-height:1.5;color:#222;max-width:900px'>"
    "<b>Spatial breakdown is only available on the Regional layer.</b> "
    "Switch the <i>Layer</i> selector at the top of the Predict tab to "
    "<i>Regional (per-BA, ~308 outputs)</i> to populate this panel.</div>"
)

bias_by_region_overall_note = Div(
    text=_BIAS_REGION_OVERALL_NOTE_HTML, width=900,
)
bias_by_region_holder = column(
    bias_by_region_overall_note, sizing_mode=None,
)


def _active_layer_short() -> str:
    """Return ``"overall"`` or ``"regional"`` based on the current
    ``RESULTS_DIR``. Used by P2b to swap the §3 region panel content.
    """
    try:
        name = Path(RESULTS_DIR).name.lower()
    except Exception:  # noqa: BLE001
        return "overall"
    if "regional" in name:
        return "regional"
    return "overall"


def _update_bias_region_holder() -> None:
    """Swap the §3 region panel between figure and note based on layer."""
    if _active_layer_short() == "regional":
        bias_by_region_holder.children = [per_region_fig]
    else:
        bias_by_region_holder.children = [bias_by_region_overall_note]


def _update_model_compare_charts() -> None:
    """Refresh charts (1) from the OVERALL summary (always; stage-independent)."""
    summary = _summary_for_layer("overall")
    models = summary.get("models", {}) if summary else {}
    if not models:
        model_compare_source.data = dict(
            model=[], r2_mean=[], r2_median=[],
            frac_above_0p9=[], frac_above_0p95=[],
        )
        model_range_source.data = dict(
            model=[], r2_min=[], r2_median=[], r2_max=[],
        )
        model_compare_fig.x_range.factors = []
        model_range_fig.x_range.factors = []
        return

    n_out = float(summary.get("config", {}).get("n_y_outputs", 1) or 1)
    # Order models by composite score descending (winner on the left).
    order = _rank_by_composite(summary)
    short_names = [_short_model_name(models[k].get("display_name", k))
                   for k in order]
    # Disambiguate any duplicates that survive the shortening (rare).
    seen: dict[str, int] = {}
    unique_names: list[str] = []
    for n in short_names:
        if n in seen:
            seen[n] += 1
            unique_names.append(f"{n} #{seen[n]}")
        else:
            seen[n] = 1
            unique_names.append(n)
    short_names = unique_names

    def _f(k: str, fld: str) -> float:
        try:
            return float(models[k].get(fld, float("nan")))
        except (TypeError, ValueError):
            return float("nan")

    # ---- chart (1): dodged bars, four metrics per model ----
    model_compare_source.data = dict(
        model=short_names,
        r2_mean=[_f(k, "oof_r2_mean") for k in order],
        r2_median=[_f(k, "oof_r2_median") for k in order],
        frac_above_0p9=[_f(k, "n_outputs_r2_above_0.9") / n_out for k in order],
        frac_above_0p95=[_f(k, "n_outputs_r2_above_0.95") / n_out for k in order],
    )
    model_compare_fig.x_range.factors = short_names

    # ---- chart (2): min / median / max range per model ----
    model_range_source.data = dict(
        model=short_names,
        r2_min=[_f(k, "oof_r2_min") for k in order],
        r2_median=[_f(k, "oof_r2_median") for k in order],
        r2_max=[_f(k, "oof_r2_max") for k in order],
    )
    model_range_fig.x_range.factors = short_names


def _update_per_output_charts(model_name: str) -> None:
    """Refresh charts (3) and (4) from per_output_metrics_<model>.csv."""
    empty_po = dict(
        output=[], r2=[], color=[], rmse=[], mae=[], nrmse=[],
        prefix=[], tech=[], region=[],
    )
    empty_grp_tech = dict(
        item=[], r2_median=[], r2_actual=[], r2_mean=[], n=[], color=[]
    )
    empty_grp_reg = dict(
        region=[], r2_mean=[], r2_median=[], r2_actual=[], n=[], color=[]
    )

    def _clear_all_per_tech():
        for cat, _lbl in PER_TECH_CATALOGS:
            per_tech_sources[cat].data = empty_grp_tech
            per_tech_figs[cat].x_range.factors = []

    if not model_name:
        per_output_bars_source.data = empty_po
        per_output_bars_fig.y_range.factors = []
        _clear_all_per_tech()
        per_region_source.data = empty_grp_reg
        per_region_fig.x_range.factors = []
        per_output_summary_div.text = ""
        return

    csv = RESULTS_DIR / f"per_output_metrics_{model_name}.csv"
    if not csv.exists():
        per_output_bars_source.data = empty_po
        per_output_bars_fig.y_range.factors = []
        _clear_all_per_tech()
        per_region_source.data = empty_grp_reg
        per_region_fig.x_range.factors = []
        per_output_summary_div.text = (
            f"<p style='color:#a60;font-size:12px'>"
            f"<code>per_output_metrics_{model_name}.csv</code> not found in "
            f"<code>{RESULTS_DIR}</code> — retrain to populate per-output detail.</p>"
        )
        return

    df = pd.read_csv(csv)
    # Decorate with parsed prefix / tech / region for the bar hover + agg.
    parsed = df["output"].apply(_parse_output_name)
    df = df.copy()
    df["_prefix"] = [p[0] or "" for p in parsed]
    df["_tech"]   = [p[1] or "" for p in parsed]
    df["_region"] = [p[2] or "" for p in parsed]

    total = len(df)
    n_bad  = int((df["r2"] < 0.5).sum())
    n_ok   = int(((df["r2"] >= 0.5) & (df["r2"] < 0.9)).sum())
    n_good = int((df["r2"] >= 0.9).sum())
    n_nan  = int(df["r2"].isna().sum())

    # ---- chart (3): horizontal bars, worst at top ----
    df_sorted = df.sort_values("r2", ascending=True, na_position="first").reset_index(drop=True)
    n_show = min(EVAL_WORST_N, total)
    df_show = df_sorted.head(n_show)
    # Bokeh draws FactorRange bottom-up, so the FIRST factor lands at the
    # bottom of the chart. We want the WORST output at the TOP, so reverse
    # the list before assigning as factors. After reversal the worst is the
    # LAST factor (drawn at the top).
    out_factors = list(reversed(df_show["output"].tolist()))
    df_reversed = df_show.iloc[::-1].reset_index(drop=True)
    per_output_bars_source.data = dict(
        output=out_factors,
        r2=df_reversed["r2"].fillna(0.0).tolist(),
        rmse=df_reversed["rmse"].fillna(0.0).tolist(),
        mae=df_reversed["mae"].fillna(0.0).tolist(),
        nrmse=df_reversed["nrmse"].fillna(0.0).tolist(),
        color=[_r2_color(r) for r in df_reversed["r2"]],
        prefix=df_reversed["_prefix"].tolist(),
        tech=df_reversed["_tech"].tolist(),
        region=df_reversed["_region"].tolist(),
    )
    per_output_bars_fig.y_range.factors = out_factors
    # Grow the chart height proportionally so labels stay readable when
    # many outputs are shown.
    per_output_bars_fig.height = max(300, min(1400, n_show * 18 + 80))
    title_suffix = (f"showing {n_show} of {total} outputs (worst first)"
                    if n_show < total else f"all {total} outputs")
    per_output_bars_fig.title.text = (
        f"Per-output R² (selected model) — {title_suffix}"
    )

    nan_html = (
        f" &middot; <span style='color:{_R2_NA}'>&#9632; {n_nan} n/a</span>"
        if n_nan else ""
    )
    per_output_summary_div.text = (
        f"<p style='font-size:12px;color:#333;margin:2px 0'>"
        f"<b>{total} outputs</b> &mdash; "
        f"<span style='color:{_R2_GOOD}'>&#9632; {n_good} good (R\u00b2 &ge; 0.9)</span> &middot; "
        f"<span style='color:{_R2_OK}'>&#9632; {n_ok} ok (0.5 &le; R\u00b2 &lt; 0.9)</span> &middot; "
        f"<span style='color:{_R2_BAD}'>&#9632; {n_bad} poor (R\u00b2 &lt; 0.5)</span>"
        f"{nan_html}"
        f"</p>"
    )

    # ---- chart (4a): per-catalog small-multiples (P2a) ----
    # Drop near-constant outputs first — frac_nonzero / mostly_zero columns
    # are written by surrogate_eval.per_output_metrics. Items where the
    # output is deployed in fewer than ~5% of cases have unstable R² and
    # were the source of the "wind-ons mean R² ≈ 0.3" optical illusion in
    # the old chart. We keep them in per_output_bars (chart 3) but exclude
    # them from the bias-by-catalog summary.
    if "mostly_zero" in df.columns:
        df_keep = df[~df["mostly_zero"].fillna(False)].copy()
    elif "frac_nonzero" in df.columns:
        df_keep = df[df["frac_nonzero"] >= 0.05].copy()
    else:
        df_keep = df.copy()

    # Resolve a display item name once per row:
    #   • Tech catalogs (cap, gen) use _tech_display_name to merge vintages.
    #   • Cost catalog uses the parsed `_tech` token (cost component).
    #   • Transmission uses `_tech` (line type).
    #   • Anything without a tech token falls back to the raw output name.
    def _display_item(row) -> str:
        prefix = row.get("_prefix") or ""
        tech = row.get("_tech") or ""
        if not tech:
            return str(row.get("output", "?"))
        if prefix in ("cap", "gen"):
            return _tech_display_name(tech)
        return tech

    df_keep["_item"] = df_keep.apply(_display_item, axis=1)
    df_keep["_catalog"] = df_keep["_prefix"].fillna("").str.lower()

    excluded_n = int(len(df) - len(df_keep))
    excluded_note = (
        f" (excluded {excluded_n} near-constant outputs)" if excluded_n
        else ""
    )

    for cat, label in PER_TECH_CATALOGS:
        sub = df_keep[df_keep["_catalog"] == cat]
        if sub.empty:
            per_tech_sources[cat].data = empty_grp_tech
            per_tech_figs[cat].x_range.factors = []
            per_tech_figs[cat].title.text = (
                f"{label} — no outputs in this catalog"
            )
            continue
        grp = (
            sub.groupby("_item")
               .agg(r2_median=("r2", "median"),
                    r2_mean=("r2", "mean"),
                    n=("r2", "size"))
               .reset_index()
               .sort_values("r2_median", ascending=True, na_position="first")
        )
        # Cap each panel at the 30 worst items (rare overflow on regional).
        capped = False
        if len(grp) > 30:
            grp = grp.head(30)
            capped = True
        # Clip displayed bar tops at -1.0 so catastrophic outputs
        # don't extend off the panel — surface the true value in the
        # tooltip via ``r2_actual``.
        r2_true  = grp["r2_median"].fillna(0.0).tolist()
        r2_clip  = [max(float(r), -1.0) for r in r2_true]
        per_tech_sources[cat].data = dict(
            item=grp["_item"].tolist(),
            r2_median=r2_clip,
            r2_actual=r2_true,
            r2_mean=grp["r2_mean"].fillna(0.0).tolist(),
            n=grp["n"].tolist(),
            color=[_r2_color(r) for r in r2_true],
        )
        per_tech_figs[cat].x_range.factors = grp["_item"].tolist()
        suffix = " (30 WORST shown)" if capped else ""
        per_tech_figs[cat].title.text = (
            f"{label} — median R² per item{suffix}{excluded_note}"
        )

    # ---- chart (4b): per-region aggregation (regional layer only) ----
    # P2b: on Overall layer the source has no region column, so we leave
    # this empty here and the layout swaps in a Div note instead. On
    # Regional we sort by MEDIAN R² ascending (worst-on-the-left) so the
    # eye lands on the regions that need attention first.
    df_reg = df_keep[df_keep["_region"] != ""]
    if not df_reg.empty:
        reg_grp = (
            df_reg.groupby("_region")
                  .agg(r2_mean=("r2", "mean"),
                       r2_median=("r2", "median"),
                       n=("r2", "size"))
                  .reset_index()
                  .sort_values("r2_median", ascending=True, na_position="first")
        )
        # Clip displayed bar tops at -1.0 so catastrophic regions don't
        # extend off the panel; tooltip surfaces the true value via
        # ``r2_actual``.
        reg_true = reg_grp["r2_median"].fillna(0.0).tolist()
        reg_clip = [max(float(r), -1.0) for r in reg_true]
        per_region_source.data = dict(
            region=reg_grp["_region"].tolist(),
            r2_mean=reg_grp["r2_mean"].fillna(0.0).tolist(),
            r2_median=reg_clip,
            r2_actual=reg_true,
            n=reg_grp["n"].tolist(),
            color=[_r2_color(r) for r in reg_true],
        )
        per_region_fig.x_range.factors = reg_grp["_region"].tolist()
        per_region_fig.title.text = (
            f"Median R² per region — worst on the left "
            f"({len(reg_grp)} regions)"
        )
    else:
        per_region_source.data = empty_grp_reg
        per_region_fig.x_range.factors = []
        per_region_fig.title.text = (
            "Median R² per region — empty on Overall layer "
            "(switch the Layer selector to Regional to populate)"
        )


# Pre-allocate the eval-tab image Divs so ``_refresh_after_stage_change``
# can swap their content on Layer selector change without rebuilding the tab.
EVAL_IMAGE_NAMES: tuple[str, ...] = (
    "model_comparison_r2.png",
    "r2_distribution_per_output.png",
    "preview_capacity_stacks.png",
    "active_learning_curve.png",
)
eval_image_divs: dict[str, Div] = {
    name: Div(text=_img_html(name), width=900) for name in EVAL_IMAGE_NAMES
}

# (P3b) By-catalog distributional fidelity panel — refreshed on every
# stage change. Auto-hides when the eval CSV/PNG aren't present.
dist_fidelity_div = Div(text=_distfid_by_catalog_html(), width=900)

per_output_source = ColumnDataSource(
    data={"output": [], "r2": [], "rmse": [], "mae": [], "nrmse": []}
)
per_output_table = DataTable(
    source=per_output_source,
    columns=[
        TableColumn(field="output", title="Output", width=280),
        TableColumn(field="r2", title="R²",
                    formatter=NumberFormatter(format="0.0000"), width=90),
        TableColumn(field="rmse", title="RMSE",
                    formatter=NumberFormatter(format="0,0.00"), width=130),
        TableColumn(field="mae", title="MAE",
                    formatter=NumberFormatter(format="0,0.00"), width=130),
        TableColumn(field="nrmse", title="NRMSE",
                    formatter=NumberFormatter(format="0.0000"), width=100),
    ],
    width=900,
    height=420,
    index_position=None,
    sortable=True,
)
per_output_caption = Div(text="", width=900)


# ---------------------------------------------------------------------------
# OOF prediction reconstruction (shared helper used by sections 4, 5, 6)
# ---------------------------------------------------------------------------
# Reconstruct (y_true, y_pred) from each artifact's ``oof_residuals`` and the
# matching Y columns of TRAINING_DF.
OOF_CACHE: dict[tuple, tuple] = {}


def _get_oof_pred(name: str):
    """Return ``(Y_true, Y_pred, y_cols)`` for model ``name`` or ``None``.

    Cached per (stage, model); cache is cleared by ``_set_active_stage``.
    Any artifact-loading error is swallowed and the model is silently
    skipped.
    """
    if not name:
        return None
    cache_key = (str(RESULTS_DIR), name)
    if cache_key in OOF_CACHE:
        return OOF_CACHE[cache_key]
    try:
        art = _get_artifact(name)
    except Exception:
        OOF_CACHE[cache_key] = None  # remember the failure
        return None
    if art is None or TRAINING_DF.empty:
        return None
    y_cols = list(art.get("y_cols", []))
    oof_res = art.get("oof_residuals")
    if oof_res is None or not y_cols:
        return None
    available = [c for c in y_cols if c in TRAINING_DF.columns]
    if not available:
        return None
    Y_true = TRAINING_DF[available].to_numpy(dtype=float)
    oof_arr = np.asarray(oof_res, dtype=float)
    # Trim to the common subset (TRAINING_DF columns and residual columns may
    # diverge when y_cols are filtered for constant outputs).
    col_idx = [y_cols.index(c) for c in available if y_cols.index(c) < oof_arr.shape[1]]
    if not col_idx:
        return None
    Y_true = Y_true[:, : len(col_idx)]
    Y_pred = Y_true - oof_arr[:, col_idx]
    cols = available[: len(col_idx)]
    val = (Y_true, Y_pred, cols)
    OOF_CACHE[cache_key] = val
    return val


# ---------------------------------------------------------------------------
# Helpers for top-2 ranking, per-case R², output catalogs, cross-layer summary
# ---------------------------------------------------------------------------
_CATALOG_LABELS = {
    "cap":  "Capacity",
    "gen":  "Generation",
    "cost": "System cost",
    "tran": "Transmission",
}


def _output_category(name: str) -> str:
    """Map an output column name to a high-level catalog label."""
    prefix, _, _ = _parse_output_name(name)
    return _CATALOG_LABELS.get(prefix or "", "Other")


def _top_n_models(n: int = 2) -> list[str]:
    """Return the top-n model keys (by composite score from SUMMARY) for the active layer."""
    return _rank_by_composite(SUMMARY)[:n]


def _per_case_r2(Y_true: np.ndarray, Y_pred: np.ndarray) -> np.ndarray:
    """Per-case R² after column z-scoring.

    Each output column is centred / scaled by its training mean / std so that
    high-magnitude outputs don't dominate. Then for every row we compute
    R² = 1 - SS_res / SS_tot, where the totals are summed across all
    (z-scored) outputs in that row.
    """
    if Y_true.size == 0 or Y_pred.shape != Y_true.shape:
        return np.full(Y_true.shape[0] if Y_true.ndim == 2 else 0, np.nan)
    std = np.nanstd(Y_true, axis=0, ddof=0)
    std_safe = np.where(std > 1e-12, std, 1.0)
    mean = np.nanmean(Y_true, axis=0)
    Zt = (Y_true - mean) / std_safe
    Zp = (Y_pred - mean) / std_safe
    res2 = np.nansum((Zp - Zt) ** 2, axis=1)
    tot2 = np.nansum(Zt ** 2, axis=1)
    return np.where(tot2 > 1e-12, 1.0 - res2 / tot2, np.nan)


def _design_label(row: pd.Series) -> str:
    """Stringify a TRAINING_DF row's design dimensions (decoded back to labels)."""
    parts: list[str] = []
    for dim, levels in DIMENSION_ENCODING.items():
        col = f"x_{dim}"
        if col not in row.index:
            continue
        try:
            inv = {v: k for k, v in levels.items()}
            parts.append(f"{dim}={inv.get(int(row[col]), str(row[col]))}")
        except Exception:
            parts.append(f"{dim}={row[col]}")
    return ", ".join(parts) if parts else "—"


# ---------------------------------------------------------------------------
# (4) Per-model parity grid — one parity plot per model, per layer
# ---------------------------------------------------------------------------
# Each subplot shows ALL OOF (sample × output) points for ONE model on ONE
# layer (Overall or Regional). Each panel uses a single colour (distinct
# per method) so methods are easy to compare at a glance.
PARITY_GRID_PER_MODEL_CAP = 5000
PARITY_GRID_FIG_W = 280
PARITY_GRID_FIG_H = 280
PARITY_GRID_COLS = 3
PARITY_LAYERS: tuple[str, ...] = ("overall", "regional")
PARITY_LAYER_LABELS = {"overall": "Overall", "regional": "Regional"}
PARITY_LAYER_COLORS = {"overall": "#1f77b4", "regional": "#d62728"}

parity_grid_tech_select = Select(
    title="Tech filter (applies to all panels, both layers)",
    value="All", options=["All"], width=300,
)
parity_grid_region_select = Select(
    title="Region filter (Regional layer only)",
    value="All", options=["All"], width=240,
)
parity_grid_status_div = Div(text="", width=900)

# Per-layer holders + legends + section titles. Use explicit fixed widths
# so the holder columns don't collapse to zero width when nested under
# the wider Section-1 table row.
PARITY_GRID_HOLDER_W = PARITY_GRID_FIG_W * PARITY_GRID_COLS + 60  # ~900 px
parity_holders: dict[str, "column"] = {}
parity_legends: dict[str, Div] = {}
parity_layer_titles: dict[str, Div] = {}
for _l in PARITY_LAYERS:
    parity_holders[_l] = column(
        Div(text="<i>Loading parity grid…</i>"),
        width=PARITY_GRID_HOLDER_W,
    )
    parity_legends[_l] = Div(text="", width=200)
    parity_layer_titles[_l] = Div(text="", width=PARITY_GRID_HOLDER_W + 220)

# Mutable state — populated by ``_build_parity_grid``. Keyed first by layer
# short name, then by model key.
_parity_sources: dict[str, dict[str, ColumnDataSource]] = {l: {} for l in PARITY_LAYERS}
_parity_diag_sources: dict[str, dict[str, ColumnDataSource]] = {l: {} for l in PARITY_LAYERS}
_parity_figures: dict[str, dict[str, "figure"]] = {l: {} for l in PARITY_LAYERS}


def _make_parity_subfig(model_key: str):
    """Build one parity subplot (figure + scatter + diag sources)."""
    src = ColumnDataSource(data=dict(
        actual=[], predicted=[], output=[], tech=[], region=[],
        color=[], abs_err=[],
    ))
    diag = ColumnDataSource(data=dict(x=[0.0, 1.0], y=[0.0, 1.0]))
    fig = figure(
        width=PARITY_GRID_FIG_W, height=PARITY_GRID_FIG_H,
        x_range=Range1d(start=0.0, end=1.0),
        y_range=Range1d(start=0.0, end=1.0),
        title=model_key,
        toolbar_location="above",
        tools="pan,wheel_zoom,box_zoom,reset,save",
        active_drag="box_zoom",
        active_scroll="wheel_zoom",
        x_axis_label="Actual",
        y_axis_label="Predicted",
        output_backend="webgl",
    )
    fig.toolbar.logo = None
    fig.title.text_font_size = "11pt"
    fig.line(x="x", y="y", source=diag, line_color="#444",
             line_dash="dashed", line_width=1.2)
    sct = fig.scatter(
        x="actual", y="predicted", size=4, alpha=0.45,
        fill_color="color", line_color=None, source=src,
    )
    fig.add_tools(HoverTool(
        renderers=[sct],
        tooltips=[
            ("Output", "@output"),
            ("Tech / Region", "@tech / @region"),
            ("Actual", "@actual{0,0.000}"),
            ("Predicted", "@predicted{0,0.000}"),
            ("|err|", "@abs_err{0,0.000}"),
        ],
        point_policy="follow_mouse",
    ))
    return fig, src, diag


def _build_parity_grid_for_layer(layer_short: str) -> None:
    """Recreate per-model parity subplots for one layer."""
    _parity_sources[layer_short].clear()
    _parity_diag_sources[layer_short].clear()
    _parity_figures[layer_short].clear()
    layer_label = PARITY_LAYER_LABELS[layer_short]
    layer_color = PARITY_LAYER_COLORS[layer_short]
    layer_models = _models_for_layer(layer_short)
    layer_summary = _summary_for_layer(layer_short)
    title_html = (
        f"<h4 style='margin:14px 0 4px 0;color:{layer_color}'>"
        f"{layer_label} layer — per-method parity</h4>"
    )
    parity_layer_titles[layer_short].text = title_html
    if not layer_models:
        parity_holders[layer_short].children = [
            Div(text=f"<i>No models found in the {layer_label} layer.</i>")
        ]
        return
    # Order models by composite score descending (best first); skip any that
    # are not in the on-disk artifact list.
    order = [k for k in _rank_by_composite(layer_summary)
             if k in layer_models]
    for k in order:
        # Skip models that fail to load.
        triple = _get_oof_pred_for_layer(layer_short, k)
        if triple is None:
            continue
        fig_, src, diag = _make_parity_subfig(k)
        _parity_figures[layer_short][k] = fig_
        _parity_sources[layer_short][k] = src
        _parity_diag_sources[layer_short][k] = diag
    if not _parity_figures[layer_short]:
        parity_holders[layer_short].children = [
            Div(text=f"<i>No usable artifacts in the {layer_label} layer.</i>")
        ]
        return
    figs = list(_parity_figures[layer_short].values())
    # Build the grid manually with nested row/column — more predictable than
    # gridplot under varying parent widths in Bokeh 3.6.
    grid_rows = [
        row(*figs[i:i + PARITY_GRID_COLS], spacing=10)
        for i in range(0, len(figs), PARITY_GRID_COLS)
    ]
    grid = column(*grid_rows, spacing=10)
    parity_holders[layer_short].children = [grid]


def _build_parity_grid() -> None:
    """Recreate per-model parity subplots for BOTH layers."""
    for layer_short in PARITY_LAYERS:
        _build_parity_grid_for_layer(layer_short)


def _refresh_parity_grid_options() -> None:
    """Repopulate Tech / Region dropdowns from both layers' outputs."""
    techs: set[str] = set()
    regions: set[str] = set()
    for layer_short in PARITY_LAYERS:
        models = _models_for_layer(layer_short)
        if not models:
            continue
        art = None
        for k in models.keys():
            art = _artifact_for_layer(layer_short, k)
            if art is not None:
                break
        if art is None:
            continue
        for c in art.get("y_cols", []):
            _, t, r = _parse_output_name(c)
            if t:
                techs.add(t)
            if r:
                regions.add(r)
    parity_grid_tech_select.options = ["All"] + sorted(techs)
    if parity_grid_tech_select.value not in parity_grid_tech_select.options:
        parity_grid_tech_select.value = "All"
    parity_grid_region_select.options = ["All"] + sorted(
        regions,
        key=lambda r: int(r[1:]) if r.startswith("p") and r[1:].isdigit() else 99999,
    )
    if parity_grid_region_select.value not in parity_grid_region_select.options:
        parity_grid_region_select.value = "All"


def _update_parity_grid_for_layer(layer_short: str) -> int:
    """Refresh every subplot for one layer. One color per method (panel-wide).

    Returns the total number of points drawn across all panels.
    """
    figs = _parity_figures[layer_short]
    if not figs:
        parity_legends[layer_short].text = ""
        return 0
    sel_tech = parity_grid_tech_select.value or "All"
    sel_region = parity_grid_region_select.value or "All"

    # One color per method — Category10 / Category20 cycled through panels.
    model_keys = list(figs.keys())
    if len(model_keys) <= 10:
        palette = list(Category10[10])
    else:
        palette = list(Category20[20])
    method_color = {k: palette[i % len(palette)] for i, k in enumerate(model_keys)}

    rng = np.random.default_rng(42)
    n_total = 0

    for k, fig_ in figs.items():
        src = _parity_sources[layer_short][k]
        diag = _parity_diag_sources[layer_short][k]
        triple = _get_oof_pred_for_layer(layer_short, k)
        if triple is None:
            src.data = dict(actual=[], predicted=[], output=[], tech=[],
                            region=[], color=[], abs_err=[])
            fig_.title.text = f"{k} — n/a"
            continue
        Y_true, Y_pred, cols = triple
        keep_idx: list[int] = []
        keep_techs: list[str] = []
        keep_regions: list[str] = []
        for i, c in enumerate(cols):
            _, t, r = _parse_output_name(c)
            t = t or "(no tech)"
            r = r or ""
            if sel_tech != "All" and t != sel_tech:
                continue
            # Region filter only applies when the output is regional. For
            # the Overall layer there is no region info, so the filter is
            # ignored (but tech filter still applies).
            if sel_region != "All" and r and r != sel_region:
                continue
            keep_idx.append(i)
            keep_techs.append(t)
            keep_regions.append(r)
        if not keep_idx:
            src.data = dict(actual=[], predicted=[], output=[], tech=[],
                            region=[], color=[], abs_err=[])
            fig_.title.text = f"{k} — no points after filter"
            continue
        Yt = Y_true[:, keep_idx]
        Yp = Y_pred[:, keep_idx]
        n_rows = Yt.shape[0]
        out_names = np.array([cols[i] for i in keep_idx], dtype=object)
        tech_arr = np.array(keep_techs, dtype=object)
        reg_arr = np.array(keep_regions, dtype=object)
        out_flat = np.tile(out_names, n_rows)
        tech_flat = np.tile(tech_arr, n_rows)
        reg_flat = np.tile(reg_arr, n_rows)
        Yt_flat = Yt.ravel()
        Yp_flat = Yp.ravel()
        finite = np.isfinite(Yt_flat) & np.isfinite(Yp_flat)
        Yt_flat = Yt_flat[finite]
        Yp_flat = Yp_flat[finite]
        out_flat = out_flat[finite]
        tech_flat = tech_flat[finite]
        reg_flat = reg_flat[finite]
        n = len(Yt_flat)
        # Pooled R² on the FULL filtered data (before sampling).
        if n > 1 and Yt_flat.var() > 0:
            ss_res = float(np.sum((Yt_flat - Yp_flat) ** 2))
            ss_tot = float(np.sum((Yt_flat - Yt_flat.mean()) ** 2))
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
        else:
            r2 = float("nan")
        # Sample for plotting only.
        if n > PARITY_GRID_PER_MODEL_CAP:
            sel = rng.choice(n, PARITY_GRID_PER_MODEL_CAP, replace=False)
            Yt_flat = Yt_flat[sel]
            Yp_flat = Yp_flat[sel]
            out_flat = out_flat[sel]
            tech_flat = tech_flat[sel]
            reg_flat = reg_flat[sel]
        n_kept = len(Yt_flat)
        n_total += n_kept
        # ALL points in this panel use the method's single colour.
        method_c = method_color[k]
        color_flat = np.full(n_kept, method_c, dtype=object)
        src.data = dict(
            actual=Yt_flat.tolist(),
            predicted=Yp_flat.tolist(),
            output=out_flat.tolist(),
            tech=tech_flat.tolist(),
            region=reg_flat.tolist(),
            color=color_flat.tolist(),
            abs_err=np.abs(Yt_flat - Yp_flat).tolist(),
        )
        if n_kept > 0:
            lo = float(min(Yt_flat.min(), Yp_flat.min()))
            hi = float(max(Yt_flat.max(), Yp_flat.max()))
        else:
            lo, hi = 0.0, 1.0
        if not np.isfinite(lo) or not np.isfinite(hi) or lo == hi:
            lo, hi = -1.0, 1.0
        pad = max((hi - lo) * 0.05, 1e-6)
        lo -= pad
        hi += pad
        diag.data = dict(x=[lo, hi], y=[lo, hi])
        fig_.x_range.start = lo
        fig_.x_range.end = hi
        fig_.y_range.start = lo
        fig_.y_range.end = hi
        r2_str = f"R²={r2:.3f}" if np.isfinite(r2) else "R²=n/a"
        fig_.title.text = f"{k} — {r2_str} ({n:,} pts)"

    # Method-color legend HTML (one swatch per panel).
    legend_rows = [
        "<div style='font-size:12px;line-height:1.4'>"
        "<b>Method (panel color)</b><br/>"
    ]
    for k in model_keys:
        legend_rows.append(
            f"<div style='margin:1px 0'>"
            f"<span style='display:inline-block;width:10px;height:10px;"
            f"background:{method_color[k]};border-radius:50%;"
            f"margin-right:6px;vertical-align:middle'></span>"
            f"<code>{k}</code></div>"
        )
    legend_rows.append("</div>")
    parity_legends[layer_short].text = "".join(legend_rows)
    return n_total


def _update_parity_grid(*_args) -> None:
    """Refresh every subplot for both layers."""
    if not any(_parity_figures[l] for l in PARITY_LAYERS):
        parity_grid_status_div.text = ""
        return
    sel_tech = parity_grid_tech_select.value or "All"
    sel_region = parity_grid_region_select.value or "All"
    parts = []
    for layer_short in PARITY_LAYERS:
        n = _update_parity_grid_for_layer(layer_short)
        parts.append(
            f"<b style='color:{PARITY_LAYER_COLORS[layer_short]}'>"
            f"{PARITY_LAYER_LABELS[layer_short]}</b>: "
            f"{n:,} points across {len(_parity_figures[layer_short])} models"
        )
    parity_grid_status_div.text = (
        f"<p style='font-size:12px;color:#555;margin:2px 0'>"
        f"Tech filter: <b>{sel_tech}</b> · region filter: <b>{sel_region}</b>"
        f"<br/>" + " &nbsp;|&nbsp; ".join(parts)
        + f" &nbsp;(per-model cap {PARITY_GRID_PER_MODEL_CAP:,}).</p>"
    )


parity_grid_tech_select.on_change(
    "value", lambda _attr, _old, _new: _update_parity_grid()
)
parity_grid_region_select.on_change(
    "value", lambda _attr, _old, _new: _update_parity_grid()
)


# ---------------------------------------------------------------------------
# (5) Per-case R² distribution — top-1 method, BOTH layers (2 charts)
# ---------------------------------------------------------------------------
# Each of the 486 cases gets a single R² score (across all outputs after
# z-scoring). Cases are sorted ascending by the model's own R² so the
# curve reveals which designs are systematically harder to predict.
# Each layer shows ONLY its top-1 method (per the §1 leaderboard Score).
PERCASE_COLOR_A = Category10[10][0]   # blue (top-1 model)
PERCASE_COLOR_B = Category10[10][1]   # orange (used by §4/§5 top-2 overlays)
PERCASE_LAYERS: tuple[str, ...] = ("overall", "regional")
PERCASE_LAYER_LABELS = {"overall": "Overall", "regional": "Regional"}
PERCASE_LAYER_HEADER_COLORS = {"overall": "#1f77b4", "regional": "#d62728"}

percase_sources_a: dict[str, ColumnDataSource] = {}
percase_figs_a: dict[str, "figure"] = {}
percase_legends: dict[str, Div] = {}
percase_layer_titles: dict[str, Div] = {}


def _make_percase_subfig(title: str, color: str, src: ColumnDataSource,
                         marker: str = "circle") -> "figure":
    fig = figure(
        width=900, height=300,
        title=title,
        x_axis_label="Case rank (sorted by this panel's model R², "
                     "ascending)",
        y_axis_label="Case R² (z-scored across outputs)",
        toolbar_location="above",
        tools="box_zoom,wheel_zoom,pan,reset,save",
        active_drag="box_zoom",
        active_scroll="wheel_zoom",
    )
    fig.toolbar.logo = None
    fig.line(
        x="rank", y="r2", source=src,
        line_color=color, line_width=1.3, alpha=0.85,
    )
    sct = fig.scatter(
        x="rank", y="r2", source=src,
        size=5, alpha=0.85, fill_color=color, line_color=None,
        marker=marker,
    )
    for thr, c in ((0.9, _R2_GOOD), (0.5, _R2_OK), (0.0, _R2_BAD)):
        fig.add_layout(Span(
            location=thr, dimension="width",
            line_color=c, line_dash="dashed",
            line_width=1, line_alpha=0.6,
        ))
    fig.add_tools(HoverTool(
        renderers=[sct],
        tooltips=[
            ("Case row", "@case"),
            ("Rank", "@rank"),
            ("R²", "@r2{0.000}"),
            ("Design", "@design"),
        ],
        point_policy="follow_mouse",
    ))
    return fig


for _layer in PERCASE_LAYERS:
    _src_a = ColumnDataSource(data=dict(rank=[], r2=[], case=[], design=[]))
    _fig_a = _make_percase_subfig(
        f"{PERCASE_LAYER_LABELS[_layer]} — top-1 (sorted by its own R²)",
        PERCASE_COLOR_A, _src_a, marker="circle",
    )
    percase_sources_a[_layer] = _src_a
    percase_figs_a[_layer] = _fig_a
    percase_legends[_layer] = Div(text="", width=900)
    percase_layer_titles[_layer] = Div(text="", width=900)


def _update_percase_chart_for_layer(layer_short: str) -> None:
    """Recompute the per-case R² curve for one layer's top-1 model."""
    empty = dict(rank=[], r2=[], case=[], design=[])
    layer_label = PERCASE_LAYER_LABELS[layer_short]
    layer_color = PERCASE_LAYER_HEADER_COLORS[layer_short]
    summary = _summary_for_layer(layer_short)
    training_df = _training_df_for_layer(layer_short)
    src_a = percase_sources_a[layer_short]
    fig_a = percase_figs_a[layer_short]
    legend = percase_legends[layer_short]
    title_div = percase_layer_titles[layer_short]
    title_div.text = (
        f"<h4 style='margin:14px 0 4px 0;color:{layer_color}'>"
        f"{layer_label} layer — best method by honest §R0 ranking</h4>"
    )
    if not summary or training_df is None or training_df.empty:
        src_a.data = empty
        fig_a.title.text = f"{layer_label} — best (no data)"
        legend.text = ""
        return
    # P3a fix: use the honest §R0 ranking (bootstrap per-output mean)
    # rather than the legacy pooled-R²-based Score. The Score depends on
    # joblibs being loadable, which fails transiently while training is
    # in progress and produces misleading picks like "best = knn" when
    # the actually-good models simply haven't finished training yet.
    # The honest §R0 ranking reads ``model_ranking_bootstrap.csv`` which
    # captures all models from the last full eval pass.
    top1_list = _rank_by_honest_r0(layer_short)[:1]
    # Only pick a model that we can actually load — if the top R0 model
    # has no joblib on disk (transient mid-training state) fall back to
    # the next-best loadable one.
    available = set(_models_for_layer(layer_short).keys())
    if top1_list and top1_list[0] not in available:
        for cand in _rank_by_honest_r0(layer_short):
            if cand in available:
                top1_list = [cand]
                break
        else:
            top1_list = []
    top1 = top1_list[0] if top1_list else ""
    triple = _get_oof_pred_for_layer(layer_short, top1) if top1 else None
    if not top1 or triple is None:
        src_a.data = empty
        fig_a.title.text = (
            f"{layer_label} — best: '{top1 or '—'}' (no usable model)"
        )
        legend.text = ""
        return
    Y_true, Y_pred, _ = triple
    r2 = _per_case_r2(Y_true, Y_pred)
    sort_order = np.argsort(np.where(np.isfinite(r2), r2, -np.inf))
    r2_sorted = r2[sort_order]
    src_a.data = dict(
        rank=list(range(1, len(sort_order) + 1)),
        r2=[float(x) if np.isfinite(x) else 0.0 for x in r2_sorted],
        case=[int(j) for j in sort_order],
        design=[_design_label(training_df.iloc[int(j)])
                for j in sort_order],
    )
    # If the picked model is not actually #1 in the honest ranking
    # (transient mid-training state where #1's joblib hasn't been
    # written yet), tell the reader explicitly so they don't mistake
    # the fallback for the truly-best method.
    full_ranking = _rank_by_honest_r0(layer_short)
    true_top1 = full_ranking[0] if full_ranking else ""
    fallback_note = ""
    if true_top1 and true_top1 != top1:
        fallback_note = (
            f" &nbsp;|&nbsp; <span style='color:#b8860b'>"
            f"NOTE: \u00a7R0 #1 is <b>{true_top1}</b> but its joblib "
            f"is not loaded yet \u2014 showing best-loadable instead."
            f"</span>"
        )
    fig_a.title.text = (
        f"{layer_label} \u2014 best: '{top1}' (sorted by its own R\u00b2)"
    )
    legend.text = (
        "<div style='font-size:12px;color:#555'>"
        f"<span style='color:{PERCASE_COLOR_A}'>\u25cf best: "
        f"{top1}</span>"
        " &nbsp;|&nbsp; horizontal lines: R\u00b2 = 0.9 / 0.5 / 0."
        f"{fallback_note}"
        "</div>"
    )


def _update_percase_chart() -> None:
    """Refresh per-case R² curves for both layers."""
    for layer_short in PERCASE_LAYERS:
        _update_percase_chart_for_layer(layer_short)


# ---------------------------------------------------------------------------
# (6) Per-catalog R² — top-2 models, BOTH layers
# ---------------------------------------------------------------------------
# Catalog = (layer, output-prefix), e.g. ("Overall", "Capacity"),
# ("Regional", "Generation"). Bars show median R² across the outputs in
# each (layer, catalog) cell, side by side for the top-2 models. Top-2
# are chosen from the OVERALL summary so the comparison is anchored.
percatalog_source = ColumnDataSource(data=dict(
    factors=[], r2=[], color=[], n=[], catalog=[], layer=[], model=[],
))
percatalog_fig = figure(
    width=900, height=380,
    x_range=FactorRange(),
    y_range=Range1d(start=-0.5, end=1.05),
    title="Per-catalog median R² — top-2 models (both layers)",
    toolbar_location="above",
    tools="box_zoom,xbox_zoom,ybox_zoom,pan,reset,save",
    active_drag="box_zoom",
    y_axis_label="R² (median across outputs)",
)
percatalog_fig.toolbar.logo = None
percatalog_fig.xaxis.major_label_orientation = 0.5
percatalog_fig.xgrid.grid_line_color = None
_pcat_bars = percatalog_fig.vbar(
    x="factors", top="r2", width=0.85,
    color="color", source=percatalog_source,
    line_color="white", line_width=0.5,
)
percatalog_fig.add_tools(HoverTool(
    renderers=[_pcat_bars],
    tooltips=[
        ("Layer", "@layer"),
        ("Catalog", "@catalog"),
        ("Model", "@model"),
        ("Median R²", "@r2{0.000}"),
        ("# outputs", "@n"),
    ],
    point_policy="follow_mouse",
))
for thr, col in ((0.9, _R2_GOOD), (0.5, _R2_OK), (0.0, _R2_BAD)):
    percatalog_fig.add_layout(Span(
        location=thr, dimension="width",
        line_color=col, line_dash="dashed", line_width=1, line_alpha=0.6,
    ))


def _update_percatalog_chart() -> None:
    """Refresh per-catalog R² bars across BOTH layers for the top-N models."""
    empty = dict(factors=[], r2=[], color=[], n=[], catalog=[],
                 layer=[], model=[])
    # Top-N models from the OVERALL layer using the honest §R0 ranking
    # (per-output mean R² with bootstrap CIs). Falls back to §1 Score
    # when model_ranking_bootstrap.csv is missing.
    overall_summary = _summary_for_layer("overall")
    if not overall_summary:
        percatalog_source.data = empty
        percatalog_fig.x_range.factors = []
        percatalog_fig.title.text = "Per-catalog R² — Overall summary not found"
        return
    models_dict = overall_summary.get("models", {})
    top_all = _rank_by_honest_r0("overall")
    if not top_all:
        top_all = _rank_by_score("overall")
    topN = [m for m in top_all if m in models_dict][:N_METHODS_COMPARE]
    if not topN:
        percatalog_source.data = empty
        percatalog_fig.x_range.factors = []
        percatalog_fig.title.text = "Per-catalog R² — no models"
        return
    palette = _palette_for_n(len(topN))
    catalog_canonical = list(_CATALOG_LABELS.values())
    layer_order = ("Overall", "Regional")

    # Pull per_output_metrics CSVs for both layers × top-N models.
    per_layer_model_df: dict[tuple, pd.DataFrame] = {}
    for layer_short, layer_label in (("overall", "Overall"), ("regional", "Regional")):
        res_dir, _, _ = _layer_paths(layer_short)
        if res_dir is None:
            continue
        for m in topN:
            csv_path = res_dir / f"per_output_metrics_{m}.csv"
            if not csv_path.exists():
                continue
            try:
                df = pd.read_csv(csv_path)
            except Exception:
                continue
            if df.empty or "output" not in df.columns or "r2" not in df.columns:
                continue
            df = df.copy()
            df["_cat"] = df["output"].apply(_output_category)
            per_layer_model_df[(layer_label, m)] = df

    if not per_layer_model_df:
        percatalog_source.data = empty
        percatalog_fig.x_range.factors = []
        percatalog_fig.title.text = (
            "Per-catalog R² — no per_output_metrics_<model>.csv found in either layer"
        )
        return

    # Catalogs that actually appear in any (layer, model) combo, in canonical order.
    catalog_seen: set[str] = set()
    for df in per_layer_model_df.values():
        catalog_seen.update(df["_cat"].unique())
    catalog_order = (
        [c for c in catalog_canonical if c in catalog_seen]
        + sorted(c for c in catalog_seen if c not in catalog_canonical)
    )

    factors: list[tuple] = []
    r2s: list[float] = []
    colors: list[str] = []
    ns: list[int] = []
    cats_out: list[str] = []
    layers_out: list[str] = []
    models_out: list[str] = []
    for layer_label in layer_order:
        for cat in catalog_order:
            for i, m in enumerate(topN):
                df = per_layer_model_df.get((layer_label, m))
                if df is None:
                    continue
                sub = df[df["_cat"] == cat]
                if sub.empty:
                    continue
                r2_med = float(sub["r2"].median())
                # 2-level factor: outer = "Layer · Catalog", inner = model.
                outer = f"{layer_label} · {cat}"
                factors.append((outer, m))
                r2s.append(r2_med)
                colors.append(palette[i % len(palette)])
                ns.append(int(len(sub)))
                cats_out.append(cat)
                layers_out.append(layer_label)
                models_out.append(m)

    percatalog_source.data = dict(
        factors=factors, r2=r2s, color=colors, n=ns,
        catalog=cats_out, layer=layers_out, model=models_out,
    )
    percatalog_fig.x_range.factors = factors
    method_list = ", ".join(f"'{m}'" for m in topN)
    percatalog_fig.title.text = (
        f"Per-catalog median R² — top-{len(topN)} methods (ranked by §R0): "
        f"{method_list}"
    )


# ---------------------------------------------------------------------------
# (7) Overall vs Regional — per-output R² distribution for top-2 methods
# ---------------------------------------------------------------------------
# For the same top-2 methods (anchored by Overall R² mean), show every
# output's R² as a jittered dot, separated into 4 columns:
# (top-1 · Overall), (top-1 · Regional), (top-2 · Overall), (top-2 · Regional).
# Median bar overlaid as a thick horizontal segment.
crosslayer_source = ColumnDataSource(data=dict(
    factors=[], r2=[], output=[], model=[], layer=[], color=[],
))
crosslayer_median_source = ColumnDataSource(data=dict(
    factors=[], median=[], mean=[], n=[],
))
crosslayer_fig = figure(
    width=900, height=420,
    x_range=FactorRange(),
    y_range=Range1d(start=-1.0, end=1.05),
    title="Overall vs Regional — per-output R² (top-2 methods)",
    toolbar_location="above",
    tools="box_zoom,xbox_zoom,ybox_zoom,pan,reset,save",
    active_drag="box_zoom",
    y_axis_label="Per-output R² (one dot per output)",
)
crosslayer_fig.toolbar.logo = None
crosslayer_fig.xaxis.major_label_orientation = 0.3
crosslayer_fig.xgrid.grid_line_color = None
_CROSSLAYER_OVERALL_C = "#1f77b4"
_CROSSLAYER_REGIONAL_C = "#d62728"

# Jittered scatter — every output is one dot.
_cl_dots = crosslayer_fig.scatter(
    x=jitter("factors", width=0.4, range=crosslayer_fig.x_range),
    y="r2",
    size=6, alpha=0.55,
    fill_color="color", line_color=None,
    source=crosslayer_source,
)
crosslayer_fig.add_tools(HoverTool(
    renderers=[_cl_dots],
    tooltips=[
        ("Model", "@model"),
        ("Layer", "@layer"),
        ("Output", "@output"),
        ("R²", "@r2{0.000}"),
    ],
    point_policy="follow_mouse",
))
# Median segment per (model, layer).
_cl_median = crosslayer_fig.segment(
    x0=dodge("factors", -0.35, range=crosslayer_fig.x_range),
    x1=dodge("factors",  0.35, range=crosslayer_fig.x_range),
    y0="median", y1="median",
    line_color="black", line_width=3,
    source=crosslayer_median_source,
)
crosslayer_fig.add_tools(HoverTool(
    renderers=[_cl_median],
    tooltips=[
        ("Group", "@factors"),
        ("Median R²", "@median{0.000}"),
        ("Mean R²", "@mean{0.000}"),
        ("# outputs", "@n"),
    ],
))
for thr, col in ((0.9, _R2_GOOD), (0.5, _R2_OK), (0.0, _R2_BAD)):
    crosslayer_fig.add_layout(Span(
        location=thr, dimension="width",
        line_color=col, line_dash="dashed", line_width=1, line_alpha=0.6,
    ))


def _update_crosslayer_chart() -> None:
    """Refresh per-output R² distribution for top-N methods across both layers."""
    empty = dict(factors=[], r2=[], output=[], model=[], layer=[], color=[])
    empty_med = dict(factors=[], median=[], mean=[], n=[])

    overall_summary = _summary_for_layer("overall")
    if not overall_summary:
        crosslayer_source.data = empty
        crosslayer_median_source.data = empty_med
        crosslayer_fig.x_range.factors = []
        crosslayer_fig.title.text = (
            "Overall vs Regional — Overall summary.json not found"
        )
        return
    m_overall = overall_summary.get("models", {})
    top_all = _rank_by_honest_r0("overall")
    if not top_all:
        top_all = _rank_by_score("overall")
    topN = [m for m in top_all if m in m_overall][:N_METHODS_COMPARE]
    if not topN:
        crosslayer_source.data = empty
        crosslayer_median_source.data = empty_med
        crosslayer_fig.x_range.factors = []
        crosslayer_fig.title.text = "Overall vs Regional — no models found"
        return

    layer_color = {"Overall": _CROSSLAYER_OVERALL_C, "Regional": _CROSSLAYER_REGIONAL_C}
    factors_all: list[tuple] = []
    r2_all: list[float] = []
    out_all: list[str] = []
    model_all: list[str] = []
    layer_all: list[str] = []
    color_all: list[str] = []
    med_factors: list[tuple] = []
    med_vals: list[float] = []
    mean_vals: list[float] = []
    n_vals: list[int] = []

    factor_order: list[tuple] = []
    for m in topN:
        for layer_short, layer_label in (("overall", "Overall"),
                                         ("regional", "Regional")):
            res_dir, _, _ = _layer_paths(layer_short)
            if res_dir is None:
                continue
            csv_path = res_dir / f"per_output_metrics_{m}.csv"
            if not csv_path.exists():
                continue
            try:
                df = pd.read_csv(csv_path)
            except Exception:
                continue
            if df.empty or "output" not in df.columns or "r2" not in df.columns:
                continue
            r2_vals = df["r2"].to_numpy(dtype=float)
            outputs = df["output"].astype(str).tolist()
            factor = (m, layer_label)
            factor_order.append(factor)
            n = len(r2_vals)
            factors_all.extend([factor] * n)
            r2_all.extend([float(x) for x in r2_vals])
            out_all.extend(outputs)
            model_all.extend([m] * n)
            layer_all.extend([layer_label] * n)
            color_all.extend([layer_color[layer_label]] * n)
            finite = np.isfinite(r2_vals)
            if finite.any():
                med_factors.append(factor)
                med_vals.append(float(np.median(r2_vals[finite])))
                mean_vals.append(float(np.mean(r2_vals[finite])))
                n_vals.append(int(finite.sum()))

    if not factors_all:
        crosslayer_source.data = empty
        crosslayer_median_source.data = empty_med
        crosslayer_fig.x_range.factors = []
        crosslayer_fig.title.text = (
            "Overall vs Regional — no per_output_metrics_<model>.csv found"
        )
        return

    crosslayer_source.data = dict(
        factors=factors_all, r2=r2_all, output=out_all,
        model=model_all, layer=layer_all, color=color_all,
    )
    crosslayer_median_source.data = dict(
        factors=med_factors, median=med_vals, mean=mean_vals, n=n_vals,
    )
    crosslayer_fig.x_range.factors = factor_order
    method_list = ", ".join(f"'{m}'" for m in topN)
    crosslayer_fig.title.text = (
        f"Per-output R² distribution — top-{len(topN)} methods (ranked by §R0): "
        f"{method_list}; Overall (blue) vs Regional (red); thick black bar = median"
    )


def _update_eval_for_model(name: str) -> None:
    """Refresh the per-output detail (charts + table) for the chosen model."""
    art = _get_artifact(name)
    if art is None:
        per_output_source.data = {"output": [], "r2": [], "rmse": [], "mae": [], "nrmse": []}
        per_output_caption.text = ""
        _update_per_output_charts("")
        return
    csv = RESULTS_DIR / f"per_output_metrics_{name}.csv"
    if csv.exists():
        df = pd.read_csv(csv).sort_values("r2", ascending=False)
        per_output_source.data = {col: df[col].tolist() for col in df.columns}
        per_output_caption.text = (
            f"<p style='font-size:12px;color:#555;margin:2px 0'>"
            f"Showing {len(df)} non-constant outputs from "
            f"<code>per_output_metrics_{name}.csv</code>. "
            f"Click a column header to sort.</p>"
        )
    else:
        per_output_source.data = {"output": [], "r2": [], "rmse": [], "mae": [], "nrmse": []}
        per_output_caption.text = (
            f"<p style='font-size:12px;color:#a60;margin:2px 0'>"
            f"<code>per_output_metrics_{name}.csv</code> not found "
            f"— retrain to populate per-model detail.</p>"
        )
    # Refresh the new interactive per-output / per-tech / per-region charts.
    _update_per_output_charts(name)


# Initial render and per-model hook
_update_model_compare_charts()
_build_parity_grid()
_refresh_parity_grid_options()
_update_parity_grid()
_update_percase_chart()
_update_percatalog_chart()
_update_crosslayer_chart()
_update_bias_region_holder()
if model_select.options:
    _update_eval_for_model(model_select.value)
model_select.on_change(
    "value", lambda _attr, _old, new: _update_eval_for_model(new)
)


# ---------------------------------------------------------------------------
# Stage switching — swap RESULTS_DIR / DATA_PATH / etc. in-place, refresh
# every dependent widget so the user never has to leave the page.
# ---------------------------------------------------------------------------

def _set_active_stage(label: str) -> None:
    if label not in STAGE_CONFIG:
        return
    cfg = STAGE_CONFIG[label]

    global RESULTS_DIR, DATA_PATH, MODELS_DIR
    global TRAINING_DF, MODEL_PATHS, MODEL_CACHE, SUMMARY
    RESULTS_DIR = cfg["results_dir"]
    DATA_PATH = cfg["data_path"]
    MODELS_DIR = RESULTS_DIR / "models"
    TRAINING_DF = _load_training_data()
    MODEL_PATHS = _discover_models()
    MODEL_CACHE = {}  # invalidate — different stage = different artifacts
    OOF_CACHE.clear()  # parity scatter caches per-stage OOF predictions
    SUMMARY = _load_summary()
    # Cross-layer caches (used by Section 1 and Section 4, which are pinned
    # to Overall regardless of stage). Clearing here lets a mid-session
    # retrain be picked up the next time the user clicks the stage selector.
    _refresh_layer_caches()

    # Hide / restore Transmission in the Variable dropdown to match the layer.
    _sync_variable_options_for_stage(label)

    # Refresh evaluation-tab static content
    eval_summary_div.text = _summary_table_html("overall")
    eval_summary_div_regional.text = _summary_table_html("regional")
    for img_name, div in eval_image_divs.items():
        div.text = _img_html(img_name)
    # P3b: by-catalog distributional fidelity panel.
    dist_fidelity_div.text = _distfid_by_catalog_html()
    # Section 1 — dual leaderboard tables + per-method parity grid (pinned to
    # Overall, re-read in case of retrain).
    _build_parity_grid()
    _refresh_parity_grid_options()
    _update_parity_grid()
    # Section 4 (per-case) and Section 5 (per-catalog) are layer-specific;
    # Section 6 (cross-layer) reads both summaries and is independent.
    _update_percase_chart()
    _update_percatalog_chart()
    _update_crosslayer_chart()
    # Section 3 — swap the region-bias panel between figure and note.
    _update_bias_region_holder()

    # Refresh model dropdown. The on_change handler for model_select will
    # fire when ``value`` changes, so ``_update_eval_for_model`` is invoked
    # automatically. We call it explicitly afterwards too, because a no-op
    # assignment (value unchanged but options/dataset different) doesn't
    # trigger the callback.
    new_model_opts = list(MODEL_PATHS.keys())
    if new_model_opts:
        new_value = (
            model_select.value if model_select.value in new_model_opts
            else new_model_opts[0]
        )
        model_select.options = new_model_opts
        model_select.value = new_value
        model_select.disabled = False
        model_select.title = "Model"
        _update_eval_for_model(new_value)
    else:
        model_select.options = []
        model_select.value = ""
        model_select.disabled = True
        model_select.title = "Model (no artifacts found)"
        _update_eval_for_model("")

    # Re-render the predict tab with the active artifact + data
    _redraw()


stage_select.on_change("value", lambda _attr, _old, new: _set_active_stage(new))


# ---------------------------------------------------------------------------
# Layout — tabs: "Predict" (interactive) + "Evaluation results" (diagnostics)
# ---------------------------------------------------------------------------

controls = column(
    row(*[design_selects[d] for d in DIMENSION_ENCODING], spacing=8),
    row(stage_select, variable_select, model_select, spacing=12),
    status_div,
    metrics_div,
    sizing_mode="stretch_width",
)

predict_tab = TabPanel(
    child=row(
        column(plot, diff_plot, uq_plot),
        column(legend_div, ci_colorbar_fig),
        controls,
        spacing=20,
    ),
    title="Predict",
)


# ---------------------------------------------------------------------------
# §2 Prediction overlook — per-item parity grid (model × layer × category)
# ---------------------------------------------------------------------------
PRED_OVERLOOK_FIG_W = 260
PRED_OVERLOOK_FIG_H = 260
PRED_OVERLOOK_COLS = 4
PRED_OVERLOOK_MAX_PANELS = 200  # safety cap on number of panels rendered

CATEGORY_OPTIONS = ["All", "Capacity", "Generation", "System cost", "Transmission"]


def _po_initial_model(layer_short: str) -> str:
    models = list(_models_for_layer(layer_short).keys())
    if not models:
        return ""
    return "rf" if "rf" in models else models[0]


_po_initial_layer = "overall" if _models_for_layer("overall") else "regional"
_po_initial_models = list(_models_for_layer(_po_initial_layer).keys())

po_layer_select = Select(
    title="Layer", value=_po_initial_layer,
    options=list(PARITY_LAYERS), width=140,
)
po_model_select = Select(
    title="Model", value=_po_initial_model(_po_initial_layer),
    options=_po_initial_models or [""], width=180,
)
po_category_select = Select(
    title="Category", value="All", options=CATEGORY_OPTIONS, width=180,
)
po_status_div = Div(text="", sizing_mode="stretch_width")
po_holder = column(
    Div(text="<i>Loading…</i>"),
    width=PRED_OVERLOOK_FIG_W * PRED_OVERLOOK_COLS + 60,
)


def _make_singleoutput_parity_fig(output_name: str, color: str):
    """One parity subplot for a single output column (486 case-points)."""
    src = ColumnDataSource(data=dict(actual=[], predicted=[], case=[]))
    diag = ColumnDataSource(data=dict(x=[0.0, 1.0], y=[0.0, 1.0]))
    fig = figure(
        width=PRED_OVERLOOK_FIG_W, height=PRED_OVERLOOK_FIG_H,
        x_range=Range1d(start=0.0, end=1.0),
        y_range=Range1d(start=0.0, end=1.0),
        title=output_name,
        toolbar_location="above",
        tools="pan,wheel_zoom,box_zoom,reset,save",
        active_drag="box_zoom",
        active_scroll="wheel_zoom",
        x_axis_label="Actual",
        y_axis_label="Predicted",
        output_backend="webgl",
    )
    fig.toolbar.logo = None
    fig.title.text_font_size = "9pt"
    fig.line(x="x", y="y", source=diag, line_color="#444",
             line_dash="dashed", line_width=1.0)
    sct = fig.scatter(
        x="actual", y="predicted", size=5, alpha=0.7,
        fill_color=color, line_color=None, source=src,
    )
    fig.add_tools(HoverTool(
        renderers=[sct],
        tooltips=[
            ("Case", "@case"),
            ("Actual", "@actual{0,0.000}"),
            ("Predicted", "@predicted{0,0.000}"),
        ],
        point_policy="follow_mouse",
    ))
    return fig, src, diag


# Output prefixes that identify a Y column in the training CSV (everything else
# \u2014 ``x_*`` design dims and the ``case`` identifier \u2014 is metadata).
_Y_COL_PREFIXES = ("cap_", "cost_", "gen_", "runtime_", "tran_")


def _all_y_cols_for_layer(short: str) -> list[str]:
    """Full list of Y output columns in the training CSV for ``short`` layer.

    Includes ALL outputs that were in the original training data, regardless
    of whether the trainer kept them. Columns the trainer dropped (because
    their variance fell below ``min_variance_threshold``) are present here
    but absent from any model's ``y_cols``. This is what lets the parity
    grid render a warning panel for those silently-skipped outputs.
    """
    df = _training_df_for_layer(short)
    if df is None or df.empty:
        return []
    return [c for c in df.columns if c.startswith(_Y_COL_PREFIXES)]


# Visual styling for "dropped output" warning panels: muted red on a faint
# pink background so they stand out as different from the layer-coloured
# parity dots above.
_DROPPED_OUTPUT_COLOR = "#c0392b"
_DROPPED_OUTPUT_BG = "#fdecea"

# Visual styling for "trivially predicted" panels: a calm green that signals
# "this is fine — the model knows the exact value, it just isn't learned".
# Used for outputs the trainer dropped because they're constant across all
# training cases (variance \u2248 0). Distinct from the red theme above,
# which is reserved for outputs we can't predict at all.
_CONSTANT_OUTPUT_COLOR = "#1a7f37"
_CONSTANT_OUTPUT_BG = "#eaf6ec"


def _format_constant_value(v: float) -> str:
    """Format a constant Y value for use in panel titles / hovers."""
    if not np.isfinite(v):
        return "n/a"
    if v == 0:
        return "0"
    if abs(v) >= 1000:
        return f"{v:,.1f}"
    if abs(v) >= 1:
        return f"{v:,.3f}"
    return f"{v:.3g}"


def _make_constant_parity_fig(output_name: str, constant_value: float,
                              actual_values):
    """Trivially-predicted parity panel for a known-constant output.

    The trainer skipped this column because every training case has the
    same value, so there was nothing to learn. The surrogate now returns
    that constant exactly, so the prediction is perfect by construction.
    We render a single dot at ``(constant, constant)`` on the y=x line and
    annotate the panel with the value so the user can read it off the title.
    """
    actual = np.asarray(actual_values, dtype=float)
    actual = actual[np.isfinite(actual)]
    n = int(actual.size)
    src = ColumnDataSource(data=dict(
        actual=actual.tolist() if n else [constant_value],
        predicted=[constant_value] * (n if n else 1),
        case=list(range(n if n else 1)),
    ))
    diag = ColumnDataSource(data=dict(x=[0.0, 1.0], y=[0.0, 1.0]))
    val_str = _format_constant_value(constant_value)
    title_short = output_name if len(output_name) <= 24 else output_name[:22] + "\u2026"
    fig = figure(
        width=PRED_OVERLOOK_FIG_W, height=PRED_OVERLOOK_FIG_H,
        x_range=Range1d(start=0.0, end=1.0),
        y_range=Range1d(start=0.0, end=1.0),
        title=f"{title_short}  \u2261 {val_str}",
        toolbar_location="above",
        tools="pan,wheel_zoom,box_zoom,reset,save",
        active_drag="box_zoom",
        active_scroll="wheel_zoom",
        x_axis_label="Actual",
        y_axis_label="Predicted (\u2261 constant)",
        output_backend="webgl",
        background_fill_color=_CONSTANT_OUTPUT_BG,
        border_fill_color=_CONSTANT_OUTPUT_BG,
    )
    fig.toolbar.logo = None
    fig.title.text_font_size = "9pt"
    fig.title.text_color = _CONSTANT_OUTPUT_COLOR
    fig.line(x="x", y="y", source=diag, line_color="#444",
             line_dash="dashed", line_width=1.0)
    sct = fig.scatter(
        x="actual", y="predicted", size=8, alpha=0.85,
        fill_color=_CONSTANT_OUTPUT_COLOR, line_color="white",
        line_width=0.6, source=src, marker="circle",
    )
    fig.add_tools(HoverTool(
        renderers=[sct],
        tooltips=[
            ("Output", output_name),
            ("Case", "@case"),
            ("Actual", "@actual{0,0.000}"),
            ("Prediction", f"\u2261 {val_str} (constant)"),
        ],
        point_policy="follow_mouse",
    ))
    # Bound the axes symmetrically around the constant so the dot is
    # centred and the y=x line is visible. If the constant is zero use a
    # small symmetric range; otherwise pad \u00b1 10% around the value.
    c = float(constant_value) if np.isfinite(constant_value) else 0.0
    if c == 0:
        lo, hi = -1.0, 1.0
    else:
        span = max(abs(c) * 0.1, 1e-6)
        lo, hi = c - span, c + span
    diag.data = dict(x=[lo, hi], y=[lo, hi])
    fig.x_range.start = lo
    fig.x_range.end = hi
    fig.y_range.start = lo
    fig.y_range.end = hi
    return fig


def _make_dropped_parity_fig(output_name: str, actual_values):
    """Warning-style parity panel for an output the model never predicts.

    Renders the actual values along the x-axis with a constant ``y = 0``
    \u2014 the implicit prediction whenever a column is missing from the
    artifact's ``y_cols``. The y=x diagonal is still drawn so users can
    visually compare the gap between what the data shows and what the model
    would have had to learn.
    """
    actual = np.asarray(actual_values, dtype=float)
    actual = actual[np.isfinite(actual)]
    n = int(actual.size)
    src = ColumnDataSource(data=dict(
        actual=actual.tolist(),
        predicted=[0.0] * n,
        case=list(range(n)),
    ))
    diag = ColumnDataSource(data=dict(x=[0.0, 1.0], y=[0.0, 1.0]))
    fig = figure(
        width=PRED_OVERLOOK_FIG_W, height=PRED_OVERLOOK_FIG_H,
        x_range=Range1d(start=0.0, end=1.0),
        y_range=Range1d(start=0.0, end=1.0),
        title=output_name,
        toolbar_location="above",
        tools="pan,wheel_zoom,box_zoom,reset,save",
        active_drag="box_zoom",
        active_scroll="wheel_zoom",
        x_axis_label="Actual",
        y_axis_label="Predicted (always 0)",
        output_backend="webgl",
        background_fill_color=_DROPPED_OUTPUT_BG,
        border_fill_color=_DROPPED_OUTPUT_BG,
    )
    fig.toolbar.logo = None
    fig.title.text_font_size = "9pt"
    fig.title.text_color = _DROPPED_OUTPUT_COLOR
    fig.line(x="x", y="y", source=diag, line_color="#444",
             line_dash="dashed", line_width=1.0)
    sct = fig.scatter(
        x="actual", y="predicted", size=6, alpha=0.85,
        fill_color=_DROPPED_OUTPUT_COLOR, line_color="white",
        line_width=0.5, source=src, marker="x",
    )
    fig.add_tools(HoverTool(
        renderers=[sct],
        tooltips=[
            ("Output", output_name),
            ("Case", "@case"),
            ("Actual", "@actual{0,0.000}"),
            ("Prediction", "(none \u2014 dropped at training)"),
        ],
        point_policy="follow_mouse",
    ))
    # Bound the axes around the actual values; if all-zero, use a small
    # symmetric range so the y=0 strip is still visible.
    if n:
        lo = float(min(actual.min(), 0.0))
        hi = float(max(actual.max(), 0.0))
    else:
        lo, hi = -1.0, 1.0
    if not np.isfinite(lo) or not np.isfinite(hi) or lo == hi:
        lo, hi = lo - 1.0, hi + 1.0
    pad = max((hi - lo) * 0.05, 1e-6)
    lo -= pad
    hi += pad
    diag.data = dict(x=[lo, hi], y=[lo, hi])
    fig.x_range.start = lo
    fig.x_range.end = hi
    fig.y_range.start = lo
    fig.y_range.end = hi
    return fig


def _build_predoverlook_grid(*_args) -> None:
    layer = po_layer_select.value
    model = po_model_select.value
    cat = po_category_select.value
    if not model:
        po_holder.children = [Div(text="<i>No model selected.</i>")]
        po_status_div.text = ""
        return
    triple = _get_oof_pred_for_layer(layer, model)
    if triple is None:
        po_holder.children = [Div(text=(
            f"<i>Model '{model}' has no usable OOF data on the "
            f"{layer} layer.</i>"
        ))]
        po_status_div.text = ""
        return
    Y_true, Y_pred, cols = triple
    # Discover Y columns that the trainer dropped (variance below
    # ``min_variance_threshold``). They exist in the training CSV but never
    # appear in any model's ``y_cols`` \u2014 so the parity grid normally
    # hides them. We split them into two buckets:
    #   1. Known-constant   \u2192 green "trivially predicted" panels (the
    #      surrogate now returns the exact value, so the prediction is
    #      perfect by construction).
    #   2. Truly unmodelled \u2192 red warning panels (defensive: in
    #      practice empty, because every dropped column has a recorded
    #      constant value).
    df = _training_df_for_layer(layer)
    all_y = _all_y_cols_for_layer(layer)
    predicted_set = set(cols)
    dropped_cols = [c for c in all_y if c not in predicted_set]
    constants_map = _constants_for_layer(layer)
    constant_cols = [c for c in dropped_cols if c in constants_map]
    missing_cols = [c for c in dropped_cols if c not in constants_map]

    if cat != "All":
        keep_idx = [i for i, c in enumerate(cols)
                    if _output_category(c) == cat]
        constant_cols = [c for c in constant_cols
                         if _output_category(c) == cat]
        missing_cols = [c for c in missing_cols
                        if _output_category(c) == cat]
    else:
        keep_idx = list(range(len(cols)))
    total_pred = len(keep_idx)
    total_constant = len(constant_cols)
    total_missing = len(missing_cols)
    if total_pred == 0 and total_constant == 0 and total_missing == 0:
        po_holder.children = [Div(text=(
            f"<i>No outputs in category '{cat}' for "
            f"{layer}/{model}.</i>"
        ))]
        po_status_div.text = ""
        return
    truncated_pred = False
    if total_pred > PRED_OVERLOOK_MAX_PANELS:
        keep_idx = keep_idx[:PRED_OVERLOOK_MAX_PANELS]
        truncated_pred = True
    color = PARITY_LAYER_COLORS.get(layer, "#1f77b4")
    figs: list = []
    for i in keep_idx:
        col = cols[i]
        y_t = Y_true[:, i].astype(float)
        y_p = Y_pred[:, i].astype(float)
        finite = np.isfinite(y_t) & np.isfinite(y_p)
        y_t = y_t[finite]
        y_p = y_p[finite]
        if y_t.size > 1 and y_t.var() > 0:
            ss_res = float(np.sum((y_t - y_p) ** 2))
            ss_tot = float(np.sum((y_t - y_t.mean()) ** 2))
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
        else:
            r2 = float("nan")
        fig_, src, diag = _make_singleoutput_parity_fig(col, color)
        src.data = dict(
            actual=y_t.tolist(),
            predicted=y_p.tolist(),
            case=list(range(len(y_t))),
        )
        if y_t.size:
            lo = float(min(y_t.min(), y_p.min()))
            hi = float(max(y_t.max(), y_p.max()))
        else:
            lo, hi = 0.0, 1.0
        if not np.isfinite(lo) or not np.isfinite(hi) or lo == hi:
            lo, hi = lo - 1.0, hi + 1.0
        pad = max((hi - lo) * 0.05, 1e-6)
        lo -= pad
        hi += pad
        diag.data = dict(x=[lo, hi], y=[lo, hi])
        fig_.x_range.start = lo
        fig_.x_range.end = hi
        fig_.y_range.start = lo
        fig_.y_range.end = hi
        r2_str = f"R\u00b2={r2:.3f}" if np.isfinite(r2) else "R\u00b2=n/a"
        title_short = col if len(col) <= 32 else col[:30] + "\u2026"
        fig_.title.text = f"{title_short} \u00b7 {r2_str}"
        figs.append(fig_)

    # Render the "predicted" portion of the grid.
    if figs:
        rows_pred = [
            row(*figs[i:i + PRED_OVERLOOK_COLS], spacing=8)
            for i in range(0, len(figs), PRED_OVERLOOK_COLS)
        ]
        pred_block = column(*rows_pred, spacing=8)
    else:
        pred_block = Div(text=(
            f"<i>No predicted outputs in category '{cat}' for "
            f"{layer}/{model}.</i>"
        ))

    children = [pred_block]

    # Trivially-predicted (known constant) panels \u2014 green theme.
    if constant_cols:
        const_figs: list = []
        for col in constant_cols:
            value = constants_map[col]
            actuals = (
                df[col].to_numpy(dtype=float)
                if df is not None and col in df.columns
                else np.array([value])
            )
            const_figs.append(_make_constant_parity_fig(col, value, actuals))
        if const_figs:
            const_header = Div(text=(
                f"<div style='margin:18px 0 6px 0;padding:8px 12px;"
                f"background:{_CONSTANT_OUTPUT_BG};border-left:4px solid "
                f"{_CONSTANT_OUTPUT_COLOR};font-size:12px;color:#555'>"
                f"<b style='color:{_CONSTANT_OUTPUT_COLOR}'>"
                f"\u2713 {len(const_figs)} output(s) trivially predicted "
                f"(constant across all training cases).</b> "
                f"The trainer skipped these columns because their "
                f"variance is below "
                f"<code>min_variance_threshold</code> \u2014 there's "
                f"nothing for an ML model to learn. The Predict tab now "
                f"returns the exact value (\u03c3 = 0), so prediction "
                f"error is zero by construction.</div>"
            ))
            const_rows = [
                row(*const_figs[i:i + PRED_OVERLOOK_COLS], spacing=8)
                for i in range(0, len(const_figs), PRED_OVERLOOK_COLS)
            ]
            children.append(const_header)
            children.append(column(*const_rows, spacing=8))

    # Truly-missing panels (no model AND no recorded constant) \u2014 red warning.
    # In practice this list is empty because every variance-dropped column
    # is recorded in ``constant_outputs``. Kept defensively so a future
    # change to the drop rule doesn't silently hide outputs again.
    if missing_cols and df is not None and not df.empty:
        miss_figs: list = []
        for col in missing_cols:
            if col not in df.columns:
                continue
            actuals = df[col].to_numpy(dtype=float)
            miss_figs.append(_make_dropped_parity_fig(col, actuals))
        if miss_figs:
            warn_header = Div(text=(
                f"<div style='margin:18px 0 6px 0;padding:8px 12px;"
                f"background:{_DROPPED_OUTPUT_BG};border-left:4px solid "
                f"{_DROPPED_OUTPUT_COLOR};font-size:12px;color:#555'>"
                f"<b style='color:{_DROPPED_OUTPUT_COLOR}'>"
                f"\u26a0 {len(miss_figs)} output(s) not modeled.</b> "
                f"No model fit and no constant value recorded. The "
                f"surrogate has no answer for these.</div>"
            ))
            miss_rows = [
                row(*miss_figs[i:i + PRED_OVERLOOK_COLS], spacing=8)
                for i in range(0, len(miss_figs), PRED_OVERLOOK_COLS)
            ]
            children.append(warn_header)
            children.append(column(*miss_rows, spacing=8))

    po_holder.children = [column(*children, spacing=8)]
    pieces = [
        f"<b>{layer}</b> \u00b7 model <b>{model}</b> \u00b7 category "
        f"<b>{cat}</b> \u00b7 predicted <b>{len(figs)}</b> of "
        f"<b>{total_pred}</b> outputs"
        f"{' (truncated to ' + str(PRED_OVERLOOK_MAX_PANELS) + ')' if truncated_pred else ''}"
    ]
    if total_constant:
        pieces.append(
            f"<span style='color:{_CONSTANT_OUTPUT_COLOR}'>"
            f"\u2713 {total_constant} trivially predicted</span>"
        )
    if total_missing:
        pieces.append(
            f"<span style='color:{_DROPPED_OUTPUT_COLOR}'>"
            f"\u26a0 {total_missing} not modeled</span>"
        )
    po_status_div.text = (
        "<p style='font-size:12px;color:#555;margin:2px 0'>"
        + " \u00b7 ".join(pieces) + ".</p>"
    )


def _po_on_layer_change(_attr, old, new):
    if new == old:
        return
    models = list(_models_for_layer(new).keys())
    po_model_select.options = models or [""]
    if po_model_select.value not in models:
        po_model_select.value = (
            "rf" if "rf" in models else (models[0] if models else "")
        )
    _build_predoverlook_grid()


po_layer_select.on_change("value", _po_on_layer_change)
po_model_select.on_change("value", lambda _a, _o, _n: _build_predoverlook_grid())
po_category_select.on_change("value", lambda _a, _o, _n: _build_predoverlook_grid())


# ---------------------------------------------------------------------------
# §3 Regional comparison — per-BA parity grid (regional layer only)
# ---------------------------------------------------------------------------
REG_COMP_FIG_W = 260
REG_COMP_FIG_H = 260
REG_COMP_COLS = 4
REG_COMP_PER_BA_CAP = 5000  # downsample per-BA panels to keep browser responsive

_rc_initial_models = list(_models_for_layer("regional").keys())
_rc_initial_model = _po_initial_model("regional")

rc_model_select = Select(
    title="Model", value=_rc_initial_model,
    options=_rc_initial_models or [""], width=180,
)
rc_category_select = Select(
    title="Category", value="All", options=CATEGORY_OPTIONS, width=180,
)
rc_status_div = Div(text="", sizing_mode="stretch_width")
rc_holder = column(
    Div(text="<i>Loading…</i>"),
    width=REG_COMP_FIG_W * REG_COMP_COLS + 60,
)


def _make_perba_parity_fig(region_label: str, color: str):
    src = ColumnDataSource(data=dict(actual=[], predicted=[], output=[]))
    diag = ColumnDataSource(data=dict(x=[0.0, 1.0], y=[0.0, 1.0]))
    fig = figure(
        width=REG_COMP_FIG_W, height=REG_COMP_FIG_H,
        x_range=Range1d(start=0.0, end=1.0),
        y_range=Range1d(start=0.0, end=1.0),
        title=region_label,
        toolbar_location="above",
        tools="pan,wheel_zoom,box_zoom,reset,save",
        active_drag="box_zoom",
        active_scroll="wheel_zoom",
        x_axis_label="Actual",
        y_axis_label="Predicted",
        output_backend="webgl",
    )
    fig.toolbar.logo = None
    fig.title.text_font_size = "10pt"
    fig.line(x="x", y="y", source=diag, line_color="#444",
             line_dash="dashed", line_width=1.0)
    sct = fig.scatter(
        x="actual", y="predicted", size=4, alpha=0.55,
        fill_color=color, line_color=None, source=src,
    )
    fig.add_tools(HoverTool(
        renderers=[sct],
        tooltips=[
            ("Output", "@output"),
            ("Actual", "@actual{0,0.000}"),
            ("Predicted", "@predicted{0,0.000}"),
        ],
        point_policy="follow_mouse",
    ))
    return fig, src, diag


def _region_sort_key(r: str) -> int:
    if r.startswith("p") and r[1:].isdigit():
        return int(r[1:])
    return 99999


def _build_regcomp_grid(*_args) -> None:
    model = rc_model_select.value
    cat = rc_category_select.value
    if not model:
        rc_holder.children = [Div(text="<i>No model selected.</i>")]
        rc_status_div.text = ""
        return
    triple = _get_oof_pred_for_layer("regional", model)
    if triple is None:
        rc_holder.children = [Div(text=(
            f"<i>Model '{model}' has no usable OOF data on the "
            f"regional layer.</i>"
        ))]
        rc_status_div.text = ""
        return
    Y_true, Y_pred, cols = triple
    by_region: dict[str, list[int]] = {}
    for i, c in enumerate(cols):
        _, _, region = _parse_output_name(c)
        if region is None:
            continue
        if cat != "All" and _output_category(c) != cat:
            continue
        by_region.setdefault(region, []).append(i)
    if not by_region:
        rc_holder.children = [Div(text=(
            f"<i>No per-BA outputs in category '{cat}'.</i>"
        ))]
        rc_status_div.text = ""
        return
    regions_sorted = sorted(by_region.keys(), key=_region_sort_key)
    color = PARITY_LAYER_COLORS["regional"]
    rng = np.random.default_rng(42)
    figs: list = []
    for region in regions_sorted:
        idxs = by_region[region]
        out_names = np.array([cols[i] for i in idxs], dtype=object)
        Yt_slice = Y_true[:, idxs]
        Yp_slice = Y_pred[:, idxs]
        n_rows = Yt_slice.shape[0]
        out_flat = np.tile(out_names, n_rows)
        Yt_flat = Yt_slice.ravel()
        Yp_flat = Yp_slice.ravel()
        finite = np.isfinite(Yt_flat) & np.isfinite(Yp_flat)
        Yt_flat = Yt_flat[finite]
        Yp_flat = Yp_flat[finite]
        out_flat = out_flat[finite]
        n_total = len(Yt_flat)
        if n_total > 1 and Yt_flat.var() > 0:
            ss_res = float(np.sum((Yt_flat - Yp_flat) ** 2))
            ss_tot = float(np.sum((Yt_flat - Yt_flat.mean()) ** 2))
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
        else:
            r2 = float("nan")
        if n_total > REG_COMP_PER_BA_CAP:
            sel = rng.choice(n_total, REG_COMP_PER_BA_CAP, replace=False)
            Yt_flat = Yt_flat[sel]
            Yp_flat = Yp_flat[sel]
            out_flat = out_flat[sel]
        fig_, src, diag = _make_perba_parity_fig(region, color)
        src.data = dict(
            actual=Yt_flat.tolist(),
            predicted=Yp_flat.tolist(),
            output=out_flat.tolist(),
        )
        if Yt_flat.size:
            lo = float(min(Yt_flat.min(), Yp_flat.min()))
            hi = float(max(Yt_flat.max(), Yp_flat.max()))
        else:
            lo, hi = 0.0, 1.0
        if not np.isfinite(lo) or not np.isfinite(hi) or lo == hi:
            lo, hi = lo - 1.0, hi + 1.0
        pad = max((hi - lo) * 0.05, 1e-6)
        lo -= pad
        hi += pad
        diag.data = dict(x=[lo, hi], y=[lo, hi])
        fig_.x_range.start = lo
        fig_.x_range.end = hi
        fig_.y_range.start = lo
        fig_.y_range.end = hi
        r2_str = f"R²={r2:.3f}" if np.isfinite(r2) else "R²=n/a"
        fig_.title.text = f"{region} · {r2_str} ({n_total:,} pts)"
        figs.append(fig_)
    rows_ = [
        row(*figs[i:i + REG_COMP_COLS], spacing=8)
        for i in range(0, len(figs), REG_COMP_COLS)
    ]
    rc_holder.children = [column(*rows_, spacing=8)]
    rc_status_div.text = (
        f"<p style='font-size:12px;color:#555;margin:2px 0'>"
        f"Model <b>{model}</b> · category <b>{cat}</b> · "
        f"<b>{len(figs)}</b> BA panels (regional layer)."
        f"</p>"
    )


rc_model_select.on_change("value", lambda _a, _o, _n: _build_regcomp_grid())
rc_category_select.on_change("value", lambda _a, _o, _n: _build_regcomp_grid())


eval_tab = TabPanel(
    child=column(
        Div(text="<h2 style='margin:8px 0 4px 0'>ReEDS Surrogate Model "
                 "&mdash; Evaluation</h2>"
                 "<p style='color:#555;margin:0 0 10px 0;font-size:13px'>"
                 "Three views: (1) per-method parity to compare models, "
                 "(2) drill into a single model &times; layer &times; "
                 "category to see each output's parity, "
                 "(3) regional layer per-BA parity.</p>"),

        # 1. Model comparison — reuse existing per-method parity grid
        Div(text="<h3 style='margin:14px 0 4px 0'>1. Model comparison "
                 "&mdash; per-method parity (both layers)</h3>"
                 "<p style='color:#555;margin:0 0 4px 0;font-size:12px'>"
                 "One parity plot per ML method on each layer's "
                 "out-of-fold predictions. Panel title shows pooled R&sup2;. "
                 "Use the Tech / Region filters to drill in.</p>"),
        row(parity_grid_tech_select, parity_grid_region_select, spacing=10),
        parity_grid_status_div,
        parity_layer_titles["overall"],
        row(parity_holders["overall"], parity_legends["overall"], spacing=20),
        parity_layer_titles["regional"],
        row(parity_holders["regional"], parity_legends["regional"], spacing=20),

        # 2. Prediction overlook
        Div(text="<h3 style='margin:18px 0 4px 0'>2. Prediction overlook "
                 "&mdash; per-item parity</h3>"
                 "<p style='color:#555;margin:0 0 4px 0;font-size:12px'>"
                 "Pick a model, layer, and output category. One parity plot "
                 "per output column with one dot per case (~486). Panel "
                 "title shows the per-output R&sup2;. Useful for spotting "
                 "which specific outputs a model struggles with.</p>"),
        row(po_layer_select, po_model_select, po_category_select, spacing=10),
        po_status_div,
        po_holder,

        # 3. Regional comparison
        Div(text="<h3 style='margin:18px 0 4px 0'>3. Regional comparison "
                 "&mdash; per-BA parity (regional layer)</h3>"
                 "<p style='color:#555;margin:0 0 4px 0;font-size:12px'>"
                 "One parity plot per BA. Each plot pools every output "
                 "column belonging to that BA (filtered by category if "
                 "selected) across all cases. Panel title shows the pooled "
                 "R&sup2; for that BA.</p>"),
        row(rc_model_select, rc_category_select, spacing=10),
        rc_status_div,
        rc_holder,

        spacing=6,
        sizing_mode="stretch_width",
    ),
    title="Evaluation results",
)


# ---------------------------------------------------------------------------
# Research Evaluation tab (surfaces surrogate_eval.py outputs without breaking
# anything above). Lazily loads CSVs / PNGs from ``<results_dir>/eval/`` for
# the selected layer. Falls back to a "run surrogate_eval.py first" notice if
# the index file is missing.
# ---------------------------------------------------------------------------

RESEARCH_EVAL_LAYERS: tuple[str, ...] = ("overall", "regional")


def _research_eval_dir(layer_short: str) -> Path | None:
    """Locate ``<results_dir>/eval`` for the requested layer, or ``None``."""
    res_dir, _, _ = _layer_paths(layer_short)
    if res_dir is None:
        return None
    eval_dir = res_dir / "eval"
    return eval_dir if eval_dir.exists() else None


def _research_eval_load_index(layer_short: str) -> dict:
    eval_dir = _research_eval_dir(layer_short)
    if eval_dir is None:
        return {}
    p = eval_dir / "_index.json"
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _research_eval_read_csv(layer_short: str, name: str) -> pd.DataFrame:
    eval_dir = _research_eval_dir(layer_short)
    if eval_dir is None:
        return pd.DataFrame()
    p = eval_dir / name
    if not p.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(p)
    except Exception:
        return pd.DataFrame()


def _research_eval_image_b64(layer_short: str, fig_name: str) -> str:
    """Read a PNG figure from ``eval/figs`` and return a base64 data URI string."""
    eval_dir = _research_eval_dir(layer_short)
    if eval_dir is None:
        return ""
    p = eval_dir / "figs" / fig_name
    if not p.exists():
        return ""
    try:
        b = p.read_bytes()
    except Exception:
        return ""
    return "data:image/png;base64," + base64.b64encode(b).decode("ascii")


def _research_eval_df_to_source(df: pd.DataFrame) -> tuple[ColumnDataSource, list[TableColumn]]:
    """Build a ColumnDataSource + columns for a generic DataTable view."""
    if df is None or df.empty:
        return ColumnDataSource(data={"_": []}), [TableColumn(field="_", title="(empty)")]
    out: dict[str, list] = {}
    cols: list[TableColumn] = []
    for c in df.columns:
        # Floats get nice formatter; everything else as-is.
        s = df[c]
        if pd.api.types.is_float_dtype(s):
            # Choose precision based on magnitude
            arr = s.replace([np.inf, -np.inf], np.nan).dropna()
            max_abs = float(arr.abs().max()) if not arr.empty else 0.0
            fmt = "0,0.0000" if max_abs < 100 else "0,0.00"
            cols.append(TableColumn(field=str(c), title=str(c),
                                    formatter=NumberFormatter(format=fmt)))
        else:
            cols.append(TableColumn(field=str(c), title=str(c)))
        out[str(c)] = s.tolist()
    return ColumnDataSource(data=out), cols


# Per-layer index lookup at module load. Cheap (small JSON each).
RESEARCH_EVAL_INDEX: dict[str, dict] = {
    layer: _research_eval_load_index(layer) for layer in RESEARCH_EVAL_LAYERS
}


def _research_eval_default_layer() -> str:
    """Prefer 'overall' if present, else the first layer that has an index."""
    for layer in RESEARCH_EVAL_LAYERS:
        if RESEARCH_EVAL_INDEX.get(layer):
            return layer
    return RESEARCH_EVAL_LAYERS[0]


_initial_re_layer = _research_eval_default_layer()
_initial_re_index = RESEARCH_EVAL_INDEX.get(_initial_re_layer, {})
_initial_re_models = list(_initial_re_index.get("models") or [])
_initial_re_csvs = list(_initial_re_index.get("csvs") or [])
_initial_re_figs = list(_initial_re_index.get("figs") or [])
_initial_re_model = "rf" if "rf" in _initial_re_models else (
    _initial_re_models[0] if _initial_re_models else ""
)

# Layer + model selectors
research_layer_select = Select(
    title="Layer",
    value=_initial_re_layer,
    options=[l for l in RESEARCH_EVAL_LAYERS if RESEARCH_EVAL_INDEX.get(l)] or [_initial_re_layer],
    width=160,
)
research_model_select = Select(
    title="Model (drives §1/§3/§5)",
    value=_initial_re_model,
    options=_initial_re_models or [""],
    width=180,
)

# Header info
research_header_div = Div(text="", sizing_mode="stretch_width")

# §0 Headline ranking
research_rank_source, research_rank_cols = _research_eval_df_to_source(
    _research_eval_read_csv(_initial_re_layer, "model_ranking_bootstrap.csv")
)
research_rank_table = DataTable(
    source=research_rank_source, columns=research_rank_cols,
    width=1080, height=260, index_position=None, fit_columns=True,
)

# §1 Grouped by category (driven by model selector)
research_groupcat_source, research_groupcat_cols = _research_eval_df_to_source(
    _research_eval_read_csv(_initial_re_layer, f"grouped_by_category_{_initial_re_model}.csv")
    if _initial_re_model else pd.DataFrame()
)
research_groupcat_table = DataTable(
    source=research_groupcat_source, columns=research_groupcat_cols,
    width=1080, height=200, index_position=None, fit_columns=True,
)

# §1b Grouped by tech (driven by model selector)
research_grouptech_source, research_grouptech_cols = _research_eval_df_to_source(
    _research_eval_read_csv(_initial_re_layer, f"grouped_by_tech_{_initial_re_model}.csv")
    if _initial_re_model else pd.DataFrame()
)
research_grouptech_table = DataTable(
    source=research_grouptech_source, columns=research_grouptech_cols,
    width=1080, height=300, index_position=None, fit_columns=True,
)

# §3 Calibration (driven by model selector)
research_calib_source, research_calib_cols = _research_eval_df_to_source(
    _research_eval_read_csv(_initial_re_layer, f"calibration_{_initial_re_model}.csv")
    if _initial_re_model else pd.DataFrame()
)
research_calib_table = DataTable(
    source=research_calib_source, columns=research_calib_cols,
    width=1080, height=280, index_position=None, fit_columns=True,
)
research_calib_overlay_img = Div(
    text=(f'<img src="{_research_eval_image_b64(_initial_re_layer, "calibration_overlay.png")}" '
          f'style="max-width:100%;border:1px solid #ddd;background:#fff;padding:4px">'
          if "calibration_overlay.png" in _initial_re_figs else
          "<p><i>calibration_overlay.png not found.</i></p>"),
    width=1080,
)

# §5 Headline scalars (driven by model selector)
research_headline_source, research_headline_cols = _research_eval_df_to_source(
    _research_eval_read_csv(_initial_re_layer, f"headline_scalars_{_initial_re_model}.csv")
    if _initial_re_model else pd.DataFrame()
)
research_headline_table = DataTable(
    source=research_headline_source, columns=research_headline_cols,
    width=1080, height=180, index_position=None, fit_columns=True,
)

# §6 Output difficulty (one global table per layer)
research_difficulty_source, research_difficulty_cols = _research_eval_df_to_source(
    _research_eval_read_csv(_initial_re_layer, "per_output_difficulty.csv")
)
research_difficulty_table = DataTable(
    source=research_difficulty_source, columns=research_difficulty_cols,
    width=1080, height=400, index_position=None, fit_columns=True,
)

# §8 Clipping summary
research_clipping_source, research_clipping_cols = _research_eval_df_to_source(
    _research_eval_read_csv(_initial_re_layer, "clipping_summary.csv")
)
research_clipping_table = DataTable(
    source=research_clipping_source, columns=research_clipping_cols,
    width=1080, height=240, index_position=None, fit_columns=True,
)

# Auto-readout Divs for §R0 and §R5 — single-sentence summaries computed
# from the *current* run's CSVs. They sit *under* the static explainer
# callouts so a re-run automatically updates them without editing captions.
research_rank_readout_div = Div(text="", sizing_mode="stretch_width")
research_headline_readout_div = Div(text="", sizing_mode="stretch_width")


def _research_eval_inline_md_to_html(text: str) -> str:
    """Convert ``**bold**`` / ``_italic_`` / ```code``` to HTML inline tags.

    The underscore rule is word-boundary aware: an ``_`` is only treated as an
    italic toggle if it's not flanked by alphanumerics on both sides. This
    keeps identifiers like ``cost_total`` intact instead of breaking them into
    ``cost<i>total``.
    """
    out: list[str] = []
    i = 0
    in_b = in_i = in_c = False
    n = len(text)
    while i < n:
        if text[i:i + 2] == "**":
            out.append("</b>" if in_b else "<b>")
            in_b = not in_b
            i += 2
            continue
        ch = text[i]
        if ch == "_":
            prev_ch = text[i - 1] if i > 0 else " "
            next_ch = text[i + 1] if i + 1 < n else " "
            is_word_internal = prev_ch.isalnum() and next_ch.isalnum()
            if is_word_internal:
                out.append("_")
            else:
                out.append("</i>" if in_i else "<i>")
                in_i = not in_i
        elif ch == "`":
            out.append("</code>" if in_c else "<code>")
            in_c = not in_c
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _research_eval_format_readout(lines: list[str]) -> str:
    """Wrap auto-readout sentences in a small amber callout. Empty if no lines."""
    if not lines:
        return ""
    body = "<br>".join(_research_eval_inline_md_to_html(s) for s in lines)
    return (
        "<div style='background:#fff8e1;border-left:3px solid #f0a050;"
        "padding:4px 10px;margin:2px 0 6px 0;font-size:12px;"
        "color:#5b4317;line-height:1.45'>"
        f"{body}</div>"
    )


def _research_eval_update_rank_readout(layer_short: str):
    df = _research_eval_read_csv(layer_short, "model_ranking_bootstrap.csv")
    line = auto_readout_r0(df)
    research_rank_readout_div.text = _research_eval_format_readout(
        [line] if line else []
    )


def _research_eval_update_headline_readout(layer_short: str, model_name: str):
    if not model_name:
        research_headline_readout_div.text = ""
        return
    df = _research_eval_read_csv(layer_short, f"headline_scalars_{model_name}.csv")
    lines = list(auto_readout_r5(df))
    research_headline_readout_div.text = _research_eval_format_readout(lines)


# Browse-CSV pane
research_browse_csv_select = Select(
    title="Browse any CSV", value=(_initial_re_csvs[0] if _initial_re_csvs else ""),
    options=_initial_re_csvs or [""], width=420,
)
_init_browse_csv_df = (
    _research_eval_read_csv(_initial_re_layer, _initial_re_csvs[0])
    if _initial_re_csvs else pd.DataFrame()
)
research_browse_csv_source, research_browse_csv_cols = _research_eval_df_to_source(_init_browse_csv_df)
research_browse_csv_table = DataTable(
    source=research_browse_csv_source, columns=research_browse_csv_cols,
    width=1080, height=380, index_position=None, fit_columns=True,
)

# Browse-figure pane
research_browse_fig_select = Select(
    title="Browse any figure", value=(_initial_re_figs[0] if _initial_re_figs else ""),
    options=_initial_re_figs or [""], width=420,
)
research_browse_fig_div = Div(
    text=(f'<img src="{_research_eval_image_b64(_initial_re_layer, _initial_re_figs[0])}" '
          f'style="max-width:100%;border:1px solid #ddd;background:#fff;padding:4px">'
          if _initial_re_figs else
          "<p><i>No figures available — run surrogate_eval.py first.</i></p>"),
    width=1080,
)


def _research_eval_update_header(layer_short: str):
    idx = RESEARCH_EVAL_INDEX.get(layer_short, {})
    if not idx:
        research_header_div.text = (
            f"<div style='padding:8px 12px;background:#fff3cd;border-left:3px solid #f0a050'>"
            f"<b>No evaluation artifacts found</b> for layer <code>{layer_short}</code>. "
            f"Run <code>python surrogate_eval.py --output_dir &lt;results_dir&gt; "
            f"--data &lt;data_csv&gt; --layer {layer_short}</code> to generate.</div>"
        )
        return
    n_models = len(idx.get("models") or [])
    n_out = idx.get("n_outputs", "?")
    mz = idx.get("mostly_zero_count", "?")
    alphas = ", ".join(str(a) for a in (idx.get("alpha_levels") or []))
    research_header_div.text = (
        f"<div style='padding:8px 12px;background:#eef5ff;border-left:3px solid #1f4e79'>"
        f"<b>Layer:</b> {layer_short} &nbsp;|&nbsp; "
        f"<b>Models:</b> {n_models} ({', '.join(idx.get('models') or [])}) &nbsp;|&nbsp; "
        f"<b>Outputs:</b> {n_out} &nbsp;|&nbsp; "
        f"<b>Mostly-zero:</b> {mz} &nbsp;|&nbsp; "
        f"<b>α-sweep:</b> {alphas}</div>"
        f"<p style='color:#555;margin:6px 0 0 0;font-size:12px'>"
        f"Tables and figures below are loaded from "
        f"<code>{(_research_eval_dir(layer_short) or '?')}</code>. "
        f"The full prose report is in <code>REPORT.md</code> / <code>REPORT.html</code> "
        f"in that directory; this tab surfaces the headline numbers + a browser for "
        f"the rest.</p>"
    )


def _research_eval_replace_table(table: DataTable, df: pd.DataFrame):
    src, cols = _research_eval_df_to_source(df)
    table.source.data = dict(src.data)
    table.columns = cols


def _research_eval_apply_layer(layer_short: str):
    """Rewire every table / image to the selected layer."""
    idx = RESEARCH_EVAL_INDEX.get(layer_short, {})
    _research_eval_update_header(layer_short)

    # Refresh model selector with this layer's models
    models = list(idx.get("models") or [])
    research_model_select.options = models or [""]
    if research_model_select.value not in models:
        research_model_select.value = ("rf" if "rf" in models else
                                       (models[0] if models else ""))

    # Refresh the universal tables (independent of model)
    _research_eval_replace_table(
        research_rank_table,
        _research_eval_read_csv(layer_short, "model_ranking_bootstrap.csv"),
    )
    _research_eval_update_rank_readout(layer_short)
    _research_eval_replace_table(
        research_difficulty_table,
        _research_eval_read_csv(layer_short, "per_output_difficulty.csv"),
    )
    _research_eval_replace_table(
        research_clipping_table,
        _research_eval_read_csv(layer_short, "clipping_summary.csv"),
    )

    # Calibration overlay PNG
    fig_b64 = _research_eval_image_b64(layer_short, "calibration_overlay.png")
    research_calib_overlay_img.text = (
        f'<img src="{fig_b64}" style="max-width:100%;border:1px solid #ddd;'
        f'background:#fff;padding:4px">'
        if fig_b64 else "<p><i>calibration_overlay.png not found.</i></p>"
    )

    # Refresh browse dropdowns
    csvs = list(idx.get("csvs") or [])
    figs = list(idx.get("figs") or [])
    research_browse_csv_select.options = csvs or [""]
    if research_browse_csv_select.value not in csvs:
        research_browse_csv_select.value = csvs[0] if csvs else ""
    research_browse_fig_select.options = figs or [""]
    if research_browse_fig_select.value not in figs:
        research_browse_fig_select.value = figs[0] if figs else ""


def _research_eval_apply_model(layer_short: str, model_name: str):
    """Refresh tables that depend on (layer, model)."""
    if not model_name:
        return
    _research_eval_replace_table(
        research_groupcat_table,
        _research_eval_read_csv(layer_short, f"grouped_by_category_{model_name}.csv"),
    )
    _research_eval_replace_table(
        research_grouptech_table,
        _research_eval_read_csv(layer_short, f"grouped_by_tech_{model_name}.csv"),
    )
    _research_eval_replace_table(
        research_calib_table,
        _research_eval_read_csv(layer_short, f"calibration_{model_name}.csv"),
    )
    _research_eval_replace_table(
        research_headline_table,
        _research_eval_read_csv(layer_short, f"headline_scalars_{model_name}.csv"),
    )
    _research_eval_update_headline_readout(layer_short, model_name)


def _on_research_layer_change(attr, old, new):
    if new == old:
        return
    _research_eval_apply_layer(new)
    _research_eval_apply_model(new, research_model_select.value)


def _on_research_model_change(attr, old, new):
    if new == old or not new:
        return
    _research_eval_apply_model(research_layer_select.value, new)


def _on_research_browse_csv_change(attr, old, new):
    if new == old or not new:
        return
    _research_eval_replace_table(
        research_browse_csv_table,
        _research_eval_read_csv(research_layer_select.value, new),
    )


def _on_research_browse_fig_change(attr, old, new):
    if new == old or not new:
        return
    b64 = _research_eval_image_b64(research_layer_select.value, new)
    research_browse_fig_div.text = (
        f'<img src="{b64}" style="max-width:100%;border:1px solid #ddd;'
        f'background:#fff;padding:4px">'
        if b64 else "<p><i>(figure not found)</i></p>"
    )


research_layer_select.on_change("value", _on_research_layer_change)
research_model_select.on_change("value", _on_research_model_change)
research_browse_csv_select.on_change("value", _on_research_browse_csv_change)
research_browse_fig_select.on_change("value", _on_research_browse_fig_change)

# Populate initial header
_research_eval_update_header(_initial_re_layer)

# ---------------------------------------------------------------------------
# Initial render of the two driven sections in the slimmed-down "Evaluation
# results" tab. §1 (per-method parity) is already populated by the existing
# ``_build_parity_grid`` / ``_update_parity_grid`` calls higher up.
# ---------------------------------------------------------------------------
_build_predoverlook_grid()
_build_regcomp_grid()


tabs = Tabs(tabs=[predict_tab, eval_tab])
layout = column(header, tabs, sizing_mode="stretch_width")

curdoc().add_root(layout)
curdoc().title = "ReEDS Surrogate Dashboard"

# Kick off the first render
_redraw()
