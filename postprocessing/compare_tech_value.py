"""
Compare the value, cost, and firmness of new-build capacity for two ReEDS
technologies (default: battery_li vs Gas-CT) using a single finished run's
outputs.h5. Everything is read from {case}/outputs/outputs.h5 -- no re-solve
is required.

Value and cost framing
-----------------------
The value/cost comparison is built around ReEDS' native "value of new
investment" output (`valnew`), which reports the value earned by capacity
newly built in each solve year, split into an energy stream (`val_load`) and
a firm-capacity stream (`val_resmarg`). This answers "what is a marginal new
unit of this tech worth to the system", which is the natural apples-to-apples
framing for comparing a storage technology to a peaker.

Two accounting quirks specific to storage are handled explicitly:

- `val_load` for a storage tech is already *net* of charging cost (GAMS
  computes (GEN - STORAGE_IN) * hours * price; see report.gms, VALUE (REVENUE)
  OF NEW BUILDS). For a thermal tech, `val_load` is gross and fuel cost lives
  entirely on the cost side. To make the two techs' cost/value decompositions
  comparable, this script "grosses up" storage's energy value by adding back
  an explicit charging-cost line (`charge_cost`) computed from `stor_in`,
  and treats it as a cost -- the storage analogue of a thermal tech's fuel
  cost -- rather than a value deduction.
- Annual generation/discharge (`valnew`'s `MWh`, `gen_ivrt`) is *gross* for
  storage, while `gen_ann` is *net* of charging and can be negative. All
  $/MWh figures in this script use the gross basis, matching `stor_inout`'s
  'out' direction.

Cost is reconstructed from `lcoe_built` (the model's own fully annualized
$/MWh LCOE for the new-build cohort, which already applies the capital
recovery factor) together with `lcoe_pieces` (unannualized FOM/VOM/fuel and
capcost, which are additive with the same cohort/denominator as
`lcoe_built`). Capital cost is recovered as the *residual*
`lcoe_built * gen - fomcost - vomcost`, rather than reconstructing the
capital recovery factor independently -- this keeps the split exact by
construction and avoids reimplementing model internals (see AGENTS.md).

Firm capacity, storage duration, and stress-period diagnostics
----------------------------------------------------------------
`firm_capacity_contribution` and `storage_duration` describe how "firm" each
tech's capacity actually is, each shown as both a national/fleet-wide line
and a per-region box-and-whisker plot (a single average can hide a lot of
regional variation -- see `_boxplot_by_tech_year`). `--include-wind` adds
land-based and offshore wind as two extra lines on a separate copy of the
firm-capacity plot.

The stress-period price and dispatch tools exist to help interpret *why* a
given tech's firm capacity contribution looks the way it does: the price
plots (national and per-region) show whether a stress day's high price is a
narrow single-hour spike or a broad/bimodal window that a short-duration
resource can't fully capture, and the dispatch plots show the underlying
generation stack (plus net imports -- see `load_dispatch_stress`) for a
specific region/day, e.g. to see whether a flat/low price means ample local
capacity or heavy reliance on imports that day. `--dispatch-region` can also
name a value in hierarchy.csv (via `--dispatch-level`) to aggregate every
region mapped to it, e.g. a whole interconnection.

Usage
-----
    python compare_tech_value.py <path-to-case>
    python compare_tech_value.py <path-to-case> --techs battery_li,Gas-CT --include-wind
    python compare_tech_value.py <path-to-case> --price-region TX_W
    python compare_tech_value.py <path-to-case> \\
        --dispatch-region western --dispatch-level interconnect \\
        --dispatch-year 2050 --dispatch-day y2009d342

Run with --help for the full list of options.

Outputs
-------
Written to {case}/outputs/plots/tech_value/ by default:
- tech_value_comparison.csv, tech_value_by_region.csv -- tidy value/cost/
  firm-capacity/storage-duration data, national and by-region
- value_cost_stack_kwyr.png, value_cost_stack_mwh.png -- value/cost/net-value
  decomposition, per tech
- value_factor.png -- value factor vs. the system-average benchmark
- firm_capacity_contribution.png (+ _boxplot, + _with_wind if requested)
- storage_duration.png (+ _boxplot)
- reduced_cost.png -- the model's own marginal-competitiveness signal
- stress_period_prices/ -- one price figure per region plus a national one
- dispatch/ -- one dispatch-stack figure per --dispatch-region call
"""
import argparse
import os
import sys
import textwrap
import warnings

