#!/usr/bin/env python
"""
Extract ReEDS data and run PRAS analysis with custom weather years

This script extracts data from a ReEDS case directory and optionally runs PRAS 
(Probabilistic Resource Adequacy Suite) reliability analysis. It allows users to:
1. Extract power system data from ReEDS model outputs for a specific year
2. Use weather and load profiles from a different case than the main ReEDS case
3. Configure and run PRAS with custom parameters including weather year, timesteps,
    and Monte Carlo samples
4. Control output options such as flow, surplus, and energy data

Out-of-sample runs pair the capacity stack from --casedir (the "build" case) with the
weather from --profile_case (the "weather" case). Neither case is modified: all
outputs land in a staging directory under this repo's runs/ (see --run_dir).

Example Usage:
    python pras_outofsampleweather.py --casedir runs/Apr23_climatetest_USA_mriesm20/ --year 2050 --profile_case runs/inputpronly_USA_mriesm20/ --weather_year 2050 --timesteps 61320 --run_pras
"""

import os
import json
import filecmp
import subprocess
import sys
import argparse
import reeds.resource_adequacy.prep_data as prep_data

#%% Constants
### The inputs_case files ReEDS2PRAS reads, listed in
### reeds/resource_adequacy/reeds2pras/src/utils/runchecks.jl. They are split by
### provenance: climate-driven inputs come from the weather case so they stay
### consistent with the load/VRE profiles prep_data pulls from the same case, and
### everything else describes the built fleet and comes from the build case.
###
### Climate-driven:
### * hydcf.csv: monthly hydro capacity factors by region, adjusted per climate
###   scenario in reeds/input_processing/hydcf.py.
### * outage_forced_hourly.h5: temperature-dependent forced outage rates, derived
###   from the case's own hourly temperatures in
###   reeds/input_processing/outage_rates.py (calc_outage_forced). ReEDS2PRAS
###   consumes it as a per-hour vector aligned to the simulation timeline, so it has
###   to track the same weather years as the profiles.
WEATHER_INPUTS = (
    'hydcf.csv',
    'outage_forced_hourly.h5',
)
### Fleet/technology characteristics, taken from the case that built the capacity.
BUILD_INPUTS = (
    'hydcapadj.csv',
    'mttr.csv',
    'outage_forced_static.csv',
    'outage_scheduled_hourly.h5',
    'resources.csv',
    'tech-subset-table.csv',
    'unitdata.csv',
    'unitsize.csv',
)

#%% Functions
def link(src, dest):
    """Point dest at src, replacing whatever is already there."""
    if not os.path.exists(src):
        raise FileNotFoundError(f"Missing required ReEDS2PRAS input: {src}")
    if os.path.islink(dest) or os.path.exists(dest):
        os.remove(dest)
    os.symlink(os.path.realpath(src), dest)


