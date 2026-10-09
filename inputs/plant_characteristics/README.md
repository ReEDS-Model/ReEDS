# Files
### startcost.csv
Most startup costs are taken from Lew et al 2013 - Western Wind and Solar Integration Study Phase 2 [(NREL/TP-5500-55588)](https://www.nlr.gov/docs/fy13osti/55588.pdf). The original data, reported in $2011/MW in Table 7, are:
* Coal: 124
* Gas-CC: 81
* Gas-CT: 67
* Steam: 86
* Nuclear: 155
RPM uses 466 $2011/MW for nuclear, but we don't have a citable source for that number.
CCS startup costs are assumed to be the startup cost for the non-CCS version multiplied by the ratio of 2035 VOM costs between gas-cc-ccs and gas-cc in ATB 2023.

* `tech_cost_adjustments_*.csv`: Selected by `GSw_TechCostAdjust`; applied to overnight capital costs in `plantcostprep.py`
  - `tech_group` is a column name in `inputs/tech-subset-table.csv`, so the adjustment applies to every technology in that group
  - `cost_delta_frac` is a fractional change, e.g. 0.28 scales the overnight capital cost by 1.28
  - Technologies and years absent from the file are not adjusted
  - `tech_cost_adjustments_ATB_2025.csv`: Near-term gas and solar capital cost premiums relative to the ATB 2025 projections from Wesley's ATB_Near_Term_Adjustment.docx file, version August 27, 2026.