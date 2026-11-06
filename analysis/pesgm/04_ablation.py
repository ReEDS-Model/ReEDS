"""Item 4 - constraint and class-merging ablation (RF, 10-fold OOF, seed 42).

Configurations (cumulative):
  A  per-class outputs (no merging), no train clip, no constraints
  B  resource classes merged (the paper's output set), no clip, no constraints
  C  B + non-negativity (train-target clip + prediction clip)   [= stored pipeline OOF + clip]
  D  C + DistPV dgen override   (no effect in CV: cap_distpv is constant and dropped)
  E  D + cost decomposition     (cost_total := sum of predicted cost components; system only)
  F  E + regional->system additivity (regional predictions rescaled to the system prediction)

For every configuration and both layers: mean / median R-squared over the
modelled outputs, and three counts of unphysical predictions over the 486
held-out runs: negative values in columns that must be >= 0; (run, quantity)
pairs where the regional sum differs from the system prediction by more than
1 %; runs where the predicted cost_total differs from the sum of predicted
components by more than 1 %.

For configuration A the per-class predictions are also summed to the merged
quantities so that A and B can be compared on the same 66 / 308 outputs.

Writes data/04_ablation.csv, data/04_ablation_per_output.csv, results_04.md.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from pesgm_common import (
    DATA, HERE, load_layer, md_table, non_negative_mask, regional_groups,
    per_output_r2, r2_summary, rf_oof, stored_oof,
)

MERGE_RE = re.compile(r"^(?P<prefix>cap|gen)_(?P<tech>wind-ons|wind-ofs|upv)_\d+(?P<region>_p\d+)?$")


def merge_predictions(P, cols, constants, target_cols):
    """Sum per-class columns of P (plus the per-class columns the pipeline
    dropped as constants) into merged names; return an (n, len(target_cols))
    array aligned to target_cols."""
    df = pd.DataFrame(P, columns=cols)
    for c, v in constants.items():
        df[c] = float(v)
    groups = {}
    for c in df.columns:
        m = MERGE_RE.match(c)
        if m:
            groups.setdefault(f"{m.group('prefix')}_{m.group('tech')}{m.group('region') or ''}", []).append(c)
    out = pd.DataFrame(index=df.index)
    for c in df.columns:
        if not MERGE_RE.match(c):
            out[c] = df[c]
    for name, src in groups.items():
        out[name] = df[src].sum(axis=1)
    missing = [c for c in target_cols if c not in out.columns]
    assert not missing, f"merged targets missing: {missing[:5]}"
    return out.reindex(columns=target_cols).values


def count_negative(P, cols):
    mask = non_negative_mask(cols)
    neg = P[:, mask] < 0
    names = [c for c, m in zip(np.asarray(cols)[mask], neg.any(axis=0)) if m]
    return dict(neg_cells=int(neg.sum()), neg_cells_pct=100 * neg.mean(),
                neg_runs=int(neg.any(axis=1).sum()), neg_outputs=int(neg.any(axis=0).sum()),
                neg_output_names="; ".join(names[:8]) + (" ..." if len(names) > 8 else ""))


def cost_identity_violations(P, cols, tol=0.01):
    if "cost_total" not in cols:
        return dict(cost_viol_runs=np.nan, cost_viol_median_pct=np.nan)
    comps = [i for i, c in enumerate(cols) if c.startswith(("cost_inv_", "cost_op_"))]
    tot = P[:, cols.index("cost_total")]
    s = P[:, comps].sum(axis=1)
    rel = np.abs(s - tot) / np.abs(tot)
    return dict(cost_viol_runs=int((rel > tol).sum()), cost_viol_median_pct=100 * float(np.median(rel)))


def additivity_violations(P_reg, reg_cols, reg_const, P_sys, sys_cols, tol=0.01):
    groups = regional_groups(reg_cols, reg_const, sys_cols)
    rels = []
    for parent, (cols, const) in groups.items():
        s = P_reg[:, [reg_cols.index(c) for c in cols]].sum(axis=1) + const
        t = P_sys[:, sys_cols.index(parent)]
        with np.errstate(divide="ignore", invalid="ignore"):
            rel = np.abs(s - t) / np.abs(t)
        rels.append(rel)
    R = np.column_stack(rels)
    ok = np.isfinite(R)
    return dict(add_pairs=int(ok.sum()), add_viol_pairs=int((R[ok] > tol).sum()),
                add_viol_pct=100 * float((R[ok] > tol).mean()), add_median_pct=100 * float(np.median(R[ok])),
                n_quantities=len(groups))


def enforce_additivity_matrix(P_reg, reg_cols, reg_const, P_sys, sys_cols):
    """Row-wise version of surrogate_constraints.enforce_additivity (the
    constant regional columns are fixed, so the modelled columns are scaled
    to system prediction minus the constant part)."""
    out = P_reg.copy()
    for parent, (cols, const) in regional_groups(reg_cols, reg_const, sys_cols).items():
        idx = [reg_cols.index(c) for c in cols]
        cur = out[:, idx].sum(axis=1)
        tgt = P_sys[:, sys_cols.index(parent)] - const
        scale = np.where((cur > 0) & (tgt > 0), tgt / np.where(cur > 0, cur, 1.0), 1.0)
        out[:, idx] = out[:, idx] * scale[:, None]
    return out


def clip_pred(P, cols):
    out = P.copy()
    m = non_negative_mask(cols)
    out[:, m] = np.maximum(out[:, m], 0.0)
    return out


def main():
    res, per_rows = [], []
    # ---------------- load everything -----------------------------------
    Xs, Ys_raw, _, sys_cols, _, _ = load_layer("system", clip=False)
    _, Ys_clip, _, _, _, _ = load_layer("system")
    Xr, Yr_raw, _, reg_cols, _, reg_const = load_layer("regional", clip=False)
    _, Yr_clip, _, _, _, _ = load_layer("regional")
    _, Ysp_raw, _, sysp_cols, _, sysp_const = load_layer("system_premerge", clip=False)
    _, Yrp_raw, _, regp_cols, _, regp_const = load_layer("regional_premerge", clip=False)
    truth = {"system": Ys_raw, "regional": Yr_raw}
    cols = {"system": sys_cols, "regional": reg_cols}

    def record(cfg, layer, P, extra=None, note=""):
        r2 = per_output_r2(truth[layer], P)
        s = r2_summary(r2)
        row = dict(config=cfg, layer=layer, n_outputs=s["n"], r2_mean=s["mean"], r2_median=s["median"],
                   n_ge_0_9=s["n_ge_0_9"], note=note)
        row.update(count_negative(P, cols[layer]))
        if layer == "system":
            row.update(cost_identity_violations(P, cols[layer]))
        if extra:
            row.update(extra)
        res.append(row)
        for j, c in enumerate(cols[layer]):
            per_rows.append(dict(config=cfg, layer=layer, output=c, r2=r2[j]))
        print(f"  {cfg} {layer:8s} mean {s['mean']:.4f} median {s['median']:.4f} "
              f"neg cells {row['neg_cells']}", flush=True)

    # ---------------- A: per-class, unclipped ---------------------------------
    print("[A] per-class, unclipped (system premerge)")
    Psp, _, _ = rf_oof(Xs, Ysp_raw)
    s = r2_summary(per_output_r2(Ysp_raw, Psp))
    res.append(dict(config="A", layer="system", n_outputs=s["n"], r2_mean=s["mean"], r2_median=s["median"],
                    n_ge_0_9=s["n_ge_0_9"], note="scored on 86 per-class outputs",
                    **count_negative(Psp, sysp_cols), **cost_identity_violations(Psp, sysp_cols)))
    PA_sys = merge_predictions(Psp, sysp_cols, sysp_const, sys_cols)
    print("[A] per-class, unclipped (regional premerge)")
    Prp, _, _ = rf_oof(Xr, Yrp_raw)
    s = r2_summary(per_output_r2(Yrp_raw, Prp))
    res.append(dict(config="A", layer="regional", n_outputs=s["n"], r2_mean=s["mean"], r2_median=s["median"],
                    n_ge_0_9=s["n_ge_0_9"], note="scored on 382 per-class outputs",
                    **count_negative(Prp, regp_cols)))
    PA_reg = merge_predictions(Prp, regp_cols, regp_const, reg_cols)
    res[-1].update(additivity_violations(PA_reg, reg_cols, reg_const, PA_sys, sys_cols))
    record("A (summed to merged outputs)", "system", PA_sys, note="per-class predictions summed")
    record("A (summed to merged outputs)", "regional", PA_reg,
           extra=additivity_violations(PA_reg, reg_cols, reg_const, PA_sys, sys_cols), note="per-class predictions summed")

    # ---------------- B: merged, unclipped ------------------------------------
    print("[B] merged, unclipped")
    PB_sys, _, _ = rf_oof(Xs, Ys_raw)
    PB_reg, _, _ = rf_oof(Xr, Yr_raw)
    record("B", "system", PB_sys)
    record("B", "regional", PB_reg, extra=additivity_violations(PB_reg, reg_cols, reg_const, PB_sys, sys_cols))

    # ---------------- C: + non-negativity (train clip = stored pipeline OOF) --
    print("[C] + non-negativity")
    PC_sys = clip_pred(stored_oof("system", "rf", Ys_clip), sys_cols)
    PC_reg = clip_pred(stored_oof("regional", "rf", Yr_clip), reg_cols)
    # The pipeline's own R2 (against clipped targets) for reference
    draft_sys = r2_summary(per_output_r2(Ys_clip, stored_oof("system", "rf", Ys_clip)))
    draft_reg = r2_summary(per_output_r2(Yr_clip, stored_oof("regional", "rf", Yr_clip)))
    record("C", "system", PC_sys, note="train clip + predict clip")
    record("C", "regional", PC_reg, extra=additivity_violations(PC_reg, reg_cols, reg_const, PC_sys, sys_cols),
           note="train clip + predict clip")

    # ---------------- D: + DistPV dgen override (no-op in CV) -----------------
    record("D", "system", PC_sys, note="cap_distpv constant -> dropped; no CV effect")
    record("D", "regional", PC_reg, extra=additivity_violations(PC_reg, reg_cols, reg_const, PC_sys, sys_cols),
           note="no CV effect")

    # ---------------- E: + cost decomposition --------------------------------
    print("[E] + cost decomposition")
    PE_sys = PC_sys.copy()
    comps = [i for i, c in enumerate(sys_cols) if c.startswith(("cost_inv_", "cost_op_"))]
    PE_sys[:, sys_cols.index("cost_total")] = PE_sys[:, comps].sum(axis=1)
    record("E", "system", PE_sys, note="cost_total := sum(components)")
    record("E", "regional", PC_reg, extra=additivity_violations(PC_reg, reg_cols, reg_const, PE_sys, sys_cols),
           note="no regional cost_total")

    # ---------------- F: + additivity ----------------------------------------
    print("[F] + additivity")
    PF_reg = enforce_additivity_matrix(PC_reg, reg_cols, reg_const, PE_sys, sys_cols)
    record("F", "system", PE_sys, note="unchanged")
    record("F", "regional", PF_reg, extra=additivity_violations(PF_reg, reg_cols, reg_const, PE_sys, sys_cols),
           note="regional rescaled to system prediction")

    df = pd.DataFrame(res)
    df.to_csv(DATA / "04_ablation.csv", index=False)
    pd.DataFrame(per_rows).to_csv(DATA / "04_ablation_per_output.csv", index=False)

    # Direct cost_total vs derived: per-output R2 and MAE
    j = sys_cols.index("cost_total")
    y = Ys_raw[:, j]
    def mae_pct(p): return 100 * np.abs(p - y).mean() / np.abs(y).mean()
    r2_direct = per_output_r2(y[:, None], PC_sys[:, [j]])[0]
    r2_derived = per_output_r2(y[:, None], PE_sys[:, [j]])[0]

    # ------------------------------------------------------------------ text
    def row(cfg, layer):
        return df[(df.config == cfg) & (df.layer == layer)].iloc[0]

    A_s, A_r = row("A", "system"), row("A", "regional")
    As_s, As_r = row("A (summed to merged outputs)", "system"), row("A (summed to merged outputs)", "regional")
    B_s, B_r = row("B", "system"), row("B", "regional")
    C_s, C_r = row("C", "system"), row("C", "regional")
    E_s, E_r = row("E", "system"), row("E", "regional")
    F_r = row("F", "regional")
    L = ["## 4. Constraint and class-merging ablation (RF, 10-fold OOF, seed 42)\n"]
    L.append(f"Without merging, the RF scored on the {int(A_s.n_outputs)} per-class system outputs has mean / median "
             f"R-squared {A_s.r2_mean:.3f} / {A_s.r2_median:.3f} ({int(A_s.n_ge_0_9)} outputs >= 0.9), and on the "
             f"{int(A_r.n_outputs)} per-class regional outputs {A_r.r2_mean:.3f} / {A_r.r2_median:.3f} "
             f"({int(A_r.n_ge_0_9)} >= 0.9); these are the pre-merge numbers in the repo's *_premerge folders and "
             f"are not comparable to the merged numbers because the output sets differ.")
    L.append(f"Summing the per-class predictions to the merged quantities and scoring on the same "
             f"{int(B_s.n_outputs)} / {int(B_r.n_outputs)} outputs gives {As_s.r2_mean:.3f} / {As_s.r2_median:.3f} "
             f"(system) and {As_r.r2_mean:.3f} / {As_r.r2_median:.3f} (regional), versus "
             f"{B_s.r2_mean:.3f} / {B_s.r2_median:.3f} and {B_r.r2_mean:.3f} / {B_r.r2_median:.3f} when the merged "
             f"quantities are predicted directly, so merging changes the aggregate R-squared by "
             f"{B_s.r2_mean - As_s.r2_mean:+.3f} (system mean) and {B_r.r2_mean - As_r.r2_mean:+.3f} (regional mean).")
    L.append(f"Non-negativity: the unconstrained merged RF produces {int(B_s.neg_cells)} negative cells in "
             f"{int(B_s.neg_runs)} runs on the system layer ({B_s.neg_cells_pct:.2f} % of must-be-positive cells, "
             f"{int(B_s.neg_outputs)} output affected: {B_s.neg_output_names}) and {int(B_r.neg_cells)} cells in "
             f"{int(B_r.neg_runs)} runs on the regional layer ({B_r.neg_cells_pct:.2f} %, {int(B_r.neg_outputs)} outputs: "
             f"{B_r.neg_output_names}); the train clip plus prediction clip removes all of them "
             f"and moves the mean R-squared by {C_s.r2_mean - B_s.r2_mean:+.4f} (system) and "
             f"{C_r.r2_mean - B_r.r2_mean:+.4f} (regional).")
    L.append(f"Configuration C scored against the pipeline's clipped targets is the draft number: mean / median "
             f"{draft_sys['mean']:.3f} / {draft_sys['median']:.3f} system and {draft_reg['mean']:.3f} / "
             f"{draft_reg['median']:.3f} regional; against the raw targets it is {C_s.r2_mean:.3f} / "
             f"{C_s.r2_median:.3f} and {C_r.r2_mean:.3f} / {C_r.r2_median:.3f}.")
    L.append("The DistPV dgen override has no measurable effect in cross-validation because cap_distpv is constant "
             "across all 486 runs and is dropped before fitting; it only changes predictions at off-grid demand values.")
    L.append(f"Cost identity: the directly predicted cost_total differs from the sum of predicted components by more "
             f"than 1 % in {int(C_s.cost_viol_runs)} of 486 runs (median gap {C_s.cost_viol_median_pct:.2f} %); "
             f"deriving cost_total from the components removes the violation by construction and changes its "
             f"R-squared from {r2_direct:.4f} to {r2_derived:.4f} and its MAE from {mae_pct(PC_sys[:, j]):.2f} % to "
             f"{mae_pct(PE_sys[:, j]):.2f} % of the mean.")
    L.append(f"Additivity: before rescaling, the regional sums differ from the system prediction by more than 1 % in "
             f"{int(C_r.add_viol_pairs)} of {int(C_r.add_pairs)} (run, quantity) pairs ({C_r.add_viol_pct:.1f} %; "
             f"median gap {C_r.add_median_pct:.2f} %) across {int(C_r.n_quantities)} quantities present in both layers; "
             f"rescaling removes them and changes the regional mean / median R-squared from {E_r.r2_mean:.3f} / "
             f"{E_r.r2_median:.3f} to {F_r.r2_mean:.3f} / {F_r.r2_median:.3f} ({int(F_r.add_viol_pairs)} pairs remain "
             f"because the rescale skips quantities whose regional sum or system prediction is not positive). "
             f"Note the dashboard does not apply "
             f"this rescale, so deployed regional predictions carry the pre-rescale inconsistency.")
    L.append("\nAblation table:\n")
    show = df[["config", "layer", "n_outputs", "r2_mean", "r2_median", "n_ge_0_9", "neg_cells", "neg_runs",
               "add_viol_pairs", "add_pairs", "cost_viol_runs", "note"]]
    L.append(md_table(show))
    (HERE / "results_04.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote results_04.md")


if __name__ == "__main__":
    main()
