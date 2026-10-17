from __future__ import annotations

import math
from pathlib import Path

import h5py
import numpy as np
import polars as pl


def gams_round(x: pl.Expr, n: int) -> pl.Expr:
    scale = 10.0 ** n
    return (pl.when(x >= 0)
            .then((x * scale + 0.5).floor() / scale)
            .otherwise(-((-x) * scale + 0.5).floor() / scale))


def gams_round_float(x: float, n: int) -> float:
    scale = 10.0 ** n
    if x >= 0:
        return math.floor(x * scale + 0.5) / scale
    return -math.floor(-x * scale + 0.5) / scale


class CaseInsensitiveDict(dict):
    def __init__(self, items):
        super().__init__({str(k).lower(): v for k, v in dict(items).items()})

    def __getitem__(self, key):
        return super().__getitem__(str(key).lower())

    def __contains__(self, key):
        return super().__contains__(str(key).lower())

    def get(self, key, default=None):
        return super().get(str(key).lower(), default)


class Inputs:
    def __init__(self, h5path: str | Path):
        self.path = Path(h5path)
        self._cache: dict[str, pl.DataFrame] = {}
        with h5py.File(self.path, "r") as f:
            self.keys = set(f)
            self.gamstype = {k: f[k].attrs["gamstype"] for k in f}

    def __contains__(self, key: str) -> bool:
        return key in self.keys

    def raw(self, key: str) -> pl.DataFrame:
        if key in self._cache:
            return self._cache[key]
        if key not in self.keys:
            raise KeyError(f"{key} is not in {self.path}")
        with h5py.File(self.path, "r") as f:
            g = f[key]
            columns = [c.decode() for c in g["columns"]]
            data = {}
            for c in columns:
                if c in g:
                    arr = g[c][()]
                    if arr.dtype.kind in ("S", "O"):
                        data[c] = pl.Series(c, [x.decode() if isinstance(x, bytes) else str(x) for x in arr])
                    else:
                        data[c] = pl.Series(c, arr)
                else:
                    data[c] = pl.Series(c, [], dtype=pl.Utf8)
            df = pl.DataFrame(data)
        df = df.rename({c: f"_s{k}" for k, c in enumerate(df.columns) if c.startswith("*")})
        self._cache[key] = df
        return df

    def set(self, key: str, dims: list[str]) -> pl.DataFrame:
        df = self.raw(key)
        cols = list(df.columns[: len(dims)])
        df = df.select(cols).rename(dict(zip(cols, dims)))
        return df.with_columns([pl.col(d).cast(pl.Utf8).str.strip_chars().str.to_lowercase() for d in dims]).unique(maintain_order=True)

    def par(self, key: str, dims: list[str]) -> pl.DataFrame:
        df = self.raw(key)
        cols = list(df.columns[: len(dims)])
        value_col = [c for c in df.columns if c.lower() == "value"][-1]
        df = df.select(cols + [value_col]).rename(dict(zip(cols + [value_col], dims + ["value"])))
        df = df.with_columns([pl.col(d).cast(pl.Utf8).str.strip_chars().str.to_lowercase() for d in dims]
                             + [pl.col("value").cast(pl.Float64)])
        return df.filter(pl.col("value") != 0.0).unique(subset=dims, keep="last", maintain_order=True)

    def label_case(self) -> dict[str, str]:
        if hasattr(self, "_label_case"):
            return self._label_case
        out: dict[str, str] = {}
        with h5py.File(self.path, "r") as f:
            for key in sorted(f):
                g = f[key]
                for c in [c.decode() for c in g["columns"]]:
                    if c.lower() == "value" or c not in g:
                        continue
                    arr = g[c][()]
                    if arr.dtype.kind not in ("S", "O"):
                        continue
                    for x in arr:
                        label = x.decode() if isinstance(x, bytes) else str(x)
                        low = label.strip().lower()
                        if low and low not in out:
                            out[low] = label.strip()
        self._label_case = out
        return out

    def switches(self) -> dict[str, str]:
        df = self.raw("switches")
        return CaseInsensitiveDict(zip(df[df.columns[0]].to_list(), df[df.columns[1]].to_list()))

    def scalars(self, key: str) -> dict[str, float]:
        df = self.raw(key)
        return CaseInsensitiveDict(zip(df[df.columns[0]].to_list(), df["value"].cast(pl.Float64).to_list()))


