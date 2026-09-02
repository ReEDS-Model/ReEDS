"""
Compare the value, cost, and firmness of new-build capacity for two or more ReEDS
technologies (default: battery_li vs Gas-CT), read from {case}/outputs/outputs.h5.

Methodology
-----------
Value comes from ReEDS's own `valnew` output, which reports what capacity newly built in
each solve year earns, split into an energy stream (`val_load`) and a firm-capacity stream
(`val_resmarg`). Two storage-specific accounting quirks are handled explicitly:

- `val_load` for storage is already net of charging cost, while for a thermal tech it is
  gross and fuel cost sits on the cost side. To put the two on the same basis, storage's
  energy value is grossed up by adding charging cost back, and that charging cost is booked
  as an explicit cost line -- the storage analogue of fuel cost. Net value is unchanged.
- Annual discharge (`valnew`'s MWh, `gen_ivrt`) is gross for storage while `gen_ann` is net
  of charging and can go negative, so every $/MWh figure here uses the gross basis.

Cost is reconstructed from `lcoe_built` (the model's own annualized $/MWh for the new-build
cohort) and `lcoe_pieces` (unannualized FOM/VOM/fuel over the same cohort and denominator).
Capital cost is taken as the residual `lcoe_built * gen - fomcost - vomcost`, which keeps
the split exact by construction rather than reconstructing the capital recovery factor.

`firm_capacity_contribution` and `storage_duration` describe how firm each tech's capacity
actually is. Both are shown as a national/fleet-wide line and as a per-region box plot,
since a single average can hide a lot of regional variation. `--include-wind` adds
land-based and offshore wind to a separate copy of the firm-capacity figure.

Use stress_period_plots.py to see the stress-period prices and dispatch behind these
firm-capacity numbers.

Usage
-----
    python compare_tech_value.py <path-to-case>
    python compare_tech_value.py <path-to-case> --techs battery_li,Gas-CT --include-wind
    python compare_tech_value.py <path-to-case> --techs upv,Gas-CC --region WI --region-level st

Run with --help for the full list of options.

Outputs
-------
Written to {case}/outputs/plots/tech_value/ by default (tech_value_{region} with --region):
- tech_value_comparison.csv, tech_value_by_region.csv -- tidy value, cost, firm-capacity and
  storage-duration data, national and by region
- value_cost_stack_kwyr.png, value_cost_stack_mwh.png -- value/cost/net-value decomposition
- value_factor.png -- value factor against the system-average benchmark
- firm_capacity_contribution.png (+ _boxplot, + _with_wind if requested)
- storage_duration.png (+ _boxplot)
- reduced_cost.png -- the model's own marginal-competitiveness signal
"""
import argparse
import os
import sys
import warnings

import matplotlib
## This script only calls savefig(); an interactive backend can crash without a display
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import lines as mlines
from matplotlib import patches as mpatches
import numpy as np
import pandas as pd

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds
from reeds import plots
import tech_eval_utils as teu


