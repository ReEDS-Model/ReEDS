"""Draw the real-world vs ReEDS battery capacity credit figures (fig_4h.png, fig_8h.png) and their
comparison tables, with ReEDS per-stress-day credits, and the stress-day dispatch figures
(fig_dispatch_*.png) into out/.

Usage (reeds env): python make_figures.py

The empirical inputs, real_world_points.csv and published_deployment_curves.csv, are maintained in
the "Battery capacity credit by utilities, ISOs" claude.ai project; copy updated versions here.
The ReEDS annual curves come from the battery report's plcoe_pitch_storage_regional_cc_scenarios.csv,
and the stress days from each run's outputs folder.
"""
import os, sys, subprocess
import pandas as pd

here = os.path.dirname(os.path.abspath(__file__))
reeds = os.path.dirname(os.path.dirname(here))
out = os.path.join(here, 'out')
scen_csv = os.path.join(reeds, 'postprocessing', 'bokehpivot', 'out', 'reeds_report',
                        'plcoe_pitch_storage_regional_cc_scenarios.csv')
runs = {'battery_4h': os.path.join(reeds, 'runs', 'vcf6_battery_4h'),
        'battery_8h': os.path.join(reeds, 'runs', 'vcf6_battery_8h')}
os.makedirs(out, exist_ok=True)

days = []
for scen, run in runs.items():
    csv = os.path.join(out, f'stressday_cc_{scen}.csv')
    subprocess.run([sys.executable, os.path.join(here, 'stressday_cc.py'), run, scen_csv, scen, csv],
                   check=True)
    days.append(pd.read_csv(csv))
pd.concat(days).to_csv(os.path.join(out, 'stressday_cc.csv'), index=False)

subprocess.run([sys.executable, os.path.join(here, 'analyze.py'), scen_csv,
                os.path.join(here, 'real_world_points.csv'), out,
                os.path.join(here, 'published_deployment_curves.csv'),
                os.path.join(out, 'stressday_cc.csv')], check=True, stdout=subprocess.DEVNULL)
# dispatch on the stress days behind the dots, for the ISOs in each figure's panels
dispatch_isos = {'battery_4h': 'PJM,MISO,ERCOT,SPP,CAISO,NYISO,ISONE,WestConnect,NorthernGrid',
                 'battery_8h': 'PJM,SPP,CAISO,NYISO,ISONE'}
for scen, isos in dispatch_isos.items():
    subprocess.run([sys.executable, os.path.join(here, 'stressday_dispatch.py'), runs[scen],
                    os.path.join(out, 'stressday_cc.csv'), scen_csv, scen, out, isos],
                   check=True, stdout=subprocess.DEVNULL)
print('wrote', ', '.join(sorted(f for f in os.listdir(out) if f.endswith(('.png', 'table.csv')))))