def stage_case_dir(run_dir, casedir, profile_case, reeds_path):
    """Assemble a staging ReEDS case directory for run_pras.jl to read.

    run_pras.jl derives every path it needs from a single --reedscase root:
    inputs_case/ for the static ReEDS2PRAS inputs, handoff/reeds_data/ for the
    prep_data outputs, handoff/PRAS/ for its own outputs, and reeds/ for the
    ReEDS2PRAS source it includes. Pointing that root straight at the profile case
    (the previous behavior) wrote outputs into the profile case's directory and took
    *every* inputs_case file from the weather case, including the ones that describe
    the built fleet. Here we build the root ourselves and symlink each input from
    whichever case it should come from, so neither source case is touched.

    The symlinked inputs are the same for every build case paired with a given
    weather case whenever the fleet files match, so one staging directory per weather
    case is enough. handoff/reeds_data/ is rewritten per build case though, so
    multiple build cases sharing a staging directory must run one at a time.
    """
    weather_case = profile_case if profile_case else casedir
    for name, path in [('--casedir', casedir), ('--profile_case', weather_case)]:
        if os.path.realpath(run_dir) == os.path.realpath(path):
            raise ValueError(
                f"--run_dir would overwrite the {name} directory ({path}). "
                "Pick a staging directory outside the source cases."
            )

    inputs_case = os.path.join(run_dir, 'inputs_case')
    reeds_data = os.path.join(run_dir, 'handoff', 'reeds_data')
    pras_dir = os.path.join(run_dir, 'handoff', 'PRAS')
    for path in [inputs_case, reeds_data, pras_dir]:
        os.makedirs(path, exist_ok=True)

    ### prep_data builds pras_vre_gen from the profile case's resources.csv, so if the
    ### two cases ever disagree the build case's copy would not line up with the
    ### profiles ReEDS2PRAS is about to read. Fail loudly rather than silently
    ### mismatching columns.
    if profile_case:
        build_resources = os.path.join(casedir, 'inputs_case', 'resources.csv')
        weather_resources = os.path.join(weather_case, 'inputs_case', 'resources.csv')
        if not filecmp.cmp(build_resources, weather_resources, shallow=False):
            raise ValueError(
                "resources.csv differs between --casedir and --profile_case:\n"
                f"  build:   {build_resources}\n"
                f"  weather: {weather_resources}\n"
                "prep_data builds pras_vre_gen from the profile case's copy, so the "
                "build case's copy would not match the profiles. Reconcile the two "
                "cases, or move 'resources.csv' from BUILD_INPUTS to WEATHER_INPUTS "
                "if the profile case's version is the correct one."
            )

    sources = {}
    for filename in WEATHER_INPUTS:
        src = os.path.join(weather_case, 'inputs_case', filename)
        link(src, os.path.join(inputs_case, filename))
        sources[filename] = src
    for filename in BUILD_INPUTS:
        src = os.path.join(casedir, 'inputs_case', filename)
        link(src, os.path.join(inputs_case, filename))
        sources[filename] = src

    ### run_pras.jl includes ReEDS2PRAS from <reedscase>/reeds/..., not from
    ### --reeds_path, so link this repo's copy in to make sure the code running is the
    ### code in this working tree rather than whatever is vendored in the source case.
    link(os.path.join(reeds_path, 'reeds'), os.path.join(run_dir, 'reeds'))

    return sources


def write_provenance(run_dir, args, sources):
    """Record where every input for this combination came from."""
    outfile = os.path.join(
        run_dir, f'provenance_{args.year}i{args.iteration}.json')
    with open(outfile, 'w') as f:
        json.dump(
            {
                'casedir': os.path.realpath(args.casedir),
                'profile_case': (
                    os.path.realpath(args.profile_case) if args.profile_case else None),
                'reeds_path': os.path.realpath(args.reeds_path),
                'run_dir': os.path.realpath(run_dir),
                'year': args.year,
                'weather_year': args.weather_year,
                'timesteps': args.timesteps,
                'iteration': args.iteration,
                'prep_iteration': args.prep_iteration,
                'pras_samples': args.pras_samples,
                'inputs_case_sources': sources,
            },
            f, indent=2,
        )
    print(f"Wrote provenance to {outfile}")


def run_pras(args):
    """Invoke reeds/resource_adequacy/run_pras.jl.

    run_pras.jl derives everything from --reedscase: the static ReEDS2PRAS inputs from
    <reedscase>/inputs_case/, the PRAS-ready data prep_data wrote from
    <reedscase>/handoff/reeds_data/, and its own outputs into
    <reedscase>/handoff/PRAS/. We point it at the staging directory built by
    stage_case_dir, which holds all three.
    """
    print('Running ReEDS2PRAS and PRAS')
    scriptpath = args.reeds_path
    command = [
        "julia",
        f"--project={args.reeds_path}",
        ### As of 20231113 there seems to be a problem with multithreading in julia on
        ### mac M1 machines and Kestrel that causes multithreaded processes to hang
        ### without resolution. So disable multithreading on those systems.
        f"--threads={args.threads if args.threads > 0 else 'auto'}",
        f"{os.path.join(scriptpath, 'reeds','resource_adequacy','run_pras.jl')}",
        f"--reeds_path={args.reeds_path}",
        f"--reedscase={args.run_dir}",
        f"--solve_year={args.year}",
        f"--iteration={args.iteration}",
        f"--weather_year={args.weather_year}",
        f"--timesteps={args.timesteps}",
        f"--hydro_energylim={args.pras_hydro_energylim}",
        f"--samples={args.pras_samples}",
        f"--write_flow={args.write_flow}",
        f"--write_surplus={args.write_surplus}",
        f"--write_energy={args.write_energy}",
        f"--overwrite={args.overwrite}",
        f"--include_samples={args.include_samples}",
    ]
    result = subprocess.run(command, text=True)
    ### subprocess.run does not raise on a nonzero exit, so without this a failed
    ### ReEDS2PRAS/PRAS run would still let this script exit 0 and the batch driver
    ### would record the combination as successful.
    if result.returncode != 0:
        raise RuntimeError(
            f"run_pras.jl exited with code {result.returncode}. See "
            f"{os.path.join(args.run_dir, 'handoff', 'PRAS')}/"
            f"PRAS_{args.year}i{args.iteration}.log"
        )

    return result

