import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.spatial import ConvexHull
from scipy.stats import gaussian_kde
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from mpl_toolkits.axes_grid1.inset_locator import inset_axes, mark_inset
from adjustText import adjust_text
from scipy.spatial import ConvexHull, QhullError
from matplotlib.patches import Patch, Rectangle, ConnectionPatch

# -----------------------------
# LOAD + CLEAN 
# -----------------------------
# import data files
disc_cost = pd.read_csv("cmm_disc_cost.csv")
risk = pd.read_csv("cmm_supplyrisk.csv")

# clean up system costs
disc_cost[['Scenario','Material_name']] = disc_cost['Scen'].str.split("_", expand=True)

ref_lookup = disc_cost[disc_cost['Material_name'] == 'Reference'].set_index('Scenario')['Disc_Cost']
ref_lookup['Restrict'] = ref_lookup['Reference']

disc_cost['ref_cost'] = disc_cost['Scenario'].map(ref_lookup)
disc_cost = disc_cost.dropna(subset=["ref_cost"])

disc_cost['Pct_Diff'] = ((disc_cost['Disc_Cost'] - disc_cost['ref_cost']) / disc_cost['ref_cost']) * 100

disc_cost["Pct_Diff"] = (
    disc_cost["Pct_Diff"].astype(float).round(6)
)

disc_cost["Pct_Diff"] = disc_cost["Pct_Diff"].clip(lower=0)

disc_cost = disc_cost[['Scenario', 'Material_name', 'Pct_Diff']]


# clean up supply risk data

symbol_to_full = {
    "Ag": "Silver","Co": "Cobalt","Dy": "Dysprosium","Ga": "Gallium",
    "Hf": "Hafnium","In": "Indium","Li": "Lithium","Mg": "Magnesium",
    "Mn": "Manganese","Nd": "Neodymium","Ni": "Nickel","Pr": "Praseodymium",
    "Sn": "Tin","Tb": "Terbium","Te": "Tellurium","V": "Vanadium","Y": "Yttrium",
    "Cu":"Copper","Al":"Aluminum"
}

risk["Material_name"] = risk["Material"].map(symbol_to_full)
risk = risk.dropna(subset=["Material_name"])
risk = risk[['Material','Material_name', 'APD (60%)', 'COD (20%)', 'RDS (20%)','Supply Risk']]

df = disc_cost.merge(risk, on="Material_name", how="inner")

materials = sorted(df["Material_name"].unique())
cmap = plt.cm.get_cmap("tab20", len(materials))
color_map = {m: cmap(i) for i, m in enumerate(materials)}

# -----------------------------
# SPLIT CASES
# -----------------------------
# baseline (no restrict)
df_without_restrict = df[
    ~df["Scenario"].str.contains("Restrict", case=False, na=False)
]

# augmented (everything, including restrict)
df_with_restrict = df.copy()

df_only_restrict = df[
    df["Scenario"].str.contains("Restrict", case=False, na=False)
]

