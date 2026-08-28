### QA/QC tool to plot hourly, state- and subsector-level electricity demand,
### tracing the demand that hourlize/load.py produces back to the raw
### EER-style source data it was built from.
###
### For "all sectors", state-level demand is produced by calling
### load.create_hourly_state_load_for_model_year() directly, so the plotted
### profiles match what an actual hourlize/load.py run would produce
### (including any exogenous sectoral load replacement). Subsector-level
### detail is aggregated away by that function, so requesting specific
### subsectors instead reads the raw EER source files directly and mirrors
### the earlier steps of create_hourly_state_load_for_model_year (timezone
### shift, state-code mapping, 8760-hour trim) without exogenous replacement.
import argparse
import datetime
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace

import matplotlib as mpl
import matplotlib.pyplot as plt
import pandas as pd

this_dir = os.path.dirname(os.path.realpath(__file__))
hourlize_path = os.path.dirname(this_dir)
reeds_path = os.path.dirname(hourlize_path)
sys.path.insert(0, hourlize_path)
sys.path.insert(0, reeds_path)
import load
import run_hourlize
import reeds
from reeds import plots

## load.create_hourly_state_load_for_model_year() calls reeds.io.write_to_h5()
## via a module-global 'reeds' that load.py's own __main__ block normally sets
## up with site.addsitedir(); set it here too since we import load.py directly.
load.reeds = reeds

plots.plotparams()


#%% ===========================================================================
### --- CONFIG / DATA ACCESS ---
### ===========================================================================
def load_hourlize_config(config_base_suffix: str | None = None) -> dict:
    """
    Load and flatten a hourlize config_base json file, resolving "{var}"
    placeholders the same way run_hourlize.setup_load() does before handing
    the config off to load.py. This keeps this script reading from the same
    paths (raw EER source, sector_config, etc.) that an actual hourlize
    load.py run would use.

    Args:
        config_base_suffix: Suffix identifying the config file (e.g., 'Anne'
            for 'config_base_Anne.json'); None uses 'config_base.json'.

    Returns:
        dict
    """
    ## run_hourlize.load_base_config()/config_string_formatter() resolve
    ## '{hourlize_path}'/'{reeds_path}' placeholders via these module globals,
    ## which are otherwise only set in run_hourlize.py's __main__ block.
    run_hourlize.hourlize_path = hourlize_path
    run_hourlize.reeds_path = reeds_path
    config = run_hourlize.load_base_config(config_base_suffix)
    cf = {**config['load'], **config['shared']}
    run_hourlize.config_string_formatter(cf, verbose=False)
    return cf


def resolve_eer_scenario(scenario: str, cf: dict) -> str:
    """
    Map a hourlize load scenario to the raw EER scenario subdirectory
    containing its underlying hourly, state- and subsector-level source
    data, following the same logic as load.main().

    Args:
        scenario: Load scenario name (from cf['scenarios'] or a replacement
            scenario ending in one of cf['replacement_to_eer_scenario_map']).
        cf: Flattened hourlize config (see load_hourlize_config()).

    Returns:
        str
    """
    replacement_map = cf.get('replacement_to_eer_scenario_map') or {}
    replace_sectors = cf.get('replace_sectors') or []
    if replacement_map and replace_sectors:
        for subsector_suffix, eer_name in replacement_map.items():
            if scenario.endswith(subsector_suffix):
                return eer_name
        raise ValueError(
            f"Cannot map scenario '{scenario}' to a raw EER scenario using "
            "'replacement_to_eer_scenario_map' in the hourlize config. "
            f"Known suffixes: {list(replacement_map)}"
        )

    valid_scenarios = list(cf.get('scenario_outfile_prefix_map', {}).keys())
    if valid_scenarios and scenario not in valid_scenarios:
        raise ValueError(
            f"'{scenario}' is not a valid load scenario. Choose from {valid_scenarios}."
        )
    return scenario


