#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Directional deposition growth verification, real ViennaPS 4.6.2.

Regression test for a real sign-convention bug found while reviewing
the "directional deposition benchmark" open issue: deposition/directional.py
passed recipe["directional_velocity"] straight through to ViennaPS's
DirectionalProcess(directionalVelocity=...), but ViennaPS's own sign
convention there is inverted relative to this project's documented
recipe convention (positive = grow) -- confirmed by sweeping
direction/velocity sign combinations through the real production path
with a floored/exported volume mesh: direction=[0,1,0],
directional_velocity=+0.1 measured as -0.2um REMOVED after 2s (it
etched), not grown. Fixed by negating directional_velocity before the
ViennaPS call. This test locks that fix in with the same rigor already
used for the Etching counterpart (CLAUDE.md: "etch depth in the opening
matched |v|xt within ~0%").

Measurement uses the real, floored save_volume_mesh() export (never the
raw in-memory level set) -- the raw level set's "bottom" edge is an
arbitrary narrow-band artifact for a semi-infinite region (see
CLAUDE.md's original Si-thickness investigation), not a real boundary,
which is what caused the sign bug to look ambiguous before this was
root-caused.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio

import tcad.process.deposition  # noqa: F401 -- registers deposition models
from tcad.backends.viennaps import session as viennaps_session
from tcad.backends.viennaps.io import save_volume_mesh
from tcad.process import registry

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"

BASE_RECIPE = {
    "grid_delta_um": 0.2,
    "x_extent_um": 4.0,
    "y_extent_um": 3.0,
    "mask_left_um": 1.5,
    "mask_right_um": 2.5,
    "pr_thickness_um": 0.5,
    "mask_material": "Mask",
    "direction": [0.0, 1.0, 0.0],
}


def _si_top_in_open_window(mesh_path, tag_name_fn, window=(-0.3, 0.3)):
    """Max Si y-coordinate within the open (unmasked) window, read from
    the real exported (floored) volume mesh -- never the raw level set,
    whose "bottom" is an arbitrary narrow-band artifact for a
    semi-infinite region, not a physical boundary."""
    mesh = meshio.read(mesh_path)
    triangle_block = next((c for c in mesh.cells if c.type == "triangle"), None)
    assert triangle_block is not None, f"no triangle cells in {mesh_path}"
    block_index = mesh.cells.index(triangle_block)
    tags = mesh.cell_data["Material"][block_index]
    points = mesh.points

    top = None
    for tri, tag in zip(triangle_block.data, tags):
        if tag_name_fn(int(tag)) != "Si":
            continue
        for node_idx in tri:
            x, y = points[node_idx][0], points[node_idx][1]
            if window[0] <= x <= window[1]:
                top = y if top is None else max(top, y)
    assert top is not None, "no Si found in the open window"
    return top


def main():
    module = viennaps_session.require_viennaps()

    def tag_name(tag):
        return str(module.Material(tag)).split("'")[1]

    step_cls = registry.get("deposition", "directional")

    with tempfile.TemporaryDirectory() as tmp:
        baseline_geom = step_cls().prepare_domain(BASE_RECIPE)
        baseline_path = save_volume_mesh(baseline_geom, Path(tmp) / "baseline")
        baseline_top = _si_top_in_open_window(baseline_path, tag_name)
        print(f"[1/3] baseline Si top (open window) = {baseline_top}")
        assert abs(baseline_top) < 1e-6, "baseline Si surface should be at y=0"

        max_rel_error = 0.0
        for t in (0.5, 1.0, 2.0, 4.0):
            recipe = {**BASE_RECIPE, "directional_velocity": 0.1, "deposition_time_s": t}
            with tempfile.TemporaryDirectory() as run_tmp:
                result = step_cls().run(recipe, run_tmp)
                top = _si_top_in_open_window(result["final_mesh"], tag_name)
            grown = top - baseline_top
            expected = 0.1 * t
            rel_error = abs(grown - expected) / expected
            max_rel_error = max(max_rel_error, rel_error)
            print(f"[2/3] t={t}s: grown={grown:.6f}um expected={expected:.6f}um "
                  f"rel_error={rel_error:.3e}")
            assert grown > 0, (
                f"t={t}s: directional_velocity=+0.1 must GROW material (positive delta), "
                f"got {grown} -- the sign-convention fix regressed"
            )

        print(f"[3/3] max relative error vs |v|*t across all time points: {max_rel_error:.3e}")
        assert max_rel_error < 0.01, f"growth doesn't match |v|*t closely enough: {max_rel_error}"

        print()
        print("DIRECTIONAL DEPOSITION GROWS material +|v|*t as documented "
              "(sign-convention fix verified) AGAINST REAL VIENNAPS 4.6.2")


if __name__ == "__main__":
    main()
