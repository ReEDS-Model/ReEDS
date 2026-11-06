"""Item 1 - empirical coverage of the 90 % (and 50/80/95 %) intervals.

Re-runs the pipeline's 10-fold CV (seed 42, same folds) for RF and NGBoost on
both layers, keeping for every held-out run (a) the 200 per-tree RF
predictions and (b) the NGBoost predicted Normal (loc, scale). The point
predictions are checked against the stored OOF residuals so the numbers tie
back to the draft.

Interval methods evaluated (per output, over the 486 held-out predictions):

* rf_conformal      the deployed method (surrogate_uq.conformal_widths):
                    +/- quantile_{1-a}(|OOF residual|). Evaluated honestly by
                    cross-fold calibration: the width used for fold k is taken
                    from the residuals of the other nine folds.
* rf_conformal_insample  the circular number produced by the existing
                    surrogate_eval calibration sweep (width and coverage from
                    the same residuals) - reported only to show it is trivial.
* rf_tree_quantile  RF-native: empirical [a/2, 1-a/2] quantiles of the 200
                    per-tree predictions.
* ngb_native        the deployed NGBoost method: loc +/- z_{1-a/2} * scale.
* ngb_conformal     split-conformal correction of the NGBoost Normal: the
                    cross-fold quantile of |residual|/scale replaces z.

Writes data/01_coverage_per_output.csv, data/01_coverage_summary.csv,
data/01_extremes.csv, figs/fig01a_reliability.*, figs/fig01b_coverage_hist.*,
results_01.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy.stats import norm
from sklearn.preprocessing import StandardScaler

from pesgm_common import (
    DATA, HERE, PALETTE, GRAY, SEED, kfold, load_layer, md_table, new_fig,
    per_output_r2, rf_oof, save_fig, stored_oof, write_json,
)

LEVELS = [0.5, 0.8, 0.9, 0.95]


# ---------------------------------------------------------------------------
# NGBoost OOF with predicted sigma (replicates compute_oof_predictions)
# ---------------------------------------------------------------------------
def _ngb_fit_one(X_tr_s, y_tr_s, X_te_s, seed):
    from ngboost import NGBRegressor
    m = NGBRegressor(n_estimators=200, learning_rate=0.05, random_state=seed, verbose=False)
    m.fit(X_tr_s, y_tr_s)
    d = m.pred_dist(X_te_s)
    return np.asarray(d.loc).ravel(), np.asarray(d.scale).ravel()


def ngb_oof(X, Y, seed=SEED):
    n, p = Y.shape
    mu = np.zeros_like(Y)
    sig = np.zeros_like(Y)
    for k, (tr, te) in enumerate(kfold(n, seed)):
        sx = StandardScaler().fit(X[tr])
        X_tr_s, X_te_s = sx.transform(X[tr]), sx.transform(X[te])
        var_mask = Y[tr].std(axis=0) > 1e-9
        train_means = Y[tr].mean(axis=0)
        sy = StandardScaler().fit(Y[tr][:, var_mask])
        Y_tr_s = sy.transform(Y[tr][:, var_mask])
        res = Parallel(n_jobs=-1)(
            delayed(_ngb_fit_one)(X_tr_s, Y_tr_s[:, j], X_te_s, seed)
            for j in range(Y_tr_s.shape[1])
        )
        loc_s = np.column_stack([r[0] for r in res])
        scl_s = np.column_stack([r[1] for r in res])
        loc = loc_s * sy.scale_ + sy.mean_
        scl = scl_s * sy.scale_
        full_mu = np.tile(train_means, (len(te), 1))
        full_sig = np.zeros((len(te), p))
        full_mu[:, var_mask] = loc
        full_sig[:, var_mask] = scl
        mu[te], sig[te] = full_mu, full_sig
        print(f"    ngboost fold {k + 1}/10 done", flush=True)
    return mu, sig


# ---------------------------------------------------------------------------
# Coverage computations (all return (n_outputs,) coverage per level)
# ---------------------------------------------------------------------------
def cov_conformal_crossfold(Y, P, fold_id, levels):
    R = np.abs(Y - P)
    out = {}
    for a in levels:
        inside = np.zeros_like(Y, dtype=bool)
        for k in np.unique(fold_id):
            cal = R[fold_id != k]
            half = np.quantile(cal, a, axis=0)
            inside[fold_id == k] = R[fold_id == k] <= half[None, :]
        out[a] = inside.mean(axis=0)
    return out


def cov_conformal_insample(Y, P, levels):
    R = np.abs(Y - P)
    return {a: (R <= np.quantile(R, a, axis=0)[None, :]).mean(axis=0) for a in levels}


def cov_tree_quantile(Y, trees, levels):
    out = {}
    for a in levels:
        lo = np.quantile(trees, (1 - a) / 2, axis=0)
        hi = np.quantile(trees, 1 - (1 - a) / 2, axis=0)
        out[a] = ((Y >= lo) & (Y <= hi)).mean(axis=0)
    return out


def cov_normal(Y, mu, sig, levels):
    out = {}
    for a in levels:
        z = norm.ppf(1 - (1 - a) / 2)
        out[a] = ((Y >= mu - z * sig) & (Y <= mu + z * sig)).mean(axis=0)
    return out


def cov_normal_conformal(Y, mu, sig, fold_id, levels):
    with np.errstate(divide="ignore", invalid="ignore"):
        S = np.abs(Y - mu) / np.where(sig > 0, sig, np.nan)   # standardised |resid|
    out = {}
    for a in levels:
        inside = np.zeros_like(Y, dtype=bool)
        for k in np.unique(fold_id):
            cal = S[fold_id != k]
            q = np.nanquantile(cal, a, axis=0)
            q = np.where(np.isnan(q), 0.0, q)
            te = fold_id == k
            inside[te] = np.abs(Y[te] - mu[te]) <= q[None, :] * sig[te]
        out[a] = inside.mean(axis=0)
    return out


def main():
    rows, summary, extremes, widths, repro = [], [], [], [], []
    for layer in ("system", "regional"):
        print(f"[{layer}] loading", flush=True)
        X, Y, _, y_cols, _, _ = load_layer(layer)
        print(f"[{layer}] RF 10-fold CV with per-tree predictions", flush=True)
        P_rf, fold_id, trees = rf_oof(X, Y, return_trees=True)
        chk = np.max(np.abs(P_rf - stored_oof(layer, "rf", Y)) / Y.std(0))
        print(f"    RF OOF reproduces stored residuals: max rel diff {chk:.1e}", flush=True)
        print(f"[{layer}] NGBoost 10-fold CV with predicted sigma", flush=True)
        mu, sig = ngb_oof(X, Y)
        chk2 = np.max(np.abs(mu - stored_oof(layer, "ngboost", Y)) / Y.std(0))
        print(f"    NGBoost OOF vs stored residuals: max rel diff {chk2:.1e} (NGBoost's default tree learner "
              f"has random_state=None, so tie-breaks differ run to run)", flush=True)
        r2_ngb_new = per_output_r2(Y, mu)
        r2_ngb_old = per_output_r2(Y, stored_oof(layer, "ngboost", Y))
        repro.append(dict(layer=layer, rf_max_rel_diff=chk, ngb_max_rel_diff=chk2,
                          ngb_r2_mean_rerun=r2_ngb_new.mean(), ngb_r2_median_rerun=np.median(r2_ngb_new),
                          ngb_r2_mean_stored=r2_ngb_old.mean(), ngb_r2_median_stored=np.median(r2_ngb_old)))
        np.savez_compressed(DATA / f"01_oof_{layer}.npz", P_rf=P_rf, fold_id=fold_id,
                            tree_q05=np.quantile(trees, 0.05, axis=0),
                            tree_q95=np.quantile(trees, 0.95, axis=0),
                            ngb_mu=mu, ngb_sig=sig, y_cols=np.array(y_cols))

        methods = {
            "rf_conformal": cov_conformal_crossfold(Y, P_rf, fold_id, LEVELS),
            "rf_conformal_insample": cov_conformal_insample(Y, P_rf, LEVELS),
            "rf_tree_quantile": cov_tree_quantile(Y, trees, LEVELS),
            "ngb_native": cov_normal(Y, mu, sig, LEVELS),
            "ngb_conformal": cov_normal_conformal(Y, mu, sig, fold_id, LEVELS),
        }
        # Interval sharpness at 90 %: mean half-width / std(y), per output
        R = np.abs(Y - P_rf)
        half_rf = np.quantile(R, 0.9, axis=0)
        half_tree = 0.5 * (np.quantile(trees, 0.95, axis=0) - np.quantile(trees, 0.05, axis=0)).mean(axis=0)
        half_ngb = (norm.ppf(0.95) * sig).mean(axis=0)
        sd = Y.std(axis=0)
        for j, c in enumerate(y_cols):
            widths.append(dict(layer=layer, output=c, rf_conformal=half_rf[j] / sd[j],
                               rf_tree_quantile=half_tree[j] / sd[j], ngb_native=half_ngb[j] / sd[j]))
        r2_rf = per_output_r2(Y, P_rf)
        for m, d in methods.items():
            for a in LEVELS:
                c = d[a]
                for j, col in enumerate(y_cols):
                    rows.append(dict(layer=layer, method=m, nominal=a, output=col, coverage=c[j],
                                     r2_rf=r2_rf[j]))
                summary.append(dict(layer=layer, method=m, nominal=a, n_outputs=len(c),
                                    mean=c.mean(), median=np.median(c), min=c.min(), max=c.max(),
                                    p10=np.quantile(c, 0.1), p90=np.quantile(c, 0.9),
                                    frac_outputs_within_5pt=np.mean(np.abs(c - a) <= 0.05),
                                    frac_under_by_10pt=np.mean(c < a - 0.10)))
            c90 = d[0.9]
            order = np.argsort(c90)
            for j in order[:5]:
                extremes.append(dict(layer=layer, method=m, side="under", output=y_cols[j],
                                     coverage90=c90[j], r2_rf=r2_rf[j]))
            for j in order[::-1][:5]:
                extremes.append(dict(layer=layer, method=m, side="over", output=y_cols[j],
                                     coverage90=c90[j], r2_rf=r2_rf[j]))

    per_out = pd.DataFrame(rows)
    summ = pd.DataFrame(summary)
    ext = pd.DataFrame(extremes)
    wid = pd.DataFrame(widths)
    per_out.to_csv(DATA / "01_coverage_per_output.csv", index=False)
    summ.to_csv(DATA / "01_coverage_summary.csv", index=False)
    ext.to_csv(DATA / "01_extremes.csv", index=False)
    wid.to_csv(DATA / "01_interval_halfwidth_over_sd.csv", index=False)
    rep = pd.DataFrame(repro)
    rep.to_csv(DATA / "01_reproduction_check.csv", index=False)

    # ------------------------------------------------------------------ figures
    plot_methods = [("rf_conformal", "RF conformal (deployed)", PALETTE[0], "o"),
                    ("rf_tree_quantile", "RF per-tree quantile", PALETTE[1], "s"),
                    ("ngb_native", "NGBoost native", PALETTE[2], "^"),
                    ("ngb_conformal", "NGBoost + conformal", PALETTE[3], "D")]
    fig, ax = new_fig(height=2.6)
    ax.plot([0.45, 1.0], [0.45, 1.0], color=GRAY, lw=0.8, ls="--", zorder=1)
    for m, lab, col, mk in plot_methods:
        for layer, ls in (("system", "-"), ("regional", ":")):
            s = summ[(summ.method == m) & (summ.layer == layer)].sort_values("nominal")
            ax.plot(s.nominal, s["mean"], ls=ls, marker=mk, color=col, ms=3.5,
                    label=lab if layer == "system" else None)
    ink = "#52514e"
    ax.plot([], [], color=ink, ls="-", label="system")
    ax.plot([], [], color=ink, ls=":", label="regional")
    ax.set_xlabel("Nominal coverage (1 − α)")
    ax.set_ylabel("Empirical coverage (mean over outputs)")
    ax.set_xticks(LEVELS)
    ax.set_xlim(0.45, 1.0)
    ax.set_ylim(0.2, 1.0)
    ax.legend(loc="lower right", ncol=1, fontsize=6)
    save_fig(fig, "fig01a_reliability")

    fig, axes = new_fig(height=2.4, ncols=2, sharey=True)
    bins = np.linspace(0, 1, 21)
    for ax, layer in zip(axes, ("system", "regional")):
        for m, lab, col, _ in plot_methods[:3]:
            c = per_out[(per_out.method == m) & (per_out.nominal == 0.9) & (per_out.layer == layer)].coverage
            ax.hist(c, bins=bins, histtype="step", lw=1.1, color=col, label=lab)
        ax.axvline(0.9, color=GRAY, ls="--", lw=0.8)
        ax.set_xlabel("Per-output 90 % coverage")
        ax.set_xlim(0, 1)
        ax.text(0.03, 0.95, layer, transform=ax.transAxes, va="top", fontsize=7)
    axes[0].set_ylabel("Number of outputs")
    axes[0].legend(loc="upper left", fontsize=5.5, bbox_to_anchor=(0.0, 0.9))
    save_fig(fig, "fig01b_coverage_hist")

    # ------------------------------------------------------------------ text
    def g(layer, m, a, col="mean"):
        return float(summ[(summ.layer == layer) & (summ.method == m) & (summ.nominal == a)][col].iloc[0])

    L = ["## 1. Interval calibration (10-fold OOF, seed 42)\n"]
    L.append("The RF out-of-fold predictions used here reproduce the stored residuals exactly (max relative "
             f"difference {rep.rf_max_rel_diff.max():.1e} of the output std). NGBoost had to be re-run to obtain "
             "the predicted sigma; its default tree learner is unseeded (random_state=None), so individual "
             "predictions differ from the stored run (max relative difference "
             f"{rep.ngb_max_rel_diff.max():.2f} std) while the aggregate accuracy is unchanged: re-run mean / median "
             f"R-squared {rep.ngb_r2_mean_rerun.iloc[0]:.4f} / {rep.ngb_r2_median_rerun.iloc[0]:.4f} (system) and "
             f"{rep.ngb_r2_mean_rerun.iloc[1]:.4f} / {rep.ngb_r2_median_rerun.iloc[1]:.4f} (regional) versus stored "
             f"{rep.ngb_r2_mean_stored.iloc[0]:.4f} / {rep.ngb_r2_median_stored.iloc[0]:.4f} and "
             f"{rep.ngb_r2_mean_stored.iloc[1]:.4f} / {rep.ngb_r2_median_stored.iloc[1]:.4f}.")
    for layer in ("system", "regional"):
        n = int(summ[(summ.layer == layer)].n_outputs.iloc[0])
        L.append(f"**{layer} layer ({n} outputs)**\n")
        L.append(f"The deployed RF split-conformal 90 % band, calibrated on the other nine folds and evaluated on the "
                 f"held-out fold, covers the true value in {100 * g(layer, 'rf_conformal', 0.9):.1f} % of held-out runs on "
                 f"average across outputs (median {100 * g(layer, 'rf_conformal', 0.9, 'median'):.1f} %, range "
                 f"{100 * g(layer, 'rf_conformal', 0.9, 'min'):.1f}-{100 * g(layer, 'rf_conformal', 0.9, 'max'):.1f} %); "
                 f"{100 * g(layer, 'rf_conformal', 0.9, 'frac_outputs_within_5pt'):.0f} % of outputs are within 5 points of nominal.")
        L.append(f"At 50/80/95 % nominal the RF conformal band covers "
                 f"{100 * g(layer, 'rf_conformal', 0.5):.1f}/{100 * g(layer, 'rf_conformal', 0.8):.1f}/"
                 f"{100 * g(layer, 'rf_conformal', 0.95):.1f} %.")
        L.append(f"The in-sample number the existing eval code reports for the same band is "
                 f"{100 * g(layer, 'rf_conformal_insample', 0.9):.1f} % at 90 % nominal; it is circular (width and "
                 f"coverage from the same residuals) and should not be cited.")
        L.append(f"The RF-native per-tree 5-95 % quantile band is badly under-covered: "
                 f"{100 * g(layer, 'rf_tree_quantile', 0.9):.1f} % mean coverage at 90 % nominal "
                 f"({100 * g(layer, 'rf_tree_quantile', 0.5):.1f}/{100 * g(layer, 'rf_tree_quantile', 0.8):.1f}/"
                 f"{100 * g(layer, 'rf_tree_quantile', 0.95):.1f} % at 50/80/95 %), which is why the conformal wrapper is needed.")
        L.append(f"The NGBoost native Normal 90 % interval covers {100 * g(layer, 'ngb_native', 0.9):.1f} % on average "
                 f"(median {100 * g(layer, 'ngb_native', 0.9, 'median'):.1f} %, "
                 f"{100 * g(layer, 'ngb_native', 0.9, 'frac_under_by_10pt'):.0f} % of outputs under-covered by more than 10 points); "
                 f"at 50/80/95 % it covers {100 * g(layer, 'ngb_native', 0.5):.1f}/{100 * g(layer, 'ngb_native', 0.8):.1f}/"
                 f"{100 * g(layer, 'ngb_native', 0.95):.1f} %.")
        L.append(f"A split-conformal correction of the NGBoost sigma (cross-fold quantile of |residual|/sigma replacing "
                 f"z) restores {100 * g(layer, 'ngb_conformal', 0.9):.1f} % coverage at 90 % nominal "
                 f"({100 * g(layer, 'ngb_conformal', 0.5):.1f}/{100 * g(layer, 'ngb_conformal', 0.8):.1f}/"
                 f"{100 * g(layer, 'ngb_conformal', 0.95):.1f} % at 50/80/95 %).")
        w = wid[wid.layer == layer]
        L.append(f"Sharpness at 90 %: median half-width / std(y) is {w.rf_conformal.median():.2f} for RF conformal, "
                 f"{w.rf_tree_quantile.median():.2f} for the RF per-tree band and {w.ngb_native.median():.2f} for NGBoost native.")
        e = ext[(ext.layer == layer) & (ext.method == "rf_conformal")]
        under = ", ".join(f"{r.output} ({100 * r.coverage90:.0f} %)" for r in e[e.side == "under"].itertuples())
        over = ", ".join(f"{r.output} ({100 * r.coverage90:.0f} %)" for r in e[e.side == "over"].itertuples())
        L.append(f"Most under-covered outputs for the RF conformal 90 % band: {under}. Most over-covered: {over}.")
        e = ext[(ext.layer == layer) & (ext.method == "ngb_native")]
        under = ", ".join(f"{r.output} ({100 * r.coverage90:.0f} %)" for r in e[e.side == "under"].itertuples())
        L.append(f"Most under-covered outputs for the NGBoost native 90 % band: {under}.\n")
    L.append("Summary table (mean coverage over outputs):\n")
    piv = summ.pivot_table(index=["layer", "method"], columns="nominal", values="mean").reset_index()
    piv.columns = [str(c) for c in piv.columns]
    L.append(md_table(piv))
    L.append("\nFigures: figs/fig01a_reliability (nominal vs empirical, solid = system, dotted = regional), "
             "figs/fig01b_coverage_hist (per-output 90 % coverage).")
    (HERE / "results_01.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote results_01.md")


if __name__ == "__main__":
    main()
