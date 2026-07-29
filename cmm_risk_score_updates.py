import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


# process the export control dataset
# source: https://www.oecd.org/en/topics/export-restrictions-on-critical-raw-materials.html
# documentation: https://www.oecd.org/content/dam/oecd/en/topics/policy-sub-issues/export-restrictions-on-critical-raw-materials/methodological-note-inventory-export-restrictions-industrial-raw-materials_2025.pdf
export_control_df = pd.read_csv('cmm_export_controls.csv',skiprows=1)
cmm_hs_codes = pd.read_csv('cmm_hs_codes.csv')
cmm_countries = pd.read_csv('cmm_countries.csv', skiprows=2)
cmm_prod = pd.read_csv('cmm_global_mat_prod.csv', names=['Material', 'Country', 'Production'],skiprows=1)

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

# Collapse Country-Material combinations by taking max of policy columns
# This combines rows for the same country-material pair with different policies
ec_df_wide = ec_df_wide.groupby(['Country', 'Material'], as_index=False).max()

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
tax_cols = [c for c in type_cols if 'tax' in c.lower()]
if tax_cols:
    ec_df_wide['tax_restrict'] = ec_df_wide[tax_cols].gt(0).any(axis=1).astype(int)
else:
    ec_df_wide['tax_restrict'] = 0

# Merge with production data
ec_df_wide = ec_df_wide.merge(cmm_prod, on=['Country', 'Material'], how='left')
ec_df_wide['Production'] = ec_df_wide['Production'].fillna(0)

# Create realized_risk summary by material
# Total production by material
total_prod_material = cmm_prod.groupby('Material')['Production'].sum().reset_index()
total_prod_material.columns = ['Material', 'total_prod_material'] 

# Production from countries with restrictions
restricted_prod = ec_df_wide[ec_df_wide['any_restrict'] == 1].groupby('Material')['Production'].sum().reset_index()
restricted_prod.columns = ['Material', 'restricted_prod']

# Production from countries with supply restrictions
supply_restricted_prod = ec_df_wide[ec_df_wide['supply_restrict'] == 1].groupby('Material')['Production'].sum().reset_index()
supply_restricted_prod.columns = ['Material', 'supply_restricted_prod']


# Production from countries with taxrestrictions
tax_restricted_prod = ec_df_wide[ec_df_wide['tax_restrict'] == 1].groupby('Material')['Production'].sum().reset_index()
tax_restricted_prod.columns = ['Material', 'tax_restricted_prod']

# Merge to create realized_risk
realized_risk = total_prod_material.merge(restricted_prod, on='Material', how='left')
realized_risk['restricted_prod'] = realized_risk['restricted_prod'].fillna(0)
realized_risk = realized_risk.merge(supply_restricted_prod, on='Material', how='left')
realized_risk['supply_restricted_prod'] = realized_risk['supply_restricted_prod'].fillna(0)
realized_risk = realized_risk.merge(tax_restricted_prod, on='Material', how='left')
realized_risk['tax_restricted_prod'] = realized_risk['tax_restricted_prod'].fillna(0)

# Calculate share of production from restricted countries
realized_risk['share_restricted'] = round(realized_risk['restricted_prod'] / realized_risk['total_prod_material'], 2)
realized_risk['share_supply_restricted'] = round(realized_risk['supply_restricted_prod'] / realized_risk['total_prod_material'], 2)
realized_risk['share_tax_restricted'] = round(realized_risk['tax_restricted_prod'] / realized_risk['total_prod_material'], 2)

# need to update this to include the changes to trade policy with new administration. 