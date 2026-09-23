"""Batch 7G Phase 1, Candidate A: constrained local Delaunay edge flipping.

Only ever touches an INTERIOR, UNCONSTRAINED, SAME-MATERIAL edge shared by
exactly 2 triangles. NEVER flips: external boundary edges, contact boundary
edges (both are the multiplicity-1 "boundary" constrained kind), material
interface edges (multiplicity-2, different tags), or any edge whose flip
would produce a zero/negative-area triangle or a NEW positive-area overlap
with any OTHER triangle in the mesh (checked directly, not assumed safe).

Deterministic order (sorted edge keys each pass), finite termination
verified by an explicit iteration cap AND a strictly-decreasing total
violation-severity potential check (if the potential does not strictly
decrease after a full pass, the run stops and reports non-termination
rather than looping forever).
"""
import numpy as np

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from geometry_checks import (
    build_topology, local_delaunay_check, triangle_signed_area, _clip_polygon, _polygon_area,
)


def _would_overlap_any_other(points, new_tri_a, new_tri_b, skip_indices, triangles):
    """Cheap, LOCAL overlap safety check: does either newly-created triangle
    positive-area-overlap any triangle NOT among the two being replaced?
    Restricted to triangles whose bounding box is near the flip (a full
    global O(N) scan per flip would be too slow across many flips; the
    physically relevant risk is only ever local to the flip site)."""
    def bbox(tri_pts):
        xs = [p[0] for p in tri_pts]
        ys = [p[1] for p in tri_pts]
        return min(xs), max(xs), min(ys), max(ys)

    for new_tri in (new_tri_a, new_tri_b):
        nb = bbox(new_tri)
        for ti, tri in enumerate(triangles):
            if ti in skip_indices:
                continue
            pts = [points[v][:2] for v in tri]
            tb = bbox(pts)
            if tb[1] < nb[0] or nb[1] < tb[0] or tb[3] < nb[2] or nb[3] < tb[2]:
                continue  # bbox disjoint -- cannot overlap
            if set(int(v) for v in tri) & set(id(p) for p in new_tri):
                pass
            p_i = list(new_tri)
            p_j = pts
            if triangle_signed_area(*p_i) < 0:
                p_i = p_i[::-1]
            if triangle_signed_area(*p_j) < 0:
                p_j = p_j[::-1]
            clipped = _clip_polygon(p_i, p_j)
            if _polygon_area(clipped) > 1e-20:
                return True
    return False


def flip_to_local_delaunay(points, triangles, tags, max_passes=50):
    """Returns (new_points [unchanged -- flipping never adds/removes
    vertices], new_triangles, new_tags, report). report includes per-pass
    flip counts, termination reason, and final violation count."""
    triangles = triangles.copy()
    tags = tags.copy()
    passes = []
    prev_violation_total_severity = None

    for pass_i in range(max_passes):
        interior, _ = local_delaunay_check(points, triangles, tags)
        violations = [e for e in interior if e["angle_sum_violation"]]
        total_severity = sum(v["severity_rad"] for v in violations)
        if not violations:
            passes.append({"pass": pass_i, "n_violations_before": 0, "n_flips": 0, "total_severity_before": 0.0})
            return points, triangles, tags, {"passes": passes, "terminated": "no_violations_remaining", "final_violations": 0}

        if prev_violation_total_severity is not None and total_severity >= prev_violation_total_severity:
            passes.append({"pass": pass_i, "n_violations_before": len(violations), "n_flips": 0,
                          "total_severity_before": total_severity, "note": "severity did not strictly decrease -- stopping"})
            return points, triangles, tags, {"passes": passes, "terminated": "severity_not_decreasing",
                                             "final_violations": len(violations)}
        prev_violation_total_severity = total_severity

        violations_sorted = sorted(violations, key=lambda v: v["edge"])
        flipped_this_pass = 0
        touched_triangles = set()
        for v in violations_sorted:
            t1, t2 = v["owners"]
            if t1 in touched_triangles or t2 in touched_triangles:
                continue  # a triangle already flipped this pass -- re-evaluate next pass
            a, b = v["edge"]
            opp1, opp2 = v["opp_vertices"]
            # new triangles: (a, opp1, opp2) and (b, opp1, opp2)
            new_a = [points[a][:2], points[opp1][:2], points[opp2][:2]]
            new_b = [points[b][:2], points[opp1][:2], points[opp2][:2]]
            area_a = abs(triangle_signed_area(*new_a))
            area_b = abs(triangle_signed_area(*new_b))
            if area_a < 1e-20 or area_b < 1e-20:
                continue  # would create a zero/near-zero area triangle -- refuse
            if _would_overlap_any_other(points, new_a, new_b, {t1, t2}, triangles):
                continue  # would create a new overlap -- refuse
            tag = tags[t1]
            triangles[t1] = [a, opp1, opp2]
            triangles[t2] = [b, opp1, opp2]
            tags[t1] = tag
            tags[t2] = tag
            touched_triangles.add(t1)
            touched_triangles.add(t2)
            flipped_this_pass += 1
        passes.append({"pass": pass_i, "n_violations_before": len(violations), "n_flips": flipped_this_pass,
                       "total_severity_before": total_severity})
        if flipped_this_pass == 0:
            return points, triangles, tags, {"passes": passes, "terminated": "no_safe_flips_available",
                                             "final_violations": len(violations)}

    interior, _ = local_delaunay_check(points, triangles, tags)
    remaining = sum(1 for e in interior if e["angle_sum_violation"])
    return points, triangles, tags, {"passes": passes, "terminated": "max_passes_reached", "final_violations": remaining}
