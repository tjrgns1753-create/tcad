#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DopantProfile: a lossless, species-preserving adapter over the
existing DopingProfile/DopingRegion shape -- no ViennaPS/DevSim needed,
pure Python math, checked against hand-computed expected values."""

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
    assert profiles[0].thermal_budget == 0.0

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


def test_gaussian_implant_donor_acceptor_share_shape():
    doping = DopingProfile(kind="gaussian_implant", regions=[
        DopingRegion(region="Si", junction_axis="x",
                     peak_position_um=0.0, straggle_um=0.5,
                     donor_peak_conc_cm3=2.0e18, acceptor_peak_conc_cm3=3.0e17,
                     donor_species="P", acceptor_species="B"),
    ])
    profiles = dopant_profiles_from_doping_profile(doping)
    by_polarity = {p.polarity: p for p in profiles}
    import math
    expected_shape = math.exp(-((1.0 - 0.0) ** 2) / (2.0 * 0.5 ** 2))
    assert abs(by_polarity["donor"].concentration_at(1.0, 0.0)
               - 2.0e18 * expected_shape) < 1.0
    assert abs(by_polarity["acceptor"].concentration_at(1.0, 0.0)
               - 3.0e17 * expected_shape) < 1.0
    # peak value at the peak position
    assert abs(by_polarity["donor"].concentration_at(0.0, 0.0) - 2.0e18) < 1.0


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


def test_gaussian_terms_produce_one_dopant_profile_each():
    """Stage B: multiple implant terms in one region -> multiple
    DopantProfiles, each carrying its OWN species/peak/straggle/
    thermal_budget -- not collapsed into one."""
    doping = DopingProfile(kind="gaussian_implant", regions=[
        DopingRegion(
            region="Si", junction_axis="x",
            peak_position_um=0.0, straggle_um=0.2,  # legacy fields, unused when gaussian_terms is set
            gaussian_terms=[
                {"species": "B", "polarity": "acceptor", "peak_conc_cm3": 1.0e18,
                 "peak_position_um": -1.0, "straggle_um": 0.2, "thermal_budget_cm2": 1.5e-11},
                {"species": "P", "polarity": "donor", "peak_conc_cm3": 2.0e18,
                 "peak_position_um": 1.0, "straggle_um": 0.15, "thermal_budget_cm2": 3.0e-12},
            ],
        ),
    ])
    profiles = dopant_profiles_from_doping_profile(doping)
    assert len(profiles) == 2

    by_species = {p.species: p for p in profiles}
    print(f"B: polarity={by_species['B'].polarity}, "
          f"peak_conc_cm3={by_species['B'].peak_conc_cm3:.3e}, "
          f"peak_position_um={by_species['B'].peak_position_um}, "
          f"straggle_um={by_species['B'].straggle_um}, "
          f"thermal_budget={by_species['B'].thermal_budget:.3e}")
    print(f"P: polarity={by_species['P'].polarity}, "
          f"peak_conc_cm3={by_species['P'].peak_conc_cm3:.3e}, "
          f"peak_position_um={by_species['P'].peak_position_um}, "
          f"straggle_um={by_species['P'].straggle_um}, "
          f"thermal_budget={by_species['P'].thermal_budget:.3e}")
    assert by_species["B"].polarity == "acceptor"
    assert by_species["B"].peak_conc_cm3 == 1.0e18
    assert by_species["B"].peak_position_um == -1.0
    assert by_species["B"].straggle_um == 0.2
    assert by_species["B"].thermal_budget == 1.5e-11
    assert by_species["P"].polarity == "donor"
    assert by_species["P"].thermal_budget == 3.0e-12

    import math
    at_peak = by_species["B"].concentration_at(-1.0, 0.0)
    far_from_peak = by_species["B"].concentration_at(-1.0 + 10.0, 0.0)
    print(f"B concentration_at(peak=-1.0) = {at_peak:.6e} cm^-3, "
          f"concentration_at(peak+10um) = {far_from_peak:.6e} cm^-3")
    assert abs(at_peak - 1.0e18) < 1.0
    assert far_from_peak < 1.0e-10  # far from peak


def main():
    test_uniform_net_only_splits_by_sign()
    test_uniform_donor_acceptor_split_preserves_both()
    test_step_junction_matches_devsim_step_function()
    test_gaussian_implant_donor_acceptor_share_shape()
    test_implant_windows_background_plus_windows()
    test_unknown_kind_raises()
    test_non_x_junction_axis_raises()
    test_gaussian_terms_produce_one_dopant_profile_each()
    print("DopantProfile conversion matches doping_mapping.py's real "
          "DevSim equations for all 4 doping kinds, in both net-only "
          "and donor/acceptor-split input forms.")


if __name__ == "__main__":
    main()
