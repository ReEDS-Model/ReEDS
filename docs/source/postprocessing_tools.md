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

This script compares the value, cost, and firmness of new-build capacity for two (or more) technologies in a finished case, using only `outputs.h5` (no re-solve required). By default it compares `battery_li` against `Gas-CT`, the standard storage-vs-peaker comparison, but any technology names can be passed via `--techs`. Run `python compare_tech_value.py --help` for the full, grouped list of options; the module docstring covers the framing and accounting choices in more depth than this summary.

**Value and cost.** Value is built from `valnew`, ReEDS' native "value of new investment" output, split into an energy stream and a firm-capacity stream; cost is reconstructed from `lcoe_built` and `lcoe_pieces` without reimplementing the capital recovery factor. Storage's charging cost is treated as an explicit cost line (the storage analogue of a thermal tech's fuel cost) rather than a value deduction, so storage and thermal technologies are shown on a consistent basis.

**Firm capacity and storage duration.** Each technology's price-weighted firm capacity contribution (stress-period generation divided by total capacity, weighted by each stress period's reserve-margin price, reusing `revenue`'s 'res_marg' category since GAMS already computes it this way when `GSw_PRM_CapCredit=0`) and fleet-wide average storage duration (from `storage_duration_out`, capacity-weighted) are each shown two ways: a national/fleet-wide line, and a box-and-whisker plot of the distribution across regions per year, since a single national number can hide a lot of regional variation. `--include-wind` adds a third figure with land-based and offshore wind as two extra lines, each summed across every `wind-ons_*`/`wind-ofs_*` resource class present in the case.

**Region filter.** `--region` (with `--region-level`, e.g. `--region WI --region-level st`) restricts the value/cost, firm-capacity-contribution, and storage-duration figures and CSVs to a single BA or every BA mapped to a hierarchy.csv value (state, interconnect, transreg, ...), instead of the national aggregate; output goes to `{case}/outputs/plots/tech_value_{region}/`. For firm-capacity-contribution and storage-duration specifically (both built by summing an additive numerator before dividing), any `--techs` entry with no exact match in outputs.h5 is summed across every matching `{entry}_*` resource class present in the case (e.g. `upv` -> `upv_1`, `upv_2`, ...), the same principle `--include-wind` already uses for wind; the value/cost-stack, value-factor, and reduced-cost figures need exact tech names and skip (with a warning) any entry with no exact match, since their $/MWh figures can't be summed across classes without re-deriving weights.

**Stress-period prices.** In a `stress_period_prices/` subfolder: one figure per region (plus a national quantity-weighted average from `reqt_price_sys`), each a small-multiples timeseries of the reserve-margin stress price ($/kW) -- one panel per stress day, hour-of-day on the x-axis, each panel labeled with that day's % share of the year's total stress price. This is what determines whether a given storage duration can cover a stress day's whole high-price window, or whether that window is split into separated peaks -- and how much that shape (and which days matter) varies by region. `--price-year`/`--price-region` control which year/region to show.

**Stress-period dispatch.** For digging into *why* a particular region/day's price looks the way it does, `--dispatch-region` (with required `--dispatch-day`, e.g. `y2009d342` -- see the stress-period-price panel titles for valid labels) writes a single stress-day dispatch stack to a `dispatch/` subfolder: `gen_h_stress` by tech, plus a `net_import_h_stress` 'Net imports' pseudo-tech (in-region generation is often well below load, with the rest covered by transmission, so without this the stack would understate supply and look like an unexplained deficit), with a `load_stress` line overlay. A sustained (not narrowly spiking) elevated price on some day usually shows up as heavy import reliance across most hours of that day, rather than a single tight hour. `--dispatch-region` can also name a value in `hierarchy.csv` (via `--dispatch-level`, e.g. `--dispatch-region western --dispatch-level interconnect`) to aggregate every region mapped to it -- net imports still work correctly when aggregated, since flows between two regions both in the aggregate cancel out, leaving only the aggregate's net flow across its true boundary.

Run as:

```bash
python compare_tech_value.py <path-to-case> [--techs battery_li,Gas-CT]
python compare_tech_value.py <path-to-case> --techs upv,wind-ons,Gas-CC --region WI --region-level st
```

Outputs are written to `{case}/outputs/plots/tech_value/` by default (or `tech_value_{region}/` when `--region` is given): tidy CSVs (`tech_value_comparison.csv`, `tech_value_by_region.csv`); figures decomposing value, cost, net value, value factor, firm capacity contribution (line + boxplot + optional wind), storage duration (line + boxplot), and reduced cost; and the `stress_period_prices/` and `dispatch/` subfolders described above.

### Explore LCOE sensitivity to capital cost and capacity factor: `postprocessing/lcoe_sensitivity.py`

This script recomputes a technology's LCOE under a modified capital-cost or capacity-factor assumption, for a chosen region of a finished case. ReEDS's own `lcoe(i,v,r,t,rscbin)` (see `report.gms`, "LCOE" section) is fixed at the run's own assumptions; this script backs out the run's own fixed-O&M-plus-site-cost term as a residual that reproduces the reported `lcoe` exactly at baseline, then holds that residual fixed while scaling capital cost and/or capacity factor by `--capex-mult`/`--cf-mult` to see how LCOE would respond. See the module docstring for the full derivation and its simplifying assumptions.

Run as:

```bash
python lcoe_sensitivity.py <path-to-case> --region WI --region-level st \
    --techs Gas-CC,upv_1,upv_2,wind-ons_5 \
    --capex-mult upv_1=0.8,upv_2=0.8 --cf-mult wind-ons_5=1.1
```

Outputs are written to `{case}/outputs/plots/lcoe_sensitivity/` by default: a tidy `lcoe_sensitivity.csv` (baseline and scenario LCOE by tech/region/year) and `lcoe_sensitivity.png`.

### Estimate retail rates: `postprocessing/retail_rate_module`

The retail rate module can be used after finishing a ReEDS run to calculate retail electricity rates by state and year, where each state is served by its own investor-owned utility (IOU).

For more information on this module, see the [retail_rate_module documentation](retail_rate_module.md).

### Generate a Tableau results viewer: `postprocessing/tableau`

The commercial software Tableau can be used for the analysis and publication of ReEDS results.

For more information on how to use Tableau with ReEDS, see the [Tableau documentation](tableau.md).
