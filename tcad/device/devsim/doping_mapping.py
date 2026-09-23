#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Write real per-node NetDoping into a DevSim region from a WaferStateV2.

Every real DevSim mesh node is evaluated with
`WaferStateV2.net_doping_at(x_um, y_um)` and the results written back
with `set_node_values`, after registering each node model with
`node_model(equation="0")` (DevSim requires a model to be registered
before its values can be overwritten).

WaferState v2 migration (docs/superpowers/specs/2026-09-10-waferstate-v2-design.md
Sec7): `apply_doping()` takes a WaferStateV2, not the v1 WaferState.
There is NO RECOVERY loop, NO `exposed_material_at()` fallback, and NO
substitution of 0.0 for an unknown. If ANY node's `net_doping_at()`
comes back `UNSUPPORTED_BY_MODEL` (or `net_doping is None`),
`apply_doping()` raises `UnsupportedDopingState` and writes nothing --
the device solve must not proceed on a partial or zeroed NetDoping.

Barrier exclusion (P0-C, user correction): `apply_doping()` no longer
takes any `exclude_windows` -- an earlier version zeroed the whole
ACCUMULATED NetDoping inside a barrier window regardless of WHICH
attachment produced it, which silently erased real pre-existing /
background dopant that was there before the barrier ever formed (this
project has no oxide-penetration energy/dose model, but that is a
reason to refuse to quantify a NEW implant there, never a reason to
erase an OLD one). A barrier now only ever carves the SUPPORT REGION
of a brand-new attachment, at attach time, in
`tcad.physics.wafer_state_accumulation.advance_wafer_state()`'s own
`barrier_windows` parameter -- see that function's docstring. By the
time a `WaferStateV2` reaches `apply_doping()`, `net_doping_at()`
already reflects every attachment's own real support region correctly;
this module trusts that value as-is and never re-masks it.

Central canonical-state gate (Tier 1-1): `canonical_node_doping()` is
the ONE check every electrical measurement passes before any doping is
written to DevSim or any solve runs -- `apply_doping()` here and
`tcad.characterization.robust_iv_sweep.ramp_doping_to_equilibrium` both
call it first. Only the canonical `WaferStateV2` decides; a process
result's own `DopingProfile` is never a substitute for it. The gate
checks GEOMETRY before it trusts a number: a node passes only when
exactly one ACTIVE + MODELLED cell OF THE DEVSIM REGION'S OWN MATERIAL
contains it -- a cell of a DIFFERENT material merely sharing a boundary
(e.g. Si's y_max == SiO2's y_min) is not ambiguity, since DevSim's
`region` argument already names which electrical-analysis region the
node belongs to; two cells whose rectangles overlap with positive area
(a genuine inconsistency, not a shared edge) still blocks regardless of
material (see `canonical_node_doping()` / `_ownership_problem()`).

Ownership is decided at the RAW coordinate first; a unique same-region
owner there is used as-is, no snap. Only when the raw point has none
(Tier 1-1 r4: including when it lies just inside a DIFFERENT material's
neighboring cell -- a float32 round-trip error can push a node a few
ULPs across a real interface) is a snap tried, and the snap SEARCH
itself looks only at ACTIVE + MODELLED cells of the region's OWN
material, so an unrelated cell that already contains the raw point can
never shadow a same-region cell's real boundary a few ULPs away. A
candidate snap is accepted only within that boundary's own float32
mesh-serialization round-trip tolerance (`_float32_roundtrip_ulp_um()`)
-- correcting for DevSim node coordinates being the mesh file's float32
vertex coordinates times `length_scale_to_cm`, never a real geometry
mismatch -- and ownership is then RE-DECIDED at the snapped point
against every present cell there, so a positive-area overlap, two
same-region cells, or an inactive/unbounded cell at that exact point
still blocks exactly as it would anywhere else. `net_doping_at()` is
queried at the final (possibly snapped) point with the final resolved
owner, never at the raw point with a stale one.

`apply_doping_symbolic()` below is the OLD kind-based
equation-string writer, preserved verbatim under its own name. It
writes NetDoping from a `DopingProfile` (the latest doping declaration),
not from the canonical state, so no production measurement path may
call it any more (pinned by
tests/unit/test_measurement_canonical_state_gate_mock.py).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

import numpy as np

from tcad.device.devsim import backend
from tcad.mesh.interface import DopingProfile

if TYPE_CHECKING:
    from tcad.physics.wafer_state_v2 import WaferStateV2


class UnsupportedDopingState(RuntimeError):
    """Raised by the central gate, canonical_node_doping() (and so by
    every measurement path built on it), when no canonical WaferStateV2
    exists, a node is not owned by exactly one ACTIVE + MODELLED cell of
    the region's material, or the state cannot supply a fully-known
    active NetDoping there (a LEGACY_UNRESOLVED region, a fail-closed
    step, an oxidation-converted region, or any node whose net_doping is
    None). The device solve MUST NOT proceed with a partial or zeroed
    NetDoping -- see this module's own docstring and
    docs/superpowers/specs/2026-09-10-waferstate-v2-design.md Sec7.4.

    It is ALSO raised when every per-node concentration is fully known
    (donor/acceptor/net all real numbers) but a REGION-LEVEL transport
    CAPABILITY has not been verified -- concentration mapping and
    transport capability are separate questions. Two such capability
    reasons exist today, checked in this fixed order, never merged into
    one reason_code: `COMPENSATED_TRANSPORT_MODEL_MISSING` (a donor and
    an acceptor of finite area coexist -- no compensation-aware
    ionized-impurity scattering/mobility model) and
    `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` (an ACTIVE
    `step_junction_v1` attachment on a 2D DevSim device -- Batch 7D
    Rev.2's own real mesh-refinement study found the 2D terminal
    current/field/R1-R2 agreement does not converge; a real 1D device
    with the identical state is NOT blocked by this reason). A DIRECT
    `WaferStateV2.net_doping_at()` query is never affected by either
    capability gate -- both raise only from `canonical_node_doping()`,
    after the per-node checks below already passed.

    `physics_status` carries the blocking diagnostics (first blocked
    node, the cells and instances found there, the canonical query's
    own status, blocked/total node counts) for a per-node block, or
    `reason_code`/`entries`/`notes` naming the capability problem (with
    `first_blocked_node: None`) for a region-level block; the message
    states them either way."""

    def __init__(self, message: str, physics_status: dict):
        super().__init__(message)
        self.physics_status = physics_status


