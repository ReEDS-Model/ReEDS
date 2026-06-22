'''
This file allows reports to be run directly from this python script (without need for the bokeh server and bokehpivot UI).

Easiest process:
1. Update bokehpivot/reeds_scenarios.csv with desired scenario names and paths.
2. If a different report is desired (other than standard_report_reduced), update 'report_path' (below).
3. Run this file. If you haven't updated 'output_dir', you'll find the results in bokehpivot/out.

If you run this file from another location, update 'bokehpivot_dir' below.
'''
import os
import sys
import pandas as pd
import scipy
import shutil
import importlib
import copy
from pdb import set_trace as b
#EDIT: Manually set bokehpivot_dir to another path if this file is in a different location.
bokehpivot_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(1, bokehpivot_dir)
import reeds_bokeh as rb

#EDIT THE FOLLOWING FIELDS
report_path = f'{bokehpivot_dir}/reports/templates/reeds2/value_factor_report.py' #Path to report that is to be run
diff = 'No' #Use 'Yes' if adding differences to a base case, specified below (default base case is first scenario in reeds_scenarios.csv)

data_source = f'{bokehpivot_dir}/reeds_scenarios_valcostfac.csv' #either a scenarios.csv file or ReEDS run directory (or directories separated by pipe symbols). Edit this file with your valcostfac run names/paths.
base = pd.read_csv(data_source)['name'][0] #Name of base case for when diff='Yes'. Defaults to first case in reeds_scenarios.csv.
output_dir = f'{bokehpivot_dir}/out/reeds_report' #This is the directory that will be created to contain the report. If it already exists, the existing directory will be archived with a date.
data_type = 'ReEDS 2.0'
scenario_filter = 'all' #'all' or string of comma-separated names.
html_num = 'one' #'one' or 'multiple'. 'one' will create one html file with all sections, and 'multiple' will create a separate html file for each section
report_format = 'html,excel' #'html', 'excel', or 'csv', or any combination separated by commas
auto_open = 'Yes' #'Yes' or 'No'. Automatically open the resulting report excel and html files when they are created.

#DON'T EDIT THIS SECTION
report_dir = os.path.dirname(report_path)
sys.path.insert(1, report_dir)
report_name = os.path.basename(report_path)[:-3]
report = importlib.import_module(report_name)
#Comment these two lines if the bokehpivot report is already made and you just want to run the custom post-processing below.
rb.reeds_static(data_type, data_source, scenario_filter, diff, base, report.static_presets, report_path, report_format, html_num, output_dir, auto_open)
shutil.copy2(os.path.realpath(__file__), output_dir)

#CUSTOM POSTPROCESSING
#Any post-processing of the excel data that was produced. you can read excel data into dataframes by importing pandas and using pandas.read_excel()

start_year = 2025

out_txt = f'{output_dir}/out.txt'
with open(out_txt, 'w') as f:
    print("Results:", file=f)

print('Read in custom files')
df_lcoe_base = pd.read_csv(f'{bokehpivot_dir}/LCOE_base.csv')
df_forcetech_map = pd.read_csv(f'{bokehpivot_dir}/forcetech_map.csv')
df_core = pd.read_csv(f'{bokehpivot_dir}/core_tech_scen.csv')

print('Read in value factors')
df = pd.read_excel(f'{output_dir}/report.xlsx', sheet_name='vf')
df = df.rename(columns={'vf': 'value_factor'})
df = df[df['tech'].isin(df_forcetech_map['tech'])].copy()
df = df[df['year']>=start_year].copy() #First endogenous year (also without prescribed builds).

