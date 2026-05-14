#%% Imports
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import patheffects as pe
import os
import sys
import argparse
import subprocess as sp
import platform
from glob import glob
from tqdm import tqdm
import traceback
import cmocean
from pptx.util import Inches
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds
from reeds import plots
from reeds import reedsplots
from reeds.report_utils import SLIDE_HEIGHT, SLIDE_WIDTH
from bokehpivot.defaults import DEFAULT_DOLLAR_YEAR, DEFAULT_PV_YEAR, DEFAULT_DISCOUNT_RATE

reeds_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
plots.plotparams()

#%% Argument inputs
parser = argparse.ArgumentParser(
    description='Compare multiple ReEDS cases',
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
)
parser.add_argument(
    'caselist', type=str, nargs='+',
    help=('space-delimited list of cases to plot, OR shared casename prefix, '
          'OR csv file of cases. The first case is treated as the base case '
          'unless a different one is provided via the --basecase/-b argument.'))
parser.add_argument(
    '--casenames', '-n', type=str, default='',
    help='comma-delimited list of shorter case names to use in plots')
parser.add_argument(
    '--titleshorten', '-s', type=str, default='',
    help='characters to cut from start of case name (only used if no casenames)')
parser.add_argument(
    '--startyear', '-t', type=int, default=2020,
    help='First year to show')
parser.add_argument(
    '--sharey', '-y', action='store_true',
    help='Use same y-axis scale for absolute and difference plots')
parser.add_argument(
    '--basecase', '-b', type=str, default='',
    help='Substring of case path to use as default (if empty, uses first case in list)')
parser.add_argument(
    '--skipbp', '-p', action='store_true',
    help='flag to prevent bokehpivot report from being generated')
parser.add_argument(
    '--bpreport', '-r', type=str, default='standard_report_reduced',
    help='which bokehpivot report to generate')
parser.add_argument(
    '--gdxdiff', '-g', action='store_true',
    help='generate gdx diff report between inputs.gdx when comparing 2 cases')
parser.add_argument(
    '--detailed', '-d', action='store_true',
    help='Include more detailed plots')
parser.add_argument(
    '--forcemulti', '-m', action='store_true',
    help='Always use multi-case plots (even for 2 cases)')
parser.add_argument(
    '--lesslabels', '-l', action='store_true',
    help='Add less value labels to plots')
parser.add_argument(
    '--nowrap', '-w', action='store_true',
    help="Don't wrap subplot titles")
parser.add_argument(
    '--simple_techs', '-x', type=str, default='display',
    help=(
        'Simplify technology names based on postprocessing/tech_aggregation.csv column '
        'named here (e.g., "display", "display_aggregated")'))
parser.add_argument(
    '--label_aggregation_level', '-a', type=str, default='display_aggregated',
    help=(
        'postprocessing/tech_aggregation.csv column to use for aggregation categories '
        '(e.g., "display_aggregated", "ther_stor_vre")'))
parser.add_argument(
    '--map', '-z', action='store_true',
    help='use hardcoded mapping rather than aggregation level for maps')
parser.add_argument(
    '--subregion', '-f', type = str, default=None,
    help="isolated subregion to highlight the results from")

#%% Inputs for testing
# reeds_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# caselist = [os.path.join(reeds_path,'postprocessing','example.csv')]
# casenames = ''
# titleshorten = 0
# startyear = 2020
# sharey = 'row'
# basecase_in = ''
# skipbp = True
# gdxdiff = False
# bpreport = 'standard_report_reduced'
# interactive = True
# forcemulti = False
# lesslabels = 0
# nowrap = False
# detailed = False
# simple_techs = 'display'
# label_aggregation_level = 'display_aggregated'
# class Args:
#     def __init__(self):
#         self.map = Falseplotdiffvals
# args = Args()

args = parser.parse_args()
caselist = args.caselist
casenames = args.casenames
try:
    titleshorten = int(args.titleshorten)
except ValueError:
    titleshorten = len(args.titleshorten)
basecase_in = args.basecase
startyear = args.startyear
sharey = True if args.sharey else 'row'
bpreport = args.bpreport
skipbp = args.skipbp
gdxdiff = args.gdxdiff
detailed = args.detailed
forcemulti = args.forcemulti
lesslabels = args.lesslabels
nowrap = args.nowrap
simple_techs = args.simple_techs
label_aggregation_level = args.label_aggregation_level
interactive = False


#%%### Fixed inputs
cmap = cmocean.cm.rain
cmap_diff = plt.cm.RdBu_r
## https://www.whitehouse.gov/wp-content/uploads/2023/11/CircularA-4.pdf
discountrate_social = DEFAULT_DISCOUNT_RATE
## https://www.epa.gov/environmental-economics/scghg
discountrate_scghg = 0.02
assert discountrate_scghg in [0.015, 0.02, 0.025]
central_health = {'cr':'ACS', 'model':'EASIUR'}
reeds_dollaryear = 2004
output_dollaryear = DEFAULT_DOLLAR_YEAR
startyear_notes = DEFAULT_PV_YEAR

colors_social = {
    'CO2': plt.cm.tab20b(4),
    'CH4': plt.cm.tab20b(5),
    'health': plt.cm.tab20b(7),
}

# remove techs within capacity set which are not inherently capacity sources outside of ReEDS
all_removals = ['Remove']
capacity_removals = ['Electrolyzer','SMR','SMR-CCS','DAC','Canadian Imports','Remove']

# Mapping options: variable to map and technologies to plot on each slide
## mapdiff: 'cap' or 'gen_ann'
mapdiff = 'cap'

# aggregation categories for mapping. If --map flag is used, uses hardcoded mapping instead of tech_agg csv
if args.map:
    maptechs = {
        'Battery/PSH': ['Battery', 'Pumped-Hydro', 'Pumped-Hydro-Flex'],
        'Biopower': ['Biopower', 'BECCS'],
        'Coal': ['Coal'],
        'Demand Response': ['DR Shed','EVMC_Shape','EVMC_Storage'],
        'Fossil+CCS': ['Coal-CCS-Flex', 'Coal-CCS', 'Coal-CCS_Upgrade','Gas-CCS',
            'Gas-CC-CCS', 'Gas-CC-CCS-Flex', 'Gas-CC-CCS_Upgrade'],
        'Geothermal': ['Geothermal'],
        'H2 Turbine': ['H2-CC_Upgrade', 'H2-CC', 'H2-CT_Upgrade', 'H2-CT', 'Hydrogen'],
        'Natural Gas': ['Gas-CC','Gas-CT','Oil/Gas Steam'],
        'Nuclear': ['Nuclear', 'Nuclear-SMR'],
        'Offshore Wind': ['Offshore Wind'],
        'Onshore Wind': ['Onshore Wind'],
        'Solar': ['CSP', 'UPV', 'DPV', 'PVB', 'Solar'],
    }
else:
    tech_agg = pd.read_csv(os.path.join(reeds_path,'postprocessing','tech_aggregation.csv'))
    maptechs = tech_agg.groupby(label_aggregation_level).agg({'display':list}).to_dict()['display']
    # remove capacity_removals from the mapping
    for k in maptechs:
        maptechs[k] = [t for t in maptechs[k] if t not in capacity_removals]

# Plotting list for 2 cases
plotdiffvals = [
    'Capacity (GW)',
    'Generation (TWh)',
    'New Annual Capacity (GW)',
    'Annual Retirements (GW)',
    'Firm Capacity (GW)',
    'Curtailment Rate',
    'Transmission (GW-mi)',
    'Transmission (PRM) (GW-mi)',
    'Bulk System Electricity Pric',
    'National Average Electricity',
    'Present Value of System Cost',
    'NEUE (ppm)',
    'Runtime (hours)',
    'Runtime by year (hours)',
]

onlytechs = None

#%%### Functions
def plot_bars_abs_stacked(
        dfplot, basecase, colors, ax, col=0,
        net=True, label=True, ypad=0.02, fontsize=9,
    ):
    """
    * ax must have at least 2 rows
    * dfplot must have cases as rows and stacked bar elements (matching colors) as cols
    """
    if not isinstance(colors, dict):
        colors = colors.squeeze()

    ## Absolute and difference
    if isinstance(basecase, str):
        dfdiff = dfplot - dfplot.loc[basecase]
    elif isinstance(basecase, list):
        dfdiff = dfplot - dfplot.loc[basecase].values
    elif isinstance(basecase, dict):
        dfdiff = dfplot - dfplot.loc[basecase.values()].values

    for (row, df) in enumerate([dfplot, dfdiff]):
        _ax = ax[row] if (col == -1) else ax[row,col]
        plots.stackbar(df=df, ax=_ax, colors=colors, net=(net or row), width=0.8)
        ymin, ymax = _ax.get_ylim()
        _ypad = (ymax - ymin) * ypad
        ## label net value
        if label:
            for x, case in enumerate(df.index):
                val = df.loc[case].sum()
                if np.around(val, 0) == 0:
                    continue
                _ax.annotate(
                    f'{val:.0f}', (x, val - _ypad), ha='center', va='top',
                    color='k', size=fontsize,
                    path_effects=[pe.withStroke(linewidth=2.0, foreground='w', alpha=0.7)],
                )
    ## Legend info
    legend_handles = [
        mpl.patches.Patch(facecolor=colors[i], edgecolor='none', label=i)
        for i in (colors if isinstance(colors, dict) else colors.index) if i in dfplot
    ]
    return legend_handles


#%%### Procedure
#%% Parse arguments
cases, colors, basecase, basemap = reeds.report_utils.parse_caselist(
    caselist,
    casenames,
    basecase_in,
    titleshorten,
)
maxlength = max([len(c) for c in cases])

## Arrange the maps
nrows, ncols, coords = plots.get_coordinates(cases, aspect=2)

