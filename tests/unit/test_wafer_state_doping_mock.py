#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState's doping query surface -- built by hand (no ViennaPS
domain needed), so this exercises the aggregation logic alone."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.dopant_profile import DopantProfile
from tcad.physics.wafer_state import WaferState


def _bare_state(dopant_profiles=()):
    return WaferState(
        materials=("Si",), stack=(), grid_delta_um=0.1,
        _cells=(), _thin_x=(), dopant_profiles=dopant_profiles,
    )


def test_no_profiles_is_zero_everywhere():
    state = _bare_state()
    assert state.donor_concentration_at(0.0, 0.0) == 0.0
    assert state.acceptor_concentration_at(0.0, 0.0) == 0.0
    assert state.net_doping_at(0.0, 0.0) == 0.0


def test_multiple_profiles_of_the_same_polarity_sum():
    """Two donor profiles superposed (e.g. a background plus an
    implant window, or two species) must ADD, matching the real
    physical relationship apply_implant_windows_doping already
    documents (superposition, not replacement)."""
    profiles = (
        DopantProfile(species="P", polarity="donor",
                      concentration_at=lambda x, d: 1.0e17),
        DopantProfile(species="As", polarity="donor",
                      concentration_at=lambda x, d: 2.0e16),
        DopantProfile(species="B", polarity="acceptor",
                      concentration_at=lambda x, d: 5.0e15),
    )
    state = _bare_state(profiles)
    assert state.donor_concentration_at(0.0, 0.0) == 1.0e17 + 2.0e16
    assert state.acceptor_concentration_at(0.0, 0.0) == 5.0e15
    assert state.net_doping_at(0.0, 0.0) == (1.0e17 + 2.0e16) - 5.0e15


def test_query_accepts_optional_dopant_profiles_kwarg():
    """WaferState.query() must accept dopant_profiles= as an optional
    kwarg without touching the domain-reading code path -- checked via
    signature inspection, no real ViennaPS domain needed for this unit
    test."""
    import inspect
    parameters = inspect.signature(WaferState.query).parameters
    assert "dopant_profiles" in parameters
    assert parameters["dopant_profiles"].default == ()


def main():
    test_no_profiles_is_zero_everywhere()
    test_multiple_profiles_of_the_same_polarity_sum()
    test_query_accepts_optional_dopant_profiles_kwarg()
    print("WaferState's doping query surface sums same-polarity "
          "profiles correctly and net_doping_at is a derived value.")


if __name__ == "__main__":
    main()
