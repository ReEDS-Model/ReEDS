import os
import sys
import re
import pandas as pd
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds


### Constants
ignore_techs = []
## Technology names that hold a subset of a family's resource classes
TECH_FAMILY = {
    'wind-ofs-fixed': 'wind-ofs',
    'wind-ofs-floating': 'wind-ofs',
}


### Functions
def expand_star(techs):
    '''
    Expand the GAMS range convention (e.g. geohydro_allkm_1*geohydro_allkm_10 becomes geohydro_allkm_1, geohydro_allkm_2,..., geohydro_allkm_10)
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
    'geohydro_allkm_5' -> ('geohydro_allkm', 5).
    Techs with no numeric class suffix (e.g. 'distpv') return (i, None).
    '''
    match = re.search(r'^(.+)_(\d+)$', i)
    if match is None:
        return i, None
    return match.group(1), int(match.group(2))


def get_collapsed_techs(case):
    '''
    Map (family, class) to the technology name in i for technologies listed with more
    than one class in i_c, e.g. ('upv', '5') -> 'upv'. The family is the name itself
    unless TECH_FAMILY says otherwise. Classes are strings.
    '''
    i_c = reeds.io.read_input(case, 'i_c').astype({'c': str})
    num_classes = i_c.groupby('i').c.nunique()
    multi = i_c.loc[i_c.i.isin(num_classes.loc[num_classes > 1].index)]
    keys = list(zip(multi.i.map(lambda i: TECH_FAMILY.get(i, i)), multi.c))
    if len(set(keys)) != len(keys):
        raise ValueError('A (family, class) pair maps to more than one technology in i_c')
    return dict(zip(keys, multi.i))


def get_tech_class_name(tech, c, collapsed):
    '''
    Return the name in the ReEDS technology set i for class c of technology
    family tech.

    Families in collapsed hold their classes under shared names, looked up by
    (family, class) ('upv', 5 -> 'upv'). Other families get the class appended
    ('geohydro_allkm', 5 -> 'geohydro_allkm_5').
    Get collapsed from get_collapsed_techs(case).

    tech and c can be scalars, or pd.Series with the same index (returns a
    pd.Series).
    '''
    names = set(collapsed.values())
    families = {family for family, _ in collapsed}

    def lookup(tech, c):
        c = str(c)
        if (tech, c) in collapsed:
            return collapsed[tech, c]
        ## Class not in i_c for a family whose name is a technology: keep the name
        if tech in names:
            return tech
        if tech in families:
            raise ValueError(f'Class {c} of {tech} is not in i_c')
        return f'{tech}_{c}'

    if isinstance(tech, pd.Series):
        c = c if isinstance(c, pd.Series) else pd.Series(c, index=tech.index)
        return pd.Series(
            [lookup(t, cc) for t, cc in zip(tech, c)], index=tech.index, name=tech.name)
    return lookup(tech, c)


def get_class_map(case):
    '''
    Map each technology to its resource class. Water-cooled techs are assigned the
    class of the technology they derive from, and technologies with no class are
    assigned class '0'. Technologies with several classes map to None.
    '''
    i_c = (
        reeds.io.read_input(case, 'i_c').astype({'c': str})
        .groupby('i').c.agg(lambda x: x.iloc[0] if len(x) == 1 else None)
    )
    ### Broadcast class to water-cooled variants
    if int(reeds.io.get_switches(case).GSw_WaterMain) == 1:
        ctt_i_ii = (
            pd.concat([
                reeds.io.read_input(case, name).rename(columns={'*i': 'i'})[['i', 'ii']]
                for name in [
                    'i_coolingtech_watersource_link',
                    'i_coolingtech_watersource_upgrades_link',
                ]
            ])
            .drop_duplicates('i')
            .set_index('i').ii
        )
        derived = ctt_i_ii.map(i_c).dropna()
        i_c = pd.concat([i_c, derived.loc[~derived.index.isin(i_c.index)]])

    return i_c.reindex(reeds.io.read_input(case, 'i').squeeze(1), fill_value='0')


def expand_GAMS_tech_groups(df, col='i'):
    '''
    GAMS has a convention for expanding rows (e.g. geohydro_allkm_1*geohydro_allkm_10 is expanded to geohydro_allkm_1, geohydro_allkm_2,..., geohydro_allkm_10)
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
