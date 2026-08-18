### Supply curves
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

reeds_path = Path(__file__).resolve().parents[2]
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

try:
    for tech in ['upv', 'wind-ons', 'wind-ofs']:
        print(f"plotting supply curve for {tech}")

        fig, axs = plt.subplots(
            2, 2, figsize=(13, 10.5),
            gridspec_kw={'hspace': 0.08, 'wspace': 0.04},
        )
        panels = [
            ('open', 'capacity', 'Open access'),
            ('reference', 'capacity', 'Reference access'),
            ('limited', 'capacity', 'Limited access'),
            ('open', 'cf', ''),
        ]

        for ax, (access, column, title) in zip(axs.flat, panels):
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
                ax.annotate(
                    f'{df[col].sum() / 1e6:.0f} TW', (0.08, 0.10),
                    xycoords='axes fraction', ha='left', va='bottom',
                    fontsize=14, zorder=1e8,
                )
            if col == 'cf':
                capacity_factor_cbar_ax = fig.axes[-2]

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
        fig.add_artist(mpl.lines.Line2D(
            [capacity_factor_position.x0, capacity_factor_position.x0],
            [caption_bottom - 0.005, capacity_factor_position.y1],
            transform=fig.transFigure, **separator,
        ))

        saveit(f"supplycurve {tech}", fig=fig)
        plt.close(fig)


except Exception:
    print(traceback.format_exc())