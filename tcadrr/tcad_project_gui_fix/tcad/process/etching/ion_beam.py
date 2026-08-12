#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Ion Beam Etching (IBE).

Real API used (verified against installed ViennaPS 4.6.2):

    vps.IonBeamEtching(parameters: vps.IBEParameters)
    vps.IonBeamEtching(parameters: vps.IBEParameters,
                        maskMaterials: Sequence[vps.Material])

Confirmed IBEParameters field names/defaults by instantiating
vps.IBEParameters() directly:
    exponent (100.0), inflectAngle (89.0), meanEnergy (250.0),
    minAngle (85.0), n_l (10.0), planeWaferRate (1.0),
    redepositionRate (0.0), redepositionThreshold (0.1),
    sigmaEnergy (10.0), thetaRMax (90.0), thetaRMin (70.0),
    thresholdEnergy (20.0), tiltAngle (0.0)
The nested cos4Yield sub-struct is left at its ViennaPS default
(isDefined=False) — not guessed here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import DEFAULT_FLOOR_DEPTH_UM, SnapshotRecorder, save_volume_mesh
from tcad.process.base import ProcessStep
from tcad.process.registry import register

# recipe key -> IBEParameters attribute name
_PARAM_FIELDS = {
    "exponent": "exponent",
    "inflect_angle": "inflectAngle",
    "mean_energy": "meanEnergy",
    "min_angle": "minAngle",
    "n_l": "n_l",
    "plane_wafer_rate": "planeWaferRate",
    "redeposition_rate": "redepositionRate",
    "redeposition_threshold": "redepositionThreshold",
    "sigma_energy": "sigmaEnergy",
    "theta_r_max": "thetaRMax",
    "theta_r_min": "thetaRMin",
    "threshold_energy": "thresholdEnergy",
    "tilt_angle": "tiltAngle",
}


@register
class IonBeamEtch(ProcessStep):
    category = "etching"
    name = "ibe"
    display_name = "Ion Beam Etching (IBE)"

    def run(self, recipe: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
        module = session.require_viennaps()

        # Fresh wafer normally; the previous step's domain when this
        # step is part of a process flow (see ProcessStep.prepare_domain).
        geometry = self.prepare_domain(recipe)

        params = module.IBEParameters()
        for recipe_key, attr in _PARAM_FIELDS.items():
            if recipe_key in recipe:
                setattr(params, attr, recipe[recipe_key])

        model = module.IonBeamEtching(params)

        recorder = SnapshotRecorder(output_dir)
        recorder.capture(geometry, "000_initial")

        module.Process(
            geometry,
            model,
            recipe["etch_time_s"],
        ).apply()

        recorder.capture(geometry, "001_ibe_etch")

        final_mesh = Path(output_dir) / "ibe_final"
        final_mesh_path = save_volume_mesh(
            geometry, final_mesh,
            floor_depth_um=recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM),
        )

        return {
            "final_mesh": final_mesh_path,
            "snapshots": recorder.snapshots,
        }
