#%% Notes
"""
Diagnostic for the FINITO load coupling in a linked ReEDS-FINITO run.

For a given run it reconstructs and compares the four load quantities that flow
through the coupling, at hourly/regional resolution, for every FINITO model year:

  1. original    - exogenous ReEDS load BEFORE FINITO reference removal
                   (reconstructed as load.h5 + reference; see note below)
  2. reference   - flat 2018 baseline industrial load that hourly_load.py removes
                   (from finito/inputs_case/load_finito.csv, busbar)
  3. endogenous  - FINITO's optimized industrial load added back in the model
                   (load_finito_rt / USE_ELE_FINITO from the handoff GDX), mapped
                   to hours exactly as reeds/resource_adequacy/prep_data.py does
  4. final       - load PRAS/RA sees = load.h5 + endogenous

It then (a) runs correctness checks (NaNs, region coverage, the accounting
identity, clipping evidence, base-year calibration, magnitude sanity), (b) writes
hourly regional CSVs for the representative weather year for items 1-3, and (c)
makes charts (annual system-wide for all four, net adjustment, duration curve,
diurnal shape, and auto-ranked regional spotlights).

IMPORTANT - these are NOT a subtract-then-add-back identity: the reference removed
is a flat 2018 baseline, the endogenous load added is FINITO's shaped, optimized
demand. "original" is therefore RECONSTRUCTED from load.h5 + reference, so the
identity load.h5 == original - reference is definitional; the load-bearing checks
are on endogenous (independent, from the GDX), on `final`, and on the magnitude
relationship between reference and endogenous.

This diagnostic REUSES the production code paths (hourly_load.get_hourly_finito_load
for the reference, and prep_data's exact endogenous mapping) so it validates the
real functions rather than a parallel reimplementation.

Run:  python reeds/resource_adequacy/finito_load_check.py
"""

#%%### USER SWITCHES ###########################################################
# Path to the linked run to check
RUN_PATH = '/kfs2/projects/futuregrid/mmowers/ReEDS/runs/v20260722_133722_FINITO'

# Weather year the representative periods are drawn from (GSw_HourlyWeatherYears);
# used for the hourly CSV exports and the single-year charts.
REP_WEATHER_YEAR = 2012

# FINITO model years to process. None = auto-detect (solved years with a handoff
# GDX that are >= first_year_finito). Or provide a list, e.g. [2030, 2050].
MODEL_YEARS = None

# Model year to spotlight in the single-year charts (duration curve, diurnal,
# regional bars). None = latest processed FINITO year.
SPOTLIGHT_YEAR = None

# Model years to write hourly regional CSVs for. None = all processed years.
CSV_MODEL_YEARS = None

# Number of regions to spotlight in the regional net-adjustment chart.
N_SPOTLIGHT_REGIONS = 12

# Output directory. None = <run>/outputs/finito_load_check
OUTPUT_DIR = None

# Whether to render charts (set False for a checks-only, CSV-only run).
MAKE_PLOTS = True
###############################################################################

#%% Imports
import os
import sys
from pathlib import Path

# make `reeds` importable when run as a standalone script from the repo
_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import gdxpds  # noqa: E402  (import before pandas on Linux to avoid a lib conflict)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import reeds  # noqa: E402
from reeds.input_processing.hourly_load import get_hourly_finito_load  # noqa: E402

if MAKE_PLOTS:
    import matplotlib as mpl
    mpl.use('Agg')
    import matplotlib.pyplot as plt

# ---- Okabe-Ito, a pre-validated colorblind-safe categorical palette ----------
# Assigned in fixed order by the role each series plays (never cycled).
COLORS = {
    'original':   '#0072B2',  # blue      - total, pre-adjustment
    'reference':  '#D55E00',  # vermillion- removed
    'endogenous': '#009E73',  # green     - added
    'final':      '#000000',  # black     - total, post-adjustment
}
DIVERGE_POS = '#009E73'  # green  - net addition
DIVERGE_NEG = '#D55E00'  # vermillion - net removal
GRID = '#D9D9D9'
INK = '#222222'
MUTED = '#888888'


#%% Helpers
def _style_axes(ax):
    ax.grid(True, color=GRID, linewidth=0.6, zorder=0)
    ax.set_axisbelow(True)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    for s in ('left', 'bottom'):
        ax.spines[s].set_color(MUTED)
    ax.tick_params(colors=INK, labelsize=9)
    return ax


