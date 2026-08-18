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

import tempfile
import warnings
import weakref
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

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


#: Domains whose exports must go through save_locos_volume_mesh() rather
#: than the normal WriteVisualizationMesh path, keyed by id(domain).
#: See register_locos_export() for why this is a side table rather than
#: an attribute on the domain itself.
_LOCOS_EXPORT_HINTS: dict = {}
_LOCOS_EXPORT_REFS: dict = {}

#: Deep copies of a LOCOS domain's level sets as they stood BEFORE
#: _make_locos_domain_chainable() unioned the mask into the oxide,
#: keyed by id(domain) exactly like _LOCOS_EXPORT_HINTS (and cleared by
#: the same weakref callback). See register_locos_unwrapped() for why a
#: second LOCOS oxidation needs these rather than the live domain.
_LOCOS_UNWRAPPED: dict = {}


def register_locos_export(domain, materials: List[Any], wrap_flags: List[bool]) -> None:
    """Record that `domain` carries ViennaPS "wrap" material stacking, so
    every later save_volume_mesh() on it delegates to
    save_locos_volume_mesh() with these `materials`/`wrap_flags` instead
    of exporting through WriteVisualizationMesh (which would silently
    drop the wrapped-under materials — see save_locos_volume_mesh's
    docstring).

    Exists so a LATER, unrelated ProcessStep that inherits this domain
    exports it correctly without needing to know anything about LOCOS:
    none of the 13+ ProcessStep.run() implementations change, they keep
    calling save_volume_mesh() exactly as before.

    A side table keyed by id(domain) rather than an attribute set on the
    domain: confirmed directly (not assumed) that the pybind11
    viennaps.d2.Domain class has no py::dynamic_attr(), so
    `domain.anything = ...` raises AttributeError. id() is safe as a key
    here only because the weakref below removes the entry the moment the
    domain is collected, so an id can never be silently reused by a
    different, unrelated object while an entry is live. The domain
    object's identity is preserved across Process() calls (they mutate
    it in place) — verified against real ViennaPS 4.6.2 across a
    three-step chain, which is what makes the lookup work for a
    downstream step at all.
    """
    key = id(domain)
    _LOCOS_EXPORT_HINTS[key] = (list(materials), list(wrap_flags))

    def _forget(_ref, key=key):
        _LOCOS_EXPORT_HINTS.pop(key, None)
        _LOCOS_EXPORT_REFS.pop(key, None)
        _LOCOS_UNWRAPPED.pop(key, None)

    _LOCOS_EXPORT_REFS[key] = weakref.ref(domain, _forget)


def register_locos_unwrapped(domain, level_sets: List[Any]) -> None:
    """Stash deep copies of `domain`'s level sets as they stand right
    now — with the mask still UNWRAPPED — for a later second LOCOS
    oxidation to rebuild from.

    Why a stash is needed at all: a LOCOS domain has to satisfy two
    mutually exclusive requirements. ViennaLS's Advect (every
    vps.Process() call) requires the LAST level set to contain all the
    others, so a LOCOS domain is only safe to chain from once its mask
    has been unioned with the oxide below it
    (_make_locos_domain_chainable). But vps.Oxidation()'s own oxide-band
    detection requires a DISTINCT oxide band between level sets, which
    that same union destroys — so a second LOCOS oxidation on the
    re-wrapped domain finds "no oxide nodes after buildNodes()",
    produces a garbage displacement and hangs.

    Both can be satisfied at once by keeping the re-wrap for chaining
    and giving a second oxidation its own rebuilt, unwrapped-mask
    domain — which is what these copies are for. Verified by real
    execution (ViennaPS 4.6.2, 10hr dry LOCOS at 1000C, grid 0.2um):
    the second oxidation then completes with real growth of the same
    order as the first (SiO2 +0.1751 um^2 vs the first step's +0.1058;
    Si genuinely consumed, -0.0641 vs -0.0819) and all three materials
    preserved. The shipped chaining test's own 0.02hr recipe is far too
    short to see this — at that time BOTH oxidations move SiO2 area by
    ~0, below the grid's own resolution.

    Copies rather than references because the live level sets are
    mutated in place, first by the re-wrap and then by every later
    chained step; these must hold the post-oxidation, pre-re-wrap state.

    Call this BEFORE the re-wrap, then `seal_locos_unwrapped()` after —
    see that function for why the stash needs a staleness fingerprint.
    """
    import viennals as vls

    _LOCOS_UNWRAPPED[id(domain)] = {
        "level_sets": [vls.Domain(ls) for ls in level_sets],
        "fingerprint": None,
    }


