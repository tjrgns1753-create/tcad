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


def probe_mesh_at_point(
    points: "np.ndarray",
    triangles: "np.ndarray",
    tags: "np.ndarray",
    tag_to_name: Dict[int, str],
    x_domain_um: float,
    y_um: float,
    tolerance_um: float,
) -> Optional[Tuple[str, float]]:
    """Nearest REAL BOUNDARY edge (touched by exactly one triangle,
    same definition tcad.device.devsim.mesh_import.import_process_result
    already uses for its own axis-extreme contacts) to (x_domain_um,
    y_um), within tolerance_um. Returns (owning_region_name,
    distance_um), or None if nothing boundary-like is within
    tolerance. Pure geometry -- no file I/O, so Task 2's own test can
    exercise it directly against an in-memory mesh if ever needed,
    and validate_pin_placement() below stays a thin wrapper around it.
    """
    edge_owner_tags: Dict[tuple, List[int]] = defaultdict(list)
    for tri, tag in zip(triangles, tags):
        for edge in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            key = tuple(sorted((int(edge[0]), int(edge[1]))))
            edge_owner_tags[key].append(int(tag))

    target = np.array([x_domain_um, y_um])
    best_dist = None
    best_tag = None
    for edge, owners in edge_owner_tags.items():
        if len(owners) != 1:
            continue  # interior edge, not a real boundary
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
            best_tag = owners[0]

    if best_dist is None or best_dist > tolerance_um:
        return None
    return tag_to_name[best_tag], best_dist


def validate_pin_placement(
    result,
    pin: Pin,
    width_um: float,
    contactable_materials: Set[str],
    tolerance_um: float = 0.05,
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
    """
    import meshio

    x_domain_um = pin.x_um - width_um / 2.0
    y_um = pin.y_um

    mesh = meshio.read(result.volume_mesh_path)
    triangle_block = next((c for c in mesh.cells if c.type == "triangle"), None)
    if triangle_block is None:
        raise PinPlacementError(pin, REASON_OUTSIDE_MESH, "mesh has no triangle cells")
    block_index = mesh.cells.index(triangle_block)
    triangles = triangle_block.data
    tags = mesh.cell_data[result.material_field][block_index]
    points = mesh.points[:, :2]  # (x, y) -- drop any z from a 2D mesh's own convention
    tag_to_name = {region.tag: region.name for region in result.material_regions}

    x_min, x_max = points[:, 0].min(), points[:, 0].max()
    y_min, y_max = points[:, 1].min(), points[:, 1].max()
    if not (x_min <= x_domain_um <= x_max and y_min <= y_um <= y_max):
        raise PinPlacementError(
            pin, REASON_OUTSIDE_MESH,
            f"({pin.x_um:.4f}, {pin.y_um:.4f}) um (wafer coords) is outside the "
            f"mesh's own bounds x=[{x_min:.4f},{x_max:.4f}] "
            f"y=[{y_min:.4f},{y_max:.4f}] (domain coords)",
        )

    found = probe_mesh_at_point(points, triangles, tags, tag_to_name, x_domain_um, y_um, tolerance_um)
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
