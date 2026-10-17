from __future__ import annotations

NO_INVTRAN = "ported; no rows in either reference case because routes_inv is empty there (no INVTRAN columns)"

SPEC: dict[str, dict] = {
    "eq_INVTRAN_DC": {
        "summary": "DC investment is symmetric: the same capacity is added in both directions.",
        "math": r"""
\V{INVTRAN}_{r,rr,\tau,t} \;=\; \V{INVTRAN}_{rr,r,\tau,t}\qquad \mathrm{routes\_inv}(r,rr,\tau,t),\ \tau\notin\mathrm{aclike}
""",
        "terms": [
            ("INVTRAN(r,rr)", r"\V{INVTRAN}_{r,rr}", "invdc_fwd (+1)", "ported"),
            ("INVTRAN(rr,r)", r"\V{INVTRAN}_{rr,r}", "invdc_rev (−1) with the SWAP rename {r: rr, rr: r} on the variable", "ported"),
        ],
        "prep": [("if int(case.scalar(\"Sw_VSC\")):", 'P.var["CAPTRAN_GRP"]'), ("dc = _not_in(inv, \"trtype\"", 'P.coef["invdc_rev"]')],
        "build": ['"eq_INVTRAN_DC"'],
        "notes": [NO_INVTRAN],
    },
    "eq_INVTRAN_AC_forward": {
        "summary": "Cumulative AC capacity added in a supply-curve bin, priced at the forward bin cost, equals the capex spent in that bin.",
        "math": r"""
\sum_{tt\in\mathcal{T}:\ tt\le t,\ \mathrm{routes\_inv}(r,rr,\mathrm{AC},tt)}\V{INVTRAN\_AC}_{r,rr,tscbin,tt}\,\P{tsc\_forward}_{r,rr,tscbin} \;=\; \V{TRAN\_CAPEX\_BINS}_{r,rr,tscbin,t}
\qquad \mathrm{routes\_inv}(r,rr,\mathrm{AC},t),\ \P{tsc\_binwidth}_{r,rr,tscbin}\neq0
""",
        "terms": [
            ("INVTRAN_AC(t) * tsc_forward", r"\P{tsc\_forward}\V{INVTRAN\_AC}_t", "acfwd_inv (tsc_forward)", "ported"),
            ("INVTRAN_AC(tt) * tsc_forward, tt in tfix", r"\sum_{tt<t}\P{tsc\_forward}\overline{\V{INVTRAN\_AC}}", "acfwd_const = past_ac (state_INVTRAN_AC on routes_inv at tt) × tsc_forward", "ported (constant)"),
            ("TRAN_CAPEX_BINS", r"\V{TRAN\_CAPEX\_BINS}", "acfwd_bins (−1); the column set is routes_inv(AC) × bins with tsc_binwidth", "ported"),
        ],
        "prep": [("past_ac = (case[\"state_INVTRAN_AC\"]", 'P.coef["acfwd_bins"]')],
        "build": ['"eq_INVTRAN_AC_forward"'],
        "notes": [NO_INVTRAN],
    },
    "eq_INVTRAN_AC_reverse": {
        "summary": "The reverse direction of the same interface, priced at the reverse bin cost, spends the same capex.",
        "math": r"""
\sum_{tt\in\mathcal{T}:\ tt\le t,\ \mathrm{routes\_inv}(r,rr,\mathrm{AC},tt)}\V{INVTRAN\_AC}_{rr,r,tscbin,tt}\,\P{tsc\_reverse}_{r,rr,tscbin} \;=\; \V{TRAN\_CAPEX\_BINS}_{r,rr,tscbin,t}
""",
        "terms": [
            ("INVTRAN_AC(rr,r,t) * tsc_reverse(r,rr)", r"\P{tsc\_reverse}_{r,rr}\V{INVTRAN\_AC}_{rr,r,t}", "acrev_inv: tsc_reverse keyed on the row (r,rr), variable with r/rr swapped", "ported"),
            ("prior years", r"\sum_{tt<t}\ldots", "acrev_const = past_ac with r/rr swapped × tsc_reverse", "ported (constant)"),
            ("TRAN_CAPEX_BINS", r"\V{TRAN\_CAPEX\_BINS}", "acrev_bins (−1)", "ported"),
        ],
        "prep": [('P.con["eq_INVTRAN_AC_reverse"]', 'P.coef["acrev_bins"]')],
        "build": ['"eq_INVTRAN_AC_reverse"'],
        "notes": [NO_INVTRAN],
    },
    "eq_INVTRAN_AC": {
        "summary": "AC investment is the sum over supply-curve bins.",
        "math": r"""
\V{INVTRAN}_{r,rr,\mathrm{AC},t} \;=\; \sum_{tscbin}\V{INVTRAN\_AC}_{r,rr,tscbin,t}\qquad \mathrm{routes\_inv}(r,rr,\mathrm{AC},t)
""",
        "terms": [
            ("INVTRAN(r,rr,AC,t)", r"\V{INVTRAN}_{AC}", "invac_tran (+1) with trtype literal 'ac'", "ported"),
            ("sum INVTRAN_AC", r"\sum\V{INVTRAN\_AC}", "invac_bins (−1) summed by (r,rr,t)", "ported"),
        ],
        "prep": [('P.con["eq_INVTRAN_AC"] = rinv_ac', 'P.coef["invac_bins"]')],
        "build": ['"eq_INVTRAN_AC"'],
        "notes": [NO_INVTRAN],
    },
    "eq_TRAN_CAPEX_BINS": {
        "summary": "Capex in a bin cannot exceed the bin width.",
        "math": r"""
\P{tsc\_binwidth}_{r,rr,tscbin} \;\ge\; \V{TRAN\_CAPEX\_BINS}_{r,rr,tscbin,t}
""",
        "terms": [
            ("tsc_binwidth", r"\P{tsc\_binwidth}", "capexbin_const", "ported (constant)"),
            ("TRAN_CAPEX_BINS", r"\V{TRAN\_CAPEX\_BINS}", "capexbin_bins (−1)", "ported"),
        ],
        "prep": [('P.con["eq_TRAN_CAPEX_BINS"]', 'P.coef["capexbin_bins"]')],
        "build": ['"eq_TRAN_CAPEX_BINS"'],
        "notes": [NO_INVTRAN],
    },
    "eq_invtran_exog": {
        "summary": "Exogenously specified transmission additions are a lower bound on investment.",
        "math": r"""
\V{INVTRAN}_{r,rr,\tau,t} \;\ge\; \P{invtran\_exog}_{r,rr,\tau,t}\qquad \mathrm{routes\_inv},\ \P{invtran\_exog}\neq0
""",
        "terms": [
            ("INVTRAN", r"\V{INVTRAN}", "invexog_inv (+1)", "ported"),
            ("invtran_exog", r"\P{invtran\_exog}", "invexog_const (−invtran_exog)", "ported (constant)"),
        ],
        "prep": [("exog = case[\"invtran_exog\"]", 'P.coef["invexog_inv"]')],
        "build": ['"eq_invtran_exog"'],
        "notes": [NO_INVTRAN],
    },
    "eq_prescribed_transmission": {
        "summary": "Before the near-term transmission year, cumulative investment on an interface cannot exceed the cumulative 'possible' future capacity.",
        "math": r"""
\sum_{tt\in\mathcal{T}:\ tt\le t}\P{trancap\_fut}_{r,rr,\mathrm{possible},\tau,tt} \;\ge\; \sum_{tt\in\mathcal{T}:\ tt\le t,\ \mathrm{routes\_inv}(r,rr,\tau,tt)}\V{INVTRAN}_{r,rr,\tau,tt}
\qquad \mathrm{routes\_inv},\ t<\P{firstyear\_trans\_nearterm},\ \textstyle\sum_{tt\le t}\P{trancap\_fut}_{possible}\neq0
""",
        "terms": [
            ("sum trancap_fut possible, tt in tfix ∪ tmodel", r"\sum_{tt\in\mathcal{T},tt\le t}\P{trancap\_fut}", "fut_cum: trancap_fut_possible summed over all tt ≤ t", "ported (constant); <b>difference</b>: the port sums every year ≤ t while GAMS sums only solved years. Identical when trancap_fut is nonzero only in solved years"),
            ("INVTRAN(t)", r"\V{INVTRAN}_t", "prestran_inv (−1)", "ported"),
            ("INVTRAN(tt), tt in tfix", r"\sum_{tt<t}\overline{\V{INVTRAN}}", "past_inv (state_INVTRAN on routes_inv at tt) subtracted into prestran_const", "ported (constant)"),
            ("row condition", r"", "rows where t < firstyear_trans_nearterm and fut_cum ≠ 0 (the GAMS condition sums all years ≤ t, which fut_cum does)", "ported"),
        ],
        "prep": [("fut = case[\"trancap_fut_possible\"]", 'P.coef["prestran_inv"]')],
        "build": ['"eq_prescribed_transmission"'],
        "notes": [NO_INVTRAN],
    },
    "eq_POI_cap": {
        "summary": "Point-of-interconnection capacity (initial plus cumulative investment) must cover all AC generation capacity and LCC converter capacity in the zone.",
        "math": r"""
\P{poi\_cap\_init}_r + \sum_{tt\in\mathcal{T},\ tt\le t}\V{INV\_POI}_{r,tt}
 \;\ge\; \sum_{(i,v)\in\mathrm{valcap}_{r,t},\ i\notin\mathrm{spur\_techs}}\frac{\V{CAP}_{i,v,r,t}}{\P{ilr}_i}
 + \sum_{x}\V{CAP\_SPUR}_{x,t}\sw{Sw\_SpurScen} + \V{CAP\_CONVERTER}_{r,t}[\mathrm{val\_converter}]
 + \sum_{(rr,tt):\ \mathrm{routes\_inv}(r,rr,\mathrm{LCC},t),\ tt\in\mathcal{T},\ tt\le t}\V{INVTRAN}_{r,rr,\mathrm{LCC},tt}
\qquad \mathrm{Sw\_TransIntraCost}
""",
        "terms": [
            ("poi_cap_init", r"\P{poi\_cap\_init}", "poi_const (+poi_cap_init)", "ported (constant)"),
            ("INV_POI(t)", r"\V{INV\_POI}_t", "poi_inv (+1); INV_POI columns = every (r, t)", "ported"),
            ("INV_POI(tt), tt in tfix", r"\sum_{tt<t}\overline{\V{INV\_POI}}", "past_poi (state_INV_POI) added to poi_const", "ported (constant)"),
            ("sum CAP / ilr", r"\sum\V{CAP}/\P{ilr}", "poi_cap (−1/ilr); raises if ilr is missing or zero for a valcap tech (GAMS would divide by zero)", "ported"),
            ("CAP_SPUR $Sw_SpurScen", r"\sum_x\V{CAP\_SPUR}", "poi_spur: −1 on (r, x, t) for xfeas sites in x_r, × CAP_SPUR summed by (r,t)", "ported (spur group)"),
            ("CAP_CONVERTER $val_converter", r"\V{CAP\_CONVERTER}", "poi_conv (−1) on val_converter rows of the current year", "ported, no columns in either reference case"),
            ("INVTRAN(r,rr,LCC,t)", r"\V{INVTRAN}_{LCC,t}", "poi_lcc (−1) on current-year LCC INVTRAN", "ported, no columns in either case"),
            ("INVTRAN(r,rr,LCC,tt), tt in tfix", r"\sum_{tt<t}\overline{\V{INVTRAN}}_{LCC}", "lcc_past (state_INVTRAN lcc, on routes_inv LCC at the current t) subtracted into poi_const", "ported (constant)"),
        ],
        "prep": [("if \"INV_POI\" in P.var:", 'P.coef["poi_lcc"]')],
        "build": ['"eq_POI_cap"'],
    },
    "eq_CAPTRAN_GRP": {
        "summary": "Flow capacity between transmission groups: initial AC capacity plus derated cumulative AC investment on the member interfaces.",
        "math": r"""
\V{CAPTRAN\_GRP}_{g,gg,t} \;=\; \P{trancap\_init\_transgroup}_{g,gg,\mathrm{AC}}
 + \sum_{(r,rr,tt):\ tt\in\mathcal{T},\ tt\le t,\ \mathrm{routes\_inv}(r,rr,\mathrm{AC},tt),\ \mathrm{routes\_transgroup}(g,gg,r,rr)}\V{INVTRAN}_{r,rr,\mathrm{AC},tt}\,(1-\mathrm{Sw\_TransGroupDerate})
\qquad \mathrm{Sw\_TransGroupContraint},\ \text{group pairs with routes}
""",
        "terms": [
            ("CAPTRAN_GRP", r"\V{CAPTRAN\_GRP}", "grp_cap (+1)", "ported"),
            ("trancap_init_transgroup(AC)", r"\P{trancap\_init\_transgroup}", "grp_const = −(init + derated past investment)", "ported (constant)"),
            ("(1 − derate) INVTRAN(AC,t)", r"(1-\delta_g)\V{INVTRAN}_{AC,t}", "grp_inv (−(1 − derate)) on AC INVTRAN mapped through routes_transgroup", "ported, no columns in either case"),
            ("(1 − derate) INVTRAN(AC,tt), tt in tfix", r"\sum_{tt<t}(1-\delta_g)\overline{\V{INVTRAN}}", "past_g (state_INVTRAN ac × (1 − derate)) into grp_const", "ported (constant)"),
        ],
        "prep": [("rtg = case[\"routes_transgroup\"]", 'P.var["CAPTRAN_GRP"]'), ("if \"CAPTRAN_GRP\" in P.var:", 'P.coef["grp_inv"]')],
        "build": ['"eq_CAPTRAN_GRP"'],
    },
    "eq_transgrp_limit_energy": {
        "summary": "Combined AC flow across a transmission-group interface is limited by the group capacity.",
        "math": r"""
\V{CAPTRAN\_GRP}_{g,gg,t}\,(1+\P{trans\_cap\_delta}_{h,t}) \;\ge\; \sum_{(r,rr):\ \mathrm{routes\_transgroup}(g,gg,r,rr)}\V{FLOW}_{r,rr,h,t,\mathrm{AC}}
""",
        "terms": [
            ("CAPTRAN_GRP * (1 + trans_cap_delta)", r"\V{CAPTRAN\_GRP}(1+\delta_{h,t})", "grplim_cap (1 + d)", "ported"),
            ("sum FLOW(AC)", r"\sum\V{FLOW}_{AC}", "grplim_flow (−1) on AC FLOW mapped through routes_transgroup, summed by (g, gg, h, t)", "ported"),
        ],
        "prep": [("lim_dom = grp_dom.join(h", 'P.coef["grplim_flow"]')],
        "build": ['"eq_transgrp_limit_energy"'],
    },
    "eq_firm_transfer_limit": {
        "summary": "In stress hours, net firm imports into a planning region are capped at a fraction of its peak load.",
        "math": r"""
\P{firm\_import\_limit}_{tr,t}\,\P{peakload\_transreg}_{tr,t}
 \;\ge\; \sum_{(r,rr,\tau,trr):\ \mathrm{routes}(rr,r,\tau,t),\ \mathrm{routes\_prm}(rr,r),\ \mathrm{routes\_transreg}(trr,tr,rr,r)}\V{FLOW}_{rr,r,h,t,\tau}(1-\P{tranloss}_{rr,r,\tau})
 - \sum_{(r,rr,\tau,trr):\ \mathrm{routes}(r,rr,\tau,t),\ \mathrm{routes\_prm}(r,rr),\ \mathrm{routes\_transreg}(tr,trr,r,rr)}\V{FLOW}_{r,rr,h,t,\tau}
\qquad h\in h_{stress},\ \mathrm{Sw\_PRM\_NetImportLimit}
""",
        "terms": [
            ("firm_import_limit * peakload_transreg", r"\P{firm\_import\_limit}\,\P{peakload\_transreg}", "firm_const (lim × peak, missing → 0)", "ported (constant)"),
            ("imports * (1 − tranloss)", r"\V{FLOW}_{rr\to r}(1-\P{tranloss})", "firm_flow imports: −(1 − loss) on FLOW(r,rr) keyed by the receiving region (routes_transreg with the region pair swapped), stress hours, routes_prm", "ported"),
            ("− exports", r"-\V{FLOW}_{r\to rr}", "firm_flow exports: +1 keyed by the sending region", "ported"),
            ("row set", r"", "rows with at least one FLOW term", "ported"),
        ],
        "prep": [("if int(case.scalar(\"Sw_PRM_NetImportLimit\")):", 'P.coef["firm_flow"]')],
        "build": ['"eq_firm_transfer_limit"'],
    },
    "eq_transmission_investment_max": {
        "summary": "Annual cap on transmission investment in MW-miles.",
        "math": r"""
\P{trans\_inv\_max}_t\cdot10^6\cdot(t-t^-) \;\ge\; \sum_{\mathrm{routes\_inv}(r,rr,\tau,t)}\frac{\V{INVTRAN}_{r,rr,\tau,t}+\V{INVTRAN}_{rr,r,\tau,t}}{2}\P{distance}_{r,rr,\tau}
 + \sum_{\mathrm{valinv},\ \mathrm{rsc\_i},\ \mathrm{m\_rscfeas}}\V{INV\_RSC}_{i,v,r,rscbin,t}\big(\P{distance\_reinforcement}_{i,r,rscbin}+\P{distance\_spur}_{i,r,rscbin}[\mathrm{Sw\_TransInvMaxTypes}=3]\big)[\mathrm{Sw\_TransInvMaxTypes}\in\{2,3\}]
\qquad \P{trans\_inv\_max}_t\neq0,\ \mathrm{Sw\_TransInvMaxTypes}
""",
        "terms": [
            ("trans_inv_max * 1e6 * (t − tprev)", r"\P{trans\_inv\_max}\cdot10^6(t-t^-)", "tim_const", "ported (constant)"),
            ("(INVTRAN(r,rr) + INVTRAN(rr,r))/2 * distance over routes_inv", r"\tfrac12(\V{INVTRAN}_{r,rr}+\V{INVTRAN}_{rr,r})\P{distance}", "tim_inv: −0.5·distance(r,rr) on INVTRAN(r,rr) and on INVTRAN(rr,r), summed per column (each column collects both directions' halves)", "ported, no columns in either case"),
            ("INV_RSC * (distance_reinforcement + distance_spur)", r"\V{INV\_RSC}(\P{d}_{reinf}+\P{d}_{spur})", "tim_rsc when Sw_TransInvMaxTypes is 2 or 3, else an empty table", "ported"),
        ],
        "prep": [("tim_types = int(case.scalar", 'P.coef["tim_rsc"] = pl.DataFrame')],
        "build": ['"eq_transmission_investment_max"'],
        "notes": ["GAMS writes the row only when INVTRAN exists (the equation is in the trans group); the port builds it only when the INVTRAN column exists, which matches CONVERT dropping a row whose only variables are absent."],
    },
    "eq_CAPTRAN_max": {
        "summary": "Upper limit on transmission capacity of each capped type on an interface.",
        "math": r"""
\mathrm{Sw\_TransCapMaxEachType}\cdot1000 \;\ge\; \V{CAPTRAN\_ENERGY}_{r,rr,\tau,t}\qquad \mathrm{routes},\ \tau\in\mathrm{trtypemax}
""",
        "terms": [("constant", r"\mathrm{Sw\_TransCapMaxEachType}\cdot1000", "ctmax_const", "ported"), ("CAPTRAN_ENERGY", r"\V{CAPTRAN\_ENERGY}", "ctmax_cap (−1)", "ported")],
        "prep": [("tmax = case.members(\"trtypemax\")", 'P.coef["ctmax_cap"]')],
        "build": ['"eq_CAPTRAN_max"'],
        "notes": ["No rows in either case: Sw_TransCapMaxEachType is 0 there."],
    },
    "eq_CAPTRAN_max_total": {
        "summary": "Upper limit on the total capacity of all capped types on an interface.",
        "math": r"""
\mathrm{Sw\_TransCapMaxAllTypes}\cdot1000 \;\ge\; \sum_{\tau\in\mathrm{trtypemax}}\V{CAPTRAN\_ENERGY}_{r,rr,\tau,t}
""",
        "terms": [("constant", r"\mathrm{Sw\_TransCapMaxAllTypes}\cdot1000", "ctmaxt_const", "ported"), ("sum CAPTRAN_ENERGY", r"\sum_\tau\V{CAPTRAN\_ENERGY}", "ctmaxt_cap (−1) summed by (r,rr,t)", "ported")],
        "prep": [("allt = case.scalar", 'P.coef["ctmaxt_cap"]')],
        "build": ['"eq_CAPTRAN_max_total"'],
        "notes": ["No rows in either case: Sw_TransCapMaxAllTypes is 0 there."],
    },
    "eq_offshore_no_backflow": {
        "summary": "No flow from land zones into offshore zones.",
        "math": r"""
\V{FLOW}_{r,rr,h,t,\tau} \;=\; 0\qquad \mathrm{routes}(r,rr,\tau,t),\ r\in\mathrm{land},\ rr\in\mathrm{offshore},\ \neg\mathrm{Sw\_OffshoreBackflow}
""",
        "terms": [("FLOW", r"\V{FLOW}", "offbf_flow (+1) == 0", "ported")],
        "prep": [("if not int(case.scalar(\"Sw_OffshoreBackflow\")):", 'P.coef["offbf_flow"]')],
        "build": ['"eq_offshore_no_backflow"'],
        "notes": ["No rows in either case: the Pacific cases have no offshore zones (GSw_OfsWind=0)."],
    },
    "eq_CAP_CONVERTER": {
        "summary": "VSC converter capacity accumulates converter investment.",
        "math": r"\V{CAP\_CONVERTER}_{r,t} = \sum_{tt\in\mathcal{T},\ tt\le t}\V{INV\_CONVERTER}_{r,tt}\qquad \mathrm{val\_converter}(r,t),\ \mathrm{Sw\_VSC}",
        "terms": [
            ("CAP_CONVERTER", r"\V{CAP\_CONVERTER}", "capconv_cap (+1); columns = val_converter rows of the current year", "ported"),
            ("INV_CONVERTER(t)", r"\V{INV\_CONVERTER}_t", "capconv_inv (−1)", "ported"),
            ("INV_CONVERTER(tt), tt in tfix", r"\sum_{tt<t}\overline{\V{INV\_CONVERTER}}", "capconv_const = −past_conv (state_INV_CONVERTER summed over tt ≤ t)", "ported (constant)"),
        ],
        "prep": [("CONV = [\"r\", \"h\", \"intype\", \"outtype\", \"t\"]", 'P.coef["poi_conv"]')],
        "build": ['"eq_CAP_CONVERTER"'],
        "where": [r"val_converter(r,t): zones at either end of a VSC route in routes_inv (derive_costs); Sw_VSC is 1 when any route is VSC."],
        "notes": ["No rows in the Pacific cases (no VSC routes). Validated on the WECC_oracle case in 2035 (4 rows): GAMS sums INV_CONVERTER over every past year, while 5_varfix.gms fixes it only where val_converter held in that year, so the 2010–2030 columns (18 here) are free and carry no cost in the 2035 solve. GAMS used them to place its converters; the port adds the same columns (prep: conv_unfixed_past) and keeps their levels out of capconv_const."],
    },
    "eq_CONVERSION_limit_energy": {
        "summary": "AC/DC conversion in an hour is limited by converter capacity.",
        "math": r"\V{CAP\_CONVERTER}_{r,t} \ge \V{CONVERSION}_{r,h,\mathrm{AC}\to\mathrm{VSC},t}+\V{CONVERSION}_{r,h,\mathrm{VSC}\to\mathrm{AC},t}",
        "terms": [
            ("CAP_CONVERTER", r"\V{CAP\_CONVERTER}_{r,t}", "convlim_cap (+1) on every (r,h,t) row; the (r,t) variable is broadcast over h by the join", "ported"),
            ("CONVERSION both directions", r"\V{CONVERSION}", "convlim_conv (−1) summed by (r,h,t)", "ported"),
        ],
        "prep": [("CONV = [\"r\", \"h\", \"intype\", \"outtype\", \"t\"]", 'P.coef["poi_conv"]')],
        "build": ['"eq_CONVERSION_limit_energy"'],
        "notes": ["No rows in the Pacific cases (no VSC routes); validated on the WECC_oracle case in 2035 (800 rows)."],
    },
    "eq_vsc_flow": {
        "summary": "DC power balance of the VSC network.",
        "math": r"""
\sum_{rr:\ \mathrm{routes}(rr,r,\mathrm{VSC},t)}(1-\P{tranloss}_{rr,r,\mathrm{VSC}})\V{FLOW}_{rr,r,h,t,\mathrm{VSC}} - \sum_{rr}\V{FLOW}_{r,rr,h,t,\mathrm{VSC}}
 + \V{CONVERSION}_{\mathrm{AC}\to\mathrm{VSC}}\,\eta_{vsc} - \V{CONVERSION}_{\mathrm{VSC}\to\mathrm{AC}}/\eta_{vsc} + \sum_{(i,v)\in\mathrm{valgen},\ r\in\mathrm{offshore}}\V{GEN}_{i,v,r,h,t} \;=\; 0
""",
        "terms": [
            ("sum (1-tranloss)*FLOW(rr,r,VSC)", r"\sum(1-\P{tranloss})\V{FLOW}_{rr,r,\mathrm{VSC}}", "vsc_import: (1 − tranloss) on VSC FLOW rows with r and rr swapped, so the row index is the receiving zone; applied with the SWAP rename on FLOW", "ported"),
            ("− sum FLOW(r,rr,VSC)", r"-\sum\V{FLOW}_{r,rr,\mathrm{VSC}}", "vsc_export (−1) on VSC FLOW rows summed by (r,h,t)", "ported"),
            ("CONVERSION(AC→VSC)·η − CONVERSION(VSC→AC)/η", r"\pm\V{CONVERSION}", "vsc_conv: +η on (ac, vsc), −1/η on (vsc, ac)", "ported"),
            ("sum GEN $[valgen$offshore(r)]", r"\sum\V{GEN}", "vsc_offgen (+1) on GEN rows in offshore zones", "ported, no columns in either reference case (no offshore zones)"),
        ],
        "where": [r"Rows: every (r,h,t) that carries a VSC flow, a converter or offshore generation; GAMS writes the row for every r and CONVERT drops the empty ones."],
        "prep": [("CONV = [\"r\", \"h\", \"intype\", \"outtype\", \"t\"]", 'P.coef["poi_conv"]')],
        "build": ['"eq_vsc_flow"'],
        "notes": ["No rows in the Pacific cases (no VSC routes); validated on the WECC_oracle case in 2035 (800 rows)."],
    },
    "eq_converter_max": {
        "summary": "Upper limit on VSC converter capacity per zone.",
        "math": r"\mathrm{Sw\_VSC\_ConverterMax} \ge \V{CAP\_CONVERTER}_{r,t}\qquad \mathrm{val\_converter}(r,t),\ \mathrm{Sw\_VSC},\ \mathrm{Sw\_VSC\_ConverterMax}\neq0",
        "terms": [
            ("Sw_VSC_ConverterMax", r"\mathrm{Sw\_VSC\_ConverterMax}", "convmax_const", "ported (constant)"),
            ("CAP_CONVERTER", r"\V{CAP\_CONVERTER}", "convmax_cap (−1)", "ported"),
        ],
        "prep": [("conv_max = case.scalar(\"Sw_VSC_ConverterMax\")", 'P.coef["convmax_cap"]')],
        "build": ['"eq_converter_max"'],
        "notes": ["No rows in either reference case; GSw_VSC_ConverterMax is 0 in every test case, so the equation is also absent from the WECC case."],
    },
}
