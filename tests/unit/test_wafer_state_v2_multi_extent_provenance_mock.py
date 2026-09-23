#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState v2 (review P1): with one material instance spanning
several cells / several non-overlapping removed extents, each surviving
attachment piece's provenance event must be the rectangle that actually
clipped THAT piece -- not the instance's first or last event.

No backend.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.wafer_state_v2 import (
    WaferStateV2, MaterialCell, GeometryTransform, advance, attach_dopant,
    uniform_inventory_integral, rect_intersection,
)

C = 1.0e17


def main():
    # ONE instance "inst_si", TWO cells (a gap in the middle), fully doped.
    s = WaferStateV2(
        cells=(
            MaterialCell("cL", "Si", (-6.0, -2.0, 0.0, 2.0), "inst_si"),
            MaterialCell("cR", "Si", (2.0, 6.0, 0.0, 2.0), "inst_si"),
        ),
        grid_delta_um=0.1,
    )
    s = attach_dopant(
        s, species="P", polarity="donor", concentration_at=lambda x, y: C,
        inventory_integral=uniform_inventory_integral(C),
        support_instance_id="inst_si", support_region_um=(-6.0, -2.0, 0.0, 2.0),
        model="uniform_v1", chemical_state="ACTIVE")
    s = attach_dopant(
        s, species="P", polarity="donor", concentration_at=lambda x, y: C,
        inventory_integral=uniform_inventory_integral(C),
        support_instance_id="inst_si", support_region_um=(2.0, 6.0, 0.0, 2.0),
        model="uniform_v1", chemical_state="ACTIVE")

    # TWO non-overlapping removed extents, one biting each cell.
    rL = (-5.0, -3.0, 0.0, 2.0)     # bites the left cell
    rR = (3.0, 5.0, 0.0, 2.0)       # bites the right cell
    s2 = advance(s, GeometryTransform(
        "etching", representable=True, removed_extents_um=(rL, rR),
        input_instance_ids=("inst_si",)), step_seed="e")

    removed_events = [e for e in s2.events if e.category == "REMOVED"]
    # exactly two REMOVED events, one per extent, each with the exact
    # intersection rectangle (which here equals the extent itself,
    # since both extents are fully inside their cell).
    ev_extents = sorted(e.extent_um for e in removed_events)
    assert ev_extents == sorted([rL, rR]), ev_extents
    print(f"[1] two REMOVED events, extent_um == the exact intersection rectangles: {ev_extents}")

    ev_by_extent = {e.extent_um: e.event_id for e in removed_events}

    # every surviving attachment piece must point at the event whose
    # removed rectangle is the one adjacent to / responsible for its clip.
    for a in s2.attachments:
        sup = a.support_region_um
        # which removed extent shares an edge with (is responsible for) this piece?
        # -> the one whose rectangle its own cell was clipped by.
        near = rL if sup[0] < 0 else rR
        assert a.creation_event_id == ev_by_extent[near], (
            f"piece {sup} points at {a.creation_event_id}, "
            f"expected the event for {near} ({ev_by_extent[near]})")
        # and the event it points at genuinely borders this piece
        assert rect_intersection(
            (sup[0] - 1e-9, sup[1] + 1e-9, sup[2], sup[3]), near) is not None
    print("[2] each surviving attachment piece's creation_event_id is the event "
          "for the rectangle that actually clipped it (not a shared first/last id)")

    # inventory attributed per event, not lumped:
    for e in removed_events:
        assert e.inventory_cm_per_depth is not None and e.inventory_cm_per_depth > 0
        # each removed rectangle is 2um x 2um -> C * 4um^2
        assert abs(e.inventory_cm_per_depth - C * 4.0 * 1e-8) < 1e-3 * (C * 4.0e-8)
    print("[3] removed inventory is attributed to each event's own rectangle")

    print()
    print("WaferState v2 P1 provenance test PASS")


if __name__ == "__main__":
    main()
