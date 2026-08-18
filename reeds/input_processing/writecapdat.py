"""
The purpose of this script is to gather individual generator data from the
NEMS generator database and organize this data into various categories, such as:
    - Non-RSC Existing Capacity
    - Non-RSC Prescribed Capacity
    - RSC Existing Capacity
    - RSC Prescribed Capacity
    - SMR Existing Capacity
    - Retirement Data
        - Generator Retirements
        - Wind Retirements
        - Non-RSC Retirements
    - Hydro Capacity Adjustment Factors - ccseasons
    - Waterconstraint Indexing
    - Canadian Imports
The categorized datasets are then written out to various csv files for use
throughout the ReEDS model.

Some notes on the NEMS database:
* Capacity is assumed to retire at the BEGINNING of 'RetireYear'. So if a row's
  'RetireYear' is 2015, that capacity is assumed to retire at 2014-12-31T23:59:59.
"""

#%% ===========================================================================
### --- IMPORTS ---
### ===========================================================================
import argparse
import datetime
import numpy as np
import os
import sys
import pandas as pd
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))
import reeds


#%%#################
### FIXED INPUTS ###
WINDOFS_FIXED_CLASSES = list(range(5))
WINDOFS_FLOATING_CLASSES = list(range(6,11))

#%% ===========================================================================
### --- FUNCTIONS ---
### ===========================================================================
def create_rsc_wsc(gendb,TECH,startyear):

    rsc_wsc = gendb.loc[(gendb['tech'].isin(TECH['rsc_wsc'])) &
                        (gendb['StartYear'] < startyear) &
                        (gendb['RetireYear'] > startyear)
                        ]

    rsc_wsc = rsc_wsc[['r','tech','summer_power_capacity_MW']].rename(columns={'tech':'i',
                                                                               'summer_power_capacity_MW':'value'})

    return rsc_wsc

def create_exog_rsc(reeds_path,inputs_case,gendb,TECH,COLNAMES,sw,startyear):
    # Mappings to resource class are based on the resource quality of the technology as it comes from reV
    # Establish resource classification inputs for technologies (UPV, wind-ons, wind-ofs)
    # from supply curves


    rsc_class = {}
    rsc_class["upv"] = get_class_cf_bounds(reeds_path, tech='upv',
                                           access_case=sw.GSw_SitingUPV, subtech='')
    rsc_class["wind-ons"]  = get_class_cf_bounds(reeds_path, tech='wind-ons',
                                                 access_case=sw.GSw_SitingWindOns, subtech='')

    # for offshore wind, specify 'fixed' or 'floating' tech
    wind_ofs_subtech_list = ['fixed','floating']
    wind_ofs_class_all = []
    for wind_ofs_subtech in wind_ofs_subtech_list:
        wind_ofs_class_subtech = get_class_cf_bounds(reeds_path, tech='wind-ofs',
                                                     access_case=sw.GSw_SitingWindOfs,subtech=wind_ofs_subtech)
        wind_ofs_class_all.append(wind_ofs_class_subtech)
    rsc_class["wind-ofs"] = pd.concat(wind_ofs_class_all, ignore_index=True)

    # Read resource classification inputs for geothermal
    rsc_class["geohydro_allkm"] = (
        pd.read_csv(os.path.join(inputs_case, 'classification_geothermal.csv'))
        .query(f"access_case == '{sw.GSw_SitingGeo}'")
    )

    # Check if any rsc_wsc tech class in unitdata does not match with a resource class
    missing_resource_class(gendb,rsc_class)

    cap_exog = {}
    for tech in TECH['rsc_wsc']:
        print(tech)
        # Filter active plants
        cap_exog[tech]= gendb.loc[(gendb['tech']==tech) &
                                  (gendb['StartYear'] < startyear)  &
                                  (gendb['RetireYear'] > startyear)].copy()
        if len(cap_exog[tech]) > 0:
            # Assigning each geothermal unit in unit database to a class based on
            # groups' temperatures
            if tech in ['geohydro_allkm','egs_allkm']:
                cap_exog[tech]["class"] = cap_exog[tech]["reV_mean_resource_temp"].apply(
                        lambda x: assign_class(x, tech, rsc_class[tech]))
                cap_exog[tech]["tech"] = (cap_exog[tech]["tech"].astype(str) + "_" +
                                    cap_exog[tech]["class"].astype(str))
            # Assigning each solar, wind unit in unit database to a class based on
            # groups' minimum and maximum capacity factors
            elif tech in TECH['rsc_pv_all']:
                cap_exog[tech]["class"] = cap_exog[tech]["reV_capacity_factor_ac"].apply(
                        lambda x: assign_class(x, tech, rsc_class['upv']))
                cap_exog[tech]["tech"] = ('upv' + "_" +
                                    cap_exog[tech]["class"].astype(str))
            else:
                cap_exog[tech]["class"] = cap_exog[tech]["reV_capacity_factor_ac"].apply(
                        lambda x: assign_class(x, tech, rsc_class[tech]))
                cap_exog[tech]["tech"] = (cap_exog[tech]["tech"].astype(str) + "_" +
                                    cap_exog[tech]["class"].astype(str))

        cap_exog[tech] = cap_exog[tech][COLNAMES['capexog_rsc'][0]]
        cap_exog[tech].columns = COLNAMES['capexog_rsc'][1]
        if len(cap_exog[tech]) > 0:
            cap_exog[tech] = pd.concat([expand_exog_cap(row, startyear) for _, row in cap_exog[tech].iterrows()],
                                       ignore_index=True)

    return cap_exog, rsc_class

def get_class_cf_bounds(reeds_path, tech, access_case, subtech):
    """Establish class cut offs based on capacity factors"""
    class_def_name = 'reV_cf_ac'

    # Load the supply curve raw file produced by reV
    df = pd.read_csv(os.path.join(
        reeds_path,'inputs','supply_curve',
        'supplycurve_'+tech+'-'+access_case+'.csv'))

    # Aggregate min/max by class and attach access_case
    if tech == 'wind-ofs':
        df['subtech'] = 'fixed'
        df.loc[df['class'].isin(WINDOFS_FLOATING_CLASSES),'subtech'] = 'floating'
        df_sub = df[df['subtech']==subtech]
        summary_df = df_sub.groupby('class')['cf'].agg(['min', 'max']).reset_index()
        summary_df['subtech'] = subtech
        summary_df['access_case'] = access_case
        summary_df.columns = ['class', f'min_{class_def_name}',
                              f'max_{class_def_name}', 'subtech', 'access_case']
    else:
        summary_df = df.groupby('class')['cf'].agg(['min', 'max']).reset_index()
        summary_df['access_case'] = access_case
        summary_df.columns = ['class', f'min_{class_def_name}',
                               f'max_{class_def_name}', 'access_case']

    # Pin each class's min CF to the max CF of the previous class to avoid gaps
    summary_df = summary_df.sort_values(by=['class',f'min_{class_def_name}'])
    for c in summary_df['class'].unique().tolist():
        if c > min(summary_df['class'].unique().tolist()):
            summary_df.loc[
                summary_df['class']==c,f'min_{class_def_name}'
                ] = summary_df.loc[summary_df['class']==c-1][f'max_{class_def_name}'].iloc[0]

    # Round values to 4 decimal places
    summary_df[f'min_{class_def_name}'] = summary_df[f'min_{class_def_name}'].round(4)
    summary_df[f'max_{class_def_name}'] = summary_df[f'max_{class_def_name}'].round(4)

    return summary_df

