from __future__ import annotations

NETUP = r"\sum_{\substack{(ii,tt):\ tt\in\mathcal{T},\ tt\le t,\\ (ii,v,r,tt)\in\mathrm{valcap},\ \mathrm{upgrade\_from}(ii,i)}}\big(\V{UPGRADES}_{ii,v,r,tt}-\V{UPGRADES\_RETIRE}_{ii,v,r,tt}[ii\notin\mathrm{noret\_upgrade\_tech}]\big)\sw{Sw\_Upgrades=1}"
NETUP_TERMS = [
    ("− UPGRADES(ii,v,r,t) + UPGRADES_RETIRE(ii,v,r,t) (right side, tt = t)", r"-\V{UPGRADES}_{ii,t}+\V{UPGRADES\_RETIRE}_{ii,t}",
     "*_up (−1) and *_ret (+1) from _netup_cur; variable index ii renamed through II = {i: ii}", "ported"),
    ("right-side net upgrades for tt in tfix", r"-\sum_{tt<t}(\overline{\V{UPGRADES}}-\overline{\V{UPGRADES\_RETIRE}})",
     "_netup_past(domain, 't') subtracted into the constant (state_UPGRADES, state_UPGRADES_RETIRE)", "ported (constant from state)"),
    ("Sw_Upgrades = 2 terms", r"(\ldots)\sw{Sw\_Upgrades=2}", "absent", "not ported; prep raises when Sw_Upgrades=2"),
]
STOCK_PRE = [("sw_up = int(case.scalar(\"Sw_Upgrades\"))", "dn = case[\"degrade_new\"]"), ("if sw_ref:", 'P.var["INV_ENER_UP"] = allow_ener')]

