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

    LOCOS mask erosion — root cause found, fixed, and SHIPPED (later
    session; supersedes the "not yet root-caused" note that used to be
    here — see CLAUDE.md, "LOCOS mask erosion — ROOT CAUSE FOUND AND
    VERIFIED FIXABLE" and its follow-up for the full investigation):

    Root cause: the mask sitting in direct contact with bare Si, with no
    pad-oxide buffer between them — not material identity, not
    mechanical parameters (both were separately ablation-tested and
    ruled out; retention was unchanged either way). Real fabs always
    grow a thin pad oxide before depositing the LOCOS mask specifically
    to buffer the thermal-expansion mismatch, and ViennaPS's own
    mask/oxide contact-mechanics solver apparently depends on that
    buffer too — this project's original geometry never had one.

    Fix: for LOCOS only, geometry is now built pad-oxide-first (Si ->
    MakePlane(..., addToExisting=True) pad SiO2 -> mask box placed with
    its bottom 1e-6um *inside* the pad oxide, the official
    locosOxidation.py example's own "contact epsilon" numerical-
    stability trick), instead of this project's normal MakeTrench-based
    mask-directly-on-Si construction. Mask retention measured 97-100%
    with this construction (was ~3.5%), verified against real ViennaPS
    4.6.2 runs, real oxide growth, and a real DevSim import of the
    result.

    This construction makes the pad oxide's own level set the union of
    itself and Si (ViennaPS's normal way of representing a material
    stack) — which would normally make Si vanish entirely from
    `saveVolumeMesh()`'s export (see CLAUDE.md for why: reverse-
    insertion-order "topmost wins" clipping, and why a ViennaLS boolean
    subtraction can't undo it — RELATIVE_COMPLEMENT/INTERSECT+INVERT
    reliably return empty once either operand has been through a
    UNION). Fixed at the export layer instead:
    `tcad.backends.viennaps.io.save_locos_volume_mesh()` recovers each
    material's true region with plain Python geometry (independent
    single-material exports + a top-surface clip), bypassing
    WriteVisualizationMesh's stacking resolution entirely. Only the
    LOCOS branch uses it — fin-style oxidation (no mask) is completely
    unaffected, still goes through the normal save_volume_mesh().
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import (
    DEFAULT_FLOOR_DEPTH_UM,
    SnapshotRecorder,
    save_locos_volume_mesh,
    save_volume_mesh,
)
from tcad.process.base import ProcessStep
from tcad.process.registry import register

#: Default pad-oxide thickness (um) grown before the LOCOS mask is
#: placed, when the recipe doesn't specify one. Floored at grid_delta
#: for the same reason ThermalOxidation floors its initial-oxide seed
#: below: a pad thinner than one grid cell cannot be resolved by the
#: level set, and the oxidation model's own auto-seed logic is not used
#: for this branch (a real, resolvable pad oxide already exists in the
#: geometry by the time Process() runs, unlike the fin/no-mask case).
#: 0.02um (20nm) matches typical real LOCOS pad-oxide thickness.
DEFAULT_PAD_OXIDE_THICKNESS_UM = 0.02


