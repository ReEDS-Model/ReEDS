'''
The purpose of this script is to write out fuel costs for the following fuels at 
census division level:
    - coal
    - uranium
    - H2 (for H2-CT/CC tech)
    - natural gas
Additionally, this script also writes out natural gas demand (total NG demand as 
well as NG demand for electricity generation) and natural gas alphas
'''
#%% ===========================================================================
### --- IMPORTS ---
### ===========================================================================

import pandas as pd
import os
import sys
import argparse
import datetime
import numpy as np
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))
import reeds
# Time the operation of this script
tic = datetime.datetime.now()


#%% Functions
def smear(dfzones, dfgroups, decay_km:float=150, decay_func=np.exp) -> pd.DataFrame:
    """
    Calculate a weighted-average parameter between dfzones and dfgroups, where the weighting
    between a zone in dfzones and all groups in dfgroups is determined by decay_func (default
    is exponential decay) and decay_km.
    """
    weights = {}

    for r, row in dfzones.iterrows():
        ## Get distance from centroid to edge of all other zones
        distances_km = dfgroups.distance(row.geometry.centroid) / 1000
        ## Weight decays with distance from centroid
        if decay_km != 0:
            weight = decay_func(-distances_km / decay_km)
        else:
            ## 1 if zero distance, 0 otherwise
            weight = (~distances_km.astype(bool)).astype(int)
        weights[r] = weight

    weight_df = pd.DataFrame(weights)
    weight_norm = weight_df / weight_df.sum()
    weight_norm = weight_norm.T

    return weight_norm


def plot_cendivweights(inputs_case, dfmap, cendivweights):
    import cmocean
    import matplotlib.pyplot as plt
    cmap = cmocean.cm.rain
    cendivs = dfmap['cendiv'].bounds.minx.sort_values().index
    nrows, ncols, coords = reeds.plots.get_coordinates(cendivs, aspect=1)
    plt.close()
    f,ax = plt.subplots(
        nrows, ncols, sharex=True, sharey=True, figsize=(3*ncols, 2.5*nrows),
        gridspec_kw={'hspace':0, 'wspace':0},
    )
    for cendiv in cendivs:
        _ax = ax[coords[cendiv]] if len(cendivs) > 1 else ax
        _ax.axis('off')
        dfmap['cendiv'].plot(ax=_ax, facecolor='none', edgecolor='k', lw=0.5, zorder=1e6)
        dfplot = dfmap['r'].copy()
        dfplot['value'] = dfplot.index.map(cendivweights[cendiv])
        dfplot = dfplot[['value','geometry']].replace(0,np.nan).dropna()
        dfplot.plot(ax=_ax, column='value', vmin=0, vmax=1, cmap=cmap)
        _ax.set_title(cendiv, fontsize=12, weight='bold', y=0.92)
    cax = ax if len(cendivs) == 1 else ax[-1, 1]
    reeds.plots.addcolorbarhist(
        f, cax, dfplot.value,
        cmap=cmap, vmin=0, vmax=1,
        orientation='horizontal', cbarbottom=-0.1, cbarheight=2, cbarwidth=0.1,
        histratio=0.1, histcolor='w', title='Weight [fraction]',
        labelpad=1.3, title_fontsize=12, ticklabel_fontsize=12,
    )
    figpath = Path(inputs_case, '..', 'outputs', 'figures', 'inputs', 'cendivweights.png')
    figpath.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(figpath)
    return f, ax


