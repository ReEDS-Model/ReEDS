'''This file creates three figures with subfigures of LCOE_base vs year, cost factor vs market share, and alternative value/cost-factor views (top), plus example PLCOE vs market share curves for select years (bottom), with lines for each tech. The third figure is the value/cost-factor view using the adjusted cost factor and LCOE base; its bottom row is unadjusted because the adjustment cancels in PLCOE.

Run this file on the reeds2 conda environment. It is also imported by run_report_valcostfac.py, which
calls make_figs() so the figures land in the report's output_dir alongside valcostfac_core.csv. Run it
standalone (editing valcostfac_core_path below) to re-render the figures without rebuilding the report.
'''
import os
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from scipy.optimize import curve_fit
from scipy.stats import linregress
from report_switches import (dollar_year, lcoe_base_dollar_year, start_year,
                             tech_display_names)

# User inputs
valcostfac_core_path = '/data/shared/projects/mmowers/ReEDS/postprocessing/bokehpivot/out/reeds_report/valcostfac_core.csv' #Only used when running this file standalone; run_report_valcostfac.py passes its own path.
years = [2030, 2040, 2050]
max_plcoe = 200
max_cost_value_factor = 5
inv_value_factor_ylim = (0.8, 3)
cost_factor_ylim = (0.8, 3)
fit_techs = ['Onshore Wind','UPV'] #Techs given a dotted OLS fit vs market share on the value/cost-factor figures.
vcf_techs = None #Techs on the value-cost-factor figures. None takes every tech in the results that clears vcf_min_anchor_gen_frac, which brings in the dispatchable techs; the contrast is the point, since their bands are far thinner than the VRE ones (nuclear's k_vcf - k_vf is 0.08 against 0.54 for wind). Set a list to override.
vcf_max_cols = 3 #Panels per row on the value-cost-factor figures before wrapping to a new row.
vcf_min_anchor_gen_frac = 0.5 #A tech is only plotted if its data reaches this low a market share. The figure matches the VF and VCF fit intercepts AT x=0, so a tech whose data never approaches zero has that match, and the whole shaded band, extrapolated rather than measured. At 0.5 every tech in these results qualifies; Gas-CC is the marginal one at 0.463.
vcf_anchor_warn_gen_frac = 0.25 #Panels whose data starts above this market share get the extrapolation noted in the panel box. Gas-CC starts at 0.463, so nearly half its plotted axis - including the matched intercept the whole construction rests on - is extrapolation.
vcf_post_curtailment = True #Also write plcoe_pitch_VCF_power_synced_postcurt.png, the synced VCF figure with VRE value and cost per MWh actually generated rather than per MWh that could have been. Both LVOE and the re-based LCOE are per uncurtailed MWh (valnew's gen_ivrt_uncurt override), while dispatchable techs are per MWh dispatched; this sensitivity puts every tech on the dispatched basis. Value factor and cost factor each scale by 1/(1 - curtailment) and the value-cost factor is unchanged to machine precision - only the split between value and cost moves. The multiplier is NEW-BUILD curtailment over the valinv vintages, which is what valnew's MWh actually is: it runs 2-3x the fleet figure (wind 70% against 40% at 2050), because the marginal unit lands in an already-saturated region. The convention of Hirth and of most of the LBNL value work is the uncurtailed basis, so this is a sensitivity rather than the headline.
vcf_available_basis = True #Write a third VCF figure putting EVERY tech per MWh available rather than per MWh delivered, so VRE and non-VRE are treated alike. The default basis is mixed - VRE per MWh the resource could have produced, dispatchables per MWh dispatched - and the post-curtailment figure resolves that the other way, by putting everything per MWh generated. Available energy is the right-hand side of eq_capacity_limit in both cases: m_cf*CAP for VRE, which is gen_ivrt_uncurt, and avail*CAP for dispatchables, where avail is the forced- and planned-outage derate reported as avg_avail. Note what this does and does not mean: a peaker's unused availability is capacity held for scarcity, not output nobody wanted, so a low value here is not the same finding as it is for VRE.
avail_basis_prefix = {'Onshore Wind': 'wind-ons', 'UPV': 'upv', 'Gas-CC': 'gas-cc',
                      'Coal': 'coal', 'Nuclear': 'nuclear', 'Battery': 'battery'} #Report tech -> raw tech prefix in the run outputs, for the available-energy basis. Techs absent here keep their default basis.
avail_basis_resource_techs = ['Onshore Wind', 'UPV'] #Techs whose available energy is resource-limited (gen_ivrt_uncurt) rather than outage-limited (avg_avail * cap_ivrt). These are already on the available basis by default, so their multiplier is 1 and they are listed only to route them to the right source.
cc_scenario_techs = ['Battery', 'UPV'] #Techs whose new-build capacity credit is also drawn in every scenario in the scenarios file, not only in the run that forces them, to separate a tech's own saturation from the system around it. Names as in valcostfac_core.csv; each needs an entry in avail_basis_prefix.
cc_scenario_min_new_gw = 1.0 #In the all-scenario capacity-credit figure, drop a year where the tech added less than this many GW. In the thermal-forced runs storage adds a few hundred MW in some years, and the credit of so little capacity swings between 0.75 and 0.98 on which one or two regions happened to build.
vcf_separate_techs = ['Battery'] #Techs drawn in their own figure rather than alongside the rest. Storage sits in a different part of the plane - value factor above 1, market share topping out near 15% - so sharing a figure with it stretches every other panel's axes to accommodate one corner. These techs are dropped from the main VCF figures and written to plcoe_pitch_VCF_power_storage.png instead; they stay in the fits table, which has no axis to distort. Empty list to keep everything in one figure.
vcf_use_full_range = True #Read the VCF figures' data from valcostfac.csv rather than valcostfac_core.csv, which report_switches' gen_frac_max truncates at 0.65 market share. That cap is scoped to the intermediary "lim" plots and badly distorts these figures: it removes 4 coal points, 7 gas-CC, 6 nuclear and 1 wind, and with them most of the dispatchable techs' escalation. Filtered, nuclear's k difference reads -0.00 and gas-CC's 0.56 on an R2-0.24 fit; over the full range they are 0.08 (R2 0.77) and 0.05 (R2 0.86). Only the VCF figures can use it - the _adj figures need value_cost_factor_adj and cost_factor_adj, which run_report_valcostfac.py derives after the cap and writes only to valcostfac_core.csv.
show_cost_factor = True #On the VCF figures, also plot the cost factor as context alongside value factor and value-cost factor.
cost_factor_direct = False #False plots 1/(cost factor), which declines like the other two series and peaks near 1.0, keeping the shaded band legible. True plots the cost factor itself, which rises so it reads as escalation directly and ends at the number quoted in the panel text, but reaches ~2.2 and so roughly halves the band's share of the axis (wind 10.8% -> 5.7%, UPV 3.7% -> 2.0%).
show_cost_factor_fit = True #Draw the cost-factor curve implied by the VF and VCF fits, alongside the cost-factor data. It is the ratio of the two fits, not a fit of its own, so it is exactly the curve the shaded band asserts. Note the fitted ratio and the data part company at high market share for UPV - 0.70 implied against 0.45 observed - which is a real limitation of describing a ratio by the ratio of two fits; both numbers are in plcoe_pitch_vcf_scales.csv. Only has an effect when show_cost_factor is on.

this_dir = os.path.dirname(os.path.abspath(__file__))
tech_style_path = os.path.join(this_dir, 'in', 'reeds2', 'tech_style.csv')
lcoe_base_path = os.path.join(this_dir, 'LCOE_base.csv')
deflator_path = os.path.join(this_dir, os.pardir, os.pardir, 'inputs', 'financials', 'deflator.csv')
deflator = pd.read_csv(deflator_path, index_col='*Dollar.Year')['Deflator']
lcoe_usd_mult = deflator.loc[lcoe_base_dollar_year] / deflator.loc[dollar_year] #Matches run_report_valcostfac.py's conversion of the same file.
reeds_native_dollar_year = 2004 #Dollar year of ReEDS output csvs as written by report_dump.py; bokehpivot's reports inflate from it.
reeds_usd_mult = deflator.loc[reeds_native_dollar_year] / deflator.loc[dollar_year] #For $ values read straight from a run's outputs folder rather than from report.xlsx.
usd_label = f'{dollar_year}$/MWh'
#run_report_valcostfac.py's import chain calls reeds.plots.plotparams(), which globally sets bold
#x-large axis labels and larger ticks. Rendering under matplotlib defaults keeps these figures
#identical whether this file is run standalone or from the report. 'backend' is excluded so the
#active backend isn't swapped out mid-run.
default_rc = {k: v for k, v in matplotlib.rcParamsDefault.items() if k != 'backend'}
cost_color = '0.35' #Neutral grey for everything cost-side, so it reads as distinct from the tech-coloured value series.


def display_tech(tech):
    """The label to print for a tech, per tech_display_names. Identity if it has no entry."""
    return tech_display_names.get(tech, tech)


def prep_data(valcostfac_core_path):
    """Load the core value/cost factors and LCOE base, and derive the plotted columns."""
    df = pd.read_csv(valcostfac_core_path)
    df['cost_value_factor'] = 1 / df['value_cost_factor']
    df['inv_value_factor'] = 1 / df['value_factor']
    df['inv_cost_factor'] = 1 / df['cost_factor']
    df['cost_value_factor_adj'] = 1 / df['value_cost_factor_adj']
    df['inv_cost_factor_adj'] = 1 / df['cost_factor_adj']

    #LCOE_base.csv is read raw rather than using valcostfac_core's lcoe_base, which is scaled by
    #force_mult and net of the PTC and so varies by scenario. Applying only the currency conversion
    #reproduces valcostfac_core's lcoe_base_orig, so these columns carry the "orig" name to match.
    df_lcoe = pd.read_csv(lcoe_base_path).rename(columns={'lcoe_base': 'lcoe_base_orig'})
    df_lcoe['lcoe_base_orig'] = df_lcoe['lcoe_base_orig'] * lcoe_usd_mult

    #run_report_valcostfac.py's adjustment divides cost_factor by a per-tech constant and multiplies
    #LCOE base by that same constant, so the two cancel in PLCOE. Recover the constant per tech and
    #apply it to get the adjusted LCOE trajectory, reproducing valcostfac_core's lcoe_base_orig_adj
    #(not lcoe_base_adj, which carries force_mult and the PTC). Techs outside the core set get NaN
    #and are not plotted.
    tech_scale = (df['cost_factor'] / df['cost_factor_adj']).groupby(df['tech']).first()
    df_lcoe['lcoe_base_orig_adj'] = df_lcoe['lcoe_base_orig'] * df_lcoe['tech'].map(tech_scale)

    df_lcoe_sel = df_lcoe[df_lcoe['year'].isin(years)].copy()
    df_lcoe_sel = df_lcoe_sel.pivot_table(index='tech', columns='year', values='lcoe_base_orig')
    df_lcoe_sel.columns = ['lcoe_base_orig_' + str(c) for c in df_lcoe_sel.columns]
    df_lcoe_sel.reset_index(inplace=True)

    df = df.merge(df_lcoe_sel, how='left', on='tech')

    for year in years:
        df[f'plcoe_{year}'] = df[f'lcoe_base_orig_{year}'] * df['cost_value_factor']

    return df, df_lcoe


def tech_fit(df, col, tech, form='linear'):
    """OLS fit of col vs gen_frac for one tech, in one of three forms:

      'linear'  y = slope*x + intercept
      'exp'     y = A*exp(m*x),    fit as ln(y) vs x            (A = exp(intercept), m = slope)
      'power'   y = A*(1-x)**k,    fit as ln(y) vs ln(1-x)      (A = exp(intercept), k = slope)

    'power' is the preferred form: it reaches zero at 100% market share rather than asymptoting
    ('exp') or crossing zero at an arbitrary point ('linear'), and k is an elasticity with respect to
    the remaining non-served share. Both log forms leave their slope unchanged when y is rescaled,
    and both make the slopes exactly additive across a product of metrics.

    Returns (linregress result, rows actually fitted), or None without enough usable points.
    Non-positive values are dropped before a log fit, as is x >= 1 for the power form.

    Note that linregress' own rvalue**2 is the fit quality in the TRANSFORMED space, so it is not
    comparable across forms. Use fit_r2_y for a like-for-like comparison in the original units."""
    d = df[df['tech'] == tech].dropna(subset=['gen_frac', col])
    if form in ('exp', 'power'):
        d = d[d[col] > 0]
    if form == 'power':
        d = d[d['gen_frac'] < 1]
    if len(d) < 2:
        return None
    x = np.log(1 - d['gen_frac']) if form == 'power' else d['gen_frac']
    y = np.log(d[col]) if form in ('exp', 'power') else d[col]
    return linregress(x, y), d


