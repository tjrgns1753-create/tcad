#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ViennaPS session / domain helpers.

Extracted from the top of tcad_2d_stagewise.py and the beginning of
run_viennaps_bosch(): the optional `import viennaps as vps` guard, the
setDimension(2) + Domain(...) construction, and the MakeTrench call that
every process recipe needs before it can run. Recipe-specific logic
(Bosch cycles, particle processes, rate functions, etc.) stays out of this
module — it belongs to individual process implementations.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from typing import Any

try:
    import viennaps as vps
except Exception:
    vps = None


def _ascii_scratch_dir() -> str:
    """A writable directory whose path contains only ASCII characters.

    ViennaPS's Writer/Reader hand the filename to a C++ narrow-char file
    API, which on Windows cannot open a path containing non-ASCII
    characters. Measured directly on a machine whose user name is not
    ASCII (so `tempfile.gettempdir()` is
    `C:\\Users\\<non-ascii>\\AppData\\Local\\Temp`):

      * `Writer(domain, path).apply()` wrote NO file and raised NOTHING —
        `save_domain_state()` returned normally and the caller only found
        out one step later, when `Reader` failed with "Could not open
        file".
      * `Reader` failed the same way on a file that demonstrably existed
        (copied there, 1206 bytes), so it is the path string, not the
        file content.

    The usual Windows workaround — an 8.3 short path via
    GetShortPathNameW — was tried first and does NOT work here: 8.3 name
    generation is disabled on this volume, so the call returns the long
    path unchanged. Hence this: find an ASCII directory, do the I/O
    there, and move the result to where the caller asked.

    The candidates are tried in order and the first writable ASCII one
    wins. `tempfile.gettempdir()` is first because on an ASCII-named
    account it already qualifies, which makes this whole detour a no-op.
    """
    candidates = [
        tempfile.gettempdir(),
        os.environ.get("PUBLIC", ""),
        os.path.join(os.environ.get("SystemDrive", "C:") + os.sep, "Temp"),
        os.environ.get("SystemDrive", "C:") + os.sep,
    ]
    for base in candidates:
        if not base or not base.isascii():
            continue
        try:
            os.makedirs(base, exist_ok=True)
            probe = tempfile.NamedTemporaryFile(dir=base, delete=True)
            probe.close()
            return base
        except Exception:
            continue
    raise RuntimeError(
        "No writable ASCII-only directory found for ViennaPS domain I/O. "
        "ViennaPS cannot open a path containing non-ASCII characters; "
        "tried: " + ", ".join(repr(c) for c in candidates if c)
    )


@contextmanager
def _ascii_io_path(path: str, mode: str):
    """Yield an ASCII path safe to hand to ViennaPS Writer/Reader.

    mode "w": yields a scratch path; after the block the scratch file is
    moved onto `path`. mode "r": copies `path` into scratch first and
    yields that. When `path` is already ASCII, it is yielded unchanged
    and nothing is copied — so an ASCII-named machine keeps exactly the
    previous behavior and cost.
    """
    if path.isascii():
        yield path
        return

    scratch_dir = tempfile.mkdtemp(prefix="tcad_vpsd_", dir=_ascii_scratch_dir())
    scratch = os.path.join(scratch_dir, "domain_state.vpsd")
    try:
        if mode == "r":
            shutil.copyfile(path, scratch)
        yield scratch
        if mode == "w":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            shutil.move(scratch, path)
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)


def is_available() -> bool:
    """True if the ViennaPS Python module imported successfully."""
    return vps is not None


def require_viennaps() -> Any:
    """Return the imported viennaps module, or raise if it's unavailable.

    Same error message/behavior as the original run_viennaps_bosch() guard.
    """
    if vps is None:
        raise RuntimeError(
            "ViennaPS is unavailable.\n"
            "Install ViennaPS first:\n"
            "python -m pip install ViennaPS"
        )
    return vps


def _ensure_units_set(module) -> None:
    """Set ViennaPS's global Length/Time units once, if not already set.

    Some models (confirmed: FluorocarbonEtching) raise
    "RuntimeError: Units have not been set." until this is done.
    "micrometer"/"second" are the exact strings ViennaPS 4.6.2 accepts —
    confirmed by triggering module.Length.setUnit()'s own validation
    error against the real installed package, which enumerates the
    accepted values verbatim: "meter, centimeter, millimeter,
    micrometer, nanometer, angstrom" (Length) and "second, minute,
    millisecond" (Time). These match this project's existing recipe
    convention of *_um / *_s keys, so they are also the semantically
    correct choice, not just the first accepted string.
    """
    if module.Length.toString() == "":
        module.Length.setUnit("micrometer")
    if module.Time.toString() == "":
        module.Time.setUnit("second")


