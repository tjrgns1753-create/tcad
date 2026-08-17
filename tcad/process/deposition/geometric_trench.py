#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Geometric (non-iterative) non-conformal deposition — a thin recipe
wrapper around ViennaPS's GeometricTrenchDeposition primitive.

Unlike every other model in this package, this is NOT a rate x time
advection simulation: it is a one-shot GEOMETRIC stamp (ViennaLS's
GeometricAdvectDistribution machinery, the same family BoxDistribution/
SphereDistribution belong to). It exists to model position-dependent
("non-conformal") coating thickness — e.g. sputtered/PVD films that
coat the field/mask top more thickly than a trench floor — without
running a real flux/transport simulation.

Real API used (verified against installed ViennaPS 4.6.2 via
`vps.GeometricTrenchDeposition.__init__.__doc__`, cross-checked against
ViennaPS's own C++ source — `include/viennaps/models/
psGeometricDistributionModels.hpp`'s `impl::TrenchDistribution`, fetched
from github.com/ViennaTools/ViennaPS — since the Python binding's
parameter names alone (trenchWidth, trenchDepth, depositionRate,
bottomMed, a, b, n) do not explain what they do):

    vps.GeometricTrenchDeposition(
        trenchWidth, trenchDepth, depositionRate, bottomMed, a, b, n,
    )

What each parameter actually does, read from `TrenchDistribution::
getSignedDistance` and `::getBounds` directly (not guessed):

  - `trenchWidth`: stored by the constructor but READ NOWHERE ELSE in
    the class (confirmed by inspecting every method body: the
    constructor, getSignedDistance, getBounds, prepare, and
    useSurfacePointId). It has zero effect on the result. This wrapper
    still has to pass a value (the C++ constructor requires it) but
    does not expose it as a recipe key, since exposing a knob that
    silently does nothing would be its own trap.
  - `depositionRate`: NOT a physical rate. `getBounds()` returns
    `[-depositionRate, +depositionRate]` per axis — it is the
    half-width of the geometric search box the underlying
    GeometricAdvectDistribution algorithm uses to look for candidate
    surface points. It must be set comfortably larger than the largest
    local thickness the a/b/n/bottomMed formula can produce, or the
    result is WRONG — verified directly (not assumed): setting it
    smaller than the true required thickness does not clip cleanly, it
    produces a visibly LARGER, incorrect deposit (measured ~2.65um
    where ~0.35um was expected, in an isolated probe). So this wrapper
    requires it explicitly rather than defaulting it, and the caller
    must size it generously.
  - `trenchDepth`, `bottomMed`, `a`, `b`, `n` together define the
    thickness profile as a function of a surface point's own y
    (`initial[D-1]` in the source), with a fixed reference at y=0 (this
    project's wafer-surface datum):
        if |y + trenchDepth| < gridDelta:  thickness = bottomMed
        else:                              thickness = a*(1-|y|/trenchDepth)^n + b
    i.e. thickness is LARGEST (= a+b) at y=0 and decays via the power
    law with |y| in EITHER direction (up onto a mask/raised feature, or
    down into a trench) — n shapes the decay curve — with a SEPARATE,
    explicit `bottomMed` value for whatever sits within one grid cell
    of y=-trenchDepth specifically (matching a real trench floor, if
    `trenchDepth` is set to the actual trench depth in the recipe).
    Verified directly against a real 2D trench+mask geometry: with
    a=0.3, b=0.05, n=2, mask top at y=0.5 measured 0.1247 (predicted
    0.3*(1-0.5)^2+0.05=0.125), trench floor at y=-1.0 (trenchDepth=1.0)
    measured 0.0998 (predicted bottomMed=0.1) — both within grid
    resolution.
  - The model has NO mask-material concept at all (no such parameter
    exists on the constructor) — it deposits everywhere in the domain
    purely by y-position, not by what material a point currently is.
  - No `Process()` duration is used: ViennaPS's own test suite
    (`tests/geometricProcessStrategy`) documents "geometric processes
    typically have zero duration", and this was confirmed directly —
    `Process(geometry, model).apply()` with no duration argument runs
    correctly.
  - Material tagging: calling this model directly, with no other step
    first, MERGES the new geometry into whatever material already sits
    at the top of the domain's material stack (verified: materials
    list was unchanged, Si's own level set simply grew) — it does NOT
    introduce a new material on its own. This mirrors every other model
    in this package (teos.py, single_particle_cvd.py, ...), none of
    which distinguish the deposit as a new material either, so this
    file's default behavior matches existing convention. An optional
    `material` recipe key opts into the distinct-material path, using
    the same `duplicateTopLevelSet()` call `bosch_drie.py` already uses
    for its own polymer layer — verified this DOES give the deposit its
    own separately-tagged, separately-measurable region.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import DEFAULT_FLOOR_DEPTH_UM, SnapshotRecorder, save_volume_mesh
from tcad.process.base import ProcessStep
from tcad.process.registry import register


@register
class GeometricTrenchDeposition(ProcessStep):
    category = "deposition"
    name = "geometric_trench"
    display_name = "Non-Conformal Deposition (geometric trench distribution)"

    def run(self, recipe: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
        module = session.require_viennaps()

        # Fresh wafer normally; the previous step's domain when this
        # step is part of a process flow (see ProcessStep.prepare_domain).
        geometry = self.prepare_domain(recipe)

        recorder = SnapshotRecorder(output_dir)
        recorder.capture(geometry, "000_initial")

        if "material" in recipe:
            # Opt-in distinct-material tagging — see module docstring.
            # Default (key absent) matches every other deposition model
            # in this package: the deposit merges into the existing top
            # material, no behavior change for any recipe not using this.
            geometry.duplicateTopLevelSet(getattr(module.Material, recipe["material"]))

        model = module.GeometricTrenchDeposition(
            0.0,  # trenchWidth -- confirmed dead in the underlying
                  # algorithm (see module docstring); no recipe key.
            recipe["reference_depth_um"],
            recipe["deposition_rate_um"],
            recipe["bottom_med_um"],
            recipe["a_um"],
            recipe["b_um"],
            recipe.get("n", 1.0),
        )

        module.Process(geometry, model).apply()

        recorder.capture(geometry, "001_geometric_trench")

        final_mesh = Path(output_dir) / "geometric_trench_final"
        final_mesh_path = save_volume_mesh(
            geometry, final_mesh,
            floor_depth_um=recipe.get("silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM),
        )

        return {
            "final_mesh": final_mesh_path,
            "snapshots": recorder.snapshots,
        }