def fit_predict(lr, x, form):
    """Predicted y in original units from a fit of the given form."""
    if form == 'linear':
        return lr.intercept + lr.slope * x
    if form == 'exp':
        return np.exp(lr.intercept) * np.exp(lr.slope * x)
    if form == 'power':
        return np.exp(lr.intercept) * (1 - x) ** lr.slope
    raise ValueError(f'unknown form: {form}')


def r2_y(y, yhat):
    """R^2 in the ORIGINAL units of y, so different fitting methods compare like for like. A
    log-space R^2 rewards proportional accuracy and flatters forms fitted in logs, which is
    misleading next to a curve the reader is judging by eye in y space."""
    ss_tot = ((y - y.mean()) ** 2).sum()
    if ss_tot == 0:
        return np.nan
    return 1 - ((y - yhat) ** 2).sum() / ss_tot


def fit_r2_y(lr, d, col, form):
    """r2_y for one of the linregress-based fits."""
    return r2_y(d[col].to_numpy(), fit_predict(lr, d['gen_frac'].to_numpy(), form))


def power_model(x, A, k):
    """y = A*(1-x)**k, the form fitted by tech_fit_nls."""
    return A * (1 - x) ** k


def tech_fit_nls(df, col, tech):
    """Nonlinear least-squares fit of y = A*(1-x)**k in the ORIGINAL units of y.

    Unlike the log-space 'power' fit this minimises absolute error, so the curve tracks the points as
    drawn. The trade-off is that exponents are no longer exactly additive across a product of
    metrics: k for value_cost_factor is not k(value_factor) + k(inv_cost_factor). Take the cost term
    as the difference between the value_factor and value_cost_factor exponents rather than fitting
    inv_cost_factor and adding, so there is only ever one answer (see summarize_fits).

    k remains invariant when y is rescaled, since a constant multiplier is absorbed by A.

    Returns (A, k, rows fitted), or None without enough usable points."""
    d = df[df['tech'] == tech].dropna(subset=['gen_frac', col])
    d = d[d['gen_frac'] < 1]
    if len(d) < 2:
        return None
    seed = tech_fit(df, col, tech, form='power')
    p0 = [1.0, 1.0] if seed is None else [np.exp(seed[0].intercept), seed[0].slope]
    try:
        (amp, k), _ = curve_fit(power_model, d['gen_frac'].to_numpy(), d[col].to_numpy(),
                                p0=p0, maxfev=20000)
    except (RuntimeError, TypeError, ValueError):
        return None
    return amp, k, d


def add_tech_fits(ax, df, col, colors, techs):
    """Overlay OLS fits vs market share and annotate each with its equation.

    Two fits per tech: a dotted straight line (linear in level) and a dash-dot curve of the form
    y = A*(1-x)**k fitted by nonlinear least squares in y space, so both track the points as drawn
    and their R^2 values (both in the original units of y) are comparable with each other.

    Each panel gets its own fit, including the cost-factor panel. Only the value-factor and
    value-cost-factor exponents are used for the steepness claims; the cost-factor exponent is a
    description of the cost data on its own terms, and must not be added to the value-factor exponent
    to reconstruct the value-cost-factor one. See summarize_fits."""
    labels = []
    for tech in techs:
        fit = tech_fit(df, col, tech)
        if fit is None:
            continue
        lr, d = fit
        xs = np.array([d['gen_frac'].min(), d['gen_frac'].max()])
        ax.plot(
            xs,
            lr.intercept + lr.slope * xs,
            color=colors[tech],
            linestyle=':',
            linewidth=2.0,
            zorder=6,
        )
        r2 = fit_r2_y(lr, d, col, 'linear')
        labels.append((tech, f'{tech} (lin): y = {lr.slope:.2f}x + {lr.intercept:.2f}  (R$^2$={r2:.2f})'))

        nls = tech_fit_nls(df, col, tech)
        if nls is None:
            continue
        amp, k, dn = nls
        xs_pow = np.linspace(dn['gen_frac'].min(), dn['gen_frac'].max(), 50)
        ax.plot(
            xs_pow,
            power_model(xs_pow, amp, k),
            color=colors[tech],
            linestyle='-.',
            linewidth=1.4,
            alpha=0.9,
            zorder=6,
        )
        nr2 = r2_y(dn[col].to_numpy(), power_model(dn['gen_frac'].to_numpy(), amp, k))
        labels.append((tech, f'{tech} (pow): y = {amp:.2f}(1-x)$^{{{k:.2f}}}$  (R$^2$={nr2:.2f})'))

    #Equations sit along the top, which these declining curves leave clear. The translucent backing
    #keeps them readable if a curve does run underneath.
    for i, (tech, label) in enumerate(labels):
        ax.text(
            0.03,
            0.98 - 0.07 * i,
            label,
            transform=ax.transAxes,
            fontsize=6.5,
            color=colors[tech],
            va='top',
            ha='left',
            zorder=7,
            bbox={'facecolor': 'white', 'edgecolor': 'none', 'alpha': 0.75, 'pad': 1.5},
        )
    return labels


def summarize_fits(df, techs=None):
    """Fit each plotted metric vs market share, and derive the steepness claim from the value-factor
    and value-cost-factor fits alone.

    nls_k, the exponent of y = A*(1-x)**k fitted in y space, is the reported measure. It is invariant
    to rescaling (a constant multiplier is absorbed by A), so it does not depend on the _adj
    convention, and the curve tracks the plotted points.

    The decomposition columns are populated ONLY on the value_cost_factor rows, because the split
    between value decline and cost escalation is a property of the value-factor/value-cost-factor
    pair, not of any single metric:

        k_ratio_vs_value_factor  = k(VCF) / k(VF)      - "VCF declines this much faster than VF"
        k_cost_derived           = k(VCF) - k(VF)      - the cost term, by difference
        cost_share_of_decline    = k_cost_derived / k(VCF)

    inv_cost_factor is still fitted, and its nls_k is the better description of the cost data on its
    own terms, but it deliberately carries no ratio column. Under nonlinear least squares the
    exponents are NOT additive - k(VF) + k(inv_cost_factor) does not equal k(VCF) - so adding them is
    the one arithmetic to avoid. Deriving the cost term by difference keeps a single answer.

    power_k is the same functional form fitted in log space instead. It is retained as a cross-check:
    that fit is exactly additive, so agreement between power_k_ratio_vs_value_factor and
    k_ratio_vs_value_factor indicates the result does not hinge on the fitting method. Divergence
    indicates the power form does not describe that tech across the whole range.

    Fit quality is reported in two spaces which must not be mixed. The *_r2_y columns are in the
    original units of y and are the only ones comparable across methods. power_r2_log is the
    transformed-space R^2 that the log regression maximises, which rewards proportional accuracy and
    runs higher; it is why a log-space fit can look good numerically yet miss the plotted points."""
    techs = fit_techs if techs is None else techs
    cols = ['value_factor','inv_cost_factor','value_cost_factor','inv_cost_factor_adj','value_cost_factor_adj']
    rows = []
    for tech in techs:
        for col in cols:
            fit = tech_fit(df, col, tech)
            if fit is None:
                continue
            lr, d = fit
            nls = tech_fit_nls(df, col, tech)
            pw = tech_fit(df, col, tech, form='power')
            rows.append({
                'tech': tech, 'metric': col,
                'gen_frac_min': d['gen_frac'].min(), 'gen_frac_max': d['gen_frac'].max(),
                'nls_A': np.nan if nls is None else nls[0],
                'nls_k': np.nan if nls is None else nls[1],
                'nls_r2_y': np.nan if nls is None else r2_y(
                    nls[2][col].to_numpy(), power_model(nls[2]['gen_frac'].to_numpy(), nls[0], nls[1])),
                'slope': lr.slope, 'intercept': lr.intercept,
                'r2_y': fit_r2_y(lr, d, col, 'linear'),
                'power_A': np.nan if pw is None else np.exp(pw[0].intercept),
                'power_k': np.nan if pw is None else pw[0].slope,
                'power_r2_y': np.nan if pw is None else fit_r2_y(pw[0], pw[1], col, 'power'),
                'power_r2_log': np.nan if pw is None else pw[0].rvalue ** 2,
            })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    vf = out[out['metric'] == 'value_factor'].set_index('tech')
    vf_nls_k = out['tech'].map(vf['nls_k'])
    vf_power_k = out['tech'].map(vf['power_k'])
    is_vcf = out['metric'].isin(['value_cost_factor', 'value_cost_factor_adj'])
    out['k_ratio_vs_value_factor'] = np.where(is_vcf, out['nls_k'] / vf_nls_k, np.nan)
    out['k_cost_derived'] = np.where(is_vcf, out['nls_k'] - vf_nls_k, np.nan)
    out['cost_share_of_decline'] = np.where(is_vcf, (out['nls_k'] - vf_nls_k) / out['nls_k'], np.nan)
    out['power_k_ratio_vs_value_factor'] = np.where(is_vcf, out['power_k'] / vf_power_k, np.nan)
    return out


def add_fit_headroom(ax, values, frac=0.68):
    """Raise the top of the axis so the plotted data fills at most `frac` of it, leaving a clear band
    across the top for the fit equations. Only ever expands the range, never shrinks it."""
    vmax = pd.Series(values).max()
    if not np.isfinite(vmax):
        return
    lo, hi = ax.get_ylim()
    ax.set_ylim(lo, max(hi, lo + (vmax - lo) / frac))


def normalize_tech_name(name):
    return str(name).strip().lower()


def load_style_colors(path):
    """Load tech colors from tech_style.csv if present."""
    if not os.path.exists(path):
        return {}
    style_df = pd.read_csv(path)
    if 'order' not in style_df.columns or 'color' not in style_df.columns:
        return {}
    style_df = style_df.dropna(subset=['order', 'color'])
    return {
        normalize_tech_name(row['order']): str(row['color']).strip()
        for _, row in style_df.iterrows()
    }


def build_color_map(techs):
    """Return a consistent color mapping for all technologies, preferring tech_style.csv."""
    style_map = load_style_colors(tech_style_path)
    cmap = plt.get_cmap('tab20')
    colors = {}
    for idx, tech in enumerate(sorted(techs)):
        colors[tech] = style_map.get(normalize_tech_name(tech), cmap(idx % cmap.N))
    return colors


