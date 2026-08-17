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

from typing import Any

try:
    import viennaps as vps
except Exception:
    vps = None


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
    """
    require_viennaps()
    module = require_viennaps()
    module.Writer(domain, path).apply()
    return path


def load_domain_state(path: str):
    """Restore a Domain previously written by save_domain_state()."""
    module = require_viennaps()
    _ensure_units_set(module)
    module.setDimension(2)
    domain = module.Domain()
    module.Reader(domain, path).apply()
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
