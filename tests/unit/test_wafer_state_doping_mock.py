#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState's doping query surface -- built by hand (no ViennaPS
domain needed), so this exercises the aggregation/dispatch logic alone.

NOTE: every fixture below is SYNTHETIC (hand-built WaferState/DopantProfile
objects), testing the dispatch LOGIC in isolation. It proves the branch
selection is correct; it does not and cannot validate that real oxidation
genuinely converts Si to SiO2 in a physically correct way -- that is Task 7's
job, with real ViennaPS execution.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.dopant_profile import DopantProfile
from tcad.physics.wafer_state import WaferState, LayerInfo, _Cell


def _bare_state(dopant_profiles=()):
    """A WaferState whose one cell exposes 'Si' everywhere -- i.e. the
    geometry genuinely still has every profile's host_material present,
    so the geometry-gated dispatch takes the 'computable' branch for
    all of them. This fixture is for exercising SUMMATION, not the
    three-way dispatch itself (see the geometry-gating tests below for
    that)."""
    return WaferState(
        materials=("Si",), stack=(), grid_delta_um=0.1,
        _cells=(_Cell(-1e9, 1e9, 1.0, "Si"),), _thin_x=(),
        dopant_profiles=dopant_profiles,
    )


def test_no_profiles_is_zero_everywhere():
    state = _bare_state()
    result = state.net_doping_at(0.0, 0.0)
    assert result.donor_concentration == 0.0
    assert result.acceptor_concentration == 0.0
    assert result.net_doping == 0.0
    assert result.physics_status is None


def test_multiple_profiles_of_the_same_polarity_sum():
    """Two donor profiles superposed (e.g. a background plus an
    implant window, or two species) must ADD, matching the real
    physical relationship apply_implant_windows_doping already
    documents (superposition, not replacement)."""
    profiles = (
        DopantProfile(species="P", polarity="donor",
                      concentration_at=lambda x, d: 1.0e17,
                      host_material="Si", model="uniform_v1"),
        DopantProfile(species="As", polarity="donor",
                      concentration_at=lambda x, d: 2.0e16,
                      host_material="Si", model="uniform_v1"),
        DopantProfile(species="B", polarity="acceptor",
                      concentration_at=lambda x, d: 5.0e15,
                      host_material="Si", model="uniform_v1"),
    )
    state = _bare_state(profiles)
    result = state.net_doping_at(0.0, 0.0)
    assert result.donor_concentration == 1.0e17 + 2.0e16
    assert result.acceptor_concentration == 5.0e15
    assert result.net_doping == (1.0e17 + 2.0e16) - 5.0e15
    assert result.physics_status is None


def test_query_signature_has_no_process_category_kwarg():
    """WaferState v2 migration: WaferState.query() no longer carries a
    per-call process-category argument (the removal-vs-conversion
    decision moved to tcad.physics.wafer_state_v2). It still takes
    dopant_profiles= as an optional kwarg."""
    import inspect
    parameters = inspect.signature(WaferState.query).parameters
    assert "dopant_profiles" in parameters
    assert parameters["dopant_profiles"].default == ()
    assert "last_step_category" not in parameters


def test_host_not_exposed_is_unsupported_never_a_silent_zero():
    """WaferState v2 migration: the v1 state has no per-location
    provenance to tell "genuinely removed" from "converted", so a
    profile whose host_material is NOT the exposed material at the
    query point reads UNSUPPORTED_BY_MODEL -- never a silent
    geometry-gated 0. (The removal-vs-conversion distinction lives in
    tcad.physics.wafer_state_v2's SpatialEvent / GeometryTransform.)"""
    profile = DopantProfile(
        species="P", polarity="donor",
        concentration_at=lambda x, d: 1e18,
        host_material="Si", model="gaussian_v1", model_params={},
    )
    state = WaferState(
        materials=("SiO2",), stack=(LayerInfo("SiO2", 0),),
        grid_delta_um=0.1, _cells=(_Cell(0.0, 1.0, 0.5, "SiO2"),),
        _thin_x=(), dopant_profiles=(profile,),
    )
    result = state.net_doping_at(0.5, 0.0)
    print(f"[conversion] donor_concentration={result.donor_concentration}, "
          f"physics_status={result.physics_status}")
    assert result.donor_concentration == 0.0   # the numeric FIELD is 0 (nothing computable)
    assert result.physics_status is not None
    assert result.physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"
    entry = result.physics_status["entries"][0]
    assert entry["material"] == "P"
    assert "not the exposed material" in entry["note"]


def test_partial_aggregate_never_hides_the_gap():
    """One profile computable, one UNSUPPORTED -- net_doping is the
    real partial sum, but physics_status MUST disclose the gap
    (spec Sec6 partial-unsupported aggregate contract)."""
    computable = DopantProfile(
        species="P", polarity="donor",
        concentration_at=lambda x, d: 3e18,
        host_material="Si", model="gaussian_v1", model_params={},
    )
    unsupported = DopantProfile(
        species="B", polarity="acceptor",
        concentration_at=lambda x, d: 1e18,
        host_material="SiGe",  # a material this WaferState doesn't have at all
        model="gaussian_v1", model_params={},
    )
    state = WaferState(
        materials=("Si",), stack=(LayerInfo("Si", 0),),
        grid_delta_um=0.1, _cells=(_Cell(0.0, 1.0, 0.5, "Si"),),
        _thin_x=(), dopant_profiles=(computable, unsupported),
    )
    result = state.net_doping_at(0.5, 0.0)
    print(f"donor={result.donor_concentration}, acceptor={result.acceptor_concentration}, "
          f"net={result.net_doping}, physics_status={result.physics_status}")
    assert result.donor_concentration == 3e18
    assert result.acceptor_concentration == 0.0   # unsupported contribution NOT silently substituted as 0-and-safe
    assert result.physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"
    assert any(e["material"] == "B" for e in result.physics_status["entries"])


def main():
    test_no_profiles_is_zero_everywhere()
    test_multiple_profiles_of_the_same_polarity_sum()
    test_query_signature_has_no_process_category_kwarg()
    test_host_not_exposed_is_unsupported_never_a_silent_zero()
    test_partial_aggregate_never_hides_the_gap()
    print("WaferState.net_doping_at is a real 2-way dispatch (host exposed "
          "-> apply; host not exposed -> UNSUPPORTED_BY_MODEL, never a silent "
          "zero), and same-polarity profiles still sum through DopingQueryResult.")


if __name__ == "__main__":
    main()
