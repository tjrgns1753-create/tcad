#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 3 real-backend verification: run every registered Deposition
model against the actually-installed ViennaPS 4.6.2, on a small grid.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.deposition  # noqa: F401 -- registers all models
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
    "deposition_time_s": 0.5,
}

RECIPE_OVERRIDES = {
    "teos": {
        "sticking_probability_p1": 0.1,
        "rate_p1": 1.0,
        "order_p1": 1.0,
    },
    "teos_pecvd": {
        "sticking_probability_radical": 0.1,
        "deposition_rate_radical": 1.0,
        "deposition_rate_ion": 1.0,
        "exponent_ion": 100.0,
    },
    "selective_epitaxy": {
        "material_rates": [{"material": "Si", "rate": 1.0}],
    },
    "single_particle_cvd": {
        "rate": 0.05,
        "sticking_probability": 1.0,
    },
    "directional": {
        "direction": [0.0, 1.0, 0.0],
        "directional_velocity": 0.1,
        "mask_material": "Mask",
    },
}


def main():
    results = {}
    for model_name in registry.list_models("deposition"):
        recipe = {**BASE_RECIPE, **RECIPE_OVERRIDES[model_name]}
        step_cls = registry.get("deposition", model_name)

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

    assert set(results) == set(registry.list_models("deposition"))
    print()
    print("ALL 5 DEPOSITION MODELS RAN AGAINST REAL VIENNAPS 4.6.2 SUCCESSFULLY")


if __name__ == "__main__":
    main()