#%% Create output folder
firstcasepath = list(cases.values())[0]
outpath = os.path.join(firstcasepath, 'outputs', 'comparisons')
os.makedirs(outpath, exist_ok=True)
## Remove disallowed characters and clip filename to max length
max_filename_length = 250
savename = os.path.join(
    outpath,
    (f"results-{','.join(cases.keys())}"
     .replace(':','').replace('/','').replace(' ','').replace('\\n','').replace('\n','')
     [:max_filename_length-len('.pptx')]) + '.pptx'
)
print(f'Saving results to {savename}')

#%% Create bokehpivot report as subprocess
if not skipbp:
    start_str = 'start ' if platform.system() == 'Windows' else ''
    bp_path = f'{reeds_path}/postprocessing/bokehpivot'
    bp_py_file = f'{bp_path}/reports/interface_report_model.py'
    report_path = f'{bp_path}/reports/templates/reeds2/{bpreport}.py'
    bp_outpath = f'{outpath}/{bpreport}-diff-multicase'
    add_diff = 'Yes'
    auto_open = 'Yes'
    bp_colors = pd.read_csv(f'{bp_path}/reeds_scenarios.csv')['color'].tolist()
    bp_colors = bp_colors*10 #Up to 200 scenarios
    bp_colors = bp_colors[:len(cases.keys())]
    df_scenarios = pd.DataFrame({'name':cases.keys(), 'color':bp_colors, 'path':cases.values()})
    scenarios_path = f'{outpath}/scenarios.csv'
    df_scenarios.to_csv(scenarios_path, index=False)
    call_str = (
        f'{start_str}python "{bp_py_file}" "ReEDS 2.0" "{scenarios_path}" all ' +
        f'{add_diff} "{basecase}" "{report_path}" "html,excel" one "{bp_outpath}" {auto_open}'
    )
    sp.Popen(call_str, shell=True)


#%% Create gdx diff report
if gdxdiff and len(cases) == 2:
    case0, case1 = list(cases.values())
    gdxname = os.path.join(
        outpath,
        f'diff_inputs-{os.path.basename(case0)}-{os.path.basename(case1)}.gdx'
    )
    command = (
        "gdxdiff "
        f"{os.path.join(case0, 'inputs_case', 'inputs.gdx')} "
        f"{os.path.join(case1, 'inputs_case', 'inputs.gdx')} "
        f"{gdxname}"
    )
    sp.run(command, shell=True)


#%%### Load data
#%% Shared
sw = reeds.io.get_switches(cases[basecase])
scalars = reeds.io.get_scalars(cases[basecase])
phaseout_trigger = float(scalars.co2_emissions_2022) * float(sw.GSw_TCPhaseout_trigger_f)

inflatable = reeds.io.get_inflatable(os.path.join(
    reeds_path,'inputs','financials','inflation_default.csv'))
inflator = inflatable[reeds_dollaryear, output_dollaryear]

scghg = pd.read_csv(
    os.path.join(reeds_path, 'postprocessing', 'plots', 'scghg_annual.csv'),
    comment='#', thousands=','
).rename(columns={
    'gas':'e',
    'emission.year':'t',
    '2.5% Ramsey':'2020_2.5%',
    '2.0% Ramsey':'2020_2.0%',
    '1.5% Ramsey':'2020_1.5%',
}).set_index(['e','t'])
scghg_central = (
    scghg[f'2020_{discountrate_scghg*100:.1f}%'].unstack('e')
    * inflatable[2020, output_dollaryear]
)

#%% Colors and mapping
output_formatting = reeds.io.get_plot_formatting()
aggregation_mapping = pd.read_csv(
        os.path.join(reeds_path,'postprocessing','tech_aggregation.csv'))


import_colors_df = pd.Series(
    {'imports': '#808080'},
    name='color',
)

#%% Parse excel report sheet names
val2sheet = reeds.io.get_report_sheetmap(cases[basecase])

#%% Read input files
dictin_sw = {case: reeds.io.get_switches(cases[case]) for case in cases}

hierarchy = {case: reeds.io.get_hierarchy(cases[case]) for case in cases}


val_r_subset = {}
for case in tqdm(cases, desc='get valid r values'):
    val_r_subset[case] =  None
    if args.subregion is not None:
        res = args.subregion.split('/')[0]
        rvals = args.subregion.split('/')[1].split('.')
        val_r_subset[case] = hierarchy[case].loc[hierarchy[case][res].isin(rvals)].index.unique().tolist()

all_st = []
val_st_subset = {}
for case in tqdm(cases, desc='get valid st values'):
    val_st_subset[case] =  None
    if args.subregion is not None:
        res = args.subregion.split('/')[0]
        rvals = args.subregion.split('/')[1].split('.')
        if res not in ['r','itlgrp']:
            val_st_subset[case] = hierarchy[case].loc[hierarchy[case][res].isin(rvals),'st'].unique().tolist()
            all_st+=val_st_subset[case]
all_st = list(set(all_st))

# val_r_subset = {}
# for case in tqdm(cases, desc='get valid r values'):
#     val_r_subset[case] =  None
#     res = 'st'
#     rvals = ['UT']
#     val_r_subset[case] = hierarchy[case].loc[hierarchy[case][res].isin(rvals)].index.unique().tolist()

# all_st = []
# val_st_subset = {}
# for case in tqdm(cases, desc='get valid st values'):
#     val_st_subset[case] =  None

#     res = 'st'
#     rvals = ['UT']
#     if res not in ['r','itlgrp']:
#         val_st_subset[case] = hierarchy[case].loc[hierarchy[case][res].isin(rvals),'st'].unique().tolist()
#         all_st+=val_st_subset[case]
# all_st = list(set(all_st))

dictin_error = {}
for case in tqdm(cases, desc='system cost error'):
    dictin_error[case] = reeds.io.read_output(cases[case], 'error_check').set_index('*').squeeze(1)

dictin_cap = {}
for case in tqdm(cases, desc='national capacity'):
    dictin_cap[case] = (reeds.io.read_output(cases[case], filename = 'cap_ivrt', r_filter = val_r_subset[case], valname = 'Capacity (GW)')
        .rename(columns = {'Value':'Capacity (GW)','i':'tech','t':'year'}))
    dictin_cap[case]['Capacity (GW)']/=1e3
    dictin_cap[case].tech = reedsplots.simplify_techs(dictin_cap[case].tech, display_level = simple_techs)
    dictin_cap[case] = (
        dictin_cap[case].groupby(['tech','year'], as_index=False)
        ['Capacity (GW)'].sum())
    dictin_cap[case] = dictin_cap[case].loc[
        ~dictin_cap[case].tech.isin(capacity_removals)].copy()


dictin_flow = {}
for case in tqdm(cases, desc='Annual transmission flow'):
    dictin_flow[case] = (reeds.io.read_output(cases[case],'tran_flow_rep_ann')
        .rename(columns = {'t':'year','Value':'Net Import (TWh)'}))
    if args.subregion is not None:
        dictin_flow[case] = dictin_flow[case].loc[
            (dictin_flow[case].r.isin(val_r_subset[case]) ^
            dictin_flow[case].rr.isin(val_r_subset[case]))]
        dictin_flow[case].loc[dictin_flow[case].r.isin(val_r_subset[case]),'Net Import (TWh)']*=-1
        dictin_flow[case] = (
            dictin_flow[case].groupby(['year'], as_index=False)
            ['Net Import (TWh)'].sum())
        dictin_flow[case]['imports'] = 'imports'
        dictin_flow[case]['Net Import (TWh)']/=1e6
    else:
        dictin_flow[case]['Net Import (TWh)'] = 0

dictin_gen = {}
for case in tqdm(cases, desc='national generation'):
    dictin_gen[case] = (reeds.io.read_output(cases[case], filename = 'gen_ivrt',r_filter = val_r_subset[case], valname = 'Generation (TWh)')
        .rename(columns = {'Value':'Generation (TWh)','i':'tech','t':'year'}))
    dictin_flow[case]['tech'] = 'interregional_flow'
    dictin_flow[case]['Generation (TWh)'] = dictin_flow[case]['Net Import (TWh)']*1e6
    dictin_gen[case] = pd.concat((dictin_gen[case],dictin_flow[case]))
    dictin_gen[case]['Generation (TWh)']/=1e6
    dictin_gen[case].tech = reedsplots.simplify_techs(dictin_gen[case].tech, display_level = simple_techs)
    dictin_gen[case] = dictin_gen[case].loc[
        ~dictin_gen[case].tech.isin(all_removals)].copy()
    dictin_gen[case] = (
        dictin_gen[case].groupby(['tech','year'], as_index=False)
        ['Generation (TWh)'].sum())


costcat_rename = {
    'CO2 Spurline':'CO2 T&S Capex',
    'CO2 Pipeline':'CO2 T&S Capex',
    'CO2 Storage':'CO2 T&S Capex',
    'CO2 Spurline FOM':'CO2 T&S O&M',
    'CO2 Pipeline FOM':'CO2 T&S O&M',
    'CO2 Incentive Payments':'CCS Incentives',
    'Capital': 'Gen & Stor Capex',
    'O&M': 'Gen & Stor O&M',
    'CO2 Network':'CO2 T&S Capex',
    'CO2 Incentives':'CCS Incentives',
    'CO2 FOM':'CO2 T&S O&M',
    'CO2 Capture':'CO2 T&S Capex',
    'H2 Fuel':'Fuel',
    'H2 VOM':'H2 Prod O&M',
}
dictin_npv = {}
for case in tqdm(cases, desc='NPV of system cost'):
    temp = reeds.results.calc_systemcost(cases[case], r_subset = val_r_subset[case], st_subset = val_st_subset).rename(columns = {'i':'tech','t':'year'})
    temp = pd.pivot_table(data = temp, index = 'cost_cat',values = 'Discounted Cost (Bil $)', aggfunc = 'sum')
    dictin_npv[case] = temp['Discounted Cost (Bil $)']

    dictin_npv[case].index = pd.Series(dictin_npv[case].index).replace(costcat_rename)
    dictin_npv[case] = dictin_npv[case].groupby(level=0, sort=False).sum()

