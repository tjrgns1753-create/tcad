#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Directional (PVD/sputter-style) deposition — a thin recipe wrapper
around ViennaPS's DirectionalProcess primitive (the same primitive the
Etching counterpart uses; see tcad/process/etching/directional.py).

Real API used (verified against installed ViennaPS 4.6.2 via
`vps.DirectionalProcess.__init__.__doc__`, overload 2):

    vps.DirectionalProcess(
        direction: [x, y, z],
        directionalVelocity,
        isotropicVelocity=0.0,
        maskMaterial=Material('Mask'),
        calculateVisibility=True,
    )

Deposition convention: `directional_velocity` (this module's recipe
key) and `isotropic_velocity` are both expected positive to grow
material along `direction` -- but the two ViennaPS constructor kwargs
they map to do NOT share one sign convention, confirmed empirically
(not assumed) via the real production path with a floored/exported
volume mesh, sweeping direction/velocity sign combinations:

  - `isotropicVelocity`: positive genuinely grows material (matches its
    own docstring). No transformation needed.
  - `directionalVelocity`: for direction=[0,1,0] (grow upward),
    directionalVelocity=+0.1 measured as -0.2um of material REMOVED
    after 2s (i.e. it etched), while directionalVelocity=-0.1 measured
    as +0.2um GROWN. The rule that fit all 4 tested (direction,
    velocity-sign) combinations, direction in {[0,1,0], [0,-1,0]}: the
    interface grows when `direction . directionalVelocity < 0` and
    erodes when `> 0` -- opposite to the naive "positive means grow"
    reading, and opposite to isotropicVelocity's own convention. This
    module therefore negates directional_velocity before passing it to
    ViennaPS's directionalVelocity (see run(), below), so this
    module's own recipe-level convention (positive = grow) holds
    regardless of ViennaPS's underlying sign. isotropic_velocity is
    passed through unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import DEFAULT_FLOOR_DEPTH_UM, SnapshotRecorder, save_volume_mesh
from tcad.process.base import ProcessStep
from tcad.process.registry import register


@register
class DirectionalDeposition(ProcessStep):
    category = "deposition"
    name = "directional"
    display_name = "Directional (PVD/Sputter) Deposition"

    def run(self, recipe: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
        module = session.require_viennaps()

        # Fresh wafer normally; the previous step's domain when this
        # step is part of a process flow (see ProcessStep.prepare_domain).
        geometry = self.prepare_domain(recipe)

        model_kwargs: Dict[str, Any] = {
            "direction": recipe["direction"],
            # Negated: see module docstring -- ViennaPS's own
            # directionalVelocity sign is inverted relative to this
            # module's recipe convention (positive = grow), confirmed
            # empirically, not assumed.
            "directionalVelocity": -recipe["directional_velocity"],
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
            recipe["deposition_time_s"],
        ).apply()

        recorder.capture(geometry, "001_directional_deposition")

        final_mesh = Path(output_dir) / "directional_deposition_final"
        final_mesh_path = save_volume_mesh(
            geometry, final_mesh,
            floor_depth_um=recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM),
        )

        return {
            "final_mesh": final_mesh_path,
            "snapshots": recorder.snapshots,
        }
