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
