"""Item 3 - leave-one-level-out (LOLO) validation = extrapolation test.

For each continuous dial (Dem, Fuel, REcost, Siting, Batt) train the RF on
the two other levels (324 runs) and predict every run at the held-out level
(162 runs); done for the Lo level and the Hi level (Open / Lim for Siting),
i.e. extrapolation, and for the Md level (interpolation). For Pol (binary)
hold out IRA, then OBBBA (243 runs each; an unseen category).

Two R-squared definitions are reported on the held-out runs:
* r2_pooled = 1 - MSE(held-out) / Var(y over all 486 runs). Same denominator
  for every hold-out and for the random-fold comparison, so it never blows up
  when the held-out level happens to have little variance of its own. This is
  the number used for the figure and the summary sentences.
* r2 (classic) = 1 - MSE / Var(y over the held-out runs). Kept in the CSV;
  it is undefined/huge-negative for outputs that are nearly constant inside
  one level, so means over outputs are clipped at -1.
Both are compared with the random-fold 10-fold OOF prediction restricted to
the same runs.

System layer, 66 outputs. Writes data/03_lolo_per_output.csv,
data/03_lolo_summary.csv, figs/fig03_lolo_headline.*, results_03.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pesgm_common import (
    DATA, HERE, HEADLINE8, HEADLINE, LEVEL_NAMES, PALETTE, GRAY, PRETTY, X_COLS,
    load_layer, md_table, new_fig, per_output_r2, rf_fit_predict, save_fig, stored_oof,
)

CONT = ["x_Dem", "x_Fuel", "x_REcost", "x_Siting", "x_Batt"]


def safe_r2(Y, P):
    """Classic R2 per output; NaN where the held-out truth is constant."""
    out = np.full(Y.shape[1], np.nan)
    sd = Y.std(axis=0)
    ok = sd > 1e-9
    out[ok] = per_output_r2(Y[:, ok], P[:, ok])
    return out


def pooled_r2(Y_te, P_te, var_all):
    """1 - MSE on held-out runs / variance over all 486 runs."""
    return 1.0 - ((P_te - Y_te) ** 2).mean(axis=0) / var_all


def main():
    X, Y, x_cols, y_cols, _, _ = load_layer("system")
    oof = stored_oof("system", "rf", Y)
    r2_full = per_output_r2(Y, oof)
    rows, summ = [], []
    var_all = Y.var(axis=0)
    cases = [(d, lvl) for d in CONT for lvl in (0, 2, 1)] + [("x_Pol", 0), ("x_Pol", 1)]
    for dial, lvl in cases:
        j = x_cols.index(dial)
        te = X[:, j] == lvl
        tr = ~te
        pred, _ = rf_fit_predict(X[tr], Y[tr], X[te])
        r2_lolo = safe_r2(Y[te], pred)
        r2_rand = safe_r2(Y[te], oof[te])
        rp_lolo = pooled_r2(Y[te], pred, var_all)
        rp_rand = pooled_r2(Y[te], oof[te], var_all)
        # Bias of the extrapolated prediction, as % of held-out mean |y|
        with np.errstate(divide="ignore", invalid="ignore"):
            bias_pct = 100 * (pred - Y[te]).mean(axis=0) / np.abs(Y[te]).mean(axis=0)
            mae_pct = 100 * np.abs(pred - Y[te]).mean(axis=0) / np.abs(Y[te]).mean(axis=0)
            mae_pct_rand = 100 * np.abs(oof[te] - Y[te]).mean(axis=0) / np.abs(Y[te]).mean(axis=0)
        name = LEVEL_NAMES[dial][lvl]
        for k, c in enumerate(y_cols):
            rows.append(dict(dial=dial[2:], held_out=name, output=c,
                             r2_pooled_lolo=rp_lolo[k], r2_pooled_random=rp_rand[k],
                             r2_lolo=r2_lolo[k], r2_random_same_runs=r2_rand[k], r2_random_full=r2_full[k],
                             bias_pct=bias_pct[k], mae_pct_lolo=mae_pct[k], mae_pct_random=mae_pct_rand[k]))
        hk = [y_cols.index(c) for c in HEADLINE8]
        kind = "interpolation" if name == "Md" else ("unseen category" if dial == "x_Pol" else "extrapolation")
        summ.append(dict(dial=dial[2:], held_out=name, kind=kind, n_test=int(te.sum()),
                         r2_pooled_lolo_mean=np.mean(rp_lolo), r2_pooled_lolo_median=np.median(rp_lolo),
                         r2_pooled_random_mean=np.mean(rp_rand), r2_pooled_random_median=np.median(rp_rand),
                         r2_pooled_headline_lolo=np.mean(rp_lolo[hk]), r2_pooled_headline_random=np.mean(rp_rand[hk]),
                         r2_classic_lolo_median=np.nanmedian(r2_lolo),
                         r2_classic_lolo_mean_clipped=np.nanmean(np.clip(r2_lolo, -1, 1)),
                         r2_classic_random_median=np.nanmedian(r2_rand),
                         n_lolo_ge_0_9=int(np.sum(rp_lolo >= 0.9)), n_random_ge_0_9=int(np.sum(rp_rand >= 0.9)),
                         n_lolo_negative=int(np.sum(rp_lolo < 0)),
                         mae_pct_lolo_median=np.nanmedian(mae_pct), mae_pct_random_median=np.nanmedian(mae_pct_rand)))
        print(f"  {dial[2:]:7s} hold out {name:6s}: pooled R2 mean {np.mean(rp_lolo):.3f} "
              f"(random-fold same runs {np.mean(rp_rand):.3f})", flush=True)
    per = pd.DataFrame(rows)
    sm = pd.DataFrame(summ)
    per.to_csv(DATA / "03_lolo_per_output.csv", index=False)
    sm.to_csv(DATA / "03_lolo_summary.csv", index=False)

    # ------------------------------------------------------------------ figure
    hp = per[per.output.isin(HEADLINE8) & (per.dial != "Pol")].copy()
    hp["side"] = np.select([hp.held_out.isin(["Lo", "Open"]), hp.held_out == "Md"], ["Lo", "Md"], "Hi")
    g = hp.groupby(["output", "side"]).agg(lolo=("r2_pooled_lolo", "mean"), lolo_min=("r2_pooled_lolo", "min"),
                                           lolo_max=("r2_pooled_lolo", "max"),
                                           rand=("r2_pooled_random", "mean")).reset_index()
    g.to_csv(DATA / "03_lolo_headline_fig.csv", index=False)
    fig, ax = new_fig(height=2.6)
    xs = np.arange(len(HEADLINE8))
    w = 0.2
    rand_full = [r2_full[y_cols.index(c)] for c in HEADLINE8]
    sides = {k: g[g.side == k].set_index("output").loc[HEADLINE8] for k in ("Lo", "Md", "Hi")}
    ax.bar(xs - 1.5 * w, rand_full, w, color=PALETTE[0], label="random 10-fold", lw=0)
    for off, key, lab, col in ((-0.5 * w, "Lo", "leave-Lo-out", PALETTE[1]), (0.5 * w, "Md", "leave-Md-out", PALETTE[2]),
                               (1.5 * w, "Hi", "leave-Hi-out", PALETTE[3])):
        d_ = sides[key]
        ax.bar(xs + off, d_.lolo.clip(lower=-0.5), w, color=col, label=lab, lw=0)
        lo_c = d_.lolo.clip(lower=-0.5)
        ax.errorbar(xs + off, lo_c,
                    yerr=[(lo_c - d_.lolo_min.clip(lower=-0.5)).clip(lower=0), (d_.lolo_max - lo_c).clip(lower=0)],
                    fmt="none", ecolor="#52514e", elinewidth=0.5, capsize=1.2)
    ax.axhline(0, color=GRAY, lw=0.6)
    ax.set_xticks(xs)
    ax.set_xticklabels([PRETTY[c] for c in HEADLINE8], rotation=35, ha="right", fontsize=6.5)
    ax.set_ylabel("R\u00b2 on held-out runs (pooled variance)")
    ax.set_ylim(-0.5, 1.0)
    ax.legend(loc="lower left", fontsize=5.8, ncol=2, columnspacing=0.8)
    save_fig(fig, "fig03_lolo_headline")

    # ------------------------------------------------------------------ text
    L = ["## 3. Leave-one-level-out validation (RF, system layer)\n"]
    L.append("Each row trains on the runs at the other level(s) of one dial and predicts all runs at the held-out "
             "level; 'random' is the 10-fold OOF prediction on the same held-out runs. R-squared uses the pooled "
             "variance over all 486 runs as denominator (1 - MSE / Var_all) so that hold-outs are comparable; "
             "classic per-level R-squared is in data/03_lolo_per_output.csv.")
    for r in sm.itertuples():
        L.append(f"Holding out {r.dial} = {r.held_out} ({r.kind}, {r.n_test} runs) gives mean / median pooled R-squared "
                 f"{r.r2_pooled_lolo_mean:.3f} / {r.r2_pooled_lolo_median:.3f} versus {r.r2_pooled_random_mean:.3f} / "
                 f"{r.r2_pooled_random_median:.3f} for random folds on the same runs; {r.n_lolo_ge_0_9} outputs stay "
                 f"above 0.9 (random: {r.n_random_ge_0_9}) and {r.n_lolo_negative} go negative; on the eight headline "
                 f"outputs the mean is {r.r2_pooled_headline_lolo:.3f} versus {r.r2_pooled_headline_random:.3f}; the "
                 f"median MAE is {r.mae_pct_lolo_median:.1f} % of the held-out mean versus {r.mae_pct_random_median:.1f} %.")
    cont = sm[sm.dial != "Pol"]
    lo = cont[cont.held_out.isin(["Lo", "Open"])]
    hi = cont[cont.held_out.isin(["Hi", "Lim"])]
    md = cont[cont.held_out == "Md"]
    L.append(f"Averaged over the five continuous dials, leaving out the Lo/Open level gives mean pooled R-squared "
             f"{lo.r2_pooled_lolo_mean.mean():.3f} (random folds on the same runs: {lo.r2_pooled_random_mean.mean():.3f}), "
             f"leaving out Hi/Lim gives {hi.r2_pooled_lolo_mean.mean():.3f} (random {hi.r2_pooled_random_mean.mean():.3f}), "
             f"and leaving out the middle level gives {md.r2_pooled_lolo_mean.mean():.3f} (random "
             f"{md.r2_pooled_random_mean.mean():.3f}); on the eight headline outputs the three numbers are "
             f"{lo.r2_pooled_headline_lolo.mean():.3f}, {hi.r2_pooled_headline_lolo.mean():.3f} and "
             f"{md.r2_pooled_headline_lolo.mean():.3f} against {lo.r2_pooled_headline_random.mean():.3f}, "
             f"{hi.r2_pooled_headline_random.mean():.3f} and {md.r2_pooled_headline_random.mean():.3f}.")
    L.append("A tree ensemble predicts a constant outside its training range, and with only the two outer levels "
             "left every split threshold sits exactly at the middle value, which sklearn resolves to the lower "
             "branch, so the middle level is predicted as if it were the low level; these numbers therefore bound "
             "what the surrogate can say beyond the sampled grid. It should be used inside the sampled levels only, "
             "and the continuous dial sliders in the dashboard interpolate tree plateaus rather than physics.")
    pol = sm[sm.dial == "Pol"]
    L.append(f"Holding out a policy level: mean pooled R-squared "
             f"{pol[pol.held_out == 'IRA'].r2_pooled_lolo_mean.iloc[0]:.3f} when IRA runs are unseen and "
             f"{pol[pol.held_out == 'OBBBA'].r2_pooled_lolo_mean.iloc[0]:.3f} when OBBBA runs are unseen "
             f"(random folds: {pol[pol.held_out == 'IRA'].r2_pooled_random_mean.iloc[0]:.3f} and "
             f"{pol[pol.held_out == 'OBBBA'].r2_pooled_random_mean.iloc[0]:.3f}), so the surrogate cannot be "
             f"transferred to an unseen policy case.")
    hb = per[per.output.isin(HEADLINE) & (per.dial != "Pol") & (per.held_out != "Md")]
    worst = hb.sort_values("r2_pooled_lolo").head(5)
    L.append("Worst headline-output extrapolations: " + "; ".join(
        f"{r.output} with {r.dial}={r.held_out} held out (pooled R-squared {r.r2_pooled_lolo:.2f}, bias "
        f"{r.bias_pct:+.0f} % of mean)" for r in worst.itertuples()) + ".")
    best = hb.sort_values("r2_pooled_lolo", ascending=False).head(3)
    L.append("Most robust: " + "; ".join(
        f"{r.output} with {r.dial}={r.held_out} held out (pooled R-squared {r.r2_pooled_lolo:.2f})"
        for r in best.itertuples()) + ".")
    L.append("\nSummary table (pooled R-squared unless marked classic):\n")
    L.append(md_table(sm[["dial", "held_out", "kind", "n_test", "r2_pooled_lolo_mean", "r2_pooled_lolo_median",
                          "r2_pooled_random_mean", "r2_pooled_random_median", "r2_pooled_headline_lolo",
                          "r2_pooled_headline_random", "r2_classic_lolo_median", "r2_classic_random_median",
                          "n_lolo_ge_0_9", "n_random_ge_0_9", "n_lolo_negative"]]))
    L.append("\nFigure: figs/fig03_lolo_headline (bars = mean over the five continuous dials, whiskers = min-max "
             "across dials, clipped at -0.5; 'random 10-fold' is the full 486-run OOF R-squared).")
    (HERE / "results_03.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote results_03.md")


if __name__ == "__main__":
    main()