print('Merge with vf components')
df_vf_energy = pd.read_excel(f'{output_dir}/report.xlsx', sheet_name='vf_energy').rename(columns={'vf_load':'vf_energy'})
df = df.merge(df_vf_energy, on=['scenario','tech','year'], how='left')
df_vf_resmarg = pd.read_excel(f'{output_dir}/report.xlsx', sheet_name='vf_resmarg')
df = df.merge(df_vf_resmarg, on=['scenario','tech','year'], how='left')
df_vf_resmarg_permw = pd.read_excel(f'{output_dir}/report.xlsx', sheet_name='vf_resmarg_permw')
df = df.merge(df_vf_resmarg_permw, on=['scenario','tech','year'], how='left')
df_vf_spatial = pd.read_excel(f'{output_dir}/report.xlsx', sheet_name='vf_spatial')
df = df.merge(df_vf_spatial, on=['scenario','tech','year'], how='left')
df_vf_temporal = pd.read_excel(f'{output_dir}/report.xlsx', sheet_name='vf_temporal')
df = df.merge(df_vf_temporal, on=['scenario','tech','year'], how='left')
df_vf_interaction = pd.read_excel(f'{output_dir}/report.xlsx', sheet_name='vf_interaction')
df = df.merge(df_vf_interaction, on=['scenario','tech','year'], how='left')
df['vf_temporal_local'] = df['vf_temporal'] * df['vf_interaction']
df['vf_spatial_simultaneous'] = df['vf_spatial'] * df['vf_interaction']

print('Merge with benchmark price and calculate LVOE')
df_bench = pd.read_excel(f'{output_dir}/report.xlsx', sheet_name='bench_price')
df_bench = df_bench.rename(columns={'val_tot':'benchmark_price'})
df = df.merge(df_bench, on=['scenario','year'], how='left')
df['lvoe'] = df['value_factor'] * df['benchmark_price']

print('Merge with LVOE components')
df_lvoe_energy = pd.read_excel(f'{output_dir}/report.xlsx', sheet_name='lvoe_energy').rename(columns={'val_load':'lvoe_energy'})
df = df.merge(df_lvoe_energy, on=['scenario','tech','year'], how='left')
df_lvoe_resmarg = pd.read_excel(f'{output_dir}/report.xlsx', sheet_name='lvoe_resmarg').rename(columns={'val_resmarg':'lvoe_resmarg'})
df = df.merge(df_lvoe_resmarg, on=['scenario','tech','year'], how='left')
df['vf_comp_energy'] = df['lvoe_energy'] / df['benchmark_price']
df['vf_comp_resmarg'] = df['lvoe_resmarg'] / df['benchmark_price']

print('Merge with LCOE_base')
#LCOE_base.csv (in 2022$/MWh) uses default ATB Moderate 2024 techs: Tech 1 class 4 land-based wind, Fixed-bottom class 3 offshore wind, class 5 utility PV, 2-on-1 f-frame  gas-cc, large nuclear, and coal-new. LCOE for gas and coal were calculated, as they aren't in the ATB. Gas prices were taken from ng_AEO_2023_reference.csv and ng_demand_AEO_2023_reference.csv (weighted average), and coal was taken from coal_AEO_2023_reference.csv (all in 2022$)
df_lcoe_base['lcoe_base'] = df_lcoe_base['lcoe_base'] * 1.041 #Converted to 2023$ from 2022$ (2024 ATB)
df = df.merge(df_lcoe_base, on=['tech','year'], how='left')
df['lcoe_base_orig'] = df['lcoe_base']
#If "_IRA" is in the scenario name, subtract the PTC from LCOE
ptc = 18.31481632 #11.36 2004$/MWh, converted to 2023$ (taken from ReEDS run ptc_value_scaled).
#If "_IRA" is in the scenario name, subtract the ptc from lcoe
df.loc[df['scenario'].str.contains('_IRA'), 'lcoe_base'] = df['lcoe_base'] - ptc

print('Add cost multipliers')
df_scens = pd.read_csv(data_source)
for i, scen in df_scens.iterrows():
    sw = pd.read_csv(f'{scen["path"]}/inputs_case/switches.csv', index_col=0).iloc[:,0]
    if sw['ForceMandate']=='1':
        df_scens.loc[i,'forcetech'] = sw['ForceTech']
        df_scens.loc[i,'y0'] = int(sw['ForceStartYear'])
        df_scens.loc[i,'y1'] = int(sw['endyear'])
        df_scens.loc[i,'m0'] = float(sw['ForceStartLevel'])
        df_scens.loc[i,'m1'] = float(sw['ForceEndLevel'])
