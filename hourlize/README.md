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

* **Tech config** (`config_[tech].json`): tech specific settings for the `resource.py` script for upv, wind-ons, and wind-ofs
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
- reV supply curve file (.csv), specified by `sc_path` in the the `rev_paths.csv` file
- corresponding hourly generation profile(s) (.h5), specified by `rev_path` in the the `rev_paths.csv` file
- class mapping files specified in config files, located at `/inputs/resource` (tech-dependent)

### Outputs 
- `supplycurve_{tech}.csv`: A supply curve with rows for each site and columns for region, class, available capacity, and costs (e.g., `inputs/supply_curve/wind-ons_supply_curve-reference.csv`). 
- `{tech}_.h5`: Hourly capacity factor profiles for each region/class;
these files include datasets with column names (class|region) and an index with datetime and timezone information (e.g., `inputs/profiles_cf/cf_wind-ons_reference.h5`)

Outputs are stored in `hourlize/out/[casename]`, with config options to automatically copy to ReEDS (`copy_to_reeds`, on by default) and the Supply_Curve_Data folder (`copy_to_shared`, off by default).


### Logic

The `resource.py` script follows the following logic (in order of execution):

1. `copy_rev_folders()`
    * Copies the original reV data specified in the `rev_paths.csv` to the specified `Supply_Curve_Data` folder
1. `get_supply_curve_and_preprocess()`
    * The supply curve is filtered if necessary, based on `filter_cols`.
    * If we have minimum capacity thresholds for the supply curve points, these are applied to further filter the supply curve.
1. `add_classes()`
    * A 'class' column is added to the supply curve and filled with the associated class. Classes can be based on statically defined conditions for columns in the supply curve (`class_path`). Otherwise (or layered on top of static class definitions), dynamic classes can be assigned (`class_bin`=true) using a binning method (`class_bin_method`, e.g. "kmeans"), a number of bins (`class_bin_num`), and the supply curve column to bin (`class_bin_col`). The binning logic itself is in `reeds.inputs.get_bin()`. The current default classes for onshore wind and utility-scale PV are based on national k-means clustering of average annual capacity factor (where higher class number corresponds with higher annual CF). Offshore wind, by contrast, uses statically defined classes from `hourlize/inputs/resource/wind-ofs_resource_classes.csv`.
1. `add_cost()`
    * A column of overall supply curve costs is added to the supply curve (`supply_curve_cost_per_mw`), as well as certain components of that cost (e.g. `trans_adder_per_mw` and `capital_adder_per_mw`). Logic for these costs depends on `tech`, and the value of `cost_out` in config (e.g. `combined_eos_trans` for onshore wind).
    * A column of overall supply curve costs is added to the supply curve (`supply_curve_cost_per_mw`), as well as certain components of that cost (e.g. `trans_adder_per_mw` and `capital_adder_per_mw`). Logic for these costs depends on `tech`, and the value of `cost_out` in config (e.g. `combined_eos_trans` for onshore wind).
1. `save_sc_outputs()`
    * Supply curve outputs are saved (`supplycurve_{tech}.csv`).
1. `process_cf_profiles()`
    * The hourly generation profiles are gathered and applicable conversions (AC-to-DC, scaling) are applied. The processed profiles are saved to a `{tech}.h5` file. This method makes use of the same h5 format specified in the `get_site_cf_hourly` function used by `recf.py` in ReEDS.
1. `copy_outputs()`
    * Copy outputs from the new directory within hourlize/out to the corresponding input files in the ReEDS repo (`copy_to_reeds`) and/or shared drive (`copy_to_shared`)

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
| compression_opts  |  file compression options. can select from 0-9: 0 is faster and larger, 9 is slower and smaller, 4 is default | 4 |
| decimals  | Number of decimal points to round to for most outputs |  4 |
| filetype  |  output filetype: 'csv' or 'h5'. Note that load.py uses h5 regardless |  'h5' |
| hierarchy_path  | Path to ReEDS hierarchy file. Typically used for region mapping for resource.py and calibration/variability outputs for load.py |  '{reeds_path}/inputs/hierarchy.csv' |
| output_timezone        | Either a timezone recognized by python (e.g., Etc/GMT+6 for Central Standard Time) or an integer providing UTC offset (e.g., UTC is 0; CST is 6) |  'Etc/GMT+6' |
| select_year  | this is the year used for resource profile-derived inputs, although the profile outputs may still be multiyear (see hourly_out_years) | 2012 |

### Resource config

