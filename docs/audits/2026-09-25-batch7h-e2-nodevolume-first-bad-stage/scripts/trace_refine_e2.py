"""Batch 7H-E2 audit copy of the production red-green pass (pure numpy, no DEVSIM / ViennaPS).

`refine_once_traced` is the logic of `tcad/device/devsim/mesh_refine.py::_refine_once` copied verbatim, plus two recorded
arrays per output triangle: the index of its parent triangle in the pass input, and its split kind. Its output arrays are
proven equal to production `refine_mesh_near(levels=k)` at run time (PLAN I1); production code is never modified.
Kinds: 0 unchanged, 1 red corner child, 2 red centre child, 3 green child."""
from fractions import Fraction
from typing import Dict, List, Tuple

import numpy as np

KIND_NAMES = {0: "unchanged", 1: "red_corner", 2: "red_centre", 3: "green"}


def _edge_key(a, b):
    return (a, b) if a < b else (b, a)


def refine_once_traced(points, triangles, tags, marked):
    n_tri = len(triangles)
    edge_owners: Dict[Tuple[int, int], List[int]] = {}
    for ti in range(n_tri):
        v0, v1, v2 = (int(x) for x in triangles[ti])
        for a, b in ((v0, v1), (v1, v2), (v2, v0)):
            edge_owners.setdefault(_edge_key(a, b), []).append(ti)
    red = marked.copy()
    changed = True
    while changed:
        changed = False
        for ti in range(n_tri):
            if red[ti]:
                continue
            v0, v1, v2 = (int(x) for x in triangles[ti])
            broken = 0
            for a, b in ((v0, v1), (v1, v2), (v2, v0)):
                owners = edge_owners[_edge_key(a, b)]
                if any(red[o] for o in owners if o != ti):
                    broken += 1
            if broken >= 2:
                red[ti] = True
                changed = True
    new_points = list(points)
    midpoint_cache: Dict[Tuple[int, int], int] = {}

    def midpoint(a, b):
        key = _edge_key(a, b)
        if key not in midpoint_cache:
            new_points.append((points[a] + points[b]) / 2.0)
            midpoint_cache[key] = len(new_points) - 1
        return midpoint_cache[key]

    new_triangles, new_tags, parent, kind = [], [], [], []
    for ti in range(n_tri):
        v0, v1, v2 = (int(x) for x in triangles[ti])
        tag = int(tags[ti])
        if red[ti]:
            m01, m12, m20 = midpoint(v0, v1), midpoint(v1, v2), midpoint(v2, v0)
            new_triangles += [(v0, m01, m20), (v1, m12, m01), (v2, m20, m12), (m01, m12, m20)]
            new_tags += [tag] * 4
            parent += [ti] * 4
            kind += [1, 1, 1, 2]
            continue
        broken_edges = []
        for apex, ea, eb in ((v2, v0, v1), (v0, v1, v2), (v1, v2, v0)):
            owners = edge_owners[_edge_key(ea, eb)]
            if any(red[o] for o in owners if o != ti):
                broken_edges.append((apex, ea, eb))
        if not broken_edges:
            new_triangles.append((v0, v1, v2))
            new_tags.append(tag)
            parent.append(ti)
            kind.append(0)
        elif len(broken_edges) == 1:
            apex, ea, eb = broken_edges[0]
            m = midpoint(ea, eb)
            new_triangles += [(apex, ea, m), (apex, m, eb)]
            new_tags += [tag, tag]
            parent += [ti, ti]
            kind += [3, 3]
        else:
            raise AssertionError("red-green closure invariant violated")
    return (np.array(new_points, dtype=points.dtype), np.array(new_triangles, dtype=triangles.dtype),
            np.array(new_tags, dtype=tags.dtype), np.array(parent, dtype=np.int64), np.array(kind, dtype=np.int8))


def refine_traced(points, triangles, tags, predicate, levels):
    """Same loop as production refine_mesh_near; returns every pass state plus lineage.
    states[k] = (points, triangles, tags) after k passes; origin[k][t] = S0 triangle index of stage-k triangle t;
    kinds[k][t] = tuple of split kinds over passes 1..k."""
    states = [(points, triangles, tags)]
    origin = [np.arange(len(triangles), dtype=np.int64)]
    kinds = [[()] * len(triangles)]
    for _ in range(levels):
        centroids = points[triangles].mean(axis=1)
        marked = np.array([predicate(c) for c in centroids], dtype=bool)
        if not marked.any():
            break
        points, triangles, tags, par, knd = refine_once_traced(points, triangles, tags, marked)
        origin.append(origin[-1][par])
        prev = kinds[-1]
        kinds.append([prev[p] + (int(k),) for p, k in zip(par, knd)])
        states.append((points, triangles, tags))
    return states, origin, kinds


def exact_orient2(p, q, r):
    """Twice the signed area with the exact binary values of the float coordinates."""
    px, py, qx, qy, rx, ry = (Fraction(float(v)) for v in (p[0], p[1], q[0], q[1], r[0], r[1]))
    return (qx - px) * (ry - py) - (qy - py) * (rx - px)


def ccw_only(points, triangles):
    """Same vertex sets; a triangle with negative exact orientation gets vertices 1 and 2 swapped."""
    out = np.array(triangles, copy=True)
    flipped = 0
    for i, (a, b, c) in enumerate(out):
        o = exact_orient2(points[a], points[b], points[c])
        if o < 0:
            out[i] = (a, c, b)
            flipped += 1
        elif o == 0:
            raise ValueError(f"zero-area triangle {i}")
    return out, flipped


def exact_area(points, triangles):
    return sum(abs(exact_orient2(points[a], points[b], points[c])) for a, b, c in triangles) / 2


def min_angle_deg_per_triangle(P, tris):
    P = np.asarray(P, dtype=float)
    T = np.asarray(tris, dtype=np.int64)
    out = np.full(len(T), 180.0)
    for k in range(3):
        a, b, c = T[:, k], T[:, (k + 1) % 3], T[:, (k + 2) % 3]
        u, v = P[b] - P[a], P[c] - P[a]
        ang = np.degrees(np.arctan2(np.abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]), (u * v).sum(1)))
        out = np.minimum(out, ang)
    return out


def max_angle_deg_per_triangle(P, tris):
    P = np.asarray(P, dtype=float)
    T = np.asarray(tris, dtype=np.int64)
    out = np.zeros(len(T))
    for k in range(3):
        a, b, c = T[:, k], T[:, (k + 1) % 3], T[:, (k + 2) % 3]
        u, v = P[b] - P[a], P[c] - P[a]
        ang = np.degrees(np.arctan2(np.abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]), (u * v).sum(1)))
        out = np.maximum(out, ang)
    return out


def node_budget(P, tris, n_nodes):
    """PLAN section 4: b_i = 2^-46 / sin(theta_i), theta_i = smallest angle of the triangles incident to node i."""
    tmin = min_angle_deg_per_triangle(P, tris)
    th = np.full(n_nodes, 90.0)
    for t, a in zip(tris, tmin):
        for v in t:
            if a < th[v]:
                th[v] = a
    return 2.0 ** -46 / np.sin(np.radians(th))