import matplotlib
## Force a non-interactive backend: this script only ever calls savefig(), and an
## interactive backend (e.g. Qt) can crash hard when run without a display attached.
matplotlib.use('Agg')
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
        description='Compare the value and cost of new-build capacity for two ReEDS technologies.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ## Include both case_positional and --case/-c, matching single_case_plots.py convention
    parser.add_argument('case_positional', type=str, nargs='?', help='path to ReEDS run folder')
    parser.add_argument('--case', '-c', type=str, help='path to ReEDS run folder')
    parser.add_argument(
        '--savepath', type=str, default=None,
        help='output directory (default: {case}/outputs/plots/tech_value)',
    )

    core = parser.add_argument_group('tech/year selection (value, cost, firm capacity, storage duration)')
    core.add_argument(
        '--techs', type=str, default='battery_li,Gas-CT',
        help=(
            'comma-separated technology names, exactly as they appear in outputs.h5 '
            '(case-sensitive -- e.g. "Gas-CT", not "gas-ct")'
        ),
    )
    core.add_argument('--dollar-year', type=int, default=2024, help='dollar year to inflate $ values to')
    core.add_argument(
        '--first-year', type=int, default=2026,
        help=(
            'first endogenous solve year; earlier solve years are fixed to historical/calibration '
            'data rather than optimized, so they are excluded from the comparison entirely '
            '(CSVs, figures, and diagnostics)'
        ),
    )
    core.add_argument(
        '--plot-first-year', type=int, default=2029,
        help=(
            'first year shown in the figures (default skips --first-year itself, since its '
            'value/cost figures are still transitional/scarcity-driven and dominate the y-axis '
            'scale); the CSVs still include every year from --first-year onward'
        ),
    )
    core.add_argument(
        '--include-wind', action='store_true',
        help=(
            'also write firm_capacity_contribution_with_wind.png, adding land-based and '
            'offshore wind (summed across all wind-ons_*/wind-ofs_* resource classes present '
            'in the case) as two extra lines alongside --techs'
        ),
    )

    price = parser.add_argument_group('stress-period price plots (stress_period_prices/)')
    price.add_argument(
        '--price-year', type=int, default=None,
        help='solve year to show in the stress-period price plot (default: the last solve year)',
    )
    price.add_argument(
        '--price-region', type=str, default=None,
        help=(
            'restrict the stress-period price plots to a single region (BA), e.g. TX_W; '
            'default is one plot per region plus the national quantity-weighted average'
        ),
    )

    region = parser.add_argument_group('region filter (value, cost, firm capacity, storage duration)')
    region.add_argument(
        '--region', type=str, default=None,
        help=(
            'restrict value/cost/firm-capacity/storage-duration figures and CSVs to a single '
            'region (BA, e.g. CA_LA) or a value within --region-level (e.g. "WI" with '
            '--region-level st) to aggregate every region mapped to it; default is national '
            '(all regions). --techs entries with no exact match in outputs.h5 are summed across '
            'every matching "{entry}_*" resource class for the firm-capacity-contribution and '
            'storage-duration plots (e.g. "upv" -> upv_1, upv_2, ...); the value/cost-stack, '
            'value-factor, and reduced-cost plots need exact names and skip (with a warning) any '
            'entry that has no exact match, since $/MWh figures cannot be summed across classes '
            'without re-deriving weights'
        ),
    )
    region.add_argument(
        '--region-level', type=str, default='r',
        help='hierarchy.csv column that --region is a value of, e.g. interconnect, transreg, st, nercr',
    )

    dispatch = parser.add_argument_group('stress-period dispatch plot (dispatch/)')
    dispatch.add_argument(
        '--dispatch-region', type=str, default=None,
        help=(
            'region (BA, e.g. CA_LA) to plot stress-period dispatch for, or a value within '
            '--dispatch-level (e.g. "western" with --dispatch-level interconnect) to aggregate '
            'every region mapped to it; no dispatch plot if omitted'
        ),
    )
    dispatch.add_argument(
        '--dispatch-level', type=str, default='r',
        help=(
            'hierarchy.csv column that --dispatch-region is a value of, e.g. interconnect, '
            'transreg, st, nercr; default "r" treats --dispatch-region as a literal BA code'
        ),
    )
    dispatch.add_argument(
        '--dispatch-year', type=int, default=None,
        help='solve year for --dispatch-region (default: the last solve year)',
    )
    dispatch.add_argument(
        '--dispatch-day', type=str, default=None,
        help=(
            'stress day for --dispatch-region, e.g. y2009d342 (see the stress_period_prices '
            'panel titles for valid day labels); required if --dispatch-region is given'
        ),
    )

    args = parser.parse_args()
    if args.case_positional and args.case:
        raise ValueError('Provide case as positional argument or --case/-c, not both')
    case = args.case_positional or args.case
    if not case:
        raise ValueError('Provide case path either as positional argument or as --case/-c')
    if args.dispatch_region and not args.dispatch_day:
        raise ValueError('--dispatch-day is required when --dispatch-region is given')
    return args, case


#%% ===========================================================================
### --- DATA LOADING ---
### ===========================================================================
def load_valnew(case, techs, dollar_year, tech_group_map=None, regions=None):
    """
    Load and inflate `valnew`, returning a wide (i, r, t) frame with one
    column per `output` (MW, MWh, val_load, val_resmarg, ...), including the
    'benchmark' rows (both per-region and system-wide, r == 'sys').

    `techs` here is the raw tech (`i`) names to query (e.g. from expand_tech_groups). Any
    entry with no exact match in `valnew` is dropped with a warning rather than raising, so
    the run doesn't abort. `regions`, if given, restricts to those BAs; the system-wide
    'benchmark' rows (r == 'sys') are always kept regardless, since they're the
    value-factor denominator.

    If `tech_group_map` is given (raw i -> group label), rows are relabeled and summed by
    group before pivoting -- safe for the additive columns (MW, MWh, val_load,
    val_resmarg). `inv_cap_ratio` is a true ratio and would be summed too, which is
    inexact for a grouped *storage* tech, but it's only consumed downstream (by
    load_charge_cost) for storage techs, and ReEDS storage techs aren't resource-class-
    suffixed today, so expand_tech_groups never actually groups one in practice.
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
    Reconstruct the annualized cost of new-build capacity (capex, FOM,
    VOM+fuel) per (i, r, t) from `lcoe_built` and `lcoe_pieces`, without
    reimplementing the capital recovery factor. Both outputs share the same
    new-build-cohort denominator (GEN.l summed over INV.l/UPGRADES.l), so:

        annualized_capex = lcoe_built * lcoe_pieces['gen'] - fomcost - vomcost

    is exact by construction (lcoe_built's own numerator is
    capex_annualized + fomcost + vomcost, divided by the same gen).
    `vomcost` already includes fuel cost for combustion techs
    (see report.gms, lcoe_pieces("vomcost",...)). `regions`, if given, restricts to those BAs.

    Known gap: `lcoe_built`'s own gate in report.gms only checks `INV.l` (brand-new
    investment), not `INV_REFURB.l` (refurbishment of existing capacity) -- unlike
    `valnew`, whose value calculations include both. So a (tech, region, year) whose only
    capacity addition that year is a refurbishment (see `cap_new_ivrt_refurb`) gets real
    value from `valnew` but zero reconstructed cost here -- a bar with value and no cost
    in the value/cost-stack plot, not a bug in this script.

    `techs` is the raw tech (`i`) names to query. If `tech_group_map` is given (raw i ->
    group label), `annualized_capex`/`fomcost`/`vomcost` are computed at raw-tech
    granularity first -- `lcoe_built` is a $/MWh ratio, not safely summable across
    resource classes -- and only relabeled/summed by group afterward, once they're
    additive $ amounts.
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
    ## lcoe_built's capital term already sums capcost + upgradecost + rsccost (each multiplied by
    ## crf(t) inside the same parenthesis in report.gms), so this residual is their combined
    ## annualized total -- adding lcoe_pieces' raw upgradecost/rsccost on top would double-count
    ## them (both are 0 for battery_li/Gas-CT in this run, but not necessarily for other techs).
    cost['annualized_capex'] = cost['lcoe_built'] * cost['gen'] - cost['fomcost'] - cost['vomcost']
    if tech_group_map:
        cost['i'] = cost['i'].map(lambda x: tech_group_map.get(x, x))
        cost = cost.groupby(['i', 'r', 't'], as_index=False)[['annualized_capex', 'fomcost', 'vomcost']].sum()
    for col in ['annualized_capex', 'fomcost', 'vomcost']:
        cost[col] = reeds.results.inflate_series(cost[col], to_dollar_year=dollar_year)
    return cost[['i', 'r', 't', 'annualized_capex', 'fomcost', 'vomcost']]


def load_charge_cost(case, techs, dollar_year, vn_wide, tech_group_map=None, regions=None):
    """
    Annual charging cost of the new-build cohort, mirroring exactly how GAMS
    computes val_load for storage: sum_h(STORAGE_IN * hours * load price),
    restricted to the vintages actually invested in that (i, r, t), scaled
    by inv_cap_ratio (see report.gms, valnew('val_load', ...)). Zero for any
    tech with no `stor_in` rows (e.g. Gas-CT). `regions`, if given, restricts to those BAs.
    `tech_group_map`, if given, relabels/sums `charge_cost_raw` (additive) by group before
    the `vn_wide` merge, so it lines up with vn_wide's own (already-relabeled) `i` values.
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

    ratio = vn_wide[['i', 'r', 't', 'inv_cap_ratio']] if 'inv_cap_ratio' in vn_wide else None
    if ratio is not None:
        cc = cc.merge(ratio, on=['i', 'r', 't'], how='left')
        cc['charge_cost'] = cc['charge_cost_raw'] * cc['inv_cap_ratio'].fillna(0)
    else:
        cc['charge_cost'] = cc['charge_cost_raw']
    cc['charge_cost'] = reeds.results.inflate_series(cc['charge_cost'], to_dollar_year=dollar_year)
    return cc[['i', 'r', 't', 'charge_cost']]


