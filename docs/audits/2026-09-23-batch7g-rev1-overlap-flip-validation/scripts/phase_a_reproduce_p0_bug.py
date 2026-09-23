"""Batch 7G Rev.1 Phase A: reproduce the P0 defect in the EXISTING (Batch 7G
Phase 1) `_would_overlap_any_other()` -- imported UNMODIFIED from that file,
never copied/edited here -- using synthetic fixtures A1/A2/A9 (legal,
non-overlapping configurations that must NOT be blocked) at REAL mesh
coordinate scale (um, ~0.01-1 range, matching the real L3/L4/L5 meshes this
project's own DevSim import multiplies by length_scale_to_cm).

The bug (Codex's diagnosis, quoted in the bounded prompt):
    if set(int(v) for v in tri) & set(id(p) for p in new_tri):
        pass
`tri` yields real vertex-index ints; `new_tri` yields Python `id()` values of
freshly-sliced coordinate arrays (huge, effectively-random memory addresses).
The intersection is therefore ALWAYS empty, so the `if` is always False and
the `pass` never executes -- i.e. this "skip triangles that share a vertex
with the new triangle" check is dead code. Every nearby triangle, INCLUDING
ones that legitimately share a vertex/edge with the flip's new triangles, is
then run through the full Sutherland-Hodgman clip with `_clip_polygon`'s
absolute (coordinate-scale-blind) `-1e-15` inside-test slack and
`_polygon_area(...) > 1e-20` overlap threshold -- both fixed absolute
constants, never scaled to the mesh's own coordinate magnitude.
"""
import os
import sys

import numpy as np

PHASE1_SCRIPTS = os.path.join(
    os.path.dirname(__file__), "..", "..", "2026-09-23-batch7g-delaunay-refinement-spike", "scripts"
)
sys.path.insert(0, PHASE1_SCRIPTS)
from candidate_a_edge_flip import _would_overlap_any_other  # noqa: E402 -- unmodified Phase 1 file


def report(name, triangles_idx, points, new_tri_a, new_tri_b, skip_indices, expect_blocked, note=""):
    blocked = _would_overlap_any_other(points, new_tri_a, new_tri_b, skip_indices, triangles_idx)
    status = "BLOCKED" if blocked else "ALLOWED"
    wrong = (blocked and not expect_blocked) or (not blocked and expect_blocked)
    verdict = "FALSE POSITIVE (bug reproduced)" if (blocked and not expect_blocked) else (
        "FALSE NEGATIVE" if (not blocked and expect_blocked) else "correct"
    )
    print(f"[{name}] {status}  expect_blocked={expect_blocked}  verdict={verdict}  {note}")
    return {"name": name, "blocked": blocked, "expect_blocked": expect_blocked, "wrong": wrong, "verdict": verdict}


