"""
Functions for processing reV wind and solar resource supply curve and profile data for use in ReEDS.
Typically called from "run_hourlize.py" -- see README for setup and details.
"""

#%% ===========================================================================
### --- IMPORTS ---
### ===========================================================================
import argparse
import datetime
import h5py
import json
import math
import numpy as np
import os
import pandas as pd
import shutil
import site
from collections import OrderedDict
from types import SimpleNamespace
from glob import glob

## ReEDS modules imported using reeds_path in main procedure

#%% ===========================================================================
### --- HELPER FUNCTIONS ---
### ===========================================================================
def copy_rev_jsons(outpath, rev_path):
    """helper function to copy reV json config files into repo as metadata

    Parameters
    ----------
    outpath
        path to direcotry for this hourlize run
    rev_path
        path to reV folder with jsons
    """
    os.makedirs(os.path.join(outpath, 'inputs', 'rev_configs'), exist_ok=True)
    rev_jsons = glob(os.path.join(rev_path, "*.json*"))
    for jsonfile in rev_jsons:
        try:
            shutil.copy2(
                jsonfile,
                os.path.join(outpath, 'inputs', 'rev_configs', os.path.basename(jsonfile)),
            )
        except FileNotFoundError as err:
            print(f"WARNING: {err}")
    print('Done copying rev json files')
    rev_jsons_out = [os.path.basename(jsonfile) for jsonfile in rev_jsons]
    return rev_jsons_out


#%% ===========================================================================
### --- SUPPLY CURVE PROCESSING ---
### ===========================================================================

def aggregate_supply_curves_by_lowest_lcoe(rev_cases_path, rev_sc_file_path):
    """Only used for geothermal"""
    raw_sc_files = os.path.join(rev_cases_path, "raw_supply_curves")

    sc_list = []
    for _, _, files in os.walk(raw_sc_files):
        for file in files:
            sc_list.append(pd.read_csv(os.path.join(raw_sc_files, file)))
    
    df_sc_agg = pd.concat(sc_list)
    df_sc_lowest_lcoe = (
        df_sc_agg.sort_values(["lcoe_all_in_usd_per_mwh", "lcoe_site_usd_per_mwh"], ascending=True)
        .groupby(["sc_point_gid"], as_index=False)
        .first()
        .reset_index(drop=True)
    )
    
    df_sc_lowest_lcoe.to_csv(rev_sc_file_path)


def match_to_counties(sc, profile_id_col, outpath, tech, offshore_meshed=False):
    """adds county FIPS code to reV supply curve

    Parameters
    ----------
    sc
        pandas dataframe of supply curve
    reeds_path
        path to ReEDS directory

    Returns
    -------
        pandas dataframe with columns for county FIPS code and county name
    """
    print("Adding county FIPS code")
    offshore = True if tech == 'wind-ofs' else False
    ## Get mapping from sc_point_gid to FIPS
    sitemap = reeds.io.get_sitemap(offshore=offshore, geo=False)
    if offshore and offshore_meshed:
        ## Replace FIPS with offshore zone for sites that can be meshed
        sitemap.loc[sitemap.always_radial == False, 'FIPS'] = (
            sitemap.loc[sitemap.always_radial == False, 'ba']
        )
    else:
        sitemap['always_radial'] = True
    assert sitemap.index.name == 'sc_point_gid', 'sitemap index must be sc_point_gid'
    dfout = sc.copy()
    dfout['FIPS'] = dfout['sc_point_gid'].map(sitemap.FIPS)
    ## Check for missing counties
    missing_counties = dfout['FIPS'].isnull()
    ## Confirmed with Gabe 20250911: The interconnection_land table only has sites with
    ## offshore_flag = False, and we should drop land-based sites from the supply curve
    ## with offshore_flag = True (i.e., sites that are not in the interconnection cost
    ## table, which produces the sitemap used here.) There should only be a small number
    ## of edge sites in the land-based supply curves that are flagged as offshore, so
    ## as long as it's less than 2% of the total number of sites, just drop them.
    if missing_counties.sum() / len(dfout) > 0.02:
        print(dfout.loc[missing_counties].set_index('sc_point_gid'))
        if missing_counties.sum() <= 1000:
            print('Missing sc_point_gids:')
            print('\n'.join(dfout.loc[missing_counties, 'sc_point_gid'].astype(str).values))
        raise IndexError(f'Missing FIPS for {missing_counties.sum()} sites')
    else:
        dfout = dfout.loc[~missing_counties].copy()
    ## geohydro has some weird off-grid sc_point_gid sites,
    ## which we drop because they'll cause issues with interconnection cost
    if tech == 'geohydro':
        dfout = dfout.dropna(subset='FIPS')
    ## Get state
    state_fips_codes = pd.read_csv(
        os.path.join(reeds.io.reeds_path, 'inputs', 'shapefiles', 'state_fips_codes.csv'),
        index_col='state_fips',
        dtype={'state_fips':str}
    )
    fips2state = state_fips_codes.state
    st2state = state_fips_codes.set_index('state_code').state
    ## State code is first two digits of full FIPS code
    dfout['STATE'] = dfout.FIPS.map(lambda x: fips2state.get(x[:2],x))
    if offshore and offshore_meshed:
        ## Map the meshed-only sites to states using ReEDS hierarchy
        ba2st = pd.read_csv(
            os.path.join(reeds.io.reeds_path, 'inputs', 'zones', 'hierarchy_offshore.csv'),
            index_col='ba',
        ).st
        ba2state = ba2st.map(st2state)
        dfout['STATE'] = dfout.STATE.map(lambda x: ba2state.get(x,x))

    ## Check if any states are missing
    missing_states = dfout['STATE'].isnull()
    if missing_states.sum():
        print(dfout.loc[missing_states])
        err = f"Missing states for {missing_states.sum()} sites"
        raise ValueError(err)
    assert dfout.STATE.isin(fips2state.values).all(), 'Mismatched states'

    return dfout


