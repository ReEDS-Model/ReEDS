from __future__ import annotations

from pathlib import Path

import h5py
import pandas as pd
import polars as pl

import reeds

ROUND_VARIABLES = ["CAP", "CAP_ENERGY", "UPGRADES", "CAP_ABOVE_LIM", "INV", "INV_ENERGY", "INV_RSC", "INV_POI",
                   "H2_STOR_INV", "H2_TRANSPORT_INV"]

STATE_SPECS = {
    "state_INV": ("INV", ["i", "v", "r", "tt"]), "state_INV_ENERGY": ("INV_ENERGY", ["i", "v", "r", "tt"]),
    "state_INV_RSC": ("INV_RSC", ["i", "v", "r", "rscbin", "tt"]), "state_INVTRAN": ("INVTRAN", ["r", "rr", "trtype", "tt"]),
    "state_CAP": ("CAP", ["i", "v", "r", "tt"]), "state_UPGRADES": ("UPGRADES", ["i", "v", "r", "tt"]),
    "state_UPGRADES_RETIRE": ("UPGRADES_RETIRE", ["i", "v", "r", "tt"]), "state_INV_REFURB": ("INV_REFURB", ["i", "v", "r", "tt"]),
    "state_INV_CAP_UP": ("INV_CAP_UP", ["i", "v", "r", "rscbin", "tt"]), "state_INV_ENER_UP": ("INV_ENER_UP", ["i", "v", "r", "rscbin", "tt"]),
    "state_INVTRAN_AC": ("INVTRAN_AC", ["r", "rr", "tscbin", "tt"]), "state_INV_POI": ("INV_POI", ["r", "tt"]),
    "state_INV_CONVERTER": ("INV_CONVERTER", ["r", "tt"]), "state_INV_SPUR": ("INV_SPUR", ["x", "tt"]),
    "state_growth_bin_limit": ("growth_bin_limit", ["gbin", "st", "tg", "tt"]),
    "state_co2_emit_rate_r": ("co2_emit_rate_r", ["r", "tt"]), "state_prm": ("prm", ["r", "tt"]),
    "state_H2_STOR_INV": ("H2_STOR_INV", ["h2_stor", "r", "tt"]), "state_H2_TRANSPORT_INV": ("H2_TRANSPORT_INV", ["r", "rr", "tt"]),
}


VALUE_COLUMNS = ("level", "marginal", "value")

DERIVED_STATE = {"co2_emit_rate_r", "prm", "growth_bin_limit"}


def _to_pandas(df: pl.DataFrame) -> pd.DataFrame:
    out = df.to_pandas()
    for col in out.columns:
        if col == "t":
            out[col] = out[col].astype(int)
        elif col in VALUE_COLUMNS:
            out[col] = out[col].astype(float)
        else:
            out[col] = out[col].astype(str)
    return out


def _to_polars(df: pd.DataFrame) -> pl.DataFrame:
    out = pl.from_pandas(df)
    casts = [pl.col("t").cast(pl.Int64)] if "t" in out.columns else []
    casts += [pl.col(c).cast(pl.Float64) for c in VALUE_COLUMNS if c in out.columns]
    casts += [pl.col(c).cast(pl.Utf8) for c in out.columns if c != "t" and c not in VALUE_COLUMNS]
    return out.with_columns(casts) if casts else out


