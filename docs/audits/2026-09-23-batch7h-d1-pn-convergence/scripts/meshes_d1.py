"""Batch 7H-D1 mesh families. Domain x in [-0.5, 0.5] um, y in [0, 0.1] um.

J1 junction support: NO node on x = 0; the node columns nearest the junction are
x = -h/2 and +h/2 and the strip between them is right triangles with matched
rows, so every circumcenter there lies on x = 0 and the discrete dual boundary is
exactly x = 0 (checked exactly in build_fixtures_d1.py). Interior columns at
+-(2k+1) h/2, contact columns at +-0.5 (last interval h/2, as in the 1D grid).

The RIGHT half (x >= h/2) is built with the 7H-C row-zipper and the 7H-A exact
Lawson flip (read-only imports), then mirrored; the strip joins the halves.
  M2(h): structured right triangles (same x columns as the 1D J1 grid).
  M1(h): odd rows shifted by h/2 for x >= 2h (non-obtuse irregular), structured
         band |x| <= 3h/2.
  M3(h): M2 points; interior rows, columns k = 2..n-2 perturbed by the 7H-D
         normalized offsets (x h) with 7H-D's index patterns; mirror-symmetric.
J0 grids (1D only): nodes at k h including x = 0 (diagnostic only).
"""
import os
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
AUD = os.path.join(HERE, "..", "..")
sys.path.insert(0, os.path.join(AUD, "2026-09-23-batch7h-c-flux-discretization", "scripts"))
import meshes as m7c  # noqa: E402  (7H-C, read-only: _build, _lawson)

OFF = [-0.3125, -0.1875, -0.0625, 0.0625, 0.1875, 0.3125]   # 7H-D M3 offsets (x h)
X_HALF, HEIGHT = 0.5, 0.1


def n_half(h):
    return int(round(X_HALF / h))


def cols_right(h):
    n = n_half(h)
    return [(2 * k + 1) * X_HALF / (2 * n) for k in range(n)]


def grid_1d(h, kind):
    """kind 'J1': +-(2k+1)h/2 and +-0.5; 'J0': k h (includes x = 0)."""
    n = n_half(h)
    if kind == "J1":
        c = cols_right(h)
        return sorted([-X_HALF, X_HALF] + c + [-v for v in c])
    return [(k - n) * X_HALF / n for k in range(2 * n + 1)]


def _rows_right(fam, h):
    n, ny = n_half(h), int(round(HEIGHT / h))
    pos = cols_right(h)
    rows = []
    for j in range(ny + 1):
        y = j * HEIGHT / ny
        if fam == "M1" and j % 2 == 1:
            xs = [pos[0], pos[1]] + [m * X_HALF / n for m in range(2, n)] + [X_HALF]
            rows.append([(x, y) for x in xs])
            continue
        row = []
        for k, x in enumerate(pos):
            if fam == "M3" and 0 < j < ny and 2 <= k <= n - 2:
                row.append((x + OFF[(3 * k + 5 * j) % 6] * h, y + OFF[(7 * k + 2 * j) % 6] * h))
            else:
                row.append((x, y))
        row.append((X_HALF, y))
        rows.append(row)
    return rows


def build(fam, h):
    rows = _rows_right(fam, h)
    PR, tR = m7c._build(rows, short=True)
    tR = m7c._lawson(PR, [list(t) for t in tR])
    nR = len(PR)
    starts = np.cumsum([0] + [len(r) for r in rows[:-1]])      # index of each row's x = h/2 node
    PL = PR * np.array([-1.0, 1.0])
    P = np.vstack([PR, PL])
    tris = [[int(a), int(b), int(c)] for a, b, c in tR]
    tris += [[int(a) + nR, int(c) + nR, int(b) + nR] for a, b, c in tR]
    for j in range(len(rows) - 1):
        r0, r1 = int(starts[j]), int(starts[j + 1])
        assert PR[r0, 0] == PR[r1, 0] == cols_right(h)[0]
        tris += [[r0 + nR, r0, r1], [r0 + nR, r1, r1 + nR]]
    return P, tris


FAMILIES = ("M1", "M2", "M3")
H_2D = (0.02, 0.01, 0.005, 0.0025)
H_1D = (0.02, 0.01, 0.005, 0.0025, 0.00125)
