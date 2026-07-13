#!/usr/bin/env python

import argparse
import os
from pathlib import Path


def _repo_root_from_app(app) -> Path:
    # app.srcdir points to docs/source, so repo root is two levels up.
    return Path(app.srcdir).resolve().parents[1]


def _repo_root_from_cli(reeds_path: str) -> Path:
    if reeds_path:
        return Path(reeds_path).resolve()
    # docs/scripts/generate_inputs_markdown.py -> repo root is two levels up.
    return Path(__file__).resolve().parents[2]


def _collect_input_readmes(inputs_root: Path) -> list[Path]:
    readmes = []
    for child in sorted(inputs_root.iterdir(), key=lambda p: p.name.casefold()):
        if not child.is_dir():
            continue
        readme = child / "README.md"
        if readme.exists():
            readmes.append(readme)
    return readmes


def _write_inputs_md(output_path: Path, readmes: list[Path]) -> None:
    lines = []
    lines.append("# Inputs Documentation")
    lines.append("")
    lines.append(
        "This page aggregates documentation from each folder README under the inputs directory."
    )
    lines.append("")
    lines.append("## Table of Contents")
    lines.append("")

    for readme in readmes:
        folder = readme.parent.name
        lines.append(f"- [inputs/{folder}](#inputs{folder})")

    for readme in readmes:
        folder = readme.parent.name
        include_rel = os.path.relpath(readme, output_path.parent).replace(os.sep, "/")
        lines.append("")
        lines.append(f"<a id='inputs{folder}'></a>")
        lines.append(f"## inputs/{folder}")
        lines.append("")
        lines.append("```{include} " + include_rel)
        lines.append("```")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(app=None):
    # If called from Sphinx, app is provided; otherwise support optional CLI usage.
    if app is None:
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--reedsPath",
            "-r",
            type=str,
            default="",
            help="Path to ReEDS repository root",
        )
        args = parser.parse_args()
        repo_root = _repo_root_from_cli(args.reedsPath)
    else:
        repo_root = _repo_root_from_app(app)

    inputs_root = repo_root / "inputs"
    docs_source_root = repo_root / "docs" / "source"
    output_path = docs_source_root / "inputs.md"

    readmes = _collect_input_readmes(inputs_root)
    _write_inputs_md(output_path, readmes)

    print("inputs.md has been updated from inputs/*/README.md files")


if __name__ == "__main__":
    main()