def canonical_node_doping(
    device: str,
    region: str,
    state: Optional["WaferStateV2"],
    length_scale_to_cm: float = 1.0,
) -> Tuple[List[float], List[float], List[float]]:
    """THE central canonical-state gate for every electrical measurement.

    Read-only: it reads the DevSim node coordinates of `region` and
    nothing else -- it never registers or writes a node model and never
    solves. Returns the canonical per-node (donors, acceptors, nets),
    exactly as `state.net_doping_at()` reports them.

    Geometry first, then the number. A node passes only when EXACTLY ONE
    present, ACTIVE + MODELLED cell WHOSE MATERIAL IS THE DEVSIM REGION'S
    OWN MATERIAL contains it -- a different-material cell merely
    touching the same boundary (e.g. Si's y_max == SiO2's y_min, a
    zero-area shared edge) is not ambiguity, since `region` already
    names which electrical-analysis region this node belongs to; two
    cells whose rectangles overlap with POSITIVE area is still blocked
    regardless of material (a genuine geometry inconsistency, never a
    benign shared edge -- see `_ownership_problem()`). Only once
    ownership resolves is `state.net_doping_at()` trusted, and only when
    it carries no physics_status and no None concentration. So a
    known-undoped 0.0 is accepted only for a node inside exactly one
    supported same-material cell with no active attachment covering it
    -- never for a node no such cell owns.

    Ownership is decided at the node's EXACT (raw) coordinates first. A
    node with no valid same-region owner there -- because nothing
    contains it exactly, OR (Tier 1-1 r4) because a float32 round-trip
    error pushed it a few ULPs across a real interface into a
    DIFFERENT material's neighboring cell, which the raw check then
    finds instead -- is tried once more with coordinates SNAPPED onto
    the nearest boundary of an ACTIVE + MODELLED cell of the REGION'S
    OWN material specifically (a neighboring cell of another material
    that already contains the raw point can never shadow that search),
    but only within that boundary's own float32 mesh-serialization
    round-trip tolerance (`_float32_roundtrip_ulp_um()`) -- DevSim node
    coordinates are the mesh's float32 vertex points times
    `length_scale_to_cm` (`import_process_result`), so a node on a
    canonical edge can read back up to 1 float32 ULP to either side of
    it (4.8 um wide: x = 2.4000001 um; a 0.6 um Si/SiO2 interface: y =
    0.6000000212 um, landing a Si-owned node 2.1e-8 um inside SiO2).
    Once a candidate snap point is found, ownership is RE-DECIDED there
    against every present cell (not just same-region ones): a
    positive-area overlap, 2+ same-region cells, or an inactive /
    unbounded cell at that exact point still blocks, same as anywhere
    else. This corrects the serialization round-trip only: an interior
    node whose raw coordinates already have a valid owner is never
    snapped, and a node whose nearest same-region boundary is farther
    than 1 ULP, or reachable from 2+ DIFFERENT same-region boundaries,
    is never snapped either -- it stays blocked on its raw coordinates
    and their own ownership problem, a real geometry mismatch.
    `net_doping_at()` is queried at the final (possibly snapped) point
    with the final resolved owner, never the raw point with a stale one.

    Concentration mapping is not the whole gate: once every node above
    has a fully-known concentration, two REGION-LEVEL transport
    CAPABILITY checks still run, in this fixed order, before any array is
    returned -- (a) `wafer_state_v2.compensated_transport_problems()`
    (a donor and an acceptor of finite area coexist in the region's
    material: reason_code COMPENSATED_TRANSPORT_MODEL_MISSING), then, only
    if (a) found nothing, (b) `wafer_state_v2.active_step_junction_instances()`
    combined with the real `devsim.get_dimension()` (an ACTIVE
    step_junction_v1 attachment on a 2D device: reason_code
    STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED). The two reasons are
    never merged into one reason_code, even when both apply to the same
    region -- see `UnsupportedDopingState`'s own docstring. This is the
    one place every DevSim doping write goes through, so both checks live
    here, not in a caller, and this function stays read-only either way.

    Raises `UnsupportedDopingState` -- and the caller must then write no
    doping, run no solve and report no number -- when `state` is None or
    not a canonical WaferStateV2, or when ANY node (after any snap) has
    zero or several same-material owning cells, a positive-area cell
    overlap, lies in a LEGACY_UNRESOLVED / UNRESOLVED cell or a cell
    without bounds, or has an unknown canonical query. One such node
    blocks the whole region; an unknown is never replaced by 0.0, by the
    latest process result's DopingProfile, or by a legacy state. The
    exception's message and `physics_status` name the first blocked node
    (x/y um, region), the material instances and cells (material,
    lifecycle, bounds) found there, why it is blocked, the canonical
    query's own status there, and blocked/total node counts.
    """
    from tcad.physics.wafer_state_v2 import WaferStateV2

    module = backend.require_devsim()
    xs_native = module.get_node_model_values(device=device, region=region, name="x")
    ys_native = module.get_node_model_values(device=device, region=region, name="y")

    points = [(x / length_scale_to_cm, y / length_scale_to_cm) for x, y in zip(xs_native, ys_native)]

    # A state-level block holds for every node alike -- no canonical
    # state, or a present cell with no bounds (it may contain any node) --
    # so only the first node is diagnosed; the rest are counted, not scanned.
    state_block = None
    present: list = []
    if state is None:
        state_block = "no canonical WaferStateV2 exists for this wafer"
    elif not isinstance(state, WaferStateV2):
        state_block = (f"the state is a {type(state).__name__}, not a canonical WaferStateV2 "
                       f"(no material instances, lifecycles or exact 2D bounds to check ownership against)")
    else:
        present = [c for c in state.cells if c.lifecycle not in _HISTORICAL_LIFECYCLES]
    bounded = [c for c in present if c.bounds_um is not None]

    donors: List[float] = []
    acceptors: List[float] = []
    nets: List[float] = []
    entries: List[dict] = []
    reasons: List[str] = []
    first: Optional[dict] = None
    blocked = 0
    if state_block is not None or len(bounded) < len(present):
        blocked = len(points)
        if points:
            x_um, y_um = points[0]
            if state_block is not None:
                first = _diagnosis(x_um, y_um, region, [], None, state_block)
                entries = [_entry("canonical_wafer_state", region, state_block)]
            else:
                found = [c for c in present if c.bounds_um is None or _contains(c.bounds_um, x_um, y_um)]
                result = state.net_doping_at(x_um, y_um)
                first = _diagnosis(x_um, y_um, region, found, result,
                                   _ownership_problem(state, region, found))
                entries = [_entry("canonical_cell_ownership", region, first["reason"])] + list(
                    (result.physics_status or {}).get("entries", []))
            reasons = [first["reason"]]
        else:
            reasons = [state_block or "a present cell has no exact bounds"]
    else:
        for x_um, y_um in points:
            # Ownership is evaluated at the RAW coordinate FIRST (Tier
            # 1-1 r4). A unique ACTIVE+MODELLED same-region owner there
            # is used as-is -- no snap. Only when the raw point has NO
            # such owner (found empty, or found non-empty but owned by
            # a DIFFERENT material entirely -- e.g. a float32 round-trip
            # error pushed it a few ULPs into a neighboring material's
            # cell) do we try a snap, and the snap SEARCH itself only
            # ever looks at ACTIVE+MODELLED cells of the region's OWN
            # material: an unrelated cell that already happens to
            # contain the raw point must never shadow a same-region
            # cell's real boundary a few ULPs away.
            found = [c for c in bounded if _contains(c.bounds_um, x_um, y_um)]
            why = _ownership_problem(state, region, found)
            owner = _same_region_owner(region, found) if why is None else None
            if owner is None:
                same_region_active = [c for c in bounded if c.material == region and c.lifecycle == "ACTIVE"]
                snap = _snap_to_canonical_boundary(x_um, y_um, same_region_active, length_scale_to_cm)
                if snap is not None:
                    sx, sy, _snap_cells = snap
                    # Re-resolve ownership at the SNAPPED point against
                    # EVERY present bounded cell (not just same-region
                    # ones): a positive-area overlap, two same-region
                    # cells meeting there, or an inactive/unbounded cell
                    # at that exact point must still block, exactly as
                    # they would for any other node.
                    snapped_found = [c for c in bounded if _contains(c.bounds_um, sx, sy)]
                    snapped_why = _ownership_problem(state, region, snapped_found)
                    x_um, y_um, found, why = sx, sy, snapped_found, snapped_why
                    owner = _same_region_owner(region, found) if why is None else None
            # Once ownership resolves, query net_doping_at() FOR that
            # exact cell -- not net_doping_at()'s own largest-y_max
            # tie-break, which would silently pick a DIFFERENT material's
            # cell merely sharing the same boundary (see
            # canonical_node_doping()'s own docstring).
            result = state.net_doping_at(x_um, y_um, owning_cell=owner)
            status_entries = (result.physics_status or {}).get("entries", [])
            if why is not None:
                node_entries = [_entry("canonical_cell_ownership", region, why)] + status_entries
            elif result.physics_status is not None or None in (
                    result.donor_concentration, result.acceptor_concentration, result.net_doping):
                notes = "; ".join(e.get("note") or e.get("parameter", "?") for e in status_entries)
                why = f"the canonical query is not fully known here: {notes or 'donor/acceptor/net is None'}"
                node_entries = status_entries or [_entry("net_doping_at", region, why)]
            else:
                donors.append(result.donor_concentration)
                acceptors.append(result.acceptor_concentration)
                nets.append(result.net_doping)
                continue
            blocked += 1
            if why not in reasons:
                reasons.append(why)
            for e in node_entries:
                if e not in entries:
                    entries.append(e)
            if first is None:
                first = _diagnosis(x_um, y_um, region, found, result, why)
        if first is None:
            # Batch 7E Rev.1: every node passed per-node geometry/ownership/
            # activation (items 1-5 of canonical_node_doping()'s own
            # docstring) -- only NOW do the two REGION-LEVEL transport-
            # capability gates run, in a fixed order so neither reason can
            # silently hide the other when a state happens to carry both
            # problems at once (a real, if unusual, possibility: e.g. a
            # step_junction_v1 attachment later overlapped by a separately-
            # attached counter-dope on the same instance):
            #   (a) compensated transport (pre-existing, Batch 7C/7D)
            #   (b) 2D step-junction mesh convergence (Batch 7E) -- checked
            #       only when (a) found nothing, so the pre-existing
            #       compensation contract and its tests are byte-for-byte
            #       unchanged when no step-junction attachment is present.
            # DEVICE DIMENSION is decided by the real public
            # devsim.get_dimension() API, queried only when a step-junction
            # attachment is actually present (a device/mock with no
            # step_junction_v1 attachment never pays for this call).
            from tcad.physics.wafer_state_v2 import (
                COMPENSATED_TRANSPORT_REASON, STEP_JUNCTION_2D_REASON,
                active_step_junction_instances, compensated_transport_problems)

            comp_problems = compensated_transport_problems(state, region)
            step_instances = active_step_junction_instances(state, region)
            step_problem = bool(step_instances) and module.get_dimension(device=device) == 2

            if not comp_problems and not step_problem:
                return donors, acceptors, nets

            n = len(points)
            if comp_problems:
                # Concentration preservation and transport capability are separate:
                # the canonical donor/acceptor/net stay valid, but no compensation-
                # aware ionized-impurity scattering / mobility model exists, so no
                # doping is written, no solve may run and no current is reported.
                scope = f"{n} of {n} mesh node(s) blocked (region-level: compensated region)"
                notes = [scope]
                trailer = []
                if step_problem:
                    # Never silently dropped: a co-occurring step-junction
                    # problem is named here, even though COMPENSATED_TRANSPORT
                    # keeps precedence as the reported reason_code (the two
                    # reasons are never merged into one -- see
                    # STEP_JUNCTION_2D_REASON's own message below for the
                    # reverse ordering, which cannot happen here since
                    # compensation is checked first).
                    co_note = (f"NOTE: this region ALSO carries an ACTIVE step_junction_v1 "
                              f"attachment on a 2D device ({STEP_JUNCTION_2D_REASON}) -- not "
                              f"reported as the reason_code here because a compensated-transport "
                              f"problem takes precedence, but not silently dropped either.")
                    notes.append(co_note)
                    trailer.append(co_note)
                raise UnsupportedDopingState(
                    "\n".join([
                        f"UNSUPPORTED_BY_MODEL ({COMPENSATED_TRANSPORT_REASON}): device "
                        f"{device!r} region {region!r} holds donor AND acceptor dopant over a "
                        f"finite area ({scope}). The canonical concentrations are kept, but the "
                        f"drift-diffusion model has no compensation-aware ionized-impurity "
                        f"scattering / mobility, so the device solve must not proceed.",
                        *comp_problems[:3],
                        *trailer,
                    ]),
                    {
                        "resolution": "UNSUPPORTED_BY_MODEL",
                        "reason_code": COMPENSATED_TRANSPORT_REASON,
                        "entries": [_entry("compensated_transport", region, p) for p in comp_problems],
                        "notes": notes, "device": device, "region": region,
                        "total_nodes": n, "blocked_nodes": n, "first_blocked_node": None,
                    },
                )

            # step_problem only (comp_problems is empty here).
            raise UnsupportedDopingState(
                "\n".join([
                    f"UNSUPPORTED_BY_MODEL ({STEP_JUNCTION_2D_REASON}): device {device!r} "
                    f"region {region!r} carries an ACTIVE step_junction_v1 dopant attachment "
                    f"on a 2D DevSim device ({n} of {n} mesh node(s) blocked). The canonical "
                    f"donor/acceptor/net concentrations are PRESERVED and remain directly "
                    f"queryable from the WaferStateV2 (state.net_doping_at() is unaffected by "
                    f"this gate) -- what is refused is specifically 2D DevSim TRANSPORT: no "
                    f"Donors/Acceptors/NetDoping node model is written, no potential-only or "
                    f"drift-diffusion solve is run, and no current, electric field or "
                    f"depletion-width number is produced. Batch 7D Rev.2's own real L0-L5 "
                    f"mesh-refinement study found the 2D step-junction terminal current, peak "
                    f"ElectricField and R1/R2 representation agreement do not converge by L5 "
                    f"(docs/audits/2026-09-21-batch7d-step-junction-convergence/rev2); the 1D "
                    f"abrupt-junction reference DOES converge, but that 1D result is never "
                    f"generalized as proof of this 2D production capability. Running another "
                    f"supported process on this wafer afterward does not resolve this capability "
                    f"gap. The device solve must not proceed.",
                ]),
                {
                    "resolution": "UNSUPPORTED_BY_MODEL",
                    "reason_code": STEP_JUNCTION_2D_REASON,
                    "device": device, "region": region,
                    "total_nodes": n, "blocked_nodes": n, "first_blocked_node": None,
                    "entries": [_entry("step_junction_2d_unverified", region,
                                       f"instance {iid!r} carries an ACTIVE step_junction_v1 "
                                       f"attachment on a 2D device")
                                for iid in step_instances],
                    "notes": [f"{STEP_JUNCTION_2D_REASON}: canonical concentrations preserved, "
                             f"2D transport (doping write + solve) not executed, no "
                             f"current/field/depletion numbers"],
                },
            )

    scope = f"{blocked} of {len(points)} mesh node(s) blocked"
    if first is None:
        node_lines = [f"First blocked node: none -- region {region!r} has no mesh nodes."]
    else:
        cells = [f"{c['cell_id']} (instance {c['material_instance_id']}, material {c['material']}, "
                 f"lifecycle {c['lifecycle']}, bounds_um {c['bounds_um']})" for c in first["cells"]]
        node_lines = [
            f"First blocked node: x={first['x_um']:.10g} um, y={first['y_um']:.10g} um "
            f"in DevSim region {region!r}.",
            f"Canonical material instance(s) containing it: "
            f"{_capped(first['material_instance_ids'], 10, ', ') or 'none'}.",
            f"Cell(s) containing it: {_capped(cells, 3, '; ') or 'none'}.",
            f"Blocked because: {first['reason']}.",
            f"Canonical query at this node: {first['query']}.",
        ]
    shown = _capped(reasons, 3, "; ")
    raise UnsupportedDopingState(
        "\n".join([
            f"UNSUPPORTED_BY_MODEL: the canonical WaferStateV2 cannot supply a "
            f"fully-known doping for device {device!r} region {region!r} "
            f"({scope}). The device solve must not proceed.",
            *node_lines,
            f"Distinct reasons over all blocked nodes: {shown or 'none'}.",
        ]),
        {
            "resolution": "UNSUPPORTED_BY_MODEL", "entries": entries, "notes": [scope],
            "device": device, "region": region,
            "total_nodes": len(points), "blocked_nodes": blocked,
            "first_blocked_node": first,
        },
    )


