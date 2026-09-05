'''Why does VRE cost escalate? This file tests the hypothesis that building wind/solar in a region
suppresses that tech's value there, pushing later deployment into regions with worse resource.

Three figures, in the order the argument runs:

  A  spatial_value_map_<tech>.png         where value falls and where capacity goes, two years
  A2 spatial_value_map_byyear_<tech>.png  the same in every model year, as a filmstrip
  B  spatial_value_suppression.png        that local build-out causes local value decline (scatter)
  C  spatial_value_cost_decomp.png        how much of the cost rise that relocation explains

Value factors here are normalised by the NATIONAL benchmark price, not each region's own price.
That matters. The regional price is endogenous to the mechanism being measured: wind depresses the
whole local price level, so LVOE_r and P_r fall together and LVOE_r/P_r barely moves - dividing by
the regional price removes most of the effect. National normalisation is also the only one that
aggregates, since VF_nat = sum_r (MWh_r/MWh_tot) * (LVOE_r/P_nat) exactly, so the map decomposes the
paper's national value factor directly. Normalising by P_r instead would map vf_temporal alone.

Value is taken from revenue.csv over the whole fleet rather than from valnew.csv over new builds
only, because valnew exists only where the model invested - an 18-of-54-region map for UPV in 2030 -
while revenue.csv covers 48-54. Coverage is the only reason. The two agree closely in level: over
the region-years where both exist the fleet/new-build ratio is 0.987 for wind and 0.998 for UPV,
median 1.000. These runs set GSw_PRM_CapCredit=0, so revenue('res_marg') takes the gen_h_stress
branch and valnew('val_resmarg') the matching stress-hour branch - both are GEN.l - STORAGE_IN.l at
stress hours priced at stress prices, differing only in fleet versus valinv vintages. The cap_firm
and m_cc_mar formulations belong to the Sw_PRM_CapCredit=1 branch and never fire here. Both measures
are written to the csv as vf_nat and vf_new_nat; the figures use the fleet one and say so.

The benchmark price is val_tot - energy plus reserve margin - over load MWh, matching the report's
'Benchmark Price by Year' preset. The energy price alone would put a value that includes res_marg
revenue over a denominator that excludes it, inflating every value factor by about 1.5x.

Costs use lcoe.csv weighted by cap_new_bin_out.csv, matching lvoe_vs_lcoe.py. lcoe_built.csv is NOT
used: it divides by curtailed GEN.l, so at high VRE shares it measures curtailment rather than cost
and inflates the 2050 rise by an order of magnitude.

Run this file on the reeds2 conda environment.
'''
import os
import sys
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize, PowerNorm, TwoSlopeNorm
from plcoe_pitch import build_color_map, default_rc, cost_color
from reeds_vs_rev import tech_run_dirs
from report_switches import start_year

#reeds.io.get_dfmap builds the zone geometries. bokehpivot sits two levels below the repo root and
#is not itself a package, so the root goes on the path explicitly rather than via a relative import.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')))

# User inputs
valcostfac_core_path = '/data/shared/projects/mmowers/ReEDS/postprocessing/bokehpivot/out/reeds_report/valcostfac_core.csv' #Only used when running this file standalone.
scenarios_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reeds_scenarios_valcostfac.csv') #Maps each scenario name to its run directory.
tech_prefix_map = {'Onshore Wind': 'wind-ons', 'UPV': 'upv'} #ReEDS tech name -> prefix of the raw tech names in the run outputs.
map_years = [2030, 2050] #Years to map. Falls back to the nearest modelled year if one is missing.
early_window = 4 #Number of modelled years averaged into the "early" build mix for the composition index.
late_window = 3 #Number of modelled years averaged into the "late" build mix.
vf_cmap = 'viridis' #Colormap for value factor maps.
pen_cmap = 'YlOrBr' #Colormap for penetration maps.
map_shared_scale = False #True gives both years one colour scale, so colour is comparable across years but the later year flattens out. False scales each year on its own, which resolves the within-year pattern the maps are for; the level change is then only in the titles and colorbars.
map_clip_pct = (2, 98) #Percentiles the map colour range is clipped to. A linear scale is otherwise wrecked by single outliers - onshore wind's 2050 value factor reaches 1.54 in NY_NYCLI against a median of 0.17. Values outside saturate at the end colours.
rev_cats = ['load', 'res_marg'] #Revenue categories summed into fleet value, matching the paper's LVOE.
storage_prefixes = ('battery', 'pumped-hydro', 'caes', 'evmc_storage') #Raw tech prefixes excluded from the regional market-share denominator, mirroring storage_techs in report_switches.
byyear_cmaps = ('RdYlBu', 'Purples', 'YlOrBr') #Colormaps for the by-year figure: value factor vs national (diverging), share of the year's new capacity, regional market share.
byyear_clip_pct = (2, 98) #Percentiles the by-year colour ranges are clipped to, pooled over all years so one colorbar serves a whole row.