| Setting | Description | Default |
| :------ | :---------- | :------ |
| bin_group_cols  |  |  ['region','class'] |
| bin_method  | 'equal_cap_man', 'equal_cap_cut'. 'kmeans' currently commented out to prevent numpy depracation warnings from sklearn. |  'equal_cap_cut' |
| copy_to_reeds  | Copy hourlize outputs to ReEDS inputs |  True |
| copy_to_shared  | Copy hourlize outputs to the shared drive |  False |
| driver  | 'H5FD_CORE', None. H5FD_CORE will load the h5 into memory for better perforamnce, but None must be used for low-memory machines. |  'H5FD_CORE' |
| dtype  | data type used to save hourly profiles |  np.uint16 |
| gather_method  |  'list', 'slice', 'smart'. This setting will take a slice of profile ids from the min to max, rather than using a list of ids, for improved performance when ids are close together for each group. |  'smart' |
| hourly_out_years  | e.g. [2012] for just 2012 or a list of year [2011, 2012, 2013] | [2007, 2008, 2009, 2010, 2011, 2012, 2013], |
| inputfiles | list of files to copy over to hourlize input folder | ["reg_map_file", "class_path"] |
| profile_id_col  | Unique identifier for reV supply curve and profiles |  'sc_point_gid' |
| resource_source_timezone  | UTC would be 0, Eastern standard time would be -5 | 0 |
| scale_factor  | Factor by which capacity factor values are scaled up when writing hourly profiles. | 1e4 |
| state_abbrev  | Path to file with state abbreviations  | '{hourlize_path}/inputs/resource/state_abbrev.csv' |
|   subsetvars | list of columns in the rev_paths file to use to select the appropriate rev_path   | ['tech', 'access_case'] |
| subtract_exog  | Indicate whether to remove exogenous (pre-start_year) capacity from the supply curve [default False] |  False |

### Tech configs

| Setting | Description | Default |
| :------ | :---------- | :------ |
| cost_out  | 'combined_eos_trans' is a computed column from economies of scale and transmission cost. To turn off economies of scale, use 'trans_cap_cost'. 'combined_off_ons_trans' is a computed column from offshore (array and export) as well as onshore transmission cost.   |  upv, wind-ons: 'combined_eos_trans'<br>wind-ofs: 'combined_off_ons_trans' |
| capacity_col  | Format of the supply curve capacity column |  upv: 'capacity_mw_{upv_type_out}'<br>wind-ofs: 'capacity_mw'<br>wind-ons: 'capacity' |
| class_bin  | This will layer dynamic bins. If class_path != None, we add region-specific bins for each of the classes defined in class_path. |  upv, wind-ons: true<br>wind-ofs: false |
| class_bin_col  | The column to be binned (only used if class_bin = True) |  upv: 'mean_cf_{upv_type_out}'<br>wind-ofs,wind-ons: 'mean_cf' |
| class_bin_method  | The bin method, either 'kmeans', 'equal_cap_cut', or 'equal_cap_man' (only used if class_bin = True)  |  'kmeans' |
| class_bin_num  | The number of class bins (only used if class_bin = True)  | upv: 10<br> wind-ofs, wind-ons: 10 |
| class_path  | null or path to class definitions file |  upv, wind-ons: null<br>wind-ofs: {hourlize_path}/inputs/resource/{tech}_resource_classes.csv  |
| filter_cols  | {} means use the entire dataframe; {'offshore':['=',0]} means filter the supply curve to rows for which offshore is 0. |  upv, wind-ons: {}<br>wind-ofs: {'offshore':['=',0]} |
| min_cap  | MW  (LBNL utility-scale solar report & NLR PV cost benchmarks define utility-scale as ≥5 MW) | upv: 5, wind-ofs: 15, wind-ons: 0 |
| profile_dir  | Use '' if .h5 files are in same folder as metadata, else point to them, e.g. f'../{rev_case}' |  upv: '{access_case}_{upv_type_out}'<br>wind-ons, wind-ofs: '' |
| profile_dset  | Name of hourly profiles in reV runs |  'rep_profiles_0' |
| profile_file_format  | Format for hourly profiles filename. Note: unused if single_profile |  upv: {rev_case}_rep-profiles<br>wind-ons, wind-ofs: '' |
| profile_weight_col  | Name of column to use for weighted average of profiles. Using 'capacity' will link to whatever value is specified by 'capacity_col'  |  'capacity' |
| single_profile  | single_profile has different columns and a single h5 profile file (for all years). |  upv, wind-ofs: false, wind-ons: true |
| upv_type_out  | type of UPV capacity and profiles to produce; options are 'ac' and 'dc'  |  upv: 'dc'; wind-ons, wind-ofs: null |

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
