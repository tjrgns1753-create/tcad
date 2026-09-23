#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState v2 (review P1): structural validation of a
`representable=True` GeometryTransform. Each of these must fail closed
(no modelled change, an UNSUPPORTED_BY_MODEL event, attachments dropped).

No backend.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.wafer_state_v2 import (
    WaferStateV2, MaterialCell, GeometryTransform, advance, attach_dopant,
    uniform_inventory_integral,
)


def _base():
    s = WaferStateV2(
        cells=(
            MaterialCell("c_si", "Si", (-5.0, 5.0, 0.0, 2.0), "inst_si"),
            MaterialCell("c_ox", "SiO2", (-5.0, 5.0, 2.0, 2.3), "inst_ox"),
        ),
        grid_delta_um=0.1,
    )
    return attach_dopant(
        s, species="P", polarity="donor", concentration_at=lambda x, y: 1.0e17,
        inventory_integral=uniform_inventory_integral(1.0e17),
        support_instance_id="inst_si", support_region_um=(-5.0, 5.0, 0.0, 2.0),
        model="uniform_v1", chemical_state="ACTIVE")


def _is_fail_closed(state):
    return (state.attachments == ()
            and any(e.category == "UNSUPPORTED_BY_MODEL" for e in state.events))


CASES = [
    ("input_instance not ACTIVE+MODELLED (converted lifecycle)",
     lambda: GeometryTransform("etching", representable=True,
                               removed_extents_um=((-1.0, 1.0, 0.0, 2.0),),
                               input_instance_ids=("inst_missing",))),
    ("oxidation target is not Si",
     lambda: GeometryTransform("oxidation", representable=True,
                               converted_extents_um=((-1.0, 1.0, 2.0, 2.3),),
                               input_instance_ids=("inst_ox",))),
    ("deposition added_cell has non-positive area",
     lambda: GeometryTransform("deposition", representable=True,
                               added_cells=(("SiN", (1.0, 1.0, 2.3, 2.8), "inst_new"),))),
    ("deposition new_instance_id collides with an existing instance",
     lambda: GeometryTransform("deposition", representable=True,
                               added_cells=(("SiN", (-5.0, 5.0, 2.3, 2.8), "inst_si"),))),
    ("deposition new_instance_id duplicated within the transform",
     lambda: GeometryTransform("deposition", representable=True,
                               added_cells=(("SiN", (-5.0, 0.0, 2.3, 2.8), "dup"),
                                            ("SiN", (0.0, 5.0, 2.3, 2.8), "dup")))),
    ("deposition output_instance_ids does not match added instances",
     lambda: GeometryTransform("deposition", representable=True,
                               added_cells=(("SiN", (-5.0, 5.0, 2.3, 2.8), "inst_new"),),
                               output_instance_ids=("inst_other",))),
]


def main():
    for i, (label, make) in enumerate(CASES, 1):
        result = advance(_base(), make(), step_seed=f"bad{i}")
        assert _is_fail_closed(result), f"case {i} ({label}) did NOT fail closed"
        print(f"[{i}] fail-closed: {label}")

    # And a well-formed transform still works, to prove the gate is not
    # simply rejecting everything.
    ok = advance(_base(), GeometryTransform(
        "deposition", representable=True,
        added_cells=(("SiN", (-5.0, 5.0, 2.3, 2.8), "inst_new"),),
        output_instance_ids=("inst_new",)), step_seed="ok")
    assert any(c.material_instance_id == "inst_new" for c in ok.active_cells())
    assert ok.attachments and ok.attachments[0].species == "P"  # the Si doping survived
    print(f"[{len(CASES) + 1}] a well-formed deposition still applies normally")

    print()
    print("WaferState v2 P1 structural-validation test PASS")


if __name__ == "__main__":
    main()
