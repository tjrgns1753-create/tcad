#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SF6/O2 plasma etching (holeEtching example family).

Real API used (verified against installed ViennaPS 4.6.2 via
`vps.SF6O2Etching.__init__.__doc__`):

    vps.SF6O2Etching(
        ionFlux, etchantFlux, oxygenFlux,
        meanIonEnergy=100.0, sigmaIonEnergy=10.0,
        ionExponent=100.0, oxySputterYield=3.0,
        etchStopDepth=-1.7976931348623157e+308,
    )

A second overload accepts a PlasmaEtchingParameters struct for full
control (nested Ions/Mask/Passivation/Polymer/Substrate sub-parameters);
this module intentionally uses the flat-float overload above, since its
parameter names/defaults are fully confirmed and match this project's
existing recipe-dict style (see bosch_drie.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import DEFAULT_FLOOR_DEPTH_UM, SnapshotRecorder, save_volume_mesh
from tcad.process.base import ProcessStep
from tcad.process.registry import register


@register
class SF6O2Etch(ProcessStep):
    category = "etching"
    name = "sf6o2"
    display_name = "SF6/O2 Plasma Etching"

    def run(self, recipe: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
        module = session.require_viennaps()

        # Fresh wafer normally; the previous step's domain when this
        # step is part of a process flow (see ProcessStep.prepare_domain).
        geometry = self.prepare_domain(recipe)

        model_kwargs = {
            "ionFlux": recipe["ion_flux"],
            "etchantFlux": recipe["etchant_flux"],
            "oxygenFlux": recipe["oxygen_flux"],
        }
        # Optional overrides — only pass through if given, so unset keys
        # fall back to ViennaPS's own confirmed defaults.
        for recipe_key, ctor_key in (
            ("mean_ion_energy", "meanIonEnergy"),
            ("sigma_ion_energy", "sigmaIonEnergy"),
            ("ion_exponent", "ionExponent"),
            ("oxy_sputter_yield", "oxySputterYield"),
            ("etch_stop_depth", "etchStopDepth"),
        ):
            if recipe_key in recipe:
                model_kwargs[ctor_key] = recipe[recipe_key]

        model = module.SF6O2Etching(**model_kwargs)

        recorder = SnapshotRecorder(output_dir)
        recorder.capture(geometry, "000_initial")

        module.Process(
            geometry,
            model,
            recipe["etch_time_s"],
        ).apply()

        recorder.capture(geometry, "001_sf6o2_etch")

        final_mesh = Path(output_dir) / "sf6o2_final"
        final_mesh_path = save_volume_mesh(
            geometry, final_mesh,
            floor_depth_um=recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM),
        )

        return {
            "final_mesh": final_mesh_path,
            "snapshots": recorder.snapshots,
        }
