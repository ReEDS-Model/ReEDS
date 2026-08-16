'''This file compares the cost escalation implied by ReEDS against the escalation in the underlying
reV supply curves, one panel per tech. The x axis is cumulative annual generation; the y axis is
marginal LCOE in a common dollar year.

reV side: the supply curve is sorted by lcoe_all_in_usd_per_mwh and cumulative annual generation is
the running sum of capacity_ac_mw * capacity_factor_ac * 8760.

ReEDS side: cost_factor * LCOE base for lcoe_year. cost_factor is lvoe / lcoe_base, and lcoe_base
carries force_mult, so this product equals (lvoe / force_mult) * (base_lcoe_year / base_year) - the
unsubsidised marginal LCOE re-based to lcoe_year costs, with force_mult cancelling exactly.

Run this file on the reeds2 conda environment.
'''
import os
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from plcoe_pitch import build_color_map, default_rc, lcoe_base_path, lcoe_usd_mult

# User inputs
valcostfac_core_path = '/data/shared/projects/mmowers/ReEDS/postprocessing/bokehpivot/out/reeds_report/valcostfac_core.csv'
run_dir = '/data/shared/projects/mmowers/ReEDS/runs/vcf4_ref' #Supplies rev_paths.csv, dollaryear_sc.csv and deflator.csv. The supply curve inputs are identical across the vcf4_* runs, so any of them will do.
tech_rev_map = {'Onshore Wind': 'wind-ons', 'UPV': 'upv'} #ReEDS tech name -> rev_paths.csv tech name
lcoe_year = 2035 #Year of LCOE base to re-base ReEDS costs onto. Match the reV supply curve's cost year.
lcoe_base_dollar_year = 2022 #Dollar year of LCOE_base.csv, per run_report_valcostfac.py.
target_dollar_year = 2023 #Dollar year everything is converted to for plotting.
xlim_headroom = 1.08 #Extend the x axis this far past the largest ReEDS generation.

this_dir = os.path.dirname(os.path.abspath(__file__))
sc_cols = ['capacity_ac_mw', 'capacity_factor_ac', 'lcoe_all_in_usd_per_mwh']


def load_deflator(run_dir):
    """Deflator series from the run, indexed by dollar year."""
    return pd.read_csv(
        os.path.join(run_dir, 'inputs_case', 'deflator.csv'), index_col='*Dollar.Year',
    ).squeeze(1)


def deflate_factor(deflator, from_year, to_year):
    """Multiplier converting from_year dollars into to_year dollars."""
    return deflator.loc[from_year] / deflator.loc[to_year]


def rev_dollar_years(run_dir):
    """Supply curve dollar years, keyed by the rev_paths tech name.

    These are not all the same: wind-ons is 2022 while upv and wind-ofs are 2023, so each tech has to
    be deflated separately. writesupplycurves.py reads the same file to deflate the ReEDS inputs.
    """
    dy = pd.read_csv(
        os.path.join(run_dir, 'inputs_case', 'dollaryear_sc.csv'), index_col='Scenario',
    ).squeeze(1)
    return {k[len('supplycurve_'):]: int(v) for k, v in dy.items() if k.startswith('supplycurve_')}


def build_rev_curve(sc_file, usd_factor):
    """Supply curve as (cumulative annual TWh, marginal LCOE), sorted cheapest first."""
    sc = pd.read_csv(sc_file, usecols=sc_cols).dropna(subset=sc_cols)
    sc = sc[(sc['capacity_ac_mw'] > 0) & (sc['capacity_factor_ac'] > 0)]
    sc = sc.sort_values('lcoe_all_in_usd_per_mwh')
    sc['lcoe'] = sc['lcoe_all_in_usd_per_mwh'] * usd_factor
    sc['cum_twh'] = (sc['capacity_ac_mw'] * sc['capacity_factor_ac'] * 8760 / 1e6).cumsum()
    return sc[['cum_twh', 'lcoe']].reset_index(drop=True)


