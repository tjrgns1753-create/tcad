"""E6H pre-criteria investigation (pure numpy, no DEVSIM): assemble the Voronoi finite-volume operator (cotangent edge weights, Voronoi
node areas -- for non-obtuse triangles this is the F3 / EdgeCouple convention DEVSIM uses) on real structured_lateral_refine outputs and
measure whether the quadratic psi = rho x (L-x)/(2 eps) is reproduced at nodes. Decides which acceptance form the DEVSIM test uses."""
import os
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
from tcad.device.devsim.mesh_refine import structured_lateral_refine  # noqa: E402


def grid(xs, ys):
    nx = len(xs) - 1
    P = np.array([[x, y, 0.0] for y in ys for x in xs])
    T = []
    for j in range(len(ys) - 1):
        for i in range(nx):
            a, b = j * (nx + 1) + i, j * (nx + 1) + i + 1
            T += [(a, b, b + nx + 1), (a, b + nx + 1, a + nx + 1)]
    return P, np.array(T), np.full(len(T), 10, dtype=np.int32)


def fv(P, T):
    n = len(P)
    W, V = {}, np.zeros(n)
    for t in T.tolist():
        for k in range(3):
            i, j, o = t[k], t[(k + 1) % 3], t[(k + 2) % 3]
            u, v = P[i, :2] - P[o, :2], P[j, :2] - P[o, :2]
            cot = (u @ v) / abs(u[0] * v[1] - u[1] * v[0])
            W[(min(i, j), max(i, j))] = W.get((min(i, j), max(i, j)), 0.0) + 0.5 * cot
            # Voronoi area contribution of triangle to vertices i and j from the angle at o
            V[i] += 0.125 * cot * ((P[j, :2] - P[o, :2]) @ (P[j, :2] - P[o, :2])) * 0  # placeholder (filled below)
    for t in T.tolist():
        for k in range(3):
            i, j, o = t[k], t[(k + 1) % 3], t[(k + 2) % 3]
            # vertex i: area of Voronoi region inside this triangle = 1/8 (|ij|^2 cot(angle at o) + |io|^2 cot(angle at j))
            lij2 = (P[i, :2] - P[j, :2]) @ (P[i, :2] - P[j, :2])
            lio2 = (P[i, :2] - P[o, :2]) @ (P[i, :2] - P[o, :2])
            u, v = P[i, :2] - P[o, :2], P[j, :2] - P[o, :2]
            cot_o = (u @ v) / abs(u[0] * v[1] - u[1] * v[0])
            u, v = P[i, :2] - P[j, :2], P[o, :2] - P[j, :2]
            cot_j = (u @ v) / abs(u[0] * v[1] - u[1] * v[0])
            V[i] += 0.125 * (lij2 * cot_o + lio2 * cot_j)
    return W, V


def solve(P, T, rho, eps=1.0):
    W, V = fv(P, T)
    n = len(P)
    A = np.zeros((n, n))
    for (i, j), w in W.items():
        A[i, i] += eps * w; A[j, j] += eps * w; A[i, j] -= eps * w; A[j, i] -= eps * w
    x = P[:, 0]
    L = x.max() - x.min()
    exact = rho * (x - x.min()) * (L - (x - x.min())) / (2 * eps)
    b = rho * V
    fixed = (x == x.min()) | (x == x.max())
    free = ~fixed
    u = np.zeros(n)
    u[free] = np.linalg.solve(A[np.ix_(free, free)], b[free] - A[np.ix_(free, fixed)] @ u[fixed])
    resid = A @ exact - b            # truncation residual of the exact quadratic at each node
    return u, exact, resid, V


def report(name, P, T):
    u, ex, r, V = solve(P, T, 1.0)
    free = ~((P[:, 0] == P[:, 0].min()) | (P[:, 0] == P[:, 0].max()))
    print(f"{name}: nodes {len(P)} tri {len(T)} max|u-exact| {np.abs(u - ex).max():.3e} (max exact {ex.max():.3e}) "
          f"max|residual of exact| {np.abs(r[free]).max():.3e} rel-to-V {np.abs(r[free] / V[free]).max():.3e}")


if __name__ == "__main__":
    P, T, G = grid([float(i) for i in range(9)], [0.0, 1.0, 2.0])
    report("uniform", P, T)
    for label, xs, ys, c, r in (("one-sided (3-tri) center 4 rings 1,.5", [float(i) for i in range(9)], [0.0, 1.0, 2.0], [4.0], [1.0, 0.5]),
                                ("two-sided (4-tri) centers 2,5 ring 1", [float(i) for i in range(9)], [0.0, 1.0, 2.0], [2.0, 5.0], [1.0]),
                                ("nonuniform x, unequal rows", [0.0, .6, 1.5, 2.0, 3.1, 4.0, 5.2, 6.0], [0.0, .4, 1.0], [3.1], [0.8, 0.4])):
        P, T, G = grid(xs, ys)
        P1, T1, G1, rep = structured_lateral_refine(P, T, G, c, r)
        report(label, P1, T1)
    print("--- convergence: domain L = 8 x H = 2 (fixed), base cells h x h, h = L / n, rows n / 4")
    for label, fam in (("one-sided family (center L/2 fixed, rings h, h/2)", lambda h: ([4.0], [h, h / 2])),
                       ("two-sided family (centers 2h, 5h, ring h)", lambda h: ([2 * h, 5 * h], [h]))):
        prev = None
        for n in (8, 16, 32, 64):
            h = 8.0 / n
            P, T, G = grid([h * i for i in range(n + 1)], [h * j for j in range(n // 4 + 1)])
            c, r = fam(h)
            P1, T1, G1, rep = structured_lateral_refine(P, T, G, c, r)
            u, ex, res, V = solve(P1, T1, 1.0)
            err = np.abs(u - ex).max()
            print(f"{label} n={n}: tri {len(T1)} max|u-exact| {err:.4e} rel {err / ex.max():.4e}" + ("" if prev is None else f"  ratio {prev / err:.3f}"))
            prev = err