def add_land_fom(
    sc : pd.DataFrame,
    tech: str,
    profile_id_col: str,
    reeds_path: str,
    crf_year: int =2050,
    fmv_column: str ='fair_market_private_lands_value',
) -> pd.DataFrame:
    """adds capital cost to supply curve that serves as a proxy for land lease costs

    Parameters
    ----------
    sc
        pandas dataframe of supply curve
    tech
        technology being processed
    reeds_path
        path to ReEDS directory
    crf_year, optional
        year to select for crf, by default 2050

    Returns
    -------
        pandas dataframe with updated supply curve with columns that have land costs
    """

    print("Adding land cost adder based on fair market value")

    # no land cap adder for offshore wind, egs or geohydro at the moment
    if tech == "wind-ofs" or tech == "egs" or tech == "geohydro":
        sc['land_cap_adder_per_mw'] = 0
        return sc

    # lease component of FO&M from ATB 2023 ($/kW-yr)
    # note that upv is on a per kW-DC basis; we convert to AC later on to keep all costs in AC terms.
    LEASE_FOM = {'upv': 2.1, 'wind-ons': 4.2}

    ## calculate capital reovery factor (crf) using baseline ReEDS financial assumptions
    # note: a better approach would be to pass on as a fixed operating cost and then use the
    # ReEDS internal CRF.

    # first get default financial assumptions
    sys_financials = pd.read_csv(os.path.join(reeds_path, "inputs", "financials", "financials_sys_ATB2023.csv"))
    inflation_df = pd.read_csv(os.path.join(reeds_path, "inputs", "financials",'inflation_default.csv'))
    sys_financials = sys_financials.merge(inflation_df, on='t', how='left')
    sys_financials['d_nom'] = (
        (1 - sys_financials['debt_fraction']) * (sys_financials['rroe_nom'] - 1)
        + (sys_financials['debt_fraction']
           * (sys_financials['interest_rate_nom'] - 1)
           * (1 - sys_financials['tax_rate']))
        + 1
    )
    sys_financials['d_real'] = sys_financials['d_nom'] / sys_financials['inflation_rate']

    # next calculate the CRF
    def calc_crf(discount_rate, financial_lifetime):
      crf = (
        (discount_rate - 1)
            / (1 - (1 / discount_rate**financial_lifetime))
        )
      return crf
    sys_financials['crf'] = calc_crf(sys_financials['d_real'], 30)

    # select a year for CRF
    crf = sys_financials.loc[sys_financials.t == crf_year].crf.squeeze()

    ## fair market values

    # get median land cost
    fmv_med = sc[fmv_column].median()

    # calculate land cost adder ($/MW). this is computed by taking the difference in normalized land cost,
    # multiplying by the typical land cost FO&M related, and then using the CRF to convert to capital cost
    # PV land FOM cost is originally in units of $/kW-DC, so convert to $/kw-AC by multiplying by the ILR here.
    sc['land_cap_adder_per_mw'] = (
        (sc[fmv_column] - fmv_med)
        / fmv_med
        * (LEASE_FOM[tech] * 1e3 / crf )
        * sc['ilr']
    )

    # check number of rows is the same
    assert sc.shape[0] == sc.shape[0], 'Updated data does not have the same number of rows as incoming data'

    print("Added 'land_cap_adder_per_mw' column")

    return sc


def adjust_rev_cols(tech, df, hourlize_path):
    """ identifies any missing columns that can be filled in. The run_hourlize script calls this function earlier to
    check for required columns before submitting a job, but calling again here to fill in missing values where possible.

    Parameters
    ----------
    tech
        technology being processed
    df
        pandas dataframe of supply curve

    Returns
    -------
        pandas dataframe with updated supply curve with columns that have land costs

    Raises
    ------
    Exception
        fails if there is a required column missing but no method defined to replace it
    """
    opt_cols_tech = ["multiplier_cc_eos", "multiplier_cc_regional"]

    from run_hourlize import check_cols
    __, missing_cols = check_cols(df, hourlize_path, [], opt_cols_tech)

    # these are instances of columns to rename to help manage differences
    # in column names across rev versions or technologies
    RENAME_COLS = {}

    df_new = df.copy()
    for col in missing_cols:
        # if missing either of these set all values to 1
        if col in ['multiplier_cc_eos', 'multiplier_cc_regional']:
            df_new[col] = 1
            print(f"Missing {col}--will set to 1 by default")
        # if missing one of the 'rename' columns then just need to rename
        elif col in RENAME_COLS:
            df_new.rename(columns={RENAME_COLS[col]:col}, inplace=True)
            print(f"Renamed {col} to {RENAME_COLS[col]}")
        else:
            raise Exception(f"There is no data for '{col}' and no method supplied for filling it.")

    return df_new


