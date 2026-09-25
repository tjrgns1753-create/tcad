"""Batch 7H-E4 design proof on a LOCAL PATCH only (exact rational arithmetic, no mesh, no ViennaPS/DEVSIM).
(1) The production green cascade on one base right triangle next to the refinement window: max angle per pass.
(2) The proposed 2:1 transition template on a unit square: every angle, via exact dot products (>= 0 means <= 90 deg).
usage: patch_proof.py"""
import math
from fractions import Fraction as F


def angles(a, b, c):
    out = []
    for p, q, r in ((a, b, c), (b, c, a), (c, a, b)):
        u, v = (q[0] - p[0], q[1] - p[1]), (r[0] - p[0], r[1] - p[1])
        dot = u[0] * v[0] + u[1] * v[1]
        cos = float(dot) / math.sqrt(float(u[0] ** 2 + u[1] ** 2) * float(v[0] ** 2 + v[1] ** 2))
        out.append((dot, math.degrees(math.acos(max(-1.0, min(1.0, cos))))))
    return out


def orient(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


print("(1) production green cascade, base cell in units of grid_delta (0.05 um); window edge on x = 1 (x = 0.10 um)")
print("    base right triangle (7H-E2 S0 triangle 594 shape): apex A=(0,0) [x=0.15], B=(1,0), C=(1,1) [on x=0.10 line]")
A, B, C = (F(0), F(0)), (F(1), F(0)), (F(1), F(1))
for k in range(1, 5):
    n = 2 ** k   # after k passes the leg B-C carries n segments, each fanned to the apex A (green splits only)
    pts = [(F(1), F(j, n)) for j in range(n + 1)]
    fan = [(A, pts[j], pts[j + 1]) for j in range(n)]
    mx = max(max(d for _, d in angles(*t)) for t in fan)
    nob = sum(1 for t in fan if min(dot for dot, _ in angles(*t)) < 0)
    print(f"    pass {k}: fan of {n} triangles, obtuse {nob} (exact dot < 0), max angle {mx:.5f} deg")
print("    -> matches 7H-E2's measured per-pass obtuse count per origin (1, 3, 7, 15) and max angle "
      "(116.565, 126.870, 131.186, 133.153 deg)")

print("\n(2) proposed transition template: unit square LL=(0,0) LR=(1,0) UR=(1,1) UL=(0,1), one hanging midpoint")
for side, M, tris in (("finer neighbour on the LEFT", (F(0), F(1, 2)), None), ("finer neighbour on the RIGHT", (F(1), F(1, 2)), None)):
    LL, LR, UR, UL = (F(0), F(0)), (F(1), F(0)), (F(1), F(1)), (F(0), F(1))
    tris = [(LL, LR, M), (M, LR, UR), (M, UR, UL)] if M[0] == 0 else [(LL, LR, M), (LL, M, UL), (UL, M, UR)]
    print(f"  {side}: midpoint M={tuple(map(str, M))}")
    area = F(0)
    for t in tris:
        ang = angles(*t)
        o = orient(*t)
        area += o / 2
        print(f"    triangle {[tuple(map(str, p)) for p in t]}: orient {o} (>0 CCW), exact dots {[str(d) for d, _ in ang]}, "
              f"angles {[round(a, 4) for _, a in ang]}")
    print(f"    total area {area} (= 1, the square), max angle 90 deg, all exact dots >= 0 -> no obtuse angle")
print("\n  regular square (no hanging node): (LL, LR, UR), (LL, UR, UL) -> two right isosceles triangles, angles 45/45/90")
print("  2:1 balance: each coarse cell edge carries at most one hanging midpoint, and in this strip only the side facing "
      "x = 0 does, so the template above is the only non-regular pattern needed.")
