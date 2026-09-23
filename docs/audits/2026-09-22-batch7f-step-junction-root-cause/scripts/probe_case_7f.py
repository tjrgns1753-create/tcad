"""Batch 7F -- one (mode, level, representation, shifted[, diagonal, height_scale])
case, its own subprocess. Public DEVSIM API only (see scan_public_api_only_7f.py).
Computes: mesh quality (whole/band/ring/outer), contact geometry, NodeVolume dopant
inventory, junction-column volume, equilibrium solve, element-vector field (global/
band/interior max + location), y-invariance (exact-x column grouping), and depletion
recovery (old y-collapsed baseline + two new clean variants). NO production tcad/ or
tests/ files are modified; tcad.device.devsim.mesh_refine.refine_mesh_near and
tcad.backends.viennaps are used READ-ONLY, exactly as import_process_result() already
calls them in production.
"""
import json
import math
import os
import sys
import tempfile
import warnings

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
warnings.simplefilter("ignore")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402
import devsim  # noqa: E402
from devsim.python_packages.simple_physics import (  # noqa: E402
    CreateSiliconPotentialOnly, CreateSiliconPotentialOnlyContact,
    CreateSiliconDriftDiffusion, CreateSiliconDriftDiffusionAtContact,
    SetSiliconParameters, GetContactBiasName,
)
from devsim.python_packages.model_create import CreateSolution  # noqa: E402

from mesh_quality import analyze_triangle_subset, classify_by_x_band  # noqa: E402
from structured_mesh import build_x_lines_um, build_structured_triangulation, import_structured_device  # noqa: E402

ND, NA = 1.0e18, 1.0e18
RECIPE_2D = {"grid_delta_um": 0.2, "x_extent_um": 4.0, "y_extent_um": 3.0, "silicon_depth_um": 2.0}
XJ_UM, LENGTH_SCALE = 0.0, 1.0e-4
BAND_HALF_WIDTH_UM = 0.1   # == import_process_result()'s own refine_half_width_um default -- the EXACT
                           # window used to build the refined mesh in the first place (never redefined here).
RING_MULTIPLIER = 3.0      # ring := [band, 3*band) um from the junction -- documented choice, fixed BEFORE
                           # looking at any result (red-green closure typically promotes one extra ring of
                           # neighbors around a marked band; 3x gives that halo room without redefinition).


def um_to_cm(v):
    return v * LENGTH_SCALE


# ---------------------------------------------------------------------------------------------- mesh construction
def build_imported_mesh_raw(level, tmp):
    """The RAW (points_um, triangles, tags) exactly as import_process_result() would
    produce for this level, WITHOUT importing into devsim -- read-only reuse of
    tcad.backends.viennaps (ViennaPS geometry) + tcad.device.devsim.mesh_refine.
    refine_mesh_near() (production refinement function, called read-only, never
    modified) so the mesh-quality audit needs no solve at all."""
    from tcad.backends.viennaps import session as vsession
    from tcad.backends.viennaps.io import save_volume_mesh
    from tcad.device.devsim.mesh_refine import refine_mesh_near
    import meshio

    domain = vsession.make_mask_spans(
        grid_delta_um=RECIPE_2D["grid_delta_um"], x_extent_um=RECIPE_2D["x_extent_um"], y_extent_um=RECIPE_2D["y_extent_um"],
        spans_um=[], mask_height_um=0.1, substrate_depth_um=RECIPE_2D["silicon_depth_um"] + 1.0,
    )
    mesh_path = save_volume_mesh(domain, os.path.join(tmp, "virgin_wafer"), floor_depth_um=RECIPE_2D["silicon_depth_um"])
    mesh = meshio.read(mesh_path)  # save_volume_mesh() already returns the real, actually-written path
    triangle_block = next(c for c in mesh.cells if c.type == "triangle")
    block_index = mesh.cells.index(triangle_block)
    triangles = triangle_block.data
    tags = mesh.cell_data["Material"][block_index]  # "Material" (capital M) -- tcad/mesh/interface.py's own material_field default
    raw_points = mesh.points[:, :2].copy()

    def _near_refine_target(centroid):
        return abs(centroid[0] - XJ_UM) < BAND_HALF_WIDTH_UM

    refined_points, refined_triangles, refined_tags = refine_mesh_near(
        raw_points, triangles, tags, _near_refine_target, levels=level + 1)
    return refined_points, refined_triangles, refined_tags, mesh_path


