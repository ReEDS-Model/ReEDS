"""DEPRECATED - pre-fix record only; it no longer runs (it imports the DistPV
function removed in the constraint fix). Its results stay in
constraints_check.md, results_09.md and data/09_* (10_after_fix.py still reads
data/09_oof_cache.npz). Use 10_after_fix.py for the current constraint layer.

Item 9 - constraint-layer fact check for the paper's Section D / Table II.

Answers the questions in constraints_check.md from the data and from the
Stage 2 constraint code itself. The prediction-time rules are applied with the
pipeline's own ``surrogate_constraints.apply_constraints`` (row by row, with
``Stage2InferenceConfig`` switches), not a re-implementation, so the order and
skip conditions are exactly those of the code.

OOF predictions: RF, 10-fold, seed 42 (``pesgm_common.rf_oof`` reproduces the
pipeline's ``compute_oof_predictions``). Two sets are fitted per layer:
  P0 = trained on raw targets (rule 1 off at training time)
  P1 = trained on clipped targets (``load_data`` + ``clip_train_targets``)

Writes data/09_*.csv, data/09_constraints_check.json, results_09.md.
Run with the reeds2 env.
"""
from __future__ import annotations

raise SystemExit("09_constraints_check.py is deprecated (pre-fix record); use 10_after_fix.py.")

import re

import numpy as np
import pandas as pd

from pesgm_common import (
    DATA, HERE, LAYERS, load_layer, md_table, non_negative_mask, regional_groups,
    per_output_r2, r2_summary, rf_oof, stored_oof, write_json,
)
from surrogate_constraints import (  # noqa: E402  (path set by pesgm_common)
    Stage2InferenceConfig, _split_regional, apply_constraints, cost_component_cols,
    dgen_distpv_cap_mw, _is_storage_gen, _is_negative_cost,
)
from surrogate_predict import clip_physical_bounds  # noqa: E402

TOL = 0.01
OOF_CACHE = DATA / "09_oof_cache.npz"


# ---------------------------------------------------------------------------
# OOF predictions (cached)
# ---------------------------------------------------------------------------
def get_oof(Xs, Ys_raw, Ys_clip, Xr, Yr_raw, Yr_clip):
    if OOF_CACHE.exists():
        z = np.load(OOF_CACHE)
        return z["P0s"], z["P0r"], z["P1s"], z["P1r"]
    print("fitting OOF: system raw / clipped, regional raw / clipped", flush=True)
    P0s, _, _ = rf_oof(Xs, Ys_raw)
    P1s, _, _ = rf_oof(Xs, Ys_clip)
    P0r, _, _ = rf_oof(Xr, Yr_raw)
    P1r, _, _ = rf_oof(Xr, Yr_clip)
    np.savez_compressed(OOF_CACHE, P0s=P0s, P0r=P0r, P1s=P1s, P1r=P1r)
    return P0s, P0r, P1s, P1r


# ---------------------------------------------------------------------------
# Apply the code's constraint stack row by row
# ---------------------------------------------------------------------------
def run_stack(P_sys, P_reg, sys_cols, reg_cols, x_dem, cfg):
    """Return (sys_out, reg_out, reg_extra_cols). System rows are constrained
    first (overall_pred=None), then regional rows get the constrained system
    row as overall_pred, exactly as apply_constraints expects."""
    S = np.empty_like(P_sys)
    R = np.empty_like(P_reg)
    extra = set()
    for i in range(P_sys.shape[0]):
        s = apply_constraints(pd.Series(P_sys[i], index=sys_cols), x_dem_value=float(x_dem[i]),
                              overall_pred=None, config=cfg)
        r = apply_constraints(pd.Series(P_reg[i], index=reg_cols), x_dem_value=float(x_dem[i]),
                              overall_pred=s, config=cfg)
        extra |= set(r.index) - set(reg_cols)
        S[i] = s.reindex(sys_cols).to_numpy()
        R[i] = r.reindex(reg_cols).to_numpy()
    return S, R, sorted(extra)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def neg_stats(P, cols):
    m = non_negative_mask(cols)
    neg = P[:, m] < 0
    return dict(neg_cells=int(neg.sum()), must_pos_cells=int(neg.size),
                neg_pct=100 * float(neg.mean()), neg_runs=int(neg.any(axis=1).sum()),
                neg_outputs=[c for c, a in zip(np.asarray(cols)[m], neg.any(axis=0)) if a])