def load_reduced_cost(case, techs, dollar_year, tech_group_map=None, regions=None):
    """Average reduced cost ($/kW) on the INV variable, by tech and year (national by
    default; restricted to `regions`, if given). `techs` is the raw tech (`i`) names to
    query; `tech_group_map`, if given, relabels by group before averaging -- a mean across
    a group's raw resource classes is as valid an aggregate as the existing mean across
    (v, r) combinations."""
    rc = reeds.io.read_output(case, 'reduced_cost').rename(columns={'*': 'bin', '*.1': 'var'})
    ## Use bracket notation, not attribute access: DataFrame.var is a built-in method
    ## (variance), so `rc.var` silently returns that method instead of the 'var' column.
    rc = rc[(rc['var'] == 'INV') & (rc.i.isin(techs))].copy()
    if regions is not None:
        rc = rc[rc.r.isin(regions)]
    rc['t'] = rc['t'].astype(int)
    rc['Value'] = reeds.results.inflate_series(rc['Value'], to_dollar_year=dollar_year)
    if tech_group_map:
        rc['i'] = rc['i'].map(lambda x: tech_group_map.get(x, x))
    return rc.groupby(['i', 't'], as_index=False)['Value'].mean().rename(columns={'Value': 'reduced_cost'})


def _parse_stress_hours(df):
    """Parse stress-period hour labels like 'sy2009d016h003' (synthetic year, day-of-year,
    hour) into sortable (stress_year, stress_day, hour) columns plus a 'day_label'."""
    parsed = df['h'].str.extract(r's?y(\d+)d(\d+)h(\d+)')
    df['stress_year'] = parsed[0].astype(int)
    df['stress_day'] = parsed[1].astype(int)
    df['hour'] = parsed[2].astype(int)
    df['day_label'] = 'y' + df['stress_year'].astype(str) + 'd' + df['stress_day'].astype(str).str.zfill(3)
    return df.sort_values(['stress_year', 'stress_day', 'hour'])


def _select_stress_year(df, year):
    """Filter a (reqt, subcat, [r], h, t, price) frame to res_marg/na and one solve year,
    defaulting to the last year present. Returns (sub, year); sub is empty if nothing matches."""
    df = df[(df.reqt == 'res_marg') & (df.subcat == 'na')].copy()
    df['t'] = df['t'].astype(int)
    if df.empty:
        return df, year
    year = df['t'].max() if year is None else year
    sub = df[df.t == year].copy()
    return sub, year


def load_national_stress_period_prices(case, year=None):
    """
    National reserve-margin stress-period price by stress-period timestep, for one solve
    year, parsed into (stress_day, hour) so it can be plotted as a within-day timeseries.

    Uses `reqt_price_sys` (GAMS's own quantity-weighted national average across regions;
    see report.gms, reqt_price_sys('res_marg',...)) rather than averaging `reqt_price`
    across regions here. Units are $/kW per stress-period timeslice, not $/MWh -- GAMS
    reports $/MW (converted to $/kW here) and does not divide by `hours(h)` for the
    stress-period formulation (see report.gms, "Stress period formulation
    ($/MW/stress-timeslice)").

    Returns (sub, year): sub is empty if no stress-period price data exists for `year`.
    """
    rps = reeds.io.read_output(case, 'reqt_price_sys').rename(
        columns={'*': 'reqt', '*.1': 'subcat', '*.2': 'h', 'Value': 'price'})
    sub, year = _select_stress_year(rps, year)
    if sub.empty:
        return sub, year
    sub['price'] = sub['price'] / 1000
    return _parse_stress_hours(sub), year


