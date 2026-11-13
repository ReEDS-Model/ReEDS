"""
Compare system totals over a set of states (default CO+NM) across two or more ReEDS runs,
e.g. the same case solved as an island vs. within a larger footprint:
    scope_summary-{name}.csv: one row per (solve year, metric), one column per run
Metrics are summed over the zones in the chosen states (from each run's hierarchy.csv):
    load_TWh, net_export_TWh, net_export_%load: end-use load and net exports out of the states
    curt_TWh, curt_%VRE:                         curtailment, as a share of uncurtailed VRE
    stor_GWh:                                    battery + pumped-hydro energy capacity
    cap_GW|{tech}, gen_TWh|{tech}:               capacity and generation by display tech
                                                 (reedsplots.simplify_techs)

Usage:
    python postprocessing/converge/compare_scope.py runs/{case1} runs/{case2} [...]
        [--labels "island,WECC_SPP,national"] [--states CO,NM] [--years 2035,2050]
Outputs are written to runs/{case1}/outputs/converge/compare/ unless --outpath is given.
"""
#%% Imports
import os
import sys
import argparse
import pandas as pd
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import reeds
from reeds.reedsplots import simplify_techs

VRE = ['UPV', 'DPV', 'CSP', 'Onshore Wind', 'Offshore Wind']
STORAGE = ['Battery', 'Pumped-Hydro']


#%% Functions
def get_zones(case, states):
    """Zones in the run's hierarchy that belong to any of the given states"""
    hierarchy = reeds.io.get_hierarchy(case)
    return sorted(hierarchy.loc[hierarchy.st.isin(states)].index)


def read(case, filename, zones):
    """ReEDS output summed over zones, with display tech names if the output has an i column"""
    df = reeds.io.read_output(case, filename)
    df = df.loc[df.r.isin(zones)].astype({'Value': float})
    if 'i' in df:
        df['tech'] = simplify_techs(df.i)
    return df


def get_summary(case, states):
    """DataFrame of metrics with index = (t, metric)"""
    zones = get_zones(case, states)
    if not zones:
        raise ValueError(f'No zones in {states} found in {case}')
    load = read(case, 'load_rt', zones).groupby('t').Value.sum() / 1e6
    netimport = read(case, 'net_import_ann_rep', zones).groupby('t').Value.sum() / 1e6
    curt = read(case, 'curt_ann', zones).groupby('t').Value.sum() / 1e6
    uncurt = read(case, 'gen_uncurtailed', zones)
    uncurt = uncurt.loc[uncurt.tech.isin(VRE)].groupby('t').Value.sum() / 1e6
    stor = read(case, 'cap_energy_ivrt', zones)
    stor = stor.loc[stor.tech.isin(STORAGE)].groupby('t').Value.sum() / 1e3
    cap = read(case, 'cap', zones).groupby(['t', 'tech']).Value.sum() / 1e3
    gen = read(case, 'gen_ann', zones).groupby(['t', 'tech']).Value.sum() / 1e6

    netexport = -netimport.reindex(load.index, fill_value=0)
    curt = curt.reindex(load.index, fill_value=0)
    metrics = {
        'load_TWh': load,
        'net_export_TWh': netexport,
        'net_export_%load': netexport / load * 100,
        'curt_TWh': curt,
        'curt_%VRE': curt / uncurt.reindex(load.index) * 100,
        'stor_GWh': stor.reindex(load.index, fill_value=0),
    }
    df = pd.concat(metrics, names=['metric', 't']).swaplevel()
    cap.index = pd.MultiIndex.from_tuples([(t, f'cap_GW|{i}') for t, i in cap.index])
    gen.index = pd.MultiIndex.from_tuples([(t, f'gen_TWh|{i}') for t, i in gen.index])
    return pd.concat([df, cap, gen]).rename_axis(['t', 'metric'])


#%% Main
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Compare system totals over a set of states across ReEDS runs',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('cases', type=str, nargs='+', help='paths to ReEDS run folders')
    parser.add_argument('--labels', '-l', type=str, default='',
                        help='comma-delimited column labels (default: run folder names)')
    parser.add_argument('--states', '-s', type=str, default='CO,NM',
                        help='comma-delimited states to sum over')
    parser.add_argument('--years', '-y', type=str, default='',
                        help='comma-delimited solve years (default: all years in every run)')
    parser.add_argument('--name', '-n', type=str, default='',
                        help='suffix for output filenames (default: labels joined by _vs_)')
    parser.add_argument('--outpath', '-o', type=str, default='',
                        help='output folder (default: {case1}/outputs/converge/compare)')
    args = parser.parse_args()
    cases = [os.path.abspath(c) for c in args.cases]
    if len(cases) < 2:
        raise ValueError('Provide at least two runs to compare')
    labels = args.labels.split(',') if args.labels else [os.path.basename(c) for c in cases]
    if len(labels) != len(cases):
        raise ValueError(f'Got {len(labels)} labels for {len(cases)} runs')
    states = args.states.split(',')

    summary = pd.concat(
        {label: get_summary(case, states) for label, case in zip(labels, cases)}, axis=1,
    )
    common = sorted(set.intersection(*[
        set(summary[label].dropna().index.get_level_values('t')) for label in labels
    ]))
    years = [int(t) for t in args.years.split(',')] if args.years else common
    missing = [t for t in years if t not in common]
    if missing:
        raise ValueError(f'{missing} not present in every run')
    ## Metrics first, then capacity and generation by tech
    summary = summary.loc[summary.index.get_level_values('t').isin(years)].sort_index(
        key=lambda x: x.str.contains(r'\|') if x.name == 'metric' else x)
    for label in labels:
        techrows = summary.index.get_level_values('metric').str.contains(r'\|')
        summary.loc[techrows, label] = summary.loc[techrows, label].fillna(0)

    outpath = args.outpath or os.path.join(cases[0], 'outputs', 'converge', 'compare')
    os.makedirs(outpath, exist_ok=True)
    name = args.name or '_vs_'.join(labels)
    name = ''.join(c if (c.isalnum() or c in '-_.') else '' for c in name)

    summary.round(3).to_csv(os.path.join(outpath, f'scope_summary-{name}.csv'))
    print(f'\n{"+".join(states)} totals, {years[-1]}:')
    print(summary.loc[years[-1]].round(1).to_string())
    print(f'\nOutputs written to {outpath}')
