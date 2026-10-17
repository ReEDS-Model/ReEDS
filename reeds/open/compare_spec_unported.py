from __future__ import annotations

GUARD_LOOP = ("for name, what in ((\"Sw_LoadSiteCF\"", "raise NotImplementedError(\"interday storage equations are not ported\")")
PRM = "Not ported. <code>prep.prepare</code> raises when Sw_PRM_CapCredit is 1. Both reference cases use stress periods (Sw_PRM_CapCredit=0), so the capacity-credit family (CAP_SDBIN, PRMTRADE, CONVERSION_PRM, reserve margin) has no GAMS rows to validate against; a reference run with Sw_PRM_CapCredit=1 is needed."
VSC = "Not ported. <code>prep.prepare</code> raises when Sw_VSC is 1."
GAS03 = "Not ported. <code>prep.prepare</code> raises when Sw_GasCurve is 0 or 3 (GASUSED and the gas bins do not exist in the port)."
INTERDAY = "Not ported. <code>prep.prepare</code> raises when any storage_interday technology is in valgen (STORAGE_INTERDAY_* variables do not exist in the port)."
HYBRID = "Not ported. <code>prep.prepare</code> raises when Sw_HybridPlant is 1 and a hybrid (non-CSP) technology is in valgen; GEN_PLANT, GEN_STORAGE, STORAGE_IN_PLANT and STORAGE_IN_GRID do not exist in the port. With Sw_HybridPlant=0 GAMS writes none of these rows either."
WATER = "Not ported. derive.py raises when Sw_WaterMain is 1 (WAT, WATCAP, WATER_CAPACITY_LIMIT_SLACK do not exist in the port)."
CO2 = "Not ported. <code>prep.prepare</code> raises when Sw_CO2_Detail is 1 (CO2_CAPTURED, CO2_STORED, CO2_FLOW, CO2_TRANSPORT_INV, CO2_SPURLINE_INV do not exist in the port)."
CCS = "Not ported. <code>prep.prepare</code> raises when any of Sw_CCSFLEX_BYP, Sw_CCSFLEX_STO, Sw_CCSFLEX_DAC is 1 (CCSFLEX_* variables do not exist in the port)."
LOADSITE = "Not ported. <code>prep.prepare</code> raises when Sw_LoadSiteCF is nonzero (CAP_LOADSITE, INV_LOADSITE, OP_LOADSITE do not exist in the port)."
FLEX = "Not ported. derive_temporal raises when flexible load is present (FLEX does not exist in the port)."
ITL = "Not ported. <code>prep.prepare</code> raises when Sw_itlgrpConstraint is 1 (CAPTRAN_ITL does not exist in the port)."
OPRES_NOGUARD = ("<b>Not ported and no guard.</b> This equation belongs to the operating-reserve family (Sw_OpRes). The port builds OPRES columns and the ops-group reserve "
                 "equations when Sw_OpRes is on but does not build this equation and does not raise, so a run with Sw_OpRes=1 would be missing it. "
                 "Both reference cases run with GSw_OpRes=2 but opres_h is empty there, so no reserve row exists.")
MINGEN = "Not ported. <code>prep.prepare</code> raises when Sw_Mingen is 1 (MINGEN does not exist in the port)."
PVB = "Not ported. derive.py raises when Sw_PVB is nonzero."


DERIVE_GUARDS = {
    FLEX: ("reeds/open/derive_temporal.py", "if int(sw[\"Sw_EFS_Flex\"]):", None),
    WATER: ("reeds/open/derive.py", "if int(sw[\"Sw_WaterMain\"]) == 1:", None),
    PVB: ("reeds/open/derive.py", "if int(sw[\"Sw_PVB\"]) != 0:", None),
}


def guarded(summary: str, math: str, note: str, prep=None, derive=None) -> dict:
    d = {"summary": summary, "math": math, "guard_only": True, "port_note": note}
    if prep:
        d["prep"] = prep
    if derive:
        d["derive"] = derive
    for key, anchor in DERIVE_GUARDS.items():
        if note.startswith(key):
            d.setdefault("derive", []).append(anchor)
    return d


