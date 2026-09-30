#!/usr/bin/env python3
"""Pure checks of tcad.device.devsim.mesh_refine.structured_lateral_refine (Batch 7H-E6G): the structured-grid transition-template
remesher used by refine_process_result_for_implant_windows for single-Si, axis-aligned structured grids refined in x bands.
Every geometric property is checked exactly (rational arithmetic). Criteria:
docs/audits/2026-10-01-batch7h-e6g-structured-template/CRITERIA.md"""
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tcad.device.devsim.mesh_refine import (  # noqa: E402
    StructuredRemeshAborted, StructuredRemeshUnsupported, refine_mesh_near, structured_lateral_refine,
)


def grid(xs, ys, split=None, dtype=np.float64):
    nx = len(xs) - 1
    pts = np.array([[x, y, 0.0] for y in ys for x in xs], dtype=dtype)
    tris, tags = [], []
    for j in range(len(ys) - 1):
        for i in range(nx):
            a, b = j * (nx + 1) + i, j * (nx + 1) + i + 1
            c, d = b + nx + 1, a + nx + 1
            tris += [(a, b, c), (a, c, d)]
            tags += [10 if split is None or i < split else 11] * 2
    return pts, np.array(tris), np.array(tags, dtype=np.int32)


def exact(P, T, P0, T0):
    X, Y = [Fraction(float(v)) for v in P[:, 0]], [Fraction(float(v)) for v in P[:, 1]]
    X0, Y0 = [Fraction(float(v)) for v in P0[:, 0]], [Fraction(float(v)) for v in P0[:, 1]]
    obt = deg = 0
    signs = set()
    area = Fraction(0)
    for a, b, c in T.tolist():
        o = (X[b] - X[a]) * (Y[c] - Y[a]) - (Y[b] - Y[a]) * (X[c] - X[a])
        deg += o == 0
        signs.add(o > 0)
        area += abs(o) / 2
        obt += any((X[u] - X[w]) * (X[v] - X[w]) + (Y[u] - Y[w]) * (Y[v] - Y[w]) < 0 for w, u, v in ((a, b, c), (b, c, a), (c, a, b)))
    area0 = sum((abs((X0[b] - X0[a]) * (Y0[c] - Y0[a]) - (Y0[b] - Y0[a]) * (X0[c] - X0[a])) / 2 for a, b, c in T0.tolist()), Fraction(0))
    own = {}
    for a, b, c in T.tolist():
        for u, v in ((a, b), (b, c), (c, a)):
            own.setdefault((min(u, v), max(u, v)), []).append(u < v)
    hanging = 0
    for (u, v) in own:
        for w in range(len(P)):
            if w in (u, v):
                continue
            if (X[w] - X[u]) * (Y[v] - Y[u]) - (Y[w] - Y[u]) * (X[v] - X[u]) == 0 and \
                    min(X[u], X[v]) <= X[w] <= max(X[u], X[v]) and min(Y[u], Y[v]) <= Y[w] <= max(Y[u], Y[v]):
                hanging += 1
    return {"obtuse": obt, "degenerate": deg, "one_orientation": len(signs) == 1, "area_equal": area == area0,
            "owners_ok": all(len(v) <= 2 and (len(v) < 2 or v[0] != v[1]) for v in own.values()), "hanging": hanging,
            "nodes_kept": bool(np.array_equal(P[:len(P0), :2], P0[:, :2]))}


def canon(P, T):
    return sorted(tuple(sorted(tuple(P[v, :2].tolist()) for v in t)) for t in T.tolist())


def ok(rep):
    return rep == {"obtuse": 0, "degenerate": 0, "one_orientation": True, "area_equal": True, "owners_ok": True, "hanging": 0, "nodes_kept": True}


def refused(fn, cls, reason):
    try:
        fn()
    except cls as e:
        assert e.reason == reason, (e.reason, reason)
        return
    raise AssertionError(f"expected {cls.__name__} {reason}")


