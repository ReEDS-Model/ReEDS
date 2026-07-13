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
    number_of_max_diff_case = 100
    #runs_path = '/Users/apham/Documents/GitHub/ReEDS/public_ReEDS/ReEDS/runs/rvs'     # Path of runs folder
    #case_file = '/Users/apham/Documents/GitHub/ReEDS/public_ReEDS/ReEDS/rv_runs_test.csv'  # Case file in csv that includes all case names to compare
    runs_path = '/kfs2/projects/uncertainty/apham/ReEDS/runs'     # Path of runs folder
    case_file = '/kfs2/projects/uncertainty/apham/ReEDS/rv_runs_all_completed.csv'  # Case file in csv that includes all case names to compare
    #########################################################################################################
    
    # Read in data case file:
    case_file = pd.read_csv(case_file)
    optimal_case = case_file['scenario'].iloc[0]
    rv_cases = case_file['scenario'].iloc[1:].values.tolist()

    if metric == 'capacity':
        file = 'cap.csv'
    elif metric == 'generation':
        file = 'gen_ann.csv'
   
    
    for submetric in submetrics:
        if submetric != 'all':
            col_ED = 'ED_'+submetric
            rank_ED = 'ED_rank_'+submetric
            col_HMSED = 'HMSED_'+submetric
            rank_HMSED = 'HMSED_rank_'+submetric
            col_gini = 'gini_'+submetric
        else:
            col_ED = 'ED'
            rank_ED = 'ED_rank'
            col_HMSED = 'HMSED'
            rank_HMSED = 'HMSED_rank'
            col_gini = 'gini' 
        
        # Find maximally different solutions
        case_file = euclidean_distance_calc(runs_path, case_file, optimal_case, 
                                            rv_cases, submetric, file, year,number_of_max_diff_case,
                                            col_ED, rank_ED, col_HMSED, rank_HMSED)
        
        # Identify top most maximally different solutions
        max_diff_solutions = case_file.sort_values(by=rank_HMSED)
        max_diff_solutions = max_diff_solutions.loc[max_diff_solutions[rank_HMSED]<=number_of_max_diff_case]
        max_diff_solutions = max_diff_solutions[['scenario',col_HMSED,rank_HMSED]]
        max_diff_solutions.to_csv(os.path.join(runs_path,'top_'+str(number_of_max_diff_case) + '_maximally_diff_solutions_'+submetric+'.csv'))
        
        # Calculate Gini index 
        if submetric == 'all':
            continue
        else:
            case_file = gini_coefficient_cal(case_file, runs_path, submetric, file, year, col_gini)
        # Identify most spatially diverse solutions
        spatially_diff_solutions = case_file.sort_values(by=col_gini)
        spatially_diff_solutions = spatially_diff_solutions.iloc[:number_of_max_diff_case]
        # Append optimal solution if it is not included
        if optimal_case not in spatially_diff_solutions['scenario'].tolist():
            opt_solution = case_file[case_file['scenario']==optimal_case]
            spatially_diff_solutions = pd.concat([opt_solution, spatially_diff_solutions], ignore_index=True)


        spatially_diff_solutions = spatially_diff_solutions[['scenario',col_gini]]
        spatially_diff_solutions.to_csv(os.path.join(runs_path,'top_'+str(number_of_max_diff_case) + '_spatially_diff_solutions_'+submetric+'.csv'))

        # Save all metrics
        case_file = case_file[['scenario',col_HMSED,rank_HMSED,col_gini]]
        case_file.to_csv(os.path.join(runs_path,'case_diversity_metrics_'+submetric+'.csv')) 

        # Plot HMSED and gini index  


