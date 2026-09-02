# Analysis tools and helper scripts

The ReEDS model includes several tools for setting up new cases, managing active cases, and analyzing case results.
Most of these scripts have command-line interfaces, the details of which can be printed by running `python path/to/scriptname.py -h`.

## Setting up new cases

### Create a new cases_{}.csv file: `preprocessing/casemaker.py`

This script facilitates the creation of a multidimensional matrix of scenarios, with "dimensions" and "casegroups" (permutations of dimensions) provided via a .yaml file.

An example .yaml file is provided in `preprocessing/casematrix_example.yaml`.
In this example, three dimensions are explored: "policy", "demand", and "sensitivity".
Each dimension specifies a dictionary of choices, and each choice specifies the switch values associated with that choice.
Default switch values are taken from `cases.csv`; if a "shared" field is provided in the casematrix .yaml file, the switch/value pairs in the "shared" field overwrite the associated defaults from `cases.csv`.
Cases in the resulting `cases_{batchname}.csv` file are labeled as `{policy choice}_{demand choice}_{sensitivity choice}`.
For example, a case using the "IRA" policy setting, "DemMd" demand setting, and "core" sensitivity setting would be labeled as `IRA_DemMd_core`.

The "casegroups" indicate which permutations of dimension values to include in the resulting `cases_{batchname}.csv` file.
The provided example includes 3 policy scenarios, 7 demand scenarios, and 9 sensitivity cases, which would produce 3 × 7 × 9 = 189 cases if all permutations were included.
`casegroups` is a list of *n*-element lists, where *n* is the number of dimensions specified above.
If an element is an empty list, all options for that dimension are used;
if an element specifies a single option or a list of options, only those options are used.
The order of elements matches the order of dimensions.
For example, since the dimensions are "policy", "demand", and "sensitivity":

- `[[], [], core]` includes all policy scenarios, all demand scenarios, and the single "core" sensitivity, for 3 × 7 × 1 = 21 cases.
- `[OBBBA, DemMd, []]` includes a single policy scenario, a single demand scenario, and all sensitivity cases, for 1 × 1 × 9 = 9 cases.
- `[[OBBBA, OBBBAcon], DemMd, [GasPriceLo, GasPriceHi]]` includes two policy scenarios, a single demand scenario, and two sensitivity cases, for 2 × 1 × 2 = 4 cases.
- `[[], [], []]` would include all 3 × 7 × 9 = 189 cases.


### Fix representative/stress periods: `preprocessing/get_case_periods.py`

This script takes as its required argument a filepath to a completed ReEDS case.

- If the optional `-r/--rep` flag is added (as in `python preprocessing/get_case_periods.py path/to/casename -r`), the representative periods for the provided run are written to `inputs/temporal/period_szn_user_{name}.csv`, where `name` is either provided by the `-n/--name` argument or (if no name is provided) given by the case name.
  - In a subsequent case, these representative periods can be used by setting `GSw_HourlyClusterAlgorithm` to `user_{name}`.
- If the optional `-s/--stress` flag is added, the stress periods for the provided run are written to `inputs/temporal/stressperiods_user_{name}.csv`.
  - In a subsequent case, these stress periods can be used by setting `GSw_PRM_StressModel` to `user_{name}`.

## Managing currently-running cases

### Print details for active HPC runs: `runstatus.py`

This script prints details about cases that are currently running on the HPC.

- If run without arguments (`python runstatus.py`), it uses `squeue` to get a list of the active runs under your username.
- If run with an argument (e.g. `python runstatus.py v20250310`), it only prints details for runs whose name begins with the provided argument.
- Adding the `-f` flag will print the names of the finished runs: `python runstatus.py v20231112 -f`
- If you increase the verbosity by adding `-v` flags, it prints a number of lines from the end of that run's gamslog.txt equal to the number of v's in the flag: `python runstatus.py v20231112 -vvvvv`

### Manage HPC runs: `restart_runs.py`

This script restarts failed runs on the HPC whose case name starts with the provided prefix: `python restart_runs.py case_name_prefix`

## Analyzing finished cases

### Compare results: `postprocessing/compare_cases.py`