df_force = df_scens.merge(df_forcetech_map, on='forcetech', how='left')
df_force = df_force.rename(columns={'name':'scenario'})[['tech','scenario','y0','y1','m0','m1']].copy()
df_force['frc'] = 1
df = df.merge(df_force, on=['tech','scenario'], how='left')
df['force_mult'] = 1 #Initialized to 1.
mult_cond = (df['y0']<=df['year'])&(df['y1']>=df['year'])
df.loc[mult_cond, 'force_mult'] = df['m0'] + (df['year']-df['y0'])*(df['m1']-df['m0'])/(df['y1']-df['y0'])
df = df.drop(columns=['y0','y1','m0','m1']).copy()
df['frc'] = df['frc'].fillna(0)
df['lcoe_base'] = df['lcoe_base'] * df['force_mult']

print('Add core tech-scenario combinations')
df_core['core'] = 1
df = df.merge(df_core, on=['tech','scenario'], how='left')
df['core'] = df['core'].fillna(0)

print('Calculate metrics')
df['value_cost_factor'] = df['lcoe_base'] / df['benchmark_price']
df['cost_value_factor'] = 1 / df['value_cost_factor']
df['cost_factor'] = df['lvoe'] / df['lcoe_base'] #Here we assume lcoe = lvoe, which is true on the margin.
df['lcoe_adder'] = (df['lvoe'] - df['lcoe_base']) / df['force_mult'] #Here we unadjust by force_mult to get the real adder.
df['integration_cost'] = df['benchmark_price'] - df['lvoe']
df['relative_cost'] = df['lvoe'] / df['force_mult'] - df['benchmark_price']
df['relative_cost_ratio'] = (df['lvoe'] / df['force_mult']) / df['benchmark_price']
df['net_cost'] = df['relative_cost'] + df['integration_cost']
df['BCR'] = df['lvoe'] / (df['lvoe'] / df['force_mult'])
df['value_cost_adder'] = df['lcoe_adder'] + df['integration_cost']

print('Merge with generation')
df_gen = pd.read_excel(f'{output_dir}/report.xlsx', sheet_name='gen')
df_gen = df_gen.rename(columns={'Generation (TWh)': 'gen_twh'})
df_gen = df_gen[['scenario','tech','year','gen_twh']].copy()
df = df.merge(df_gen, on=['scenario','tech','year'], how='left')

print('Merge with generation fraction')
df_gen_frac = pd.read_excel(f'{output_dir}/report.xlsx', sheet_name='gen_frac')
df_gen_frac = df_gen_frac.rename(columns={'Generation (TWh)': 'gen_frac'})
df_gen_frac = df_gen_frac[['scenario','tech','year','gen_frac']].copy()
df = df.merge(df_gen_frac, on=['scenario','tech','year'], how='left')

print('output valcostfac.csv')
df.to_csv(f'{output_dir}/valcostfac.csv', index=False)

print('Make plots and line fits')
import plotly.express as px #I needed to run "pip install plotly statsmodels"
os.makedirs(f'{output_dir}/plots')

print('Restrict to just those scenarios with "frc" == 1 or other specified scenario-tech combinations')
plot_cond = (
    (df['frc']==1) |
    ((df['tech'].isin(['UPV','Onshore Wind'])) & (df['scenario'].isin(['ref','ref_IRA','tax']))) |
    ((df['tech']=='Gas-CC') & (df['scenario'].isin(['upv','onswind','ref','ref_IRA','tax']))) |
    ((df['tech']=='Gas-CC-CCS') & (df['scenario'].isin(['tax'])))
)
df_plot = df[plot_cond].copy()
df_plot['tech scenario'] = df_plot['tech'] + ' ' + df_plot['scenario']
plots = [
    {'x':'gen_frac','y':'value_factor'},
    {'x':'gen_frac','y':'value_cost_factor'},
    {'x':'gen_frac','y':'cost_value_factor'},
    {'x':'gen_frac','y':'cost_factor'},
    {'x':'gen_frac','y':'vf_energy'},
    {'x':'gen_frac','y':'vf_resmarg'},
    {'x':'gen_frac','y':'vf_resmarg_permw'},
    {'x':'gen_frac','y':'vf_comp_energy'},
    {'x':'gen_frac','y':'vf_comp_resmarg'},
    {'x':'gen_frac','y':'vf_temporal'},
    {'x':'gen_frac','y':'vf_spatial'},
    {'x':'gen_frac','y':'vf_interaction'},
    {'x':'gen_frac','y':'vf_temporal_local'},
    {'x':'gen_frac','y':'vf_spatial_simultaneous'},
    {'x':'gen_twh','y':'lcoe_adder'},
    {'x':'gen_frac','y':'value_cost_adder'},
    {'x':'gen_frac','y':'integration_cost'},
    {'x':'gen_frac','y':'relative_cost'},
    {'x':'gen_frac','y':'relative_cost_ratio'},
    {'x':'gen_frac','y':'net_cost'},
    {'x':'gen_frac','y':'BCR'},
]

