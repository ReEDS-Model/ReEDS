from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import gams.transfer as gt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reeds.open.port_registry import GROUPS  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
GAMS_EXE = Path(r"C:\GAMS\53\gams.exe")


def gams_equations() -> list[str]:
    src = (ROOT / "reeds" / "core" / "setup" / "c_model.gms").read_text(encoding="utf-8")
    src = re.sub(r"^\*.*$", "", src, flags=re.M)
    names = re.findall(r"^(eq_\w+)\s*(?:\([^)]*\))?\s*(?:\$\[.*?\]|\$\(.*?\)|\$\w+)?\s*\.\.", src, flags=re.M | re.S)
    return list(dict.fromkeys(names))


def ported_equations() -> dict[str, str]:
    out = {}
    for group, spec in GROUPS.items():
        for e in spec["equations"]:
            out[e.lower()] = group
    return out


def dump_year(case: Path, year: int, iteration: int = 0) -> Path:
    out = case / "port" / f"alldata_{year}i{iteration}.gdx"
    if out.is_file():
        return out
    out.parent.mkdir(exist_ok=True)
    restart = case / "g00files" / f"{case.name}_{year}i{iteration}.g00"
    if not restart.is_file():
        raise FileNotFoundError(restart)
    script = out.with_suffix(".gms")
    script.write_text(f'execute_unload "{out.as_posix()}" ;\n', encoding="utf-8")
    result = subprocess.run([str(GAMS_EXE), str(script), f"r={restart}", f"o={out.with_suffix('.lst')}", "lo=0"], cwd=str(case))
    if result.returncode or not out.is_file():
        raise RuntimeError(f"alldata dump for {case.name} {year} failed with return code {result.returncode}")
    return out


def row_counts(alldata: Path) -> dict[str, int]:
    c = gt.Container(load_from=str(alldata))
    counts = {}
    for name, sym in c.data.items():
        if name.lower().startswith("eq_") and isinstance(sym, gt.Equation):
            counts[name.lower()] = 0 if sym.records is None else int(len(sym.records))
    return counts


def validation_status(case: Path, year: int, port_dir: str) -> str | None:
    report = case / port_dir / f"validate_{year}" / "report.json"
    if not report.is_file():
        return None
    rep = json.loads(report.read_text(encoding="utf-8"))
    gates = [rep["gate1_matrix"]["pass"], rep["gate2_objective"]["pass"], rep["gate3_gams_primal"]["pass"], rep["gate4_kkt"]["pass"]]
    return "pass" if all(gates) else "FAIL"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Which GAMS equations produce rows in which reference cases, and whether the port covers them")
    ap.add_argument("cases", nargs="+", help="GAMS case directories with g00files kept; append =2025,2030 to override --years for one case")
    ap.add_argument("--years", nargs="+", type=int, default=[2030])
    ap.add_argument("--port_dir", default="port")
    ap.add_argument("--out", default=None, help="csv path for the full table")
    args = ap.parse_args(argv)
    equations = gams_equations()
    ported = ported_equations()
    table = pd.DataFrame(index=[e.lower() for e in equations])
    table["group"] = [ported.get(e, "") for e in table.index]
    gates = {}
    for spec in args.cases:
        path, _, years = spec.partition("=")
        case = Path(path).resolve()
        for year in ([int(y) for y in years.split(",")] if years else args.years):
            col = f"{case.name}:{year}"
            counts = row_counts(dump_year(case, year))
            table[col] = [counts.get(e, 0) for e in table.index]
            gates[col] = validation_status(case, year, args.port_dir)
    count_cols = [c for c in table.columns if c != "group"]
    table["max_rows"] = table[count_cols].max(axis=1)
    table["status"] = [
        ("uncovered" if row.max_rows == 0 else ("ported" if row.group else "to port")) for row in table.itertuples()
    ]
    pd.set_option("display.width", 250)
    print(table.to_string())
    print()
    for col, g in gates.items():
        print(f"{col}: validation {g or 'not run'}")
    print()
    for status in ["uncovered", "to port", "ported"]:
        names = table.index[table["status"] == status].tolist()
        print(f"{status}: {len(names)}")
        if status != "ported":
            print("  " + ", ".join(names))
    if args.out:
        table.to_csv(args.out)
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
