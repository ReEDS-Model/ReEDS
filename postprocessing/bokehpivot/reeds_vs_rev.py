'''This file compares the cost escalation implied by ReEDS against the escalation in the underlying
reV supply curves, one panel per tech. The x axis is cumulative annual generation; the y axis is
marginal LCOE in a common dollar year.

reV side: the supply curve is sorted by lcoe_all_in_usd_per_mwh and cumulative annual generation is
the running sum of capacity_ac_mw * capacity_factor_ac * 8760.

ReEDS side: two ways of re-basing the marginal LCOE onto lcoe_year technology costs, plotted together
because they bracket the answer rather than one being correct.

  cost factor  base_lcoe_year * cost_factor      = base_lcoe_year + adder * (base_lcoe_year/base_year)
  LCOE adder   base_lcoe_year + lcoe_adder       = base_lcoe_year + adder

Both start from the same quantity: cost_factor is lvoe/lcoe_base and lcoe_adder is
(lvoe - lcoe_base)/force_mult, and lcoe_base carries force_mult, so each reduces to the unsubsidised
marginal LCOE (lvoe/force_mult) with force_mult cancelling exactly. They differ only in how the adder
over base cost is carried to lcoe_year: the cost factor scales it by base_lcoe_year/base_year, the
LCOE adder holds it fixed in real terms.

Neither is right on its own. The adder is partly resource quality degradation, which does scale with
plant cost because a worse capacity factor multiplies the same capex, and partly transmission, which
does not. The cost factor treats all of it as scaling and the LCOE adder treats none of it as
scaling, so the truth sits between the two lines. The gap matters: base_lcoe_year/base_year runs from
0.61 to 1.35 for UPV over the plotted years.

Each tech is compared against the supply curve from its own run - the scenario that forces that tech,
which is the scenario its core results come from - rather than against one run's curves for all
techs. See tech_run_dirs.

Curtailment basis. The ReEDS points as first drawn are on a MIXED basis: the y value comes from
LVOE, which valnew defines per UNCURTAILED MWh (the gen_ivrt_uncurt override in report.gms), while
the x value is gen_ann_nat, actual generation AFTER curtailment. The two agree while curtailment is
a few percent and diverge by 40% at 2050 in these runs, where both wind and UPV curtail about two
fifths of what they could generate. reeds_vs_rev_curtailment.png replaces that line with two
consistent ones. Pre-curtailment keeps y and puts x on gen_ivrt_uncurt, which is the like-for-like
basis against the reV curve - lcoe_all_in is built on nominal capacity factors and knows nothing of
curtailment. Post-curtailment keeps x and scales y by uncurtailed/curtailed generation, the cost per
MWh actually delivered, which answers a different question and is labelled as such. The mixed line
sits between them.

Run this file on the reeds2 conda environment. It is also imported by run_report_valcostfac.py, which
calls make_figs() so the figure lands in the report's output_dir alongside valcostfac_core.csv.
'''
import os
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
from plcoe_pitch import build_color_map, default_rc, display_tech, lcoe_base_path
from report_switches import dollar_year, lcoe_base_dollar_year

