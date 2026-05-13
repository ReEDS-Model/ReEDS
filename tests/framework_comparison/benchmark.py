"""
Benchmark harness for the ReEDS LP framework comparison.

Runs each framework x each problem size and collects:
  - build_s   : model-construction time (seconds)
  - solve_s   : LP-solver time (seconds)
  - total_s   : build_s + solve_s
  - objective : optimal objective value (used for cross-check)
  - peak_mb   : peak RSS memory increase (MiB) via psutil background poll
  - loc        : non-blank, non-comment source lines in solve_*.py

Usage examples
--------------
# All frameworks, all sizes (slow)
python benchmark.py

# Quick sanity-check — small problem only
python benchmark.py --size small

# Subset of frameworks
python benchmark.py --frameworks linopy pyomo --size small medium

# Include gamspy/CPLEX as a separate entry
python benchmark.py --frameworks gamspy_cplex --size small
"""

from __future__ import annotations

import argparse
import csv
import importlib
import math
import sys
import threading
from datetime import datetime
from pathlib import Path

import psutil

# ── Make sure sibling modules are importable ──────────────────────────────────
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from data_generator import make_problem   # noqa: E402

# ── Framework registry ────────────────────────────────────────────────────────
# Each entry: (label, module_name, solver_kwarg)
# solver_kwarg is passed as `solver=` to solve(); None → omit kwarg.
FRAMEWORK_REGISTRY: list[tuple[str, str, str | None]] = [
    ("linopy",         "solve_linopy",         "highs"),
    ("pyomo",          "solve_pyomo",          "highs"),
    ("pyoptinterface", "solve_pyoptinterface", "highs"),
    ("arco",           "solve_arco",           "highs"),
    ("gams_highs",     "solve_gams",           "highs"),
    ("gams_cplex",     "solve_gams",           "cplex"),
    ("gamspy_highs",   "solve_gamspy",         "highs"),
    ("gamspy_cplex",   "solve_gamspy",         "cplex"),
]

SIZES = ["small", "medium", "large", "xlarge"]

# Objective tolerance for cross-framework sanity check (relative)
ATOL_REL = 1e-3


# ── Helpers ───────────────────────────────────────────────────────────────────

