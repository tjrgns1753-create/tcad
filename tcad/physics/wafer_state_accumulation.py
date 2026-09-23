#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`advance_wafer_state()` -- the single v2 threading point the real
production / GUI doping path calls (design doc 2026-09-10 Sec7.2).

WaferState v2 migration: this now returns a `WaferStateV2`, never the
v1 `WaferState`. It does NOT infer a `GeometryTransform` from a
`ProcessResult` / exported mesh (design doc Sec5.5). A caller that
genuinely knows a step's exact rectangular extents and target instance
ids passes an explicit `GeometryTransform`; every other step (a real
ViennaPS curved etch, a real oxidation front, an unmodelled geometry
change) passes `transform=None`, and the step becomes
`UNSUPPORTED_BY_MODEL` -- which is the correct, honest outcome.

The v1 `WaferState` geometry (x_min/x_max/y_max, NO y_min) is migrated
ONLY through `legacy_state_from_v1_cells()` -> LEGACY_UNRESOLVED cells;
it never silently becomes a MODELLED 2D state. A dopant profile
attached over a LEGACY_UNRESOLVED / UNRESOLVED cell is refused an
active attachment by `attach_dopant()` and recorded as unresolved --
it is never written back to DevSim as a number.

Doping TARGET resolution (P0-A): a doping application never picks "the
first cell whose material name matches" -- that silently mis-attaches
whenever more than one instance of the same material exists (an
original substrate plus a later re-deposited layer of the same
material) or a single instance has been split into more than one cell
by an earlier etch/oxidation. See `_resolve_doping_target()`.

Barrier exclusion (P0-C): a barrier (e.g. SiO2 over part of a doped
region) is never applied as a generic post-hoc zeroing of the
accumulated NetDoping -- that would erase pre-existing/background
dopant that was there before the barrier existed. Instead, a barrier
carves the SUPPORT REGION of the *new* attachment being created by
THIS call, at attach time, before it ever becomes part of the
accumulated state -- see `_carve_support_around_barrier()`. Any
already-accumulated attachment (from an earlier call) is untouched.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from tcad.mesh.interface import ProcessResult
from tcad.physics.dopant_profile import dopant_profiles_from_doping_profile
from tcad.physics.wafer_state import WaferState
from tcad.physics import wafer_state_v2 as v2


#: `state_transition` of an oxidation step that changed nothing because it was
#: handed an existing domain and returned it untouched (time_hours == 0,
#: `inherited=True`). The backend domain IS the prior domain, so the prior
#: WaferState still describes it and is preserved by object identity.
ZERO_DURATION_INHERITED_IDENTITY = {
    "kind": "identity", "reason": "zero_duration_oxidation",
    "category": "oxidation", "inherited": True,
}

#: A step with NO inherited domain that materialized the recipe's own virgin Si
#: wafer (time_hours == 0, `inherited=False`) is NOT an identity: the backend
#: built a brand-new domain, so nothing proves that any earlier WaferState
#: (its bounds, material instances, lineage, dopant, grid) describes it. It is
#: a `materialization` and carries the exact geometry it materialized:
#:   {"kind": "materialization", "reason": "zero_duration_oxidation",
#:    "category": "oxidation", "inherited": False,
#:    "initial_geometry": {"material": "Si",
#:                         "bounds_um": [x_min, x_max, y_min, y_max],
#:                         "material_instance_id": "si#substrate",
#:                         "grid_delta_um": g}}
#: The bounds come from the recipe's `x_extent_um` / `silicon_depth_um` (never
#: from a mesh, never from `y_extent_um` or the exporter floor): the virgin
#: substrate is x in [-x_extent/2, +x_extent/2], y in [-silicon_depth, 0].
_MATERIALIZATION_TOP_KEYS = frozenset(
    {"kind", "reason", "category", "inherited", "initial_geometry"})
_MATERIALIZATION_GEOMETRY_KEYS = frozenset(
    {"material", "bounds_um", "material_instance_id", "grid_delta_um"})
_SUBSTRATE_INSTANCE_ID = "si#substrate"