def load_regional_stress_period_prices(case, year=None):
    """
    Same as load_national_stress_period_prices, but for every region at once (from
    `reqt_price` rather than `reqt_price_sys`), so callers can slice by region without
    re-reading outputs.h5 per region. Returns (sub, year) with an 'r' column.
    """
    rp = reeds.io.read_output(case, 'reqt_price').rename(
        columns={'*': 'reqt', '*.1': 'subcat', '*.2': 'h', 'Value': 'price'})
    sub, year = _select_stress_year(rp, year)
    if sub.empty:
        return sub, year
    sub['price'] = sub['price'] / 1000
    return _parse_stress_hours(sub), year


def resolve_regions(case, region, level='r'):
    """
    Resolve a region/level pair (--dispatch-region/--dispatch-level or --region/
    --region-level) into a list of BA (r) codes to aggregate. level='r' (default) treats
    `region` as a literal BA code. Any other level (e.g. 'interconnect', 'transreg', 'st',
    'nercr' -- any column of inputs_case/hierarchy.csv) treats `region` as a value within
    that column and returns every BA mapped to it.
    """
    if level == 'r':
        return [region]
    hierarchy = reeds.io.get_hierarchy(case)
    if level not in hierarchy.columns:
        raise ValueError(f"'{level}' is not a column of hierarchy.csv; got {list(hierarchy.columns)}")
    regions = hierarchy.loc[hierarchy[level].str.lower() == region.lower()].index.tolist()
    if not regions:
        raise ValueError(f"No regions found with {level}='{region}' in hierarchy.csv")
    return regions


def load_dispatch_stress(case, regions, year=None):
    """
    Stress-period generation dispatch (by tech, in GW) and load (GW) summed across `regions`
    (a list of one or more BA codes -- see resolve_regions), across every stress day
    in one solve year -- for visualizing why the price in a region or aggregate of regions is
    high or flat on a given day (e.g. ample local capacity vs. load, or heavy reliance on
    imports, that day).

    Summing net_import_h_stress across `regions` before use is intentional and exact: flows
    between two regions both in `regions` cancel out (one side's export is the other's
    import), leaving only the net flow across the boundary of the whole aggregate -- e.g.
    summing every western-interconnect BA's net imports gives the interconnect's net import
    from the rest of the country, not a meaningless sum of each BA's individual number.

    In-region (or in-aggregate) generation alone is frequently well below load, with the gap
    covered by transmission -- so a 'Net imports' pseudo-tech is included alongside the real
    techs; without it, the stack understates supply and can look like an unexplained deficit.
    Real techs are simplified/aggregated to match reeds.io.get_plot_formatting()['tech_color']
    categories, the same convention used by reeds.reedsplots.plot_stressperiod_dispatch.

    Returns (gen, load, year): gen has columns [i, t, GW, stress_year, stress_day, hour,
    day_label]; load has the same minus i. Both empty if no data exists for `regions`/`year`.
    """
    gen = reeds.io.read_output(case, 'gen_h_stress', valname='GW')
    gen = gen[gen.r.isin(regions)].copy()
    gen['t'] = gen['t'].astype(int)
    if gen.empty:
        return gen, pd.DataFrame(), year

    year = gen['t'].max() if year is None else year
    gen = gen[gen.t == year].copy()
    if gen.empty:
        return gen, pd.DataFrame(), year
    gen['GW'] = gen['GW'] / 1000
    gen['i'] = reeds.reedsplots.simplify_techs(gen['i'])
    gen = gen.groupby(['i', 't', 'h'], as_index=False)['GW'].sum()

    net_imports = reeds.io.read_output(case, 'net_import_h_stress', valname='GW')
    net_imports = net_imports[(net_imports.r.isin(regions)) & (net_imports.t.astype(int) == year)].copy()
    if not net_imports.empty:
        net_imports['GW'] = net_imports['GW'] / 1000
        net_imports = net_imports.groupby(['t', 'h'], as_index=False)['GW'].sum()
        net_imports['i'] = 'Net imports'
        gen = pd.concat([gen, net_imports[['i', 't', 'h', 'GW']]], ignore_index=True)
    gen = _parse_stress_hours(gen)

    load = reeds.io.read_output(case, 'load_stress', valname='GW')
    load = load[(load.r.isin(regions)) & (load.t.astype(int) == year)].copy()
    if not load.empty:
        load['GW'] = load['GW'] / 1000
        load = load.groupby(['t', 'h'], as_index=False)['GW'].sum()
        load = _parse_stress_hours(load)
    return gen, load, year


