#!/bin/bash
#SBATCH --account=reedsimp
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
# #SBATCH --ntasks-per-node=1
#SBATCH --mail-user=molmezt@nlr.gov
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mem=246000        # RAM in MB; up to 246000 for normal or 2000000 for bigmem on kestrel
# add >>> #SBATCH --qos=high <<< above for quicker launch at double AU cost
#SBATCH --job-name=v20260723_(USA_defaults_COPT,USA_defaults_CPLEX,USA_defaults_HIGHS)
#SBATCH --output=/kfs2/projects/reedsimp/molmezt/ReEDS_1/slurm_serial_runs/v20260723-20260724T212013/slurm-%j.out

. $HOME/.bashrc

/usr/bin/time -a -o /kfs2/projects/reedsimp/molmezt/ReEDS_1/runs/v20260723_USA_defaults_COPT/resource_stats.log -f 'memory_KB=%M, runtime=%E' bash /kfs2/projects/reedsimp/molmezt/ReEDS_1/runs/v20260723_USA_defaults_COPT/call_v20260723_USA_defaults_COPT.sh 2>&1 | tee /kfs2/projects/reedsimp/molmezt/ReEDS_1/runs/v20260723_USA_defaults_COPT/slurm-${SLURM_JOB_ID}_0.out &
/usr/bin/time -a -o /kfs2/projects/reedsimp/molmezt/ReEDS_1/runs/v20260723_USA_defaults_CPLEX/resource_stats.log -f 'memory_KB=%M, runtime=%E' bash /kfs2/projects/reedsimp/molmezt/ReEDS_1/runs/v20260723_USA_defaults_CPLEX/call_v20260723_USA_defaults_CPLEX.sh 2>&1 | tee /kfs2/projects/reedsimp/molmezt/ReEDS_1/runs/v20260723_USA_defaults_CPLEX/slurm-${SLURM_JOB_ID}_1.out &
/usr/bin/time -a -o /kfs2/projects/reedsimp/molmezt/ReEDS_1/runs/v20260723_USA_defaults_HIGHS/resource_stats.log -f 'memory_KB=%M, runtime=%E' bash /kfs2/projects/reedsimp/molmezt/ReEDS_1/runs/v20260723_USA_defaults_HIGHS/call_v20260723_USA_defaults_HIGHS.sh 2>&1 | tee /kfs2/projects/reedsimp/molmezt/ReEDS_1/runs/v20260723_USA_defaults_HIGHS/slurm-${SLURM_JOB_ID}_2.out &
wait
