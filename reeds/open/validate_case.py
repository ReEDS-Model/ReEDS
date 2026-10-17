from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reeds.open import check_derive, inputs_h5, run_gams_model, validate_slice  # noqa: E402
from reeds.open.port_registry import GROUPS  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the GAMS oracle for each year of a case and run every check of the port against it")
    ap.add_argument("casepath", help="GAMS case directory with g00files kept")
    ap.add_argument("--years", nargs="+", type=int, required=True)
    ap.add_argument("--port_dir", default="port")
    ap.add_argument("--groups", nargs="+", default=list(GROUPS))
    ap.add_argument("--highs-solver", default="ipm")
    ap.add_argument("--skip-derive-check", action="store_true")
    ap.add_argument("--builder", default="pyoframe", choices=["pyoframe", "linopy"])
    args = ap.parse_args(argv)
    case = Path(args.casepath).resolve()
    results = {}
    for year in args.years:
        inputs_h5.ingest(case, f"{year}i0")
    for year in args.years:
        port = case / args.port_dir
        if not (port / f"port_solution_{year}.gdx").is_file():
            run_gams_model.main(str(case), year, args.groups, args.port_dir)
        print(f"==== validate {case.name} {year}", flush=True)
        rc_val = validate_slice.main([str(port), str(year), "--derived", "--prefix", "port", "--highs-solver", args.highs_solver,
                                      "--builder", args.builder])
        rc_der = 0
        if not args.skip_derive_check:
            print(f"==== check_derive {case.name} {year}", flush=True)
            rc_der = check_derive.main([str(case), str(year), "--oracle", str(port / f"port_inputs_{year}.gdx"),
                                        "--state_gdx", str(port / f"port_solution_{year}.gdx")])
        results[year] = (rc_val, rc_der)
    print()
    for year, (rc_val, rc_der) in results.items():
        print(f"{case.name} {year}: four gates {'PASS' if rc_val == 0 else 'FAIL'}; derived symbols {'PASS' if rc_der == 0 else 'FAIL'}")
    return 1 if any(rc for pair in results.values() for rc in pair) else 0


if __name__ == "__main__":
    raise SystemExit(main())
