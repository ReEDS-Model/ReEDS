"""
Shared visualization helpers for the ReEDS surrogate model pipeline.

What this module gives you
--------------------------
1) Tech aggregation that mirrors bokehpivot: raw ReEDS tech names
   (e.g. ``upv_1``, ``wind-ons_3``, ``gas-cc_h_1x1``, ``battery_li``) are
   collapsed onto the display names from
   ``postprocessing/bokehpivot/in/reeds2/tech_map.csv`` (e.g. ``UPV``,
   ``Onshore Wind``, ``Gas-CC``, ``Battery``) and colored using
   ``tech_style.csv``.

2) A matplotlib helper that draws a ReEDS-style **stacked capacity
   portfolio** as side-by-side ``Actual`` vs ``Predicted`` bars for one
   case, with consistent colors and stack order.

3) A grid helper that picks a handful of representative cases and writes
   a single PNG so you can eyeball "is this surrogate any good?" at a
   glance after training.

These helpers are imported by ``surrogate_ml_models.py`` (for the
training-time preview) and ``surrogate_dashboard.py`` (for the
interactive panel).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Tech style / mapping loaders
# ---------------------------------------------------------------------------

# Resolve postprocessing/bokehpivot/in/reeds2/ regardless of where this script
# is invoked from. After the Stage1 refactor this file lives at
# postprocessing/reedssurr/Stage1/code/, so we walk up to postprocessing/.
_BOKEH_DIR = Path(__file__).resolve().parents[3] / "bokehpivot" / "in" / "reeds2"


def load_tech_style(style_path: Optional[Path] = None) -> pd.DataFrame:
    """Return tech_style.csv as a DataFrame indexed by display tech name."""
    style_path = style_path or (_BOKEH_DIR / "tech_style.csv")
    df = pd.read_csv(style_path)
    df = df.set_index("order")
    return df


def load_tech_map(map_path: Optional[Path] = None) -> pd.DataFrame:
    """Return tech_map.csv as a DataFrame with `raw` and `display` columns.

    The raw side may contain trailing ``*`` wildcards (e.g. ``upv*``,
    ``coal*``) which are treated as prefix matches in :func:`raw_to_display`.
    """
    map_path = map_path or (_BOKEH_DIR / "tech_map.csv")
    df = pd.read_csv(map_path, dtype=str).fillna("")
    return df


def _build_tech_lookup(tech_map: pd.DataFrame) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Split tech_map into exact and prefix lookups for fast resolution."""
    exact: dict[str, str] = {}
    prefix: list[tuple[str, str]] = []
    for raw, display in zip(tech_map["raw"], tech_map["display"]):
        raw = raw.strip()
        display = display.strip()
        if not raw:
            continue
        if raw.endswith("*"):
            prefix.append((raw[:-1].lower(), display))
        else:
            exact[raw.lower()] = display
    # Longest prefix first so e.g. "coal-ccs_mod" wins over "coal".
    prefix.sort(key=lambda kv: -len(kv[0]))
    return exact, prefix


def raw_to_display(raw_tech: str, exact: dict[str, str], prefix: list[tuple[str, str]]) -> str:
    """Map a raw ReEDS tech name to its bokehpivot display name.

    Falls back to a title-cased version of the raw name if no rule matches,
    so unknown techs are still rendered (just without an official color).
    """
    key = raw_tech.lower()
    if key in exact:
        return exact[key]
    for pfx, display in prefix:
        if key.startswith(pfx):
            return display
    return raw_tech


# ---------------------------------------------------------------------------
# Column parsing
# ---------------------------------------------------------------------------

# Stage 1 capacity columns look like ``cap_<tech>``.
# Stage 2 capacity columns look like ``cap_<tech>_<region>`` where region
# starts with a single letter (p/s/r/...) followed by digits.
_REGION_RE = re.compile(r"_(p|s|r|st)\d+$", re.IGNORECASE)


def _strip_region_suffix(tech: str) -> str:
    """Drop a trailing ReEDS region tag (e.g. ``_p60``) if present."""
    return _REGION_RE.sub("", tech)


