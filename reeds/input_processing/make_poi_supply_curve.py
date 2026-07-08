"""
Build a regional POI / network-reinforcement cost supply curve
(``poi_supply_curve_{GSw_ZoneSet}.csv``) from raw interconnection data.

Input
-----
``raw_interconnection_TSC_data.csv`` with one cumulative supply-curve point per row:

| column         | units  | meaning                                                       |
|----------------|--------|---------------------------------------------------------------|
| ``region``     | -      | ReEDS zone (must match the zone set's hierarchy.csv)          |
| ``capacity_GW``| GW     | cumulative POI capacity at this point                         |
| ``cum_cost_$`` | $      | cumulative reinforcement cost; ``0`` marks existing capacity  |
| ``slope_$/kW`` | $/kW   | marginal cost from the previous point (informational)         |

``capacity_GW`` is in **gigawatts**; ``region_bins`` converts it to MW for the output bin widths
(``width_mw = width_gw * 1000``) and to kW in the marginal-cost denominator (``width_gw * 1e6``).
Cost outputs (``cost`` rows) are in the raw file's input dollar year (USD2024); ReEDS'
``transmission.py`` deflates them to the model dollar year at read time (see dollaryear.csv).

The row where ``cum_cost_$`` is 0 is the zone's **existing capacity** (the free
``poi_cap_init``); only capacity *above* it is binnable. Points at lower capacity than the
existing-capacity anchor are dropped, which handles zones with more existing capacity than the
lowest-capacity point in the raw curve (e.g. p60, p62).

This module's ``make_regional_poi_bins`` is imported by ``transmission.py`` and called at run time
on ``raw_interconnection_TSC_data.csv`` (the single committed source). The command-line entry point
below is a standalone helper for generating/inspecting a curve offline; its ``poi_supply_curve_*``
output is not a committed ReEDS input.

Output
------
Long format (the same schema ``transmission.py`` writes to ``inputs_case/poi_supply_curve.csv``)::

    *r,rtscbin,sc_cat,value
    p60,bin1,cost,<$/kW>
    p60,bin1,cap,<incremental MW>
    ...

``cost`` is the per-bin marginal cost (USD/kW, strictly increasing across bins) and ``cap`` is the
**incremental** bin width (MW). Per-bin cost is capped at the upper POI limit (``--upper-cost``,
default 2000 = ``GSw_POIUpperCost``); anything pricier is covered by the unlimited ``bin_upper``
backstop that ``transmission.py`` appends at runtime, so finite bins never exceed it.

By default each zone is re-binned to ``--numpoibins`` bins (default 5, matching ``cases.csv``) via
the optimal capacity-weighted least-squares segmentation used elsewhere for POI/RSC binning. Pass
``--native`` to instead emit one bin per raw segment (variable bin count per zone).

Usage (run from the repo root; input/output default to ``inputs/transmission/``)
-----
    python -m reeds.input_processing.make_poi_supply_curve --zoneset z134
    python -m reeds.input_processing.make_poi_supply_curve --numpoibins 7 --output poi_supply_curve_z134.csv
    python -m reeds.input_processing.make_poi_supply_curve --native
"""

import argparse
import os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
# POI data files live in inputs/transmission/ at the repo root (this module is in
# reeds/input_processing/, two levels down), so default raw input and outputs resolve there.
TRANS_DIR = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'inputs', 'transmission')


def optimal_bins(costs, widths, nbins):
    """Collapse native segments into ``nbins`` capacity-weighted, piecewise-constant bins.

    ``costs``/``widths`` are the per-segment marginal cost ($/kW) and capacity width (MW). Returns
    ``[(width_mw, cost_per_kw), ...]`` in increasing-cost order, minimizing the capacity-weighted L2
    difference from the native marginal-cost curve (exact DP with prefix sums). ``nbins <= 0`` or
    ``nbins >= n`` returns the native segments unchanged (still sorted by cost).
    """
    costs = np.asarray(costs, dtype=float)
    widths = np.asarray(widths, dtype=float)
    order = np.argsort(costs, kind='mergesort')
    x = costs[order]
    w = widths[order]
    n = len(x)
    if n == 0:
        return []
    if nbins <= 0 or nbins >= n:
        return list(zip(w, x))
    W = np.concatenate([[0.0], np.cumsum(w)])
    WX = np.concatenate([[0.0], np.cumsum(w * x)])
    WX2 = np.concatenate([[0.0], np.cumsum(w * x * x)])

    def sse(a, b):
        sw = W[b] - W[a]
        return 0.0 if sw <= 0 else (WX2[b] - WX2[a]) - (WX[b] - WX[a]) ** 2 / sw

    INF = float('inf')
    dp = np.full((nbins + 1, n + 1), INF)
    cut = np.zeros((nbins + 1, n + 1), dtype=int)
    dp[0, 0] = 0.0
    for k in range(1, nbins + 1):
        for j in range(k, n + 1):
            best, ba = INF, k - 1
            for a in range(k - 1, j):
                v = dp[k - 1, a] + sse(a, j)
                if v < best:
                    best, ba = v, a
            dp[k, j] = best
            cut[k, j] = ba
    bins = []
    j = n
    for k in range(nbins, 0, -1):
        a = cut[k, j]
        sw = W[j] - W[a]
        bins.append((sw, (WX[j] - WX[a]) / sw if sw > 0 else x[a:j].mean()))
        j = a
    return list(reversed(bins))


