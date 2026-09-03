#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ANNEAL_HANDLERS: the per-model anneal dispatch registry -- gaussian_v1
is registered directly (anneal_profile itself), no other model has an
anneal handler yet (this project has no anneal physics for uniform_v1/
step_junction_v1/implant_windows_v1)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def test_gaussian_v1_is_the_only_registered_handler():
    from tcad.physics.dopant_models import ANNEAL_HANDLERS
    print(f"registered anneal handlers: {sorted(ANNEAL_HANDLERS)}")
    assert set(ANNEAL_HANDLERS) == {"gaussian_v1"}


def test_dispatch_widens_gaussian_and_flags_unregistered_model():
    from tcad.physics.dopant_profile import DopantProfile
    from tcad.physics.doping import apply_thermal_anneal

    gaussian = DopantProfile(
        species="B", polarity="acceptor",
        concentration_at=lambda x, d: 1e18,
        host_material="Si", model="gaussian_v1",
        model_params={"peak_conc_cm3": 1e18, "peak_position_um": 0.0, "straggle_um": 0.2},
    )
    no_model = DopantProfile(
        species="As", polarity="donor",
        concentration_at=lambda x, d: 5e17,
        host_material="Si", model="uniform_v1", model_params={"net_doping_cm3": 5e17},
    )
    updated, physics_status = apply_thermal_anneal((gaussian, no_model), 900.0, 600.0)

    g2 = next(p for p in updated if p.species == "B")
    u2 = next(p for p in updated if p.species == "As")
    print(f"B (gaussian_v1) straggle {gaussian.model_params['straggle_um']:.4f} -> "
          f"{g2.model_params['straggle_um']:.4f} um")
    print(f"As (uniform_v1) model_params unchanged: {u2.model_params == no_model.model_params}")
    print(f"physics_status: {physics_status}")

    assert g2.model_params["straggle_um"] > gaussian.model_params["straggle_um"], (
        "gaussian_v1 profile must actually widen"
    )
    assert len(g2.thermal_history) == 1 and g2.thermal_history[0].temperature_c == 900.0
    assert u2.model_params == no_model.model_params, "unregistered model must NOT be modified"
    assert len(u2.thermal_history) == 1, "raw thermal fact recorded even with no handler"
    assert physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"
    assert any(e["material"] == "As" for e in physics_status["entries"])
    assert not any(e["material"] == "B" for e in physics_status["entries"])


def main():
    test_gaussian_v1_is_the_only_registered_handler()
    test_dispatch_widens_gaussian_and_flags_unregistered_model()
    print("ANNEAL_HANDLERS registers gaussian_v1 only; apply_thermal_anneal "
          "dispatches per-profile, widening gaussian_v1 profiles and "
          "flagging (never silently skipping) any other model as "
          "UNSUPPORTED_BY_MODEL, while always recording the raw thermal "
          "event regardless of whether a handler exists.")


if __name__ == "__main__":
    main()
