# Existing Wind and UPV reV Match

`build_existing_rev_lcoe_cf.py` creates an enriched plant CSV, a processed EIA
state/national market-data CSV, two twelve-chart LCOE comparison suites, and
fit statistics.

Run it from the Anaconda `base` environment:

```powershell
python build_existing_rev_lcoe_cf.py `
  --eia-state-generation annual_generation_state.xls
```

The default supply-curve paths use UNC paths under `\\nrelnas01\ReEDS`; the
script does not map `Z:` and does not write to the network share. Outputs are
local unless an output argument is explicitly set to a network path.

The script:

- reads the EIA generator database from the ReEDS GitHub `main` branch,
- keeps `wind-ons` and `upv` generators through the latest EIA market-data
  year (2024 in the current source), excluding later NEMS/project records,
- assigns each plant to the nearest positive-capacity reV site,
- retains matched reV site LCOE, transmission cost (`lcot`), and all-in LCOE,
- reads EIA's annual state generation workbook for 1990-2024,
- queries EIA State Electricity Profiles for retail sales and direct use,
- defines total load as retail sales plus direct use,
- defines non-storage generation as EIA total generation less pumped-storage
  generation,
- calculates wind or solar generation shares of non-storage generation,
- retains pre-1990 plants in the CSV and year charts without assigning them a
  clipped market year,
- omits rows outside 1990-2024 from market-share and generation charts and
  fits,
- writes state-panel and national LCOE charts against year, market share, and
  wind/solar generation,
- displays generation axes in TWh,
- groups capacity-weighted averages by exact EIA market year for market-share
  and generation charts and by actual `StartYear` for year charts,
- fits ordinary least-squares lines to the annual capacity-weighted averages,
- writes each fit equation, R-squared value, and slope units on its chart,
- calculates annual reV point generation as capacity times capacity factor
  times 8,760 hours,
- creates a primary chart suite using `lcoe_site_usd_per_mwh` and a comparison
  suite using `lcoe_all_in_usd_per_mwh`,
- overlays national and state reV supply curves sorted by the same LCOE metric
  as each chart suite and accumulated by annual TWh on generation charts,
- fits the visible portion of each underlying reV supply curve over the same
  TWh range as the existing-generation chart.

A state-panel reV fit is labeled unavailable when fewer than two raw reV
supply-curve points fall within that state's displayed historical-generation
range.

EIA combines solar thermal and photovoltaic generation in this historical
workbook. That combined utility-scale solar series is used as the `upv`
generation proxy.

## Outputs

- `existing_wind_upv_rev_lcoe_cf.csv`
- `eia_state_generation_load_1990_2024.csv`
- `charts/site_lcoe/` with twelve PNG charts and
  `linear_fit_statistics.csv`
- `charts/all_in_lcoe/` with twelve comparison PNG charts and
  `linear_fit_statistics.csv`

Use `--eia`, `--wind-sc`, `--upv-sc`, `--eia-state-generation`,
`--eia-api-key`, `--out`, `--market-data-out`, or `--charts-dir` to override
inputs or outputs. Set the `EIA_API_KEY` environment variable to use a personal
EIA key; otherwise the script uses EIA's `DEMO_KEY`.
