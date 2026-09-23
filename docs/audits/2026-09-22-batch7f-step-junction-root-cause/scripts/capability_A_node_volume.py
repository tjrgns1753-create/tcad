"""Batch 7F capability spike A: is NodeVolume real public API, and does
sum(NodeVolume) actually equal the triangulated rectangle area?

Never guesses the unit. Builds a small rectangle via the SAME public
create_gmsh_mesh() path import_process_result() uses (project raw mesh
arrays), triangulates it by hand (two triangles), imports it, reads
NodeVolume via get_node_model_values(), and compares sum(NodeVolume) to
the exact rectangle area computed independently from the triangle
vertex coordinates (shoelace formula). Public API only.
"""
import json
import sys

import devsim

W, H = 2.0e-4, 1.0e-4  # cm -- a 2x1 um-scale rectangle in cm units (arbitrary, just needs to be exact)


def shoelace_area(tri_pts):
    (x0, y0), (x1, y1), (x2, y2) = tri_pts
    return abs((x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)) / 2.0


def main():
    # Two triangles tiling a W x H rectangle, exactly like a ViennaPS/
    # meshio import would hand to create_gmsh_mesh(): flat coordinate list
    # + [2, physical_index, v0, v1, v2] element records (see
    # tcad/device/devsim/mesh_import.py::import_process_result, the same
    # public devsim.create_gmsh_mesh() call this project's own real
    # pipeline uses -- reused here read-only, not modified).
    coords = [0.0, 0.0, 0.0,  W, 0.0, 0.0,  W, H, 0.0,  0.0, H, 0.0]
    tris = [(0, 1, 2), (0, 2, 3)]
    elements = []
    for v0, v1, v2 in tris:
        elements += [2, 0, v0, v1, v2]
    # boundary contacts (needed for finalize_mesh/create_device to accept a region)
    elements += [1, 1, 0, 1]  # bottom edge as a contact
    elements += [1, 2, 2, 3]  # top edge as a contact

    devsim.create_gmsh_mesh(mesh="m_capA", coordinates=coords, elements=elements,
                            physical_names=["Si", "bot", "top"])
    devsim.add_gmsh_region(gmsh_name="Si", mesh="m_capA", region="Si", material="Si")
    devsim.add_gmsh_contact(gmsh_name="bot", mesh="m_capA", name="bot", material="metal", region="Si")
    devsim.add_gmsh_contact(gmsh_name="top", mesh="m_capA", name="top", material="metal", region="Si")
    devsim.finalize_mesh(mesh="m_capA")
    devsim.create_device(mesh="m_capA", device="d_capA")

    has_attr = hasattr(devsim, "get_node_model_values")
    node_model_list = list(devsim.get_node_model_list(device="d_capA", region="Si"))
    node_volume_present = "NodeVolume" in node_model_list

    result = {
        "has_get_node_model_values": has_attr,
        "node_model_list": node_model_list,
        "NodeVolume_in_list": node_volume_present,
    }

    if node_volume_present:
        nv = devsim.get_node_model_values(device="d_capA", region="Si", name="NodeVolume")
        sum_nv = sum(nv)
        exact_area = shoelace_area([(0.0, 0.0), (W, 0.0), (W, H)]) + shoelace_area([(0.0, 0.0), (W, H), (0.0, H)])
        rel_err = abs(sum_nv - exact_area) / exact_area
        result.update({
            "NodeVolume_values": nv,
            "sum_NodeVolume": sum_nv,
            "exact_triangulated_rectangle_area_cm2": exact_area,
            "relative_error": rel_err,
            "MATCHES_TRIANGULATED_AREA": rel_err < 1e-9,
        })
        if rel_err >= 1e-9:
            result["VERDICT"] = "MISMATCH -- reason not yet established; do not use for inventory integrals"
        else:
            result["VERDICT"] = "sum(NodeVolume) == triangulated rectangle area to " + f"{rel_err:.3e} relative -- safe for dopant inventory integrals"
    else:
        result["VERDICT"] = "UNAVAILABLE_FROM_PUBLIC_API -- NodeVolume not in get_node_model_list(); stop, do not invent inventory integrals"

    devsim.delete_device(device="d_capA")
    devsim.delete_mesh(mesh="m_capA")

    print("===CAPABILITY_A_RESULT===")
    print(json.dumps(result, indent=2, default=str))
    sys.exit(0 if node_volume_present and result.get("MATCHES_TRIANGULATED_AREA") else 1)


if __name__ == "__main__":
    main()
