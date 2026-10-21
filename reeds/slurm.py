### Imports
import os


### Functions
def get_cluster():
    """
    Return the name of the HPC cluster if on a cluster.
    If not on a cluster, return None.
    """
    name_fields = ['NREL_CLUSTER', 'NLR_CLUSTER']
    ## Keep the first match in name_fields
    for name_field in name_fields:
        out = os.environ.get(name_field)
        if out:
            break
    return out


def check_slurm(forcelocal=False):
    """Check whether to submit slurm jobs (if on HPC) or run locally"""
    if forcelocal:
        hpc = False
    else:
        hpc = True if get_cluster() else False
    return hpc
