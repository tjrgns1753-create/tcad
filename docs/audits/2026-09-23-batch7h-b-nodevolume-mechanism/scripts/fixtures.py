"""Batch 7H-B fixtures, coordinates in um, fixed before any DEVSIM run.
The DEVSIM import converts with float64 `um * 1e-4` (cm). Every analytical
prediction is evaluated on the coordinates read BACK from DEVSIM's public
`x`/`y` node models (after asserting they equal the input), so no
representation mismatch enters the comparison."""
import math

import numpy as np

S3 = math.sqrt(3.0)
T4 = [(0.0, 0.0), (1.0, 0.0), (0.3, 0.35)]


def _tri(pts):
    return {"points": [list(p) for p in pts], "triangles": [[0, 1, 2]]}


def _scaled(pts, s):
    return [(x * s, y * s) for x, y in pts]


C100, S100 = math.cos(math.radians(100.0)), math.sin(math.radians(100.0))
C260, S260 = math.cos(math.radians(260.0)), math.sin(math.radians(260.0))

FIXTURES = {
    "T1_equilateral": _tri([(0.0, 0.0), (1.0, 0.0), (0.5, S3 / 2.0)]),
    "T2_scalene_acute": _tri([(0.0, 0.0), (1.2, 0.0), (0.4, 0.9)]),
    "T3_right_isosceles": _tri([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]),
    "T4_mild_obtuse": _tri(T4),
    "T5_strong_obtuse": _tri([(0.0, 0.0), (1.0, 0.0), (0.4, 0.1)]),
    "T6_T4_mirror": _tri([(-x, y) for x, y in T4]),
    "T7_T4_rot90": _tri([(-y, x) for x, y in T4]),
    "T8_T4_x0.1": _tri(_scaled(T4, 0.1)),
    "T9_T4_x10": _tri(_scaled(T4, 10.0)),
    "P1_square_diagA": {"points": [[0, 0], [1, 0], [1, 1], [0, 1]], "triangles": [[0, 1, 2], [0, 2, 3]]},
    "P2_square_diagB": {"points": [[0, 0], [1, 0], [1, 1], [0, 1]], "triangles": [[0, 1, 3], [1, 2, 3]]},
    "P3_kite_nonDelaunay": {"points": [[-1, 0], [0, -3], [1, 0], [0, 1]], "triangles": [[0, 1, 3], [1, 2, 3]]},
    "P4_kite_Delaunay": {"points": [[-1, 0], [0, -3], [1, 0], [0, 1]], "triangles": [[0, 1, 2], [0, 2, 3]]},
    # obtuse (156.5 deg at vertex 2) triangle whose long edge (0,1) is the shared
    # INTERIOR edge; opposite angles 156.5 + 22.6 < 180, so the edge is Delaunay
    "P5_interior_obtuse_Delaunay": {"points": [[0, 0], [1, 0], [0.4, 0.1], [0.5, -2.5]],
                                    "triangles": [[0, 1, 2], [1, 0, 3]]},
    # closed fan, interior node 0; spokes at 0/100/180/260 deg: two triangles are
    # obtuse (100 deg) at the centre; every spoke is Delaunay (40+50 deg)
    "P6_fan_obtuse_centre": {"points": [[0, 0], [1, 0], [C100, S100], [-1, 0], [C260, S260]],
                             "triangles": [[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 1]]},
    # same outer boundary, interior node moved to (cos100, 0): all four triangles right-angled at it
    "P7_fan_right_control": {"points": [[C100, 0], [1, 0], [C100, S100], [-1, 0], [C260, S260]],
                             "triangles": [[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 1]]},
}


def as_arrays(name):
    f = FIXTURES[name]
    return np.array(f["points"], dtype=np.float64), [list(t) for t in f["triangles"]]
