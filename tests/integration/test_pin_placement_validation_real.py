#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Coordinate -> mesh boundary resolution against a REAL ViennaPS Si/SiO2 mesh:
a valid point on Si's own external boundary, a point outside the mesh, a point on
the SiO2 external (SiO2/vacuum) surface, and a point deep in Si bulk.

Fixture provenance: DIRECT_EXPLICIT_GEOMETRY -- an explicit initial Si/SiO2
stack (see tests/integration/_explicit_oxide_fixture.py). The SiO2 is stated as
an input geometry. It is NOT an oxidation result, NOT a deposited oxide, and
this test says nothing about oxidation kinetics or Si consumption. It checks
contact/pin classification on a real Si/SiO2 mesh boundary only.

All four pin coordinates are computed from the exported mesh (independent
edge-ownership code, not the classifier under test); none is a remembered
number from an earlier run, and no tolerance is widened to obtain a reason.
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
    validate_pin_placement, PinPlacementError,
    REASON_OUTSIDE_MESH, REASON_ON_INSULATOR, REASON_INTERIOR_BULK,
)

import _explicit_oxide_fixture as fixture

# Explicit INPUT geometry of the stack (requested values, not measurements).
X_EXTENT_UM = 10.0
Y_EXTENT_UM = 8.0
SILICON_DEPTH_UM = 5.0
OXIDE_TOP_UM = 0.4            # 2 grid cells; a stated input, not a grown thickness
GRID = 0.2
TOLERANCE_UM = 0.05           # validate_pin_placement()'s default, passed explicitly
CONTACTABLE = {"Si"}


def _pin(computed, role):
    return Pin(name=computed.name, role=role, x_um=computed.x_um, y_um=computed.y_um)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        stack = fixture.build_explicit_si_sio2_stack(
            tmp, x_extent_um=X_EXTENT_UM, y_extent_um=Y_EXTENT_UM,
            silicon_depth_um=SILICON_DEPTH_UM, oxide_top_um=OXIDE_TOP_UM, grid_delta_um=GRID)
        print(fixture.describe(stack))
        m = stack.measured
        assert stack.forbidden_call_counts == {"Oxidation": 0, "Process": 0}, stack.forbidden_call_counts
        assert set(m["materials"]) == {"Si", "SiO2"}, m["materials"]
        assert m["shared_edges"].get("Si|SiO2", 0) >= 1, m["shared_edges"]
        assert m["duplicate_coordinate_points"] == 0, m["duplicate_coordinate_points"]
        print(f"      materials={m['materials']} shared Si|SiO2 edges={m['shared_edges']['Si|SiO2']} "
              f"duplicate coordinates={m['duplicate_coordinate_points']} "
              f"oxidation/Process calls={stack.forbidden_call_counts}")

        pins = fixture.compute_pins(stack, tolerance_um=TOLERANCE_UM)
        process_result = stack.process_result
        for key in ("si_bottom", "outside", "sio2_top", "si_bulk"):
            p = pins[key]
            print(f"      computed from the exported mesh: {p.name:10s} wafer ({p.x_um:.4f}, {p.y_um:.4f}) "
                  f"[domain x={p.x_domain_um:.4f}] -- {p.basis}")
            print(f"        evidence: {p.evidence}")
        # the SiO2 pin is on the EXTERNAL SiO2/vacuum boundary, not the internal Si/SiO2 interface
        sio2 = pins["sio2_top"].evidence
        assert sio2["edge_owner_material"] == "SiO2" and sio2["edge_owner_triangles"] == 1
        assert sio2["is_internal_si_sio2_interface"] is False
        assert sio2["height_above_exported_interface_um"] > 2.0 * TOLERANCE_UM

        # [1/4] The wafer's own real bottom boundary of Si.
        region = validate_pin_placement(process_result, _pin(pins["si_bottom"], "Body"),
                                        CONTACTABLE, tolerance_um=TOLERANCE_UM)
        assert region == "Si", f"expected Si, got {region}"
        print(f"[1/4] valid pin on Si's external boundary resolves: region={region}")

        # [2/4] Outside the mesh: explicit margin beyond the exported bbox.
        try:
            validate_pin_placement(process_result, _pin(pins["outside"], "Drain"),
                                   CONTACTABLE, tolerance_um=TOLERANCE_UM)
            assert False, "expected PinPlacementError for a point outside the mesh"
        except PinPlacementError as exc:
            assert exc.reason == REASON_OUTSIDE_MESH, exc.reason
            print(f"[2/4] outside-mesh pin correctly rejected: {exc.detail}")

        # [3/4] On the SiO2 external surface, which is NOT in contactable_materials.
        try:
            validate_pin_placement(process_result, _pin(pins["sio2_top"], "Gate"),
                                   CONTACTABLE, tolerance_um=TOLERANCE_UM)
            assert False, "expected PinPlacementError for a point on SiO2"
        except PinPlacementError as exc:
            assert exc.reason == REASON_ON_INSULATOR, exc.reason
            print(f"[3/4] on-insulator pin correctly rejected: {exc.detail}")

        # [4/4] Deep inside Si bulk, far from every external boundary.
        try:
            validate_pin_placement(process_result, _pin(pins["si_bulk"], "Body"),
                                   CONTACTABLE, tolerance_um=TOLERANCE_UM)
            assert False, "expected PinPlacementError for a point deep in Si bulk"
        except PinPlacementError as exc:
            assert exc.reason == REASON_INTERIOR_BULK, exc.reason
            print(f"[4/4] interior-bulk pin correctly rejected: {exc.detail}")

    assert list(devsim.get_device_list()) == [], devsim.get_device_list()
    assert list(devsim.get_mesh_list()) == [], devsim.get_mesh_list()
    print("      DevSim: 0 devices, 0 meshes left")
    print()
    print("COORDINATE -> MESH BOUNDARY RESOLUTION VERIFIED on an explicit initial Si/SiO2 stack "
          "(DIRECT_EXPLICIT_GEOMETRY; not an oxidation result)")


if __name__ == "__main__":
    main()
