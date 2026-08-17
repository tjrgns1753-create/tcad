#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Geometric (non-conformal) trench deposition — real ViennaPS 4.6.2,
through the actual production entry point
(registry.get("deposition","geometric_trench").run()).

Guards two things the module docstring documents but that Phase 3's
smoke test doesn't check: (1) the thickness profile actually follows
the a/b/n/bottomMed formula read from ViennaPS's own C++ source
(psGeometricDistributionModels.hpp's TrenchDistribution), not just
"doesn't crash", and (2) the optional `material` recipe key gives the
deposit its own distinct, separately-measurable material tag.

Formula (verified against source, not guessed):
    thickness = bottomMed   if |y + reference_depth| < gridDelta
    thickness = a*(1-|y|/reference_depth)^n + b   otherwise
peaking at y=0 (this project's wafer-surface datum) and decaying with
|y| in either direction.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio

import tcad.process.deposition  # noqa: F401 -- registers the models
from tcad.backends.viennaps import session
from tcad.process import registry

assert session.is_available(), "ViennaPS must be installed for this test"

MASK_HEIGHT_UM = 0.5  # == pr_thickness_um below; mask top sits at y=+0.5
REFERENCE_DEPTH_UM = 1.0
BOTTOM_MED_UM = 0.1
A_UM = 0.3
B_UM = 0.05
N = 2.0

RECIPE = {
    "grid_delta_um": 0.05,
    "x_extent_um": 6.0,
    "y_extent_um": 3.0,
    "mask_left_um": 2.0,
    "mask_right_um": 4.0,
    "pr_thickness_um": MASK_HEIGHT_UM,
    "reference_depth_um": REFERENCE_DEPTH_UM,
    "deposition_rate_um": 1.0,
    "bottom_med_um": BOTTOM_MED_UM,
    "a_um": A_UM,
    "b_um": B_UM,
    "n": N,
    "material": "SiO2",
}


def thickness_at(mesh, material, x_target):
    block = next((c for c in mesh.cells if c.type == "triangle"), None)
    tags = mesh.cell_data["Material"][mesh.cells.index(block)]
    top, bottom = None, None
    for tri, tag in zip(block.data, tags):
        if int(tag) != material:
            continue
        for i in tri:
            x, y = float(mesh.points[i][0]), float(mesh.points[i][1])
            if abs(round(x, 1) - x_target) < 1e-6:
                top = y if top is None else max(top, y)
                bottom = y if bottom is None else min(bottom, y)
    if top is None:
        return None
    return top - bottom


def main():
    module = session.require_viennaps()
    ox_tag = int(module.Material.SiO2)

    step_cls = registry.get("deposition", "geometric_trench")
    with tempfile.TemporaryDirectory() as tmp:
        result = step_cls().run(dict(RECIPE), tmp)
        assert Path(result["final_mesh"]).exists()
        print(f"[1/3] geometric_trench.run() OK -> {result['final_mesh']}")

        mesh = meshio.read(result["final_mesh"])
        block = next((c for c in mesh.cells if c.type == "triangle"), None)
        tags = {int(t) for t in mesh.cell_data["Material"][mesh.cells.index(block)]}
        assert ox_tag in tags, (
            f"[2/3] the 'material' recipe key should give the deposit its own "
            f"distinct SiO2 tag, but tags present are {sorted(tags)}"
        )
        # Mask is also present -- confirms the deposit did NOT silently
        # absorb/replace the mask material.
        mask_tag = int(module.Material.Mask)
        assert mask_tag in tags, f"[2/3] Mask material missing entirely: {sorted(tags)}"
        print(f"[2/3] deposit has its own distinct material tag: {sorted(tags)}")

        # Field/mask-top thickness, far from the trench window, should
        # follow the power law at y=mask_top=0.5 (no floor band reached
        # here -- fresh-wafer geometry has trench_depth_um=0.0, so
        # nothing sits near y=-REFERENCE_DEPTH_UM).
        predicted = A_UM * (1.0 - abs(MASK_HEIGHT_UM) / REFERENCE_DEPTH_UM) ** N + B_UM
        far_x = round(RECIPE["x_extent_um"] / 2.0 - 0.5, 1)  # near the domain edge, outside the window
        measured = thickness_at(mesh, ox_tag, far_x)
        assert measured is not None, f"[3/3] no deposit found at x={far_x}"
        assert abs(measured - predicted) < RECIPE["grid_delta_um"] * 2, (
            f"[3/3] field thickness {measured:.4f}um vs predicted {predicted:.4f}um "
            f"(a*(1-|y|/depth)^n+b at y={MASK_HEIGHT_UM}) -- off by more than "
            f"2 grid cells"
        )
        print(f"[3/3] field thickness matches the source-verified formula: "
              f"measured={measured:.4f}um, predicted={predicted:.4f}um")

    print("GEOMETRIC TRENCH DEPOSITION TEST PASSED")


if __name__ == "__main__":
    main()