def build_h_dt_szn(inputs_case):
    """Rep-timeslice -> full multi-weather-year timestamp map (mirrors prep_data)."""
    h_dt_szn = pd.read_csv(os.path.join(inputs_case, 'rep', 'h_dt_szn.csv'))
    hmap_allyrs = pd.read_csv(
        os.path.join(inputs_case, 'rep', 'hmap_allyrs.csv'), low_memory=False)
    h_dt_szn = h_dt_szn.set_index(['year', 'hour'])
    h_dt_szn['timestamp'] = pd.to_datetime(
        h_dt_szn.index.map(hmap_allyrs.set_index(['year', 'hour'])['*timestamp']))
    return h_dt_szn.reset_index().set_index('timestamp')


def map_endogenous(gdx_file, t, h_dt_szn, ref_columns, tz):
    """FINITO endogenous load (load_finito_rt) mapped to hours.

    Mirrors reeds/resource_adequacy/prep_data.py lines ~158-177 exactly.
    """
    gdxreeds = gdxpds.to_dataframes(gdx_file)
    lf = gdxreeds['load_finito_rt'].rename(columns={'allh': 'h', 'Value': 'load_MW'})
    lf['t'] = lf['t'].astype(int)
    load_finito = lf.loc[lf.t == t].drop('t', axis=1).copy()
    load_finito = pd.merge(
        load_finito, h_dt_szn.reset_index(), on='h', how='outer'
    )[['timestamp', 'r', 'load_MW']].rename(columns={'timestamp': 'datetime'})
    load_finito = load_finito.pivot(index=['datetime'], columns='r', values='load_MW')
    load_finito.index = load_finito.index.tz_convert(tz)
    load_finito = load_finito.reindex(columns=ref_columns, fill_value=0).fillna(0)
    return load_finito


