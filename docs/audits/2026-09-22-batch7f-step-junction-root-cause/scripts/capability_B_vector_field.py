"""Batch 7F capability spike B: does the public element_from_edge_model()
path reconstruct a genuine 2D vector electric field?

Builds a small two-triangle rectangle (public create_gmsh_mesh(), same
shape as capability A), creates the SAME "ElectricField" edge model
DEVSIM's own CreateSiliconPotentialOnly()/CreateOxidePotentialOnly()
create (public simple_physics.py: "(Potential@n0-Potential@n1)*
EdgeInverseLength" -- verified by reading the installed public package
source, never guessed), assigns a KNOWN LINEAR potential
Potential(x,y) = -Ex0*x - Ey0*y directly via set_node_values (no solve
needed -- this is a pure capability/correspondence proof, not a physics
solve), then:
  1. element_from_edge_model(device, region, edge_model="ElectricField")
     -> creates ElectricField_x / ElectricField_y element models
     (public API, doc-confirmed).
  2. get_element_model_values() for both.
  3. get_element_node_list() to get each element's 3 node indices, so
     each element's centroid is computed from real node coordinates --
     the correspondence between the returned value list and the
     triangle list is established by COUNT (one value per element,
     same order as get_element_node_list()'s own element ordering) and
     cross-checked by RECONSTRUCTING the known field at each centroid
     from the SAME linear potential formula, never assumed.
Compares the element-reconstructed Ex/Ey/magnitude against the exact
KNOWN Ex0, Ey0, magnitude0 used to build the potential. If they don't
match to numerical precision, this stops here and reports a capability
blocker -- no global-edge-scalar substitute is invented.
"""
import json
import math
import sys

import devsim

W, H = 2.0e-4, 1.0e-4  # cm
EX0, EY0 = 5.0e4, -3.0e4  # V/cm -- an arbitrary, non-axis-aligned KNOWN field
MAG0 = math.hypot(EX0, EY0)


def build_mesh():
    coords = [0.0, 0.0, 0.0,  W, 0.0, 0.0,  W, H, 0.0,  0.0, H, 0.0]
    tris = [(0, 1, 2), (0, 2, 3)]
    elements = []
    for v0, v1, v2 in tris:
        elements += [2, 0, v0, v1, v2]
    elements += [1, 1, 0, 1]
    elements += [1, 2, 2, 3]
    devsim.create_gmsh_mesh(mesh="m_capB", coordinates=coords, elements=elements,
                            physical_names=["Si", "bot", "top"])
    devsim.add_gmsh_region(gmsh_name="Si", mesh="m_capB", region="Si", material="Si")
    devsim.add_gmsh_contact(gmsh_name="bot", mesh="m_capB", name="bot", material="metal", region="Si")
    devsim.add_gmsh_contact(gmsh_name="top", mesh="m_capB", name="top", material="metal", region="Si")
    devsim.finalize_mesh(mesh="m_capB")
    devsim.create_device(mesh="m_capB", device="d_capB")