def import_imported_mesh(points_um, triangles, tags, device_name, mesh_name):
    """Reuses import_process_result()'s OWN create_gmsh_mesh() wiring logic
    (region "Si", contacts Si_xmin/Si_xmax) but on an ALREADY-refined raw
    array this script controls directly -- calls the same public API
    (create_gmsh_mesh/add_gmsh_region/add_gmsh_contact/finalize_mesh/
    create_device) production code uses, never a private path."""
    region, mesh, contacts = import_structured_device(
        devsim, points_um, triangles, tags.astype(np.int64) * 0, device_name, mesh_name,
        LENGTH_SCALE, region_name="Si")
    return region, mesh, contacts


# ---------------------------------------------------------------------------------------------- doping + inventory
def set_doping(device, region, representation, xj_cm):
    if representation == "R1":
        acc_eq = f"{NA:.10e}*step(({xj_cm:.10e})-x)"
    elif representation == "R2":
        acc_eq = f"{NA:.10e}*(1-step(x-({xj_cm:.10e})))"
    else:
        raise ValueError(representation)
    devsim.node_model(device=device, region=region, name="Donors", equation=f"{ND:.10e}*step(x-({xj_cm:.10e}))")
    devsim.node_model(device=device, region=region, name="Acceptors", equation=acc_eq)
    devsim.node_model(device=device, region=region, name="NetDoping", equation="Donors-Acceptors")


def locate_junction(x_native, intended_x):
    x0 = min(x_native, key=lambda v: abs(v - intended_x))
    tol = 1e-6 * max(abs(intended_x), 1e-5)
    assert abs(x0 - intended_x) < tol, f"no node at intended junction {intended_x}: nearest {x0}"
    righties = sorted(v for v in set(x_native) if v > x0)
    assert righties, "no node strictly right of x0"
    return x0, righties[0]


def dopant_inventory(device, region, xj_used_cm):
    """Q/q [cm^-1] via NodeVolume (spike A: sum(NodeVolume) == triangulated
    area to 0.0 relative error), plus the analytic CONTINUUM inventory --
    exact rectangle areas either side of the real, continuum junction
    position, using the REAL MEASURED bounding box of this device's own
    nodes (never the recipe's stated x_extent_um/y_extent_um: this
    project's own established practice -- e.g.
    test_wafer_state_v2_initial_geometry_devsim_real.py's own
    _assert_mesh_matches_recipe_bounds() -- is that the mesh is the
    evidence, the recipe is never assumed equal to it; confirmed
    necessary here directly: silicon_depth_um bounds the FLOORED Si
    depth, not the recipe's separate y_extent_um, which governs the
    overall pre-floor simulation box instead)."""
    donors = devsim.get_node_model_values(device=device, region=region, name="Donors")
    acceptors = devsim.get_node_model_values(device=device, region=region, name="Acceptors")
    nets = devsim.get_node_model_values(device=device, region=region, name="NetDoping")
    nv = devsim.get_node_model_values(device=device, region=region, name="NodeVolume")
    x = devsim.get_node_model_values(device=device, region=region, name="x")
    y = devsim.get_node_model_values(device=device, region=region, name="y")

    q_d = sum(d * v for d, v in zip(donors, nv))
    q_a = sum(a * v for a, v in zip(acceptors, nv))
    q_net = sum(n * v for n, v in zip(nets, nv))

    xmin_cm, xmax_cm, ymin_cm, ymax_cm = min(x), max(x), min(y), max(y)
    y_cm = ymax_cm - ymin_cm
    donor_area_cm2 = max(0.0, xmax_cm - xj_used_cm) * y_cm
    acceptor_area_cm2 = max(0.0, xj_used_cm - xmin_cm) * y_cm
    q_d_analytic = ND * donor_area_cm2
    q_a_analytic = NA * acceptor_area_cm2
    q_net_analytic = q_d_analytic - q_a_analytic
    total_area_cm2 = (xmax_cm - xmin_cm) * y_cm

    return {
        "Q_D_over_q_cm-1": q_d, "Q_A_over_q_cm-1": q_a, "Q_net_over_q_cm-1": q_net,
        "Q_D_analytic_continuum_cm-1": q_d_analytic, "Q_A_analytic_continuum_cm-1": q_a_analytic,
        "Q_net_analytic_continuum_cm-1": q_net_analytic,
        "sum_NodeVolume_cm2": sum(nv), "n_nodes": len(x),
        "measured_bbox_cm": {"xmin": xmin_cm, "xmax": xmax_cm, "ymin": ymin_cm, "ymax": ymax_cm},
        "measured_total_area_cm2": total_area_cm2,
        "sum_NodeVolume_vs_measured_area_relative_error": abs(sum(nv) - total_area_cm2) / total_area_cm2,
    }