def load_sector_config(cf: dict) -> dict:
    with open(cf['sector_config_file']) as f:
        return json.load(f)


#%% ===========================================================================
### --- STATE / SUBSECTOR SELECTION ---
### ===========================================================================
def get_state_maps(reeds_path: str) -> tuple[dict, dict]:
    """
    Get the state name-to-code map used throughout hourlize/load.py, plus
    its inverse (code -> list of raw EER column names). The inverse has
    two names for 'MD' (maryland and district of columbia), matching how
    load.py folds Washington D.C. into Maryland.
    """
    state_name_code_map = load.get_state_name_code_map(reeds_path)
    code_to_names = {}
    for name, code in state_name_code_map.items():
        code_to_names.setdefault(code, []).append(name)
    return state_name_code_map, code_to_names


def resolve_states(states: list[str], code_to_names: dict) -> tuple[list[str], list[str]]:
    """
    Resolve a list of state codes (or ['CONUS']) to the state codes and raw
    EER column names (lowercase state names) they correspond to. Alaska and
    Hawaii are always excluded, matching load.py's CONUS-only scope.
    """
    if len(states) == 1 and states[0].strip().upper() == 'CONUS':
        codes = sorted(c for c in code_to_names if c not in ('AK', 'HI'))
    else:
        codes = [s.strip().upper() for s in states]
        unknown = [c for c in codes if c not in code_to_names]
        if unknown:
            raise ValueError(
                f"Unrecognized state code(s): {unknown}. "
                f"Valid codes: {sorted(c for c in code_to_names if c not in ('AK','HI'))}"
            )
    raw_names = sorted({name for code in codes for name in code_to_names[code]})
    return codes, raw_names


def list_subsectors(cf: dict, eer_scenario: str, model_year: int) -> pd.DataFrame:
    """Get the sector/subsector combinations present in the raw EER source file."""
    gz_path = os.path.join(cf['load_source'], eer_scenario, f'{model_year}.csv.gz')
    if not os.path.exists(gz_path):
        raise FileNotFoundError(f"Raw EER load source file not found: {gz_path}")
    df = pd.read_csv(gz_path, compression='gzip', usecols=['sector', 'subsector'])
    return df.drop_duplicates().sort_values(['sector', 'subsector']).reset_index(drop=True)


#%% ===========================================================================
### --- DATA ---
### ===========================================================================
def read_all_sector_load(
    cf: dict,
    eer_scenario: str,
    scenario: str,
    model_years: list[int],
    weather_years: list[int],
    state_name_code_map: dict,
    sector_config: dict,
) -> dict[int, pd.DataFrame]:
    """
    Get state-level hourly demand summed across all sectors/subsectors for
    each model year, using load.create_hourly_state_load_for_model_year()
    directly -- the same function hourlize/load.py uses in production,
    including any exogenous sectoral load replacement (e.g., data centers).
    This reflects the demand ReEDS actually sees.

    Returns:
        dict[int, pd.DataFrame]: Model year -> hourly demand by state code.
    """
    replace_sectors = cf.get('replace_sectors') or []
    replace_states = cf.get('replace_states') or []
    replacement_share = {int(k): v for k, v in dict(cf.get('replacement_share') or {}).items()}

    ## create_hourly_state_load_for_model_year() reads timezone settings from a
    ## module-global 'cf' (normally set in load.py's own __main__ block) rather
    ## than from its arguments, so it must be set here too.
    load.cf = SimpleNamespace(**cf)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_h5 = os.path.join(tmpdir, 'load_comparison.h5')
        for model_year in model_years:
            load.create_hourly_state_load_for_model_year(
                load_source_path=cf['load_source'],
                scenario=scenario,
                weather_years=weather_years,
                model_year=model_year,
                output_fpath=tmp_h5,
                state_name_code_map=state_name_code_map,
                replace_sectors=replace_sectors,
                replace_states=replace_states,
                replacement_share=replacement_share,
                sector_config=sector_config,
            )
        result = reeds.io.read_h5_groups(tmp_h5)

    ## read_h5_groups returns a single dataframe (not a dict) if there's only one group
    if isinstance(result, pd.DataFrame):
        result = {str(model_years[0]): result}
    return {int(k): v for k, v in result.items()}