def _finite_real(v) -> bool:
    import math
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v))


def is_canonical_inherited_zero_duration_identity(transition) -> bool:
    """True only for the exact inherited identity dict.

    Strict: a missing/extra key, a different kind/reason/category, `None`,
    `{}`, a non-dict, or a non-bool `inherited` (Python's `1 == True` would
    otherwise pass a plain dict comparison) is NOT an identity."""
    return (isinstance(transition, dict)
            and isinstance(transition.get("inherited"), bool)
            and transition == ZERO_DURATION_INHERITED_IDENTITY)


def parse_fresh_zero_duration_materialization(transition):
    """The validated `initial_geometry` dict of a canonical fresh zero-duration
    materialization, or None if `transition` is anything else (including every
    malformed or near-miss variant). Strict schema: exact key sets, exact
    kind/reason/category, `inherited is False`, material exactly "Si", the exact
    substrate instance id, four finite real bounds forming a positive-area
    rectangle, a finite positive grid."""
    if not isinstance(transition, dict) or set(transition) != _MATERIALIZATION_TOP_KEYS:
        return None
    if (transition["kind"] != "materialization"
            or transition["reason"] != "zero_duration_oxidation"
            or transition["category"] != "oxidation"
            or transition["inherited"] is not False):
        return None
    geometry = transition["initial_geometry"]
    if not isinstance(geometry, dict) or set(geometry) != _MATERIALIZATION_GEOMETRY_KEYS:
        return None
    if geometry["material"] != "Si" or geometry["material_instance_id"] != _SUBSTRATE_INSTANCE_ID:
        return None
    bounds = geometry["bounds_um"]
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4 or not all(map(_finite_real, bounds)):
        return None
    x_min, x_max, y_min, y_max = bounds
    if not (x_max > x_min and y_max > y_min):
        return None
    grid = geometry["grid_delta_um"]
    if not _finite_real(grid) or not grid > 0:
        return None
    return geometry


def is_canonical_fresh_zero_duration_materialization(transition) -> bool:
    return parse_fresh_zero_duration_materialization(transition) is not None


def fresh_zero_duration_materialization_transition(recipe) -> dict:
    """The transition a fresh zero-duration step reports, built from the
    recipe's own bounds. Raises ValueError if the recipe cannot state them
    exactly (`x_extent_um`, `silicon_depth_um`, `grid_delta_um` all required
    -- nothing is guessed) -- checked BEFORE any geometry is built."""
    try:
        x_extent = float(recipe["x_extent_um"])
        depth = float(recipe["silicon_depth_um"])
        grid = float(recipe["grid_delta_um"])
    except KeyError as exc:
        raise ValueError(
            f"a fresh zero-duration oxidation materializes the recipe's own "
            f"wafer and needs its explicit bounds; recipe key {exc.args[0]!r} "
            f"is missing") from exc
    transition = {
        "kind": "materialization", "reason": "zero_duration_oxidation",
        "category": "oxidation", "inherited": False,
        "initial_geometry": {
            "material": "Si",
            "bounds_um": [-x_extent / 2.0, x_extent / 2.0, -depth, 0.0],
            "material_instance_id": _SUBSTRATE_INSTANCE_ID,
            "grid_delta_um": grid,
        },
    }
    if parse_fresh_zero_duration_materialization(transition) is None:
        raise ValueError(
            f"recipe bounds do not describe a valid virgin Si wafer: "
            f"x_extent_um={x_extent}, silicon_depth_um={depth}, grid_delta_um={grid}")
    return transition


