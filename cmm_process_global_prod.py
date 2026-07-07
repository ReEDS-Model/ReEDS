
#-------------------------------------------------------------------
# Packages
#-------------------------------------------------------------------

import pandas as pd
import numpy as np
import os
import re

#-------------------------------------------------------------------
# Directories
#-------------------------------------------------------------------
                                                                                
workdir = os.path.dirname(os.path.abspath(__file__))

#-------------------------------------------------------------------
# Import Data
#-------------------------------------------------------------------

prod_df = pd.read_csv(os.path.join(workdir, 'cmm_global_mat_prod_raw.csv'))
price_df = pd.read_csv(os.path.join(workdir, 'cmm_global_mat_price_raw.csv'))
deflator_df = pd.read_csv(os.path.join(workdir, 'inputs', 'financials', 'deflator.csv'))
byproduct_df = pd.read_csv(os.path.join(workdir, 'cmm_byproduct_raw.csv'))

### PRODUCTION AND RESERVE DATA ####
# keep relevant columns
prod_df = prod_df.iloc[:, 0:5]
new_cols = ['* mat','mat_ctry','value','type','sc_pt']
prod_df.columns = new_cols

# trim whitespace and clean up values
prod_df['* mat'] = prod_df['* mat'].str.strip()
prod_df['mat_ctry'] = prod_df['mat_ctry'].str.strip()
prod_df['type'] = prod_df['type'].str.strip()
prod_df['sc_pt'] = prod_df['sc_pt'].str.strip()

# clean up value column
prod_df['value'] = pd.to_numeric(prod_df['value'], errors='coerce').fillna(0)

# clean up country names
prod_df['mat_ctry'].unique()
prod_df['mat_ctry'] = prod_df['mat_ctry'].replace('Other countries','Other') 
prod_df['mat_ctry'] = prod_df['mat_ctry'].replace('United States','USA') 
prod_df['mat_ctry'] = prod_df['mat_ctry'].replace('Republic of Korea','South_Korea') 
prod_df['mat_ctry'] = prod_df['mat_ctry'].replace('Côte d’Ivoire','Cote_d_Ivoire') 
prod_df['mat_ctry'] = prod_df['mat_ctry'].replace('Congo(Kinshasa)','Congo') 
prod_df['mat_ctry'] = prod_df['mat_ctry'].replace('United Arab Emirates','UAE') 
prod_df['mat_ctry'] = prod_df['mat_ctry'].replace('China and Burma','China') 
prod_df['mat_ctry'] = prod_df['mat_ctry'].str.replace(r'\s+', '_', regex=True)

# ensure not double counting production at multiple points in supply chain  
prod_df['* mat'].unique()
# Magnesium compound production is magnesite at mine site. 
prod_df['* mat'] = prod_df['* mat'].replace('Magnesium Compounds','Magnesium')
prod_df = prod_df[prod_df['* mat'] != 'Magnesium Metal']
# filter out rare earths
prod_df = prod_df[prod_df['* mat'] != 'Rare Earths']
# Titanium concentrates are ilmenite and Rutile at mine site. Titanium dioxide is at refinery stage. 
prod_df['* mat'] = prod_df['* mat'].replace('Titanium Mineral Concentrates','Titanium')
prod_df = prod_df[prod_df['* mat'] != 'Titanium and Titanium Dioxide']
# Copper and Hafnium keep only mine production
prod_df = prod_df[~((prod_df['* mat'] == 'Copper') & (prod_df['sc_pt'] == 'Refinery'))]
prod_df = prod_df[~((prod_df['* mat'] == 'Hafnium') & (prod_df['sc_pt'] == 'Refinery'))]

# split data into production and reserve data
reserve_df = prod_df[prod_df['type'] == 'Reserves']
prod_df = prod_df[prod_df['type'] == 'Production']

# double check reserve data for duplicates (none); filter to US and select columns
reserve_duplicate = reserve_df.duplicated(subset=['* mat','mat_ctry'], keep=False)
reserve_df = reserve_df[reserve_df['mat_ctry'] == 'USA']
reserve_df = reserve_df[['* mat','mat_ctry','value']]

