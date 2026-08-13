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

LOCOS mask/oxide elastic-coupling segfault — root cause and fix (this
session, superseding an earlier halfTrench=True workaround that changed
this project's trench-geometry coordinate convention and was never
fully physically validated; see CLAUDE.md history):

    Root cause (isolated by a single-variable ablation against the
    ORIGINAL, unmodified trench geometry -- no halfTrench, no extra
    pad-oxide layer): ViennaPS's OxidationMaskParameters defaults to
    contactMode=1 ("oneway"/kinematic mask contact). For this project's
    trench geometry, that contact mode's elastic solve diverges
    (confirmed: 16 non-converged solves, then a native access-violation
    crash, reproduced deterministically). Setting ONLY
    OxidationMaskParameters.contactMode=2 ("twoway"/elastic feedback --
    the same mode the official ViennaPS locosOxidation.py example uses,
    via its config.txt's maskContactMode="twoway"), with every other
    parameter left at ViennaPS's own default, is sufficient by itself:
    0 solver failures, real oxide growth, identical geometry to setting
    the full official example's parameter set on top. No geometry
    change was needed or used.

    The additional mechanics/pressure/stokes/coupling iteration and
    tolerance settings below match the official example's own values
    (not fabricated) for headroom on grids/recipes not covered by the
    ablation above, since only contactMode was proven necessary at the
    tested recipe -- they are not each individually re-verified as
    load-bearing.

    Separate, still-open issue, NOT fixed by contactMode=2 (verified:
    identical ~99% mask-area loss with or without it, and independent of
    the initial-oxide-seed value below): the mask erodes almost
    completely during LOCOS oxidation in this project's geometry. Not
    yet root-caused. Do not treat LOCOS mask preservation as physically
    validated.
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
        # Plain trench geometry for both fin and LOCOS -- see module
        # docstring above for why LOCOS no longer needs halfTrench=True.
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

            # LOCOS mask/oxide elastic-coupling fix — see module
            # docstring for the root cause and the ablation that found
            # contactMode=2 alone sufficient. The rest of this block
            # matches the official locosOxidation.py example's own
            # values, not fabricated, for headroom beyond the tested
            # recipe.
            import viennals as vls

            mask_params = vls.OxidationMaskParameters()
            mask_params.contactMode = 2
            model.setMaskParameters(mask_params)
            model.setMechanicsIterations(300)
            model.setMechanicsTolerance(5e-3)
            model.setPressureIterations(500)
            model.setPressureTolerance(1e-3)
            model.setStokesIterations(500)
            model.setStokesTolerance(1e-3)
            model.setCouplingIterations(100)
            model.setCouplingTolerance(2e-2)
            model.setMaskCouplingIterations(30)
            model.setMaskCouplingTolerance(1e-2)

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