######################################################################################################
#%% FUNCTIONS ###
def euclidean_distance_calc(runs_path, case_file, optimal_case,
                            rv_cases, submetric, file, year, number_of_max_diff_case,
                            col_ED, rank_ED, col_HMSED, rank_HMSED):

    output_path_optimal = os.path.join(runs_path,optimal_case,'outputs')
    data_optimal = pd.read_csv(os.path.join(output_path_optimal,file)).rename(columns={'Value':optimal_case})

    case_file[col_ED] = 0
    case_file[rank_ED] = 0
    case_file[col_HMSED] = 0   
    case_file[rank_HMSED] = 0  
    
    data_rv = data_optimal
    for case in rv_cases:
        print(case)
        output_path_rv = os.path.join(runs_path,case,'outputs')
          
        data = pd.read_csv(os.path.join(output_path_rv,file)).rename(columns={'Value':case})
        
        data_rv = data_rv.merge(data, on=['i','r','t'], how='outer')
        data_rv = data_rv.fillna(0)
        data_rv_sub = data_rv[data_rv['t']==year]
        if submetric != 'all':
            data_rv_sub = data_rv_sub[data_rv_sub['i'].str.contains(submetric)]
        
        data_rv_sub = data_rv_sub.reset_index().drop(columns='index')

        # calculate euclidean distance (ED) to identify solution that 
        # is furthest away from cost-optimal
        # ED formula from https://doi.org/10.1016/j.energy.2017.03.043 
        sum_diff = 0
        for i in list(range(len(data_rv_sub[case]))):
            sum_diff += (data_rv_sub[case][i]-data_rv_sub[optimal_case][i])**2
        ed = sum_diff
        
        # another way
        #data_rv_sub['distance'] = (data_rv_sub['Value']-data_rv_sub['Value_opt'])**2
        #euclidean_dist = data_rv_sub['distance'].sum()
        #print(f"Case {case}'s distance from optimal: {euclidean_dist}")
        
        case_file.loc[case_file['scenario']==case,col_ED] = ed

    case_file[rank_ED] = 0
    case_file.loc[case_file['scenario']==case_file.loc[case_file[col_ED].idxmax(), 'scenario'], rank_ED] = 1
    case_file.loc[(case_file[rank_ED]!=1) & (case_file['scenario']!=optimal_case), rank_ED] = 9999999

    case_file.loc[case_file[rank_ED]==1,col_HMSED] = case_file.loc[case_file[rank_ED]==1,col_ED].iloc[0]
    case_file.loc[case_file[rank_ED]==1,rank_HMSED] = case_file.loc[case_file[rank_ED]==1,rank_ED].iloc[0]

    # calculate harmonic mean squared of euclidean distance (HMSED) 
    # to find the next number_of_max_diff_case maximally different solutions
    # HMSED formula from https://doi.org/10.1016/j.energy.2017.03.043 
    #for case_max_diff in list(range(len(rv_cases)-1)):
    for case_max_diff in list(range(number_of_max_diff_case)):
        
        # set of selected cases (cost+optimal + previous maximally different scenarios)
        rv_cases_i = case_file.loc[case_file[rank_ED]>case_max_diff+1, 'scenario'].tolist()
        # set of random vector cases to calculate HMSED
        sel_cases_i = [x for x in case_file['scenario'].tolist() if x not in rv_cases_i]

        # calculate HMSED from each case in set of rv cases to set of selected cases:
        inverse_sum_diff = 0
        for i in rv_cases_i:
            for j in sel_cases_i:
                inverse_sum_diff += 1/sum((data_rv_sub[i]-data_rv_sub[j])**2)
            inverse_sum_diff_i = inverse_sum_diff**(-1)
            case_file.loc[case_file['scenario']==i,col_HMSED] = inverse_sum_diff_i 
        max_diff_case = case_file.loc[case_file['scenario'].isin(rv_cases_i)]
        max_diff_case = max_diff_case.loc[max_diff_case[col_HMSED].idxmax(), 'scenario']
        case_file.loc[case_file['scenario']==max_diff_case, rank_HMSED] = case_max_diff + 2
        case_file.loc[case_file['scenario']==max_diff_case, rank_ED] = case_file[rank_HMSED]

    return case_file

def gini_coefficient_cal(case_file, runs_path, submetric, file, year, col_gini):

    case_file[col_gini] = 0    
    
    for case in case_file['scenario'].unique().tolist():
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
    
        case_file.loc[case_file['scenario']==case,col_gini] = gini  

    return case_file  
    
main()
