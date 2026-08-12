#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 4 real-backend verification: run the Thermal Oxidation model
against the actually-installed ViennaPS 4.6.2, both without and with
mask_material (fin-style vs LOCOS-style), on a small grid.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.oxidation  # noqa: F401 -- registers the model
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
    "oxidant": "Dry",
    "temperature_c": 1000.0,
    "time_hours": 0.01,
}

VARIANTS = {
    "thermal_fin_style_no_mask": {},
    "thermal_locos_style_with_mask": {"mask_material": "Mask"},
}


def main():
    step_cls = registry.get("oxidation", "thermal")

    for variant_name, overrides in VARIANTS.items():
        recipe = {**BASE_RECIPE, **overrides}

        with tempfile.TemporaryDirectory() as tmp:
            result = step_cls().run(recipe, tmp)

            assert "final_mesh" in result and "snapshots" in result
            assert Path(result["final_mesh"]).exists(), (
                f"{variant_name}: final mesh not written"
            )
            assert len(result["snapshots"]) >= 1
            for snap in result["snapshots"]:
                assert Path(snap).exists(), f"{variant_name}: missing snapshot {snap}"

        print(f"[{variant_name}] real ViennaPS run OK -> {result['final_mesh']}")

    print()
    print("THERMAL OXIDATION (fin-style + LOCOS-style) RAN AGAINST REAL VIENNAPS 4.6.2 SUCCESSFULLY")


if __name__ == "__main__":
    main()
