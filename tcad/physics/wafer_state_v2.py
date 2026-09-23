#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState v2 -- 2D material-cell identity, lineage, provenance, and
fail-closed conservative dopant transfer.

Design: docs/superpowers/specs/2026-09-10-waferstate-v2-design.md
(review-approved). This module holds ONLY the pure data model and the
pure transfer functions. No ViennaPS / DevSim import at module top
level; nothing here runs a process or reads a file.

The one rule that governs everything below: a MODELLED transition
(a real clip / split / conversion with numbers attached) happens ONLY
when the process layer hands `advance()` an explicit
`GeometryTransform` whose `representable` flag is True and whose
extents are exact axis-aligned rectangles with all four bounds known.
With no transform, a non-representable one, or a source geometry that
never carried a real `y_min`, the transition is recorded as
`UNSUPPORTED_BY_MODEL`, the affected dopant goes to an
`UnresolvedInventory` ledger entry (with a numeric total ONLY where its
own 2D support was already exact), and no number is invented.

Coordinates are micrometres. Area is converted to cm explicitly:
1 um^2 = 1e-8 cm^2, so for a rectangle of uniform concentration
C [cm^-3] the dopant inventory per unit out-of-plane depth is
exactly C * area_cm2 [cm^-1].

This module never samples or discretises an integral -- every inventory
figure is a closed form. A `DopantAttachment` carries an
`inventory_integral(bounds_um)` callable that returns the EXACT
closed-form integral of its own concentration over a rectangle
(uniform -> C*area; a piecewise-constant step / windowed profile -> a
sum of exact rectangle integrals; a Gaussian -> the exact erf
expression), or `None` when the profile has no exact integral. A
profile with no exact integral gets `inventory_cm_per_depth = None` and
its region is reported `UNSUPPORTED_BY_MODEL` -- never an approximation.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, List, Optional, Tuple

Bounds = Tuple[float, float, float, float]  # (x_min, x_max, y_min, y_max), um

UM2_TO_CM2 = 1.0e-8

#: The ONLY legal dopant activation states. ACTIVE dopant may be used in an
#: electrical donor/acceptor query; CHEMICAL is present/provenance only and
#: UNKNOWN is undecided -- neither is ever electrical, and neither is ever
#: read as 0.0 or summed as if it were ACTIVE (see `net_doping_at`).
CHEMICAL_STATES = ("CHEMICAL", "ACTIVE", "UNKNOWN")


def validate_chemical_state(value: Any) -> str:
    """Return `value` if it is exactly one of `CHEMICAL_STATES`, else raise
    ValueError immediately -- no coercion, no default, no guessing."""
    if value not in CHEMICAL_STATES:
        raise ValueError(
            f"chemical_state must be exactly one of {CHEMICAL_STATES}, got {value!r}")
    return value


# --------------------------------------------------------------------------
# Data model (design doc Sec5)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class MaterialCell:
    cell_id: str
    material: str
    bounds_um: Optional[Bounds]          # None only for a LEGACY_UNRESOLVED cell with no real y_min
    material_instance_id: str
    lineage: Tuple[str, ...] = ()
    lifecycle: str = "ACTIVE"            # ACTIVE | REMOVED | CONVERTED | LEGACY_UNRESOLVED
    provenance_event_ids: Tuple[str, ...] = ()

    @property
    def is_modelled(self) -> bool:
        """True only when this cell is a real 2D rectangle usable for
        modelled physics -- an exact bounds_um AND not a legacy /
        fail-closed stub."""
        return (self.lifecycle not in ("LEGACY_UNRESOLVED", "UNRESOLVED")
                and self.bounds_um is not None)


@dataclass(frozen=True)
class DopantAttachment:
    attachment_id: str
    species: Optional[str]
    polarity: str                        # "donor" | "acceptor"
    chemical_state: str                  # "CHEMICAL" | "ACTIVE" | "UNKNOWN"
    concentration_at: Callable[[float, float], float]
    support_instance_id: str
    support_region_um: Optional[Bounds]  # None when the geometric support is unknown (v1/legacy)
    creation_event_id: str
    model: str
    # EXACT closed-form integral of concentration over a rectangle,
    # [cm^-1]. Returns None when this profile has no exact integral --
    # then this attachment's inventory is unknown, NOT approximated.
    inventory_integral: Optional[Callable[[Bounds], Optional[float]]] = None
    model_params: Dict[str, Any] = field(default_factory=dict)
    provenance: Any = None
    inventory_cm_per_depth: Optional[float] = None

    def __post_init__(self) -> None:
        validate_chemical_state(self.chemical_state)

    @property
    def support_is_exact(self) -> bool:
        return self.support_region_um is not None

    def exact_inventory_over(self, region_um: Optional[Bounds]) -> Optional[float]:
        """The EXACT dopant inventory over `region_um` [cm^-1], or None
        when the geometric support is unknown OR this profile has no
        exact integral. Never an approximation."""
        if region_um is None or self.inventory_integral is None:
            return None
        return self.inventory_integral(region_um)


@dataclass(frozen=True)
class _AttachmentProfileView:
    """Read-only v1-shaped view of one `DopantAttachment`, returned by
    `WaferStateV2.dopant_profiles` for GUI callers that still expect the
    v1 `DopantProfile` attribute surface. Not a state carrier -- see
    that property's docstring."""
    species: Optional[str]
    polarity: str
    concentration_at: Callable[[float, float], float]
    host_material: Optional[str]
    model: str = ""
    model_params: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SpatialEvent:
    event_id: str
    category: str                        # PRESERVED|REMOVED|ADDED|CONVERTED|REPLACED|UNSUPPORTED_BY_MODEL
    process_category: str
    input_cell_ids: Tuple[str, ...] = ()
    output_cell_ids: Tuple[str, ...] = ()
    input_attachment_ids: Tuple[str, ...] = ()
    output_attachment_ids: Tuple[str, ...] = ()
    extent_um: Optional[Bounds] = None
    model_status: str = "MODELLED"       # MODELLED | UNSUPPORTED_BY_MODEL
    # Dopant inventory [cm^-1] this event accounted for: the amount
    # removed (REMOVED etch) or ledgered (CONVERTED). None when the
    # event moved no dopant or the amount was not computable.
    inventory_cm_per_depth: Optional[float] = None
    note: str = ""


@dataclass(frozen=True)
class UnresolvedInventory:
    species: Optional[str]
    polarity: str
    total_cm_per_depth: Optional[float]  # a number ONLY when quantity_status == KNOWN_EXACT
    quantity_status: str                 # KNOWN_EXACT | UNKNOWN_GEOMETRIC_SUPPORT
    origin_attachment_id: str
    conversion_event_id: str
    note: str = ""


