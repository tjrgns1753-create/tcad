#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Coordinate -> mesh boundary resolution against a REAL ViennaPS mesh:
a valid point on Si's own boundary, a point outside the mesh, a point
on SiO2 (insulator), and a point deep in Si bulk (no boundary nearby)."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.backends.viennaps import session
from tcad.device.devsim import backend as devsim_backend

assert session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

import tcad.process.oxidation  # noqa: F401 -- registers thermal oxidation
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.mesh.pin import Pin
from tcad.device.devsim.contact_probe import (
    validate_pin_placement, PinPlacementError,
    REASON_OUTSIDE_MESH, REASON_ON_INSULATOR, REASON_INTERIOR_BULK,
)

WIDTH_UM = 10.0
GRID = 0.2
#: Real, already-verified values (tests/integration/test_blanket_no_mask_real.py's
#: own OXIDATION dict) -- oxide THICKNESS is an output of oxidant/
#: temperature/time, not a direct recipe input; there is no
#: "oxide_thickness_um" key on this process step.
OXIDATION = {"oxidant": "Dry", "temperature_c": 1000.0, "time_hours": 0.5}


def _oxidized_si_result(tmp):
    """A real thermal oxidation on a fresh wafer: Si body + a thin SiO2
    cap on top -- a real 2-material mesh with a real insulator, no
    hand-built geometry. No mask_material key -> the fin-style (blanket,
    no-mask) branch, not LOCOS."""
    step_cls = registry.get("oxidation", "thermal")
    step = step_cls()
    recipe = {
        "grid_delta_um": GRID, "x_extent_um": WIDTH_UM, "y_extent_um": 8.0,
        **OXIDATION,
    }
    result = step.run(recipe, tmp)
    return build_process_result({"final_mesh": result["final_mesh"], "snapshots": []})


def main():
    with tempfile.TemporaryDirectory() as tmp:
        process_result = _oxidized_si_result(tmp)
        contactable = {"Si"}

        # Valid: the wafer's own real bottom boundary. Measured directly
        # against this exact recipe (grid_delta_um=0.2, no
        # silicon_depth_um override -> the process step's own default
        # floor depth): Si spans y=[-5.0, -0.00163], SiO2 spans
        # y=[-0.00164, +0.20462] -- do not guess these numbers for a
        # different recipe without re-measuring.
        valid_pin = Pin(name="Body", role="Body", x_um=WIDTH_UM / 2.0, y_um=-5.0)
        region = validate_pin_placement(process_result, valid_pin, WIDTH_UM, contactable)
        assert region == "Si", f"expected Si, got {region}"
        print(f"[1/4] valid pin on Si boundary resolves: region={region}")

        # Invalid: far outside the mesh entirely.
        outside_pin = Pin(name="Ghost", role="Drain", x_um=1000.0, y_um=0.0)
        try:
            validate_pin_placement(process_result, outside_pin, WIDTH_UM, contactable)
            assert False, "expected PinPlacementError for a point outside the mesh"
        except PinPlacementError as exc:
            assert exc.reason == REASON_OUTSIDE_MESH, exc.reason
            print(f"[2/4] outside-mesh pin correctly rejected: {exc.detail}")

        # Invalid: on the SiO2 cap, which is NOT in contactable_materials.
        # y=0.19 (not the brief's originally-drafted 0.15): measured
        # directly against this exact recipe, the mesh's own top
        # boundary sits at y=+0.20462 (matches the Si/SiO2 comment
        # above); 0.15 is 0.0546um from it -- just outside the default
        # 0.05um tolerance, so it resolves as REASON_INTERIOR_BULK, not
        # REASON_ON_INSULATOR (the point is not, in fact, within
        # tolerance of any real boundary at 0.15). 0.19 is 0.0146um
        # from the real top boundary, safely within tolerance.
        oxide_pin = Pin(name="BadGate", role="Gate", x_um=WIDTH_UM / 2.0, y_um=0.19)
        try:
            validate_pin_placement(process_result, oxide_pin, WIDTH_UM, contactable)
            assert False, "expected PinPlacementError for a point on SiO2"
        except PinPlacementError as exc:
            assert exc.reason == REASON_ON_INSULATOR, exc.reason
            print(f"[3/4] on-insulator pin correctly rejected: {exc.detail}")

        # Invalid: deep inside Si bulk (roughly midway between the top
        # Si/SiO2 boundary at y~0 and the bottom boundary at y=-5.0),
        # away from every real boundary.
        bulk_pin = Pin(name="Buried", role="Body", x_um=WIDTH_UM / 2.0, y_um=-2.5)
        try:
            validate_pin_placement(process_result, bulk_pin, WIDTH_UM, contactable, tolerance_um=0.05)
            assert False, "expected PinPlacementError for a point deep in Si bulk"
        except PinPlacementError as exc:
            assert exc.reason == REASON_INTERIOR_BULK, exc.reason
            print(f"[4/4] interior-bulk pin correctly rejected: {exc.detail}")

    print()
    print("COORDINATE -> MESH BOUNDARY RESOLUTION VERIFIED against real ViennaPS 4.6.2")


if __name__ == "__main__":
    main()
