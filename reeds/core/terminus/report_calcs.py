#%% Imports
import gdxpds
import pandas as pd
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).parent.parent.parent.parent))
import reeds



#%% Functions
def get_gams_results(case):
    print('Loading results.gdx')
    dictin = gdxpds.to_dataframes(Path(case, 'outputs', 'results.gdx'))
    ## Set indices as multiindex
    valcols = ['Value','Level','Marginal','Lower','Upper','Scale']
    for key, df in dictin.items():
        indices = [i for i in df if i not in valcols]
        dictin[key] = df.set_index(indices).squeeze(1)
    print('Finished loading results.gdx')
    return dictin

def get_gams_set(g, setname_list):
    """Return a dict of {setname: Series} for each set found in g."""
    result = {}
    for setname in setname_list:
        if setname in g:
            result[setname] = g[setname].index.get_level_values(0).unique()
    return result


def calc_gen_h(g,dictset,sw):
    """Hourly generation by technology, region, timeslice, and year.

    Mirrors the GAMS gen_h calculation:
      gen_h(i,r,h,t) = sum_v[GEN - STORAGE_IN(storage/hyd_pump)]
                       - sum_(v,p)[PRODUCE/prod_conversion_rate] * Sw_Prod
    followed by csp-ns / upv_6 capacity corrections.
    """
    dfs = {}
    ## Calculation of gen_h to subtract storage input and hydrogen production load from generation, when applicable
    # Generation value is sum of GEN over all vintage
    dfs['gen'] = g['GEN'].Level.groupby(['i', 'r', 'h', 't']).sum()

    # Subtract storage input (when STORAGE_IN is enabled)
    storage_techs = set().union(*(
        s.index
        for key in ('storage_standalone', 'hyd_add_pump')
        if (s := dictset.get(key)) is not None
    ))
    if storage_techs and 'STORAGE_IN' in g:
        stor_mask = g['STORAGE_IN'].Level.index.get_level_values('i').isin(storage_techs)
        stor_in = g['STORAGE_IN'].Level[stor_mask].groupby(['i', 'r', 'h', 't']).sum()
        dfs['gen_h'] = dfs['gen'].subtract(stor_in, fill_value=0)

    # Subtract hydrogen production load (when Sw_Prod is enabled)
    if int(sw['Sw_Prod']):
        produce = g['PRODUCE'].Level
        prod_mask = produce.index.get_level_values('i').isin(set(dictset['consume']))
        if prod_mask.any():
            produce_df = produce[prod_mask].reset_index()
            pcr_df = g['prod_conversion_rate'].reset_index()
            merged = produce_df.merge(pcr_df, on=['i', 'v', 'r', 't'], how='left')
            merged['h2_load'] = merged['Level'] / merged['prod_conversion_rate']
            h2_load = merged.groupby(['i', 'r', 'h', 't'])['h2_load'].sum()
            dfs['gen_h'] = dfs['gen_h'].subtract(h2_load, fill_value=0)

    ## Correction of CSP-NS / UPV-6 
    # gen_h("csp-ns",r,h,t) = cap_cspns(r,t) * m_cf("upv_6","new1",r,h,t)
    # gen_h("upv_6",r,h,t)  = gen_h("upv_6",...) - gen_h("csp-ns",...), clipped to 0
    if 'cap_cspns' in g and 'm_cf' in g:
        cap_cspns = g['cap_cspns']  # parameter Series indexed by (r, t)
        # Extract m_cf for upv_6 / new1: indexed by (r, h, t)
        upv6_cf = g['m_cf'].xs('upv_6', level='i').xs('new1', level='v')

        cap_df = cap_cspns.rename('cap').reset_index()
        cf_df = upv6_cf.rename('cf').reset_index()
        cspns_df = cap_df.merge(cf_df, on=['r', 't'])
        cspns_series = (cspns_df['cap'] * cspns_df['cf']).set_axis(
            pd.MultiIndex.from_arrays(
                [['csp-ns'] * len(cspns_df)] + [cspns_df[c] for c in ['r', 'h', 't']],
                names=['i', 'r', 'h', 't'],
            )
        )

        # Replace any existing csp-ns rows with the computed values
        dfs['gen_h'] = dfs['gen_h'][dfs['gen_h'].index.get_level_values('i') != 'csp-ns']
        dfs['gen_h'] = pd.concat([dfs['gen_h'], cspns_series])

        # Subtract csp-ns generation from upv_6 and clip to 0
        upv6_mask = dfs['gen_h'].index.get_level_values('i') == 'upv_6'
        upv6_vals = dfs['gen_h'][upv6_mask]
        upv6_sub = cspns_series.copy()
        upv6_sub.index = upv6_sub.index.set_levels(['upv_6'], level='i')
        upv6_corrected = upv6_vals.subtract(
            upv6_sub.reindex(upv6_vals.index, fill_value=0)
        ).clip(lower=0)
        dfs['gen_h'] = pd.concat([dfs['gen_h'][~upv6_mask], upv6_corrected])

    dfs['gen_h_nat'] = dfs['gen_h'].groupby(['i', 'h', 't']).sum()

    return dfs



def calc_iq(g):
    """Capacity above interconnection queue limit"""
    dfs = {}
    dfs['cap_above_limit'] = g['CAP_ABOVE_LIM'].Level
    return dfs


def calc_co2_stor(g):
    """CO2 capture, transport, and storage"""
    dfs = {}
    dfs['CO2_CAPTURED_out'] = g['CO2_CAPTURED'].Level
    dfs['CO2_CAPTURED_out_ann'] = (g['CO2_STORED'].Level * g['hours']).groupby(['r','t']).sum()
    return dfs


def combine_forward_reverse(df, value='Level'):
    """Combine forward (r < rr) and reverse (r > rr) into one +/- series"""
    r_indices = ['r', 'rr']
    other_indices = [i for i in df.index.names if i not in r_indices]
    forward = df.loc[
        df.index.get_level_values('r') < df.index.get_level_values('rr'),
        value,
    ]
    reverse = -df.loc[
        df.index.get_level_values('r') > df.index.get_level_values('rr'),
        value,
    ].rename_axis(['rr', 'r'] + other_indices).reorder_levels(['r', 'rr'] + other_indices)
    return pd.concat([forward, reverse]).groupby(['r', 'rr'] + other_indices).sum()


def calc_transmission(g):
    """Transmission capacity and flow"""
    dfs = {}
    dfs['tran_flow_rep'] = combine_forward_reverse(g['FLOW'])
    dfs['tran_flow_rep_ann'] = (dfs['tran_flow_rep'] * g['hours']).groupby(['r','rr','trtype','t']).sum()
    return dfs


def main(case):
    dictin = get_gams_results(case)
    set_list = ['storage_standalone', 'hyd_add_pump', 'consume']
    sw = reeds.io.get_switches(case)
    dictset = get_gams_set(dictin, set_list)
    dictout = {
        **calc_gen_h(dictin,dictset,sw),
        **calc_iq(dictin),
        **calc_co2_stor(dictin),
        **calc_transmission(dictin),
    }
    ## Drop zeros to reduce file size and match GAMS convention
    for key, df in dictout.items():
        _df = df.rename('Value').reset_index()
        dictout[key] = _df.loc[_df.Value != 0].copy()
    return dictout