@dataclass(frozen=True)
class GeometryTransform:
    """The explicit transition contract (design doc Sec5.5). The process
    layer supplies this; `advance()` never infers a transition from a
    mesh. `representable` is True ONLY if every extent below is an exact
    axis-aligned rectangle with all four bounds known."""
    process_category: str
    representable: bool = False
    removed_extents_um: Tuple[Bounds, ...] = ()
    added_cells: Tuple[Tuple[str, Bounds, str], ...] = ()   # (material, bounds_um, new_instance_id)
    converted_extents_um: Tuple[Bounds, ...] = ()
    input_instance_ids: Tuple[str, ...] = ()
    output_instance_ids: Tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class WaferStateV2:
    cells: Tuple[MaterialCell, ...] = ()
    attachments: Tuple[DopantAttachment, ...] = ()
    events: Tuple[SpatialEvent, ...] = ()
    unresolved_inventory: Tuple[UnresolvedInventory, ...] = ()
    grid_delta_um: float = 0.0

    # -- geometry queries ------------------------------------------------

    def active_cells(self) -> Tuple[MaterialCell, ...]:
        return tuple(c for c in self.cells if c.lifecycle == "ACTIVE")

    def cell_by_id(self, cell_id: str) -> Optional[MaterialCell]:
        return next((c for c in self.cells if c.cell_id == cell_id), None)

    def instance_of(self, cell_id: str) -> Optional[str]:
        cell = self.cell_by_id(cell_id)
        return cell.material_instance_id if cell else None

    def attachments_for_instance(self, material_instance_id: str) -> Tuple[DopantAttachment, ...]:
        """The ONLY sanctioned lookup: by material_instance_id, never by
        material NAME (test 3). A name-based lookup would let a
        re-deposited 'Si' pick up the original 'Si''s dopant."""
        return tuple(a for a in self.attachments if a.support_instance_id == material_instance_id)

    @property
    def dopant_profiles(self) -> Tuple["_AttachmentProfileView", ...]:
        """READ-ONLY v1-compatibility view for GUI callers that still
        iterate `wafer_state.dopant_profiles` (species / polarity /
        host_material / concentration_at). Each view resolves
        `host_material` from the owning ACTIVE cell's material, so a
        re-deposited instance never mislabels its dopant. This is a
        query surface only -- there is no setter; the accumulating state
        is advanced through `advance_wafer_state()` /
        `wafer_state_v2.attach_dopant()`."""
        instance_material = {
            c.material_instance_id: c.material for c in self.cells
        }
        return tuple(
            _AttachmentProfileView(
                species=a.species,
                polarity=a.polarity,
                concentration_at=a.concentration_at,
                host_material=instance_material.get(a.support_instance_id),
                model=a.model,
                model_params=a.model_params,
            )
            for a in self.attachments
        )

    def exposed_material_at(self, x_um: float) -> Optional[str]:
        best: Optional[MaterialCell] = None
        for cell in self.active_cells():
            b = cell.bounds_um
            if b is None:
                continue
            if b[0] <= x_um <= b[1]:
                if best is None or b[3] > best.bounds_um[3]:
                    best = cell
        return best.material if best is not None else None

    def exposed_materials(self) -> frozenset:
        surface: Dict[float, MaterialCell] = {}
        for cell in self.active_cells():
            b = cell.bounds_um
            if b is None:
                continue
            key = b[0]
            if key not in surface or b[3] > surface[key].bounds_um[3]:
                surface[key] = cell
        return frozenset(c.material for c in surface.values())

    def under_resolved_x(self) -> Tuple[float, ...]:
        # v2 has no live level-set access; the v1 thin-layer diagnostic
        # is out of scope here. A v2 built by migrating a v1 state
        # carries the v1 value forward via _thin_x_passthrough.
        return getattr(self, "_thin_x_passthrough", ())

    # -- doping query (v1 compatibility surface, design doc Sec7.3) ------

    def net_doping_at(
        self, x_um: float, y_um: float = 0.0, *,
        owning_cell: Optional[MaterialCell] = None,
    ) -> "DopingQueryResult":
        """The one public doping query.

        If a LEGACY_UNRESOLVED cell or an UNSUPPORTED_BY_MODEL event
        covers this point, ALL THREE concentration values are `None`
        (not 0.0 -- 0 is the physical claim "known un-doped") and
        `physics_status` reports UNSUPPORTED_BY_MODEL. Otherwise the
        three values are real floats summed from the active
        attachments whose exact support contains the point.

        `owning_cell`, when given, is trusted as the point's owner
        INSTEAD of this method's own tie-break (below: among every
        active cell whose bounds contain the point, the one with the
        largest y_max). That tie-break is a coarse "what's on top"
        default and picks the WRONG cell whenever two different
        materials share an exact boundary with no thickness between
        them (e.g. Si's y_max == SiO2's y_min): it always prefers the
        cell stacked above, even when the point is being queried FOR the
        cell below. A caller that already knows which cell genuinely
        owns the point by a more specific rule -- e.g.
        tcad.device.devsim.doping_mapping.canonical_node_doping(),
        which resolves ownership by the DevSim region's own material --
        passes it here so the attachment lookup matches that
        determination instead of this method's own independent (and
        coarser) guess. Every existing caller that omits it keeps this
        method's original tie-break, unchanged.
        """
        legacy_here = any(
            c.lifecycle == "LEGACY_UNRESOLVED"
            and (c.bounds_um is None or (c.bounds_um[0] <= x_um <= c.bounds_um[1]))
            for c in self.cells
        )
        unsupported_here = self._unsupported_covering(x_um, y_um)

        if legacy_here or unsupported_here is not None:
            note = (
                "point lies in a LEGACY_UNRESOLVED cell (no exact y_min for "
                "its material support)" if legacy_here else
                f"point lies in a region an UNSUPPORTED_BY_MODEL "
                f"{unsupported_here.process_category!r} event covers "
                f"({unsupported_here.note})"
            )
            return DopingQueryResult(
                donor_concentration=None, acceptor_concentration=None, net_doping=None,
                physics_status={
                    "resolution": "UNSUPPORTED_BY_MODEL",
                    "entries": [{
                        "parameter": "dopant_fate_2d_state",
                        "material": "?", "resolution": "UNSUPPORTED_BY_MODEL",
                        "provenance": "DERIVED", "note": note,
                    }],
                    "notes": [],
                },
            )

        if owning_cell is not None:
            owning = owning_cell
        else:
            owning = None
            for cell in self.active_cells():
                b = cell.bounds_um
                if b is not None and b[0] <= x_um <= b[1] and b[2] <= y_um <= b[3]:
                    if owning is None or b[3] > owning.bounds_um[3]:
                        owning = cell

        donor = 0.0
        acceptor = 0.0
        if owning is not None:
            for a in self.attachments_for_instance(owning.material_instance_id):
                # Activation gate: only an ACTIVE attachment may supply an
                # electrical donor/acceptor number. A CHEMICAL or UNKNOWN
                # attachment covering this point (or with no known support,
                # which may cover it) makes ALL THREE values None -- never
                # 0.0 and never summed as if it were ACTIVE.
                if a.chemical_state != "ACTIVE" and (
                        a.support_region_um is None
                        or _point_in(a.support_region_um, x_um, y_um)):
                    return DopingQueryResult(
                        donor_concentration=None, acceptor_concentration=None,
                        net_doping=None,
                        physics_status={
                            "resolution": "UNSUPPORTED_BY_MODEL",
                            "entries": [{
                                "parameter": "dopant_activation_state",
                                "material": owning.material,
                                "resolution": "UNSUPPORTED_BY_MODEL",
                                "provenance": "DERIVED",
                                "note": f"attachment {a.attachment_id!r} covering this "
                                        f"point has chemical_state {a.chemical_state!r}; "
                                        f"only ACTIVE dopant is electrically usable "
                                        f"(no activation model is available)",
                            }],
                            "notes": [],
                        },
                    )
                # An attachment whose 2D support is unknown, or whose
                # profile has no exact integral, does NOT get a local
                # numeric read either (review P0): "I do not know the
                # inventory but I will still hand you an electrical
                # doping number" is exactly the loophole this closes.
                if (a.support_region_um is None or a.inventory_integral is None
                        or a.inventory_cm_per_depth is None):
                    if a.support_region_um is None or _point_in(a.support_region_um, x_um, y_um):
                        return DopingQueryResult(
                            donor_concentration=None, acceptor_concentration=None,
                            net_doping=None,
                            physics_status={
                                "resolution": "UNSUPPORTED_BY_MODEL",
                                "entries": [{
                                    "parameter": "dopant_fate_2d_state",
                                    "material": owning.material,
                                    "resolution": "UNSUPPORTED_BY_MODEL",
                                    "provenance": "DERIVED",
                                    "note": "an attachment covering this point has no exact "
                                            "geometric support / no exact integral -- its "
                                            "electrical contribution is not modelled",
                                }],
                                "notes": [],
                            },
                        )
                    continue
                if not _point_in(a.support_region_um, x_um, y_um):
                    continue
                mag = max(0.0, float(a.concentration_at(x_um, y_um)))
                if a.polarity == "donor":
                    donor += mag
                else:
                    acceptor += mag
        return DopingQueryResult(
            donor_concentration=donor, acceptor_concentration=acceptor,
            net_doping=donor - acceptor, physics_status=None,
        )

    def _unsupported_covering(self, x_um: float, y_um: float) -> Optional[SpatialEvent]:
        # A CONVERTED event's region has KNOWN geometry but UNKNOWN
        # dopant fate (segregation) -- it stays unsupported regardless of
        # any cell there.
        for e in self.events:
            if (e.category == "CONVERTED" and e.model_status == "UNSUPPORTED_BY_MODEL"
                    and e.extent_um is not None and _point_in(e.extent_um, x_um, y_um)):
                return e
        # A doping-APPLICATION-level UNSUPPORTED event (attach_dopant
        # refused an active attachment -- an ambiguous target, a barrier
        # carve that wasn't exact, no exact integral, ...) is about that
        # application's dopant, never about the cell's own geometry. It
        # must NOT be "un-covered" by a later ACTIVE MODELLED cell the
        # way a whole-step geometry UNSUPPORTED event can be below --
        # the cell was already known-good geometry at attach time, that
        # is exactly why the refusal happened at the doping layer
        # instead of the geometry layer.
        for e in self.events:
            if (e.category == "UNSUPPORTED_BY_MODEL" and e.process_category == "doping"
                    and (e.extent_um is None or _point_in(e.extent_um, x_um, y_um))):
                return e
        # A whole-step fail-closed UNSUPPORTED event is about UNKNOWN
        # geometry -- a later ACTIVE modelled cell that genuinely
        # contains this point (concrete new deposition geometry)
        # "un-covers" it.
        for cell in self.active_cells():
            if cell.is_modelled and _point_in(cell.bounds_um, x_um, y_um):
                return None
        for e in self.events:
            if e.category != "UNSUPPORTED_BY_MODEL":
                continue
            if e.extent_um is None or _point_in(e.extent_um, x_um, y_um):
                return e
        return None