# identify duplicates and separate from non-duplicates
prod_duplicate = prod_df.duplicated(subset=['* mat','mat_ctry'], keep=False)
prod_df_no_duplicates = prod_df[~prod_duplicate]
prod_df_duplicates = prod_df[prod_duplicate]

# create function for processing duplicate data
def process_duplicates(group):
    # Get the material name for this group (it's the same for all rows in the group)
    material_name = group['* mat'].iloc[0]

    # Rule 1: If the material is 'Silicon', sum the values
    # because the two types of silicon are separate products
    if material_name == 'Silicon':
        total_production = round(group['value'].sum(), 2)
        result_row = group.iloc[[0]].copy()
        result_row['value'] = total_production
        result_row['sc_pt'] = 'Aggregated Silicon'
        return result_row

    # Rule 3: Otherwise (fallback for all other materials), keep the 'Mine' row
    # because mine vs refinery are different steps in supply chain
    else:
        return None # Or handle as needed if no 'Mine' row exists

# run function and combine non-duplicate and processed duplicate data
processed_duplicates = prod_df_duplicates.groupby(['* mat','mat_ctry']).apply(process_duplicates)
processed_duplicates = processed_duplicates.reset_index(drop=True)
prod_df = pd.concat([prod_df_no_duplicates, processed_duplicates], ignore_index=True)
# double check no more duplicates
prod_duplicate = prod_df.duplicated(subset=['* mat','mat_ctry'], keep=False)
# select only relevant columns for model
prod_df = prod_df[['* mat','mat_ctry','value']]

prod_df.to_csv(os.path.join(workdir, 'cmm_global_mat_prod.csv'), index=False)
reserve_df.to_csv(os.path.join(workdir, 'cmm_us_reserves.csv'), index=False)


### LIST OF PRODUCING COUNTRIES AND ALLIES ###
# make set of countries for which we have production data
countries_array = prod_df['mat_ctry'].unique()
countries = pd.DataFrame(countries_array, columns=['* mat_ctry'])
caption = "* set of countries for which we have materials production data"
caption_df = pd.DataFrame([caption], columns=['* mat_ctry'])
countries = pd.concat([caption_df, countries], ignore_index=True)

countries.to_csv(os.path.join(workdir, 'cmm_countries.csv'), index=False)


# make set of countries for analysis domestic + allied analysis 
# list of free trade countries from here: https://ustr.gov/trade-agreements/free-trade-agreements
free_trade = np.array(['Australia','Bahrain','Canada','Chile','Colombia','Costa_Rica','Dominican_Republic','El_Salvador',
                        'Guatemala','Honduras','Israel','Japan','Jordan','South_Korea','Mexico','Morocco','Nicaragua','Oman',
                        'Panama','Peru','Singapore'])
ptaap_rta = np.array(['Argentina','Bangladesh','Cambodia','Ecuador','El_Salvador','Guatemala','Indonesia','Malaysia','Taiwan'])
ptaap_framework = np.array(['Austria','Belgium','Bulgaria','Croatia','Cyprus','Czech Republic','Denmark','Estonia','Finland',
                        'France','Germany','Greece','Hungary','India','Ireland','Italy','Japan','Latvia','Liechtenstein',
                        'Lithuania','Luxembourg','Malta','Netherlands','North Macedonia','Poland','Portugal','Romania',
                        'Slovakia','Slovenia','South Korea','Spain','Sweden','Switzerland','Thailand','United Kingdom','Vietnam'])

agreements = np.unique(np.concatenate([free_trade, ptaap_rta, ptaap_framework]))
allies = np.intersect1d(countries_array, agreements)
allies = pd.DataFrame(allies,columns=['* allies'])
caption = "* allied countries with material inputs for power"
caption_df = pd.DataFrame([caption],columns=['* allies'])
allies = pd.concat([caption_df, allies], ignore_index=True)

allies.to_csv(os.path.join(workdir, 'cmm_allies.csv'), index=False)