dictin_npv2 = {}
for case in tqdm(cases, desc='Annualized system costs'):
    temp = reeds.results.calc_systemcost(cases[case], r_subset = val_r_subset[case],rename_as_bokeh = True, st_subset = val_st_subset).rename(columns = {'i':'tech','t':'year'})
    temp = pd.pivot_table(data = temp, index = ['cost_cat','year'],values = 'Discounted Cost (Bil $)', aggfunc = 'sum')
    dictin_npv2[case] = temp.reset_index(drop = False)
    dictin_npv2[case].cost_cat = dictin_npv2[case].cost_cat.replace(costcat_rename)
    dictin_npv2[case] = (
        dictin_npv2[case]
        .groupby(['cost_cat', 'year'], sort=False, as_index=False)
        ['Discounted Cost (Bil $)'].sum()
    )

dictin_loads = {}
for case in tqdm(cases, desc='Annual electricity costs'):
    dictin_loads[case] = (reeds.io.read_output(cases[case],'load_rt',r_filter = val_r_subset[case])
        .rename(columns = {'Value':'Load (MWh)','t':'year'}))
    dictin_loads[case] = pd.pivot_table(data = dictin_loads[case], index = ['year'],values = 'Load (MWh)', aggfunc = 'sum').reset_index(drop = False)

dictin_scoe = {}
for case in tqdm(cases, desc='SCOE'):
    dictin_scoe[case] = reeds.io.read_report(cases[case], 'National Average Electricity', val2sheet)
    dictin_scoe[case].cost_cat = dictin_scoe[case].cost_cat.replace(
        {**costcat_rename,**{'CO2 Incentives':'CCS Incentives'}})
    dictin_scoe[case] = (
        dictin_scoe[case].groupby(['cost_cat','year'], sort=False, as_index=False)
        ['Average cost ($/MWh)'].sum())
    
dictin_prices = {}
for case in tqdm(cases, desc='Annual electricity costs'):
    temp = (reeds.io.read_output(cases[case],'load_rt',r_filter = val_r_subset[case])
        .rename(columns = {'Value':'Load (MWh)','t':'year'}))
    temp = pd.pivot_table(data = temp, index = ['year'],values = 'Load (MWh)', aggfunc = 'sum').reset_index(drop = False)
    temp_values = reeds.results.calc_systemcost(cases[case], r_subset = val_r_subset[case],rename_as_bokeh = True, st_subset = val_st_subset, discount_rate = 0.00001
        ).rename(columns = {'i':'tech','t':'year'}) # discount rate set marginally small to annulaize flat across years
    temp_values = pd.pivot_table(data = temp_values, index = ['cost_cat','year'],values = 'Discounted Cost (Bil $)', aggfunc = 'sum')
    temp = pd.merge(left = temp_values.reset_index(drop = False), right = temp, on = 'year')
    temp['Electricity Price ($/MWh)'] = (temp['Discounted Cost (Bil $)']*1e9)/temp['Load (MWh)']
    dictin_prices[case] = pd.pivot_table(data = temp, index = ['cost_cat','year'],values = 'Electricity Price ($/MWh)', aggfunc = 'sum').reset_index(drop = False)
    dictin_prices[case]['Electricity Price ($/MWh)']

dictin_syscost = {}
for case in tqdm(cases, desc='annual system cost'):
    dictin_syscost[case] = reeds.io.read_report(cases[case], 'Undiscounted Annualized Syst', val2sheet)
    dictin_syscost[case].cost_cat = dictin_syscost[case].cost_cat.replace(
        {**costcat_rename,**{'CO2 Incentives':'CCS Incentives'}})
    dictin_syscost[case] = (
        dictin_syscost[case].groupby(['cost_cat','year'], sort=False)
        ['Cost (Bil $)'].sum().unstack('cost_cat'))

dictin_emissions = {}
for case in tqdm(cases, desc='national emissions'):
    dictin_emissions[case] = (
        reeds.io.read_output(cases[case], 'emit_nat', valname='ton')
    )
    if int(dictin_sw[case].get('GSw_Upstream', 0)):
        dictin_emissions[case] = dictin_emissions[case].groupby(['e','t']).ton.sum().unstack('e')
    else:
        dictin_emissions[case] = (
            dictin_emissions[case]
            .set_index(['etype','e','t'])
            .drop(['precombustion', 'upstream'], level='etype', errors='ignore')
            .groupby(['e','t']).ton.sum()
            .unstack('e')
        )


dictin_trans = {}
dictin_trans_inter = {}
dictin_trans_intra = {}
for case in tqdm(cases, desc='national transmission'):
    '''
    dictin_trans[case] = results.calc_tech_trans(cases[case])
    dictin_trans[case].loc[(dictin_trans[case].r.isin(val_r_subset[case]))]
    dictin_trans[case]['Amount (GW-mi)'] = dictin_trans[case]['Trans (TW-mi)']*1e3
    dictin_trans[case]['trtype'] = [trtype_map[x] for x in dictin_trans[case].trtype]
    print(dictin_trans[case])
    '''
    
    if args.subregion is not None:
        dictin_trans[case] = reeds.io.read_output(cases[case], 'tran_mi_out_detail', valname='MW-mi').rename(columns = {'t':'year'})
        dictin_trans[case]['Amount (GW-mi)'] = dictin_trans[case]['MW-mi']/1e3
        dictin_trans[case] = dictin_trans[case].loc[(dictin_trans[case].r.isin(val_r_subset[case])) | (dictin_trans[case].rr.isin(val_r_subset[case]))]
        
        dictin_trans_inter[case] = dictin_trans[case].loc[
            (dictin_trans[case].r.isin(val_r_subset[case]))^(dictin_trans[case].rr.isin(val_r_subset[case]))]
        dictin_trans_inter[case] = pd.pivot_table(data = dictin_trans_inter[case], 
            index = ['year','trtype'], values = 'Amount (GW-mi)',aggfunc = 'sum').reset_index(drop = False)
        dictin_trans_intra[case] = dictin_trans[case].loc[
            (dictin_trans[case].r.isin(val_r_subset[case]))*(dictin_trans[case].rr.isin(val_r_subset[case]))]
        dictin_trans_intra[case] = pd.pivot_table(data = dictin_trans_intra[case], 
            index = ['year','trtype'], values = 'Amount (GW-mi)',aggfunc = 'sum').reset_index(drop = False)
    else:
        dictin_trans[case] = reeds.io.read_report(cases[case], 'Transmission (GW-mi)')
    

dictin_trans_r = {}
for case in tqdm(cases, desc='regional transmission'):
    dictin_trans_r[case] = reeds.io.read_output(cases[case], 'tran_out', valname='MW',r_filter = val_r_subset)
    for _level in ['interconnect','transreg','transgrp','st']:
        dictin_trans_r[case][f'inter_{_level}'] = (
            dictin_trans_r[case].r.map(hierarchy[case][_level])
            != dictin_trans_r[case].rr.map(hierarchy[case][_level])
        ).astype(int)

dictin_cap_r = {}
for case in tqdm(cases, desc='regional capacity'):
    dictin_cap_r[case] = reeds.io.read_output(cases[case], 'cap', valname='MW')
    if args.subregion is not None:
        dictin_cap_r[case] = dictin_cap_r[case].loc[dictin_cap_r[case].r.isin(val_r_subset[case])]
    dictin_cap_r[case].i = reedsplots.simplify_techs(dictin_cap_r[case].i, display_level = simple_techs)
    dictin_cap_r[case] = dictin_cap_r[case].loc[
        ~dictin_cap_r[case].i.isin(capacity_removals)].copy()
    dictin_cap_r[case] = dictin_cap_r[case].groupby(['i','r','t'], as_index=False).MW.sum()

dictin_cap_firm = {}
for case in tqdm(cases, desc='firm capacity'):
    dictin_cap_firm[case] = reeds.io.read_output(cases[case], 'cap_firm', valname='MW')
    dictin_cap_firm[case].i = reedsplots.simplify_techs(dictin_cap_firm[case].i, display_level = simple_techs)
    dictin_cap_firm[case] = dictin_cap_firm[case].loc[
        ~dictin_cap_firm[case].i.isin(capacity_removals)].copy()
    dictin_cap_firm[case] = dictin_cap_firm[case].groupby(['i','r','ccseason','t'], as_index=False).MW.sum()

dictin_runtime = {}
for case in tqdm(cases, desc='runtime'):
    dictin_runtime[case] = (
        reeds.io.read_report(cases[case], 'Runtime by year (hours)', val2sheet)
        .drop(columns='Net Level processtime')
    )

dictin_neue = {}
dictin_neue_all = {}
for case in tqdm(cases, desc='NEUE'):
    infiles = sorted(glob(os.path.join(cases[case],'outputs','neue_*.csv')))
    if not len(infiles):
        continue
    df = {}
    for f in infiles:
        y, i = [int(s) for s in os.path.basename(f).strip('neue_.csv').split('i')]
        df[y,i] = pd.read_csv(f, index_col=['level', 'metric', 'region']).squeeze(1)
    dictin_neue_all[case] = pd.concat(df, names=('t', 'iteration'))
    indices = ['t', 'level', 'metric', 'region']
    dictin_neue[case] = (
        dictin_neue_all[case]
        .reset_index()
        .drop_duplicates(subset=indices, keep='last').drop(columns='iteration')
        .set_index(indices).squeeze(1)
    )

