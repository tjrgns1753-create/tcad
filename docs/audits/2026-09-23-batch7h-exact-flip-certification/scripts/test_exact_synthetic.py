"""Batch 7H-A Phase A: 14 synthetic fixtures with exact expected verdicts.
All coordinates are float32 (the dtype of the real imported mesh)."""
import os
import sys

sys.dont_write_bytecode = True
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REV1 = os.path.join(HERE, "..", "..", "2026-09-23-batch7g-rev1-overlap-flip-validation", "scripts")
sys.path.insert(0, REV1)

import exact_geometry as eg  # noqa: E402
import exact_flip as ef  # noqa: E402
from geometry_checks_v2 import method_a_clip_area, method_b_sat_overlap_length  # noqa: E402  (Rev.1, read-only)

F = np.float32
REV1_L3_AREA_TOL = 2.9802436074533034e-08   # stored Rev.1 L3 value (PRIOR_RESULT_CORRECTIONS.md item 2)
RESULTS = []


def P(*xy):
    return np.array(xy, dtype=np.float32)


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"[{name}] {'PASS' if cond else 'FAIL'}  {detail}")


def verdict(pts, ti, tj):
    ipts, _ = eg.exact_integer_points(pts)
    return eg.classify_pair(ipts, ti, tj)


def run():
    # A1 shared vertex only
    pts = P([0, 0], [.1, 0], [.1, .1], [0, .1], [.2, .05], [.2, .15])
    v = verdict(pts, (0, 1, 2), (2, 4, 5)); check("A1_shared_vertex_only", v == eg.TOUCH, v)

    # A2 shared edge only
    pts = P([0, 0], [.1, 0], [.1, .1], [0, -.1])
    v = verdict(pts, (0, 1, 2), (1, 0, 3)); check("A2_shared_edge_only", v == eg.TOUCH, v)

    # A3 closed bboxes touch at a corner, triangles do not meet
    pts = P([0, 0], [.1, 0], [0, .1], [.1, .1], [.2, .1], [.1, .2])
    v = verdict(pts, (0, 1, 2), (3, 4, 5)); check("A3_bbox_touch_only", v == eg.DISJOINT, v)

    # A4 float32 near-collinear touch: B's edge tilted by ONE float32 ulp,
    # meeting A only at the common point (0.2,-1.8) (different vertex indices)
    y_up = np.nextafter(F(-1.8), F(0))
    pts = P([.2, -1.8], [.4, -1.8], [.2, -1.6], [.2, -1.8], [.1, 0], [.1, -1.625])
    pts[4] = [F(.1), y_up]
    v = verdict(pts, (0, 1, 2), (3, 4, 5)); check("A4_float32_near_collinear_touch", v == eg.TOUCH, v)

    # A5 small but exact positive overlap
    pts = P([0, 0], [.1, 0], [0, .1], [.09, 0], [.2, 0], [.09, .02])
    ipts, K = eg.exact_integer_points(pts)
    v = eg.classify_pair(ipts, (0, 1, 2), (3, 4, 5))
    _, area = eg.exact_intersection_polygon(ipts, (0, 1, 2), (3, 4, 5), K)
    check("A5_small_exact_positive_overlap", v == eg.POSITIVE and area > 0, f"{v} area={float(area):.3e}")

    # A6 shared-vertex bow-tie (the second triangle's other vertices lie inside the first)
    pts = P([0, 0], [.1, 0], [.05, .08], [.08, .02], [.02, .06])
    v = verdict(pts, (0, 1, 2), (0, 3, 4)); check("A6_shared_vertex_bowtie_overlap", v == eg.POSITIVE, v)

    # A7 duplicate triangle
    pts = P([0, 0], [.1, 0], [.1, .1])
    v = verdict(pts, (0, 1, 2), (1, 2, 0)); check("A7_duplicate_triangle", v == eg.DUPLICATE, v)

    # A8 collinear edge overlap (partial common segment on y=0, interiors on opposite sides)
    pts = P([0, 0], [.2, 0], [.1, .1], [.1, 0], [.3, 0], [.2, -.1])
    v = verdict(pts, (0, 1, 2), (3, 4, 5)); check("A8_collinear_edge_overlap_is_touch", v == eg.TOUCH, v)

    # A9 legal convex flip (kite, non-Delaunay diagonal 1-3)
    pts = P([-1, 0], [0, -3], [1, 0], [0, 1])
    tris, tags, rep = ef.exact_flip(pts, [[0, 1, 3], [1, 2, 3]], [0, 0])
    ipts, K = eg.exact_integer_points(pts)
    union_ok = sum(abs(eg.orient(*[ipts[x] for x in t])) for t in tris) == \
        sum(abs(eg.orient(*[ipts[x] for x in t])) for t in [[0, 1, 3], [1, 2, 3]])
    pair_v = eg.classify_pair(ipts, tris[0], tris[1])
    check("A9_legal_convex_flip", len(rep["history"]) == 1 and rep["terminated"] == "no_exact_violations_remaining"
          and union_ok and pair_v == eg.TOUCH and sorted(map(sorted, tris)) == [[0, 1, 2], [0, 2, 3]],
          f"tris={tris} term={rep['terminated']} union_ok={union_ok} pair={pair_v}")

    # A10 nonconvex quad. An incircle-violating edge always sits in a convex
    # quad (Lawson/de Berg lemma), so the only way to reach the convexity gate
    # is to force the candidate; the gate must reject and leave the mesh unchanged.
    pts = P([0, 0], [2, 0], [3, 1], [3, -.1])
    tris0 = [[0, 1, 2], [1, 0, 3]]
    tris, _, rep = ef.exact_flip(pts, tris0, [0, 0], violation_fn=lambda *a: True, max_passes=3)
    rej = rep["passes"][0]["rejects"]["not_strictly_convex"]
    check("A10_nonconvex_illegal_flip_rejected", tris == tris0 and rej == 1 and not rep["history"],
          f"rejects={rep['passes'][0]['rejects']} term={rep['terminated']}")
    natural = ef.exact_violations(eg.exact_integer_points(pts)[0], tris0, [0, 0], frozenset())
    check("A10b_nonconvex_quad_not_an_exact_violation", natural == [], f"natural_violations={natural}")

    # A11 same-side shared-edge invalid fan
    pts = P([0, 0], [.1, 0], [.05, .1], [.06, .05])
    v = verdict(pts, (0, 1, 2), (0, 1, 3)); check("A11_same_side_shared_edge_fan", v == eg.POSITIVE, v)

    # A12 near the max domain magnitude (|coord| = 2.0): shared-edge touch,
    # then the neighbor's apex moved ONE float32 ulp across the shared edge
    pts = P([1.9, -2.0], [2.0, -1.9], [2.0, -2.0], [1.9, -1.9])
    v1 = verdict(pts, (0, 1, 2), (0, 1, 3))
    pts2 = pts.copy()
    # move vertex 1 of the second triangle's own copy: make a separate vertex 4
    pts2 = np.vstack([pts2, P([2.0, -1.9])])
    pts2[4] = [np.nextafter(F(2.0), F(3)), F(-1.9)]
    v2 = verdict(pts2, (0, 1, 2), (0, 4, 3))
    check("A12_near_max_magnitude", v1 == eg.TOUCH and v2 == eg.POSITIVE, f"touch_case={v1} one_ulp_case={v2}")

    # A13 exact positive overlap far below Rev.1's stored area_tol
    s10, s20 = 2.0 ** -10, 2.0 ** -20
    pts = P([0, 0], [s10, 0], [0, s10], [s10 - s20, 0], [2 * s10, 0], [s10 - s20, s10])
    ipts, K = eg.exact_integer_points(pts)
    v = eg.classify_pair(ipts, (0, 1, 2), (3, 4, 5))
    _, area = eg.exact_intersection_polygon(ipts, (0, 1, 2), (3, 4, 5), K)
    a_area, _ = method_a_clip_area(pts[[0, 1, 2]], pts[[3, 4, 5]])
    check("A13_exact_positive_below_rev1_area_tol", v == eg.POSITIVE and 0 < float(area) < REV1_L3_AREA_TOL,
          f"{v} exact_area={float(area):.3e} (={area}) rev1_area_tol={REV1_L3_AREA_TOL:.3e} rev1_methodA_area={float(a_area):.3e}")

    # A14 Rev.1 real example (pass-3 mesh, triangles 13 and 188, share vertex index 7):
    # Rev.1 Method A in float32 arithmetic produced a large false polygon.
    pts = P([-0.8, -2.0], [-0.6, -1.8], [-0.8, -1.8], [-0.4, -1.6], [-0.6, -1.6])
    ti, tj = (0, 1, 2), (1, 3, 4)
    v = verdict(pts, ti, tj)
    a_area, a_poly = method_a_clip_area(pts[list(ti)], pts[list(tj)])
    sat = method_b_sat_overlap_length(pts[list(ti)], pts[list(tj)])
    check("A14_rev1_false_polygon_is_exact_touch", v == eg.TOUCH and float(a_area) > 1e-3,
          f"exact={v} rev1_methodA_area={float(a_area):.6e} rev1_sat={sat}")

    n_fail = sum(1 for _, ok in RESULTS if not ok)
    print(f"=== {len(RESULTS) - n_fail}/{len(RESULTS)} PASSED ===")
    return n_fail == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