### BYPRODUCT DATA ###  
byproduct_df['byproduct_mT'] = byproduct_df['Ktons_recovery'] * 1000
power_materials =np.array(['Alumina', 'Aluminum', 'Bauxite', 'Boron', 'Cadmium', 'Chromium', 'Cobalt', 'Copper', 'Dysprosium', 
                        'Gallium', 'Gold', 'Hafnium', 'Indium', 'Iron_ore', 'Lead', 'Lithium', 'Magnesium', 'Manganese', 
                        'Molybdenum', 'Neodymium', 'Nickel', 'Niobium', 'Praseodymium', 'Phosphate_rock', 'Selenium', 'Silicon', 
                        'Silver', 'Steel', 'Tantalum', 'Tellurium', 'Terbium', 'Tin', 'Titanium', 'Tungsten', 
                        'Vanadium', 'Yttrium', 'Zinc', 'Zirconium'])

byproduct_df = byproduct_df[byproduct_df["Element_name"].isin(power_materials)]
byproduct_df = byproduct_df[['Element_name','byproduct_mT']]
byproduct_df['mat_ctry'] = 'USA'
new_cols = ['* mat','value','mat_ctry']
byproduct_df.columns = new_cols
byproduct_df = byproduct_df[['* mat','mat_ctry','value']]
byproduct_df.to_csv(os.path.join(workdir, 'cmm_us_byproduct.csv'), index=False)

# PRICE DATA

price_df = price_df[['Material','Product','Type','price_per_tonne','year_source']]
price_df['Material'] = price_df['Material'].str.strip()
price_df['Material'] = price_df['Material'].str.replace(r'\s+', '_', regex=True)

# remove prices not needed 
#keep only metal chromium
price_df = price_df[~((price_df['Material'] == 'Chromium') & (price_df['Product'] == 'ore'))]
price_df = price_df[~((price_df['Material'] == 'Chromium') & (price_df['Product'] == 'alloy'))]
# keep only refined gallium (from notes in source document)
price_df = price_df[~((price_df['Material'] == 'Gallium') & (price_df['price_per_tonne'] == 220000.0))]
# keep only magnesium metal 
price_df = price_df[~((price_df['Material'] == 'Magnesium') & (price_df['Product'] == 'chemical compound'))]
# keep only titanium metal
price_df = price_df[~((price_df['Material'] == 'Titanium') & (price_df['Product'] == 'chemical compound'))]
price_df = price_df[~((price_df['Material'] == 'Titanium') & (price_df['Product'] == 'mineral concentrate'))]
# keep only yttrium metal 
price_df = price_df[~((price_df['Material'] == 'Yttrium') & (price_df['Product'] == 'chemical compound'))]
# keep only zinc metal
price_df = price_df[~((price_df['Material'] == 'Zirconium') & (price_df['Product'] == 'ore'))]
# keep only manganese metal 
price_df = price_df[~((price_df['Material'] == 'Manganese') & (price_df['Product'] == 'ore'))]
price_df = price_df[~((price_df['Material'] == 'Manganese') & (price_df['Product'] == 'alloy'))]

# deflate prices 
new_cols = ['year','deflator']
deflator_df.columns = new_cols
deflator_df.loc[len(deflator_df)] = {'year': 2025, 'deflator': 0.586666667} # calculated from https://www.minneapolisfed.org/about-us/monetary-policy/inflation-calculator/consumer-price-index-1800-
deflator_df.loc[len(deflator_df)] = {'year': 2026, 'deflator': 0.586666667} # using 2025 because pulled in Q1 of 2026

price_df = pd.merge(
    price_df,
    deflator_df,
    how='left',
    left_on='year_source', # Key in the left DataFrame
    right_on='year'      # Key in the right DataFrame
)

price_df['price_per_tonne_2004'] = price_df['price_per_tonne'] * price_df['deflator']
price_df['price_per_tonne_2004'] = price_df['price_per_tonne_2004'].round(2)

# take average by material type (keeping current for reference and 2004 for deflated price to go in model)
price_df = price_df.groupby(['Material'], as_index=False)[['price_per_tonne','price_per_tonne_2004']].mean().round(2)

#print prices to output in presentation
#price_df.to_csv(os.path.join(workdir, 'cmm_price_temp.csv'), index=False)

price_df = price_df[['Material','price_per_tonne']]
new_cols = ['* mat','price']
price_df.columns = new_cols

price_df.to_csv(os.path.join(workdir, 'cmm_global_mat_price.csv'), index=False)