def _extract_region(tech: str) -> Optional[str]:
    """Return the trailing region tag (e.g. ``p60``) if the name ends with one."""
    m = _REGION_RE.search(tech)
    if m is None:
        return None
    return tech[m.start() + 1:]  # drop the leading underscore


def aggregate_cap_to_techs(
    cap_series: pd.Series,
    tech_map_df: Optional[pd.DataFrame] = None,
    prefix: str = "cap_",
) -> pd.Series:
    """Collapse a row of raw ``<prefix>*`` columns into display-tech totals.

    Parameters
    ----------
    cap_series
        A pandas Series whose index entries all start with ``prefix``. Values
        are in the source units (MW for capacity, MWh for generation, ...).
        Stage 1 (system) and Stage 2 (regional) layouts are both accepted;
        region suffixes are stripped before mapping.
    tech_map_df
        Optional pre-loaded tech_map (saves IO if called in a loop).
    prefix
        Column prefix to filter on. Defaults to ``"cap_"`` for backward
        compatibility; pass ``"gen_"`` for generation aggregation.
    """
    tech_map_df = tech_map_df if tech_map_df is not None else load_tech_map()
    exact, prefix_lookup = _build_tech_lookup(tech_map_df)

    totals: dict[str, float] = {}
    for col, val in cap_series.items():
        if not col.startswith(prefix):
            continue
        raw = col[len(prefix):]
        raw = _strip_region_suffix(raw)
        display = raw_to_display(raw, exact, prefix_lookup)
        totals[display] = totals.get(display, 0.0) + float(val)
    return pd.Series(totals, name=cap_series.name)


def aggregate_cap_to_tech_region(
    cap_series: pd.Series,
    tech_map_df: Optional[pd.DataFrame] = None,
    prefix: str = "cap_",
) -> pd.DataFrame:
    """Collapse Stage-2 ``<prefix><tech>_<region>`` columns to (region, tech).

    Returns a wide DataFrame indexed by region (sorted) with one column per
    display-tech (also sorted by tech_style canonical order). Cells carry
    the source units. Columns from Stage-1 layouts (no region suffix) are
    dropped silently.
    """
    tech_map_df = tech_map_df if tech_map_df is not None else load_tech_map()
    exact, prefix_lookup = _build_tech_lookup(tech_map_df)

    totals: dict[tuple[str, str], float] = {}
    for col, val in cap_series.items():
        if not col.startswith(prefix):
            continue
        raw = col[len(prefix):]
        region = _extract_region(raw)
        if region is None:
            continue
        raw_tech = _strip_region_suffix(raw)
        display = raw_to_display(raw_tech, exact, prefix_lookup)
        key = (region, display)
        totals[key] = totals.get(key, 0.0) + float(val)
    if not totals:
        return pd.DataFrame()
    s = pd.Series(totals)
    s.index = pd.MultiIndex.from_tuples(s.index, names=["region", "tech"])
    wide = s.unstack("tech", fill_value=0.0)
    # Sort regions naturally (p60, p61, …) and techs by canonical order.
    def _region_sort_key(r: str) -> tuple:
        # Split letter prefix and integer suffix for natural ordering.
        for i, ch in enumerate(r):
            if ch.isdigit():
                return (r[:i], int(r[i:]))
        return (r, 0)
    wide = wide.reindex(sorted(wide.index, key=_region_sort_key))
    wide = wide.reindex(columns=order_techs(wide.columns))
    wide.columns.name = "tech"
    return wide


def order_techs(techs: Iterable[str], style_df: Optional[pd.DataFrame] = None) -> list[str]:
    """Return techs sorted in canonical tech_style.csv order (unknowns last)."""
    style_df = style_df if style_df is not None else load_tech_style()
    style_order = list(style_df.index)
    rank = {name: i for i, name in enumerate(style_order)}
    return sorted(techs, key=lambda t: (rank.get(t, len(style_order)), t))


