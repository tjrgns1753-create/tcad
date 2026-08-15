#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOCOS process-flow chaining — real ViennaPS 4.6.2, through the actual
production entry points (registry -> ThermalOxidation.run() ->
DirectionalEtch(inherited_domain=...).run()), the same way
tcad.process.flow.run_flow() chains any two steps.

Guards the fix in ThermalOxidation._make_locos_domain_chainable() and
tcad.backends.viennaps.io.register_locos_export(). Before it, chaining
ANY further step onto fresh-LOCOS geometry silently destroyed the Si
and SiO2 level sets outright (both dropping to zero points during the
chained step's own Process() call, before export was even reached), so
the chained step exported a mesh missing two of its three materials —
or, when the resulting degenerate bounding box hit the floor
mechanism's boolean intersect, hung for minutes instead.

Root cause (ViennaLS lsAdvect.hpp's own documented precondition): Advect
advects only the LAST level set, then replaces each lower one with
`lower INTERSECT last`, and requires the last to CONTAIN all the others.
Every other geometry in this project satisfies that automatically —
MakeTrench inserts the substrate last, wrapping the mask. LOCOS must
insert its mask last and unwrapped (both alternatives break
vps.Oxidation()'s own solve), so it is restored afterwards instead. See
LOCOS_CHAINING_TEST_LOG.txt for the full investigation.

Checks:
  1. The LOCOS step's OWN export is unchanged by the fix — all three
     materials, mask retention still >=90%.
  2. A chained step completes and its own export ALSO has all three
     materials with nonzero area (the actual bug).
  3. No level set was destroyed by the chained step.
  4. The chained etch is physically real, not a no-op: it removes oxide,
     and leaves the masked region's Si intact.
  5. A SECOND chained step still works, with no further fixup — the
     invariant is restored once, and Advect preserves it thereafter.

No fabricated numbers: every expectation is derived from the recipe or
compared against the step's own measured "before" state.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio

import tcad.process.etching  # noqa: F401 -- registers the models
import tcad.process.oxidation  # noqa: F401
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"

OXIDATION_RECIPE = {
    "grid_delta_um": 0.2,
    "x_extent_um": 4.0,
    "y_extent_um": 3.0,
    "mask_left_um": 1.5,
    "mask_right_um": 2.5,
    "pr_thickness_um": 0.5,
    "oxidant": "Dry",
    "temperature_c": 1000.0,
    "time_hours": 0.02,
    "mask_material": "Mask",
}

ETCH_RECIPE = {
    "direction": [0, -1, 0],
    "directional_velocity": -0.05,
    "etch_time_s": 1.0,
    "mask_material": "Mask",
}


def areas_by_material(mesh_path):
    """{material tag: total triangle area} from a written mesh."""
    mesh = meshio.read(str(mesh_path))
    block = next((c for c in mesh.cells if c.type == "triangle"), None)
    assert block is not None, f"{mesh_path} has no triangles at all"
    tags = mesh.cell_data["Material"][mesh.cells.index(block)]
    areas = {}
    for tri, tag in zip(block.data, tags):
        p = mesh.points[tri]
        a = abs((p[1, 0] - p[0, 0]) * (p[2, 1] - p[0, 1])
                - (p[2, 0] - p[0, 0]) * (p[1, 1] - p[0, 1])) / 2.0
        areas[int(tag)] = areas.get(int(tag), 0.0) + a
    return areas


def main():
    module = viennaps_session.require_viennaps()
    si_tag = int(module.Material.Si)
    oxide_tag = int(module.Material.SiO2)
    mask_tag = int(getattr(module.Material, OXIDATION_RECIPE["mask_material"]))
    expected = {si_tag, oxide_tag, mask_tag}

    # The mask's own pre-oxidation area, straight from the recipe's
    # geometry -- not a magic number.
    window_um = OXIDATION_RECIPE["mask_right_um"] - OXIDATION_RECIPE["mask_left_um"]
    mask_height_um = max(OXIDATION_RECIPE["pr_thickness_um"], 0.1)
    mask_area_initial = (OXIDATION_RECIPE["x_extent_um"] - window_um) * mask_height_um

    with tempfile.TemporaryDirectory() as tmp:
        # ---- step 1: LOCOS oxidation, the real production entry point ----
        step1 = registry.get("oxidation", "thermal")()
        result1 = step1.run(dict(OXIDATION_RECIPE), str(Path(tmp) / "step1"))
        areas1 = areas_by_material(result1["final_mesh"])

        assert set(areas1) == expected, (
            f"[1/5] LOCOS step's own export should have all 3 materials "
            f"{sorted(expected)}, got {sorted(areas1)}"
        )
        retention = areas1[mask_tag] / mask_area_initial
        assert retention >= 0.90, (
            f"[1/5] mask retention regressed to {retention:.1%} "
            f"({areas1[mask_tag]:.5f} of {mask_area_initial:.5f})"
        )
        print(f"[1/5] LOCOS step's own export unchanged by the fix: "
              f"3 materials, mask retention {retention:.2%}")

        # ---- step 2: chain a real, unrelated step onto it ----
        etch_cls = registry.get("etching", "directional")
        step2 = etch_cls(inherited_domain=step1.last_domain)
        result2 = step2.run(dict(ETCH_RECIPE), str(Path(tmp) / "step2"))
        areas2 = areas_by_material(result2["final_mesh"])

        assert set(areas2) == expected, (
            f"[2/5] chained step's export is missing materials: expected "
            f"{sorted(expected)}, got {sorted(areas2)} -- this is the bug "
            f"this test exists for"
        )
        for tag, area in areas2.items():
            assert area > 0.0, f"[2/5] material {tag} exported with zero area"
        print(f"[2/5] chained step's export has all 3 materials: "
              f"{ {k: round(v, 5) for k, v in sorted(areas2.items())} }")

        # ---- 3: nothing was destroyed in the domain itself ----
        points = [ls.getNumberOfPoints() for ls in step2.last_domain.getLevelSets()]
        assert all(p > 0 for p in points), (
            f"[3/5] a level set was destroyed by the chained step: {points}"
        )
        print(f"[3/5] every level set survived the chained step: {points} points")

        # ---- 4: the chained etch actually did something physical ----
        assert areas2[oxide_tag] < areas1[oxide_tag], (
            f"[4/5] the chained etch removed no oxide at all "
            f"({areas1[oxide_tag]:.5f} -> {areas2[oxide_tag]:.5f}); a fix that "
            f"preserves materials by making the step a no-op is not a fix"
        )
        # The etch is shallower than the pad oxide covering the window, so
        # it cannot reach Si yet. (This model has NO material selectivity
        # -- see etching/directional.py's docstring; Si survives here
        # purely because oxide is still in the way.)
        assert abs(areas2[si_tag] - areas1[si_tag]) < 1e-3, (
            f"[4/5] Si changed ({areas1[si_tag]:.5f} -> {areas2[si_tag]:.5f}) "
            f"though the etch is shallower than the oxide above it"
        )
        print(f"[4/5] chained etch is physically real: oxide "
              f"{areas1[oxide_tag]:.5f} -> {areas2[oxide_tag]:.5f}, Si intact")

        # ---- 5: a SECOND chained step, with no further fixup ----
        step3 = etch_cls(inherited_domain=step2.last_domain)
        result3 = step3.run(dict(ETCH_RECIPE), str(Path(tmp) / "step3"))
        areas3 = areas_by_material(result3["final_mesh"])

        assert set(areas3) == expected, (
            f"[5/5] second chained step lost materials: {sorted(areas3)}"
        )
        assert areas3[oxide_tag] < areas2[oxide_tag], (
            f"[5/5] second chained etch removed no oxide "
            f"({areas2[oxide_tag]:.5f} -> {areas3[oxide_tag]:.5f})"
        )
        print(f"[5/5] second chained step also OK, no further fixup needed: "
              f"oxide {areas2[oxide_tag]:.5f} -> {areas3[oxide_tag]:.5f}")

    print("LOCOS CHAINING TEST PASSED")


if __name__ == "__main__":
    main()
