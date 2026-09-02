#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""anneal_profile(): real dose-conserving Gaussian broadening -- no
ViennaPS/DevSim needed."""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.dopant_profile import DopantProfile
from tcad.physics.diffusion_model import anneal_profile, thermal_budget_contribution


def _gaussian_profile(species, polarity, peak, position, straggle):
    def shape(x, d, p=peak, pos=position, s=straggle):
        return p * math.exp(-((x - pos) ** 2) / (2.0 * s ** 2))
    return DopantProfile(
        species=species, polarity=polarity, concentration_at=shape,
        peak_conc_cm3=peak, peak_position_um=position, straggle_um=straggle,
    )


def _dose(profile):
    """Q = peak * straggle * sqrt(2*pi) -- this plan's own defined
    dose convention (a self-consistent 1D linear density, not a
    claimed real-world 3D areal dose -- see the plan's Global
    Constraints for why)."""
    return profile.peak_conc_cm3 * profile.straggle_um * math.sqrt(2.0 * math.pi)


def test_broadens_and_conserves_dose():
    profile = _gaussian_profile("P", "donor", peak=1e19, position=0.0, straggle=0.1)
    dose_before = _dose(profile)

    annealed = anneal_profile(profile, temperature_c=900.0, time_s=600.0)

    dose_after = _dose(annealed)
    print(f"anneal P donor @ 900.0 C, 600.0 s:")
    print(f"  straggle_um: {profile.straggle_um:.6f} -> {annealed.straggle_um:.6f} "
          f"({'broadened' if annealed.straggle_um > profile.straggle_um else 'NOT broadened'})")
    print(f"  peak_conc_cm3: {profile.peak_conc_cm3:.6e} -> {annealed.peak_conc_cm3:.6e} "
          f"({'dropped' if annealed.peak_conc_cm3 < profile.peak_conc_cm3 else 'NOT dropped'})")
    print(f"  dose Q: {dose_before:.6e} -> {dose_after:.6e} "
          f"(relative change {abs(dose_after - dose_before) / dose_before:.3e})")

    assert annealed.straggle_um > profile.straggle_um, "must broaden, not stay fixed"
    assert annealed.peak_conc_cm3 < profile.peak_conc_cm3, (
        "peak must drop as the profile widens -- otherwise dose is invented"
    )
    assert abs(dose_after - dose_before) / dose_before < 1e-9, (
        f"dose not conserved: {dose_before} -> {dose_after}"
    )


def test_exact_broadening_matches_the_real_formula():
    """sigma_new^2 = sigma_old^2 + 2*Dt -- the exact Gaussian-diffusion
    Green's-function result, checked against thermal_budget_contribution's
    own real D(T)*t (Task 1), not re-derived independently here."""
    profile = _gaussian_profile("B", "acceptor", peak=5e18, position=1.0, straggle=0.2)
    contribution = thermal_budget_contribution("B", "Si", 950.0, 300.0)
    assert contribution.value is not None

    annealed = anneal_profile(profile, temperature_c=950.0, time_s=300.0)

    # Dt is in cm^2; straggle_um is in um -- 1 cm^2 = 1e8 um^2.
    expected_straggle_um2 = (0.2 ** 2) + 2.0 * contribution.value * 1e8
    print(f"anneal B acceptor @ 950.0 C, 300.0 s: D*t = {contribution.value:.6e} cm^2")
    print(f"  straggle_um^2: {annealed.straggle_um ** 2:.6e} "
          f"(expected {expected_straggle_um2:.6e})")
    print(f"  thermal_budget: {annealed.thermal_budget:.6e} cm^2 "
          f"(expected {contribution.value:.6e} cm^2)")
    assert abs(annealed.straggle_um ** 2 - expected_straggle_um2) / expected_straggle_um2 < 1e-9

    assert abs(annealed.thermal_budget - contribution.value) / contribution.value < 1e-9


def test_higher_temperature_broadens_more():
    profile_a = _gaussian_profile("P", "donor", peak=1e19, position=0.0, straggle=0.1)
    profile_b = _gaussian_profile("P", "donor", peak=1e19, position=0.0, straggle=0.1)

    low = anneal_profile(profile_a, temperature_c=900.0, time_s=600.0)
    high = anneal_profile(profile_b, temperature_c=1000.0, time_s=600.0)

    print(f"anneal P donor, 600.0 s: straggle_um @ 900.0 C = {low.straggle_um:.6f}, "
          f"@ 1000.0 C = {high.straggle_um:.6f} "
          f"({'higher T broadens more' if high.straggle_um > low.straggle_um else 'NOT higher'})")

    assert high.straggle_um > low.straggle_um, (
        "1000 C must broaden more than 900 C at the identical duration"
    )


def test_no_shape_or_no_species_is_unchanged():
    """A profile with no defined Gaussian shape (straggle_um is None --
    e.g. Stage A's uniform/step_junction/implant_windows-derived
    profiles) or no species label has nothing anneal_profile() can
    compute a citation-backed D(T) for -- returned unchanged, not
    guessed."""
    no_shape = DopantProfile(species="P", polarity="donor",
                              concentration_at=lambda x, d: 1e17)
    result = anneal_profile(no_shape, temperature_c=900.0, time_s=600.0)
    print(f"no-shape profile (straggle_um=None) annealed @ 900.0 C, 600.0 s: "
          f"returned same object = {result is no_shape}")
    assert result is no_shape or result == no_shape

    no_species = DopantProfile(species=None, polarity="donor",
                                concentration_at=lambda x, d: 1e19,
                                peak_conc_cm3=1e19, peak_position_um=0.0,
                                straggle_um=0.1)
    result = anneal_profile(no_species, temperature_c=900.0, time_s=600.0)
    print(f"no-species profile (species=None) annealed @ 900.0 C, 600.0 s: "
          f"straggle_um {no_species.straggle_um:.6f} -> {result.straggle_um:.6f} "
          f"({'unchanged' if result.straggle_um == no_species.straggle_um else 'CHANGED'})")
    assert result.straggle_um == no_species.straggle_um, (
        "no species label -- no citation-backed D(T) exists -- must not guess one"
    )


def test_cumulative_across_two_anneal_calls():
    """The core worked example this whole stage exists for: annealing
    TWICE must widen the profile MORE than annealing once, and by the
    exact sum of both steps' own D(T)*t (each step's OWN temperature)."""
    profile = _gaussian_profile("P", "donor", peak=1e19, position=0.0, straggle=0.1)

    once = anneal_profile(profile, temperature_c=900.0, time_s=600.0)
    twice = anneal_profile(once, temperature_c=1000.0, time_s=300.0)

    c1 = thermal_budget_contribution("P", "Si", 900.0, 600.0)
    c2 = thermal_budget_contribution("P", "Si", 1000.0, 300.0)
    expected_straggle_um2 = (0.1 ** 2) + 2.0 * (c1.value + c2.value) * 1e8

    print(f"cumulative anneal P donor: initial straggle_um = {profile.straggle_um:.6f}")
    print(f"  after step1 (900.0 C, 600.0 s): straggle_um = {once.straggle_um:.6f}, "
          f"thermal_budget = {once.thermal_budget:.6e} cm^2")
    print(f"  after step2 (1000.0 C, 300.0 s): straggle_um = {twice.straggle_um:.6f}, "
          f"thermal_budget = {twice.thermal_budget:.6e} cm^2 "
          f"(expected sum {c1.value + c2.value:.6e} cm^2)")

    assert twice.straggle_um > once.straggle_um
    assert abs(twice.straggle_um ** 2 - expected_straggle_um2) / expected_straggle_um2 < 1e-9
    assert abs(twice.thermal_budget - (c1.value + c2.value)) / (c1.value + c2.value) < 1e-9


def main():
    test_broadens_and_conserves_dose()
    test_exact_broadening_matches_the_real_formula()
    test_higher_temperature_broadens_more()
    test_no_shape_or_no_species_is_unchanged()
    test_cumulative_across_two_anneal_calls()
    print("anneal_profile() conserves dose exactly, matches the real "
          "Gaussian-diffusion broadening formula, is genuinely "
          "temperature-dependent (not just elapsed time), and "
          "accumulates correctly across repeated anneal calls.")


if __name__ == "__main__":
    main()
