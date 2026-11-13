"""
Things to try:
- Identify descending/ascending pairs of high/low values and shade between them (to avoid
  overemphasizing the max and min values)
"""

#%% Imports
import os
import sys
import argparse
import traceback
import pandas as pd
from pathlib import Path
import matplotlib.pyplot as plt
sys.path.append(str(Path(__file__).parent.parent))
import reeds

reeds.plots.plotparams()


#%% Fixed inputs
interactive = False


#%% Argument inputs
parser = argparse.ArgumentParser(
    description='Compare groups of Monte Carlo samples',
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
)
parser.add_argument(
    'caselist', type=str, nargs='+',
    help=(
        'space-delimited list of dfcases to plot, OR csv file of dfcases (both with glob '
        'controls included). The first case is treated as the base case '
        'unless a different one is provided via the --basecase/-b argument.'
    ))
parser.add_argument(
    '--casenames', '-n', type=str, default='',
    help='comma-delimited list of shorter case names to use in plots')
parser.add_argument(
    '--titleshorten', '-s', type=str, default='',
    help='characters to cut from start of case name (only used if no casenames)')
parser.add_argument(
    '--basepath', '-b', type=str, default='',
    help='Substring of case path to use as default (if empty, uses first case in list)')
parser.add_argument(
    '--write', '-w', choices=['pdf', 'png', 'ppt', 'pptx'], default='pptx',
    help='Output format (png or pptx)')
parser.add_argument(
    '--keepincomplete', '-k', action='store_true',
    help="Keep cases that didn't finish (e.g. if only interested in inputs)")

# #%% Inputs for testing
# caselist = [str(Path(reeds.io.reeds_path,'postprocessing','example.csv'))]
# casenames = ''
# titleshorten = ''
# basepath = None
# write = 'pptx'
# interactive = True
# keep_incomplete = False

### Parse inputs
args = parser.parse_args()
caselist = args.caselist
casenames = args.casenames
write = args.write.strip('.')
keep_incomplete = args.keepincomplete
try:
    titleshorten = int(args.titleshorten)
except ValueError:
    titleshorten = len(args.titleshorten)
if args.basepath == '':
    basepath = None
else:
    basepath = args.basepath
    if not Path(basepath).is_dir():
        print(f'{basepath=} does not exist; using first sample instead')
        basepath = None


#%%### Procedure
#%% Parse arguments
casepaths, nicelabels, colors = reeds.report_utils.parse_caseglobs(
    caselist,
    casenames,
    titleshorten,
    keep_incomplete=keep_incomplete,
)

#%% Create output container
if basepath is not None:
    savepath = Path(basepath, 'outputs', 'comparisons')
else:
    ## Put it in the first sample if no basepath is specified
    basepath = casepaths[list(casepaths.keys())[0]][0]
    savepath = Path(basepath, 'outputs', 'comparisons')

savepath.mkdir(parents=True, exist_ok=True)
print(f'Saving results to {savepath}')

if write in ['pdf', 'png']:
    def saveit(savename, **kwargs):
        outpath = Path(savepath, savename.replace(' ', '') + f'.{write}')
        plt.savefig(outpath)
        print(outpath)
        if interactive:
            plt.show()

elif write in ['ppt', 'pptx']:
    label = ','.join(nicelabels.values()).replace(' ','')
    outpath = os.path.join(savepath, f'comparegroup-{label}.pptx')
    prs = reeds.report_utils.init_pptx()
    def saveit(savename, **kwargs):
        reeds.report_utils.add_to_pptx(savename, prs=prs, **kwargs)
        if interactive:
            plt.show()


#%% Colors
plot_settings = reeds.io.get_plot_formatting()
colors_tech = plot_settings['tech_color']


#%% Cases
# dfcases = pd.DataFrame(casepaths)
## Allow for different numbers of samples across dfcases
dfcases = pd.concat({k: pd.Series(v) for k,v in casepaths.items()}, axis=1)
dfcases.columns = dfcases.columns.rename('caseprefix')
dfcases = dfcases.stack().rename('path').dropna().reset_index(level='caseprefix')
dfcases['number'] = dfcases.path.map(lambda x: int(x.split('_')[-1].strip('MC')))
## Add central case
if basepath is not None:
    dfcases = pd.concat([
        dfcases,
        pd.DataFrame({'caseprefix':'central', 'path':basepath, 'number':0}, index=[0])
    ])
dfcases = dfcases.set_index(['caseprefix','number']).sort_index()
samples = [i for i in dfcases.index.get_level_values('number').unique() if i != 0]
## Instantiate the data containers
cases = {key: [reeds.ReEDScase(x) for x in caselist] for key, caselist in casepaths.items()}
casebase = reeds.ReEDScase(basepath)


#%%### Inputs plots
#%% Demand
for caseprefix in casepaths:
    try:
        f, ax, dfplot = reeds.mcplots.plot_demand_lines(cases[caseprefix])
        savename = f'in-demand-{nicelabels[caseprefix]}'
        saveit(savename)
    except Exception:
        print(traceback.format_exc())


