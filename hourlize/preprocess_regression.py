"""
Combine residential and commercial load data from ResStock and ComStock outputs.

Processes all scenarios (Baseline, GHP, GHP+Envelope, ASHP) and outputs combined
residential+commercial load files organized by scenario subdirectories.
Output format is compatible with the get_sectoral_replacement_load function.
"""

import argparse
import os
import pandas as pd
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple


def extract_scenario_and_year_from_filename(filename: str) -> Tuple[str, int]:
    """Extract scenario name and year from filename matching [Scenario]_y[YYYY].csv."""
    match = re.search(r'^(.+)_y(\d{4})\.csv$', filename)
    if not match:
        raise ValueError(f"Filename '{filename}' doesn't match '[Scenario]_y[YYYY].csv'")
    return match.group(1), int(match.group(2))


def group_files_by_scenario_year(files: List[str]) -> Dict[str, Dict[int, str]]:
    """Group files by scenario and year from filenames matching [Scenario]_y[YYYY].csv."""
    grouped = defaultdict(dict)
    for fpath in files:
        filename = os.path.basename(fpath)
        try:
            scenario, model_year = extract_scenario_and_year_from_filename(filename)
            grouped[scenario][model_year] = fpath
        except ValueError:
            print(f"  Skipping: {filename} (unexpected format)")
    return dict(grouped)


def read_buildstock_load_file(filepath: str) -> pd.DataFrame:
    """Read ResStock/ComStock load file with datetime index."""
    df = pd.read_csv(filepath, index_col=0, parse_dates=True)
    df.index.name = 'datetime'
    return df


def aggregate_residential_commercial_by_scenario(
    resstock_files: List[str],
    comstock_files: List[str],
    output_dir: str
) -> Dict[str, Dict[int, Tuple[str, pd.DataFrame]]]:
    """Combine residential and commercial loads by scenario and model year."""
    print("Grouping files by scenario...")
    resstock_by_scen_year = group_files_by_scenario_year(resstock_files)
    comstock_by_scen_year = group_files_by_scenario_year(comstock_files)
    
    common_scenarios = sorted(
        set(resstock_by_scen_year) & set(comstock_by_scen_year)
    )
    
    if not common_scenarios:
        raise ValueError(
            f"No common scenarios. ResStock: {list(resstock_by_scen_year.keys())}, "
            f"ComStock: {list(comstock_by_scen_year.keys())}"
        )
    
    print(f"Found {len(common_scenarios)} common scenarios: {common_scenarios}\n")
    
    results = {}
    os.makedirs(output_dir, exist_ok=True)
    
    for scenario in common_scenarios:
        print(f"Processing scenario: {scenario}")
        
        common_years = sorted(
            set(resstock_by_scen_year[scenario]) & set(comstock_by_scen_year[scenario])
        )
        
        if not common_years:
            print(f"  ⚠ No common model years")
            continue
        
        results[scenario] = {}
        scenario_dir = os.path.join(output_dir, scenario)
        os.makedirs(scenario_dir, exist_ok=True)
        
        for model_year in common_years:
            df_res = read_buildstock_load_file(resstock_by_scen_year[scenario][model_year])
            df_com = read_buildstock_load_file(comstock_by_scen_year[scenario][model_year])
            
            # Select common states and sum
            common_states = df_res.columns.intersection(df_com.columns)
            if len(common_states) == 0:
                raise ValueError(f"No common states for {scenario} {model_year}")
            
            df_combined = df_res[common_states].add(df_com[common_states])
            
            # Write output
            output_path = os.path.join(scenario_dir, f"{scenario}_y{model_year}.csv")
            df_combined.to_csv(output_path)
            results[scenario][model_year] = (output_path, df_combined)
    
    return results


def main(
    resstock_path: str,
    comstock_path: str,
    output_dir: str
) -> None:
    """Process all scenarios and write combined residential+commercial loads to subdirectories."""
    print(f"ResStock: {resstock_path}")
    print(f"ComStock: {comstock_path}")
    print(f"Output:   {output_dir}\n")
    
    resstock_files = [str(f) for f in Path(resstock_path).glob("*.csv")]
    comstock_files = [str(f) for f in Path(comstock_path).glob("*.csv")]
    
    print(f"Found {len(resstock_files)} ResStock files, {len(comstock_files)} ComStock files\n")
    
    results = aggregate_residential_commercial_by_scenario(
        resstock_files, comstock_files, output_dir
    )
    
    print(f"\n{'='*60}")
    print(f"Successfully processed {len(results)} scenarios")
    print(f"Output: {output_dir}")
    print(f"{'='*60}\n")
    
    for scenario in sorted(results.keys()):
        years = sorted(results[scenario].keys())
        n_files = len(years)
        n_hours = len(results[scenario][years[0]][1])
        n_states = len(results[scenario][years[0]][1].columns)
        print(f"{scenario:20s} {n_files} files | {n_hours:,} hours | {n_states} states")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Combine ResStock and ComStock residential+commercial load data"
    )
    parser.add_argument(
        "--resstock-path",
        type=str,
        default="/projects/geohc/radhikar/outputs/resstock_cross_val_june8_2026/ReEDs",
        help="ResStock ReEDS outputs directory"
    )
    parser.add_argument(
        "--comstock-path",
        type=str,
        default="/projects/geohc/radhikar/outputs/comstock_cross_val_may13_2026/ReEDs",
        help="ComStock ReEDS outputs directory"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="hourlize/processed_loads",
        help="Output directory (organized by scenario)"
    )
    
    args = parser.parse_args()
    main(resstock_path=args.resstock_path, comstock_path=args.comstock_path, 
         output_dir=args.output_dir)