#: Cell lifecycles that are history, not present geometry: a REMOVED cell
#: was etched away and a CONVERTED one consumed -- their successor cells
#: and events describe what is there now.
_HISTORICAL_LIFECYCLES = ("REMOVED", "CONVERTED")


def _entry(parameter: str, region: str, note: str) -> dict:
    return {"parameter": parameter, "material": region, "resolution": "UNSUPPORTED_BY_MODEL",
            "provenance": "DERIVED", "note": note}


def _contains(bounds_um, x_um: float, y_um: float) -> bool:
    return bounds_um[0] <= x_um <= bounds_um[1] and bounds_um[2] <= y_um <= bounds_um[3]


def _capped(items: List[str], limit: int, sep: str) -> str:
    """At most `limit` items, then a count -- a migrated legacy state can
    carry thousands of cells, which must not flood the GUI log."""
    return sep.join(items[:limit]) + (f" (+{len(items) - limit} more)" if len(items) > limit else "")


def _diagnosis(x_um: float, y_um: float, region: str, found: list, result, why: str) -> dict:
    return {
        "x_um": x_um, "y_um": y_um, "region": region,
        "material_instance_ids": list(dict.fromkeys(c.material_instance_id for c in found)),
        "cells": [{"cell_id": c.cell_id, "material_instance_id": c.material_instance_id,
                   "material": c.material, "lifecycle": c.lifecycle, "bounds_um": c.bounds_um}
                  for c in found],
        "reason": why,
        "query": f"not run -- {why}" if result is None else _query_text(result),
        "query_physics_status": None if result is None else result.physics_status,
    }


