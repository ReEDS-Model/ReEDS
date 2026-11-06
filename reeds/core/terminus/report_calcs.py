#%% Imports
import gdxpds
import pandas as pd
from pathlib import Path
from typing import Literal


#%% Helper functions
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


def get_flow(df, direction:Literal['forward','reverse']='forward', value='Level'):
    if direction == 'forward':
        mask = df.index.get_level_values('r') < df.index.get_level_values('rr')
        if isinstance(df, pd.Series):
            out = df.loc[mask]
        elif isinstance(df, pd.DataFrame):
            out = df.loc[mask, value]
    elif direction == 'reverse':
        mask = df.index.get_level_values('r') > df.index.get_level_values('rr')
        if isinstance(df, pd.Series):
            _out = df.loc[mask]
        elif isinstance(df, pd.DataFrame):
            _out = df.loc[mask, value]
        index_order = df.index.names
        reverse = {'r':'rr', 'rr':'r'}
        reverse_indices = [reverse.get(i,i) for i in index_order]
        out = _out.rename_axis(reverse_indices).reorder_levels(index_order)
    return out


def combine_forward_reverse(df, agg:Literal['net','simult']='net', value='Level'):
    """Combine forward (r < rr) and reverse (r > rr) into one +/- series"""
    index_order = df.index.names
    forward = get_flow(df, 'forward')
    reverse = (-1 if agg == 'net' else 1) * get_flow(df, 'reverse')
    return pd.concat([forward, reverse]).groupby(index_order).sum()


#%% Results calculations
def calc_iq(g):
    """Capacity above interconnection queue limit"""
    dfs = {}
    ## (tg,r,t)
    dfs['cap_above_limit'] = g['CAP_ABOVE_LIM'].Level
    return dfs


def calc_co2_stor(g):
    """CO2 capture, transport, and storage"""
    dfs = {}
    ## (s,r,h,t)
    dfs['CO2_CAPTURED_out'] = g['CO2_CAPTURED'].Level
    ## (s,r,t)
    dfs['CO2_CAPTURED_out_ann'] = (g['CO2_CAPTURED'].Level * g['hours']).groupby(['r','t']).sum()
    ## (s,r,cs,h,t)
    dfs['CO2_STORED_out'] = g['CO2_STORED'].Level
    ## (s,r,cs,t)
    dfs['CO2_STORED_out_ann'] = (g['CO2_STORED'].Level * g['hours']).groupby(['r','cs','t']).sum()
    ## (r,rr,t)
    dfs['CO2_TRANSPORT_INV_out'] = g['CO2_TRANSPORT_INV'].Level
    ## (r,cs,t)
    dfs['CO2_SPURLINE_INV_out'] = g['CO2_SPURLINE_INV'].Level
    ## (s,r,rr,h,t)
    dfs['CO2_FLOW_out'] = combine_forward_reverse(g['CO2_FLOW'], agg='simult')
    ## (s,r,rr,t)
    dfs['CO2_FLOW_out_ann'] = (dfs['CO2_FLOW_out'] * g['hours']).groupby(['r','rr','t']).sum()
    ## (s,r,rr,h,t)
    dfs['CO2_FLOW_pos_out'] = get_flow(g['CO2_FLOW'], 'forward')
    ## (s,r,rr,t)
    dfs['CO2_FLOW_pos_out_ann'] = (dfs['CO2_FLOW_pos_out'] * g['hours']).groupby(['r','rr','t']).sum()
    ## (s,r,rr,h,t)
    dfs['CO2_FLOW_neg_out'] = -get_flow(g['CO2_FLOW'], 'reverse')
    ## (s,r,rr,t)
    dfs['CO2_FLOW_neg_out_ann'] = (dfs['CO2_FLOW_neg_out'] * g['hours']).groupby(['r','rr','t']).sum()
    ## (s,r,rr,h,t)
    dfs['CO2_FLOW_net_out'] = combine_forward_reverse(g['CO2_FLOW'], agg='net')
    ## (s,r,rr,t)
    dfs['CO2_FLOW_net_out_ann'] = (dfs['CO2_FLOW_net_out'] * g['hours']).groupby(['r','rr','t']).sum()
    return dfs


