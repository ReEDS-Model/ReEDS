"""Shared helpers for the PESGM analysis scripts (analysis/pesgm/).

Everything here reuses the Stage 2 surrogate code under
postprocessing/reedssurr/Stage2/code (data loading, train-target clipping,
constraint helpers) so the numbers line up with the draft. Run with the
``reeds2`` conda env (sklearn 1.2.2 / xgboost 3.2.0 / ngboost 0.5.8), which is
the env the stored artefacts were trained in:

    C:/Users/ychen10/AppData/Local/anaconda3/envs/reeds2/python.exe <script>.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import r2_score
from sklearn.model_selection import KFold
from sklearn.preprocessing import StandardScaler

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
STAGE2 = REPO / "postprocessing" / "reedssurr" / "Stage2"
CODE = STAGE2 / "code"
INPUTS = STAGE2 / "inputs"
OUTPUTS = STAGE2 / "outputs"
FIGS = HERE / "figs"
DATA = HERE / "data"
FIGS.mkdir(exist_ok=True)
DATA.mkdir(exist_ok=True)

if str(CODE) not in sys.path:
    sys.path.insert(0, str(CODE))

# Pipeline modules (imported for their exact behaviour, not re-implemented).
from surrogate_ml_models import Config, load_data, get_model, compute_oof_predictions  # noqa: E402
from surrogate_constraints import (  # noqa: E402
    non_negative_mask, clip_train_targets, cost_component_cols,
)
from surrogate_paths import resolve_models_dir  # noqa: E402

SEED = 42          # same as Config.random_state / KFold seed in the pipeline
N_FOLDS = 10
X_COLS = ["x_Batt", "x_Dem", "x_Fuel", "x_Pol", "x_REcost", "x_Siting"]
DIAL_LABELS = {"x_Batt": "Batt", "x_Dem": "Dem", "x_Fuel": "Fuel",
               "x_Pol": "Pol", "x_REcost": "REcost", "x_Siting": "Siting"}
LEVEL_NAMES = {
    "x_Batt": {0: "Lo", 1: "Md", 2: "Hi"}, "x_Dem": {0: "Lo", 1: "Md", 2: "Hi"},
    "x_Fuel": {0: "Lo", 1: "Md", 2: "Hi"}, "x_REcost": {0: "Lo", 1: "Md", 2: "Hi"},
    "x_Siting": {0: "Open", 1: "Ref", 2: "Lim"}, "x_Pol": {0: "IRA", 1: "OBBBA"},
}

# Headline outputs requested for the paper (system layer, merged column names).
HEADLINE = [
    "cost_total", "tran_total",
    "cap_wind-ons", "gen_wind-ons", "cap_upv", "gen_upv",
    "cap_gas-cc", "gen_gas-cc", "cap_battery_li", "gen_battery_li",
    "cap_gas-ct", "gen_gas-ct", "cap_nuclear", "gen_nuclear",
]
HEADLINE8 = ["cost_total", "tran_total", "cap_wind-ons", "cap_upv",
             "cap_gas-cc", "cap_battery_li", "cap_gas-ct", "gen_gas-cc"]
PRETTY = {
    "cost_total": "Total cost", "tran_total": "Transmission",
    "cap_wind-ons": "Wind cap.", "gen_wind-ons": "Wind gen.",
    "cap_upv": "UPV cap.", "gen_upv": "UPV gen.",
    "cap_gas-cc": "Gas-CC cap.", "gen_gas-cc": "Gas-CC gen.",
    "cap_battery_li": "Battery cap.", "gen_battery_li": "Battery gen.",
    "cap_gas-ct": "Gas-CT cap.", "gen_gas-ct": "Gas-CT gen.",
    "cap_nuclear": "Nuclear cap.", "gen_nuclear": "Nuclear gen.",
}

LAYERS = {
    "system": dict(data=INPUTS / "overall_ml_numeric_merged.csv", out=OUTPUTS / "overall"),
    "regional": dict(data=INPUTS / "regional_ml_numeric_merged.csv", out=OUTPUTS / "regional"),
    "system_premerge": dict(data=INPUTS / "overall_ml_numeric.csv", out=OUTPUTS / "overall_premerge"),
    "regional_premerge": dict(data=INPUTS / "regional_ml_numeric.csv", out=OUTPUTS / "regional_premerge"),
}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def load_layer(layer: str, clip: bool = True):
    """Return (X, Y, x_cols, y_cols, case_names, constants) exactly as the
    pipeline's ``load_data`` does (constant-column drop + train-target clip).
    With ``clip=False`` the raw (unclipped) targets are returned instead."""
    cfg = Config(data_path=str(LAYERS[layer]["data"]), output_dir=str(LAYERS[layer]["out"]))
    X, Y, x_cols, y_cols, case_names, constants = load_data(cfg)
    if not clip:
        df = pd.read_csv(cfg.data_path)
        Y = df[y_cols].values.astype(np.float64)
    return X, Y, x_cols, y_cols, case_names, constants


def load_artifact(layer: str, model: str) -> dict:
    import pickle
    p = resolve_models_dir(LAYERS[layer]["out"]) / f"{model}.joblib"
    with open(p, "rb") as f:
        return pickle.load(f)


def stored_oof(layer: str, model: str, Y: np.ndarray) -> np.ndarray:
    """OOF predictions reconstructed from the artefact's stored residuals."""
    art = load_artifact(layer, model)
    return Y - np.asarray(art["oof_residuals"], dtype=np.float64)


