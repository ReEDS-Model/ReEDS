import argparse
import os
import re
import subprocess
import sys
import tempfile

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
import gams.transfer as gt

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds

REEDS_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
TECH_MAP = os.path.join(REEDS_PATH, 'postprocessing', 'bokehpivot', 'in', 'reeds2', 'tech_map.csv')
TECH_STYLE = os.path.join(REEDS_PATH, 'postprocessing', 'bokehpivot', 'in', 'reeds2', 'tech_style.csv')
CASE_COLORS = {'soft': '#2a78d6', 'hard': '#eb6834'}
CASE_LABELS = {'soft': 'Soft queue', 'hard': 'Hard queue'}
QUEUE_COLOR = '#b8b6ad'
LOST_LOAD = 'Lost Load'
INTERFACE_COLORS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948']
LOST_LOAD_REGION_COLORS = ['#52514e', '#b8b6ad', '#86b6ef']


def export_model_params(case, workdir):
    g00 = os.path.join(case, 'g00files', os.path.basename(case) + '.g00')
    if not os.path.isfile(g00):
        raise FileNotFoundError(g00)
    gms = os.path.join(workdir, 'export_params.gms')
    gdx = os.path.join(workdir, 'model_params.gdx')
    with open(gms, 'w') as f:
        f.write(f"execute_unload '{gdx}', tg_i, ilr, interconnection_start, prescribed_build ;\n")
    result = subprocess.run(
        ['gams', gms, f'r={g00}', 'lo=0', f'o={os.path.join(workdir, "export_params.lst")}'],
        cwd=workdir,
    )
    if result.returncode != 0:
        raise RuntimeError(f'GAMS export of model parameters from {g00} failed with code {result.returncode}')
    m = gt.Container(gdx)
    tg_i = m['tg_i'].records[['tg', 'i']].astype(str)
    ilr = m['ilr'].records.astype({'i': str}).set_index('i')['value']
    interconnection_start = int(m['interconnection_start'].records['value'].iloc[0])
    prescribed = m['prescribed_build'].records.copy()
    prescribed.columns = ['i', 'v', 'r', 't', 'value']
    prescribed = prescribed.astype({'i': str, 'v': str, 'r': str})
    prescribed['t'] = prescribed['t'].astype(int)
    return tg_i, ilr, interconnection_start, prescribed


def build_tech_display():
    techmap = pd.read_csv(TECH_MAP)
    patterns = [
        (re.compile('^' + raw.replace('*', '.*') + '$'), display)
        for raw, display in zip(techmap['raw'], techmap['display'])
    ]
    style = pd.read_csv(TECH_STYLE)
    order = list(style['order'])
    colors = dict(zip(style['order'], style['color']))

    def to_display(i):
        for pattern, display in patterns:
            if pattern.match(str(i).lower()):
                return display
        raise KeyError(f'No tech_map.csv entry matches tech {i!r}')

    return to_display, order, colors


def check_styled(techs, order):
    missing = [t for t in techs if t not in order]
    if missing:
        raise KeyError(f'No tech_style.csv entry for display techs {missing}')


def stack_bars(ax, x, widths, df, order, colors):
    pos_bottom = np.zeros(len(df))
    neg_bottom = np.zeros(len(df))
    for tech in [t for t in order if t in df.columns]:
        values = df[tech].to_numpy()
        pos = np.where(values > 0, values, 0)
        neg = np.where(values < 0, values, 0)
        if pos.any():
            ax.bar(x, pos, width=widths, bottom=pos_bottom, align='edge',
                   color=colors[tech], linewidth=0, label=tech)
            pos_bottom = pos_bottom + pos
        if neg.any():
            ax.bar(x, neg, width=widths, bottom=neg_bottom, align='edge',
                   color=colors[tech], linewidth=0, label=tech)
            neg_bottom = neg_bottom + neg


