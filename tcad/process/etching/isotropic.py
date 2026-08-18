#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Isotropic etching — a thin recipe wrapper around ViennaPS's
IsotropicProcess primitive, used for etching (negative rate).

Real API used (verified against installed ViennaPS 4.6.2 via
`vps.IsotropicProcess.__init__.__doc__`):

    vps.IsotropicProcess(rate=1.0, maskMaterial=Material('Undefined'))

IsotropicProcess itself is direction-agnostic: a positive rate grows
material (see process/deposition/isotropic.py in a later phase) and a
negative rate removes it. This module fixes the etching convention
(rate is expected negative) so it can be registered distinctly from the
future deposition counterpart.

Material selectivity (optional `material_rates` recipe key)
-----------------------------------------------------------
Without it, one rate applies to every material except `mask_material`
— no selectivity, which real wet/isotropic chemistries do have.
Supplying `material_rates` selects ViennaPS's per-material overload:

    vps.IsotropicProcess(
        materialRates: {Material: rate},
        defaultRate=0.0,
    )

SIGN: negative removes, i.e. the SAME convention as the single-rate
overload above, so rates are passed through unchanged. This was
measured, not assumed, and specifically must not be inferred from
etching/directional.py: DirectionalProcess's own materialRates overload
uses the OPPOSITE sign from this one (positive removes there), and that
wrapper therefore has to flip the sign where this one must not. See
LOCOS_CHAINING_TEST_LOG.txt items 21/23 for both measurements.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import DEFAULT_FLOOR_DEPTH_UM, SnapshotRecorder, save_volume_mesh
from tcad.process.base import ProcessStep
from tcad.process.registry import register


@register
class IsotropicEtch(ProcessStep):
    category = "etching"
    name = "isotropic"
    display_name = "Isotropic Etching"

    def run(self, recipe: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
        module = session.require_viennaps()

        # Fresh wafer normally; the previous step's domain when this
        # step is part of a process flow (see ProcessStep.prepare_domain).
        geometry = self.prepare_domain(recipe)

        if "material_rates" in recipe:
            # Per-material selectivity. Rates pass through UNCHANGED:
            # this overload's sign convention matches the single-rate
            # one (negative removes), unlike DirectionalProcess's
            # materialRates overload. See the module docstring.
            material_rates = {
                getattr(module.Material, name): float(rate)
                for name, rate in recipe["material_rates"].items()
            }
            model = module.IsotropicProcess(
                materialRates=material_rates,
                defaultRate=float(recipe.get("default_rate", 0.0)),
            )
        else:
            model_kwargs: Dict[str, Any] = {"rate": recipe["rate"]}
            if "mask_material" in recipe:
                model_kwargs["maskMaterial"] = getattr(module.Material, recipe["mask_material"])

            model = module.IsotropicProcess(**model_kwargs)

        recorder = SnapshotRecorder(output_dir)
        recorder.capture(geometry, "000_initial")

        module.Process(
            geometry,
            model,
            recipe["etch_time_s"],
        ).apply()

        recorder.capture(geometry, "001_isotropic_etch")

        final_mesh = Path(output_dir) / "isotropic_etch_final"
        final_mesh_path = save_volume_mesh(
            geometry, final_mesh,
            floor_depth_um=recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM),
        )

        return {
            "final_mesh": final_mesh_path,
            "snapshots": recorder.snapshots,
        }
