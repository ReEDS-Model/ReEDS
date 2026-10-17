from __future__ import annotations

import polars as pl

from .derive import isin, semi
from .report_core import Helpers, add, div, empty, mul, nz, scale, sub, total, val


def _forward(df: pl.DataFrame) -> pl.DataFrame:
    return df.filter(pl.col("r") < pl.col("rr"))


def _reverse(df: pl.DataFrame) -> pl.DataFrame:
    return df.filter(pl.col("r") > pl.col("rr")).rename({"r": "rr", "rr": "r"})


def _combine(df: pl.DataFrame, dims: list[str], net: bool) -> pl.DataFrame:
    rev = _reverse(df)
    if net:
        rev = scale(rev, -1.0)
    return add([_forward(df), rev], dims)


def interconnection_and_co2(H: Helpers, R: dict) -> None:
    S, C = H.S, H.C
    R["cap_above_limit"] = nz(H.L("CAP_ABOVE_LIM").select(["tg", "r", "t", "value"]))
    hrs = H.hours.rename({"hours": "value"})
    captured = H.L("CO2_CAPTURED")
    R["CO2_CAPTURED_out"] = nz(captured.select(["r", "h", "t", "value"]))
    R["CO2_CAPTURED_out_ann"] = nz(total(mul(captured, hrs, ["h"]), ["r", "t"]))
    stored = H.L("CO2_STORED")
    R["CO2_STORED_out"] = nz(stored.select(["r", "cs", "h", "t", "value"]))
    R["CO2_STORED_out_ann"] = nz(total(mul(stored, hrs, ["h"]), ["r", "cs", "t"]))
    R["CO2_TRANSPORT_INV_out"] = nz(H.L("CO2_TRANSPORT_INV").select(["r", "rr", "t", "value"]))
    R["CO2_SPURLINE_INV_out"] = nz(H.L("CO2_SPURLINE_INV").select(["r", "cs", "t", "value"]))
    flow = H.L("CO2_FLOW")
    dims = ["r", "rr", "h", "t"]
    out = _combine(flow, dims, net=False)
    R["CO2_FLOW_out"] = nz(out)
    R["CO2_FLOW_out_ann"] = nz(total(mul(out, hrs, ["h"]), ["r", "rr", "t"]))
    pos = _forward(flow).select(dims + ["value"])
    R["CO2_FLOW_pos_out"] = nz(pos)
    R["CO2_FLOW_pos_out_ann"] = nz(total(mul(pos, hrs, ["h"]), ["r", "rr", "t"]))
    neg = scale(_reverse(flow), -1.0).select(dims + ["value"])
    R["CO2_FLOW_neg_out"] = nz(neg)
    R["CO2_FLOW_neg_out_ann"] = nz(total(mul(neg, hrs, ["h"]), ["r", "rr", "t"]))
    net = _combine(flow, dims, net=True)
    R["CO2_FLOW_net_out"] = nz(net)
    R["CO2_FLOW_net_out_ann"] = nz(total(mul(net, hrs, ["h"]), ["r", "rr", "t"]))


def transmission_calcs(H: Helpers, R: dict) -> None:
    S, C = H.S, H.C
    rrt = ["r", "rr", "trtype", "t"]
    R["invtran_out"] = nz(H.L("INVTRAN").select(rrt + ["value"]))
    cap_e = H.L("CAPTRAN_ENERGY").select(rrt + ["value"])
    cap_p = H.L("CAPTRAN_PRM").select(rrt + ["value"])
    R["tran_cap_energy"] = nz(cap_e)
    R["tran_cap_prm"] = nz(cap_p)
    R["tran_cap_grp"] = nz(H.L("CAPTRAN_GRP").select(["transgrp", "transgrpp", "t", "value"]))
    tran_out = scale(_combine(cap_e, rrt, net=False), 0.5)
    tran_prm_out = scale(_combine(cap_p, rrt, net=False), 0.5)
    R["tran_out"] = nz(tran_out)
    R["tran_prm_out"] = nz(tran_prm_out)
    dist = S.distance
    R["tran_mi_out_detail"] = nz(mul(tran_out, dist, ["r", "rr", "trtype"]))
    R["tran_mi_out"] = nz(total(R["tran_mi_out_detail"], ["trtype", "t"]))
    R["tran_prm_mi_out"] = nz(total(mul(tran_prm_out, dist, ["r", "rr", "trtype"]), ["trtype", "t"]))
    R["cap_converter_out"] = nz(H.L("CAP_CONVERTER").select(["r", "t", "value"]))
    flow = H.L("FLOW").select(["r", "rr", "h", "trtype", "t", "value"])
    rep = H.rep(flow)
    stress = semi(flow, C.h_stress_t, ["h", "t"])
    R["tran_flow_all_rep"] = nz(rep)
    R["tran_flow_all_stress"] = nz(stress)
    dims = ["r", "rr", "h", "trtype", "t"]
    flow_rep_net = H.rep(_combine(flow, dims, net=True))
    R["tran_flow_rep"] = nz(flow_rep_net)
    R["tran_flow_stress"] = nz(semi(_combine(flow, dims, net=True), C.h_stress_t, ["h", "t"]))
    hrs = H.hours.rename({"hours": "value"})
    R["tran_flow_rep_ann"] = nz(total(mul(flow_rep_net, hrs, ["h"]), rrt))
    R["tran_util_h_rep"] = nz(div(rep, cap_e, rrt))
    R["tran_util_h_stress"] = nz(div(stress, cap_p, rrt))
    rep_hours_total = float(H.hours["hours"].sum())
    R["tran_util_ann_rep"] = nz(scale(total(mul(div(rep, cap_e, rrt), hrs, ["h"]), rrt), 1.0 / rep_hours_total))
    stress_hours = total(semi(C.hours_t, C.h_stress_t, ["h", "t"]), ["t"])
    util_s = total(mul(div(stress, cap_p, rrt), C.hours_t, ["h", "t"]), rrt)
    R["tran_util_ann_stress"] = nz(div(util_s, stress_hours, ["t"]))