def read_raw_subsector_load(
    cf: dict,
    eer_scenario: str,
    model_year: int,
    weather_years: list[int],
    subsectors: list[str],
    raw_state_names: list[str],
    state_name_code_map: dict,
) -> pd.DataFrame:
    """
    Read raw hourly, state- and subsector-level EER load for a single model
    year and aggregate to state-level demand for the requested subsectors.
    Mirrors the file layout, timezone shift, and state-code mapping used by
    load.create_hourly_state_load_for_model_year(), but preserves subsector
    granularity (which that function aggregates away) and does not include
    any exogenous sectoral load replacement.
    """
    gz_path = os.path.join(cf['load_source'], eer_scenario, f'{model_year}.csv.gz')
    if not os.path.exists(gz_path):
        raise FileNotFoundError(f"Raw EER load source file not found: {gz_path}")

    print(f"Reading raw EER load for model year {model_year} from {gz_path}...")
    usecols = ['sector', 'subsector', 'weather_datetime'] + raw_state_names
    df = pd.read_csv(gz_path, compression='gzip', usecols=usecols, parse_dates=['weather_datetime'])
    df = df.loc[df.weather_datetime.dt.year.isin(weather_years)]

    df = df.loc[df.subsector.str.lower().isin([s.lower() for s in subsectors])]
    if not len(df):
        raise ValueError(
            f"No rows match subsectors {subsectors} for model year {model_year}. "
            "Use --list-subsectors to see valid options."
        )

    ## Sum across the selected subsectors (mirrors the cross-sector sum in
    ## create_hourly_state_load_for_model_year, restricted here to a subset)
    df = df.groupby('weather_datetime', sort=False, as_index=False)[raw_state_names].sum()

    ## Apply the same timezone shift as create_hourly_state_load_for_model_year
    df = (
        df.groupby(df['weather_datetime'].dt.year, as_index=False)
        .apply(lambda x: load.roll_hourly_data(x, cf['load_source_timezone'], cf['output_timezone']))
        .set_index('weather_datetime')
        .tz_localize(cf['output_timezone'])
    )

    ## Rename raw state-name columns to state codes and merge duplicates (DC -> MD)
    df.columns = df.columns.map(state_name_code_map)
    df = df.drop(columns=['AK', 'HI'], errors='ignore')
    df = df.T.groupby(df.columns).sum().T

    ## Take only the first 8760 hours of each weather year, as ReEDS expects
    df = df.groupby(df.index.year).head(8760).round(0).astype(int)

    return df


def get_demand_h5_path(cf: dict, scenario: str) -> str:
    """
    Get the path to the processed, state-level demand_*.h5 file for a
    scenario in {reeds_path}/inputs/load -- the file ReEDS itself reads at
    run time -- using the same 'scenario_outfile_prefix_map' that
    hourlize/load.py uses to name its output files.
    """
    prefix_map = cf.get('scenario_outfile_prefix_map') or {}
    if scenario not in prefix_map:
        raise ValueError(
            f"'{scenario}' is not in the hourlize config's 'scenario_outfile_prefix_map', "
            "so its processed demand_*.h5 filename can't be determined."
        )
    return os.path.join(reeds_path, 'inputs', 'load', f"demand_{prefix_map[scenario]}.h5")


