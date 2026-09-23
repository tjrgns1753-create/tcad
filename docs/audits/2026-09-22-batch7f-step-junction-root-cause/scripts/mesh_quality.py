"""Batch 7F: pure numpy mesh-quality metrics over raw (points, triangles) arrays.
No DevSim, no solve -- read-only geometry analysis, reused by both the imported
(ViennaPS) and structured-control probes.
"""
import numpy as np


def _edge_key(a, b):
    return (a, b) if a < b else (b, a)


def triangle_signed_area(p0, p1, p2):
    return 0.5 * ((p1[0] - p0[0]) * (p2[1] - p0[1]) - (p2[0] - p0[0]) * (p1[1] - p0[1]))


def edge_lengths_for_triangle(p0, p1, p2):
    e01 = np.linalg.norm(p1 - p0)
    e12 = np.linalg.norm(p2 - p1)
    e20 = np.linalg.norm(p0 - p2)
    return e01, e12, e20


def triangle_min_angle_deg(p0, p1, p2):
    def angle_at(a, b, c):
        v1, v2 = b - a, c - a
        cosang = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-300)
        cosang = max(-1.0, min(1.0, cosang))
        return np.degrees(np.arccos(cosang))
    a0 = angle_at(p0, p1, p2)
    a1 = angle_at(p1, p2, p0)
    a2 = angle_at(p2, p0, p1)
    return min(a0, a1, a2)


def analyze_triangle_subset(points, triangles, indices):
    """All metrics for the triangle subset named by `indices` (into `triangles`)."""
    if len(indices) == 0:
        return {"n_triangles": 0}
    tris = triangles[indices]
    pts_used = np.unique(tris.flatten())
    n_nodes = len(pts_used)

    edge_owners = {}
    zero_area = 0
    flipped = 0
    areas = []
    min_angles = []
    aspect_ratios = []
    edge_len_all = []
    coord_set = {}
    dup_coords = 0

    for ti in indices:
        v0, v1, v2 = (int(x) for x in triangles[ti])
        p0, p1, p2 = points[v0], points[v1], points[v2]
        signed = triangle_signed_area(p0, p1, p2)
        area = abs(signed)
        areas.append(area)
        if area < 1e-20:
            zero_area += 1
        if signed < 0:
            flipped += 1
        e01, e12, e20 = edge_lengths_for_triangle(p0, p1, p2)
        edge_len_all += [e01, e12, e20]
        longest = max(e01, e12, e20)
        shortest_altitude = (2.0 * area / longest) if longest > 0 else 0.0
        aspect_ratios.append(longest / shortest_altitude if shortest_altitude > 1e-300 else float("inf"))
        min_angles.append(triangle_min_angle_deg(p0, p1, p2))
        for a, b in ((v0, v1), (v1, v2), (v2, v0)):
            edge_owners.setdefault(_edge_key(a, b), []).append(ti)

    for pid in pts_used:
        key = (round(float(points[pid][0]), 15), round(float(points[pid][1]), 15))
        coord_set.setdefault(key, []).append(int(pid))
    dup_coords = sum(len(v) - 1 for v in coord_set.values() if len(v) > 1)

    non_manifold = sum(1 for owners in edge_owners.values() if len(owners) > 2)
    unique_edges = len(edge_owners)

    def stats(vals):
        if not vals:
            return {"min": None, "median": None, "max": None}
        arr = np.array(vals, dtype=float)
        finite = arr[np.isfinite(arr)]
        return {
            "min": float(np.min(arr)), "median": float(np.median(finite)) if len(finite) else None,
            "max": float(np.max(arr)) if np.isfinite(np.max(arr)) else "inf",
        }

    return {
        "n_triangles": len(indices), "n_nodes": n_nodes,
        "n_unique_edges": unique_edges, "n_duplicate_coords": dup_coords,
        "n_zero_area_triangles": zero_area, "n_flipped_orientation_triangles": flipped,
        "n_non_manifold_edges": non_manifold,
        "edge_length": stats(edge_len_all),
        "triangle_area": stats(areas),
        "triangle_area_sum": float(sum(areas)),
        "triangle_min_angle_deg": stats(min_angles),
        "aspect_ratio_longest_edge_over_shortest_altitude": stats(aspect_ratios),
    }


def classify_by_x_band(points, triangles, junction_x_native, band_half_width, ring_multiplier=3.0):
    """Returns index arrays (whole, band, ring, outer) by triangle centroid x,
    in the mesh's NATIVE coordinate units (same units as junction_x_native and
    band_half_width -- caller passes um for the imported mesh, matching the
    project's own refine_mesh_near() predicate exactly)."""
    centroids_x = points[triangles].mean(axis=1)[:, 0]
    dx = np.abs(centroids_x - junction_x_native)
    band = np.where(dx < band_half_width)[0]
    ring = np.where((dx >= band_half_width) & (dx < ring_multiplier * band_half_width))[0]
    outer = np.where(dx >= ring_multiplier * band_half_width)[0]
    whole = np.arange(len(triangles))
    return whole, band, ring, outer