def region_bins(g, numpoibins, upper_cost, native):
    """Return ``[(width_mw, cost_per_kw), ...]`` POI bins for one zone's raw supply curve.

    The existing-capacity anchor is the (lowest-capacity) row with zero cumulative cost; only
    capacity above it is binned, and lower-capacity rows are discarded.
    """
    g = g.sort_values('capacity_GW')
    # Existing capacity = capacity at which cumulative cost is zero (the free poi_cap_init).
    anchor = g['cum_cost_$'].abs().idxmin()
    existing_cap = g.loc[anchor, 'capacity_GW']
    # Keep the anchor and everything above it; drop below-existing points (handles zones whose
    # existing capacity exceeds the lowest-capacity point in the raw curve).
    above = g.loc[g['capacity_GW'] >= existing_cap].sort_values('capacity_GW')
    # capacity_GW is in GW: read into cap_gw / width_gw and convert to MW (width_mw) and kW (in the
    # marginal-cost denominator) below.
    cap_gw = above['capacity_GW'].to_numpy(dtype=float)
    cum_cost = above['cum_cost_$'].to_numpy(dtype=float)
    width_gw = np.diff(cap_gw)                      # incremental capacity per segment (GW)
    d_cost = np.diff(cum_cost)                       # incremental $ per segment (cost==0 at anchor)
    keep = width_gw > 0
    width_gw = width_gw[keep]
    d_cost = d_cost[keep]
    if len(width_gw) == 0:
        return []
    width_mw = width_gw * 1000.0
    # Marginal cost $/kW = incremental $ / incremental kW; clip to [0, upper_cost] so no finite bin
    # is pricier than the bin_upper backstop (and negatives, if any, are floored at 0).
    marg = np.clip(d_cost / (width_gw * 1e6), 0.0, upper_cost)
    return optimal_bins(marg, width_mw, 0 if native else numpoibins)


def make_regional_poi_bins(raw, numpoibins=5, upper_cost=2000.0, native=False):
    """Convert raw cumulative interconnection data into the long-format POI supply curve.

    ``raw`` is a path or DataFrame with columns ``region, capacity_GW, cum_cost_$, slope_$/kW``.
    Returns a DataFrame with columns ``*r, rtscbin, sc_cat, value`` (cost rows in $/kW, cap rows
    in incremental MW), one bin set per zone.
    """
    df = pd.read_csv(raw) if isinstance(raw, (str, os.PathLike)) else raw.copy()
    rows = []
    for region, g in df.groupby('region', sort=True):
        for k, (width_mw, cost_kw) in enumerate(
                region_bins(g, numpoibins, upper_cost, native), start=1):
            rows.append((region, f'bin{k}', 'cost', round(float(cost_kw), 2)))
            rows.append((region, f'bin{k}', 'cap', round(float(width_mw), 1)))
    return pd.DataFrame(rows, columns=['*r', 'rtscbin', 'sc_cat', 'value'])


def main():
    parser = argparse.ArgumentParser(
        description='Build a regional POI supply curve from raw interconnection data.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        '--raw', default=os.path.join(TRANS_DIR, 'raw_interconnection_TSC_data.csv'),
        help='path to the raw cumulative interconnection-cost CSV')
    parser.add_argument(
        '--numpoibins', type=int, default=5,
        help='number of bins per zone (re-segmented to best fit the raw curve)')
    parser.add_argument(
        '--native', action='store_true',
        help='emit one bin per raw segment instead of --numpoibins bins')
    parser.add_argument(
        '--upper-cost', type=float, default=2000.0,
        help='cap per-bin cost ($/kW) at this upper POI limit (GSw_POIUpperCost)')
    parser.add_argument(
        '--zoneset', default=None,
        help='zone set name; output defaults to poi_supply_curve_{zoneset}.csv')
    parser.add_argument(
        '--output', default=None,
        help='explicit output path (overrides --zoneset)')
    args = parser.parse_args()

    out = make_regional_poi_bins(
        args.raw, numpoibins=args.numpoibins,
        upper_cost=args.upper_cost, native=args.native)

    if args.output:
        outpath = args.output
    elif args.zoneset:
        outpath = os.path.join(TRANS_DIR, f'poi_supply_curve_{args.zoneset}.csv')
    else:
        outpath = os.path.join(TRANS_DIR, 'poi_supply_curve_from_raw.csv')

    out.to_csv(outpath, index=False)
    nbins = out.loc[out['sc_cat'] == 'cost'].groupby('*r').size()
    print(f'Wrote {len(nbins)} zones ({"native" if args.native else f"{args.numpoibins}-bin"}) '
          f'to {outpath}')
    print('Bins per zone:\n' + nbins.to_string())


if __name__ == '__main__':
    main()
