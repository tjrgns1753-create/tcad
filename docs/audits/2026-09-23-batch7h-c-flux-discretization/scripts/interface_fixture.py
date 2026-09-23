"""Batch 7H-C addendum fixture (registered before any registered-fixture solve):
IF4 = two regions A (0<=x<=1 um) and B (1<=x<=2 um) sharing the unperturbed
x = 1 um column as the interface. Each half is the M4 construction on a
1 x 1 um half-domain (dyadic interior perturbation, then one anti-Lawson pass
making strictly-Delaunay edges non-Delaunay). B is A mirrored about x = 1."""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import meshes as ms  # noqa: E402

eg, ef = ms.eg, ms.ef


def half():
    nx, ny, h = 5, 5, 0.25
    offs = [-5 / 64, -3 / 64, -1 / 64, 1 / 64, 3 / 64, 5 / 64]
    rows = []
    for j in range(ny):
        row = []
        for i in range(nx):
            x, y = i * h, j * h
            if 0 < i < nx - 1 and 0 < j < ny - 1:
                x += offs[(3 * i + 5 * j) % 6]
                y += offs[(7 * i + 2 * j) % 6]
            row.append((x, y))
        rows.append(row)
    P, t = ms._build(rows, short=True)
    t = ms._lawson(P, t)
    # anti-Lawson pass identical to meshes.m4()
    ipts, _ = eg.exact_integer_points(P)
    tris = [list(x) for x in t]
    owners = {}
    for ti, tt in enumerate(tris):
        for a, b, c in ((tt[0], tt[1], tt[2]), (tt[1], tt[2], tt[0]), (tt[2], tt[0], tt[1])):
            owners.setdefault((min(a, b), max(a, b)), []).append((ti, c))
    touched = set()
    for (a, b), own in sorted(owners.items()):
        if len(own) != 2:
            continue
        (t1, c), (t2, d) = own
        if t1 in touched or t2 in touched:
            continue
        A, B, C, D = ipts[a], ipts[b], ipts[c], ipts[d]
        aa, bb = (a, b) if eg.orient(A, B, C) > 0 else (b, a)
        if eg.incircle(ipts[aa], ipts[bb], C, D) >= 0:
            continue
        if not (eg.orient(A, B, C) * eg.orient(A, B, D) < 0 and eg.orient(C, D, A) * eg.orient(C, D, B) < 0):
            continue
        tris[t1] = [a, c, d] if eg.orient(A, C, D) > 0 else [a, d, c]
        tris[t2] = [b, c, d] if eg.orient(B, C, D) > 0 else [b, d, c]
        touched |= {t1, t2}
    return P, tris


def if4():
    PA, TA = half()
    PB = PA.copy()
    PB[:, 0] = 2.0 - PA[:, 0]
    TB = ms._ccw(PB, TA)
    # merge: B's x=1 column nodes map onto A's x=1 column nodes
    pts = [tuple(p) for p in PA]
    index = {tuple(p): i for i, p in enumerate(pts)}
    mapB = []
    for p in PB:
        key = tuple(p)
        if key not in index:
            index[key] = len(pts)
            pts.append(key)
        mapB.append(index[key])
    P = np.array(pts)
    TB = [[mapB[v] for v in t] for t in TB]
    shared = sorted(i for i, p in enumerate(P) if p[0] == 1.0)
    return P, TA, TB, shared


if __name__ == "__main__":
    import hashlib
    import json
    P, TA, TB, shared = if4()
    qa = ms.quality(P, TA + TB)
    out = {"points_um": P.tolist(), "triangles_A": TA, "triangles_B": TB, "interface_nodes": shared,
           "quality_union": {k: v for k, v in qa.items()}}
    p = os.path.join(HERE, "..", "data", "fixture_IF4.json")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    print({k: v for k, v in qa.items() if "contact" not in k}, "interface nodes", len(shared))
    print("fixture_IF4.json sha256", hashlib.sha256(open(p, "rb").read()).hexdigest())