### Model years and discount rates
years = {}
yearstep = {}
for case in cases:
    years[case] = sorted(dictin_cap[case].year.astype(int).unique())
    years[case] = [y for y in years[case] if y >= startyear]
    yearstep[case] = years[case][-1] - years[case][-2]
lastyear = max(years[case])
## Years for which to add data notes
startyear_sums = 2023
allyears = range(startyear_sums,lastyear+1)
noteyears = [2035, 2050]
if all([lastyear < y for y in noteyears]):
    noteyears = [lastyear]
startyear_growth = 2035

discounts = pd.Series(
    index=range(startyear_notes,lastyear+1),
    data=[1/(1+discountrate_social)**(y-startyear_notes)
          for y in range(startyear_notes,lastyear+1)]
).rename_axis('t')

### Health impacts
dictin_health = {}
dictin_health_central = {}
dictin_health_central_mort = {}
for case in tqdm(cases, desc='health'):
    try:
        dictin_health[case] = (
            reeds.io.read_output(cases[case], 'health_damages_caused_r.csv')
            .groupby(['year','pollutant','model','cr']).sum()
        )
        dictin_health_central[case] = (
            dictin_health[case]
            .xs(central_health['cr'], level='cr')
            .xs(central_health['model'], level='model')
            .groupby('year').sum()
            ['damage_$']
            ### Inflate from reeds_dollaryear (2004) to bokeh output_dollaryear (2021)
            * inflator
            ### Convert to $B
            / 1e9
        )
        dictin_health_central_mort[case] = (
            dictin_health[case]
            .xs(central_health['cr'], level='cr')
            .xs(central_health['model'], level='model')
            .groupby('year').sum()
            ['mortality']
        )
    except (FileNotFoundError, KeyError) as err:
        print(f'Health impacts error for {case}: {err}')
        dictin_health_central[case] = (
            pd.Series(np.nan, index=years[case], name='damage_$')
            .rename_axis('year')
        )
        dictin_health_central_mort[case] = (
            pd.Series(np.nan, index=years[case], name='mortality')
            .rename_axis('year')
        )

### Directory size
dictin_dirsize = {}
for case in tqdm(cases, desc='directory size'):
    dictin_dirsize[case] = reeds.io.get_folder_size(cases[case])

### Get model dimensions
dictin_modeldims = {}
for case in tqdm(cases, desc='model dimensions'):
    dictin_modeldims[case] = reeds.log.get_model_dimensions(cases[case], t = lastyear)

#%% Detailed inputs
if detailed:
    ### Timeslice generation by region
    dictin_gen_h = {}
    for case in tqdm(cases, desc='gen_h'):
        dictin_gen_h[case] = reeds.io.read_output(cases[case], 'gen_h', valname='GW')
        dictin_gen_h[case].GW /= 1e3
        dictin_gen_h[case].i = reedsplots.simplify_techs(dictin_gen_h[case].i)
        dictin_gen_h[case] = dictin_gen_h[case].groupby(['i','r','h','t'], as_index=False).GW.sum()
        ## Separate charge and discharge
        dictin_gen_h[case].loc[
            (dictin_gen_h[case].i.str.startswith('battery')
            | dictin_gen_h[case].i.str.startswith('pumped-hydro'))
            & (dictin_gen_h[case].GW < 0),
            'i'
        ] += '|charge'
        dictin_gen_h[case].loc[
            (dictin_gen_h[case].i.str.startswith('battery')
            | dictin_gen_h[case].i.str.startswith('pumped-hydro'))
            & (~dictin_gen_h[case].i.str.endswith('|charge')),
            'i'
        ] += '|discharge'

    ### Aggregated generation by region
    dictin_gen_h_twh = {}
    for case in tqdm(dictin_gen_h):
        numhours = pd.read_csv(
            os.path.join(cases[case],'inputs_case','numhours.csv'),
        ).rename(columns={'*h':'h'}).set_index('h').squeeze(1)

        dictin_gen_h_twh[case] = dictin_gen_h[case].copy()
        dictin_gen_h_twh[case]['TWh'] = (
            dictin_gen_h_twh[case]['GW'] * dictin_gen_h_twh[case]['h'].map(numhours)
            / 1e3
        ).round(3)

        dictin_gen_h_twh[case] = dictin_gen_h_twh[case].groupby(['t','i']).TWh.sum().unstack('i')

    ### Stress period dispatch
    dictin_gen_h_stress = {}
    for case in tqdm(cases, desc='gen_h_stress'):
        dictin_gen_h_stress[case] = reeds.io.read_output(cases[case], 'gen_h_stress', valname='GW')
        dictin_gen_h_stress[case].GW /= 1e3
        dictin_gen_h_stress[case].i = reedsplots.simplify_techs(dictin_gen_h_stress[case].i)
        ## Separate charge and discharge
        dictin_gen_h_stress[case].loc[dictin_gen_h_stress[case].GW < 0,'i'] += '|charge'
        dictin_gen_h_stress[case].loc[dictin_gen_h_stress[case].i.isin(
            ['battery_li','pumped-hydro']),'i'] += '|discharge'

    ### Stress period flows
    dictin_tran_flow_stress = {}
    for case in tqdm(cases, desc='tran_flow_stress'):
        dictin_tran_flow_stress[case] = reeds.io.read_output(
            cases[case], 'tran_flow_stress', valname='GW')
        dictin_tran_flow_stress[case].GW /= 1e3

    ### Stress period load
    dictin_load_stress = {}
    for case in tqdm(cases, desc='load_stress'):
        dictin_load_stress[case] = reeds.io.read_output(cases[case], 'load_stress', valname='GW')
        dictin_load_stress[case].GW /= 1e3

    ### Peak load (for capacity credit)
    distloss = 0.05
    dictin_peak_ccseason = {}
    for case in tqdm(cases, desc='peak_ccseason'):
        dictin_peak_ccseason[case] = pd.read_csv(
            os.path.join(cases[case],'inputs_case','peak_ccseason.csv'),
        ).rename(columns={'*r':'r', 'MW':'GW'})
        dictin_peak_ccseason[case].GW /= (1e3 * (1 - distloss))

    ### Capacity credit PRMTRADE
    dictin_prmtrade = {}
    for case in tqdm(cases, desc='prmtrade'):
        dictin_prmtrade[case] = reeds.io.read_output(cases[case], 'captrade', valname='GW')
        dictin_prmtrade[case].GW /= 1e3


#%%### Plots ######
### Set up powerpoint file
prs = reeds.report_utils.init_pptx()

#%%### System cost error
try:
    dfplot = pd.concat(dictin_error, axis=1).replace(0,np.nan).dropna(how='all').fillna(0)

    ncols_err = len(dfplot)
    data = {
        'z': {'title': 'System cost\n[fraction]', 'scale':1},
        'gen': {'title': 'Non-valgen\ngeneration\n[GWh]', 'scale':1e-3},
        'cap': {'title': 'Non-valcap\ncapacity\n[GW]', 'scale':1e-3},
        'RPS': {'title': 'Non-RecMap\nRECS\n[GWh]', 'scale':1e-3},
        'OpRes': {'title': 'Non-valgen\nopres\n[MWh]', 'scale':1},
        'm_rsc_dat': {'title': 'Supply curve\ntweaks [GW]', 'scale':1e-3},
        'dropped': {'title': 'Dropped load\n[GWh]', 'scale':1e-3},
    }
    data = {k:v for k,v in data.items() if k in dfplot.index}

    plt.close()
    f,ax = plt.subplots(
        1, ncols_err,
        figsize=(min(ncols_err*3.5, SLIDE_WIDTH), max(3.75, 0.25*len(cases))),
    )
    for col, (datum, settings) in enumerate(data.items()):
        if datum not in dfplot.index:
            continue
        vals = dfplot.loc[datum] * settings['scale']
        _ax = ax if ncols_err == 1 else ax[col]
        _ax.bar(
            range(len(cases)),
            vals.values, color=[colors[c] for c in cases],
        )
        ## Formatting
        _ax.set_title(settings['title'], weight='bold', fontsize=14)
        _ax.set_xticks(range(len(cases)))
        _ax.set_xticklabels(cases.keys(), rotation=45, rotation_mode='anchor', ha='right')
        if _ax.get_ylim()[0] < 0:
            _ax.axhline(0, c='k', ls='--', lw=0.75)
        ## Notes
        for x, val in enumerate(vals):
            text = f"{val:.1e}" if datum == 'z' else f"{val:.0f}"
            _ax.annotate(text, (x, val), ha='center',
            xytext=(0, 2), textcoords='offset points',
        )

    plots.despine(ax)

    ### Save it
    title = 'Error Check'
    slide = reeds.report_utils.add_to_pptx(title, prs=prs, width=None, height=SLIDE_HEIGHT)
    if interactive:
        plt.show()
except Exception:
    print(traceback.format_exc())