def compute_firm_capacity_contribution(case, techs, tech_group_map=None, regions=None):
    """
    Price-weighted firm capacity contribution: for each stress period, the ratio of
    stress-period generation to total capacity, weighted by that stress period's
    reserve-margin price --

        sum_h(gen_h_stress(i,r,h,t) * price(r,h,t)) / (cap(i,r,t) * sum_h(price(r,h,t)))

    The numerator is read directly from `revenue`'s 'res_marg' category rather than
    recomputed from `gen_h_stress`/`reqt_price`: when GSw_PRM_CapCredit=0, GAMS computes
    revenue('res_marg', i, r, t) as exactly sum_h(gen_h_stress * price) (report.gms, REVENUE
    LEVELS), so reusing it is both simpler and exact by construction. Only meaningful under
    GSw_PRM_CapCredit=0 -- see the warning in main().

    `techs` is the raw tech (`i`) names to query. If `tech_group_map` is given (raw i ->
    group label), rows are relabeled and summed by group before computing the ratio -- e.g.
    mapping every 'wind-ons_*' class to 'Land-Based Wind' gives that resource class's
    aggregate contribution, summing numerator and denominator across classes first (never
    averaging per-class ratios directly), the same principle used for regional aggregation.
    `regions`, if given, restricts to those BAs before aggregating to `nat`.

    Returns (df, nat): df is per (i, r, t); nat is aggregated to (i, t) by summing numerator
    and denominator across regions first (never averaging regional ratios directly).
    """
    def _group(s):
        return s.map(lambda x: tech_group_map.get(x, x)) if tech_group_map else s

    rev = reeds.io.read_output(case, 'revenue')
    rev = rev[(rev.rev_cat == 'res_marg') & (rev.i.isin(techs))][['i', 'r', 't', 'Value']].copy()
    if regions is not None:
        rev = rev[rev.r.isin(regions)]
    rev['i'] = _group(rev['i'])
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
    cap['i'] = _group(cap['i'])
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
    Fleet-wide average storage duration (hours) by tech and year, capacity-weighted:
    GAMS's own `storage_duration_out` (CAP_ENERGY.l / CAP.l per vintage/region; see
    report.gms, BINNED STORAGE CAPACITY) weighted by `cap_ivrt` (CAP.l), summed across
    vintages and regions before dividing -- not an average of per-vintage durations.
    `storage_duration_out` only exists for battery techs, so non-battery techs in
    `techs` are simply absent from the result. `regions`, if given, restricts to those BAs.

    `techs` is the raw tech (`i`) names to query. If `tech_group_map` is given (raw i ->
    group label), rows are relabeled and summed by group *after* the vintage-level merge
    below (relabeling first would risk colliding two raw techs' same-named vintage bins,
    e.g. both 'upv_1' and 'upv_2' having a 'new3' vintage, into a single, wrong join key).

    Returns (df_region, nat): df_region is capacity-weighted across vintages within each
    (i, r, t); nat additionally weights across regions, i.e., the fleet-wide average.
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
    """
    Combine value (valnew) and cost (lcoe_built/lcoe_pieces + charging) into
    a single tidy (i, r, t) frame with value, cost, and net-value columns.
    `techs` is the raw tech (`i`) names to query; `tech_group_map`, if given, relabels/sums
    by group (see load_valnew/load_new_build_cost/load_charge_cost). `regions`, if given,
    restricts to those BAs (see load_valnew).
    """
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

    ## Gross up storage's energy value by adding back its (already-subtracted) charging cost,
    ## then book that same charging cost as an explicit cost line -- the storage analogue of
    ## fuel cost. Net value is unaffected; only the value/cost decomposition changes.
    df['gross_energy_value'] = df['val_load'] + df['charge_cost']
    df['firm_capacity_value'] = df['val_resmarg']
    df['total_value'] = df['gross_energy_value'] + df['firm_capacity_value']
    df['total_cost'] = df['annualized_capex'] + df['fomcost'] + df['vomcost'] + df['charge_cost']
    df['net_value'] = df['total_value'] - df['total_cost']
    return df, vn


def compute_value_factors(vn_wide, techs):
    """
    Value factor and its temporal/spatial/interaction decomposition, ported
    from postprocessing/bokehpivot/reeds2.py::pre_valnew, computed at (i, r, t)
    and then aggregated to (i, t) with an MWh-weighted mean -- equivalent to
    bokeh's 'sum(a*b)/sum(b)' y_agg convention used for these charts there.
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

    ## Note: not passing include_groups=False for compatibility with pandas < 2.2;
    ## `weighted` only touches named value columns, so the grouping columns are harmless.
    nat = df.groupby(['i', 't']).apply(weighted).reset_index()
    return nat


#%% ===========================================================================
### --- PLOTTING ---
### ===========================================================================
def wrap_label(text, width=28):
    """Wrap a long axis label onto multiple lines so it doesn't run off the figure."""
    return '\n'.join(textwrap.wrap(text, width=width))


def get_wind_techs(case):
    """
    Every raw wind resource-class tech (e.g. wind-ons_1..10, wind-ofs_1..10) present in this
    case's `cap` output, split into land-based and offshore. Resource classes are queried
    dynamically rather than hardcoded, since which classes exist can vary by scenario.
    """
    cap = reeds.io.read_output(case, 'cap')
    i_lower = cap['i'].str.lower()
    ons = sorted(cap.loc[i_lower.str.startswith('wind-ons'), 'i'].unique())
    ofs = sorted(cap.loc[i_lower.str.startswith('wind-ofs'), 'i'].unique())
    return ons, ofs


def expand_tech_groups(case, techs):
    """
    Expand any --techs entry with no exact match among this case's `cap` output `i` values
    into every matching '{entry}_*' resource class present in the case (e.g. 'upv' ->
    'upv_1', 'upv_2', ...), generalizing the wind-ons/wind-ofs summing get_wind_techs
    already does for --include-wind. Only safe for metrics built by summing an additive
    numerator before dividing (firm capacity contribution, storage duration) -- see
    compute_firm_capacity_contribution/compute_storage_duration.

    Returns (techs_raw, tech_group_map): techs_raw is every raw i to query; tech_group_map
    maps each raw i back to the original --techs entry it was expanded from (itself, for an
    entry that was already an exact match).
    """
    cap = reeds.io.read_output(case, 'cap')
    all_i = set(cap['i'].unique())
    tech_group_map = {}
    for tech in techs:
        if tech in all_i:
            tech_group_map[tech] = tech
            continue
        prefix = tech.lower() + '_'
        matches = sorted(i for i in all_i if i.lower().startswith(prefix))
        if not matches:
            raise AssertionError(
                f"'{tech}' has no exact match and no '{tech}_*' resource classes in this "
                "case's `cap` output -- check --techs against outputs.h5."
            )
        for m in matches:
            tech_group_map[m] = tech
    return list(tech_group_map.keys()), tech_group_map


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