def kfold(n: int, seed: int = SEED, n_folds: int = N_FOLDS):
    return KFold(n_splits=n_folds, shuffle=True, random_state=seed).split(np.zeros(n))


# ---------------------------------------------------------------------------
# Random forest, per-output, identical to the pipeline's RF
# ---------------------------------------------------------------------------
def rf_estimator(seed: int = SEED, n_jobs: int = 1) -> RandomForestRegressor:
    """Same hyperparameters as get_model('rf') in surrogate_ml_models.py.
    MultiOutputRegressor clones this per output, so fitting one forest per
    output with the same seed reproduces the pipeline exactly."""
    return RandomForestRegressor(n_estimators=200, max_depth=None, min_samples_leaf=2,
                                 random_state=seed, n_jobs=n_jobs)


def _fit_one(X_tr, y_tr, X_te, seed, return_trees):
    m = rf_estimator(seed).fit(X_tr, y_tr)
    pred = m.predict(X_te)
    if return_trees:
        trees = np.stack([t.predict(X_te) for t in m.estimators_], axis=0)  # (n_trees, n_te)
        return pred, trees
    return pred, None


def _run_tasks(tasks, n_jobs=-1):
    """tasks: list of (X_tr_s, y_tr, X_te_s, seed, return_trees). Process pool
    (loky) over ALL tasks at once; sklearn's RF fit holds the GIL for most of
    its Python-level bookkeeping, so threads do not help here."""
    return Parallel(n_jobs=n_jobs, batch_size="auto")(delayed(_fit_one)(*t) for t in tasks)


def rf_fit_predict(X_tr, Y_tr, X_te, seed: int = SEED, return_trees: bool = False,
                   n_jobs: int = -1):
    """Fit one RF per output on (X_tr, Y_tr) and predict X_te.
    Features are standardised on the training set like the pipeline.
    Returns pred (n_te, n_out) and optionally trees (n_trees, n_te, n_out)."""
    sx = StandardScaler().fit(X_tr)
    X_tr_s, X_te_s = sx.transform(X_tr), sx.transform(X_te)
    res = _run_tasks([(X_tr_s, Y_tr[:, j], X_te_s, seed, return_trees) for j in range(Y_tr.shape[1])],
                     n_jobs=n_jobs)
    pred = np.column_stack([r[0] for r in res])
    trees = np.stack([r[1] for r in res], axis=2) if return_trees else None
    return pred, trees


def rf_oof(X, Y, seed: int = SEED, fold_seed: int = SEED, n_folds: int = N_FOLDS,
           return_trees: bool = False):
    """10-fold OOF predictions with the pipeline's KFold(shuffle, seed).
    All fold x output forests are dispatched to the process pool in one call."""
    n, p = Y.shape
    oof = np.zeros_like(Y)
    trees = np.zeros((200, n, p)) if return_trees else None
    fold_id = np.zeros(n, dtype=int)
    tasks, meta = [], []
    for k, (tr, te) in enumerate(kfold(n, fold_seed, n_folds)):
        fold_id[te] = k
        sx = StandardScaler().fit(X[tr])
        X_tr_s, X_te_s = sx.transform(X[tr]), sx.transform(X[te])
        for j in range(p):
            tasks.append((X_tr_s, Y[tr, j], X_te_s, seed, return_trees))
            meta.append((te, j))
    res = _run_tasks(tasks)
    for (te, j), (pred, tr_) in zip(meta, res):
        oof[te, j] = pred
        if return_trees:
            trees[:, te, j] = tr_
    return oof, fold_id, trees


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def per_output_r2(Y, P) -> np.ndarray:
    return np.array([r2_score(Y[:, j], P[:, j]) for j in range(Y.shape[1])])