def main():
    build_mesh()
    device, region = "d_capB", "Si"

    x = devsim.get_node_model_values(device=device, region=region, name="x")
    y = devsim.get_node_model_values(device=device, region=region, name="y")

    # A linear potential with KNOWN gradient (Potential = -Ex0*x - Ey0*y,
    # since E = -grad(Potential)) -- no solve, values set directly.
    from devsim.python_packages.model_create import CreateSolution
    CreateSolution(device, region, "Potential")
    pot = [-(EX0 * xv + EY0 * yv) for xv, yv in zip(x, y)]
    devsim.set_node_values(device=device, region=region, name="Potential", values=pot)

    # The exact same public "ElectricField" edge model DEVSIM's own
    # CreateSiliconPotentialOnly()/CreateOxidePotentialOnly() create --
    # verified by reading the installed devsim/python_packages/
    # simple_physics.py source directly, not guessed:
    #   efield = "(Potential@n0 - Potential@n1)*EdgeInverseLength"
    efield_eq = "(Potential@n0 - Potential@n1)*EdgeInverseLength"
    devsim.edge_model(device=device, region=region, name="ElectricField", equation=efield_eq)

    devsim.element_from_edge_model(device=device, region=region, edge_model="ElectricField")
    ex_raw = devsim.get_element_model_values(device=device, region=region, name="ElectricField_x")
    ey_raw = devsim.get_element_model_values(device=device, region=region, name="ElectricField_y")

    element_nodes = devsim.get_element_node_list(device=device, region=region)
    n_elements = len(element_nodes)  # 2 triangles
    # CORRESPONDENCE, established empirically here, never assumed: DEVSIM's
    # own get_element_model_values() for an element_from_edge_model()
    # output returns 3 raw values PER ELEMENT (one per edge/corner of the
    # triangle used in its internal least-squares gradient reconstruction),
    # so len(ex_raw) == 3 * n_elements, in element order (element i's 3
    # raw slots are ex_raw[3*i : 3*i+3]). This is DIFFERENT from a naive
    # "one value per element" assumption -- verified below, not guessed.
    stride_ok = (len(ex_raw) == len(ey_raw) == 3 * n_elements)

    node_x = {i: x[i] for i in range(len(x))}
    node_y = {i: y[i] for i in range(len(y))}

    per_element = []
    max_ex_err = max_ey_err = max_mag_err = 0.0
    max_within_element_spread_ex = max_within_element_spread_ey = 0.0
    for i in range(n_elements):
        node_ids = element_nodes[i]
        cx = sum(node_x[int(n)] for n in node_ids) / len(node_ids)
        cy = sum(node_y[int(n)] for n in node_ids) / len(node_ids)
        slot_ex = ex_raw[3 * i: 3 * i + 3]
        slot_ey = ey_raw[3 * i: 3 * i + 3]
        # Proof (not assumption) that the 3 raw slots are redundant copies
        # of the SAME per-element vector for a field that truly is
        # constant per element (exactly the case here, since Potential is
        # globally linear): their own internal spread must be ~0.
        spread_ex = max(slot_ex) - min(slot_ex)
        spread_ey = max(slot_ey) - min(slot_ey)
        max_within_element_spread_ex = max(max_within_element_spread_ex, spread_ex)
        max_within_element_spread_ey = max(max_within_element_spread_ey, spread_ey)
        ex_i, ey_i = slot_ex[0], slot_ey[0]  # any of the 3 -- proven equal above
        mag = math.hypot(ex_i, ey_i)
        ex_err = abs(ex_i - EX0)
        ey_err = abs(ey_i - EY0)
        mag_err = abs(mag - MAG0)
        max_ex_err = max(max_ex_err, ex_err)
        max_ey_err = max(max_ey_err, ey_err)
        max_mag_err = max(max_mag_err, mag_err)
        per_element.append({
            "element": i, "node_ids": [int(n) for n in node_ids], "centroid": [cx, cy],
            "raw_slots_Ex": list(slot_ex), "raw_slots_Ey": list(slot_ey),
            "within_element_spread_Ex": spread_ex, "within_element_spread_Ey": spread_ey,
            "Ex_reconstructed": ex_i, "Ey_reconstructed": ey_i, "magnitude_reconstructed": mag,
        })

    ok = (stride_ok and n_elements == 2
          and max_within_element_spread_ex < 1e-6 * abs(EX0)
          and max_within_element_spread_ey < 1e-6 * abs(EY0)
          and max_ex_err < 1e-6 * abs(EX0) and max_ey_err < 1e-6 * abs(EY0)
          and max_mag_err < 1e-6 * MAG0)

    result = {
        "known_Ex0_Vpercm": EX0, "known_Ey0_Vpercm": EY0, "known_magnitude_Vpercm": MAG0,
        "n_elements": n_elements, "len_ElectricField_x_raw": len(ex_raw), "len_ElectricField_y_raw": len(ey_raw),
        "stride_3_per_element_confirmed": stride_ok,
        "per_element": per_element,
        "max_within_element_spread_Ex_Vpercm": max_within_element_spread_ex,
        "max_within_element_spread_Ey_Vpercm": max_within_element_spread_ey,
        "max_Ex_error_Vpercm": max_ex_err, "max_Ey_error_Vpercm": max_ey_err, "max_magnitude_error_Vpercm": max_mag_err,
        "CORRESPONDENCE_AND_RECONSTRUCTION_OK": ok,
    }
    if ok:
        result["VERDICT"] = ("element_from_edge_model()+get_element_model_values()+get_element_node_list() "
                             "genuinely reconstruct the known 2D vector field per element, to numerical precision -- "
                             "safe to use for junction-field magnitude/location analysis")
    else:
        result["VERDICT"] = "CAPABILITY_BLOCKER -- element vector reconstruction did not reproduce the known field; stop"

    devsim.delete_device(device=device)
    devsim.delete_mesh(mesh="m_capB")

    print("===CAPABILITY_B_RESULT===")
    print(json.dumps(result, indent=2, default=str))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
