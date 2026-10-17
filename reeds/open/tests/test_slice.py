import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from reeds.open import contract, prep, solvers, synthetic  # noqa: E402
from reeds.open import build_pyoframe as bpf  # noqa: E402
from reeds.open import validate_slice  # noqa: E402

REFERENCE_OBJECTIVE = 28351.94078717607


@pytest.fixture(scope="module")
def prepared():
    solvers.load_highs()
    case = synthetic.make_case()
    assert contract.check(case) == []
    return case, prep.prepare(case)


def solve(P):
    m = bpf.build(P)
    m.attr.Silent = True
    m.optimize()
    return m, bpf.results(m, P)


def test_synthetic_solves_to_reference_objective(prepared):
    _, P = prepared
    _, res = solve(P)
    assert abs(res["objective"] - REFERENCE_OBJECTIVE) / REFERENCE_OBJECTIVE < 1e-8


def test_solution_is_reproducible(prepared):
    _, P = prepared
    _, a = solve(P)
    _, b = solve(P)
    for name in P.var:
        assert a["primal"][name].equals(b["primal"][name]), name
    for name in P.con:
        if name in a["dual"]:
            assert a["dual"][name].equals(b["dual"][name]), name


def test_every_constraint_family_has_rows(prepared):
    _, P = prepared
    m, _ = solve(P)
    for name, dom in P.con.items():
        assert dom.height > 0, name
        assert hasattr(m, name), name


def test_matrix_export_matches_prepared_domains(prepared, tmp_path):
    _, P = prepared
    py = validate_slice.python_matrix(P, tmp_path / "model.mps")
    n_rows = sum(df.height for df in P.con.values())
    n_cols = sum(df.height for df in P.var.values())
    assert len(py["rows"]) == n_rows
    assert len(py["cols"]) == n_cols
    assert validate_slice.CONSTANT_COL not in py["cols"]
    symbols = {validate_slice.symbol_of(r) for r in py["rows"]}
    assert symbols == {name.lower() for name in P.con}


def test_objective_from_precomposed_tables_matches_component_costs(prepared):
    case, P = prepared
    import polars as pl
    cs = case.scalar("cost_scale")
    pvo = float(case["pvf_onm"]["value"][0])
    fom = case["cost_fom"].join(P.var["CAP"], on=["i", "v", "r", "t"], how="semi")
    expected = cs * pvo * fom["value"].sum()
    assert abs(P.obj["CAP"]["value"].sum() - expected) < 1e-9 * max(1.0, abs(expected))
    assert P.obj["GEN"].filter(pl.col("value") == 0.0).height == 0


def test_canonical_names_align_gams_and_pyoframe():
    assert validate_slice.canonical("GEN[Gas-CC,new1,z1,d1h1,2032]") == "gen(gas-cc,new1,z1,d1h1,2032)"
    assert validate_slice.canonical("GEN(gas-cc,new1,z1,d1h1,2032)") == "gen(gas-cc,new1,z1,d1h1,2032)"
    assert validate_slice.symbol_of("eq_loadcon(z1,d1h1,2032)") == "eq_loadcon"
