#!/bin/bash
#SBATCH --account=reedsimp
#SBATCH --time=00-04:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --mail-user=molmezt@nlr.gov
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mem=246000        # RAM in MB; up to 246000 for normal or 2000000 for bigmem on kestrel
# add >>> #SBATCH --qos=high <<< above for quicker launch at double AU cost