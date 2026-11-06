"""Item 14 - candidate figures for the PESGM paper (no model fitting).

Every figure uses the stored OOF predictions (raw, no constraints) unless
its name says otherwise, the training CSVs, or tables already computed by
earlier items (05 ANOVA, 06 diagnostics, 01 calibration, 02 learning
curve, 10 constraint results). IEEE style from pesgm_common (8 pt sans,
3.5 in single column / 7.16 in double column), no titles, PDF + 300 dpi PNG
under figs/. Writes data/14_figure_numbers.json with the numbers each
caption quotes.
"""
from __future__ import annotations

import json
import re

import geopandas as gpd
import numpy as np
import pandas as pd

from pesgm_common import (
    DATA, GRAY, INK, LAYERS, PALETTE, REPO, load_layer, per_output_r2, save_fig, set_style,
)

plt = set_style()
from matplotlib.colors import BoundaryNorm, ListedColormap  # noqa: E402
from matplotlib.patches import Patch, Rectangle  # noqa: E402

N = {}   # numbers quoted by the captions
FAM = {"cap": ("Capacity", PALETTE[0]), "gen": ("Generation", PALETTE[1]),
       "cost": ("Cost", PALETTE[2]), "tran": ("Transmission", PALETTE[3]),
       "runtime": ("Run time", GRAY)}
MODELS = [("ridge", "Ridge"), ("lasso", "Lasso"), ("knn", "k-NN"), ("xgb", "XGBoost"),
          ("ngboost", "NGBoost"), ("nn", "MLP"), ("rf", "RF")]
ERCOT = ["p60", "p61", "p62", "p63", "p64", "p65", "p67"]
SEQ = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5",
       "#2a78d6", "#1c5cab", "#104281"]          # sequential blue, 0.0-1.0 in 0.1 steps
NEG = "#e3a08a"                                  # R2 < 0 (separate class, not on the ramp)
NOTMOD = "#e6e5e1"                               # not modelled (never built / constant)


def fig(w=3.5, h=2.4, **kw):
    f, a = plt.subplots(figsize=(w, h), **kw)
    return f, a


def family(c):
    return c.split("_")[0] if c.split("_")[0] in FAM else "runtime"


# ---------------------------------------------------------------- data
Xs, Ys, x_cols, sc, _, sconst = load_layer("system", clip=False)
_, Ysc, _, _, _, _ = load_layer("system")
_, Yr, _, rc, _, rconst = load_layer("regional", clip=False)
_, Yrc, _, _, _, _ = load_layer("regional")
RES = np.load(DATA / "10_stored_residuals.npz")
OOF = {(l, m): (Ysc if l == "system" else Yrc) - RES[f"{l}_{m}"].astype(float)
       for l in ("system", "regional") for m, _ in MODELS}
R2 = {(l, m): pd.Series(per_output_r2(Ys if l == "system" else Yr, OOF[(l, m)]),
                        index=sc if l == "system" else rc)
      for l in ("system", "regional") for m, _ in MODELS}
DIAG = pd.read_csv(DATA / "06_per_output_diagnostics.csv")


# ---------------------------------------------------------------- 1 ercot_map
def ercot_map():
    shp = REPO / "inputs" / "shapefiles"
    ba = gpd.read_file(shp / "US_PCA" / "US_PCA.shp")
    tx = ba[ba.st == "tx"]
    state = gpd.GeoSeries([tx.unary_union], crs=tx.crs)
    ercot = tx[tx.rb.isin(ERCOT)]
    f, ax = fig(3.5, 2.8)
    ax.set_axis_off()
    ercot.plot(ax=ax, color="#cde2fb", edgecolor="#52514e", linewidth=0.6, zorder=1)
    state.boundary.plot(ax=ax, color=INK, linewidth=0.9, zorder=2)
    for r, g in zip(ercot.rb, ercot.geometry):
        p = g.representative_point()
        ax.text(p.x, p.y, r, ha="center", va="center", fontsize=8, color=INK, zorder=3)
    ax.set_aspect("equal")
    save_fig(f, "ercot_map")


