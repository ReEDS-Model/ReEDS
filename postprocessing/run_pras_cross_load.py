"""
Cross-load PRAS resource-adequacy testing.

Takes the PRAS system (generators, storage, transmission) built for one ReEDS
run ("base case") and re-assesses it using the regional load timeseries from
one or more *other* ReEDS runs ("load cases"), instead of the base case's own
load. This is useful for stress-testing a given generation portfolio against
load shapes from other scenarios (e.g. different weather years, electrification
assumptions, or climate scenarios) without rebuilding the generation fleet.

Both the base case and each load case must already have a saved .pras system
file (i.e. `postprocessing/run_reeds2pras.py` has already been run for that
case/year), and the two systems must model the same set of regions and have
the same number of timesteps.

Example usage on the HPC:
    case=/projects/reedsweto/github/ReEDS/runs/v20260524_baseline
    otherload=/projects/reedsweto/github/ReEDS/runs/v20260524_hiload
    python postprocessing/run_pras_cross_load.py $case $otherload -s 1000
"""
#%% Imports
import argparse
import os
import site
import subprocess
from glob import glob
import pandas as pd

reeds_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


#%%### Functions
def check_slurm(forcelocal=False):
    """Check whether to submit slurm jobs (if on HPC) or run locally"""
    hpc = True if (int(os.environ.get('REEDS_USE_SLURM', 0))) else False
    hpc = False if forcelocal else hpc
    return hpc


def find_pras_system(case, year=0, iteration=None):
    """
    Locate the .pras system file for a ReEDS run, using the same
    "latest solve iteration" logic as postprocessing/run_reeds2pras.py.
    Does not build the file if it's missing -- run run_reeds2pras.py first.
    """
    years = pd.read_csv(
        os.path.join(case, 'inputs_case', 'modeledyears.csv')
    ).columns.astype(int).tolist()
    t = year if (year in years) else years[-1]

    if iteration is None:
        matches = sorted(glob(os.path.join(case, 'lstfiles', f'*{t}i*.lst')))
        if not matches:
            raise FileNotFoundError(f"No lstfiles found for year {t} in {case}")
        iteration = int(
            os.path.splitext(matches[-1])[0].split(f'{t}i')[-1]
        )

    pras_system_path = os.path.join(
        case, 'handoff', 'PRAS', f'PRAS_{t}i{iteration}.pras'
    )
    if not os.path.isfile(pras_system_path):
        raise FileNotFoundError(
            f"{pras_system_path} does not exist. Run "
            f"`python postprocessing/run_reeds2pras.py {case} -y {t} -i {iteration}` "
            "first to build the PRAS system (0 samples is fine if you only "
            "need the system, not a full assessment)."
        )
    return pras_system_path, t, iteration


def submit_job(
    case,
    julia_command,
    jobname,
    threads=1,
):
    """Write and submit a SLURM job that runs a single julia_command string"""
    commands_header, commands_sbatch, commands_other = [], [], []
    with open(os.path.join(reeds_path, 'reeds', 'hpc', 'srun_template.sh'), 'r') as f:
        for line in f:
            if line.strip().startswith('#!'):
                commands_header.append(line.strip())
            elif line.strip().startswith('#SBATCH'):
                commands_sbatch.append(line.strip())
            else:
                commands_other.append(line.strip())
    slurm = (
        commands_header
        + commands_sbatch
        + [f"#SBATCH --job-name={jobname}"]
        + [f"#SBATCH --output={os.path.join(case, 'handoff', 'PRAS', 'crossload', f'slurm-{jobname}-%j.out')}"]
        + [f"#SBATCH --cpus-per-task={threads}" if threads else '']
        + commands_other + ['']
        + [julia_command]
    )
    os.makedirs(os.path.join(case, 'handoff', 'PRAS', 'crossload'), exist_ok=True)
    callfile = os.path.join(
        case, 'handoff', 'PRAS', 'crossload', f'call_{jobname}.sh')
    with open(callfile, 'w+') as f:
        for line in slurm:
            f.writelines(line + '\n')
    batchcom = f'sbatch {callfile}'
    subprocess.Popen(batchcom.split())


