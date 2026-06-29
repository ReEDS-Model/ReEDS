"""
Active-learning experiment for the ReEDS surrogate model.

Compares **uncertainty-driven sample acquisition** against **random acquisition**
on the existing 486-case dataset, simulating a 'self-improving' workflow:
the surrogate identifies the most uncertain candidate designs, those would be
sent to the slow ReEDS solver, and the surrogate is retrained.

Method
------
* Hold out a fixed random test set of ``--n_test`` cases (default 100).
* From the remaining pool, start with ``--n_init`` random training cases (30).
* For ``--n_iter`` iterations (default 20):
    - Train a Random Forest on the current training set.
    - Predict on the candidate pool (pool minus current training set).
    - Two strategies in parallel:
        * 'random'        — acquire ``--n_per_iter`` random candidates.
        * 'uncertainty'   — acquire the ``--n_per_iter`` candidates with the
                            highest predictive variance (averaged across the
                            86 outputs).
    - Retrain, re-evaluate R² on the FIXED test set.
* Repeat over ``--n_seeds`` random seeds and report median / IQR per strategy.
* Produces a learning curve PNG (R² vs # training samples) plus a CSV with the
  raw per-step metrics.

Outputs
-------
    active_learning_curve.png
    active_learning_history.csv

Usage
-----
    python surrogate_active_learning.py \
        --data ../inputs/overall_ml_numeric.csv \
        --output_dir ../outputs/overall
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import r2_score
from sklearn.preprocessing import StandardScaler

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from surrogate_ml_models import load_data, Config  # noqa: E402


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def _make_rf(random_state: int) -> RandomForestRegressor:
    """Random Forest used both for prediction and for uncertainty (tree var)."""
    return RandomForestRegressor(
        n_estimators=200,
        max_depth=None,
        min_samples_leaf=2,
        random_state=random_state,
        n_jobs=-1,
    )


def _tree_uncertainty(model: RandomForestRegressor, X_cand: np.ndarray) -> np.ndarray:
    """Average per-output prediction stdev across the forest trees.

    Returns a vector of length ``len(X_cand)``. Larger values = the trees in
    the forest disagree more on that input, so it's more 'informative'
    to label.
    """
    # Each tree produces (n_cand, n_out).
    per_tree = np.stack([tree.predict(X_cand) for tree in model.estimators_])
    # std across trees → (n_cand, n_out).
    std = per_tree.std(axis=0)
    # Normalise each output's std by its OOB scale so that high-magnitude
    # outputs (e.g. cost_total in dollars) don't dominate the ranking.
    scale = std.std(axis=0)
    scale[scale < 1e-9] = 1.0
    std_norm = std / scale[None, :]
    return std_norm.mean(axis=1)


def _evaluate(model, X_test: np.ndarray, Y_test: np.ndarray) -> dict:
    Y_pred = model.predict(X_test)
    r2_per_out = []
    for i in range(Y_test.shape[1]):
        # Guard against constant-variance test slices on outputs that may
        # accidentally be near-constant in the held-out subset.
        if Y_test[:, i].std() < 1e-9:
            continue
        r2_per_out.append(r2_score(Y_test[:, i], Y_pred[:, i]))
    r2_per_out = np.asarray(r2_per_out, dtype=np.float64)
    return {
        "n_outputs_used": int(len(r2_per_out)),
        "r2_mean": float(r2_per_out.mean()),
        "r2_median": float(np.median(r2_per_out)),
        "r2_p25": float(np.quantile(r2_per_out, 0.25)),
        "r2_p75": float(np.quantile(r2_per_out, 0.75)),
        "n_above_0_9": int((r2_per_out > 0.9).sum()),
    }


def run_one_seed(
    X: np.ndarray, Y: np.ndarray,
    seed: int,
    n_test: int, n_init: int, n_per_iter: int, n_iter: int,
) -> list[dict]:
    """Run both strategies for a single seed. Returns a list of step records."""
    rng = np.random.default_rng(seed)
    n = X.shape[0]
    perm = rng.permutation(n)
    test_idx = perm[:n_test]
    pool_idx = perm[n_test:]
    init_idx = pool_idx[:n_init].copy()
    remaining_pool = pool_idx[n_init:].copy()

    X_test, Y_test = X[test_idx], Y[test_idx]
    records: list[dict] = []

    for strategy in ("random", "uncertainty"):
        train_idx = init_idx.copy().tolist()
        pool = remaining_pool.copy().tolist()
        # Use a strategy-local RNG so each strategy is independently random
        # but reproducible per seed.
        local_rng = np.random.default_rng(seed * 100 + (0 if strategy == "random" else 1))
        # Standardise X using the initial training set; re-fit per iteration
        # to mimic a realistic 'retrain from scratch' pipeline.
        for step in range(n_iter + 1):
            scaler = StandardScaler().fit(X[train_idx])
            model = _make_rf(random_state=seed)
            model.fit(scaler.transform(X[train_idx]), Y[train_idx])
            metrics = _evaluate(model, scaler.transform(X_test), Y_test)
            records.append({
                "seed": seed,
                "strategy": strategy,
                "step": step,
                "n_train": len(train_idx),
                **metrics,
            })
            if step == n_iter or not pool:
                break
            pool_arr = np.asarray(pool, dtype=int)
            if strategy == "random":
                local_rng.shuffle(pool_arr)
                acquire = pool_arr[:n_per_iter]
            else:
                X_pool_s = scaler.transform(X[pool_arr])
                u = _tree_uncertainty(model, X_pool_s)
                # Pick the most uncertain.
                top = np.argsort(u)[-n_per_iter:]
                acquire = pool_arr[top]
            train_idx.extend(acquire.tolist())
            pool = list(set(pool) - set(acquire.tolist()))

    return records


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_curves(df: pd.DataFrame, out_path: Path) -> None:
    """Median R² (with IQR ribbon) per strategy as a function of train size."""
    fig, (ax_med, ax_above) = plt.subplots(1, 2, figsize=(12, 5))

    palette = {"random": "#888", "uncertainty": "#1f77b4"}
    for strategy, sub in df.groupby("strategy"):
        agg = sub.groupby("n_train").agg(
            r2_median=("r2_median", "median"),
            r2_p25=("r2_median", lambda s: np.quantile(s, 0.25)),
            r2_p75=("r2_median", lambda s: np.quantile(s, 0.75)),
            r2_mean=("r2_mean", "median"),
            n_above_0_9=("n_above_0_9", "median"),
        ).reset_index().sort_values("n_train")
        c = palette.get(strategy, "#444")
        ax_med.plot(agg["n_train"], agg["r2_median"], "-o",
                    color=c, label=f"{strategy} acquisition", markersize=4)
        ax_med.fill_between(agg["n_train"], agg["r2_p25"], agg["r2_p75"],
                            color=c, alpha=0.15)
        ax_above.plot(agg["n_train"], agg["n_above_0_9"], "-o",
                      color=c, label=f"{strategy} acquisition", markersize=4)

    for ax, title, ylab in [
        (ax_med, "Median per-output R²", "Median R² on held-out test set"),
        (ax_above, "Outputs with R² > 0.9", "# outputs (out of ~86)"),
    ]:
        ax.set_xlabel("# training cases (acquired)")
        ax.set_ylabel(ylab)
        ax.set_title(title)
        ax.grid(alpha=0.3)
        ax.legend(loc="lower right")

    ax_med.axhline(0.9, color="red", linestyle="--", alpha=0.5)
    fig.suptitle(
        "Active learning lift — uncertainty- vs random-acquisition (Random Forest)",
        fontsize=12,
    )
    plt.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    _STUDY_ROOT = _HERE.parent
    parser.add_argument("--data", default=str(_STUDY_ROOT / "inputs" / "overall_ml_numeric.csv"))
    parser.add_argument("--output_dir", default=str(_STUDY_ROOT / "outputs" / "overall"))
    parser.add_argument("--n_seeds", type=int, default=3)
    parser.add_argument("--n_init", type=int, default=30)
    parser.add_argument("--n_per_iter", type=int, default=10)
    parser.add_argument("--n_iter", type=int, default=20)
    parser.add_argument("--n_test", type=int, default=100)
    args = parser.parse_args()

    config = Config(data_path=args.data, output_dir=args.output_dir)
    print(f"[1/3] Loading {args.data}")
    X, Y, x_cols, y_cols, _, _ = load_data(config)
    print(f"    n_samples={X.shape[0]}, n_outputs={Y.shape[1]}")

    if args.n_init + args.n_test + args.n_per_iter * args.n_iter > X.shape[0]:
        raise ValueError(
            f"Requested {args.n_init} + {args.n_test} "
            f"+ {args.n_per_iter}*{args.n_iter} > {X.shape[0]} cases. "
            f"Reduce --n_iter or --n_per_iter."
        )

    print(f"[2/3] Running {args.n_seeds} seeds × 2 strategies × "
          f"{args.n_iter + 1} steps each")
    all_records: list[dict] = []
    for seed in range(args.n_seeds):
        print(f"    seed {seed}...")
        recs = run_one_seed(
            X, Y, seed,
            n_test=args.n_test, n_init=args.n_init,
            n_per_iter=args.n_per_iter, n_iter=args.n_iter,
        )
        all_records.extend(recs)

    df = pd.DataFrame(all_records)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "active_learning_history.csv"
    png_path = out_dir / "active_learning_curve.png"
    df.to_csv(csv_path, index=False)
    print(f"[3/3] Wrote {csv_path.name}")
    plot_curves(df, png_path)
    print(f"    Wrote {png_path.name}")

    # Headline numbers — last step of each strategy, median across seeds.
    print("\n=== Active-learning lift (final iteration, median across seeds) ===")
    final = df[df.groupby(["seed", "strategy"])["step"].transform("max")
               == df["step"]]
    summary = final.groupby("strategy").agg(
        n_train=("n_train", "median"),
        r2_median=("r2_median", "median"),
        r2_mean=("r2_mean", "median"),
        n_above_0_9=("n_above_0_9", "median"),
    )
    print(summary.to_string())


if __name__ == "__main__":
    main()