# ---------------------------------------------------------------- 2 case_design
def case_design():
    rows = [("Demand", ["EER baseline", "EER IRA-low", "EER 100% by 2050"]),
            ("Natural gas supply", ["Low supply\n(high price)", "Reference", "High supply\n(low price)"]),
            ("Wind & solar cost", ["ATB advanced", "ATB moderate", "ATB conservative"]),
            ("Wind & solar siting", ["Open", "Reference", "Limited"]),
            ("Battery cost", ["ATB advanced", "ATB moderate", "ATB conservative"]),
            ("Policy", ["IRA", "OBBBA", None])]
    f, ax = fig(3.5, 2.5)
    ax.set_axis_off()
    x0, cw, rh = 1.05, 0.80, 0.30
    for j, h in enumerate(["0 (Lo)", "1 (Md)", "2 (Hi)"]):
        ax.text(x0 + (j + 0.5) * cw, 0.12, h, ha="center", va="center", fontsize=7, color="#52514e")
    for i, (name, lv) in enumerate(rows):
        y = 0.30 + i * rh
        ax.text(x0 - 0.05, y + rh / 2, name, ha="right", va="center", fontsize=7)
        for j, t in enumerate(lv):
            if t is None:
                continue
            ax.add_patch(Rectangle((x0 + j * cw + 0.02, y + 0.02), cw - 0.04, rh - 0.04,
                                   facecolor="#eef3fb", edgecolor="#9ec5f4", linewidth=0.6))
            ax.text(x0 + (j + 0.5) * cw, y + rh / 2, t, ha="center", va="center", fontsize=6)
    ax.text(x0 + 1.5 * cw, 0.30 + 6 * rh + 0.12, "3$^5$ × 2 = 486 ReEDS runs (ERCOT, through 2050)",
            ha="center", va="center", fontsize=7.5)
    ax.set_xlim(-0.2, x0 + 3 * cw + 0.02)
    ax.set_ylim(0.30 + 6 * rh + 0.25, 0.0)
    save_fig(f, "case_design")


# ---------------------------------------------------------------- 3 buckets_rf
BUCKETS = [(-np.inf, 0, "< 0"), (0, 0.5, "0–0.5"), (0.5, 0.9, "0.5–0.9"), (0.9, np.inf, "≥ 0.9")]


def buckets_rf():
    f, ax = fig(3.5, 2.4)
    x = np.arange(4)
    w = 0.38
    for k, (layer, lab, col) in enumerate((("system", "System", PALETTE[0]), ("regional", "Regional", PALETTE[1]))):
        r2 = R2[(layer, "rf")].to_numpy()
        cnt = [int(((r2 >= lo) & (r2 < hi)).sum()) for lo, hi, _ in BUCKETS]
        pct = 100 * np.array(cnt) / len(r2)
        N[f"buckets_{layer}"] = dict(zip([b[2] for b in BUCKETS], cnt))
        xs = x + (k - 0.5) * w
        ax.bar(xs, pct, w * 0.92, color=col, label=f"{lab} (n = {len(r2)})")
        for xi, p, n in zip(xs, pct, cnt):
            ax.text(xi, p + 1, f"{n}\n{p:.0f}%", ha="center", va="bottom", fontsize=5.5, color=INK)
    ax.set_xticks(x, [b[2] for b in BUCKETS])
    ax.set_xlabel("Out-of-fold R² (Random Forest)")
    ax.set_ylabel("Share of outputs (%)")
    ax.set_ylim(0, 62)
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper left")
    save_fig(f, "buckets_rf")


