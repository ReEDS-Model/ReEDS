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
    parser.add_argument('--crpyears', '-y', type=int, default=20, 
                        help='crpyears, default is 20')
    parser.add_argument('--format', '-f', type=str, default='png',
                        help='format of output plots, options are .png and .pdf')
    parser.add_argument('--save', '-s', action="store_true",
                        help='save calculated euclidean distances to csv.')
    args = parser.parse_args()
    
    core_metric_parameter = args.metric             # Metric to calculate distance: 'capacity', 'generation'
    figure_format = args.format                     # 'png' or 'pdf'
    save_data = args.save                           # Save calculated euclidean distances to csv.
    
    ######################################### FOR TESTING/DEBUGGING #########################################
    # atb_version = 2024                              # ATB version
    # core_metric_parameter = 'CAPEX'                 # Metric to plot: 'CAPEX', 'Fixed O&M','Variable O&M'
    # crpyears = 20
    # atb_inputs = 'url'                              # Read in ATBe.csv input file from 'url' or 'local' inputs folder 
                                                      # (if a version of ATB is not yet available online, read from 'inputs')
                                                      # Link to past ATBe versions: https://data.openei.org/s3_viewer?bucket=oedi-data-lake&prefix=ATB%2Felectricity%2Fcsv%2F&limit=50
                                                      # 2024 atb_path = 'https://oedi-data-lake.s3.amazonaws.com/ATB/electricity/csv/2024/v3.0.0/ATBe.csv'
                                                      # 2025 atb is not yet available online, so only option is reading it from inputs folder.
    # figure_format = 'png'                           # 'png' or 'pdf'
    # save_data = False                               # Print the version of ATBe that has been cleaned and ready for plotting to csv
    #########################################################################################################
    
    # Specify dollar year:
    if atb_version == 2024:
        dollar_year = 2022
    elif atb_version == 2025:
        dollar_year = 2023

    # Get the path for ATB data and clean the data:
    (inputs_path, atb_path, figures_path) = read_path(atb_inputs, atb_version)
    (technologies, dfplot) = clean_atb_data(atb_inputs, atb_path, atb_version, core_metric_parameter, crpyears)
    if save_data:
        print("Saving the version of ATBe that has been cleaned and ready for plotting to csv file...")
        dfplot.to_csv(os.path.join(inputs_path, "ATB_"+str(atb_version)+"_cleaned.csv"))

    # Define plot attributes:
    (traces, colors, tracelabels, legendtitle, plottitle) = plot_attributes(inputs_path, atb_version)

    # Plot ATB:
    plot_atb(figures_path, atb_version, technologies, dfplot, traces, colors, legendtitle, plottitle, 
             tracelabels, core_metric_parameter, figure_format, dollar_year)
    
######################################################################################################
#%% FUNCTIONS ###
def read_path(atb_inputs, atb_version):
    # Iputs path:
    inputs_path = os.path.join(os.getcwd(),'inputs')
    if not os.path.exists(inputs_path):
        os.makedirs(inputs_path)

    # ATB path:
    if atb_inputs == 'url':
        print('\nYou choose to read ATBe '+str(atb_version) + ' file from an URL.')
        user_input = input('\nPlease enter the URL to the ATBe '+str(atb_version) + ' file here to continue: ')
        atb_path = user_input
    elif atb_inputs == 'local':
        print('\nYou choose to read ATBe_'+str(atb_version)+ '.csv file from local "inputs" folder.')
        atb_path = os.path.join(inputs_path,'ATBe_'+str(atb_version)+'.csv')
    
    # Figures path:
    figures_path = os.path.join(os.getcwd(),'figures')
    if not os.path.exists(figures_path):
        os.makedirs(figures_path)

    return (inputs_path, atb_path, figures_path)

