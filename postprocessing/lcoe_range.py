"""
LCOE ranges/scenarios for a chosen region of a finished ReEDS case:

- Gas-CC (or any non-resource-constrained tech via --gas-tech): two scenario lines, each
  with a +/-X% fuel-price band (--fuel-price-pct) -- the run's own capital cost, and a
  second scenario with a flat $/kW capital-cost increase (--capex-add).
- UPV / wind-ons: two scenario bands, each spanning the min-to-max LCOE across every
  resource class present in the region (the capacity-factor-driven spread across classes,
  not the individual class lines) -- one under the run's own ATB cost assumption, one under
  a separate (typically higher-cost) ATB cost file (--upv-conservative/--wind-conservative).

Each scenario is built on tech_eval_utils.calibrate_lcoe, which reproduces the run's own
reported `lcoe` exactly at baseline; see that module's docstring for the derivation.

ATB conservative-cost scaling
------------------------------
The raw ATB cost files in inputs/plant_characteristics/ are a constant multiple of the
processed inputs_case/plantcharout.csv capital cost, in every year, so their absolute values
cannot be used directly. Instead this script computes

    capex_ratio(t) = raw_conservative_capcost(t) / raw_moderate_capcost(t)

from the two raw files -- the moderate file coming from the case's own plantchar_upv /
plantchar_onswind switch -- and applies it to both the run's processed capital cost and the
calibrated K (FOM plus site cost), since K cannot be decomposed into a separate FOM piece.
The capital-cost shift is therefore exact and the FOM shift approximate: FOM's own
conservative/moderate ratio tracks capex's closely but not exactly, e.g. 1.20 vs 1.31 at
2035 for UPV. Capacity factor is left at the run's own resource profiles, since the ATB
files' CF_mult/cf_improvement columns are a turbine/module vintage factor rather than a
resource-class CF.

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
import sys

import matplotlib
## This script only calls savefig(); an interactive backend can crash without a display
matplotlib.use('Agg')
import matplotlib.pyplot as plt
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
        description=(
            'LCOE ranges: fuel-price/capex-adder scenarios for a non-RSC tech, and '
            'resource-class + ATB-cost-scenario ranges for UPV/wind-ons.'
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    teu.add_case_arg(parser)
    parser.add_argument(
        '--savepath', type=str, default=None,
        help='output directory (default: {case}/outputs/plots/lcoe_range)',
    )
    teu.add_region_args(parser, required=True)
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
    return args, teu.resolve_case(args)


#%% ===========================================================================
### --- DATA LOADING ---
### ===========================================================================
def resolve_input_path(path):
    """Resolve an ATB cost file given relative to the repo root, or as an absolute path."""
    full = path if os.path.isabs(path) else os.path.join(reeds.io.reeds_path, path)
    if not os.path.isfile(full):
        raise FileNotFoundError(
            f'ATB cost file not found: {full}. Pass an existing file from '
            'inputs/plant_characteristics/ -- the defaults track a specific ATB vintage.'
        )
    return full


def load_capex_ratio(case, moderate_switch, conservative_path):
    """
    Ratio of conservative- to moderate-scenario raw capital cost by year, from the two ATB
    plant-characteristics files. `moderate_switch` is the case's own plantchar_upv /
    plantchar_onswind switch value, so the comparison always uses whichever moderate scenario
    the run actually used.
    """
    moderate_path = os.path.join(
        reeds.io.reeds_path, 'inputs', 'plant_characteristics', f'{moderate_switch}.csv')
    mod = pd.read_csv(moderate_path)
    cons = pd.read_csv(conservative_path)
    ## UPV-style files are (t, capcost, ...); wind-style files are (Turbine, Year, ...)
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
    Two scenarios for a non-RSC tech: the run's own capital cost, and that plus capex_add_kw
    ($/kW, dollar_year$). Each is evaluated at fuel-price multipliers of 1 -+ fuel_pct/100,
    so the fuel_mult == 1 rows are the scenario's line and the full spread is its band.
    """
    if teu.get_fuel_column(tech.lower()) is None:
        raise ValueError(
            f"'{tech}' has no recognized fuel -- check tech_eval_utils.FUEL_COLUMN_BY_PREFIX")
    df = teu.calibrate_lcoe(
        case, [tech], regions=regions, first_year=first_year, last_year=last_year)

    ## capex_add_kw is $/kW in dollar_year$; the LCOE formula works in $/MW in native 2004$
    capex_add = capex_add_kw * 1000 * teu.get_deflator(dollar_year)

    rows = []
    for scenario, cost_cap_add in [('ATB Moderate', 0.0), (f'+${capex_add_kw:.0f}/kW capex', capex_add)]:
        for fuel_mult in sorted({1 - fuel_pct / 100, 1.0, 1 + fuel_pct / 100}):
            lcoe = teu.lcoe_from_parts(
                df['crf'], df['fin_mult'], df['cost_cap'] + cost_cap_add, df['K'],
                df['cf_baseline'], df['cost_vom'], df['fuel_term'] * fuel_mult,
            )
            rows.append(pd.DataFrame({
                'family': tech, 'scenario': scenario, 'fuel_mult': fuel_mult,
                'r': df['r'], 't': df['t'], 'lcoe': lcoe,
            }))
    out = pd.concat(rows, ignore_index=True)
    out['lcoe'] = reeds.results.inflate_series(out['lcoe'], to_dollar_year=dollar_year)
    return out


