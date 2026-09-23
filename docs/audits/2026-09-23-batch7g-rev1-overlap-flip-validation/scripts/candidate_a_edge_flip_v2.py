"""Batch 7G Rev.1 Phase C: corrected constrained local Delaunay edge-flip
repair. A NEW file -- does not modify or import Phase 1's own
candidate_a_edge_flip.py, which stays byte-identical.

Every flip must satisfy ALL of (per the bounded prompt's own Phase C list):
  1. target edge owned by exactly 2 triangles                (from local_delaunay_check's own interior list)
  2. both triangles share the same material tag               (same)
  3. not a boundary/contact/material-interface edge            (same -- these are never in the interior list)
  4. the 4 vertices (a, opp1, b, opp2) form a convex quadrilateral
  5. opp1/opp2 lie on opposite sides of the OLD diagonal (a,b)  (guaranteed by the quad being a proper glued pair;
                                                                   re-verified directly, not assumed)
  6. the NEW diagonal (opp1,opp2) lies inside the quadrilateral (implied by convexity, re-checked directly)
  7. old-pair union area == new-pair union area within a derived tolerance
  8. both new triangles have nonzero area, stored with consistent CCW orientation
  9. positive-area overlap against EXTERNAL triangles does not INCREASE
     (before/after LOCAL overlap set/area comparison, using the corrected
     two-method checker -- never a blanket "any pre-existing overlap nearby
     blocks the flip", which was Phase 1's own bug)
  10. material tag, point coordinates, and every external boundary/contact/
      interface edge are preserved (flipping never touches point positions,
      only replaces 2 triangle records)

No "global severity must strictly decrease" rule is used as a correctness
gate (Phase 1 used this without a proven monotonicity argument, per the
bounded prompt's own instruction not to reuse it as a correctness
condition). Termination is instead by an explicit deterministic queue
(sorted edge keys, re-evaluated each pass) plus a fixed iteration cap,
and the run reports its own termination state honestly (converged / cap
reached / no legal flips left), never silently claiming success.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from geometry_checks_v2 import (
    triangle_signed_area, corrected_triangle_overlap_check, derive_overlap_area_tolerance,
    build_topology,
)

PHASE1_SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "..",
                              "2026-09-23-batch7g-delaunay-refinement-spike", "scripts")
sys.path.insert(0, PHASE1_SCRIPTS)
from geometry_checks import local_delaunay_check  # noqa: E402 -- Phase 1, unmodified, reused read-only


def _quad_convex_and_diagonals_ok(pa, p_opp1, pb, p_opp2):
    """Quad in perimeter order a -> opp1 -> b -> opp2 -> a. Returns
    (is_convex, opp1_opp2_opposite_sides_of_ab, new_diag_inside)."""
    poly = [pa, p_opp1, pb, p_opp2]
    signs = []
    for i in range(4):
        a, b, c = poly[i], poly[(i + 1) % 4], poly[(i + 2) % 4]
        cr = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        signs.append(cr)
    is_convex = all(s > 0 for s in signs) or all(s < 0 for s in signs)

    ab = pb - pa
    def side(p):
        v = p - pa
        return ab[0] * v[1] - ab[1] * v[0]
    opposite_sides = (side(p_opp1) * side(p_opp2)) < 0

    # new diagonal (opp1,opp2) inside the quad iff the quad is convex AND
    # a/b are on opposite sides of the opp1-opp2 line too (symmetric check)
    o1o2 = p_opp2 - p_opp1
    def side2(p):
        v = p - p_opp1
        return o1o2[0] * v[1] - o1o2[1] * v[0]
    ab_opposite_sides_of_new_diag = (side2(pa) * side2(pb)) < 0
    new_diag_inside = is_convex and opposite_sides and ab_opposite_sides_of_new_diag
    return is_convex, opposite_sides, new_diag_inside


def _local_overlap_area_against_externals(points, triangles, tags, own_indices, exclude_indices, area_tol_bbox_pts):
    """Sum of confirmed-overlap area between the triangles at `own_indices`
    (their CURRENT geometry in `triangles`) and every OTHER triangle except
    `exclude_indices` (which always includes own_indices plus, for a
    'before' snapshot, nothing extra; for an 'after' snapshot, the same).
    Restricted to a local candidate set via bbox for cost, matching this
    project's own established locality argument (Batch 7G Phase 1's own
    `_would_overlap_any_other` docstring)."""
    def bbox_of(ti):
        pts = points[triangles[ti]][:, :2]
        return pts[:, 0].min(), pts[:, 0].max(), pts[:, 1].min(), pts[:, 1].max()

    total_area = 0.0
    pairs = []
    own_bboxes = {ti: bbox_of(ti) for ti in own_indices}
    for tj in range(len(triangles)):
        if tj in exclude_indices:
            continue
        pts_j = points[triangles[tj]][:, :2]
        tb = (pts_j[:, 0].min(), pts_j[:, 0].max(), pts_j[:, 1].min(), pts_j[:, 1].max())
        for ti in own_indices:
            nb = own_bboxes[ti]
            if tb[1] < nb[0] or nb[1] < tb[0] or tb[3] < nb[2] or nb[3] < tb[2]:
                continue
            si = set(int(v) for v in triangles[ti])
            sj = set(int(v) for v in triangles[tj])
            shared = si & sj
            p_i = points[triangles[ti]][:, :2]
            p_j = pts_j
            from geometry_checks_v2 import method_a_clip_area, method_b_sat_overlap_length, shared_edge_is_proper_adjacency
            length_tol, area_tol, _ = area_tol_bbox_pts
            if len(shared) == 2:
                is_proper, _, _ = shared_edge_is_proper_adjacency(points, triangles[ti], triangles[tj], shared, length_tol)
                if is_proper is True:
                    continue
            if len(shared) == 3:
                continue
            area_a, _ = method_a_clip_area(p_i, p_j)
            min_ov_b = method_b_sat_overlap_length(p_i, p_j)
            if area_a > area_tol and min_ov_b > length_tol:
                total_area += area_a
                pairs.append((ti, tj, float(area_a)))
    return total_area, pairs


def flip_to_local_delaunay_v2(points, triangles, tags, max_passes=50):
    triangles = triangles.copy()
    tags = tags.copy()
    length_tol, area_tol, tol_detail = derive_overlap_area_tolerance(points, triangles)
    area_tol_bundle = (length_tol, area_tol, tol_detail)
    passes = []

    for pass_i in range(max_passes):
        interior, _ = local_delaunay_check(points, triangles, tags)
        violations = [e for e in interior if e["angle_sum_violation"]]
        if not violations:
            passes.append({"pass": pass_i, "n_violations_before": 0, "n_flips": 0})
            return points, triangles, tags, {"passes": passes, "terminated": "no_violations_remaining",
                                              "final_violations": 0, "tolerance": tol_detail}

        violations_sorted = sorted(violations, key=lambda v: v["edge"])
        flipped_this_pass = 0
        rejects = {"not_convex": 0, "opposite_sides_fail": 0, "new_diag_not_inside": 0,
                   "area_not_preserved": 0, "zero_area_new_tri": 0, "overlap_would_increase": 0,
                   "triangle_already_touched": 0}
        touched_triangles = set()

        for v in violations_sorted:
            t1, t2 = v["owners"]
            if t1 in touched_triangles or t2 in touched_triangles:
                rejects["triangle_already_touched"] += 1
                continue
            a, b = v["edge"]
            opp1, opp2 = v["opp_vertices"]
            pa = points[a][:2]
            pb_ = points[b][:2]
            p_opp1 = points[opp1][:2]
            p_opp2 = points[opp2][:2]

            is_convex, opposite_sides, new_diag_inside = _quad_convex_and_diagonals_ok(pa, p_opp1, pb_, p_opp2)
            if not is_convex:
                rejects["not_convex"] += 1
                continue
            if not opposite_sides:
                rejects["opposite_sides_fail"] += 1
                continue
            if not new_diag_inside:
                rejects["new_diag_not_inside"] += 1
                continue

            old_area = abs(triangle_signed_area(pa, p_opp1, pb_)) + abs(triangle_signed_area(pa, pb_, p_opp2))
            new_tri_1 = (a, opp1, opp2)
            new_tri_2 = (b, opp1, opp2)
            new_area = abs(triangle_signed_area(pa, p_opp1, p_opp2)) + abs(triangle_signed_area(pb_, p_opp1, p_opp2))
            if abs(old_area - new_area) > max(area_tol, 1e-15 * max(old_area, new_area)):
                rejects["area_not_preserved"] += 1
                continue
            if abs(new_area) < 1e-300:
                rejects["zero_area_new_tri"] += 1
                continue
            a1 = triangle_signed_area(pa, p_opp1, p_opp2)
            a2 = triangle_signed_area(pb_, p_opp1, p_opp2)
            new_tri_1_ordered = (a, opp1, opp2) if a1 > 0 else (a, opp2, opp1)
            new_tri_2_ordered = (b, opp1, opp2) if a2 > 0 else (b, opp2, opp1)

            before_area, before_pairs = _local_overlap_area_against_externals(
                points, triangles, tags, {t1, t2}, {t1, t2}, area_tol_bundle)

            trial_triangles = triangles.copy()
            trial_triangles[t1] = list(new_tri_1_ordered)
            trial_triangles[t2] = list(new_tri_2_ordered)
            after_area, after_pairs = _local_overlap_area_against_externals(
                points, trial_triangles, tags, {t1, t2}, {t1, t2}, area_tol_bundle)

            if after_area > before_area + area_tol:
                rejects["overlap_would_increase"] += 1
                continue

            tag = tags[t1]
            triangles[t1] = list(new_tri_1_ordered)
            triangles[t2] = list(new_tri_2_ordered)
            tags[t1] = tag
            tags[t2] = tag
            touched_triangles.add(t1)
            touched_triangles.add(t2)
            flipped_this_pass += 1

        passes.append({"pass": pass_i, "n_violations_before": len(violations),
                       "n_flips": flipped_this_pass, "rejects": rejects})
        if flipped_this_pass == 0:
            return points, triangles, tags, {"passes": passes, "terminated": "no_legal_flips_available",
                                              "final_violations": len(violations), "tolerance": tol_detail}

    interior, _ = local_delaunay_check(points, triangles, tags)
    remaining = sum(1 for e in interior if e["angle_sum_violation"])
    return points, triangles, tags, {"passes": passes, "terminated": "max_passes_reached",
                                      "final_violations": remaining, "tolerance": tol_detail}