print('Add an upper limit on gen_frac and add intermediary "lim" plots, if desired') #We probably should also have a lower limit for value factors
gen_frac_max = 0.65
df_plot_lim = df_plot[(df_plot['gen_frac'] <= gen_frac_max)].copy()
plots_lim = copy.deepcopy(plots)
for p in plots_lim:
    p['lim'] = 'yes'

print('Limit further to just the core tech-scenario combinations')
df_plot_core = df_plot_lim[df_plot_lim['core']==1].copy()
conv_techs = ['Gas-CC','Gas-CC-CCS','Nuclear','Coal']
re_techs = ['Onshore Wind','Offshore Wind','Geothermal','UPV']

print('Add cost_factor_adj') #For conv_techs this is equal to cost_factor divided by average cost_factor. For re_techs, this is equal to cost_factor divided by the intercept of the ols line fit.
for tech in df_plot_core['tech'].unique():
    df_tech = df_plot_core[df_plot_core['tech']==tech].copy()
    if tech in conv_techs:
        scale = df_tech['cost_factor'].mean()
    elif tech in re_techs:
        #Get the intercept of the ols line fit
        lg = scipy.stats.linregress(df_tech['gen_frac'], df_tech['cost_factor'])
        scale = lg.intercept
    df_plot_core.loc[df_plot_core['tech']==tech, 'cost_factor_adj'] = df_plot_core['cost_factor'] / scale
    df_plot_core.loc[df_plot_core['tech']==tech, 'lcoe_base_adj'] = df_plot_core['lcoe_base'] * scale
    df_plot_core.loc[df_plot_core['tech']==tech, 'lcoe_base_orig_adj'] = df_plot_core['lcoe_base_orig'] * scale

print('Recalculate VCF')
df_plot_core['value_cost_factor_adj'] = df_plot_core['value_factor'] / df_plot_core['cost_factor_adj']
#Find average VCF for all conv_techs, and use that to scale the VCF for all techs
VCF_adj = df_plot_core[df_plot_core['tech'].isin(conv_techs)]['value_cost_factor_adj'].mean()
df_plot_core['value_cost_factor_adj2'] = df_plot_core['value_cost_factor_adj'] / VCF_adj
#Apply minimum vcf to df_plot_core, if desired
vcf_min = 0
df_plot_core = df_plot_core[df_plot_core['value_cost_factor_adj2'] >= vcf_min].copy()
with open(out_txt, 'a') as f:
    print(f'VCF_adj: {VCF_adj}', file=f)

print('Find average VF for all conv_techs, and use that to scale the VF for all techs (old method)')
VF_adj = df_plot_core[df_plot_core['tech'].isin(conv_techs)]['value_factor'].mean()
df_plot_core['value_factor_adj_old'] = df_plot_core['value_factor'] / VF_adj
with open(out_txt, 'a') as f:
    print(f'VF_adj (old): {VF_adj}', file=f)

print('output valcostfac_core.csv')
df_plot_core.to_csv(f'{output_dir}/valcostfac_core.csv', index=False)
plots_core = [
    {'x':'gen_frac','y':'value_factor', 'core': 'yes'},
    {'x':'gen_frac','y':'value_factor_adj_old', 'core': 'yes'},
    {'x':'gen_frac','y':'cost_factor', 'core': 'yes'},
    {'x':'gen_frac','y':'cost_factor_adj', 'core': 'yes'},
    {'x':'gen_frac','y':'value_cost_factor', 'core': 'yes'},
    {'x':'gen_frac','y':'value_cost_factor_adj', 'core': 'yes'},
    {'x':'gen_frac','y':'value_cost_factor_adj2', 'core': 'yes'},
]

