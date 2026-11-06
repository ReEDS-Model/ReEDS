"""Item 12 - corridor floors: minimum over the 486 runs vs ReEDS initial capacity.

ReEDS reports tran_out(r, rr) = (energy capacity r->rr + rr->r) / 2
(reeds/core/terminus/report.gms), so the initial corridor capacity is
(MW_forward + MW_reverse) / 2 from inputs/transmission/itl_NARIS.csv, mapped
to the z134 zones (p60..p67) through zonehash.csv / interfaces_r.csv the same
way reeds.inputs.get_itls does. Writes data/12_corridor_floor_vs_init.csv.
"""
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ZONES = REPO / "inputs" / "zones" / "z134"


def main():
    zh = pd.read_csv(ZONES / "zonehash.csv", index_col="r")["md5"]
    itf = pd.read_csv(ZONES / "interfaces_r.csv")
    itl = pd.read_csv(REPO / "inputs" / "transmission" / "itl_NARIS.csv").rename(
        columns={"md5_from": "md5_r", "md5_to": "md5_rr"})
    itf["r"] = itf.interface.str.split("~~").str[0]
    itf["rr"] = itf.interface.str.split("~~").str[1]
    itf["md5_r"], itf["md5_rr"] = itf.r.map(zh), itf.rr.map(zh)
    e = itf.merge(itl, on=["md5_r", "md5_rr"], how="left")
    regs = [f"p{i}" for i in range(60, 68)]
    e = e[e.r.isin(regs) & e.rr.isin(regs)].copy()
    e["init_MW"] = (e.MW_forward + e.MW_reverse) / 2
    e["col"] = ["tran_%s_%s_AC" % tuple(sorted((a, b), key=lambda x: int(x[1:])))
                for a, b in zip(e.r, e.rr)]
    df = pd.read_csv(REPO / "postprocessing" / "reedssurr" / "Stage2" / "inputs"
                     / "regional_ml_numeric_merged.csv")
    tc = [c for c in df.columns if c.startswith("tran_")]
    out = pd.DataFrame({"min_486": df[tc].min(), "max_486": df[tc].max()}).join(
        e.set_index("col")[["MW_forward", "MW_reverse", "init_MW"]], how="outer")
    out["min_minus_init"] = out.min_486 - out.init_MW
    out.to_csv(HERE / "data" / "12_corridor_floor_vs_init.csv")
    print(out.round(3).to_string())


if __name__ == "__main__":
    main()