def read_processed_demand(
    cf: dict,
    scenario: str,
    model_years: list[int],
    weather_years: list[int],
) -> dict[int, pd.DataFrame]:
    """
    Read state-level hourly demand for a scenario directly from its already-
    processed demand_*.h5 file in {reeds_path}/inputs/load, rather than
    recomputing it from the raw EER source. This is fully aggregated across
    sectors/subsectors (no subsector filtering is possible here) and reflects
    exactly what a ReEDS run reads in.
    """
    h5path = get_demand_h5_path(cf, scenario)
    if not os.path.exists(h5path):
        raise FileNotFoundError(f"Processed demand file not found: {h5path}")

    print(f"Reading processed demand from {h5path}...")
    result = reeds.io.read_h5_groups(h5path)
    if isinstance(result, pd.DataFrame):
        if len(model_years) != 1:
            raise ValueError(
                f"{h5path} contains only one model year but {len(model_years)} "
                "model years were requested."
            )
        result = {str(model_years[0]): result}

    missing = [str(y) for y in model_years if str(y) not in result]
    if missing:
        raise ValueError(
            f"Model year(s) {missing} not found in {h5path}. "
            f"Available: {sorted(result.keys())}"
        )

    data_by_modelyear = {}
    for model_year in model_years:
        df = result[str(model_year)]
        data_by_modelyear[model_year] = df.loc[df.index.year.isin(weather_years)]

    return data_by_modelyear


#%% ===========================================================================
### --- PLOTS ---
### ===========================================================================
def compute_annual_totals(
    data: dict[str, dict[int, pd.DataFrame]],
    state_cols: list[str] | None = None,
) -> pd.DataFrame:
    """Sum hourly demand [MW] across states, then annual totals [TWh] by scenario/model/weather year."""
    records = []
    for scenario, data_by_modelyear in data.items():
        for model_year, df in sorted(data_by_modelyear.items()):
            cols = [c for c in state_cols if c in df.columns] if state_cols else list(df.columns)
            demand = df[cols].sum(axis=1)
            annual_twh = demand.groupby(demand.index.year).sum() / 1e6
            for weather_year, val in annual_twh.items():
                records.append({
                    'scenario': scenario,
                    'model_year': int(model_year),
                    'weather_year': int(weather_year),
                    'demand_twh': val,
                })
    return pd.DataFrame.from_records(records)


## GW = TWh * 0.7 * 10**3 / 8760
UNIT_CONVERSION_FROM_TWH = {'TWh': 1, 'GW': 0.7 * 10**3 / 8760}


def plot_annual_demand(
    df_annual: pd.DataFrame, label: str, units: str = 'TWh', savepath: str | None = None,
):
    """
    Plot type 1: Annual demand by model year, one line per scenario. If
    multiple weather years are included, each line shows the weather-year
    mean and the shaded band shows the weather-year min/max, following the
    style of postprocessing/input_plots.plot_modelyears_weatheryears().

    Plot type 3: An identical plot to Plot type 1, but using the 
    already processed inputs/profiles_demand/demand_*.h5 files.

    Args:
        units: 'TWh' (default) plots the annual total directly; 'GW' converts
            via GW = TWh * 0.7 * 10**3 / 8760.
    """
    if units not in UNIT_CONVERSION_FROM_TWH:
        raise ValueError(f"units must be one of {list(UNIT_CONVERSION_FROM_TWH)}; got '{units}'")
    df_annual = df_annual.assign(demand=df_annual['demand_twh'] * UNIT_CONVERSION_FROM_TWH[units])
    scenarios = list(dict.fromkeys(df_annual['scenario']))

    plt.close()
    f, ax = plt.subplots(figsize=(6, 4))
    stats_by_scenario = {}
    for i, scenario in enumerate(scenarios):
        color = f'C{i % 10}'
        stats = (
            df_annual.loc[df_annual.scenario == scenario]
            .groupby('model_year')['demand']
            .agg(['min', 'mean', 'max'])
            .sort_index()
        )
        stats_by_scenario[scenario] = stats
        ax.fill_between(stats.index, stats['max'], stats['min'], color=color, alpha=0.25, lw=0)
        ax.plot(stats.index, stats['mean'], color=color, marker='o', markersize=4, label=scenario)
    ax.set_xlabel('Model year')
    ax.set_ylabel(f'Annual demand [{units}]')
    ax.set_ylim(0)
    ax.set_title(label, fontsize='large', y=1.02)
    ax.xaxis.set_major_locator(mpl.ticker.MaxNLocator(integer=True))
    ax.yaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(2))
    if len(scenarios) > 1:
        ax.legend(
            loc='upper left', bbox_to_anchor=(1, 1), frameon=False, fontsize='large', title='Scenario',
        )
    plots.despine(ax)

    if savepath:
        plt.savefig(savepath, dpi=300, bbox_inches='tight')
        print(f'Saved {savepath}')

    return f, ax, stats_by_scenario