SPEC: dict[str, dict] = {
    "eq_loadsite_inv": guarded("Flexibly sited load capacity accumulates its investment.",
        r"\V{CAP\_LOADSITE}_{r,t} = \sum_{tt\in\mathcal{T},\ tt\le t}\V{INV\_LOADSITE}_{r,tt}\qquad \mathrm{Sw\_LoadSiteCF},\ \mathrm{val\_loadsite}(r)", LOADSITE, [GUARD_LOOP]),
    "eq_loadsite_cap": guarded("Hourly sited load cannot exceed its capacity.",
        r"\V{CAP\_LOADSITE}_{r,t} \ge \V{OP\_LOADSITE}_{r,h,t}\qquad 0<\mathrm{Sw\_LoadSiteCF}<1", LOADSITE, [GUARD_LOOP]),
    "eq_loadsite_op": guarded("Sited load must run at least the target capacity factor.",
        r"\sum_h\V{OP\_LOADSITE}_{r,h,t}\P{hours}_h \ge \V{CAP\_LOADSITE}_{r,t}\sum_h\P{hours}_h\,\mathrm{Sw\_LoadSiteCF}\qquad 0<\mathrm{Sw\_LoadSiteCF}<1", LOADSITE, [GUARD_LOOP]),
    "eq_loadsite_siting": guarded("Sited load capacity in a siting region matches the annual target.",
        r"\sum_{r\in\mathrm{loadsitereg},\ \mathrm{val\_loadsite}(r)}\V{CAP\_LOADSITE}_{r,t} = \P{loadsite\_annual}_{\mathrm{loadsitereg},t}", LOADSITE, [GUARD_LOOP]),
    "eq_load_flex_day": guarded("Flexible load is conserved within each season.",
        r"\frac{\sum_{h\in szn}\V{FLEX}_{f,r,h,t}\P{hours}_h}{\P{numdays}_{szn}} = \frac{\sum_{h\in szn}\P{load\_exog\_flex}_{f,r,h,t}\P{hours}_h}{\P{numdays}_{szn}}\qquad \mathrm{Sw\_EFS\_flex}", FLEX),
    "eq_load_flex1": guarded("Flexible demand must be served within its shifting window.",
        r"\V{FLEX}_{f,r,h,t}\P{hours}_h + \sum_{hh:\ \mathrm{flex\_h\_corr1}(f,h,hh)}\V{FLEX}_{f,r,hh,t}\P{hours}_{hh} \ge \P{load\_exog\_flex}_{f,r,h,t}\P{hours}_h", FLEX),
    "eq_load_flex2": guarded("Flexible load cannot exceed the demand available for shifting.",
        r"\P{load\_exog\_flex}_{f,r,h,t}\P{hours}_h + \sum_{hh:\ \mathrm{flex\_h\_corr2}(f,h,hh)}\P{load\_exog\_flex}_{f,r,hh,t}\P{hours}_{hh} \ge \V{FLEX}_{f,r,h,t}\P{hours}_h", FLEX),
    "eq_mingen_lb": guarded("Seasonal minimum-generation level is at least the minimum loading in every hour of the season.",
        r"\V{MINGEN}_{r,szn,t} \ge \sum_{(i,v):\ \mathrm{valgen},\ \P{minloadfrac}_{r,i,h}\neq0}\V{GEN}_{i,v,r,h,t}\,\P{minloadfrac}_{r,i,h}\qquad h\in szn,\ \mathrm{Sw\_Mingen}", MINGEN, [GUARD_LOOP]),
    "eq_mingen_ub": guarded("Generation in every hour of the season is at least the seasonal minimum-generation level.",
        r"\sum_{(i,v):\ \mathrm{valgen},\ \P{minloadfrac}_{r,i,h}\neq0}\V{GEN}_{i,v,r,h,t} \ge \V{MINGEN}_{r,szn,t}\qquad h\in szn,\ \mathrm{Sw\_Mingen}", MINGEN, [GUARD_LOOP]),
    "eq_ORCap_large_res_frac": guarded("Reserves from a unit with a large reserve fraction are limited by its generation in the peak-load hour of the season.",
        r"\P{reserve\_frac}_{i,o}\sum_{(szn,hh):\ h\in szn,\ \mathrm{maxload\_szn}(r,hh,t,szn)}\V{GEN}_{i,v,r,hh,t} \ge \V{OPRES}_{o,i,v,r,h,t}\qquad \P{reserve\_frac}_{i,o}>0.5,\ i\notin\mathrm{storage\_standalone}\cup\mathrm{hyd\_add\_pump},\ \mathrm{Sw\_OpRes}",
        OPRES_NOGUARD),
    "eq_ORCap_small_res_frac": guarded("Reserves from a unit with a small reserve fraction are limited by its generation in the same hour.",
        r"\V{GEN}_{i,v,r,h,t} \ge \V{OPRES}_{o,i,v,r,h,t}\qquad 0<\P{reserve\_frac}_{i,o}\le0.5,\ \mathrm{Sw\_OpRes}", OPRES_NOGUARD),
    "eq_PRMTRADELimit": guarded("Firm-capacity trade on a line is limited by its PRM capacity.",
        r"\V{CAPTRAN\_PRM}_{r,rr,\tau,t}\sum_{h:\ \mathrm{h\_ccseason\_prm}(h,cc)}(1+\P{trans\_cap\_delta}_{h,t}) \ge \V{PRMTRADE}_{r,rr,\tau,cc,t}\qquad \mathrm{routes\_prm},\ \mathrm{Sw\_PRM\_CapCredit}", PRM, [GUARD_LOOP]),
    "eq_PRMTRADE_VSC": guarded("Firm capacity can pass through the VSC network but does not contribute directly.",
        r"\sum_{rr}(1-\P{tranloss}_{rr,r,\mathrm{VSC}})\V{PRMTRADE}_{rr,r,\mathrm{VSC},cc,t} - \sum_{rr}\V{PRMTRADE}_{r,rr,\mathrm{VSC},cc,t} + \V{CONVERSION\_PRM}_{\mathrm{AC}\to\mathrm{VSC}}\eta_{vsc} - \V{CONVERSION\_PRM}_{\mathrm{VSC}\to\mathrm{AC}}/\eta_{vsc} = 0\qquad \mathrm{Sw\_PRM\_CapCredit},\ \mathrm{Sw\_VSC}",
        PRM + " " + VSC, [GUARD_LOOP]),
    "eq_cap_sdbin_balance": guarded("Binned storage power capacity cannot exceed total storage capacity.",
        r"\P{bcr}_i\V{CAP}_{i,v,r,t} \ge \sum_{sdbin}\V{CAP\_SDBIN}_{i,v,r,cc,sdbin,t}\qquad i\in\mathrm{storage}\setminus\mathrm{csp},\ \mathrm{valcap},\ \mathrm{Sw\_PRM\_CapCredit}", PRM, [GUARD_LOOP]),
    "eq_cap_sdbin_energy_balance": guarded("Binned storage energy capacity cannot exceed battery energy capacity.",
        r"\V{CAP\_ENERGY}_{i,v,r,t} \ge \sum_{sdbin}\V{CAP\_SDBIN\_ENERGY}_{i,v,r,cc,sdbin,t}\qquad i\in\mathrm{battery},\ \mathrm{Sw\_PRM\_CapCredit}", PRM, [GUARD_LOOP]),
    "eq_sdbin_power_energy_link": guarded("Binned energy equals binned power times the bin duration.",
        r"\V{CAP\_SDBIN\_ENERGY}_{i,v,r,cc,sdbin,t} = \P{bin\_duration}_{sdbin}\V{CAP\_SDBIN}_{i,v,r,cc,sdbin,t}\qquad i\in\mathrm{battery},\ \mathrm{Sw\_PRM\_CapCredit}", PRM, [GUARD_LOOP]),
    "eq_sdbin_power_limit": guarded("Capacity-credit-weighted storage in each duration bin cannot exceed the bin size from the capacity-credit script.",
        r"\P{sdbin\_size}_{ccreg,cc,sdbin,t} \ge \sum_{(i,v,r):\ r\in ccreg,\ \mathrm{valcap},\ \mathrm{standalone}\cup\mathrm{hyd\_add\_pump}}\V{CAP\_SDBIN}\,\P{cc\_storage}_{i,sdbin} + \sum_{\mathrm{hybrid}\setminus\mathrm{csp}}\V{CAP\_SDBIN}\,\P{cc\_storage}\,\P{hybrid\_cc\_derate}\qquad \mathrm{Sw\_PRM\_CapCredit}",
        PRM, [GUARD_LOOP]),
    "eq_reserve_margin": guarded("Planning reserve margin with capacity credits (capacity-credit mode).",
        r"""
\sum_{\substack{\mathrm{valcap},\ i\notin\mathrm{vre}\cup\mathrm{hydro}\cup\mathrm{storage}\cup\mathrm{consume},\\ \neg\mathrm{forced\_retire}}}\V{CAP}(1+\P{ccseason\_cap\_frac\_delta})(1-\P{mean\_forced\_outage\_rate})
 + \sum_{\mathrm{vre}\cup\mathrm{csp}\cup\mathrm{pvb}}\P{cc\_old}_{i,r,cc,t}
 + \sum_{\mathrm{valinv}}\P{m\_cc\_mar}_{i,r,cc,t}(\V{INV}+\V{INV\_REFURB})
 + \sum_{sdbin}\P{cc\_storage}_{i,sdbin}\V{CAP\_SDBIN} + \sum_{\mathrm{hybrid}}\P{cc\_storage}\P{hybrid\_cc\_derate}\V{CAP\_SDBIN}
 + \sum\P{cc\_int}\V{CAP} + \sum\P{cc\_excess} \\
 + \sum_{\mathrm{hydro\_nd},\ h\in\mathrm{h\_ccseason\_prm}(cc)}\V{GEN}
 + \sum_{\mathrm{hydro\_d}\cup\mathrm{hyd\_add\_pump}}\V{CAP}\,\P{cap\_hyd\_ccseason\_adj}(1+\P{hydro\_capcredit\_delta})
 + \sum_{\mathrm{routes\_prm},\ \mathrm{notvsc}}(1-\P{tranloss})\V{PRMTRADE}_{rr\to r} - \sum\V{PRMTRADE}_{r\to rr}
 \pm \V{CONVERSION\_PRM}\sw{Sw\_VSC}
 \;\ge\; \Big(\P{peakdem\_static\_ccseason}_{r,cc,t} + \frac{\sum_{\mathrm{smr}}\V{PRODUCE}/\P{pcr}\cdot\P{hours}\P{frac\_h\_ccseason\_weights}}{\sum\P{hours}\P{frac\_h\_ccseason\_weights}}\sw{Sw\_Prod}\Big)(1+\P{prm}_{r,t})
""", PRM, [GUARD_LOOP]),
    "eq_transgrp_limit_prm": guarded("Firm-capacity trade across a transmission group is limited by the group capacity (capacity-credit mode).",
        r"\V{CAPTRAN\_GRP}_{g,gg,t}\sum_{h\in\mathrm{h\_ccseason\_prm}(cc)}(1+\P{trans\_cap\_delta}_{h,t}) \ge \sum_{\mathrm{routes\_transgroup}}\V{PRMTRADE}_{r,rr,\mathrm{AC},cc,t}", PRM, [GUARD_LOOP]),
    "eq_CAPTRAN_ITL": guarded("Flow capacity between ITL groups: initial plus cumulative AC investment.",
        r"\V{CAPTRAN\_ITL}_{g,gg,t} = \P{trancap\_init\_itlgrp}_{g,gg,\mathrm{AC}} + \sum_{(r,rr,tt):\ tt\in\mathcal{T},\ tt\le t,\ \mathrm{routes\_inv}(AC),\ \mathrm{routes\_itlgrp}}\V{INVTRAN}_{r,rr,\mathrm{AC},tt}\qquad \mathrm{Sw\_itlgrpConstraint}", ITL, [GUARD_LOOP]),
    "eq_itlgrp_limit_energy": guarded("AC flow across an ITL group interface is limited by the group capacity.",
        r"\V{CAPTRAN\_ITL}_{g,gg,t}(1+\P{trans\_cap\_delta}_{h,t}) \ge \sum_{\mathrm{routes\_itlgrp}}\V{FLOW}_{r,rr,h,t,\mathrm{AC}}", ITL, [GUARD_LOOP]),
    "eq_itlgrp_limit_prm": guarded("Firm-capacity trade across an ITL group interface (capacity-credit mode).",
        r"\V{CAPTRAN\_ITL}_{g,gg,t}\sum_{h\in\mathrm{h\_ccseason\_prm}(cc)}(1+\P{trans\_cap\_delta}_{h,t}) \ge \sum_{\mathrm{routes\_itlgrp}}\V{PRMTRADE}_{r,rr,\mathrm{AC},cc,t}", ITL + " " + PRM, [GUARD_LOOP]),
    "eq_firm_transfer_limit_cc": guarded("Net firm imports into a planning region are capped at a fraction of its peak demand (capacity-credit mode).",
        r"\P{firm\_import\_limit}_{tr,t}\sum_{r\in tr}\P{peakdem\_static\_ccseason}_{r,cc,t} \ge \sum(1-\P{tranloss})\V{PRMTRADE}_{rr\to r} - \sum\V{PRMTRADE}_{r\to rr}\qquad \mathrm{Sw\_PRM\_NetImportLimit},\ \mathrm{Sw\_PRM\_CapCredit}", PRM, [GUARD_LOOP]),
    "eq_CONVERSION_limit_prm": guarded("Firm-capacity conversion through VSC converters is limited by converter capacity.",
        r"\V{CAP\_CONVERTER}_{r,t} \ge \V{CONVERSION\_PRM}_{r,cc,\mathrm{AC}\to\mathrm{VSC},t}+\V{CONVERSION\_PRM}_{r,cc,\mathrm{VSC}\to\mathrm{AC},t}", VSC + " " + PRM, [("if int(case.scalar(\"Sw_VSC\")):", None)]),
    "eq_gasused": guarded("Gas burned in a census division is drawn from the gas supply bins.",
        r"\sum_{gb}\V{GASUSED}_{cd,gb,h,t} = \frac{\sum_{\mathrm{valgen},\ \mathrm{gas},\ r\in cd}\P{heat\_rate}(\V{GEN}+\V{CCSFLEX\_POW})}{\P{gas\_scale}} + \frac{\sum\P{dac\_gas\_cons\_rate}\V{PRODUCE}_{\mathrm{dac\_gas}}}{\P{gas\_scale}}\sw{Sw\_DAC\_Gas}\qquad \mathrm{Sw\_GasCurve}\in\{0,3\}", GAS03, [GUARD_LOOP]),
    "eq_gasbinlimit": guarded("Regional gas bin limit (Sw_GasCurve=0).",
        r"\P{gaslimit}_{cd,gb,t} \ge \sum_h\P{hours}_h\V{GASUSED}_{cd,gb,h,t}", GAS03, [GUARD_LOOP]),
    "eq_gasbinlimit_nat": guarded("National gas bin limit (Sw_GasCurve=3).",
        r"\P{gaslimit\_nat}_{gb,t} \ge \sum_{h,cd}\P{hours}_h\V{GASUSED}_{cd,gb,h,t}", GAS03, [GUARD_LOOP]),
    "eq_storage_interday_level": guarded("Interday storage: level at the start of the next partition.",
        r"\sum_{p':\ \mathrm{nextpartition}(p,p')}\V{SIL}_{i,v,r,p',t} = \V{SIL}_{i,v,r,p,t} + \P{numpartitions}_p\sum_{szn\in p}\sum_{h\in szn}\V{SID}_{i,v,r,h,t}\P{hd}_h", INTERDAY, [GUARD_LOOP]),
    "eq_storage_interday_level_max_day": guarded("Interday storage: maximum relative state of charge within a representative period.",
        r"\V{SIL\_MAX\_DAY}_{i,v,r,szn,t} \ge \sum_{hh:\ \mathrm{h\_preh}(h,hh)}\V{SID}_{i,v,r,hh,t}\P{hd}_h", INTERDAY, [GUARD_LOOP]),
    "eq_storage_interday_level_min_day": guarded("Interday storage: minimum relative state of charge within a representative period.",
        r"\sum_{hh:\ \mathrm{h\_preh}(h,hh)}\V{SID}_{i,v,r,hh,t}\P{hd}_h \ge \V{SIL\_MIN\_DAY}_{i,v,r,szn,t}", INTERDAY, [GUARD_LOOP]),
    "eq_storage_interday_min_level_start": guarded("Interday storage: state of charge stays nonnegative at the start of a partition.",
        r"\V{SIL}_{i,v,r,p,t} + \sum_{szn\in p}\V{SIL\_MIN\_DAY}_{i,v,r,szn,t} \ge 0", INTERDAY, [GUARD_LOOP]),
    "eq_storage_interday_min_level_end": guarded("Interday storage: state of charge stays nonnegative at the end of a partition.",
        r"\V{SIL}_{i,v,r,p,t} + (\P{numpartitions}_p-1)\sum_{szn\in p}\sum_{h\in szn}\V{SID}\P{hd}_h + \sum_{szn\in p}\V{SIL\_MIN\_DAY} \ge 0", INTERDAY, [GUARD_LOOP]),
    "eq_storage_interday_max_level_start": guarded("Interday storage: state of charge within energy capacity at the start of a partition.",
        r"\P{storage\_duration\_m}\V{CAP}[i\notin\mathrm{battery}] + \V{CAP\_ENERGY}[i\in\mathrm{battery}] \ge \V{SIL}_{i,v,r,p,t} + \sum_{szn\in p}\V{SIL\_MAX\_DAY}", INTERDAY, [GUARD_LOOP]),
    "eq_storage_interday_max_level_end": guarded("Interday storage: state of charge within energy capacity at the end of a partition.",
        r"\P{storage\_duration\_m}\V{CAP}[i\notin\mathrm{battery}] + \V{CAP\_ENERGY}[i\in\mathrm{battery}] \ge \V{SIL}_{i,v,r,p,t} + (\P{numpartitions}_p-1)\sum_{szn\in p}\sum_{h\in szn}\V{SID}\P{hd}_h + \sum_{szn\in p}\V{SIL\_MAX\_DAY}", INTERDAY, [GUARD_LOOP]),
    "eq_plant_total_gen": guarded("Hybrid plant: total generation is plant plus battery output minus charging from the plant.",
        r"\V{GEN\_PLANT}+\V{GEN\_STORAGE}-\V{STORAGE\_IN\_PLANT}[h\in\mathrm{dayhours}] = \V{GEN}_{i,v,r,h,t}\qquad i\in\mathrm{storage\_hybrid}\setminus\mathrm{csp},\ \mathrm{Sw\_HybridPlant}", HYBRID,
        [("if int(case.scalar(\"Sw_HybridPlant\")) and _in(valgen", None)]),
    "eq_hybrid_plant_energy_limit": guarded("Hybrid plant: PV output to the battery and inverter is bounded by the PV resource.",
        r"\sum_c\P{m\_cf}_{i,c,v,r,h,t}\V{CAP}_{i,v,r,t} \ge \V{STORAGE\_IN\_PLANT}[h\in\mathrm{dayhours}] + \V{GEN\_PLANT}", HYBRID, [("if int(case.scalar(\"Sw_HybridPlant\")) and _in(valgen", None)]),
    "eq_plant_capacity_limit": guarded("Hybrid plant: inverter capacity bounds everything that passes through it.",
        r"\frac{\V{CAP}_{i,v,r,t}}{\P{ilr}_i} \ge \V{GEN\_PLANT}+\V{GEN\_STORAGE}+\V{STORAGE\_IN\_GRID}+\sum_o\V{OPRES}\sw{Sw\_OpRes}", HYBRID, [("if int(case.scalar(\"Sw_HybridPlant\")) and _in(valgen", None)]),
    "eq_pvb_itc_charge_reqt": guarded("PV-battery ITC qualification: a minimum share of charging must come from the PV.",
        r"\sum_{h\in\mathrm{dayhours}\cap h_{rep}}\V{STORAGE\_IN\_PLANT}\P{hours}_h \ge \P{pvb\_itc\_qual\_frac}\Big(\sum_{h\in\mathrm{dayhours}\cap h_{rep}}\V{STORAGE\_IN\_PLANT}\P{hours}_h+\sum_{h\in h_{rep}}\V{STORAGE\_IN\_GRID}\P{hours}_h\Big)\qquad i\in\mathrm{pvb},\ \mathrm{Sw\_PVB}", PVB),
    "eq_water_accounting": guarded("Water withdrawn or consumed by generation.",
        r"\V{WAT}_{i,v,w,r,h,t} = \V{GEN}_{i,v,r,h,t}\P{hours}_h\P{water\_rate}_{i,w}/10^6\qquad \mathrm{i\_water}(i),\ \mathrm{valgen},\ h\in h_{rep},\ \mathrm{Sw\_WaterMain}", WATER),
    "eq_water_capacity_total": guarded("Water access capacity required by generation capacity (and PSH reservoir filling).",
        r"\V{WATCAP}_{i,v,r,t} = \frac{\sum_{h\in h_{rep}}\P{hours}_h\sum_w\V{CAP}\P{water\_rate}_{i,w}(1+\textstyle\sum\P{h\_szn}\P{seas\_cap\_frac\_delta})}{10^6} + \sum_{rscbin}\V{INV\_RSC}\,\P{water\_req\_psh}_{r,rscbin}\sw{Sw\_PSHwatercon}", WATER),
    "eq_water_capacity_limit": guarded("Water access cannot exceed supply by source type and zone (with a penalized slack).",
        r"\P{m\_watsc\_dat}_{wst,\mathrm{cap},r,t} + \V{WATER\_CAPACITY\_LIMIT\_SLACK}_{wst,r,t} \ge \sum_{(i,v):\ \mathrm{i\_wst}(i,wst),\ \mathrm{valcap}}\V{WATCAP}_{i,v,r,t}", WATER),
    "eq_water_use_limit": guarded("Seasonal water use cannot exceed seasonally available access.",
        r"\V{WATCAP}_{i,v,r,t}\sum_{wst:\ \mathrm{i\_wst}}\P{watsa}_{wst,r,szn,t} \ge \sum_{h\in szn}\V{WAT}_{i,v,w,r,h,t}", WATER),
    "eq_co2_capture": guarded("CO2 captured by CCS, SMR-CCS and DAC.",
        r"\V{CO2\_CAPTURED}_{r,h,t} = \sum_{\mathrm{valgen}}\P{capture\_rate}_{CO2}\V{GEN} + \sum\P{smr\_capture\_rate}\P{smr\_co2\_intensity}\V{PRODUCE}_{\mathrm{smr\_ccs}}\sw{Sw\_H2} + \sum_{\mathrm{dac}}\V{PRODUCE}_{DAC}\sw{Sw\_DAC}\qquad \mathrm{Sw\_CO2\_Detail}", CO2, [GUARD_LOOP]),
    "eq_co2_transport_caplimit": guarded("Bidirectional CO2 pipeline flow is limited by cumulative pipeline investment.",
        r"\sum_{tt\in\mathcal{T}:\ \P{co2\_detail\_startyr}\le tt\le t}(\V{CO2\_TRANSPORT\_INV}_{r,rr,tt}+\V{CO2\_TRANSPORT\_INV}_{rr,r,tt}) \ge \V{CO2\_FLOW}_{rr,r,h,t}+\V{CO2\_FLOW}_{r,rr,h,t}", CO2, [GUARD_LOOP]),
    "eq_co2_spurline_caplimit": guarded("CO2 injected at a storage site is limited by the spur-line investment to it.",
        r"\sum_{tt\in\mathcal{T}:\ \P{co2\_detail\_startyr}\le tt\le t}\V{CO2\_SPURLINE\_INV}_{r,cs,tt} \ge \V{CO2\_STORED}_{r,cs,h,t}", CO2, [GUARD_LOOP]),
    "eq_co2_sink": guarded("Regional CO2 balance: stored CO2 equals captured CO2 plus net imports.",
        r"\sum_{cs:\ \mathrm{r\_cs}(r,cs)}\V{CO2\_STORED}_{r,cs,h,t} = \V{CO2\_CAPTURED}_{r,h,t} + \sum_{rr:\ \mathrm{co2\_routes}(r,rr)}(\V{CO2\_FLOW}_{rr,r,h,t}-\V{CO2\_FLOW}_{r,rr,h,t})", CO2, [GUARD_LOOP]),
    "eq_co2_injection_limit": guarded("Hourly injection limit per storage site.",
        r"\P{co2\_injection\_limit}_{cs} \ge \sum_{r:\ \mathrm{r\_cs}(r,cs)}\V{CO2\_STORED}_{r,cs,h,t}", CO2, [GUARD_LOOP]),
    "eq_co2_cumul_limit": guarded("Cumulative storage limit per site over all solved years.",
        r"\P{co2\_storage\_limit}_{cs} \ge \sum_{(r,h,tt):\ tt\in\mathcal{T},\ \P{co2\_detail\_startyr}\le tt\le t,\ \mathrm{r\_cs},\ h\in h_{rep}}\P{yearweight}_{tt}\P{hours}_h\V{CO2\_STORED}_{r,cs,h,tt}", CO2, [GUARD_LOOP]),
    "eq_ccsflex_byp_ccsenergy_limit": guarded("Flexible CCS (bypass): CCS power is limited to a share of plant output.",
        r"\V{CCSFLEX\_POW}_{i,v,r,h,t} \le \P{ccsflex\_powlim}_{i,t}(\V{GEN}+\V{CCSFLEX\_POW})\qquad \mathrm{ccsflex\_byp}(i),\ \mathrm{Sw\_CCSFLEX\_BYP}", CCS, [GUARD_LOOP]),
    "eq_ccsflex_sto_ccsenergy_limit_szn": guarded("Flexible CCS (storage): seasonal CCS energy is limited to a share of plant output.",
        r"\sum_{h\in szn}\P{hours}_h\V{CCSFLEX\_POW} \le \P{ccsflex\_powlim}_{i,t}\sum_{h\in szn}\P{hours}_h(\V{GEN}+\V{CCSFLEX\_POW})\qquad \mathrm{szn\_rep}(szn),\ \mathrm{Sw\_CCSFLEX\_STO}", CCS, [GUARD_LOOP]),
    "eq_ccsflex_sto_ccsenergy_balance": guarded("Flexible CCS (storage, no level tracking): seasonal CCS energy requirement is met within the season.",
        r"\sum_{h\in szn}\P{hours}_h\V{CCSFLEX\_POWREQ} = \sum_{h\in szn}\P{hours}_h\V{CCSFLEX\_POW}\qquad \mathrm{Sw\_CCSFLEX\_STO},\ \mathrm{Sw\_CCSFLEX\_STO\_LEVEL}=0", CCS, [GUARD_LOOP]),
    "eq_ccsflex_sto_storage_level": guarded("Flexible CCS (storage with level tracking): solvent storage balance.",
        r"\sum_{hh:\ \mathrm{nexth}(h,hh)}\V{CCSFLEX\_STO\_STORAGE\_LEVEL}_{hh} = \V{CCSFLEX\_STO\_STORAGE\_LEVEL}_{h} + \P{ccsflex\_sto\_storage\_eff}_{i,t}\P{hd}_h\V{CCSFLEX\_POWREQ} - \P{hd}_h\V{CCSFLEX\_POW}\qquad \mathrm{Sw\_CCSFLEX\_STO\_LEVEL}=1", CCS, [GUARD_LOOP]),
    "eq_ccsflex_sto_storage_level_max": guarded("Flexible CCS: solvent storage level within capacity.",
        r"\P{ccsflex\_sto\_storage\_duration}_i\V{CCSFLEX\_STO\_STORAGE\_CAP}_{i,v,r,t} \ge \V{CCSFLEX\_STO\_STORAGE\_LEVEL}_{i,v,r,h,t}", CCS, [GUARD_LOOP]),
}
