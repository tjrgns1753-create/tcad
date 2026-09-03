#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DopantProfile: a lossless, species-preserving adapter over the
existing DopingProfile/DopingRegion shape -- no ViennaPS/DevSim needed,
pure Python math, checked against hand-computed expected values.

2026-09-03 dopant-state-unification, Task 1: DopantProfile becomes
model-agnostic (host_material/model/model_params/thermal_history
instead of Gaussian-specific top-level fields). Two tests that
exercised capability `_gaussian_implant_profiles()` no longer provides
after this migration were REMOVED, not silently left broken:
  - donor+acceptor split sharing one Gaussian shape in a single call
  - the (Stage B) `gaussian_terms` multi-implant-term list
Both concepts are discarded/absorbed into the new WaferState-level,
cross-step `dopant_profiles` accumulation -- see
docs/superpowers/specs/2026-09-03-dopant-state-unification-design.md,
section 11's component-classification table ("DopingRegion.
gaussian_terms | Discard, concept absorbed") and this plan's own
task-1-brief.md, whose reference `_gaussian_implant_profiles()` never
grew a gaussian_terms branch or a donor/acceptor-split branch. This is
a deliberate, reviewed scope narrowing for this migration, not an
oversight; `_uniform_profiles`/`_step_junction_profiles`/
`_implant_windows_profiles` keep their existing donor/acceptor-split
branching unchanged, and are untouched by this removal.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.mesh.interface import DopingProfile, DopingRegion
from tcad.physics.dopant_profile import (
    DopantProfile,
    dopant_profiles_from_doping_profile,
)


def test_uniform_net_only_splits_by_sign():
    """No donor/acceptor split known -> the project's own documented
    convention (positive net = donor, negative net = acceptor) applies,
    and only ONE polarity's profile is produced -- never an invented
    opposite-polarity value that was never there."""
    doping = DopingProfile(kind="uniform", regions=[
        DopingRegion(region="Si", net_doping_cm3=1.0e17),
    ])
    profiles = dopant_profiles_from_doping_profile(doping)
    assert len(profiles) == 1
    assert profiles[0].polarity == "donor"
    assert profiles[0].species is None
    assert profiles[0].concentration_at(0.0, 0.0) == 1.0e17
    assert profiles[0].thermal_history == ()

    doping = DopingProfile(kind="uniform", regions=[
        DopingRegion(region="Si", net_doping_cm3=-2.0e16),
    ])
    profiles = dopant_profiles_from_doping_profile(doping)
    assert len(profiles) == 1
    assert profiles[0].polarity == "acceptor"
    assert profiles[0].concentration_at(5.0, 0.0) == 2.0e16


def test_uniform_donor_acceptor_split_preserves_both():
    doping = DopingProfile(kind="uniform", regions=[
        DopingRegion(region="Si", net_doping_cm3=5.0e15,
                     donor_conc_cm3=1.0e16, acceptor_conc_cm3=5.0e15,
                     donor_species="P", acceptor_species="B"),
    ])
    profiles = dopant_profiles_from_doping_profile(doping)
    by_polarity = {p.polarity: p for p in profiles}
    assert len(profiles) == 2
    assert by_polarity["donor"].species == "P"
    assert by_polarity["donor"].concentration_at(0.0, 0.0) == 1.0e16
    assert by_polarity["donor"].host_material == "Si"
    assert by_polarity["donor"].model == "uniform_v1"
    assert by_polarity["acceptor"].species == "B"
    assert by_polarity["acceptor"].concentration_at(0.0, 0.0) == 5.0e15


def test_step_junction_matches_devsim_step_function():
    """Reproduces doping_mapping.py's real DevSim equations exactly,
    INCLUDING the boundary quirk: at x == junction_position_um, both
    step() calls fire (DevSim's step(z) is 1.0 for z >= 0), so both
    donor and acceptor profiles are non-zero there. This is existing,
    already-shipped DevSim behavior -- not something this module may
    round away."""
    doping = DopingProfile(kind="step_junction", regions=[
        DopingRegion(region="Si", junction_axis="x", junction_position_um=1.0,
                     donor_conc_cm3=1.0e18, acceptor_conc_cm3=2.0e18,
                     donor_species="P", acceptor_species="B"),
    ])
    profiles = dopant_profiles_from_doping_profile(doping)
    by_polarity = {p.polarity: p for p in profiles}
    donor, acceptor = by_polarity["donor"], by_polarity["acceptor"]

    assert donor.concentration_at(2.0, 0.0) == 1.0e18   # right of junction: donor side
    assert donor.concentration_at(0.0, 0.0) == 0.0       # left of junction: no donor
    assert acceptor.concentration_at(0.0, 0.0) == 2.0e18
    assert acceptor.concentration_at(2.0, 0.0) == 0.0
    # boundary quirk, exactly matching DevSim's own step():
    assert donor.concentration_at(1.0, 0.0) == 1.0e18
    assert acceptor.concentration_at(1.0, 0.0) == 2.0e18


