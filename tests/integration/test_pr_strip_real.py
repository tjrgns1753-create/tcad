#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PR STRIP must genuinely remove resist geometry from the live domain,
real ViennaPS 4.6.2.

Root cause this pins (see docs/investigation_log.md, "PR Strip removes
nothing"): resist that becomes real geometry used to be tagged
Material.Mask, the same tag LOCOS's own permanent hard mask uses, so
there was no safe way to remove ONLY the resist. Fixed by tagging
resist Material.PHS (TCADApplication._RESIST_MATERIAL) instead, so PR
STRIP can call domain.removeMaterial(PHS) unconditionally without ever
risking a real hard mask.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.backends.viennaps import session
from tcad.process.base import ProcessStep
from tcad.process.etching.isotropic import IsotropicEtch

assert session.is_available(), "ViennaPS must be installed for this real-backend test"

module = session.require_viennaps()

RECIPE = {
    "mask_left_um": 3.5, "mask_right_um": 6.5,
    "mask_spans_um": [[3.5, 6.5]],
    "mask_material": "PHS",
    "pr_thickness_um": 1.0,
    "silicon_depth_um": 5.0,
    "grid_delta_um": 0.2,
    "x_extent_um": 10.0,
    "y_extent_um": 8.0,
}


class _Litho(ProcessStep):
    category = "_test"
    name = "_litho_only"

    def run(self, recipe, output_dir):
        return {"_domain": self.prepare_domain(recipe)}


def main():
    litho = _Litho()
    with tempfile.TemporaryDirectory() as tmp:
        domain = litho.run(RECIPE, tmp)["_domain"]

    materials = sorted(str(m) for m in domain.getMaterialsInDomain())
    assert "Material('PHS')" in materials, (
        f"resist geometry must be tagged PHS, not Mask: {materials}")
    assert "Material('Mask')" not in materials, (
        f"resist must NOT be tagged Mask -- that's LOCOS's own hard mask "
        f"tag, and confusing the two is the bug this test pins: {materials}")

    # Etch through the resist -- it must protect the covered region,
    # same as any real litho-masked etch, and must still be there
    # afterward (etching does not consume the mask).
    etch = IsotropicEtch()
    etch._inherited_domain = domain
    etch_recipe = dict(RECIPE, rate=-0.05, etch_time_s=2.0)
    with tempfile.TemporaryDirectory() as tmp:
        etch.run(etch_recipe, tmp)

    materials_after_etch = sorted(str(m) for m in domain.getMaterialsInDomain())
    assert "Material('PHS')" in materials_after_etch, (
        f"resist must survive a real etch through it: {materials_after_etch}")

    # PR STRIP: exactly what worker_main()'s _strip_resist branch does.
    domain.removeMaterial(module.Material.PHS)
    materials_after_strip = sorted(str(m) for m in domain.getMaterialsInDomain())
    assert "Material('PHS')" not in materials_after_strip, (
        f"PR STRIP must remove PHS from the live domain: {materials_after_strip}")
    assert any("Si" in m and "SiO2" not in m for m in materials_after_strip), (
        f"Si must remain after PR STRIP: {materials_after_strip}")

    print("PR STRIP genuinely removes resist (PHS) from the live domain; "
          "Si remains; LOCOS's Mask tag is never touched.")


if __name__ == "__main__":
    main()
