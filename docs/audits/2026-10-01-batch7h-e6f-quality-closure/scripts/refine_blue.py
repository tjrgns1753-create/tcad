"""Batch 7H-E6F audit module (NOT production): the red-green-blue closure of alt_rgb_e6f.py with the SAME decisions, made cheaper.

Decision per triangle (identical to alt_rgb_e6f.refine_once_rgb; see that file):
  scheduled edges S; 0 -> untouched; 3 -> red; 1 edge e -> green if both children exactly non-obtuse, else blue if e is not the
  longest edge L and the three blue children are exactly non-obtuse, else red; 2 edges -> blue if one is L and the blue children are
  exactly non-obtuse, else red. Red adds its three edges to S; blue adds L.
Cost changes only: float64 coordinates and midpoints cached per edge; exact squared edge lengths cached per edge; the longest edge
cached per triangle; quality verdicts cached per (triangle, split); a work queue that re-examines only the owners of newly scheduled
edges instead of sweeping every triangle; and a float screening of each sign (dot / cross product) with a bound of 8u times the sum of
the product magnitudes, falling back to exact rational arithmetic whenever the float value is within that bound. No angle is rounded.
Tie-breaking of the longest edge: first maximum in the order (v0,v1), (v1,v2), (v2,v0) -- the same as alt_rgb_e6f (deterministic for a
given vertex order, not orientation-invariant).
refine_once_blue raises ResourceLimit before building any output array when the child count would exceed `cap`."""
import collections
from fractions import Fraction

import numpy as np

U = 2.0 ** -53
STATS = collections.Counter()


class ResourceLimit(RuntimeError):
    pass


def _key(a, b):
    return (a, b) if a < b else (b, a)


def _dot_nonneg(o, u, v):
    ux, uy, vx, vy = u[0] - o[0], u[1] - o[1], v[0] - o[0], v[1] - o[1]
    d = ux * vx + uy * vy
    if abs(d) > 8 * U * (abs(ux * vx) + abs(uy * vy)):
        STATS["dot_float"] += 1
        return d > 0
    STATS["dot_exact"] += 1
    F = Fraction
    return (F(float(u[0])) - F(float(o[0]))) * (F(float(v[0])) - F(float(o[0]))) + \
           (F(float(u[1])) - F(float(o[1]))) * (F(float(v[1])) - F(float(o[1]))) >= 0


def _cross_nonzero(a, b, c):
    ux, uy, vx, vy = b[0] - a[0], b[1] - a[1], c[0] - a[0], c[1] - a[1]
    x = ux * vy - uy * vx
    if abs(x) > 8 * U * (abs(ux * vy) + abs(uy * vx)):
        STATS["cross_float"] += 1
        return True
    STATS["cross_exact"] += 1
    F = Fraction
    return (F(float(b[0])) - F(float(a[0]))) * (F(float(c[1])) - F(float(a[1]))) - \
           (F(float(b[1])) - F(float(a[1]))) * (F(float(c[0])) - F(float(a[0]))) != 0


def ok(p0, p1, p2):
    """Exactly non-obtuse and non-degenerate (float screening, exact fallback)."""
    if not _cross_nonzero(p0, p1, p2):
        return False
    return _dot_nonneg(p0, p1, p2) and _dot_nonneg(p1, p2, p0) and _dot_nonneg(p2, p0, p1)