def junction_column_volume(device, region, x0_cm):
    x = devsim.get_node_model_values(device=device, region=region, name="x")
    nv = devsim.get_node_model_values(device=device, region=region, name="NodeVolume")
    col = [v for xv, v in zip(x, nv) if abs(xv - x0_cm) < 1e-9 * max(abs(x0_cm), 1e-9) + 1e-15]
    return {"n_nodes_in_column": len(col), "column_NodeVolume_sum_cm2": sum(col)}


# ---------------------------------------------------------------------------------------------- field / y-invariance / depletion
def element_field_analysis(device, region, x_native, y_native, band_half_width_cm, contacts_x_cm):
    devsim.element_from_edge_model(device=device, region=region, edge_model="ElectricField")
    ex_raw = devsim.get_element_model_values(device=device, region=region, name="ElectricField_x")
    ey_raw = devsim.get_element_model_values(device=device, region=region, name="ElectricField_y")
    element_nodes = devsim.get_element_node_list(device=device, region=region)
    n_el = len(element_nodes)
    assert len(ex_raw) == len(ey_raw) == 3 * n_el, "element correspondence stride assumption violated -- capability blocker"

    xmin_cm, xmax_cm = min(x_native), max(x_native)
    ymin_cm, ymax_cm = min(y_native), max(y_native)

    records = []
    for i in range(n_el):
        nid = element_nodes[i]
        cx = sum(x_native[int(n)] for n in nid) / 3.0
        cy = sum(y_native[int(n)] for n in nid) / 3.0
        ex_i, ey_i = ex_raw[3 * i], ey_raw[3 * i]  # 3 raw slots proven redundant in spike B
        mag = math.hypot(ex_i, ey_i)
        touches_boundary = any(
            abs(x_native[int(n)] - xmin_cm) < 1e-12 or abs(x_native[int(n)] - xmax_cm) < 1e-12
            or abs(y_native[int(n)] - ymin_cm) < 1e-12 or abs(y_native[int(n)] - ymax_cm) < 1e-12
            for n in nid)
        in_band = abs(cx) < band_half_width_cm
        records.append({"i": i, "cx": cx, "cy": cy, "Ex": ex_i, "Ey": ey_i, "mag": mag,
                        "boundary_adjacent": touches_boundary, "in_band": in_band})

    def _best(recs, key="mag"):
        if not recs:
            return None
        r = max(recs, key=lambda rr: rr[key])
        dist_to_contacts = {"to_xmin": abs(r["cx"] - xmin_cm), "to_xmax": abs(r["cx"] - xmax_cm),
                            "to_ymin": abs(r["cy"] - ymin_cm), "to_ymax": abs(r["cy"] - ymax_cm)}
        return {"magnitude_Vpercm": r["mag"], "Ex_Vpercm": r["Ex"], "Ey_Vpercm": r["Ey"],
                "centroid_cm": [r["cx"], r["cy"]], "distance_to_junction_cm": abs(r["cx"]),
                **{k: v for k, v in dist_to_contacts.items()}, "boundary_adjacent": r["boundary_adjacent"]}

    global_max = _best(records)
    band_max = _best([r for r in records if r["in_band"]])
    interior_max = _best([r for r in records if r["in_band"] and not r["boundary_adjacent"]])
    max_abs_ey = max((abs(r["Ey"]) for r in records), default=0.0)
    max_abs_ex = max((abs(r["Ex"]) for r in records), default=1e-300)
    return {
        "n_elements": n_el, "global_max": global_max, "junction_band_max": band_max,
        "junction_interior_max_excl_boundary": interior_max,
        "y_invariance_indicator_max_absEy_over_max_absEx": max_abs_ey / max_abs_ex,
    }