def calculate_daily_state_degree_days(
    inputs_case: str
) -> dict[str, pd.DataFrame]:
    """
    Calculate daily historical heating and cooling degree days for each state
    and each weather year (based on the GSw_HourlyWeatherYears switch) using
    hourly state-level temperature data.

    Args:
        inputs_case: Path to the inputs case directory.

    Returns:
        dict[str, pd.DataFrame]
    """
    # Get hourly state-level temperatures
    temp_hourly = reeds.io.get_temperatures(inputs_case)

    # Get baseline temperature for calculating degree days
    scalars = reeds.io.get_scalars(inputs_case)
    base_temp = scalars['degree_days_base_temperature']

    # Calculate degree-hours (hourly deviations from baseline)
    # and then take the daily averages of degree-hours to
    # get degree days. This is different from the traditional
    # approach for calculating degree days
    # (https://www.eia.gov/energyexplained/units-and-calculators/degree-days.php),
    # but we found that this approach generally resulted in better
    # predictors of daily deviations from annual average gas prices.
    hdd_hourly = (base_temp - temp_hourly).clip(lower=0)
    hdd_daily = hdd_hourly.resample('D').mean()

    cdd_hourly = (temp_hourly - base_temp).clip(lower=0)
    cdd_daily = cdd_hourly.resample('D').mean()

    degree_days_daily = {
        'hdd': hdd_daily,
        'cdd': cdd_daily
    }

    return degree_days_daily


def calculate_daily_gasreg_degree_days(
    inputs_case: str,
) -> dict[str, pd.DataFrame]:
    """
    Calculate daily gasreg-level heating and cooling degree days.
    This is done by calculating daily state-level degree days for
    the weather year(s) of the given case and then aggregating
    them to the gasreg level via population-weighted average.

    Args:
        inputs_case: Path to the inputs case directory.

    Returns:
        dict[str, pd.DataFrame]
    """
    # Calculate population-based state-gasreg weights
    state_gasreg_weights = (
        reeds.spatial.calculate_region_aggregion_population_weights(
            inputs_case,
            region_level='state',
            aggregion_level='gasreg'
        )
    )

    # Calculate state-level daily HDDs and CDDs
    degree_days_daily_st = calculate_daily_state_degree_days(inputs_case)
    hdd_daily_st = degree_days_daily_st['hdd']
    cdd_daily_st = degree_days_daily_st['cdd']

    # Aggregate daily state-level degree days to
    # the gasreg level via population-weighted average
    state_groups = reeds.inputs.get_state_groups()
    st2gasreg = state_groups.set_index('st')['gasreg']
    hdd_daily_gasreg = reeds.spatial.aggregate_by_weighted_average(
        hdd_daily_st,
        state_gasreg_weights,
        st2gasreg
    )
    hdd_daily_gasreg = hdd_daily_gasreg.rename_axis(index='datetime')
    cdd_daily_gasreg = reeds.spatial.aggregate_by_weighted_average(
        cdd_daily_st,
        state_gasreg_weights,
        st2gasreg
    )
    cdd_daily_gasreg = cdd_daily_gasreg.rename_axis(index='datetime')

    degree_days_daily = {
        'hdd': hdd_daily_gasreg,
        'cdd': cdd_daily_gasreg
    }

    return degree_days_daily