def main():
    results = []

    # ---- A1: a legal flip whose new triangle shares exactly ONE vertex
    # with an unrelated, nearby, non-overlapping fan triangle. Real
    # mesh-scale coordinates (~0.1 um edges), matching L3/L4/L5.
    # Layout: a small quad (0,1,2,3) that will be "flipped" into triangles
    # (0,2,4) and (1,2,4)-like shapes; plus one extra unrelated triangle
    # (2,5,6) sharing vertex 2 with the new triangles but occupying
    # completely disjoint area (a fan spoke), which is the real, common
    # real-mesh situation around every flip site.
    pts = np.array([
        [0.0, 0.0, 0.0],   # 0
        [0.1, 0.0, 0.0],   # 1
        [0.1, 0.1, 0.0],   # 2
        [0.0, 0.1, 0.0],   # 3
        [0.05, 0.15, 0.0],  # 4 (apex above the quad, used as "opp2" style point)
        [0.2, 0.05, 0.0],  # 5 (fan spoke unrelated point)
        [0.2, 0.15, 0.0],  # 6 (fan spoke unrelated point)
    ], dtype=float)
    triangles_idx = np.array([
        [0, 1, 2],  # t0 -- will be "replaced" (skip_indices)
        [0, 2, 3],  # t1 -- will be "replaced" (skip_indices)
        [2, 5, 6],  # t2 -- UNRELATED fan triangle sharing vertex 2 only, no real overlap
    ])
    # new_tri_a/new_tri_b as the OLD code expects: lists of coordinate slices
    new_tri_a = [pts[0][:2], pts[1][:2], pts[4][:2]]
    new_tri_b = [pts[0][:2], pts[4][:2], pts[3][:2]]
    results.append(report(
        "A1_shared_vertex_only_no_overlap", triangles_idx, pts, new_tri_a, new_tri_b,
        {0, 1}, expect_blocked=False,
        note="new triangles share vertex 0 with nothing external; t2 shares vertex 2 with new_tri_a only, "
             "geometrically disjoint (fan spoke) -- must be ALLOWED"))

    # ---- A2: new triangle shares a full EDGE with an unrelated, properly
    # adjacent neighbor (the normal case every real flip produces: the two
    # new triangles' outer edges are shared with the mesh's existing fan).
    pts2 = np.array([
        [0.0, 0.0, 0.0],   # 0
        [0.1, 0.0, 0.0],   # 1
        [0.1, 0.1, 0.0],   # 2
        [0.0, 0.1, 0.0],   # 3
        [0.05, -0.1, 0.0],  # 4 -- apex of a triangle below, sharing edge (0,1) with new_tri_a
    ], dtype=float)
    triangles_idx2 = np.array([
        [0, 1, 2],  # t0 -- replaced
        [0, 2, 3],  # t1 -- replaced
        [1, 0, 4],  # t2 -- UNRELATED, properly adjacent along edge (0,1), no overlap
    ])
    new_tri_a2 = [pts2[0][:2], pts2[1][:2], pts2[2][:2]]
    new_tri_b2 = [pts2[0][:2], pts2[2][:2], pts2[3][:2]]
    results.append(report(
        "A2_shared_edge_no_overlap", triangles_idx2, pts2, new_tri_a2, new_tri_b2,
        {0, 1}, expect_blocked=False,
        note="t2 shares the full edge (0,1) with new_tri_a, properly adjacent below it -- must be ALLOWED"))

    # ---- A9: convex quadrilateral legal flip, full realistic flip
    # scenario reproduced end to end: old diagonal (0,2), new diagonal
    # (1,3), t2 is the real local fan neighbor across edge (0,1).
    pts9 = np.array([
        [0.0, 0.0, 0.0],   # 0
        [0.12, -0.02, 0.0],  # 1
        [0.14, 0.11, 0.0],  # 2
        [0.01, 0.13, 0.0],  # 3
        [-0.1, -0.05, 0.0],  # 4 -- neighbor across edge (0,1)
    ], dtype=float)
    triangles_idx9 = np.array([
        [0, 1, 2],  # t0 replaced (old diagonal 0-2)
        [0, 2, 3],  # t1 replaced
        [1, 0, 4],  # t2 unrelated neighbor sharing edge (0,1)
    ])
    new_tri_a9 = [pts9[1][:2], pts9[2][:2], pts9[3][:2]]  # (1,2,3) after flip to diagonal 1-3
    new_tri_b9 = [pts9[3][:2], pts9[0][:2], pts9[1][:2]]  # (3,0,1)
    results.append(report(
        "A9_convex_quad_legal_flip", triangles_idx9, pts9, new_tri_a9, new_tri_b9,
        {0, 1}, expect_blocked=False,
        note="legal convex-quad flip; t2 is the real neighbor sharing edge (0,1) with new_tri_b -- must be ALLOWED"))

    # ---- A5 control: a REAL positive-area overlap must still be BLOCKED
    # (proves the bug is a false-POSITIVE issue, not that the function
    # never blocks anything).
    pts5 = np.array([
        [0.0, 0.0, 0.0],
        [0.1, 0.0, 0.0],
        [0.1, 0.1, 0.0],
        [0.0, 0.1, 0.0],
        [0.03, 0.03, 0.0],
        [0.08, 0.03, 0.0],
        [0.05, 0.08, 0.0],
    ], dtype=float)
    triangles_idx5 = np.array([
        [0, 1, 2],
        [0, 2, 3],
        [4, 5, 6],  # a genuinely UNRELATED (disjoint vertex set) triangle sitting INSIDE the quad -- real overlap
    ])
    new_tri_a5 = [pts5[0][:2], pts5[1][:2], pts5[2][:2]]
    new_tri_b5 = [pts5[0][:2], pts5[2][:2], pts5[3][:2]]
    results.append(report(
        "A5_real_overlap_control", triangles_idx5, pts5, new_tri_a5, new_tri_b5,
        {0, 1}, expect_blocked=True,
        note="triangle (4,5,6) genuinely sits inside the quad with positive-area overlap -- must be BLOCKED"))

    # ---- A8 control: pre-existing overlap FAR from the flip site must NOT
    # block a flip whose own new triangles don't touch it.
    pts8 = np.array([
        [0.0, 0.0, 0.0],
        [0.1, 0.0, 0.0],
        [0.1, 0.1, 0.0],
        [0.0, 0.1, 0.0],
        [10.0, 10.0, 0.0],
        [10.1, 10.0, 0.0],
        [10.05, 10.05, 0.0],
        [10.02, 10.02, 0.0],
        [10.08, 10.02, 0.0],
        [10.05, 10.08, 0.0],
    ], dtype=float)
    triangles_idx8 = np.array([
        [0, 1, 2],  # t0 replaced
        [0, 2, 3],  # t1 replaced
        [4, 5, 6],  # t2 -- overlap partner, FAR AWAY (around x=10)
        [7, 8, 9],  # t3 -- overlaps t2, FAR AWAY, irrelevant to this flip
    ])
    new_tri_a8 = [pts8[0][:2], pts8[1][:2], pts8[2][:2]]
    new_tri_b8 = [pts8[0][:2], pts8[2][:2], pts8[3][:2]]
    results.append(report(
        "A8_preexisting_overlap_elsewhere", triangles_idx8, pts8, new_tri_a8, new_tri_b8,
        {0, 1}, expect_blocked=False,
        note="t2/t3 overlap each other far away (~x=10) -- bbox-disjoint from the flip site -- must be ALLOWED "
             "(this one should already pass via the bbox prefilter, included as a control)"))

    print()
    n_wrong = sum(1 for r in results if r["wrong"])
    print(f"=== {n_wrong}/{len(results)} cases show a WRONG verdict from the OLD _would_overlap_any_other() ===")
    for r in results:
        if r["wrong"]:
            print(f"  BUG REPRODUCED: {r['name']} -> {r['verdict']}")
    return results


if __name__ == "__main__":
    main()