_dfmap_cache = {}


def zone_map(run_dir):
    """Zone geometries for a run, cached - get_dfmap dissolves the full hierarchy and is slow
    enough that recomputing it for every figure dominates the runtime."""
    if run_dir not in _dfmap_cache:
        import reeds
        _dfmap_cache[run_dir] = reeds.io.get_dfmap(run_dir)
    return _dfmap_cache[run_dir]


def _read(run_dir, fname, cols):
    """Read one GAMS output, naming the columns since the headers are positional placeholders."""
    return pd.read_csv(os.path.join(run_dir, 'outputs', fname), names=cols, header=0)


def load_regional(run_dir, prefix):
    """Fleet value, penetration and prices for one tech, by region and year.

    Returns one row per (r, t) with the national- and regional-normalised value factors, the local
    price level relative to national, and penetration as uncurtailed generation over regional load.
    """
    rev = _read(run_dir, 'revenue.csv', ['cat', 'i', 'r', 't', 'val'])
    rev = rev[rev['i'].str.startswith(prefix) & rev['cat'].isin(rev_cats)]
    fleet_rev = rev.groupby(['r', 't'])['val'].sum().rename('fleet_rev')
    #Energy-only revenue is kept separate so the price-suppression channel can be read without the
    #reserve-margin term, which is stress-hour generation valued at stress prices and moves with
    #stress-period conditions rather than with the energy price.
    energy_rev = (rev[rev['cat'] == 'load'].groupby(['r', 't'])['val'].sum().rename('energy_rev'))

    #gen_ivrt_uncurt is the denominator revenue_en itself uses for VRE, so value is per uncurtailed
    #MWh - the same basis as LVOE in valcostfac_core.
    gen = _read(run_dir, 'gen_ivrt_uncurt.csv', ['i', 'v', 'r', 't', 'gen'])
    gen = gen[gen['i'].str.startswith(prefix)].groupby(['r', 't'])['gen'].sum().rename('gen')

    #Regional market share on a generation basis, mirroring share_basis='gen' in report_switches:
    #actual generation of this tech over total regional generation excluding storage. This is the
    #regional counterpart of gen_frac, and is not the same as pen below, which is uncurtailed
    #generation over regional load and can exceed one where a region exports.
    ga = _read(run_dir, 'gen_ann.csv', ['i', 'r', 't', 'gen'])
    gen_tot = (ga[~ga['i'].str.lower().str.startswith(storage_prefixes)]
               .groupby(['r', 't'])['gen'].sum().rename('gen_tot'))
    gen_act = (ga[ga['i'].str.startswith(prefix)]
               .groupby(['r', 't'])['gen'].sum().rename('gen_act'))

    #valnew carries the benchmark load and load-weighted price, by region and for the system.
    vn = _read(run_dir, 'valnew.csv', ['metric', 'i', 'r', 't', 'val'])
    bench = vn[vn['i'] == 'benchmark']
    reg = (bench[bench['r'] != 'sys']
           .pivot_table(index=['r', 't'], columns='metric', values='val', aggfunc='sum'))
    sysb = (bench[bench['r'] == 'sys']
            .pivot_table(index='t', columns='metric', values='val', aggfunc='sum'))
    #The benchmark is the full per-MWh cost of serving load, energy plus reserve margin - the
    #val_tot the report's 'Benchmark Price by Year' preset sums (reeds2.py builds vf as
    #(val_tot/mwh) / (val_tot_bench_sys/mwh_bench_sys)). Using the energy price alone would put a
    #value that includes res_marg revenue over a denominator that excludes it, inflating every
    #value factor here by about 1.5x relative to valcostfac_core.
    price_nat = ((sysb['val_load'] + sysb['val_resmarg']) / sysb['MWh']).rename('price_nat')
    price_energy_nat = (sysb['val_load'] / sysb['MWh']).rename('price_energy_nat')

    #New-build value, for the columns that have to line up with valcostfac_core.
    new = (vn[vn['i'].str.startswith(prefix)]
           .pivot_table(index=['r', 't'], columns='metric', values='val', aggfunc='sum')
           .fillna(0))
    new['lvoe_new'] = np.where(new['MWh'] > 0, (new['val_load'] + new['val_resmarg']) / new['MWh'], np.nan)

    df = pd.concat([fleet_rev, energy_rev, gen, gen_act, gen_tot], axis=1)
    df = df.join(reg[['MWh', 'val_load', 'val_resmarg']]
                 .rename(columns={'MWh': 'load', 'val_load': 'load_val',
                                  'val_resmarg': 'resmarg_val'}))
    df = df.join(new[['lvoe_new', 'MW']].rename(columns={'MW': 'new_mw'}))
    df = df.reset_index().merge(price_nat.reset_index(), on='t')
    df = df.merge(price_energy_nat.reset_index(), on='t')

    #Regional benchmark on the same energy-plus-reserve-margin basis, so price_rel below is the
    #regional counterpart of the report's vf_spatial. price_energy_r keeps the energy-only price
    #for the channel that is specifically about energy price suppression.
    df['price_r'] = (df['load_val'] + df['resmarg_val']) / df['load']
    df['price_energy_r'] = df['load_val'] / df['load']
    df['lvoe_fleet'] = df['fleet_rev'] / df['gen']
    df['lvoe_energy'] = df['energy_rev'] / df['gen']
    df['vf_nat'] = df['lvoe_fleet'] / df['price_nat']
    df['vf_energy_nat'] = df['lvoe_energy'] / df['price_nat']
    df['vf_reg'] = df['lvoe_fleet'] / df['price_r']
    df['vf_new_nat'] = df['lvoe_new'] / df['price_nat']
    df['price_rel'] = df['price_r'] / df['price_nat']
    df['price_energy_rel'] = df['price_energy_r'] / df['price_energy_nat']
    df['pen'] = df['gen'] / df['load']
    df['market_share'] = df['gen_act'] / df['gen_tot']
    df['new_mw'] = df['new_mw'].fillna(0)
    return df[df['t'] >= start_year].copy()