def calculate_daily_gasprice_multipliers(
    inputs_case: str
) -> dict[str, pd.DataFrame]:
    """
    Calculate daily gas price multipliers at the r and cendiv levels.
    This is done by calculating daily gasreg-level heating and cooling
    degree days and then applying price adjustment regression parameters
    to them to derive gasreg-level price multipliers. Then, to derive r-level
    multipliers, the gasreg-level multipliers are copied to their constituent
    zones. To derive cendiv-level multipliers, gasreg-level multipliers are
    aggregated via population-weighted average.

    Note that this function just gives an intermediate result, which is
    passed to hourly_writetimeseries.py for further processing. In
    hourly_writetimeseries.py, the multipliers are renormalized so that the
    average of the multipliers for the set of representative periods
    is 1 for each region.

    Args:
        inputs_case: Path to the inputs case directory.

    Returns:
        dict[str, pd.DataFrame]
    """
    # Get degree day-price multiplier regression parameters. These
    # parameters represent a regression model where heating and
    # cooling degree days were regressed on the log of the multiplicative
    # difference between daily gas prices and the annual price for each
    # gasreg with monthly fixed effects.
    regression_params = pd.read_csv(
        os.path.join(
            inputs_case,
            'gasreg_price_adj_regression_params.csv'
        ),
        index_col='param'
    )

    # Calculate daily gasreg-level HDDs and CDDs
    degree_days_daily_gasreg = calculate_daily_gasreg_degree_days(inputs_case)
    hdd_daily_gasreg = degree_days_daily_gasreg['hdd']
    cdd_daily_gasreg = degree_days_daily_gasreg['cdd']

    # Apply regression parameters to daily HDD/CDDs
    # to get daily gasreg-level price multipliers
    df_out = pd.DataFrame(index=hdd_daily_gasreg.index)
    for gasreg in regression_params.columns:
        beta_cdd = regression_params.loc['beta_CDD', gasreg]
        beta_hdd = regression_params.loc['beta_HDD', gasreg]
        alpha = regression_params.loc['alpha', gasreg]
        month_effects_map = (
            regression_params
            .loc[regression_params.index.str.contains('alpha_')]
            [gasreg]
        )
        month_effects_map.index = (
            month_effects_map.index
            .str
            .removeprefix('alpha_')
        )
        month_effects = (
            hdd_daily_gasreg.index
            .strftime('%b')
            .str
            .upper()
            .map(month_effects_map)
        )
        # Applying the regression parameters gives the log of the
        # daily multiplicative difference from the annual average
        # price, so exponentiate to get daily price multipliers.
        gasreg_price_log_mult_diffs = (
            alpha
            + beta_cdd * cdd_daily_gasreg[gasreg]
            + beta_hdd * hdd_daily_gasreg[gasreg]
            + month_effects.values
        )
        gasreg_price_multipliers = np.exp(gasreg_price_log_mult_diffs)
        df_out[gasreg] = gasreg_price_multipliers

    # Get hierarchy
    hierarchy = reeds.io.get_hierarchy(os.path.dirname(inputs_case))

    # Create one set of multipliers at the r hierarchy level
    # by copying the gasreg-level multipliers to their constitutent zones
    df_out_r = pd.DataFrame(data={
        r: df_out[gasreg] for r, gasreg in hierarchy['gasreg'].items()
    })

    # Create another set of multipliers for census divisions by aggregating
    # the gasreg-level multipliers via population-weighted average
    gasreg_cendiv_weights = (
        reeds.spatial.calculate_region_aggregion_population_weights(
            inputs_case,
            region_level='gasreg',
            aggregion_level='cendiv'
        )
    )
    gasreg_cendiv_map = dict(zip(hierarchy['gasreg'], hierarchy['cendiv']))
    df_out_cendiv = reeds.spatial.aggregate_by_weighted_average(
        df_out,
        gasreg_cendiv_weights,
        gasreg_cendiv_map
    )

    dict_out = {
        'r': df_out_r,
        'cendiv': df_out_cendiv
    }

    return dict_out