def plot_plcoe_pitch(
    df,
    df_lcoe,
    output_path,
    use_inverse_value_factor=True,
    use_cost_value_factor=True,
    use_adj=False,
    show_fits=False,
):
    techs = sorted(df['tech'].unique())
    colors = build_color_map(techs)

    #use_adj swaps the cost factor, the ratio, and LCOE base for their adjusted counterparts. The
    #per-tech constant that the adjustment moves from the cost factor into LCOE base cancels in the
    #product, so the bottom-row PLCOE curves are identical either way and stay unadjusted.
    adj = '_adj' if use_adj else ''
    #Abbreviated so the compound ratio title still fits the 4-across top row.
    cf_name = 'adj. cost factor' if use_adj else 'cost factor'
    lcoe_name = 'adj. LCOE base' if use_adj else 'LCOE base'
    cap = lambda s: s[0].upper() + s[1:]
    lcoe_col = f'lcoe_base_orig{adj}'

    fig = plt.figure(figsize=(22, 9))
    outer = fig.add_gridspec(2, 1, height_ratios=[1, 1.2], hspace=0.7)
    top = outer[0].subgridspec(1, 4, wspace=0.3)
    bottom = outer[1].subgridspec(1, len(years), wspace=0.25)

    ax_lcoe = fig.add_subplot(top[0])
    ax_inv_vf = fig.add_subplot(top[1])
    ax_cf = fig.add_subplot(top[2])
    ax_cvf = fig.add_subplot(top[3])
    bottom_axes = [fig.add_subplot(bottom[i]) for i in range(len(years))]

    # LCOE vs year (upper left)
    for tech in techs:
        tech_data = df_lcoe[df_lcoe['tech'] == tech].sort_values('year')
        tech_data = tech_data.dropna(subset=[lcoe_col])
        if tech_data.empty:
            continue
        ax_lcoe.plot(
            tech_data['year'],
            tech_data[lcoe_col],
            label=tech,
            color=colors[tech],
            linewidth=1.8,
            marker='o',
            markersize=3,
        )
    ax_lcoe.set_title(f'{cap(lcoe_name)} vs year')
    ax_lcoe.set_xlabel('Year')
    ax_lcoe.set_ylabel(f'{cap(lcoe_name)} ({usd_label})')
    ax_lcoe.set_ylim(bottom=0)
    ax_lcoe.grid(True, linestyle='--', linewidth=0.6, alpha=0.7)
    for year in years:
        ax_lcoe.axvline(
            year,
            color='black',
            linestyle=(0, (2, 2)),
            linewidth=1.3,
            alpha=0.9,
            zorder=5,
        )

    if use_inverse_value_factor:
        vf_col = 'inv_value_factor'
        vf_title = '1/(value factor) vs market share'
        vf_ylabel = '1/(value factor)'
        vf_ylim = inv_value_factor_ylim
    else:
        vf_col = 'value_factor'
        vf_title = 'value factor vs market share'
        vf_ylabel = 'value factor'
        vf_ylim = (
            0,
            1 / inv_value_factor_ylim[0],
        )

    if use_cost_value_factor:
        cf_col = f'cost_factor{adj}'
        cf_title = f'{cap(cf_name)} vs market share'
        cf_ylabel = cap(cf_name)
        cf_ylim = cost_factor_ylim
        ratio_col = f'cost_value_factor{adj}'
        ratio_title = f'({cf_name})/(value factor) vs market share'
        ratio_ylabel = f'({cf_name})/(value factor)'
        ratio_ylim = (0.8, max_cost_value_factor)
        formula_text = f'PLCOE = ({lcoe_name}) * ({cf_name})/(value factor)'
    else:
        cf_col = f'inv_cost_factor{adj}'
        cf_title = f'1/({cf_name}) vs market share'
        cf_ylabel = f'1/({cf_name})'
        cf_ylim = (
            0,
            1 / cost_factor_ylim[0],
        )
        ratio_col = f'value_cost_factor{adj}'
        ratio_title = f'(value factor)/({cf_name}) vs market share'
        ratio_ylabel = f'(value factor)/({cf_name})'
        ratio_ylim = (
            0,
            1 / 0.8,
        )
        formula_text = f'PLCOE = ({lcoe_name}) / ((value factor)/({cf_name}))'

    # Value factor view vs market share (upper middle-left)
    for tech in techs:
        tech_data = df[df['tech'] == tech].sort_values('gen_frac')
        if tech_data.empty:
            continue
        ax_inv_vf.plot(
            tech_data['gen_frac'],
            tech_data[vf_col],
            color=colors[tech],
            alpha=0.9,
            linewidth=1.5,
            linestyle='solid',
            marker='o',
            markersize=3,
        )
    ax_inv_vf.set_title(vf_title)
    ax_inv_vf.set_xlabel('Market share (generation fraction)')
    ax_inv_vf.set_ylabel(vf_ylabel)
    ax_inv_vf.set_ylim(vf_ylim)
    ax_inv_vf.grid(True, linestyle='--', linewidth=0.6, alpha=0.7)
    if show_fits:
        add_tech_fits(ax_inv_vf, df, vf_col, colors, fit_techs)
        add_fit_headroom(ax_inv_vf, df[vf_col])

    # Cost factor vs market share (upper middle-right)
    for tech in techs:
        tech_data = df[df['tech'] == tech].sort_values('gen_frac')
        if tech_data.empty:
            continue
        ax_cf.plot(
            tech_data['gen_frac'],
            tech_data[cf_col],
            color=colors[tech],
            alpha=0.9,
            linewidth=1.5,
            linestyle='solid',
            marker='o',
            markersize=3,
        )
    ax_cf.set_title(cf_title)
    ax_cf.set_xlabel('Market share (generation fraction)')
    ax_cf.set_ylabel(cf_ylabel)
    ax_cf.set_ylim(cf_ylim)
    ax_cf.grid(True, linestyle='--', linewidth=0.6, alpha=0.7)
    if show_fits:
        add_tech_fits(ax_cf, df, cf_col, colors, fit_techs)
        add_fit_headroom(ax_cf, df[cf_col])

    # Ratio view vs market share (upper right)
    for tech in techs:
        tech_data = df[df['tech'] == tech].sort_values('gen_frac')
        if tech_data.empty:
            continue
        ax_cvf.plot(
            tech_data['gen_frac'],
            tech_data[ratio_col],
            color=colors[tech],
            alpha=0.8,
            linewidth=1.5,
            marker='o',
            markersize=3,
        )
    ax_cvf.set_title(ratio_title)
    ax_cvf.set_xlabel('Market share (generation fraction)')
    ax_cvf.set_ylabel(ratio_ylabel)
    ax_cvf.set_ylim(ratio_ylim)
    ax_cvf.grid(True, linestyle='--', linewidth=0.6, alpha=0.7)
    if show_fits:
        add_tech_fits(ax_cvf, df, ratio_col, colors, fit_techs)
        add_fit_headroom(ax_cvf, df[ratio_col])

    # PLCOE vs market share for select years (bottom row)
    for ax, year in zip(bottom_axes, years):
        for tech in techs:
            tech_data = df[df['tech'] == tech].sort_values('gen_frac')
            plcoe_col = f'plcoe_{year}'
            tech_data = tech_data.dropna(subset=['gen_frac', plcoe_col])
            if tech_data.empty:
                continue
            ax.plot(
                tech_data['gen_frac'],
                tech_data[plcoe_col],
                color=colors[tech],
                linewidth=1.5,
                marker='o',
                markersize=3,
            )
        ax.set_title(f'{year} PLCOE vs market share')
        ax.set_xlabel('Market share (generation fraction)')
        ax.set_ylim(0, max_plcoe)
        if ax is bottom_axes[0]:
            ax.set_ylabel(f'PLCOE ({usd_label})')
        else:
            ax.set_ylabel('')
            ax.set_yticklabels([])
        ax.grid(True, linestyle='--', linewidth=0.6, alpha=0.7)

    # Shared legend for technologies
    legend_handles = [
        Line2D([0], [0], color=colors[tech], lw=2, label=tech) for tech in techs
    ]
    fig.legend(
        legend_handles,
        techs,
        loc='lower center',
        ncol=min(len(techs), 5),
        fontsize=8,
    )
    fig.subplots_adjust(bottom=0.18)

    # Place formula in the middle gap between top and bottom chart rows.
    top_row_bottom = min(
        ax_lcoe.get_position().y0,
        ax_inv_vf.get_position().y0,
        ax_cf.get_position().y0,
        ax_cvf.get_position().y0,
    )
    bottom_row_top = max(ax.get_position().y1 for ax in bottom_axes)
    formula_y = bottom_row_top + 0.5 * (top_row_bottom - bottom_row_top)
    fig.text(
        0.5,
        formula_y,
        formula_text,
        ha='center',
        va='center',
        fontsize=12,
        fontweight='bold',
        color='black',
        bbox={
            'facecolor': 'white',
            'edgecolor': 'black',
            'linewidth': 1.1,
            'boxstyle': 'round,pad=0.35',
            'alpha': 0.95,
        },
    )

    fig.savefig(output_path, dpi=300, bbox_inches='tight')
    return fig


def vcf_matched_scale(df, tech, form='linear'):
    """Scalar for LCOE base that lines the value-cost-factor intercept up with the value-factor one.

    value_cost_factor is lcoe_base/benchmark_price, so scaling LCOE base by s scales VCF by s and
    nothing else. Both fits are exactly scale-equivariant - OLS slope and intercept both scale by s,
    and the NLS amplitude A absorbs s while k is unchanged - so setting s = intercept(VF)/intercept(VCF)
    matches the intercepts exactly rather than iteratively.

    Nothing that carries a claim moves: k, the exponent ratio and the cost share of decline are all
    invariant, and PLCOE is unchanged because cost_value_factor picks up the reciprocal scaling (the
    same cancellation the _adj figures rely on). The shared intercept is imposed, not observed - it
    is what makes the remaining gap readable as cost escalation, and is not itself evidence.

    Returns (s, vf_params, vcf_params), params being (intercept, slope) for 'linear' or (A, k) for
    'power', with vcf_params already scaled. None if either fit is unavailable."""
    if form == 'linear':
        vf, vcf = tech_fit(df, 'value_factor', tech), tech_fit(df, 'value_cost_factor', tech)
        if vf is None or vcf is None or vcf[0].intercept == 0:
            return None
        s = vf[0].intercept / vcf[0].intercept
        return s, (vf[0].intercept, vf[0].slope), (vcf[0].intercept * s, vcf[0].slope * s)
    vf, vcf = tech_fit_nls(df, 'value_factor', tech), tech_fit_nls(df, 'value_cost_factor', tech)
    if vf is None or vcf is None or vcf[0] == 0:
        return None
    s = vf[0] / vcf[0]
    return s, (vf[0], vf[1]), (vcf[0] * s, vcf[1])


def _fit_form(form):
    """(predictor, equation formatter) for one of the two fit forms."""
    if form == 'linear':
        return (lambda p, x: p[0] + p[1] * x,
                lambda p: f'y = {p[1]:.2f}x + {p[0]:.2f}')
    return (lambda p, x: p[0] * (1 - x) ** p[1],
            lambda p: f'y = {p[0]:.2f}(1-x)$^{{{p[1]:.2f}}}$')


def implied_cf_equation(form, vf_p, vcf_p, direct):
    """Equation of the cost-factor curve implied by the VF and VCF fits.

    The implied curve is the ratio of the two fits, so its equation follows from theirs rather than
    from a fit of its own. Under the power form that ratio is itself a power curve, and because the
    intercepts were matched the coefficients cancel exactly, leaving y = (1-x)^(k_vcf - k_vf) for
    1/(cost factor). That single exponent difference is what the shaded band measures. Under the
    linear form the ratio of two straight lines is not a straight line, so it is written as the
    quotient rather than forced into a slope-intercept that would not be true.
    """
    num, den = (vf_p, vcf_p) if direct else (vcf_p, vf_p)
    if form == 'linear':
        return f'y = ({num[0]:.2f} {num[1]:+.2f}x) / ({den[0]:.2f} {den[1]:+.2f}x)'
    coef = num[0] / den[0]
    lead = '' if abs(coef - 1) < 5e-3 else f'{coef:.2f}'
    return f'y = {lead}(1-x)$^{{{num[1] - den[1]:.2f}}}$'


def new_build_curtailment(run_dir, prefix):
    """Curtailment of each year's new builds: 1 - gen_ivrt / gen_ivrt_uncurt over the vintages
    invested in that year.

    Those vintages are read from cap_new_ivrt, and the uncurtailed side reconciles exactly to
    valnew('MWh') - the denominator LVOE is built on - so the multiplier lands on the quantity it
    is meant to correct. Fleet curtailment would be the wrong number here by a factor of two or
    more, since the marginal build is curtailed far more heavily than the average one.
    """
    out = os.path.join(run_dir, 'outputs')
    cols = ['i', 'v', 'r', 't']
    gc = pd.read_csv(os.path.join(out, 'gen_ivrt.csv'), names=cols + ['gc'], header=0)
    gu = pd.read_csv(os.path.join(out, 'gen_ivrt_uncurt.csv'), names=cols + ['gu'], header=0)
    nv = pd.read_csv(os.path.join(out, 'cap_new_ivrt.csv'), names=cols + ['mw'], header=0)
    keys = nv[nv['mw'] > 0][cols].drop_duplicates()
    keys = keys[keys['i'].str.startswith(prefix)]
    m = keys.merge(gc, on=cols, how='left').merge(gu, on=cols, how='left')
    nat = m.groupby('t')[['gc', 'gu']].sum()
    return (1 - nat['gc'] / nat['gu']).rename('curtailment')


def new_build_available_ratio(run_dir, prefix, resource_basis):
    """Delivered energy over available energy, per year, for each year's new builds.

    Available means the most the plant could have produced: the right-hand side of
    eq_capacity_limit. For VRE that is m_cf*CAP, reported as gen_ivrt_uncurt. For
    everything else it is avail*CAP, with avail the forced- and planned-outage derate
    that report.gms averages into avg_avail. avg_avail is 1.0 for VRE - it carries no
    outage derate - so the two cannot share a source.

    Vintages are the ones invested in that year, matching new_build_curtailment, so the
    ratio describes the marginal build rather than the fleet.
    """
    out = os.path.join(run_dir, 'outputs')
    cols = ['i', 'v', 'r', 't']
    gen = pd.read_csv(os.path.join(out, 'gen_ivrt.csv'), names=cols + ['gen'], header=0)
    nv = pd.read_csv(os.path.join(out, 'cap_new_ivrt.csv'), names=cols + ['mw'], header=0)
    keys = nv[nv['mw'] > 0][cols].drop_duplicates()
    keys = keys[keys['i'].str.startswith(prefix)]
    if keys.empty:
        return pd.Series(dtype=float)
    m = keys.merge(gen, on=cols, how='left')
    if resource_basis:
        unc = pd.read_csv(os.path.join(out, 'gen_ivrt_uncurt.csv'),
                          names=cols + ['avail_mwh'], header=0)
        m = m.merge(unc, on=cols, how='left')
    else:
        cap = pd.read_csv(os.path.join(out, 'cap_ivrt.csv'), names=cols + ['mw'], header=0)
        av = pd.read_csv(os.path.join(out, 'avg_avail.csv'),
                         names=['i', 'v', 'r', 'avail'], header=0)
        m = m.merge(cap, on=cols, how='left').merge(av, on=['i', 'v', 'r'], how='left')
        m['avail_mwh'] = m['mw'] * m['avail'] * 8760
    nat = m.groupby('t')[['gen', 'avail_mwh']].sum()
    return (nat['gen'] / nat['avail_mwh']).replace([np.inf, -np.inf], np.nan).rename('ratio')


