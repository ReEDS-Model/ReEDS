'''This file creates two figures with subfigures of LCOE_base vs year, cost factor vs market share, and alternative value/cost-factor views (top), plus example PLCOE vs market share curves for select years (bottom), with lines for each tech.

Run this file on the reeds2 conda environment.
'''
import os
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

# User inputs
valcostfac_core_path = '/data/shared/projects/mmowers/ReEDS/postprocessing/bokehpivot/out/reeds_report/valcostfac_core.csv'
years = [2030, 2040, 2050]
max_plcoe = 200
max_cost_value_factor = 5
inv_value_factor_ylim = (0.8, 3)

this_dir = os.path.dirname(os.path.abspath(__file__))
tech_style_path = os.path.join(this_dir, 'in', 'reeds2', 'tech_style.csv')
df_output_path = os.path.join(this_dir, 'plcoe_pitch_df.csv')

df = pd.read_csv(valcostfac_core_path)
df['cost_value_factor'] = 1 / df['value_cost_factor']
df['inv_value_factor'] = 1 / df['value_factor']

df_lcoe = pd.read_csv(f'{this_dir}/LCOE_base.csv')
df_lcoe_sel = df_lcoe[df_lcoe['year'].isin(years)].copy()
df_lcoe_sel = df_lcoe_sel.pivot_table(index='tech', columns='year', values='lcoe_base')
df_lcoe_sel.columns = ['lcoe_base_' + str(c) for c in df_lcoe_sel.columns]
df_lcoe_sel.reset_index(inplace=True)

df = df.merge(df_lcoe_sel, how='left', on='tech')

for year in years:
    df[f'plcoe_{year}'] = df[f'lcoe_base_{year}'] * df['cost_value_factor']


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
    output_path=None,
    use_inverse_value_factor=True,
    use_cost_value_factor=True,
):
    techs = sorted(df['tech'].unique())
    colors = build_color_map(techs)

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
        if tech_data.empty:
            continue
        ax_lcoe.plot(
            tech_data['year'],
            tech_data['lcoe_base'],
            label=tech,
            color=colors[tech],
            linewidth=1.8,
            marker='o',
            markersize=3,
        )
    ax_lcoe.set_title('LCOE base vs year')
    ax_lcoe.set_xlabel('Year')
    ax_lcoe.set_ylabel('LCOE base ($/MWh)')
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
        ratio_col = 'cost_value_factor'
        ratio_title = '(cost factor)/(value factor) vs market share'
        ratio_ylabel = '(cost factor)/(value factor)'
        ratio_ylim = (0.8, max_cost_value_factor)
        formula_text = 'PLCOE = (LCOE base) * (cost factor)/(value factor)'
    else:
        ratio_col = 'value_cost_factor'
        ratio_title = '(value factor)/(cost factor) vs market share'
        ratio_ylabel = '(value factor)/(cost factor)'
        ratio_ylim = (
            0,
            1 / 0.8,
        )
        formula_text = 'PLCOE = (LCOE base) / ((value factor)/(cost factor))'

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

    # Cost factor vs market share (upper middle-right)
    for tech in techs:
        tech_data = df[df['tech'] == tech].sort_values('gen_frac')
        if tech_data.empty:
            continue
        ax_cf.plot(
            tech_data['gen_frac'],
            tech_data['cost_factor'],
            color=colors[tech],
            alpha=0.9,
            linewidth=1.5,
            linestyle='solid',
            marker='o',
            markersize=3,
        )
    ax_cf.set_title('Cost factor vs market share')
    ax_cf.set_xlabel('Market share (generation fraction)')
    ax_cf.set_ylabel('Cost factor')
    ax_cf.set_ylim(0.8, 3)
    ax_cf.grid(True, linestyle='--', linewidth=0.6, alpha=0.7)

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

    if output_path is None:
        output_path = os.path.join(this_dir, 'plcoe_pitch_cost-value-factor.png')

    fig.savefig(output_path, dpi=300, bbox_inches='tight')
    return fig


if __name__ == '__main__':
    fig_cost_value = plot_plcoe_pitch(
        df,
        df_lcoe,
        output_path=os.path.join(this_dir, 'plcoe_pitch_cost-value-factor.png'),
        use_inverse_value_factor=True,
        use_cost_value_factor=True,
    )
    fig_value_cost = plot_plcoe_pitch(
        df,
        df_lcoe,
        output_path=os.path.join(this_dir, 'plcoe_pitch_value-cost-factor.png'),
        use_inverse_value_factor=False,
        use_cost_value_factor=False,
    )
    plt.close(fig_cost_value)
    plt.close(fig_value_cost)
    df.to_csv(df_output_path, index=False)
