#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Faraday Cage Ion Beam Etching — IBE (see ion_beam.py) plus a Faraday-cage
geometric correction. Confirmed by instantiating
`vps.FaradayCageParameters()` directly: it nests an `ibeParams`
(`vps.IBEParameters`, same fields/defaults as ion_beam.py's own
_PARAM_FIELDS) plus one extra top-level field, `cageAngle` (default 0.0).

Real API used (verified against installed ViennaPS 4.6.2):

    vps.FaradayCageEtching(parameters: vps.FaradayCageParameters,
                            maskMaterials: Sequence[vps.Material])

Unlike IonBeamEtching, maskMaterials has no default overload here — it
is always required, so this module defaults it to [Material('Mask')]
when the recipe doesn't specify one, matching this project's convention
elsewhere (e.g. MakeTrench's own maskMaterial default).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import DEFAULT_FLOOR_DEPTH_UM, SnapshotRecorder, save_volume_mesh
from tcad.process.base import ProcessStep
from tcad.process.registry import register

# recipe key -> IBEParameters attribute name (same fields as ion_beam.py)
_IBE_PARAM_FIELDS = {
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
class FaradayCageEtch(ProcessStep):
    category = "etching"
    name = "faraday_cage"
    display_name = "Faraday Cage Ion Beam Etching"

    def run(self, recipe: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
        module = session.require_viennaps()

        # Fresh wafer normally; the previous step's domain when this
        # step is part of a process flow (see ProcessStep.prepare_domain).
        geometry = self.prepare_domain(recipe)

        params = module.FaradayCageParameters()
        if "cage_angle" in recipe:
            params.cageAngle = recipe["cage_angle"]
        for recipe_key, attr in _IBE_PARAM_FIELDS.items():
            if recipe_key in recipe:
                setattr(params.ibeParams, attr, recipe[recipe_key])

        mask_materials = [
            getattr(module.Material, m)
            for m in recipe.get("mask_materials", ["Mask"])
        ]

        model = module.FaradayCageEtching(params, mask_materials)

        recorder = SnapshotRecorder(output_dir)
        recorder.capture(geometry, "000_initial")

        module.Process(
            geometry,
            model,
            recipe["etch_time_s"],
        ).apply()

        recorder.capture(geometry, "001_faraday_cage_etch")

        final_mesh = Path(output_dir) / "faraday_cage_final"
        final_mesh_path = save_volume_mesh(
            geometry, final_mesh,
            floor_depth_um=recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM),
        )

        return {
            "final_mesh": final_mesh_path,
            "snapshots": recorder.snapshots,
        }
