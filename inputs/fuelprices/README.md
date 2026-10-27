## Fuel Prices Input Files

- `alpha_AEO_{YYYY}_*.csv`: census division alpha values, used in the calculation of natural gas demand curves ($2004 dollar year)
  - `alpha_AEO_{YYYY}_HOG.csv`: High Oil and Gas Resource and Technology scenario
  - `alpha_AEO_{YYYY}_LOG.csv`: Low Oil and Gas Resource and Technology scenario 
  - `alpha_AEO_{YYYY}_reference.csv`: Reference scenario

- `cd_beta0.csv`: Reference census division beta levels electric sector ($2004 dollar year)

- `cd_beta0_allsector.csv`: Reference census division beta levels all sectors ($2004 dollar year)

- `coal_AEO_2025_reference.csv`: [AEO2025](https://www.eia.gov/outlooks/aeo/pdf/2025/AEO2025-narrative.pdf) Reference case census division fuel price [$/MMBtu] of coal with missing values forward-filled from earlier years and missing New England values set to Mid Atlantic

- `coal_AEO_2026_altelec.csv`: [AEO2026](https://www.eia.gov/outlooks/aeo/) Alternative Electricity case census division fuel price [$/MMBtu] of coal with missing New England values set to Mid Atlantic

- `coal_AEO_2026_baseline.csv`: [AEO2026](https://www.eia.gov/outlooks/aeo/) Counterfactual Baseline case census division fuel price [$/MMBtu] of coal with missing values forward-filled from earlier years and missing New England values set to Mid Atlantic

- `dollaryear.csv`: Dollar year mapping for each fuel price scenario

- `h2-combustion_*.csv`: price of hydrogen for combustion technologies (h2-ct and cc) at $X/MMBtu for all years
  - `h2-combustion_10.csv`: $10/MMBtu
  - `h2-combustion_30.csv`: $30/MMBtu
  - `h2-combustion_reference.csv`: $20/MMBtu

- `ng_AEO_{YYYY}_*.csv`: census division fuel price [$/MMBtu] of natural gas ($2004 dollar year)
  - `ng_AEO_{YYYY}_HOG.csv`: High Oil and Gas Resource and Technology scenario 
  - `ng_AEO_{YYYY}_LOG.csv`: Low Oil and Gas Resource and Technology scenario
  - `ng_AEO_{YYYY}_reference.csv`: Reference scenario 
  - `ng_AEO_{YYYY}_baseline.csv`: 

- `ng_demand_AEO_{YYYY}_*.csv`: census division natural gas demand [Quads] for the **electric sector**, used in the calculation of natural gas demand curves ($2004 dollar year)
  - `ng_demand_AEO_{YYYY}_HOG.csv`: High Oil and Gas Resource and Technology census division natural gas demand
  - `ng_demand_AEO_{YYYY}_LOG.csv`: Low Oil and Gas Resource and Technology census division natural gas demand
  - `ng_demand_AEO_{YYYY}_reference.csv`: Reference census division natural gas demand 
  - `ng_demand_AEO_{YYYY}_baseline.csv`: 

- `ng_tot_demand_AEO_{YYYY}_*.csv`: census division natural gas demand [Quads] across **all sectors**, used in the calculation of natural gas demand curves ($2004 dollar year)
  - `ng_tot_demand_AEO_{YYYY}_HOG.csv`: High Oil and Gas Resource and Technology census division natural gas demand
  - `ng_tot_demand_AEO_{YYYY}_LOG.csv`: Low Oil and Gas Resource and Technology census division natural gas demand 
  - `ng_tot_demand_AEO_{YYYY}_reference.csv`: Reference census division natural gas demand 
  - `ng_tot_demand_AEO_{YYYY}_baseline.csv`: 

- `uranium_AEO_2025_*.csv`: 
  - `uranium_AEO_2025_reference.csv`: 
  - `uranium_AEO_2026_baseline.csv`: 
