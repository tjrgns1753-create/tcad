#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MOSFET Id-Vds output characteristic -- mirrors
test_mosfet_id_vgs_real.py's own device/geometry exactly, gate held
fixed, drain swept."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio

import tcad.process.geometry  # noqa: F401 -- registers gate_stack
from tcad.process import registry
from tcad.backends.viennaps.io import filter_mesh_materials
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import apply_implant_windows_doping
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.mesh_import import (
    derive_implant_windows_refinement, import_process_result,
)
from tcad.device.devsim.doping_mapping import apply_doping
from tcad.device.devsim.mesh_refine import graded_refine_mesh_near
from tcad.characterization.mosfet_sweep import run_mosfet_id_vds_sweep

devsim = devsim_backend.require_devsim()
import viennaps as vps  # noqa: E402

GRID = 0.05
CHANNEL = (-1.0, 1.0)
SRC = (-2.4, -1.0)
DRN = (1.0, 2.4)
X_EXTENT = 2 * DRN[1]
BACKGROUND_DOPING_CM3 = -1e17
SD_DOPING_CM3 = 1e20
GATE_OXIDE_UM = 0.02
LENGTH_SCALE_TO_CM = 1e-4
GATE_VOLTAGE = 4.0

RECIPE = {
    "grid_delta_um": GRID, "x_extent_um": X_EXTENT, "y_extent_um": 3.0,
    "silicon_depth_um": 1.0, "channel_um": list(CHANNEL), "source_um": list(SRC),
    "drain_um": list(DRN), "gate_oxide_thickness_um": GATE_OXIDE_UM,
    "gate_height_um": 0.15, "pad_height_um": 0.10,
    "dedupe_materials": ["Si", "SiO2"],
}


def main():
    step_cls = registry.get("geometry", "gate_stack")
    with tempfile.TemporaryDirectory() as tmp:
        step = step_cls()
        result = step.run(RECIPE, tmp)
        filtered = filter_mesh_materials(result["final_mesh"], [vps.Material.Si, vps.Material.SiO2])

        mesh = meshio.read(filtered)
        block = next(c for c in mesh.cells if c.type == "triangle")
        idx = mesh.cells.index(block)
        points, triangles, tags = mesh.points, block.data, mesh.cell_data["Material"][idx]

        def _dope(process_result):
            return apply_implant_windows_doping(
                process_result, region="Si", axis="x",
                background_doping_cm3=BACKGROUND_DOPING_CM3,
                windows=[
                    {"min_um": SRC[0], "max_um": SRC[1], "conc_cm3": SD_DOPING_CM3},
                    {"min_um": DRN[0], "max_um": DRN[1], "conc_cm3": SD_DOPING_CM3},
                ],
            )

        doping = _dope(build_process_result({"final_mesh": filtered, "snapshots": []})).doping
        predicates = derive_implant_windows_refinement(
            doping, points, triangles, interface_position_um=0.0, interface_axis="y",
        )
        refined_points, refined_tris, refined_tags = graded_refine_mesh_near(points, triangles, tags, predicates)
        refined_mesh = meshio.Mesh(
            points=refined_points, cells=[("triangle", refined_tris)],
            cell_data={"Material": [refined_tags]},
        )
        refined_path = f"{filtered}.refined.vtu"
        meshio.write(refined_path, refined_mesh)
        print(f"[1/4] device built + refined: {len(refined_points)} points")

        process_result = _dope(build_process_result({"final_mesh": refined_path, "snapshots": result["snapshots"]}))
        imported = import_process_result(
            process_result, mesh_name="mosfet_vds_mesh", device_name="mosfet_vds_device",
            contact_regions=["Si", "SiO2"], contact_axis="x",
            contact_axes={"SiO2": "y"}, contact_sides={"SiO2": "max"},
            interface_region_pairs=[("Si", "SiO2")],
            length_scale_to_cm=LENGTH_SCALE_TO_CM,
        )
        assert set(imported.contacts) == {"Si_xmin", "Si_xmax", "SiO2_ymax"}, imported.contacts
        apply_doping(imported.device, process_result.doping, length_scale_to_cm=LENGTH_SCALE_TO_CM)
        print(f"[2/4] imported + doped: contacts={imported.contacts}")

        drain_voltages = [0.0, 0.05, 0.1, 0.2, 0.3]
        result_iv = run_mosfet_id_vds_sweep(
            device=imported.device, si_region="Si", oxide_region="SiO2",
            source_contact="Si_xmin", drain_contact="Si_xmax", gate_contact="SiO2_ymax",
            interface_name="Si_SiO2_interface",
            drain_voltages=drain_voltages, gate_voltage=GATE_VOLTAGE,
        )
        assert len(result_iv.points) == len(drain_voltages)
        id_series = [pt.currents["Si_xmax"] for pt in result_iv.points]
        is_series = [pt.currents["Si_xmin"] for pt in result_iv.points]
        print(f"[3/4] Vds (V): {drain_voltages}")
        print(f"      Id  (A): {[f'{i:.4e}' for i in id_series]}")

        id_scale = max(abs(i) for i in id_series)
        for vd, i_source, i_drain in zip(drain_voltages, is_series, id_series):
            assert abs(i_source + i_drain) < 0.02 * id_scale, (
                f"charge not conserved at Vds={vd}: Is={i_source:.4e} Id={i_drain:.4e}"
            )
        print(f"[4/4] charge conserved (|Is+Id| < 2% of sweep scale) at every point")

        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)

    print()
    print("MOSFET Id-Vds SWEEP VERIFIED against real ViennaPS 4.6.2 + DevSim")


if __name__ == "__main__":
    main()