@dataclass(frozen=True)
class DopingQueryResult:
    # None (not 0.0) whenever physics_status is UNSUPPORTED_BY_MODEL:
    # 0 would be the physical claim "known un-doped here".
    donor_concentration: Optional[float]
    acceptor_concentration: Optional[float]
    net_doping: Optional[float]
    physics_status: Optional[dict]


# --------------------------------------------------------------------------
# Geometry / inventory helpers
# --------------------------------------------------------------------------

def area_cm2(bounds_um: Bounds) -> float:
    x0, x1, y0, y1 = bounds_um
    return max(0.0, (x1 - x0)) * max(0.0, (y1 - y0)) * UM2_TO_CM2


def _point_in(bounds_um: Optional[Bounds], x_um: float, y_um: float) -> bool:
    if bounds_um is None:
        return False
    x0, x1, y0, y1 = bounds_um
    return x0 <= x_um <= x1 and y0 <= y_um <= y1


def rect_intersection(a: Bounds, b: Bounds) -> Optional[Bounds]:
    x0 = max(a[0], b[0])
    x1 = min(a[1], b[1])
    y0 = max(a[2], b[2])
    y1 = min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, x1, y0, y1)


def rect_subtract(a: Bounds, b: Bounds) -> List[Bounds]:
    """`a` minus `b`, as a list of disjoint axis-aligned rectangles that
    exactly tile `a \\ b`. Guillotine cut: up to 4 pieces."""
    inter = rect_intersection(a, b)
    if inter is None:
        return [a]
    ix0, ix1, iy0, iy1 = inter
    ax0, ax1, ay0, ay1 = a
    pieces: List[Bounds] = []
    if ay1 > iy1:
        pieces.append((ax0, ax1, iy1, ay1))       # top strip
    if iy0 > ay0:
        pieces.append((ax0, ax1, ay0, iy0))       # bottom strip
    if ix0 > ax0:
        pieces.append((ax0, ix0, iy0, iy1))       # left strip (middle band only)
    if ax1 > ix1:
        pieces.append((ix1, ax1, iy0, iy1))       # right strip (middle band only)
    return [p for p in pieces if p[1] > p[0] and p[3] > p[2]]


# --------------------------------------------------------------------------
# EXACT closed-form inventory integrals per profile model.
#
# Each builder returns an `inventory_integral(bounds_um) -> float | None`
# callable. Nothing here is sampled or discretised: the integral of
# every profile below is a closed form. A model with no closed form
# gets no builder here, its attachment carries `inventory_integral=None`,
# and its inventory is None (UNSUPPORTED), never approximated.
# --------------------------------------------------------------------------

def uniform_inventory_integral(conc_cm3: float) -> Callable[[Bounds], float]:
    """integral of C over a rectangle == C * area_cm2, exact for any
    bounds (grid-aligned or not)."""
    return lambda b: conc_cm3 * area_cm2(b)


