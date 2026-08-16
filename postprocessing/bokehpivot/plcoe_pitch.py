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

# User inputs
valcostfac_core_path = '/data/shared/projects/mmowers/ReEDS/postprocessing/bokehpivot/out/reeds_report/valcostfac_core.csv' #Only used when running this file standalone; run_report_valcostfac.py passes its own path.
years = [2030, 2040, 2050]
max_plcoe = 200
max_cost_value_factor = 5
inv_value_factor_ylim = (0.8, 3)
cost_factor_ylim = (0.8, 3)
fit_techs = ['Onshore Wind','UPV'] #Techs given a dotted OLS fit vs market share on the value/cost-factor figures.

this_dir = os.path.dirname(os.path.abspath(__file__))
tech_style_path = os.path.join(this_dir, 'in', 'reeds2', 'tech_style.csv')
lcoe_base_path = os.path.join(this_dir, 'LCOE_base.csv')
lcoe_usd_mult = 1.041 #Converts LCOE_base.csv from 2022$ to 2023$, matching run_report_valcostfac.py.
#run_report_valcostfac.py's import chain calls reeds.plots.plotparams(), which globally sets bold
#x-large axis labels and larger ticks. Rendering under matplotlib defaults keeps these figures
#identical whether this file is run standalone or from the report. 'backend' is excluded so the
#active backend isn't swapped out mid-run.
default_rc = {k: v for k, v in matplotlib.rcParamsDefault.items() if k != 'backend'}


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
    ax_lcoe.set_ylabel(f'{cap(lcoe_name)} ($/MWh)')
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
            ax.set_ylabel('PLCOE ($/MWh)')
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
        plt.close(fig_cost_value)
        plt.close(fig_value_cost)
        plt.close(fig_value_cost_adj)
    df.to_csv(os.path.join(output_dir, 'plcoe_pitch_df.csv'), index=False)
    fits = summarize_fits(df)
    fits.to_csv(os.path.join(output_dir, 'plcoe_pitch_fits.csv'), index=False)
    return df


if __name__ == '__main__':
    make_figs(valcostfac_core_path)
