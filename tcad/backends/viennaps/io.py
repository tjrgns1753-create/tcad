#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ViennaPS mesh I/O and snapshot recording helpers.

Extracted from the `snapshot()` closure and the final
`geometry.saveVolumeMesh(...)` call inside the original
run_viennaps_bosch(). Any process recipe (Bosch today; SF6/O2,
Fluorocarbon, TEOS, thermal oxidation, etc. in later phases) can reuse
these instead of re-implementing surface/volume mesh saving.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Union

PathLike = Union[str, Path]

DEFAULT_FLOOR_DEPTH_UM = 5.0
"""Fallback depth (um, below the wafer's y=0 top-surface datum that
MakeTrench establishes) that save_volume_mesh() guarantees is present as
real, triangulated material in the exported volume mesh, used whenever a
recipe doesn't specify one explicitly.

Wafer.silicon_depth_um (tcad/core/models.py) IS wired to this: every
ProcessStep.run() (all 13 implementations) calls
`save_volume_mesh(geometry, final_mesh, floor_depth_um=recipe.get(
"silicon_depth_um", DEFAULT_FLOOR_DEPTH_UM))`, and
tcad_2d_stagewise.py's recipe-building code populates
`recipe["silicon_depth_um"]` from `self.wafer.silicon_depth_um`. This
constant mirrors that field's own default purely so the two stay in
sync when no recipe key is present (e.g. recipes built without a Wafer
instance, such as most of tests/) — it is the value actually used
whenever `recipe["silicon_depth_um"]` is absent, not a placeholder.

Exists to counter a documented ViennaPS/ViennaLS limitation (see
CLAUDE.md, "Initial geometry / MakeTrench"): `Domain.saveVolumeMesh()`
(viennals::WriteVisualizationMesh, whose own header says it "should ONLY
BE USED FOR VISUALIZATION") only triangulates each level set's narrow
band in directions with INFINITE_BOUNDARY. For a semi-infinite Si
substrate (and any material stacked below the domain's topmost level
set) that band is only ~2*gridDelta wide regardless of gridDelta, so
without a floor the exported Si region collapses to a sliver a couple of
grid cells deep.
"""


def save_surface_mesh(domain, path: PathLike, add_material_ids: bool = True) -> str:
    """Save the domain's surface mesh (VTP). Returns the written path as str.

    Mirrors the original `geometry.saveSurfaceMesh(str(filename), True)`.
    """
    path_str = str(path)
    domain.saveSurfaceMesh(path_str, add_material_ids)
    return path_str


def _floored_copy_for_export(domain, floor_depth_um: float):
    """Return a DEEP COPY of `domain` with every level set intersected
    against a bounding box whose floor is at y = -floor_depth_um
    (absolute, fixed at the wafer's y=0 datum MakeTrench establishes —
    not relative to the current, possibly-etched/grown surface, so the
    floor stays put across a process flow regardless of how much the
    surface has moved).

    Does NOT mutate `domain` itself — the process-flow-visible geometry
    (ProcessStep.last_domain, any further Process() calls on it) is
    completely unaffected. Only this throwaway copy, used solely for this
    one saveVolumeMesh() export, is modified. Verified directly (not
    assumed): the original domain's raw level-set surfaces are bit-
    identical before and after this function runs.

    Every level set is floored, not just the one tagged Si — confirmed
    necessary by direct measurement (see CLAUDE.md): flooring only Si
    left a stacked SiO2 layer's own level set still extending to the
    floor depth unbounded (31% area error vs the correctly-floored
    result), because in ViennaPS's material-stacking representation a
    non-topmost material's level set itself implicitly wraps everything
    below it, inheriting the same narrow-band clipping Si has.

    The bounding box's lateral/top extent is measured from
    `domain.getBoundingBox()` (which — unlike the semi-infinite Si
    direction — already correctly reflects the real extent of bounded
    material such as the mask) plus a safety margin, not hardcoded, so
    this works across differing recipe geometry sizes without risking a
    silent top/side clip of real material.
    """
    import viennals as vls

    floored = domain.__class__(domain)  # ViennaPS Domain deep-copy constructor

    bbox = floored.getBoundingBox()
    x_min, x_max = bbox[0][0], bbox[1][0]
    y_max_existing = bbox[1][1]
    grid_delta = floored.getGridDelta()

    x_pad = max(x_max - x_min, 10 * grid_delta, 1.0)
    ceil_y = y_max_existing + max(10 * grid_delta, 1.0)
    floor_y = -floor_depth_um

    for ls in floored.getLevelSets():
        # Pre-expand before the boolean intersect: found necessary (this
        # session) for a level set that comes out of Process() narrower
        # than 2 layers wide (confirmed with a LOCOS mask/pad-oxide
        # geometry) -- ViennaLS's own internal auto-expand-then-continue
        # path for such a level set crashes inside the subsequent
        # BooleanOperation (IndexError: vector::_M_range_check) if not
        # pre-expanded explicitly here first. A no-op for every
        # already-verified geometry this project uses (Si+Mask,
        # Si+SiO2+Mask, Si+Polymer+Mask, Bosch mid-cycle): Expand() only
        # widens the narrow-band representation, it does not move the
        # actual interface, so the subsequent intersect still produces
        # the identical triangulated result for level sets that were
        # already wide enough.
        vls.Expand(ls, 3).apply()
        box = vls.Domain(ls)
        vls.MakeGeometry(
            box,
            vls.Box([x_min - x_pad, floor_y, 0.0], [x_max + x_pad, ceil_y, 0.0]),
        ).apply()
        vls.BooleanOperation(ls, box, vls.BooleanOperationEnum.INTERSECT).apply()

    return floored


def save_volume_mesh(
    domain, path: PathLike, floor_depth_um: float = DEFAULT_FLOOR_DEPTH_UM
) -> str:
    """Save the domain's volume mesh. Returns the *actual* written path.

    Verified against installed ViennaPS 4.6.2: `domain.saveVolumeMesh(path)`
    does not write to `path` literally — it appends "_volume.vtu" to
    whatever base name is given (confirmed by inspecting the output
    directory after a real call, not guessed from docs). This helper
    reports that real filename so callers (GUI log, mesh interface,
    tests) point at a file that actually exists.

    Before export, a floored COPY of `domain` is built (see
    `_floored_copy_for_export`) so the semi-infinite Si substrate (and
    every other material) is present as real triangulated volume down to
    `floor_depth_um`, instead of collapsing to ~2*gridDelta. `domain`
    itself is never modified by this call.
    """
    path_str = str(path)
    floored = _floored_copy_for_export(domain, floor_depth_um)
    floored.saveVolumeMesh(path_str)
    return f"{path_str}_volume.vtu"


class SnapshotRecorder:
    """Collects sequential surface-mesh snapshots into an output directory.

    Reproduces the original inline `snapshot(name)` closure:
        filename = out / f"{name}.vtp"
        geometry.saveSurfaceMesh(str(filename), True)
        snapshots.append(str(filename))
    """

    def __init__(self, output_dir: PathLike):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots: List[str] = []

    def capture(self, domain, name: str) -> str:
        filename = self.output_dir / f"{name}.vtp"
        path = save_surface_mesh(domain, filename, True)
        self.snapshots.append(path)
        return path