def add_ilr(tech, df, reeds_path, casename):
    # For UPV compute the inverter loading ratio (assume 1 for other techs)
    if tech == "upv":
        df['ilr'] = df['capacity_dc_mw'] / df['capacity_ac_mw']

        # check that value is unique to 2 decimal points
        ilr_unique = df['ilr'].round(2).unique()
        if len(ilr_unique) > 1:
            print(f"WARNING: Multiple ILRs detected for UPV: {ilr_unique}."
                  "Hourlize will run, but check whether ReEDS ILR assumptions to need to be updated.")
        # otherwise check that ILR matches ReEDS value
        else:
            scalars = reeds.io.get_scalars()
            ilr_reeds = scalars["ilr_utility"]
            ilr_rev = ilr_unique[0]

            if not math.isclose(ilr_rev, ilr_reeds, abs_tol=0.01):
                print(f"WARNING: the upv inverter-loading ratio for this reV supply curve data is {ilr_rev} "
                      f"but ReEDS currently assumes an ILR of {ilr_reeds}. It is recommended to update "
                      "the ReEDS assumption; see details in the 'UPDATE_ILR_WARNING.txt' file in the repo."
                      )

                ilr_update_file = os.path.join(reeds_path, 'inputs', "UPDATE_ILR_WARNING.txt")
                with open(ilr_update_file, "a") as file:
                    file.write(f"The upv inverter-loading ratio for {casename} from reV is {ilr_rev}\n"
                               f"but ReEDS currently assumes {ilr_reeds}. Please update the value\n"
                               "of 'ilr_utility' in the scalars.csv file. Delete this file after updating.\n\n"
                               )
            else:
                print("Confirmed reV and ReEDS ILR assumptions match.")
    else:
        df['ilr'] = 1

    return df