def y_invariance(x_native, values_by_name):
    groups = {}
    for i, xv in enumerate(x_native):
        groups.setdefault(xv, []).append(i)
    multi = {k: v for k, v in groups.items() if len(v) >= 2}
    out = {"n_distinct_x_columns": len(groups), "n_columns_with_ge2_nodes": len(multi),
          "n_singleton_columns": len(groups) - len(multi)}
    for name, vals in values_by_name.items():
        spreads = [max(vals[i] for i in idxs) - min(vals[i] for i in idxs) for idxs in multi.values()]
        out[f"{name}_max_spread"] = max(spreads) if spreads else None
        out[f"{name}_median_spread"] = float(np.median(spreads)) if spreads else None
    return out


def depletion_old_ycollapsed(x, majority, background, xj_cm, side):
    pts = sorted(((xv, m, b) for xv, m, b in zip(x, majority, background)
                 if (xv > xj_cm if side == "+" else xv < xj_cm)), key=lambda t: abs(t[0] - xj_cm))
    out = {}
    for frac in (0.5, 0.9, 0.99):
        hit = next((abs(xv - xj_cm) for xv, m, b in pts if b > 0 and m >= frac * b), None)
        out[f"recovery_{int(frac * 100)}pct_cm"] = hit
    return out


def depletion_center_yline(x, y, majority, background, xj_cm, side, min_points=5):
    y_arr = np.array(y)
    y_center = (y_arr.min() + y_arr.max()) / 2.0
    # the ACTUAL y value with the most x-coverage nearest the geometric center
    from collections import Counter
    counts = Counter(y)
    candidates = sorted(counts.items(), key=lambda kv: (abs(kv[0] - y_center), -kv[1]))
    for y_val, cnt in candidates:
        if cnt < min_points:
            continue
        pts = sorted(((xv, m, b) for xv, yv, m, b in zip(x, y, majority, background)
                     if yv == y_val and (xv > xj_cm if side == "+" else xv < xj_cm)), key=lambda t: abs(t[0] - xj_cm))
        out = {"y_line_used_cm": y_val, "n_points_on_line": cnt}
        for frac in (0.5, 0.9, 0.99):
            hit = next((abs(xv - xj_cm) for xv, m, b in pts if b > 0 and m >= frac * b), None)
            out[f"recovery_{int(frac * 100)}pct_cm"] = hit
        return out
    return {"UNAVAILABLE_ON_THIS_MESH": True, "reason": f"no y-line found with >= {min_points} points"}


def depletion_volume_weighted_columns(x, nv, majority, background, xj_cm, side):
    groups = {}
    for i, xv in enumerate(x):
        groups.setdefault(xv, []).append(i)
    profile = []
    for xv, idxs in groups.items():
        wsum = sum(nv[i] for i in idxs)
        if wsum <= 0:
            continue
        m_avg = sum(majority[i] * nv[i] for i in idxs) / wsum
        b_avg = sum(background[i] * nv[i] for i in idxs) / wsum
        profile.append((xv, m_avg, b_avg))
    pts = sorted((t for t in profile if (t[0] > xj_cm if side == "+" else t[0] < xj_cm)), key=lambda t: abs(t[0] - xj_cm))
    out = {"n_columns_used": len(profile)}
    for frac in (0.5, 0.9, 0.99):
        hit = next((abs(xv - xj_cm) for xv, m, b in pts if b > 0 and m >= frac * b), None)
        out[f"recovery_{int(frac * 100)}pct_cm"] = hit
    return out