def initial_wafer_state_from_recipe(
    recipe: dict, *, material: str = "Si",
) -> v2.WaferStateV2:
    """Build a MODELLED initial `WaferStateV2` from a domain-construction
    recipe's OWN explicit bounds.

    `tcad.backends.viennaps.session.create_domain` / `make_mask_spans`
    build the virgin substrate box at exactly
    ``x in [-x_extent_um/2, +x_extent_um/2]``,
    ``y in [-silicon_depth_um, 0.0]`` -- surface at y=0, substrate
    extending down. Those four numbers come straight from the recipe the
    caller is about to hand ViennaPS; NONE of them is read back from an
    exported mesh, a y_max heuristic, or a material name (design doc
    2026-09-10 Sec7.2, the user's P0 "명시적 초기 geometry 초기화 경로").

    `silicon_depth_um` is REQUIRED (P1) -- there used to be a private
    fallback default (a literal duplicate of
    `tcad.backends.viennaps.io.DEFAULT_FLOOR_DEPTH_UM`) that let this
    function build a MODELLED cell from a GUESSED depth when the recipe
    didn't actually carry one. That contradicts this function's own
    contract ("never read back... never invented"): a recipe with no
    exact depth is a Group-B source and must not produce a MODELLED
    cell at all -- raise instead, so the caller falls back to the
    legacy path.

    A caller uses this ONLY when the geometry it is about to build is a
    genuine virgin rectangle (no resist pattern, no prior real process
    step). Anything already etched / oxidised / re-masked has no exact
    y_min in its source input and stays LEGACY_UNRESOLVED via
    `advance_wafer_state(None, ...)`.
    """
    half_x = float(recipe["x_extent_um"]) / 2.0
    depth = float(recipe["silicon_depth_um"])  # KeyError, not a guess, if absent
    return v2.initialize_wafer_state(
        cells=[(material, (-half_x, half_x, -depth, 0.0),
                f"{material.lower()}#substrate")],
        grid_delta_um=float(recipe.get("grid_delta_um", 0.0)),
    )