def get_supply_curve_and_preprocess(tech, original_sc_file, reeds_path, hourlize_path, outpath,
                                    reg_map_file, min_cap, capacity_col,
                                    existing_sites, state_abbrev, start_year, casename,
                                    filter_cols={}, profile_id_col="sc_point_gid",
                                    offshore_meshed=False):
    """processes reV supply curve file; output is a dataframe with a row for each supply curve point

    Parameters
    ----------
    tech
        technology to be processed
    original_sc_file
        path to original supply curve file
    reeds_path
        path to ReEDS directory
    hourlize_path
        path to hourlize directory
    reg_map_file
        path to file with region mapping
    min_cap
        capacity threshold for filtering out sites
    capacity_col
        column in supply curve file to use for 'capacity'
    existing_sites
        path to existing sites file
    state_abbrev
        path to state abbreviation file
    start_year
        start year to use for existing sites
    filter_cols, optional
        dictionary identifying columns to filter as well as filtering condition, by default {}
    profile_id_col, optional
        id for columns that links profiles with supply curve , by default "sc_point_gid"

    Returns
    -------
        pandas dataframe with updated supply curve
    """
    #Retrieve and filter the supply curve. Also, apply minimum capacity thresholds and apply test mode if necessary.
    print('Reading supply curve inputs and filtering...')
    startTime = datetime.datetime.now()
    dfin = pd.read_csv(original_sc_file, low_memory=False)
    df = dfin.copy()

    # add ILR information
    df = add_ilr(tech, df, reeds_path, casename)

    # add county fips information; will replace existing county columns
    # in rev supply curve with version used in ReEDS
    df = match_to_counties(
        sc=df,
        profile_id_col=profile_id_col,
        outpath=outpath,
        tech=tech,
        offshore_meshed=offshore_meshed,
    )

    # add land cost using fair market value information from reV
    df = add_land_fom(df, tech, profile_id_col, reeds_path)

    # handle any missing columns
    df = adjust_rev_cols(tech, df, hourlize_path)

    # Add 'capacity' column to match specified capacity_col
    if 'capacity' not in df.columns:
        df['capacity'] = df[capacity_col]

    for k in filter_cols.keys():
        #Apply any filtering of the supply curve, e.g. to select onshore or offshore wind.
        if filter_cols[k][0] == '=':
            df = df[df[k] == filter_cols[k][1]].copy()
        elif filter_cols[k][0] == '>':
            df = df[df[k] > filter_cols[k][1]].copy()
        elif filter_cols[k][0] == '<':
            df = df[df[k] < filter_cols[k][1]].copy()

    ## Map county to zone
    print(f"Mapping county to zone from {reg_map_file}")
    df['county'] = 'p' + df.FIPS.astype(str).map('{:>05}'.format)
    # map the regions from county to zone using the mapping file supplied
    county2zone = pd.read_csv(reg_map_file, dtype={'FIPS':str}, index_col='FIPS').r
    ## Offshore zones have ba in FIPS column, so fall back to FIPS value if not in county2zone
    df['ba'] = df.FIPS.map(lambda x: county2zone.get(x,x))

    ## process existing sites
    if existing_sites is not None:
        print('Assigning existing sites...')
        #Read in existing sites and filter
        df_exist = pd.read_csv(existing_sites, low_memory=False)
        ## Assign BA based on county
        df_exist['reeds_ba'] = df_exist.FIPS.str.strip('p').map(county2zone)
        assert df_exist.reeds_ba.isnull().sum() == 0, f'Unmatched counties in {existing_sites}'
        ## If meshed, assign existing offshore wind to offshore zones
        if (tech == 'wind-ofs') and (offshore_meshed):
            df_exist = reeds.spatial.assign_to_offshore_zones(df_exist)

        df_exist = df_exist[
            ['tech','TSTATE','reeds_ba','Unique ID',
            'T_LONG','T_LAT','summer_power_capacity_MW','StartYear','RetireYear']
        ].rename(columns={
            'TSTATE':'STATE', 'T_LAT':'LAT', 'T_LONG':'LONG', 'summer_power_capacity_MW':'cap', 'reeds_ba':'pca',
            'Unique ID':'UID', 'StartYear':'Commercial.Online.Year',
        }).copy()
        df_exist = df_exist[(df_exist['tech'].str.lower().str.contains(tech.lower())) & (df_exist['RetireYear'] > start_year)].reset_index(drop=True)
        if (df_exist['LONG'] > 0).any():
            err = (
                f'Some longitudes in {existing_sites} are positive; '
                'for the contiguous US they should all be negative'
            )
            raise ValueError(err)
        df_exist.sort_values('cap', ascending=False, inplace=True)

        #Map the state codes of df_exist to the state names in df
        df_cp = df.copy()
        df_st = pd.read_csv(state_abbrev, low_memory=False)
        dict_st = dict(zip(df_st['ST'], df_st['State']))
        df_exist['STATE'] = df_exist['STATE'].map(dict_st)
        df_cp = df_cp[[profile_id_col, 'STATE','latitude','longitude','capacity']].copy()
        df_cp['existing_capacity'] = 0.0
        df_cp['existing_uid'] = 0
        df_cp['online_year'] = 0
        df_cp['retire_year'] = 0
        df_cp_out = pd.DataFrame()

        #Restrict matching to within the same state
        print("{:<18} {:>} MW".format("Total", round(df_exist.cap.sum())))
        print("{:<18} {:>}".format("-------", "-------"))
        for st in df_exist['STATE'].unique():
            df_exist_st = df_exist[df_exist['STATE'] == st].copy()
            print("{:<18} {:>} MW".format(st, round(df_exist_st.cap.sum())))
            df_cp_st = df_cp[df_cp['STATE'] == st].copy()
            for i_exist, r_exist in df_exist_st.iterrows():
                #Current way to deal with lats and longs that don't exist
                if r_exist['LONG'] == 0:
                    continue
                #Assume each lat is ~69 miles and each long is ~53 miles
                # TODO FIXME: If this calculation matters, use meters from equal-area projection
                # (fixed lat/lon-to-miles is inaccurate over areas as large as the USA)
                df_cp_st['mi_sq'] =  ((df_cp_st['latitude'] - r_exist['LAT'])*69)**2 + ((df_cp_st['longitude'] - r_exist['LONG'])*53)**2
                #Sort by closest
                df_cp_st.sort_values(['mi_sq'], inplace=True)
                #Step through the available sites and fill up the closest ones until we are done with this existing capacity
                exist_cap_remain = r_exist['cap']
                for i_avail, r_avail in df_cp_st.iterrows():
                    avail_cap = df_cp_st.at[i_avail, 'capacity']
                    # TODO: handle missing UIDs
                    try:
                        df_cp_st.at[i_avail, 'existing_uid'] = r_exist['UID']
                    except Exception:
                        df_cp_st.at[i_avail, 'existing_uid'] = 0
                    df_cp_st.at[i_avail, 'online_year'] = r_exist['Commercial.Online.Year']
                    df_cp_st.at[i_avail, 'retire_year'] = r_exist['RetireYear']
                    if exist_cap_remain <= avail_cap:
                        df_cp_st.at[i_avail, 'existing_capacity'] = exist_cap_remain
                        exist_cap_remain = 0
                        break
                    else:
                        df_cp_st.at[i_avail, 'existing_capacity'] = avail_cap
                        exist_cap_remain = exist_cap_remain - avail_cap
                if exist_cap_remain > 0:
                    print('WARNING: Existing site shortfall: ' + str(exist_cap_remain))
                #Build output and take the available sites with existing capacity out of consideration for the next exisiting site
                df_cp_out_add = df_cp_st[df_cp_st['existing_capacity'] > 0].copy()
                df_cp_out = pd.concat([df_cp_out, df_cp_out_add], sort=False).reset_index(drop=True)
                df_cp_st = df_cp_st[df_cp_st['existing_capacity'] == 0].copy()
        df_cp_out['exist_mi_diff'] = df_cp_out['mi_sq']**0.5
        df_cp_out = df_cp_out[[profile_id_col, 'existing_capacity', 'existing_uid', 'online_year', 'retire_year', 'exist_mi_diff']].copy()
        df = pd.merge(left=df, right=df_cp_out, how='left', on=profile_id_col, sort=False)
        df[['existing_capacity','existing_uid','online_year','retire_year','exist_mi_diff']] = df[['existing_capacity','existing_uid','online_year','retire_year','exist_mi_diff']].fillna(0)
        df[['existing_uid','online_year','retire_year']] = df[['existing_uid','online_year','retire_year']].astype(int)
    else:
        df['existing_capacity'] = 0.0

    if min_cap > 0:
        #Remove sites with less than minimum capacity threshold, but keep sites that have existing capacity
        df = df[(df['capacity'] >= min_cap) | (df['existing_capacity'] > 0)].copy()

    print('Done reading supply curve inputs and filtering: '+ str(datetime.datetime.now() - startTime))
    return df


