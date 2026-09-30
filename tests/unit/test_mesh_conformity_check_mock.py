#!/usr/bin/env python3
"""False-green tests of the exact conformity checker (Batch 7H-E6H, criteria A in
docs/audits/2026-10-01-batch7h-e6h-conformity-poisson/CRITERIA.md) and its agreement with the E6G brute-force hanging-node count."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "docs/audits/2026-10-01-batch7h-e6h-conformity-poisson/scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from conformity_e6h import check_conformity  # noqa: E402
from tcad.device.devsim.mesh_refine import structured_lateral_refine  # noqa: E402
from test_mesh_structured_remesh_mock import exact, grid  # noqa: E402

BAD_KEYS = {"duplicate_coordinates", "duplicate_triangles", "unused_nodes", "degenerate", "edges_with_more_than_two_owners",
            "interior_edges_same_direction", "boundary_edges_off_rectangle", "hanging_nodes"}


def fails(rep, *keys):
    assert not rep["pass"], rep
    for k in keys:
        assert rep[k] if k not in ("one_orientation", "boundary_covers_rectangle_exactly", "area_equals_rectangle") else not rep[k], (k, rep)


def main():
    P, T, _ = grid([0.0, 1.0, 2.0, 3.0], [0.0, 1.0, 2.0, 3.0])
    assert check_conformity(P, T)["pass"]

    # builder outputs on the small E6G cases agree with the brute-force exact() count (0 hanging) and pass
    cases = [(grid([0.0, 1.0, 2.0], [0.0, 1.0]), [0.5], [0.5]),
             (grid([float(i) for i in range(11)], [float(j) for j in range(11)]), [5.0], [1.0, 0.5, 0.25]),
             (grid([0.5 * i for i in range(17)], [0.5 * j for j in range(5)]), [1.6, 6.3], [0.5, 0.25, 0.125])]
    for (P, T, G), c, r in cases:
        P1, T1, _, _ = structured_lateral_refine(P, T, G, c, r)
        rep, ref = check_conformity(P1, T1), exact(P1, T1, P, T)
        assert rep["pass"] and rep["hanging_nodes"] == ref["hanging"] == 0, (rep, ref)

    # deliberate T-junction: a coarse cell edge against two fine cells, node (1, .5) inside the coarse edge
    pts = np.array([(0, 0), (1, 0), (1, 1), (0, 1), (1, .5), (2, 0), (2, .5), (2, 1)], dtype=float)
    right = [(1, 5, 6), (1, 6, 4), (4, 6, 7), (4, 7, 2)]
    good = np.array([(0, 1, 4), (0, 4, 2), (0, 2, 3)] + right)
    assert check_conformity(pts, good)["pass"]
    tj = np.array([(0, 1, 2), (0, 2, 3)] + right)
    rep = check_conformity(pts, tj)
    fails(rep, "hanging_nodes")
    assert rep["hanging_nodes"] == 1 and exact(pts, tj, pts, tj)["hanging"] == 1, rep

    # interior missing triangle: unmatched edges appear inside the rectangle
    P, T, _ = grid([0.0, 1.0, 2.0, 3.0], [0.0, 1.0, 2.0, 3.0])
    rep = check_conformity(P, np.delete(T, 8, axis=0))
    fails(rep, "boundary_edges_off_rectangle")
    assert not rep["boundary_covers_rectangle_exactly"] and not rep["area_equals_rectangle"], rep

    # duplicate triangle (and three owners of one edge)
    rep = check_conformity(P, np.vstack([T, T[:1]]))
    fails(rep, "duplicate_triangles", "edges_with_more_than_two_owners")

    # one flipped triangle: mixed orientation and an interior edge traversed twice in the same direction
    Tf = T.copy()
    Tf[5] = Tf[5][::-1]
    rep = check_conformity(P, Tf)
    fails(rep, "interior_edges_same_direction")
    assert not rep["one_orientation"], rep

    # coincident nodes: an interior node duplicated and half of its triangles moved to the copy (a slit)
    interior = 5                       # node (1, 1) of the 4 x 4 grid
    P2 = np.vstack([P, P[interior]])
    T2 = T.copy()
    move = [i for i, t in enumerate(T2.tolist()) if interior in t][:2]
    for i in move:
        T2[i] = [len(P) if v == interior else v for v in T2[i]]
    rep = check_conformity(P2, T2)
    fails(rep, "duplicate_coordinates")

    # an unused node and a degenerate triangle
    fails(check_conformity(np.vstack([P, [[5.0, 5.0, 0.0]]]), T), "unused_nodes")
    Td = np.vstack([T, [[0, 1, 1]]])
    fails(check_conformity(P, Td), "degenerate")
    print("CONFORMITY CHECKER FALSE-GREEN TESTS PASSED")


if __name__ == "__main__":
    main()