def advance_wafer_state(
    prior_state: Optional[v2.WaferStateV2],
    result: Optional[ProcessResult],
    category: str,
    transform: Optional[v2.GeometryTransform] = None,
    *,
    target_instance_id: Optional[str] = None,
    barrier_windows: Optional[List[Dict[str, float]]] = None,
    barrier_axis: str = "x",
) -> v2.WaferStateV2:
    """Advance the accumulating v2 state by one process step.

    prior_state : the prior `WaferStateV2` (or None on the first step).
    result      : the step's `ProcessResult` (or any object exposing
                  `.doping`) -- used ONLY to read the step's declared
                  doping profiles and, when `result.metadata` is a dict,
                  its `state_transition`; never to infer geometry. A
                  result with no `metadata` (or a non-dict one) simply
                  has no transition -- that is NEVER read as a
                  zero-duration identity. `result` may be None ONLY for
                  a non-"doping" step advanced from an existing
                  `prior_state` (e.g. anneal, which has no mesh/result of
                  its own and is fail-closed with transform=None);
                  None with no prior state, or None for a "doping" step,
                  raises ValueError -- there is nothing to build a state
                  or an attachment from, and none is invented.
    category    : the process category ("doping", "etching", ...).
    transform   : an explicit `GeometryTransform` when the caller knows
                  the step's exact rectangles + target instances;
                  otherwise None -> the geometry change is
                  `UNSUPPORTED_BY_MODEL`.
    target_instance_id : (doping only, P0-A) the exact instance this
                  application's dopant binds to. Required whenever more
                  than one ACTIVE+MODELLED instance of the profile's
                  `host_material` exists, or that instance has been
                  split across more than one cell -- omitting it in
                  either case fails closed (UNSUPPORTED) rather than
                  guessing "the first matching cell". Safe to omit when
                  there is exactly one such instance and it is exactly
                  one cell.
    barrier_windows, barrier_axis : (doping only, P0-C) rectangles this
                  application's OWN new attachment cannot exactly reach
                  (e.g. SiO2 covering part of the doped region). Each
                  window is subtracted from the new attachment's support
                  region at attach time; if that carve is not exactly
                  one resulting rectangle (fully covered, or split into
                  multiple disjoint pieces -- this project has no
                  supported mask/implant configuration equation to
                  quantify a partial block), the WHOLE new application
                  fails closed rather than inventing a partial number.
                  Never applied to any attachment already in
                  `prior_state` -- pre-existing/background dopant is
                  untouched.
    """
    if result is None:
        if category == "doping":
            raise ValueError(
                "advance_wafer_state: a 'doping' step requires a result "
                "carrying its DopingProfile; result=None cannot attach "
                "any dopant")
        if prior_state is None:
            raise ValueError(
                "advance_wafer_state: result=None requires a prior_state "
                "to advance; with no prior state there is no geometry to "
                "migrate and none is invented")
    metadata = getattr(result, "metadata", None)
    transition = metadata.get("state_transition") if isinstance(metadata, dict) else None
    if category == "oxidation":
        if prior_state is not None and is_canonical_inherited_zero_duration_identity(transition):
            return prior_state
        geometry = parse_fresh_zero_duration_materialization(transition)
        if geometry is not None and prior_state is None:
            # The backend built a brand-new virgin Si wafer and there is no
            # earlier state to reconcile it with: the initial state IS that
            # explicit geometry (MODELLED Si cell, no dopant, no oxidation
            # event -- only the initial-geometry provenance).
            return v2.initialize_wafer_state(
                cells=[(geometry["material"], tuple(geometry["bounds_um"]),
                        geometry["material_instance_id"])],
                grid_delta_um=float(geometry["grid_delta_um"]),
            )
        # A fresh materialization with a prior state falls through to the
        # fail-closed path below: the backend did not inherit the prior
        # domain, and nothing here proves the prior geometry / lineage /
        # dopant describes the new one. Never `return prior_state`, and no
        # "same bounds" exception -- equal bounds do not prove equal history.

    state = prior_state

    if state is None:
        # No prior v2 state: migrate the step's own mesh geometry as
        # LEGACY_UNRESOLVED (design doc Sec7.0) -- a mesh has no exact,
        # trusted per-material y_min, so it is never promoted to a
        # MODELLED rectangle here.
        legacy_cells = WaferState.from_process_result(result)._cells
        state = v2.legacy_state_from_v1_cells(legacy_cells)

    if not category:
        # No process step actually ran (e.g. the GUI's
        # _materialize_current_wafer, which only exports the wafer as it
        # already is). No process => no state transition: return the
        # state untouched rather than fail-closing it.
        return state

    # Geometry step: advance through the explicit transform (or fail
    # closed with no transform).
    if category != "doping":
        return v2.advance(state, transform, step_seed=category)

    # Doping step: geometry unchanged; attach each declared profile.
    if transform is not None:
        state = v2.advance(state, transform, step_seed="doping")
    if result.doping is None:
        return state

    plan = []
    for profile in dopant_profiles_from_doping_profile(result.doping):
        instance_id, support_region = _desired_target(
            state, profile.host_material, target_instance_id,
            barrier_windows, barrier_axis)
        plan.append((profile, instance_id, support_region))

    # ONE request is all-or-nothing. A profile's attachability depends only
    # on the cells/support/integral, never on its siblings, so each is
    # first tried against the SAME base state. If some would attach and
    # some would not, no active attachment may remain from this request:
    # every profile of it is recorded as refused (provenance + ledger,
    # no numbers), and every prior attachment is preserved untouched.
    would_attach = [
        len(_attach_planned(state, item).attachments) > len(state.attachments)
        for item in plan
    ]
    partial = any(would_attach) and not all(would_attach)
    for item, ok in zip(plan, would_attach):
        state = _attach_planned(
            state, item,
            refuse_reason=(
                "the doping request is refused as a whole: another profile of "
                "the same request cannot be attached (atomic request)"
                if partial and ok else None),
        )
    return state


def _attach_planned(state, item, refuse_reason=None):
    """Attach (or refuse) ONE planned profile of a doping request."""
    profile, instance_id, support_region = item
    return v2.attach_dopant(
        state,
        species=profile.species,
        polarity=profile.polarity,
        chemical_state=profile.chemical_state,
        concentration_at=profile.concentration_at,
        inventory_integral=_exact_integral_for(profile),
        support_instance_id=(
            instance_id if instance_id is not None
            else f"__no_unambiguous_target_for_{profile.host_material}__"
        ),
        support_region_um=support_region,
        model=profile.model,
        model_params=profile.model_params,
        provenance=profile.source,
        # `attach_dopant()`'s own `_IdGen` restarts at "att:1"/"evt:1"
        # for every call that shares the same step_seed -- its
        # default ("") collides across every SEPARATE call to
        # advance_wafer_state(..., "doping") (e.g. a background
        # application followed later by a new masked one), which
        # would give two real, distinct attachments the identical
        # attachment_id. `len(state.events)` grows monotonically
        # with every event this module or attach_dopant ever
        # appended, including across a request's own profiles, so it
        # is a simple, deterministic, always-unique seed here.
        step_seed=f"doping:{len(state.events)}",
        refuse_reason=refuse_reason,
    )