def clean_atb_data(atb_inputs, atb_path, atb_version, core_metric_parameter, crpyears):
    # Read ATB data
    try:
        atb = pd.read_csv(atb_path, index_col=0, low_memory=False)
    except Exception:
        if atb_inputs == 'url':
            raise FileNotFoundError('URL is incorrect')
        elif atb_inputs == 'local':
            raise FileNotFoundError('ATBe file is missing or incorrect. Please provide data file with name ATBe_' + str(atb_version) + '.csv in the "inputs" folder.')
    atb.technology.unique()
    
    # Use 'Market' case for 2024 version, which is equivalent to 'Exp + TC' in 2025 version
    if atb_version == 2024:
        core_metric_case = 'Market'
    elif atb_version == 2025:
        core_metric_case = 'Exp + TC'

    # Technology to plot
    technologies = [
        'Biopower',
        'Coal_FE',
        'CSP',
        'Geothermal',
        'LandbasedWind',
        'NaturalGas_FE',
        'Nuclear',
        'OffShoreWind',
        'Utility-Scale Battery Storage',
        'UtilityPV',
    #     'CommPV',
    #     'Hydropower',
    #     'Pumped Storage Hydropower',
    #     'ResPV',
    #     'Utility-Scale PV-Plus-Battery',
    #     'Commercial Battery Storage',
    #     'Residential Battery Storage',
    ]
    
    # Clean the raw ATB data in the right format for plotting
    dictplot = {}
    keepcols = ['technology','techdetail','scenario','core_metric_variable','value']
    for technology in technologies:
        # In ATB 2025 version, some technologies do not have 'Exp + TC' case, so use 'R&D' for them
        if atb_version == 2025:
            if technology in [
                'Biopower',
                'Coal_FE',
                'CSP',
                'Geothermal',
                'NaturalGas_FE',
                'Nuclear',
                'OffShoreWind',
            ]:
                core_metric_case = 'R&D'
            else:
                core_metric_case = 'Exp + TC'
        
        dictplot[technology] = atb.loc[
            (atb.technology==technology)
            & (atb.core_metric_parameter==core_metric_parameter)
            & (atb.core_metric_case==core_metric_case)
            & (atb.crpyears==crpyears)
            # & (atb.techdetail==techdetail)
            # & (atb.core_metric_variable==2050)
            , keepcols
        ]
    dfplot = pd.concat(dictplot, ignore_index=True).set_index('technology')
    
    return (technologies, dfplot)

def plot_attributes(inputs_path, atb_version):
    cm = plt.cm.coolwarm
    cm = plt.cm.RdBu
    d = 0.06
    # traces setting
    with open(os.path.join(inputs_path,"traces_"+str(atb_version)+".json")) as file:
        traces = json.load(file)
    # tracelabels setting
    with open(os.path.join(inputs_path,"tracelabels.json")) as file:
        tracelabels = json.load(file)

    # colors setting
    with open(os.path.join(inputs_path,"colors.json")) as file:
        colors = json.load(file)
    # add colors for offshore wind classes
    colors["OffShoreWind"] = {
            'Class1': cm(0.),
            'Class2': cm(d),
            'Class3': cm(2*d),
            'Class4': cm(3*d),
            'Class5': cm(4*d),
            'Class6': cm(5*d),
            'Class7': cm(6*d),
            'Class8': cm(1.),
            'Class9': cm(1-d),
            'Class10': cm(1-d*2),
            'Class11': cm(1-d*3),
            'Class12': cm(1-d*4),
            'Class13': cm(1-d*5),
            'Class14': cm(1-d*6),
        }   

    legendtitle = {
        'UtilityPV':None,
        'Nuclear':None,
        'LandbasedWind':None,
        'Biopower':None,
        'CSP':None,
        'Utility-Scale Battery Storage': 'Duration\n[hours]',
        'OffShoreWind': 'Class',
        'NaturalGas_FE': None,
        'Coal_FE': None,
        'Geothermal': None,
    }

    plottitle = {
        'UtilityPV':'Utility PV',
        'Nuclear':'Nuclear',
        'LandbasedWind':'Land-based wind',
        'Biopower':'Biopower',
        'CSP':'CSP',
        'Utility-Scale Battery Storage': 'Utility battery',
        'OffShoreWind': 'Offshore wind',
        'NaturalGas_FE': 'Natural gas',
        'Coal_FE': 'Coal',
        'Geothermal': 'Geothermal',
    }
    return (traces, colors, tracelabels, legendtitle, plottitle)

