from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import polars as pl

from .derive import Symbols, isin, members
from .levels import Levels

V4 = ["i", "v", "r", "t"]

VAR_DIMS: dict[str, list[str]] = {
    "ACP_PURCHASES": ["rpscat", "st", "t"], "AVAIL_SITE": ["x", "h", "t"], "BIOUSED": ["bioclass", "r", "t"], "CAP": V4, "CAP_ABOVE_LIM": ["tg", "r", "t"],
    "CAP_CONVERTER": ["r", "t"], "CAP_ENERGY": V4, "CAP_LOADSITE": ["r", "t"], "CAP_RSC": ["i", "v", "r", "rscbin", "t"],
    "CAP_SDBIN": ["i", "v", "r", "ccseason", "sdbin", "t"], "CAP_SPUR": ["x", "t"], "CAPTRAN_ENERGY": ["r", "rr", "trtype", "t"],
    "CAPTRAN_GRP": ["transgrp", "transgrpp", "t"], "CAPTRAN_PRM": ["r", "rr", "trtype", "t"], "CCSFLEX_POW": ["i", "v", "r", "h", "t"],
    "CCSFLEX_POWREQ": ["i", "v", "r", "h", "t"], "CO2_CAPTURED": ["r", "h", "t"], "CO2_FLOW": ["r", "rr", "h", "t"],
    "CO2_SPURLINE_INV": ["r", "cs", "t"], "CO2_STORED": ["r", "cs", "h", "t"], "CO2_TRANSPORT_INV": ["r", "rr", "t"],
    "CONVERSION": ["r", "h", "intype", "outtype", "t"], "CREDIT_H2PTC": ["i", "v", "r", "h", "t"], "DROPPED": ["r", "h", "t"],
    "EMIT": ["etype", "e", "r", "t"], "EXCESS": ["r", "h", "t"], "FLEX": ["flex_type", "r", "h", "t"],
    "FLOW": ["r", "rr", "h", "t", "trtype"], "GASUSED": ["cendiv", "gb", "h", "t"], "GEN": ["i", "v", "r", "h", "t"],
    "GEN_PLANT": ["i", "v", "r", "h", "t"], "GROWTH_BIN": ["gbin", "i", "st", "t"], "H2_FLOW": ["r", "rr", "h", "t"],
    "H2_STOR_CAP": ["h2_stor", "r", "t"], "H2_STOR_IN": ["h2_stor", "r", "h", "t"], "H2_STOR_INV": ["h2_stor", "r", "t"],
    "H2_STOR_LEVEL": ["h2_stor", "r", "actualszn", "h", "t"], "H2_STOR_LEVEL_SZN": ["h2_stor", "r", "actualszn", "t"],
    "H2_STOR_OUT": ["h2_stor", "r", "h", "t"], "H2_TRANSPORT_INV": ["r", "rr", "t"], "INV": V4, "INV_CAP_UP": ["i", "v", "r", "rscbin", "t"],
    "INV_CONVERTER": ["r", "t"], "INV_ENER_UP": ["i", "v", "r", "rscbin", "t"], "INV_ENERGY": V4, "INV_POI": ["r", "t"],
    "INV_REFURB": V4, "INV_RSC": ["i", "v", "r", "rscbin", "t"], "INV_SPUR": ["x", "t"], "INVTRAN": ["r", "rr", "trtype", "t"],
    "LOAD": ["r", "h", "t"], "OP_LOADSITE": ["r", "h", "t"], "OPRES": ["ortype", "i", "v", "r", "h", "t"],
    "OPRES_FLOW": ["ortype", "r", "rr", "h", "t"], "PEAK_FLEX": ["r", "ccseason", "t"], "PRMTRADE": ["r", "rr", "trtype", "ccseason", "t"],
    "PRODUCE": ["p", "i", "v", "r", "h", "t"], "RAMPUP": ["i", "r", "h", "hh", "t"], "RECS": ["rpscat", "i", "st", "ast", "t"],
    "STORAGE_IN": ["i", "v", "r", "h", "t"], "STORAGE_IN_GRID": ["i", "v", "r", "h", "t"],
    "STORAGE_INTERDAY_DISPATCH": ["i", "v", "r", "h", "t"], "STORAGE_INTERDAY_LEVEL": ["i", "v", "r", "szn", "t"],
    "STORAGE_LEVEL": ["i", "v", "r", "h", "t"], "TRAN_CAPEX_BINS": ["r", "rr", "tscbin", "t"], "UPGRADES": V4,
    "UPGRADES_RETIRE": V4, "VGASBINQ_NATIONAL": ["fuelbin", "t"], "VGASBINQ_REGIONAL": ["fuelbin", "cendiv", "t"],
    "WAT": ["i", "v", "w", "r", "h", "t"], "WATCAP": V4,
}

EQ_DIMS: dict[str, list[str]] = {
    "eq_supply_demand_balance": ["r", "h", "t"], "eq_loadcon": ["r", "h", "t"], "eq_OpRes_requirement": ["ortype", "r", "h", "t"],
    "eq_REC_Requirement": ["rpscat", "st", "t"], "eq_national_gen": ["t"], "eq_annual_cap": ["eall", "t"],
    "eq_reserve_margin": ["r", "ccseason", "t"], "eq_RGGI_cap": ["t"], "eq_state_cap": ["st", "t"], "eq_bioused": ["r", "t"],
    "eq_biousedlimit": ["bioclass", "usda_region", "t"], "eq_h2_demand": ["p", "t"], "eq_h2_demand_regional": ["r", "h", "t"],
    "eq_h2_ptc_region_balance": ["h2ptcreg", "t"], "eq_h2_ptc_region_hour_balance": ["h2ptcreg", "h", "t"],
}

