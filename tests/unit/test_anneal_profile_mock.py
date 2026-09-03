#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""anneal_profile(): real dose-conserving Gaussian broadening -- no
ViennaPS/DevSim needed.

2026-09-03 dopant-state-unification, Task 1: DopantProfile is now
model-agnostic (model_params dict instead of top-level peak_conc_cm3/
peak_position_um/straggle_um; no more thermal_budget field at all).
anneal_profile() no longer tracks a cumulative thermal budget itself --
per its own docstring, appending a ThermalEvent to thermal_history is
apply_thermal_anneal()'s job (a later task of this same plan), so the
two thermal_budget-specific assertions from the old
test_exact_broadening_matches_the_real_formula/
test_cumulative_across_two_anneal_calls are dropped; the straggle/dose
broadening assertions (this function's actual job) are unchanged and
still hold via model_params.
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.dopant_profile import DopantProfile
from tcad.physics.diffusion_model import anneal_profile, thermal_budget_contribution


def _gaussian_profile(species, polarity, peak, position, straggle, host_material="Si"):
    def shape(x, d, p=peak, pos=position, s=straggle):
        return p * math.exp(-((x - pos) ** 2) / (2.0 * s ** 2))
    return DopantProfile(
        species=species, polarity=polarity, concentration_at=shape,
        host_material=host_material, model="gaussian_v1",
        model_params={
            "peak_conc_cm3": peak, "peak_position_um": position,
            "straggle_um": straggle,
        },
    )


def _dose(profile):
    """Q = peak * straggle * sqrt(2*pi) -- this plan's own defined
    dose convention (a self-consistent 1D linear density, not a
    claimed real-world 3D areal dose -- see the plan's Global
    Constraints for why)."""
    return (profile.model_params["peak_conc_cm3"]
            * profile.model_params["straggle_um"] * math.sqrt(2.0 * math.pi))


def test_broadens_and_conserves_dose():
    profile = _gaussian_profile("P", "donor", peak=1e19, position=0.0, straggle=0.1)
    dose_before = _dose(profile)

    annealed = anneal_profile(profile, temperature_c=900.0, time_s=600.0)

    dose_after = _dose(annealed)
    old_straggle = profile.model_params["straggle_um"]
    new_straggle = annealed.model_params["straggle_um"]
    old_peak = profile.model_params["peak_conc_cm3"]
    new_peak = annealed.model_params["peak_conc_cm3"]
    print(f"anneal P donor @ 900.0 C, 600.0 s:")
    print(f"  straggle_um: {old_straggle:.6f} -> {new_straggle:.6f} "
          f"({'broadened' if new_straggle > old_straggle else 'NOT broadened'})")
    print(f"  peak_conc_cm3: {old_peak:.6e} -> {new_peak:.6e} "
          f"({'dropped' if new_peak < old_peak else 'NOT dropped'})")
    print(f"  dose Q: {dose_before:.6e} -> {dose_after:.6e} "
          f"(relative change {abs(dose_after - dose_before) / dose_before:.3e})")

    assert new_straggle > old_straggle, "must broaden, not stay fixed"
    assert new_peak < old_peak, (
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
    new_straggle = annealed.model_params["straggle_um"]
    print(f"anneal B acceptor @ 950.0 C, 300.0 s: D*t = {contribution.value:.6e} cm^2")
    print(f"  straggle_um^2: {new_straggle ** 2:.6e} "
          f"(expected {expected_straggle_um2:.6e})")
    assert abs(new_straggle ** 2 - expected_straggle_um2) / expected_straggle_um2 < 1e-9


def test_higher_temperature_broadens_more():
    profile_a = _gaussian_profile("P", "donor", peak=1e19, position=0.0, straggle=0.1)
    profile_b = _gaussian_profile("P", "donor", peak=1e19, position=0.0, straggle=0.1)

    low = anneal_profile(profile_a, temperature_c=900.0, time_s=600.0)
    high = anneal_profile(profile_b, temperature_c=1000.0, time_s=600.0)

    low_straggle = low.model_params["straggle_um"]
    high_straggle = high.model_params["straggle_um"]
    print(f"anneal P donor, 600.0 s: straggle_um @ 900.0 C = {low_straggle:.6f}, "
          f"@ 1000.0 C = {high_straggle:.6f} "
          f"({'higher T broadens more' if high_straggle > low_straggle else 'NOT higher'})")

    assert high_straggle > low_straggle, (
        "1000 C must broaden more than 900 C at the identical duration"
    )


def test_no_shape_or_no_species_is_unchanged():
    """A profile with no defined Gaussian shape (no straggle_um in
    model_params -- e.g. Stage A's uniform/step_junction/
    implant_windows-derived profiles) or no species label has nothing
    anneal_profile() can compute a citation-backed D(T) for -- returned
    unchanged, not guessed."""
    no_shape = DopantProfile(species="P", polarity="donor",
                              concentration_at=lambda x, d: 1e17,
                              host_material="Si", model="uniform_v1")
    result = anneal_profile(no_shape, temperature_c=900.0, time_s=600.0)
    print(f"no-shape profile (no straggle_um) annealed @ 900.0 C, 600.0 s: "
          f"returned same object = {result is no_shape}")
    assert result is no_shape or result == no_shape

    no_species = DopantProfile(
        species=None, polarity="donor", concentration_at=lambda x, d: 1e19,
        host_material="Si", model="gaussian_v1",
        model_params={"peak_conc_cm3": 1e19, "peak_position_um": 0.0, "straggle_um": 0.1},
    )
    result = anneal_profile(no_species, temperature_c=900.0, time_s=600.0)
    old_straggle = no_species.model_params["straggle_um"]
    new_straggle = result.model_params["straggle_um"]
    print(f"no-species profile (species=None) annealed @ 900.0 C, 600.0 s: "
          f"straggle_um {old_straggle:.6f} -> {new_straggle:.6f} "
          f"({'unchanged' if new_straggle == old_straggle else 'CHANGED'})")
    assert new_straggle == old_straggle, (
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

    once_straggle = once.model_params["straggle_um"]
    twice_straggle = twice.model_params["straggle_um"]
    print(f"cumulative anneal P donor: initial straggle_um = "
          f"{profile.model_params['straggle_um']:.6f}")
    print(f"  after step1 (900.0 C, 600.0 s): straggle_um = {once_straggle:.6f}")
    print(f"  after step2 (1000.0 C, 300.0 s): straggle_um = {twice_straggle:.6f}")

    assert twice_straggle > once_straggle
    assert abs(twice_straggle ** 2 - expected_straggle_um2) / expected_straggle_um2 < 1e-9


def test_anneal_profile_reads_model_params_and_uses_real_host_material():
    """Real bug this task's schema change surfaces and fixes: the OLD
    anneal_profile() hardcoded "Si" as the D(T) host material instead
    of reading the profile's own host_material -- harmless while every
    profile WAS Si, but wrong the moment host_material is a real,
    meaningful field (this task adds it). A SiGe-tagged profile must
    get SiGe's own D(T), not silently reuse Si's."""
    from tcad.physics.dopant_profile import DopantProfile
    from tcad.physics.diffusion_model import anneal_profile

    profile = DopantProfile(
        species="B", polarity="acceptor",
        concentration_at=lambda x, d: 1e18,
        host_material="Si", model="gaussian_v1",
        model_params={"peak_conc_cm3": 1e18, "peak_position_um": 0.0, "straggle_um": 0.2},
    )
    widened = anneal_profile(profile, 900.0, 600.0)
    print(f"straggle {profile.model_params['straggle_um']:.4f} -> "
          f"{widened.model_params['straggle_um']:.4f} um (host_material=Si)")
    assert widened.model_params["straggle_um"] > profile.model_params["straggle_um"]

    unknown_host = DopantProfile(
        species="B", polarity="acceptor",
        concentration_at=lambda x, d: 1e18,
        host_material="SiGe",  # no B-in-SiGe citation exists in this project
        model="gaussian_v1",
        model_params={"peak_conc_cm3": 1e18, "peak_position_um": 0.0, "straggle_um": 0.2},
    )
    unchanged = anneal_profile(unknown_host, 900.0, 600.0)
    print(f"host_material=SiGe (no citation): straggle unchanged = "
          f"{unchanged.model_params['straggle_um'] == unknown_host.model_params['straggle_um']}")
    assert unchanged.model_params["straggle_um"] == unknown_host.model_params["straggle_um"], (
        "must NOT silently reuse Si's D(T) for a different host_material -- UNKNOWN, not guessed"
    )


def main():
    test_broadens_and_conserves_dose()
    test_exact_broadening_matches_the_real_formula()
    test_higher_temperature_broadens_more()
    test_no_shape_or_no_species_is_unchanged()
    test_cumulative_across_two_anneal_calls()
    test_anneal_profile_reads_model_params_and_uses_real_host_material()
    print("anneal_profile() conserves dose exactly, matches the real "
          "Gaussian-diffusion broadening formula, is genuinely "
          "temperature-dependent (not just elapsed time), accumulates "
          "correctly across repeated anneal calls, and uses the "
          "profile's own host_material (not a hardcoded 'Si') for D(T).")


if __name__ == "__main__":
    main()