def plot_hourly_demand(
    data: dict[str, dict[int, pd.DataFrame]],
    weather_years: list[int],
    state_cols: list[str] | None,
    label: str,
    savepath: str | None = None,
):
    """
    Plot type 2: Hourly demand [GW] over the 8760 hours, one row per month,
    with one colored line per scenario/model-year/weather-year combination
    (following the pattern in reeds.plots.plotyearbymonth()).
    """
    scenarios = list(data.keys())
    multi_scenario = len(scenarios) > 1

    plt.close()
    f, ax = None, None
    i = 0
    for scenario in scenarios:
        for model_year, df in sorted(data[scenario].items()):
            cols = [c for c in state_cols if c in df.columns] if state_cols else list(df.columns)
            demand = df[cols].sum(axis=1) / 1e3
            for weather_year in weather_years:
                demand_w = demand.loc[demand.index.year == weather_year]
                if not len(demand_w):
                    raise ValueError(
                        f"No data for weather year {weather_year} in scenario '{scenario}', "
                        f"model year {model_year}."
                    )
                if multi_scenario:
                    series_label = f'{scenario} {model_year} w{weather_year}'
                else:
                    series_label = f'{model_year} w{weather_year}'
                series = demand_w.rename(series_label)
                f, ax = plots.plotyearbymonth(
                    series.to_frame(),
                    style='line',
                    colors=[f'C{i % 10}'],
                    f=f,
                    ax=ax,
                    figsize=(13.33, 4),
                )
                i += 1
    ax[0].legend(
        loc='upper left', bbox_to_anchor=(1, 1), frameon=False, fontsize='large',
        title=(
            'Scenario, model year, weather year'
            if multi_scenario else
            'Model year, weather year'
        ),
    )
    f.suptitle(f"{label}  |  weather years {', '.join(str(y) for y in weather_years)}", y=1.01)

    if savepath:
        plt.savefig(savepath, dpi=300, bbox_inches='tight')
        print(f'Saved {savepath}')

    return f, ax


#%% ===========================================================================
### --- PROCEDURE ---
### ===========================================================================
def build_label(
    scenarios: list[str],
    states_arg: list[str],
    codes: list[str],
    subsectors: list[str] | None,
    source: str | None = None,
) -> str:
    is_conus = len(states_arg) == 1 and states_arg[0].strip().upper() == 'CONUS'
    region_label = 'CONUS' if is_conus else '+'.join(codes)
    subsector_label = 'All sectors' if subsectors is None else ', '.join(subsectors)
    scenario_label = ', '.join(scenarios)
    label = f'{scenario_label} | {region_label} | {subsector_label}'
    return f'{label} | {source}' if source else label


def build_cli_command(args) -> str:
    """Build a reproducible command line for this script from parsed args."""
    cmd = [sys.executable, os.path.realpath(__file__)]

    if args.config_base:
        cmd += ['--config_base', args.config_base]
    if args.scenarios is not None:
        cmd += ['--scenarios', *args.scenarios]
    if args.states is not None:
        cmd += ['--states', *args.states]
    if args.weather_years is not None:
        cmd += ['--weather_years', *[str(y) for y in args.weather_years]]
    if args.model_years is not None:
        cmd += ['--model_years', *[str(y) for y in args.model_years]]
    if args.subsectors is not None:
        cmd += ['--subsectors', *args.subsectors]
    if args.list_subsectors:
        cmd += ['--list_subsectors']

    cmd += ['--plot_type', str(args.plot_type)]
    cmd += ['--units', args.units]

    if args.savepath:
        cmd += ['--savepath', args.savepath]
    if args.show:
        cmd += ['--show']
    if args.local:
        cmd += ['--local']

    # If the parent invocation is in batch-submission mode, force the child
    # invocation to run directly (no recursive sbatch submit).
    if args.batch:
        cmd += ['--batch']

    return ' '.join(shlex.quote(x) for x in cmd)