def add_classes(df_sc, class_path, class_bin, class_bin_col, class_bin_method, class_bin_num):
    """
    add wind and solar class information to supply curve file. typical approach is to define
    national classes based on capacity factor but can vary depending on the settings in the tech config
    files (see hourlize README for more details)
    """
    #Add 'class' column to supply curve, based on specified class definitions in class_path.
    print('Adding classes...')
    startTime = datetime.datetime.now()
    #Create class column.
    if class_path is None:
        df_sc['class'] = '1'
    else:
        df_sc['class'] = 'NA' #Initialize to NA to make sure we have full coverage of classes here.
        df_class = pd.read_csv(class_path, index_col='class')
        #Now loop through classes (rows in df_class). Classes may have multiple defining criteria (columns in df_class),
        #so we loop through columns to build the selection criteria for each class, building up a 'mask' of criteria for each class.
        #Numeric ranges in class definitions (e.g. min and max wind speeds) are indicated by the pipe symbol, e.g. '5|6'
        #for 'mean_res' would mean 'mean_res' must fall between 5 and 6 for that class.
        for cname, row in df_class.iterrows():
            #Start with mask=True, and then build up the full conditional based on each column of df_class.
            mask = True
            for col, val in row.items():
                if '|' in val:
                    #Pipe is a special character that indicates a numeric range.
                    rng = val.split('|')
                    rng = [float(n) for n in rng]
                    mask = mask & (df_sc[col] >= min(rng))
                    mask = mask & (df_sc[col] < max(rng))
                else:
                    #No pipe symbol means we do a simple match.
                    mask = mask & (df_sc[col] == val)
            #Finally, apply the mask that has been built for this class.
            df_sc.loc[mask, 'class'] = cname
    # Add dynamic, region-specific class bins based on class_bin_method
    if class_bin:
        #In this case, class names in class_path must be numbered, starting at 1
        df_sc = df_sc.rename(columns={'class':'class_orig'})
        df_sc['class_orig'] = df_sc['class_orig'].astype(int)
        df_sc = (
            df_sc
            .groupby(['class_orig'], sort=False)
            .apply(
                reeds.inputs.get_bin,
                bin_col=class_bin_col,
                bin_out_col='class_bin',
                weight_col='capacity',
                bin_num=class_bin_num,
                bin_method=class_bin_method,
            )
            .reset_index(drop=True)
        )
        df_sc['class'] = (df_sc['class_orig'] - 1) * class_bin_num + df_sc['class_bin']
    print('Done adding classes: '+ str(datetime.datetime.now() - startTime))
    return df_sc


def add_cost(df_sc, tech):
    """
    Calculate capital cost adders.
    Note that all transmission costs and adders are always defined in terms of $/MW-AC (not $/MW-DC),
    even when running with upv_type=DC. Conversion of this costs to $/MW-DC for UPV occurs downstream in
    ReEDS (see "convert UPV costs from $/MW-AC to $/MW-DC" comment in b_inputs.gms)
    """
    assert tech in ['upv', 'wind-ons', 'wind-ofs', 'egs', 'geohydro']
    if tech in ['upv', 'wind-ons']:
        # first term computes the combined eos and regional multiplier by subtracting the
        # 'base' costs (without the multipliers) from the 'full' site costs (with the
        # multipliers); second term adds in the land capital cost adder to the eos/regional adders.
        costlabel = 'occ' if 'cost_site_occ_usd_per_ac_mw' in df_sc else 'cc'
        df_sc['capital_adder_per_mw'] = (
            df_sc[f'cost_site_{costlabel}_usd_per_ac_mw']
            - df_sc[f'cost_base_{costlabel}_usd_per_ac_mw']
            + df_sc['land_cap_adder_per_mw']
        )
    elif tech == 'wind-ofs':
        # Since the site capex (costcol) has site-specific multipliers
        # baked in, we divide the capex by the multipliers to obtain the base capex.
        # `cost_occ` includes array cable costs, so we don't need to add them (Gabe 20250813).
        costcol = (
            'cost_occ_2035_usd_per_mw' if 'cost_occ_2035_usd_per_mw' in df_sc
            else 'cost_capex_2035_usd_per_mw'
        )
        df_sc['capital_adder_per_mw'] = (
            df_sc[costcol]
            * df_sc['multiplier_cc_eos']
            * df_sc['multiplier_cc_regional']
            - (df_sc[costcol] / df_sc['multiplier_cc_site_specific'])
        )
    else:
        df_sc['capital_adder_per_mw'] = 0

    print('Done adding capital cost adders')
    return df_sc


#%% ===========================================================================
### --- PROFILES ---
### ===========================================================================

def read_cf_file(
    year,
    rev_path=None,
    profile_dir=None,
    rev_case=None,
    profile_file_format=None,
    profile_dset=None,
    profile_id_col=None,
    multiyear_file=False
):
    if multiyear_file:
        h5path = os.path.join(
            rev_path, profile_dir,
            f'{rev_case}_bespoke.h5')
        with h5py.File(h5path, 'r') as h5:
            dfall = pd.DataFrame(h5[f'cf_profile-{year}'][:])
            # adjust profiles by scaling factor
            rev_scale_factor = h5[f'cf_profile-{year}'].attrs['scale_factor']
            dfall = dfall/rev_scale_factor
            # read meta and time index
            df_meta = pd.DataFrame(h5['meta'][:])
            df_index = pd.Series(h5[f'time_index-{year}'][:])
    else:
        h5path = os.path.join(
            rev_path, profile_dir, f'{profile_file_format}_{year}.h5')
        with h5py.File(h5path, 'r') as h5:
            dfall = pd.DataFrame(h5[profile_dset][:])
            # read meta and time index
            df_meta = pd.DataFrame(h5['meta'][:])
            df_index = pd.Series(h5['time_index'][:])

    ## Check that meta and profile are the same dimensions
    assert dfall.shape[1] == df_meta.shape[0], (
        f"Dimensions of profile ({dfall.shape[1]}) do not match "
        f"meta file dimensions ({df_meta.shape[0]}) in "
        f"{profile_file_format}_{year}.h5"
    )
    ## Change hourly profile column names from simple index to
    ## associated id specified by profile_id_col (usually sc_point_gid)
    dfall.columns = dfall.columns.map(df_meta[profile_id_col])
    ## Add time index
    dfall = dfall.set_index(df_index)
    
    return dfall

