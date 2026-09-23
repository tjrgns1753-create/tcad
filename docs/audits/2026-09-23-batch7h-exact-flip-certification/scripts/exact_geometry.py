"""Batch 7H-A: exact-arithmetic triangle geometry (standard library only).

Every stored coordinate is a float32 value. float32 is exactly representable
in float64, and `float(v).as_integer_ratio()` returns its exact value as
num / 2**k. All coordinates of one mesh are rescaled by one common power of
two, 2**K, so each coordinate becomes an exact Python integer. orient2d,
incircle, areas and triangle-pair classification are then exact integer
arithmetic: no tolerance, no sqrt, no normalized axis anywhere. Exact
intersection polygons (only for positive-overlap pairs) use
fractions.Fraction.

Pair classification (no tolerance, exhaustive, mutually exclusive):
  INVALID                      -- either triangle has zero signed area
  DUPLICATE                    -- same three vertex indices
  EXACT_POSITIVE_AREA_OVERLAP  -- the open interiors intersect
  EXACT_BOUNDARY_TOUCH_ONLY    -- closed triangles intersect, interiors do not
  EXACT_DISJOINT               -- closed triangles do not intersect

Separation argument (why testing edge lines is exhaustive): for convex
polygons P, Q the Minkowski difference P-Q is a convex polygon whose outward
edge normals are the outward normals of P's edges and the negated outward
normals of Q's edges. Interiors are disjoint iff the origin is not in the
interior of P-Q iff some edge line of P-Q has the origin on its closed outer
side, which is exactly "all vertices of Q lie on the closed outer side of an
edge line of P" (or the same with P and Q swapped). Closed sets are disjoint
iff the same holds with the STRICT outer side.
"""
from fractions import Fraction

POSITIVE = "EXACT_POSITIVE_AREA_OVERLAP"
TOUCH = "EXACT_BOUNDARY_TOUCH_ONLY"
DISJOINT = "EXACT_DISJOINT"
INVALID = "INVALID"
DUPLICATE = "DUPLICATE"