def step_inventory_integral(conc_cm3: float, x_position_um: float, side: str) -> Callable[[Bounds], float]:
    """C on one side of x_position_um (a lateral step junction / window
    edge), 0 on the other. `side` is 'x_ge' (C where x >= position) or
    'x_le' (C where x <= position). Exact:
      integral == C * (y1-y0) * (overlap of [x0,x1] with the C side) * 1e-8
    """
    def integ(b: Bounds) -> float:
        x0, x1, y0, y1 = b
        if side == "x_ge":
            lo, hi = max(x0, x_position_um), x1
        else:  # x_le
            lo, hi = x0, min(x1, x_position_um)
        return conc_cm3 * max(0.0, y1 - y0) * max(0.0, hi - lo) * UM2_TO_CM2
    return integ


def windowed_inventory_integral(
    background_cm3: float,
    windows: Tuple[Tuple[float, float, float], ...],
) -> Callable[[Bounds], float]:
    """background + sum of (min_um, max_um, conc_cm3) rectangular windows,
    every term a piecewise constant -> exact rectangle integral, summed."""
    def integ(b: Bounds) -> float:
        x0, x1, y0, y1 = b
        h = max(0.0, y1 - y0)
        total = background_cm3 * max(0.0, x1 - x0) * h
        for lo, hi, mag in windows:
            olo, ohi = max(x0, lo), min(x1, hi)
            total += mag * max(0.0, ohi - olo) * h
        return total * UM2_TO_CM2
    return integ


def gaussian_inventory_integral(
    peak_cm3: float, position_um: float, straggle_um: float,
) -> Callable[[Bounds], float]:
    """peak * exp(-(x-position)^2 / (2 straggle^2)), y-independent.
    integral over [x0,x1]x[y0,y1] ==
      peak * (y1-y0) * straggle * sqrt(pi/2) * (erf(u1) - erf(u0)) * 1e-8
    with u = (x - position) / (sqrt(2) straggle). Exact via math.erf.
    """
    import math

    def integ(b: Bounds) -> float:
        x0, x1, y0, y1 = b
        s2 = math.sqrt(2.0) * straggle_um
        u0 = (x0 - position_um) / s2
        u1 = (x1 - position_um) / s2
        x_integral = straggle_um * math.sqrt(math.pi / 2.0) * (math.erf(u1) - math.erf(u0))
        return peak_cm3 * max(0.0, y1 - y0) * x_integral * UM2_TO_CM2
    return integ


# --------------------------------------------------------------------------
# ID helpers -- deterministic, readable, unique within one advance() call
# --------------------------------------------------------------------------

class _IdGen:
    def __init__(self, seed: str = "") -> None:
        self._seed = seed
        self._n = 0

    def next(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}:{self._seed}:{self._n}" if self._seed else f"{prefix}:{self._n}"


# --------------------------------------------------------------------------
# advance() -- the single v2 threading point (design doc Sec7.2)
# --------------------------------------------------------------------------

def advance(
    prior: Optional[WaferStateV2],
    transform: Optional[GeometryTransform],
    *,
    step_seed: str = "",
) -> WaferStateV2:
    """Advance the v2 state by one process step.

    `transform` is the explicit GeometryTransform the process layer
    supplies (design doc Sec5.5). If it is None or `representable` is
    False, the whole step is the fail-closed UNSUPPORTED_BY_MODEL path:
    every attachment on an ACTIVE cell is moved to the unresolved
    ledger (numeric total only where its own support was exact), no
    cell is split/removed/converted, and no active dopant is invented.
    """
    prior = prior or WaferStateV2()
    ids = _IdGen(step_seed)

    if transform is None or not transform.representable:
        return _fail_closed(prior, transform, ids, category_hint=step_seed)

    cat = transform.process_category
    if cat == "etching":
        return _apply_etch(prior, transform, ids)
    if cat == "deposition":
        return _apply_deposition(prior, transform, ids)
    if cat == "oxidation":
        return _apply_conversion(prior, transform, ids)
    if cat in ("remesh", "geometry_sync"):
        return _apply_remesh(prior, transform, ids)
    if cat == "doping":
        # doping does not itself move geometry; attachments are added by
        # attach_dopant() before/after this. A representable doping
        # transform is a no-op PRESERVED marker.
        ev = SpatialEvent(ids.next("evt"), "PRESERVED", "doping",
                          note="doping step: geometry unchanged")
        return replace(prior, events=prior.events + (ev,))
    # Unknown but representable category: still fail closed -- we do not
    # guess semantics for a category with no rule.
    return _fail_closed(prior, transform, ids)


def _fail_closed(
    prior: WaferStateV2,
    transform: Optional[GeometryTransform],
    ids: _IdGen,
    *,
    category_hint: str = "",
) -> WaferStateV2:
    # When there is no transform at all, there is no
    # `transform.process_category` to read -- fall back to the
    # caller's own `step_seed` (e.g. advance_wafer_state passes the
    # real process category there) so the resulting event's
    # process_category stays meaningful instead of a generic "unknown".
    cat = (
        transform.process_category if transform is not None
        else (category_hint or "unknown")
    )
    reason = (
        "no GeometryTransform supplied" if transform is None
        else "GeometryTransform.representable is False"
    )
    ev = SpatialEvent(
        ids.next("evt"), "UNSUPPORTED_BY_MODEL", cat,
        input_cell_ids=tuple(c.cell_id for c in prior.active_cells()),
        input_attachment_ids=tuple(a.attachment_id for a in prior.attachments),
        model_status="UNSUPPORTED_BY_MODEL",
        note=f"{reason}; no modelled clip/split/conversion performed",
    )
    ledger = list(prior.unresolved_inventory)
    for a in prior.attachments:
        ledger.append(_to_unresolved(a, ev.event_id, note=f"{cat}: {reason}"))
    # item 3: the fail-closed step makes every prior attachment's fate
    # unknown, so they are DROPPED from the active set entirely -- kept
    # only in the ledger. A later valid GeometryTransform cannot
    # resurrect them as active doping; only newly attach_dopant()-ed
    # profiles are active from here on.
    #
    # The prior modelled cells' geometry is also now suspect (an
    # unmodelled step ran on them): mark them UNRESOLVED so they no
    # longer count as trustworthy modelled geometry. A later concrete
    # deposition still adds real ACTIVE cells.
    new_cells = tuple(
        replace(c, lifecycle="UNRESOLVED",
                provenance_event_ids=c.provenance_event_ids + (ev.event_id,))
        if c.lifecycle == "ACTIVE" and c.is_modelled else c
        for c in prior.cells
    )
    return replace(
        prior,
        cells=new_cells,
        attachments=(),
        events=prior.events + (ev,),
        unresolved_inventory=tuple(ledger),
    )


def _to_unresolved(a: DopantAttachment, event_id: str, *, note: str) -> UnresolvedInventory:
    total = a.inventory_cm_per_depth
    if total is None and a.support_is_exact:
        total = a.exact_inventory_over(a.support_region_um)
    if a.support_is_exact and total is not None:
        return UnresolvedInventory(
            species=a.species, polarity=a.polarity,
            total_cm_per_depth=total, quantity_status="KNOWN_EXACT",
            origin_attachment_id=a.attachment_id, conversion_event_id=event_id,
            note=note,
        )
    return UnresolvedInventory(
        species=a.species, polarity=a.polarity,
        total_cm_per_depth=None, quantity_status="UNKNOWN_GEOMETRIC_SUPPORT",
        origin_attachment_id=a.attachment_id, conversion_event_id=event_id,
        note=note + " (no exact integral for this support/profile -- total not computable)",
    )


