from __future__ import annotations

REC_ROWS = r"\mathrm{stfeas}(st),\ t\notin\mathrm{tfirst},\ \mathrm{Sw\_StateRPS},\ t\ge\P{firstyear\_RPS}"
ENDUSE = r"\sum_{(r,h):\ r\in st,\ h\in h_{rep}}\P{hours}_h\big(\V{LOAD}_{r,h,t}-\P{can\_exports\_h}_{r,h,t}\sw{Sw\_Canada=1}-\textstyle\sum_v\V{GEN}_{\mathrm{distpv},v,r,h,t}\big)(1-\P{distloss})"
STYLE_CAVEAT = ("<b>difference</b>: GAMS uses the end-use-sales formula here whatever RecStyle says, while load_terms switches on RecStyle(st, RPSCat). "
                "The two agree only when RecStyle is 0 for the row's state and category, which holds in both reference cases (matrix gate passed).")

SPEC: dict[str, dict] = {
    "eq_RGGI_cap": {
        "summary": "RGGI cap on process CO2 of the member zones.",
        "math": r"""
\P{RGGI\_cap}_t \;\ge\; \sum_{r\in\mathrm{RGGI\_r}}\V{EMIT}_{\mathrm{process},CO2,r,t}\qquad t\ge\P{RGGI\_start\_yr},\ \mathrm{Sw\_RGGI}
""",
        "terms": [
            ("RGGI_cap(t)", r"\P{RGGI\_cap}_t", "rggi_const (rggi_cap, rounded to 0 decimals as in e_solveprep)", "ported (constant)"),
            ("sum EMIT(process, CO2, RGGI zones)", r"\sum\V{EMIT}", "rggi_emit (−1) on process/co2 EMIT rows in rggi_r", "ported"),
            ("row set", r"", "years with at least one EMIT term", "ported"),
        ],
        "prep": [("emit_co2 = P.var[\"EMIT\"]", 'P.coef["rggi_emit"]')],
        "build": ['"eq_RGGI_cap"'],
        "notes": ["No rows in either case: the Pacific cases contain no RGGI zones."],
    },
    "eq_state_cap": {
        "summary": "State CO2 cap (California cap-and-trade): in-state process CO2 plus imported electricity at last year's emission intensity of the sending zone.",
        "math": r"""
\P{state\_cap}_{st,t} \;\ge\; \sum_{r\in st}\V{EMIT}_{\mathrm{process},CO2,r,t}
 + \sum_{\substack{(h,r,rr,\tau):\ r\in st,\ rr\notin st,\ \mathrm{routes}(rr,r,\tau,t),\ h\in h_{rep},\\ \neg(\mathrm{Sw\_AnnualCap}>0\ \wedge\ \P{emit\_cap}_{CO2,t}=0\ \wedge\ \P{emit\_cap}_{CO2e,t}=0)}}
 \P{hours}_h\,\V{FLOW}_{rr,r,h,t,\tau}\sum_{tt:\ \mathrm{tprev}(t,tt)}\P{co2\_emit\_rate\_r}_{rr,tt}
\qquad t\ge\P{state\_cap\_start\_yr},\ \textstyle\sum_{tt}\P{state\_cap}_{st,tt}\neq0,\ \mathrm{Sw\_StateCap}
""",
        "terms": [
            ("state_cap(st,t)", r"\P{state\_cap}", "stcap_const = co2_state_cap (the GAMS state_cap table, renamed because state_CAP is a prior-year level table and Windows file names are case-insensitive)", "ported (constant)"),
            ("sum EMIT(process, CO2) in state", r"\sum_{r\in st}\V{EMIT}", "stcap_emit (−1)", "ported"),
            ("hours * FLOW(rr→r) * co2_emit_rate_r(rr, tprev)", r"\P{hours}\V{FLOW}_{rr\to r}\P{co2\_emit\_rate\_r}_{rr,t^-}", "stcap_flow: −hours × rate(source zone, tprev) on FLOW(source, dest) with dest in the state and source outside it (or outside any state); rate from state_co2_emit_rate_r at tprev", "ported"),
            ("national-cap condition", r"\neg(\ldots)", "when Sw_AnnualCap > 0 the flow rows are kept only for years with a co2 or co2e emit_cap", "ported"),
            ("first solve year", r"\sum_{tt\in\mathrm{tprev}}=\emptyset", "no tprev → rate missing → flow terms drop (value filtered ≠ 0), as the empty GAMS sum", "ported"),
        ],
        "prep": [("if int(case.scalar(\"Sw_StateCap\")):", 'P.coef["stcap_flow"] = stcap_flow')],
        "build": ['"eq_state_cap"'],
        "notes": ["co2_emit_rate_r is computed by GAMS after each solve (4_post_solve_adjustments); the port reads it from the previous year's solution gdx."],
    },
    "eq_CSAPR_Budget": {
        "summary": "CSAPR NOx budget per trading group.",
        "math": r"""
\sum_{st\in\mathrm{stfeas}\cap\mathrm{csapr\_group\_st}(g)}\P{csapr\_cap}_{st,\mathrm{budget},t}
 \;\ge\; \sum_{st\in g}\ \sum_{(i,v,h,r):\ r\in st,\ \mathrm{valgen},\ h\in h_{rep}}\P{h\_weight\_csapr}_h\,\P{hours}_h\,\P{emit\_rate}_{\mathrm{process},NOX,i,v,r,t}\,\V{GEN}_{i,v,r,h,t}
\qquad \mathrm{Sw\_CSAPR},\ t\ge\P{csapr\_startyr}
""",
        "terms": [
            ("sum csapr_cap(st, budget, t)", r"\sum\P{csapr\_cap}_{budget}", "csb_const (budget summed over stfeas states of the group)", "ported (constant)"),
            ("weighted NOx from GEN", r"\P{h\_weight\_csapr}\P{hours}\P{emit\_rate}_{NOX}\V{GEN}", "csb_gen = −((hw·hrs)·er) mapped to the group through csapr_group_st", "ported"),
            ("row set", r"", "groups × years ≥ csapr_startyr with a GEN term", "ported"),
        ],
        "prep": [("if int(case.scalar(\"Sw_CSAPR\")):", 'P.coef["csa_gen"]')],
        "build": ['"eq_CSAPR_Budget"', '"eq_CSAPR_Assurance"'],
        "notes": ["No rows in either case: no CSAPR states in the Pacific cases (csapr_group_st empty)."],
    },
    "eq_CSAPR_Assurance": {
        "summary": "CSAPR NOx assurance level per state.",
        "math": r"""
\P{csapr\_cap}_{st,\mathrm{assurance},t} \;\ge\; \sum_{(i,v,h,r):\ r\in st,\ \mathrm{valgen},\ h\in h_{rep}}\P{h\_weight\_csapr}_h\,\P{hours}_h\,\P{emit\_rate}_{\mathrm{process},NOX,i,v,r,t}\,\V{GEN}_{i,v,r,h,t}
\qquad \mathrm{stfeas}(st),\ t\ge\P{csapr\_startyr},\ \P{csapr\_cap}_{st,\mathrm{assurance},t}\neq0
""",
        "terms": [
            ("csapr_cap(st, assurance, t)", r"\P{csapr\_cap}_{assurance}", "csa_const", "ported (constant)"),
            ("weighted NOx from GEN", r"\ldots\V{GEN}", "csa_gen (same coefficient as csb_gen, keyed by state)", "ported"),
        ],
        "prep": [("assure = ccap.filter", 'P.coef["csa_gen"]')],
        "build": ['"eq_CSAPR_Assurance"'],
    },
    "eq_emit_rate_limit": {
        "summary": "Regional emission-rate limit.",
        "math": r"\P{emit\_rate\_limit}_{e,r,t}\sum_{\mathrm{valgen},\ h\in h_{rep}}\P{hours}_h\V{GEN}_{i,v,r,h,t} \ge \V{EMIT}_{\mathrm{process},e,r,t}+\V{EMIT}_{\mathrm{upstream},e,r,t}\sw{Sw\_Upstream}\qquad \mathrm{emit\_rate\_con}(e,r,t)",
        "guard_only": True,
        "port_note": "Not ported. emit_rate_con is an empty set in the port (derive_ops.policies) and <code>prep.prepare</code> raises if it has rows.",
        "prep": [("if case[\"emit_rate_con\"].height:", None)],
    },
    "eq_bankborrowcap": {
        "summary": "Weighted multi-year emissions cap (intertemporal solves only).",
        "math": r"\sum_{t\in\mathrm{tmodel}:\ \P{emit\_cap}_{e,t}\neq0}\P{yearweight}_t\P{emit\_cap}_{e,t} \ge \sum_{r,t}\P{yearweight}_t(\V{EMIT}_{\mathrm{process},e,r,t}+\V{EMIT}_{\mathrm{upstream},e,r,t}\sw{Sw\_Upstream})\qquad \mathrm{Sw\_BankBorrowCap}",
        "guard_only": True,
        "port_note": "Not ported (intertemporal feature). <code>prep.prepare</code> raises when Sw_BankBorrowCap is 1.",
        "prep": [("for name, msg in ((\"Sw_BankBorrowCap\"", "raise NotImplementedError(f\"{name}=1 ({msg}) is not ported\")")],
    },
    "eq_cdr_cap": {
        "summary": "Carbon removal (DAC, BECCS) may offset only fossil-CCS emissions.",
        "math": r"""
\sum_{\mathrm{valgen},\ i\in\mathrm{ccs}\setminus\mathrm{beccs},\ h\in h_{rep}}\P{hours}_h\V{GEN}_{i,v,r,h,t}\,\P{e}_{i,v,r,t}
 \;\ge\; -\sum_{\mathrm{dac}}\P{hours}_h\,\P{prod\_emit\_rate}_{CO2,i,t}\V{PRODUCE}_{DAC,i,v,r,h,t} - \sum_{\mathrm{beccs}}\P{hours}_h\,\P{emit\_rate}_{CO2}\V{GEN}
""",
        "where": [r"\(\P{e}\) is the process (+ upstream) CO2 rate when Sw_AnnualCap < 2 and the GWP-weighted sum over pollutants otherwise."],
        "guard_only": True,
        "port_note": "Not ported. <code>prep.prepare</code> raises when Sw_NoFossilOffsetCDR is 1.",
        "prep": [("for name, msg in ((\"Sw_BankBorrowCap\"", "raise NotImplementedError(f\"{name}=1 ({msg}) is not ported\")")],
    },
    "eq_REC_Generation": {
        "summary": "RECs a technology can sell from a state are bounded by its eligible generation in that state.",
        "math": r"""
\sum_{(v,r,h):\ \mathrm{valgen},\ r\in st,\ h\in h_{rep}}\P{RPSTechMult}_{c,i,st}\,\P{hours}_h\Big(\V{GEN}_{i,v,r,h,t}
 - \V{CREDIT\_H2PTC}_{i,v,r,h,t}[\mathrm{valgen\_h2ptc}]\sw{Sw\_H2\_PTC}
 - \V{STORAGE\_IN\_GRID}\,\P{storage\_eff\_pvb\_g}\sw{Sw\_HybridPlant}\Big) \\
 \;\ge\; \sum_{ast:\ \mathrm{RecMap}(i,c,st,ast,t),\ \mathrm{stfeas}(ast)\vee ast=\mathrm{voluntary}}\V{RECS}_{c,i,st,ast,t}
 + \sum_{ast:\ \mathrm{RecMap}(i,\mathrm{RPS\_Bundled},st,ast,t),\ \mathrm{stfeas}(ast),\ ast\neq st}\V{RECS}_{\mathrm{RPS\_Bundled},i,st,ast,t}[c=\mathrm{RPS\_All}]
 + \sum_{ast}\V{RECS}_{\mathrm{CES\_Bundled},i,st,ast,t}[c=\mathrm{CES}]
\qquad """ + REC_ROWS + r""",\ c\notin\{\mathrm{RPS\_Bundled},\mathrm{CES\_Bundled}\},\ \mathrm{RecTech}(c,i,st,t)
""",
        "terms": [
            ("RPSTechMult * hours * GEN", r"\P{RPSTechMult}\P{hours}\V{GEN}", "recgen_gen (mult × hours) on GEN columns of the technology in the state's zones, representative hours", "ported"),
            ("− RPSTechMult * hours * CREDIT_H2PTC", r"-\P{RPSTechMult}\P{hours}\V{CREDIT\_H2PTC}", "recgen_credit (−mult × hours) when CREDIT_H2PTC exists", "ported"),
            ("− STORAGE_IN_GRID term", r"\ldots\sw{Sw\_HybridPlant}", "absent", "not ported; guarded"),
            ("sum RECS(c,i,st,ast)", r"\sum_{ast}\V{RECS}_{c}", "recgen_recs own part (−1): RECS columns whose (c,i,st) matches the row", "ported"),
            ("bundled RECS credited to RPS_All / CES rows", r"\sum_{ast}\V{RECS}_{bundled}", "recgen_recs bundled part (−1): rps_bundled columns under rps_all rows, ces_bundled under ces rows (st ≠ ast, stfeas(ast))", "ported"),
            ("RECS column set", r"", "recmap rows with stfeas(st) and (stfeas(ast) or voluntary), minus same-state bundled pairs, which appear in no GAMS row", "ported"),
        ],
        "prep": [("if int(case.scalar(\"Sw_StateRPS\")):", 'P.var["RECS"] = recs_dom'), ("RG = [\"rpscat\", \"i\", \"st\", \"t\"]", 'P.coef["recgen_recs"]'), ('P.coef["recgen_credit"] = (P.con', None)],
        "build": ['"eq_REC_Generation"'],
        "notes": ["The RECS variable is indexed (rpscat, i, st, ast, t); in the row tables its category and selling state are renamed rpscat_v and st_v so they do not collide with the row's own rpscat and st."],
    },
    "eq_REC_Requirement": {
        "summary": "Net RECs owned by a state, plus alternative compliance payments, must meet its requirement fraction of load (or generation).",
        "math": r"""
\sum_{(i,ast):\ \mathrm{RecMap}(i,c,ast,st,t),\ \mathrm{stfeas}(ast)}\V{RECS}_{c,i,ast,st,t} - \sum_{(i,ast):\ \mathrm{RecMap}(i,c,st,ast,t),\ \mathrm{stfeas}(ast),\ ast\neq st}\V{RECS}_{c,i,st,ast,t}
 + \big(\text{bundled imports} - \text{bundled exports}\big)[c\in\{\mathrm{RPS\_All},\mathrm{CES}\}]
 + \V{ACP\_PURCHASES}_{c,st,t}[\neg\mathrm{acp\_disallowed}]
 - \sum_{r\in st,\ h\in h_{rep}}\P{can\_exports\_h}\P{hours}\sw{Sw\_Canada=1}[c=\mathrm{CES}] \\
 \;\ge\; \P{RecPerc}_{c,st,t}\sum_{(r,h):\ \mathrm{r\_st\_rps}(r,st),\ h\in h_{rep}}\P{hours}_h\Big(
 \big[(\V{LOAD}-\P{can\_exports\_h}-\textstyle\sum_v\V{GEN}_{distpv})(1-\P{distloss})\big]_{\mathrm{RecStyle}=0}
 + \big[\V{LOAD}-\P{can\_exports\_h}-\textstyle\sum_v\V{GEN}_{distpv}\big]_{\mathrm{RecStyle}=1} \\
 \qquad + \big[\textstyle\sum_{\mathrm{valgen},\ i\notin\mathrm{storage\_standalone}}(\V{GEN}-\P{distloss}\V{GEN}[distpv]-\V{STORAGE\_IN\_GRID}\eta\sw{Sw\_HybridPlant}) - \P{can\_exports\_h}\sw{Sw\_Canada=1}[c=\mathrm{CES}]\big]_{\mathrm{RecStyle}=2}\Big)
\qquad \P{RecPerc}\neq0,\ """ + REC_ROWS + r""",\ \mathrm{stfeas}(st)\vee st=\mathrm{voluntary},\ c\text{ unbundled}
""",
        "terms": [
            ("imports RECS(c, i, ast→st)", r"\sum\V{RECS}_{ast\to st}", "into(req_rows, +1, strict=False): columns with ast = row state (includes in-state use ast = st)", "ported"),
            ("− exports RECS(c, i, st→ast), ast ≠ st", r"-\sum\V{RECS}_{st\to ast}", "outof(req_rows, −1, allow_voluntary=False)", "ported"),
            ("± bundled imports/exports", r"\pm\sum\V{RECS}_{bundled}", "bundled_terms(..., 'in' +1 / 'out' −1) for rps_bundled under rps_all rows and ces_bundled under ces rows", "ported"),
            ("ACP_PURCHASES $[not acp_disallowed]", r"\V{ACP\_PURCHASES}", "recreq_acp (+1) on rows not in acp_disallowed; ACP_PURCHASES columns = these rows ∪ launder rows ∪ objective rows", "ported"),
            ("− sum can_exports_h * hours (CES, Sw_Canada=1)", r"-\sum\P{can\_exports\_h}\P{hours}", "exp_c (−ce·hrs) added into recreq_const", "ported (constant)"),
            ("RecPerc * hours * LOAD terms (styles 0, 1)", r"-\P{RecPerc}\P{hours}(1-\P{distloss})^{[0]}\V{LOAD}", "recreq_load = −f·mult with f = (1−dl)·hrs (style 0) or hrs (style 1), mult = RecPerc, zones from r_st_rps", "ported"),
            ("RecPerc * hours * GEN(distpv) terms (styles 0, 1)", r"+\P{RecPerc}\P{hours}(1-\P{distloss})^{[0]}\V{GEN}_{distpv}", "recreq_gen (gen_d part, +f·mult)", "ported"),
            ("RecPerc * hours * generation (style 2)", r"-\P{RecPerc}\P{hours}\V{GEN}", "recreq_gen (gen2 part, −(1−dl)·hrs·mult for distpv, −hrs·mult otherwise, non-standalone-storage techs)", "ported; STORAGE_IN_GRID absent (guarded)"),
            ("RecPerc * hours * can_exports_h constants", r"+\P{RecPerc}\P{hours}\P{can\_exports\_h}(\ldots)", "const from load_terms (style 0: ce(1−dl)hrs·mult, style 1: ce·hrs·mult, style 2: ce·hrs·mult for CES only)", "ported (constant)"),
        ],
        "prep": [("ce = case[\"can_exports_h\"].rename", 'P.coef["recreq_acp"]')],
        "build": ['"eq_REC_Requirement"'],
        "helpers": ["load_terms", "into", "outof", "bundled_terms", "recs_coef"],
        "notes": ["The GAMS RecStyle selector is evaluated per (st, RPSCat); load_terms joins recstyle on exactly those keys."],
    },
    "eq_REC_BundleLimit": {
        "summary": "Bundled RECs traded between two states cannot exceed the electricity flowing between them.",
        "math": r"""
\sum_{(h,r,rr,\tau):\ r\in st,\ rr\in ast,\ \mathrm{routes}(r,rr,\tau,t),\ h\in h_{rep}}\P{hours}_h\V{FLOW}_{r,rr,h,t,\tau} \;\ge\; \sum_{i:\ \mathrm{RecMap}(i,c,st,ast,t)}\V{RECS}_{c,i,st,ast,t}
\qquad \mathrm{stfeas}(st),\ \mathrm{stfeas}(ast),\ st\neq ast,\ c\in\{\mathrm{RPS\_Bundled},\mathrm{CES\_Bundled}\},\ \textstyle\sum_i\mathrm{RecMap}\neq0,\ t\ge\P{firstyear\_RPS}
""",
        "terms": [
            ("sum hours * FLOW(st→ast)", r"\sum\P{hours}\V{FLOW}", "recbl_flow (+hours) on FLOW between zones of the two states, representative hours", "ported"),
            ("sum RECS(bundled, st→ast)", r"\sum_i\V{RECS}", "recbl_recs (−1)", "ported"),
        ],
        "prep": [("BL = [\"rpscat\", \"st\", \"ast\", \"t\"]", 'P.coef["recbl_recs"]')],
        "build": ['"eq_REC_BundleLimit"'],
    },
    "eq_REC_unbundledLimit": {
        "summary": "Unbundled imported RECs are limited to a fraction of the requirement (end-use sales basis).",
        "math": r"""
\P{REC\_unbundled\_limit}_{c,st,t}\,\P{RecPerc}_{c,st,t}\;""" + ENDUSE + r"""
 \;\ge\; \sum_{(i,ast):\ \mathrm{RecMap}(i,c,ast,st,t),\ \mathrm{stfeas}(ast),\ ast\neq st}\V{RECS}_{c,i,ast,st,t}
 - \sum_{(i,ast)}\V{RECS}_{\mathrm{RPS\_Bundled},i,ast,st,t}[c=\mathrm{RPS\_All}] - \sum_{(i,ast)}\V{RECS}_{\mathrm{CES\_Bundled},i,ast,st,t}[c=\mathrm{CES}]
\qquad \mathrm{st\_unbundled\_limit}(c,st),\ \mathrm{stfeas}(st),\ c\in\{\mathrm{RPS\_All},\mathrm{CES}\},\ t\ge\P{firstyear\_RPS}
""",
        "terms": [
            ("limit * RecPerc * hours * (1−distloss) * LOAD", r"+\P{lim}\P{RecPerc}\P{hours}(1-\P{distloss})\V{LOAD}", "recunb_load = −load_c from load_terms with mult = limit × RecPerc and zones from r_st", "ported; " + STYLE_CAVEAT),
            ("− limit * RecPerc * hours * (1−distloss) * GEN(distpv)", r"-\ldots\V{GEN}_{distpv}", "recunb_gen = −gen_c", "ported (same caveat)"),
            ("− limit * RecPerc * hours * (1−distloss) * can_exports_h", r"-\ldots\P{can\_exports\_h}", "recunb_const = −const", "ported (constant, same caveat)"),
            ("imported RECS (ast ≠ st)", r"\sum\V{RECS}_{ast\to st}", "into(unb_rows, −1, strict=True)", "ported"),
            ("− bundled imports", r"-\sum\V{RECS}_{bundled}", "bundled_terms(..., +1, 'in')", "ported"),
        ],
        "prep": [("unb = (case[\"rec_unbundled_limit\"]", 'P.coef["recunb_recs"]')],
        "build": ['"eq_REC_unbundledLimit"'],
        "helpers": ["load_terms", "into", "bundled_terms", "recs_coef"],
    },
    "eq_REC_ooslim": {
        "summary": "Out-of-state RECs are limited to a fraction of the requirement (end-use sales basis).",
        "math": r"""
\P{RPS\_oosfrac}_{st}\,\P{RecPerc}_{c,st,t}\;""" + ENDUSE + r"""
 \;\ge\; \sum_{(i,ast):\ \mathrm{RecMap}(i,c,ast,st,t),\ \mathrm{stfeas}(ast),\ ast\neq st}\V{RECS}_{c,i,ast,st,t}
 + \sum_{(i,ast)}\V{RECS}_{\mathrm{RPS\_Bundled},i,ast,st,t}[c=\mathrm{RPS\_All}] + \sum_{(i,ast)}\V{RECS}_{\mathrm{CES\_Bundled},i,ast,st,t}[c=\mathrm{CES}]
\qquad \P{RecPerc}\neq0,\ \P{RPS\_oosfrac}_{st}\neq0,\ \mathrm{stfeas}(st),\ c\text{ unbundled},\ t\ge\P{firstyear\_RPS}
""",
        "terms": [
            ("oosfrac * RecPerc * end-use load terms", r"\ldots\V{LOAD},\ \V{GEN}_{distpv},\ \P{can\_exports\_h}", "recoos_load, recoos_gen, recoos_const from load_terms with mult = oosfrac × RecPerc (signs flipped as for unbundledLimit)", "ported; " + STYLE_CAVEAT),
            ("imported RECS (ast ≠ st)", r"\sum\V{RECS}_{ast\to st}", "into(oos_rows, −1, strict=True)", "ported"),
            ("+ bundled imports", r"+\sum\V{RECS}_{bundled}", "bundled_terms(..., −1, 'in')", "ported"),
        ],
        "prep": [("oos = (recperc.filter", 'P.coef["recoos_recs"]')],
        "build": ['"eq_REC_ooslim"'],
        "helpers": ["load_terms", "into", "bundled_terms", "recs_coef"],
    },
    "eq_REC_launder": {
        "summary": "A state cannot export more RECs than it generates in-state (less a penalty on ACP purchases).",
        "math": r"""
\sum_{(i,v,r,h):\ \mathrm{valgen},\ \mathrm{RecTech}(c,i,st,t),\ r\in st,\ h\in h_{rep}}\P{hours}_h\big(\V{GEN}_{i,v,r,h,t}-\V{CREDIT\_H2PTC}_{i,v,r,h,t}[\mathrm{valgen\_h2ptc}]\sw{Sw\_H2\_PTC}\big)
 - 10\,\V{ACP\_PURCHASES}_{c,st,t}[\neg\mathrm{acp\_disallowed}] \\
 \;\ge\; \sum_{(i,ast):\ \mathrm{RecMap}(i,c,st,ast,t),\ (\mathrm{stfeas}(ast)\vee ast=\mathrm{voluntary}),\ ast\neq st}\V{RECS}_{c,i,st,ast,t}
 + \sum_{(i,ast):\ \mathrm{stfeas}(ast),\ ast\neq st}\V{RECS}_{\mathrm{RPS\_Bundled},i,st,ast,t}[c=\mathrm{RPS\_All}] + \sum\V{RECS}_{\mathrm{CES\_Bundled},i,st,ast,t}[c=\mathrm{CES}]
\qquad \mathrm{RecStates}(c,st,t),\ """ + REC_ROWS + r""",\ c\text{ unbundled}
""",
        "terms": [
            ("hours * GEN of RecTech in state", r"\P{hours}\V{GEN}", "lau_gen (+hours)", "ported"),
            ("− hours * CREDIT_H2PTC", r"-\P{hours}\V{CREDIT\_H2PTC}", "reclau_credit (−hours) when CREDIT_H2PTC exists", "ported"),
            ("− 10 * ACP_PURCHASES", r"-10\,\V{ACP\_PURCHASES}", "lau_acp (−10)", "ported"),
            ("exported RECS (ast ≠ st, stfeas or voluntary)", r"\sum\V{RECS}_{st\to ast}", "outof(lau_rows, −1, allow_voluntary=True)", "ported"),
            ("bundled exports", r"\sum\V{RECS}_{bundled}", "bundled_terms(..., −1, 'out')", "ported"),
        ],
        "prep": [("lau_rows = (case[\"recstates\"]", 'P.var["ACP_PURCHASES"] = acp_cols'), ('P.coef["reclau_credit"] = (P.con', None)],
        "build": ['"eq_REC_launder"'],
        "helpers": ["outof", "bundled_terms", "recs_coef"],
    },
    "eq_RPS_OFSWind": {
        "summary": "State offshore-wind capacity requirement.",
        "math": r"""
\sum_{(i,v,r):\ r\in st,\ i\in\mathrm{ofswind}}\P{m\_capacity\_exog}_{i,v,r,t}
 + \sum_{(i,v,r,tt):\ r\in st,\ i\in\mathrm{ofswind},\ \mathrm{inv\_cond}(i,v,r,t,tt),\ tt\in\mathcal{T}}\big(\V{INV}_{i,v,r,tt}+\V{INV\_REFURB}_{i,v,r,tt}[\mathrm{refurbtech}]\sw{Sw\_Refurb}\big)
 \;\ge\; \P{offshore\_cap\_req}_{st,t}
\qquad \mathrm{stfeas}(st),\ \P{offshore\_cap\_req}\neq0,\ \mathrm{Sw\_StateRPS},\ \text{ofswind valcap in } st,\ t\ge\P{firstyear\_RPS}
""",
        "terms": [
            ("sum m_capacity_exog (ofswind, state)", r"\sum\P{m\_capacity\_exog}", "exog into ofs_const", "ported (constant)"),
            ("INV(t), INV_REFURB(t)", r"\V{INV}_t,\ \V{INV\_REFURB}_t", "ofs_inv, ofs_refurb (+1) on inv_cond rows with tt = t", "ported"),
            ("INV(tt), INV_REFURB(tt), tt in tfix", r"\sum_{tt<t}\overline{\V{INV}}+\overline{\V{INV\_REFURB}}", "past, past_ref into ofs_const", "ported (constant)"),
            ("offshore_cap_req", r"\P{offshore\_cap\_req}", "subtracted into ofs_const", "ported (constant)"),
        ],
        "prep": [("ofs_req = (case[\"offshore_cap_req\"]", 'P.coef["ofs_refurb"]')],
        "build": ['"eq_RPS_OFSWind"'],
        "notes": ["No rows in either case: GSw_OfsWind=0, so no offshore-wind technology is in valcap."],
    },
    "eq_national_gen": {
        "summary": "National generation mandate (RPS or CES).",
        "math": r"""
\sum_{\mathrm{valgen},\ h\in h_{rep}}\V{GEN}\,\P{hours}\,\P{nat\_gen\_tech\_frac}_i \;\ge\; \P{national\_gen\_frac}_t\Big(\big[\textstyle\sum\V{LOAD}\P{hours} + \sum\P{tranloss}\V{FLOW}\P{hours} + \sum\V{STORAGE\_IN}\P{hours} - \sum\V{GEN}_{storage}\P{hours}\big]_{\mathrm{Sw\_GenMandate}=1}
 + \big[\textstyle\sum\P{hours}((\V{LOAD}-\P{can\_exports\_h})(1-\P{distloss})-\V{GEN}_{distpv})\big]_{\mathrm{Sw\_GenMandate}=2}\Big)
""",
        "guard_only": True,
        "port_note": "Not ported. <code>prep.prepare</code> raises when Sw_GenMandate is on.",
        "prep": [("for name, msg in ((\"Sw_BankBorrowCap\"", "raise NotImplementedError(f\"{name}=1 ({msg}) is not ported\")")],
    },
    "eq_interconnection_queues": {
        "summary": "Capacity added since the start of the interconnection-queue data cannot exceed the queue limit, with a penalized slack.",
        "math": r"""
\P{queue\_limit}_{tg,r,t} + \V{CAP\_ABOVE\_LIM}_{tg,r,t} \;\ge\; \sum_{\substack{(i,v,tt):\ v\in\mathrm{newv},\ \mathrm{valinv}(i,v,r,tt),\ \mathrm{tg\_i}(tg,i),\\ tt\ge\P{interconnection\_start},\ tt\in\mathcal{T}}}\big(\V{INV}_{i,v,r,tt}+\V{INV\_REFURB}_{i,v,r,tt}[\mathrm{refurbtech}]\sw{Sw\_Refurb}\big)
\qquad t\ge\P{model\_builds\_start\_yr},\ \textstyle\sum\P{queue\_limit}\neq0,\ \text{new-vintage valinv in } tg,\ \mathrm{Sw\_QueueConstraintYears}
""",
        "terms": [
            ("queue_limit", r"\P{queue\_limit}", "queue_const (+queue_limit, zeros filled)", "ported (constant)"),
            ("CAP_ABOVE_LIM", r"\V{CAP\_ABOVE\_LIM}", "queue_above (+1); columns = rows ∪ objective-table rows (every (tg, r, t) with a cap_penalty appears in the objective and is kept by CONVERT)", "ported"),
            ("INV(t), INV_REFURB(t) new vintages, t ≥ interconnection_start", r"\V{INV}_t,\ \V{INV\_REFURB}_t", "queue_inv, queue_refurb (−1) mapped through tg_i", "ported"),
            ("prior-year INV, INV_REFURB", r"\sum_{tt<t}\ldots", "past, past_ref subtracted into queue_const", "ported (constant)"),
        ],
        "prep": [("if int(case.scalar(\"Sw_QueueConstraintYears\")):", 'P.var["CAP_ABOVE_LIM"] = pl.concat')],
        "build": ['"eq_interconnection_queues"'],
        "notes": ["No rows in either case: queue_limit is empty for 2030 there, but the 104 CAP_ABOVE_LIM columns exist through the objective."],
    },
    "eq_growthlimit_relative": {
        "summary": "Relative growth limit: this year's investment in a technology and state must fit into the growth bins, whose upper bins carry a capital-cost penalty.",
        "math": r"""
(t-t^-)\sum_{gbin}\V{GROWTH\_BIN}_{gbin,i,st,t} \;\ge\; \sum_{(v,r):\ \mathrm{valinv}(i,v,r,t),\ r\in st}\V{INV}_{i,v,r,t}
\qquad \textstyle\sum_r\mathrm{valinv\_irt}(i,r,t)[r\in st]>0,\ \mathrm{stfeas}(st),\ \mathrm{Sw\_GrowthPenalties},\ \P{model\_builds\_start\_yr}\le t\le\mathrm{Sw\_GrowthPenLastYear}
""",
        "terms": [
            ("(yeart(t) − yeart(tprev)) * sum GROWTH_BIN", r"(t-t^-)\sum_{gbin}\V{GROWTH\_BIN}", "grl_bin: +gap on every (gbin, i, st, t) of the row; gap = t − previous solve year (t itself in the first year, as GAMS sums an empty tprev)", "ported"),
            ("sum INV $[valinv$r_st]", r"\sum\V{INV}", "grl_inv (−1) on valinv rows carrying their state, summed by (i, st, t)", "ported"),
        ],
        "where": [r"GROWTH_BIN columns: gbin × rows of this equation, plus gbin × every (i, st, t) with i in a technology group that has a valinv_tg row — GAMS keeps those extra columns because eq_growthbin_limit sums over every i in the group.",
                  r"t^- is the previous solve year (tprev)."],
        "prep": [("if int(case.scalar(\"Sw_GrowthPenalties\")):", 'P.coef["gbl_bin"]')],
        "build": ['"eq_growthlimit_relative"'],
        "derive": [("reeds/open/derive_ops.py", "def growth(S: Symbols", None)],
        "notes": ["Objective: cost_growth(i,st,t) × growth_penalty(gbin) × gap on GROWTH_BIN, under pvf_capital (slice_objinv_GROWTH_BIN in derive_ops.growth).",
                  "No rows in either reference case (Sw_GrowthPenalties=0). First exercised by the Pacific_mid test case, where the equation exists only in 2030: model_builds_start_yr is 2026 and Sw_GrowthPenLastYear is 2034."],
    },
    "eq_growthbin_limit": {
        "summary": "Capacity in each growth bin of a technology group and state is limited by the bin size derived from the previous solve year's builds.",
        "math": r"""
\P{growth\_bin\_limit}_{gbin,st,tg,t} \;\ge\; \sum_{i:\ \mathrm{tg\_i}(tg,i)}\V{GROWTH\_BIN}_{gbin,i,st,t}
\qquad \mathrm{valinv\_tg}(st,tg,t),\ \mathrm{stfeas}(st),\ \mathrm{Sw\_GrowthPenalties},\ \P{model\_builds\_start\_yr}\le t\le\mathrm{Sw\_GrowthPenLastYear}
""",
        "terms": [
            ("growth_bin_limit", r"\P{growth\_bin\_limit}", "gbl_const (zeros filled: a group without a bin limit, e.g. coal, gets a 0 ≥ … row as in GAMS)", "ported (constant)"),
            ("sum GROWTH_BIN $tg_i", r"\sum_{i\in tg}\V{GROWTH\_BIN}", "gbl_bin (−1) over every i of the group, summed by (gbin, st, tg, t)", "ported"),
        ],
        "where": [r"growth_bin_limit (derive_ops.growth) follows 3_solve_oneyear.gms: in the first solve year every bin is gbin_min(tg); afterwards last_year_max_growth = INV at tprev / Σ_{allt} 1.3^{allt-t^{--}-1} × 1.3^{t^- - t^{--} - 1}, gbin1 = Σ_{allt in (t^-, t]} lymg·1.3^{allt-t^-} / (t−t^-), then the running maximum over all solved years (state_growth_bin_limit), floored at gbin_min, the other bins = gbin1 × (growth_bin_size_mult − 1.3), rounded to 0 decimals.",
                  r"valinv_tg(st,tg,t): some (i, r) with valinv_irt(i,r,t), r in st and i in tg."],
        "prep": [("if int(case.scalar(\"Sw_GrowthPenalties\")):", 'P.coef["gbl_bin"]')],
        "build": ['"eq_growthbin_limit"'],
        "derive": [("reeds/open/derive_ops.py", "def growth(S: Symbols", None)],
        "notes": ["GAMS skips the growth-bin update in the start year ($ifthene.post_startyear in 3_solve_oneyear.gms); the division there would be 0/0 otherwise.",
                  "No rows in either reference case (Sw_GrowthPenalties=0)."],
    },
    "eq_growthlimit_absolute": {
        "summary": "Absolute growth limit per technology group.",
        "math": r"(t^- - t)\,\P{growth\_limit\_absolute}_{tg} \ge \sum_{(i,v,r):\ \mathrm{valinv},\ \mathrm{tg\_i}(tg,i)}\V{INV}_{i,v,r,t}\qquad \mathrm{Sw\_GrowthAbsCon},\ t\le\mathrm{Sw\_GrowthConLastYear}",
        "guard_only": True,
        "port_note": "Not ported. <code>prep.prepare</code> raises when Sw_GrowthAbsCon is on. Note the GAMS left side uses tprev(tt,t), i.e. the year after t, so the factor is (next year − t).",
        "prep": [("for name, msg in ((\"Sw_BankBorrowCap\"", "raise NotImplementedError(f\"{name}=1 ({msg}) is not ported\")")],
    },
}