#%% Procedure
if __name__ == '__main__':
    #%% Parse arguments
    parser = argparse.ArgumentParser(description="""This file organizes fuel cost data by techonology""")

    parser.add_argument("reeds_path", help='ReEDS directory')
    parser.add_argument("inputs_case", help='ReEDS/runs/{case}/inputs_case directory')

    args = parser.parse_args()
    reeds_path = args.reeds_path
    inputs_case = args.inputs_case

    # #%% Settings for testing
    # reeds_path = reeds.io.reeds_path
    # inputs_case = os.path.join(reeds_path,'runs','v20260609_cendivM0_Pacific','inputs_case')

    #%% Set up logger
    log = reeds.log.makelog(
        scriptname=__file__,
        logpath=os.path.join(inputs_case,'..','gamslog.txt'),
    )
    print("Starting fuelcostprep.py")

    #%% Inputs from switches
    sw = reeds.io.get_switches(inputs_case)

    # Load valid regions
    val_r = reeds.io.read_input(inputs_case, 'r').squeeze(1).tolist()
    val_cendiv = reeds.io.read_input(inputs_case, 'cendiv').squeeze(1).tolist()

    r_cendiv = pd.read_csv(os.path.join(inputs_case,"r_cendiv.csv"))

    dollaryear = pd.read_csv(os.path.join(inputs_case, "dollaryear_fuel.csv"))
    deflator = pd.read_csv(os.path.join(inputs_case,'deflator.csv'))
    deflator.columns = ["Dollar.Year","Deflator"]
    dollaryear = dollaryear.merge(deflator,on="Dollar.Year",how="left")

    #%% ===========================================================================
    ### --- PROCEDURE: FUEL PRICE CALCULATIONS ---
    ### ===========================================================================

    ####################
    #    -- Coal --    #
    ####################
    coal = pd.read_csv(os.path.join(inputs_case, 'coal_price.csv'))
    coal = coal.melt(id_vars = ['year']).rename(columns={'variable':'cendiv'})
    coal = coal.loc[coal['cendiv'].isin(val_cendiv)]

    # Adjust prices to 2004$
    deflate = dollaryear.loc[dollaryear['Scenario'] == sw.coalscen,'Deflator'].values[0]
    coal.loc[:,'value'] = coal['value'] * deflate

    coal = coal.merge(r_cendiv,on='cendiv',how='left')
    coal = coal.drop('cendiv', axis=1)
    coal = coal[['year','r','value']].rename(columns={'year':'t','value':'coal'})
    coal.coal = coal.coal.round(6)

    #######################
    #    -- Uranium --    #
    #######################
    uranium = pd.read_csv(os.path.join(inputs_case, 'uranium_price.csv'))

    # Adjust prices to 2004$
    deflate = dollaryear.loc[dollaryear['Scenario'] == sw.uraniumscen,'Deflator'].values[0]
    uranium.loc[:,'cost'] = uranium['cost'] * deflate
    uranium = pd.concat([uranium.assign(r=i) for i in val_r], ignore_index=True)
    uranium = uranium[['year','r','cost']].rename(columns={'year':'t','cost':'uranium'})
    uranium.uranium = uranium.uranium.round(6)

    #############################
    #    -- H2-Combustion --    #
    #############################
    # note that these fuel inputs are not used when H2 production is run endogenously in ReEDS (GSw_H2 > 0)
    h2fuel = pd.read_csv(os.path.join(inputs_case, 'hydrogen_price.csv'), index_col='year')

    #Adjust prices to 2004$
    deflate = dollaryear.loc[dollaryear['Scenario'] == sw.h2combustionfuelscen,'Deflator'].squeeze()
    h2fuel['cost'] = h2fuel['cost'] * deflate
    # Reshape from [:,[t,cost]] to [:,[t,r,cost]]
    h2fuel = (
        pd.concat({r:h2fuel for r in val_r}, axis=0, names=['r'])
        .reset_index().rename(columns={'year':'t','cost':'h2fuel'})
        [['t','r','h2fuel']]
        .round(6)
    )

    ###########################
    #    -- Natural Gas --    #
    ###########################

    ngprice = pd.read_csv(os.path.join(inputs_case,'natgas_price_cendiv.csv'))
    ngprice = ngprice.melt(id_vars=['year']).rename(columns={'variable':'cendiv'})
    ngprice = ngprice.loc[ngprice['cendiv'].isin(val_cendiv)]

    # Adjust prices to 2004$
    deflate = dollaryear.loc[dollaryear['Scenario'] == sw.ngscen,'Deflator'].values[0]
    ngprice.loc[:,'value'] = ngprice['value'] * deflate

    # Save Natural Gas prices by census region
    ngprice_cendiv = ngprice.copy()
    ngprice_cendiv = ngprice_cendiv.pivot_table(index='cendiv',columns='year',values='value')
    ngprice_cendiv = ngprice_cendiv.round(6)

    # Map census regions to model regions
    ngprice = ngprice.merge(r_cendiv,on='cendiv',how='left')
    ngprice = ngprice.drop('cendiv', axis=1)
    ngprice = ngprice[['year','r','value']].rename(columns={'year':'t','value':'naturalgas'})
    ngprice.naturalgas = ngprice.naturalgas.round(6)

    # Census division weights
    dfmap = reeds.io.get_dfmap(reeds.io.standardize_case(inputs_case))
    cendivweights = smear(
        dfzones=dfmap['r'],
        dfgroups=dfmap['cendiv'],
        decay_km=float(sw.GSw_GasRegionSmooth),
    ).round(3)
    if int(sw.debug):
        try:
            plot_cendivweights(inputs_case, dfmap, cendivweights)
        except Exception as err:
            print(err)

    # Daily gas price multipliers
    daily_gasprice_multipliers = calculate_daily_gasprice_multipliers(
        inputs_case
    )
    daily_gasprice_multipliers_r = daily_gasprice_multipliers['r']
    daily_gasprice_multipliers_cendiv = daily_gasprice_multipliers['cendiv']

    # Combine all fuel data
    fuel = coal.merge(uranium,on=['t','r'],how='left')
    fuel = fuel.merge(ngprice,on=['t','r'],how='left')
    fuel = fuel.merge(h2fuel,on=['t','r'],how='left')
    fuel = fuel.sort_values(['t','r'])


    #%%#################################### 
    ### Natural Gas Demand Calculations ###

    # Natural Gas demand
    ngdemand = pd.read_csv(os.path.join(inputs_case,'ng_demand_elec.csv'), index_col='year')
    ngdemand = ngdemand[ngdemand.columns[ngdemand.columns.isin(val_cendiv)]]
    ngdemand = ngdemand.transpose()
    ngdemand = ngdemand.round(6)

    # Total Natural Gas demand
    ngtotdemand = pd.read_csv(os.path.join(inputs_case, 'ng_demand_tot.csv'), index_col='year')
    ngtotdemand = ngtotdemand[ngtotdemand.columns[ngtotdemand.columns.isin(val_cendiv)]]
    ngtotdemand = ngtotdemand.transpose()
    ngtotdemand = ngtotdemand.round(6)

    ### Natural Gas Alphas (already in 2004$)
    alpha = pd.read_csv(os.path.join(inputs_case, 'alpha.csv'), index_col='t')
    alpha = alpha[alpha.columns[alpha.columns.isin(val_cendiv)]]
    alpha = alpha.round(6)

    #%%###################
    ### Data Write-Out ###
    ######################

    fuel.to_csv(os.path.join(inputs_case,'fprice.csv'),index=False)
    ngprice_cendiv.to_csv(os.path.join(inputs_case,'gasprice_ref.csv'))
    reeds.io.write_profile_to_h5(
        daily_gasprice_multipliers_r,
        'daily_gasprice_multipliers_r.h5',
        inputs_case
    )
    reeds.io.write_profile_to_h5(
        daily_gasprice_multipliers_cendiv,
        'daily_gasprice_multipliers_cendiv.h5',
        inputs_case
    )

    ngdemand.to_csv(os.path.join(inputs_case,'ng_demand_elec.csv'))
    ngtotdemand.to_csv(os.path.join(inputs_case,'ng_demand_tot.csv'))
    alpha.to_csv(os.path.join(inputs_case,'alpha.csv'))
    cendivweights.to_csv(os.path.join(inputs_case,'cendivweights.csv'))

    reeds.log.toc(tic=tic, year=0, process='input_processing/fuelcostprep.py', 
        path=os.path.join(inputs_case,'..'))

    print('Finished fuelcostprep.py')
