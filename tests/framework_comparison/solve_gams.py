"""
Native GAMS implementation of the ReEDS-representative LP test problem.

Generates a temporary .gms file from ProblemData, calls the GAMS executable,
and parses the .lst output for timing and objective value.

Timing split:
  build_s = Python .gms generation time + GAMS compilation + GAMS GENERATION TIME
  solve_s = GAMS SOLVE TIME (HiGHS) or RESOURCE USAGE (CPLEX)
"""

from __future__ import annotations
import re
import subprocess
import tempfile
import time
from pathlib import Path

from data_generator import ProblemData

GAMS_EXE = "/Library/Frameworks/GAMS.framework/Resources/gams"


def _write_gms(data: ProblemData, gms_path: Path, solver: str) -> None:
    R, I, H, T = data.regions, data.techs, data.hours, data.years
    ri, ii, hi, ti = data.r_idx, data.i_idx, data.h_idx, data.t_idx

    lines = []

    # ---- Sets ---------------------------------------------------------------
    lines += [
        "Sets",
        f"  i  technologies  / {', '.join(I)} /",
        f"  r  regions       / {', '.join(R)} /",
        f"  h  hours         / {', '.join(str(h) for h in H)} /",
        f"  t  years         / {', '.join(str(t) for t in T)} /",
        ";",
        "Alias(r, rr);",
        "Alias(t, tt);",
        "Alias(h, hh);",
        "",
        "Sets",
        "  rt(r,rr)  transmission routes /",
        *[f"    {a}.{b}" for (a, b) in data.routes],
        "  /",
        "",
        "  valcap(i,r,t)  active combinations /",
        *[
            f"    {i}.{r}.{t}"
            for i in I for r in R for t in T
            if data.valcap[ii[i], ri[r], ti[t]]
        ],
        "  /",
        "",
    ]

    # Tech classification sets
    vre_techs   = [i for i in I if data.is_vre[ii[i]]]
    stor_techs  = [i for i in I if data.is_storage[ii[i]]]
    disp_techs  = [i for i in I if not data.is_vre[ii[i]] and not data.is_storage[ii[i]]]
    has_disp    = bool(disp_techs)
    has_emit    = any(data.emit_rate[ii[i]] > 0 for i in I)
    has_storage = bool(stor_techs)
    has_mingen  = any(data.minloadfrac[ii[i]] > 0 for i in I
                      if not data.is_storage[ii[i]])

    lines += [
        "Sets",
        f"  is_vre(i)  VRE technologies  / {', '.join(vre_techs) if vre_techs else ''} /",
        f"  stor(i)    storage technologies  / {', '.join(stor_techs) if stor_techs else ''} /",
        "",
        "* h_suc(h,hh): successor pairs with wrap-around (for SOC balance)",
        "  h_suc(h,hh) /",
        *[f"    {H[k]}.{H[(k+1) % len(H)]}" for k in range(len(H))],
        "  /",
        "",
        "* h_ramp(h,hh): consecutive pairs without wrap (for ramping)",
        "  h_ramp(h,hh) /",
        *[f"    {H[k]}.{H[k+1]}" for k in range(len(H)-1)],
        "  /",
        ";",
        "",
    ]

    # ---- Parameters ---------------------------------------------------------
    def param(name, domain, entries, desc=""):
        lines.append(f"Parameter {name}({domain}) {desc} /")
        lines.extend(f"  {e}" for e in entries)
        lines.extend(["/;", ""])

    param("load_p", "r,h,t",
          [f"{r}.{h}.{t}  {data.load[ri[r], hi[h], ti[t]]:.15g}"
           for r in R for h in H for t in T])

    param("cf_p", "i,r,h",
          [f"{i}.{r}.{h}  {data.cf[ii[i], ri[r], hi[h]]:.15g}"
           for i in I for r in R for h in H])

    param("ci_p", "i,r",
          [f"{i}.{r}  {data.cap_init[ii[i], ri[r]]:.15g}"
           for i in I for r in R if data.cap_init[ii[i], ri[r]] > 0])

    param("cinv_p", "i",
          [f"{i}  {data.cost_inv[ii[i]]:.15g}" for i in I])

    param("cop_p", "i",
          [f"{i}  {data.cost_op[ii[i]]:.15g}" for i in I])

    param("tc_p", "r,rr",
          [f"{a}.{b}  {data.transcap[(a, b)]:.15g}" for (a, b) in data.routes])

    param("pvf_p", "t",
          [f"{t}  {data.pvf[ti[t]]:.15g}" for t in T])

    param("hw_p", "h",
          [f"{h}  {data.hours_weight[hi[h]]:.15g}" for h in H])

    param("peak_p", "r,t",
          [f"{r}.{t}  {float(data.load[ri[r], :, ti[t]].max()):.15g}"
           for r in R for t in T])

    if has_mingen:
        param("mf_p", "i",
              [f"{i}  {data.minloadfrac[ii[i]]:.15g}"
               for i in I if data.minloadfrac[ii[i]] > 0 and not data.is_storage[ii[i]]])

    if has_emit:
        param("er_p", "i",
              [f"{i}  {data.emit_rate[ii[i]]:.15g}"
               for i in I if data.emit_rate[ii[i]] > 0])

    param("ec_p", "t",
          [f"{t}  {data.emit_cap[ti[t]]:.15g}" for t in T])

    if has_disp:
        param("sc_p", "i",
              [f"{i}  {data.startcost[ii[i]]:.15g}"
               for i in disp_techs if data.startcost[ii[i]] > 0])

    # min_cf applies to dispatchable (non-VRE, non-storage) techs
    param("mincf_p", "i",
          [f"{i}  {data.min_cf[ii[i]]:.15g}"
           for i in disp_techs if data.min_cf[ii[i]] > 0])

    if has_storage:
        lines += [
            f"Scalar eff_p  charging efficiency / {data.charge_eff:.15g} /;",
            f"Scalar dur_p  storage duration hours / {data.duration_h:.15g} /;",
            "",
        ]

    # Precompute total hours weight
    total_hw = float(data.hours_weight.sum())
    lines += [f"Scalar total_hw  total hours weight / {total_hw:.15g} /;", ""]

    # ---- Variables ----------------------------------------------------------
    pos_vars = "GEN, CAP, INV, FLOW"
    var_decls = [
        "  GEN(i,r,h,t)",
        "  CAP(i,r,t)",
        "  INV(i,r,t)",
        "  FLOW(r,rr,h,t)",
    ]
    if has_disp:
        var_decls.append("  RAMPUP(i,r,h,t)")
        pos_vars += ", RAMPUP"
    if has_storage:
        var_decls += ["  CHARGE(i,r,h,t)", "  SOC(i,r,h,t)"]
        pos_vars += ", CHARGE, SOC"
    var_decls.append("  Z")
    lines += ["Variables", *var_decls, ";",
              f"Positive Variables {pos_vars};", ""]

    # ---- Equations ----------------------------------------------------------
    eqs = ["eq_cap_accum(i,r,t)", "eq_cap_limit(i,r,h,t)"]
    if has_mingen:
        eqs.append("eq_mingen(i,r,h,t)")
    eqs += ["eq_supply(r,h,t)", "eq_reserve(r,t)", "eq_trans(r,rr,h,t)", "eq_emit(t)"]
    if has_disp:
        eqs += ["eq_ramping(i,r,h,hh,t)", "eq_mincf(i,r,t)"]
    if has_storage:
        eqs += ["eq_soc(i,r,h,hh,t)", "eq_soc_cap(i,r,h,t)", "eq_charge_cap(i,r,h,t)"]
    eqs.append("eq_obj")
    lines += ["Equations", *[f"  {e}" for e in eqs], ";", ""]

    # ---- Equation bodies ----------------------------------------------------
    lines += [
        "eq_cap_accum(valcap(i,r,t))..",
        "  CAP(i,r,t) =e= ci_p(i,r)",
        "    + Sum(tt$(Ord(tt) <= Ord(t) and valcap(i,r,tt)), INV(i,r,tt));",
        "",
        "eq_cap_limit(i,r,h,t)$(valcap(i,r,t))..",
        "  GEN(i,r,h,t) =l= cf_p(i,r,h) * CAP(i,r,t);",
        "",
    ]

    if has_mingen:
        lines += [
            "eq_mingen(i,r,h,t)$(valcap(i,r,t) and mf_p(i) > 0)..",
            "  GEN(i,r,h,t) =g= mf_p(i) * CAP(i,r,t);",
            "",
        ]

    stor_term = "- Sum(stor(i)$valcap(i,r,t), CHARGE(i,r,h,t))" if has_storage else ""
    lines += [
        "eq_supply(r,h,t)..",
        "  Sum(i$valcap(i,r,t), GEN(i,r,h,t))",
        f"  + Sum(rt(rr,r), (1 - {data.tranloss}) * FLOW(rr,r,h,t))",
        "  - Sum(rt(r,rr), FLOW(r,rr,h,t))",
        *([f"  {stor_term}"] if has_storage else []),
        "  =e= load_p(r,h,t);",
        "",
        "eq_reserve(r,t)..",
        f"  Sum(i$valcap(i,r,t), CAP(i,r,t)) =g= (1 + {data.prm}) * peak_p(r,t);",
        "",
        "eq_trans(rt(r,rr),h,t)..",
        "  FLOW(r,rr,h,t) =l= tc_p(r,rr);",
        "",
    ]

    if has_emit:
        lines += [
            "eq_emit(t)..",
            "  Sum((i,r,h)$(valcap(i,r,t) and er_p(i)),",
            "    er_p(i) * hw_p(h) * GEN(i,r,h,t)) =l= ec_p(t);",
            "",
        ]
    else:
        lines += ["eq_emit(t).. 0 =l= ec_p(t);", ""]

    if has_disp:
        lines += [
            "eq_ramping(i,r,h,hh,t)$(valcap(i,r,t)$(not is_vre(i))$(not stor(i))$h_ramp(h,hh))..",
            "  RAMPUP(i,r,h,t) =g= GEN(i,r,hh,t) - GEN(i,r,h,t);",
            "",
            "eq_mincf(i,r,t)$(valcap(i,r,t)$mincf_p(i))..",
            "  Sum(h, hw_p(h) * GEN(i,r,h,t)) =g= mincf_p(i) * CAP(i,r,t) * total_hw;",
            "",
        ]

    if has_storage:
        lines += [
            "eq_soc(stor(i),r,h,hh,t)$(valcap(i,r,t)$h_suc(h,hh))..",
            "  SOC(i,r,hh,t) =e= SOC(i,r,h,t) + eff_p * CHARGE(i,r,h,t) - GEN(i,r,h,t);",
            "",
            "eq_soc_cap(stor(i),r,h,t)$(valcap(i,r,t))..",
            "  SOC(i,r,h,t) =l= dur_p * CAP(i,r,t);",
            "",
            "eq_charge_cap(stor(i),r,h,t)$(valcap(i,r,t))..",
            "  CHARGE(i,r,h,t) =l= CAP(i,r,t);",
            "",
        ]

    # Objective — investment + operations + ramping start cost
    obj_lines = [
        "eq_obj..",
        "  Z =e= Sum(t, pvf_p(t) * (",
        "    Sum((i,r)$valcap(i,r,t), cinv_p(i) * INV(i,r,t))",
        "    + Sum((i,r,h)$valcap(i,r,t),",
        "        cop_p(i) * hw_p(h) * GEN(i,r,h,t))",
    ]
    if has_disp:
        obj_lines += [
            "    + Sum((i,r,h,hh)$(valcap(i,r,t)$(not is_vre(i))$(not stor(i))",
            "        $h_ramp(h,hh)$sc_p(i)),",
            "        sc_p(i) * RAMPUP(i,r,h,t))",
        ]
    obj_lines += [
        "  ));",
        "",
        "Model reeds_mini / all /;",
        f"Option LP = {solver};",
        "reeds_mini.optfile = 1;",
        "Solve reeds_mini using LP minimizing Z;",
        "Display Z.l;",
    ]
    lines += obj_lines

    gms_path.write_text("\n".join(lines), encoding="ascii")