def cost_stats(P, cols):
    comps = [cols.index(c) for c in cost_component_cols(cols)]
    tot = P[:, cols.index("cost_total")]
    s = P[:, comps].sum(axis=1)
    rel = np.abs(s - tot) / np.abs(tot)
    return dict(cost_viol_runs=int((rel > TOL).sum()), cost_gap_median_pct=100 * float(np.median(rel)))


def add_rel(P_reg, reg_cols, reg_const, P_sys, sys_cols):
    """Paper / item-4 definition: for every quantity present in both layers
    (pesgm_common.regional_groups: regional suffix _pNN, tran_* corridors ->
    tran_total), S = sum of modelled regional predictions + dropped-constant
    regional columns, T = system prediction, rel = |S - T| / |T|.
    Returns (rel matrix runs x quantities, quantity names, S, T)."""
    groups = regional_groups(reg_cols, reg_const, sys_cols)
    names, Ss, Ts = [], [], []
    for parent, (cols, const) in groups.items():
        Ss.append(P_reg[:, [reg_cols.index(c) for c in cols]].sum(axis=1) + const)
        Ts.append(P_sys[:, sys_cols.index(parent)])
        names.append(parent)
    S, T = np.column_stack(Ss), np.column_stack(Ts)
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.abs(S - T) / np.abs(T)
    return rel, names, S, T


def add_stats(P_reg, reg_cols, reg_const, P_sys, sys_cols):
    rel, names, S, T = add_rel(P_reg, reg_cols, reg_const, P_sys, sys_cols)
    fin = np.isfinite(rel)
    t0_s_nonzero = int(((T == 0) & (np.abs(S) > 1e-6)).sum())
    return dict(add_quantities=len(names), add_pairs_all=int(rel.size), add_pairs_finite=int(fin.sum()),
                add_viol=int((rel[fin] > TOL).sum()), add_viol_pct=100 * float((rel[fin] > TOL).mean()),
                add_gap_median_pct=100 * float(np.median(rel[fin])),
                add_T0_S_nonzero=t0_s_nonzero)


def enforce_additivity_matrix_item4(P_reg, reg_cols, reg_const, P_sys, sys_cols):
    """Copy of 04_ablation.enforce_additivity_matrix (used for the paper's
    '92 %' number) so the reproduction is exact."""
    out = P_reg.copy()
    for parent, (cols, const) in regional_groups(reg_cols, reg_const, sys_cols).items():
        idx = [reg_cols.index(c) for c in cols]
        cur = out[:, idx].sum(axis=1)
        tgt = P_sys[:, sys_cols.index(parent)] - const
        scale = np.where((cur > 0) & (tgt > 0), tgt / np.where(cur > 0, cur, 1.0), 1.0)
        out[:, idx] = out[:, idx] * scale[:, None]
    return out


def clip_np(P, cols):
    out = P.copy()
    m = non_negative_mask(cols)
    out[:, m] = np.maximum(out[:, m], 0.0)
    return out


def score(Y, P, cols):
    r2 = per_output_r2(Y, P)
    s = r2_summary(r2)
    return s, dict(zip(cols, r2))


