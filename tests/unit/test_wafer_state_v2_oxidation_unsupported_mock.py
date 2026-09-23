#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState v2 test 4 (design doc §9): oxidation of doped Si does not
invent active dopant -- it is exposed as UNSUPPORTED_BY_MODEL.

A doped Si cell is partly consumed by a real, representable oxidation
transform. Asserts:
  - no dopant attachment is created in the new SiO2 or the remaining Si
    for the consumed volume
  - an unresolved_inventory ledger entry carries the consumed amount
    (KNOWN_EXACT here, because the support was exact)
  - a device-active-doping query in the converted region returns
    UNSUPPORTED_BY_MODEL, not a number
  - a query in the mask-protected remaining Si still returns the real value
  - total chemical inventory is conserved (kept + ledgered == initial)

Also the fail-closed case: an oxidation with NO representable transform
must ledger everything and invent nothing.

No backend.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.wafer_state_v2 import (
    WaferStateV2, MaterialCell, GeometryTransform, advance, attach_dopant,
    uniform_inventory_integral,
)

C = 1.0e18


def _doped_si():
    s = WaferStateV2(
        cells=(MaterialCell("c1", "Si", (-5.0, 5.0, 0.0, 2.0), "inst_si"),),
        grid_delta_um=0.1,
    )
    return attach_dopant(
        s, species="B", polarity="acceptor", concentration_at=lambda x, y: C,
        inventory_integral=uniform_inventory_integral(C),
        support_instance_id="inst_si", support_region_um=(-5.0, 0.0, 0.0, 2.0),
        model="uniform_v1", chemical_state="ACTIVE",
    )


def main():
    s = _doped_si()
    initial = s.attachments[0].inventory_cm_per_depth

    # Oxidise the top-left corner: x in [-5, 0], y in [1, 2]. The bottom
    # half (y in [0, 1]) stays real Si (mask-protected).
    s2 = advance(s, GeometryTransform(
        "oxidation", representable=True,
        converted_extents_um=((-5.0, 0.0, 1.0, 2.0),),
        input_instance_ids=("inst_si",)), step_seed="ox")

    sio2_cells = [c for c in s2.active_cells() if c.material == "SiO2"]
    assert len(sio2_cells) == 1
    assert sum(len(s2.attachments_for_instance(c.material_instance_id)) for c in sio2_cells) == 0
    print("[1] the new SiO2 carries zero dopant attachments -- nothing placed into it")

    ledger = [u for u in s2.unresolved_inventory if u.origin_attachment_id == s.attachments[0].attachment_id]
    assert len(ledger) == 1
    assert ledger[0].quantity_status == "KNOWN_EXACT"
    assert ledger[0].total_cm_per_depth is not None and ledger[0].total_cm_per_depth > 0
    print(f"[2] unresolved ledger entry: {ledger[0].total_cm_per_depth:.4e} cm^-1, KNOWN_EXACT")

    kept = sum(a.inventory_cm_per_depth for a in s2.attachments)
    ledgered = sum(u.total_cm_per_depth for u in s2.unresolved_inventory)
    assert abs((kept + ledgered) - initial) <= 1e-6 * initial, (kept, ledgered, initial)
    print(f"[3] chemical inventory conserved: kept {kept:.4e} + ledgered {ledgered:.4e} == initial")

    q_converted = s2.net_doping_at(-2.5, 1.5)
    assert q_converted.physics_status is not None
    assert q_converted.physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"
    print("[4] query IN the converted region: UNSUPPORTED_BY_MODEL, not a number")

    q_remaining = s2.net_doping_at(-2.5, 0.5)
    assert q_remaining.physics_status is None
    assert abs(q_remaining.net_doping - (-1.0e18)) < 1.0
    print("[5] query in the mask-protected remaining Si: real value -1e18, no gap")

    # No modelled active attachment was invented for the converted region.
    active_in_converted = [
        a for a in s2.attachments
        if a.support_region_um is not None
        and a.support_region_um[2] >= 1.0 and a.support_region_um[0] < 0.0
    ]
    assert active_in_converted == [], "an active dopant attachment was invented for the converted volume"
    print("[6] zero invented active dopant in the converted volume")

    # --- fail-closed: oxidation with no representable transform ---
    s_fc = advance(_doped_si(), GeometryTransform("oxidation", representable=False), step_seed="fc")
    # item 3: the prior attachment is DROPPED from the active set, kept only in the ledger.
    assert s_fc.attachments == (), "a fail-closed step must not leave the attachment active"
    assert s_fc.unresolved_inventory and all(
        u.quantity_status == "KNOWN_EXACT" for u in s_fc.unresolved_inventory)
    assert any(e.model_status == "UNSUPPORTED_BY_MODEL" for e in s_fc.events)
    assert s_fc.net_doping_at(-2.5, 0.5).physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"
    assert s_fc.net_doping_at(-2.5, 0.5).net_doping is None
    print("[7] fail-closed oxidation (no transform): attachment dropped to ledger, nothing invented")

    print()
    print("WaferState v2 test 4 PASS -- oxidation redistribution stays UNSUPPORTED_BY_MODEL")


if __name__ == "__main__":
    main()
