"""
LCOE ranges/scenarios for a chosen region of a finished ReEDS case:

- Gas-CC (or any non-resource-constrained tech via --gas-tech): two scenario lines, each
  with a +/-X% fuel-price band (--fuel-price-pct) -- the run's own capital cost, and a
  second scenario with a flat $/kW capital-cost increase (--capex-add).
- UPV / wind-ons: two scenario bands, each spanning the min-to-max LCOE across every
  resource class present in the region (the capacity-factor-driven spread across classes,
  not the individual class lines) -- one under the run's own ATB cost assumption, one under
  a separate (typically higher-cost) ATB cost file (--upv-conservative/--wind-conservative).

Shares the LCOE formula and K-residual calibration approach with lcoe_sensitivity.py (see
that script's docstring for the full derivation): back out a fixed FOM(+site-cost) residual
K that makes the formula reproduce the run's own reported `lcoe` exactly at baseline, then
hold K fixed while scaling capital cost and/or fuel price for each scenario.

ATB conservative-cost scaling
------------------------------
The raw ATB cost files in inputs/plant_characteristics/ are not in the same units/
normalization as the processed inputs_case/plantcharout.csv (confirmed empirically:
plantcharout's capcost is a *constant* multiple of the raw ATB file's capcost, for every
year -- almost certainly an AC/DC or ILR conversion applied uniformly regardless of cost
scenario, not worth reverse-engineering exactly). Rather than use the conservative file's
absolute values directly, this script computes

    capex_ratio(t) = raw_conservative_capcost(t) / raw_moderate_capcost(t)

from the two raw files (the moderate file is looked up from the case's own switches --
plantchar_upv/plantchar_onswind) and applies that ratio to *both* the run's own processed
capital cost and the calibrated K (FOM + site-cost) term, since K can't be decomposed into a
separate FOM piece to scale on its own. The capital-cost shift is therefore exact; the
FOM shift is an approximation (checked against the raw files: FOM's own conservative/
moderate ratio tracks capex's ratio closely but not exactly, e.g. 1.20 vs 1.31 at 2035 for
UPV). Capacity factor is left untouched -- it comes from the run's own resource profiles,
not from the ATB files' CF_mult/cf_improvement columns (a turbine/module vintage factor,
distinct from resource-class CF, and out of scope for a cost-only comparison).

Usage
-----
    python lcoe_range.py <path-to-case> --region WI --region-level st

Run with --help for the full list of options.

Outputs
-------
Written to {case}/outputs/plots/lcoe_range/ by default:
- lcoe_range.csv -- tidy scenario/class-level LCOE behind every band
- lcoe_range.png -- one panel per family (the --gas-tech, UPV, wind-ons), each showing two
  scenario bands (see above)
"""
import argparse
import os
import re
import sys

import matplotlib
## Force a non-interactive backend: this script only ever calls savefig(), and an
## interactive backend (e.g. Qt) can crash hard when run without a display attached.
matplotlib.use('Agg')
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds
from reeds import plots as reedsplots_style


