"""Draw the real-world vs ReEDS battery capacity credit figures (fig_4h.png, fig_8h.png) and their
comparison tables, with ReEDS per-stress-day credits, into out/.

Usage (reeds env, gams on PATH): python make_figures.py [--skip_gams]

The empirical inputs, real_world_points.csv and published_deployment_curves.csv, are maintained in
the "Battery capacity credit by utilities, ISOs" claude.ai project; copy updated versions here.
The ReEDS annual curves come from the battery report's plcoe_pitch_storage_regional_cc_scenarios.csv,
and the stress days from each run's final restart file.
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
    case = os.path.basename(run)
    gdx = os.path.join(out, f'stressday_resmarg_{scen}.gdx')
    if '--skip_gams' not in sys.argv or not os.path.exists(gdx):
        g00 = sorted(f for f in os.listdir(os.path.join(run, 'g00files')) if f.startswith(case + '_'))[-1]
        subprocess.run(['gams', os.path.join(here, 'stressday_resmarg.gms'),
                        f'r={os.path.join(run, "g00files", g00[:-4])}', f'--outgdx={gdx}',
                        f'o={os.path.join(out, f"stressday_resmarg_{scen}.lst")}', 'lo=2',
                        f'logfile={os.path.join(out, f"stressday_resmarg_{scen}.log")}'],
                       cwd=out, check=True)
    csv = os.path.join(out, f'stressday_cc_{scen}.csv')
    subprocess.run([sys.executable, os.path.join(here, 'stressday_cc.py'), run, gdx, scen_csv, scen, csv],
                   check=True)
    days.append(pd.read_csv(csv))
pd.concat(days).to_csv(os.path.join(out, 'stressday_cc.csv'), index=False)

subprocess.run([sys.executable, os.path.join(here, 'analyze.py'), scen_csv,
                os.path.join(here, 'real_world_points.csv'), out,
                os.path.join(here, 'published_deployment_curves.csv'),
                os.path.join(out, 'stressday_cc.csv')], check=True, stdout=subprocess.DEVNULL)
print('wrote', ', '.join(sorted(f for f in os.listdir(out) if f.endswith(('.png', 'table.csv')))))
