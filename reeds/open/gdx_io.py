from __future__ import annotations

from pathlib import Path

import gams.transfer as gt
import polars as pl

from .contract import SCHEMA, Case, from_tables

GDX_NAME = {
    "scalars": "slice_scalars",
    "co2_state_cap": "state_cap",
}

FIELDS = ("level", "marginal", "lower", "upper", "scale")


def records(container: gt.Container, name: str) -> pl.DataFrame | None:
    if name not in container:
        raise KeyError(f"{name} is not in the GDX file")
    sym = container[name]
    df = sym.records
    if df is None:
        return None
    df = df.copy()
    for col in df.columns:
        if str(df[col].dtype) == "category":
            df[col] = df[col].astype(str)
    return pl.from_pandas(df)


def contract_table(container: gt.Container, name: str) -> pl.DataFrame:
    kind, dims = SCHEMA[name]
    gdx_name = GDX_NAME.get(name, name)
    df = records(container, gdx_name)
    if df is None:
        return pl.DataFrame({c: [] for c in dims} | ({"value": []} if kind != "set" else {}))
    index_cols = list(df.columns[: len(dims)])
    df = df.rename(dict(zip(index_cols, dims)))
    if kind == "set":
        return df.select(list(dims))
    return df.select(list(dims) + ["value"])


def load_case_from_gdx(path: str | Path) -> Case:
    container = gt.Container(load_from=str(path))
    tables = {}
    for name in SCHEMA:
        if name.startswith("state_"):
            continue
        gdx_name = GDX_NAME.get(name, name)
        if gdx_name in container:
            tables[name] = contract_table(container, name)
    return from_tables(tables)


def solution_table(container: gt.Container, name: str, dims: tuple[str, ...]) -> pl.DataFrame:
    df = records(container, name)
    if df is None:
        return pl.DataFrame({c: [] for c in dims} | {f: [] for f in FIELDS})
    index_cols = list(df.columns[: len(dims)])
    df = df.rename(dict(zip(index_cols, dims)))
    for d in dims:
        if d in ("t", "tt"):
            df = df.with_columns(pl.col(d).cast(pl.Int64))
    return df.select(list(dims) + [f for f in FIELDS if f in df.columns])


def load_solution(path: str | Path, variables: dict[str, tuple[str, ...]],
                  equations: dict[str, tuple[str, ...]]) -> dict:
    container = gt.Container(load_from=str(path))
    out = {"variables": {}, "equations": {}, "objective": None}
    for name, dims in variables.items():
        out["variables"][name] = solution_table(container, name, dims)
    for name, dims in equations.items():
        out["equations"][name] = solution_table(container, name, dims)
    z = records(container, "Z_slice") if "Z_slice" in container else records(container, "Z")
    out["objective"] = float(z["level"][0])
    return out


def load_jacobian(path: str | Path) -> dict:
    container = gt.Container(load_from=str(path))
    rows = records(container, "i").rename({"uni": "row", "element_text": "name"})
    cols = records(container, "j").rename({"uni": "col", "element_text": "name"})
    a = records(container, "A").rename({"i": "row", "j": "col"})
    e = records(container, "e")
    x = records(container, "x")
    objrow = records(container, "iobj")
    objvar = records(container, "jobj")
    return {
        "rows": rows,
        "cols": cols,
        "A": a,
        "e": e.rename({"i": "row"}),
        "x": x.rename({"j": "col"}),
        "objective_row": str(objrow[objrow.columns[0]][0]) if objrow is not None else None,
        "objective_col": str(objvar[objvar.columns[0]][0]) if objvar is not None else None,
        "objcoef": float(records(container, "objcoef")["value"][0]),
        "objconst": float(records(container, "objconst")["value"][0]) if "objconst" in container else 0.0,
    }
