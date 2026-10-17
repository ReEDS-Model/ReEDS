from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

REEDS = Path(__file__).resolve().parents[2]
C_MODEL = REEDS / "reeds" / "core" / "setup" / "c_model.gms"
D_OBJECTIVE = REEDS / "reeds" / "core" / "setup" / "d_objective.gms"
VARFIX = REEDS / "reeds" / "core" / "solve" / "5_varfix.gms"
TEMPLATE = Path(__file__).resolve().parent / "gams" / "model_template.gms"

OBJECTIVE_EQUATIONS = ("eq_ObjFn", "eq_ObjFn_inv", "eq_Objfn_op")
OBJECTIVE_VARIABLES = ("Z", "Z_inv", "Z_op")

VAR_BLOCK = re.compile(r"^\s*(?:positive\s+|free\s+|integer\s+|binary\s+)?variables?\s*(.*?)^\s*;", re.I | re.S | re.M)
EQ_STATEMENT = re.compile(r"^(eq_\w+)\s*(?:\(([^)]*)\))?\s*(\$[^.]*?)?\s*\.\.(.*?);", re.S | re.M)
FX_STATEMENT = re.compile(r"^\s*([A-Za-z_]\w*)\.fx\((.*?)\)\s*(\$\[.*?\]|\$[A-Za-z_]\w*(?:\([^)]*\))?)?\s*=", re.M | re.S)


@dataclass
class Equation:
    name: str
    dims: tuple[str, ...]
    condition: str
    body: str
    variables: set[str] = field(default_factory=set)
    source: str = ""


def _strip_comments(text: str) -> str:
    out = []
    in_ontext = False
    for line in text.splitlines():
        low = line.strip().lower()
        if low.startswith("$ontext"):
            in_ontext = True
            continue
        if low.startswith("$offtext"):
            in_ontext = False
            continue
        if in_ontext or line.startswith("*"):
            continue
        out.append(line)
    return "\n".join(out)


def _texts(paths) -> dict[Path, str]:
    return {p: _strip_comments(p.read_text(encoding="utf-8", errors="replace")) for p in paths}


def variable_dims(paths=(C_MODEL, D_OBJECTIVE)) -> dict[str, tuple[str, ...]]:
    dims: dict[str, tuple[str, ...]] = {}
    for text in _texts(paths).values():
        for m in VAR_BLOCK.finditer(text):
            for line in m.group(1).splitlines():
                line = line.strip()
                if not line or line.startswith("*"):
                    continue
                vm = re.match(r"^([A-Za-z_]\w*)\s*(?:\(([^)]*)\))?", line)
                if vm and vm.group(1).lower() not in ("positive", "free", "variable", "variables"):
                    name = vm.group(1)
                    if name not in dims:
                        dims[name] = tuple(d.strip() for d in vm.group(2).split(",")) if vm.group(2) else ()
    return dims


def all_variables(paths=(C_MODEL, D_OBJECTIVE)) -> list[str]:
    return list(variable_dims(paths))


def parse_equations(paths=(C_MODEL, D_OBJECTIVE)) -> dict[str, Equation]:
    equations: dict[str, Equation] = {}
    var_lower = {v.lower(): v for v in all_variables(paths)}
    for path, text in _texts(paths).items():
        for m in EQ_STATEMENT.finditer(text):
            name = m.group(1)
            dims = tuple(d.strip() for d in m.group(2).split(",")) if m.group(2) else ()
            cond = (m.group(3) or "").strip()
            body = m.group(4)
            used = set()
            for tok in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", body):
                key = tok.group(1).lower()
                if key in var_lower:
                    used.add(var_lower[key])
            equations[name] = Equation(name, dims, cond, body, used, path.name)
    return equations


def parse_varfix(path=VARFIX) -> dict[str, str]:
    text = _strip_comments(path.read_text(encoding="utf-8", errors="replace"))
    pins = {}
    for m in FX_STATEMENT.finditer(text):
        var, args, cond = m.group(1), m.group(2), m.group(3) or ""
        args_t = re.sub(r"\btfix\b", "t", args)
        cond_t = re.sub(r"\btfix\b", "t", cond)
        if cond_t.startswith("$[") and cond_t.endswith("]"):
            inner = cond_t[2:-1].lstrip("$")
            cond_t = f"$[tmodel(t)$({inner})]"
        elif cond_t.startswith("$"):
            cond_t = f"$[tmodel(t)$({cond_t[1:]})]"
        else:
            cond_t = "$tmodel(t)"
        pins[var.lower()] = f"{var}.fx({args_t}){cond_t} = 0 ;"
    return pins


MANUAL_PINS = {
    "captran_itl": "CAPTRAN_ITL.fx(itlgrp,itlgrpp,t)$tmodel(t) = 0 ;",
    "credit_h2ptc": "CREDIT_H2PTC.fx(i,v,r,h,t)$[tmodel(t)$valgen(i,v,r,t)] = 0 ;",
    "cap_above_lim": "CAP_ABOVE_LIM.fx(tg,r,t)$tmodel(t) = 0 ;",
}


def default_pin(var: str, dims: tuple[str, ...]) -> str:
    if var.lower() in MANUAL_PINS:
        return MANUAL_PINS[var.lower()]
    raise KeyError(f"variable {var} has no 5_varfix.gms pattern and no manual pin; add one to MANUAL_PINS")


def pin_block(active: set[str], variables: list[str], pins: dict[str, str]) -> str:
    lines = []
    dims = variable_dims()
    active_lower = {a.lower() for a in active}
    for var in variables:
        if var.lower() in active_lower or var in OBJECTIVE_VARIABLES:
            continue
        if var.lower() in MANUAL_PINS:
            lines.append(MANUAL_PINS[var.lower()])
        elif var.lower() in pins:
            lines.append(pins[var.lower()])
        elif var in dims:
            lines.append(default_pin(var, dims[var]))
        else:
            raise KeyError(f"no pin pattern and no declared domain for variable {var}")
    return "\n".join(lines)


def write_model_gms(equation_names: list[str], active_variables: list[str], out_path: Path,
                    model_name: str = "ReEDSport") -> dict:
    equations = parse_equations()
    unknown = [e for e in equation_names if e not in equations]
    if unknown:
        raise KeyError(f"equations not found in c_model.gms or d_objective.gms: {unknown}")
    names = list(equation_names)
    for obj in OBJECTIVE_EQUATIONS:
        if obj not in names:
            names.append(obj)
    active = set(active_variables)
    variables = all_variables()
    pins = parse_varfix()
    text = TEMPLATE.read_text(encoding="utf-8")
    text = text.replace("%%MODEL%%", model_name)
    text = text.replace("%%EQUATIONS%%", "\n".join(f"    {e}" for e in names))
    text = text.replace("%%PINS%%", pin_block(active, variables, pins))
    out_path.write_text(text, encoding="utf-8")
    return {"equations": names, "active_variables": sorted(active),
            "pinned_variables": sorted(v for v in variables if v not in active and v not in OBJECTIVE_VARIABLES)}