def plot_buildouts(cases, to_display, order, colors, outdir):
    new = {}
    for key, case in cases.items():
        df = reeds.io.read_output(case, 'cap_new_out')
        df['tech'] = df['i'].map(to_display)
        new[key] = df.groupby(['t', 'tech'])['Value'].sum().unstack('tech').fillna(0) / 1e3
    years = sorted(set(new['soft'].index) | set(new['hard'].index))
    techs = sorted(set(new['soft'].columns) | set(new['hard'].columns))
    check_styled(techs, order)
    for key in new:
        new[key] = new[key].reindex(index=years, columns=techs).fillna(0)
    diff = new['hard'] - new['soft']

    f, ax = plt.subplots(3, 1, figsize=(8, 9), sharex=True,
                         gridspec_kw={'height_ratios': [1, 1, 0.8], 'hspace': 0.12})
    width = 3.5
    x = np.array(years) - width / 2
    for row, key in enumerate(['soft', 'hard']):
        stack_bars(ax[row], x, width, new[key], order, colors)
        ax[row].set_ylabel(f'{CASE_LABELS[key]}\nnew capacity [GW]')
    ymax = max(ax[0].get_ylim()[1], ax[1].get_ylim()[1])
    for row in [0, 1]:
        ax[row].set_ylim(0, ymax)
    stack_bars(ax[2], x, width, diff, order, colors)
    ax[2].axhline(0, c='k', lw=0.75)
    ax[2].set_ylabel('Hard − soft\nnew capacity [GW]')
    ax[2].set_xticks(years)
    for a in ax:
        a.spines[['top', 'right']].set_visible(False)
        a.grid(axis='y', color='#e5e4e0', lw=0.5)
        a.set_axisbelow(True)
    handles = {}
    for a in ax:
        for h, lab in zip(*a.get_legend_handles_labels()):
            handles.setdefault(lab, h)
    labels = [t for t in order if t in handles]
    f.legend([handles[t] for t in labels[::-1]], labels[::-1],
             loc='center left', bbox_to_anchor=(0.92, 0.5), frameon=False, fontsize=9)
    path = os.path.join(outdir, 'buildouts_new_capacity.png')
    f.savefig(path, dpi=200, bbox_inches='tight')
    plt.close(f)
    return path, new, diff


def rep_period_weights(case):
    sw = reeds.io.get_switches(case)
    hours_per_period = {'day': 24, 'wek': 120, 'year': 24}[sw.GSw_HourlyType]
    hmap = pd.read_csv(os.path.join(case, 'inputs_case', 'rep', 'hmap_myr.csv'))
    if sw.GSw_HourlyType == 'year':
        weights = hmap['actual_period'].value_counts().sort_index() // hours_per_period
    else:
        weights = hmap['season'].value_counts() // hours_per_period
    return weights


def dispatch_tables(case, year, to_display):
    gen_rep = reeds.io.read_output(case, 'gen_h')
    gen_rep = gen_rep.loc[gen_rep['t'] == year]
    gen_stress = reeds.io.read_output(case, 'gen_h_stress')
    gen_stress = gen_stress.loc[gen_stress['t'] == year]
    gen = pd.concat([gen_rep, gen_stress], ignore_index=True)
    gen['tech'] = gen['i'].map(to_display)
    table = gen.groupby(['h', 'tech'])['Value'].sum().unstack('tech').fillna(0) / 1e3

    lost = reeds.io.read_output(case, 'lost_load_h')
    lost = lost.loc[lost['t'] == year].groupby('h')['Value'].sum() / 1e3
    table[LOST_LOAD] = lost.reindex(table.index).fillna(0)

    prm = reeds.io.read_output(case, 'prm')
    prm = prm.loc[prm['t'] == year].set_index('r')['Value']

    reqt = reeds.io.read_output(case, 'reqt_quant')
    reqt.columns = ['req', 'subtype', 'r', 'h', 't', 'Value']
    load_rep = reqt.loc[(reqt['req'] == 'eq_loadcon') & (reqt['t'] == year)].copy()
    load_rep = load_rep.loc[~load_rep['h'].str.startswith('s')]
    load_rep['prm'] = load_rep['r'].map(prm)
    if load_rep['prm'].isna().any():
        raise KeyError(f'Missing PRM for regions {sorted(load_rep.loc[load_rep.prm.isna(), "r"].unique())} in {year}')
    load_rep['with_prm'] = load_rep['Value'] * (1 + load_rep['prm'])

    load_stress = reeds.io.read_output(case, 'load_stress')
    load_stress = load_stress.loc[load_stress['t'] == year].copy()
    load_stress['prm'] = load_stress['r'].map(prm)
    if load_stress['prm'].isna().any():
        raise KeyError(f'Missing PRM for stress regions in {year}')
    load_stress['actual'] = load_stress['Value'] / (1 + load_stress['prm'])

    load = pd.concat([
        pd.DataFrame({
            'load': load_rep.groupby('h')['Value'].sum(),
            'load_prm': load_rep.groupby('h')['with_prm'].sum(),
        }),
        pd.DataFrame({
            'load': load_stress.groupby('h')['actual'].sum(),
            'load_prm': load_stress.groupby('h')['Value'].sum(),
        }),
    ]) / 1e3
    return table, load


