"""Batch 7H-E6F audit prototype (NOT production): red-green-BLUE closure with exact non-obtuse checks, to test whether a local
alternative exists after the red-promotion rule was shown to spread over the whole mesh. Pure numpy / Fraction; float64 midpoints.

Per triangle, S = edges scheduled for bisection. Iterated to a fixed point (S only grows):
  0 edges in S -> untouched;  3 -> red (4 midpoint children);
  1 edge e     -> green (apex to midpoint of e) if both children are exactly non-obtuse, else blue if e is not the longest edge L
                  (L is added to S), else red;
  2 edges      -> blue if one of them is L and all three blue children are exactly non-obtuse, else red.
Blue split with L = (P, Q) opposite R and the other split edge e = (Q, R) (or (R, P), symmetric): N = mid(L), M = mid(e);
children (R, P, N), (N, Q, M), (N, M, R). A red triangle adds its three edges to S."""
from fractions import Fraction

import numpy as np


def _key(a, b):
    return (a, b) if a < b else (b, a)


def _ok(p0, p1, p2):
    q = [(Fraction(float(p[0])), Fraction(float(p[1]))) for p in (p0, p1, p2)]
    (ax, ay), (bx, by), (cx, cy) = q
    if (bx - ax) * (cy - ay) - (by - ay) * (cx - ax) == 0:
        return False
    return all((ux - ox) * (vx - ox) + (uy - oy) * (vy - oy) >= 0
               for (ox, oy), (ux, uy), (vx, vy) in ((q[0], q[1], q[2]), (q[1], q[2], q[0]), (q[2], q[0], q[1])))


def refine_once_rgb(points, triangles, tags, marked):
    P = np.asarray(points, dtype=np.float64)
    T = [tuple(int(v) for v in t) for t in triangles]
    mid = {}

    def mpt(a, b):
        return (P[a] + P[b]) / 2.0

    def l2(a, b):
        d = [Fraction(float(P[a][i])) - Fraction(float(P[b][i])) for i in (0, 1)]
        return d[0] * d[0] + d[1] * d[1]

    def longest(t):
        es = [(t[0], t[1]), (t[1], t[2]), (t[2], t[0])]
        return max(es, key=lambda e: l2(*e))

    def blue_children(t, L, e):
        p, q = L
        r = next(v for v in t if v not in L)
        N = mpt(p, q)
        if set(e) == {q, r}:
            M = mpt(q, r)
            return [(P[r], P[p], N), (N, P[q], M), (N, M, P[r])]
        M = mpt(r, p)
        return [(P[r], N, P[q]), (N, P[r], M), (N, M, P[p])]

    red = list(marked)
    S = set()
    for i, t in enumerate(T):
        if red[i]:
            S |= {_key(t[0], t[1]), _key(t[1], t[2]), _key(t[2], t[0])}
    status = [None] * len(T)
    changed = True
    while changed:
        changed = False
        for i, t in enumerate(T):
            if red[i]:
                continue
            es = [(t[0], t[1]), (t[1], t[2]), (t[2], t[0])]
            br = [e for e in es if _key(*e) in S]
            L = longest(t)
            new = None
            if len(br) == 3:
                new = "red"
            elif len(br) == 1:
                e = br[0]
                apex = next(v for v in t if v not in e)
                m = mpt(*e)
                if _ok(P[apex], P[e[0]], m) and _ok(P[apex], m, P[e[1]]):
                    new = ("green", e)
                elif _key(*e) != _key(*L) and all(_ok(*c) for c in blue_children(t, L, e)):
                    new = ("blue", L, e)
                else:
                    new = "red"
            elif len(br) == 2:
                if any(_key(*e) == _key(*L) for e in br):
                    e = next(x for x in br if _key(*x) != _key(*L))
                    new = ("blue", L, e) if all(_ok(*c) for c in blue_children(t, L, e)) else "red"
                else:
                    new = "red"
            if new == "red":
                red[i] = True
                S |= {_key(*x) for x in es}
                changed = True
            elif new is not None and new[0] == "blue" and _key(*new[1]) not in S:
                S.add(_key(*new[1]))
                changed = True
            status[i] = new
    pts = list(P)

    def midx(a, b):
        k = _key(a, b)
        if k not in mid:
            pts.append(mpt(a, b))
            mid[k] = len(pts) - 1
        return mid[k]
    out_t, out_g = [], []
    for i, t in enumerate(T):
        g = int(tags[i])
        st = "red" if red[i] else status[i]
        if st is None:
            out_t.append(t)
            out_g.append(g)
        elif st == "red":
            a, b, c = t
            ab, bc, ca = midx(a, b), midx(b, c), midx(c, a)
            out_t += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
            out_g += [g] * 4
        elif st[0] == "green":
            e = st[1]
            apex = next(v for v in t if v not in e)
            # keep the parent's orientation: t = (apex, e0, e1) cyclically
            k = t.index(apex)
            a, b, c = t[k], t[(k + 1) % 3], t[(k + 2) % 3]
            m = midx(b, c)
            out_t += [(a, b, m), (a, m, c)]
            out_g += [g] * 2
        else:
            L, e = st[1], st[2]
            r = next(v for v in t if v not in L)
            k = t.index(r)
            a, b, c = t[k], t[(k + 1) % 3], t[(k + 2) % 3]      # r = a, L = (b, c) in the parent's orientation
            n = midx(b, c)
            if set(e) == {c, a}:
                m = midx(c, a)
                out_t += [(a, b, n), (n, c, m), (n, m, a)]
            else:
                m = midx(a, b)
                out_t += [(a, m, n), (m, b, n), (a, n, c)]
            out_g += [g] * 3
    return np.array(pts, dtype=np.float64), np.array(out_t, dtype=np.int64), np.array(out_g, dtype=np.asarray(tags).dtype)


def refine_mesh_near_rgb(points, triangles, tags, predicate, levels=1):
    for _ in range(levels):
        c = np.asarray(points, dtype=np.float64)[np.asarray(triangles)].mean(axis=1)
        marked = [bool(predicate(x)) for x in c]
        if not any(marked):
            break
        points, triangles, tags = refine_once_rgb(points, triangles, tags, marked)
    return points, triangles, tags
