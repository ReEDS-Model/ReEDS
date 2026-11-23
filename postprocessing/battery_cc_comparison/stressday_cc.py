"""Per-stress-day battery capacity credit by transreg and nationally, with a check that the
firm-value-weighted mean of the days reproduces the annual credit in the scenarios CSV.

Usage: python stressday_cc.py <run_dir> <stressday_resmarg gdx> <regional cc scenarios csv> <scenario> <out csv>

A day's credit is the new battery's reserve-margin value over that day's stress hours divided by
what the same new MW would earn there if fully firm, summed over the group's zones - the annual
credit of plcoe_pitch.grouped_capacity_credit split by stress day. weight is the day's share of
the year's firm value, so sum(weight * credit) over a year's days is the annual credit.
"""
import sys, os, pandas as pd, numpy as np, gdxpds
run, gdx, scen_csv, scen, out = sys.argv[1:6]
o = os.path.join(run, 'outputs')
d = gdxpds.to_dataframes(gdx)
rh = d['resmarg_h']; rh.columns = ['i', 'r', 'h', 't', 'val']
ph = d['price_h']; ph.columns = ['r', 'h', 't', 'price']
for x in (rh, ph): x['t'] = x['t'].astype(int)
vn = pd.read_csv(os.path.join(o, 'valnew.csv'), names=['metric', 'i', 'r', 't', 'v'], header=0)
vn = vn[vn.i.str.lower().str.startswith('battery')]
w = vn.pivot_table(index=['i', 'r', 't'], columns='metric', values='v').reset_index()
# per-hour value of the new build = vintage value * inv_cap_ratio (report.gms valnew)
rh = rh.merge(w[['i', 'r', 't', 'inv_cap_ratio']], on=['i', 'r', 't'], how='inner')
rh['val'] *= rh['inv_cap_ratio']
chk = rh.groupby(['i', 'r', 't']).val.sum().rename('sum_h').to_frame().join(
    w.set_index(['i', 'r', 't'])['val_resmarg']).fillna(0)
print('max |sum_h - valnew val_resmarg| / max val:', (chk.sum_h - chk.val_resmarg).abs().max() / chk.val_resmarg.abs().max())
# zones as in regional_capacity_credit: MW > 0 and res_marg_ann > 0
mw = w.groupby(['r', 't']).MW.sum()
ann = ph.groupby(['r', 't']).price.sum()
zones = pd.concat([mw, ann], axis=1).dropna()
zones = zones[(zones.MW > 0) & (zones.price > 0)].index
ph['day'] = ph.h.str[:10]
rh['day'] = rh.h.str[:10]
pd_ = ph.groupby(['r', 't', 'day']).price.sum().rename('price_d').reset_index()
pd_ = pd_[pd_.set_index(['r', 't']).index.isin(zones)]
pd_['firm'] = pd_.price_d * pd_.set_index(['r', 't']).index.map(mw).values
vd = rh.groupby(['r', 't', 'day']).val.sum().rename('val').reset_index()
z = pd_.merge(vd, on=['r', 't', 'day'], how='left').fillna({'val': 0})
hier = pd.read_csv(os.path.join(run, 'inputs_case', 'hierarchy.csv'))
hier = hier.rename(columns={hier.columns[0]: 'r'}).set_index('r')['transreg']
rows = []
for zmap in (hier, pd.Series('National', index=hier.index)):
    g = z.assign(grp=z.r.map(zmap)).groupby(['grp', 't', 'day'])[['val', 'firm']].sum().reset_index()
    rows.append(g)
g = pd.concat(rows)
g = g[g.firm > 0]
tot = g.groupby(['grp', 't'])[['val', 'firm']].transform('sum')
g['weight'] = g.firm / tot.firm
g['credit'] = g.val / g.firm
date = pd.to_datetime(g.day.str[2:6] + '-01-01') + pd.to_timedelta(g.day.str[7:10].astype(int) - 1, unit='D')
g['date'] = date.dt.strftime('%Y-%m-%d')
g['season'] = date.dt.month.map({12: 'winter', 1: 'winter', 2: 'winter', 3: 'spring', 4: 'spring', 5: 'spring',
                                  6: 'summer', 7: 'summer', 8: 'summer', 9: 'fall', 10: 'fall', 11: 'fall'})
# check against the scenarios CSV
ann_cc = (g.groupby(['grp', 't']).val.sum() / g.groupby(['grp', 't']).firm.sum()).rename('cc_days')
sc = pd.read_csv(scen_csv); sc = sc[sc.scenario == scen].set_index(['transreg', 'year']).capacity_credit
cmp = ann_cc.to_frame().join(sc.rename_axis(['grp', 't']), how='inner')
print('rows compared:', len(cmp), ' max |diff|:', (cmp.cc_days - cmp.capacity_credit).abs().max())
g = g.rename(columns={'grp': 'transreg', 't': 'year'})
g.insert(0, 'scenario', scen)
g[['scenario', 'transreg', 'year', 'day', 'date', 'season', 'weight', 'credit', 'val', 'firm']].to_csv(out, index=False)
print('wrote', len(g), 'rows')
