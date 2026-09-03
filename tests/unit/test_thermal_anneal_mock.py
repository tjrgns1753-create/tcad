#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""apply_thermal_anneal(): dispatches each DopantProfile to its own
model's anneal handler (tcad.physics.dopant_models.ANNEAL_HANDLERS,
keyed by profile.model) -- no ViennaPS/DevSim needed.

2026-09-03 dopant-state-unification, Task 3: apply_thermal_anneal()'s
signature changed from (ProcessResult, ...) -> ProcessResult to
(Tuple[DopantProfile, ...], ...) -> (Tuple[DopantProfile, ...],
Optional[dict]), since profiles now live on WaferState, not
ProcessResult.doping (spec Sec9). Every profile gets a ThermalEvent
appended to thermal_history regardless of whether a handler exists;
today only gaussian_v1 profiles are actually widened -- everything else
is reported UNSUPPORTED_BY_MODEL, not silently skipped.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.doping import DEPTH_EVOLUTION_RESOLUTION, apply_thermal_anneal
from tcad.physics.dopant_profile import DopantProfile
from tcad.physics.values import Resolution


def _gaussian(species, polarity, peak, position, straggle):
    return DopantProfile(
        species=species, polarity=polarity,
        concentration_at=lambda x, d: peak,
        host_material="Si", model="gaussian_v1",
        model_params={
            "peak_conc_cm3": peak, "peak_position_um": position,
            "straggle_um": straggle,
        },
    )


def _uniform(species, polarity, conc):
    return DopantProfile(
        species=species, polarity=polarity,
        concentration_at=lambda x, d: conc,
        host_material="Si", model="uniform_v1",
        model_params={"net_doping_cm3": conc},
    )


def test_depth_evolution_is_a_real_importable_constant():
    assert DEPTH_EVOLUTION_RESOLUTION is Resolution.UNSUPPORTED_BY_MODEL


def test_anneal_widens_every_profile_by_its_own_species_D():
    b = _gaussian("B", "acceptor", 1.0e18, -1.0, 0.2)
    p = _gaussian("P", "donor", 1.0e18, 1.0, 0.2)

    updated, physics_status = apply_thermal_anneal((b, p), temperature_c=900.0, time_s=600.0)
    b2 = next(pr for pr in updated if pr.species == "B")
    p2 = next(pr for pr in updated if pr.species == "P")

    print(f"B: straggle 0.2 -> {b2.model_params['straggle_um']:.6f} um, "
          f"peak 1.0e18 -> {b2.model_params['peak_conc_cm3']:.6e} cm^-3")
    print(f"P: straggle 0.2 -> {p2.model_params['straggle_um']:.6f} um, "
          f"peak 1.0e18 -> {p2.model_params['peak_conc_cm3']:.6e} cm^-3")
    print(f"physics_status: {physics_status}")

    assert b2.model_params["straggle_um"] > 0.2, "B must broaden"
    assert p2.model_params["straggle_um"] > 0.2, "P must broaden"
    # B and P have DIFFERENT Ea/D0 [Christensen2003] -- at the SAME
    # T/t they must broaden by DIFFERENT amounts, not identically.
    assert abs(b2.model_params["straggle_um"] - p2.model_params["straggle_um"]) > 1e-6, (
        f"B ({b2.model_params['straggle_um']}) and P ({p2.model_params['straggle_um']}) "
        f"broadened identically -- species-independent D(T) is wrong"
    )
    assert physics_status is None, (
        "both profiles have a registered gaussian_v1 handler -- nothing UNSUPPORTED"
    )


def test_original_profile_untouched():
    implant = _gaussian("P", "donor", 1.0e18, 0.0, 0.2)
    original_peak = implant.model_params["peak_conc_cm3"]
    apply_thermal_anneal((implant,), temperature_c=900.0, time_s=600.0)
    assert implant.model_params["peak_conc_cm3"] == original_peak
    assert implant.thermal_history == (), "the input profile itself must never be mutated"


def test_unregistered_model_is_flagged_not_silently_modified():
    """No handler registered for uniform_v1 -- this project has no
    anneal/redistribution physics for it. Must be reported, never
    silently skipped and never run through gaussian_v1's formula."""
    uniform = _uniform("As", "donor", 5.0e17)
    updated, physics_status = apply_thermal_anneal((uniform,), temperature_c=900.0, time_s=600.0)
    u2 = updated[0]
    print(f"uniform_v1 (no handler): model_params unchanged = "
          f"{u2.model_params == uniform.model_params}")
    print(f"physics_status: {physics_status}")
    assert u2.model_params == uniform.model_params, (
        "no anneal handler for this model -- must not invent a shape"
    )
    assert len(u2.thermal_history) == 1, "raw thermal fact recorded even with no handler"
    assert physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"
    assert any(e["material"] == "As" for e in physics_status["entries"])


def test_900c_and_1000c_give_different_results():
    implant = _gaussian("P", "donor", 1.0e18, 0.0, 0.2)
    (low,), _ = apply_thermal_anneal((implant,), temperature_c=900.0, time_s=600.0)
    (high,), _ = apply_thermal_anneal((implant,), temperature_c=1000.0, time_s=600.0)
    low_straggle = low.model_params["straggle_um"]
    high_straggle = high.model_params["straggle_um"]
    print(f"P at 900C/600s -> straggle {low_straggle:.6f} um; "
          f"1000C/600s -> straggle {high_straggle:.6f} um")
    assert high_straggle > low_straggle


def main():
    test_depth_evolution_is_a_real_importable_constant()
    test_anneal_widens_every_profile_by_its_own_species_D()
    test_original_profile_untouched()
    test_unregistered_model_is_flagged_not_silently_modified()
    test_900c_and_1000c_give_different_results()
    print("apply_thermal_anneal() dispatches each profile to its own "
          "model's registered anneal handler, widens every gaussian_v1 "
          "profile by its own species' real D(T) independently, flags "
          "(never silently skips or misapplies) an unregistered model, "
          "and 900C != 1000C.")


if __name__ == "__main__":
    main()