# -----------------------------
# FIXED RISK FUNCTION
# -----------------------------
def plot_fixed(df_input, filename, title=None):
    df_fixed = df_input.copy()

    df_fixed["Composite_Risk"] = (
        0.6 * df_fixed["APD (60%)"] +
        0.2 * df_fixed["COD (20%)"] +
        0.2 * df_fixed["RDS (20%)"]
    )

    fig, ax = plt.subplots(figsize=(12, 9))
    legend_handles = []

    # Store labels so we can adjust them after all points/ranges are drawn
    texts = []
    label_xs = []
    label_ys = []

    for mat in materials:
        sub = df_fixed[df_fixed["Material_name"] == mat]
        if sub.empty:
            continue

        color = color_map[mat]

        short_label = sub["Material"].iloc[0]
        long_label = sub["Material_name"].iloc[0]
        legend_label = f"{short_label}: {long_label}"

        x = sub["Composite_Risk"].iloc[0]
        n_obs = len(sub)

        y_min = sub["Pct_Diff"].min()
        y_max = sub["Pct_Diff"].max()

        # midpoint used for label placement
        if n_obs == 1:
            y_mid = sub["Pct_Diff"].iloc[0]
        else:
            y_mid = (y_min + y_max) / 2

        # draw a point if only one observation or zero-height range
        if n_obs == 1 or np.isclose(y_min, y_max):
            ax.scatter(
                x,
                y_mid,
                color=color,
                s=80,
                zorder=3
            )

            legend_handles.append(
                Line2D(
                    [0], [0],
                    marker='o',
                    linestyle='None',
                    markerfacecolor=color,
                    markeredgecolor=color,
                    markersize=8,
                    label=legend_label
                )
            )
        else:
            ax.plot(
                [x, x],
                [y_min, y_max],
                color=color,
                linewidth=2.5
            )

            legend_handles.append(
                Line2D(
                    [0], [0],
                    color=color,
                    linewidth=2.5,
                    label=legend_label
                )
            )

        # add shortened label on plot, but store it for later adjustment
        txt = ax.text(
            x,
            y_mid,
            short_label,
            fontsize=11,
            ha='center',
            va='center',
            zorder=5,
            bbox=dict(
                facecolor='white',
                edgecolor='none',
                alpha=0.75,
                pad=1
            )
        )

        texts.append(txt)
        label_xs.append(x)
        label_ys.append(y_mid)

    ax.set_xlabel("Composite supply risk (60/20/20)", fontsize=16)
    ax.set_ylabel("% Difference in Cumulative Discounted System Cost", fontsize=16)

    if title is not None:
        ax.set_title(title, fontsize=18)
    else:
        ax.set_title(os.path.splitext(filename)[0], fontsize=18)

    ax.grid(True)

    # Adjust labels to reduce overlap
    if texts:
        adjust_text(
            texts,
            x=label_xs,
            y=label_ys,
            ax=ax,
            expand=(1.2, 1.4),
            force_text=(0.5, 0.8),
            force_static=(0.2, 0.4),
            arrowprops=dict(
                arrowstyle='-',
                linewidth=0.6,
                alpha=0.6
            )
        )

    if legend_handles:
        ax.legend(
            handles=legend_handles,
            title="Material",
            loc="center left",
            bbox_to_anchor=(1.02, 0.5),
            fontsize=10,
            title_fontsize=11,
            frameon=True
        )

    fig.tight_layout()
    fig.savefig(filename, dpi=300, bbox_inches="tight")
    plt.close(fig)

