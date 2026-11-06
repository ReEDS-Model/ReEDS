"""Item 13 - numbers behind claims_check.md (no model fitting).

Reads the training CSVs, the stored OOF residuals cached by 10_after_fix.py
(data/10_stored_residuals.npz), the constrained RF OOF it wrote
(data/after_fix/*/oof_rf.npz) and the 10_* tables, and prints / saves every
number that claims_check.md cites. Writes data/13_claims_numbers.json.
"""
from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd

from pesgm_common import DATA, LAYERS, load_layer, non_negative_mask, per_output_r2, regional_groups
from surrogate_constraints import transmission_floors

J = {}
dfs = pd.read_csv(LAYERS["system"]["data"])
dfr = pd.read_csv(LAYERS["regional"]["data"])
Xs, Ys_raw, x_cols, sc, _, sconst = load_layer("system", clip=False)
_, Ys_clip, _, _, _, _ = load_layer("system")
_, Yr_raw, _, rc, _, rconst = load_layer("regional", clip=False)
_, Yr_clip, _, _, _, _ = load_layer("regional")
res = np.load(DATA / "10_stored_residuals.npz")
oof = {(l, m): (Ys_clip if l == "system" else Yr_clip) - res[f"{l}_{m}"].astype(float)
       for l in ("system", "regional") for m in ("rf", "nn", "ridge")}

# ---------------- design / data
J["x_levels"] = {c: sorted(dfs[c].unique().tolist()) for c in x_cols}
J["n_runs"] = len(dfs)
J["n_system_modelled"], J["n_regional_modelled"] = len(sc), len(rc)
J["system_constants"] = sconst
J["n_regional_constants"] = len(rconst)
J["n_regional_constants_nonzero"] = sum(1 for v in rconst.values() if v != 0)
J["system_by_family"] = pd.Series([c.split("_")[0] for c in sc]).value_counts().to_dict()
J["regional_by_family"] = pd.Series([c.split("_")[0] for c in rc]).value_counts().to_dict()
J["system_tran_cols"] = [c for c in sc if c.startswith("tran_")]
J["regional_tran_cols_all"] = [c for c in dfr.columns if c.startswith("tran_")]
J["regional_tran_modelled"] = [c for c in rc if c.startswith("tran_")]
J["n_cost_components"] = len([c for c in sc if c.startswith(("cost_inv_", "cost_op_"))])
J["runtime_min"] = dict(zip(["min", "median", "mean", "max"],
                            np.round(np.percentile(dfs.runtime_seconds / 60, [0, 50]).tolist()
                                     + [float((dfs.runtime_seconds / 60).mean()),
                                        float((dfs.runtime_seconds / 60).max())], 1)))
J["regions"] = sorted({m.group(1) for c in dfr.columns for m in [re.search(r"_(p\d+)$", c)] if m})

# ---------------- raw RF R2 per output
r2s = pd.Series(per_output_r2(Ys_raw, oof[("system", "rf")]), index=sc)
r2r = pd.Series(per_output_r2(Yr_raw, oof[("regional", "rf")]), index=rc)
heads = ["cost_total", "tran_total", "tran_AC_total"] + [f"{k}_{t}" for t in
         ("wind-ons", "upv", "gas-cc", "battery_li") for k in ("cap", "gen")]
J["headline_r2"] = {c: round(float(r2s[c]), 4) for c in heads}
J["cost_op_r2"] = {c: round(float(r2s[c]), 4) for c in sc if c.startswith("cost_op_")}
J["cost_inv_r2"] = {c: round(float(r2s[c]), 4) for c in sc if c.startswith("cost_inv_")}

# ---------------- cap_nuclear
y = Ys_raw[:, sc.index("cap_nuclear")]
p = oof[("system", "rf")][:, sc.index("cap_nuclear")]
J["cap_nuclear"] = dict(r2=float(r2s["cap_nuclear"]), mean_MW=float(y.mean()), std_MW=float(y.std()),
                        min_MW=float(y.min()), max_MW=float(y.max()), n_unique=int(np.unique(y).size),
                        mae_MW=float(np.abs(p - y).mean()), max_abs_err_MW=float(np.abs(p - y).max()),
                        mae_pct_of_mean=float(100 * np.abs(p - y).mean() / y.mean()))

# ---------------- activation frequency (system, all columns incl. constants)
ycols_all = [c for c in dfs.columns if not c.startswith("x_") and c != "case_name"]
act = {c: float((dfs[c].abs() > 1e-6).mean()) for c in ycols_all}
J["activation_sparse"] = {c: round(act[c], 3) for c in ycols_all if re.search(
    r"h2|H2|smr|CCS|ccs|electrolyzer", c)}
