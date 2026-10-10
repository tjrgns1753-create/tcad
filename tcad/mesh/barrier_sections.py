"""Tagged 2D triangle geometry only; NOT an implant stopping/activation model.

Read material unions between exact boundary-coordinate breakpoints. Fraction
arithmetic preserves the serialized coordinates without rounding or buckets.
"""
from collections import Counter
from fractions import Fraction as F
import math


def covered_sections(points, triangles, tags, doped_tag, barrier_tag,
                     axis="x", min_thickness=0.0):
    if axis not in ("x", "y"):
        raise ValueError("BARRIER_AXIS_INVALID")
    if not math.isfinite(float(min_thickness)) or min_thickness < 0:
        raise ValueError("BARRIER_THRESHOLD_INVALID")
    if len(tags) != len(triangles):
        raise ValueError("BARRIER_TAG_COUNT_INVALID")
    if any(not all(math.isfinite(float(v)) for v in p) for p in points):
        raise ValueError("BARRIER_COORDINATE_NONFINITE")
    if points.shape[1] > 2 and any(float(p[2]) != float(points[0][2]) for p in points):
        raise ValueError("BARRIER_NOT_PLANAR")
    a = 0 if axis == "x" else 1
    xy = [(F(float(p[a])), F(float(p[1-a]))) for p in points]
    edges = {doped_tag: Counter(), barrier_tag: Counter()}
    for tri, tag in zip(triangles, tags):
        tag = int(tag)
        if tag not in edges:
            continue
        i, j, k = map(int, tri)
        p, q, r = xy[i], xy[j], xy[k]
        if (q[0]-p[0])*(r[1]-p[1]) == (r[0]-p[0])*(q[1]-p[1]):
            raise ValueError("BARRIER_TRIANGLE_DEGENERATE")
        for u, v in ((i,j), (j,k), (k,i)):
            edges[tag][tuple(sorted((u,v)))] += 1
    boundary = {}
    for tag, counts in edges.items():
        if any(n > 2 for n in counts.values()):
            raise ValueError("BARRIER_NONMANIFOLD")
        boundary[tag] = [(xy[u], xy[v]) for (u,v), n in counts.items() if n == 1]
    if not boundary[doped_tag] or not boundary[barrier_tag]:
        return []
    breaks = sorted({p[0] for es in boundary.values() for edge in es for p in edge})
    threshold = F(float(min_thickness))
    adjacency = F(1e-6)  # Existing exported-interface adjacency convention, not stopping power.

    def line(p, q):
        slope = (q[1]-p[1])/(q[0]-p[0])
        return slope, p[1]-slope*p[0]

    def value(l, x):
        return l[0]*x+l[1]

    def sections(tag, lo, hi):
        mid = (lo+hi)/2
        lines = [line(p,q) for p,q in boundary[tag]
                 if min(p[0],q[0]) < mid < max(p[0],q[0])]
        lines.sort(key=lambda l: value(l, mid))
        if len(lines) % 2:
            raise ValueError("BARRIER_BOUNDARY_OPEN")
        # A proper noncrossing boundary keeps its order within each slab.
        # Do not silently extrapolate a midpoint ordering across crossings.
        for x in (lo, hi):
            if any(value(u,x) > value(v,x) for u,v in zip(lines,lines[1:])):
                raise ValueError("BARRIER_SECTION_ORDER_UNRESOLVED")
        return list(zip(lines[::2],lines[1::2]))

    def clip(lo, hi, inequalities):
        # Each inequality is m*x+b >= 0. Roots are computed, not sampled.
        for m,b in inequalities:
            if m == 0:
                if b < 0:
                    return None
            elif m > 0:
                lo = max(lo, -b/m)
            else:
                hi = min(hi, -b/m)
            if hi <= lo:
                return None
        return lo, hi

    answer = []
    for lo,hi in zip(breaks,breaks[1:]):
        si = sections(doped_tag, lo, hi)
        if not si:
            continue
        si_top = si[-1][1]
        for bottom,top in sections(barrier_tag, lo, hi):
            gap = (bottom[0]-si_top[0], bottom[1]-si_top[1])
            thick = (top[0]-bottom[0], top[1]-bottom[1]-threshold)
            interval = clip(lo,hi,[gap,(-gap[0],adjacency-gap[1]),thick])
            if interval:
                answer.append(interval)
    merged = []
    for lo,hi in sorted(answer):
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(hi,merged[-1][1]))
        else:
            merged.append((lo,hi))
    return [{"min_um":float(lo),"max_um":float(hi)} for lo,hi in merged]
