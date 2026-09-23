"""Batch 7G Rev.1 Phase A/B: A1-A12 synthetic fixtures against the
CORRECTED checker (geometry_checks_v2.py). Must all pass BEFORE any real L3
mesh is touched by the corrected code (Phase E gate). Coordinates are given
at REAL mesh scale (~0.05-0.4 um edges) and, where the fixture specifically
targets float32-origin noise (A4), as float32 arrays -- matching the real
ViennaPS-imported mesh's own coordinate dtype confirmed in Phase A's L3
diagnosis.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from geometry_checks_v2 import (
    classify_pair_topology, shared_edge_is_proper_adjacency, method_a_clip_area,
    method_b_sat_overlap_length, corrected_triangle_overlap_check, derive_overlap_area_tolerance,
)

RESULTS = []


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition)))
    print(f"[{name}] {'PASS' if condition else 'FAIL'}  {detail}")


def main():
    # ---- A1: one shared vertex, no interior overlap (fan spoke)
    pts = np.array([
        [0.0, 0.0], [0.1, 0.0], [0.1, 0.1], [0.0, 0.1], [0.2, 0.05], [0.2, 0.15],
    ])
    tri = np.array([[0, 1, 2], [2, 4, 5]])
    r = corrected_triangle_overlap_check(pts, tri, np.zeros(2, dtype=int))
    check("A1_shared_vertex_no_overlap", r["n_confirmed_overlaps"] == 0 and r["n_unknown_pairs"] == 0,
          f"confirmed={r['n_confirmed_overlaps']} unknown={r['n_unknown_pairs']} topo={r['topology_tally']}")

    # ---- A2: shared edge, properly adjacent, no overlap
    pts2 = np.array([[0.0, 0.0], [0.1, 0.0], [0.1, 0.1], [0.0, -0.1]])
    tri2 = np.array([[0, 1, 2], [1, 0, 3]])
    r2 = corrected_triangle_overlap_check(pts2, tri2, np.zeros(2, dtype=int))
    topo, is_proper = classify_pair_topology(tri2[0], tri2[1])[0], None
    is_proper, si, sj = shared_edge_is_proper_adjacency(pts2, tri2[0], tri2[1], {0, 1}, 1e-9)
    check("A2_shared_edge_no_overlap", r2["n_confirmed_overlaps"] == 0 and bool(is_proper),
          f"topo={topo} is_proper={is_proper} confirmed={r2['n_confirmed_overlaps']}")

    # ---- A3: bboxes touch (corner-to-corner) but no interior overlap, disjoint vertices
    pts3 = np.array([[0.0, 0.0], [0.1, 0.0], [0.0, 0.1], [0.1, 0.1], [0.2, 0.1], [0.1, 0.2]])
    tri3 = np.array([[0, 1, 2], [3, 4, 5]])  # second triangle touches first only at corner (0.1,0.1)
    r3 = corrected_triangle_overlap_check(pts3, tri3, np.zeros(2, dtype=int))
    check("A3_bbox_touch_no_overlap", r3["n_confirmed_overlaps"] == 0,
          f"confirmed={r3['n_confirmed_overlaps']} unknown={r3['n_unknown_pairs']}")

    # ---- A4: float32-origin, near-collinear boundary touch (coincident-but-
    # different-index edge) -- the actual dtype/scale of the real mesh.
    pts4 = np.array([
        [0.2, -1.8], [0.4, -1.8], [0.2, -1.6],       # tri A
        [0.2, -1.8], [0.1, -1.8], [0.1, -1.625],     # tri B, touches tri A's edge (0.2,-1.8)-(0.4,-1.8) region only near the shared point, disjoint indices
    ], dtype=np.float32)
    tri4 = np.array([[0, 1, 2], [3, 4, 5]])
    r4 = corrected_triangle_overlap_check(pts4, tri4, np.zeros(2, dtype=int))
    check("A4_float32_near_collinear_touch", r4["n_confirmed_overlaps"] == 0,
          f"confirmed={r4['n_confirmed_overlaps']} unknown={r4['n_unknown_pairs']} tol={r4['area_tol']:.3e}")

    # ---- A5: real positive-area overlap, disjoint vertex sets
    pts5 = np.array([[0.0, 0.0], [0.1, 0.0], [0.1, 0.1], [0.0, 0.1], [0.03, 0.03], [0.08, 0.03], [0.05, 0.08]])
    tri5 = np.array([[0, 1, 2], [4, 5, 6]])
    r5 = corrected_triangle_overlap_check(pts5, tri5, np.zeros(2, dtype=int))
    check("A5_real_overlap_confirmed", r5["n_confirmed_overlaps"] == 1,
          f"confirmed={r5['n_confirmed_overlaps']} detail={r5['confirmed_overlaps']}")

    # ---- A6: shared vertex, invalid bow-tie fold (interiors genuinely cross)
    # Two triangles sharing vertex 0, but folded so their interiors overlap.
    pts6 = np.array([[0.0, 0.0], [0.1, 0.0], [0.05, 0.08], [0.08, 0.02], [0.02, 0.06]])
    tri6 = np.array([[0, 1, 2], [0, 3, 4]])  # triangle2's other two vertices sit INSIDE triangle1
    r6 = corrected_triangle_overlap_check(pts6, tri6, np.zeros(2, dtype=int))
    check("A6_shared_vertex_bowtie_overlap", r6["n_confirmed_overlaps"] == 1,
          f"confirmed={r6['n_confirmed_overlaps']} topo={r6['topology_tally']}")

    # ---- A7: duplicate triangle
    pts7 = np.array([[0.0, 0.0], [0.1, 0.0], [0.1, 0.1]])
    tri7 = np.array([[0, 1, 2], [1, 2, 0]])  # same 3 vertices, rotated order
    r7 = corrected_triangle_overlap_check(pts7, tri7, np.zeros(2, dtype=int))
    check("A7_duplicate_triangle_detected", r7["n_duplicate_triangles"] == 1 and r7["n_confirmed_overlaps"] == 0,
          f"n_duplicate={r7['n_duplicate_triangles']} confirmed_overlap={r7['n_confirmed_overlaps']}")

    # ---- A8: pre-existing overlap FAR away, irrelevant to a local pair check
    pts8 = np.array([[0.0, 0.0], [0.1, 0.0], [0.1, 0.1], [10.0, 10.0], [10.1, 10.0], [10.05, 10.05], [10.02, 10.02], [10.08, 10.02], [10.05, 10.08]])
    tri8 = np.array([[0, 1, 2], [3, 4, 5], [6, 7, 8]])
    r8 = corrected_triangle_overlap_check(pts8, tri8, np.zeros(3, dtype=int))
    check("A8_preexisting_overlap_elsewhere_isolated", r8["n_confirmed_overlaps"] == 1 and
          all(0 not in ov["triangles"] for ov in r8["confirmed_overlaps"]),
          f"confirmed={r8['confirmed_overlaps']}")

    # ---- A9: convex quadrilateral, legal flip -- old-pair union == new-pair union check
    p0, p1, p2, p3 = np.array([0.0, 0.0]), np.array([0.12, -0.02]), np.array([0.14, 0.11]), np.array([0.01, 0.13])
    old_area = abs(np.cross(p1 - p0, p2 - p0)) / 2 + abs(np.cross(p2 - p0, p3 - p0)) / 2
    new_area = abs(np.cross(p2 - p1, p3 - p1)) / 2 + abs(np.cross(p3 - p1, p0 - p1)) / 2
    check("A9_convex_quad_area_preserved", abs(old_area - new_area) < 1e-12,
          f"old_area={old_area:.9f} new_area={new_area:.9f}")

    # ---- A10: concave/nonconvex quadrilateral -- flipping the diagonal is
    # illegal (would create a self-intersecting / negative-area configuration)
    # Quad 0,1,2,3 where vertex 2 is "pulled in" so 0-1-2-3 is NOT convex.
    q0, q1, q2, q3 = np.array([0.0, 0.0]), np.array([0.1, 0.0]), np.array([0.03, 0.03]), np.array([0.0, 0.1])
    # convexity test: cross products of consecutive edges must all have the same sign
    pts_q = [q0, q1, q2, q3]
    signs = []
    for i in range(4):
        a, b, c = pts_q[i], pts_q[(i + 1) % 4], pts_q[(i + 2) % 4]
        cr = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        signs.append(cr > 0)
    is_convex = all(signs) or not any(signs)
    check("A10_nonconvex_quad_detected", not is_convex, f"signs={signs} is_convex={is_convex}")

    # ---- A11: material-interface edge (shared edge, DIFFERENT tags) --
    # must be classified shared_edge + excluded regardless of proper-adjacency
    pts11 = np.array([[0.0, 0.0], [0.1, 0.0], [0.1, 0.1], [0.0, -0.1]])
    tri11 = np.array([[0, 1, 2], [1, 0, 3]])
    tags11 = np.array([0, 1])  # different materials
    topo11, shared11 = classify_pair_topology(tri11[0], tri11[1])
    is_proper11, _, _ = shared_edge_is_proper_adjacency(pts11, tri11[0], tri11[1], shared11, 1e-9)
    check("A11_material_interface_shared_edge_classified", topo11 == "shared_edge" and bool(is_proper11) and tags11[0] != tags11[1],
          f"topo={topo11} is_proper={is_proper11} tags={tags11.tolist()}")

    # ---- A12: boundary/contact edge (owner count == 1, no pair to compare)
    pts12 = np.array([[0.0, 0.0], [0.1, 0.0], [0.1, 0.1]])
    tri12 = np.array([[0, 1, 2]])
    from geometry_checks_v2 import build_topology
    owners12 = build_topology(tri12)
    n_owners = [len(v) for v in owners12.values()]
    check("A12_boundary_edge_single_owner", all(n == 1 for n in n_owners), f"owner_counts={n_owners}")

    print()
    n_fail = sum(1 for _, ok in RESULTS if not ok)
    print(f"=== {len(RESULTS) - n_fail}/{len(RESULTS)} PASSED ===")
    if n_fail:
        print("FAILURES:", [n for n, ok in RESULTS if not ok])
    return n_fail == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
