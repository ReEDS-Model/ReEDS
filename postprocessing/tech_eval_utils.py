"""
Shared helpers for the technology-evaluation postprocessing scripts: compare_tech_value.py,
stress_period_plots.py, lcoe_sensitivity.py, lcoe_range.py, and region_stack.py.

Covers what those scripts have in common: --case/--region argument handling, region
resolution through hierarchy.csv, resource-class expansion, tech display names and colors,
and the reconstruction of ReEDS's own reported LCOE.

LCOE reconstruction
-------------------
report.gms computes LCOE with the closed form (both the non-resource-constrained branch,
e.g. Gas-CC, and the resource-supply-curve branch, e.g. upv/wind-ons):

    lcoe = (crf * cost_cap_fin_mult * cost_cap + K) / (cf * 8760) + cost_vom + heat_rate * fuel_price

where cf is `avg_avail(i,v,r)` for non-RSC techs or the resource-profile-driven annual
capacity factor for RSC techs, and K is fixed O&M plus, for RSC techs, a resource-site
interconnection cost baked into the same numerator.

`cost_fom`/`cost_vom`/`heat_rate` are in general a vintage-cohort average over several
years (see b_inputs.gms), which cannot be reproduced exactly from the single-year
plantcharout.csv values, and the RSC branch's site-cost adder is a GAMS-internal sum over
feasible sites. Rather than approximate those, `calibrate_lcoe` backs out K as the residual
that reproduces the run's own reported `lcoe` exactly, so callers can rescale capital cost,
capacity factor, or fuel price against a baseline that matches ReEDS by construction.
"""
import os
import re
import sys
import textwrap

import matplotlib.colors as mcolors
import numpy as np
import pandas as pd

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds


HOURS_PER_YEAR = 8760

## Fuel consumed by each tech-name prefix, keyed to the column names in inputs_case/fprice.csv
FUEL_COLUMN_BY_PREFIX = {
    'gas': 'naturalgas',
    'h2-cc': 'naturalgas',
    'h2-ct': 'naturalgas',
    'coal': 'coal',
    'nuclear': 'uranium',
}


#%% ===========================================================================
### --- ARGUMENTS ---
### ===========================================================================
def add_case_arg(parser):
    """Accept the case path either positionally or as --case/-c, matching single_case_plots.py."""
    parser.add_argument('case_positional', type=str, nargs='?', help='path to ReEDS run folder')
    parser.add_argument('--case', '-c', type=str, help='path to ReEDS run folder')


def resolve_case(args):
    """Return the absolute case path from the arguments added by add_case_arg."""
    if args.case_positional and args.case:
        raise ValueError('Provide case as positional argument or --case/-c, not both')
    case = args.case_positional or args.case
    if not case:
        raise ValueError('Provide case path either as positional argument or as --case/-c')
    return os.path.abspath(case)


def add_region_args(parser, name='region', level_name=None, required=False, extra_help=''):
    """
    Add a --{name}/--{level_name} pair for selecting one BA or an aggregate of BAs. The names
    are configurable so a script can add more than one pair (e.g. --region and
    --dispatch-region).
    """
    level_name = level_name or f'{name}-level'
    help_text = (
        f'region to restrict to: a literal BA (e.g. CA_LA), or a value within --{level_name} '
        f'(e.g. WI with --{level_name} st) to aggregate every BA mapped to it'
    )
    if not required:
        help_text += '; default is all regions'
    parser.add_argument(
        f'--{name}', type=str, default=None, required=required,
        help=f'{help_text}. {extra_help}'.strip(),
    )
    parser.add_argument(
        f'--{level_name}', type=str, default='r',
        help=(
            f'hierarchy.csv column that --{name} is a value of, e.g. st, transreg, '
            'interconnect, nercr; "r" treats it as a literal BA code'
        ),
    )


