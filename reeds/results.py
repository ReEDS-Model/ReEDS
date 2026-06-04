"""
This script contains functions to assist with the post-processing of
complex ReEDS output data like system costs, reinforcement transmission, etc.
"""


#%% ===========================================================================
### --- IMPORTS ---
### ===========================================================================
import os
import sys
import pandas as pd
from itertools import product

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))  
import reeds  
reeds_path = reeds.io.reeds_path  

sys.path.append(os.path.join(reeds_path, 'postprocessing', 'bokehpivot'))
from defaults import DEFAULT_DOLLAR_YEAR, DEFAULT_PV_YEAR, DEFAULT_DISCOUNT_RATE


#%% ===========================================================================
### --- Postprocessing tools --- Based on bokeh
### ===========================================================================
def scale_column(df, **kw):
    df[kw['column']] = df[kw['column']] * kw['scale_factor']
    return df


def calc_cap(case):
    """
    Calculate capacity from ReEDS output.
    This function is designed to replicate outputs from bokehpivot/reeds2.py
    except that this does not have the 'Net Level Capacity (GW)' column

    Args:
        case (str): Path to the ReEDS run case or outputs.h5 file.   
    Returns:
        df (pandas dataframe): Capacity (GW) with these columns:
                i (string): technology
                v (string): vintage
                r (string): region
                t (int): year
                Value (float): Capacity (GW)
    """
    # Get data
    df = reeds.io.read_output(case, 'cap')

    # simplify technology names based on bokehpivot mapping
    df['i'] = reeds.reedsplots.simplify_techs(df['i'])

    # aggregate over the new technology labels
    df = df.groupby(['i', 'r', 't'], as_index=False).sum()

    # convert MW to GW
    df = scale_column(df,**{'scale_factor': .001, 'column':'Value'})
    
    return df

def calc_gen(case):
    """
    Calculate generation from ReEDS output.
    This function is designed to replicate outputs from bokehpivot/reeds2.py
    except that this does not have the 'Net Level Generation (TWh)' column

    Args:
        case (str): Path to the ReEDS run case or outputs.h5 file.
    Returns:
        df (pandas dataframe): Generation (TWh) with these columns:
                i (string): technology
                r (string): region
                t (int): year
                Value (float): Generation (TWh)
    """
    # Get data
    df = reeds.io.read_output(case,'gen_ann')

    # simplify technology names based on bokehpivot mapping
    df['i'] = reeds.reedsplots.simplify_techs(df['i'])

    # aggregate over the new technology labels
    df = df.groupby(['i', 'r', 't'], as_index=False).sum()

    # convert MWh to TWh
    df = scale_column(df,**{'scale_factor': 1e-6, 'column':'Value'})

    return df

def calc_sited_load(case):
    """
    Calculate sited load from ReEDS output.

    Args:
        case (str): Path to the ReEDS run case or outputs.h5 file.
    Returns:
        df (pandas dataframe): Sited Load (MW) with these columns:
                r (string): region
                t (int): year
                Value (float): Sited Load (MW)
    """
    # Get data
    df = reeds.io.read_output(case,'loadsite_cap')

    return df

def calc_emissions(case):
    """
    Calculate emissions from ReEDS output.

    Args:
        case (str): Path to the ReEDS run case or outputs.h5 file.
    Returns:
        df (pandas dataframe): Emissions (tonnes) with these columns:
                e (string): mission category
                r (string): region
                t (int): year
                Value (float): Emissions (tonnes)
    """
    # Get data
    df = reeds.io.read_output(case, 'emit_r') 

    # processing of data depends on if upstream emissions are present
    sw = reeds.io.get_switches(case)
    if int(sw.get('GSw_Upstream', 0)):
        df = (df
                .groupby(['e','r','t']).Value.sum()
                .reset_index()    
        )
    else:
        df = (df
                .set_index(['etype','e','r','t'])
                .drop(['precombustion', 'upstream'], level='etype', errors='ignore')
                .groupby(['e','r','t']).Value.sum()
                .reset_index()
        )

    # convert tonnes to million metric tonnes
    df = scale_column(df,**{'scale_factor': 1e-6, 'column':'Value'})

    return df