def process_cf_profiles(
    tech,
    df_sc,
    rev_path,
    rev_case,
    hourly_out_years,
    profile_dset,
    profile_dir,
    profile_id_col,
    profile_file_format,
    single_profile,
    output_dirpath,
    output_filetype='.h5',
    compression_opts=4,
    dtype=np.uint16,
    scale_factor=1e4
):
    """
    """
    print('Getting multiyear profiles...')
    startTime = datetime.datetime.now()
    ## Load hourly profile for each year
    for year in hourly_out_years:
        print('Writing cf profiles for ' + str(year))
        df_prof_out = read_cf_file(
            year=year,
            rev_path=rev_path,
            profile_dir=profile_dir,
            rev_case=rev_case,
            profile_file_format=profile_file_format,
            profile_dset=profile_dset,
            profile_id_col=profile_id_col,
            multiyear_file=single_profile
        )

        ### Downselect to sites with supply curve data
        sc_site_ids = (
            df_sc.loc[df_sc[profile_id_col].isin(df_prof_out.columns)]
            [profile_id_col]
        )
        df_prof_out = df_prof_out[sc_site_ids].sort_index(axis=1)

        ### Apply AC-to-DC conversion if applicable
        if (upv_type_out is not None) and (upv_type_out.lower() == "dc"):
            df_prof_out = convert_upv_ac_profiles_to_dc(df_prof_out, df_sc)

        ### Apply scaling factor
        df_prof_out = df_prof_out * scale_factor

        ### Convert dtype
        if 'int' in dtype and scale_factor < 100:
            raise ValueError(
                "scale_factor must be greater than 100 when converting "
                "CF values to ints. Update scale_factor or dtype."
            )
        df_prof_out = df_prof_out.astype(dtype)
        # Make sure dtype is numeric
        if not pd.api.types.is_numeric_dtype(df_prof_out.iloc[:, 0]):
            raise ValueError(
                f"{dtype} is not a valid (numeric) dtype entry."
                "Update config_[case].json."
            )

        ### Sort column names (sc point GIDs)
        df_prof_out = df_prof_out.sort_index(axis=1)

        ### Write outputs
        if '.csv' in output_filetype:
            df_prof_out.to_csv(os.path.join(output_dirpath, 'results', tech + '.csv.gz'))
        else:
            filepath = os.path.join(output_dirpath, 'results', f'{tech}.h5')
            with h5py.File(filepath, 'a') as f:
                # Columns (supply curve point GIDs)
                if year == hourly_out_years[0]:
                    f.create_dataset('columns', data=df_prof_out.columns)
                # Time index
                f.create_dataset(
                    f'time_index_{year}',
                    data=df_prof_out.index.values.astype('|S')
                )
                # Capacity factor values
                cf_dataset = f.create_dataset(
                    f'cf_profile_{year}',
                    data=df_prof_out.values,
                    compression='gzip',
                    compression_opts=compression_opts
                )
                cf_dataset.attrs['scale'] = 1 / scale_factor

        print('Done with ' + str(year))

    print('Done writing multiyear profiles: '+ str(datetime.datetime.now() - startTime))
    return df_prof_out


def convert_upv_ac_profiles_to_dc(df_prof, df_sc):
    ## reV only produces AC profiles so we always read in those. If we're running hourlize to produce
    ## DC UPV outputs then we convert to 'DC' profiles here. Note that these do not actually represent
    ## pre-inverter profiles, but rather are just AC output / DC capacity.
    ilr_by_site = df_sc.set_index(cf.profile_id_col).ilr.copy()
    df_prof_out = df_prof / ilr_by_site
    return df_prof_out


#%% ===========================================================================
### --- SAVE OUTPUTS ---
### ===========================================================================

