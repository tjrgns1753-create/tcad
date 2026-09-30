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
  - A triangle that would need a green split on exactly one edge is
    ALSO promoted to red when either green child would be obtuse or
    degenerate (quality closure, Batch 7H-E6F). A green split of a right
    triangle along a LEG, for example, gives a 116.57-degree child, and
    DEVSIM's NodeVolume over-integrates obtuse triangles (7H-B / 7H-E6E-R1:
    +30 % region area on the implant-windows path). The test is exact
    (rational arithmetic on the float coordinates of the midpoint the
    split will actually create); a right angle is allowed. A red split of
    a non-obtuse parent is similar to it, so a non-obtuse input stays
    non-obtuse; an input that is already obtuse is NOT repaired. The
    quality closure can spread the refinement beyond the predicate's
    window (to keep conformity without obtuse children).
  - Triangles untouched by any of the above keep their original vertex
    indices unchanged, so the coarse mesh far from the window is
    bit-for-bit identical to the unrefined input.

refine_mesh_near() applies one such pass; calling it `levels` times
halves the local edge length near the window each time (level=3 ->
8x finer locally), matching how much finer the mesh needs to be for
the project's own doping levels (see the module docstring above).
"""

from __future__ import annotations

from fractions import Fraction
from typing import Callable, Dict, List, Tuple

import numpy as np


def _edge_key(a: int, b: int) -> Tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _non_obtuse_exact(p0, p1, p2) -> bool:
    """True iff the triangle (2D points given as float pairs) has nonzero
    area and no obtuse angle, decided exactly with rational arithmetic
    on the float values (a right angle counts as non-obtuse)."""
    q = [(Fraction(float(p[0])), Fraction(float(p[1]))) for p in (p0, p1, p2)]
    (ax, ay), (bx, by), (cx, cy) = q
    if (bx - ax) * (cy - ay) - (by - ay) * (cx - ax) == 0:
        return False
    for (ox, oy), (ux, uy), (vx, vy) in ((q[0], q[1], q[2]), (q[1], q[2], q[0]), (q[2], q[0], q[1])):
        if (ux - ox) * (vx - ox) + (uy - oy) * (vy - oy) < 0:
            return False
    return True


def _refine_once(
    points: np.ndarray,
    triangles: np.ndarray,
    tags: np.ndarray,
    marked: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One closed red-green refinement pass. `marked` is a bool array,
    one entry per triangle, giving the initial red-refinement seed
    (closure may promote additional triangles to red).

    Coordinates are carried in float64 (values of a float32 input are
    unchanged): a float32 midpoint is rounded, which bends the right
    angles of red children by ~1e-5 degree into obtuse ones (measured on
    the implant-windows path, Batch 7H-E6F), while the float64 sum of two
    float32 values is exact, so the float64 midpoint is the true midpoint."""
    points = np.asarray(points, dtype=np.float64)
    n_tri = len(triangles)
    green_ok_cache: Dict[Tuple[int, int, int], bool] = {}

    def green_children_ok(apex: int, ea: int, eb: int) -> bool:
        # The midpoint exactly as midpoint() below will create it (same
        # expression, same dtype), so what is tested is what is built.
        key = (apex,) + _edge_key(ea, eb)
        if key not in green_ok_cache:
            m = np.array([(points[ea] + points[eb]) / 2.0], dtype=points.dtype)[0]
            pa, pe0, pe1 = points[apex][:2], points[ea][:2], points[eb][:2]
            green_ok_cache[key] = _non_obtuse_exact(pa, pe0, m[:2]) and _non_obtuse_exact(pa, m[:2], pe1)
        return green_ok_cache[key]

    edge_owners: Dict[Tuple[int, int], List[int]] = {}
    for ti in range(n_tri):
        v0, v1, v2 = (int(x) for x in triangles[ti])
        for a, b in ((v0, v1), (v1, v2), (v2, v0)):
            edge_owners.setdefault(_edge_key(a, b), []).append(ti)

    red = marked.copy()

    # Closure: promote any unmarked triangle with >=2 edges bordering a
    # red triangle to red too, and any with exactly one such edge whose
    # green children would be obtuse or degenerate; repeat until stable.
    changed = True
    while changed:
        changed = False
        for ti in range(n_tri):
            if red[ti]:
                continue
            v0, v1, v2 = (int(x) for x in triangles[ti])
            broken = []
            for apex, a, b in ((v2, v0, v1), (v0, v1, v2), (v1, v2, v0)):
                owners = edge_owners[_edge_key(a, b)]
                if any(red[o] for o in owners if o != ti):
                    broken.append((apex, a, b))
            if len(broken) >= 2 or (len(broken) == 1 and not green_children_ok(*broken[0])):
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