def count_loc(module_name: str) -> int:
    """Count non-blank, non-comment lines in tests/framework_comparison/<module>.py."""
    src = HERE / f"{module_name}.py"
    if not src.exists():
        return -1
    count = 0
    with open(src, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                count += 1
    return count


def _peak_rss_mb(func, *args, **kwargs):
    """
    Run func(*args, **kwargs) while polling RSS every 10 ms in a background
    thread.  Returns (result, peak_increase_mb) where peak_increase_mb is the
    maximum RSS increase above the baseline observed during the call.

    Using psutil RSS instead of tracemalloc so that native C-extension
    allocations (e.g. pyoptinterface → HiGHS C library) are counted.
    """
    proc     = psutil.Process()
    baseline = proc.memory_info().rss
    peak     = [baseline]
    stop     = threading.Event()

    def _poll():
        while not stop.is_set():
            try:
                peak[0] = max(peak[0], proc.memory_info().rss)
            except psutil.NoSuchProcess:
                break
            stop.wait(0.01)   # 10 ms interval

    t = threading.Thread(target=_poll, daemon=True)
    t.start()
    try:
        result = func(*args, **kwargs)
    finally:
        stop.set()
        t.join()
    return result, (peak[0] - baseline) / 1024**2


def run_one(
    label: str,
    module_name: str,
    solver: str | None,
    data,
    build_only: bool = False,
    measure_memory: bool = True,
) -> dict:
    """Import module, run solve() under RSS polling, return a result dict."""
    try:
        mod = importlib.import_module(module_name)
    except ImportError as exc:
        return {
            "label": label,
            "error": f"ImportError: {exc}",
            "objective": None,
            "build_s": None,
            "solve_s": None,
            "total_s": None,
            "peak_mb": None,
        }

    def _call():
        kwargs: dict = {}
        if solver is not None:
            kwargs["solver"] = solver
        if build_only:
            kwargs["build_only"] = True
        return mod.solve(data, **kwargs)

    try:
        if measure_memory:
            (obj, build_s, solve_s), peak_mb = _peak_rss_mb(_call)
        else:
            obj, build_s, solve_s = _call()
            peak_mb = None
        if math.isnan(obj):
            obj = None
    except Exception as exc:
        return {
            "label": label,
            "error": str(exc),
            "objective": None,
            "build_s": None,
            "solve_s": None,
            "total_s": None,
            "peak_mb": None,
        }

    return {
        "label": label,
        "error": None,
        "objective": obj,
        "build_s": build_s,
        "solve_s": solve_s,
        "total_s": build_s + solve_s,
        "peak_mb": peak_mb,
    }


def fmt(val, fmt_spec: str, missing: str = "ERROR") -> str:
    if val is None:
        return missing
    return format(val, fmt_spec)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark Python LP frameworks on the ReEDS mini-problem."
    )
    parser.add_argument(
        "--size", nargs="+", choices=SIZES, default=SIZES,
        metavar="SIZE",
        help="Problem size(s) to benchmark. Default: all.",
    )
    parser.add_argument(
        "--frameworks", nargs="+",
        choices=[label for label, *_ in FRAMEWORK_REGISTRY],
        default=[label for label, *_ in FRAMEWORK_REGISTRY],
        metavar="FW",
        help="Framework labels to include. Default: all.",
    )
    parser.add_argument(
        "--no-memory", action="store_true",
        help="Skip peak-memory measurement (disables psutil RSS polling thread).",
    )
    parser.add_argument(
        "--no-solve", action="store_true",
        help="Build models but skip the LP solve (reports build time and memory only).",
    )
    parser.add_argument(
        "--repeat", type=int, default=1, metavar="N",
        help="Repeat each (framework, size) N times and report the minimum times.",
    )
    args = parser.parse_args()

    selected_sizes = args.size
    selected_labels = set(args.frameworks)
    selected_entries = [
        (label, mod, solver)
        for (label, mod, solver) in FRAMEWORK_REGISTRY
        if label in selected_labels
    ]

    # Pre-generate all problem data (outside timing loop)
    print("Generating problem data ...")
    problems = {sz: make_problem(sz) for sz in selected_sizes}

    # Pre-compute LOC counts
    loc_cache: dict[str, int] = {}
    for (_, mod, _) in selected_entries:
        if mod not in loc_cache:
            loc_cache[mod] = count_loc(mod)

    # Collect results
    all_rows: list[dict] = []

    col_w = 18  # framework column width
    num_w = 10  # numeric column width

    header = (
        f"{'framework':<{col_w}} {'size':<8}"
        f" {'build_s':>{num_w}} {'solve_s':>{num_w}} {'total_s':>{num_w}}"
        f" {'peak_mb':>{num_w}} {'objective':>20} {'loc':>6}"
    )
    sep = "-" * len(header)
    print()
    print(header)
    print(sep)

    ref_objectives: dict[str, float] = {}   # size → first successful objective

    for sz in selected_sizes:
        data = problems[sz]
        size_first = True

        for (label, mod, solver) in selected_entries:
            best: dict | None = None

            for _ in range(args.repeat):
                row = run_one(label, mod, solver, data,
                              build_only=args.no_solve,
                              measure_memory=not args.no_memory)
                if best is None or (
                    row["total_s"] is not None
                    and (best["total_s"] is None
                         or row["total_s"] < best["total_s"])
                ):
                    best = row

            assert best is not None
            best["size"] = sz
            best["loc"] = loc_cache.get(mod, -1)
            all_rows.append(best)

            # Cross-framework objective sanity check
            if best["objective"] is not None:
                key = sz
                if key not in ref_objectives:
                    ref_objectives[key] = best["objective"]
                else:
                    ref = ref_objectives[key]
                    rel_err = abs(best["objective"] - ref) / max(abs(ref), 1e-9)
                    if rel_err > ATOL_REL:
                        best["error"] = (
                            best.get("error") or ""
                        ) + f" [OBJ MISMATCH: {best['objective']:.6g} vs {ref:.6g}]"

            # Print row
            if size_first:
                print()   # blank line between sizes
                size_first = False

            err_suffix = f"  << {best['error']}" if best["error"] else ""
            peak_str = f"{'---':>{num_w}}" if args.no_memory else fmt(best['peak_mb'], f'>{num_w}.1f')
            print(
                f"{label:<{col_w}} {sz:<8}"
                f" {fmt(best['build_s'], f'>{num_w}.3f')}"
                f" {fmt(best['solve_s'], f'>{num_w}.3f')}"
                f" {fmt(best['total_s'], f'>{num_w}.3f')}"
                f" {peak_str}"
                f" {fmt(best['objective'], f'>20,.0f')}"
                f" {best['loc']:>{6}}"
                f"{err_suffix}"
            )

    print()
    print(sep)

    # Save CSV
    results_dir = HERE / "results"
    results_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = results_dir / f"benchmark_{ts}.csv"

    fieldnames = [
        "framework", "size", "build_s", "solve_s", "total_s",
        "peak_mb", "objective", "loc", "error",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in all_rows:
            writer.writerow({
                "framework": row["label"],
                "size": row.get("size", ""),
                "build_s": row["build_s"],
                "solve_s": row["solve_s"],
                "total_s": row["total_s"],
                "peak_mb": row["peak_mb"],
                "objective": row["objective"],
                "loc": row.get("loc", ""),
                "error": row.get("error", ""),
            })

    print(f"Results saved to: {csv_path.relative_to(HERE.parent.parent)}")


if __name__ == "__main__":
    main()