# User inputs
valcostfac_core_path = '/data/shared/projects/mmowers/ReEDS/postprocessing/bokehpivot/out/reeds_report/valcostfac_core.csv' #Only used when running this file standalone; run_report_valcostfac.py passes its own path.
scenarios_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reeds_scenarios_valcostfac.csv') #Maps each scenario name to its run directory, which supplies rev_paths.csv, dollaryear_sc.csv and deflator.csv. Also only used standalone; run_report_valcostfac.py passes its own data_source.
tech_rev_map = {'Onshore Wind': 'wind-ons', 'UPV': 'upv'} #ReEDS tech name -> rev_paths.csv tech name
lcoe_year = 2035 #Year of LCOE base to re-base ReEDS costs onto. Match the reV supply curve's cost year (confirmed ATB Moderate 2035 for both upv and wind-ons).
show_curtailment_basis = True #Also write reeds_vs_rev_curtailment.png: the cost-factor re-basing drawn on two internally consistent bases, pre- and post-curtailment, instead of the mixed one. See the module docstring.
show_adder_method = True #Also plot the LCOE-adder re-basing alongside the cost-factor one. See the module docstring; the two bracket the answer.
fit_lines = True #Overlay a least-squares line on each series and report its slope, for comparing how fast ReEDS and reV rise with generation.
target_dollar_year = dollar_year #Dollar year everything is converted to for plotting. From report_switches, so this figure shares a basis with the report and the pitch figures.
xlim_headroom = 1.08 #Extend the x axis this far past the largest ReEDS generation.
ylim_headroom = 1.18 #Extend the y axis this far past the highest line, leaving room for the summary box.

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
        #The two re-basings of the same marginal LCOE - see the module docstring. lcoe_cf scales the
        #adder over base cost by base_lcoe_year/base_year; lcoe_add holds it fixed.
        r['lcoe_cf'] = r['cost_factor'] * base.iloc[0]
        r['lcoe_add'] = base.iloc[0] + r['lcoe_adder']
        r['run_dir'] = run_dir

        #Pre- and post-curtailment generation for the tech, from the run itself. gen_twh from the
        #report is gen_ann_nat, so gen_post reproduces it and is kept as a check; gen_pre is what
        #the LVOE denominator actually is.
        prefix = rev_tech
        gu = pd.read_csv(os.path.join(run_dir, 'outputs', 'gen_ivrt_uncurt.csv'),
                         names=['i', 'v', 'r', 't', 'gen'], header=0)
        ga = pd.read_csv(os.path.join(run_dir, 'outputs', 'gen_ann_nat.csv'),
                         names=['i', 't', 'gen'], header=0)
        pre = gu[gu['i'].str.startswith(prefix)].groupby('t')['gen'].sum() / 1e6
        post = ga[ga['i'].str.startswith(prefix)].groupby('t')['gen'].sum() / 1e6
        r['gen_pre_twh'] = r['year'].map(pre)
        r['gen_post_twh'] = r['year'].map(post)
        r['curtailment'] = 1 - r['gen_post_twh'] / r['gen_pre_twh']
        #Cost per delivered MWh: the same dollars spread over the MWh that survive curtailment.
        r['lcoe_cf_post'] = r['lcoe_cf'] / (1 - r['curtailment'])

        rev_paths = pd.read_csv(os.path.join(run_dir, 'inputs_case', 'rev_paths.csv')).set_index('tech')
        sc_file = rev_paths.loc[rev_tech, 'sc_file']
        if not isinstance(sc_file, str) or not os.path.exists(sc_file):
            print(f'Skipping {tech}: supply curve not found at {sc_file}')
            continue
        factor = deflate_factor(deflator, rev_dollar_years(run_dir)[rev_tech], target_dollar_year)
        curve = build_rev_curve(sc_file, factor)

        r['rev_lcoe'] = np.interp(r['gen_twh'], curve['cum_twh'], curve['lcoe'])
        r['ratio_cf'] = r['lcoe_cf'] / r['rev_lcoe']
        r['ratio_add'] = r['lcoe_add'] / r['rev_lcoe']
        #reV sampled at pre-curtailment generation, the basis its own LCOE is on.
        r['rev_lcoe_pre'] = np.interp(r['gen_pre_twh'], curve['cum_twh'], curve['lcoe'])
        r['ratio_cf_pre'] = r['lcoe_cf'] / r['rev_lcoe_pre']
        r['sc_file'] = sc_file
        reeds[tech], curves[tech] = r, curve
    return reeds, curves


def linfit(x, y):
    """Least-squares line through (x, y), returning (slope, intercept, R^2)."""
    slope, intercept = np.polyfit(x, y, 1)
    ss_tot = ((y - y.mean()) ** 2).sum()
    r2 = np.nan if ss_tot == 0 else 1 - ((y - (intercept + slope * x)) ** 2).sum() / ss_tot
    return slope, intercept, r2


def series_specs(color, show_adder=None, basis='mixed'):
    """The lines drawn in one panel: (key, label, x column, y column, color, linestyle, marker).

    show_adder defaults to the show_adder_method switch; pass it explicitly to draw one figure each
    way from a single run. basis='mixed' is the original figure, y per uncurtailed MWh against
    post-curtailment TWh. basis='curtailment' replaces that with the two consistent lines.
    """
    if basis == 'curtailment':
        return [
            ('rev', 'reV supply curve', 'gen_pre_twh', 'rev_lcoe_pre', '0.35', '-', None),
            ('pre', 'ReEDS, pre-curtailment', 'gen_pre_twh', 'lcoe_cf', color, '-', 'o'),
            ('post', 'ReEDS, post-curtailment', 'gen_post_twh', 'lcoe_cf_post', color, '--', 's'),
        ]
    specs = [
        ('rev', 'reV supply curve', 'gen_twh', 'rev_lcoe', '0.35', '-', None),
        ('cf', 'ReEDS (cost factor)', 'gen_twh', 'lcoe_cf', color, '-', 'o'),
    ]
    if show_adder_method if show_adder is None else show_adder:
        specs.append(('add', 'ReEDS (LCOE adder)', 'gen_twh', 'lcoe_add', color, '--', 's'))
    return specs


