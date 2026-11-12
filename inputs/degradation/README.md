## Degradation Input Files

- `degradation_annual_default.csv`: Annual capacity degradation rate [fraction/year] by technology
  - Applied in the model as `(1 - rate)^years` to derate capacity as plants age
  - The file is selected by the `degrade_suffix` switch
