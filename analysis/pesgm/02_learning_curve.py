"""Item 2 - RF learning curve: OOF R-squared vs number of training runs.

For n in {50, 100, 150, 200, 300, 400, 486} and 5 repeats: draw a random
subset of n runs (seed 42 + repeat), run the pipeline's 10-fold CV
(KFold shuffle, seed 42 + repeat) on that subset and score the OOF
predictions on the subset. Repeat 0 at n = 486 is the exact draft
configuration (seed 42) and reproduces its numbers. As a second, lower-
variance estimate, each subset model is also fitted on all n runs and scored
on the 486 - n runs that were not drawn (external test set; R-squared with the pooled
variance over all 486 runs as denominator so that small complements do not
blow it up).

System layer, 66 outputs. Writes data/02_learning_curve.csv,
figs/fig02_learning_curve.*, results_02.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pesgm_common import (
    DATA, HERE, PALETTE, GRAY, SEED, HEADLINE8, load_layer, md_table, new_fig,
    per_output_r2, r2_summary, rf_fit_predict, rf_oof, save_fig,
)

SIZES = [50, 100, 150, 200, 300, 400, 486]
N_REP = 5


def main():
    X, Y, _, y_cols, _, _ = load_layer("system")
    n_all = len(X)
    hidx = [y_cols.index(c) for c in HEADLINE8]
    rows = []
    for n in SIZES:
        for rep in range(N_REP):
            seed = SEED + rep
            rng = np.random.default_rng(seed)
            sub = np.sort(rng.choice(n_all, size=n, replace=False)) if n < n_all else np.arange(n_all)
            Xs, Ys = X[sub], Y[sub]
            # Drop outputs constant within the subset (R2 undefined); the
            # pipeline does the same on the full table.
            keep = Ys.std(axis=0) > 1e-9
            oof, _, _ = rf_oof(Xs, Ys[:, keep], seed=SEED, fold_seed=seed)
            r2 = np.full(Y.shape[1], np.nan)
            r2[keep] = per_output_r2(Ys[:, keep], oof)
            s = r2_summary(r2[keep])
            row = dict(n=n, rep=rep, eval="oof", n_outputs=int(keep.sum()), r2_mean=s["mean"],
                       r2_median=s["median"], n_ge_0_9=s["n_ge_0_9"], n_ge_0_95=s["n_ge_0_95"])
            row.update({f"r2_{y_cols[j]}": r2[j] for j in hidx})
            rows.append(row)
            if n < n_all:
                rest = np.setdiff1d(np.arange(n_all), sub)
                pred, _ = rf_fit_predict(Xs, Ys[:, keep], X[rest], seed=SEED)
                # Pooled-variance R2 (denominator = variance over all 486 runs):
                # the complement can be small and near-constant for some
                # outputs, which makes the classic R2 explode.
                r2e = np.full(Y.shape[1], np.nan)
                r2e[keep] = 1.0 - ((pred - Y[rest][:, keep]) ** 2).mean(axis=0) / Y[:, keep].var(axis=0)
                se = r2_summary(r2e[keep])
                row = dict(n=n, rep=rep, eval="external", n_outputs=int(keep.sum()), r2_mean=se["mean"],
                           r2_median=se["median"], n_ge_0_9=se["n_ge_0_9"], n_ge_0_95=se["n_ge_0_95"])
                row.update({f"r2_{y_cols[j]}": r2e[j] for j in hidx})
                rows.append(row)
            print(f"  n={n:3d} rep={rep} OOF mean R2 {s['mean']:.3f} median {s['median']:.3f} "
                  f">=0.9: {s['n_ge_0_9']}", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(DATA / "02_learning_curve.csv", index=False)

    agg = (df.groupby(["eval", "n"])
             .agg(r2_mean=("r2_mean", "mean"), r2_mean_sd=("r2_mean", "std"),
                  r2_mean_min=("r2_mean", "min"), r2_mean_max=("r2_mean", "max"),
                  r2_median=("r2_median", "mean"), r2_median_sd=("r2_median", "std"),
                  r2_median_min=("r2_median", "min"), r2_median_max=("r2_median", "max"),
                  n_ge_0_9=("n_ge_0_9", "mean"), n_ge_0_9_min=("n_ge_0_9", "min"),
                  n_ge_0_9_max=("n_ge_0_9", "max"))
             .reset_index())
    agg.to_csv(DATA / "02_learning_curve_summary.csv", index=False)

    # ------------------------------------------------------------------ figure
    oof = agg[agg["eval"] == "oof"].set_index("n")
    ext = agg[agg["eval"] == "external"].set_index("n")
    fig, (ax, ax2) = new_fig(height=2.3, ncols=2, gridspec_kw=dict(width_ratios=[1.15, 1]))
    ax.fill_between(oof.index, oof.r2_mean_min, oof.r2_mean_max, color=PALETTE[0], alpha=0.18, lw=0)
    ax.plot(oof.index, oof.r2_mean, color=PALETTE[0], marker="o", label="mean (OOF)")
    ax.fill_between(oof.index, oof.r2_median_min, oof.r2_median_max, color=PALETTE[1], alpha=0.18, lw=0)
    ax.plot(oof.index, oof.r2_median, color=PALETTE[1], marker="s", label="median (OOF)")
    ax.plot(ext.index, ext.r2_mean, color=PALETTE[0], ls=":", marker="o", mfc="white", ms=3,
            label="mean (external, pooled var.)")
    ax2.fill_between(oof.index, oof.n_ge_0_9_min, oof.n_ge_0_9_max, color=PALETTE[2], alpha=0.18, lw=0)
    ax2.plot(oof.index, oof.n_ge_0_9, color=PALETTE[2], marker="^")
    for a in (ax, ax2):
        a.set_xlabel("Training runs n")
        a.set_xticks([50, 150, 300, 486])
        a.set_xlim(30, 500)
    ax.set_ylabel("Out-of-fold R² (66 outputs)")
    ax2.set_ylabel("Outputs with R² ≥ 0.9 (of 66)")
    ax.set_ylim(0, 1)
    ax2.set_ylim(0, 40)
    ax.legend(loc="lower right", fontsize=6)
    save_fig(fig, "fig02_learning_curve")

    # ------------------------------------------------------------------ text
    def o(n, col):
        return float(oof.loc[n, col])

    L = ["## 2. Learning curve (RF, system layer, 10-fold OOF, 5 repeats)\n"]
    L.append(f"At the full n = 486 the mean / median OOF R-squared is {o(486, 'r2_mean'):.3f} / {o(486, 'r2_median'):.3f} "
             f"(repeat 0 is the draft seed; the five fold-assignment seeds span {o(486, 'r2_mean_min'):.3f}-"
             f"{o(486, 'r2_mean_max'):.3f} mean and {o(486, 'r2_median_min'):.3f}-{o(486, 'r2_median_max'):.3f} median), "
             f"with {o(486, 'n_ge_0_9'):.1f} outputs at R-squared >= 0.9 on average "
             f"(range {int(o(486, 'n_ge_0_9_min'))}-{int(o(486, 'n_ge_0_9_max'))}).")
    for n in (50, 100, 150, 200, 300, 400):
        L.append(f"With n = {n} runs the OOF mean / median R-squared is {o(n, 'r2_mean'):.3f} / {o(n, 'r2_median'):.3f} "
                 f"(repeat spread {o(n, 'r2_mean_min'):.3f}-{o(n, 'r2_mean_max'):.3f} on the mean) and "
                 f"{o(n, 'n_ge_0_9'):.1f} outputs reach R-squared >= 0.9 (range {int(o(n, 'n_ge_0_9_min'))}-"
                 f"{int(o(n, 'n_ge_0_9_max'))}); scored on the {486 - n} undrawn runs the mean R-squared is "
                 f"{float(ext.loc[n, 'r2_mean']):.3f} (pooled-variance R-squared).")
    half = o(486, "r2_mean") - 0.5 * (o(486, "r2_mean") - o(50, "r2_mean"))
    n_half = int(min(n for n in SIZES if o(n, "r2_mean") >= half))
    n90 = [n for n in SIZES if o(n, "r2_mean") >= 0.95 * o(486, "r2_mean")]
    L.append(f"Half of the R-squared gain between n = 50 and n = 486 is reached by n = {n_half}, and "
             f"{'n = ' + str(min(n90)) if n90 else 'no size below 486'} is the first size within 5 % of the full-table mean R-squared; "
             f"the curve has not flattened at 486, so a national design with more dials should expect to need "
             f"more than 486 runs for the same per-output accuracy.")
    L.append("\nPer-size summary (mean over 5 repeats; min-max in the CSV):\n")
    L.append(md_table(agg[["eval", "n", "r2_mean", "r2_mean_sd", "r2_median", "r2_median_sd", "n_ge_0_9"]]))
    L.append("\nFigure: figs/fig02_learning_curve (shaded = min-max over 5 repeats).")
    (HERE / "results_02.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote results_02.md")


if __name__ == "__main__":
    main()
