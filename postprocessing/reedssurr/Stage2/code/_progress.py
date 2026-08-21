"""Live training progress monitor.

Watches the joblibs directories AND the train_*.log files for both layers
and prints a refreshing status table every REFRESH_S seconds.

Usage:  python _progress.py
Stop:   Ctrl+C
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

REFRESH_S = 10
HERE = Path(__file__).resolve().parent
STAGE1 = HERE.parent
LAYERS = ("overall", "regional")
MODELS_ORDER = (
    "knn", "ridge", "lasso",
    "rf", "xgb", "nn", "ngboost",
)
LOG_PATHS = {L: HERE / f"train_{L}.log" for L in LAYERS}
from surrogate_paths import resolve_models_dir  # noqa: E402
MODELS_DIRS = {L: resolve_models_dir(STAGE1 / "outputs" / L) for L in LAYERS}
# Plain-text mirror of the dashboard, refreshed every cycle.  Open this
# file in VS Code as a regular editor tab to watch progress without ever
# needing to switch terminals.
PROGRESS_FILE = HERE / "PROGRESS.txt"

# ANSI escape codes for in-place refresh
CLEAR_SCREEN = "\033[2J\033[H"
RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RED = "\033[31m"
DIM = "\033[2m"

# Enable ANSI on Windows 10+
if sys.platform == "win32":
    os.system("")


def _read_log_tail(path: Path, n: int = 80) -> list[str]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return lines[-n:]
    except Exception:
        return []


_RE_HEADER = re.compile(r"^\s*---\s*([A-Z_]+)\s*(?:\([^)]*\))?\s*---\s*$")
_RE_R2     = re.compile(r"OOF R\u00b2 mean:\s*([-\d.]+),\s*median:\s*([-\d.]+)")
_RE_SAVED  = re.compile(r"Saved final model:\s*(\w+)\.joblib")


def _parse_log_state(log_lines: list[str]) -> dict:
    """Return dict with keys: current, last_r2_mean, last_r2_median, completed."""
    state = {
        "current": None,
        "last_r2_mean": None,
        "last_r2_median": None,
        "completed": [],
    }
    for line in log_lines:
        m = _RE_HEADER.match(line)
        if m:
            state["current"] = m.group(1).lower()
            state["last_r2_mean"] = None
            state["last_r2_median"] = None
            continue
        m = _RE_R2.search(line)
        if m:
            state["last_r2_mean"] = float(m.group(1))
            state["last_r2_median"] = float(m.group(2))
            continue
        m = _RE_SAVED.search(line)
        if m:
            state["completed"].append(m.group(1).lower())
            continue
    return state


def _model_status(layer: str, model: str, log_state: dict, jobs: set) -> tuple[str, str]:
    """Return (icon+color, plain-text reason) for one model."""
    if model in jobs:
        return f"{GREEN}\u2713 done   {RESET}", "joblib written"
    if log_state["current"] == model:
        r2m = log_state.get("last_r2_mean")
        if r2m is not None:
            return f"{CYAN}\u25b6 fitting{RESET}", f"OOF done R\u00b2={r2m:.3f}, fitting final"
        return f"{CYAN}\u25b6 OOF CV {RESET}", "running k-fold CV"
    return f"{DIM}\u00b7 pending{RESET}", ""


def _layer_block(layer: str, plain: bool = False) -> str:
    log_lines = _read_log_tail(LOG_PATHS[layer])
    log_state = _parse_log_state(log_lines)
    jobs_dir = MODELS_DIRS[layer]
    jobs_set: set[str] = set()
    if jobs_dir.exists():
        jobs_set = {p.stem for p in jobs_dir.glob("*.joblib")}
    n_done = sum(1 for m in MODELS_ORDER if m in jobs_set)
    pct = int(100 * n_done / len(MODELS_ORDER))
    bar_len = 30
    fill = int(bar_len * n_done / len(MODELS_ORDER))
    if plain:
        bar = f"{'#' * fill}{'-' * (bar_len - fill)}"
    else:
        bar = f"{GREEN}{'#' * fill}{RESET}{DIM}{'-' * (bar_len - fill)}{RESET}"
    lines: list[str] = []
    if plain:
        lines.append(f"{layer.upper():<9}  [{bar}] {n_done}/{len(MODELS_ORDER)}  ({pct}%)")
    else:
        lines.append(f"{BOLD}{layer.upper():<9}{RESET}  [{bar}] {n_done}/{len(MODELS_ORDER)}  ({pct}%)")
    for m in MODELS_ORDER:
        if plain:
            if m in jobs_set:
                icon, reason = "[done]   ", "joblib written"
            elif log_state["current"] == m:
                r2m = log_state.get("last_r2_mean")
                if r2m is not None:
                    icon = "[fitting]"
                    reason = f"OOF done R2={r2m:.3f}, fitting final"
                else:
                    icon = "[OOF CV] "
                    reason = "running k-fold CV"
            else:
                icon, reason = "[wait]   ", ""
        else:
            icon, reason = _model_status(layer, m, log_state, jobs_set)
        ts = ""
        if m in jobs_set:
            jp = jobs_dir / f"{m}.joblib"
            try:
                ts_str = datetime.fromtimestamp(jp.stat().st_mtime).strftime("%H:%M:%S")
                if plain:
                    ts = f"  @{ts_str}"
                else:
                    ts = f"  {DIM}@{ts_str}{RESET}"
            except Exception:
                ts = ""
        if plain:
            lines.append(f"   {icon} {m:<10}{ts}  {reason}")
        else:
            lines.append(f"   {icon} {m:<10}{ts}  {DIM}{reason}{RESET}")
    tail = [ln.rstrip() for ln in log_lines if ln.strip()][-3:]
    if tail:
        joined = " | ".join(tail)[-160:]
        if plain:
            lines.append(f"   log: {joined}")
        else:
            lines.append(f"   {DIM}log: {joined}{RESET}")
    return "\n".join(lines)


def _build_plain_report(started: datetime, now: datetime) -> str:
    elapsed = str(now - started).split(".")[0]
    out = []
    out.append("=" * 76)
    out.append(f"  ReEDS-Proxy -- Training Progress")
    out.append(f"  Refresh every {REFRESH_S}s   "
               f"Started {started:%Y-%m-%d %H:%M:%S}   "
               f"Now {now:%H:%M:%S}   Elapsed {elapsed}")
    out.append("=" * 76)
    out.append("")
    out.append(_layer_block("overall", plain=True))
    out.append("")
    out.append(_layer_block("regional", plain=True))
    out.append("")
    out.append("-" * 76)
    out.append("  Tip: enable VS Code File > Auto Save and 'files.autoRevert'")
    out.append("       so this view reloads automatically.")
    out.append("       Stop monitor with Ctrl+C in the python terminal.")
    out.append("       Stopping the monitor does NOT stop training.")
    out.append("-" * 76)
    return "\n".join(out) + "\n"


def main() -> None:
    started = datetime.now()
    try:
        while True:
            now = datetime.now()
            elapsed = now - started
            # Plain-text mirror to file so user can open in editor.
            try:
                PROGRESS_FILE.write_text(
                    _build_plain_report(started, now),
                    encoding="utf-8",
                )
            except Exception:
                pass
            # Coloured terminal output (unchanged).
            print(CLEAR_SCREEN, end="")
            print(f"{BOLD}ReEDS-Proxy \u2014 Training Progress{RESET}  "
                  f"{DIM}(refresh {REFRESH_S}s, started {started:%H:%M:%S}, "
                  f"elapsed {str(elapsed).split('.')[0]}){RESET}\n")
            print(_layer_block("overall"))
            print()
            print(_layer_block("regional"))
            print()
            print(f"{DIM}Mirror file: {PROGRESS_FILE} (open in editor for "
                  f"auto-refreshing view).{RESET}")
            print(f"{DIM}Ctrl+C here to stop monitoring (does NOT stop "
                  f"training).{RESET}")
            time.sleep(REFRESH_S)
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Monitor stopped. Training (if any) continues in its own "
              f"terminals.{RESET}")


if __name__ == "__main__":
    main()
