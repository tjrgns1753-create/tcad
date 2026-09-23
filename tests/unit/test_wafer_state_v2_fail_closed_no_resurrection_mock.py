#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState v2 (review item 3): a fail-closed step permanently
removes the affected attachment from the active set. A later,
perfectly-valid GeometryTransform does not bring it back as numeric
doping.

No backend.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.wafer_state_v2 import (
    WaferStateV2, MaterialCell, GeometryTransform, advance, attach_dopant,
    uniform_inventory_integral,
)


def _doped():
    s = WaferStateV2(
        cells=(MaterialCell("c1", "Si", (-5.0, 5.0, 0.0, 2.0), "inst_si"),), grid_delta_um=0.1)
    return attach_dopant(
        s, species="P", polarity="donor", concentration_at=lambda x, y: 1.0e17,
        inventory_integral=uniform_inventory_integral(1.0e17),
        support_instance_id="inst_si", support_region_um=(-5.0, 5.0, 0.0, 2.0),
        model="uniform_v1", chemical_state="ACTIVE")


def main():
    s = _doped()
    old_id = s.attachments[0].attachment_id

    # A step with NO representable transform: fail-closed.
    s = advance(s, GeometryTransform("etching", representable=False), step_seed="fc")
    assert s.attachments == ()
    assert any(u.origin_attachment_id == old_id for u in s.unresolved_inventory)
    print("[1] fail-closed: the attachment is gone from the active set, ledgered")

    # Now a perfectly valid remesh -- must NOT resurrect it. The old
    # region's geometry is still unresolved after the unmodelled etch,
    # so a query there is UNSUPPORTED (None) -- never the old 1e17.
    s = advance(s, GeometryTransform("remesh", representable=True), step_seed="rm")
    assert s.attachments == (), "a valid remesh resurrected a ledgered attachment"
    q = s.net_doping_at(0.0, 1.0)
    assert q.physics_status is not None and q.net_doping is None
    print("[2] a following valid remesh: old region still UNSUPPORTED, doping not resurrected")

    # A valid representable deposition creates concrete new geometry.
    s = advance(s, GeometryTransform(
        "deposition", representable=True,
        added_cells=(("SiN", (-5.0, 5.0, 2.0, 2.5), "inst_sin"),)), step_seed="dep")
    assert all(a.attachment_id != old_id for a in s.attachments)
    # inside the NEW deposited cell: supported, no doping -> a real 0.
    q_new = s.net_doping_at(0.0, 2.25)
    assert q_new.physics_status is None and q_new.net_doping == 0.0
    # inside the OLD (still unresolved) region: still UNSUPPORTED.
    assert s.net_doping_at(0.0, 1.0).net_doping is None
    print("[3] deposition: new cell queryable (real 0); old region stays UNSUPPORTED; "
          "nothing resurrected")

    # A NEW explicit attach_dopant() on the NEW instance is active there.
    s = attach_dopant(
        s, species="As", polarity="donor", concentration_at=lambda x, y: 2.0e16,
        inventory_integral=uniform_inventory_integral(2.0e16),
        support_instance_id="inst_sin", support_region_um=(-5.0, 5.0, 2.0, 2.5),
        model="uniform_v1", chemical_state="ACTIVE")
    assert len(s.attachments) == 1 and s.attachments[0].species == "As"
    assert abs(s.net_doping_at(0.0, 2.25).net_doping - 2.0e16) < 1.0
    # the OLD region is STILL unsupported -- the new doping did not leak there
    assert s.net_doping_at(0.0, 1.0).net_doping is None
    print("[4] only a fresh explicit attach_dopant() on a real new instance adds active doping")

    print()
    print("WaferState v2 fail-closed test PASS -- no attachment resurrection")


if __name__ == "__main__":
    main()
