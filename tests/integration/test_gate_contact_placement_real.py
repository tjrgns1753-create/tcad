#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gate-over-channel + separate source/drain contacts — real ViennaPS
4.6.2 + DevSim, through the real production entry points.

This is the "next smallest experiment" the `implant_windows` doping
section named and explicitly did NOT execute: whether a distinct
gate-stack material whose own bounding box is the channel window, plus
distinct source/drain materials, produces three (here four, including
the body) correctly-positioned contacts through the EXISTING
contact_sides API — no coordinate-windowed contact placement needed.

Also regression-guards a real bug this investigation found and fixed in
`tcad/backends/viennaps/io.py`: `save_locos_volume_mesh()` (needed here
because these 4 materials are laterally disjoint, which the normal
`save_volume_mesh()`'s insertion-order "topmost wins" resolution cannot
handle at all — confirmed separately: it kept only 1 of 4 materials)
was itself broken for a domain topology no earlier caller had exercised:
a level set laterally NARROWER than the export floor mechanism's own
padding. `domain.getBoundingBox()` does not return the union across a
multi-level-set domain (confirmed: it returned only the last-inserted
material's own bbox), and even with the correct union bbox,
`_floored_copy_for_export`'s own floor-box padding — derived from
`getBoundingBox()` on the ISOLATED single-material domain, which
correctly reports that ONE material's own tight extent — collapsed the
subsequent boolean intersect to an EMPTY level set. Fixed by threading
the domain's true union extent through as an explicit `bounds_hint`,
bypassing both wrong re-derivations. See CLAUDE.md for the full
diagnosis (four rejected hypotheses before finding the real one).

Geometry (4 materials, none overlapping in volume — Si sits at y<=0,
the other three sit at y>=0 in disjoint lateral windows):
    Si     : body,   y in [-depth, 0], full domain width
    Gate   : y in [0, gate_h],  x in the CHANNEL window only
    Source : y in [0, pad_h],   x in the source window
    Drain  : y in [0, pad_h],   x in the drain window
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio

from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import save_locos_volume_mesh
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.device.devsim import backend as devsim_backend
from tcad.device.devsim.mesh_import import import_process_result

assert session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

module = session.require_viennaps()
devsim = devsim_backend.require_devsim()
import viennals as vls  # noqa: E402

GRID = 0.05
X_EXTENT = 6.0
Y_EXTENT = 3.0
SI_DEPTH = 1.0
GATE_H = 0.15
PAD_H = 0.10
GATE = (-0.8, 0.8)
SRC = (-2.4, -1.0)
DRN = (1.0, 2.4)


def _box_level_set(bounds, bcs, lo_xy, hi_xy):
    ls = vls.Domain(bounds, bcs, GRID)
    geom = vls.MakeGeometry(ls, vls.Box(list(lo_xy), list(hi_xy)))
    geom.setIgnoreBoundaryConditions([False, True, False])
    geom.apply()
    return ls


def _build_gate_stack_domain():
    """4 laterally-disjoint materials: Si body, TiN gate (channel-only),
    W source pad, Cu drain pad. Deliberately NOT wired into
    ProcessStep.prepare_domain() -- this is a verification-only
    construction for this test, not a shipped recipe geometry."""
    half_x = X_EXTENT / 2.0
    scratch = session.create_domain(GRID, X_EXTENT, Y_EXTENT)
    module.MakePlane(scratch, 0.0, module.Material.Si).apply()
    bcs = scratch.getBoundaryConditions()
    bounds = [-half_x, half_x, -SI_DEPTH - 0.5, Y_EXTENT]

    geom = session.create_domain(GRID, X_EXTENT, Y_EXTENT)
    geom.insertNextLevelSetAsMaterial(
        _box_level_set(bounds, bcs, (-half_x, -SI_DEPTH), (half_x, 0.0)),
        module.Material.Si, False,
    )
    geom.insertNextLevelSetAsMaterial(
        _box_level_set(bounds, bcs, (GATE[0], 0.0), (GATE[1], GATE_H)),
        module.Material.TiN, False,
    )
    geom.insertNextLevelSetAsMaterial(
        _box_level_set(bounds, bcs, (SRC[0], 0.0), (SRC[1], PAD_H)),
        module.Material.W, False,
    )
    geom.insertNextLevelSetAsMaterial(
        _box_level_set(bounds, bcs, (DRN[0], 0.0), (DRN[1], PAD_H)),
        module.Material.Cu, False,
    )
    return geom


def _region_x_range(device, region):
    xs = devsim.get_node_model_values(device=device, region=region, name="x")
    return min(xs), max(xs)


def main():
    geometry = _build_gate_stack_domain()

    with tempfile.TemporaryDirectory() as tmp:
        mesh_path = save_locos_volume_mesh(
            geometry,
            materials=[module.Material.Si, module.Material.TiN,
                       module.Material.W, module.Material.Cu],
            wrap_flags=[False, False, False, False],
            path=Path(tmp) / "gate_stack",
            floor_depth_um=SI_DEPTH,
        )
        print(f"[1/4] exported: {mesh_path}")

        mesh = meshio.read(mesh_path)
        block = next(c for c in mesh.cells if c.type == "triangle")
        tags = {int(t) for t in mesh.cell_data["Material"][mesh.cells.index(block)]}
        names = sorted(str(module.Material(t)).split("'")[1] for t in tags)
        assert set(names) == {"Si", "TiN", "W", "Cu"}, (
            f"expected all 4 laterally-disjoint materials in the export, got {names} "
            f"-- regression in save_locos_volume_mesh's bounds handling for a "
            f"narrow, non-wrapped level set"
        )
        print(f"[2/4] all 4 materials present: {names}")

        step_result = {"final_mesh": mesh_path, "snapshots": []}
        process_result = build_process_result(step_result)

        imported = import_process_result(
            process_result, mesh_name="gate_mesh", device_name="gate_device",
            contact_regions=["Si", "TiN", "W", "Cu"],
            contact_axis="y",
            contact_sides={"Si": "min", "TiN": "max", "W": "max", "Cu": "max"},
        )
        expected_contacts = {"Si_ymin", "TiN_ymax", "W_ymax", "Cu_ymax"}
        assert set(imported.contacts) == expected_contacts, (
            f"expected {expected_contacts}, got {set(imported.contacts)}"
        )
        print(f"[3/4] all 4 contacts created via the EXISTING contact_sides "
              f"API (no new API needed): {sorted(imported.contacts)}")

        checks = [("TiN", GATE), ("W", SRC), ("Cu", DRN)]
        for region, expected_range in checks:
            lo, hi = _region_x_range(imported.device, region)
            assert abs(lo - expected_range[0]) < GRID and abs(hi - expected_range[1]) < GRID, (
                f"{region} contact x-range ({lo:.4f},{hi:.4f}) vs "
                f"expected {expected_range}"
            )
        gate_lo, gate_hi = _region_x_range(imported.device, "TiN")
        assert gate_lo > SRC[1] and gate_hi < DRN[0], (
            f"gate contact ({gate_lo},{gate_hi}) overlaps source/drain windows "
            f"-- not properly bounded to the channel"
        )
        print(f"[4/4] every contact lands exactly at its own recipe window "
              f"(gate={GATE}, source={SRC}, drain={DRN}), gate strictly "
              f"between source and drain -- bounded to the channel only")

    print()
    print("GATE-OVER-CHANNEL + SEPARATE SOURCE/DRAIN CONTACTS VERIFIED "
          "AGAINST REAL VIENNAPS 4.6.2 + DEVSIM: the existing contact_sides "
          "API is sufficient once the export bug is fixed -- no new "
          "device/mesh API is needed for this part of a MOSFET geometry")


if __name__ == "__main__":
    main()