def load_regional_cost(run_dir, prefix, base):
    """Cost factor of what was built, by region and year.

    lcoe.csv exists only where INV_RSC is nonzero, so merging it onto cap_new_bin_out gives exactly
    the bins invested in. Dividing by base - lcoe_base_orig * force_mult - strips the exogenous ATB
    decline and the mandate ramp, leaving a cost factor comparable to the paper's.
    """
    lcoe = _read(run_dir, 'lcoe.csv', ['i', 'v', 'r', 't', 'bin', 'lcoe'])
    chosen = _read(run_dir, 'cap_new_bin_out.csv', ['i', 'v', 'r', 't', 'bin', 'mw'])
    m = lcoe.merge(chosen, on=['i', 'v', 'r', 't', 'bin'])
    m = m[m['i'].str.startswith(prefix) & (m['mw'] > 0)].copy()
    m['num'] = m['lcoe'] * m['mw']
    g = m.groupby(['r', 't'])[['num', 'mw']].sum().reset_index()
    g['lcoe'] = g['num'] / g['mw']

    g['base'] = g['t'].map(base)
    g = g.dropna(subset=['base'])
    g['cfr'] = g['lcoe'] / g['base']
    return g[g['t'] >= start_year].copy()


def composition_index(cost):
    """Split the national cost factor into a mix effect and a within-region effect.

    CF(t) = sum_r w_r(t) * cf_r(t). Freezing each region's cost at its own MW-weighted mean across
    all years it builds, c_r, and letting only the weights move gives the composition index
    sum_r w_r(t) * c_r - the cost rise attributable purely to relocating. The residual is the
    within-region climb up each local supply curve.

    c_r is used rather than a base-year cost because the region count swings from 7 to 46 over the
    horizon, so Laspeyres or LMDI forms break on entry and exit.
    """
    d = cost.copy()
    d['wn'] = d['cfr'] * d['mw']
    c_r = d.groupby('r')[['wn', 'mw']].sum()
    c_r = (c_r['wn'] / c_r['mw']).rename('c_r')
    d = d.merge(c_r.reset_index(), on='r')

    rows = []
    for t, x in d.groupby('t'):
        rows.append({
            't': int(t),
            'actual': np.average(x['cfr'], weights=x['mw']),
            'compos': np.average(x['c_r'], weights=x['mw']),
            'new_gw': x['mw'].sum() / 1000,
            'nreg': x['r'].nunique(),
        })
    idx = pd.DataFrame(rows).sort_values('t').reset_index(drop=True)
    idx['within'] = idx['actual'] / idx['compos']
    return idx, c_r


