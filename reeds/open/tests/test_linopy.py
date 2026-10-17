import sys
from pathlib import Path

import numpy as np
import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from reeds.open import contract, prep, solvers, synthetic  # noqa: E402
from reeds.open import build_linopy as bl  # noqa: E402
from reeds.open import build_pyoframe as bpf  # noqa: E402
from reeds.open import validate_slice  # noqa: E402

REFERENCE_OBJECTIVE = 28351.94078717607


@pytest.fixture(scope="module")
def prepared():
    solvers.load_highs()
    case = synthetic.make_case()
    assert contract.check(case) == []
    return case, prep.prepare(case)


def solve_linopy(P):
    lm = bl.build(P)
    bl.solve(lm, solver="simplex")
    return lm, bl.results(lm, P)


def test_linopy_solves_to_reference_objective(prepared):
    _, P = prepared
    _, res = solve_linopy(P)
    assert abs(res["objective"] - REFERENCE_OBJECTIVE) / REFERENCE_OBJECTIVE < 1e-8


def test_linopy_rows_and_columns_match_prepared_domains(prepared):
    _, P = prepared
    lm, _ = solve_linopy(P)
    py = bl.matrix(lm, validate_slice.VAR_DIMS, validate_slice.EQ_DIMS)
    assert len(py["cols"]) == sum(df.height for df in P.var.values())
    assert len(py["rows"]) == sum(df.height for df in P.con.values())


def test_linopy_matrix_equals_pyoframe_matrix(prepared, tmp_path):
    _, P = prepared
    a = validate_slice.python_matrix(P, tmp_path / "model.mps", builder="pyoframe")
    lm = bl.build(P)
    b = bl.matrix(lm, validate_slice.VAR_DIMS, validate_slice.EQ_DIMS)
    assert sorted(a["cols"]) == sorted(b["cols"])
    assert sorted(a["rows"]) == sorted(b["rows"])
    ca = {n: j for j, n in enumerate(a["cols"])}
    ra = {n: i for i, n in enumerate(a["rows"])}
    col_perm = np.array([ca[n] for n in b["cols"]])
    row_perm = np.array([ra[n] for n in b["rows"]])
    A_a = a["A"][row_perm][:, col_perm]
    diff = (A_a - b["A"]).tocoo()
    assert diff.nnz == 0 or np.abs(diff.data).max() < 1e-12
    assert np.allclose(a["c"][col_perm], b["c"])
    assert np.allclose(a["row_lo"][row_perm], b["row_lo"])
    assert np.allclose(a["row_up"][row_perm], b["row_up"])
    assert np.allclose(a["col_lo"][col_perm], b["col_lo"])
    assert np.allclose(a["col_up"][col_perm], b["col_up"])


def test_linopy_objective_and_reduced_costs_agree_with_pyoframe(prepared):
    _, P = prepared
    m = bpf.build(P)
    bpf.solve(m, solver="simplex")
    lm, _ = solve_linopy(P)
    assert abs(bpf.objective_value(m) - bl.objective_value(lm)) / REFERENCE_OBJECTIVE < 1e-8
    names = tuple(n for n in ("CAP", "INV", "INV_RSC") if n in P.var)
    rc_py = bpf.reduced_costs(m, P, names)
    rc_lp = bl.reduced_costs(lm, P, names)
    for name in names:
        keys = list(P.var[name].columns)
        joined = rc_py[name].join(rc_lp[name].rename({"marginal": "lp"}), on=keys, how="full", coalesce=True)
        assert joined["marginal"].is_null().sum() == 0 and joined["lp"].is_null().sum() == 0
        x = joined["marginal"].to_numpy()
        y = joined["lp"].to_numpy()
        assert np.abs(x - y).max() <= 1e-6 * max(1.0, np.abs(x).max()), name


def test_linopy_solution_satisfies_kkt(prepared):
    _, P = prepared
    lm, res = solve_linopy(P)
    py = bl.matrix(lm, validate_slice.VAR_DIMS, validate_slice.EQ_DIMS)
    x = np.concatenate([res["primal"][name]["solution"].to_numpy() for name in lm.var_dom])
    y = np.concatenate([res["dual"][name]["dual"].to_numpy() for name in lm.row_dom])
    primal = validate_slice.primal_check(py, x, 1e-6)
    assert primal["pass"], primal
    kkt = validate_slice.kkt_check(py, x, y, 1e-6)
    assert kkt["pass"], kkt
