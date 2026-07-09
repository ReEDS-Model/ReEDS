#%% Imports
import gdxpds
import pandas as pd
from pathlib import Path
from typing import Literal


#%% Helper functions
def get_gams_results(case):
    print('Loading resultsgdx')
    dictin = gdxpds.to_dataframes(Path(case, 'outputs', 'results.gdx'))
    ## Set indices as multiindex
    valcols = ['Value','Level','Marginal','Lower','Upper','Scale']
    for key, df in dictin.items():
        indices = [i for i in df if i not in valcols]
        dictin[key] = df.set_index(indices).squeeze(1)
    print('Finished loading results.gdx')
    return dictin


def get_flow(df, direction:Literal['forward','reverse']='forward', value='Level'):
    r_indices = ['r', 'rr']
    other_indices = [i for i in df.index.names if i not in r_indices]
    if direction == 'forward':
        out = df.loc[
            df.index.get_level_values('r') < df.index.get_level_values('rr'),
            value,
        ]
    elif direction == 'reverse':
        out = df.loc[
            df.index.get_level_values('r') > df.index.get_level_values('rr'),
            value,
        ].rename_axis(['rr', 'r'] + other_indices).reorder_levels(r_indices + other_indices)
    return out


def combine_forward_reverse(df, agg:Literal['net','simult']='net', value='Level'):
    """Combine forward (r < rr) and reverse (r > rr) into one +/- series"""
    r_indices = ['r', 'rr']
    other_indices = [i for i in df.index.names if i not in r_indices]
    forward = get_flow(df, 'forward')
    reverse = (-1 if agg == 'net' else 1) * get_flow(df, 'reverse')
    return pd.concat([forward, reverse]).groupby(r_indices + other_indices).sum()


#%% Results calculations
def calc_iq(g):
    """Capacity above interconnection queue limit"""
    dfs = {}
    dfs['cap_above_limit'] = g['CAP_ABOVE_LIM'].Level
    return dfs


def calc_co2_stor(g):
    """CO2 capture, transport, and storage"""
    dfs = {}
    dfs['CO2_CAPTURED_out'] = g['CO2_CAPTURED'].Level
    dfs['CO2_CAPTURED_out_ann'] = (g['CO2_CAPTURED'].Level * g['hours']).groupby(['r','t']).sum()
    dfs['CO2_STORED_out'] = g['CO2_STORED'].Level
    dfs['CO2_STORED_out_ann'] = (g['CO2_STORED'].Level * g['hours']).groupby(['r','cs','t']).sum()
    dfs['CO2_TRANSPORT_INV_out'] = g['CO2_TRANSPORT_INV'].Level
    dfs['CO2_SPURLINE_INV_out'] = g['CO2_SPURLINE_INV'].Level
    dfs['CO2_FLOW_out'] = combine_forward_reverse(g['CO2_FLOW'], agg='simult')
    dfs['CO2_FLOW_out_ann'] = (dfs['CO2_FLOW_out'] * g['hours']).groupby(['r','rr','t']).sum()
    dfs['CO2_FLOW_pos_out'] = get_flow(g['CO2_FLOW'], 'forward')
    dfs['CO2_FLOW_pos_out_ann'] = (dfs['CO2_FLOW_pos_out'] * g['hours']).groupby(['r','rr','t']).sum()
    dfs['CO2_FLOW_neg_out'] = -get_flow(g['CO2_FLOW'], 'reverse')
    dfs['CO2_FLOW_neg_out_ann'] = (dfs['CO2_FLOW_neg_out'] * g['hours']).groupby(['r','rr','t']).sum()
    dfs['CO2_FLOW_net_out'] = combine_forward_reverse(g['CO2_FLOW'], agg='net')
    dfs['CO2_FLOW_net_out_ann'] = (dfs['CO2_FLOW_net_out'] * g['hours']).groupby(['r','rr','t']).sum()
    return dfs


def calc_transmission(g):
    """Transmission capacity and flow"""
    dfs = {}
    dfs['tran_flow_rep'] = combine_forward_reverse(g['FLOW'])
    dfs['tran_flow_rep_ann'] = (dfs['tran_flow_rep'] * g['hours']).groupby(['r','rr','trtype','t']).sum()
    return dfs


#%% Procedure
def main(case):
    dictin = get_gams_results(case)
    dictout = {
        **calc_iq(dictin),
        **calc_co2_stor(dictin),
        **calc_transmission(dictin),
    }
    ## Drop zeros to reduce file size and match GAMS convention
    for key, df in dictout.items():
        _df = df.rename('Value').reset_index()
        dictout[key] = _df.loc[_df.Value != 0].copy()
    return dictout