def members(df: pl.DataFrame) -> set:
    return set(df[df.columns[0]].to_list())


def one_col(values, name: str) -> pl.DataFrame:
    return pl.DataFrame({name: pl.Series(sorted(values), dtype=pl.Utf8)})


def cross(*dfs: pl.DataFrame) -> pl.DataFrame:
    out = dfs[0]
    for df in dfs[1:]:
        out = out.join(df, how="cross")
    return out


def semi(df: pl.DataFrame, other: pl.DataFrame, on: list[str] | None = None) -> pl.DataFrame:
    on = on or [c for c in other.columns if c in df.columns]
    return df.join(other.select(on).unique(), on=on, how="semi")


def anti(df: pl.DataFrame, other: pl.DataFrame, on: list[str] | None = None) -> pl.DataFrame:
    on = on or [c for c in other.columns if c in df.columns]
    return df.join(other.select(on).unique(), on=on, how="anti")


def isin(col: str, values) -> pl.Expr:
    return pl.col(col).is_in(list(values))


def lookup(df: pl.DataFrame, par: pl.DataFrame, on: list[str], name: str, fill: float | None = 0.0) -> pl.DataFrame:
    out = df.join(par.select(on + ["value"]).rename({"value": name}), on=on, how="left")
    if fill is not None:
        out = out.with_columns(pl.col(name).fill_null(fill))
    return out


def fsum_by(df: pl.DataFrame, keys: list[str], col: str = "value") -> pl.DataFrame:
    grouped = df.group_by(keys).agg(pl.col(col))
    return grouped.with_columns(pl.col(col).map_elements(lambda xs: math.fsum(xs), return_dtype=pl.Float64))


def nonzero(df: pl.DataFrame) -> pl.DataFrame:
    return df.filter(pl.col("value") != 0.0)


def year_int(df: pl.DataFrame, cols=("t", "tt", "allt")) -> pl.DataFrame:
    return df.with_columns([pl.col(c).cast(pl.Int64) for c in cols if c in df.columns])


def year_str(df: pl.DataFrame, cols=("t", "tt", "allt")) -> pl.DataFrame:
    return df.with_columns([pl.col(c).cast(pl.Utf8) for c in cols if c in df.columns])


