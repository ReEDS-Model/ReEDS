import sys, numpy as np, pandas as pd, matplotlib
matplotlib.use('Agg'); import matplotlib.pyplot as plt
reeds = pd.read_csv(sys.argv[1]); pts = pd.read_csv(sys.argv[2]); out = sys.argv[3]; crv = pd.read_csv(sys.argv[4])
days = pd.read_csv(sys.argv[5]) if len(sys.argv) > 5 else None  # per-stress-day ReEDS credits (optional)
SZN = {'summer':'#d9822b','winter':'#2e6fb7'}  # stress-day halves: May-Oct, Nov-Apr
MINW = 0.01  # stress days under 1% of the year's firm value are not drawn
RM = 1.12
pts['pen_actual'] = pts.batt_mw/pts.peak_mw
reeds['penetration'] = reeds.penetration*RM  # ReEDS: MW / (peak*1.12) -> MW / actual peak
pts['pen_reeds_axis'] = pts.pen_actual
crv['pen'] = crv.mw/crv.peak_mw
def curve(scen, reg, minnew=0):
    d = reeds[(reeds.scenario==scen)&(reeds.transreg==reg)]
    if reg!='National': d = d[d.new_mw>=minnew]
    return d.sort_values('penetration')
def interp(scen, reg, x):
    d = curve(scen, reg, 200)
    if len(d)==0: return np.nan, ''
    flag = 'below ReEDS range' if x < d.penetration.min() else ''
    return float(np.interp(x, d.penetration, d.capacity_credit)), flag
rows=[]
for _,p in pts.iterrows():
    scen = 'battery_4h' if p.duration_h<=4 else 'battery_8h'
    r, f1 = interp(scen, p.region, p.pen_reeds_axis); n, f2 = interp(scen,'National',p.pen_reeds_axis)
    if 4 < p.duration_h < 8:
        r4,_ = interp('battery_4h', p.region, p.pen_reeds_axis); n4,_=interp('battery_4h','National',p.pen_reeds_axis)
        frac=(p.duration_h-4)/4; r=r4+frac*(r-r4); n=n4+frac*(n-n4); scen='4h/8h interp'
    rows.append(dict(id=p.id, source=p.source, region=p.region, dur=p.duration_h, season=p.season, metric=p.metric,
        pen_actual=p.pen_actual, pen_axis=p.pen_reeds_axis, real=p.credit, reeds_region=r, reeds_nat=n,
        diff_region=r-p.credit, diff_nat=n-p.credit, scen=scen, flag=f1))
tab = pd.DataFrame(rows); tab.to_csv(out+'/comparison_table.csv', index=False)
pd.set_option('display.width',250); print(tab.round(3).to_string())

col = {'annual':'#222222','annual (summer-driven)':'#222222','summer':'#d9822b','summer evening':'#c0392b','summer afternoon':'#e8b04b','winter':'#2e6fb7'}
def mk(k): return 'o' if k=='marginal' else 's'
STC={'PJM 2019 (Astrape)':'#7b3294','NYISO 2019 (Astrape)':'#7b3294','CPUC 2021 (E3/Astrape)':'#7b3294'}
def panel(ax, reg, scen, durs, title):
    nat = curve(scen,'National')
    ax.plot(nat.penetration, nat.capacity_credit, '--', color='#888', lw=1.5, label='ReEDS national')
    if days is not None and reg!='National':
        line = curve(scen, reg).set_index('year').penetration
        dd = days[(days.scenario==scen)&(days.transreg==reg)&(days.weight>=MINW)&days.year.isin(line.index)]
        ax.scatter(dd.year.map(line), dd.credit, s=6+250*dd.weight, c=dd.season.map(SZN), alpha=.55, edgecolor='none', zorder=2)
    if reg!='National':
        d = curve(scen, reg)
        ax.plot(d.penetration, d.capacity_credit, '-', color='#2a9d8f', lw=1.5, label=f'ReEDS {reg}')
        ax.scatter(d.penetration, d.capacity_credit, s=8+np.sqrt(d.new_mw)/2, color='#2a9d8f', alpha=.6, zorder=3)
    sel = pts[(pts.region==reg)&(pts.duration_h.isin(durs))] if reg!='National' else pts.iloc[0:0]
    for _,p in sel.iterrows():
        ax.scatter(p.pen_reeds_axis, p.credit, marker=mk(p.kind), s=60, color=col.get(p.season,'k'),
                   edgecolor='white' if p.duration_h in (4,8) else 'k', linewidth=1, zorder=5)
        ax.annotate(p.label, (p.pen_reeds_axis, p.credit), xytext=(5,2+p.dy), textcoords='offset points', fontsize=7, color=col.get(p.season,'k'))
    cc = crv[(crv.region==reg)&(crv.duration_h.isin(durs))]
    for (st,du),g in cc.groupby(['study','duration_h']):
        g=g.sort_values('pen'); c=STC[st]
        ax.plot(g.pen, g.credit, ':' if du in (5,6) else '-', color=c, lw=1.6, marker='D', ms=4, zorder=4)
        ax.annotate(f"{st}{'' if du in (4,8) else f' {du:g}-hr'}", (g.pen.iloc[-1], g.credit.iloc[-1]), xytext=(4,-10), textcoords='offset points', fontsize=7, color=c)
    ax.set_title(title, fontsize=10, loc='left'); ax.set_ylim(-0.02,1.05); ax.set_xlim(0, 0.6)
    ax.grid(alpha=.25); ax.tick_params(labelsize=8, labelbottom=True)
