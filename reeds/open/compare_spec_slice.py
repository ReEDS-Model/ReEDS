from __future__ import annotations

OPRES_GAP = ("<b>No guard:</b> if Sw_OpRes were 1 the OPRES / OPRES_FLOW terms of this equation would be missing from the port "
             "(the port creates the OPRES columns and the reserve equations but does not add OPRES to the capacity, storage and transmission limits). "
             "Both reference cases run with GSw_OpRes=2 but their operating-reserve period set (opres_periods) maps to no modeled season, so opres_h is empty and no reserve row exists.")

SPEC: dict[str, dict] = {
    "eq_loadcon": {
        "summary": "Defines busbar load so that its dual is the marginal energy price. Only the exogenous load, Canada exports and production load are active.",
        "math": r"""
\V{LOAD}_{r,h,t} \;=\; \P{load\_exog\_static}_{r,h,t}
 + \P{can\_exports\_h}_{r,h,t}\,\sw{Sw\_Canada=1}
 + \P{evmc\_baseline\_load}_{r,h,t}\,\sw{Sw\_EVMC}
 + \sum_{(i,v)\in\mathrm{evmc\_shape}\cap\mathrm{valcap}_{r,t}} \P{evmc\_shape\_load}_{i,r,h}\,\V{CAP}_{i,v,r,t}
 + \sum_{f}\V{FLEX}_{f,r,h,t}\,\sw{Sw\_EFS\_flex} \\
 \quad + \sum_{\substack{(p,i,v):\ i\in\mathrm{consume},\ (i,v,r,t)\in\mathrm{valcap},\\ \mathrm{i\_p}(i,p),\ i\neq\text{dac\_gas}}}
   \frac{\V{PRODUCE}_{p,i,v,r,h,t}}{\P{prod\_conversion\_rate}_{i,v,r,t}}\;\sw{Sw\_Prod}\,[h\in h_{rep}]
 + \Big(\sum_{s\in\mathrm{h2\_stor\_r}(r)} \P{h2\_network\_load}_{s,t}(\V{H2\_STOR\_IN}+\V{H2\_STOR\_OUT})_{s,r,h,t}
   + \sum_{rr\in\mathrm{h2\_routes}(r)} \P{h2\_network\_load}_{\text{comp},t}\tfrac{\V{H2\_FLOW}_{r,rr,h,t}+\V{H2\_FLOW}_{rr,r,h,t}}{2}\Big)\sw{Sw\_H2\_CompressorLoad} \\
 \quad + \V{OP\_LOADSITE}_{r,h,t}\,[0<\mathrm{Sw\_LoadSiteCF}<1] + \V{CAP\_LOADSITE}_{r,t}\,[\mathrm{Sw\_LoadSiteCF}=1]
""",
        "terms": [
            ("LOAD(r,h,t)", r"\V{LOAD}_{r,h,t}", "load_var (+1) × LOAD", "ported"),
            ("load_exog_static(r,h,t)", r"\P{load\_exog\_static}_{r,h,t}", "load_neg: −(load_exog_static + can_exports_h) on every (r,h,t) row, zeros filled", "ported (constant)"),
            ("can_exports_h(r,h,t)$[Sw_Canada=1]", r"\P{can\_exports\_h}_{r,h,t}\sw{Sw\_Canada=1}", "folded into load_neg; derive_temporal leaves can_exports_h empty unless Sw_Canada=1", "ported (constant)"),
            ("evmc_baseline_load$Sw_EVMC, sum evmc_shape_load*CAP", r"\P{evmc\_baseline\_load},\ \P{evmc\_shape\_load}\,\V{CAP}", "absent", "not ported; derive_ops raises only for evmc_storage techs, evmc_shape techs have <b>no guard</b>"),
            ("sum{flex_type, FLEX}$Sw_EFS_flex", r"\sum_f \V{FLEX}_{f,r,h,t}", "absent", "not ported; derive_temporal raises when flexible load is present"),
            ("sum PRODUCE/prod_conversion_rate $[Sw_Prod$h_rep(h)]", r"\sum \V{PRODUCE}/\P{prod\_conversion\_rate}", "load_produce: −1/prod_conversion_rate on PRODUCE(p,i,v,r,h,t), i≠dac_gas, h∈h_rep; _row sums over (p,i,v)", "ported"),
            ("H2 compressor loads $Sw_H2_CompressorLoad", r"\P{h2\_network\_load}\,(\V{H2\_STOR\_IN}+\ldots)", "absent", "not ported; prep raises when Sw_H2_CompressorLoad"),
            ("OP_LOADSITE / CAP_LOADSITE", r"\V{OP\_LOADSITE},\ \V{CAP\_LOADSITE}", "absent", "not ported; prep raises when Sw_LoadSiteCF"),
        ],
        "prep": [('P.con["eq_loadcon"]', 'P.coef["load_var"]'), 'P.coef["load_produce"] = (prod_dom'],
        "build": ['"eq_loadcon"'],
        "helpers": ["_on_domain", "_add", "_signed", "_row"],
        "notes": ["The row domain is every (r, h, t) with t in tmodel, as in GAMS (no $-condition beyond tmodel).",
                  "PRODUCE columns exist only for representative hours, so the h_rep condition is carried by the column domain."],
    },
    "eq_supply_demand_balance": {
        "summary": "Zonal energy balance. Generation plus net imports minus storage charging equals load.",
        "math": r"""
\sum_{(i,v)\in\mathrm{valgen}_{r,t},\ r\in\mathrm{land}} \V{GEN}_{i,v,r,h,t}
 + \sum_{(rr,\tau)\in\mathrm{routes}(rr,r,\tau,t),\ \tau\in\mathrm{notvsc}} (1-\P{tranloss}_{rr,r,\tau})\,\V{FLOW}_{rr,r,h,t,\tau}
 - \sum_{(rr,\tau)\in\mathrm{routes}(r,rr,\tau,t),\ \tau\in\mathrm{notvsc}} \V{FLOW}_{r,rr,h,t,\tau} \\
 \quad + \big(\V{CONVERSION}_{r,h,\mathrm{VSC}\to\mathrm{AC},t}\,\P{\eta}_{vsc} - \V{CONVERSION}_{r,h,\mathrm{AC}\to\mathrm{VSC},t}/\P{\eta}_{vsc}\big)\sw{Sw\_VSC}
 - \sum_{(i,v)\in\mathrm{valcap}_{r,t},\ i\in\mathrm{storage\_standalone}\cup\mathrm{hyd\_add\_pump}} \V{STORAGE\_IN}_{i,v,r,h,t}
 - \sum_{i\in\mathrm{storage\_hybrid}\setminus\mathrm{csp}} \V{STORAGE\_IN\_GRID}_{i,v,r,h,t}\,\sw{Sw\_HybridPlant}
 + (\V{DROPPED}_{r,h,t}-\V{EXCESS}_{r,h,t})\,[t<\mathrm{Sw\_StartMarkets}]
 \;=\; \V{LOAD}_{r,h,t}
""",
        "terms": [
            ("sum GEN $[valgen$land(r)]", r"\sum \V{GEN}", "bal_gen: GEN rows with r in land (coefficient 1); within(...).sum_by(r,h,t)", "ported"),
            ("sum (1-tranloss)*FLOW(rr,r) $[routes$notvsc]", r"\sum(1-\P{tranloss})\V{FLOW}_{rr,r}", "bal_import: (1 − tranloss) on every AC and LCC route (r,rr,trtype,t), trtype in notvsc; summed by (rr,h,t) then rr renamed to r (receiving zone)", "ported"),
            ("− sum FLOW(r,rr) $[routes$notvsc]", r"-\sum \V{FLOW}_{r,rr}", "bal_export (+1 on notvsc routes) × FLOW, summed by (r,h,t), entered with coefficient −1", "ported"),
            ("CONVERSION(VSC→AC)·η − CONVERSION(AC→VSC)/η $[Sw_VSC$val_converter]", r"\V{CONVERSION}\cdot\eta_{vsc}", "bal_conv: +η on (intype vsc, outtype ac), −1/η on (ac, vsc); CONVERSION columns = val_converter × h × both directions", "ported, no columns in either reference case (no VSC routes)"),
            ("− sum STORAGE_IN $[valcap$(storage_standalone or hyd_add_pump)]", r"-\sum\V{STORAGE\_IN}", "bal_stor_in: STORAGE_IN rows semi-joined to valcap", "ported for storage_standalone; <b>no guard</b>: the STORAGE_IN column is not created for hyd_add_pump techs (prep line 'stor_in_techs')"),
            ("− sum STORAGE_IN_GRID $Sw_HybridPlant", r"-\sum\V{STORAGE\_IN\_GRID}", "absent", "not ported; prep raises when Sw_HybridPlant and hybrid non-CSP techs are in valgen"),
            ("DROPPED − EXCESS", r"\V{DROPPED}-\V{EXCESS}", "absent", "not ported; prep raises when t < Sw_StartMarkets"),
            ("LOAD(r,h,t)", r"\V{LOAD}_{r,h,t}", "−LOAD (keep_extras)", "ported"),
        ],
        "prep": [('P.con["eq_supply_demand_balance"]', 'P.coef["bal_stor_in"]')],
        "build": ['"eq_supply_demand_balance"'],
        "helpers": ["U"],
        "notes": ["hyd_add_pump is the set {hyded_pumped-hydro, hyded_pumped-hydro-flex} ∩ i; it is empty unless hydro pump upgrades are enabled, but nothing stops a run in which it is not."],
    },
    "eq_capacity_limit": {
        "summary": "Available capacity bounds generation for dispatchable, hydro and non-dispatchable (curtailable VRE) technologies. The whole left side is one precomposed coefficient κ.",
        "math": r"""
\underbrace{\Big[\P{avail}_{i,r,h}\,\P{derate\_geo\_vintage}_{i,v}\,(1+\textstyle\sum_{szn}\P{h\_szn}_{h,szn}\P{seas\_cap\_frac\_delta}_{i,v,r,szn,t})\Big]_{i\in\mathrm{dispatchtech}\setminus\mathrm{hydro\_d}}
 + \Big[\P{avail}_{i,r,h}\,\textstyle\sum_{szn\ni h}\P{cap\_hyd\_szn\_adj}_{i,szn,r}\,(1+\P{hydro\_capcredit\_delta}_{i,t}[h\in h_{stress}])\Big]_{i\in\mathrm{hydro\_d}}
 + \Big[\textstyle\sum_{c\in\mathrm{i\_c}(i)}\P{m\_cf}_{i,c,v,r,h,t}\Big]_{i\notin\mathrm{dispatchtech}}}_{\kappa_{i,v,r,h,t}}\;\V{CAP}_{i,v,r,t} \\
 \quad + \Big[\textstyle\sum_c \P{m\_cf}\Big]_{i\notin\mathrm{dispatchtech}}\sum_{(tt,rscbin)}\big(\V{INV\_ENER\_UP}_{i,v,r,rscbin,tt} - \P{degrade\_new}_{i,tt,t}\V{INV\_CAP\_UP}_{i,v,r,rscbin,tt}\big)
 + \P{evmc\_shape\_gen}_{i,r,h}\V{CAP}_{i,v,r,t} \\
 \;\ge\; \V{GEN}_{i,v,r,h,t} + \sum_{o\in\mathrm{opres\_model},\ \P{reserve\_frac}_{i,o}\neq 0,\ h\in\mathrm{opres\_h}} \V{OPRES}_{o,i,v,r,h,t}\,\sw{Sw\_OpRes}
 + \V{CCSFLEX\_POW}_{i,v,r,h,t}\,[i\in\mathrm{ccsflex}]\sw{Sw\_CCSFLEX\_*}
""",
        "where": [r"Rows: \((i,v,r,t)\in\mathrm{valgen}\), \(i\notin\mathrm{spur\_techs}\cup\mathrm{storage\_standalone}\cup(\mathrm{storage\_hybrid}\setminus\mathrm{csp})\cup\mathrm{nondispatch}\), every \(h\)."],
        "terms": [
            ("avail * derate_geo_vintage * (1 + seas delta) * CAP $[dispatchtech$(not hydro_d)]", r"\kappa\,\V{CAP}", "caplim = slice_cap_coef (term1 in derive_temporal.slice_coefficients) × CAP", "ported (precomposed)"),
            ("avail * CAP * cap_hyd_szn_adj * (1 + hydro_capcredit_delta$h_stress) $hydro_d", r"\kappa\,\V{CAP}", "slice_cap_coef term2", "ported (precomposed)"),
            ("sum{c, m_cf} * CAP $[not dispatchtech]", r"\kappa\,\V{CAP}", "slice_cap_coef term3 (m_cf summed over c with fsum)", "ported (precomposed)"),
            ("m_cf * (INV_ENER_UP − degrade_new*INV_CAP_UP)", r"\sum(\V{INV\_ENER\_UP}-\P{degrade\_new}\V{INV\_CAP\_UP})", "absent", "not ported; derive_temporal raises when allow_cap_up has rows"),
            ("evmc_shape_gen * CAP", r"\P{evmc\_shape\_gen}\,\V{CAP}", "absent", "not ported; <b>no guard</b> for evmc_shape techs"),
            ("GEN(i,v,r,h,t)", r"\V{GEN}", "−GEN (drop_extras restricts GEN to the row set)", "ported"),
            ("sum OPRES $[Sw_OpRes...]", r"\sum_o\V{OPRES}", "absent", OPRES_GAP),
            ("CCSFLEX_POW", r"\V{CCSFLEX\_POW}", "absent", "not ported; prep raises when any Sw_CCSFLEX_* is on"),
        ],
        "prep": [('cl_techs = (set(', 'P.coef["caplim_nd"]')],
        "build": ['"eq_capacity_limit"', '"eq_capacity_limit_nd"'],
        "derive": [("reeds/open/derive_temporal.py", "dispatch = members(S.dispatchtech)", 'S["slice_cap_coef"]')],
        "notes": ["κ is stored only where nonzero; a (i,v,r,h) row with κ=0 still exists in GAMS (GEN ≤ 0) and in the port because the row domain is the GEN domain filtered by technology, with κ filled as 0 by _on_domain."],
    },
    "eq_capacity_limit_nd": {
        "summary": "Non-dispatchable technologies (distpv, non-curtailable) must generate exactly their capacity factor times capacity.",
        "math": r"""
\sum_{c\in\mathrm{i\_c}(i)}\P{m\_cf}_{i,c,v,r,h,t}\;\V{CAP}_{i,v,r,t} \;=\; \V{GEN}_{i,v,r,h,t}
 + \sum_{o\in\mathrm{opres\_model},\ \P{reserve\_frac}_{i,o}\neq0,\ h\in\mathrm{opres\_h}}\V{OPRES}_{o,i,v,r,h,t}\,\sw{Sw\_OpRes}
\qquad (i,v,r,t)\in\mathrm{valgen},\ i\in\mathrm{nondispatch}
""",
        "terms": [
            ("sum{c, m_cf} * CAP", r"\sum_c\P{m\_cf}\,\V{CAP}", "caplim_nd = slice_cap_coef restricted to nondispatch rows (term3 only, because nondispatch ⊂ not dispatchtech)", "ported (precomposed)"),
            ("GEN", r"\V{GEN}", "−GEN", "ported"),
            ("sum OPRES", r"\sum_o\V{OPRES}", "absent", OPRES_GAP),
        ],
        "prep": [('P.con["eq_capacity_limit_nd"]', 'P.coef["caplim_nd"]')],
        "build": ['"eq_capacity_limit_nd"'],
    },
    "eq_cap_init_noret": {
        "summary": "Existing (initial-vintage) capacity that cannot retire equals the exogenous capacity, net of upgrades away from the technology.",
        "math": r"""
\P{m\_capacity\_exog}_{i,v,r,t}\,\P{degrade\_init}_{i,v,r,t}
 + \sum_{(tt,rscbin):\ tt\in\mathcal{T},\ \mathrm{allow\_cap\_up}(i,v,r,rscbin,tt)} \P{degrade\_new}_{i,tt,t}\,\V{INV\_CAP\_UP}_{i,v,r,rscbin,tt}
\;=\; \V{CAP}_{i,v,r,t}
 + \sum_{\substack{(ii,tt):\ tt\in\mathcal{T},\ tt\le t,\\ (ii,v,r,tt)\in\mathrm{valcap},\ \mathrm{upgrade\_from}(ii,i)}} \big(\V{UPGRADES}_{ii,v,r,tt} - \V{UPGRADES\_RETIRE}_{ii,v,r,tt}[ii\notin\mathrm{noret\_upgrade\_tech}]\big)\sw{Sw\_Upgrades=1}
 + (\ldots)\sw{Sw\_Upgrades=2}
""",
        "where": [r"Rows: \((i,v,r,t)\in\mathrm{valcap}\), \(v\in\mathrm{initv}\), \(i\notin\mathrm{upgrade}\), \((i,v,r,t)\notin\mathrm{retiretech}\)."],
        "terms": [
            ("m_capacity_exog * degrade_init", r"\P{m\_capacity\_exog}\,\P{degrade\_init}", "cap_init: _mul(m_capacity_exog, degrade_init) on the row domain", "ported (constant)"),
            ("sum degrade_new * INV_CAP_UP(tt), tt = t", r"\P{degrade\_new}_{i,t,t}\V{INV\_CAP\_UP}_{t}", "noret_init_capup from _capup_terms(degrade=True)", "ported (allow_cap_up rows raise in derive_temporal, so empty in practice)"),
            ("sum degrade_new * INV_CAP_UP(tt), tt in tfix", r"\P{degrade\_new}_{i,tt,t}\,\overline{\V{INV\_CAP\_UP}}_{tt}", "capup_past (state_INV_CAP_UP) added to cap_init", "ported (constant from state)"),
            ("CAP(i,v,r,t)", r"\V{CAP}", "noret_init_cap (−1)", "ported"),
            ("− UPGRADES(ii,v,r,t) + UPGRADES_RETIRE(ii,v,r,t), tt = t", r"-\V{UPGRADES}_{ii,t}+\V{UPGRADES\_RETIRE}_{ii,t}", "noret_init_up (−1), noret_init_ret (+1) from _netup_cur; variable index ii renamed via II", "ported"),
            ("prior-year UPGRADES − UPGRADES_RETIRE, tt in tfix", r"-\sum_{tt<t}(\overline{\V{UPGRADES}}-\overline{\V{UPGRADES\_RETIRE}})", "_netup_past(noret_init, 't') subtracted from cap_init", "ported (constant from state)"),
            ("Sw_Upgrades = 2 terms", r"(\ldots)\sw{Sw\_Upgrades=2}", "absent", "not ported; prep raises when Sw_Upgrades=2"),
        ],
        "prep": [("not_ret = valcap.join(retiretech", 'P.coef["cap_init"] = _on_domain'), ("noret_init = P.con", 'P.coef["noret_init_cap"]')],
        "build": ['"eq_cap_init_noret"'],
        "helpers": ["_mul", "_capup_terms", "_netup_cur", "_netup_past", "_row"],
    },
    "eq_cap_new_noret": {
        "summary": "New-vintage capacity that cannot retire equals degraded cumulative investment minus prescribed retirements, net of upgrades.",
        "math": r"""
\sum_{tt\in\mathcal{T}:\ \mathrm{inv\_cond}(i,v,r,t,tt),\ (i,v,r,tt)\in\mathrm{valcap}} \P{degrade\_new}_{i,tt,t}\big(\V{INV}_{i,v,r,tt} + \V{INV\_REFURB}_{i,v,r,tt}[i\in\mathrm{refurbtech}]\sw{Sw\_Refurb}\big)
 - \underbrace{\sum_{(tt,ttt):\ \mathrm{inv\_cond}(i,v,r,tt,ttt),\ tt\in\mathcal{T},\ ttt\le tt\le t} \P{degrade\_new}_{i,ttt,tt}\,\P{prescribed\_retirements}_{i,v,r,tt,ttt}}_{\P{prescr}_{i,v,r,t}}
 + \sum_{(tt,rscbin)} \P{degrade\_new}_{i,tt,t}\V{INV\_CAP\_UP}_{i,v,r,rscbin,tt} \\
 \;=\; \V{CAP}_{i,v,r,t} + \sum_{(ii,tt\le t)}\big(\V{UPGRADES}_{ii,v,r,tt}-\V{UPGRADES\_RETIRE}_{ii,v,r,tt}\big)\sw{Sw\_Upgrades=1} + (\ldots)\sw{Sw\_Upgrades=2}
""",
        "where": [r"Rows: \((i,v,r,t)\in\mathrm{valcap}\), \(v\in\mathrm{newv}\), \(i\notin\mathrm{upgrade}\), not in retiretech."],
        "terms": [
            ("degrade_new(i,t,t) * INV(i,v,r,t)", r"\P{degrade\_new}_{i,t,t}\V{INV}_t", "cap_new_inv from _stock_terms (inv_cond rows with tt in tmodel joined to degrade_new); variable t renamed tt, summed back to (i,v,r,t)", "ported"),
            ("degrade_new * INV(tt), tt in tfix", r"\sum_{tt<t}\P{degrade\_new}_{i,tt,t}\overline{\V{INV}}_{tt}", "cap_new_const (past_c in _stock_terms from state_INV)", "ported (constant from state)"),
            ("degrade_new * INV_REFURB(tt)", r"\P{degrade\_new}\,\V{INV\_REFURB}", "noret_new_refurb (current) and const_ref (state_INV_REFURB) via _stock_terms", "ported"),
            ("− sum degrade_new * prescribed_retirements", r"-\P{prescr}", "slice_prescr_ret precomposed in derive_temporal.slice_coefficients (prescr) and subtracted in _stock_terms", "ported (precomposed)"),
            ("degrade_new * INV_CAP_UP", r"\P{degrade\_new}\V{INV\_CAP\_UP}", "noret_new_capup / capup_past", "ported (empty in practice, see eq_cap_init_noret)"),
            ("CAP", r"\V{CAP}", "noret_new_cap (−1)", "ported"),
            ("net upgrades, current and past", r"\V{UPGRADES}-\V{UPGRADES\_RETIRE}", "noret_new_up, noret_new_ret, _netup_past", "ported"),
            ("Sw_Upgrades = 2 terms", r"(\ldots)", "absent", "not ported; prep raises"),
        ],
        "prep": [('P.con["eq_cap_new_noret"]', 'P.coef["cap_new_inv"], P.coef["cap_new_const"]'), ("noret_new = P.con", 'P.coef["noret_new_cap"]')],
        "build": ['"eq_cap_new_noret"'],
        "derive": [("reeds/open/derive_temporal.py", "years = {str(y) for y in S.years}", 'S["slice_prescr_ret_energy"]')],
        "helpers": ["_stock_terms", "_capup_terms", "_netup_cur", "_netup_past", "_add", "_row"],
    },
    "eq_cap_energy_new_noret": {
        "summary": "Battery energy capacity equals degraded cumulative energy investment minus prescribed energy retirements plus exogenous energy capacity.",
        "math": r"""
\sum_{tt\in\mathcal{T}:\ \mathrm{inv\_cond}(i,v,r,t,tt),\ \mathrm{valcap}(i,v,r,tt)} \P{degrade\_new}_{i,tt,t}\V{INV\_ENERGY}_{i,v,r,tt}
 - \sum_{(tt,ttt)} \P{degrade\_new}_{i,ttt,tt}\P{prescribed\_retirements\_energy}_{i,v,r,tt,ttt}
 + \P{m\_capacity\_exog\_energy}_{i,v,r,t} \;=\; \V{CAP\_ENERGY}_{i,v,r,t}
\qquad (i,v,r,t)\in\mathrm{valcap},\ i\in\mathrm{battery}
""",
        "terms": [
            ("degrade_new * INV_ENERGY(t)", r"\P{degrade\_new}_{i,t,t}\V{INV\_ENERGY}_t", "cap_energy_inv (_stock_terms with INV_ENERGY)", "ported"),
            ("degrade_new * INV_ENERGY(tt), tt in tfix", r"\sum_{tt<t}\ldots\overline{\V{INV\_ENERGY}}", "cap_energy_const (state_INV_ENERGY)", "ported (constant)"),
            ("− prescribed_retirements_energy term", r"-\P{prescr}^{E}", "slice_prescr_ret_energy (same prescr() as eq_cap_new_noret)", "ported (precomposed)"),
            ("m_capacity_exog_energy", r"\P{m\_capacity\_exog\_energy}", "extra_name in _stock_terms", "ported (constant)"),
            ("CAP_ENERGY", r"\V{CAP\_ENERGY}", "− CAP_ENERGY", "ported"),
        ],
        "prep": [('P.con["eq_cap_energy_new_noret"]', 'P.coef["cap_energy_inv"], P.coef["cap_energy_const"]')],
        "build": ['"eq_cap_energy_new_noret"'],
        "helpers": ["_stock_terms", "U"],
        "notes": ["Unlike the power equations this one has no retiretech split and no upgrade terms, and it is written in every battery valcap row regardless of vintage."],
    },
    "eq_rsc_inv_account": {
        "summary": "Investment in a supply-curve technology is the sum of its bin investments.",
        "math": r"""
\sum_{rscbin\in\mathrm{m\_rscfeas}(r,i)} \V{INV\_RSC}_{i,v,r,rscbin,t} \;=\; \V{INV}_{i,v,r,t}
\qquad (i,v,r,t)\in\mathrm{valinv},\ i\in\mathrm{rsc\_i}
""",
        "terms": [
            ("sum INV_RSC over feasible bins", r"\sum_{rscbin}\V{INV\_RSC}", "INV_RSC.sum_by(i,v,r,t); the column set already excludes bins fixed at zero by flag_eq_rsc_INVlim", "ported"),
            ("INV", r"\V{INV}", "−INV restricted (within) to the rsc_valinv domain", "ported"),
        ],
        "prep": [("rsc_valinv = _in(valinv", "inv_rsc = rsc_valinv.join"), ('P.con["eq_rsc_inv_account"]', None)],
        "build": ['"eq_rsc_inv_account"'],
        "notes": ["If every bin of an (i,v,r,t) is fixed at zero the row still exists in GAMS with only INV, forcing INV = 0; in the port the row comes from INV (keep_extras) with no INV_RSC term, which is the same row."],
    },
    "eq_rsc_INVlim": {
        "summary": "Cumulative investment in a supply-curve bin cannot exceed the bin's remaining capacity. The gross bin capacity is precomposed; prior-year investment comes from the state tables.",
        "math": r"""
\underbrace{\Big(\P{m\_rsc\_dat}_{r,i,rscbin,\mathrm{cap}} - \sum_{(ii,v,tt):\ \mathrm{tfirst}(tt),\ \mathrm{rsc\_agg}(i,ii),\ i\in\mathrm{exog\_rsc}}\P{capacity\_exog\_rsc}_{ii,v,r,rscbin,tt}\Big)
 \big(1[i\notin\mathrm{rsc\_capacity\_scalar\_i}] + \P{rsc\_capacity\_scalar}_{i,r,t}[i\in\mathrm{rsc\_capacity\_scalar\_i}]\big)
 + \P{hyd\_add\_upg\_cap}_{r,i,rscbin,t}\,[\mathrm{Sw\_HydroCapEnerUpgradeType}=1]}_{\P{rsc\_cap}_{r,i,rscbin,t}} \\
 \;\ge\; \sum_{(ii,v,tt):\ (ii,v,r,tt)\in\mathrm{valinv},\ tt\le t,\ \mathrm{rsc\_agg}(i,ii)} \V{INV\_RSC}_{ii,v,r,rscbin,tt}\,\P{resourcescaler}_{ii}
""",
        "where": [r"Rows: \(i\in\mathrm{rsc\_i}\), \(\mathrm{m\_rscfeas}(r,i,rscbin)\), \(\mathrm{m\_rsc\_con}(r,i)\), and not flagged: GAMS sets flag_eq_rsc_INVlim where the right-hand side (gross capacity minus prior investment) is below rhs_tolerance, drops the row and fixes INV_RSC of that bin to 0."],
        "terms": [
            ("(m_rsc_dat cap − exog) * scalar + hyd_add_upg_cap", r"\P{rsc\_cap}", "slice_rsc_cap precomposed in derive_temporal (gross); rsc_lim_rhs = gross − past", "ported (precomposed)"),
            ("− sum INV_RSC(ii,tt) * resourcescaler, tt in tfix", r"-\sum_{tt<t}\overline{\V{INV\_RSC}}_{ii,tt}\P{resourcescaler}_{ii}", "past (state_INV_RSC × resourcescaler, aggregated over ii by rsc_agg) subtracted into rsc_lim_rhs", "ported (constant from state)"),
            ("sum INV_RSC(ii,t) * resourcescaler(ii)", r"\sum_{ii,v}\P{resourcescaler}_{ii}\V{INV\_RSC}_{ii,v,r,rscbin,t}", "rsc_lim_use: resourcescaler on INV_RSC(ii), row key (r,i,rscbin,t) via rsc_agg; variable i renamed ii", "ported"),
            ("flag_eq_rsc_INVlim and INV_RSC.fx = 0", r"\text{rows dropped, columns removed}", "flagged / fixed: rows with |rhs| < rhs_tolerance removed from P.con and their INV_RSC columns removed from P.var (GAMS holdfixed=1)", "ported (e_solveprep logic)"),
        ],
        "prep": [("rsc_agg = case[\"rsc_agg\"]", 'P.coef["rsc_lim_use"]')],
        "build": ['"eq_rsc_INVlim"'],
        "derive": [("reeds/open/derive_temporal.py", "cap = S.m_rsc_dat.filter", 'S["slice_rsc_cost"]')],
        "notes": ["The GAMS row index is (r, i, rscbin, t), with i the numeraire technology of rsc_agg; investing technologies ii map onto it."],
    },
    "eq_storage_capacity": {
        "summary": "Second capacity limit for storage: charging plus discharging (plus reserves) cannot exceed available power capacity.",
        "math": r"""
\underbrace{\P{bcr}_i\,\P{avail}_{i,r,h}\,(1+\textstyle\sum_{szn}\P{h\_szn}_{h,szn}\P{seas\_cap\_frac\_delta}_{i,v,r,szn,t})}_{\kappa^{s}_{i,v,r,h,t}}\,\V{CAP}_{i,v,r,t}\,[\mathrm{valcap}]
 \;\ge\; \frac{\V{GEN}_{i,v,r,h,t}[i\notin\mathrm{storage\_hybrid}\setminus\mathrm{csp}]}{1[i\notin\mathrm{evmc}]+\P{evmc\_storage\_discharge\_frac}[i\in\mathrm{evmc}]}
 + \V{GEN\_STORAGE}\sw{Sw\_HybridPlant}
 + \frac{\V{STORAGE\_IN}_{i,v,r,h,t}}{1[i\notin\mathrm{evmc}]+\P{evmc\_storage\_charge\_frac}[i\in\mathrm{evmc}]}
 + (\V{STORAGE\_IN\_PLANT}+\V{STORAGE\_IN\_GRID})\sw{Sw\_HybridPlant}
 + \sum_{o}\P{reserve\_frac}_{i,o}\V{OPRES}_{o,i,v,r,h,t}\sw{Sw\_OpRes}
""",
        "where": [r"Rows: \((i,v,r,t)\in\mathrm{valgen}\), \(i\in\mathrm{storage\_standalone}\setminus\mathrm{evmc}\) (evmc and hybrid alternatives off), every \(h\)."],
        "terms": [
            ("CAP * bcr * avail * (1 + seas delta) $valcap", r"\kappa^{s}\V{CAP}", "stor_cap = slice_stor_cap_coef (derive_temporal) on the row domain", "ported (precomposed)"),
            ("GEN / evmc discharge frac", r"\V{GEN}", "−GEN.drop_extras()", "ported for non-evmc (divisor 1); evmc techs raise in derive_ops"),
            ("STORAGE_IN / evmc charge frac", r"\V{STORAGE\_IN}", "−STORAGE_IN.drop_extras()", "ported for non-evmc"),
            ("GEN_STORAGE, STORAGE_IN_PLANT, STORAGE_IN_GRID", r"\ldots\sw{Sw\_HybridPlant}", "absent", "not ported; prep raises when hybrid non-CSP techs are in valgen with Sw_HybridPlant"),
            ("sum reserve_frac * OPRES", r"\sum_o\P{reserve\_frac}\V{OPRES}", "absent", OPRES_GAP),
        ],
        "prep": [("sc_techs = (S[\"storage_standalone\"]", 'P.coef["stor_cap"]')],
        "build": ['"eq_storage_capacity"'],
        "derive": [("reeds/open/derive_temporal.py", "bcr = S.bcr.rename", 'S["slice_stor_cap_coef"]')],
    },
    "eq_storage_duration": {
        "summary": "Storage level cannot exceed energy capacity: duration × power capacity for fixed-duration storage, CAP_ENERGY for batteries.",
        "math": r"""
\underbrace{\P{storage\_duration\_m}_{i,v,r}\big(1[i\in\mathrm{csp\_storage}]+1[i\in\mathrm{psh}]+\P{bcr}_i[i\in\mathrm{pvb}]\big)}_{d_{i,v,r}}\V{CAP}_{i,v,r,t}
 + \P{evmc\_storage\_energy\_hours}_{i,r,h,t}\P{bcr}_i\V{CAP}_{i,v,r,t}[i\in\mathrm{evmc}]
 + \V{CAP\_ENERGY}_{i,v,r,t}[i\in\mathrm{battery}] \;\ge\; \V{STORAGE\_LEVEL}_{i,v,r,h,t}
""",
        "where": [r"Rows: \((i,v,r,t)\in\mathrm{valgen}\cap\mathrm{valcap}\), \(i\in\mathrm{storage}\setminus\mathrm{storage\_interday}\), every \(h\)."],
        "terms": [
            ("storage_duration_m * CAP * (1$CSP_Storage + 1$psh + bcr$pvb)", r"d\,\V{CAP}", "stor_dur_cap = slice_dur_coef (derive_temporal) broadcast to the (i,v,r,h,t) rows", "ported (precomposed)"),
            ("evmc_storage_energy_hours * CAP * bcr $evmc", r"\ldots[i\in\mathrm{evmc}]", "absent", "not ported; evmc techs raise in derive_ops"),
            ("CAP_ENERGY $battery", r"\V{CAP\_ENERGY}", "stor_dur_energy (+1 on battery rows)", "ported"),
            ("STORAGE_LEVEL", r"\V{STORAGE\_LEVEL}", "−STORAGE_LEVEL", "ported"),
        ],
        "prep": [('P.con["eq_storage_duration"]', 'P.coef["stor_dur_energy"]')],
        "build": ['"eq_storage_duration"'],
        "derive": [("reeds/open/derive_temporal.py", "mult = (pl.when(isin(\"i\", members(S.csp_storage)))", 'S["slice_dur_coef"]')],
        "notes": ["For a battery with no psh/csp membership d = 0 and the row reduces to CAP_ENERGY ≥ STORAGE_LEVEL, as in GAMS."],
    },
    "eq_storage_level": {
        "summary": "Storage inventory balance between a timeslice and its successor.",
        "math": r"""
\sum_{hh:\ \mathrm{nexth}(h,hh)}\V{STORAGE\_LEVEL}_{i,v,r,hh,t}[i\notin\mathrm{interday}] + \V{STORAGE\_INTERDAY\_DISPATCH}_{i,v,r,h,t}\P{hd}_h[i\in\mathrm{interday}]
\;=\; \V{STORAGE\_LEVEL}_{i,v,r,h,t}[i\notin\mathrm{interday}]
 + \P{storage\_eff}_{i,t}\P{hd}_h\Big(\V{STORAGE\_IN}_{i,v,r,h,t}[i\in\mathrm{storage\_standalone}\cup\mathrm{hyd\_add\_pump}] + \V{CAP}_{i,v,r,t}\P{csp\_sm}_i\textstyle\sum_c\P{m\_cf}[i\in\mathrm{csp\_storage}]\Big) \\
 \quad + \V{CAP}\,\P{avail}\,\P{hd}_h\textstyle\sum_{szn\ni h}\P{m\_cf\_szn}[i\in\mathrm{hyd\_add\_pump}]
 + (\P{storage\_eff\_pvb\_p}\P{hd}\V{STORAGE\_IN\_PLANT} + \P{storage\_eff\_pvb\_g}\P{hd}\V{STORAGE\_IN\_GRID})\sw{Sw\_HybridPlant}
 - \P{hd}_h\V{GEN}_{i,v,r,h,t}[i\notin\mathrm{storage\_hybrid}\setminus\mathrm{csp}] - \P{hd}_h\V{GEN\_STORAGE}\sw{Sw\_HybridPlant}
 - \P{hd}_h\,\V{OPRES}_{\mathrm{reg/combo},i,v,r,h,t}\tfrac{1-\P{storage\_eff}_{i,t}}{2}\P{reg\_energy\_frac}\,[h\in\mathrm{opres\_h}]\sw{Sw\_OpRes}
""",
        "where": [r"Rows: \((i,v,r,t)\in\mathrm{valgen}\), \(i\in\mathrm{storage}\), every \(h\); the port builds rows on the STORAGE_LEVEL domain, which excludes interday storage (guarded)."],
        "terms": [
            ("sum{hh$nexth(h,hh), STORAGE_LEVEL(hh)}", r"\V{STORAGE\_LEVEL}_{hh}", "nxt: STORAGE_LEVEL renamed h→hh and mapped through the nexth table (coefficient 1)", "ported"),
            ("STORAGE_LEVEL(h)", r"\V{STORAGE\_LEVEL}_{h}", "−STORAGE_LEVEL", "ported"),
            ("storage_eff * hours_daily * STORAGE_IN", r"\P{storage\_eff}\P{hd}\V{STORAGE\_IN}", "stor_lvl_in = storage_eff(i,t) × hours_daily(h), coefficient −1× on the right side", "ported for storage_standalone; <b>no guard</b> for hyd_add_pump (no STORAGE_IN column)"),
            ("storage_eff * hours_daily * CAP * csp_sm * m_cf $CSP_Storage", r"\ldots\V{CAP}\P{csp\_sm}\sum_c\P{m\_cf}", "absent", "<b>no guard</b>: csp_storage techs in valgen would get a row without the solar-field charging term (neither reference case has CSP in valgen)"),
            ("CAP * avail * hours_daily * m_cf_szn $hyd_add_pump", r"\V{CAP}\P{avail}\P{hd}\P{m\_cf\_szn}", "absent", "<b>no guard</b> (hyd_add_pump)"),
            ("hybrid plant charging terms", r"\ldots\sw{Sw\_HybridPlant}", "absent", "not ported; guarded"),
            ("− hours_daily * GEN", r"-\P{hd}\V{GEN}", "stor_lvl_gen = +hours_daily(h) on GEN over the row domain", "ported"),
            ("− hours_daily * GEN_STORAGE", r"-\P{hd}\V{GEN\_STORAGE}", "absent", "not ported; guarded"),
            ("− reg-reserve losses", r"-\P{hd}\V{OPRES}\tfrac{1-\eta}{2}\P{reg\_energy\_frac}", "absent", OPRES_GAP),
            ("interday dispatch", r"\V{STORAGE\_INTERDAY\_DISPATCH}", "absent", "not ported; prep raises when interday storage techs are in valgen"),
        ],
        "prep": [('P.con["eq_storage_level"]', 'P.coef["stor_lvl_gen"]')],
        "build": ['"eq_storage_level"'],
        "notes": ["Row = next level − (level + charge − discharge) = 0; the build subtracts the right side as U(level, charge, −discharge)."],
    },
    "eq_CAPTRAN_ENERGY": {
        "summary": "Energy-trading transmission capacity equals initial capacity plus cumulative investment.",
        "math": r"""
\V{CAPTRAN\_ENERGY}_{r,rr,\tau,t} \;=\; \P{trancap\_init\_energy}_{r,rr,\tau} + \sum_{tt\in\mathcal{T},\ tt\le t,\ \mathrm{routes\_inv}(r,rr,\tau,tt)} \V{INVTRAN}_{r,rr,\tau,tt}
\qquad \mathrm{routes}(r,rr,\tau,t)
""",
        "terms": [
            ("CAPTRAN_ENERGY", r"\V{CAPTRAN\_ENERGY}", "+CAPTRAN_ENERGY", "ported"),
            ("trancap_init_energy", r"\P{trancap\_init\_energy}", "captran_e_const = −(init + past)", "ported (constant)"),
            ("sum INVTRAN(tt), tt in tfix", r"\sum_{tt<t}\overline{\V{INVTRAN}}", "past_tran from state_INVTRAN folded into captran_e_const", "ported (constant from state)"),
            ("INVTRAN(t)", r"\V{INVTRAN}_t", "inv_tran term when the INVTRAN column exists (routes_inv non-empty)", "ported, no rows with INVTRAN in either reference case (routes_inv empty)"),
        ],
        "prep": [('P.con["eq_CAPTRAN_ENERGY"]', 'P.coef["captran_p_inv"]')],
        "build": ['"eq_CAPTRAN_ENERGY"', '"eq_CAPTRAN_PRM"'],
    },
    "eq_CAPTRAN_PRM": {
        "summary": "PRM-trading transmission capacity equals initial PRM capacity plus derated cumulative investment.",
        "math": r"""
\V{CAPTRAN\_PRM}_{r,rr,\tau,t} \;=\; \P{trancap\_init\_prm}_{r,rr,\tau} + (1-\mathrm{Sw\_TransInvPRMderate})\sum_{tt\in\mathcal{T},\ tt\le t,\ \mathrm{routes\_inv}} \V{INVTRAN}_{r,rr,\tau,tt}
\qquad \mathrm{routes}(r,rr,\tau,t),\ \mathrm{routes\_prm}(r,rr)
""",
        "terms": [
            ("CAPTRAN_PRM", r"\V{CAPTRAN\_PRM}", "+CAPTRAN_PRM", "ported"),
            ("trancap_init_prm + (1−derate) sum past INVTRAN", r"\P{trancap\_init\_prm}+(1-\delta)\sum_{tt<t}\overline{\V{INVTRAN}}", "captran_p_const", "ported (constant)"),
            ("(1−derate) INVTRAN(t)", r"(1-\delta)\V{INVTRAN}_t", "captran_p_inv: −(1 − derate) on INVTRAN within the CAPTRAN_PRM domain", "ported, no rows with INVTRAN in either case"),
        ],
        "prep": [('P.con["eq_CAPTRAN_ENERGY"]', 'P.coef["captran_p_inv"]')],
        "build": ['"eq_CAPTRAN_ENERGY"', '"eq_CAPTRAN_PRM"'],
    },
    "eq_transmission_limit": {
        "summary": "Flow on a line is limited by the energy capacity in representative hours and by the PRM capacity in stress hours.",
        "math": r"""
\V{CAPTRAN\_ENERGY}_{r,rr,\tau,t}(1+\P{trans\_cap\_delta}_{h,t})[h\in h_{rep}]
 + \V{CAPTRAN\_PRM}_{r,rr,\tau,t}(1+\P{trans\_cap\_delta}_{h,t})[h\in h_{stress},\ \mathrm{routes\_prm}(r,rr)]
 \;\ge\; \V{FLOW}_{r,rr,h,t,\tau} + \sum_{o\in\mathrm{opres\_model}}\V{OPRES\_FLOW}_{o,r,rr,h,t}\,\P{opres\_mult}\,[\tau\in\mathrm{aclike},\ \mathrm{opres\_routes}(r,rr,t),\ h\in\mathrm{opres\_h}]\sw{Sw\_OpRes}
""",
        "terms": [
            ("CAPTRAN_ENERGY * (1 + trans_cap_delta) $h_rep", r"\V{CAPTRAN\_ENERGY}(1+\delta_{h,t})", "tlim_rep: (1 + trans_cap_delta) on the representative-hour rows × CAPTRAN_ENERGY", "ported"),
            ("CAPTRAN_PRM * (1 + trans_cap_delta) $[h_stress$routes_prm]", r"\V{CAPTRAN\_PRM}(1+\delta_{h,t})", "tlim_stress on the stress-hour rows of routes_prm × CAPTRAN_PRM", "ported"),
            ("FLOW", r"\V{FLOW}", "−FLOW within the row domain", "ported"),
            ("sum OPRES_FLOW * opres_mult", r"\sum_o\V{OPRES\_FLOW}\,\P{opres\_mult}", "absent", OPRES_GAP),
        ],
        "prep": [('P.con["eq_transmission_limit"]', 'P.coef["tlim_flow"]')],
        "build": ['"eq_transmission_limit"'],
        "notes": ["A stress-hour row on a route without routes_prm has no capacity term: FLOW ≤ 0, which the port reproduces because the row set is the full FLOW domain."],
    },
    "eq_emit_accounting": {
        "summary": "Regional emissions by type and pollutant: generation × emission rate plus production (SMR, DAC) emissions.",
        "math": r"""
\V{EMIT}_{e^{t},e,r,t} \;=\; \sum_{(i,v)\in\mathrm{valgen}_{r,t},\ h\in h_{rep}} \P{hours}_h\,\P{emit\_rate}_{e^{t},e,i,v,r,t}\big(\V{GEN}_{i,v,r,h,t}+\V{CCSFLEX\_POW}\sw{Sw\_CCSFLEX\_*}\big)
 + \sum_{(p,i,v):\ \mathrm{valcap},\ \mathrm{i\_p}(i,p),\ h\in h_{rep}} \P{hours}_h\,\P{prod\_emit\_rate}_{e^{t},e,i,t}\V{PRODUCE}_{p,i,v,r,h,t}
 - (\text{flexible CCS capture})\sw{Sw\_CCSFLEX\_BYP/STO}
\qquad \mathrm{emit\_modeled}(e,r,t)
""",
        "terms": [
            ("EMIT(etype,e,r,t)", r"\V{EMIT}", "emit_var (+1)", "ported"),
            ("sum hours * emit_rate * GEN $[valgen$h_rep]", r"\sum\P{hours}\P{emit\_rate}\V{GEN}", "emit_gen = −hours(h) × emit_rate(etype,e,i,v,r,t) for h in h_rep, summed over (i,v,h)", "ported"),
            ("sum hours * prod_emit_rate * PRODUCE", r"\sum\P{hours}\P{prod\_emit\_rate}\V{PRODUCE}", "emit_produce = −hours × prod_emit_rate(etype,e,i,t) on PRODUCE rows whose (etype,e,r,t) is an EMIT row", "ported"),
            ("CCSFLEX_POW and flexible-CCS capture terms", r"\V{CCSFLEX\_POW},\ \V{CCSFLEX\_POWREQ}", "absent", "not ported; prep raises when any Sw_CCSFLEX_* is on"),
        ],
        "prep": [('P.con["eq_emit_accounting"]', 'P.coef["emit_gen"]'), ('P.coef["emit_produce"] = (prod_dom', None)],
        "build": ['"eq_emit_accounting"'],
        "notes": ["EMIT is a free variable (negative emissions allowed); every other variable is nonnegative."],
    },
    "eq_annual_cap": {
        "summary": "National annual emissions cap on CO2 (Sw_AnnualCap=1) or CO2-equivalent (Sw_AnnualCap≥2).",
        "math": r"""
\P{emit\_cap}_{eall,t} \;\ge\; \sum_{e\in\mathrm{emit\_capped},\ r}\big(\V{EMIT}_{\mathrm{process},e,r,t} + \V{EMIT}_{\mathrm{upstream},e,r,t}\sw{Sw\_Upstream}\big)\P{gwp}_e
\qquad \textstyle\sum_{tt}\P{emit\_cap}_{eall,tt}\neq0,\ \mathrm{Sw\_AnnualCap}>0
""",
        "terms": [
            ("emit_cap(eall,t)", r"\P{emit\_cap}", "annual_cap_rhs on the (eall,t) rows that have a cap in any year", "ported (constant)"),
            ("sum EMIT(process) * gwp", r"\sum\V{EMIT}_{proc}\P{gwp}", "annual_cap_gwp: gwp(e) on (eall, e) for capped e, × EMIT filtered to etype=process, summed by (eall,t)", "ported"),
            ("EMIT(upstream) $Sw_Upstream", r"\V{EMIT}_{up}\sw{Sw\_Upstream}", "absent", "<b>no guard</b>: Sw_Upstream=1 would add the upstream rows in GAMS only"),
        ],
        "prep": [("cap_any = case[\"emit_cap\"]", 'P.coef["annual_cap_gwp"]')],
        "build": ['"eq_annual_cap"'],
        "notes": ["The slice case has one row (a CO2 cap table with values); the full case has none because emit_cap is empty there."],
    },
    "eq_ObjFn_inv": {
        "summary": "Investment part of the objective. Each term becomes a coefficient table slice_objinv_<VAR> (precomposed in derive_*.py), scaled by cost_scale × pvf_capital(t) in prep.",
        "math": r"""
\V{Z}_{inv,t} = \P{pvf\_capital}_t\Big(
 \sum_{\mathrm{valinv}}\P{cost\_cap\_fin\_mult}_{i,r,t}\P{cost\_cap}_{i,t}\V{INV}
 + \sum_{\mathrm{valinv},\ \mathrm{battery}}\P{cost\_cap\_fin\_mult}\P{cost\_cap\_energy}\V{INV\_ENERGY}
 + \sum_{tg,r}\P{cap\_penalty}_{tg}\V{CAP\_ABOVE\_LIM}
 + (\text{growth penalties})\sw{Sw\_GrowthPenalties} \\
 + \sum_{\mathrm{upgrade},\mathrm{valcap}}\P{cost\_upgrade}\P{cost\_cap\_fin\_mult}\V{UPGRADES}\sw{Sw\_Upgrades}
 + \sum_{\mathrm{m\_rscfeas},\mathrm{valinv},\mathrm{rsc\_i}\setminus\mathrm{spur}}\P{m\_rsc\_dat}_{\mathrm{cost}}\P{rsc\_fin\_mult}\sum_{ii\in\mathrm{rsc\_agg}(i)}\V{INV\_RSC}_{ii}
 + (\text{spur lines})\sw{Sw\_SpurScen}
 + \sum_r\P{trans\_cost\_cap\_fin\_mult}_t\,\mathrm{Sw\_TransIntraCost}\cdot1000\,\V{INV\_POI}
 + (\text{water})\sw{Sw\_WaterMain} \\
 + \sum_{\mathrm{refurbtech},\mathrm{valinv}}\P{cost\_cap\_fin\_mult}\P{cost\_cap}\V{INV\_REFURB}\sw{Sw\_Refurb}
 + \sum_{\mathrm{routes\_inv}(AC),\ \mathrm{tsc\_binwidth}}\P{trans\_cost\_cap\_fin\_mult}\V{TRAN\_CAPEX\_BINS}
 + \sum_{\mathrm{routes\_inv},\ \tau\notin\mathrm{aclike}}\P{trans\_cost\_cap\_fin\_mult}\tfrac{\P{transmission\_cost\_nonac}}{2}\V{INVTRAN}
 + \sum_{\tau\in\mathrm{lcclike}}\P{trans\_cost\_cap\_fin\_mult}\,\P{cost\_acdc\_lcc}\V{INVTRAN}
 + (\text{VSC converters})\sw{Sw\_VSC} \\
 + (\text{sdbin penalty})\sw{Sw\_PRM\_CapCredit}
 + \sum\P{cost\_cap\_fin\_mult}\P{cost\_cap\_up}\V{INV\_CAP\_UP} + \sum\P{cost\_cap\_fin\_mult}\P{cost\_ener\_up}\V{INV\_ENER\_UP}
 + \sum_{\mathrm{h2\_routes\_inv}}\P{cost\_h2\_transport\_cap}\V{H2\_TRANSPORT\_INV}\sw{Sw\_H2=2}
 + \sum_{\mathrm{h2\_stor\_r}}\P{cost\_h2\_storage\_cap}\V{H2\_STOR\_INV}\sw{Sw\_H2=2}
 + (\text{CO2 pipelines, spur lines})\sw{Sw\_CO2\_Detail}\Big)
""",
        "terms": [
            ("cost_cap_fin_mult * cost_cap * INV", r"c^{inv}_{INV}", "slice_objinv_INV (derive_temporal.slice_coefficients)", "ported (precomposed)"),
            ("cost_cap_fin_mult * cost_cap_energy * INV_ENERGY", r"c^{inv}_{INV\_ENERGY}", "slice_objinv_INV_ENERGY", "ported (precomposed)"),
            ("cap_penalty * CAP_ABOVE_LIM", r"c^{inv}_{CAL}", "slice_objinv_CAP_ABOVE_LIM (derive_ops.policies); this table also defines the CAP_ABOVE_LIM column set", "ported"),
            ("growth penalties $Sw_GrowthPenalties", r"\ldots", "absent", "not ported; prep raises when Sw_GrowthPenalties"),
            ("cost_upgrade * cost_cap_fin_mult * UPGRADES", r"c^{inv}_{UPG}", "slice_objinv_UPGRADES", "ported (precomposed)"),
            ("m_rsc_dat cost * rsc_fin_mult * sum{ii, INV_RSC(ii)}", r"c^{inv}_{RSC}", "slice_objinv_INV_RSC: numeraire cost × rsc_fin_mult mapped to each investing tech ii by rsc_agg (fsum over duplicates)", "ported (precomposed); rows for columns outside the INV_RSC domain are counted in objective_rows_off_domain"),
            ("spur lines $Sw_SpurScen", r"\P{spurline\_cost}_x\,\mathrm{Sw\_SpurCostMult}\,\V{INV\_SPUR}_{x,t}", "slice_objinv_INV_SPUR on xfeas × t (derive_ops)", "ported (spur group)"),
            ("trans_cost_cap_fin_mult * Sw_TransIntraCost * 1000 * INV_POI", r"c^{inv}_{POI}", "slice_objinv_INV_POI (derive_ops.transmission)", "ported (precomposed)"),
            ("water $Sw_WaterMain", r"\ldots", "absent", "not ported; derive raises when Sw_WaterMain=1"),
            ("cost_cap_fin_mult * cost_cap * INV_REFURB", r"c^{inv}_{REF}", "slice_objinv_INV_REFURB", "ported (precomposed)"),
            ("trans_cost_cap_fin_mult * TRAN_CAPEX_BINS", r"c^{inv}_{BINS}", "slice_objinv_TRAN_CAPEX_BINS", "ported (precomposed), no columns in either case"),
            ("non-AC and LCC INVTRAN costs", r"c^{inv}_{INVTRAN}", "slice_objinv_INVTRAN = fin_mult × cost_nonac / 2 (non-aclike) + fin_mult × cost_acdc_lcc (lcclike), fsum per route", "ported (precomposed), no columns in either case"),
            ("VSC, sdbin penalty, CO2 detail", r"\ldots", "absent", "not ported; guarded"),
            ("INV_CAP_UP, INV_ENER_UP costs", r"c^{inv}_{UP}", "slice_objinv_INV_CAP_UP / INV_ENER_UP are empty tables; derive_temporal raises if allow_cap_up has rows", "guarded"),
            ("cost_h2_transport_cap * H2_TRANSPORT_INV", r"c^{inv}_{H2T}", "slice_objinv_H2_TRANSPORT_INV empty; h2 routes raise", "guarded"),
            ("cost_h2_storage_cap * H2_STOR_INV $(Sw_H2=2)", r"c^{inv}_{H2S}", "slice_objinv_H2_STOR_INV (derive_ops.hydrogen)", "ported (precomposed)"),
        ],
        "prep": [("cs = case.scalar(\"cost_scale\")", "return _sorted(P)")],
        "build": [("terms = [(P(df) * getattr(m, name)).sum()", "m.minimize =")],
        "derive": [("reeds/open/derive_temporal.py", "ccfm = S.cost_cap_fin_mult.filter", 'S["slice_objinv_INV_RSC"]'),
                   ("reeds/open/derive_temporal.py", 'S["slice_objinv_INV_REFURB"] = nonzero', 'S["cap_ener_up"]'),
                   ("reeds/open/derive_ops.py", "tccfm = S.trans_cost_cap_fin_mult", 'S["slice_objop_INV_POI"]'),
                   ("reeds/open/derive_ops.py", "fy = sc[\"firstyear_RPS\"]", 'S["slice_objinv_CAP_ABOVE_LIM"]'),
                   ("reeds/open/derive_ops.py", "stor_dom = S.h2_stor_r.with_columns", 'S["slice_objop_H2_TRANSPORT_INV"]')],
        "notes": ["The GAMS objective is Z = cost_scale × Σ_t (Z_inv + Z_op); the port minimizes Σ (coefficient × variable) with the coefficient already multiplied by cost_scale and the present-value factor, and compares against the GAMS objective minus its constant part (gate 2).",
                  "Columns that appear only in the objective (no constraint row) are kept, as GAMS CONVERT keeps them."],
    },
    "eq_Objfn_op": {
        "summary": "Operations part of the objective. Terms become slice_objop_<VAR> tables scaled by cost_scale × pvf_onm(t).",
        "math": r"""
\V{Z}_{op,t} = \P{pvf\_onm}_t\Big(
 \sum_{\mathrm{valgen},h}\P{hours}_h\P{cost\_vom}\V{GEN}[i\notin\mathrm{hybrid}\setminus\mathrm{csp}]
 + (\text{hybrid plant VOM})\sw{Sw\_HybridPlant}
 + \sum_{\mathrm{valcap}}\P{cost\_fom}\V{CAP} + \sum_{\mathrm{battery}}\P{cost\_fom\_energy}\V{CAP\_ENERGY}
 + \sum_{\mathrm{routes}}\tfrac{\P{transmission\_line\_fom}}{2}\V{CAPTRAN\_ENERGY} + \sum_{\mathrm{lcclike}}\P{cost\_acdc\_lcc}\P{trans\_fom\_frac}\V{CAPTRAN\_ENERGY}
 + (\text{VSC})\sw{Sw\_VSC} \\
 + \sum_{\mathrm{m\_rscfeas},\mathrm{valcap},\mathrm{rsc\_i}\setminus\mathrm{spur}\setminus\mathrm{sccapcosttech}}\P{m\_rsc\_dat}_{\mathrm{cost\_trans}}\P{trans\_fom\_frac}\V{CAP\_RSC}
 + (\text{spur})\sw{Sw\_SpurScen}
 + \sum_r \mathrm{Sw\_TransIntraCost}\cdot1000\,\P{trans\_fom\_frac}\sum_{tt\in\mathcal{T},tt\le t}\V{INV\_POI}_{r,tt}
 - \sum_{\mathrm{valcap}\cap\mathrm{retiretech}}\P{cost\_fom}\P{retire\_penalty}_t(\V{CAP}-\V{INV}-\V{INV\_REFURB}-\V{UPGRADES})\sw{Sw\_RetirePenalty} \\
 + \sum\P{hours}\P{cost\_opres}\V{OPRES}\sw{Sw\_OpRes}
 + \sum_{\text{fixed-price fuels}}\P{hours}\P{heat\_rate}\P{fuel\_price}\V{GEN}
 + \sum\P{startcost}_i\P{numhours\_nexth}_{h,hh}\V{RAMPUP}\sw{Sw\_StartCost}
 + \sum_{\mathrm{cofire}}(1-\P{bio\_cofire\_perc})\P{hours}\P{heat\_rate}\P{fuel\_price}_{\text{coal-new}}\V{GEN}
 + \sum_{\mathrm{gas}}\P{hours}\P{heat\_rate}\P{fuel\_price}\P{gasprice\_adj\_r}\V{GEN}[\mathrm{Sw\_GasCurve}=2]
 + (\text{dac\_gas fuel})\sw{Sw\_DAC\_Gas} + (\text{gas bins})[\mathrm{Sw\_GasCurve}\in\{0,1,3\}] \\
 + \sum_{r,bioclass}\V{BIOUSED}\big(\textstyle\sum_{usda}\P{biosupply}_{\mathrm{price}}+\P{bio\_transport\_cost}\big)
 + \sum_{\mathrm{routes}}\P{cost\_hurdle}\P{hours}\V{FLOW}
 + \sum_{e,r}(\V{EMIT}_{proc}+\V{EMIT}_{up}\sw{Sw\_Upstream})\P{emit\_tax}
 + \sum\P{hours}\P{capture\_rate}_{CO2}\,\mathrm{Sw\_CO2\_Storage}\,\V{GEN}
 + \sum\P{hours}\,\P{smr\_capture\_rate}\,\P{smr\_co2\_intensity}\,\mathrm{Sw\_CO2\_Storage}\,\V{PRODUCE}_{smr\_ccs}
 + (\text{DAC storage cost})\sw{Sw\_DAC} \\
 + \sum\P{acp\_price}\V{ACP\_PURCHASES}\sw{Sw\_StateRPS}
 + (\text{dropped load})[t<\mathrm{Sw\_StartMarkets}]
 + \sum\P{hours}\P{cost\_prod}\V{PRODUCE}\sw{Sw\_Prod}
 + \sum_{\mathrm{h2\_routes\_inv}}\P{cost\_h2\_transport\_fom}\sum_{tt}\V{H2\_TRANSPORT\_INV}_{r,rr,t}
 + \sum\P{hours}\,\mathrm{Sw\_H2\_IntraReg\_Transport}\cdot10^3\,\V{PRODUCE}_{H2,newv}
 + \sum\P{cost\_h2\_storage\_fom}\V{H2\_STOR\_CAP}
 + (\text{retail adder})\sw{Sw\_RetailAdder} + (\text{CO2 detail})\sw{Sw\_CO2\_Detail} \\
 - \sum\tfrac{\P{crf}_t}{\P{crf\_co2\_incentive}_t}\P{co2\_captured\_incentive}\P{hours}\P{capture\_rate}\V{GEN}
 - (\text{DAC incentive})
 - \sum\P{hours}\P{ptc\_value\_scaled}\P{tc\_phaseout\_mult}(\V{GEN}-\ldots\sw{Sw\_PVB})
 - \sum\P{hours}\tfrac{\P{crf}}{\P{crf\_h2\_incentive}}\P{h2\_ptc}\cdot10^3\V{PRODUCE}_{H2,electrolyzer}\sw{Sw\_H2\_PTC}\Big)
""",
        "terms": [
            ("VOM, fixed-price fuel, cofire coal, gas (GasCurve=2), CO2 storage cost, CO2 incentive, PTC on GEN", r"c^{op}_{GEN}", "slice_objop_GEN: hours × (vom + hr·fp [fixed fuels] + (1−bcp)·hr·coalfp [cofire] + hr·fp·gpa [gas] + capr·Sw_CO2_Storage − crf/crfi·inc·capr − ptc·tcm)", "ported (precomposed)"),
            ("cost_fom * CAP − retire penalty on CAP", r"c^{op}_{CAP}", "slice_objop_CAP = cost_fom − cost_fom × retire_penalty on retiretech rows", "ported (precomposed)"),
            ("+ cost_fom * retire_penalty * INV / INV_REFURB / UPGRADES", r"c^{op}_{INV},\ldots", "slice_objop_INV, slice_objop_INV_REFURB, slice_objop_UPGRADES (positive, because the GAMS term is −penalty × (CAP − INV − …))", "ported (precomposed)"),
            ("cost_fom_energy * CAP_ENERGY", r"c^{op}_{CAP\_ENERGY}", "slice_objop_CAP_ENERGY", "ported"),
            ("transmission_line_fom / 2 + cost_acdc_lcc * trans_fom_frac on CAPTRAN_ENERGY", r"c^{op}_{CAPTRAN}", "slice_objop_CAPTRAN_ENERGY", "ported"),
            ("m_rsc_dat cost_trans * trans_fom_frac * CAP_RSC", r"c^{op}_{CAP\_RSC}", "slice_objop_CAP_RSC", "ported"),
            ("Sw_TransIntraCost * 1000 * trans_fom_frac * sum INV_POI(tt)", r"c^{op}_{POI}", "slice_objop_INV_POI for the current-year column; prior-year INV_POI is a constant (dropped from the objective, included in the GAMS constant checked by gate 2)", "ported"),
            ("hours * cost_opres * OPRES", r"c^{op}_{OPRES}", "slice_objop_OPRES (derive_ops.operations)", "ported, no columns in either case"),
            ("startcost * numhours_nexth * RAMPUP", r"c^{op}_{RAMP}", "slice_objop_RAMPUP", "ported"),
            ("BIOUSED * (biosupply price + bio_transport_cost)", r"c^{op}_{BIO}", "slice_objop_BIOUSED", "ported"),
            ("cost_hurdle * hours * FLOW", r"c^{op}_{FLOW}", "slice_objop_FLOW", "ported"),
            ("EMIT * emit_tax", r"\P{emit\_tax}\V{EMIT}", "slice_objop_EMIT is an empty table", "<b>no guard</b>: a case with a nonzero emit_tax would lose the tax term"),
            ("acp_price * ACP_PURCHASES", r"c^{op}_{ACP}", "slice_objop_ACP_PURCHASES (derive_ops.policies); the table also defines ACP_PURCHASES columns", "ported"),
            ("cost_prod, intra-regional H2 transport, SMR-CCS storage cost, H2 PTC on PRODUCE", r"c^{op}_{PROD}", "slice_objop_PRODUCE (derive_ops.hydrogen), fsum of the four parts", "ported (precomposed)"),
            ("cost_h2_transport_fom * sum_tt H2_TRANSPORT_INV(r,rr,t)", r"c^{op}_{H2T}", "slice_objop_H2_TRANSPORT_INV empty (routes raise); the GAMS term indexes the variable by t inside a sum over tt, so it would be coefficient × number of years", "guarded"),
            ("cost_h2_storage_fom * H2_STOR_CAP", r"c^{op}_{H2S}", "slice_objop_H2_STOR_CAP", "ported"),
            ("gas bins (Sw_GasCurve 0/1/3), dac_gas fuel, hybrid VOM, VSC, spur, dropped load, retail adder, CO2 detail, DAC incentive, PVB", r"\ldots", "absent", "not ported; all guarded (Sw_GasCurve 0/1/3 raise, Sw_DAC_Gas raises in derive_ops when dac rates are needed, Sw_HybridPlant, Sw_VSC, Sw_SpurScen, Sw_StartMarkets, Sw_RetailAdder, Sw_CO2_Detail, Sw_PVB)"),
        ],
        "prep": [("cs = case.scalar(\"cost_scale\")", "return _sorted(P)")],
        "build": [("terms = [(P(df) * getattr(m, name)).sum()", "m.minimize =")],
        "derive": [("reeds/open/derive_temporal.py", "vom = S.cost_vom.filter", 'S["slice_objop_UPGRADES"]'),
                   ("reeds/open/derive_temporal.py", "cost_trans = S.m_rsc_dat.filter", 'S["slice_objop_EMIT"]'),
                   ("reeds/open/derive_ops.py", "co_y = S.cost_opres.filter", 'S["slice_objop_BIOUSED"]'),
                   ("reeds/open/derive_ops.py", "prod_dom = (valcap_y.filter(isin(\"i\", members(S.consume)))", 'S["slice_objop_PRODUCE"]')],
        "notes": ["The H2 fuel cost for h2_gen technologies is charged only in stress hours (or when Sw_H2=0), as the GAMS condition says; fixed_fuel in derive_temporal encodes that condition.",
                  "The prior-year INV_POI FOM term is a constant in the current year's LP; GAMS carries it in the objective constant, which gate 2 removes before comparing objective values."],
    },
}
