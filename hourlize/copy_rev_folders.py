"""
Copy reV supply curve source folders to the shared ReEDS supply curve directory.

Source:      original_rev_folder (from rev_paths.csv)
Destination: /kfs2/shared-projects/reeds/Supply_Curve_Data/{sc_path}/reV/{rev_case}

Usage:
    python copy_rev_folders.py
    python copy_rev_folders.py --tech wind-ons upv
    python copy_rev_folders.py --sc_path ONSHORE/2025_08_31_NewSites
    python copy_rev_folders.py --overwrite   # skip overwrite prompts
"""
import argparse
import os
import subprocess
import time

import pandas as pd


DEST_BASE = '/kfs2/shared-projects/reeds/Supply_Curve_Data'
DEFAULT_CSV = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '..', 'inputs', 'supply_curve', 'rev_paths.csv',
)


def main(rev_paths_csv, techs=None, sc_paths=None, overwrite=False):
    t0 = time.perf_counter()
    # load rev paths file
    df = pd.read_csv(rev_paths_csv)

    # subset runs as specified
    if techs:
        df = df.loc[df['tech'].isin(techs)]
    if sc_paths:
        df = df.loc[df['sc_path'].isin(sc_paths)]
    if df.empty:
        print('No rows match the given filters.')
        return

    # iterate over rows to run
    for _, row in df.iterrows():
        src = row['original_rev_folder']
        label = f"{row['tech']} / {row['access_case']}"

        if pd.isna(src) or str(src).strip() == '' or str(src) == 'none':
            print(f'[SKIP] {label}: original_rev_folder not specified.')
            continue

        src = str(src).strip()
        if not os.path.isabs(src):
            print(f'[SKIP] {label}: source path is not absolute: {src!r}')
            continue

        if not os.path.exists(src):
            print(f'[SKIP] {label}: source does not exist: {src}')
            continue

        dst = os.path.join(DEST_BASE, row['sc_path'], 'reV', row['rev_case'])

        print(f'\n[{label}]')
        print(f'  src: {src}')
        print(f'  dst: {dst}')

        # check if folder exists and follow overwrite procedure
        if os.path.exists(dst):
            if overwrite:
                print('  Destination exists — overwriting (--overwrite).')
            else:
                answer = input('  Destination already exists. Overwrite? [y/N] ').strip().lower()
                if answer != 'y':
                    print('  Skipped.')
                    continue

        # copy folder using rysnc
        os.makedirs(dst, exist_ok=True)
        t0_row = time.perf_counter()
        print('  Copying...')
        subprocess.run(
            ['rsync', '-a', '--progress', src.rstrip('/') + '/', dst],
            check=True,
        )
        elapsed_row = time.perf_counter() - t0_row
        print(f'  Done. ({elapsed_row:.1f}s)')

    elapsed = time.perf_counter() - t0
    print(f'\nTotal time: {elapsed:.1f}s')


if __name__ == '__main__':
    
    # command line arguments
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--csv', default=DEFAULT_CSV,
        help='Path to rev_paths.csv (default: inputs/supply_curve/rev_paths.csv)',
    )
    parser.add_argument(
        '--techs', '-t', nargs='+', metavar='TECH',
        help='Filter by one or more techs. E.g. --tech wind-ons upv',
    )
    parser.add_argument(
        '--sc_paths', nargs='+', metavar='SC_PATH',
        help='Filter by one or more sc_paths. E.g. --sc_path ONSHORE/2025_08_31_NewSites',
    )
    parser.add_argument(
        '--overwrite', '-o', action='store_true',
        help='Force overwrite of existing destinations without prompting',
    )
    args = parser.parse_args()

    main(args.csv, args.techs, args.sc_paths, args.overwrite)