def early_late_ratio(cost, c_r):
    """Composition index for the first and last few build years, and the ratio between them.

    Reported alongside the year-by-year index because the earliest modelled year can be very thin -
    wind builds in 3 regions and 2 GW in 2026 - which makes a first-year normalisation unstable.
    """
    yrs = sorted(cost['t'].unique())
    early_yrs, late_yrs = yrs[:early_window], yrs[-late_window:]
    out = {}
    for name, sel in [('early', early_yrs), ('late', late_yrs)]:
        x = cost[cost['t'].isin(sel)]
        w = x.groupby('r')['mw'].sum()
        w = w / w.sum()
        out[name] = float((w * c_r.reindex(w.index)).sum())
    out['ratio'] = out['late'] / out['early']
    out['early_years'], out['late_years'] = early_yrs, late_yrs
    return out


def fe_slope(df, ycol, xcol):
    """Slope and correlation of y on x, after removing year means and then region means.

    Year fixed effects strip the national trend, so what is left is cross-regional. Adding region
    fixed effects strips each region's own level, leaving only within-region variation over time -
    a stricter test, since windy regions are also intrinsically low-price regions.
    """
    d = df[np.isfinite(df[ycol]) & np.isfinite(df[xcol])].copy()
    if len(d) < 10:
        return {}
    d['y'] = d[ycol] - d.groupby('t')[ycol].transform('mean')
    d['x'] = d[xcol] - d.groupby('t')[xcol].transform('mean')
    out = {'slope_year_fe': np.polyfit(d['x'], d['y'], 1)[0],
           'corr_year_fe': np.corrcoef(d['x'], d['y'])[0, 1]}
    d['y2'] = d['y'] - d.groupby('r')['y'].transform('mean')
    d['x2'] = d['x'] - d.groupby('r')['x'].transform('mean')
    out['slope_region_fe'] = np.polyfit(d['x2'], d['y2'], 1)[0]
    out['corr_region_fe'] = np.corrcoef(d['x2'], d['y2'])[0, 1]
    out['n'] = len(d)
    return out


def load_base(valcostfac_core_path, core, tech):
    """lcoe_base_orig * force_mult by year, over every modelled year.

    Taken from valcostfac.csv rather than valcostfac_core.csv. The core file is filtered to
    gen_frac <= gen_frac_max, which for these runs drops onshore wind's 2050 - its largest build
    year at 354 GW, market share 0.699 against the 0.65 cap - and with it the whole terminal year of
    the cost decomposition. That cap is a scoping choice for the pitch figures and has no bearing
    here, so the unfiltered file is used and only core == 1 rows for this tech's own scenario are
    kept. Falls back to the core file if valcostfac.csv is not alongside it.
    """
    full_path = os.path.join(os.path.dirname(os.path.abspath(valcostfac_core_path)),
                             'valcostfac.csv')
    rows = core[core['tech'] == tech]
    scenario = rows['scenario'].iloc[0]
    if os.path.exists(full_path):
        full = pd.read_csv(full_path)
        sel = full[(full['tech'] == tech) & (full['scenario'] == scenario)
                   & (full['core'] == 1)]
        if len(sel):
            rows = sel
    idx = rows.set_index('year')
    return (idx['lcoe_base_orig'] * idx['force_mult']).sort_index()


def prep_data(valcostfac_core_path=valcostfac_core_path, scenarios_path=scenarios_path):
    """Per tech: the regional panel, the cost decomposition and the suppression regressions."""
    core = pd.read_csv(valcostfac_core_path)
    run_dirs = tech_run_dirs(core, scenarios_path)

    out = {}
    for tech, prefix in tech_prefix_map.items():
        if tech not in run_dirs:
            print(f'Skipping {tech}: no run directory.')
            continue
        run_dir = run_dirs[tech]
        panel = load_regional(run_dir, prefix)
        panel['tech'] = tech
        cost = load_regional_cost(run_dir, prefix, load_base(valcostfac_core_path, core, tech))
        idx, c_r = composition_index(cost)
        panel = panel.merge(c_r.reset_index(), on='r', how='left')

        #Logs, so the regressions read as proportional value loss per unit of penetration.
        for src, dst in [('vf_nat', 'ln_vf'), ('vf_energy_nat', 'ln_vf_energy'),
                         ('price_rel', 'ln_price_rel'),
                         ('price_energy_rel', 'ln_price_energy_rel')]:
            panel[dst] = np.log(panel[src].where(panel[src] > 0))

        out[tech] = {
            'panel': panel,
            'cost': cost,
            'index': idx,
            'c_r': c_r,
            'early_late': early_late_ratio(cost, c_r),
            'run_dir': run_dir,
            'stats': {k: fe_slope(panel, k, 'pen')
                      for k in ['ln_vf', 'ln_vf_energy', 'ln_price_rel',
                                'ln_price_energy_rel']},
        }
    return out


