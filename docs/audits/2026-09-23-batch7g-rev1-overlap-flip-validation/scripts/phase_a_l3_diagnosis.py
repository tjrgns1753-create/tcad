"""Batch 7G Rev.1 Phase A (continued): the clean synthetic A1/A2/A9 fixtures
did NOT reproduce a false positive from the OLD `_would_overlap_any_other()`
(see phase_a_reproduce_p0_bug.py's real output -- 0/5 wrong). Per this
batch's own instruction ("기존 구현이 실패하지 않는다면 그 이유를 실제
intersection polygon과 수치로 증명하고, 추측하지 않는다"), this script
builds the REAL L3 imported mesh (byte-for-byte the same construction Batch
7G Phase 1 used: build_raw_or_imported(level=2), reused read-only), finds
the REAL local-Delaunay violations with the REAL local_delaunay_check(), and
calls the REAL, unmodified `_would_overlap_any_other()` for the first
several candidate flips -- while a LOCAL diagnostic re-walk (same bbox
prefilter + clip logic, written fresh in THIS file only, never imported into
or substituted for the real function) prints exactly which nearby triangle
triggered a block and the intersection polygon/area, then CROSS-CHECKS that
its own boolean matches the real function's real returned boolean for the
identical inputs, so the diagnosis is grounded in the real function's actual
behaviour, not a guess.
"""
import os
import sys
import warnings

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
warnings.simplefilter("ignore")

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
PHASE1_SCRIPTS = os.path.join(ROOT, "docs", "audits", "2026-09-23-batch7g-delaunay-refinement-spike", "scripts")
sys.path.insert(0, PHASE1_SCRIPTS)

from probe_delaunay_7g import build_raw_or_imported  # noqa: E402 -- Phase 1, unmodified, reused read-only
from geometry_checks import local_delaunay_check, triangle_signed_area, _clip_polygon, _polygon_area  # noqa: E402
from candidate_a_edge_flip import _would_overlap_any_other  # noqa: E402 -- Phase 1, unmodified


def local_bbox(tri_pts):
    xs = [p[0] for p in tri_pts]
    ys = [p[1] for p in tri_pts]
    return min(xs), max(xs), min(ys), max(ys)


def diagnostic_walk(points, new_tri_a, new_tri_b, skip_indices, triangles, verbose_limit=3):
    """Re-walks the SAME candidate set the real function iterates (bbox
    prefilter over ALL triangles, since the real function has no spatial
    index either), printing which triangle(s) produce nonzero clipped area
    and why (shared-vertex count with the new triangle, and the exact
    polygon/area). Returns (blocked_bool, details)."""
    details = []
    blocked = False
    printed = 0
    for new_tri, tag in ((new_tri_a, "new_tri_a"), (new_tri_b, "new_tri_b")):
        nb = local_bbox(new_tri)
        new_tri_vertex_coords = {tuple(np.round(p, 12)) for p in new_tri}
        for ti, tri in enumerate(triangles):
            if ti in skip_indices:
                continue
            pts_j = [points[v][:2] for v in tri]
            tb = local_bbox(pts_j)
            if tb[1] < nb[0] or nb[1] < tb[0] or tb[3] < nb[2] or nb[3] < tb[2]:
                continue
            # how many vertices does this OTHER triangle share (by coordinate,
            # since new_tri is passed as raw coordinate slices with no index
            # attached in the real function's own calling convention)?
            shared = sum(1 for p in pts_j if tuple(np.round(p, 12)) in new_tri_vertex_coords)
            p_i = list(new_tri)
            p_j = pts_j
            if triangle_signed_area(*p_i) < 0:
                p_i = p_i[::-1]
            if triangle_signed_area(*p_j) < 0:
                p_j = p_j[::-1]
            clipped = _clip_polygon(p_i, p_j)
            area = _polygon_area(clipped)
            if area > 1e-20:
                blocked = True
                details.append({"tag": tag, "other_tri_idx": ti, "shared_vertex_count_by_coord": shared,
                                "clipped_polygon": [list(p) for p in clipped], "area": area,
                                "new_tri": [list(p) for p in new_tri], "other_tri_pts": [list(p) for p in pts_j]})
                if printed < verbose_limit:
                    print(f"    [{tag}] blocked by triangle idx={ti} shared_vertex_count(by coord)={shared} "
                          f"clipped_area={area:.6e} um^2  polygon={[list(np.round(p,6)) for p in clipped]}")
                    print(f"      new_tri pts   = {[list(np.round(p,6)) for p in new_tri]}")
                    print(f"      other_tri pts = {[list(np.round(p,6)) for p in pts_j]}")
                    printed += 1
    return blocked, details


def main():
    print("Building real imported L3 mesh (refine_mesh_near, levels=3, same recipe as Batch 7G Phase 1)...")
    pts, tri, tags = build_raw_or_imported(3)  # level=3 -> refine_levels=4 -> L3 (matches manifest geo_imp_L3 exactly)
    print(f"n_points={len(pts)} n_triangles={len(tri)}")

    interior, _ = local_delaunay_check(pts, tri, tags)
    violations = [e for e in interior if e["angle_sum_violation"]]
    print(f"n_delaunay_violations={len(violations)}")
    violations_sorted = sorted(violations, key=lambda v: v["edge"])

    n_cases = min(10, len(violations_sorted))
    print(f"\nExamining the first {n_cases} candidate flips (sorted by edge key, matching Candidate A's own order):\n")

    disagreements = 0
    n_real_blocked = 0
    n_real_allowed = 0
    for i, v in enumerate(violations_sorted[:n_cases]):
        a, b = v["edge"]
        opp1, opp2 = v["opp_vertices"]
        t1, t2 = v["owners"]
        new_a = [pts[a][:2], pts[opp1][:2], pts[opp2][:2]]
        new_b = [pts[b][:2], pts[opp1][:2], pts[opp2][:2]]
        real_blocked = _would_overlap_any_other(pts, new_a, new_b, {t1, t2}, tri)
        print(f"--- candidate #{i} edge=({a},{b}) owners=({t1},{t2}) opp=({opp1},{opp2}) "
              f"REAL_FUNCTION_RESULT={'BLOCKED' if real_blocked else 'ALLOWED'} ---")
        diag_blocked, details = diagnostic_walk(pts, new_a, new_b, {t1, t2}, tri)
        agree = (diag_blocked == real_blocked)
        if not agree:
            disagreements += 1
            print(f"    !!! DIAGNOSTIC DISAGREES WITH REAL FUNCTION (diag={diag_blocked}, real={real_blocked})")
        if real_blocked:
            n_real_blocked += 1
        else:
            n_real_allowed += 1
        if not details and real_blocked:
            print("    (no candidate produced area>1e-20 in the diagnostic walk -- inconsistent, see disagreement above)")
        print()

    print(f"=== SUMMARY: {n_real_blocked}/{n_cases} real-BLOCKED, {n_real_allowed}/{n_cases} real-ALLOWED, "
          f"{disagreements} diagnostic/real disagreements ===")


if __name__ == "__main__":
    main()
