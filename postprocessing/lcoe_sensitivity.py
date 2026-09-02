"""
Explore how the LCOE of a technology in a finished ReEDS case would change under a
different capital-cost or capacity-factor assumption, for a chosen region.

ReEDS reports its own LCOE as `lcoe(i,v,r,t,rscbin)` (see report.gms, "LCOE" section),
computed from the run's own capital cost, financing, O&M, capacity factor, and fuel
price assumptions. That value is fixed once the run finishes -- this script lets you
ask "what if capital cost were 20% lower" or "what if capacity factor were 10% higher"
without re-running the model.

Methodology
-----------
report.gms computes LCOE with the closed form (both the non-resource-constrained branch,
e.g. Gas-CC, and the resource-supply-curve branch, e.g. upv/wind-ons):

    LCOE = (crf(t) * cost_cap_fin_mult(i,r,t) * cost_cap(i,t) + K) / (CF * 8760)
           + cost_vom(i,v,r,t) + heat_rate(i,v,r,t) * fuel_price(i,r,t)

where CF is `avg_avail(i,v,r)` for non-RSC techs or the resource-profile-driven annual
capacity factor for RSC techs, and K is fixed O&M (plus, for RSC techs, a resource-site
interconnection cost baked into the same numerator).

`cost_cap(i,t)` and `fuel_price(i,r,t)` are clean, unambiguous, single-year values (no
vintage-cohort averaging). `cost_fom`/`cost_vom`/`heat_rate`, however, are in general a
*vintage-cohort average* over several years (see b_inputs.gms, "VOM costs by v are
averaged over the class's associated years"), which cannot be reproduced exactly from
the single-year `plantcharout.csv` values, and the RSC branch's site/interconnection
cost adder is a GAMS-internal sum over feasible sites not worth re-deriving directly
(see AGENTS.md's guidance against reimplementing model internals).

Rather than approximating those, this script backs out `K` as the residual that makes
the formula above reproduce the run's own reported `lcoe` *exactly* at baseline:

    K = lcoe_baseline * CF_baseline * 8760
        - crf(t) * cost_cap_fin_mult(i,r,t) * cost_cap(i,t)
        - (cost_vom(i,t) + heat_rate(i,t) * fuel_price(i,r,t)) * CF_baseline * 8760

`K` is then held fixed while `cost_cap` and/or `CF` are scaled by the user's
`--capex-mult`/`--cf-mult` overrides. `cost_vom`/`heat_rate`/`fuel_price` are also held
at their run values (their vintage-averaging error is small in absolute $/MWh terms
relative to capital cost and FOM). Net effect: the baseline case in the output CSV/plot
always matches ReEDS's own reported LCOE exactly; only the *response* to a capex/CF
override carries this approximation, which is the right place for it to live.

CF_baseline is sourced two ways depending on the technology:
- Techs present in `inputs_case/rep/cf_vre.csv` (upv, wind-ons, wind-ofs, etc.): the
  numhours-weighted annual average of the resource profile, approximating `gen_rsc/8760`.
- All other techs (e.g. Gas-CC): `avg_avail(i,v,r)` from outputs.h5, exactly as report.gms
  uses it (this is an availability/outage-derate factor, not a dispatched capacity
  factor -- consistent with how report.gms treats non-RSC techs).

Usage
-----
    python lcoe_sensitivity.py <path-to-case> --region WI --region-level st
    python lcoe_sensitivity.py <path-to-case> --region WI --region-level st \\
        --techs Gas-CC,upv_1,upv_2,wind-ons_5 \\
        --capex-mult upv_1=0.8,upv_2=0.8 --cf-mult wind-ons_5=1.1

A --techs entry with no exact match (e.g. "upv", the default) is expanded to every
"{entry}_*" resource class with lcoe data in the region -- i.e. every class *available to
build* there, not just the ones actually invested in (see expand_tech_families). Pass
exact class names instead (e.g. "upv_1,upv_2") to plot only a subset. --capex-mult/--cf-mult
similarly accept either an exact class or a bare family name to scale every class in it.

Run with --help for the full list of options.

Outputs
-------
Written to {case}/outputs/plots/lcoe_sensitivity/ by default:
- lcoe_sensitivity.csv -- tidy (i, r, t) baseline and scenario LCOE, one row per resource
  class/region/year
- lcoe_sensitivity.png -- one panel per tech family (e.g. every upv_* class on one panel,
  every wind-ons_* class on another, Gas-CC alone) showing the region-average baseline
  (solid) vs. scenario (dashed) LCOE by year, one line per resource class -- to show the
  range of LCOE across classes, not just a single number per family
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
        description='Explore LCOE sensitivity to capital cost and capacity factor assumptions.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ## Include both case_positional and --case/-c, matching compare_tech_value.py convention
    parser.add_argument('case_positional', type=str, nargs='?', help='path to ReEDS run folder')
    parser.add_argument('--case', '-c', type=str, help='path to ReEDS run folder')
    parser.add_argument(
        '--savepath', type=str, default=None,
        help='output directory (default: {case}/outputs/plots/lcoe_sensitivity)',
    )
    parser.add_argument(
        '--techs', type=str, default='Gas-CC,upv,wind-ons',
        help=(
            'comma-separated technology names, exactly as they appear in outputs.h5 '
            '(case-sensitive -- e.g. "Gas-CC", not "gas-cc"). A name with no exact match '
            '(e.g. "upv") is expanded to every "{name}_*" resource class with lcoe data in '
            'the requested region (available to build, not just actually built) -- e.g. '
            '"upv" -> upv_1, upv_2, ...; pass exact classes instead (e.g. "upv_1,upv_2") to '
            'plot only a subset'
        ),
    )
    parser.add_argument(
        '--region', type=str, default=None,
        help=(
            'restrict to a single region, e.g. a literal BA (CA_LA) or a value within '
            '--region-level (e.g. WI with --region-level st); default: no filter (all regions, '
            'which is rarely what you want -- expect a lot of output)'
        ),
    )
    parser.add_argument(
        '--region-level', type=str, default='r',
        help='hierarchy.csv column that --region is a value of, e.g. st, transreg, interconnect',
    )
    parser.add_argument(
        '--capex-mult', type=str, default='',
        help=(
            'comma-separated TECH=MULT capital-cost overrides, e.g. "upv_1=0.8,upv_2=0.8" or, '
            'to scale every class in a family at once, "upv=0.8"'
        ),
    )
    parser.add_argument(
        '--cf-mult', type=str, default='',
        help=(
            'comma-separated TECH=MULT capacity-factor/availability overrides, e.g. '
            '"wind-ons_5=1.1" or "wind-ons=1.1" to scale every class in the family'
        ),
    )
    parser.add_argument('--dollar-year', type=int, default=2024, help='dollar year to inflate $ values to')
    parser.add_argument(
        '--first-year', type=int, default=2026,
        help='first endogenous solve year; earlier years are fixed to historical data and excluded',
    )

    args = parser.parse_args()
    if args.case_positional and args.case:
        raise ValueError('Provide case as positional argument or --case/-c, not both')
    case = args.case_positional or args.case
    if not case:
        raise ValueError('Provide case path either as positional argument or as --case/-c')
    return args, case


def parse_mult_overrides(s):
    """Parse 'TECH=MULT,TECH=MULT' into {TECH: float(MULT)}."""
    out = {}
    for item in s.split(','):
        item = item.strip()
        if not item:
            continue
        tech, val = item.split('=')
        out[tech.strip()] = float(val)
    return out


def resolve_regions(case, region, region_level):
    """Return a list of BAs (r) matching --region/--region-level, or None if --region is unset."""
    if region is None:
        return None
    if region_level == 'r':
        return [region]
    hierarchy = reeds.io.get_hierarchy(case)
    regions = hierarchy.index[hierarchy[region_level] == region].tolist()
    if not regions:
        raise ValueError(f"No regions found for {region_level} == '{region}' in hierarchy.csv")
    return regions


def get_tech_family(tech):
    """Strip a trailing resource-class suffix (e.g. 'upv_1' -> 'upv', 'wind-ons_10' ->
    'wind-ons') to get the panel a tech is plotted on; a tech with no such suffix (e.g.
    'Gas-CC') is its own family/panel."""
    m = re.match(r'^(.+)_\d+$', tech)
    return m.group(1) if m else tech


def expand_tech_families(case, techs, regions):
    """
    Expand any --techs entry with no exact match among this case's `lcoe` output `i` values
    (restricted to `regions`, if given) into every matching '{entry}_*' resource class with
    lcoe data there -- i.e. every class with resource potential in the region ("available to
    build"), not just the ones actually invested in. An entry that's already an exact class
    name (e.g. 'upv_1') or has no class suffix at all (e.g. 'Gas-CC') passes through as-is.

    Returns (techs_raw, tech_family): techs_raw is every raw i to plot; tech_family maps each
    raw i to the panel/family label it's grouped under (get_tech_family for an exact-match
    entry, or the original --techs entry it was expanded from).
    """
    lcoe = reeds.io.read_output(case, 'lcoe')
    if regions is not None:
        lcoe = lcoe[lcoe.r.isin(regions)]
    all_i = set(lcoe['i'].unique())
    tech_family = {}
    for tech in techs:
        if tech in all_i:
            tech_family[tech] = get_tech_family(tech)
            continue
        prefix = tech.lower() + '_'
        matches = sorted(i for i in all_i if i.lower().startswith(prefix))
        if not matches:
            raise AssertionError(
                f"'{tech}' has no exact match and no '{tech}_*' resource classes with lcoe "
                "data in this case/region -- check --techs against outputs.h5."
            )
        for m in matches:
            tech_family[m] = tech
    return list(tech_family.keys()), tech_family


def resolve_mult(tech, overrides, tech_family):
    """Look up a TECH=MULT override for `tech` itself, falling back to its family (e.g.
    "--capex-mult upv=0.8" applies to every upv_N class), then to 1.0 (no change)."""
    if tech in overrides:
        return overrides[tech]
    return overrides.get(tech_family.get(tech, tech), 1.0)


#%% ===========================================================================
### --- DATA LOADING ---
### ===========================================================================
FUEL_COLUMN_BY_PREFIX = {'gas': 'naturalgas', 'h2-cc': 'naturalgas', 'h2-ct': 'naturalgas',
                          'coal': 'coal', 'nuclear': 'uranium'}


def load_plantchar(case):
    """
    Load inputs_case/plantcharout.csv into a wide (i_lower, t) -> {capcost, fom, vom,
    heatrate, ...} frame. `i` casing is inconsistent across ReEDS input/output files
    (e.g. 'UPV_1' here vs. 'upv_1' in outputs.h5), so match on lowercase throughout.
    """
    pc = pd.read_csv(os.path.join(case, 'inputs_case', 'plantcharout.csv'))
    pc = pc.rename(columns={'*i': 'i'})
    pc['i_lower'] = pc['i'].str.lower()
    wide = pc.pivot_table(index=['i_lower', 't'], columns='variable', values='value', aggfunc='first')
    return wide.reset_index()


def load_crf(case):
    fin = pd.read_csv(os.path.join(case, 'inputs_case', 'financials_sys_full.csv'))
    return fin.set_index('t')['crf']


def load_fuel_price(case):
    """Wide (t, r) -> $/MMBtu by fuel type."""
    return pd.read_csv(os.path.join(case, 'inputs_case', 'fprice.csv'))


def load_cf_vre_annual(case):
    """Numhours-weighted annual average CF per (i_lower, r), from resource profiles."""
    cf = pd.read_csv(os.path.join(case, 'inputs_case', 'rep', 'cf_vre.csv')).rename(columns={'*i': 'i'})
    nh = pd.read_csv(os.path.join(case, 'inputs_case', 'rep', 'numhours.csv')).rename(columns={'*h': 'h'})
    cf = cf.merge(nh, on='h', how='left')
    cf['i_lower'] = cf['i'].str.lower()

    def weighted_cf(group):
        return np.average(group['cf'], weights=group['numhours'])

    ## Note: not passing include_groups=False for compatibility with pandas < 2.2;
    ## weighted_cf only touches named value columns, so the grouping columns are harmless.
    out = cf.groupby(['i_lower', 'r']).apply(weighted_cf).rename('cf_annual').reset_index()
    return out


def get_fuel_column(tech_lower):
    for prefix, col in FUEL_COLUMN_BY_PREFIX.items():
        if tech_lower.startswith(prefix):
            return col
    return None


#%% ===========================================================================
### --- CORE CALCULATION ---
### ===========================================================================
def compute_lcoe_sensitivity(case, techs, tech_family, regions, capex_mult, cf_mult, first_year):
    """
    For each (i, r, t), back out a calibrated FOM(+site-cost)-equivalent residual K from
    the run's own reported `lcoe`, then recompute a scenario LCOE with the user's
    capex/CF multipliers applied, holding K, cost_vom, heat_rate, and fuel_price fixed
    at the run's values. See module docstring for the full derivation.

    Returns a tidy (i, r, t) DataFrame with lcoe_baseline and lcoe_scenario (both in
    the run's native 2004$/MWh -- inflate separately for display).
    """
    lcoe = reeds.io.read_output(case, 'lcoe')
    lcoe['t'] = lcoe['t'].astype(int)
    lcoe = lcoe[lcoe.i.isin(techs) & (lcoe.t >= first_year)].copy()
    if regions is not None:
        lcoe = lcoe[lcoe.r.isin(regions)]
    missing = [t for t in techs if t not in lcoe.i.unique()]
    if missing:
        raise AssertionError(
            f"No 'lcoe' rows found for {missing} in the requested region(s). Tech names are "
            "case-sensitive (e.g. 'Gas-CC', not 'gas-cc') -- check --techs against outputs.h5."
        )
    ## Use the cheapest available resource bin per (i,v,r,t) as the representative site
    lcoe = lcoe.sort_values('rscbin').groupby(['i', 'v', 'r', 't'], as_index=False).first()
    lcoe['i_lower'] = lcoe['i'].str.lower()

    avg_avail = reeds.io.read_output(case, 'avg_avail')  # i, v, r, Value
    fin_mult = reeds.io.read_output(case, 'cost_cap_fin_mult')  # i, r, t, Value
    fin_mult['t'] = fin_mult['t'].astype(int)
    crf = load_crf(case)
    plantchar = load_plantchar(case)
    fprice = load_fuel_price(case)
    cf_vre = load_cf_vre_annual(case)
    rsc_techs = set(cf_vre['i_lower'].unique())

    df = lcoe.merge(
        fin_mult.rename(columns={'Value': 'fin_mult'}), on=['i', 'r', 't'], how='left',
    )
    df = df.merge(
        plantchar.rename(columns={'capcost': 'cost_cap', 'fom': 'cost_fom_raw',
                                   'vom': 'cost_vom', 'heatrate': 'heat_rate'}),
        on=['i_lower', 't'], how='left',
    )
    df['crf'] = df['t'].map(crf)

    ## Baseline capacity factor: resource-profile-driven for RSC techs, avg_avail (an
    ## availability/outage-derate factor) for everything else.
    is_rsc = df['i_lower'].isin(rsc_techs)
    df = df.merge(
        cf_vre.rename(columns={'cf_annual': 'cf_rsc'}), on=['i_lower', 'r'], how='left',
    )
    df = df.merge(
        avg_avail.rename(columns={'Value': 'avail'}), on=['i', 'v', 'r'], how='left',
    )
    df['cf_baseline'] = np.where(is_rsc, df['cf_rsc'], df['avail'])
    assert df['cf_baseline'].notna().all(), 'Missing baseline capacity factor for some (i,r,t) rows'

    ## Fuel price (0 for techs with no fuel, e.g. upv/wind-ons -- heat_rate is 0 there too)
    df['fuel_col'] = df['i_lower'].map(get_fuel_column)
    df['fuel_price'] = 0.0
    for col in df['fuel_col'].dropna().unique():
        mask = df['fuel_col'] == col
        fp = fprice[['t', 'r', col]].rename(columns={col: 'fuel_price_lookup'})
        df.loc[mask, 'fuel_price'] = (
            df.loc[mask, ['t', 'r']].merge(fp, on=['t', 'r'], how='left')['fuel_price_lookup'].values
        )
    df['heat_rate'] = df['heat_rate'].fillna(0.0)
    df['fuel_term'] = df['heat_rate'] * df['fuel_price']

    ## Back out the calibrated FOM(+site-cost) residual K that reproduces the baseline
    ## `lcoe` exactly (see module docstring).
    df['K'] = (
        df['Value'] * df['cf_baseline'] * 8760
        - df['crf'] * df['fin_mult'] * df['cost_cap']
        - (df['cost_vom'] + df['fuel_term']) * df['cf_baseline'] * 8760
    )

    ## Apply user overrides and recompute the scenario LCOE with the same closed form.
    df['capex_mult'] = df['i'].map(lambda i: resolve_mult(i, capex_mult, tech_family))
    df['cf_mult'] = df['i'].map(lambda i: resolve_mult(i, cf_mult, tech_family))
    df['cost_cap_scenario'] = df['cost_cap'] * df['capex_mult']
    df['cf_scenario'] = df['cf_baseline'] * df['cf_mult']
    df['lcoe_scenario'] = (
        (df['crf'] * df['fin_mult'] * df['cost_cap_scenario'] + df['K']) / (df['cf_scenario'] * 8760)
        + df['cost_vom'] + df['fuel_term']
    )
    df = df.rename(columns={'Value': 'lcoe_baseline'})

    return df[[
        'i', 'r', 't', 'lcoe_baseline', 'lcoe_scenario', 'cf_baseline', 'cf_scenario',
        'cost_cap', 'cost_cap_scenario', 'capex_mult', 'cf_mult',
    ]].reset_index(drop=True)


#%% ===========================================================================
### --- PLOTTING ---
### ===========================================================================
def resolve_tech_display(tech_lower, tech_map):
    """
    Look up a raw tech's display name in bokehpivot's tech_map (tech_map.csv), which mixes
    exact keys (e.g. 'battery_li') with trailing-'*' prefix patterns for resource-class-
    suffixed techs (e.g. 'upv*' -> 'UPV', 'wind-ons*' -> 'Onshore Wind') -- a plain dict
    lookup on a class-suffixed name like 'upv_1' never matches those and silently falls
    through to a generic color. Exact match wins; among prefix matches, the longest (most
    specific) prefix wins, e.g. 'coalolduns*' over the more generic 'coal*'.
    """
    if tech_lower in tech_map.index:
        return tech_map[tech_lower]
    best_prefix, best_display = '', None
    for key, display in tech_map.items():
        if key.endswith('*') and tech_lower.startswith(key[:-1]) and len(key) > len(best_prefix):
            best_prefix, best_display = key, display
    return best_display


def shade_colors(base_hex, n):
    """
    Return n distinguishable shades of a base color (lightest to darkest, i.e. lowest to
    highest resource class), for plotting multiple resource classes of the same tech family
    on one panel: individually distinguishable while still reading as one family/color.
    """
    if n == 1:
        return [base_hex]
    base_rgb = np.array(mcolors.to_rgb(base_hex))
    light_rgb = base_rgb + (1 - base_rgb) * 0.7  # 70% of the way toward white
    shades = [tuple(light_rgb + (base_rgb - light_rgb) * frac) for frac in np.linspace(0, 1, n)]
    return [mcolors.to_hex(s) for s in shades]


def _class_sort_key(tech):
    """Natural sort by trailing class number (upv_2 before upv_10), not lexicographic."""
    m = re.match(r'^.+_(\d+)$', tech)
    return int(m.group(1)) if m else 0


def get_tech_style(techs, tech_family):
    """
    Look up one base display name/color per family (e.g. 'upv' -> UPV's gold, 'wind-ons' ->
    Onshore Wind's cyan) via bokehpivot's tech_map/tech_style, then assign each raw tech a
    distinct shade of its family's color (lightest to darkest, by class number) so multiple
    resource classes sharing a panel are individually distinguishable.
    """
    fmt = reeds.io.get_plot_formatting()
    tech_map, tech_color = fmt['tech_map'], fmt['tech_color']['color']
    fallback_colors = plt.rcParams['axes.prop_cycle'].by_key()['color']

    families = list(dict.fromkeys(tech_family[t] for t in techs))
    style = {}
    for n, family in enumerate(families):
        display = resolve_tech_display(family.lower(), tech_map)
        if display is None:
            display = family
        base = tech_color.get(display, fallback_colors[n % len(fallback_colors)])
        members = sorted((t for t in techs if tech_family[t] == family), key=_class_sort_key)
        for tech, color in zip(members, shade_colors(base, len(members))):
            style[tech] = {'display': display, 'family': family, 'color': color}
    return style


def plot_lcoe_sensitivity(df, techs, tech_family, style, savepath, units, has_override):
    """
    One panel per family (e.g. every upv_* class together, every wind-ons_* class together,
    Gas-CC alone) to show the range of LCOE across resource classes. Each line is the
    region-average (unweighted mean across `regions`) baseline (solid) and, if any
    --capex-mult/--cf-mult override was given, scenario (dashed) LCOE by year; per-region
    (e.g. WI_E vs. WI_W) detail is in the CSV but dropped from the plot to keep a multi-class
    panel legible.
    """
    families = list(dict.fromkeys(tech_family[t] for t in techs))
    fig, axes = plt.subplots(1, len(families), figsize=(4.5 * len(families), 4.5), sharey=False)
    axes = np.atleast_1d(axes)

    for ax, family in zip(axes, families):
        members = sorted((t for t in techs if tech_family[t] == family), key=_class_sort_key)
        for tech in members:
            sub = df[df.i == tech]
            avg = sub.groupby('t', as_index=False)[['lcoe_baseline', 'lcoe_scenario']].mean()
            label = tech if len(members) > 1 else style[tech]['display']
            ax.plot(avg['t'], avg['lcoe_baseline'], marker='o', ms=4, lw=1.75,
                     color=style[tech]['color'], label=f'{label} baseline')
            if has_override:
                ax.plot(avg['t'], avg['lcoe_scenario'], marker='o', ms=4, lw=1.75, ls='--',
                         color=style[tech]['color'], label=f'{label} scenario')
        ax.set_ylim(bottom=0)
        ax.set_title(style[members[0]]['display'])
        ax.set_xlabel('Year')
        reedsplots_style.despine(ax)
        ax.legend(frameon=False, fontsize=7, loc='upper left', bbox_to_anchor=(1.02, 1))
    axes[0].set_ylabel(f'LCOE [{units}]')
    plt.tight_layout()
    plt.savefig(os.path.join(savepath, 'lcoe_sensitivity.png'))
    plt.close()


#%% ===========================================================================
### --- MAIN ---
### ===========================================================================
def main():
    args, case = parse_args()
    case = os.path.abspath(case)
    techs_input = [t.strip() for t in args.techs.split(',') if t.strip()]
    capex_mult = parse_mult_overrides(args.capex_mult)
    cf_mult = parse_mult_overrides(args.cf_mult)
    has_override = bool(capex_mult or cf_mult)
    regions = resolve_regions(case, args.region, args.region_level)
    savepath = args.savepath or os.path.join(case, 'outputs', 'plots', 'lcoe_sensitivity')
    os.makedirs(savepath, exist_ok=True)

    reedsplots_style.plotparams()

    ## techs/tech_family expand any --techs entry with no exact match (e.g. 'upv') into every
    ## resource class with lcoe data in the region, and record which panel/family each raw
    ## tech is plotted under (see expand_tech_families/get_tech_family).
    techs, tech_family = expand_tech_families(case, techs_input, regions)
    style = get_tech_style(techs, tech_family)

    df = compute_lcoe_sensitivity(case, techs, tech_family, regions, capex_mult, cf_mult, args.first_year)
    for col in ['lcoe_baseline', 'lcoe_scenario']:
        df[col] = reeds.results.inflate_series(df[col], to_dollar_year=args.dollar_year)

    df.to_csv(os.path.join(savepath, 'lcoe_sensitivity.csv'), index=False)
    print(f'Wrote {os.path.join(savepath, "lcoe_sensitivity.csv")}')

    plot_lcoe_sensitivity(
        df, techs, tech_family, style, savepath, units=f'{args.dollar_year}$/MWh', has_override=has_override,
    )
    print(f'Wrote {os.path.join(savepath, "lcoe_sensitivity.png")}')


if __name__ == '__main__':
    main()