def seal_locos_unwrapped(domain) -> None:
    """Record what `domain` looks like right now, so a later rebuild can
    tell whether anything has modified it since.

    Why this matters: the stashed copies are only a faithful
    reconstruction of the domain as long as NOTHING has run on it since
    they were taken. Any intervening step (an etch, a deposition, a
    fin-style oxidation) mutates the live level sets in place while the
    stash keeps the older state — so rebuilding from the stash after
    one of those would silently discard that step's effect and produce
    a plausible-looking result from the wrong geometry.

    The fingerprint is each level set's point count, taken immediately
    after the re-wrap (the state a chained step inherits). It is a
    heuristic, not a proof of identity: a step that changed the geometry
    while leaving every count identical would slip through. In practice
    any real advection changes them, and the failure it does catch —
    silently oxidizing stale geometry — is the one worth refusing over.
    """
    entry = _LOCOS_UNWRAPPED.get(id(domain))
    if entry is None:
        return
    entry["fingerprint"] = tuple(
        ls.getNumberOfPoints() for ls in domain.getLevelSets()
    )


def locos_unwrapped_level_sets(domain) -> Optional[List[Any]]:
    """The unwrapped level-set copies stashed for `domain`, or None.

    Returns None if nothing was stashed, OR if `domain` has been
    modified since the stash was sealed (see seal_locos_unwrapped) —
    the caller must treat both as "cannot rebuild" rather than
    proceeding from geometry that no longer matches.

    Returns the stored copies directly. A caller that inserts them into
    a domain (which mutates them) and may need the originals again must
    copy them itself — the one production caller rebuilds a throwaway
    domain per oxidation, so it does not.
    """
    entry = _LOCOS_UNWRAPPED.get(id(domain))
    if entry is None:
        return None
    current = tuple(ls.getNumberOfPoints() for ls in domain.getLevelSets())
    if entry["fingerprint"] is not None and current != entry["fingerprint"]:
        return None
    return entry["level_sets"]


def is_locos_registered(domain) -> bool:
    """Whether `domain` was passed to register_locos_export().

    Unlike `_locos_export_hint`, this answers the plain question "did a
    LOCOS step produce this domain" without also requiring the recorded
    materials list to still line up with the current level-set count —
    a caller asking whether some operation is safe on a LOCOS-derived
    domain needs the former, not the latter.
    """
    return id(domain) in _LOCOS_EXPORT_HINTS


def _locos_export_hint(domain) -> Optional[Tuple[List[Any], List[bool]]]:
    """The (materials, wrap_flags) registered for `domain`, or None."""
    hint = _LOCOS_EXPORT_HINTS.get(id(domain))
    if hint is None:
        return None
    # Guard against a level set having been added/removed since
    # registration: the lists must still describe getLevelSets() 1:1, or
    # save_locos_volume_mesh() would raise. Fall back to the normal
    # export (plus its missing-material warning) rather than crash a
    # step that is otherwise fine.
    materials, wrap_flags = hint
    try:
        if len(list(domain.getLevelSets())) != len(materials):
            return None
    except Exception:
        return None
    return materials, wrap_flags


def save_surface_mesh(domain, path: PathLike, add_material_ids: bool = True) -> str:
    """Save the domain's surface mesh (VTP). Returns the written path as str.

    Mirrors the original `geometry.saveSurfaceMesh(str(filename), True)`.
    """
    path_str = str(path)
    domain.saveSurfaceMesh(path_str, add_material_ids)
    return path_str


