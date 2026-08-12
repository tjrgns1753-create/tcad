#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Wet (isotropic, per-material rate) etching.

Real API used (verified against installed ViennaPS 4.6.2 via
`vps.WetEtching.__init__.__doc__`):

    vps.WetEtching(materialRates: Sequence[tuple[vps.Material, float]])

ViennaPS also exposes a second, crystallographic overload:

    vps.WetEtching(direction100, direction010,
                    rate100, rate110, rate111, rate311,
                    materialRates)

for orientation-dependent wet etches (e.g. KOH/TMAH on <100> silicon,
as in the cantileverWetEtching example). That overload needs empirical
etch-rate constants (rate100/110/111/311) that are specific to a real
etchant/temperature combination — this module does not fabricate those
numbers, so only the simpler per-material-rate overload is implemented
here. The crystallographic overload can be added once real rate
constants are supplied (e.g. from a datasheet or calibration run).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import DEFAULT_FLOOR_DEPTH_UM, SnapshotRecorder, save_volume_mesh
from tcad.process.base import ProcessStep
from tcad.process.registry import register


@register
class WetEtch(ProcessStep):
    category = "etching"
    name = "wet_etching"
    display_name = "Wet Etching (per-material rate)"

    def run(self, recipe: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
        module = session.require_viennaps()

        # Fresh wafer normally; the previous step's domain when this
        # step is part of a process flow (see ProcessStep.prepare_domain).
        geometry = self.prepare_domain(recipe)

        # recipe["material_rates"]: list of {"material": "Si", "rate": -0.05}
        material_rates = [
            (getattr(module.Material, entry["material"]), entry["rate"])
            for entry in recipe["material_rates"]
        ]

        model = module.WetEtching(material_rates)

        recorder = SnapshotRecorder(output_dir)
        recorder.capture(geometry, "000_initial")

        module.Process(
            geometry,
            model,
            recipe["etch_time_s"],
        ).apply()

        recorder.capture(geometry, "001_wet_etch")

        final_mesh = Path(output_dir) / "wet_etching_final"
        final_mesh_path = save_volume_mesh(
            geometry, final_mesh,
            floor_depth_um=recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM),
        )

        return {
            "final_mesh": final_mesh_path,
            "snapshots": recorder.snapshots,
        }