This script creates a powerpoint file comparing the results of the cases provided via the `caselist` argument.
The list of cases to compare can be provided in one of two ways: as a space-delimited list of filepaths, or as a single filepath to a .csv file in the format of postprocessing/example.csv.
The first case in the list is treated as the base case, and other cases are all compared to that same case.
`compare_cases.py` accepts command line arguments to modify the figures:
- `--casenames` or `-n`: comma-delimited list of shorter case names to use in plots
- `--titleshorten` or `-s`: characters to cut from start of case name (only used if no casenames)
- `--startyear` or `-t`: First year to show
- `--sharey` or `-y`: Use same y-axis scale for absolute and difference plots
- `--basecase` or `-b`: Substring of case path to use as default (if empty, uses first case in list)
- `--skipbp` or `-p`: flag to prevent bokehpivot report from being generated
- `--bpreport` or `-r`: which bokehpivot report to generate
- `--tableau` or `-a`: create the csvs needed for publication of ReEDS study results via Tableau
- `--gdxdiff` or `-g`: generate gdx diff report between inputs.gdx when comparing 2 cases
- `--detailed` or `-d`: Include more detailed plots
- `--forcemulti` or `-m`: Always use multi-case plots (even for 2 cases)
- `--lesslabels` or `-l`: Add less value labels to plots
- `--nowrap` or `-w`: Don't wrap subplot title
- `--simplify-techs` or `-st`: Simplify technology names based on postprocessing\tech_aggregation.csv column named here
- `--label_aggregation_level` or `-a`: postprocessing\tech_aggregation.csv column to use for aggregation categories
- `--map` or `-z`: aggregate techs to hard coded dictionary, else uses aggregation categories from postprocessing\tech_aggregation.csv

Example for two cases:

```bash
python postprocessing/compare_cases.py /Users/username/github/ReEDS/runs/v20250310_main_USA /Users/username/github/ReEDS/runs/v20250310_newthing_USA
```

Example for three cases:

```bash
python postprocessing/compare_cases.py /Users/username/github/ReEDS/runs/v20250310_main_USA /Users/username/github/ReEDS/runs/v20250310_newthing1_USA /Users/username/github/ReEDS/runs/v20250310_newthing2_USA
```

Example for a .csv file of cases:

```bash
python postprocessing/compare_cases.py /Users/username/github/ReEDS/postprocessing/example.csv
```

### Run PRAS: `postprocessing/run_reeds2pras.py`

The PRAS model is typically run multiple times during each ReEDS case (as long as `GSw_PRM_CapCredit = 0`) to ensure resource adequacy.
This script reruns PRAS on a finished ReEDS case (provided by the single required command-line argument) and allows the settings to be changed.
For example, to use a different number of samples than are specified by the default `pras_samples` switch, use the `-s/--samples` command-line argument.

### Run a dispatch model: `postprocessing/run_pcm.py`

This script reruns a completed ReEDS case as a dispatch simulation at higher time resolution.
The operational constraints in `c_model.gms` are used directly, but the investment and capacity variables are fixed to their previously optimized values; only the operational variables are re-optimized.
365 representative 1-day periods at 1-hour resolution are used by default, but these settings can be changed using the `-s/--switch_mods` switch.

