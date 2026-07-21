"""Generate summary figures for the final report."""
import json
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
import shutil

REPO = Path(r"C:\ReEDS\ReEDS\postprocessing\reedssurr")
OUT_DIR = Path(r"C:\Users\ychen10\OneDrive - NREL\Project 18 - ReEDS Surrogate\figures")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# --------- Fig 1: case design schematic ----------
fig, ax = plt.subplots(figsize=(9, 4.2))
dims = ["Demand", "Fuel price", "Renewable cost", "Siting", "Battery cost", "Policy"]
levels = [["Lo", "Md", "Hi"]] * 5 + [["IRA", "OBBBA"]]
colors = ["#4c78a8", "#f58518", "#54a24b", "#e45756", "#72b7b2", "#b279a2"]
for i, (d, lv, c) in enumerate(zip(dims, levels, colors)):
    y = len(dims) - i
    for j, l in enumerate(lv):
        ax.add_patch(mpatches.FancyBboxPatch(
            (0.6 + j * 1.1, y - 0.32), 1.0, 0.64,
            boxstyle="round,pad=0.02", linewidth=1,
            facecolor=c, edgecolor="black", alpha=0.75))
        ax.text(1.1 + j * 1.1, y, l, ha="center", va="center",
                fontsize=11, color="white", fontweight="bold")
    ax.text(0.4, y, d, ha="right", va="center", fontsize=11)
ax.text(5.4, 6.9, "3 × 3 × 3 × 3 × 3 × 2  =  486  ReEDS runs",
        ha="center", fontsize=13, fontweight="bold")
ax.set_xlim(-2.5, 5.5); ax.set_ylim(0.2, 7.4)
ax.axis("off")
ax.set_title("Full-factorial case design (ERCOT, solve through 2050)", fontsize=12)
plt.tight_layout()
plt.savefig(OUT_DIR / "fig1_case_design.png", dpi=140, bbox_inches="tight")
plt.close()

# --------- Fig 2: model R² comparison ----------
overall_sj = json.loads((REPO / "Stage2/outputs/overall/summary.json").read_text())
regional_sj = json.loads((REPO / "Stage2/outputs/regional/summary.json").read_text())

def _r2(sj):
    return {k: v["oof_r2_mean"] for k, v in sj["models"].items()}

o = _r2(overall_sj); r = _r2(regional_sj)
model_order = ["ridge", "lasso", "knn", "xgb", "nn", "rf"]
labels = {"ridge": "Ridge", "lasso": "Lasso", "knn": "kNN",
          "xgb": "XGBoost", "nn": "MLP", "rf": "Random Forest"}
o_vals = [o.get(m, np.nan) for m in model_order]
r_vals = [r.get(m, np.nan) for m in model_order]
x = np.arange(len(model_order)); w = 0.38
fig, ax = plt.subplots(figsize=(8.5, 4.2))
n_overall = len(pd.read_csv(REPO / "Stage2/outputs/overall/per_output_metrics_rf.csv"))
n_regional = len(pd.read_csv(REPO / "Stage2/outputs/regional/per_output_metrics_rf.csv"))
ax.bar(x - w/2, o_vals, w, label=f"Overall ({n_overall} outputs)", color="#4c78a8")
ax.bar(x + w/2, r_vals, w, label=f"Regional ({n_regional} outputs)", color="#f58518")
for i, (a, b) in enumerate(zip(o_vals, r_vals)):
    if not np.isnan(a):
        ax.text(i - w/2, a + 0.01, f"{a:.2f}", ha="center", fontsize=9)
    if not np.isnan(b):
        ax.text(i + w/2, b + 0.01, f"{b:.2f}", ha="center", fontsize=9)
ax.set_xticks(x); ax.set_xticklabels([labels[m] for m in model_order])
ax.set_ylabel("Mean out-of-fold R²"); ax.set_ylim(0, 1.0)
ax.axhline(0.9, color="gray", linestyle="--", linewidth=0.8)
ax.legend(loc="lower right")
ax.set_title("Model comparison — 10-fold OOF R² (mean over all outputs)")
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(OUT_DIR / "fig2_model_comparison.png", dpi=140, bbox_inches="tight")
plt.close()

