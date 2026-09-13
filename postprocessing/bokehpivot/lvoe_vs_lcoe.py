'''This file checks the assumption that the marginal LCOE of a technology equals its weighted-average
LVOE, by putting LVOE against the distribution of ReEDS' own LCOE outputs for the same year.

Both sides are per uncurtailed MWh, which is what makes the comparison valid. report.gms sets
valnew('MWh') from gen_ivrt_uncurt for any tech with uncurtailed generation - so LVOE is value per
MWh generated before curtailment - and lcoe_nopol divides by gen_rsc, which is sum{h, m_cf * hours},
a nominal capacity factor with no curtailment term. lcoe_cf_act exists precisely because it uses
realised avg_cf instead, so it is the one variant that must NOT be used here.

lcoe is the right variant for these ForceMandate runs, and lcoe_nopol is not. ForceMandate scales
cost_cap, cost_fom, cost_vom and rsc_fin_mult by forcetechmult (2_financials.gms), and lcoe picks the
supply-curve term up as m_rsc_dat(...,"cost") * rsc_fin_mult_out, so every component carries the
multiplier. lcoe_nopol takes m_rsc_dat(...,"cost") with no rsc_fin_mult, leaving plant costs scaled
and transmission costs unscaled - a hybrid that is increasingly dominated by the unscaled term as
forcetechmult falls, which manufactures a drift that is not in the model.

lcoe is also defined only where INV_RSC is nonzero, so it covers exactly the bins invested in. That
is what makes it small (806 UPV rows against 71,879) and exactly what this comparison wants.

Boxes are weighted by chosen capacity, so they describe what the model actually built rather than
treating every supply-curve bin as one observation regardless of size, and the dashed line is the
capacity-weighted mean of the same distribution - the direct partner to LVOE, which is a weighted
average of value over the same MWh. Statistics over available capacity are not produced, since lcoe
does not exist for bins the model did not invest in.

Run this file on the reeds2 conda environment.
'''
import os
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from plcoe_pitch import build_color_map, cost_color, default_rc, display_tech
from reeds_vs_rev import tech_run_dirs, load_deflator, deflate_factor
from matplotlib.colors import Normalize
from report_switches import dollar_year

# User inputs
valcostfac_core_path = '/data/shared/projects/mmowers/ReEDS/postprocessing/bokehpivot/out/reeds_report/valcostfac_core.csv' #Only used when running this file standalone.
scenarios_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reeds_scenarios_valcostfac.csv') #Maps each scenario name to its run directory.
tech_prefix_map = {'Onshore Wind': 'wind-ons', 'UPV': 'upv'} #ReEDS tech name -> prefix of the raw tech names in the run outputs.
lcoe_file = 'lcoe' #See the module docstring. Not lcoe_nopol, which leaves the supply-curve cost unscaled by the mandate, and not lcoe_cf_act, whose denominator is curtailment-adjusted.
reeds_dollar_year = 2004 #Dollar year of the raw GAMS outputs.
box_pcts = (0.25, 0.75) #Box edges, as capacity-weighted percentiles.
whisker_pcts = (0.10, 0.90) #Whisker ends. Not Tukey - stated on the figure.
scatter_descale = True #On the by-year scatter, divide LCOE by force_mult so it is the unforced cost rather than the mandate-scaled one the model optimised on. LVOE is already unforced. With both unforced the 45-degree line means "worth what it costs at unforced prices"; with LCOE scaled it would mean "worth what the model paid", and points would sit far above the line simply because the mandate made them cheap.
scatter_year_step = 4 #Calendar-year stride for the by-year scatter, matching spatial_value's byyear_year_step so the columns line up with the maps.
scatter_size_max = 260 #Marker area in points^2 for the largest AEP in the figure; sizes scale linearly with AEP from there.
scatter_pen_cmap = 'YlOrRd' #Colours each dot by the penetration of its region.

lcoe_cols = ['tech', 'vintage', 'rb', 'year', 'bin', 'lcoe']
avail_cols = ['tech', 'rb', 'year', 'bin', 'avail_mw']
chosen_cols = ['tech', 'vintage', 'rb', 'year', 'bin', 'chosen_mw']