# ---------------------------------------------------------------- 4 rankings
def r2_ranking_system():
    s = R2[("system", "rf")].sort_values()
    lo = -0.5
    f, ax = fig(3.5, 6.8)
    y = np.arange(len(s))
    cols = [FAM[family(c)][1] for c in s.index]
    ax.barh(y, np.clip(s.to_numpy(), lo, 1), height=0.72, color=cols)
    for yi, v in zip(y, s.to_numpy()):
        if v < 0:
            ax.text(max(v, lo) - 0.02, yi, f"{v:.2f}", ha="right", va="center", fontsize=5)
    ax.axvline(0, color=INK, linewidth=0.6)
    ax.axvline(0.9, color=GRAY, linewidth=0.6, linestyle=(0, (3, 2)))
    ax.set_yticks(y, s.index, fontsize=4.6)
    ax.set_ylim(-0.7, len(s) - 0.3)
    ax.set_xlim(lo - 0.2, 1.0)
    ax.set_xlabel("Out-of-fold R² (Random Forest, system)")
    ax.grid(axis="y", visible=False)
    used = [k for k in FAM if any(family(c) == k for c in s.index)]
    ax.legend(handles=[Patch(color=FAM[k][1], label=FAM[k][0]) for k in used], loc="lower right")
    save_fig(f, "r2_ranking_system")


def r2_ranking_regional():
    s = R2[("regional", "rf")].sort_values(ascending=False)
    lo = -0.5
    f, ax = fig(3.5, 2.4)
    x = np.arange(1, len(s) + 1)
    for k in ("cap", "gen", "cost", "tran"):
        m = np.array([family(c) == k for c in s.index])
        ax.scatter(x[m], np.clip(s.to_numpy()[m], lo, 1), s=6, color=FAM[k][1], label=FAM[k][0],
                   linewidths=0)
    ax.axhline(0.9, color=GRAY, linewidth=0.6, linestyle=(0, (3, 2)))
    ax.axhline(0, color=INK, linewidth=0.6)
    ax.set_xlabel("Rank of regional output (best to worst)")
    ax.set_ylabel("Out-of-fold R² (RF)")
    ax.set_ylim(lo - 0.05, 1.03)
    ax.set_xlim(0, len(s) + 2)
    ax.legend(loc="lower left", ncol=2, markerscale=1.5)
    N["regional_below_neg05"] = int((s < lo).sum())
    save_fig(f, "r2_ranking_regional")


# ---------------------------------------------------------------- 5 ba_heatmap
def ba_heatmap():
    r2 = R2[("regional", "rf")]
    d = DIAG[DIAG.layer == "regional"].set_index("output")
    df = pd.DataFrame({"r2": r2})
    df["region"] = [re.search(r"_(p\d+)$", c).group(1) if re.search(r"_(p\d+)$", c) else None for c in df.index]
    df = df[df.region.notna()]
    df["base"] = [re.sub(r"_p\d+$", "", c) for c in df.index]
    df["cls"] = d.loc[df.index, "class"]
    grid = df.pivot_table(index="base", columns="region", values="r2").reindex(columns=ERCOT)
    weak = df.groupby("base").cls.apply(lambda c: (c != "regular").mean() > 0.5)
    order = []
    for flag in (False, True):
        b = grid.loc[weak[weak == flag].index]
        order += b.mean(axis=1).sort_values(ascending=False).index.tolist()
    grid = grid.loc[order]
    n_reg = int((~weak).sum())
    N["ba_heatmap_rows"] = dict(regular=n_reg, sparse_or_flat=int(weak.sum()))
    cmap = ListedColormap([NEG] + SEQ)
    cmap.set_bad(NOTMOD)
    norm = BoundaryNorm([-1e9, 0] + list(np.linspace(0.1, 1.0, 10)), cmap.N)
    f, ax = fig(3.5, 0.098 * len(grid) + 0.75)
    im = ax.imshow(np.ma.masked_invalid(grid.to_numpy(float)), aspect="auto", cmap=cmap, norm=norm,
                   interpolation="nearest")
    ax.axhline(n_reg - 0.5, color=INK, linewidth=0.8)
    ax.text(len(ERCOT) - 0.45, n_reg - 0.5, " sparse /\n near-constant\n below", fontsize=5, va="top",
            ha="left", color="#52514e")
    ax.set_xticks(range(len(ERCOT)), ERCOT, fontsize=6.5)
    ax.xaxis.tick_top()
    ax.set_yticks(range(len(grid)), grid.index, fontsize=4.3)
    ax.tick_params(length=0)
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    cb = f.colorbar(im, ax=ax, fraction=0.045, pad=0.25, ticks=[-0.5, 0.1, 0.5, 0.9, 1.0])
    cb.ax.set_yticklabels(["< 0", "0.1", "0.5", "0.9", "1"], fontsize=6)
    cb.set_label("Out-of-fold R² (RF); grey = not modelled", fontsize=6.5)
    cb.outline.set_visible(False)
    save_fig(f, "ba_heatmap")


