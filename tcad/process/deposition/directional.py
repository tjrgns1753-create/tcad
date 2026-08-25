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

`calculateVisibility` default overridden to False -- real growth-shape
verification (this session), not just the top-surface |v|*t magnitude
check test_directional_deposition_growth_real.py already covered:

  ViennaPS's own default, calculateVisibility=True, was found to STALL
  growth at a small, GRID- AND TIME-DEPENDENT, NON-MONOTONIC fraction
  of the expected |v|*t for this project's own flat-window/vertical-
  source geometry (the only geometry this project's recipes build for
  deposition) -- e.g. grid_delta_um=0.05, direction=[0,1,0] (straight
  overhead, no tilt): growth matched exactly at t=0.5s (0.0500um) but
  then STAYED PINNED at exactly that value for t=1/2/4s (expected
  0.1/0.2/0.4um) -- not a slow approach to a limit, a hard stop. Swept
  grid_delta_um in {0.2, 0.15, 0.1, 0.075, 0.05, 0.02} at fixed t=4s:
  0.2 and 0.02 matched; 0.15 and 0.1 stalled at exactly 2 and 1 grid
  cells respectively; 0.05 stalled at 1 cell; 0.075 did not stall at
  all (matched). This grid-dependence is non-monotonic, consistent
  with a class of ViennaPS/ViennaLS numerical fragility this project
  has already documented elsewhere (see CLAUDE.md's "MakeTrench
  floating-point sensitivity" and the Phase 8 mesh-quality
  investigation) -- not something traceable to a single clean
  parameter threshold.

  calculateVisibility=False was tested across the exact same grid
  sweep at t=4s: every point matched |v|*t (0.0% relative error)
  except grid_delta_um=0.075 (12.3% over, a single outlier, same class
  of non-monotonic artifact, not chased further). Since this project's
  deposition recipes only ever build a flat, fully-exposed window
  under a non-tilted, straight-overhead source (`direction=[0,1,0]` or
  `[0,-1,0]` in every existing recipe/test) -- a geometry where real
  physical self-shadowing cannot occur at all -- there is no physical
  reason for `calculateVisibility=True`'s shadow/ray-tracing
  calculation to matter here, and it was actively harmful (up to 8x
  under-growth). Recipes that DO need real shadow calculation (a
  tilted source, or a re-entrant/overhung profile) can still opt back
  in via `calculate_visibility=True` in the recipe -- this default
  change does not remove the capability, only stops it from silently
  corrupting the common, simple case.
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

        if "material" in recipe:
            # Opt-in distinct-material tagging, same mechanism and same
            # default-off behavior as geometric_trench.py/bosch_drie.py:
            # without this key the deposit merges into whatever material
            # already sits on top (unchanged from before this existed).
            geometry.duplicateTopLevelSet(getattr(module.Material, recipe["material"]))

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
        # See isotropic.py's matching comment: "deposit_exclude_material"
        # (user-chosen growth exclusion) is deliberately distinct from
        # "mask_material" (unconditional mask/resist geometry tagging,
        # set by prepare_domain() on every recipe that has a mask).
        if "deposit_exclude_material" in recipe:
            model_kwargs["maskMaterial"] = getattr(
                module.Material, recipe["deposit_exclude_material"]
            )
        # Default False, not ViennaPS's own True: see module docstring
        # -- real-execution-verified to stall growth non-monotonically
        # for this project's flat-window/non-tilted-source geometry,
        # where real shadowing cannot occur anyway. Still overridable
        # per-recipe for geometries that genuinely need it.
        model_kwargs["calculateVisibility"] = recipe.get("calculate_visibility", False)

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