def save_sc_outputs(
    df_sc,
    existing_sites,
    start_year,
    outpath,
    tech,
    subtract_exog,
    profile_id_col,
    decimals,
):
    """save supply curve output files"""
    #Save resource supply curve outputs
    print('Saving supply curve outputs...')
    startTime = datetime.datetime.now()
    #Create local copy of df_sc so that we don't modify the df_sc passed by reference
    df_sc = df_sc.copy()
    # save copy of pre-processed reV supply curve
    df_sc.to_csv(os.path.join(outpath, 'results', tech + '_supply_curve_raw.csv'), index=False)
    #Round now to prevent infeasibility in model because existing (pre-2010 + prescribed) capacity is slightly higher than supply curve capacity
    df_sc[['capacity','existing_capacity']] = df_sc[['capacity','existing_capacity']].round(decimals)
    if existing_sites:
        # bincol = ['sc_point_gid'] if exog_bin else []
        df_exist = df_sc[df_sc['existing_capacity'] > 0].copy()
        #Exogenous (pre-start-year) capacity output
        df_exog = df_exist[df_exist['online_year'] < start_year].copy()
        # Aggregate existing capacity to (i,rs,t)
        if not df_exog.empty:
            df_exog = df_exog[[profile_id_col, 'class','retire_year','existing_capacity']].copy()
            max_exog_ret_year = df_exog['retire_year'].max()
            ret_year_ls = list(range(start_year,max_exog_ret_year + 1))
            df_exog = df_exog.pivot_table(index=[profile_id_col,'class'], columns='retire_year', values='existing_capacity')
            # Make a column for every year until the largest retirement year
            df_exog = df_exog.reindex(columns=ret_year_ls).bfill(axis='columns')
            df_exog = pd.melt(
                df_exog.reset_index(), id_vars= [profile_id_col,'class'],
                value_vars=ret_year_ls, var_name='year', value_name='capacity')
            df_exog = df_exog[df_exog['capacity'].notnull()].copy()
            if(tech == 'egs' or tech == 'geohydro'):
                df_exog['tech'] = tech + '_allkm_' + df_exog['class'].astype(str)
            else:
                df_exog['tech'] = tech + '_' + df_exog['class'].astype(str)
            df_exog = df_exog[[profile_id_col,'tech','year','capacity']].copy()
            df_exog = df_exog.groupby(['tech','year',profile_id_col], sort=False, as_index=False).sum()
            df_exog = df_exog.sort_values(['year',profile_id_col]).round(decimals)
            df_exog.to_csv(os.path.join(outpath, 'results', tech + '_exog_cap.csv'), index=False)
        #Prescribed capacity output
        if tech in ['wind-ons', 'wind-ofs']:
            df_pre = df_exist[df_exist['online_year'] >= start_year].copy()
            if not df_pre.empty:
                df_pre = df_pre[[profile_id_col,'online_year','existing_capacity']].copy()
                df_pre = df_pre.rename(columns={'online_year':'year', 'existing_capacity':'capacity'})
                df_pre = df_pre.groupby([profile_id_col,'year'], sort=False, as_index =False).sum()
                df_pre['capacity'] =  df_pre['capacity'].round(decimals)
                df_pre = df_pre.sort_values(['year',profile_id_col])
                df_pre.to_csv(os.path.join(outpath, 'results', tech + '_prescribed_builds.csv'), index=False)
        #Reduce supply curve based on exogenous (pre-start-year) capacity
        if subtract_exog:
            criteria = (df_sc['online_year'] > 0) & (df_sc['online_year'] < start_year)
            df_sc.loc[criteria, 'capacity'] = (
                df_sc.loc[criteria, 'capacity'] - df_sc.loc[criteria, 'existing_capacity'])

    cfcol = 'capacity_factor_ac' if 'capacity_factor_ac' in df_sc else 'mean_cf'
    df_sc_out = (
        df_sc[[profile_id_col, 'class', 'capacity', 'capital_adder_per_mw', cfcol]]
        .sort_values(profile_id_col)
        .rename(columns={cfcol:'cf'})
        .round({'capacity':decimals, 'capital_adder_per_mw':decimals, 'cf':decimals+2})
    )
    df_sc_out.to_csv(
        os.path.join(outpath, 'results', f'supplycurve_{tech}.csv'),
        index=False,
    )
    print(f'Done saving supply curve outputs: {datetime.datetime.now() - startTime}')
    return df_sc_out


def copy_outputs(
    outpath,
    reeds_path,
    sc_path,
    casename,
    copy_to_reeds,
    copy_to_shared,
    rev_jsons,
    configpath,
    tech,
    access_case,
    offshore_meshed,
):
    #Save outputs to the shared drive and to this reeds repo.
    print('Copying outputs to shared drive and/or reeds repo')
    startTime = datetime.datetime.now()

    ## Parse filename components
    if tech != 'wind-ofs':
        techlabel = tech
    else:
        techlabel = f"{tech}_{'meshed' if offshore_meshed else 'radial'}"

    resultspath = os.path.join(outpath, 'results')
    inputspath = os.path.join(reeds_path, 'inputs')

    if copy_to_reeds:
        #Supply curve
        shutil.copy2(
            os.path.join(resultspath, f'supplycurve_{tech}.csv'),
            os.path.join(inputspath, 'supply_curve', f'supplycurve_{tech}-{access_case}.csv')
        )

        #Prescribed builds and exogenous capacity (if they exist)
        try:
            shutil.copy2(
                os.path.join(resultspath, f'{tech}_prescribed_builds.csv'),
                os.path.join(
                    inputspath, 'capacity_exogenous',
                    f'prescribed_builds_{techlabel}_{access_case}.csv',
                )
            )
        except Exception:
            print('WARNING: No prescribed builds')

        try:
            df = pd.read_csv(os.path.join(resultspath,f'{tech}_exog_cap.csv'))
            df.rename(columns={df.columns[0]: '*'+str(df.columns[0])}, inplace=True)
            df.to_csv(
                os.path.join(inputspath,'capacity_exogenous',f'exog_cap_{tech}_{access_case}.csv'),
                index=False
            )
        except Exception:
            print('WARNING: No exogenous capacity')

        ## Metadata
        # rev configs
        meta_path = os.path.join(inputspath,'supply_curve','metadata',f'{casename}')
        if os.path.exists(meta_path):
            shutil.rmtree(meta_path)
        os.makedirs(meta_path)
        for metafile in rev_jsons:
            try:
                shutil.copy(
                    os.path.join(outpath, 'inputs', 'rev_configs', os.path.basename(metafile)),
                    os.path.join(meta_path,os.path.basename(metafile)),
                )
            except FileNotFoundError as err:
                print(err)

        # hourlize config
        shutil.copy(
                configpath,
                os.path.join(meta_path,os.path.basename(configpath)),
            )

        # Copy the readme file if there is one
        for ext in ['.yaml', '.yml', '.md', '.txt', '']:
            try:
                shutil.copy2(
                    os.path.join(outpath,'inputs','readme'+ext),
                    os.path.join(meta_path,''),
                )
            except Exception:
                pass

        # Hourly profiles
        print(
            "Hourly profiles are not copied to the ReEDS repository. "
            "When finalized, these files should be uploaded to Zenodo "
            "and inputs/remote_files.csv should be updated accordingly. "
            "See preprocessing/README.md for upload instructions."
        )

    if copy_to_shared:
        shared_drive_path = os.path.join(sc_path, os.path.basename(os.path.normpath(outpath)))
        #Create output directory, creating backup if one already exists.
        if os.path.exists(shared_drive_path):
            time = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
            os.rename(shared_drive_path, shared_drive_path + '-archive-'+time)
        shutil.copytree(outpath, shared_drive_path)

    print('Done copying outputs to shared drive and/or reeds repo: '+ str(datetime.datetime.now() - startTime))


