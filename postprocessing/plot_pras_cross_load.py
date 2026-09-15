"""
Diagnostic plots for a run_pras_cross_load.jl output file.

Reuses plotting functions from reeds/resource_adequacy/diagnostic_plots.py
that only depend on the assessed EUE/LOLE results and the regional load that
was fed into PRAS -- i.e. the plots that are meaningful for a hybrid
"base case fleet + other case's load" system, as opposed to the fleet-mix
plots in diagnostic_plots.py that describe a single case's own generation
portfolio.

Normally invoked automatically by postprocessing/run_pras_cross_load.py after
run_pras_cross_load.jl finishes, but can also be run standalone against an
existing cross-load output file.
"""
#%% Imports
import argparse
import os
import site
import traceback

reeds_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


#%% Main function
def main(base_case, load_case, outfile, t, load_year=None, load_iteration=None):
    """
    Generate diagnostic plots for a run_pras_cross_load.jl output file, and
    write them to a 'plots' subfolder next to `outfile`, within that run's
    own folder under handoff/PRAS/crossload.

    Parameters
    ----------
    base_case : path to the ReEDS run that supplied the PRAS generation/
        storage/transmission fleet
    load_case : path to the ReEDS run that supplied the substituted regional
        load timeseries
    outfile : path to the run_pras_cross_load.jl results .h5 file
    t : solve year used for the base system (i.e. the hybrid system's
        timestamps, which are inherited from the base case)
    load_year : solve year used for the load case (default: same as t)
    load_iteration : solve-year iteration used for the load case
        (default: last)
    """
    site.addsitedir(reeds_path)
    import reeds
    from reeds.resource_adequacy import diagnostic_plots

    base_case = os.path.abspath(base_case)
    load_case = os.path.abspath(load_case)
    load_year = t if load_year is None else load_year

    #%% Assemble the minimal switches/data needed by the reused plot functions
    sw = reeds.io.get_switches(base_case)
    sw['t'] = t
    ## Plots go in a 'plots' subfolder alongside the results file, within the
    ## run's own folder (which also holds the call script, log, and SLURM output)
    sw['savepath'] = os.path.join(os.path.dirname(outfile), 'plots')
    os.makedirs(sw['savepath'], exist_ok=True)

    fulltimeindex = reeds.timeseries.get_timeindex(sw.resource_adequacy_years)

    dfs = {}
    ## Hourly USA/regional EUE and LOLE from this cross-load assessment
    dfs['pras'] = reeds.io.read_pras_results(outfile)
    dfs['pras'].index = fulltimeindex
    ## Regional load actually used in this assessment (comes from load_case)
    dfs['pras_load'] = reeds.io.get_pras_system(
        load_case, year=load_year,
        iteration=('last' if load_iteration is None else load_iteration),
    )['load']
    dfs['pras_load'].index = fulltimeindex

    #%% Make the plots
    for func in [
        diagnostic_plots.plot_dropped_load_timeseries_full,
        diagnostic_plots.plot_dropped_load_duration,
    ]:
        try:
            func(sw, dfs)
        except Exception:
            print(f'{func.__name__}() failed:', traceback.format_exc())

    for level in ['r', 'transgrp']:
        try:
            diagnostic_plots.map_dropped_load(sw, dfs, level=level)
        except Exception:
            print(f'map_dropped_load(level={level}) failed:', traceback.format_exc())

    print(f'Wrote cross-load diagnostic plots to {sw["savepath"]}')


#%%### Procedure
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Generate diagnostic plots for a run_pras_cross_load.jl output file')
    parser.add_argument('base_case', type=str,
                         help='ReEDS run that supplied the PRAS generation/storage/'
                              'transmission fleet')
    parser.add_argument('load_case', type=str,
                         help='ReEDS run that supplied the substituted regional load')
    parser.add_argument('outfile', type=str,
                         help='path to the run_pras_cross_load.jl .h5 results file')
    parser.add_argument('--t', type=int, required=True,
                         help='solve year used for the base system')
    parser.add_argument('--load_year', type=int, default=None,
                         help='solve year used for the load case (default: same as --t)')
    parser.add_argument('--load_iteration', type=int, default=None,
                         help='solve-year iteration used for the load case (default: last)')

    args = parser.parse_args()

    main(
        base_case=args.base_case,
        load_case=args.load_case,
        outfile=args.outfile,
        t=args.t,
        load_year=args.load_year,
        load_iteration=args.load_iteration,
    )