# -----------------------------
# POLYGON WITH PANELS
# -----------------------------
def plot_polygons_panel(df_input, filename, title=None, use_density=False):
    # Weight grid
    apd_vals = np.linspace(0.5, 0.7, 25)
    cod_vals = np.linspace(0.1, 0.25, 25)

    rows = []
    for a in apd_vals:
        for c in cod_vals:
            r = 1 - a - c
            if r <= 0:
                continue

            tmp = df_input.copy()
            tmp["Composite_Risk"] = (
                a * tmp["APD (60%)"] +
                c * tmp["COD (20%)"] +
                r * tmp["RDS (20%)"]
            )
            rows.append(tmp)

    df_all = pd.concat(rows, ignore_index=True)

    # Split materials into the two panels
    focal_materials = ["Aluminum", "Copper"]
    other_materials = [
        mat for mat in materials
        if mat not in focal_materials
    ]

    panel_materials = [focal_materials, other_materials]
    panel_titles = ["Aluminum and Copper", "All Other Materials"]

    # Do not share axes: each panel can show its own useful range
    fig, axes = plt.subplots(
        ncols=2,
        figsize=(18, 8),
        sharex=False,
        sharey=False
    )

    # Dictionary prevents duplicate legend entries
    legend_handles = {}

    for ax, mats_in_panel, panel_title in zip(
        axes, panel_materials, panel_titles
    ):
        texts = []
        label_xs = []
        label_ys = []

        for mat in mats_in_panel:
            sub = df_all[df_all["Material_name"] == mat]

            if sub.empty:
                continue

            color = color_map[mat]

            short_label = sub["Material"].iloc[0]
            long_label = sub["Material_name"].iloc[0]
            legend_label = f"{short_label}: {long_label}"

            # Actual unique risk/cost combinations
            pts = sub[
                ["Composite_Risk", "Pct_Diff"]
            ].drop_duplicates().to_numpy()

            if len(pts) == 0:
                continue

            x = pts[:, 0]
            y = pts[:, 1]

            # Optional density shading
            if use_density and len(pts) > 1:
                try:
                    kde = gaussian_kde(np.vstack([x, y]))

                    xi, yi = np.mgrid[
                        x.min():x.max():100j,
                        y.min():y.max():100j
                    ]

                    zi = kde(
                        np.vstack([xi.flatten(), yi.flatten()])
                    ).reshape(xi.shape)

                    ax.contourf(
                        xi,
                        yi,
                        zi,
                        levels=6,
                        colors=[color],
                        alpha=0.20
                    )

                except Exception:
                    pass

            # Point fallback for too few points to construct a hull
            if len(pts) < 3:
                x0 = sub["Composite_Risk"].mean()
                y0 = sub["Pct_Diff"].mean()

                ax.scatter(
                    x0,
                    y0,
                    color=color,
                    s=80,
                    zorder=3
                )

                txt = ax.text(
                    x0,
                    y0,
                    short_label,
                    fontsize=11,
                    ha="center",
                    va="center",
                    zorder=5,
                    bbox=dict(
                        facecolor="white",
                        edgecolor="none",
                        alpha=0.75,
                        pad=1
                    )
                )

                texts.append(txt)
                label_xs.append(x0)
                label_ys.append(y0)

                legend_handles[mat] = Line2D(
                    [0], [0],
                    marker="o",
                    linestyle="None",
                    markerfacecolor=color,
                    markeredgecolor=color,
                    markersize=8,
                    label=legend_label
                )

                continue

            # Convex hull / polygon
            try:
                hull = ConvexHull(pts)
                hull_pts = pts[hull.vertices]

                center = hull_pts.mean(axis=0)

                angles = np.arctan2(
                    hull_pts[:, 1] - center[1],
                    hull_pts[:, 0] - center[0]
                )

                hull_pts = hull_pts[np.argsort(angles)]
                hull_pts = np.vstack([hull_pts, hull_pts[0]])

                ax.plot(
                    hull_pts[:, 0],
                    hull_pts[:, 1],
                    color=color,
                    linewidth=2
                )

                ax.fill(
                    hull_pts[:, 0],
                    hull_pts[:, 1],
                    color=color,
                    alpha=0.35
                )

                txt = ax.text(
                    center[0],
                    center[1],
                    short_label,
                    fontsize=11,
                    ha="center",
                    va="center",
                    zorder=5,
                    bbox=dict(
                        facecolor="white",
                        edgecolor="none",
                        alpha=0.75,
                        pad=1
                    )
                )

                texts.append(txt)
                label_xs.append(center[0])
                label_ys.append(center[1])

                legend_handles[mat] = Patch(
                    facecolor=color,
                    edgecolor=color,
                    alpha=0.35,
                    label=legend_label
                )

            except Exception:
                # Fallback if ConvexHull cannot form a polygon
                x0 = sub["Composite_Risk"].mean()
                y0 = sub["Pct_Diff"].mean()

                ax.scatter(
                    x0,
                    y0,
                    color=color,
                    s=80,
                    zorder=3
                )

                txt = ax.text(
                    x0,
                    y0,
                    short_label,
                    fontsize=11,
                    ha="center",
                    va="center",
                    zorder=5,
                    bbox=dict(
                        facecolor="white",
                        edgecolor="none",
                        alpha=0.75,
                        pad=1
                    )
                )

                texts.append(txt)
                label_xs.append(x0)
                label_ys.append(y0)

                legend_handles[mat] = Line2D(
                    [0], [0],
                    marker="o",
                    linestyle="None",
                    markerfacecolor=color,
                    markeredgecolor=color,
                    markersize=8,
                    label=legend_label
                )

        # Adjust labels within each panel independently
        if texts:
            adjust_text(
                texts,
                x=label_xs,
                y=label_ys,
                ax=ax,
                expand=(1.2, 1.4),
                force_text=(0.5, 0.8),
                force_static=(0.2, 0.4),
                arrowprops=dict(
                    arrowstyle="-",
                    linewidth=0.6,
                    alpha=0.6
                )
            )

        ax.set_title(panel_title, fontsize=15)
        ax.set_xlabel("Composite supply risk", fontsize=14)
        ax.set_ylabel(
            "% Difference in Cumulative Discounted System Cost",
            fontsize=14
        )
        ax.grid(True)
        ax.margins(x=0.10, y=0.10)

    # Overall figure title
    if title is not None:
        fig.suptitle(title, fontsize=18, y=0.98)
    else:
        fig.suptitle(
            os.path.splitext(filename)[0],
            fontsize=18,
            y=0.98
        )

    # One legend for both panels
    fig.legend(
        handles=list(legend_handles.values()),
        title="Material",
        loc="center left",
        bbox_to_anchor=(0.86, 0.5),
        fontsize=10,
        title_fontsize=11,
        frameon=True
    )

    # Reserve room at right for the shared legend
    fig.tight_layout(rect=[0, 0, 0.84, 0.94])

    fig.savefig(
        filename,
        dpi=300,
        bbox_inches="tight"
    )
    plt.close(fig)










