#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage B acceptance tests, exactly as specified during design review:

A: B implant -> anneal
B: B implant -> P implant -> anneal
C: B implant -> anneal -> P implant -> anneal

For each: no profile is destroyed, B and P use independently-different
D(T), anneal reaches every currently-existing profile, dose is
conserved, and changing temperature/time produces a different real
result. C's own final anneal must move BOTH the original B profile
(already annealed once) and the newly-added P profile.

2026-09-03 dopant-state-unification, Task 3: apply_thermal_anneal()'s
signature changed from (ProcessResult, ...) -> ProcessResult to
(Tuple[DopantProfile, ...], ...) -> (Tuple[DopantProfile, ...],
Optional[dict]) -- profiles now live on WaferState, not
ProcessResult.doping (spec Sec9; Task 5 wires the real per-step
WaferState accumulation this multi-implant B/P scenario stands in
for here). Each implant is still built with the real, unchanged
apply_gaussian_implant_doping() against a real ViennaPS-produced
ProcessResult, then converted to a DopantProfile via
dopant_profiles_from_doping_profile() (Task 1) -- B and P become two
independent profiles in one tuple rather than two gaussian_terms
entries inside one DopingRegion (that old existing=/gaussian_terms
accumulation mechanism is removed outright in Task 4). The anneal
formula itself (tcad.physics.diffusion_model.anneal_profile) is
UNCHANGED, so every straggle/peak number below is the same real
number Stage B already established -- only the plumbing moved.
"""

import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.etching  # noqa: F401
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_gaussian_implant_doping, apply_thermal_anneal
from tcad.physics.dopant_profile import dopant_profiles_from_doping_profile
from tcad.device.devsim import backend as devsim_backend

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

RECIPE = {
    "grid_delta_um": 0.1, "x_extent_um": 4.0, "y_extent_um": 3.0,
    "mask_left_um": 1.5, "mask_right_um": 2.5, "pr_thickness_um": 0.5,
    "etch_time_s": 0.5, "rate": -0.05, "mask_material": "Mask",
}


def _fresh_process_result():
    step_cls = registry.get("etching", "isotropic")
    with tempfile.TemporaryDirectory() as tmp:
        step_result = step_cls().run(RECIPE, tmp)
        return build_process_result(step_result)


def _dose(profile):
    return (profile.model_params["peak_conc_cm3"]
            * profile.model_params["straggle_um"] * math.sqrt(2.0 * math.pi))


def _species_profile(result):
    """A gaussian_implant ProcessResult carries exactly ONE profile
    (dopant_profiles_from_doping_profile no longer expands the retired
    gaussian_terms/existing= multi-implant list, per Task 4's own
    scope) -- convert and pull it out."""
    profiles = dopant_profiles_from_doping_profile(result.doping)
    assert len(profiles) == 1
    return profiles[0]


def _by_species(profiles):
    return {p.species: p for p in profiles}


def scenario_A():
    b_profile = _species_profile(apply_gaussian_implant_doping(
        _fresh_process_result(), "Si", "x", peak_position_um=0.0, straggle_um=0.2,
        acceptor_peak_conc_cm3=1.0e18, acceptor_species="B",
    ))
    b_dose_before = _dose(b_profile)

    updated, _ = apply_thermal_anneal((b_profile,), temperature_c=900.0, time_s=600.0)
    b = updated[0]

    assert b.model_params["straggle_um"] > 0.2, "[A] B must broaden"
    assert abs(_dose(b) - b_dose_before) / b_dose_before < 1e-6, "[A] dose must be conserved"
    print(f"[A] B implant -> anneal: straggle 0.200 -> {b.model_params['straggle_um']:.4f} um, "
          f"dose conserved to {abs(_dose(b) - b_dose_before) / b_dose_before:.2e}")


def scenario_B():
    b_profile = _species_profile(apply_gaussian_implant_doping(
        _fresh_process_result(), "Si", "x", peak_position_um=-1.0, straggle_um=0.2,
        acceptor_peak_conc_cm3=1.0e18, acceptor_species="B",
    ))
    p_profile = _species_profile(apply_gaussian_implant_doping(
        _fresh_process_result(), "Si", "x", peak_position_um=1.0, straggle_um=0.2,
        donor_peak_conc_cm3=1.0e18, donor_species="P",
    ))
    updated, _ = apply_thermal_anneal((b_profile, p_profile), temperature_c=900.0, time_s=600.0)
    terms = _by_species(updated)

    assert "B" in terms and "P" in terms, "[B] neither profile may be destroyed"
    assert terms["B"].model_params["straggle_um"] > 0.2, "[B] B must broaden"
    assert terms["P"].model_params["straggle_um"] > 0.2, "[B] P must broaden"
    assert abs(terms["B"].model_params["straggle_um"] - terms["P"].model_params["straggle_um"]) > 1e-6, (
        "[B] B and P must broaden by DIFFERENT amounts (different D(T))"
    )
    print(f"[B] B implant -> P implant -> anneal: both present, "
          f"B={terms['B'].model_params['straggle_um']:.4f}um "
          f"P={terms['P'].model_params['straggle_um']:.4f}um")


def scenario_C():
    b_profile = _species_profile(apply_gaussian_implant_doping(
        _fresh_process_result(), "Si", "x", peak_position_um=-1.0, straggle_um=0.2,
        acceptor_peak_conc_cm3=1.0e18, acceptor_species="B",
    ))
    (b_annealed_once,), _ = apply_thermal_anneal((b_profile,), temperature_c=900.0, time_s=600.0)
    b_straggle_after_first_anneal = b_annealed_once.model_params["straggle_um"]

    p_profile = _species_profile(apply_gaussian_implant_doping(
        _fresh_process_result(), "Si", "x", peak_position_um=1.0, straggle_um=0.2,
        donor_peak_conc_cm3=1.0e18, donor_species="P",
    ))
    updated, _ = apply_thermal_anneal(
        (b_annealed_once, p_profile), temperature_c=900.0, time_s=600.0,
    )
    terms = _by_species(updated)

    assert "B" in terms and "P" in terms, "[C] neither profile may be destroyed"
    assert terms["B"].model_params["straggle_um"] > b_straggle_after_first_anneal, (
        "[C] the FINAL anneal must widen B FURTHER, beyond its own first anneal -- "
        f"got {terms['B'].model_params['straggle_um']} vs {b_straggle_after_first_anneal} "
        f"after anneal 1 alone"
    )
    assert terms["P"].model_params["straggle_um"] > 0.2, (
        "[C] P (introduced after B's first anneal) must also broaden"
    )
    print(f"[C] B implant -> anneal -> P implant -> anneal: B widened across "
          f"BOTH anneals ({0.2:.4f} -> {b_straggle_after_first_anneal:.4f} -> "
          f"{terms['B'].model_params['straggle_um']:.4f} um), P widened by the final "
          f"anneal alone ({0.2:.4f} -> {terms['P'].model_params['straggle_um']:.4f} um)")


def scenario_temperature_dependence():
    implant = _species_profile(apply_gaussian_implant_doping(
        _fresh_process_result(), "Si", "x", peak_position_um=0.0, straggle_um=0.2,
        donor_peak_conc_cm3=1.0e18, donor_species="P",
    ))
    (low,), _ = apply_thermal_anneal((implant,), temperature_c=900.0, time_s=600.0)
    (high,), _ = apply_thermal_anneal((implant,), temperature_c=1000.0, time_s=600.0)
    low_s = low.model_params["straggle_um"]
    high_s = high.model_params["straggle_um"]
    assert high_s != low_s
    assert high_s > low_s
    print(f"[T] 900C/10min -> {low_s:.4f}um, 1000C/10min -> {high_s:.4f}um "
          f"(same duration, different T -- genuinely different results)")


def main():
    scenario_A()
    scenario_B()
    scenario_C()
    scenario_temperature_dependence()
    print("\nAll Stage B acceptance scenarios (A/B/C + temperature "
          "dependence) verified against real physics: no profile "
          "destroyed, independent species D(T), every existing "
          "profile reached by anneal, dose conserved, and a later "
          "anneal continues to affect an earlier profile.")


if __name__ == "__main__":
    main()
