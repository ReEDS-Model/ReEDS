#%% Imports
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import os
import sys
import math
import json
import argparse
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
import reeds

# Get reedsplots from ReEDS repo
reeds_path = reeds.io.reeds_path
sys.path.append(reeds_path)

from reeds import plots
plots.plotparams()

############################################################################################################# 
def main():

    ########################################## USER-DEFINED INPUTS ##########################################
    parser = argparse.ArgumentParser(description="Calculating euclidean distance between two solutions")
    parser.add_argument('--metric', '-m', type=str, default='capacity',
                        help='metric to calculate distance, options: generation and capacity. default is capacity')
    parser.add_argument('--runs_path', '-r', type=str,
                        help='location of run folder')
    parser.add_argument('--case_file', '-c', type=str,
                        help='location of csv file that includes all case names to compare. first row is base case')
    
    #args = parser.parse_args()
    #metric = args.metric                            # Metric to calculate distance: 'capacity', 'generation'
    #runs_path = args.runs_path                      # Path of runs folder.
    #case_file = args.case_file                      # Case file in csv that includes all case names to compare.
    
    ######################################### FOR TESTING/DEBUGGING #########################################
    metric = 'capacity'                                                               # Metric to calculate distance: 'capacity', 'generation'
    runs_path = '/Users/apham/Documents/GitHub/ReEDS/public_ReEDS/ReEDS/runs/rvs'     # Path of runs folder
    case_file = '/Users/apham/Documents/GitHub/ReEDS/public_ReEDS/ReEDS/rv_runs_test.csv'  # Case file in csv that includes all case names to compare
    #########################################################################################################
    
    # Read in data case file:
    case_file = pd.read_csv(case_file)
    optimal_case = case_file['old_prefix'].iloc[0]
    rv_cases = case_file['old_prefix'].iloc[1:].values.tolist()
    case_file['euclidean_distance'] = 0
    
    for case in rv_cases:
        output_path_rv = os.path.join(runs_path,case,'outputs')
        output_path_optimal = os.path.join(runs_path,optimal_case,'outputs')
        if metric == 'capacity':
            file = 'cap.csv'
        elif metric == 'generation':
            file = 'gen_ann.csv'
        data = pd.read_csv(os.path.join(output_path_rv,file))
        data_optimal = pd.read_csv(os.path.join(output_path_optimal,file)).rename(columns={'Value':'Value_opt'})

        data = data.merge(data_optimal, on=['i','r','t'], how='left')
        data = data.fillna(0)
        final_year = 2050
        data['distance'] = (data['Value']-data['Value_opt'])**2
        data = data[data['t']==final_year]
        euclidean_dist = data['distance'].sum()
        print(f"Case {case}'s distance from optimal: {euclidean_dist}")

        case_file.loc[case_file['old_prefix']==case,'euclidean_distance'] = euclidean_dist
    
    # Find the maximally different solution:
    case_file['max_diff_case'] = case_file.loc[case_file['euclidean_distance'].idxmax(), 'old_prefix']

    case_file.to_csv(os.path.join(runs_path,'case_diversity_metrics.csv'))    


######################################################################################################
#%% FUNCTIONS ###

main()