#%%### Model Dimensions
try:
    model_plots = {
            'equations': {'title': f'{lastyear} Single\nequations', 'yaxis':'count'},
            'variables': {'title': f'{lastyear} Variables', 'yaxis':'count'},
            'non_zero_elements': {'title': f'{lastyear} Non-zero\nelements', 'yaxis':'count'},
            'peak_memory': {'title': f'{lastyear} Peak\nGAMS memory\n[GB]', 'yaxis':'GB'},
            'directory_size': {'title': 'Directory size\n[GB]', 'yaxis':'GB'},
        }

    plt.close()
    f,ax = plt.subplots(
        1, 5,
        figsize=(SLIDE_WIDTH,SLIDE_HEIGHT),
        layout='constrained',
    )

    for col, (datum, settings) in enumerate(model_plots.items()):
        if datum == 'directory_size':
            vals = [dictin_dirsize[case] for case in cases]
        else:
            vals = [dictin_modeldims[case][datum]
                for case in cases
            ]
        ax[col].bar(
            range(len(cases)),
            vals, color=[colors[c] for c in cases],
        )
        ## Formatting
        ax[col].set_title(settings['title'], weight='bold', fontsize=14)
        ax[col].set_xticks(range(len(cases)))
        ax[col].set_xticklabels(cases.keys(), rotation=90, rotation_mode='anchor', ha='right')
        if ax[col].get_ylim()[0] < 0:
            ax[col].axhline(0, c='k', ls='--', lw=0.75)
        ## Notes
        for x, val in enumerate(vals):
            text = f"{val:.0f}" if val < 1e6 else f"{val/1e6:.1f}M"
            ax[col].annotate(text, (x, val), ha='center',
            xytext=(0, 2), textcoords='offset points',
        )

    plots.despine(ax)

    ### Save it
    title = 'Model Dimensions'
    slide = reeds.report_utils.add_to_pptx(title, prs=prs, width=None, height=SLIDE_HEIGHT)
    if interactive:
        plt.show()
except Exception:
    print(traceback.format_exc())

#%%### Generation capacity lines
try:
    aggtechsplot = {}
    #aggtechsplot['Interregional\ntransmission'] = ['inter_transreg']
    for i in aggregation_mapping[label_aggregation_level].unique():
        aggtechsplot[i] = list(set(aggregation_mapping.loc[aggregation_mapping[label_aggregation_level] == i,simple_techs].tolist()))

    checktechs = [i for sublist in aggtechsplot.values() for i in sublist]
    alltechs = pd.concat(dictin_cap).tech.unique()
    printstring = (
        'The following techs are not plotted: '
        + ', '.join([c for c in alltechs if c not in checktechs])
    )

    offsetstart = {
        'Solar': (15,0),
        'Storage': (15,0),
        'Wind': (15,0),
        'Gas': (15,0),
    }

    val = '4_Capacity (GW)'
    ycol = 'Capacity (GW)'

    offset = dict()

    # Sort the capacities by difference across cases
    orderedaggs = []
    diffs = []
    for tech in aggtechsplot:
        temp_caps = []
        for case in cases:
            temp_caps.append(
                dictin_cap[case].loc[(dictin_cap[case].tech.isin(aggtechsplot[tech])) &
                    (dictin_cap[case].year == dictin_cap[case].year.max()),
                    ycol
                ].sum()
            )
        orderedaggs.append(tech)
        diffs.append(max(temp_caps)-min(temp_caps))
    df = pd.DataFrame({'tech':orderedaggs,'diff':diffs})
    df.sort_values(by = 'diff', ascending = False, inplace = True)

    aggtechsplot = {i:aggtechsplot[i] for i in df.tech.tolist()}
    if 'Remove' in aggtechsplot:
        del aggtechsplot['Remove']

    techrows, techcols = 2, len(aggtechsplot)//2+len(aggtechsplot)%2
    techcoords = dict(zip(
        list(aggtechsplot.keys()),
        [(row,col) for row in range(techrows) for col in range(techcols)]
    ))

    plt.close()
    f,ax = plt.subplots(
        techrows, techcols, sharex=True, sharey=True,
        figsize=(SLIDE_WIDTH, SLIDE_HEIGHT),
        gridspec_kw={'wspace':0.3, 'hspace':0.15},
    )
    df = {}
    for tech in aggtechsplot:
        for case in cases:
            ### Central cases
            if 'transmission' in tech.lower():
                df[tech,case] = dictin_trans_r[case].loc[
                    dictin_trans_r[case][aggtechsplot[tech][0]]==1
                ].groupby('t').MW.sum() / 1e3
            else:
                df[tech,case] = dictin_cap[case].loc[
                    dictin_cap[case].tech.isin(aggtechsplot[tech])
                ].groupby('year')[ycol].sum().reindex(years[case]).fillna(0)
            ax[techcoords[tech]].plot(
                df[tech,case].index, df[tech,case].values,
                label=case, color=colors[case], ls='-',
            )
            ### Annotate the last value (with overlaps)
            fincap = df[tech,case].reindex([lastyear]).fillna(0).squeeze()
            ax[techcoords[tech]].annotate(
                ' {:.0f}'.format(fincap),
                (lastyear, fincap+offset.get((tech,case),0)),
                ha='left', va='center',
                color=colors[case], fontsize='small',
                annotation_clip=False,
            )
        ### Formatting
        ax[techcoords[tech]].xaxis.set_minor_locator(mpl.ticker.MultipleLocator(5 if lastyear>2040 else 1))
        ax[techcoords[tech]].xaxis.set_major_locator(mpl.ticker.MultipleLocator(10 if lastyear>2040 else 5))
        ax[techcoords[tech]].annotate(
            tech.replace(' ','\n'),
            (0.05,1.0), va='top', ha='left',
            xycoords='axes fraction',
            fontsize='x-large', weight='bold',)
        ### Annotate the 2020 value
        if len(df[tech,basecase]):
            plots.annotate(
                ax[techcoords[tech]], basecase,
                startyear, offsetstart.get(tech,(10,10)), color='C7',
                arrowprops={'arrowstyle':'-|>', 'color':'C7'})
    if len(aggtechsplot) % 2:
        ax[-1,-1].axis('off')
    ## Legend
    handles, labels = ax[-1,0].get_legend_handles_labels()

    leg = ax[0,-1].legend(
        handles, labels,
        fontsize='large', frameon=False,
        loc='center left', bbox_to_anchor=(1.1,-0.075),
        handletextpad=0.3, handlelength=0.7,
        ncol=1,
    )
    for legobj in leg.legend_handles:
        legobj.set_linewidth(8)
        legobj.set_solid_capstyle('butt')
    ax[techcoords[list(aggtechsplot.keys())[0]]].set_xlim(startyear,lastyear)
    ax[techcoords[list(aggtechsplot.keys())[0]]].set_ylim(0)
    ax[techcoords[list(aggtechsplot.keys())[0]]].set_ylabel('Capacity [GW]', y=-0.075)
    ax[techcoords[list(aggtechsplot.keys())[0]]].set_ylim(0)

    plots.despine(ax)
    plt.draw()
    plots.shorten_years(ax[techcoords[list(aggtechsplot.keys())[-1]]])

    # add text boxes off slide to itemize the technologies in each category
    slide = reeds.report_utils.add_to_pptx('Capacity', prs=prs)
    reeds.report_utils.add_textbox((printstring if len(printstring)>0 else '---'), slide)
    ntech = 0
    for cat in aggtechsplot.keys():
        if 'transmission' not in cat.lower():
            aggtechsplot[cat].sort()
            techs = "\n    ".join([x for x in aggtechsplot[cat]])
            reeds.report_utils.add_textbox(f'{cat}:\n    {techs}', slide,
                                            top = SLIDE_HEIGHT+1,
                                            left = (SLIDE_WIDTH/len(aggtechsplot.keys()))*ntech,
                                            width = (SLIDE_WIDTH/len(aggtechsplot.keys())))
            ntech += 1

    if interactive:
        print(printstring)
        plt.show()
except Exception:
    print(traceback.format_exc())

#%%### Capacity and generation bars

toplot = {
            'Capacity': {
                'data': dictin_cap,
                'colors':output_formatting['tech_color'].squeeze(),
                'columns':'tech',
                'values':'Capacity (GW)',
                'label':'Capacity [GW]'
            },
            'Generation': {
                'data': dictin_gen,
                'colors':output_formatting['tech_color'].squeeze(),
                'columns':'tech',
                'values':'Generation (TWh)',
                'label':'Generation [TWh]'
            },
            # 'Runtime': {
            #     'data': dictin_runtime,
            #     'colors':output_formatting['time_colors'],
            #     'columns':'process',
            #     'values':'processtime',
            #     'label':'Runtime [hours]'
            # },
            'Net Regional Imports' : {
                'data': dictin_flow,
                'colors':import_colors_df,
                'columns':'imports',
                'values':'Net Import (TWh)',
                'label':'Net Import (TWh)'
            },
            'Annualized System Cost': {
                'data': dictin_npv2,
                'colors':output_formatting['cost_cat_colors'].squeeze(),
                'columns':'cost_cat',
                'values':'Discounted Cost (Bil $)',
                'label':'Discounted Cost (Bil $)'
            },
            'Annual Electricity Price': {
                'data': dictin_prices,
                'colors':output_formatting['cost_cat_colors'].squeeze(),
                'columns':'cost_cat',
                'values':'Electricity Price ($/MWh)',
                'label':'Electricity Price ($/MWh)'
            },

        }

