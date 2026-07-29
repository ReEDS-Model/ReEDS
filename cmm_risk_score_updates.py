import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


# process the export control dataset

export_control_df = pd.read_csv('cmm_export_controls.csv',skiprows=1)
cmm_hs_codes = pd.read_csv('cmm_hs_codes.csv')
cmm_countries = pd.read_csv('cmm_countries.csv', skiprows=2)

# filter down to relevant hs codes, group by country and hs6, keep most recent year, remove eliminated policies

ec_df = export_control_df[export_control_df['HS6'].isin(cmm_hs_codes['id'])]
ec_df = ec_df.loc[ec_df.groupby(['Country', 'HS6'])['year'].idxmax()]
ec_df = ec_df[ec_df['dir'] != 'elimination']
ec_df = ec_df[ec_df['end'] == 'nd']

# Clean country and type names: replace spaces with underscores and align names of countries with cmm_countries
ec_df['Country'] = ec_df['Country'].str.replace(' ', '_')
ec_df['type'] = ec_df['type'].str.replace(' ', '_')
ec_df['Country'] = ec_df['Country'].replace('United_Arab_Emirates', 'UAE')
ec_df['Country'] = ec_df['Country'].replace('Dem_Rep_of_Congo', 'Congo')
ec_df['Country'] = ec_df['Country'].replace('Mayanmar', 'Burma')
ec_df['Country'] = ec_df['Country'].replace('Russian Federation', 'Russia')

# Read countries from cmm_countries
cmm_countries_list = cmm_countries.iloc[:, 0].tolist()

# Filter ec_df to only countries in cmm_countries
ec_df = ec_df[ec_df['Country'].isin(cmm_countries_list)]

# merge with cmm_hs_codes to get duplicates if multiple materials per HS6
cmm_hs_codes_clean = cmm_hs_codes[['mat', 'id']].rename(columns={'id': 'HS6', 'mat': 'Material'})
ec_df = ec_df.merge(cmm_hs_codes_clean, on='HS6', how='left')


# select relevant columns and rename them
ec_df = ec_df[['Country','HS6', 'type', 'Material']]

# Print unique values in type column
print("Unique values in 'type' column:")
print(ec_df['type'].unique())

# Group by Country, HS6, and Material, then pivot type column to wider format
# Use pivot_table to create binary columns for each type value
ec_df['value'] = 1
ec_df_wide = ec_df.pivot_table(index=['Country', 'HS6', 'Material'], columns='type', values='value', fill_value=0)
ec_df_wide = ec_df_wide.reset_index()

# Sort by Country, then Material
ec_df_wide = ec_df_wide.sort_values(['Country', 'Material'])

# Drop HS6 column and remove duplicates on remaining columns
ec_df_wide = ec_df_wide.drop('HS6', axis=1)
ec_df_wide = ec_df_wide.drop_duplicates()

# Add indicator columns from type columns
id_cols = ['Country', 'Material']
type_cols = [c for c in ec_df_wide.columns if c not in id_cols]

# 1 if any type column has a value
ec_df_wide['any_restrict'] = ec_df_wide[type_cols].gt(0).any(axis=1).astype(int)

# 1 if export prohibition or licensing requirement is present
supply_cols = [
    c for c in type_cols
    if ('prohibition' in c.lower()) or ('licensing' in c.lower()) or ('captive' in c.lower())
]
if supply_cols:
    ec_df_wide['supply_restrict'] = ec_df_wide[supply_cols].gt(0).any(axis=1).astype(int)
else:
    ec_df_wide['supply_restrict'] = 0

# 1 if any tax-related type is present
tax_cols = [c for c in type_cols if 'tax_restrict' in c.lower()]
if tax_cols:
    ec_df_wide['tax'] = ec_df_wide[tax_cols].gt(0).any(axis=1).astype(int)
else:
    ec_df_wide['tax'] = 0

## we probably want one row per country and material, 
# with the type columns having more than one positive value depending the type that exists.. update?