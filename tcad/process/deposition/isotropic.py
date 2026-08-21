#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Isotropic deposition — a thin recipe wrapper around ViennaPS's
IsotropicProcess primitive, used for deposition (positive rate).

Real API used (verified against installed ViennaPS 4.6.2 via
`vps.IsotropicProcess.__init__.__doc__`, same class as
process/etching/isotropic.py):

    vps.IsotropicProcess(rate=1.0, maskMaterial=Material('Undefined'))

IsotropicProcess itself is direction-agnostic: a positive rate grows
material, a negative rate removes it (see process/etching/isotropic.py
for the etching counterpart). This module fixes the deposition
convention (rate is expected positive) so it can be registered
distinctly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import DEFAULT_FLOOR_DEPTH_UM, SnapshotRecorder, save_volume_mesh
from tcad.process.base import ProcessStep
from tcad.process.registry import register


@register
class IsotropicDeposition(ProcessStep):
    category = "deposition"
    name = "isotropic"
    display_name = "Isotropic Deposition"

    def run(self, recipe: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
        module = session.require_viennaps()

        # Fresh wafer normally; the previous step's domain when this
        # step is part of a process flow (see ProcessStep.prepare_domain).
        geometry = self.prepare_domain(recipe)

        if "material" in recipe:
            # Opt-in distinct-material tagging, same mechanism and same
            # default-off behavior as geometric_trench.py/bosch_drie.py:
            # without this key the deposit merges into whatever material
            # already sits on top (unchanged from before this existed).
            geometry.duplicateTopLevelSet(getattr(module.Material, recipe["material"]))

        model_kwargs: Dict[str, Any] = {"rate": recipe["rate"]}
        if "mask_material" in recipe:
            model_kwargs["maskMaterial"] = getattr(module.Material, recipe["mask_material"])

        model = module.IsotropicProcess(**model_kwargs)

        recorder = SnapshotRecorder(output_dir)
        recorder.capture(geometry, "000_initial")

        module.Process(
            geometry,
            model,
            recipe["deposition_time_s"],
        ).apply()

        recorder.capture(geometry, "001_isotropic_deposition")

        final_mesh = Path(output_dir) / "isotropic_deposition_final"
        final_mesh_path = save_volume_mesh(
            geometry, final_mesh,
            floor_depth_um=recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM),
        )

        return {
            "final_mesh": final_mesh_path,
            "snapshots": recorder.snapshots,
        }
