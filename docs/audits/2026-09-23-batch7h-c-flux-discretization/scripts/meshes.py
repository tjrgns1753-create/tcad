"""Batch 7H-C mesh families on one rectangle, L x H = 2 x 1 um, left contact x=0,
right contact x=2 um, top/bottom insulating. All coordinates are dyadic
(multiples of 1/64 um) so exact integer geometry (7H-A exact_geometry) applies.

M1 non-obtuse control: alternately shifted rows, zipper + exact Lawson.
M2 right-triangle structured control: 0.25 um grid, one diagonal direction.
M3 Delaunay with obtuse triangles: M2 grid with deterministic dyadic interior
   perturbation, zipper + exact Lawson (Delaunay).
M4 non-Delaunay/obtuse: SAME point set as M3, zipper choosing the LONGER
   diagonal, no Lawson (only the diagonals differ from M3).
Controls for Experiment B: M4 mirrored (x -> 2-x), rotated 180 deg, scaled x2.
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
A7H = os.path.join(HERE, "..", "..", "2026-09-23-batch7h-exact-flip-certification", "scripts")
sys.path.insert(0, A7H)
import exact_geometry as eg  # noqa: E402  (7H-A, read-only)
import exact_flip as ef  # noqa: E402  (7H-A, read-only)

LX, LY = 2.0, 1.0
H = 0.25


def _zipper(lower, upper, rule):
    """lower/upper: lists of point indices sorted by x. Triangles CCW."""
    tris, i, j = [], 0, 0
    while i < len(lower) - 1 or j < len(upper) - 1:
        if i == len(lower) - 1:
            adv = "B"
        elif j == len(upper) - 1:
            adv = "A"
        else:
            dA = rule["d"](lower[i + 1], upper[j])   # new cross edge if A advances
            dB = rule["d"](lower[i], upper[j + 1])   # new cross edge if B advances
            adv = ("A" if dA <= dB else "B") if rule["short"] else ("A" if dA >= dB else "B")
        if adv == "A":
            tris.append([lower[i], lower[i + 1], upper[j]])
            i += 1
        else:
            tris.append([lower[i], upper[j + 1], upper[j]])
            j += 1
    return tris


def _build(rows_xy, short):
    pts, rows = [], []
    for row in rows_xy:
        idx = []
        for x, y in sorted(row):
            idx.append(len(pts))
            pts.append((x, y))
        rows.append(idx)
    P = np.array(pts, dtype=np.float64)
    d = lambda a, b: float(np.sum((P[a] - P[b]) ** 2))  # noqa: E731
    tris = []
    for k in range(len(rows) - 1):
        tris += _zipper(rows[k], rows[k + 1], {"d": d, "short": short})
    return P, tris


def _grid_rows(perturb=False):
    nx, ny = int(LX / H) + 1, int(LY / H) + 1
    offs = [-5 / 64, -3 / 64, -1 / 64, 1 / 64, 3 / 64, 5 / 64]
    rows = []
    for j in range(ny):
        row = []
        for i in range(nx):
            x, y = i * H, j * H
            if perturb and 0 < i < nx - 1 and 0 < j < ny - 1:
                x += offs[(3 * i + 5 * j) % 6]
                y += offs[(7 * i + 2 * j) % 6]
            row.append((x, y))
        rows.append(row)
    return rows


def _lawson(P, tris):
    tags = [0] * len(tris)
    _, bset, _, _ = eg.edge_sets(tris, tags)
    prot = frozenset(e for e, _ in bset)
    out, _, rep = ef.exact_flip(P, tris, tags, protected=prot)
    assert rep["terminated"] == "no_exact_violations_remaining", rep["terminated"]
    return out


def m1():
    rows = []
    for j in range(int(LY / H) + 1):
        if j % 2 == 0:
            rows.append([(i * H, j * H) for i in range(int(LX / H) + 1)])
        else:
            rows.append([(0.0, j * H)] + [(H / 2 + i * H, j * H) for i in range(int(LX / H))] + [(LX, j * H)])
    P, t = _build(rows, short=True)
    return P, _lawson(P, t)


def m2():
    return _build(_grid_rows(False), short=True)


def m3():
    P, t = _build(_grid_rows(True), short=True)
    return P, _lawson(P, t)


def m4():
    """First design (zipper choosing the longer diagonal) produced inverted and
    overlapping triangles and was discarded BEFORE any solve. Final design:
    start from M3 and, in one deterministic pass over sorted interior edges,
    flip every strictly-Delaunay edge (incircle < 0) whose quad is strictly
    convex into its non-Delaunay diagonal (each triangle flipped at most once
    per pass). A flip inside a strictly convex quad keeps the mesh valid."""
    P, tris = m3()
    tris = [list(t) for t in tris]
    ipts, _ = eg.exact_integer_points(P)
    owners = {}
    for ti, t in enumerate(tris):
        for a, b, c in ((t[0], t[1], t[2]), (t[1], t[2], t[0]), (t[2], t[0], t[1])):
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


def _ccw(P, tris):
    out = []
    for a, b, c in tris:
        s = (P[b, 0] - P[a, 0]) * (P[c, 1] - P[a, 1]) - (P[b, 1] - P[a, 1]) * (P[c, 0] - P[a, 0])
        out.append([a, b, c] if s > 0 else [a, c, b])
    return out


def variants(P, tris):
    mir = P.copy(); mir[:, 0] = LX - P[:, 0]
    rot = P.copy(); rot[:, 0] = LX - P[:, 0]; rot[:, 1] = LY - P[:, 1]
    return {"mirror": (mir, _ccw(mir, tris)), "rot180": (rot, _ccw(rot, tris)), "scale2": (P * 2.0, [list(t) for t in tris])}


FAMILIES = {"M1": m1, "M2": m2, "M3": m3, "M4": m4}


def quality(P, tris):
    ipts, K = eg.exact_integer_points(P)
    cls = {"acute": 0, "right": 0, "obtuse": 0}
    angles = []
    for t in tris:
        Q = [ipts[v] for v in t]
        dots = []
        for k in range(3):
            A, B, C = Q[k], Q[(k + 1) % 3], Q[(k + 2) % 3]
            dots.append((B[0] - A[0]) * (C[0] - A[0]) + (B[1] - A[1]) * (C[1] - A[1]))
            u, v = P[t[(k + 1) % 3]] - P[t[k]], P[t[(k + 2) % 3]] - P[t[k]]
            angles.append(np.degrees(np.arccos(np.clip(np.dot(u, v) / np.linalg.norm(u) / np.linalg.norm(v), -1, 1))))
        cls["obtuse" if min(dots) < 0 else ("right" if min(dots) == 0 else "acute")] += 1
    orient = [eg.orient(*[ipts[v] for v in t]) for t in tris]
    tags = [0] * len(tris)
    _, bset, _, _ = eg.edge_sets(tris, tags)
    prot = frozenset(e for e, _ in bset)
    viol = ef.exact_violations(ipts, [list(t) for t in tris], tags, prot)
    scan, _ = eg.global_exact_scan(ipts, [list(t) for t in tris], K)
    area2 = sum(abs(o) for o in orient)
    area_exact = eg.Fraction(area2, 2 * (1 << (2 * K)))
    left = sorted(int(i) for i in np.where(P[:, 0] == P[:, 0].min())[0])
    right = sorted(int(i) for i in np.where(P[:, 0] == P[:, 0].max())[0])
    return {"n_points": len(P), "n_triangles": len(tris), "classes": cls, "min_angle_deg": float(min(angles)),
            "max_angle_deg": float(max(angles)), "all_ccw": all(o > 0 for o in orient),
            "exact_delaunay_violations": len(viol), "exact_overlap_counts": scan["counts"],
            "area_exact_um2": str(area_exact), "left_contact_nodes": left, "right_contact_nodes": right,
            "n_boundary_edges": len(bset)}