def _floored_copy_for_export(domain, floor_depth_um: float, bounds_hint=None):
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

    The bounding box's lateral extent is measured from
    `domain.getBoundingBox()` (which — unlike the semi-infinite Si
    direction — already correctly reflects the real extent of bounded
    material such as the mask, for every topology this project's normal
    process-step export uses) plus a safety margin, not hardcoded, so
    this works across differing recipe geometry sizes without risking a
    silent top/side clip of real material.

    bounds_hint : optional (x_min, x_max) OVERRIDE for the lateral
        padding basis, bypassing `domain.getBoundingBox()`'s own x-range
        for that purpose (y still comes from the real bbox). Needed by
        `_export_single_level_set`'s isolated single-material export:
        confirmed by direct measurement, not assumed, that padding
        relative to a NARROW material's own tight bbox (which is exactly
        what `getBoundingBox()` on a genuinely-single-level-set domain
        correctly reports) collapses the boolean intersect below to
        EMPTY — even though that same tight bbox is completely accurate.
        The fix is not a wrong bbox, it's the wrong basis to pad from:
        the padding needs to be relative to the domain's TRUE total
        extent (every existing whole-domain caller already gets this for
        free, since `getBoundingBox()` on a multi-level-set domain that
        follows this project's own last-level-set-wraps-everything
        convention already equals the total extent). Every existing
        caller omits this and is completely unaffected.
    """
    import viennals as vls

    floored = domain.__class__(domain)  # ViennaPS Domain deep-copy constructor

    bbox = floored.getBoundingBox()
    if bounds_hint is None:
        x_min, x_max = bbox[0][0], bbox[1][0]
    else:
        x_min, x_max = bounds_hint
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


def _warn_if_materials_missing_from_export(domain, mesh_path: str) -> None:
    """Sanity check: every material present in `domain` should have at
    least one triangle in the exported mesh at `mesh_path`. Warns
    (never raises — a diagnostic must never break a real export it
    can't itself explain) if one doesn't.

    Exists because ViennaLS's WriteVisualizationMesh (what
    saveVolumeMesh() calls) resolves overlapping level sets by
    insertion order ("topmost/last-inserted wins"), which can silently
    drop an entire material from the export for certain domain
    topologies. Confirmed real and reproducible (this session — see
    CLAUDE.md's LOCOS process-flow-chaining investigation): a domain
    built with ViennaPS's own material "wrap" stacking
    (`insertNextLevelSetAsMaterial(..., wrapLowerLevelSet=True)`, which
    `MakePlane(..., addToExisting=True)` also uses internally) can,
    after a FURTHER `Process()` call from a later, unrelated
    ProcessStep, export a mesh through this NORMAL path that drops one
    or more materials entirely — reproduced directly: a fresh LOCOS
    oxidation step's own mesh has all 3 materials (via
    save_locos_volume_mesh(), the fix for THAT specific export), but
    chaining a plain directional etch onto its `last_domain` and
    calling the NORMAL save_volume_mesh() for THAT step's own export
    dropped SiO2 and Mask entirely, mislabeling a small residual region
    as Si. This project does not yet have a general fix for this (the
    fix would need every ProcessStep to know whether its inherited
    domain requires save_locos_volume_mesh()-style export, a larger
    architectural change not made this session) — this check exists so
    a future occurrence is visible instead of silent.
    """
    try:
        domain_materials = {int(m) for m in domain.getMaterialsInDomain()}
    except Exception:
        return

    if not domain_materials:
        return

    try:
        import meshio

        mesh = meshio.read(mesh_path)
        triangle_block = next((c for c in mesh.cells if c.type == "triangle"), None)
        if triangle_block is None:
            exported_materials: set = set()
        else:
            block_index = mesh.cells.index(triangle_block)
            exported_materials = {int(t) for t in mesh.cell_data["Material"][block_index]}
    except Exception:
        return

    missing = domain_materials - exported_materials
    if missing:
        warnings.warn(
            f"save_volume_mesh(): the exported mesh {mesh_path} is missing "
            f"{len(missing)} material(s) that ARE present in the domain "
            f"(material tag(s) {sorted(missing)}). This is a known ViennaLS "
            f"WriteVisualizationMesh limitation for certain wrapped/stacked "
            f"level-set topologies (e.g. a process step chained onto "
            f"LOCOS-produced geometry) — see CLAUDE.md. The exported mesh may "
            f"be missing real material regions.",
            RuntimeWarning,
            stacklevel=3,
        )


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

    If `domain` was registered via register_locos_export() (i.e. it
    carries ViennaPS "wrap" material stacking, which this export path
    cannot resolve correctly), this delegates to
    save_locos_volume_mesh() instead. That is what lets a downstream
    ProcessStep inheriting a LOCOS-built domain export it correctly
    while still just calling save_volume_mesh() like every other step.

    After export, warns (does not raise) if a material present in
    `domain` has zero triangles in the written mesh — see
    `_warn_if_materials_missing_from_export` for why this can happen
    and what it means.
    """
    hint = _locos_export_hint(domain)
    if hint is not None:
        materials, wrap_flags = hint
        return save_locos_volume_mesh(
            domain, materials, wrap_flags, path, floor_depth_um=floor_depth_um
        )

    path_str = str(path)
    floored = _floored_copy_for_export(domain, floor_depth_um)
    floored.saveVolumeMesh(path_str)
    out_path = f"{path_str}_volume.vtu"
    _warn_if_materials_missing_from_export(domain, out_path)
    return out_path


