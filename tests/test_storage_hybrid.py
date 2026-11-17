"""
Unit tests for storage-hybrid wrapper input processing (no GAMS needed).

Run with `python -m pytest tests/test_storage_hybrid.py`.
"""
import os
from pathlib import Path

import h5py
import pandas as pd
import pytest

import reeds
from reeds.input_processing import copy_files


TECHS = [
    'battery_li', 'tes_ms', 'flex_geo', 'nuclear', 'gas-cc', 'h2-ct',
    'upv_1', 'upv_2', 'upv_3', 'wind-ons_1', 'wind-ons_2',
]


@pytest.fixture
def inputs_case(tmp_path):
    """A tiny inputs_case with the i set in inputs.h5"""
    path = tmp_path / 'case' / 'inputs_case'
    path.mkdir(parents=True)
    reeds.io.write_to_inputs_h5(
        pd.Series(TECHS), 'i', path, 'set', comment='generation technologies', verbose=0,
    )
    return path


def make_sw(types, gentechs, storagetechs, bcr='0.5', gridcharging='0'):
    return {
        'GSw_StorageHybrid': '1',
        'GSw_StorageHybrid_Types': types,
        'GSw_StorageHybrid_GenTechs': gentechs,
        'GSw_StorageHybrid_StorageTechs': storagetechs,
        'GSw_StorageHybrid_BCR': bcr,
        'GSw_StorageHybrid_GridCharging': gridcharging,
    }


def config(gen_tech, storage_tech, config_id='1'):
    return {
        'config_id': config_id,
        'storage_hybrid_tech': copy_files._storage_hybrid_wrapper_name(config_id, gen_tech),
        'gen_tech': gen_tech,
        'storage_tech': storage_tech,
    }


#%% build_storage_hybrid_configs
def test_configs_broadcast_single_values(inputs_case):
    sw = make_sw('1_2', 'nuclear_gas-cc', 'tes-ms', bcr='0.5', gridcharging='0.25')
    configs = copy_files.build_storage_hybrid_configs(sw, str(inputs_case))
    assert [c['storage_hybrid_tech'] for c in configs] == [
        'storage-hybrid-1-nuclear', 'storage-hybrid-2-gas-cc']
    assert all(c['storage_tech'] == 'tes_ms' for c in configs)
    assert all(c['bcr'] == 0.5 and c['gridcharge_ratio'] == 0.25 for c in configs)


def test_configs_expand_numbered_family(inputs_case):
    sw = make_sw('1', 'upv', 'battery-li')
    configs = copy_files.build_storage_hybrid_configs(sw, str(inputs_case))
    assert [c['gen_tech'] for c in configs] == ['upv_1', 'upv_2', 'upv_3']
    assert [c['storage_hybrid_tech'] for c in configs] == [
        'storage-hybrid-1-upv_1', 'storage-hybrid-1-upv_2', 'storage-hybrid-1-upv_3']
    assert all(c['expanded'] for c in configs)


def test_configs_off_or_empty(inputs_case):
    assert copy_files.build_storage_hybrid_configs(
        {**make_sw('1', 'nuclear', 'tes-ms'), 'GSw_StorageHybrid': '0'}, str(inputs_case)) == []
    assert copy_files.build_storage_hybrid_configs(
        make_sw('', 'nuclear', 'tes-ms'), str(inputs_case)) == []


@pytest.mark.parametrize('sw, message', [
    (make_sw('1_2', 'nuclear_gas-cc', 'tes-ms', bcr='0.5_0.5_0.5'), 'must have 1 value or 2'),
    (make_sw('1_2', 'nuclear_gas-cc_upv', 'tes-ms'), 'must have 1 value or 2'),
    (make_sw('1', 'fusion', 'tes-ms'), 'not found'),
    (make_sw('1', 'nuclear', 'caes'), 'not found'),
    (make_sw('a_A', 'nuclear', 'tes-ms'), 'Duplicate'),
])
def test_configs_errors(inputs_case, sw, message):
    with pytest.raises(ValueError, match=message):
        copy_files.build_storage_hybrid_configs(sw, str(inputs_case))


