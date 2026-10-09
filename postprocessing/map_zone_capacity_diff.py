#%% IMPORTS
import pandas as pd
import matplotlib.pyplot as plt
import os
import sys
import argparse
import traceback
import itertools
import cmocean
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds
from reeds import plots
from reeds import reedsplots

os.environ['PROJ_NETWORK'] = 'OFF'

reeds_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

plots.plotparams()

##########
#%% INPUTS
## Note that if your case builds lots of transmission, wscale might
## need to be reduced to avoid too much overlap in the plotted routes
wscale_straight = 0.0004
wscale_routes = 1.5
wscale_h2 = 10
## Note that if you change the CRS you'll probably need to change
## the position of the annotations
crs = 'ESRI:102008'
### General purpose
cmap = cmocean.cm.rain
### For VRE siting & transmission maps
transalpha = 0.25
transcolor = 'k'
ms = 1.15
gen_cmap = {
    'wind-ons':plt.cm.Blues,
    'upv':plt.cm.Reds,
    'wind-ofs':plt.cm.Purples,
}
max_filename_length = 250
### For testing
interactive = False
write = True

###################
#%% ARGUMENT INPUTS
# parser = argparse.ArgumentParser(
#     description='Create static maps and plots of ReEDS outputs',
#     formatter_class=argparse.ArgumentDefaultsHelpFormatter,
# )
# ## Include both case_positional and --case/-c for backwards compatibility
# parser.add_argument('case_positional', type=str, help='path to ReEDS run folder', nargs='?')
# parser.add_argument('--case', '-c', type=str, help='path to ReEDS run folder')
# parser.add_argument('--casediff', '-cd', type=str, help='path to ReEDS run folder for diff')
# parser.add_argument('--year', '-y', type=int, default=0,help='year to plot, or 0 for last year')
# parser.add_argument('--level', '-l', type=str, default='interconnect',help='spatial resolution to plot, from hiearchy.csv')

# args = parser.parse_args()
# if args.case_positional and args.case:
#     err = (
#         'Provided case as both positional argument and as --case/-c; '
#         'only use one or the other, not both'
#     )
#     raise ValueError(err)
# elif args.case_positional:
#     case = args.case_positional
# elif args.case:
#     case = args.case
# else:
#     raise ValueError('Provide case path either as positional argument or as --case/-c')
# casediff = None
# if args.casediff:
#     casediff = args.casediff
# level = args.level



# #%% Inputs for testing
# case = os.path.join(reeds_path,'runs','v20260624_raM1_MultiMetricRA')
# year = 0
# interactive = True
# write = False
# import importlib
# importlib.reload(reedsplots)

casename = 'Aug10_OFSRepDay'
runspath = f'/Volumes/Projects/15. PACES/runs/{casename}/'

level = 'transgrp'

casebase = None
# casebase = runspath + casename + '_USA_reanalysis-adj'
cases = [
    runspath + casename + '_USA_reanalysis-adj',
    # runspath + casename + '_USA_ecearth3cc-2000',
    # runspath + casename + '_USA_ecearth3cc-2010',
    # runspath + casename + '_USA_ecearth3cc-2020',
    # runspath + casename + '_USA_ecearth3cc-2030',
    # runspath + casename + '_USA_ecearth3cc-2040',
    # runspath + casename + '_USA_ecearth3cc-2050',
    # runspath + casename + '_USA_ecearth3veg-2000',
    # runspath + casename + '_USA_ecearth3veg-2010',
    # runspath + casename + '_USA_ecearth3veg-2020',
    # runspath + casename + '_USA_ecearth3veg-2030',
    # runspath + casename + '_USA_ecearth3veg-2040',
    # runspath + casename + '_USA_ecearth3veg-2050',
    # runspath + casename + '_USA_gfdlcm4-2000',
    # runspath + casename + '_USA_gfdlcm4-2010',
    # runspath + casename + '_USA_gfdlcm4-2020',
    # runspath + casename + '_USA_gfdlcm4-2030',
    # runspath + casename + '_USA_gfdlcm4-2040',
    # runspath + casename + '_USA_gfdlcm4-2050',
    # runspath + casename + '_USA_mpiesm12hr-2000',
    # runspath + casename + '_USA_mpiesm12hr-2010',
    # runspath + casename + '_USA_mpiesm12hr-2020',
    # runspath + casename + '_USA_mpiesm12hr-2030',
    # runspath + casename + '_USA_mpiesm12hr-2040',
    # runspath + casename + '_USA_mpiesm12hr-2050',
    # runspath + casename + '_USA_taiesm1-2000',
    # runspath + casename + '_USA_taiesm1-2010',
    # runspath + casename + '_USA_taiesm1-2020',
    # runspath + casename + '_USA_taiesm1-2030',
    # runspath + casename + '_USA_taiesm1-2040',
    # runspath + casename + '_USA_taiesm1-2050',
]

#############
#%% PROCEDURE
#%% Set up logger
log = reeds.log.makelog(
    scriptname=__file__,
    logpath=os.path.join(os.getcwd(),'map_zone_capacity_outlog.txt'),
)

#%% Make output directory
# savepath = os.path.join(case, 'outputs', 'figures')
savepath = os.path.join('/Users','jcarag','Documents','Projects','PACES','plots','Aug10_regional_cap_diff_plots')
os.makedirs(savepath, exist_ok=True)

#%% Load colors
trtypes = pd.read_csv(
    os.path.join(reeds_path,'postprocessing','bokehpivot','in','reeds2','trtype_map.csv'),
    index_col='raw')['display']
colors = pd.read_csv(
    os.path.join(reeds_path,'postprocessing','bokehpivot','in','reeds2','trtype_style.csv'),
    index_col='order')['color']
colors = pd.concat([colors, trtypes.map(colors)])


#%% All-in-one map
dfmap = None
for case in cases:
    try:
        for sideplots in [True]:
            plt.close()
            filename_case = case.split('_')[-1]
            if casebase is not None:
                basecase = casebase.split('_')[-1]
                print(f'Starting diff plotting: {filename_case}-{level}-map_gencap-allyrs{"-sideplots" if sideplots else ""}.png')
                f,ax,eax, dfmap = reedsplots.map_zone_capacity_diff(case=casebase, casediff=case, sideplots=sideplots, level=level, dfmap=dfmap,
                                                            drawinterconnects=False, drawstates=True, drawtransgrps=True, drawregions=['r'],
                                                            width=3e4)
                savename = f'diff_{filename_case}-{level}-map_gencap-allyrs{"-sideplots" if sideplots else ""}.png'
            else: # if casebase is None:
                print(f'Starting single case plotting: {filename_case}-{level}-map_gencap-allyrs{"-sideplots" if sideplots else ""}.png')
                f,ax,eax, dfmap = reedsplots.map_zone_capacity(case=case, sideplots=sideplots, level=level, dfmap=dfmap,
                                                        drawinterconnects=False, drawstates=True, drawtransgrps=True, drawregions=['r'],
                                                        width=3e4)
                savename = f'{filename_case}-{level}-map_gencap-allyrs{"-sideplots" if sideplots else ""}.png'
            
            if write:
                print(f'Saving {savename}')
                plt.savefig(os.path.join(savepath, savename))
            if interactive:
                plt.show()
            plt.close()
            
    except Exception:
        print('map_gencap_transcap failed:')
        print(traceback.format_exc())



# %%
