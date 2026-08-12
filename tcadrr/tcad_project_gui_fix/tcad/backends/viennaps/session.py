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
    half_trench: bool = False,
):
    """Apply vps.MakeTrench(...).apply() to an existing domain in place.

    mask_height_um is clamped to a 0.1 um floor, matching the original
    `maskHeight=max(recipe["pr_thickness_um"], 0.1)` call.

    half_trench=True passes MakeTrench's own `halfTrench` flag through
    (default False, so every existing caller is byte-identical). Verified
    (isolated scratch probes, this session) this is what avoids the LOCOS
    mask-mechanics segfault (psOxidation.hpp's solveElasticVelocity),
    without changing gridDelta/pad-oxide handling. Note: it also rebuilds
    the domain as a half-geometry mirrored (REFLECTIVE_BOUNDARY) at x=0,
    so the mask edge lands at trench_width_um/2, NOT at the recipe's
    mask_left_um/mask_right_um positions -- callers that need exact
    absolute mask placement must not combine this with those keys.
    """
    module = require_viennaps()

    module.MakeTrench(
        domain=domain,
        trenchWidth=trench_width_um,
        trenchDepth=trench_depth_um,
        maskHeight=max(mask_height_um, 0.1),
        halfTrench=half_trench,
    ).apply()

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