regs4 = [('PJM','PJM'),('MISO','MISO'),('ERCOT','ERCOT'),('SPP','SPP'),('CAISO','CAISO (CPUC)'),('NYISO','NYISO'),('ISONE','ISO-NE'),('WestConnect','WestConnect (WRAP SWEDE)'),('NorthernGrid','NorthernGrid (WRAP MidC)')]
for scen, durs, fn, ttl in [('battery_4h',[1,2,3,4,5],'fig_4h.png','4-hour batteries: real-world credit vs ReEDS battery_4h'),
                            ('battery_8h',[6,8],'fig_8h.png','6 to 8-hour batteries: real-world credit vs ReEDS battery_8h')]:
    regs = regs4 if scen=='battery_4h' else [r for r in regs4 if r[0] in ('PJM','SPP','CAISO','NYISO','ISONE')]
    n=len(regs); ncol=3; nrow=int(np.ceil(n/ncol))
    fig, axs = plt.subplots(nrow, ncol, figsize=(12, 3.4*nrow), sharex=True, sharey=True)
    for ax,(reg,t) in zip(axs.flat, regs): panel(ax, reg, scen, durs, t)
    for ax in list(axs.flat)[n:]: ax.axis('off')
    for ax in axs[-1]: ax.set_xlabel('Battery MW / actual peak load (ReEDS penetration x 1.12)', fontsize=8)
    for ax in axs[:,0]: ax.set_ylabel('Capacity credit', fontsize=8)
    from matplotlib.lines import Line2D
    h=[Line2D([],[],ls='--',color='#888',label='ReEDS national'),Line2D([],[],color='#2a9d8f',marker='o',label='ReEDS region (dot size = new MW)'),
       Line2D([],[],ls='',marker='o',color='#222',label='real-world, marginal'),Line2D([],[],ls='',marker='s',color='#222',label='real-world, average or class-level'),
       Line2D([],[],ls='',marker='o',color='#d9822b',label='summer'),Line2D([],[],ls='',marker='o',color='#c0392b',label='summer evening'),Line2D([],[],ls='',marker='o',color='#2e6fb7',label='winter'),Line2D([],[],ls='',marker='o',color='#222',label='annual or not seasonal'),Line2D([],[],color='#7b3294',marker='D',label='published deployment curve (2019-2021 studies)')]
    if days is not None:
        present = set(days[(days.scenario==scen)&(days.weight>=MINW)].season)
        h += [Line2D([],[],ls='',marker='o',ms=7,color=c,alpha=.55,mec='none',label=f"ReEDS stress day, {k} ({'May-Oct' if k=='summer' else 'Nov-Apr'}; size = share of year)") for k,c in SZN.items() if k in present]
    fig.legend(handles=h, loc='lower center', ncol=4, fontsize=8, frameon=False)
    fig.suptitle(ttl, x=0.01, ha='left', fontsize=12)
    fig.tight_layout(rect=(0,(0.05 if nrow>2 else 0.1)*(1.4 if days is not None else 1),1,0.97)); fig.savefig(out+'/'+fn, dpi=150); plt.close(fig)
rows=[]
for _,c in crv.iterrows():
    if c.duration_h<=4: r,f=interp('battery_4h',c.region,c.pen); n,_=interp('battery_4h','National',c.pen)
    elif c.duration_h>=8: r,f=interp('battery_8h',c.region,c.pen); n,_=interp('battery_8h','National',c.pen)
    else:
        r4,f=interp('battery_4h',c.region,c.pen); n4,_=interp('battery_4h','National',c.pen)
        r8,_=interp('battery_8h',c.region,c.pen); n8,_=interp('battery_8h','National',c.pen)
        fr=(c.duration_h-4)/4; r=r4+fr*(r8-r4); n=n4+fr*(n8-n4)
    rows.append(dict(study=c.study,region=c.region,dur=c.duration_h,mw=c.mw,pen=c.pen,real=c.credit,reeds_region=r,reeds_nat=n,diff_region=r-c.credit,diff_nat=n-c.credit,flag=f))
ct=pd.DataFrame(rows); ct.to_csv(out+'/curve_comparison_table.csv',index=False); print(ct.round(3).to_string())
