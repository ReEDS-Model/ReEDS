"""Item 10 - evaluation after the constraint-layer fix (no retraining).

Applies the fixed Stage 2 constraint layer (``surrogate_constraints.
apply_constraints``: constants held -> clip -> regional additivity -> cost
identity) to the STORED out-of-fold predictions of every model (OOF =
clipped training target - stored ``oof_residuals``; the artefacts are only
read) and recomputes:

  Part 2  Table III (all 7 models), RF figures (R2 buckets, system ranking,
          per-BA heatmap), the four ablation numbers, the cumulative per-rule
          ablation, and the old-vs-new list of regional numbers.
  Part 3  bounds audit: capacity-factor ceiling and transmission floor for
          RF, MLP and Ridge on both layers.

The "none" ablation row reuses the RF OOF fitted on raw targets that
09_constraints_check.py cached in data/09_oof_cache.npz (an analysis CV
refit made before this task; nothing is refitted here).

Writes data/10_*.csv / .json, data/after_fix/<layer>/ (summary.json,
per_output_metrics_<model>.csv, oof_rf.npz laid out like Stage2/outputs for
the OneDrive figure scripts), figs/buckets|r2_ranking_rf|ba_heatmap_rf
(.pdf + .png) and results_after_fix.md.  Run with the reeds2 env.
"""
from __future__ import annotations

import json
import pickle
import re
import sys

import numpy as np
import pandas as pd

from pesgm_common import (
    DATA, GRAY, HERE, INK, LAYERS, PALETTE, load_layer, md_table, new_fig,
    non_negative_mask, per_output_r2, r2_summary, regional_groups, resolve_models_dir,
    save_fig, set_style,
)
from surrogate_constraints import (  # noqa: E402
    Stage2InferenceConfig, _is_storage_gen, apply_constraints, cost_component_cols,
    system_transmission_floors, transmission_floors,
)
from surrogate_ml_models import MonotoneXGBMultiOutput  # noqa: E402

# xgb artefacts were pickled with this class under __main__.
setattr(sys.modules["__main__"], "MonotoneXGBMultiOutput", MonotoneXGBMultiOutput)

MODELS = ["ridge", "lasso", "knn", "rf", "xgb", "nn", "ngboost"]
NAME = {"ridge": "Ridge", "lasso": "Lasso", "knn": "k-NN", "rf": "Random Forest",
        "xgb": "XGBoost", "nn": "MLP", "ngboost": "NGBoost"}
FOLDER = {"system": "overall", "regional": "regional"}
TOL = 0.01
RES_CACHE = DATA / "10_stored_residuals.npz"
RES_COLS = DATA / "10_stored_residuals_cols.json"
AFTER = DATA / "after_fix"
OLD = {  # constraints_check.md, RF, all four rules (system side is untouched by the fix)
    "sys_mean": 0.7492, "sys_median": 0.8819, "cost_total_r2": 0.9117,
    "neg_pct_before": 0.295, "cost_viol_before": 355,
    "add_viol_before": 14943, "add_pairs_before": 23544, "add_viol_after_paper": 1167,
    "reg_mean_paper": 0.630, "reg_median_paper": 0.714,
}


# ---------------------------------------------------------------------------
# Stored OOF residuals (read once from the artefacts, cached)
# ---------------------------------------------------------------------------
def stored_residuals():
    if RES_CACHE.exists() and RES_COLS.exists():
        z = np.load(RES_CACHE)
        return {k: z[k] for k in z.files}, json.loads(RES_COLS.read_text())
    res, cols = {}, {}
    for layer in ("system", "regional"):
        mdir = resolve_models_dir(LAYERS[layer]["out"])
        for m in MODELS:
            print(f"  reading {layer}/{m}.joblib", flush=True)
            with open(mdir / f"{m}.joblib", "rb") as f:
                art = pickle.load(f)
            res[f"{layer}_{m}"] = np.asarray(art["oof_residuals"], dtype=np.float32)
            cols[f"{layer}_{m}"] = list(art["y_cols"])
            del art
    np.savez_compressed(RES_CACHE, **res)
    RES_COLS.write_text(json.dumps(cols))
    return res, cols


# ---------------------------------------------------------------------------
# Constraint stack over all runs
# ---------------------------------------------------------------------------
def constrain(Ps, Pr, sys_cols, reg_cols, sys_const, reg_const, cfg, floors=None):
    S, R = np.empty_like(Ps), np.empty_like(Pr)
    for i in range(Ps.shape[0]):
        s = apply_constraints(pd.Series(Ps[i], index=sys_cols), constants=sys_const,
                              floors=system_transmission_floors(floors or {}), config=cfg)
        r = apply_constraints(pd.Series(Pr[i], index=reg_cols), overall_pred=s,
                              constants=reg_const, floors=floors, config=cfg)
        S[i] = s.reindex(sys_cols).to_numpy()
        R[i] = r.reindex(reg_cols).to_numpy()
    return S, R