def _ownership_problem(state: "WaferStateV2", region: str, found: list) -> Optional[str]:
    """Why the present cells `found` at a node (bounds containing it, or
    no bounds at all) do not make exactly one ACTIVE + MODELLED cell of
    `region`'s material its owner; None when they do.

    A cell of a DIFFERENT material merely present at this node (e.g. the
    Si cell owning a Si/SiO2 interface node, with the SiO2 cell only
    touching the same boundary) is not itself a problem -- DevSim's
    `region` argument already names which electrical-analysis region
    this node belongs to, so only cells of THAT material are owner
    candidates. What IS always a problem: a cell with no exact bounds
    (unknown geometry), a non-ACTIVE cell (stale/history geometry), two
    cells whose rectangles overlap with POSITIVE area (a genuine
    geometry inconsistency -- two solids occupying the same space, never
    a benign shared edge), more than one same-material candidate (an
    instance split across cells, or two instances touching -- Tier 2
    territory), or none at all."""
    unbounded = [c for c in found if c.bounds_um is None]
    if unbounded:
        c = unbounded[0]
        more = f" (as may {len(unbounded) - 1} more cell(s) without bounds)" if len(unbounded) > 1 else ""
        return (f"cell {c.cell_id} ({c.material}, lifecycle {c.lifecycle}) has no exact bounds, "
                f"so it may contain this node{more} -- ownership cannot be decided")
    inactive = [c for c in found if c.lifecycle != "ACTIVE"]
    if inactive:
        c = inactive[0]
        more = f" (and {len(inactive) - 1} more non-ACTIVE cell(s))" if len(inactive) > 1 else ""
        return (f"cell {c.cell_id} containing this node has lifecycle {c.lifecycle}{more} "
                f"-- not ACTIVE modelled geometry")

    overlap = _first_positive_area_overlap(found)
    if overlap is not None:
        a, b, rect = overlap
        return (f"cell {a.cell_id} ({a.material}, bounds_um {a.bounds_um}) and cell "
                f"{b.cell_id} ({b.material}, bounds_um {b.bounds_um}) physically overlap "
                f"over a positive area {rect} -- two solids occupying the same space, an "
                f"inconsistent canonical state")

    same_region = [c for c in found if c.material == region]
    if len(same_region) > 1:
        return (f"{len(same_region)} ACTIVE modelled cells contain this node, so its owning "
                f"material instance is ambiguous")
    if same_region:
        return None
    if not found:
        same = [f"{c.material_instance_id} {c.bounds_um}" for c in state.active_cells()
                if c.material == region and c.bounds_um is not None]
        return (f"no ACTIVE modelled cell contains this node "
                f"(ACTIVE {region!r} cells: {_capped(same, 3, ', ') or 'none'})")
    other = found[0]
    more = f" (and {len(found) - 1} more)" if len(found) > 1 else ""
    return (f"the only cell containing this node is material {other.material} "
            f"(instance {other.material_instance_id}){more}, not the DevSim region's "
            f"material {region!r}")