#%% Fuel price
for caseprefix in casepaths:
    try:
        f, ax, dfplot = reeds.mcplots.plot_fuelprice_lines(cases[caseprefix])
        savename = f'in-gasprice-{nicelabels[caseprefix]}'
        saveit(savename)
    except Exception:
        print(traceback.format_exc())


#%% Capital cost
for caseprefix in casepaths:
    labels = {
        'upv_3': 'UPV',
        'wind-ons_3': 'Wind',
        'battery_li': 'Battery',
    }
    try:
        f, ax, dfplot = reeds.mcplots.plot_capcost_lines(cases[caseprefix])
        savename = f"in-capcost-{','.join(list(labels.values()))}-{nicelabels[caseprefix]}"
        saveit(savename)
    except Exception:
        print(traceback.format_exc())


#%% Supply curves (SLOW)
for caseprefix in casepaths:
    techs = ['upv', 'wind-ons']
    for tech in techs:
        try:
            f, ax, dfplot = reeds.mcplots.map_supplycurve_diff(
                cases[caseprefix], casebase=casebase, tech=tech,
            )
            savename = f"in-supplycurve-{tech.replace('-','')}-{nicelabels[caseprefix]}"
            saveit(savename)
        except Exception:
            print(traceback.format_exc())


#%%### Output plots
#%% Generation capacity vertical histograms
techs = [
    'UPV',
    'Gas-CC',
    'Onshore Wind',
    'Gas-CT',
    'Nuclear',
    'Battery',
    'Offshore Wind',
    'Coal-CCS',
    'Gas-CC-CCS',
    'Coal',
    'Nuclear-SMR',
]
try:
    f, ax, dfplot = reeds.mcplots.plot_cap_gen_hist(
        cases, casebase=casebase, nicelabels=nicelabels, colors=colors,
    )
    savename = (
        f"out-cap-hist-{','.join(techs)}-"
        f"{','.join([nicelabels[caseprefix].replace(' ','') for caseprefix in cases])}"
    )
    saveit(savename)
except Exception:
    print(traceback.format_exc())


#%% Transmission interface capacity vertical histograms
level = 'transreg' if len(casebase.hierarchy.transreg.unique()) >= 2 else 'st'
try:
    f, ax, dfplot = reeds.mcplots.plot_cap_trans_hist(
        cases, casebase=casebase, nicelabels=nicelabels, colors=colors, level=level,
    )
    savename = (
        f'out-trans-{level}-'
        f"{','.join([nicelabels[caseprefix].replace(' ','') for caseprefix in cases])}"
    )
    saveit(savename)
except Exception:
    print(traceback.format_exc())


#%% Emissions
etype = 'process'
for pollutant in ['CO2', 'CO2e', 'CH4', 'N2O', 'SO2', 'NOX']:
    try:
        f, ax, dfplot = reeds.mcplots.plot_emissions(
            cases, nicelabels=nicelabels, colors=colors, pollutant=pollutant, etype=etype,
        )
        savename = (
            f"out-emissions_{etype}_{pollutant}-histline_country-"
            f"{','.join([nicelabels[caseprefix].replace(' ','') for caseprefix in cases])}"
        )
        saveit(savename)
    except Exception:
        print(traceback.format_exc())


#%% Scatter & correlation, outputs vs inputs
corr_method = 'spearman'
for caseprefix, plotcases in cases.items():
    try:
        f, ax, dfplot = reeds.mcplots.plot_scatter_everything(plotcases)
        savename = (
            f"out-everything-scatter-x_everything-y_cap-corr_{corr_method}-"
            + f"{nicelabels[caseprefix]}"
        ).replace(' ','')
        saveit(savename)
    except Exception:
        print(traceback.format_exc())


#%% Generation capacity stacked bars by sample: Nation
for caseprefix, plotcases in cases.items():
    try:
        f, ax, dfplot = reeds.mcplots.plot_cap_gen_bar(plotcases)
        savename = (f'out-cap-bar_country-{nicelabels[caseprefix]}').replace(' ','')
        saveit(savename)
    except Exception:
        print(traceback.format_exc())


#%% Generation capacity stacked bars by sample: State (SLOW)
for caseprefix, plotcases in cases.items():
    try:
        f, ax, dfplot = reeds.mcplots.plot_cap_gen_bar_states(plotcases)
        savename = (f'out-cap-bar_st-{nicelabels[caseprefix]}').replace(' ','')
        saveit(savename)
    except Exception:
        print(traceback.format_exc())


#%% NPV (system, health, climate) vertical histograms
try:
    f, ax, dfplot = reeds.mcplots.plot_npv(
        cases, casebase=casebase, nicelabels=nicelabels, colors=colors,
    )
    savename = (
        f"out-npv_system,health,climate,total-"
        f"{','.join([nicelabels[caseprefix].replace(' ','') for caseprefix in cases])}"
    )
    saveit(savename)
except Exception:
    print(traceback.format_exc())


#%% Save the powerpoint file
if write in ['ppt', 'pptx']:
    prs.save(outpath)
    print(f'\ncompare_casegroup.py results saved to:\n{outpath}')