#%% ===========================================================================
### --- ARGUMENTS ---
### ===========================================================================
def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            'LCOE ranges: fuel-price/capex-adder scenarios for a non-RSC tech, and '
            'resource-class + ATB-cost-scenario ranges for UPV/wind-ons.'
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('case_positional', type=str, nargs='?', help='path to ReEDS run folder')
    parser.add_argument('--case', '-c', type=str, help='path to ReEDS run folder')
    parser.add_argument(
        '--savepath', type=str, default=None,
        help='output directory (default: {case}/outputs/plots/lcoe_range)',
    )
    parser.add_argument(
        '--region', type=str, required=True,
        help='region to plot, e.g. a literal BA (CA_LA) or a value within --region-level (e.g. WI)',
    )
    parser.add_argument(
        '--region-level', type=str, default='st',
        help='hierarchy.csv column that --region is a value of; "r" treats --region as a literal BA',
    )
    parser.add_argument(
        '--gas-tech', type=str, default='Gas-CC',
        help='non-resource-constrained tech to show the fuel-price/capex-adder range for',
    )
    parser.add_argument(
        '--upv-conservative', type=str,
        default=os.path.join('inputs', 'plant_characteristics', 'upv_ATB_2024_conservative.csv'),
        help='ATB cost file providing the higher-cost UPV range (relative to the repo root, or absolute)',
    )
    parser.add_argument(
        '--wind-conservative', type=str,
        default=os.path.join('inputs', 'plant_characteristics', 'ons-wind_ATB_2024_conservative.csv'),
        help='ATB cost file providing the higher-cost wind-ons range (relative to the repo root, or absolute)',
    )
    parser.add_argument(
        '--fuel-price-pct', type=float, default=20,
        help='+/- percent fuel-price range to show for --gas-tech',
    )
    parser.add_argument(
        '--capex-add', type=float, default=800,
        help='flat capital-cost increase ($/kW, in --dollar-year dollars) for the second --gas-tech scenario',
    )
    parser.add_argument('--dollar-year', type=int, default=2024, help='dollar year to inflate $ values to')
    parser.add_argument(
        '--first-year', type=int, default=2026,
        help='first endogenous solve year; earlier years are fixed to historical data and excluded',
    )
    parser.add_argument('--last-year', type=int, default=2050, help='last year to show')

    args = parser.parse_args()
    if args.case_positional and args.case:
        raise ValueError('Provide case as positional argument or --case/-c, not both')
    case = args.case_positional or args.case
    if not case:
        raise ValueError('Provide case path either as positional argument or as --case/-c')
    return args, case


def resolve_regions(case, region, region_level):
    """Return a list of BAs (r) matching --region/--region-level."""
    if region_level == 'r':
        return [region]
    hierarchy = reeds.io.get_hierarchy(case)
    regions = hierarchy.index[hierarchy[region_level].str.lower() == region.lower()].tolist()
    if not regions:
        raise ValueError(f"No regions found for {region_level} == '{region}' in hierarchy.csv")
    return regions


#%% ===========================================================================
### --- DATA LOADING ---
### ===========================================================================
FUEL_COLUMN_BY_PREFIX = {'gas': 'naturalgas', 'h2-cc': 'naturalgas', 'h2-ct': 'naturalgas',
                          'coal': 'coal', 'nuclear': 'uranium'}


def get_fuel_column(tech_lower):
    for prefix, col in FUEL_COLUMN_BY_PREFIX.items():
        if tech_lower.startswith(prefix):
            return col
    return None


def load_plantchar(case):
    """Load inputs_case/plantcharout.csv into a wide (i_lower, t) frame (see lcoe_sensitivity.py)."""
    pc = pd.read_csv(os.path.join(case, 'inputs_case', 'plantcharout.csv')).rename(columns={'*i': 'i'})
    pc['i_lower'] = pc['i'].str.lower()
    wide = pc.pivot_table(index=['i_lower', 't'], columns='variable', values='value', aggfunc='first')
    return wide.reset_index()


def load_crf(case):
    fin = pd.read_csv(os.path.join(case, 'inputs_case', 'financials_sys_full.csv'))
    return fin.set_index('t')['crf']


def load_fuel_price(case):
    return pd.read_csv(os.path.join(case, 'inputs_case', 'fprice.csv'))


def load_cf_vre_annual(case):
    """Numhours-weighted annual average CF per (i_lower, r), from resource profiles."""
    cf = pd.read_csv(os.path.join(case, 'inputs_case', 'rep', 'cf_vre.csv')).rename(columns={'*i': 'i'})
    nh = pd.read_csv(os.path.join(case, 'inputs_case', 'rep', 'numhours.csv')).rename(columns={'*h': 'h'})
    cf = cf.merge(nh, on='h', how='left')
    cf['i_lower'] = cf['i'].str.lower()

    def weighted_cf(group):
        return np.average(group['cf'], weights=group['numhours'])

    ## Note: not passing include_groups=False for compatibility with pandas < 2.2.
    return cf.groupby(['i_lower', 'r']).apply(weighted_cf).rename('cf_annual').reset_index()