def resolve_regions(case, region, level='r'):
    """
    Resolve a --region/--region-level pair into the list of BAs (r) to aggregate, or None if
    `region` is unset. level='r' treats `region` as a literal BA code; any other level is a
    column of inputs_case/hierarchy.csv. Both are matched case-insensitively.
    """
    if region is None:
        return None
    hierarchy = reeds.io.get_hierarchy(case)
    if level == 'r':
        matches = [r for r in hierarchy.index if r.lower() == region.lower()]
        if not matches:
            raise ValueError(
                f"'{region}' is not a BA in this case. Set the matching region-level argument "
                'to treat it as a value of a hierarchy.csv column instead, e.g. st.'
            )
        return matches
    if level not in hierarchy.columns:
        raise ValueError(f"'{level}' is not a column of hierarchy.csv; got {list(hierarchy.columns)}")
    regions = hierarchy.loc[hierarchy[level].str.lower() == region.lower()].index.tolist()
    if not regions:
        raise ValueError(f"No regions found with {level}='{region}' in hierarchy.csv")
    return regions


def parse_techs(techs):
    """Split a comma-separated --techs string into a list of tech names."""
    return [t.strip() for t in techs.split(',') if t.strip()]


def wrap_label(text, width=28):
    """Wrap a long axis label onto multiple lines so it doesn't run off the figure."""
    return '\n'.join(textwrap.wrap(text, width=width))


#%% ===========================================================================
### --- TECH NAMES AND STYLING ---
### ===========================================================================
def get_tech_family(tech):
    """Strip a trailing resource-class suffix ('upv_1' -> 'upv'); a tech without one is its
    own family."""
    match = re.match(r'^(.+)_\d+$', tech)
    return match.group(1) if match else tech


def class_sort_key(tech):
    """Sort key by trailing resource-class number, so upv_2 comes before upv_10."""
    match = re.match(r'^.+_(\d+)$', tech)
    return int(match.group(1)) if match else 0


def expand_tech_classes(case, techs, output='cap', regions=None):
    """
    Expand any tech name with no exact match among `output`'s `i` values into every matching
    '{name}_*' resource class present in the case (e.g. 'upv' -> upv_1, upv_2, ...). Pass
    output='cap' to count only classes actually built, or output='lcoe' for every class
    available to build.

    Returns (techs_raw, tech_group_map), where tech_group_map maps each raw i back to the
    name it was expanded from (itself, for a name that already matched exactly). Only use
    the grouping for metrics built by summing an additive numerator before dividing.
    """
    df = reeds.io.read_output(case, output)
    if regions is not None:
        df = df[df.r.isin(regions)]
    all_i = set(df['i'].unique())

    tech_group_map = {}
    for tech in techs:
        if tech in all_i:
            tech_group_map[tech] = tech
            continue
        prefix = tech.lower() + '_'
        matches = sorted((i for i in all_i if i.lower().startswith(prefix)), key=class_sort_key)
        if not matches:
            raise ValueError(
                f"'{tech}' has no exact match and no '{tech}_*' resource classes in this case's "
                f"'{output}' output. Tech names are case-sensitive (e.g. 'Gas-CC', not 'gas-cc') "
                "-- check --techs against outputs.h5."
            )
        for match in matches:
            tech_group_map[match] = tech
    return list(tech_group_map.keys()), tech_group_map


def resolve_tech_display(tech_lower, tech_map):
    """
    Display name for a raw tech from bokehpivot's tech_map.csv, which mixes exact keys
    ('battery_li') with trailing-'*' prefix patterns ('upv*' -> 'UPV'). A plain dict lookup
    on a class-suffixed name never matches the latter. Exact match wins, then the longest
    matching prefix ('coalolduns*' over 'coal*'). Returns None if nothing matches.
    """
    if tech_lower in tech_map.index:
        return tech_map[tech_lower]
    best_prefix, best_display = '', None
    for key, display in tech_map.items():
        if key.endswith('*') and tech_lower.startswith(key[:-1]) and len(key) > len(best_prefix):
            best_prefix, best_display = key, display
    return best_display


def get_family_color(family, tech_map, tech_color, fallback='#666666'):
    """Return (color, display name) for a tech or tech family."""
    display = resolve_tech_display(family.lower(), tech_map) or family
    return tech_color.get(display, fallback), display


