# -*- coding: utf-8 -*-
"""
Code to process allowed shifting hours for demand response into
fraction of hours that can be shifted into each time slice
At some point, it may be nice to instead read in the actual DR
shifting potential and change to fraction of load that can be shifted
but haven't done that yet.

Created on Feb 24 2021
@author: bstoll
"""

# %% ===========================================================================
### --- IMPORTS ---
### ===========================================================================
import os
import sys
import argparse
import pandas as pd
import datetime
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))
import reeds
# Time the operation of this script
tic = datetime.datetime.now()

# %%#################
### FIXED INPUTS ###

decimals = 4


#%% ===========================================================================
### --- MAIN FUNCTION ---
### ===========================================================================

if __name__ == "__main__":
    ### Parse arguments
    parser = argparse.ArgumentParser(
        description="This file produces the DR shiftability inputs"
    )
    parser.add_argument("reeds_path", help="ReEDS directory")
    parser.add_argument("inputs_case", help="output directory")

    args = parser.parse_args()
    inputs_case = args.inputs_case
    reeds_path = args.reeds_path

    # Settings for testing
    # reeds_path = os.getcwd()
    # inputs_case = os.path.join(reeds_path,'runs','dr1_Pacific','inputs_case')

    #%% Set up logger
    log = reeds.log.makelog(
        scriptname=__file__,
        logpath=os.path.join(inputs_case,'..','gamslog.txt'),
    )
    print('Starting writedrshift.py')

    #%% Inputs from switches
    sw = reeds.io.get_switches(inputs_case)
    val_r = reeds.io.read_input(inputs_case, 'r').squeeze(1).tolist()

    reeds.log.toc(tic=tic, year=0, process='input_processing/writedrshift.py', 
        path=os.path.join(inputs_case,'..'))
    print('Finished writedrshift.py')  
