#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Fluorocarbon (CxFy) plasma etching.

Real API used (verified against installed ViennaPS 4.6.2):

    vps.FluorocarbonEtching(parameters: vps.FluorocarbonParameters)

FluorocarbonEtching has only this one constructor — no flat-float
overload — so a vps.FluorocarbonParameters() instance is built and its
top-level fields set. Confirmed field names/defaults by instantiating
vps.FluorocarbonParameters() directly:
    ionFlux (56.0), etchantFlux (500.0), polyFlux (100.0),
    delta_p (1.0), temperature (300.0), k_ie (2.0), k_ev (2.0),
    etchStopDepth (-1.7976931348623157e+308)

Two additional real-API requirements found only by executing this model
against the installed package (not documented in any docstring):

  1. Global units must be set before use, or the model raises
     "RuntimeError: Units have not been set." — handled once, for every
     model, in tcad.backends.viennaps.session.create_domain().

  2. Every Material actually present in the geometry (Mask, Si,
     Polymer here) must be registered via
     params.addMaterial(FluorocarbonMaterialParameters), or the model
     raises "Material 'Si' not found in fluorocarbon model parameters."
     at Process().apply() time. FluorocarbonMaterialParameters' own
     confirmed fields/defaults (A_ie, A_sp, B_sp, E_a, Eth_ie, Eth_sp,
     K, beta_e, beta_p, density) are used unchanged — only `id` (the
     Material) is set per entry; no physical constants are guessed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import DEFAULT_FLOOR_DEPTH_UM, SnapshotRecorder, save_volume_mesh
from tcad.process.base import ProcessStep
from tcad.process.registry import register

# recipe key -> FluorocarbonParameters attribute name
_PARAM_FIELDS = {
    "ion_flux": "ionFlux",
    "etchant_flux": "etchantFlux",
    "poly_flux": "polyFlux",
    "delta_p": "delta_p",
    "temperature_k": "temperature",
    "k_ie": "k_ie",
    "k_ev": "k_ev",
    "etch_stop_depth": "etchStopDepth",
}

# Materials MakeTrench puts in the geometry (Mask, Si) plus Polymer,
# which the coverage-based surface model deposits during etching.
_REQUIRED_MATERIALS = ("Mask", "Si", "Polymer")


@register
class FluorocarbonEtch(ProcessStep):
    category = "etching"
    name = "fluorocarbon"
    display_name = "Fluorocarbon (CxFy) Plasma Etching"

    def run(self, recipe: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
        module = session.require_viennaps()

        # Fresh wafer normally; the previous step's domain when this
        # step is part of a process flow (see ProcessStep.prepare_domain).
        geometry = self.prepare_domain(recipe)

        params = module.FluorocarbonParameters()
        for recipe_key, attr in _PARAM_FIELDS.items():
            if recipe_key in recipe:
                setattr(params, attr, recipe[recipe_key])

        for material_name in _REQUIRED_MATERIALS:
            material_params = module.FluorocarbonMaterialParameters()
            material_params.id = getattr(module.Material, material_name)
            params.addMaterial(material_params)

        model = module.FluorocarbonEtching(params)

        recorder = SnapshotRecorder(output_dir)
        recorder.capture(geometry, "000_initial")

        module.Process(
            geometry,
            model,
            recipe["etch_time_s"],
        ).apply()

        recorder.capture(geometry, "001_fluorocarbon_etch")

        final_mesh = Path(output_dir) / "fluorocarbon_final"
        final_mesh_path = save_volume_mesh(
            geometry, final_mesh,
            floor_depth_um=recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM),
        )

        return {
            "final_mesh": final_mesh_path,
            "snapshots": recorder.snapshots,
        }