def compute_rsc_scenarios(case, prefix, regions, capex_ratio, dollar_year, first_year, last_year):
    """
    Two scenarios for every resource class of an RSC family present in `regions`: the run's
    own (ATB moderate) cost, and ATB Conservative, scaled by capex_ratio. The min-to-max
    spread across classes is each scenario's band.
    """
    classes, _ = teu.expand_tech_classes(case, [prefix], output='lcoe', regions=regions)
    df = teu.calibrate_lcoe(
        case, classes, regions=regions, first_year=first_year, last_year=last_year)

    ratio_by_year = df['t'].map(capex_ratio)
    if ratio_by_year.isna().any():
        missing = sorted(df.loc[ratio_by_year.isna(), 't'].unique())
        raise ValueError(f'The ATB cost files have no capital cost for solve year(s) {missing}')

    rows = []
    for scenario, mult in [('ATB Moderate', 1.0), ('ATB Conservative', ratio_by_year)]:
        lcoe = teu.lcoe_from_parts(
            df['crf'], df['fin_mult'], df['cost_cap'] * mult, df['K'] * mult,
            df['cf_baseline'], df['cost_vom'], df['fuel_term'],
        )
        rows.append(pd.DataFrame({
            'family': prefix, 'scenario': scenario, 'i': df['i'], 'r': df['r'], 't': df['t'], 'lcoe': lcoe,
        }))
    out = pd.concat(rows, ignore_index=True)
    out['lcoe'] = reeds.results.inflate_series(out['lcoe'], to_dollar_year=dollar_year)
    return out


#%% ===========================================================================
### --- PLOTTING ---
### ===========================================================================
def plot_lcoe_range(dfgas, dfupv, dfwind, savepath, units, gas_tech):
    panels = [
        (dfgas, gas_tech, 'fuel_mult'),
        (dfupv, 'upv', None),
        (dfwind, 'wind-ons', None),
    ]
    fmt = reeds.io.get_plot_formatting()
    tech_map, tech_color = fmt['tech_map'], fmt['tech_color']['color']
    fig, axes = plt.subplots(1, len(panels), figsize=(5.2 * len(panels), 4.5), sharey=False)
    axes = np.atleast_1d(axes)

    for ax, (df, family, band_col) in zip(axes, panels):
        base, display = teu.get_family_color(family, tech_map, tech_color)
        scenarios = list(dict.fromkeys(df['scenario']))
        ## scenarios[0] is the cheaper (ATB Moderate) case, so reverse shade_colors' light-to-
        ## dark order to put the darker shade on it. Lines are lightened less than fills, since
        ## a fill's pale shade reads fine as an area but washes out as a line.
        fill_shades = teu.shade_colors(base, len(scenarios))[::-1]
        line_shades = teu.shade_colors(base, len(scenarios), lighten=0.35)[::-1]
        for scenario, fill_color, line_color in zip(scenarios, fill_shades, line_shades):
            sub = df[df.scenario == scenario]
            band = sub.groupby('t')['lcoe'].agg(['min', 'max', 'mean'])
            years = band.index
            ax.fill_between(years, band['min'], band['max'], color=fill_color, alpha=0.35, lw=0)
            center = band['mean'] if band_col is None else sub.loc[sub[band_col] == 1.0].groupby('t')['lcoe'].mean()
            ax.plot(years, center.reindex(years), color=line_color, marker='o', ms=4, lw=1.75, label=scenario)
        ## LCOE bands never approach zero, so a bottom-anchored legend stays clear of them
        ax.set_ylim(bottom=0)
        ax.set_title(display)
        ax.set_xlabel('Year')
        ax.set_ylabel(f'LCOE [{units}]')
        ax.legend(frameon=False, fontsize=8, loc='lower left')
        plots.despine(ax)

    plt.tight_layout()
    plt.savefig(os.path.join(savepath, 'lcoe_range.png'))
    plt.close()


#%% ===========================================================================
### --- MAIN ---
### ===========================================================================
def main():
    args, case = parse_args()
    savepath = args.savepath or os.path.join(case, 'outputs', 'plots', 'lcoe_range')
    os.makedirs(savepath, exist_ok=True)

    plots.plotparams()
    regions = teu.resolve_regions(case, args.region, level=args.region_level)
    switches = reeds.io.get_switches(case)

    dfgas = compute_gas_scenarios(
        case, args.gas_tech, regions, args.fuel_price_pct, args.capex_add,
        args.dollar_year, args.first_year, args.last_year,
    )
    upv_ratio = load_capex_ratio(
        case, switches['plantchar_upv'], resolve_input_path(args.upv_conservative))
    wind_ratio = load_capex_ratio(
        case, switches['plantchar_onswind'], resolve_input_path(args.wind_conservative))

    dfupv = compute_rsc_scenarios(
        case, 'upv', regions, upv_ratio, args.dollar_year, args.first_year, args.last_year)
    dfwind = compute_rsc_scenarios(
        case, 'wind-ons', regions, wind_ratio, args.dollar_year, args.first_year, args.last_year)

    dfall = pd.concat([dfgas, dfupv, dfwind], ignore_index=True)
    dfall.to_csv(os.path.join(savepath, 'lcoe_range.csv'), index=False)
    print(f'Wrote {os.path.join(savepath, "lcoe_range.csv")}')

    plot_lcoe_range(dfgas, dfupv, dfwind, savepath, units=f'{args.dollar_year}$/MWh', gas_tech=args.gas_tech)
    print(f'Wrote {os.path.join(savepath, "lcoe_range.png")}')


if __name__ == '__main__':
    main()
