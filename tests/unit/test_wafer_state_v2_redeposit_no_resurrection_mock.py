#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState v2 test 2 (design doc §9): a re-deposited layer does not
resurrect the etched layer's dopant.

dope Si -> etch it all away -> deposit fresh Si over the same x range.
Asserts:
  - the deposited Si has a NEW material_instance_id (!= the etched one)
  - the new instance carries zero dopant attachments
  - the old attachment is not linked to the new instance
  - lineage/provenance distinguish the two Si instances
  - net_doping_at() in the new Si reads 0, no invented value

No backend.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.wafer_state_v2 import (
    WaferStateV2, MaterialCell, GeometryTransform, advance, attach_dopant,
    uniform_inventory_integral,
)


def main():
    s = WaferStateV2(
        cells=(MaterialCell("c1", "Si", (-5.0, 5.0, 0.0, 2.0), "inst_old_si"),),
        grid_delta_um=0.1,
    )
    s = attach_dopant(
        s, species="P", polarity="donor", concentration_at=lambda x, y: 1.0e17,
        inventory_integral=uniform_inventory_integral(1.0e17),
        support_instance_id="inst_old_si", support_region_um=(-5.0, 5.0, 0.0, 2.0),
        model="uniform_v1", chemical_state="ACTIVE",
    )
    old_attachment_id = s.attachments[0].attachment_id

    # Etch the entire doped Si away.
    s = advance(s, GeometryTransform(
        "etching", representable=True,
        removed_extents_um=((-5.0, 5.0, 0.0, 2.0),),
        input_instance_ids=("inst_old_si",)), step_seed="etch")
    assert not s.active_cells(), "all Si should be etched"
    print("[1] doped Si fully etched")

    # Redeposit fresh Si over the identical x range.
    s = advance(s, GeometryTransform(
        "deposition", representable=True,
        added_cells=(("Si", (-5.0, 5.0, 0.0, 2.0), "inst_new_si"),)), step_seed="dep")

    new_cells = [c for c in s.active_cells() if c.material == "Si"]
    assert len(new_cells) == 1
    new_cell = new_cells[0]
    assert new_cell.material_instance_id == "inst_new_si"
    assert new_cell.material_instance_id != "inst_old_si"
    print(f"[2] deposited Si has a NEW instance id ({new_cell.material_instance_id})")

    assert s.attachments_for_instance("inst_new_si") == ()
    print("[3] the new Si instance carries zero dopant attachments")

    # The old attachment must not have migrated onto the new instance.
    assert not any(a.support_instance_id == "inst_new_si" for a in s.attachments), (
        "an old attachment was linked to the freshly-deposited instance")
    assert not any(a.attachment_id == old_attachment_id and a.support_instance_id == "inst_new_si"
                   for a in s.attachments)
    print("[4] the etched layer's attachment is not linked to the new Si")

    # Lineage/provenance distinguish them: the new cell descends from an
    # ADDED deposition event; the old (REMOVED) cell does not share it.
    added_events = [e.event_id for e in s.events if e.category == "ADDED" and e.process_category == "deposition"]
    assert new_cell.lineage and any(eid in new_cell.lineage for eid in added_events)
    old_cell = next(c for c in s.cells if c.material_instance_id == "inst_old_si")
    assert not any(eid in old_cell.provenance_event_ids for eid in added_events)
    print("[5] lineage/provenance distinguish the old Si and the new Si")

    q = s.net_doping_at(0.0, 1.0)
    assert q.net_doping == 0.0 and q.donor_concentration == 0.0
    assert q.physics_status is None
    print("[6] net_doping_at() in the deposited Si reads a real 0 -- nothing resurrected")

    print()
    print("WaferState v2 test 2 PASS -- redeposition does not resurrect dopant")


if __name__ == "__main__":
    main()