@register
class ThermalOxidation(ProcessStep):
    category = "oxidation"
    name = "thermal"
    display_name = "Thermal Oxidation"

    def _build_locos_geometry(self, recipe: Dict[str, Any], module):
        """Fresh-wafer LOCOS geometry: Si -> pad SiO2 (addToExisting) ->
        mask box with contact-epsilon overlap into the pad oxide. See
        module docstring for why this replaces the normal
        prepare_domain()/MakeTrench construction for LOCOS specifically.

        Only used when there is no inherited domain (this is a
        from-scratch construction, same restriction ProcessStep.
        prepare_domain() itself documents for its own trench-building
        branch — continuing LOCOS oxidation on top of an already-
        processed inherited domain is a different, unsupported case).

        Returns (geometry, materials, wrap_flags) where materials/
        wrap_flags describe geometry.getLevelSets() in insertion order,
        matching the shape tcad.backends.viennaps.io.
        save_locos_volume_mesh() expects.
        """
        import viennals as vls

        geometry = session.create_domain(
            grid_delta_um=recipe["grid_delta_um"],
            x_extent_um=recipe["x_extent_um"],
            y_extent_um=recipe["y_extent_um"],
        )

        si_material = module.Material.Si
        oxide_material = getattr(module.Material, recipe.get("oxide_material", "SiO2"))
        mask_material = getattr(module.Material, recipe["mask_material"])

        module.MakePlane(geometry, 0.0, si_material).apply()

        pad_oxide_um = recipe.get(
            "pad_oxide_thickness_um",
            max(DEFAULT_PAD_OXIDE_THICKNESS_UM, recipe["grid_delta_um"]),
        )
        module.MakePlane(geometry, pad_oxide_um, oxide_material, True).apply()

        # Mask box construction, matched to geometry's own just-created
        # grid (gridDelta/boundary conditions) so the level set can be
        # inserted into it -- getBoundaryConditions() is only safe to
        # call once the domain has at least one level set (confirmed:
        # segfaults on an empty Domain), which is why this comes after
        # the two MakePlane() calls above, not before.
        bcs = geometry.getBoundaryConditions()
        grid_delta = recipe["grid_delta_um"]
        half_x = recipe["x_extent_um"] / 2.0
        # y bounds here are only an HRLE allocation hint for this
        # throwaway box-building level set, not a physical floor (the
        # y axis is INFINITE_BOUNDARY per `bcs` regardless) -- the real
        # floor is applied later, at export time, exactly like every
        # other geometry in this project (see io.DEFAULT_FLOOR_DEPTH_UM).
        bounds = [-half_x, half_x, -1.0, recipe["y_extent_um"]]

        trench_width_um = round(recipe["mask_right_um"] - recipe["mask_left_um"], 9)
        window_half = trench_width_um / 2.0
        mask_height_um = max(recipe["pr_thickness_um"], 0.1)
        # "Contact epsilon": the official locosOxidation.py example's
        # own trick, placing the mask's bottom boundary numerically
        # INSIDE the pad oxide so Cartesian stencils unambiguously
        # resolve the mask/oxide contact (see CLAUDE.md).
        contact_eps = 1.0e-6

        left_ls = vls.Domain(bounds, bcs, grid_delta)
        left_geom = vls.MakeGeometry(
            left_ls,
            vls.Box(
                [-half_x, pad_oxide_um - contact_eps],
                [-window_half, pad_oxide_um + mask_height_um],
            ),
        )
        left_geom.setIgnoreBoundaryConditions([False, True, False])
        left_geom.apply()

        right_ls = vls.Domain(bounds, bcs, grid_delta)
        right_geom = vls.MakeGeometry(
            right_ls,
            vls.Box(
                [window_half, pad_oxide_um - contact_eps],
                [half_x, pad_oxide_um + mask_height_um],
            ),
        )
        right_geom.setIgnoreBoundaryConditions([False, True, False])
        right_geom.apply()

        vls.BooleanOperation(left_ls, right_ls, vls.BooleanOperationEnum.UNION).apply()
        # wrapLowerLevelSet=False: the mask is its own distinct,
        # bounded shape (two boxes), not a wrap of the pad oxide below
        # it -- confirmed necessary (see CLAUDE.md item 6 under "LOCOS
        # mask erosion"): wrapping the mask into the oxide here instead
        # made the mask's area get absorbed into SiO2 during Process().
        geometry.insertNextLevelSetAsMaterial(left_ls, mask_material, False)

        self.last_domain = geometry
        materials = [si_material, oxide_material, mask_material]
        wrap_flags = [False, True, False]
        return geometry, materials, wrap_flags

    def run(self, recipe: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
        module = session.require_viennaps()

        # LOCOS gets its own from-scratch geometry (pad-oxide-first,
        # see _build_locos_geometry and the module docstring) only when
        # building a fresh wafer -- an inherited domain (mid process
        # flow) falls back to the previous behavior: whatever geometry
        # was carried over, mask material tagged onto it as before.
        # Fin-style oxidation (no mask_material) is always the plain
        # trench geometry, fresh or inherited, exactly as before.
        is_fresh_locos = self._inherited_domain is None and "mask_material" in recipe
        if is_fresh_locos:
            geometry, locos_materials, locos_wrap_flags = self._build_locos_geometry(recipe, module)
        else:
            geometry = self.prepare_domain(recipe)

        model = module.Oxidation()

        model.setOxidant(getattr(module.OxidantType, recipe["oxidant"]))
        model.setTemperature(recipe["temperature_c"])
        model.setTime(recipe["time_hours"])

        if not is_fresh_locos:
            # Native-oxide seed the model auto-creates when no SiO2
            # layer exists (psOxidation.hpp) defaults to 0.002um
            # regardless of gridDelta. Below one grid cell, the level-set
            # can't resolve the seed interface: oxidation stalls at
            # t~0.1hr and the CFL solver fails to converge at longer
            # times (confirmed by raw level-set experiments, isolated
            # from saveVolumeMesh/DevSim). Floor it at gridDelta, same
            # as ViennaPS's own trenchOxidation.py example
            # (seed_thickness = max(oxideThickness, gridDelta)).
            # Not applicable to the fresh-LOCOS path: that geometry
            # already contains a real, resolvable pad-oxide SiO2 layer,
            # so there is no seed to create.
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
        floor_depth_um = recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM)
        if is_fresh_locos:
            # Normal save_volume_mesh() would drop Si entirely here —
            # see save_locos_volume_mesh's docstring and the module
            # docstring above for why.
            final_mesh_path = save_locos_volume_mesh(
                geometry, locos_materials, locos_wrap_flags, final_mesh,
                floor_depth_um=floor_depth_um,
            )
        else:
            final_mesh_path = save_volume_mesh(
                geometry, final_mesh, floor_depth_um=floor_depth_um,
            )

        return {
            "final_mesh": final_mesh_path,
            "snapshots": recorder.snapshots,
        }