class Levels:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def keys(self) -> list[str]:
        if not self.path.is_file():
            return []
        with h5py.File(self.path, "r") as f:
            return list(f.keys())

    def years(self) -> list[int]:
        return sorted({int(k.split("__")[1]) for k in self.keys() if k.startswith("meta__")})

    def _write(self, key: str, df: pd.DataFrame, attrs: dict) -> None:
        reeds.io.write_to_h5(df, key, str(self.path), attrs=attrs, overwrite=True)

    def _read(self, key: str) -> pl.DataFrame:
        return _to_polars(reeds.io.read_h5(self.path, key))

    def has_year(self, year: int) -> bool:
        return f"meta__{year}" in self.keys()

    def save_year(self, year: int, iteration: int, objective: float, status: str,
                  variables: dict[str, pl.DataFrame], equations: dict[str, pl.DataFrame], derived: dict[str, pl.DataFrame],
                  reduced: dict[str, pl.DataFrame] | None = None) -> None:
        stale = [k for k in self.keys() if k.endswith(f"__{year}")]
        if stale:
            with h5py.File(self.path, "a") as f:
                for k in stale:
                    del f[k]
        for name, df in variables.items():
            self._write(f"var__{name}__{year}", _to_pandas(df), {"kind": "variable", "name": name, "year": year})
        for name, df in equations.items():
            self._write(f"eq__{name}__{year}", _to_pandas(df), {"kind": "equation", "name": name, "year": year})
        for name, df in derived.items():
            self._write(f"derived__{name}__{year}", _to_pandas(df), {"kind": "derived", "name": name, "year": year})
        for name, df in (reduced or {}).items():
            self._write(f"rc__{name}__{year}", _to_pandas(df), {"kind": "reduced_cost", "name": name, "year": year})
        meta = pd.DataFrame({"name": ["objective", "iteration"], "value": [float(objective), float(iteration)]})
        self._write(f"meta__{year}", meta, {"kind": "meta", "year": year, "status": status})

    def meta(self, year: int) -> dict:
        df = self._read(f"meta__{year}")
        return dict(zip(df["name"].to_list(), df["value"].to_list()))

    def table(self, kind: str, name: str, years: list[int] | None = None) -> pl.DataFrame:
        if years is None:
            years = self.years()
        parts = []
        for y in sorted(years):
            key = f"{kind}__{name}__{y}"
            if key in self.keys():
                parts.append(self._read(key).with_columns(pl.lit(y).alias("_solve_year")))
        if not parts:
            raise KeyError(f"{kind} {name} has no rows for years {years} in {self.path}")
        out = pl.concat(parts, how="vertical_relaxed")
        index = [c for c in out.columns if c not in VALUE_COLUMNS and c != "_solve_year"]
        out = out.sort("_solve_year").unique(subset=index, keep="last", maintain_order=True)
        return out.drop("_solve_year")

    def variable(self, name: str, years: list[int] | None = None) -> pl.DataFrame:
        return self.table("var", name, years)

    def has(self, kind: str, name: str, year: int) -> bool:
        return f"{kind}__{name}__{year}" in self.keys()


def round_small(df: pl.DataFrame, tolerance: float) -> pl.DataFrame:
    return df.with_columns(pl.when(pl.col("level").abs() < tolerance).then(0.0).otherwise(pl.col("level")).alias("level"))


def state_tables(levels: Levels, tfix_years: list[int], remove_small_numbers: bool, rhs_tolerance: float) -> dict[str, pl.DataFrame]:
    out: dict[str, pl.DataFrame] = {}
    for state_name, (symbol, dims) in STATE_SPECS.items():
        kind = "derived" if symbol in DERIVED_STATE else "var"
        present = [y for y in tfix_years if levels.has(kind, symbol, y)]
        if not present:
            out[state_name] = pl.DataFrame({d: pl.Series([], dtype=pl.Utf8) for d in dims} | {"value": pl.Series([], dtype=pl.Float64)})
            continue
        df = levels.table(kind, symbol, present)
        value_col = "level" if "level" in df.columns else "value"
        df = df.rename({value_col: "level"})
        if remove_small_numbers and symbol in ROUND_VARIABLES:
            df = round_small(df, rhs_tolerance)
        df = (df.rename({"t": "tt", "level": "value"}).with_columns(pl.col("tt").cast(pl.Utf8))
              .filter(pl.col("value") != 0.0).select(dims + ["value"]))
        out[state_name] = df
    raw_dims = ["i", "v", "r", "tt"]
    present = [y for y in tfix_years if levels.has("var", "UPGRADES", y)]
    if present:
        raw = levels.table("var", "UPGRADES", present).rename({"t": "tt", "level": "value"})
        out["state_UPGRADES_unrounded"] = (raw.with_columns(pl.col("tt").cast(pl.Utf8)).filter(pl.col("value") != 0.0).select(raw_dims + ["value"]))
    else:
        out["state_UPGRADES_unrounded"] = pl.DataFrame({d: pl.Series([], dtype=pl.Utf8) for d in raw_dims} | {"value": pl.Series([], dtype=pl.Float64)})
    return out
