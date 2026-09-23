#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState v2 test 9 (design doc §7.0 / §9, added by review): the
v1 -> v2 migration is fail-closed.

A v1 `_Cell` carries x_min/x_max/y_max and NO y_min. Migrating it must
NOT invent a rectangle (no guessed floor). Asserts:
  - the migrated cell is LEGACY_UNRESOLVED, not a MODELLED MaterialCell
  - its bounds_um is None (no rectangle)
  - dopant attached to it has inventory_cm_per_depth == None
    (no numeric atom count invented)
  - the unresolved-inventory ledger entry, if the attachment is later
    touched, carries quantity_status == "UNKNOWN_GEOMETRIC_SUPPORT"
  - a device-active-doping query returns UNSUPPORTED_BY_MODEL
  - the migration provenance SpatialEvent is recorded

No backend.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.wafer_state_v2 import (
    legacy_state_from_v1_cells, attach_dopant, advance, GeometryTransform,
)
from tcad.physics.wafer_state import _Cell  # the real v1 cell shape


def main():
    v1_cells = [
        _Cell(x_min=-5.0, x_max=5.0, y_max=2.0, material="Si"),   # note: no y_min
    ]
    state = legacy_state_from_v1_cells(v1_cells, grid_delta_um=0.1)

    assert len(state.cells) == 1
    cell = state.cells[0]
    assert cell.lifecycle == "LEGACY_UNRESOLVED", cell.lifecycle
    assert cell.is_modelled is False
    assert cell.bounds_um is None, "a rectangle (with a guessed y_min) must NOT be invented"
    print("[1] migrated v1 cell is LEGACY_UNRESOLVED with bounds_um=None")

    assert any(e.category == "UNSUPPORTED_BY_MODEL" and e.process_category == "migration"
               for e in state.events)
    print("[2] a migration provenance event is recorded")

    # attach_dopant() on a LEGACY_UNRESOLVED instance creates NO active
    # attachment (review P0): only a refusal event + a None-quantity
    # ledger entry.
    n_att_before = len(state.attachments)
    state = attach_dopant(
        state, species="P", polarity="donor", concentration_at=lambda x, y: 1.0e17,
        support_instance_id=cell.material_instance_id, support_region_um=None,
        model="uniform_v1", chemical_state="ACTIVE",
    )
    assert len(state.attachments) == n_att_before, (
        "attach_dopant created an active attachment on a legacy cell")
    refusals = [e for e in state.events
                if e.category == "UNSUPPORTED_BY_MODEL" and e.process_category == "doping"]
    assert refusals, "no UNSUPPORTED_BY_MODEL doping event recorded"
    led = [u for u in state.unresolved_inventory
           if u.quantity_status == "UNKNOWN_GEOMETRIC_SUPPORT" and u.species == "P"]
    assert led and led[0].total_cm_per_depth is None, "a numeric inventory was invented"
    print("[3] attach_dopant on a legacy cell: no active attachment, "
          "ledger entry total=None, UNKNOWN_GEOMETRIC_SUPPORT")

    q = state.net_doping_at(0.0, 1.0)
    assert q.physics_status is not None
    assert q.physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"
    assert q.donor_concentration is None and q.acceptor_concentration is None and q.net_doping is None
    print("[4] a device-active-doping query returns UNSUPPORTED_BY_MODEL, all three values None")

    # A later step over the legacy geometry still records unresolved
    # provenance and invents nothing.
    touched = advance(state, GeometryTransform("etching", representable=False), step_seed="e")
    assert touched.attachments == ()
    assert touched.net_doping_at(0.0, 1.0).net_doping is None
    print("[5] a following step: still fail-closed, nothing invented")

    print()
    print("WaferState v2 test 9 PASS -- v1 -> v2 migration is fail-closed, nothing invented")


if __name__ == "__main__":
    main()
