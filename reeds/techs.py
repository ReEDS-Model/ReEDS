import os
import sys
import re
import pandas as pd
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds


### Constants
ignore_techs = []


### Functions
def expand_star(techs):
    '''
    Expand the GAMS range convention (e.g. upv_1*upv_10 becomes upv_1, upv_2,..., upv_10)
    in a list of technology names. We assume the numbers we would like to enumerate occur
    at the end. Entries without a '*' are passed through unchanged.
    '''
    expanded = []
    for tech in techs:
        if '*' not in tech:
            expanded.append(tech)
            continue
        start, end = tech.split('*')
        num_start = int(re.search(r'(\d+)\s*$', start).group(1))
        num_end = int(re.search(r'(\d+)$', end).group(1))
        root = re.sub(r'\d+\s*$', '', start)
        expanded += [f'{root}{num}' for num in range(num_start, num_end + 1)]

    return expanded


def split_class(i):
    '''
    Split a resource-class-bearing tech name into (base, class), e.g.,
    'upv_5' -> ('upv', 5), 'csp2_5' -> ('csp2', 5).
    Techs with no numeric class suffix (e.g. 'distpv') return (i, None).
    '''
    match = re.search(r'^(.+)_(\d+)$', i)
    if match is None:
        return i, None
    return match.group(1), int(match.group(2))


def expand_GAMS_tech_groups(df, col='i'):
    '''
    GAMS has a convention for expanding rows (e.g. upv_1*upv_10 is expanded to upv_1, upv_2,..., upv_10)
    This function expands a df with the same convention, for the instances where a file is ingested
    by both python and GAMS. We assume the numbers we would like to enumerate occur at the end.
    '''
    tech_groups = [group for group in df[col] if '*' in group]

    for tech_group in tech_groups:
        techs = expand_star([tech_group])
        # Extract the tech group from the main df
        df_subset = df[df[col] == tech_group]
        # Drop the tech group from the main df
        df = df[df[col] != tech_group]

        df_list = []

        for tech in techs:
            df_expanded_single = df_subset.copy()
            df_expanded_single[col] = tech
            df_list = df_list + [df_expanded_single]

        df = pd.concat([df] + df_list, ignore_index=True)

    return df


def import_tech_groups(file_path):
    '''
    Creates a dictionary of different tech groups from a csv.
    Used during the import process -- if a particular assumption applies to a family of technologies,
        this dictionary creates the mapping.

    First column of the input csv is the dictionary key for that tech family.
    There cannot be duplicate keys, and they must differ from a tech name.
    '''
    tech_subset_table = pd.read_csv(file_path)
    tech_subset_table = tech_subset_table.rename(columns={'Unnamed: 0': 'i'})

    tech_subset_table = expand_GAMS_tech_groups(tech_subset_table)

    tech_subset_table = tech_subset_table.set_index('i')
    tech_groups = {}
    for col in list(tech_subset_table.columns):
        tech_groups[col] = list(tech_subset_table[col][tech_subset_table[col] == 'YES'].index)

    return tech_groups


def get_tech_subset_table(case):
    """Output techs are in lower case"""
    inputs_case = case if 'inputs_case' in case else os.path.join(case, 'inputs_case')
    tech_subset_table = (
        pd.read_csv(os.path.join(inputs_case, 'tech-subset-table.csv'), index_col=0)
        .rename_axis(index='i', columns='tech_group')
        .stack().dropna()
        .reorder_levels(['tech_group','i']).sort_index()
        .reset_index('i').i
        .str.lower()
    )
    return tech_subset_table


def get_techlist_after_bans(case):
    sw = reeds.io.get_switches(case)
    tech_subset_table = get_tech_subset_table(case)
    techlist = sorted(tech_subset_table.unique())
    if not int(sw.GSw_BECCS):
        techlist = [i for i in techlist if 'beccs' not in i]
    if not int(sw.GSw_Biopower):
        techlist = [i for i in techlist if i != 'biopower']
    if not int(sw.GSw_DAC):
        techlist = [i for i in techlist if i not in tech_subset_table.loc['DAC'].values]
    if not int(sw.GSw_H2_SMR):
        techlist = [i for i in techlist if i not in tech_subset_table.loc['SMR'].values]
    if not int(sw.GSw_Storage):
        techlist = [i for i in techlist if i not in tech_subset_table.loc['STORAGE_STANDALONE'].values]
    if not int(sw.GSw_CCSFLEX_BYP):
        techlist = [i for i in techlist if i not in tech_subset_table.loc['CCSFLEX_BYP'].values]
    if not int(sw.GSw_CCSFLEX_STO):
        techlist = [i for i in techlist if i not in tech_subset_table.loc['CCSFLEX_STO'].values]
    if not int(sw.GSw_CCSFLEX_DAC):
        techlist = [i for i in techlist if i not in tech_subset_table.loc['CCSFLEX_DAC'].values]

    return techlist


def get_storage_hybrid_gentechs(inputs_case):
    """Return a Series that maps each storage-hybrid wrapper to its gen tech"""
    path = os.path.join(inputs_case, 'storage_hybrid_gentechs.csv')
    if not os.path.exists(path):
        return pd.Series(dtype=str, name='gen_tech')
    return pd.read_csv(path, index_col='*storage-hybrid_type')['gen_tech']


def add_storage_hybrid_gentech_members(techs, inputs_case):
    """
    Return techs (lower-case tech names) plus each storage-hybrid wrapper whose gen tech
    is in techs, so tech-group lists keyed on the gen tech also cover its wrappers.
    """
    techs = list(techs)
    techs += [
        wrapper.lower()
        for wrapper, gen_tech in get_storage_hybrid_gentechs(inputs_case).items()
        if gen_tech.lower() in techs
    ]
    return techs


def add_storage_hybrid_vre_resources(resources, inputs_case):
    """
    Add a row to resources (from inputs_case/resources.csv) for each storage-hybrid
    wrapper whose gen tech has a VRE profile, in each region where the gen tech has one.
    The wrapper's resource is '{wrapper}|{r}', and it has the gen tech's profile.
    Returns (resources, wrapper_to_gentech).
    """
    gentechs = get_storage_hybrid_gentechs(inputs_case)
    rows = resources.merge(
        gentechs.rename('i').rename_axis('wrapper').reset_index(), on='i')
    rows['i'] = rows['wrapper']
    rows['resource'] = rows['wrapper'] + '|' + rows['r']
    resources = pd.concat(
        [resources, rows[resources.columns]], ignore_index=True)
    return resources, gentechs.loc[rows['wrapper'].unique()]
