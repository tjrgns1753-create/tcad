#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bosch DRIE must respect a lithography-tagged photoresist mask, not
only ViennaPS's own native "Mask" material.

Root cause this pins: bosch_drie.py's own mask-blocking logic
(polymer_breakthrough's maskMaterial, and etch_rate()'s zero-rate check)
was hardcoded to module.Material.Mask, while the GUI's real lithography
flow tags a chained-step resist "PHS" (tcad_2d_stagewise.py's
_RESIST_MATERIAL, kept distinct from ViennaPS's native "Mask" so
photoresist can be told apart from a hard mask). A real
oxidation -> lithography -> Bosch DRIE chain therefore silently ignored
the resist mask entirely -- no crash, no warning, the masked region
etched exactly like open silicon.

Decisive isolation: probe the SAME masked (outside-window) location
under an IDENTICAL recipe, varying only mask_material between "Mask"
(ViennaPS's native tag, always worked) and "PHS" (this project's real
resist tag). Before the fix, "Mask" left the probe height unchanged
while "PHS" measurably eroded it -- proof the hardcode, not the
recipe or the mask geometry, was the defect. After the fix both tags
must produce IDENTICAL protection.

Real physics grounding (not just "a mask should mask" asserted without
a source): Osipov, Iankevich, Berezenko, Endiiarova, "Influence of
operation parameters on BOSCH-process technological characteristics",
Materials Today: Proceedings (2020) -- measured real Si/photoresist
etch selectivity around 38:1 (SF6/CHF3 chemistry, ICP reactor) for
exactly this cyclic passivation/etch process, confirming a photoresist
mask genuinely blocks Bosch DRIE etching in reality. This test checks
the SIGN of that effect (masked stays protected) at the binary
maskMaterial=0-or-full-rate resolution ViennaPS itself offers -- it
does not attempt to reproduce the finite 38:1 ratio, which is a known
simplification already implicit in every other etch model here
(isotropic.py, directional.py) that reads mask_material the same
dynamic way this fix now does.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio
import numpy as np

import tcad.process.oxidation  # noqa: F401 -- registers oxidation models
import tcad.process.etching    # noqa: F401 -- registers etch models
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry
from tcad.process.base import mask_spans_from_openings

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"

WIDTH_UM = 10.0
Y_EXTENT_UM = 8.0
SILICON_DEPTH_UM = 5.0
PR_THICKNESS_UM = 1.0
MASK_OPENINGS = [[3.5, 6.5]]
GRID_DELTA_UM = 0.05
PROBE_X = -3.0  # outside the mask opening -- must stay protected either way


def _outside_window_height(mask_material_tag):
    """Real oxidation -> real litho-tagged remask -> real Bosch DRIE
    (2 seconds total etch exposure), then the real topmost material and
    height at PROBE_X (a masked, outside-window location)."""
    with tempfile.TemporaryDirectory() as tmp:
        ox_recipe = {
            "_process_category": "oxidation", "_process_model_key": "thermal",
            "mask_spans_um": [], "pr_thickness_um": PR_THICKNESS_UM,
            "silicon_depth_um": SILICON_DEPTH_UM, "grid_delta_um": GRID_DELTA_UM,
            "x_extent_um": WIDTH_UM, "y_extent_um": Y_EXTENT_UM,
            "oxidant": "Dry", "temperature_c": 1000.0, "time_hours": 0.5,
        }
        ox_step = registry.get("oxidation", "thermal")()
        ox_step.run(ox_recipe, tmp)

        spans = mask_spans_from_openings(MASK_OPENINGS, WIDTH_UM)
        etch_recipe = {
            "_process_category": "etching", "_process_model_key": "bosch_drie",
            "remask_spans_um": spans, "mask_material": mask_material_tag,
            "pr_thickness_um": PR_THICKNESS_UM, "silicon_depth_um": SILICON_DEPTH_UM,
            "grid_delta_um": GRID_DELTA_UM, "x_extent_um": WIDTH_UM,
            "y_extent_um": Y_EXTENT_UM,
            "etch_time_s": 0.3, "cycles": 1, "polymer_rate": 0.03,
            "polymer_sticking": 1.0, "ion_source_exponent": 500.0,
            "ion_rate": -0.02, "neutral_rate": -0.01, "neutral_sticking": 0.10,
        }
        etch_step = registry.get("etching", "bosch_drie")(
            inherited_domain=ox_step.last_domain
        )
        etch_result = etch_step.run(etch_recipe, tmp)
        mesh = meshio.read(etch_result["final_mesh"])

        import viennaps as vps
        names = {}
        for attr in dir(vps.Material):
            if attr.startswith("_"):
                continue
            v = getattr(vps.Material, attr)
            if isinstance(v, vps.Material):
                names.setdefault(int(v), attr)

        best = None
        for key, blocks in mesh.cell_data.items():
            if "material" not in key.lower():
                continue
            for cells, values in zip(mesh.cells, blocks):
                for cell, tag in zip(cells.data, np.asarray(values).ravel()):
                    corners = mesh.points[cell]
                    x_mid = corners[:, 0].mean()
                    if abs(x_mid - PROBE_X) >= 0.15:
                        continue
                    y_top = corners[:, 1].max()
                    name = names.get(int(tag), f"?{int(tag)}")
                    if best is None or y_top > best[0]:
                        best = (y_top, name)
        assert best is not None, f"no cells found near x={PROBE_X}"
        return best  # (y_top, material_name)


def main():
    y_mask, mat_mask = _outside_window_height("Mask")
    y_phs, mat_phs = _outside_window_height("PHS")

    print(f"[1/2] mask_material='Mask': outside-window topmost={mat_mask} at y={y_mask:.4f}")
    print(f"[2/2] mask_material='PHS' : outside-window topmost={mat_phs} at y={y_phs:.4f}")

    # Both tags name a real mask; the masked region must be protected
    # identically regardless of which one the caller used. A regression
    # of the hardcode bug would show mat_phs != mat_phs's own tag name
    # (etched down to Si/SiO2) or a height measurably lower than y_mask.
    assert mat_phs == "PHS", (
        f"outside-window resist eroded through to {mat_phs!r} -- the "
        f"'PHS'-tagged mask was not respected (the hardcoded-Material.Mask "
        f"regression this test exists to catch)"
    )
    # Tolerance is 10% of the mesh grid spacing -- enough to absorb
    # ordinary mesh-generation noise between two independent runs, far
    # tighter than the ~0.06um erosion the hardcode bug actually produced
    # (a regression of that bug would fail this by >10x).
    tolerance_um = GRID_DELTA_UM * 0.1
    assert abs(y_phs - y_mask) < tolerance_um, (
        f"'PHS'-tagged mask protected the region to a DIFFERENT height "
        f"({y_phs:.6f}) than 'Mask'-tagged ({y_mask:.6f}) under the "
        f"identical recipe -- both must be equally protected "
        f"(tolerance {tolerance_um:.6f})"
    )
    print("Bosch DRIE respects a lithography-tagged ('PHS') resist mask "
          "exactly as it already respects ViennaPS's native 'Mask' tag.")


if __name__ == "__main__":
    main()