def submit_to_slurm(args):
    """
    Submit this script as a Slurm batch job, following the same template-based
    pattern used in hourlize/run_hourlize.py.
    """
    savedir = args.savepath or os.path.join(this_dir, 'out')
    os.makedirs(savedir, exist_ok=True)

    timestamp = datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S-%f')
    job_name = args.jobname
    batch_script = os.path.join(savedir, f'{job_name}_{timestamp}_batch.sh')

    cmd = build_cli_command(args)

    template = os.path.join(hourlize_path, 'inputs', 'configs', 'srun_template.sh')
    if not os.path.exists(template):
        raise FileNotFoundError(f'Slurm template not found: {template}')
    shutil.copy(template, batch_script)

    if args.debugnode:
        writelines = []
        with open(batch_script, 'r') as f:
            for line in f:
                writelines.append(('# ' if '--time' in line else '') + line.strip())
        with open(batch_script, 'w') as f:
            for line in writelines:
                f.write(line + '\n')
            f.write('#SBATCH --time=01:00:00\n')
            f.write('#SBATCH --partition=debug\n')

    with open(batch_script, 'a') as f:
        f.write(f'#SBATCH --job-name={job_name}\n')
        f.write(f'#SBATCH --output={os.path.join(savedir, f"slurm-qaqc-{job_name}-%j.out")}\n')
        f.write('\n. $HOME/.bashrc # load default settings\n')
        f.write('set -euo pipefail\n')
        if os.environ.get('NREL_CLUSTER') == 'kestrel':
            f.write('source /nopt/nrel/apps/env.sh\n')
            f.write('module load anaconda3\n')
            f.write('conda activate reeds\n')
        elif os.environ.get('NREL_CLUSTER') == 'eagle':
            f.write('module load conda\n')
            f.write('conda activate reeds\n')
        f.write(f'cd {shlex.quote(reeds_path)}\n')
        f.write(f'echo Running: {cmd}\n')
        f.write(f'{cmd}\n')

    if args.nosubmit:
        print(f'Created batch script: {batch_script}')
        print('Not submitted (--nosubmit).')
        return

    batch_cmd = ['sbatch', batch_script]
    print(f"Submitting: {' '.join(shlex.quote(x) for x in batch_cmd)}")
    subprocess.Popen(batch_cmd)
    print(f'Submitted {job_name}')