# ---------------------------------------------------------------------------
# Metrics (same definitions as 04 / 09)
# ---------------------------------------------------------------------------
def neg_stats(P, cols):
    m = non_negative_mask(cols)
    neg = P[:, m] < 0
    return dict(neg_cells=int(neg.sum()), must_pos_cells=int(neg.size), neg_pct=100 * float(neg.mean()))


def cost_viol(P, cols):
    comps = [cols.index(c) for c in cost_component_cols(cols)]
    tot = P[:, cols.index("cost_total")]
    rel = np.abs(P[:, comps].sum(axis=1) - tot) / np.abs(tot)
    return int((rel > TOL).sum())


def add_stats(P_reg, reg_cols, reg_const, P_sys, sys_cols):
    """S = modelled regional predictions + dropped-constant regional columns,
    T = system prediction, 63 quantities (regional_groups), violation if
    |S-T|/|T| > 1 %; pairs with T = 0 are left out of the denominator."""
    Ss, Ts = [], []
    for parent, (cols, const) in regional_groups(reg_cols, reg_const, sys_cols).items():
        Ss.append(P_reg[:, [reg_cols.index(c) for c in cols]].sum(axis=1) + const)
        Ts.append(P_sys[:, sys_cols.index(parent)])
    S, T = np.column_stack(Ss), np.column_stack(Ts)
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.abs(S - T) / np.abs(T)
    fin = np.isfinite(rel)
    return dict(add_viol=int((rel[fin] > TOL).sum()), add_pairs=int(fin.sum()),
                add_T0_S_nonzero=int(((T == 0) & (np.abs(S) > 1e-6)).sum()),
                add_quantities=len(Ss))


def scores(Y, P, cols):
    r2 = per_output_r2(Y, P)
    s = r2_summary(r2)
    s["n_gt_0_9"] = int(np.sum(r2 > 0.9))
    return s, pd.Series(r2, index=cols)


# ---------------------------------------------------------------------------
# Part 3: bounds audit
# ---------------------------------------------------------------------------
def cf_pairs(cols, const):
    """(gen col, cap col) with gen modelled, cap modelled or held constant,
    storage skipped."""
    out = []
    for g in cols:
        if not g.startswith("gen_") or _is_storage_gen(g):
            continue
        c = "cap_" + g[len("gen_"):]
        if c in cols or c in const:
            out.append((g, c))
    return out


def cf_audit(df_raw, P, cols, const):
    rows = []
    for g, c in cf_pairs(cols, const):
        cap_o, gen_o = df_raw[c].to_numpy(float), df_raw[g].to_numpy(float)
        ok = cap_o >= 1.0
        if not ok.any():
            continue
        ceiling = float(np.max(gen_o[ok] / (8760.0 * cap_o[ok])))
        cap_p = P[:, cols.index(c)] if c in cols else np.full(P.shape[0], float(const[c]))
        gen_p = P[:, cols.index(g)]
        okp = cap_p >= 1.0
        cf_p = gen_p[okp] / (8760.0 * cap_p[okp])
        rows.append(dict(gen=g, cap=c, cap_held_constant=c not in cols, cf_ceiling=ceiling,
                         n_eval=int(okp.sum()), n_over=int((cf_p > ceiling * (1 + TOL)).sum()),
                         max_pred_cf=float(cf_p.max()) if cf_p.size else np.nan))
    return pd.DataFrame(rows)


def tran_audit(df_raw, P, cols):
    rows = []
    for c in cols:
        if not c.startswith("tran_"):
            continue
        floor = float(df_raw[c].min())
        p = P[:, cols.index(c)]
        rows.append(dict(column=c, floor=floor, n_eval=int(p.size),
                         n_below=int((p < floor * (1 - TOL)).sum()), min_pred=float(p.min())))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Figures (IEEE single column)
# ---------------------------------------------------------------------------
BUCKETS = [(-np.inf, 0.0, "R² < 0"), (0.0, 0.5, "0–0.5"), (0.5, 0.9, "0.5–0.9"), (0.9, np.inf, "≥ 0.9")]


def bucket_counts(r2):
    r2 = np.asarray(r2)
    return [int(((r2 >= lo) & (r2 < hi)).sum()) for lo, hi, _ in BUCKETS]


def fig_buckets(r2_sys, r2_reg):
    fig, ax = new_fig(height=2.2)
    x = np.arange(len(BUCKETS))
    w = 0.38
    for k, (r2, lab, col) in enumerate(((r2_sys, f"System (n={len(r2_sys)})", PALETTE[0]),
                                        (r2_reg, f"Regional (n={len(r2_reg)})", PALETTE[1]))):
        cnt = bucket_counts(r2)
        pct = 100 * np.array(cnt) / len(r2)
        xs = x + (k - 0.5) * w
        ax.bar(xs, pct, w * 0.92, color=col, label=lab, edgecolor="white", linewidth=0.6)
        for xi, p, n in zip(xs, pct, cnt):
            ax.text(xi, p + 1.2, f"{n}", ha="center", va="bottom", fontsize=6, color=INK)
    ax.set_xticks(x)
    ax.set_xticklabels([b[2] for b in BUCKETS])
    ax.set_xlabel("Out-of-fold R² (Random Forest, no constraints)")
    ax.set_ylabel("Share of outputs (%)")
    ax.set_ylim(0, 60)
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper left")
    save_fig(fig, "buckets")


