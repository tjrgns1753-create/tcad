#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Blanket vs. Selective deposition must be a real, user-chosen toggle,
real ViennaPS 4.6.2 -- not something forced by whether a mask happens
to exist in the recipe.

Root cause this pins (see docs/investigation_log.md, "Deposition:
renderer y-scale artifact ... unconditional mask exclusion", and the
follow-up found while wiring the GUI's own Blanket/Selective toggle):
"mask_material" is read by TWO independent things --
prepare_domain() (what material tag inserted mask/resist geometry
gets, unconditional) and, before this fix, the deposition models'
maskMaterial= growth-exclusion switch (which should be a user choice,
not automatic). Sharing one key name meant ANY recipe with a mask at
all made deposition unconditionally selective. Fixed by giving growth
-exclusion its own key, "deposit_exclude_material"
(tcad/process/deposition/isotropic.py and its directional/
single_particle_cvd siblings), set by the GUI only when the user picks
"Selective" in the new Deposition mode combobox.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio

from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import save_volume_mesh
from tcad.process.base import ProcessStep
from tcad.process.deposition.isotropic import IsotropicDeposition

assert session.is_available(), "ViennaPS must be installed for this real-backend test"

module = session.require_viennaps()

BASE_RECIPE = {
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


def _masked_domain():
    with tempfile.TemporaryDirectory() as tmp:
        return _Litho().run(BASE_RECIPE, tmp)["_domain"]


def _w_y_extent(domain, tmp_dir):
    """Real per-material y-range from an actually-exported volume mesh."""
    mesh_path = save_volume_mesh(domain, str(Path(tmp_dir) / "check"), floor_depth_um=5.0)
    mesh = meshio.read(mesh_path)
    triangle_block = next(c for c in mesh.cells if c.type == "triangle")
    block_index = mesh.cells.index(triangle_block)
    tags = mesh.cell_data["Material"][block_index]
    points = mesh.points
    ys = [
        points[idx][1]
        for tri, tag in zip(triangle_block.data, tags)
        if str(module.Material(int(tag))) == "Material('W')"
        for idx in tri
    ]
    return (min(ys), max(ys)) if ys else None


def main():
    # --- Blanket: no deposit_exclude_material key at all -> deposits
    #     straight over the ~1.0um PHS resist. ---
    dom_blanket = _masked_domain()
    dep = IsotropicDeposition()
    dep._inherited_domain = dom_blanket
    recipe_blanket = dict(BASE_RECIPE, rate=0.05, deposition_time_s=1.0, material="W")
    with tempfile.TemporaryDirectory() as tmp:
        dep.run(recipe_blanket, tmp)
        w_blanket = _w_y_extent(dom_blanket, tmp)

    assert w_blanket is not None, "Blanket deposition must produce W"
    blanket_thickness = w_blanket[1] - w_blanket[0]
    assert blanket_thickness > 0.5, (
        f"Blanket W should span roughly the full ~1.0um resist height, "
        f"got {blanket_thickness:.3f}um -- deposition did not cover the mask")

    # --- Selective: deposit_exclude_material="PHS" -> excluded from the
    #     resist, only grows in the open window. ---
    dom_selective = _masked_domain()
    dep2 = IsotropicDeposition()
    dep2._inherited_domain = dom_selective
    recipe_selective = dict(
        BASE_RECIPE, rate=0.05, deposition_time_s=1.0, material="W",
        deposit_exclude_material="PHS",
    )
    with tempfile.TemporaryDirectory() as tmp:
        dep2.run(recipe_selective, tmp)
        w_selective = _w_y_extent(dom_selective, tmp)

    assert w_selective is not None, "Selective deposition must still grow in the open window"
    selective_thickness = w_selective[1] - w_selective[0]
    assert selective_thickness < 0.3, (
        f"Selective W should be excluded from the ~1.0um resist and stay "
        f"thin (open-window growth only), got {selective_thickness:.3f}um")

    print(f"Blanket W spans {blanket_thickness:.3f}um (covers the resist); "
          f"Selective W spans {selective_thickness:.3f}um (excludes it) -- "
          f"the mode toggle genuinely changes real ViennaPS growth.")


if __name__ == "__main__":
    main()