def plot_reeds_vs_rev(reeds, curves, output_path, show_adder=None, basis='mixed'):
    """One panel per tech: the reV supply curve with the ReEDS marginal LCOE points over it.

    show_adder=False drops the LCOE-adder re-basing and leaves the multiplicative cost-factor one
    against the reV curve. The two re-basings bracket the answer (see the module docstring), so the
    both-methods figure is the honest one for judging how much the choice matters; this version is
    for reading the cost-factor comparison on its own without a second ReEDS line beside it.
    """
    techs = [t for t in tech_rev_map if t in reeds]
    colors = build_color_map(techs)
    fig, axes = plt.subplots(1, len(techs), figsize=(6.5 * len(techs), 5.2), squeeze=False)
    axes = axes[0]

    for ax, tech in zip(axes, techs):
        r, curve = reeds[tech], curves[tech]
        specs = series_specs(colors[tech], show_adder, basis)
        xmax = max(r[xc].max() for _, _, xc, _, _, _, _ in specs) * xlim_headroom

        #The full reV curve is drawn from the supply curve itself, but its fit and its summary
        #statistics use rev_lcoe - the curve sampled at the ReEDS generation levels. That puts every
        #series on the same x points, so the slopes are comparable rather than reflecting how the
        #supply curve's ~50k rows happen to be spaced.
        vis = curve[curve['cum_twh'] <= xmax]
        ax.plot(vis['cum_twh'], vis['lcoe'], color='0.35', linewidth=2.2, zorder=3)

        rows, rev_slope = [], None
        for key, label, xcol, col, color, ls, marker in specs:
            x, y = r[xcol].to_numpy(), r[col].to_numpy()
            if key != 'rev':
                ax.plot(x, y, color=color, linewidth=1.8, linestyle=ls, marker=marker,
                        markersize=5, alpha=1.0 if key in ('cf', 'pre') else 0.75, label=label,
                        zorder=4)
            else:
                #Legend handle for the curve already drawn above.
                ax.plot([], [], color=color, linewidth=2.2, label=label)
            slope = np.nan
            if fit_lines:
                slope, intercept, _ = linfit(x, y)
                ax.plot(x, intercept + slope * x, color=color, linestyle=':', linewidth=1.4,
                        alpha=0.9, zorder=5)
            if key == 'rev':
                rev_slope = slope
            rows.append((label, y[-1] / y[0], slope * 1000, slope / rev_slope if rev_slope else np.nan))

        head = f'{"over the ReEDS range":<22}{"escal.":>7}'
        if fit_lines:
            head += f'{"slope*":>9}{"vs reV":>8}'
        lines = [head]
        for label, esc, slope_k, vs_rev in rows:
            line = f'{label:<22}{"x" + format(esc, ".2f"):>7}'
            if fit_lines:
                line += f'{slope_k:>9.1f}{vs_rev:>7.1f}x'
            lines.append(line)
        if fit_lines:
            lines.append(f'*dotted fit, {target_dollar_year}$/MWh per 1000 TWh')
        ax.text(
            0.03, 0.97, '\n'.join(lines),
            transform=ax.transAxes, fontsize=7.5, family='monospace', va='top', ha='left', zorder=6,
            bbox={'facecolor': 'white', 'edgecolor': '0.7', 'boxstyle': 'round,pad=0.4', 'alpha': 0.9},
        )
        ax.set_title(display_tech(tech))
        if basis == 'curtailment':
            #The two ReEDS lines are on different x bases, so the label has to say so.
            ax.set_xlabel('Cumulative annual generation (TWh), pre- or post-curtailment per series')
        else:
            ax.set_xlabel('Cumulative annual generation (TWh)')
        ax.set_xlim(0, xmax)
        ax.set_ylim(0, ax.get_ylim()[1] * ylim_headroom) #Room for the summary box above the lines.
        ax.grid(True, linestyle='--', linewidth=0.6, alpha=0.7)
        ax.legend(loc='lower right', fontsize=9)
    axes[0].set_ylabel(f'Marginal LCOE ({target_dollar_year}$/MWh)')

    both = show_adder_method if show_adder is None else show_adder
    if basis == 'curtailment':
        sub = ' - cost-factor re-basing on consistent pre- and post-curtailment bases'
    else:
        sub = '' if both else ' - cost-factor re-basing only'
    fig.suptitle(
        f'ReEDS cost escalation vs the underlying reV supply curves '
        f'(LCOE base year {lcoe_year}){sub}', fontsize=12)
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
        #Same comparison with only the multiplicative cost-factor re-basing of the ReEDS marginal
        #LCOE. Same data and same fits as above - only the adder series is dropped - so it adds no
        #rows to reeds_vs_rev.csv.
        fig_cf = plot_reeds_vs_rev(
            reeds, curves, os.path.join(output_dir, 'reeds_vs_rev_cost-factor.png'),
            show_adder=False)
        plt.close(fig_cf)
        if show_curtailment_basis:
            fig_curt = plot_reeds_vs_rev(
                reeds, curves, os.path.join(output_dir, 'reeds_vs_rev_curtailment.png'),
                basis='curtailment')
            plt.close(fig_curt)

    #run_dir and sc_file are carried through so the table records which run and which supply curve
    #file each tech was compared against.
    out = pd.concat(
        [r[['tech', 'scenario', 'year', 'gen_twh', 'gen_frac', 'cost_factor', 'lcoe_adder',
            'lcoe_cf', 'lcoe_add', 'rev_lcoe', 'ratio_cf', 'ratio_add',
            'gen_pre_twh', 'gen_post_twh', 'curtailment', 'lcoe_cf_post', 'rev_lcoe_pre',
            'ratio_cf_pre', 'run_dir', 'sc_file']]
         for r in reeds.values()],
        ignore_index=True,
    ).rename(columns={'lcoe_cf': 'reeds_lcoe_cost_factor', 'lcoe_add': 'reeds_lcoe_adder_based'})
    out.to_csv(os.path.join(output_dir, 'reeds_vs_rev.csv'), index=False)
    return out


if __name__ == '__main__':
    make_figs()
