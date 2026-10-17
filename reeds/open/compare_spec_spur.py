from __future__ import annotations

SPEC: dict[str, dict] = {
    "eq_site_cf": {
        "summary": "Available generation at a reV site is bounded by the capacity factor of the spur-line resources sited there.",
        "math": r"""
\sum_{(i,v,r):\ i\in\mathrm{spur\_techs},\ \mathrm{x\_r}(x,r),\ (i,v)\in\mathrm{valgen}_{r,t}}
 \sum_c \P{m\_cf}_{i,c,v,r,h,t}
 \sum_{rscbin:\ \mathrm{valcap},\ \mathrm{m\_rscfeas}(r,i,rscbin),\ \mathrm{spurline\_sitemap}(i,r,rscbin,x)} \V{CAP\_RSC}_{i,v,r,rscbin,t}
 \;\ge\; \V{AVAIL\_SITE}_{x,h,t}\qquad \mathrm{Sw\_SpurScen},\ x\in\mathrm{xfeas}
""",
        "terms": [
            ("sum m_cf * CAP_RSC over sited resources", r"\sum\P{m\_cf}\,\V{CAP\_RSC}",
             "sitecf_rsc: spur_cf (m_cf summed over c, spur techs only) on valgen rows, joined to spurline_sitemap, m_rscfeas, x_r and xfeas; "
             "keyed (x,h,t,i,v,r,rscbin), × CAP_RSC summed by (x,h,t)", "ported"),
            ("AVAIL_SITE(x,h,t)", r"\V{AVAIL\_SITE}", "sitecf_avail (−1) on every (xfeas, h, t) row", "ported"),
        ],
        "prep": [('P.coef["sitecf_rsc"]', 'P.coef["sitecf_avail"]')],
        "build": ['"eq_site_cf"'],
        "derive": [("reeds/open/derive_temporal.py", 'S["spur_cf"]', None), ("reeds/open/derive.py", 'spur = members(S.onswind) | members(S.upv)', 'S["spurline_cost"]')],
        "where": [r"spur_techs = onswind ∪ upv, plus geo_hydro when geohydrosupplycurve is reV and geo_egs_allkm when egssupplycurve is reV (b_inputs.gms).",
                  r"xfeas: sites with an x_r row (b_inputs.gms: xfeas(x)$sum{r$x_r(x,r), 1})."],
        "notes": ["Rows exist for every feasible site and hour because AVAIL_SITE always appears, so none are dropped by CONVERT.",
                  "Validated on port_vsc (AZ.NM, Sw_SpurScen=1) for 2025 and 2030."],
    },
    "eq_spurclip": {
        "summary": "Spur-line capacity clips the available generation at a site.",
        "math": r"\V{CAP\_SPUR}_{x,t} \ge \V{AVAIL\_SITE}_{x,h,t}\qquad \mathrm{Sw\_SpurScen},\ x\in\mathrm{xfeas}",
        "terms": [
            ("CAP_SPUR(x,t)", r"\V{CAP\_SPUR}_{x,t}", "spurclip_cap (+1) on every (x,h,t) row; the (x,t) variable is broadcast over h by the join", "ported"),
            ("AVAIL_SITE(x,h,t)", r"\V{AVAIL\_SITE}_{x,h,t}", "spurclip_avail (−1)", "ported"),
        ],
        "prep": [('P.con["eq_spurclip"]', 'P.coef["spurclip_avail"]')],
        "build": ['"eq_spurclip"'],
    },
    "eq_spur_noclip": {
        "summary": "Without spur-line sharing, spur-line capacity must cover the installed AC capacity at the site.",
        "math": r"\V{CAP\_SPUR}_{x,t} \ge \sum_{(i,v,r,rscbin):\ \mathrm{spurline\_sitemap}(i,r,rscbin,x),\ \mathrm{valcap}}\frac{\V{CAP\_RSC}_{i,v,r,rscbin,t}}{\P{ilr}_i}\qquad \mathrm{Sw\_SpurScen},\ \neg\mathrm{Sw\_SpurShare},\ x\in\mathrm{xfeas}",
        "terms": [
            ("CAP_SPUR(x,t)", r"\V{CAP\_SPUR}_{x,t}", "noclip_cap (+1)", "ported"),
            ("sum CAP_RSC / ilr", r"\sum\V{CAP\_RSC}/\P{ilr}", "noclip_rsc: −1/ilr(i) on spurline_sitemap joined to valcap, keyed (x,t,i,v,r,rscbin), × CAP_RSC summed by (x,t); raises if ilr is missing", "ported"),
        ],
        "prep": [('if not int(case.scalar("Sw_SpurShare")):', 'P.coef["noclip_rsc"]')],
        "build": ['"eq_spur_noclip"'],
        "notes": ["Sw_SpurShare=1 drops the equation; both port_vsc years run with Sw_SpurShare=0."],
    },
    "eq_capacity_limit_hybrid": {
        "summary": "Generation and reserves of spur-line technologies in a zone are bounded by the available site generation.",
        "math": r"\sum_{x:\ \mathrm{x\_r}(x,r),\ x\in\mathrm{xfeas}}\V{AVAIL\_SITE}_{x,h,t} \ge \sum_{(i,v):\ i\in\mathrm{spur\_techs},\ \mathrm{valgen}}\Big(\V{GEN}_{i,v,r,h,t}+\sum_{o:\ \mathrm{opres\_model},\ \P{reserve\_frac}_{i,o}\neq0,\ h\in\mathrm{opres\_h}}\V{OPRES}_{o,i,v,r,h,t}\sw{Sw\_OpRes}\Big)\qquad \mathrm{Sw\_SpurScen}",
        "terms": [
            ("sum AVAIL_SITE over sites in r", r"\sum_x\V{AVAIL\_SITE}", "hyb_avail: +1 on (r,x,t) for xfeas sites in x_r, × AVAIL_SITE summed by (r,h,t)", "ported"),
            ("sum GEN of spur techs", r"\sum\V{GEN}", "hyb_gen (−1) on GEN rows of spur techs, summed by (r,h,t)", "ported"),
            ("sum OPRES of spur techs $Sw_OpRes", r"\sum_o\V{OPRES}", "hyb_opres (−1) on OPRES rows of spur techs (the OPRES domain already carries opres_model, reserve_frac and opres_h), summed by (r,h,t)",
             "ported; no OPRES columns in port_vsc (Sw_OpRes=0)"),
        ],
        "prep": [('hyb_avail = (x_r.join(xfeas', 'P.coef["hyb_opres"]')],
        "build": ['"eq_capacity_limit_hybrid"'],
        "notes": ["GAMS writes the row for every (r,h,t); CONVERT drops rows without variables, so the port's row set is the union of the term rows."],
    },
    "eq_CAP_SPUR": {
        "summary": "Spur-line capacity accumulates spur-line investment.",
        "math": r"\V{CAP\_SPUR}_{x,t} = \sum_{tt\in\mathcal{T},\ tt\le t}\V{INV\_SPUR}_{x,tt}\qquad \mathrm{Sw\_SpurScen}",
        "terms": [
            ("CAP_SPUR(x,t)", r"\V{CAP\_SPUR}_{x,t}", "capspur_cap (+1); columns exist for every x, not only xfeas, as in GAMS", "ported"),
            ("INV_SPUR(x,t)", r"\V{INV\_SPUR}_{x,t}", "capspur_inv (−1) keyed (x,tt,t), × INV_SPUR renamed t→tt, summed by (x,t)", "ported"),
            ("INV_SPUR(x,tt), tt in tfix, x in xfeas", r"\sum_{tt<t}\overline{\V{INV\_SPUR}}", "capspur_const = −state_INV_SPUR summed over tt ≤ t (5_varfix fixes INV_SPUR only for xfeas)", "ported (constant)"),
            ("INV_SPUR(x,tt), tt in tfix, x not in xfeas", r"\sum_{tt<t}\V{INV\_SPUR}_{x,tt}", "free past-year columns spur_unfixed_past: 5_varfix.gms never fixes them, so they stay variables with no cost", "ported (GAMS quirk replicated)"),
        ],
        "prep": [('P.con["eq_CAP_SPUR"]', 'P.coef["capspur_const"]')],
        "build": ['"eq_CAP_SPUR"'],
        "notes": ["Same pattern as the LCC columns of eq_POI_cap and the converter columns of eq_CAP_CONVERTER: the GAMS sum runs over every past year while varfix pins only part of it."],
    },
}
