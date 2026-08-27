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