def _read_triangle_mesh(path: PathLike) -> Tuple[Any, List[List[int]]]:
    import meshio

    mesh = meshio.read(str(path))
    triangle_block = next((c for c in mesh.cells if c.type == "triangle"), None)
    if triangle_block is None:
        return mesh.points, []
    return mesh.points, [[int(i) for i in tri] for tri in triangle_block.data]


def _union_bounding_box(domain) -> Tuple[float, float, float, float]:
    """Return (x_min, x_max, y_min, y_max): the TRUE union bounding box
    across every level set in `domain`.

    `domain.getBoundingBox()` does NOT return this for a multi-level-set
    domain — confirmed directly (not assumed): on a real 4-material
    domain (materials occupying disjoint lateral regions, none wrapping
    another), it returned only the LAST-inserted level set's own bbox,
    not the union. This function instead isolates each level set into
    its own single-level-set probe domain — whose own `getBoundingBox()`
    was confirmed accurate for a genuinely-single-level-set domain — and
    takes the min/max across all of them.
    """
    bcs = domain.getBoundaryConditions()
    grid_delta = domain.getGridDelta()

    import viennals as vls
    from tcad.backends.viennaps.session import require_viennaps

    # Any material works for this probe: it tags a throwaway domain used
    # only to read back getBoundingBox(), then discarded — the tag value
    # itself is never inspected. Si is always a valid enum member.
    probe_material = require_viennaps().Material.Si

    x_min = x_max = y_min = y_max = None
    for level_set in domain.getLevelSets():
        # Bounds are irrelevant here (only used to query this one level
        # set's own true extent, never exported), so a huge placeholder
        # box avoids clipping any real geometry.
        probe = domain.__class__([-1e6, 1e6, -1e6, 1e6], bcs, grid_delta)
        probe.insertNextLevelSetAsMaterial(vls.Domain(level_set), probe_material, False)
        bbox = probe.getBoundingBox()
        lo, hi = bbox[0], bbox[1]
        x_min = lo[0] if x_min is None else min(x_min, lo[0])
        x_max = hi[0] if x_max is None else max(x_max, hi[0])
        y_min = lo[1] if y_min is None else min(y_min, lo[1])
        y_max = hi[1] if y_max is None else max(y_max, hi[1])

    return x_min, x_max, y_min, y_max


