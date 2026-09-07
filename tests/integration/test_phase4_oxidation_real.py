#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 4 real-backend verification: run both oxidation models against
the actually-installed ViennaPS 4.6.2 on a small grid -- Thermal
Oxidation (CORE, fin-style, no mask) and LOCOS (ADVANCED/OPTIONAL,
mask_material set).

2026-09-08: LOCOS split out of ThermalOxidation into its own
ProcessStep/registry entry ("oxidation", "locos") -- see
tcad/process/oxidation/locos.py. This test used to run both variants
through the SAME class (mask_material was the only thing telling them
apart); it now looks each variant up under its own registry name,
which is what this split's own registry/GUI separation claims.
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
    "thermal_fin_style_no_mask": ("thermal", {}),
    "locos_style_with_mask": ("locos", {"mask_material": "Mask"}),
}


def main():
    for variant_name, (model_name, overrides) in VARIANTS.items():
        recipe = {**BASE_RECIPE, **overrides}
        step_cls = registry.get("oxidation", model_name)

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
    print("THERMAL OXIDATION (CORE) + LOCOS (ADVANCED) BOTH RAN AGAINST REAL VIENNAPS 4.6.2 SUCCESSFULLY")


if __name__ == "__main__":
    main()
