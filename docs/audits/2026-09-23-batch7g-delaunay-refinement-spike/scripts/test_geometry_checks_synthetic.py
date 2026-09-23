"""Batch 7G Phase 1 section 5: validate geometry_checks.py against 7 synthetic
fixtures with KNOWN defects, BEFORE running it on any real mesh. Each fixture
asserts the checker catches EXACTLY the expected defect and NOTHING else
(a checker that over-fires on clean fixtures is as useless as one that misses
real defects). Tolerances are never adjusted after seeing these results --
they are already fixed in geometry_checks.py's own module docstring.
"""
import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from geometry_checks import (
    local_delaunay_check, triangle_geometry_table, hanging_node_check,
    triangle_overlap_check, boundary_loops_and_hole_check,
)

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition)))
    print(f"[{name}] {'PASS' if condition else 'FAIL'} {detail}")


# ============================================================ Fixture 1: normal Delaunay 2-triangle mesh
def fixture_1():
    # kite quadrilateral P1=(-1,0) P2=(0,-3) P3=(1,0) P4=(0,1), split via the
    # DELAUNAY-preferred diagonal P1-P3 (verified: alpha+beta=126.87deg < 180).
    pts = np.array([[-1, 0, 0], [0, -3, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
    tri = np.array([[0, 1, 2], [0, 2, 3]])
    tags = np.array([0, 0])
    interior, constrained = local_delaunay_check(pts, tri, tags)
    hang = hanging_node_check(pts, tri, tags)
    overlaps, _ = triangle_overlap_check(pts, tri, tags)
    hole = boundary_loops_and_hole_check(pts, tri)
    check("F1_no_delaunay_violation", len(interior) == 1 and not interior[0]["angle_sum_violation"] and not interior[0]["incircle_violation"])
    check("F1_no_hanging_node", len(hang) == 0)
    check("F1_no_overlap", len(overlaps) == 0)
    check("F1_no_hole", abs(hole["uncovered_hole_area"]) < 1e-9)
    check("F1_one_constrained_boundary_only", all(c["kind"] == "boundary" for c in constrained))


# ============================================================ Fixture 2: locally non-Delaunay diagonal
def fixture_2():
    # SAME kite, opposite (non-Delaunay-preferred) diagonal P2-P4 (verified:
    # alpha+beta=233.13deg > 180 -- both angle-sum AND incircle agree).
    pts = np.array([[-1, 0, 0], [0, -3, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
    tri = np.array([[0, 1, 3], [1, 2, 3]])
    tags = np.array([0, 0])
    interior, _ = local_delaunay_check(pts, tri, tags)
    hang = hanging_node_check(pts, tri, tags)
    overlaps, _ = triangle_overlap_check(pts, tri, tags)
    check("F2_delaunay_violation_detected", len(interior) == 1 and interior[0]["angle_sum_violation"] and interior[0]["incircle_violation"])
    check("F2_severity_matches_angle_sum", abs(interior[0]["severity_rad"] - np.radians(233.13010235415598 - 180.0)) < 1e-6)
    check("F2_no_hanging_node", len(hang) == 0)
    check("F2_no_overlap", len(overlaps) == 0)


# ============================================================ Fixture 3: obtuse triangle
def fixture_3():
    # (0,0),(4,0),(3.9,0.3): clearly obtuse at the vertex near (4,0).
    pts = np.array([[0, 0, 0], [4, 0, 0], [3.9, 0.3, 0]], dtype=float)
    tri = np.array([[0, 1, 2]])
    geo = triangle_geometry_table(pts, tri)
    check("F3_classified_obtuse", geo[0]["classification"] == "obtuse", f"angles={geo[0]['angles_deg']}")
    check("F3_circumcenter_outside", geo[0]["circumcenter_inside"] is False)
    # sanity: an ACUTE triangle must NOT be misclassified as obtuse
    pts_acute = np.array([[0, 0, 0], [2, 0, 0], [1, 1.5, 0]], dtype=float)
    geo_acute = triangle_geometry_table(pts_acute, np.array([[0, 1, 2]]))
    check("F3_acute_control_not_obtuse", geo_acute[0]["classification"] != "obtuse", f"angles={geo_acute[0]['angles_deg']}")
    check("F3_acute_control_circumcenter_inside", geo_acute[0]["circumcenter_inside"] is True)


# ============================================================ Fixture 4: T-junction / hanging node
def fixture_4():
    # left unit square (0,0)-(1,1): ONE undivided edge at x=1, y in [0,1].
    # right unit square (1,0)-(2,1): edge at x=1 SPLIT into (1,0)-(1,0.5) and
    # (1,0.5)-(1,1) by inserting node 6=(1,0.5) and building 4 small triangles
    # on the right instead of 2 -- the node (1,0.5) is NOT a vertex of the
    # left side's triangles at all: classic hanging node.
    pts = np.array([
        [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],   # 0,1,2,3: left square corners
        [2, 0, 0], [2, 1, 0],                          # 4,5: right square outer corners
        [1, 0.5, 0],                                    # 6: the hanging midpoint on x=1
    ], dtype=float)
    left = [[0, 1, 2], [0, 2, 3]]  # undivided edge (1,2) == x=1, y in[0,1]
    right = [[1, 4, 6], [4, 5, 6], [6, 5, 2], [1, 6, 2]]  # x=1 split via node 6
    tri = np.array(left + right)
    tags = np.array([0] * len(tri))
    hang = hanging_node_check(pts, tri, tags)
    found = [h for h in hang if h["node"] == 6]
    check("F4_hanging_node_detected", len(found) >= 1, f"hang={hang}")
    if found:
        check("F4_unsplit_edge_is_1_2", found[0]["unsplit_edge"] == (1, 2), f"got {found[0]['unsplit_edge']}")
        check("F4_split_present_on_other_side", found[0]["split_present_on_other_side"] is True)
    # sanity control: a FULLY conforming version (no node 6, right side also
    # just 2 triangles) must report ZERO hanging nodes.
    pts_ok = pts[:6]
    right_ok = [[1, 4, 5], [1, 5, 2]]
    tri_ok = np.array(left + right_ok)
    tags_ok = np.array([0] * len(tri_ok))
    hang_ok = hanging_node_check(pts_ok, tri_ok, tags_ok)
    check("F4_conforming_control_zero_hanging", len(hang_ok) == 0, f"got {hang_ok}")


# ============================================================ Fixture 5: overlapping triangles
def fixture_5():
    # Two DISJOINT vertex sets (no shared indices at all) whose triangles
    # spatially overlap with real positive area.
    pts = np.array([
        [0, 0, 0], [2, 0, 0], [0, 2, 0],       # 0,1,2: triangle A
        [0.5, 0.5, 0], [2.5, 0.5, 0], [0.5, 2.5, 0],  # 3,4,5: triangle B, overlapping A
    ], dtype=float)
    tri = np.array([[0, 1, 2], [3, 4, 5]])
    tags = np.array([0, 0])
    overlaps, n_checked = triangle_overlap_check(pts, tri, tags)
    check("F5_overlap_detected", len(overlaps) == 1, f"overlaps={overlaps}")
    check("F5_overlap_area_positive", len(overlaps) == 1 and overlaps[0]["overlap_area"] > 0.1)
    # sanity control: two triangles that only share an EDGE must NOT be flagged
    pts_adj = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=float)
    tri_adj = np.array([[0, 1, 2], [0, 2, 3]])
    overlaps_adj, _ = triangle_overlap_check(pts_adj, tri_adj, np.array([0, 0]))
    check("F5_shared_edge_not_overlap", len(overlaps_adj) == 0, f"got {overlaps_adj}")


# ============================================================ Fixture 6: interior hole
def fixture_6():
    # 4x4 grid of points (a 3x3 array of cells); triangulate every cell
    # EXCEPT the CENTER cell (surrounded on all 4 sides by triangulated
    # cells), leaving a real interior, separately-bounded hole. (A CORNER
    # cell's removal, tried first, only reshapes the OUTER boundary into an
    # L -- no separate inner loop at all; the checker correctly reported
    # zero hole for that case, which is why the center cell is used here.)
    xs, ys = [0, 1, 2, 3], [0, 1, 2, 3]
    idx = {}
    pts = []
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            idx[(i, j)] = len(pts)
            pts.append([x, y, 0])
    pts = np.array(pts, dtype=float)
    tri = []
    for j in range(3):
        for i in range(3):
            if (i, j) == (1, 1):  # the CENTER cell -- leave untriangulated -> interior hole
                continue
            a, b, c, d = idx[(i, j)], idx[(i + 1, j)], idx[(i + 1, j + 1)], idx[(i, j + 1)]
            tri.append([a, b, c])
            tri.append([a, c, d])
    tri = np.array(tri)
    tags = np.array([0] * len(tri))
    hole = boundary_loops_and_hole_check(pts, tri)
    check("F6_two_boundary_loops", hole["n_boundary_loops"] == 2, f"hole={hole}")
    check("F6_hole_detected", abs(hole["uncovered_hole_area"] - 1.0) < 1e-9, f"hole={hole}")
    # sanity control: fully triangulated 3x3 grid -> zero hole area, 1 loop
    tri_full = list(tri) + [[idx[(1, 1)], idx[(2, 1)], idx[(2, 2)]], [idx[(1, 1)], idx[(2, 2)], idx[(1, 2)]]]
    tri_full = np.array(tri_full)
    hole_full = boundary_loops_and_hole_check(pts, tri_full)
    check("F6_full_control_zero_hole", abs(hole_full["uncovered_hole_area"]) < 1e-9, f"got {hole_full['uncovered_hole_area']}")
    check("F6_full_control_one_loop", hole_full["n_boundary_loops"] == 1, f"got {hole_full['n_boundary_loops']}")


# ============================================================ Fixture 7: material interface (2-material, constrained edge)
def fixture_7():
    pts = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [2, 0, 0], [2, 1, 0]], dtype=float)
    tri = np.array([[0, 1, 2], [0, 2, 3], [1, 4, 5], [1, 5, 2]])
    tags = np.array([0, 0, 1, 1])  # left pair material 0, right pair material 1
    interior, constrained = local_delaunay_check(pts, tri, tags)
    iface = [c for c in constrained if c["kind"] == "material_interface"]
    check("F7_interface_edge_classified_constrained", len(iface) == 1 and iface[0]["edge"] == (1, 2), f"iface={iface}")
    check("F7_interface_not_in_interior_flip_candidates", all(e["edge"] != (1, 2) for e in interior))
    check("F7_interior_edges_within_each_material_only", len(interior) == 2)  # the 2 within-material diagonals


def main():
    fixture_1()
    fixture_2()
    fixture_3()
    fixture_4()
    fixture_5()
    fixture_6()
    fixture_7()
    print()
    failed = [n for n, ok in results if not ok]
    if failed:
        print(f"FAILED: {failed}")
        sys.exit(1)
    print(f"ALL {len(results)} SYNTHETIC FIXTURE ASSERTIONS PASSED")


if __name__ == "__main__":
    main()