def main():
    # A: the green-split counterexample geometry -- the old red-green pass leaves one obtuse child; the template build leaves none
    P, T, G = grid([0.0, 1.0, 2.0], [0.0, 1.0])
    Po, To, _ = refine_mesh_near(P, T, G, lambda c: c[0] < 1.0 and c[1] < 0.5, levels=1)
    assert exact(Po, To, P, T)["obtuse"] == 1
    P1, T1, G1, rep = structured_lateral_refine(P, T, G, [0.5], [0.5])
    assert ok(exact(P1, T1, P, T)) and set(G1.tolist()) == {10}, exact(P1, T1, P, T)
    print("A: old red-green 1 obtuse; template build", len(T1), "triangles, 0 obtuse, conforming, area exact")

    # B: local window, 3 rings; locality: columns far from the window keep their original triangles; order control
    P, T, G = grid([float(i) for i in range(11)], [float(j) for j in range(11)])
    P1, T1, G1, rep = structured_lateral_refine(P, T, G, [5.0], [1.0, 0.5, 0.25])
    assert ok(exact(P1, T1, P, T)), exact(P1, T1, P, T)
    far = {tuple(t) for t in T.tolist() if P[t, 0].max() <= 2.0 or P[t, 0].min() >= 8.0}
    assert far <= {tuple(t) for t in T1.tolist()}, "far-field triangles were rebuilt"
    rng = np.random.default_rng(7)
    perm = rng.permutation(len(P))
    inv = np.argsort(perm)
    Tp = np.roll(inv[T][rng.permutation(len(T))], 1, axis=1)
    P2, T2, _, _ = structured_lateral_refine(P[perm], Tp, G, [5.0], [1.0, 0.5, 0.25])
    assert canon(P1, T1) == canon(P2, T2), "output depends on node / triangle order"
    print("B: 1180 triangles expected ->", len(T1), "; far field untouched; permuted input gives the same geometry")

    # C: float32 coordinates, slightly anisotropic cells; target resolution in every band
    xs = [float(np.float32(0.2 * i)) for i in range(16)]
    ys = [float(np.float32(0.2 * (1 + 1e-3) * j)) for j in range(6)]
    P, T, G = grid(xs, ys, dtype=np.float32)
    c, rings = float(np.float32(1.4)), [0.2, 0.1, 0.05]
    P1, T1, G1, rep = structured_lateral_refine(P, T, G, [c], rings)
    assert ok(exact(P1, T1, P, T)), exact(P1, T1, P, T)
    X0 = np.unique(P[:, 0].astype(float))
    for t in T1.tolist():
        q = P1[t, :2]
        cx = q[:, 0].mean()
        need = max([k + 1 for k, hw in enumerate(rings) if abs(cx - c) < hw] or [0])
        if need:
            i = int(np.searchsorted(X0, cx)) - 1
            assert Fraction(float(q[:, 0].max())) - Fraction(float(q[:, 0].min())) <= (Fraction(float(X0[i + 1])) - Fraction(float(X0[i]))) / 2 ** need
    print("C: float32 anisotropic grid:", len(T1), "triangles, exact checks and band resolution hold")

    # D: two separate windows, one center off the grid lines
    P, T, G = grid([0.5 * i for i in range(17)], [0.5 * j for j in range(5)])
    P1, T1, _, _ = structured_lateral_refine(P, T, G, [1.6, 6.3], [0.5, 0.25, 0.125])
    assert ok(exact(P1, T1, P, T))
    print("D: two windows:", len(T1), "triangles, exact checks hold")

    # identity: no band touches the domain
    P, T, G = grid([float(i) for i in range(5)], [0.0, 1.0])
    out = structured_lateral_refine(P, T, G, [100.0], [0.5])
    assert out[0] is P and out[1] is T and out[3]["identity"]

    # G: refusals and aborts
    P, T, G = grid([float(i) for i in range(6)], [float(j) for j in range(4)], split=3)
    refused(lambda: structured_lateral_refine(P, T, G, [2.5], [0.5]), StructuredRemeshUnsupported, "MULTI_MATERIAL")
    P, T, G = grid([float(i) for i in range(6)], [float(j) for j in range(4)])
    refused(lambda: structured_lateral_refine(P, T[1:], G[1:], [2.5], [0.5]), StructuredRemeshUnsupported, "NOT_TWO_TRIANGLES_PER_CELL")
    Pz = P.copy()
    Pz[0, 2] = 1e-3
    refused(lambda: structured_lateral_refine(Pz, T, G, [2.5], [0.5]), StructuredRemeshUnsupported, "NOT_PLANAR")
    To = T.copy()
    To[0] = [T[0][0], T[0][1], T[1][2]]                      # replace a half by an overlapping triangle of the same cell
    refused(lambda: structured_lateral_refine(P, To, G, [2.5], [0.5]), StructuredRemeshUnsupported, "CELL_HALVES_OVERLAP")
    P, T, G = grid([0.1 * i for i in range(11)], [float(j) for j in range(3)])
    refused(lambda: structured_lateral_refine(P, T, G, [0.5], [0.1]), StructuredRemeshAborted, "TRANSITION_ASPECT")
    P, T, G = grid([float(i) for i in range(11)], [float(j) for j in range(11)])
    refused(lambda: structured_lateral_refine(P, T, G, [5.0], [1.0, 0.5, 0.25], cap=1000), StructuredRemeshAborted, "RESOURCE_CAP")
    print("G: multi-material, missing triangle, non-planar, overlapping halves refused; aspect and cap abort")
    print("ALL STRUCTURED REMESH MOCK CHECKS PASSED")


if __name__ == "__main__":
    main()
