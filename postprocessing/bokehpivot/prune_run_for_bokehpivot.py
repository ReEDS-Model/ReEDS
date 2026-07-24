#!/usr/bin/env python3
"""
Prune a ReEDS run folder for bokehpivot reporting.

This script keeps the files needed by the standard ReEDS 2.0 bokehpivot
report plus any .goo files anywhere under the run folder.

Required report-side files kept by default:
  - meta.csv
  - outputs/outputs.h5
  - inputs_case/crf.csv
  - inputs_case/val_r.csv
  - inputs_case/df_capex_init.csv
  - inputs_case/switches.csv
  - inputs_case/scalars.csv
  - inputs_case/hierarchy.csv
  - inputs_case/bcr.csv
  - inputs_case/cappayments_ba.csv
  - inputs_case/spur_parameters.csv

Usage:
  python prune_run_for_bokehpivot.py /path/to/ReEDS/runs/mycase
  python prune_run_for_bokehpivot.py /path/to/ReEDS/runs/mycase --apply
    python prune_run_for_bokehpivot.py /path/to/ReEDS/runs/batchname_ --apply --batch-prefix batchname_
"""

from __future__ import annotations

import argparse
from pathlib import Path


REQUIRED_RELATIVE_PATHS = {
    Path("meta.csv"),
    Path("outputs/outputs.h5"),
    Path("inputs_case/crf.csv"),
    Path("inputs_case/val_r.csv"),
    Path("inputs_case/df_capex_init.csv"),
    Path("inputs_case/switches.csv"),
    Path("inputs_case/scalars.csv"),
    Path("inputs_case/hierarchy.csv"),
    Path("inputs_case/bcr.csv"),
    Path("inputs_case/cappayments_ba.csv"),
    Path("inputs_case/spur_parameters.csv"),
}


def is_goo_file(path: Path) -> bool:
    return path.suffix.lower() == ".goo"


def should_keep(path: Path, run_root: Path) -> bool:
    try:
        rel_path = path.relative_to(run_root)
    except ValueError:
        return False
    return is_goo_file(path) or rel_path in REQUIRED_RELATIVE_PATHS


def looks_like_run_folder(path: Path) -> bool:
    return any((path / rel_path).exists() for rel_path in REQUIRED_RELATIVE_PATHS)


def collect_run_roots(root: Path, batch_prefix: str | None = None) -> list[Path]:
    if looks_like_run_folder(root):
        return [root]

    run_roots: list[Path] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if batch_prefix is not None and not child.name.startswith(batch_prefix):
            continue
        if looks_like_run_folder(child):
            run_roots.append(child)
    return run_roots


def prune_run(run_root: Path, apply_changes: bool) -> tuple[list[Path], list[Path], list[Path]]:
    kept_files: list[Path] = []
    deleted_files: list[Path] = []

    for current_path in sorted(run_root.rglob("*")):
        if not current_path.is_file():
            continue
        if should_keep(current_path, run_root):
            kept_files.append(current_path)
            continue
        deleted_files.append(current_path)
        if apply_changes:
            current_path.unlink()

    removed_dirs: list[Path] = []
    if apply_changes:
        for current_dir in sorted(
            (p for p in run_root.rglob("*") if p.is_dir()),
            key=lambda p: len(p.relative_to(run_root).parts),
            reverse=True,
        ):
            if current_dir == run_root:
                continue
            try:
                next(current_dir.iterdir())
            except StopIteration:
                current_dir.rmdir()
                removed_dirs.append(current_dir)

    return kept_files, deleted_files, removed_dirs


def main() -> int:
    parser = argparse.ArgumentParser(description="Prune a ReEDS run folder for bokehpivot reporting.")
    parser.add_argument("run_root", type=Path, help="Path to a ReEDS run folder or a batch folder containing runs/")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete files and empty directories. Without this flag, the script only reports what it would remove.",
    )
    parser.add_argument(
        "--batch-prefix",
        default=None,
        help="Optional prefix used to limit batch pruning to run folders whose names start with this string.",
    )
    args = parser.parse_args()

    run_root = args.run_root.expanduser().resolve()
    if not run_root.exists():
        raise FileNotFoundError(f"Run folder does not exist: {run_root}")
    if not run_root.is_dir():
        raise NotADirectoryError(f"Run root is not a directory: {run_root}")

    run_roots = collect_run_roots(run_root, args.batch_prefix)
    if not run_roots:
        raise FileNotFoundError(
            f"No run folders found under {run_root}. Point the script at a run folder, or at a batch folder with run subdirectories."
        )

    all_kept_files: list[Path] = []
    all_deleted_files: list[Path] = []
    all_removed_dirs: list[Path] = []
    for current_root in run_roots:
        kept_files, deleted_files, removed_dirs = prune_run(current_root, args.apply)
        all_kept_files.extend(kept_files)
        all_deleted_files.extend(deleted_files)
        all_removed_dirs.extend(removed_dirs)

    mode = "applied" if args.apply else "dry-run"
    if len(run_roots) == 1 and run_roots[0] == run_root:
        print(f"Prune {mode} for: {run_root}")
    else:
        print(f"Prune {mode} for batch: {run_root}")
        print(f"Run folders found: {len(run_roots)}")
        for current_root in run_roots:
            print(f"  {current_root.name}")
    print(f"Kept files: {len(all_kept_files)}")
    print(f"Files to delete: {len(all_deleted_files)}")
    if all_deleted_files:
        print("\nFiles to delete:")
        for path in all_deleted_files:
            print(f"  {path.relative_to(run_root)}")
    if args.apply:
        print(f"Removed empty directories: {len(all_removed_dirs)}")
    else:
        print("No files were deleted because --apply was not set.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())