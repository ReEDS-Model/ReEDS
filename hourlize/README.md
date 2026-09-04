---
orphan: true
---

# Hourlize

## Overview

Hourlize processes hourly resource and load data into ReEDS inputs. 
The vision is for this module to allow maximum flexibility temporally and spatially.

Hourlize is run by a call to `run_hourlize.py`, which assembles information on the cases to run and then executes a call to either
 `resource.py` and `load.py`. The `run_hourlize.py` script can be used to set up jobs to submit to the HPC to run in parallel or to run hourlize jobs directly in sequence.

## Quickstart: Resource

1. Update the `rev_paths` folder in ReEDS.
1. Update settings in `config_base.json` and the relevant tech configs (`config_[tech].json`) as needed ([details](#config-jsons)).
1. If submitting slurm jobs on the HPC, specify run allocation and other submission settings in `hourlize/inputs/configs/srun_template.sh` ([details](#config-jsons)).
1. Run `run_hourlize.py resource` ([details](#running-hourlize)).
1. Update `inputs/supply_curve/dollaryear.csv` if needed. 
1. If the results are intended to be used on the main branch, then after testing and quality control, upload the new profiles to the remote host as described in `preprocessing/README.md`
1. Sync up the new folders in `Supply_Curve_Data` to (e.g., if you ran on the HPC, copy to nrelnas01 and Yampa).

## Quickstart: Load

1. Update settings in `config_base.json` as needed ([details](#config-jsons)), including `load_source`.
1. If running on the HPC, specify run allocation or other submission settings in `inputs/configs/srun_template.sh` ([details](#config-jsons)).
1. Run using `run_hourlize.py load` ([details](#running-hourlize)).
1. Outputs are written to `ReEDS/inputs/load`.
    1. If the results are intended to be used on the main branch, then after testing and quality control, upload the new profiles to the remote host as described in `preprocessing/README.md`.
    1. If the results are not intended for general use, they can still be used locally in ReEDS by setting the `GSw_LoadProfiles` switch to the absolute filepath of the resulting hourly demand file.

## Details on setup

### Config jsons

Resource mode in hourlize uses a set of json config files to provide information on how to process the supply curves. These files are located in `hourlize/inputs/configs`:

* **Tech config** (`config_[tech].json`): tech-specific settings for the `resource.py` script for UPV, onshore wind, offshore wind, EGS, and geohydro
* **Base config** (`config_base.json`): general hourlize settings (shared) as well as specific settings for the resource and load processes

The `run_hourlize.py` process will generate a final config (`config.json`) from the relevant base and tech configs for each run. In the case of duplicated entries across configs hourlize the tech config value takes precendence.

The `srun_template.sh` file is used to govern HPC submission settings. Update with your allocation, email, and any other slurm specifications before submitting jobs. There is also a command line argument to via `run_hourlize.py` for running jobs using the debug partition.

For more details on the meaning of the different config settings see the tables in the [Details on config file settings](#details-on-config-file-settings) section. 

### Updating the `rev_paths` file (resource mode)

If you don't have new reV supply curves you can probably skip this section and go down to [running hourlize](#running-hourlize).

Update the fields in `ReEDS/inputs/supply_curve/rev_paths.csv` for the relevant techs. Some details on the columns to update:

* `original_rev_folder`: full path of the original location of the supply curves passed by the reV team.
* `original_sc_file`: path to the original reV supply curve csv files (i.e., before hourlize pre-processing). Specified relative to the "reV" folder within the corresponding sc_path.
* `sc_path`: name of the folder to add in `Supply_Curve_Data` to store the reV files and hourlize results; should be of the format tech/update_name (e.g. UPV/2023_06_06_Update, ONSHORE/2023_07_28_Update).
* `rev_case`: name of the reV case to be used for this scenario; this should reference a directory in the "reV" folder with the sc_path (e.g., if 02_limited is one of the rev_case values for upv, then there should be a folder called UPV/2023_06_06_Update/reV/02_limited).
* `cf_path`: full path to the generation file used for the reV runs. This can typically be found in the `config_aggregation.json` file from the reV run as `gen_fpath`. An exception is for bespoke wind runs, in which case this should point to the reV profiles. Not used by ReEdS but needed for R2X.

## Running hourlize

### run_hourlize.py

The `run_hourlize.py` script serves as a wrapper for calling either `load.py` or `resource.py`. It does the following:

* Collect run(s) configuration settings from the relevant config files to build a consolidated config file for each run.
* Runs formatting on config file entries.
  * Entries with {variable} in the text will have the {variable} text replaced with the value referenced by 'variable', which typically refers to another config entry or a file path.
  * Entries with {eval_expression} will evaluate 'expression' as a python expression; useful for creating lists using ranges.
  * Combines all configs into a single config.json sent to resource.py.
* Creates an output folder for the supply curve run in `hourlize/out/[casename]`, where casename is defined in the `cases.json file`.
* Creates a .sh or .bat script to run the case with a call to `resource.py`.
* Optionally submits jobs to the HPC or initiates the runs directly.

Example calls:

```bash
python run_hourlize.py load                  # run load.py
python run_hourlize.py resource              # run resource.py with default cases
python run_hourlize.py resource --local      # if on HPC run all cases sequentially on current node without batch submission to slurm
python run_hourlize.py resource --nosubmit   # if on HPC create launch scripts and input folders but don't submit runs
python run_hourlize.py status                # check status on a set of resource runs
```

Command-line arguments can be used to run a subset of technologies or access cases.
To see details on all command line arguments run `python run_hourlize.py -h`.

After setting up the run, if specified `run_hourlize.py` will launch the .sh or .bat file which performs the following call to `resource.py`:

```bash
python resource.py --config /path/to/hourlize/[casename]/inputs/config.json
```

### Tips for processing reV supply curves (resource mode)

* Hourlize is currently best configured to run on the NLR HPC, with submission of parallel slurm jobs for resource processing.
* By default hourlize is set up to copy outputs into the ReEDS repo (`copy_to_reeds = true`).
* If you want the hourlize runs to be copied back the shared supply curve folder, set `copy_to_shared = true`. Note that if running on the HPC you'll still need to sync up the folders on nrelnas01 and Yampa.
* After running hourlize, check to make sure the supply curve folders have open permissions; if they don't, you can set open permissions with `chmod -R 777 [folder_name]`. 
* Hourlize relies on a set of columns being in the reV supply curve. In some cases hourlize can fill in missing columns hourlize in a pre-processing step, but in others these missing columns can cause hourlize to fall. A list of required columns can be found in `hourlize/inputs/resource/rev_sc_columns.csv`
* The dollar year typically aligns with the ATB year of the reV run, although it's best to confirm with the reV team to make sure all their costs have been converted to that dollar year.


## Resource Logic (resource.py)

### Inputs
- reV supply curve file (.csv), selected from `rev_paths.csv` using the case's `tech` and `access_case`
- corresponding hourly generation profile(s) (.h5), located under the selected reV case
- class mapping files specified in config files, located at `/inputs/resource` (tech-dependent)

### Outputs 
- `supplycurve_{tech}.csv`: A supply curve with rows for each site and columns for region, class, available capacity, and costs (e.g., `inputs/supply_curve/wind-ons_supply_curve-reference.csv`). 
- `{tech}.h5` or `{tech}.csv.gz`: Hourly capacity-factor profiles for each processed year, with site IDs, time indexes, and scaled capacity-factor values.

Outputs are stored in `hourlize/out/[casename]`, with config options to automatically copy to ReEDS (`copy_to_reeds`) and the Supply_Curve_Data folder (`copy_to_shared`). Both options are enabled by default in `config_base.json`.

### Logic

The `resource.py` script follows the following logic (in order of execution):

1. `copy_rev_folders()`
    * Copies the original reV data specified in `rev_paths.csv` to the corresponding `Supply_Curve_Data` folder.
1. Geothermal supply-curve aggregation (EGS and geohydro only)
    * When `geo_run_supply_curve_aggregation` is true, raw geothermal supply curves are collected across cases, optionally filtered by `atb_scenario`, and reduced to the lowest-LCOE entry for each `sc_point_gid`.
1. `get_supply_curve_and_preprocess()`
    * Reads the selected supply curve, applies the technology-specific `filter_cols` filters and `min_cap` threshold, maps sites to ReEDS regions, and adds county/state metadata. Offshore meshing is controlled by `offshore_meshed`.
1. `add_classes()`
    * Adds a `class` column using static definitions from `class_path` and/or dynamic bins when `class_bin` is true. Dynamic bins use `class_bin_method`, `class_bin_num`, and `class_bin_col`; the binning logic is in `reeds.inputs.get_bin()`.
1. `add_cost()`
    * Adds overall and component supply-curve costs, including `supply_curve_cost_per_mw`, `trans_adder_per_mw`, and `capital_adder_per_mw`. Categories included vary by `tech`.
1. `save_sc_outputs()`
    * Saves the processed supply curve as `supplycurve_{tech}.csv`.
1. `process_cf_profiles()`
    * When `process_profiles` is true, reads the requested years from the reV profiles, keeps only sites present in the processed supply curve, applies UPV AC-to-DC conversion when requested, scales values by `scale_factor`, and writes the hourly profiles using the configured output format.
1. `copy_outputs()`
    * Copies run outputs and configuration metadata to the ReEDS inputs and/or shared drive according to `copy_to_reeds` and `copy_to_shared`.

## Load Logic (load.py)

* See Load Quickstart at top for overall load pipeline. load.py processes the load profiles coming from EER, converting them into ReEDS model inputs. EER load profiles are originally delivered at the state, subsector level for 15 weather years (2007-2013 + 2016-2023) and 7 model years (2021, 2025, 2030, 2035, 2040, 2045, 2050), via compressed csv.gz files, in Central Standard Time (hour-ending). The basic logic of load.py is outlined below.

1. Where applicable, replace subsectors of EER load with other data sources as specified in `inputs/configs/config_base.json` and `inputs/load/sector_config.json`.
1. Aggregate the load profiles to the state level.
1. Convert the load profiles from the source timezone to the output timezone.
1. Remove the final day from leap years.

## Details on config file settings

This section provides some descriptions and typical values for the settings in the config files (see [above](#config-jsons) for a general overview of these config files).

### Shared config

| Setting | Description | Default |
| :------ | :---------- | :------ |
| compression_opts | HDF5 compression level from 0 (fastest/largest) to 9 (slowest/smallest) | 4 |

### Resource config

| Setting | Description | Default |
| :------ | :---------- | :------ |
| class_bin_method | Method used for dynamic class bins: 'kmeans', 'equal_cap_cut', or 'equal_cap_man' | 'kmeans' |
| copy_to_reeds | Copy hourlize outputs to ReEDS inputs | true |
| copy_to_shared | Copy hourlize outputs to the shared drive | true |
| filetype | Output file type for hourly profiles: 'csv' or 'h5' | 'h5' |
| hourly_out_years | Years to include in exported hourly profiles | [2007, 2008, 2009, 2010, 2011, 2012, 2013, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023] |
| inputfiles | Config entries for files to copy into the hourlize input folder | ["reg_map_file", "class_path"] |
| offshore_meshed | Whether to use meshed offshore transmission connections when matching supply curves to counties | false |
| process_profiles | Whether to process and export hourly capacity-factor profiles | true |
| profile_id_col | Unique identifier for supply-curve sites and profiles | 'sc_point_gid' |
| reg_map_file | Path to the ReEDS region mapping file | '{reeds_path}/inputs/zones/z90/county2zone.csv' |
| rev_paths_file | Path to the file defining reV supply-curve and profile locations | '{reeds_path}/inputs/supply_curve/rev_paths.csv' |
| scale_factor | Factor used to scale capacity-factor values when writing hourly profiles | 1e4 |
| state_abbrev | Path to the state-abbreviation file | '{hourlize_path}/inputs/resource/state_abbrev.csv' |
| subsetvars | Columns in `rev_paths_file` used to select the appropriate reV path | ['tech', 'access_case'] |
| subtract_exog | Legacy flag passed to supply-curve output processing; currently has no effect | false |

### Tech configs

| Setting | Description | Default |
| :------ | :---------- | :------ |
| atb_scenario | ATB scenario used when aggregating geothermal supply curves | egs, geohydro: 'moderate' |
| capacity_col | Supply-curve column containing available capacity | upv: 'capacity_{upv_type_out}_mw'<br>wind-ons, wind-ofs, egs, geohydro: 'capacity_ac_mw' |
| class_bin | Whether to create dynamic class bins in addition to any classes from `class_path` | upv, wind-ons, wind-ofs: true<br>egs, geohydro: false |
| class_bin_col | Supply-curve column to use for dynamic class bins | upv: 'capacity_factor_{upv_type_out}'<br>wind-ons: 'capacity_factor_ac'<br>wind-ofs: 'ncf_2035'<br>egs, geohydro: 'capacity_factor_ac' |
| class_bin_num | Number of dynamic class bins | upv: 5<br>wind-ons: 10<br>wind-ofs: 5<br>egs, geohydro: 10 |
| class_path | Path to class definitions, or null to omit static class definitions | upv, wind-ons: null<br>wind-ofs, egs, geohydro: '{hourlize_path}/inputs/resource/{tech}_resource_classes.csv' |
| filter_cols | Column filters applied before processing the supply curve | upv: {"capacity": [">", 0]}<br>wind-ons: {"capacity": [">", 0], "offshore": [":", 0]}<br>wind-ofs: {"capacity_ac_mw": [">", 0], "offshore": [":", 1], "mean_depth": [">", -1300]}<br>egs, geohydro: {} |
| geo_aggregation_method | Method used to aggregate geothermal supply curves | egs, geohydro: 'lowest_lcoe' |
| geo_run_supply_curve_aggregation | Whether to aggregate geothermal supply curves before processing | egs, geohydro: true |
| min_cap | Minimum site capacity in MW | upv: 5<br>wind-ofs: 15<br>wind-ons, egs, geohydro: 0 |
| profile_dir | Directory containing hourly profile files, relative to the reV case | upv: '{access_case}_ac'<br>wind-ons, wind-ofs, egs, geohydro: '' |
| profile_dset | HDF5 dataset containing hourly profiles | upv, wind-ons, wind-ofs: 'rep_profiles_0'<br>egs, geohydro: '' |
| profile_file_format | Filename format for hourly profiles | upv: '{access_case}_ac_rep-profiles'<br>wind-ofs: '{rev_case}_rep-profiles'<br>wind-ons, egs, geohydro: '' |
| process_profiles | Whether to process hourly profiles for the technology | egs, geohydro: false |
| single_profile | Whether all profile years are stored in a single profile file | upv, wind-ofs: false<br>wind-ons: true<br>egs, geohydro: null |
| upv_type_out | UPV capacity and profile type to produce: 'ac' or 'dc' | upv: 'dc' |

### Load config

| Setting | Description | Default |
| :------ | :---------- | :------ |
| inputfiles | list of files to copy over to hourlize input folder | [] |
| legacy_ba_state_map_file | File mapping the set of 134 legacy ReEDS zones to the states they belong to. | '{hourlize_path}/inputs/load/legacy_ba_state_map.csv' |
| legacy_ba_timezone_file | File defining the timezones for the set of 134 legacy ReEDS zones. | '{hourlize_path}/inputs/load/legacy_ba_timezone.csv' |
| load_source | Directory containing subdirectories named after load scenarios. Each load scenario subdirectory should contain compressed csv files (using gzip compression), each named after the relevant model year (e.g., "{load_source}/baseline/2025.csv.gz"). Each file should contain one column for each state, containing hourly load values in MW, along with "weather_datetime", "sector", and "subsector" columns. Each year of the datetime column should start at Jan 1, 12am. | '/projects/eerload/source_eer_load_profiles/20250512_eer_download/shape_outputs_2025-05-12' |
| load_source_timezone | Timezone of the load source, assuming times are reported using the hour-ending convention. The timezone should be recognized by python (e.g., Etc/GMT+6 for Central Standard Time). | 'Etc/GMT+6' |
| model_years | List of model years to include in exported load profiles. | [2021, 2025, 2030, 2035, 2040, 2045, 2050] |
| replace_sectors | List of sectors for which endogenous (with respect to 'load_source') sectoral load should be replaced with load from external load sources. | [] |
| replace_states | List of lowercase names of states in the contiguous U.S. (or "all" to represent all states in the contiguous U.S.) whose sectoral load (using sectors specified in 'replace_sectors') should be replaced. | 'all' |
| replacement_share | The percentage (specified as a number from 0 to 1) of endogenous sectoral load (using sectors specified in 'replace_sectors') that should be removed in each model year before adding exogenous sectoral load. Dictionary keys are the model years and dictionary values are the percentages. | {"2021": 1, "2025": 1, "2030": 1, "2035": 1, "2040": 1, "2045": 1, "2050": 1} |
| scenarios | List of load scenarios (of those listed as subdirectories in 'load_source') to include in exported load profiles. | ['IRA cons', 'central', 'baseline'] |
| sector_config_file | File containing configuration defining the subsectors of each sector, the model years for which sectoral load should be replaced, and information concerning the files containing exogenous sectoral load. | '{hourlize_path}/inputs/load/sector_config.json' |
| weather_years | List of weather years to include in exported load profiles. | [2007, 2008, 2009, 2010, 2011, 2012, 2013, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023] |
