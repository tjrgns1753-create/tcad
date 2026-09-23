"""Batch 7G Phase 1: run the geometry_checks suite (validated against 7
synthetic fixtures first, see test_geometry_checks_synthetic.py) against a
real mesh -- raw ViennaPS, imported L3/L4/L5 (refine_mesh_near reused
read-only from production), or structured L3/L4/L5 (Batch 7F's own
structured_mesh.py, unchanged, reused read-only). One mesh per subprocess.
Public DEVSIM API only for the NodeVolume-vs-barycentric-area comparison
(everything else is pure numpy, no DevSim needed).
"""
import json
import os
import sys
import tempfile
import time
import warnings

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
warnings.simplefilter("ignore")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "docs", "audits", "2026-09-22-batch7f-step-junction-root-cause", "scripts"))

from geometry_checks import (  # noqa: E402
    local_delaunay_check, triangle_geometry_table, edge_cotangent_weights,
    hanging_node_check, triangle_overlap_check, boundary_loops_and_hole_check,
)
from mesh_quality import classify_by_x_band  # noqa: E402 (Batch 7F's own, reused read-only)
from structured_mesh import build_x_lines_um, build_structured_triangulation, import_structured_device  # noqa: E402

XJ_UM, LENGTH_SCALE = 0.0, 1.0e-4
BAND_HALF_WIDTH_UM = 0.1
RING_MULTIPLIER = 3.0
RECIPE_2D = {"grid_delta_um": 0.2, "x_extent_um": 4.0, "y_extent_um": 3.0, "silicon_depth_um": 2.0}


def build_raw_or_imported(level):
    """level=None -> RAW ViennaPS mesh, no refine_mesh_near() at all.
    level=int -> refine_mesh_near() applied exactly like import_process_result()
    and Batch 7F's own probe (levels=level+1), reused read-only."""
    from tcad.backends.viennaps import session as vsession
    from tcad.backends.viennaps.io import save_volume_mesh
    from tcad.device.devsim.mesh_refine import refine_mesh_near
    import meshio

    tmp = tempfile.mkdtemp()
    domain = vsession.make_mask_spans(
        grid_delta_um=RECIPE_2D["grid_delta_um"], x_extent_um=RECIPE_2D["x_extent_um"], y_extent_um=RECIPE_2D["y_extent_um"],
        spans_um=[], mask_height_um=0.1, substrate_depth_um=RECIPE_2D["silicon_depth_um"] + 1.0,
    )
    mesh_path = save_volume_mesh(domain, os.path.join(tmp, "virgin_wafer"), floor_depth_um=RECIPE_2D["silicon_depth_um"])
    mesh = meshio.read(mesh_path)
    triangle_block = next(c for c in mesh.cells if c.type == "triangle")
    block_index = mesh.cells.index(triangle_block)
    triangles = triangle_block.data
    tags = mesh.cell_data["Material"][block_index]
    raw_points = mesh.points[:, :2].copy()

    if level is None:
        return raw_points, np.array(triangles), np.array(tags)

    def _near_refine_target(centroid):
        return abs(centroid[0] - XJ_UM) < BAND_HALF_WIDTH_UM

    pts, tri, tg = refine_mesh_near(raw_points, triangles, tags, _near_refine_target, levels=level + 1)
    return pts, tri, tg


def build_structured(level_equiv, band_spacing_um):
    xl = build_x_lines_um(BAND_HALF_WIDTH_UM, band_spacing_um, RECIPE_2D["x_extent_um"], RECIPE_2D["grid_delta_um"])
    pts, tri, tags = build_structured_triangulation(xl, RECIPE_2D["y_extent_um"], 30, diagonal="fixed")
    return pts, tri, tags


def node_volume_vs_barycentric(points_um, triangles, device_name, mesh_name):
    import devsim
    region, mesh_name, contacts = import_structured_device(devsim, points_um, triangles,
                                                            np.zeros(len(triangles), dtype=np.int64),
                                                            device_name, mesh_name, LENGTH_SCALE)
    x = devsim.get_node_model_values(device=device_name, region=region, name="x")
    y = devsim.get_node_model_values(device=device_name, region=region, name="y")
    nv = devsim.get_node_model_values(device=device_name, region=region, name="NodeVolume")

    # A_barycentric(node) = sum(incident triangle area)/3 -- reference only,
    # NEVER called "DEVSIM's own dual-volume definition".
    bary = np.zeros(len(points_um))
    for tri in triangles:
        p0, p1, p2 = points_um[tri[0]], points_um[tri[1]], points_um[tri[2]]
        area_um2 = abs((p1[0] - p0[0]) * (p2[1] - p0[1]) - (p2[0] - p0[0]) * (p1[1] - p0[1])) / 2.0
        area_cm2 = area_um2 * (LENGTH_SCALE ** 2)
        for v in tri:
            bary[v] += area_cm2 / 3.0

    devsim.delete_device(device=device_name)
    devsim.delete_mesh(mesh=mesh_name)
    return list(x), list(y), list(nv), bary.tolist()