_INV_REL_TOL = 1e-6


def _validate_extents(extents: Tuple[Bounds, ...]) -> Optional[str]:
    """Returns an error string if any extent has non-positive area or
    two extents overlap; None if the set is clean."""
    for e in extents:
        if not (e[1] > e[0] and e[3] > e[2]):
            return f"extent {e} has non-positive area"
    for i in range(len(extents)):
        for j in range(i + 1, len(extents)):
            if rect_intersection(extents[i], extents[j]) is not None:
                return f"extents {extents[i]} and {extents[j]} overlap"
    return None


def _covered_by(rect: Bounds, covers: List[Bounds]) -> bool:
    """True iff `rect` is entirely contained in the union of `covers`
    (exact rectangle arithmetic, no tolerance)."""
    remaining = [rect]
    for c in covers:
        nxt: List[Bounds] = []
        for r in remaining:
            nxt.extend(rect_subtract(r, c))
        remaining = nxt
    return not remaining


#: Why a compensated (finite-area donor + acceptor) region has no transport number.
COMPENSATED_TRANSPORT_REASON = "COMPENSATED_TRANSPORT_MODEL_MISSING"

#: Why an ACTIVE step_junction_v1 attachment on a 2D DevSim device is refused
#: transport (Batch 7E). Separate cause from COMPENSATED_TRANSPORT_REASON above:
#: this is not about donor/acceptor coexistence, it is that Batch 7D Rev.2's own
#: real L0-L5 mesh-refinement study found the 2D step-junction solve's terminal
#: current, peak electric field and R1/R2 representation agreement do NOT
#: converge (see docs/audits/2026-09-21-batch7d-step-junction-convergence/rev2).
#: The 1D abrupt-junction reference DOES converge, but that is a 1D result, not
#: proof of 2D production capability -- never generalize it.
STEP_JUNCTION_2D_REASON = "STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED"


def _positive_rects(a: DopantAttachment) -> Optional[List[Bounds]]:
    """The EXACT rectangles inside `a.support_region_um` where this attachment's
    concentration is strictly positive, from its `model` and `model_params`
    alone -- no sampling, no threshold. `None` means the model has no exact
    description of that region (or its support is unknown): the caller must then
    fail closed, never assume the two dopants do not overlap.

      uniform_v1         whole support
      gaussian_v1        whole support (exp(-u^2/2s^2) > 0 everywhere)
      step_junction_v1   donor: x >= junction; acceptor: x <= junction (DEVSIM's own
                         step() convention: at the junction line both are written, net
                         N_D - N_A). The two rectangles share only that LINE, which is
                         zero area, so an ideal step junction is not a compensated region
      implant_windows_v1 whole support if the background is > 0, else the union of
                         the windows (x in [lo, hi], any y) that have a positive value
    """
    s = a.support_region_um
    if s is None:
        return None
    p = a.model_params or {}
    if a.model == "uniform_v1" and "conc_cm3" in p:
        return [s] if p["conc_cm3"] > 0 else []
    if a.model == "gaussian_v1" and {"peak_conc_cm3", "straggle_um"} <= p.keys() and p["straggle_um"] > 0:
        return [s] if p["peak_conc_cm3"] > 0 else []
    if a.model == "step_junction_v1" and {"conc_cm3", "junction_position_um"} <= p.keys():
        if p["conc_cm3"] <= 0:
            return []
        pos = p["junction_position_um"]
        r = ((max(s[0], pos), s[1], s[2], s[3]) if a.polarity == "donor"
             else (s[0], min(s[1], pos), s[2], s[3]))
        return [r] if r[1] > r[0] else []
    if a.model == "implant_windows_v1" and "background_cm3" in p:
        if p["background_cm3"] > 0:
            return [s]
        out: List[Bounds] = []
        for lo, hi, mag in p.get("windows", []):
            if mag > 0:
                r = rect_intersection(s, (lo, hi, s[2], s[3]))
                if r is not None:
                    out.append(r)
        return out
    return None


def compensated_transport_problems(state: WaferStateV2, material: str) -> List[str]:
    """Every finite-area donor + acceptor coexistence among the ACTIVE attachments
    on the state's ACTIVE + MODELLED instances of `material` -- one sentence per
    pair, empty when there is none.

    A pair counts when the exact positive rectangles (`_positive_rects`) of a
    donor and an acceptor share POSITIVE AREA (a shared edge or point is not
    area), or when either model has no exact positive region (the relation
    cannot be proven -> fail closed). A single polarity, or donor and acceptor
    on opposite sides of an ideal step junction, is not compensated.

    The canonical CONCENTRATIONS stay valid (N_D, N_A, N_D - N_A); this is only
    the answer to "may a transport number be computed here": no, because the
    drift-diffusion path has no compensation-aware ionized-impurity scattering
    / mobility.
    """
    out: List[str] = []
    instances = sorted({c.material_instance_id for c in state.active_cells()
                        if c.is_modelled and c.material == material})
    for iid in instances:
        active = [a for a in state.attachments_for_instance(iid) if a.chemical_state == "ACTIVE"]
        for d in (a for a in active if a.polarity == "donor"):
            for ac in (a for a in active if a.polarity == "acceptor"):
                rd, ra = _positive_rects(d), _positive_rects(ac)
                if rd is None or ra is None:
                    out.append(f"instance {iid!r}: the donor/acceptor relation of {d.attachment_id!r} "
                               f"({d.model}) and {ac.attachment_id!r} ({ac.model}) cannot be proven "
                               f"non-overlapping")
                    continue
                hit = next((r for x in rd for y in ra
                            if (r := rect_intersection(x, y)) is not None), None)
                if hit is not None:
                    out.append(f"instance {iid!r}: donor {d.attachment_id!r} and acceptor "
                               f"{ac.attachment_id!r} coexist over the finite area {hit}")
    return out


def active_step_junction_instances(state: WaferStateV2, material: str) -> List[str]:
    """material_instance_id of every ACTIVE + MODELLED instance of `material`
    carrying at least one ACTIVE `step_junction_v1` dopant attachment (Batch 7E).

    This is the ONLY sanctioned source of truth for the 2D step-junction
    mesh-convergence gate in `doping_mapping.canonical_node_doping()`: the
    canonical WaferStateV2 attachment record, never a `DopingProfile.kind`
    string and never a GUI combobox's most recent selection (both can go
    stale relative to what is actually attached to the wafer).

    Pure state query -- no DevSim dependency, so it never decides DIMENSION.
    The caller (`doping_mapping.py`, which already imports DevSim) combines
    this with a real `devsim.get_dimension(device=...)` call to decide
    whether the STEP_JUNCTION_2D_REASON gate actually fires: a 1D device
    with the identical canonical state is not blocked by this gate.
    """
    instances = sorted({c.material_instance_id for c in state.active_cells()
                        if c.is_modelled and c.material == material})
    return [iid for iid in instances
            if any(a.chemical_state == "ACTIVE" and a.model == "step_junction_v1"
                   for a in state.attachments_for_instance(iid))]