def x_positions(hs, weights=None):
    periods = pd.Series(hs, index=hs).str.rsplit('h', n=1).str[0]
    lefts, widths, bounds = [], [], []
    cursor = 0.0
    for period in pd.unique(periods):
        members = periods.index[periods == period]
        span = float(weights[period]) if weights is not None else float(len(members))
        step = span / len(members)
        bounds.append((cursor, period, span))
        for k in range(len(members)):
            lefts.append(cursor + k * step)
            widths.append(step)
        cursor += span
    return np.array(lefts), np.array(widths), bounds, cursor


def draw_load(ax, lefts, widths, load):
    edges = np.append(lefts, lefts[-1] + widths[-1])
    for col, style, label in [('load', '-', 'Load'), ('load_prm', '--', 'Load × (1 + PRM)')]:
        values = load[col].to_numpy()
        ax.stairs(values, edges, color='#0b0b0b', lw=1.2, ls=style, label=label, baseline=None)


def period_label(period):
    stamp = period.lstrip('s')
    return reeds.timeseries.h2timestamp(stamp).strftime('%Y-%m-%d')


def plot_dispatch_year(cases, year, to_display, order, colors, outdir):
    data = {key: dispatch_tables(case, year, to_display) for key, case in cases.items()}
    techs = sorted(set().union(*[set(t.columns) for t, _ in data.values()]))
    check_styled(techs, order)
    weights = {key: rep_period_weights(case) for key, case in cases.items()}

    rep_totals = []
    stress_counts = []
    for key in cases:
        table, _ = data[key]
        rep_h = sorted(h for h in table.index if not h.startswith('s'))
        stress_h = sorted(h for h in table.index if h.startswith('s'))
        rep_totals.append(x_positions(rep_h, weights[key])[3])
        stress_counts.append(len(stress_h))
    xmax = [max(rep_totals), max(stress_counts)]
    width_ratio = [3, max(1.2, 3 * max(stress_counts) / max(1, len(rep_h)))] if max(stress_counts) else [1]

    ncols = 2 if max(stress_counts) else 1
    f, ax = plt.subplots(2, ncols, figsize=(15, 7), sharey=True, squeeze=False,
                         gridspec_kw={'width_ratios': width_ratio, 'wspace': 0.04, 'hspace': 0.35})
    for row, key in enumerate(['soft', 'hard']):
        table, load = data[key]
        rep_h = sorted(h for h in table.index if not h.startswith('s'))
        stress_h = sorted(h for h in table.index if h.startswith('s'))
        panels = [(rep_h, weights[key], 'Representative periods (width = days represented)')]
        if ncols == 2:
            panels.append((stress_h, None, 'Stress periods'))
        for col, (hs, w, xlabel) in enumerate(panels):
            a = ax[row, col]
            if not hs:
                a.axis('off')
                continue
            missing_load = load.reindex(hs).isna().any(axis=1)
            if missing_load.any():
                raise KeyError(f'No load for {list(missing_load[missing_load].index)} in {key} {year}')
            lefts, widths, bounds, total = x_positions(hs, w)
            stack_bars(a, lefts, widths, table.loc[hs], order, colors)
            draw_load(a, lefts, widths, load.reindex(hs))
            for start, period, span in bounds:
                a.axvline(start, c='w', lw=0.6)
                label = period_label(period) + (f' ({int(span)})' if w is not None else '')
                a.annotate(label, (start, 1.0), xycoords=('data', 'axes fraction'),
                           rotation=45, fontsize=7, ha='left', va='bottom')
            a.set_xlim(0, xmax[col])
            a.set_xticks([])
            a.axhline(0, c='k', lw=0.6, ls=':')
            a.spines[['top', 'right']].set_visible(False)
            if row == 1:
                a.set_xlabel(xlabel, fontsize=9)
        ax[row, 0].set_ylabel(f'{CASE_LABELS[key]}\n{year} generation [GW]')
    handles = {}
    for a in ax.flat:
        for h, lab in zip(*a.get_legend_handles_labels()):
            handles.setdefault(lab, h)
    tech_labels = [t for t in order if t in handles]
    line_labels = [lab for lab in ['Load', 'Load × (1 + PRM)'] if lab in handles]
    labels = tech_labels[::-1] + line_labels
    f.legend([handles[lab] for lab in labels], labels, loc='center left',
             bbox_to_anchor=(0.91, 0.5), frameon=False, fontsize=8)
    path = os.path.join(outdir, f'dispatch_rep_stress_{year}.png')
    f.savefig(path, dpi=200, bbox_inches='tight')
    plt.close(f)
    return path