def tech_color(tech: str, style_df: Optional[pd.DataFrame] = None) -> str:
    """Return the bokehpivot hex color for a display tech (gray for unknowns)."""
    style_df = style_df if style_df is not None else load_tech_style()
    if tech in style_df.index:
        return str(style_df.loc[tech, "color"])
    return "#999999"


# ---------------------------------------------------------------------------
# System cost & transmission aggregators (used by the dashboard view selector)
# ---------------------------------------------------------------------------

# Cost-category bucket labels, ordering, and colors come straight from
# bokehpivot's reeds2 metadata so the dashboard matches the official ReEDS
# stacked-bar plots exactly:
#   * cost_cat_map.csv    raw cost column name -> display bucket
#   * cost_cat_style.csv  display bucket -> hex color (also defines order)
#   * trtype_style.csv    transmission trtype -> hex color
# Loaded lazily so import-time failures (missing bokehpivot in some scripts)
# fall back to a plain palette and don't crash the importer.


def load_cost_cat_style(style_path: Optional[Path] = None) -> pd.DataFrame:
    """Return ``cost_cat_style.csv`` as a DataFrame indexed by bucket label."""
    style_path = style_path or (_BOKEH_DIR / "cost_cat_style.csv")
    df = pd.read_csv(style_path)
    df = df.set_index("order")
    return df


def load_cost_cat_map(map_path: Optional[Path] = None) -> pd.DataFrame:
    """Return ``cost_cat_map.csv`` mapping raw cost column -> display bucket."""
    map_path = map_path or (_BOKEH_DIR / "cost_cat_map.csv")
    df = pd.read_csv(map_path, dtype=str).fillna("")
    return df


def _build_cost_lookup(cost_map: pd.DataFrame) -> dict[str, str]:
    """Lower-cased exact lookup ``raw -> display`` from ``cost_cat_map.csv``."""
    return {
        str(r).strip().lower(): str(d).strip()
        for r, d in zip(cost_map["raw"], cost_map["display"])
        if str(r).strip()
    }


def load_trtype_style(style_path: Optional[Path] = None) -> pd.DataFrame:
    """Return ``trtype_style.csv`` as a DataFrame indexed by trtype."""
    style_path = style_path or (_BOKEH_DIR / "trtype_style.csv")
    df = pd.read_csv(style_path)
    df = df.set_index("order")
    return df


# Lazy module-level caches so repeated lookups don't re-read the CSVs.
_COST_CAT_MAP_DF: Optional[pd.DataFrame] = None
_COST_CAT_STYLE_DF: Optional[pd.DataFrame] = None
_COST_LOOKUP: Optional[dict[str, str]] = None
_TRTYPE_STYLE_DF: Optional[pd.DataFrame] = None


def _ensure_cost_caches() -> tuple[dict[str, str], pd.DataFrame]:
    global _COST_CAT_MAP_DF, _COST_CAT_STYLE_DF, _COST_LOOKUP
    if _COST_CAT_MAP_DF is None:
        _COST_CAT_MAP_DF = load_cost_cat_map()
    if _COST_CAT_STYLE_DF is None:
        _COST_CAT_STYLE_DF = load_cost_cat_style()
    if _COST_LOOKUP is None:
        _COST_LOOKUP = _build_cost_lookup(_COST_CAT_MAP_DF)
    return _COST_LOOKUP, _COST_CAT_STYLE_DF


def _ensure_trtype_cache() -> pd.DataFrame:
    global _TRTYPE_STYLE_DF
    if _TRTYPE_STYLE_DF is None:
        _TRTYPE_STYLE_DF = load_trtype_style()
    return _TRTYPE_STYLE_DF


def _cost_bucket(col: str) -> str:
    """Map a ``cost_*`` column name to its bokehpivot display bucket.

    Strips any trailing ReEDS region suffix before lookup so Stage-2
    columns like ``cost_op_fom_costs_p60`` resolve via the same key as
    ``cost_op_fom_costs``. Unknown columns fall back to ``"Other"`` so
    they're still rendered (just without an official color).
    """
    lookup, _ = _ensure_cost_caches()
    raw = col[len("cost_"):]
    raw_no_region = _strip_region_suffix(raw)
    return lookup.get(raw_no_region.lower(), "Other")