def _active_modelled_cells(prior: WaferStateV2, instance_id: str) -> List[MaterialCell]:
    return [c for c in prior.active_cells()
            if c.material_instance_id == instance_id and c.is_modelled]


def _instance_targeting_error(prior: WaferStateV2, t: GeometryTransform) -> Optional[str]:
    """A representable etch/oxidation transform must name at least one
    target instance, and every named instance must be ACTIVE + MODELLED
    right now. For oxidation, every target's material must be Si.
    Returns an error string, or None if valid (review P1)."""
    if not t.input_instance_ids:
        return "representable etch/oxidation transform has empty input_instance_ids"
    for iid in t.input_instance_ids:
        cells = _active_modelled_cells(prior, iid)
        if not cells:
            return f"input_instance_id {iid!r} is not an ACTIVE + MODELLED instance"
        if t.process_category == "oxidation" and any(c.material != "Si" for c in cells):
            return f"oxidation target {iid!r} has non-Si material {[c.material for c in cells]}"
    return None


def _deposition_error(prior: WaferStateV2, t: GeometryTransform) -> Optional[str]:
    """Structural validation of a representable deposition (review P1)."""
    if not t.added_cells:
        return "representable deposition transform has empty added_cells"
    existing = {c.material_instance_id for c in prior.cells}
    seen: set = set()
    for material, bounds, new_id in t.added_cells:
        if not (bounds[1] > bounds[0] and bounds[3] > bounds[2]):
            return f"added_cell {new_id!r} bounds {bounds} have non-positive area"
        if new_id in existing:
            return f"added_cell new_instance_id {new_id!r} collides with an existing instance"
        if new_id in seen:
            return f"added_cell new_instance_id {new_id!r} is duplicated within the transform"
        seen.add(new_id)
    if t.output_instance_ids and set(t.output_instance_ids) != seen:
        return (f"output_instance_ids {sorted(t.output_instance_ids)} does not match the "
                f"actual added instances {sorted(seen)}")
    return None


def _apply_geometry_change(
    prior: WaferStateV2, t: GeometryTransform, ids: _IdGen, *,
    kind: str,   # "etching" -> REMOVED ; "oxidation" -> CONVERTED
) -> WaferStateV2:
    """Shared implementation of etch (REMOVED) and oxidation
    (CONVERTED). Both: change ONLY the instances named in
    `t.input_instance_ids` (item 4); an instance not named is PRESERVED
    even where it overlaps an extent; each SpatialEvent's `extent_um` is
    the real removed/converted intersection rectangle; each attachment's
    provenance points at the event that changed ITS OWN instance."""
    extents = t.removed_extents_um if kind == "etching" else t.converted_extents_um
    err = _validate_extents(extents) or _instance_targeting_error(prior, t)
    if err:
        return _fail_closed(prior, replace(t, representable=False, note=err), ids)

    targets = set(t.input_instance_ids)
    out_cells: List[MaterialCell] = []
    out_attachments: List[DopantAttachment] = []
    events: List[SpatialEvent] = list(prior.events)
    ledger: List[UnresolvedInventory] = list(prior.unresolved_inventory)
    # every removed/converted piece paired with the SpatialEvent id that
    # owns that exact rectangle (review P1: provenance is per-piece,
    # never "the instance's first/last event").
    pieces_with_event: List[Tuple[Bounds, str]] = []
    # per instance: the surviving rectangles, each tagged with the event
    # whose subtraction actually shaped it.
    survivors_by_instance: Dict[str, List[Tuple[Bounds, str]]] = {}

    for cell in prior.cells:
        if (cell.lifecycle != "ACTIVE" or not cell.is_modelled
                or cell.material_instance_id not in targets):
            out_cells.append(cell)          # untargeted / inactive -> PRESERVED
            continue
        hit = [rect_intersection(cell.bounds_um, r) for r in extents]
        hit = [p for p in hit if p is not None]
        if not hit:
            out_cells.append(cell)          # targeted but not spatially affected
            continue

        out_ids: List[str] = []
        cell_event_ids: List[str] = []
        for piece in hit:
            if kind == "etching":
                ev = SpatialEvent(
                    ids.next("evt"), "REMOVED", "etching", extent_um=piece,
                    input_cell_ids=(cell.cell_id,),
                    note=f"{cell.material} instance {cell.material_instance_id} etched at {piece}")
            else:
                ev = SpatialEvent(
                    ids.next("evt"), "CONVERTED", "oxidation", extent_um=piece,
                    input_cell_ids=(cell.cell_id,), model_status="UNSUPPORTED_BY_MODEL",
                    note="Si consumed by oxidation; B/P redistribution + segregation not modelled")
                sio2 = MaterialCell(
                    cell_id=ids.next("cell"), material="SiO2", bounds_um=piece,
                    material_instance_id=ids.next("inst"), lineage=(ev.event_id,),
                    lifecycle="ACTIVE", provenance_event_ids=(ev.event_id,))
                out_cells.append(sio2)
                out_ids.append(sio2.cell_id)
            events.append(ev)
            cell_event_ids.append(ev.event_id)
            pieces_with_event.append((piece, ev.event_id))

        # subtract each piece in turn, tagging each surviving sub-rect
        # with the event that just carved it.
        survivors: List[Tuple[Bounds, str]] = [(cell.bounds_um, "")]
        for piece, eid in zip(hit, cell_event_ids):
            nxt: List[Tuple[Bounds, str]] = []
            for s, cur in survivors:
                if rect_intersection(s, piece) is None:
                    nxt.append((s, cur))                 # untouched -> keep its tag
                    continue
                for sub in rect_subtract(s, piece):
                    nxt.append((sub, eid))               # shaped by eid
            survivors = nxt
        survivors_by_instance.setdefault(cell.material_instance_id, []).extend(survivors)

        for s, eid in survivors:
            nc = MaterialCell(
                cell_id=ids.next("cell"), material=cell.material, bounds_um=s,
                material_instance_id=cell.material_instance_id, lineage=cell.lineage,
                lifecycle="ACTIVE",
                provenance_event_ids=cell.provenance_event_ids + (eid,) if eid else cell.provenance_event_ids)
            out_cells.append(nc)
            out_ids.append(nc.cell_id)
        gone = "REMOVED" if kind == "etching" else "CONVERTED"
        out_cells.append(replace(
            cell, lifecycle=gone,
            provenance_event_ids=cell.provenance_event_ids + tuple(cell_event_ids)))
        for eid in cell_event_ids:
            k = next(i for i, e in enumerate(events) if e.event_id == eid)
            events[k] = replace(events[k], output_cell_ids=tuple(out_ids))

    # attachments: clip per removed/converted piece-event (review P1).
    for a in prior.attachments:
        if a.support_instance_id not in survivors_by_instance:
            out_attachments.append(a)          # instance untargeted/unaffected -> PRESERVED
            continue
        if a.support_region_um is not None and not any(
                rect_intersection(a.support_region_um, p) for p, _ in pieces_with_event):
            out_attachments.append(a)          # support outside every piece -> PRESERVED
            continue
        if not a.support_is_exact or a.inventory_integral is None:
            some_event = pieces_with_event[0][1]
            ledger.append(_to_unresolved(
                a, some_event, note=f"{kind} of an attachment with no exact integrable support"))
            continue

        initial = a.exact_inventory_over(a.support_region_um)
        remaining: List[Tuple[Bounds, str]] = [(a.support_region_um, "")]
        moved_by_event: Dict[str, float] = {}
        for piece, eid in pieces_with_event:
            nxt: List[Tuple[Bounds, str]] = []
            for r, cur in remaining:
                overlap = rect_intersection(r, piece)
                if overlap is None:
                    nxt.append((r, cur))
                    continue
                moved_by_event[eid] = moved_by_event.get(eid, 0.0) + (a.exact_inventory_over(overlap) or 0.0)
                for sub in rect_subtract(r, piece):
                    nxt.append((sub, eid))
            remaining = nxt

        kept_total = 0.0
        for r, eid in remaining:
            piece_inv = a.exact_inventory_over(r)
            kept_total += piece_inv or 0.0
            out_attachments.append(replace(
                a, attachment_id=ids.next("att"), support_region_um=r,
                creation_event_id=eid or a.creation_event_id,
                inventory_cm_per_depth=piece_inv))
        moved_total = sum(moved_by_event.values())
        if initial:
            assert abs((kept_total + moved_total) - initial) <= _INV_REL_TOL * abs(initial), (
                f"{kind} inventory not conserved: initial={initial}, "
                f"kept={kept_total}, moved={moved_total}")
        for eid, amt in moved_by_event.items():
            if amt <= _INV_REL_TOL * max(1.0, abs(initial or 0.0)):
                continue
            if kind == "etching":
                k = next(i for i, e in enumerate(events) if e.event_id == eid)
                prev = events[k].inventory_cm_per_depth or 0.0
                events[k] = replace(events[k], inventory_cm_per_depth=prev + amt)
            else:
                ledger.append(UnresolvedInventory(
                    species=a.species, polarity=a.polarity,
                    total_cm_per_depth=amt, quantity_status="KNOWN_EXACT",
                    origin_attachment_id=a.attachment_id, conversion_event_id=eid,
                    note="dopant in the Si volume consumed by oxidation; "
                         "segregation/redistribution not modelled"))

    return WaferStateV2(
        cells=tuple(out_cells), attachments=tuple(out_attachments),
        events=tuple(events), unresolved_inventory=tuple(ledger),
        grid_delta_um=prior.grid_delta_um,
    )