def run(spec):
    t_start = time.time()
    mode = spec["mode"]
    if mode == "raw":
        pts, tri, tags = build_raw_or_imported(None)
    elif mode == "imported":
        pts, tri, tags = build_raw_or_imported(spec["level"])
    else:
        pts, tri, tags = build_structured(spec["level_equiv"], spec["band_spacing_um"])

    tags = np.asarray(tags)
    t_mesh = time.time()

    interior, constrained = local_delaunay_check(pts, tri, tags)
    t_delaunay = time.time()

    geo = triangle_geometry_table(pts, tri)
    t_geo = time.time()

    cot = edge_cotangent_weights(pts, tri, tags)
    t_cot = time.time()

    hang = hanging_node_check(pts, tri, tags)
    t_hang = time.time()

    overlaps, n_checked_pairs = triangle_overlap_check(pts, tri, tags)
    t_overlap = time.time()

    hole = boundary_loops_and_hole_check(pts, tri)
    t_hole = time.time()

    # zone classification for interior-edge violations and per-node results
    whole_idx, band_idx, ring_idx, outer_idx = classify_by_x_band(pts, tri, XJ_UM, BAND_HALF_WIDTH_UM, RING_MULTIPLIER)
    tri_zone = {}
    for zset, name in ((band_idx, "band"), (ring_idx, "ring"), (outer_idx, "outer")):
        for ti in zset:
            tri_zone[int(ti)] = name

    def edge_zone(e):
        t1, t2 = e["owners"] if "owners" in e else e["edge"]
        z1 = tri_zone.get(int(t1) if "owners" in e else -1, "unknown")
        return z1

    violations = [e for e in interior if e["angle_sum_violation"]]
    for e in violations:
        t1 = e["owners"][0]
        e["zone"] = tri_zone.get(int(t1), "unknown")

    device_name, mesh_name = f"d_{spec['label']}", f"m_{spec['label']}"
    x_native, y_native, nv, bary = node_volume_vs_barycentric(pts, tri, device_name, mesh_name)
    t_nv = time.time()

    nv_arr = np.array(nv)
    bary_arr = np.array(bary)
    excess = nv_arr - bary_arr
    total_excess = float(excess.sum())
    total_nv = float(nv_arr.sum())

    node_x_um = [xv / LENGTH_SCALE for xv in x_native]
    node_zone = []
    for xv in node_x_um:
        dx = abs(xv - XJ_UM)
        if dx < BAND_HALF_WIDTH_UM:
            node_zone.append("band")
        elif dx < RING_MULTIPLIER * BAND_HALF_WIDTH_UM:
            node_zone.append("ring")
        else:
            node_zone.append("outer")

    excess_by_zone = {"band": 0.0, "ring": 0.0, "outer": 0.0}
    for z, exc in zip(node_zone, excess):
        excess_by_zone[z] += float(exc)

    top20_idx = np.argsort(-np.abs(excess))[:20]
    top20 = [{"node": int(i), "x_um": node_x_um[i], "y_cm": y_native[i], "zone": node_zone[i],
             "NodeVolume": float(nv_arr[i]), "barycentric": float(bary_arr[i]), "excess": float(excess[i])}
             for i in top20_idx]

    result = {
        "label": spec["label"], "mode": mode, "n_points": len(pts), "n_triangles": len(tri),
        "n_interior_unconstrained_edges": len(interior), "n_constrained_edges": len(constrained),
        "n_delaunay_violations": len(violations),
        "delaunay_violation_rate": len(violations) / len(interior) if interior else 0.0,
        "violations_by_zone": {z: sum(1 for v in violations if v.get("zone") == z) for z in ("band", "ring", "outer", "unknown")},
        "max_violation_severity_rad": max((v["severity_rad"] for v in violations), default=0.0),
        "n_negative_cotangent_weights": sum(1 for c in cot if c["negative_candidate"]),
        "n_hanging_nodes": len(hang), "hanging_node_sample": hang[:10],
        "n_overlap_pairs": len(overlaps), "overlap_pairs_checked": n_checked_pairs, "total_overlap_area_um2": sum(o["overlap_area"] for o in overlaps),
        "boundary_holes": hole,
        "sum_NodeVolume_cm2": total_nv, "sum_barycentric_cm2": float(bary_arr.sum()),
        "total_excess_cm2": total_excess, "total_excess_relative": total_excess / float(bary_arr.sum()) if bary_arr.sum() else None,
        "excess_by_zone_cm2": excess_by_zone,
        "excess_fraction_in_ring": excess_by_zone["ring"] / total_excess if total_excess else None,
        "top20_excess_nodes": top20,
        "timing_s": {"mesh": t_mesh - t_start, "delaunay": t_delaunay - t_mesh, "geo": t_geo - t_delaunay,
                    "cot": t_cot - t_geo, "hanging": t_hang - t_cot, "overlap": t_overlap - t_hang,
                    "hole": t_hole - t_overlap, "nodevolume": t_nv - t_hole, "total": time.time() - t_start},
    }
    return result


if __name__ == "__main__":
    spec = json.loads(sys.argv[1])
    r = run(spec)
    print("===RESULT_JSON===")
    print(json.dumps(r, default=str))
