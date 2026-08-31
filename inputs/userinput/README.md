## User Input Files

- `futurefiles.csv`: Registry describing how each file copied into `inputs_case/` is projected forward in time by `reeds/input_processing/forecast.py`
  - Columns give the file format (`filetype`, `wide`, `header`), the index columns to hold fixed (`key`, `year_col`, `fix_cols`), the extrapolation method (`forecast_fit`), and optional bounds (`clip_min`, `clip_max`)
  - Every new file written into `inputs_case/` needs an entry here; `forecast.py` prints a warning for files it does not find

- `ivt_default.csv`: Default vintage bin assignment: the vintage number each technology belongs to in each year
  - Selected by the `ivt_suffix` switch; the model converts these bin numbers into the `ivt(i,v,t)` mapping set

- `ivt_small.csv`: Reduced vintage bin assignment used for smaller and faster test runs, with fewer distinct vintages than `ivt_default.csv`
  - Selected with `ivt_suffix = small`

- `ivt_step.csv`: ivt steps for endyears beyond 2050

- `mcs_distribution_rules.yaml`: Validation rules for the distribution specifications used in Monte Carlo Sampling (MCS)
  - Each top-level key is a valid distribution name; the rules are checked against the user's `mcs_distributions_*.yaml` file by `reeds/input_processing/mcs_sampler.py`

- `mcs_distributions_default.yaml`: Default set of parameter distributions sampled for Monte Carlo Sampling (MCS) analysis
  - The file is selected by the `MCS_dist` switch and is only used when `MCS_runs` is nonzero

- `windows_2100.csv`: Start and stop years of each overlapping solve window used by the window solve method to 2100

- `windows_default.csv`: Start and stop years of each overlapping solve window used by the window solve method

- `windows_step10.csv`: Start and stop years of each overlapping solve window used by the window solve method for `beyond2050step10`

- `windows_step5.csv`: Start and stop years of each overlapping solve window used by the window solve method for `beyond2050step5`