def main(args):
    print(
        "Loading hourlize config "
        f"({'config_base.json' if not args.config_base else f'config_base_{args.config_base}.json'})..."
    )
    cf = load_hourlize_config(args.config_base)

    scenarios = args.scenarios or cf.get('scenarios') or []
    if not scenarios:
        raise ValueError(
            "No scenario specified with --scenarios and none found in the hourlize "
            "config's 'scenarios' list."
        )
    eer_scenarios = {scenario: resolve_eer_scenario(scenario, cf) for scenario in scenarios}
    for scenario, eer_scenario in eer_scenarios.items():
        print(f"Scenario '{scenario}' maps to raw EER scenario '{eer_scenario}' at the file path: {cf['load_source']}/{eer_scenario}.")

    weather_years = args.weather_years or cf['weather_years']
    model_years = args.model_years or cf['model_years']

    state_name_code_map, code_to_names = get_state_maps(reeds_path)
    codes, raw_state_names = resolve_states(args.states, code_to_names)
    is_conus = len(args.states) == 1 and args.states[0].strip().upper() == 'CONUS'

    subsectors = (
        None if (len(args.subsectors) == 1 and args.subsectors[0].lower() == 'all')
        else args.subsectors
    )

    if args.units == 'GW' and args.plot_type == 1:
        if subsectors is None:
            raise ValueError(
                "--units GW is only allowed when --subsectors is specified and each "
                "subsector contains 'data center'."
            )
        invalid_subsectors = [s for s in subsectors if 'data center' not in s.lower()]
        if invalid_subsectors:
            raise ValueError(
                "--units GW is only allowed for subsectors containing 'data center'. "
                f"Invalid subsector(s): {invalid_subsectors}"
            )

    if args.plot_type == 3 and subsectors is not None:
        raise ValueError(
            "--subsectors is not supported for --plot_type 3: the processed demand_*.h5 "
            "files in inputs/load are already aggregated across all sectors. Omit "
            "--subsectors (or pass 'all')."
        )

    if args.list_subsectors:
        first_scenario = scenarios[0]
        df_subsectors = list_subsectors(cf, eer_scenarios[first_scenario], model_years[0])
        print(df_subsectors.to_string(index=False))
        return

    data = {}
    source = None
    if args.plot_type == 3:
        print("Reading processed demand directly from inputs/load/demand_*.h5.")
        for scenario in scenarios:
            print(f"--- Scenario: {scenario} ---")
            data[scenario] = read_processed_demand(cf, scenario, model_years, weather_years)
        state_cols = None if is_conus else codes
        source = 'processed demand_*.h5'
    elif subsectors is None:
        sector_config = load_sector_config(cf) if cf.get('replace_sectors') else {}
        print(
            "Using load.create_hourly_state_load_for_model_year() for all-sector "
            "demand (reflects the full hourlize pipeline, including any sectoral "
            "load replacement)."
        )
        for scenario in scenarios:
            print(f"--- Scenario: {scenario} ---")
            data[scenario] = read_all_sector_load(
                cf, eer_scenarios[scenario], scenario, model_years, weather_years,
                state_name_code_map, sector_config,
            )
        state_cols = None if is_conus else codes
    else:
        print(f"Reading raw EER subsector data for: {subsectors}")
        if cf.get('replace_sectors'):
            print(
                "Note: subsector-level view reflects endogenous EER load only; it "
                "does not include exogenous sectoral load replacement applied by load.py."
            )
        for scenario in scenarios:
            print(f"--- Scenario: {scenario} ---")
            data[scenario] = {
                model_year: read_raw_subsector_load(
                    cf, eer_scenarios[scenario], model_year, weather_years, subsectors,
                    raw_state_names, state_name_code_map,
                )
                for model_year in model_years
            }
        state_cols = None  # already restricted to the requested states while reading

    label = build_label(scenarios, args.states, codes, subsectors, source)
    savedir = args.savepath or os.path.join(this_dir, 'out')
    os.makedirs(savedir, exist_ok=True)
    states_tag = 'CONUS' if is_conus else '-'.join(codes)
    subsector_tag = (
        'allsectors' if subsectors is None
        else '-'.join(s.strip().replace(' ', '_') for s in subsectors)
    )
    scenario_tag = '-'.join(scenario.replace(' ', '_') for scenario in scenarios)

    if args.plot_type in (1, 3):
        df_annual = compute_annual_totals(data, state_cols)
        source_tag = 'processed' if args.plot_type == 3 else 'raw'
        savepath = os.path.join(
            savedir,
            f'annual_demand_{source_tag}_{scenario_tag}_{states_tag}_{subsector_tag}_{args.units}.png',
        )
        plot_annual_demand(df_annual, label, args.units, savepath)
    else:
        if args.units != 'GW':
            print(
                f"Note: --units {args.units} is ignored for --plot_type 2; hourly demand is "
                "always shown in GW."
            )
        weather_years_tag = '-'.join(str(y) for y in weather_years)
        savepath = os.path.join(
            savedir,
            f'hourly_demand_{scenario_tag}_{states_tag}_{subsector_tag}_w{weather_years_tag}.png',
        )
        if os.path.exists(savepath):
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
            stem, ext = os.path.splitext(savepath)
            savepath = f'{stem}-{timestamp}{ext}'
        plot_hourly_demand(data, weather_years, state_cols, label, savepath)

    if args.show:
        plt.show()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description=(
            "QA/QC plots of hourly electricity demand, reading state-level demand "
            "the same way hourlize/load.py produces it (or, for a subset of "
            "subsectors, straight from the raw EER source files)."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        '--config_base', '-c', type=str, default=None,
        help="Suffix for the hourlize config_base file. Omit to use config_base.json.",
    )
    parser.add_argument(
        '--scenarios', '-s', type=str, nargs='+', default=None,
        help="Load scenario(s) to plot (from the config's 'scenarios' list, or "
             "replacement scenarios), one line/band per scenario. Defaults to the "
             "config's 'scenarios' list.",
    )
    parser.add_argument(
        '--states', '-st', type=str, nargs='+', default=['CONUS'],
        help="State codes to include (e.g. CO NM TX), or 'CONUS' for all states.",
    )
    parser.add_argument(
        '--weather_years', '-w', type=int, nargs='+', default=None,
        help="Weather years to include. Defaults to the config's 'weather_years'.",
    )
    parser.add_argument(
        '--model_years', '-my', type=int, nargs='+', default=None,
        help="Model years to include. Defaults to the config's 'model_years'.",
    )
    parser.add_argument(
        '--subsectors', '-sub', type=str, nargs='+', default=['all'],
        help="Raw EER subsector name(s) to include (e.g. 'residential space heating'), "
             "or 'all' for every sector/subsector. Use --list-subsectors to see options. "
             "Not supported for --plot_type 3.",
    )
    parser.add_argument(
        '--list_subsectors', action='store_true',
        help="Print the sector/subsector combinations available in the raw EER "
             "source for the first requested model year, then exit.",
    )
    parser.add_argument(
        '--plot_type', '-p', type=int, choices=[1, 2, 3], default=1,
        help="1: annual demand across all model years, recomputed from the raw EER "
             "source. " \
             "2: hourly demand over the 8760 hours of one or more weather years. "
             "3: annual demand across all model years, read directly from the "
             "already-processed demand_*.h5 files in inputs/load (total demand, " \
             "not possible to view individual subsectors).",
    )
    parser.add_argument(
        '--units', '-u', type=str, choices=['TWh', 'GW'], default='TWh',
        help="Units for --plot_type 1 (annual demand). 'GW' converts via "
             "GW = TWh * 0.7 * 10**3 / 8760 for an approximation of data center deployment. "
             "Not to be used with other subsectors. " \
             "--plot_type 2 is always shown in GW. " \
             "--plot_type 3 is always shown in TWh.",
    )
    parser.add_argument(
        '--savepath', type=str, default=None,
        help="Directory to save the plot to. Defaults to hourlize/qaqc/out.",
    )
    parser.add_argument(
        '--show', action='store_true', help="Display the plot interactively.",
    )
    parser.add_argument(
        '--batch', action='store_false',
        help='Disable batch submission and run directly (default behavior is to submit to Slurm).',
    )
    parser.add_argument(
        '--nosubmit', action='store_true',
        help='Create Slurm run/batch scripts but do not submit to Slurm (use with --batch).',
    )
    parser.add_argument(
        '--debugnode', action='store_true',
        help='When batching, force 1-hour runtime on the debug partition (mirrors run_hourlize).',
    )
    parser.add_argument(
        '--jobname', type=str, default='load_comparison',
        help='Job name to use when submitting with --batch.',
    )
    parser.add_argument('--local', '-l', default=False, action='store_true',
                help='Run all cases locally (if on HPC will run on current node)'
    )

    args = parser.parse_args()
    if args.batch:
        submit_to_slurm(args)
        sys.exit(0)
    main(args)
