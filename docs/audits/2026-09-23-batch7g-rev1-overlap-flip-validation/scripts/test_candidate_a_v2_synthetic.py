"""Batch 7G Rev.1 Phase C validation: corrected Candidate A on synthetic
fixtures, before it is ever applied to the real L3 mesh (Phase E gate)."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from candidate_a_edge_flip_v2 import flip_to_local_delaunay_v2

RESULTS = []


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition)))
    print(f"[{name}] {'PASS' if condition else 'FAIL'}  {detail}")


def main():
    # Non-Delaunay kite (same numeric fixture Phase 1 used, reproduced
    # independently here): diagonal 1-3 is non-Delaunay (233.13 deg),
    # diagonal 0-2 is Delaunay (126.87 deg) -- flip must reduce violations to 0.
    pts = np.array([[-1.0, 0.0], [0.0, -3.0], [1.0, 0.0], [0.0, 1.0]])
    tri = np.array([[0, 1, 3], [1, 2, 3]])  # split along diagonal 1-3 (non-Delaunay)
    tags = np.array([0, 0])
    new_pts, new_tri, new_tags, report = flip_to_local_delaunay_v2(pts, tri, tags)
    check("kite_flips_to_zero_violations", report["final_violations"] == 0,
          f"terminated={report['terminated']} final_violations={report['final_violations']} passes={report['passes']}")

    # Boundary/contact edges must never be touched (mirrors Phase 1's own
    # mutation 8, re-verified against the CORRECTED implementation).
    pts_b = np.array([[0, 0], [2, 0], [2, 1], [0, 1]], dtype=float)
    tri_b = np.array([[0, 1, 2], [0, 2, 3]])
    tags_b = np.array([0, 0])
    _, new_tri_b, _, _ = flip_to_local_delaunay_v2(pts_b, tri_b, tags_b)

    def edges_of(tris):
        es = set()
        for t in tris:
            v0, v1, v2 = int(t[0]), int(t[1]), int(t[2])
            for a, b in ((v0, v1), (v1, v2), (v2, v0)):
                es.add((a, b) if a < b else (b, a))
        return es
    boundary_expected = {(0, 1), (1, 2), (2, 3), (0, 3)}
    survived = boundary_expected <= edges_of(new_tri_b)
    check("boundary_edges_never_flipped", survived, f"survived={survived}")

    # Material tags preserved (2-material mesh, mirrors Phase 1's mutation 9).
    pts2 = np.array([[0, 0], [1, 0], [1, 1], [0, 1], [2, 0], [2, 1]], dtype=float)
    tri2 = np.array([[0, 1, 2], [0, 2, 3], [1, 4, 5], [1, 5, 2]])
    tags2 = np.array([0, 0, 1, 1])
    _, new_tri2, new_tags2, _ = flip_to_local_delaunay_v2(pts2, tri2, tags2)
    check("material_tags_preserved", sorted(tags2.tolist()) == sorted(new_tags2.tolist()),
          f"before={sorted(tags2.tolist())} after={sorted(new_tags2.tolist())}")

    # Non-convex quad must never be flipped even if it were (hypothetically)
    # flagged non-Delaunay -- constructed so the flip candidate quad is concave.
    pts_c = np.array([[0.0, 0.0], [0.1, 0.0], [0.03, 0.03], [0.0, 0.1]], dtype=float)
    tri_c = np.array([[0, 1, 2], [0, 2, 3]])
    tags_c = np.array([0, 0])
    _, new_tri_c, _, report_c = flip_to_local_delaunay_v2(pts_c, tri_c, tags_c)
    unchanged = np.array_equal(np.sort(tri_c, axis=1), np.sort(np.array(new_tri_c), axis=1))
    check("nonconvex_quad_not_flipped", unchanged, f"unchanged={unchanged} report={report_c['passes']}")

    print()
    n_fail = sum(1 for _, ok in RESULTS if not ok)
    print(f"=== {len(RESULTS) - n_fail}/{len(RESULTS)} PASSED ===")
    return n_fail == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