def apply_available_basis(df, valcostfac_core_path):
    """Put every tech's value and cost per MWh available rather than per MWh delivered.

    VRE is already on that basis, so its multiplier is 1; the dispatchable techs are
    scaled by delivered/available. As with the post-curtailment figure the value-cost
    factor is unchanged, because the multiplier cancels in the ratio - only the split
    between value and cost moves.
    """
    from reeds_vs_rev import tech_run_dirs, scenarios_path
    run_dirs = tech_run_dirs(df, scenarios_path)
    out = df.copy()
    out['avail_mult'] = 1.0
    for tech, prefix in avail_basis_prefix.items():
        if tech in avail_basis_resource_techs:
            continue  #already per MWh available
        if tech not in run_dirs or tech not in set(out['tech']):
            continue
        try:
            ratio = new_build_available_ratio(run_dirs[tech], prefix, resource_basis=False)
        except FileNotFoundError as e:
            print(f'available-basis ratio unavailable for {tech} ({e.filename}); left as is.')
            continue
        sel = out['tech'] == tech
        out.loc[sel, 'avail_mult'] = out.loc[sel, 'year'].map(ratio).fillna(1.0).to_numpy()
    for col in ['value_factor', 'cost_factor', 'lvoe']:
        if col in out:
            out[col] = out[col] * out['avail_mult']
    for col, src in [('inv_value_factor', 'value_factor'), ('inv_cost_factor', 'cost_factor')]:
        if src in out:
            out[col] = 1 / out[src]
    return out


def new_build_capacity_credit(run_dir, prefix):
    """Capacity credit of each year's new builds: the share of fully-firm capacity value captured.

        credit(t) = sum_r val_resmarg(r,t) / sum_r [ MW(r,t) * res_marg_ann(r,t) ]

    The denominator is what the same new MW would have earned in its own region had it been
    perfectly firm, since res_marg_ann(r,t) is the sum of that region's stress-hour reserve-margin
    prices - exactly what a MW available in every stress hour collects.

    It is a ratio of sums across regions, not a MW-weighted mean of regional credits, because that
    is already the rule the regional number itself uses. report.gms builds val_resmarg as
    sum over stress hours of (firm contribution * that hour's price), so the regional credit is a
    price-weighted collapse over hours; aggregating regions by MW instead would switch rules
    partway up the hierarchy. ReEDS' own national benchmark sums value across regions too. The
    difference is not cosmetic - res_marg_ann spans $16k to $127k/MW across regions in 2050, and
    the tight, expensive regions are where resource-limited techs do worst, so the MW-weighted
    mean reads high (battery 2040: 0.45 against 0.34).

    Being value-weighted over stress hours, this sits below a conventional hour-counting ELCC for
    resource-limited techs: stress-hour prices are extremely concentrated (CV 4.7-13.2 within a
    region; the top 10% of the 176 hours carry essentially all the annual firm value), so missing
    the few priciest hours costs more here than missing many cheap ones.

    Returns an empty Series rather than a wrong one when res_marg_ann is absent, which is the case
    under the capacity-credit PRM formulation (GSw_PRM_CapCredit=1): report.gms:1066 notes
    val_resmarg is simply not written for non-VRE there.
    """
    out = os.path.join(run_dir, 'outputs')
    val = pd.read_csv(os.path.join(out, 'valnew.csv'),
                      names=['metric', 'i', 'r', 't', 'val'], header=0)
    price = pd.read_csv(os.path.join(out, 'reqt_price.csv'),
                        names=['req', 'na', 'r', 'h', 't', 'price'], header=0)
    ann = price.loc[price['req'] == 'res_marg_ann', ['r', 't', 'price']]
    if ann.empty:
        print(f'No res_marg_ann in {run_dir}; capacity credit needs GSw_PRM_CapCredit=0.')
        return pd.Series(dtype=float)
    sel = val[val['i'].str.startswith(prefix) & val['metric'].isin(['MW', 'val_resmarg'])]
    wide = sel.pivot_table(index=['i', 'r', 't'], columns='metric', values='val').reset_index()
    if 'val_resmarg' not in wide or 'MW' not in wide:
        return pd.Series(dtype=float)
    m = wide.merge(ann, on=['r', 't'], how='left')
    m = m[(m['MW'] > 0) & (m['price'] > 0)]
    if m.empty:
        return pd.Series(dtype=float)
    #A region with capacity but no val_resmarg row earned nothing there; GAMS omits zeros, and
    #sum() skipping the NaN gives it the zero it should have in the numerator while it still
    #counts in the denominator.
    m['firm_value'] = m['MW'] * m['price']
    nat = m.groupby('t')[['val_resmarg', 'firm_value']].sum()
    return (nat['val_resmarg'] / nat['firm_value']).rename('capacity_credit')


def cumulative_capacity_gw(run_dir, prefix):
    """Installed national capacity of a tech by year, GW, from cap_ivrt."""
    cap = pd.read_csv(os.path.join(run_dir, 'outputs', 'cap_ivrt.csv'),
                      names=['i', 'v', 'r', 't', 'mw'], header=0)
    return cap[cap['i'].str.startswith(prefix)].groupby('t')['mw'].sum() / 1000


def new_build_gw(run_dir, prefix):
    """Capacity of each year's new builds, GW, from valnew - the MW the capacity credit is taken over."""
    val = pd.read_csv(os.path.join(run_dir, 'outputs', 'valnew.csv'),
                      names=['metric', 'i', 'r', 't', 'val'], header=0)
    sel = val[(val['metric'] == 'MW') & val['i'].str.startswith(prefix)]
    return sel.groupby('t')['val'].sum() / 1000


def capacity_credit_frame(df):
    """Capacity credit per (tech, year), joined to the market share the rest of the report plots.

    Each tech is read from the run that forces it, the same pairing the other per-run quantities
    use. Techs whose prefix is not in avail_basis_prefix are skipped.
    """
    from reeds_vs_rev import tech_run_dirs, scenarios_path
    run_dirs = tech_run_dirs(df, scenarios_path)
    rows = []
    for tech, prefix in avail_basis_prefix.items():
        if tech not in run_dirs or tech not in set(df['tech']):
            continue
        try:
            credit = new_build_capacity_credit(run_dirs[tech], prefix)
        except FileNotFoundError as e:
            print(f'capacity credit unavailable for {tech} ({e.filename}); skipped.')
            continue
        if credit.empty:
            continue
        #Cumulative national capacity of the tech in its own forcing run, the alternative x axis.
        cap_gw = cumulative_capacity_gw(run_dirs[tech], prefix)
        sub = df.loc[df['tech'] == tech, ['tech', 'year', 'gen_frac']].drop_duplicates()
        sub = sub.assign(capacity_credit=sub['year'].map(credit),
                         cap_gw=sub['year'].map(cap_gw))
        rows.append(sub.dropna(subset=['capacity_credit']))
    if not rows:
        return pd.DataFrame(columns=['tech', 'year', 'gen_frac', 'cap_gw', 'capacity_credit'])
    return pd.concat(rows, ignore_index=True).sort_values(['tech', 'year'])


def plot_capacity_credit(df, output_path, x='gen_frac', cc=None):
    """Capacity credit against market share or against cumulative capacity, every tech on one
    pair of axes.

    Market share matches the rest of the report: the decline in capacity credit is one of the
    mechanisms behind the value-factor decline, so it reads against the same x as the value-factor
    curves. Cumulative capacity answers a different question - how much of a technology the system
    can absorb before firmness stops being rewarded - and separates techs that market share puts
    on top of each other, since a gigawatt of storage and a gigawatt of wind are nowhere near the
    same share of generation. It runs on a log axis because the techs span twenty gigawatts to
    three terawatts.

    One axes rather than panels: six monotone curves separate cleanly, and the point is the
    contrast between the dispatchable techs' flat lines and the resource-limited techs' collapse.
    """
    if cc is None:
        cc = capacity_credit_frame(df)
    if cc.empty or x not in cc:
        return None, cc
    colors = build_color_map(sorted(cc['tech'].unique()))
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    order = sorted(cc['tech'].unique(), key=lambda t: -cc.loc[cc['tech'] == t, 'capacity_credit'].mean())
    for tech in order:
        d = cc[cc['tech'] == tech].dropna(subset=[x]).sort_values(x)
        xs = d[x] * 100 if x == 'gen_frac' else d[x]
        ax.plot(xs, d['capacity_credit'], marker='o', ms=4, lw=1.6,
                color=colors[tech], label=display_tech(tech))
    ax.axhline(1.0, color=cost_color, lw=0.9, ls=':', zorder=0)
    ax.annotate('perfectly firm', xy=(0.01, 1.0), xycoords=('axes fraction', 'data'),
                va='bottom', ha='left', fontsize=7.5, color=cost_color)
    if x == 'gen_frac':
        ax.set_xlabel('Market share (% of generation)')
    else:
        ax.set_xscale('log')
        ax.set_xlabel('Cumulative national capacity (GW)')
        ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f'{v:g}'))
        ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.set_ylabel('Capacity credit of new builds')
    ax.set_ylim(bottom=0)
    ax.grid(alpha=0.25, lw=0.6)
    #The dispatchable curves sit above 0.75 and the resource-limited ones below 0.4 over the whole
    #range, so the band between them is the one reliably empty region.
    ax.legend(loc='center right', fontsize=8, frameon=False, ncol=2)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    return fig, cc


def capacity_credit_by_scenario(techs=None):
    """New-build capacity credit of each tech in cc_scenario_techs, in every scenario of the report.

    The capacity-credit figures above read each tech from the run that forces it, so a tech's
    credit there is a function of its own deployment. Here the same quantity - computed by
    new_build_capacity_credit, so on the same ratio-of-sums basis - comes from every run, which
    shows how much of a tech's credit is set by what else the system builds. Scenarios are labelled
    by the tech they force, from core_tech_scen.csv; one not listed there is the reference.
    """
    from reeds_vs_rev import scenarios_path
    techs = cc_scenario_techs if techs is None else techs
    scen = pd.read_csv(scenarios_path)
    forced = pd.read_csv(os.path.join(this_dir, 'core_tech_scen.csv')).set_index('scenario')['tech']
    rows = []
    for tech in techs:
        prefix = avail_basis_prefix.get(tech)
        if prefix is None:
            continue
        for _, sc in scen.iterrows():
            try:
                credit = new_build_capacity_credit(sc['path'], prefix)
                built = new_build_gw(sc['path'], prefix)
                cap = cumulative_capacity_gw(sc['path'], prefix)
            except FileNotFoundError as e:
                print(f'capacity credit unavailable for {tech} in {sc["name"]} ({e.filename}); skipped.')
                continue
            if credit.empty:
                continue
            d = pd.DataFrame({'year': credit.index.astype(int), 'capacity_credit': credit.to_numpy()})
            d['new_gw'] = d['year'].map(built)
            d['cap_gw'] = d['year'].map(cap)
            d = d[(d['new_gw'] >= cc_scenario_min_new_gw) & (d['year'] >= start_year)]
            rows.append(d.assign(tech=tech, scenario=sc['name'],
                                 forced_tech=forced.get(sc['name'], None)))
    if not rows:
        return pd.DataFrame(columns=['tech', 'scenario', 'forced_tech', 'year', 'new_gw',
                                     'cap_gw', 'capacity_credit'])
    return pd.concat(rows, ignore_index=True)[
        ['tech', 'scenario', 'forced_tech', 'year', 'new_gw', 'cap_gw', 'capacity_credit']]


