"""Batch 7G Rev.1 Phase A: full scan of all real L3 Delaunay-violation
candidate flips (not just the first 10) against the REAL, unmodified
`_would_overlap_any_other()`, classifying every block by whether it is a
shared-vertex/edge floating-point clipping artifact (area at or near the
float32 ULP scale of the mesh's own coordinates) or a genuinely large,
non-adjacent intersection area that needs independent verification in
Phase B/E.
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

from probe_delaunay_7g import build_raw_or_imported  # noqa: E402
from geometry_checks import local_delaunay_check, triangle_signed_area, _clip_polygon, _polygon_area  # noqa: E402
from candidate_a_edge_flip import _would_overlap_any_other  # noqa: E402

# float32 ULP at this mesh's own coordinate magnitude (~0.1-2.0 um), used
# ONLY as a reporting bucket boundary here (not as a new production
# tolerance -- Phase B derives its own tolerance independently).
FLOAT32_ULP_AT_1 = float(np.spacing(np.float32(1.0)))


def local_bbox(tri_pts):
    xs = [p[0] for p in tri_pts]
    ys = [p[1] for p in tri_pts]
    return min(xs), max(xs), min(ys), max(ys)


def classify_blocks(points, new_tri_a, new_tri_b, skip_indices, triangles):
    out = []
    for new_tri, tag in ((new_tri_a, "a"), (new_tri_b, "b")):
        nb = local_bbox(new_tri)
        new_tri_vertex_coords = {tuple(np.round(p, 12)) for p in new_tri}
        for ti, tri in enumerate(triangles):
            if ti in skip_indices:
                continue
            pts_j = [points[v][:2] for v in tri]
            tb = local_bbox(pts_j)
            if tb[1] < nb[0] or nb[1] < tb[0] or tb[3] < nb[2] or nb[3] < tb[2]:
                continue
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
                out.append({"shared": shared, "area": area})
    return out


def main():
    pts, tri, tags = build_raw_or_imported(3)  # matches manifest geo_imp_L3
    print(f"n_points={len(pts)} n_triangles={len(tri)}")
    interior, _ = local_delaunay_check(pts, tri, tags)
    violations = sorted([e for e in interior if e["angle_sum_violation"]], key=lambda v: v["edge"])
    print(f"n_delaunay_violations={len(violations)}")

    n_blocked, n_allowed = 0, 0
    artifact_only = 0     # every blocking reason has shared>=1 AND area < 1e-6 um^2 (a generous artifact ceiling)
    has_shared_large = 0  # a blocking reason has shared>=1 but area >= 1e-6 um^2 (needs independent check)
    has_disjoint = 0      # a blocking reason has shared==0 (genuinely no shared vertex/edge at all)
    max_artifact_area = 0.0
    large_cases = []

    for v in violations:
        a, b = v["edge"]
        opp1, opp2 = v["opp_vertices"]
        t1, t2 = v["owners"]
        new_a = [pts[a][:2], pts[opp1][:2], pts[opp2][:2]]
        new_b = [pts[b][:2], pts[opp1][:2], pts[opp2][:2]]
        real_blocked = _would_overlap_any_other(pts, new_a, new_b, {t1, t2}, tri)
        if not real_blocked:
            n_allowed += 1
            continue
        n_blocked += 1
        reasons = classify_blocks(pts, new_a, new_b, {t1, t2}, tri)
        any_disjoint = any(r["shared"] == 0 for r in reasons)
        any_shared_large = any(r["shared"] >= 1 and r["area"] >= 1e-6 for r in reasons)
        all_shared_small = all(r["shared"] >= 1 and r["area"] < 1e-6 for r in reasons) and len(reasons) > 0
        if any_disjoint:
            has_disjoint += 1
        if any_shared_large:
            has_shared_large += 1
            large_cases.append({"edge": v["edge"], "reasons": [r for r in reasons if r["shared"] >= 1 and r["area"] >= 1e-6]})
        if all_shared_small and not any_disjoint and not any_shared_large:
            artifact_only += 1
            max_artifact_area = max(max_artifact_area, max(r["area"] for r in reasons))

    print(f"\nreal function: n_blocked={n_blocked} n_allowed={n_allowed} (of {len(violations)} candidates)")
    print(f"  blocked-and-EVERY-reason-is-shared-vertex/edge-with-area<1e-6um2 (float32-noise-consistent artifact): {artifact_only}")
    print(f"  blocked-and-at-least-one-reason-has-shared>=1-but-area>=1e-6um2 (needs independent check): {has_shared_large}")
    print(f"  blocked-and-at-least-one-reason-is-fully-DISJOINT (shared==0, genuinely no topology link): {has_disjoint}")
    print(f"  max artifact-bucket area seen: {max_artifact_area:.6e} um^2 (float32 ULP at coordinate~1.0: {FLOAT32_ULP_AT_1:.3e})")
    print(f"\nlarge/disjoint cases needing independent Phase B/E verification ({len(large_cases)}):")
    for c in large_cases[:20]:
        print(f"  edge={c['edge']}: {c['reasons']}")


if __name__ == "__main__":
    main()