def _cost_canonical_order() -> list[str]:
    """Bucket order from ``cost_cat_style.csv`` (plus a final ``Other``)."""
    _, style_df = _ensure_cost_caches()
    order = list(style_df.index)
    if "Other" not in order:
        order.append("Other")
    return order


def _order_cost_buckets(buckets: Iterable[str]) -> list[str]:
    canonical = _cost_canonical_order()
    rank = {name: i for i, name in enumerate(canonical)}
    return sorted(buckets, key=lambda b: (rank.get(b, len(canonical)), b))


def aggregate_cost_to_buckets(series: pd.Series) -> pd.Series:
    """Collapse ``cost_*`` columns into bokehpivot cost-category buckets.

    Returns a Series in canonical ``cost_cat_style.csv`` order; values share
    the source units (dollars). Excludes ``cost_total`` to avoid double
    counting.
    """
    totals: dict[str, float] = {}
    for col, val in series.items():
        if not isinstance(col, str) or not col.startswith("cost_"):
            continue
        if col == "cost_total" or col.startswith("cost_total_"):
            continue
        bucket = _cost_bucket(col)
        totals[bucket] = totals.get(bucket, 0.0) + float(val)
    ordered = _order_cost_buckets(totals.keys())
    return pd.Series({b: totals[b] for b in ordered})


def aggregate_cost_to_region_bucket(series: pd.Series) -> pd.DataFrame:
    """Wide DataFrame indexed by region, columns = cost buckets (dollars).

    Looks for ``cost_<...>_<region>`` columns; columns without a region
    suffix are ignored. Result rows are sorted naturally (p60, p61, ...).
    """
    totals: dict[tuple[str, str], float] = {}
    for col, val in series.items():
        if not isinstance(col, str) or not col.startswith("cost_"):
            continue
        if col == "cost_total" or col.startswith("cost_total_"):
            continue
        raw = col[len("cost_"):]
        region = _extract_region(raw)
        if region is None:
            continue
        bucket = _cost_bucket(col)
        key = (region, bucket)
        totals[key] = totals.get(key, 0.0) + float(val)
    if not totals:
        return pd.DataFrame()
    s = pd.Series(totals)
    s.index = pd.MultiIndex.from_tuples(s.index, names=["region", "bucket"])
    wide = s.unstack("bucket", fill_value=0.0)

    def _region_sort_key(r: str) -> tuple:
        for i, ch in enumerate(r):
            if ch.isdigit():
                return (r[:i], int(r[i:]))
        return (r, 0)
    wide = wide.reindex(sorted(wide.index, key=_region_sort_key))
    # Bucket column order from bokehpivot canonical ordering.
    ordered_cols = _order_cost_buckets(wide.columns)
    return wide[ordered_cols]


def cost_color(bucket: str) -> str:
    """Stable hex color for a cost bucket label (bokehpivot palette)."""
    _, style_df = _ensure_cost_caches()
    if bucket in style_df.index:
        return str(style_df.loc[bucket, "color"])
    return "#999999"


def trtype_color(trtype: str) -> str:
    """Stable hex color for a transmission trtype (bokehpivot palette)."""
    style_df = _ensure_trtype_cache()
    if trtype in style_df.index:
        return str(style_df.loc[trtype, "color"])
    return "#999999"


def aggregate_transmission_overall(series: pd.Series) -> pd.Series:
    """Sum ``tran_*`` columns into per-trtype totals (system-wide).

    Picks up Stage-1 totals like ``tran_AC_total`` and Stage-2 corridor
    breakdowns like ``tran_p60_p61_AC`` alike; trtype is taken from the
    last token after the final underscore.
    """
    totals: dict[str, float] = {}
    for col, val in series.items():
        if not isinstance(col, str) or not col.startswith("tran_"):
            continue
        if col == "tran_total":
            continue  # avoid double-counting against per-trtype sum
        body = col[len("tran_"):]
        # tran_AC_total -> "AC"; tran_p60_p61_AC -> "AC"
        if body.endswith("_total"):
            trtype = body[: -len("_total")]
        else:
            trtype = body.split("_")[-1]
        totals[trtype] = totals.get(trtype, 0.0) + float(val)
    return pd.Series(totals).sort_index()