# ---------------------------------------------------------------------------------------------- equilibrium solve
def equilibrium(device, region, contacts, relative_error=1e-6, maximum_iterations=100):
    SetSiliconParameters(device, region, 300)
    devsim.set_parameter(device=device, region=region, name="taun", value=1e-8)
    devsim.set_parameter(device=device, region=region, name="taup", value=1e-8)
    CreateSolution(device, region, "Potential")
    CreateSiliconPotentialOnly(device, region)
    for c in contacts:
        devsim.set_parameter(device=device, name=GetContactBiasName(c), value=0.0)
        CreateSiliconPotentialOnlyContact(device, region, c)
    try:
        devsim.solve(type="dc", absolute_error=1.0, relative_error=relative_error, maximum_iterations=maximum_iterations)
        ok1 = True
    except Exception:
        ok1 = False
    CreateSolution(device, region, "Electrons")
    CreateSolution(device, region, "Holes")
    devsim.set_node_values(device=device, region=region, name="Electrons", init_from="IntrinsicElectrons")
    devsim.set_node_values(device=device, region=region, name="Holes", init_from="IntrinsicHoles")
    CreateSiliconDriftDiffusion(device, region)
    for c in contacts:
        CreateSiliconDriftDiffusionAtContact(device, region, c)
    try:
        devsim.solve(type="dc", absolute_error=1e10, relative_error=relative_error, maximum_iterations=maximum_iterations)
        ok2 = True
    except Exception:
        ok2 = False
    return ok1 and ok2


