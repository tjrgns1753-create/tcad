"""Batch 7H-D mesh families on x in [-0.5, 0.5] um, y in [0, 0.1] um,
dx = dy = 0.02 um. Every mesh keeps the same boundary polygon, the same
contact nodes (x = -0.5 / +0.5 columns) and an unperturbed x = 0 column (so
the junction line is conforming in every mesh). Uses the 7H-C row-zipper
builder and 7H-A exact Lawson flip (read-only imports).

M1 non-obtuse irregular: alternately shifted rows (odd rows at x = 0.01 + 0.02k),
   with x = 0 and the two boundary nodes inserted in odd rows; zipper + Lawson.
M2 right-triangle structured: same x-lines as the 1D dx = 0.02 reference.
M3 Delaunay with obtuse triangles: M2 points, interior rows j = 2, 3 and
   columns i = 2..48 (i != 25) perturbed by dyadic fractions of dx; zipper + Lawson.
M4 non-Delaunay: SAME points as M3; one deterministic anti-Lawson pass.
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
AUD = os.path.join(HERE, "..", "..")
sys.path.insert(0, os.path.join(AUD, "2026-09-23-batch7h-c-flux-discretization", "scripts"))
sys.path.insert(0, os.path.join(AUD, "2026-09-23-batch7h-exact-flip-certification", "scripts"))
import meshes as m7c  # noqa: E402  (7H-C, read-only: _build, _lawson)
import exact_geometry as eg  # noqa: E402

DX = 0.02
NX = 51          # columns i = 0..50, x = (i - 25) * DX
NY = 6           # rows j = 0..5, y = j * DX


def xcol(i):
    return (i - 25) * DX


def m2_rows():
    return [[(xcol(i), j * DX) for i in range(NX)] for j in range(NY)]


def m1():
    rows = []
    for j in range(NY):
        if j % 2 == 0:
            rows.append([(xcol(i), j * DX) for i in range(NX)])
        else:
            xs = [xcol(0), 0.0, xcol(NX - 1)] + [(k - 25) * DX + DX / 2 for k in range(NX - 1)]
            rows.append([(x, j * DX) for x in sorted(set(xs))])
    P, t = m7c._build(rows, short=True)
    return P, m7c._lawson(P, t)


def m2():
    return m7c._build(m2_rows(), short=True)


def _perturbed_rows():
    offs = [-0.3125, -0.1875, -0.0625, 0.0625, 0.1875, 0.3125]
    rows = []
    for j in range(NY):
        row = []
        for i in range(NX):
            x, y = xcol(i), j * DX
            if j in (2, 3) and 2 <= i <= NX - 3 and i != 25:
                x += offs[(3 * i + 5 * j) % 6] * DX
                y += offs[(7 * i + 2 * j) % 6] * DX
            row.append((x, y))
        rows.append(row)
    return rows


def m3():
    P, t = m7c._build(_perturbed_rows(), short=True)
    return P, m7c._lawson(P, t)


def m4():
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


FAMILIES = {"M1": m1, "M2": m2, "M3": m3, "M4": m4}
