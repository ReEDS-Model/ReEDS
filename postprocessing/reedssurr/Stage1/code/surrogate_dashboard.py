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
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from bokeh.io import curdoc
from bokeh.layouts import column, row
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
    Span,
    TableColumn,
    TabPanel,
    Tabs,
)
from bokeh.palettes import RdYlGn11
from bokeh.plotting import figure

# Local imports — keep the module path importable when launched via ``bokeh serve``.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from surrogate_predict import DIMENSION_ENCODING, clip_physical_bounds, load_artifact, predict   # noqa: E402
from surrogate_plots import (                                              # noqa: E402
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
    tech_color,
)
from surrogate_uq import conformal_widths                                  # noqa: E402

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
_DEFAULT_OVERALL_DATA = str(_STUDY_ROOT / "inputs" / "overall_ml_numeric.csv")
_DEFAULT_REGIONAL_DIR = str(_STUDY_ROOT / "outputs" / "regional")
_DEFAULT_REGIONAL_DATA = str(_STUDY_ROOT / "inputs" / "regional_ml_numeric.csv")


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
    ("Overall (system, ~86 outputs)", Path(ARGS.overall_dir), Path(ARGS.overall_data)),
    ("Regional (per-BA, ~382 outputs)", Path(ARGS.regional_dir), Path(ARGS.regional_data)),
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
# Load training data for the "Actual" lookup (re-loaded on layer change)
# ---------------------------------------------------------------------------

def _load_training_data() -> pd.DataFrame:
    if not DATA_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(DATA_PATH)


TRAINING_DF: pd.DataFrame = _load_training_data()
TECH_MAP_DF = load_tech_map()
TECH_STYLE_DF = load_tech_style()


def _find_actual_row(levels: dict[str, str]) -> pd.Series | None:
    """Return the training row for the picked design point, or None."""
    if TRAINING_DF.empty:
        return None
    df = TRAINING_DF
    for dim, label in levels.items():
        col = f"x_{dim}"
        if col not in df.columns:
            return None
        df = df[df[col] == DIMENSION_ENCODING[dim][label]]
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
    if name not in MODEL_CACHE:
        MODEL_CACHE[name] = load_artifact(MODEL_PATHS[name])
    return MODEL_CACHE[name]


# ---------------------------------------------------------------------------
# Bokeh widgets
# ---------------------------------------------------------------------------

