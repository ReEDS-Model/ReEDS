"""Map of the ERCOT balancing areas used by the regional surrogate layer.

BA polygons: ReEDS BA shapefile (inputs/shapefiles/US_PCA, Albers equal
area); ERCOT = the seven Texas BAs whose interconnect is 'texas' (p60-p65,
p67), each filled with its own colour. County boundaries: TIGER 2022
counties cached under inputs/shapefiles/cache, clipped to the seven BAs and
drawn in black. Nothing outside the seven BAs is drawn.

Writes figs/fig08_ercot_bas.pdf/.png and data/08_ercot_bas.csv.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd

from pesgm_common import DATA, PALETTE, REPO, new_fig, save_fig

SHP = REPO / "inputs" / "shapefiles"
ERCOT = ["p60", "p61", "p62", "p63", "p64", "p65", "p67"]
COLORS = dict(zip(ERCOT, [PALETTE[0], PALETTE[1], PALETTE[2], PALETTE[3], PALETTE[4], PALETTE[6], PALETTE[7]]))


def main():
    ba = gpd.read_file(SHP / "US_PCA" / "US_PCA.shp")
    tx = ba[ba.st == "tx"].copy()
    counties = gpd.read_file(SHP / "cache" / "tl_2022_us_county" / "tl_2022_us_county.shp")
    counties = counties[counties.STATEFP == "48"].to_crs(tx.crs)
    ercot_union = tx[tx.rb.isin(ERCOT)].unary_union
    counties = counties[counties.intersects(ercot_union)].copy()
    counties["geometry"] = counties.geometry.intersection(ercot_union)   # clip to the 7 BAs
    pts = gpd.read_file(SHP / "transmission_endpoints" / "transmission_endpoints.shp").set_index("ba_str")
    pd.DataFrame([dict(ba=r, name=pts.loc[r, "name"], lon=pts.loc[r, "lon"], lat=pts.loc[r, "lat"])
                  for r in ERCOT]).to_csv(DATA / "08_ercot_bas.csv", index=False)

    fig, ax = new_fig(height=3.0)
    ax.set_axis_off()
    ax.grid(False)
    ercot = tx[tx.rb.isin(ERCOT)]
    ercot.plot(ax=ax, color=[COLORS[r] for r in ercot.rb], alpha=0.75, edgecolor="none", zorder=1)
    counties.plot(ax=ax, facecolor="none", edgecolor="#0b0b0b", linewidth=0.25, zorder=2)
    ercot.plot(ax=ax, facecolor="none", edgecolor="#0b0b0b", linewidth=0.9, zorder=3)
    for r, geom in zip(ercot.rb, ercot.geometry):
        c = geom.representative_point()
        ax.text(c.x, c.y, r, ha="center", va="center", fontsize=8, fontweight="bold", zorder=4,
                color="#0b0b0b", bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.75))
    minx, miny, maxx, maxy = ercot.total_bounds
    ax.set_xlim(minx - 15e3, maxx + 15e3)
    ax.set_ylim(miny - 15e3, maxy + 15e3)
    ax.set_aspect("equal")
    save_fig(fig, "fig08_ercot_bas")


if __name__ == "__main__":
    main()