def _pick_years(panel, years):
    """Nearest modelled year to each requested one, since runs do not all reach 2050."""
    have = np.array(sorted(panel['t'].unique()))
    return [int(have[np.argmin(np.abs(have - y))]) for y in years]


def plot_maps(data, tech, output_path):
    """Figure A: value factor and penetration, mapped for two years.

    Colour is linear in the value factor itself rather than in its log, and each year is scaled on
    its own. Those two choices go together: a shared scale forces a log ramp, because UPV's value
    factor falls about tenfold between the mapped years and the later map would otherwise be one
    flat colour. Scaling per year instead resolves the within-year spatial pattern, which is what
    these maps are for - the level collapse is carried by figure B and by the national series.

    The cost of per-year scaling is that colour is no longer comparable between panels, so each
    panel's title carries its national value and each panel gets its own colorbar.
    """
    panel = data[tech]['panel']
    years = _pick_years(panel, map_years)
    dfmap = zone_map(data[tech]['run_dir'])
    zones, country = dfmap['r'], dfmap['country']

    rows = [
        ('vf_nat', 'Value factor', vf_cmap, 'gen'),
        ('pen', 'Penetration', pen_cmap, 'ratio'),
    ]
    #Generous hspace: each panel carries its own colorbar below it, which would otherwise collide
    #with the next row's titles.
    fig, axes = plt.subplots(2, len(years), figsize=(5.6 * len(years), 9.6),
                             gridspec_kw={'hspace': 0.34, 'wspace': 0.02})

    def limits(vals):
        """Colour range for one panel, clipped so single outliers cannot flatten the rest."""
        v = vals.replace([np.inf, -np.inf], np.nan).dropna()
        lo, hi = np.percentile(v, map_clip_pct)
        return (float(lo), float(hi)) if hi > lo else (float(v.min()), float(v.max()))

    for i, (col, label, cmap, agg) in enumerate(rows):
        shared = limits(panel[panel['t'].isin(years)][col]) if map_shared_scale else None
        for j, year in enumerate(years):
            ax = axes[i, j]
            yr = panel[panel['t'] == year]
            norm = Normalize(*(shared if shared else limits(yr[col])))

            g = zones.copy()
            g['value'] = yr.set_index('r')[col]
            #Regions with no capacity of this tech are left unfilled rather than shown as zero.
            g[g['value'].notna()].plot(ax=ax, column='value', cmap=cmap, norm=norm,
                                       edgecolor='white', linewidth=0.2)
            g[g['value'].isna()].plot(ax=ax, facecolor='0.92', edgecolor='white', linewidth=0.2)
            country.plot(ax=ax, facecolor='none', edgecolor='k', linewidth=0.6, zorder=10)
            ax.axis('off')

            #National anchor, since colour alone no longer says how the level moved between years.
            if agg == 'gen':
                nat = np.average(yr[col].fillna(0), weights=yr['gen'].fillna(0))
            else:
                nat = yr['gen'].sum() / yr['load'].sum()
            ax.set_title(f'{year}   national {label.lower()} {nat:.3f}', fontsize=10.5, y=1.02)

            cb = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), ax=ax,
                              location='bottom', fraction=0.040, pad=0.005,
                              extend='both' if not map_shared_scale else 'neither')
            cb.set_label(label, fontsize=9)
            cb.ax.tick_params(labelsize=7.5)

    st = data[tech]['stats']['ln_vf']
    scale_note = ('one colour scale across years'
                  if map_shared_scale else
                  f'each year on its own colour scale, clipped to p{map_clip_pct[0]}-'
                  f'p{map_clip_pct[1]} (arrows = saturated)')
    fig.suptitle(
        f'{tech}: fleet value factor (vs national benchmark price) and penetration '
        f'(uncurtailed generation / regional load)\n'
        f'{scale_note}; unfilled = no capacity  |  d ln(VF)/d penetration = '
        f'{st["slope_year_fe"]:+.3f} (year FE), {st["slope_region_fe"]:+.3f} (+ region FE)',
        fontsize=11.5, y=0.97)
    fig.savefig(output_path, dpi=300, bbox_inches='tight')
    return fig


