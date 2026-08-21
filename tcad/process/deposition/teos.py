#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
TEOS Deposition (single- or dual-precursor conformal CVD).

Real API used (verified against installed ViennaPS 4.6.2 via
`vps.TEOSDeposition.__init__.__doc__`):

    vps.TEOSDeposition(
        stickingProbabilityP1, rateP1, orderP1,
        stickingProbabilityP2=0.0, rateP2=0.0, orderP2=0.0,
    )

Only one constructor exists (no parameter struct). P1 is the primary
precursor; P2 is an optional second precursor (defaults to inactive,
matching ViennaPS's own defaults).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import DEFAULT_FLOOR_DEPTH_UM, SnapshotRecorder, save_volume_mesh
from tcad.process.base import ProcessStep
from tcad.process.registry import register


@register
class TEOSDeposition(ProcessStep):
    category = "deposition"
    name = "teos"
    display_name = "TEOS Deposition"

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
            "stickingProbabilityP1": recipe["sticking_probability_p1"],
            "rateP1": recipe["rate_p1"],
            "orderP1": recipe["order_p1"],
        }
        for recipe_key, ctor_key in (
            ("sticking_probability_p2", "stickingProbabilityP2"),
            ("rate_p2", "rateP2"),
            ("order_p2", "orderP2"),
        ):
            if recipe_key in recipe:
                model_kwargs[ctor_key] = recipe[recipe_key]

        model = module.TEOSDeposition(**model_kwargs)

        recorder = SnapshotRecorder(output_dir)
        recorder.capture(geometry, "000_initial")

        module.Process(
            geometry,
            model,
            recipe["deposition_time_s"],
        ).apply()

        recorder.capture(geometry, "001_teos_deposition")

        final_mesh = Path(output_dir) / "teos_deposition_final"
        final_mesh_path = save_volume_mesh(
            geometry, final_mesh,
            floor_depth_um=recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM),
        )

        return {
            "final_mesh": final_mesh_path,
            "snapshots": recorder.snapshots,
        }