def shade_colors(base_hex, n, lighten=0.7):
    """
    n shades of `base_hex`, lightest to darkest, so resource classes of one family stay
    individually distinguishable while reading as one color. `lighten` sets how far the
    lightest shade sits toward white; 0.7 suits a filled band, ~0.35 a line against white.
    """
    if n == 1:
        return [base_hex]
    base_rgb = np.array(mcolors.to_rgb(base_hex))
    light_rgb = base_rgb + (1 - base_rgb) * lighten
    shades = [tuple(light_rgb + (base_rgb - light_rgb) * frac) for frac in np.linspace(0, 1, n)]
    return [mcolors.to_hex(s) for s in shades]


#%% ===========================================================================
### --- LCOE RECONSTRUCTION ---
### ===========================================================================
def get_fuel_column(tech_lower):
    """fprice.csv column for a tech, or None if it burns no fuel."""
    for prefix, col in FUEL_COLUMN_BY_PREFIX.items():
        if tech_lower.startswith(prefix):
            return col
    return None


def load_plantchar(case):
    """
    inputs_case/plantcharout.csv as a wide (i_lower, t) -> {capcost, fom, vom, heatrate, ...}
    frame. `i` casing differs between input and output files ('UPV_1' vs 'upv_1'), so match
    on lowercase throughout.
    """
    pc = pd.read_csv(os.path.join(case, 'inputs_case', 'plantcharout.csv')).rename(columns={'*i': 'i'})
    pc['i_lower'] = pc['i'].str.lower()
    wide = pc.pivot_table(index=['i_lower', 't'], columns='variable', values='value', aggfunc='first')
    return wide.reset_index()


def load_crf(case):
    """Capital recovery factor by year."""
    fin = pd.read_csv(os.path.join(case, 'inputs_case', 'financials_sys_full.csv'))
    return fin.set_index('t')['crf']


def load_fuel_price(case):
    """inputs_case/fprice.csv: $/MMBtu by (t, r) with one column per fuel."""
    return pd.read_csv(os.path.join(case, 'inputs_case', 'fprice.csv'))


def load_cf_vre_annual(case):
    """Numhours-weighted annual average capacity factor per (i_lower, r) from the resource
    profiles, approximating report.gms's gen_rsc/8760 for supply-curve techs."""
    cf = pd.read_csv(os.path.join(case, 'inputs_case', 'rep', 'cf_vre.csv')).rename(columns={'*i': 'i'})
    numhours = pd.read_csv(
        os.path.join(case, 'inputs_case', 'rep', 'numhours.csv')).rename(columns={'*h': 'h'})
    cf = cf.merge(numhours, on='h', how='left')
    cf['i_lower'] = cf['i'].str.lower()

    def weighted_cf(group):
        return np.average(group['cf'], weights=group['numhours'])

    ## include_groups=False is omitted for compatibility with pandas < 2.2
    return cf.groupby(['i_lower', 'r']).apply(weighted_cf).rename('cf_annual').reset_index()


def get_deflator(dollar_year):
    """2004$ per `dollar_year`$, i.e. the inverse of reeds.results.inflate_series."""
    deflator = pd.read_csv(
        os.path.join(reeds.io.reeds_path, 'inputs', 'financials', 'deflator.csv'), index_col=0)
    return deflator.loc[dollar_year, 'Deflator']


def lcoe_from_parts(crf, fin_mult, cost_cap, fixed_cost, cf, cost_vom, fuel_term):
    """report.gms's LCOE closed form, in the run's native 2004$/MWh."""
    return (crf * fin_mult * cost_cap + fixed_cost) / (cf * HOURS_PER_YEAR) + cost_vom + fuel_term


