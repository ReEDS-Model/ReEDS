#%% Imports
import pandas as pd
import numpy as np
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
    submetrics = ['pv','all']           
    year = 2050
    number_of_max_diff_case = 10
    #runs_path = '/Users/apham/Documents/GitHub/ReEDS/public_ReEDS/ReEDS/runs/rvs'     # Path of runs folder
    #case_file = '/Users/apham/Documents/GitHub/ReEDS/public_ReEDS/ReEDS/rv_runs_test.csv'  # Case file in csv that includes all case names to compare
    runs_path = '/kfs2/projects/uncertainty/apham/ReEDS/runs'     # Path of runs folder
    case_file = '/kfs2/projects/uncertainty/apham/ReEDS/rv_runs_pv_completed.csv'  # Case file in csv that includes all case names to compare
    #########################################################################################################
    
    # Read in data case file:
    case_file = pd.read_csv(case_file)
    optimal_case = case_file['old_prefix'].iloc[0]
    rv_cases = case_file['old_prefix'].iloc[1:].values.tolist()
    case_file['euclidean_distance'] = 0
    case_file['rank'] = 0
    case_file['euclidean_distance_pv'] = 0
    case_file['euclidean_distance_wind-ons'] = 0
    case_file['euclidean_distance_wind-ofs'] = 0
    case_file['euclidean_distance_coal'] = 0
    case_file['euclidean_distance_gas'] = 0
    case_file['euclidean_distance_nuclear'] = 0
    case_file['rank_pv'] = 0
    case_file['rank_wind-ons'] = 0
    case_file['rank_wind-ofs'] = 0
    case_file['rank_coal'] = 0
    case_file['rank_gas'] = 0
    case_file['rank_nuclear'] = 0
    case_file['gini_pv'] = 0
    case_file['gini_wind-ons'] = 0
    case_file['gini_wind-ofs'] = 0
    case_file['gini_coal'] = 0
    case_file['gini_gas'] = 0
    case_file['gini_nuclear'] = 0
    
    for submetric in submetrics:
        # Find the maximally different solution from optimal solution:
        case_file = euclidean_distance_calc(runs_path, case_file, optimal_case, rv_cases, metric, submetric, year)
        if submetric =='all':
            col = 'euclidean_distance'
            rank = 'rank'
        else:
            col = 'euclidean_distance_'+submetric
            rank = 'rank_'+submetric
        case_file.loc[case_file['old_prefix']==case_file.loc[case_file[col].idxmax(), 'old_prefix'], rank] = 1
        
        # Calculate Gini index
        if submetric == 'all':
            continue
        else:
            case_file = gini_coefficient_cal(case_file, runs_path, metric, submetric, year)
            
                
    

    # Find the next number_of_max_diff_case maximallty different solutions from 
    # optimal solution and maximally different solutions so far
    #for i in list(range(number_of_max_diff_case)):
    #    rv_cases_i = rv_cases.remove(case_file.loc[case_file['rank']>i, 'old_prefix'])
    #    sel_cases_i = optimal_case.append(case_file.loc[case_file['rank']>i, 'old_prefix'])

    

    case_file.to_csv(os.path.join(runs_path,'case_diversity_metrics.csv'))    


######################################################################################################
#%% FUNCTIONS ###
def euclidean_distance_calc(runs_path, case_file, optimal_case, rv_cases, metric, submetric, year):
    for case in rv_cases:
        print(case)
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
        data['distance'] = (data['Value']-data['Value_opt'])**2
        data = data[data['t']==year]
        if submetric != 'all':
            data = data[data['i'].str.contains(submetric)]

        euclidean_dist = data['distance'].sum()
        #print(f"Case {case}'s distance from optimal: {euclidean_dist}")
        if submetric == 'all':
            col = 'euclidean_distance'
        else:
            col = 'euclidean_distance_'+submetric
        case_file.loc[case_file['old_prefix']==case,col] = euclidean_dist
    return case_file

def gini_coefficient_cal(case_file, runs_path, metric, submetric, year):
    for case in case_file['old_prefix'].unique().tolist():
        if metric == 'capacity':
            file = 'cap.csv'
        elif metric == 'generation':
            file = 'gen_ann.csv'

        output_path_gi = os.path.join(runs_path,case,'outputs')    
        data = pd.read_csv(os.path.join(output_path_gi,file))
        data = data[data['t']==year]
        data = data[data['i'].str.contains(submetric)]
        data = data.drop(columns=['i','t'])
        data = data.groupby(['r'], as_index=False).agg({'Value': 'sum'})

        total = 0
        for i, xi in enumerate(data['Value'][:-1],1):
            total += np.sum(np.abs(xi-data['Value'][i:]))
            gini = total / (len(data['Value'])**2 * np.mean(data['Value']))
        col = 'gini_'+submetric
        case_file.loc[case_file['old_prefix']==case,col] = gini  

    return case_file  
    
main()