#%% ===========================================================================
### --- ARGUMENTS ---
### ===========================================================================
def parse_args():
    parser = argparse.ArgumentParser(
        description='Compare the value and cost of new-build capacity for two ReEDS technologies.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    teu.add_case_arg(parser)
    parser.add_argument(
        '--savepath', type=str, default=None,
        help='output directory (default: {case}/outputs/plots/tech_value)',
    )
    parser.add_argument(
        '--techs', type=str, default='battery_li,Gas-CT',
        help=(
            'comma-separated technology names, exactly as they appear in outputs.h5 '
            '(case-sensitive -- e.g. "Gas-CT", not "gas-ct"). A name with no exact match is '
            'summed across every matching "{name}_*" resource class (e.g. "upv" -> upv_1, '
            'upv_2, ...) for the firm-capacity and storage-duration figures; the value/cost, '
            'value-factor and reduced-cost figures need exact names and skip it with a '
            'warning, since $/MWh figures cannot be summed across classes'
        ),
    )
    parser.add_argument('--dollar-year', type=int, default=2024, help='dollar year to inflate $ values to')
    parser.add_argument(
        '--first-year', type=int, default=2026,
        help=(
            'first endogenous solve year; earlier solve years are fixed to historical data '
            'rather than optimized, so they are excluded from the CSVs and figures entirely'
        ),
    )
    parser.add_argument(
        '--plot-first-year', type=int, default=2029,
        help=(
            'first year shown in the figures; the default skips --first-year itself, whose '
            'transitional value/cost results dominate the y-axis scale. The CSVs still cover '
            'every year from --first-year onward'
        ),
    )
    parser.add_argument(
        '--include-wind', action='store_true',
        help=(
            'also write firm_capacity_contribution_with_wind.png, adding land-based and '
            'offshore wind (each summed across all its resource classes) as two extra lines'
        ),
    )
    teu.add_region_args(parser)

    args = parser.parse_args()
    return args, teu.resolve_case(args)


#%% ===========================================================================
### --- DATA LOADING ---
### ===========================================================================
def load_valnew(case, techs, dollar_year, tech_group_map=None, regions=None):
    """
    Load and inflate `valnew`, returning a wide (i, r, t) frame with one column per `output`
    (MW, MWh, val_load, val_resmarg, ...), including the 'benchmark' rows.

    A tech with no exact match in `valnew` is dropped with a warning rather than raising.
    `regions`, if given, restricts to those BAs; the system-wide benchmark rows (r == 'sys')
    are always kept, since they are the value-factor denominator. `tech_group_map`, if given,
    relabels and sums by group, which is safe for the additive columns.
    """
    vn = reeds.io.read_output(case, 'valnew').rename(columns={'*': 'output', '*.1': 'i', '*.2': 'r'})
    vn['t'] = vn['t'].astype(int)
    ## Only the 'val_*' rows are dollar amounts; MW/MWh/inv_cap_ratio are not
    is_dollars = vn['output'].str.startswith('val_')
    vn.loc[is_dollars, 'Value'] = reeds.results.inflate_series(
        vn.loc[is_dollars, 'Value'], to_dollar_year=dollar_year)

    keep = vn[vn['i'].isin(techs + ['benchmark'])].copy()
    if regions is not None:
        keep = keep[(keep['r'] == 'sys') | (keep['r'].isin(regions))]
    missing = [t for t in techs if t not in keep.loc[keep.i != 'benchmark', 'i'].unique()]
    if missing:
        warnings.warn(
            f"No 'valnew' rows found for {missing} (in the requested region(s), if any) -- "
            "skipping them for the value/cost-stack, value-factor, and reduced-cost plots. "
            "Tech names in outputs.h5 are case-sensitive (e.g. 'Gas-CT', not 'gas-ct')."
        )
    if tech_group_map:
        is_benchmark = keep['i'] == 'benchmark'
        keep.loc[~is_benchmark, 'i'] = keep.loc[~is_benchmark, 'i'].map(
            lambda x: tech_group_map.get(x, x))

    wide = keep.pivot_table(index=['i', 'r', 't'], columns='output', values='Value', aggfunc='sum')
    return wide.reset_index()


def load_new_build_cost(case, techs, dollar_year, tech_group_map=None, regions=None):
    """
    Annualized cost of new-build capacity (capex, FOM, VOM+fuel) per (i, r, t), reconstructed
    from `lcoe_built` and `lcoe_pieces`. Both share the same new-build-cohort denominator, so

        annualized_capex = lcoe_built * lcoe_pieces['gen'] - fomcost - vomcost

    is exact by construction. `vomcost` already includes fuel cost for combustion techs.

    `lcoe_built` is only reported for capacity from `INV`, not `INV_REFURB`, while `valnew`
    covers both, so a (tech, region, year) whose only addition is a refurbishment shows value
    with no cost here. run_diagnostics reports which years those are.

    `tech_group_map`, if given, is applied only after the $ amounts are computed at raw-tech
    granularity, since `lcoe_built` is a ratio and is not summable across resource classes.
    """
    lp = reeds.io.read_output(case, 'lcoe_pieces')
    lp = lp[lp.i.isin(techs)]
    if regions is not None:
        lp = lp[lp.r.isin(regions)]
    lp = lp.pivot_table(index=['i', 'r', 't'], columns='lcoe_cat', values='Value', aggfunc='sum')
    for col in ['fomcost', 'vomcost', 'gen']:
        if col not in lp:
            lp[col] = 0.0
    lp = lp.fillna(0.0).reset_index()

    lb = reeds.io.read_output(case, 'lcoe_built', valname='lcoe_built')
    lb = lb[lb.i.isin(techs)]
    if regions is not None:
        lb = lb[lb.r.isin(regions)]

    cost = lp.merge(lb, on=['i', 'r', 't'], how='left')
    cost['t'] = cost['t'].astype(int)
    ## lcoe_built's capital term already covers capcost, upgradecost and rsccost, so this
    ## residual is their combined annualized total
    cost['annualized_capex'] = cost['lcoe_built'] * cost['gen'] - cost['fomcost'] - cost['vomcost']
    if tech_group_map:
        cost['i'] = cost['i'].map(lambda x: tech_group_map.get(x, x))
        cost = cost.groupby(['i', 'r', 't'], as_index=False)[['annualized_capex', 'fomcost', 'vomcost']].sum()
    for col in ['annualized_capex', 'fomcost', 'vomcost']:
        cost[col] = reeds.results.inflate_series(cost[col], to_dollar_year=dollar_year)
    return cost[['i', 'r', 't', 'annualized_capex', 'fomcost', 'vomcost']]


def load_charge_cost(case, techs, dollar_year, vn_wide, tech_group_map=None, regions=None):
    """
    Annual charging cost of the new-build cohort, mirroring how GAMS computes val_load for
    storage: sum_h(STORAGE_IN * hours * load price) over the vintages actually invested in
    that (i, r, t), scaled by inv_cap_ratio. Empty for a tech with no `stor_in` rows.
    """
    stor_in = reeds.io.read_output(case, 'stor_in')
    stor_in = stor_in[stor_in.i.isin(techs)]
    if regions is not None:
        stor_in = stor_in[stor_in.r.isin(regions)]
    if stor_in.empty:
        return pd.DataFrame(columns=['i', 'r', 't', 'charge_cost'])

    cap_new = reeds.io.read_output(case, 'cap_new_ivrt')
    newv = cap_new[(cap_new.i.isin(techs)) & (cap_new.Value > 0)][['i', 'v', 'r', 't']].drop_duplicates()

    hours = reeds.io.read_output(case, 'hours').rename(columns={'Value': 'hours'})
    reqt_price = reeds.io.read_output(case, 'reqt_price').rename(
        columns={'*': 'reqt', '*.1': 'subcat', '*.2': 'h', 'Value': 'price'})
    load_price = reqt_price[(reqt_price.reqt == 'load') & (reqt_price.subcat == 'na')][['r', 'h', 't', 'price']]

    si = stor_in.merge(newv, on=['i', 'v', 'r', 't'], how='inner')
    si = si.merge(hours, on='h', how='left').merge(load_price, on=['r', 'h', 't'], how='inner')
    si['charge_cost_raw'] = si.Value * si.hours * si.price
    if tech_group_map:
        si['i'] = si['i'].map(lambda x: tech_group_map.get(x, x))
    cc = si.groupby(['i', 'r', 't'], as_index=False)['charge_cost_raw'].sum()
    cc['t'] = cc['t'].astype(int)

    if 'inv_cap_ratio' in vn_wide:
        cc = cc.merge(vn_wide[['i', 'r', 't', 'inv_cap_ratio']], on=['i', 'r', 't'], how='left')
        cc['charge_cost'] = cc['charge_cost_raw'] * cc['inv_cap_ratio'].fillna(0)
    else:
        cc['charge_cost'] = cc['charge_cost_raw']
    cc['charge_cost'] = reeds.results.inflate_series(cc['charge_cost'], to_dollar_year=dollar_year)
    return cc[['i', 'r', 't', 'charge_cost']]


def load_reduced_cost(case, techs, dollar_year, tech_group_map=None, regions=None):
    """Average reduced cost ($/kW) on the INV variable, by tech and year."""
    rc = reeds.io.read_output(case, 'reduced_cost').rename(columns={'*': 'bin', '*.1': 'var'})
    ## rc['var'], not rc.var -- the latter resolves to DataFrame.var (variance)
    rc = rc[(rc['var'] == 'INV') & (rc.i.isin(techs))].copy()
    if regions is not None:
        rc = rc[rc.r.isin(regions)]
    rc['t'] = rc['t'].astype(int)
    rc['Value'] = reeds.results.inflate_series(rc['Value'], to_dollar_year=dollar_year)
    if tech_group_map:
        rc['i'] = rc['i'].map(lambda x: tech_group_map.get(x, x))
    return rc.groupby(['i', 't'], as_index=False)['Value'].mean().rename(columns={'Value': 'reduced_cost'})


def compute_firm_capacity_contribution(case, techs, tech_group_map=None, regions=None):
    """
    Price-weighted firm capacity contribution: stress-period generation over total capacity,
    weighted by each stress period's reserve-margin price --

        sum_h(gen_h_stress(i,r,h,t) * price(r,h,t)) / (cap(i,r,t) * sum_h(price(r,h,t)))

    The numerator is `revenue`'s 'res_marg' category, which GAMS computes as exactly that sum
    when GSw_PRM_CapCredit=0. Only meaningful for a run with GSw_PRM_CapCredit=0.

    Returns (df, nat): df is per (i, r, t); nat aggregates to (i, t) by summing numerator and
    denominator across regions first, never by averaging regional ratios. `tech_group_map`
    aggregates across resource classes the same way.
    """
    def group(series):
        return series.map(lambda x: tech_group_map.get(x, x)) if tech_group_map else series

    rev = reeds.io.read_output(case, 'revenue')
    rev = rev[(rev.rev_cat == 'res_marg') & (rev.i.isin(techs))][['i', 'r', 't', 'Value']].copy()
    if regions is not None:
        rev = rev[rev.r.isin(regions)]
    rev['i'] = group(rev['i'])
    rev = rev.groupby(['i', 'r', 't'], as_index=False)['Value'].sum().rename(columns={'Value': 'gen_price_weighted'})

    reqt_price = reeds.io.read_output(case, 'reqt_price').rename(
        columns={'*': 'reqt', '*.1': 'subcat', '*.2': 'h', 'Value': 'price'})
    price_sum = reqt_price[(reqt_price.reqt == 'res_marg') & (reqt_price.subcat == 'na')]
    if regions is not None:
        price_sum = price_sum[price_sum.r.isin(regions)]
    price_sum = (
        price_sum.groupby(['r', 't'], as_index=False)['price'].sum()
        .rename(columns={'price': 'price_sum'})
    )

    cap = reeds.io.read_output(case, 'cap')
    cap = cap[cap.i.isin(techs)][['i', 'r', 't', 'Value']].copy()
    if regions is not None:
        cap = cap[cap.r.isin(regions)]
    cap['i'] = group(cap['i'])
    cap = cap.groupby(['i', 'r', 't'], as_index=False)['Value'].sum().rename(columns={'Value': 'cap'})
    cap['t'] = cap['t'].astype(int)

    df = cap.merge(price_sum, on=['r', 't'], how='left').merge(rev, on=['i', 'r', 't'], how='left')
    df['gen_price_weighted'] = df['gen_price_weighted'].fillna(0.0)
    df['price_sum'] = df['price_sum'].fillna(0.0)
    df['denom'] = df['cap'] * df['price_sum']
    df['firm_capacity_contribution'] = df['gen_price_weighted'] / df['denom']

    nat = df.groupby(['i', 't'], as_index=False)[['gen_price_weighted', 'denom']].sum()
    nat['firm_capacity_contribution'] = nat['gen_price_weighted'] / nat['denom']
    return df[['i', 'r', 't', 'firm_capacity_contribution']], nat[['i', 't', 'firm_capacity_contribution']]


def compute_storage_duration(case, techs, tech_group_map=None, regions=None):
    """
    Capacity-weighted average storage duration (hours) by tech and year, from GAMS's own
    `storage_duration_out` weighted by `cap_ivrt`, summing across vintages and regions before
    dividing. `storage_duration_out` only exists for battery techs, so other techs are absent
    from the result.

    Returns (df_region, nat): df_region is weighted across vintages within each (i, r, t);
    nat additionally weights across regions.
    """
    dur = reeds.io.read_output(case, 'storage_duration_out')
    dur = dur[dur.i.isin(techs)].rename(columns={'Value': 'duration'})
    if regions is not None:
        dur = dur[dur.r.isin(regions)]

    cap = reeds.io.read_output(case, 'cap_ivrt')
    cap = cap[cap.i.isin(techs)].rename(columns={'Value': 'cap'})
    if regions is not None:
        cap = cap[cap.r.isin(regions)]

    df = dur.merge(cap, on=['i', 'v', 'r', 't'], how='left')
    df['weighted'] = df['duration'] * df['cap']
    df['t'] = df['t'].astype(int)
    ## Relabel only after the merge, so two classes' identically-named vintage bins can't collide
    if tech_group_map:
        df['i'] = df['i'].map(lambda x: tech_group_map.get(x, x))

    df_region = df.groupby(['i', 'r', 't'], as_index=False)[['weighted', 'cap']].sum()
    df_region['storage_duration'] = df_region['weighted'] / df_region['cap']

    nat = df.groupby(['i', 't'], as_index=False)[['weighted', 'cap']].sum()
    nat['storage_duration'] = nat['weighted'] / nat['cap']

    return df_region[['i', 'r', 't', 'storage_duration']], nat[['i', 't', 'storage_duration']]


#%% ===========================================================================
### --- METRIC CONSTRUCTION ---
### ===========================================================================
def assemble_value_cost(case, techs, dollar_year, tech_group_map=None, regions=None):
    """Combine value and cost into a single tidy (i, r, t) frame with net-value columns."""
    groups = sorted(set(tech_group_map.values())) if tech_group_map else techs
    vn = load_valnew(case, techs, dollar_year, tech_group_map=tech_group_map, regions=regions)
    cost = load_new_build_cost(case, techs, dollar_year, tech_group_map=tech_group_map, regions=regions)
    charge = load_charge_cost(case, techs, dollar_year, vn, tech_group_map=tech_group_map, regions=regions)

    df = vn[vn.i.isin(groups)].merge(cost, on=['i', 'r', 't'], how='left')
    df = df.merge(charge, on=['i', 'r', 't'], how='left')
    for col in ['annualized_capex', 'fomcost', 'vomcost', 'charge_cost']:
        df[col] = df[col].fillna(0.0)
    for col in ['val_load', 'val_resmarg']:
        if col not in df:
            df[col] = 0.0
        df[col] = df[col].fillna(0.0)

    ## Gross up storage's energy value by the charging cost val_load already netted out, then
    ## book that same charging cost as an explicit cost line; net value is unaffected
    df['gross_energy_value'] = df['val_load'] + df['charge_cost']
    df['firm_capacity_value'] = df['val_resmarg']
    df['total_value'] = df['gross_energy_value'] + df['firm_capacity_value']
    df['total_cost'] = df['annualized_capex'] + df['fomcost'] + df['vomcost'] + df['charge_cost']
    df['net_value'] = df['total_value'] - df['total_cost']
    return df, vn


def compute_value_factors(vn_wide, techs):
    """
    Value factor and its temporal/spatial/interaction decomposition, ported from
    postprocessing/bokehpivot/reeds2.py::pre_valnew, computed at (i, r, t) and aggregated to
    (i, t) with an MWh-weighted mean to match bokehpivot's y_agg convention for these charts.
    """
    val_cols = [c for c in ['val_load', 'val_resmarg'] if c in vn_wide]
    val_cols_sys = [c for c in ['val_load_sys', 'val_resmarg_sys'] if c in vn_wide]

    bench = vn_wide[vn_wide.i == 'benchmark']
    bench_loc = bench[bench.r != 'sys'].set_index(['r', 't'])
    bench_sys = bench[bench.r == 'sys'].set_index('t')

    keep_cols = ['MW', 'MWh'] + val_cols
    df = vn_wide[vn_wide.i.isin(techs)].copy()
    df['val_tot'] = df[val_cols].sum(axis=1)
    df['val_tot_sys'] = df[val_cols_sys].sum(axis=1) if val_cols_sys else 0.0

    df = df.merge(bench_loc[keep_cols].add_suffix('_bl'), left_on=['r', 't'], right_index=True, how='left')
    df = df.merge(bench_sys[keep_cols].add_suffix('_bs'), left_on='t', right_index=True, how='left')
    df['val_tot_bl'] = df[[f'{c}_bl' for c in val_cols]].sum(axis=1)
    df['val_tot_bs'] = df[[f'{c}_bs' for c in val_cols]].sum(axis=1)

    with np.errstate(divide='ignore', invalid='ignore'):
        df['vf'] = (df['val_tot'] / df['MWh']) / (df['val_tot_bs'] / df['MWh_bs'])
        df['vf_temporal'] = (df['val_tot_sys'] / df['MWh']) / (df['val_tot_bs'] / df['MWh_bs'])
        df['vf_spatial'] = (df['val_tot_bl'] / df['MWh_bl']) / (df['val_tot_bs'] / df['MWh_bs'])
        df['vf_temporal_local'] = (df['val_tot'] / df['MWh']) / (df['val_tot_bl'] / df['MWh_bl'])
        df['vf_spatial_simult'] = df['val_tot'] / df['val_tot_sys']
        df['vf_interaction'] = df['vf_spatial_simult'] / df['vf_spatial']
    df = df.replace([np.inf, -np.inf], np.nan)

    vf_cols = ['vf', 'vf_temporal', 'vf_spatial', 'vf_temporal_local', 'vf_spatial_simult', 'vf_interaction']
    df = df[df['MWh'].fillna(0) > 0]

    def weighted(group):
        w = group['MWh']
        out = {}
        for col in vf_cols:
            valid = group[col].notna()
            out[col] = np.average(group.loc[valid, col], weights=w.loc[valid]) if valid.any() else np.nan
        return pd.Series(out)

    ## include_groups=False is omitted for compatibility with pandas < 2.2
    return df.groupby(['i', 't']).apply(weighted).reset_index()


#%% ===========================================================================
### --- PLOTTING ---
### ===========================================================================
def get_wind_techs(case):
    """Land-based and offshore wind resource classes present in this case's `cap` output."""
    cap = reeds.io.read_output(case, 'cap')
    i_lower = cap['i'].str.lower()
    ons = sorted(cap.loc[i_lower.str.startswith('wind-ons'), 'i'].unique())
    ofs = sorted(cap.loc[i_lower.str.startswith('wind-ofs'), 'i'].unique())
    return ons, ofs


def get_tech_style(techs, tech_group_map=None):
    """
    Display name and color per tech, from bokehpivot's tech_map/tech_style. A group label
    with no tech_map entry of its own (e.g. 'upv') is looked up through one of its member
    classes so it still gets a real color.
    """
    fmt = reeds.io.get_plot_formatting()
    tech_map, tech_color = fmt['tech_map'], fmt['tech_color']['color']
    representative = {}
    if tech_group_map:
        for raw, group in tech_group_map.items():
            representative.setdefault(group, raw)

    style = {}
    fallback_colors = plt.rcParams['axes.prop_cycle'].by_key()['color']
    for n, tech in enumerate(techs):
        lookup = representative.get(tech, tech)
        display = teu.resolve_tech_display(lookup.lower(), tech_map) or tech
        color = tech_color.get(display, fallback_colors[n % len(fallback_colors)])
        style[tech] = {'display': display, 'color': color}
    return style


def plot_value_cost_stack(nat, techs, style, savepath, units, value_cols, cost_cols, ylabel, fname):
    years = sorted(nat['t'].unique())
    ntech = len(techs)
    fig, axes = plt.subplots(1, ntech, figsize=(3.6 * ntech, 4.5), sharey=True)
    axes = np.atleast_1d(axes)
    value_colors = plt.cm.Greens(np.linspace(0.4, 0.75, len(value_cols)))
    cost_colors = plt.cm.Reds(np.linspace(0.4, 0.75, len(cost_cols)))

    for ax, tech in zip(axes, techs):
        sub = nat[nat.i == tech].set_index('t').reindex(years)
        bottom_pos = np.zeros(len(years))
        for col, color in zip(value_cols, value_colors):
            vals = sub[col].fillna(0).values
            ax.bar(years, vals, bottom=bottom_pos, color=color, label=col, width=2.2)
            bottom_pos = bottom_pos + vals
        bottom_neg = np.zeros(len(years))
        for col, color in zip(cost_cols, cost_colors):
            vals = -sub[col].fillna(0).values
            ax.bar(years, vals, bottom=bottom_neg, color=color, label=f'-{col}', width=2.2)
            bottom_neg = bottom_neg + vals
        ax.plot(years, sub['net_value'].values, marker='o', color='k', lw=1.25, label='net_value', zorder=10)
        ax.axhline(0, color='0.4', lw=0.8)
        ax.set_title(style[tech]['display'])
        ax.set_xlabel('Year')
    axes[0].set_ylabel(teu.wrap_label(f'{ylabel} [{units}]'))
    axes[-1].legend(frameon=False, fontsize=7, loc='upper left', bbox_to_anchor=(1.02, 1))
    plots.despine(axes)
    plt.tight_layout()
    plt.savefig(os.path.join(savepath, fname))
    plt.close()


def plot_value_factor(vf, techs, style, savepath):
    fig, ax = plt.subplots(figsize=(6, 4.2))
    for tech in techs:
        sub = vf[vf.i == tech].sort_values('t')
        ax.plot(sub['t'], sub['vf'], marker='o', color=style[tech]['color'], label=style[tech]['display'])
    ax.axhline(1, color='0.5', ls='--', lw=1, label='benchmark (system-average)')
    ax.set_ylabel('Value factor [-]')
    ax.set_xlabel('Year')
    ax.legend(frameon=False, fontsize=9)
    plots.despine(ax)
    plt.tight_layout()
    plt.savefig(os.path.join(savepath, 'value_factor.png'))
    plt.close()


def plot_firm_capacity_contribution(fc, techs, style, savepath, fname='firm_capacity_contribution.png'):
    fig, ax = plt.subplots(figsize=(6, 4.2))
    for tech in techs:
        sub = fc[fc.i == tech].sort_values('t')
        ax.plot(
            sub['t'], sub['firm_capacity_contribution'], marker='o',
            color=style[tech]['color'], label=style[tech]['display'],
        )
    ax.axhline(1, color='0.5', ls='--', lw=1, label='fully firm (gen = capacity)')
    ax.set_ylim(bottom=0)
    ax.set_ylabel(teu.wrap_label('Firm capacity contribution [-]'))
    ax.set_xlabel('Year')
    ax.legend(frameon=False, fontsize=9, loc='upper left', bbox_to_anchor=(1.02, 1))
    plots.despine(ax)
    plt.tight_layout()
    plt.savefig(os.path.join(savepath, fname))
    plt.close()


def plot_boxplot_by_tech_year(
    df, value_col, techs, style, savepath, fname, ylabel,
    ref_line=None, ref_label=None, ylim_zero=False,
):
    """
    One box per tech per year summarizing a per-(i, r, t) metric's distribution across
    regions, which a national average line can't show. Techs with no data for `value_col` are
    skipped rather than drawn empty.
    """
    plot_techs = [t for t in techs if df.loc[df.i == t, value_col].notna().any()]
    years = sorted(df['t'].unique())
    if not plot_techs or not years:
        return
    ntech = len(plot_techs)
    width = 0.8 / ntech
    fig, ax = plt.subplots(figsize=(max(6, 1.1 * len(years)), 4.5))

    for i, tech in enumerate(plot_techs):
        offset = (i - (ntech - 1) / 2) * width
        data, positions = [], []
        for j, year in enumerate(years):
            vals = df.loc[(df.i == tech) & (df.t == year), value_col].dropna().values
            if len(vals) == 0:
                continue
            data.append(vals)
            positions.append(j + offset)
        if not data:
            continue
        ax.boxplot(
            data, positions=positions, widths=width * 0.85, patch_artist=True, manage_ticks=False,
            boxprops={'facecolor': style[tech]['color'], 'alpha': 0.6},
            medianprops={'color': 'k'}, flierprops={'markersize': 3, 'markeredgecolor': style[tech]['color']},
        )

    if ref_line is not None:
        ax.axhline(ref_line, color='0.5', ls='--', lw=1)
    if ylim_zero:
        ax.set_ylim(bottom=0)
    ax.set_xticks(range(len(years)))
    ax.set_xticklabels(years)
    ax.set_xlim(-0.5, len(years) - 0.5)
    ax.set_ylabel(teu.wrap_label(ylabel))
    ax.set_xlabel('Year')
    handles = [
        mpatches.Patch(facecolor=style[t]['color'], alpha=0.6, label=style[t]['display'])
        for t in plot_techs
    ]
    if ref_line is not None:
        handles.append(mlines.Line2D([], [], color='0.5', ls='--', lw=1, label=ref_label))
    ax.legend(handles=handles, frameon=False, fontsize=9, loc='upper left', bbox_to_anchor=(1.02, 1))
    plots.despine(ax)
    plt.tight_layout()
    plt.savefig(os.path.join(savepath, fname))
    plt.close()


def plot_storage_duration(dur, techs, style, savepath):
    """Non-storage techs have no storage_duration_out data and are skipped."""
    fig, ax = plt.subplots(figsize=(6, 4.2))
    plotted = False
    for tech in techs:
        sub = dur[dur.i == tech].sort_values('t')
        if sub['storage_duration'].notna().sum() == 0:
            continue
        ax.plot(
            sub['t'], sub['storage_duration'], marker='o',
            color=style[tech]['color'], label=style[tech]['display'],
        )
        plotted = True
    if not plotted:
        plt.close()
        return
    ax.set_ylabel('Average storage duration [hours]')
    ax.set_xlabel('Year')
    ax.legend(frameon=False, fontsize=9)
    plots.despine(ax)
    plt.tight_layout()
    plt.savefig(os.path.join(savepath, 'storage_duration.png'))
    plt.close()


def plot_reduced_cost(rc, techs, style, savepath, units):
    fig, ax = plt.subplots(figsize=(6, 4.2))
    for tech in techs:
        sub = rc[rc.i == tech].sort_values('t')
        ax.plot(sub['t'], sub['reduced_cost'], marker='o', color=style[tech]['color'], label=style[tech]['display'])
    ax.axhline(0, color='0.5', ls='--', lw=1)
    ax.set_ylabel(teu.wrap_label(f'Reduced cost on INV [{units}]'))
    ax.set_xlabel('Year')
    ax.legend(frameon=False, fontsize=9)
    plots.despine(ax)
    plt.tight_layout()
    plt.savefig(os.path.join(savepath, 'reduced_cost.png'))
    plt.close()


#%% ===========================================================================
### --- VERIFICATION ---
### ===========================================================================
def run_diagnostics(case, techs, first_year, regions=None):
    """
    Tie-out checks against independent outputs.h5 keys. The gross-discharge and capex checks
    are national by design, since they validate this script's $/MWh accounting rather than
    any one region; the refurbishment check honors `regions`, since it explains what a
    --region-filtered value/cost stack is showing.
    """
    print('\n--- diagnostics ---')
    ## Confirms the $/MWh denominator is gross discharge rather than net generation
    gen_ivrt = reeds.io.read_output(case, 'gen_ivrt')
    gen_ivrt = gen_ivrt[gen_ivrt.t >= first_year]
    stor_inout = reeds.io.read_output(case, 'stor_inout').rename(columns={'*': 'direction'})
    stor_inout = stor_inout[stor_inout.t >= first_year]
    for tech in techs:
        gi = gen_ivrt[gen_ivrt.i == tech].groupby('t').Value.sum()
        so = stor_inout[(stor_inout.i == tech) & (stor_inout.direction == 'out')].groupby('t').Value.sum()
        if gi.empty or so.empty:
            continue
        common = gi.index.intersection(so.index)
        diff = ((gi[common] - so[common]).abs() / so[common].replace(0, np.nan)).max()
        if pd.notna(diff) and diff > 0.01:
            warnings.warn(f'{tech}: gen_ivrt vs stor_inout[out] differ by up to {diff:.1%} across years')
        else:
            print(f'  OK: {tech} gross discharge (gen_ivrt) matches stor_inout[out]')

    ## Both use the un-annualized INV cohort, but diverge in ITC years: lcoe_pieces uses the
    ## with-ITC financing multiplier and systemcost_techba the noITC one
    lp = reeds.io.read_output(case, 'lcoe_pieces')
    lp = lp[lp.t >= first_year]
    sc = reeds.io.read_output(case, 'systemcost_techba')
    sc = sc[sc.t >= first_year]
    for tech in techs:
        a = lp[(lp.i == tech) & (lp.lcoe_cat == 'capcost')].groupby('t').Value.sum()
        b = sc[(sc.i == tech) & (sc.sys_costs == 'inv_investment_capacity_costs')].groupby('t').Value.sum()
        common = a.index.intersection(b.index)
        if len(common) == 0:
            continue
        diff = ((a[common] - b[common]).abs() / b[common].replace(0, np.nan)).median()
        print(f'  {tech}: median |lcoe_pieces capcost - systemcost capex| / capex = {diff:.1%} (ITC years may diverge)')

    ## Years whose only capacity addition is a refurbishment show value but no reconstructed
    ## cost, since lcoe_built covers INV only (see load_new_build_cost)
    refurb = reeds.io.read_output(case, 'cap_new_ivrt_refurb')
    refurb = refurb[(refurb.t >= first_year) & (refurb.i.isin(techs))]
    newcap = reeds.io.read_output(case, 'cap_new_ivrt')
    newcap = newcap[(newcap.t >= first_year) & (newcap.i.isin(techs))]
    if regions is not None:
        refurb = refurb[refurb.r.isin(regions)]
        newcap = newcap[newcap.r.isin(regions)]
    refurb_ty = refurb.groupby(['i', 't'], as_index=False).Value.sum().rename(columns={'Value': 'refurb'})
    new_ty = newcap.groupby(['i', 't'], as_index=False).Value.sum().rename(columns={'Value': 'new_total'})
    merged = new_ty.merge(refurb_ty, on=['i', 't'], how='left').fillna({'refurb': 0.0})
    merged = merged[merged['new_total'] > 0]
    ## The 0.999 tolerance allows for float noise in "all of this year's additions are refurb"
    merged['refurb_only'] = merged['refurb'] >= merged['new_total'] * 0.999
    for tech in techs:
        yrs = sorted(merged.loc[(merged.i == tech) & merged['refurb_only'], 't'])
        if yrs:
            print(
                f'  {tech}: {len(yrs)} year(s) with refurbishment-only capacity additions '
                f'(no lcoe_built cost data there): {yrs}'
            )


#%% ===========================================================================
### --- MAIN ---
### ===========================================================================
def main():
    args, case = parse_args()
    techs = teu.parse_techs(args.techs)
    dollar_year = args.dollar_year
    savepath = args.savepath or os.path.join(
        case, 'outputs', 'plots', f'tech_value_{args.region}' if args.region else 'tech_value')
    os.makedirs(savepath, exist_ok=True)

    plots.plotparams()

    techs_raw, tech_group_map = teu.expand_tech_classes(case, techs, output='cap')
    style = get_tech_style(techs, tech_group_map=tech_group_map)
    regions = teu.resolve_regions(case, args.region, level=args.region_level)

    sw = reeds.io.get_switches(case)
    if str(sw.get('GSw_PRM_CapCredit', '0')) == '1':
        warnings.warn(
            'GSw_PRM_CapCredit=1 for this run: val_resmarg and firm_capacity_contribution for '
            'non-VRE techs are not computed the way this script assumes and will show as '
            '0/NaN for any non-VRE tech.'
        )

    df, vn = assemble_value_cost(case, techs_raw, dollar_year, tech_group_map=tech_group_map, regions=regions)
    fc_df, fc_nat = compute_firm_capacity_contribution(
        case, techs_raw, tech_group_map=tech_group_map, regions=regions)
    dur_df, dur_nat = compute_storage_duration(
        case, techs_raw, tech_group_map=tech_group_map, regions=regions)
    ## Drop pre-first_year rows before the benchmark and aggregate calculations, not just from
    ## the figures, so they don't influence the value factor or the national totals
    df = df[df['t'] >= args.first_year].reset_index(drop=True)
    vn = vn[vn['t'] >= args.first_year].reset_index(drop=True)
    fc_df = fc_df[fc_df['t'] >= args.first_year].reset_index(drop=True)
    fc_nat = fc_nat[fc_nat['t'] >= args.first_year].reset_index(drop=True)
    dur_df = dur_df[dur_df['t'] >= args.first_year].reset_index(drop=True)
    dur_nat = dur_nat[dur_nat['t'] >= args.first_year].reset_index(drop=True)
    df = df.merge(fc_df, on=['i', 'r', 't'], how='left').merge(dur_df, on=['i', 'r', 't'], how='left')
    vf = compute_value_factors(vn, techs)
    rc = load_reduced_cost(case, techs_raw, dollar_year, tech_group_map=tech_group_map, regions=regions)
    rc = rc[rc['t'] >= args.first_year].reset_index(drop=True)

    ## Sum dollar/MW/MWh numerators across regions first; never average ratios
    dollar_cols = [
        'gross_energy_value', 'firm_capacity_value', 'total_value',
        'annualized_capex', 'fomcost', 'vomcost', 'charge_cost', 'total_cost', 'net_value',
    ]
    nat = df.groupby(['i', 't'], as_index=False)[dollar_cols + ['MW', 'MWh']].sum()
    for col in dollar_cols:
        nat[f'{col}_kwyr'] = nat[col] / nat['MW'] / 1000
        nat[f'{col}_permwh'] = nat[col] / nat['MWh']
    nat = nat.merge(vf, on=['i', 't'], how='left').merge(rc, on=['i', 't'], how='left')
    nat = nat.merge(fc_nat, on=['i', 't'], how='left').merge(dur_nat, on=['i', 't'], how='left')

    ## A group name like 'upv' has firm-capacity and storage-duration data but no value/cost
    ## data, so the $/MWh figures below plot techs_value while the others plot every tech
    for tech in techs:
        if not (nat.i == tech).any():
            warnings.warn(f"No value/cost data assembled for '{tech}' -- omitted from those plots/CSVs")
    techs_value = [t for t in techs if (nat.i == t).any()]

    nat_long = nat.melt(id_vars=['i', 't'], var_name='metric', value_name='value')
    nat_long.to_csv(os.path.join(savepath, 'tech_value_comparison.csv'), index=False)
    df.to_csv(os.path.join(savepath, 'tech_value_by_region.csv'), index=False)
    print(f'Wrote {os.path.join(savepath, "tech_value_comparison.csv")}')
    print(f'Wrote {os.path.join(savepath, "tech_value_by_region.csv")}')

    ## The CSVs cover every year from --first-year; the figures start at --plot-first-year
    nat_plot = nat[nat['t'] >= args.plot_first_year].reset_index(drop=True)
    ## fc_nat/dur_nat, not nat_plot: nat only has rows for techs_value
    fc_nat_plot = fc_nat[fc_nat['t'] >= args.plot_first_year].reset_index(drop=True)
    dur_nat_plot = dur_nat[dur_nat['t'] >= args.plot_first_year].reset_index(drop=True)

    nat_kwyr = nat_plot.copy()
    nat_kwyr['net_value'] = nat_plot['net_value_kwyr']
    plot_value_cost_stack(
        nat_kwyr, techs_value, style, savepath, units=f'{dollar_year}$/kW-yr',
        value_cols=['gross_energy_value_kwyr', 'firm_capacity_value_kwyr'],
        cost_cols=['annualized_capex_kwyr', 'fomcost_kwyr', 'vomcost_kwyr', 'charge_cost_kwyr'],
        ylabel='Value / cost of new-build capacity', fname='value_cost_stack_kwyr.png',
    )

    nat_mwh = nat_plot.copy()
    nat_mwh['net_value'] = nat_plot['net_value_permwh']
    plot_value_cost_stack(
        nat_mwh, techs_value, style, savepath, units=f'{dollar_year}$/MWh',
        value_cols=['gross_energy_value_permwh', 'firm_capacity_value_permwh'],
        cost_cols=['annualized_capex_permwh', 'fomcost_permwh', 'vomcost_permwh', 'charge_cost_permwh'],
        ylabel='Value / cost per MWh (gross discharge/generation)', fname='value_cost_stack_mwh.png',
    )

    plot_value_factor(nat_plot, techs_value, style, savepath)
    plot_firm_capacity_contribution(fc_nat_plot, techs, style, savepath)
    plot_boxplot_by_tech_year(
        fc_df[fc_df['t'] >= args.plot_first_year], 'firm_capacity_contribution', techs, style, savepath,
        fname='firm_capacity_contribution_boxplot.png',
        ylabel='Firm capacity contribution by region [-]',
        ref_line=1, ref_label='fully firm (gen = capacity)', ylim_zero=True,
    )

    if args.include_wind:
        wind_ons, wind_ofs = get_wind_techs(case)
        wind_group_map = dict(tech_group_map)
        wind_group_map.update({t: 'Land-Based Wind' for t in wind_ons})
        wind_group_map.update({t: 'Offshore Wind' for t in wind_ofs})
        wind_techs = ['Land-Based Wind', 'Offshore Wind']
        _, fc_nat_wind = compute_firm_capacity_contribution(
            case, techs_raw + wind_ons + wind_ofs, tech_group_map=wind_group_map, regions=regions)
        fc_nat_wind = fc_nat_wind[
            (fc_nat_wind['t'] >= args.plot_first_year) & (fc_nat_wind.i.isin(techs + wind_techs))
        ].reset_index(drop=True)
        tech_color = reeds.io.get_plot_formatting()['tech_color']['color']
        style_wind = dict(style)
        style_wind['Land-Based Wind'] = {
            'display': 'Land-Based Wind', 'color': tech_color.get('Onshore Wind', '#00B6EF')}
        style_wind['Offshore Wind'] = {
            'display': 'Offshore Wind', 'color': tech_color.get('Offshore Wind', '#106BA7')}
        plot_firm_capacity_contribution(
            fc_nat_wind, techs + wind_techs, style_wind, savepath,
            fname='firm_capacity_contribution_with_wind.png',
        )

    plot_storage_duration(dur_nat_plot, techs, style, savepath)
    plot_boxplot_by_tech_year(
        dur_df[dur_df['t'] >= args.plot_first_year], 'storage_duration', techs, style, savepath,
        fname='storage_duration_boxplot.png',
        ylabel='Average storage duration by region [hours]',
    )
    plot_reduced_cost(nat_plot, techs_value, style, savepath, units=f'{dollar_year}$/kW')
    print(f'Wrote figures to {savepath}')

    run_diagnostics(case, techs_raw, args.first_year, regions=regions)


if __name__ == '__main__':
    main()