def fig_ranking(r2_sys):
    s = r2_sys.sort_values()
    lo = -0.5
    fig, ax = new_fig(height=6.6)
    y = np.arange(len(s))
    vals = np.clip(s.to_numpy(), lo, 1.0)
    neg = s.to_numpy() < 0
    ax.hlines(y, 0, vals, color=GRAY, linewidth=0.6)
    ax.scatter(vals[~neg], y[~neg], s=9, color=PALETTE[0], zorder=3, label="R² ≥ 0")
    ax.scatter(vals[neg], y[neg], s=9, facecolor="white", edgecolor=PALETTE[0], linewidth=0.9,
               zorder=3, label="R² < 0")
    for yi, v in zip(y[neg], s.to_numpy()[neg]):
        ax.text(max(v, lo) - 0.03, yi, f"{v:.2f}", ha="right", va="center", fontsize=5, color=INK)
    ax.axvline(0.9, color=GRAY, linewidth=0.6, linestyle=(0, (3, 2)))
    ax.set_yticks(y)
    ax.set_yticklabels(s.index, fontsize=4.6)
    ax.set_ylim(-0.8, len(s) - 0.2)
    ax.set_xlim(lo - 0.25, 1.02)
    ax.set_xlabel("Out-of-fold R² (RF, system)")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right")
    save_fig(fig, "r2_ranking_rf")


def fig_ba_heatmap(r2_reg):
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap
    set_style()
    df = pd.DataFrame({"r2": r2_reg})
    df["region"] = [re.search(r"_(p\d+)$", c).group(1) if re.search(r"_(p\d+)$", c) else None
                    for c in df.index]
    df["base"] = [re.sub(r"_p\d+$", "", c) for c in df.index]
    tran = df.index.str.startswith("tran_")
    df.loc[tran, "region"] = None
    df = df[df.region.notna()]
    grid = df.pivot_table(index="base", columns="region", values="r2", aggfunc="mean")
    grid = grid.reindex(columns=sorted(grid.columns, key=lambda r: int(r[1:])))
    grid = grid.loc[grid.mean(axis=1).sort_values(ascending=False).index]
    # sequential blue ramp for 0..1 in 0.1 steps; R2 < 0 is a separate neutral class
    ramp = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5",
            "#2a78d6", "#1c5cab", "#104281"]
    cmap = ListedColormap(["#d9d7d2"] + ramp)
    cmap.set_bad("white")
    norm = BoundaryNorm([-1e9, 0] + list(np.linspace(0.1, 1.0, 10)), cmap.N)
    n = len(grid)
    fig, ax = plt.subplots(figsize=(3.5, 0.105 * n + 0.9))
    data = np.ma.masked_invalid(grid.to_numpy(float))
    im = ax.imshow(data, aspect="auto", cmap=cmap, norm=norm, interpolation="nearest")
    neg = np.argwhere(np.nan_to_num(grid.to_numpy(float), nan=1.0) < 0)
    for (i, j) in neg:
        ax.text(j, i, "<0", ha="center", va="center", fontsize=4, color=INK)
    ax.set_xticks(range(grid.shape[1]))
    ax.set_xticklabels(grid.columns, fontsize=6)
    ax.xaxis.tick_top()
    ax.set_yticks(range(n))
    ax.set_yticklabels(grid.index, fontsize=4.4)
    ax.tick_params(length=0)
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.05, pad=0.02, ticks=[-0.5, 0.1, 0.5, 0.9, 1.0])
    cb.ax.set_yticklabels(["< 0", "0.1", "0.5", "0.9", "1"], fontsize=6)
    cb.set_label("Out-of-fold R² (RF, per BA)", fontsize=7)
    cb.outline.set_visible(False)
    save_fig(fig, "ba_heatmap_rf")
    return grid


