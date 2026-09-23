#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CAD-style negative tests that need a real Si/SiO2 mesh: a Drain placed on the
SiO2 external surface (invalid contact material), a Gate placed outside the
mesh, and a DevSim import with no contact specification.

Fixture provenance: DIRECT_EXPLICIT_GEOMETRY -- an explicit initial Si/SiO2
stack (see tests/integration/_explicit_oxide_fixture.py). The SiO2 is stated as
an input geometry. It is NOT an oxidation result, NOT a deposited oxide, and
this test says nothing about oxidation kinetics or Si consumption. The
purpose is contact/pin classification on a real Si/SiO2 mesh boundary.

Every pin coordinate is computed from the exported mesh; none is a remembered
number from an earlier run.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tcad.backends.viennaps import session
from tcad.device.devsim import backend as devsim_backend

assert session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

devsim = devsim_backend.require_devsim()

from tcad.mesh.pin import Pin
from tcad.device.devsim.contact_probe import (
    validate_pin_placement, PinPlacementError, REASON_ON_INSULATOR, REASON_OUTSIDE_MESH,
)
from tcad.device.devsim.mesh_import import import_process_result

import _explicit_oxide_fixture as fixture

# Explicit INPUT geometry of the stack (requested values, not measurements).
X_EXTENT_UM = 10.0
Y_EXTENT_UM = 8.0
SILICON_DEPTH_UM = 5.0
OXIDE_TOP_UM = 0.4            # 2 grid cells; a stated input, not a grown thickness
GRID = 0.2
TOLERANCE_UM = 0.05           # validate_pin_placement()'s default, passed explicitly
CONTACTABLE = {"Si"}


def main():
    with tempfile.TemporaryDirectory() as tmp:
        stack = fixture.build_explicit_si_sio2_stack(
            tmp, x_extent_um=X_EXTENT_UM, y_extent_um=Y_EXTENT_UM,
            silicon_depth_um=SILICON_DEPTH_UM, oxide_top_um=OXIDE_TOP_UM, grid_delta_um=GRID)
        print(fixture.describe(stack))
        assert stack.forbidden_call_counts == {"Oxidation": 0, "Process": 0}, stack.forbidden_call_counts
        assert set(stack.materials) == {"Si", "SiO2"}, stack.materials
        assert stack.measured["shared_edges"].get("Si|SiO2", 0) >= 1, stack.measured["shared_edges"]
        region_names = {r.name for r in stack.process_result.material_regions}
        assert region_names == {"Si", "SiO2"}, region_names

        pins = fixture.compute_pins(stack, tolerance_um=TOLERANCE_UM)
        process_result = stack.process_result

        # [1/3] Drain on the SiO2 EXTERNAL top boundary (SiO2/vacuum), not the internal interface.
        p = pins["sio2_top"]
        assert p.evidence["edge_owner_material"] == "SiO2" and p.evidence["edge_owner_triangles"] == 1
        assert p.evidence["is_internal_si_sio2_interface"] is False
        print(f"      Drain pin ({p.x_um:.4f}, {p.y_um:.4f}) wafer um = {p.basis}; {p.evidence}")
        drain_on_oxide = Pin(name="Drain", role="Drain", x_um=p.x_um, y_um=p.y_um)
        try:
            validate_pin_placement(process_result, drain_on_oxide, CONTACTABLE, tolerance_um=TOLERANCE_UM)
            assert False, "expected PinPlacementError for Drain on SiO2"
        except PinPlacementError as exc:
            assert exc.reason == REASON_ON_INSULATOR, exc.reason
            print(f"[1/3] Drain-on-SiO2 correctly rejected: {exc.detail}")

        # [2/3] Gate outside the mesh: explicit margin beyond the exported mesh's bbox.
        p = pins["outside"]
        print(f"      Gate pin ({p.x_um:.4f}, {p.y_um:.4f}) wafer um = {p.basis}")
        gate_outside = Pin(name="Gate", role="Gate", x_um=p.x_um, y_um=p.y_um)
        try:
            validate_pin_placement(process_result, gate_outside, CONTACTABLE, tolerance_um=TOLERANCE_UM)
            assert False, "expected PinPlacementError for Gate outside the mesh"
        except PinPlacementError as exc:
            assert exc.reason == REASON_OUTSIDE_MESH, exc.reason
            print(f"[2/3] Gate-outside-mesh correctly rejected: {exc.detail}")

        # [3/3] Zero contacts -> the import succeeds and produces no contacts (a caller must
        # check that before attempting a solve; no solve is run here). The Si/SiO2 interface
        # is requested explicitly and must really exist in the DevSim device.
        imported = None
        try:
            imported = import_process_result(
                process_result, mesh_name="no_contact_mesh", device_name="no_contact_device",
                interface_region_pairs=[("Si", "SiO2")],
            )
            assert imported.contacts == [], imported.contacts
            assert set(imported.regions) == {"Si", "SiO2"}, imported.regions
            assert imported.interfaces == ["Si_SiO2_interface"], imported.interfaces
            assert list(devsim.get_contact_list(device=imported.device)) == []
            assert set(devsim.get_region_list(device=imported.device)) == {"Si", "SiO2"}
            assert list(devsim.get_interface_list(device=imported.device)) == ["Si_SiO2_interface"]
            nodes = {r: len(devsim.get_node_model_values(device=imported.device, region=r, name="x"))
                     for r in ("Si", "SiO2")}
            assert all(n > 0 for n in nodes.values()), nodes
            print(f"[3/3] zero-contact import correctly produces no contacts "
                  f"(contacts={imported.contacts}); regions={imported.regions} "
                  f"interfaces={imported.interfaces} nodes={nodes}; no solve was run")
        finally:
            if imported is not None:
                devsim.delete_device(device=imported.device)
                devsim.delete_mesh(mesh=imported.mesh)

    assert list(devsim.get_device_list()) == [], devsim.get_device_list()
    assert list(devsim.get_mesh_list()) == [], devsim.get_mesh_list()
    print("      DevSim cleanup: 0 devices, 0 meshes left")
    print()
    print("CAD-STYLE NEGATIVE VALIDATION VERIFIED on an explicit initial Si/SiO2 stack "
          "(DIRECT_EXPLICIT_GEOMETRY; not an oxidation result)")


if __name__ == "__main__":
    main()
