'''This file compares the cost escalation implied by ReEDS against the escalation in the underlying
reV supply curves, one panel per tech. The x axis is cumulative annual generation; the y axis is
marginal LCOE in a common dollar year.

reV side: the supply curve is sorted by lcoe_all_in_usd_per_mwh and cumulative annual generation is
the running sum of capacity_ac_mw * capacity_factor_ac * 8760.

ReEDS side: cost_factor * LCOE base for lcoe_year. cost_factor is lvoe / lcoe_base, and lcoe_base
carries force_mult, so this product equals (lvoe / force_mult) * (base_lcoe_year / base_year) - the
unsubsidised marginal LCOE re-based to lcoe_year costs, with force_mult cancelling exactly.

Each tech is compared against the supply curve from its own run - the scenario that forces that tech,
which is the scenario its core results come from - rather than against one run's curves for all
techs. See tech_run_dirs.

Run this file on the reeds2 conda environment. It is also imported by run_report_valcostfac.py, which
calls make_figs() so the figure lands in the report's output_dir alongside valcostfac_core.csv.
'''
import os
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
from plcoe_pitch import build_color_map, default_rc, lcoe_base_path
from report_switches import dollar_year, lcoe_base_dollar_year

# User inputs
valcostfac_core_path = '/data/shared/projects/mmowers/ReEDS/postprocessing/bokehpivot/out/reeds_report/valcostfac_core.csv' #Only used when running this file standalone; run_report_valcostfac.py passes its own path.
scenarios_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reeds_scenarios_valcostfac.csv') #Maps each scenario name to its run directory, which supplies rev_paths.csv, dollaryear_sc.csv and deflator.csv. Also only used standalone; run_report_valcostfac.py passes its own data_source.
tech_rev_map = {'Onshore Wind': 'wind-ons', 'UPV': 'upv'} #ReEDS tech name -> rev_paths.csv tech name
lcoe_year = 2035 #Year of LCOE base to re-base ReEDS costs onto. Match the reV supply curve's cost year.
target_dollar_year = dollar_year #Dollar year everything is converted to for plotting. From report_switches, so this figure shares a basis with the report and the pitch figures.
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


def tech_run_dirs(df, scenarios_path):
    """Map each tech to the run directory of the scenario its core results came from.

    Each tech appears in valcostfac_core.csv under exactly one scenario - the one that forces that
    tech, per core_tech_scen.csv - so the supply curve is taken from that same run rather than from
    an arbitrary one. The supply curve inputs happen to be identical across the runs in a given
    report, but pinning each tech to its own run keeps the comparison self-consistent if a report is
    ever built from runs on different supply curve vintages."""
    paths = pd.read_csv(scenarios_path).set_index('name')['path']
    out = {}
    for tech, scens in df.groupby('tech')['scenario'].unique().items():
        if len(scens) > 1:
            print(f'Skipping {tech}: expected one scenario in the core results, found {sorted(scens)}.')
            continue
        if scens[0] not in paths.index:
            print(f'Skipping {tech}: scenario {scens[0]!r} is not in {os.path.basename(scenarios_path)}.')
            continue
        out[tech] = paths.loc[scens[0]]
    return out


def prep_data(valcostfac_core_path=valcostfac_core_path, scenarios_path=scenarios_path):
    """Assemble the ReEDS points and the reV supply curve for each tech, in target_dollar_year $."""
    df = pd.read_csv(valcostfac_core_path)
    run_dirs = tech_run_dirs(df, scenarios_path)

    reeds, curves = {}, {}
    for tech, rev_tech in tech_rev_map.items():
        if tech not in run_dirs or tech not in set(df['tech']):
            print(f'Skipping {tech}: no core results or no run directory.')
            continue
        run_dir = run_dirs[tech]
        deflator = load_deflator(run_dir)

        #LCOE_base.csv is the unforced, pre-PTC base cost (valcostfac_core's lcoe_base_orig). Read
        #per tech because each tech's run supplies its own deflator.
        lcoe_base = pd.read_csv(lcoe_base_path)
        lcoe_base['lcoe_base'] *= deflate_factor(deflator, lcoe_base_dollar_year, target_dollar_year)
        base = lcoe_base[(lcoe_base['year'] == lcoe_year) & (lcoe_base['tech'] == tech)]['lcoe_base']
        if base.empty:
            print(f'Skipping {tech}: no {lcoe_year} LCOE base.')
            continue
        r = df[df['tech'] == tech].sort_values('gen_twh').copy()
        r['lcoe'] = r['cost_factor'] * base.iloc[0]
        r['run_dir'] = run_dir

        rev_paths = pd.read_csv(os.path.join(run_dir, 'inputs_case', 'rev_paths.csv')).set_index('tech')
        sc_file = rev_paths.loc[rev_tech, 'sc_file']
        if not isinstance(sc_file, str) or not os.path.exists(sc_file):
            print(f'Skipping {tech}: supply curve not found at {sc_file}')
            continue
        factor = deflate_factor(deflator, rev_dollar_years(run_dir)[rev_tech], target_dollar_year)
        curve = build_rev_curve(sc_file, factor)

        r['rev_lcoe'] = np.interp(r['gen_twh'], curve['cum_twh'], curve['lcoe'])
        r['ratio'] = r['lcoe'] / r['rev_lcoe']
        r['sc_file'] = sc_file
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


def make_figs(valcostfac_core_path=valcostfac_core_path, scenarios_path=scenarios_path, output_dir=None):
    """Write the comparison figure and the underlying table next to valcostfac_core.csv."""
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(valcostfac_core_path))
    reeds, curves = prep_data(valcostfac_core_path, scenarios_path)
    if not reeds:
        print('Nothing to plot.')
        return None

    with matplotlib.rc_context(default_rc):
        fig = plot_reeds_vs_rev(reeds, curves, os.path.join(output_dir, 'reeds_vs_rev.png'))
        plt.close(fig)

    #run_dir and sc_file are carried through so the table records which run and which supply curve
    #file each tech was compared against.
    out = pd.concat(
        [r[['tech', 'scenario', 'year', 'gen_twh', 'gen_frac', 'cost_factor',
            'lcoe', 'rev_lcoe', 'ratio', 'run_dir', 'sc_file']] for r in reeds.values()],
        ignore_index=True,
    ).rename(columns={'lcoe': 'reeds_lcoe'})
    out.to_csv(os.path.join(output_dir, 'reeds_vs_rev.csv'), index=False)
    return out


if __name__ == '__main__':
    make_figs()