def _same_region_owner(region: str, found: list):
    """The unique ACTIVE cell of `found` whose material is `region`, or
    None -- exactly the condition `_ownership_problem()` requires to
    return None (ownership resolved). Kept separate from that function
    (which only needs to know WHETHER ownership resolved) so
    `canonical_node_doping()` can pass the actual resolved cell to
    `state.net_doping_at(..., owning_cell=...)`."""
    same = [c for c in found if c.material == region]
    return same[0] if len(same) == 1 else None


def _first_positive_area_overlap(cells: list):
    """The first pair of `cells` (already ACTIVE, exact bounds) whose
    rectangles overlap with POSITIVE area -- not merely a shared edge or
    corner (a zero-area intersection, e.g. Si's y_max == SiO2's y_min).
    A canonical WaferStateV2's own geometry should never produce a
    positive-area overlap (etch/oxidation subtract exactly; see
    wafer_state_v2._apply_geometry_change); this exists to catch it as a
    genuine inconsistency rather than let it silently pick one cell.
    Returns (cell_a, cell_b, overlap_bounds_um) or None."""
    for i in range(len(cells)):
        a = cells[i]
        for j in range(i + 1, len(cells)):
            b = cells[j]
            x0 = max(a.bounds_um[0], b.bounds_um[0])
            x1 = min(a.bounds_um[1], b.bounds_um[1])
            y0 = max(a.bounds_um[2], b.bounds_um[2])
            y1 = min(a.bounds_um[3], b.bounds_um[3])
            if x1 > x0 and y1 > y0:
                return a, b, (x0, x1, y0, y1)
    return None


