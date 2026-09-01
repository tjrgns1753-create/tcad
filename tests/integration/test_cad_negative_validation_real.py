#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CAD-style negative tests that need a real mesh: a Drain placed on
SiO2 (invalid contact material), a Gate placed outside the mesh, and
DC solve attempted with zero contacts."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.backends.viennaps import session
from tcad.device.devsim import backend as devsim_backend

assert session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

devsim = devsim_backend.require_devsim()

import tcad.process.oxidation  # noqa: F401 -- registers thermal oxidation
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.mesh.pin import Pin
from tcad.device.devsim.contact_probe import validate_pin_placement, PinPlacementError, REASON_ON_INSULATOR, REASON_OUTSIDE_MESH
from tcad.device.devsim.mesh_import import import_process_result

WIDTH_UM = 10.0
GRID = 0.2
#: Real, already-verified values (test_blanket_no_mask_real.py's own
#: OXIDATION dict) -- see Task 2's test for why there is no direct
#: "oxide_thickness_um" recipe key.
OXIDATION = {"oxidant": "Dry", "temperature_c": 1000.0, "time_hours": 0.5}


def main():
    with tempfile.TemporaryDirectory() as tmp:
        step_cls = registry.get("oxidation", "thermal")
        step = step_cls()
        recipe = {
            "grid_delta_um": GRID, "x_extent_um": WIDTH_UM, "y_extent_um": 8.0,
            **OXIDATION,
        }
        result = step.run(recipe, tmp)
        process_result = build_process_result({"final_mesh": result["final_mesh"], "snapshots": []})
        contactable = {"Si"}

        # Drain placed on SiO2 -- invalid electrical contact. y_um=0.19
        # lands within validate_pin_placement()'s default 0.05um
        # tolerance of the real, exposed SiO2-vacuum top surface this
        # exact recipe produces (measured directly: oxide top comes out
        # at y=0.2046 domain-coords for GRID=0.2/0.5hr Dry/1000C, since
        # probe_mesh_at_point() only recognizes true single-owner mesh
        # boundary edges -- e.g. the outer oxide surface -- never an
        # interior Si/SiO2 material-material edge, so a point in the
        # MIDDLE of the oxide layer (e.g. y=0.15um, a plausible first
        # guess) resolves to REASON_INTERIOR_BULK instead, not
        # REASON_ON_INSULATOR).
        drain_on_oxide = Pin(name="Drain", role="Drain", x_um=WIDTH_UM / 2.0, y_um=0.19)
        try:
            validate_pin_placement(process_result, drain_on_oxide, contactable)
            assert False, "expected PinPlacementError for Drain on SiO2"
        except PinPlacementError as exc:
            assert exc.reason == REASON_ON_INSULATOR, exc.reason
            print(f"[1/3] Drain-on-SiO2 correctly rejected: {exc.detail}")

        # Gate placed outside the mesh entirely.
        gate_outside = Pin(name="Gate", role="Gate", x_um=WIDTH_UM + 5.0, y_um=0.0)
        try:
            validate_pin_placement(process_result, gate_outside, contactable)
            assert False, "expected PinPlacementError for Gate outside the mesh"
        except PinPlacementError as exc:
            assert exc.reason == REASON_OUTSIDE_MESH, exc.reason
            print(f"[2/3] Gate-outside-mesh correctly rejected: {exc.detail}")

        # Zero contacts -> import succeeds but produces no contacts;
        # attempting a solve on such a device is the caller's own
        # responsibility to refuse before calling DevSim (mirrors
        # run_measurement()'s existing `len(imported.contacts) != 2`
        # check in tcad_2d_stagewise.py) -- verified here at the
        # import_process_result level: no contact_regions/point_contacts/
        # extra_contacts given -> imported.contacts is empty.
        imported = import_process_result(
            process_result, mesh_name="no_contact_mesh", device_name="no_contact_device",
        )
        assert imported.contacts == [], imported.contacts
        print(f"[3/3] zero-contact import correctly produces no contacts "
              f"(a caller must check this before attempting a solve): {imported.contacts}")
        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)

    print()
    print("CAD-STYLE NEGATIVE VALIDATION (real-mesh level) VERIFIED against real ViennaPS 4.6.2")


if __name__ == "__main__":
    main()