def plot_maps_byyear(data, tech, output_path):
    """Figure A2: every model year as a column, three metrics as rows.

    The mechanism as a filmstrip rather than a before/after. Read a column downward for one year -
    where value stands, where the model is building right now, how saturated each region already
    is - and read a row rightward to watch deployment walk out of the regions it has already
    devalued. Row 2 is the weight w_r(t) from the composition index in figure C, so this figure and
    that one are showing the same quantity in different form.

    With thirteen years there is one colorbar per row, not per panel, so every row needs a scale
    that stays legible across the whole horizon:

      Row 1 plots the value factor RELATIVE to the national value factor of the same year, not the
      value factor itself. Absolute VF falls roughly fortyfold over the horizon, so a shared linear
      scale would be flat black by 2050 and a shared log scale would reintroduce exactly what the
      two-year maps dropped. Dividing by the year's national value keeps the scale linear, shared
      and centred on 1, and it is the right quantity here anyway: relocation is driven by where
      value is high or low relative to elsewhere at that moment, not by the national level.

      Row 2 plots each region's new capacity relative to the largest regional build of that same
      year, which is self normalising - the absolute GW, spanning 2 GW in 2026 to 709 GW in 2050,
      is in the panel annotation instead. Scaling to the national total instead would wash the row
      out, because with forty-odd regions building, shares cluster near 1/40. Regions that built
      nothing are grey rather than zero-coloured, since about a third of region-years have no build
      at all.

      Row 3 plots regional market share, which is already bounded and needs no rescaling.
    """
    panel = data[tech]['panel']
    years = sorted(panel['t'].unique())
    dfmap = zone_map(data[tech]['run_dir'])
    zones, country = dfmap['r'], dfmap['country']

    #National anchors, one per year, quoted in each panel so the levels survive the rescaling.
    nat = {}
    for t, x in panel.groupby('t'):
        nat[t] = {
            'vf': np.average(x['vf_nat'].fillna(0), weights=x['gen'].fillna(0)),
            'gw': x['new_mw'].sum() / 1000,
            'share': x['gen_act'].sum() / x['gen_tot'].sum(),
        }

    d = panel.copy()
    d['vf_rel'] = d['vf_nat'] / d['t'].map({t: v['vf'] for t, v in nat.items()})
    #Scaled to the year's largest regional build rather than to the national total: with forty-odd
    #regions building, shares of the total cluster near 1/40 and every panel washes out. Relative to
    #the year's maximum the pattern - which regions this year's capacity actually went to - is
    #legible in every year, and the absolute GW is annotated.
    max_mw = d.groupby('t')['new_mw'].transform('max')
    d['new_share'] = np.where(max_mw > 0, d['new_mw'] / max_mw, np.nan)
    d.loc[d['new_mw'] <= 0, 'new_share'] = np.nan

    def clip(col):
        v = d[col].replace([np.inf, -np.inf], np.nan).dropna()
        return np.percentile(v, byyear_clip_pct)

    lo, hi = clip('vf_rel')
    rows = [
        ('vf_rel', 'VF / national VF', byyear_cmaps[0],
         TwoSlopeNorm(vmin=min(lo, 0.99), vcenter=1.0, vmax=max(hi, 1.01)),
         lambda t: f"VF {nat[t]['vf']:.3f}"),
        #Square-root scaled: regional builds are heavily skewed - a median of 1.2 GW against a
        #94 GW maximum - so a linear ramp leaves everything but the year's one or two largest
        #builders indistinguishable from white.
        ('new_share', "New capacity (max = 1)", byyear_cmaps[1],
         PowerNorm(0.5, vmin=0, vmax=1), lambda t: f"{nat[t]['gw']:.0f} GW"),
        ('market_share', 'Market share', byyear_cmaps[2],
         Normalize(0, clip('market_share')[1]), lambda t: f"{nat[t]['share']:.2f}"),
    ]

    fig, axes = plt.subplots(len(rows), len(years), figsize=(1.95 * len(years), 2.35 * len(rows)),
                             gridspec_kw={'hspace': 0.16, 'wspace': 0.02})

    for i, (col, label, cmap, norm, note) in enumerate(rows):
        for j, year in enumerate(years):
            ax = axes[i, j]
            g = zones.copy()
            g['value'] = d[d['t'] == year].set_index('r')[col]
            g[g['value'].notna()].plot(ax=ax, column='value', cmap=cmap, norm=norm,
                                       edgecolor='white', linewidth=0.1)
            g[g['value'].isna()].plot(ax=ax, facecolor='0.93', edgecolor='white', linewidth=0.1)
            country.plot(ax=ax, facecolor='none', edgecolor='k', linewidth=0.4, zorder=10)
            ax.axis('off')
            if i == 0:
                ax.set_title(str(year), fontsize=10, y=0.99)
            #Below the map rather than over it, so the annotation does not sit on Texas.
            ax.text(0.5, -0.03, note(year), transform=ax.transAxes, ha='center', va='top',
                    fontsize=7, color='0.25')

        cb = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), ax=list(axes[i, :]),
                          fraction=0.010, pad=0.008, location='right',
                          extend='both' if col == 'vf_rel' else 'neither')
        cb.set_label(label, fontsize=8.5)
        cb.ax.tick_params(labelsize=7)

    fig.suptitle(
        f'{tech}: value, deployment and saturation by model year   '
        f'(grey = no capacity, or no build that year in the middle row)\n'
        f'row 1 is relative to each year national value factor, so colour is comparable across '
        f'years; row 2 is scaled to that year largest regional build, square-root ramp; '
        f'national levels are annotated in every panel',
        fontsize=11.5, y=0.99)
    fig.savefig(output_path, dpi=300, bbox_inches='tight')
    return fig