def plot_capacity_credit_by_scenario(output_path, cc=None):
    """One row per tech, every scenario as a line: against model year on the left and against that
    tech's own installed capacity on the right.

    The right column is the diagnostic. If a tech's credit depended only on how much of it is
    installed, every scenario would fall on one curve there; where the lines separate, something
    else the scenario builds is setting the credit.

    Each scenario takes the colour of the tech it forces, matching every other figure in the report,
    and the reference is a dashed grey. Those colours are inherited rather than chosen for this
    figure, and grey against battery pink falls below the colour-vision separation a line chart wants
    on colour alone (OKLab delta E 6.6 under deuteranopia), so every scenario also has its own
    marker and the reference its own dash.
    """
    cc = capacity_credit_by_scenario() if cc is None else cc
    if cc.empty:
        return None, cc
    from reeds_vs_rev import scenarios_path
    order = list(pd.read_csv(scenarios_path)['name'])
    style_map = load_style_colors(tech_style_path)
    markers = ['o', 's', '^', 'D', 'v', 'P', 'X', '*']

    def look(scen):
        ft = cc.loc[cc['scenario'] == scen, 'forced_tech'].iloc[0]
        if ft is None or pd.isna(ft):
            return dict(color='#8C8C8C', ls=(0, (5, 2.5)), label='Reference (no forcing)')
        return dict(color=style_map.get(normalize_tech_name(ft), '#555555'), ls='-',
                    label=f'{display_tech(ft)} forced')

    techs = [t for t in cc_scenario_techs if t in set(cc['tech'])]
    year_step = (cc.sort_values('year').groupby(['tech', 'scenario'])['year'].diff()
                 .dropna().mode().iloc[0])
    fig, axes = plt.subplots(len(techs), 2, figsize=(10.4, 3.7 * len(techs)), squeeze=False)
    handles = {}
    for row, tech in enumerate(techs):
        for col, x in enumerate(['year', 'cap_gw']):
            ax = axes[row][col]
            for k, scen in enumerate(order):
                d = cc[(cc['tech'] == tech) & (cc['scenario'] == scen)].sort_values('year')
                if d.empty:
                    continue
                #Break the line where years were dropped for building under cc_scenario_min_new_gw,
                #so a segment never implies a path through years with no data. The solve-year step
                #is read from the data - the most common spacing across every series - rather than
                #assumed.
                gap = d['year'].diff() > year_step
                if gap.any():
                    blanks = d[gap].assign(capacity_credit=np.nan, year=d.loc[gap, 'year'] - 1)
                    d = pd.concat([d, blanks]).sort_values('year')
                st = look(scen)
                ln, = ax.plot(d[x], d['capacity_credit'], color=st['color'], ls=st['ls'], lw=1.6,
                              marker=markers[k % len(markers)], ms=5, mec='white', mew=0.6,
                              label=st['label'])
                handles.setdefault(scen, ln)
            ax.axhline(1.0, color=cost_color, lw=0.9, ls=':', zorder=0)
            ax.set_ylim(0, 1.05)
            ax.grid(alpha=0.25, lw=0.6)
            if x == 'cap_gw':
                ax.set_xscale('log')
                _log_ticks(ax, axis='x', steps=(1, 2, 5))
                ax.set_xlabel(f'Installed {display_tech(tech)} capacity (GW)')
            else:
                ax.set_xlabel('Model year')
                ax.set_ylabel('Capacity credit of new builds')
            ax.set_title(f'{display_tech(tech)}' + (' vs model year' if x == 'year'
                                                     else ' vs its own installed capacity'),
                         fontsize=10, loc='left')
    fig.legend([handles[s] for s in order if s in handles],
               [look(s)['label'] for s in order if s in handles],
               loc='lower center', ncol=4, fontsize=8, frameon=False, bbox_to_anchor=(0.5, 0.0))
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(output_path, dpi=200)
    return fig, cc

def new_build_duration(run_dir, prefix='battery'):
    """Duration in hours of each region's new storage build, per year: INV_ENERGY over INV.

    Both come from standard outputs - cap_energy_new_out is INV_ENERGY.l and cap_new_ivrt is
    INV.l/ilr, which is INV.l for battery. Differencing cap_energy_ivrt instead would be wrong:
    energy capacity retires, and the model can add energy to existing power capacity or power to
    existing energy capacity, since INV and INV_ENERGY are independent. In 2038 that difference
    reads 2.4 h against the true 3.7 h.

    cap_energy_new_out was declared in report_params.csv but never assigned until 2026-10, so a
    run reported before then ships it empty and this returns nothing.
    """
    out = os.path.join(run_dir, 'outputs')
    cols = ['i', 'v', 'r', 't']
    mwh = pd.read_csv(os.path.join(out, 'cap_energy_new_out.csv'), names=cols + ['mwh'], header=0)
    if mwh.empty:
        print(f'cap_energy_new_out is empty in {run_dir}; re-run report.gms to populate it.')
        return pd.DataFrame(columns=cols + ['mw', 'mwh', 'dur'])
    mw = pd.read_csv(os.path.join(out, 'cap_new_ivrt.csv'), names=cols + ['mw'], header=0)
    m = mw[mw['i'].str.startswith(prefix)].merge(
        mwh[mwh['i'].str.startswith(prefix)], on=cols, how='inner')
    #Builds of a megawatt or less are numerical dust whose ratio is meaningless and unbounded.
    m = m[m['mw'] > 1].copy()
    m['dur'] = m['mwh'] / m['mw']
    return m


def weighted_quantile(values, weights, qs):
    """Quantiles of `values` weighted by `weights`, by interpolating the weighted CDF."""
    order = np.argsort(values)
    v, w = np.asarray(values)[order], np.asarray(weights)[order]
    c = np.cumsum(w) / w.sum()
    return [float(np.interp(q, c, v)) for q in qs]


def plot_new_build_duration(run_dir, output_path, prefix='battery', min_gw=1.0):
    """Distribution of new-build storage duration by model year, with the mean connected.

    Quantiles and mean are capacity-weighted, so a region that built a gigawatt counts for more
    than one that built ten megawatts; an unweighted box would be dominated by the many small
    regional builds. Box width is proportional to the square root of the capacity built that year,
    so a wide box is a year whose distribution describes a lot of capacity, subject to a floor
    that keeps the thinnest box readable.

    Years building less than min_gw are dropped: before 2020 the fleet grows by a few megawatts a
    year and the distribution is one or two sites.
    """
    d = new_build_duration(run_dir, prefix)
    if d.empty:
        return None, d
    rows, stats, widths = [], [], []
    for y in sorted(d['t'].unique()):
        s = d[d['t'] == y]
        if s['mw'].sum() / 1000 < min_gw:
            continue
        q = weighted_quantile(s['dur'], s['mw'], [0.1, 0.25, 0.5, 0.75, 0.9])
        mean = float(np.average(s['dur'], weights=s['mw']))
        gw = s['mw'].sum() / 1000
        stats.append(dict(label=str(int(y)), whislo=q[0], q1=q[1], med=q[2], q3=q[3], whishi=q[4],
                          fliers=[]))
        widths.append(gw ** 0.5)
        rows.append(dict(year=int(y), gw=gw, p10=q[0], p25=q[1], median=q[2], p75=q[3], p90=q[4],
                         mean=mean, n_regions=len(s)))
    if not rows:
        return None, pd.DataFrame()
    tab = pd.DataFrame(rows)
    widths = 0.26 + 0.46 * np.array(widths) / max(widths)
    fig, ax = plt.subplots(figsize=(8.0, 4.4))
    ax.bxp(stats, widths=widths, showfliers=False, patch_artist=True,
           boxprops=dict(facecolor='#CFE4EE', edgecolor='#2A6F8E', lw=0.9),
           medianprops=dict(color='#14455C', lw=1.4),
           whiskerprops=dict(color='#2A6F8E', lw=0.9), capprops=dict(color='#2A6F8E', lw=0.9))
    ax.plot(range(1, len(tab) + 1), tab['mean'], color='#C0392B', marker='o', ms=4, lw=1.6,
            zorder=5, label='capacity-weighted mean')
    ax.set_xlabel('Model year')
    ax.set_ylabel('Duration of new builds (hours)')
    ax.set_ylim(bottom=0)
    ax.grid(axis='y', alpha=0.25, lw=0.6)
    ax.legend(loc='upper left', fontsize=8, frameon=False)
    for lab in ax.get_xticklabels():
        lab.set_rotation(60)
        lab.set_ha('right')
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    return fig, tab


def stress_block_hours(run_dir):
    """Length in hours of one stress block in this run, from its GSw_HourlyChunkLengthStress.

    hourly_writetimeseries.py builds the stress timeslices from this same switch, so it is the
    block length by construction.
    """
    sw = pd.read_csv(os.path.join(run_dir, 'inputs_case', 'switches.csv'), header=None, index_col=0)[1]
    return float(sw['GSw_HourlyChunkLengthStress'])


def battery_stress_arbitrage(run_dir, prefix='battery'):
    """Per year, how the storage fleet earns its reserve-margin value inside the stress periods.

    A battery's net energy over a stress day is zero or slightly negative - it discharges only
    what it charged, less round-trip losses - so none of its capacity value is firm energy. All of
    it is the price spread between the hours it discharges in and the hours it charges in. This
    splits the fleet credit into the gross value of discharge and the cost of charging, and
    reports the two capacity-weighted prices whose ratio drives it.

    gen_h_stress for storage is already net of charging, so a negative entry is a charging hour.

    The prices are reported per MWh delivered in a stress block. reqt_price('res_marg') is $/MW per
    block per year - the dual of the block's supply-demand balance, which binds on MW - and
    report.gms declines to call it $/MWh because the blocks carry no weight in the annual
    objective. They do have a real length, GSw_HourlyChunkLengthStress hours, and a MW held
    through the block is that many MWh, so dividing by it gives the value of one MWh delivered in
    that block. Prices are read in ReEDS' native 2004$ and converted to dollar_year. The credit
    shares are ratios and need neither conversion.
    """
    out = os.path.join(run_dir, 'outputs')
    gen = pd.read_csv(os.path.join(out, 'gen_h_stress.csv'),
                      names=['i', 'r', 'h', 't', 'gen'], header=0)
    gen = gen[gen['i'].str.startswith(prefix)].groupby(['r', 'h', 't'], as_index=False)['gen'].sum()
    rq = pd.read_csv(os.path.join(out, 'reqt_price.csv'),
                     names=['req', 'na', 'r', 'h', 't', 'price'], header=0)
    hourly = rq.loc[rq['req'] == 'res_marg', ['r', 'h', 't', 'price']]
    ann = rq.loc[rq['req'] == 'res_marg_ann', ['r', 't', 'price']].rename(columns={'price': 'ann'})
    cap = pd.read_csv(os.path.join(out, 'cap_ivrt.csv'), names=['i', 'v', 'r', 't', 'mw'], header=0)
    cap = cap[cap['i'].str.startswith(prefix)].groupby(['r', 't'], as_index=False)['mw'].sum()
    m = gen.merge(hourly, on=['r', 'h', 't']).merge(cap, on=['r', 't']).merge(ann, on=['r', 't'])
    m = m[(m['mw'] > 0) & (m['ann'] > 0)]
    block_hours = stress_block_hours(run_dir)
    to_usd_mwh = reeds_usd_mult / block_hours
    rows = []
    for y, d in m.groupby('t'):
        firm = (d.drop_duplicates(['r', 't'])['mw'] * d.drop_duplicates(['r', 't'])['ann']).sum()
        up, dn = d[d['gen'] > 0], d[d['gen'] < 0]
        if firm <= 0 or up.empty or dn.empty:
            continue
        rows.append(dict(
            year=int(y),
            gross=float((up['gen'] * up['price']).sum() / firm),
            charge_cost=float((dn['gen'] * dn['price']).sum() / firm),
            net=float((d['gen'] * d['price']).sum() / firm),
            price_discharge=float(np.average(up['price'], weights=up['gen']) * to_usd_mwh),
            price_charge=float(np.average(dn['price'], weights=-dn['gen']) * to_usd_mwh),
            gw=float(d.drop_duplicates(['r', 't'])['mw'].sum() / 1000),
            block_hours=block_hours))
    return pd.DataFrame(rows)