def calc_transmission(g):
    """Transmission capacity and flow"""
    dfs = {}
    ## (r,rr,trtype,t)
    dfs['invtran_out'] = g['INVTRAN'].Level
    ## (r,rr,trtype,t)
    dfs['tran_cap_energy'] = g['CAPTRAN_ENERGY'].Level
    ## (r,rr,trtype,t)
    dfs['tran_cap_prm'] = g['CAPTRAN_PRM'].Level
    ## (transgrp,transgrpp,t)
    dfs['tran_cap_grp'] = g['CAPTRAN_GRP'].Level
    ## (r,rr,trtype,t)
    dfs['tran_out'] = combine_forward_reverse(dfs['tran_cap_energy'], agg='simult') / 2
    ## (r,rr,trtype,t)
    dfs['tran_prm_out'] = combine_forward_reverse(dfs['tran_cap_prm'], agg='simult') / 2
    ## (r,rr,trtype,t)
    dfs['tran_mi_out_detail'] = dfs['tran_out'] * g['distance']
    ## (trtype,t)
    dfs['tran_mi_out'] = dfs['tran_mi_out_detail'].groupby(['trtype','t']).sum()
    ## (trtype,t)
    dfs['tran_prm_mi_out'] = (dfs['tran_prm_out'] * g['distance']).groupby(['trtype','t']).sum()
    ## (r,t)
    dfs['cap_converter_out'] = g['CAP_CONVERTER'].Level
    ## (s,r,rr,h,trtype,t)     (s,r,rr,allh,t,trtype)
    dfs['tran_flow_all_rep'] = g['FLOW'].Level.loc[:,:,:,g['h_rep'].index]
    ## (s,r,rr,allh,trtype,t)
    dfs['tran_flow_all_stress'] = (
        g['FLOW'].Level.reset_index()
        .merge(g['h_stress_t'], on=['allh','t'])
        .set_index(['s','r','rr','allh','trtype','t']).Level
    )
    ## (s,r,rr,h,trtype,t)                         (s,r,rr,allh,t,trtype)
    dfs['tran_flow_rep'] = combine_forward_reverse(g['FLOW'], agg='net').loc[:,:,:,g['h_rep'].index]
    ## (s,r,rr,allh,trtype,t)
    dfs['tran_flow_stress'] = (
        combine_forward_reverse(g['FLOW']).reset_index()
        .merge(g['h_stress_t'], on=['allh','t'])
        .set_index(['s','r','rr','allh','trtype','t']).Level
    )
    ## (s,r,rr,trtype,t)
    dfs['tran_flow_rep_ann'] = (dfs['tran_flow_rep'] * g['hours']).groupby(['s','r','rr','trtype','t']).sum()
    ## (s,r,rr,h,trtype,t)
    dfs['tran_util_h_rep'] = dfs['tran_flow_all_rep'] / dfs['tran_cap_energy']
    ## (s,r,rr,allh,trtype,t)
    dfs['tran_util_h_stress'] = dfs['tran_flow_all_stress'] / dfs['tran_cap_prm']
    ## (s,r,rr,trtype,t)
    dfs['tran_util_ann_rep'] = (
        (dfs['tran_flow_all_rep'] * g['hours'] / dfs['tran_cap_energy']).groupby(['s','r','rr','trtype','t']).sum()
        / g['hours'].loc[g['h_rep'].index].sum()
    )
    ## (s,r,rr,trtype,t)
    dfs['tran_util_ann_stress'] = (
        (dfs['tran_flow_all_stress'] * g['hours_t'] / dfs['tran_cap_prm']).groupby(['s','r','rr','trtype','t']).sum()
        / g['hours_t'].loc[g['h_stress_t'].index].groupby('t').sum()
    )
    return dfs


#%% Procedure
def main(case):
    ## NOTE: If calculations slow down for large runs, consider dropping zeros upfront
    ## in get_gams_results() to speed up processing
    dictin = get_gams_results(case)
    dictout = {
        **calc_iq(dictin),
        **calc_co2_stor(dictin),
        **calc_transmission(dictin),
    }
    ## Drop zeros to reduce file size and match GAMS convention
    for key, df in dictout.items():
        _df = df.rename('Value').reset_index()
        dictout[key] = _df.loc[_df.Value != 0].dropna().copy()
    return dictout
