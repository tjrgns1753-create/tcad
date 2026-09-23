#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState v2 test 5 (design doc §9): a remesh / geometry-sync step
preserves inventory exactly and leaves a PRESERVED provenance event.

No backend.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.wafer_state_v2 import (
    WaferStateV2, MaterialCell, GeometryTransform, advance, attach_dopant,
    step_inventory_integral,
)


def main():
    s = WaferStateV2(
        cells=(MaterialCell("c1", "Si", (-5.0, 5.0, 0.0, 2.0), "inst_si",
                            lineage=("origin_evt",)),),
        grid_delta_um=0.1,
    )
    s = attach_dopant(
        s, species="P", polarity="donor",
        concentration_at=lambda x, y: 1.0e17 if x < 0 else 3.0e17,  # non-uniform on purpose
        inventory_integral=lambda b: (
            step_inventory_integral(1.0e17, 0.0, "x_le")(b)
            + step_inventory_integral(3.0e17, 0.0, "x_ge")(b)),
        support_instance_id="inst_si", support_region_um=(-5.0, 5.0, 0.0, 2.0),
        model="step_junction_v1", chemical_state="ACTIVE",
    )
    inv_before = tuple(a.inventory_cm_per_depth for a in s.attachments)
    lineage_before = s.cells[0].lineage
    instance_before = s.cells[0].material_instance_id

    s2 = advance(s, GeometryTransform("remesh", representable=True), step_seed="remesh1")

    inv_after = tuple(a.inventory_cm_per_depth for a in s2.attachments)
    assert inv_after == inv_before, (inv_before, inv_after)
    print("[1] dopant inventory bit-unchanged across the remesh")

    assert s2.cells[0].material_instance_id == instance_before
    assert s2.cells[0].lineage == lineage_before
    print("[2] material_instance_id and lineage intact")

    ev = s2.events[-1]
    assert ev.category == "PRESERVED" and ev.process_category == "remesh"
    assert ev.input_attachment_ids == ev.output_attachment_ids
    print("[3] a PRESERVED provenance event is recorded")

    # A remesh must not create any unresolved-inventory entry.
    assert s2.unresolved_inventory == ()
    print("[4] no unresolved-inventory entry created")

    print()
    print("WaferState v2 test 5 PASS -- remesh preserves inventory and provenance")


if __name__ == "__main__":
    main()
