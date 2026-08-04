"""
Generate "R² at a glance" ranking heatmaps for the Random-Forest surrogate.

Two figures are produced (RF only):

  * ``fig5_r2_ranking_overall.png``  — the ~66 system-total outputs as a single
    ranked column: highest R² at the top, lowest at the bottom, each cell
    coloured by its R² and annotated with the value. One glance tells you which
    outputs the surrogate nails and which it misses.

  * ``fig5r_r2_ranking_regional.png`` — the per-BA outputs as a grid with one
    column per ERCOT region (p60…p67) and one row per base variable, rows sorted
    by mean R² across regions. Blank cells = that variable is not modelled in
    that region.

Inputs are the small, version-controlled ``per_output_metrics_rf.csv`` files that
the training pipeline writes next to ``summary.json`` (NOT the large *.joblib
models, which live outside the repo).

Usage
-----
    python surrogate_r2_heatmap.py
    python surrogate_r2_heatmap.py --figures_dir "D:\\some\\other\\figures"
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import Normalize

_HERE = Path(__file__).resolve().parent
_STUDY_ROOT = _HERE.parent  # .../Stage2

# Default output location: the OneDrive deliverables figures folder used by the
# report + slides. Override with --figures_dir on another machine.
_DEFAULT_FIGURES_DIR = (
    r"C:\Users\ychen10\OneDrive - NREL\Project 18 - ReEDS Surrogate\figures"
)

# Diverging-ish colour scale: red = poor, yellow = middling, green = excellent.
_CMAP = plt.get_cmap("RdYlGn").copy()
_CMAP.set_under("#7a0000")   # R² < 0  (worse than predicting the mean)
_CMAP.set_bad("#e6e6e6")     # missing cell (regional grid)
_NORM = Normalize(vmin=0.0, vmax=1.0)


def _region_of(name: str) -> str | None:
    m = re.search(r"_(p\d+)$", name)
    return m.group(1) if m else None


def _base_of(name: str) -> str:
    return re.sub(r"_p\d+$", "", name)


# ---------------------------------------------------------------------------
# Overall: single ranked column
# ---------------------------------------------------------------------------
def plot_overall(metrics_csv: Path, out_path: Path) -> Path:
    df = pd.read_csv(metrics_csv)
    df = df[["output", "r2"]].dropna().sort_values("r2", ascending=False)
    r2 = df["r2"].to_numpy(dtype=float)
    labels = df["output"].tolist()
    n = len(df)

    fig_h = max(6.0, 0.22 * n + 1.0)
    fig, ax = plt.subplots(figsize=(4.8, fig_h))

    data = r2.reshape(-1, 1)
    ax.imshow(data, aspect="auto", cmap=_CMAP, norm=_NORM)

    ax.set_xticks([])
    ax.set_yticks(range(n))
    ax.set_yticklabels(labels, fontsize=6)
    ax.tick_params(length=0)

    # Annotate each cell with its R² (dark text on light cells, white on dark).
    for i, v in enumerate(r2):
        disp = max(0.0, min(1.0, v))
        txt_col = "white" if (v < 0 or disp > 0.75 or disp < 0.28) else "black"
        ax.text(0, i, f"{v:.2f}", ha="center", va="center",
                fontsize=5.5, color=txt_col)

    ax.set_title("RF R² ranking — system outputs\n(high → low)", fontsize=9)
    sm = plt.cm.ScalarMappable(cmap=_CMAP, norm=_NORM)
    cbar = fig.colorbar(sm, ax=ax, fraction=0.06, pad=0.02)
    cbar.set_label("R² (out-of-fold)", fontsize=8)
    cbar.ax.tick_params(labelsize=7)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return out_path


# ---------------------------------------------------------------------------
# Regional: base-variable rows × region columns
# ---------------------------------------------------------------------------
def plot_regional(metrics_csv: Path, out_path: Path) -> Path:
    df = pd.read_csv(metrics_csv)[["output", "r2"]].dropna()
    df["region"] = df["output"].map(_region_of)
    df["base"] = df["output"].map(_base_of)
    df = df[df["region"].notna()]

    regions = sorted(df["region"].unique(), key=lambda r: int(r[1:]))
    grid = df.pivot_table(index="base", columns="region", values="r2",
                          aggfunc="mean")
    grid = grid.reindex(columns=regions)
    # Sort rows by mean R² across the regions where the variable exists.
    grid = grid.loc[grid.mean(axis=1, skipna=True).sort_values(ascending=False).index]

    rows = grid.index.tolist()
    n = len(rows)
    masked = np.ma.masked_invalid(grid.to_numpy(dtype=float))

    fig_h = max(6.0, 0.20 * n + 1.0)
    fig, ax = plt.subplots(figsize=(6.4, fig_h))
    ax.imshow(masked, aspect="auto", cmap=_CMAP, norm=_NORM)

    ax.set_xticks(range(len(regions)))
    ax.set_xticklabels(regions, fontsize=8)
    ax.set_yticks(range(n))
    ax.set_yticklabels(rows, fontsize=5.5)
    ax.tick_params(length=0)
    ax.set_xlabel("ERCOT region (BA)", fontsize=8)

    ax.set_title("RF R² ranking — per-BA outputs\n(rows sorted high → low; grey = not modelled)",
                 fontsize=9)
    sm = plt.cm.ScalarMappable(cmap=_CMAP, norm=_NORM)
    cbar = fig.colorbar(sm, ax=ax, fraction=0.04, pad=0.02)
    cbar.set_label("R² (out-of-fold)", fontsize=8)
    cbar.ax.tick_params(labelsize=7)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return out_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overall_csv",
                        default=str(_STUDY_ROOT / "outputs" / "overall"
                                    / "per_output_metrics_rf.csv"))
    parser.add_argument("--regional_csv",
                        default=str(_STUDY_ROOT / "outputs" / "regional"
                                    / "per_output_metrics_rf.csv"))
    parser.add_argument("--figures_dir", default=_DEFAULT_FIGURES_DIR)
    args = parser.parse_args()

    figs = Path(args.figures_dir)
    p1 = plot_overall(Path(args.overall_csv), figs / "fig5_r2_ranking_overall.png")
    print(f"wrote {p1}")
    p2 = plot_regional(Path(args.regional_csv), figs / "fig5r_r2_ranking_regional.png")
    print(f"wrote {p2}")


if __name__ == "__main__":
    main()
