"""Dump valcost_equivalence_<case>.gdx to csv, one row per (stream, i, r, t).

Usage: python reeds/core/terminus/valcost_equivalence.py <casedir>
Writes <casedir>/outputs/valcost_equivalence.csv and valcost_equivalence_rc.csv.
"""
import os
import sys
import gdxpds
import pandas as pd

casedir = sys.argv[1]
fname = os.path.basename(os.path.normpath(casedir))
gdx = os.path.join(casedir, 'outputs', f'valcost_equivalence_{fname}.gdx')
dfs = gdxpds.to_dataframes(gdx)

vc = dfs['valcost']
vc.columns = ['stream', 'i', 'r', 't', 'value']
vc['t'] = vc['t'].astype(int)
vc.to_csv(os.path.join(casedir, 'outputs', 'valcost_equivalence.csv'), index=False)

rc = dfs['valcost_rc']
rc.columns = ['i', 'r', 't', 'reduced_cost']
rc['t'] = rc['t'].astype(int)
rc.to_csv(os.path.join(casedir, 'outputs', 'valcost_equivalence_rc.csv'), index=False)
print(f'wrote {len(vc)} rows to outputs/valcost_equivalence.csv')