#%% append_storage_hybrid_ivt
def test_ivt_append(inputs_case):
    ivt = (
        ',2020,2025,2030\n'
        'nuclear,1,2,3\n'
        'upv_1*upv_3,1,1,2\n'
    )
    path = inputs_case / 'ivt.csv'
    path.write_text(ivt)
    configs = [config('nuclear', 'tes_ms')] + [
        config(f'upv_{n}', 'battery_li', '2') for n in (1, 2, 3)]
    copy_files.append_storage_hybrid_ivt(str(inputs_case), configs)
    df = pd.read_csv(path, index_col=0)
    ## Original rows are kept, single gen techs get a row, and a contiguous family
    ## gets one condensed range row
    assert list(df.index) == [
        'nuclear', 'upv_1*upv_3',
        'storage-hybrid-2-upv_1*storage-hybrid-2-upv_3', 'storage-hybrid-1-nuclear']
    assert df.loc['storage-hybrid-1-nuclear'].tolist() == [1, 2, 3]
    assert df.loc['storage-hybrid-2-upv_1*storage-hybrid-2-upv_3'].tolist() == [1, 1, 2]


def test_ivt_append_missing_gen_tech(inputs_case):
    (inputs_case / 'ivt.csv').write_text(',2020\nnuclear,1\n')
    with pytest.raises(ValueError, match='no row in ivt.csv'):
        copy_files.append_storage_hybrid_ivt(str(inputs_case), [config('gas-cc', 'battery_li')])


#%% Registry row cloner (CSV)
@pytest.fixture
def csv_with_header(tmp_path):
    path = tmp_path / 'table.csv'
    ## CRLF line endings and a range row; both must survive untouched
    path.write_bytes(
        b'tech,hours\r\n'
        b'battery_li,24\r\n'
        b'nuclear,48\r\n'
        b'upv_1*upv_3,12\r\n'
    )
    return path


def appended(path, before):
    after = path.read_bytes()
    assert after.startswith(before), 'existing lines were changed'
    return after[len(before):]


def test_clone_storage_precedence(csv_with_header):
    before = csv_with_header.read_bytes()
    copy_files._clone_storage_hybrid_csv_rows(
        str(csv_with_header), 'tech', 'storage', [config('nuclear', 'battery_li')])
    assert appended(csv_with_header, before) == b'storage-hybrid-1-nuclear,24\r\n'


def test_clone_gen_precedence(csv_with_header):
    before = csv_with_header.read_bytes()
    copy_files._clone_storage_hybrid_csv_rows(
        str(csv_with_header), 'tech', 'gen', [config('nuclear', 'battery_li')])
    assert appended(csv_with_header, before) == b'storage-hybrid-1-nuclear,48\r\n'


def test_clone_range_row_and_fallback(csv_with_header):
    ## upv_2 has no row of its own but is covered by the upv_1*upv_3 range row;
    ## gen precedence finds it there, and storage precedence falls back to it when the
    ## storage tech has no row
    before = csv_with_header.read_bytes()
    copy_files._clone_storage_hybrid_csv_rows(
        str(csv_with_header), 'tech', 'storage', [config('upv_2', 'tes_ms')])
    assert appended(csv_with_header, before) == b'storage-hybrid-1-upv_2,12\r\n'


def test_clone_gen_only_never_falls_back(csv_with_header):
    before = csv_with_header.read_bytes()
    changed = copy_files._clone_storage_hybrid_csv_rows(
        str(csv_with_header), 'tech', 'gen_only', [config('wind-ons_1', 'battery_li')])
    assert not changed
    assert csv_with_header.read_bytes() == before


