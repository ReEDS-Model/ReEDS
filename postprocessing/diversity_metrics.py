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
    run_on = 'local'                                                    # kestrel vs local  
    metric = 'gen'                                                      # Metric to calculate distance:
                                                                        # 'cap', 'gen', 'weighted_gen', 'emission', 
                                                                        # 'weighted_emission', 'employment', 
                                                                        # 'weighted_employment'
    #submetrics = ['Solar PV','Land-based Wind','Offshore Wind','Gas','Coal','gentech']   # only if metric = cap or gen  
    submetrics = ['gentech']     
    year = 2050
    ed_or_hmsed = 'ED'                                                  # 'ED' or 'HMSED'
    number_of_max_diff_case = 100                                       # Only if ed_or_hmsed = 'HMSED'

    if run_on == 'local':
        dir = '/Users/apham/Documents/Projects/ReEDS_Projects/FY26/Uncertainty/MGA_Paper_2'
        runs_path = '/Users/apham/Documents/Projects/ReEDS_Projects/FY26/Uncertainty/MGA_Paper_2/runs'          # Path of runs folder
        case_file_orig = '/Users/apham/Documents/GitHub/ReEDS/public_ReEDS/ReEDS/rv_runs_all_completed.csv'  # Case file in csv that includes all case names to compare
    elif run_on == 'kestrel':
        dir = '/kfs2/projects/uncertainty/apham/ReEDS/runs'
        runs_path = '/kfs2/projects/uncertainty/apham/ReEDS/runs'                       # Path of runs folder
        case_file_orig = '/kfs2/projects/uncertainty/apham/ReEDS/uncertainty_plots_all_cases.csv'  # Case file in csv that includes all case names to compare
    #########################################################################################################
    
    # Read in data case file:
    case_file = pd.read_csv(case_file_orig)
    optimal_case = case_file['scenario'].iloc[0]
    rv_cases = case_file['scenario'].iloc[1:].values.tolist()
    min_max_cases = case_file[(case_file['scenario'].str.contains('min')) | 
                          (case_file['scenario'].str.contains('max'))]['scenario'].tolist()
    rv_cases = [x for x in rv_cases if x not in min_max_cases]

    if metric == 'cap':
        file = 'cap.csv'
    elif (metric == 'gen') | (metric == 'weighted_gen'):
        file = 'gen_ann.csv'
    elif (metric == 'emission') | (metric == 'weighted_emission'):
        file = 'emit_r.csv'
    elif (metric == 'employment') | (metric == 'weighted_employment'):
        file = 'employment_tot.csv'

    #data = data_clean(runs_path,case_file,file,year,metric)
    #data.to_csv(os.path.join(dir,'csv',metric+'.csv'),index=False)

    data = pd.read_csv(os.path.join(dir,'csv',metric+'.csv'))

    # Filter out chosen scenarios only:
    # Read in chosen scenarios:
    scenarios_chosen = pd.read_csv(os.path.join(reeds_path,'uncertainty_selected_cases.csv'))
    scenarios_chosen = scenarios_chosen['scenario'].unique().tolist()
    
    if ('emission' in metric) | ('employment' in metric):
        col = ["r"] + scenarios_chosen
    else:
        col = ["tech", "r"] + scenarios_chosen
    data_chosen = data[col]
    data_chosen.to_csv(os.path.join(dir,'csv',metric+'_chosen.csv'),index=False)

   
    for submetric in submetrics:
        if (submetric != 'gentech') & (('emission' not in metric) & ('employment' not in metric)):
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
        
        #rv_cases = [item for item in rv_cases if submetric in item]
        #case_file = case_file[case_file['scenario'].str.contains(submetric)]

        # Find maximally different solutions
        case_file = euclidean_distance_calc(runs_path, case_file, optimal_case, data, metric,
                                            rv_cases, submetric, file, year,number_of_max_diff_case,
                                            col_ED, rank_ED, col_HMSED, rank_HMSED, ed_or_hmsed)
        
        # Identify top most maximally different solutions

        if ed_or_hmsed == 'HMSED':
            max_diff_solutions = case_file.sort_values(by=rank_HMSED)
            max_diff_solutions = max_diff_solutions.loc[(max_diff_solutions[rank_HMSED]<=number_of_max_diff_case) & 
                                                        (max_diff_solutions[rank_HMSED]>0)]
            max_diff_solutions = max_diff_solutions[['scenario',col_HMSED,rank_HMSED]]
            max_diff_solutions.to_csv(os.path.join(runs_path,
                                                'top_'+str(number_of_max_diff_case) + 
                                                '_maximally_diff_solutions_'+submetric+'.csv'),
                                                index=False)
        elif ed_or_hmsed == 'ED':
            if ('emission' in metric) | ('employment' in metric):
                case_file.to_csv(os.path.join(dir,'csv',
                                            'ED_'+metric +'.csv'),
                                            index=False)
            else:
                case_file.to_csv(os.path.join(dir,'csv',
                                            'ED_'+metric + 
                                            '_'+submetric+'.csv'),
                                            index=False)
        
        # Calculate Gini index 
        if (metric == 'gen') | (metric == 'weighted_gen'):
            submetric_gini = 'gentech'
        
        case_file = gini_coefficient_cal(case_file, runs_path, data, metric, submetric_gini, file, year, col_gini)
        # Identify most spatially diverse solutions
        spatially_diff_solutions = case_file.sort_values(by=col_gini)
        spatially_diff_solutions = spatially_diff_solutions.iloc[:number_of_max_diff_case]
        # Append optimal solution if it is not included
        if optimal_case not in spatially_diff_solutions['scenario'].tolist():
            opt_solution = case_file[case_file['scenario']==optimal_case]
            spatially_diff_solutions = pd.concat([opt_solution, spatially_diff_solutions], ignore_index=True)


        spatially_diff_solutions = spatially_diff_solutions[['scenario',col_gini]]
        if ('emission' in metric) | ('employment' in metric):
                spatially_diff_solutions.to_csv(os.path.join(dir,'csv',
                                                        'Gini_' +metric+'.csv'),
                                                        index=False)
        else:
            spatially_diff_solutions.to_csv(os.path.join(dir,'csv',
                                                        'Gini_' +metric+ '_' + submetric_gini+'.csv'),
                                                        index=False)

        # Save all metrics
        case_file = case_file[['scenario',col_HMSED,rank_HMSED,col_gini]]
        case_file.to_csv(os.path.join(runs_path,'case_diversity_metrics_'+submetric+'.csv')) 

        ## Plot HMSED and gini index
        plot_HMSED_gini(runs_path, metric, submetric, rank_HMSED, col_HMSED, col_gini,
                        max_diff_solutions, spatially_diff_solutions)
        

