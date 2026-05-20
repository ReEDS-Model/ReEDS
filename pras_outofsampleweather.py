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

Example Usage:
    python pras_outofsampleweather.py --casedir runs/Apr23_climatetest_USA_mriesm20/ --year 2050 --profile_case runs/inputpronly_USA_mriesm20/ --output_dir test_pras_inputs/ --pras_system_path test_pras_inputs/mriesm20_mriesm20.pras --weather_year 2050 --timesteps 61320 --run_pras
"""

import os
import subprocess
import sys
import argparse
import reeds.resource_adequacy.prep_data as prep_data

#%% Functions
def run_pras(
        args, 
    ):
    """
    """
    ### Get the PRAS settings for this solve year
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
        f"--inputs_case={args.profile_case}/inputs_case",
        f"--augur_data={args.output_dir}",
        f"--pras_system_path={args.pras_system_path}",
        f"--solve_year={args.year}",
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

    return result

def parse_args():
    """Parse command line arguments for ReEDS data extraction and running PRAS"""
    parser = argparse.ArgumentParser(
        description="Extract ReEDS data for a specific year and store in current directory"
    )
    
    parser.add_argument(
        "--casedir", 
        required=True, 
        help="Path to the ReEDS case directory"
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
        help="Optional: Path to a different case to use for load and resource profiles, also serves as inputs_case arg for run_pras"
    )
    
    parser.add_argument(
        "--output_dir",
        default=None,
        help="Optional: Directory where prep_data output files will be stored, this is also the input to run_pras in the augur_data flag (default: case/ReEDS_Augur/augur_data)"
    )
    
    # PRAS-related arguments
    parser.add_argument(
        "--reeds_path",
        default=os.path.dirname(os.path.abspath(__file__)),
        help="Path to the ReEDS code repository"
    )
    
    parser.add_argument(
        "--pras_system_path",
        default=None,
        help="Path to store the PRAS system (default: output_dir)"
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
        help="Whether to include raw Monte Carlo samples in output (1=yes, 0=no)"
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
    
    # Make sure the gdx file exists
    gdx_file = os.path.join(args.casedir, 'ReEDS_Augur', 'augur_data', f'reeds_data_{args.year}.gdx')
    if not os.path.exists(gdx_file):
        print(f"Error: GDX file {gdx_file} does not exist")
        print("Make sure the ReEDS model has been run for this year and the outputs are available")
        sys.exit(1)
        
    if args.profile_case is None:
        args.output_dir = os.path.join(args.casedir, 'ReEDS_Augur', 'augur_data')
    
    if args.output_dir is None:
        args.output_dir = os.path.join(args.profile_case, 'ReEDS_Augur', 'augur_data')
        
    if args.pras_system_path is None:
        args.pras_system_path = args.output_dir
    
    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)
    
    profile_msg = f" and using weather and load profiles from {args.profile_case}" if args.profile_case else ""
    print(f"Extracting ReEDS data for year {args.year} from {args.casedir}{profile_msg}")
        
    try:
        # Call prep_data.main with the specified arguments
        csvout, h5out = prep_data.main(
            t=args.year,
            casedir=args.casedir,
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
        print(f"Error extracting data: {e}")
        print("\nFull stack trace:")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