def get_tech_style(techs, tech_group_map=None):
    """
    Look up display name + color for each tech via bokehpivot's tech_map/tech_style. If
    `tech_group_map` is given (raw i -> group label, see expand_tech_groups), a group label
    with no tech_map entry of its own (e.g. the literal string 'upv') is resolved through one
    of its raw member techs (e.g. 'upv_1') instead, so it still gets a real color/display name.
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
        display = resolve_tech_display(lookup.lower(), tech_map)
        if display is None:
            display = tech
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
    axes[0].set_ylabel(wrap_label(f'{ylabel} [{units}]'))
    axes[-1].legend(frameon=False, fontsize=7, loc='upper left', bbox_to_anchor=(1.02, 1))
    reedsplots_style.despine(axes)
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
    reedsplots_style.despine(ax)
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
    ax.set_ylabel(wrap_label('Firm capacity contribution [-]'))
    ax.set_xlabel('Year')
    ax.legend(frameon=False, fontsize=9, loc='upper left', bbox_to_anchor=(1.02, 1))
    reedsplots_style.despine(ax)
    plt.tight_layout()
    plt.savefig(os.path.join(savepath, fname))
    plt.close()


def _boxplot_by_tech_year(
    df, value_col, techs, style, savepath, fname, ylabel,
    ref_line=None, ref_label=None, ylim_zero=False,
):
    """
    Shared box-and-whisker layout for a per-(i, r, t) metric: one box per tech per year,
    summarizing the distribution across regions -- e.g. a wide box means the metric is very
    region-dependent, not a single well-defined number, which a national/fleet-wide average
    line plot can't show. Techs with no data for `value_col` at all are silently skipped
    (both their boxes and their legend entry), rather than drawn as empty.
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
    ax.set_ylabel(wrap_label(ylabel))
    ax.set_xlabel('Year')
    handles = [
        matplotlib.patches.Patch(facecolor=style[t]['color'], alpha=0.6, label=style[t]['display'])
        for t in plot_techs
    ]
    if ref_line is not None:
        handles.append(matplotlib.lines.Line2D([], [], color='0.5', ls='--', lw=1, label=ref_label))
    ax.legend(handles=handles, frameon=False, fontsize=9, loc='upper left', bbox_to_anchor=(1.02, 1))
    reedsplots_style.despine(ax)
    plt.tight_layout()
    plt.savefig(os.path.join(savepath, fname))
    plt.close()


def plot_firm_capacity_contribution_boxplot(fc_df, techs, style, savepath):
    """Box-and-whisker version of firm_capacity_contribution.png: distribution across
    regions per tech per year, rather than the line plot's single national average."""
    _boxplot_by_tech_year(
        fc_df, 'firm_capacity_contribution', techs, style, savepath,
        fname='firm_capacity_contribution_boxplot.png',
        ylabel='Firm capacity contribution by region [-]',
        ref_line=1, ref_label='fully firm (gen = capacity)', ylim_zero=True,
    )


def plot_storage_duration(dur, techs, style, savepath):
    """One line per tech with any storage_duration_out data; non-storage techs (e.g. Gas-CT)
    are silently skipped rather than drawn as an empty line."""
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
    reedsplots_style.despine(ax)
    plt.tight_layout()
    plt.savefig(os.path.join(savepath, 'storage_duration.png'))
    plt.close()


def plot_storage_duration_boxplot(dur_region, techs, style, savepath):
    """Box-and-whisker version of storage_duration.png: distribution across regions per
    tech per year, rather than the line plot's single fleet-wide average."""
    _boxplot_by_tech_year(
        dur_region, 'storage_duration', techs, style, savepath,
        fname='storage_duration_boxplot.png',
        ylabel='Average storage duration by region [hours]',
    )


def plot_dispatch_stress_day(gen, load, label, year, day_label, savepath):
    """
    Single-day stress-period dispatch stack (by tech, GW) with a load line overlay, for one
    region (or aggregate of regions, e.g. an interconnect) and year -- shows what's driving
    (or not driving) that day's reserve-margin price, e.g. a flat/low price usually means
    ample generation capacity relative to load that day.
    """
    d = gen[gen.day_label == day_label]
    if d.empty:
        warnings.warn(f'No dispatch data for {label}, {year}, {day_label}; skipping plot')
        return

    tech_color = reeds.io.get_plot_formatting()['tech_color'].squeeze(1).copy()
    tech_color['Net imports'] = '0.65'
    dfday = d.pivot_table(index='hour', columns='i', values='GW', aggfunc='sum').fillna(0)
    ## Keep a consistent stacking order and drop techs that are zero all day
    dfday = dfday[[c for c in tech_color.index if c in dfday.columns and dfday[c].abs().sum() > 0]]

    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    reedsplots_style.stackbar(dfday, ax, colors=tech_color, net=False, align='center', width=2.6)

    handles = [
        matplotlib.patches.Patch(facecolor=tech_color[c], edgecolor='none', label=c)
        for c in dfday.columns
    ][::-1]
    if not load.empty:
        lday = load[load.day_label == day_label].set_index('hour')['GW'].reindex(dfday.index)
        ax.plot(lday.index, lday.values, color='k', lw=1.75, marker='o', ms=4, label='Load')
        handles.append(matplotlib.lines.Line2D(
            [], [], color='k', lw=1.75, marker='o', ms=4, label='Load'))

    ax.axhline(0, color='0.4', lw=0.8)
    ax.set_title(f'{label}, {year}, {day_label}')
    ax.set_xlabel('Hour of day')
    ax.set_ylabel('GW')
    ax.legend(handles=handles, frameon=False, fontsize=7, loc='upper left', bbox_to_anchor=(1.02, 1))
    reedsplots_style.despine(ax)
    plt.tight_layout()
    plt.savefig(os.path.join(savepath, f'{label}_{year}_{day_label}.png'))
    plt.close()


