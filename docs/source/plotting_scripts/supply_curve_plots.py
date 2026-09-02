'''
Generates maps of the supply curves capacity. 
Can be used to re-create documentation figures or to generate a summary
figure for a presentation.
'''

import sys
import numpy as np
import pandas as pd
from pathlib import Path
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import patheffects as pe
import geopandas as gpd
import shapely
import argparse
import traceback
import cmocean

reeds_path = Path(__file__).resolve().parents[3]
sys.path.append(str(reeds_path))
import reeds
from reeds import plots
from postprocessing import input_plots

plots.plotparams()

savepath = reeds_path / 'docs' / 'source' / 'figs' / 'docs'
savepath.mkdir(parents=True, exist_ok=True)

def saveit(savename, fig=None):
    outpath = savepath / (savename.lower().replace(' ', '-') + '.png')
    (fig or plt.gcf()).savefig(outpath, bbox_inches='tight')
    print(outpath)


def add_capacity_total(ax, df, fontsize=14):
    ax.annotate(
        f'{df.capacity.sum() / 1e6:.0f} TW', (0.08, 0.10),
        xycoords='axes fraction', ha='left', va='bottom', fontsize=fontsize, zorder=1e8,
    )


def plot_docs():
    for tech in ['egs']:
        print(f"plotting supply curve for {tech}")

        if tech == 'egs':
            panels = [
                ('reference', 'capacity', 'Reference access'),
            ]
            fig, ax = plt.subplots(figsize=(6.5, 5.25))
            axes = [ax]
        else:
            panels = [
                ('open', 'capacity', 'Open access'),
                ('reference', 'capacity', 'Reference access'),
                ('limited', 'capacity', 'Limited access'),
                ('open', 'cf', ''),
            ]
            fig, axs = plt.subplots(
                2, 2, figsize=(13, 10.5),
                gridspec_kw={'hspace': 0.08, 'wspace': 0.04},
            )
            axes = axs.flat

        for ax, (access, column, title) in zip(axes, panels):
            f, ax, df, col = next(input_plots.map_supplycurves(
                access=access,
                tech=tech,
                cols_out=column,
                draw_stats=False,
                title=title,
                title_fontsize=16,
                title_fontweight='bold',
                cbar_ticklabel_fontsize=12,
                cbar_title_fontsize=14,
                cbar_labelpad=2.6,
                f=fig,
                ax=ax,
            ))
            if col == 'capacity':
                add_capacity_total(ax, df)
            if col == 'cf':
                capacity_factor_cbar_ax = fig.axes[-2]

        # dividing line settings for capacity factor plot (not used for egs)
        if tech != 'egs':
            capacity_factor_ax = axs[1, 1]
            separator = {'color': '0.55', 'lw': 1.5, 'clip_on': False, 'zorder': 1e9}
            capacity_factor_ax.plot([0, 1], [1, 1], transform=capacity_factor_ax.transAxes, **separator)
            capacity_factor_position = capacity_factor_ax.get_position()        
            fig.canvas.draw()
            caption_bottom = min(
                text.get_window_extent(fig.canvas.get_renderer())
                .transformed(fig.transFigure.inverted()).y0
                for text in capacity_factor_cbar_ax.texts
            )
            # draw dividing line
            fig.add_artist(mpl.lines.Line2D(
                [capacity_factor_position.x0, capacity_factor_position.x0],
                [caption_bottom - 0.005, capacity_factor_position.y1],
                transform=fig.transFigure, **separator,
            ))

        saveit(f"supplycurve {tech}", fig=fig)
        plt.close(fig)


def plot_presentation():
    access_cases = ['open', 'reference', 'limited']
    technologies = {
        'upv': 'Utility-scale PV',
        'wind-ons': 'Land-based wind',
    }
    row_labels = ['Open\naccess', 'Reference\naccess', 'Limited\naccess']

    fig = plt.figure(figsize=(6.5, 5.6))
    grid = fig.add_gridspec(
        4, 2, height_ratios=[1, 1, 1, 0.06],
        left=0.16, right=0.98, bottom=0.09, top=0.94,
        hspace=0.08, wspace=0.06,
    )
    map_axes = np.empty((len(access_cases), len(technologies)), dtype=object)

    for col, (tech, tech_label) in enumerate(technologies.items()):
        colorbar_mappable = None
        for row, (access, row_label) in enumerate(zip(access_cases, row_labels)):
            ax = fig.add_subplot(grid[row, col])
            map_axes[row, col] = ax
            f, ax, df, _ = next(input_plots.map_supplycurves(
                access=access,
                tech=tech,
                cols_out='capacity',
                draw_colorbar=False,
                draw_stats=False,
                f=fig,
                ax=ax,
            ))
            add_capacity_total(ax, df, fontsize=12)
            if row == 0:
                ax.set_title(tech_label, fontsize=12, fontweight='bold', pad=2)
            if col == 0:
                ax.annotate(
                    row_label, (-0.08, 0.5), xycoords='axes fraction',
                    ha='right', va='center', fontsize=10, clip_on=False,
                )
            colorbar_mappable = ax.collections[-1]

        colorbar_ax = fig.add_subplot(grid[-1, col])
        colorbar = fig.colorbar(colorbar_mappable, cax=colorbar_ax, orientation='horizontal')
        colorbar.ax.xaxis.set_major_formatter(
            mpl.ticker.FuncFormatter(lambda value, _: f'{value / 1e3:g}')
        )
        colorbar.ax.tick_params(labelsize=9, pad=1)
        colorbar.set_label('Capacity [GW]', fontsize=10, fontweight='bold', labelpad=2)

    saveit('supplycurve-capacity-summary', fig=fig)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description='Generate supply-curve availability maps.')
    parser.add_argument(
        '--mode', choices=['docs', 'presentation'], default='docs',
        help='Plot layout to generate.',
    )
    args = parser.parse_args()

    try:
        if args.mode == 'docs':
            plot_docs()
        else:
            plot_presentation()
    except Exception:
        print(traceback.format_exc())
        raise


if __name__ == '__main__':
    main()