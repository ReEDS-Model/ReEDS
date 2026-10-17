import argparse
import json
import re
import subprocess
import sys
from glob import glob
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import reeds  # noqa: E402
from reeds.open import gams_model, port_registry  # noqa: E402


def gams_command(casepath: Path, year: int, script: Path, lst_name: str, port_dir: str) -> str:
    sw = reeds.io.get_switches(casepath)
    years = pd.read_csv(casepath / "inputs_case" / "modeledyears.csv").columns.astype(int).values
    tprev = {**{years[0]: years[0]}, **dict(zip(years[1:], years))}
    tnext = {**dict(zip(years, years[1:])), **{years[-1]: years[-1]}}
    batch_case = casepath.name
    if year == min(years):
        raise ValueError("the port model restarts from a prior solve year; it cannot run the first year")
    restarts = sorted(glob(str(casepath / "g00files" / f"{batch_case}_{tprev[year]}i*.g00")))
    if not restarts:
        raise FileNotFoundError(f"no restart file for {tprev[year]} under {casepath / 'g00files'}")
    cmd = reeds.inputs.solvestring_sequential(
        batch_case=batch_case, caseSwitches=sw, cur_year=year, next_year=tnext[year], prev_year=tprev[year],
        stress_year=f"{year}i0", restartfile=restarts[-1], hpc=int(sw["hpc"]), iteration=0)
    cmd = cmd.replace(str(Path("reeds", "core", "solve", "3_solve_oneyear.gms")), str(script), 1)
    cmd = re.sub(r" xs=\S+", "", cmd)
    lst = Path("lstfiles", lst_name)
    cmd = re.sub(r" o=\S+", lambda m: f" o={lst}", cmd)
    return cmd.rstrip("\n") + f" --port_dir={port_dir}"


def main(casepath: str, year: int, groups: list[str], port_dir: str = "port") -> Path:
    casepath = Path(casepath).resolve()
    out_dir = casepath / port_dir
    out_dir.mkdir(exist_ok=True)
    equations, variables = port_registry.resolve(groups)
    script = out_dir / f"model_{year}.gms"
    info = gams_model.write_model_gms(equations, variables, script)
    info["groups"] = groups
    (out_dir / f"model_{year}.json").write_text(json.dumps(info, indent=2))
    cmd = gams_command(casepath, year, script, f"{casepath.name}_port_{year}.lst", port_dir)
    print(cmd)
    result = subprocess.run(cmd, shell=True, cwd=casepath)
    if result.returncode:
        raise RuntimeError(f"{script.name} failed with return code {result.returncode}")
    out = out_dir / f"port_solution_{year}.gdx"
    if not out.is_file():
        raise FileNotFoundError(out)
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Solve one year of the ported ReEDS equations in GAMS and export it")
    parser.add_argument("casepath", type=str)
    parser.add_argument("year", type=int)
    parser.add_argument("--groups", nargs="+", default=["slice"])
    parser.add_argument("--port_dir", type=str, default="port")
    args = parser.parse_args()
    main(args.casepath, args.year, args.groups, args.port_dir)