# ---------------------------------------------------------------------------
def main():
    J = {}
    Xs, Ys_raw, x_cols, sys_cols, _, sys_const = load_layer("system", clip=False)
    _, Ys_clip, _, _, _, _ = load_layer("system")
    Xr, Yr_raw, _, reg_cols, _, reg_const = load_layer("regional", clip=False)
    _, Yr_clip, _, _, _, _ = load_layer("regional")
    assert np.array_equal(Xs, Xr)
    df_raw = {"system": pd.read_csv(LAYERS["system"]["data"]),
              "regional": pd.read_csv(LAYERS["regional"]["data"])}
    truth = {"system": Ys_raw, "regional": Yr_raw}
    cols = {"system": sys_cols, "regional": reg_cols}
    clipY = {"system": Ys_clip, "regional": Yr_clip}
    floors = transmission_floors(df_raw["regional"])   # corridor floor = min over runs

    res, rcols = stored_residuals()
    old, new = {}, {}
    full = Stage2InferenceConfig()
    for m in MODELS:
        for layer in ("system", "regional"):
            assert rcols[f"{layer}_{m}"] == cols[layer], f"column order differs for {layer}/{m}"
            old[(layer, m)] = clipY[layer] - res[f"{layer}_{m}"].astype(np.float64)
        print(f"  constraining {m}", flush=True)
        new[("system", m)], new[("regional", m)] = constrain(
            old[("system", m)], old[("regional", m)], sys_cols, reg_cols, sys_const, reg_const, full,
            floors)

    # ---------------------------------------------------------------- Table III
    summ = json.loads((LAYERS["system"]["out"] / "summary.json").read_text())
    summ_r = json.loads((LAYERS["regional"]["out"] / "summary.json").read_text())
    sj = {"system": summ, "regional": summ_r}
    t3, per_out = [], []
    for m in MODELS:
        for layer in ("system", "regional"):
            so, r2o = scores(truth[layer], old[(layer, m)], cols[layer])
            sn, r2n = scores(truth[layer], new[(layer, m)], cols[layer])
            sc, _ = scores(clipY[layer], old[(layer, m)], cols[layer])   # pipeline definition
            ref = sj[layer]["models"][m]
            t3.append(dict(model=NAME[m], layer=layer,
                           old_mean=so["mean"], new_mean=sn["mean"],
                           old_median=so["median"], new_median=sn["median"],
                           old_n_gt_0_9=so["n_gt_0_9"], new_n_gt_0_9=sn["n_gt_0_9"],
                           summary_json_mean=ref["oof_r2_mean"],
                           summary_json_match=bool(abs(sc["mean"] - ref["oof_r2_mean"]) < 5e-4
                                                   and sc["n_gt_0_9"] == ref["n_outputs_r2_above_0.9"])))
            for c in cols[layer]:
                per_out.append(dict(model=m, layer=layer, output=c, r2_old=r2o[c], r2_new=r2n[c]))
            # files laid out like Stage2/outputs/<layer>/ for the figure scripts
            d = AFTER / FOLDER[layer]
            d.mkdir(parents=True, exist_ok=True)
            P = new[(layer, m)]
            Y = truth[layer]
            rmse = np.sqrt(((P - Y) ** 2).mean(axis=0))
            rng = Y.max(axis=0) - Y.min(axis=0)
            pd.DataFrame({"output": cols[layer], "r2": r2n.to_numpy(), "rmse": rmse,
                          "mae": np.abs(P - Y).mean(axis=0),
                          "nrmse": np.where(rng > 0, rmse / np.where(rng > 0, rng, 1), 0.0)}
                         ).to_csv(d / f"per_output_metrics_{m}.csv", index=False)
    t3 = pd.DataFrame(t3)
    t3.to_csv(DATA / "10_table3.csv", index=False)
    per_out = pd.DataFrame(per_out)
    per_out.to_csv(DATA / "10_per_output_old_new.csv", index=False)
    for layer in ("system", "regional"):
        d = AFTER / FOLDER[layer]
        models_js = {}
        for m in MODELS:
            row = t3[(t3.model == NAME[m]) & (t3.layer == layer)].iloc[0]
            r2n = per_out[(per_out.model == m) & (per_out.layer == layer)].r2_new
            models_js[m] = {"display_name": sj[layer]["models"][m].get("display_name", NAME[m]),
                            "oof_r2_mean": float(row.new_mean), "oof_r2_median": float(row.new_median),
                            "oof_r2_min": float(r2n.min()), "oof_r2_max": float(r2n.max()),
                            "n_outputs_r2_above_0.9": int(row.new_n_gt_0_9),
                            "n_outputs_r2_above_0.95": int((r2n > 0.95).sum())}
        (d / "summary.json").write_text(json.dumps({
            "note": "Stored OOF predictions with the fixed Stage 2 constraint layer applied "
                    "(analysis/pesgm/10_after_fix.py); scored against the raw ReEDS targets.",
            "models": models_js, "constant_outputs": sj[layer]["constant_outputs"]}, indent=2))
        np.savez_compressed(d / "oof_rf.npz", y_cols=np.array(cols[layer]), Y=truth[layer],
                            oof=new[(layer, "rf")])

    # ---------------------------------------------------------------- RF figures
    r2s = per_out[(per_out.model == "rf") & (per_out.layer == "system")].set_index("output").r2_new
    r2r = per_out[(per_out.model == "rf") & (per_out.layer == "regional")].set_index("output").r2_new
    r2s_old = per_out[(per_out.model == "rf") & (per_out.layer == "system")].set_index("output").r2_old
    r2r_old = per_out[(per_out.model == "rf") & (per_out.layer == "regional")].set_index("output").r2_old
    # Paper figures use the raw OOF scores (no constraints), like Table III.
    fig_buckets(r2s_old.to_numpy(), r2r_old.to_numpy())
    fig_ranking(r2s_old)
    fig_ba_heatmap(r2r_old)
    J["buckets"] = {"system_old": bucket_counts(r2s_old), "system_new": bucket_counts(r2s),
                    "regional_old": bucket_counts(r2r_old), "regional_new": bucket_counts(r2r)}

    # ---------------------------------------------------------------- ablation (RF)
    P0 = np.load(DATA / "09_oof_cache.npz")
    P0s, P0r = P0["P0s"], P0["P0r"]
    Ps, Pr = old[("system", "rf")], old[("regional", "rf")]
    configs = [
        ("none", P0s, P0r, Stage2InferenceConfig(apply_non_negativity=False, apply_additivity=False,
                                                 apply_constant_override=False, apply_cost_decomposition=False)),
        ("+1", Ps, Pr, Stage2InferenceConfig(apply_non_negativity=True, apply_additivity=False,
                                             apply_constant_override=False, apply_cost_decomposition=False)),
        ("+1,2", Ps, Pr, Stage2InferenceConfig(apply_non_negativity=True, apply_additivity=True,
                                               apply_constant_override=False, apply_cost_decomposition=False)),
        ("+1,2,3", Ps, Pr, Stage2InferenceConfig(apply_non_negativity=True, apply_additivity=True,
                                                 apply_constant_override=True, apply_cost_decomposition=False)),
        ("all four", Ps, Pr, full),
    ]
    abl, abl_r2 = [], {}
    for name, A, B, cfg in configs:
        S, R = constrain(A, B, sys_cols, reg_cols, sys_const, reg_const, cfg, floors)
        ss, r2s_c = scores(Ys_raw, S, sys_cols)
        rs, r2r_c = scores(Yr_raw, R, reg_cols)
        a = add_stats(R, reg_cols, reg_const, S, sys_cols)
        ns = neg_stats(S, sys_cols)
        abl.append(dict(config=name, sys_mean=ss["mean"], sys_median=ss["median"],
                        reg_mean=rs["mean"], reg_median=rs["median"], cost_total_r2=r2s_c["cost_total"],
                        neg_cells=ns["neg_cells"], neg_pct=ns["neg_pct"], must_pos_cells=ns["must_pos_cells"],
                        cost_viol_runs=cost_viol(S, sys_cols), add_viol=a["add_viol"],
                        add_pairs=a["add_pairs"], add_T0_S_nonzero=a["add_T0_S_nonzero"]))
        abl_r2[name] = pd.concat([r2s_c.add_prefix("system:"), r2r_c.add_prefix("regional:")])
    abl = pd.DataFrame(abl)
    abl.to_csv(DATA / "10_ablation.csv", index=False)
    steps = []
    names = [c[0] for c in configs]
    for a_, b_ in zip(names[:-1], names[1:]):
        d = (abl_r2[b_] - abl_r2[a_]).abs()
        steps.append(dict(step=f"{a_} -> {b_}", max_change=float(d.max()), output=str(d.idxmax()),
                          n_gt_0_005=int((d > 0.005).sum())))
    J["ablation_steps"] = steps
    byname = abl.set_index("config")
    J["four_numbers"] = dict(
        neg_before=byname.loc["none", ["neg_cells", "must_pos_cells", "neg_pct"]].to_dict(),
        neg_stored_oof=int(neg_stats(Ps, sys_cols)["neg_cells"]),
        neg_stored_min=float(Ps[:, non_negative_mask(sys_cols)].min()),
        neg_after=int(byname.loc["all four", "neg_cells"]),
        cost_before=int(byname.loc["+1", "cost_viol_runs"]), cost_after=int(byname.loc["all four", "cost_viol_runs"]),
        add_before=(int(byname.loc["+1", "add_viol"]), int(byname.loc["+1", "add_pairs"])),
        add_after=(int(byname.loc["all four", "add_viol"]), int(byname.loc["all four", "add_pairs"])),
        add_reduction_pct=100 * (1 - byname.loc["all four", "add_viol"] / byname.loc["+1", "add_viol"]),
        add_T0_S_nonzero_before=int(byname.loc["+1", "add_T0_S_nonzero"]),
        add_T0_S_nonzero_after=int(byname.loc["all four", "add_T0_S_nonzero"]),
    )

    # ---------------------------------------------------------------- transmission (RF)
    S_all, R_all = new[("system", "rf")], new[("regional", "rf")]
    corr = [c for c in reg_cols if c.startswith("tran_")]
    const_tran = sum(v for k, v in reg_const.items() if k.startswith("tran_"))
    S_tr = R_all[:, [reg_cols.index(c) for c in corr]].sum(axis=1) + const_tran
    T_tr = S_all[:, sys_cols.index("tran_total")]
    gap = np.abs(S_tr - T_tr) / np.abs(T_tr)
    fl_sum = sum(floors[c] for c in floors) 
    below_floor_target = int((T_tr < fl_sum).sum())
    po_rf = per_out[(per_out.model == "rf") & (per_out.layer == "regional")].set_index("output")
    init = pd.read_csv(DATA / "12_corridor_floor_vs_init.csv", index_col=0)
    J["transmission"] = dict(
        n_corridors=len(floors), floors_equal_initial=bool((init["min_minus_init"].abs() < 1e-6).all()),
        below_floor_after=int(sum((R_all[:, reg_cols.index(c)] < floors[c] * (1 - TOL)).sum() for c in corr)),
        below_floor_any_after=int(sum((R_all[:, reg_cols.index(c)] < floors[c] - 1e-9).sum() for c in corr)),
        n_pred=int(len(corr) * R_all.shape[0]),
        p60_p61_r2_old=float(po_rf.loc["tran_p60_p61_AC", "r2_old"]),
        p60_p61_r2_new=float(po_rf.loc["tran_p60_p61_AC", "r2_new"]),
        tran_total_runs_exact=int((gap <= 1e-9).sum()), tran_total_runs_off_1pct=int((gap > TOL).sum()),
        tran_total_runs_system_below_floor_sum=below_floor_target,
        tran_total_max_rel_gap=float(gap.max()),
        system_shortfall_below_floor_sum_MW=float(max(0.0, (fl_sum - T_tr).max())),
        min_pred_minus_floor_MW=float(min((R_all[:, reg_cols.index(c)] - floors[c]).min() for c in corr)),
        tran_r2=po_rf.loc[corr, ["r2_old", "r2_new"]].to_dict("index"),
    )

    # ---------------------------------------------------------------- Part 3 audit
    audits_cf, audits_tr = [], []
    for m in ("rf", "nn", "ridge"):
        for layer in ("system", "regional"):
            const = sys_const if layer == "system" else reg_const
            for which, P in (("stored OOF", old[(layer, m)]), ("after fix", new[(layer, m)])):
                a = cf_audit(df_raw[layer], P, cols[layer], const)
                a.insert(0, "model", NAME[m]); a.insert(1, "layer", layer); a.insert(2, "predictions", which)
                audits_cf.append(a)
                t = tran_audit(df_raw[layer], P, cols[layer])
                t.insert(0, "model", NAME[m]); t.insert(1, "layer", layer); t.insert(2, "predictions", which)
                audits_tr.append(t)
    cf = pd.concat(audits_cf, ignore_index=True)
    tr = pd.concat(audits_tr, ignore_index=True)
    cf.to_csv(DATA / "10_audit_cf_ceiling.csv", index=False)
    tr.to_csv(DATA / "10_audit_tran_floor.csv", index=False)

    write = lambda o: json.dumps(o, indent=2, default=lambda v: v.item() if hasattr(v, "item") else str(v))
    (DATA / "10_after_fix.json").write_text(write(J))
    write_report(t3, per_out, abl, J, cf, tr)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def f3(v):
    return f"{v:.3f}"


