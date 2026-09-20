"""
Levelized value of energy (LVOE) for a flat generator (e.g. geothermal) in each region and
solve year of a ReEDS run, broken down by the service it's paid for:
    Energy:          hours(h) * avail(h) * energy price (eq_supply_demand_balance marginal)
    Reserve margin:  avail(h) * stress-period price (eq_supply_demand_balance marginal in stress h)
    State RPS/CES:   state REC-requirement marginals (1 credit per MWh; assumes full eligibility)
    National CES:    eq_national_gen marginal (1 credit per MWh), if nonzero
Each stream is calculated in $/MW-yr and divided by annual generation per MW (the plant's
contribution to the energy balance) to get $/MWh; $/kW-yr is also reported.

Two generation profiles are evaluated:
    avail: the tech's timeslice availability from the case inputs (forced + scheduled outages),
           which is how ReEDS actually dispatches a must-run thermal tech
    flat:  an ideal 1.0-availability block, as an upper bound

Prices are inflated from the case's dollar year to --dollar_year (default: bokehpivot default).

Usage:
    python postprocessing/converge/geothermal_lvoe.py runs/{case} [--tech geothermal]
Outputs are written to runs/{case}/outputs/converge/.
"""
#%% Imports
import os
import sys
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import reeds
from reeds import plots
sys.path.append(os.path.join(reeds.io.reeds_path, 'postprocessing', 'bokehpivot'))
from defaults import DEFAULT_DOLLAR_YEAR

plots.plotparams()

SERVICES = ['Energy', 'Reserve margin', 'State RPS/CES', 'National CES']
COLORS = {
    'Energy': '#4C78A8',
    'Reserve margin': '#F58518',
    'State RPS/CES': '#54A24B',
    'National CES': '#B279A2',
}
PROFILES = {'avail': 'Modeled availability', 'flat': 'Flat block (avail = 1)'}


#%% Functions
def get_stress_dir(case, year, stress_h):
    """Find the stress{year}i* folder whose timeslices match the res_marg prices for {year}"""
    inputs_case = os.path.join(case, 'inputs_case')
    candidates = sorted(
        [d for d in os.listdir(inputs_case) if d.startswith(f'stress{year}i')],
        key=lambda d: int(d.split('i')[-1]), reverse=True,
    )
    for d in candidates:
        hset = set(pd.read_csv(os.path.join(inputs_case, d, 'numhours.csv')).iloc[:,0])
        if set(stress_h) <= hset:
            return os.path.join(inputs_case, d)
    raise FileNotFoundError(f'No stress folder for {year} matches the res_marg timeslices')


def get_avail(folder, tech, regions):
    """avail(r,h) = (1 - forced outage) * (1 - scheduled outage) as written for GAMS"""
    forced = pd.read_csv(os.path.join(folder, 'outage_forced_h.csv'))
    forced.columns = ['i', 'r', 'h', 'rate']
    forced = forced.loc[(forced.i == tech) & forced.r.isin(regions)].set_index(['r', 'h']).rate
    scheduled = pd.read_csv(os.path.join(folder, 'outage_scheduled_h.csv'))
    scheduled.columns = ['i', 'h', 'rate']
    scheduled = scheduled.loc[scheduled.i == tech].set_index('h').rate
    if forced.empty or scheduled.empty:
        raise ValueError(f'No outage rates found for tech={tech} in {folder}')
    avail = pd.Series(
        {(r, h): (1 - forced[r, h]) * (1 - scheduled[h]) for (r, h) in forced.index}
    ).round(3)
    return avail


def get_lvoe(case, tech='geothermal', dollar_year=DEFAULT_DOLLAR_YEAR):
    sw = reeds.io.get_switches(case)
    inflator = reeds.io.get_inflatable()[int(sw['dollar_year']), dollar_year]

    prices = reeds.io.read_output(case, 'reqt_price')
    prices.columns = ['type', 'subtype', 'r', 'h', 't', 'value']
    prices['value'] *= inflator
    hours = reeds.io.read_output(case, 'hours').set_index('h').Value
    regions = sorted(prices.r.unique())
    avail_rep = get_avail(os.path.join(case, 'inputs_case', 'rep'), tech, regions)

    rows = []
    for t, dft in prices.groupby('t'):
        energy = dft.loc[dft.type == 'load'].set_index(['r', 'h']).value
        resmarg = dft.loc[dft.type == 'res_marg'].set_index(['r', 'h']).value
        state_rps = dft.loc[dft.type == 'state_rps'].groupby('r').value.sum()
        nat_gen = dft.loc[dft.type == 'nat_gen'].groupby('r').value.sum()
        if len(resmarg):
            avail_stress = get_avail(
                get_stress_dir(case, t, resmarg.index.get_level_values('h').unique()),
                tech, regions)
        for r in regions:
            ## Rep-period timeslices: value per MW-yr
            h_rep = energy.loc[r].index
            for profile in PROFILES:
                a_rep = avail_rep.loc[r].reindex(h_rep) if profile == 'avail' else pd.Series(1.0, index=h_rep)
                gen_per_mw = (hours.reindex(h_rep) * a_rep).sum()
                value = {
                    'Energy': (hours.reindex(h_rep) * a_rep * energy.loc[r]).sum(),
                    'State RPS/CES': state_rps.get(r, 0) * gen_per_mw,
                    'National CES': nat_gen.get(r, 0) * gen_per_mw,
                }
                if len(resmarg) and (r in resmarg.index.get_level_values('r')):
                    h_stress = resmarg.loc[r].index
                    a_stress = avail_stress.loc[r].reindex(h_stress) if profile == 'avail' else 1.0
                    value['Reserve margin'] = (resmarg.loc[r] * a_stress).sum()
                else:
                    value['Reserve margin'] = 0.0
                for service in SERVICES:
                    rows.append({
                        't': t, 'r': r, 'profile': profile, 'service': service,
                        'cf': gen_per_mw / 8760,
                        'usd_per_mwh': value[service] / gen_per_mw,
                        'usd_per_kwyr': value[service] / 1e3,
                    })
    lvoe = pd.DataFrame(rows)
    ## Drop services that are zero everywhere (e.g. no national CES)
    keep = lvoe.groupby('service').usd_per_mwh.apply(lambda x: x.abs().sum() > 0)
    lvoe = lvoe.loc[lvoe.service.isin(keep[keep].index)]
    return lvoe