def get_deflator(dollar_year):
    """2004$ per --dollar-year$ (the inverse of reeds.results.inflate_series's direction)."""
    d = pd.read_csv(os.path.join(reeds.io.reeds_path, 'inputs', 'financials', 'deflator.csv'), index_col=0)
    return d.loc[dollar_year, 'Deflator']


def find_available_classes(case, prefix, regions):
    """Every raw i starting with '{prefix}_' (e.g. 'upv', 'wind-ons') that has lcoe data in
    `regions` -- i.e. every resource class available to build there, not just built ones."""
    lcoe = reeds.io.read_output(case, 'lcoe')
    lcoe = lcoe[lcoe.r.isin(regions)]
    all_i = lcoe['i'].unique()
    classes = [i for i in all_i if i.lower().startswith(prefix.lower() + '_')]
    return sorted(classes, key=lambda i: int(re.match(r'.+_(\d+)$', i).group(1)))


def load_capex_ratio(case, moderate_switch, conservative_path):
    """
    Ratio of conservative-scenario to moderate-scenario raw capital cost by year, from the
    two ATB plant-characteristics files -- see module docstring for why a ratio (rather than
    the conservative file's absolute value) is used. `moderate_switch` is the case's own
    plantchar_upv/plantchar_onswind switch value, so this always compares against whichever
    moderate scenario the run actually used.
    """
    moderate_path = os.path.join(
        reeds.io.reeds_path, 'inputs', 'plant_characteristics', f'{moderate_switch}.csv')
    mod = pd.read_csv(moderate_path)
    cons = pd.read_csv(conservative_path)
    ## UPV-style files are (t, capcost, ...); wind-style files are (Turbine, Year, ...,
    ## 'Overnight Cap Cost $/kW', ...) -- detect which and normalize to a (year -> capcost) Series.
    if 'capcost' in mod.columns:
        mod_s = mod.set_index('t')['capcost']
        cons_s = cons.set_index('t')['capcost']
    else:
        mod_s = mod.set_index('Year')['Overnight Cap Cost $/kW']
        cons_s = cons.set_index('Year')['Overnight Cap Cost $/kW']
    return (cons_s / mod_s).rename('capex_ratio')