def _export_single_level_set(
    domain, level_set, material, floor_depth_um: float, bounds_hint=None
):
    """Export ONE level set from `domain` in complete isolation: a fresh
    throwaway Domain containing only a copy of this level set, tagged
    `material`, run through the normal floored save_volume_mesh() path.

    Because no other level set shares this throwaway domain, the result
    is that level set's TRUE triangulated region — uncontaminated by
    ViennaLS's insertion-order material-stacking ("topmost/last-inserted
    wins") resolution that WriteVisualizationMesh applies whenever
    multiple level sets share one domain. This is the building block
    save_locos_volume_mesh() uses to recover a wrapped
    (wrapLowerLevelSet=True, e.g. from MakePlane(..., addToExisting=True))
    material's real region: export the wrapping material in isolation
    (it still geometrically contains whatever it wraps — isolation alone
    doesn't undo that), export the wrapped-under material in isolation
    too, then clip the two against each other in plain Python (see
    save_locos_volume_mesh's docstring for why a ViennaLS boolean
    subtraction cannot do this instead).

    bounds_hint : optional (x_min, x_max, y_max) — the domain's TRUE
        union extent (see `_union_bounding_box`), computed once by a
        caller that isolates multiple level sets from the same domain
        (e.g. `save_locos_volume_mesh`'s own loop) to avoid recomputing
        it per level set. Computed internally via `_union_bounding_box`
        if omitted.

        This MUST be the domain's union extent, not `level_set`'s own,
        and for a subtler reason than "the isolated domain needs to be
        wide enough" (confirmed by direct measurement — widening the
        isolated domain's own declared construction bounds ALONE does
        NOT fix this): `_floored_copy_for_export`'s floor-box padding is
        computed relative to its own `getBoundingBox()` reading, which
        for a domain holding exactly one (narrow, laterally-bounded)
        level set correctly reports that level set's own TIGHT extent —
        and padding relative to a narrow material's own tight bbox
        collapses the subsequent boolean intersect to EMPTY (0 points),
        even though that tight bbox is itself completely accurate. This
        is why the union extent is threaded through as `bounds_hint` to
        `_floored_copy_for_export` below, not just used to size `single`.
        Every existing whole-domain export gets the correct padding
        basis "for free," since `getBoundingBox()` on a multi-level-set
        domain that follows this project's own last-level-set-wraps-
        everything convention already equals the true total extent — a
        laterally narrow, non-wrapped material in isolation (e.g. a gate
        electrode spanning only the channel width) is what first breaks
        that assumption.
    """
    bcs = domain.getBoundaryConditions()
    grid_delta = domain.getGridDelta()
    if bounds_hint is None:
        x_min, x_max, _y_min, y_max = _union_bounding_box(domain)
    else:
        x_min, x_max, y_max = bounds_hint

    import viennals as vls

    single = domain.__class__(
        [x_min, x_max, -floor_depth_um - 1.0, y_max + 1.0], bcs, grid_delta
    )
    single.insertNextLevelSetAsMaterial(vls.Domain(level_set), material, False)

    # Floor + export directly (not via save_volume_mesh()) so the floor
    # box's lateral padding uses `bounds_hint` (the domain's true union
    # extent) rather than being re-derived from this isolated, single
    # -material domain's own tight bbox — see the bounds_hint note
    # above. Also correctly bypasses save_volume_mesh()'s registered
    # -LOCOS-hint check and post-export material-completeness warning,
    # neither of which applies to this internal, deliberately single
    # -material, throwaway domain.
    floored = _floored_copy_for_export(single, floor_depth_um, bounds_hint=(x_min, x_max))
    with tempfile.TemporaryDirectory() as tmp:
        path_str = str(Path(tmp) / "single")
        floored.saveVolumeMesh(path_str)
        return _read_triangle_mesh(f"{path_str}_volume.vtu")


def _top_lookup(points, triangles, grid_delta: float, x_min: float, x_max: float):
    """Per-x-column top-y lookup table built from `triangles`' own
    vertices, nearest-neighbor-filled for any column no vertex happens
    to land in.

    The fill matters: a coarse grid can leave some x-bins untouched by
    any triangle vertex; left at a low sentinel, such a bin would make
    the "is this point above the surface here" clip test in
    save_locos_volume_mesh accept everything in that column
    unconditionally, wrongly keeping triangles that should have been
    clipped (found and fixed during this function's own verification —
    see CLAUDE.md, LOCOS mask erosion investigation).
    """
    import numpy as np

    n_bins = int(round((x_max - x_min) / grid_delta)) + 2
    tops = np.full(n_bins, -1e18)
    for tri in triangles:
        for idx in tri:
            x, y = points[idx][0], points[idx][1]
            b = max(0, min(n_bins - 1, int((x - x_min) / grid_delta)))
            tops[b] = max(tops[b], y)

    valid = tops > -1e17
    if valid.any() and not valid.all():
        idx_valid = np.flatnonzero(valid)
        for i in range(n_bins):
            if not valid[i]:
                nearest = idx_valid[np.argmin(np.abs(idx_valid - i))]
                tops[i] = tops[nearest]

    def lookup(x: float) -> float:
        b = max(0, min(n_bins - 1, int((x - x_min) / grid_delta)))
        return float(tops[b])

    return lookup