def refine_once_blue(points, triangles, tags, marked, cap=None, stats=None):
    P = np.asarray(points, dtype=np.float64)
    T = [tuple(int(v) for v in t) for t in np.asarray(triangles).tolist()]
    n = len(T)
    owners = collections.defaultdict(list)
    for i, t in enumerate(T):
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            owners[_key(a, b)].append(i)
    mcache, l2cache, lcache, qcache = {}, {}, {}, {}

    def mpt(a, b):
        k = _key(a, b)
        if k not in mcache:
            mcache[k] = (P[k[0]] + P[k[1]]) / 2.0
        return mcache[k]

    def l2(a, b):
        k = _key(a, b)
        if k not in l2cache:
            d = [Fraction(float(P[a][i])) - Fraction(float(P[b][i])) for i in (0, 1)]
            l2cache[k] = d[0] * d[0] + d[1] * d[1]
        return l2cache[k]

    def longest(i):
        if i not in lcache:
            t = T[i]
            es = [(t[0], t[1]), (t[1], t[2]), (t[2], t[0])]
            lcache[i] = max(es, key=lambda e: l2(*e))
        return lcache[i]

    def blue_children(t, L, e):
        p, q = L
        r = next(v for v in t if v not in L)
        N = mpt(p, q)
        if set(e) == {q, r}:
            M = mpt(q, r)
            return [(P[r], P[p], N), (N, P[q], M), (N, M, P[r])]
        M = mpt(r, p)
        return [(P[r], N, P[q]), (N, P[r], M), (N, M, P[p])]

    def green_ok(i, e):
        k = ("g", i, _key(*e))
        if k not in qcache:
            t = T[i]
            apex = next(v for v in t if v not in e)
            m = mpt(*e)
            qcache[k] = ok(P[apex], P[e[0]], m) and ok(P[apex], m, P[e[1]])
        return qcache[k]

    def blue_ok(i, L, e):
        k = ("b", i, _key(*L), _key(*e))
        if k not in qcache:
            qcache[k] = all(ok(*c) for c in blue_children(T[i], L, e))
        return qcache[k]

    red = [bool(x) for x in marked]
    S = set()
    queue = collections.deque()
    queued = [False] * n

    def schedule(e):
        k = _key(*e)
        if k in S:
            return
        S.add(k)
        for o in owners[k]:
            if not red[o] and not queued[o]:
                queued[o] = True
                queue.append(o)
    for i, t in enumerate(T):
        if red[i]:
            for e in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                schedule(e)
    status = [None] * n
    pops = 0
    while queue:
        i = queue.popleft()
        queued[i] = False
        pops += 1
        if red[i]:
            continue
        t = T[i]
        es = [(t[0], t[1]), (t[1], t[2]), (t[2], t[0])]
        br = [e for e in es if _key(*e) in S]
        L = longest(i)
        new = None
        if len(br) == 3:
            new = "red"
        elif len(br) == 1:
            e = br[0]
            if green_ok(i, e):
                new = ("green", e)
            elif _key(*e) != _key(*L) and blue_ok(i, L, e):
                new = ("blue", L, e)
            else:
                new = "red"
        elif len(br) == 2:
            if any(_key(*e) == _key(*L) for e in br):
                e = next(x for x in br if _key(*x) != _key(*L))
                new = ("blue", L, e) if blue_ok(i, L, e) else "red"
            else:
                new = "red"
        if new == "red":
            red[i] = True
            status[i] = "red"
            for e in es:
                schedule(e)
        else:
            status[i] = new
            if new is not None and new[0] == "blue":
                schedule(new[1])
    counts = collections.Counter("red" if red[i] else ("untouched" if status[i] is None else status[i][0]) for i in range(n))
    children = 4 * counts["red"] + 3 * counts["blue"] + 2 * counts["green"] + counts["untouched"]
    if stats is not None:
        stats.update({"input_triangles": n, "input_points": int(len(P)), "red": counts["red"], "green": counts["green"],
                      "blue": counts["blue"], "untouched": counts["untouched"], "queue_pops": pops, "scheduled_edges": len(S),
                      "output_triangles": children, "output_points": int(len(P)) + len(S)})
    if cap is not None and children > cap:
        raise ResourceLimit(f"{children} output triangles would exceed the cap {cap}")
    pts = list(P)
    mid = {}

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
            k = t.index(apex)
            a, b, c = t[k], t[(k + 1) % 3], t[(k + 2) % 3]
            m = midx(b, c)
            out_t += [(a, b, m), (a, m, c)]
            out_g += [g] * 2
        else:
            L, e = st[1], st[2]
            r = next(v for v in t if v not in L)
            k = t.index(r)
            a, b, c = t[k], t[(k + 1) % 3], t[(k + 2) % 3]
            nn = midx(b, c)
            if set(e) == {c, a}:
                m = midx(c, a)
                out_t += [(a, b, nn), (nn, c, m), (nn, m, a)]
            else:
                m = midx(a, b)
                out_t += [(a, m, nn), (m, b, nn), (a, nn, c)]
            out_g += [g] * 3
    return np.array(pts, dtype=np.float64), np.array(out_t, dtype=np.int64), np.array(out_g, dtype=np.asarray(tags).dtype)


def refine_mesh_near_blue(points, triangles, tags, predicate, levels=1, cap=None, pass_stats=None):
    for _ in range(levels):
        c = np.asarray(points, dtype=np.float64)[np.asarray(triangles)].mean(axis=1)
        marked = [bool(predicate(x)) for x in c]
        if not any(marked):
            break
        st = {}
        points, triangles, tags = refine_once_blue(points, triangles, tags, marked, cap=cap, stats=st)
        if pass_stats is not None:
            pass_stats.append(st)
    return points, triangles, tags