# Assign each wind, solar and geothermal unit in unit database to a class
def assign_class(cf, tech, df_class):
    # Each unit is assigned to the class associated with the min and max performance
    # its mean performance falls between
    value = 'mean_temp' if tech in ['geohydro_allkm', 'egs_allkm'] else 'cf_ac'
    row = df_class[(df_class[f'min_reV_{value}'] < cf) & (cf <= df_class[f'max_reV_{value}'])]
    # Handle min cutoff point
    if cf == df_class[f'min_reV_{value}'].min():
        row = df_class[cf == df_class[f'min_reV_{value}']]

    if len(row) == 1:
        return row.iloc[0]['class']
    # If a offshore wind cf matches with both fixed and floating
    # resources, assign a fixed resource
    elif (len(row) > 1) & (tech == 'wind-ofs'):
        row = row[row['subtech']=='fixed']
        return row.iloc[0]['class']
    else:
        # If a unit's capacity factor/mean temp does not fall between any two max and min values
        # specified in the classificalion file, it is unclassified and gives an error
        raise ValueError('Unclassified ' + tech + ' technology with cf= ' + str(cf) +
                         ', check capacity factor/mean temperature values in unitdata.csv and classification files.')

# Expand each row into multiple rows (startyear → retirement_year)
def expand_exog_cap(row, start_year):
    # List the years between start_year and retirement_year
    # (not including the retirement_year itself since unit is
    # retired at the start of the year)
    years = np.arange(start_year, row["year"])
    df = pd.DataFrame({
        "tech": [row["tech"]] * len(years),
        "region": [row["region"]] * len(years),
        "year": years,
        "sc_point_gid": [row["sc_point_gid"]] * len(years),
        "MW": [row["MW"]] * len(years)})
    return df

# Assign each calendar year to its appropriate modeledyear
# (For example: capacity that comes online in 2016 will
# show up in modeled year 2020)
def assign_modeledyear(x,years_list):
    for m in years_list:
        if x <= m:
            return m
    return None

# Check if there are any rsc techs in unitdata without resource classes
def missing_resource_class(gendb,rsc_class):
    # Find the tech classes in unitdata that need to be matched to resource classes
    matched_techs = [i for i in gendb['tech'].unique().tolist() if i in TECH['rsc_wsc']]
    # Do not count csp-ns as it is matched to upv resources
    matched_techs = [i for i in matched_techs if i not in TECH['rsc_csp'] ]
    # Find tech classes in unitdata that are without assigned resource classes
    missing_techs = list(set(matched_techs) - set(rsc_class))
    if len(missing_techs) > 0:
        raise ValueError(f'{missing_techs} are in unitdata but not matched with any resource classes. Exiting program.')
    else:
        print('All rsc/geothermal tech classes in unitdata are matched with available resource classes.')


def process_ivt(years, inputs_case):

    ivt_df= pd.read_csv(os.path.join(inputs_case,'ivt.csv'))
    ### modify set of technology name as lower case and convert all columns except the first to string
    ivt_df.iloc[:, 0] = ivt_df.iloc[:, 0].str.lower()
    ivt_df=ivt_df.astype(str)
    ivt_df = ivt_df[[ivt_df.columns[0]] + [str(y) for y in years]]

    full_range = list(range(years[0], years[-1] + 1))

    for y in full_range:
        y_str = str(y)
        if y_str not in ivt_df.columns:
            # Find closest *future* year that exists
            future_years = [fy for fy in years if fy >= y]
            closest_future = min(future_years)
            ivt_df[y_str] = ivt_df[str(closest_future)]

    ivt_df = ivt_df[[ivt_df.columns[0]] + [str(x) for x in full_range]]

    return ivt_df


# Only keep neccessary columns from unitdata to work with
# And rename column names for easier processing
def COLNAMES_define(retscen):
    return {
        'capexog_rsc': (
            ['tech','r','RetireYear','sc_point_gid','summer_power_capacity_MW'],
            ['tech','region','year','sc_point_gid','MW']
        ),
        'capnonrsc': (
            ['tech','coolingwatertech','r','ctt','wst','summer_power_capacity_MW'],
            ['i','coolingwatertech','r','ctt','wst','value']
        ),
        'capnonrsc_energy': (
            ['tech','r','energy_capacity_MWh'],
            ['i','r','value']
        ),
        'prescribed_nonRSC': (
            ['StartYear','tech','vin','r','coolingwatertech','ctt','wst','summer_power_capacity_MW'],
            ['t','i','v','r','coolingwatertech','ctt','wst','value']
        ),
        'prescribed_nonRSC_energy': (
            ['StartYear','tech','vin','r','coolingwatertech','ctt','wst','energy_capacity_MWh'],
            ['t','i','v','r','coolingwatertech','ctt','wst','value']
        ),
        'prescribed_RSC': (
            ['StartYear','tech','vin','r','summer_power_capacity_MW'],
            ['t','i','v','r','value']
        ),
        'rsc': (
            ['tech','r','v','ctt','wst','summer_power_capacity_MW'],
            ['i','r','v','ctt','wst','value']
        ),
        'rsc_wsc': (
            ['r','tech','summer_power_capacity_MW'],
            ['r','i','value']
        ),
        'prsc_csp': (
            ['StartYear','r','tech','ctt','wst','summer_power_capacity_MW'],
            ['t','r','i','ctt','wst','value']
        ),
        'prsc_geo': (
            ['StartYear','r','tech','summer_power_capacity_MW'],
            ['t','r','i','value']
        ),
        'retirements': (
            ['tech','v','r',retscen,'StartYear','coolingwatertech','ctt','wst','type','summer_power_capacity_MW'],
            ['i','v','r','t','tt','coolingwatertech','ctt','wst','type','value']
        ),
        'retirements_energy': (
            ['tech','v','r',retscen,'StartYear','type','energy_capacity_MWh'],
            ['r','i','v','t','tt','type','value']
        ),
        'windret': (
            ['r','tech','RetireYear','summer_power_capacity_MW'],
            ['r','i','t','value']
        ),
        'georet': (
            ['r','tech','RetireYear','summer_power_capacity_MW'],
            ['r','i','t','value']
        ),
    }
