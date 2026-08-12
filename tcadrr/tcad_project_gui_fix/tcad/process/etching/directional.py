#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Directional (anisotropic RIE-style) etching — a thin recipe wrapper
around ViennaPS's DirectionalProcess primitive.

Real API used (verified against installed ViennaPS 4.6.2 via
`vps.DirectionalProcess.__init__.__doc__`, overload 2):

    vps.DirectionalProcess(
        direction: [x, y, z],
        directionalVelocity,
        isotropicVelocity=0.0,
        maskMaterial=Material('Mask'),
        calculateVisibility=True,
    )

Etching convention: directionalVelocity (and isotropicVelocity, if
used) are expected negative to remove material along `direction`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import DEFAULT_FLOOR_DEPTH_UM, SnapshotRecorder, save_volume_mesh
from tcad.process.base import ProcessStep
from tcad.process.registry import register


@register
class DirectionalEtch(ProcessStep):
    category = "etching"
    name = "directional"
    display_name = "Directional (Anisotropic) Etching"

    def run(self, recipe: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
        module = session.require_viennaps()

        # Fresh wafer normally; the previous step's domain when this
        # step is part of a process flow (see ProcessStep.prepare_domain).
        geometry = self.prepare_domain(recipe)

        model_kwargs: Dict[str, Any] = {
            "direction": recipe["direction"],
            "directionalVelocity": recipe["directional_velocity"],
        }
        if "isotropic_velocity" in recipe:
            model_kwargs["isotropicVelocity"] = recipe["isotropic_velocity"]
        if "mask_material" in recipe:
            model_kwargs["maskMaterial"] = getattr(module.Material, recipe["mask_material"])
        if "calculate_visibility" in recipe:
            model_kwargs["calculateVisibility"] = recipe["calculate_visibility"]

        model = module.DirectionalProcess(**model_kwargs)

        recorder = SnapshotRecorder(output_dir)
        recorder.capture(geometry, "000_initial")

        module.Process(
            geometry,
            model,
            recipe["etch_time_s"],
        ).apply()

        recorder.capture(geometry, "001_directional_etch")

        final_mesh = Path(output_dir) / "directional_etch_final"
        final_mesh_path = save_volume_mesh(
            geometry, final_mesh,
            floor_depth_um=recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM),
        )

        return {
            "final_mesh": final_mesh_path,
            "snapshots": recorder.snapshots,
        }