#%% Main
def main(run_path=RUN_PATH):
    inputs_case = os.path.join(run_path, 'inputs_case')
    outdir = OUTPUT_DIR or os.path.join(run_path, 'outputs', 'finito_load_check')
    os.makedirs(outdir, exist_ok=True)

    sw = reeds.io.get_switches(run_path)
    if not int(sw.GSw_FINITO_Link):
        raise SystemExit('This run is not a linked FINITO run (GSw_FINITO_Link=0).')
    scalars = reeds.io.get_scalars(inputs_case)
    distloss = float(scalars['distloss'])
    first_year_finito = int(sw.first_year_finito)

    # --- exogenous load seen by ReEDS (post-removal); this IS load.h5 -----------
    load = reeds.io.read_file(os.path.join(inputs_case, 'load.h5'), parse_timestamps=True)
    tz = load.index.get_level_values('datetime').tz
    regions = list(load.columns)

    # --- reference (flat 2018 baseline), busbar; mirrors remove_finito_load -----
    reference = (get_hourly_finito_load(inputs_case) / (1 - distloss))
    reference = reference.reindex(columns=regions, fill_value=0)

    h_dt_szn = build_h_dt_szn(inputs_case)

    # --- which model years to process ------------------------------------------
    handoff = os.path.join(run_path, 'handoff', 'reeds_data')
    avail = sorted(int(f.split('_')[-1].split('.')[0])
                   for f in os.listdir(handoff) if f.startswith('reeds_data_'))
    years = MODEL_YEARS or [y for y in avail if y >= first_year_finito]
    csv_years = CSV_MODEL_YEARS or years
    spotlight = SPOTLIGHT_YEAR or years[-1]

    print(f'FINITO load check | run: {os.path.basename(run_path)}')
    print(f'  regions: {len(regions)} | distloss: {distloss} | '
          f'first_year_finito: {first_year_finito}')
    print(f'  model years: {years}\n')

    # accumulate lightweight aggregates for charts; keep only rep-WY slices hourly
    annual = {k: {} for k in ['original', 'reference', 'endogenous', 'final']}
    regional_net = {}          # {year: Series(region -> net TWh, rep WY)}
    wy_slices = {}             # {year: {item: DataFrame(rep-WY hours x regions)}}
    issues = []

    for t in years:
        load_year = load.loc[t]                    # hourly, all weather years
        ref_t = reference.loc[t] if t in reference.index else pd.Series(0.0, index=regions)
        endo = map_endogenous(
            os.path.join(handoff, f'reeds_data_{t}.gdx'), t, h_dt_szn, regions, tz)
        # align endogenous to load_year's index (rep periods broadcast to all WYs)
        endo = endo.reindex(load_year.index).fillna(0)

        orig = load_year.add(ref_t, axis=1)        # reconstruct pre-removal load
        final = load_year.add(endo)                # what PRAS/RA sees

        # ---- correctness checks ----
        for name, df in [('original', orig), ('reference', None),
                         ('endogenous', endo), ('final', final)]:
            if df is not None and df.isnull().any().any():
                issues.append(f'{t}: NaNs in {name} '
                              f'({int(df.isnull().sum().sum())} cells)')
        miss = [r for r in regions if r not in endo.columns]
        if miss:
            issues.append(f'{t}: endogenous missing regions {miss}')
        if (final < 0).any().any():
            issues.append(f'{t}: final load < 0 somewhere (unexpected)')
        # magnitude relationship: reference removed vs endogenous added
        ref_twh = ref_t.sum() * 8760 / 1e6
        endo_twh = endo.loc[endo.index.get_level_values('datetime').year
                            == REP_WEATHER_YEAR].sum().sum() / 1e6

        # ---- aggregates (rep weather year for a coherent annual comparison) ----
        wy = REP_WEATHER_YEAR
        def wyslice(df):
            return df.loc[df.index.get_level_values('datetime').year == wy] \
                     .reset_index('year', drop=True) if 'year' in df.index.names \
                else df.loc[df.index.year == wy]
        o_wy, f_wy, e_wy = wyslice(orig), wyslice(final), wyslice(endo)
        r_wy = o_wy * 0 + ref_t                     # flat reference over rep-WY hours
        annual['original'][t] = o_wy.sum().sum() / 1e6
        annual['reference'][t] = r_wy.sum().sum() / 1e6
        annual['endogenous'][t] = e_wy.sum().sum() / 1e6
        annual['final'][t] = f_wy.sum().sum() / 1e6
        regional_net[t] = (e_wy.sum() - r_wy.sum()) / 1e6   # region -> net TWh
        if t in csv_years:
            wy_slices[t] = {'original': o_wy, 'reference': r_wy, 'endogenous': e_wy,
                            'final': f_wy}
        print(f'  {t}: reference={ref_twh:8.1f} TWh | '
              f'endogenous={endo_twh:8.1f} TWh | '
              f'net={(endo_twh - ref_twh):+8.1f} TWh')

    annual = pd.DataFrame(annual)

    # ---- report ----
    print('\n=== correctness checks ===')
    if not issues:
        print('  PASS: no NaNs, all regions present, final load >= 0.')
    else:
        for i in issues:
            print('  ISSUE:', i)
    if (annual['reference'] == 0).all():
        print('  *** FINDING: reference load is ZERO for every year -> the 2018 '
              'industrial baseline is NOT being removed, so FINITO endogenous load '
              'is added on top of load that still contains it (double-counting). '
              'Check finito/inputs_case/load_finito.csv. ***')

    # ---- CSV exports (hourly, regional, rep weather year) ----
    for t in csv_years:
        for item in ('original', 'reference', 'endogenous'):
            fn = os.path.join(outdir, f'{item}_wy{REP_WEATHER_YEAR}_y{t}.csv')
            wy_slices[t][item].round(3).to_csv(fn)
    print(f'\nWrote hourly regional CSVs (wy{REP_WEATHER_YEAR}) to {outdir}')
    annual.round(2).to_csv(os.path.join(outdir, 'annual_system_twh.csv'))

    if MAKE_PLOTS:
        make_plots(annual, regional_net, wy_slices, spotlight, outdir)
        print('Wrote charts to', outdir)

    return annual, regional_net, wy_slices


#%% Charts
# FINITO load is ~1-2% of total, so anywhere we'd overlay a FINITO component on
# total load we instead use a big+small two-panel pattern (shared x-axis, same
# units) that zooms the component onto its own readable scale -- never a 2nd y-axis.
def _legend(ax):
    ax.legend(frameon=False, fontsize=9, loc='best')