plotwidth = 2.0
figwidth = plotwidth * len(cases)
dfbase = {}
for slidetitle, data in toplot.items():
    plt.close()
    f,ax = plt.subplots(
        2, len(cases), figsize=(figwidth, 6.8),
        sharex=True, sharey=sharey, dpi=None,
    )
    ax[0,0].set_ylabel(data['label'], y=-0.075)
    ax[0,0].set_xlim(2017.5, lastyear+2.5)
    ax[1,0].annotate(
        f'Diff\nfrom\n{basecase}', (0.03,0.03), xycoords='axes fraction',
        fontsize='x-large', weight='bold')
    ###### Absolute
    alltechs = set()
    for col, case in enumerate(cases):
        if case not in data['data']:
            continue
        dfplot = data['data'][case].pivot(index='year', columns=data['columns'], values=data['values'])
        dfplot = (
            dfplot[[c for c in data['colors'].index if (( c in dfplot.columns) & (c not in (all_removals)))]]
            .round(3).replace(0,np.nan)
            .dropna(axis=1, how='all')
        )

        if case == basecase:
            dfbase[slidetitle] = dfplot.copy()
        alltechs.update(dfplot.columns)
        plots.stackbar(df=dfplot, ax=ax[0,col], colors=data['colors'], width=yearstep[case], net=False)
        ax[0,col].set_title(
            (case if nowrap else plots.wraptext(case, width=plotwidth*0.9, fontsize=14)),
            fontsize=14, weight='bold', x=0, ha='left', pad=8,)
        ax[0,col].xaxis.set_major_locator(mpl.ticker.MultipleLocator(10))
        ax[0,col].xaxis.set_minor_locator(mpl.ticker.MultipleLocator(5))


    ### Legend
    handles = [
        mpl.patches.Patch(
            facecolor=data['colors'][i], edgecolor='none',
            label=i
        )
        for i in data['colors'].keys() if i in alltechs
    ]

    leg = ax[0,-1].legend(
        handles=handles[::-1], loc='upper left', bbox_to_anchor=(1.0,1.0),
        fontsize='medium', ncol=1,  frameon=False,
        handletextpad=0.3, handlelength=0.7, columnspacing=0.5,
    )

    ###### Difference
    for col, case in enumerate(cases):
        ax[1,col].xaxis.set_major_locator(mpl.ticker.MultipleLocator(10))
        ax[1,col].xaxis.set_minor_locator(mpl.ticker.MultipleLocator(5))
        ax[1,col].axhline(0,c='k',ls='--',lw=0.75)

        if (case not in data['data']) or (case == basecase):
            continue
        dfplot = data['data'][case].pivot(index='year', columns=data['columns'], values=data['values'])
        dfplot = (
            dfplot
            .round(3).replace(0,np.nan)
            .dropna(axis=1, how='all')
        )
        for i in list(alltechs):
            if i not in dfplot.columns:
                dfplot[i] = 0
            if i not in dfbase[slidetitle].columns:
                dfbase[slidetitle][i] = 0

        dfplot = dfplot.subtract(dfbase[slidetitle], fill_value=0)
        dfplot = dfplot[[c for c in data['colors'].index if (( c in dfplot.columns) & (c not in (all_removals)))]].copy()
        alltechs.update(dfplot.columns)
        plots.stackbar(df=dfplot, ax=ax[1,col], colors=data['colors'], width=yearstep[case], net=True)

    plots.despine(ax)
    plt.draw()
    plots.shorten_years(ax[1,col])
    ### Save it
    slide = reeds.report_utils.add_to_pptx(
        slidetitle+' stack', prs=prs, width=min(figwidth, SLIDE_WIDTH))
    if interactive:
        plt.show()


#%% Alternate view: Stacks with bars labeled
barwidth = 0.35
labelpad = 0.08
width = 1.6*len(cases) + 0.5

# Generate the aggregation mapping for capacity columns
aggstack = {}
tech_map_display = (
    aggregation_mapping[[simple_techs,label_aggregation_level]].drop_duplicates().set_index(simple_techs)
    )
for i in tech_map_display.index:
    display_aggregated = tech_map_display.at[i,label_aggregation_level]
    aggstack[i] = display_aggregated

aggcolors = output_formatting['tech_color'].squeeze()

aggtechs_disagg = aggstack.copy()
for k,v in aggstack.items():
    if v == 'Storage':
        aggtechs_disagg[k+'|charge'] = 'Storage|charge'
        aggtechs_disagg[k+'|discharge'] = 'Storage|discharge'

try:
    if len(cases) <= 4:
        plt.close()
        f,ax = plt.subplots(figsize=(width, 5))

        ### Final capacity and generation
        datum = 'Capacity'
        data = {
            'data': dictin_cap,
            'values':'Capacity (GW)',
            'label':f' {lastyear} Capacity [GW]',
        }
        ax.set_ylabel(data['label'])
        dfplot = pd.concat(
            {case:
                data['data'][case].loc[data['data'][case].year==lastyear]
                .set_index('tech')[data['values']]
                for case in cases},
            axis=1,
        ).T
        dfplot = dfplot.rename(columns=aggstack).T
        dfplot = dfplot.groupby(dfplot.index).sum().T
        unmapped = [c for c in dfplot if c not in aggcolors]
        if len(unmapped):
            raise Exception(f"Unmapped techs: {unmapped}")
        dfplot = (
            dfplot[[c for c in aggcolors.keys() if c in dfplot.columns]]
            .round(3).replace(0,np.nan).dropna(axis=1, how='all').fillna(0)
        )
        mindistance = dfplot.sum(axis=1).max() / 20
        dfcumsum = dfplot.cumsum(axis=1)
        dfdiff = dfplot - dfplot.loc[dfplot.index.map(basemap)].values

        ## Absolute and difference
        plots.stackbar(df=dfplot, ax=ax, colors=aggcolors, width=barwidth, net=False)

        ### Labels
        for x, case in enumerate(cases):
            labels = (dfcumsum.loc[case] - dfplot.loc[case]/2).rename('middle').to_frame()
            labels['ylabel'] = plots.optimize_label_positions(
                ydata=labels.middle.values, mindistance=mindistance, ypad=0,
            )
            labels['yval'] = labels.index.map(dfplot.loc[case])
            for i, row in labels.iterrows():
                ## Draw the line
                ax.annotate(
                    '',
                    xy=(x+barwidth/2, row.middle),
                    xytext=(x+barwidth/2+labelpad, row.ylabel),
                    arrowprops={
                        'arrowstyle':'-', 'shrinkA':0, 'shrinkB':0,
                        'color':aggcolors[i], 'lw':0.5},
                    annotation_clip=False,
                )
                ## Write the label
                diff = np.around(dfdiff.loc[case,i], 0)
                ax.annotate(
                    (
                        f"{row.yval:.0f}"
                        + (f" {i}" if case == list(cases.keys())[-1] else '')
                        + (f" ({diff:+.0f})" if diff else '')
                    ),
                    (x+barwidth/2+labelpad+0.01, row.ylabel),
                    va='center', ha='left', fontsize=9, color=aggcolors[i],
                    weight=('bold' if abs(diff) >= 100 else 'normal'),
                    annotation_clip=False,
                )

        ### Formatting
        ax.set_xticks(range(len(cases)))
        ax.set_xticklabels(cases.keys(), rotation=45, rotation_mode='anchor', ha='right')
        ax.yaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(5))
        plt.tight_layout()
        plots.despine(ax)
        plt.draw()
        ### Save it
        slide = reeds.report_utils.add_to_pptx('Capacity Stacks', prs=prs, width=width)

        # Add text box for aggregation category contents
        ntech = 0
        for cat in aggtechsplot.keys():
            if 'transmission' not in cat.lower():
                aggtechsplot[cat].sort()
                techs = "\n    ".join([x for x in aggtechsplot[cat]])
                reeds.report_utils.add_textbox(f'{cat}:\n    {techs}', slide,
                                                top = SLIDE_HEIGHT+1,
                                                left = (SLIDE_WIDTH/len(aggtechsplot.keys()))*ntech,
                                                width = (SLIDE_WIDTH/len(aggtechsplot.keys())))
                ntech += 1
        if interactive:
            plt.show()
except Exception:
    print(traceback.format_exc())

#%%### Hodgepodge: Final capacity, final generation, final transmission, NPV
try:
    width = max(11, len(cases)*1.3)
    plt.close()
    f,ax = plt.subplots(
        2, 4, figsize=(width, SLIDE_HEIGHT), sharex=True,
        sharey=('col' if (sharey is True) else False),
    )
    handles = {}

    ### Final capacity and generation
    toplot = {
        'Capacity': {
            'data': dictin_cap,
            'values':'Capacity (GW)',
            'label':f'{lastyear} Capacity [GW]'},
        'Generation': {
            'data': dictin_gen,
            'values':'Generation (TWh)',
            'label':f'{lastyear} Generation [TWh]'},
    }
    ax[0,1].axhline(0, c='k', ls='--', lw=0.75)
    for col, (datum, data) in enumerate(toplot.items()):
        ax[0,col].set_ylabel(data['label'], y=-0.075)
        dfplot = pd.concat(
            {case:
            data['data'][case].loc[data['data'][case].year==lastyear]
            .set_index('tech')[data['values']]
            for case in cases},
            axis=1,
        ).T
        dfplot = (
            dfplot[[c for c in output_formatting['bokeh_tech_colors'].index if c in dfplot]]
            .round(3).replace(0,np.nan).dropna(axis=1, how='all')
        )
        handles[datum] = plot_bars_abs_stacked(
            dfplot=dfplot, basecase=basemap,
            colors=output_formatting['tech_color'], fontsize=8,
            ax=ax, col=col, net=(True if datum == 'Generation' else False),
            label=(False if lesslabels else True),
        )

    ### Total transmission
    col = 2
    ax[0,col].set_ylabel(f'{lastyear} Transmission capacity [TW-mi]', y=-0.075)
    dftrans = pd.concat({
        case:
        dictin_trans[case].groupby(['year','trtype'])['Amount (GW-mi)'].sum()
        .unstack('trtype')
        .reindex(allyears).interpolate('linear')
        / 1e3
        for case in cases
    }, axis=1).loc[lastyear].unstack('trtype')

    handles['Transmission'] = plot_bars_abs_stacked(
        dfplot=dftrans, basecase=basemap,
        colors=output_formatting['trtype_colors'],
        ax=ax, col=col, net=False,
        label=(False if lesslabels else True),
    )

    ### NPV
    col = 3
    ax[0,col].set_ylabel('NPV of system cost [$B]', y=-0.075)
    dfplot = pd.concat({
        case: (
            dictin_npv2[case]
            .loc[dictin_npv2[case]['year'] == lastyear]
            .set_index('cost_cat')['Discounted Cost (Bil $)']
        )
        for case in cases
    }, axis=1).T.fillna(0)
    dfplot = dfplot[[c for c in output_formatting['cost_cat_colors'].index if c in dfplot]].copy()

    handles['NPV'] = plot_bars_abs_stacked(
        dfplot=dfplot, basecase=basemap,
        colors=output_formatting['cost_cat_colors'],
        ax=ax, col=col, net=False,
        label=(False if lesslabels else True),
    )

    ### Formatting
    for col in range(4):
        ax[1,col].set_xticks(range(len(cases)))
        ax[1,col].set_xticklabels(cases.keys(), rotation=90)
        ax[1,col].annotate('Diff', (0.03,0.03), xycoords='axes fraction', fontsize='large')
        ax[1,col].axhline(0, c='k', ls='--', lw=0.75)
    plt.tight_layout()
    plots.despine(ax)
    plt.draw()
    ### Save it
    slide = reeds.report_utils.add_to_pptx(
        'Capacity, Generation, Transmission, NPV', prs=prs, width=width)
    if interactive:
        plt.show()

    ### Add legends as separate figure below the slide
    plt.close()
    f,ax = plt.subplots(1, 4, figsize=(11, 0.1))
    for col, datum in enumerate(handles):
        leg = ax[col].legend(
            handles=handles[datum][::-1], loc='upper center', bbox_to_anchor=(0.5,1.0),
            fontsize='medium', ncol=1, frameon=False,
            handletextpad=0.3, handlelength=0.7, columnspacing=0.5,
        )
        ax[col].axis('off')
    reeds.report_utils.add_to_pptx(slide=slide, prs=prs, width=width, top=7.5)