def weighted_quantile(values, weights, quantiles):
    """Capacity-weighted quantiles, so a 5 MW bin does not count the same as a 500 MW one."""
    values, weights = np.asarray(values, float), np.asarray(weights, float)
    keep = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if keep.sum() == 0:
        return None
    values, weights = values[keep], weights[keep]
    order = np.argsort(values)
    values, weights = values[order], weights[order]
    cum = np.cumsum(weights) / np.sum(weights)
    return np.interp(quantiles, cum, values)


def weighted_mean(values, weights):
    """Capacity-weighted mean, the direct like-for-like partner to LVOE - which is itself a
    weighted average, of value rather than cost, over the same uncurtailed MWh basis."""
    values, weights = np.asarray(values, float), np.asarray(weights, float)
    keep = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if keep.sum() == 0:
        return np.nan
    return np.average(values[keep], weights=weights[keep])


def load_lcoe(run_dir, prefix, usd_factor):
    """The run's LCOE distribution for one tech, with available and chosen capacity alongside."""
    out = os.path.join(run_dir, 'outputs')
    lcoe = pd.read_csv(os.path.join(out, f'{lcoe_file}.csv'), names=lcoe_cols, header=0)
    avail = pd.read_csv(os.path.join(out, 'cap_avail.csv'), names=avail_cols, header=0)
    chosen = pd.read_csv(os.path.join(out, 'cap_new_bin_out.csv'), names=chosen_cols, header=0)
    lcoe = lcoe[lcoe['tech'].str.startswith(prefix)].copy()
    lcoe['lcoe'] = lcoe['lcoe'] * usd_factor
    #vintage is uniquely determined by year in these outputs, so neither merge duplicates rows.
    lcoe = lcoe.merge(avail, on=['tech', 'rb', 'year', 'bin'], how='left')
    lcoe = lcoe.merge(chosen, on=['tech', 'vintage', 'rb', 'year', 'bin'], how='left')
    lcoe[['avail_mw', 'chosen_mw']] = lcoe[['avail_mw', 'chosen_mw']].fillna(0)
    #lcoe only exists where the model invested, so available-capacity statistics would be taken over
    #the chosen bins alone and would not describe the opportunity set. They are not computed.
    return lcoe


def prep_data(valcostfac_core_path=valcostfac_core_path, scenarios_path=scenarios_path):
    """Per tech: the LVOE series, and per-year capacity-weighted LCOE percentiles."""
    df = pd.read_csv(valcostfac_core_path)
    run_dirs = tech_run_dirs(df, scenarios_path)
    qs = [whisker_pcts[0], box_pcts[0], 0.5, box_pcts[1], whisker_pcts[1]]

    out = {}
    for tech, prefix in tech_prefix_map.items():
        if tech not in run_dirs:
            print(f'Skipping {tech}: no run directory.')
            continue
        run_dir = run_dirs[tech]
        usd = deflate_factor(load_deflator(run_dir), reeds_dollar_year, dollar_year)
        lcoe = load_lcoe(run_dir, prefix, usd)
        lv = df[df['tech'] == tech].sort_values('year')

        rows = []
        for _, r in lv.iterrows():
            g = lcoe[lcoe['year'] == r['year']]
            ch = weighted_quantile(g['lcoe'], g['chosen_mw'], qs)
            rows.append({
                'tech': tech, 'scenario': r['scenario'], 'year': int(r['year']),
                'gen_frac': r['gen_frac'], 'lvoe': r['lvoe'], 'force_mult': r['force_mult'],
                'chosen_mw': g['chosen_mw'].sum(), 'avail_mw': g['avail_mw'].sum(),
                'chosen_mean': weighted_mean(g['lcoe'], g['chosen_mw']),
                'lvoe_over_lcoe': r['lvoe'] / weighted_mean(g['lcoe'], g['chosen_mw']),
                **{f'chosen_p{int(q*100)}': (np.nan if ch is None else ch[i])
                   for i, q in enumerate(qs)},
            })
        out[tech] = pd.DataFrame(rows)
    return out