def aggregate_transmission_by_corridor(series: pd.Series) -> pd.Series:
    """Sum ``tran_<r1>_<r2>_<trtype>`` columns by corridor label.

    Only fires for Stage-2 data (corridor columns must contain at least
    two ``p\\d+`` tokens). Returns a Series indexed by ``"p60-p61"`` style
    labels, values summed across trtypes for that corridor.
    """
    import re
    pat = re.compile(r"^(p\d+)_(p\d+)(?:_(.+))?$")
    totals: dict[str, float] = {}
    for col, val in series.items():
        if not isinstance(col, str) or not col.startswith("tran_"):
            continue
        body = col[len("tran_"):]
        m = pat.match(body)
        if not m:
            continue
        label = f"{m.group(1)}-{m.group(2)}"
        totals[label] = totals.get(label, 0.0) + float(val)

    def _key(label: str) -> tuple:
        a, b = label.split("-")
        return (int(a[1:]), int(b[1:]))

    return pd.Series({k: totals[k] for k in sorted(totals, key=_key)})


# ---------------------------------------------------------------------------
# Stacked bar plot: predicted vs actual
# ---------------------------------------------------------------------------

def plot_capacity_stack(
    actual: pd.Series,
    predicted: pd.Series,
    title: str = "",
    ax=None,
    unit_scale: float = 1e-3,    # MW -> GW
    unit_label: str = "GW",
    legend: bool = True,
):
    """Draw side-by-side Actual / Predicted stacked-bar capacity portfolios.

    Both inputs must be display-tech series (see :func:`aggregate_cap_to_techs`).
    Returns the Matplotlib ``Axes`` so callers can tweak further.
    """
    import matplotlib.pyplot as plt

    style_df = load_tech_style()
    all_techs = order_techs(set(actual.index) | set(predicted.index), style_df=style_df)
    # Drop techs that are zero in both bars to avoid an unreadable legend.
    all_techs = [
        t for t in all_techs
        if (actual.get(t, 0.0) + predicted.get(t, 0.0)) * unit_scale > 1e-6
    ]

    if ax is None:
        _, ax = plt.subplots(figsize=(4.5, 5.5))

    x_positions = [0, 1]
    x_labels = ["Actual", "Predicted"]
    base_pos = np.zeros(2, dtype=float)
    base_neg = np.zeros(2, dtype=float)

    for tech in all_techs:
        vals = np.array(
            [actual.get(tech, 0.0), predicted.get(tech, 0.0)], dtype=float
        ) * unit_scale
        color = tech_color(tech, style_df=style_df)
        # Split into +/- so retirements/negative deltas stack correctly when
        # callers ever pass deltas instead of levels.
        pos = np.clip(vals, 0, None)
        neg = np.clip(vals, None, 0)
        if pos.any():
            ax.bar(x_positions, pos, bottom=base_pos, color=color, edgecolor="white",
                   linewidth=0.4, width=0.7, label=tech)
            base_pos = base_pos + pos
        if neg.any():
            ax.bar(x_positions, neg, bottom=base_neg, color=color, edgecolor="white",
                   linewidth=0.4, width=0.7,
                   label=tech if not pos.any() else None)
            base_neg = base_neg + neg

    ax.set_xticks(x_positions)
    ax.set_xticklabels(x_labels)
    ax.set_ylabel(f"Capacity ({unit_label})")
    if title:
        ax.set_title(title, fontsize=10)
    ax.axhline(0, color="black", linewidth=0.5)
    ax.grid(axis="y", linestyle=":", alpha=0.4)

    # Totals on top of each bar
    totals = base_pos + base_neg
    ymax = max(totals.max() if totals.size else 0.0, 1.0)
    for x, t in zip(x_positions, totals):
        ax.text(x, t + 0.02 * ymax, f"{t:,.0f}", ha="center", va="bottom",
                fontsize=8, color="black")
    ax.set_ylim(top=ymax * 1.12)

    if legend and all_techs:
        # De-duplicate handles (a tech with both +/- contributions gets two).
        handles, labels = ax.get_legend_handles_labels()
        seen: dict[str, object] = {}
        for h, lab in zip(handles, labels):
            if lab not in seen:
                seen[lab] = h
        ax.legend(
            seen.values(), seen.keys(),
            loc="center left", bbox_to_anchor=(1.02, 0.5),
            fontsize=7, frameon=False,
        )
    return ax