def r2_summary(r2: np.ndarray) -> dict:
    return dict(mean=float(np.mean(r2)), median=float(np.median(r2)),
                n_ge_0_9=int(np.sum(r2 >= 0.9)), n_ge_0_95=int(np.sum(r2 >= 0.95)),
                n=int(len(r2)))


def parse_regional(col: str):
    """('cap_upv', 'p61') for 'cap_upv_p61'; ('tran', 'corridor') for tran_*."""
    import re
    if col.startswith("tran_"):
        return "tran", "corridor"
    m = re.search(r"_(p\d+)$", col)
    if m:
        return col[: m.start()], m.group(1)
    return col, None


def regional_groups(reg_cols, reg_constants, sys_cols):
    """{system col: (list of modelled regional cols, sum of dropped-constant
    regional cols)} for every quantity present in both layers. The pipeline
    drops zero-variance regional columns before fitting, so their constant
    value has to be added back when regional predictions are summed."""
    groups = {}
    for c in list(reg_cols) + list(reg_constants):
        parent, region = parse_regional(c)
        if region is None:
            continue
        if parent == "tran":
            parent = "tran_total"
        if parent not in sys_cols:
            continue
        cols, const = groups.get(parent, ([], 0.0))
        if c in reg_constants:
            const += float(reg_constants[c])
        else:
            cols.append(c)
        groups[parent] = (cols, const)
    return {k: v for k, v in groups.items() if v[0]}


def category(col: str) -> str:
    return col.split("_")[0] if col.split("_")[0] in ("cap", "gen", "tran", "cost") else "misc"


# ---------------------------------------------------------------------------
# Figure style (IEEE single column)
# ---------------------------------------------------------------------------
# Categorical palette: the dataviz skill's validated reference palette
# (adjacent-pair CVD dE >= 8, normal-vision dE >= 15). Fixed order.
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
GRAY = "#8a8985"
INK = "#0b0b0b"


def set_style():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "Liberation Sans", "DejaVu Sans"],
        "font.size": 8, "axes.labelsize": 8, "axes.titlesize": 8,
        "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
        "axes.linewidth": 0.6, "xtick.major.width": 0.6, "ytick.major.width": 0.6,
        "xtick.major.size": 2.5, "ytick.major.size": 2.5,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": "#52514e", "xtick.color": "#52514e", "ytick.color": "#52514e",
        "axes.labelcolor": INK, "text.color": INK,
        "axes.grid": True, "grid.color": "#e3e2dd", "grid.linewidth": 0.4,
        "axes.axisbelow": True,
        "legend.frameon": False, "legend.handlelength": 1.2,
        "lines.linewidth": 1.2, "lines.markersize": 3.5,
        "pdf.fonttype": 42, "ps.fonttype": 42,
        "figure.dpi": 100, "savefig.dpi": 300,
        "axes.prop_cycle": matplotlib.cycler(color=PALETTE),
    })
    return plt


def new_fig(height: float = 2.4, width: float = 3.5, **kw):
    plt = set_style()
    fig, ax = plt.subplots(figsize=(width, height), **kw)
    return fig, ax


def save_fig(fig, name: str):
    """Save <name>.pdf and <name>.png (300 dpi) under analysis/pesgm/figs."""
    fig.tight_layout(pad=0.3)
    for ext in ("pdf", "png"):
        fig.savefig(FIGS / f"{name}.{ext}", bbox_inches="tight", pad_inches=0.02)
    import matplotlib.pyplot as plt
    plt.close(fig)
    print(f"  wrote figs/{name}.pdf and .png")


def write_json(obj, name: str):
    (DATA / name).write_text(json.dumps(obj, indent=2, default=_json_default))


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(str(type(o)))


class Timer:
    def __init__(self):
        self.t = time.perf_counter()

    def lap(self) -> float:
        now = time.perf_counter()
        dt = now - self.t
        self.t = now
        return dt


def md_table(df: pd.DataFrame, floatfmt: str = "{:.3f}") -> str:
    """Minimal GitHub-markdown table (tabulate is not installed in reeds2)."""
    cols = list(df.columns)

    def fmt(v):
        if isinstance(v, (float, np.floating)):
            return "" if np.isnan(v) else floatfmt.format(v)
        return str(v)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(fmt(row[c]) for c in cols) + " |")
    return "\n".join(lines)
