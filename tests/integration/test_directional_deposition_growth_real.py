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

Also verifies the real growth SHAPE (later session), not just
top-surface magnitude at one grid resolution:

  1. calculateVisibility default fix: ViennaPS's own default
     (calculateVisibility=True) was found, by real execution, to STALL
     growth at a small, grid- and time-dependent, NON-MONOTONIC
     fraction of the expected |v|*t for this project's flat-window/
     non-tilted-source geometry (up to 8x under-growth at some
     grid_delta_um values, while others matched exactly -- see
     deposition/directional.py's module docstring for the full sweep).
     deposition/directional.py now defaults calculateVisibility=False
     (still overridable per-recipe). This test sweeps grid_delta_um to
     lock that fix in, not just the single resolution the original
     sign-convention test used.
  2. No lateral spread: a purely directional recipe
     (isotropic_velocity unset) must not grow material sideways past
     the exposed window's own x-extent -- the real physical signature
     distinguishing directional (line-of-sight) from isotropic
     (conformal) deposition, mirrored from the same check already
     applied to the Etching counterpart (CLAUDE.md: "no lateral etch
     (expected -- no isotropic component set)").
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


def _si_cap_x_extent(mesh_path, tag_name_fn, y_threshold=0.01):
    """(x_min, x_max) of Si material ABOVE y_threshold -- isolates the
    grown cap from the floored semi-infinite substrate below it (which
    spans the whole domain width at y<0 regardless of growth)."""
    mesh = meshio.read(mesh_path)
    triangle_block = next((c for c in mesh.cells if c.type == "triangle"), None)
    block_index = mesh.cells.index(triangle_block)
    tags = mesh.cell_data["Material"][block_index]
    points = mesh.points

    xmin, xmax = None, None
    for tri, tag in zip(triangle_block.data, tags):
        if tag_name_fn(int(tag)) != "Si":
            continue
        for node_idx in tri:
            x, y = points[node_idx][0], points[node_idx][1]
            if y > y_threshold:
                xmin = x if xmin is None else min(xmin, x)
                xmax = x if xmax is None else max(xmax, x)
    return xmin, xmax


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

        # calculateVisibility=False default: sweep grid_delta_um at a
        # fixed, long-enough time (t=4s, several grid cells worth of
        # growth at every resolution tested, avoiding short-time
        # quantization noise) to confirm the default fix isn't specific
        # to BASE_RECIPE's own single grid_delta_um=0.2.
        print("[4/6] grid_delta_um sweep (calculateVisibility default fix):")
        t = 4.0
        max_grid_rel_error = 0.0
        for grid_delta_um in (0.2, 0.15, 0.1, 0.05, 0.02):
            recipe = {**BASE_RECIPE, "grid_delta_um": grid_delta_um,
                      "directional_velocity": 0.1, "deposition_time_s": t}
            with tempfile.TemporaryDirectory() as run_tmp:
                grid_baseline_geom = step_cls().prepare_domain(dict(recipe))
                grid_baseline_path = save_volume_mesh(grid_baseline_geom, Path(run_tmp) / "gbase")
                grid_baseline_top = _si_top_in_open_window(grid_baseline_path, tag_name)

                result = step_cls().run(recipe, run_tmp)
                top = _si_top_in_open_window(result["final_mesh"], tag_name)
            grown = top - grid_baseline_top
            expected = 0.1 * t
            rel_error = abs(grown - expected) / expected
            max_grid_rel_error = max(max_grid_rel_error, rel_error)
            print(f"      grid_delta_um={grid_delta_um}: grown={grown:.6f}um "
                  f"expected={expected:.6f}um rel_error={rel_error:.3e}")

        print(f"[5/6] max relative error across grid sweep: {max_grid_rel_error:.3e}")
        # A generous bound (not the 1% used for the fine t-sweep above):
        # ViennaPS's own triangle quality is not a monotonic function of
        # grid_delta_um (already documented under "MakeTrench
        # floating-point sensitivity" in CLAUDE.md), so a single
        # resolution can show real, non-bug-related noise larger than
        # 1% -- what this bound guards against is a regression back to
        # calculateVisibility=True's up-to-8x stalling, not sub-percent
        # mesh noise.
        assert max_grid_rel_error < 0.15, (
            f"growth doesn't match |v|*t across the grid sweep -- possible "
            f"regression of the calculateVisibility=False default fix: {max_grid_rel_error}"
        )

        # No lateral spread: the real physical signature of directional
        # (line-of-sight) deposition, as opposed to isotropic
        # (conformal) deposition -- mirrors the Etching counterpart's
        # own "no lateral etch" check.
        recipe = {**BASE_RECIPE, "directional_velocity": 0.1, "deposition_time_s": 2.0}
        with tempfile.TemporaryDirectory() as run_tmp:
            result = step_cls().run(recipe, run_tmp)
            cap_xmin, cap_xmax = _si_cap_x_extent(result["final_mesh"], tag_name)
        window_width = BASE_RECIPE["mask_right_um"] - BASE_RECIPE["mask_left_um"]
        cap_width = cap_xmax - cap_xmin
        print(f"[6/6] grown-cap x-extent = [{cap_xmin:.4f}, {cap_xmax:.4f}] "
              f"(width={cap_width:.4f}, window width={window_width:.4f})")
        assert cap_width <= window_width + 2 * BASE_RECIPE["grid_delta_um"], (
            f"grown Si cap (width={cap_width}) spread laterally past the window "
            f"(width={window_width}) by more than one grid cell -- directional "
            f"deposition should not spread sideways with isotropic_velocity unset"
        )

        print()
        print("DIRECTIONAL DEPOSITION GROWS material +|v|*t as documented "
              "(sign-convention fix verified), the calculateVisibility=False "
              "default holds across a grid sweep, and growth does not spread "
              "laterally past the exposed window -- AGAINST REAL VIENNAPS 4.6.2")


if __name__ == "__main__":
    main()
