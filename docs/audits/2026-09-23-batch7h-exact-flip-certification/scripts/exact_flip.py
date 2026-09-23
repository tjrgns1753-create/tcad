"""Batch 7H-A: exact-safe constrained Lawson flip (audit copy only).

Differences from Rev.1's candidate_a_edge_flip_v2.py (which is left untouched):
  * Violation criterion is the exact incircle predicate (integer arithmetic),
    not a float angle sum with slack. A cocircular quad (incircle == 0) is
    never flipped, so no flip can be undone by a later flip of the same quad
    (Lawson: every strict flip strictly lowers the lifted paraboloid surface;
    the set of triangulations is finite, so the loop terminates without
    cycling). An oscillation detector is kept anyway and stops the run.
  * Every safety test is exact: strict convexity, exact old/new union area
    equality, exact positive new-triangle area, exact external overlap
    classification. There is no UNKNOWN verdict.
  * A flip is rejected if the number OR the exact area of positive-area
    overlaps between the quad's triangles and external triangles increases.
"""
from fractions import Fraction

import exact_geometry as eg


def _owners(tris):
    owners = {}
    for ti, t in enumerate(tris):
        v0, v1, v2 = t
        for a, b, opp in ((v0, v1, v2), (v1, v2, v0), (v2, v0, v1)):
            owners.setdefault((a, b) if a < b else (b, a), []).append((ti, opp))
    return owners


def eligible(edge, own, tags, protected):
    """Unconstrained interior edge: exactly two owners, same material, not in
    the protected (boundary/contact/interface) set."""
    if len(own) != 2 or edge in protected:
        return False
    return tags[own[0][0]] == tags[own[1][0]]


def is_violation(ipts, a, b, c, d):
    if eg.orient(ipts[a], ipts[b], ipts[c]) < 0:
        a, b = b, a
    return eg.incircle(ipts[a], ipts[b], ipts[c], ipts[d]) > 0


def exact_violations(ipts, tris, tags, protected):
    out = []
    for e, own in _owners(tris).items():
        if not eligible(e, own, tags, protected):
            continue
        (t1, c), (t2, d) = own
        if is_violation(ipts, e[0], e[1], c, d):
            out.append((e, t1, t2, c, d))
    return sorted(out)


def _ccw_tri(ipts, a, b, c):
    return [a, b, c] if eg.orient(ipts[a], ipts[b], ipts[c]) > 0 else [a, c, b]


def _local_positive(ipts, tris, own_idx, externals, K):
    pos = []
    area = Fraction(0)
    n_touch = 0
    for ti in own_idx:
        for tj in externals:
            v = eg.classify_pair(ipts, tris[ti], tris[tj])
            if v == eg.POSITIVE or v == eg.DUPLICATE or v == eg.INVALID:
                pos.append((ti, tj, v))
                if v == eg.POSITIVE:
                    area += eg.exact_intersection_polygon(ipts, tris[ti], tris[tj], K)[1]
            elif v == eg.TOUCH:
                n_touch += 1
    return pos, area, n_touch