def calc_annualload(case,scalars):
    """
    Calculate annual end-use demand from ReEDS outputs.

    Args:
        case (str): case name
        scalars (series): scalar names and values
    Returns:
        df (pandas dataframe): Annual load (TWh) with these columns:
                r (string): region
                t (int): year
                Value (float): Annual load (TWh)
    """
    sw = reeds.io.get_switches(case)  

    df_out = pd.DataFrame()

    # Exogenous electricity demand
    df_elec = reeds.io.read_output(case, 'load_rt') 
    df_elec.Value = df_elec.Value * (1 - scalars.get('distloss')) # convert bus-bar load to end-use
    df_elec['Measure'] = 'Exogenous Demand'

    # Electricity demand for hydrogen production (columns: r, t, Value)
    df_h2 = reeds.io.read_output(case, 'prod_load_ann').groupby(['r','t'], as_index=False).Value.sum()
    df_h2['Measure'] = 'Hydrogen Production Demand'

    # Cost-optimal sited load 
    df_sited = pd.read_csv(os.path.join(case, 'outputs', 'loadsite_cap.csv')) 
    df_sited['Value'] = df_sited['Value'] * float(sw.GSw_LoadSiteCF) * 8760 # convert from MW to MWh per year
    df_sited['Measure'] = 'Cost-Optimal Sited Demand'

    df_out = pd.concat([df_elec, df_h2,  df_sited])

    # Create a "Total Demand" category by summing the three demand categories together
    df_total = (df_out
                .groupby(['r','t'], as_index=False).Value.sum()
                .assign(Measure='Total Demand'))
    df_out = pd.concat([df_out, df_total], axis=0)

    # convert MWh to TWh for national data
    df_out = scale_column(df_out,**{'scale_factor': 1e-6, 'column':'Value'})

    return df_out

def calc_h2prod(case):
    """
    Calculate hydrogen production from ReEDS output.
    This function is designed to replicate outputs from bokehpivot/reeds2.py
    except that this does not have the 'Net Level Capacity (GW)' column

    Args:
        case (str): Path to the ReEDS run case or outputs.h5 file.   
    Returns:
        df (pandas dataframe): Capacity (GW) with these columns:
                tech (string): technology
                rb (string): region
                year (int): year
                Value (float): Hydrogen Production (Million metric tons)
    """
    # Get data
    df = reeds.io.read_output(case, 'prod_produce_ann')

    # simplify technology names based on bokehpivot mapping
    df['i'] = reeds.reedsplots.simplify_techs(df['i'])

    # aggregate over the new technology labels
    df = df.groupby(['i', 'r', 't'], as_index=False).sum()

    # convert tonnes to million metric tonnes
    df = scale_column(df,**{'scale_factor': .000001, 'column':'Value'})
    
    return df

def inflate_series(inputs_case,dfin, to_dollar_year=DEFAULT_DOLLAR_YEAR):
    """
    Inflate a series of financial data to a specified dollar year.
    """
    df_deflator = pd.read_csv(
        os.path.join(inputs_case, 'deflator.csv'), 
        index_col=0
    )
    return dfin * 1 / df_deflator.loc[to_dollar_year, 'Deflator']


def gather_cost_types(df):
    """
    Gather lists of capital and operation labels
    """
    cost_cats_df = df['cost_cat'].unique().tolist()
    cost_cat_map = pd.read_csv(
        os.path.join(
            reeds_path, 'postprocessing', 'bokehpivot', 'in', 'reeds2', 'cost_cat_map.csv'
        ),
    )
    if (~cost_cat_map.cost_type.isin(['Capital','Operation'])).any():
        error = (
            'Invalid values in cost_type column of cost_cat_map.csv. '
            'Only valid values are "Capital" and "Operation".'
        )
        raise KeyError(error)

    # Make sure all cost categories in df are in cost_cat_map and throw error if not
    if not set(cost_cats_df).issubset(cost_cat_map['raw'].values.tolist()):
        error = (
            'Not all cost categories have been mapped. Categories without a mapping are:\n'
            '\n'.join([c for c in cost_cats_df if c not in cost_cat_map['raw'].values.tolist()])
        )
        raise KeyError(error)

    cap_type_ls = [
        c for c in cost_cats_df
        if c in cost_cat_map[cost_cat_map['cost_type']=='Capital']['raw'].tolist()]
    op_type_ls = [
        c for c in cost_cats_df
        if c in cost_cat_map[cost_cat_map['cost_type']=='Operation']['raw'].tolist()]

    return cost_cat_map, cap_type_ls, op_type_ls


