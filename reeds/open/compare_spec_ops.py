from __future__ import annotations

SPEC: dict[str, dict] = {
    "eq_OpRes_requirement": {
        "summary": "Operating-reserve requirement by reserve type and zone: reserves from generators plus net reserve imports must cover the load, wind and PV components.",
        "math": r"""
\sum_{(i,v)\in\mathrm{valgen}_{r,t},\ \P{reserve\_frac}_{i,o}\neq0}\V{OPRES}_{o,i,v,r,h,t}
 + \sum_{rr:\ \mathrm{opres\_routes}(rr,r,t)}(1-\P{tranloss}_{rr,r,\mathrm{AC}})\V{OPRES\_FLOW}_{o,rr,r,h,t}
 - \sum_{rr:\ \mathrm{opres\_routes}(r,rr,t)}\V{OPRES\_FLOW}_{o,r,rr,h,t}
 + \V{DROPPED}_{r,h,t}[t<\mathrm{Sw\_StartMarkets}] \\
 \;\ge\; \P{orperc}_{o,\mathrm{or\_load}}\V{LOAD}_{r,h,t}
 + \P{orperc}_{o,\mathrm{or\_wind}}\sum_{(i,v)\in\mathrm{valgen},\ i\in\mathrm{wind}}\V{GEN}_{i,v,r,h,t}
 + \P{orperc}_{o,\mathrm{or\_pv}}\sum_{(i,v)\in\mathrm{valcap},\ i\in\mathrm{pv}\cup\mathrm{pvb}}\frac{\V{CAP}_{i,v,r,t}}{\P{ilr}_i}\,[h\in\mathrm{dayhours}]
\qquad o\in\mathrm{opres\_model},\ h\in\mathrm{opres\_h},\ \mathrm{Sw\_OpRes}
""",
        "terms": [
            ("sum OPRES $[valgen$reserve_frac]", r"\sum\V{OPRES}", "opres_gen (+1) on the OPRES columns (valgen × reserve_frac × opres_h)", "ported"),
            ("(1 − tranloss(rr,r,AC)) * OPRES_FLOW(rr,r)", r"(1-\P{tranloss})\V{OPRES\_FLOW}_{rr,r}", "opres_import: 1 − tranloss(AC) on OPRES_FLOW(o,r,rr) summed by (o,rr,h,t) then rr→r (receiving zone)", "ported"),
            ("− OPRES_FLOW(r,rr)", r"-\V{OPRES\_FLOW}_{r,rr}", "opres_export (−1) summed by (o,r,h,t)", "ported"),
            ("DROPPED", r"\V{DROPPED}", "absent", "not ported; prep raises when t < Sw_StartMarkets"),
            ("orperc(or_load) * LOAD", r"\P{orperc}_{load}\V{LOAD}", "opres_load = −orperc(o, or_load) on LOAD; orperc already includes Sw_OpResReqMult (derive_ops)", "ported"),
            ("orperc(or_wind) * sum GEN(wind)", r"\P{orperc}_{wind}\sum\V{GEN}", "opres_wind = −orperc(o, or_wind) on wind GEN in opres hours", "ported"),
            ("orperc(or_pv) * sum CAP/ilr $dayhours", r"\P{orperc}_{pv}\sum\V{CAP}/\P{ilr}", "opres_pv = −(1/ilr)·orperc(o, or_pv) on pv/pvb CAP for dayhours; raises if ilr is missing (GAMS would divide by zero)", "ported"),
        ],
        "prep": [("sw_opres = int(case.scalar(\"Sw_OpRes\"))", "bio_r = _in(valgen"), ("if sw_opres:", 'P.var["OPRES_FLOW"]'), ("OR4 = [\"ortype\", \"r\", \"h\", \"t\"]", 'P.coef["opres_pv"]')],
        "build": ['"eq_OpRes_requirement"'],
        "helpers": ["_signed", "_row"],
        "notes": ["Both reference cases run with Sw_OpRes=0, so none of the reserve equations has rows; see the OPRES caveat on eq_capacity_limit.",
                  "Rows are every (o, r, h, t) with h in opres_h, as in GAMS; a zone without any term still has a row 0 ≥ 0."],
    },
    "eq_gasaccounting_regional": {
        "summary": "Gas burned in a census division is allocated across the regional fuel bins (Sw_GasCurve=1).",
        "math": r"""
\sum_{fuelbin}\V{VGASBINQ\_REGIONAL}_{fuelbin,cd,t} \;=\; \sum_{(i,v,r,h):\ \mathrm{valgen},\ i\in\mathrm{gas},\ r\in cd}\P{hours}_h\,\P{heat\_rate}_{i,v,r,t}\,\V{GEN}_{i,v,r,h,t}
\qquad cd\in\mathrm{cendiv},\ \mathrm{Sw\_GasCurve}=1
""",
        "terms": [
            ("sum VGASBINQ_REGIONAL", r"\sum_{fuelbin}\V{VGASBINQ\_REGIONAL}", "gasacc_reg_bin (+1) summed by (cendiv, t); columns = fuelbin × cendiv × tmodel", "ported"),
            ("sum hours * heat_rate * GEN $[valgen$gas$r_cendiv]", r"\sum\P{hours}\P{heat\_rate}\V{GEN}", "gasacc_reg_gen = −hours(h)·heat_rate on gas GEN columns, mapped to the census division through r_cendiv and summed by (cendiv, t)", "ported"),
        ],
        "where": [r"hours(h) over every timeslice of the solve year (representative and stress), as in GAMS, which has no h_rep filter here."],
        "prep": [("if int(case.scalar(\"Sw_GasCurve\")) == 1:", 'P.coef["gasbin_nat_var"]')],
        "build": ['"eq_gasaccounting_regional"'],
        "derive": [("reeds/open/derive_costs.py", "def gas_curve(S: Symbols", None)],
        "notes": ["Objective (pvf_onm): gasbinp_regional × VGASBINQ_REGIONAL and gasbinp_national × VGASBINQ_NATIONAL, plus gasmultterm × cendiv_weights × hours × heat_rate × gasprice_adj_r on gas GEN instead of the fixed fuel price (slice_objop_GEN in derive_temporal).",
                  "No rows in either reference case (Sw_GasCurve=2). runreeds.py refuses Sw_GasCurve=1 for a sub-national region, so a national reference case is needed to exercise it."],
    },
    "eq_gasaccounting_national": {
        "summary": "Gas burned nationally is allocated across the national fuel bins (Sw_GasCurve=1).",
        "math": r"""
\sum_{fuelbin}\V{VGASBINQ\_NATIONAL}_{fuelbin,t} \;=\; \sum_{(i,v,r,h):\ \mathrm{valgen},\ i\in\mathrm{gas}}\P{hours}_h\,\P{heat\_rate}_{i,v,r,t}\,\V{GEN}_{i,v,r,h,t}
\qquad \mathrm{Sw\_GasCurve}=1
""",
        "terms": [
            ("sum VGASBINQ_NATIONAL", r"\sum_{fuelbin}\V{VGASBINQ\_NATIONAL}", "gasacc_nat_bin (+1) summed by t; columns = fuelbin × tmodel", "ported"),
            ("sum hours * heat_rate * GEN $[valgen$gas]", r"\sum\P{hours}\P{heat\_rate}\V{GEN}", "gasacc_nat_gen = −hours(h)·heat_rate on gas GEN columns summed by t", "ported"),
        ],
        "prep": [("if int(case.scalar(\"Sw_GasCurve\")) == 1:", 'P.coef["gasbin_nat_var"]')],
        "build": ['"eq_gasaccounting_national"'],
        "notes": ["No rows in either reference case (Sw_GasCurve=2)."],
    },
    "eq_gasbinlimit_regional": {
        "summary": "Each regional fuel bin holds at most its width (Sw_GasCurve=1).",
        "math": r"\P{gasbinwidth\_regional}_{fuelbin,cd,t} \;\ge\; \V{VGASBINQ\_REGIONAL}_{fuelbin,cd,t}\qquad \mathrm{Sw\_GasCurve}=1",
        "terms": [
            ("gasbinwidth_regional", r"\P{gasbinwidth\_regional}", "gasbin_reg_width: reference consumption × bin width (0.6 for the first bin, 2.0 for the last, (1.4−0.6)/18 otherwise), floored at 10 MMBtu (derive_costs.gas_curve)", "ported (constant)"),
            ("VGASBINQ_REGIONAL", r"\V{VGASBINQ\_REGIONAL}", "gasbin_reg_var (−1)", "ported"),
        ],
        "prep": [("if int(case.scalar(\"Sw_GasCurve\")) == 1:", 'P.coef["gasbin_nat_var"]')],
        "build": ['"eq_gasbinlimit_regional"'],
        "derive": [("reeds/open/derive_costs.py", "def gas_curve(S: Symbols", None)],
        "notes": ["No rows in either reference case (Sw_GasCurve=2)."],
    },
    "eq_gasbinlimit_national": {
        "summary": "Each national fuel bin holds at most its width (Sw_GasCurve=1).",
        "math": r"\P{gasbinwidth\_national}_{fuelbin,t} \;\ge\; \V{VGASBINQ\_NATIONAL}_{fuelbin,t}\qquad \mathrm{Sw\_GasCurve}=1",
        "terms": [
            ("gasbinwidth_national", r"\P{gasbinwidth\_national}", "gasbin_nat_width: national reference consumption × bin width, no floor", "ported (constant)"),
            ("VGASBINQ_NATIONAL", r"\V{VGASBINQ\_NATIONAL}", "gasbin_nat_var (−1)", "ported"),
        ],
        "prep": [("if int(case.scalar(\"Sw_GasCurve\")) == 1:", 'P.coef["gasbin_nat_var"]')],
        "build": ['"eq_gasbinlimit_national"'],
        "notes": ["No rows in either reference case (Sw_GasCurve=2)."],
    },
    "eq_storage_opres": {
        "summary": "Storage must hold enough energy to deliver the reserves it offers for the duration of the timeslice.",
        "math": r"""
\V{STORAGE\_LEVEL}_{i,v,r,h,t} - \P{hd}_h\V{GEN}_{i,v,r,h,t}[i\notin\mathrm{hybrid}\setminus\mathrm{csp}] - \P{hd}_h\V{GEN\_STORAGE}\sw{Sw\_HybridPlant}
 - \P{hd}_h\,\V{OPRES}_{\mathrm{reg}|\mathrm{combo},i,v,r,h,t}\frac{1-\P{storage\_eff}_{i,t}}{2}\P{reg\_energy\_frac}
 \;\ge\; \P{hd}_h\sum_{o\in\mathrm{opres\_model}}\V{OPRES}_{o,i,v,r,h,t}
\qquad (i,v,r,t)\in\mathrm{valgen},\ i\in\mathrm{storage\_standalone}\cup(\mathrm{hybrid}\setminus\mathrm{csp})\cup\mathrm{hyd\_add\_pump},\ h\in\mathrm{opres\_h}
""",
        "terms": [
            ("STORAGE_LEVEL", r"\V{STORAGE\_LEVEL}", "sopres_level (+1)", "ported"),
            ("− hours_daily * GEN $[not hybrid]", r"-\P{hd}\V{GEN}", "sopres_gen (−hd) on non-hybrid rows", "ported"),
            ("− hours_daily * GEN_STORAGE", r"-\P{hd}\V{GEN\_STORAGE}", "absent", "not ported; guarded by Sw_HybridPlant"),
            ("− hours_daily * OPRES(reg or combo) * (1 − eff)/2 * reg_energy_frac", r"-\P{hd}\V{OPRES}_{reg}\tfrac{1-\eta}{2}\P{ref}", "sopres_reg: −((hd·(1−eff))/2)·ref on the reg (Sw_OpRes=1) or combo (Sw_OpRes=2) column", "ported"),
            ("hours_daily * sum OPRES", r"\P{hd}\sum_o\V{OPRES}", "sopres_all (−hd) on every OPRES column of the row", "ported"),
        ],
        "prep": [("so_dom = (_in(P.var[\"GEN\"]", 'P.coef["sopres_all"]')],
        "build": ['"eq_storage_opres"'],
        "notes": ["The reg column receives both sopres_reg and sopres_all; pyoframe adds the two coefficients, as GAMS does."],
    },
    "eq_storage_thermalres": {
        "summary": "Thermal storage (CSP-TES) can only offer reserves from its charging.",
        "math": r"""
\V{STORAGE\_IN}_{i,v,r,h,t} \;\ge\; \sum_{o\in\mathrm{opres\_model}}\P{reserve\_frac}_{i,o}\V{OPRES}_{o,i,v,r,h,t}
\qquad (i,v,r,t)\in\mathrm{valgen},\ i\in\mathrm{Thermal\_Storage},\ h\in\mathrm{opres\_h}
""",
        "terms": [
            ("STORAGE_IN", r"\V{STORAGE\_IN}", "sthermal_in (+1)", "ported"),
            ("sum reserve_frac * OPRES", r"\sum_o\P{reserve\_frac}\V{OPRES}", "sthermal_opres (−reserve_frac)", "ported"),
        ],
        "prep": [("st_dom = _in(valgen, \"i\", S[\"thermal_storage\"])", 'P.coef["sthermal_opres"]')],
        "build": ['"eq_storage_thermalres"'],
        "notes": ["Thermal_Storage techs have no STORAGE_IN column in the port (STORAGE_IN exists for storage_standalone only), so a row would have only OPRES terms; neither reference case has thermal storage in valgen."],
    },
    "eq_storage_in_cap": {
        "summary": "Charging power is limited to a fraction of available discharge capacity.",
        "math": r"""
\P{avail}_{i,r,h}\,\P{storinmaxfrac}_{i,v,r}\,\V{CAP}_{i,v,r,t}\,(1+\textstyle\sum_{szn}\P{h\_szn}_{h,szn}\P{seas\_cap\_frac\_delta}_{i,v,r,szn,t})\,\big(1[i\notin\mathrm{evmc}]+\P{evmc\_storage\_charge\_frac}_{i,r,h,t}[i\in\mathrm{evmc}]\big)
 \;\ge\; \V{STORAGE\_IN}_{i,v,r,h,t}
\qquad i\in\mathrm{storage\_standalone}\cup\mathrm{hyd\_add\_pump},\ \mathrm{valgen}\cap\mathrm{valcap},\ \P{storinmaxfrac}_{i,v,r}<1
""",
        "terms": [
            ("avail * storinmaxfrac * CAP * (1 + seas delta) * (evmc factor)", r"\ldots\V{CAP}", "sincap_cap: ((avail·smf)·(1+d))·(charge_frac if evmc else 1)", "ported"),
            ("STORAGE_IN", r"\V{STORAGE\_IN}", "sincap_in (−1)", "ported"),
            ("row condition storinmaxfrac < 1", r"", "smf filled with 0 where missing, rows kept where smf < 1 (GAMS treats a missing parameter as 0, which satisfies < 1)", "ported"),
        ],
        "prep": [("smf = case[\"storinmaxfrac\"]", 'P.coef["sincap_in"]')],
        "build": ['"eq_storage_in_cap"'],
        "notes": ["Both reference cases carry storinmaxfrac = 1 for every storage technology, so the equation has no rows there."],
    },
    "eq_storage_in_minloading": {
        "summary": "Minimum charging across hours of the same season (Sw_MinLoading).",
        "math": r"""
\V{STORAGE\_IN}_{i,v,r,h,t} \;\ge\; \V{STORAGE\_IN}_{i,v,r,hh,t}\,\P{minstorfrac}_{i,v,r}
\qquad \mathrm{hour\_szn\_group}(h,hh),\ \P{minstorfrac}\neq0,\ \mathrm{Sw\_MinLoading}
""",
        "guard_only": True,
        "port_note": "Not ported. <code>prep.prepare</code> raises NotImplementedError when Sw_MinLoading is 1. minstorfrac and hour_szn_group are derived (derive_ops) so the data side is ready.",
        "prep": [("if int(case.scalar(\"Sw_MinLoading\")):", None)],
    },
    "eq_minloading": {
        "summary": "Minimum loading across hours of the same season (Sw_MinLoading).",
        "math": r"""
\V{GEN}_{i,v,r,h,t} \;\ge\; \V{GEN}_{i,v,r,hh,t}\,\P{minloadfrac}_{r,i,hh}
\qquad \mathrm{valgen},\ \P{minloadfrac}_{r,i,hh}\neq0,\ t\ge\P{model\_builds\_start\_yr},\ \mathrm{hour\_szn\_group}(h,hh),\ \mathrm{Sw\_MinLoading}
""",
        "guard_only": True,
        "port_note": "Not ported. <code>prep.prepare</code> raises NotImplementedError when Sw_MinLoading is 1. minloadfrac is not derived.",
        "prep": [("if int(case.scalar(\"Sw_MinLoading\")):", None)],
    },
    "eq_battery_minduration": {
        "summary": "New batteries must have at least the minimum duration.",
        "math": r"""
\V{CAP\_ENERGY}_{i,v,r,t} \;\ge\; \P{minbatteryduration}\,\V{CAP}_{i,v,r,t}\qquad (i,v,r,t)\in\mathrm{valcap},\ v\in\mathrm{newv},\ i\in\mathrm{battery}
""",
        "terms": [
            ("CAP_ENERGY", r"\V{CAP\_ENERGY}", "bmd_energy (+1)", "ported"),
            ("minbatteryduration * CAP", r"\P{minbatteryduration}\V{CAP}", "bmd_cap (−minbatteryduration)", "ported"),
        ],
        "prep": [("bmd_dom = _in(_in(valcap", 'P.coef["bmd_cap"]')],
        "build": ['"eq_battery_minduration"'],
    },
    "eq_ramping": {
        "summary": "Defines the upward ramp of a technology fleet between consecutive timeslices.",
        "math": r"""
\V{RAMPUP}_{i,r,h,hh,t} \;\ge\; \sum_{v:\ (i,v,r,t)\in\mathrm{valgen}}\big(\V{GEN}_{i,v,r,hh,t}-\V{GEN}_{i,v,r,h,t}\big)
\qquad \mathrm{Sw\_StartCost},\ \P{startcost}_i\neq0,\ \P{numhours\_nexth}_{h,hh}\neq0,\ \mathrm{valgen\_irt}(i,r,t)
""",
        "terms": [
            ("RAMPUP", r"\V{RAMPUP}", "ramp_up (+1); the RAMPUP column set is valgen_irt × startcost techs × numhours_nexth pairs", "ported"),
            ("− sum GEN(hh)", r"-\sum_v\V{GEN}_{hh}", "ramp_gen_hh (−1) on GEN with h renamed to hh", "ported"),
            ("+ sum GEN(h)", r"+\sum_v\V{GEN}_{h}", "ramp_gen_h (+1)", "ported"),
        ],
        "prep": [("if sw_sc:", 'P.var["RAMPUP"]'), ("RAMP = [\"i\", \"r\", \"h\", \"hh\", \"t\"]", 'P.coef["ramp_gen_h"]')],
        "build": ['"eq_ramping"'],
    },
    "eq_dhyd_dispatch": {
        "summary": "Seasonal energy budget of dispatchable hydro.",
        "math": r"""
\sum_{h\in szn}\P{hours}_h\;\Big(\V{CAP}_{i,v,r,t} + \sum_{(tt,rscbin)}\big(\V{INV\_ENER\_UP}_{tt} - \P{degrade\_new}_{i,tt,t}\V{INV\_CAP\_UP}_{tt}\big)\Big)\,\P{m\_cf\_szn}_{i,v,r,szn,t}
 \;\ge\; \sum_{h\in szn}\P{hours}_h\Big(\V{GEN}_{i,v,r,h,t} + \P{reg\_energy\_frac}\,\V{OPRES}_{\mathrm{reg}|\mathrm{combo},i,v,r,h,t}[h\in\mathrm{opres\_h}]\sw{Sw\_OpRes}\Big)
\qquad i\in\mathrm{hydro\_d},\ \mathrm{valgen}
""",
        "terms": [
            ("sum hours(szn) * CAP * m_cf_szn", r"\P{H}_{szn}\P{m\_cf\_szn}\V{CAP}", "dhyd_cap = sumh(szn) (fsum of hours over the season) × m_cf_szn", "ported"),
            ("upsizing terms", r"\V{INV\_ENER\_UP},\ \V{INV\_CAP\_UP}", "absent", "not ported; allow_cap_up raises in derive_temporal"),
            ("sum hours * GEN", r"\sum_h\P{hours}\V{GEN}", "dhyd_gen (−hours)", "ported"),
            ("sum hours * reg_energy_frac * OPRES(reg|combo) $opres_h", r"\sum_h\P{hours}\P{ref}\V{OPRES}", "dhyd_opres (−hours·ref) on the reg/combo column in opres hours; empty table when Sw_OpRes=0", "ported"),
        ],
        "prep": [("DH = [\"i\", \"v\", \"r\", \"szn\", \"t\"]", 'P.coef["dhyd_opres"] = pl.DataFrame')],
        "build": ['"eq_dhyd_dispatch"'],
        "helpers": ["_fsum"],
        "notes": ["Rows exist for every season, including seasons with no hours in the representative set (then both sides are empty sums and the row is 0 ≥ 0 in GAMS and in the port)."],
    },
    "eq_Canadian_Imports": {
        "summary": "Seasonal cap on generation from the Canadian import technology.",
        "math": r"""
\P{can\_imports\_szn}_{r,szn,t} \;\ge\; \sum_{(i,v)\in\mathrm{valgen},\ i\in\mathrm{canada},\ h\in szn}\V{GEN}_{i,v,r,h,t}\P{hours}_h
\qquad \P{can\_imports\_szn}_{r,szn,t}\neq0,\ \mathrm{Sw\_Canada}=1
""",
        "terms": [
            ("can_imports_szn", r"\P{can\_imports\_szn}", "canimp_const (derive_temporal: import energy × seasonal fraction, rounded to 3 decimals as in e_solveprep)", "ported (constant)"),
            ("sum GEN * hours", r"\sum\V{GEN}\P{hours}", "canimp_gen (−hours)", "ported"),
            ("row set", r"", "rows with a GEN term only (GAMS CONVERT drops the others)", "ported"),
        ],
        "prep": [("if int(case.scalar(\"Sw_Canada\")) == 1:", 'P.coef["canimp_gen"]')],
        "build": ['"eq_Canadian_Imports"'],
    },
    "eq_mingen_fixed": {
        "summary": "Technologies with a fixed minimum generation fraction must run at least that fraction of available capacity.",
        "math": r"""
\V{GEN}_{i,v,r,h,t} \;\ge\; \P{mingen\_fixed}_i\,\P{avail}_{i,r,h}\,\V{CAP}_{i,v,r,t}
\qquad \mathrm{Sw\_MingenFixed},\ \P{mingen\_fixed}_i\neq0,\ \mathrm{valgen},\ t\ge\mathrm{Sw\_StartMarkets}
""",
        "terms": [
            ("GEN", r"\V{GEN}", "mgf_gen (+1)", "ported"),
            ("mingen_fixed * avail * CAP", r"\P{mingen\_fixed}\P{avail}\V{CAP}", "mgf_cap (−mf·avail)", "ported"),
        ],
        "prep": [("if int(case.scalar(\"Sw_MingenFixed\")):", 'P.coef["mgf_cap"]')],
        "build": ['"eq_mingen_fixed"'],
    },
    "eq_min_cf": {
        "summary": "Minimum annual capacity factor of a technology fleet in a zone.",
        "math": r"""
\sum_{v:\ \mathrm{valgen},\ h\in h_{rep}}\P{hours}_h\V{GEN}_{i,v,r,h,t} \;\ge\; \sum_{v:\ \mathrm{valgen}}\V{CAP}_{i,v,r,t}\cdot\sum_{h\in h_{rep}}\P{hours}_h\cdot\P{minCF}_{i,t}
\qquad \P{minCF}_{i,t}\neq0,\ \mathrm{valgen\_irt}(i,r,t),\ \mathrm{Sw\_MinCF}
""",
        "terms": [
            ("sum hours * GEN $h_rep", r"\sum\P{hours}\V{GEN}", "mincf_gen (+hours) on representative hours", "ported"),
            ("sum CAP * sum hours * minCF", r"\sum_v\V{CAP}\cdot H_{rep}\cdot\P{minCF}", "mincf_cap = −((1·H_rep)·minCF) with H_rep = fsum of representative hours, in GAMS evaluation order", "ported"),
        ],
        "prep": [("if int(case.scalar(\"Sw_MinCF\")):", 'P.coef["mincf_cap"]')],
        "build": ['"eq_min_cf"'],
    },
    "eq_max_daily_cf": {
        "summary": "Maximum seasonal (daily) capacity factor for technologies with maxdailycf.",
        "math": r"""
\sum_{v}\V{CAP}_{i,v,r,t}\cdot\sum_{h\in szn}\P{hours}_h\P{avail}_{i,r,h}\cdot\P{maxdailycf}_{i,t} \;\ge\; \sum_{v,\ h\in szn}\P{hours}_h\V{GEN}_{i,v,r,h,t}
\qquad \P{maxdailycf}_{i,t}\neq0,\ \textstyle\sum_{h\in szn}\P{avail}_{i,r,h}\neq0,\ \mathrm{valgen\_irt},\ \mathrm{Sw\_MaxDailyCF}
""",
        "terms": [
            ("sum CAP * sum hours*avail * maxdailycf", r"\sum_v\V{CAP}\cdot HA_{szn}\cdot\P{maxdailycf}", "maxcf_cap = (1·ha)·mdc with ha = fsum over the season of hours × avail", "ported"),
            ("sum hours * GEN", r"\sum\P{hours}\V{GEN}", "maxcf_gen (−hours)", "ported"),
            ("row condition sum avail ≠ 0", r"", "av_szn filter", "ported"),
        ],
        "prep": [("if int(case.scalar(\"Sw_MaxDailyCF\")):", 'P.coef["maxcf_gen"]')],
        "build": ['"eq_max_daily_cf"'],
    },
    "eq_caa_max_cf": {
        "summary": "Clean Air Act section 111: capacity-factor cap on new gas plants.",
        "math": r"""
\sum_{h\in h_{rep}}\P{hours}_h\cdot\P{caa\_gas\_max\_cf}\cdot\V{CAP}_{i,v,r,t} \;\ge\; \sum_{h\in h_{rep}}\P{hours}_h\V{GEN}_{i,v,r,h,t}
\qquad \mathrm{valgen},\ i\in\mathrm{gas}\setminus\mathrm{ccs},\ \P{heat\_rate}\neq0,\ \P{firstyear\_v}_{i,v}\ge\P{caa\_first\_year},\ t\ge\P{caa\_coal\_retire\_year},\ \mathrm{Sw\_Clean\_Air\_Act}
""",
        "terms": [
            ("sum hours * caa_gas_max_cf * CAP", r"H_{rep}\,\P{caa\_gas\_max\_cf}\,\V{CAP}", "caa_cap (+H_rep·caa_gas_max_cf)", "ported"),
            ("sum hours * GEN", r"\sum\P{hours}\V{GEN}", "caa_gen (−hours)", "ported"),
        ],
        "prep": [("if int(case.scalar(\"Sw_Clean_Air_Act\")):", 'P.coef["caa_gen"]')],
        "build": ['"eq_caa_max_cf"'],
    },
    "eq_caa_rate_standard": {
        "summary": "Clean Air Act section 111 rate standard for coal: emissions cannot exceed what capturing at the standard rate would give.",
        "math": r"""
(1-\P{caa\_capture\_rate\_standard})\sum_{\substack{(i,v,r,h):\ \mathrm{valgen},\ i\in\mathrm{coal}\setminus\mathrm{cofire},\\ r\in st,\ h\in h_{rep}}}\P{hours}_h\big(\P{emit\_rate}_{\mathrm{proc},CO2,i,v,r,t}+\P{capture\_rate}_{CO2,i,v,r,t}\big)\V{GEN}_{i,v,r,h,t}
 \;\ge\; \sum_{\text{same}}\P{hours}_h\,\P{emit\_rate}_{\mathrm{proc},CO2,i,v,r,t}\V{GEN}_{i,v,r,h,t}
\qquad t\ge\P{caa\_coal\_retire\_year},\ \mathrm{Sw\_Clean\_Air\_Act}
""",
        "terms": [
            ("both GEN sums", r"\P{hours}\big((er+cr)(1-std)-er\big)\V{GEN}", "caars_gen: one coefficient per GEN column, ((hours·(er+cr))·(1−std)) + (−(hours·er)), with missing er/cr as 0", "ported"),
            ("row set", r"", "(st, t) rows with at least one coal GEN column", "ported"),
        ],
        "prep": [("std = case.scalar(\"caa_capture_rate_standard\")", 'P.coef["caars_gen"]')],
        "build": ['"eq_caa_rate_standard"'],
    },
    "eq_bioused": {
        "summary": "Biomass used in a zone equals the fuel burned by biopower and the biomass share of cofiring.",
        "math": r"""
\sum_{bioclass}\V{BIOUSED}_{bioclass,r,t} \;=\; \sum_{(i,v)\in\mathrm{valgen},\ i\in\mathrm{bio},\ h}\P{hours}_h\P{heat\_rate}_{i,v,r,t}\V{GEN}_{i,v,r,h,t}
 + \sum_{i\in\mathrm{cofire}}\P{bio\_cofire\_perc}\,\P{hours}_h\P{heat\_rate}\V{GEN}
\qquad r\text{ with a bio or cofire technology in valgen}
""",
        "terms": [
            ("sum BIOUSED", r"\sum\V{BIOUSED}", "bio_used (+1); BIOUSED columns = bioclass × zones with bio/cofire valgen", "ported"),
            ("hours * heat_rate * GEN (bio)", r"\P{hours}\P{heat\_rate}\V{GEN}", "bio_gen = −(hours·hr) for bio techs", "ported"),
            ("bio_cofire_perc * hours * heat_rate * GEN (cofire)", r"\P{bcp}\P{hours}\P{heat\_rate}\V{GEN}", "bio_gen = −((bcp·hours)·hr) for cofire techs", "ported"),
        ],
        "prep": [('P.con["eq_bioused"] = bio_r', 'P.coef["bio_gen"] = bio_gen')],
        "build": ['"eq_bioused"'],
    },
    "eq_biousedlimit": {
        "summary": "Biomass supply by USDA region and class.",
        "math": r"""
\P{biosupply}_{usda,bioclass,\mathrm{cap}} \;\ge\; \sum_{r\in usda\text{ with bio valgen}}\V{BIOUSED}_{bioclass,r,t}
""",
        "terms": [
            ("biosupply(usda,bioclass,cap)", r"\P{biosupply}_{cap}", "biolim_const = biosupply_cap (derive_ops: supply curve cap × 1e6 × 13 MMBtu/ton × Sw_BioSupply, rounded to 3 decimals)", "ported (constant)"),
            ("sum BIOUSED", r"\sum_r\V{BIOUSED}", "biolim_used (−1) mapped through r_usda", "ported"),
            ("row set", r"", "GAMS writes every (bioclass, usda, t); rows without a BIOUSED column are dropped by CONVERT and by the port", "ported"),
        ],
        "prep": [("bl_dom = case[\"bioclass\"]", 'P.coef["biolim_used"]')],
        "build": ['"eq_biousedlimit"'],
    },
    "eq_batterymandate": {
        "summary": "State battery storage mandate.",
        "math": r"""
\sum_{(i,v,r):\ r\in st,\ \mathrm{valcap},\ i\in\mathrm{battery}\cup\mathrm{pvb}}\P{bcr}_i\V{CAP}_{i,v,r,t} \;\ge\; \P{batterymandate}_{st,t}
\qquad \P{batterymandate}_{st,t}\neq0,\ t\ge\P{firstyear\_battery},\ \mathrm{Sw\_BatteryMandate}
""",
        "terms": [
            ("sum bcr * CAP", r"\sum\P{bcr}\V{CAP}", "bmand_cap (bcr, missing → 0)", "ported"),
            ("batterymandate", r"\P{batterymandate}", "bmand_const (−batterymandate)", "ported (constant)"),
            ("row set", r"", "rows with at least one CAP column", "ported"),
        ],
        "prep": [("if int(case.scalar(\"Sw_BatteryMandate\")):", 'P.coef["bmand_cap"]')],
        "build": ['"eq_batterymandate"'],
    },
}