######################################################################################################
#%% FUNCTIONS ###
def data_clean(runs_path,case_file,file,year,metric):
    population_fips = pd.read_csv(os.path.join(reeds_path,'inputs','disaggregation','county_population.csv'))
    county2zone = reeds.io.get_county2zone(GSw_ZoneSet='z54', as_map=False)
    county2zone['FIPS'] = 'p' + county2zone.FIPS
    county2zone = county2zone[['FIPS','r']]
    population_fips = population_fips.merge(county2zone, on='FIPS',how='left')
    population_r = population_fips.groupby(['r'], as_index=False).agg({'value': 'sum'}).rename(columns={'value':'population'})

    # Clean up and format raw data:
    data_scenario_base = pd.DataFrame()
    for scenario in case_file['scenario'].unique().tolist():
        data_scenario = pd.read_csv(os.path.join(runs_path,scenario,'outputs',file))
        data_scenario = data_scenario[data_scenario['t']==year].drop(columns='t')
        if 'emission' in metric:
            data_scenario = data_scenario[(data_scenario['eall']=='CO2') & (data_scenario['etype']=='process')]
            data_scenario = data_scenario[['r','Value']]
        elif 'employment' in metric:
            data_scenario = data_scenario[['r','Value']]
        else:
            data_scenario['i'] = data_scenario['i'].str.lower()
            tech_map = pd.read_csv(os.path.join(reeds_path,'postprocessing','tech_aggregation.csv')
                                ).rename(columns={'raw':'i','display_aggregated':'tech'}
                                            ).drop(columns=['display','diagnostics','ther_stor_vre'])
            tech_map.loc[tech_map['tech']=='Solar','tech'] = 'Solar PV'

            data_scenario = data_scenario.merge(tech_map,on='i',how='left')

            data_scenario.loc[data_scenario['i'].str.contains('upv'),'tech'] = 'Solar PV'
            data_scenario.loc[data_scenario['i'].str.contains('wind-ons'),'tech'] = 'Land-based Wind'
            data_scenario.loc[data_scenario['i'].str.contains('wind-ofs'),'tech'] = 'Offshore Wind'
            data_scenario.loc[data_scenario['i'].str.contains('geohydro_allkm'),'tech'] = 'Geothermal'
            data_scenario.loc[data_scenario['i'].str.contains('egs'),'tech'] = 'Geothermal'
            data_scenario.loc[data_scenario['i'].isin(['hydnd','hydud','hydund','hydnpnd','hyded','hydend']),'tech'] = 'Hydro'

            data_scenario = data_scenario.groupby(['tech','r'], as_index=False).agg({'Value': 'sum'})
            data_scenario = data_scenario[data_scenario['tech']!='Remove']
        
        if 'weighted' in metric:
            if 'emission' in metric:
                data_scenario.loc[data_scenario['Value']<0,'Value'] = 0
            data_scenario = data_scenario.merge(population_r,on='r',how='left')
            data_scenario['Value'] = data_scenario['Value']/data_scenario['population']
            data_scenario = data_scenario.drop(columns='population')
        data_scenario = data_scenario.rename(columns={'Value':scenario})
        if 'Optimal' in scenario:
            data_scenario_base = data_scenario.copy()
        else:
            if ('emission' in metric ) | ('employment' in metric ):
                data_scenario_base = data_scenario_base.merge(data_scenario,on=['r'],how='outer')
            else:
                data_scenario_base = data_scenario_base.merge(data_scenario,on=['tech','r'],how='outer')
            data_scenario_base = data_scenario_base.fillna(0)

    return data_scenario_base
        
