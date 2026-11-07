"""Unit tests for the Stage 2 constraint layer (surrogate_constraints.py).

Run from any folder:
    python -m pytest postprocessing/reedssurr/Stage2/tests -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler

CODE = Path(__file__).resolve().parents[1] / "code"
if str(CODE) not in sys.path:
    sys.path.insert(0, str(CODE))

import surrogate_constraints as sc  # noqa: E402
from surrogate_constraints import (  # noqa: E402
    Stage2InferenceConfig, apply_constraints, enforce_additivity, hold_constants,
)
from surrogate_predict import predict  # noqa: E402
from surrogate_uq import prediction_interval  # noqa: E402

DISTPV = 12994.628099


def s(d: dict) -> pd.Series:
    return pd.Series(d, dtype=float)


# ---------------------------------------------------------------------------
# Additivity
# ---------------------------------------------------------------------------
def test_additivity_with_constant_region():
    # p63 was dropped as a constant (2,400 MW); only p65 is modelled.
    reg = s({"cap_nuclear_p65": 1000.0})
    sys_pred = s({"cap_nuclear": 4000.0})
    out = enforce_additivity(reg, sys_pred, constants={"cap_nuclear_p63": 2400.0})
    assert out["cap_nuclear_p65"] == pytest.approx(1600.0)
    # Constant held in the vector is not scaled, and the full sum matches.
    out2 = apply_constraints(reg, overall_pred=sys_pred, constants={"cap_nuclear_p63": 2400.0})
    assert out2["cap_nuclear_p63"] == pytest.approx(2400.0)
    assert out2[["cap_nuclear_p63", "cap_nuclear_p65"]].sum() == pytest.approx(4000.0)


def test_transmission_corridors_map_to_tran_total():
    reg = s({"tran_p60_p61_AC": 100.0, "tran_p61_p62_AC": 300.0})
    out = enforce_additivity(reg, s({"tran_total": 800.0}))
    assert out["tran_p60_p61_AC"] == pytest.approx(200.0)
    assert out["tran_p61_p62_AC"] == pytest.approx(600.0)
    assert out.sum() == pytest.approx(800.0)


def test_transmission_interface_counted_once_and_constant_corridor_fixed():
    # The same interface listed in both directions counts once; a constant
    # corridor is subtracted from the target and not scaled.
    reg = s({"tran_p60_p61_AC": 100.0, "tran_p61_p60_AC": 100.0, "tran_p61_p62_AC": 300.0})
    out = enforce_additivity(reg, s({"tran_total": 1000.0}),
                             constants={"tran_p63_p64_AC": 200.0})
    assert out["tran_p60_p61_AC"] == pytest.approx(200.0)
    assert out["tran_p61_p60_AC"] == pytest.approx(200.0)
    assert out["tran_p61_p62_AC"] == pytest.approx(600.0)


def test_additivity_skips_non_positive():
    reg = s({"gen_battery_li_p60": -5.0, "gen_battery_li_p61": -3.0})
    out = enforce_additivity(reg, s({"gen_battery_li": -10.0}))
    pd.testing.assert_series_equal(out, reg)
    # Adjusted target <= 0: the constant part already exceeds the system value.
    reg2 = s({"cap_x_p60": 10.0})
    out2 = enforce_additivity(reg2, s({"cap_x": 5.0}), constants={"cap_x_p61": 6.0})
    pd.testing.assert_series_equal(out2, reg2)


def test_floor_preserving_rescale_of_transmission():
    # Floors = initial corridor capacity; a constant corridor (6,539.15 MW)
    # is subtracted from the system value first. System says 10,939.15 MW,
    # so the two modelled corridors must sum to 4,400: only the increments
    # above the floors (20.7 + 213.15) are scaled to 4400 - 4316.15.
    floors = {"tran_p60_p61_AC": 2929.30, "tran_p61_p62_AC": 1386.85}
    const = {"tran_p63_p64_AC": 6539.15}
    reg = s({"tran_p60_p61_AC": 2950.0, "tran_p61_p62_AC": 1600.0})
    sys_pred = s({"tran_total": 4400.0 + 6539.15})
    out = apply_constraints(reg, overall_pred=sys_pred, constants=const, floors=floors)
    s_new = (4400.0 - 4316.15) / (20.7 + 213.15)
    assert out["tran_p60_p61_AC"] == pytest.approx(2929.30 + s_new * 20.7)
    assert out["tran_p61_p62_AC"] == pytest.approx(1386.85 + s_new * 213.15)
    assert out.sum() == pytest.approx(sys_pred["tran_total"])
    for c, f in floors.items():
        assert out[c] >= f
    # The plain proportional rescale (no floors) pushes p60_p61 below its floor.
    plain = enforce_additivity(reg, sys_pred, constants=const)
    assert plain["tran_p60_p61_AC"] < floors["tran_p60_p61_AC"]


def test_floor_preserving_rescale_at_or_below_floor_sum():
    floors = {"tran_p60_p61_AC": 2929.30, "tran_p61_p62_AC": 1386.85}
    reg = s({"tran_p60_p61_AC": 3000.0, "tran_p61_p62_AC": 1500.0})
    # System value equal to (or below) the sum of floors: s' = 0, every
    # corridor sits at its floor and the sum matches (or is as close as the
    # floors allow).
    out = enforce_additivity(reg, s({"tran_total": 4316.15}), floors=floors)
    assert out["tran_p60_p61_AC"] == pytest.approx(2929.30)
    assert out["tran_p61_p62_AC"] == pytest.approx(1386.85)
    out_low = enforce_additivity(reg, s({"tran_total": 4000.0}), floors=floors)
    pd.testing.assert_series_equal(out_low, out)
    # Without floors a non-positive target is still a skip (the plain rule).
    reg0 = s({"cap_x_p60": 5.0})
    pd.testing.assert_series_equal(enforce_additivity(reg0, s({"cap_x": 0.0})), reg0)
    # A regional value already below its floor: skipped, like a mixed-sign quantity.
    reg2 = s({"tran_p60_p61_AC": 2900.0, "tran_p61_p62_AC": 1500.0})
    out2 = enforce_additivity(reg2, s({"tran_total": 4600.0}), floors=floors)
    pd.testing.assert_series_equal(out2, reg2)


def test_corridor_clipped_to_floor_before_rescale():
    # Rule 1 clips at the known lower bound: p60_p61 is predicted 2,900 MW,
    # below its 2,929.3 MW initial capacity, so it is raised to the floor
    # first; the rescale then puts the remaining 183.85 MW above the floors
    # on p61_p62 (the only corridor with an increment).
    floors = {"tran_p60_p61_AC": 2929.30, "tran_p61_p62_AC": 1386.85}
    reg = s({"tran_p60_p61_AC": 2900.0, "tran_p61_p62_AC": 1500.0})
    out = apply_constraints(reg, overall_pred=s({"tran_total": 4500.0}), floors=floors)
    assert out["tran_p60_p61_AC"] == pytest.approx(2929.30)
    assert out["tran_p61_p62_AC"] == pytest.approx(1386.85 + (4500.0 - 4316.15))
    assert out.sum() == pytest.approx(4500.0)
    # The clip alone (no system prediction) also raises it to the floor.
    clipped = sc.clip_predictions(reg, floors)
    assert clipped["tran_p60_p61_AC"] == pytest.approx(2929.30)
    assert clipped["tran_p61_p62_AC"] == 1500.0


def test_system_tran_total_clipped_to_sum_of_corridor_floors():
    corridor = {"tran_p60_p61_AC": 2929.30, "tran_p61_p62_AC": 1386.85}
    sys_floors = sc.system_transmission_floors(corridor)
    assert sys_floors == {"tran_total": pytest.approx(4316.15), "tran_AC_total": pytest.approx(4316.15)}
    out = apply_constraints(s({"tran_total": 4000.0, "tran_AC_total": 4000.0}), floors=sys_floors)
    assert out["tran_total"] == pytest.approx(4316.15)
    assert out["tran_AC_total"] == pytest.approx(4316.15)   # duplicate of tran_total, same floor
    assert sc.system_transmission_floors({}) == {}


def test_transmission_floors_from_training_runs():
    df = pd.DataFrame({"tran_p60_p61_AC": [3000.0, 2929.3, 3100.0],
                       "cap_upv_p60": [1.0, 0.0, 2.0], "x_Dem": [0, 1, 2]})
    assert sc.transmission_floors(df) == {"tran_p60_p61_AC": 2929.3}


def test_additivity_skips_mixed_sign_quantity():
    # Net storage generation with mixed signs: the sum (0.5) nearly cancels,
    # so a proportional rescale to 100 would blow each region up 200x.
    reg = s({"gen_pumped-hydro_p61": -10.0, "gen_pumped-hydro_p64": 10.5})
    out = apply_constraints(reg, overall_pred=s({"gen_pumped-hydro": 100.0}))
    pd.testing.assert_series_equal(out, reg)


def test_additivity_is_default_and_noop_without_overall():
    assert Stage2InferenceConfig().apply_additivity is True
    reg = s({"cap_upv_p60": 10.0, "cap_upv_p61": 30.0})
    pd.testing.assert_series_equal(apply_constraints(reg), reg)


# ---------------------------------------------------------------------------
# Order: clip before rescale
# ---------------------------------------------------------------------------
def test_clip_runs_before_rescale():
    reg = s({"cap_x_p60": -50.0, "cap_x_p61": 100.0})
    out = apply_constraints(reg, overall_pred=s({"cap_x": 200.0}))
    # Clip first: (0, 100) -> scale 2 -> (0, 200), sum 200.
    # Rescale first would give (-200, 400) -> clip -> (0, 400), sum 400.
    assert out["cap_x_p60"] == 0.0
    assert out["cap_x_p61"] == pytest.approx(200.0)
    assert out.sum() == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# Cost identity
# ---------------------------------------------------------------------------
def test_cost_identity_equals_component_sum():
    pred = s({
        "cost_inv_investment_capacity_costs": 10e9,
        "cost_op_fuelcosts_objfn": 5e9,
        "cost_op_ptc_payments_negative": -2e9,
        "cost_op_h2_transport_intrareg": -1e-6,   # clipped to 0 first
        "cost_total": 99e9,                       # direct prediction, replaced
        "cap_upv": 100.0,
    })
    out = apply_constraints(pred)
    comps = sc.cost_component_cols(out.index)
    assert len(comps) == 4
    assert out["cost_total"] == pytest.approx(out[comps].sum())
    assert out["cost_total"] == pytest.approx(13e9)


# ---------------------------------------------------------------------------
# DistPV / constants
# ---------------------------------------------------------------------------
def test_cap_distpv_held_at_reeds_value():
    assert not hasattr(sc, "dgen_distpv_cap_mw")
    consts = {"cap_distpv": DISTPV}
    pred = s({"cap_upv": 100.0, "gen_distpv": 2.7e7})
    out = apply_constraints(pred, constants=consts)
    assert out["cap_distpv"] == DISTPV
    # A stray value is overwritten by the ReEDS constant.
    out2 = hold_constants(s({"cap_distpv": 1.0}), consts)
    assert out2["cap_distpv"] == DISTPV


def test_regional_distpv_constants_not_rescaled():
    consts = {"cap_distpv_p60": 1000.0, "cap_distpv_p61": 2000.0}
    reg = s({"cap_upv_p60": 10.0})
    out = apply_constraints(reg, overall_pred=s({"cap_distpv": 3600.0, "cap_upv": 20.0}),
                            constants=consts)
    assert out["cap_distpv_p60"] == 1000.0
    assert out["cap_distpv_p61"] == 2000.0
    assert out["cap_upv_p60"] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# predict() / prediction_interval() plumbing with a tiny fitted artifact
# ---------------------------------------------------------------------------
def _artifact(y_cols):
    x_cols = ["x_Batt", "x_Dem", "x_Fuel", "x_Pol", "x_REcost", "x_Siting"]
    rng = np.random.default_rng(0)
    X = rng.integers(0, 3, size=(30, len(x_cols))).astype(float)
    Y = np.abs(rng.normal(100, 10, size=(30, len(y_cols))))
    sx = StandardScaler().fit(X)
    model = LinearRegression().fit(sx.transform(X), Y)
    return {"model": model, "scaler_x": sx, "scaler_y": None, "x_cols": x_cols,
            "y_cols": list(y_cols), "oof_residuals": rng.normal(0, 1, size=Y.shape)}


LEVELS = {"Batt": 1.0, "Dem": 0.0, "Fuel": 1.0, "Pol": 0.0, "REcost": 1.0, "Siting": 1.0}


def test_predict_regional_with_overall_pred_and_constants():
    art = _artifact(["cap_nuclear_p65", "cost_op_fom_costs_p60", "cost_op_fom_costs_p61"])
    consts = {"cap_nuclear_p63": 2400.0}
    sys_pred = s({"cap_nuclear": 5000.0, "cost_op_fom_costs": 300.0})
    out = predict(art, LEVELS, overall_pred=sys_pred, constants=consts)
    assert out["cap_nuclear_p63"] + out["cap_nuclear_p65"] == pytest.approx(5000.0)
    assert out[["cost_op_fom_costs_p60", "cost_op_fom_costs_p61"]].sum() == pytest.approx(300.0)


def test_prediction_interval_aligns_extra_outputs():
    # Regional cost columns make derive_cost_total append cost_total; held
    # constants are appended too. Both get a zero-width interval.
    art = _artifact(["cap_upv_p60", "cost_op_fom_costs_p60"])
    point, lo, hi = prediction_interval(art, LEVELS, constants={"cap_distpv_p60": 10.0})
    assert list(point.index) == list(lo.index) == list(hi.index)
    assert lo["cap_distpv_p60"] == hi["cap_distpv_p60"] == 10.0
    assert lo["cost_total"] == hi["cost_total"]
    assert (hi["cap_upv_p60"] - lo["cap_upv_p60"]) > 0