# ---------------------------------------------------------------------------
# Training-time preview grid
# ---------------------------------------------------------------------------

def _pick_preview_indices(
    X: np.ndarray,
    n_max: int = 6,
    rng_seed: int = 0,
) -> list[int]:
    """Pick a small spread of sample indices: corners of the design space + random."""
    n = X.shape[0]
    if n <= n_max:
        return list(range(n))
    rng = np.random.default_rng(rng_seed)
    chosen: list[int] = []

    # Centroid + extremes give a quick read on bias.
    centroid = X.mean(axis=0)
    chosen.append(int(np.argmin(np.linalg.norm(X - centroid, axis=1))))
    chosen.append(int(np.argmax(np.linalg.norm(X - centroid, axis=1))))

    pool = [i for i in range(n) if i not in chosen]
    rng.shuffle(pool)
    chosen.extend(pool[: n_max - len(chosen)])
    return chosen[:n_max]


def plot_stacked_preview_grid(
    Y_true: np.ndarray,
    Y_pred: np.ndarray,
    y_cols: list[str],
    case_names: Optional[list[str]],
    x_cols: list[str],
    X: np.ndarray,
    output_dir: Path,
    model_display_name: str,
    n_cases: int = 6,
) -> Optional[Path]:
    """Write a PNG with N side-by-side actual/predicted capacity stacks.

    Returns the output path, or ``None`` if there are no capacity columns
    (e.g. user trained on a Y subset that excluded ``cap_*``).
    """
    import matplotlib.pyplot as plt

    cap_idx = [i for i, c in enumerate(y_cols) if c.startswith("cap_")]
    if not cap_idx:
        return None

    tech_map_df = load_tech_map()
    cap_cols = [y_cols[i] for i in cap_idx]

    sample_idx = _pick_preview_indices(X, n_max=n_cases)
    ncols = min(3, len(sample_idx))
    nrows = int(np.ceil(len(sample_idx) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 5.5 * nrows),
                             squeeze=False)

    for plot_i, sample_i in enumerate(sample_idx):
        ax = axes[plot_i // ncols][plot_i % ncols]
        actual_raw = pd.Series(Y_true[sample_i, cap_idx], index=cap_cols)
        pred_raw = pd.Series(Y_pred[sample_i, cap_idx], index=cap_cols)
        actual = aggregate_cap_to_techs(actual_raw, tech_map_df=tech_map_df)
        predicted = aggregate_cap_to_techs(pred_raw, tech_map_df=tech_map_df)

        if case_names is not None:
            title = case_names[sample_i]
        else:
            title = ", ".join(
                f"{c.replace('x_', '')}={int(v)}"
                for c, v in zip(x_cols, X[sample_i])
            )
        plot_capacity_stack(actual, predicted, title=title, ax=ax,
                            legend=(plot_i == 0))

    # Hide any unused axes
    for i in range(len(sample_idx), nrows * ncols):
        axes[i // ncols][i % ncols].axis("off")

    fig.suptitle(
        f"Capacity portfolio: Actual vs OOF prediction — {model_display_name}",
        fontsize=12, y=1.0,
    )
    fig.tight_layout()
    out_path = output_dir / "preview_capacity_stacks.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path