# --------- Fig 3: per-output R² bucket bar chart for RF ----------
rf_overall = pd.read_csv(REPO / "Stage2/outputs/overall/per_output_metrics_rf.csv")
rf_regional = pd.read_csv(REPO / "Stage2/outputs/regional/per_output_metrics_rf.csv")

def _buckets(r2):
    bins = [-np.inf, 0, 0.5, 0.9, np.inf]
    labels = ["R² < 0\n(unusable)", "0 – 0.5\n(weak)",
              "0.5 – 0.9\n(usable)", "R² ≥ 0.9\n(dashboard-ready)"]
    counts = pd.cut(r2, bins=bins, labels=labels).value_counts().reindex(labels)
    return counts, labels

o_counts, labels = _buckets(rf_overall["r2"])
r_counts, _ = _buckets(rf_regional["r2"])
n_o, n_r = len(rf_overall), len(rf_regional)
o_pct = 100 * o_counts / n_o
r_pct = 100 * r_counts / n_r

x = np.arange(len(labels)); w = 0.38
fig, ax = plt.subplots(figsize=(9, 4.6))
colors_bar = ["#c94b4b", "#e9a83d", "#79b473", "#3a7d44"]
b1 = ax.bar(x - w/2, o_pct, w, label=f"Overall  (n={n_o})", color="#4c78a8")
b2 = ax.bar(x + w/2, r_pct, w, label=f"Regional (n={n_r})", color="#f58518")
for i, (a, b) in enumerate(zip(o_counts, r_counts)):
    ax.text(i - w/2, o_pct.iloc[i] + 1.5, f"{a}\n({o_pct.iloc[i]:.0f}%)",
            ha="center", fontsize=9)
    ax.text(i + w/2, r_pct.iloc[i] + 1.5, f"{b}\n({r_pct.iloc[i]:.0f}%)",
            ha="center", fontsize=9)
ax.set_xticks(x); ax.set_xticklabels(labels)
ax.set_ylabel("% of outputs in this bucket")
ax.set_ylim(0, max(o_pct.max(), r_pct.max()) * 1.25)
ax.set_title("Random Forest — how many outputs are dashboard-ready?\n"
             "Per-output 10-fold OOF R² binned into decision buckets")
ax.legend(loc="upper left")
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(OUT_DIR / "fig3_rf_r2_histogram.png", dpi=140, bbox_inches="tight")
plt.close()

# --------- Fig 4: per-family RF parity plot (overall layer) ----------
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import KFold

_data = pd.read_csv(REPO / "Stage2/inputs/overall_ml_numeric_merged.csv")
_xcols = [c for c in _data.columns if c.startswith("x_")]
_ynum = _data.select_dtypes(include=[np.number])
_ycols = [c for c in _ynum.columns if not c.startswith("x_")]
X = _data[_xcols].to_numpy()
Y_all = _data[_ycols]
# Drop constant / near-constant outputs (numerical noise, not real signal)
_std = Y_all.std()
_mean_abs = Y_all.abs().mean()
_keep = Y_all.columns[(_std > 1.0) | (_std > 1e-6 * _mean_abs)].tolist()
Y = Y_all[_keep].to_numpy()

kf = KFold(n_splits=10, shuffle=True, random_state=42)
oof = np.zeros_like(Y, dtype=float)
for tr, te in kf.split(X):
    m = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
    m.fit(X[tr], Y[tr])
    oof[te] = m.predict(X[te])

families = [
    ("cap_",  "Capacity (MW)",       "#4c78a8"),
    ("gen_",  "Generation (MWh)",    "#54a24b"),
    ("cost_", "Cost ($)",            "#e45756"),
    ("tran_", "Transmission (MW)",   "#f58518"),
]
fig, axes = plt.subplots(2, 2, figsize=(10, 9))
for ax, (pfx, title, color) in zip(axes.flat, families):
    idx = [i for i, n in enumerate(_keep) if n.startswith(pfx)]
    if not idx:
        ax.set_visible(False); continue
    y_true = Y[:, idx].ravel()
    y_pred = oof[:, idx].ravel()
    # per-family R²
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - y_true.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    ax.scatter(y_true, y_pred, s=8, alpha=0.35, color=color, edgecolor="none")
    lo = min(y_true.min(), y_pred.min())
    hi = max(y_true.max(), y_pred.max())
    ax.plot([lo, hi], [lo, hi], "k--", lw=0.8, alpha=0.6)
    ax.set_xlabel("Actual"); ax.set_ylabel("Predicted (OOF)")
    ax.set_title(f"{title}  —  {len(idx)} outputs  ·  pooled R² = {r2:.3f}")
    ax.grid(alpha=0.3)
