"""Batch 7H-B analytical per-node area rules (F1-F5), element couples (G1/G2)
and public-model reconstructions (F6a-F6e). Pure Python/numpy, float64.
Fixed before any DEVSIM run; recorded in REPORT_DRAFT.md.

Conventions (triangle vertices i, j, k; theta_v = interior angle at v):
  cot(theta_a) = dot(b-a, c-a) / |cross(b-a, c-a)|  -- sign from the dot
  product only, so the value does not depend on the stored orientation.
  F2 per-(triangle,node) circumcentric area at i:
      A_i = (|ij|^2 cot(theta_k) + |ik|^2 cot(theta_j)) / 8
  sum_i A_i == triangle area exactly for every non-degenerate triangle.
"""
import numpy as np


def _cot(a, b, c):
    u, v = b - a, c - a
    return float(np.dot(u, v)) / abs(float(u[0] * v[1] - u[1] * v[0]))


def tri_area(p):
    a, b, c = p
    return abs(float((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))) / 2.0


def tri_parts(p):
    """Per-vertex pieces for one triangle p (3x2): cot at each vertex,
    squared length of the edge opposite each vertex, area."""
    cot = [_cot(p[0], p[1], p[2]), _cot(p[1], p[2], p[0]), _cot(p[2], p[0], p[1])]
    l2 = [float(np.sum((p[(v + 1) % 3] - p[(v + 2) % 3]) ** 2)) for v in range(3)]
    return cot, l2, tri_area(p)


def per_triangle_node(p, rule):
    """Returns the 3 per-vertex areas of triangle p under `rule`."""
    cot, l2, area = tri_parts(p)
    if rule == "F1":
        return [area / 3.0] * 3
    if rule == "F5":
        obtuse = [v for v in range(3) if cot[v] < 0]
        if obtuse:
            o = obtuse[0]
            return [area / 2.0 if v == o else area / 4.0 for v in range(3)]
        rule = "F2"
    out = []
    for i in range(3):
        j, k = (i + 1) % 3, (i + 2) % 3
        # |ij|^2 is the edge opposite k -> l2[k]; |ik|^2 is opposite j -> l2[j]
        ck, cj = cot[k], cot[j]
        if rule == "F3":
            ck, cj = abs(ck), abs(cj)
        a_i = (l2[k] * ck + l2[j] * cj) / 8.0
        if rule == "F4":
            a_i = abs(a_i)
        out.append(a_i)
    return out


RULES = ("F1", "F2", "F3", "F4", "F4b", "F5")


def node_areas(points, triangles, rule):
    """F4b = |sum over triangles of the signed F2 contribution| per node."""
    base = "F2" if rule == "F4b" else rule
    out = np.zeros(len(points))
    for t in triangles:
        vals = per_triangle_node(points[list(t)], base)
        for v, a in zip(t, vals):
            out[v] += a
    return np.abs(out) if rule == "F4b" else out


def element_couples(points, triangles):
    """Per (triangle, edge): signed half-length * cot(opposite angle), i.e.
    the signed distance from the edge midpoint to the circumcenter along the
    perpendicular bisector. Returns {edge_key: [(tri_index, signed_couple, length)]}."""
    out = {}
    for ti, t in enumerate(triangles):
        p = points[list(t)]
        cot, l2, _ = tri_parts(p)
        for opp in range(3):
            a, b = t[(opp + 1) % 3], t[(opp + 2) % 3]
            L = np.sqrt(l2[opp])
            out.setdefault((min(a, b), max(a, b)), []).append((ti, 0.5 * L * cot[opp], L))
    return out


def edge_couple_predictions(points, triangles):
    """G1 signed sum and G2 absolute sum of element couples per edge."""
    ec = element_couples(points, triangles)
    return ({e: sum(c for _, c, _ in v) for e, v in ec.items()},
            {e: sum(abs(c) for _, c, _ in v) for e, v in ec.items()},
            {e: v[0][2] for e, v in ec.items()})