def _apply_etch(prior: WaferStateV2, t: GeometryTransform, ids: _IdGen) -> WaferStateV2:
    return _apply_geometry_change(prior, t, ids, kind="etching")


def _apply_deposition(prior: WaferStateV2, t: GeometryTransform, ids: _IdGen) -> WaferStateV2:
    err = _deposition_error(prior, t)
    if err:
        return _fail_closed(prior, replace(t, representable=False, note=err), ids)
    cells = list(prior.cells)
    events = list(prior.events)
    for material, bounds, new_instance_id in t.added_cells:
        ev = SpatialEvent(
            ids.next("evt"), "ADDED", "deposition", extent_um=bounds,
            note=f"deposited {material} as new instance {new_instance_id}",
        )
        events.append(ev)
        nc = MaterialCell(
            cell_id=ids.next("cell"), material=material, bounds_um=bounds,
            material_instance_id=new_instance_id, lineage=(ev.event_id,),
            lifecycle="ACTIVE", provenance_event_ids=(ev.event_id,),
        )
        cells.append(nc)
        events[-1] = replace(events[-1], output_cell_ids=(nc.cell_id,))
    # NO attachment is auto-connected to a new instance (design doc Sec6B/D).
    return replace(prior, cells=tuple(cells), events=tuple(events))


def _apply_conversion(prior: WaferStateV2, t: GeometryTransform, ids: _IdGen) -> WaferStateV2:
    """Si -> SiO2 over exact converted rectangles, restricted to the
    instances named in `t.input_instance_ids`. Dopant in a converted
    volume goes to `unresolved_inventory` (segregation not modelled) --
    NEVER into the SiO2 or the remaining Si. Mask-protected dopant
    (outside every converted rect) is PRESERVED, clipped to the
    surviving Si."""
    return _apply_geometry_change(prior, t, ids, kind="oxidation")


def _apply_remesh(prior: WaferStateV2, t: GeometryTransform, ids: _IdGen) -> WaferStateV2:
    ev = SpatialEvent(
        ids.next("evt"), "PRESERVED", t.process_category,
        input_cell_ids=tuple(c.cell_id for c in prior.active_cells()),
        output_cell_ids=tuple(c.cell_id for c in prior.active_cells()),
        input_attachment_ids=tuple(a.attachment_id for a in prior.attachments),
        output_attachment_ids=tuple(a.attachment_id for a in prior.attachments),
        note="remesh / geometry sync: instance ids, lineage, and inventory unchanged",
    )
    return replace(prior, events=prior.events + (ev,))


# --------------------------------------------------------------------------
# Building blocks the process/GUI layer uses
# --------------------------------------------------------------------------