#%% ===========================================================================
### --- CORE CALCULATION ---
### ===========================================================================
def compute_gas_scenarios(case, tech, regions, fuel_pct, capex_add_kw, dollar_year, first_year, last_year):
    """
    Two scenarios for a non-RSC tech: baseline capital cost, and baseline + capex_add_kw
    ($/kW, dollar_year$), each evaluated at fuel-price multipliers of
    1 -+ fuel_pct/100 -- the 1.0 rows are the scenario's line, the full spread is its band.
    """
    lcoe = reeds.io.read_output(case, 'lcoe')
    lcoe['t'] = lcoe['t'].astype(int)
    lcoe = lcoe[
        (lcoe.i == tech) & (lcoe.r.isin(regions)) & (lcoe.t >= first_year) & (lcoe.t <= last_year)
    ].copy()
    assert len(lcoe), f"No 'lcoe' rows found for '{tech}' in {regions}"
    ## Use the cheapest available resource bin per (i,v,r,t) as the representative site
    lcoe = lcoe.sort_values('rscbin').groupby(['i', 'v', 'r', 't'], as_index=False).first()
    lcoe['i_lower'] = lcoe['i'].str.lower()

    avg_avail = reeds.io.read_output(case, 'avg_avail')
    fin_mult = reeds.io.read_output(case, 'cost_cap_fin_mult')
    fin_mult['t'] = fin_mult['t'].astype(int)
    crf = load_crf(case)
    plantchar = load_plantchar(case)
    fprice = load_fuel_price(case)

    df = lcoe.merge(fin_mult.rename(columns={'Value': 'fin_mult'}), on=['i', 'r', 't'], how='left')
    df = df.merge(
        plantchar.rename(columns={'capcost': 'cost_cap', 'vom': 'cost_vom', 'heatrate': 'heat_rate'}),
        on=['i_lower', 't'], how='left',
    )
    df['crf'] = df['t'].map(crf)
    df = df.merge(avg_avail.rename(columns={'Value': 'cf_baseline'}), on=['i', 'v', 'r'], how='left')

    fuel_col = get_fuel_column(tech.lower())
    assert fuel_col is not None, f"'{tech}' has no recognized fuel -- check FUEL_COLUMN_BY_PREFIX"
    fp = fprice[['t', 'r', fuel_col]].rename(columns={fuel_col: 'fuel_price'})
    df = df.merge(fp, on=['t', 'r'], how='left')
    df['fuel_term_base'] = df['heat_rate'] * df['fuel_price']

    ## Back out the calibrated FOM-equivalent residual K that reproduces the baseline `lcoe`
    ## exactly (see module/lcoe_sensitivity.py docstring).
    df['K'] = (
        df['Value'] * df['cf_baseline'] * 8760
        - df['crf'] * df['fin_mult'] * df['cost_cap']
        - df['fuel_term_base'] * df['cf_baseline'] * 8760
    )

    deflator = get_deflator(dollar_year)
    capex_add_2004 = capex_add_kw * 1000 * deflator  # $/kW (dollar_year$) -> $/MW (native 2004$)

    rows = []
    scenarios = [('ATB Moderate', 0.0), (f'+${capex_add_kw:.0f}/kW capex', capex_add_2004)]
    for scenario, cost_cap_add in scenarios:
        cost_cap_s = df['cost_cap'] + cost_cap_add
        for fuel_mult in sorted({1 - fuel_pct / 100, 1.0, 1 + fuel_pct / 100}):
            fuel_term_s = df['heat_rate'] * df['fuel_price'] * fuel_mult
            lcoe_s = (
                (df['crf'] * df['fin_mult'] * cost_cap_s + df['K']) / (df['cf_baseline'] * 8760)
                + df['cost_vom'] + fuel_term_s
            )
            rows.append(pd.DataFrame({
                'family': tech, 'scenario': scenario, 'fuel_mult': fuel_mult,
                'r': df['r'], 't': df['t'], 'lcoe': lcoe_s,
            }))
    out = pd.concat(rows, ignore_index=True)
    out['lcoe'] = reeds.results.inflate_series(out['lcoe'], to_dollar_year=dollar_year)
    return out


