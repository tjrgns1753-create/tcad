#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
TEOS Plasma-Enhanced CVD (radical + ion-assisted deposition).

Real API used (verified against installed ViennaPS 4.6.2 via
`vps.TEOSPECVD.__init__.__doc__`):

    vps.TEOSPECVD(
        stickingProbabilityRadical, depositionRateRadical,
        depositionRateIon, exponentIon,
        stickingProbabilityIon=1.0, reactionOrderRadical=1.0,
        reactionOrderIon=1.0, minAngleIon=0.0,
    )

Only one constructor exists (no parameter struct).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import DEFAULT_FLOOR_DEPTH_UM, SnapshotRecorder, save_volume_mesh
from tcad.process.base import ProcessStep
from tcad.process.registry import register


@register
class TEOSPECVDDeposition(ProcessStep):
    category = "deposition"
    name = "teos_pecvd"
    display_name = "TEOS PE-CVD"

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

        model_kwargs: Dict[str, Any] = {
            "stickingProbabilityRadical": recipe["sticking_probability_radical"],
            "depositionRateRadical": recipe["deposition_rate_radical"],
            "depositionRateIon": recipe["deposition_rate_ion"],
            "exponentIon": recipe["exponent_ion"],
        }
        for recipe_key, ctor_key in (
            ("sticking_probability_ion", "stickingProbabilityIon"),
            ("reaction_order_radical", "reactionOrderRadical"),
            ("reaction_order_ion", "reactionOrderIon"),
            ("min_angle_ion", "minAngleIon"),
        ):
            if recipe_key in recipe:
                model_kwargs[ctor_key] = recipe[recipe_key]

        model = module.TEOSPECVD(**model_kwargs)

        recorder = SnapshotRecorder(output_dir)
        recorder.capture(geometry, "000_initial")

        module.Process(
            geometry,
            model,
            recipe["deposition_time_s"],
        ).apply()

        recorder.capture(geometry, "001_teos_pecvd")

        final_mesh = Path(output_dir) / "teos_pecvd_final"
        final_mesh_path = save_volume_mesh(
            geometry, final_mesh,
            floor_depth_um=recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM),
        )

        return {
            "final_mesh": final_mesh_path,
            "snapshots": recorder.snapshots,
        }