def plot_lvoe(lvoe, column, unit, title, savepath):
    """Stacked bars of LVOE by service over years; rows = regions, columns = profiles"""
    regions = sorted(lvoe.r.unique())
    years = sorted(lvoe.t.unique())
    services = [s for s in SERVICES if s in lvoe.service.unique()]
    nrows, ncols = len(regions), len(PROFILES)
    fig, axes = plt.subplots(
        nrows, ncols, figsize=(1.6 + 1.1 * len(years) * ncols, 2.6 * nrows),
        sharex=True, sharey=True, squeeze=False, dpi=150,
    )
    ymax = lvoe.groupby(['t', 'r', 'profile'])[column].sum().max()
    for i, r in enumerate(regions):
        for j, profile in enumerate(PROFILES):
            ax = axes[i, j]
            df = (
                lvoe.loc[(lvoe.r == r) & (lvoe.profile == profile)]
                .pivot(index='t', columns='service', values=column)
                .reindex(index=years, columns=services).fillna(0)
            )
            bottom = np.zeros(len(years))
            for service in services:
                ax.bar(
                    df.index, df[service], bottom=bottom, width=3.6,
                    color=COLORS[service], edgecolor='white', linewidth=0.8, label=service,
                )
                bottom += df[service].values
            for x, y in zip(df.index, bottom):
                if y > 0:
                    ax.annotate(f'{y:.0f}', (x, y), ha='center', va='bottom',
                                fontsize=8, xytext=(0, 2), textcoords='offset points')
            ax.set_title(f'{r} — {PROFILES[profile]}', fontsize=10, loc='left')
            ax.grid(axis='y', color='0.9', lw=0.6)
            ax.set_axisbelow(True)
            ax.set_xticks(years)
            ax.tick_params(labelsize=8, top=False, right=False)
            for side in ['top', 'right']:
                ax.spines[side].set_visible(False)
            if j == 0:
                ax.set_ylabel(unit, fontsize=9, fontweight='normal')
    axes[0, 0].set_ylim(0, ymax * 1.12)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(
        handles[::-1], labels[::-1], loc='upper left', bbox_to_anchor=(1.0, 0.98),
        frameon=False, fontsize=9,
    )
    fig.suptitle(title, x=0.01, ha='left', fontsize=11)
    fig.tight_layout()
    fig.savefig(savepath, bbox_inches='tight')
    plt.close(fig)


#%% Main
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='LVOE by service for a flat generator in each region and year',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('case', type=str, help='path to ReEDS run folder')
    parser.add_argument('--tech', '-i', type=str, default='geothermal',
                        help='tech name used in outage_forced_h.csv / outage_scheduled_h.csv')
    parser.add_argument('--dollar_year', '-d', type=int, default=DEFAULT_DOLLAR_YEAR,
                        help='output dollar year')
    args = parser.parse_args()
    case = os.path.abspath(args.case)

    outpath = os.path.join(case, 'outputs', 'converge')
    os.makedirs(outpath, exist_ok=True)

    lvoe = get_lvoe(case, tech=args.tech, dollar_year=args.dollar_year)
    lvoe.round(4).to_csv(os.path.join(outpath, f'lvoe_{args.tech}.csv'), index=False)

    casename = os.path.basename(case)
    for column, unit in [('usd_per_mwh', f'{args.dollar_year}$/MWh'),
                         ('usd_per_kwyr', f'{args.dollar_year}$/kW-yr')]:
        plot_lvoe(
            lvoe, column, unit,
            title=f'{casename}: {args.tech} LVOE by service [{unit}]',
            savepath=os.path.join(outpath, f'lvoe_{args.tech}-{column}.png'),
        )

    ## Print a summary table of the modeled-availability profile in $/MWh
    summary = (
        lvoe.loc[lvoe.profile == 'avail']
        .pivot_table(index=['r', 't'], columns='service', values='usd_per_mwh')
    )
    summary['Total'] = summary.sum(axis=1)
    print(f'\nLVOE [{args.dollar_year}$/MWh], modeled availability profile:')
    print(summary.round(2).to_string())
    print(f'\nOutputs written to {outpath}')