def calc_systemcost(
    case,
    cost_type="annualized",
    group_r=False,
    rename_as_bokeh=False,
    through_year=2050,
    # The following parameters are only used if cost_type == 'annualized'
    discount_rate=DEFAULT_DISCOUNT_RATE,
    present_value_year=DEFAULT_PV_YEAR,
    shift_capital=True,
    remove_existing=False,
    crf_from_user=False,
    drop_zeros=True,
):
    """
    Calculate system costs from ReEDS output.
    This function is based on pre_systemcost from bokehpivot/reeds2.py

    Args:
        case (str): Path to the ReEDS run case or outputs.h5 file.
        cost_type (str): Type of cost to calculate. Options are:
            - 'objective': Calculate objective function system costs.
            - 'annualized': Calculate annualized system costs.
        group_r (bool): If True, group results across regions (dropping the region column).
        rename_as_bokeh (bool): If True, rename cost categories to match Bokeh output.
        through_year (int): If int, only include costs from present_value_year to through_year.
        discount_rate (float): Discount rate for present value calculations.
            (Only used if cost_type == 'annualized'.)
        present_value_year (int): Base year for present value calculations.
            (Only used if cost_type == 'annualized'.)
        shift_capital (bool): 
            - If True: Start capital payments in the year of the investment,
              even though loan payments typically start in the following year, so that
              investments made in 2050 are still reflected in 2050 capital payments.
            - If False: Reflects typical loan payments that start in the year after the loan.
            (Only used if cost_type == 'annualized'.)
        remove_existing (bool): If False, include historical capacity costs from before the start year (typically 2010).
            (Only used if cost_type == 'annualized'.)
        crf_from_user (bool): Use a user-specified Capital Recovery Factor (CRF) instead of the model’s.
            (Only used if cost_type == 'annualized'.)
    """
    # Identify the inputs_case directory based on provided path
    inputs_case = (
        os.path.abspath(os.path.join(case, '..', '..', 'inputs_case'))
        if case.endswith('.h5')
        else os.path.join(case, 'inputs_case')
    )

    # Get case inputs
    systemcost = reeds.io.read_output(case, 'systemcost_ba')
    pvf_capital = reeds.io.read_output(case, 'pvf_capital', valname='pvfcap')
    pvf_onm = reeds.io.read_output(case, 'pvf_onm', valname='pvfonm')
    crf_in = pd.read_csv(os.path.join(inputs_case, 'crf.csv'))
    df_capex_init = pd.read_csv(os.path.join(inputs_case, 'df_capex_init.csv'))

    sw = reeds.io.get_switches(case)  
    scalars = reeds.io.get_scalars(case)  

    # Valid regions
    val_r = reeds.io.read_input(case, 'r').squeeze(1).values

    # Rename columns to match the expected format
    systemcost.rename(columns={'t':'year', 'sys_costs':'cost_cat'}, inplace=True)
    pvf_capital.rename(columns={'t':'year'}, inplace=True)
    pvf_onm.rename(columns={'t':'year'}, inplace=True)
    crf_in.rename(columns={'*t':'year'}, inplace=True)
    df_capex_init.rename(columns={'t':'year','region':'r'}, inplace=True)

    # Convert to Billion dollars
    systemcost['Value'] *= 1e-9
    df_capex_init['capex'] *= 1e-9

    # Years Optimized
    sim_years = sorted(systemcost['year'].unique())
    sys_eval_years = int(sw['sys_eval_years'])
    trans_crp = int(scalars['trans_crp'])
    addyears = max(sys_eval_years, trans_crp)
    firstmodelyear, lastmodelyear = int(systemcost.year.min()), int(systemcost.year.max())

    # Begin processing
    df = systemcost.copy()

    # Apply inflation
    df['Value'] = inflate_series(inputs_case,df['Value'])
    df.rename(columns={'Value':'Cost (Bil $)'}, inplace=True)

    cost_cat_map, cap_type_ls, op_type_ls = gather_cost_types(df)
    # Get the list of transmission investment categories (subset of cap_type_ls)
    trans_cap_type_ls = [
        c for c in cap_type_ls if c in [
            'inv_converter_costs',
            'inv_transmission_line_investment',
            'inv_transmission_interzone_ac_investment',
            'inv_transmission_interzone_dc_investment',
        ]
    ]
    nontrans_cap_type_ls = [c for c in cap_type_ls if c not in trans_cap_type_ls]

    # Calculate objective function system costs
    if cost_type == 'objective':
        # Multiply all capital costs by pvf_capital and operation by pvf_onm
        df = pd.merge(left=df, right=pvf_capital, how='left', on=['year'], sort=False)
        df = pd.merge(left=df, right=pvf_onm, how='left', on=['year'], sort=False)
        cap_cond = df['cost_cat'].isin(cap_type_ls)
        onm_cond = df['cost_cat'].isin(op_type_ls)
        df.loc[cap_cond, 'Cost (Bil $)'] *= df.loc[cap_cond, 'pvfcap']
        df.loc[onm_cond, 'Cost (Bil $)'] *= df.loc[onm_cond, 'pvfonm']
        df.drop(['pvfcap','pvfonm'], axis='columns', inplace=True)

    # Annualize if specified
    elif cost_type == 'annualized':
        # Turn each cost category into a column
        df = df.pivot_table(index=['year', 'r'], columns='cost_cat', values='Cost (Bil $)').reset_index()

        # Add rows for all regions and years (including extra years after end year for financial recovery)
        full_yrs = list(range(firstmodelyear - sys_eval_years, lastmodelyear + addyears + 1))
        allyrs = pd.DataFrame(list(product(full_yrs, val_r)), columns=['year','r'])
        df = pd.merge(allyrs, df, on=['year', 'r'], how='left')
    
        if not remove_existing:
            # Add payments for pre-2010 capacity; 
            # Keep data up until the year before the first modeled year
            df_capex_hist = df_capex_init.loc[
                df_capex_init.r.isin(val_r)].groupby(['year','r']).capex.sum()

            # Convert to billion dollars and remove years after the first modeled year
            df_capex_hist=df_capex_hist.loc[:firstmodelyear-1,:]

            # Convert to output dollar year
            df_capex_hist = pd.DataFrame(inflate_series(inputs_case,df_capex_hist))

            # Insert into full cost table
            df = df.join(df_capex_hist, on=['year','r'])

            # Add historical capex only where valid (non-null)
            mask = (df['year'] < firstmodelyear) 
            df.loc[mask, 'inv_investment_capacity_costs'] = df.loc[mask, 'capex']
            df = df.drop('capex',axis=1)

        # For capital costs, multiply by CRF to annualize, and sum over previous 20 years.
        # This requires 20 years before 2010 to sum properly.
        if crf_from_user:
            crf = pd.DataFrame({
                'year': full_yrs,
                'crf': (
                    discount_rate * (1 + discount_rate)**sys_eval_years
                    / ((1 + discount_rate)**sys_eval_years - 1)
                )
            }).set_index('year')

        # Otherwise use the crf from model run
        else:
            crf = crf_in.copy()
            crf = crf.set_index('year').reindex(full_yrs)
            crf = crf.interpolate(method='linear')
            crf['crf'] = crf['crf'].fillna(method='bfill')
            
        if shift_capital:
            # This means we start capital payments in the year of the investment,
            # even though loan payments typically start in the following year, so that
            # investments made in 2050 are still reflected in 2050 capital payments.
            # This requires dividing the crf by discount rate to result in the
            # same present value calculation.
            crf = crf / (1 + discount_rate)
        else:
            # This method reflects typical loan payments that start in the year after the loan.
            df[cap_type_ls] = df.groupby('r')[cap_type_ls].shift()

        df = pd.merge(left=df.set_index('year'), right=crf, how='left',on=['year'], sort=False)
        df[cap_type_ls] = df[cap_type_ls].fillna(0)
        
        df[cap_type_ls] = df[cap_type_ls].multiply(df["crf"], axis="index")

        # Sort to ensure rolling sum is correct
        df = df.reset_index().set_index(['r','year']).sort_index()

        df[nontrans_cap_type_ls] = (
            df.groupby('r')[nontrans_cap_type_ls].rolling(sys_eval_years).sum()
        ).reset_index(level=0, drop=True)

        df[trans_cap_type_ls] = (
            df.groupby('r')[trans_cap_type_ls].rolling(trans_crp).sum()
        ).reset_index(level=0, drop=True)
        df = df.reset_index()

        # Remove years before first modeled year
        keep_yrs = list(range(firstmodelyear, lastmodelyear + addyears + 1))
        df = df.loc[df.year.isin(keep_yrs)]

        # For operation costs, simply fill missing years with model year values.
        # Assuming sys_eval_years = 20, operation payments last for 20 yrs starting in the
        # modeled year, so fill 19 empty years after the modeled year.

        # Set NaN values to 0 for missing costs in simulation years.
        # This approach prevents incorrect forward-filling from earlier years into years
        # where the cost is actually zero (since GAMS drops all zeros).
        df.loc[df['year'].isin(sim_years), op_type_ls] = (
            df.loc[df['year'].isin(sim_years), op_type_ls]
            .fillna(0)
        )

        df.loc[:,op_type_ls] = (
            df.groupby('r')[op_type_ls]
            .fillna(method='ffill', limit=sys_eval_years-1)
        )
        df = df.fillna(0)

        df = pd.melt(
            df.reset_index(),
            id_vars=['year', 'r'],
            value_vars=cap_type_ls + op_type_ls,
            var_name='cost_cat',
            value_name='Cost (Bil $)'
        )

        # Add Discounted Cost column 
        df['Discounted Cost (Bil $)'] = (
            df['Cost (Bil $)']
            / (1 + discount_rate)**(df['year'] - present_value_year)
        )

    else:
        raise ValueError(
            'Invalid cost_type. Valid options are "annualized" or "objective".'
        )

    if through_year:
        df = df.loc[(df.year >= present_value_year) & (df.year <= through_year)]  

    if rename_as_bokeh:
        cost_cat_map = cost_cat_map.set_index('raw')["display"].to_dict()
        df['cost_cat'] = df['cost_cat'].map(lambda x: cost_cat_map.get(x, x))

        value_cols = [c for c in df.columns if c in ['Cost (Bil $)', 'Discounted Cost (Bil $)']]
        df = df.groupby(['year', 'r', 'cost_cat'], as_index=False)[value_cols].sum()

    if group_r:
        df = df.groupby(['year', 'cost_cat'], as_index=False).sum()
        df.drop(columns=['r'], inplace=True)

    if drop_zeros:
        # Remove rows with zero values to reduce file size
        df = df.loc[df['Cost (Bil $)'] != 0].reset_index(drop=True)

    return df