def _parse_lst(lst_path: Path) -> tuple[float, float, float]:
    """Return (objective, generation_time_s, solve_time_s) from .lst file."""
    text = lst_path.read_text(encoding="ascii", errors="replace")

    if "Licensing Problem" in text or "SOLVER STATUS     7" in text:
        raise RuntimeError("GAMS solver licensing problem — solver not covered by license")
    if "MODEL STATUS      4" in text or "MODEL STATUS      5" in text:
        raise RuntimeError("GAMS model infeasible or unbounded")

    obj = None
    for pat in [
        r"OBJECTIVE VALUE\s+([\d.E+\-]+)",
        r"Z\.L\s*=\s*([\d.E+\-]+)",
    ]:
        m = re.search(pat, text)
        if m:
            obj = float(m.group(1))
            break

    gen_m = re.search(r"GENERATION TIME\s+=\s+([\d.]+)\s+SECONDS", text)

    solve_m = re.search(r"RESOURCE USAGE,\s*LIMIT\s+([\d.]+)", text)
    if solve_m is None:
        solve_m = re.search(r"SOLVE TIME\s+=\s+([\d.]+)\s+SECONDS", text)

    if obj is None:
        snippet = text[-2000:] if len(text) > 2000 else text
        raise RuntimeError(f"Could not parse objective from {lst_path}:\n{snippet}")

    gen_s   = float(gen_m.group(1))   if gen_m   else 0.0
    solve_s = float(solve_m.group(1)) if solve_m else 0.0
    return obj, gen_s, solve_s


