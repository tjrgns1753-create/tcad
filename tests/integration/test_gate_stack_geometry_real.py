#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GateStack geometry model — real ViennaPS 4.6.2 + DevSim, through the
real production entry point (registry -> ProcessStep.run(), not manual
geometry construction the way test_gate_contact_placement_real.py's
probe was).

This is the production wiring for the topology
test_gate_contact_placement_real.py verified works through the
EXISTING contact_sides API: Si body, a gate oxide + electrode confined
to a channel window (on top of one another), and separate source/drain
pads. See tcad/process/geometry/gate_stack.py and
tcad/backends/viennaps/session.py's make_gate_stack() for why this is
its own zero-duration "geometry" category rather than another
prepare_domain() branch, and why it is a TERMINAL construction (no
further process step may be chained onto it — verified separately to
silently corrupt the export).

Checks, all against the real production run() -> DevSim import path:
  1. registry.get("geometry", "gate_stack") is reachable and runs.
  2. all 5 materials (Si, source, drain, oxide, gate) present in the
     exported mesh with nonzero area.
  3. DevSim import + all 4 contacts placed via the existing
     contact_sides API, each at its own recipe window.
  4. gate strictly between source and drain (bounded to the channel).
  5. inherited_domain is refused outright (no sensible "continue a flow
     into a gate stack").
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio

import tcad.process.geometry  # noqa: F401 -- registers gate_stack
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.mesh_import import import_process_result

devsim = devsim_backend.require_devsim()

GRID = 0.05
CHANNEL = (-0.8, 0.8)
SRC = (-2.4, -1.0)
DRN = (1.0, 2.4)

RECIPE = {
    "grid_delta_um": GRID,
    "x_extent_um": 6.0,
    "y_extent_um": 3.0,
    "silicon_depth_um": 1.0,
    "channel_um": list(CHANNEL),
    "source_um": list(SRC),
    "drain_um": list(DRN),
    "gate_oxide_thickness_um": 0.02,
    "gate_height_um": 0.15,
    "pad_height_um": 0.10,
}


def region_x_range(device, region):
    xs = devsim.get_node_model_values(device=device, region=region, name="x")
    return min(xs), max(xs)


def main():
    step_cls = registry.get("geometry", "gate_stack")

    # Check 5: inherited_domain must be refused.
    try:
        step_cls(inherited_domain=object())
        raise AssertionError("expected NotImplementedError for inherited_domain")
    except NotImplementedError:
        pass
    print("[1/5] inherited_domain correctly refused")

    with tempfile.TemporaryDirectory() as tmp:
        step = step_cls()
        result = step.run(RECIPE, tmp)
        mesh_path = result["final_mesh"]
        print(f"[2/5] real production run() OK: {mesh_path}")

        mesh = meshio.read(mesh_path)
        block = next(c for c in mesh.cells if c.type == "triangle")
        idx = mesh.cells.index(block)
        tags = {int(t) for t in mesh.cell_data["Material"][idx]}
        import viennaps as vps
        names = sorted(str(vps.Material(t)).split("'")[1] for t in tags)
        assert set(names) == {"Si", "SiO2", "TiN", "W", "Cu"}, names
        print(f"[3/5] all 5 materials present: {names}")

        step_result = {"final_mesh": mesh_path, "snapshots": result["snapshots"]}
        process_result = build_process_result(step_result)

        imported = import_process_result(
            process_result, mesh_name="gate_stack_mesh", device_name="gate_stack_device",
            contact_regions=["Si", "TiN", "W", "Cu"],
            contact_axis="y",
            contact_sides={"Si": "min", "TiN": "max", "W": "max", "Cu": "max"},
        )
        expected_contacts = {"Si_ymin", "TiN_ymax", "W_ymax", "Cu_ymax"}
        assert set(imported.contacts) == expected_contacts, imported.contacts
        print(f"[4/5] all 4 contacts created via the existing contact_sides API: "
              f"{sorted(imported.contacts)}")

        checks = [("TiN", CHANNEL), ("W", SRC), ("Cu", DRN)]
        for region, expected in checks:
            lo, hi = region_x_range(imported.device, region)
            assert abs(lo - expected[0]) < GRID and abs(hi - expected[1]) < GRID, (
                f"{region}: measured ({lo:.4f},{hi:.4f}) vs expected {expected}"
            )
        gate_lo, gate_hi = region_x_range(imported.device, "TiN")
        assert gate_lo > SRC[1] and gate_hi < DRN[0], (
            f"gate ({gate_lo},{gate_hi}) not strictly between source/drain"
        )
        print("[5/5] every contact lands at its own recipe window; gate strictly "
              "between source and drain")

    print()
    print("GATE STACK GEOMETRY MODEL VERIFIED through the real production "
          "registry -> ProcessStep.run() -> DevSim import path")


if __name__ == "__main__":
    main()