class Symbols(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as e:
            raise AttributeError(name) from e


def derive(h5path: str | Path, year: int, stress_year: str, state: dict[str, pl.DataFrame] | None = None) -> Symbols:
    I = Inputs(h5path)
    S = Symbols()
    sw = I.scalars("gswitches")
    sc = I.scalars("scalars")
    S["sw"], S["sc"] = sw, sc
    S["csw"] = I.switches()
    S["year"] = year
    S["_inputs"] = I

    # ---------------------------------------------------------------- base sets
    S["i"] = I.set("i", ["i"])
    S["v"] = I.set("v", ["v"])
    S["r"] = I.set("r", ["r"])
    S["t"] = I.set("t", ["t"])
    S["allt"] = I.set("allt", ["allt"])
    S["initv"] = I.set("initv", ["v"])
    S["newv"] = I.set("newv", ["v"])
    S["tmodel_new"] = I.set("tmodel_new", ["t"])
    S["offshore"] = I.set("offshore", ["r"])
    S["land"] = anti(S.r, S.offshore)
    S["etype"] = I.set("etype", ["etype"])
    S["e"] = I.set("e", ["e"])
    S["eall"] = I.set("eall", ["eall"])
    S["trtype"] = I.set("trtype", ["trtype"])
    S["aclike"] = I.set("aclike", ["trtype"])
    S["lcclike"] = I.set("lcclike", ["trtype"])
    S["notvsc"] = I.set("notvsc", ["trtype"])
    S["quarter"] = I.set("quarter", ["quarter"])
    S["c"] = I.set("c", ["c"])
    S["i_c"] = I.set("i_c", ["i", "c"])
    S["f"] = I.set("f", ["f"])
    S["fuel2tech"] = I.set("fuel2tech", ["f", "i"])
    S["tg_rsc_upvagg"] = I.set("tg_rsc_upvagg", ["i", "ii"])
    S["gwp"] = I.par("gwp", ["e"])

    years = sorted(int(x) for x in members(S.tmodel_new))
    S["years"] = years
    S["tmodel"] = one_col([str(year)], "t")
    S["tfix"] = one_col([str(y) for y in years if y < year], "t")
    S["tfirst"] = one_col([str(years[0])], "t")
    S["tprev"] = pl.DataFrame({"t": [str(y) for y in years[1:]], "tt": [str(y) for y in years[:-1]]})
    numbins = int(S.csw["numbins"])
    S["rscbin"] = pl.DataFrame({"rscbin": pl.Series([f"bin{k}" for k in range(1, numbins + 1)], dtype=pl.Utf8)})

    # ---------------------------------------------------------------- timeslices
    rep = lambda k, dims: I.set(f"rep__{k}", dims)  # noqa: E731
    stress = lambda k, dims: I.set(f"stress__{k}__{stress_year}", dims)  # noqa: E731
    S["h_rep"] = rep("set_h", ["h"])
    S["h_stress"] = stress("set_h", ["h"])
    S["h"] = pl.concat([S.h_rep, S.h_stress]).unique(maintain_order=True)
    S["szn_rep"] = rep("set_szn", ["szn"])
    S["szn_stress"] = stress("set_szn", ["szn"])
    S["szn"] = pl.concat([S.szn_rep, S.szn_stress]).unique(maintain_order=True)
    S["h_szn"] = pl.concat([rep("h_szn", ["h", "szn"]), stress("h_szn", ["h", "szn"])]).unique(maintain_order=True)
    S["nexth"] = pl.concat([rep("nexth", ["h", "hh"]), stress("nexth", ["h", "hh"])]).unique(maintain_order=True)
    hours = pl.concat([I.par(f"rep__numhours", ["h"]), I.par(f"stress__numhours__{stress_year}", ["h"])])
    S["hours_raw"] = semi(hours, S.h)
    S["hours"] = S.hours_raw.with_columns(gams_round(pl.col("value"), 3).alias("value"))
    S["hours_daily"] = pl.concat([
        S.h_rep.with_columns(pl.lit(float(sw["Sw_HourlyChunkLengthRep"])).alias("value")),
        S.h_stress.with_columns(pl.lit(float(sw["Sw_HourlyChunkLengthStress"])).alias("value")),
    ])
    fhq = pl.concat([I.par("rep__frac_h_quarter_weights", ["h", "quarter"]),
                     I.par(f"stress__frac_h_quarter_weights__{stress_year}", ["h", "quarter"])])
    S["frac_h_quarter_weights"] = semi(fhq, S.h)
    n_h_szn = S.h_szn.group_by("szn").agg(pl.len().alias("n"))
    S["szn_quarter_weights"] = (S.h_szn.join(S.frac_h_quarter_weights, on="h", how="inner")
                                .group_by(["szn", "quarter"]).agg(pl.col("value").sum())
                                .join(n_h_szn, on="szn").with_columns((pl.col("value") / pl.col("n")).alias("value"))
                                .select(["szn", "quarter", "value"]))
    climate_final = I.par("climate_heuristics_finalyear", ["climate_param"])
    climate_yearfrac = I.par("climate_heuristics_yearfrac", ["allt"])
    S["climate_heuristics_finalyear"] = dict(zip(climate_final["climate_param"], climate_final["value"]))
    S["climate_heuristics_yearfrac"] = dict(zip(climate_yearfrac["allt"], climate_yearfrac["value"]))
    tcd = S.climate_heuristics_finalyear.get("trans_summer_cap_delta", 0.0) * S.climate_heuristics_yearfrac.get(str(year), 0.0)
    S["trans_cap_delta"] = (S.frac_h_quarter_weights.filter(pl.col("quarter") == "summ")
                            .with_columns((pl.lit(tcd) * pl.col("value")).alias("value"), pl.lit(str(year)).alias("t"))
                            .select(["h", "t", "value"]))

    # ---------------------------------------------------------------- hierarchy
    hier = I.set("hierarchy", ["r", "nercr", "transreg", "transgrp", "cendiv", "st", "interconnect", "country",
                               "usda_region", "h2ptcreg", "hurdlereg", "gasreg", "ccreg"])
    S["hierarchy"] = hier
    for col in ["nercr", "transreg", "transgrp", "cendiv", "st", "interconnect", "country", "usda_region", "h2ptcreg", "hurdlereg", "ccreg"]:
        S[f"r_{col}"] = hier.select(["r", col]).unique()
    S["r_st"] = hier.select(["r", "st"]).unique()
    S["stfeas"] = S.r_st.select("st").unique()

    # ---------------------------------------------------------------- upgrades and bans
    upgrade_link = I.set("upgrade_link", ["i", "ii", "iii"])
    if int(sw["Sw_WaterMain"]) == 1:
        raise NotImplementedError("Sw_WaterMain=1 is not ported")
    S["upgrade_link"] = upgrade_link
    ban = set(x.lower() for x in [
        "upv_10", "csp-ns", "other", "unknown", "geothermal", "hydro", "pumped-hydro-flex", "hydED_pumped-hydro-flex",
        "CoalOldUns_CoalOldScr", "CoalOldUns_CofireOld", "CoalOldScr_CofireOld"])
    ban |= {f"csp3_{k}" for k in range(1, 13)} | {f"csp4_{k}" for k in range(1, 13)}
    if int(sw["Sw_HydroCapEnerUpgradeType"]) != 1:
        ban |= {"hydud", "hydund"}
    if int(sw["Sw_HydroAddPumpDispUpgSwitch"]) == 0:
        ban |= {"hydend_hyded", "hyded_pumped-hydro"}
    bannew = set(x.lower() for x in ["can-imports", "hydro", "distpv", "geothermal", "cofireold", "CoalOldScr", "CoalOldUns",
                                      "csp-ns", "HydEND", "HydED"])
    upgrade = set(upgrade_link["i"].to_list())
    if not int(sw["Sw_Upgrades"]):
        ban |= upgrade
        bannew |= upgrade
    subsets = I.par("tech-subset-table", ["i", "i_subtech"]).with_columns(pl.col("i_subtech").str.to_lowercase())
    if int(sw["Sw_Upgrades"]):
        upgrade_to0 = upgrade_link.select(["i", pl.col("iii").alias("ii")]).unique()
        expanded = (upgrade_to0.join(subsets.rename({"i": "ii"}), on="ii", how="inner")
                    .group_by(["i", "i_subtech"]).agg(pl.col("value").sum()).filter(pl.col("value") != 0))
        subsets = pl.concat([subsets.filter(~isin("i", upgrade)), expanded.select(["i", "i_subtech", "value"])])

    def subset(name: str) -> set:
        return set(subsets.filter(pl.col("i_subtech") == name.lower())["i"].to_list())

    def switch_bans():
        rules = [
            ("Sw_BECCS", 0, {"beccs_mod", "beccs_max"}), ("Sw_Biopower", 0, {"biopower"}),
            ("Sw_CCSFLEX_BYP", 0, {"gas-cc-ccs-f1", "coal-ccs-f1"}), ("Sw_CCSFLEX_STO", 0, {"gas-cc-ccs-f2", "coal-ccs-f2"}),
            ("Sw_CCSFLEX_DAC", 0, {"gas-cc-ccs-f3", "coal-ccs-f3"}), ("Sw_CoalIGCC", 0, {"coal-igcc"}),
            ("Sw_CoalNew", 0, {"coal-new"}), ("Sw_CofireNew", 0, {"cofirenew"}), ("Sw_DAC_Gas", 0, {"dac_gas"}),
            ("Sw_GasCT_Aero", 0, {"gas-ct_aero"}),
            ("Sw_GasCC_H_1x1", 0, {"gas-cc_h_1x1", "gas-cc_h_1x1-ccs_mod", "gas-cc_h_1x1-ccs_max"}),
            ("Sw_GasCC_H_2x1", 0, {"gas-cc_h_2x1", "gas-cc_h_2x1-ccs_mod", "gas-cc_h_2x1-ccs_max"}),
            ("Sw_GasFuelCell", 0, {"ng-fuel-cell"}), ("Sw_H2FuelCell", 0, {"h2-fuel-cell"}), ("Sw_LfillGas", 0, {"lfill-gas"}),
            ("Sw_NuclearSMR", 0, {"nuclear-smr"}),
        ]
        out = set()
        for name, value, techs in rules:
            if int(sw[name]) == value:
                out |= techs
        if int(sw["Sw_Canada"]) != 1:
            out |= {"can-imports"}
        subset_rules = [
            ("Sw_CCS", 0, "ccs"), ("Sw_CSP", 0, "csp"), ("Sw_CSP", 1, "csp2"), ("Sw_DAC", 0, "dac"), ("Sw_EVMC", 0, "evmc"),
            ("Sw_Geothermal", 0, "geo"), ("Sw_Geothermal", 1, "geo_extra"), ("Sw_H2", 0, "h2"), ("Sw_H2_SMR", 0, "smr"),
            ("Sw_H2Combustion", 0, "h2_combustion"), ("Sw_H2CombinedCycle", 0, "h2_cc"), ("Sw_MaxCaptureCCSTechs", 0, "ccs_max"),
            ("Sw_OfsWind", 0, "ofswind"), ("Sw_DRShed", 0, "dr_shed"),
        ]
        for name, value, sub in subset_rules:
            if int(sw[name]) == value:
                out |= subset(sub)
        if int(sw["Sw_H2Combustionupgrade"]) == 0:
            out |= subset("h2_combustion") & upgrade
        return out

    ban |= switch_bans()
    if int(sw["Sw_Nuclear"]) == 0:
        bannew |= subset("nuclear")
    if int(sw["Sw_OnsWind6to10"]) == 0:
        bannew |= {f"wind-ons_{k}" for k in range(6, 11)}
    hybrid = int(sw["Sw_HybridPlant"])
    if hybrid == 0:
        ban |= subset("storage_hybrid")
    elif hybrid == 1:
        ban |= subset("storage_hybrid") - {"csp_storage"}
        ban -= subset("csp_storage")
    elif hybrid == 2:
        ban -= subset("storage_hybrid") - {"csp_storage"}
        ban |= subset("csp_storage")
    elif hybrid == 3:
        ban -= subset("storage_hybrid") - {"csp_storage"}
    if int(sw["Sw_PVB"]) == 0:
        ban |= subset("pvb")
        bannew |= subset("pvb")
    if int(sw["Sw_PVB"]) != 0:
        raise NotImplementedError("Sw_PVB=1 is not ported (GSw_PVB_Types bans)")
    if int(sw["Sw_Storage"]) == 0:
        ban |= subset("storage_standalone")
    S["Sw_BatteryMandate"] = int(sw["Sw_BatteryMandate"]) if int(sw["Sw_Storage"]) else 0
    i_c = S.i_c
    missing_class = anti(S.i, i_c)
    S["i_c"] = pl.concat([i_c, missing_class.with_columns(pl.lit("0").alias("c"))]).unique(maintain_order=True)
    S["resourceclassnum"] = {c: float(c) for c in members(S.c)}
    if float(sw["Sw_NumCSPclasses"]) < 12:
        ban |= {i for i in subset("csp") if any(float(c) > float(sw["Sw_NumCSPclasses"]) for c in S.i_c.filter(pl.col("i") == i)["c"].to_list() if c != "0")}
    if int(sw["Sw_CSPRemoveLow"]) == 1:
        ban |= {i for i in subset("csp") if any(float(c) == float(sw["Sw_NumCSPclasses"]) for c in S.i_c.filter(pl.col("i") == i)["c"].to_list() if c != "0")}
    if float(sw["Sw_NumGeoclasses"]) < 10:
        ban |= {i for i in subset("geo") if any(float(c) > float(sw["Sw_NumGeoclasses"]) for c in S.i_c.filter(pl.col("i") == i)["c"].to_list() if c != "0")}
    S["nuclear_ba_ban"] = I.set("nuclear_ba_ban_list", ["r"])
    S["tech_banned"] = I.par("techs_banned", ["i", "r"])
    upgrade_link = upgrade_link.filter(~isin("i", ban) & ~isin("ii", ban) & ~isin("iii", ban))
    S["upgrade_link"] = upgrade_link
    S["upgrade"] = one_col(set(upgrade_link["i"].to_list()), "i")
    S["upgrade_to"] = upgrade_link.select(["i", pl.col("iii").alias("ii")]).unique()
    S["upgrade_from"] = upgrade_link.select(["i", "ii"]).unique()
    S["ban"] = one_col(ban, "i")
    S["bannew"] = one_col(bannew, "i")
    all_i = members(S.i)
    for name in ["battery", "beccs", "bio", "boiler", "canada", "ccs", "ccs_mod", "ccs_max", "ccsflex_byp", "ccsflex_dac",
                 "ccsflex_sto", "ccsflex", "cf_tech", "coal_ccs", "coal", "cofire", "combined_cycle", "combustion_turbine",
                 "consume", "conv", "temp_derate", "csp_storage", "csp", "csp1", "csp2", "csp3", "csp4", "dac", "distpv",
                 "dr_shed", "demand_flex", "evmc", "evmc_storage", "evmc_shape", "fossil", "ng_fuel_cell", "gas_cc_ccs",
                 "gas_cc", "gas_ct", "gas", "gentech", "geo", "geo_base", "geo_hydro", "geo_egs", "geo_extra",
                 "geo_egs_allkm", "geo_egs_nf", "h2_combustion", "h2_cc", "h2_ct", "h2", "h2_fuel_cell", "h2_gen",
                 "hydro_d", "hydro_nd", "hydro", "lfill", "nondispatch", "nuclear", "ofswind", "ogs", "onswind", "psh",
                 "pv", "pvb", "pvb1", "pvb2", "pvb3", "re", "refurbtech", "smr", "storage_hybrid",
                 "storage_interday", "storage_standalone", "storage", "thermal_storage", "upv", "vre_distributed",
                 "vre_no_csp", "vre_utility", "vre", "wind"]:
        key = "rsc" if name == "rsc_i" else name
        S[name] = one_col((subset(key) & all_i) - ban, "i")
    S["rsc_i"] = one_col((subset("rsc") & all_i) - ban, "i")
    S["hyd_add_pump"] = one_col({"hyded_pumped-hydro", "hyded_pumped-hydro-flex"} & all_i, "i")
    if int(sw["Sw_InterDayLinkage"]) == 0:
        S["storage_interday"] = one_col(set(), "i")
    S["coal_noccs"] = one_col(members(S.coal) - members(S.ccs), "i")
    S["dispatchtech"] = one_col(all_i - members(S.vre) - members(S.hydro_nd) - ban, "i")
    S["sccapcosttech"] = one_col(members(S.hydro) | members(S.psh) | members(S.dr_shed), "i")
    S["spur_techs"] = one_col(set(), "i")
    if int(sw["Sw_SpurScen"]) == 1:
        spur = members(S.onswind) | members(S.upv)
        if S.csw["geohydrosupplycurve"] == "reV":
            spur |= members(S.geo_hydro)
        if S.csw["egssupplycurve"] == "reV":
            spur |= members(S.geo_egs_allkm)
        S["spur_techs"] = one_col(spur - ban, "i")
    S["x"] = I.set("x", ["x"])
    S["x_r"] = I.set("x_r", ["x", "r"])
    S["xfeas"] = one_col(members(S.x_r.select("x")), "x")
    S["spurline_sitemap"] = I.set("spurline_sitemap", ["i", "r", "rscbin", "x"])
    S["spurline_cost"] = I.par("spurline_cost", ["x"])
    rsc = members(S.rsc_i)
    rsc_agg = pl.DataFrame({"i": sorted(rsc), "ii": sorted(rsc)})
    S["tg_rsc_cspagg"] = I.set("tg_rsc_cspagg", ["i", "ii"])
    rsc_agg = pl.concat([rsc_agg, S.tg_rsc_cspagg, S.tg_rsc_upvagg,
                         pl.DataFrame({"i": ["pumped-hydro"] * len(members(S.psh)), "ii": sorted(members(S.psh))})]).unique()
    S["rsc_agg"] = rsc_agg.filter(~isin("i", ban) & ~isin("ii", ban))
    from .derive_capacity import capacity
    from .derive_costs import costs, gas_curve
    from .derive_temporal import slice_coefficients, temporal
    from .derive_state import adjust_capacity_exog_for_upgrades, adjust_costs_for_upgrades
    capacity(S)
    costs(S)
    gas_curve(S)
    if state is not None:
        adjust_costs_for_upgrades(S, state["state_UPGRADES_unrounded"])
    temporal(S, stress_year, state)
    if state is not None:
        adjust_capacity_exog_for_upgrades(S, state["state_UPGRADES"], [y for y in S.years if y <= year])
    slice_coefficients(S)
    from .derive_ops import operations
    operations(S, stress_year)
    from .derive_ops import transmission, policies, growth, hydrogen
    transmission(S)
    policies(S)
    growth(S, state)
    hydrogen(S, stress_year)
    return S