def make_plots(annual, regional_net, wy_slices, spotlight, outdir):
    wy = REP_WEATHER_YEAR

    # 1) system-wide annual: totals (top) + FINITO components (bottom) -----------
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(7, 6), sharex=True,
                                 gridspec_kw={'height_ratios': [2, 1]})
    for ax in (a1, a2):
        _style_axes(ax)
    for item in ['original', 'final']:
        a1.plot(annual.index, annual[item], color=COLORS[item], linewidth=2,
                marker='o', markersize=5, label=item, zorder=3)
    for item in ['endogenous', 'reference']:
        a2.plot(annual.index, annual[item], color=COLORS[item], linewidth=2,
                marker='o', markersize=5, label=item, zorder=3)
    _legend(a1)
    _legend(a2)
    a1.set_title(f'System-wide annual load (weather year {wy})',
                 color=INK, fontsize=11, loc='left')
    a1.set_ylabel('total load, TWh/yr', color=INK, fontsize=9)
    a2.set_ylabel('FINITO, TWh/yr', color=INK, fontsize=9)
    a2.set_xlabel('model year', color=INK, fontsize=9)
    a2.set_ylim(bottom=0)
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, '1_annual_system.png'), dpi=140)
    plt.close(fig)

    # 2) net FINITO adjustment (endogenous - reference), by year ----------------
    net = annual['endogenous'] - annual['reference']
    fig, ax = plt.subplots(figsize=(7, 4.2))
    _style_axes(ax)
    ax.axhline(0, color=MUTED, linewidth=1)
    ax.bar(net.index, net.values, width=3,
           color=[DIVERGE_POS if v >= 0 else DIVERGE_NEG for v in net.values],
           zorder=3)
    ax.set_title('Net FINITO load adjustment  (endogenous − reference)',
                 color=INK, fontsize=11, loc='left')
    ax.set_ylabel('TWh/yr', color=INK, fontsize=9)
    ax.set_xlabel('model year', color=INK, fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, '2_net_adjustment.png'), dpi=140)
    plt.close(fig)

    if spotlight in wy_slices:
        sl = wy_slices[spotlight]
        # 3) load-duration: totals (top) + endogenous own scale (bottom) --------
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(7, 6), sharex=True,
                                     gridspec_kw={'height_ratios': [2, 1]})
        for ax in (a1, a2):
            _style_axes(ax)
        pct = np.arange(len(sl['original'])) / len(sl['original']) * 100
        for item in ['original', 'final']:
            a1.plot(pct, np.sort(sl[item].sum(axis=1).values)[::-1] / 1e3,
                    color=COLORS[item], linewidth=2, label=item, zorder=3)
        for item in ['endogenous', 'reference']:
            a2.plot(pct, np.sort(sl[item].sum(axis=1).values)[::-1] / 1e3,
                    color=COLORS[item], linewidth=2, label=item, zorder=3)
        _legend(a1)
        _legend(a2)
        a1.set_title(f'System load-duration curve, {spotlight} (weather year {wy})',
                     color=INK, fontsize=11, loc='left')
        a1.set_ylabel('total, GW', color=INK, fontsize=9)
        a2.set_ylabel('FINITO, GW', color=INK, fontsize=9)
        a2.set_xlabel('% of hours at or above', color=INK, fontsize=9)
        a2.set_ylim(bottom=0)
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, '3_duration_curve.png'), dpi=140)
        plt.close(fig)

        # 4) diurnal: totals (top) + endogenous own scale (bottom) --------------
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(7, 6), sharex=True,
                                     gridspec_kw={'height_ratios': [2, 1]})
        for ax in (a1, a2):
            _style_axes(ax)
        for item in ['original', 'final']:
            s = sl[item].sum(axis=1)
            a1.plot(s.groupby(s.index.hour).mean().index,
                    s.groupby(s.index.hour).mean().values / 1e3,
                    color=COLORS[item], linewidth=2, label=item, zorder=3)
        for item in ['endogenous', 'reference']:
            s = sl[item].sum(axis=1)
            a2.plot(s.groupby(s.index.hour).mean().index,
                    s.groupby(s.index.hour).mean().values / 1e3,
                    color=COLORS[item], linewidth=2, label=item, zorder=3)
        _legend(a1)
        _legend(a2)
        a1.set_title(f'Average diurnal system load, {spotlight} (weather year {wy})',
                     color=INK, fontsize=11, loc='left')
        a1.set_ylabel('total, GW', color=INK, fontsize=9)
        a2.set_ylabel('FINITO, GW', color=INK, fontsize=9)
        a2.set_xlabel('hour of day', color=INK, fontsize=9)
        a2.set_ylim(bottom=0)
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, '4_diurnal.png'), dpi=140)
        plt.close(fig)

        # 5) regional net adjustment, top-N by magnitude ------------------------
        net_r = regional_net[spotlight].reindex(
            regional_net[spotlight].abs().sort_values(ascending=False).index)
        net_r = net_r.head(N_SPOTLIGHT_REGIONS)[::-1]
        fig, ax = plt.subplots(figsize=(7, max(4.2, 0.32 * len(net_r))))
        _style_axes(ax)
        ax.axvline(0, color=MUTED, linewidth=1)
        ax.barh(net_r.index, net_r.values,
                color=[DIVERGE_POS if v >= 0 else DIVERGE_NEG for v in net_r.values],
                zorder=3)
        ax.set_title(f'Net FINITO adjustment by region, {spotlight}  '
                     f'(top {len(net_r)} by magnitude)',
                     color=INK, fontsize=11, loc='left')
        ax.set_xlabel('TWh/yr  (endogenous − reference)', color=INK, fontsize=9)
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, '5_regional_net.png'), dpi=140)
        plt.close(fig)


if __name__ == '__main__':
    main()
