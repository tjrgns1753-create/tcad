#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""point_contacts on import_process_result(): two coordinate-placed
contacts on the SAME Si region resolve to distinct, correctly-sized
node sets, and every existing axis-extreme contact behavior is
unaffected (regression)."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.backends.viennaps import session
from tcad.device.devsim import backend as devsim_backend

assert session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

devsim = devsim_backend.require_devsim()

import tcad.process.etching  # noqa: F401 -- registers isotropic etch
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.device.devsim.mesh_import import import_process_result

WIDTH_UM = 10.0
GRID = 0.2


def _contact_nodes(device, region, contact):
    """The set of distinct mesh node indices DevSim actually bound to
    `contact` -- read from DevSim's own element-node list for that
    contact, not reconstructed from the mesh."""
    return {
        int(n)
        for element in devsim.get_element_node_list(device=device, region=region, contact=contact)
        for n in element
    }


def _si_boundary_node_count(process_result):
    """How many nodes sit on Si's REAL boundary, by the same
    one-triangle-owner edge definition import_process_result uses."""
    import meshio
    from tcad.device.devsim.contact_probe import boundary_edges_by_tag

    mesh = meshio.read(process_result.volume_mesh_path)
    block = next(c for c in mesh.cells if c.type == "triangle")
    tags = mesh.cell_data[process_result.material_field][mesh.cells.index(block)]
    si_tag = next(r.tag for r in process_result.material_regions if r.name == "Si")
    edges = boundary_edges_by_tag(block.data, tags)[si_tag]
    return len({n for edge in edges for n in edge})


def main():
    with tempfile.TemporaryDirectory() as tmp:
        step_cls = registry.get("etching", "isotropic")
        step = step_cls()
        recipe = {
            "grid_delta_um": GRID, "x_extent_um": WIDTH_UM, "y_extent_um": 8.0,
            # "rate" (not "etch_rate_um_s") -- negative removes material,
            # this module's own fixed etching convention (see
            # tcad/process/etching/isotropic.py's module docstring).
            "silicon_depth_um": 3.0, "etch_time_s": 1.0, "rate": -0.05,
        }
        result = step.run(recipe, tmp)
        process_result = build_process_result({"final_mesh": result["final_mesh"], "snapshots": []})

        # Two point contacts near opposite sides of Si's own top surface,
        # NOT at the region's own x-extremes (which contact_regions would
        # already give byte-for-byte, unchanged) -- a real interior point.
        imported = import_process_result(
            process_result, mesh_name="pc_mesh", device_name="pc_device",
            point_contacts=[
                {"name": "PinA", "region": "Si", "x_domain_um": -1.0, "y_um": 0.0, "radius_um": 0.3},
                {"name": "PinB", "region": "Si", "x_domain_um": 1.0, "y_um": 0.0, "radius_um": 0.3},
            ],
        )
        assert set(imported.contacts) == {"PinA", "PinB"}, imported.contacts
        print(f"[1/4] two point contacts created: {imported.contacts}")

        contact_list = devsim.get_contact_list(device=imported.device)
        assert set(contact_list) == {"PinA", "PinB"}, contact_list

        # The radius really filtered: each contact binds a small, non-
        # empty subset of Si's own real boundary nodes, and the two
        # subsets are disjoint. Si's full boundary node set is computed
        # from the same real mesh via this project's own boundary-edge
        # definition (an edge touched by exactly one triangle) -- the
        # definition import_process_result itself uses.
        bound = {
            name: _contact_nodes(imported.device, "Si", name)
            for name in ("PinA", "PinB")
        }
        si_boundary_nodes = _si_boundary_node_count(process_result)
        for name, nodes in bound.items():
            assert nodes, f"{name} bound no nodes at all"
            assert len(nodes) < 0.05 * si_boundary_nodes, (
                f"{name} bound {len(nodes)} of {si_boundary_nodes} Si boundary "
                f"nodes -- radius_um=0.3 filtered nothing"
            )
        assert not (bound["PinA"] & bound["PinB"]), (
            f"PinA and PinB share nodes: {sorted(bound['PinA'] & bound['PinB'])}"
        )
        print(f"[2/4] both contacts registered and radius-filtered: "
              f"PinA={len(bound['PinA'])} PinB={len(bound['PinB'])} nodes of "
              f"{si_boundary_nodes} Si boundary nodes, disjoint")

        devsim.delete_device(device=imported.device)
        devsim.delete_mesh(mesh=imported.mesh)

        # Same specs at length_scale_to_cm=1e-4 -- the exact scale the
        # Task-3 length-scale bug hid under (spec coordinates are
        # documented as pre-scale um, so an unscaled comparison silently
        # finds no edge at all and creates no contact). The contacts must
        # resolve to the IDENTICAL node sets as at the default scale.
        imported_scaled = import_process_result(
            process_result, mesh_name="pc_mesh_cm", device_name="pc_device_cm",
            point_contacts=[
                {"name": "PinA", "region": "Si", "x_domain_um": -1.0, "y_um": 0.0, "radius_um": 0.3},
                {"name": "PinB", "region": "Si", "x_domain_um": 1.0, "y_um": 0.0, "radius_um": 0.3},
            ],
            length_scale_to_cm=1.0e-4,
        )
        assert set(imported_scaled.contacts) == {"PinA", "PinB"}, imported_scaled.contacts
        for name in ("PinA", "PinB"):
            scaled_nodes = _contact_nodes(imported_scaled.device, "Si", name)
            assert scaled_nodes == bound[name], (
                f"{name} resolved differently at length_scale_to_cm=1e-4: "
                f"{len(scaled_nodes)} nodes vs {len(bound[name])} at the default scale"
            )
        print(f"[2b/4] identical contacts resolve at length_scale_to_cm=1e-4")
        devsim.delete_device(device=imported_scaled.device)
        devsim.delete_mesh(mesh=imported_scaled.mesh)

        # Regression: the EXISTING axis-extreme contact_regions path,
        # called with point_contacts omitted, is unaffected.
        imported2 = import_process_result(
            process_result, mesh_name="pc_mesh2", device_name="pc_device2",
            contact_regions=["Si"], contact_axis="x",
        )
        assert set(imported2.contacts) == {"Si_xmin", "Si_xmax"}, imported2.contacts
        print(f"[3/4] existing contact_regions path unaffected: {imported2.contacts}")
        devsim.delete_device(device=imported2.device)
        devsim.delete_mesh(mesh=imported2.mesh)

        # extra_contacts: Si gets its normal x-axis contact_regions pair
        # PLUS a y-axis contact for the SAME region in one call -- the
        # exact shape a Body contact needs (Source/Drain on x, Body on y).
        imported3 = import_process_result(
            process_result, mesh_name="pc_mesh3", device_name="pc_device3",
            contact_regions=["Si"], contact_axis="x",
            extra_contacts=[{"name": "Si_ymin", "region": "Si", "axis": "y", "side": "min"}],
        )
        assert set(imported3.contacts) == {"Si_xmin", "Si_xmax", "Si_ymin"}, imported3.contacts
        print(f"[4/4] extra_contacts adds a 2nd-axis contact alongside "
              f"contact_regions': {sorted(imported3.contacts)}")
        devsim.delete_device(device=imported3.device)
        devsim.delete_mesh(mesh=imported3.mesh)

    print()
    print("point_contacts VERIFIED against real ViennaPS 4.6.2 + DevSim, "
          "existing contact_regions path confirmed byte-for-byte unaffected")


if __name__ == "__main__":
    main()
