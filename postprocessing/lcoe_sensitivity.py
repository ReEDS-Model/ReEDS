"""
Explore how the LCOE of a technology in a finished ReEDS case would change under a
different capital-cost or capacity-factor assumption, for a chosen region.

ReEDS reports its own LCOE as `lcoe(i,v,r,t,rscbin)`, computed from the run's own capital
cost, financing, O&M, capacity factor, and fuel price assumptions. That value is fixed once
the run finishes; this script lets you ask "what if capital cost were 20% lower" or "what if
capacity factor were 10% higher" without re-running the model.

Methodology
-----------
tech_eval_utils.calibrate_lcoe backs out the fixed-cost residual K that reproduces the run's
own reported `lcoe` exactly (see that module's docstring for the closed form and why K is
calibrated rather than reconstructed). This script then holds K, `cost_vom`, `heat_rate` and
`fuel_price` fixed while scaling capital cost and capacity factor by the user's
--capex-mult/--cf-mult overrides.

So the baseline in the output CSV and figure always matches ReEDS exactly, and only the
*response* to an override carries the approximation.

Usage
-----
    python lcoe_sensitivity.py <path-to-case> --region WI --region-level st
    python lcoe_sensitivity.py <path-to-case> --region WI --region-level st \\
        --techs Gas-CC,upv_1,upv_2,wind-ons_5 \\
        --capex-mult upv_1=0.8,upv_2=0.8 --cf-mult wind-ons_5=1.1

A --techs entry with no exact match (e.g. "upv", the default) is expanded to every
"{entry}_*" resource class with lcoe data in the region, i.e. every class available to build
there rather than only those actually invested in. Pass exact class names to plot a subset.
--capex-mult/--cf-mult accept either an exact class or a bare family name.

Run with --help for the full list of options.

Outputs
-------
Written to {case}/outputs/plots/lcoe_sensitivity/ by default:
- lcoe_sensitivity.csv -- tidy (i, r, t) baseline and scenario LCOE
- lcoe_sensitivity.png -- one panel per tech family, one line per resource class, showing
  the region-average baseline (solid) and scenario (dashed) LCOE by year
"""
import argparse
import os
import sys

import matplotlib
## This script only calls savefig(); an interactive backend can crash without a display
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds
from reeds import plots
import tech_eval_utils as teu


#%% ===========================================================================
### --- ARGUMENTS ---
### ===========================================================================
def parse_args():
    parser = argparse.ArgumentParser(
        description='Explore LCOE sensitivity to capital cost and capacity factor assumptions.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    teu.add_case_arg(parser)
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
            'the requested region; pass exact classes to plot only a subset'
        ),
    )
    teu.add_region_args(
        parser, extra_help='Plotting every region at once is rarely useful; expect a lot of output.')
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
    return args, teu.resolve_case(args)


def parse_mult_overrides(overrides):
    """Parse 'TECH=MULT,TECH=MULT' into {TECH: float(MULT)}."""
    out = {}
    for item in overrides.split(','):
        item = item.strip()
        if not item:
            continue
        tech, val = item.split('=')
        out[tech.strip()] = float(val)
    return out


def resolve_mult(tech, overrides, tech_family):
    """Look up an override for `tech`, falling back to its family and then to 1.0."""
    if tech in overrides:
        return overrides[tech]
    return overrides.get(tech_family.get(tech, tech), 1.0)


#%% ===========================================================================
### --- CORE CALCULATION ---
### ===========================================================================
def compute_lcoe_sensitivity(case, techs, tech_family, regions, capex_mult, cf_mult, first_year):
    """
    Recompute LCOE with the user's capex/CF multipliers applied, against the calibrated
    baseline from tech_eval_utils.calibrate_lcoe. Both LCOE columns are in the run's native
    2004$/MWh; inflate them separately for display.
    """
    df = teu.calibrate_lcoe(case, techs, regions=regions, first_year=first_year)

    df['capex_mult'] = df['i'].map(lambda i: resolve_mult(i, capex_mult, tech_family))
    df['cf_mult'] = df['i'].map(lambda i: resolve_mult(i, cf_mult, tech_family))
    df['cost_cap_scenario'] = df['cost_cap'] * df['capex_mult']
    df['cf_scenario'] = df['cf_baseline'] * df['cf_mult']
    df['lcoe_scenario'] = teu.lcoe_from_parts(
        df['crf'], df['fin_mult'], df['cost_cap_scenario'], df['K'],
        df['cf_scenario'], df['cost_vom'], df['fuel_term'],
    )

    return df[[
        'i', 'r', 't', 'lcoe_baseline', 'lcoe_scenario', 'cf_baseline', 'cf_scenario',
        'cost_cap', 'cost_cap_scenario', 'capex_mult', 'cf_mult',
    ]].reset_index(drop=True)


#%% ===========================================================================
### --- PLOTTING ---
### ===========================================================================
def get_tech_style(techs, tech_family):
    """
    Display name and color per raw tech: one base color per family, then a distinct shade per
    resource class so classes sharing a panel stay distinguishable.
    """
    fmt = reeds.io.get_plot_formatting()
    tech_map, tech_color = fmt['tech_map'], fmt['tech_color']['color']
    fallback_colors = plt.rcParams['axes.prop_cycle'].by_key()['color']

    families = list(dict.fromkeys(tech_family[t] for t in techs))
    style = {}
    for n, family in enumerate(families):
        base, display = teu.get_family_color(
            family, tech_map, tech_color, fallback=fallback_colors[n % len(fallback_colors)])
        members = sorted((t for t in techs if tech_family[t] == family), key=teu.class_sort_key)
        for tech, color in zip(members, teu.shade_colors(base, len(members), lighten=0.6)):
            style[tech] = {'display': display, 'family': family, 'color': color}
    return style


def plot_lcoe_sensitivity(df, techs, tech_family, style, savepath, units, has_override):
    """
    One panel per family, one line per resource class, to show the range of LCOE across
    classes. Each line is the unweighted mean across `regions` of the baseline (solid) and,
    if any override was given, scenario (dashed) LCOE; per-region detail stays in the CSV.
    """
    families = list(dict.fromkeys(tech_family[t] for t in techs))
    fig, axes = plt.subplots(1, len(families), figsize=(4.5 * len(families), 4.5), sharey=False)
    axes = np.atleast_1d(axes)

    for ax, family in zip(axes, families):
        members = sorted((t for t in techs if tech_family[t] == family), key=teu.class_sort_key)
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
        plots.despine(ax)
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
    techs_input = teu.parse_techs(args.techs)
    capex_mult = parse_mult_overrides(args.capex_mult)
    cf_mult = parse_mult_overrides(args.cf_mult)
    has_override = bool(capex_mult or cf_mult)
    regions = teu.resolve_regions(case, args.region, level=args.region_level)
    savepath = args.savepath or os.path.join(case, 'outputs', 'plots', 'lcoe_sensitivity')
    os.makedirs(savepath, exist_ok=True)

    plots.plotparams()

    techs, _ = teu.expand_tech_classes(case, techs_input, output='lcoe', regions=regions)
    ## Each raw tech is plotted on its family's panel, e.g. upv_1 and upv_2 both on 'upv'
    tech_family = {t: teu.get_tech_family(t) for t in techs}
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
