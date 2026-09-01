#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Coordinate -> real mesh boundary -> DevSim contact resolution.

Backend-side counterpart to tcad/mesh/pin.py's Pin: this module reads
a REAL process-generated mesh (meshio, same convention
tcad/device/devsim/mesh_import.py already uses) and determines, for
each Pin, whether its (x_um, y_um) WAFER-coordinate position lands on
a real, contactable material boundary -- and if not, WHY (one of the
REASON_* codes below), so a CAD-style error can name the actual
problem instead of a generic import failure.

Kept as its own module rather than folded into mesh_import.py: that
file is already 1000+ lines and heavily exercised by every existing
contact-derivation caller; this module ADDS a new pre-validation layer
in front of it without touching any of that file's existing logic
(mesh_import.py itself only gains two new, additive, opt-in parameters
-- see Task 3/4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from tcad.mesh.pin import Pin

#: A point outside the mesh's own bounding box entirely.
REASON_OUTSIDE_MESH = "outside_mesh"
#: A point that resolves to a real material boundary, but that
#: material is not electrically contactable (e.g. SiO2/Si3N4 -- an
#: insulator, or PHS/Mask -- resist, which never reaches the real mesh
#: at all per this project's own litho-is-state-only design, so a
#: point over resist reports this same reason, not a distinct one --
#: see contact_probe.py's own docstring on probe_mesh_at_point()).
REASON_ON_INSULATOR = "on_insulator"
#: Inside the mesh's bounding box, but not near any boundary edge --
#: e.g. deep inside bulk Si, away from every real contact surface.
REASON_INTERIOR_BULK = "interior_bulk"
#: Inside the mesh's bounding box, near no boundary edge of ANY
#: material within the search tolerance (distinct from
#: REASON_INTERIOR_BULK only in that this project's callers may choose
#: to report it separately for a point that isn't clearly "deep bulk"
#: either, e.g. right at a material-material interface with no outer
#: mesh boundary there).
REASON_NO_BOUNDARY_NEARBY = "no_boundary_nearby"
#: Two (or more) pins resolved to the identical contact position --
#: checked at the multi-pin batch level (resolve_pins_to_point_contacts),
#: never by validate_pin_placement() on a single pin alone.
REASON_DUPLICATE_POSITION = "duplicate_position"


class PinPlacementError(Exception):
    """Raised (or collected, in the batch resolver) when a Pin cannot
    become a real DevSim contact.

    pin : the Pin that failed.
    reason : one of the REASON_* constants above.
    detail : a human-readable, GUI-displayable explanation with real
        numbers (e.g. actual mesh bounds), never a generic message.
    """

    def __init__(self, pin: Pin, reason: str, detail: str):
        self.pin = pin
        self.reason = reason
        self.detail = detail
        super().__init__(f"{pin.name}: {reason} -- {detail}")


from collections import defaultdict
from typing import Dict, List, Set, Tuple

import numpy as np


def boundary_edges_by_tag(
    triangles: "np.ndarray", tags: "np.ndarray",
) -> Dict[int, List[tuple]]:
    """{material tag: [real boundary edge, ...]} -- an edge touched by
    exactly ONE triangle, the same definition
    tcad.device.devsim.mesh_import.import_process_result already uses
    for its own axis-extreme contacts. Pure geometry, no file I/O;
    computed ONCE per mesh and shared by every pin in a batch (see
    resolve_pins_to_point_contacts)."""
    owners: Dict[tuple, List[int]] = defaultdict(list)
    for tri, tag in zip(triangles, tags):
        for edge in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            key = tuple(sorted((int(edge[0]), int(edge[1]))))
            owners[key].append(int(tag))

    by_tag: Dict[int, List[tuple]] = defaultdict(list)
    for edge, edge_owners in owners.items():
        if len(edge_owners) == 1:
            by_tag[edge_owners[0]].append(edge)
    return by_tag


def read_mesh_geometry(result) -> Dict:
    """Everything this module needs from `result`'s REAL mesh, read
    ONCE: {"points", "triangles", "tags", "tag_to_name",
    "boundary_edges_by_tag"}. Passed to validate_pin_placement() so a
    batch of pins costs one meshio.read + one edge-ownership pass
    total, not one per pin."""
    import meshio

    mesh = meshio.read(result.volume_mesh_path)
    triangle_block = next((c for c in mesh.cells if c.type == "triangle"), None)
    if triangle_block is None:
        return {}
    block_index = mesh.cells.index(triangle_block)
    triangles = triangle_block.data
    tags = mesh.cell_data[result.material_field][block_index]
    return {
        # (x, y) -- drop any z from a 2D mesh's own convention
        "points": mesh.points[:, :2],
        "triangles": triangles,
        "tags": tags,
        "tag_to_name": {region.tag: region.name for region in result.material_regions},
        "boundary_edges_by_tag": boundary_edges_by_tag(triangles, tags),
    }


def probe_mesh_at_point(
    points: "np.ndarray",
    triangles: "np.ndarray",
    tags: "np.ndarray",
    tag_to_name: Dict[int, str],
    x_domain_um: float,
    y_um: float,
    tolerance_um: float,
    edges_by_tag: Optional[Dict[int, List[tuple]]] = None,
) -> Optional[Tuple[str, float]]:
    """Nearest REAL BOUNDARY edge (touched by exactly one triangle,
    same definition tcad.device.devsim.mesh_import.import_process_result
    already uses for its own axis-extreme contacts) to (x_domain_um,
    y_um), within tolerance_um. Returns (owning_region_name,
    distance_um), or None if nothing boundary-like is within
    tolerance. Pure geometry -- no file I/O, so Task 2's own test can
    exercise it directly against an in-memory mesh if ever needed,
    and validate_pin_placement() below stays a thin wrapper around it.

    edges_by_tag : optional, already-computed boundary_edges_by_tag()
        output -- pass it to skip recomputing the edge-ownership map
        for every pin in a batch. Purely a cost optimization; the
        result is identical either way.
    """
    if edges_by_tag is None:
        edges_by_tag = boundary_edges_by_tag(triangles, tags)

    target = np.array([x_domain_um, y_um])
    best_dist = None
    best_tag = None
    for tag, edges in edges_by_tag.items():
        for edge in edges:
            p0, p1 = points[edge[0]], points[edge[1]]
            seg = p1 - p0
            seg_len_sq = float(np.dot(seg, seg))
            if seg_len_sq == 0.0:
                t = 0.0
            else:
                t = max(0.0, min(1.0, float(np.dot(target - p0, seg)) / seg_len_sq))
            nearest = p0 + t * seg
            dist = float(np.linalg.norm(target - nearest))
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_tag = tag

    if best_dist is None or best_dist > tolerance_um:
        return None
    return tag_to_name[best_tag], best_dist


def pin_x_domain_um(pin: Pin, points: "np.ndarray") -> float:
    """The single, shared WAFER -> DOMAIN x conversion.

    Derived from the mesh's OWN minimum x, not from a caller-supplied
    wafer width: this project's domains are centered, so the usual
    `x_wafer - width/2` only agrees when the mesh happens to be exactly
    symmetric about 0. It is not always -- a MakeTrench-derived wafer
    with x_extent_um=4.0 really meshes as x=-2.1..+2.1 (CLAUDE.md
    records this), where the two conventions place the same wafer
    coordinate 0.1um apart. min-x + wafer offset is exact regardless of
    centering or padding, so every caller uses this one function."""
    return float(points[:, 0].min()) + pin.x_um


def validate_pin_placement(
    result,
    pin: Pin,
    contactable_materials: Set[str],
    tolerance_um: float = 0.05,
    geometry: Optional[Dict] = None,
) -> str:
    """Resolve one Pin's WAFER-coordinate position to a real,
    contactable material region on `result`'s own mesh. Returns the
    resolved region name on success; raises PinPlacementError
    (REASON_OUTSIDE_MESH / REASON_ON_INSULATOR / REASON_INTERIOR_BULK)
    on failure.

    contactable_materials : the set of MaterialRegion.name values this
        caller considers electrically contactable (e.g. {"Si", "TiN",
        "W", "Cu"} for a real MOSFET) -- deliberately NOT hardcoded
        here, since which materials count as a real conductor/
        semiconductor is a caller-level (GUI/test) decision, not
        something this backend-adjacent module should assume. A
        resolved region NOT in this set is reported as
        REASON_ON_INSULATOR regardless of whether it is physically an
        insulator (SiO2) or simply not one this caller wants to
        contact -- the distinction does not matter to the caller
        either way: neither should become a contact.

    geometry : optional read_mesh_geometry(result) output. Passed by
        resolve_pins_to_point_contacts() so a whole batch of pins
        shares ONE mesh read; omitted (the default) this function
        reads the mesh itself, exactly as before.
    """
    if geometry is None:
        geometry = read_mesh_geometry(result)
    if not geometry:
        raise PinPlacementError(pin, REASON_OUTSIDE_MESH, "mesh has no triangle cells")

    points = geometry["points"]
    x_domain_um = pin_x_domain_um(pin, points)
    y_um = pin.y_um

    x_min, x_max = points[:, 0].min(), points[:, 0].max()
    y_min, y_max = points[:, 1].min(), points[:, 1].max()
    if not (x_min <= x_domain_um <= x_max and y_min <= y_um <= y_max):
        raise PinPlacementError(
            pin, REASON_OUTSIDE_MESH,
            f"({pin.x_um:.4f}, {pin.y_um:.4f}) um (wafer coords) is outside the "
            f"mesh's own bounds x=[{x_min:.4f},{x_max:.4f}] "
            f"y=[{y_min:.4f},{y_max:.4f}] (domain coords)",
        )

    found = probe_mesh_at_point(
        points, geometry["triangles"], geometry["tags"], geometry["tag_to_name"],
        x_domain_um, y_um, tolerance_um, geometry["boundary_edges_by_tag"],
    )
    if found is None:
        raise PinPlacementError(
            pin, REASON_INTERIOR_BULK,
            f"no real material boundary within {tolerance_um}um of "
            f"({pin.x_um:.4f}, {pin.y_um:.4f}) um -- this point is inside bulk "
            f"material, not on a contactable surface",
        )

    region_name, distance_um = found
    if region_name not in contactable_materials:
        raise PinPlacementError(
            pin, REASON_ON_INSULATOR,
            f"nearest boundary ({distance_um:.4f}um away) belongs to {region_name!r}, "
            f"which is not in the contactable set {sorted(contactable_materials)}",
        )
    return region_name


def find_duplicate_pin_positions(pins: List[Pin], tolerance_um: float = 1e-6) -> List[Tuple[Pin, ...]]:
    """Groups of 2+ pins whose (x_um, y_um) positions coincide within
    tolerance_um -- a CAD-style "two electrodes at the same spot" error,
    checked BEFORE any mesh lookup (this is a pure pin-vs-pin check,
    independent of the real mesh). Returns a list of tuples, one tuple
    per colliding group (empty list if every pin is at a distinct
    position)."""
    groups: List[List[Pin]] = []
    for pin in pins:
        placed = False
        for group in groups:
            if abs(group[0].x_um - pin.x_um) < tolerance_um and abs(group[0].y_um - pin.y_um) < tolerance_um:
                group.append(pin)
                placed = True
                break
        if not placed:
            groups.append([pin])
    return [tuple(g) for g in groups if len(g) > 1]


def resolve_pins_to_point_contacts(
    result,
    pins: List[Pin],
    contactable_materials: Set[str],
    radius_um: float = 0.1,
    tolerance_um: float = 0.05,
) -> List[Dict]:
    """A batch of Pins -> the `point_contacts` list
    tcad.device.devsim.mesh_import.import_process_result expects, in
    ONE pass over the real mesh.

    The single source of truth for the whole wafer-coordinate -> real
    DevSim contact conversion: duplicate-position check, wafer->domain
    x conversion (pin_x_domain_um -- mesh min-x based, never a
    caller-supplied width), per-pin boundary/contactability validation,
    and the radius check import_process_result itself performs
    SILENTLY. Every caller (the GUI's electrode panel, the end-to-end
    tests) goes through here, so none of them can drift into its own
    slightly-different copy of any of those steps.

    radius_um : the same radius written into each returned spec, i.e.
        how far from the pin's point a real boundary edge of its own
        region may sit and still be bound into that contact. Checked
        HERE (REASON_NO_BOUNDARY_NEARBY) rather than left to
        import_process_result, which just `continue`s and silently
        produces no contact at all for such a pin.

    Raises PinPlacementError on the FIRST failing pin (a CAD-style
    error naming the pin and the real reason); a caller wanting to
    report every bad pin at once can call validate_pin_placement()
    per pin itself.
    """
    duplicates = find_duplicate_pin_positions(pins)
    if duplicates:
        group = duplicates[0]
        raise PinPlacementError(
            group[0], REASON_DUPLICATE_POSITION,
            f"pins {' & '.join(p.name for p in group)} are all at "
            f"({group[0].x_um:.4f}, {group[0].y_um:.4f}) um (wafer coords) -- "
            f"two electrodes cannot occupy the same position",
        )

    geometry = read_mesh_geometry(result)
    if not geometry:
        raise PinPlacementError(pins[0], REASON_OUTSIDE_MESH, "mesh has no triangle cells")
    points = geometry["points"]
    name_to_tag = {name: tag for tag, name in geometry["tag_to_name"].items()}

    specs: List[Dict] = []
    for pin in pins:
        region = validate_pin_placement(
            result, pin, contactable_materials, tolerance_um, geometry=geometry,
        )
        x_domain_um = pin_x_domain_um(pin, points)

        # The same midpoint-within-radius test import_process_result's
        # own point_contacts branch runs -- done here so "no boundary
        # edge close enough" is a named error instead of a contact that
        # silently never gets created.
        target = np.array([x_domain_um, pin.y_um])
        region_edges = geometry["boundary_edges_by_tag"].get(name_to_tag[region], [])
        near = [
            edge for edge in region_edges
            if np.linalg.norm((points[edge[0]] + points[edge[1]]) / 2.0 - target) <= radius_um
        ]
        if not near:
            raise PinPlacementError(
                pin, REASON_NO_BOUNDARY_NEARBY,
                f"no {region!r} boundary edge lies within radius_um={radius_um} of "
                f"({pin.x_um:.4f}, {pin.y_um:.4f}) um (wafer coords) -- this pin "
                f"would produce no DevSim contact at all",
            )

        specs.append({
            "name": pin.name, "region": region,
            "x_domain_um": x_domain_um, "y_um": pin.y_um,
            "radius_um": radius_um,
        })
    return specs