def compute_rsc_scenarios(case, prefix, family_label, regions, capex_ratio, dollar_year, first_year, last_year):
    """
    Two scenarios for an RSC family (e.g. every upv_* or wind-ons_* class present in
    `regions`): baseline (the run's own, i.e. ATB moderate, cost) and ATB Conservative
    (capex_ratio-scaled), each evaluated for every resource class -- the min-to-max spread
    across classes is the scenario's band; see module docstring for the ATB-scaling approach.
    """
    classes = find_available_classes(case, prefix, regions)
    assert classes, f"No '{prefix}_*' resource classes with lcoe data in {regions}"

    lcoe = reeds.io.read_output(case, 'lcoe')
    lcoe['t'] = lcoe['t'].astype(int)
    lcoe = lcoe[
        (lcoe.i.isin(classes)) & (lcoe.r.isin(regions)) & (lcoe.t >= first_year) & (lcoe.t <= last_year)
    ].copy()
    lcoe = lcoe.sort_values('rscbin').groupby(['i', 'v', 'r', 't'], as_index=False).first()
    lcoe['i_lower'] = lcoe['i'].str.lower()

    fin_mult = reeds.io.read_output(case, 'cost_cap_fin_mult')
    fin_mult['t'] = fin_mult['t'].astype(int)
    crf = load_crf(case)
    plantchar = load_plantchar(case)
    cf_vre = load_cf_vre_annual(case)

    df = lcoe.merge(fin_mult.rename(columns={'Value': 'fin_mult'}), on=['i', 'r', 't'], how='left')
    df = df.merge(
        plantchar.rename(columns={'capcost': 'cost_cap', 'vom': 'cost_vom'}), on=['i_lower', 't'], how='left',
    )
    df['crf'] = df['t'].map(crf)
    df = df.merge(cf_vre.rename(columns={'cf_annual': 'cf_baseline'}), on=['i_lower', 'r'], how='left')
    assert df['cf_baseline'].notna().all(), 'Missing baseline capacity factor for some (i,r,t) rows'

    df['K'] = (
        df['Value'] * df['cf_baseline'] * 8760
        - df['crf'] * df['fin_mult'] * df['cost_cap']
        - df['cost_vom'] * df['cf_baseline'] * 8760
    )

    ratio_by_year = df['t'].map(capex_ratio)
    assert ratio_by_year.notna().all(), 'capex_ratio is missing a year present in the lcoe data'

    rows = []
    for scenario, mult in [('ATB Moderate', 1.0), ('ATB Conservative', ratio_by_year)]:
        cost_cap_s = df['cost_cap'] * mult
        K_s = df['K'] * mult
        lcoe_s = (df['crf'] * df['fin_mult'] * cost_cap_s + K_s) / (df['cf_baseline'] * 8760) + df['cost_vom']
        rows.append(pd.DataFrame({
            'family': family_label, 'scenario': scenario, 'i': df['i'], 'r': df['r'], 't': df['t'], 'lcoe': lcoe_s,
        }))
    out = pd.concat(rows, ignore_index=True)
    out['lcoe'] = reeds.results.inflate_series(out['lcoe'], to_dollar_year=dollar_year)
    return out


#%% ===========================================================================
### --- PLOTTING ---
### ===========================================================================
def resolve_tech_display(tech_lower, tech_map):
    """See lcoe_sensitivity.py: tech_map.csv mixes exact keys with trailing-'*' prefix
    patterns (e.g. 'upv*' -> 'UPV'); a plain dict lookup never matches those."""
    if tech_lower in tech_map.index:
        return tech_map[tech_lower]
    best_prefix, best_display = '', None
    for key, display in tech_map.items():
        if key.endswith('*') and tech_lower.startswith(key[:-1]) and len(key) > len(best_prefix):
            best_prefix, best_display = key, display
    return best_display


def shade_colors(base_hex, n, lighten=0.7):
    """
    n distinguishable shades of a base color, lightest to darkest (see lcoe_sensitivity.py).
    `lighten` controls how far the lightest shade sits toward white; the default (0.7) suits
    a filled band, but is too pale for a line to read clearly against white, so callers that
    need a line color should pass a smaller `lighten` (e.g. 0.35) for that use.
    """
    if n == 1:
        return [base_hex]
    base_rgb = np.array(mcolors.to_rgb(base_hex))
    light_rgb = base_rgb + (1 - base_rgb) * lighten
    shades = [tuple(light_rgb + (base_rgb - light_rgb) * frac) for frac in np.linspace(0, 1, n)]
    return [mcolors.to_hex(s) for s in shades]


def get_family_color(family):
    fmt = reeds.io.get_plot_formatting()
    tech_map, tech_color = fmt['tech_map'], fmt['tech_color']['color']
    display = resolve_tech_display(family.lower(), tech_map)
    if display is None:
        display = family
    return tech_color.get(display, '#666666'), display