def plot_atb(figures_path, atb_version, technologies, dfplot, traces, colors, legendtitle, plottitle, 
             tracelabels, core_metric_parameter, figure_format, dollar_year):
    
    # Set up number of panels for figure
    alpha = 0.4
    nrows, ncols = 2, 5
    coords = dict(zip(
        technologies,
        [(row, col) for row in range(nrows) for col in range(ncols)]
    ))

    # Plot the figure
    plt.close()
    f,ax = plt.subplots(
        nrows, ncols, figsize=(13,8), sharex=True, sharey=True,
        # gridspec_kw={'wspace':1.0, 'hspace':0.2},
        gridspec_kw={'hspace':0.25},
    )

    for technology in technologies:
        df = {}
        #scenarios = ['Moderate'] if technology == 'Nuclear' else ['Moderate', 'Advanced', 'Conservative']
        scenarios = ['Moderate', 'Advanced', 'Conservative']
        for scenario in scenarios:
            df[scenario] = (
                dfplot
                .loc[dfplot.scenario==scenario]
                .loc[technology]
                .pivot(columns='techdetail',index='core_metric_variable',values='value')
            )[traces[technology]]
        ### Central
        for trace in df['Moderate']:
            ax[coords[technology]].plot(
                df['Moderate'].index, df['Moderate'][trace].values,
                color=colors[technology][trace], label=tracelabels[technology][trace],
            )
        if len(traces[technology]) != 1:
            ax[coords[technology]].legend(
                fontsize=8,   #'small',
                loc = ('upper right'),
                #loc=('center left' if coords[technology][1]==2 else 'lower left'),
                #bbox_to_anchor=((1,0.5) if coords[technology][1]==2 else (0.,0.)),
                ncol=(2 if technology == 'OffShoreWind' else 1),
                handlelength=0.7, handletextpad=0.3, columnspacing=0.5,
                title=legendtitle[technology],
                frameon=False,
            )
        ### Formatting
        ax[coords[technology]].set_title(plottitle[technology], weight='bold')
        ax[coords[technology]].grid(which='major',axis='y',ls=':',lw=0.5,c='0.5')
        ### Range
        #if technology == 'Nuclear':
        #    continue
        for trace in df['Advanced']:
            ax[coords[technology]].fill_between(
                df['Advanced'].index, df['Conservative'][trace].values, df['Advanced'][trace].values,
                color=colors[technology][trace], alpha=alpha, label='_nolabel_', lw=0,
            )

    ### Format the figure
    for col in range(ncols):
        ax[-1,col].set_xlabel(None)
    ax[0,0].xaxis.set_major_locator(mpl.ticker.MultipleLocator(10))
    ax[0,0].xaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(2))
    if core_metric_parameter == 'CAPEX':
        ax[0,0].yaxis.set_major_locator(mpl.ticker.MultipleLocator(2000))
    else:
        ax[0,0].yaxis.set_major_locator(mpl.ticker.MultipleLocator(40))
    ax[0,0].yaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(2))
    ax[0,0].set_ylim(0,math.ceil(dfplot.value.max()/100)*100)
    ax[1,0].set_ylabel(core_metric_parameter + ' cost [' + str(dollar_year) + '$/kW]')
    ax[0,0].set_ylabel(core_metric_parameter + ' cost [' + str(dollar_year) + '$/kW]')
    plots.despine(ax)

    # Save the figure
    if figure_format == 'png':
        plt.savefig(os.path.join(figures_path,'ATB'+str(atb_version)+'-{}.png'.format(core_metric_parameter)))
    elif figure_format == 'pdf':
        plt.savefig(os.path.join(figures_path,'ATB'+str(atb_version)+'-{}.pdf'.format(core_metric_parameter)))

main()