#%% ===========================================================================
### --- SUPPLEMENTAL DATA ---
### ===========================================================================

#########################
### STATIC DICTIONARY ###
TECH = {
    'capnonrsc': [
        'battery_li', 'biopower', 'coal-igcc', 'coal-new',
        'coaloldscr','coalolduns','gas-cc', 'gas-ct',
        'lfill-gas','nuclear', 'o-g-s', 'pumped-hydro'
    ],
    'capnonrsc_energy': [
        'battery_li'
    ],
    'prescribed_nonRSC': [
        'battery_li', 'biopower', 'coal-igcc', 'coal-new',
        'coaloldscr', 'coalolduns', 'gas-cc', 'gas-ct',
        'hydED', 'hydEND', 'hydUD', 'hydUND', 'hydND', 'hydNPND',
        'lfill-gas', 'nuclear', 'o-g-s', 'pumped-hydro'
    ],
    'prescribed_nonRSC_energy': [
        'battery_li',
    ],
    'storage'  : ['battery_li', 'pumped-hydro'
    ],
    'rsc_pv_all': ['upv','pvb','pvb_pv','csp-ns'],
    'rsc_upv': ['upv','pvb'],
    'rsc_w': ['wind-ons','wind-ofs'],
    'rsc_csp': ['csp-ns'],
    'rsc_wsc': ['upv','pvb','csp-ns','csp-ws','wind-ons','wind-ofs',
                'geohydro_allkm','egs_allkm'],
    'prsc_csp': ['csp-ns','csp-ws'],
    'prsc_geo': ['geohydro_allkm','egs_allkm'],
    'retirements': [
        'coalolduns', 'o-g-s', 'hydED', 'hydEND', 'gas-ct', 'lfill-gas',
        'coaloldscr', 'biopower', 'gas-cc', 'coal-new',
        'battery_li','nuclear', 'pumped-hydro', 'coal-igcc'
    ],
    'retirements_energy': [
        'battery_li'
    ],
    'windret': ['wind-ons'],
    'georet': ['geohydro_allkm','egs_allkm'],
    # This is not all technologies that do not having cooling, but technologies
    # that are (or could be) in the plant database.
    'no_cooling': [
        'upv', 'pvb', 'gas-ct', 'geohydro_allkm','egs_allkm',
        'battery_li', 'pumped-hydro', 'pumped-hydro-flex',
        'hydUD', 'hydUND', 'hydD', 'hydND', 'hydSD', 'hydSND', 'hydNPD',
        'hydNPND', 'hydED', 'hydEND', 'wind-ons', 'wind-ofs',
    ],
}



#%% ===========================================================================
### --- MAIN FUNCTION ---
### ===========================================================================