def plot_lvoe_vs_lcoe(data, output_path):
    """One panel per tech: LVOE over boxes of the LCOE actually built that year."""
    techs = [t for t in tech_prefix_map if t in data]
    colors = build_color_map(techs)
    fig, axes = plt.subplots(1, len(techs), figsize=(7.4 * len(techs), 5.2), squeeze=False)
    axes = axes[0]
    lo, hi = f'p{int(whisker_pcts[0]*100)}', f'p{int(whisker_pcts[1]*100)}'
    q1, q3 = f'p{int(box_pcts[0]*100)}', f'p{int(box_pcts[1]*100)}'

    for ax, tech in zip(axes, techs):
        t = data[tech]
        pos = np.arange(len(t))
        stats = [
            {'label': '', 'med': r[f'chosen_p50'], 'q1': r[f'chosen_{q1}'], 'q3': r[f'chosen_{q3}'],
             'whislo': r[f'chosen_{lo}'], 'whishi': r[f'chosen_{hi}'], 'fliers': []}
            for _, r in t.iterrows() if np.isfinite(r['chosen_p50'])
        ]
        keep = [i for i, (_, r) in enumerate(t.iterrows()) if np.isfinite(r['chosen_p50'])]
        if stats:
            ax.bxp(stats, positions=pos[keep], widths=0.55, showfliers=False, zorder=3,
                   boxprops={'facecolor': 'white', 'edgecolor': cost_color},
                   medianprops={'color': cost_color, 'linewidth': 1.6},
                   whiskerprops={'color': cost_color}, capprops={'color': cost_color},
                   patch_artist=True)
        #The two lines are the comparison: a capacity-weighted mean cost against a generation-
        #weighted mean value, on the same uncurtailed MWh basis. They coincide where the marginal
        #unit is worth what it costs.
        ax.plot(pos, t['chosen_mean'], color=cost_color, marker='s', markersize=4.5,
                linestyle='--', linewidth=1.5, alpha=0.9, zorder=4,
                label='LCOE built (weighted average)')
        ax.plot(pos, t['lvoe'], color=colors[tech], marker='o', markersize=5, linewidth=1.8,
                zorder=5, label='LVOE (weighted average)')

        ax.set_xticks(pos)
        ax.set_xticklabels([f'{y}\n{g:.2f}' for y, g in zip(t['year'], t['gen_frac'])], fontsize=7)
        ax.set_title(display_tech(tech))
        ax.set_xlabel('Model year and market share')
        ax.set_ylim(bottom=0)
        ax.grid(True, axis='y', linestyle='--', linewidth=0.6, alpha=0.7)
        ax.set_axisbelow(True)
        handles, labels = ax.get_legend_handles_labels()
        handles.append(Patch(facecolor='white', edgecolor=cost_color,
                             label=f'LCOE built that year ({q1}-{q3}, whiskers {lo}-{hi})'))
        ax.legend(handles=handles, loc='upper right', fontsize=8)
    axes[0].set_ylabel(f'{dollar_year}$/MWh (per uncurtailed MWh)')
    fig.suptitle(
        f'Weighted-average LVOE against the distribution of ReEDS {lcoe_file} for capacity built '
        f'that year', fontsize=12)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches='tight')
    return fig


def _read(run_dir, fname, cols):
    return pd.read_csv(os.path.join(run_dir, 'outputs', fname), names=cols, header=0)


