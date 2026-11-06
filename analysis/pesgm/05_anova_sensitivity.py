"""Item 5 - which dial drives what: exact factorial variance decomposition.

Because the 486 runs are a complete, balanced 3^5 x 2 factorial, the total
variance of any output splits exactly into main effects, two-way interactions
and higher-order terms (classical ANOVA sum-of-squares identity). The
decomposition is applied to (a) the ReEDS outputs themselves and (b) the RF
out-of-fold predictions on the same grid, so the two share structures can be
compared term by term. RF permutation importance (sklearn, final RF per output
fitted on all 486 runs, scored on all runs, 20 repeats, seed 42) is reported
as the conventional surrogate-side importance for comparison.

Writes data/05_variance_shares.csv (long), data/05_variance_shares_wide.csv,
data/05_permutation_importance.csv, figs/fig05a_variance_shares.*,
figs/fig05b_truth_vs_rf.*, results_05.md.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.preprocessing import StandardScaler

from pesgm_common import (
    DATA, HERE, HEADLINE, DIAL_LABELS, PALETTE, GRAY, PRETTY, SEED, X_COLS,
    load_layer, md_table, new_fig, rf_estimator, save_fig, stored_oof,
)

DIALS = ["x_Dem", "x_Fuel", "x_REcost", "x_Siting", "x_Batt", "x_Pol"]


def factorial_decomposition(X: np.ndarray, y: np.ndarray, x_cols: list[str]):
    """Exact ANOVA sum-of-squares shares for a balanced full factorial.

    Returns dict {(dial,): share, (dial_a, dial_b): share, 'higher': share}.
    Row-level effects: main effect of A = cell mean over A minus grand mean;
    two-way AB = cell mean over (A, B) minus grand mean minus both main
    effects. For a balanced design the sums of squares of these row-level
    effects add up exactly to the total sum of squares."""
    df = pd.DataFrame(X, columns=x_cols)
    yc = y - y.mean()
    df["yc"] = yc
    ss_tot = float((yc ** 2).sum())
    if ss_tot <= 0:
        return None
    main = {d: df.groupby(d).yc.transform("mean").values for d in DIALS}
    shares = {(d,): float((main[d] ** 2).sum() / ss_tot) for d in DIALS}
    for a, b in combinations(DIALS, 2):
        e = df.groupby([a, b]).yc.transform("mean").values - main[a] - main[b]
        shares[(a, b)] = float((e ** 2).sum() / ss_tot)
    shares["higher"] = float(max(0.0, 1.0 - sum(shares.values())))
    return shares


def main():
    X, Y, x_cols, y_cols, _, _ = load_layer("system")
    P = stored_oof("system", "rf", Y)
    rows = []
    for out in HEADLINE:
        j = y_cols.index(out)
        for src, M in (("ReEDS", Y), ("RF-OOF", P)):
            sh = factorial_decomposition(X, M[:, j], x_cols)
            for key, v in sh.items():
                if key == "higher":
                    rows.append(dict(output=out, source=src, term="higher", dial_a="", dial_b="", share=v))
                elif len(key) == 1:
                    rows.append(dict(output=out, source=src, term="main", dial_a=key[0][2:], dial_b="", share=v))
                else:
                    rows.append(dict(output=out, source=src, term="two-way", dial_a=key[0][2:],
                                     dial_b=key[1][2:], share=v))
        print(f"  decomposed {out}", flush=True)
    long = pd.DataFrame(rows)
    long.to_csv(DATA / "05_variance_shares.csv", index=False)

    # Wide: main effects per dial + total two-way + higher, truth and RF
    def wide(src):
        d = long[long.source == src]
        main = d[d.term == "main"].pivot(index="output", columns="dial_a", values="share")
        main["two-way"] = d[d.term == "two-way"].groupby("output").share.sum()
        main["higher"] = d[d.term == "higher"].set_index("output").share
        return main.reindex(HEADLINE)
    W_t, W_rf = wide("ReEDS"), wide("RF-OOF")
    W = pd.concat({"ReEDS": W_t, "RF-OOF": W_rf}, axis=1)
    W.to_csv(DATA / "05_variance_shares_wide.csv")

    # Permutation importance of the final per-output RF (fit on all 486).
    sx = StandardScaler().fit(X)
    Xs = sx.transform(X)
    pi_rows = []
    for out in HEADLINE:
        j = y_cols.index(out)
        m = rf_estimator(SEED, n_jobs=-1).fit(Xs, Y[:, j])
        r = permutation_importance(m, Xs, Y[:, j], scoring="r2", n_repeats=20, random_state=SEED, n_jobs=1)
        imp = np.maximum(r.importances_mean, 0)
        share = imp / imp.sum() if imp.sum() > 0 else imp
        for k, c in enumerate(x_cols):
            pi_rows.append(dict(output=out, dial=c[2:], importance=r.importances_mean[k],
                                importance_sd=r.importances_std[k], share=share[k]))
    PI = pd.DataFrame(pi_rows)
    PI.to_csv(DATA / "05_permutation_importance.csv", index=False)
    PIw = PI.pivot(index="output", columns="dial", values="share").reindex(HEADLINE)

    # ------------------------------------------------------------------ fig a: stacked bars (truth)
    order = ["Dem", "Fuel", "REcost", "Siting", "Batt", "Pol", "two-way", "higher"]
    colors = PALETTE[:6] + ["#b8b7b2", "#e3e2dd"]
    hatches = [None] * 6 + ["////", None]
    fig, ax = new_fig(height=2.6)
    ys = np.arange(len(HEADLINE))[::-1]
    left = np.zeros(len(HEADLINE))
    for term, col, h in zip(order, colors, hatches):
        v = W_t[term].values
        ax.barh(ys, v, left=left, color=col, height=0.72, label=term, lw=0, hatch=h,
                edgecolor="white" if h is None else "#52514e")
        left += v
    ax.set_yticks(ys)
    ax.set_yticklabels([PRETTY[c] for c in HEADLINE], fontsize=6.5)
    ax.set_xlabel("Share of 2050 output variance across the 486 runs")
    ax.set_xlim(0, 1)
    ax.grid(axis="y", visible=False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.45, 1.16), ncol=4, fontsize=5.8,
              handlelength=1.0, columnspacing=0.8)
    save_fig(fig, "fig05a_variance_shares")

    # ------------------------------------------------------------------ fig b: truth vs RF shares
    fig, ax = new_fig(height=2.4)
    for k, dial in enumerate(["Dem", "Fuel", "REcost", "Siting", "Batt", "Pol"]):
        ax.scatter(W_t[dial], W_rf[dial], s=14, color=PALETTE[k], label=dial, lw=0, alpha=0.9)
    ax.scatter(W_t["two-way"], W_rf["two-way"], s=14, color="#52514e", marker="x", lw=0.8, label="two-way")
    ax.plot([0, 1], [0, 1], color=GRAY, lw=0.8, ls="--")
    ax.set_xlabel("Variance share in ReEDS outputs")
    ax.set_ylabel("Variance share in RF OOF predictions")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect("equal")
    ax.legend(loc="upper left", fontsize=5.8, ncol=2, columnspacing=0.6, handletextpad=0.2)
    save_fig(fig, "fig05b_truth_vs_rf")

    # ------------------------------------------------------------------ text
    L = ["## 5. Dial sensitivity from the full factorial (exact ANOVA shares)\n"]
    main_cols = ["Dem", "Fuel", "REcost", "Siting", "Batt", "Pol"]
    for out in HEADLINE:
        t = W_t.loc[out]
        r = W_rf.loc[out]
        top = t[main_cols].sort_values(ascending=False)
        pi = PIw.loc[out].sort_values(ascending=False)
        L.append(f"{out}: main effects explain {100 * t[main_cols].sum():.0f} % of its variance across the 486 runs "
                 f"(largest {top.index[0]} {100 * top.iloc[0]:.0f} %, then {top.index[1]} {100 * top.iloc[1]:.0f} %, "
                 f"{top.index[2]} {100 * top.iloc[2]:.0f} %), two-way interactions {100 * t['two-way']:.0f} % and "
                 f"higher-order terms {100 * t['higher']:.0f} %; the RF OOF predictions attribute "
                 f"{100 * r[top.index[0]]:.0f} % to {top.index[0]} and {100 * r['two-way']:.0f} % to two-way terms, and "
                 f"RF permutation importance ranks {pi.index[0]} ({100 * pi.iloc[0]:.0f} %) then {pi.index[1]} "
                 f"({100 * pi.iloc[1]:.0f} %).")
    # agreement
    diff = (W_rf[main_cols] - W_t[main_cols]).abs()
    d2 = 100 * (W_rf['two-way'] - W_t['two-way']).mean()
    dh = 100 * (W_rf['higher'] - W_t['higher']).mean()
    dm = 100 * (W_rf[main_cols].sum(axis=1) - W_t[main_cols].sum(axis=1)).mean()
    L.append(f"\nAcross the {len(HEADLINE)} headline outputs and 6 dials, the RF share of each main effect differs "
             f"from the ReEDS share by {100 * diff.values.mean():.1f} points on average (max {100 * diff.values.max():.1f} "
             f"points, for {diff.stack().idxmax()[1]} on {diff.stack().idxmax()[0]}); on average the RF predictions "
             f"put {dm:+.1f} points more of their variance into main effects, {d2:+.1f} points into two-way "
             f"interactions and {dh:+.1f} points into higher-order terms than the ReEDS outputs do, i.e. the "
             f"out-of-fold surrogate reproduces the main-effect and pairwise structure and smooths away part of the "
             f"three-way-and-higher variance.")
    rank_agree = np.mean([W_t.loc[o, main_cols].idxmax() == W_rf.loc[o, main_cols].idxmax() for o in HEADLINE])
    rank_pi = np.mean([W_t.loc[o, main_cols].idxmax() == PIw.loc[o].idxmax() for o in HEADLINE])
    L.append(f"The dominant dial is the same in ReEDS and in the RF predictions for {100 * rank_agree:.0f} % of headline "
             f"outputs, and permutation importance picks the same dominant dial for {100 * rank_pi:.0f} %.")
    tot = W_t[main_cols].mean()
    L.append("Averaged over the headline outputs the dials rank " + ", ".join(
        f"{d} ({100 * v:.0f} %)" for d, v in tot.sort_values(ascending=False).items()) +
        f", with two-way interactions at {100 * W_t['two-way'].mean():.0f} % and higher-order terms at "
        f"{100 * W_t['higher'].mean():.0f} %.")
    L.append("\nVariance shares (ReEDS outputs):\n")
    tab = (100 * W_t).round(1).reset_index()
    L.append(md_table(tab, "{:.1f}"))
    L.append("\nVariance shares (RF OOF predictions):\n")
    L.append(md_table((100 * W_rf).round(1).reset_index(), "{:.1f}"))
    L.append("\nRF permutation importance (normalised share, %):\n")
    L.append(md_table((100 * PIw).round(1).reset_index(), "{:.1f}"))
    L.append("\nFigures: figs/fig05a_variance_shares (stacked shares, ReEDS outputs), figs/fig05b_truth_vs_rf "
             "(ReEDS vs RF share per output-dial pair).")
    (HERE / "results_05.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote results_05.md")


if __name__ == "__main__":
    main()