def f4(v):
    return f"{v:.4f}"


def write_report(t3, per_out, abl, J, cf, tr):
    L = ["# Results after the constraint-layer fix\n",
         "Generated by `10_after_fix.py` (reeds2 env). Every model's **stored** out-of-fold (OOF) "
         "predictions are used as they are; no model was retrained. All R² values are scored against "
         "the raw ReEDS targets, over the 66 system and 308 regional modelled outputs.\n",
         "**Which numbers use the constraints.** Table III and the bucket and ranking figures use the "
         "**raw OOF scores (no constraints)** for every model. That is what the training pipeline's "
         "`summary.json` reports. Section D reports the effect of the constraint layer for the Random "
         "Forest (RF) only (Parts 2d, 2e, 2g, 2.9 and 3). There, \"old\" means the stored OOF predictions "
         "with no prediction-time rules, and \"new\" means after the fixed layer. The fixed layer holds "
         "constants, then clips, then rescales regional values to the system value, then applies the cost "
         "identity. Transmission corridors are rescaled only above their floor.\n"]

    # ---------------- Table III
    L.append("## Part 2a. Table III: raw OOF scores (no constraints), all models\n")
    L.append("These numbers reproduce `summary.json`, where the pipeline scores against clipped targets, "
             f"for {int(t3.summary_json_match.sum())} of {len(t3)} model-layer rows. The constrained "
             "values for every model are in `data/10_table3.csv` (`new_*` columns) and are not used in "
             "the paper.\n")
    show = t3.copy()
    for c in ("old_mean", "old_median"):
        show[c] = show[c].map(f3)
    show = show.rename(columns={"old_mean": "mean R²", "old_median": "median R²",
                                "old_n_gt_0_9": "outputs R² > 0.9"})
    L.append(md_table(show[["model", "layer", "mean R²", "median R²", "outputs R² > 0.9"]]))
    L.append("")
    for _, r in t3.iterrows():
        n_out = 66 if r.layer == "system" else 308
        L.append(f"- {r.model}, {r.layer}, raw OOF: mean / median R² {f3(r.old_mean)} / {f3(r.old_median)}, "
                 f"with {r.old_n_gt_0_9} of {n_out} outputs above 0.9.")
    L.append("")

    # ---------------- figures
    b = J["buckets"]
    L.append("## Part 2b–c. RF figures (raw OOF scores, no constraints)\n")
    L.append("The figures are `figs/buckets`, `figs/r2_ranking_rf` and `figs/ba_heatmap_rf` (PDF + 300 dpi "
             "PNG). They use the raw OOF scores, like Table III. The OneDrive copies keep their old names "
             "and were regenerated from the raw pipeline outputs.\n")
    labs = [x[2] for x in BUCKETS]
    for layer in ("system", "regional"):
        L.append(f"- RF {layer} bucket counts, raw OOF ({', '.join(labs)}): {b[f'{layer}_old']}. "
                 f"For reference, after the constraint layer: {b[f'{layer}_new']}.")
    L.append("")

    # ---------------- four numbers
    F = J["four_numbers"]
    L.append("## Part 2d. The four ablation numbers (RF)\n")
    nb = F["neg_before"]
    L.append(f"- Negative values with no rules: {int(nb['neg_cells'])} of {int(nb['must_pos_cells'])} "
             f"must-be-positive system cells ({nb['neg_pct']:.2f}%). This uses the raw-target CV refit, "
             f"as before. The stored OOF predictions contain {F['neg_stored_oof']}, all at or above "
             f"{F['neg_stored_min']:.3f} dollars. They come from the float32 storage of the residuals. "
             f"After all rules there are {F['neg_after']}.")
    L.append(f"- cost_total more than 1% off the sum of its components: {F['cost_before']} of 486 runs "
             f"before (old {OLD['cost_viol_before']}), {F['cost_after']} after.")
    ab, aa = F["add_before"], F["add_after"]
    L.append(f"- Regional sums more than 1% off the system prediction: {ab[0]:,} of {ab[1]:,} pairs before "
             f"({100*ab[0]/ab[1]:.1f}%; old {OLD['add_viol_before']:,} of {OLD['add_pairs_before']:,}). "
             f"After: {aa[0]:,} of {aa[1]:,} ({100*aa[0]/aa[1]:.1f}%; old paper figure "
             f"{OLD['add_viol_after_paper']:,}). Pairs where the system prediction is 0 are left out of "
             f"the denominator, as before. Among them, pairs with a non-zero regional sum: "
             f"{F['add_T0_S_nonzero_before']:,} before and {F['add_T0_S_nonzero_after']:,} after.")
    L.append(f"- Reduction in additivity violations: {F['add_reduction_pct']:.1f}% (old paper figure 92%).")
    L.append("")

    # ---------------- cumulative ablation
    L.append("## Part 2e. Cumulative per-rule ablation (RF, fixed rule 2)\n")
    L.append("Rules are added in the paper's order (1 non-negativity, 2 regional additivity, 3 constants "
             "held, 4 cost identity). Within each row they run in the code's order. \"none\" uses the "
             "raw-target CV refit with no rules. The other rows use the stored OOF predictions.\n")
    s = abl.copy()
    for c in ("sys_mean", "sys_median", "reg_mean", "reg_median", "cost_total_r2"):
        s[c] = s[c].map(f4)
    s["neg_pct"] = s["neg_pct"].map(lambda v: f"{v:.2f}%")
    s["additivity >1% (pairs)"] = [f"{a:,} / {p:,}" for a, p in zip(abl.add_viol, abl.add_pairs)]
    L.append(md_table(s[["config", "sys_mean", "sys_median", "reg_mean", "reg_median", "cost_total_r2",
                         "neg_cells", "neg_pct", "cost_viol_runs", "additivity >1% (pairs)"]]))
    L.append("")
    for st in J["ablation_steps"]:
        L.append(f"- Step {st['step']}: the largest change in any output's R² is {st['max_change']:.4f} "
                 f"({st['output']}), and {st['n_gt_0_005']} outputs change by more than 0.005.")
    L.append("")

    # ---------------- transmission (floor-preserving rescale)
    T = J["transmission"]
    L.append("## Part 2g. Transmission corridors with the floor-preserving rescale (RF)\n")
    L.append(f"- Floors: for all {T['n_corridors']} corridors, the minimum over the 486 runs equals the initial "
             f"corridor capacity, (forward + reverse ITL) / 2 for the z134 zones "
             f"({'they agree exactly' if T['floors_equal_initial'] else 'they do NOT agree'}; "
             f"`data/12_corridor_floor_vs_init.csv`).")
    L.append(f"- Corridor predictions more than 1% below the floor after all rules: {T['below_floor_after']} of "
             f"{T['n_pred']} (583 with the plain rescale). "
             + ("No prediction is below its floor by any amount."
                if T["min_pred_minus_floor_MW"] >= 0 else
                f"The lowest is {-T['min_pred_minus_floor_MW']:.1e} MW below its floor (round-off)."))
    L.append(f"- tran_p60_p61_AC R²: {f3(T['p60_p61_r2_old'])} raw, {f3(T['p60_p61_r2_new'])} after the fix "
             f"(0.082 with the plain rescale).")
    n_floor_runs = T["tran_total_runs_system_below_floor_sum"]
    L.append(f"- tran_total additivity holds in all 486 runs: the largest relative gap between the corridor "
             f"sum and the system tran_total is {T['tran_total_max_rel_gap']:.1e}. The system tran_total is "
             f"clipped to the sum of the corridor floors (34,478.6 MW) before the rescale"
             + (f"; in {n_floor_runs} runs it sits at that sum and every corridor is set to its floor."
                if n_floor_runs else "."))
    for c, v in T["tran_r2"].items():
        L.append(f"- {c} R²: {f3(v['r2_old'])} raw, {f3(v['r2_new'])} after the fix.")
    L.append("")

    # ---------------- Part 2.9
    rf = per_out[per_out.model == "rf"]
    sysrf = rf[rf.layer == "system"]
    regrf = rf[rf.layer == "regional"]
    alln = abl.set_index("config").loc["all four"]
    L.append("## Part 2.9 System numbers unchanged, regional numbers moved (RF)\n")
    L.append(f"- System mean / median R² after all rules: {f4(alln.sys_mean)} / {f4(alln.sys_median)} "
             f"(constraints_check.md: {OLD['sys_mean']} / {OLD['sys_median']}). cost_total R²: "
             f"{f4(alln.cost_total_r2)} (constraints_check.md: {OLD['cost_total_r2']}).")
    sys_moved = sysrf[(sysrf.r2_new - sysrf.r2_old).abs() > 5e-4]
    L.append(f"- System outputs whose R² moves by more than 0.0005: "
             f"{', '.join(f'{r.output} {f3(r.r2_old)} → {f3(r.r2_new)}' for r in sys_moved.itertuples()) or 'none'}.")
    L.append(f"- Regional mean / median R²: {f4(regrf.r2_old.mean())} / {f4(regrf.r2_old.median())} → "
             f"{f4(regrf.r2_new.mean())} / {f4(regrf.r2_new.median())} (the paper's earlier figure, from a "
             f"re-implementation of the rescale: {OLD['reg_mean_paper']} / {OLD['reg_median_paper']}).")
    moved = regrf[(regrf.r2_new.round(3) != regrf.r2_old.round(3))].copy()
    moved["delta"] = moved.r2_new - moved.r2_old
    L.append(f"- {len(moved)} of {len(regrf)} regional outputs change at 3-decimal precision "
             f"({int((moved.delta > 0).sum())} up, {int((moved.delta < 0).sum())} down). The full list is "
             f"in the appendix; `data/10_per_output_old_new.csv` has every model.")
    L.append("")

    # ---------------- Part 3
    L.append("## Part 3. Bounds audit (no code change)\n")
    L.append("Capacity-factor ceiling: the cap is the maximum over the 486 runs of gen / (8760 × cap) "
             "among runs with cap ≥ 1 MW. A prediction counts when predicted cap ≥ 1 MW and the predicted "
             "CF exceeds the ceiling by more than 1%. Storage is skipped. A capacity held constant "
             "(e.g. cap_distpv) is used at its constant value. Transmission floor: the minimum over the "
             "486 runs for each column. A prediction counts when it is more than 1% below the floor.\n")
    for (m, layer, which), g in cf.groupby(["model", "layer", "predictions"], sort=False):
        bad = g[g.n_over > 0]
        L.append(f"- CF ceiling, {m}, {layer}, {which}: {int(g.n_over.sum())} of {int(g.n_eval.sum())} "
                 f"predictions exceed the ceiling over {len(g)} technologies"
                 + (f" ({'; '.join(f'{r.gen} {r.n_over}' for r in bad.itertuples())})." if len(bad) else "."))
    for (m, layer, which), g in tr.groupby(["model", "layer", "predictions"], sort=False):
        bad = g[g.n_below > 0]
        L.append(f"- Transmission floor, {m}, {layer}, {which}: {int(g.n_below.sum())} of {int(g.n_eval.sum())} "
                 f"predictions fall below the floor over {len(g)} columns"
                 + (f" ({'; '.join(f'{r.column} {r.n_below}' for r in bad.itertuples())})." if len(bad) else "."))
    L.append("")
    L.append("Per-technology detail: `data/10_audit_cf_ceiling.csv`, `data/10_audit_tran_floor.csv`.\n")

    # ---------------- appendix
    L.append("## Appendix. RF regional outputs whose R² changed (old → new)\n")
    a = moved.sort_values("delta")[["output", "r2_old", "r2_new", "delta"]]
    L.append(md_table(a, "{:.3f}"))
    (HERE / "results_after_fix.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote results_after_fix.md")


if __name__ == "__main__":
    main()
