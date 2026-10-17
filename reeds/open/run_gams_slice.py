import argparse
import re
import subprocess
import sys
from glob import glob
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import reeds  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "gams" / "slice_solve.gms"


def gams_command(casepath: Path, year: int, slice_dir: str) -> str:
    sw = reeds.io.get_switches(casepath)
    years = pd.read_csv(casepath / "inputs_case" / "modeledyears.csv").columns.astype(int).values
    tprev = {**{years[0]: years[0]}, **dict(zip(years[1:], years))}
    tnext = {**dict(zip(years, years[1:])), **{years[-1]: years[-1]}}
    batch_case = casepath.name
    if year == min(years):
        raise ValueError("the slice solve restarts from a prior solve year; it cannot run the first year")
    restarts = sorted(glob(str(casepath / "g00files" / f"{batch_case}_{tprev[year]}i*.g00")))
    if not restarts:
        raise FileNotFoundError(f"no restart file for {tprev[year]} under {casepath / 'g00files'}")
    cmd = reeds.inputs.solvestring_sequential(
        batch_case=batch_case,
        caseSwitches=sw,
        cur_year=year,
        next_year=tnext[year],
        prev_year=tprev[year],
        stress_year=f"{year}i0",
        restartfile=restarts[-1],
        hpc=int(sw["hpc"]),
        iteration=0,
    )
    cmd = cmd.replace(str(Path("reeds", "core", "solve", "3_solve_oneyear.gms")), str(SCRIPT), 1)
    cmd = re.sub(r" xs=\S+", "", cmd)
    lst = Path("lstfiles", f"{batch_case}_slice_{year}.lst")
    cmd = re.sub(r" o=\S+", lambda m: f" o={lst}", cmd)
    cmd = cmd.rstrip("\n") + f" --slice_dir={slice_dir}"
    return cmd


def main(casepath: str, year: int, slice_dir: str = "slice") -> Path:
    casepath = Path(casepath).resolve()
    (casepath / slice_dir).mkdir(exist_ok=True)
    cmd = gams_command(casepath, year, slice_dir)
    print(cmd)
    result = subprocess.run(cmd, shell=True, cwd=casepath)
    if result.returncode:
        raise RuntimeError(f"slice_solve.gms failed with return code {result.returncode}")
    out = casepath / slice_dir / f"slice_solution_{year}.gdx"
    if not out.is_file():
        raise FileNotFoundError(out)
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Solve one year of the ReEDS slice in GAMS and export it")
    parser.add_argument("casepath", type=str)
    parser.add_argument("year", type=int)
    parser.add_argument("--slice_dir", type=str, default="slice")
    args = parser.parse_args()
    main(args.casepath, args.year, args.slice_dir)