def main():
    J = {}
    # ------------------------------------------------------------------ data
    Xs, Ys_raw, x_cols, sys_cols, _, sys_const = load_layer("system", clip=False)
    _, Ys_clip, _, _, _, _ = load_layer("system")
    Xr, Yr_raw, _, reg_cols, _, reg_const = load_layer("regional", clip=False)
    _, Yr_clip, _, _, _, _ = load_layer("regional")
    assert np.array_equal(Xs, Xr)
    x_dem = Xs[:, x_cols.index("x_Dem")]
    df_sys = pd.read_csv(LAYERS["system"]["data"])
    df_reg = pd.read_csv(LAYERS["regional"]["data"])
    ycols_all = {"system": [c for c in df_sys.columns if not c.startswith("x_") and c != "case_name"],
                 "regional": [c for c in df_reg.columns if not c.startswith("x_") and c != "case_name"]}
    dfs = {"system": df_sys, "regional": df_reg}
    modelled = {"system": sys_cols, "regional": reg_cols}
    consts = {"system": sys_const, "regional": reg_const}

    # ---------------------------------------------------------------- Q2
    rows = []
    for layer in ("system", "regional"):
        df = dfs[layer]
        mask = dict(zip(ycols_all[layer], non_negative_mask(ycols_all[layer])))
        Yraw = load_layer(layer, clip=False)[1]
        Ycl = load_layer(layer)[1]
        delta = dict(zip(modelled[layer], np.abs(Ycl - Yraw).max(axis=0)))
        for c in ycols_all[layer]:
            n = int((df[c] < 0).sum())
            if n:
                rows.append(dict(layer=layer, column=c, n_negative_rows=n, min_value=float(df[c].min()),
                                 must_be_nonneg=bool(mask[c]), modelled=c in modelled[layer],
                                 max_change_from_train_clip=float(delta.get(c, np.nan))))
    q2 = pd.DataFrame(rows)
    q2.to_csv(DATA / "09_q2_negative_targets.csv", index=False)
    J["q2_cells_changed_by_train_clip"] = {
        "system": int((Ys_clip != Ys_raw).sum()), "regional": int((Yr_clip != Yr_raw).sum())}

    # ---------------------------------------------------------------- Q3
    q3 = []
    for layer in ("system", "regional"):
        cols = ycols_all[layer]
        m = non_negative_mask(cols)
        # consistency of the two copies of the rule (constraints vs predict.py)
        probe = pd.Series(-1.0, index=cols)
        clipped_by_predict = (clip_physical_bounds(probe) == 0).to_numpy()
        J[f"q3_mask_matches_clip_physical_bounds_{layer}"] = bool(np.array_equal(clipped_by_predict, m))
        for c, keep in zip(cols, m):
            if keep:
                continue
            reason = ("storage net generation" if _is_storage_gen(c) else
                      "'_negative' cost" if _is_negative_cost(c) else "no cap_/tran_/gen_/cost_ prefix")
            q3.append(dict(layer=layer, column=c, reason=reason, modelled=c in modelled[layer]))
    q3 = pd.DataFrame(q3)
    q3.to_csv(DATA / "09_q3_exempt.csv", index=False)

    # ---------------------------------------------------------------- Q4
    q4 = {}
    for c in ["cap_distpv", "gen_distpv"]:
        s = df_sys[c]
        q4[c] = dict(n_unique=int(s.nunique()), min=float(s.min()), max=float(s.max()),
                     modelled=c in sys_cols, dropped_constant=c in sys_const,
                     mean_by_x_Dem={int(k): float(v) for k, v in df_sys.groupby("x_Dem")[c].mean().items()})
    reg_distpv = [c for c in ycols_all["regional"] if "distpv" in c]
    q4["regional_distpv"] = {c: dict(n_unique=int(df_reg[c].nunique()), modelled=c in reg_cols,
                                     value=float(df_reg[c].iloc[0]) if df_reg[c].nunique() == 1 else None)
                             for c in reg_distpv}
    q4["regional_cap_distpv_sum"] = float(df_reg[[c for c in reg_distpv if c.startswith("cap_")]].iloc[0].sum())
    q4["dgen_formula_values"] = {k: dgen_distpv_cap_mw(k) for k in (0.0, 0.5, 1.0, 1.5, 2.0)}
    q4["system_constants"] = sys_const
    q4["regional_constants"] = reg_const
    J["q4"] = q4

    # ---------------------------------------------------------------- Q5
    comps_mod = cost_component_cols(sys_cols)
    comps_all = cost_component_cols(ycols_all["system"])
    tot = df_sys["cost_total"].to_numpy()
    s_all = df_sys[comps_all].sum(axis=1).to_numpy()
    J["q5"] = dict(
        components_modelled=comps_mod, components_all=comps_all,
        components_dropped_as_constant=[c for c in comps_all if c not in comps_mod],
        cost_cols_not_component=[c for c in ycols_all["system"] if c.startswith("cost_") and c not in comps_all],
        raw_identity_max_abs=float(np.abs(tot - s_all).max()),
        raw_identity_max_rel=float((np.abs(tot - s_all) / np.abs(tot)).max()),
    )
    jt = sys_cols.index("cost_total")
    ci = [sys_cols.index(c) for c in comps_mod]
    s_clip = Ys_clip[:, ci].sum(axis=1)
    J["q5"]["clipped_targets_identity_max_abs"] = float(np.abs(Ys_clip[:, jt] - s_clip).max())

    # ---------------------------------------------------------------- OOF
    P0s, P0r, P1s, P1r = get_oof(Xs, Ys_raw, Ys_clip, Xr, Yr_raw, Yr_clip)
    J["oof_matches_stored_pipeline"] = {
        "system_max_abs_diff": float(np.abs(P1s - stored_oof("system", "rf", Ys_clip)).max()),
        "regional_max_abs_diff": float(np.abs(P1r - stored_oof("regional", "rf", Yr_clip)).max()),
        "system_max_rel_diff_vs_scale": float((np.abs(P1s - stored_oof("system", "rf", Ys_clip)).max(axis=0)
                                               / np.maximum(np.abs(Ys_raw).max(axis=0), 1e-12)).max()),
    }

    # ---------------------------------------------------------------- Q5c
    def rmse_b(p, y):
        return float(np.sqrt(np.mean((p - y) ** 2)) / 1e9)
    y = Ys_raw[:, jt]
    out5 = {}
    for name, P in (("trained raw, no clip (P0)", P0s), ("trained clipped + prediction clip (P1)", clip_np(P1s, sys_cols))):
        direct = P[:, jt]
        summed = P[:, ci].sum(axis=1)
        out5[name] = dict(r2_direct=float(per_output_r2(y[:, None], direct[:, None])[0]),
                          r2_sum=float(per_output_r2(y[:, None], summed[:, None])[0]),
                          rmse_direct_B=rmse_b(direct, y), rmse_sum_B=rmse_b(summed, y),
                          mae_direct_B=float(np.abs(direct - y).mean() / 1e9),
                          mae_sum_B=float(np.abs(summed - y).mean() / 1e9))
    J["q5c"] = out5
    J["q5_cost_total_mean_B"] = float(y.mean() / 1e9)

    # ---------------------------------------------------------------- Q6a reproduce paper numbers (item-4 way)
    C_s = clip_np(stored_oof("system", "rf", Ys_clip), sys_cols)
    C_r = clip_np(stored_oof("regional", "rf", Yr_clip), reg_cols)
    E_s = C_s.copy()
    E_s[:, jt] = E_s[:, ci].sum(axis=1)
    F_r = enforce_additivity_matrix_item4(C_r, reg_cols, reg_const, E_s, sys_cols)
    B_neg = neg_stats(P0s, sys_cols)
    C_cost = cost_stats(C_s, sys_cols)
    C_add = add_stats(C_r, reg_cols, reg_const, C_s, sys_cols)
    F_add = add_stats(F_r, reg_cols, reg_const, E_s, sys_cols)
    J["q6_paper_numbers"] = dict(
        neg=B_neg, cost=C_cost, add_before=C_add, add_after_item4=F_add,
        add_reduction_pct=100 * (1 - F_add["add_viol"] / C_add["add_viol"]),
    )

    # ---------------------------------------------------------------- Q6b cumulative ablation with the real code
    configs = [
        ("none", P0s, P0r, Stage2InferenceConfig(False, False, False, False)),
        ("+1", P1s, P1r, Stage2InferenceConfig(True, False, False, False)),
        ("+1,2", P1s, P1r, Stage2InferenceConfig(True, True, False, False)),
        ("+1,2,3", P1s, P1r, Stage2InferenceConfig(True, True, True, False)),
        ("all four", P1s, P1r, Stage2InferenceConfig(True, True, True, True)),
    ]
    abl, outs, per_out = [], {}, []
    for name, Ps, Pr, cfg in configs:
        S, R, extra = run_stack(Ps, Pr, sys_cols, reg_cols, x_dem, cfg)
        outs[name] = (S, R)
        ss, r2s = score(Ys_raw, S, sys_cols)
        rs, r2r = score(Yr_raw, R, reg_cols)
        row = dict(config=name, sys_r2_mean=ss["mean"], sys_r2_median=ss["median"],
                   reg_r2_mean=rs["mean"], reg_r2_median=rs["median"], cost_total_r2=r2s["cost_total"])
        ns, nr = neg_stats(S, sys_cols), neg_stats(R, reg_cols)
        row.update(sys_neg_cells=ns["neg_cells"], sys_neg_pct=ns["neg_pct"], reg_neg_cells=nr["neg_cells"])
        row.update({k: v for k, v in cost_stats(S, sys_cols).items()})
        a = add_stats(R, reg_cols, reg_const, S, sys_cols)
        row.update(add_viol=a["add_viol"], add_pairs_finite=a["add_pairs_finite"], add_viol_pct=a["add_viol_pct"],
                   add_T0_S_nonzero=a["add_T0_S_nonzero"], regional_cols_appended=";".join(extra))
        abl.append(row)
        for c in sys_cols:
            per_out.append(dict(config=name, layer="system", output=c, r2=r2s[c]))
        for c in reg_cols:
            per_out.append(dict(config=name, layer="regional", output=c, r2=r2r[c]))
        print(f"  {name}: sys {ss['mean']:.4f} reg {rs['mean']:.4f} cost {r2s['cost_total']:.4f} "
              f"add viol {a['add_viol']}/{a['add_pairs_finite']}", flush=True)
    abl = pd.DataFrame(abl)
    abl.to_csv(DATA / "09_ablation.csv", index=False)
    po = pd.DataFrame(per_out).pivot_table(index=["layer", "output"], columns="config", values="r2")
    po.to_csv(DATA / "09_ablation_per_output.csv")
    order = [c[0] for c in configs]
    steps = []
    for a, b in zip(order[:-1], order[1:]):
        d = (po[b] - po[a]).abs()
        steps.append(dict(step=f"{a} -> {b}", max_abs_output_r2_change=float(d.max()),
                          output=str(d.idxmax()), n_outputs_changed_gt_0_005=int((d > 0.005).sum())))
    J["q6_steps"] = steps

    # ---------------------------------------------------------------- Q1 + Q7: additivity in the full stack
    # Code grouping (what enforce_additivity actually rescales)
    groups_code = {}
    for c in reg_cols:
        sp = _split_regional(c)
        if sp and sp[0] in sys_cols:
            groups_code.setdefault(sp[0], []).append(c)
    groups_paper = regional_groups(reg_cols, reg_const, sys_cols)
    J["q1_quantities_paper_def"] = len(groups_paper)
    J["q1_quantities_code_rescales"] = len(groups_code)
    J["q1_in_paper_not_code"] = sorted(set(groups_paper) - set(groups_code))
    J["q1_in_code_not_paper"] = sorted(set(groups_code) - set(groups_paper))

    S_all, R_all = outs["all four"]
    # The stack's intermediate: regional rescaled to the final system row,
    # before the regional clip (apply_constraints runs additivity, then clip).
    R_resc = np.empty_like(P1r)
    for i in range(P1r.shape[0]):
        r = apply_constraints(pd.Series(P1r[i], index=reg_cols), overall_pred=pd.Series(S_all[i], index=sys_cols),
                              config=Stage2InferenceConfig(False, True, False, False))
        R_resc[i] = r.reindex(reg_cols).to_numpy()

    changed = R_resc != R_all
    J["q1_clip_after_rescale"] = dict(
        cells_changed=int(changed.sum()), runs=int(changed.any(axis=1).sum()),
        columns=sorted({reg_cols[j] for j in np.where(changed.any(axis=0))[0]}),
        max_abs_change=float(np.abs(R_resc - R_all).max()))
    rel_fin, names, S_fin, T = add_rel(R_all, reg_cols, reg_const, S_all, sys_cols)
    rel_pre, _, S_pre, _ = add_rel(R_resc, reg_cols, reg_const, S_all, sys_cols)
    cur = np.column_stack([P1r[:, [reg_cols.index(c) for c in groups_code[n]]].sum(axis=1)
                           if n in groups_code else np.full(P1r.shape[0], np.nan) for n in names])
    viol = np.where(np.isfinite(rel_fin), rel_fin > TOL, False)
    T0 = (T == 0)
    cause = np.full(viol.shape, "", dtype=object)
    for k, n in enumerate(names):
        for i in range(viol.shape[0]):
            if not viol[i, k]:
                continue
            if n not in groups_code:
                cause[i, k] = "quantity not matched by enforce_additivity regex"
            elif cur[i, k] <= 0 or T[i, k] <= 0:
                cause[i, k] = "rescale skipped (regional sum or system value <= 0)"
            elif rel_pre[i, k] > TOL:
                cause[i, k] = "dropped-constant regional columns not rescaled"
            else:
                cause[i, k] = "clipping after rescale"
    cnt = pd.Series(cause[viol]).value_counts()
    J["q1_final"] = dict(
        pairs_all=int(rel_fin.size), pairs_finite=int(np.isfinite(rel_fin).sum()),
        pairs_T_zero=int(T0.sum()), pairs_T_zero_S_nonzero=int((T0 & (np.abs(S_fin) > 1e-6)).sum()),
        viol=int(viol.sum()), viol_pct_of_finite=100 * float(viol.sum() / np.isfinite(rel_fin).sum()),
        causes={k: int(v) for k, v in cnt.items()},
    )
    by_q = []
    for k, n in enumerate(names):
        v = viol[:, k]
        if v.any() or (n in groups_code and ((cur[:, k] <= 0) | (T[:, k] <= 0)).any()):
            skip = ((cur[:, k] <= 0) | (T[:, k] <= 0)) if n in groups_code else np.zeros(len(v), bool)
            by_q.append(dict(quantity=n, rescaled_by_code=n in groups_code, viol_pairs=int(v.sum()),
                             skipped_pairs=int(skip.sum()),
                             skip_regional_sum_le0=int((cur[:, k] <= 0).sum()) if n in groups_code else 0,
                             skip_system_le0=int((T[:, k] <= 0).sum()),
                             system_value_zero=int(T0[:, k].sum()),
                             causes="; ".join(f"{c}: {m}" for c, m in
                                              pd.Series(cause[v, k]).value_counts().items())))
    # Q7 breakdown of skipped pairs (code grouping only)
    in_code = np.array([n in groups_code for n in names])
    skip = in_code[None, :] & ((cur <= 0) | (T <= 0))
    tiny = 1e-6
    both0 = skip & (np.abs(T) < tiny) & (np.abs(S_fin) < tiny)
    t0_s = skip & (np.abs(T) < tiny) & (np.abs(S_fin) >= tiny)
    fin_skip = skip & ~(np.abs(T) < tiny)
    negdef = np.array([_is_storage_gen(n) or _is_negative_cost(n) for n in names])
    J["q7_breakdown"] = dict(
        skipped=int(skip.sum()),
        skipped_negative_by_definition_quantities=int((skip & negdef[None, :]).sum()),
        skipped_both_zero=int(both0.sum()),
        skipped_system_zero_regional_nonzero=int(t0_s.sum()),
        skipped_system_nonzero=int(fin_skip.sum()),
        skipped_system_nonzero_viol=int((fin_skip & viol).sum()),
        t0_s_abs_median=float(np.median(np.abs(S_fin[t0_s]))) if t0_s.any() else 0.0,
        t0_s_abs_max=float(np.abs(S_fin[t0_s]).max()) if t0_s.any() else 0.0,
        t0_s_by_quantity={n: dict(pairs=int(t0_s[:, k].sum()),
                                  median_abs=float(np.median(np.abs(S_fin[t0_s[:, k], k]))),
                                  max_abs=float(np.abs(S_fin[t0_s[:, k], k]).max()))
                          for k, n in enumerate(names) if t0_s[:, k].any()},
    )
    q7 = pd.DataFrame(by_q).sort_values(["skipped_pairs", "viol_pairs"], ascending=False)
    q7.to_csv(DATA / "09_q1_q7_by_quantity.csv", index=False)
    J["q7_total_skipped_pairs"] = int(q7.skipped_pairs.sum())

    # Raw-data additivity: does ReEDS itself satisfy sum_r = system?
    rel_raw, names_raw, S_raw, T_raw = add_rel(Yr_raw, reg_cols, reg_const, Ys_raw, sys_cols)
    raw = []
    for k, n in enumerate(names_raw):
        gap = np.abs(S_raw[:, k] - T_raw[:, k])
        raw.append(dict(quantity=n, max_abs_gap=float(gap.max()),
                        max_rel_gap=float(np.nanmax(np.where(T_raw[:, k] != 0, gap / np.abs(T_raw[:, k]), 0)))))
    raw = pd.DataFrame(raw).sort_values("max_rel_gap", ascending=False)
    raw.to_csv(DATA / "09_raw_additivity.csv", index=False)
    J["raw_additivity_quantities_gap_gt_1e-6_rel"] = raw[raw.max_rel_gap > 1e-6].to_dict("records")

    write_json(J, "09_constraints_check.json")

    # ---------------------------------------------------------------- short md dump
    L = ["## 9. Constraint-layer check (tables generated by 09_constraints_check.py)\n",
         "### Q2 negative values in the 486 training runs\n", md_table(q2, "{:.6g}"),
         "\n### Q3 exempt columns\n", md_table(q3),
         "\n### Q6 cumulative ablation (real apply_constraints)\n", md_table(abl, "{:.4f}"),
         "\n### Q6 per-step max change in any output R2\n", md_table(pd.DataFrame(steps), "{:.4f}"),
         "\n### Q1/Q7 additivity by quantity (all four rules)\n", md_table(q7, "{:.4f}"),
         "\n### Raw ReEDS additivity\n", md_table(raw, "{:.3g}")]
    (HERE / "results_09.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote results_09.md and data/09_constraints_check.json")


if __name__ == "__main__":
    main()
