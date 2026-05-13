"""Run one ReEDS framework comparison adapter and write JSON."""

from __future__ import annotations

import argparse
import importlib
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from data_generator import make_problem

SIZES = ["small", "medium", "large", "xlarge"]
XPRESS_LICENSE_CANDIDATES = (
    "XPRESS_LICENSE_FILE",
    "XPAUTH_PATH",
)


@dataclass(slots=True)
class FrameworkResult:
    """Store one framework run result.

    Parameters
    ----------
    label : str
        Benchmark case label.
    module : str
        Python module that provides ``solve``.
    solver : str | None
        Solver passed to ``solve``.
    size : str
        Problem size.
    objective : float | None
        Objective value, when solve succeeds.
    build_s : float | None
        Adapter-reported model build time.
    solve_s : float | None
        Adapter-reported solver time.
    total_s : float | None
        ``build_s + solve_s``.
    error : str | None
        Error message, when the adapter fails.

    Examples
    --------
    >>> FrameworkResult("arco_highs", "solve_arco", "highs", "small", total_s=0.1).total_s
    0.1
    """

    label: str
    module: str
    solver: str | None
    size: str
    objective: float | None = None
    build_s: float | None = None
    solve_s: float | None = None
    total_s: float | None = None
    error: str | None = None


def normalize_solver(value: str | None) -> str | None:
    """Normalize solver CLI values.

    Parameters
    ----------
    value : str | None
        Raw solver value.

    Returns
    -------
    str | None
        ``None`` for empty or ``none`` values; otherwise the original string.

    Examples
    --------
    >>> normalize_solver('none') is None
    True
    >>> normalize_solver('highs')
    'highs'
    """
    if not value or value.lower() == "none":
        return None
    return value


def configure_xpress_license() -> None:
    license_path = next(
        (
            Path(os.environ[name]).expanduser()
            for name in XPRESS_LICENSE_CANDIDATES
            if os.environ.get(name)
        ),
        Path("~/Downloads/xpauth.xpr").expanduser(),
    )
    if not license_path.exists():
        return

    import xpress

    xpress.init(str(license_path))


def run_framework(
    label: str,
    module_name: str,
    size: str,
    *,
    solver: str | None = None,
    build_only: bool = False,
) -> FrameworkResult:
    """Run one framework adapter.

    Parameters
    ----------
    label : str
        Benchmark case label.
    module_name : str
        Importable Python module containing ``solve``.
    size : str
        Problem size from ``SIZES``.
    solver : str | None, default=None
        Optional solver keyword passed to ``solve``.
    build_only : bool, default=False
        Build the model but skip solving.

    Returns
    -------
    FrameworkResult
        Structured success or failure result.

    Examples
    --------
    >>> run_framework('bad', 'missing_module', 'small').error is not None
    True
    """
    solver = normalize_solver(solver)
    try:
        if solver == "xpress":
            configure_xpress_license()
        module = importlib.import_module(module_name)
        data = make_problem(size)
        kwargs: dict[str, Any] = {}
        if solver is not None:
            kwargs["solver"] = solver
        if build_only:
            kwargs["build_only"] = True
        objective, build_s, solve_s = module.solve(data, **kwargs)
    except Exception as exc:
        return FrameworkResult(label, module_name, solver, size, error=str(exc))

    return FrameworkResult(
        label=label,
        module=module_name,
        solver=solver,
        size=size,
        objective=None if math.isnan(objective) else objective,
        build_s=build_s,
        solve_s=solve_s,
        total_s=build_s + solve_s,
    )


def write_result(result: FrameworkResult, path: Path) -> None:
    """Write a result as JSON.

    Parameters
    ----------
    result : FrameworkResult
        Result to serialize.
    path : Path
        Output path.

    Examples
    --------
    >>> path = Path('/tmp/framework-result.json')
    >>> write_result(FrameworkResult('arco', 'solve_arco', 'highs', 'small'), path)
    >>> path.exists()
    True
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(result)), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser.

    Returns
    -------
    argparse.ArgumentParser
        Parser for ``run_framework.py``.

    Examples
    --------
    >>> args = build_parser().parse_args(['--label', 'arco', '--module', 'solve_arco', '--size', 'small', '--output', 'x.json'])
    >>> args.module_name
    'solve_arco'
    """
    parser = argparse.ArgumentParser(description="Run one framework comparison adapter.")
    parser.add_argument("--label", required=True)
    parser.add_argument("--module", required=True, dest="module_name")
    parser.add_argument("--solver")
    parser.add_argument("--size", required=True, choices=SIZES)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--build-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    Parameters
    ----------
    argv : Sequence[str] | None, default=None
        CLI arguments excluding program name.

    Returns
    -------
    int
        Process exit code. Adapter failures are captured in JSON and return 0.

    Examples
    --------
    >>> main(['--label', 'arco', '--module', 'solve_arco', '--solver', 'highs', '--size', 'small', '--build-only', '--output', '/tmp/arco.json'])
    0
    """
    args = build_parser().parse_args(argv)
    result = run_framework(
        args.label,
        args.module_name,
        args.size,
        solver=args.solver,
        build_only=args.build_only,
    )
    write_result(result, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