def create_domain(
    grid_delta_um: float,
    x_extent_um: float,
    y_extent_um: float,
    dimension: int = 2,
):
    """Set units, the simulation dimension, and create a new ViennaPS Domain.

    Mirrors the original inline sequence:
        vps.setDimension(2)
        geometry = vps.Domain(gridDelta=..., xExtent=..., yExtent=...)
    plus the one-time global unit setup every model needs (see
    _ensure_units_set).
    """
    module = require_viennaps()

    _ensure_units_set(module)

    module.setDimension(dimension)

    return module.Domain(
        gridDelta=grid_delta_um,
        xExtent=x_extent_um,
        yExtent=y_extent_um,
    )


def make_trench(
    domain,
    trench_width_um: float,
    trench_depth_um: float,
    mask_height_um: float,
):
    """Apply vps.MakeTrench(...).apply() to an existing domain in place.

    mask_height_um is clamped to a 0.1 um floor, matching the original
    `maskHeight=max(recipe["pr_thickness_um"], 0.1)` call.
    """
    module = require_viennaps()

    module.MakeTrench(
        domain=domain,
        trenchWidth=trench_width_um,
        trenchDepth=trench_depth_um,
        maskHeight=max(mask_height_um, 0.1),
    ).apply()

    return domain


def make_mask_spans(
    grid_delta_um: float,
    x_extent_um: float,
    y_extent_um: float,
    spans_um,
    mask_height_um: float,
    substrate_depth_um: float = 1.0,
    mask_material: str = "Mask",
    dimension: int = 2,
):
    """Build a domain whose mask is an arbitrary list of OPAQUE spans.

    `MakeTrench` can only ever produce one fixed pattern —
    `opaque | open | opaque`, a single centred window. A real mask needs
    more than that; in particular a MOSFET source/drain implant mask is
    the COMPLEMENT (`open | opaque(gate/channel) | open`, i.e. one
    central opaque span), which `MakeTrench` cannot express at all.

    spans_um : sequence of (min_um, max_um) pairs, in domain x
        coordinates (the domain spans [-x_extent_um/2, +x_extent_um/2]).
        Each pair is a region COVERED by mask; everything else is open.
        Spans may touch or overlap — they are unioned, so overlap is
        harmless rather than an error.
    substrate_depth_um : the substrate box's own lower bound. This is an
        HRLE allocation hint only, NOT a physical floor — the y axis is
        INFINITE_BOUNDARY, and the real floor is applied at export time
        like every other geometry in this project (see
        io.DEFAULT_FLOOR_DEPTH_UM).

    Level-set ORDERING is load-bearing, not stylistic. ViennaLS `Advect`
    advects only the LAST level set and then replaces each lower one with
    `lower INTERSECT last`, so the last level set must CONTAIN all
    others or the lower ones are destroyed on any subsequent process
    step. `MakeTrench` satisfies this by inserting the SUBSTRATE last,
    wrapping the mask — so this function mirrors that exact ordering
    (mask first, then substrate last with wrapLowerLevelSet=True).
    Verified by direct measurement, not assumed: the obvious
    alternative (mask inserted last, unwrapped) produces an EMPTY export
    and reproduces the same class of failure as the LOCOS chaining bug,
    while this ordering survives a real chained etch with every level
    set intact. See CLAUDE.md.

    Also verified: two spans covering everything outside a window
    reproduce real `MakeTrench` to within 0.06% in every material's
    area — i.e. this is a strict generalization of it, not a different
    geometry that merely looks similar.
    """
    module = require_viennaps()
    import viennals as vls

    _ensure_units_set(module)
    module.setDimension(dimension)

    half_x = x_extent_um / 2.0
    substrate = getattr(module.Material, "Si")
    mask_mat = getattr(module.Material, mask_material)

    # A scratch domain purely to learn this grid's boundary conditions:
    # getBoundaryConditions() is only safe once a domain has at least
    # one level set (confirmed elsewhere in this project: it segfaults
    # on an empty Domain), and the final domain must receive its level
    # sets in mask-then-substrate order, so the conditions cannot be
    # read from it before the mask exists.
    scratch = create_domain(grid_delta_um, x_extent_um, y_extent_um, dimension)
    module.MakePlane(scratch, 0.0, substrate).apply()
    bcs = scratch.getBoundaryConditions()
    bounds = [-half_x, half_x, -substrate_depth_um, y_extent_um]

    mask_ls = None
    for lo, hi in spans_um:
        box_ls = vls.Domain(bounds, bcs, grid_delta_um)
        box = vls.MakeGeometry(box_ls, vls.Box([lo, 0.0], [hi, mask_height_um]))
        # The mask boxes deliberately run to the domain edge in x for a
        # full-width span; without this the x boundary condition would
        # clip them back.
        box.setIgnoreBoundaryConditions([False, True, False])
        box.apply()
        if mask_ls is None:
            mask_ls = box_ls
        else:
            vls.BooleanOperation(
                mask_ls, box_ls, vls.BooleanOperationEnum.UNION
            ).apply()

    domain = create_domain(grid_delta_um, x_extent_um, y_extent_um, dimension)
    if mask_ls is not None:
        domain.insertNextLevelSetAsMaterial(mask_ls, mask_mat, False)

    substrate_ls = vls.Domain(bounds, bcs, grid_delta_um)
    vls.MakeGeometry(
        substrate_ls, vls.Box([-half_x, -substrate_depth_um], [half_x, 0.0])
    ).apply()
    # wrapLowerLevelSet=True: makes this (the last) level set the union
    # of substrate + mask, satisfying Advect's containment precondition
    # exactly as MakeTrench does.
    domain.insertNextLevelSetAsMaterial(substrate_ls, substrate, True)

    return domain