SPEC: dict[str, dict] = {
    "eq_cap_init_retmo": {
        "summary": "Retirable existing capacity cannot grow: this year's capacity is at most last year's, net of upgrades, plus upsizing.",
        "math": r"""
\sum_{tt:\ \mathrm{tprev}(t,tt),\ (i,v,r,tt)\in\mathrm{valcap}}\Big[\V{CAP}_{i,v,r,tt}
 + \sum_{\substack{(ii,ttt):\ ttt\in\mathcal{T},\ ttt\le tt,\\ \mathrm{valcap}(ii,v,r,ttt),\ \mathrm{upgrade\_from}(ii,i)}}\big(\V{UPGRADES}_{ii,v,r,ttt}-\V{UPGRADES\_RETIRE}_{ii,v,r,ttt}[ii\notin\mathrm{noret}]\big)\sw{Sw\_Upgrades=1} + (\ldots)\sw{Sw\_Upgrades=2}\Big]
 + \sum_{rscbin:\ \mathrm{allow\_cap\_up}(i,v,r,rscbin,t)}\V{INV\_CAP\_UP}_{i,v,r,rscbin,t} \\
 \;\ge\; \V{CAP}_{i,v,r,t} + """ + NETUP + r""" + (\ldots)\sw{Sw\_Upgrades=2}
""",
        "where": [r"Rows: \((i,v,r,t)\in\mathrm{valcap}\cap\mathrm{retiretech}\), \(v\in\mathrm{initv}\), \(i\notin\mathrm{upgrade}\). Every variable indexed by a prior year is a constant in the port."],
        "terms": [
            ("CAP(i,v,r,tprev)", r"\overline{\V{CAP}}_{t^-}", "retmo_init_const via _prev_cap(degrade=False): state_CAP at tprev where valcap(i,v,r,tprev)", "ported (constant from state)"),
            ("left-side net upgrades up to tprev", r"\sum_{ttt\le t^-}(\overline{\V{UPGRADES}}-\overline{\V{UPGRADES\_RETIRE}})", "_netup_past(prev rows, 'tt') added in _prev_cap", "ported (constant); cancels the right-side prior-year part exactly, so only the current-year columns remain"),
            ("sum INV_CAP_UP(t)", r"\sum_{rscbin}\V{INV\_CAP\_UP}_t", "retmo_init_capup from _capup_terms(degrade=False) (coefficient 1)", "ported (empty: allow_cap_up raises in derive_temporal)"),
            ("CAP(i,v,r,t)", r"\V{CAP}_t", "retmo_init_cap (−1)", "ported"),
        ] + NETUP_TERMS,
        "prep": STOCK_PRE + [('P.con["eq_cap_init_retmo"]', 'P.coef["retmo_init_capup"]')],
        "build": ['"eq_cap_init_retmo"'],
        "helpers": ["_prev_cap", "_netup_past", "_netup_cur", "_capup_terms", "_row"],
        "notes": ["If the technology had no valcap row in the previous year the GAMS left side is empty and the row reads 0 ≥ CAP + …; _prev_cap gives the same because the prev join is empty and _on_domain fills 0."],
    },
    "eq_cap_init_retub": {
        "summary": "Retirable existing capacity is bounded above by the exogenous capacity, net of upgrades.",
        "math": r"""
\P{m\_capacity\_exog}_{i,v,r,t}\P{degrade\_init}_{i,v,r,t}
 + \sum_{(tt,rscbin):\ tt\in\mathcal{T},\ \mathrm{allow\_cap\_up}(i,v,r,rscbin,tt)}\P{degrade\_new}_{i,tt,t}\V{INV\_CAP\_UP}_{i,v,r,rscbin,tt}
 \;\ge\; \V{CAP}_{i,v,r,t} + """ + NETUP + r""" + (\ldots)\sw{Sw\_Upgrades=2}
""",
        "where": [r"Rows as eq_cap_init_retmo (valcap ∩ retiretech, initv, not upgrade)."],
        "terms": [
            ("m_capacity_exog * degrade_init", r"\P{m\_capacity\_exog}\P{degrade\_init}", "retub_init_const: _mul(m_capacity_exog, degrade_init) on the rows (exog, shared with eq_cap_init_noret)", "ported (constant)"),
            ("degrade_new * INV_CAP_UP, current and past", r"\P{degrade\_new}\V{INV\_CAP\_UP}", "retub_init_capup (degrade_new(i,t,t)), capup_past into the constant", "ported (empty in practice)"),
            ("CAP", r"\V{CAP}_t", "retub_init_cap (−1)", "ported"),
        ] + NETUP_TERMS,
        "prep": [('P.con["eq_cap_init_retub"]', 'P.coef["retub_init_cap"]')],
        "build": ['"eq_cap_init_retub"'],
        "helpers": ["_mul", "_capup_terms", "_netup_past", "_netup_cur", "_row"],
    },
    "eq_cap_new_retmo": {
        "summary": "Retirable new capacity cannot exceed last year's degraded capacity plus this year's investment, refurbishment and upsizing, net of upgrades.",
        "math": r"""
\sum_{tt:\ \mathrm{tprev}(t,tt),\ \mathrm{valcap}(i,v,r,tt)}\Big[\P{degrade\_new}_{i,tt,t}\V{CAP}_{i,v,r,tt} + (\text{net upgrades up to }tt)\sw{Sw\_Upgrades=1}+(\ldots)\sw{Sw\_Upgrades=2}\Big]
 + \V{INV}_{i,v,r,t}[\mathrm{valinv}] + \V{INV\_REFURB}_{i,v,r,t}[\mathrm{valinv},\ i\in\mathrm{refurbtech}]\sw{Sw\_Refurb}
 + \sum_{rscbin}\V{INV\_CAP\_UP}_{i,v,r,rscbin,t} \\
 \;\ge\; \V{CAP}_{i,v,r,t} + """ + NETUP + r""" + (\ldots)\sw{Sw\_Upgrades=2}
""",
        "where": [r"Rows: \((i,v,r,t)\in\mathrm{valcap}\cap\mathrm{retiretech}\), \(v\in\mathrm{newv}\), \(i\notin\mathrm{upgrade}\)."],
        "terms": [
            ("degrade_new(i,tprev,t) * CAP(tprev)", r"\P{degrade\_new}_{i,t^-,t}\overline{\V{CAP}}_{t^-}", "retmo_new_const via _prev_cap(degrade=True): state_CAP × degrade_new(i,tprev,t)", "ported (constant from state)"),
            ("left-side net upgrades up to tprev (not degraded)", r"\sum_{ttt\le t^-}(\ldots)", "_netup_past(prev rows, 'tt') in _prev_cap", "ported (constant)"),
            ("INV(i,v,r,t) $valinv", r"\V{INV}_t", "retmo_new_inv (+1 on INV rows inside the row domain)", "ported"),
            ("INV_REFURB(i,v,r,t)", r"\V{INV\_REFURB}_t", "retmo_new_refurb (+1), empty when Sw_Refurb=0", "ported"),
            ("sum INV_CAP_UP(t)", r"\sum\V{INV\_CAP\_UP}_t", "retmo_new_capup (coefficient 1)", "ported (empty in practice)"),
            ("CAP(t)", r"\V{CAP}_t", "retmo_new_cap (−1)", "ported"),
        ] + NETUP_TERMS,
        "prep": [('P.con["eq_cap_new_retmo"]', 'P.coef["retmo_new_cap"]')],
        "build": ['"eq_cap_new_retmo"'],
        "helpers": ["_prev_cap", "_netup_past", "_netup_cur", "_capup_terms", "_signed", "_row"],
    },
    "eq_cap_new_retub": {
        "summary": "Retirable new capacity is bounded above by degraded cumulative investment minus prescribed retirements, net of upgrades.",
        "math": r"""
\sum_{tt\in\mathcal{T}:\ \mathrm{inv\_cond}(i,v,r,t,tt),\ \mathrm{valcap}(i,v,r,tt)}\P{degrade\_new}_{i,tt,t}\big(\V{INV}_{i,v,r,tt}+\V{INV\_REFURB}_{i,v,r,tt}[\mathrm{refurbtech}]\sw{Sw\_Refurb}\big)
 - \P{prescr}_{i,v,r,t}
 + \sum_{(tt,rscbin)}\P{degrade\_new}_{i,tt,t}\V{INV\_CAP\_UP}_{i,v,r,rscbin,tt}
 \;\ge\; \V{CAP}_{i,v,r,t} + """ + NETUP + r""" + (\ldots)\sw{Sw\_Upgrades=2}
""",
        "where": [r"Rows as eq_cap_new_retmo. \(\P{prescr}\) is the degraded prescribed-retirement sum defined under eq_cap_new_noret."],
        "terms": [
            ("degrade_new(i,t,t) * INV(t)", r"\P{degrade\_new}_{i,t,t}\V{INV}_t", "retub_new_inv from _stock_terms; variable t renamed tt then summed to (i,v,r,t)", "ported"),
            ("degrade_new * INV(tt), tt in tfix, − prescr", r"\sum_{tt<t}\P{degrade\_new}\overline{\V{INV}} - \P{prescr}", "const from _stock_terms(state_INV, slice_prescr_ret)", "ported (constant)"),
            ("degrade_new * INV_REFURB(tt)", r"\P{degrade\_new}\V{INV\_REFURB}", "retub_new_refurb (current), const_ref (state_INV_REFURB)", "ported"),
            ("degrade_new * INV_CAP_UP(tt)", r"\P{degrade\_new}\V{INV\_CAP\_UP}", "retub_new_capup, capup_past", "ported (empty in practice)"),
            ("CAP(t)", r"\V{CAP}_t", "retub_new_cap (−1)", "ported"),
        ] + NETUP_TERMS,
        "prep": [('P.con["eq_cap_new_retub"]', 'P.coef["retub_new_cap"]')],
        "build": ['"eq_cap_new_retub"'],
        "helpers": ["_stock_terms", "_capup_terms", "_netup_past", "_netup_cur", "_add", "_row"],
    },
    "eq_forceprescription_power": {
        "summary": "Investment in prescribed technologies equals the prescribed build, with a free slack once the technology is available (or for state offshore-wind requirements).",
        "math": r"""
\V{INV}_{i,v,r,t} + \V{INV\_REFURB}_{i,v,r,t}[i\in\mathrm{refurbtech}]\sw{Sw\_Refurb}
 \;=\; \P{prescribed\_build}_{i,v,r,t}
 + \V{EXTRA\_PRESCRIP}_{i,v,r,t}\,[t\ge\P{firstyear}_i]
 + \V{EXTRA\_PRESCRIP}_{i,v,r,t}\,[\mathrm{r\_offshore}(r,t),\ i\in\mathrm{ofswind},\ t\ge\P{firstyear\_RPS},\ \textstyle\sum_{st\ni r}\P{offshore\_cap\_req}_{st,t}\neq0]
""",
        "where": [r"Rows: \(v\in\mathrm{newv}\), \(\mathrm{force\_prescribe}(i,v,r,t)\), \((i,v,r,t)\in\mathrm{valinv}\), Sw_ForcePrescription on."],
        "terms": [
            ("INV", r"\V{INV}", "fp_inv (+1)", "ported"),
            ("INV_REFURB $[refurbtech$Sw_Refurb]", r"\V{INV\_REFURB}", "fp_refurb (+1) on INV_REFURB rows in the domain", "ported"),
            ("prescribed_build", r"\P{prescribed\_build}", "fp_build = −prescribed_build on the rows (zeros filled)", "ported (constant)"),
            ("EXTRA_PRESCRIP $[t>=firstyear(i)]", r"\V{EXTRA\_PRESCRIP}", "k1 = 1 where t ≥ firstyear(i)", "ported"),
            ("EXTRA_PRESCRIP $[r_offshore$ofswind$...]", r"\V{EXTRA\_PRESCRIP}", "k2 = 1 where the offshore conditions hold; fp_extra = −(k1 + k2), so the coefficient is 2 when both hold, as in GAMS where the variable appears twice", "ported"),
            ("EXTRA_PRESCRIP column set", r"", "P.var[EXTRA_PRESCRIP] = rows with k ≠ 0 (a column that appears in no row is dropped by GAMS CONVERT)", "ported"),
        ],
        "prep": [("if sw_fp:", 'P.var["EXTRA_PRESCRIP_ENERGY"] = ke')],
        "build": ['"eq_forceprescription_power"', '"eq_forceprescription_energy"'],
        "helpers": ["_on_domain", "_signed", "_row"],
    },
    "eq_forceprescription_energy": {
        "summary": "Battery energy investment equals the prescribed energy build plus a free slack once the technology is available.",
        "math": r"""
\V{INV\_ENERGY}_{i,v,r,t} \;=\; \P{prescribed\_build\_energy}_{i,v,r,t} + \V{EXTRA\_PRESCRIP\_ENERGY}_{i,v,r,t}\,[t\ge\P{firstyear}_i]
\qquad\text{rows of eq\_forceprescription\_power with } i\in\mathrm{battery}
""",
        "terms": [
            ("INV_ENERGY", r"\V{INV\_ENERGY}", "fpe_inv (+1)", "ported"),
            ("prescribed_build_energy", r"\P{prescribed\_build\_energy}", "fpe_build = −prescribed_build_energy", "ported (constant)"),
            ("EXTRA_PRESCRIP_ENERGY $[t>=firstyear(i)]", r"\V{EXTRA\_PRESCRIP\_ENERGY}", "fpe_extra (−1) on rows with k1 ≠ 0; those rows are the column set", "ported"),
        ],
        "prep": [("fpe_dom = _in(fp_dom", 'P.var["EXTRA_PRESCRIP_ENERGY"] = ke')],
        "build": ['"eq_forceprescription_energy"'],
    },
    "eq_refurblim": {
        "summary": "Refurbishment cannot exceed the capacity that has reached the end of its life (expired investment plus exogenous retirements).",
        "math": r"""
\sum_{(vv,tt):\ \mathrm{m\_refurb\_cond}(i,vv,r,t,tt),\ tt\in\mathcal{T},\ (i,vv,r,tt)\in\mathrm{valinv}}\V{INV}_{i,vv,r,tt}
 + \sum_{(v,tt):\ tt\le t}\P{avail\_retire\_exog\_rsc}_{i,v,r,tt}
 \;\ge\; \sum_{(vv,tt):\ \mathrm{inv\_cond}(i,vv,r,t,tt),\ tt\in\mathcal{T},\ \mathrm{valinv}(i,vv,r,tt)}\V{INV\_REFURB}_{i,vv,r,tt}
\qquad i\in\mathrm{refurbtech},\ \text{every } r,\ \mathrm{Sw\_Refurb}
""",
        "terms": [
            ("INV(i,vv,r,t) with m_refurb_cond(i,vv,r,t,t)", r"\V{INV}_{vv,t}", "refurblim_inv (+1), variable v renamed vv, summed to (i,r,t)", "ported"),
            ("INV(i,vv,r,tt), tt in tfix", r"\sum_{tt<t}\overline{\V{INV}}", "past_inv (state_INV over m_refurb_cond rows with valinv_tfix) into refurblim_const", "ported (constant)"),
            ("sum avail_retire_exog_rsc(tt<=t) over all v, all years", r"\sum_{v,tt\le t}\P{avail\_retire\_exog\_rsc}", "avail: all years ≤ t, not only solved years (derive_case already trims to t ≤ year)", "ported (constant)"),
            ("INV_REFURB(i,vv,r,t) with inv_cond(i,vv,r,t,t)", r"\V{INV\_REFURB}_{vv,t}", "refurblim_refurb (−1)", "ported"),
            ("INV_REFURB(tt), tt in tfix", r"\sum_{tt<t}\overline{\V{INV\_REFURB}}", "past_ref subtracted into refurblim_const", "ported (constant)"),
            ("row set", r"", "rows kept only where a current-year INV or INV_REFURB column exists; GAMS CONVERT drops the others (count in P.options)", "ported"),
        ],
        "prep": [('rl_dom = case["refurbtech"]', 'P.options["refurblim_rows_without_variables"]')],
        "build": ['"eq_refurblim"'],
        "helpers": ["_on_domain", "_add", "_row"],
    },
    "eq_cap_rsc": {
        "summary": "Capacity by supply-curve bin equals exogenous bin capacity plus cumulative bin investment.",
        "math": r"""
\sum_{tt\in\mathrm{tfirst}}\P{capacity\_exog\_rsc}_{i,v,r,rscbin,tt}[i\in\mathrm{exog\_rsc}]
 + \sum_{tt\in\mathcal{T}:\ tt\le t,\ \mathrm{m\_rscfeas}(r,i,rscbin),\ (i,v,r,tt)\in\mathrm{valinv}}\V{INV\_RSC}_{i,v,r,rscbin,tt}
 \;=\; \V{CAP\_RSC}_{i,v,r,rscbin,t}
\qquad i\in\mathrm{rsc\_i}\setminus\mathrm{sccapcosttech},\ (i,v,r,t)\in\mathrm{valcap},\ \text{every } rscbin
""",
        "terms": [
            ("capacity_exog_rsc in tfirst $exog_rsc", r"\P{capacity\_exog\_rsc}", "exog0 summed over tfirst years, into cap_rsc_const", "ported (constant)"),
            ("INV_RSC(t)", r"\V{INV\_RSC}_t", "cap_rsc_inv (+1) on INV_RSC columns inside the row domain", "ported"),
            ("INV_RSC(tt), tt in tfix", r"\sum_{tt<t}\overline{\V{INV\_RSC}}", "past_rsc (state_INV_RSC with m_rscfeas and valinv_tfix) into cap_rsc_const", "ported (constant)"),
            ("CAP_RSC", r"\V{CAP\_RSC}", "cap_rsc_cap (−1); CAP_RSC columns = the row domain", "ported"),
        ],
        "prep": [("rsc_cap_dom = (_not_in(_in(valcap", 'P.coef["cap_rsc_cap"]')],
        "build": ['"eq_cap_rsc"'],
        "notes": ["The rscbin index is unconditioned in GAMS, so every bin (feasible or not) gets a row and a CAP_RSC column; infeasible bins have no INV_RSC term and reduce to CAP_RSC = exogenous."],
    },
    "eq_cap_upgrade": {
        "summary": "Upgraded capacity equals derated cumulative upgrade purchases minus retired upgrades.",
        "math": r"""
\sum_{\substack{tt\in\mathcal{T}:\ tt\le t,\ tt\ge\mathrm{Sw\_UpgradeYear},\ \mathrm{valcap}(i,v,r,tt),\\ \exists ii:\ \mathrm{upgrade\_from}(i,ii)\wedge\mathrm{valcap}(ii,v,r,tt),\ [tt\le\P{caa\_coal\_retire\_year}\text{ if }i\in\mathrm{coal}]}}
 \V{UPGRADES}_{i,v,r,tt}\,(1-\P{upgrade\_derate}_{i,v,r,tt})\;\sw{Sw\_Upgrades=1} + (\ldots)\sw{Sw\_Upgrades=2}
 \;=\; \V{CAP}_{i,v,r,t} + \sum_{tt\in\mathcal{T}:\ \mathrm{valcap}(i,v,r,tt)}\V{UPGRADES\_RETIRE}_{i,v,r,tt}\,[i\notin\mathrm{noret\_upgrade\_tech}]
\qquad i\in\mathrm{upgrade},\ (i,v,r,t)\in\mathrm{valcap}
""",
        "terms": [
            ("UPGRADES(t) * (1 − upgrade_derate(t))", r"(1-\P{upgrade\_derate}_t)\V{UPGRADES}_t", "cap_upgrade_up: rows of from_ok with t ≥ Sw_UpgradeYear and (not coal or t ≤ caa_coal_retire_year)", "ported"),
            ("UPGRADES(tt) * (1 − derate(tt)), tt in tfix", r"\sum_{tt<t}(1-\P{upgrade\_derate}_{tt})\overline{\V{UPGRADES}}", "past (state_UPGRADES with the same conditions at tt) into cap_upgrade_const", "ported (constant)"),
            ("CAP", r"\V{CAP}", "cap_upgrade_cap (−1)", "ported"),
            ("UPGRADES_RETIRE(t) $[not noret]", r"\V{UPGRADES\_RETIRE}_t", "cap_upgrade_ret (−1) on the UPGRADES_RETIRE columns (which exclude noret techs)", "ported"),
            ("UPGRADES_RETIRE(tt), tt in tfix", r"\sum_{tt<t}\overline{\V{UPGRADES\_RETIRE}}", "ret_past subtracted into cap_upgrade_const", "ported (constant)"),
            ("Sw_Upgrades = 2 terms", r"(\ldots)", "absent", "not ported; guarded"),
        ],
        "prep": [("uy = case.scalar(\"Sw_UpgradeYear\")", 'P.coef["cap_upgrade_cap"]')],
        "build": ['"eq_cap_upgrade"'],
        "helpers": ["_on_domain", "_add", "_signed", "_row"],
    },
    "eq_cap_up": {
        "summary": "Cumulative capacity upsizing is limited by the allowed upsizing.",
        "math": r"""
\P{cap\_cap\_up}_{i,v,r,rscbin,t} \;\ge\; \sum_{tt\in\mathcal{T}}\V{INV\_CAP\_UP}_{i,v,r,rscbin,tt}\qquad \mathrm{allow\_cap\_up}(i,v,r,rscbin,t)
""",
        "terms": [
            ("cap_cap_up", r"\P{cap\_cap\_up}", "eq_cap_up_const = cap_cap_up − prior-year INV_CAP_UP (state)", "ported (constant)"),
            ("INV_CAP_UP(t)", r"\V{INV\_CAP\_UP}_t", "eq_cap_up_inv (−1)", "ported"),
        ],
        "prep": [("for name, allow_now, var, cap_tab, state in", 'P.coef[f"{name}_inv"]')],
        "build": ['"eq_cap_up"', '"eq_ener_up"'],
        "notes": ["allow_cap_up and cap_cap_up are empty tables in the port: derive_temporal raises if allow_cap_up has rows because cost_cap_up / cap_cap_up are not derived. The equation code is therefore unexercised."],
    },
    "eq_ener_up": {
        "summary": "Cumulative energy upsizing is limited by the allowed upsizing.",
        "math": r"""
\P{cap\_ener\_up}_{i,v,r,rscbin,t} \;\ge\; \sum_{tt\in\mathcal{T}}\V{INV\_ENER\_UP}_{i,v,r,rscbin,tt}\qquad \mathrm{allow\_ener\_up}(i,v,r,rscbin,t)
""",
        "terms": [
            ("cap_ener_up", r"\P{cap\_ener\_up}", "eq_ener_up_const = cap_ener_up − prior-year INV_ENER_UP", "ported (constant)"),
            ("INV_ENER_UP(t)", r"\V{INV\_ENER\_UP}_t", "eq_ener_up_inv (−1)", "ported"),
        ],
        "prep": [("for name, allow_now, var, cap_tab, state in", 'P.coef[f"{name}_inv"]')],
        "build": ['"eq_ener_up"'],
        "notes": ["Same caveat as eq_cap_up: allow_ener_up is empty, so the code path is unexercised."],
    },
}