def test_clone_family_root(tmp_path):
    path = tmp_path / 'unitsize.csv'
    path.write_bytes(b'tech,MW\nupv,100\n')
    copy_files._clone_storage_hybrid_csv_rows(
        str(path), 'tech', 'gen', [config('upv_3', 'battery_li')])
    assert path.read_bytes() == b'tech,MW\nupv,100\nstorage-hybrid-1-upv_3,100\n'


def test_clone_geothermal_alias(tmp_path):
    ## Outage files list geothermal techs only as 'geothermal' (GAMS maps it through geo(i))
    path = tmp_path / 'outage_forced_static.csv'
    path.write_bytes(b'geothermal,0.129\n')
    geo_config = {**config('egs_allkm_5', 'flex_geo'), 'gen_alias': 'geothermal'}
    copy_files._clone_storage_hybrid_csv_rows(str(path), 0, 'gen_only', [geo_config])
    assert path.read_bytes() == b'geothermal,0.129\nstorage-hybrid-1-egs_allkm_5,0.129\n'


def test_clone_headerless_and_existing_row(tmp_path):
    ## Position-indexed column, no trailing newline, and a wrapper that already has a row
    path = tmp_path / 'outage.csv'
    path.write_bytes(b'nuclear,0.02\nstorage-hybrid-1-nuclear,0.5')
    copy_files._clone_storage_hybrid_csv_rows(
        str(path), 0, 'gen',
        [config('nuclear', 'tes_ms'), config('nuclear', 'tes_ms', config_id='2')])
    assert path.read_bytes() == (
        b'nuclear,0.02\nstorage-hybrid-1-nuclear,0.5\nstorage-hybrid-2-nuclear,0.02\n')


def test_registry_gen_tech_timing():
    ## A wrapper is built, degrades and counts toward national generation targets like
    ## its gen tech, so these entries must never take the storage tech's rows first
    precedence = {entry: prec for entry, _, prec in copy_files.STORAGE_HYBRID_ROW_CLONES}
    for entry in [
        'years_until_endogenous.csv', 'firstyear', 'degradation_annual.csv',
        'nat_gen_tech_frac',
    ]:
        assert precedence[entry] == 'gen', entry


def test_clone_lead_time_from_gen_tech(tmp_path):
    path = tmp_path / 'years_until_endogenous.csv'
    path.write_bytes(b'i,years_from_now\ntes_ms,0\nNuclear,8\n')
    copy_files._clone_storage_hybrid_csv_rows(
        str(path), 'i', 'gen', [config('nuclear', 'tes_ms')])
    assert path.read_bytes().endswith(b'storage-hybrid-1-nuclear,8\n')


def test_clone_missing_column(csv_with_header):
    with pytest.raises(ValueError, match="no 'i' column"):
        copy_files._clone_storage_hybrid_csv_rows(
            str(csv_with_header), 'i', 'gen', [config('nuclear', 'tes_ms')])


#%% Registry row cloner (inputs.h5)
def test_clone_h5_rows(inputs_case):
    df = pd.DataFrame({'i': ['nuclear', 'upv_1*upv_3'], 'c': ['1', '2'], 'Value': [1.0, 1.0]})
    reeds.io.write_to_inputs_h5(df, 'test_param', inputs_case, 'parameter', verbose=0)
    copy_files._clone_storage_hybrid_h5_rows(
        str(inputs_case), 'test_param', 'i', 'gen',
        [config('nuclear', 'tes_ms'), config('upv_2', 'battery_li', '2')])
    out = reeds.io.read_h5(os.path.join(inputs_case, 'inputs.h5'), 'test_param')
    assert out['i'].tolist() == [
        'nuclear', 'upv_1*upv_3', 'storage-hybrid-1-nuclear', 'storage-hybrid-2-upv_2']
    assert out['c'].tolist()[2:] == ['1', '2']
    with h5py.File(os.path.join(inputs_case, 'inputs.h5'), 'r') as f:
        assert 'test_param' in f