design_selects: dict[str, Select] = {}
for dim, levels in DIMENSION_ENCODING.items():
    default = "Md" if "Md" in levels else next(iter(levels))
    design_selects[dim] = Select(
        title=dim, value=default, options=list(levels.keys()), width=110,
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
    # STAGE_CONFIG keys are full labels (e.g. ``"Regional (per-BA, ~382 outputs)"``),
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
<h2 style='margin:0'>ReEDS Surrogate Model — Interactive Panel</h2>
<p style='color:#555;margin:2px 0 8px 0'>Pick a design point and a trained model.
The top panel shows the ReEDS-style stacked portfolio (actual vs. surrogate
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
_DIFF_HEIGHT = 320        # diff panel: predicted − actual, sandwiched between bars and CI
_UQ_HEIGHT = 240          # secondary panel showing per-category 90% CI
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


def _summary_table_html() -> str:
    if not SUMMARY:
        return ("<i>summary.json not found — run "
                "<code>python surrogate_ml_models.py</code> first.</i>")
    cfg = SUMMARY.get("config", {})
    n_out = cfg.get("n_y_outputs", "?")
    rows_html = []
    # Highlight the row with the best R² mean
    models = SUMMARY.get("models", {})
    best = max(models, key=lambda k: models[k].get("oof_r2_mean", float("-inf"))) if models else None
    for name, m in models.items():
        bg = " style='background:#eaffea'" if name == best else ""
        rows_html.append(
            f"<tr{bg}>"
            f"<td>{m.get('display_name', name)}{' &#11088;' if name == best else ''}</td>"
            f"<td style='text-align:right'>{m.get('oof_r2_mean', float('nan')):.3f}</td>"
            f"<td style='text-align:right'>{m.get('oof_r2_median', float('nan')):.3f}</td>"
            f"<td style='text-align:right'>{m.get('oof_r2_min', float('nan')):.3f}</td>"
            f"<td style='text-align:right'>{m.get('oof_r2_max', float('nan')):.3f}</td>"
            f"<td style='text-align:right'>"
            f"{m.get('n_outputs_r2_above_0.9', '?')} / {n_out}</td>"
            f"<td style='text-align:right'>"
            f"{m.get('n_outputs_r2_above_0.95', '?')} / {n_out}</td>"
            f"</tr>"
        )
    style = (
        "<style>"
        ".summ-tbl{border-collapse:collapse;font-size:12px;width:100%;margin:6px 0}"
        ".summ-tbl th,.summ-tbl td{border:1px solid #bbb;padding:4px 8px}"
        ".summ-tbl th{background:#eee;text-align:left}"
        "</style>"
    )
    return (
        style
        + f"<p style='margin:0 0 4px 0'><b>Dataset:</b> "
        f"{cfg.get('n_samples', '?')} samples &times; "
        f"{cfg.get('n_x_features', '?')} design dims &rarr; "
        f"{n_out} non-constant outputs. "
        f"<b>Evaluation:</b> {cfg.get('cv_type', '?')} "
        f"({cfg.get('evaluation', '')}).</p>"
        + "<table class='summ-tbl'>"
        + "<thead><tr><th>Model</th><th>R² mean</th><th>R² median</th>"
        + "<th>R² min</th><th>R² max</th><th>R²&gt;0.9</th><th>R²&gt;0.95</th></tr></thead>"
        + f"<tbody>{''.join(rows_html)}</tbody></table>"
    )


eval_summary_div = Div(text=_summary_table_html(), width=900)
parity_div = Div(text="", width=900)

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


def _update_eval_for_model(name: str) -> None:
    """Refresh the parity image + per-output table for the chosen model."""
    art = _get_artifact(name)
    if art is None:
        parity_div.text = "<i>No artifact loaded.</i>"
        per_output_source.data = {"output": [], "r2": [], "rmse": [], "mae": [], "nrmse": []}
        per_output_caption.text = ""
        return
    display = art.get("display_name", name)
    safe = display.replace(" ", "_").replace("(", "").replace(")", "")
    p = RESULTS_DIR / f"parity_{safe}.png"
    if p.exists():
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        parity_div.text = (
            f"<h4 style='margin:12px 0 4px 0'>OOF parity plots — {display}</h4>"
            f"<p style='color:#555;margin:0 0 6px 0;font-size:12px'>"
            f"Top row: 3 outputs with the highest R². Bottom row: 3 with the lowest.</p>"
            f"<img src='data:image/png;base64,{b64}' "
            f"style='max-width:100%;height:auto;border:1px solid #ddd;padding:4px'/>"
        )
    else:
        parity_div.text = (
            f"<h4 style='margin:12px 0 4px 0'>OOF parity plots — {display}</h4>"
            f"<i>parity_{safe}.png not found in {RESULTS_DIR}</i>"
        )
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


# Initial render and per-model hook
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
    SUMMARY = _load_summary()

    # Hide / restore Transmission in the Variable dropdown to match the layer.
    _sync_variable_options_for_stage(label)

    # Refresh evaluation-tab static content
    eval_summary_div.text = _summary_table_html()
    for img_name, div in eval_image_divs.items():
        div.text = _img_html(img_name)

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
eval_tab = TabPanel(
    child=column(
        Div(text="<h3 style='margin:8px 0 4px 0'>Model comparison "
                 "(out-of-fold cross-validation)</h3>"),
        eval_summary_div,
        Div(text="<h4 style='margin:12px 0 4px 0'>R² mean across models</h4>"),
        eval_image_divs["model_comparison_r2.png"],
        Div(text="<h4 style='margin:12px 0 4px 0'>R² distribution per output</h4>"),
        eval_image_divs["r2_distribution_per_output.png"],
        Div(text="<h4 style='margin:12px 0 4px 0'>Stacked-bar preview "
                 "(best model, 6 sampled cases)</h4>"),
        eval_image_divs["preview_capacity_stacks.png"],
        Div(text="<h4 style='margin:12px 0 4px 0'>Active-learning lift "
                 "(uncertainty- vs random-acquisition)</h4>"
                 "<p style='color:#555;margin:0 0 6px 0;font-size:12px'>"
                 "Random Forest retrained from 30 &rarr; 230 cases. "
                 "Median R² (left) and # outputs &gt; 0.9 (right) on a held-out test set. "
                 "Run <code>python surrogate_active_learning.py</code> to (re)generate.</p>"),
        eval_image_divs["active_learning_curve.png"],
        parity_div,
        Div(text="<h4 style='margin:12px 0 4px 0'>Per-output OOF metrics</h4>"),
        per_output_caption,
        per_output_table,
        spacing=6,
        sizing_mode="stretch_width",
    ),
    title="Evaluation results",
)

tabs = Tabs(tabs=[predict_tab, eval_tab])
layout = column(header, tabs, sizing_mode="stretch_width")

curdoc().add_root(layout)
curdoc().title = "ReEDS Surrogate Dashboard"

# Kick off the first render
_redraw()