def plot_battery_stress_arbitrage(run_dir, output_path, prefix='battery', start_year=2026):
    """Two panels: the prices storage buys and sells at inside the stress periods, and the credit
    those prices produce.

    Years before start_year are dropped: the fleet is a few gigawatts then and the ratios are
    dominated by a handful of region-hours.
    """
    d = battery_stress_arbitrage(run_dir, prefix)
    if d.empty:
        return None, d
    d = d[d['year'] >= start_year].sort_values('year')
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.4, 4.3))
    ax1.fill_between(d['year'], d['price_charge'], d['price_discharge'],
                     color='#CFE4EE', alpha=0.8, lw=0)
    ax1.plot(d['year'], d['price_discharge'], color='#C0392B', marker='o', ms=4, lw=1.6,
             label='discharge-weighted')
    ax1.plot(d['year'], d['price_charge'], color='#2A6F8E', marker='o', ms=4, lw=1.6,
             label='charge-weighted')
    ax1.set_yscale('log')
    ax1.set_ylabel(f'Stress-block reserve-margin price ({dollar_year}$/MWh)')
    ax1.set_xlabel('Model year')
    ax1.set_title('Prices storage buys and sells at', fontsize=10, loc='left')
    ax1.legend(loc='lower right', fontsize=8, frameon=False)
    ax1.grid(alpha=0.25, lw=0.6)

    ax2.bar(d['year'], d['gross'], width=1.5, color='#8FC4D8', label='gross value of discharge')
    ax2.bar(d['year'], d['charge_cost'], width=1.5, color='#E6A4A0', label='cost of charging')
    ax2.plot(d['year'], d['net'], color='#14455C', marker='o', ms=4, lw=1.8,
             label='net capacity credit')
    ax2.axhline(0, color=cost_color, lw=0.8)
    ax2.set_xlabel('Model year')
    ax2.set_ylabel('Share of fully-firm capacity value')
    ax2.set_title('What those prices leave', fontsize=10, loc='left')
    ax2.legend(loc='upper right', fontsize=8, frameon=False)
    ax2.grid(axis='y', alpha=0.25, lw=0.6)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    return fig, d


def apply_post_curtailment(df, valcostfac_core_path):
    """Put VRE value and cost per MWh generated, matching the dispatched basis of the other techs.

    value_factor and cost_factor each pick up 1/(1 - curtailment); value_cost_factor is their ratio
    and does not move. Techs without a run directory or without a tech_prefix entry are left on
    their existing basis, which for dispatchable techs is already the dispatched one. The scenario
    -> run mapping is the same one reeds_vs_rev and lvoe_vs_lcoe use.
    """
    from reeds_vs_rev import tech_run_dirs, scenarios_path
    from lvoe_vs_lcoe import tech_prefix_map
    run_dirs = tech_run_dirs(df, scenarios_path)
    out = df.copy()
    out['curtailment_new'] = 0.0
    for tech, prefix in tech_prefix_map.items():
        if tech not in run_dirs or tech not in set(out['tech']):
            continue
        curt = new_build_curtailment(run_dirs[tech], prefix)
        sel = out['tech'] == tech
        out.loc[sel, 'curtailment_new'] = out.loc[sel, 'year'].map(curt).fillna(0).to_numpy()
    mult = 1 / (1 - out['curtailment_new'])
    for col in ['value_factor', 'cost_factor', 'lvoe']:
        if col in out:
            out[col] = out[col] * mult
    #value_cost_factor is left as is: it is value_factor / cost_factor and the multiplier cancels.
    for col, src in [('inv_value_factor', 'value_factor'), ('inv_cost_factor', 'cost_factor')]:
        if src in out:
            out[col] = 1 / out[src]
    return out


def load_full_range(valcostfac_core_path, core):
    """The same core results, without report_switches' gen_frac_max truncation.

    valcostfac_core.csv is filtered to gen_frac <= gen_frac_max, a cap meant for the intermediary
    "lim" plots. The value-cost-factor figures are about how value and cost move as market share
    rises, so truncating market share removes exactly the part they exist to show - and for the
    dispatchable techs it removes most of it. Each tech is taken from its own scenario, matching the
    core file, and only core == 1 rows are kept. Falls back to the core file if valcostfac.csv is
    not alongside it.
    """
    full_path = os.path.join(os.path.dirname(os.path.abspath(valcostfac_core_path)),
                             'valcostfac.csv')
    if not os.path.exists(full_path):
        print('valcostfac.csv not found; VCF figures fall back to the truncated core results.')
        return core
    full = pd.read_csv(full_path)
    scen = core.groupby('tech')['scenario'].first()
    keep = [t in scen.index and sc == scen[t] for t, sc in zip(full['tech'], full['scenario'])]
    out = full[keep & (full['core'] == 1) & (full['year'] >= start_year)].copy()
    #Derived columns the figures read. The _adj family is deliberately absent: it is normalised
    #against the conventional techs' means computed after the cap, so it exists only in the core
    #file and only the figures that stay on the core file use it.
    out['cost_value_factor'] = 1 / out['value_cost_factor']
    out['inv_value_factor'] = 1 / out['value_factor']
    out['inv_cost_factor'] = 1 / out['cost_factor']
    return out


def _log_ticks(ax, axis='y', steps=(1, 2, 3, 5)):
    """Label a log axis at the given steps per decade in plain decimals.

    Decades alone leave only one or two labelled ticks over the range these figures span.
    """
    lo_lim, hi_lim = ax.get_ylim() if axis == 'y' else ax.get_xlim()
    nice = [d * 10.0 ** e for e in range(-4, 6) for d in steps]
    ticks = [t for t in nice if lo_lim <= t <= hi_lim]
    target = ax.yaxis if axis == 'y' else ax.xaxis
    (ax.set_yticks if axis == 'y' else ax.set_xticks)(ticks)
    (ax.set_yticklabels if axis == 'y' else ax.set_xticklabels)([f'{t:g}' for t in ticks])
    target.set_minor_formatter(matplotlib.ticker.NullFormatter())


def vcf_panel_techs(df, techs=None):
    """Techs eligible for the value-cost-factor figures, in a stable order.

    The figure's construction - scale LCOE base until the VF and VCF fits share an intercept at
    x=0, then shade between them - only means something if the data comes near x=0. A tech whose
    market share starts high has its intercept, and therefore the entire band, produced by
    extrapolation rather than measurement, so vcf_min_anchor_gen_frac gates on the lowest observed
    market share rather than on the tech name.
    """
    if techs is not None:
        return [t for t in techs if t in set(df['tech'])]
    if vcf_techs is not None:
        return [t for t in vcf_techs if t in set(df['tech'])]
    lo = df.groupby('tech')['gen_frac'].min()
    #fit_techs first so the VRE panels lead, then the rest by how far their market share reaches.
    #vcf_separate_techs are held back for their own figure.
    rest = sorted([t for t in lo.index if t not in fit_techs and t not in vcf_separate_techs
                   and lo[t] <= vcf_min_anchor_gen_frac],
                  key=lambda t: -df[df['tech'] == t]['gen_frac'].max())
    return [t for t in fit_techs if t in lo.index and t not in vcf_separate_techs] + rest


