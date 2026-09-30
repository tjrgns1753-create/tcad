"""Batch 7H-E6H exact conformity checker for a 2D triangle mesh that tiles an axis-aligned rectangle. Criteria: ../CRITERIA.md (A).

Every float64 coordinate is a dyadic rational, so all coordinates are converted to integers on one common power-of-two scale and every
test is exact integer arithmetic (no epsilon). The hanging-node (T-junction) test does not scan nodes x edges: nodes are indexed by their
exact x line, and an edge is tested against the nodes on the x lines strictly inside its x extent (a vertical edge against the nodes on
its own line strictly between its ends)."""
from bisect import bisect_left, bisect_right
from typing import Dict, List, Tuple

import numpy as np


def _dyadic_ints(values) -> List[int]:
    ratios = [float(v).as_integer_ratio() for v in values]
    k = max((d.bit_length() - 1 for _, d in ratios), default=0)
    return [n * ((1 << k) // d) for n, d in ratios]


def check_conformity(points, triangles) -> Dict[str, object]:
    P = np.asarray(points, dtype=np.float64)
    T = np.asarray(triangles)
    n, m = len(P), len(T)
    res: Dict[str, object] = {"nodes": n, "triangles": m}
    res["index_valid"] = bool(T.ndim == 2 and T.shape[1] == 3 and np.issubdtype(T.dtype, np.integer) and m > 0
                              and T.min() >= 0 and T.max() < n)
    if not res["index_valid"]:
        res["pass"] = False
        return res
    if P.shape[1] > 2 and np.any(P[:, 2:] != 0):
        res["planar"] = False
        res["pass"] = False
        return res
    scale_ints = _dyadic_ints(P[:, :2].reshape(-1).tolist())
    X, Y = scale_ints[0::2], scale_ints[1::2]
    res["duplicate_coordinates"] = n - len(set(zip(X, Y)))
    tri = [tuple(t) for t in T.tolist()]
    res["duplicate_triangles"] = m - len({tuple(sorted(t)) for t in tri})
    res["unused_nodes"] = n - len({v for t in tri for v in t})
    degenerate = 0
    positive = negative = 0
    area2 = 0
    for a, b, c in tri:
        o = (X[b] - X[a]) * (Y[c] - Y[a]) - (Y[b] - Y[a]) * (X[c] - X[a])
        if o == 0:
            degenerate += 1
        elif o > 0:
            positive += 1
        else:
            negative += 1
        area2 += abs(o)
    res["degenerate"] = degenerate
    res["one_orientation"] = bool(positive == 0 or negative == 0)
    # edge ownership: an interior edge is owned by exactly two triangles that traverse it in opposite directions
    owners: Dict[Tuple[int, int], List[bool]] = {}
    for a, b, c in tri:
        for u, v in ((a, b), (b, c), (c, a)):
            owners.setdefault((min(u, v), max(u, v)), []).append(u < v)
    too_many = sum(1 for v in owners.values() if len(v) > 2)
    same_direction = sum(1 for v in owners.values() if len(v) == 2 and v[0] == v[1])
    boundary = [e for e, v in owners.items() if len(v) == 1]
    res["edges"] = len(owners)
    res["edges_with_more_than_two_owners"] = too_many
    res["interior_edges_same_direction"] = same_direction
    res["boundary_edges"] = len(boundary)
    x0, x1, y0, y1 = min(X), max(X), min(Y), max(Y)
    sides = {"xmin": [], "xmax": [], "ymin": [], "ymax": []}
    off_rectangle = 0
    for u, v in boundary:
        if X[u] == X[v] == x0:
            sides["xmin"].append(tuple(sorted((Y[u], Y[v]))))
        elif X[u] == X[v] == x1:
            sides["xmax"].append(tuple(sorted((Y[u], Y[v]))))
        elif Y[u] == Y[v] == y0:
            sides["ymin"].append(tuple(sorted((X[u], X[v]))))
        elif Y[u] == Y[v] == y1:
            sides["ymax"].append(tuple(sorted((X[u], X[v]))))
        else:
            off_rectangle += 1
    res["boundary_edges_off_rectangle"] = off_rectangle
    chain_ok = True
    for name, (lo, hi) in {"xmin": (y0, y1), "xmax": (y0, y1), "ymin": (x0, x1), "ymax": (x0, x1)}.items():
        cursor = lo
        for a, b in sorted(sides[name]):
            if a != cursor:
                chain_ok = False
                break
            cursor = b
        else:
            chain_ok = chain_ok and cursor == hi
    res["boundary_covers_rectangle_exactly"] = bool(chain_ok and off_rectangle == 0)
    res["area_equals_rectangle"] = bool(area2 == 2 * (x1 - x0) * (y1 - y0))
    # hanging nodes: a node strictly inside an edge
    lines: Dict[int, List[int]] = {}
    for x, y in zip(X, Y):
        lines.setdefault(x, []).append(y)
    for ys in lines.values():
        ys.sort()
    line_sets = {x: set(ys) for x, ys in lines.items()}
    xs_sorted = sorted(lines)
    hanging = 0
    for u, v in owners:
        ax, ay, bx, by = X[u], Y[u], X[v], Y[v]
        if ax == bx:
            ys = lines[ax]
            lo, hi = min(ay, by), max(ay, by)
            hanging += bisect_left(ys, hi) - bisect_right(ys, lo)
            continue
        if ax > bx:
            ax, ay, bx, by = bx, by, ax, ay
        for xl in xs_sorted[bisect_right(xs_sorted, ax):bisect_left(xs_sorted, bx)]:
            num = (by - ay) * (xl - ax)
            den = bx - ax
            if num % den == 0 and (ay + num // den) in line_sets[xl]:
                hanging += 1
    res["hanging_nodes"] = hanging
    res["pass"] = bool(
        res["duplicate_coordinates"] == 0 and res["duplicate_triangles"] == 0 and res["unused_nodes"] == 0 and degenerate == 0
        and res["one_orientation"] and too_many == 0 and same_direction == 0 and res["boundary_covers_rectangle_exactly"]
        and res["area_equals_rectangle"] and hanging == 0)
    return res


def count_apex_triangles(points, triangles) -> int:
    """Triangles with exactly one axis-aligned edge and two diagonal edges (the isosceles apex triangle of a one-sided template)."""
    P = np.asarray(points, dtype=np.float64)
    count = 0
    for t in np.asarray(triangles).tolist():
        axis = 0
        for u, v in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            axis += bool(P[u, 0] == P[v, 0] or P[u, 1] == P[v, 1])
        count += axis == 1
    return count