except Exception:
    print(traceback.format_exc())

#%% Costs: NPV of system cost, NPV of climate + health costs
try:
    simple_npv = False
    width = max(11, len(cases)*1.3)
    plt.close()
    f,ax = plt.subplots(
        2, 3, figsize=(width, 6), sharex=True,
        sharey=('col' if (sharey is True) else False),
    )
    handles = {}

    ### NPV of system cost
    col = 0
    ax[0,col].set_ylabel('NPV of system cost [$B]', y=-0.075)
    ax[0,col].axhline(0, c='k', ls='--', lw=0.75)
    dfcost_npv = pd.concat({case: dictin_npv[case] for case in cases}, axis=1).T.fillna(0)
    dfcost_npv = dfcost_npv[[c for c in output_formatting['cost_cat_colors'].index if c in dfcost_npv]].copy()
    if simple_npv:
        dfcost_npv = dfcost_npv.sum(axis=1)
        dfcost_npv = pd.concat([pd.Series({case:dfcost_npv[case]}, name=case).to_frame() for case in cases])

    handles['NPV'] = plot_bars_abs_stacked(
        dfplot=dfcost_npv, basecase=basemap,
        colors=output_formatting['cost_cat_colors'],
        ax=ax, col=col, net=(not simple_npv),
        label=(False if lesslabels else True),
    )

    ### NPV of climate and health costs
    col = 1
    ax[0,col].set_ylabel('NPV of climate + health cost [$B]', y=-0.075)

    dfsocial = {}
    for case in cases:
        dfsocial[case] = (
            dictin_emissions[case].reindex(allyears).interpolate('linear')
            * scghg_central
        )[['CO2','CH4']].dropna() / 1e9
        dfsocial[case]['health'] = dictin_health_central[case].reindex(allyears).interpolate('linear')
    dfsocial = pd.concat(dfsocial, axis=1)

    dfsocial_npv = dfsocial.multiply(discounts, axis=0).dropna().sum().unstack('e')

    handles['social'] = plot_bars_abs_stacked(
        dfplot=dfsocial_npv, basecase=basemap,
        colors=colors_social,
        ax=ax, col=col, net=True,
        label=(False if lesslabels else True),
    )

    ### Combined
    col = 2
    ax[0,col].set_ylabel('NPV of system\n+ climate + health cost [$B]', y=-0.075)
    dfcombo_npv = pd.concat([dfcost_npv, dfsocial_npv], axis=1)

    handles['combo'] = plot_bars_abs_stacked(
        dfplot=dfcombo_npv, basecase=basemap,
        colors={**output_formatting['cost_cat_colors'].to_dict(), **colors_social},
        ax=ax, col=col, net=True,
        label=(False if lesslabels else True),
    )

    ### Formatting
    for col in range(3):
        ax[1,col].set_xticks(range(len(cases)))
        ax[1,col].set_xticklabels(cases.keys(), rotation=90)
        ax[1,col].annotate('Diff', (0.03,0.03), xycoords='axes fraction', fontsize='large')
        ax[1,col].axhline(0, c='k', ls='--', lw=0.75)
        ## Add commas to y axis labels
        if max([abs(i) for i in ax[0,col].get_ylim()]) >= 10000:
            ax[0,col].yaxis.set_major_formatter(mpl.ticker.StrMethodFormatter('{x:,.0f}'))
    plt.tight_layout()
    plots.despine(ax)
    plt.draw()
    ### Save it
    slide = reeds.report_utils.add_to_pptx('NPV of System, Climate, Health costs', height=SLIDE_HEIGHT)
    if interactive:
        plt.show()

    ### Add legends as separate figure below the slide
    plt.close()
    f,ax = plt.subplots(1, 4, figsize=(11, 0.1))
    for col, datum in enumerate(handles):
        leg = ax[col].legend(
            handles=handles[datum][::-1], loc='upper center', bbox_to_anchor=(0.5,1.0),
            fontsize='medium', ncol=1, frameon=False,
            handletextpad=0.3, handlelength=0.7, columnspacing=0.5,
        )
    for col in range(4):
        ax[col].axis('off')
    reeds.report_utils.add_to_pptx(slide=slide, prs=prs, width=width, top=7.5)
except Exception:
    print(traceback.format_exc())


#%%### Transmission maps
try:
    if (len(cases) == 2) and (not forcemulti):
        casebase, casecomp = list(cases.values())
        casebase_name, casecomp_name = list(cases.keys())
        plt.close()
        f,ax = reedsplots.plot_trans_diff(
            casebase=casebase,
            casecomp=casecomp,
            pcalabel=False,
            wscale=0.0004,
            subtract_baseyear=2020,
            yearlabel=True,
            year=lastyear,
            alpha=1, dpi=150,
            titleshorten=titleshorten,
        )
        reeds.report_utils.add_to_pptx(f'Transmission ({lastyear})', prs=prs)
        if interactive:
            plt.show()
    else:
        ### Absolute
        wscale = 0.0003
        alpha = 0.8
        for subtract_baseyear in [None, 2020]:
            plt.close()
            f,ax = plt.subplots(
                nrows, ncols, figsize=(SLIDE_WIDTH, SLIDE_HEIGHT),
                gridspec_kw={'wspace':0.0,'hspace':-0.1},
            )
            for case in cases:
                ### Plot it
                reedsplots.plot_trans_onecase(
                    case=cases[case], pcalabel=False, wscale=wscale,
                    yearlabel=False, year=lastyear, simpletypes=None,
                    alpha=alpha, scalesize=8,
                    f=f, ax=ax[coords[case]], title=False,
                    subtract_baseyear=subtract_baseyear,
                    thickborders='transreg', drawstates=False, drawzones=False,
                    label_line_capacity=10,
                    scale=(True if case == basecase else False),
                )
                ax[coords[case]].set_title(case)
            ### Formatting
            title = (
                f'New Interzonal Transmission Since {subtract_baseyear}' if subtract_baseyear
                else 'All Interzonal Transmission')
            for row in range(nrows):
                for col in range(ncols):
                    if nrows == 1:
                        ax[col].axis('off')
                    elif ncols == 1:
                        ax[row].axis('off')
                    else:
                        ax[row,col].axis('off')
            ### Save it
            slide = reeds.report_utils.add_to_pptx(title, prs=prs)
            if interactive:
                plt.show()


        ### Difference
        plt.close()
        f,ax = plt.subplots(
            nrows, ncols, figsize=(SLIDE_WIDTH, SLIDE_HEIGHT),
            gridspec_kw={'wspace':0.0,'hspace':-0.1},
        )
        for case in cases:
            ax[coords[case]].set_title(case)
            if case == basecase:
                ### Plot absolute
                reedsplots.plot_trans_onecase(
                    case=cases[case], pcalabel=False, wscale=wscale,
                    yearlabel=False, year=lastyear, simpletypes=None,
                    alpha=alpha, scalesize=8,
                    f=f, ax=ax[coords[case]], title=False,
                    subtract_baseyear=subtract_baseyear,
                    thickborders='transreg', drawstates=False, drawzones=False,
                    label_line_capacity=10,
                    scale=(True if case == basecase else False),
                )
            else:
                ### Plot the difference
                reedsplots.plot_trans_diff(
                    casebase=cases[basecase], casecomp=cases[case],
                    pcalabel=False, wscale=wscale,
                    yearlabel=False, year=lastyear, simpletypes=None,
                    alpha=alpha,
                    f=f, ax=ax[coords[case]],
                    subtract_baseyear=subtract_baseyear,
                    thickborders='transreg', drawstates=False, drawzones=False,
                    label_line_capacity=10,
                    scale=False,
                )
        ### Formatting
        title = 'Interzonal transmission difference'
        for row in range(nrows):
            for col in range(ncols):
                if nrows == 1:
                    ax[col].axis('off')
                elif ncols == 1:
                    ax[row].axis('off')
                else:
                    ax[row,col].axis('off')
        ### Save it
        slide = reeds.report_utils.add_to_pptx(title, prs=prs)
        if interactive:
            plt.show()