def queue_tables(cases, tg_i, ilr, interconnection_start, prescribed):
    limits = {}
    for key, case in cases.items():
        q = pd.read_csv(os.path.join(case, 'inputs_case', 'queue_limit.csv'))
        q.columns = ['tg', 'r', 't', 'limit']
        limits[key] = q
    merged = limits['soft'].merge(limits['hard'], on=['tg', 'r', 't'], suffixes=('_soft', '_hard'), how='outer')
    if merged[['limit_soft', 'limit_hard']].isna().any().any() or not np.allclose(merged['limit_soft'], merged['limit_hard']):
        raise ValueError('queue_limit.csv differs between the two cases')
    queue = limits['hard']
    queue_year = int(queue['t'].max())
    queue = queue.loc[queue['t'] == queue_year].groupby(['tg', 'r'])['limit'].sum()

    i_to_tg = tg_i.set_index('i')['tg']
    built = {}
    for key, case in cases.items():
        df = reeds.io.read_output(case, 'cap_new_out')
        df = df.loc[(df['t'] >= interconnection_start) & (df['t'] <= queue_year)]
        df = df.loc[df['i'].isin(i_to_tg.index)].copy()
        missing_ilr = sorted(set(df['i']) - set(ilr.index))
        if missing_ilr:
            raise KeyError(f'No ilr for techs {missing_ilr}')
        df['inv'] = df['Value'] * df['i'].map(ilr)
        df['tg'] = df['i'].map(i_to_tg)
        built[key] = df.groupby(['tg', 'r'])['inv'].sum()

    pres = prescribed.loc[
        (prescribed['t'] >= interconnection_start)
        & (prescribed['t'] <= queue_year)
        & prescribed['i'].isin(i_to_tg.index)
    ].copy()
    pres['tg'] = pres['i'].map(i_to_tg)
    pres = pres.groupby(['tg', 'r'])['value'].sum()

    table = pd.concat(
        {'queue': queue, 'prescribed': pres, 'soft': built['soft'], 'hard': built['hard']}, axis=1,
    ).fillna(0) / 1e3
    table = table.loc[table.abs().max(axis=1) > 0]
    for key in ['soft', 'hard']:
        short = table.loc[table[key] < table['prescribed'] - 1e-3]
        if len(short):
            raise ValueError(f'{key} case built less than its prescribed builds:\n{short}')
    return table, queue_year


def clustered(ax, table):
    groups = list(table.index)
    x = np.arange(len(groups))
    width = 0.26
    series = [('queue', QUEUE_COLOR, 'Queue limit'),
              ('soft', CASE_COLORS['soft'], f"Built – {CASE_LABELS['soft'].lower()}"),
              ('hard', CASE_COLORS['hard'], f"Built – {CASE_LABELS['hard'].lower()}")]
    for k, (col, color, label) in enumerate(series):
        ax.bar(x + (k - 1) * width, table[col], width=width * 0.92, color=color, label=label, linewidth=0)
        if col in ('soft', 'hard'):
            ax.bar(x + (k - 1) * width, table['prescribed'], width=width * 0.92, color=color,
                   hatch='////', edgecolor='white', linewidth=0)
    ax.set_xticks(x)
    ax.set_xticklabels(groups, rotation=30, ha='right')
    ax.spines[['top', 'right']].set_visible(False)
    ax.grid(axis='y', color='#e5e4e0', lw=0.5)
    ax.set_axisbelow(True)


