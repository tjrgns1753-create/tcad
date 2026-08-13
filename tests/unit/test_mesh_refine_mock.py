#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit verification of tcad.device.devsim.mesh_refine's local red-green
triangle refinement, on a synthetic structured grid (no ViennaPS/DevSim
needed -- pure geometry algorithm). Checks the invariants the algorithm
must hold to be safe to use as a mesh_import.py preprocessing step:

  1. Conformity: every edge is shared by at most 2 triangles (no
     hanging nodes / T-junctions) after refinement.
  2. Area preservation: refinement must not lose or duplicate geometry.
  3. Locality: triangles far from the refinement window keep their
     ORIGINAL vertex indices unchanged.
  4. Local edge length actually shrinks by ~2x per level inside the
     window (confirms refinement is doing real work, not a no-op).

See tcad/device/devsim/mesh_refine.py's own module docstring for why
this exists: DEVSIM's official diode example grades its mesh down to
sub-nm spacing at the doping junction; this project's ViennaPS-derived
mesh is uniform, which real execution showed makes Phase 8's
1e18 cm^-3 PN-junction drift-diffusion sweep stall (see
tests/integration/test_phase8_pn_junction_real.py, which uses this
module's refine_near_um to fix it).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np

from tcad.device.devsim.mesh_refine import _edge_key, refine_mesh_near


def make_grid(nx, ny, dx=1.0, dy=1.0):
    """Uniform structured triangulation of an nx*dx by ny*dy rectangle."""
    xs = np.arange(nx + 1) * dx
    ys = np.arange(ny + 1) * dy
    points = []
    index = {}
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            index[(i, j)] = len(points)
            points.append([x, y, 0.0])
    points = np.array(points, dtype=float)

    triangles = []
    tags = []
    for j in range(ny):
        for i in range(nx):
            a = index[(i, j)]
            b = index[(i + 1, j)]
            c = index[(i + 1, j + 1)]
            d = index[(i, j + 1)]
            triangles.append((a, b, c))
            triangles.append((a, c, d))
            tags.append(1)
            tags.append(1)
    return points, np.array(triangles, dtype=int), np.array(tags, dtype=int)


def total_area(points, triangles):
    p = points[triangles]
    v0 = p[:, 1, :2] - p[:, 0, :2]
    v1 = p[:, 2, :2] - p[:, 0, :2]
    cross = v0[:, 0] * v1[:, 1] - v0[:, 1] * v1[:, 0]
    return np.abs(cross).sum() / 2.0


def max_edge_multiplicity(triangles):
    edge_owners = {}
    for tri in triangles:
        v0, v1, v2 = (int(x) for x in tri)
        for a, b in ((v0, v1), (v1, v2), (v2, v0)):
            edge_owners[_edge_key(a, b)] = edge_owners.get(_edge_key(a, b), 0) + 1
    return max(edge_owners.values())


def min_edge_length(points, triangles):
    p = points[triangles]
    lens = []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        d = p[:, i, :2] - p[:, j, :2]
        lens.append(np.sqrt((d ** 2).sum(axis=1)))
    return np.concatenate(lens).min()


def main():
    points, triangles, tags = make_grid(10, 10, dx=1.0, dy=1.0)
    area0 = total_area(points, triangles)
    assert max_edge_multiplicity(triangles) == 2, "sanity: input grid must itself be conforming"

    def predicate(centroid):
        return abs(centroid[0] - 5.0) < 1.0  # window around x=5, away from any domain boundary

    far_before = {
        tuple(int(v) for v in tri)
        for tri in triangles
        if abs(points[list(tri)].mean(axis=0)[0] - 5.0) > 3.0  # well outside window + 1 green ring
    }
    assert far_before, "sanity: test grid must have triangles outside the refinement window"

    for levels in (1, 2, 3):
        pts2, tri2, tag2 = refine_mesh_near(points, triangles, tags, predicate, levels=levels)
        area2 = total_area(pts2, tri2)
        max_mult = max_edge_multiplicity(tri2)
        min_edge2 = min_edge_length(pts2, tri2)
        far_after = {tuple(int(v) for v in tri) for tri in tri2}

        assert abs(area2 - area0) < 1e-9, f"levels={levels}: area not preserved ({area2} vs {area0})"
        assert max_mult <= 2, f"levels={levels}: non-conforming mesh (an edge shared by {max_mult} triangles)"
        assert far_before.issubset(far_after), f"levels={levels}: far-field triangles were modified"
        assert len(tag2) == len(tri2), f"levels={levels}: tags/triangles length mismatch"
        assert set(tag2.tolist()) == {1}, f"levels={levels}: material tag not preserved through refinement"
        expected_min_edge = 1.0 / (2 ** levels)
        assert min_edge2 <= expected_min_edge + 1e-9, (
            f"levels={levels}: expected local edge length <= {expected_min_edge}, got {min_edge2}"
        )
        print(
            f"levels={levels}: {len(tri2)} triangles, area={area2:.6f} "
            f"(delta={area2 - area0:.2e}), max_edge_multiplicity={max_mult}, "
            f"min_edge={min_edge2:.4f}, far-field preserved=True"
        )

    # No triangle in the window at all -> no-op, output identical to input.
    pts3, tri3, tag3 = refine_mesh_near(points, triangles, tags, lambda c: False, levels=3)
    assert np.array_equal(pts3, points) and np.array_equal(tri3, triangles) and np.array_equal(tag3, tags), (
        "a predicate matching nothing must leave the mesh completely unchanged"
    )
    print("empty predicate -> no-op: OK")

    print("ALL MESH_REFINE MOCK CHECKS PASSED")


if __name__ == "__main__":
    main()