def prep_scatter(valcostfac_core_path=valcostfac_core_path, scenarios_path=scenarios_path):
    """One row per new-build (class, region, bin, year): LCOE, LVOE, AEP and regional penetration.

    LCOE is the model's lcoe output, which exists only for invested bins - so this is new builds and
    nothing else. Adding the uninvested bins needs an lcoe over all feasible bins written from
    report.gms; lcoe_fullpol is not that, since it leaves the supply-curve term unscaled by the
    mandate.

    LVOE is valnew's val_load + val_resmarg over its MWh, per (class, region, year): valnew has no
    bin dimension, so every bin of a class in a region carries the same value, which is right
    because they share a generation profile. AEP is chosen MW times gen_rsc, which reconciles to
    valnew's MWh at a median ratio of 1.000, so dot size and the LVOE denominator are one basis.
    Penetration is the region's uncurtailed generation of the tech over its load, the same
    measure the spatial figures use.
    """
    df = pd.read_csv(valcostfac_core_path)
    run_dirs = tech_run_dirs(df, scenarios_path)
    #force_mult, for de-scaling. Per tech-year, from the unfiltered valcostfac.csv where present so
    #the last model year is not lost to gen_frac_max.
    full_path = os.path.join(os.path.dirname(os.path.abspath(valcostfac_core_path)), 'valcostfac.csv')
    src = pd.read_csv(full_path) if os.path.exists(full_path) else df
    src = src[src['core'] == 1] if 'core' in src else src

    out = {}
    for tech, prefix in tech_prefix_map.items():
        if tech not in run_dirs:
            continue
        run_dir = run_dirs[tech]
        usd = deflate_factor(load_deflator(run_dir), reeds_dollar_year, dollar_year)
        scen = df[df['tech'] == tech]['scenario'].iloc[0]
        fm = src[(src['tech'] == tech) & (src['scenario'] == scen)].set_index('year')['force_mult']

        lcoe = _read(run_dir, f'{lcoe_file}.csv', lcoe_cols)
        chosen = _read(run_dir, 'cap_new_bin_out.csv', chosen_cols)
        gen_rsc = _read(run_dir, 'gen_rsc.csv', ['tech', 'vintage', 'rb', 'year', 'gen_per_mw'])
        vn = _read(run_dir, 'valnew.csv', ['metric', 'tech', 'rb', 'year', 'val'])
        gu = _read(run_dir, 'gen_ivrt_uncurt.csv', ['tech', 'vintage', 'rb', 'year', 'gen'])

        d = lcoe[lcoe['tech'].str.startswith(prefix)].merge(
            chosen, on=['tech', 'vintage', 'rb', 'year', 'bin'])
        d = d[d['chosen_mw'] > 0].merge(gen_rsc, on=['tech', 'vintage', 'rb', 'year'], how='left')
        d['aep_gwh'] = d['chosen_mw'] * d['gen_per_mw'] / 1000

        v = vn[vn['tech'].str.startswith(prefix) & (vn['rb'] != 'sys')].pivot_table(
            index=['tech', 'rb', 'year'], columns='metric', values='val', aggfunc='sum').fillna(0)
        v['lvoe'] = np.where(v['MWh'] > 0, (v['val_load'] + v['val_resmarg']) / v['MWh'], np.nan)
        d = d.merge(v[['lvoe']].reset_index(), on=['tech', 'rb', 'year'], how='left')

        load = vn[(vn['tech'] == 'benchmark') & (vn['metric'] == 'MWh') & (vn['rb'] != 'sys')]
        load = load.set_index(['rb', 'year'])['val'].rename('load')
        gen = gu[gu['tech'].str.startswith(prefix)].groupby(['rb', 'year'])['gen'].sum()
        pen = (gen / load).rename('pen').reset_index()
        d = d.merge(pen, on=['rb', 'year'], how='left')

        d['lcoe'] = d['lcoe'] * usd
        d['lvoe'] = d['lvoe'] * usd
        d['force_mult'] = d['year'].map(fm)
        d['lcoe_descaled'] = d['lcoe'] / d['force_mult']
        d['tech_name'] = tech
        out[tech] = d[d['year'] >= min(fm.index)].dropna(subset=['lvoe', 'lcoe'])
    return out