def remask_domain(
    domain,
    grid_delta_um: float,
    x_extent_um: float,
    spans_um,
    mask_height_um: float,
    mask_material: str = "Mask",
):
    """Add a NEW lithography mask on top of an ALREADY-PROCESSED domain.

    `prepare_domain()`'s own mask construction (MakeTrench /
    make_mask_spans, above) only ever builds a mask on a FRESH wafer.
    Real gate patterning needs the fab step that comes after that: a
    layer is blanket-deposited over existing geometry, THEN re-masked,
    THEN etched into a pattern. This is that re-mask step, applied
    in-place to a domain a previous process step already built.

    domain : an existing ViennaPS Domain (e.g. `step.last_domain` from
        a prior chained step) — mutated in place and also returned.
    spans_um : opaque mask spans (same shape/convention as
        `make_mask_spans`'s own `spans_um` — domain x coordinates,
        merged if overlapping).
    mask_height_um : mask thickness above the domain's current top.

    CONFORMS TO TOPOGRAPHY. Photoresist is spun on: it fills whatever
    steps, trenches and humps the previous steps left, rather than
    hovering at one flat height. Getting this wrong is not cosmetic —
    measured on a real 4-step chain (oxidation -> window etch -> metal
    deposition -> remask + metal etch), a mask placed only at the
    domain's single global top y left the LOW parts of a stepped
    surface completely unprotected: the metal survived in the middle
    (under a tall bump) and was etched away exactly where the mask was
    supposed to be covering it — the inverse of the requested pattern,
    with no warning. So each mask span is built as a full-height column
    spanning from BELOW the lowest geometry up to `mask_height_um`
    above the highest, and the wrapLowerLevelSet=True insert (a union
    with everything already present) discards whatever part of that
    column lies inside existing material, leaving exactly the
    conformal, gap-filling resist a real spin-on leaves.

    Mechanics, verified directly against real ViennaPS 4.6.2 (build a
    domain, blanket-deposit a second material, remask, then run a real
    IsotropicProcess etch with maskMaterial=<mask_material> — the
    masked span survives, the rest clears, the material stack below is
    otherwise undisturbed). Inserted with wrapLowerLevelSet=True,
    which — per psDomain.hpp — unions the new level set with whatever
    was the domain's previous last level set, making the mask the new
    last entry and therefore satisfying ViennaLS Advect's "last level
    set contains all others" precondition for any FURTHER process step
    run on this domain. That same union is what lets each mask span be
    built as a full-height column (see above) without displacing
    anything: the part of the column already occupied by existing
    material is absorbed by the union, leaving only the part standing
    above the real surface.
    """
    module = require_viennaps()
    import viennals as vls

    from tcad.backends.viennaps.io import _union_bounding_box

    bcs = domain.getBoundaryConditions()
    # TRUE union extent across every level set, not
    # domain.getBoundingBox() -- that returns only the LAST level set's
    # own box on a multi-level-set domain (confirmed in io.py's own
    # _union_bounding_box docstring), which is exactly the reading that
    # put the mask at one flat height and left stepped topography
    # unprotected.
    _x_min, _x_max, y_min, top_y = _union_bounding_box(domain)
    half_x = x_extent_um / 2.0
    mask_mat = getattr(module.Material, mask_material)
    # Start the column below ALL existing geometry so it fills every
    # step/trench on the way up (spin-on resist behavior). The
    # wrapLowerLevelSet=True insert below unions this with everything
    # already in the domain, so the submerged part of the column is
    # absorbed rather than displacing any existing material -- which is
    # what makes going this far down safe rather than destructive.
    box_bottom = y_min - 1.0
    box_top = top_y + mask_height_um
    bounds = [-half_x, half_x, box_bottom - 1.0, box_top + 1.0]

    mask_ls = None
    for lo, hi in spans_um:
        box_ls = vls.Domain(bounds, bcs, grid_delta_um)
        box = vls.MakeGeometry(box_ls, vls.Box([lo, box_bottom], [hi, box_top]))
        # Full-width spans must reach the domain edge, same reason as
        # make_mask_spans's own loop.
        box.setIgnoreBoundaryConditions([False, True, False])
        box.apply()
        if mask_ls is None:
            mask_ls = box_ls
        else:
            vls.BooleanOperation(mask_ls, box_ls, vls.BooleanOperationEnum.UNION).apply()

    if mask_ls is not None:
        domain.insertNextLevelSetAsMaterial(mask_ls, mask_mat, True)

    return domain