def exact_integer_points(points_xy):
    """points_xy: iterable of (x, y) float32/float64 values. Returns
    (int_points, K) with int_points[i] = (X, Y), X = x * 2**K exactly."""
    ratios = []
    kmax = 0
    for x, y in points_xy:
        rx = float(x).as_integer_ratio()
        ry = float(y).as_integer_ratio()
        for _, den in (rx, ry):
            k = den.bit_length() - 1
            assert den == 1 << k, "denominator must be a power of two"
            kmax = max(kmax, k)
        ratios.append((rx, ry))
    out = []
    for (nx, dx), (ny, dy) in ratios:
        out.append((nx * ((1 << kmax) // dx), ny * ((1 << kmax) // dy)))
    # round-trip proof: every integer divided by 2**K equals the stored value
    for (X, Y), (x, y) in zip(out, points_xy):
        assert Fraction(X, 1 << kmax) == Fraction(float(x)) and Fraction(Y, 1 << kmax) == Fraction(float(y))
    return out, kmax


def orient(a, b, c):
    """Twice the signed area of (a, b, c); exact integer. >0 means CCW."""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def incircle(a, b, c, d):
    """>0 iff d is strictly inside the circumcircle of CCW triangle (a,b,c)."""
    adx, ady = a[0] - d[0], a[1] - d[1]
    bdx, bdy = b[0] - d[0], b[1] - d[1]
    cdx, cdy = c[0] - d[0], c[1] - d[1]
    return ((adx * adx + ady * ady) * (bdx * cdy - cdx * bdy)
            - (bdx * bdx + bdy * bdy) * (adx * cdy - cdx * ady)
            + (cdx * cdx + cdy * cdy) * (adx * bdy - bdx * ady))


def ccw(tri_pts):
    a, b, c = tri_pts
    return (a, b, c) if orient(a, b, c) > 0 else (a, c, b)


def _separated(P, Q, strict):
    """True if some edge line of CCW triangle P has every vertex of Q on its
    outer side (closed, or strict if `strict`)."""
    for i in range(3):
        a, b = P[i], P[(i + 1) % 3]
        if strict:
            if all(orient(a, b, q) < 0 for q in Q):
                return True
        else:
            if all(orient(a, b, q) <= 0 for q in Q):
                return True
    return False


def classify_pair(ipts, tri_i, tri_j):
    """ipts: exact integer points; tri_i/tri_j: vertex-index triples."""
    if set(int(v) for v in tri_i) == set(int(v) for v in tri_j):
        return DUPLICATE
    Pi = [ipts[int(v)] for v in tri_i]
    Pj = [ipts[int(v)] for v in tri_j]
    if orient(*Pi) == 0 or orient(*Pj) == 0:
        return INVALID
    P, Q = ccw(Pi), ccw(Pj)
    if _separated(P, Q, strict=True) or _separated(Q, P, strict=True):
        return DISJOINT
    if _separated(P, Q, strict=False) or _separated(Q, P, strict=False):
        return TOUCH
    return POSITIVE


def exact_intersection_polygon(ipts, tri_i, tri_j, K):
    """Exact convex intersection polygon (Fractions, in original units) by
    Sutherland-Hodgman with exact rational intersection points."""
    P = ccw([ipts[int(v)] for v in tri_i])
    Q = ccw([ipts[int(v)] for v in tri_j])
    poly = [(Fraction(x), Fraction(y)) for x, y in P]
    for i in range(3):
        a, b = Q[i], Q[(i + 1) % 3]

        def side(p):
            return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])

        out = []
        n = len(poly)
        for k in range(n):
            s, e = poly[k - 1], poly[k]
            ss, se = side(s), side(e)
            if se >= 0:
                if ss < 0:
                    t = ss / (ss - se)
                    out.append((s[0] + t * (e[0] - s[0]), s[1] + t * (e[1] - s[1])))
                out.append(e)
            elif ss >= 0:
                t = ss / (ss - se)
                out.append((s[0] + t * (e[0] - s[0]), s[1] + t * (e[1] - s[1])))
        poly = out
        if not poly:
            break
    scale = Fraction(1, 1 << K)
    poly = [(x * scale, y * scale) for x, y in poly]
    area2 = sum(poly[k - 1][0] * poly[k][1] - poly[k][0] * poly[k - 1][1] for k in range(len(poly))) if len(poly) >= 3 else Fraction(0)
    return poly, abs(area2) / 2


def tri_bbox(ipts, tri):
    xs = [ipts[int(v)][0] for v in tri]
    ys = [ipts[int(v)][1] for v in tri]
    return min(xs), max(xs), min(ys), max(ys)


def candidate_pairs(ipts, triangles, cell):
    """All (i<j) pairs whose CLOSED integer bboxes intersect. Uniform grid is
    only a candidate reducer; the final bbox test is exact and closed."""
    boxes = [tri_bbox(ipts, t) for t in triangles]
    buckets = {}
    for ti, (x0, x1, y0, y1) in enumerate(boxes):
        for gx in range(x0 // cell, x1 // cell + 1):
            for gy in range(y0 // cell, y1 // cell + 1):
                buckets.setdefault((gx, gy), []).append(ti)
    pairs = set()
    for members in buckets.values():
        m = len(members)
        for a in range(m):
            ia = members[a]
            ba = boxes[ia]
            for b in range(a + 1, m):
                ib = members[b]
                bb = boxes[ib]
                if ba[1] < bb[0] or bb[1] < ba[0] or ba[3] < bb[2] or bb[3] < ba[2]:
                    continue
                pairs.add((ia, ib) if ia < ib else (ib, ia))
    return sorted(pairs), boxes


def default_cell(ipts, triangles):
    spans = []
    for t in triangles[: min(len(triangles), 4000)]:
        x0, x1, y0, y1 = tri_bbox(ipts, t)
        spans.append(max(x1 - x0, y1 - y0))
    spans.sort()
    return max(spans[len(spans) // 2] * 2, 1)


def global_exact_scan(ipts, triangles, K, keep_all=False):
    """Classify every closed-bbox-intersecting pair. Returns summary + lists."""
    cell = default_cell(ipts, triangles)
    pairs, _ = candidate_pairs(ipts, triangles, cell)
    counts = {POSITIVE: 0, TOUCH: 0, DISJOINT: 0, INVALID: 0, DUPLICATE: 0}
    positives = []
    verdicts = {} if keep_all else None
    for i, j in pairs:
        v = classify_pair(ipts, triangles[i], triangles[j])
        counts[v] += 1
        if keep_all:
            verdicts[(i, j)] = v
        if v == POSITIVE:
            poly, area = exact_intersection_polygon(ipts, triangles[i], triangles[j], K)
            positives.append({"pair": (i, j), "tri_i": [int(x) for x in triangles[i]],
                              "tri_j": [int(x) for x in triangles[j]], "area_exact": str(area),
                              "area_float": float(area), "polygon": [(float(x), float(y)) for x, y in poly]})
    total_area = sum(Fraction(p["area_exact"]) for p in positives)
    return {"n_candidate_pairs": len(pairs), "counts": counts, "positives": positives,
            "total_positive_area_exact": str(total_area), "total_positive_area_um2": float(total_area),
            "cell": cell}, verdicts


def edge_sets(triangles, tags):
    owners = {}
    for ti, t in enumerate(triangles):
        v0, v1, v2 = (int(x) for x in t)
        for a, b in ((v0, v1), (v1, v2), (v2, v0)):
            owners.setdefault((a, b) if a < b else (b, a), []).append(ti)
    boundary = frozenset((e, int(tags[o[0]])) for e, o in owners.items() if len(o) == 1)
    interface = frozenset((e, tuple(sorted((int(tags[o[0]]), int(tags[o[1]])))))
                          for e, o in owners.items() if len(o) == 2 and int(tags[o[0]]) != int(tags[o[1]]))
    non_manifold = frozenset(e for e, o in owners.items() if len(o) > 2)
    return owners, boundary, interface, non_manifold


def mesh_exact_invariants(ipts, triangles, tags):
    from collections import Counter
    _, boundary, interface, non_manifold = edge_sets(triangles, tags)
    keys = Counter(tuple(sorted(int(v) for v in t)) for t in triangles)
    dup = frozenset(k for k, c in keys.items() if c > 1)
    zero = frozenset(ti for ti, t in enumerate(triangles) if orient(*[ipts[int(v)] for v in t]) == 0)
    inverted = frozenset(ti for ti, t in enumerate(triangles) if orient(*[ipts[int(v)] for v in t]) < 0)
    area2 = sum(abs(orient(*[ipts[int(v)] for v in t])) for t in triangles)
    return {"n_triangles": len(triangles), "tag_counter": Counter(int(t) for t in tags),
            "boundary_edge_set": boundary, "interface_edge_set": interface,
            "non_manifold_edge_set": non_manifold, "duplicate_triangle_set": dup,
            "zero_area_set": zero, "inverted_set": inverted, "total_area2_int": area2}
