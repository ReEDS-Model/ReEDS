'''Rewrites the Battery rows of LCOE_base.csv from a ReEDS run's own battery cost inputs.

The Battery LCOE base is a four-hour battery_li cycling once a day (capacity factor 4/24), with
capital annualized as the sequential solve does: crf * cost_cap_fin_mult * (capcost + 4 *
capcost_energy) + fom + 4 * fom_energy, per MW-yr. capcost_energy is taken from plantcharout.csv,
so it includes the discounted mid-life refurbishment of the energy capacity that plantcostprep.py
adds, and cost_cap_fin_mult is the unweighted mean over regions. run_report_valcostfac.py turns
this back into $/kW-yr with the same 4/24, so the per-kW cost factor of a four-hour build is 1
up to the regional multipliers of where it is built.

The run's battery cost inputs and financing do not depend on which tech it forces, but its
outputs/cost_cap_fin_mult.csv must exist (written by the run's reporting). Writes 2022$, the
dollar year of LCOE_base.csv.

Run this file on the reeds conda environment.
'''
import os
import pandas as pd
from report_switches import lcoe_base_dollar_year, start_year

# User inputs
run_dir = '/data/shared/projects/mmowers/ReEDS/runs/vcf6_battery' #Any post-merge run.
duration = 4 #Hours of energy per MW of power in the reference battery.
lcoe_base_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'LCOE_base.csv')


def battery_lcoe_base(run_dir, duration=duration):
    """$/MWh in lcoe_base_dollar_year by year, for the years in plantcharout.csv."""
    inp = os.path.join(run_dir, 'inputs_case')
    pc = pd.read_csv(os.path.join(inp, 'plantcharout.csv'))
    pc.columns = ['i', 't', 'variable', 'value']
    pc = pc[pc['i'] == 'battery_li'].pivot(index='t', columns='variable', values='value')
    crf = pd.read_csv(os.path.join(inp, 'financials_sys_full.csv')).set_index('t')['crf']
    fin = pd.read_csv(os.path.join(run_dir, 'outputs', 'cost_cap_fin_mult.csv'))
    fin.columns = ['i', 'r', 't', 'value']
    fin = fin[fin['i'] == 'battery_li'].groupby('t')['value'].mean()
    #cost_cap_fin_mult is only written for model years, so fill the years between and beyond.
    fin = fin.reindex(pc.index).interpolate().ffill().bfill()
    #Before start_year both are historical (crf is 0.033 in 2022), so hold them at start_year.
    crf = crf.reindex(pc.index)
    crf[crf.index < start_year] = crf[start_year]
    fin[fin.index < start_year] = fin[start_year]
    deflator = pd.read_csv(os.path.join(inp, 'deflator.csv'), index_col=0).iloc[:, 0]
    annual = (crf * fin * (pc['capcost'] + duration * pc['capcost_energy'])
              + pc['fom'] + duration * pc['fom_energy']) #2004$/MW-yr
    return annual / deflator[lcoe_base_dollar_year] / (duration / 24 * 8760)


if __name__ == '__main__':
    df = pd.read_csv(lcoe_base_path)
    keep = df['tech'] != 'Battery'
    years = df.loc[~keep, 'year']
    new = battery_lcoe_base(run_dir).reindex(years).rename('lcoe_base').reset_index()
    new = new.rename(columns={'t': 'year'})
    new.insert(0, 'tech', 'Battery')
    pd.concat([df[keep], new]).to_csv(lcoe_base_path, index=False)
    print(new.to_string(index=False))