# ---------------------------------------------------------------- 6 model_comparison
def model_comparison():
    f, axes = plt.subplots(2, 1, figsize=(3.5, 3.0), sharex=True)
    x = np.arange(len(MODELS))
    w = 0.38
    tab = {}
    for ax, layer in zip(axes, ("system", "regional")):
        mean = [R2[(layer, m)].mean() for m, _ in MODELS]
        med = [R2[(layer, m)].median() for m, _ in MODELS]
        tab[layer] = {lab: (round(a, 3), round(b, 3)) for (_, lab), a, b in zip(MODELS, mean, med)}
        ax.bar(x - w / 2, mean, w * 0.92, color=PALETTE[0], label="Mean")
        ax.bar(x + w / 2, med, w * 0.92, color=PALETTE[1], label="Median")
        ax.set_ylim(0, 1)
        ax.set_ylabel(f"R² ({layer})")
        ax.grid(axis="x", visible=False)
    axes[0].legend(loc="upper left", ncol=2)
    axes[1].set_xticks(x, [lab for _, lab in MODELS])
    N["model_comparison"] = tab
    save_fig(f, "model_comparison")


# ---------------------------------------------------------------- 7 pred_vs_actual
def pred_vs_actual():
    panels = [("cost_total", "Total system cost", 1e-9, "$B"), ("tran_total", "Transmission", 1e-3, "GW"),
              ("cap_wind-ons", "Onshore wind capacity", 1e-3, "GW"), ("cap_upv", "Utility PV capacity", 1e-3, "GW"),
              ("cap_battery_li", "Battery capacity", 1e-3, "GW"), ("gen_gas-cc", "Gas-CC generation", 1e-6, "TWh")]
    f, axes = plt.subplots(2, 3, figsize=(7.16, 4.4))
    P = OOF[("system", "rf")]
    for ax, (c, name, sc_, unit), tag in zip(axes.flat, panels, "abcdef"):
        y, p = Ys[:, sc.index(c)] * sc_, P[:, sc.index(c)] * sc_
        lo, hi = min(y.min(), p.min()), max(y.max(), p.max())
        pad = 0.04 * (hi - lo)
        ax.plot([lo - pad, hi + pad], [lo - pad, hi + pad], color=GRAY, linewidth=0.8, zorder=1)
        ax.scatter(y, p, s=5, color=PALETTE[0], alpha=0.55, linewidths=0, zorder=2)
        ax.set_xlim(lo - pad, hi + pad)
        ax.set_ylim(lo - pad, hi + pad)
        ax.set_aspect("equal")
        ax.text(0.04, 0.96, f"({tag}) {name}\nR² = {R2[('system', 'rf')][c]:.2f}", transform=ax.transAxes,
                va="top", ha="left", fontsize=7)
        ax.set_xlabel(f"ReEDS ({unit})")
        ax.set_ylabel(f"Surrogate, out-of-fold ({unit})")
    save_fig(f, "pred_vs_actual")