# ---------------------------------------------------------------------------------------------- run
def run_imported(level, representation, shifted, label):
    tmp_ctx = tempfile.TemporaryDirectory()
    device_name, mesh_name = f"d_{label}", f"m_{label}"
    try:
        points_um, triangles, tags, _ = build_imported_mesh_raw(level, tmp_ctx.name)

        whole, band, ring, outer = classify_by_x_band(points_um, triangles, XJ_UM, BAND_HALF_WIDTH_UM, RING_MULTIPLIER)
        mesh_quality_result = {
            "whole": analyze_triangle_subset(points_um, triangles, whole),
            "junction_band": analyze_triangle_subset(points_um, triangles, band),
            "transition_ring": analyze_triangle_subset(points_um, triangles, ring),
            "coarse_outer": analyze_triangle_subset(points_um, triangles, outer),
        }

        region, mesh_name, contacts = import_imported_mesh(points_um, triangles, tags, device_name, mesh_name)

        x_native = devsim.get_node_model_values(device=device_name, region=region, name="x")
        y_native = devsim.get_node_model_values(device=device_name, region=region, name="y")
        x0, x1 = locate_junction(x_native, um_to_cm(XJ_UM))
        local_spacing = x1 - x0
        xj_shifted = (x0 + x1) / 2.0
        xj_used = xj_shifted if shifted else x0

        # contact geometry
        contact_geometry = {}
        for cname in contacts:
            try:
                clist = devsim.get_contact_list(device=device_name)
            except Exception:
                clist = contacts
            contact_geometry[cname] = {"in_contact_list": cname in clist}

        set_doping(device_name, region, representation, xj_used)
        inv = dopant_inventory(device_name, region, xj_used)
        # Spike A compared sum(NodeVolume) against the ACTUAL triangulated
        # area (sum of real triangle areas), not a naive bounding-box
        # rectangle -- a bounding box can only ever be >= the true
        # triangulated area for a convex mesh, so bbox is not the right
        # comparison on a real, possibly-irregular imported/refined mesh.
        # mesh_quality_result's triangle areas are in the mesh's NATIVE um
        # units (computed pre-import, before *LENGTH_SCALE); NodeVolume is
        # in cm^2 (DevSim's own convention, confirmed by spike A) -- must
        # convert um^2 -> cm^2 (LENGTH_SCALE**2) before comparing.
        tri_area_sum = mesh_quality_result["whole"]["triangle_area_sum"] * (LENGTH_SCALE ** 2)
        inv["triangulated_area_sum_cm2"] = tri_area_sum
        inv["sum_NodeVolume_vs_triangulated_area_relative_error"] = (
            abs(inv["sum_NodeVolume_cm2"] - tri_area_sum) / tri_area_sum if tri_area_sum > 0 else None)
        col = junction_column_volume(device_name, region, x0)

        donors_all = devsim.get_node_model_values(device=device_name, region=region, name="Donors")
        acceptors_all = devsim.get_node_model_values(device=device_name, region=region, name="Acceptors")
        doping_fingerprint = {"donors_sha256": None, "acceptors_sha256": None}
        import hashlib
        doping_fingerprint["donors_sha256"] = hashlib.sha256(json.dumps(list(donors_all)).encode()).hexdigest()
        doping_fingerprint["acceptors_sha256"] = hashlib.sha256(json.dumps(list(acceptors_all)).encode()).hexdigest()

        ok = equilibrium(device_name, region, contacts)

        result = {
            "label": label, "mode": "imported", "level": level, "representation": representation, "shifted": shifted,
            "n_nodes": len(x_native), "x0_cm": x0, "x1_cm": x1, "local_spacing_cm": local_spacing,
            "xj_used_cm": xj_used, "contacts": contacts, "contact_geometry": contact_geometry,
            "mesh_quality": mesh_quality_result, "inventory": inv, "junction_column": col,
            "doping_fingerprint": doping_fingerprint, "equilibrium_converged": ok,
            "field": None, "y_invariance": None,
            "depletion_old_ycollapsed_donor_side": None, "depletion_old_ycollapsed_acceptor_side": None,
            "depletion_center_yline_donor_side": None, "depletion_center_yline_acceptor_side": None,
            "depletion_volume_weighted_donor_side": None, "depletion_volume_weighted_acceptor_side": None,
        }
        if ok:
            result["field"] = element_field_analysis(device_name, region, x_native, y_native,
                                                      band_half_width_cm=um_to_cm(BAND_HALF_WIDTH_UM), contacts_x_cm=(x0, x1))
            pot = devsim.get_node_model_values(device=device_name, region=region, name="Potential")
            electrons = devsim.get_node_model_values(device=device_name, region=region, name="Electrons")
            holes = devsim.get_node_model_values(device=device_name, region=region, name="Holes")
            nets = devsim.get_node_model_values(device=device_name, region=region, name="NetDoping")
            nv = devsim.get_node_model_values(device=device_name, region=region, name="NodeVolume")
            result["y_invariance"] = y_invariance(x_native, {"Potential": pot, "Electrons": electrons, "Holes": holes, "NetDoping": nets})
            result["depletion_old_ycollapsed_donor_side"] = depletion_old_ycollapsed(x_native, electrons, donors_all, xj_used, "+")
            result["depletion_old_ycollapsed_acceptor_side"] = depletion_old_ycollapsed(x_native, holes, acceptors_all, xj_used, "-")
            result["depletion_center_yline_donor_side"] = depletion_center_yline(x_native, y_native, electrons, donors_all, xj_used, "+")
            result["depletion_center_yline_acceptor_side"] = depletion_center_yline(x_native, y_native, holes, acceptors_all, xj_used, "-")
            result["depletion_volume_weighted_donor_side"] = depletion_volume_weighted_columns(x_native, nv, electrons, donors_all, xj_used, "+")
            result["depletion_volume_weighted_acceptor_side"] = depletion_volume_weighted_columns(x_native, nv, holes, acceptors_all, xj_used, "-")
        return result
    finally:
        for fn, kw in ((devsim.delete_device, {"device": device_name}), (devsim.delete_mesh, {"mesh": mesh_name})):
            try:
                fn(**kw)
            except Exception:
                pass
        tmp_ctx.cleanup()