def save_locos_volume_mesh(
    domain,
    materials: List[Any],
    wrap_flags: List[bool],
    path: PathLike,
    floor_depth_um: float = DEFAULT_FLOOR_DEPTH_UM,
    dedupe_materials: Optional[List[Any]] = None,
) -> str:
    """Save a volume mesh for a domain built with ViennaPS's material
    "wrap" stacking WITHOUT losing a wrapped-under material entirely,
    unlike the normal save_volume_mesh()/WriteVisualizationMesh path.

    Background (see CLAUDE.md, "LOCOS mask erosion — ROOT CAUSE FOUND
    AND VERIFIED FIXABLE"): fixing LOCOS mask erosion requires building
    a pad-oxide layer via `MakePlane(..., addToExisting=True)`
    (`insertNextLevelSetAsMaterial(..., wrapLowerLevelSet=True)`
    underneath), which makes the pad oxide's own level set a UNION of
    itself and the silicon beneath it — that is simply how ViennaPS
    represents a stack of materials. `WriteVisualizationMesh` (what
    `saveVolumeMesh()` calls) resolves overlapping level sets by
    processing them in reverse insertion order, each claiming whatever
    region isn't already claimed by a later-inserted material — so with
    the oxide's region now a strict superset of Si's, plain
    `saveVolumeMesh()` gives 100% of the shared region to the
    last-inserted material and Si triangulates to nothing.

    The obvious fix — subtract Si's region from the oxide's wrapped
    region via a ViennaLS boolean op (RELATIVE_COMPLEMENT, or INTERSECT
    with an inverted operand) — does not work: verified directly (see
    CLAUDE.md) that ViennaLS reliably returns an EMPTY level set from
    either operation whenever ONE of the two operands has ever been
    through a UNION, which every wrapped level set has by definition.
    This is a ViennaLS Python-API limitation, not something fixable by
    operand order or pre-processing (Prune/Expand were tried, no
    effect).

    This function instead resolves each level set's TRUE region with
    plain Python geometry, entirely bypassing ViennaLS's broken boolean
    machinery and WriteVisualizationMesh's stacking resolution:
      1. Export every level set of `domain` in complete isolation (see
         `_export_single_level_set`) — for a wrapped level set this
         still includes whatever it wraps, since isolation alone
         doesn't undo the union baked into its own geometry.
      2. Process level sets in insertion order. For each one marked
         `wrapped` in `wrap_flags`, discard every triangle whose
         centroid is not strictly above the running top-surface lookup
         of every TRUE region claimed by earlier (lower-index) level
         sets — i.e. keep only the part of its region that ISN'T
         already Si's (or an earlier wrapped material's true region).
      3. Merge the surviving triangles from every level set into one
         mesh, tagged per `materials`.

    materials[i] / wrap_flags[i] describe domain.getLevelSets()[i], in
    the SAME order: materials[i] is the vps.Material this level set
    should be tagged with in the exported mesh; wrap_flags[i] is
    whether it was inserted into `domain` with wrapLowerLevelSet=True
    (equivalently, `MakePlane(..., addToExisting=True)`), i.e. whether
    its own raw region also contains whatever every earlier level set
    already claims and needs Python-side clipping before export.

    Verified (see CLAUDE.md): real ViennaPS 4.6.2 LOCOS run (Si -> pad
    SiO2 via addToExisting=True -> Si3N4/Mask box, materials=[Si, SiO2,
    mask], wrap_flags=[False, True, False]) gives a combined mesh with
    all three materials genuinely present and correctly bounded (Si not
    lost), which then imports into DevSim successfully.

    dedupe_materials : optional list of vps.Material values. Two
        materials both listed here that share a geometrically-coincident
        boundary point (e.g. Si and a confined oxide touching at y=0)
        get that point MERGED into one shared mesh vertex, instead of
        each material's independent, isolated triangulation (see point
        1 above) producing a separate, same-coordinate-but-different-
        -index point for each. Needed for
        tcad.device.devsim.mesh_import.import_process_result's
        `interface_region_pairs`, which detects a shared interface edge
        by matching vertex INDICES, not coordinates — confirmed
        directly that without this, a save_locos_volume_mesh()-produced
        mesh has ZERO shared indices between any two materials even
        when their coordinates coincide exactly (31/31 points), so
        `interface_region_pairs` silently finds nothing.

        Default None: no dedup, byte-for-byte the same output every
        existing caller already gets (LOCOS, gate contact placement,
        gate_stack's own test) — zero regression risk.

        Deliberately NOT "dedupe every touching pair automatically":
        tried that first and it crashes DevSim's own create_device()
        with a native, uncatchable-from-Python-logic assert
        (`ASSERT .../Geometry/Region.cc:464 UNEXPECTED`) for THIS
        project's gate_stack topology specifically — reproduced even
        after registering a topological (no-equation) interface for
        EVERY touching pair, so it is not simply "an unregistered
        shared boundary" DevSim objects to; the deeper native cause was
        not chased further (see CLAUDE.md). Restricting dedup to only
        the materials a caller actually asked to interface avoids ever
        exercising that untested, crash-prone topology for materials
        (e.g. gate_stack's own source/drain metal pads) nothing needs
        connected to anything else.
    Returns the path actually written (mirrors save_volume_mesh(),
    though the filename suffix differs).
    """
    import numpy as np
    import meshio

    dedupe_tags = {int(m) for m in dedupe_materials} if dedupe_materials else None

    level_sets = list(domain.getLevelSets())
    if not (len(level_sets) == len(materials) == len(wrap_flags)):
        raise ValueError(
            f"save_locos_volume_mesh: domain has {len(level_sets)} level sets, "
            f"but materials has {len(materials)} and wrap_flags has "
            f"{len(wrap_flags)} entries — all three must match "
            "domain.getLevelSets(), 1:1, in insertion order."
        )

    grid_delta = domain.getGridDelta()
    # domain.getBoundingBox() does NOT return the union across every
    # level set (confirmed directly, not assumed — see
    # _union_bounding_box's own docstring), so both the wrap-clipping
    # lookup's x-range below AND each isolated per-level-set export
    # (via bounds_hint) need the real union instead. Computed once here
    # and reused for every level set in the loop below, rather than
    # recomputing it per level set.
    x_min, x_max, _y_min, y_max = _union_bounding_box(domain)
    bounds_hint = (x_min, x_max, y_max)

    all_points: List[List[float]] = []
    all_point_tags: List[int] = []
    all_tris: List[List[int]] = []
    all_tags: List[int] = []
    combined_top = None  # running top-surface lookup of every TRUE region claimed so far

    def add_block(points, tris, tag: int) -> None:
        offset = len(all_points)
        for p in points:
            all_points.append([float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0])
            all_point_tags.append(tag)
        for tri in tris:
            all_tris.append([int(tri[0]) + offset, int(tri[1]) + offset, int(tri[2]) + offset])
            all_tags.append(tag)

    for level_set, material, wrapped in zip(level_sets, materials, wrap_flags):
        points, tris = _export_single_level_set(
            domain, level_set, material, floor_depth_um, bounds_hint=bounds_hint
        )

        if wrapped and combined_top is not None and tris:
            margin = grid_delta * 0.1
            kept = []
            for tri in tris:
                cx = sum(points[i][0] for i in tri) / 3.0
                cy = sum(points[i][1] for i in tri) / 3.0
                if cy > combined_top(cx) + margin:
                    kept.append(tri)
            tris = kept

        add_block(points, tris, int(material))

        if tris:
            this_top = _top_lookup(points, tris, grid_delta, x_min, x_max)
            if combined_top is None:
                combined_top = this_top
            else:
                previous_top = combined_top
                combined_top = lambda x, a=previous_top, b=this_top: max(a(x), b(x))  # noqa: E731

    # Deduplicate coincident vertices ACROSS materials before writing.
    # Each level set above was triangulated in complete isolation (its
    # own throwaway single-material Domain -- see
    # _export_single_level_set), so two materials that physically touch
    # (e.g. Si and a confined oxide sharing the y=0 boundary within a
    # channel window) end up with geometrically-identical boundary
    # points at DIFFERENT vertex indices in the merged mesh -- confirmed
    # directly (not assumed): coordinates matched exactly (31/31) while
    # sharing zero indices. This silently breaks every DOWNSTREAM
    # consumer that identifies a shared boundary by vertex index rather
    # than coordinate -- mesh_import.py's interface_region_pairs (edges
    # are matched by sorted node-index pairs) finds ZERO interface edges
    # for a save_locos_volume_mesh()-produced mesh without this, even
    # when the two materials are geometrically touching. Fixed by
    # merging points with identical (rounded) coordinates into one
    # shared vertex, remapping every triangle's indices accordingly. 9
    # decimal places matches this project's existing float-noise
    # convention (see ProcessStep.prepare_domain()'s trench_width_um
    # rounding) -- far finer than any real triangulated distance, so
    # this cannot merge two vertices that were meant to stay distinct.
    dedup_key_to_index: Dict[Tuple[float, float, float], int] = {}
    dedup_points: List[List[float]] = []
    remap: List[int] = []
    for p, point_tag in zip(all_points, all_point_tags):
        eligible = dedupe_tags is not None and point_tag in dedupe_tags
        key = (round(p[0], 9), round(p[1], 9), round(p[2], 9)) if eligible else None
        idx = dedup_key_to_index.get(key) if key is not None else None
        if idx is None:
            idx = len(dedup_points)
            if key is not None:
                dedup_key_to_index[key] = idx
            dedup_points.append(p)
        remap.append(idx)
    dedup_tris = [[remap[i] for i in tri] for tri in all_tris]

    out_mesh = meshio.Mesh(
        points=np.array(dedup_points) if dedup_points else np.zeros((0, 3)),
        cells=[("triangle", np.array(dedup_tris) if dedup_tris else np.zeros((0, 3), dtype=int))],
        cell_data={"Material": [np.array(all_tags, dtype=int)]},
    )
    out_path = f"{str(path)}_locos_volume.vtu"
    meshio.write(out_path, out_mesh)
    return out_path