def calibrate_lcoe(case, techs, regions=None, first_year=None, last_year=None):
    """
    Assemble the inputs behind ReEDS's own reported `lcoe` and back out the calibrated fixed
    cost K that makes lcoe_from_parts reproduce it exactly (see module docstring), so callers
    can rescale capital cost, capacity factor, or fuel price against an exact baseline.

    Returns a tidy (i, v, r, t) frame with lcoe_baseline, K, and every term of the closed
    form. Capacity factor is the resource-profile annual average for techs with resource
    profiles and `avg_avail` (an availability derate, as report.gms uses) for the rest.
    """
    lcoe = reeds.io.read_output(case, 'lcoe')
    lcoe['t'] = lcoe['t'].astype(int)
    lcoe = lcoe[lcoe.i.isin(techs)].copy()
    if regions is not None:
        lcoe = lcoe[lcoe.r.isin(regions)]
    if first_year is not None:
        lcoe = lcoe[lcoe.t >= first_year]
    if last_year is not None:
        lcoe = lcoe[lcoe.t <= last_year]
    missing = [t for t in techs if t not in lcoe.i.unique()]
    if missing:
        raise ValueError(
            f"No 'lcoe' rows found for {missing} in the requested region(s) and years. Tech "
            "names are case-sensitive (e.g. 'Gas-CC', not 'gas-cc') -- check against outputs.h5."
        )
    ## Take the cheapest available resource bin per (i,v,r,t) as the representative site
    lcoe = lcoe.sort_values('rscbin').groupby(['i', 'v', 'r', 't'], as_index=False).first()
    lcoe['i_lower'] = lcoe['i'].str.lower()

    fin_mult = reeds.io.read_output(case, 'cost_cap_fin_mult')
    fin_mult['t'] = fin_mult['t'].astype(int)
    cf_vre = load_cf_vre_annual(case)
    plantchar = load_plantchar(case)

    df = lcoe.merge(fin_mult.rename(columns={'Value': 'fin_mult'}), on=['i', 'r', 't'], how='left')
    df = df.merge(
        plantchar.rename(columns={'capcost': 'cost_cap', 'vom': 'cost_vom', 'heatrate': 'heat_rate'}),
        on=['i_lower', 't'], how='left',
    )
    df = df.merge(
        reeds.io.read_output(case, 'avg_avail').rename(columns={'Value': 'avail'}),
        on=['i', 'v', 'r'], how='left',
    )
    df = df.merge(cf_vre.rename(columns={'cf_annual': 'cf_rsc'}), on=['i_lower', 'r'], how='left')
    df['crf'] = df['t'].map(load_crf(case))
    df['cf_baseline'] = np.where(df['i_lower'].isin(set(cf_vre['i_lower'])), df['cf_rsc'], df['avail'])
    if df['cf_baseline'].isna().any():
        bad = df.loc[df['cf_baseline'].isna(), ['i', 'r', 't']].drop_duplicates().head()
        raise ValueError(f'Missing baseline capacity factor; first few (i, r, t):\n{bad}')

    ## Techs with no fuel (upv, wind-ons, ...) have a 0 heat rate, so the fuel term drops out
    fprice = load_fuel_price(case)
    df['fuel_col'] = df['i_lower'].map(get_fuel_column)
    df['fuel_price'] = 0.0
    for col in df['fuel_col'].dropna().unique():
        mask = df['fuel_col'] == col
        lookup = fprice[['t', 'r', col]].rename(columns={col: 'price'})
        df.loc[mask, 'fuel_price'] = (
            df.loc[mask, ['t', 'r']].merge(lookup, on=['t', 'r'], how='left')['price'].values
        )
    df['heat_rate'] = df['heat_rate'].fillna(0.0)
    df['fuel_term'] = df['heat_rate'] * df['fuel_price']

    df = df.rename(columns={'Value': 'lcoe_baseline'})
    df['K'] = (
        (df['lcoe_baseline'] - df['cost_vom'] - df['fuel_term']) * df['cf_baseline'] * HOURS_PER_YEAR
        - df['crf'] * df['fin_mult'] * df['cost_cap']
    )
    return df[[
        'i', 'v', 'r', 't', 'lcoe_baseline', 'K', 'crf', 'fin_mult', 'cost_cap',
        'cf_baseline', 'cost_vom', 'heat_rate', 'fuel_price', 'fuel_term',
    ]].reset_index(drop=True)