def test_implant_windows_background_plus_windows():
    doping = DopingProfile(kind="implant_windows", regions=[
        DopingRegion(region="Si", junction_axis="x",
                     donor_conc_cm3=1.0e15, acceptor_conc_cm3=1.0e16,
                     net_doping_cm3=1.0e15 - 1.0e16,
                     implant_windows=[
                         {"min_um": -1.6, "max_um": -0.6,
                          "donor_conc_cm3": 1.0e20, "acceptor_conc_cm3": 0.0,
                          "conc_cm3": 1.0e20},
                     ]),
    ])
    profiles = dopant_profiles_from_doping_profile(doping)
    by_polarity = {p.polarity: p for p in profiles}
    # inside the window: background + window contribution
    assert by_polarity["donor"].concentration_at(-1.1, 0.0) == 1.0e15 + 1.0e20
    # outside the window: background only
    assert by_polarity["donor"].concentration_at(2.0, 0.0) == 1.0e15
    assert by_polarity["acceptor"].concentration_at(-1.1, 0.0) == 1.0e16


def test_unknown_kind_raises():
    doping = DopingProfile(kind="not_a_real_kind", regions=[
        DopingRegion(region="Si", net_doping_cm3=1.0),
    ])
    try:
        dopant_profiles_from_doping_profile(doping)
        assert False, "expected NotImplementedError"
    except NotImplementedError:
        pass


def test_non_x_junction_axis_raises():
    """junction_axis="y" is not yet supported -- evaluators work along x
    only. A caller passing junction_axis="y" should get an immediate
    NotImplementedError, not a silently incorrect result."""
    doping = DopingProfile(kind="step_junction", regions=[
        DopingRegion(region="Si", junction_axis="y", junction_position_um=1.0,
                     donor_conc_cm3=1.0e18, acceptor_conc_cm3=1.0e18),
    ])
    try:
        dopant_profiles_from_doping_profile(doping)
        assert False, "expected NotImplementedError for junction_axis='y'"
    except NotImplementedError as e:
        assert "junction_axis" in str(e)


def test_gaussian_implant_non_x_axis_raises():
    """The junction_axis guard in _gaussian_implant_profiles() fires
    before anything else is read -- a y-axis region still raises
    immediately, same as every other doping kind's axis guard.
    (2026-09-03 dopant-state-unification Task 4: DopingRegion no
    longer has a gaussian_terms field at all -- this test used to
    construct one to exercise the guard ahead of that field; the guard
    fires ahead of peak_conc_cm3/peak_position_um/straggle_um instead,
    which is the only content a gaussian_implant region carries now.)"""
    doping = DopingProfile(kind="gaussian_implant", regions=[
        DopingRegion(
            region="Si", junction_axis="y",
            peak_conc_cm3=-1.0e18, peak_position_um=-1.0, straggle_um=0.2,
        ),
    ])
    try:
        dopant_profiles_from_doping_profile(doping)
        assert False, "expected NotImplementedError for junction_axis='y'"
    except NotImplementedError as e:
        assert "junction_axis" in str(e)
        print(f"gaussian_implant branch with junction_axis='y' raised as expected: {e}")


def test_dopant_profile_has_no_gaussian_specific_top_level_fields():
    import dataclasses
    from tcad.physics.dopant_profile import DopantProfile
    field_names = {f.name for f in dataclasses.fields(DopantProfile)}
    assert "peak_conc_cm3" not in field_names
    assert "peak_position_um" not in field_names
    assert "straggle_um" not in field_names
    assert "thermal_budget" not in field_names
    assert field_names == {
        "species", "polarity", "concentration_at", "host_material",
        "model", "model_params", "thermal_history", "source",
    }
    print(f"DopantProfile fields (model-agnostic): {sorted(field_names)}")


def test_gaussian_implant_profile_carries_model_tag_and_params():
    from tcad.mesh.interface import DopingProfile, DopingRegion
    from tcad.physics.dopant_profile import dopant_profiles_from_doping_profile

    region = DopingRegion(
        region="Si", junction_axis="x", peak_position_um=1.0,
        straggle_um=0.2, peak_conc_cm3=1e18,
    )
    doping = DopingProfile(kind="gaussian_implant", regions=[region])
    profiles = dopant_profiles_from_doping_profile(doping)
    assert len(profiles) == 1
    p = profiles[0]
    assert p.model == "gaussian_v1"
    assert p.host_material == "Si"
    assert p.model_params["peak_conc_cm3"] == 1e18
    assert p.model_params["peak_position_um"] == 1.0
    assert p.model_params["straggle_um"] == 0.2
    assert p.thermal_history == ()
    print(f"model={p.model!r}, model_params={p.model_params}, "
          f"concentration_at(1.0, 0.0)={p.concentration_at(1.0, 0.0):.3e}")
    assert abs(p.concentration_at(1.0, 0.0) - 1e18) < 1.0


def main():
    test_uniform_net_only_splits_by_sign()
    test_uniform_donor_acceptor_split_preserves_both()
    test_step_junction_matches_devsim_step_function()
    test_implant_windows_background_plus_windows()
    test_unknown_kind_raises()
    test_non_x_junction_axis_raises()
    test_gaussian_implant_non_x_axis_raises()
    test_dopant_profile_has_no_gaussian_specific_top_level_fields()
    test_gaussian_implant_profile_carries_model_tag_and_params()
    print("DopantProfile conversion matches doping_mapping.py's real "
          "DevSim equations for uniform/step_junction/implant_windows, "
          "in both net-only and donor/acceptor-split input forms, and "
          "the new model-agnostic schema carries host_material/model/"
          "model_params correctly for gaussian_implant.")


if __name__ == "__main__":
    main()