def _float32_roundtrip_ulp_um(boundary_um: float, length_scale_to_cm: float) -> float:
    """The maximum coordinate deviation (um) a canonical boundary at
    `boundary_um` can pick up purely from being serialized to the mesh
    file's float32 vertex coordinates and then scaled by
    `length_scale_to_cm` on the way into a real DevSim node.

    tcad.device.devsim.mesh_import.import_process_result computes
    `points = raw_points * length_scale_to_cm` where `raw_points` is the
    float32 array meshio read from the VTU file; a float32 numpy array
    times a plain Python float stays float32 (NEP 50 weak-scalar
    promotion -- confirmed against the installed numpy). So the node
    DevSim actually holds is float32(boundary_um) * float32(
    length_scale_to_cm), rounded to the nearest float32 -- exactly ONE
    float32 ULP of that scaled value, converted back to um by dividing
    by length_scale_to_cm. This is not an invented epsilon, a fraction
    of grid_delta_um, or a fixed constant: it depends only on the
    boundary's own magnitude and length_scale_to_cm, so it can never
    grow with mesh resolution or a user-chosen process dimension.
    Verified empirically for boundaries 0.6-50 um at length_scale_to_cm
    =1e-4 -- the real observed round-trip error stayed within this
    bound (1.5x-4.2x margin) in every case
    (docs/audits/2026-09-17-tier1-1-r3/).
    """
    b32 = np.float32(abs(boundary_um))
    s32 = np.float32(abs(length_scale_to_cm))
    scaled = b32 * s32
    return abs(float(np.spacing(scaled))) / abs(length_scale_to_cm)


def _clamp_within_tolerance(x_um, y_um, bounds_um, length_scale_to_cm):
    """`(x_um, y_um)` clamped onto `bounds_um`, only if every axis that
    needs clamping is within THAT boundary's own
    `_float32_roundtrip_ulp_um()` tolerance. None if any needed clamp
    exceeds tolerance (a real gap, however small) or if the point
    already lies exactly inside (nothing to snap -- the exact-match path
    already handles that case, this function is only ever called when it
    failed). Returns `(snapped_x, snapped_y, distance_um)`, `distance_um`
    the largest single-axis correction applied."""
    x0, x1, y0, y1 = bounds_um
    sx, sy, dist, moved = x_um, y_um, 0.0, False
    if x_um < x0:
        gap = x0 - x_um
        if gap > _float32_roundtrip_ulp_um(x0, length_scale_to_cm):
            return None
        sx, dist, moved = x0, max(dist, gap), True
    elif x_um > x1:
        gap = x_um - x1
        if gap > _float32_roundtrip_ulp_um(x1, length_scale_to_cm):
            return None
        sx, dist, moved = x1, max(dist, gap), True
    if y_um < y0:
        gap = y0 - y_um
        if gap > _float32_roundtrip_ulp_um(y0, length_scale_to_cm):
            return None
        sy, dist, moved = y0, max(dist, gap), True
    elif y_um > y1:
        gap = y_um - y1
        if gap > _float32_roundtrip_ulp_um(y1, length_scale_to_cm):
            return None
        sy, dist, moved = y1, max(dist, gap), True
    if not moved:
        return None
    return sx, sy, dist


def _snap_to_canonical_boundary(x_um, y_um, bounded_cells, length_scale_to_cm):
    """Try snapping `(x_um, y_um)` onto the boundary of each of
    `bounded_cells` (see `_clamp_within_tolerance`). Cells that reach the
    SAME snapped point are grouped together and returned as that point's
    owners -- e.g. two cells that genuinely share the exact boundary
    being snapped to. If cells reach 2+ DIFFERENT snapped points (the
    node could snap to more than one distinct boundary), that is
    ambiguous and no snap is applied. Returns
    `(snapped_x, snapped_y, owning_cells)` or None (nothing within
    tolerance, or ambiguous)."""
    reachable: Dict[Tuple[float, float], list] = {}
    for c in bounded_cells:
        r = _clamp_within_tolerance(x_um, y_um, c.bounds_um, length_scale_to_cm)
        if r is not None:
            reachable.setdefault((r[0], r[1]), []).append(c)
    if len(reachable) != 1:
        return None
    (sx, sy), cells = next(iter(reachable.items()))
    return sx, sy, cells