def plot_suppression(data, output_path):
    """Figure B: does local build-out cause local value decline, and through which channel.

    This is a partial-regression view: both axes have their year means removed, so the national
    trend common to every region is gone and what remains is the cross-regional relationship the
    quoted slopes measure. Plotting the raw 2030-to-2050 difference instead would be a far weaker
    picture, because UPV's value factor collapses almost uniformly - every region lands near
    -2.2 in logs - so the between-region variation that carries the argument is invisible.

    Row 1 is the total value factor. Row 2 drops the reserve-margin term, leaving value earned on
    energy alone. Row 3 is the local energy price level, which separates the two techs: wind
    depresses the whole local energy price, so its suppression is a price-level effect, while UPV's
    local energy price barely moves and its loss is a capture-rate effect concentrated in its own
    generating hours. The corresponding ratio on the full benchmark - energy plus reserve margin,
    the regional counterpart of the report's vf_spatial - is in spatial_value_stats.csv as
    ln_price_rel; it is the less clean statement of the channel, because the reserve-margin
    requirement price moves for reasons of its own.
    """
    techs = [t for t in tech_prefix_map if t in data]
    colors = build_color_map(techs)
    rows = [
        ('ln_vf', 'ln(value factor)', 'total value'),
        ('ln_vf_energy', 'ln(energy-only value factor)', 'energy value, reserve margin removed'),
        ('ln_price_energy_rel', 'ln(local energy price / national)', 'local energy price level'),
    ]
    fig, axes = plt.subplots(len(rows), len(techs), figsize=(6.4 * len(techs), 4.4 * len(rows)),
                             squeeze=False, constrained_layout=True)

    for j, tech in enumerate(techs):
        panel = data[tech]['panel'].copy()
        panel['pen_d'] = panel['pen'] - panel.groupby('t')['pen'].transform('mean')
        for i, (col, ylab, tag) in enumerate(rows):
            ax = axes[i, j]
            d = panel[np.isfinite(panel[col]) & np.isfinite(panel['pen_d'])].copy()
            d['y'] = d[col] - d.groupby('t')[col].transform('mean')
            #Sized by generation so the regions carrying the transition dominate visually, and
            #faded because there is one dot per region-year rather than per region.
            g = d['gen'].clip(lower=0)
            size = 8 + 150 * (g / g.max() if g.max() > 0 else g)
            ax.scatter(d['pen_d'], d['y'], s=size, color=colors[tech], alpha=0.40,
                       edgecolor='none', zorder=3)

            st = data[tech]['stats'][col]
            if st:
                xs = np.linspace(d['pen_d'].min(), d['pen_d'].max(), 50)
                ax.plot(xs, st['slope_year_fe'] * xs, color=cost_color, linestyle='--',
                        linewidth=1.8, zorder=5)
                ax.text(0.03, 0.06,
                        f'slope {st["slope_year_fe"]:+.3f}   r = {st["corr_year_fe"]:+.2f}   '
                        f'n = {st["n"]}\nwith region FE: {st["slope_region_fe"]:+.3f} '
                        f'(r = {st["corr_region_fe"]:+.2f})',
                        transform=ax.transAxes, fontsize=8.5, color=cost_color,
                        bbox={'facecolor': 'white', 'edgecolor': '0.8', 'pad': 3.5})

            ax.axhline(0, color='0.7', linewidth=0.8, zorder=1)
            ax.axvline(0, color='0.7', linewidth=0.8, zorder=1)
            ax.grid(True, linestyle='--', linewidth=0.6, alpha=0.7)
            ax.set_axisbelow(True)
            ax.set_title(f'{tech} - {tag}' if i == 0 else tag, fontsize=10.5)
            if i == len(rows) - 1:
                ax.set_xlabel('penetration, year mean removed')
            if j == 0:
                ax.set_ylabel(ylab)

    fig.suptitle(
        'Local build-out against local value loss: one dot per region-year, sized by generation\n'
        'both axes have year means removed, so the national trend is gone and only '
        'cross-regional variation remains',
        fontsize=12.5)
    fig.savefig(output_path, dpi=300, bbox_inches='tight')
    return fig


