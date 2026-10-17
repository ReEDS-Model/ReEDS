from __future__ import annotations

import re
from pathlib import Path

import polars as pl

REEDS = Path(__file__).resolve().parents[2]
SOURCES = {
    "b_inputs": REEDS / "reeds" / "core" / "setup" / "b_inputs.gms",
    "2_temporal_params": REEDS / "reeds" / "core" / "solve" / "2_temporal_params.gms",
}
OUT = Path(__file__).resolve().parent / "gams_includes.csv"

KEYWORD = re.compile(r"^\s*(sets?|parameters?|tables?|scalars?)\b", re.I)
DECL = re.compile(r"^\s*(?:(sets?|parameters?|tables?|scalars?)\s+)?([A-Za-z_]\w*)\s*(?:\(([^)]*)\))?\s*(?:\"[^\"]*\")?\s*/?\s*$", re.I)
INCLUDE = re.compile(r"\$include\s+inputs_case(?:%ds%|/)(\S+)")


def _declaration(lines: list[str], n: int) -> tuple[str, str, tuple[str, ...]]:
    kind = ""
    for k in range(n - 1, max(-1, n - 25), -1):
        raw = lines[k].strip()
        if not raw or raw.startswith("$") or raw.startswith("*"):
            continue
        m = DECL.match(raw)
        if not m or m.group(2).lower() in ("yes", "no"):
            continue
        kind = (m.group(1) or "").lower()
        name = m.group(2)
        dims = tuple(d.strip() for d in (m.group(3) or "").split(",") if d.strip())
        if not kind:
            for j in range(k - 1, max(-1, k - 8), -1):
                km = KEYWORD.match(lines[j])
                if km:
                    kind = km.group(1).lower()
                    break
        return kind.rstrip("s"), name, dims
    raise ValueError(f"no declaration found above line {n + 1}: {lines[n]}")


def _flags(lines: list[str], n: int) -> dict:
    window = [lines[j].lower() for j in range(max(0, n - 6), n)]
    return {
        "ondelim": any("$ondelim" in w for w in window),
        "onempty": any("$onempty" in w for w in window),
    }


def _folder_and_file(spec: str) -> tuple[str, str]:
    if spec.startswith("%temporal_inputs%%ds%"):
        return "rep", spec.split("%ds%", 1)[1]
    if spec.startswith("stress%stress_year%%ds%"):
        return "stress", spec.split("%ds%", 1)[1]
    return "", spec


def build() -> pl.DataFrame:
    rows = []
    for source, path in SOURCES.items():
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for n, line in enumerate(lines):
            m = INCLUDE.search(line)
            if not m:
                continue
            folder, file = _folder_and_file(m.group(1))
            flags = _flags(lines, n)
            if file.endswith(".txt"):
                kind, symbol, dims = "scalar", Path(file).stem, ()
                layout = "gams_scalars"
            else:
                kind, symbol, dims = _declaration(lines, n)
                if kind == "":
                    kind = "set"
            if file.endswith(".txt"):
                pass
            elif kind == "table":
                layout = "table"
            elif kind == "scalar":
                layout = "scalar"
            elif kind == "set" and not flags["ondelim"]:
                layout = "list"
            else:
                layout = "long"
            rows.append({
                "source": source, "line": n + 1, "folder": folder, "file": file,
                "symbol": symbol, "kind": kind, "layout": layout, "dims": ",".join(dims),
                "ondelim": flags["ondelim"], "onempty": flags["onempty"],
            })
    return pl.DataFrame(rows)


if __name__ == "__main__":
    df = build()
    df.write_csv(OUT)
    print(f"{df.height} includes -> {OUT}")
    print(df.group_by(["kind", "layout"]).agg(pl.len()).sort("kind"))