def main(reeds_path, inputs_case):

    #########################
    ### SUPPLEMENTAL DATA ###

    quartershorten = {'spring':'spri','summer':'summ','fall':'fall','winter':'wint'}

    hotcold_months = {'NOV':'cold', 'DEC':'cold', 'JAN':'cold', 'FEB':'cold',
                    'JUN':'hot',  'JUL':'hot',  'AUG':'hot'
                    }

    #%% Inputs from switches
    sw = reeds.io.get_switches(inputs_case)
    retscen = sw.retscen
    GSw_WaterMain = int(sw.GSw_WaterMain)
    GSw_PVB = int(sw.GSw_PVB)
    startyear = int(sw.startyear)
    endyear = int(sw.endyear)

    scalars = reeds.io.get_scalars(inputs_case)

    years = pd.read_csv(
        os.path.join(inputs_case,'modeledyears.csv')
    ).columns.astype(int).values.tolist()

    regions = reeds.io.read_input(inputs_case, 'r').squeeze(1).values

    ####################
    ### DICTIONARIES ###

    COLNAMES = COLNAMES_define(retscen)


    #%%
    print('Importing generator database:')
    gdb_use = pd.read_csv(os.path.join(inputs_case,'unitdata.csv'),
                          dtype={"sc_point_gid": "Int64"},
                          low_memory=False)

    # Preserve a version of gdb_use with all pv techs separated for cap_exog
    gdb_use_cap_exog = gdb_use.copy()
    # Multiply all PV capacities by ILR to convert AC to DC
    gdb_use_cap_exog.loc[
        gdb_use_cap_exog['tech'].isin(TECH['rsc_pv_all']), 'summer_power_capacity_MW'
    ] *= scalars['ilr_utility']

    # If PVB is turned off, consider all PVB as UPV and battery_li for existing and prescribed builds
    # If PVB is turned on, consider all PVB as 'pvb'
    if GSw_PVB == 0:
        gdb_use['tech'] = gdb_use['tech'].replace('pvb_battery','battery_li')
        gdb_use['tech'] = gdb_use['tech'].replace('pvb_pv','upv')
    else:
        gdb_use['tech'] = gdb_use['tech'].replace('pvb_battery','pvb')
        gdb_use['tech'] = gdb_use['tech'].replace('pvb_pv','pvb')

    # Consider all DUPV as UPV for existing and prescribed builds.
    gdb_use['tech'] = gdb_use['tech'].replace('dupv','upv')

    # Change tech category of hydro that will be prescribed to use upgrade tech
    # This is a coarse assumption that all recent new hydro is upgrades
    # Existing hydro techs (hydED/hydEND) specifically refer to hydro that exists in startyear
    # Future work could incorporate this change into unit database creation and possibly
    #    use data from ORNL HydroSource to assign a more accurate hydro category.
    gdb_use.loc[
        (gdb_use['tech']=='hydEND') &
        (gdb_use['StartYear'] >= startyear) &
        (gdb_use['StartYear'] <= endyear),
        'tech'] = 'hydUND'
    gdb_use.loc[
        (gdb_use['tech']=='hydED') &
        (gdb_use['StartYear'] >= startyear) &
        (gdb_use['StartYear'] <= endyear),
        'tech'] = 'hydUD'

    # We model csp-ns (CSP No Storage) as upv throughout ReEDS, but switch it back for reporting.
    # So save the csp-ns capacity separately, then rename it.
    csp_units = (
        gdb_use.loc[(gdb_use['tech']=='csp-ns') & (gdb_use['RetireYear'] > startyear)]
        .groupby(['r','StartYear','RetireYear']).summer_power_capacity_MW.sum()
        .reset_index()
    )
    if len(csp_units):
        cap_cspns = (
            pd.concat(
                {i: pd.Series(
                    [row.summer_power_capacity_MW]*(row.RetireYear - row.StartYear + 2),
                    index=range(row.StartYear, row.RetireYear + 2)
                ) for (i,row) in csp_units.iterrows()},
                axis=1)
            .rename(columns=csp_units['r']).fillna(0)
            .T.groupby(level=0).sum().T
            .stack().replace(0,np.nan).dropna()
            .rename_axis(['t','r']).reorder_levels(['r','t']).rename('MWac')
        )
        cap_cspns = (
            cap_cspns.loc[cap_cspns.index.get_level_values('t') >= startyear].copy())
    else:
        cap_cspns = pd.DataFrame(columns=['r','t','MWac']).set_index(['r','t'])
    # Rename csp-ns to upv
    gdb_use.loc[gdb_use['tech']=='csp-ns','coolingwatertech'] = (
        gdb_use.loc[gdb_use['tech']=='csp-ns','coolingwatertech']
        .map(lambda x: x.replace('csp-ns','upv'))
    )
    gdb_use.loc[gdb_use['tech']=='csp-ns','tech'] = 'upv'

    # If using cooling water, set the coolingwatertech of technologies with no
    # cooling to be the same as the tech
    if GSw_WaterMain == 1:
        gdb_use.loc[gdb_use['tech'].isin(TECH['no_cooling']),
                    'coolingwatertech'] = gdb_use.loc[gdb_use['tech'].isin(TECH['no_cooling']),
                                                    'tech']

    # Multiply all PV capacities by ILR
    # EIA-NEMS PV capacity is in MWac while ReEDS uses MWdc internally,
    # so multiply PV capacity by the ILR [MWdc/MWac] of PV
    gdb_use.loc[
        gdb_use['tech'].isin(TECH['rsc_pv_all']), 'summer_power_capacity_MW'
    ] *= scalars['ilr_utility']

    #%%##################################
    #    -- All Existing Capacity --    #
    #####################################

    ### Used as the starting point for intra-zone network reinforcement costs
    #   Power capacity in MW
    poi_cap_init = gdb_use.loc[(gdb_use['StartYear'] < startyear) &
                            (gdb_use['RetireYear'] > startyear)
    ].groupby('r').summer_power_capacity_MW.sum().rename('MW').round(3)

    #%%######################################
    #    -- non-RSC Existing Capacity --    #
    #########################################

    print('Gathering non-RSC Existing Capacity...')
    capnonrsc = gdb_use.loc[(gdb_use['tech'].isin(TECH['capnonrsc'])) &
                            (gdb_use['StartYear'] < startyear) &
                            (gdb_use['RetireYear'] > startyear)
                            ]
    capnonrsc = capnonrsc[COLNAMES['capnonrsc'][0]]
    capnonrsc.columns = COLNAMES['capnonrsc'][1]
    capnonrsc = capnonrsc.groupby(COLNAMES['capnonrsc'][1][:-1]).sum().reset_index()

    capnonrsc_energy = gdb_use.loc[(gdb_use['tech'].isin(TECH['capnonrsc_energy'])) &
                                    (gdb_use['StartYear'] < startyear) &
                                    (gdb_use['RetireYear'] > startyear)
                                    ]
    capnonrsc_energy = capnonrsc_energy[COLNAMES['capnonrsc_energy'][0]]
    capnonrsc_energy.columns = COLNAMES['capnonrsc_energy'][1]
    capnonrsc_energy = capnonrsc_energy.groupby(COLNAMES['capnonrsc_energy'][1][:-1]).sum().reset_index()


    #%%########################################
    #    -- non-RSC Prescribed Capacity --    #
    ###########################################

    print('Gathering non-RSC Prescribed Capacity...')
    ivt_df= process_ivt(years, inputs_case)

    ### prescribed power capacity
    prescribed_nonRSC = gdb_use.loc[(gdb_use['tech'].isin(TECH['prescribed_nonRSC'])) &
                                    (gdb_use['StartYear'] >= startyear) &
                                    (gdb_use['StartYear'] <= endyear)
                                    ]
    prescribed_nonRSC['tech'] = prescribed_nonRSC['tech'].str.lower()
    ### assign vintage based on start year of the unit
    prescribed_nonRSC= pd.merge(prescribed_nonRSC, ivt_df, how='left', left_on='tech', right_on='Unnamed: 0')
    prescribed_nonRSC['vin'] = prescribed_nonRSC.apply(lambda row: f"new{row[str(row['StartYear'])]}", axis=1)

    prescribed_nonRSC = prescribed_nonRSC[COLNAMES['prescribed_nonRSC'][0]]
    prescribed_nonRSC.columns = COLNAMES['prescribed_nonRSC'][1]
    # Remove ctt and wst data from storage, set coolingwatertech to tech type ('i')
    for j, row in prescribed_nonRSC.iterrows():
        if row['i'] in TECH['storage']:
            prescribed_nonRSC.loc[j,['ctt','wst','coolingwatertech']] = ['n','n',row['i']]


    if int(sw.GSw_NuclearDemo)==1:
        # Load in demo data and stack it on prescribed non-RSC
        demo = pd.read_csv(
            os.path.join(inputs_case,'demonstration_plants.csv')).drop("notes", axis=1)
        # Filter demonstration plants to regions in function call
        demo = demo[demo['r'].isin(regions)]
        prescribed_nonRSC = pd.concat([prescribed_nonRSC,demo],sort=False)

    prescribed_nonRSC = (
        prescribed_nonRSC.groupby(COLNAMES['prescribed_nonRSC'][1][:-1]).sum().reset_index())

    ### prescribed energy capacity
    prescribed_nonRSC_energy = gdb_use.loc[(gdb_use['tech'].isin(TECH['prescribed_nonRSC_energy'])) &
                                    (gdb_use['StartYear'] >= startyear) &
                                    (gdb_use['StartYear'] <= endyear)
                                    ]
    if len(prescribed_nonRSC_energy):
        ### assign vintage based on start year of the unit
        prescribed_nonRSC_energy= pd.merge(prescribed_nonRSC_energy, ivt_df, how='left', left_on='tech', right_on='Unnamed: 0')
        prescribed_nonRSC_energy['vin'] = prescribed_nonRSC_energy.apply(lambda row: f"new{row[str(row['StartYear'])]}", axis=1)

        prescribed_nonRSC_energy = prescribed_nonRSC_energy[COLNAMES['prescribed_nonRSC_energy'][0]]
        prescribed_nonRSC_energy.columns = COLNAMES['prescribed_nonRSC_energy'][1]
        # Remove ctt and wst data from storage, set coolingwatertech to tech type ('i')
        for j, row in prescribed_nonRSC_energy.iterrows():
            if row['i'] in TECH['storage']:
                prescribed_nonRSC_energy.loc[j,['ctt','wst','coolingwatertech']] = ['n','n',row['i']]

        prescribed_nonRSC_energy = (
            prescribed_nonRSC_energy.groupby(COLNAMES['prescribed_nonRSC_energy'][1][:-1]).sum().reset_index())
    else:
        prescribed_nonRSC_energy = pd.DataFrame(columns=COLNAMES['prescribed_nonRSC_energy'][1])


    #%%##################################
    #    -- RSC Existing Capacity --    #
    #####################################
    '''
    The following are RSC tech that are treated differently in the model
    '''
    print('Gathering RSC Existing Capacity...')

    # PVB and UPV values are collected at the same time here:
    caprsc = gdb_use.loc[(gdb_use['tech'].isin(TECH['rsc_upv'])) &
                        (gdb_use['StartYear'] < startyear)  &
                        (gdb_use['RetireYear'] > startyear)
                        ]

    caprsc['v']='init-1'
    # Assign existing upv as upv_5 based on their average cf
    caprsc.loc[caprsc['tech']=='upv','tech']='upv_5'
    caprsc = caprsc[COLNAMES['rsc'][0]]
    caprsc.columns = COLNAMES['rsc'][1]
    caprsc = caprsc.groupby(COLNAMES['rsc'][1][:-2]).value.sum().reset_index()


    # Add existing CSP builds:
    #   Note: Since CSP data is affected by GSw_WaterMain, it must be dealt with
    #       separate from the other RSC tech (UPV, DUPV, wind, etc)
    csp = gdb_use.loc[(gdb_use['tech'].isin(TECH['rsc_csp']))    &
                    (gdb_use['StartYear'] < startyear) &
                    (gdb_use['RetireYear'] > startyear)
                    ]
    csp['v']='init-1'
    csp = csp[COLNAMES['rsc'][0]]
    csp.columns = COLNAMES['rsc'][1]
    csp = csp.groupby(COLNAMES['rsc'][1][:-1]).sum().reset_index()
    if GSw_WaterMain == 1:
        csp['i'] = csp['i'] + '_' + csp['ctt'] + '_' + csp['wst']
    csp.drop('wst', axis=1, inplace=True)

    # Add existing hydro builds:
    gendb = gdb_use[["tech", 'r', "summer_power_capacity_MW"]]
    gendb = gendb[(gendb.tech == 'hydED') | (gendb.tech == 'hydEND')]

    hyd = gendb.groupby(['tech', 'r']).sum() \
            .reset_index() \
            .rename({"tech":"i","summer_power_capacity_MW":"value"}, axis=1)

    hyd['ctt'] = 'n'
    hyd['v'] = 'init-1'
    # Concat all RSC Existing Data to one dataframe:
    caprsc = pd.concat([caprsc, csp, hyd])

    # Export Existing RSC data specifically used in writesupplycurves.py
    rsc_wsc = create_rsc_wsc(gdb_use, TECH=TECH, startyear=startyear)

    # Create geoexist.csv and copy to inputs_case
    geoexist = gdb_use.loc[(gdb_use['tech'].isin(['geohydro_allkm','egs_allkm'])) &
                       (gdb_use['StartYear'] < startyear) &
                       (gdb_use['RetireYear'] > startyear)
                       ]
    geoexist = (geoexist[['tech','r','summer_power_capacity_MW']]
                .rename(columns={'tech':'i','summer_power_capacity_MW':'MW'})
                )
    geoexist = geoexist.groupby(['i','r']).sum().reset_index()
    # Rename generic geothermal tech category to geohydro_allkm_1
    geoexist['i'] = 'geohydro_allkm_1'

    ######################################
    #    -- RSC Exogenous Capacity --    #
    ######################################

    (cap_exog, rsc_class) = create_exog_rsc(reeds_path, inputs_case, gdb_use_cap_exog, TECH, COLNAMES, sw, startyear)


    #%%####################################
    #    -- RSC Prescribed Capacity --    #
    #######################################

    print('Gathering RSC Prescribed Capacity...')
    cap_pres = {}
    for tech in TECH['rsc_wsc']:
        cap_pres[tech]= gdb_use.loc[(gdb_use['tech']==tech) &
                    (gdb_use['StartYear'] >= startyear) &
                    (gdb_use['StartYear'] <= endyear)
                    ].copy()
        mask = ivt_df['Unnamed: 0'].str.contains(tech, case=False, na=False)
        if len(cap_pres[tech]) != 0:
            # DUPV, PVB and UPV values are collected at the same time here:
            if tech in TECH['rsc_upv']:
                print(tech)
                cap_pres[tech]["class"] = cap_pres[tech]["reV_capacity_factor_ac"].apply(
                        lambda x: assign_class(x, tech, rsc_class['upv']))
                cap_pres[tech]["tech"] = (cap_pres[tech]["tech"].astype(str) + "_" +
                                    cap_pres[tech]["class"].astype(str))
            # Load in wind builds:
            elif tech in TECH['rsc_w']:
                print(tech)
                cap_pres[tech]["class"] = cap_pres[tech]["reV_capacity_factor_ac"].apply(
                        lambda x: assign_class(x, tech, rsc_class[tech]))
                cap_pres[tech]["tech"] = (cap_pres[tech]["tech"].astype(str) + "_" +
                                    cap_pres[tech]["class"].astype(str))
            # Add prescribed csp builds:
            #   Note: Since csp is affected by GSw_WaterMain, it must be dealt with separate
            #         from the other RSC tech (dupv, upv, wind, etc)
            elif tech in TECH['prsc_csp']:
                print(tech)
                cap_pres[tech]["class"] = cap_pres[tech]["reV_capacity_factor_ac"].apply(
                        lambda x: assign_class(x, tech, rsc_class['upv']))
                cap_pres[tech]["tech"] = (cap_pres[tech]["tech"].astype(str) + "_" +
                                    cap_pres[tech]["class"].astype(str))
                if GSw_WaterMain == 1:
                     cap_pres[tech]["tech"] = np.where( cap_pres[tech]["tech"]=='csp-ws',
                                          cap_pres[tech]["tech"]+'_'+cap_pres[tech]['ctt']+'_'+cap_pres[tech]['wst'],
                                         'csp-ws')
            # Load in geo builds:
            elif tech in TECH['prsc_geo']:
                cap_pres[tech]["class"] = cap_pres[tech]["reV_mean_resource_temp"].apply(
                        lambda x: assign_class(x, tech, rsc_class[tech]))
                cap_pres[tech]["tech"] = (cap_pres[tech]["tech"].astype(str) + "_" +
                                    cap_pres[tech]["class"].astype(str))
            # assign vintages based on start year of the unit
            ivt_df_mask = (ivt_df[mask]                                   # filter rows
                            .iloc[:, 1:]                                  # drop first technology column
                            .melt(var_name='year', value_name='vin_num')  # convert to long format
                            .assign(
                                vin=lambda df: 'new' + df['vin_num'].astype(str),
                                year=lambda df: df['year'].astype(int)    # year to intager
                            ))
            cap_pres[tech] =  pd.merge(cap_pres[tech], ivt_df_mask, how='left', left_on='StartYear', right_on='year')
            cap_pres[tech] = cap_pres[tech][COLNAMES['prescribed_RSC'][0]]
            cap_pres[tech].columns = COLNAMES['prescribed_RSC'][1]
            cap_pres[tech] = cap_pres[tech].groupby(['i','v','r','t']).sum().reset_index()
    # Concat all RSC Existing Data to one dataframe:
    prescribed_rsc = pd.concat([cap_pres[tech] for tech in TECH["rsc_wsc"]
                                if tech in cap_pres and not cap_pres[tech].empty],ignore_index=True)


    #%%----------------------------------------------------------------------------
    ################################
    # -- SMR Existing Capacity --  #
    ################################
    print('Gathering SMR Existing Capacity...')
    # Grab the first year for smr because that is when new capacity can begin to be built (for
    # smr, smr_ccs and electrolyzers)
    firstyear = reeds.io.read_input(inputs_case, 'firstyear').set_index('i').squeeze(1).astype(int)
    h2_prod_first_year = firstyear['smr']
    # Get exogenous H2 demand
    h2_exogenous_demand = (
        pd.read_csv(os.path.join(inputs_case,'h2_exogenous_demand.csv'))
        .rename(columns={f'{sw.GSw_H2_Demand_Case}':'million_tons'},)
        .drop(['*p'], axis=1).set_index('t').squeeze(1)
    )
    ### Get BA share of national H2 demand
    h2_ba_share = (
        pd.read_csv(os.path.join(inputs_case,'h2_ba_share.csv'))
        .rename(columns={'*r':'r'})
    )
    # Filter to regions in function call
    h2_ba_share = h2_ba_share[h2_ba_share['r'].isin(regions)]
    h2_ba_share = h2_ba_share.pivot(index='t', columns='r', values='fraction')
    ## h2_ba_share is only populated for 2021 and 2050, so need to fill the empty data
    h2_ba_share = h2_ba_share.reindex(sorted(set(years+[2021,2050])))
    ## If a region has no data for 2021, it's zero (GAMS convention)
    h2_ba_share.loc[2021] = h2_ba_share.loc[2021].fillna(0)
    ## Backfill before 2021
    h2_ba_share.loc[:2021] = h2_ba_share.loc[:2021].bfill()
    ## Interpolate between 2021-2050
    h2_ba_share.loc[2021:] = h2_ba_share.loc[2021:].interpolate('index')
    ## Only keep the modeled years
    h2_ba_share = h2_ba_share.loc[years].copy()
    ## Reshape from wide to long format
    h2_ba_share_out = h2_ba_share.reset_index().melt(id_vars='t', var_name='r', value_name='fraction')[['r','t','fraction']]

    # Calculating the consumption characteristics (has columns i, t, parameter, value)
    consume_char0 = pd.read_csv(
        os.path.join(inputs_case,'consume_char.csv')).rename(columns={'*i':'i'})
    consume_char0['i'] = consume_char0['i'].str.lower()
    consume_char0 = consume_char0.set_index(['i','t','parameter']).value

    outage_forced_static = pd.read_csv(os.path.join(inputs_case,'outage_forced_static.csv'),
                                header=None, index_col=0,
    ).squeeze(1)

    smr_init_ele_efficiency = consume_char0['smr',startyear,'ele_efficiency']
    smr_outage_forced = outage_forced_static['smr']
    h2_demand_initial = h2_exogenous_demand[h2_prod_first_year]

    # Now make some calculations to get the existing SMR capacity
    # Hydrogen demand per r,t (million metric tons) * (10^9 kg/million metric ton) * (kWh/kg)
    # / 8760 to convert kWh --> kW  / (10^3 kW/MW) / outage rate
    # * to make a tiny adjustment upwards to avoid infeasibilities
    h2_existing_smr_cap = (
        h2_ba_share.stack('r').reorder_levels(['r','t']).rename('fraction').reset_index())
    # If this was multiplied by the H2 demand per year, then we would be forcing
    # existing SMR to meet exogenous H2 demand forever and we don't want that.
    # Only for it to meet 2023 demand
    h2_existing_smr_cap['million_tons'] = h2_existing_smr_cap['fraction'] * h2_demand_initial
    h2_existing_smr_cap['value'] =  (
        h2_existing_smr_cap['million_tons'] * 1e9 * smr_init_ele_efficiency
        / 8760 / 1000 / (1 - smr_outage_forced) * 1.0001)
    # Make any value after h2_prod_first_year to be the same MW value as h2_prod_first_year
    # (aka we will not force model to build more SMR capacity in 2030 once it has already
    # met h2 demand in 2024). aka if model year is 2024, then from 2024-2050, the data
    # will be the same df with columns t, r, fraction, million metric tons,
    # value for 134 different BAs in h2_prod_first_year
    # (but only do this if endyear > h2_prod_first_year, otherwise it will introduce NaNs)
    if endyear > h2_prod_first_year:
        h2_prod_first_year_df = h2_existing_smr_cap[
            h2_existing_smr_cap['t']==h2_prod_first_year
        ].drop(['t'], axis=1)
        # For any years after h2_prod_first_year
        after_h2_prod_first_year_df = h2_existing_smr_cap[
            h2_existing_smr_cap['t'] > h2_prod_first_year
        ].drop(['fraction','million_tons','value'], axis=1)
        # New df from 2025 --> 2050
        after_h2_prod_first_year_df = pd.merge(
            h2_prod_first_year_df,
            after_h2_prod_first_year_df,
            how='left', on=['r'],
        )
        # Concat 2010-2024 df and 2025-->end of model
        h2_existing_smr_cap = pd.concat([
            h2_existing_smr_cap[h2_existing_smr_cap['t']<=h2_prod_first_year],
            after_h2_prod_first_year_df
        ])
    # Filter down to modeled regions and years (otherwise b_inputs will throw an error)
    h2_existing_smr_cap = h2_existing_smr_cap.sort_values(by=['t','r'])


    #%%----------------------------------------------------------------------------
    ################################
    #    -- Retirements Data --    #
    ################################
    print('Gathering Retirement Data...')

    rets_data = {}
    for rettype in ['retirements','retirements_energy']:
        rets_df = gdb_use.loc[(gdb_use['tech'].isin(TECH[rettype])) &
                        (gdb_use[retscen]>startyear) & (gdb_use[retscen]<=endyear) &
                        (gdb_use['StartYear'] <= endyear)
                        ].copy()

        # Assign the retirements type based on whether the unit was online before or after startyear
        rets_df['type'] = None
        if len(rets_df) > 0:
            rets_df.loc[rets_df['StartYear'] >= startyear,'type']='prescribed'
            rets_df.loc[rets_df['StartYear'] < startyear, 'type']='existing'

        rets_df['tech'] = rets_df['tech'].str.lower()
        rets_df= pd.merge(rets_df, ivt_df, how='left', left_on='tech', right_on='Unnamed: 0')
        rets_df['v'] = rets_df.apply(lambda row: f"new{row[str(row['StartYear'])]}"
                            if row['StartYear'] >= startyear
                            else "init-1",axis=1)
        rets_df['StartYear']=rets_df['StartYear'].apply(lambda x: assign_modeledyear(x, years))
        rets_df[retscen]=rets_df[retscen].apply(lambda x: assign_modeledyear(x, years))
        rets_df = rets_df[COLNAMES[rettype][0]]
        rets_df.columns = COLNAMES[rettype][1]
        rets_df.sort_values(by=COLNAMES[rettype][1],inplace=True)
        rets_df = rets_df.groupby(COLNAMES[rettype][1][:-1]).sum().reset_index()
        rets_data[rettype] = rets_df.copy()
    ## Unpack
    rets = rets_data['retirements']
    rets_energy = rets_data['retirements_energy']

    ################################
    #    -- Wind Retirements --    #
    ################################
    print('Gathering Wind Retirement Data...')
    maxage_data = pd.read_csv(os.path.join(inputs_case, 'maxage.csv'))
    wind_maxage = maxage_data[maxage_data.iloc[:,0].str.contains('wind-ons')].values[0,1]

    wind_rets = gdb_use.loc[(gdb_use['tech'].isin(TECH['windret'])) &
                            (gdb_use['StartYear'] <= startyear) &
                            (gdb_use['RetireYear'] >  startyear) &
                            (gdb_use['RetireYear'] <  startyear + wind_maxage)
                            ]
    wind_rets = wind_rets[COLNAMES['windret'][0]]
    wind_rets.columns = COLNAMES['windret'][1]
    wind_rets['v'] = 'init-1'
    wind_rets = wind_rets.groupby(['i','v','r','t']).sum().reset_index()

    wind_rets = (wind_rets.pivot_table(index = ['i','v','r'], columns = 't', values='value')
                        .reset_index()
                        .fillna(0)
                )
    #================================
    #   --- Geothermal Retirements ---
    #================================
    print('Gathering Geothermal Retirement Data...')
    geo_maxage = maxage_data[maxage_data.iloc[:,0].str.contains('geothermal')].values[0,1]
    geo_retirements = gdb_use.loc[(gdb_use['tech'].isin(TECH['georet'])) &
                    (gdb_use['StartYear'] <= startyear) &
                    (gdb_use['RetireYear'] >  startyear) &
                    (gdb_use['RetireYear'] <  startyear + geo_maxage)
                    ]
    geo_retirements = geo_retirements[COLNAMES['georet'][0]]
    geo_retirements.columns = COLNAMES['georet'][1]
    geo_retirements['v'] = 'init-1'
    geo_retirements = geo_retirements.groupby(['i','v','r','t']).sum().reset_index()

    geo_retirements = (geo_retirements
            .pivot_table(index = ['i','v','r'], columns = 't', values='value')
            .reset_index()
            .fillna(0)
            )


    #%%----------------------------------------------------------------------------
    #############################################################
    #    -- Hydro Capacity Adjustment Factors: CC-Seasaon --    #
    #############################################################

    # Initialize with monthly hydropower capacity adjustment factor values
    hydcapadj_ccszn = pd.read_csv(os.path.join(inputs_case,'hydcapadj.csv')).rename(columns={'*i':'i'})
    #Filter to regions in function call
    hydcapadj_ccszn = hydcapadj_ccszn[hydcapadj_ccszn['r'].isin(regions)]
    # Map hot/cold values to ccseason months and filter for ccseason data
    hydcapadj_ccszn['ccseason'] = hydcapadj_ccszn['month'].map(hotcold_months)
    hydcapadj_ccszn = (hydcapadj_ccszn[hydcapadj_ccszn['ccseason'].isin(['cold','hot'])]
                    .drop(columns='month'))
    # Average monthly data to get factor values by ccseason
    hydcapadj_ccszn = hydcapadj_ccszn.groupby(['i','r','ccseason']).mean().reset_index()
    hydcapadj_ccszn['value'] = hydcapadj_ccszn['value'].round(5)


    #%%----------------------------------------------------------------------------
    ########################################
    #    -- Waterconstraint Indexing --    #
    ########################################

    if len(rets) > 0:
        rets['i'] = rets['i'].str.lower()
    if len(rets_energy) > 0:
        rets_energy['i'] = rets_energy['i'].str.lower()
    if len(prescribed_nonRSC) > 0:
        prescribed_nonRSC['i'] = prescribed_nonRSC['i'].str.lower()
    if len(prescribed_nonRSC_energy) > 0:
        prescribed_nonRSC_energy['i'] = prescribed_nonRSC_energy['i'].str.lower()

    # When water constraints are enabled, retirements are also indexed by cooling technology
    # and cooling water source. otherwise, they only have the indices of year, region, and tech
    if GSw_WaterMain == 1:
        ### Group by all cols except 'value'
        rets = rets.groupby(COLNAMES['retirements'][1][:-1]).sum().reset_index()
        rets.columns = COLNAMES['retirements'][1]

        capnonrsc = capnonrsc.groupby(COLNAMES['capnonrsc'][1][:-1]).sum().reset_index()
        capnonrsc.columns = COLNAMES['capnonrsc'][1]

        prescribed_nonRSC = (
            prescribed_nonRSC
            .groupby(COLNAMES['prescribed_nonRSC'][1][:-1]).sum().reset_index())
        prescribed_nonRSC.columns = COLNAMES['prescribed_nonRSC'][1]

        prescribed_nonRSC_energy = (
            prescribed_nonRSC_energy
            .groupby(COLNAMES['prescribed_nonRSC_energy'][1][:-1]).sum().reset_index())

        rets['i'] = rets['coolingwatertech']
        rets = rets.groupby(['i','v','r','t','tt','type']).value.sum().reset_index()
        rets.columns = ['i','v','r','t','tt','type','value']

        capnonrsc['i'] = capnonrsc['coolingwatertech']
        capnonrsc = capnonrsc.groupby(['i','r']).value.sum().reset_index()
        capnonrsc.columns = ['i','r','value']

        prescribed_nonRSC['i'] = prescribed_nonRSC['coolingwatertech']
        prescribed_nonRSC = prescribed_nonRSC.groupby(['i','v','r','t']).value.sum().reset_index()
        prescribed_nonRSC.columns = ['i','v','r','t','value']

        prescribed_nonRSC_energy['i'] = prescribed_nonRSC_energy['coolingwatertech']
        prescribed_nonRSC_energy = prescribed_nonRSC_energy.groupby(['i','v','r','t']).value.sum().reset_index()
        prescribed_nonRSC_energy.columns = ['i','v','r','t','value']
    else:
    # Group by [year, region, tech]
        rets = rets.groupby(['i','v','r','t','tt','type']).value.sum().reset_index()
        rets.columns = ['i','v','r','t','tt','type','value']

        capnonrsc = capnonrsc.groupby(['i','r']).value.sum().reset_index()
        capnonrsc.columns = ['i','r','value']

        prescribed_nonRSC = prescribed_nonRSC.groupby(['i','v','r','t']).value.sum().reset_index()
        prescribed_nonRSC.columns = ['i','v','r','t','value']

        prescribed_nonRSC_energy = prescribed_nonRSC_energy.groupby(['i','v','r','t']).value.sum().reset_index()
        prescribed_nonRSC_energy.columns = ['i','v','r','t','value']

    # Final Groupby step for capacity groupings not affected by GSw_WaterMain:
    caprsc = caprsc.groupby(['i','v','r']).value.sum().reset_index()
    prescribed_rsc = prescribed_rsc.groupby(['i','v','r','t']).value.sum().reset_index()


    #%%----------------------------------------------------------------------------
    ################################
    #    -- Canadian Imports --    #
    ################################

    can_imports_year_mwh = pd.read_csv(os.path.join(inputs_case,'can_imports.csv'),
                                    index_col='r').dropna()
    # Filter to regions in function call
    can_imports_year_mwh = can_imports_year_mwh[can_imports_year_mwh.index.isin(regions)]
    can_imports_year_mwh.columns = can_imports_year_mwh.columns.astype(int)
    can_imports_year_mwh = can_imports_year_mwh.reindex(years, axis=1).dropna(axis=1)

    ## Get hours per quarter
    year = sw['GSw_HourlyWeatherYears'].split('_')[0]
    timestamps = pd.Series(index=pd.date_range(f'{year}-01-01', periods=8760, freq='h'))

    month2quarter = pd.read_csv(
        os.path.join(inputs_case, 'month2quarter.csv'),
        index_col='month',
    ).squeeze(1)

    quarterhours = timestamps.index.month.map(month2quarter).value_counts()
    quarterhours.index = quarterhours.index.map(lambda x: quartershorten.get(x,x)).rename('szn')

    can_imports_quarter_frac = pd.read_csv(os.path.join(inputs_case,'can_imports_quarter_frac.csv'),
                                    header=0, names=['szn','frac'], index_col='szn'
                                    ).squeeze(1)
    can_imports_capacity = (
        ## Start with annual imports in MWh
        pd.concat({szn: can_imports_year_mwh for szn in quartershorten.values()}, axis=0, names=['szn','r'])
        ## Multiply by season frac to get MWh per season
        .multiply(can_imports_quarter_frac, axis=0, level='szn')
        ## Divide by hours per season to get average MW by season
        .divide(quarterhours, axis=0, level='szn')
        ## Keep the max value across seasons
        .groupby('r').max()
        ## Reshape for GAMS
        .stack().rename_axis(['r','t']).rename('MW').round(3)
    )

    #%%----------------------------------------------------------------------------
    ##############################
    #    -- Data Write-Out --    #
    ##############################

    #Round outputs before writing out
    for df in [rets, rets_energy, capnonrsc, capnonrsc_energy, prescribed_nonRSC, prescribed_nonRSC_energy,
               caprsc, prescribed_rsc, h2_existing_smr_cap]:
        df['value'] = df['value'].round(6)
        # Set all years to integer datatype
        if 't' in df.columns:
            df['t'] = df.t.astype(float).round().astype(int)

    #%%
    # Return
    files_out = {'capnonrsc' :  capnonrsc[['i','r','value']],
                'capnonrsc_energy' : capnonrsc_energy[['i','r','value']],
                'rets' :  rets[['i','v','r','t','tt','type','value']],
                'rets_energy' : rets_energy[['i','v','r','t','tt','type','value']],
                'prescribed_nonRSC' : prescribed_nonRSC[['i','v','r','t','value']],
                'prescribed_nonRSC_energy' : prescribed_nonRSC_energy[['i','v','r','t','value']],
                'caprsc' :caprsc[['i','v','r','value']],
                'prescribed_rsc' : prescribed_rsc[['i','v','r','t','value']],
                'wind_rets' : wind_rets,
                'h2_existing_smr_cap' : h2_existing_smr_cap[['r','t','value']],
                'geo_retirements' : geo_retirements,
                'poi_cap_init' : poi_cap_init,
                'cap_cspns': cap_cspns.reset_index(),
                'rsc_wsc':rsc_wsc,
                'hydcapadj_ccszn' : hydcapadj_ccszn[['i','ccseason','r','value']],
                'can_imports_capacity' : can_imports_capacity.reset_index(),
                'geoexist' : geoexist,
                'h2_ba_share': h2_ba_share_out,
                'exog_cap_upv':cap_exog['upv'],
                'exog_cap_wind-ons':cap_exog['wind-ons'],
                'exog_cap_wind-ofs':cap_exog['wind-ofs'],
                'exog_cap_geohydro':cap_exog['geohydro_allkm']
                }

    return files_out