def _query_text(result) -> str:
    status = result.physics_status
    if status is not None:
        notes = "; ".join(e.get("note") or e.get("parameter", "?") for e in status.get("entries", []))
        return f"physics_status {status.get('resolution')} -- {notes or 'no note'}"
    return (f"physics_status None, donor={result.donor_concentration}, "
            f"acceptor={result.acceptor_concentration}, net={result.net_doping}")


def apply_doping(
    device: str,
    region: str,
    state: Optional["WaferStateV2"],
    length_scale_to_cm: float = 1.0,
) -> Optional[dict]:
    """Write real per-node NetDoping into a DevSim region from a
    `WaferStateV2` (WaferState v2 migration).

    Every real DevSim mesh node is checked for exactly one owning ACTIVE
    + MODELLED cell of the region's material and evaluated with
    `state.net_doping_at(x_um, y_um)`. If ANY node fails that ownership
    check or comes back `UNSUPPORTED_BY_MODEL` (a LEGACY_UNRESOLVED
    region, a fail-closed step, an oxidation-converted region, or a node
    covered by an attachment with no exact support / integral) this call raises
    `UnsupportedDopingState` and writes NOTHING: the device solve must
    not proceed with a partial or zeroed NetDoping. There is no
    RECOVERY loop, no `exposed_material_at()` fallback, and no
    substitution of 0.0 for an unknown -- an unknown dopant state stays
    unknown.

    No `exclude_windows` parameter (P0-C, removed): a barrier's effect
    is already baked into `state` by the time it reaches this function
    -- see `tcad.physics.wafer_state_accumulation.advance_wafer_state()`'s
    `barrier_windows` parameter, which carves a NEW attachment's own
    support region at attach time rather than this function zeroing the
    accumulated total afterward (that used to also erase real
    pre-existing/background dopant that predates the barrier).

    Returns None on full success (mirrors the previous convention), or
    raises `UnsupportedDopingState` (carrying a `physics_status` dict)
    when the state is not fully modellable -- decided entirely by the
    central gate, `canonical_node_doping()`, before anything is written.
    """
    donors, acceptors, nets = canonical_node_doping(device, region, state, length_scale_to_cm)
    module = backend.require_devsim()
    module.node_model(device=device, region=region, name="Donors", equation="0")
    module.set_node_values(device=device, region=region, name="Donors", values=donors)
    module.node_model(device=device, region=region, name="Acceptors", equation="0")
    module.set_node_values(device=device, region=region, name="Acceptors", values=acceptors)
    module.node_model(device=device, region=region, name="NetDoping", equation="0")
    module.set_node_values(device=device, region=region, name="NetDoping", values=nets)
    return None



def _exclusion_factor_expr(
    exclude_windows: Optional[List[Dict[str, float]]],
    axis: str,
    length_scale_to_cm: float,
) -> str:
    """DevSim equation string: 1 everywhere, 0 inside any exclusion
    window. Windows are assumed non-overlapping (derive_barrier_covered_
    windows() only ever emits merged, disjoint windows), so summing
    each window's step()*step() indicator and subtracting from 1 is
    safe -- same step()-based windowing mechanism implant_windows
    already uses (see apply_doping_symbolic's own docstring), reused
    rather than inventing a second one. Used only by
    apply_doping_symbolic() below.
    """
    if not exclude_windows:
        return "1"
    terms = []
    for w in exclude_windows:
        lo = w["min_um"] * length_scale_to_cm
        hi = w["max_um"] * length_scale_to_cm
        terms.append(f"step({axis}-({lo}))*step(({hi})-{axis})")
    return "(1 - (" + " + ".join(terms) + "))"


