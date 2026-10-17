"""ReEDS-style outputs for the slice.

Each output reproduces the definition in ReEDS ``core/terminus/report.gms`` or
``report_calcs.py`` (cited per function), restricted to what the slice
contains. Keys, column names, units and file layout match ReEDS:

* ``outputs.h5``: one group per key, a ``columns`` dataset plus one dataset
  per column. Strings are stored as fixed-width bytes, ``t`` as uint16 and
  ``Value`` as float32, so ``reeds.io.read_output(case, key)`` reads it.
* ``outputs/{key}.csv``: the same tables as CSV.
* Zeros are dropped, as GAMS does.

Outputs that depend on parts of ReEDS outside the slice (upgrades, hybrids,
H2, operating reserves, RPS, CCS, ...) are not produced.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

from .contract import Case
from .prep import Prepared


def _lvl(res: dict, name: str) -> pl.DataFrame:
    return res["primal"][name].rename({"solution": "Value"})


def _mar(res: dict, name: str) -> pl.DataFrame:
    return res["dual"][name].rename({"dual": "Value"}).with_columns(pl.col("Value").fill_null(0.0))


def _par(case: Case, name: str, rename_value: str = "Value") -> pl.DataFrame:
    return case[name].rename({"value": rename_value})


def _ilr(case: Case) -> pl.DataFrame:
    """ilr(i) is 1 by default in b_inputs.gms (ilr(i)$valcap_i = 1; upv overridden)."""
    techs = case["valcap"].select("i").unique()
    return (techs.join(case["ilr"].rename({"value": "ilr"}), on="i", how="left")
            .with_columns(pl.col("ilr").fill_null(1.0)))


def _scale_dual(df: pl.DataFrame, case: Case) -> pl.DataFrame:
    """(1 / cost_scale) * (1 / pvf_onm(t)) * marginal, as used for every reqt_price."""
    cs = case.scalar("cost_scale")
    return (df.join(case["pvf_onm"].rename({"value": "pvf"}), on="t", how="inner")
            .with_columns((pl.col("Value") / cs / pl.col("pvf")).alias("Value")).drop("pvf"))


def _members(case: Case, name: str) -> list:
    return list(case.members(name))


def _combine_forward_reverse(df: pl.DataFrame, agg: str) -> pl.DataFrame:
    """report_calcs.combine_forward_reverse: forward (r<rr) plus or minus reverse (r>rr)."""
    other = [c for c in df.columns if c not in ("r", "rr", "Value")]
    fwd = df.filter(pl.col("r") < pl.col("rr"))
    rev = (df.filter(pl.col("r") > pl.col("rr"))
           .rename({"r": "rr", "rr": "r"})
           .with_columns(pl.col("Value") * (-1.0 if agg == "net" else 1.0)))
    return (pl.concat([fwd.select(["r", "rr"] + other + ["Value"]),
                       rev.select(["r", "rr"] + other + ["Value"])])
            .group_by(["r", "rr"] + other).agg(pl.col("Value").sum()))


def reeds_outputs(case: Case, P: Prepared, res: dict) -> dict[str, pl.DataFrame]:
    out: dict[str, pl.DataFrame] = {}
    tmodel = case["tmodel"]
    hours = _par(case, "hours", "hours")
    h_rep, h_stress = _members(case, "h_rep"), _members(case, "h_stress")
    ilr = _ilr(case)

    CAP, GEN, INV = _lvl(res, "CAP"), _lvl(res, "GEN"), _lvl(res, "INV")
    SIN, LVL, LOAD, FLOW = (_lvl(res, n) for n in ("STORAGE_IN", "STORAGE_LEVEL", "LOAD", "FLOW"))

    # objfn_raw = z.l
    out["objfn_raw"] = pl.DataFrame({"Value": [res["objective"]]})

    # cap_deg_ivrt(i,v,r,t) = CAP.l / ilr
    out["cap_deg_ivrt"] = (CAP.join(ilr, on="i").with_columns(pl.col("Value") / pl.col("ilr"))
                           .select(["i", "v", "r", "t", "Value"]))
    # cap_ivrt: CAP/ilr, except upv/wind/distpv use undegraded exog + sum of INV over inv_cond
    undeg = set(_members(case, "upv") + _members(case, "wind") + _members(case, "distpv"))
    inv_all = pl.concat([INV.rename({"t": "tt"}),
                         _par(case, "state_INV").select(["i", "v", "r", "tt", "Value"])])
    inv_sum = (case["inv_cond"].join(tmodel, on="t", how="semi")
               .join(inv_all, on=["i", "v", "r", "tt"], how="inner")
               .group_by(["i", "v", "r", "t"]).agg(pl.col("Value").sum()))
    exog = _par(case, "m_capacity_exog").join(tmodel, on="t", how="semi")
    und = (pl.concat([exog.select(["i", "v", "r", "t", "Value"]), inv_sum.select(["i", "v", "r", "t", "Value"])])
           .group_by(["i", "v", "r", "t"]).agg(pl.col("Value").sum())
           .join(P.var["CAP"], on=["i", "v", "r", "t"], how="semi")
           .filter(pl.col("i").is_in(list(undeg)))
           .join(ilr, on="i").with_columns(pl.col("Value") / pl.col("ilr")).drop("ilr"))
    out["cap_ivrt"] = pl.concat([out["cap_deg_ivrt"].filter(~pl.col("i").is_in(list(undeg))),
                                 und.select(["i", "v", "r", "t", "Value"])])
    # cap_out(i,r,t) = sum(v, cap_ivrt)
    out["cap"] = out["cap_ivrt"].group_by(["i", "r", "t"]).agg(pl.col("Value").sum())
    # cap_energy_ivrt: battery = CAP_ENERGY.l (6_data_dump.gms); psh = CAP * storage_duration_m
    psh = _members(case, "psh")
    cap_e = _lvl(res, "CAP_ENERGY")
    psh_e = (CAP.filter(pl.col("i").is_in(psh))
             .join(_par(case, "slice_dur_coef", "dur"), on=["i", "v", "r"], how="inner")
             .with_columns(pl.col("Value") * pl.col("dur")).drop("dur"))
    out["cap_energy_ivrt"] = pl.concat([cap_e, psh_e.select(cap_e.columns)])
    # cap_new_ivrt(i,v,r,t) = INV/ilr ; cap_new_out(i,r,t) = sum(v, INV)/ilr
    out["cap_new_ivrt"] = (INV.join(ilr, on="i").with_columns(pl.col("Value") / pl.col("ilr"))
                           .select(["i", "v", "r", "t", "Value"]))
    out["cap_new_out"] = out["cap_new_ivrt"].group_by(["i", "r", "t"]).agg(pl.col("Value").sum())
    out["cap_energy_new_out"] = _lvl(res, "INV_ENERGY")
    # cap_new_bin_out(i,v,r,t,rscbin): INV_RSC/ilr for rsc techs, INV/ilr in "bin1" otherwise
    rsc = _members(case, "rsc_i")
    bins = (_lvl(res, "INV_RSC").join(ilr, on="i").with_columns(pl.col("Value") / pl.col("ilr"))
            .select(["i", "v", "r", "t", "rscbin", "Value"]))
    nonrsc = (out["cap_new_ivrt"].filter(~pl.col("i").is_in(rsc))
              .with_columns(pl.lit("bin1").alias("rscbin")).select(bins.columns))
    out["cap_new_bin_out"] = pl.concat([bins, nonrsc])

    # gen_ivrt(i,v,r,t) = sum(h, GEN * hours)
    out["gen_ivrt"] = (GEN.join(hours, on="h").with_columns(pl.col("Value") * pl.col("hours"))
                       .group_by(["i", "v", "r", "t"]).agg(pl.col("Value").sum()))
    # gen_h(i,r,allh,t) = sum(v, GEN - STORAGE_IN[storage_standalone])
    stand = _members(case, "storage_standalone")
    net = pl.concat([GEN, SIN.filter(pl.col("i").is_in(stand)).with_columns(-pl.col("Value"))])
    gen_h = net.group_by(["i", "r", "h", "t"]).agg(pl.col("Value").sum()).rename({"h": "allh"})
    out["gen_h"] = gen_h.select(["i", "r", "allh", "t", "Value"])
    out["gen_h_stress"] = out["gen_h"].filter(pl.col("allh").is_in(h_stress))
    # gen_ann(i,r,t) = sum(h, gen_h * hours)
    out["gen_ann"] = (out["gen_h"].join(hours.rename({"h": "allh"}), on="allh")
                      .with_columns(pl.col("Value") * pl.col("hours"))
                      .group_by(["i", "r", "t"]).agg(pl.col("Value").sum()))

    # storage
    stor = _members(case, "storage")
    out["stor_in"] = SIN.rename({"h": "allh"})
    out["stor_out"] = GEN.filter(pl.col("i").is_in(stor)).rename({"h": "allh"})
    out["stor_level"] = LVL.rename({"h": "allh"})
    s_in = (SIN.join(hours, on="h").with_columns(pl.col("Value") * pl.col("hours"))
            .group_by(["i", "v", "r", "t"]).agg(pl.col("Value").sum()).with_columns(pl.lit("in").alias("_s0")))
    s_out = (out["gen_ivrt"].filter(pl.col("i").is_in(stor)).with_columns(pl.lit("out").alias("_s0")))
    out["stor_inout"] = pl.concat([s_in.select(["i", "v", "r", "t", "_s0", "Value"]),
                                   s_out.select(["i", "v", "r", "t", "_s0", "Value"])])

    # curt_h(r,allh,t) = sum(vre, cf * CAP) - sum(vre, GEN)
    vre = _members(case, "vre")
    avail = (CAP.filter(pl.col("i").is_in(vre))
             .join(_par(case, "slice_cap_coef", "cf"), on=["i", "v", "r", "t"], how="inner")
             .with_columns(pl.col("Value") * pl.col("cf"))
             .group_by(["r", "h", "t"]).agg(pl.col("Value").sum()))
    used = GEN.filter(pl.col("i").is_in(vre)).group_by(["r", "h", "t"]).agg(pl.col("Value").sum())
    out["curt_h"] = (pl.concat([avail, used.with_columns(-pl.col("Value"))])
                     .group_by(["r", "h", "t"]).agg(pl.col("Value").sum())
                     .rename({"h": "allh"}).select(["r", "allh", "t", "Value"]))

    # load_rt(r,t) = sum(h, hours * load_exog)
    out["load_rt"] = (_par(case, "load_exog_static").join(hours, on="h")
                      .with_columns(pl.col("Value") * pl.col("hours"))
                      .group_by(["r", "t"]).agg(pl.col("Value").sum()))

    # emissions: emit_r over representative hours, emit_irt over all h (as in report.gms)
    rate = _par(case, "emit_rate", "rate").join(tmodel, on="t", how="semi")
    gen_mwh = GEN.join(hours, on="h").with_columns((pl.col("Value") * pl.col("hours")).alias("mwh"))
    em = gen_mwh.join(rate, on=["i", "v", "r", "t"], how="inner").with_columns(
        (pl.col("mwh") * pl.col("rate")).alias("Value"))
    gwp = _par(case, "gwp", "gwp")

    def with_co2e(df, keys):
        co2e = (df.join(gwp, on="e", how="inner").with_columns(pl.col("Value") * pl.col("gwp"))
                .group_by([k for k in keys if k != "e"]).agg(pl.col("Value").sum())
                .with_columns(pl.lit("CO2e").alias("e")))
        return pl.concat([df.select(keys + ["Value"]), co2e.select(keys + ["Value"])]).rename({"e": "eall"})

    em_r = em.filter(pl.col("h").is_in(h_rep)).group_by(["etype", "e", "r", "t"]).agg(pl.col("Value").sum())
    out["emit_r"] = with_co2e(em_r, ["etype", "e", "r", "t"])
    out["emit_nat"] = out["emit_r"].group_by(["etype", "eall", "t"]).agg(pl.col("Value").sum())
    em_irt = em.group_by(["etype", "e", "i", "r", "t"]).agg(pl.col("Value").sum())
    out["emit_irt"] = with_co2e(em_irt, ["etype", "e", "i", "r", "t"])

    # prices: (1/cost_scale) * (1/pvf_onm) * marginal [/ hours]
    if "eq_annual_cap" in res["dual"]:
        cap_m = _scale_dual(_mar(res, "eq_annual_cap"), case)
        out["co2_price"] = cap_m.filter(pl.col("eall").str.to_uppercase() == "CO2").select(["t", "Value"])
    bal = _scale_dual(_mar(res, "eq_supply_demand_balance"), case)
    rp = [bal.join(hours, on="h").filter(pl.col("hours") != 0)
          .with_columns((pl.col("Value") / pl.col("hours")))
          .select(pl.lit("load").alias("_s0"), pl.lit("na").alias("_s1"), "r", pl.col("h").alias("_s2"), "t", "Value")]
    rp.append(bal.filter(pl.col("h").is_in(h_stress))
              .select(pl.lit("res_marg").alias("_s0"), pl.lit("na").alias("_s1"), "r",
                      pl.col("h").alias("_s2"), "t", "Value"))
    rp.append(bal.filter(pl.col("h").is_in(h_stress)).group_by(["r", "t"]).agg(pl.col("Value").sum())
              .select(pl.lit("res_marg_ann").alias("_s0"), pl.lit("na").alias("_s1"), "r",
                      pl.lit("ann").alias("_s2"), "t", "Value"))
    if "eq_annual_cap" in res["dual"]:
        rp.append(cap_m.join(case["r"], how="cross")
                  .select(pl.lit("annual_cap").alias("_s0"), pl.col("eall").alias("_s1"), "r",
                          pl.lit("ann").alias("_s2"), "t", "Value"))
    lc = _scale_dual(_mar(res, "eq_loadcon"), case)
    rp.append(lc.select(pl.lit("eq_loadcon").alias("_s0"), pl.lit("na").alias("_s1"), "r",
                        pl.col("h").alias("_s2"), "t", "Value"))
    out["reqt_price"] = pl.concat(rp)

    lh = LOAD.join(hours, on="h")
    rq = [lh.select(pl.lit("load").alias("_s0"), pl.lit("na").alias("_s1"), "r", pl.col("h").alias("_s2"), "t",
                    (pl.col("Value") * pl.col("hours")).alias("Value"))]
    st = LOAD.filter(pl.col("h").is_in(h_stress))
    rq.append(st.select(pl.lit("res_marg").alias("_s0"), pl.lit("na").alias("_s1"), "r",
                        pl.col("h").alias("_s2"), "t", "Value"))
    rq.append(st.group_by(["r", "t"]).agg(pl.col("Value").max())
              .select(pl.lit("res_marg_ann").alias("_s0"), pl.lit("na").alias("_s1"), "r",
                      pl.lit("ann").alias("_s2"), "t", "Value"))
    ann = lh.with_columns((pl.col("Value") * pl.col("hours")).alias("mwh")).group_by(["r", "t"]).agg(
        pl.col("mwh").sum())
    frac = ann.join(ann.group_by("t").agg(pl.col("mwh").sum().alias("tot")), on="t").with_columns(
        (pl.col("mwh") / pl.col("tot")).alias("frac"))
    ecap = _par(case, "emit_cap").join(tmodel, on="t", how="semi")
    rq.append(ecap.join(frac, on="t").select(
        pl.lit("annual_cap").alias("_s0"), pl.col("eall").alias("_s1"), "r", pl.lit("ann").alias("_s2"), "t",
        (pl.col("Value") * pl.col("frac")).alias("Value")))
    rq.append(LOAD.select(pl.lit("eq_loadcon").alias("_s0"), pl.lit("na").alias("_s1"), "r",
                          pl.col("h").alias("_s2"), "t", "Value"))
    out["reqt_quant"] = pl.concat(rq)

    # system-wide quantities and quantity-weighted prices
    sys_types = ["load", "res_marg", "res_marg_ann", "annual_cap"]
    q = out["reqt_quant"].filter(pl.col("_s0").is_in(sys_types))
    out["reqt_quant_sys"] = q.group_by(["_s0", "_s1", "_s2", "t"]).agg(pl.col("Value").sum())
    pq = (out["reqt_price"].filter(pl.col("_s0").is_in(sys_types))
          .join(q.rename({"Value": "q"}), on=["_s0", "_s1", "r", "_s2", "t"], how="inner")
          .with_columns((pl.col("Value") * pl.col("q")).alias("pq"))
          .group_by(["_s0", "_s1", "_s2", "t"]).agg(pl.col("pq").sum(), pl.col("q").sum())
          .filter(pl.col("q") != 0)
          .with_columns((pl.col("pq") / pl.col("q")).alias("Value")))
    out["reqt_price_sys"] = pq.select(["_s0", "_s1", "_s2", "t", "Value"])

    # transmission (report_calcs.calc_transmission)
    ce = _lvl(res, "CAPTRAN_ENERGY")
    cp = _lvl(res, "CAPTRAN_PRM")
    out["tran_cap_energy"] = ce
    out["tran_cap_prm"] = cp
    out["tran_out"] = _combine_forward_reverse(ce, "simult").with_columns(pl.col("Value") / 2)
    out["tran_prm_out"] = _combine_forward_reverse(cp, "simult").with_columns(pl.col("Value") / 2)
    if "INVTRAN" in res["primal"]:
        out["invtran_out"] = _lvl(res, "INVTRAN")
    flow = FLOW.rename({"h": "allh"})
    fcols = ["r", "rr", "allh", "trtype", "t", "Value"]
    out["tran_flow_all_rep"] = flow.filter(pl.col("allh").is_in(h_rep)).select(fcols)
    out["tran_flow_all_stress"] = flow.filter(pl.col("allh").is_in(h_stress)).select(fcols)
    net = _combine_forward_reverse(flow, "net")
    out["tran_flow_rep"] = net.filter(pl.col("allh").is_in(h_rep)).select(fcols)
    out["tran_flow_stress"] = net.filter(pl.col("allh").is_in(h_stress)).select(fcols)
    out["tran_flow_rep_ann"] = (out["tran_flow_rep"].join(hours.rename({"h": "allh"}), on="allh")
                                .with_columns(pl.col("Value") * pl.col("hours"))
                                .group_by(["r", "rr", "trtype", "t"]).agg(pl.col("Value").sum()))
    # losses_tran_h(rr,r,allh,trtype,t) = tranloss(rr,r) * FLOW(rr->r)
    loss = (FLOW.join(_par(case, "tranloss", "loss"), on=["r", "rr", "trtype"], how="inner")
            .with_columns(pl.col("Value") * pl.col("loss"))
            .select(pl.col("r").alias("rr"), pl.col("rr").alias("r"), pl.col("h").alias("allh"),
                    "trtype", "t", "Value"))
    out["losses_tran_h"] = loss

    # GAMS never stores zeros
    return {k: (v.filter(pl.col("Value") != 0) if k != "objfn_raw" else v) for k, v in out.items()}


# ---------------------------------------------------------------------- writers
def _to_pandas_reeds(df: pl.DataFrame) -> pd.DataFrame:
    """ReEDS dtypes: Value float32, years uint16, labels str; other numbers stay float64."""
    # polars treats "*" as a wildcard, so GAMS '*' domains are carried as _s0,_s1,_s2
    # and renamed here the way reeds.io.make_columns_unique names them.
    pdf = df.to_pandas().rename(columns={"_s0": "*", "_s1": "*.1", "_s2": "*.2"})
    for col in pdf.columns:
        if col == "Value":
            pdf[col] = pdf[col].astype(np.float32)
        elif col in ("t", "allt", "tt"):
            pdf[col] = pdf[col].astype(np.uint16)
        elif pd.api.types.is_numeric_dtype(pdf[col]):
            pdf[col] = pdf[col].astype(np.float64)
        else:
            pdf[col] = pdf[col].astype(str)
    return pdf


def write_reeds_h5(dfs: dict[str, pl.DataFrame], path: str | Path) -> Path:
    """Write in the layout of reeds.io.write_to_h5 so reeds.io.read_output can read it."""
    import h5py
    path = Path(path)
    if path.exists():
        path.unlink()
    with h5py.File(path, "w") as f:
        for key, df in dfs.items():
            pdf = _to_pandas_reeds(df)
            if not len(pdf):
                continue
            g = f.create_group(key)
            g.create_dataset("columns", data=pdf.columns.astype(str),
                             dtype=f"S{max(len(c) for c in pdf.columns)}")
            for col in pdf.columns:
                data = pdf[col]
                if not pd.api.types.is_numeric_dtype(data):
                    g.create_dataset(col, data=data.str.encode("utf-8"), dtype=f"S{max(1, data.str.len().max())}",
                                     compression="gzip", compression_opts=4)
                else:
                    g.create_dataset(col, data=data.values, dtype=data.dtype,
                                     compression="gzip", compression_opts=4)
    return path


def read_reeds_h5(path: str | Path, key: str) -> pd.DataFrame:
    """Same logic as reeds.io.read_h5, for checking the files without ReEDS installed."""
    import h5py
    with h5py.File(path, "r") as f:
        columns = [c.decode() for c in f[key]["columns"]]
        df = pd.DataFrame({c: f[key][c][()] for c in columns})
    for c in df:
        if df[c].dtype.kind in ("S", "O"):
            df[c] = df[c].str.decode("utf-8")
    return df


def write_outputs(dfs: dict[str, pl.DataFrame], outdir: str | Path, csv: bool = True) -> Path:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    write_reeds_h5(dfs, outdir / "outputs.h5")
    if csv:
        for key, df in dfs.items():
            _to_pandas_reeds(df).to_csv(outdir / f"{key}.csv", index=False)
    return outdir