#%% ===========================================================================
### --- PROCEDURE ---
### ===========================================================================

if __name__== '__main__':
    #%% load arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', '-c', type=str, default='', help='path to config file for this run')
    parser.add_argument('--nolog', '-n', default=False, action='store_true', help='turn off logging for debugging')

    args = parser.parse_args()
    configpath = args.config
    nolog = args.nolog
    startTime = datetime.datetime.now()

    #%% load config information
    with open(configpath, "r") as f:
        config = json.load(f, object_pairs_hook=OrderedDict)
    cf = SimpleNamespace(**config)

    #%% look for upv output type (AC or DC)
    if cf.tech == "upv":
        upv_type_out = cf.upv_type_out
    else:
        upv_type_out = None

    #%% import additional modules using path to ReEDS
    site.addsitedir(cf.reeds_path)
    import reeds

    #%% setup logging
    if not nolog:
        log = reeds.log.makelog(
            scriptname=__file__,
            logpath=os.path.join(cf.outpath, f'log_{cf.casename}.txt'),
        )

    #%% Make copies of rev jsons
    rev_jsons = copy_rev_jsons(cf.outpath, cf.rev_path)

    #%% Special-case processing for geothermal
    if cf.tech in ['egs', 'geohydro']:
        if cf.geo_run_supply_curve_aggregation:
            print('Aggregating raw geothermal supply curves...')
            if cf.geo_aggregation_method == 'lowest_lcoe':
                aggregate_supply_curves_by_lowest_lcoe(
                    rev_cases_path=cf.rev_path,
                    rev_sc_file_path=cf.original_sc_file,
                )
            else:
                raise NotImplementedError(
                    f'geo_aggregation_method={cf.geo_aggregation_method} has not been implemented'
                )

    #%% Get supply curves
    df_sc = get_supply_curve_and_preprocess(
        tech=cf.tech,
        original_sc_file=cf.original_sc_file,
        reeds_path=cf.reeds_path,
        hourlize_path=cf.hourlize_path,
        outpath=cf.outpath,
        reg_map_file=cf.reg_map_file,
        min_cap=cf.min_cap,
        capacity_col=cf.capacity_col,
        existing_sites=cf.existing_sites,
        state_abbrev=cf.state_abbrev,
        start_year=cf.start_year,
        casename=cf.casename,
        filter_cols=cf.filter_cols,
        profile_id_col=cf.profile_id_col,
        offshore_meshed=cf.offshore_meshed,
    )

    #%% Add classes
    df_sc = add_classes(
        df_sc, cf.class_path, cf.class_bin, cf.class_bin_col,
        cf.class_bin_method, cf.class_bin_num)

    #%% Add cost
    df_sc = add_cost(df_sc, cf.tech)

    #%% Save the supply curve
    df_sc_out = save_sc_outputs(
        df_sc=df_sc,
        existing_sites=cf.existing_sites,
        start_year=cf.start_year,
        outpath=cf.outpath,
        tech=cf.tech,
        subtract_exog=cf.subtract_exog,
        profile_id_col=cf.profile_id_col,
        decimals=2,
    )

    #%% Save hourly profiles
    if cf.process_profiles:
        process_cf_profiles(
            tech=cf.tech,
            df_sc=df_sc,
            rev_path=cf.rev_path,
            rev_case=cf.rev_case,
            hourly_out_years=cf.hourly_out_years,
            profile_dset=cf.profile_dset,
            profile_dir=cf.profile_dir,
            profile_id_col=cf.profile_id_col,
            profile_file_format=cf.profile_file_format,
            single_profile=cf.single_profile,
            output_dirpath=cf.outpath,
            output_filetype=cf.filetype,
            compression_opts=cf.compression_opts,
            scale_factor=cf.scale_factor
        )

    #%% Copy outputs to ReEDS and/or the shared drive
    copy_outputs(
        outpath=cf.outpath,
        reeds_path=cf.reeds_path,
        sc_path=cf.sc_path,
        casename=cf.casename,
        copy_to_reeds=cf.copy_to_reeds,
        copy_to_shared=cf.copy_to_shared,
        rev_jsons=rev_jsons,
        configpath=configpath,
        tech=cf.tech,
        access_case=cf.access_case,
        offshore_meshed=cf.offshore_meshed,
    )
    print('All done! total time: '+ str(datetime.datetime.now() - startTime))
