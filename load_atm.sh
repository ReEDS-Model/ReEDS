#!/bin/bash

cd /kfs2/projects/atm/Bcakire/ReEDS || exit 1

module load anaconda3
conda activate /kfs2/projects/atm/Bcakire/conda_envs/reeds2_atm

module load julia/1.12.1
export JULIA_DEPOT_PATH=/kfs2/projects/atm/Bcakire/julia_depot

echo "CONDA_PREFIX=$CONDA_PREFIX"
echo "Python:"
which python
python --version

echo "Julia:"
which julia
julia --version

echo "JULIA_DEPOT_PATH=$JULIA_DEPOT_PATH"
module load gams/51.3.0
