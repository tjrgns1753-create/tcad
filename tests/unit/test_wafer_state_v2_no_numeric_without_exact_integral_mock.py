#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState v2 (review P0): an attachment with no exact integral / no
exact support gets NO local numeric query either.

"I do not know the inventory, but I will still hand you an electrical
doping number" is the loophole this closes.

Asserts:
  - a profile with inventory_integral=None over an otherwise-valid
    instance: net_doping_at() donor/acceptor/net all None
  - a profile with support_region_um=None: same
  - attach_dopant() to an UNRESOLVED (post-fail-closed) instance creates
    zero active attachments and no numeric doping anywhere

No backend.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.wafer_state_v2 import (
    WaferStateV2, MaterialCell, GeometryTransform, advance, attach_dopant,
    DopantAttachment, DopingQueryResult, uniform_inventory_integral,
)


def _all_none(q: DopingQueryResult) -> bool:
    return (q.donor_concentration is None and q.acceptor_concentration is None
            and q.net_doping is None and q.physics_status is not None
            and q.physics_status["resolution"] == "UNSUPPORTED_BY_MODEL")


def main():
    # A real ACTIVE MODELLED Si cell.
    base = WaferStateV2(
        cells=(MaterialCell("c1", "Si", (-5.0, 5.0, 0.0, 2.0), "inst_si"),), grid_delta_um=0.1)

    # --- profile with NO exact integral: hand-build the attachment so it
    # bypasses attach_dopant()'s own refusal, then query it. ---
    no_integral = DopantAttachment(
        attachment_id="a_ni", species="P", polarity="donor", chemical_state="CHEMICAL",
        concentration_at=lambda x, y: 9.9e17,          # a real number is available...
        support_instance_id="inst_si", support_region_um=(-5.0, 5.0, 0.0, 2.0),
        creation_event_id="e", model="mystery_model",
        inventory_integral=None,                       # ...but the inventory is unknown
        inventory_cm_per_depth=None)
    s = base.__class__(cells=base.cells, attachments=(no_integral,), grid_delta_um=0.1)
    assert _all_none(s.net_doping_at(0.0, 1.0)), (
        "a no-exact-integral attachment still returned a numeric doping value")
    print("[1] no exact integral: net_doping_at donor/acceptor/net all None")

    # --- profile with UNKNOWN 2D support ---
    no_support = DopantAttachment(
        attachment_id="a_ns", species="B", polarity="acceptor", chemical_state="CHEMICAL",
        concentration_at=lambda x, y: 3.0e17,
        support_instance_id="inst_si", support_region_um=None,
        creation_event_id="e", model="uniform_v1",
        inventory_integral=uniform_inventory_integral(3.0e17),
        inventory_cm_per_depth=None)
    s2 = base.__class__(cells=base.cells, attachments=(no_support,), grid_delta_um=0.1)
    assert _all_none(s2.net_doping_at(0.0, 1.0)), (
        "an unknown-support attachment still returned a numeric doping value")
    print("[2] unknown 2D support: net_doping_at donor/acceptor/net all None")

    # --- attach_dopant() onto an UNRESOLVED instance (post fail-closed) ---
    s3 = advance(base, GeometryTransform("etching", representable=False), step_seed="fc")
    assert s3.attachments == ()
    s3 = attach_dopant(
        s3, species="As", polarity="donor", concentration_at=lambda x, y: 1.0e17,
        inventory_integral=uniform_inventory_integral(1.0e17),
        support_instance_id="inst_si", support_region_um=(-5.0, 5.0, 0.0, 2.0),
        model="uniform_v1", chemical_state="ACTIVE")
    assert s3.attachments == (), "attach_dopant created an active attachment on an UNRESOLVED instance"
    assert any(e.category == "UNSUPPORTED_BY_MODEL" and e.process_category == "doping"
               for e in s3.events)
    assert s3.net_doping_at(0.0, 1.0).net_doping is None
    print("[3] attach_dopant onto an UNRESOLVED instance: 0 active attachments, no numeric doping")

    print()
    print("WaferState v2 P0 test PASS -- no numeric doping without an exact integral / support")


if __name__ == "__main__":
    main()