# ---------------------------------------------------------------- 8 failure_classes
def failure_classes():
    f, ax = fig(3.5, 2.6)
    lo = -0.45
    for layer, col, s_, a in (("regional", PALETTE[1], 5, 0.55), ("system", PALETTE[0], 11, 0.9)):
        d = DIAG[DIAG.layer == layer]
        ax.scatter(100 * d.activation, np.clip(d.r2, lo, 1), s=s_, color=col, alpha=a, linewidths=0,
                   label=f"{layer.capitalize()} ({len(d)})")
    d = DIAG[DIAG.layer == "system"].set_index("output")
    lab = ["cap_nuclear", "cap_nuclear-smr", "cost_inv_h2_production", "cost_inv_h2_storage",
           "cap_Gas-CC_Gas-CC-CCS_mod", "cap_H2-CT"]
    # label positions in data coordinates (x in %, y in R2), chosen to avoid overlaps
    pos = {"cap_nuclear": (72, -0.30), "cap_nuclear-smr": (14, 0.13), "cost_inv_h2_production": (14, 0.02),
           "cost_inv_h2_storage": (14, -0.13), "cap_Gas-CC_Gas-CC-CCS_mod": (14, 0.40),
           "cap_H2-CT": (24, 0.70)}
    for c in lab:
        ax.annotate(c, (100 * d.loc[c, "activation"], max(d.loc[c, "r2"], lo)), xytext=pos[c],
                    textcoords="data", fontsize=5.2, color=INK, va="center",
                    arrowprops=dict(arrowstyle="-", color=GRAY, linewidth=0.4, shrinkA=0, shrinkB=2))
    ax.axhline(0, color=INK, linewidth=0.6)
    ax.set_xlabel("Runs with a non-zero value (%)")
    ax.set_ylabel("Out-of-fold R² (RF)")
    ax.set_ylim(lo - 0.05, 1.05)
    ax.legend(loc="lower center")
    N["failure_classes_class_counts"] = {f"{a}/{b}": int(n) for (a, b), n in
                                         DIAG.groupby(["layer", "class"]).size().items()}
    save_fig(f, "failure_classes")


# ---------------------------------------------------------------- 9 constraints_effect
def constraints_effect():
    J = json.loads((DATA / "10_after_fix.json").read_text())
    F = J["four_numbers"]
    fl = pd.read_csv(DATA / "10_audit_tran_floor.csv")
    reg = fl[fl.layer == "regional"].groupby(["model", "predictions"]).n_below.sum()
    items = [("Cost identity\n(runs)", F["cost_before"], F["cost_after"]),
             ("Additivity\n(pairs)", F["add_before"][0], F["add_after"][0]),
             ("Below floor\nRF", int(reg[("Random Forest", "stored OOF")]), int(reg[("Random Forest", "after fix")])),
             ("Below floor\nMLP", int(reg[("MLP", "stored OOF")]), int(reg[("MLP", "after fix")])),
             ("Below floor\nRidge", int(reg[("Ridge", "stored OOF")]), int(reg[("Ridge", "after fix")]))]
    N["constraints_effect"] = {k.replace("\n", " "): (b, a) for k, b, a in items}
    f, ax = fig(3.5, 2.5)
    x = np.arange(len(items))
    w = 0.38
    for k, (lab, col, idx) in enumerate((("Without rules", GRAY, 1), ("With rules", PALETTE[0], 2))):
        vals = np.array([it[idx] for it in items], float)
        xs = x + (k - 0.5) * w
        ax.bar(xs, np.where(vals > 0, vals, np.nan), w * 0.92, color=col, label=lab)
        for xi, v in zip(xs, vals):
            ax.text(xi, max(v, 1) * 1.15, f"{int(v):,}", ha="center", va="bottom", fontsize=5.5, color=INK)
    ax.set_yscale("log")
    ax.set_ylim(0.8, 1e5)
    ax.set_xticks(x, [it[0] for it in items], fontsize=6)
    ax.set_ylabel("Violations (count, log scale)")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper right")
    save_fig(f, "constraints_effect")