def calc_reinforcement_spur_capacity_miles(case):
    """
    Compute total reinforcement, and spur line transmission by region (GW-mi) 

    Args:
        case (str): Path to the ReEDS case directory or outputs.h5 file.

    Returns:
        pd.DataFrame: Transmission capacity DataFrame (TW-mi) for reinforcement, spur line.
    """
    # Identify the inputs_case directory based on provided path
    inputs_case = (
        os.path.abspath(os.path.join(case, '..', '..', 'inputs_case'))
        if case.endswith('.h5')
        else os.path.join(case, 'inputs_case')
    )

    sw = reeds.io.get_switches(case)  
    scalars = reeds.io.get_scalars(case)  

    # Valid regions
    val_r = reeds.io.read_input(case, 'r').squeeze(1).values

    # Get the spur/reinforcement distance for each i/r/rscbin  
    spur_parameters = pd.read_csv(os.path.join(inputs_case, 'spur_parameters.csv'))

    # Get added capacity by i/v/r/t/rscbin
    cap_new_bin_out = reeds.io.read_output(case, 'cap_new_bin_out')

    cap_new_bin_out['Value'] = cap_new_bin_out['Value'] * 1e-3  # Convert to GW
    cap_new_bin_out.rename(
        columns={'t': 'year', 'Value': 'New Cap (GW)'},
        inplace=True)

    # Sum new capacity by technology and resource bin
    cap_new_bin_out = cap_new_bin_out.groupby(
        ['i', 'r', 'rscbin', 'year'], as_index=False)['New Cap (GW)'].sum()

    # Convert UPV from DC to AC
    upv_mask = cap_new_bin_out['i'].str.startswith('upv')
    cap_new_bin_out.loc[upv_mask, 'New Cap (GW)'] *= float(scalars['ilr_utility'])

    # Filter technologies of interest
    cap_new_filtered = cap_new_bin_out[cap_new_bin_out['i'].str.startswith(('wind', 'upv', 'csp'))]

    # Merge spur parameters
    cap_new_filtered = cap_new_filtered.merge(spur_parameters, on=['i', 'r', 'rscbin'], how='left')

    # Compute spur and reinforcement distances (GW-mi)
    tech_trans = pd.concat([
        cap_new_filtered[['year', 'r', 'New Cap (GW)', 'dist_spur_km']]
        .rename(columns={'dist_spur_km': 'dist'})
        .assign(trtype='spur'),

        cap_new_filtered[['year', 'r', 'New Cap (GW)', 'dist_reinforcement_km']]
        .rename(columns={'dist_reinforcement_km': 'dist'})
        .assign(trtype='reinforcement')
    ])

    tech_trans['Trans (GW-mi)'] = tech_trans['New Cap (GW)'] * tech_trans['dist'] / 1.60934  # km to mi

    # Compute cumulative GW-mi per year and transmission type
    years = sorted(cap_new_bin_out.year.unique())
    full_idx = pd.MultiIndex.from_product(
        [years, val_r, ['spur', 'reinforcement']], names=['year', 'r', 'trtype'])

    tech_trans_out = (
        tech_trans.groupby(['year', 'r' , 'trtype'])['Trans (GW-mi)'].sum()
        # cap_new_bin_out is new additions, so fill missing years with zero
        .reindex(full_idx).fillna(0)
        # Do a cumulative sum of the transmission capacity 
        # for each region and transmission type over the years
        .groupby(['trtype', 'r']).cumsum()
        .reset_index()
        .sort_values(by=['r', 'trtype', 'year'])
    )

    if sw['GSw_RegionResolution'] in ['county', 'mixed']:
        """
        Due to some old ReEDS outputs runs we need to zero out 
        the reinforcement line for county level regions 
        (This can be removed in the future if countly level
        supply curves get reinforcement distance zeroed out)
        """
        # Get county level regions
        county_regions = pd.read_csv(
            os.path.join(inputs_case, 'county2zone.csv'),
            dtype={'FIPS':str},
        )

        county_regions['county'] = 'p' + county_regions.FIPS

        # Set reinforcement distance to zero for county level regions  
        tech_trans_out = tech_trans_out.loc[  
            ~(  
                tech_trans_out.r.isin(county_regions['county'])  
                & (tech_trans_out.trtype == 'reinforcement')  
            )  
        ]    

    return tech_trans_out

