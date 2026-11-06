"""Item 6 - failure-class evidence: why some outputs have low R-squared.

Per output (RF, stored 10-fold OOF, both layers): R-squared, activation
frequency (fraction of the 486 runs in which the output is non-zero),
coefficient of variation (std / |mean|), MAE as % of the mean |y|, and RMSE as
% of the output range. Sparse outputs (active in < 50 % of runs) and
near-constant outputs (CV < 2 %) are labelled.

Writes data/06_per_output_diagnostics.csv, data/06_headline_errors.csv,
figs/fig06_r2_vs_activation_cv.*, results_06.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pesgm_common import (
    DATA, HERE, HEADLINE, PALETTE, GRAY, PRETTY, category, load_layer, md_table,
    new_fig, per_output_r2, save_fig, stored_oof,
)

SPARSE_THR = 0.5
CONST_THR = 0.02


def diagnostics(layer):
    X, Y, _, y_cols, _, _ = load_layer(layer)
    P = stored_oof(layer, "rf", Y)
    r2 = per_output_r2(Y, P)
    act = (np.abs(Y) > 0).mean(axis=0)
    mean_abs = np.abs(Y).mean(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        cv = Y.std(axis=0) / np.abs(Y.mean(axis=0))
        mae_pct = 100 * np.abs(P - Y).mean(axis=0) / mean_abs
        rng = Y.max(axis=0) - Y.min(axis=0)
        nrmse_pct = 100 * np.sqrt(((P - Y) ** 2).mean(axis=0)) / rng
    df = pd.DataFrame(dict(layer=layer, output=y_cols, category=[category(c) for c in y_cols], r2=r2,
                           activation=act, cv=cv, mae_pct_of_mean=mae_pct, rmse_pct_of_range=nrmse_pct,
                           mean=Y.mean(axis=0), std=Y.std(axis=0), n_unique=[len(np.unique(Y[:, j])) for j in range(Y.shape[1])]))
    df["class"] = np.select([df.activation < SPARSE_THR, df.cv < CONST_THR], ["sparse", "near-constant"], "regular")
    return df


def main():
    d = pd.concat([diagnostics("system"), diagnostics("regional")], ignore_index=True)
    d.to_csv(DATA / "06_per_output_diagnostics.csv", index=False)
    sysd = d[d.layer == "system"].set_index("output")
    head = sysd.loc[HEADLINE, ["r2", "activation", "cv", "mae_pct_of_mean", "rmse_pct_of_range", "class"]].reset_index()
    head.to_csv(DATA / "06_headline_errors.csv", index=False)

    # ------------------------------------------------------------------ figure
    fig, axes = new_fig(height=2.4, ncols=2, sharey=True)
    cls_style = {"regular": (PALETTE[0], "o"), "sparse": (PALETTE[1], "s"), "near-constant": (PALETTE[3], "^")}
    for ax, xcol, xlab in zip(axes, ("activation", "cv"), ("Activation frequency", "Coefficient of variation")):
        for layer, alpha, size in (("regional", 0.35, 7), ("system", 0.9, 12)):
            sub = d[d.layer == layer]
            for cls, (col, mk) in cls_style.items():
                s = sub[sub["class"] == cls]
                ax.scatter(s[xcol], s.r2.clip(lower=-0.5), s=size, color=col, marker=mk, alpha=alpha, lw=0,
                           label=f"{cls}" if layer == "system" else None)
        ax.axhline(0.9, color=GRAY, lw=0.6, ls="--")
        ax.set_xlabel(xlab)
        ax.set_ylim(-0.55, 1.02)
    axes[1].set_xscale("log")
    axes[0].set_xlim(-0.03, 1.03)
    axes[0].set_ylabel("Out-of-fold R² (clipped at −0.5)")
    # label the system-layer sparse / near-constant outputs on the panels
    lab = sysd[((sysd["class"] == "sparse") & (sysd.r2 < 0.6)) | (sysd["class"] == "near-constant")]
    for name, r in lab.iterrows():
        short = name.replace("cap_", "c:").replace("gen_", "g:").replace("cost_op_", "op:").replace("cost_inv_", "inv:")
        ax = axes[0] if r["class"] == "sparse" else axes[1]
        xv = r.activation if r["class"] == "sparse" else r.cv
        ax.annotate(short, (xv, max(r.r2, -0.5)), fontsize=4.2, xytext=(2, 1), textcoords="offset points",
                    color="#52514e")
    axes[0].legend(loc="lower right", fontsize=6, markerscale=1.2)
    save_fig(fig, "fig06_r2_vs_activation_cv")

    # ------------------------------------------------------------------ text
    L = ["## 6. Failure classes: sparse and near-constant outputs\n"]
    for layer in ("system", "regional"):
        s = d[d.layer == layer]
        g = s.groupby("class").agg(n=("r2", "size"), r2_mean=("r2", "mean"), r2_median=("r2", "median"),
                                   mae_pct_median=("mae_pct_of_mean", "median"),
                                   n_below_0_5=("r2", lambda v: int((v < 0.5).sum())))
        g = g.reindex(["regular", "sparse", "near-constant"]).fillna(0)
        L.append(f"**{layer} layer ({len(s)} outputs)**: {int(g.loc['sparse', 'n'])} outputs are sparse (non-zero in "
                 f"fewer than 50 % of runs) with mean / median R-squared {g.loc['sparse', 'r2_mean']:.2f} / "
                 f"{g.loc['sparse', 'r2_median']:.2f}; {int(g.loc['near-constant', 'n'])} are near-constant (CV < 2 %) with "
                 f"mean / median R-squared {g.loc['near-constant', 'r2_mean']:.2f} / {g.loc['near-constant', 'r2_median']:.2f}; "
                 f"the remaining {int(g.loc['regular', 'n'])} regular outputs have mean / median R-squared "
                 f"{g.loc['regular', 'r2_mean']:.3f} / {g.loc['regular', 'r2_median']:.3f}.")
        low = s[s.r2 < 0.5]
        L.append(f"Of the {len(low)} {layer} outputs with R-squared below 0.5, {int((low['class'] == 'sparse').sum())} are sparse "
                 f"and {int((low['class'] == 'near-constant').sum())} are near-constant, so "
                 f"{100 * (low['class'] != 'regular').mean():.0f} % of the low-R-squared outputs fall in the two failure classes.")
        rho_a = s[["r2", "activation"]].corr(method="spearman").iloc[0, 1]
        rho_c = s[["r2", "cv"]].corr(method="spearman").iloc[0, 1]
        L.append(f"Spearman correlation of per-output R-squared with activation frequency is {rho_a:.2f} and with "
                 f"coefficient of variation {rho_c:.2f} ({layer}).")
    nuc = sysd.loc["cap_nuclear"]
    L.append(f"\ncap_nuclear takes only {int(nuc.n_unique)} distinct values across the 486 runs (CV {100 * nuc.cv:.2f} %); "
             f"its OOF R-squared is {nuc.r2:.2f} but its MAE is {nuc.mae_pct_of_mean:.3f} % of the mean, so the low "
             f"R-squared is a metric artefact of a near-constant denominator, not a prediction failure.")
    L.append("Headline-output absolute errors (RF, 10-fold OOF): " + "; ".join(
        f"{r.output} R-squared {r.r2:.2f}, MAE {r.mae_pct_of_mean:.1f} % of mean" for r in head.itertuples()) + ".")
    L.append("\nHeadline table:\n")
    L.append(md_table(head.round(3)))
    L.append("\nFigure: figs/fig06_r2_vs_activation_cv (left: R-squared vs activation frequency; right: vs CV, log "
             "scale; large markers = system layer, faint = regional; near-constant and low-R-squared sparse system outputs labelled).")
    (HERE / "results_06.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote results_06.md")


if __name__ == "__main__":
    main()