def parse_args():
    """Parse command line arguments for ReEDS data extraction and running PRAS"""
    parser = argparse.ArgumentParser(
        description="Extract ReEDS data for a specific year and store in current directory"
    )
    
    parser.add_argument(
        "--casedir", 
        required=True, 
        help="Path to the ReEDS case directory providing the capacity stack (the 'build' case)"
    )
    
    parser.add_argument(
        "--year", 
        type=int, 
        required=True, 
        help="Model year to extract data for"
    )
    
    parser.add_argument(
        "--profile_case",
        default=None,
        help="Optional: Path to a different case to use for load and resource profiles (the 'weather' case). Its inputs_case/{load,recf}.h5 and rep/ drive prep_data, and its climate-driven ReEDS2PRAS inputs (hydcf.csv, outage_forced_hourly.h5) are used instead of the build case's."
    )

    parser.add_argument(
        "--run_dir",
        default=None,
        help="Optional: Staging case directory that run_pras.jl reads as its --reedscase. Holds symlinked inputs_case files, the prep_data outputs, and the PRAS outputs. Default: <reeds_path>/runs/oos_<profile_case or casedir basename>. Neither source case is modified."
    )

    parser.add_argument(
        "--output_dir",
        default=None,
        help="Optional: Directory where prep_data output files will be stored. Default: <run_dir>/handoff/reeds_data. If overridden, must match <run_dir>/handoff/reeds_data/ for run_pras to find the data."
    )

    # PRAS-related arguments
    parser.add_argument(
        "--reeds_path",
        default=os.path.dirname(os.path.abspath(__file__)),
        help="Path to the ReEDS code repository"
    )

    parser.add_argument(
        "--iteration",
        type=int,
        default=0,
        help="Label used by run_pras.jl to name the pras_system file as PRAS_{year}i{iteration} (default: 0). In out-of-sample runs this is repurposed to identify the build case, so it does not select a stress-period directory -- see --prep_iteration."
    )

    parser.add_argument(
        "--prep_iteration",
        type=int,
        default=0,
        help="Real ReEDS solve iteration, used by prep_data to find <casedir>/inputs_case/stress{year}i{prep_iteration}/ (default: 0). Keep this at the iteration the build case actually solved, even when --iteration is repurposed as a build-case label."
    )

    parser.add_argument(
        "--weather_year",
        type=int,
        default=None,
        help="Weather year for PRAS simulation"
    )
    
    parser.add_argument(
        "--timesteps",
        type=int,
        default=8760,
        help="Number of timesteps for PRAS simulation"
    )
    
    parser.add_argument(
        "--pras_hydro_energylim",
        type=int,
        default=1,
        help="Whether to apply energy limits to hydro in PRAS (1=yes, 0=no)"
    )
    
    parser.add_argument(
        "--pras_samples",
        type=int,
        default=100,
        help="Number of Monte Carlo samples for PRAS simulation"
    )
    
    parser.add_argument(
        "--threads",
        type=int,
        default=-1,
        help="Number of threads for PRAS simulation (-1=auto)"
    )
    
    parser.add_argument(
        "--write_flow",
        type=int,
        default=0,
        help="Whether to write flow outputs from PRAS (1=yes, 0=no)"
    )
    
    parser.add_argument(
        "--write_surplus",
        type=int,
        default=0,
        help="Whether to write surplus outputs from PRAS (1=yes, 0=no)"
    )
    
    parser.add_argument(
        "--write_energy",
        type=int,
        default=0,
        help="Whether to write energy outputs from PRAS (1=yes, 0=no)"
    )
    
    parser.add_argument(
        "--overwrite",
        type=int,
        default=1,
        help="Whether to overwrite existing PRAS outputs (1=yes, 0=no)"
    )
    
    parser.add_argument(
        "--include_samples",
        type=int,
        default=0,
        help="Whether to include the number of samples in the output .csv filename (1=yes, 0=no)"
    )
    
    parser.add_argument(
        "--run_pras",
        action="store_true",
        help="Run PRAS after extracting data"
    )
    
    return parser.parse_args()