def calc_transmission_capacity(case,levels):
    """
    Calculate transmission capacity from ReEDS output.

    Args:
        case (str): Path to the ReEDS run case or outputs.h5 file.
        levels (list): list of levels in hierarchy

    Returns:
        intraregional (pandas dataframe): intra-regional transmission capacity with these columns:
            Spatial Resolution (string): spatial resolution of the results, based on the level but with naming revised in level_to_spatial_resolution
            r (string): region
            trtype (string): transmission type
            t (int): year
            Value (float): Transmission Capacity (TW-miles)
        interregional (pandas dataframe): interregional transmission capacity with these columns:
            Spatial Resolution (string): spatial resolution of the results, based on the level but with naming revised in level_to_spatial_resolution
            r (string): region
            trtype (string): transmission type
            t (int): year
            Value (float): Interregional Transmission Capacity (GW)
    """
    ## Transmission capacity

    ### Load the inter-BA transmission MW-miles and convert to GW-miles
    tran_mi_out_detail = pd.read_csv(
                os.path.join(case,'outputs', 'tran_mi_out_detail.csv')).rename(columns={'Value':'Amount (GW-mi)'})
    tran_mi_out_detail['Amount (GW-mi)'] /= 1000
    
    ### Load transmission reinforcement and spur line data
    tech_trans_out = calc_reinforcement_spur_capacity_miles(case).rename(columns={'Trans (GW-mi)':'Amount (GW-mi)',
                                                                                'year':'t'})
    tech_trans_out['rr']=tech_trans_out['r']

    ### Combine inter-BA transmission results and spur lines results
    tran_mi_out_new = pd.concat([tran_mi_out_detail, tech_trans_out], axis=0)

    ### Now calculate interregional and intraregional data
    # Data for interregional
    trans_r = pd.read_csv(
        os.path.join(case,'outputs','tran_out.csv')
    ).rename(columns={'Value':'MW'})

    # pull intra and interregional transmission data into dictionaries for processing
    dict_inter = {}
    level_map = get_level_map(case)
    hierarchy = reeds.io.get_hierarchy(case)
    for level in levels:
        
        # Translate the level to a cleaner spatial resolution for publishing csvs. Ex. st --> State, transgrp --> Transmission Planning Subregion.
        spatial_resolution = level_map[level]
        
        regions = hierarchy[level].unique()
    
        # calculate the interregional transmission capacity
        trans_r[f'inter_{level}'] = (
                trans_r.r.map(hierarchy[level])
                != trans_r.rr.map(hierarchy[level])
            ).astype(int)

        if level == 'country':
            dict_inter[spatial_resolution] = pd.concat({
                r: (
                    trans_r.loc[
                        (trans_r['inter_transreg'] == 1)
                    ].groupby(['trtype','t']).MW.sum()
                    .rename('GW')
                    / 1e3
                ).round(3)
                for r in regions
            }, axis=1, names=(level,)).rename_axis(['trtype','t'])

        elif f'inter_{level}' in trans_r:
            dict_inter[spatial_resolution] = pd.concat({
                r: (
                    trans_r.loc[
                        (trans_r[f'inter_{level}'] == 1)
                        & ((trans_r.r.map(hierarchy[level]) == r)
                        | (trans_r.rr.map(hierarchy[level]) == r))
                    ].groupby(['trtype','t']).MW.sum()
                    .rename('GW')
                    / 1e3
                ).round(3)
                for r in regions
            }, axis=1, names=(level,)).rename_axis(['trtype','t'])

        else:
            pass

    # Units: TW-mile
    intraregional = tran_mi_out_new.copy().rename(columns={'Amount (GW-mi)':'Value'})

    # Units: GW
    interregional = (
        pd.concat(dict_inter, axis=1, names=('Spatial Resolution','r'))
        .T.stack(['trtype','t'])
        .rename('Value')
        .reset_index()
    )
    del interregional['Spatial Resolution']
    
    return intraregional, interregional

def get_level_map(case):
    # for all regions available in ReEDS/inputs/hierarchy.csv, map them to a clean display name
    level_map = pd.read_csv(
        os.path.join(reeds_path, 'postprocessing', 'plots', 'level_map.csv'), 
        index_col='raw').squeeze(1)
    
    # add a value to level map for 'r' based on the spatial resolution of the run
    sw = reeds.io.get_switches(case)
    level_map['r'] = level_map.get(sw.GSw_RegionResolution)
      
    return level_map

# %%