def plot_cost_decomp(data, output_path):
    """Figure C: how much of the cost factor rise is relocation rather than local supply curve."""
    techs = [t for t in tech_prefix_map if t in data]
    colors = build_color_map(techs)
    fig, axes = plt.subplots(1, len(techs), figsize=(7.2 * len(techs), 5.6), squeeze=False,
                             constrained_layout=True)

    for ax, tech in zip(axes[0], techs):
        idx = data[tech]['index']
        el = data[tech]['early_late']
        #Normalised to the mean of the early window rather than to the first year: the first
        #modelled year can be a handful of regions and a couple of GW, which is too thin a base.
        base = idx[idx['t'].isin(el['early_years'])]
        a0, c0 = base['actual'].mean(), base['compos'].mean()

        ax.plot(idx['t'], idx['actual'] / a0, color=colors[tech], marker='o', markersize=5,
                linewidth=2, zorder=5, label='actual cost factor')
        ax.plot(idx['t'], idx['compos'] / c0, color=cost_color, marker='s', markersize=4.5,
                linestyle='--', linewidth=1.6, zorder=4,
                label='composition only (regional mix shift)')
        ax.plot(idx['t'], (idx['actual'] / a0) / (idx['compos'] / c0), color='0.6',
                marker='^', markersize=4, linestyle=':', linewidth=1.4, zorder=3,
                label='within-region (supply curve climb)')
        ax.fill_between(idx['t'], 1, idx['compos'] / c0, color=cost_color, alpha=0.12, zorder=1)

        #The first modelled years are thin - wind builds in 3 regions and 2 GW in 2026 - so the
        #index swings there. Shaded to show which years the normalisation averages over.
        ax.axvspan(min(el['early_years']), max(el['early_years']), color='0.85', alpha=0.45,
                   zorder=0, label=f'normalisation window ({idx["nreg"].iloc[0]} regions at first year)')
        ax.axhline(1, color='0.7', linewidth=0.8, zorder=1)
        ax.set_title(f'{tech}\ncomposition {el["early"]:.3f} -> {el["late"]:.3f} '
                     f'= {el["ratio"]:.2f}x over the horizon', fontsize=11)
        ax.set_xlabel('Model year')
        ax.grid(True, linestyle='--', linewidth=0.6, alpha=0.7)
        ax.set_axisbelow(True)
        ax.legend(loc='upper left', fontsize=8.5)
    axes[0][0].set_ylabel(f'Index, mean of the first {early_window} build years = 1')

    fig.suptitle(
        'Cost factor of new builds: relocation to costlier regions vs climbing the local supply curve\n'
        'shaded area is the share attributable to regional mix alone', fontsize=12.5)
    fig.savefig(output_path, dpi=300, bbox_inches='tight')
    return fig


def make_figs(valcostfac_core_path=valcostfac_core_path, scenarios_path=scenarios_path,
              output_dir=None):
    """Write the three spatial figures and their tables next to valcostfac_core.csv."""
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(valcostfac_core_path))
    data = prep_data(valcostfac_core_path, scenarios_path)
    if not data:
        print('Nothing to plot.')
        return None

    with matplotlib.rc_context(default_rc):
        for tech in data:
            slug = tech.lower().replace(' ', '-')
            fig = plot_maps(data, tech, os.path.join(output_dir, f'spatial_value_map_{slug}.png'))
            plt.close(fig)
            fig = plot_maps_byyear(
                data, tech, os.path.join(output_dir, f'spatial_value_map_byyear_{slug}.png'))
            plt.close(fig)
        fig = plot_suppression(data, os.path.join(output_dir, 'spatial_value_suppression.png'))
        plt.close(fig)
        fig = plot_cost_decomp(data, os.path.join(output_dir, 'spatial_value_cost_decomp.png'))
        plt.close(fig)

    panel = pd.concat([d['panel'] for d in data.values()], ignore_index=True)
    panel.to_csv(os.path.join(output_dir, 'spatial_value_panel.csv'), index=False)
    idx = pd.concat([d['index'].assign(tech=t) for t, d in data.items()], ignore_index=True)
    idx.to_csv(os.path.join(output_dir, 'spatial_value_cost_decomp.csv'), index=False)
    stats = pd.DataFrame([
        {'tech': t, 'metric': k, **v} for t, d in data.items() for k, v in d['stats'].items()
    ])
    stats.to_csv(os.path.join(output_dir, 'spatial_value_stats.csv'), index=False)
    return data


if __name__ == '__main__':
    make_figs()
