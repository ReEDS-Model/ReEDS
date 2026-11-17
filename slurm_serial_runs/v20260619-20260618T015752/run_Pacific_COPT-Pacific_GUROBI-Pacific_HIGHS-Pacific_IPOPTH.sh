#!/bin/bash
#SBATCH --account=reedsimp
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
# #SBATCH --ntasks-per-node=1
#SBATCH --mail-user=molmezt@nlr.gov
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mem=246000        # RAM in MB; up to 246000 for normal or 2000000 for bigmem on kestrel
# add >>> #SBATCH --qos=high <<< above for quicker launch at double AU cost
#SBATCH --job-name=v20260619_(Pacific_COPT,Pacific_GUROBI,Pacific_HIGHS,Pacific_IPOPTH)
#SBATCH --output=/kfs2/projects/reedsimp/molmezt/ReEDS_1/slurm_serial_runs/v20260619-20260618T015752/slurm-%j.out

. $HOME/.bashrc

/usr/bin/time -a -o /kfs2/projects/reedsimp/molmezt/ReEDS_1/runs/v20260619_Pacific_COPT/resource_stats.log -f 'memory_KB=%M, runtime=%E' bash /kfs2/projects/reedsimp/molmezt/ReEDS_1/runs/v20260619_Pacific_COPT/call_v20260619_Pacific_COPT.sh 2>&1 | tee /kfs2/projects/reedsimp/molmezt/ReEDS_1/runs/v20260619_Pacific_COPT/slurm-${SLURM_JOB_ID}_0.out &
/usr/bin/time -a -o /kfs2/projects/reedsimp/molmezt/ReEDS_1/runs/v20260619_Pacific_GUROBI/resource_stats.log -f 'memory_KB=%M, runtime=%E' bash /kfs2/projects/reedsimp/molmezt/ReEDS_1/runs/v20260619_Pacific_GUROBI/call_v20260619_Pacific_GUROBI.sh 2>&1 | tee /kfs2/projects/reedsimp/molmezt/ReEDS_1/runs/v20260619_Pacific_GUROBI/slurm-${SLURM_JOB_ID}_1.out &
/usr/bin/time -a -o /kfs2/projects/reedsimp/molmezt/ReEDS_1/runs/v20260619_Pacific_HIGHS/resource_stats.log -f 'memory_KB=%M, runtime=%E' bash /kfs2/projects/reedsimp/molmezt/ReEDS_1/runs/v20260619_Pacific_HIGHS/call_v20260619_Pacific_HIGHS.sh 2>&1 | tee /kfs2/projects/reedsimp/molmezt/ReEDS_1/runs/v20260619_Pacific_HIGHS/slurm-${SLURM_JOB_ID}_2.out &
/usr/bin/time -a -o /kfs2/projects/reedsimp/molmezt/ReEDS_1/runs/v20260619_Pacific_IPOPTH/resource_stats.log -f 'memory_KB=%M, runtime=%E' bash /kfs2/projects/reedsimp/molmezt/ReEDS_1/runs/v20260619_Pacific_IPOPTH/call_v20260619_Pacific_IPOPTH.sh 2>&1 | tee /kfs2/projects/reedsimp/molmezt/ReEDS_1/runs/v20260619_Pacific_IPOPTH/slurm-${SLURM_JOB_ID}_3.out &
wait