def plot_vre_vcf(df, output_path, form='linear', techs=None, log_y=False, sync_axes=False,
                 basis_note=''):
    """One panel per tech, showing value factor against value-cost factor after LCOE base has been
    scaled so the two share a fit intercept.

    With the intercepts matched the curves start together, so the shaded gap between them is the
    cost escalation alone - the part of the competitiveness decline that is not value factor. The
    linear and power versions of this figure are the same construction under two fit forms; agreement
    between them is the check that the result does not depend on the form.

    log_y is retained as an option but no figure is written with it any more - the additive
    reading it enables is carried by plcoe_pitch_VRE_VCF_decomposition.png, which does the same
    split as stacked bars and does not need the reader to measure gaps off a log axis. What follows
    is why it helps, should it be wanted again:

    log_y is the better axis for reading the decomposition. VCF is the product VF * (1/CF), so only in
    logs do the two components sum to the whole: on a linear axis their declines over-account for the
    VCF decline by about 1.5x, and reading the split off them overstates the cost share (39% against a
    true 31% for wind, 35% against 20% for UPV). On a log axis equal vertical distances are equal
    ratios, the band's thickness is exactly ln(cost factor), and the value and cost gaps stack to the
    VCF gap, so the split can be measured off the page at any market share."""
    techs = vcf_panel_techs(df, techs)
    colors = build_color_map(techs)
    predict, equation = _fit_form(form)
    label = 'linear' if form == 'linear' else 'power (NLS)'

    #Wrap onto a grid rather than one long row: with the dispatchable techs included a single row
    #would be well over two feet wide.
    ncol = min(len(techs), vcf_max_cols)
    nrow = int(np.ceil(len(techs) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(6.8 * ncol, 5.2 * nrow), squeeze=False)
    axes = axes.ravel()
    for ax in axes[len(techs):]:
        ax.set_visible(False)
    panel_lims = []
    scales = []
    for ax, tech in zip(axes, techs):
        d = df[df['tech'] == tech].dropna(
            subset=['gen_frac', 'value_factor', 'value_cost_factor']).sort_values('gen_frac')
        matched = vcf_matched_scale(df, tech, form)
        if d.empty or matched is None:
            ax.set_visible(False)
            continue
        s, vf_p, vcf_p = matched
        x = d['gen_frac'].to_numpy()
        y_vf = d['value_factor'].to_numpy()
        y_vcf = d['value_cost_factor'].to_numpy() * s
        color = colors[tech]

        #The band is drawn between the FITS, not between the points. The intercept match is a
        #property of the fits and the claim is about their exponents, so the fitted band is the
        #quantity actually being asserted. The band between raw points is also unusable here: at the
        #lowest market share the scaled VCF sits above VF in every tech and fit form, by up to 0.048,
        #so shading the points would fill a region meaning the opposite of its label. The fitted band
        #is strictly positive across the range.
        #Fits span the whole axis, from zero market share out past the last point, so the matched
        #intercept is visible. That convergence at x=0 is the construction the band rests on and it
        #sits outside the data, which starts at x=0.08 for wind and 0.06 for UPV. The stretch beyond
        #the observed points is drawn faint so the extrapolation stays obvious.
        x_hi = x.max() * 1.04
        xs = np.linspace(0, x_hi, 400)
        fit_vf, fit_vcf = predict(vf_p, xs), predict(vcf_p, xs)
        #A straight-line fit can reach zero inside the range (it does for UPV), so the band stops
        #there rather than being drawn through the sign change.
        band = (fit_vf > 0) & (fit_vcf > 0)
        ax.fill_between(xs[band], fit_vcf[band], fit_vf[band], color=color, alpha=0.15, zorder=2,
                        label='cost escalation (fitted)')
        observed = (xs >= x.min()) & (xs <= x.max())
        for params in (vf_p, vcf_p):
            fit = predict(params, xs)
            ax.plot(xs, fit, color=color, linestyle=':', linewidth=1.2, alpha=0.35, zorder=5)
            ax.plot(xs[observed], fit[observed], color=color, linestyle=':', linewidth=1.4,
                    alpha=0.9, zorder=5)

        ax.plot(x, y_vf, color=color, linestyle='-', marker='o', markersize=5, linewidth=1.8,
                label='value factor', zorder=4)
        ax.plot(x, y_vcf, color=color, linestyle='--', marker='s', markersize=5, linewidth=1.8,
                alpha=0.85, label='value-cost factor (scaled)', zorder=4)

        #1/(cost factor) is VCF/VF, so it is the vertical ratio of the two series above rather than a
        #new measurement, and after the scaling it passes through 1.0 at zero market share. It is
        #drawn against the curve IMPLIED by the VF and VCF fits, not against a fit of its own: an
        #independent fit would be a second, slightly different answer to the same question, whereas
        #the implied curve is the one the shaded band actually asserts. Where the points depart from
        #it - and for UPV they depart a long way at the top of the range - that gap is a real
        #limitation of describing a ratio by the ratio of two fits, and is better shown than hidden.
        y_cf, cf_observed = np.array([]), np.nan
        eq_cf, r2_cf, cf_tag = None, np.nan, None
        if show_cost_factor:
            #Scaling LCOE base by s divides the cost factor by s, which is the same as multiplying
            #1/(cost factor) by s. Either way the series passes through 1.0 at zero market share.
            if cost_factor_direct:
                y_cf = d['cost_factor'].to_numpy() / s
                implied = np.divide(fit_vf, fit_vcf, out=np.full_like(fit_vf, np.nan), where=band)
                cf_label = 'cost factor, scaled'
            else:
                y_cf = d['inv_cost_factor'].to_numpy() * s
                implied = np.divide(fit_vcf, fit_vf, out=np.full_like(fit_vcf, np.nan), where=band)
                cf_label = '1/(cost factor), scaled'
            cf_observed = y_cf[-1] if cost_factor_direct else 1 / y_cf[-1]
            ax.plot(x, y_cf, color=cost_color, linestyle='-.', marker='^', markersize=4.5,
                    linewidth=1.3, alpha=0.85, label=cf_label, zorder=3)
            if show_cost_factor_fit:
                #R^2 of the implied curve against the cost-factor data it is drawn over. This is not
                #a goodness-of-fit for a fitted curve - nothing was fitted to these points - but a
                #measure of how far the ratio of the two fits departs from the ratio actually
                #observed, which is exactly the limitation worth quoting next to the equation. It
                #can go negative, and for the linear UPV panel it does, where the value-factor fit
                #crosses zero inside the data range.
                num, den = (vf_p, vcf_p) if cost_factor_direct else (vcf_p, vf_p)
                p_num, p_den = predict(num, x), predict(den, x)
                ok = (p_num > 0) & (p_den > 0)
                r2_cf = r2_y(y_cf[ok], p_num[ok] / p_den[ok]) if ok.sum() > 1 else np.nan
                eq_cf = implied_cf_equation(form, vf_p, vcf_p, cost_factor_direct)
                cf_tag = 'CF (implied)' if cost_factor_direct else '1/CF (implied)'
                ax.plot(xs, implied, color=cost_color, linestyle=':', linewidth=1.2, alpha=0.35,
                        zorder=5)
                ax.plot(xs[observed], implied[observed], color=cost_color, linestyle=':',
                        linewidth=1.4, alpha=0.9, zorder=5,
                        label=f'{cf_label}, implied by fits')

        #Implied cost factor from the fits: 1.00 at zero market share by construction, so the value
        #at the top of the range is the cost escalation the scaling makes visible. It is recorded in
        #plcoe_pitch_vcf_scales.csv rather than printed on the panel, which keeps the box to the
        #scaling and the two fits it applies to. A straight line can fall through zero inside the
        #plotted range - the linear value-factor fit for UPV does, at x=0.43 against data reaching
        #0.45 - and the ratio of two fits is meaningless once either has, so it is left undefined
        #there rather than reported.
        pred_vf, pred_vcf = predict(vf_p, x.max()), predict(vcf_p, x.max())
        valid = pred_vf > 0 and pred_vcf > 0
        cf_hi = pred_vf / pred_vcf if valid else np.nan
        #The cost-factor line sits with the two fits it is the ratio of, so the arithmetic is on
        #the page: under the power form its exponent is exactly k_vcf - k_vf, and the reader can
        #check the subtraction against the two lines above it. Its R^2 is not a goodness-of-fit -
        #nothing was fitted to the cost-factor points - but a measure of how far the ratio of the
        #two fits departs from the ratio observed.
        lines = [
            f'LCOE base x {s:.4f}',
            f'VF   {equation(vf_p)}  (R$^2$={r2_y(y_vf, predict(vf_p, x)):.2f})',
            f'VCF  {equation(vcf_p)}  (R$^2$={r2_y(y_vcf, predict(vcf_p, x)):.2f})',
        ]
        if eq_cf is not None:
            lines.append(f'{cf_tag}  {eq_cf}  (R$^2$={r2_cf:.2f})')
        #The intercept match at x=0 is the construction the band rests on. Where the data starts
        #well above zero that match is extrapolated, not measured, so the panel says so rather than
        #letting the band read as though it were observed all the way down.
        if x.min() > vcf_anchor_warn_gen_frac:
            lines.append(f'data starts at x={x.min():.2f}; intercept extrapolated')
        text = '\n'.join(lines)
        ax.text(0.97, 0.97, text, transform=ax.transAxes, fontsize=8, va='top', ha='right',
                multialignment='left', zorder=7,
                bbox={'facecolor': 'white', 'edgecolor': '0.7', 'boxstyle': 'round,pad=0.4',
                      'alpha': 0.92})

        ax.set_title(display_tech(tech))
        ax.set_xlabel('Market share (generation fraction)')
        ax.set_xlim(0, x_hi)
        #Headroom accounts for the fits at x=0, which rise above the data (UPV's reaches 1.17).
        observed_series = [y_vf, y_vcf] + ([y_cf] if show_cost_factor else [])
        series = observed_series + [fit_vf, fit_vcf]
        if log_y:
            #The floor comes from the DATA alone, the ceiling from the data and the fits. A fit that
            #dives towards zero would otherwise stretch the axis down over empty space and squash
            #everything else - the linear value-factor fit for UPV falls through zero at x=0.43, and
            #on a log axis that is an unbounded plunge. Letting it run off the bottom keeps the scale
            #set by real values, and a fit leaving the axis is itself the clearest statement that the
            #form has failed there.
            floor = np.concatenate([v[np.isfinite(v) & (v > 0)] for v in observed_series if v.size]).min()
            ceil = max(v[np.isfinite(v) & (v > 0)].max() for v in series if v.size)
            pad = np.log10(ceil / floor)
            ax.set_yscale('log')
            #A smaller fraction than the linear axis uses: over a decade or more, 0.30 of the span
            #is a factor of three of empty sky above the curves.
            ax.set_ylim(10 ** (np.log10(floor) - 0.05 * pad), 10 ** (np.log10(ceil) + 0.17 * pad))
            _log_ticks(ax)
            panel_lims.append({'ax': ax, 'tech': tech, 'x_hi': x_hi, 'floor': floor,
                               'ceil': ceil})
        else:
            ymax = max(v.max() for v in series)
            ax.set_ylim(0, ymax / 0.80)
            panel_lims.append({'ax': ax, 'tech': tech, 'x_hi': x_hi, 'ymax': ymax})
        ax.grid(True, linestyle='--', linewidth=0.6, alpha=0.7)
        ax.legend(loc='upper left', fontsize=8)
        scales.append({'tech': tech, 'form': form, 'lcoe_base_scale': s,
                       'implied_cost_factor_at_gen_frac_max': cf_hi,
                       'observed_cost_factor_at_gen_frac_max': cf_observed,
                       'gen_frac_max': x.max()})
    #One axis range for every panel, so band thickness and curve steepness can be compared by eye
    #across techs instead of only within a panel. Each tech's curves still stop where its own data
    #stops - extending them to the shared limit would manufacture extrapolation that the unsynced
    #figure does not have - so the differing curve lengths are themselves informative: UPV reaches
    #0.45 market share where gas-CC reaches 0.90.
    if sync_axes and panel_lims:
        x_all = max(q['x_hi'] for q in panel_lims)
        if log_y:
            floor_all = min(q['floor'] for q in panel_lims)
            ceil_all = max(q['ceil'] for q in panel_lims)
            pad_all = np.log10(ceil_all / floor_all)
            y_lo = 10 ** (np.log10(floor_all) - 0.05 * pad_all)
            y_hi = 10 ** (np.log10(ceil_all) + 0.17 * pad_all)
        else:
            y_lo, y_hi = 0, max(q['ymax'] for q in panel_lims) / 0.80
        for q in panel_lims:
            q['ax'].set_xlim(0, x_all)
            q['ax'].set_ylim(y_lo, y_hi)
            if log_y:
                _log_ticks(q['ax'])

    for i in range(0, len(techs), ncol):
        axes[i].set_ylabel('Value factor / value-cost factor')
    fig.suptitle(
        f'Value factor vs value-cost factor, LCOE base scaled to match intercepts ({label} fits)'
        + (' - log scale, so the value and cost declines stack' if log_y else '')
        + (' - shared axes' if sync_axes else '')
        + basis_note,
        fontsize=12)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches='tight')
    return fig, pd.DataFrame(scales)


def plot_all_tech_factors(df, output_path, form='power', techs=None):
    """Value factor, cost factor and value-cost factor against market share, every tech on each panel.

    The same numbers as the per-tech VCF figure: the value factor as it is, and the value-cost and
    cost factors with LCOE base scaled by that tech's s from vcf_matched_scale: VCF times s and CF
    divided by s, so scaled VCF = VF / scaled CF still holds point by point. The cost factor is
    drawn directly rather than as 1/CF, so it rises where the other two fall.

    Colours follow the report's tech colours; each tech also has its own marker and a label at its
    last point, since the UPV yellow and wind cyan are low-contrast on white. Storage is left out
    with vcf_separate_techs, as in the per-tech figures.
    """
    techs = vcf_panel_techs(df, techs)
    colors = build_color_map(techs)
    markers = ['o', 's', '^', 'D', 'v', 'P', 'X']
    panels = [('value_factor', 'Value factor'),
              ('cost_factor', 'Cost factor, LCOE base scaled'),
              ('value_cost_factor', 'Value-cost factor, LCOE base scaled')]
    rows = []
    for tech in techs:
        matched = vcf_matched_scale(df, tech, form)
        if matched is None:
            continue
        sc = matched[0]
        d = df[df['tech'] == tech].dropna(subset=['gen_frac', 'value_factor', 'value_cost_factor',
                                                  'cost_factor']).sort_values('gen_frac')
        rows.append(pd.DataFrame({'tech': tech, 'year': d['year'].to_numpy(),
                                  'gen_frac': d['gen_frac'].to_numpy(),
                                  'value_factor': d['value_factor'].to_numpy(),
                                  'cost_factor': d['cost_factor'].to_numpy() / sc,
                                  'value_cost_factor': d['value_cost_factor'].to_numpy() * sc,
                                  'lcoe_base_scale': sc}))
    if not rows:
        return None, pd.DataFrame()
    data = pd.concat(rows, ignore_index=True)
    plotted = list(data['tech'].unique())
    fig, axes = plt.subplots(1, 3, figsize=(14.0, 4.6))
    panel_ends = []
    for ax, (col, title) in zip(axes, panels):
        ends = []
        for k, tech in enumerate(plotted):
            d = data[data['tech'] == tech]
            ax.plot(d['gen_frac'] * 100, d[col], color=colors[tech], lw=1.6,
                    marker=markers[k % len(markers)], ms=5, mec='white', mew=0.6,
                    label=display_tech(tech))
            ends.append([d[col].iloc[-1], d['gen_frac'].iloc[-1] * 100, display_tech(tech)])
        ax.set_title(title, fontsize=10, loc='left')
        panel_ends.append((ax, ends))
        ax.set_xlabel('Market share (% of generation)')
        ax.grid(alpha=0.25, lw=0.6)
        ax.set_xlim(0, data['gen_frac'].max() * 100 * 1.16)
    #VF and VCF share one y range, so the gap between the two panels reads as the cost factor.
    hi = max(data['value_factor'].max(), data['value_cost_factor'].max()) * 1.05
    for ax in (axes[0], axes[2]):
        ax.set_ylim(0, hi)
    axes[1].set_ylim(bottom=min(0.9, data['cost_factor'].min() * 0.95))
    axes[1].axhline(1.0, color=cost_color, lw=0.9, ls=':', zorder=0)
    #Label each line at its last point, nudging labels apart vertically where lines end close
    #together (Coal and Gas-CC finish within a few hundredths of each other). Done after the limits
    #are set, since the minimum gap is a fraction of the axis height.
    for ax, ends in panel_ends:
        lo, hi_y = ax.get_ylim()
        gap = 0.045 * (hi_y - lo)
        ends.sort(key=lambda e: e[0])
        placed = []
        for y, x, label in ends:
            y_lab = y if not placed else max(y, placed[-1] + gap)
            placed.append(y_lab)
            ax.annotate(label, (x, y), xytext=(x + 1.2, y_lab), textcoords='data', fontsize=7,
                        va='center', color='0.25')
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='lower center', ncol=len(plotted), fontsize=8, frameon=False)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(output_path, dpi=200)
    return fig, data

def vcf_log_decomposition(df, tech, form='power'):
    """Exact split of the log decline in value-cost factor into a value part and a cost part.

    VCF is the product VF * (1/CF), and logs turn a product into a sum, so

        -ln VCF  =  -ln VF  +  -ln(1/CF)

    holds at every data point with no fitting anywhere - it is an identity, good to 1e-15 here.
    Levels do not decompose this way: the linear declines of the two parts over-account for the VCF
    decline by about 1.5x, and reading the split off them overstates the cost share badly (39%
    against a true 31% for wind, 35% against 20% for UPV).

    The identity holds for any scaling of LCOE base, but the SHARES do not: scaling shifts ln(1/CF)
    and ln VCF while leaving ln VF alone. The intercept-matched scaling is applied so 1/CF is 1.0 at
    zero market share, which puts both components at zero there and makes the bars a decline from a
    common baseline rather than from an arbitrary offset.

    Returns a per-point table, or None if the tech cannot be scaled."""
    matched = vcf_matched_scale(df, tech, form)
    d = df[df['tech'] == tech].dropna(
        subset=['gen_frac', 'value_factor', 'value_cost_factor', 'inv_cost_factor']
    ).sort_values('gen_frac')
    if matched is None or d.empty:
        return None
    s = matched[0]
    out = pd.DataFrame({
        'tech': tech,
        'form': form,
        'year': d['year'].to_numpy(),
        'gen_frac': d['gen_frac'].to_numpy(),
        'lcoe_base_scale': s,
        'value_factor': d['value_factor'].to_numpy(),
        'inv_cost_factor_scaled': d['inv_cost_factor'].to_numpy() * s,
        'value_cost_factor_scaled': d['value_cost_factor'].to_numpy() * s,
    })
    out['value_decline'] = -np.log(out['value_factor'])
    out['cost_decline'] = -np.log(out['inv_cost_factor_scaled'])
    out['total_decline'] = -np.log(out['value_cost_factor_scaled'])
    out['cost_share'] = out['cost_decline'] / out['total_decline']
    return out


