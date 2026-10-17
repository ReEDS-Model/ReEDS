from __future__ import annotations

H2ROWS = r"\mathrm{Sw\_H2}=2,\ t\ge\P{h2\_demand\_start}"

SPEC: dict[str, dict] = {
    "eq_prod_capacity_limit": {
        "summary": "Production (hydrogen, DAC) is limited by available capacity times the conversion rate.",
        "math": r"""
\V{CAP}_{i,v,r,t}\,\P{avail}_{i,r,h}\big(\P{prod\_conversion\_rate}_{i,v,r,t}[i\neq\mathrm{dac\_gas}]+1[i=\mathrm{dac\_gas}]\big)\big(1+\textstyle\sum_{szn}\P{h\_szn}_{h,szn}\P{seas\_cap\_frac\_delta}_{i,v,r,szn,t}\big)
 \;\ge\; \sum_{p:\ \mathrm{i\_p}(i,p)}\V{PRODUCE}_{p,i,v,r,h,t}
\qquad i\in\mathrm{consume},\ \mathrm{valcap},\ \mathrm{Sw\_Prod},\ h\in h_{rep}
""",
        "terms": [
            ("CAP * avail * (pcr or 1) * (1 + seas delta)", r"\ldots\V{CAP}", "prodcap_cap: ((avail × (1 for dac_gas else pcr)) × (1 + d))", "ported"),
            ("sum PRODUCE over p", r"\sum_p\V{PRODUCE}", "prodcap_produce (−1) summed over p by _row", "ported"),
        ],
        "prep": [("sw_h2 = int(case.scalar(\"Sw_H2\"))", "h2_start = case.scalar"), ("if sw_prod:", 'P.coef["prodcap_produce"]')],
        "build": ['"eq_prod_capacity_limit"'],
        "notes": ["Sw_Prod is derived as 1 when Sw_H2, Sw_DAC or Sw_DAC_Gas is on (derive_ops.hydrogen), matching the GAMS definition."],
    },
    "eq_h2_demand": {
        "summary": "National annual hydrogen balance (Sw_H2=1).",
        "math": r"""
\sum_{\mathrm{h2},\ \mathrm{valcap},\ h\in h_{rep}}\V{PRODUCE}_{H2,i,v,r,h,t}\P{hours}_h \;=\; \P{h2\_exogenous\_demand}_{H2,t} + \sum_{\mathrm{valgen},\ i\in\mathrm{h2\_gen},\ h\in h_{rep}}\V{GEN}\,\P{hours}_h\,\P{h2\_combustion\_intensity}\,\P{heat\_rate}
""",
        "guard_only": True,
        "port_note": "Not ported. <code>prep.prepare</code> raises when Sw_H2 is 1; both reference cases use Sw_H2=2 (regional balance).",
        "prep": [("if sw_h2 == 1:", None)],
    },
    "eq_h2_demand_regional": {
        "summary": "Hourly regional hydrogen balance: production plus net pipeline imports plus net storage withdrawals equals exogenous demand plus hydrogen burned in H2 generators.",
        "math": r"""
\sum_{(i,v,p):\ i\in\mathrm{h2},\ \mathrm{valcap},\ \mathrm{i\_p}(i,p)}\V{PRODUCE}_{p,i,v,r,h,t}
 + (1-\P{h2\_tranloss})\sum_{rr:\ \mathrm{h2\_routes}(rr,r)}\V{H2\_FLOW}_{rr,r,h,t} - \sum_{rr:\ \mathrm{h2\_routes}(r,rr)}\V{H2\_FLOW}_{r,rr,h,t}
 + \sum_{s\in\mathrm{h2\_stor\_r}(r)}\big(\V{H2\_STOR\_OUT}_{s,r,h,t}-\V{H2\_STOR\_IN}_{s,r,h,t}\big) \\
 \;=\; \sum_p\P{h2\_exogenous\_demand\_regional}_{r,p,h,t} + \sum_{(i,v)\in\mathrm{valgen},\ i\in\mathrm{h2\_gen}}\V{GEN}_{i,v,r,h,t}\,\P{h2\_combustion\_intensity}\,\P{heat\_rate}_{i,v,r,t}
\qquad """ + H2ROWS + r""",\ h\in h_{rep}
""",
        "terms": [
            ("sum PRODUCE (h2 techs)", r"\sum\V{PRODUCE}", "h2dem_produce (+1)", "ported"),
            ("net H2_FLOW", r"\pm\V{H2\_FLOW}", "h2dem_flow_in / h2dem_flow_out are empty tables", "not ported; prep raises when h2_routes has rows"),
            ("H2_STOR_OUT − H2_STOR_IN", r"\V{H2\_STOR\_OUT}-\V{H2\_STOR\_IN}", "h2dem_stor_out (+1), h2dem_stor_in (−1)", "ported"),
            ("sum_p h2_exogenous_demand_regional", r"\sum_p\P{h2\_exogenous\_demand\_regional}", "h2dem_const (−Σ_p)", "ported (constant)"),
            ("GEN * h2_combustion_intensity * heat_rate", r"\V{GEN}\,\P{hci}\,\P{heat\_rate}", "h2dem_gen (−(hci·hr))", "ported"),
            ("row set", r"", "GAMS writes every (r, h, t); rows without any variable are dropped by CONVERT, the port keeps rows with a PRODUCE, storage or GEN term", "ported"),
        ],
        "prep": [("if sw_h2 == 2 and (tmodel[\"t\"] >= h2_start).all():", 'P.coef["h2dem_flow_out"]')],
        "build": ['"eq_h2_demand_regional"'],
    },
    "eq_h2_transport_caplimit": {
        "summary": "Bidirectional pipeline flow is limited by cumulative pipeline investment.",
        "math": r"""
\sum_{tt\in\mathcal{T}:\ \P{h2\_demand\_start}\le tt\le t}\big(\V{H2\_TRANSPORT\_INV}_{r,rr,tt}[\mathrm{h2\_routes\_inv}(r,rr)]+\V{H2\_TRANSPORT\_INV}_{rr,r,tt}[\mathrm{h2\_routes\_inv}(rr,r)]\big) \;\ge\; \V{H2\_FLOW}_{rr,r,h,t}+\V{H2\_FLOW}_{r,rr,h,t}
\qquad \mathrm{h2\_routes}(r,rr),\ """ + H2ROWS,
        "guard_only": True,
        "port_note": "Not ported. The build has a row definition with the forward/reverse investment and flow terms, but every coefficient table is empty and <code>prep.prepare</code> raises when h2_routes has rows (derive_ops also raises when Sw_H2_Transport is on).",
        "prep": [("routes_h2 = case[\"h2_routes\"]", "raise NotImplementedError(\"hydrogen pipeline routes are not ported\")"), ("for key in [\"h2tc_const\"", None)],
        "build": ['"eq_h2_transport_caplimit"'],
    },
    "eq_h2_storage_level": {
        "summary": "Hourly hydrogen storage balance (Sw_H2_StorTimestep=2).",
        "math": r"\sum_{(hh,s'):\ \mathrm{nexth\_actualszn}(s,h,s',hh)}\V{H2\_STOR\_LEVEL}_{st,r,s',hh,t} = \V{H2\_STOR\_LEVEL}_{st,r,s,h,t} + \P{hd}_h(\V{H2\_STOR\_IN}-\V{H2\_STOR\_OUT})_{st,r,h,t}",
        "guard_only": True,
        "port_note": "Not ported. <code>prep.prepare</code> raises when Sw_H2_StorTimestep is 2; both reference cases use the seasonal timestep (1).",
        "prep": [("if sw_h2 == 2 and int(case.scalar(\"Sw_H2_StorTimestep\")) == 2:", None)],
    },
    "eq_h2_storage_level_szn": {
        "summary": "Seasonal hydrogen storage balance: the level at the start of the next period equals this period's start level plus net injections.",
        "math": r"""
\sum_{s':\ \mathrm{nextszn}(s,s')}\V{H2\_STOR\_LEVEL\_SZN}_{st,r,s',t} \;=\; \V{H2\_STOR\_LEVEL\_SZN}_{st,r,s,t} + \sum_{h:\ \mathrm{h\_actualszn}(h,s)}\P{hd}_h\big(\V{H2\_STOR\_IN}_{st,r,h,t}-\V{H2\_STOR\_OUT}_{st,r,h,t}\big)
\qquad \mathrm{h2\_stor\_r}(st,r),\ \mathrm{Sw\_H2\_StorTimestep}=1,\ """ + H2ROWS,
        "terms": [
            ("LEVEL_SZN(next season)", r"\V{H2\_STOR\_LEVEL\_SZN}_{s'}", "h2lvl_next (+1): row season joined to nextszn, variable actualszn renamed actualsznn", "ported"),
            ("LEVEL_SZN(this season)", r"\V{H2\_STOR\_LEVEL\_SZN}_{s}", "h2lvl_this (−1)", "ported"),
            ("hours_daily * H2_STOR_IN", r"\P{hd}\V{H2\_STOR\_IN}", "h2lvl_in (−hd) over the hours of the actual season", "ported"),
            ("− hours_daily * H2_STOR_OUT", r"-\P{hd}\V{H2\_STOR\_OUT}", "h2lvl_out (+hd)", "ported"),
        ],
        "prep": [("HS4 = [\"h2_stor\", \"r\", \"actualszn\", \"t\"]", 'P.coef["h2lvl_out"]')],
        "build": ['"eq_h2_storage_level_szn"'],
        "notes": ["actualszn runs over the 365 actual days (2,920 rows = 8 storage/zone pairs × 365), while H2_STOR_IN/OUT exist only for representative hours; h_actualszn maps each actual day to its representative hours."],
    },
    "eq_h2_storage_capacity": {
        "summary": "Hydrogen storage capacity accumulates storage investment.",
        "math": r"""
\sum_{tt\in\mathcal{T},\ tt\le t}\V{H2\_STOR\_INV}_{st,r,tt} \;=\; \V{H2\_STOR\_CAP}_{st,r,t}\qquad \mathrm{h2\_stor\_r}(st,r),\ """ + H2ROWS,
        "terms": [
            ("H2_STOR_INV(t)", r"\V{H2\_STOR\_INV}_t", "h2cap_inv (+1)", "ported"),
            ("H2_STOR_INV(tt), tt in tfix", r"\sum_{tt<t}\overline{\V{H2\_STOR\_INV}}", "h2cap_const (state_H2_STOR_INV)", "ported (constant)"),
            ("H2_STOR_CAP", r"\V{H2\_STOR\_CAP}", "h2cap_cap (−1)", "ported"),
        ],
        "prep": [("cap_dom = P.var[\"H2_STOR_CAP\"]", 'P.coef["h2cap_cap"]')],
        "build": ['"eq_h2_storage_capacity"'],
    },
    "eq_h2_min_storage_cap": {
        "summary": "Minimum hydrogen storage: enough to run the H2 generators for Sw_H2_MinStorHours.",
        "math": r"""
\sum_{st\in\mathrm{h2\_stor\_r}(r)}\V{H2\_STOR\_CAP}_{st,r,t} \;\ge\; \sum_{(i,v)\in\mathrm{valcap},\ i\in\mathrm{h2\_gen}}\V{CAP}_{i,v,r,t}\,\P{heat\_rate}_{i,v,r,t}\,\P{h2\_combustion\_intensity}\,\mathrm{Sw\_H2\_MinStorHours}
\qquad \mathrm{Sw\_H2}=2,\ \mathrm{Sw\_H2\_MinStorHours}
""",
        "terms": [
            ("sum H2_STOR_CAP", r"\sum\V{H2\_STOR\_CAP}", "h2min_cap (+1)", "ported"),
            ("CAP * heat_rate * hci * MinStorHours", r"\V{CAP}\P{heat\_rate}\P{hci}\,\mathrm{Sw\_H2\_MinStorHours}", "h2min_gen = −(((1·hr)·hci)·msh)", "ported"),
            ("row set", r"", "GAMS writes every (r, t); the port keeps zones with a storage or a CAP term (CONVERT drops the rest)", "ported"),
        ],
        "prep": [("msh = case.scalar(\"Sw_H2_MinStorHours\")", 'P.coef["h2min_gen"]')],
        "build": ['"eq_h2_min_storage_cap"'],
    },
    "eq_h2_storage_flowlimit": {
        "summary": "Injection plus withdrawal rate is limited by storage capacity over the design duration.",
        "math": r"""
\frac{\V{H2\_STOR\_CAP}_{st,r,t}}{\P{h2\_storage\_duration}} \;\ge\; \V{H2\_STOR\_IN}_{st,r,h,t}+\V{H2\_STOR\_OUT}_{st,r,h,t}\qquad \mathrm{h2\_stor\_r},\ h\in h_{rep},\ """ + H2ROWS,
        "terms": [
            ("H2_STOR_CAP / h2_storage_duration", r"\V{H2\_STOR\_CAP}/\P{dur}", "h2fl_cap (1/h2_storage_duration)", "ported"),
            ("H2_STOR_IN + H2_STOR_OUT", r"\V{H2\_STOR\_IN}+\V{H2\_STOR\_OUT}", "h2fl_in, h2fl_out (−1)", "ported"),
        ],
        "prep": [("fl_dom = stor_rows.select", 'P.coef["h2fl_out"]')],
        "build": ['"eq_h2_storage_flowlimit"'],
    },
    "eq_h2_storage_caplimit": {
        "summary": "Hourly storage level cannot exceed capacity (Sw_H2_StorTimestep=2).",
        "math": r"\V{H2\_STOR\_CAP}_{st,r,t} \ge \V{H2\_STOR\_LEVEL}_{st,r,s,h,t}",
        "guard_only": True,
        "port_note": "Not ported (Sw_H2_StorTimestep=2 guard).",
        "prep": [("if sw_h2 == 2 and int(case.scalar(\"Sw_H2_StorTimestep\")) == 2:", None)],
    },
    "eq_h2_storage_caplimit_szn": {
        "summary": "Seasonal storage level cannot exceed capacity.",
        "math": r"\V{H2\_STOR\_CAP}_{st,r,t} \;\ge\; \V{H2\_STOR\_LEVEL\_SZN}_{st,r,s,t}\qquad \mathrm{h2\_stor\_r},\ \mathrm{Sw\_H2\_StorTimestep}=1,\ " + H2ROWS,
        "terms": [("H2_STOR_CAP", r"\V{H2\_STOR\_CAP}", "h2cl_cap (+1)", "ported"), ("H2_STOR_LEVEL_SZN", r"\V{H2\_STOR\_LEVEL\_SZN}", "h2cl_lvl (−1)", "ported")],
        "prep": [('P.con["eq_h2_storage_caplimit_szn"]', 'P.coef["h2cl_lvl"]')],
        "build": ['"eq_h2_storage_caplimit_szn"'],
    },
    "eq_h2_ptc_region_balance": {
        "summary": "Annual matching for the hydrogen PTC: credited clean generation in a region equals the electricity used by electrolyzers.",
        "math": r"""
\sum_{(i,v,r,h):\ \mathrm{r\_h2ptcreg}(r,g),\ h\in h_{rep},\ \mathrm{valgen\_h2ptc}}\V{CREDIT\_H2PTC}_{i,v,r,h,t}
 \;=\; \sum_{(v,r,h):\ \mathrm{r\_h2ptcreg}(r,g),\ \mathrm{valcap}(\mathrm{electrolyzer}),\ \P{pcr}\neq0}\frac{\V{PRODUCE}_{H2,\mathrm{electrolyzer},v,r,h,t}}{\P{prod\_conversion\_rate}_{\mathrm{electrolyzer},v,r,t}}
\qquad \mathrm{h2\_ptc\_years}(t),\ t\ge\P{h2\_demand\_start},\ \mathrm{Sw\_H2\_PTC},\ t<\P{h2\_ptc\_temporal\_match\_year}
""",
        "terms": [
            ("sum CREDIT_H2PTC", r"\sum\V{CREDIT\_H2PTC}", "ptcb_credit (+1) mapped through r_h2ptcreg", "ported"),
            ("sum PRODUCE / pcr", r"\sum\V{PRODUCE}/\P{pcr}", "ptcb_produce (−1/pcr) on electrolyzer H2 PRODUCE", "ported"),
            ("row set", r"", "regions with a credit or a produce term", "ported"),
        ],
        "prep": [("if int(case.scalar(\"Sw_H2_PTC\")) and sw_h2:", 'P.coef["ptch_produce"]')],
        "build": ['"eq_h2_ptc_region_balance"', '"eq_h2_ptc_region_hour_balance"', '"eq_h2_ptc_creditgen"'],
        "notes": ["In both reference cases 2030 is at or after h2_ptc_temporal_match_year, so the hourly variant has the rows and this annual variant has none."],
    },
    "eq_h2_ptc_region_hour_balance": {
        "summary": "Hourly matching for the hydrogen PTC (from the temporal-match year).",
        "math": r"""
\sum_{(i,v,r):\ \mathrm{r\_h2ptcreg}(r,g),\ \mathrm{valgen\_h2ptc}}\V{CREDIT\_H2PTC}_{i,v,r,h,t}
 \;=\; \sum_{(v,r):\ \mathrm{r\_h2ptcreg}(r,g),\ \mathrm{valcap}(\mathrm{electrolyzer}),\ \P{pcr}\neq0}\frac{\V{PRODUCE}_{H2,\mathrm{electrolyzer},v,r,h,t}}{\P{prod\_conversion\_rate}}
\qquad h\in h_{rep},\ \mathrm{h2\_ptc\_years}(t),\ t\ge\P{h2\_demand\_start},\ \mathrm{Sw\_H2\_PTC},\ t\ge\P{h2\_ptc\_temporal\_match\_year}
""",
        "terms": [
            ("sum CREDIT_H2PTC per hour", r"\sum\V{CREDIT\_H2PTC}", "ptch_credit (+1)", "ported"),
            ("sum PRODUCE / pcr per hour", r"\sum\V{PRODUCE}/\P{pcr}", "ptch_produce (−1/pcr)", "ported"),
        ],
        "prep": [("match_year = case.scalar(\"h2_ptc_temporal_match_year\")", 'P.coef["ptch_produce"]')],
        "build": ['"eq_h2_ptc_region_hour_balance"'],
    },
    "eq_h2_ptc_creditgen": {
        "summary": "Credited generation cannot exceed generation.",
        "math": r"\V{GEN}_{i,v,r,h,t} \;\ge\; \V{CREDIT\_H2PTC}_{i,v,r,h,t}\qquad \mathrm{valgen\_h2ptc}(i,v,r,t),\ h\in h_{rep},\ \mathrm{Sw\_H2\_PTC},\ \mathrm{h2\_ptc\_years}(t),\ t\ge\P{h2\_demand\_start}",
        "terms": [("GEN", r"\V{GEN}", "ptcg_gen (+1)", "ported"), ("CREDIT_H2PTC", r"\V{CREDIT\_H2PTC}", "ptcg_credit (−1); CREDIT_H2PTC columns = valgen_h2ptc × representative hours", "ported")],
        "prep": [("ptc_year = tmodel.join(case[\"h2_ptc_years\"]", 'P.coef["ptcg_credit"]')],
        "build": ['"eq_h2_ptc_creditgen"'],
    },
}
