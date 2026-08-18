#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SF6/C4F8 plasma etching (Bosch-chemistry family, same file shape as
sf6o2.py/hbr_o2.py, different parameter set: no oxygen flux, no oxygen
sputter yield -- this chemistry doesn't use O2 passivation).

Real API used (verified against installed ViennaPS 4.6.2 via
`vps.SF6C4F8Etching.__init__.__doc__`, overload 2):

    vps.SF6C4F8Etching(
        ionFlux, etchantFlux, meanEnergy, sigmaEnergy,
        ionExponent=300.0,
        etchStopDepth=-1.7976931348623157e+308,
    )
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import DEFAULT_FLOOR_DEPTH_UM, SnapshotRecorder, save_volume_mesh
from tcad.process.base import ProcessStep
from tcad.process.registry import register


@register
class SF6C4F8Etch(ProcessStep):
    category = "etching"
    name = "sf6_c4f8"
    display_name = "SF6/C4F8 Plasma Etching"

    def run(self, recipe: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
        module = session.require_viennaps()

        # Fresh wafer normally; the previous step's domain when this
        # step is part of a process flow (see ProcessStep.prepare_domain).
        geometry = self.prepare_domain(recipe)

        model_kwargs = {
            "ionFlux": recipe["ion_flux"],
            "etchantFlux": recipe["etchant_flux"],
            "meanEnergy": recipe["mean_energy"],
            "sigmaEnergy": recipe["sigma_energy"],
        }
        # Optional overrides — only pass through if given, so unset keys
        # fall back to ViennaPS's own confirmed defaults.
        for recipe_key, ctor_key in (
            ("ion_exponent", "ionExponent"),
            ("etch_stop_depth", "etchStopDepth"),
        ):
            if recipe_key in recipe:
                model_kwargs[ctor_key] = recipe[recipe_key]

        model = module.SF6C4F8Etching(**model_kwargs)

        recorder = SnapshotRecorder(output_dir)
        recorder.capture(geometry, "000_initial")

        module.Process(
            geometry,
            model,
            recipe["etch_time_s"],
        ).apply()

        recorder.capture(geometry, "001_sf6_c4f8_etch")

        final_mesh = Path(output_dir) / "sf6_c4f8_final"
        final_mesh_path = save_volume_mesh(
            geometry, final_mesh,
            floor_depth_um=recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM),
        )

        return {
            "final_mesh": final_mesh_path,
            "snapshots": recorder.snapshots,
        }