#%% ===========================================================================
### --- PROCEDURE ---
### ===========================================================================

if __name__ == '__main__':
    ### Time the operation of this script
    tic = datetime.datetime.now()

    ### Parse arguments
    parser = argparse.ArgumentParser(description="""This file processes plant cost data by tech""")
    parser.add_argument("reeds_path", help="ReEDS directory")
    parser.add_argument("inputs_case", help="path to runs/{case}/inputs_case")

    args = parser.parse_args()
    reeds_path = args.reeds_path
    inputs_case = args.inputs_case

    # #%% Settings for testing
    # reeds_path = reeds.io.reeds_path
    # inputs_case = os.path.join(reeds_path,'runs','v20260804_inputsM0_Simple','inputs_case')

    #%% Set up logger
    log = reeds.log.makelog(
        scriptname=__file__,
        logpath=os.path.join(inputs_case,'..','gamslog.txt'),
    )
    print('Starting writecapdat.py')

    #%% Run procedure
    files_out = main(reeds_path, inputs_case)

    #%% Write outputs
    print('Writing out capacity data')
    outname = {
        'rets': 'retirements',
        'rets_energy': 'retirements_energy',
        'wind_rets': 'wind_retirements',
        'hydcapadj_ccszn': 'cap_hyd_ccseason_adj',
    }
    gamstype = {
        'poi_cap_init': 'parameter',
    }
    comment = {
        'poi_cap_init': '--MW-- initial (pre-startyear) capacity of all types',
    }
    for key, df in files_out.items():
        if gamstype.get(key, False):
            reeds.io.write_to_inputs_h5(
                df=df, key=outname.get(key, key), case=inputs_case, gamstype=gamstype[key],
                comment=comment.get(key, ''),
            )
        else:
            fpath = os.path.join(inputs_case, f'{outname.get(key, key)}.csv')
            reeds.io.gamsify_header(df).to_csv(fpath, index=False)

    reeds.log.toc(tic=tic, year=0, process='input_processing/writecapdat.py',
        path=os.path.join(inputs_case,'..'))

    print('Finished writecapdat.py')