except Exception:
    print(traceback.format_exc())

#%% Flexibly sited load
try:
    if any([float(dictin_sw[c].get('GSw_LoadSiteCF', 0)) for c in cases]):
        loadsite_cases = {
            k:v for k,v in cases.items() if float(dictin_sw[k].get('GSw_LoadSiteCF', 0))
        }
        f, ax, dictplot = reeds.reedsplots.map_output_byyear(
            case=loadsite_cases,
            param='loadsite_cap',
            years=[lastyear],
            vscale=1e-3,
            vmin=0,
            title='Sited demand [GW]',
        )
        ## Save it
        slide = reeds.results.add_to_pptx('Flexibly Sited Demand', prs=prs, width=SLIDE_WIDTH)
        if interactive:
            plt.show()
except Exception:
    print(traceback.format_exc())


#%%### Generation capacity maps

### Shared data
try:
    base = cases[list(cases.keys())[0]]
    val_r = dictin_cap_r[basecase].r.unique()
    dfmap = reeds.io.get_dfmap(base)
    dfba = dfmap['r']
    dfstates = dfmap['st']
    if (len(cases) == 2) and (not forcemulti):
        for i_plot in maptechs.keys():
            plt.close()
            f,ax=plt.subplots(
                1, 3, sharex=True, sharey=True, figsize=(14,8),
                gridspec_kw={'wspace':-0.05, 'hspace':0.05},
                dpi=150,
            )

            _,_,dfplot = reedsplots.plot_diff_maps(
                val=mapdiff, i_plot=i_plot, titles = maptechs[i_plot],
                year=lastyear, casebase=casebase, casecomp=casecomp,
                plot='base', f=f, ax=ax[0],
                cmap=cmocean.cm.rain,
            )
            ax[0].annotate(
                casebase_name,
                (0.1,1), xycoords='axes fraction', fontsize=10)

            _,_,dfplot = reedsplots.plot_diff_maps(
                val=mapdiff, i_plot=i_plot, titles = maptechs[i_plot],
                year=lastyear, casebase=casebase, casecomp=casecomp,
                plot='comp', f=f, ax=ax[1],
                cmap=cmocean.cm.rain,
            )
            ax[1].annotate(
                casecomp_name,
                (0.1,1), xycoords='axes fraction', fontsize=10)

            _,_,dfplot = reedsplots.plot_diff_maps(
                val=mapdiff, i_plot=i_plot, titles = maptechs[i_plot],
                year=lastyear, casebase=casebase, casecomp=casecomp,
                plot='absdiff', f=f, ax=ax[2],
                cmap=plt.cm.RdBu_r,
            )
            ax[2].annotate(
                '{}\n– {}'.format(
                    casecomp_name,
                    casebase_name),
                (0.1,1), xycoords='axes fraction', fontsize=10)

            reeds.report_utils.add_to_pptx(f'{i_plot} Capacity {lastyear} [GW]', prs=prs)
            if interactive:
                plt.show()
    else:
        figwidth = SLIDE_WIDTH
        #### Absolute maps
        if (nrows == 1) or (ncols == 1):
            legendcoords = max(nrows, ncols) - 1
        elif (nrows-1, ncols-1) in coords.values():
            legendcoords = (nrows-1, ncols-1)
        else:
            legendcoords = (nrows-2, ncols-1)

        ### Set up plot
        for tech_type in maptechs.keys():
            ### Get limits
            vmin = 0.
            vmax = float(pd.concat({
                case: dictin_cap_r[case].loc[
                    (dictin_cap_r[case].i.isin(maptechs[tech_type]))
                    & (dictin_cap_r[case].t.astype(int)==lastyear)
                ].groupby('r').MW.sum()
                for case in cases
            }).max()) / 1e3
            if np.isnan(vmax):
                vmax = 0.
            if not vmax:
                print(f'{tech_type} has zero capacity in {lastyear}, so skipping maps')
                continue
            ### Set up plot
            plt.close()
            f,ax = plt.subplots(
                nrows, ncols, figsize=(figwidth, SLIDE_HEIGHT),
                gridspec_kw={'wspace':0.0,'hspace':-0.1},
            )
            ### Plot it
            for case in cases:
                dfval = dictin_cap_r[case].loc[
                    (dictin_cap_r[case].i.isin(maptechs[tech_type]))
                    & (dictin_cap_r[case].t.astype(int)==lastyear)
                ].groupby('r').MW.sum()
                dfplot = dfba.copy()
                dfplot['GW'] = (dfval / 1e3).fillna(0)

                ax[coords[case]].set_title(
                    case if nowrap else plots.wraptext(case, width=figwidth/ncols*0.9, fontsize=14)
                )
                dfba.plot(
                    ax=ax[coords[case]],
                    facecolor='none', edgecolor='k', lw=0.1, zorder=10000)
                dfstates.plot(
                    ax=ax[coords[case]],
                    facecolor='none', edgecolor='k', lw=0.2, zorder=10001)
                dfplot.plot(
                    ax=ax[coords[case]], column='GW', cmap=cmap, vmin=vmin, vmax=vmax,
                    legend=False,
                )
                ## Legend
                if coords[case] == legendcoords:
                    plots.addcolorbarhist(
                        f=f, ax0=ax[coords[case]], data=dfplot.GW.values,
                        title=f'{tech_type} {lastyear}\ncapacity [GW]', cmap=cmap, vmin=vmin, vmax=vmax,
                        orientation='horizontal', labelpad=2.25, histratio=0.,
                        cbarwidth=0.05, cbarheight=0.85,
                        cbarbottom=-0.05, cbarhoffset=0.,
                    )

            for row in range(nrows):
                for col in range(ncols):
                    if nrows == 1:
                        ax[col].axis('off')
                    elif ncols == 1:
                        ax[row].axis('off')
                    else:
                        ax[row,col].axis('off')
            ### Save it
            slide = reeds.report_utils.add_to_pptx(f'{tech_type} Capacity {lastyear} [GW]', prs=prs)
            if interactive:
                plt.show()

        #### Difference maps
        ### Set up plot
        for tech_type in maptechs.keys():
            ### Get limits
            dfval = pd.concat({
                case: dictin_cap_r[case].loc[
                    (dictin_cap_r[case].i.isin(maptechs[tech_type]))
                    & (dictin_cap_r[case].t.astype(int)==lastyear)
                ].groupby('r').MW.sum()
                for case in cases
            }, axis=1).fillna(0) / 1e3
            dfdiff = dfval.subtract(dfval[basecase], axis=0)
            ### Get colorbar limits
            absmax = dfval.stack().max()
            diffmax = dfdiff.unstack().abs().max()

            if np.isnan(absmax):
                absmax = 0.
            if not absmax:
                print(f'{tech_type} has zero capacity in {lastyear}, so skipping maps')
                continue
            ### Set up plot
            plt.close()
            f,ax = plt.subplots(
                nrows, ncols, figsize=(figwidth, SLIDE_HEIGHT),
                gridspec_kw={'wspace':0.0,'hspace':-0.1},
            )
            ### Plot it
            for case in cases:
                dfplot = dfba.copy()
                dfplot['GW'] = dfval[case] if case == basecase else dfdiff[case]

                ax[coords[case]].set_title(
                    case if nowrap else plots.wraptext(case, width=figwidth/ncols*0.9, fontsize=14)
                )
                dfba.plot(
                    ax=ax[coords[case]],
                    facecolor='none', edgecolor='k', lw=0.1, zorder=10000)
                dfstates.plot(
                    ax=ax[coords[case]],
                    facecolor='none', edgecolor='k', lw=0.2, zorder=10001)
                dfplot.plot(
                    ax=ax[coords[case]], column='GW',
                    cmap=(cmap if case == basecase else cmap_diff),
                    vmin=(0 if case == basecase else -diffmax),
                    vmax=(absmax if case == basecase else diffmax),
                    legend=False,
                )
                ## Difference legend
                if coords[case] == legendcoords:
                    plots.addcolorbarhist(
                        f=f, ax0=ax[coords[case]], data=dfplot.GW.values,
                        title=f'{tech_type} {lastyear}\ncapacity, difference\nfrom {basecase} [GW]',
                        cmap=(cmap if case == basecase else cmap_diff),
                        vmin=(0 if case == basecase else -diffmax),
                        vmax=(absmax if case == basecase else diffmax),
                        orientation='horizontal', labelpad=2.25, histratio=0.,
                        cbarwidth=0.05, cbarheight=0.85,
                        cbarbottom=-0.05, cbarhoffset=0.,
                    )
            ## Absolute legend
            plots.addcolorbarhist(
                f=f, ax0=ax[coords[basecase]], data=dfval[basecase].values,
                title=f'{tech_type} {lastyear}\ncapacity [GW]',
                cmap=cmap, vmin=0, vmax=absmax,
                orientation='horizontal', labelpad=2.25, histratio=0.,
                cbarwidth=0.05, cbarheight=0.85,
                cbarbottom=-0.05, cbarhoffset=0.,
            )

            for row in range(nrows):
                for col in range(ncols):
                    if nrows == 1:
                        ax[col].axis('off')
                    elif ncols == 1:
                        ax[row].axis('off')
                    else:
                        ax[row,col].axis('off')
            ### Save it
            slide = reeds.report_utils.add_to_pptx(f'Difference: {tech_type} Capacity {lastyear} [GW]', prs=prs)
            if interactive:
                plt.show()
except Exception:
    print(traceback.format_exc())

#%% Save the powerpoint file
prs.save(savename)
print(f'\ncompare_casegroup.py results saved to:\n{savename}')

### Open it
if sys.platform == 'darwin':
    sp.run(f"open '{savename}'", shell=True)
elif platform.system() == 'Windows':
    sp.run(f'"{savename}"', shell=True)