def plot_lcoe_range(dfgas, dfupv, dfwind, savepath, units, gas_tech):
    panels = [
        (dfgas, gas_tech, 'fuel_mult'),
        (dfupv, 'upv', None),
        (dfwind, 'wind-ons', None),
    ]
    fig, axes = plt.subplots(1, len(panels), figsize=(5.2 * len(panels), 4.5), sharey=False)
    axes = np.atleast_1d(axes)

    for ax, (df, family, band_col) in zip(axes, panels):
        base, display = get_family_color(family)
        scenarios = list(dict.fromkeys(df['scenario']))
        ## scenarios[0] is always the cheaper/baseline (ATB Moderate) case (see
        ## compute_gas_scenarios/compute_rsc_scenarios); shade_colors returns lightest-to-
        ## darkest, so reverse it to put the darker shade on the cheaper case and the
        ## lighter shade on the more expensive alternative. Lines use a separately (less)
        ## lightened set than the fills: the fill's pale shade reads fine as an area, but is
        ## too washed out for a line against a white background.
        fill_shades = shade_colors(base, len(scenarios))[::-1]
        line_shades = shade_colors(base, len(scenarios), lighten=0.35)[::-1]
        for scenario, fill_color, line_color in zip(scenarios, fill_shades, line_shades):
            sub = df[df.scenario == scenario]
            band = sub.groupby('t')['lcoe'].agg(['min', 'max', 'mean'])
            years = band.index
            ax.fill_between(years, band['min'], band['max'], color=fill_color, alpha=0.35, lw=0)
            center = band['mean'] if band_col is None else sub.loc[sub[band_col] == 1.0].groupby('t')['lcoe'].mean()
            ax.plot(years, center.reindex(years), color=line_color, marker='o', ms=4, lw=1.75, label=scenario)
        ## All three families' data sit well above y=0 (LCOE bands don't approach zero), so
        ## an inside-axes legend anchored to the bottom stays clear of every line/band,
        ## unlike 'upper left'/'best', which collide with the highest (leftmost) points.
        ax.set_ylim(bottom=0)
        ax.set_title(display)
        ax.set_xlabel('Year')
        ax.set_ylabel(f'LCOE [{units}]')
        ax.legend(frameon=False, fontsize=8, loc='lower left')
        reedsplots_style.despine(ax)

    plt.tight_layout()
    plt.savefig(os.path.join(savepath, 'lcoe_range.png'))
    plt.close()


#%% ===========================================================================
### --- MAIN ---
### ===========================================================================
def main():
    args, case = parse_args()
    case = os.path.abspath(case)
    savepath = args.savepath or os.path.join(case, 'outputs', 'plots', 'lcoe_range')
    os.makedirs(savepath, exist_ok=True)

    reedsplots_style.plotparams()
    regions = resolve_regions(case, args.region, args.region_level)
    switches = reeds.io.get_switches(case)

    dfgas = compute_gas_scenarios(
        case, args.gas_tech, regions, args.fuel_price_pct, args.capex_add,
        args.dollar_year, args.first_year, args.last_year,
    )

    upv_conservative = args.upv_conservative if os.path.isabs(args.upv_conservative) else \
        os.path.join(reeds.io.reeds_path, args.upv_conservative)
    wind_conservative = args.wind_conservative if os.path.isabs(args.wind_conservative) else \
        os.path.join(reeds.io.reeds_path, args.wind_conservative)
    upv_ratio = load_capex_ratio(case, switches['plantchar_upv'], upv_conservative)
    wind_ratio = load_capex_ratio(case, switches['plantchar_onswind'], wind_conservative)

    dfupv = compute_rsc_scenarios(
        case, 'upv', 'upv', regions, upv_ratio, args.dollar_year, args.first_year, args.last_year)
    dfwind = compute_rsc_scenarios(
        case, 'wind-ons', 'wind-ons', regions, wind_ratio, args.dollar_year, args.first_year, args.last_year)

    dfall = pd.concat([dfgas, dfupv, dfwind], ignore_index=True)
    dfall.to_csv(os.path.join(savepath, 'lcoe_range.csv'), index=False)
    print(f'Wrote {os.path.join(savepath, "lcoe_range.csv")}')

    plot_lcoe_range(dfgas, dfupv, dfwind, savepath, units=f'{args.dollar_year}$/MWh', gas_tech=args.gas_tech)
    print(f'Wrote {os.path.join(savepath, "lcoe_range.png")}')


if __name__ == '__main__':
    main()
