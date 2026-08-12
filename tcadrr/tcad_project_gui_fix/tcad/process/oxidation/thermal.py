#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Thermal Oxidation.

Real API used (verified against installed ViennaPS 4.6.2 — vps.Oxidation
is a builder-style ProcessModel, not a flat-kwarg constructor):

    model = vps.Oxidation()                      # no-arg constructor
    model.setOxidant(vps.OxidantType.Dry | Wet)   # docstring: "Oxidant species"
    model.setTemperature(temperatureC)            # docstring: "in °C (800-1200 °C)"
    model.setTime(timeHr)                         # docstring: "Total oxidation time in hours"
    model.setPressure(pressureAtm)                # optional, docstring: "in atm"
    model.setOxideMaterial(material)               # optional override
    model.setSiliconMaterial(material)              # optional override
    model.setMaskMaterial(material)                 # optional; docstring:
                                                      # "activates LOCOS physics"
    vps.Process(domain, model).apply()

Two things confirmed only by real execution (not guessed):
  - setTime() takes **hours**, unlike this project's other *_s recipe
    keys — kept as its own explicit `time_hours` key rather than forced
    into the *_s convention, to avoid a silent unit mismatch.
  - The `duration` argument to vps.Process() is not used by Oxidation:
    passing a duration far from the value given to setTime() (tested
    999.0 vs setTime(0.01)) still simulated exactly 0.01 hr. Oxidation
    tracks its own physical time internally, so Process() is called
    with no duration argument here (default 0.0), and `time_hours` is
    the real control.

fin vs LOCOS, without a separate model file:
    vps.Oxidation.setMaskMaterial()'s own docstring states it
    "activates LOCOS physics" (mask-bending / bird's-beak mechanics).
    So a plain oxidation run (mask_material omitted) behaves like a
    fin/exposed-Si oxidation, and supplying mask_material switches the
    same model into LOCOS behavior. This is why fin/LOCOS do not need
    separate ProcessStep classes at this stage — the recipe's optional
    `mask_material` key is the variation point, as required.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import DEFAULT_FLOOR_DEPTH_UM, SnapshotRecorder, save_volume_mesh
from tcad.process.base import ProcessStep
from tcad.process.registry import register


@register
class ThermalOxidation(ProcessStep):
    category = "oxidation"
    name = "thermal"
    display_name = "Thermal Oxidation"

    def run(self, recipe: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
        module = session.require_viennaps()

        # Fresh wafer normally; the previous step's domain when this
        # step is part of a process flow (see ProcessStep.prepare_domain).
        #
        # LOCOS (mask_material present) builds with halfTrench=True:
        # verified (isolated scratch probes, this session) that this
        # avoids a real segfault in the mask/oxide elastic coupling
        # solver (solveElasticVelocity) that the full (non-half) trench
        # geometry triggers, with the process's own pad/seed oxide
        # setup unchanged. Fin-style oxidation (no mask_material) is
        # unaffected -- half_trench only ever becomes True here.
        #
        # NOTE (open issue, not yet fully physically validated): with
        # halfTrench=True, real oxide growth beyond the seed and Si
        # recession were confirmed present and Deal-Grove-consistent in
        # order of magnitude at time_hours=0.1, but the lateral
        # bird's-beak *shape* did not visibly change between
        # time_hours=0.01 and 0.1 -- consistent with it still being
        # dominated by the seed's own conformal geometry at this
        # grid_delta, not fully resolved lateral diffusion. Treat LOCOS
        # geometry as runtime-resolved (no crash) but physically
        # validation-limited until revisited.
        geometry = self.prepare_domain(recipe, half_trench="mask_material" in recipe)

        model = module.Oxidation()

        model.setOxidant(getattr(module.OxidantType, recipe["oxidant"]))
        model.setTemperature(recipe["temperature_c"])
        model.setTime(recipe["time_hours"])
        # Native-oxide seed the model auto-creates when no SiO2 layer
        # exists (psOxidation.hpp) defaults to 0.002um regardless of
        # gridDelta. Below one grid cell, the level-set can't resolve
        # the seed interface: oxidation stalls at t~0.1hr and the CFL
        # solver fails to converge at longer times (confirmed by raw
        # level-set experiments, isolated from saveVolumeMesh/DevSim).
        # Floor it at gridDelta, same as ViennaPS's own trenchOxidation.py
        # example (seed_thickness = max(oxideThickness, gridDelta)).
        model.setInitialOxideThickness(max(0.002, recipe["grid_delta_um"]))

        if "pressure_atm" in recipe:
            model.setPressure(recipe["pressure_atm"])
        if "oxide_material" in recipe:
            model.setOxideMaterial(getattr(module.Material, recipe["oxide_material"]))
        if "silicon_material" in recipe:
            model.setSiliconMaterial(getattr(module.Material, recipe["silicon_material"]))
        if "mask_material" in recipe:
            # Presence of this key is the fin (absent) vs LOCOS (present)
            # switch — see module docstring above.
            model.setMaskMaterial(getattr(module.Material, recipe["mask_material"]))

        recorder = SnapshotRecorder(output_dir)
        recorder.capture(geometry, "000_initial")

        module.Process(geometry, model).apply()

        recorder.capture(geometry, "001_thermal_oxidation")

        final_mesh = Path(output_dir) / "thermal_oxidation_final"
        final_mesh_path = save_volume_mesh(
            geometry, final_mesh,
            floor_depth_um=recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM),
        )

        return {
            "final_mesh": final_mesh_path,
            "snapshots": recorder.snapshots,
        }
