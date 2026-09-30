#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Local triangle mesh refinement near a doping junction.

Motivation (found this session, real-execution-verified, not guessed):
ViennaPS's level-set-derived volume mesh is uniform (one grid_delta_um
everywhere). DEVSIM's own official diode example
(devsim/examples/diode/diode_common.py, read from source on GitHub)
instead grades its mesh down to sub-nm/few-nm spacing right at the
doping junction. Isolated testing (same mesh, same domain, same solver
tolerances, only doping varied) showed the project's Phase 8 PN-junction
drift-diffusion sweep converges cleanly when the Debye length at the
doping level used is comparable to or larger than the mesh spacing
(donor=acceptor=1e16 or 1e14 cm^-3, grid_delta_um=0.15), and stalls with
a persistent Newton residual oscillation at the project's real doping
(1e18 cm^-3, Debye length ~4nm vs. a 150nm mesh -- ~37x too coarse) --
this module is the fix: refine triangles near the junction instead of
changing doping (which CLAUDE.md's own rules forbid doing just to dodge
a numerical issue) or refining the WHOLE mesh uniformly (verified
separately to be both far more expensive -- 50k+ nodes, minutes per
solve -- and not even reliably better, since ViennaPS's own triangle
quality at a given grid_delta_um is not a monotonic function of
grid_delta_um, an issue already documented elsewhere in this project
under "MakeTrench floating-point sensitivity").

Algorithm: standard "red-green" (regular/conforming) triangle
refinement, applied only to triangles whose centroid falls within a
window around the target position:
  - A triangle inside the window is marked "red": split into 4
    sub-triangles by adding a new node at each edge midpoint.
  - A triangle outside the window but sharing an edge with a red
    triangle is marked "green": split into 2 sub-triangles by
    connecting the shared edge's (already-created) midpoint to the
    opposite vertex -- this is what keeps the mesh conforming (no
    hanging nodes / T-junctions at the red/unrefined boundary).
  - A triangle that would need "green" splitting on 2 or more edges is
    promoted to "red" instead (closure, iterated to a fixed point) --
    the classic red-green rule; splitting on 2 edges without a full red
    split produces degenerate slivers.
  - Triangles untouched by any of the above keep their original vertex
    indices unchanged, so the coarse mesh far from the window is
    bit-for-bit identical to the unrefined input.

refine_mesh_near() applies one such pass; calling it `levels` times
halves the local edge length near the window each time (level=3 ->
8x finer locally), matching how much finer the mesh needs to be for
the project's own doping levels (see the module docstring above).
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Tuple

import numpy as np