def filter_mesh_materials(mesh_path: PathLike, keep_materials: List[Any]) -> str:
    """Return the path to a NEW mesh file containing only the triangles
    (and the points they reference) tagged with one of `keep_materials`.

    Exists to drop electrically-irrelevant regions from a geometry
    built for a different purpose than the one it's about to be
    imported for — e.g. tcad/process/geometry/gate_stack.py's source/
    drain metal PADS, useful for demonstrating contact placement (see
    CLAUDE.md, "Gate-over-channel + separate source/drain contacts"),
    but not needed for (and, confirmed by direct measurement, actively
    HARMFUL to) a gate-only C-V sweep: importing them alongside a
    dedup()'d Si-SiO2 interface crashes DevSim's own create_device()
    with a native assert (`ASSERT .../Geometry/Region.cc:464
    UNEXPECTED`) — reproduced with as few as 3 regions (Si, SiO2, one
    untouched metal pad) present, even though the pad shares NO
    deduped vertices with anything. Not root-caused at the DevSim C++
    level (matches this project's established practice for this class
    of native-library behavior elsewhere in this file) — sidestepped
    instead by not asking DevSim to import a region the caller doesn't
    need at all.

    keep_materials : vps.Material values (or anything int()-convertible
        to the mesh's own integer material tags) to retain.

    Points referenced by NO surviving triangle are dropped and every
    triangle's indices are remapped accordingly, so the output is a
    clean, self-contained mesh — not just a triangle-level filter of the
    original point list (which would leave stray unused points DevSim's
    importer does not expect).
    """
    import meshio
    import numpy as np

    mesh = meshio.read(str(mesh_path))
    block = next(c for c in mesh.cells if c.type == "triangle")
    block_index = mesh.cells.index(block)
    tags = mesh.cell_data["Material"][block_index]
    keep_tags = {int(m) for m in keep_materials}

    kept_tris = [tri for tri, tag in zip(block.data, tags) if int(tag) in keep_tags]
    kept_tags = [int(tag) for tag in tags if int(tag) in keep_tags]

    remap: Dict[int, int] = {}
    new_points: List[Any] = []
    new_tris: List[List[int]] = []
    for tri in kept_tris:
        new_tri = []
        for i in tri:
            i = int(i)
            if i not in remap:
                remap[i] = len(new_points)
                new_points.append(mesh.points[i])
            new_tri.append(remap[i])
        new_tris.append(new_tri)

    out_mesh = meshio.Mesh(
        points=np.array(new_points) if new_points else np.zeros((0, 3)),
        cells=[("triangle", np.array(new_tris) if new_tris else np.zeros((0, 3), dtype=int))],
        cell_data={"Material": [np.array(kept_tags, dtype=int)]},
    )
    out_path = f"{str(mesh_path)}.filtered.vtu"
    meshio.write(out_path, out_mesh)
    return out_path


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
