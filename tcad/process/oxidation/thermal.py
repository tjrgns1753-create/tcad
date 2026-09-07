#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Thermal Oxidation — CORE process. Plain fin-style oxidation of whatever
Si surface is currently exposed: no mask, no mask/oxide mechanics, no
LOCOS geometry. If the simulator's core process flow (wafer -> litho ->
etch -> deposition -> oxidation -> doping -> anneal -> metallization ->
DevSim) needs to run with LOCOS absent or broken, this model is
unaffected -- see tcad/process/oxidation/locos.py for the separate,
optional/advanced LOCOS model this used to be fused with.

Real API used (verified against installed ViennaPS 4.6.2 — vps.Oxidation
is a builder-style ProcessModel, not a flat-kwarg constructor):

    model = vps.Oxidation()                      # no-arg constructor
    model.setOxidant(vps.OxidantType.Dry | Wet)   # docstring: "Oxidant species"
    model.setTemperature(temperatureC)            # docstring: "in °C (800-1200 °C)"
    model.setTime(timeHr)                         # docstring: "Total oxidation time in hours"
    model.setPressure(pressureAtm)                # optional, docstring: "in atm"
    model.setOxideMaterial(material)               # optional override
    model.setSiliconMaterial(material)              # optional override
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

2026-09-07, LOCOS separation: this model used to ALSO run LOCOS
(vps.Oxidation.setMaskMaterial()'s own docstring states it "activates
LOCOS physics" — mask-bending/bird's-beak mechanics — so a single
ProcessStep dispatched on whether the recipe carried `mask_material`).
That coupling is removed: this file now does exactly one thing (plain
fin-style oxidation), registered as `("oxidation", "thermal")`, always
the CORE process. LOCOS is `("oxidation", "locos")`, a separate
ProcessStep in locos.py, registered as an ADVANCED/OPTIONAL process —
selecting "Thermal oxidation" here can no longer reach any LOCOS-only
geometry, mask, or mask/oxide elastic-contact code, and this file no
longer imports or depends on anything LOCOS-specific. Nothing in this
file's own logic changed; only the mask_material branch (and the
helper methods it alone used) moved out.
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
        geometry = self.prepare_domain(recipe)

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
        # Floor it at gridDelta, same as ViennaPS's own
        # trenchOxidation.py example (seed_thickness =
        # max(oxideThickness, gridDelta)).
        model.setInitialOxideThickness(max(0.002, recipe["grid_delta_um"]))

        if "pressure_atm" in recipe:
            model.setPressure(recipe["pressure_atm"])
        if "oxide_material" in recipe:
            model.setOxideMaterial(getattr(module.Material, recipe["oxide_material"]))
        if "silicon_material" in recipe:
            model.setSiliconMaterial(getattr(module.Material, recipe["silicon_material"]))

        recorder = SnapshotRecorder(output_dir)
        recorder.capture(geometry, "000_initial")

        module.Process(geometry, model).apply()

        recorder.capture(geometry, "001_thermal_oxidation")

        final_mesh = Path(output_dir) / "thermal_oxidation_final"
        final_mesh_path = save_volume_mesh(
            geometry, final_mesh, floor_depth_um=recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM),
        )

        return {
            "final_mesh": final_mesh_path,
            "snapshots": recorder.snapshots,
        }