print('Include plots_lim for all plots with gen_frac <= gen_frac_max')
for plot in plots + plots_core:
    if 'lim' in plot:
        df_plt = df_plot_lim
        lim_str = f'_ms-{gen_frac_max}'
    elif 'core' in plot:
        df_plt = df_plot_core
        lim_str = f'_core'
    else:
        df_plt = df_plot
        lim_str = ''
    fig = px.scatter(df_plt, x=plot['x'], y=plot['y'], color='tech scenario',
        hover_data=['tech scenario', 'year', 'gen_frac', plot['y']], trendline='ols',
        template='plotly_white', width=950, height=630)
    # fig.update_xaxes(range=[0, 1.005])
    # fig.update_yaxes(range=[0, 1.205])
    fig.update_layout(font=dict(size=13))
    fig.update_traces(mode='lines+markers', marker=dict(size=10), selector=dict(mode='markers'))
    fig.update_traces(line=dict(dash='dash', width=2), selector=dict(mode='lines'))
    fig.write_html(f'{output_dir}/plots/{plot["y"]}-vs-{plot["x"]}{lim_str}.html')

print('Read in vf_full for transreg and interconnect calcs') #Eventually I should use vf_full for everything I think
df_full = pd.read_excel(f'{output_dir}/report.xlsx', sheet_name='vf_full')
df_full = df_full[df_full['tech'].isin(df_forcetech_map['tech'].tolist() + ['benchmark'])].copy()
df_full = df_full[df_full['year']>=start_year].copy() #First endogenous year (also without prescribed builds).
subregs = ['transreg','interconnect']
dfs_subreg = {}
for subreg in subregs:
    df_sub = df_full.groupby(['tech','scenario','year',subreg], as_index=False)[['mwh','val_tot']].sum()
    df_sub['lvoe'] = df_sub['val_tot'] / df_sub['mwh']
    df_sub_bench = df_sub[df_sub['tech']=='benchmark'].copy().drop(columns=['tech']).rename(columns={'lvoe':'lvoe_bench','mwh':'mwh_bench','val_tot':'val_tot_bench'})
    df_sub = df_sub[df_sub['tech']!='benchmark'].copy()
    #Restrict to only core tech-scenario combinations
    df_sub = df_sub.merge(df_core[['tech','scenario']], on=['tech','scenario'], how='inner')
    df_sub = df_sub.merge(df_sub_bench, on=['scenario','year',subreg], how='left')
    df_sub['vf'] = df_sub['lvoe'] / df_sub['lvoe_bench']
    df_gen_sub = pd.read_excel(f'{output_dir}/report.xlsx', sheet_name=f'gen_{subreg}')
    df_sub = df_sub.merge(df_gen_sub, on=['scenario','tech','year',subreg], how='left')
    df_sub['gen_frac'] = df_sub['Generation (TWh)']*1e6 / df_sub['mwh_bench']
    #Merge in lcoe_base and use to calculate vcf.
    df_sub = df_sub.merge(df[['scenario','tech','year','lcoe_base']], on=['scenario','tech','year'], how='left')
    df_sub['vcf'] = df_sub['lcoe_base'] / df_sub['lvoe_bench']
    dfs_subreg[subreg] = df_sub.copy()

print('Make subregion plots')
metrics = ['vf','vcf']
for subreg in subregs:
    df_sub = dfs_subreg[subreg]
    for scenario in df_sub['scenario'].unique():
        df_plt = df_sub[df_sub['scenario']==scenario]
        for metric in metrics:
            fig = px.scatter(df_plt, x='gen_frac', y=metric, color=subreg,
                hover_data=[subreg, 'year', 'gen_frac', metric], trendline='ols',
                template='plotly_white', width=950, height=630)
            fig.update_layout(font=dict(size=13))
            fig.update_traces(mode='lines+markers', marker=dict(size=10), selector=dict(mode='markers'))
            fig.update_traces(line=dict(dash='dash', width=2), selector=dict(mode='lines'))
            fig.write_html(f'{output_dir}/plots/{metric}-vs-gen_frac_{subreg}_{scenario}.html')