REDUCED_COST_VARIABLES = ("CAP", "INV", "INV_RSC")


def empty(dims: list[str]) -> pl.DataFrame:
    return pl.DataFrame({d: pl.Series([], dtype=pl.Utf8) for d in dims} | {"value": pl.Series([], dtype=pl.Float64)})


def _normalize(df: pl.DataFrame, dims: list[str], value_col: str) -> pl.DataFrame:
    missing = [d for d in dims if d not in df.columns]
    if missing:
        raise KeyError(f"columns {missing} are missing from a table with columns {df.columns}")
    out = df.select(dims + [pl.col(value_col).cast(pl.Float64).alias("value")])
    out = out.with_columns([pl.col(d).cast(pl.Utf8) for d in dims])
    return out.filter(pl.col("value") != 0.0)


@dataclass
class Ctx:
    S: Symbols
    years: list[int]
    lv: dict[str, pl.DataFrame]
    eqm: dict[str, pl.DataFrame]
    rc: dict[str, pl.DataFrame]
    h_t: pl.DataFrame
    h_stress_t: pl.DataFrame
    hours_t: pl.DataFrame
    prm: pl.DataFrame
    co2_emit_rate_r: pl.DataFrame
    z_rep: dict[int, float]
    objfn_raw: float
    absent_variables: list[str] = field(default_factory=list)
    absent_equations: list[str] = field(default_factory=list)

    def L(self, name: str) -> pl.DataFrame:
        if name not in VAR_DIMS:
            raise KeyError(f"{name} is not a variable the report knows")
        if name in self.lv:
            return self.lv[name]
        if name not in self.absent_variables:
            self.absent_variables.append(name)
        return empty(VAR_DIMS[name])

    def M(self, name: str) -> pl.DataFrame:
        if name not in EQ_DIMS:
            raise KeyError(f"{name} is not an equation the report knows")
        if name in self.eqm:
            return self.eqm[name]
        if name not in self.absent_equations:
            self.absent_equations.append(name)
        return empty(EQ_DIMS[name])

    def RC(self, name: str) -> pl.DataFrame:
        if name not in self.rc:
            raise KeyError(f"reduced costs of {name} were not stored")
        return self.rc[name]

    @property
    def tmodel_new(self) -> pl.DataFrame:
        return pl.DataFrame({"t": pl.Series([str(y) for y in self.years], dtype=pl.Utf8)})

    @property
    def tsolved(self) -> pl.DataFrame:
        return self.tmodel_new

    @property
    def tfirst(self) -> str:
        return str(self.years[0])

    @property
    def tlast(self) -> str:
        return str(self.years[-1])

    def yeart(self) -> pl.DataFrame:
        return self.tmodel_new.with_columns(pl.col("t").cast(pl.Int64).cast(pl.Float64).alias("value"))

    def tprev(self) -> pl.DataFrame:
        return pl.DataFrame({"t": [str(y) for y in self.years[1:]], "tt": [str(y) for y in self.years[:-1]]})

    def year_gap(self) -> pl.DataFrame:
        gaps = [float(self.years[0])] + [float(b - a) for a, b in zip(self.years[:-1], self.years[1:])]
        return pl.DataFrame({"t": [str(y) for y in self.years], "gap": gaps})


def from_store(S: Symbols, store: Levels, years: list[int]) -> Ctx:
    lv: dict[str, pl.DataFrame] = {}
    eqm: dict[str, pl.DataFrame] = {}
    rc: dict[str, pl.DataFrame] = {}
    keys = set(store.keys())
    for name, dims in VAR_DIMS.items():
        present = [y for y in years if f"var__{name}__{y}" in keys]
        if present:
            lv[name] = _normalize(store.variable(name, present), dims, "level")
    for name, dims in EQ_DIMS.items():
        present = [y for y in years if f"eq__{name}__{y}" in keys]
        if present:
            eqm[name] = _normalize(store.table("eq", name, present), dims, "marginal")
    for name in REDUCED_COST_VARIABLES:
        present = [y for y in years if f"rc__{name}__{y}" in keys]
        if not present:
            raise KeyError(f"reduced costs of {name} are not in {store.path}")
        rc[name] = _normalize(store.table("rc", name, present), VAR_DIMS[name], "marginal")

    def derived(name: str, dims: list[str], value: bool) -> pl.DataFrame:
        df = store.table("derived", name, years)
        if value:
            return _normalize(df, dims, "value")
        return df.select(dims).with_columns([pl.col(d).cast(pl.Utf8) for d in dims])

    z_rep = {y: float(store.meta(y)["objective"]) for y in years}
    return Ctx(S=S, years=years, lv=lv, eqm=eqm, rc=rc,
               h_t=derived("h_t", ["h", "t"], False), h_stress_t=derived("h_stress_t", ["h", "t"], False),
               hours_t=derived("hours_t", ["h", "t"], True), prm=derived("prm", ["r", "t"], True),
               co2_emit_rate_r=derived("co2_emit_rate_r", ["r", "t"], True),
               z_rep=z_rep, objfn_raw=z_rep[years[-1]])