def prep_data(valcostfac_core_path=valcostfac_core_path, run_dir=run_dir):
    """Assemble the ReEDS points and the reV supply curve for each tech, in target_dollar_year $."""
    df = pd.read_csv(valcostfac_core_path)
    deflator = load_deflator(run_dir)
    sc_dollar_years = rev_dollar_years(run_dir)
    rev_paths = pd.read_csv(os.path.join(run_dir, 'inputs_case', 'rev_paths.csv')).set_index('tech')

    #LCOE_base.csv is the unforced, pre-PTC base cost (valcostfac_core's lcoe_base_orig).
    lcoe_base = pd.read_csv(lcoe_base_path)
    lcoe_base['lcoe_base'] *= deflate_factor(deflator, lcoe_base_dollar_year, target_dollar_year)
    base = lcoe_base[lcoe_base['year'] == lcoe_year].set_index('tech')['lcoe_base']

    reeds, curves = {}, {}
    for tech, rev_tech in tech_rev_map.items():
        if tech not in base.index or tech not in set(df['tech']):
            print(f'Skipping {tech}: no LCOE base or no core results.')
            continue
        r = df[df['tech'] == tech].sort_values('gen_twh').copy()
        r['lcoe'] = r['cost_factor'] * base[tech]

        sc_file = rev_paths.loc[rev_tech, 'sc_file']
        if not isinstance(sc_file, str) or not os.path.exists(sc_file):
            print(f'Skipping {tech}: supply curve not found at {sc_file}')
            continue
        factor = deflate_factor(deflator, sc_dollar_years[rev_tech], target_dollar_year)
        curve = build_rev_curve(sc_file, factor)

        r['rev_lcoe'] = np.interp(r['gen_twh'], curve['cum_twh'], curve['lcoe'])
        r['ratio'] = r['lcoe'] / r['rev_lcoe']
        reeds[tech], curves[tech] = r, curve
    return reeds, curves


def plot_reeds_vs_rev(reeds, curves, output_path):
    """One panel per tech: the reV supply curve with the ReEDS marginal LCOE points over it."""
    techs = [t for t in tech_rev_map if t in reeds]
    colors = build_color_map(techs)
    fig, axes = plt.subplots(1, len(techs), figsize=(6.5 * len(techs), 5.2), squeeze=False)
    axes = axes[0]

    for ax, tech in zip(axes, techs):
        r, curve = reeds[tech], curves[tech]
        xmax = r['gen_twh'].max() * xlim_headroom
        vis = curve[curve['cum_twh'] <= xmax]
        ax.plot(vis['cum_twh'], vis['lcoe'], color='0.35', linewidth=2.2,
                label='reV supply curve', zorder=3)
        ax.plot(r['gen_twh'], r['lcoe'], color=colors[tech], linewidth=1.8, marker='o',
                markersize=5, label='ReEDS marginal LCOE', zorder=4)

        esc_reeds = r['lcoe'].iloc[-1] / r['lcoe'].iloc[0]
        esc_rev = r['rev_lcoe'].iloc[-1] / r['rev_lcoe'].iloc[0]
        ax.text(
            0.03, 0.97,
            f'escalation over the ReEDS range\n'
            f'  ReEDS  x{esc_reeds:.2f}\n'
            f'  reV      x{esc_rev:.2f}',
            transform=ax.transAxes, fontsize=9, va='top', ha='left', zorder=6,
            bbox={'facecolor': 'white', 'edgecolor': '0.7', 'boxstyle': 'round,pad=0.4', 'alpha': 0.9},
        )
        ax.set_title(tech)
        ax.set_xlabel('Cumulative annual generation (TWh)')
        ax.set_xlim(0, xmax)
        ax.set_ylim(bottom=0)
        ax.grid(True, linestyle='--', linewidth=0.6, alpha=0.7)
        ax.legend(loc='lower right', fontsize=9)
    axes[0].set_ylabel(f'Marginal LCOE ({target_dollar_year}$/MWh)')

    fig.suptitle(
        f'ReEDS cost escalation vs the underlying reV supply curves '
        f'(LCOE base year {lcoe_year})', fontsize=12)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches='tight')
    return fig


def make_figs(valcostfac_core_path=valcostfac_core_path, run_dir=run_dir, output_dir=None):
    """Write the comparison figure and the underlying table next to valcostfac_core.csv."""
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(valcostfac_core_path))
    reeds, curves = prep_data(valcostfac_core_path, run_dir)
    if not reeds:
        print('Nothing to plot.')
        return None

    with matplotlib.rc_context(default_rc):
        fig = plot_reeds_vs_rev(reeds, curves, os.path.join(output_dir, 'reeds_vs_rev.png'))
        plt.close(fig)

    out = pd.concat(
        [r[['tech', 'scenario', 'year', 'gen_twh', 'gen_frac', 'cost_factor',
            'lcoe', 'rev_lcoe', 'ratio']] for r in reeds.values()],
        ignore_index=True,
    ).rename(columns={'lcoe': 'reeds_lcoe'})
    out.to_csv(os.path.join(output_dir, 'reeds_vs_rev.csv'), index=False)
    return out


if __name__ == '__main__':
    make_figs()