def _edge_key(a: int, b: int) -> Tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _refine_once(
    points: np.ndarray,
    triangles: np.ndarray,
    tags: np.ndarray,
    marked: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One closed red-green refinement pass. `marked` is a bool array,
    one entry per triangle, giving the initial red-refinement seed
    (closure may promote additional triangles to red)."""
    n_tri = len(triangles)

    edge_owners: Dict[Tuple[int, int], List[int]] = {}
    for ti in range(n_tri):
        v0, v1, v2 = (int(x) for x in triangles[ti])
        for a, b in ((v0, v1), (v1, v2), (v2, v0)):
            edge_owners.setdefault(_edge_key(a, b), []).append(ti)

    red = marked.copy()

    # Closure: promote any unmarked triangle with >=2 edges bordering a
    # red triangle to red too, repeat until stable.
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

    def midpoint(a: int, b: int) -> int:
        key = _edge_key(a, b)
        if key not in midpoint_cache:
            new_points.append((points[a] + points[b]) / 2.0)
            midpoint_cache[key] = len(new_points) - 1
        return midpoint_cache[key]

    new_triangles: List[Tuple[int, int, int]] = []
    new_tags: List[int] = []

    for ti in range(n_tri):
        v0, v1, v2 = (int(x) for x in triangles[ti])
        tag = int(tags[ti])

        if red[ti]:
            m01 = midpoint(v0, v1)
            m12 = midpoint(v1, v2)
            m20 = midpoint(v2, v0)
            new_triangles += [
                (v0, m01, m20),
                (v1, m12, m01),
                (v2, m20, m12),
                (m01, m12, m20),
            ]
            new_tags += [tag, tag, tag, tag]
            continue

        broken_edges = []  # (apex_vertex, edge_v0, edge_v1)
        for apex, ea, eb in ((v2, v0, v1), (v0, v1, v2), (v1, v2, v0)):
            owners = edge_owners[_edge_key(ea, eb)]
            if any(red[o] for o in owners if o != ti):
                broken_edges.append((apex, ea, eb))

        if not broken_edges:
            new_triangles.append((v0, v1, v2))
            new_tags.append(tag)
        elif len(broken_edges) == 1:
            apex, ea, eb = broken_edges[0]
            m = midpoint(ea, eb)
            new_triangles += [(apex, ea, m), (apex, m, eb)]
            new_tags += [tag, tag]
        else:
            raise AssertionError(
                f"triangle {ti} has {len(broken_edges)} broken edges after "
                "closure -- red-green closure invariant violated"
            )

    return (
        np.array(new_points, dtype=points.dtype),
        np.array(new_triangles, dtype=triangles.dtype),
        np.array(new_tags, dtype=tags.dtype),
    )


def refine_mesh_near(
    points: np.ndarray,
    triangles: np.ndarray,
    tags: np.ndarray,
    predicate: Callable[[np.ndarray], bool],
    levels: int = 3,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Apply `levels` closed red-green refinement passes to triangles
    whose centroid satisfies `predicate(centroid)`.

    Each pass only refines triangles CURRENTLY matching the predicate
    (evaluated against that pass's triangle set, so already-refined
    triangles from a prior pass are re-evaluated at their new, smaller
    size) -- this is what makes repeated calls progressively finer
    inside the window rather than just re-splitting the same triangles
    without shrinking them further.

    Triangles whose centroid never satisfies `predicate`, and are never
    adjacent to one that does, are returned with their original vertex
    indices unchanged (their entries in `points` are untouched) --
    refinement is purely local, the rest of the mesh is bit-for-bit
    the input.
    """
    for _ in range(levels):
        centroids = points[triangles].mean(axis=1)
        marked = np.array([predicate(c) for c in centroids], dtype=bool)
        if not marked.any():
            break
        points, triangles, tags = _refine_once(points, triangles, tags, marked)
    return points, triangles, tags


def graded_refine_mesh_near(
    points: np.ndarray,
    triangles: np.ndarray,
    tags: np.ndarray,
    predicates: List[Callable[[np.ndarray], bool]],
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Telescoping/graded alternative to calling refine_mesh_near() once
    with one wide window and many levels: apply ONE refine_mesh_near()
    pass (levels=1) per predicate in `predicates`, in order — normally
    a sequence of windows from widest (matching the mesh's own existing
    spacing) to narrowest (reaching the real target resolution).

    Because each successively narrower window is a SUBSET of the wider
    ones before it, only the innermost region ends up refined by every
    pass (the full cumulative depth), while the outer rings get
    progressively fewer halvings — unlike refine_mesh_near() with a
    single wide window and N levels, where the ENTIRE window gets N
    halvings regardless of how close to the target position it is.

    Found necessary by real execution (not assumed): a single-window
    approach that reaches deep sub-Debye-length resolution at real
    device doping levels (1e19-1e20 cm^-3) needs enough levels that the
    WHOLE window's node count grows by close to 4^levels — confirmed
    directly to reach ~588k equations for one doping level before this
    function was written, and to still fail to converge in reasonable
    time even after capping levels. The graded version reaches the
    SAME final local resolution with far fewer total nodes (see
    CLAUDE.md — 16025 vs 51239 Si nodes at 1e19 cm^-3, and reaches
    1e20 cm^-3 at all, which the single-window approach did not,
    within a comparable node budget).
    """
    for predicate in predicates:
        points, triangles, tags = refine_mesh_near(points, triangles, tags, predicate, levels=1)
    return points, triangles, tags


# ---------------------------------------------------------------------------
# Structured-grid lateral refinement with non-obtuse transition templates
# (Batch 7H-E6G). The red-green passes above create obtuse children on the
# right-triangle grids ViennaPS writes, and DEVSIM's NodeVolume over-counts
# obtuse triangles, so the area gate refuses those meshes. For the one case
# below -- a single-material, axis-aligned structured grid refined in bands
# along x -- the mesh is instead rebuilt from its own grid lines: each column
# is split by a 1D binary tree into strips one sub-cell wide, a strip of
# depth d has 2^d sub-rows per row, neighbouring strips differ by at most one
# level, and a coarser strip next to a finer one uses a transition template
# (midpoint of the shared edge; non-obtuse iff the sub-cell's width >= half
# its height, checked exactly). Every original node keeps its index and
# coordinates; new nodes are appended.
# Criteria: docs/audits/2026-10-01-batch7h-e6g-structured-template/CRITERIA.md
# ---------------------------------------------------------------------------

STRUCTURED_TRIANGLE_CAP = 400000


class StructuredRemeshUnsupported(ValueError):
    """The input is outside the structured builder's supported scope (`reason` says which condition failed).
    The caller keeps its existing refinement path."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


class StructuredRemeshAborted(RuntimeError):
    """The input is supported but the construction cannot be completed without breaking a contract
    (transition aspect condition, resource cap). Never replaced by another refinement."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def structured_grid_of(points: np.ndarray, triangles: np.ndarray, tags: np.ndarray):
    """Prove that (points, triangles, tags) is a single-material, axis-aligned structured grid: the node set is the full tensor
    product of its distinct x and y values, and every grid cell is covered by exactly its two halves (two triangles on 3 of its 4
    corners whose missing corners are opposite). Returns (xs, ys, cell_triangles, orientation) or raises StructuredRemeshUnsupported."""
    P = np.asarray(points, dtype=np.float64)
    T = np.asarray(triangles, dtype=np.int64)
    G = np.asarray(tags).reshape(-1)
    if P.ndim != 2 or P.shape[1] < 2 or len(T) == 0:
        raise StructuredRemeshUnsupported("NOT_A_TRIANGLE_MESH")
    if P.shape[1] > 2 and np.any(P[:, 2:] != 0):
        raise StructuredRemeshUnsupported("NOT_PLANAR")
    if len(np.unique(G)) != 1:
        raise StructuredRemeshUnsupported("MULTI_MATERIAL", f"{len(np.unique(G))} material tags")
    xs, ys = np.unique(P[:, 0]), np.unique(P[:, 1])
    nx, ny = len(xs) - 1, len(ys) - 1
    if nx < 1 or ny < 1 or len(np.unique(P[:, :2], axis=0)) != len(P) or len(P) != (nx + 1) * (ny + 1):
        raise StructuredRemeshUnsupported("NOT_TENSOR_PRODUCT_NODES", f"{len(P)} nodes vs {len(xs)} x {len(ys)} lines")
    if len(T) != 2 * nx * ny:
        raise StructuredRemeshUnsupported("NOT_TWO_TRIANGLES_PER_CELL", f"{len(T)} triangles for {nx} x {ny} cells")
    ix = np.searchsorted(xs, P[:, 0])
    iy = np.searchsorted(ys, P[:, 1])
    cells: Dict[Tuple[int, int], List[int]] = {}
    for t_index, t in enumerate(T.tolist()):
        I, J = ix[t], iy[t]
        if I.max() - I.min() != 1 or J.max() - J.min() != 1:
            raise StructuredRemeshUnsupported("TRIANGLE_NOT_HALF_OF_ONE_CELL", f"triangle {t_index}")
        cells.setdefault((int(I.min()), int(J.min())), []).append(t_index)
    corner = lambda i, j: (i, j)  # noqa: E731
    for (i, j), members in cells.items():
        if len(members) != 2:
            raise StructuredRemeshUnsupported("CELL_NOT_COVERED_BY_TWO_HALVES", f"cell ({i}, {j}) has {len(members)} triangles")
        four = {corner(i, j), corner(i + 1, j), corner(i + 1, j + 1), corner(i, j + 1)}
        missing = []
        for m in members:
            have = {(int(ix[v]), int(iy[v])) for v in T[m]}
            if len(have) != 3:
                raise StructuredRemeshUnsupported("TRIANGLE_NOT_HALF_OF_ONE_CELL", f"triangle {m}")
            missing.append((four - have).pop())
        (a0, b0), (a1, b1) = missing
        if a0 == a1 or b0 == b1:   # missing corners must be diagonally opposite, otherwise the halves overlap
            raise StructuredRemeshUnsupported("CELL_HALVES_OVERLAP", f"cell ({i}, {j})")
    if len(cells) != nx * ny:
        raise StructuredRemeshUnsupported("CELL_NOT_COVERED_BY_TWO_HALVES", f"{len(cells)} of {nx * ny} cells covered")
    a, b, c = P[T[:, 0], :2], P[T[:, 1], :2], P[T[:, 2], :2]
    o = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
    if not (np.all(o > 0) or np.all(o < 0)):
        raise StructuredRemeshUnsupported("MIXED_ORIENTATION")
    return xs, ys, cells, (1 if o[0] > 0 else -1)


def _validated_request(centers, half_widths):
    """Finite, non-empty centres and strictly positive finite half widths, else StructuredRemeshAborted('INVALID_REQUEST').
    (Batch 7H-E6H: NaN comparisons used to make an invalid request look like 'nothing to refine'.)"""
    try:
        c = [float(v) for v in centers]
        h = [float(v) for v in half_widths]
    except (TypeError, ValueError) as exc:
        raise StructuredRemeshAborted("INVALID_REQUEST", f"non-numeric centre or half width: {exc}") from exc
    if not c or not h:
        raise StructuredRemeshAborted("INVALID_REQUEST", "empty centre or half-width list")
    if not all(math.isfinite(v) for v in c + h):
        raise StructuredRemeshAborted("INVALID_REQUEST", "non-finite centre or half width")
    if any(v <= 0.0 for v in h):
        raise StructuredRemeshAborted("INVALID_REQUEST", "half widths must be > 0")
    return c, h


def _strip_depths(xs: np.ndarray, centers: List[float], half_widths: List[float], cap: int = STRUCTURED_TRIANGLE_CAP):
    """1D binary-tree strips: split an interval while a band {|x - c| < hw_k} it intersects requires depth >= k + 1, then 2:1
    balance neighbours. Returns [(a, b, depth, column)] left to right. Budget (Batch 7H-E6H): a strip at depth d needs at least
    2^(d+1) triangles and every leaf at least 2, so the build aborts with RESOURCE_CAP as soon as either lower bound exceeds `cap`,
    and with SUBDIVISION_EXHAUSTED when a midpoint is not strictly inside its interval (no new float64 coordinate can be made)."""
    def required(a, b):
        need = 0
        for k, hw in enumerate(half_widths):
            if any(a < c + hw and b > c - hw for c in centers):
                need = max(need, k + 1)
        return need

    def split(a, b, d):
        if (1 << (d + 2)) > cap:
            raise StructuredRemeshAborted("RESOURCE_CAP", f"a strip at depth {d + 1} alone needs more than {cap} triangles")
        m = (a + b) / 2.0
        if not a < m < b:
            raise StructuredRemeshAborted("SUBDIVISION_EXHAUSTED", f"interval [{a!r}, {b!r}] cannot be split at depth {d + 1}")
        return m

    def budget(n_leaves):
        if 2 * n_leaves > cap:
            raise StructuredRemeshAborted("RESOURCE_CAP", f"{n_leaves} strips need more than {cap} triangles")

    leaves = []
    for i in range(len(xs) - 1):
        stack = [(float(xs[i]), float(xs[i + 1]), 0)]
        out = []
        while stack:
            a, b, d = stack.pop()
            if d < required(a, b):
                m = split(a, b, d)
                stack += [(m, b, d + 1), (a, m, d + 1)]
            else:
                out.append((a, b, d, i))
            budget(len(leaves) + len(out) + len(stack))
        leaves += sorted(out)
    changed = True
    while changed:
        changed = False
        for k in range(len(leaves) - 1):
            (a0, b0, d0, i0), (a1, b1, d1, i1) = leaves[k], leaves[k + 1]
            if abs(d0 - d1) > 1:
                j = k if d0 < d1 else k + 1
                a, b, d, i = leaves[j]
                m = split(a, b, d)
                leaves[j:j + 1] = [(a, m, d + 1, i), (m, b, d + 1, i)]
                budget(len(leaves))
                changed = True
                break
    return leaves


def structured_lateral_refine(points, triangles, tags, centers: List[float], half_widths: List[float],
                              cap: int = STRUCTURED_TRIANGLE_CAP):
    """Rebuild a supported structured grid so that every point within half_widths[k] of any center (x axis) lies in cells refined
    k + 1 times in both directions, with non-obtuse transition templates. Returns (points, triangles, tags, report). Raises
    StructuredRemeshUnsupported (input outside scope) or StructuredRemeshAborted (aspect condition or cap)."""
    from fractions import Fraction
    P0 = np.asarray(points, dtype=np.float64)
    T0 = np.asarray(triangles, dtype=np.int64)
    G0 = np.asarray(tags).reshape(-1)
    centers, half_widths = _validated_request(centers, half_widths)
    xs, ys, cells, orient = structured_grid_of(P0, T0, G0)
    leaves = _strip_depths(xs, centers, half_widths, cap)
    if all(d == 0 for _, _, d, _ in leaves):   # a valid request whose bands need no refinement in this domain
        return points, triangles, tags, {"identity": True, "leaves": len(leaves)}
    ny = len(ys) - 1
    ysub_cache: Dict[Tuple[int, int], List[float]] = {}

    def ysub(j: int, d: int) -> List[float]:
        key = (j, d)
        if key not in ysub_cache:
            if d == 0:
                ysub_cache[key] = [float(ys[j]), float(ys[j + 1])]
            else:
                prev = ysub(j, d - 1)
                out = []
                for u, v in zip(prev[:-1], prev[1:]):
                    m = (u + v) / 2.0
                    if not u < m < v:
                        raise StructuredRemeshAborted("SUBDIVISION_EXHAUSTED", f"row interval [{u!r}, {v!r}] cannot be split")
                    out += [u, m]
                ysub_cache[key] = out + [prev[-1]]
        return ysub_cache[key]

    depth_left = [leaves[k - 1][2] if k > 0 else None for k in range(len(leaves))]
    depth_right = [leaves[k + 1][2] if k + 1 < len(leaves) else None for k in range(len(leaves))]
    n_tri = 0
    for k, (a, b, d, i) in enumerate(leaves):   # planned count first: the cap is checked before any sub-row list or aspect loop
        fl = depth_left[k] == d + 1
        fr = depth_right[k] == d + 1
        n_tri += (4 if (fl and fr) else 3 if (fl or fr) else 2) * ny * (2 ** d)
    if n_tri > cap:
        raise StructuredRemeshAborted("RESOURCE_CAP", f"{n_tri} triangles would exceed the cap {cap}")
    min_margin = None
    for k, (a, b, d, i) in enumerate(leaves):
        fl = depth_left[k] == d + 1
        fr = depth_right[k] == d + 1
        if fl != fr:   # one-sided template: exact non-obtuse condition w >= h / 2 for every sub-cell of this strip
            w = Fraction(b) - Fraction(a)
            for j in range(ny):
                yy = ysub(j, d)
                for u, v in zip(yy[:-1], yy[1:]):
                    h = Fraction(v) - Fraction(u)
                    margin = w - h / 2
                    min_margin = margin if min_margin is None else min(min_margin, margin)
                    if margin < 0:
                        raise StructuredRemeshAborted("TRANSITION_ASPECT", f"strip [{a!r}, {b!r}] depth {d}: width {float(w)!r} < "
                                                      f"half sub-row height {float(h) / 2!r}")
    # nodes: every original node keeps its index; new nodes appended line by line, y ascending
    index: Dict[Tuple[float, float], int] = {(float(x), float(y)): n for n, (x, y) in enumerate(P0[:, :2].tolist())}
    new_pts: List[Tuple[float, float]] = []

    def node(x: float, y: float) -> int:
        key = (x, y)
        if key not in index:
            index[key] = len(P0) + len(new_pts)
            new_pts.append(key)
        return index[key]
    lines = [leaves[0][0]] + [b for _, b, _, _ in leaves]
    n_leaves = len(leaves)
    line_depth = [max(leaves[k][2] if k < n_leaves else -1, leaves[k - 1][2] if k > 0 else -1) for k in range(n_leaves + 1)]
    for x, d in zip(lines, line_depth):
        for j in range(ny):
            for y in ysub(j, d):
                node(x, y)
    tris: List[Tuple[int, int, int]] = []
    for k, (a, b, d, i) in enumerate(leaves):
        fl = depth_left[k] == d + 1
        fr = depth_right[k] == d + 1
        for j in range(ny):
            if d == 0 and not (fl or fr):
                tris += [tuple(int(v) for v in T0[m]) for m in sorted(cells[(i, j)])]   # untouched cell: original triangles
                continue
            yy = ysub(j, d)
            yf = ysub(j, d + 1) if (fl or fr) else None
            for s in range(len(yy) - 1):
                y0, y1 = yy[s], yy[s + 1]
                LL, LR, UR, UL = node(a, y0), node(b, y0), node(b, y1), node(a, y1)
                if fl and fr:
                    ML, MR = node(a, yf[2 * s + 1]), node(b, yf[2 * s + 1])
                    cell = [(LL, LR, MR), (LL, MR, ML), (ML, MR, UR), (ML, UR, UL)]
                elif fl:
                    M = node(a, yf[2 * s + 1])
                    cell = [(LL, LR, M), (M, LR, UR), (M, UR, UL)]
                elif fr:
                    M = node(b, yf[2 * s + 1])
                    cell = [(LL, LR, M), (LL, M, UL), (UL, M, UR)]
                else:
                    cell = [(LL, LR, UR), (LL, UR, UL)]
                tris += cell if orient > 0 else [(p, r, q) for p, q, r in cell]
    if len(tris) != n_tri:
        raise StructuredRemeshAborted("INTERNAL_COUNT_MISMATCH", f"{len(tris)} built vs {n_tri} planned")
    out_pts = np.zeros((len(P0) + len(new_pts), P0.shape[1]), dtype=np.float64)
    out_pts[:len(P0)] = P0
    if new_pts:
        out_pts[len(P0):, :2] = np.array(new_pts, dtype=np.float64)
    depths = [d for _, _, d, _ in leaves]
    report = {"identity": False, "leaves": len(leaves), "max_depth": max(depths),
              "leaves_by_depth": {str(d): depths.count(d) for d in sorted(set(depths))},
              "triangles": len(tris), "points": int(len(out_pts)), "new_points": len(new_pts),
              "min_template_margin": None if min_margin is None else float(min_margin)}
    return out_pts, np.array(tris, dtype=np.int64), np.full(len(tris), G0[0], dtype=G0.dtype), report
