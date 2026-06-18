"""
This script contains the function to get the last iteration g00 file for a given case. 
This is used in the batch call scripts to identify the last iteration of a solved year 
for output processing.
"""


#%% ===========================================================================
### --- IMPORTS ---
### ===========================================================================
import sys
import argparse
from pathlib import Path

#%% ===========================================================================
### --- Function ---
### ===========================================================================

def get_last_g00(batch_case, max_year):
    pattern = f'{batch_case}_{max_year}i*.g00'
    matches = list(Path('g00files').glob(pattern))
    
    if not matches:
        print(f"ERROR: The run {batch_case} has not solved last modeled year {max_year}.", file=sys.stderr)
        sys.exit(1)
    
    last_file = max(
        matches,
        key=lambda f: int(f.stem[f.stem.rfind('i')+1:])
    )
    
    # Use forward slashes universally, works on both OS
    print((Path('g00files') / last_file.name).as_posix())

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Get the last iteration g00 file for a given batch case.')
    parser.add_argument('batch_case', type=str, help='The batch case name (e.g., v20260504_Pacific)')
    parser.add_argument('max_year', type=int, help='The last modeled year to check for (e.g., 2032)')
    args = parser.parse_args()
    
    
    get_last_g00(args.batch_case, args.max_year)