def plot_lvoe_vs_lcoe_scatter(data, output_path):
    """By-year scatter of LVOE against LCOE for every new-build bin, techs as rows.

    One dot per (class, region, bin) built that year, sized by its AEP and coloured by the
    penetration of its region. The 45-degree line is LVOE = LCOE. Axes are shared within a
    technology row so the cloud can be watched moving year to year, and the columns are the same
    model years as the by-year maps.
    """
    techs = [t for t in tech_prefix_map if t in data]
    frames = {t: data[t] for t in techs}
    all_years = sorted(set().union(*[set(f['year']) for f in frames.values()]))
    years = [y for y in all_years if (y - all_years[0]) % scatter_year_step == 0]
    xcol = 'lcoe_descaled' if scatter_descale else 'lcoe'
    xlabel = f'LCOE, {"unforced" if scatter_descale else "as optimised"} ({dollar_year}$/MWh)'

    pen_all = pd.concat([f['pen'] for f in frames.values()]).dropna()
    pnorm = Normalize(0, float(np.percentile(pen_all, 98)))
    aep_max = max(f['aep_gwh'].max() for f in frames.values())
    cmap = plt.get_cmap(scatter_pen_cmap)

    fig, axes = plt.subplots(len(techs), len(years), squeeze=False, sharex='row', sharey='row',
                             figsize=(2.05 * len(years), 2.45 * len(techs)),
                             gridspec_kw={'hspace': 0.30, 'wspace': 0.06})
    for i, tech in enumerate(techs):
        f = frames[tech]
        #Shared per row so the cloud can be watched moving. Set from the 98th percentile, since
        #a handful of very high-LCOE bins in the last year would otherwise stretch the whole row.
        lim = float(np.nanpercentile(pd.concat([f[xcol], f['lvoe']]), 98)) * 1.05
        for j, year in enumerate(years):
            ax = axes[i, j]
            x = f[f['year'] == year]
            ax.plot([0, lim], [0, lim], color='0.55', linewidth=0.9, zorder=1)
            if not x.empty:
                x = x.sort_values('aep_gwh', ascending=False)
                ax.scatter(x[xcol], x['lvoe'],
                           s=scatter_size_max * x['aep_gwh'] / aep_max + 4,
                           c=x['pen'], cmap=cmap, norm=pnorm, alpha=0.7,
                           edgecolor='0.25', linewidth=0.3, zorder=3)
                w = x['aep_gwh']
                ax.text(0.03, 0.97,
                        f"{len(x)} bins, {x['rb'].nunique()} regions\n"
                        f"{w.sum() / 1000:.0f} TWh\n"
                        f"LVOE/LCOE {np.average(x['lvoe'], weights=w) / np.average(x[xcol], weights=w):.2f}",
                        transform=ax.transAxes, va='top', ha='left', fontsize=6.6, color='0.25',
                        linespacing=1.3, zorder=6,
                        bbox={'facecolor': 'white', 'edgecolor': 'none', 'alpha': 0.8,
                              'boxstyle': 'round,pad=0.2'})
            ax.set_xlim(0, lim)
            ax.set_ylim(0, lim)
            ax.set_aspect('equal')
            ax.grid(True, linestyle='--', linewidth=0.5, alpha=0.6)
            ax.set_axisbelow(True)
            ax.tick_params(labelsize=7)
            if i == 0:
                ax.set_title(str(year), fontsize=9.5)
            if j == 0:
                ax.set_ylabel(f'{display_tech(tech)}\nLVOE ({dollar_year}$/MWh)', fontsize=8.5)
            if i == len(techs) - 1 and j == len(years) // 2:
                ax.set_xlabel(xlabel, fontsize=8.5)

    cb = fig.colorbar(plt.cm.ScalarMappable(norm=pnorm, cmap=cmap), ax=axes.ravel().tolist(),
                      fraction=0.014, pad=0.008, location='right', extend='max')
    cb.set_label('Penetration of the region (gen / load)', fontsize=8.5)
    cb.ax.tick_params(labelsize=7)
    fig.suptitle(
        'LVOE against LCOE for each new-build bin, by model year\n'
        'one dot per class-region-bin built that year, sized by its AEP and coloured by regional '
        'penetration; grey line is LVOE = LCOE',
        fontsize=11, y=0.995)
    fig.savefig(output_path, dpi=300, bbox_inches='tight')
    return fig


def make_figs(valcostfac_core_path=valcostfac_core_path, scenarios_path=scenarios_path,
              output_dir=None):
    """Write the comparison figure and its table next to valcostfac_core.csv."""
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(valcostfac_core_path))
    data = prep_data(valcostfac_core_path, scenarios_path)
    if not data:
        print('Nothing to plot.')
        return None
    with matplotlib.rc_context(default_rc):
        fig = plot_lvoe_vs_lcoe(data, os.path.join(output_dir, 'lvoe_vs_lcoe.png'))
        plt.close(fig)
        #By-year scatter over every new-build bin, the region-level view of the same check.
        scatter = prep_scatter(valcostfac_core_path, scenarios_path)
        if scatter:
            fig = plot_lvoe_vs_lcoe_scatter(
                scatter, os.path.join(output_dir, 'lvoe_vs_lcoe_byyear.png'))
            plt.close(fig)
            pd.concat(scatter.values(), ignore_index=True).to_csv(
                os.path.join(output_dir, 'lvoe_vs_lcoe_byyear.csv'), index=False)
    out = pd.concat(data.values(), ignore_index=True)
    out.to_csv(os.path.join(output_dir, 'lvoe_vs_lcoe.csv'), index=False)
    return out


if __name__ == '__main__':
    make_figs()