def apply_doping_symbolic(
    device: str,
    doping: DopingProfile,
    length_scale_to_cm: float = 1.0,
    window_scale: float = 1.0,
    exclude_windows: Optional[List[Dict[str, float]]] = None,
    exclude_axis: str = "x",
) -> None:
    """The ORIGINAL kind-based symbolic-equation NetDoping writer,
    preserved verbatim (only renamed) -- see this module's own top
    docstring for why. It has NO production caller: it writes NetDoping
    from a `DopingProfile` (one doping declaration), not from the
    canonical WaferStateV2, so it bypasses the central gate. Tier 1-1
    moved its last caller,
    tcad.characterization.robust_iv_sweep.ramp_doping_to_equilibrium,
    onto `canonical_node_doping()`; every production measurement now
    writes doping through that gate (`apply_doping()` or the robust
    continuation). tests/unit/test_measurement_canonical_state_gate_mock.py
    fails if a production call to this function reappears.

    Real API used (verified against installed DevSim 2.10.1 — same
    node_model() used elsewhere in this project, confirmed here specifically
    for a constant-expression doping value by running it and reading back
    get_node_model_values(), and cross-checked physically: the resulting
    device solve's built-in potential matched the analytic
    V_t*ln(NetDoping/n_i) prediction for both signs of doping — see
    tests/test_phase7_doping_real.py):

        devsim.node_model(device=, region=, name="NetDoping", equation=str(value))

    Real API used (verified against installed DevSim 2.10.1 — confirmed
    here specifically for both a constant-expression doping value and a
    step-junction doping value, by running each and reading back
    get_node_model_values(), and cross-checked physically: the resulting
    equilibrium solve's potential spread matched the analytic
    V_t*ln(Nd*Na/n_i^2) built-in potential for a step junction to full
    floating-point precision — see tests/test_phase8_pn_junction_real.py):

        devsim.node_model(device=, region=, name="NetDoping", equation=str(value))
        # step junction (real DevSim built-in step() function, found by
        # reading devsim_data/examples/diode/diode_common.py's own
        # SetNetDoping(), not guessed):
        devsim.node_model(device=, region=, name="Donors",
                           equation=f"{donor}*step(x-({junction_position}))")
        devsim.node_model(device=, region=, name="Acceptors",
                           equation=f"{acceptor}*step(({junction_position})-x)")
        devsim.node_model(device=, region=, name="NetDoping",
                           equation="Donors-Acceptors")

    "uniform", "step_junction", "gaussian_implant", and "implant_windows"
    are implemented. gaussian_implant's equation ("exp"/"^" confirmed
    supported by DevSim's own equation parser:
    devsim/python_packages/simple_physics.py uses both, e.g.
    `"n_i*exp(Potential/V_t)"`, `"NetDoping^2"`) sets NetDoping directly to
    a Gaussian, the same way "uniform" sets it directly to a constant — no
    separate Donors/Acceptors split, since a Gaussian implant isn't a
    donor/acceptor pair the way a step junction is:

        devsim.node_model(device=, region=, name="NetDoping",
            equation=f"{peak}*exp(-(({axis}-({position}))^2)/(2*({straggle})^2))")

    implant_windows sets NetDoping to a background constant plus zero or
    more `step()*step()` window terms SUMMED on top — real DevSim
    `step(x)*step(-x)`-style windowing (the same `step()` function
    diode_common.py uses for the step junction above), confirmed by direct
    execution reading get_node_model_values() back and comparing to an
    independently-computed value per node (0.000e+00 max error across all
    nodes — see test_implant_windows_doping_real.py):

        devsim.node_model(device=, region=, name="NetDoping",
            equation=(
                f"{background}"
                f" + {conc_1}*step({axis}-({min_1}))*step(({max_1})-{axis})"
                f" + {conc_2}*step({axis}-({min_2}))*step(({max_2})-{axis})"
                " + ..."
            ))

    length_scale_to_cm : must match whatever
        tcad.device.devsim.mesh_import.import_process_result's
        length_scale_to_cm was for this device, so junction_position_um
        (given in the same "um" units as ProcessResult, see
        tcad/mesh/interface.py) converts into the same coordinate scale
        DevSim's own "x"/"y"/"z" node models use. Irrelevant for
        "uniform" doping, which has no position dependence. Default 1.0
        matches the default (and every Phase 7 caller's) import scale.

    window_scale : multiplies every implant WINDOW's concentration (not
        the background), for "implant_windows" only. Default 1.0 leaves
        every existing caller byte-identical. Its purpose is
        doping-level CONTINUATION: re-registering NetDoping at a
        sequence of increasing scales, re-solving at each, lets the
        equilibrium solve reach a heavily-doped target it cannot reach
        in one step. `ramp_doping_to_equilibrium` used to call this with
        it; it now ramps the canonical per-node NetDoping instead.

    exclude_windows, exclude_axis : zero the written NetDoping inside
        each window, expressed as an equation string. `apply_doping()`
        no longer has this masking (P0-C: it erased pre-existing dopant
        under a barrier); it survives only in this unused writer.
    """
    module = backend.require_devsim()
    exclusion = _exclusion_factor_expr(exclude_windows, exclude_axis, length_scale_to_cm)

    if doping.kind == "uniform":
        for region_doping in doping.regions:
            module.node_model(
                device=device,
                region=region_doping.region,
                name="NetDoping",
                equation=f"({region_doping.net_doping_cm3})*{exclusion}",
            )
    elif doping.kind == "step_junction":
        for region_doping in doping.regions:
            axis = region_doping.junction_axis
            position_native = region_doping.junction_position_um * length_scale_to_cm
            module.node_model(
                device=device, region=region_doping.region, name="Donors",
                equation=f"{region_doping.donor_conc_cm3}*step({axis}-({position_native}))",
            )
            module.node_model(
                device=device, region=region_doping.region, name="Acceptors",
                equation=f"{region_doping.acceptor_conc_cm3}*step(({position_native})-{axis})",
            )
            module.node_model(
                device=device, region=region_doping.region, name="NetDoping",
                equation=f"(Donors-Acceptors)*{exclusion}",
            )
    elif doping.kind == "gaussian_implant":
        for region_doping in doping.regions:
            axis = region_doping.junction_axis
            position_native = region_doping.peak_position_um * length_scale_to_cm
            straggle_native = region_doping.straggle_um * length_scale_to_cm
            gaussian_expr = (
                f"{region_doping.peak_conc_cm3}*exp(-(({axis}-({position_native}))^2)"
                f"/(2*({straggle_native})^2))"
            )
            module.node_model(
                device=device, region=region_doping.region, name="NetDoping",
                equation=f"({gaussian_expr})*{exclusion}",
            )
    elif doping.kind == "implant_windows":
        for region_doping in doping.regions:
            axis = region_doping.junction_axis
            background = region_doping.net_doping_cm3 or 0.0
            terms = [str(background)]
            for window in region_doping.implant_windows or []:
                lo_native = window["min_um"] * length_scale_to_cm
                hi_native = window["max_um"] * length_scale_to_cm
                terms.append(
                    f"{window['conc_cm3'] * window_scale}*step({axis}-({lo_native}))"
                    f"*step(({hi_native})-{axis})"
                )
            windows_expr = " + ".join(terms)
            module.node_model(
                device=device, region=region_doping.region, name="NetDoping",
                equation=f"({windows_expr})*{exclusion}",
            )
    else:
        raise NotImplementedError(
            f"doping_mapping.apply_doping_symbolic supports kind in "
            f"('uniform', 'step_junction', 'gaussian_implant', "
            f"'implant_windows') so far, got {doping.kind!r}"
        )
