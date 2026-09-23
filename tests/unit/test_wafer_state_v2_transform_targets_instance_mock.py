#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState v2 (review item 4): an etch / oxidation transform changes
ONLY the material instances named in `input_instance_ids`.

Two separate Si instances side by side, both doped. An etch whose
removed extent spatially spans BOTH, but whose `input_instance_ids`
names only one, must:
  - REMOVE geometry / clip doping only for the named instance
  - leave the other instance's geometry, attachment, and inventory
    bit-identical (PRESERVED), even though the removed rectangle
    overlaps it
  - point each surviving attachment's provenance at the event that
    actually changed ITS instance

Also: a transform with empty / non-existent `input_instance_ids`, or
with overlapping / zero-area extents, must fail closed.

No backend.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.wafer_state_v2 import (
    WaferStateV2, MaterialCell, GeometryTransform, advance, attach_dopant,
    uniform_inventory_integral,
)

CA, CB = 1.0e17, 4.0e17


def _two_instances():
    s = WaferStateV2(
        cells=(
            MaterialCell("cA", "Si", (-5.0, 0.0, 0.0, 2.0), "inst_A"),
            MaterialCell("cB", "Si", (0.0, 5.0, 0.0, 2.0), "inst_B"),
        ),
        grid_delta_um=0.1,
    )
    s = attach_dopant(
        s, species="P", polarity="donor", concentration_at=lambda x, y: CA,
        inventory_integral=uniform_inventory_integral(CA),
        support_instance_id="inst_A", support_region_um=(-5.0, 0.0, 0.0, 2.0),
        model="uniform_v1", chemical_state="ACTIVE")
    s = attach_dopant(
        s, species="As", polarity="donor", concentration_at=lambda x, y: CB,
        inventory_integral=uniform_inventory_integral(CB),
        support_instance_id="inst_B", support_region_um=(0.0, 5.0, 0.0, 2.0),
        model="uniform_v1", chemical_state="ACTIVE")
    return s


def main():
    s = _two_instances()
    b_att_before = next(a for a in s.attachments if a.support_instance_id == "inst_B")
    b_inv_before = b_att_before.inventory_cm_per_depth
    b_cell_before = next(c for c in s.active_cells() if c.material_instance_id == "inst_B")

    # Etch a rectangle that spans BOTH instances (x -2..3), but target inst_A only.
    s2 = advance(s, GeometryTransform(
        "etching", representable=True,
        removed_extents_um=((-2.0, 3.0, 0.0, 2.0),),
        input_instance_ids=("inst_A",)), step_seed="e")

    # inst_B: geometry, attachment, inventory all bit-identical.
    b_cell_after = next(c for c in s2.active_cells() if c.material_instance_id == "inst_B")
    assert b_cell_after.bounds_um == b_cell_before.bounds_um
    assert b_cell_after.lifecycle == "ACTIVE"
    b_atts_after = [a for a in s2.attachments if a.support_instance_id == "inst_B"]
    assert len(b_atts_after) == 1
    assert b_atts_after[0].support_region_um == b_att_before.support_region_um
    assert b_atts_after[0].inventory_cm_per_depth == b_inv_before
    assert b_atts_after[0].attachment_id == b_att_before.attachment_id  # untouched -> not re-minted
    assert not any(u.origin_attachment_id == b_att_before.attachment_id
                   for u in s2.unresolved_inventory)
    print("[1] the untargeted instance (inst_B) is PRESERVED bit-for-bit, "
          "despite the removed rectangle overlapping it")

    # inst_A: was actually etched.
    a_atts_after = [a for a in s2.attachments if a.support_instance_id == "inst_A"]
    assert a_atts_after, "inst_A should still have a surviving clipped attachment"
    a_event = next(e for e in s2.events if e.category == "REMOVED")
    assert "inst_A" in a_event.note
    # each surviving inst_A attachment's provenance points at the event that changed inst_A
    for a in a_atts_after:
        assert a.creation_event_id == a_event.event_id
    # the event's extent is the real removed intersection with inst_A's cell
    # (x -2..0, not the whole -5..0 cell and not the whole -2..3 rectangle)
    assert a_event.extent_um == (-2.0, 0.0, 0.0, 2.0), a_event.extent_um
    print("[2] the targeted instance (inst_A) is etched; event.extent_um is the "
          "real intersection rectangle; attachment provenance points at that event")

    # --- fail-closed cases ---
    for bad, why in [
        (GeometryTransform("etching", representable=True,
                           removed_extents_um=((-1.0, 1.0, 0.0, 2.0),),
                           input_instance_ids=()), "empty input_instance_ids"),
        (GeometryTransform("etching", representable=True,
                           removed_extents_um=((-1.0, 1.0, 0.0, 2.0),),
                           input_instance_ids=("inst_nonexistent",)), "nonexistent instance"),
        (GeometryTransform("etching", representable=True,
                           removed_extents_um=((-1.0, 1.0, 0.0, 2.0), (0.0, 2.0, 0.0, 2.0)),
                           input_instance_ids=("inst_A",)), "overlapping extents"),
        (GeometryTransform("etching", representable=True,
                           removed_extents_um=((1.0, 1.0, 0.0, 2.0),),
                           input_instance_ids=("inst_A",)), "zero-area extent"),
    ]:
        r = advance(_two_instances(), bad, step_seed="bad")
        assert r.attachments == (), f"{why}: should have failed closed (attachments dropped)"
        assert any(e.model_status == "UNSUPPORTED_BY_MODEL" for e in r.events), why
    print("[3] empty / nonexistent instances, overlapping extents, zero-area extents: all fail closed")

    print()
    print("WaferState v2 transform-targets-instance test PASS")


if __name__ == "__main__":
    main()
