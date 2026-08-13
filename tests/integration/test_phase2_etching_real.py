#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 2 real-backend verification: run every registered Etching model
against the actually-installed ViennaPS 4.6.2 (not a mock), on a small
grid for speed. Confirms the real API calls (constructor names,
parameter names) used in each model file are correct.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.etching  # noqa: F401 -- registers all models
from tcad.backends.viennaps import session
from tcad.process import registry

assert session.is_available(), "ViennaPS must be installed for this real-backend test"

BASE_RECIPE = {
    "grid_delta_um": 0.2,
    "x_extent_um": 4.0,
    "y_extent_um": 3.0,
    "mask_left_um": 1.5,
    "mask_right_um": 2.5,
    "pr_thickness_um": 0.5,
    "etch_time_s": 0.5,
}

RECIPE_OVERRIDES = {
    "bosch_drie": {
        "cycles": 1,
        "polymer_rate": 0.03,
        "polymer_sticking": 1.0,
        "ion_source_exponent": 500.0,
        "ion_rate": -0.02,
        "neutral_rate": -0.01,
        "neutral_sticking": 0.10,
    },
    "sf6o2": {
        "ion_flux": 12.0,
        "etchant_flux": 1800.0,
        "oxygen_flux": 100.0,
    },
    "hbr_o2": {
        "ion_flux": 12.0,
        "etchant_flux": 1800.0,
        "oxygen_flux": 100.0,
    },
    "sf6_c4f8": {
        "ion_flux": 12.0,
        "etchant_flux": 1800.0,
        "mean_energy": 100.0,
        "sigma_energy": 10.0,
    },
    "cf4_o2": {
        "ion_flux": 12.0,
        "etchant_flux": 1800.0,
        "oxygen_flux": 100.0,
        "polymer_flux": 100.0,
    },
    "fluorocarbon": {
        "ion_flux": 56.0,
        "etchant_flux": 500.0,
        "poly_flux": 100.0,
    },
    "ibe": {
        "mean_energy": 250.0,
        "plane_wafer_rate": -1.0,
    },
    "faraday_cage": {
        "mean_energy": 250.0,
        "plane_wafer_rate": -1.0,
        "cage_angle": 15.0,
    },
    "wet_etching": {
        "material_rates": [
            {"material": "Si", "rate": -0.05},
            {"material": "Mask", "rate": 0.0},
        ],
    },
    "isotropic": {
        "rate": -0.05,
        "mask_material": "Mask",
    },
    "directional": {
        "direction": [0.0, -1.0, 0.0],
        "directional_velocity": -0.1,
        "mask_material": "Mask",
    },
}


def main():
    results = {}
    for model_name in registry.list_models("etching"):
        recipe = {**BASE_RECIPE, **RECIPE_OVERRIDES[model_name]}
        step_cls = registry.get("etching", model_name)

        with tempfile.TemporaryDirectory() as tmp:
            result = step_cls().run(recipe, tmp)

            assert "final_mesh" in result and "snapshots" in result
            assert Path(result["final_mesh"]).exists(), (
                f"{model_name}: final mesh not written"
            )
            assert len(result["snapshots"]) >= 1
            for snap in result["snapshots"]:
                assert Path(snap).exists(), f"{model_name}: missing snapshot {snap}"

        results[model_name] = "OK"
        print(f"[{model_name}] real ViennaPS run OK -> {result['final_mesh']}")

    assert set(results) == set(registry.list_models("etching"))
    print()
    print(f"ALL {len(results)} ETCHING MODELS RAN AGAINST REAL VIENNAPS 4.6.2 SUCCESSFULLY")


if __name__ == "__main__":
    main()
