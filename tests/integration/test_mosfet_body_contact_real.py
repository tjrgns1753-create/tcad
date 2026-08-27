#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4-terminal S/D/G/B device: Body is Si's own y-min (extra_contacts,
Task 4), biased at a fixed 0V through an Id-Vgs sweep -- KCL across
the 3 conducting terminals (Source/Drain/Body; Gate carries no DC
current, matching test_mosfet_id_vgs_real.py's own established check)."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio

import tcad.process.geometry  # noqa: F401
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
from tcad.characterization.mosfet_sweep import run_mosfet_id_vgs_sweep

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
DRAIN_VOLTAGE = 0.1

RECIPE = {
    "grid_delta_um": GRID, "x_extent_um": X_EXTENT, "y_extent_um": 3.0,
    "silicon_depth_um": 1.0, "channel_um": list(CHANNEL), "source_um": list(SRC),
    "drain_um": list(DRN), "gate_oxide_thickness_um": GATE_OXIDE_UM,
    "gate_height_um": 0.15, "pad_height_um": 0.10,
    "dedupe_materials": ["Si", "SiO2"],
}


def _build_device(tmp):
    """Build the 4-terminal Si/SiO2 gate-stack device (mesh, refinement,
    doping, import). Factored out so a fresh device can be built per
    DevSim call -- run_mosfet_id_vgs_sweep (and, by extension,
    solve_mosfet_dc_operating_point) is one-call-per-device."""
    step_cls = registry.get("geometry", "gate_stack")
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

    process_result = _dope(build_process_result({"final_mesh": refined_path, "snapshots": result["snapshots"]}))
    imported = import_process_result(
        process_result, mesh_name="mosfet_body_mesh", device_name="mosfet_body_device",
        contact_regions=["Si", "SiO2"], contact_axis="x",
        contact_axes={"SiO2": "y"}, contact_sides={"SiO2": "max"},
        extra_contacts=[{"name": "Si_ymin", "region": "Si", "axis": "y", "side": "min"}],
        interface_region_pairs=[("Si", "SiO2")],
        length_scale_to_cm=LENGTH_SCALE_TO_CM,
    )
    assert set(imported.contacts) == {"Si_xmin", "Si_xmax", "SiO2_ymax", "Si_ymin"}, imported.contacts
    apply_doping(imported.device, process_result.doping, length_scale_to_cm=LENGTH_SCALE_TO_CM)
    return imported


def main():
    from tcad.characterization.dc_operating_point import solve_mosfet_dc_operating_point

    # A separate, freshly-imported device for the DC-operating-point
    # call -- run_mosfet_id_vgs_sweep (which solve_mosfet_dc_operating_point
    # calls internally) is one-call-per-device, same as the sweep below.
    with tempfile.TemporaryDirectory() as tmp:
        imported = _build_device(tmp)

        op_point = solve_mosfet_dc_operating_point(
            device=imported.device, si_region="Si", oxide_region="SiO2",
            source_contact="Si_xmin", drain_contact="Si_xmax", gate_contact="SiO2_ymax",
            interface_name="Si_SiO2_interface",
            drain_voltage=DRAIN_VOLTAGE, gate_voltage=1.0,
            body_contact="Si_ymin", body_voltage=0.0,
        )
        assert op_point.converged is True
        assert op_point.voltages["SiO2_ymax"] == 1.0
        assert op_point.voltages["Si_xmax"] == DRAIN_VOLTAGE
        assert "Si_ymin" in op_point.currents
        print(f"[1/4] DC operating point solved directly: currents={op_point.currents}")

        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)

    with tempfile.TemporaryDirectory() as tmp:
        imported = _build_device(tmp)
        print(f"[2/4] 4-terminal device imported: {sorted(imported.contacts)}")

        gate_voltages = [0.0, 4.0, 8.0]
        result_iv = run_mosfet_id_vgs_sweep(
            device=imported.device, si_region="Si", oxide_region="SiO2",
            source_contact="Si_xmin", drain_contact="Si_xmax", gate_contact="SiO2_ymax",
            interface_name="Si_SiO2_interface",
            gate_voltages=gate_voltages, drain_voltage=DRAIN_VOLTAGE,
            body_contact="Si_ymin", body_voltage=0.0,
        )
        assert len(result_iv.points) == len(gate_voltages)
        print(f"[3/4] Id-Vgs sweep with Body fixed at 0V completed")

        for pt in result_iv.points:
            assert "Si_ymin" in pt.currents, "Body current must be read at every point"
            i_scale = max(abs(v) for v in pt.currents.values()) or 1e-30
            total = pt.currents["Si_xmin"] + pt.currents["Si_xmax"] + pt.currents["Si_ymin"]
            assert abs(total) < 0.02 * i_scale, (
                f"charge not conserved across S/D/Body at Vgs={pt.voltages['SiO2_ymax']}: "
                f"currents={pt.currents}"
            )
        print(f"[4/4] charge conserved across Source+Drain+Body at every point")

        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)

    print()
    print("4-TERMINAL S/D/G/B DEVICE VERIFIED against real ViennaPS 4.6.2 + DevSim")


if __name__ == "__main__":
    main()
