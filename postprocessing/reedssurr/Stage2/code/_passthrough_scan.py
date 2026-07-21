import pandas as pd, os
d = r'C:\ReEDS\ReEDS\postprocessing\reedssurr\Stage2\outputs\overall'
m = pd.read_csv(os.path.join(d,'per_output_metrics_rf.csv'))
df = pd.read_csv(r'C:\ReEDS\ReEDS\postprocessing\reedssurr\Stage2\inputs\overall_ml_numeric_merged.csv')
u = df[m['output']].nunique().rename('n_unique')
mm = m.merge(u, left_on='output', right_index=True)
sub = mm[mm.n_unique<=15].sort_values(['n_unique','output'])
for _,r in sub.iterrows():
    print(f"| `{r['output']}` | {int(r['n_unique'])} | {r['r2']:.3f} |")
print('N=',len(sub),'of',len(mm))