This approach is distinct from the [R2X](https://github.com/NatLabRockies/R2X) tool, which formats the results of a ReEDS case as inputs to a separate production cost modeling tool such as [Sienna](https://github.com/NREL-Sienna) or [PLEXOS](https://www.energyexemplar.com/plexos).
Those tools provide more advanced and realistic features like unit commitment and rolling forecast horizons;
by contrast, `run_pcm.py` simply reuses the existing ReEDS formulation at higher time resolution,
and is subject to all the normal caveats and limitations of ReEDS (linear variables, pipe-and-bubble transmission flow, etc.).

### Generate static plots: `postprocessing/single_case_plots.py`

This script runs automatically at the end of a ReEDS case and writes static figures to the `{case}/outputs/figures` folder as .png files.

### Generate interactive plots: `postprocessing/bokehpivot`

The bokehpivot module can be used to visualize the outputs of ReEDS runs.
For more information on how to use bokehpivot, see the [bokehpivot guide](bokehpivot.md).

If you're new to bokehpivot, the following YouTube video will be a good starting point: [Viewing ReEDS Outputs Using the BokehPivot Module](https://www.youtube.com/watch?v=8Xi59M4bB6I&list=PLmIn8Hncs7bG558qNlmz2QbKhsv7QCKiC&index=3)

### Calculate hourly prices and technology value metrics: `postprocessing/reValue`

reValue is used for two main things:

- extracting regional hourly prices from ReEDS scenarios and years
- (Optional) using extracted prices to calculate value and competitiveness-related metrics for a set of regional generation or load profiles.

More more information on reValue, see the [reValue documentation](revalue.md).

### Compare technology value and cost: `postprocessing/compare_tech_value.py`

This script compares the value, cost, and firmness of new-build capacity for two (or more) technologies in a finished case, using only `outputs.h5` (no re-solve required). By default it compares `battery_li` against `Gas-CT`, the standard storage-vs-peaker comparison, but any technology names can be passed via `--techs`. The module docstring covers the accounting choices in more depth than this summary.

Value comes from `valnew`, ReEDS' native "value of new investment" output, split into an energy stream and a firm-capacity stream; cost is reconstructed from `lcoe_built` and `lcoe_pieces`. Storage's charging cost is treated as an explicit cost line rather than a value deduction, so storage and thermal technologies are shown on a consistent basis. Each technology's price-weighted firm capacity contribution and capacity-weighted average storage duration are each shown both as a national/fleet-wide line and as a box plot of the distribution across regions.

- `--techs`: comma-separated technology names, exactly as they appear in `outputs.h5` (case-sensitive). A name with no exact match (e.g. `upv`) is summed across every matching `upv_*` resource class for the firm-capacity and storage-duration figures; the $/MWh figures need exact names and skip it with a warning.
- `--region` and `--region-level`: restrict to a single BA (e.g. `CA_LA`) or to every BA mapped to a `hierarchy.csv` value (e.g. `--region WI --region-level st`). Output then goes to `{case}/outputs/plots/tech_value_{region}/`.
- `--include-wind`: add land-based and offshore wind to a separate copy of the firm-capacity figure.
- `--dollar-year`, `--first-year`, `--plot-first-year`: dollar year to inflate to, first solve year to include, and first year to show in the figures.

Run as:

```bash
python compare_tech_value.py <path-to-case> [--techs battery_li,Gas-CT]
python compare_tech_value.py <path-to-case> --techs upv,wind-ons,Gas-CC --region WI --region-level st
```

Outputs are written to `{case}/outputs/plots/tech_value/` by default: tidy CSVs (`tech_value_comparison.csv`, `tech_value_by_region.csv`) and figures decomposing value, cost, net value, value factor, firm capacity contribution (line + boxplot + optional wind), storage duration (line + boxplot), and reduced cost. Use `stress_period_plots.py` to see the stress-period prices and dispatch behind the firm-capacity numbers.

### Plot stress-period prices and dispatch: `postprocessing/stress_period_plots.py`

This script plots the reserve-margin stress-period prices and dispatch of a finished case, which is what determines how much of a stress day's value a given technology can capture.

The price figures are small-multiples timeseries of the stress price ($/kW per stress timeslice) -- one panel per stress day, hour of day on the x-axis, each panel labeled with that day's share of the year's total stress price. This shows whether a stress day's high-price window is narrow enough for a short-duration resource to cover, or split into separated peaks. One figure is written per region, plus a national quantity-weighted average.

The dispatch figure is a single stress day's generation stack for one region, including net imports as a pseudo-technology (in-region generation is often well below load, with the rest covered by transmission) and a load line overlay.

- `--year` and `--region`: solve year and single BA to plot prices for; the default is the last solve year and one figure per region.
- `--dispatch-region`, `--dispatch-level`, `--dispatch-year`, `--dispatch-day`: region (or `hierarchy.csv` aggregate) and stress day for the dispatch figure. `--dispatch-day` is required whenever `--dispatch-region` is given; valid day labels appear as the price panel titles.

Run as:

```bash
python stress_period_plots.py <path-to-case> --region TX_W
python stress_period_plots.py <path-to-case> \
    --dispatch-region western --dispatch-level interconnect --dispatch-day y2009d342
```

Outputs are written to `{case}/outputs/plots/stress_periods/` by default, in `prices/` and `dispatch/` subfolders.

### Explore LCOE sensitivity to capital cost and capacity factor: `postprocessing/lcoe_sensitivity.py`

This script recomputes a technology's LCOE under a modified capital-cost or capacity-factor assumption, for a chosen region of a finished case. ReEDS's own `lcoe(i,v,r,t,rscbin)` is fixed at the run's own assumptions; this script backs out the run's own fixed-O&M-plus-site-cost term as a residual that reproduces the reported `lcoe` exactly at baseline, then holds that residual fixed while scaling capital cost and/or capacity factor by `--capex-mult`/`--cf-mult` to see how LCOE would respond. See `postprocessing/tech_eval_utils.py` for the full derivation and its simplifying assumptions.

- `--techs`: comma-separated technology names. A name with no exact match (e.g. `upv`) is expanded to every `upv_*` resource class available to build in the region.
- `--capex-mult` and `--cf-mult`: comma-separated `TECH=MULT` overrides, accepting either an exact resource class (`upv_1=0.8`) or a family name (`upv=0.8`) to scale every class in it.
- `--region` and `--region-level`: as in `compare_tech_value.py`.

Run as:

```bash
python lcoe_sensitivity.py <path-to-case> --region WI --region-level st \
    --techs Gas-CC,upv_1,upv_2,wind-ons_5 \
    --capex-mult upv_1=0.8,upv_2=0.8 --cf-mult wind-ons_5=1.1
```

Outputs are written to `{case}/outputs/plots/lcoe_sensitivity/` by default: a tidy `lcoe_sensitivity.csv` (baseline and scenario LCOE by tech/region/year) and `lcoe_sensitivity.png`.

### Compare LCOE ranges across cost scenarios: `postprocessing/lcoe_range.py`

This script plots LCOE ranges for a chosen region under alternative cost assumptions, using the same baseline calibration as `lcoe_sensitivity.py`. It writes one panel per technology family:

- The `--gas-tech` panel (default `Gas-CC`) shows two scenario lines -- the run's own capital cost, and that plus a flat `--capex-add` $/kW increase -- each with a +/-`--fuel-price-pct` fuel-price band.
- The UPV and land-based wind panels each show two bands spanning the minimum-to-maximum LCOE across every resource class present in the region: one under the run's own ATB cost assumption, and one under a higher-cost ATB file given by `--upv-conservative`/`--wind-conservative`.

Because the raw ATB cost files are on a different normalization than the processed `plantcharout.csv`, the conservative scenario is applied as a year-by-year *ratio* of conservative to moderate capital cost rather than as an absolute value. The moderate file is read from the case's own `plantchar_upv`/`plantchar_onswind` switches, so the comparison always uses whichever scenario the run actually used. The `--upv-conservative`/`--wind-conservative` defaults track a specific ATB vintage and will need updating when the input files are revised.

Run as:

```bash
python lcoe_range.py <path-to-case> --region WI --region-level st
```

Outputs are written to `{case}/outputs/plots/lcoe_range/` by default: `lcoe_range.csv` (the tidy scenario/class-level LCOE behind every band) and `lcoe_range.png`.

### Plot capacity and generation for one region: `postprocessing/region_stack.py`

This script writes capacity (GW) and generation (TWh) stacked-bar plots by technology over time for a single region, using the same conventions as `compare_cases.py`'s national stacks. The generation panel overlays an annual load line: where load sits above the stack the region is a net importer that year, and below it a net exporter.

- `--region` and `--region-level`: required; a literal BA or a `hierarchy.csv` value to aggregate.
- `--simple-techs`: the `tech_aggregation.csv` column used to group raw technology names.
- `--first-year` and `--last-year`: year range to show.

Run as:

```bash
python region_stack.py <path-to-case> --region WI --region-level st
```

Outputs are written to `{case}/outputs/plots/region_stack/` by default: `region_stack.png` plus the tidy `region_cap.csv`, `region_gen.csv`, and `region_load.csv` behind it.

### Estimate retail rates: `postprocessing/retail_rate_module`

The retail rate module can be used after finishing a ReEDS run to calculate retail electricity rates by state and year, where each state is served by its own investor-owned utility (IOU).

For more information on this module, see the [retail_rate_module documentation](retail_rate_module.md).

### Generate a Tableau results viewer: `postprocessing/tableau`

The commercial software Tableau can be used for the analysis and publication of ReEDS results.

For more information on how to use Tableau with ReEDS, see the [Tableau documentation](tableau.md).