#%% Validation (reeds.checks.check_storage_hybrid uses the repo's inputs/)
def validation_sw(**kwargs):
    sw = {**make_sw('1_2', 'nuclear_gas-cc', 'tes-ms_battery-li', gridcharging='0_0.25'),
          'GSw_HybridPlant': '3'}
    sw.update({k if k.startswith('GSw_') else f'GSw_StorageHybrid_{k}': v
               for k, v in kwargs.items()})
    return sw


@pytest.mark.parametrize('sw', [
    validation_sw(),
    validation_sw(Types='1', GenTechs='upv', StorageTechs='battery-li', GridCharging='0'),
    validation_sw(Types='1', GenTechs='geohydro-allkm', StorageTechs='flex-geo', GridCharging='0'),
    validation_sw(CostMult='0.5'),
    validation_sw(GSw_FINITO_Link='0'),
    {'GSw_StorageHybrid': '0'},
])
def test_validation_passes(sw):
    reeds.checks.check_storage_hybrid(sw)


@pytest.mark.parametrize('kwargs, message', [
    ({'GSw_HybridPlant': '1'}, 'GSw_HybridPlant=2 or 3'),
    ({'GSw_FINITO_Link': '1'}, 'FINITO'),
    ({'BCR': '0.5_0.5_0.5'}, 'must have 1 value or 2'),
    ({'BCR': '0'}, 'must be > 0'),
    ({'GridCharging': '1.0'}, 'between 0 and the matching'),
    ({'CostMult': '0'}, 'CostMult must be a number > 0'),
    ({'CostMult': 'low'}, 'CostMult must be a number > 0'),
    ({'Types': '1_1'}, 'duplicate'),
    ({'GenTechs': 'h2-ct'}, 'hydrogen'),
    ({'GenTechs': 'coal-new'}, 'burns coal'),
    ({'GenTechs': 'biopower'}, 'burns biomass'),
    ({'GenTechs': 'beccs-mod'}, 'burns biomass'),
    ({'GenTechs': 'gas-cc-ccs-mod'}, 'captures CO2'),
    ({'GenTechs': 'gas-cc-ccs-f1'}, 'captures CO2'),
    ({'GenTechs': 'battery-li'}, 'includes storage'),
    ({'GenTechs': 'distpv'}, 'distributed PV'),
    ({'StorageTechs': 'caes'}, 'must be a storage'),
    ({'Types': '1', 'GenTechs': 'wind-ons', 'StorageTechs': 'tes-ms', 'GridCharging': '0'},
     'thermal storage'),
    ({'Types': '1', 'GenTechs': 'nuclear', 'StorageTechs': 'flex-geo', 'GridCharging': '0'},
     'geothermal'),
])
def test_validation_errors(kwargs, message):
    with pytest.raises(ValueError, match=message):
        reeds.checks.check_storage_hybrid(validation_sw(**kwargs))


#%% Capacity-credit resources for VRE wrappers
def test_add_vre_resources(inputs_case):
    pd.DataFrame({
        '*storage-hybrid_type': ['storage-hybrid-1-upv_2', 'storage-hybrid-2-nuclear'],
        'gen_tech': ['upv_2', 'nuclear'],
    }).to_csv(inputs_case / 'storage_hybrid_gentechs.csv', index=False)
    resources = pd.DataFrame({
        'r': ['p1', 'p2', 'p1'], 'i': ['upv_2', 'upv_2', 'upv_3'],
        'ccreg': ['c', 'c', 'c'], 'resource': ['upv_2|p1', 'upv_2|p2', 'upv_3|p1'],
    })
    out, gentechs = reeds.techs.add_storage_hybrid_vre_resources(resources, str(inputs_case))
    added = out.iloc[len(resources):]
    assert added['resource'].tolist() == [
        'storage-hybrid-1-upv_2|p1', 'storage-hybrid-1-upv_2|p2']
    assert gentechs.to_dict() == {'storage-hybrid-1-upv_2': 'upv_2'}