def exact_flip(points_xy, triangles, tags, protected=frozenset(), max_passes=50, violation_fn=None):
    ipts, K = eg.exact_integer_points(points_xy)
    tris = [[int(v) for v in t] for t in triangles]
    tags = [int(t) for t in tags]
    violation_fn = violation_fn or is_violation
    history = []            # one record per accepted flip
    quad_diagonals = {}     # frozenset(quad) -> list of diagonals it has had
    passes = []
    for p in range(max_passes):
        own = _owners(tris)
        cands = []
        for e, o in own.items():
            if not eligible(e, o, tags, protected):
                continue
            (t1, c), (t2, d) = o
            if violation_fn(ipts, e[0], e[1], c, d):
                cands.append((e, t1, t2, c, d))
        cands.sort()
        if not cands:
            passes.append({"pass": p, "n_violations_before": 0, "n_flips": 0})
            return tris, tags, {"terminated": "no_exact_violations_remaining", "passes": passes,
                                "history": history, "K": K}
        cell = eg.default_cell(ipts, tris)
        boxes = [eg.tri_bbox(ipts, t) for t in tris]
        grid = {}
        for ti, (x0, x1, y0, y1) in enumerate(boxes):
            for gx in range(x0 // cell, x1 // cell + 1):
                for gy in range(y0 // cell, y1 // cell + 1):
                    grid.setdefault((gx, gy), set()).add(ti)
        touched = set()
        rejects = {"triangle_already_touched": 0, "stale_edge": 0, "not_strictly_convex": 0,
                   "union_area_mismatch": 0, "nonpositive_new_area": 0, "overlap_would_increase": 0}
        n_flips = 0
        for (a, b), t1, t2, c, d in cands:
            if t1 in touched or t2 in touched:
                rejects["triangle_already_touched"] += 1
                continue
            if set(tris[t1]) != {a, b, c} or set(tris[t2]) != {a, b, d}:
                rejects["stale_edge"] += 1
                continue
            A, B, C, D = ipts[a], ipts[b], ipts[c], ipts[d]
            o_abc, o_abd = eg.orient(A, B, C), eg.orient(A, B, D)
            o_cda, o_cdb = eg.orient(C, D, A), eg.orient(C, D, B)
            if not (o_abc * o_abd < 0 and o_cda * o_cdb < 0):
                rejects["not_strictly_convex"] += 1
                continue
            if abs(o_abc) + abs(o_abd) != abs(o_cda) + abs(o_cdb):
                rejects["union_area_mismatch"] += 1
                continue
            n1, n2 = _ccw_tri(ipts, a, c, d), _ccw_tri(ipts, b, c, d)
            if eg.orient(*[ipts[v] for v in n1]) <= 0 or eg.orient(*[ipts[v] for v in n2]) <= 0:
                rejects["nonpositive_new_area"] += 1
                continue
            qx0 = min(A[0], B[0], C[0], D[0]); qx1 = max(A[0], B[0], C[0], D[0])
            qy0 = min(A[1], B[1], C[1], D[1]); qy1 = max(A[1], B[1], C[1], D[1])
            ext = set()
            for gx in range(qx0 // cell, qx1 // cell + 1):
                for gy in range(qy0 // cell, qy1 // cell + 1):
                    ext |= grid.get((gx, gy), set())
            ext -= {t1, t2}
            ext = sorted(tj for tj in ext if not (boxes[tj][1] < qx0 or qx1 < boxes[tj][0]
                                                   or boxes[tj][3] < qy0 or qy1 < boxes[tj][2]))
            before, area_b, touch_b = _local_positive(ipts, tris, (t1, t2), ext, K)
            old1, old2 = tris[t1], tris[t2]
            tris[t1], tris[t2] = n1, n2
            after, area_a, touch_a = _local_positive(ipts, tris, (t1, t2), ext, K)
            if len(after) > len(before) or area_a > area_b:
                tris[t1], tris[t2] = old1, old2
                rejects["overlap_would_increase"] += 1
                continue
            quad = frozenset((a, b, c, d))
            old_diag = (min(a, b), max(a, b))
            new_diag = (min(c, d), max(c, d))
            seen = quad_diagonals.setdefault(quad, [old_diag])
            oscillation = new_diag in seen
            seen.append(new_diag)
            history.append({"pass": p, "quad": sorted(quad), "old_diagonal": old_diag, "new_diagonal": new_diag,
                            "triangles": (t1, t2), "n_external_checked": len(ext),
                            "external_positive_before": len(before), "external_positive_after": len(after),
                            "external_touch_before": touch_b, "external_touch_after": touch_a,
                            "reflip_to_earlier_diagonal": oscillation})
            if oscillation:
                passes.append({"pass": p, "n_violations_before": len(cands), "n_flips": n_flips + 1, "rejects": rejects})
                return tris, tags, {"terminated": "OSCILLATION_DETECTED", "passes": passes, "history": history, "K": K}
            for tt in (t1, t2):
                boxes[tt] = (qx0, qx1, qy0, qy1)
                for gx in range(qx0 // cell, qx1 // cell + 1):
                    for gy in range(qy0 // cell, qy1 // cell + 1):
                        grid.setdefault((gx, gy), set()).add(tt)
            touched |= {t1, t2}
            n_flips += 1
        passes.append({"pass": p, "n_violations_before": len(cands), "n_flips": n_flips, "rejects": rejects})
        if n_flips == 0:
            return tris, tags, {"terminated": "no_legal_exact_flip_left", "passes": passes, "history": history, "K": K}
    return tris, tags, {"terminated": "max_passes_reached", "passes": passes, "history": history, "K": K}
