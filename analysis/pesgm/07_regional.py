"""Item 7 - regional layer detail (RF, stored 10-fold OOF).

(a) Per-region (ERCOT BA p60-p65, p67) number of modelled outputs and mean /
    median R-squared, plus the same by output category within region.
(b) Regional-additivity residual BEFORE rescaling: for every quantity present
    in both layers (cap_* and gen_* by tech, tran_total, cost components) and
    every run, (sum of regional OOF predictions - system OOF prediction) as a
    percentage of the system prediction, and the same against the ReEDS truth.

Writes data/07_region_summary.csv, data/07_region_category.csv,
data/07_additivity_residual.csv, figs/fig07_region_r2.*, results_07.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pesgm_common import (
    DATA, HERE, PALETTE, GRAY, category, load_layer, md_table, new_fig,
    parse_regional, per_output_r2, regional_groups, save_fig, stored_oof,
)

HEADLINE_Q = ["cap_wind-ons", "cap_upv", "cap_gas-cc", "cap_battery_li", "cap_gas-ct",
              "gen_wind-ons", "gen_upv", "gen_gas-cc", "tran_total"]


def main():
    Xr, Yr, _, reg_cols, _, reg_const = load_layer("regional")
    Pr = stored_oof("regional", "rf", Yr)
    Xs, Ys, _, sys_cols, _, _ = load_layer("system")
    Ps = stored_oof("system", "rf", Ys)
    r2 = per_output_r2(Yr, Pr)
    parsed = [parse_regional(c) for c in reg_cols]
    d = pd.DataFrame(dict(output=reg_cols, parent=[p[0] for p in parsed], region=[p[1] for p in parsed],
                          category=[category(c) for c in reg_cols], r2=r2,
                          activation=(np.abs(Yr) > 0).mean(axis=0)))
    d.to_csv(DATA / "07_regional_per_output.csv", index=False)
    reg = (d.groupby("region").agg(n_outputs=("r2", "size"), r2_mean=("r2", "mean"), r2_median=("r2", "median"),
                                   n_ge_0_9=("r2", lambda v: int((v >= 0.9).sum())),
                                   n_below_0_5=("r2", lambda v: int((v < 0.5).sum())),
                                   mean_activation=("activation", "mean")).reset_index())
    reg.to_csv(DATA / "07_region_summary.csv", index=False)
    rc = d.groupby(["region", "category"]).agg(n=("r2", "size"), r2_mean=("r2", "mean"),
                                               r2_median=("r2", "median")).reset_index()
    rc.to_csv(DATA / "07_region_category.csv", index=False)

    # ---------------- additivity residual before rescaling -------------------
    rows = []
    for sys_name, (gcols, const) in regional_groups(reg_cols, reg_const, sys_cols).items():
        idx = [reg_cols.index(c) for c in gcols]
        s_pred = Pr[:, idx].sum(axis=1) + const
        s_true = Yr[:, idx].sum(axis=1) + const
        t_pred = Ps[:, sys_cols.index(sys_name)]
        t_true = Ys[:, sys_cols.index(sys_name)]
        with np.errstate(divide="ignore", invalid="ignore"):
            rel_pred = 100 * (s_pred - t_pred) / np.abs(t_pred)
            rel_true = 100 * (s_pred - t_true) / np.abs(t_true)
        ok = np.isfinite(rel_pred) & (np.abs(t_true) > 0)
        rows.append(dict(quantity=sys_name, n_regions=len(idx), constant_part=const, n_runs=int(ok.sum()),
                         mean_true=float(np.abs(t_true).mean()),
                         median_abs_gap_vs_system_pred_pct=float(np.median(np.abs(rel_pred[ok]))),
                         p90_abs_gap_vs_system_pred_pct=float(np.quantile(np.abs(rel_pred[ok]), 0.9)),
                         max_abs_gap_vs_system_pred_pct=float(np.max(np.abs(rel_pred[ok]))),
                         frac_gap_gt_1pct=float((np.abs(rel_pred[ok]) > 1).mean()),
                         frac_gap_gt_5pct=float((np.abs(rel_pred[ok]) > 5).mean()),
                         mean_signed_gap_pct=float(rel_pred[ok].mean()),
                         median_abs_gap_vs_truth_pct=float(np.median(np.abs(rel_true[ok]))),
                         r2_sum_of_regional=per_output_r2(t_true[:, None], s_pred[:, None])[0],
                         r2_system_model=per_output_r2(t_true[:, None], t_pred[:, None])[0]))
    add = pd.DataFrame(rows).sort_values("mean_true", ascending=False)
    add.to_csv(DATA / "07_additivity_residual.csv", index=False)

    # total-capacity / total-generation / total-cost gaps (weighted view)
    def total_gap(prefix):
        q = add[add.quantity.str.startswith(prefix)]
        return q

    # ------------------------------------------------------------------ figure
    fig, ax = new_fig(height=2.3)
    regs = list(reg.region)
    xs = np.arange(len(regs))
    ax.bar(xs, reg.r2_mean, 0.6, color=PALETTE[0], lw=0, label="mean R²")
    ax.scatter(xs, reg.r2_median, s=14, color=PALETTE[1], marker="D", zorder=3, label="median R²")
    for x, n in zip(xs, reg.n_outputs):
        ax.text(x, 0.02, str(int(n)), ha="center", va="bottom", fontsize=6, color="white")
    ax.set_xticks(xs)
    ax.set_xticklabels([r if r != "corridor" else "lines" for r in regs])
    ax.set_xlabel("ERCOT balancing area (outputs per bar)")
    ax.set_ylabel("Out-of-fold R²")
    ax.set_ylim(0, 1)
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper right", fontsize=6)
    save_fig(fig, "fig07_region_r2")

    # ------------------------------------------------------------------ text
    L = ["## 7. Regional layer detail (RF, 10-fold OOF)\n"]
    L.append(f"The regional layer has {len(d)} modelled outputs across {int(d.region.notna().sum() - (d.region == 'corridor').sum())} "
             f"BA-resolved columns in 7 balancing areas plus {int((d.region == 'corridor').sum())} transmission corridors (an 11th corridor is constant and dropped); "
             f"per region: " + "; ".join(
                 f"{r.region} {int(r.n_outputs)} outputs, mean / median R-squared {r.r2_mean:.2f} / {r.r2_median:.2f}, "
                 f"{int(r.n_ge_0_9)} at >= 0.9" for r in reg.itertuples()) + ".")
    best, worst = reg.loc[reg.r2_mean.idxmax()], reg.loc[reg.r2_mean.idxmin()]
    L.append(f"The best-predicted region is {best.region} (mean R-squared {best.r2_mean:.2f}) and the worst is "
             f"{worst.region} ({worst.r2_mean:.2f}); mean activation frequency of the outputs is {best.mean_activation:.2f} "
             f"versus {worst.mean_activation:.2f}, so regional difficulty tracks how many sparse tech-region "
             f"combinations a BA has.")
    for cat in ("cap", "gen", "cost"):
        q = rc[rc.category == cat]
        L.append(f"By category within region, {cat} outputs have mean R-squared from {q.r2_mean.min():.2f} "
                 f"({q.loc[q.r2_mean.idxmin(), 'region']}) to {q.r2_mean.max():.2f} ({q.loc[q.r2_mean.idxmax(), 'region']}).")
    a = add.set_index("quantity")
    L.append(f"\nAdditivity before rescaling: across the {len(add)} quantities present in both layers, the sum of the raw "
             f"regional RF predictions differs from the system RF prediction by a median of "
             f"{add.median_abs_gap_vs_system_pred_pct.median():.2f} % of the system value (median over quantities of the "
             f"per-quantity median absolute gap), exceeds 1 % in {100 * add.frac_gap_gt_1pct.mean():.0f} % of (run, quantity) "
             f"pairs and 5 % in {100 * add.frac_gap_gt_5pct.mean():.0f} %.")
    L.append("For the headline quantities the median absolute gap is " + ", ".join(
        f"{q} {a.loc[q, 'median_abs_gap_vs_system_pred_pct']:.2f} % (p90 {a.loc[q, 'p90_abs_gap_vs_system_pred_pct']:.1f} %)"
        for q in HEADLINE_Q if q in a.index) + ".")
    L.append("The sum of regional predictions is itself a competitive estimate of the system total: R-squared against the "
             "ReEDS system value is " + ", ".join(
                 f"{q} {a.loc[q, 'r2_sum_of_regional']:.3f} (system model {a.loc[q, 'r2_system_model']:.3f})"
                 for q in HEADLINE_Q if q in a.index) + ".")
    big = add[add.frac_gap_gt_5pct > 0.25].quantity.tolist()
    L.append(f"Quantities whose regional sum misses the system prediction by more than 5 % in over a quarter of runs: "
             f"{', '.join(big) if big else 'none'}.")
    L.append("Because the dashboard does not call enforce_additivity, these pre-rescale gaps are what a user sees "
             "when comparing the regional and system views.")
    L.append("\nPer-region table:\n")
    L.append(md_table(reg.round(3)))
    L.append("\nAdditivity residual table (sorted by magnitude of the quantity):\n")
    L.append(md_table(add[["quantity", "n_regions", "median_abs_gap_vs_system_pred_pct", "p90_abs_gap_vs_system_pred_pct",
                           "frac_gap_gt_1pct", "frac_gap_gt_5pct", "mean_signed_gap_pct", "r2_sum_of_regional",
                           "r2_system_model"]].round(3)))
    L.append("\nFigure: figs/fig07_region_r2.")
    (HERE / "results_07.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote results_07.md")


if __name__ == "__main__":
    main()