def main():
    args = parse_args()
    
    # Make sure the case directory exists
    if not os.path.exists(args.casedir):
        print(f"Error: Case directory {args.casedir} does not exist")
        sys.exit(1)

    if args.profile_case and not os.path.exists(args.profile_case):
        print(f"Error: Profile case directory {args.profile_case} does not exist")
        sys.exit(1)
    
    # Make sure the gdx file exists (new-main layout: <case>/handoff/reeds_data/)
    gdx_file = os.path.join(args.casedir, 'handoff', 'reeds_data', f'reeds_data_{args.year}.gdx')
    if not os.path.exists(gdx_file):
        print(f"Error: GDX file {gdx_file} does not exist")
        print("Make sure the ReEDS model has been run for this year and the outputs are available")
        sys.exit(1)

    # Build the staging case directory that run_pras.jl reads. Default to one
    # directory per weather case under this repo's runs/, so the source cases stay
    # untouched and the PRAS_{year}i{iteration} naming still distinguishes build cases.
    if args.run_dir is None:
        weather_case = args.profile_case if args.profile_case else args.casedir
        args.run_dir = os.path.join(
            args.reeds_path, 'runs',
            'oos_' + os.path.basename(os.path.normpath(weather_case)),
        )
    args.run_dir = os.path.abspath(args.run_dir)

    sources = stage_case_dir(
        run_dir=args.run_dir,
        casedir=args.casedir,
        profile_case=args.profile_case,
        reeds_path=args.reeds_path,
    )
    print(f"Staged ReEDS2PRAS inputs in {args.run_dir}")
    if args.profile_case:
        for filename in WEATHER_INPUTS:
            print(f"  {filename} <- profile_case")

    # Default output_dir to <run_dir>/handoff/reeds_data so run_pras.jl finds the
    # PRAS-ready files at the path it derives from --reedscase.
    if args.output_dir is None:
        args.output_dir = os.path.join(args.run_dir, 'handoff', 'reeds_data')

    os.makedirs(args.output_dir, exist_ok=True)

    write_provenance(args.run_dir, args, sources)
    
    profile_msg = f" and using weather and load profiles from {args.profile_case}" if args.profile_case else ""
    print(f"Extracting ReEDS data for year {args.year} from {args.casedir}{profile_msg}")
        
    try:
        # Call prep_data.main with the specified arguments
        csvout, h5out = prep_data.main(
            t=args.year,
            casedir=args.casedir,
            iteration=args.prep_iteration,
            profile_casepath=args.profile_case,
            output_path=args.output_dir
        )
        
        # Print the output files created
        print("\nCSV files created:")
        for key in csvout:
            print(f"  {key}_{args.year}.csv")
        
        print("\nHDF5 files created:")
        for key in h5out:
            print(f"  {key}_{args.year}.h5")
        
        print("\nExtraction complete!")
        
        # Run PRAS if requested
        if args.run_pras:
            run_pras(args)
        
    except Exception as e:
        import traceback
        print(f"Error: {e}")
        print("\nFull stack trace:")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
