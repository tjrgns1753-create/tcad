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

Material selectivity (optional `material_rates` recipe key)
-----------------------------------------------------------
Without it, this model has NO selectivity: one velocity is applied to
every material except `mask_material`. That is often not what a real
etch does -- a real oxide etch typically runs 10:1 or better against
Si -- and the difference is easy to mistake for selectivity when it
isn't: measured directly (see LOCOS_CHAINING_TEST_LOG.txt, item 19),
etching a masked window covered by 0.2um of oxide removes "only oxide"
at 0.05-0.20um of etch purely because the oxide is in the way, then
eats into Si at the very same rate the moment it punches through.

Supplying `material_rates` selects ViennaPS's own per-material
overload instead:

    vps.DirectionalProcess(
        direction: [x, y, z],
        materialRates: {Material: (directionalRate, isotropicRate)},
        defaultDirectionalRate=0.0,
        defaultIsotropicRate=0.0,
    )

SIGN: recipes keep this file's own convention -- NEGATIVE removes
material -- and the wrapper flips it before handing it to ViennaPS.
That flip is required, not cosmetic: measured against real ViennaPS
4.6.2, this overload takes POSITIVE rates to remove material, the
OPPOSITE of the single-velocity overload above, and a wrong-signed
value is silently a no-op rather than an error (see
LOCOS_CHAINING_TEST_LOG.txt, item 21 -- a negative-rate call removed
exactly 0.0000 where the positive-rate one removed the full 0.2001,
and the same trap has already bitten this project once on a different
overload, see CLAUDE.md "Directional deposition -- RESOLVED"). Note
IsotropicProcess's own materialRates overload does NOT share this
inversion (measured separately) -- the two disagree with each other,
so neither wrapper's convention should be inferred from the other's.
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

        if "material_rates" in recipe:
            # Per-material selectivity. Rates are NEGATED on the way in:
            # this overload removes material for POSITIVE rates, the
            # opposite of the single-velocity one below, while recipes
            # keep one convention (negative removes). See the module
            # docstring -- this is measured, and a wrong sign here fails
            # silently rather than raising.
            material_rates = {
                getattr(module.Material, name): (-float(directional), -float(isotropic))
                for name, (directional, isotropic) in recipe["material_rates"].items()
            }
            model = module.DirectionalProcess(
                direction=recipe["direction"],
                materialRates=material_rates,
                defaultDirectionalRate=-float(recipe.get("default_directional_rate", 0.0)),
                defaultIsotropicRate=-float(recipe.get("default_isotropic_rate", 0.0)),
            )
        else:
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