def _desired_target(
    state: v2.WaferStateV2, host_material: str, target_instance_id: Optional[str],
    barrier_windows: Optional[List[Dict[str, float]]], barrier_axis: str,
) -> Tuple[Optional[str], Optional[v2.Bounds]]:
    """The (material instance, exact support rectangle) a doping profile of
    `host_material` means on the state's CURRENT geometry, after the same
    barrier carve a first application applies -- the ONE definition shared by
    `advance_wafer_state` (attach) and `canonical_doping_request_matches`
    (reattach), so the two can never disagree. (None, None) when the target is
    ambiguous or the carve is not exactly one rectangle."""
    instance_id, support = _resolve_doping_target(state, host_material, target_instance_id)
    if support is not None and barrier_windows:
        carved = _carve_support_around_barrier(support, barrier_windows, barrier_axis)
        if carved is None:
            return None, None
        support = carved
    return instance_id, support


def canonical_doping_request_matches(
    state: Optional[v2.WaferStateV2],
    doping,
    target_instance_id: Optional[str] = None,
    barrier_windows: Optional[List[Dict[str, float]]] = None,
    barrier_axis: str = "x",
):
    """Does the canonical state ALREADY hold every profile of this doping
    request? Returns `(matched, attachments, reason)`.

    A request matches only when EACH of its profiles has its own distinct
    attachment that is EXACTLY what the request means now: the same material
    INSTANCE, `model`, exact `model_params` (which carry the requested
    concentrations), `species`, `polarity`, `chemical_state`, and the same
    exact support rectangle -- `support_region_um == ` the desired support the
    request computes from the CURRENT geometry and the SAME barrier windows an
    application would use (`_desired_target`). Rectangle equality is exact: no
    tolerance, no "contained in the geometry", no sampling. So a strict
    subset or superset of the desired support, a different barrier carve, an
    unknown support or a request whose desired support is ambiguous never
    match. After a geometry step that clips both the cell and the attachment
    identically, the two are equal again and the request matches. No
    runtime-callable identity is used. Any other attachment on the wafer --
    an earlier, different doping -- is irrelevant and never makes this true.
    """
    if not isinstance(state, v2.WaferStateV2) or doping is None:
        return False, (), "no canonical WaferStateV2 or no doping request"
    profiles = dopant_profiles_from_doping_profile(doping)
    if not profiles:
        return False, (), "the request has no non-zero dopant profile"
    remaining = list(state.attachments)
    matched = []
    for p in profiles:
        instance_id, desired = _desired_target(
            state, p.host_material, target_instance_id, barrier_windows, barrier_axis)
        if instance_id is None or desired is None:
            return False, (), (f"the {p.host_material!r} target instance / desired support is "
                               f"not unambiguous on the current geometry")
        found = next((
            a for a in remaining
            if a.support_instance_id == instance_id
            and a.model == p.model
            and a.model_params == p.model_params
            and a.species == p.species
            and a.polarity == p.polarity
            and a.chemical_state == p.chemical_state
            and a.support_region_um == desired
        ), None)
        if found is None:
            return False, (), (
                f"no canonical attachment on instance {instance_id!r} has the same "
                f"model/params/species/polarity/chemical_state AND the exact desired support "
                f"{desired} ({p.polarity} {p.species!r} {p.model} {p.chemical_state}) "
                f"as this request")
        remaining.remove(found)
        matched.append(found)
    return True, tuple(matched), "every requested profile has its own canonical attachment"