# -----------------------------
# POLYGON WITH INSET
# -----------------------------


def plot_polygons_with_inset(
    df_input,
    filename,
    title=None,
    use_density=False,
    zoom_ymin=0,
    zoom_ymax=0.045
):
    # ---------------------------------
    # Helper: add labels for later
    # adjustment with adjust_text
    # ---------------------------------
    def add_label(
        target_ax,
        x_value,
        y_value,
        label,
        fontsize,
        text_list,
        x_list,
        y_list
    ):
        txt = target_ax.text(
            x_value,
            y_value,
            label,
            fontsize=fontsize,
            ha="center",
            va="center",
            zorder=6,
            bbox=dict(
                facecolor="white",
                edgecolor="none",
                alpha=0.75,
                pad=0.8
            )
        )

        text_list.append(txt)
        x_list.append(x_value)
        y_list.append(y_value)

    # ---------------------------------
    # Helper: original density style
    #
    # Uses default matplotlib contour colors,
    # as in the earlier version of the plot.
    # ---------------------------------
    def add_original_density(target_ax, x, y):
        if not use_density or len(x) <= 1:
            return

        try:
            kde = gaussian_kde(np.vstack([x, y]))

            xi, yi = np.mgrid[
                x.min():x.max():100j,
                y.min():y.max():100j
            ]

            zi = kde(
                np.vstack([
                    xi.flatten(),
                    yi.flatten()
                ])
            ).reshape(xi.shape)

            target_ax.contourf(
                xi,
                yi,
                zi,
                levels=6,
                alpha=0.20
            )

        except (
            np.linalg.LinAlgError,
            ValueError
        ):
            # KDE is not defined for point-like, horizontal,
            # vertical, or otherwise degenerate cases.
            pass

    # ---------------------------------
    # Helper: plot a material that cannot
    # form a full two-dimensional polygon
    # ---------------------------------
    def draw_degenerate_material(
        x,
        y,
        color,
        short_label,
        legend_label,
        material_key
    ):
        x0 = np.mean(x)
        y0 = np.mean(y)

        x_span = np.ptp(x)
        y_span = np.ptp(y)

        is_point = (
            np.isclose(x_span, 0, atol=1e-12)
            and np.isclose(y_span, 0, atol=1e-12)
        )

        is_horizontal = (
            np.isclose(y_span, 0, atol=1e-12)
            and not np.isclose(x_span, 0, atol=1e-12)
        )

        is_vertical = (
            np.isclose(x_span, 0, atol=1e-12)
            and not np.isclose(y_span, 0, atol=1e-12)
        )

        if is_point:
            ax.scatter(
                x0,
                y0,
                color=color,
                s=80,
                zorder=4
            )

            axins.scatter(
                x0,
                y0,
                color=color,
                s=55,
                zorder=4
            )

            legend_handles[material_key] = Line2D(
                [0],
                [0],
                marker="o",
                linestyle="None",
                markerfacecolor=color,
                markeredgecolor=color,
                markersize=8,
                label=legend_label
            )

        elif is_horizontal:
            ax.plot(
                [x.min(), x.max()],
                [y0, y0],
                color=color,
                linewidth=2,
                zorder=4
            )

            axins.plot(
                [x.min(), x.max()],
                [y0, y0],
                color=color,
                linewidth=1.5,
                zorder=4
            )

            legend_handles[material_key] = Line2D(
                [0],
                [0],
                color=color,
                linewidth=2,
                label=legend_label
            )

        elif is_vertical:
            ax.plot(
                [x0, x0],
                [y.min(), y.max()],
                color=color,
                linewidth=2,
                zorder=4
            )

            axins.plot(
                [x0, x0],
                [y.min(), y.max()],
                color=color,
                linewidth=1.5,
                zorder=4
            )

            legend_handles[material_key] = Line2D(
                [0],
                [0],
                color=color,
                linewidth=2,
                label=legend_label
            )

        else:
            # Collinear diagonal values
            order = np.argsort(x)

            ax.plot(
                x[order],
                y[order],
                color=color,
                linewidth=2,
                zorder=4
            )

            axins.plot(
                x[order],
                y[order],
                color=color,
                linewidth=1.5,
                zorder=4
            )

            legend_handles[material_key] = Line2D(
                [0],
                [0],
                color=color,
                linewidth=2,
                label=legend_label
            )

        add_label(
            ax,
            x0,
            y0,
            short_label,
            11,
            main_texts,
            main_label_xs,
            main_label_ys
        )

        zoom_mask = (
            (y >= zoom_ymin)
            & (y <= zoom_ymax)
        )

        if np.any(zoom_mask):
            add_label(
                axins,
                np.mean(x[zoom_mask]),
                np.mean(y[zoom_mask]),
                short_label,
                8,
                inset_texts,
                inset_label_xs,
                inset_label_ys
            )

    # ---------------------------------
    # Create supply-risk sensitivity grid
    # ---------------------------------
    apd_vals = np.linspace(0.5, 0.7, 25)
    cod_vals = np.linspace(0.1, 0.25, 25)

    rows = []

    for a in apd_vals:
        for c in cod_vals:
            r = 1 - a - c

            if r <= 0:
                continue

            tmp = df_input.copy()

            tmp["Composite_Risk"] = (
                a * tmp["APD (60%)"]
                + c * tmp["COD (20%)"]
                + r * tmp["RDS (20%)"]
            )

            rows.append(tmp)

    df_all = pd.concat(rows, ignore_index=True)

    # ---------------------------------
    # Figure layout
    # Main: left
    # Legend: upper right
    # Zoom inset: lower right
    # ---------------------------------
    fig = plt.figure(figsize=(16, 10))

    gs = fig.add_gridspec(
        nrows=2,
        ncols=2,
        width_ratios=[3.1, 1.9],
        height_ratios=[1.05, 1.35],
        left=0.07,
        right=0.98,
        bottom=0.08,
        top=0.91,
        wspace=0.18,
        hspace=0.16
    )

    ax = fig.add_subplot(gs[:, 0])

    ax_legend = fig.add_subplot(gs[0, 1])
    ax_legend.axis("off")

    axins = fig.add_subplot(gs[1, 1])

    # Makes the inset wider than it is tall
    axins.set_box_aspect(0.72)

    legend_handles = {}

    main_texts = []
    main_label_xs = []
    main_label_ys = []

    inset_texts = []
    inset_label_xs = []
    inset_label_ys = []

    zoom_x_vals = []

    # ---------------------------------
    # Plot each material
    # ---------------------------------
    for mat in materials:
        sub = df_all[
            df_all["Material_name"] == mat
        ].copy()

        if sub.empty:
            continue

        color = color_map[mat]

        short_label = sub["Material"].iloc[0]
        long_label = sub["Material_name"].iloc[0]
        legend_label = f"{short_label}: {long_label}"

        pts = (
            sub[["Composite_Risk", "Pct_Diff"]]
            .drop_duplicates()
            .to_numpy()
        )

        if len(pts) == 0:
            continue

        x = pts[:, 0]
        y = pts[:, 1]

        zoom_pts = pts[
            (pts[:, 1] >= zoom_ymin)
            & (pts[:, 1] <= zoom_ymax)
        ]

        if len(zoom_pts) > 0:
            zoom_x_vals.extend(
                zoom_pts[:, 0].tolist()
            )

        x_span = np.ptp(x)
        y_span = np.ptp(y)

        has_2d_variation = (
            len(pts) >= 3
            and not np.isclose(x_span, 0, atol=1e-12)
            and not np.isclose(y_span, 0, atol=1e-12)
        )

        # ---------------------------------
        # Flat / point / collinear cases
        # ---------------------------------
        if not has_2d_variation:
            draw_degenerate_material(
                x,
                y,
                color,
                short_label,
                legend_label,
                mat
            )
            continue

        # ---------------------------------
        # Convex hull / polygon case
        # ---------------------------------
        try:
            hull = ConvexHull(pts)
            hull_pts = pts[hull.vertices]

            center = hull_pts.mean(axis=0)

            angles = np.arctan2(
                hull_pts[:, 1] - center[1],
                hull_pts[:, 0] - center[0]
            )

            hull_pts = hull_pts[np.argsort(angles)]

            # Close polygon
            hull_pts = np.vstack([
                hull_pts,
                hull_pts[0]
            ])

            # ---------------------------------
            # Main plot
            #
            # Density first, matching the
            # original visual approach.
            # ---------------------------------
            add_original_density(ax, x, y)

            ax.plot(
                hull_pts[:, 0],
                hull_pts[:, 1],
                color=color,
                linewidth=2,
                zorder=3
            )

            ax.fill(
                hull_pts[:, 0],
                hull_pts[:, 1],
                color=color,
                alpha=0.35,
                zorder=2
            )

            add_label(
                ax,
                center[0],
                center[1],
                short_label,
                11,
                main_texts,
                main_label_xs,
                main_label_ys
            )

            # ---------------------------------
            # Zoom inset
            #
            # Same original density treatment,
            # clipped automatically to the inset
            # axis limits set below.
            # ---------------------------------
            add_original_density(axins, x, y)

            axins.plot(
                hull_pts[:, 0],
                hull_pts[:, 1],
                color=color,
                linewidth=1.5,
                zorder=3
            )

            axins.fill(
                hull_pts[:, 0],
                hull_pts[:, 1],
                color=color,
                alpha=0.35,
                zorder=2
            )

            if len(zoom_pts) > 0:
                zoom_center = zoom_pts.mean(axis=0)

                add_label(
                    axins,
                    zoom_center[0],
                    zoom_center[1],
                    short_label,
                    8,
                    inset_texts,
                    inset_label_xs,
                    inset_label_ys
                )

            legend_handles[mat] = Patch(
                facecolor=color,
                edgecolor=color,
                alpha=0.35,
                label=legend_label
            )

        except (
            QhullError,
            ValueError,
            np.linalg.LinAlgError
        ):
            # Covers diagonal collinear cases
            draw_degenerate_material(
                x,
                y,
                color,
                short_label,
                legend_label,
                mat
            )

    # ---------------------------------
    # Main-plot formatting
    # ---------------------------------
    ax.set_xlabel(
        "Composite supply risk",
        fontsize=16
    )

    ax.set_ylabel(
        "% Difference in Cumulative Discounted System Cost",
        fontsize=16
    )

    ax.grid(True, alpha=0.65)
    ax.margins(x=0.03, y=0.04)

    if main_texts:
        adjust_text(
            main_texts,
            x=main_label_xs,
            y=main_label_ys,
            ax=ax,
            expand=(1.2, 1.4),
            force_text=(0.5, 0.8),
            force_static=(0.2, 0.4),
            arrowprops=dict(
                arrowstyle="-",
                linewidth=0.6,
                alpha=0.6
            )
        )

    # ---------------------------------
    # Zoom inset formatting
    # ---------------------------------
    axins.set_ylim(
        zoom_ymin,
        zoom_ymax
    )

    if zoom_x_vals:
        x_low = min(zoom_x_vals)
        x_high = max(zoom_x_vals)

        x_padding = max(
            0.01,
            (x_high - x_low) * 0.07
        )

        x_low_plot = x_low - x_padding
        x_high_plot = x_high + x_padding

    else:
        x_low_plot, x_high_plot = ax.get_xlim()

    axins.set_xlim(
        x_low_plot,
        x_high_plot
    )

    axins.set_title(
        f"Zoom: y = {zoom_ymin:g} to {zoom_ymax:g}",
        fontsize=11,
        pad=8
    )

    axins.set_xlabel("")
    axins.set_ylabel("")

    axins.tick_params(
        axis="both",
        labelsize=8
    )

    axins.grid(True, alpha=0.45)

    if inset_texts:
        adjust_text(
            inset_texts,
            x=inset_label_xs,
            y=inset_label_ys,
            ax=axins,
            expand=(1.1, 1.2),
            force_text=(0.3, 0.5),
            force_static=(0.15, 0.25),
            arrowprops=dict(
                arrowstyle="-",
                linewidth=0.45,
                alpha=0.50
            )
        )

    # ---------------------------------
    # Highlight source range in main plot
    # ---------------------------------
    main_xmin, main_xmax = ax.get_xlim()

    box_xmin = max(x_low_plot, main_xmin)
    box_xmax = min(x_high_plot, main_xmax)

    if box_xmax <= box_xmin:
        box_xmin = main_xmin
        box_xmax = main_xmax

    ax.axhspan(
        zoom_ymin,
        zoom_ymax,
        color="0.92",
        alpha=0.18,
        zorder=0
    )

    zoom_box = Rectangle(
        (box_xmin, zoom_ymin),
        box_xmax - box_xmin,
        zoom_ymax - zoom_ymin,
        fill=False,
        edgecolor="0.35",
        linewidth=1.2,
        linestyle="--",
        zorder=5
    )

    ax.add_patch(zoom_box)

    # ---------------------------------
    # Title and legend
    # ---------------------------------
    if title:
        fig.suptitle(
            title,
            fontsize=18,
            y=0.965
        )

    if legend_handles:
        ax_legend.legend(
            handles=list(legend_handles.values()),
            title="Material",
            loc="upper left",
            fontsize=9,
            title_fontsize=11,
            frameon=True,
            borderaxespad=0
        )

    # ---------------------------------
    # Compute final connector positions
    # after axes placement is finalized
    # ---------------------------------
    fig.canvas.draw()

    source_top_right = fig.transFigure.inverted().transform(
        ax.transData.transform(
            (box_xmax, zoom_ymax)
        )
    )

    source_bottom_right = fig.transFigure.inverted().transform(
        ax.transData.transform(
            (box_xmax, zoom_ymin)
        )
    )

    inset_bbox = axins.get_position()

    inset_top_left = (
        inset_bbox.x0,
        inset_bbox.y1
    )

    inset_bottom_left = (
        inset_bbox.x0,
        inset_bbox.y0
    )

    upper_connector = ConnectionPatch(
        xyA=source_top_right,
        coordsA=fig.transFigure,
        xyB=inset_top_left,
        coordsB=fig.transFigure,
        color="0.40",
        linewidth=1.0,
        alpha=0.85,
        linestyle="--",
        clip_on=False,
        zorder=6
    )

    lower_connector = ConnectionPatch(
        xyA=source_bottom_right,
        coordsA=fig.transFigure,
        xyB=inset_bottom_left,
        coordsB=fig.transFigure,
        color="0.40",
        linewidth=1.0,
        alpha=0.85,
        linestyle="--",
        clip_on=False,
        zorder=6
    )

    fig.add_artist(upper_connector)
    fig.add_artist(lower_connector)

    # ---------------------------------
    # Save
    # ---------------------------------
    fig.savefig(
        filename,
        dpi=300,
        bbox_inches="tight"
    )

    plt.close(fig)

# -----------------------------
# CREATE ALL 6 PLOTS
# -----------------------------

# NEED TO UPDATE TO ONLY RESTRICT ONCE CASES UPDATED
plot_polygons_with_inset(
    df_with_restrict,
    "3_range_with_density_with_restrict_inset.png",
    use_density=True,
    zoom_ymin=0,
    zoom_ymax=0.4,
    title=(""
    )
)

plot_polygons_with_inset(
    df_without_restrict,
    "3_range_with_density_without_restrict_inset.png",
    use_density=True,
    zoom_ymin=0,
    zoom_ymax=0.04,
    title=(
        ""
    )
)