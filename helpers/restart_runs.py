#%% Imports
import os
import sys
import shutil
import subprocess
import argparse
from glob import glob
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
import reeds
from runreeds import submit_slurm_parallel_jobs
from runstatus import get_run_status

#%% Argument inputs
parser = argparse.ArgumentParser(description='Restart failed runs on the HPC')
parser.add_argument('batch_name', type=str, help='batch name (case prefix) to search for')
parser.add_argument(
    '--copy_solver_settings', '-c', action='store_true',
    help='Copy the solver settings file used by this run from the repo to the run folder',
)
parser.add_argument('--copy_srun_template', '-s', action='store_true',
                    help='Copy current srun_template.sh to sbatch file')
parser.add_argument('--force', '-f', action='store_true',
                    help='Proceed without double-checking')
parser.add_argument('--more_copyfiles', '-m', type=str, default='',
                    help=',-delimited list of additional relative filepaths to copy from reeds_path')
parser.add_argument('--copy_reeds', '-r', action='store_true',
                    help='Copy the reeds/ model folder from the repo to the run')
parser.add_argument('--include_finished', '-i', action='store_true',
                    help='Also restart finished runs (e.g. to redo postprocessing)')
parser.add_argument('--cases_file', '-p', type=str, default='',
                    help=(
                        'Path to a cases CSV file (e.g. cases_finalclimate.csv). '
                        'When provided, only cases with ignore=0 in that file will be restarted.'
                    ))

args = parser.parse_args()
batch_name = args.batch_name
copy_solver_settings = args.copy_solver_settings
copy_srun_template = args.copy_srun_template
force = args.force
more_copyfiles = [i for i in args.more_copyfiles.split(',') if len(i)]
copy_reeds = args.copy_reeds
include_finished = args.include_finished
cases_file = args.cases_file

# #%% Inputs for debugging
# batch_name = 'v20231113_yamM0'
# copy_solver_settings = True
# copy_srun_template = True
# force = True
# more_copyfiles = ['report.gms']
# copy_reeds = False
# include_finished = False
# cases_file = ''

###### Procedure
#%% Shared parameters
reeds_path = reeds.io.reeds_path
#%% Get all runs
dictruns = get_run_status(reeds_path, batch_name)

runs_unfinished = dictruns['running'] + dictruns['failed']
runs_failed = dictruns['failed']
runs_running = dictruns['running']

### Take a look
print('unfinished:', len(runs_unfinished))
print('running:', len(runs_running))
print('failed:', len(runs_failed))

#%% Filter by cases_file ignore switch if provided
if cases_file:
    df_cases = pd.read_csv(cases_file, index_col=0, header=0)
    ignore_row = df_cases.loc['ignore']
    # Keep only runs whose case column has ignore explicitly set to 0
    allowed = {col for col, val in ignore_row.items() if str(val).strip() == '0'}
    before = len(runs_failed)
    runs_failed = [
        r for r in runs_failed
        if os.path.basename(r).split(batch_name + '_', 1)[-1] in allowed
    ]
    print(
        f'Filtered by {os.path.basename(cases_file)} (ignore=0): '
        f'{before} → {len(runs_failed)} runs'
    )

#%% Double check
if not force:
    for i in runs_failed:
        print(os.path.basename(i))
    print(f'Restarting the {len(runs_failed)} runs listed above.')
    confirm_local = str(input('Proceed? [y]/n: ') or 'y')
    if confirm_local not in ['y','Y','yes','Yes','YES']:
        quit()


#%% Copy the header from the srun_template.sh file if desired
if copy_srun_template:
    srun_template = os.path.join(reeds_path,'reeds','hpc','srun_template.sh')
    writelines_srun = list()
    with open(srun_template, 'r') as f:
        for line in f:
            writelines_srun.append(line.strip())
else:
    writelines_srun = list()