def attach_dopant(
    state: WaferStateV2,
    *,
    species: Optional[str],
    polarity: str,
    concentration_at: Callable[[float, float], float],
    support_instance_id: str,
    support_region_um: Optional[Bounds],
    model: str,
    chemical_state: str,
    inventory_integral: Optional[Callable[[Bounds], Optional[float]]] = None,
    model_params: Optional[Dict[str, Any]] = None,
    provenance: Any = None,
    step_seed: str = "",
    refuse_reason: Optional[str] = None,
) -> WaferStateV2:
    """Bind a dopant profile to a specific material instance and 2D
    support.

    An ACTIVE (queryable) attachment is created ONLY when ALL of
    (review P0):
      - `support_instance_id` is an ACTIVE + MODELLED instance right now
      - `support_region_um` is an exact rectangle
      - `inventory_integral` is a real exact-integral callable
      - `support_region_um` lies entirely within that instance's known
        geometry

    Any other request (a LEGACY_UNRESOLVED / UNRESOLVED / nonexistent
    instance; an unknown or out-of-bounds support; no exact integral)
    creates NO active attachment: it records an UNSUPPORTED_BY_MODEL
    doping event and an `unresolved_inventory` ledger entry
    (`total=None`, `UNKNOWN_GEOMETRIC_SUPPORT`), so nothing downstream
    can read an electrical doping number for it.

    `chemical_state` is REQUIRED (no default) and must be exactly one of
    `CHEMICAL_STATES`, else ValueError: an ACTIVE attachment is the only
    kind an electrical query may read; a CHEMICAL/UNKNOWN one is recorded
    but stays electrically unsupported (see `WaferStateV2.net_doping_at`).

    `refuse_reason`, when given, forces the refusal path with that reason
    even though the attachment itself would be possible -- how a caller
    refuses ONE request atomically when a sibling profile of the same
    request cannot be attached (never a partially applied request).
    """
    validate_chemical_state(chemical_state)
    ids = _IdGen(step_seed)
    cells = _active_modelled_cells(state, support_instance_id)
    reason: Optional[str] = refuse_reason
    if reason is not None:
        pass
    elif not cells:
        reason = (f"instance {support_instance_id!r} is not ACTIVE + MODELLED "
                  f"(legacy / unresolved / nonexistent)")
    elif support_region_um is None:
        reason = "support_region_um is unknown (no exact 2D support)"
    elif inventory_integral is None:
        reason = "profile has no exact inventory integral"
    elif not _covered_by(support_region_um, [c.bounds_um for c in cells]):
        reason = "support_region_um extends outside the instance's known geometry"

    if reason is not None:
        ev = SpatialEvent(
            ids.next("evt"), "UNSUPPORTED_BY_MODEL", "doping",
            # The ATTEMPTED support region, when known, scopes this
            # refusal to the rectangle the caller actually meant to
            # dope (P0-C) -- never the whole wafer, and never silently
            # nothing (see _unsupported_covering()'s own doping-level
            # carve-out: a refused doping application is never
            # "un-covered" by an unrelated later ACTIVE MODELLED cell
            # the way a whole-step geometry UNSUPPORTED event can be).
            extent_um=support_region_um,
            model_status="UNSUPPORTED_BY_MODEL",
            note=f"attach_dopant refused an active attachment: {reason}")
        att_id = ids.next("att")
        led = UnresolvedInventory(
            species=species, polarity=polarity, total_cm_per_depth=None,
            quantity_status="UNKNOWN_GEOMETRIC_SUPPORT",
            origin_attachment_id=att_id, conversion_event_id=ev.event_id,
            note=f"doping request not modellable: {reason}")
        return replace(
            state,
            events=state.events + (ev,),
            unresolved_inventory=state.unresolved_inventory + (led,),
        )

    ev = SpatialEvent(
        ids.next("evt"), "ADDED", "doping",
        input_attachment_ids=(), note=f"doping attached to instance {support_instance_id}",
    )
    att = DopantAttachment(
        attachment_id=ids.next("att"), species=species, polarity=polarity,
        chemical_state=chemical_state, concentration_at=concentration_at,
        support_instance_id=support_instance_id, support_region_um=support_region_um,
        creation_event_id=ev.event_id, model=model, inventory_integral=inventory_integral,
        model_params=dict(model_params or {}), provenance=provenance,
        inventory_cm_per_depth=inventory_integral(support_region_um),
    )
    return replace(
        state,
        attachments=state.attachments + (att,),
        events=state.events + (replace(ev, output_attachment_ids=(att.attachment_id,)),),
    )


def initialize_wafer_state(
    *,
    cells: Any,   # iterable of (material, exact_bounds_um, material_instance_id)
    grid_delta_um: float = 0.0,
) -> WaferStateV2:
    """Build a MODELLED initial WaferStateV2 from EXPLICIT geometry.

    Every cell's four bounds (`x_min, x_max, y_min, y_max`, um) come
    directly from an authoritative recipe / domain-construction input
    (a GUI Wafer's width/depth, a CLI process recipe, a prepare_domain
    call). They are NEVER read back from an exported mesh, a y_max
    heuristic, or a material name -- that is `legacy_state_from_v1_cells()`,
    the fail-closed path for a source that has no real y_min.

    This is the ONLY sanctioned way to create a MODELLED 2D state; a
    caller with no explicit substrate bounds must use the legacy path
    and accept `UNSUPPORTED_BY_MODEL` for any electrical query.
    """
    ids = _IdGen("init")
    out_cells: List[MaterialCell] = []
    events: List[SpatialEvent] = []
    seen_instances: set = set()
    for material, bounds, instance_id in cells:
        b = tuple(float(v) for v in bounds)
        if len(b) != 4 or not (b[1] > b[0] and b[3] > b[2]):
            raise ValueError(
                f"initialize_wafer_state: cell {instance_id!r} bounds {bounds!r} "
                f"are not an exact axis-aligned rectangle with positive area")
        if instance_id in seen_instances:
            raise ValueError(f"initialize_wafer_state: duplicate instance id {instance_id!r}")
        seen_instances.add(instance_id)
        ev = SpatialEvent(
            ids.next("evt"), "ADDED", "initial_geometry", extent_um=b,
            note=f"virgin {material} substrate from explicit bounds {b}")
        events.append(ev)
        out_cells.append(MaterialCell(
            cell_id=ids.next("cell"), material=material, bounds_um=b,
            material_instance_id=instance_id, lineage=(ev.event_id,),
            lifecycle="ACTIVE", provenance_event_ids=(ev.event_id,)))
        events[-1] = replace(events[-1], output_cell_ids=(out_cells[-1].cell_id,))
    return WaferStateV2(cells=tuple(out_cells), events=tuple(events), grid_delta_um=grid_delta_um)


def legacy_state_from_v1_cells(
    v1_cells: Any,
    *,
    grid_delta_um: float = 0.0,
    thin_x: Tuple[float, ...] = (),
) -> WaferStateV2:
    """Fail-closed migration of a v1 WaferState's `_cells`
    (x_min/x_max/y_max, NO y_min). Every resulting cell is
    LEGACY_UNRESOLVED with `bounds_um=None` -- NOT a rectangle with a
    guessed floor (design doc Sec7.0). Dopant attached to such a cell
    carries `support_region_um=None` -> inventory None -> device-active
    query UNSUPPORTED_BY_MODEL.
    """
    ids = _IdGen("legacy")
    cells: List[MaterialCell] = []
    events: List[SpatialEvent] = []
    for i, c in enumerate(v1_cells):
        ev = SpatialEvent(
            ids.next("evt"), "UNSUPPORTED_BY_MODEL", "migration",
            model_status="UNSUPPORTED_BY_MODEL",
            note="migrated from a v1 _Cell with no y_min / material lower boundary",
        )
        events.append(ev)
        cells.append(MaterialCell(
            cell_id=ids.next("cell"), material=getattr(c, "material", "?"),
            bounds_um=None,
            material_instance_id=ids.next("inst"),
            lineage=(ev.event_id,), lifecycle="LEGACY_UNRESOLVED",
            provenance_event_ids=(ev.event_id,),
        ))
    state = WaferStateV2(
        cells=tuple(cells), events=tuple(events),
        grid_delta_um=grid_delta_um,
    )
    object.__setattr__(state, "_thin_x_passthrough", tuple(thin_x))
    return state
