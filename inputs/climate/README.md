## Climate Input Files

- `climate_heuristics_finalyear.csv`: Climate heuristic adjustment [fraction] applied in the final year, by climate parameter
  - Covers hydropower capacity credit, thermal summer capacity, and transmission summer capacity deltas
  - Scenario is selected by the `GSw_ClimateHeuristics` switch

- `climate_heuristics_yearfrac.csv`: Annual scaling factor [fraction] applied to the final-year climate heuristic adjustment
  - Phases the adjustments in `climate_heuristics_finalyear.csv` in over time, reaching their full value in the final year
  - Scenario is selected by the `GSw_ClimateHeuristics` switch
