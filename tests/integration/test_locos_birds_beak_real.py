#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOCOS bird's-beak (lateral oxide encroachment under the mask edge) —
quantitative measurement through the real production entry point
(registry -> LocosOxidation.run(), tcad/process/oxidation/locos.py),
real ViennaPS 4.6.2.

This does NOT re-run the full grid/time/pad-thickness scaling study
already done and recorded in docs/investigation_log.md ("LOCOS
bird's-beak shape — INVESTIGATED, evidence supports genuine diffusion
physics, no code change needed") -- that investigation already
established, by real measurement, that the taper is grid-independent in
length and scales with pad-oxide thickness the way real lateral-
oxidant-diffusion physics predicts (0.3um taper at pad=0.1um vs. 0.45um
at pad=0.2um, at a mature growth stage). This test is a SMALL,
reusable regression check, at the exact SAME recipe class (pad=0.1um,
0.5hr/1000C dry, gd=0.05), that the same real, coordinate-measured
taper is still present after the 2026-09-08 LOCOS/ThermalOxidation
split -- so a future change that silently breaks the taper (e.g. an
export or mask-mechanics regression) has something to fail against,
without re-deriving the whole scaling study every time.

Real coordinates, not a visual "looks like a bird's beak" judgment:
the SiO2 top surface is read directly from the real, exported,
per-material mesh (same technique as
test_locos_contact_mode_fix_real.py's own _measure()), binned by x, and
compared at three x-regions relative to the recipe's own known window
edge:
  - window interior (field-oxide plateau)
  - right at the nominal mask edge (must be INTERMEDIATE, not equal to
    either the plateau or the pad-only value -- that intermediate value
    is the taper itself, at real, non-fabricated coordinates)
  - well under the mask (pad-oxide-only, effectively unmoved)
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio

import tcad.process.oxidation  # noqa: F401 -- registers "locos"
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"

# Matches docs/investigation_log.md's own "mature timescale" recipe
# class (pad=0.1um, 0.5hr, gd=0.05) -- the one shown there to sit well
# clear of grid-resolution noise, not a freshly invented value.
RECIPE = {
    "grid_delta_um": 0.05,
    "x_extent_um": 3.0,
    "y_extent_um": 2.0,
    "mask_left_um": 1.0,
    "mask_right_um": 2.0,  # 1.0um window, centered in domain coords
    "pr_thickness_um": 0.5,
    "oxidant": "Dry",
    "temperature_c": 1000.0,
    "time_hours": 0.5,
    "mask_material": "Mask",
    "pad_oxide_thickness_um": 0.1,
}


def _sio2_top_by_x(mesh_path, module, x_bin=0.05):
    """max y (top surface) of SiO2, binned by x -- a real y_top(x)
    profile read from the exported mesh's own triangle vertices, not a
    fabricated function."""
    mesh = meshio.read(str(mesh_path))
    block = next((c for c in mesh.cells if c.type == "triangle"), None)
    assert block is not None, f"{mesh_path} has no triangle cells"
    tags = mesh.cell_data["Material"][mesh.cells.index(block)]
    target = int(module.Material.SiO2)
    bins = {}
    for tri, tag in zip(block.data, tags):
        if int(tag) != target:
            continue
        for i in tri:
            x, y = float(mesh.points[i][0]), float(mesh.points[i][1])
            b = round(x / x_bin) * x_bin
            bins[b] = max(bins.get(b, -1e9), y)
    return bins


def main():
    module = viennaps_session.require_viennaps()
    step_cls = registry.get("oxidation", "locos")

    with tempfile.TemporaryDirectory() as tmp:
        result = step_cls().run(dict(RECIPE), tmp)
        profile = _sio2_top_by_x(result["final_mesh"], module)

        half = RECIPE["x_extent_um"] / 2.0
        window_right_domain = RECIPE["mask_right_um"] - half  # nominal mask edge, +0.5
        pad_um = RECIPE["pad_oxide_thickness_um"]

        # Field-oxide plateau: window interior, well clear of the edge.
        interior = {x: y for x, y in profile.items() if x < window_right_domain - 0.15}
        assert interior, "no SiO2 measured inside the growth window"
        plateau = max(interior.values())

        # Pad-oxide-only region: well under the mask, far from the edge.
        under_mask = {x: y for x, y in profile.items() if x > window_right_domain + 0.5}
        assert under_mask, "no SiO2 measured well under the mask"
        pad_only = min(under_mask.values())

        # Real value AT the nominal mask edge coordinate (nearest bin).
        edge_x = min(profile, key=lambda x: abs(x - window_right_domain))
        edge_y = profile[edge_x]

        print(f"[1/4] window interior (field-oxide) plateau: {plateau:.5f} um")
        print(f"[2/4] under-mask (pad-oxide-only) value: {pad_only:.5f} um "
              f"(started at pad_oxide_thickness_um={pad_um})")
        print(f"[3/4] value at nominal mask edge x={edge_x:+.3f} "
              f"(recipe edge={window_right_domain:+.3f}): {edge_y:.5f} um")

        # 1) Real vertical growth in the window: plateau clearly above
        # the as-built pad thickness.
        assert plateau > pad_um + 1e-4, (
            f"no real vertical oxide growth in the window: plateau={plateau:.5f} "
            f"vs as-built pad={pad_um}"
        )

        # 2) Mask genuinely protects the covered Si -- pad-oxide-only
        # region stayed close to its as-built thickness, not swept up
        # into the field-oxide growth.
        assert pad_only < plateau - 1e-4, (
            f"no real mask protection: under-mask value {pad_only:.5f} is not "
            f"clearly below the field-oxide plateau {plateau:.5f}"
        )
        assert abs(pad_only - pad_um) < 0.01, (
            f"under-mask SiO2 grew far more than expected for a protected region: "
            f"{pad_only:.5f} vs as-built {pad_um}"
        )

        # 3) Bird's beak: the value AT the nominal edge must be a real
        # TAPER -- strictly between the plateau and the pad-only value,
        # not equal to either (a sharp step would mean no lateral
        # encroachment at all; a value outside the range would be a
        # measurement error).
        assert pad_only < edge_y < plateau, (
            f"no taper at the mask edge: pad_only={pad_only:.5f}, "
            f"edge={edge_y:.5f}, plateau={plateau:.5f} -- expected a real "
            f"intermediate value (bird's-beak encroachment), not a sharp step"
        )
        print(f"[4/4] bird's-beak taper CONFIRMED at real coordinates: edge value "
              f"{edge_y:.5f} is strictly between pad-only {pad_only:.5f} and "
              f"plateau {plateau:.5f} -- a genuine lateral encroachment, not a "
              f"sharp mask-edge cutoff")

        # Quantify a taper length for the record (90% -> 10% of the
        # plateau-to-pad delta), printed only -- not asserted to a
        # specific number, since docs/investigation_log.md's own study
        # is the source of truth for the expected magnitude (~0.3-0.45um
        # at this pad thickness) and grid/solver noise can move this by
        # tens of percent run to run without indicating a regression.
        delta = plateau - pad_only
        hi_thresh = pad_only + 0.9 * delta
        lo_thresh = pad_only + 0.1 * delta
        xs_sorted = sorted(profile)
        x_hi = next((x for x in xs_sorted if x >= window_right_domain and profile[x] <= hi_thresh), None)
        x_lo = next((x for x in xs_sorted if x >= window_right_domain and profile[x] <= lo_thresh), None)
        if x_hi is not None and x_lo is not None:
            print(f"      taper length (90%->10% of plateau-to-pad delta): "
                  f"{x_lo - x_hi:.3f} um (docs/investigation_log.md's own study: "
                  f"~0.3um at this same pad=0.1um recipe class)")

        print()
        print("LOCOS BIRD'S-BEAK: real, coordinate-measured lateral oxide "
              "encroachment confirmed against real ViennaPS 4.6.2, post-split "
              "(tcad/process/oxidation/locos.py)")


if __name__ == "__main__":
    main()