def queue_legend(ax, **kwargs):
    handles, labels = ax.get_legend_handles_labels()
    handles.append(Patch(facecolor='white', edgecolor='#52514e', hatch='////', linewidth=0))
    labels.append('Prescribed builds')
    ax.legend(handles, labels, frameon=False, fontsize=9, **kwargs)


def plot_queue(cases, tg_i, ilr, interconnection_start, prescribed, outdir):
    table, queue_year = queue_tables(cases, tg_i, ilr, interconnection_start, prescribed)
    total = table.groupby(level='tg').sum()
    total = total.sort_values('queue', ascending=False)

    f, ax = plt.subplots(figsize=(9, 4.5))
    clustered(ax, total)
    ax.set_ylabel(f'Capacity {interconnection_start}–{queue_year} [GW]')
    queue_legend(ax, loc='upper right')
    path_total = os.path.join(outdir, f'queue_limit_vs_built_{queue_year}.png')
    f.savefig(path_total, dpi=200, bbox_inches='tight')
    plt.close(f)

    regions = sorted(table.index.get_level_values('r').unique())
    tgs = list(total.index)
    f, ax = plt.subplots(len(regions), 1, figsize=(9, 2.6 * len(regions)), sharex=True, squeeze=False)
    for row, r in enumerate(regions):
        sub = table.xs(r, level='r').reindex(tgs).fillna(0)
        clustered(ax[row, 0], sub)
        ax[row, 0].set_ylabel(f'{r}\n[GW]')
    queue_legend(ax[0, 0], ncol=4, loc='lower left', bbox_to_anchor=(0, 1.02))
    path_region = os.path.join(outdir, f'queue_limit_vs_built_{queue_year}_by_region.png')
    f.savefig(path_region, dpi=200, bbox_inches='tight')
    plt.close(f)
    return path_total, path_region, table