def make_gate_stack(
    grid_delta_um: float,
    x_extent_um: float,
    y_extent_um: float,
    channel_um,
    source_um,
    drain_um,
    gate_oxide_thickness_um: float,
    gate_height_um: float,
    pad_height_um: float,
    silicon_depth_um: float = 1.0,
    gate_material: str = "TiN",
    source_material: str = "W",
    drain_material: str = "Cu",
    oxide_material: str = "SiO2",
    dimension: int = 2,
):
    """Build a 5-material MOSFET-shaped gate stack: Si body, a thin gate
    oxide confined to the channel window, a gate electrode on top of it
    (also confined to the channel), and separate source/drain pads.

    Verified this is the ONLY insertion order/wrap combination (of
    several tried) that exports correctly via save_locos_volume_mesh():
    Si, source, drain, gate oxide all inserted UNWRAPPED (they are
    mutually disjoint -- touch only at shared boundaries, never overlap
    in area -- so no material-stacking ambiguity exists between them);
    the gate ELECTRODE is inserted LAST with wrapLowerLevelSet=True,
    since it is the true topmost layer (sits on top of the oxide, which
    sits on top of Si, within the channel window only). Two other
    orderings were tried and rejected by direct measurement:
      - wrapping the SUBSTRATE last (mirroring MakeTrench/
        make_mask_spans' own convention): satisfies ViennaLS Advect's
        containment precondition, but save_locos_volume_mesh's clip
        logic assumes the WRAPPED material is the newest TOP layer, the
        opposite relationship -- the substrate's true (bottom) region
        gets discarded, exporting only a tiny sliver artifact.
      - wrapping EVERY insertion after Si (a true cumulative union
        chain, confirmed by direct measurement to be how
        wrapLowerLevelSet actually accumulates -- it unions with
        whatever is CURRENTLY the top of the stack at insertion time,
        not just the immediately-preceding level set): this DOES
        satisfy Advect (no level set destroyed by a subsequent
        Process() call), but corrupts the export differently --
        save_locos_volume_mesh's per-x-column top-surface lookup
        (_top_lookup) nearest-neighbor-fills any x-bin a narrow,
        laterally-confined material (e.g. the source pad) has no real
        data in, which incorrectly extrapolates that material's own
        height into completely unrelated lateral windows (e.g. the
        drain's), corrupting every other wrapped material's clip
        boundary. This is a real, previously-undiscovered limitation of
        _top_lookup, verified but NOT fixed this session (see CLAUDE.md)
        -- it was tuned and tested only for LOCOS's own near-domain-
        -spanning field oxide, not multiple narrow, disjoint windows.

    CONSEQUENCE, not a hypothetical: because only the gate electrode is
    wrapped, this domain does NOT satisfy Advect's containment
    precondition for the OTHER four level sets (Si, source, drain,
    oxide) -- confirmed directly: chaining a further real Process() step
    (e.g. an etch) onto this domain destroys all four (their level sets
    collapse to 0 points), and the subsequent export does not even
    produce a readable mesh file (no warning fires either, since
    save_volume_mesh's own missing-material check silently gives up
    when it can't read the mesh at all). This geometry is a TERMINAL
    construction only -- do not chain any further ViennaPS process step
    (or a tcad.process.flow.FlowStep) onto the domain this returns.

    gate_oxide_thickness_um is floored at 1.5x gridDelta, not just 1x:
    measured directly (not assumed) that a box level set exactly 1x
    gridDelta thick collapses to an EMPTY export through this project's
    own floor-export machinery (_floored_copy_for_export's Expand(3) +
    boolean-intersect pipeline) -- a razor-thin floating-point/grid-
    -alignment edge case (1.00x fails, 1.01x already succeeds), the same
    class of bug as the already-documented MakeTrench floating-point
    sensitivity. 1.5x gridDelta is a safety margin confirmed clear of
    this failure boundary, not the tightest possible value.
    gate_height_um / pad_height_um are floored the same way for the same
    reason (both are also freestanding boxes exported in isolation).

    THIS FLOOR IS SILENT AND CAN SUBSTANTIALLY CHANGE THE BUILT
    GEOMETRY -- found (not assumed) by a real MOS C-V audit: a caller
    requesting gate_oxide_thickness_um=0.02 at grid_delta_um=0.05 (a
    combination the GUI's own gate_stack panel and this project's own
    gate_stack C-V test both use) silently gets a 0.075um oxide -- 3.75x
    thicker than requested -- because 0.02 < 1.5*0.05. A caller that
    computes a physics reference value (e.g. the ideal C_ox =
    eps_ox*eps_0*width/t_ox used to sanity-check a C-V sweep) from the
    REQUESTED thickness instead of the ACTUALLY BUILT one gets a
    reference wrong by the same 3.75x factor -- this was measured to be
    the dominant cause of an apparent "MOS accumulation capacitance is
    only 25% of ideal C_ox" finding that looked like a physics/mesh
    problem but was actually a stale-reference-value bug once the real
    built thickness is used (102% of the correctly-computed C_ox, not
    25%). Returns the ACTUALLY APPLIED dimensions (see `actual_dims`
    below) specifically so a caller never has to guess whether this
    floor fired, and warns via `warnings.warn` when it does.

    channel_um / source_um / drain_um : (min_um, max_um) pairs in domain
        x coordinates. Not validated against overlap -- a caller
        building a physically nonsensical layout (e.g. source
        overlapping the channel) gets whatever geometry that implies,
        same permissiveness as make_mask_spans' own spans_um.

    Returns (domain, materials, wrap_flags, actual_dims) -- `actual_dims`
    is {"gate_oxide_thickness_um": oxide_h, "gate_height_um": gate_h,
    "pad_height_um": pad_h}, the POST-FLOOR values genuinely used to
    build the geometry (equal to the requested values whenever none of
    them needed flooring).
    """
    import warnings

    module = require_viennaps()
    import viennals as vls

    _ensure_units_set(module)
    module.setDimension(dimension)

    safe_min = 1.5 * grid_delta_um
    oxide_h = max(gate_oxide_thickness_um, safe_min)
    gate_h = max(gate_height_um, safe_min)
    pad_h = max(pad_height_um, safe_min)
    _floored = {
        "gate_oxide_thickness_um": (gate_oxide_thickness_um, oxide_h),
        "gate_height_um": (gate_height_um, gate_h),
        "pad_height_um": (pad_height_um, pad_h),
    }
    for _name, (_requested, _applied) in _floored.items():
        if _applied != _requested:
            warnings.warn(
                f"make_gate_stack: {_name}={_requested}um is below the "
                f"1.5*grid_delta_um={safe_min}um export-safety floor for "
                f"grid_delta_um={grid_delta_um}um -- built with "
                f"{_name}={_applied}um instead. Use the actual_dims "
                f"returned by this function (not the requested value) "
                f"for any downstream physics reference computation (e.g. "
                f"ideal C_ox).",
                stacklevel=2,
            )

    half_x = x_extent_um / 2.0
    silicon = getattr(module.Material, "Si")
    gate_mat = getattr(module.Material, gate_material)
    source_mat = getattr(module.Material, source_material)
    drain_mat = getattr(module.Material, drain_material)
    oxide_mat = getattr(module.Material, oxide_material)

    # Scratch domain purely to read this grid's boundary conditions
    # safely -- getBoundaryConditions() segfaults on an empty Domain
    # (confirmed elsewhere in this project), same pattern make_mask_spans
    # already uses.
    scratch = create_domain(grid_delta_um, x_extent_um, y_extent_um, dimension)
    module.MakePlane(scratch, 0.0, silicon).apply()
    bcs = scratch.getBoundaryConditions()
    bounds = [-half_x, half_x, -silicon_depth_um - 0.5, y_extent_um]

    def box(lo_xy, hi_xy):
        ls = vls.Domain(bounds, bcs, grid_delta_um)
        geom = vls.MakeGeometry(ls, vls.Box(list(lo_xy), list(hi_xy)))
        geom.setIgnoreBoundaryConditions([False, True, False])
        geom.apply()
        return ls

    domain = create_domain(grid_delta_um, x_extent_um, y_extent_um, dimension)
    domain.insertNextLevelSetAsMaterial(
        box((-half_x, -silicon_depth_um), (half_x, 0.0)), silicon, False)
    domain.insertNextLevelSetAsMaterial(
        box((source_um[0], 0.0), (source_um[1], pad_h)), source_mat, False)
    domain.insertNextLevelSetAsMaterial(
        box((drain_um[0], 0.0), (drain_um[1], pad_h)), drain_mat, False)
    domain.insertNextLevelSetAsMaterial(
        box((channel_um[0], 0.0), (channel_um[1], oxide_h)), oxide_mat, False)
    domain.insertNextLevelSetAsMaterial(
        box((channel_um[0], oxide_h), (channel_um[1], oxide_h + gate_h)),
        gate_mat, True,
    )

    materials = [silicon, source_mat, drain_mat, oxide_mat, gate_mat]
    wrap_flags = [False, False, False, False, True]
    actual_dims = {
        "gate_oxide_thickness_um": oxide_h,
        "gate_height_um": gate_h,
        "pad_height_um": pad_h,
    }
    return domain, materials, wrap_flags, actual_dims


