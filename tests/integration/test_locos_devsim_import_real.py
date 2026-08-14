#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOCOS mask-retention fix — DevSim import, real ViennaPS 4.6.2 + DevSim
2.10.1, through the actual production entry points (registry ->
ThermalOxidation.run() -> build_process_result() -> import_process_result()),
not an isolated probe.

This is the real bar the pad-oxide-first LOCOS geometry fix
(tcad/process/oxidation/thermal.py) and its matching export function
(tcad.backends.viennaps.io.save_locos_volume_mesh) both had to clear
before shipping: fixing mask retention is worthless if the resulting
mesh can't be imported into DevSim, and the earlier (superseded)
attempt to fix mask retention with a pad-oxide layer hit exactly that
wall (Si vanishing entirely from the export — see CLAUDE.md, "LOCOS
mask erosion" section, for the full investigation this test's fix
resolves).

Checks:
  1. ThermalOxidation.run() with mask_material completes without error
     and produces a mesh containing Si, SiO2, AND the mask material —
     all three, not just two (Si vanishing was the specific bug).
  2. build_process_result() (the real Process -> ProcessResult adapter,
     never LOCOS-aware itself) reads the LOCOS mesh correctly.
  3. import_process_result() (the real ProcessResult -> DevSim adapter)
     succeeds, giving all three regions and two contacts on Si.
  4. Mask retention is real (>=90%), not just "present" — the actual
     thing this fix was for.

No calibration/fabricated numbers: expected values come from the
recipe itself.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio

import tcad.process.oxidation  # noqa: F401 -- registers the model
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.mesh_import import import_process_result

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

RECIPE = {
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


def main():
    module = viennaps_session.require_viennaps()
    step_cls = registry.get("oxidation", "thermal")

    with tempfile.TemporaryDirectory() as tmp:
        step_result = step_cls().run(dict(RECIPE), tmp)
        assert Path(step_result["final_mesh"]).exists()
        print(f"[1/4] ThermalOxidation.run() (LOCOS) OK -> {step_result['final_mesh']}")

        mesh = meshio.read(step_result["final_mesh"])
        triangle_block = next((c for c in mesh.cells if c.type == "triangle"), None)
        block_index = mesh.cells.index(triangle_block)
        tags = mesh.cell_data["Material"][block_index]
        materials_present = sorted({str(module.Material(int(t))).split("'")[1] for t in tags})
        assert set(materials_present) == {"Mask", "SiO2", "Si"}, (
            f"expected all three materials present (Si must not vanish -- the "
            f"specific bug this fix addresses), got {materials_present}"
        )
        print(f"[2/4] all three materials present in export: {materials_present}")

        process_result = build_process_result(step_result)
        region_names = sorted(r.name for r in process_result.material_regions)
        assert set(region_names) == {"Mask", "SiO2", "Si"}

        imported = import_process_result(
            process_result,
            mesh_name="locos_fix_mesh",
            device_name="locos_fix_device",
            contact_regions=["Si"],
            contact_axis="x",
        )
        assert set(imported.regions) == set(region_names)
        assert len(imported.contacts) == 2, f"expected 2 contacts, got {imported.contacts}"
        print(f"[3/4] DevSim import OK -> regions={imported.regions} contacts={imported.contacts}")

        import devsim
        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)

        def tri_area(points, tri):
            p = [points[i] for i in tri]
            return abs(
                (p[1][0] - p[0][0]) * (p[2][1] - p[0][1])
                - (p[2][0] - p[0][0]) * (p[1][1] - p[0][1])
            ) / 2.0

        points = mesh.points
        mask_area = sum(
            tri_area(points, tri)
            for tri, tag in zip(triangle_block.data, tags)
            if str(module.Material(int(tag))).split("'")[1] == "Mask"
        )
        trench_width = round(RECIPE["mask_right_um"] - RECIPE["mask_left_um"], 9)
        window_half = trench_width / 2.0
        half_x = RECIPE["x_extent_um"] / 2.0
        mask_height = max(RECIPE["pr_thickness_um"], 0.1)
        expected_pre_mask_area = 2 * (half_x - window_half) * mask_height
        retention = mask_area / expected_pre_mask_area
        assert retention > 0.90, f"mask retention regressed: {retention:.4f}"
        print(f"[4/4] mask retention = {100*retention:.2f}% "
              f"(area={mask_area:.6f} of expected pre-oxidation {expected_pre_mask_area:.6f})")

    print()
    print("LOCOS MASK-RETENTION FIX: DEVSIM IMPORT VERIFIED THROUGH THE REAL "
          "PRODUCTION ENTRY POINTS (registry -> ThermalOxidation.run() -> "
          "build_process_result() -> import_process_result())")


if __name__ == "__main__":
    main()