def euclidean_distance_calc(runs_path, case_file, optimal_case, data_all, metric,
                            rv_cases, submetric, file, year, number_of_max_diff_case,
                            col_ED, rank_ED, col_HMSED, rank_HMSED, ed_or_hmsed):
    
    if ('emission' in metric) | ('employment' in metric):
        data_optimal = data_all[['r',optimal_case]]
    else:
        data_optimal = data_all[['tech','r',optimal_case]]

    case_file[col_ED] = 0
    case_file[rank_ED] = 0
    case_file[col_HMSED] = 0   
    case_file[rank_HMSED] = 0  
    
    data_rv = data_optimal
    for case in rv_cases:
        print(f"Calculate ED from optimal for {case}")
        
        if ('emission' in metric) | ('employment' in metric):
            data = data_all[['r',case]]
            data_rv = data_rv.merge(data, on='r', how='outer')
            data_rv = data_rv.fillna(0)
        else:
            data = data_all[['tech','r',case]]
            data_rv = data_rv.merge(data, on=['tech','r'], how='outer')
            data_rv = data_rv.fillna(0)

            if submetric != 'gentech':
                data_rv = data_rv[data_rv['tech'].str.contains(submetric)]
        
        data_rv = data_rv.reset_index().drop(columns='index')

        # calculate euclidean distance (ED) to identify solution that 
        # is furthest away from cost-optimal
        # ED formula from https://doi.org/10.1016/j.energy.2017.03.043 
        sum_diff = 0
        for i in list(range(len(data_rv[case]))):
            sum_diff += (data_rv[case][i]-data_rv[optimal_case][i])**2
        ed = sum_diff
        
        # another way
        #data_rv['distance'] = (data_rv[case]-data_rv[optimal_case])**2
        #euclidean_dist = data_rv['distance'].sum()
        #print(f"Case {case}'s distance from optimal: {euclidean_dist}")
        
        case_file.loc[case_file['scenario']==case,col_ED] = ed

    case_file[rank_ED] = 0
    case_file.loc[case_file['scenario']==case_file.loc[case_file[col_ED].idxmax(), 'scenario'], rank_ED] = 1
    case_file.loc[(case_file[rank_ED]!=1) & (case_file['scenario']!=optimal_case), rank_ED] = 9999999

    case_file.loc[case_file[rank_ED]==1,col_HMSED] = case_file.loc[case_file[rank_ED]==1,col_ED].iloc[0]
    case_file.loc[case_file[rank_ED]==1,rank_HMSED] = case_file.loc[case_file[rank_ED]==1,rank_ED].iloc[0]

    if ed_or_hmsed == 'HMSED':
        # calculate harmonic mean squared of euclidean distance (HMSED) 
        # to find the next number_of_max_diff_case maximally different solutions
        # HMSED formula from https://doi.org/10.1016/j.energy.2017.03.043 
        #for case_max_diff in list(range(len(rv_cases)-1)):
        for case_max_diff in list(range(number_of_max_diff_case)):
            print(f"{case_max_diff} maximally different solution(s) in terms of {submetric}")
            
            # set of selected cases (cost+optimal + previous maximally different scenarios)
            rv_cases_i = case_file.loc[case_file[rank_ED]>case_max_diff+1, 'scenario'].tolist()
            # set of random vector cases to calculate HMSED
            sel_cases_i = [x for x in case_file['scenario'].tolist() if x not in rv_cases_i]

            # calculate HMSED from each case in set of rv cases to set of selected cases:
            inverse_sum_diff = 0
            for i in rv_cases_i:
                for j in sel_cases_i:
                    inverse_sum_diff += 1/sum((data_rv[i]-data_rv[j])**2)
                inverse_sum_diff_i = inverse_sum_diff**(-1)
                case_file.loc[case_file['scenario']==i,col_HMSED] = inverse_sum_diff_i 
            max_diff_case = case_file.loc[case_file['scenario'].isin(rv_cases_i)]
            max_diff_case = max_diff_case.loc[max_diff_case[col_HMSED].idxmax(), 'scenario']
            case_file.loc[case_file['scenario']==max_diff_case, rank_HMSED] = case_max_diff + 2
            case_file.loc[case_file['scenario']==max_diff_case, rank_ED] = case_file[rank_HMSED]

    return case_file