#%% Main function
def main(
    base_case,
    load_cases,
    year=0,
    base_iteration=None,
    load_iteration=None,
    samples=100,
    seed=1,
    overwrite=False,
    write_flow=False,
    write_surplus=False,
    write_energy=False,
    write_shortfall_samples=False,
    write_availability_samples=False,
    outdir=None,
    local=False,
):
    """
    For each load_case, submit (or run) a job that assesses base_case's PRAS
    system using load_case's regional load timeseries.
    """
    site.addsitedir(reeds_path)
    import reeds

    base_case = os.path.abspath(base_case)
    base_pras, base_year, base_it = find_pras_system(base_case, year, base_iteration)
    print(f'Base system:  {base_pras}')

    sw = reeds.io.get_switches(base_case)
    threads = sw['threads'] if sw.get('threads', 0) > 0 else 1

    outdir = outdir or os.path.join(base_case, 'handoff', 'PRAS', 'crossload')
    os.makedirs(outdir, exist_ok=True)

    hpc = check_slurm(forcelocal=local)

    for load_case in load_cases:
        load_case = os.path.abspath(load_case)
        load_pras, load_year, load_it = find_pras_system(
            load_case, year, load_iteration)
        print(f'Load system:  {load_pras}')

        base_name = os.path.basename(base_case)
        load_name = os.path.basename(load_case)
        outfile = os.path.join(
            outdir,
            f'PRAS_{base_name}_{base_year}i{base_it}'
            f'_loadfrom_{load_name}_{load_year}i{load_it}-{samples}.h5'
        )

        julia_command = ' '.join([
            "julia",
            f"--project={reeds_path}",
            f"--threads={threads}",
            f"{os.path.join(reeds_path, 'reeds', 'resource_adequacy', 'run_pras_cross_load.jl')}",
            f"--base_pras={base_pras}",
            f"--load_pras={load_pras}",
            f"--outfile={outfile}",
            f"--samples={samples}",
            f"--pras_seed={seed}",
            f"--overwrite={int(overwrite)}",
            f"--write_flow={int(write_flow)}",
            f"--write_surplus={int(write_surplus)}",
            f"--write_energy={int(write_energy)}",
            f"--write_shortfall_samples={int(write_shortfall_samples)}",
            f"--write_availability_samples={int(write_availability_samples)}",
        ])

        jobname = f'PRASxLoad-{base_name}-{load_name}-{samples}'

        if hpc:
            print(f'Submitting SLURM job {jobname}')
            submit_job(base_case, julia_command, jobname, threads=threads)
        else:
            print(f'Running locally: {jobname}')
            print(julia_command)
            log = open(os.path.join(outdir, f'{jobname}.log'), 'a')
            result = subprocess.run(
                julia_command, stdout=log, stderr=log, text=True, shell=True)
            log.close()
            if result.returncode:
                raise Exception(
                    f"run_pras_cross_load.jl returned code {result.returncode} for "
                    f"{jobname}. Check {log.name} for the error trace."
                )


#%%### Procedure
if __name__ == '__main__':
    description = """Assess one ReEDS run's PRAS system (generators/storage/transmission)
    using the regional load timeseries from one or more other ReEDS runs. Both the
    base case and each load case must already have a saved .pras system (i.e.
    postprocessing/run_reeds2pras.py has already been run for that case/year).
    """
    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('base_case', type=str,
                         help='path to the ReEDS run providing the PRAS generation/'
                              'storage/transmission system')
    parser.add_argument('load_cases', type=str, nargs='+',
                         help='path(s) to the ReEDS run(s) providing the regional load '
                              'timeseries to test the base system against')
    parser.add_argument('--year', '-y', type=int, default=0,
                         help='solve year to use for both base and load cases '
                              '(0 = last modeled year of each case)')
    parser.add_argument('--base_iteration', type=str, default='',
                         help='solve-year iteration to use for the base case '
                              '(if not provided, uses the last iteration)')
    parser.add_argument('--load_iteration', type=str, default='',
                         help='solve-year iteration to use for the load case(s) '
                              '(if not provided, uses the last iteration)')
    parser.add_argument('--samples', '-s', type=int, default=100,
                         help='PRAS samples to run')
    parser.add_argument('--seed', type=int, default=1,
                         help='PRAS random seed (0 = random)')
    parser.add_argument('--overwrite', '-o', action='store_true',
                         help='overwrite results if the output file already exists')
    parser.add_argument('--flow', '-f', action='store_true',
                         help='write hourly flow from PRAS')
    parser.add_argument('--surplus', '-u', action='store_true',
                         help='write hourly surplus from PRAS')
    parser.add_argument('--energy', '-e', action='store_true',
                         help='write hourly storage energy from PRAS')
    parser.add_argument('--shortfall', '-d', action='store_true',
                         help='write hourly shortfall by sample from PRAS')
    parser.add_argument('--availability', '-a', action='store_true',
                         help='write hourly unit availability by sample from PRAS')
    parser.add_argument('--outdir', type=str, default='',
                         help='directory to write results to '
                              '(default: <base_case>/handoff/PRAS/crossload)')
    parser.add_argument('--local', '-l', action='store_true',
                         help='run locally (not as a SLURM job)')

    args = parser.parse_args()

    main(
        base_case=args.base_case,
        load_cases=args.load_cases,
        year=args.year,
        base_iteration=(None if not len(args.base_iteration) else int(args.base_iteration)),
        load_iteration=(None if not len(args.load_iteration) else int(args.load_iteration)),
        samples=args.samples,
        seed=args.seed,
        overwrite=args.overwrite,
        write_flow=args.flow,
        write_surplus=args.surplus,
        write_energy=args.energy,
        write_shortfall_samples=args.shortfall,
        write_availability_samples=args.availability,
        outdir=(args.outdir if len(args.outdir) else None),
        local=args.local,
    )