J["n_system_outputs_active_lt_10pct"] = sorted(c for c in sc if act[c] < 0.10)

# ---------------- per-BA pattern (raw RF)
reg = pd.DataFrame({"r2": r2r})
reg["region"] = [re.search(r"_(p\d+)$", c).group(1) if re.search(r"_(p\d+)$", c) else None for c in reg.index]
reg["base"] = [re.sub(r"_p\d+$", "", c) for c in reg.index]
reg = reg[reg.region.notna()]
act_r = {c: float((dfr[c].abs() > 1e-6).mean()) for c in rc}
cv_r = {c: float(dfr[c].std() / abs(dfr[c].mean())) if dfr[c].mean() != 0 else np.inf for c in rc}
reg["act"] = [act_r[c] for c in reg.index]
reg["cv"] = [cv_r[c] for c in reg.index]
poor = reg[reg.r2 < 0.5]
J["perba_poor_cells"] = int(len(poor))
J["perba_poor_sparse_or_flat"] = int(((poor.act < 0.5) | (poor.cv < 0.05)).sum())
g = reg.groupby("base")
summ = pd.DataFrame({"n_regions": g.size(), "n_poor": g.apply(lambda d: int((d.r2 < 0.5).sum()))})
multi = summ[summ.n_regions >= 3]
J["perba_bases_in_3plus_regions"] = int(len(multi))
J["perba_bases_poor_everywhere"] = int((multi.n_poor == multi.n_regions).sum())
J["perba_bases_poor_nowhere"] = int((multi.n_poor == 0).sum())
J["perba_bases_mixed"] = sorted(multi[(multi.n_poor > 0) & (multi.n_poor < multi.n_regions)].index.tolist())
J["region_mean_r2"] = reg.groupby("region").r2.mean().round(3).to_dict()

# ---------------- remaining additivity violations: all skipped?
S_new = np.load(DATA / "after_fix" / "overall" / "oof_rf.npz")["oof"]
R_new = np.load(DATA / "after_fix" / "regional" / "oof_rf.npz")["oof"]
R_clip = oof[("regional", "rf")].copy()
m = non_negative_mask(rc)
R_clip[:, m] = np.maximum(R_clip[:, m], 0)
fl = transmission_floors(dfr)
for c, f in fl.items():
    if c in rc:
        R_clip[:, rc.index(c)] = np.maximum(R_clip[:, rc.index(c)], f)
n_viol = n_skipped = 0
for parent, (cols, const) in regional_groups(rc, rconst, sc).items():
    idx = [rc.index(c) for c in cols]
    s = R_new[:, idx].sum(1) + const
    t = S_new[:, sc.index(parent)]
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.abs(s - t) / np.abs(t)
    v = np.isfinite(rel) & (rel > 0.01)
    unchanged = np.all(np.isclose(R_new[:, idx], R_clip[:, idx], rtol=1e-9, atol=1e-6), axis=1)
    n_viol += int(v.sum())
    n_skipped += int((v & unchanged).sum())
J["remaining_violations"] = n_viol
J["remaining_violations_rescale_not_applied"] = n_skipped

# ---------------- below-bound counts / shortfall (stored OOF, before rules)
mpos = non_negative_mask(sc)
J["rf_stored_negative_cells_system"] = int((oof[("system", "rf")][:, mpos] < 0).sum())
J["rf_stored_most_negative"] = float(oof[("system", "rf")][:, mpos].min())
for mdl in ("rf", "nn", "ridge"):
    P = oof[("regional", mdl)]
    short = [float((fl[c] - P[:, rc.index(c)]).max()) for c in fl if c in rc]
    below = sum(int((P[:, rc.index(c)] < fl[c] * 0.99).sum()) for c in fl if c in rc)
    J[f"{mdl}_corridor_below_1pct"] = below
    J[f"{mdl}_corridor_max_shortfall_MW"] = round(max(short), 1)
J["tran_total_floor"] = round(sum(fl.values()), 1)

# ---------------- merging (item 4): per-class outputs with R2 < 0 before merging
abl = pd.read_csv(DATA / "04_ablation_per_output.csv")
pc = abl[(abl.config == "A") & (abl.layer == "system")]
J["premerge_system_negative_r2"] = pc[pc.r2 < 0].sort_values("r2")[["output", "r2"]].round(3).values.tolist()

(DATA / "13_claims_numbers.json").write_text(json.dumps(J, indent=1, default=float))
print(json.dumps(J, indent=1, default=float))
