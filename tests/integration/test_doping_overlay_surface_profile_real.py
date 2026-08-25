#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_material_surface_profile() must track the REAL local surface height,
not a global bounding box -- pinned with an etched-trench mesh where
the Si top genuinely differs by ~1um between the mesa and the trench
floor (see docs/investigation_log.md, "renderer draws doping color
using a global bounding box").
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.etching  # noqa: F401
from tcad.process import registry
from tcad.backends.viennaps import session

assert session.is_available(), "ViennaPS must be installed for this test"

RECIPE = {
    "grid_delta_um": 0.1, "x_extent_um": 10.0, "y_extent_um": 8.0,
    "mask_spans_um": [[-1.5, 1.5]], "mask_material": "PHS",
    "pr_thickness_um": 0.5, "silicon_depth_um": 5.0,
    "rate": -1.0, "etch_time_s": 1.0,
}


def main():
    import tcad_2d_stagewise as gui
    import meshio

    tmp = tempfile.mkdtemp(prefix="tsp_")
    step_cls = registry.get("etching", "isotropic")
    result = step_cls().run(RECIPE, tmp)

    module = session.require_viennaps()
    mesh = meshio.read(result["final_mesh"])
    tri = next(c for c in mesh.cells if c.type == "triangle")
    tags = mesh.cell_data["Material"][mesh.cells.index(tri)]
    points = mesh.points
    si_tag = int(module.Material.Si)

    profile = gui.TCADApplication._material_surface_profile(
        tri.data, points, tags, si_tag, -5.0, 5.0, n_buckets=100,
    )
    assert profile, "profile must not be empty for a mesh containing Si"

    # x=-4..-2.5 is the ETCHED region (protected span is [-1.5,1.5], so
    # everything outside it was etched -1.0um deep); x=-1..1 is
    # PROTECTED (inside the mask span), still near the original surface.
    etched_tops = [seg[2] for seg in profile if -4.0 <= seg[0] <= -2.5]
    protected_tops = [seg[2] for seg in profile if -1.0 <= seg[0] <= 1.0]
    assert etched_tops and protected_tops, "expected buckets in both x ranges"

    etched_top = max(etched_tops)
    protected_top = max(protected_tops)
    print(f"Etched-region top: {etched_top:.4f}  Protected-region top: {protected_top:.4f}")
    assert protected_top - etched_top > 0.5, (
        f"the profile must show the real ~1um step between the etched "
        f"and protected regions, got {protected_top - etched_top:.4f}um "
        f"-- a global bounding box would report the SAME top for both")

    print("_material_surface_profile() tracks the real per-x surface, "
          "not a global bounding box.")


if __name__ == "__main__":
    main()