def run_structured(level_equiv, representation, shifted, label, diagonal="fixed", y_extent_um=None, band_spacing_um=None):
    device_name, mesh_name = f"d_{label}", f"m_{label}"
    y_extent_um = y_extent_um or RECIPE_2D["y_extent_um"]
    n_y = 30
    try:
        x_lines = build_x_lines_um(BAND_HALF_WIDTH_UM, band_spacing_um, RECIPE_2D["x_extent_um"], RECIPE_2D["grid_delta_um"])
        points_um, triangles, tags = build_structured_triangulation(x_lines, y_extent_um, n_y, diagonal=diagonal)

        whole, band, ring, outer = classify_by_x_band(points_um, triangles, XJ_UM, BAND_HALF_WIDTH_UM, RING_MULTIPLIER)
        mesh_quality_result = {
            "whole": analyze_triangle_subset(points_um, triangles, whole),
            "junction_band": analyze_triangle_subset(points_um, triangles, band),
            "transition_ring": analyze_triangle_subset(points_um, triangles, ring),
            "coarse_outer": analyze_triangle_subset(points_um, triangles, outer),
        }

        region, mesh_name, contacts = import_structured_device(devsim, points_um, triangles, tags, device_name, mesh_name, LENGTH_SCALE)

        x_native = devsim.get_node_model_values(device=device_name, region=region, name="x")
        y_native = devsim.get_node_model_values(device=device_name, region=region, name="y")
        x0, x1 = locate_junction(x_native, um_to_cm(XJ_UM))
        local_spacing = x1 - x0
        xj_shifted = (x0 + x1) / 2.0
        xj_used = xj_shifted if shifted else x0

        set_doping(device_name, region, representation, xj_used)
        inv = dopant_inventory(device_name, region, xj_used)
        # Spike A compared sum(NodeVolume) against the ACTUAL triangulated
        # area (sum of real triangle areas), not a naive bounding-box
        # rectangle -- a bounding box can only ever be >= the true
        # triangulated area for a convex mesh, so bbox is not the right
        # comparison on a real, possibly-irregular imported/refined mesh.
        # mesh_quality_result's triangle areas are in the mesh's NATIVE um
        # units (computed pre-import, before *LENGTH_SCALE); NodeVolume is
        # in cm^2 (DevSim's own convention, confirmed by spike A) -- must
        # convert um^2 -> cm^2 (LENGTH_SCALE**2) before comparing.
        tri_area_sum = mesh_quality_result["whole"]["triangle_area_sum"] * (LENGTH_SCALE ** 2)
        inv["triangulated_area_sum_cm2"] = tri_area_sum
        inv["sum_NodeVolume_vs_triangulated_area_relative_error"] = (
            abs(inv["sum_NodeVolume_cm2"] - tri_area_sum) / tri_area_sum if tri_area_sum > 0 else None)
        col = junction_column_volume(device_name, region, x0)

        donors_all = devsim.get_node_model_values(device=device_name, region=region, name="Donors")
        acceptors_all = devsim.get_node_model_values(device=device_name, region=region, name="Acceptors")
        import hashlib
        doping_fingerprint = {
            "donors_sha256": hashlib.sha256(json.dumps(list(donors_all)).encode()).hexdigest(),
            "acceptors_sha256": hashlib.sha256(json.dumps(list(acceptors_all)).encode()).hexdigest(),
        }

        ok = equilibrium(device_name, region, contacts)

        BIAS = [-0.3, 0.0, 0.3, 0.4]
        bias_points = []
        if ok:
            p_contact, n_contact = min(contacts), max(contacts)
            from devsim.python_packages.simple_physics import ece_name, hce_name
            for v in BIAS:
                devsim.set_parameter(device=device_name, name=GetContactBiasName(n_contact), value=v)
                devsim.set_parameter(device=device_name, name=GetContactBiasName(p_contact), value=0.0)
                try:
                    devsim.solve(type="dc", absolute_error=1e10, relative_error=1e-6, maximum_iterations=100)
                    cur = {c: devsim.get_contact_current(device=device_name, contact=c, equation=ece_name)
                          + devsim.get_contact_current(device=device_name, contact=c, equation=hce_name) for c in contacts}
                    bias_points.append({"v_bias": v, "converged": True, "currents": cur,
                                        "conservation_error": abs(sum(cur.values()))})
                except Exception as exc:
                    bias_points.append({"v_bias": v, "converged": False, "error": str(exc)})
                    break

        result = {
            "label": label, "mode": "structured", "level_equiv": level_equiv, "representation": representation,
            "shifted": shifted, "diagonal": diagonal, "y_extent_um": y_extent_um, "band_spacing_um": band_spacing_um,
            "n_nodes": len(x_native), "x0_cm": x0, "x1_cm": x1, "local_spacing_cm": local_spacing,
            "xj_used_cm": xj_used, "contacts": contacts,
            "mesh_quality": mesh_quality_result, "inventory": inv, "junction_column": col,
            "doping_fingerprint": doping_fingerprint, "equilibrium_converged": ok, "bias_points": bias_points,
            "field": None, "y_invariance": None,
            "depletion_old_ycollapsed_donor_side": None, "depletion_old_ycollapsed_acceptor_side": None,
            "depletion_center_yline_donor_side": None, "depletion_center_yline_acceptor_side": None,
            "depletion_volume_weighted_donor_side": None, "depletion_volume_weighted_acceptor_side": None,
        }
        if ok:
            result["field"] = element_field_analysis(device_name, region, x_native, y_native,
                                                      band_half_width_cm=um_to_cm(BAND_HALF_WIDTH_UM), contacts_x_cm=(x0, x1))
            pot = devsim.get_node_model_values(device=device_name, region=region, name="Potential")
            electrons = devsim.get_node_model_values(device=device_name, region=region, name="Electrons")
            holes = devsim.get_node_model_values(device=device_name, region=region, name="Holes")
            nets = devsim.get_node_model_values(device=device_name, region=region, name="NetDoping")
            nv = devsim.get_node_model_values(device=device_name, region=region, name="NodeVolume")
            result["y_invariance"] = y_invariance(x_native, {"Potential": pot, "Electrons": electrons, "Holes": holes, "NetDoping": nets})
            result["depletion_old_ycollapsed_donor_side"] = depletion_old_ycollapsed(x_native, electrons, donors_all, xj_used, "+")
            result["depletion_old_ycollapsed_acceptor_side"] = depletion_old_ycollapsed(x_native, holes, acceptors_all, xj_used, "-")
            result["depletion_center_yline_donor_side"] = depletion_center_yline(x_native, y_native, electrons, donors_all, xj_used, "+")
            result["depletion_center_yline_acceptor_side"] = depletion_center_yline(x_native, y_native, holes, acceptors_all, xj_used, "-")
            result["depletion_volume_weighted_donor_side"] = depletion_volume_weighted_columns(x_native, nv, electrons, donors_all, xj_used, "+")
            result["depletion_volume_weighted_acceptor_side"] = depletion_volume_weighted_columns(x_native, nv, holes, acceptors_all, xj_used, "-")
        return result
    finally:
        for fn, kw in ((devsim.delete_device, {"device": device_name}), (devsim.delete_mesh, {"mesh": mesh_name})):
            try:
                fn(**kw)
            except Exception:
                pass


if __name__ == "__main__":
    args = json.loads(sys.argv[1])
    mode = args["mode"]
    if mode == "imported":
        r = run_imported(args["level"], args["representation"], args["shifted"], args["label"])
    else:
        r = run_structured(args["level_equiv"], args["representation"], args["shifted"], args["label"],
                           diagonal=args.get("diagonal", "fixed"), y_extent_um=args.get("y_extent_um"),
                           band_spacing_um=args["band_spacing_um"])
    print("===RESULT_JSON===")
    print(json.dumps(r, default=str))