#%% Capacity-credit forced outages for wrappers
def test_add_gentech_members(inputs_case):
    pd.DataFrame({
        '*storage-hybrid_type': ['storage-hybrid-1-gas-cc', 'storage-hybrid-2-upv_2'],
        'gen_tech': ['Gas-CC', 'upv_2'],
    }).to_csv(inputs_case / 'storage_hybrid_gentechs.csv', index=False)
    out = reeds.techs.add_storage_hybrid_gentech_members(
        pd.Series(['gas-cc', 'nuclear']), str(inputs_case))
    assert out == ['gas-cc', 'nuclear', 'storage-hybrid-1-gas-cc']


#%% Incentives: TES and batteries are both energy storage
@pytest.mark.parametrize('fpath', sorted(
    Path(reeds.io.reeds_path, 'inputs', 'financials').glob('incentives_*.csv')
), ids=lambda p: p.stem)
def test_tes_incentives_match_battery(fpath):
    """
    TES is energy storage under the same credits as batteries, so every incentives
    file must give TES exactly the BATTERY rows (or neither tech any rows)
    """
    df = pd.read_csv(fpath)
    battery = df.loc[df.i == 'BATTERY'].drop(columns='i').reset_index(drop=True)
    tes = df.loc[df.i == 'TES'].drop(columns='i').reset_index(drop=True)
    pd.testing.assert_frame_equal(tes, battery, check_dtype=False)


#%% Storage-side ITC window for wrappers
def test_storage_side_itc_window(monkeypatch):
    """
    The storage side keeps the storage tech's ITC rate (with domestic content and the
    tax-equity penalty) over the larger of the gen and storage techs' windows
    """
    def row(i, start, safe_harbor, itc, domestic=0.0):
        return {
            'i': i, 'country': 'usa', 't_start_construction': start,
            'safe_harbor': safe_harbor, 'itc_frac': itc,
            'itc_percpt_domestic_bonus': domestic, 'itc_tax_equity_penalty': 0.1,
        }
    rows = (
        [row('Nuclear-SMR', 2032, 6, 0.3)]
        + [row('tes_ms', 2032, 4, 0.3, domestic=0.05)]
        + [row('upv_1', 2027, 0, 0.3)]
        + [row('battery_li', 2027, 4, 0.3)]
    )
    monkeypatch.setattr(reeds.financials, 'import_data', lambda **kwargs: pd.DataFrame(rows))
    wrappers = pd.DataFrame({
        'i': ['storage-hybrid-1-nuclear-smr', 'storage-hybrid-2-upv_1', 'storage-hybrid-3-gas-cc'],
        'gen_tech': ['Nuclear-SMR', 'upv_1', 'gas-cc'],
        'storage_tech': ['tes_ms', 'battery_li', 'battery_li'],
    })
    df = reeds.financials.storage_hybrid_storage_itc('obbba', None, None, wrappers)
    years = df.groupby('i')['t'].agg(['min', 'max'])
    ## TES on a nuclear wrapper: nuclear's 6-year window, not TES's 4
    assert tuple(years.loc['storage-hybrid-1-nuclear-smr']) == (2032, 2038)
    ## Battery on a upv wrapper: the battery's 4 years, not upv's 0
    assert tuple(years.loc['storage-hybrid-2-upv_1']) == (2027, 2031)
    ## Gen tech with no credit: the storage tech's own window
    assert tuple(years.loc['storage-hybrid-3-gas-cc']) == (2027, 2031)
    ## Rate: (0.3 + 0.05 domestic) * (1 - 0.1)
    tes = df.loc[df.i == 'storage-hybrid-1-nuclear-smr', 'itc_frac_monetized']
    assert tes.round(6).eq(0.315).all()


def test_storage_side_itc_no_wrappers():
    df = reeds.financials.storage_hybrid_storage_itc(
        'obbba', None, None, pd.DataFrame(columns=['i', 'gen_tech', 'storage_tech']))
    assert df.empty and list(df.columns) == ['i', 't', 'itc_frac_monetized']