def plot_stress_period_prices(sub, year, savepath, region=None):
    """
    Small-multiples timeseries of the reserve-margin stress price (national-average, or
    for `region` if given) for each stress period (day) in `year`: one panel per stress
    day, hour-of-day on the x-axis, regular (linear) scale and shared across panels -- so
    the days with genuinely high prices stand out visually, which is what determines
    whether a given storage duration can capture most of a stress day's price, or whether
    it's split across separated peaks.
    """
    label = region if region is not None else 'national'
    if sub.empty:
        warnings.warn(f'No stress-period price data for {label}, year {year}; skipping plot')
        return

    days = sub[['day_label', 'stress_year', 'stress_day']].drop_duplicates().sort_values(
        ['stress_year', 'stress_day'])
    ndays = len(days)
    ncols = min(5, ndays)
    nrows = int(np.ceil(ndays / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(2.4 * ncols, 2.0 * nrows), sharex=True, sharey=True)
    axes = np.atleast_1d(axes).flatten()

    ## Share of the year's total stress price carried by each day -- the same price_sum
    ## used as the denominator weight in compute_firm_capacity_contribution -- so it's easy
    ## to see at a glance which days actually matter for a tech's price-weighted capacity value.
    total_price = sub['price'].sum()
    pct_by_day = sub.groupby('day_label')['price'].sum() / total_price * 100

    for ax, day_label in zip(axes, days['day_label']):
        d = sub[sub.day_label == day_label].sort_values('hour')
        ax.plot(d['hour'], d['price'], marker='o', ms=3, color='0.15', lw=1.1)
        ax.set_title(day_label, fontsize=7.5)
        ax.text(
            0.5, 0.92, f'{pct_by_day[day_label]:.0f}%', transform=ax.transAxes,
            ha='center', va='top', fontsize=7, color='0.35',
        )
        ax.tick_params(labelsize=6.5)
    for ax in axes[ndays:]:
        ax.axis('off')

    fig.supxlabel('Hour of day')
    fig.supylabel(wrap_label(
        f'Reserve margin stress price, {label} {year} [$/kW per stress timeslice]', width=32))
    plt.tight_layout()
    plt.savefig(os.path.join(savepath, f'{label}_{year}.png'))
    plt.close()


def plot_reduced_cost(rc, techs, style, savepath, units):
    fig, ax = plt.subplots(figsize=(6, 4.2))
    for tech in techs:
        sub = rc[rc.i == tech].sort_values('t')
        ax.plot(sub['t'], sub['reduced_cost'], marker='o', color=style[tech]['color'], label=style[tech]['display'])
    ax.axhline(0, color='0.5', ls='--', lw=1)
    ax.set_ylabel(wrap_label(f'Reduced cost on INV [{units}]'))
    ax.set_xlabel('Year')
    ax.legend(frameon=False, fontsize=9)
    reedsplots_style.despine(ax)
    plt.tight_layout()
    plt.savefig(os.path.join(savepath, 'reduced_cost.png'))
    plt.close()


#%% ===========================================================================
### --- VERIFICATION ---
### ===========================================================================
def run_diagnostics(case, techs, first_year, regions=None):
    """Print a handful of tie-out checks against independent outputs.h5 keys. The gross-
    discharge and capex tie-out checks are national by design (sanity-checking this
    script's overall $/MWh accounting, independent of any --region); the refurbishment-
    only-year check below is restricted to `regions` (if given) since it's meant to
    explain what a --region-filtered value/cost-stack plot is actually showing."""
    print('\n--- diagnostics ---')
    ## Gross discharge tie-out: sum(gen_ivrt) should equal stor_inout's 'out' direction,
    ## for any storage tech in `techs`. This is what guarantees the $/MWh denominator is
    ## gross discharge, not net generation.
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

    ## Capex tie-out: lcoe_pieces capcost should be close to systemcost_techba's
    ## inv_investment_capacity_costs (both use the un-annualized INV.l cohort; they can
    ## diverge in years with an active ITC, since lcoe_pieces uses the with-ITC financing
    ## multiplier and systemcost_techba explicitly uses the noITC one).
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

    ## Refurbishment-only years: lcoe_built's own gate (report.gms) only checks INV.l, not
    ## INV_REFURB.l, so a (tech, region, year) whose only capacity addition is a refurbishment
    ## shows real value (valnew includes INV_REFURB.l) but zero reconstructed cost here -- a
    ## bar with value and no cost in the value/cost-stack plot, not a bug in this script.
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
    ## "Refurb-only" allows for float noise: essentially all of that year's new capacity is refurb
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
    case = os.path.abspath(case)
    techs = [t.strip() for t in args.techs.split(',') if t.strip()]
    dollar_year = args.dollar_year
    savepath = args.savepath or os.path.join(
        case, 'outputs', 'plots', f'tech_value_{args.region}' if args.region else 'tech_value')
    os.makedirs(savepath, exist_ok=True)

    reedsplots_style.plotparams()

    ## techs_raw/tech_group_map expand any --techs entry with no exact match (e.g. 'upv') into
    ## its raw resource classes (e.g. upv_1, upv_2, ...) -- every metric below sums/averages
    ## across those classes to get back to one number per group label, see expand_tech_groups.
    techs_raw, tech_group_map = expand_tech_groups(case, techs)
    style = get_tech_style(techs, tech_group_map=tech_group_map)
    value_regions = resolve_regions(case, args.region, level=args.region_level) if args.region else None

    sw = reeds.io.get_switches(case)
    if str(sw.get('GSw_PRM_CapCredit', '0')) == '1':
        warnings.warn(
            'GSw_PRM_CapCredit=1 for this run: val_resmarg and firm_capacity_contribution for '
            'non-VRE techs are not computed the way this script assumes (see report.gms) and '
            'will show as 0/NaN here for any non-VRE tech.'
        )

    df, vn = assemble_value_cost(case, techs_raw, dollar_year, tech_group_map=tech_group_map, regions=value_regions)
    fc_df, fc_nat = compute_firm_capacity_contribution(
        case, techs_raw, tech_group_map=tech_group_map, regions=value_regions)
    dur_df, dur_nat = compute_storage_duration(
        case, techs_raw, tech_group_map=tech_group_map, regions=value_regions)
    ## Solve years before --first-year are fixed to historical/calibration data rather than
    ## optimized, so exclude them here (before the benchmark/value-factor and national-aggregate
    ## calculations) rather than just cropping the plots after the fact.
    df = df[df['t'] >= args.first_year].reset_index(drop=True)
    vn = vn[vn['t'] >= args.first_year].reset_index(drop=True)
    fc_df = fc_df[fc_df['t'] >= args.first_year].reset_index(drop=True)
    fc_nat = fc_nat[fc_nat['t'] >= args.first_year].reset_index(drop=True)
    dur_df = dur_df[dur_df['t'] >= args.first_year].reset_index(drop=True)
    dur_nat = dur_nat[dur_nat['t'] >= args.first_year].reset_index(drop=True)
    df = df.merge(fc_df, on=['i', 'r', 't'], how='left').merge(dur_df, on=['i', 'r', 't'], how='left')
    vf = compute_value_factors(vn, techs)
    rc = load_reduced_cost(case, techs_raw, dollar_year, tech_group_map=tech_group_map, regions=value_regions)
    rc = rc[rc['t'] >= args.first_year].reset_index(drop=True)

    ## National (or, with --region, region) aggregates: sum dollar/MW/MWh numerators across
    ## regions first, never average ratios
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

    ## Empty-frame / case-sensitivity guard. A tech can legitimately be missing here (warned
    ## about in load_valnew) while still present in fc_nat/dur_nat, e.g. a --techs group prefix
    ## like 'upv' that only expand_tech_groups (firm capacity / storage duration) supports --
    ## so value/cost-stack, value-factor, and reduced-cost use techs_value (data-available
    ## subset), while firm-capacity-contribution and storage-duration keep using `techs`.
    for tech in techs:
        if not (nat.i == tech).any():
            warnings.warn(f"No value/cost data assembled for '{tech}' -- omitted from those plots/CSVs")
    techs_value = [t for t in techs if (nat.i == t).any()]

    ## --- write tidy outputs ---
    nat_long = nat.melt(id_vars=['i', 't'], var_name='metric', value_name='value')
    nat_long.to_csv(os.path.join(savepath, 'tech_value_comparison.csv'), index=False)
    df.to_csv(os.path.join(savepath, 'tech_value_by_region.csv'), index=False)
    print(f'Wrote {os.path.join(savepath, "tech_value_comparison.csv")}')
    print(f'Wrote {os.path.join(savepath, "tech_value_by_region.csv")}')

    ## --- figures ---
    ## The CSVs above cover every year from --first-year; the figures start later
    ## (--plot-first-year) purely for legibility, since --first-year's own value/cost figures
    ## are still transitional and dominate the y-axis scale (see --plot-first-year help text).
    nat_plot = nat[nat['t'] >= args.plot_first_year].reset_index(drop=True)
    ## fc_nat/dur_nat (not nat_plot) are the group-aware source for these two metrics: nat_plot
    ## only has rows for techs_value (assemble_value_cost's exact-name-only key space), so a
    ## --techs group prefix like 'upv' -- present in fc_nat/dur_nat but absent from nat -- would
    ## silently disappear from these plots if plotted from nat_plot instead.
    fc_nat_plot = fc_nat[fc_nat['t'] >= args.plot_first_year].reset_index(drop=True)
    dur_nat_plot = dur_nat[dur_nat['t'] >= args.plot_first_year].reset_index(drop=True)

    value_cols = ['gross_energy_value_kwyr', 'firm_capacity_value_kwyr']
    cost_cols = ['annualized_capex_kwyr', 'fomcost_kwyr', 'vomcost_kwyr', 'charge_cost_kwyr']
    nat_kwyr = nat_plot.copy()
    nat_kwyr['net_value'] = nat_plot['net_value_kwyr']
    plot_value_cost_stack(
        nat_kwyr, techs_value, style, savepath, units=f'{dollar_year}$/kW-yr',
        value_cols=value_cols, cost_cols=cost_cols,
        ylabel='Value / cost of new-build capacity', fname='value_cost_stack_kwyr.png',
    )

    value_cols_mwh = ['gross_energy_value_permwh', 'firm_capacity_value_permwh']
    cost_cols_mwh = ['annualized_capex_permwh', 'fomcost_permwh', 'vomcost_permwh', 'charge_cost_permwh']
    nat_mwh = nat_plot.copy()
    nat_mwh['net_value'] = nat_plot['net_value_permwh']
    plot_value_cost_stack(
        nat_mwh, techs_value, style, savepath, units=f'{dollar_year}$/MWh',
        value_cols=value_cols_mwh, cost_cols=cost_cols_mwh,
        ylabel='Value / cost per MWh (gross discharge/generation)', fname='value_cost_stack_mwh.png',
    )

    plot_value_factor(nat_plot, techs_value, style, savepath)
    plot_firm_capacity_contribution(fc_nat_plot, techs, style, savepath)
    plot_firm_capacity_contribution_boxplot(
        fc_df[fc_df['t'] >= args.plot_first_year], techs, style, savepath)

    if args.include_wind:
        wind_ons, wind_ofs = get_wind_techs(case)
        wind_group_map = dict(tech_group_map)
        wind_group_map.update({t: 'Land-Based Wind' for t in wind_ons})
        wind_group_map.update({t: 'Offshore Wind' for t in wind_ofs})
        wind_techs = ['Land-Based Wind', 'Offshore Wind']
        _, fc_nat_wind = compute_firm_capacity_contribution(
            case, techs_raw + wind_ons + wind_ofs, tech_group_map=wind_group_map, regions=value_regions)
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
    plot_storage_duration_boxplot(dur_df[dur_df['t'] >= args.plot_first_year], techs, style, savepath)
    plot_reduced_cost(nat_plot, techs_value, style, savepath, units=f'{dollar_year}$/kW')

    price_savepath = os.path.join(savepath, 'stress_period_prices')
    os.makedirs(price_savepath, exist_ok=True)
    nat_sub, price_year = load_national_stress_period_prices(case, year=args.price_year)
    plot_stress_period_prices(nat_sub, price_year, price_savepath, region=None)

    reg_all, _ = load_regional_stress_period_prices(case, year=price_year)
    regions = [args.price_region] if args.price_region is not None else sorted(reg_all.r.unique())
    for region in regions:
        plot_stress_period_prices(reg_all[reg_all.r == region], price_year, price_savepath, region=region)

    if args.dispatch_region:
        dispatch_savepath = os.path.join(savepath, 'dispatch')
        os.makedirs(dispatch_savepath, exist_ok=True)
        dispatch_regions = resolve_regions(case, args.dispatch_region, level=args.dispatch_level)
        gen, load, dispatch_year = load_dispatch_stress(case, dispatch_regions, year=args.dispatch_year)
        plot_dispatch_stress_day(
            gen, load, args.dispatch_region, dispatch_year, args.dispatch_day, dispatch_savepath)

    print(f'Wrote figures to {savepath}')

    run_diagnostics(case, techs_raw, args.first_year, regions=value_regions)


if __name__ == '__main__':
    main()
