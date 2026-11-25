"""Battery dispatch and reserve-margin price on the stress days behind the stress-day dots, one
figure per ISO with a row per year.

Usage: python stressday_dispatch.py <run_dir> <stressday_cc csv> <regional cc scenarios csv>
           <scenario> <out dir> <ISO>[,<ISO>...]

Bars are the new batteries' net output (discharge - charge) as a share of their power capacity, and
the line is the ISO's reserve-margin price, both MW-weighted over the ISO's zones that built that
year - the zones and weights behind the dots. A day's credit is close to the price-weighted mean of
its bars (exact for a single zone); the label gives the exact value from stressday_cc.
Each day is eight 3-hour blocks, in Central Standard Time (ReEDS model time).
"""
import os, sys
import numpy as np, pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

run, days_csv, scen_csv, scen, out, isos = sys.argv[1:7]
YEARS = list(range(2028, 2051, 2))  # every model year from the first market year (report_switches.start_year is 2027)
MINW = 0.01
BAR, PRICE = '#2a9d8f', '#222222'

o = os.path.join(run, 'outputs')
ng = pd.read_csv(os.path.join(o, 'gen_h_stress.csv'), names=['i', 'r', 'h', 't', 'mw'], header=0)
ng = ng[ng.i.str.lower().str.startswith('battery')]
ph = pd.read_csv(os.path.join(o, 'reqt_price.csv'), names=['req', 'na', 'r', 'h', 't', 'price'], header=0)
ph = ph.loc[ph.req == 'res_marg', ['r', 'h', 't', 'price']]
cap = pd.read_csv(os.path.join(o, 'cap_ivrt.csv'), names=['i', 'v', 'r', 't', 'cap'], header=0)
cap = cap[cap.i.str.lower().str.startswith('battery')]
vn = pd.read_csv(os.path.join(run, 'outputs', 'valnew.csv'), names=['metric', 'i', 'r', 't', 'v'], header=0)
vn = vn[vn.i.str.lower().str.startswith('battery')]
mw = vn[vn.metric == 'MW'].groupby(['r', 't']).v.sum()
hier = pd.read_csv(os.path.join(run, 'inputs_case', 'hierarchy.csv'))
hier = hier.rename(columns={hier.columns[0]: 'r'}).set_index('r')['transreg']
ann = ph.groupby(['r', 't']).price.sum()
days = pd.read_csv(days_csv)
days = days[(days.scenario == scen) & (days.weight >= MINW)]
sc = pd.read_csv(scen_csv)
sc = sc[sc.scenario == scen].set_index(['transreg', 'year'])

# output share of each zone's new batteries: fleet net output / fleet CAP, the new MW's share since
# all batteries share one vintage (see stressday_cc.py)
ng = ng.merge(cap.groupby(['r', 't']).cap.sum().reset_index(), on=['r', 't'])
ng['share'] = ng.mw / ng.cap

for iso in isos.split(','):
    rows = [t for t in YEARS if ((days.transreg == iso) & (days.year == t)).any()]
    fig, axs = plt.subplots(len(rows), 1, figsize=(12, 2.4 * len(rows) + 0.6), squeeze=False)
    for ax, t in zip(axs[:, 0], rows):
        z = [r for r in hier.index[hier == iso] if mw.get((r, t), 0) > 0 and ann.get((r, t), 0) > 0]
        w = mw.loc[[(r, t) for r in z]].droplevel('t')
        dd = days[(days.transreg == iso) & (days.year == t)].sort_values('date')
        x0, ticks, ticklabels, prices = 0, [], [], []
        for _, day in dd.iterrows():
            hs = [f'{day.day}h{k:03d}' for k in range(3, 25, 3)]
            sh = (ng[(ng.t == t) & ng.h.isin(hs) & ng.r.isin(z)]
                  .assign(wt=lambda x: x.r.map(w)).assign(v=lambda x: x.share * x.wt)
                  .groupby('h').v.sum().reindex(hs, fill_value=0) / w.sum())
            pr = (ph[(ph.t == t) & ph.h.isin(hs) & ph.r.isin(z)]
                  .assign(v=lambda x: x.price * x.r.map(w)).groupby('h').v.sum()
                  .reindex(hs, fill_value=0) / w.sum() / 1000)
            xs = x0 + np.arange(8)
            ax.bar(xs, sh.values, width=0.8, color=BAR, zorder=2)
            prices.append((xs, pr.values))
            ax.text(x0 + 3.5, 1.32, f'{day.date}\ncredit {day.credit:.2f} | {day.weight:.0%} of year',
                    ha='center', va='bottom', fontsize=7, color='#444')
            ticks += [x0, x0 + 4]; ticklabels += ['0', '12']
            if x0: ax.axvline(x0 - 1, color='#bbb', lw=0.8)
            x0 += 10
        ax.axhline(0, color='#888', lw=0.8)
        ax.set_ylim(-1.15, 1.15); ax.set_xlim(-1, x0 - 1)
        ax.set_xticks(ticks); ax.set_xticklabels(ticklabels, fontsize=7)
        ax.set_ylabel('net output /\nnew MW', fontsize=8, color=BAR); ax.tick_params(axis='y', labelsize=7, colors=BAR)
        ax2 = ax.twinx()
        pmax = max(p.max() for _, p in prices) or 1
        for xs, p in prices:
            ax2.plot(xs, p, color=PRICE, lw=1.4, marker='o', ms=3, zorder=3)
        ax2.set_ylim(-1.15 * pmax, 1.15 * pmax)  # zero lines up with the bars' zero
        ax2.set_yticks([0, float(f'{pmax:.2g}')])
        ax2.set_ylabel('price\n($/kW-yr per block)', fontsize=8, color=PRICE); ax2.tick_params(axis='y', labelsize=7)
        cc, pen = sc.loc[(iso, t), 'capacity_credit'], sc.loc[(iso, t), 'penetration'] * 1.12
        ax.set_title(f'{t}: annual credit {cc:.2f}, batteries {pen:.1%} of peak', loc='left', fontsize=9, pad=36)
    dur = scen.split('_')[-1].replace('h', '-hour')
    fig.suptitle(f'{iso}: new {dur} battery net output and reserve-margin price on stress days '
                 f'(days with at least 1% of the year\'s firm value; hours are CST block starts)',
                 x=0.01, ha='left', fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    fig.savefig(os.path.join(out, f'fig_dispatch_{scen}_{iso}.png'), dpi=150)
    plt.close(fig)
    print('wrote', f'fig_dispatch_{scen}_{iso}.png')
