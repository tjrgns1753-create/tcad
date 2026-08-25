#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Conformal CVD-style deposition — a thin recipe wrapper around
ViennaPS's SingleParticleProcess primitive (the same primitive Bosch
DRIE uses for its polymer passivation step; see
tcad/process/etching/bosch_drie.py).

Real API used (verified against installed ViennaPS 4.6.2, already
exercised in Phase 1/2):

    vps.SingleParticleProcess(
        rate=1.0, stickingProbability=1.0, sourceExponent=1.0,
        maskMaterial=Material('Undefined'),
    )

Deposition convention: rate is expected positive to grow material
(the etching counterpart in tcad/process/etching/isotropic.py /
directional.py uses a negative rate on the same primitives).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import DEFAULT_FLOOR_DEPTH_UM, SnapshotRecorder, save_volume_mesh
from tcad.process.base import ProcessStep
from tcad.process.registry import register


@register
class SingleParticleCVDDeposition(ProcessStep):
    category = "deposition"
    name = "single_particle_cvd"
    display_name = "Conformal CVD (SingleParticleProcess)"

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
            "rate": recipe["rate"],
            "stickingProbability": recipe["sticking_probability"],
        }
        if "source_exponent" in recipe:
            model_kwargs["sourceExponent"] = recipe["source_exponent"]
        # See isotropic.py's matching comment: "deposit_exclude_material"
        # (user-chosen growth exclusion) is deliberately distinct from
        # "mask_material" (unconditional mask/resist geometry tagging,
        # set by prepare_domain() on every recipe that has a mask).
        if "deposit_exclude_material" in recipe:
            model_kwargs["maskMaterial"] = getattr(
                module.Material, recipe["deposit_exclude_material"]
            )

        model = module.SingleParticleProcess(**model_kwargs)

        recorder = SnapshotRecorder(output_dir)
        recorder.capture(geometry, "000_initial")

        module.Process(
            geometry,
            model,
            recipe["deposition_time_s"],
        ).apply()

        recorder.capture(geometry, "001_single_particle_cvd")

        final_mesh = Path(output_dir) / "single_particle_cvd_final"
        final_mesh_path = save_volume_mesh(
            geometry, final_mesh,
            floor_depth_um=recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM),
        )

        return {
            "final_mesh": final_mesh_path,
            "snapshots": recorder.snapshots,
        }