def plot_stress_transmission(case, first_year, outdir, min_util=0.05):
    util = reeds.io.read_output(case, 'tran_util_h_stress')
    util['interface'] = util['r'] + ' → ' + util['rr']
    lost = reeds.io.read_output(case, 'lost_load_h')
    lost = lost.loc[lost['h'].str.startswith('s')]
    years = sorted(t for t in util['t'].unique() if t >= first_year)
    if not years:
        raise ValueError(f'No stress-period transmission results at or after {first_year}')
    util = util.loc[util['t'].isin(years)]

    peak = util.groupby('interface')['Value'].max()
    interfaces = list(peak.loc[peak > min_util].sort_values(ascending=False).index)
    dropped = sorted(peak.loc[peak <= min_util].index)
    if dropped:
        dropped_text = [d.replace('→', '->') for d in dropped]
        print(f'Interfaces not shown (utilization never above {min_util:.0%}): {dropped_text}')
    regions = sorted(lost.loc[lost['t'].isin(years), 'r'].unique())
    if len(regions) > len(LOST_LOAD_REGION_COLORS):
        raise ValueError(f'{len(regions)} regions with lost load but only {len(LOST_LOAD_REGION_COLORS)} colors')
    region_colors = dict(zip(regions, LOST_LOAD_REGION_COLORS))

    hours_by_year = {t: sorted(util.loc[util['t'] == t, 'h'].unique()) for t in years}
    nrows = 1 + len(interfaces)
    f, ax = plt.subplots(
        nrows, len(years), figsize=(5 * len(years) + 2, 1.9 + 1.25 * nrows), sharey='row', squeeze=False,
        gridspec_kw={'width_ratios': [len(hours_by_year[t]) for t in years],
                     'height_ratios': [2] + [1] * len(interfaces), 'wspace': 0.05, 'hspace': 0.15},
    )
    for col, t in enumerate(years):
        hs = hours_by_year[t]
        lefts, widths, bounds, total = x_positions(hs)
        edges = np.append(lefts, lefts[-1] + widths[-1])

        ll = lost.loc[lost['t'] == t].pivot_table(index='h', columns='r', values='Value', aggfunc='sum')
        ll = ll.reindex(index=hs, columns=regions).fillna(0) / 1e3
        bottom = np.zeros(len(hs))
        for r in regions:
            ax[0, col].bar(lefts, ll[r], width=widths, bottom=bottom, align='edge',
                           color=region_colors[r], linewidth=0, label=f'Lost load – {r}')
            bottom = bottom + ll[r].to_numpy()
        shed = ll.sum(axis=1).to_numpy() > 0

        ut = util.loc[util['t'] == t].pivot_table(index='h', columns='interface', values='Value', aggfunc='sum')
        ut = ut.reindex(index=hs, columns=interfaces).fillna(0) * 100
        for row, interface in enumerate(interfaces, start=1):
            a = ax[row, col]
            for left, width, s in zip(lefts, widths, shed):
                if s:
                    a.axvspan(left, left + width, color='#f3e3d3', lw=0)
            a.stairs(ut[interface].to_numpy(), edges, fill=True, color=INTERFACE_COLORS[0], alpha=0.85)
            a.set_ylim(0, 105)
            a.set_yticks([0, 50, 100])
            if col == 0:
                a.set_ylabel(interface, rotation=0, ha='right', va='center', fontsize=9)

        for row in range(nrows):
            a = ax[row, col]
            for start, period, span in bounds:
                a.axvline(start, c='#d0cfca', lw=0.6)
            a.set_xlim(0, total)
            a.set_xticks([])
            a.spines[['top', 'right']].set_visible(False)
            a.grid(axis='y', color='#e5e4e0', lw=0.5)
            a.set_axisbelow(True)
        for start, period, span in bounds:
            ax[0, col].annotate(period_label(period), (start, 1.0), xycoords=('data', 'axes fraction'),
                                rotation=45, fontsize=7, ha='left', va='bottom')
        ax[-1, col].set_xlabel(f'{t} stress periods', fontsize=9)
    ax[0, 0].set_ylabel('Lost load [GW]')
    f.text(0.005, 0.38, 'Interface utilization [%]', rotation=90, va='center', fontsize=10)
    handles = {}
    for a in ax[0, :]:
        for h, lab in zip(*a.get_legend_handles_labels()):
            handles.setdefault(lab, h)
    labels = list(handles)
    handles_list = [handles[lab] for lab in labels]
    handles_list.append(Patch(facecolor='#f3e3d3', linewidth=0))
    labels.append('Hours with lost load')
    f.legend(handles_list, labels, loc='upper left', bbox_to_anchor=(0.91, 0.88), frameon=False, fontsize=8)
    path = os.path.join(outdir, 'stress_transmission_utilization.png')
    f.savefig(path, dpi=200, bbox_inches='tight')
    plt.close(f)
    return path


def main(soft, hard, outdir):
    cases = {'soft': os.path.abspath(soft), 'hard': os.path.abspath(hard)}
    for case in cases.values():
        if not os.path.isdir(case):
            raise FileNotFoundError(case)
    os.makedirs(outdir, exist_ok=True)
    to_display, order, colors = build_tech_display()
    with tempfile.TemporaryDirectory() as workdir:
        tg_i, ilr, interconnection_start, prescribed = export_model_params(cases['hard'], workdir)

    written = []
    path, _, _ = plot_buildouts(cases, to_display, order, colors, outdir)
    written.append(path)

    years = sorted(
        set(reeds.io.read_output(cases['soft'], 'gen_h')['t'])
        & set(reeds.io.read_output(cases['hard'], 'gen_h')['t'])
    )
    for year in years:
        written.append(plot_dispatch_year(cases, year, to_display, order, colors, outdir))

    path_total, path_region, table = plot_queue(cases, tg_i, ilr, interconnection_start, prescribed, outdir)
    written += [path_total, path_region]
    written.append(plot_stress_transmission(cases['hard'], interconnection_start, outdir))
    print(table.round(3).to_string())
    for path in written:
        print(path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Compare soft and hard interconnection queue cases')
    parser.add_argument('--soft', required=True, help='Path to the soft-queue case')
    parser.add_argument('--hard', required=True, help='Path to the hard-queue case')
    parser.add_argument('--outdir', required=True, help='Folder for the figures')
    args = parser.parse_args()
    main(args.soft, args.hard, args.outdir)