def solve(
    data: ProblemData,
    solver: str = "highs",
    build_only: bool = False,
    gams_exe: str | Path = GAMS_EXE,
) -> tuple[float, float, float]:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        gms  = tmp_path / "reeds_mini.gms"
        lst  = tmp_path / "reeds_mini.lst"

        t0 = time.perf_counter()
        _write_gms(data, gms, solver)
        if solver.lower() == "highs":
            (tmp_path / "highs.op1").write_text("solver = ipm\n", encoding="ascii")
        elif solver.lower() == "cplex":
            (tmp_path / "cplex.op1").write_text("lpmethod 4\n", encoding="ascii")
        write_s = time.perf_counter() - t0
        if build_only:
            return float("nan"), write_s, 0.0

        t1 = time.perf_counter()
        result = subprocess.run(
            [str(gams_exe), str(gms), "lo=0", f"o={lst}", f"curdir={tmp_path}"],
            capture_output=True, text=True,
        )
        gams_wall = time.perf_counter() - t1

        if result.returncode > 1:
            lst_tail = ""
            if lst.exists():
                lst_tail = lst.read_text(encoding="ascii", errors="replace")[-2000:]
            raise RuntimeError(
                f"GAMS exited {result.returncode}:\n"
                f"stdout:\n{result.stdout[-1000:]}\n"
                f"stderr:\n{result.stderr[-500:]}\n"
                f"lst tail:\n{lst_tail}"
            )

        obj, gen_s, solve_s = _parse_lst(lst)

    build_s = write_s + (gams_wall - solve_s)
    return obj, build_s, solve_s


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("--gams-exe", default=GAMS_EXE, help="Path to the GAMS executable")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).parent))
    from data_generator import make_problem
    for size in ("small", "medium", "large", "xlarge"):
        data = make_problem(size)
        obj, b, s = solve(data, solver="cplex", gams_exe=args.gams_exe)
        print(f"{size:6s}  obj={obj:>18,.0f}  build={b:.3f}s  solve={s:.3f}s")
