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
    submetrics = ['pv','wind-ons','wind-ofs','gas','coal','all']           
    year = 2050
    number_of_max_diff_case = 2
    runs_path = '/Users/apham/Documents/GitHub/ReEDS/public_ReEDS/ReEDS/runs/rvs'     # Path of runs folder
    case_file = '/Users/apham/Documents/GitHub/ReEDS/public_ReEDS/ReEDS/rv_runs_test.csv'  # Case file in csv that includes all case names to compare
    #runs_path = '/kfs2/projects/uncertainty/apham/ReEDS/runs'     # Path of runs folder
    #case_file = '/kfs2/projects/uncertainty/apham/ReEDS/rv_runs_gentech_completed.csv'  # Case file in csv that includes all case names to compare
    #########################################################################################################
    
    # Read in data case file:
    case_file = pd.read_csv(case_file)
    optimal_case = case_file['scenario'].iloc[0]
    rv_cases = case_file['scenario'].iloc[1:].values.tolist()
    
    for submetric in submetrics:
        # Find maximally different solutions
        case_file = euclidean_distance_calc(runs_path, case_file, optimal_case, rv_cases, 
                                            number_of_max_diff_case, metric, submetric, year)
        
        # Calculate Gini index and final most spatially diverse solutions
        if submetric == 'all':
            continue
        else:
            case_file = gini_coefficient_cal(case_file, runs_path, metric, submetric, year)

    case_file.to_csv(os.path.join(runs_path,'case_diversity_metrics.csv'))    


######################################################################################################
#%% FUNCTIONS ###
def euclidean_distance_calc(runs_path, case_file, optimal_case, rv_cases, 
                            number_of_max_diff_case, metric, submetric, year):
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
        data = data[data['t']==year]

        if submetric != 'all':
            data = data[data['i'].str.contains(submetric)]
            col = 'ED_'+submetric
            rank = 'rank_'+submetric
        else:
            col = 'ED'
            rank = 'rank'
        
        data = data.reset_index().drop(columns='index')

        # calculate euclidean distance (ED) to identify solution that 
        # is furthest away from cost-optimal
        # ED formula from https://doi.org/10.1016/j.energy.2017.03.043 
        sum_diff = 0
        for i in list(range(len(data['Value']))):
            sum_diff += (data['Value'][i]-data['Value_opt'][i])**2
        ed = sum_diff

        #data['distance'] = (data['Value']-data['Value_opt'])**2
        #euclidean_dist = data['distance'].sum()
        #print(f"Case {case}'s distance from optimal: {euclidean_dist}")
       
        case_file[col] = 0
        case_file.loc[case_file['scenario']==case,col] = ed
        case_file[rank] = 0
        case_file.loc[case_file['scenario']==case_file.loc[case_file[col].idxmax(), 'scenario'], rank] = 1
        case_file.loc[(case_file[rank]!=1) & (case_file['scenario']!=optimal_case), rank] = 999

        # calculate harmonic mean squared of euclidean distance (HMSED) 
        # to find the next number_of_max_diff_case maximallty different solutions
        # HMSED formula from https://doi.org/10.1016/j.energy.2017.03.043 
        # only calculate HMSED if number_of_max_diff_case > 1 
        if number_of_max_diff_case > 1:
            for i in list(range(number_of_max_diff_case)):
                
                # set of selected cases (cost+optimal + previous maximally different scenarios)
                sel_cases_i = case_file.loc[case_file[rank]>i+1, 'scenario'].tolist()
                # set of random vector cases to calculate HMSED
                rv_cases_i = [x for x in case_file['scenario'].tolist() if x not in sel_cases_i]

                # calculate HMSED from each case in set of rv cases to set of selected cases:
                inverse_sum_diff = 0
                for i in rv_cases_i:
                    for j in sel_cases_i:
                        inverse_sum_diff += (data['Value'][i]-data['Value_opt'][i])**2
                ed = sum_diff


                
    return case_file

def gini_coefficient_cal(case_file, runs_path, metric, submetric, year):
    for case in case_file['scenario'].unique().tolist():
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
        
        # Calculate gini coefficient based on classical definition from
        # https://www.statsdirect.com/help/nonparametric_methods/gini.htm (first formula)
        # gini index = (sum(i,j) |x_i-x_j|)/(2*n^2*mean(x))
        sum_diff = 0
        for i, xi in enumerate(data['Value'][:-1],1):
            sum_diff += np.sum(np.abs(xi-data['Value'][i:]))
        gini = sum_diff / (len(data['Value'])**2 * np.mean(data['Value']))
        
        col = 'gini_'+submetric
        case_file[col] = 0
        case_file.loc[case_file['scenario']==case,col] = gini  

    return case_file  
    
main()
