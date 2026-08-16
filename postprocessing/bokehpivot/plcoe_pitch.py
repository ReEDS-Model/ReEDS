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

    Returns (linregress result, gen_frac min, gen_frac max), or None without enough usable points.
    Non-positive values are dropped before a log fit, as is x >= 1 for the power form."""
    d = df[df['tech'] == tech].dropna(subset=['gen_frac', col])
    if form in ('exp', 'power'):
        d = d[d[col] > 0]
    if form == 'power':
        d = d[d['gen_frac'] < 1]
    if len(d) < 2:
        return None
    x = np.log(1 - d['gen_frac']) if form == 'power' else d['gen_frac']
    y = np.log(d[col]) if form in ('exp', 'power') else d[col]
    return linregress(x, y), d['gen_frac'].min(), d['gen_frac'].max()


def add_tech_fits(ax, df, col, colors, techs):
    """Overlay OLS fits vs market share and annotate each with its equation.

    Two fits per tech: a dotted straight line (linear in level) and a dash-dot curve of the form
    y = A*(1-x)**k. The power-form exponent k is the one quoted for steepness comparisons, since it
    is invariant to rescaling and exactly additive across metrics; showing both makes the difference
    between the models visible, including where the linear fit runs negative."""
    labels = []
    for tech in techs:
        fit = tech_fit(df, col, tech)
        if fit is None:
            continue
        lr, x0, x1 = fit
        xs = np.array([x0, x1])
        ax.plot(
            xs,
            lr.intercept + lr.slope * xs,
            color=colors[tech],
            linestyle=':',
            linewidth=2.0,
            zorder=6,
        )
        labels.append((tech, f'{tech} (lin): y = {lr.slope:.2f}x + {lr.intercept:.2f}  (R$^2$={lr.rvalue ** 2:.2f})'))

        pow_fit = tech_fit(df, col, tech, form='power')
        if pow_fit is None:
            continue
        plr, px0, px1 = pow_fit
        xs_pow = np.linspace(px0, px1, 50)
        amp = np.exp(plr.intercept)
        ax.plot(
            xs_pow,
            amp * (1 - xs_pow) ** plr.slope,
            color=colors[tech],
            linestyle='-.',
            linewidth=1.4,
            alpha=0.9,
            zorder=6,
        )
        labels.append((tech, f'{tech} (pow): y = {amp:.2f}(1-x)$^{{{plr.slope:.2f}}}$  (R$^2$={plr.rvalue ** 2:.2f})'))

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
    """Fit slopes vs market share for the plotted metrics, with each metric's steepening relative to
    the value factor.

    Raw slopes are not comparable across metrics because the curves sit at different levels: the
    value-cost factor starts well below the value factor, so an equal fractional decline shows up as
    a smaller raw slope, and the resulting ratio also moves with the _adj rescaling convention. Treat
    slope_ratio_vs_value_factor as a caution, not a result.

    power_k, the exponent of y = A*(1-x)**k, is the measure to quote. It is invariant to rescaling
    (a constant multiplier moves A, never k) and, because ln(value_cost_factor) = ln(value_factor) +
    ln(1/cost_factor) holds pointwise, the exponents are exactly additive. That shows up in
    power_k_ratio_vs_value_factor: the ratio for value_cost_factor equals 1 plus the ratio for
    inv_cost_factor, so the cost factor's contribution can be read off directly.

    exp_slope (from y = A*exp(m*x)) is kept as an independent cross-check. It shares those two
    properties but asymptotes rather than reaching zero at full market share, and generally fits
    worse. Agreement between exp_slope_ratio_vs_value_factor and power_k_ratio_vs_value_factor is
    evidence the steepness result is a property of the data rather than of the chosen form."""
    techs = fit_techs if techs is None else techs
    cols = ['value_factor','inv_cost_factor','value_cost_factor','inv_cost_factor_adj','value_cost_factor_adj']
    rows = []
    for tech in techs:
        for col in cols:
            fit = tech_fit(df, col, tech)
            if fit is None:
                continue
            lr, x0, x1 = fit
            pw = tech_fit(df, col, tech, form='power')
            ex = tech_fit(df, col, tech, form='exp')
            plr = None if pw is None else pw[0]
            elr = None if ex is None else ex[0]
            rows.append({
                'tech': tech, 'metric': col,
                'gen_frac_min': x0, 'gen_frac_max': x1,
                'power_A': np.nan if plr is None else np.exp(plr.intercept),
                'power_k': np.nan if plr is None else plr.slope,
                'power_r2': np.nan if plr is None else plr.rvalue ** 2,
                'slope': lr.slope, 'intercept': lr.intercept, 'r2': lr.rvalue ** 2,
                'exp_slope': np.nan if elr is None else elr.slope,
                'exp_A': np.nan if elr is None else np.exp(elr.intercept),
                'exp_r2': np.nan if elr is None else elr.rvalue ** 2,
            })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    vf = out[out['metric'] == 'value_factor'].set_index('tech')
    out['power_k_ratio_vs_value_factor'] = out['power_k'] / out['tech'].map(vf['power_k'])
    out['slope_ratio_vs_value_factor'] = out['slope'] / out['tech'].map(vf['slope'])
    out['exp_slope_ratio_vs_value_factor'] = out['exp_slope'] / out['tech'].map(vf['exp_slope'])
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
