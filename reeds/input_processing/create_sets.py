#%% Imports
import sys
import argparse
import pandas as pd
from pathlib import Path
from typing import Literal
from datetime import datetime
sys.path.append(str(Path(__file__).parent.parent.parent))
import reeds
tic = datetime.now()


#%% Objects
class GAMSset:
    def __init__(
        self,
        df:pd.Series|pd.DataFrame,
        gamstype:Literal['set','parameter']='set',
        units:str='',
        comment:str='',
    ):
        self.df = df
        self.gamstype = gamstype
        self.units = units
        self.comment = comment


#%% Functions
def make_r_level(case):
    """Mappings between r (zones) and higher geographic hierarchy levels"""
    ## Normal ones
    hierarchy = reeds.io.get_hierarchy(case)
    dictout = {}
    for level in hierarchy:
        df = hierarchy[level].reset_index()
        dictout[f'r_{level}'] = GAMSset(df, 'set')
    ## Special cases
    # r_itlgrp
    # r_loadsitereg
    return dictout


#%%
def main(case):
    #%% Make sets
    dictout = {
        **make_r_level(case),
    }
    #%% Write them
    for key, dset in dictout.items():
        reeds.io.write_to_inpust_h5(
            dset.df, key, case,
            gamstype=dset.gamstype, units=dset.units, comment=dset.comment,
        )
    #%% Done
    return dictout


#%% Procedure
if __name__ == '__main__':
    #%% Parse arguments
    parser = argparse.ArgumentParser(description="Create model sets")
    parser.add_argument('reeds_path', help='ReEDS directory path')
    parser.add_argument('inputs_case', help='inputs_case directory path')

    args = parser.parse_args()
    case = Path(args.inputs_case).parent

    # #%% Settings for testing ###
    # case = str(Path(reeds.io.reeds_path, 'runs', 'v20260724_inputsM0_MARICTNYNJPAOH_Offshore'))

    #%% Set up logger
    log = reeds.log.makelog(scriptname=__file__, logpath=Path(case, 'gamslog.txt'))
    print('Starting create_sets.py', flush=True)

    #%% Run it
    main(case)

    #%% Finish the timer
    reeds.log.toc(tic=tic, year=0, process='input_processing/create_sets.py', path=case)
    print('Finished create_sets.py', flush=True)
