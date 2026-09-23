#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState v2 (review item 2): an UNSUPPORTED / LEGACY query returns
None for ALL THREE concentration values, not 0.0.

0.0 is the physical claim "known un-doped here". Where the model does
not know the dopant state, it must say None.

No backend.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tcad.physics.wafer_state_v2 import (
    WaferStateV2, MaterialCell, GeometryTransform, advance, attach_dopant,
    legacy_state_from_v1_cells, uniform_inventory_integral,
)
from tcad.physics.wafer_state import _Cell


def _assert_all_none(q, label):
    assert q.physics_status is not None
    assert q.physics_status["resolution"] == "UNSUPPORTED_BY_MODEL"
    assert q.donor_concentration is None, f"{label}: donor {q.donor_concentration!r} != None"
    assert q.acceptor_concentration is None, f"{label}: acceptor {q.acceptor_concentration!r} != None"
    assert q.net_doping is None, f"{label}: net {q.net_doping!r} != None"


def main():
    # --- LEGACY_UNRESOLVED point ---
    leg = legacy_state_from_v1_cells([_Cell(-5.0, 5.0, 2.0, "Si")], grid_delta_um=0.1)
    _assert_all_none(leg.net_doping_at(0.0, 1.0), "legacy")
    print("[1] query in a LEGACY_UNRESOLVED cell: donor/acceptor/net all None")

    # --- point covered by an UNSUPPORTED_BY_MODEL oxidation event ---
    s = WaferStateV2(
        cells=(MaterialCell("c1", "Si", (-5.0, 5.0, 0.0, 2.0), "inst_si"),), grid_delta_um=0.1)
    s = attach_dopant(
        s, species="B", polarity="acceptor", concentration_at=lambda x, y: 1.0e18,
        inventory_integral=uniform_inventory_integral(1.0e18),
        support_instance_id="inst_si", support_region_um=(-5.0, 5.0, 0.0, 2.0),
        model="uniform_v1", chemical_state="ACTIVE")
    s = advance(s, GeometryTransform(
        "oxidation", representable=True, converted_extents_um=((-5.0, 0.0, 1.0, 2.0),),
        input_instance_ids=("inst_si",)), step_seed="ox")
    _assert_all_none(s.net_doping_at(-2.5, 1.5), "converted region")
    print("[2] query in an oxidation-converted region: donor/acceptor/net all None")

    # --- fail-closed whole-step UNSUPPORTED ---
    s_fc = advance(
        WaferStateV2(cells=(MaterialCell("c1", "Si", (-5.0, 5.0, 0.0, 2.0), "inst_si"),)),
        GeometryTransform("etching", representable=False), step_seed="fc")
    _assert_all_none(s_fc.net_doping_at(0.0, 1.0), "fail-closed")
    print("[3] query after a fail-closed step: donor/acceptor/net all None")

    # --- a genuinely un-doped but supported point still returns 0.0, not None ---
    ok = WaferStateV2(
        cells=(MaterialCell("c1", "Si", (-5.0, 5.0, 0.0, 2.0), "inst_si"),))
    q_ok = ok.net_doping_at(0.0, 1.0)
    assert q_ok.physics_status is None
    assert q_ok.donor_concentration == 0.0 and q_ok.acceptor_concentration == 0.0
    assert q_ok.net_doping == 0.0
    print("[4] a supported, genuinely un-doped point still returns 0.0 (known un-doped)")

    print()
    print("WaferState v2 unsupported-None test PASS -- unknown state is None, not 0")


if __name__ == "__main__":
    main()