def plot_vcf_decomposition(df, output_path, form='power', techs=None):
    """Stacked bars splitting the log decline in value-cost factor into value and cost parts.

    Bar height is -ln(VCF), the total loss of competitiveness at that market share, and the two
    segments are the exact contributions of falling value and rising cost. Unlike the exponent
    difference from the fits, nothing here is estimated, so the split does not inherit the fitting
    error that makes a ratio of two good fits a poor fit to the ratio."""
    techs = fit_techs if techs is None else techs
    colors = build_color_map(techs)
    fig, axes = plt.subplots(1, len(techs), figsize=(7.2 * len(techs), 5.2), squeeze=False)
    axes = axes[0]
    tables = []
    for ax, tech in zip(axes, techs):
        t = vcf_log_decomposition(df, tech, form)
        if t is None or t.empty:
            ax.set_visible(False)
            continue
        tables.append(t)
        idx = np.arange(len(t))
        ax.bar(idx, t['value_decline'], width=0.74, color=colors[tech], zorder=3,
               label='value factor decline')
        ax.bar(idx, t['cost_decline'], bottom=t['value_decline'], width=0.74, color=cost_color,
               zorder=3, label='cost escalation')
        for i, (total, share) in enumerate(zip(t['total_decline'], t['cost_share'])):
            ax.text(i, total + 0.015 * t['total_decline'].max(), f'{share * 100:.0f}%',
                    ha='center', va='bottom', fontsize=6.5, color=cost_color, zorder=4)

        ax.set_xticks(idx)
        ax.set_xticklabels([f'{g:.2f}\n{int(y)}' for g, y in zip(t['gen_frac'], t['year'])],
                           fontsize=6.5)
        ax.set_title(display_tech(tech))
        ax.set_xlabel('Market share (generation fraction) and year')
        ax.set_ylim(0, t['total_decline'].max() / 0.78)
        ax.grid(True, axis='y', linestyle='--', linewidth=0.6, alpha=0.7)
        ax.set_axisbelow(True)
        ax.legend(loc='upper left', fontsize=8)
        ax.text(
            0.97, 0.97,
            '\n'.join([
                f'LCOE base x {t["lcoe_base_scale"].iloc[0]:.4f} ({form} fits)',
                'ln VCF = ln VF + ln(1/CF), exact',
                f'cost share at x={t["gen_frac"].iloc[-1]:.2f}: {t["cost_share"].iloc[-1] * 100:.0f}%',
            ]),
            transform=ax.transAxes, fontsize=8, va='top', ha='right', multialignment='left',
            zorder=7,
            bbox={'facecolor': 'white', 'edgecolor': '0.7', 'boxstyle': 'round,pad=0.4',
                  'alpha': 0.92})
    axes[0].set_ylabel('Log decline in competitiveness,  -ln(factor)')
    fig.suptitle(
        'Value and cost contributions to the decline in value-cost factor '
        '(percentages are the cost share)', fontsize=12)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches='tight')
    return fig, (pd.concat(tables, ignore_index=True) if tables else pd.DataFrame())


def make_figs(valcostfac_core_path, output_dir=None):
    """Write both pitch figures and the underlying dataframe, next to valcostfac_core.csv by default."""
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(valcostfac_core_path))

    df, df_lcoe = prep_data(valcostfac_core_path)

    with matplotlib.rc_context(default_rc):
        fig_cost_value = plot_plcoe_pitch(
            df,
            df_lcoe,
            output_path=os.path.join(output_dir, 'plcoe_pitch_cost-value-factor.png'),
            use_inverse_value_factor=True,
            use_cost_value_factor=True,
        )
        fig_value_cost = plot_plcoe_pitch(
            df,
            df_lcoe,
            output_path=os.path.join(output_dir, 'plcoe_pitch_value-cost-factor.png'),
            use_inverse_value_factor=False,
            use_cost_value_factor=False,
            show_fits=True,
        )
        fig_value_cost_adj = plot_plcoe_pitch(
            df,
            df_lcoe,
            output_path=os.path.join(output_dir, 'plcoe_pitch_value-cost-factor_adj.png'),
            use_inverse_value_factor=False,
            use_cost_value_factor=False,
            use_adj=True,
            show_fits=True,
        )
        #The VCF pair: value factor against value-cost factor with LCOE base scaled so the two
        #share a fit intercept, under each fit form. Panels cover every tech clearing
        #vcf_min_anchor_gen_frac, not just VRE, so the dispatchable techs' near-absent bands sit
        #beside the VRE ones. The _adj figures above are left as they were.
        df_vcf = load_full_range(valcostfac_core_path, df) if vcf_use_full_range else df
        fig_vcf_lin, scales_lin = plot_vre_vcf(
            df_vcf, os.path.join(output_dir, 'plcoe_pitch_VCF_linear.png'), form='linear')
        fig_vcf_pow, scales_pow = plot_vre_vcf(
            df_vcf, os.path.join(output_dir, 'plcoe_pitch_VCF_power.png'), form='power')
        #The separated techs - storage - in their own figure, on their own axes. Same
        #construction, drawn by the same function; kept apart only because sharing a figure
        #with a tech whose value factor exceeds 1 and whose market share stops near 15%
        #compresses every other panel.
        scales_sep = pd.DataFrame()
        sep = [t for t in vcf_separate_techs if t in set(df_vcf['tech'])]
        if sep:
            fig_vcf_sep, scales_sep = plot_vre_vcf(
                df_vcf, os.path.join(output_dir, 'plcoe_pitch_VCF_power_storage.png'),
                form='power', techs=sep)
            plt.close(fig_vcf_sep)
        #Same figure on one shared pair of axis ranges, for comparing panels against each other
        #rather than reading each on its own. Adds no rows to the scales table.
        fig_vcf_pow_sync, _ = plot_vre_vcf(
            df_vcf, os.path.join(output_dir, 'plcoe_pitch_VCF_power_synced.png'), form='power',
            sync_axes=True)
        #All techs on one set of axes per factor, from the same scaled series as the figure above.
        fig_all, all_tab = plot_all_tech_factors(
            df_vcf, os.path.join(output_dir, 'plcoe_pitch_all_tech_factors.png'), form='power')
        if fig_all is not None:
            plt.close(fig_all)
            all_tab.to_csv(os.path.join(output_dir, 'plcoe_pitch_all_tech_factors.csv'), index=False)
        #Sensitivity: VRE per MWh generated rather than per MWh that could have been, so every
        #tech is on the dispatched basis. VCF is identical; only the value/cost split moves.
        scales_post = pd.DataFrame()
        if vcf_post_curtailment:
            try:
                df_post = apply_post_curtailment(df_vcf, valcostfac_core_path)
                fig_vcf_post, scales_post = plot_vre_vcf(
                    df_post, os.path.join(output_dir, 'plcoe_pitch_VCF_power_synced_postcurt.png'),
                    form='power', sync_axes=True,
                    basis_note=' - VRE per MWh generated (post-curtailment)')
                plt.close(fig_vcf_post)
                scales_post = scales_post.assign(basis='post_curtailment')
            except Exception as e:
                print(f'Post-curtailment VCF figure skipped ({type(e).__name__}: {e}).')
        #Third basis: every tech per MWh available, the mirror of the post-curtailment figure.
        if vcf_available_basis:
            try:
                df_avail = apply_available_basis(df_vcf, valcostfac_core_path)
                fig_vcf_avail, scales_avail = plot_vre_vcf(
                    df_avail, os.path.join(output_dir, 'plcoe_pitch_VCF_power_synced_avail.png'),
                    form='power', sync_axes=True,
                    basis_note=' - every tech per MWh available (VRE resource, others outage-derated)')
                plt.close(fig_vcf_avail)
                scales_post = pd.concat(
                    [scales_post, scales_avail.assign(basis='available_energy')],
                    ignore_index=True)
            except Exception as e:
                print(f'Available-basis VCF figure skipped ({type(e).__name__}: {e}).')
        plt.close(fig_cost_value)
        plt.close(fig_value_cost)
        plt.close(fig_value_cost_adj)
        fig_vcf_bars, decomp = plot_vcf_decomposition(
            #Still VRE-only: it takes fit_techs, and a stacked split of a near-zero total is
            #not worth a panel for the dispatchable techs.
            df_vcf, os.path.join(output_dir, 'plcoe_pitch_VRE_VCF_decomposition.png'),
            form='power')
        plt.close(fig_vcf_bars)
        #Capacity credit of each year's new builds, against the same market-share axis. Read from
        #the runs rather than from valcostfac, and on the full range for the same reason the VCF
        #figures are: the collapse happens above the gen_frac_max cut.
        try:
            fig_cc, cc = plot_capacity_credit(
                df_vcf, os.path.join(output_dir, 'plcoe_pitch_capacity_credit.png'))
            if fig_cc is not None:
                plt.close(fig_cc)
            #Same data, against installed capacity instead of market share.
            fig_cc_cap, _ = plot_capacity_credit(
                df_vcf, os.path.join(output_dir, 'plcoe_pitch_capacity_credit_cap.png'),
                x='cap_gw', cc=cc)
            if fig_cc_cap is not None:
                plt.close(fig_cc_cap)
            #Selected techs' credit in every scenario, not only their own forcing run.
            fig_cc_sc, cc_sc = plot_capacity_credit_by_scenario(
                os.path.join(output_dir, 'plcoe_pitch_capacity_credit_scenarios.png'))
            if fig_cc_sc is not None:
                plt.close(fig_cc_sc)
                cc_sc.to_csv(os.path.join(output_dir, 'plcoe_pitch_capacity_credit_scenarios.csv'),
                             index=False)
        except Exception as e:
            print(f'Capacity-credit figure skipped ({type(e).__name__}: {e}).')
            cc = pd.DataFrame()
        #Storage-specific figures, read from the run that forces storage. Both describe the
        #battery fleet rather than the value/cost plane, so they are not driven by df.
        dur_tab, arb_tab = pd.DataFrame(), pd.DataFrame()
        try:
            from reeds_vs_rev import tech_run_dirs, scenarios_path
            stor_dirs = tech_run_dirs(df_vcf, scenarios_path)
            for tech in vcf_separate_techs:
                if tech not in stor_dirs:
                    continue
                prefix = avail_basis_prefix.get(tech, tech.lower())
                fig_dur, dur_tab = plot_new_build_duration(
                    stor_dirs[tech], os.path.join(output_dir, 'plcoe_pitch_storage_duration.png'),
                    prefix=prefix)
                if fig_dur is not None:
                    plt.close(fig_dur)
                fig_arb, arb_tab = plot_battery_stress_arbitrage(
                    stor_dirs[tech], os.path.join(output_dir, 'plcoe_pitch_storage_arbitrage.png'),
                    prefix=prefix)
                if fig_arb is not None:
                    plt.close(fig_arb)
                break
        except Exception as e:
            print(f'Storage duration/arbitrage figures skipped ({type(e).__name__}: {e}).')
        plt.close(fig_vcf_lin)
        plt.close(fig_vcf_pow)
        plt.close(fig_vcf_pow_sync)
    df.to_csv(os.path.join(output_dir, 'plcoe_pitch_df.csv'), index=False)
    fits = summarize_fits(df)
    fits.to_csv(os.path.join(output_dir, 'plcoe_pitch_fits.csv'), index=False)
    #scales_sep carries the separated techs, which are absent from scales_lin/scales_pow
    #because they are held out of those figures. The table keeps every tech.
    pd.concat([scales_lin.assign(basis='pre_curtailment'),
               scales_pow.assign(basis='pre_curtailment'),
               scales_sep.assign(basis='pre_curtailment') if not scales_sep.empty else scales_sep,
               scales_post],
              ignore_index=True).to_csv(
        os.path.join(output_dir, 'plcoe_pitch_vcf_scales.csv'), index=False)
    decomp.to_csv(os.path.join(output_dir, 'plcoe_pitch_vcf_decomposition.csv'), index=False)
    cc.to_csv(os.path.join(output_dir, 'plcoe_pitch_capacity_credit.csv'), index=False)
    dur_tab.to_csv(os.path.join(output_dir, 'plcoe_pitch_storage_duration.csv'), index=False)
    arb_tab.to_csv(os.path.join(output_dir, 'plcoe_pitch_storage_arbitrage.csv'), index=False)
    return df


if __name__ == '__main__':
    make_figs(valcostfac_core_path)