# ---------------------------------------------------------------- 10 dial_sensitivity
def dial_sensitivity():
    v = pd.read_csv(DATA / "05_variance_shares.csv")
    v = v[v.source == "ReEDS"]
    outs = ["cost_total", "tran_total", "cap_wind-ons", "cap_upv", "cap_gas-cc", "cap_battery_li",
            "cap_gas-ct", "gen_gas-cc"]
    names = {"cost_total": "Total cost", "tran_total": "Transmission", "cap_wind-ons": "Wind cap.",
             "cap_upv": "UPV cap.", "cap_gas-cc": "Gas-CC cap.", "cap_battery_li": "Battery cap.",
             "cap_gas-ct": "Gas-CT cap.", "gen_gas-cc": "Gas-CC gen."}
    dials = [("Dem", "Demand"), ("Fuel", "Gas supply"), ("REcost", "Wind & solar cost"),
             ("Siting", "Siting"), ("Batt", "Battery cost"), ("Pol", "Policy")]
    f, ax = fig(3.5, 2.7)
    y = np.arange(len(outs))[::-1]
    left = np.zeros(len(outs))
    tab = {}
    for k, (dcode, dname) in enumerate(dials):
        sh = np.array([v[(v.output == o) & (v.term == "main") & (v.dial_a == dcode)].share.sum() for o in outs])
        ax.barh(y, 100 * sh, left=100 * left, height=0.7, color=PALETTE[k], label=dname,
                edgecolor="white", linewidth=0.4)
        left += sh
        tab[dname] = dict(zip(outs, np.round(100 * sh, 1)))
    inter = 1 - left
    ax.barh(y, 100 * inter, left=100 * left, height=0.7, color="#d9d7d2", label="Interactions",
            edgecolor="white", linewidth=0.4)
    tab["Interactions"] = dict(zip(outs, np.round(100 * inter, 1)))
    N["dial_sensitivity_pct"] = tab
    ax.set_yticks(y, [names[o] for o in outs])
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of ReEDS output variance (%)")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.45, -0.2), ncol=4, fontsize=6, handlelength=1)
    save_fig(f, "dial_sensitivity")


# ---------------------------------------------------------------- 12 optional (re-plots)
def ci_coverage():
    c = pd.read_csv(DATA / "01_coverage_per_output.csv")
    c = c[(c.method == "rf_conformal") & (c.nominal == 0.9)]
    f, ax = fig(3.5, 2.3)
    bins = np.arange(0.85, 0.9501, 0.005)
    for layer, col in (("system", PALETTE[0]), ("regional", PALETTE[1])):
        v = np.clip(c[c.layer == layer].coverage.to_numpy(), bins[0], bins[-1] - 1e-9)
        ax.hist(v, bins=bins, color=col, alpha=0.75, label=f"{layer.capitalize()} ({len(v)})",
                weights=np.full(len(v), 100 / len(v)))
        N[f"ci_coverage_{layer}"] = dict(median=round(float(np.median(v)), 3), min=round(float(v.min()), 3),
                                         frac_ge_085=round(float((v >= 0.85).mean()), 3))
    ax.axvline(0.9, color=INK, linewidth=0.8)
    ax.set_xlabel("Empirical coverage of the 90% interval (out-of-fold)")
    ax.set_ylabel("Share of outputs (%)")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper left")
    save_fig(f, "ci_coverage")


def learning_curve():
    lc = pd.read_csv(DATA / "02_learning_curve.csv")
    lc = lc[lc["eval"] == "oof"]
    g = lc.groupby("n").r2_mean
    f, ax = fig(3.5, 2.3)
    ax.scatter(lc.n, lc.r2_mean, s=7, color=PALETTE[0], alpha=0.5, linewidths=0, label="Repeat")
    ax.plot(g.mean().index, g.mean().to_numpy(), color=PALETTE[0], linewidth=1.2, marker="o",
            markersize=3, label="Mean of 5 repeats")
    ax.set_xlabel("Training runs (n)")
    ax.set_ylabel("Mean out-of-fold R² (RF, system)")
    ax.legend(loc="lower right")
    N["learning_curve_mean"] = {int(k): round(float(v), 3) for k, v in g.mean().items()}
    save_fig(f, "learning_curve")


def main():
    for fn in (ercot_map, case_design, buckets_rf, r2_ranking_system, r2_ranking_regional, ba_heatmap,
               model_comparison, pred_vs_actual, failure_classes, constraints_effect, dial_sensitivity,
               ci_coverage, learning_curve):
        fn()
    (DATA / "14_figure_numbers.json").write_text(json.dumps(N, indent=1, default=str))
    print(json.dumps(N, indent=1, default=str)[:4000])


if __name__ == "__main__":
    main()