def _resolve_doping_target(
    state: v2.WaferStateV2, host_material: str, target_instance_id: Optional[str],
) -> Tuple[Optional[str], Optional[v2.Bounds]]:
    """Resolve (instance_id, support_region_um) for a doping profile
    targeting `host_material`. Returns (None, None) when the target
    cannot be resolved unambiguously -- the caller must then fail
    closed (a sentinel instance id that `attach_dopant()` refuses).

    - `target_instance_id` given: that instance must correspond to
      EXACTLY ONE ACTIVE+MODELLED cell right now (a single exact
      rectangle). An instance split across multiple cells has no
      single Bounds to hand `attach_dopant()`, so it is refused rather
      than silently binding to an arbitrary one of its cells.
    - `target_instance_id` omitted: auto-select ONLY when there is
      EXACTLY ONE ACTIVE+MODELLED instance of `host_material` AND that
      instance is exactly one cell. Two (or more) instances of the same
      material (e.g. an original substrate plus a later re-deposited
      layer of the same material) are inherently ambiguous by material
      name alone and must fail closed without an explicit target --
      never "whichever cell came first in the list".
    """
    candidates = [c for c in state.active_cells()
                  if c.is_modelled and c.material == host_material]
    if target_instance_id is not None:
        matches = [c for c in candidates
                   if c.material_instance_id == target_instance_id]
        if len(matches) == 1:
            return target_instance_id, matches[0].bounds_um
        return None, None

    instance_ids = sorted({c.material_instance_id for c in candidates})
    if len(instance_ids) != 1:
        return None, None
    only_id = instance_ids[0]
    matches = [c for c in candidates if c.material_instance_id == only_id]
    if len(matches) != 1:
        return None, None
    return only_id, matches[0].bounds_um


def _carve_support_around_barrier(
    support_region_um: v2.Bounds,
    barrier_windows: List[Dict[str, float]],
    axis: str,
) -> Optional[v2.Bounds]:
    """Subtract each barrier window (a full-depth strip along `axis`)
    from `support_region_um`. Returns the single remaining rectangle
    when the carve is EXACT (one clean piece left); None when the
    barrier fully covers the support or splits it into more than one
    disjoint piece -- this project has no supported mask/implant
    energy-dose configuration equation to quantify either case, so the
    caller must refuse the whole new attachment rather than invent a
    partial number (P0-C)."""
    x0, x1, y0, y1 = support_region_um
    remaining: List[v2.Bounds] = [support_region_um]
    for w in barrier_windows:
        if axis == "x":
            strip = (w["min_um"], w["max_um"], y0, y1)
        else:
            strip = (x0, x1, w["min_um"], w["max_um"])
        nxt: List[v2.Bounds] = []
        for r in remaining:
            nxt.extend(v2.rect_subtract(r, strip))
        remaining = nxt
        if not remaining:
            return None
    if len(remaining) == 1:
        return remaining[0]
    return None


def _exact_integral_for(profile):
    """Build the profile's EXACT closed-form inventory integral, or None
    when the model has no closed form (design doc Sec5.2 -- never a
    numeric approximation)."""
    mp = profile.model_params or {}
    if profile.model == "uniform_v1" and "conc_cm3" in mp:
        return v2.uniform_inventory_integral(mp["conc_cm3"])
    if profile.model == "step_junction_v1" and {"conc_cm3", "junction_position_um"} <= mp.keys():
        side = "x_ge" if profile.polarity == "donor" else "x_le"
        return v2.step_inventory_integral(mp["conc_cm3"], mp["junction_position_um"], side)
    if profile.model == "gaussian_v1" and {"peak_conc_cm3", "peak_position_um", "straggle_um"} <= mp.keys():
        return v2.gaussian_inventory_integral(
            mp["peak_conc_cm3"], mp["peak_position_um"], mp["straggle_um"])
    if profile.model == "implant_windows_v1" and "background_cm3" in mp:
        windows = tuple((lo, hi, c) for lo, hi, c in mp.get("windows", []))
        return v2.windowed_inventory_integral(mp["background_cm3"], windows)
    return None