#%%### Loop through runs, figure out when they failed, and restart
for case in runs_failed:
    casename = os.path.basename(case)

    #%% Copy the solver settings file if desired
    if copy_solver_settings:
        fpath_settings = Path(
            reeds.io.reeds_path, 'reeds', 'solver', reeds.io.get_optfile(case)
        )
        shutil.copy(fpath_settings, os.path.join(case,''))

    #%% Copy additional files if desired
    for f in more_copyfiles:
        shutil.copy(f, Path(case, f))
    if copy_reeds:
        shutil.copytree(Path(reeds_path, 'reeds'), Path(case, 'reeds'), dirs_exist_ok=True)

    #%% Make a backup copy of the original bash and sbatch scripts
    callfile = os.path.join(case,f'call_{casename}.sh')
    shutil.copy(callfile, os.path.join(case,f'ORIGINAL_call_{casename}.sh'))

    sbatchfile = os.path.join(case,f'{casename}.sh')
    shutil.copy(sbatchfile, os.path.join(case,f'ORIGINAL_{casename}.sh'))

    #%% Get last .lst file and restart from there
    lstfiles = sorted(glob(os.path.join(case,'lstfiles','*.lst')))
    if any([os.path.basename(i).startswith('report') for i in lstfiles]):
        restart_tag = '# Output processing'
    elif len(lstfiles) < 2: 
        # If there is only 1 lst file, then it is an environment.csv,
        #  so the run failed during inputs processing 
        restart_tag = '# Input processing'
    elif len(lstfiles) == 2: 
        # If there are only 2 lst files, then one of them will be environment.csv and
        # the other will be 1_inputs.lst, so the run failed during the model compilation 
        restart_tag = '# Compile model'
    else:
        # Drop environment and inputs .lst files
        lstfiles = [i for i in lstfiles if ("environment.csv" not in i) and ('1_Inputs.lst' not in i)]
        lastfile = lstfiles[-1]
        restart_year = int(os.path.splitext(lastfile)[0].split('_')[-1].split('i')[0])
        restart_tag = f'# Year: {restart_year}'

    #%% Comment out the unnecessary lines
    writelines = []
    with open(callfile, 'r') as f:
        comment = 0
        for line in f:
            ## Start commenting at input processing
            if '# Input processing' in line:
                comment = 1
            ## Stop commenting at restart_tag
            if line.startswith(restart_tag):
                comment = 0
            ## Record it
            writelines.append(('# ' if comment else '') + line.strip())

    ### Write it
    with open(callfile, 'w') as f:
        for line in writelines:
            f.writelines(line + '\n')

# Check if we are going to run this in parallel or not
hpc = True if (int(os.environ.get('REEDS_USE_SLURM',0))) else False
if hpc and len(runs_failed) > 1:
    # On HPC with multiple cases 
    cases_per_node = int(input('Number of simultaneous runs per node [integer]: '))
else:
    cases_per_node = 1

if hpc and (cases_per_node > 1):
    # Write the slurm scripts for parallel runs and 
    # submit them to the HPC
    casenames = [os.path.basename(p).split(batch_name + "_", 1)[-1] for p in runs_failed]
    submit_slurm_parallel_jobs(
        reeds_path=reeds_path,
        BatchName=batch_name,
        casenames=casenames,
        cases_per_node=cases_per_node,
    )

else:
    # Run each case individually
    for case in runs_failed:
        casename = os.path.basename(case)
        callfile = os.path.join(case, f'call_{casename}.sh')
        sbatchfile = os.path.join(case, f'{casename}.sh')
        # It is a single case or we are not on HPC
        if copy_srun_template:
            writelines_srun_case = writelines_srun.copy()
            writelines_srun_case.append(f"\n#SBATCH --job-name={casename}\n")
            writelines_srun_case.append(f"sh {callfile}")
            with open(sbatchfile, 'w') as f:
                for line in writelines_srun_case:
                    f.writelines(line + '\n')

        #%% Run it
        sbatch = f'sbatch {sbatchfile}'
        sbatchout = subprocess.run(sbatch, capture_output=True, shell=True)

        if len(sbatchout.stderr):
            print(sbatchout.stderr.decode())
        print(f"{casename}: {sbatchout.stdout.decode()}")