def gini_coefficient_cal(case_file, runs_path, data_all, metric, submetric, file, year, col_gini):

    case_file[col_gini] = 0    
    
    for case in case_file['scenario'].unique().tolist():        
        if ('emission' in metric) | ('employment' in metric):
            data = data_all[['r',case]]
        else:    
            data = data_all[['tech','r',case]]
            if submetric != 'gentech':
                data = data[data['tech'].str.contains(submetric)]
            data = data.drop(columns='tech')
            data = data.groupby(['r'], as_index=False).agg({case: 'sum'})
        
        # Calculate gini coefficient based on classical definition from
        # https://www.statsdirect.com/help/nonparametric_methods/gini.htm (first formula)
        # gini index = (sum(i,j) |x_i-x_j|)/(2*n^2*mean(x))
        sum_diff = 0
        for i, xi in enumerate(data[case][:-1],1):
            sum_diff += np.sum(np.abs(xi-data[case][i:]))
        gini = sum_diff / (len(data[case])**2 * np.mean(data[case]))
    
        case_file.loc[case_file['scenario']==case,col_gini] = gini  

    return case_file  

def plot_HMSED_gini(runs_path, metric, submetric, rank_HMSED, col_HMSED, col_gini,
                    max_diff_solutions, spatially_diff_solutions):
    color_techs = {'coal':'#222222','gas':'#52216B',
                        'nuclear':'#820000','storage':'#CC0079',
                        'pv':'#FFC903','wind-ons':'#00B6EF',
                        'wind-ofs':'#106BA7', 'gentech':'C3'}
    titles = {'coal': 'Coal', 'gas':'Gas', 'nuclear':'Nulear',
                'wind-ons':'Land-based wind','wind-ofs':'Offshore wind',
                'pv':'Solar PV','gentech':'Generating technologies'}
    # Plot HMSED
    #max_diff_solutions = pd.read_csv(os.path.join(runs_path,'top_100_maximally_diff_solutions_pv.csv'))
    hmsed_output = max_diff_solutions[~max_diff_solutions['scenario'].str.contains('Optimal')]
    fig,ax = plt.subplots(figsize=(6,3))
    ax.plot(hmsed_output[rank_HMSED].values, hmsed_output[col_HMSED].values, alpha=1,
            color=color_techs[submetric], linewidth=1.5)
    ax.tick_params(axis='both', which='major', width=0.5, length=1.5, pad=2)
    ax.tick_params(axis='both', which='minor', width=0.3, length=1, pad=2)
    ax.tick_params(top=False, right=False)
    #ax.tick_params(axis='x', labelrotation=90)
    ax.tick_params(labelsize=11)
    ax.set_ylabel('HMSED', fontsize=12,fontweight='bold',fontname="Arial", labelpad=2)
    ax.set_xlabel('MGA sample number', fontsize=12,fontweight='bold',fontname="Arial", labelpad=2)
    ax.set_title(titles[submetric] + ' ' + metric + ', 2050',
                    fontsize=13,fontweight='bold',fontname="Arial",pad=0)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.grid(color='lightgray', linestyle='dashed', linewidth=0.5, axis='y',zorder=0)
    fig.savefig(os.path.join(runs_path,'HMSED_'+submetric+'.png'), dpi=600, bbox_inches='tight')

    # Plot gini index
    #spatially_diff_solutions = pd.read_csv(os.path.join(runs_path,'top_100_spatially_diff_solutions_pv.csv'))
    gini_output = spatially_diff_solutions[~spatially_diff_solutions['scenario'].str.contains('Optimal')]
    gini_output_sorted = gini_output.sort_values(by=col_gini, ascending=False)
    gini_output_sorted = gini_output_sorted.reset_index()
    gini_output_sorted['sample'] = gini_output_sorted.index + 1
    fig,ax = plt.subplots(figsize=(6,3))
    ax.plot(gini_output_sorted['sample'].values, gini_output_sorted[col_gini].values, alpha=1,
            color=color_techs[submetric], linewidth=1.5)
    ax.tick_params(axis='both', which='major', width=0.5, length=1.5, pad=2)
    ax.tick_params(axis='both', which='minor', width=0.3, length=1, pad=2)
    ax.tick_params(top=False, right=False)
    #ax.set_ylim(0,1)
    #ax.tick_params(axis='x', labelrotation=90)
    ax.tick_params(labelsize=11)
    ax.set_ylabel('Gini coefficient', fontsize=12,fontweight='bold',fontname="Arial", labelpad=2)
    ax.set_xlabel('MGA sample number', fontsize=12,fontweight='bold',fontname="Arial", labelpad=2)
    ax.set_title(titles[submetric] + ' ' + metric + ', 2050',
                    fontsize=13,fontweight='bold',fontname="Arial",pad=0)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.grid(color='lightgray', linestyle='dashed', linewidth=0.5, axis='y',zorder=0)
    fig.savefig(os.path.join(runs_path,'gini_'+submetric+'.png'), dpi=600, bbox_inches='tight')

main()