fig.suptitle("Random Forest parity by variable family (overall layer, 10-fold OOF)",
             fontsize=13, fontweight="bold")
plt.tight_layout(rect=[0, 0, 1, 0.97])
plt.savefig(OUT_DIR / "fig4_rf_parity_overall.png", dpi=140, bbox_inches="tight")
plt.close()

# per-output R² (reused by best/worst plots below)
_r2 = np.zeros(Y.shape[1])
for j in range(Y.shape[1]):
    yt, yp = Y[:, j], oof[:, j]
    ss_tot = np.sum((yt - yt.mean()) ** 2)
    _r2[j] = 1 - np.sum((yt - yp) ** 2) / ss_tot if ss_tot > 0 else np.nan


# --------- helper: parity subplot ----------
def _parity(ax, yt, yp, title, color):
    ax.scatter(yt, yp, s=14, alpha=0.5, color=color, edgecolor="none")
    lo, hi = min(yt.min(), yp.min()), max(yt.max(), yp.max())
    ax.plot([lo, hi], [lo, hi], "k--", lw=0.8, alpha=0.6)
    ax.set_xlabel("Actual"); ax.set_ylabel("Predicted (OOF)")
    ax.set_title(title, fontsize=9)
    ax.grid(alpha=0.3)


# --------- Figs 4c-4f: per-family best-N / worst-N (overall) ----------
family_specs = {
    "capacity":     ("cap_",  "Capacity (MW)",     "#4c78a8", 5),
    "generation":   ("gen_",  "Generation (MWh)",  "#54a24b", 5),
    "cost":         ("cost_", "Cost ($)",          "#e45756", 5),
    "transmission": ("tran_", "Transmission (MW)", "#f58518", 2),
}
for fam_key, (pfx, fam_title, color, k) in family_specs.items():
    idx = [i for i, n in enumerate(_keep) if n.startswith(pfx)]
    r2_sub = {i: _r2[i] for i in idx if np.isfinite(_r2[i])}
    if not r2_sub: continue
    ranked = sorted(r2_sub.items(), key=lambda kv: kv[1], reverse=True)
    k_eff = min(k, len(ranked) // 2) if len(ranked) >= 2 else 1
    if k_eff < 1: k_eff = 1
    best = ranked[:k_eff]
    worst = ranked[-k_eff:][::-1]  # worst first from the tail, reverse to descending
    cols = k_eff
    fig, axes = plt.subplots(2, cols, figsize=(3.2 * cols, 6.4), squeeze=False)
    for c, (j, r2v) in enumerate(best):
        _parity(axes[0, c], Y[:, j], oof[:, j],
                f"BEST {c+1}: {_keep[j]}\nR² = {r2v:.3f}", color)
    for c, (j, r2v) in enumerate(worst):
        _parity(axes[1, c], Y[:, j], oof[:, j],
                f"WORST {c+1}: {_keep[j]}\nR² = {r2v:.3f}", color)
    fig.suptitle(f"Random Forest — {fam_title}: top-{k_eff} best and worst outputs (overall, 10-fold OOF)",
                 fontsize=12, fontweight="bold")
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.savefig(OUT_DIR / f"fig4_{fam_key}_best_worst.png", dpi=140, bbox_inches="tight")
    plt.close()


# --------- Fig 4r: per-family pooled parity for REGIONAL layer ----------
_data_r = pd.read_csv(REPO / "Stage2/inputs/regional_ml_numeric_merged.csv")
_xcols_r = [c for c in _data_r.columns if c.startswith("x_")]
_ynum_r = _data_r.select_dtypes(include=[np.number])
_ycols_r = [c for c in _ynum_r.columns if not c.startswith("x_")]
Xr = _data_r[_xcols_r].to_numpy()
Yr_all = _data_r[_ycols_r]
_std_r = Yr_all.std(); _mabs_r = Yr_all.abs().mean()
_keep_r = Yr_all.columns[(_std_r > 1.0) | (_std_r > 1e-6 * _mabs_r)].tolist()
Yr = Yr_all[_keep_r].to_numpy()

print(f"[regional] {Xr.shape[0]} samples, {Yr.shape[1]} outputs — computing OOF...")
oof_r = np.zeros_like(Yr, dtype=float)
for tr, te in kf.split(Xr):
    m = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
    m.fit(Xr[tr], Yr[tr])
    oof_r[te] = m.predict(Xr[te])

fig, axes = plt.subplots(2, 2, figsize=(10, 9))
for ax, (pfx, title, color) in zip(axes.flat, families):
    idx = [i for i, n in enumerate(_keep_r) if n.startswith(pfx)]
    if not idx:
        ax.set_visible(False); continue
    y_true = Yr[:, idx].ravel(); y_pred = oof_r[:, idx].ravel()
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - y_true.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    ax.scatter(y_true, y_pred, s=6, alpha=0.25, color=color, edgecolor="none")
    lo, hi = min(y_true.min(), y_pred.min()), max(y_true.max(), y_pred.max())
    ax.plot([lo, hi], [lo, hi], "k--", lw=0.8, alpha=0.6)
    ax.set_xlabel("Actual"); ax.set_ylabel("Predicted (OOF)")
    ax.set_title(f"{title}  —  {len(idx)} outputs  ·  pooled R² = {r2:.3f}")
    ax.grid(alpha=0.3)
fig.suptitle("Random Forest parity by variable family (regional layer, 10-fold OOF)",
             fontsize=13, fontweight="bold")
plt.tight_layout(rect=[0, 0, 1, 0.97])
plt.savefig(OUT_DIR / "fig4r_rf_parity_regional.png", dpi=140, bbox_inches="tight")
plt.close()


# --------- Figs 4r_*: per-family best-N / worst-N (REGIONAL) ----------
_r2_r = np.zeros(Yr.shape[1])
for j in range(Yr.shape[1]):
    yt, yp = Yr[:, j], oof_r[:, j]
    ss_tot = np.sum((yt - yt.mean()) ** 2)
    _r2_r[j] = 1 - np.sum((yt - yp) ** 2) / ss_tot if ss_tot > 0 else np.nan

for fam_key, (pfx, fam_title, color, k) in family_specs.items():
    idx = [i for i, n in enumerate(_keep_r) if n.startswith(pfx)]
    r2_sub = {i: _r2_r[i] for i in idx if np.isfinite(_r2_r[i])}
    if not r2_sub: continue
    ranked = sorted(r2_sub.items(), key=lambda kv: kv[1], reverse=True)
    k_eff = min(k, len(ranked) // 2) if len(ranked) >= 2 else 1
    if k_eff < 1: k_eff = 1
    best = ranked[:k_eff]
    worst = ranked[-k_eff:][::-1]
    cols = k_eff
    fig, axes = plt.subplots(2, cols, figsize=(3.2 * cols, 6.4), squeeze=False)
    for c, (j, r2v) in enumerate(best):
        _parity(axes[0, c], Yr[:, j], oof_r[:, j],
                f"BEST {c+1}: {_keep_r[j]}\nR² = {r2v:.3f}", color)
    for c, (j, r2v) in enumerate(worst):
        _parity(axes[1, c], Yr[:, j], oof_r[:, j],
                f"WORST {c+1}: {_keep_r[j]}\nR² = {r2v:.3f}", color)
    fig.suptitle(f"Random Forest — {fam_title}: top-{k_eff} best and worst outputs (regional, 10-fold OOF)",
                 fontsize=12, fontweight="bold")
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.savefig(OUT_DIR / f"fig4r_{fam_key}_best_worst.png", dpi=140, bbox_inches="tight")
    plt.close()

print("Generated:")
for p in sorted(OUT_DIR.glob("*.png")):
    print(" ", p.name)
