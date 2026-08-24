#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Selective Epitaxy (crystal-orientation-dependent growth).

Real API used (verified against installed ViennaPS 4.6.2 via
`vps.SelectiveEpitaxy.__init__.__doc__`, overload 2):

    vps.SelectiveEpitaxy(
        materialRates: Sequence[tuple[Material, float]],
        rate111=0.5, rate100=1.0,
    )

rate111/rate100 defaults (0.5, 1.0) are ViennaPS's own confirmed
defaults, not fabricated here — they are only overridden if the recipe
supplies them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import DEFAULT_FLOOR_DEPTH_UM, SnapshotRecorder, save_volume_mesh
from tcad.process.base import ProcessStep
from tcad.process.registry import register


@register
class SelectiveEpitaxyDeposition(ProcessStep):
    category = "deposition"
    name = "selective_epitaxy"
    display_name = "Selective Epitaxy"

    def run(self, recipe: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
        module = session.require_viennaps()

        # Fresh wafer normally; the previous step's domain when this
        # step is part of a process flow (see ProcessStep.prepare_domain).
        geometry = self.prepare_domain(recipe)

        if "material" in recipe:
            # Same opt-in distinct-material tagging every other
            # deposition model in this package already has (isotropic,
            # directional, single_particle_cvd, teos, teos_pecvd,
            # geometric_trench); this was the one model without it, so
            # an epitaxial layer could only ever merge into whatever
            # material was already on top.
            #
            # Merging is correct for HOMOepitaxy -- Si grown on Si is
            # the same crystal, not a new region -- which is why the key
            # stays optional and absent by default: a recipe that does
            # not set it behaves exactly as before. It is HETEROepitaxy
            # (SiGe on Si, say) that needs the grown layer to be its own
            # material, and that was not expressible at all.
            #
            # NOTE this is the DEPOSITED material, which is a different
            # thing from the "material" entries in `material_rates`
            # below -- those name the SEED surfaces growth is selective
            # to (e.g. grow on Si, not on the mask).
            geometry.duplicateTopLevelSet(getattr(module.Material, recipe["material"]))

        # recipe["material_rates"]: list of {"material": "Si", "rate": 1.0}
        material_rates = [
            (getattr(module.Material, entry["material"]), entry["rate"])
            for entry in recipe["material_rates"]
        ]

        model_args = [material_rates]
        model_kwargs: Dict[str, Any] = {}
        if "rate_111" in recipe:
            model_kwargs["rate111"] = recipe["rate_111"]
        if "rate_100" in recipe:
            model_kwargs["rate100"] = recipe["rate_100"]

        model = module.SelectiveEpitaxy(*model_args, **model_kwargs)

        recorder = SnapshotRecorder(output_dir)
        recorder.capture(geometry, "000_initial")

        module.Process(
            geometry,
            model,
            recipe["deposition_time_s"],
        ).apply()

        recorder.capture(geometry, "001_selective_epitaxy")

        final_mesh = Path(output_dir) / "selective_epitaxy_final"
        final_mesh_path = save_volume_mesh(
            geometry, final_mesh,
            floor_depth_um=recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM),
        )

        return {
            "final_mesh": final_mesh_path,
            "snapshots": recorder.snapshots,
        }