def save_domain_state(domain, path: str) -> str:
    """Persist a Domain's full level-set/material state to `path`.

    Real API used (verified against installed ViennaPS 4.6.2 by a
    round-trip test before this was written): vps.Writer(domain,
    filename).apply() writes a single .vpsd file that vps.Reader can
    restore. Confirmed preserved across the round trip: the material
    set, the number of level sets, the bounding box, and gridDelta —
    and a further Process() runs correctly on the restored domain.

    Note this is NOT the same as saveLevelSets(), which writes separate
    per-layer .lvst files that vps.Reader does not accept.

    Writes through _ascii_io_path() because ViennaPS cannot open a
    non-ASCII path (see that helper), and verifies afterwards that a file
    actually appeared: Writer reports failure by writing nothing rather
    than by raising, which previously turned a failed save into a
    confusing "Could not open file" from the NEXT step's Reader.
    """
    require_viennaps()
    module = require_viennaps()
    with _ascii_io_path(path, "w") as io_path:
        module.Writer(domain, io_path).apply()
        if not os.path.exists(io_path):
            raise RuntimeError(
                f"ViennaPS Writer did not produce a domain state file at {io_path!r}."
            )
    return path


def load_domain_state(path: str):
    """Restore a Domain previously written by save_domain_state()."""
    module = require_viennaps()
    _ensure_units_set(module)
    module.setDimension(2)
    domain = module.Domain()
    with _ascii_io_path(path, "r") as io_path:
        module.Reader(domain, io_path).apply()
    return domain


def describe_domain(domain) -> dict:
    """Backend-facing snapshot of a domain's structural state.

    Used by the process-flow layer to record, and by tests to prove,
    what actually changed from one step to the next (materials present,
    level-set count, bounding box, grid spacing).
    """
    require_viennaps()
    return {
        "materials": sorted(str(m).split("'")[1] for m in domain.getMaterialsInDomain()),
        "num_level_sets": domain.getNumberOfLevelSets(),
        "bounding_box": [list(p) for p in domain.getBoundingBox()],
        "grid_delta": domain.getGridDelta(),
    }
